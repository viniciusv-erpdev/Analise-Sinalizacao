"""Public account fields; authorization is assigned exclusively by the service."""
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.db.models.functions import Lower, Trim


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="E-mail", required=True, max_length=254)

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Nome de usuário"
        self.fields["password1"].label = "Senha"
        self.fields["password2"].label = "Confirmação de senha"
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-control"
            field.widget.attrs["autocomplete"] = (
                "new-password" if name.startswith("password") else name
            )
        self.fields["username"].widget.attrs["autofocus"] = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        # Includes legacy values with surrounding spaces. This is validation,
        # not a database uniqueness constraint for concurrent writers.
        if get_user_model().objects.annotate(
            registration_email=Lower(Trim("email"))
        ).filter(registration_email=email).exists():
            raise forms.ValidationError("Já existe uma conta com este e-mail.", code="duplicate_email")
        return email
