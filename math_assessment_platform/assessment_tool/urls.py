from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('verify/', views.verify_email, name='verify_email'),
    path('dashboard/', views.HomeDashboardView.as_view(), name='dashboard'),
    # path('login/', auth_views.LoginView.as_view(
    #     template_name='assessment_tool/login.html',
    #     redirect_authenticated_user=True),
    #     name='login'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register_teacher, name='register'),
    path('db-viewer/', views.database_viewer, name='db_viewer'),
    path('courses/', views.course_list_view, name='course_list'),
    # 1. The main file explorer page
    path('explorer/', views.file_explorer, name='file_explorer'),
    # 2. AJAX endpoint to get contents for a folder column
    path('get-folder-contents/<int:group_id>/', views.get_folder_contents, name='get_folder_contents'),
    # 3. AJAX endpoint to get the preview/metadata for a specific item
    path('get-item-preview/<str:item_type>/<int:item_id>/', views.get_item_preview, name='get_item_preview'),
    path('create-folder/', views.create_folder, name='create_folder'),
    path('rename-item/', views.rename_item, name='rename_item'),
    path('delete-item/', views.delete_item, name='delete_item'),
    path('trash/restore/', views.restore_trash_item_view, name='restore_trash_item'),
    path('courses/<int:course_id>/', views.course_detail_view, name='course_detail'),
    path('course/<int:course_id>/assessments/', views.assessment_view, name='assessment_view'),
    path('course/<int:course_id>/assessments/create/', views.create_assessment_ajax, name='create_assessment_ajax'),
    path('course/<int:course_id>/assessments/update-status/', views.update_assessment_status_ajax, name='update_assessment_status_ajax'),
    path('courses/api/assessment/<int:assessment_id>/update-window/', views.update_assessment_window_ajax, name='update_assessment_window_ajax'),
    path('courses/api/assessment/<int:assessment_id>/trash/', views.trash_assessment_ajax, name='trash_assessment_ajax'),
    path('courses/api/course/<int:course_id>/reorder-assessments/', views.reorder_assessment_ajax, name='reorder_assessment_ajax'),
    path('course/<int:course_id>/assessment/<int:assessment_id>/setup/', views.assessment_setup_view, name='assessment_setup'),
    path('course/<int:course_id>/assessment/<int:assessment_id>/setup/create-aqg/', views.create_aqg_ajax, name='create_aqg_ajax'),
    path('course/<int:course_id>/assessment/<int:assessment_id>/setup/rename-aqg/', views.rename_aqg_ajax, name='rename_aqg_ajax'),
    path('course/<int:course_id>/assessment/<int:assessment_id>/setup/reorder-aqg/', views.reorder_aqg_ajax, name='reorder_aqg_ajax'),
    path('course/<int:course_id>/assessment/<int:assessment_id>/setup/add-problem/', views.add_problem_to_aqg_ajax, name='add_problem_to_aqg_ajax'),
]