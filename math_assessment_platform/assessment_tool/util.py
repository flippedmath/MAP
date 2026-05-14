import re
from .models import BranchGroup
from django.http import JsonResponse
import copy

def get_valid_unique_name(model_class, parent_obj, requested_name, field_name='name', item_type='folder'):
    # 1. Basic Validation: Alphanumeric and single internal spaces
    clean_name = requested_name.strip()
    if not clean_name or not re.match(r'^[a-zA-Z0-9]+( [a-zA-Z0-9]+)*$', clean_name):
        return None, "Names must be alphanumeric and single spaced only."

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


def clone_course_payload(old_course, new_folder, new_owner, context):
    new_course = copy.deepcopy(old_course)
    new_course.pk = None
    new_course.id = None
    new_course.owner = new_owner
    new_course.branch_location = new_folder
    new_course.name = f"Copy of {old_course.name}"

    # Your specific Version Logic
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

def clone_problem_item(old_prob, new_parent_payload, parent_type):
    """
    Handles cloning a Problem and linking it to its parent, 
    whatever type that parent might be.
    """
    new_prob = copy.deepcopy(old_prob)
    new_prob.pk = None
    
    # Dynamic linking based on what the parent payload was
    if parent_type == 'aqg':
        new_prob.aqg = new_parent_payload
    elif parent_type == 'cqd':
        new_prob.cqd = new_parent_payload
    elif parent_type == 'assessment':
        new_prob.assessment = new_parent_payload
    # etc...
    
    new_prob.save()


def clone_node_recursive(old_folder, new_parent, new_owner, context=None, starter_node=False):
    if context is None:
        context = {'course': None, 'assessment': None, 'aqg': None, 'cqd': None}

    t_name = old_folder.name
    # if it's the first node, change the name, otherwise keep the name the same
    if starter_node:
        # Duplicate the BranchGroup (Folder)
        # We need a NEW folder for the NEW course to satisfy the OneToOne constraint
        t_name = f"Copy of {old_folder.name}"
        t_name, error = get_valid_unique_name(BranchGroup, old_folder.branch_location.parent, t_name)
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
    }

    handler = cloner_map.get(old_folder.folder_type)
    if handler and hasattr(old_folder, old_folder.folder_type):
        old_payload = getattr(old_folder, old_folder.folder_type)
        # The handler clones the object and updates the context
        new_payload = handler(old_payload, new_folder, new_owner, context)
        
        # 3. Handle Problems (Items that can live in any payload type)
        # If the payload has a 'problems' relationship, clone them
        if hasattr(old_payload, 'problems'):
            for old_prob in old_payload.problems.all():
                clone_problem_item(old_prob, new_payload, old_folder.folder_type)

    # 4. Recursion: Keep going down the tree
    for child in old_folder.children.all():
        clone_node_recursive(child, new_folder, new_owner, context)

    return new_folder