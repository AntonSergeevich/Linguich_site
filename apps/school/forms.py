from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import normalize_phone

from .models import Course, Language, Lead, LeadSource


class LeadForm(forms.ModelForm):
    """The one form the whole public site funnels into."""

    consent = forms.BooleanField(
        required=True,
        label=_("Согласен на обработку персональных данных"),
        error_messages={"required": _("Без согласия мы не сможем вам перезвонить.")},
    )
    # Honeypot: a real person never fills a hidden field.
    company = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Lead
        fields = ["name", "phone", "email", "message", "language", "course", "preferred_format"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Как к вам обращаться", "autocomplete": "name"}),
            "phone": forms.TextInput(attrs={"type": "tel", "placeholder": "+7 (___) ___-__-__", "autocomplete": "tel"}),
            "email": forms.EmailInput(attrs={"placeholder": "email (необязательно)", "autocomplete": "email"}),
            "message": forms.Textarea(attrs={"rows": 3, "placeholder": "Что хотите изучать и с какой целью?"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["language"].queryset = Language.objects.filter(is_active=True)
        self.fields["language"].required = False
        self.fields["language"].empty_label = "Любой язык"
        self.fields["course"].queryset = Course.objects.filter(is_active=True)
        self.fields["course"].required = False
        self.fields["course"].empty_label = "Ещё не выбрал"
        self.fields["email"].required = False
        self.fields["message"].required = False

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get("phone"))
        if len(phone) != 12:
            raise forms.ValidationError(_("Похоже, в номере опечатка. Проверьте, пожалуйста."))
        return phone

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("company"):
            raise forms.ValidationError(_("Не удалось отправить заявку."))
        return cleaned


class CallbackForm(forms.Form):
    """Two-field version for the sticky «перезвоните мне» widget."""

    name = forms.CharField(max_length=120)
    phone = forms.CharField(max_length=20)
    consent = forms.BooleanField(required=True)

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get("phone"))
        if len(phone) != 12:
            raise forms.ValidationError(_("Проверьте номер телефона."))
        return phone

    def save(self):
        return Lead.objects.create(
            name=self.cleaned_data["name"],
            phone=self.cleaned_data["phone"],
            source=LeadSource.CALLBACK,
        )
