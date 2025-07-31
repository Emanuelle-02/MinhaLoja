from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.core.exceptions import ValidationError
from .models import *


class AdminAccountForm(forms.ModelForm):
    password = forms.CharField(
        label="Nova senha",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Deixe em branco para não alterar a senha."
    )
    password_confirm = forms.CharField(
        label="Confirme a nova senha",
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Repita a senha para confirmação."
    )

    def __init__(self, *args, **kwargs):
        super(AdminAccountForm, self).__init__(*args, **kwargs)
        # Personalizando o help_text do campo username
        self.fields['username'].help_text = (
        "<ul>"
        "<li>Deixe inalterado caso não queira mudar o nome de usuário. Caso queira mudar, lembre-se:</li>"
        "<li>O nome de usuário deve possuir no máximo 150 caracteres. Apenas letras, dígitos e @/./+/-/_ são permitidos.</li>"
        "</ul>"
        )
        
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'phone']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'username': 'Nome de Usuário',
            'email': 'Email',
            'phone': 'Telefone',   
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        # Validar senhas apenas se pelo menos uma foi preenchida
        if password or password_confirm:
            if password != password_confirm:
                raise ValidationError("As senhas não coincidem.")
            if len(password) < 8:
                raise ValidationError("A senha deve ter pelo menos 8 caracteres.")
        
        return cleaned_data