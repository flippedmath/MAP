from django.contrib import admin
from .models import UserProfile, Course, Assessment, Problem

# Register the custom User model
admin.site.register(UserProfile)

# Register your math platform models
@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'status') 

@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'status')

@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = ('id', 'problem_status')