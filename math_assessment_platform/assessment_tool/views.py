from django.shortcuts import render, redirect
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Course, UsersInCourse, UserProfile
from .models import BranchGroup, Assessment, Problem, CustomQuestionDistribution, AssessmentQuestionGroup
from .util import get_valid_unique_name, send_to_trash, restore_item_from_trash, calculate_midpoint_order
import json
from django.http import JsonResponse
from .models import BranchGroup

from django.db import transaction
from .forms import TeacherRegistrationForm
from .models import EmailAuthentication
import secrets
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.db import IntegrityError
from django.views.decorators.http import require_POST
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

    # 1. Define folders_qs with prefetch_related
    # This grabs the linked objects for ALL folders in this column in one go.
    folders_qs = BranchGroup.objects.filter(parent=group)\
        .select_related('parent__parent')\
        .prefetch_related('course', 'assessment', 'cqd', 'aqg')\
        .order_by('order')

    problems_qs = Problem.objects.filter(branch_location=group).order_by('title')

    # 2. Check if items exist
    has_items = folders_qs.exists() or problems_qs.exists()

    # 3. Package contents
    # We no longer need to pass separate lists for courses/assessments 
    # because they are now "attached" to the objects in folders_qs.
    contents = {
        'folders': folders_qs,
        'problems': problems_qs,
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


def delete_item(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    data = json.loads(request.body)
    item_id = data.get('id')
    item_type = data.get('type')

    # 1. Resolve Object & Path with strict Ownership Verification
    try:
        if item_type in ['folder', 'course', 'assessment', 'assessment_selection', 'question_selection', 'problem']:
            if item_type in ['folder', 'course', 'assessment']:
                # Allow IT Support to fetch any folder container, otherwise restrict to the owner
                #   IT_Support users should have access to delete anything from anyone's Trash as if they owned it
                if request.user.user_type == 'IT_Support':
                    obj = get_object_or_404(BranchGroup, id=item_id)
                else:
                    obj = get_object_or_404(BranchGroup, id=item_id, owner=request.user)
                item_full_path = obj.get_parent_path() + obj.name + "/"

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
                    return JsonResponse({'error': f'User not authenticated to delete: {item_type}'}, status=400)
            elif item_type == 'question_selection':
                if request.user.user_type == 'IT_Support':
                    cqd_item = get_object_or_404(CustomQuestionDistribution, id=item_id)
                else:
                    cqd_item = get_object_or_404(CustomQuestionDistribution, id=item_id, assigned_folder__owner=request.user)
                obj = cqd_item.assigned_folder
            elif item_type == 'problem':
                problem_item = get_object_or_404(Problem, id=item_id, owner=request.user)
                
                # TODO: Placeholder here for removing any sub-problem data in other tables 
                #       before I lose the reference to them
                    
                # Point 'obj' to the folder so it calculates the tracking path and deletes the directory
                obj = problem_item.branch_location

            if not obj:
                return JsonResponse({'error': 'Target branch directory location tracking error.'}, status=400)

            # ✅ Perfectly scoped for ALL types inside the main validation wrapper block
            item_full_path = obj.get_parent_path() + obj.name + "/"

        else:
            return JsonResponse({'error': f'Unsupported item type: {item_type}'}, status=400)
            
    except Exception as e:
        import traceback
        print(f"The course id being queried is = {item_id}")
        print(traceback.format_exc()) # This prints the full stack trace to your terminal console
        return JsonResponse({
            'error': f"Python Exception: {str(e)}",
            'item_id_received': item_id,
            'item_type_received': item_type
        }, status=400)
        return JsonResponse({'error': 'Item not found or permission denied.'}, status=404)

    # 2. System Protection Check
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

    # 3. Empty Check for Folders
    if item_type == 'folder':
        has_content = (
            BranchGroup.objects.filter(parent=obj).exists() or
            Course.objects.filter(branch_location=obj).exists() or
            Assessment.objects.filter(branch_location=obj).exists() or
            Problem.objects.filter(branch_location=obj).exists() or
            AssessmentQuestionGroup.objects.filter(branch_location=obj).exists() or
            CustomQuestionDistribution.objects.filter(assigned_folder=obj).exists()
        )
        if has_content:
            return JsonResponse({'error': 'Folder is not empty.'}, status=400)

    # 4. Execute
    with transaction.atomic():
        if item_type in ['folder', 'course', 'assessment', 'assessment_selection', 'question_selection', 'problem']:
            # Deleting the BranchGroup here runs a clean cascade down to clear the item tables automatically
            obj.delete()
        else:
            return JsonResponse({f'error': 'What kind of object am I tryig to delete?: {item_type}.'}, status=403)
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

        # Ensure field names match your actual model definitions
        model_map = {
            'folder': (BranchGroup, 'name'),
            'course': (Course, 'name'), 
            'assessment': (Assessment, 'name'),
            'problem': (Problem, 'title'),
            'assessment_selection': (AssessmentQuestionGroup, 'name'),
            # can't rename the custom_question_group generated name from get_unique_name
        }

        if item_type not in model_map:
            return JsonResponse({'error': 'Unknown item type.'}, status=400)

        model_class, field_name = model_map[item_type]
        is_it_support = (request.user.user_type == 'IT_Support')
        
        if item_type in ['folder', 'course', 'assessment']:
            if is_it_support:
                obj = get_object_or_404(BranchGroup, id=item_id)
            else:
                obj = get_object_or_404(BranchGroup, id=item_id, owner=request.user)
            item_full_path = obj.get_parent_path() + obj.name + "/"
            parent = obj.parent
        else:
            # Independent items (problems, selection groups) resolve normally
            if is_it_support:
                obj = get_object_or_404(model_class, id=item_id)
            else:
                obj = get_object_or_404(model_class, id=item_id, owner=request.user)
            item_full_path = obj.branch_location.get_parent_path() + obj.branch_location.name + "/"
            parent = obj.branch_location

        # Check to make sure the 'new_name' doesn't contain any special characters 
        #    other than space (no '_' and '()' especially since I am going to hard code 
        #    those in for special circumstances later)
        bg_context_node = obj if item_type == 'folder' else parent
        new_name, error = get_valid_unique_name(BranchGroup, bg_context_node.parent if item_type == 'folder' else bg_context_node, new_name)
        if error:
            return JsonResponse({'error': error}, status=400)

        # # Path Protection Logic
        # if item_type == 'folder':
        #     item_full_path = obj.get_parent_path() + obj.name + "/"
        # else:
        #     item_full_path = obj.branch_location.get_parent_path() + obj.branch_location.name + "/"

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

        # Allow IT Support or owners to change names inside the Courses/ tree via this specific grid
        if item_full_path.startswith(f"/Users/{username}_root/Courses/") and not request.resolver_match.view_name == 'course_list':
            # Note: If you want to allow renames from the courses page but block general Explorer renames,
            # we can skip this check if request path hits your course list, or keep it open for IT Support.
            if not is_it_support and item_type == 'folder' and obj.name in ['Courses', 'Trash']:
                return JsonResponse({'error': 'Cannot rename Course items here.'}, status=403)

        # if item_full_path.startswith(f"/Users/{username}_root/Courses/"):
        #     return JsonResponse({'error': 'Cannot rename Course items here.'}, status=403)

        # Collision Check: Find the Parent/Location
        # We need to check siblings (other items with the same parent)
        # parent = getattr(obj, 'parent', None) or getattr(obj, 'branch_location', None)
        
        # Automatic Suffix Incrementer Logic
        base_name = new_name
        counter = 1
        
        while True:
            duplicate_query = {field_name: new_name}
            if parent:
                if item_type in ['folder', 'course', 'assessment']:
                    # Sibling collision check against the folder structure table
                    duplicate_exists = BranchGroup.objects.filter(parent=parent, name=new_name).exclude(id=obj.id if item_type == 'folder' else obj.id).exists()
                else:
                    duplicate_exists = model_class.objects.filter(branch_location=parent, **duplicate_query).exclude(id=obj.id).exists()
            else:
                duplicate_exists = BranchGroup.objects.filter(parent__isnull=True, owner=obj.owner, name=new_name).exclude(id=obj.id if item_type == 'folder' else obj.id).exists()

            if not duplicate_exists:
                break
            
            new_name = f"{base_name} ({counter})"
            counter += 1

        # --- STEP 4: EXECUTE SYNCHRONIZED DATABASE ATOMIC WRITE ---
        with transaction.atomic():
            if item_type in ['course', 'assessment']:
                # 'obj' is the BranchGroup folder. Rename the folder container:
                obj.name = new_name
                obj.save()

                # Find and rename the connected core payload entity (e.g., Course row)
                payload_relation_str = 'course' if item_type == 'course' else 'assessment'
                if hasattr(obj, payload_relation_str):
                    payload_obj = getattr(obj, payload_relation_str)
                    setattr(payload_obj, field_name, new_name)
                    payload_obj.save()
                    
            elif item_type == 'folder':
                obj.name = new_name
                obj.save()
                
                # If a regular folder maps to a course or assessment payload, sync it too
                if hasattr(obj, 'course'):
                    obj.course.name = new_name
                    obj.course.save()
                elif hasattr(obj, 'assessment'):
                    obj.assessment.name = new_name
                    obj.assessment.save()
            else:
                # Fallback for independent metadata types (problems, selections)
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
        'user_type': user_type if user_type == 'IT_Support' else 'Teacher'
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



