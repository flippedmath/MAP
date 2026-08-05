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
        required=True,
        label="Emails or usernames",
        widget=forms.Textarea(attrs={
            "placeholder": (
                "Paste one or many: student@example.com, other@school.edu "
                "or usernames — commas, semicolons, or new lines"
            ),
            "autocomplete": "off",
            "rows": 2,
            "class": "course-invite-recipients",
            "style": (
                "width:100%;min-height:2.75rem;padding:6px 8px;border:1px solid #cbd5e1;"
                "border-radius:6px;box-sizing:border-box;resize:vertical;"
                "font-family:inherit;font-size:0.85rem;line-height:1.35;"
            ),
        }),
        help_text=(
            "One student, or a list separated by commas, semicolons, or new lines. "
            "Each entry gets its own invitation."
        ),
    )

    def clean_recipient(self):
        from .course_invites import normalize_recipient, parse_invite_recipients

        recipients = parse_invite_recipients(self.cleaned_data.get("recipient"))
        if not recipients:
            raise ValidationError("Enter at least one email address or username.")
        for entry in recipients:
            try:
                normalize_recipient(entry)
            except ValueError as exc:
                raise ValidationError(f"{entry}: {exc}") from exc
        return recipients


class ParentCourseInviteForm(forms.Form):
    student_id = forms.IntegerField(required=True, label="Student")
    parent_email = forms.EmailField(
        required=True,
        label="Parent email",
        widget=forms.EmailInput(attrs={
            "placeholder": "parent@example.com",
            "autocomplete": "off",
        }),
    )

    def clean_parent_email(self):
        return (self.cleaned_data.get("parent_email") or "").strip().lower()


class ParentRegistrationForm(forms.Form):
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