from django.contrib import messages
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, User
from apps.billing.models import Tariff
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify_many
from apps.scheduling.models import Group, LessonStatus
from apps.utils import is_ajax, json_error, json_form_error, json_ok

from . import antispam
from .schematic import build_schematic
from .forms import CallbackForm, LeadForm
from .models import FAQ, Course, Language, Lead, LeadSource, Promo, Review, SiteSettings


def _teachers():
    return (
        User.objects.filter(role__in=[Role.TEACHER, Role.OWNER], is_active=True, teacher_profile__show_on_site=True)
        .select_related("teacher_profile")
        .prefetch_related("teacher_profile__languages")
    )


def home(request):
    starting_soon = (
        Group.objects.filter(is_active=True, starts_on__gte=timezone.localdate())
        .select_related("course", "course__language", "teacher")
        .order_by("starts_on")[:3]
    )
    context = {
        "languages": Language.objects.filter(is_active=True).annotate(
            course_count=Count("courses", filter=Q(courses__is_active=True))
        ),
        "featured_courses": Course.objects.filter(is_active=True, is_featured=True).select_related("language")[:6],
        "teachers": _teachers()[:4],
        "reviews": Review.objects.filter(is_published=True)[:3],
        "faqs": FAQ.objects.filter(is_published=True)[:6],
        "promos": Promo.objects.filter(is_active=True)[:2],
        "starting_soon": starting_soon,
        "schematic": build_schematic(),
        "lead_form": LeadForm(),
    }
    return render(request, "public/home.html", context)


def courses(request):
    queryset = Course.objects.filter(is_active=True).select_related("language")
    language_slug = request.GET.get("language")
    course_format = request.GET.get("format")
    if language_slug:
        queryset = queryset.filter(language__slug=language_slug)
    if course_format:
        queryset = queryset.filter(format=course_format)
    return render(request, "public/courses.html", {
        "courses": queryset,
        "languages": Language.objects.filter(is_active=True),
        "active_language": language_slug or "",
        "active_format": course_format or "",
    })


def course_detail(request, slug):
    course = get_object_or_404(Course.objects.select_related("language"), slug=slug, is_active=True)
    groups = (
        course.groups.filter(is_active=True)
        .select_related("teacher", "location")
        .prefetch_related("slots")
    )
    return render(request, "public/course_detail.html", {
        "course": course,
        "groups": groups,
        "tariffs": Tariff.objects.filter(is_active=True).filter(Q(course=course) | Q(course__isnull=True)),
        "lead_form": LeadForm(initial={"course": course, "language": course.language}),
        "teachers": _teachers().filter(teacher_profile__languages=course.language).distinct()[:4],
    })


def language_detail(request, slug):
    language = get_object_or_404(Language, slug=slug, is_active=True)
    return render(request, "public/language.html", {
        "language": language,
        "courses": language.courses.filter(is_active=True),
        "teachers": _teachers().filter(teacher_profile__languages=language).distinct(),
        "reviews": Review.objects.filter(is_published=True, language=language)[:3],
        "lead_form": LeadForm(initial={"language": language}),
    })


def teachers(request):
    return render(request, "public/teachers.html", {"teachers": _teachers()})


def prices(request):
    return render(request, "public/prices.html", {
        "tariffs": Tariff.objects.filter(is_active=True, is_public=True).select_related("course"),
        "courses": Course.objects.filter(is_active=True).select_related("language"),
        "lead_form": LeadForm(),
    })


def promos(request):
    today = timezone.localdate()
    return render(request, "public/promos.html", {
        "promos": Promo.objects.filter(is_active=True).filter(
            Q(ends_at__isnull=True) | Q(ends_at__gte=today)
        ),
    })


def contacts(request):
    from .models import Location

    return render(request, "public/contacts.html", {
        "locations": Location.objects.filter(is_active=True),
        "lead_form": LeadForm(),
    })


def privacy(request):
    return render(request, "public/privacy.html", {})


def signup(request):
    """Public «записаться» page: pick a language, a format, leave a contact."""
    return render(request, "public/signup.html", {
        "lead_form": LeadForm(initial=request.GET.dict()),
        "languages": Language.objects.filter(is_active=True),
        "teachers": _teachers(),
    })


ACCEPTED = "Заявка принята — перезвоним в течение рабочего дня."


@require_POST
def lead_create(request):
    """Single endpoint behind every form on the site. Always answers JSON."""
    try:
        antispam.check_request(request)
    except antispam.SpamRejected as exc:
        return json_error(str(exc))

    form = LeadForm(request.POST)
    if not form.is_valid():
        return json_form_error(form)

    # Повтор того же номера — почти всегда второй клик по кнопке или
    # перезагрузка страницы. Заводить вторую карточку в CRM незачем,
    # но и пугать человека ошибкой не за что.
    if antispam.find_recent_duplicate(form.cleaned_data["phone"]):
        return json_ok(ACCEPTED)

    lead = form.save(commit=False)
    lead.source = request.POST.get("source") or LeadSource.TRIAL_FORM
    _stamp_origin(lead, request)
    lead.save()
    _alert_staff_about(lead)

    return json_ok(ACCEPTED)


@require_POST
def callback_create(request):
    try:
        antispam.check_request(request)
    except antispam.SpamRejected as exc:
        return json_error(str(exc))

    form = CallbackForm(request.POST)
    if not form.is_valid():
        return json_form_error(form)
    if antispam.find_recent_duplicate(form.cleaned_data["phone"]):
        return json_ok("Спасибо! Наберём вас в ближайшее время.")
    lead = form.save(commit=False)
    _stamp_origin(lead, request)
    lead.save()
    _alert_staff_about(lead)
    return json_ok("Спасибо! Наберём вас в ближайшее время.")


def _stamp_origin(lead, request):
    lead.ip = antispam.client_ip(request)
    lead.user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:200]


def _alert_staff_about(lead):
    # Администраторы разбирают заявки наравне с владелицей — им тоже
    # должно прилетать, иначе смысл роли теряется.
    staff = User.objects.filter(role__in=[Role.OWNER, Role.ADMIN], is_active=True)
    notify_many(
        staff,
        kind=NotificationKind.NEW_LEAD,
        subject="Новая заявка",
        body=f"{lead.name}, {lead.phone}. {lead.get_source_display()}."
             + (f" Комментарий: {lead.message}" if lead.message else ""),
        url="/cabinet/crm/leads/",
        dedupe_key=f"lead:{lead.pk}",
    )
