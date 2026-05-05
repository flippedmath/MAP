from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('verify/', views.verify_email, name='verify_email'),
    path('dashboard/', views.HomeDashboardView.as_view(), name='dashboard'),
    path('login/', auth_views.LoginView.as_view(
        template_name='assessment_tool/login.html',
        redirect_authenticated_user=True),
        name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register_teacher, name='register'),
    path('db-viewer/', views.database_viewer, name='db_viewer'),
    path('courses/', views.course_list_view, name='course_list'),
]