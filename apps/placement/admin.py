from django.contrib import admin

from .models import Question, TestAnswer, TestSession


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["prompt", "level", "skill", "correct_option", "is_active"]
    list_filter = ["level", "skill", "is_active", "language"]
    search_fields = ["prompt"]
    list_editable = ["is_active"]


@admin.register(TestSession)
class TestSessionAdmin(admin.ModelAdmin):
    list_display = ["__str__", "result_level", "correct_count", "total_count", "started_at", "lead"]
    list_filter = ["result_level", "started_at"]
    readonly_fields = ["started_at", "finished_at"]


admin.site.register(TestAnswer)
