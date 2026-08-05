from django.contrib import admin

from .models import (
    Enrollment,
    Group,
    Lesson,
    LessonParticipant,
    RecurringSlot,
    TeacherAvailability,
    TimeOff,
)


class RecurringSlotInline(admin.TabularInline):
    model = RecurringSlot
    extra = 1


class EnrollmentInline(admin.TabularInline):
    model = Enrollment
    extra = 0
    autocomplete_fields = ["student"]


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ["name", "course", "teacher", "level", "capacity", "seats_taken", "schedule_summary", "is_active"]
    list_filter = ["is_active", "mode", "teacher"]
    search_fields = ["name"]
    inlines = [RecurringSlotInline, EnrollmentInline]


class ParticipantInline(admin.TabularInline):
    model = LessonParticipant
    extra = 0
    autocomplete_fields = ["student"]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ["starts_at", "title", "teacher", "mode", "status", "is_trial"]
    list_filter = ["status", "mode", "teacher", "is_trial"]
    date_hierarchy = "starts_at"
    inlines = [ParticipantInline]


admin.site.register([TeacherAvailability, TimeOff, Enrollment])
