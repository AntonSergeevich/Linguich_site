from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

from .models import normalize_phone

UserModel = get_user_model()


class EmailOrPhoneBackend(ModelBackend):
    """Authenticate against either the email or the phone field.

    Both identifiers are unique, so the lookup can never be ambiguous. We still
    run ``set_password``-style hashing on a miss to keep timing uniform.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get("email") or kwargs.get("phone")
        if not identifier or not password:
            return None

        identifier = identifier.strip()
        lookup = Q(email__iexact=identifier)
        phone = normalize_phone(identifier)
        if phone:
            lookup |= Q(phone=phone)

        user = UserModel.objects.filter(lookup).first()
        if user is None:
            UserModel().set_password(password)  # equalise timing
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
