from django import forms
from django.core.exceptions import ValidationError
from .models import UserProfile, EmailAuthentication

class TeacherRegistrationForm(forms.Form):
    GENDER_CHOICES = [('M', 'Male'), ('F', 'Female'), ('O', 'Other')]

    username = forms.CharField(max_length=150, required=True)
    first_name = forms.CharField(max_length=150, required=True)
    display_name = forms.CharField(max_length=255, required=False)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput, required=True)
    confirm_password = forms.CharField(widget=forms.PasswordInput, required=True)
    gender = forms.ChoiceField(choices=GENDER_CHOICES, required=True)
    organization_name = forms.CharField(max_length=255, required=False)

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if UserProfile.objects.filter(username=username).exists():
            raise ValidationError("This username is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        # Check user_profile table
        if UserProfile.objects.filter(user_email=email).exists():
            raise ValidationError("A user with this email already exists.")
        # Check email_authentication table
        if EmailAuthentication.objects.filter(temp_email=email).exists():
            raise ValidationError("This email is currently pending authentication for another user.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password != confirm_password:
            raise ValidationError("Passwords do not match.")
        return cleaned_data