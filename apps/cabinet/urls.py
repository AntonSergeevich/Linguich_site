from django.urls import path

from . import owner, student, teacher

app_name = "cabinet"

urlpatterns = [
    path("", student.home_redirect, name="home"),
    path("notifications/", student.notifications, name="notifications"),

    # --- Ученик ----------------------------------------------------------
    path("schedule/", student.schedule, name="schedule"),
    path("homework/", student.homework, name="homework"),
    path("homework/<int:pk>/", student.homework_detail, name="homework_detail"),
    path("homework/<int:pk>/submit/", student.homework_submit, name="homework_submit"),
    path("program/", student.program, name="program"),
    path("payments/", student.payments, name="payments"),
    path("book/", student.book, name="book"),
    path("api/slots/", student.slots_api, name="slots_api"),
    path("api/book/", student.book_api, name="book_api"),
    path("api/lesson/<int:pk>/join/", student.join_api, name="join_api"),
    path("api/lesson/<int:pk>/cancel/", student.cancel_api, name="cancel_api"),

    # --- Преподаватель ---------------------------------------------------
    path("t/", teacher.dashboard, name="teacher_home"),
    path("t/schedule/", teacher.schedule, name="teacher_schedule"),
    path("t/lesson/<int:pk>/", teacher.lesson_detail, name="teacher_lesson"),
    path("t/lesson/<int:pk>/save/", teacher.lesson_save, name="teacher_lesson_save"),
    path("t/lesson/<int:pk>/cancel/", teacher.lesson_cancel, name="teacher_lesson_cancel"),
    path("t/students/", teacher.students, name="teacher_students"),
    path("t/students/<int:pk>/", teacher.student_detail, name="teacher_student"),
    path("t/review/", teacher.review_queue, name="teacher_review"),
    path("t/review/<int:pk>/", teacher.submission_detail, name="teacher_submission"),
    path("t/review/<int:pk>/save/", teacher.submission_review, name="teacher_submission_save"),
    path("t/assignments/create/", teacher.assignment_create, name="teacher_assignment_create"),
    path("t/programs/", teacher.programs, name="teacher_programs"),
    path("t/programs/create/", teacher.program_create, name="teacher_program_create"),
    path("t/programs/<int:pk>/", teacher.program_detail, name="teacher_program"),
    path("t/programs/<int:pk>/modules/create/", teacher.module_create, name="teacher_module_create"),
    path("t/modules/<int:pk>/units/create/", teacher.unit_create, name="teacher_unit_create"),
    path("t/availability/", teacher.availability, name="teacher_availability"),
    path("t/availability/create/", teacher.availability_create, name="teacher_availability_create"),
    path("t/availability/<int:pk>/delete/", teacher.availability_delete, name="teacher_availability_delete"),
    path("t/timeoff/create/", teacher.time_off_create, name="teacher_timeoff_create"),

    # --- Владелец / CRM --------------------------------------------------
    path("crm/", owner.crm_home, name="crm_home"),
    path("crm/leads/", owner.leads, name="crm_leads"),
    path("crm/leads/<int:pk>/update/", owner.lead_update, name="crm_lead_update"),
    path("crm/leads/<int:pk>/convert/", owner.lead_convert, name="crm_lead_convert"),
    path("crm/students/", owner.students, name="crm_students"),
    path("crm/students/<int:pk>/", owner.student_card, name="crm_student"),
    path("crm/students/<int:pk>/update/", owner.student_update, name="crm_student_update"),
    path("crm/students/<int:pk>/enroll/", owner.enrollment_create, name="crm_enroll"),
    path("crm/payments/", owner.payments, name="crm_payments"),
    path("crm/payments/create/", owner.payment_create, name="crm_payment_create"),
    path("crm/packages/create/", owner.package_create, name="crm_package_create"),
    path("crm/debts/remind/", owner.debt_remind, name="crm_debt_remind"),
    path("crm/groups/", owner.groups, name="crm_groups"),
    path("crm/groups/create/", owner.group_create, name="crm_group_create"),
    path("crm/groups/generate/", owner.generate_schedule, name="crm_generate_schedule"),
    path("crm/students/create/", owner.student_create, name="crm_student_create"),
    path("crm/staff/", owner.staff, name="crm_staff"),
    path("crm/staff/create/", owner.staff_create, name="crm_staff_create"),
    path("crm/staff/<int:pk>/update/", owner.staff_update, name="crm_staff_update"),
    path("crm/staff/<int:pk>/delete/", owner.staff_delete, name="crm_staff_delete"),
    # Пароль сбрасывают и ученикам, и сотрудникам — маршрут общий,
    # права разбираются внутри.
    path("crm/accounts/<int:pk>/password/", owner.credentials_reset, name="crm_credentials_reset"),
]
