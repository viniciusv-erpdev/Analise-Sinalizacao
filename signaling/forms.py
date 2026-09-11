from django import forms


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
