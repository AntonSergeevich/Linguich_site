from django.contrib import admin

from .models import LessonCharge, Package, Payment, Tariff


@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = ["name", "lessons_count", "price", "price_per_lesson", "validity_days",
                    "is_active", "is_public", "is_featured"]
    list_editable = ["is_active", "is_public", "is_featured"]


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ["student", "lessons_total", "lessons_used", "lessons_left", "price", "issued_on", "status"]
    list_filter = ["status", "issued_on"]
    search_fields = ["student__first_name", "student__last_name", "student__phone"]
    autocomplete_fields = ["student"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["student", "amount", "method", "status", "paid_on", "created_by"]
    list_filter = ["status", "method", "paid_on"]
    search_fields = ["student__first_name", "student__last_name"]
    date_hierarchy = "paid_on"
    autocomplete_fields = ["student"]


admin.site.register(LessonCharge)
