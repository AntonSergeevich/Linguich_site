from django.contrib import admin

from .models import Assignment, Material, Module, Program, Submission, Unit


class UnitInline(admin.TabularInline):
    model = Unit
    extra = 1


class ModuleInline(admin.TabularInline):
    model = Module
    extra = 1


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ["title", "language", "level", "author", "unit_count", "is_active"]
    list_filter = ["language", "level", "is_active"]
    inlines = [ModuleInline]


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ["title", "program", "order"]
    inlines = [UnitInline]


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ["title", "teacher", "group", "due_at", "max_score", "pending_review_count"]
    list_filter = ["teacher", "due_at"]
    search_fields = ["title"]


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["student", "assignment", "status", "score", "submitted_at"]
    list_filter = ["status"]
    search_fields = ["student__first_name", "student__last_name", "assignment__title"]


admin.site.register([Unit, Material])
