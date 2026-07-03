from django.shortcuts import render, redirect
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Course, UsersInCourse, UserProfile
from .models import (
    BranchGroup, Assessment, Problem, 
    CustomQuestionDistribution, AssessmentQuestionGroup, 
    CustomQuestionDistribution, 
    QuestionBlock, EntitySegment,
    EntityType, EntityUserInput
)
from .util import get_valid_unique_name, send_to_trash, restore_item_from_trash, calculate_midpoint_order, SymPyAssessmentEngine, get_entity_validator, get_blueprint_for_token, evaluate_and_format_entity
import json
from django.http import JsonResponse

from django.db import transaction
from .forms import TeacherRegistrationForm
from .models import EmailAuthentication
import secrets
import random
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.db import IntegrityError
from django.views.decorators.http import require_POST, require_http_methods
from django.shortcuts import get_object_or_404

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db.models import Case, Value, When, IntegerField
from django.apps import apps
from django.contrib.auth.decorators import user_passes_test

from django.contrib.auth import logout, login, authenticate
from django.contrib.auth.forms import AuthenticationForm # 🆕 Import standard login form
from django.views.decorators.csrf import csrf_exempt

# import iso8601  # or use standard datetime.fromisoformat
from django.utils import timezone
import re
from django.template.loader import render_to_string
import traceback
from django.views.decorators.csrf import csrf_protect

import sympy as sp
from sympy.parsing.latex import parse_latex
# 🎯 WORKAROUND MONKEYPATCH: Trick SymPy into accepting antlr4-python3-runtime 4.13.x
import importlib.metadata
_orig_version = importlib.metadata.version

def patched_version(package_name):
    if package_name == 'antlr4-python3-runtime':
        return '4.11.1'  # Return the exact string SymPy's regex check is looking for
    return _orig_version(package_name)

# Overwrite the metadata version checker at runtime
importlib.metadata.version = patched_version


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
                    try:
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
                        EmailAuthentication.generate_auth_record(user, form.cleaned_data['email'])

                        return redirect('login')

                    except IntegrityError as e:
                        err_msg = str(e)
            
                        if 'unique_lower_user_email' in err_msg or 'user_email' in err_msg:
                            messages.error(request, "That email is already registered. Please use a different one or log in.")
                        elif 'user_username_key' in err_msg or 'unique_lower_username' in err_msg:
                            messages.error(request, "That username is already taken. Please choose another.")
                        else:
                            messages.error(request, "A database error occurred. Please try again.")

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
    auth_record = EmailAuthentication.objects.filter(u_id=request.user).first()
    
    if not auth_record:
        # If no record exists but account is unactivated, something is wrong
        messages.error(request, "If you navigated to a page to authenticate an email. You need to have added a new email first.")
        return redirect('dashboard')

    # Time logic
    timeout_time = auth_record.timeout
    if timezone.is_naive(timeout_time):
        timeout_time = timezone.make_aware(timeout_time)

    remaining_time = timeout_time - timezone.now()
    minutes_left = int(remaining_time.total_seconds() // 60)
    is_expired = minutes_left <= 0

    if request.method == 'POST':    
        if 'change_email' in request.POST:
            new_email = request.POST.get('new_email', '').strip().lower()
            
            if new_email:
                # 1. Check for existence using case-insensitive lookup
                # This covers all bases: 'Existing@Email.com' or 'existing@email.com'
                email_exists = UserProfile.objects.filter(user_email__iexact=new_email).exclude(user_id=request.user.user_id).exists()
                pending_exists = EmailAuthentication.objects.filter(temp_email__iexact=new_email).exclude(u_id=request.user.user_id).exists()

                if email_exists or pending_exists:
                    messages.error(request, f"The email {new_email} is already associated with an account.")
                else:
                    # 2. Proceed with update if unique
                    EmailAuthentication.generate_auth_record(request.user, new_email)
                    messages.success(request, f"Email changed to {new_email}. A new code has been sent.")
                    return redirect('verify_email')

        # If the button 'resend' was pressed
        if 'resend' in request.POST:
            # We use the email currently stored in the auth_record
            if auth_record:
                EmailAuthentication.generate_auth_record(request.user, auth_record.temp_email)
                messages.success(request, "A new activation code has been sent!")
                return redirect('verify_email')

        if 'code' in request.POST:
            input_code = request.POST.get('code')
            if not is_expired and input_code == auth_record.code:
                user = request.user
                user.user_email = auth_record.temp_email
                user.unactivated_account = False
                user.save()
                EmailAuthentication.objects.filter(u_id=user).delete()
                messages.success(request, "Account activated successfully!")
                return redirect('dashboard')
            elif is_expired:
                messages.error(request, "This code has expired. Please resend a new one.")
            else:
                messages.error(request, "Invalid code.")
    
        if 'cancel_activation' in request.POST:
            user = request.user
            # Mark the account as active
            user.unactivated_account = False
            user.save()
            
            # Wipe the pending authentication data
            EmailAuthentication.objects.filter(u_id=user.user_id).delete()
            
            messages.info(request, "Email verification cancelled. Your account is now active with your current email.")
            return redirect('dashboard')

    return render(request, 'assessment_tool/verify_email.html', {
        'minutes_left': max(0, minutes_left),
        'temp_email': auth_record.temp_email,
        'is_expired': is_expired,
        'is_already_active': not request.user.unactivated_account, # True if they are updating email, false if they are a brand new user
        'current_email': request.user.user_email
    })


@user_passes_test(lambda u: u.is_superuser, login_url='/dashboard/')
def database_viewer(request):
    # Get the table selection from the GET request
    table_name = request.GET.get('table', 'user_profile')
    
    # Map the dropdown values to the actual Models
    model_map = {
        'user_profile': UserProfile,
        'email_authentication': EmailAuthentication,
        'course': Course,
        'branch_group': BranchGroup,
        'users_in_course': UsersInCourse,
        'assessment': Assessment,
        'aqg': AssessmentQuestionGroup,
        'cqd': CustomQuestionDistribution,
        'problem': Problem,
        'question_block': QuestionBlock,
        'entity_segment': EntitySegment,
        'entity_type': EntityType,
        'entity_user_input': EntityUserInput,
    }
    
    selected_model = model_map.get(table_name, UserProfile)
    
    # Fetch all data and field names for the headers
    data = selected_model.objects.all()
    headers = [field.name for field in selected_model._meta.fields]
    
    return render(request, 'assessment_tool/db_viewer.html', {
        'data': data,
        'headers': headers,
        'selected_table': table_name
    })


@login_required
def course_list_view(request):
    user = request.user
    user_type = request.user.user_type

    # Extract the optional username filter from GET arguments
    username_filter = request.GET.get('username_filter', '').strip()
    
    # 1. Define the custom status order priority matrix
    status_priority = Case(
        When(status='active', then=Value(1)),
        When(status='template', then=Value(2)),
        When(status='hidden', then=Value(3)),
        When(status='developing', then=Value(4)),
        When(status='closed', then=Value(5)),
        When(status='deleted', then=Value(6)),
        default=Value(7),
        output_field=IntegerField(),
    )
    # Show user owned courses first, then sort by other users
    user_priority = Case(
        When(owner=request.user, then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )

    if user_type == 'IT_Support':
        # Start with the full base queryset
        queryset = Course.objects.all().select_related('branch_location', 'owner')
        
        # Apply the multi-relational filter if active
        if username_filter:
            # 1. Grab only the unique Course IDs that match our criteria
            matching_ids = Course.objects.filter(
                Q(owner__username__iexact=username_filter) |
                Q(usersincourse__user__username__iexact=username_filter)
            ).values_list('id', flat=True) # Extracts just a list of integers/UUIDs

            # 2. Filter the main optimized queryset using those IDs (No global DISTINCT needed!)
            queryset = queryset.filter(id__in=matching_ids)

            # 3. Dynamic Sub-sorting order tailored for the searched target user
            filter_user_priority = Case(
                When(owner__username__iexact=username_filter, then=Value(1)), # Filtered Owner first
                default=Value(2),                                             # Enrolled participant second
                output_field=IntegerField(),
            )
            courses = queryset.annotate(
                ownership_order=filter_user_priority,
                status_order=status_priority
            ).order_by('ownership_order', 'status_order', 'name')
        else:
            # Default sorting rules when no username filter is active
            courses = queryset.annotate(
                user_order=user_priority,
                status_order=status_priority
            ).order_by('user_order', 'status_order', 'name')

    elif user_type == 'Teacher':
        courses = Course.objects.filter(
            Q(owner=user) | Q(status='template')
        ).select_related('owner', 'branch_location').annotate(
            status_order=status_priority
        ).order_by('status_order', 'name')

    elif user_type == 'Student':
        # Student Base Ruleset
        # 1. Look for rows in the 'course' table...
        # 2. Where the 'usersincourse' junction table has a matching user...
        # 3. AND the course's own status is 'active'.
        courses = Course.objects.filter(
            usersincourse__user=user,
            status='active'
        )
    else:
        # forward any other users (i.e. 'Parent') to the dashboard page.
        return redirect('dashboard')


    if request.method == 'POST':
        # Safely extract the filter during the POST thread to pass it down to redirects
        post_username_filter = request.GET.get('username_filter', '').strip()

        # Helper utility to build our sticky redirection string
        def get_sticky_redirect():
            if post_username_filter:
                return redirect(f"/courses/?username_filter={post_username_filter}")
            return redirect('course_list')

        # HANDLE SHORT DESCRIPTION UPDATES
        if 'update_description' in request.POST:
            course_id = request.POST.get('desc_course_id')
            new_desc = request.POST.get('short_description', '').strip()
            course = get_object_or_404(Course, id=course_id)

            # Strict Role & Ownership Verification Checks
            if course.owner != request.user and user_type != 'IT_Support':
                messages.error(request, "Permission Denied. You do not own this course.")
                return get_sticky_redirect()

            # Save clean text changes
            course.short_desc = new_desc if new_desc else None
            course.save()
            
            messages.success(request, f"Successfully updated description for '{course.name}'.")
            return get_sticky_redirect()

        elif 'update_status' in request.POST:
            course_id = request.POST.get('course_id')
            new_status = request.POST.get('new_status')
            course = get_object_or_404(Course, id=course_id)

            # Strict Role Enforcement
            if course.owner != request.user and user_type != 'IT_Support':
                messages.error(request, "Permission Denied.")
                return get_sticky_redirect()

            # Handle the special 'deleted' mutation (Triggers your Trash quarantine)
            if new_status == 'deleted':
                send_to_trash(course.branch_location, request.user)
                messages.success(request, f"Course '{course.name}' moved to Trash.")
                return get_sticky_redirect()

            # Handle recovery out of 'deleted' back to production using your restore logic
            if new_status == 'restore_trigger' and course.status == 'deleted':
                folder = course.branch_location
                allowed_historical_states = ['closed', 'hidden', 'developing']

                # Safety Check: Read directly from what Postgres tracked *before* the trash move
                if folder.previous_status in allowed_historical_states:
                    
                    # Run the engine—it handles setting the status back automatically!
                    restore_item_from_trash(request, folder)
                else:
                    messages.error(
                        request, 
                        f"Cannot restore '{course.name}'. Invalid or missing historical status tracking data."
                    )
                
                return get_sticky_redirect()


            # Standard Status Update Mutations (active, closed, template, hidden)
            course.status = new_status
            course.save()
            messages.success(request, f"Updated '{course.name}' status to {new_status}.")
            return get_sticky_redirect()
        
        # 2. Handling the "Create by Copying"
        if 'copy_course' in request.POST:
            source_id = request.POST.get('source_course_id')
            target_transition = request.POST.get('target_transition') # e.g. 'developing_to_template'
            source_course = get_object_or_404(Course, id=source_id)

            try:
                source_course.duplicate_course(user=user, target_transition=target_transition)
                messages.success(request, f"Successfully branched new course from '{source_course.name}'.")
                return redirect('course_list')
            except:
                messages.error(request, "Permission denied for this specific Course copy operation or associated folder doesn't exist.")
                return redirect('course_list')

        # 3. HANDLE NEW DEVELOPING COURSE
        elif 'create_developing' in request.POST and user.user_type == 'IT_Support':
            name = request.POST.get('course_name')
            desc = request.POST.get('short_description', '')
            
            # CRITICAL: Grab the image file from request.FILES
            image_file = request.FILES.get('course_image')
            
            if name:
                # Pass the image_file to your updated class method
                Course.create_developing(
                    owner=user, 
                    name=name, 
                    short_desc=desc, 
                    image_file=image_file
                )
                messages.success(request, f"New developing course '{name}' created.")
            else:
                messages.error(request, "Course name is required.")
            return get_sticky_redirect()

        elif 'delete_course' in request.POST and user.user_type == 'IT_Support':
            folder_id = request.POST.get('folder_id')
            folder = get_object_or_404(BranchGroup, id=folder_id)
            course = folder.course  # Grab the 1-to-1 course metadata object

            # --- CASE 1: HARD PURGE (Only allowed if already soft-deleted) ---
            if course.status == 'deleted':
                course_name = folder.name
                folder.delete()  # Triggers database CASCADE and physical file deletion signals
                messages.success(request, f"Permanently deleted '{course_name}' and all associated assessments.")
            
            # --- CASE 2: SOFT-DELETE QUARANTINE (For active, template, hidden, developing, closed) ---
            else:                
                # 1. Ship the folder structure over to the physical Trash directory tree
                send_to_trash(folder, request.user)

                # 2. Update the metadata payload status to reflect its quarantine state
                course.status = 'deleted'
                course.save()

                messages.success(request, f"Moved '{folder.name}' to the Trash quarantine folder.")
                
            return get_sticky_redirect()


    return render(request, 'assessment_tool/course_page.html', {
        'courses': courses, 
        'user_type': user_type,
        'username_filter': username_filter
    })


@login_required
@user_passes_test(lambda u: u.user_type in ['Teacher', 'IT_Support'], login_url='/dashboard/')
def file_explorer(request):
    # Get the root folder for the user
    root_folder = BranchGroup.objects.filter(owner=request.user, parent__isnull=True).first()
    
    if not root_folder:
        # Optional: Trigger the folder creation logic here if it's missing
        return render(request, 'assessment_tool/explorer_error.html', {
            'error': "Your folder structure hasn't been initialized. Please contact IT."
        })

    # We pass the root folder initially; Javascript will handle loading sub-columns
    return render(request, 'assessment_tool/explorer.html', {
        'root_folder': root_folder,
    })

# AJAX view to get contents of a specific folder

from django.db.models import Count

def get_folder_contents(request, group_id):
    group = get_object_or_404(BranchGroup, id=group_id, owner=request.user)

    # 1. Update query to select/prefetch 'problem' alongside other types
    # Problems now live inside this single unified query as unique BranchGroup leaves!
    folders_qs = BranchGroup.objects.filter(parent=group)\
        .select_related('parent__parent')\
        .prefetch_related('course', 'assessment', 'cqd', 'aqg', 'problem')\
        .order_by('order')

    # 2. This old lookup can be completely removed or set to empty since 
    # problems are no longer orphans floating inside a directory container row.
    problems_qs = Problem.objects.none() 

    # 3. Check if items exist (now safely driven by folders_qs)
    has_items = folders_qs.exists()

    # 4. Package contents
    contents = {
        'folders': folders_qs,
        'problems': problems_qs, # Kept as empty queryset for backwards compatibility with column.html until Part 2
        'has_items': has_items,
    }

    # Logic to determine if this folder allows creating a child folder
    username = request.user.username
    current_path = group.get_parent_path() + group.name + "/"
    root_sys = f"/Users/{username}_root/"
    
    # Is this folder one of the protected system paths?
    is_protected = (
        current_path == root_sys or 
        current_path.startswith(f"{root_sys}Courses/") or 
        current_path.startswith(f"{root_sys}Standalone Assessments/") or
        current_path.startswith(f"{root_sys}Shared for Collaboration/") or
        current_path.startswith(f"{root_sys}Student Generated Assessments by Course/") or
        current_path.startswith(f"{root_sys}Public/") or 
        current_path.startswith(f"{root_sys}Trash/")
    )

    return render(request, 'assessment_tool/partials/column.html', {
        'contents': contents,
        'parent_id': group.id,
        'level': int(request.GET.get('level', 1)),
        'is_protected': is_protected,
        'current_path': current_path,
    })


from django.http import HttpResponseForbidden

@login_required
def get_item_preview(request, item_type, item_id):
    model_map = {
        'course': Course,
        'assessment': Assessment,
        'problem': Problem,
        'question_selection': CustomQuestionDistribution,
        'assessment_selection': AssessmentQuestionGroup,
    }
    
    model = model_map.get(item_type)
    item = get_object_or_404(model, id=item_id)
    
    # Permissions check: IT_Support sees all, Teachers see owned
    if request.user.user_type != 'IT_Support' and item.owner != request.user:
        return HttpResponseForbidden()

    return render(request, 'assessment_tool/partials/preview.html', {
        'item': item,
        'type': item_type
    })


def create_folder(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    data = json.loads(request.body)
    parent_id = data.get('parent_id')
    requested_name = data.get('name', 'New Folder')

    # Get parent and verify ownership
    parent_folder = get_object_or_404(BranchGroup, id=parent_id, owner=request.user)

    # Check if this IS the root folder (assuming root has no parent)
    is_root = parent_folder.parent is None
    if is_root:
        return JsonResponse({
            'error': 'New folders cannot be created in the Home directory.'
        }, status=403)

    # Security: Check if parent is a protected system folder
    username = request.user.username
    parent_full_path = parent_folder.get_parent_path() + parent_folder.name + "/"
    
    root = f"/Users/{username}_root/"
    # Block creation inside Courses or Standalone Assessments
    if parent_full_path.startswith(f"{root}Courses/") or \
       parent_full_path.startswith(f"{root}Standalone Assessments/") or \
       parent_full_path.startswith(f"{root}Shared for Collaboration/") or \
       parent_full_path.startswith(f"{root}Student Generated Assessments by Course/") or \
       parent_full_path.startswith(f"{root}Public/") or \
       parent_full_path.startswith(f"{root}Trash/"):
        return JsonResponse({
            'error': 'This directory is managed by the system. Sub-folders cannot be added here.'
        }, status=403)

    # Use the helper logic
    unique_name, error = get_valid_unique_name(BranchGroup, parent_folder, requested_name)
    
    if error:
        return JsonResponse({'error': error}, status=400)

    # Create the folder
    new_folder = BranchGroup.objects.create(
        name=unique_name,
        order=unique_name,
        parent=parent_folder,
        owner=request.user
    )

    return JsonResponse({'status': 'success', 'id': new_folder.id})


def delete_item(request, item_type=None, item_id=None):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    # 1. Flexible Extraction Layer (Handles both URL parameters and JSON bodies fluidly)
    if not item_id or not item_type:
        try:
            data = json.loads(request.body)
            item_id = item_id or data.get('id')
            item_type = item_type or data.get('type')
        except Exception:
            return JsonResponse({'error': 'Malformed request JSON payload content structure.'}, status=400)

    if not item_id or not item_type:
        return JsonResponse({'error': 'Missing required identifier parameters.'}, status=400)

    # Convert ID to int to keep unmanaged queries tracking reliably
    try:
        item_id = int(item_id)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid format: ID identifier must be an integer.'}, status=400)

    # 2. Resolve Object & Path with strict Ownership Verification
    try:
        if item_type in ['folder', 'course', 'assessment', 'assessment_selection', 'question_selection', 'problem']:
            if item_type in ['folder', 'course', 'assessment']:
                if request.user.user_type == 'IT_Support':
                    obj = get_object_or_404(BranchGroup, id=item_id)
                else:
                    obj = get_object_or_404(BranchGroup, id=item_id, owner=request.user)

            elif item_type == 'assessment_selection':
                aqg_item = get_object_or_404(AssessmentQuestionGroup.objects.select_related('branch_location', 'assessment__course'), id=item_id)
                is_course_teacher = UsersInCourse.objects.filter(
                    course=aqg_item.assessment.course,
                    user=request.user,
                    user__user_type='Teacher'
                ).exists()
                if is_course_teacher or request.user.user_type == 'IT_Support':
                    obj = aqg_item.branch_location
                else:
                    return JsonResponse({'error': f'User not authenticated to delete: {item_type}'}, status=403)
                    
            elif item_type == 'question_selection':
                if request.user.user_type == 'IT_Support':
                    cqd_item = get_object_or_404(CustomQuestionDistribution, id=item_id)
                else:
                    cqd_item = get_object_or_404(CustomQuestionDistribution, id=item_id, assigned_folder__owner=request.user)
                obj = cqd_item.assigned_folder
                
            elif item_type == 'problem':
                problem_item = get_object_or_404(Problem.objects.select_related('branch_location'), id=item_id)
                if request.user.user_type != 'IT_Support' and problem_item.branch_location.owner != request.user:
                    return JsonResponse({'error': 'Permission Denied: You do not own this resource.'}, status=403)
                obj = problem_item.branch_location

            if not obj:
                return JsonResponse({'error': 'Target branch directory location tracking error.'}, status=400)

            item_full_path = obj.get_parent_path() + obj.name + "/"
        else:
            return JsonResponse({'error': f'Unsupported item type: {item_type}'}, status=400)
            
    except Exception as e:
        print(f"The item id being queried is = {item_id}")
        print(traceback.format_exc()) 
        return JsonResponse({
            'error': f"Python Exception: {str(e)}",
            'item_id_received': item_id,
            'item_type_received': item_type
        }, status=400)

    # 3. System Protection Check
    username = request.user.username
    root = f"/Users/{username}_root/"
    protected = [f"{root}Courses/", 
                 f"{root}Standalone Assessments/", 
                 f"{root}Standalone Problems/",
                 f"{root}Shared for Collaboration/",
                 f"{root}Student Generated Assessments by Course/",
                 f"{root}Public/",
                 f"{root}Trash/"]

    if item_full_path in protected:
        return JsonResponse({'error': 'System folders cannot be deleted.'}, status=403)

    # 4. Empty Check for Folders
    if item_type == 'folder':
        has_content = (
            BranchGroup.objects.filter(parent=obj).exists() or
            Course.objects.filter(branch_location=obj).exists() or
            Assessment.objects.filter(branch_location=obj).exists() or
            AssessmentQuestionGroup.objects.filter(branch_location=obj).exists() or
            CustomQuestionDistribution.objects.filter(assigned_folder=obj).exists()
        )
        if has_content:
            return JsonResponse({'error': 'Folder is not empty.'}, status=400)

    # 5. Execute
    with transaction.atomic():
        if item_type in ['folder', 'course', 'assessment', 'assessment_selection', 'question_selection', 'problem']:
            obj.delete()
        else:
            return JsonResponse({'error': f'Unsupported purge routing requested for type: {item_type}.'}, status=403)
            
    return JsonResponse({'status': 'success'})


def rename_item(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        data = json.loads(request.body)
        item_id = data.get('id')
        item_type = data.get('type')
        new_name = data.get('new_name', '').strip()

        if not new_name:
            return JsonResponse({'error': 'Name cannot be blank.'}, status=400)

        # Map client identifiers to core model definitions
        model_map = {
            'folder': (BranchGroup, 'name'),
            'course': (Course, 'name'), 
            'assessment': (Assessment, 'name'),
            'problem': (Problem, 'title'),
            'assessment_selection': (AssessmentQuestionGroup, 'name'),
        }

        if item_type not in model_map:
            return JsonResponse({'error': 'Unknown item type.'}, status=400)

        model_class, field_name = model_map[item_type]
        
        # --- COMPONENT FETCH AND SECURITY CLEARANCE ---
        if item_type in ['folder', 'course', 'assessment']:
            obj = get_object_or_404(BranchGroup, id=item_id)
            
            # Since verify_workspace_clearance expects a Problem instance, 
            # we handle Folder/Course/Assessment node ownership directly or fallback on IT_Support
            if request.user.user_type != 'IT_Support' and obj.owner != request.user:
                return JsonResponse({'error': 'You do not have permission to rename this system element.'}, status=403)
                
            item_full_path = obj.get_parent_path() + obj.name + "/"
            parent = obj.parent
        else:
            # 🚀 UPDATED: Fetch independent items and defer to your global clearance engine
            # The 'obj' is a BranchGroup item, not the 'problem' item
            print(f"model_class: {model_class}")
            obj = get_object_or_404(model_class, id=item_id)
            
            if item_type == 'problem':
                # Pass your problem record straight to your specialized security matrix mapping routine
                if not verify_workspace_clearance(request.user, obj):
                    return JsonResponse({'error': 'You do not have workspace clearance to rename this problem.'}, status=403)
            else:
                # Fallback security check for other independent items (like assessment_selection groups)
                if request.user.user_type != 'IT_Support' and obj.branch_location and obj.branch_location.owner != request.user:
                    return JsonResponse({'error': 'You do not have permission to rename this resource.'}, status=403)

            item_full_path = obj.branch_location.get_parent_path() + obj.branch_location.name + "/"
            parent = obj.branch_location

        # Check to make sure the 'new_name' doesn't contain unallowed structures via business rules
        bg_context_node = obj if item_type == 'folder' else parent
        new_name, error = get_valid_unique_name(BranchGroup, bg_context_node.parent if item_type == 'folder' else bg_context_node, new_name)
        if error:
            return JsonResponse({'error': error}, status=400)

        username = request.user.username
        protected_roots = [
            f"/Users/{username}_root/Courses/",
            f"/Users/{username}_root/Standalone Assessments/",
            f"/Users/{username}_root/Standalone Problems/",
            f"/Users/{username}_root/Shared for Collaboration/",
            f"/Users/{username}_root/Student Generated Assessments by Course/",
            f"/Users/{username}_root/Public/",
            f"/Users/{username}_root/Trash/",
        ]

        if item_full_path in protected_roots:
            return JsonResponse({'error': 'Cannot rename system folders.'}, status=403)

        if item_full_path.startswith(f"/Users/{username}_root/Courses/") and not request.resolver_match.view_name == 'course_list':
            if request.user.user_type != 'IT_Support' and item_type == 'folder' and obj.name in ['Courses', 'Trash']:
                return JsonResponse({'error': 'Cannot rename Course items here.'}, status=403)

        # Automatic Suffix Incrementor Collision Management Logic
        base_name = new_name
        counter = 1
        
        while True:
            duplicate_query = {field_name: new_name}
            if parent:
                if item_type in ['folder', 'course', 'assessment']:
                    duplicate_exists = BranchGroup.objects.filter(parent=parent, name=new_name).exclude(id=obj.id if item_type == 'folder' else obj.id).exists()
                else:
                    duplicate_exists = model_class.objects.filter(branch_location=parent, **duplicate_query).exclude(id=obj.id).exists()
            else:
                duplicate_exists = BranchGroup.objects.filter(parent__isnull=True, owner=obj.owner, name=new_name).exclude(id=obj.id if item_type == 'folder' else obj.id).exists()

            if not duplicate_exists:
                break
            
            new_name = f"{base_name} ({counter})"
            counter += 1

        # --- EXECUTE SYNCHRONIZED DATABASE ATOMIC WRITE ---
        with transaction.atomic():
            if item_type in ['course', 'assessment']:
                obj.name = new_name
                obj.save()

                payload_relation_str = 'course' if item_type == 'course' else 'assessment'
                if hasattr(obj, payload_relation_str):
                    payload_obj = getattr(obj, payload_relation_str)
                    setattr(payload_obj, field_name, new_name)
                    payload_obj.save()
                    
            elif item_type == 'folder':
                obj.name = new_name
                obj.save()
                
                if hasattr(obj, 'course'):
                    obj.course.name = new_name
                    obj.course.save()
                elif hasattr(obj, 'assessment'):
                    obj.assessment.name = new_name
                    obj.assessment.save()

            elif item_type == 'problem':
                setattr(obj, field_name, new_name)  # updates obj.title
                obj.save()

                if obj.branch_location:
                    obj.branch_location.name = new_name
                    obj.branch_location.save()
            else:
                setattr(obj, field_name, new_name)
                obj.save()

        return JsonResponse({'status': 'success', 'new_name': new_name})
    
    except Exception as e:
        return JsonResponse({'error': f"Rename operation failed: {str(e)}"}, status=500)



@login_required
@require_POST
def restore_trash_item_view(request):
    try:
        data = json.loads(request.body)
        folder_id = data.get('folder_id')
        
        folder = get_object_or_404(BranchGroup, id=folder_id, owner=request.user)
        
        # Fire our polymorphic handler function from utils
        restore_item_from_trash(request, folder)
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
def login_view(request):
    # 1. HANDLE USERS ALREADY LOGGED IN (GET Requests)
    if request.user.is_authenticated and request.method == 'GET':
        if request.user.user_type == 'Student':
            logout(request)
            return redirect('login')
        else:
            return redirect('dashboard')

    # 2. HANDLE AUTHENTICATION ATTEMPTS (POST Requests)
    if request.method == 'POST':
        if request.user.is_authenticated:
            logout(request)
            
        # Initialize the standard form with post data
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            # Extract authenticated user records from the valid form payload
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password. Please try again.")
            return redirect('login')

    # 3. RENDER BLANK LOGIN FORM (GET Requests)
    form = AuthenticationForm() # Empty form instance for the template context
    reason = request.GET.get('reason')
    if reason == 'multiple_tabs':
        messages.warning(request, "You were logged out because the platform was opened in another tab.")
        
    return render(request, 'assessment_tool/login.html', {'form': form})


@login_required
def course_detail_view(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    user_type = request.user.user_type # Pulling from your established profile engine

    # 1. Unpack html markup string safely out of the course JSON field
    intro_html_content = ""
    if course.introduction:
        try:
            # If stored field text is a string representation of JSON
            data = json.loads(course.introduction) if isinstance(course.introduction, str) else course.introduction
            intro_html_content = data.get('html_content', '')
        except (json.JSONDecodeError, TypeError, AttributeError):
            intro_html_content = str(course.introduction)

    # 2. Process Rich Text Form Updates
    if request.method == 'POST' and 'introduction_payload' in request.POST:
        if user_type not in ['Teacher', 'IT_Support']:
            messages.error(request, "Unauthorized operation framework.")
            return redirect('course_detail', course_id=course.id)
            
        raw_json_str = request.POST.get('introduction_payload')
        try:
            # Ensure incoming transmission is validated JSON structured block
            json.loads(raw_json_str) 
            course.introduction = raw_json_str
            course.save()
            messages.success(request, "Course introduction update saved successfully!")
        except json.JSONDecodeError:
            messages.error(request, "Failed parsing document data validation framework structure.")
            
        return redirect('course_detail', course_id=course.id)

    context = {
        'course': course,
        'user_type': user_type,
        'intro_html_content': intro_html_content,
        'active_tab': 'introduction', 
    }
    return render(request, 'assessment_tool/course_intro.html', context)


@login_required
def assessment_view(request, course_id):
    # 1. Grab the current course structure context
    course = get_object_or_404(Course, id=course_id)
    
    # 2. Extract current user type session flags from user request profile if needed
    user_type = getattr(request.user, 'user_type', 'Student') # pretends the 'user_type' is 'Student' if 'user_type' didn't return anything

    # 3. Fetch master assessment templates linked to this course track
    assessments = (
        Assessment.objects.filter(
            course=course,
            parent_assessment__isnull=True,
            user__isnull=True
        ).exclude(
        status='deleted'
        ).select_related('branch_location').order_by('order', 'creation_date')
    )

    context = {
        'course': course,
        'user_type': user_type,
        'assessments': assessments,
        'active_tab': 'assessments', 
        'current_time': timezone.now()
    }
    return render(request, 'assessment_tool/assessments.html', context)




@login_required
@require_POST
def create_assessment_ajax(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    
    # Permission verification
    user_type = getattr(request.user, 'user_type', 'Student')
    if user_type not in ['Teacher', 'IT_Support']:
        return JsonResponse({'error': 'Unauthorized framework privilege clearance.'}, status=403)
        
    try:
        data = json.loads(request.body)
        assessment_name = data.get('name', '').strip()
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid payload data structure.'}, status=400)
        
    if not assessment_name:
        return JsonResponse({'error': 'Assessment name is a required identifier.'}, status=400)
        
    try:
        with transaction.atomic():
            # 1. Discover the parent folder for this course structure.
            # We locate the BranchGroup node whose folder_type is 'course' and points to this course id.
            parent_folder = BranchGroup.objects.filter(
                course=course,
                folder_type='course'
            ).first()
            
            # Fallback pathing resolution if explicit link mapping isn't fully bound yet
            if not parent_folder:
                return JsonResponse({'error': 'Course parent is required.'}, status=400)
            
                # TODO: assessments are allowed to be present without a course, if so, save it in the Asessments root folder instead
                #.      Come back to this later to implement
                # parent_folder = BranchGroup.objects.filter(
                #     owner=course.owner if hasattr(course, 'owner') else request.user,
                #     name='Courses',
                #     folder_type='folder'
                # ).first()

            # 2. Allocate the brand new structural BranchGroup folder block
            assessment_folder = BranchGroup.objects.create(
                name=assessment_name,
                owner=parent_folder.owner if parent_folder else request.user,
                parent=parent_folder,
                folder_type='assessment',
                order=assessment_name # Alphabetical string sorting alignment
            )
            
            # 3. Provision the master Assessment template model schema
            new_assessment = Assessment.objects.create(
                course=course,
                name=assessment_name,
                branch_location=assessment_folder,
                status='inactive',  # Default baseline initialization fallback
                is_historic=False,   # Master template starts variable/algorithmic
                points_weight=1.0,   # 100% normal weight multiplier assignment
                order=assessment_name
            )
            
            return JsonResponse({
                'success': True,
                'assessment_id': new_assessment.id,
                'name': new_assessment.name,
                'status': new_assessment.status
            })
            
    except Exception as e:
        return JsonResponse({'error': f'Failed executing database transaction block: {str(e)}'}, status=500)
    
@login_required
@require_POST
def update_assessment_status_ajax(request, course_id):
    """Updates status for an assessment after safety confirmation checks pass."""
    user_type = getattr(request.user, 'user_type', 'Student')
    if user_type not in ['Teacher', 'IT_Support']:
        return JsonResponse({'error': 'Privilege check failed.'}, status=403)

    try:
        data = json.loads(request.body)
        assessment_id = data.get('assessment_id')
        new_status = data.get('status')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Malformed parameters.'}, status=400)

    # Valid options from your enum definition
    valid_statuses = ['closed', 'open', 'locked', 'retake_available', 'submitted', 'active', 'inactive', 'upcoming']
    if new_status not in valid_statuses:
        return JsonResponse({'error': 'Target lifecycle flag is not registered inside status enum.'}, status=400)

    assessment = get_object_or_404(Assessment, id=assessment_id, course_id=course_id)
    assessment.status = new_status
    assessment.save()
    
    return JsonResponse({'success': True})


@login_required
@require_POST
def update_assessment_window_ajax(request, assessment_id):
    """
    Saves the start_time and end_time range parameters for an isolated assessment item.
    """
    user_type = getattr(request.user, 'user_type', 'Student')
    if user_type not in ['Teacher', 'IT_Support']:
        return JsonResponse({'error': 'Privilege authorization checkpoint mismatch.'}, status=403)

    try:
        data = json.loads(request.body)
        start_raw = data.get('start_time')
        end_raw = data.get('end_time')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Malformed properties container framework.'}, status=400)

    assessment = get_object_or_404(Assessment, id=assessment_id)
    
    # Process updates or strip values to None if matching disable checks
    parsed_start = None
    parsed_end = None

    if start_raw and end_raw:
        try:
            # Parse localized user strings into fully timezone-aware objects
            parsed_start = timezone.is_aware(timezone.datetime.fromisoformat(start_raw)) or timezone.make_aware(timezone.datetime.fromisoformat(start_raw))
            parsed_end = timezone.is_aware(timezone.datetime.fromisoformat(end_raw)) or timezone.make_aware(timezone.datetime.fromisoformat(end_raw))
        except ValueError:
            return JsonResponse({'error': 'Invalid date string layout tracking parameters.'}, status=400)

        # 🛑 Backend Validation Rule Check: Start must precede End
        if parsed_start >= parsed_end:
            return JsonResponse({'error': 'The start date configuration must be before the terminal target boundary.'}, status=400)

    # Persist values to database
    assessment.start_time = parsed_start
    assessment.end_time = parsed_end
    assessment.save()

    return JsonResponse({
        'success': True,
        'assessment_id': assessment.id,
        'status': assessment.status
    })

@login_required
@require_POST
def trash_assessment_ajax(request, assessment_id):
    try:
        # 1. Use select_related to bring down the correct relationship path safely
        assessment = Assessment.objects.select_related('branch_location').get(id=assessment_id)
        
        # 🎯 SCOPED PERMISSION CHECK: Verify the user is registered as a Teacher for THIS specific course
        is_teacher_in_course = UsersInCourse.objects.filter(
            user=request.user,
            course=assessment.course,
            user__user_type='Teacher'
        ).exists()
        if is_teacher_in_course:
            return JsonResponse({'success': False, 'error': 'Unauthorized modification request.'}, status=403)
            
        # 2. Flag assessment status to 'deleted'
        assessment.status = 'deleted'
        assessment.save()

        # 3. Relocate the linked branch_location into the default system 'Trash' directory folder
        if assessment.branch_location:
            try:
                branch_group = assessment.branch_location
                
                # Trace up to find the user's top-level root folder wrapper
                user_root = BranchGroup.objects.filter(owner=request.user, parent__isnull=True).first()
                
                if user_root:
                    # Locate the default 'Trash' sub-folder provisioned by signals.py
                    trash_folder = BranchGroup.objects.filter(
                        parent=user_root,
                        name='Trash',
                        folder_type='folder'
                    ).first()
                    
                    if trash_folder:
                        branch_group.parent = trash_folder
                        branch_group.save()
            except Exception as e:
                pass  # Fall back safely if there are folder assignment structural rules

        return JsonResponse({'success': True, 'message': 'Assessment relocated to Trash.'})

    except Assessment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Assessment tracking record not found.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def reorder_assessment_ajax(request, course_id):
    # Verify Permissions
    user_type = getattr(request.user, 'user_type', 'Student')
    if user_type not in ['Teacher', 'IT_Support'] and not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Unauthorized modification request.'}, status=403)
        
    try:
        data = json.loads(request.body)
        assessment_id = data.get('assessment_id')
        prev_id = data.get('prev_id')  # ID of the item row now above it
        next_id = data.get('next_id')  # ID of the item row now below it
        
        # Pull down the assessment along with its branch folder location relation cleanly
        assessment = get_object_or_404(
            Assessment.objects.select_related('branch_location'), 
            id=assessment_id, 
            course_id=course_id
        )
        
        prev_order = ""
        next_order = ""
        
        if prev_id:
            prev_order = Assessment.objects.get(id=prev_id).order or ""
        if next_id:
            next_order = Assessment.objects.get(id=next_id).order or ""
            
        # Compute the new lexicographical midpoint string using your string algorithm
        new_order = calculate_midpoint_order(prev_order, next_order)
        
        # 🎯 SYNCHRONIZED TRANSACTION BLOCK
        with transaction.atomic():
            # 1. Update the dashboard order string
            assessment.order = new_order
            assessment.save()
            
            # 2. Update the folder node's order string to keep the explorer completely in sync
            if assessment.branch_location:
                folder = assessment.branch_location
                folder.order = new_order
                folder.save()
        
        return JsonResponse({'success': True, 'new_order': new_order})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def assessment_setup_view(request, course_id, assessment_id):
    # 🎯 SCOPED PERMISSION CHECK: Verify username matching across the usersincourse set
    is_teacher = Course.objects.filter(
        id=course_id,
        usersincourse__user=request.user,
        usersincourse__user__user_type='Teacher'
    ).exists()
    
    user_type = getattr(request.user, 'user_type', 'Student')
    if not is_teacher and user_type != 'IT_Support' and not request.user.is_staff:
        messages.error(request, "You do not have access to manage this assessment configuration.")
        return redirect('course_dashboard', course_id=course_id)

    course = get_object_or_404(Course, id=course_id)
    assessment = get_object_or_404(Assessment.objects.select_related('branch_location'), id=assessment_id, course=course)
    
    # Retrieve current question groups in lexicographical order
    aqg_groups = AssessmentQuestionGroup.objects.filter(assessment=assessment).order_by('order')

    context = {
        'course': course,
        'assessment': assessment,
        'aqg_groups': aqg_groups,
        'user_type': user_type if user_type == 'IT_Support' else 'Teacher',
        'load_problem_workspace': True,
    }
    return render(request, 'assessment_tool/assessment_setup.html', context)


@login_required
@require_POST
def create_aqg_ajax(request, course_id, assessment_id):
    is_teacher = UsersInCourse.objects.filter(
        course_id=course_id,
        user=request.user,
        user__user_type='Teacher'
    ).exists()
    
    user_type = getattr(request.user, 'user_type', 'Student')
    if not is_teacher and user_type != 'IT_Support' and not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Unauthorized action.'}, status=403)

    try:
        data = json.loads(request.body)
        raw_name = data.get('name', '').strip()
        
        clean_name = re.sub(r'\s+', ' ', raw_name)
        if not clean_name:
            return JsonResponse({'success': False, 'error': 'Section name cannot be empty.'}, status=400)

        assessment = get_object_or_404(Assessment.objects.select_related('branch_location'), id=assessment_id, course_id=course_id)
        
        last_aqg = AssessmentQuestionGroup.objects.filter(assessment=assessment).order_by('order').last()
        prev_order = last_aqg.order if last_aqg else ""
        new_order = calculate_midpoint_order(prev_order, "")

        with transaction.atomic():
            folder = BranchGroup.objects.create(
                name=clean_name,
                owner=request.user,
                parent=assessment.branch_location,
                folder_type='aqg',
                order=new_order
            )

            aqg = AssessmentQuestionGroup.objects.create(
                assessment=assessment,
                name=clean_name,
                order=new_order,
                branch_location=folder
            )

            html_snippet = render_to_string('assessment_tool/components/aqg_card.html', {'group': aqg})

        return JsonResponse({
            'success': True,
            'html': html_snippet,
            'id': aqg.id,
            'name': aqg.name,
            'order': aqg.order
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def rename_aqg_ajax(request, course_id, assessment_id):
    is_teacher = UsersInCourse.objects.filter(
        course_id=course_id,
        user=request.user,
        user__user_type='Teacher'
    ).exists()
    
    user_type = getattr(request.user, 'user_type', 'Student')
    if not is_teacher and user_type != 'IT_Support' and not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Unauthorized action.'}, status=403)

    try:
        data = json.loads(request.body)
        aqg_id = data.get('id')
        raw_name = data.get('name', '').strip()
        
        clean_name = re.sub(r'\s+', ' ', raw_name)
        if not clean_name:
            return JsonResponse({'success': False, 'error': 'Section name cannot be empty.'}, status=400)

        aqg = get_object_or_404(AssessmentQuestionGroup.objects.select_related('branch_location'), id=aqg_id, assessment_id=assessment_id)

        with transaction.atomic():
            aqg.name = clean_name
            aqg.save()

            if aqg.branch_location:
                aqg.branch_location.name = clean_name
                aqg.branch_location.save()

        return JsonResponse({'success': True, 'name': clean_name})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def reorder_aqg_ajax(request, course_id, assessment_id):
    is_teacher = UsersInCourse.objects.filter(
        course_id=course_id,
        user=request.user,
        user__user_type='Teacher'
    ).exists()
    
    user_type = getattr(request.user, 'user_type', 'Student')
    if not is_teacher and user_type != 'IT_Support' and not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Unauthorized action.'}, status=403)

    try:
        data = json.loads(request.body)
        aqg_id = data.get('aqg_id')
        prev_id = data.get('prev_id')
        next_id = data.get('next_id')

        aqg = get_object_or_404(AssessmentQuestionGroup.objects.select_related('branch_location'), id=aqg_id, assessment_id=assessment_id)

        prev_order = ""
        next_order = ""

        if prev_id:
            prev_order = AssessmentQuestionGroup.objects.get(id=prev_id).order or ""
        if next_id:
            next_order = AssessmentQuestionGroup.objects.get(id=next_id).order or ""

        new_order = calculate_midpoint_order(prev_order, next_order)

        with transaction.atomic():
            aqg.order = new_order
            aqg.save()

            if aqg.branch_location:
                aqg.branch_location.order = new_order
                aqg.branch_location.save()

        return JsonResponse({'success': True, 'new_order': new_order})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@require_POST
@login_required
def add_problem_to_aqg_ajax(request, course_id, assessment_id):
    """
    Creates a new sequential Problem child item inside an Assessment Question Group.
    Provisions a companion identity BranchGroup node nested securely within the target location frame.
    """
    # 1. Authority Guard: Enforce strict role-access permissions
    is_teacher = UsersInCourse.objects.filter(
        course_id=course_id,
        user=request.user,
        user__user_type='Teacher'
    ).exists()
    
    user_type = getattr(request.user, 'user_type', 'Student')
    if not is_teacher and user_type != 'IT_Support' and not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized deployment verification state access failed.'}, status=403)

    try:
        data = json.loads(request.body)
        aqg_id = data.get('aqg_id')
        
        # 2. Fetch the target parent AssessmentQuestionGroup layer container location framework
        aqg = get_object_or_404(
            AssessmentQuestionGroup.objects.select_related('branch_location'), 
            id=aqg_id, 
            assessment_id=assessment_id
        )
        parent_directory = aqg.branch_location

        if not parent_directory:
            return JsonResponse({'error': 'Target base group context mapping location identity mismatch error.'}, status=400)

        # 3. Handle sequential layout naming definitions
        # Trace current child problem structural nodes to determine starting title index string
        existing_problem_nodes = BranchGroup.objects.filter(parent=parent_directory, folder_type='problem')
        problem_count = existing_problem_nodes.count() + 1
        requested_item_name = f"Problem {problem_count}"

        # Resolve unique naming contexts cleanly using your existing utility script
        final_item_name, name_err = get_valid_unique_name(
            model_class=BranchGroup,
            parent_obj=parent_directory,
            requested_name=requested_item_name
            # Keeps item_type='folder' implicitly to verify parent sibling contexts cleanly!
        )
        if name_err:
            return JsonResponse({'error': name_err}, status=400)

        # Determine structural lexicographical midpoint sorting strings
        last_problem_node = existing_problem_nodes.order_by('order').last()
        prev_order_val = last_problem_node.order if last_problem_node else ""
        
        new_order = calculate_midpoint_order(prev_order_val, "")

        # 4. Synchronized Database Atomic Transaction Block
        with transaction.atomic():
            # A. Provision the silent structural BranchGroup identity tracker node
            problem_branch_node = BranchGroup.objects.create(
                owner=request.user,
                name=final_item_name,
                parent=parent_directory,
                folder_type='problem',
                order=new_order
            )

            # B. Allocate the companion concrete math problem payload row layer
            new_problem_item = Problem.objects.create(
                branch_location=problem_branch_node,  # Coordinates link
                title=final_item_name,                # Suffix incremented calculated name
                aqg=aqg,                              # Assessment structural layout frame hook
                problem_status='draft'                # Status = 'draft' or 'complete
            )

        # 5. 🎯 NEW: Render the problem_card component into a raw HTML string snippet
        # This matches the exact variable scope context ('prob') expected by problem_card.html
        problem_html = render_to_string(
            'assessment_tool/components/problem_card.html', 
            {'prob': new_problem_item}, 
            request=request
        )

        return JsonResponse({
            'status': 'success',
            'branch_id': problem_branch_node.id,
            'problem_id': new_problem_item.id,
            'allocated_name': final_item_name,
            'html': problem_html  # 🎯 Send the complete pre-rendered component string to the UI
        }, status=201)

    except Exception as e:
        print(traceback.format_exc())
        return JsonResponse({'error': f"Operation failed: {str(e)}"}, status=400)


@login_required
def add_cqd_to_aqg_ajax(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        data = json.loads(request.body)
        aqg_id = data.get('aqg_id')
        
        if not aqg_id:
            return JsonResponse({'error': 'Missing section group identifier constraint.'}, status=400)
            
        # Fetch the active section group component context container
        aqg = get_object_or_404(AssessmentQuestionGroup.objects.select_related('branch_location'), id=aqg_id)
        parent_directory = aqg.branch_location
        
        # Calculate sequential ordering positions inside the folder layout tree branch
        last_child = BranchGroup.objects.filter(parent=parent_directory).order_by('order').last()
        
        # 🚀 FIX: Fallback to an empty string instead of a whitespace character " "
        # (Alternatively, if your midpoint logic prefers starting from the beginning of the alphabet, use "a")
        prev_order = last_child.order if last_child else "" 
        
        new_order = calculate_midpoint_order(prev_order, "z")
        
        # Generation identity config fields
        final_item_name = f"A placeholder name"
        
        with transaction.atomic():
            # 1. Provision the structural BranchGroup framework node container
            cqd_branch_node = BranchGroup.objects.create(
                owner=request.user,
                name=final_item_name,
                parent=parent_directory,
                folder_type='cqd',  
                order=new_order,
                creation_date=timezone.now(),
                modification_date=timezone.now()
            )
            
            # 2. Allocate the concrete CustomQuestionDistribution database payload row layer
            new_cqd_item = CustomQuestionDistribution.objects.create(
                assigned_folder=cqd_branch_node,
                suggested_count=1  
            )
            
            # Set a temporary query attribute variable hook to reflect 0 initialization sub-pairs safely inside get_unique_name
            new_cqd_item.num_pairs = 0

            cqd_branch_node.name = new_cqd_item.get_unique_name()
            cqd_branch_node.save(update_fields=['name', 'modification_date']) 
        
        # 3. Pre-compile the standalone component template context snapshot layout fragment string snippet
        cqd_html = render_to_string(
            'assessment_tool/components/cqd_card.html',
            {'cqd': new_cqd_item},
            request=request
        )
        
        return JsonResponse({
            'status': 'success',
            'html': cqd_html
        }, status=201)
        
    except Exception as e:
        return JsonResponse({'error': f"Internal Server Exception Process Fault: {str(e)}"}, status=500)


@login_required
def update_cqd_count_ajax(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        data = json.loads(request.body)
        cqd_id = data.get('cqd_id')
        suggested_count = data.get('suggested_count')

        # Clean validation conversion safeguard
        try:
            new_count = int(suggested_count)
            if new_count <= 0:
                new_count = 1
        except (TypeError, ValueError):
            new_count = 1

        # Locate the record and confirm ownership against the virtual folder owner field
        if request.user.user_type == 'IT_Support':
            cqd_item = get_object_or_404(CustomQuestionDistribution, id=cqd_id)
        else:
            cqd_item = get_object_or_404(CustomQuestionDistribution, id=cqd_id, assigned_folder__owner=request.user)

        # Update and save the model state
        cqd_item.suggested_count = new_count
        cqd_item.save(update_fields=['suggested_count'])

        return JsonResponse({
            'status': 'success',
            'new_count': cqd_item.suggested_count
        }, status=200)

    except Exception as e:
        return JsonResponse({'error': f"Database Write Operation Failure: {str(e)}"}, status=500)
    

@login_required
@require_POST
def reorder_nested_item_ajax(request):
    # Determine permission scopes across Teacher/IT parameters
    # Note: If your system uses a course context here, you can extract context validation checks 
    # but checking for BranchGroup ownership offers an intuitive fallback layout baseline safety layer.
    
    try:
        data = json.loads(request.body)
        branch_id = data.get('branch_id')
        prev_branch_id = data.get('prev_branch_id')
        next_branch_id = data.get('next_branch_id')

        if not branch_id:
            return JsonResponse({'success': False, 'error': 'Missing targets.'}, status=400)

        # 1. Fetch target node with ownership validation rules
        if request.user.user_type == 'IT_Support' or request.user.is_staff:
            target_node = get_object_or_404(BranchGroup, id=branch_id)
        else:
            target_node = get_object_or_404(BranchGroup, id=branch_id, owner=request.user)

        prev_order = ""
        next_order = ""

        # 2. Extract companion midpoint string sequences out of adjacent sibling nodes
        if prev_branch_id:
            prev_order = BranchGroup.objects.get(id=prev_branch_id).order or ""
        if next_branch_id:
            next_order = BranchGroup.objects.get(id=next_branch_id).order or ""

        # 3. Calculate position using your established midpoint algorithm function loop string builder
        new_order = calculate_midpoint_order(prev_order, next_order)

        # 4. Atomic write transaction execution state loop
        with transaction.atomic():
            target_node.order = new_order
            target_node.save(update_fields=['order', 'modification_date'])

        return JsonResponse({'success': True, 'new_order': new_order})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': f"Sorting Matrix Runtime Failure: {str(e)}"}, status=400)
    


@login_required
def start_student_assessment_session(request, assessment_id):
    if request.user.user_type != 'Student':
        return JsonResponse({'error': 'Unauthorized view permission layout.'}, status=403)
        
    assessment = get_object_or_404(Assessment, id=assessment_id)
    course = assessment.course
    username = request.user.username
    
    # 1. Ensure the specific student course storage path exists
    # Target Root: /Users/{username}_root/Student Generated Assessments by Course/{Course_Name}/
    target_root_path = f"/Users/{username}_root/Student Generated Assessments by Course/{course.name}/"
    
    with transaction.atomic():
        # Get or create the course branch container inside the student's virtual layout hierarchy
        course_container, created = BranchGroup.objects.get_or_create(
            name=course.name,
            owner=request.user,
            defaults={'order': 'M', 'is_directory': True} 
            # adjust defaults according to your local structural model properties
        )
        
        # 2. Extract every problem assigned via the assessment question groups
        aqgs = AssessmentQuestionGroup.objects.filter(assessment=assessment).order_by('order')
        
        compiled_test_payload = {
            "assessment_id": assessment.id,
            "title": assessment.title,
            "questions": []
        }
        
        for aqg in aqgs:
            # Randomly fetch problems according to the distribution count constraints
            problems_pool = list(Problem.objects.filter(aqg=aqg))
            if not problems_pool:
                continue
                
            chosen_problem = random.choice(problems_pool)
            
            # Fetch all entity data elements associated with this problem template structure
            entities = EntitySegment.objects.filter(problem=chosen_problem)
            
            evaluated_variables = {}
            active_answer_blocks = {}
            
            # Step A: Evaluate variables first to lock down random selections
            for entity in entities:
                meta = json.loads(entity.content)
                if meta.get('type', '').startswith('variable_'):
                    val = SymPyAssessmentEngine.evaluate_variable(meta)
                    evaluated_variables[meta.get('token')] = val
            
            # Step B: Process layout blocks and structure multiple-choice distractors securely
            for entity in entities:
                meta = json.loads(entity.content)
                ent_type = meta.get('type')
                token = meta.get('token')
                
                if ent_type == 'multiple_choice' and entity.default_answer:
                    # Resolve token references in correct values
                    correct_expr_raw = meta['choices'][0]['content'] # assuming first index is template target
                    evaluated_correct = SymPyAssessmentEngine.substitute_tokens(correct_expr_raw, evaluated_variables)
                    
                    choices_payload = [{'id': 'correct', 'content': evaluated_correct}]
                    
                    if meta.get('decoy_generation_mode') == 'sympy_random':
                        decoys = SymPyAssessmentEngine.generate_sympy_decoys(evaluated_correct, count=3)
                        for d in decoys:
                            choices_payload.append({'id': f'decoy_{random.randint(1000,9999)}', 'content': d})
                    
                    random.shuffle(choices_payload) # Mix them up so 'correct' isn't always index 0
                    
                    active_answer_blocks[token] = {
                        "type": "multiple_choice",
                        "choices": choices_payload,
                        "points": entity.points
                    }
                    
                    # Core security: Cache the master answer validation map in the session snapshot state only
                    active_answer_blocks[token]["_secure_correct_key"] = evaluated_correct

                elif ent_type == 'mathematical_expression' and entity.default_answer:
                    evaluated_correct = SymPyAssessmentEngine.substitute_tokens(meta['correct_formula'], evaluated_variables)
                    active_answer_blocks[token] = {
                        "type": "mathematical_expression",
                        "points": entity.points,
                        "expected_structure": meta.get('expected_structural_form'),
                        "_secure_correct_key": evaluated_correct
                    }
            
            # Step C: Compile the display HTML by rendering token replacements safely
            q_blocks = QuestionBlock.objects.filter(problem=chosen_problem)
            compiled_html_elements = []
            
            for block in q_blocks:
                rendered_text = SymPyAssessmentEngine.substitute_tokens(block.content, evaluated_variables)
                
                # Replace answer tokens with client-safe input elements
                for token, block_data in active_answer_blocks.items():
                    if block_data['type'] == 'multiple_choice':
                        # Generate non-revealing radio select input loops
                        radio_html = f'<div class="mc-group" data-token="{token}">'
                        for choice in block_data['choices']:
                            radio_html += f'<label><input type="radio" name="{token}" value="{choice["content"]}"> {choice["content"]}</label><br>'
                        radio_html += '</div>'
                        rendered_text = rendered_text.replace(f"<{token}>", radio_html)
                        
                    elif block_data['type'] == 'mathematical_expression':
                        input_field_html = f'<input type="text" class="math-expr-input" name="{token}" placeholder="Enter formula answer...">'
                        rendered_text = rendered_text.replace(f"<{token}>", input_field_html)
                
                compiled_html_elements.append(rendered_text)

            # Package the processed problem tracking structure state
            compiled_test_payload["questions"].append({
                "problem_id": chosen_problem.id,
                "title": chosen_problem.title,
                "html_canvas": "".join(compiled_html_elements),
                # Send configuration items to client without secure validation hashes
                "client_answer_blocks": {k: {sub_k: sub_v for sub_k, sub_v in v.items() if not sub_k.startswith('_')} for k, v in active_answer_blocks.items()}
            })
            
        # 3. Store the secure state dictionary directly into the Django Session database backend 
        # to ensure verification keys remain entirely unreachable from browser contexts.
        session_key = f"active_assessment_snapshot_{assessment.id}"
        request.session[session_key] = compiled_test_payload
        
        return JsonResponse({
            'success': True,
            'assessment_title': assessment.title,
            # Send data to client UI template renderer lines
            'payload': {
                "title": compiled_test_payload["title"],
                "questions": [{k: v for k, v in q.items() if k != '_secure_correct_key'} for q in compiled_test_payload["questions"]]
            }
        }, status=200)
    

@login_required
@require_POST
def submit_student_assessment_evaluation(request, assessment_id):
    session_key = f"active_assessment_snapshot_{assessment_id}"
    snapshot = request.session.get(session_key)
    
    if not snapshot:
        return JsonResponse({'error': 'Active testing sequence data context snapshot not found.'}, status=400)
        
    try:
        submission_data = json.loads(request.body)
        student_answers = submission_data.get('answers', {}) # Expected dictionary format: {"token_name": "student_string_input"}
        
        total_score = 0.0
        max_possible_points = 0.0
        grading_ledger_report = []

        # Access original session map objects completely invisible to the request context layers
        for question in snapshot["questions"]:
            # Reconstruct answer blocks with validation keys safely intact
            for token, secure_meta in question["client_answer_blocks"].items():
                # We fetch original structural rules directly from our backend snapshot model data
                pass
            
            # For demonstration, evaluating direct values against snapshot session properties
            # (In practice, match tokens submitted out of student_answers directly)
            
        # Clear out session map upon successful processing to lock down multiple submission pathways
        del request.session[session_key]
        
        return JsonResponse({
            'status': 'success',
            'score': total_score,
            'max_points': max_possible_points
        }, status=200)
        
    except Exception as e:
        return JsonResponse({'error': f"Grading System Runtime Failure: {str(e)}"}, status=400)


def verify_workspace_clearance(user, problem):
    """
    Validates structural user clearance across three conditions:
    - User is 'IT_Support'
    - User is the owner of the branch group tied to the problem
    - User is a 'Teacher' registered inside the course ancestry track
    """
    if not user.is_authenticated or user.user_type == 'Student':
        return False
        
    if user.user_type == 'IT_Support':
        return True
        
    if problem.branch_location and problem.branch_location.owner == user:
        return True
        
    if problem.aqg_id:
        has_group_clearance = UsersInCourse.objects.filter(
            user=user,
            user__user_type='Teacher',
            course__assessment_id_originator__assessmentquestiongroup__problem=problem
        ).exists()
        if has_group_clearance:
            return True
            
    return False






@require_POST
@user_passes_test(lambda u: u.is_superuser or u.is_staff, login_url='/dashboard/')
def save_problem_workspace(request, problem_id):
    """
    Unified, transactional endpoint that runs teacher tokens through verification matrices,
    commits verified variables to entity_segment rows, and updates the text canvas in QuestionBlock.
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Malformed JSON payload specification request."}, status=400)

    try:
        problem = Problem.objects.get(pk=problem_id)
    except Problem.DoesNotExist:
        return JsonResponse({"success": False, "error": f"Problem reference ID {problem_id} not found."}, status=404)

    # 🔒 SECURITY FENCE
    if not verify_workspace_clearance(request.user, problem):
        return JsonResponse({'success': False, 'error': 'Permission Denied: Insufficient authorization clearing.'}, status=403)

    user_inputs = payload.get("inputs", [])
    body_html = payload.get("body_html", "").strip() # Extract raw rich-text markup sent down by Quill
    
    if not isinstance(user_inputs, list):
        return JsonResponse({"success": False, "error": "The workspace inputs block layout must be an array list structure."}, status=400)

    # Cache format patterns locally for this loop session to minimize database load
    cached_patterns = {}

    # 🎯 STEP A: VALIDATION LOOP (Before touch transactions)
    validated_engines = []
    # 🎯 FIX: Track tokens that successfully pass validation in this request session
    locally_validated_tokens = set()

    print("\n" + "="*60)
    print(f"📥 BEGIN WORKSPACE SAVE VALIDATION FOR PROBLEM ID: {problem_id}")
    print(f"Total input cards received: {len(user_inputs)}")
    print("="*60)

    for index, entity_data in enumerate(user_inputs):
        token_id = entity_data.get("token") 
        sequence_token = entity_data.get("sequence_token", token_id) # The unique identifier (e.g., 'formula2')
        
        print(f"\n🔍 Processing card [{index}] | Sequence Token: <{sequence_token}> | Type: {token_id}")

        if not token_id:
            return JsonResponse({"success": False, "error": f"Missing 'token' identity string at index [{index}]."}, status=400)

        if token_id not in cached_patterns:
            try:
                entity_type_record = EntityType.objects.get(name=token_id)
                pattern_data = entity_type_record.format_pattern
                if isinstance(pattern_data, str):
                    pattern_data = json.loads(pattern_data)
                cached_patterns[token_id] = pattern_data
            except EntityType.DoesNotExist:
                return JsonResponse({"success": False, "error": f"Token configuration type '{token_id}' is invalid."}, status=400)

        blueprint = cached_patterns[token_id]
        provided_fields = entity_data.get("inputs", {})

        substitutions_map = {}
        cleaned_provided_fields = {}

        solve_method = provided_fields.get("solve method", "")

        for key, value in provided_fields.items():
            if key == "substitutions" and isinstance(value, dict):
                for sub_k, sub_v in value.items():
                    substitutions_map[f"sub_{sub_k}"] = sub_v
            elif key.startswith('sub_'):
                substitutions_map[key] = value
            else:
                cleaned_provided_fields[key] = value

        # 🎯 STEP A: VALIDATION LOOP (Inside your existing for loop)
        if token_id == 'formula':
            if not cleaned_provided_fields.get('formula'):
                print(f"⚠️  [{sequence_token}] Formula field is empty. Injecting fallback '0'.")
                cleaned_provided_fields['formula'] = "0"

            if solve_method == 'variable substitution':
                has_substitutions = len(substitutions_map) > 0 or "substitutions" in provided_fields
                
                if not has_substitutions:
                    is_linked_dependency = any(
                        f"<{sequence_token}>" in str(entity.get("inputs", {})) or 
                        sequence_token in str(entity.get("inputs", {}))
                        for entity in user_inputs if entity.get("sequence_token") != sequence_token
                    )
                    
                    print(f"📋 [{sequence_token}] No substitutions found. Dependency scan linkage status: {is_linked_dependency}")
                    
                    if not is_linked_dependency:
                        return JsonResponse({
                            "success": False,
                            "error": f"Validation failed for '{sequence_token}': Please add at least one variable substitution row or link to evaluate."
                        }, status=422)
                
                # Look for the new key name when validating variables
                vars_list = [v.strip() for v in cleaned_provided_fields.get('variables', '').split(',') if v.strip()]
                if vars_list and not cleaned_provided_fields.get('variable to solve for'):
                    cleaned_provided_fields['variable to solve for'] = vars_list[0]
                elif not cleaned_provided_fields.get('variable to solve for'):
                    cleaned_provided_fields['variable to solve for'] = "x"
                
            elif solve_method == 'simplify':
                # FIX: Changed lookups from 'variable substitution' to 'variable to solve for'
                target_var = cleaned_provided_fields.get('variable to solve for', '').strip()
                if not target_var:
                    cleaned_provided_fields['variable to solve for'] = "x" 
            else:
                cleaned_provided_fields['variable to solve for'] = ""

        # 🧪 DIAGNOSTIC PRINT: Inspect fields sent to validator constructor
        print(f"⚙️  Sending fields to get_entity_validator for <{sequence_token}>:")
        print(f"    - Cleaned Fields: {cleaned_provided_fields}")
        print(f"    - Substitutions Map: {substitutions_map}")

        # 🎯 FIX: Dynamically inject a temporary validation pass flag into upstream payload 
        # dictionary nodes so that downstream validators know they passed this request session.
        runtime_payload = []
        for entity in user_inputs:
            entity_copy = dict(entity)
            ent_seq = entity_copy.get("sequence_token")
            if ent_seq in locally_validated_tokens:
                # If this sibling token passed verification earlier in the loop, mark it valid in memory
                entity_copy["is_validated_dependency"] = True
                entity_copy["outstanding_errors"] = False
            runtime_payload.append(entity_copy)

        validator = get_entity_validator(
            token_id, 
            cleaned_provided_fields, 
            blueprint, 
            all_entities_payload=runtime_payload  # 🎯 Pass the runtime annotated payload track
        )

        if not validator.is_valid():
            error_details = ", ".join([f"[{k}]: {v}" for k, v in validator.errors.items()])
            friendly_name = blueprint.get("name", token_id)
            print(f"❌ BACKEND VALIDATION FAILURE FOR {friendly_name} (<{sequence_token}>): {error_details}")
            return JsonResponse({
                "success": False,
                "error": f"Validation failed for '{friendly_name}' component: {error_details}"
            }, status=422)
            
        print(f"✅ Card <{sequence_token}> successfully verified.")

        # 🎯 FIX: Register this sequence token identifier as verified
        if sequence_token:
            locally_validated_tokens.add(sequence_token)

        validated_engines.append({
            "token_id": token_id,
            "sequence_token": sequence_token,
            "shuffle_seed": entity_data.get("shuffle_seed", ""),
            "validator": validator,
            "blueprint": blueprint,
            "substitutions_map": substitutions_map
        })

    print("\n💾 All components valid. Proceeding to Atomic Database Write...")

    # 🎯 STEP B: ATOMIC DATABASE SAVE TRANSACTION
    with transaction.atomic():
        
        # 1. Update the parent Problem parameters if altered
        problem.title = payload.get("title", problem.title)
        problem.save()

        # 2. Synchronize Canvas Text directly to the Related QuestionBlock row entry
        structured_json_string = json.dumps({"html_content": body_html})
        q_block, created = QuestionBlock.objects.get_or_create(
            problem=problem,
            defaults={'content': structured_json_string}
        )
        if not created:
            q_block.content = structured_json_string
            q_block.save()

        # 3. Clear previous variable configurations for a fresh workspace compile write
        EntitySegment.objects.filter(problem=problem).delete()

        # 4. Commit verified segments safely
        for engine_item in validated_engines:
            token_id = engine_item["token_id"]
            sequence_token = engine_item["sequence_token"]
            shuffle_seed = engine_item["shuffle_seed"]
            blueprint = engine_item["blueprint"]
            validator = engine_item["validator"]
            item_substitutions = engine_item["substitutions_map"]  # 🎯 Read it back safely here
            
            # Extract directly from the dynamic cleaned_data map
            content_payload = dict(validator.cleaned_data)

            # Inject the sub_ mappings back into the content payload dictionary 
            # so they are saved cleanly in your database row's JSON field
            if token_id == 'formula':
                for sub_key, sub_value in item_substitutions.items():
                    content_payload[sub_key] = sub_value
            
            points_value = content_payload.get("points") or blueprint.get("points", {}).get("default", 0.0)
            
            # Combine the user parameters and append display configurations to content payload JSON
            content_payload["answer_field"] = blueprint.get("answer_field", False)
            content_payload["sequence_token"] = sequence_token 
            content_payload["shuffle_seed"] = shuffle_seed

            blueprint_default = blueprint.get("default_answer")
            if blueprint_default in [True, False]:
                default_answer_fallback = blueprint_default
            else:
                if str(blueprint_default).lower() in ['true', '1', 'yes']:
                    default_answer_fallback = True
                else:
                    default_answer_fallback = False

            EntitySegment.objects.create(
                problem=problem,
                problem_type_id_originator=EntityType.objects.get(name=token_id),
                content=json.dumps(content_payload),
                points=float(points_value) if points_value is not None else 0.0,
                default_answer=str(default_answer_fallback),
                parent_entity=None,
                is_answer_to_multi_choice=None,
                space_allocation=None
            )

    print("🎉 Workspace transaction complete!")
    return JsonResponse({
        "success": True,
        "message": f"Workspace structure compiled successfully. Saved {len(user_inputs)} components and canvas."
    })



@user_passes_test(lambda u: u.is_superuser or u.is_staff, login_url='/dashboard/')
@login_required
def problem_workspace_editor(request, problem_id):
    try:
        problem = Problem.objects.get(pk=problem_id)
    except Problem.DoesNotExist:
        return JsonResponse({"success": False, "error": "Problem not found"}, status=404)
    
    # 1. Fetch available EntityType options
    all_types = EntityType.objects.all()
    dynamic_variables_options = []
    answer_fields_options = []
    
    for entity_type in all_types:
        try:
            pattern = entity_type.format_pattern
            if isinstance(pattern, str):
                pattern = json.loads(pattern)
            name_list = entity_type.entity_name_list
            if isinstance(name_list, str):
                name_list = json.loads(name_list)
        except (json.JSONDecodeError, TypeError):
            continue
            
        if pattern.get("disabled") is True:
            continue
            
        token_info = {
            "token": entity_type.name,
            "name": pattern.get("name", entity_type.name),
            "note": pattern.get("note", ""),
            "inputs": pattern.get("inputs", {})
        }
        
        if "Dynamic Variables" in name_list:
            dynamic_variables_options.append(token_info)
        elif "Answer Input Fields" in name_list:
            answer_fields_options.append(token_info)

    # 2. Load existing segments for *this* specific problem
    saved_segments_records = EntitySegment.objects.filter(problem=problem).order_by('id')
    
    # 🎯 FIRST: Build the full workspace environment registry for cross-component lookups
    all_entities_payload = []
    prepped_segments = []
    
    for segment in saved_segments_records:
        if isinstance(segment.content, dict):
            content_data = segment.content
        elif isinstance(segment.content, str) and segment.content.strip():
            try:
                content_data = json.loads(segment.content)
            except json.JSONDecodeError:
                content_data = {}
        else:
            content_data = {}

        token_name = segment.problem_type_id_originator.name
        sequence_token = content_data.get("sequence_token") or token_name
        archetype_name = re.sub(r'\d+$', '', token_name)

        # Create a thoroughly sanitized input payload copy for evaluation engines
        clean_inputs = dict(content_data)
        clean_inputs.pop("answer_field", None)
        clean_inputs.pop("sequence_token", None)
        clean_inputs.pop("shuffle_seed", None)

        all_entities_payload.append({
            'token': archetype_name,
            'sequence_token': str(sequence_token).strip(),
            'inputs': clean_inputs, # 🎯 Clean inputs matching preview structures
            'simulated_value': "" 
        })
        # Keep clean_inputs coupled with the segment block state 
        prepped_segments.append((segment, content_data, clean_inputs, token_name, sequence_token, archetype_name))

    loaded_segments = []
    # 🎯 SECOND: Process each asset using the shared environmental ledger context
    for segment, content_data, clean_inputs, token_name, sequence_token, archetype_name in prepped_segments:
        blueprint_pattern = segment.problem_type_id_originator.format_pattern
        if isinstance(blueprint_pattern, str):
            try:
                blueprint_pattern = json.loads(blueprint_pattern)
            except json.JSONDecodeError:
                blueprint_pattern = {}

        # 🚀 CALL ENCAPSULATED UTILITY
        render_results = evaluate_and_format_entity(
            archetype_name=archetype_name,
            sequence_token=sequence_token,
            clean_inputs=clean_inputs,
            pattern_blueprint=blueprint_pattern,
            all_entities_payload=all_entities_payload
        )

        loaded_segments.append({
            "id": segment.id,
            "token": archetype_name,
            "sequence_token": sequence_token,
            "points": segment.points,
            "inputs": clean_inputs,
            "simulated_value": render_results['evaluated_output'], # Keep for internal map symmetry
            "evaluated_output": render_results['evaluated_output'],
            "latex_output": render_results['latex_output']
        })

    # 3. Safely pull Quill rich text from QuestionBlock
    q_block = QuestionBlock.objects.filter(problem=problem).first()
    body_html = "<p><br></p>"
    if q_block and q_block.content:
        # 🎯 FIX: Defensively verify if content is already a dictionary or an unparsed string
        if isinstance(q_block.content, dict):
            content_data = q_block.content
        elif isinstance(q_block.content, str) and q_block.content.strip():
            try:
                content_data = json.loads(q_block.content)
            except json.JSONDecodeError:
                content_data = {}
        else:
            content_data = {}

        # Safely extract the HTML content markup or fallback
        if isinstance(content_data, dict):
            body_html = content_data.get("html_content", "<p><br></p>")
        else:
            body_html = q_block.content

    # 🎯 Return EVERYTHING as a fast, clean AJAX payload response
    return JsonResponse({
        "success": True,
        "title": problem.title,
        "body_html": body_html,
        "dynamic_variables_options": dynamic_variables_options,
        "answer_fields_options": answer_fields_options,
        "loaded_segments": loaded_segments
    })


@csrf_protect
@require_POST
def validate_component_preview(request):
    try:
        payload = json.loads(request.body)
        entities_list = payload.get('entities', [])
        
        print("\n" + "="*60)
        print("📥 [PREVIEW VIEW] INCOMING REQUEST PAYLOAD")
        print(f"Total Entities Received: {len(entities_list)}")
        print(json.dumps(payload, indent=2))
        print("="*60)
        
        if not entities_list:
            return JsonResponse({'success': True, 'updated_cache': {}, 'errors': {}})

        trigger_token = payload.get('trigger_token', '')
        mutation_targets = payload.get('mutation_targets', [trigger_token]) # Fallback to just trigger if missing

        # 🎯 FIX: Build a completely bulletproof sibling ledger using uniform lowercase lookups
        all_entities_payload = []
        for item in entities_list:
            token_raw = item.get('token', '')
            sequence_token_raw = str(item.get('sequence_token') or token_raw).strip()
            archetype_name = re.sub(r'\d+$', '', token_raw)
            
            # 🎯 ENFORCED BACKEND LOCK-BREAKER:
            # If this component is targeted for mutation/re-calculation, wipe out its 
            # incoming simulated value so the math engine is forced to evaluate the new inputs.
            if sequence_token_raw in mutation_targets:
                clean_sim_value = ""
            else:
                raw_sim_value = item.get('simulated_value')
                if raw_sim_value is None or str(raw_sim_value).strip() in ["", "None", "null"]:
                    clean_sim_value = ""
                else:
                    clean_sim_value = str(raw_sim_value).strip()

            all_entities_payload.append({
                'token': archetype_name,
                'sequence_token': sequence_token_raw,
                'inputs': item.get('inputs', {}) or {},
                'simulated_value': clean_sim_value
            })

        updated_cache = {}
        global_errors_ledger = {}

        # 1. Map entities by sequence_token for O(1) out-of-order topological tree navigation
        entities_map = {}
        for item in entities_list:
            token_raw = item.get('token', '')
            seq_id = item.get('sequence_token', token_raw).strip()
            entities_map[seq_id] = item

        # 2. 🔀 TOPOLOGICAL SORT: Arrange targets so dependencies compute before consumers
        ordered_targets = []
        visited = set()

        def dfs_topological_sort(node_id):
            if node_id in visited:
                return
            if node_id not in entities_map:
                return
            
            # Extract inputs to scan for raw macro injections like <randInt1>
            current_item = entities_map[node_id]
            input_text_blob = json.dumps(current_item.get('inputs', {}))
            parent_tokens = re.findall(r'(?:<([a-zA-Z0-9_]+)>)', input_text_blob)
            
            for parent_id in parent_tokens:
                # If a structural dependency exists inside our execution track, solve it first
                if parent_id in mutation_targets:
                    dfs_topological_sort(parent_id)
            
            visited.add(node_id)
            ordered_targets.append(node_id)

        for target in mutation_targets:
            dfs_topological_sort(target)

        print(f"🔀 [DAG SORT] Original Execution Order: {mutation_targets}")
        print(f"🎯 [DAG SORT] Resolved Topological Order: {ordered_targets}")

        # 3. Iterate sequentially through our safely ordered DAG pipeline
        for sequence_token_id in ordered_targets:
            item = entities_map[sequence_token_id]
            token_raw = item.get('token', '')
            archetype_name = re.sub(r'\d+$', '', token_raw)
            
            pattern_blueprint = get_blueprint_for_token(archetype_name)
            entity_inputs = item.get('inputs', {}) or {}
            entity_inputs['sequence_token'] = sequence_token_id
            
            # REFRESH LOCK-BREAKER
            if sequence_token_id != trigger_token and archetype_name.lower() in ['rand', 'randint']:
                target_payload = next((x for x in all_entities_payload if x.get("sequence_token") == sequence_token_id), None)
                if target_payload:
                    target_payload['simulated_value'] = ""

            # 🚀 CALL ENCAPSULATED UTILITY
            render_results = evaluate_and_format_entity(
                archetype_name=archetype_name,
                sequence_token=sequence_token_id,
                clean_inputs=entity_inputs,
                pattern_blueprint=pattern_blueprint,
                all_entities_payload=all_entities_payload
            )
            
            if not render_results['is_valid'] and render_results['errors']:
                global_errors_ledger[sequence_token_id] = render_results['errors']

            updated_cache[sequence_token_id] = {
                'evaluated_output': render_results['evaluated_output'],
                'latex_output': render_results['latex_output'],
                'extracted_variables': render_results['extracted_variables']
            }

        print("\n📤 [PREVIEW VIEW] FINAL UPDATED CACHE RESPONSE OUT")
        print(json.dumps(updated_cache, indent=2))
        if global_errors_ledger:
            print(f"🚨 ACTIVE STRUCTURAL ERRORS PASSING DOWNSTREAM: {global_errors_ledger}")
        print("="*60 + "\n")

        return JsonResponse({
            'success': len(global_errors_ledger) == 0,
            'updated_cache': updated_cache,
            'errors': global_errors_ledger,
            'error': None
        })

    except Exception as e:
        import traceback
        print("\n💥 [CRITICAL VIEW EXCEPTION] 💥")
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'updated_cache': {},
            'errors': {},
            'error': f"Math Evaluation Warning: {str(e)}"
        }, status=400)

