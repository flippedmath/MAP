from django.shortcuts import render
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