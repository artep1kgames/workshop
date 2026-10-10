
import uuid

from django.conf import settings
from django.db import models, transaction
from django.db.models import Max
from django.db.models.signals import post_delete
from django.dispatch import receiver
from decimal import Decimal


class Product(models.Model):
    name = models.CharField("Название товара", max_length=200)
    is_active = models.BooleanField("Активен", default=True)
    sort_order = models.PositiveIntegerField("Порядок сортировки", default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "Товар"
        verbose_name_plural = "Товары"

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
        verbose_name="Товар",
    )
    name = models.CharField("Название варианта", max_length=200)
    price = models.DecimalField(
        "Цена",
        max_digits=10,
        decimal_places=2,
    )
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        ordering = ["product__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "name"],
                name="unique_variant_name_per_product",
            ),
        ]
        verbose_name = "Вариант товара"
        verbose_name_plural = "Варианты товаров"

    def __str__(self):
        return f"{self.product.name} — {self.name}"


class Report(models.Model):
    date = models.DateField("Дата", unique=True)
    is_closed = models.BooleanField("День закрыт", default=False)
    closed_at = models.DateTimeField(
        "Время закрытия",
        null=True,
        blank=True,
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_reports",
        verbose_name="Кто закрыл",
    )

    class Meta:
        ordering = ["-date"]
        verbose_name = "Дневной отчёт"
        verbose_name_plural = "Дневные отчёты"

    def __str__(self):
        return str(self.date)


class Receipt(models.Model):
    report = models.ForeignKey(
        Report,
        on_delete=models.PROTECT,
        related_name="receipts",
        verbose_name="Дневной отчёт",
    )
    number = models.PositiveIntegerField("Номер чека")
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_receipts",
        verbose_name="Кто создал",
    )
    submission_token = models.UUIDField(
        "Ключ отправки",
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    payment_method = models.CharField(
        "Способ оплаты",
        max_length=10,
        choices=[
            ("cash", "Наличная"),
            ("cashless", "Безналичная"),
        ],
        default="cash",
    )
    

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "number"],
                name="unique_receipt_number_per_day",
            ),
        ]
        verbose_name = "Чек"
        verbose_name_plural = "Чеки"

    def __str__(self):
        return f"Чек №{self.number} от {self.report.date:%d.%m.%Y}"

    def save(self, *args, **kwargs):
        if self.number is None:
            with transaction.atomic():
                last_number = Receipt.objects.filter(
                    report=self.report
                ).aggregate(
                    max_number=Max("number")
                )["max_number"] or 0

                self.number = last_number + 1
                super().save(*args, **kwargs)
            return

        super().save(*args, **kwargs)

    @property
    def total_quantity(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total(self):
        return sum(
            (item.total for item in self.items.all()),
            start=0,
        )


class ReceiptItem(models.Model):
    receipt = models.ForeignKey(
        Receipt,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Чек",
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.PROTECT,
        related_name="receipt_items",
        verbose_name="Вариант товара",
    )
    quantity = models.PositiveIntegerField("Количество")
    price = models.DecimalField(
        "Цена на момент заказа",
        max_digits=10,
        decimal_places=2,
    )

    class Meta:
        ordering = ["variant__product__name", "variant__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["receipt", "variant"],
                name="unique_variant_per_receipt",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="receipt_item_quantity_positive",
            ),
        ]
        verbose_name = "Позиция чека"
        verbose_name_plural = "Позиции чеков"

    def __str__(self):
        return f"{self.variant}: {self.quantity}"

    @property
    def total(self):
        return (self.quantity or 0) * (self.price or Decimal("0.00"))


@receiver(post_delete, sender=Receipt)
def renumber_receipts_after_delete(sender, instance, **kwargs):
    with transaction.atomic():
        receipts = Receipt.objects.filter(
            report_id=instance.report_id
        ).order_by("created_at", "id")

        for number, receipt in enumerate(receipts, start=1):
            if receipt.number != number:
                Receipt.objects.filter(pk=receipt.pk).update(
                    number=number
                )
