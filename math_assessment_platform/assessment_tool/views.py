from django.shortcuts import render, redirect
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Course, UsersInCourse, UserProfile

class HomeDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'assessment_tool/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Tailor data based on the User Roles defined in your Requirements Doc
        if user.user_type == 'Student':
            # Requirements Doc Page 1: Students see assigned courses
            context['courses'] = Course.objects.filter(
                usersincourse__user=user
            )
            context['ongoing_test'] = user.ongoing_assessment
            
        elif user.user_type == 'Teacher':
            # Requirements Doc Page 1: Teachers manage classes
            context['managed_courses'] = Course.objects.filter(
                usersincourse__user=user,
                usersincourse__user_access='Teacher' # Based on your 'user_access' field
            )

        return context


from django.db import transaction
from .forms import TeacherRegistrationForm
from .models import EmailAuthentication
import secrets
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages

def register_teacher(request):
    # If the user is already logged in, don't let them register
    if request.user.is_authenticated:
        messages.info(request, "You are already logged in. Please log out if you wish to register a new account.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = TeacherRegistrationForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # 1. Create the user using your manager method
                    from .models import UserProfile
                    user = UserProfile.objects.create_teacher_user(
                        username=form.cleaned_data['username'],
                        user_email=form.cleaned_data['email'],
                        password=form.cleaned_data['password'],
                        user_first_name=form.cleaned_data['first_name'],
                        user_last_name=form.cleaned_data['last_name'],
                        gender=form.cleaned_data['gender'],
                        organization=form.cleaned_data['organization_name'],
                        user_display_name=form.cleaned_data.get('display_name')
                    )

                    # 2. Populate email_authentication table
                    EmailAuthentication.objects.create(
                        u_id=user.user_id,
                        temp_email=form.cleaned_data['email'],
                        code=secrets.token_urlsafe(20), # Randomized string
                        timeout=timezone.now() + timedelta(minutes=60) # 60 min future
                    )

                return redirect('login')
            except Exception as e:
                form.add_error(None, f"An error occurred during registration: {e}")
    else:
        form = TeacherRegistrationForm()
    
    return render(request, 'assessment_tool/register.html', {'form': form})



from django.shortcuts import render, redirect
from django.utils import timezone
from django.contrib import messages
from .models import EmailAuthentication, UserProfile
from django.utils.timezone import make_aware, is_naive

def verify_email(request):
    # Get the authentication record for this user
    auth_record = EmailAuthentication.objects.filter(u_id=request.user.user_id).first() # user.user_id?
    
    if not auth_record:
        # If no record exists but account is unactivated, something is wrong
        messages.error(request, "If no email_authentication record exists but account is unactivated, something is wrong.")
        return redirect('dashboard')

    # Ensure auth_record.timeout is timezone-aware
    timeout_time = auth_record.timeout
    if is_naive(timeout_time):
        timeout_time = make_aware(timeout_time)

    now = timezone.now()
    remaining_time = timeout_time - now # Now both are aware
    minutes_left = int(remaining_time.total_seconds() // 60)

    if minutes_left <= 0:
        messages.error(request, "Your activation code has expired. Please contact support.")
        # Logic for resending code could go here
    
    if request.method == 'POST':
        input_code = request.POST.get('code')
        
        if input_code == auth_record.code:
            user = request.user
            # Update user profile with the temporary email
            user.user_email = auth_record.temp_email
            user.unactivated_account = False
            user.save()
            
            # Delete all authentication rows for this user
            EmailAuthentication.objects.filter(u_id=user.user_id).delete()
            
            messages.success(request, "Email authenticated successfully!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid code. Please try again.")

    return render(request, 'assessment_tool/verify_email.html', {
        'minutes_left': max(0, minutes_left),
        'temp_email': auth_record.temp_email
    })