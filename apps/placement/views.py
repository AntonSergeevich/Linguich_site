import json

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, User
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify_many
from apps.school.models import Course, Lead, LeadSource
from apps.utils import json_error, json_ok

from . import engine
from .models import LEVEL_COPY, Question, TestSession


def test_page(request):
    return render(request, "public/test.html", {})


def _payload(question):
    return {
        "id": question.pk,
        "level": question.level,
        "prompt": question.prompt,
        "hint": question.hint,
        "options": question.options,
    }


def _session_for(request, session_id):
    session = get_object_or_404(TestSession, pk=session_id)
    owns = (
        (request.user.is_authenticated and session.user_id == request.user.pk)
        or session.session_key == request.session.session_key
    )
    if not owns:
        return None
    return session


@require_POST
def start(request):
    if not request.session.session_key:
        request.session.create()

    session = TestSession.objects.create(
        user=request.user if request.user.is_authenticated else None,
        session_key=request.session.session_key,
        current_level="A2",
    )
    question = engine.next_question(session)
    if question is None:
        return json_error("Банк вопросов пока пуст. Мы уже чиним это.", status=503)

    return json_ok(session=session.pk, total=engine.MAX_QUESTIONS, question=_payload(question))


@require_POST
def answer(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return json_error("Некорректный запрос.")

    session = _session_for(request, data.get("session"))
    if session is None:
        return json_error("Сессия теста не найдена. Начните заново.", status=403)
    if session.is_finished:
        return json_error("Тест уже завершён.")

    question = get_object_or_404(Question, pk=data.get("question"))
    chosen = int(data.get("chosen", -1))
    is_correct, keep_going = engine.register_answer(session, question, chosen, int(data.get("seconds", 0)))

    response = {
        "is_correct": is_correct,
        "correct_index": question.correct_index,
        "explanation": question.explanation,
        "answered": session.total_count,
        "progress": min(100, round(100 * session.total_count / engine.MAX_QUESTIONS)),
    }

    next_q = engine.next_question(session) if keep_going else None
    if next_q is None:
        session.result_level = engine.final_level(session)
        session.finished_at = timezone.now()
        session.save(update_fields=["result_level", "finished_at"])
        response["finished"] = True
        response["result"] = {
            "level": session.result_level,
            "title": session.level_title,
            "message": session.level_message,
            "correct": session.correct_count,
            "total": session.total_count,
            "minutes": session.duration_minutes,
            "skills": session.skill_breakdown(),
        }
        if request.user.is_authenticated and request.user.is_student:
            profile = getattr(request.user, "student_profile", None)
            if profile and not profile.level:
                profile.level = session.result_level
                profile.save(update_fields=["level"])
    else:
        response["finished"] = False
        response["question"] = _payload(next_q)

    return json_ok(**response)


@require_POST
def capture_lead(request):
    """After the result screen: turn a curious visitor into a CRM record."""
    session = _session_for(request, request.POST.get("session"))
    if session is None:
        return json_error("Сессия теста не найдена.", status=403)

    name = (request.POST.get("name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    if not name or not phone:
        return json_error("Заполните имя и телефон.", fields={
            "name": "" if name else "Укажите имя",
            "phone": "" if phone else "Укажите телефон",
        })

    from apps.accounts.models import normalize_phone

    lead = Lead.objects.create(
        name=name,
        phone=normalize_phone(phone),
        source=LeadSource.PLACEMENT_TEST,
        placement_level=session.result_level,
        language=session.language,
        message=f"Результат теста: {session.result_level} ({session.correct_count}/{session.total_count}).",
    )
    session.lead = lead
    session.save(update_fields=["lead"])

    notify_many(
        User.objects.filter(role=Role.OWNER, is_active=True),
        kind=NotificationKind.NEW_LEAD,
        subject=f"Тест уровня: {session.result_level}",
        body=f"{name}, {lead.phone}. Результат {session.result_level}, {session.accuracy}% верных.",
        url="/cabinet/crm/leads/",
        dedupe_key=f"lead:{lead.pk}",
    )
    return json_ok("Спасибо! Скоро свяжемся и пришлём программу.")
