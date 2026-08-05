from django.contrib import admin

from .models import FAQ, Course, Language, Lead, Location, Promo, Review, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ["name", "flag_emoji", "is_active", "sort_order"]
    list_editable = ["is_active", "sort_order"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ["title", "language", "format", "level_range", "price_per_lesson", "is_active", "is_featured"]
    list_filter = ["language", "format", "is_active", "is_featured"]
    list_editable = ["is_active", "is_featured"]
    search_fields = ["title", "summary"]
    prepopulated_fields = {"slug": ("title",)}


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "source", "status", "language", "created_at"]
    list_filter = ["status", "source", "created_at"]
    list_editable = ["status"]
    search_fields = ["name", "phone", "email"]
    date_hierarchy = "created_at"


admin.site.register([Location, Promo, Review, FAQ])
admin.site.site_header = "Лингвич — администрирование"
admin.site.site_title = "Лингвич"
admin.site.index_title = "Управление"
