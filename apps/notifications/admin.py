from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["recipient", "kind", "channel", "status", "scheduled_for", "sent_at"]
    list_filter = ["status", "channel", "kind"]
    search_fields = ["recipient__first_name", "recipient__last_name", "subject"]
    date_hierarchy = "scheduled_for"
