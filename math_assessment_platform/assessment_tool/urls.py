from django.urls import path
from django.contrib.auth import views as auth_views
from .views import HomeDashboardView

urlpatterns = [
    path('', HomeDashboardView.as_view(), name='dashboard'),
    path('login/', auth_views.LoginView.as_view(
        template_name='assessment_tool/login.html',
        redirect_authenticated_user=True),
        name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]