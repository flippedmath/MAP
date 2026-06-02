import re
# from .models import BranchGroup, UsersInCourse ... instead of this, use --> BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
from django.apps import apps
from django.http import JsonResponse
import copy
import os
from django.core.files.base import ContentFile
import uuid
from django.db import transaction
from django.contrib import messages
from django.utils import timezone
from django.db import IntegrityError


def get_valid_unique_name(model_class, parent_obj, requested_name, field_name='name', item_type='folder'):
    # 1. Basic Validation: Alphanumeric and single internal spaces
    clean_name = requested_name.strip()
    # I am using a negated character set here: '()_' are not allowed, 
    #      everything else goes, but enforces single spaced words
    # I used to be using this:
    # re.match(r'^[a-zA-Z0-9]+( [a-zA-Z0-9]+)*$', clean_name)
    if not clean_name or not re.match(r'^[^()_]+( [^()_]+)*$', clean_name):
        return None, "Names must not include parenthesis or underscores and must be single spaced only."

    base_name = clean_name
    new_name = clean_name
    counter = 1

    # 2. Collision Loop
    while True:
        lookup = {field_name: new_name}
        if item_type == 'folder':
            # Folders check against 'parent'
            duplicate_exists = model_class.objects.filter(parent=parent_obj, **lookup).exists()
        else:
            # Items (Course, etc) check against 'branch_location'
            duplicate_exists = model_class.objects.filter(branch_location=parent_obj, **lookup).exists()

        if not duplicate_exists:
            break
        
        new_name = f"{base_name} ({counter})"
        counter += 1
    
    return new_name, None

def get_course_image_path(instance, filename):
    """
    Generates a unique path: media/course_images/user_<id>/<uuid>_<filename>
    """
    ext = filename.split('.')[-1]
    # Use a UUID to ensure the filename itself is unique
    unique_filename = f"{uuid.uuid4()}.{ext}"
    # Organize by owner ID so files aren't all in one giant folder
    return os.path.join('course_images', f"user_{instance.owner.user_id}", unique_filename)

def clone_course_payload(old_course, new_folder, new_owner, context):
    new_course = copy.deepcopy(old_course)
    new_course.pk = None
    new_course.id = None
    new_course.owner = new_owner
    new_course.branch_location = new_folder
    # renaming with 'copy of' is not strictly necessary, but a good thing to do anyways
    new_course.name = f"Copy of {old_course.name}"

    try:
        v_parts = old_course.version.split('.')
        if len(v_parts) == 4:
            v_parts[3] = str(int(v_parts[3]) + 1)
            new_course.version = ".".join(v_parts)
        else:
            new_course.version = "0.0.0.1"
    except (ValueError, AttributeError, IndexError):
        new_course.version = "0.0.0.1"

    # Your specific Image Logic
    if old_course.image:
        image_content = old_course.image.read()
        new_filename = f"copy_{os.path.basename(old_course.image.name)}"
        new_course.image.save(new_filename, ContentFile(image_content), save=False)

    new_course.save()
    context['course'] = new_course # Update context for children
    return new_course

def clone_assessment_payload(old_assessment, new_folder, new_owner, context):
    new_asm = copy.deepcopy(old_assessment)
    new_asm.pk = None
    new_asm.owner = new_owner
    new_asm.branch_location = new_folder
    # Link to the course currently being cloned in this tree
    new_asm.course = context['course']
    new_asm.save()
    context['assessment'] = new_asm
    return new_asm

def clone_aqg_payload(old_aqg, new_folder, new_owner, context):
    new_aqg = copy.deepcopy(old_aqg)
    new_aqg.pk = None
    new_aqg.branch_location = new_folder
    new_aqg.assessment = context['assessment']
    new_aqg.save()
    return new_aqg

def clone_cqd_payload(old_cqd, new_folder, new_owner, context):
    new_cqd = copy.deepcopy(old_cqd)
    new_cqd.pk = None
    new_cqd.branch_location = new_folder
    new_cqd.save()
    return new_cqd

def clone_problem_payload(old_prob, new_folder, new_owner, context):
    """
    Clones a explicit Problem database payload and safely replicates 
    its structural server disk asset files to prevent cross-node pointer contamination.
    """
    new_prob = copy.deepcopy(old_prob)
    new_prob.pk = None
    new_prob.id = None
    new_prob.owner = new_owner
    new_prob.branch_location = new_folder
    
    # Safely handle replication of physical custom math script source files on server storage
    # TODO: placeholder for replicating any sub-tables connected to problem
            
    new_prob.save()
    return new_prob


def clone_node_recursive(old_folder, new_parent, new_owner, context=None, starter_node=False):
    if context is None:
        context = {'course': None, 'assessment': None, 'aqg': None, 'cqd': None}

    # I have circular imports unless I import BranchGroup later. So this resolves my problem:
    BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')

    t_name = old_folder.name
    # if it's the first node, change the name, otherwise keep the name the same
    if starter_node:
        # Duplicate the BranchGroup (Folder)
        # We need a NEW folder for the NEW course to satisfy the OneToOne constraint
        t_name = f"{old_folder.name}"
        # This means the name has a (1) or some other number at the end (#).
        #  So crop it out since 'get_valid_unique_name' will add a unique combination back in
        if '(' in t_name:
            split_name = t_name.split()
            t_name = " ".join(split_name[:len(split_name) - 1])
        print(f"Before name: {t_name}")
        t_name, error = get_valid_unique_name(BranchGroup, new_parent, t_name)
        print(f"After name: {t_name}")
        if error:
            return JsonResponse({'error': error}, status=400)

    # 1. Clone the Folder (The Container)
    new_folder = BranchGroup.objects.create(
        owner=new_owner,
        name=t_name,
        parent=new_parent,
        folder_type=old_folder.folder_type,
        order=old_folder.order
    )

    # 2. Check for a Payload (The Math Content)
    # Mapping folder_type to the specific cloning function
    cloner_map = {
        'course': clone_course_payload,
        'assessment': clone_assessment_payload,
        'aqg': clone_aqg_payload,
        'cqd': clone_cqd_payload,
        'problem': clone_problem_payload,
    }

    handler = cloner_map.get(old_folder.folder_type)
    if handler and hasattr(old_folder, old_folder.folder_type):
        # grab the separated table that is tied to the branch_group table row
        old_payload = getattr(old_folder, old_folder.folder_type)

        # The handler clones the object and updates the context
        new_payload = handler(old_payload, new_folder, new_owner, context)
        

    # 4. Recursion: Keep going down the tree
    for child in old_folder.children.all():
        clone_node_recursive(child, new_folder, new_owner, context)

    return new_folder

def send_to_trash(folder, user):
    """
    Quarantines a folder tree into the user's Trash folder.
    """
    with transaction.atomic():
        # 1. Find the user's Trash folder root
        # Adjust the filter name to match how you look up your root folders
        BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
        trash_root = BranchGroup.objects.get(
            name='Trash', 
            parent__name=f"{user.username}_root"
        )
        
        # 2. Track history before breaking links
        folder.previous_parent = folder.parent
        if hasattr(folder, 'course'):
            folder.previous_status = folder.course.status
            
            # 3. Mark the payload status as deleted
            course = folder.course
            course.status = 'deleted'
            course.save()

        # 4. Move physical directory location to Trash root
        folder.parent = trash_root
        folder.save()

def restore_course_payload(request, folder):
    """
    Restores a course: rewinds status, recovers original folder placement.
    """
    course = folder.course
    user = request.user
    
    # 1. Fallback safety check: If original parent was wiped, find the general Courses/ folder
    target_parent = folder.previous_parent
    if not target_parent:
        BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
        target_parent = BranchGroup.objects.get(
            name='Courses', 
            parent__name=f"{user.username}_root"
        )
        
    # 2. Put folder back in its place
    folder.parent = target_parent
    folder.previous_parent = None # Clear history hook
    folder.save()
    
    # 3. Revert Course Status
    course.status = folder.previous_status or 'developing' # Fallback default
    folder.previous_status = None
    course.save()

# --- Placeholders for other types ---
def restore_assessment_payload(request, folder):
    """
    Polymorphic sub-handler to restore an assessment folder out of Trash
    and flip its dashboard status back to 'upcoming'.
    """
    BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
    # 1. Trace up to find the logged-in user's top-level root directory node
    user_root = BranchGroup.objects.filter(owner=request.user, parent__isnull=True).first()
    
    if user_root:
        # 2. Locate the default 'Courses' subfolder provisioned for this user by signals.py
        courses_folder = BranchGroup.objects.filter(
            parent=user_root,
            name='Courses',
            folder_type='folder'
        ).first()
        
        # 3. Move the assessment's folder back under 'Courses' (or fallback to the user root)
        folder.parent = courses_folder if courses_folder else user_root
        folder.save()

    # 4. 🎯 RE-ACTIVATE DASHBOARD ROW (FIXED LOOKUP)
    try:
        # Query the Assessment directly using the current folder's ID
        Assessment = apps.get_model('assessment_tool', 'Assessment')
        assessment = Assessment.objects.filter(branch_location=folder).first()
        
        if assessment:
            assessment.status = 'locked'
            assessment.save()
        else:
            raise ValueError(f"No matching Assessment record found tracking folder ID {folder.id}.")
            
    except Exception as e:
        raise ValueError(f"Failed to synchronize assessment lifecycle status: {str(e)}")
    

# I am currently not going to implement a 'restore' procedure for 'aqg'.
# If it is deleted, then just recreate it
def restore_aqg_payload(request, folder):
    pass

# I am currently not going to implement a 'restore' procedure for 'cqd'.
# If it is deleted, then just recreate it
def restore_cqd_payload(request, folder):
    pass

# I am currently not going to implement a 'restore' procedure for 'folder'.
# If it is deleted, then just recreate it
def restore_folder_payload(request, folder):
    pass

# I am currently not going to implement a 'restore' procedure for 'problem'.
# If it is deleted, then just recreate it
def restore_problem_payload(request, folder):
    pass

def restore_item_from_trash(request, folder):
    """
    Polymorphic dispatcher to restore items from the Trash folder back to production.
    """
    restore_map = {
        'course': restore_course_payload,
        'assessment': restore_assessment_payload,
        'aqg': restore_aqg_payload,
        'cqd': restore_cqd_payload,
        'folder': restore_folder_payload,
        'problem': restore_problem_payload,
    }
    
    handler = restore_map.get(folder.folder_type)
    if handler:
        with transaction.atomic():
            handler(request, folder)
            messages.success(request, f"Successfully restored '{folder.name}'.")
    else:
        messages.error(request, f"Unknown folder type: {folder.folder_type}\nRestore method unknown")


def assign_user_to_course(user, course_obj, authenticate=True):

    is_active = 'active'
    if not authenticate:
        is_active = 'closed'

    try:
        UsersInCourse = apps.get_model('assessment_tool', 'UsersInCourse')
        # 2. Create the entry in the users_in_course junction table
        new_assignment = UsersInCourse.objects.create(
            user=user,
            course=course_obj,
            user_access=is_active,
            creation_date=timezone.now() # Manually setting since blank=True is on the model
        )
        return new_assignment

    except IntegrityError:
        # Triggers if the unique_together constraint checks out (User + Course already exists)
        print("Notice: This user is already assigned to this course.")
        # Optional fallback: Fetch and return the existing record instead
        return UsersInCourse.objects.get(user=user, course=course_obj)


def generate_unique_course_version(dest_status, source_course=None):
    """
    Generates an incremented, unique 4-part version string based on 
    the target destination status and the source course it's copied from.
     Optimised to run all loop iterations completely in memory via a single set-lookup.
    """
    apps = __import__('django.apps', fromlist=['apps']).apps
    Course = apps.get_model('assessment_tool', 'Course')

    # CASE 1: Brand new baseline tracking (No source course / Original Developing)
    if dest_status == 'developing' and source_course is None:
        base_parts = [1, 0, 0, 0]
        target_index = 0  # Increment the first position (1.0.0.0 -> 2.0.0.0)
        
    else:
        # We are copying from an existing course. Split its current version string.
        try:
            base_parts = [int(num) for num in source_course.version.split('.')]
        except (AttributeError, ValueError):
            base_parts = [1, 0, 0, 0]

        # Determine which index position to increment based on state transitions
        if dest_status == 'developing':
            target_index = 0
            base_parts[1], base_parts[2], base_parts[3] = 0, 0, 0
        elif dest_status == 'template':
            target_index = 1
            base_parts[2], base_parts[3] = 0, 0
        elif dest_status == 'active':
            if source_course and source_course.status == 'closed':
                target_index = 3  # Stage 4: Copied from closed (X.Y.Z.W)
            else:
                target_index = 2  # Stage 3: Copied from a template (X.Y.Z.0)
                base_parts[3] = 0 
        else:
            target_index = 3

        # 🆕 Initial increment since we are copying an existing blueprint row
        base_parts[target_index] += 1

    # ==========================================================================
    # 🆕 IN-MEMORY OPTIMISATION STEP
    # Query database exactly ONCE to pull a lightweight hash-set of values
    # ==========================================================================
    if target_index > 0:
        # Narrow down the records by matching the static prefix parts (e.g. "4.2.")
        prefix = ".".join(map(str, base_parts[:target_index])) + "."
        existing_versions = set(
            Course.objects.filter(version__startswith=prefix)
                          .values_list('version', flat=True)
        )
    else:
        # For top-level developing courses, grab all version tracking records in that bucket
        existing_versions = set(
            Course.objects.filter(status='developing')
                          .values_list('version', flat=True)
        )
    # ==========================================================================

    # Memory collision checking loop (O(1) lookups)
    is_unique = False
    while not is_unique:
        potential_version = ".".join(map(str, base_parts))
        
        if potential_version not in existing_versions:
            is_unique = True
        else:
            # Collision detected! Increment the targeted stage index and try again
            base_parts[target_index] += 1

    return potential_version


def calculate_midpoint_order(prev="", next=""):
    """
    Generates a lexicographical midpoint string between prev and next strings.
    Adapted from the project's sort_by_string.py algorithm.
    """

    ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    CHAR_TO_INT = {char: i for i, char in enumerate(ALPHABET)}
    BASE = len(ALPHABET)

    if next and prev >= next:
        raise ValueError(f"Invalid range: {prev} is not less than {next}")

    res = []
    i = 0
    while True:
        p_val = CHAR_TO_INT[prev[i]] if i < len(prev) else -1
        n_val = CHAR_TO_INT[next[i]] if (next and i < len(next)) else BASE
        
        # If there is a gap of at least 2, we can fit a character in between
        if n_val - p_val > 1:
            mid_val = (p_val + n_val) // 2
            res.append(ALPHABET[mid_val])
            break
        
        # If no gap exists (e.g., between 'A' and 'B')
        res.append(ALPHABET[max(0, p_val)])
        i += 1
        
    return "".join(res)

