
import uuid
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Q, Sum
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models import Case, When, Value, IntegerField
from .models import Product, ProductVariant, Report, Receipt, ReceiptItem


def get_today_report():
    today = timezone.localdate()
    report, _ = Report.objects.get_or_create(date=today)
    return report


@login_required
def index(request):
    report = get_today_report()

    receipts = report.receipts.prefetch_related(
        "items__variant__product"
    ).order_by("-created_at", "-id")

    amount_expression = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )

    totals = ReceiptItem.objects.filter(
        receipt__report=report,
    ).aggregate(
        total_quantity=Sum("quantity"),
        total_amount=Sum(amount_expression),
        cash_amount=Sum(
            amount_expression,
            filter=Q(receipt__payment_method="cash"),
        ),
        cashless_amount=Sum(
            amount_expression,
            filter=Q(receipt__payment_method="cashless"),
        ),
    )

    history = Report.objects.exclude(
        date=report.date
    ).annotate(
        receipt_count=Count("receipts", distinct=True),
        total_quantity=Sum("receipts__items__quantity"),
        total_amount=Sum(
            ExpressionWrapper(
                F("receipts__items__quantity")
                * F("receipts__items__price"),
                output_field=DecimalField(
                    max_digits=14,
                    decimal_places=2,
                ),
            )
        ),
    ).order_by("-date")[:14]

    return render(request, "workplace/index.html", {
        "report": report,
        "receipts": receipts,
        "receipt_count": receipts.count(),
        "total_quantity": totals["total_quantity"] or 0,
        "total_amount": totals["total_amount"] or Decimal("0.00"),
        "cash_amount": totals["cash_amount"] or Decimal("0.00"),
        "cashless_amount": totals["cashless_amount"] or Decimal("0.00"),
        "history": history,
    })


@login_required
def new_receipt(request):
    report = get_today_report()

    if report.is_closed:
        return redirect("index")

    products = get_ordered_products()

    return render(request, "workplace/new_receipt.html", {
        "products": products,
        "submission_token": uuid.uuid4(),
        "report": report,
    })


@login_required
@require_POST
def create_receipt(request):
    report = get_today_report()

    if report.is_closed:
        return HttpResponseBadRequest("День уже закрыт.")

    payment_method = request.POST.get("payment_method", "cash")

    if payment_method not in ("cash", "cashless"):
        return HttpResponseBadRequest("Некорректный способ оплаты.")

    try:
        token = uuid.UUID(request.POST.get("submission_token", ""))
    except (ValueError, AttributeError):
        return HttpResponseBadRequest("Некорректный ключ отправки.")

    existing = Receipt.objects.filter(submission_token=token).first()
    if existing:
        return redirect("index")

    variants = ProductVariant.objects.filter(
        is_active=True,
        product__is_active=True,
    )

    selected = []

    for variant in variants:
        raw_quantity = request.POST.get(f"quantity_{variant.pk}", "0")

        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            return HttpResponseBadRequest("Количество должно быть целым числом.")

        if quantity < 0:
            return HttpResponseBadRequest("Количество не может быть отрицательным.")

        if quantity > 0:
            selected.append((variant, quantity))

    if not selected:
        return HttpResponseBadRequest("Добавь хотя бы одну позицию в чек.")

    try:
        with transaction.atomic():
            report = Report.objects.select_for_update().get(pk=report.pk)

            if report.is_closed or report.date != timezone.localdate():
                return HttpResponseBadRequest("День уже закрыт.")

            existing = Receipt.objects.filter(
                submission_token=token
            ).first()

            if existing:
                return redirect("index")

            last_number = Receipt.objects.filter(
                report=report
            ).aggregate(
                max_number=Max("number")
            )["max_number"]

            receipt = Receipt.objects.create(
                report=report,
                number=(last_number or 0) + 1,
                created_by=request.user,
                submission_token=token,
                payment_method=payment_method,
            )

            ReceiptItem.objects.bulk_create([
                ReceiptItem(
                    receipt=receipt,
                    variant=variant,
                    quantity=quantity,
                    price=variant.price,
                )
                for variant, quantity in selected
            ])

    except IntegrityError:
        return redirect("index")

    return redirect("index")


@login_required
@require_http_methods(["GET", "POST"])
def edit_receipt(request, receipt_id):
    receipt = get_object_or_404(
        Receipt.objects.select_related("report").prefetch_related(
            "items__variant__product"
        ),
        pk=receipt_id,
    )

    if request.method == "POST":
        if receipt.report.is_closed:
            return HttpResponseBadRequest(
                "Нельзя редактировать чек закрытого дня."
            )

        variants = ProductVariant.objects.filter(
            is_active=True,
            product__is_active=True,
        )

        selected = []

        for variant in variants:
            raw_quantity = request.POST.get(
                f"quantity_{variant.pk}", "0"
            )

            try:
                quantity = int(raw_quantity)
            except (TypeError, ValueError):
                return HttpResponseBadRequest(
                    "Количество должно быть целым числом."
                )

            if quantity < 0:
                return HttpResponseBadRequest(
                    "Количество не может быть отрицательным."
                )

            if quantity > 0:
                selected.append((variant, quantity))

        if not selected:
            return HttpResponseBadRequest(
                "В чеке должна быть хотя бы одна позиция."
            )

        with transaction.atomic():
            receipt.items.all().delete()

            ReceiptItem.objects.bulk_create([
                ReceiptItem(
                    receipt=receipt,
                    variant=variant,
                    quantity=quantity,
                    price=variant.price,
                )
                for variant, quantity in selected
            ])

        return redirect("index")

    products = get_ordered_products()

    quantities = {
        item.variant_id: item.quantity
        for item in receipt.items.all()
    }

    return render(request, "workplace/edit_receipt.html", {
        "receipt": receipt,
        "products": products,
        "quantities": quantities,
    })


@login_required
@require_POST
def close_day(request):
    today = timezone.localdate()

    with transaction.atomic():
        report = get_object_or_404(
            Report.objects.select_for_update(),
            date=today,
        )

        if not report.is_closed:
            report.is_closed = True
            report.closed_at = timezone.now()
            report.closed_by = request.user
            report.save(update_fields=[
                "is_closed",
                "closed_at",
                "closed_by",
            ])

    return redirect("index")


@login_required
@require_POST
def reopen_day(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("Недостаточно прав.")

    today = timezone.localdate()

    with transaction.atomic():
        report = get_object_or_404(
            Report.objects.select_for_update(),
            date=today,
        )

        if report.is_closed:
            report.is_closed = False
            report.closed_at = None
            report.closed_by = None
            report.save(update_fields=[
                "is_closed",
                "closed_at",
                "closed_by",
            ])

    return redirect("index")

def get_ordered_products():
    return Product.objects.filter(
        is_active=True,
        variants__is_active=True,
    ).distinct().order_by(
        "sort_order",
        "name",
    ).prefetch_related("variants")
