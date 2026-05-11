from django.shortcuts import render, redirect
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Course, UsersInCourse, UserProfile
from .util import get_valid_unique_name

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
from django.db import IntegrityError

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


from django.apps import apps
from django.contrib.auth.decorators import user_passes_test

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


from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from .models import Course

@login_required
def course_list_view(request):
    user = request.user
    
    # 1. Logic for Visibility
    if user.user_type == 'IT_Support':
        # IT Support sees all courses
        courses = Course.objects.all().select_related('owner')
    elif user.user_type == 'Teacher':
        # Teachers see their own courses OR any template
        courses = Course.objects.filter(
            Q(owner=user) | Q(status='template')
        ).select_related('owner')
    else:
        # Placeholder for Student view
        return render(request, 'assessment_tool/student_placeholder.html', {
            'message': "Student dashboard is coming soon!"
        })

    if request.method == 'POST':
        # 2. Handling the "Create by Copying" (POST logic)
        if 'copy_course' in request.POST:
            source_id = request.POST.get('source_course_id')
            source_course = get_object_or_404(Course, id=source_id)
            
            new_status = None
            if user.user_type == 'IT_Support' and source_course.status == 'developing':
                new_status = 'template'
            elif source_course.status == 'template':
                new_status = 'active'

            if new_status:
                # The model method handles the entire chain of references
                source_course.duplicate_course(new_owner=user, new_status=new_status)
                messages.success(request, f"Full course chain cloned as {new_status}.")
                return redirect('course_list')
            else:
                messages.error(request, "Permission denied for this specific copy operation.")
        
        # HANDLE NEW DEVELOPING COURSE (IT_Support Only)
        elif 'create_developing' in request.POST and user.user_type == 'IT_Support':
            name = request.POST.get('course_name')
            desc = request.POST.get('short_description', '')
            if name:
                Course.create_developing(owner=user, name=name, short_desc=desc)
                messages.success(request, f"New developing course '{name}' created.")
            else:
                messages.error(request, "Course name is required.")
            return redirect('course_list')


    return render(request, 'assessment_tool/course_page.html', {
        'courses': courses, 
        'user_type': user.user_type
    })


from .models import BranchGroup, Assessment, Problem, CustomQuestionDistribution, AssessmentQuestionGroup

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
    

    # print(f"--- DEBUG VIEW --- Folder: {group.name} | Path: {group.get_parent_path()}")


    # 1. Define the QuerySets with your specific optimizations
    folders_qs = BranchGroup.objects.filter(parent=group).select_related('parent__parent')
    courses_qs = Course.objects.filter(branch_location=group).select_related('branch_location')
    assessments_qs = Assessment.objects.filter(branch_location=group)
    problems_qs = Problem.objects.filter(branch_location=group)
    qs_qs = CustomQuestionDistribution.objects.filter(assigned_folder=group).annotate(num_pairs=Count('cqdpair'))
    aq_qs = AssessmentQuestionGroup.objects.filter(branch_location=group)

    # 2. Check if ANY items exist (use the simple filter results for speed)
    # We use the raw filters here because .exists() is faster than running the full optimized query
    has_items = (
        folders_qs.exists() or 
        courses_qs.exists() or 
        assessments_qs.exists() or 
        problems_qs.exists() or
        qs_qs.exists() or
        aq_qs.exists()
    )

    # print(f"folders_qs.exists(): {folders_qs.exists()}\n| courses_qs.exists(): {courses_qs.exists()}\n| assessments_qs.exists(): {assessments_qs.exists()}\n| problems_qs.exists(): {problems_qs.exists()}\n| qs_qs.exists(): {qs_qs.exists()}\n| aq_qs.exists(): {aq_qs.exists()}\n| Summary has_items: {has_items}")

    # 3. Package everything into contents
    contents = {
        'folders': folders_qs,
        'courses': courses_qs,
        'assessments': assessments_qs,
        'problems': problems_qs,
        'question_selection': qs_qs,
        'assessment_selection': aq_qs,
        'has_items': has_items,
    }

    return render(request, 'assessment_tool/partials/column.html', {
        'contents': contents,
        'parent_id': group.id,
        # 'current_path': group.get_parent_path() + group.name + "/",
        'level': int(request.GET.get('level', 1))
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

import json
from django.http import JsonResponse
from .models import BranchGroup

def create_folder(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    data = json.loads(request.body)
    parent_id = data.get('parent_id')
    requested_name = data.get('name', 'New Folder')

    # Get parent and verify ownership
    parent_folder = get_object_or_404(BranchGroup, id=parent_id, owner=request.user)

    # Use the helper logic
    unique_name, error = get_valid_unique_name(BranchGroup, parent_folder, requested_name)
    
    if error:
        return JsonResponse({'error': error}, status=400)

    # Create the folder
    new_folder = BranchGroup.objects.create(
        name=unique_name,
        parent=parent_folder,
        owner=request.user
    )

    return JsonResponse({'status': 'success', 'id': new_folder.id})

from django.http import JsonResponse
import json

def delete_item(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    data = json.loads(request.body)
    item_id = data.get('id')
    item_type = data.get('type')

    # 1. Resolve Object & Path with strict Ownership Verification
    try:
        if item_type == 'folder':
            obj = get_object_or_404(BranchGroup, id=item_id, owner=request.user)
            item_full_path = obj.get_parent_path() + obj.name + "/"
        
        elif item_type == 'course':
            obj = get_object_or_404(Course, id=item_id, owner=request.user)
            loc = obj.branch_location
            item_full_path = loc.get_parent_path() + loc.name + "/"

        elif item_type == 'assessment':
            obj = get_object_or_404(Assessment, id=item_id, owner=request.user)
            loc = obj.branch_location
            item_full_path = loc.get_parent_path() + loc.name + "/"

        elif item_type == 'problem':
            obj = get_object_or_404(Problem, id=item_id, owner=request.user)
            loc = obj.branch_location
            item_full_path = loc.get_parent_path() + loc.name + "/"

        elif item_type == 'assessment_selection':
            # Note: Checking owner via the linked branch_location
            obj = get_object_or_404(AssessmentQuestionGroup, id=item_id, branch_location__owner=request.user)
            loc = obj.branch_location
            item_full_path = loc.get_parent_path() + loc.name + "/"

        else:
            return JsonResponse({'error': f'Unsupported item type: {item_type}'}, status=400)
            
    except Exception as e:
        return JsonResponse({'error': 'Item not found or permission denied.'}, status=404)

    # 2. System Protection Check
    username = request.user.username
    root = f"/Users/{username}_root/"
    protected = [f"{root}Courses/", f"{root}Standalone Assessments/", f"{root}Standalone Problems/"]

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
    obj.delete()
    return JsonResponse({'status': 'success'})

from django.shortcuts import get_object_or_404
from django.http import JsonResponse
import json

def rename_item(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    data = json.loads(request.body)
    item_id = data.get('id')
    item_type = data.get('type')
    new_name = data.get('new_name', '').strip()

    if not new_name:
        return JsonResponse({'error': 'Name cannot be empty.'}, status=400)
    # Regex: Starts/ends with alphanumeric, allows single spaces in between
    if not re.match(r'^[a-zA-Z0-9]+( [a-zA-Z0-9]+)*$', new_name):
        return JsonResponse({'error': 'Names must be alphanumeric with single spaces only.'}, status=400)

    # TODO: check to make sure the 'new_name' doesn't contain any special characters other than space (no '_' and '()' especially since I am going to hard code those in for special circumstances later)

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
    
    # This is where the 404 usually happens - double check ID and Owner
    obj = get_object_or_404(model_class, id=item_id, owner=request.user)

    # Path Protection Logic
    if item_type == 'folder':
        item_full_path = obj.get_parent_path() + obj.name + "/"
    else:
        item_full_path = obj.branch_location.get_parent_path() + obj.branch_location.name + "/"

    username = request.user.username
    protected_roots = [
        f"/Users/{username}_root/Courses/",
        f"/Users/{username}_root/Standalone Assessments/",
        f"/Users/{username}_root/Standalone Problems/"
    ]

    if item_full_path in protected_roots:
        return JsonResponse({'error': 'Cannot rename system folders.'}, status=403)

    if item_full_path.startswith(f"/Users/{username}_root/Courses/"):
        return JsonResponse({'error': 'Cannot rename Course items here.'}, status=403)

    # Collision Check: Find the Parent/Location
    # We need to check siblings (other items with the same parent)
    parent = getattr(obj, 'parent', None) or getattr(obj, 'branch_location', None)
    
    # Automatic Suffix Incrementer Logic
    base_name = new_name
    counter = 1
    
    while True:
        # Check if any sibling has this name
        # We exclude the current object itself so we don't collide with our own name
        duplicate_query = {field_name: new_name}
        if parent:
            if item_type == 'folder':
                duplicate_exists = BranchGroup.objects.filter(parent=parent, **duplicate_query).exclude(id=obj.id).exists()
            else:
                # For items, check the specific model class in that location
                duplicate_exists = model_class.objects.filter(branch_location=parent, **duplicate_query).exclude(id=obj.id).exists()
        else:
            # Root level check
            duplicate_exists = BranchGroup.objects.filter(parent__isnull=True, owner=request.user, **duplicate_query).exclude(id=obj.id).exists()

        if not duplicate_exists:
            break
        
        # If exists, append/increment (n)
        new_name = f"{base_name} ({counter})"
        counter += 1

    # Perform Rename
    setattr(obj, field_name, new_name)
    obj.save()

    return JsonResponse({'status': 'success', 'new_name': new_name})
