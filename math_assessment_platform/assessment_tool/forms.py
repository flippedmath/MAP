from django import forms
from django.core.exceptions import ValidationError
from .models import UserProfile, EmailAuthentication

class TeacherRegistrationForm(forms.Form):
    GENDER_CHOICES = [('M', 'Male'), ('F', 'Female'), ('O', 'Other')]

    username = forms.CharField(max_length=150, required=True, widget=forms.TextInput(attrs={
            'pattern': '^[a-zA-Z0-9]+$',
            'title': 'Username must be alphanumeric (no underscores or spaces).'
        }))
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
        
        # Check for underscores, forward slashes, and other symbols (and at least 1 character)
        if not username.isalnum():
            raise ValidationError("Usernames must be alphanumeric.")
        
        if len(username) <= 3:
            raise ValidationError("Usernames must contain at least 4 characters.")
        
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


class CourseInviteForm(forms.Form):
    recipient = forms.CharField(
        max_length=255,
        required=True,
        label="Email or username",
        widget=forms.TextInput(attrs={
            "placeholder": "student@example.com or username",
            "autocomplete": "off",
        }),
    )

    def clean_recipient(self):
        return (self.cleaned_data.get("recipient") or "").strip()


class StudentRegistrationForm(forms.Form):
    GENDER_CHOICES = [('M', 'Male'), ('F', 'Female'), ('O', 'Other')]

    username = forms.CharField(max_length=150, required=True, widget=forms.TextInput(attrs={
        'pattern': '^[a-zA-Z0-9]+$',
        'title': 'Username must be alphanumeric (no underscores or spaces).'
    }))
    first_name = forms.CharField(max_length=150, required=True)
    display_name = forms.CharField(max_length=255, required=False)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput, required=True)
    confirm_password = forms.CharField(widget=forms.PasswordInput, required=True)
    gender = forms.ChoiceField(choices=GENDER_CHOICES, required=True)

    def __init__(self, *args, locked_email=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.locked_email = (locked_email or "").strip().lower() or None
        if self.locked_email:
            self.fields['email'].initial = self.locked_email
            self.fields['email'].widget.attrs['readonly'] = True

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if not username or not username.isalnum():
            raise ValidationError("Usernames must be alphanumeric.")
        if len(username) <= 3:
            raise ValidationError("Usernames must contain at least 4 characters.")
        if UserProfile.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already taken.")
        return username.lower()

    def clean_email(self):
        email = (self.cleaned_data.get('email') or "").strip().lower()
        if self.locked_email and email != self.locked_email:
            raise ValidationError("Email must match the invitation.")
        if UserProfile.objects.filter(user_email__iexact=email).exists():
            raise ValidationError("A user with this email already exists.")
        if EmailAuthentication.objects.filter(temp_email__iexact=email).exists():
            raise ValidationError("This email is currently pending authentication for another user.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password != confirm_password:
            raise ValidationError("Passwords do not match.")
        return cleaned_data