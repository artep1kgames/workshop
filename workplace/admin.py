
from django.contrib import admin

from .models import (
    Product,
    ProductVariant,
    Report,
    Receipt,
    ReceiptItem,
)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_editable = ("is_active",)
    search_fields = ("name",)
    list_filter = ("is_active",)
    inlines = [ProductVariantInline]


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "name", "price", "is_active")
    list_editable = ("price", "is_active")
    list_filter = ("product", "is_active")
    search_fields = ("product__name", "name")


class ReceiptItemInline(admin.TabularInline):
    model = ReceiptItem
    extra = 0
    can_delete = False
    readonly_fields = ("variant", "quantity", "price", "total")
    fields = ("variant", "quantity", "price", "total")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("date", "is_closed", "closed_at", "closed_by")
    list_filter = ("is_closed",)
    readonly_fields = ("date", "is_closed", "closed_at", "closed_by")


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "created_at", "created_by")
    list_filter = ("report__date",)
    search_fields = ("id", "created_by__username")
    readonly_fields = (
        "report",
        "created_at",
        "created_by",
        "submission_token",
    )
    inlines = [ReceiptItemInline]


@admin.register(ReceiptItem)
class ReceiptItemAdmin(admin.ModelAdmin):
    list_display = ("receipt", "variant", "quantity", "price", "total")
    list_filter = ("receipt__report__date", "variant__product")
    readonly_fields = ("receipt", "variant", "quantity", "price", "total")
