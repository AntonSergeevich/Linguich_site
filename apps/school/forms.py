from django import forms
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import normalize_phone
from apps.accounts.widgets import PhoneInput

from . import antispam
from .models import Course, Language, Lead, LeadSource


class HoneypotInput(forms.TextInput):
    """Поле-приманка: в разметке есть, для человека — нет.

    Прячем стилями, а не `type="hidden"` и не `display:none` в CSS-файле:
    внешний файл бот может не загрузить, а инлайновый стиль он видит там же,
    где и поле. `tabindex="-1"` и `aria-hidden` убирают его с дороги у тех,
    кто ходит по форме с клавиатуры или через скринридер.
    """

    def __init__(self, attrs=None):
        base = {
            "autocomplete": "off",
            "tabindex": "-1",
            "aria-hidden": "true",
            "style": (
                "position:absolute!important;left:-9999px!important;"
                "width:1px;height:1px;opacity:0;pointer-events:none"
            ),
        }
        base.update(attrs or {})
        super().__init__(base)


class AntispamFieldsMixin:
    """Скрытые поля защиты: ловушка и подписанная метка времени.

    Метка выдаётся заново при каждой отрисовке — по ней видно, сколько
    времени ушло на заполнение. Проверяются оба поля во вью, здесь только
    разметка, чтобы её нельзя было забыть добавить на новой форме.

    Поля добавляются в `__init__`, а не объявляются на классе: метакласс
    Django собирает поля только с классов-форм, и с обычной подмешки они
    молча не попали бы в форму вообще.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"] = forms.CharField(required=False, widget=HoneypotInput)
        self.fields["form_ts"] = forms.CharField(
            required=False, widget=forms.HiddenInput, initial=antispam.form_timestamp()
        )

    @property
    def antispam_fields(self):
        """Оба поля разом — чтобы в шаблоне была одна строка."""
        return format_html("{}{}", self["company"], self["form_ts"])


class LeadForm(AntispamFieldsMixin, forms.ModelForm):
    """The one form the whole public site funnels into."""

    consent = forms.BooleanField(
        required=True,
        label=_("Согласен на обработку персональных данных"),
        error_messages={"required": _("Без согласия мы не сможем вам перезвонить.")},
    )

    class Meta:
        model = Lead
        fields = ["name", "phone", "email", "message", "language", "course", "preferred_format"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Как к вам обращаться", "autocomplete": "name"}),
            "phone": PhoneInput,
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


class CallbackForm(AntispamFieldsMixin, forms.Form):
    """Two-field version for the sticky «перезвоните мне» widget."""

    name = forms.CharField(max_length=120)
    phone = forms.CharField(max_length=20, widget=PhoneInput)
    consent = forms.BooleanField(required=True)

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data.get("phone"))
        if len(phone) != 12:
            raise forms.ValidationError(_("Проверьте номер телефона."))
        return phone

    def save(self, commit=True):
        # commit=False нужен, чтобы вью успела проставить IP и user-agent
        # до записи — они участвуют в защите от ботов.
        lead = Lead(
            name=self.cleaned_data["name"],
            phone=self.cleaned_data["phone"],
            source=LeadSource.CALLBACK,
        )
        if commit:
            lead.save()
        return lead
