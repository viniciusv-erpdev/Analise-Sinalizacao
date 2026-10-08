from django import forms

from signaling.characterization import (
    MAX_PGT_ITEMS, MAX_PGT_LENGTH, validate_report_text,
)


class PGTListWidget(forms.Widget):
    template_name = "signaling/widgets/pgt_list.html"

    def value_from_datadict(self, data, files, name):
        if hasattr(data, "getlist"):
            return data.getlist(name)
        return data.get(name, [])

    def format_value(self, value):
        return value if isinstance(value, (list, tuple)) else [""]

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"].update(
            max_items=MAX_PGT_ITEMS,
            max_length=MAX_PGT_LENGTH,
        )
        return context


class PGTListField(forms.Field):
    widget = PGTListWidget

    def clean(self, value):
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise forms.ValidationError("Informe uma lista de locais.")
        if len(value) > MAX_PGT_ITEMS:
            raise forms.ValidationError(f"Informe no máximo {MAX_PGT_ITEMS} locais.")
        result = []
        for item in value:
            if not isinstance(item, str):
                raise forms.ValidationError("Cada local deve ser um texto.")
            validate_report_text(item)
            if len(item) > MAX_PGT_LENGTH:
                raise forms.ValidationError(
                    f"Cada local deve possuir no máximo {MAX_PGT_LENGTH} caracteres."
                )
            if item.strip():
                result.append(item.strip())
        return result


MAX_REPORT_PHOTOS = 10
MAX_REPORT_PHOTO_SIZE_BYTES = 10 * 1024 * 1024
ALLOWED_REPORT_PHOTO_CONTENT_TYPES = {"image/jpeg", "image/png"}


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if not data:
            return []
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        return [single_file_clean(data, initial)]


class SignalingReportForm(forms.Form):
    functional_classification = forms.CharField(
        label="Classificação Funcional das Vias",
        required=False,
        max_length=500,
        validators=[validate_report_text],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    geometric_configuration = forms.CharField(
        label="Configuração Geométrica",
        required=False,
        max_length=500,
        validators=[validate_report_text],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    regulated_speed = forms.CharField(
        label="Velocidade Regulamentada",
        required=False,
        max_length=100,
        validators=[validate_report_text],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    pgts = PGTListField(label="Polos Geradores de Tráfego (PGT)", required=False)

    def characterization_fields(self):
        return [
            self[name] for name in (
                "functional_classification", "geometric_configuration", "regulated_speed",
            )
        ]

    inspection_address = forms.CharField(
        label="Endereço da vistoria",
        max_length=300,
        error_messages={"required": "Este campo é obrigatório."},
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    occurrence_date = forms.DateField(
        label="Data de ocorrência",
        required=False,
        error_messages={"invalid": "Informe uma data válida."},
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    inspection_date = forms.DateField(
        label="Data da vistoria",
        error_messages={
            "required": "Este campo é obrigatório.",
            "invalid": "Informe uma data válida.",
        },
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    study_reason = forms.CharField(
        label="Motivo do estudo",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    study_objective = forms.CharField(
        label="Objetivo do estudo",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    inspector_name = forms.CharField(
        label="Responsável pela vistoria",
        max_length=200,
        error_messages={"required": "Este campo é obrigatório."},
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    photos = MultipleFileField(
        label="Fotos do local",
        required=False,
        widget=MultipleFileInput(attrs={
            "class": "form-control",
            "accept": "image/jpeg,image/png",
        }),
    )

    def clean_photos(self):
        photos = self.cleaned_data["photos"]
        if len(photos) > MAX_REPORT_PHOTOS:
            raise forms.ValidationError(
                f"Envie no máximo {MAX_REPORT_PHOTOS} fotos."
            )

        for photo in photos:
            if photo.size > MAX_REPORT_PHOTO_SIZE_BYTES:
                raise forms.ValidationError(
                    "Cada foto deve possuir no máximo 10 MB."
                )
            if photo.content_type not in ALLOWED_REPORT_PHOTO_CONTENT_TYPES:
                raise forms.ValidationError(
                    "Envie somente fotos nos formatos JPEG ou PNG."
                )
        return photos
