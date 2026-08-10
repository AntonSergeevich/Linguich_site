from django import forms


class PhoneInput(forms.TextInput):
    """Поле телефона в едином виде на всём сайте.

    Маску вешает `initPhoneInputs` в static/js/app.js — он ищет инпуты по
    `type="tel"`, поэтому важно, чтобы все телефонные поля рендерились
    именно так, а не обычным текстовым. `inputmode` открывает на телефоне
    цифровую клавиатуру, `autocomplete` даёт браузеру подставить свой номер.

    Длина: «+7 (999) 123-45-67» — ровно 18 символов, дальше вводить нечего.
    """

    input_type = "tel"

    def __init__(self, attrs=None):
        base = {
            "placeholder": "+7 (___) ___-__-__",
            "autocomplete": "tel",
            "inputmode": "tel",
            "maxlength": "18",
        }
        base.update(attrs or {})
        super().__init__(base)
