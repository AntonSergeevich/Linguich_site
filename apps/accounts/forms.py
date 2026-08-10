from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Role, StudentProfile, User, normalize_phone
from .widgets import PhoneInput


class LoginForm(forms.Form):
    username = forms.CharField(label=_("Email или телефон"), max_length=120)
    password = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("username") or not cleaned.get("password"):
            return cleaned
        self.user = authenticate(
            self.request, username=cleaned["username"], password=cleaned["password"]
        )
        if self.user is None:
            raise ValidationError(_("Неверный email/телефон или пароль."))
        if not self.user.is_active:
            raise ValidationError(_("Аккаунт отключён. Напишите нам, поможем восстановить."))
        return cleaned


class RegistrationForm(forms.Form):
    """Students sign up themselves; staff accounts are created by the owner."""

    first_name = forms.CharField(label=_("Имя"), max_length=80)
    last_name = forms.CharField(label=_("Фамилия"), max_length=80, required=False)
    email = forms.EmailField(label=_("Email"))
    phone = forms.CharField(label=_("Телефон"), max_length=20, widget=PhoneInput)
    password1 = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Повторите пароль"), widget=forms.PasswordInput)
    consent = forms.BooleanField(label=_("Согласен на обработку персональных данных"))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(_("Такой email уже зарегистрирован. Попробуйте войти."))
        return email

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if len(phone) != 12:
            raise ValidationError(_("Проверьте номер телефона."))
        if User.objects.filter(phone=phone).exists():
            raise ValidationError(_("Этот номер уже зарегистрирован."))
        return phone

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password1")
        if password and password != cleaned.get("password2"):
            self.add_error("password2", _("Пароли не совпадают."))
        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                self.add_error("password1", exc.messages[0])
        return cleaned

    def save(self):
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            phone=self.cleaned_data["phone"],
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data.get("last_name", ""),
            role=Role.STUDENT,
        )
        StudentProfile.objects.create(user=user)
        return user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "avatar", "timezone",
                  "notify_email", "notify_telegram"]
        widgets = {"phone": PhoneInput}

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get("phone"))
        if phone and User.objects.filter(phone=phone).exclude(pk=self.instance.pk).exists():
            raise ValidationError(_("Этот номер занят другим аккаунтом."))
        return phone


class StudentDetailsForm(forms.ModelForm):
    class Meta:
        model = StudentProfile
        fields = ["level", "birth_date", "goal", "parent_name", "parent_phone"]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "goal": forms.Textarea(attrs={"rows": 3}),
            "parent_phone": PhoneInput,
        }
