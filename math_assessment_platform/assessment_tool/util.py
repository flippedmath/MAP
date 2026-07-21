import re
# from .models import BranchGroup, UsersInCourse, EntitySegment ... instead of this, use --> BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
from django.apps import apps
from django.http import JsonResponse
import copy
import os
import logging
from django.core.files.base import ContentFile
import uuid
from django.db import transaction
from django.contrib import messages
from django.utils import timezone
from django.db import IntegrityError
import random
import json
import math
import sympy as sp
from sympy import Matrix as SymPyMatrix
from sympy.core.relational import Relational
from sympy.parsing.sympy_parser import parse_expr
from sympy.parsing.latex import parse_latex
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# Bare names reserved as SymPy special functions — not allowed as free variables.
# Authors must use a subscript/number suffix (beta_1, gamma2, zeta_3).
RESERVED_SYMPY_GREEK_FUNCTIONS = frozenset({"beta", "gamma", "zeta"})
GREEK_VAR_BASE_PATTERN = (
    r"(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lamda|"
    r"mu|nu|xi|omicron|rho|sigma|tau|upsilon|phi|chi|psi|omega)"
)


def _is_valid_algebraic_variable_name(item):
    """
    Return (ok: bool, error_message: str|None) for a declared variable identifier.
    """
    if not item:
        return False, "Empty variable identifier."
    if item in ("E", "I", "i"):
        return False, (
            f"'{item}' is a reserved mathematical constant in SymPy and cannot be "
            f"used as a variable identifier."
        )
    item_lower = item.lower()
    if item_lower in RESERVED_SYMPY_GREEK_FUNCTIONS:
        return False, (
            f"'{item}' is a reserved SymPy function (not a free variable). "
            f"Use a subscripted form such as '{item_lower}_1' if you need it as a variable."
        )
    is_standard = bool(re.match(r"^[a-zA-Z][0-9]*$", item))
    is_subscript = bool(re.match(r"^[a-zA-Z]_[0-9]+$", item))
    greek = GREEK_VAR_BASE_PATTERN
    is_greek_base = bool(re.match(rf"^{greek}$", item_lower))
    is_greek_num = bool(re.match(rf"^{greek}[0-9]+$", item_lower))
    is_greek_sub = bool(re.match(rf"^{greek}_[0-9]+$", item_lower))
    if not (is_standard or is_subscript or is_greek_base or is_greek_num or is_greek_sub):
        return False, f"'{item}' is not a valid algebraic variable identifier."
    return True, None


def get_valid_unique_name(model_class, parent_obj, requested_name, field_name='name', item_type='folder', exclude_id=None):
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
            qs = model_class.objects.filter(parent=parent_obj, **lookup)
        else:
            # Items (Course, etc) check against 'branch_location'
            qs = model_class.objects.filter(branch_location=parent_obj, **lookup)

        if exclude_id is not None:
            qs = qs.exclude(id=exclude_id)

        if not qs.exists():
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
    copy_problem_content(old_prob, new_prob)
    return new_prob


def copy_problem_content(old_prob, new_prob):
    """
    Deep-copy QuestionBlock and EntitySegment rows from old_prob onto new_prob.
    Remaps parent_entity FKs so nested entity graphs stay intact on the clone.
    """
    QuestionBlock = apps.get_model('assessment_tool', 'QuestionBlock')
    EntitySegment = apps.get_model('assessment_tool', 'EntitySegment')

    def as_json_text(value):
        # Postgres json/jsonb columns may arrive as dict/list via the driver even
        # when the Django field is TextField; re-serialize so INSERTs stay valid JSON.
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return value

    for qb in QuestionBlock.objects.filter(problem=old_prob):
        QuestionBlock.objects.create(
            problem=new_prob,
            content=as_json_text(qb.content),
            space_allocation=as_json_text(qb.space_allocation),
        )

    old_segments = list(EntitySegment.objects.filter(problem=old_prob).order_by('id'))
    id_map = {}
    for seg in old_segments:
        new_seg = EntitySegment.objects.create(
            problem=new_prob,
            problem_type_id_originator=seg.problem_type_id_originator,
            content=as_json_text(seg.content),
            points=seg.points,
            default_answer=seg.default_answer,
            is_answer_to_multi_choice=seg.is_answer_to_multi_choice,
            space_allocation=as_json_text(seg.space_allocation),
            parent_entity=None,
        )
        id_map[seg.id] = new_seg

    for seg in old_segments:
        if seg.parent_entity_id and seg.parent_entity_id in id_map:
            new_seg = id_map[seg.id]
            new_seg.parent_entity = id_map[seg.parent_entity_id]
            new_seg.save(update_fields=['parent_entity'])


def duplicate_problem_in_aqg(source_problem, owner):
    """
    Create an independent copy of source_problem under the same parent folder
    (AQG section or CQD problem-set folder). Title/branch name become
    'Copy of <original>' (uniquified).
    Returns (new_problem, None) on success or (None, error_message) on failure.
    """
    BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
    Problem = apps.get_model('assessment_tool', 'Problem')
    AssessmentQuestionGroup = apps.get_model('assessment_tool', 'AssessmentQuestionGroup')
    CustomQuestionDistribution = apps.get_model('assessment_tool', 'CustomQuestionDistribution')

    if not source_problem.branch_location_id:
        return None, "Problem is missing its folder location."

    source_branch = source_problem.branch_location
    parent_directory = source_branch.parent
    if not parent_directory:
        return None, "Problem folder is missing its parent location."

    aqg = source_problem.aqg
    cqd = source_problem.cqd

    # Resolve AQG / CQD from folder ancestry when FKs are incomplete
    if not aqg:
        aqg = AssessmentQuestionGroup.objects.filter(branch_location_id=parent_directory.id).first()
        if not aqg and parent_directory.parent_id:
            aqg = AssessmentQuestionGroup.objects.filter(
                branch_location_id=parent_directory.parent_id
            ).first()
    if not cqd and getattr(parent_directory, 'folder_type', None) == 'cqd':
        cqd = CustomQuestionDistribution.objects.filter(assigned_folder=parent_directory).first()

    requested_name = f"Copy of {source_problem.title}".strip()
    # get_valid_unique_name rejects parentheses; strip a trailing " (N)" uniquifier first
    if '(' in requested_name:
        parts = requested_name.split()
        if parts and parts[-1].startswith('(') and parts[-1].endswith(')'):
            requested_name = " ".join(parts[:-1]).strip()
    if len(requested_name) > 255:
        requested_name = requested_name[:255].rstrip()

    final_name, name_err = get_valid_unique_name(
        model_class=BranchGroup,
        parent_obj=parent_directory,
        requested_name=requested_name,
    )
    if name_err:
        return None, name_err

    next_sibling = (
        BranchGroup.objects.filter(parent=parent_directory, order__gt=source_branch.order or "")
        .order_by('order')
        .first()
    )
    new_order = calculate_midpoint_order(
        source_branch.order or "",
        next_sibling.order if next_sibling else "",
    )

    with transaction.atomic():
        new_branch = BranchGroup.objects.create(
            owner=owner,
            name=final_name,
            parent=parent_directory,
            folder_type='problem',
            order=new_order,
        )
        new_problem = Problem.objects.create(
            branch_location=new_branch,
            title=final_name,
            aqg=aqg,
            cqd=cqd,
            problem_status=source_problem.problem_status or 'draft',
        )
        copy_problem_content(source_problem, new_problem)
        if cqd:
            _ensure_cqd_pair(cqd, new_problem, new_branch)
            refresh_cqd_identity(cqd)

    return new_problem, None


def _strip_name_uniquifier(name):
    requested_name = (name or "").strip()
    if '(' in requested_name:
        parts = requested_name.split()
        if parts and parts[-1].startswith('(') and parts[-1].endswith(')'):
            requested_name = " ".join(parts[:-1]).strip()
    return requested_name


def _ensure_cqd_pair(cqd, problem, branch):
    CqdPair = apps.get_model('assessment_tool', 'CqdPair')
    pair = CqdPair.objects.filter(parent_aqd=cqd, problem=problem).first()
    if pair:
        if pair.branch_id != branch.id:
            pair.branch = branch
            pair.save(update_fields=['branch'])
        return pair
    return CqdPair.objects.create(parent_aqd=cqd, problem=problem, branch=branch)


def _clear_cqd_membership(problem):
    """Detach problem from any CQD membership rows and clear problem.cqd."""
    CqdPair = apps.get_model('assessment_tool', 'CqdPair')
    old_cqd = problem.cqd
    CqdPair.objects.filter(problem=problem).delete()
    if problem.cqd_id:
        problem.cqd = None
    return old_cqd


def refresh_cqd_identity(cqd):
    """
    Recompute problem-set count from folder children and sync display/folder names.
    Returns (display_name, count).
    """
    BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
    if not cqd or not cqd.assigned_folder_id:
        return ("Problem Set", 0)

    count = BranchGroup.objects.filter(
        parent=cqd.assigned_folder,
        folder_type='problem',
    ).count()
    cqd.num_pairs = count
    display_name = cqd.get_display_name()
    folder_name = cqd.get_unique_name()
    folder = cqd.assigned_folder
    if folder.name != folder_name:
        folder.name = folder_name
        folder.save()
    return display_name, count


def count_problems_in_cqd(cqd):
    BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
    if not cqd or not cqd.assigned_folder_id:
        return 0
    return BranchGroup.objects.filter(parent=cqd.assigned_folder, folder_type='problem').count()


def move_problem_to_aqg(problem, target_aqg):
    """
    Move a problem into another Assessment Question Group section on the same
    assessment (top-level of that section, not inside a problem set).
    Appends to the end of the target section's child list.
    Returns (problem, None) on success or (None, error_message) on failure.
    """
    BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')

    if not problem.branch_location_id:
        return None, "Problem is missing its folder location."

    branch = problem.branch_location
    target_parent = target_aqg.branch_location
    if not target_parent:
        return None, "Target question group section is missing its folder location."

    source_aqg = problem.aqg
    if source_aqg and source_aqg.assessment_id != target_aqg.assessment_id:
        return None, "Target section belongs to a different assessment."

    already_top_level = (
        branch.parent_id == target_parent.id
        and not problem.cqd_id
    )
    if already_top_level:
        return None, "Problem is already in that section."

    requested_name = _strip_name_uniquifier(problem.title or branch.name or "Problem")
    final_name, name_err = get_valid_unique_name(
        model_class=BranchGroup,
        parent_obj=target_parent,
        requested_name=requested_name,
        exclude_id=branch.id,
    )
    if name_err:
        return None, name_err

    last_child = (
        BranchGroup.objects.filter(parent=target_parent)
        .exclude(id=branch.id)
        .order_by('order')
        .last()
    )
    new_order = calculate_midpoint_order(last_child.order if last_child else "", "")

    with transaction.atomic():
        old_cqd = _clear_cqd_membership(problem)

        branch.parent = target_parent
        branch.order = new_order
        branch.name = final_name
        branch.save()

        problem.aqg = target_aqg
        problem.title = final_name
        problem.save()

        if old_cqd:
            refresh_cqd_identity(old_cqd)

    return problem, None


def move_problem_to_cqd(problem, target_cqd):
    """
    Move a problem into a Custom Question Distribution (problem set) folder.
    Appends to the end of that set's child list and records a CqdPair row.
    Returns (problem, None) or (None, error_message).
    """
    BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
    AssessmentQuestionGroup = apps.get_model('assessment_tool', 'AssessmentQuestionGroup')

    if not problem.branch_location_id:
        return None, "Problem is missing its folder location."

    target_parent = target_cqd.assigned_folder
    if not target_parent:
        return None, "Problem set is missing its folder location."

    branch = problem.branch_location

    # CQD must live under an AQG section
    section_aqg = AssessmentQuestionGroup.objects.filter(
        branch_location_id=target_parent.parent_id
    ).select_related('assessment').first()
    if not section_aqg:
        return None, "Problem set is not inside a question group section."

    if problem.aqg_id and problem.aqg.assessment_id != section_aqg.assessment_id:
        return None, "Problem set belongs to a different assessment."

    if branch.parent_id == target_parent.id and problem.cqd_id == target_cqd.id:
        return None, "Problem is already in that problem set."

    requested_name = _strip_name_uniquifier(problem.title or branch.name or "Problem")
    final_name, name_err = get_valid_unique_name(
        model_class=BranchGroup,
        parent_obj=target_parent,
        requested_name=requested_name,
        exclude_id=branch.id,
    )
    if name_err:
        return None, name_err

    last_child = (
        BranchGroup.objects.filter(parent=target_parent)
        .exclude(id=branch.id)
        .order_by('order')
        .last()
    )
    new_order = calculate_midpoint_order(last_child.order if last_child else "", "")

    with transaction.atomic():
        old_cqd = problem.cqd if problem.cqd_id != target_cqd.id else None
        if old_cqd:
            apps.get_model('assessment_tool', 'CqdPair').objects.filter(
                parent_aqd=old_cqd, problem=problem
            ).delete()

        branch.parent = target_parent
        branch.order = new_order
        branch.name = final_name
        branch.save()

        problem.aqg = section_aqg
        problem.cqd = target_cqd
        problem.title = final_name
        problem.save()

        _ensure_cqd_pair(target_cqd, problem, branch)
        display_name, count = refresh_cqd_identity(target_cqd)
        if old_cqd:
            refresh_cqd_identity(old_cqd)

    problem._cqd_display_name = display_name
    problem._cqd_count = count
    return problem, None


def remove_problem_from_cqd(problem):
    """
    Move a problem out of its problem set back to the parent AQG section,
    inserting it immediately after the problem-set folder in sibling order.
    Returns (problem, None) or (None, error_message).
    """
    BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
    AssessmentQuestionGroup = apps.get_model('assessment_tool', 'AssessmentQuestionGroup')
    CustomQuestionDistribution = apps.get_model('assessment_tool', 'CustomQuestionDistribution')

    if not problem.branch_location_id:
        return None, "Problem is missing its folder location."

    branch = problem.branch_location
    cqd = problem.cqd
    if not cqd and branch.parent_id:
        cqd = CustomQuestionDistribution.objects.filter(
            assigned_folder_id=branch.parent_id
        ).select_related('assigned_folder').first()

    if not cqd or not cqd.assigned_folder_id:
        return None, "Problem is not inside a problem set."

    cqd_folder = cqd.assigned_folder
    section_parent = cqd_folder.parent
    if not section_parent:
        return None, "Problem set is missing its parent section folder."

    section_aqg = AssessmentQuestionGroup.objects.filter(
        branch_location_id=section_parent.id
    ).first()
    if not section_aqg:
        return None, "Could not resolve the parent question group section."

    if branch.parent_id != cqd_folder.id:
        return None, "Problem is not currently inside that problem set folder."

    requested_name = _strip_name_uniquifier(problem.title or branch.name or "Problem")
    final_name, name_err = get_valid_unique_name(
        model_class=BranchGroup,
        parent_obj=section_parent,
        requested_name=requested_name,
        exclude_id=branch.id,
    )
    if name_err:
        return None, name_err

    next_sibling = (
        BranchGroup.objects.filter(parent=section_parent, order__gt=cqd_folder.order or "")
        .exclude(id=branch.id)
        .order_by('order')
        .first()
    )
    new_order = calculate_midpoint_order(
        cqd_folder.order or "",
        next_sibling.order if next_sibling else "",
    )

    with transaction.atomic():
        _clear_cqd_membership(problem)

        branch.parent = section_parent
        branch.order = new_order
        branch.name = final_name
        branch.save()

        problem.aqg = section_aqg
        problem.cqd = None
        problem.title = final_name
        problem.save()

        display_name, count = refresh_cqd_identity(cqd)

    problem._cqd_display_name = display_name
    problem._cqd_count = count
    problem._source_cqd_id = cqd.id
    problem._aqg_id = section_aqg.id
    return problem, None


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
        t_name, error = get_valid_unique_name(BranchGroup, new_parent, t_name)
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
    Handles empty bounds cleanly for front/back insertions to avoid sorting flips
    and string structural expansion.
    """

    ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    CHAR_TO_INT = {char: i for i, char in enumerate(ALPHABET)}
    BASE = len(ALPHABET)

    # 🎯 EDGE CASE 1: Initial item or completely empty list context
    if not prev and not next:
        return "M"  # Pick a stable character right near the middle of the alphabet

    # 🎯 EDGE CASE 2: Moving an item to the absolute FRONT of the list (prev is empty)
    if not prev and next:
        for i, char in enumerate(next):
            val = CHAR_TO_INT[char]
            if val > 0:
                # Decrement this character to make it smaller, then buffer the midpoint space
                return next[:i] + ALPHABET[val - 1] + ALPHABET[BASE // 2]
        # Fallback if next is entirely '0' elements (e.g. "000") -> pad '0's and append mid-alphabet character
        return "0" * len(next) + ALPHABET[BASE // 2]

    # 🎯 EDGE CASE 3: Appending an item to the absolute BACK of the list (next is empty)
    if prev and not next:
        last_char = prev[-1]
        last_val = CHAR_TO_INT[last_char]
        if last_val < BASE - 1:
            # Increment the last character by 1 to keep the key short and readable
            return prev[:-1] + ALPHABET[last_val + 1]
        # Fallback if the string already ends with 'z' -> extend with a mid-alphabet safety character
        return prev + ALPHABET[BASE // 2]

    # --- Standard Range Validation ---
    if next and prev >= next:
        raise ValueError(f"Invalid range: {prev} is not less than {next}")

    # --- Core Midpoint String Matching Algorithm Loop ---
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



class SymPyAssessmentEngine:

    @classmethod
    def generate_sympy_decoys(cls, correct_value_str, count=3):
        """
        Generates common algebraic wrong-answer distractors dynamically.
        E.g., sign flips, adding/subtracting 1, or multiplying constants.
        """
        decoys = set()
        try:
            expr = parse_expr(correct_value_str)
            
            # Common mutations
            mutations = [
                lambda e: -e,                           # Sign mutation
                lambda e: e + 1,                        # Off-by-one mutation
                lambda e: e - 1,
                lambda e: e * 2,                        # Scale mutation
                lambda e: parse_expr(f"({str(e)})**2")  # Power mutation
            ]
            
            random.shuffle(mutations)
            for mutate in mutations:
                if len(decoys) >= count:
                    break
                try:
                    decoy_expr = mutate(expr)
                    decoy_str = str(sp.simplify(decoy_expr))
                    if decoy_str != str(sp.simplify(expr)):
                        decoys.add(decoy_str)
                except Exception:
                    continue
        except Exception:
            pass
            
        # Fallback to simple random numbers if algebra parsing fails
        while len(decoys) < count:
            decoys.add(str(random.randint(-10, 10)))
            
        return list(decoys)

    @classmethod
    def grade_mathematical_expression(cls, student_input_str, correct_formula_str, expected_structure=None):
        """
        Grades expression inputs based on two tiers:
        1. Equivalence via simplify() == 0
        2. Structural form verification via UnevaluatedExpr or string matching
        Returns: (score_multiplier, tracking_flag)
        """
        try:
            student_ans = parse_expr(student_input_str)
            correct_ans = parse_expr(correct_formula_str)
            
            # Tier 1: Value Equivalence Verification
            is_equivalent = sp.simplify(student_ans - correct_ans) == 0
            
            if not is_equivalent:
                return 0.0, "INCORRECT_VALUE"
            
            # Tier 2: Structural Verification (e.g., Factored or Expanded Form)
            if expected_structure == "Factor":
                # Ensure the student answer's string structure matches a factored structure pattern
                is_factored = student_input_str.count('(') >= correct_formula_str.count('(')
                if not is_factored:
                    return 0.5, "VALUE_MATCH_STRUCTURE_MISMATCH"
                    
            return 1.0, "PERFECT_MATCH"
            
        except Exception:
            return 0.0, "SYNTAX_PARSE_ERROR"
        

    @classmethod
    def check_syntax_validity(cls, expression_str: str) -> tuple[bool, str]:
        """
        Verifies if an expression string is mathematically readable.
        Tries standard SymPy parsing first, then falls back to a LaTeX syntax check.
        Returns: (is_valid, error_message_or_empty_string)
        """
        if not expression_str or not isinstance(expression_str, str):
            return False, "Expression is empty or an invalid data type."
            
        # Check A: Standard Python/SymPy expression string match
        try:
            parse_expr(expression_str, evaluate=False)
            return True, ""
        except Exception as standard_err:
            # Save the error string to show if LaTeX fallback also fails
            standard_error_msg = str(standard_err)
            
        # Check B: LaTeX notation compilation fallback
        try:
            parse_latex(expression_str)
            return True, ""
        except Exception as latex_err:
            # If BOTH fail, provide a detailed message combining the standard breakdown
            # or pointing out the parser syntax failure.
            detailed_msg = f"Invalid math syntax: {standard_error_msg} (LaTeX parse note: {str(latex_err)})"
            return False, detailed_msg
        
    @classmethod
    def evaluate_formula_operations(cls, expression_str: str, method: str, variables: list, solve_for: str) -> str:
        """
        Parses a formula string (Standard or LaTeX) and executes algebraic mutations.
        Methods: 'leave as formula', 'simplify', 'expand polynomial', 'factor polynomial', 'variable substitution'
        """
        if not expression_str:
            return ""

        # 1. Parse into a live SymPy object (Standard with LaTeX fallback)
        try:
            # 🎯 CRITICAL: evaluate=False prevents SymPy from instantly calculating 
            # the answer, preserving operations like integrals/derivatives as symbols.
            expr = parse_expr(str(expression_str), evaluate=False)
        except Exception:
            try:
                expr = parse_latex(str(expression_str))
            except Exception as e:
                return f"[Parsing Error: {str(e)}]"

        # 2. Route the expression based on the selected dropdown method choice
        try:
            method = method.strip().lower() if method else "leave as formula"

            if method == "simplify":
                # 🚧 Placeholder for future simplification logic
                return "[Placeholder: Simplify Method Display]"

            elif method == "expand polynomial":
                # 🚧 Placeholder for future polynomial expansion logic
                return "[Placeholder: Expand Polynomial Method Display]"

            elif method == "factor polynomial":
                # 🚧 Placeholder for future polynomial de-expansion logic
                return "[Placeholder: Factor Polynomial Method Display]"            

            elif method == "variable substitution":
                # 🚧 Placeholder for future algebraic variable isolation logic
                return f"[Placeholder: Solve for {solve_for or '_'} Method Display]"

            # 🎯 Default fallback: 'leave as formula'
            # Convert the unevaluated SymPy object directly into a clean LaTeX math string
            return sp.latex(expr)

        except Exception as eval_err:
            return f"[Evaluation Error: {str(eval_err)}]"
        


class EntityValidationError(Exception):
    """Custom exception for mathematical datatype or validation errors in the assessment engine."""
    def __init__(self, message, token=None, field_slot=None):
        super().__init__(message)
        self.message = message
        self.token = token            # The token where the error occurred (e.g., 'matrix1')
        self.field_slot = field_slot  # The specific input slot (e.g., 'cells')
        
    def __str__(self):
        if self.token:
            return f"[{self.token}] {self.message}"
        return self.message


def fetch_sibling_entity_by_token(problem_obj, target_token):
    """
    Scans all EntitySegment records assigned to a specific problem instance,
    parses their serialized JSON content, and returns the entity that matches
    the specified client-side string token.
    """
    # Grab all segments belonging to this problem to narrow down our lookup space
    EntitySegment = apps.get_model('assessment_tool', 'EntitySegment')
    sibling_segments = EntitySegment.objects.filter(problem=problem_obj)
    
    for segment in sibling_segments:
        if not segment.content:
            continue
            
        try:
            meta = json.loads(segment.content)
            # Check if this segment's internal JSON token matches our target
            if meta.get("token") == target_token:
                return segment
        except (json.JSONDecodeError, TypeError):
            # If a row contains corrupted or unparseable JSON, skip it safely
            continue
            
    # Raise our newly enhanced validation exception if the token cannot be resolved
    raise EntityValidationError(
        message=f"The entity token reference '<{target_token}>' could not be found within this problem's configuration scope.",
        token=target_token
    )

def validate_entity_node_datatype(entity_segment_obj):
    """
    Recursively checks that an entity segment's inputs (whether static 
    or linked child entities) conform to expected mathematical types.
    """
    meta = json.loads(entity_segment_obj.content)
    ent_type = entity_segment_obj.problem_type_id_originator.name

    # Example Check: Validating a Matrix Variable's Cells
    if ent_type == "variable_matrix":
        cells = meta.get("cells", [])
        for row in cells:
            for cell_value in row:
                # If it's a linked token, fetch the child record and check its type
                if str(cell_value).startswith("<") and str(cell_value).endswith(">"):
                    child_token = cell_value.strip("<>")
                    # Query database for the child segment linked under this problem
                    # (Assuming a helper lookup method exists)
                    child_entity = fetch_sibling_entity_by_token(entity_segment_obj.problem, child_token)
                    
                    if child_entity.problem_type_id_originator.name == "variable_string_array":
                        raise EntityValidationError(
                            f"Type Mismatch: Matrix cells cannot accept String Array token '{cell_value}'."
                        )
                else:
                    # If it's a static user input, verify SymPy can parse it as a valid scalar expression
                    try:
                        parsed = sp.parse_expr(str(cell_value))
                        if isinstance(parsed, (sp.Matrix, str)):
                            raise EntityValidationError(f"Invalid static value '{cell_value}' inside matrix cell.")
                    except Exception:
                        raise EntityValidationError(f"Syntax Error: '{cell_value}' is not a valid mathematical statement.")

    return True

class BaseEntity:
    """
    Abstract validation base class for processing structural configurations
    against seeded format patterns stored in the EntityType table.
    """
    def __init__(self, data, pattern_blueprint, all_entities_payload=None):
        self.data = data  # The raw inputs dictionary mapping (e.g. {"min": "100", "max": "<randInt2>"})
        self.pattern_blueprint = pattern_blueprint  # The matched format_pattern dictionary
        self.all_entities_payload = all_entities_payload or []
        self.cleaned_data = {}
        self.runtime_values = {} # 🎯 Holds real numbers for validation/evaluation
        self.errors = {}

    def resolve_numeric_value(self, input_key, default_fallback=0):
        """
        🎯 GENERALIZED UTILITY METHOD
        Safely extracts and resolves a numeric input field key down to a clean integer/float primitive.
        Handles direct numbers, numeric string digits, and recursive token macro definitions uniformly.
        """
        val = self.runtime_values.get(input_key)
        
        if val is None:
            val = self.data.get(input_key) if isinstance(self.data, dict) else None

        if val is None:
            return default_fallback

        if isinstance(val, str) and re.match(r"^<([^>]+)>$", val.strip()):
            try:
                val = self.resolve_token_dependency(val)
            except Exception:
                return default_fallback

        try:
            if isinstance(val, str):
                val = val.strip()
            return int(float(val)) if "." not in str(val) else float(val)
        except (ValueError, TypeError):
            return default_fallback

    def insert_implicit_multiplication(self, formula_str: str) -> str:
        """
        Shared math-expression normalizer used by formula and matrix entities.
        Converts caret powers (^) to SymPy exponents (**) and inserts implicit
        multiplication (e.g. 5x -> 5*x, (x+1)(x-1) -> (x+1)*(x-1)).
        """
        if not formula_str:
            return ""

        s = str(formula_str).strip()

        # Convert standard caret power notation to SymPy Python exponents
        s = s.replace('^', '**')

        # SymPy callables (longer names first). Include unevaluated class names
        # (Integral/Derivative/Limit) so linking '<formulaN>' whose simulated
        # value is str(Integral(...)) is not mangled into Integral*(...).
        funcs = (
            r'(?:'
            r'asin|acos|atan|acot|acsc|asec|'
            r'sinh|cosh|tanh|coth|csch|sech|'
            r'asinh|acosh|atanh|acoth|acsch|asech|'
            r'sin|cos|tan|cot|csc|sec|'
            r'exp|log|ln|sqrt|conjugate|'
            r'Integral|Derivative|Limit|Sum|Product|'
            r'diff|integrate|limit'
            r')'
        )

        # 1. Number followed by a letter/variable/backslash (e.g., 8x -> 8*x)
        s = re.sub(r'(\d)([a-zA-Z\\])', r'\1*\2', s)

        # 2. Number followed by an opening parenthesis (e.g., 8(x+1) -> 8*(x+1))
        s = re.sub(r'(\d)\(', r'\1*(', s)

        # 3. Standalone variable followed by '(' excluding system function names
        s = re.sub(r'\b(?!' + funcs + r'\b)([a-zA-Z\d_]+)\(', r'\1*(', s)

        # 4. Closing parenthesis followed by an opening parenthesis
        s = re.sub(r'\)\(', r')*(', s)

        # 5. Closing parenthesis followed by a number or variable
        s = re.sub(r'\)([\d[a-zA-Z])', r')*\1', s)

        # 6. Variable followed by a known math function name
        s = re.sub(r'\b(?!' + funcs + r'\b)([a-zA-Z\d_]+)(' + funcs + r')\b', r'\1*\2', s)

        # 7. Numbers before functions
        s = re.sub(r'(\d)(' + funcs + r')\b', r'\1*\2', s)

        # 8. Lowercase standalone i is the imaginary unit (SymPy I), not a free
        # variable. Run after digit/letter splits so e.g. 4i → 4*i → 4*I.
        # Word boundaries keep sin/pi/limit/xi/etc. intact.
        s = re.sub(r'\bi\b', 'I', s)

        return s

    def parse_math_expression(self, expression_str, local_dict=None, evaluate=False):
        """
        Parse a user/math expression with the same normalization rules as FormulaEntity.
        """
        normalized = self.insert_implicit_multiplication(str(expression_str))
        return sp.parse_expr(normalized, local_dict=local_dict or {}, evaluate=evaluate)

    def strip_trivial_multiplicative_ones(self, expr):
        """
        Remove evaluate=False artifacts like Mul(-1, 1) (-> -1) and other *1 / 1* factors
        without expanding or otherwise rewriting the expression tree.
        """
        if isinstance(expr, sp.MatrixBase):
            return expr.applyfunc(self.strip_trivial_multiplicative_ones)
        if isinstance(expr, tuple):
            return tuple(self.strip_trivial_multiplicative_ones(item) for item in expr)
        if not isinstance(expr, sp.Basic):
            return expr

        def _is_one(factor):
            return factor == 1 or factor == sp.Integer(1)

        if isinstance(expr, sp.Mul):
            factors = [self.strip_trivial_multiplicative_ones(arg) for arg in expr.args]
            factors = [factor for factor in factors if not _is_one(factor)]
            if not factors:
                return sp.Integer(1)
            if len(factors) == 1:
                return factors[0]
            return sp.Mul(*factors, evaluate=False)

        if expr.args:
            new_args = tuple(self.strip_trivial_multiplicative_ones(arg) for arg in expr.args)
            if new_args != expr.args:
                try:
                    return expr.func(*new_args, evaluate=False)
                except TypeError:
                    return expr.func(*new_args)
        return expr

    def is_valid(self):
        self.errors = {}
        self.cleaned_data = {}
        self.runtime_values = {} # Reset
        
        provided_inputs = self.data
        blueprint_inputs = self.pattern_blueprint.get("inputs", {})
        
        if not isinstance(provided_inputs, dict):
            self.errors["inputs"] = "The provided inputs field must be a structured key-value map."
            return False

        for input_key, field_rules in blueprint_inputs.items():
            expected_field_type = field_rules.get("field")
            has_default = "default" in field_rules
            default_value = field_rules.get("default")
            
            if input_key not in provided_inputs:
                if has_default:
                    self.cleaned_data[input_key] = default_value
                    self.runtime_values[input_key] = default_value
                    continue
                else:
                    self.errors[input_key] = f"Missing required configuration property: '{input_key}'."
                    continue

            user_value = provided_inputs[input_key]
            value_to_validate = user_value
            
            if isinstance(user_value, str) and re.match(r"^<([^>]+)>$", user_value.strip()):
                try:
                    value_to_validate = self.resolve_token_dependency(user_value)
                except ValidationError as e:
                    self.errors[input_key] = e.message
                    continue

            try:
                validated_result = self.validate_field_type(
                    input_key, value_to_validate, expected_field_type
                )
                self.runtime_values[input_key] = validated_result
                self.cleaned_data[input_key] = user_value
                    
            except ValidationError as e:
                self.errors[input_key] = e.message

        return len(self.errors) == 0

    def resolve_token_dependency(self, token_string):
        """
        Recursively extracts the real-time simulation output value of a cross-referenced token tag.
        """
        clean_sequence_token = token_string.replace("<", "").replace(">", "").strip()
        

        target_payload = next(
            (item for item in self.all_entities_payload if (item.get("sequence_token") or item.get("indexed_token") or "") == clean_sequence_token),
            None
        )
        
        if not target_payload:
            raise ValidationError(f"Linked reference token <{clean_sequence_token}> could not be found in active workspace components.")
        
        token_archetype = target_payload.get("token")
        token_inputs = target_payload.get("inputs", {})
        token_blueprint = get_blueprint_for_token(token_archetype)
        
        
        # 🎯 SHORT-CIRCUIT FOR RANDOM ARCHETYPES
        # If the target is an upstream random entity, reuse its client-side generated value
        # 🎯 CACHE HIT: Check if we already have a locked-in client string or a freshly computed value
        cached_val = target_payload.get('simulated_value', '')
        if token_archetype in ['rand', 'randInt'] and cached_val != "":
            return cached_val

        # 🎯 CACHE MISS: If cached_val is "", evaluate via sub-engine sub-pipeline
        dependency_validator = get_entity_validator(
            token_archetype, 
            token_inputs, 
            token_blueprint, 
            all_entities_payload=self.all_entities_payload
        )
        
        if not dependency_validator.is_valid():
            raise ValidationError(f"Dependency error: Linked component <{clean_sequence_token}> has outstanding validation errors.")
            
        resolved_value = str(dependency_validator.evaluate_output())
        
        # 🎯 WRITE-BACK LOCK: Save the freshly rolled number directly back into the payload entry list
        if token_archetype in ['rand', 'randInt']:
            target_payload['simulated_value'] = resolved_value  # This updates it in all_entities_payload by reference!

        return resolved_value

    def validate_field_type(self, key, value, field_type):
        if field_type == "integer":
            if value == "" or value is None:
                return None
            try:
                return int(value)
            except:
                raise ValidationError(f"Value for '{key}' must be a valid integer.")
        elif field_type == "double":
            if value == "" or value is None:
                return None
            try:
                return float(value)
            except:
                raise ValidationError(f"Value for '{key}' must be a numeric decimal or double.")
        elif field_type in ["text", "paragraph"]:
            if getattr(value, 'strip', None) and value.strip() == "":
                return None
            if not isinstance(value, str):
                raise ValidationError(f"Value for '{key}' must be a valid text string.")
            return value.strip()
        elif field_type == "dropdown":
            if not isinstance(value, str):
                raise ValidationError(f"Selected option for '{key}' must be a string identifier.")
            return value
        return value

    def evaluate_output(self):
        raise NotImplementedError("Child entity component sub-classes must override evaluate_output().")

    def grade_answer(self, student_input, points_available):
        """
        Score a student response against this entity's answer key.
        Child answer-field classes override with real checks.
        Empty / missing input always earns 0 of points_available.
        """
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0

        empty = (
            student_input is None
            or student_input == ""
            or student_input == []
            or student_input == {}
            or (isinstance(student_input, dict) and not any(
                v not in (None, "", [], {}) for v in student_input.values()
            ))
        )
        if empty:
            return {"earned": 0.0, "max": pts, "detail": "No student input"}
        return {"earned": 0.0, "max": pts, "detail": "Grading not implemented"}

    # --- Shared shortAnswer-style text / expression comparison ---

    def _trim_str(self, raw):
        if raw is None:
            return ""
        if isinstance(raw, dict):
            raw = raw.get("value", "")
        return str(raw).strip()

    def _to_sympy(self, raw):
        s = self._trim_str(raw)
        if not s:
            return None
        normalized = self.insert_implicit_multiplication(s)
        try:
            if re.search(r"(?<![<>!=])=(?!=)", normalized):
                left, right = re.split(r"(?<![<>!=])=(?!=)", normalized, maxsplit=1)
                left_expr = sp.parse_expr(left.strip(), evaluate=False)
                right_expr = sp.parse_expr(right.strip(), evaluate=False)
                return sp.Eq(left_expr, right_expr)
            return sp.parse_expr(normalized, evaluate=False)
        except Exception:
            return None

    def _simplify_key(self, raw):
        """Return simplified display/grade key string, or trimmed text if unparseable."""
        trimmed = self._trim_str(raw)
        expr = self._to_sympy(trimmed)
        if expr is None:
            return trimmed
        try:
            if isinstance(expr, sp.Equality):
                left = sp.simplify(expr.lhs)
                right = sp.simplify(expr.rhs)
                return f"{left} = {right}"
            return str(sp.simplify(expr))
        except Exception:
            return trimmed

    def _exprs_equivalent(self, student_expr, correct_expr):
        def as_diff(e):
            if isinstance(e, sp.Equality):
                return e.lhs - e.rhs
            return e

        try:
            return sp.simplify(as_diff(student_expr) - as_diff(correct_expr)) == 0
        except Exception:
            return False

    def _grade_short_answer_text(self, student_raw, correct_raw):
        """
        True if student matches correct via shortAnswer rules:
        trim + lowercase exact match, else sympy equivalence with count_ops gate
        (reject if student still needs further simplification).
        """
        student_trimmed = self._trim_str(student_raw)
        correct_trimmed = self._trim_str(correct_raw)
        if not student_trimmed:
            return False
        if student_trimmed.lower() == correct_trimmed.lower():
            return True
        student_expr = self._to_sympy(student_trimmed)
        correct_expr = self._to_sympy(correct_trimmed)
        if student_expr is None or correct_expr is None:
            return False
        if not self._exprs_equivalent(student_expr, correct_expr):
            return False
        try:
            student_ops = sp.count_ops(student_expr)
            correct_ops = sp.count_ops(correct_expr)
        except Exception:
            return False
        return student_ops <= correct_ops
    

class RandomIntegerEntity(BaseEntity):
    """
    Validation engine for the 'randInt' token pattern.
    """
    def is_valid(self):
        if not super().is_valid():
            return False
            
        # 🎯 FIX 1: Read explicitly from raw dict data fields (self.data) 
        # to capture the unmutated structural macro markup strings (<randInt1>)
        raw_min = str(self.data.get("min", ""))
        raw_max = str(self.data.get("max", ""))

        # These methods automatically trace and resolve dynamic dependencies like '<randInt1>'
        min_val = self.resolve_numeric_value("min", default_fallback=1)
        max_val = self.resolve_numeric_value("max", default_fallback=9)
        step_val = self.resolve_numeric_value("step", default_fallback=1)
        exclude_raw = self.runtime_values.get("exclude", "")
        if exclude_raw in (None,):
            exclude_raw = self.data.get("exclude", "")

        # ---------------------------------------------------------------------
        # 🛡️ STATIC STRUCTURAL BLUEPRINT GUARDS (Before Evaluation)
        # ---------------------------------------------------------------------
        all_entities = getattr(self, 'all_entities_payload', [])

        # CASE A: Upstream macro is linked to the MIN input field
        if re.match(r"^<([^>]+)>$", raw_min.strip()):
            clean_target_token = raw_min.replace("<", "").replace(">", "").strip()
            target_payload = next(
                (item for item in all_entities if (item.get("sequence_token") or item.get("indexed_token") or "") == clean_target_token),
                None
            )
            if target_payload:
                upstream_inputs = target_payload.get("inputs", {})
                try:
                    # 🎯 FIX 2: Double-cast float to int to prevent crashing on decimal strings
                    upstream_max_bound = int(float(upstream_inputs.get("max", 9)))
                    
                    # If upstream max outpaces our absolute local max ceiling, block the transaction
                    if upstream_max_bound > max_val:
                        self.errors["min"] = (
                            f"Structural Error: Linked component '<{clean_target_token}>' can reach a maximum boundary "
                            f"of {upstream_max_bound}, which exceeds this component's maximum bound ({max_val})."
                        )
                except (ValueError, TypeError):
                    pass

        # CASE B: Upstream macro is linked to the MAX input field
        if re.match(r"^<([^>]+)>$", raw_max.strip()):
            clean_target_token = raw_max.replace("<", "").replace(">", "").strip()
            target_payload = next(
                (item for item in all_entities if (item.get("sequence_token") or item.get("indexed_token") or "") == clean_target_token),
                None
            )
            if target_payload:
                upstream_inputs = target_payload.get("inputs", {})
                try:
                    # 🎯 FIX 2: Double-cast float to int to prevent crashing on decimal strings
                    upstream_min_bound = int(float(upstream_inputs.get("min", 1)))
                    
                    # If upstream min plunges lower than our absolute local min floor, block the transaction
                    if upstream_min_bound < min_val:
                        self.errors["max"] = (
                            f"Structural Error: Linked component '<{clean_target_token}>' has a minimum boundary "
                            f"of {upstream_min_bound}, which falls below this component's minimum bound ({min_val})."
                        )
                except (ValueError, TypeError):
                    pass

        # ---------------------------------------------------------------------
        # 🎯 RUNTIME / DYNAMIC CROSS-INPUT BOUNDS GUARD
        # ---------------------------------------------------------------------
        if min_val > max_val:
            # We flag BOTH rows so the UI can highlight whichever fields are invalid
            self.errors["min"] = f"Minimum bound ({min_val}) cannot be greater than maximum bound ({max_val})."
            self.errors["max"] = f"Maximum bound ({max_val}) cannot be lower than minimum bound ({min_val})."

        if step_val <= 0:
            self.errors["step"] = "Step value interval must be a positive integer greater than 0."

        # ---------------------------------------------------------------------
        # EXCLUSION LEDGER PARSING LOGIC
        # ---------------------------------------------------------------------
        if exclude_raw not in (None, ""):
            if isinstance(exclude_raw, (list, tuple)):
                elements = [str(item).strip() for item in exclude_raw if str(item).strip() != ""]
            else:
                elements = [item.strip() for item in str(exclude_raw).split(",") if item.strip()]

            parsed_integers = []
            for item in elements:
                if re.match(r"^<([^>]+)>$", item):
                    try:
                        resolved_item = self.resolve_token_dependency(item)
                        parsed_integers.append(int(float(resolved_item)))
                        continue
                    except Exception:
                        self.errors["exclude"] = (
                            f"Linked exclude token '{item}' could not be resolved to an integer."
                        )
                        break

                # Integers only (reject decimals / non-numeric text)
                if not re.match(r"^-?\d+$", item):
                    self.errors["exclude"] = (
                        f"Value '{item}' inside exclude filter is not a valid integer."
                    )
                    break
                parsed_integers.append(int(item))

            if "exclude" not in self.errors:
                self.runtime_values["exclude_array"] = parsed_integers
                # Persist a normalized comma-separated form for EntitySegment content
                self.cleaned_data["exclude"] = ", ".join(str(n) for n in parsed_integers)
                self.runtime_values["exclude"] = self.cleaned_data["exclude"]
        else:
            self.runtime_values["exclude_array"] = []
            self.cleaned_data["exclude"] = ""
            self.runtime_values["exclude"] = ""

        return len(self.errors) == 0

    def evaluate_output(self):
        """
        🎯 MEMORY SAFE O(1) CALCULATION: Computes random integers mathematically
        """
        # 🎯 Look into the global ledger context to see if this card already has a locked-in value
        if hasattr(self, 'all_entities_payload') and self.all_entities_payload:
            my_sequence_token = self.data.get('sequence_token') or self.runtime_values.get('sequence_token')
            
            target_payload = next(
                (item for item in self.all_entities_payload if item.get("sequence_token") == my_sequence_token),
                None
            )
            
            if target_payload:
                cached_val = target_payload.get('simulated_value', '')
                if cached_val not in ["", "None", "null"]:
                    return cached_val
                
        min_val = int(self.resolve_numeric_value("min", default_fallback=1))
        max_val = int(self.resolve_numeric_value("max", default_fallback=9))
        step_val = int(self.resolve_numeric_value("step", default_fallback=1))
        exclude_set = set(self.runtime_values.get("exclude_array", []))

        if min_val > max_val:
            return str(min_val)

        # Calculate the absolute max step indices possible within this integer span
        total_range = max_val - min_val
        max_steps = total_range // step_val

        # If range or steps result in no legal spaces, fallback cleanly
        if max_steps < 0:
            return str(min_val)

        # 🎯 EXCLUSION LOOP GUARD: Direct sampling to guarantee O(1) space integrity
        attempts = 0
        max_attempts = 200 # Prevent infinite locks if a user accidentally excludes every number in range
        
        while attempts < max_attempts:
            random_step_multiplier = random.randint(0, max_steps)
            candidate_value = min_val + (random_step_multiplier * step_val)
            
            if candidate_value not in exclude_set:
                selected_choice = str(candidate_value)
                return selected_choice
            
            attempts += 1

        # Fallback Strategy: If random sampling kept hitting exclusions, loop once to find the absolute first unexcluded slot
        current = min_val
        while current <= max_val:
            if current not in exclude_set:
                return str(current)
            current += step_val

        return str(min_val)


class RandomDoubleEntity(BaseEntity):
    """
    Validation engine for the 'rand' token pattern (Random Double/Decimal).
    """
    def is_valid(self):
        # 1. RUN SUPER FIRST: This populates runtime_values, errors, and uncovers dependencies
        if not super().is_valid():
            return False
            
        # 2. Extract RAW configurations straight from self.data to catch unparsed string tokens
        raw_min = str(self.data.get("min", ""))
        raw_max = str(self.data.get("max", ""))

        # 3. Pull resolved values for structural fallback comparisons
        min_val = self.resolve_numeric_value("min", default_fallback=0.0)
        max_val = self.resolve_numeric_value("max", default_fallback=1.0)
        step_val = self.resolve_numeric_value("step", default_fallback=0.01)

        # ---------------------------------------------------------------------
        # 🛡️ STATIC STRUCTURAL BLUEPRINT GUARDS (Before dynamic bounds checks)
        # ---------------------------------------------------------------------
        all_entities = getattr(self, 'all_entities_payload', []) or []

        # CASE A: An upstream entity macro token is linked to our MIN input field
        if re.match(r"^<([^>]+)>$", raw_min.strip()):
            clean_target_token = raw_min.replace("<", "").replace(">", "").strip()
            
            # Find the unmutated tracking profile directly from the workspace payload map
            target_payload = next(
                (item for item in all_entities 
                 if (item.get("sequence_token") or item.get("indexed_token") or "") == clean_target_token),
                None
            )
            
            if target_payload:
                upstream_inputs = target_payload.get("inputs", {})
                try:
                    # Get the structural upper ceiling boundary configured on the linked parent
                    upstream_max_bound = float(upstream_inputs.get("max", 9))
                    
                    # 💥 CRITICAL REJECTION: Linked max cannot exceed local max
                    if upstream_max_bound > max_val:
                        self.errors["min"] = (
                            f"Structural Error: Linked component '<{clean_target_token}>' has a maximum upper bound ({upstream_max_bound}) "
                            f"that exceeds this component's maximum boundary ceiling ({max_val})."
                        )
                except (ValueError, TypeError):
                    pass

        # CASE B: An upstream entity macro token is linked to our MAX input field
        if re.match(r"^<([^>]+)>$", raw_max.strip()):
            clean_target_token = raw_max.replace("<", "").replace(">", "").strip()
            
            target_payload = next(
                (item for item in all_entities 
                 if (item.get("sequence_token") or item.get("indexed_token") or "") == clean_target_token),
                None
            )
            
            if target_payload:
                upstream_inputs = target_payload.get("inputs", {})
                try:
                    # Get the structural lower floor boundary configured on the linked parent
                    upstream_min_bound = float(upstream_inputs.get("min", -9))
                    
                    # 💥 CRITICAL REJECTION: Linked min cannot fall below local min
                    if upstream_min_bound < min_val:
                        self.errors["max"] = (
                            f"Structural Error: Linked component '<{clean_target_token}>' has a minimum lower bound ({upstream_min_bound}) "
                            f"that falls below this component's minimum boundary floor ({min_val})."
                        )
                except (ValueError, TypeError):
                    pass

        # ---------------------------------------------------------------------
        # Standard Runtime Verification Fallbacks
        # ---------------------------------------------------------------------
        if min_val > max_val:
            self.errors["min"] = f"Minimum bound ({min_val}) cannot be greater than maximum bound ({max_val})."
            self.errors["max"] = f"Maximum bound ({max_val}) cannot be lower than minimum bound ({min_val})."

        if step_val <= 0:
            self.errors["step"] = "Step decimal interval must be a positive number greater than 0."

        return len(self.errors) == 0

    def evaluate_output(self):
        """
        🎯 MEMORY SAFE CALCULATION: Computes random decimal steps mathematically
        """
        # 🎯 FIX: Look into the global ledger context to see if this card already has a locked-in value
        if hasattr(self, 'all_entities_payload') and self.all_entities_payload:
            # We look up our own active sequence token name (e.g., 'randInt1')
            my_sequence_token = self.data.get('sequence_token') or self.runtime_values.get('sequence_token')
            
            target_payload = next(
                (item for item in self.all_entities_payload if item.get("sequence_token") == my_sequence_token),
                None
            )
            
            if target_payload:
                cached_val = target_payload.get('simulated_value', '')
                if cached_val not in ["", "None", "null"]:
                    return cached_val
                
        min_val = self.resolve_numeric_value("min", default_fallback=0.0)
        max_val = self.resolve_numeric_value("max", default_fallback=1.0)
        step_val = self.resolve_numeric_value("step", default_fallback=0.01)


        if min_val >= max_val:
            val_out = str(round(min_val, 4))
            return val_out

        total_range = max_val - min_val
        max_steps = int((total_range + 1e-9) // step_val)

        if max_steps <= 0:
            val_out = str(round(min_val, 4))
            return val_out

        random_step_multiplier = random.randint(0, max_steps)
        result_value = min_val + (random_step_multiplier * step_val)

        if result_value > max_val:
            result_value = max_val

        step_str = str(step_val)
        decimal_places = len(step_str.split('.')[1]) if '.' in step_str else 4
        final_double_out = str(round(result_value, decimal_places))
        
        return final_double_out
    

class PrimeFactorsEntity(BaseEntity):
    """
    Validation and evaluation engine for the 'primeFactors' token pattern.
    Expects an input field 'number to factor' to break down into its prime components.
    """
    def is_valid(self):
        if not super().is_valid():
            return False
            
        target_num = self.resolve_numeric_value("number to factor", default_fallback=12)

        if target_num <= 1:
            self.errors["number to factor"] = "The input number must be a positive integer greater than 1."

        return len(self.errors) == 0

    def evaluate_output(self):
        """
        🎯 COMPUTES PRIME FACTORS MATHEMATICALLY
        """
        n = self.resolve_numeric_value("number to factor", default_fallback=12)

        if n <= 1:
            return ""

        factors = []
        original_n = n
        
        # Factor out 2s
        while n % 2 == 0:
            factors.append(2)
            n //= 2
            
        # Factor out odd digits up to sqrt(n)
        factor = 3
        while factor * factor <= n:
            while n % factor == 0:
                factors.append(factor)
                n //= factor
            factor += 2
            
        if n > 1:
            factors.append(n)

        factors_result_str = ", ".join(str(f) for f in factors)
        return factors_result_str

class FormulaEntity(BaseEntity):
    """
    Validation and evaluation engine for the 'formula' token pattern.
    """
    def _wants_output_rhs_only(self):
        """Checkbox: emit only the solved/simplified right-hand side (e.g. 2 instead of c = 2)."""
        raw = self.data.get("output rhs only", self.runtime_values.get("output rhs only", False))
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _wants_simplify_after_substitution(self):
        """Checkbox: run SymPy simplify after variable substitution (default off)."""
        raw = self.data.get(
            "simplify after substitution",
            self.runtime_values.get("simplify after substitution", False),
        )
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def is_valid(self):
        if not super().is_valid():
            return False

        formula_expr = self.runtime_values.get("formula", "")
        solve_method = self.runtime_values.get("solve method", "leave as formula")
        variables_str = self.runtime_values.get("variables", "")
        
        # Check both variants from the updated serialization layout
        solve_for_target = self.runtime_values.get("variable to simplify") or self.runtime_values.get("variable to substitute") or self.runtime_values.get("variable to solve for") or ""
        
        # 🎯 FIX: Normalize "-- N/A --" to an empty string for uniform logic processing
        if solve_for_target.strip() in ["-- N/A --", "-- choose variable --"]:
            solve_for_target = ""

        self.runtime_values["variable substitution"] = solve_for_target
        self.runtime_values["variable to solve for"] = solve_for_target


        if not formula_expr:
            if solve_method in ['variable substitution', 'simplify']:
                self.runtime_values["formula"] = "0"
                formula_expr = "0"
            else:
                self.errors["formula"] = "A mathematical expression or equation string is required."
                return False
        
        if formula_expr and str(formula_expr).strip() != "0":
            # Apply implicit multiplication rules before testing syntax validity
            implicit_clean_expr = self.insert_implicit_multiplication(str(formula_expr))
            
            # Temporarily substitute macro tokens with an arbitrary integer for raw syntax evaluation
            clean_syntax_check = re.sub(r'&lt;([^&>]+)&gt;|<([^>]+)>', '1', implicit_clean_expr)
            is_valid_syntax, syntax_error_msg = SymPyAssessmentEngine.check_syntax_validity(clean_syntax_check)
            if not is_valid_syntax:
                self.errors["formula"] = syntax_error_msg

        parsed_variables = []
        if variables_str:
            raw_elements = [v.strip() for v in str(variables_str).split(",") if v.strip()]
            for item in raw_elements:
                ok, err = _is_valid_algebraic_variable_name(item)
                if not ok:
                    self.errors["variables"] = err
                    break
                parsed_variables.append(item)
        
        if "variables" not in self.errors:
            self.runtime_values["parsed_variables_array"] = parsed_variables

        # Persist UI checkboxes into cleaned_data so saves keep them (even before reseed)
        solve_for_target_clean = (solve_for_target or "").strip()
        wants_rhs = self._wants_output_rhs_only() and solve_method == "simplify" and bool(solve_for_target_clean)
        self.cleaned_data["output rhs only"] = wants_rhs
        self.cleaned_data["simplify after substitution"] = self._wants_simplify_after_substitution()
        self.runtime_values["output rhs only"] = wants_rhs
        self.runtime_values["simplify after substitution"] = self.cleaned_data["simplify after substitution"]

        # 🎯 UPDATED BLOCK: ENFORCING N/A RECONCILIATION FOR SIMPLIFY METHOD
        if solve_method == "simplify":
            # 1. Catch missing target variable when simplifying an inherited token link
            is_macro_token = bool(re.search(r'&lt;([^&>]+)&gt;|<([^>]+)>', str(formula_expr)))
            
            if is_macro_token and not solve_for_target:
                self.errors["variable to solve for"] = (
                    f"Ambiguous Simplify Target: This card references an external step '{formula_expr}', "
                    f"but no 'Target Variable to Simplify' has been selected. Please choose which variable "
                    f"you want to isolate on the left side of the equation."
                )
            
            # 2. If a target variable is selected, make sure it is defined in the variables index
            elif parsed_variables and solve_for_target and (solve_for_target not in parsed_variables):
                self.errors["variable to solve for"] = (
                    f"Target variable '{solve_for_target}' must be present inside your "
                    f"declared variables list: {parsed_variables}."
                )

        elif solve_method == "variable substitution":
            self.runtime_values["variable to solve for"] = ""
            self.runtime_values["variable substitution"] = ""

        return len(self.errors) == 0


    def evaluate_output(self):
        formula_str = str(self.runtime_values.get("formula", "")).strip()
        solve_method = str(self.runtime_values.get("solve method", "leave as formula")).strip()
        var_list = self.runtime_values.get("parsed_variables_array", [])
        solve_for_target = self.runtime_values.get("variable to solve for", "").strip()
        # When last_computed_sympy_result is a (lhs, rhs) pair, latex uses this op
        # (<=, >=, <, >, =) instead of always hard-coding "=".
        self.last_relation_display_op = None
        # Multi-root simplify solutions for downstream expanders (e.g. answersOrDne).
        self.last_solution_list = None

        if solve_for_target in ["-- N/A --", "-- choose variable --"]:
            solve_for_target = ""


        if not formula_str:
            return "0"

        # Build local substitutions structures (same merge/normalize as div0 check)
        subs_map = self._collect_formula_substitutions()

        resolved_subs = {}
        for var_name, var_value in subs_map.items():
            if isinstance(var_value, str) and var_value.startswith('<') and var_value.endswith('>'):
                raw_resolved = self.resolve_token_dependency(var_value)
                if raw_resolved and isinstance(raw_resolved, str) and '=' in raw_resolved:
                    parts = re.split(r'(<=|>=|==|<|>|=)', raw_resolved, 1)
                    if len(parts) >= 3:
                        raw_resolved = parts[2].strip()
                resolved_subs[var_name] = f"({raw_resolved})"
            else:
                resolved_subs[var_name] = var_value

        def bracket_replacer(match):
            target_token = match.group(1) if match.group(1) else match.group(2)
            resolved = f"({self.resolve_token_dependency(f'<{target_token.strip()}>')})"
            return resolved

        processed_formula = re.sub(r'&lt;([^&>]+)&gt;|<([^>]+)>', bracket_replacer, formula_str)

        # Inbound implicit math expansion immediately following macro expansion
        processed_formula = self.insert_implicit_multiplication(processed_formula)

        local_dict = {var: sp.Symbol(var) for var in var_list}
        if 'pi' not in local_dict: local_dict['pi'] = sp.pi
        if 'exp' not in local_dict: local_dict['exp'] = sp.exp
        if 'I' not in local_dict: local_dict['I'] = sp.I

        if solve_method in ['leave as formula', 'variable substitution', 'simplify']:
            local_dict['integrate'] = sp.Integral
            local_dict['diff'] = sp.Derivative
            local_dict['limit'] = sp.Limit

        # Helper method to parse single standalone chunk strings via SymPy safely
        def parse_segment(expr_str):
            s = str(expr_str).strip()
            
            if "\\" in s:
                return parse_latex(s)
            
            if is_fully_wrapped_tuple(s):
                s = s[1:-1].strip()
                
                if '=' not in s:
                    # 🎯 FIXED: Use bracket-aware top-level comma splitting here too
                    comma_split = split_top_level_comma(s)
                    if comma_split:
                        s = f"{comma_split[0]} = {comma_split[1]}"
                
            if '=' in s:
                parts = re.split(r'(<=|>=|==|<|>|=)', s, 1)
                if len(parts) >= 3:
                    s = parts[2].strip()
                    
            try:
                parsed_obj = sp.parse_expr(s, local_dict=local_dict, evaluate=False)
                return parsed_obj
            except Exception as segment_err:
                raise segment_err

        # Helper to verify if the first '(' matches the final ')'
        def is_fully_wrapped_tuple(s):
            if not (s.startswith('(') and s.endswith(')')):
                return False
            
            balance = 0
            for i in range(len(s) - 1):
                if s[i] == '(': balance += 1
                elif s[i] == ')': balance -= 1
                if balance == 0: return False
            return True

        # 🎯 NEW HELPER: Split string on the first comma found ONLY at the root depth (depth=0)
        def split_top_level_comma(s):
            depth = 0
            for idx, char in enumerate(s):
                if char == '(': depth += 1
                elif char == ')': depth -= 1
                elif char == ',' and depth == 0:
                    # Found the root-level comma divide!
                    return [s[:idx].strip(), s[idx+1:].strip()]
            return None # No top-level comma found

        # Pre-process the entire formula string to clean up tuple representations 
        processed_formula_clean = processed_formula.strip()
        
        if is_fully_wrapped_tuple(processed_formula_clean):
            processed_formula_clean = processed_formula_clean[1:-1].strip()
            
            if '=' not in processed_formula_clean:
                # 🎯 FIXED: Safely split on the root-level comma separator only
                comma_split = split_top_level_comma(processed_formula_clean)
                if comma_split:
                    processed_formula_clean = f"{comma_split[0]} = {comma_split[1]}"

        # Relation Operator Scanner
        rel_match = re.search(r'(<=|>=|==|<|>)', processed_formula_clean)
        if not rel_match and '=' in processed_formula_clean:
            if processed_formula_clean.count('(') == processed_formula_clean.count(')'):
                if not (processed_formula_clean.strip().startswith('integrate') or processed_formula_clean.strip().startswith('diff')):
                    rel_match = re.search(r'(=)', processed_formula_clean)

        has_relation = rel_match is not None
        rel_op = rel_match.group(1) if has_relation else ""
        display_op = "=" if rel_op == "==" else rel_op


        # 🎯 PROCESS SIMPLIFY STRATEGIES
        if solve_method == 'simplify':
            # RHS-only only applies when isolating a chosen target variable
            output_rhs_only = self._wants_output_rhs_only() and bool(solve_for_target)
            try:
                if not solve_for_target:
                    if not has_relation:
                        parsed_expr = parse_segment(processed_formula_clean)
                        result = sp.simplify(parsed_expr.doit())
                        self.last_extracted_free_symbols = (
                            result.free_symbols if hasattr(result, 'free_symbols') else set()
                        )
                    else:
                        left_raw, right_raw = processed_formula_clean.split(rel_op, 1)
                        left_parsed = parse_segment(left_raw)
                        right_parsed = parse_segment(right_raw)
                        left_simplified = sp.simplify(left_parsed.doit())
                        right_simplified = sp.simplify(right_parsed.doit())
                        self.last_extracted_free_symbols = (
                            left_simplified.free_symbols.union(right_simplified.free_symbols)
                        )
                        if output_rhs_only and display_op == "=":
                            self.last_computed_sympy_result = right_simplified
                            return str(right_simplified)
                        self.last_relation_display_op = display_op
                        self.last_computed_sympy_result = (left_simplified, right_simplified)
                        return f"{left_simplified} {display_op} {right_simplified}"
                else:
                    target_symbol = sp.Symbol(solve_for_target)
                    if not has_relation:
                        parsed_expr = parse_segment(processed_formula_clean)
                        equation = sp.Eq(parsed_expr.doit(), 0)
                        rel_op = "="
                        left_parsed = equation.lhs
                        right_parsed = equation.rhs
                    else:
                        left_raw, right_raw = processed_formula_clean.split(rel_op, 1)
                        left_parsed = parse_segment(left_raw).doit()
                        right_parsed = parse_segment(right_raw).doit()
                        if rel_op in ["=", "=="]: equation = sp.Eq(left_parsed, right_parsed)
                        elif rel_op == "<":   equation = sp.Lt(left_parsed, right_parsed)
                        elif rel_op == "<=":  equation = sp.Le(left_parsed, right_parsed)
                        elif rel_op == ">":   equation = sp.Gt(left_parsed, right_parsed)
                        elif rel_op == ">=":  equation = sp.Ge(left_parsed, right_parsed)

                    # Variables UI should list symbols available in the linked/input
                    # equation — not free symbols of a bogus numeric solve result.
                    self.last_extracted_free_symbols = equation.free_symbols if hasattr(equation, 'free_symbols') else set()

                    if rel_op in ["<", "<=", ">", ">="]:
                        try:
                            solved_rel = sp.reduce_inequalities(equation, target_symbol)
                            self.last_computed_sympy_result = solved_rel
                            return str(solved_rel)
                        except Exception as e:
                            solutions = sp.solve(equation, target_symbol)
                    else:
                        solutions = sp.solve(equation, target_symbol)

                    if isinstance(solutions, list):
                        if len(solutions) == 1:
                            resolved_right_side = solutions[0]
                            self.last_solution_list = [solutions[0]]
                        elif len(solutions) > 1:
                            resolved_right_side = f"[{', '.join(str(s) for s in solutions)}]"
                            self.last_solution_list = list(solutions)
                        else:
                            # Empty solve: never invent 0 (e.g. solve for `c` when only `b`
                            # appears). Surface the input equation instead.
                            if output_rhs_only and display_op == "=":
                                self.last_computed_sympy_result = right_parsed
                                return str(right_parsed)
                            if has_relation:
                                self.last_relation_display_op = display_op
                                self.last_computed_sympy_result = (left_parsed, right_parsed)
                            else:
                                self.last_computed_sympy_result = equation
                            return processed_formula_clean
                    else:
                        resolved_right_side = solutions
                        if solutions is not None:
                            self.last_solution_list = (
                                list(solutions) if isinstance(solutions, (list, tuple, set, frozenset))
                                else [solutions]
                            )

                    if resolved_right_side is None:
                        if output_rhs_only and display_op == "=":
                            self.last_computed_sympy_result = right_parsed
                            return str(right_parsed)
                        if has_relation:
                            self.last_relation_display_op = display_op
                            self.last_computed_sympy_result = (left_parsed, right_parsed)
                        else:
                            self.last_computed_sympy_result = equation
                        return processed_formula_clean

                    if output_rhs_only:
                        # Emit only the solved value (e.g. "0" instead of "c = 0").
                        # Never leave last_computed_sympy_result as None — sp.latex(None)
                        # renders as \text{None} in the card preview.
                        try:
                            self.last_computed_sympy_result = sp.sympify(resolved_right_side)
                        except Exception:
                            self.last_computed_sympy_result = sp.Integer(0)
                        return str(resolved_right_side)

                    if not isinstance(resolved_right_side, str):
                        self.last_computed_sympy_result = sp.Eq(target_symbol, resolved_right_side)
                    else:
                        self.last_computed_sympy_result = target_symbol

                    return f"{solve_for_target} = {resolved_right_side}"
                    
            except Exception as eval_err:
                return processed_formula_clean

        # 🎯 RETAIN OTHER NATIVE SOLVE METHODS AS IS
        else:
            
            # This is the exact block that ran during your leave as formula execution!
            if has_relation and solve_method in ['leave as formula', 'variable substitution']:
                left_raw, right_raw = processed_formula_clean.split(rel_op, 1)
                parsed_expr = (parse_segment(left_raw), parse_segment(right_raw))
            
            elif has_relation and solve_method == 'leave as formula':
                left_raw, right_raw = processed_formula_clean.split(rel_op, 1)
                left_parsed = parse_segment(left_raw)
                right_parsed = parse_segment(right_raw)
                self.last_relation_display_op = display_op
                self.last_computed_sympy_result = (left_parsed, right_parsed)
                return f"{left_parsed} {display_op} {right_parsed}"
            
            else:
                parsed_expr = parse_segment(processed_formula_clean)


            if solve_method == 'expand polynomial':
                result = sp.expand(parsed_expr.doit())
            elif solve_method == 'factor polynomial':
                result = sp.factor(parsed_expr.doit())
            elif solve_method == 'variable substitution':
                sympy_subs_map = {}
                for v_name, v_val in resolved_subs.items():
                    if isinstance(v_val, str) and v_val.strip():
                        try:
                            sympy_subs_map[sp.Symbol(v_name)] = sp.parse_expr(str(v_val), local_dict=local_dict, evaluate=False)
                        except Exception:
                            sympy_subs_map[sp.Symbol(v_name)] = v_val
                    else:
                        if v_val != "":
                            sympy_subs_map[sp.Symbol(v_name)] = v_val

                simplify_after = self._wants_simplify_after_substitution()

                if sympy_subs_map:
                    with sp.evaluate(False):
                        if isinstance(parsed_expr, tuple):
                            result_left = parsed_expr[0].subs(sympy_subs_map)
                            result_right = parsed_expr[1].subs(sympy_subs_map)
                        else:
                            result = parsed_expr.subs(sympy_subs_map)

                    if isinstance(parsed_expr, tuple):
                        if simplify_after:
                            result_left = sp.simplify(result_left)
                            result_right = sp.simplify(result_right)
                        self.last_relation_display_op = display_op
                        self.last_computed_sympy_result = (result_left, result_right)
                        return f"{result_left} {display_op} {result_right}"

                    if simplify_after:
                        result = sp.simplify(result)
                else:
                    if isinstance(parsed_expr, tuple):
                        result_left, result_right = parsed_expr
                        if simplify_after:
                            result_left = sp.simplify(result_left)
                            result_right = sp.simplify(result_right)
                        self.last_relation_display_op = display_op
                        self.last_computed_sympy_result = (result_left, result_right)
                        return f"{result_left} {display_op} {result_right}"
                    result = parsed_expr
                    if simplify_after:
                        result = sp.simplify(result)
            else:
                result = parsed_expr

        if isinstance(result, tuple) and len(result) >= 2 and has_relation:
            if self.last_relation_display_op is None:
                self.last_relation_display_op = display_op
            self.last_computed_sympy_result = result
            op = self.last_relation_display_op or "="
            return f"{result[0]} {op} {result[1]}"

        self.last_computed_sympy_result = result
        return str(result)

    # ------------------------------------------------------------------
    # Save-Draft: possible division-by-zero via interval arithmetic
    # ------------------------------------------------------------------

    def _payload_by_sequence_token(self, clean_token):
        clean = str(clean_token or "").replace("<", "").replace(">", "").strip()
        if not clean:
            return None
        return next(
            (
                item
                for item in (self.all_entities_payload or [])
                if (item.get("sequence_token") or item.get("indexed_token") or "") == clean
            ),
            None,
        )

    def _resolve_bound_endpoint(self, raw, side="low", visiting=None):
        """
        Resolve a rand/randInt min or max field to a float endpoint.
        Linked tokens use the upstream random's outer min (side=low) or max (side=high).
        """
        visiting = visiting or set()
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            return float(raw)

        s = str(raw).strip()
        token_match = re.match(r"^<([^>]+)>$", s)
        if token_match:
            tok = token_match.group(1).strip()
            if tok in visiting:
                return None
            iv = self._random_entity_interval(tok, visiting | {tok})
            if not iv:
                return None
            return iv[0] if side == "low" else iv[1]
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    def _random_entity_interval(self, clean_token, visiting=None):
        """Return (min, max) for a rand/randInt token, or None."""
        visiting = visiting or set()
        payload = self._payload_by_sequence_token(clean_token)
        if not payload:
            return None
        arch = payload.get("token")
        if arch not in ("rand", "randInt"):
            return None
        inputs = payload.get("inputs", {}) or {}
        lo = self._resolve_bound_endpoint(inputs.get("min"), side="low", visiting=visiting)
        hi = self._resolve_bound_endpoint(inputs.get("max"), side="high", visiting=visiting)
        if lo is None or hi is None:
            return None
        if lo > hi:
            lo, hi = hi, lo
        return (lo, hi)

    def _normalize_formula_sub_value(self, raw):
        """
        Normalize substitution values so linked workspace tokens always use <token>
        form. Save payloads often send both substitutions={x:'<randInt4>'} and
        sub_x='randInt4' (or HTML-entity encoded); bare / encoded forms must not
        defeat interval analysis or dependency resolution.
        """
        if raw is None or not isinstance(raw, str):
            return raw
        s = (
            raw.strip()
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&LT;", "<")
            .replace("&GT;", ">")
        )
        bracketed = re.match(r"^<([^<>]+)>$", s)
        if bracketed:
            return f"<{bracketed.group(1).strip()}>"
        # Bare sequence token (randInt4, formula1, ...)
        if re.match(r"^[A-Za-z][A-Za-z0-9_]*\d+$", s):
            return f"<{s}>"
        return raw

    def _collect_formula_substitutions(self):
        """
        Merge sub_* keys and the substitutions dict. The nested substitutions
        map wins when both are present (it is produced by formula serialize with
        proper <token> brackets); sub_* is only a fallback.
        """
        subs_map = {}
        for k, v in self.data.items():
            if not k.startswith("sub_") or v is None or v == "":
                continue
            name = k.replace("sub_", "", 1).strip()
            if name:
                subs_map[name] = self._normalize_formula_sub_value(v)

        nested = self.data.get("substitutions", {}) or {}
        if isinstance(nested, dict):
            for name, v in nested.items():
                if v is None or v == "":
                    continue
                key = str(name).strip()
                if key:
                    subs_map[key] = self._normalize_formula_sub_value(v)
        return subs_map

    def _expand_token_to_sympy(self, clean_token, ranges, token_by_sym, visiting):
        """
        Expand a workspace token into a SymPy expression.
        rand/randInt → unique symbol with interval in `ranges`.
        formula → recursively expanded expression with its own substitutions.
        """
        clean = str(clean_token or "").replace("<", "").replace(">", "").strip()
        payload = self._payload_by_sequence_token(clean)
        if not payload:
            return sp.Symbol(clean)

        arch = payload.get("token")
        if arch in ("rand", "randInt"):
            sym = sp.Symbol(f"_rnd_{clean}")
            iv = self._random_entity_interval(clean)
            if iv is not None:
                ranges[sym] = iv
                token_by_sym[sym] = clean
            return sym

        if arch == "formula":
            if clean in visiting:
                return sp.Symbol(f"_cyc_{clean}")
            nested_inputs = dict(payload.get("inputs", {}) or {})
            # No DB blueprint needed for structural expand — inputs come from payload.
            nested = FormulaEntity(
                nested_inputs,
                {"name": "formula", "inputs": {}},
                all_entities_payload=self.all_entities_payload,
            )
            nested.data["sequence_token"] = clean
            expr, nested_ranges, nested_tokens = nested._build_range_aware_sympy_expr(
                visiting | {clean}
            )
            ranges.update(nested_ranges)
            token_by_sym.update(nested_tokens)
            return expr

        # Fallback: try a concrete dependency resolve (sample), else leave symbolic
        try:
            resolved = self.resolve_token_dependency(f"<{clean}>")
            return sp.sympify(resolved)
        except Exception:
            return sp.Symbol(clean)

    def _build_range_aware_sympy_expr(self, visiting=None):
        """
        Build a SymPy expression for this formula where linked rand/randInt
        values are symbols annotated with [min, max] intervals (no sampling).
        Returns (expr, ranges_dict, token_by_symbol).
        """
        visiting = set(visiting or set())
        my_token = (
            self.data.get("sequence_token")
            or self.runtime_values.get("sequence_token")
            or ""
        )
        my_token = str(my_token).replace("<", "").replace(">", "").strip()
        if my_token:
            visiting = visiting | {my_token}

        ranges = {}
        token_by_sym = {}
        # Prefer raw teacher inputs. BaseEntity.is_valid() resolves bare <token>
        # links into runtime_values via sample evaluation — using that here made
        # Save-Draft div0 checks flaky (dependent on the rolled random seed).
        formula_str = str(
            self.data.get("formula")
            or self.runtime_values.get("formula", "")
            or ""
        ).strip()
        if not formula_str:
            return sp.Integer(0), ranges, token_by_sym

        local_dict = {}
        placeholder_exprs = {}

        def bracket_replacer(match):
            tok = (match.group(1) or match.group(2) or "").strip()
            ph_name = f"_ph_{tok}"
            if ph_name not in local_dict:
                ph_sym = sp.Symbol(ph_name)
                local_dict[ph_name] = ph_sym
                placeholder_exprs[ph_sym] = self._expand_token_to_sympy(
                    tok, ranges, token_by_sym, visiting
                )
            return ph_name

        processed = re.sub(r"&lt;([^&>]+)&gt;|<([^>]+)>", bracket_replacer, formula_str)
        processed = self.insert_implicit_multiplication(processed)

        # Strip a single outer wrapping pair only when it truly wraps the whole
        # expression. Naively checking startswith('(') and endswith(')') breaks
        # forms like (x-y)/(w-z) into the unparseable "x-y)/(w-z".
        processed_clean = processed.strip()

        def _fully_wrapped_parens(s):
            if not (s.startswith("(") and s.endswith(")")):
                return False
            depth = 0
            for i, ch in enumerate(s):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0 and i < len(s) - 1:
                        return False
            return depth == 0

        if _fully_wrapped_parens(processed_clean):
            processed_clean = processed_clean[1:-1].strip()

        exprs_to_parse = []
        rel_match = re.search(r"(<=|>=|==|<|>|=)", processed_clean)
        if rel_match and processed_clean.count("(") == processed_clean.count(")"):
            op = rel_match.group(1)
            left, right = processed_clean.split(op, 1)
            exprs_to_parse.extend([left.strip(), right.strip()])
        else:
            exprs_to_parse.append(processed_clean)

        parsed_parts = []
        for piece in exprs_to_parse:
            if not piece:
                continue
            try:
                part = sp.parse_expr(piece, local_dict=local_dict, evaluate=False)
            except Exception:
                continue
            if placeholder_exprs:
                part = part.subs(placeholder_exprs)
            parsed_parts.append(part)

        if not parsed_parts:
            return sp.Integer(0), ranges, token_by_sym

        expr = parsed_parts[0]
        if len(parsed_parts) > 1:
            # Sum sides so denominators on either side of an equation are visible
            expr = parsed_parts[0] + parsed_parts[1]

        # Apply variable substitutions (literals or linked tokens)
        subs_map = self._collect_formula_substitutions()
        for var_name, var_value in subs_map.items():
            if not var_name:
                continue
            target = sp.Symbol(str(var_name).strip())
            if isinstance(var_value, str) and re.match(r"^<([^>]+)>$", var_value.strip()):
                tok = var_value.strip()[1:-1].strip()
                replacement = self._expand_token_to_sympy(
                    tok, ranges, token_by_sym, visiting
                )
            elif var_value is None or var_value == "":
                continue
            else:
                try:
                    replacement = sp.parse_expr(
                        self.insert_implicit_multiplication(str(var_value)),
                        evaluate=False,
                    )
                except Exception:
                    continue
            try:
                expr = expr.subs(target, replacement)
            except Exception:
                pass

        return expr, ranges, token_by_sym

    @staticmethod
    def _interval_add(a, b):
        return (a[0] + b[0], a[1] + b[1])

    @staticmethod
    def _interval_sub(a, b):
        return (a[0] - b[1], a[1] - b[0])

    @staticmethod
    def _interval_mul(a, b):
        products = []
        for x in (a[0], a[1]):
            for y in (b[0], b[1]):
                p = x * y
                # 0 * ±inf → nan; treat as covering unbounded contribution
                if isinstance(p, float) and math.isnan(p):
                    return (float("-inf"), float("inf"))
                products.append(p)
        return (min(products), max(products))

    @classmethod
    def _interval_pow_int(cls, base, exp):
        """Integer power of an interval (conservative)."""
        e = int(exp)
        if e == 0:
            return (1.0, 1.0)
        if e < 0:
            # 1 / base^|e| — if base contains 0, result is unbounded
            if base[0] <= 0 <= base[1]:
                return (float("-inf"), float("inf"))
            inv = (1.0 / base[1], 1.0 / base[0]) if base[0] > 0 else (1.0 / base[1], 1.0 / base[0])
            lo, hi = (min(inv), max(inv))
            return cls._interval_pow_int((lo, hi), -e) if e != -1 else (lo, hi)
        # positive integer
        if e == 1:
            return base
        # For even powers, negatives fold; use endpoint sampling of monotonic pieces
        samples = [base[0] ** e, base[1] ** e]
        if e % 2 == 0 and base[0] < 0 < base[1]:
            samples.append(0.0)
        return (min(samples), max(samples))

    def _eval_expr_interval(self, expr, ranges):
        """
        Conservative interval evaluation of a SymPy expression.
        Returns (lo, hi) or None if the expression depends on unbound symbols
        or uses unsupported operations.
        """
        try:
            expr = sp.sympify(expr)
        except Exception:
            return None

        if expr.is_Number:
            try:
                v = float(expr)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(v):
                return None
            return (v, v)

        if expr.is_Symbol:
            if expr in ranges:
                lo, hi = ranges[expr]
                return (float(lo), float(hi))
            return None

        if expr.is_Add:
            acc = (0.0, 0.0)
            for arg in expr.args:
                iv = self._eval_expr_interval(arg, ranges)
                if iv is None:
                    return None
                acc = self._interval_add(acc, iv)
            return acc

        if expr.is_Mul:
            acc = (1.0, 1.0)
            for arg in expr.args:
                iv = self._eval_expr_interval(arg, ranges)
                if iv is None:
                    return None
                acc = self._interval_mul(acc, iv)
            return acc

        if expr.is_Pow:
            base_iv = self._eval_expr_interval(expr.base, ranges)
            if base_iv is None:
                return None
            if expr.exp.is_Number and expr.exp.is_integer:
                return self._interval_pow_int(base_iv, int(expr.exp))
            return None

        # Unsupported node (functions, etc.)
        return None

    def _bind_orphan_token_symbols(self, expr, ranges, token_by_sym):
        """
        If a bare token name (e.g. Symbol('randInt4')) remains in the expression
        because a substitution lacked <brackets>, attach its [min,max] range.
        """
        free = getattr(expr, "free_symbols", set()) or set()
        for sym in list(free):
            if sym in ranges:
                continue
            name = str(sym)
            if name.startswith("_rnd_"):
                tok = name[len("_rnd_"):]
            elif re.match(r"^[A-Za-z][A-Za-z0-9_]*\d+$", name):
                tok = name
            else:
                continue
            iv = self._random_entity_interval(tok)
            if iv is None:
                continue
            ranges[sym] = iv
            token_by_sym[sym] = tok
        return ranges, token_by_sym

    @staticmethod
    def _interval_contains_zero(iv):
        if iv is None:
            return False
        lo, hi = iv
        return (
            not (math.isfinite(lo) and math.isfinite(hi))
            or (lo <= 0 <= hi)
        )

    def _token_is_randint(self, clean_token):
        payload = self._payload_by_sequence_token(clean_token)
        return bool(payload and payload.get("token") == "randInt")

    @staticmethod
    def _format_range_endpoint(value, as_int):
        if as_int:
            return str(int(round(value)))
        text = f"{float(value):.6g}"
        return text

    def _minimal_translation_for_symbol(self, denom, base_ranges, sym, as_int, max_steps=250):
        """
        Smallest |δ| translating sym's [lo,hi] → [lo+δ, hi+δ] so denom's
        interval no longer contains 0. Returns (abs_delta, delta, new_lo, new_hi) or None.
        """
        lo, hi = base_ranges.get(sym, (None, None))
        if lo is None or hi is None:
            return None
        if not (math.isfinite(lo) and math.isfinite(hi)):
            return None

        step = 1.0 if as_int else max(abs(hi - lo) / 50.0, 0.01)

        for step_i in range(1, max_steps + 1):
            for sign in (1, -1):
                delta = sign * step_i * step
                if as_int:
                    delta = float(int(round(delta)))
                new_lo, new_hi = lo + delta, hi + delta
                if as_int:
                    new_lo, new_hi = float(int(round(new_lo))), float(int(round(new_hi)))
                trial = dict(base_ranges)
                trial[sym] = (new_lo, new_hi)
                iv = self._eval_expr_interval(denom, trial)
                if iv is not None and not self._interval_contains_zero(iv):
                    return (abs(delta), delta, new_lo, new_hi)
        return None

    def _suggest_range_shift_for_denom(self, denom, eval_ranges, token_by_sym, ranged_syms):
        """
        Prefer a single linked random whose min/max can be shifted together
        (same δ) by the smallest amount so 0 leaves the denominator hull.
        """
        best = None  # (abs_delta, token, old_lo, old_hi, new_lo, new_hi, as_int)
        for sym in ranged_syms:
            tok = token_by_sym.get(sym)
            if not tok:
                continue
            lo, hi = eval_ranges.get(sym, (None, None))
            if lo is None or not (math.isfinite(lo) and math.isfinite(hi)):
                continue
            as_int = self._token_is_randint(tok)
            found = self._minimal_translation_for_symbol(
                denom, eval_ranges, sym, as_int=as_int
            )
            if not found:
                continue
            abs_delta, _delta, new_lo, new_hi = found
            candidate = (abs_delta, tok, lo, hi, new_lo, new_hi, as_int)
            if best is None or candidate[0] < best[0] or (
                candidate[0] == best[0] and tok < best[1]
            ):
                best = candidate

        if not best:
            return None

        abs_delta, tok, lo, hi, new_lo, new_hi, as_int = best
        return {
            "token": tok,
            "old_min": self._format_range_endpoint(lo, as_int),
            "old_max": self._format_range_endpoint(hi, as_int),
            "new_min": self._format_range_endpoint(new_lo, as_int),
            "new_max": self._format_range_endpoint(new_hi, as_int),
            "shift": self._format_range_endpoint(
                new_lo - lo if math.isfinite(new_lo - lo) else abs_delta,
                as_int,
            ),
        }

    def _format_div0_message(self, denom_display, token_list, free_names, suggestion):
        if free_names:
            free_list = ", ".join(free_names)
            msg = (
                f"Possible division by zero: denominator ({denom_display}) can be 0 for some "
                f"values of {token_list} within their min/max ranges "
                f"(and some values of free variable(s) {free_list})."
            )
        else:
            msg = (
                f"Possible division by zero: denominator ({denom_display}) can be 0 for some "
                f"values of {token_list} within their min/max ranges."
            )

        if suggestion:
            msg += (
                f" Suggestion: shift <{suggestion['token']}> from "
                f"[{suggestion['old_min']}, {suggestion['old_max']}] to "
                f"[{suggestion['new_min']}, {suggestion['new_max']}] "
                f"(translate min/max by {suggestion['shift']}) to avoid a zero denominator."
            )
        elif not free_names:
            msg += (
                " No single-entity min/max translation avoids this; "
                "adjust multiple ranges or the formula."
            )
        else:
            msg += (
                " Bind the free variable(s) (or adjust ranges on a downstream card "
                "that substitutes them) — shifting random min/max alone cannot fix "
                "an unbound variable in the denominator."
            )
        return msg

    def _find_division_by_zero_issue(self, visiting=None):
        """
        Locate a denominator that can contain 0 under linked random ranges.
        Returns a dict with message fields, or None.
        """
        visiting = set(visiting or set())
        my_token = (
            self.data.get("sequence_token")
            or self.runtime_values.get("sequence_token")
            or ""
        )
        my_token = str(my_token).replace("<", "").replace(">", "").strip()
        if my_token:
            if my_token in visiting:
                return None
            visiting = visiting | {my_token}

        try:
            expr, ranges, token_by_sym = self._build_range_aware_sympy_expr(visiting)
            ranges, token_by_sym = self._bind_orphan_token_symbols(expr, ranges, token_by_sym)
        except Exception:
            return None

        try:
            denoms = self._collect_denominators(expr)
        except Exception:
            return None

        for denom in denoms:
            free = getattr(denom, "free_symbols", set()) or set()

            if not free:
                try:
                    if denom == 0 or (denom.is_Number and float(denom) == 0):
                        return {
                            "has_unranged": False,
                            "message": (
                                "Possible division by zero: denominator evaluates to 0."
                            ),
                        }
                except Exception:
                    pass
                continue

            ranged_syms = {s for s in free if s in ranges}
            unranged_syms = free - ranged_syms
            if not ranged_syms:
                continue

            eval_ranges = dict(ranges)
            for s in unranged_syms:
                eval_ranges[s] = (float("-inf"), float("inf"))

            iv = self._eval_expr_interval(denom, eval_ranges)
            if not self._interval_contains_zero(iv):
                continue

            involved = sorted({token_by_sym[s] for s in ranged_syms if s in token_by_sym})
            token_list = ", ".join(f"<{t}>" for t in involved) or "linked random entities"
            free_names = sorted(str(s) for s in unranged_syms)
            denom_display = str(denom)
            for sym, tok in token_by_sym.items():
                denom_display = denom_display.replace(str(sym), f"<{tok}>")

            # Suggestions only use finite ranged symbols (not the ±∞ stand-ins).
            suggestion = None
            if not unranged_syms:
                suggestion = self._suggest_range_shift_for_denom(
                    denom, eval_ranges, token_by_sym, ranged_syms
                )

            return {
                "has_unranged": bool(unranged_syms),
                "message": self._format_div0_message(
                    denom_display, token_list, free_names, suggestion
                ),
            }
        return None

    def check_possible_division_by_zero(self, visiting=None):
        """
        Structural Save-Draft check: using interval arithmetic over linked
        rand/randInt [min, max] ranges (ignoring step/exclude), detect whether
        any denominator can contain 0.

        Attribution: defer to an upstream formula only when that upstream has a
        fully-ranged (actionable) div0 issue. Mixed free-variable issues are
        reported on the card that binds the remaining variables when possible.

        Returns an error string, or None if no issue / analysis inapplicable.
        """
        visiting = set(visiting or set())
        my_token = (
            self.data.get("sequence_token")
            or self.runtime_values.get("sequence_token")
            or ""
        )
        my_token = str(my_token).replace("<", "").replace(">", "").strip()
        if my_token and my_token in visiting:
            return None

        # Include self while probing upstream so cyclic formula links cannot recurse.
        defer_visiting = visiting | {my_token} if my_token else set(visiting)
        for dep_tok in self._iter_linked_formula_tokens():
            if dep_tok in defer_visiting:
                continue
            upstream = self._make_formula_validator_for_token(dep_tok)
            if not upstream:
                continue
            try:
                upstream_issue = upstream._find_division_by_zero_issue(defer_visiting)
            except Exception:
                upstream_issue = None
            if upstream_issue and not upstream_issue.get("has_unranged"):
                return None

        try:
            # Parent visiting only — _find adds this card's token itself.
            issue = self._find_division_by_zero_issue(visiting)
        except Exception:
            return None
        if not issue:
            return None
        # Mixed free-variable issues cannot be fixed by shifting random min/max alone.
        # Leave those to a downstream card that binds the free vars (actionable Suggestion).
        if issue.get("has_unranged"):
            return None
        return issue.get("message")

    def _collect_denominators(self, expr):
        dens = set()

        def walk(e):
            if e is None:
                return
            try:
                e = sp.sympify(e)
            except Exception:
                return
            if e.is_Pow and e.exp.is_Number and e.exp < 0:
                dens.add(sp.simplify(e.base))
                walk(e.base)
            elif e.is_Add or e.is_Mul:
                for arg in e.args:
                    walk(arg)
            elif e.is_Pow:
                walk(e.base)
                walk(e.exp)
            elif getattr(e, "args", None):
                for arg in e.args:
                    walk(arg)
            try:
                _num, den = sp.fraction(sp.together(e))
                if den is not None and den != 1:
                    dens.add(sp.simplify(den))
                    walk(den)
            except Exception:
                pass

        walk(expr)
        # Drop trivial dens
        cleaned = set()
        for d in dens:
            if d is None:
                continue
            try:
                if d == 0:
                    cleaned.add(d)
                    continue
                if d.is_Number and float(d) != 0:
                    continue
            except Exception:
                pass
            cleaned.add(d)
        return cleaned

    def _iter_linked_formula_tokens(self):
        """Sequence tokens of formula entities linked from this card (expression or subs)."""
        found = []
        seen = set()

        def consider(raw):
            if not isinstance(raw, str):
                return
            for match in re.finditer(r"&lt;([^&>]+)&gt;|<([^>]+)>", raw):
                tok = (match.group(1) or match.group(2) or "").strip()
                if not tok or tok in seen:
                    continue
                payload = self._payload_by_sequence_token(tok)
                if payload and payload.get("token") == "formula":
                    seen.add(tok)
                    found.append(tok)

        formula_str = str(
            self.data.get("formula")
            or self.runtime_values.get("formula", "")
            or ""
        )
        consider(formula_str)
        for _var, val in self._collect_formula_substitutions().items():
            consider(val)
        return found

    def _make_formula_validator_for_token(self, clean_token):
        payload = self._payload_by_sequence_token(clean_token)
        if not payload or payload.get("token") != "formula":
            return None
        nested_inputs = dict(payload.get("inputs", {}) or {})
        nested_inputs.setdefault("sequence_token", clean_token)
        return FormulaEntity(
            nested_inputs,
            {"name": "formula", "inputs": {}},
            all_entities_payload=self.all_entities_payload,
        )


class GraphEntity(BaseEntity):
    """
    Validation and evaluation engine for the 'graph' token pattern.
    Handles variable limit constraints, implicit relations, 
    automated bounding rules, and grid rendering parameters.
    """

    def is_valid(self):
        if not super().is_valid():
            return False

        # 🎯 FIX 1: Read incoming inputs directly from self.data instead of self.runtime_values
        raw_formulas = self.data.get("formulas")
        variables_str = self.data.get("variables", "x,y")
        x_axis_input = self.data.get("x-axis range")
        y_axis_input = self.data.get("y-axis range")

        # 🎯 FIX 2: Dynamically re-assemble formula_0, formula_1... if top-level "formulas" is a flat string or empty
        if isinstance(raw_formulas, list) and len(raw_formulas) > 0:
            formulas = raw_formulas
        else:
            formulas = []
            idx = 0
            while f"formula_{idx}" in self.data:
                val = self.data.get(f"formula_{idx}")
                if val is not None and str(val).strip() != "":
                    formulas.append(str(val).strip())
                idx += 1
                
            # Secondary fallback if "formulas" was passed as a flat single expression string
            if not formulas and isinstance(raw_formulas, str) and raw_formulas.strip():
                formulas = [raw_formulas.strip()]

        # Save them safely into runtime values for downstream execution methods (evaluate_output)
        self.runtime_values["formulas"] = formulas
        self.runtime_values["variables"] = variables_str
        
        # Extract grid visualization checkbox flag
        show_grid_raw = self.data.get("show_grid", True)
        self.runtime_values["show_grid"] = str(show_grid_raw).lower() in ["true", "1", "yes", "checked"]

        # Parse declared axis/variable tokens
        parsed_axis_vars = []
        if variables_str:
            parsed_axis_vars = [v.strip() for v in str(variables_str).split(",") if v.strip()]
            for item in parsed_axis_vars:
                # Enforce single character + optional numbers pattern
                if not re.match(r'^[a-zA-Z]\d*$', item):
                    self.errors["variables"] = f"'{item}' is not a valid coordinate variable (must be a single letter followed by 0 or more numbers)."
                    return False
        
        if len(parsed_axis_vars) > 2:
            self.errors["variables"] = "A graph component layout supports a maximum of 2 coordinate axis variables."
            return False

        self.runtime_values["parsed_variables_array"] = parsed_axis_vars

        # 🎯 Check against our newly unified formulas array
        if not formulas:
            self.errors["formulas"] = "At least one formula expression string is required."
            return False

        normalized_formulas = []

        for index, raw_expr in enumerate(formulas):
            if not raw_expr or str(raw_expr).strip() == "":
                self.errors["formulas"] = f"Formula element index [{index}] cannot be an empty string."
                return False

            # Replace token macro dependencies with a dummy number for clean processing
            clean_expr = re.sub(r'&lt;([^&>]+)&gt;|<([^>]+)>', '1', str(raw_expr).strip())
            
            # MATCH STRICT VARIABLE PATTERN: 1 letter followed by 0 or more numbers
            found_symbols = set(re.findall(r'\b[a-zA-Z]\d*\b', clean_expr))
            
            # Apply implicit relation rules if '=' is missing
            if '=' not in clean_expr:
                if len(found_symbols) == 0:
                    implicit_var = 'y' if 'y' in parsed_axis_vars or 'x' not in found_symbols else 'x'
                    clean_expr = f"{implicit_var} = {clean_expr}"
                    found_symbols.add(implicit_var)
                elif len(found_symbols) == 1:
                    alone_var = list(found_symbols)[0]
                    implicit_var = 'y' if alone_var != 'y' else 'x'
                    clean_expr = f"{implicit_var} = {clean_expr}"
                    found_symbols.add(implicit_var)
            else:
                parts = clean_expr.split('=')
                if len(parts) != 2:
                    self.errors["formulas"] = f"Formula index [{index}] contains an invalid equation structure."
                    return False

            # Verify that total free variables for this line do not exceed 2
            if len(found_symbols) > 2:
                self.errors["formulas"] = f"Formula index [{index}] contains too many variables ({', '.join(found_symbols)}). A graph line supports up to 2 free variables."
                return False

            normalized_formulas.append(clean_expr)

        self.runtime_values["normalized_formulas_list"] = normalized_formulas

        # Handle Axis Ranges (Uses user inputs if valid, falls back to automatic calculations if blank)
        self.runtime_values["resolved_x-axis range"] = self._process_axis_bounds("x-axis range", x_axis_input, normalized_formulas)
        self.runtime_values["resolved_y-axis range"] = self._process_axis_bounds("y-axis range", y_axis_input, normalized_formulas)

        # Populate cleaned_data contract for save views
        if len(self.errors) == 0:
            self.cleaned_data = {
                "formulas": formulas,
                "variables": variables_str,
                "show_grid": self.runtime_values["show_grid"],
                "resolved_x_range": self.runtime_values["resolved_x-axis range"],
                "resolved_y_range": self.runtime_values["resolved_y-axis range"],
                "parsed_variables": parsed_axis_vars
            }

            # 🎯 FIX: Forward raw bounding field components directly to saved segment row strings
            # This allows the frontend fields to persist their states on workspace reloads!
            axis_input_keys = ['x_min', 'x_max', 'x_step', 'y_min', 'y_max', 'y_step']
            for field_key in axis_input_keys:
                if field_key in self.data:
                    self.cleaned_data[field_key] = self.data[field_key]
                else:
                    self.cleaned_data[field_key] = ""

            # Keep formula fallback structures inside the database JSON object
            for idx in range(len(formulas)):
                self.cleaned_data[f"formula_{idx}"] = formulas[idx]

        return len(self.errors) == 0

    def _process_axis_bounds(self, axis_key, input_range, normalized_formulas):
        is_blank = (
            not input_range or 
            not isinstance(input_range, list) or 
            len(input_range) != 3 or 
            any(x in [None, "", "null"] for x in input_range)
        )

        if not is_blank:
            try:
                min_val = float(self._resolve_nested_primitive(input_range[0]))
                max_val = float(self._resolve_nested_primitive(input_range[1]))
                step_val = float(self._resolve_nested_primitive(input_range[2]))
                
                if min_val >= max_val:
                    self.errors[axis_key] = "The coordinate minimum range threshold cannot exceed its maximum."
                if step_val <= 0:
                    self.errors[axis_key] = "The step interval must be greater than zero."
                return [min_val, max_val, step_val]
            except (ValueError, TypeError):
                self.errors[axis_key] = "User-defined bounds override contains malformed numbers."
                return [-10.0, 10.0, 1.0]

        # --- Automatic Bounding Estimator Engine ---
        guessed_min, guessed_max, guessed_step = -10.0, 10.0, 1.0
        
        try:
            for formula in normalized_formulas:
                expr_body = formula.split('=')[-1].strip()
                found_numbers = [float(n) for n in re.findall(r'[-+]?\d*\.\d+|\b[-+]?\d+\b', expr_body)]
                
                if found_numbers:
                    max_coef = max(abs(n) for n in found_numbers if n != 0)
                    if max_coef > 0:
                        calculated_pad = round(max_coef * 2.5)
                        calculated_pad = max(5.0, min(calculated_pad, 500.0)) 
                        
                        guessed_max = float(calculated_pad)
                        guessed_min = float(-calculated_pad)
                        
                        span = guessed_max - guessed_min
                        if span <= 20: guessed_step = 1.0
                        elif span <= 100: guessed_step = 5.0
                        else: guessed_step = 25.0
        except Exception:
            pass

        return [guessed_min, guessed_max, guessed_step]

    def _resolve_nested_primitive(self, value):
        if isinstance(value, str) and re.match(r"^<([^>]+)>$", value.strip()):
            return self.resolve_token_dependency(value)
        return value

    def evaluate_output(self):
        raw_formulas = self.runtime_values.get("formulas", [])
        var_list = self.runtime_values.get("parsed_variables_array", ["x", "y"])
        resolved_x = self.runtime_values.get("resolved_x-axis range", [-10.0, 10.0, 1.0])
        resolved_y = self.runtime_values.get("resolved_y-axis range", [-10.0, 10.0, 1.0])
        show_grid = self.runtime_values.get("show_grid", True)

        processed_formulas = []
        
        # Safe contextual macro dependency replacement
        def bracket_replacer(match):
            target_token = match.group(1) if match.group(1) else match.group(2)
            try:
                resolved = self.resolve_token_dependency(f'<{target_token.strip()}>')
                return f"({resolved})"
            except Exception:
                return "1"  # Structural numeric safety fallback during early layout checks

        for formula_expr in raw_formulas:
            clean_expr = re.sub(r'&lt;([^&>]+)&gt;|<([^>]+)>', bracket_replacer, str(formula_expr).strip())
            processed_formulas.append(clean_expr)

        graph_manifest = {
            "archetype": "graph",
            "formulas": processed_formulas,
            "axis_names": var_list,
            "visualization": {
                "show_grid_overlay": show_grid,
            },
            "bounds": {
                "x_range": {"min": resolved_x[0], "max": resolved_x[1], "step": resolved_x[2]},
                "y_range": {"min": resolved_y[0], "max": resolved_y[1], "step": resolved_y[2]}
            }
        }

        return json.dumps(graph_manifest)


class MatrixEntity(BaseEntity):
    """
    Validation and evaluation engine for structural matrix layouts.
    Reconstructs 2D data matrices sent from UI grids into evaluated SymPy structures,
    handling nested token resolution, variables, and scalar operations.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_computed_sympy_result = None

    def is_valid(self):
        if not super().is_valid():
            return False

        # 🎯 1. PARSE DECLARED VARIABLE IDENTIFIERS AND RESOLVE VALUES
        variables_str = self.runtime_values.get("variables", "")
        parsed_variables = []
        variable_substitutions = {}
        
        if variables_str:
            try:
                variables_dict = json.loads(variables_str) if isinstance(variables_str, str) else variables_str
            except Exception:
                self.errors["variables"] = "Failed to parse variables object schema."
                return False

            for item, raw_val in variables_dict.items():
                item = item.strip()
                ok, err = _is_valid_algebraic_variable_name(item)
                if not ok:
                    self.errors["variables"] = err
                    break
                    
                parsed_variables.append(item)

                val_str = str(raw_val).strip()
                if re.match(r"^(?:&lt;|<)[^>&]+(?:&gt;|>)$", val_str):
                    resolved_dep = self.resolve_token_dependency(val_str)
                    if isinstance(resolved_dep, str) and '=' in resolved_dep:
                        resolved_dep = resolved_dep.split('=')[-1].strip()
                    variable_substitutions[item] = resolved_dep
                elif val_str:
                    variable_substitutions[item] = val_str

        if "variables" not in self.errors:
            self.runtime_values["parsed_variables_array"] = parsed_variables
            self.runtime_values["_variable_substitutions_map"] = variable_substitutions

        if self.cleaned_data.get("linked_matrix"):
            return True

        # 🎯 2. RECONCILE FRONTEND MIGRATION & AUTO-EXPAND FLAT PLAIN DATA
        rows = int(self.runtime_values.get("rows", 3))
        cols = int(self.runtime_values.get("columns", 3))
        
        matrix_data = self.runtime_values.get("matrix_data") or self.cleaned_data.get("matrix_data", [])

        # 🎯 THE PATCH: Intercept flat strings/numbers and build the expected 2D shape dynamically
        if isinstance(matrix_data, (str, int, float)):
            fallback_val = str(matrix_data)
            matrix_data = [[fallback_val for _ in range(cols)] for _ in range(rows)]

        if not matrix_data or not isinstance(matrix_data, list):
            self.errors["matrix_data"] = "Matrix configuration is empty or structural layout format is invalid."
            return False

        if len(matrix_data) != rows:
            self.errors["matrix_data"] = f"Grid row mismatch. Expected {rows} rows, found {len(matrix_data)}."
            return False

        # Build dynamic environment context map to validate custom algebraic equations inside cells
        local_dict = {var: sp.Symbol(var) for var in parsed_variables}

        # Validate cell strings using the structured 2D array layout
        for r_idx in range(rows):
            row_data = matrix_data[r_idx]
            if not isinstance(row_data, list) or len(row_data) != cols:
                self.errors["matrix_data"] = f"Grid column size mismatch at row {r_idx}. Expected {cols} columns."
                return False

            for c_idx in range(cols):
                cell_value = row_data[c_idx]

                if cell_value is None:
                    continue
                
                s_val = str(cell_value).strip()
                if not s_val:
                    continue

                if re.match(r"^(?:&lt;|<)[^>&]+(?:&gt;|>)$", s_val):
                    continue

                if re.match(r"^-?\d+(?:\.\d+)?$", s_val):
                    continue

                if s_val in local_dict:
                    continue

                try:
                    self.parse_math_expression(s_val, local_dict=local_dict, evaluate=False)
                except Exception:
                    self.errors["matrix_data"] = (
                        f"Invalid cell calculation at row {r_idx}, column {c_idx} ('{cell_value}'). "
                        f"Cells must contain numbers, valid variables, references, or evaluate mathematically."
                    )
                    return False
            
        # Cache clean matrix grid internally for execution phases
        self.runtime_values["_reconstructed_2d_grid"] = matrix_data
        return len(self.errors) == 0

    def _resolve_cell_to_scalar(self, cell_value, local_dict, evaluate=True) -> sp.Expr:
        if cell_value is None:
            return sp.Integer(0)

        s = str(cell_value).strip()
        if not s:
            return sp.Integer(0)

        token_match = re.match(r"^(?:&lt;|<)([^>&]+)(?:&gt;|>)$", s)
        if token_match:
            clean_token = token_match.group(1).strip()
            resolved_raw = self.resolve_token_dependency(f"<{clean_token}>")
            
            if isinstance(resolved_raw, str) and '=' in resolved_raw:
                parts = resolved_raw.split('=')
                resolved_raw = parts[-1].strip()

            return self.parse_math_expression(str(resolved_raw), local_dict=local_dict, evaluate=evaluate)

        return self.parse_math_expression(s, local_dict=local_dict, evaluate=evaluate)

    def _build_sympy_matrix(self, local_dict, evaluate_cells=True) -> SymPyMatrix:
        linked_token = self.cleaned_data.get("linked_matrix")
        if linked_token:
            raw_target_matrix_val = self.resolve_token_dependency(linked_token)
            
            # Cast stringified SymPy expressions for Matrix A/Override targets
            if isinstance(raw_target_matrix_val, str):
                s_a = raw_target_matrix_val.strip()
                
                # Route stringified Matrix layouts through shared math parser
                if s_a.startswith("Matrix("):
                    return sp.parse_expr(s_a, local_dict=local_dict, evaluate=evaluate_cells)
                else:
                    return self.parse_math_expression(s_a, local_dict=local_dict, evaluate=evaluate_cells)
                    
            if isinstance(raw_target_matrix_val, SymPyMatrix):
                # If it's already an active SymPy Matrix instance object,
                # explicitly substitute our local variables into it
                return raw_target_matrix_val.subs(local_dict)
                
            if isinstance(raw_target_matrix_val, list):
                return SymPyMatrix(raw_target_matrix_val).subs(local_dict)
                
            raise ValueError(f"Unable to parse linked object source data for token {linked_token}.")

        r_count = int(self.runtime_values.get("rows", 3))
        c_count = int(self.runtime_values.get("columns", 3))
        raw_grid = self.runtime_values.get("_reconstructed_2d_grid", [])

        if not raw_grid:
            raise ValueError("Execution context structure missing critical target grid matrix references.")

        evaluated_2d_array = []
        for r_idx in range(r_count):
            current_row = []
            for c_idx in range(c_count):
                cell_scalar = self._resolve_cell_to_scalar(
                    raw_grid[r_idx][c_idx], local_dict, evaluate=evaluate_cells
                )
                current_row.append(cell_scalar)
            evaluated_2d_array.append(current_row)

        return SymPyMatrix(evaluated_2d_array)

    def _build_substitution_local_dict(self, action):
        """
        Build SymPy local_dict for variable substitutions.
        leave as matrix / simplify: parse without evaluating (preserve structure for LaTeX).
        other ops: parse with evaluation so transforms can run.
        """
        var_list = self.runtime_values.get("parsed_variables_array", [])
        subs_map = self.runtime_values.get("_variable_substitutions_map", {})
        evaluate_subs = action not in ("leave as matrix", "simplify")

        local_dict = {}
        for var in var_list:
            if var in subs_map and subs_map[var] is not None:
                local_dict[var] = self.parse_math_expression(
                    str(subs_map[var]), evaluate=evaluate_subs
                )
            else:
                local_dict[var] = sp.Symbol(var)

        if 'pi' not in local_dict:
            local_dict['pi'] = sp.pi
        if 'exp' not in local_dict:
            local_dict['exp'] = sp.exp
        if 'I' not in local_dict:
            local_dict['I'] = sp.I
        return local_dict

    def evaluate_output(self):
        action = self.runtime_values.get("calculate", "leave as matrix")
        local_dict = self._build_substitution_local_dict(action)

        # leave as matrix: substitute without simplifying expression trees
        if action == "leave as matrix":
            with sp.evaluate(False):
                matrix_A = self._build_sympy_matrix(local_dict, evaluate_cells=False)
                result = matrix_A
        elif action == "simplify":
            # Same substitution path as leave as matrix, then simplify each entry
            with sp.evaluate(False):
                matrix_A = self._build_sympy_matrix(local_dict, evaluate_cells=False)
            result = matrix_A.applyfunc(sp.simplify)
        else:
            matrix_A = self._build_sympy_matrix(local_dict, evaluate_cells=True)
            if action == "transpose":
                result = matrix_A.T
            elif action == "inversion":
                if not matrix_A.is_square:
                    raise ValueError("Matrix inversion operation is restricted to square configurations.")
                if matrix_A.det() == 0:
                    raise ValueError("Matrix inversion impossible: System is singular (determinant is zero).")
                result = matrix_A.inv()
            elif action == "determinate":
                if not matrix_A.is_square:
                    raise ValueError("Determinant calculation parameters are restricted to square patterns.")
                result = matrix_A.det()
            elif action == "scalar":
                scalar_multiplier = self.resolve_numeric_value("scalar", default_fallback=1.0)
                result = matrix_A * scalar_multiplier
            elif action in ["multiply", "add", "subtract"]:
                matrix_b_token = self.cleaned_data.get("matrix B")
                if not matrix_b_token:
                    raise ValueError(f"Operation workflow action '{action}' requires a valid linked Matrix B input assignment.")
                
                resolved_b_data = self.resolve_token_dependency(matrix_b_token)
                
                # Cast stringified SymPy expressions smoothly back into functional structures
                if isinstance(resolved_b_data, str):
                    s_b = resolved_b_data.strip()
                    if s_b.startswith("Matrix("):
                        matrix_B = sp.sympify(s_b)
                    else:
                        matrix_B = self.parse_math_expression(s_b, local_dict=local_dict, evaluate=True)
                elif isinstance(resolved_b_data, list):
                    matrix_B = SymPyMatrix(resolved_b_data)
                else:
                    matrix_B = resolved_b_data
                
                if not isinstance(matrix_B, SymPyMatrix):
                    raise TypeError("Resolved calculation targets for Matrix B failed validation checks.")

                if action == "multiply":
                    if matrix_A.cols != matrix_B.rows:
                        raise ValueError(f"Incompatible dimensions: Matrix A columns ({matrix_A.cols}) must match Matrix B rows ({matrix_B.rows}).")
                    result = matrix_A * matrix_B
                elif action == "add":
                    if matrix_A.shape != matrix_B.shape:
                        raise ValueError(f"Incompatible addition sizes: Grid shapes {matrix_A.shape} and {matrix_B.shape} must align exactly.")
                    result = matrix_A + matrix_B
                elif action == "subtract":
                    if matrix_A.shape != matrix_B.shape:
                        raise ValueError(f"Incompatible subtraction sizes: Grid shapes {matrix_A.shape} and {matrix_B.shape} must align exactly.")
                    result = matrix_A - matrix_B
            else:
                result = matrix_A

        result = self.strip_trivial_multiplicative_ones(result)
        self.last_computed_sympy_result = result
        if action == "determinate":
            # Scalar determinant — linkable as integer/double (not a matrix)
            try:
                numeric = float(sp.N(result))
                if numeric.is_integer():
                    self.output_types = ["integer", "double"]
                else:
                    self.output_types = ["double"]
            except Exception:
                self.output_types = ["double"]
        else:
            self.output_types = ["matrix"]
        return str(result)


class MatrixResultByIndexEntity(BaseEntity):
    """
    Extract a single cell from a linked matrix entity using 1-based row/column indices.
    (1, 1) is the upper-left corner of the evaluated matrix result.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_computed_sympy_result = None
        self.output_types = []
        self._resolved_matrix = None
        self._row_index = None
        self._col_index = None

    def _should_simplify(self):
        raw = self.data.get("simplify", False)
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _coerce_to_matrix(self, raw_value):
        # Parse without evaluating so cell structure is preserved until optional simplify.
        if isinstance(raw_value, (SymPyMatrix, sp.MatrixBase)):
            return raw_value
        if isinstance(raw_value, list):
            return SymPyMatrix(raw_value)
        if isinstance(raw_value, str):
            s = raw_value.strip()
            if not s:
                raise ValueError("Linked matrix value is empty.")
            if s.startswith("Matrix("):
                parsed = sp.sympify(s, evaluate=False)
            else:
                parsed = self.parse_math_expression(s, evaluate=False)
            if isinstance(parsed, (SymPyMatrix, sp.MatrixBase)):
                return parsed
            raise ValueError("Linked entity evaluated to a non-matrix value.")
        raise ValueError(f"Unable to interpret linked matrix payload of type {type(raw_value).__name__}.")

    def _classify_cell(self, cell_expr):
        """Return a single most-specific output type for link compatibility."""
        if cell_expr is None:
            return []
        if hasattr(cell_expr, 'free_symbols') and cell_expr.free_symbols:
            return ["formula"]
        try:
            if getattr(cell_expr, 'is_Integer', False):
                return ["integer"]
            if getattr(cell_expr, 'is_integer', False) is True:
                return ["integer"]
            if getattr(cell_expr, 'is_number', False):
                return ["double"]
        except Exception:
            pass
        return ["formula"]

    def is_valid(self):
        if not super().is_valid():
            return False

        # Persist checkbox into cleaned/runtime so saves keep the teacher choice
        simplify_flag = self._should_simplify()
        self.cleaned_data["simplify"] = simplify_flag
        self.runtime_values["simplify"] = simplify_flag

        matrix_token = self.cleaned_data.get("matrix")
        if not matrix_token or (isinstance(matrix_token, str) and not matrix_token.strip()):
            self.errors["matrix"] = "A source matrix must be linked."
            return False

        raw_matrix = self.runtime_values.get("matrix")
        try:
            matrix_obj = self._coerce_to_matrix(raw_matrix)
        except Exception as exc:
            self.errors["matrix"] = (
                f"Linked entity did not evaluate to a matrix: {exc}"
            )
            return False

        row = self.runtime_values.get("row")
        col = self.runtime_values.get("column")

        if row is None:
            self.errors["row"] = "Row index is required (1 = top row)."
        elif not isinstance(row, int) or row < 1:
            self.errors["row"] = "Row index must be an integer greater than or equal to 1."

        if col is None:
            self.errors["column"] = "Column index is required (1 = left column)."
        elif not isinstance(col, int) or col < 1:
            self.errors["column"] = "Column index must be an integer greater than or equal to 1."

        if self.errors:
            return False

        n_rows, n_cols = matrix_obj.shape
        if row > n_rows:
            self.errors["row"] = (
                f"Row {row} is outside matrix dimensions {n_rows}×{n_cols}."
            )
        if col > n_cols:
            self.errors["column"] = (
                f"Column {col} is outside matrix dimensions {n_rows}×{n_cols}."
            )

        if self.errors:
            return False

        self._resolved_matrix = matrix_obj
        self._row_index = row
        self._col_index = col
        return True

    def evaluate_output(self):
        if self._resolved_matrix is None:
            # Allow evaluate after a prior is_valid() on a fresh instance path
            if not self.is_valid():
                raise ValueError("Cannot extract matrix cell: configuration is invalid.")

        cell = self._resolved_matrix[self._row_index - 1, self._col_index - 1]
        cell = self.strip_trivial_multiplicative_ones(cell)
        if self.runtime_values.get("simplify") or self._should_simplify():
            cell = sp.simplify(cell)
        self.last_computed_sympy_result = cell
        self.output_types = self._classify_cell(cell)
        return str(cell)


class NumAnswerEntity(BaseEntity):
    """
    Answer-field numeric response: correct value (literal or linked int/double)
    compared to the student answer after rounding both to N decimal places.
    """

    def _coerce_bool(self, raw):
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _parse_decimal_places(self, raw, default=3):
        if raw is None or raw == "":
            return default
        try:
            n = int(float(raw))
        except (TypeError, ValueError):
            return None
        if n < 0:
            return None
        return n

    def _to_finite_float(self, raw):
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool):
            return None
        try:
            if hasattr(raw, "evalf") and not isinstance(raw, (int, float)):
                val = float(sp.N(raw))
            else:
                val = float(raw)
        except (TypeError, ValueError):
            # Accept fraction / expression strings (e.g. -1/2) the same way shortAnswer does.
            trimmed = str(raw).strip()
            if not trimmed:
                return None
            try:
                expr = self.parse_math_expression(trimmed, evaluate=True)
                val = float(sp.N(expr))
            except Exception:
                return None
        if not math.isfinite(val):
            return None
        return val

    def is_valid(self):
        if not super().is_valid():
            return False

        # Prefer resolved runtime value (links already expanded by BaseEntity)
        raw_value = self.runtime_values.get("value", self.data.get("value"))
        resolved = self._to_finite_float(raw_value)
        if resolved is None:
            self.errors["value"] = "A numeric correct answer is required (number or linked integer/double)."
            return False

        places_raw = self.runtime_values.get(
            "decimal_places",
            self.data.get("decimal_places", 3),
        )
        places = self._parse_decimal_places(places_raw, default=3)
        if places is None:
            self.errors["decimal_places"] = "Decimal places must be an integer greater than or equal to 0."
            return False

        show_note = self._coerce_bool(
            self.data.get(
                "show_rounding_note",
                self.runtime_values.get("show_rounding_note", False),
            )
        )

        self.runtime_values["resolved_value"] = resolved
        self.runtime_values["decimal_places"] = places
        self.runtime_values["show_rounding_note"] = show_note
        self.cleaned_data["value"] = self.data.get("value", resolved)
        self.cleaned_data["decimal_places"] = places
        self.cleaned_data["show_rounding_note"] = show_note
        return True

    def evaluate_output(self):
        resolved = self.runtime_values.get("resolved_value")
        if resolved is None:
            if not self.is_valid():
                raise ValueError("Cannot evaluate numAnswer: configuration is invalid.")
            resolved = self.runtime_values.get("resolved_value")

        places = self.runtime_values.get("decimal_places", 3)
        try:
            places = int(places)
        except (TypeError, ValueError):
            places = 3
        if places < 0:
            places = 0

        rounded = round(float(resolved), places)
        self.output_types = ["double"]
        if places == 0 and float(rounded).is_integer():
            self.output_types = ["integer", "double"]
            return str(int(rounded))
        # Fixed decimal display so the latex box shows the rounded key clearly
        return f"{rounded:.{places}f}"

    def grade_answer(self, student_input, points_available):
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0

        places = self.runtime_values.get("decimal_places", 3)
        try:
            places = int(places)
        except (TypeError, ValueError):
            places = 3
        if places < 0:
            places = 0

        correct = self.runtime_values.get("resolved_value")
        if correct is None:
            correct = self._to_finite_float(self.runtime_values.get("value"))

        raw_student = student_input
        if isinstance(student_input, dict):
            raw_student = student_input.get("value", "")
        if raw_student is None or (isinstance(raw_student, str) and raw_student.strip() == ""):
            return {
                "earned": 0.0,
                "max": pts,
                "detail": "No student input",
            }

        student_val = self._to_finite_float(raw_student)
        if student_val is None or correct is None:
            return {
                "earned": 0.0,
                "max": pts,
                "detail": f"Incorrect (rounded to {places} decimals)",
            }

        rounded_student = round(student_val, places)
        rounded_correct = round(float(correct), places)
        if rounded_student == rounded_correct:
            return {"earned": pts, "max": pts, "detail": "Correct"}
        return {
            "earned": 0.0,
            "max": pts,
            "detail": f"Incorrect (rounded to {places} decimals)",
        }


class ShortAnswerEntity(BaseEntity):
    """
    Answer-field short text / expression response.
    Exact match uses trim + lowercase; sympy path uses trimmed original-case
    strings and requires equivalence without needing further simplification
    (count_ops(student) <= count_ops(correct)). Comparison helpers live on BaseEntity.

    Optional accept_rounded_decimals: after the normal rules fail, evaluate both
    sides numerically and accept if round(student, 3) == round(correct, 3).
    """

    ROUNDED_DECIMAL_PLACES = 3

    def _coerce_bool(self, raw):
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _wants_accept_rounded_decimals(self):
        raw = self.data.get(
            "accept_rounded_decimals",
            self.runtime_values.get("accept_rounded_decimals", False),
        )
        return self._coerce_bool(raw)

    def _expr_to_float(self, raw):
        """
        Parse a student/key string to a finite float.
        Accepts plain decimals and sympy-evaluable expressions (e.g. 8/9).
        Equations and non-numeric text return None.
        """
        trimmed = self._trim_str(raw)
        if not trimmed:
            return None
        try:
            direct = float(trimmed)
            if math.isfinite(direct):
                return direct
        except (TypeError, ValueError):
            pass

        expr = self._to_sympy(trimmed)
        if expr is None or isinstance(expr, sp.Equality):
            return None
        try:
            numeric = float(sp.N(expr))
        except Exception:
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    def is_valid(self):
        if not super().is_valid():
            return False

        raw_value = self.runtime_values.get("value", self.data.get("value"))
        trimmed = self._trim_str(raw_value)
        if not trimmed:
            self.errors["value"] = "A correct answer is required (text or linked formula)."
            return False

        simplified = self._simplify_key(trimmed)
        accept_rounded = self._wants_accept_rounded_decimals()
        self.runtime_values["resolved_value"] = trimmed
        self.runtime_values["simplified_key"] = simplified
        self.runtime_values["accept_rounded_decimals"] = accept_rounded
        self.cleaned_data["value"] = self.data.get("value", trimmed)
        self.cleaned_data["accept_rounded_decimals"] = accept_rounded
        return True

    def evaluate_output(self):
        simplified = self.runtime_values.get("simplified_key")
        if simplified is None:
            if not self.is_valid():
                raise ValueError("Cannot evaluate shortAnswer: configuration is invalid.")
            simplified = self.runtime_values.get("simplified_key")

        self.output_types = ["string"]
        return str(simplified) if simplified is not None else ""

    def grade_answer(self, student_input, points_available):
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0

        correct_key = self.runtime_values.get("simplified_key")
        if correct_key is None:
            raw_correct = self.runtime_values.get(
                "resolved_value",
                self.runtime_values.get("value", self.data.get("value")),
            )
            correct_key = self._simplify_key(raw_correct)

        student_raw = student_input
        if isinstance(student_input, dict):
            student_raw = student_input.get("value", "")
        student_trimmed = self._trim_str(student_raw)

        if not student_trimmed:
            return {"earned": 0.0, "max": pts, "detail": "No student input"}

        if self._grade_short_answer_text(student_trimmed, correct_key):
            # Distinguish exact vs sympy for detail (same outcome)
            if student_trimmed.lower() == self._trim_str(correct_key).lower():
                return {"earned": pts, "max": pts, "detail": "Exact match"}
            return {"earned": pts, "max": pts, "detail": "Equivalent (simplified form)"}

        # Optional: accept when both evaluate to the same value at 3 decimal places
        accept_rounded = self.runtime_values.get("accept_rounded_decimals")
        if accept_rounded is None:
            accept_rounded = self._wants_accept_rounded_decimals()
        if accept_rounded:
            places = self.ROUNDED_DECIMAL_PLACES
            student_num = self._expr_to_float(student_trimmed)
            correct_num = self._expr_to_float(correct_key)
            if (
                student_num is not None
                and correct_num is not None
                and round(student_num, places) == round(correct_num, places)
            ):
                return {
                    "earned": pts,
                    "max": pts,
                    "detail": f"Correct (rounded to {places} decimals)",
                }

        # Match prior detail when sympy-equivalent but not simplified enough
        student_expr = self._to_sympy(student_trimmed)
        correct_expr = self._to_sympy(correct_key)
        if (
            student_expr is not None
            and correct_expr is not None
            and self._exprs_equivalent(student_expr, correct_expr)
        ):
            try:
                if sp.count_ops(student_expr) > sp.count_ops(correct_expr):
                    return {
                        "earned": 0.0,
                        "max": pts,
                        "detail": "Equivalent but not simplified",
                    }
            except Exception:
                pass
        return {"earned": 0.0, "max": pts, "detail": "Incorrect"}


class LongAnswerEntity(BaseEntity):
    """
    Free-response paragraph answer field. No auto-grading — preview always
    reports earned 0 of available points with a manual-grading detail.
    """

    def is_valid(self):
        return super().is_valid()

    def evaluate_output(self):
        self.output_types = ["content"]
        return "Long answer (manual grading)"

    def grade_answer(self, student_input, points_available):
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0
        return {
            "earned": 0.0,
            "max": pts,
            "detail": "To be graded manually",
        }


class CanvasEntity(BaseEntity):
    """
    Scratch-paper canvas answer field. Optional linked source as underlay.
    No auto-grading — manual when points > 0; scratch paper when points = 0.
    """

    def is_valid(self):
        if not super().is_valid():
            return False
        source = self.cleaned_data.get("source")
        if source is None or source is False or (isinstance(source, str) and not str(source).strip()):
            self.cleaned_data["source"] = None
            self.runtime_values["source"] = None
        return True

    def evaluate_output(self):
        self.output_types = ["content"]
        source = self.cleaned_data.get("source")
        if isinstance(source, str) and re.match(r"^<[^>]+>$", source.strip()):
            label = source.strip().replace("<", "").replace(">", "")
            return f"Canvas over <{label}>"
        return "Canvas (scratch paper)"

    def grade_answer(self, student_input, points_available):
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0
        detail = "To be graded manually" if pts > 0 else "Scratch paper (not graded)"
        return {
            "earned": 0.0,
            "max": pts,
            "detail": detail,
        }


class MatrixAnswerEntity(BaseEntity):
    """
    Answer-field matrix fill-in: link a matrix Dynamic Variable, mark cells to solve,
    grade each blank like shortAnswer. Modes: points_per_cell, whole_matrix, per_cell.
    """

    GRADING_MODES = ("points_per_cell", "whole_matrix", "per_cell")
    DEFAULT_GRADING_MODE = "points_per_cell"

    def _coerce_to_matrix(self, raw_value):
        if isinstance(raw_value, (SymPyMatrix, sp.MatrixBase)):
            return raw_value
        if isinstance(raw_value, list):
            return SymPyMatrix(raw_value)
        if isinstance(raw_value, str):
            s = raw_value.strip()
            if not s:
                raise ValueError("Linked matrix value is empty.")
            if s.startswith("Matrix("):
                parsed = sp.sympify(s, evaluate=False)
            else:
                parsed = self.parse_math_expression(s, evaluate=False)
            if isinstance(parsed, (SymPyMatrix, sp.MatrixBase)):
                return parsed
            raise ValueError("Linked entity evaluated to a non-matrix value.")
        raise ValueError(f"Unable to interpret linked matrix payload of type {type(raw_value).__name__}.")

    def _normalize_solve_cells(self, raw, nrows, ncols):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        if not isinstance(raw, (list, tuple)):
            return []

        seen = set()
        out = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            try:
                r = int(item[0])
                c = int(item[1])
            except (TypeError, ValueError):
                continue
            if r < 0 or c < 0 or r >= nrows or c >= ncols:
                continue
            key = (r, c)
            if key in seen:
                continue
            seen.add(key)
            out.append([r, c])
        return out

    def _mode_max(self, mode, points, n_solve):
        try:
            pts = float(points) if points is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0
        if mode == "points_per_cell":
            return pts * max(n_solve, 0)
        return pts

    def _resolve_grading_mode(self):
        mode = str(
            self.runtime_values.get(
                "grading_mode",
                self.data.get("grading_mode", self.DEFAULT_GRADING_MODE),
            )
        ).strip()
        if mode not in self.GRADING_MODES:
            mode = self.DEFAULT_GRADING_MODE
        return mode

    def _store_matrix_runtime(self, matrix_obj, solve_cells, mode):
        """Persist dims/grid for author UI even when solve_cells is still empty."""
        nrows, ncols = int(matrix_obj.rows), int(matrix_obj.cols)
        cell_keys = [f"{r},{c}" for r, c in solve_cells]
        correct_by_key = {}
        rows_display = []
        for r in range(nrows):
            row_vals = []
            for c in range(ncols):
                cell_str = str(matrix_obj[r, c])
                row_vals.append(cell_str)
                key = f"{r},{c}"
                if key in cell_keys:
                    correct_by_key[key] = self._simplify_key(cell_str)
            rows_display.append(row_vals)

        self.runtime_values["resolved_matrix"] = matrix_obj
        self.runtime_values["nrows"] = nrows
        self.runtime_values["ncols"] = ncols
        self.runtime_values["solve_cells"] = solve_cells
        self.runtime_values["solve_keys"] = cell_keys
        self.runtime_values["correct_by_key"] = correct_by_key
        self.runtime_values["rows_display"] = rows_display
        self.runtime_values["grading_mode"] = mode
        self.cleaned_data["solve_cells"] = solve_cells
        self.cleaned_data["grading_mode"] = mode

    def is_valid(self):
        if not super().is_valid():
            return False

        matrix_token = self.cleaned_data.get("matrix")
        if not matrix_token or (isinstance(matrix_token, str) and not matrix_token.strip()):
            self.errors["matrix"] = "A source matrix must be linked."
            return False

        raw_matrix = self.runtime_values.get("matrix")
        try:
            matrix_obj = self._coerce_to_matrix(raw_matrix)
        except Exception as exc:
            self.errors["matrix"] = f"Linked entity did not evaluate to a matrix: {exc}"
            return False

        nrows, ncols = int(matrix_obj.rows), int(matrix_obj.cols)
        raw_solve = self.data.get("solve_cells", self.runtime_values.get("solve_cells", []))
        solve_cells = self._normalize_solve_cells(raw_solve, nrows, ncols)
        mode = self._resolve_grading_mode()

        # Always store the grid so the author card can paint cells even before
        # any solve cells are marked (is_valid still fails until ≥1 is set).
        self.cleaned_data["matrix"] = matrix_token
        self._store_matrix_runtime(matrix_obj, solve_cells, mode)

        if len(solve_cells) < 1:
            self.errors["solve_cells"] = "Mark at least one cell as set to solve."
            return False

        return True

    def evaluate_output(self):
        """
        Build author/preview JSON. Works with 0 solve cells when the matrix was
        already hydrated by is_valid (partial / incomplete configuration).
        """
        if self.runtime_values.get("rows_display") is None:
            # Soft hydrate without requiring solve cells
            if not isinstance(self.data, dict):
                raise ValueError("Cannot evaluate matrixAnswer: configuration is invalid.")
            matrix_token = self.data.get("matrix") or self.cleaned_data.get("matrix")
            if not matrix_token:
                raise ValueError("Cannot evaluate matrixAnswer: no matrix linked.")
            raw_matrix = self.runtime_values.get("matrix")
            if raw_matrix is None and isinstance(matrix_token, str) and re.match(r"^<[^>]+>$", matrix_token.strip()):
                raw_matrix = self.resolve_token_dependency(matrix_token)
                self.runtime_values["matrix"] = raw_matrix
            matrix_obj = self._coerce_to_matrix(raw_matrix)
            nrows, ncols = int(matrix_obj.rows), int(matrix_obj.cols)
            solve_cells = self._normalize_solve_cells(
                self.data.get("solve_cells", self.runtime_values.get("solve_cells", [])),
                nrows,
                ncols,
            )
            self._store_matrix_runtime(matrix_obj, solve_cells, self._resolve_grading_mode())

        nrows = self.runtime_values.get("nrows", 0)
        ncols = self.runtime_values.get("ncols", 0)
        solve_cells = self.runtime_values.get("solve_cells") or []
        mode = self.runtime_values.get("grading_mode", self.DEFAULT_GRADING_MODE)
        n = len(solve_cells)
        if n < 1:
            summary = f"{nrows}×{ncols} — click cells to set to solve"
        else:
            summary = f"{nrows}×{ncols}, {n} cells to solve ({mode})"
        payload = {
            "archetype": "matrixAnswer",
            "summary": summary,
            "rows": self.runtime_values.get("rows_display") or [],
            "solve_cells": solve_cells,
            "grading_mode": mode,
        }
        self.output_types = ["content"]
        return json.dumps(payload)

    def grade_answer(self, student_input, points_available):
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0

        if self.runtime_values.get("correct_by_key") is None:
            self.is_valid()

        solve_cells = self.runtime_values.get("solve_cells") or []
        correct_by_key = self.runtime_values.get("correct_by_key") or {}
        mode = self.runtime_values.get("grading_mode", self.DEFAULT_GRADING_MODE)
        if mode not in self.GRADING_MODES:
            mode = self.DEFAULT_GRADING_MODE
        n = len(solve_cells)
        mode_max = self._mode_max(mode, pts, n)

        cells_map = {}
        if isinstance(student_input, dict):
            raw_cells = student_input.get("cells", student_input)
            if isinstance(raw_cells, dict):
                cells_map = raw_cells

        def cell_value(r, c):
            key = f"{r},{c}"
            if key in cells_map:
                return cells_map.get(key)
            return cells_map.get(f"{r}, {c}", "")

        any_filled = False
        correct_count = 0
        for pair in solve_cells:
            r, c = pair[0], pair[1]
            key = f"{r},{c}"
            student_val = self._trim_str(cell_value(r, c))
            if student_val:
                any_filled = True
            correct_val = correct_by_key.get(key, "")
            if self._grade_short_answer_text(student_val, correct_val):
                correct_count += 1

        if not any_filled:
            return {"earned": 0.0, "max": mode_max, "detail": "No student input"}

        if n <= 0:
            return {"earned": 0.0, "max": mode_max, "detail": "No solve cells"}

        if mode == "whole_matrix":
            earned = pts if correct_count == n else 0.0
        elif mode == "points_per_cell":
            earned = correct_count * pts
        else:  # per_cell — split points
            earned = pts * (correct_count / n)

        return {
            "earned": float(earned),
            "max": float(mode_max),
            "detail": f"{correct_count}/{n} cells correct ({mode})",
        }


class ArrayMatchingUnorderedEntity(BaseEntity):
    """
    Answer-field comma-separated list matching (unordered by default).
    Outer () or [] wrappers around the whole string are stripped before parse.
    Segments split on commas outside parentheses/brackets. Each segment uses
    shortAnswer rules (exact trim+lowercase, else sympy with count_ops gate).
    Optional ordered matching and partial credit.
    """

    def _coerce_bool(self, raw):
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _raw_to_str(self, raw):
        if raw is None:
            return ""
        if isinstance(raw, dict):
            raw = raw.get("value", raw.get("results", ""))
        if isinstance(raw, (list, tuple)):
            return ", ".join(str(x) for x in raw)
        return str(raw)

    def _is_fully_wrapped(self, s, open_ch, close_ch):
        """True iff s is one balanced outer open_ch...close_ch pair."""
        if len(s) < 2 or s[0] != open_ch or s[-1] != close_ch:
            return False
        depth = 0
        for i, ch in enumerate(s):
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    return False
                if depth < 0:
                    return False
        return depth == 0

    def _strip_outer_wrappers(self, s):
        """
        If the entire trimmed string is wrapped in (...) or [...], peel those
        layers before comma-splitting (e.g. "[2,3]" / "(2,3)" → "2,3").
        """
        s = str(s).strip()
        while len(s) >= 2:
            if self._is_fully_wrapped(s, "(", ")"):
                s = s[1:-1].strip()
                continue
            if self._is_fully_wrapped(s, "[", "]"):
                s = s[1:-1].strip()
                continue
            break
        return s

    def _split_paren_aware(self, raw):
        """
        Split on commas only when not inside (...) or [...].
        Commas inside nesting stay part of the same segment.
        """
        s = self._strip_outer_wrappers(self._raw_to_str(raw))
        if not s:
            return []
        parts = []
        buf = []
        depth = 0
        for ch in s:
            if ch in "([":
                depth += 1
                buf.append(ch)
            elif ch in ")]":
                depth = max(0, depth - 1)
                buf.append(ch)
            elif ch == "," and depth == 0:
                piece = "".join(buf).strip()
                if piece:
                    parts.append(piece)
                buf = []
            else:
                buf.append(ch)
        piece = "".join(buf).strip()
        if piece:
            parts.append(piece)
        return parts

    def _parse_list(self, raw):
        return self._split_paren_aware(raw)

    def _items_match(self, student_piece, key_piece):
        """Match via shortAnswer formula/text rules, then numeric round-3 (incl. oo)."""
        if self._grade_short_answer_text(student_piece, key_piece):
            return True
        # Infinity endpoints: oo / -oo
        try:
            sa = str(student_piece).strip().lower().replace("∞", "oo").replace("infty", "oo")
            sb = str(key_piece).strip().lower().replace("∞", "oo").replace("infty", "oo")
            if sa in ("oo", "+oo", "inf", "+inf") and sb in ("oo", "+oo", "inf", "+inf"):
                return True
            if sa in ("-oo", "-inf") and sb in ("-oo", "-inf"):
                return True
        except Exception:
            pass
        try:
            na = float(str(student_piece).strip())
            nb = float(str(key_piece).strip())
            if math.isfinite(na) and math.isfinite(nb):
                return round(na, 3) == round(nb, 3)
        except (TypeError, ValueError):
            pass
        # SymPy parse (fractions / oo)
        try:
            ea = self._to_sympy(student_piece)
            eb = self._to_sympy(key_piece)
            if ea is not None and eb is not None and self._exprs_equivalent(ea, eb):
                return True
        except Exception:
            pass
        return False

    def _format_list(self, items):
        return ", ".join(str(t) for t in items)

    def _match_counts_unordered(self, key_items, student_items):
        """Greedy multiset match. Returns (matches, missing, extras)."""
        remaining = list(student_items)
        matches = 0
        for key in key_items:
            found_idx = None
            for i, stud in enumerate(remaining):
                if self._items_match(stud, key):
                    found_idx = i
                    break
            if found_idx is not None:
                matches += 1
                remaining.pop(found_idx)
        missing = len(key_items) - matches
        extras = len(remaining)
        return matches, missing, extras

    def _match_counts_ordered(self, key_items, student_items):
        """Positional match. Returns (matches, missing, extras)."""
        n = len(key_items)
        m = len(student_items)
        matches = 0
        for i in range(min(n, m)):
            if self._items_match(student_items[i], key_items[i]):
                matches += 1
        missing = n - matches
        extras = max(0, m - n)
        return matches, missing, extras

    def _match_counts(self, key_items, student_items, ordered=False):
        if ordered:
            return self._match_counts_ordered(key_items, student_items)
        return self._match_counts_unordered(key_items, student_items)

    def is_valid(self):
        if not super().is_valid():
            return False

        raw_results = self.runtime_values.get("results", self.data.get("results"))
        key_items = self._parse_list(raw_results)
        if not key_items:
            self.errors["results"] = "At least one comma-separated answer is required (or link primeFactors)."
            return False

        partial = self._coerce_bool(
            self.data.get(
                "partial_credit",
                self.runtime_values.get("partial_credit", False),
            )
        )
        ordered = self._coerce_bool(
            self.data.get(
                "ordered",
                self.runtime_values.get("ordered", False),
            )
        )

        self.runtime_values["key_items"] = key_items
        self.runtime_values["key_display"] = self._format_list(key_items)
        self.runtime_values["partial_credit"] = partial
        self.runtime_values["ordered"] = ordered
        self.cleaned_data["results"] = self.data.get("results", raw_results)
        self.cleaned_data["partial_credit"] = partial
        self.cleaned_data["ordered"] = ordered
        return True

    def evaluate_output(self):
        display = self.runtime_values.get("key_display")
        if display is None:
            if not self.is_valid():
                raise ValueError("Cannot evaluate arrayMatchingUnordered: configuration is invalid.")
            display = self.runtime_values.get("key_display")
        self.output_types = ["string"]
        return str(display) if display is not None else ""

    def grade_answer(self, student_input, points_available):
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0

        key_items = self.runtime_values.get("key_items")
        if key_items is None:
            raw_results = self.runtime_values.get("results", self.data.get("results"))
            key_items = self._parse_list(raw_results)

        n = len(key_items) if key_items else 0
        if n == 0:
            return {"earned": 0.0, "max": pts, "detail": "No answer key"}

        student_raw = student_input
        if isinstance(student_input, dict):
            student_raw = student_input.get("value", student_input.get("results", ""))
        student_str = self._raw_to_str(student_raw).strip()
        if not student_str:
            return {"earned": 0.0, "max": pts, "detail": "No student input"}

        student_items = self._parse_list(student_str)
        ordered = self._coerce_bool(
            self.runtime_values.get(
                "ordered",
                self.data.get("ordered", False),
            )
        )
        matches, missing, extras = self._match_counts(key_items, student_items, ordered=ordered)
        partial = self._coerce_bool(
            self.runtime_values.get(
                "partial_credit",
                self.data.get("partial_credit", False),
            )
        )

        order_note = "ordered" if ordered else "unordered"
        if not partial:
            if matches == n and extras == 0 and missing == 0:
                return {"earned": pts, "max": pts, "detail": f"All correct ({order_note})"}
            return {"earned": 0.0, "max": pts, "detail": "Incorrect"}

        sub = pts / n
        earned = matches * sub - 0.5 * sub * (missing + extras)
        if earned < 0:
            earned = 0.0
        return {
            "earned": earned,
            "max": pts,
            "detail": f"{matches}/{n} matched ({order_note}, partial)",
        }


class AnswersOrDneEntity(BaseEntity):
    """
    Answer field: either Correct-is-DNE, or one-or-more linked answer keys
    (shortAnswer / arrayMatchingUnordered / numAnswer / formula-with-simplify).

    A linked formula (solve method = simplify with a target variable) expands into
    multiple virtual keys from the Or/And/Eq solution: equalities → point answers,
    bound conjunctions → ordered coordinate intervals (e.g. [-oo, -1]).

    Student submits DNE or typed entries; unordered multiset match via graders /
    cross shortAnswer↔numAnswer equivalence.
    """

    ALLOWED_KEY_ARCHETYPES = (
        "shortAnswer",
        "arrayMatchingUnordered",
        "numAnswer",
        "formula",
    )
    STUDENT_ENTRY_TYPES = ("shortAnswer", "arrayMatchingUnordered", "numAnswer")
    GRADING_MODES = ("all_or_nothing", "per_answer")

    def _coerce_bool(self, raw, default=False):
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _normalize_answers_list(self, raw):
        if raw is None or raw is False:
            return []
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return []
            if s.startswith("["):
                try:
                    raw = json.loads(s)
                except Exception:
                    # single token string
                    return [s] if re.match(r"^<[^>]+>$", s) else []
            elif re.match(r"^<[^>]+>$", s):
                return [s]
            else:
                return []
        if not isinstance(raw, (list, tuple)):
            return []
        out = []
        for item in raw:
            if item is None:
                continue
            if isinstance(item, dict):
                tok = item.get("token") or item.get("value") or ""
            else:
                tok = str(item).strip()
            tok = tok.replace("&lt;", "<").replace("&gt;", ">").strip()
            if not tok:
                continue
            if not tok.startswith("<"):
                tok = f"<{tok}>"
            if not tok.endswith(">"):
                tok = f"{tok}>"
            if re.match(r"^<[^>]+>$", tok):
                out.append(tok)
        return out

    def _find_payload(self, sequence_token):
        clean = str(sequence_token or "").replace("<", "").replace(">", "").strip()
        if not clean:
            return None
        return next(
            (
                item
                for item in (self.all_entities_payload or [])
                if (item.get("sequence_token") or item.get("indexed_token") or "") == clean
            ),
            None,
        )

    def _validator_for_payload(self, payload):
        archetype = payload.get("token")
        blueprint = get_blueprint_for_token(archetype)
        return get_entity_validator(
            archetype,
            payload.get("inputs", {}) or {},
            blueprint,
            all_entities_payload=self.all_entities_payload,
        )

    # ------------------------------------------------------------------
    # Formula simplify → answer slots (points + intervals)
    # ------------------------------------------------------------------

    def _format_slot_endpoint(self, value):
        if value is None:
            return None
        if value == sp.oo or value is sp.oo:
            return "oo"
        if value == -sp.oo or value is -sp.oo:
            return "-oo"
        try:
            if isinstance(value, sp.Rational) and value.q != 1:
                return str(value)
            if isinstance(value, sp.Integer):
                return str(int(value))
            simplified = sp.simplify(value)
            return str(simplified)
        except Exception:
            return str(value)

    def _format_interval_slot(self, lo, lo_closed, hi, hi_closed):
        # Unbounded ends conventionally use matching brackets in student entry
        # (e.g. [-oo,-1] even though -oo is open).
        left = "[" if (lo_closed or lo == -sp.oo) else "("
        right = "]" if (hi_closed or hi == sp.oo) else ")"
        return f"{left}{self._format_slot_endpoint(lo)},{self._format_slot_endpoint(hi)}{right}"

    def _relational_bound_on_symbol(self, rel, symbol):
        """
        If rel constrains `symbol`, return (side, bound, closed) where side is
        'lo' or 'hi'. Otherwise None.
        """
        if not isinstance(rel, Relational) or isinstance(rel, sp.Equality):
            return None
        lhs, rhs = rel.lhs, rel.rhs
        # symbol on left: x < a, x <= a, x > a, x >= a
        if lhs == symbol and symbol not in getattr(rhs, "free_symbols", set()):
            bound = rhs
            if isinstance(rel, (sp.StrictLessThan, sp.LessThan)):
                return ("hi", bound, isinstance(rel, sp.LessThan))
            if isinstance(rel, (sp.StrictGreaterThan, sp.GreaterThan)):
                return ("lo", bound, isinstance(rel, sp.GreaterThan))
        # symbol on right: a < x, a <= x, a > x, a >= x
        if rhs == symbol and symbol not in getattr(lhs, "free_symbols", set()):
            bound = lhs
            if isinstance(rel, (sp.StrictLessThan, sp.LessThan)):
                return ("lo", bound, isinstance(rel, sp.LessThan))
            if isinstance(rel, (sp.StrictGreaterThan, sp.GreaterThan)):
                return ("hi", bound, isinstance(rel, sp.GreaterThan))
        return None

    def _and_to_interval(self, expr, symbol):
        """
        Parse And of inequalities on `symbol` into (lo, lo_closed, hi, hi_closed).
        Defaults: lo=-oo (open), hi=+oo (open).
        """
        lo, lo_closed = -sp.oo, False
        hi, hi_closed = sp.oo, False
        saw_bound = False
        for rel in sp.And.make_args(expr):
            parsed = self._relational_bound_on_symbol(rel, symbol)
            if parsed is None:
                return None
            side, bound, closed = parsed
            saw_bound = True
            if side == "lo":
                # Tightest lower bound
                try:
                    if bound == -sp.oo:
                        lo, lo_closed = -sp.oo, False
                    elif lo == -sp.oo or sp.simplify(bound - lo) >= 0:
                        lo, lo_closed = bound, closed
                    elif sp.simplify(bound - lo) == 0:
                        lo_closed = lo_closed and closed
                except Exception:
                    lo, lo_closed = bound, closed
            else:
                try:
                    if bound == sp.oo:
                        hi, hi_closed = sp.oo, False
                    elif hi == sp.oo or sp.simplify(hi - bound) >= 0:
                        hi, hi_closed = bound, closed
                    elif sp.simplify(hi - bound) == 0:
                        hi_closed = hi_closed and closed
                except Exception:
                    hi, hi_closed = bound, closed
        if not saw_bound:
            return None
        return (lo, lo_closed, hi, hi_closed)

    def _solution_expr_to_slots(self, expr, symbol):
        """
        Flatten Or/And/Eq/Relational/list solution into slot descriptors:
          ("point", sympy_value) or ("interval", (lo, lo_closed, hi, hi_closed))
        """
        if expr is None:
            return []
        if expr is True or expr == sp.true:
            return [("interval", (-sp.oo, False, sp.oo, False))]
        if expr is False or expr == sp.false:
            return []

        # Multi-root list / set forms: x = [-4/3, -1, 0]
        if isinstance(expr, (list, tuple, set, frozenset, sp.FiniteSet)):
            slots = []
            for item in expr:
                slots.extend(self._solution_expr_to_slots(item, symbol))
            return slots

        if isinstance(expr, sp.Or):
            slots = []
            for arg in sp.Or.make_args(expr):
                slots.extend(self._solution_expr_to_slots(arg, symbol))
            return slots

        if isinstance(expr, sp.Equality):
            lhs, rhs = expr.lhs, expr.rhs
            # Eq(x, list-like) shouldn't happen; handle FiniteSet on one side
            if isinstance(rhs, (list, tuple, set, frozenset, sp.FiniteSet)) and lhs == symbol:
                return [("point", sp.simplify(s)) for s in rhs]
            if isinstance(lhs, (list, tuple, set, frozenset, sp.FiniteSet)) and rhs == symbol:
                return [("point", sp.simplify(s)) for s in lhs]
            if lhs == symbol:
                return [("point", sp.simplify(rhs))]
            if rhs == symbol:
                return [("point", sp.simplify(lhs))]
            # Eq rearranged: try solve
            try:
                sols = sp.solve(expr, symbol)
                if isinstance(sols, (list, tuple)):
                    return [("point", sp.simplify(s)) for s in sols]
                if sols is not None:
                    return [("point", sp.simplify(sols))]
            except Exception:
                pass
            return []

        if isinstance(expr, sp.And):
            interval = self._and_to_interval(expr, symbol)
            if interval is not None:
                return [("interval", interval)]
            # Nested Or inside And — uncommon; flatten args
            slots = []
            for arg in sp.And.make_args(expr):
                slots.extend(self._solution_expr_to_slots(arg, symbol))
            return slots

        if isinstance(expr, Relational):
            parsed = self._relational_bound_on_symbol(expr, symbol)
            if parsed is None:
                return []
            side, bound, closed = parsed
            if side == "lo":
                return [("interval", (bound, closed, sp.oo, False))]
            return [("interval", (-sp.oo, False, bound, closed))]

        # Bare numeric / symbolic root value (from a solution list item)
        try:
            if symbol not in getattr(expr, "free_symbols", set()):
                return [("point", sp.simplify(expr))]
        except Exception:
            pass

        return []

    def _slots_from_evaluated_list_string(self, text, symbol):
        """
        Parse display strings like 'x = [-4/3, -1, 0]' or '[-4/3, -1, 0]'
        into point slots when last_computed was only the target Symbol.
        """
        s = self._trim_str(text)
        if not s:
            return []
        sym_name = str(symbol)
        m = re.match(
            rf"^{re.escape(sym_name)}\s*=\s*\[(.*)\]\s*$",
            s,
            flags=re.DOTALL,
        )
        if not m:
            m = re.match(r"^\[(.*)\]\s*$", s, flags=re.DOTALL)
        if not m:
            return []
        inner = m.group(1).strip()
        if not inner:
            return []
        # Reuse arrayMatching paren-aware split via a lightweight local split
        parts = []
        buf = []
        depth = 0
        for ch in inner:
            if ch in "([":
                depth += 1
                buf.append(ch)
            elif ch in ")]":
                depth = max(0, depth - 1)
                buf.append(ch)
            elif ch == "," and depth == 0:
                piece = "".join(buf).strip()
                if piece:
                    parts.append(piece)
                buf = []
            else:
                buf.append(ch)
        piece = "".join(buf).strip()
        if piece:
            parts.append(piece)

        slots = []
        for part in parts:
            try:
                val = sp.sympify(part)
                slots.append(("point", sp.simplify(val)))
            except Exception:
                expr = self._to_sympy(part)
                if expr is not None:
                    slots.append(("point", sp.simplify(expr)))
        return slots

    def _slot_to_virtual_payload(self, slot, parent_token, index):
        kind, payload = slot
        seq = f"{parent_token}__slot_{index}"
        if kind == "point":
            value = self._format_slot_endpoint(payload)
            return {
                "token": "shortAnswer",
                "sequence_token": seq,
                "indexed_token": seq,
                "inputs": {
                    "value": value,
                    "accept_rounded_decimals": True,
                },
                "_virtual_from_formula": parent_token,
                "_slot_display": value,
            }
        if kind == "interval":
            lo, lo_closed, hi, hi_closed = payload
            display = self._format_interval_slot(lo, lo_closed, hi, hi_closed)
            # Ordered coordinate list; outer brackets stripped by grader
            results = f"{self._format_slot_endpoint(lo)}, {self._format_slot_endpoint(hi)}"
            return {
                "token": "arrayMatchingUnordered",
                "sequence_token": seq,
                "indexed_token": seq,
                "inputs": {
                    "results": results,
                    "ordered": True,
                    "partial_credit": False,
                },
                "_virtual_from_formula": parent_token,
                "_slot_display": display,
            }
        return None

    def _virtual_payloads_from_formula(self, formula_payload):
        """
        Evaluate a simplify-for-variable formula and expand into virtual keys.
        Returns (payloads_list, error_message).
        """
        try:
            validator = self._validator_for_payload(formula_payload)
        except Exception as exc:
            return [], f"Could not load formula: {exc}"

        inputs = formula_payload.get("inputs") or {}
        method = str(
            inputs.get("solve method")
            or validator.runtime_values.get("solve method")
            or validator.data.get("solve method")
            or ""
        ).strip()
        target = str(
            inputs.get("variable to simplify")
            or inputs.get("variable to solve for")
            or validator.runtime_values.get("variable to simplify")
            or validator.runtime_values.get("variable to solve for")
            or ""
        ).strip()
        if target in ("-- N/A --", "-- choose variable --"):
            target = ""

        if method != "simplify":
            return [], (
                "Linked formula must use solve method “simplify” "
                "with a target variable selected."
            )
        if not target:
            return [], (
                "Linked formula must have a target variable selected "
                "under “Target Variable to Simplify”."
            )

        if not validator.is_valid():
            err = next(iter(validator.errors.values()), "invalid formula")
            return [], f"Linked formula is invalid: {err}"

        try:
            evaluated = validator.evaluate_output()
        except Exception as exc:
            return [], f"Linked formula could not be evaluated: {exc}"

        result_obj = getattr(validator, "last_computed_sympy_result", None)
        solution_list = getattr(validator, "last_solution_list", None)
        if result_obj is None and not solution_list:
            return [], "Linked formula produced no simplify result to expand."

        # Tuple (lhs, rhs) from non-targeted simplify — not expandable
        if isinstance(result_obj, tuple) and not solution_list:
            return [], (
                "Linked formula simplify result is not a solved relation for the "
                "target variable (got a left/right pair). Ensure a target variable is set."
            )

        symbol = sp.Symbol(target)
        slots = []
        if solution_list:
            slots = self._solution_expr_to_slots(list(solution_list), symbol)
        if not slots and result_obj is not None and not isinstance(result_obj, tuple):
            slots = self._solution_expr_to_slots(result_obj, symbol)
        # Multi-root display form: last_computed is often just the Symbol `x`
        # while evaluated_output is "x = [-4/3, -1, 0]".
        if not slots:
            slots = self._slots_from_evaluated_list_string(evaluated, symbol)
        if not slots:
            return [], (
                "Linked formula simplify result has no extractable solutions "
                "(equalities, intervals, or a solution list) for the target variable."
            )

        parent = (
            formula_payload.get("sequence_token")
            or formula_payload.get("indexed_token")
            or "formula"
        )
        virtual = []
        for i, slot in enumerate(slots):
            vp = self._slot_to_virtual_payload(slot, parent, i)
            if vp:
                virtual.append(vp)
        if not virtual:
            return [], "Could not build answer slots from the formula simplify result."
        return virtual, None

    def _entry_matches_key(self, entry, key_payload):
        if not isinstance(entry, dict) or not key_payload:
            return False
        archetype = key_payload.get("token")
        entry_type = entry.get("type")
        if entry_type not in self.STUDENT_ENTRY_TYPES:
            return False
        if archetype not in ("shortAnswer", "arrayMatchingUnordered", "numAnswer"):
            return False

        # Same entry type as the linked key — use that key's grader.
        if entry_type == archetype:
            try:
                validator = self._validator_for_payload(key_payload)
                if not validator.is_valid():
                    return False
                result = validator.grade_answer(entry.get("value"), 1.0)
                earned = float(result.get("earned") or 0)
                mx = float(result.get("max") or 0)
                return mx > 0 and abs(earned - mx) < 1e-9
            except Exception:
                return False

        # Cross-accept formula/string ↔ number when values are mathematically equal
        # (e.g. shortAnswer "-1/2" vs numAnswer entry "-0.5", and vice versa).
        if {entry_type, archetype} == {"shortAnswer", "numAnswer"}:
            return self._short_num_values_equivalent(entry.get("value"), key_payload)

        return False

    def _resolve_key_compare_string(self, key_payload):
        """Author-facing correct value as a string suitable for sympy / float parse."""
        try:
            validator = self._validator_for_payload(key_payload)
            if not validator.is_valid():
                return None
            archetype = key_payload.get("token")
            if archetype == "shortAnswer":
                raw = validator.runtime_values.get("simplified_key")
                if raw is None:
                    raw = validator.runtime_values.get(
                        "resolved_value",
                        validator.evaluate_output(),
                    )
                return self._trim_str(raw)
            if archetype == "numAnswer":
                resolved = validator.runtime_values.get("resolved_value")
                if resolved is None:
                    resolved = validator.evaluate_output()
                return self._trim_str(resolved)
        except Exception:
            return None
        return None

    def _value_to_comparable_expr(self, raw):
        """Parse decimals or fractions (e.g. -0.5, -1/2) into a SymPy expression."""
        trimmed = self._trim_str(raw)
        if not trimmed:
            return None
        expr = self._to_sympy(trimmed)
        if expr is not None and not isinstance(expr, sp.Equality):
            return expr
        try:
            direct = float(trimmed)
            if math.isfinite(direct):
                return sp.Float(direct)
        except (TypeError, ValueError):
            pass
        return None

    def _short_num_values_equivalent(self, student_raw, key_payload):
        """
        True when student text and linked shortAnswer/numAnswer key are the same
        number (exact sympy equivalence, or round-to-3 fallback).
        """
        correct_raw = self._resolve_key_compare_string(key_payload)
        if correct_raw is None:
            return False
        student_expr = self._value_to_comparable_expr(student_raw)
        correct_expr = self._value_to_comparable_expr(correct_raw)
        if student_expr is not None and correct_expr is not None:
            if self._exprs_equivalent(student_expr, correct_expr):
                return True
            # Fallback for messy floats: same 3-decimal rounding as shortAnswer option
            try:
                s_num = float(sp.N(student_expr))
                c_num = float(sp.N(correct_expr))
                if (
                    math.isfinite(s_num)
                    and math.isfinite(c_num)
                    and round(s_num, 3) == round(c_num, 3)
                ):
                    return True
            except Exception:
                pass
        return False

    def _match_counts(self, key_payloads, entries):
        """
        Multiset match: each author key consumes at most one student entry.

        So two keys both equal to -0.5 require two submissions (any mix of
        -0.5 / -1/2). One key of -0.5 with both forms submitted → 1 match + 1 extra wrong.
        """
        remaining = list(entries or [])
        matches = 0
        for key_payload in key_payloads or []:
            found_idx = None
            for i, entry in enumerate(remaining):
                if self._entry_matches_key(entry, key_payload):
                    found_idx = i
                    break
            if found_idx is not None:
                matches += 1
                remaining.pop(found_idx)
        wrongs = len(remaining)
        return matches, wrongs

    def is_valid(self):
        if not super().is_valid():
            return False

        correct_is_dne = self._coerce_bool(
            self.data.get(
                "correct_is_dne",
                self.runtime_values.get("correct_is_dne", False),
            )
        )
        mode = str(
            self.data.get(
                "grading_mode",
                self.runtime_values.get("grading_mode", "all_or_nothing"),
            )
            or "all_or_nothing"
        ).strip()
        if mode not in self.GRADING_MODES:
            mode = "all_or_nothing"

        raw_answers = self.data.get("answers", self.runtime_values.get("answers", []))
        answers = self._normalize_answers_list(raw_answers)

        if correct_is_dne:
            answers = []
            self.runtime_values["key_payloads"] = []
        else:
            if not answers:
                self.errors["answers"] = (
                    "Link at least one shortAnswer, arrayMatchingUnordered, numAnswer, "
                    "or simplify-formula key — or check Correct answer is DNE."
                )
                return False
            key_payloads = []
            for tok in answers:
                payload = self._find_payload(tok)
                if not payload:
                    self.errors["answers"] = f"Linked key {tok} was not found in the workspace."
                    return False
                archetype = payload.get("token")
                if archetype not in self.ALLOWED_KEY_ARCHETYPES:
                    self.errors["answers"] = (
                        f"{tok} must be a shortAnswer, arrayMatchingUnordered, numAnswer, "
                        f"or formula (simplify with target variable) card."
                    )
                    return False

                if archetype == "formula":
                    virtual, err = self._virtual_payloads_from_formula(payload)
                    if err:
                        self.errors["answers"] = f"{tok}: {err}"
                        return False
                    key_payloads.extend(virtual)
                    continue

                # Ensure the linked key itself validates
                try:
                    v = self._validator_for_payload(payload)
                    if not v.is_valid():
                        self.errors["answers"] = (
                            f"Linked key {tok} has validation errors and cannot be used."
                        )
                        return False
                except Exception as exc:
                    self.errors["answers"] = f"Linked key {tok} could not be validated: {exc}"
                    return False
                key_payloads.append(payload)
            self.runtime_values["key_payloads"] = key_payloads

        self.runtime_values["correct_is_dne"] = correct_is_dne
        self.runtime_values["grading_mode"] = mode
        self.runtime_values["answers"] = answers
        self.cleaned_data["correct_is_dne"] = correct_is_dne
        self.cleaned_data["grading_mode"] = mode
        self.cleaned_data["answers"] = answers
        return True

    def _expand_answers_to_key_payloads(self, answers):
        """Resolve linked tokens into grading payloads (formula → virtual slots)."""
        key_payloads = []
        for tok in answers or []:
            payload = self._find_payload(tok)
            if not payload:
                continue
            if payload.get("token") == "formula":
                virtual, err = self._virtual_payloads_from_formula(payload)
                if not err and virtual:
                    key_payloads.extend(virtual)
                continue
            key_payloads.append(payload)
        return key_payloads

    def evaluate_output(self):
        if self.runtime_values.get("correct_is_dne") is None:
            if not self.is_valid():
                raise ValueError("Cannot evaluate answersOrDne: configuration is invalid.")
        self.output_types = ["content"]
        if self.runtime_values.get("correct_is_dne"):
            return "DNE"

        key_payloads = self.runtime_values.get("key_payloads")
        if key_payloads is None:
            key_payloads = self._expand_answers_to_key_payloads(
                self.runtime_values.get("answers") or []
            )

        lines = []
        for payload in key_payloads:
            display = payload.get("_slot_display")
            if display:
                lines.append(str(display))
                continue
            try:
                validator = self._validator_for_payload(payload)
                if not validator.is_valid():
                    tok = payload.get("sequence_token") or payload.get("indexed_token") or "?"
                    lines.append(f"<{tok}>")
                    continue
                out = validator.evaluate_output()
                lines.append(str(out) if out is not None else "")
            except Exception:
                tok = payload.get("sequence_token") or payload.get("indexed_token") or "?"
                lines.append(f"<{tok}>")
        return "\n".join(lines) if lines else ""

    def grade_answer(self, student_input, points_available):
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0

        if self.runtime_values.get("correct_is_dne") is None and self.runtime_values.get("answers") is None:
            # Soft hydrate for grading without prior is_valid
            self.is_valid()

        correct_is_dne = self._coerce_bool(self.runtime_values.get("correct_is_dne", False))
        mode = self.runtime_values.get("grading_mode") or "all_or_nothing"
        answers = self.runtime_values.get("answers") or []
        key_payloads = self.runtime_values.get("key_payloads")
        if key_payloads is None and not correct_is_dne:
            key_payloads = self._expand_answers_to_key_payloads(answers)

        dne = False
        entries = []
        if isinstance(student_input, dict):
            dne = self._coerce_bool(student_input.get("dne", False))
            raw_entries = student_input.get("entries", [])
            if isinstance(raw_entries, list):
                for e in raw_entries:
                    if not isinstance(e, dict):
                        continue
                    et = e.get("type")
                    if et not in self.STUDENT_ENTRY_TYPES:
                        continue
                    entries.append({"type": et, "value": e.get("value")})
        elif isinstance(student_input, str) and student_input.strip().upper() in ("DNE", "NONE", "N/A"):
            dne = True

        if correct_is_dne:
            if dne and not entries:
                return {"earned": pts, "max": pts, "detail": "DNE (correct)"}
            if entries:
                return {"earned": 0.0, "max": pts, "detail": "Incorrect (expected DNE)"}
            if dne:
                return {"earned": pts, "max": pts, "detail": "DNE (correct)"}
            return {"earned": 0.0, "max": pts, "detail": "No student input"}

        # Keys exist
        if dne:
            return {"earned": 0.0, "max": pts, "detail": "Incorrect (DNE when answers exist)"}
        if not entries:
            return {"earned": 0.0, "max": pts, "detail": "No student input"}

        n = len(key_payloads or [])
        if n == 0:
            return {"earned": 0.0, "max": pts, "detail": "No answer key"}

        matches, wrongs = self._match_counts(key_payloads, entries)

        if mode == "all_or_nothing":
            if matches == n and wrongs == 0:
                return {"earned": pts, "max": pts, "detail": "All correct"}
            return {"earned": 0.0, "max": pts, "detail": "Incorrect"}

        sub = pts / n
        earned = matches * sub - 0.5 * sub * wrongs
        if earned < 0:
            earned = 0.0
        return {
            "earned": earned,
            "max": pts,
            "detail": f"{matches}/{n} matched (per answer)",
        }


class MultipleChoiceAnswerEntity(BaseEntity):
    """
    Multiple-choice answer field with dynamic options, optional radio mode,
    and grading methods: all_or_nothing (default), practical, proportional.
    """

    GRADING_METHODS = ("all_or_nothing", "practical", "proportional")
    # Sequence tokens like <randInt1> / &lt;formula2&gt; embedded in choice text.
    _EMBEDDED_TOKEN_RE = re.compile(
        r"(?:&lt;|<)([A-Za-z][A-Za-z0-9_]*\d+)(?:&gt;|>)"
    )

    def _coerce_bool(self, raw, default=False):
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _resolve_content(self, raw):
        """
        Resolve choice text for grading/display.
        Whole-string or mixed prose/LaTeX may include embedded <token> refs.
        """
        if raw is None:
            return ""
        text = str(raw).strip()
        if not text:
            return ""

        def _replace_token(match):
            seq = match.group(1).strip()
            return str(self.resolve_token_dependency(f"<{seq}>")).strip()

        try:
            if self._EMBEDDED_TOKEN_RE.search(text):
                return self._EMBEDDED_TOKEN_RE.sub(_replace_token, text)
        except Exception as exc:
            raise ValidationError(str(getattr(exc, "message", exc)))
        return text

    def _normalize_options(self, raw_options):
        if isinstance(raw_options, str):
            try:
                raw_options = json.loads(raw_options)
            except Exception:
                raw_options = []
        if not isinstance(raw_options, list):
            return []

        normalized = []
        for idx, item in enumerate(raw_options):
            if not isinstance(item, dict):
                continue
            opt_id = str(item.get("id") or f"opt_{idx + 1}").strip() or f"opt_{idx + 1}"
            content_raw = item.get("content", "")
            is_correct = self._coerce_bool(item.get("is_correct"), False)
            try:
                content_resolved = self._resolve_content(content_raw)
            except ValidationError as e:
                self.errors["options"] = f"Option {opt_id}: {e.message}"
                content_resolved = ""
            normalized.append({
                "id": opt_id,
                "content": content_raw if isinstance(content_raw, str) else str(content_raw or ""),
                "content_resolved": content_resolved,
                "is_correct": is_correct,
            })
        return normalized

    def is_valid(self):
        # Skip strict missing-key errors for nested options handled below
        if not isinstance(self.data, dict):
            self.errors["inputs"] = "The provided inputs field must be a structured key-value map."
            return False

        # Validate scalar fields via base where present; options handled manually
        scalar_data = {
            k: v for k, v in self.data.items()
            if k != "options" and not str(k).startswith("option_")
        }
        # Temporarily validate scalars with a shallow blueprint pass
        original_data = self.data
        self.data = scalar_data
        # Ensure defaults applied for missing scalars
        blueprint_inputs = self.pattern_blueprint.get("inputs", {}) or {}
        for key in ("randomize_order", "force_radio", "grading_method"):
            if key not in self.data and key in blueprint_inputs and "default" in blueprint_inputs[key]:
                self.data[key] = blueprint_inputs[key]["default"]
        base_ok = super().is_valid()
        self.data = original_data
        if not base_ok and self.errors:
            # Ignore errors about missing options from base if any leaked
            self.errors.pop("options", None)

        options = self._normalize_options(original_data.get("options", []))
        if "options" in self.errors:
            return False

        if len(options) < 2:
            self.errors["options"] = "At least 2 choices are required."
            return False

        for opt in options:
            content_raw = str(opt.get("content") or "").strip()
            content_resolved = str(opt.get("content_resolved") or "").strip()
            if not content_resolved and not content_raw:
                self.errors["options"] = "Each choice must have text or a linked Dynamic Variable."
                return False
            # Whole-string link that failed to resolve
            if (
                re.match(r"^<[^<>]+>$", content_raw)
                and not content_resolved
            ):
                if "options" not in self.errors:
                    self.errors["options"] = f"Could not resolve linked option {opt.get('id')}."
                return False

        num_correct = sum(1 for o in options if o.get("is_correct"))
        # Zero correct is allowed: students must leave all choices unchecked for full credit.
        # Radio mode is only valid with exactly one correct option (cannot uncheck a radio).

        method = str(
            self.runtime_values.get(
                "grading_method",
                original_data.get("grading_method", "all_or_nothing"),
            )
        ).strip()
        if method not in self.GRADING_METHODS:
            method = "all_or_nothing"

        randomize = self._coerce_bool(
            self.runtime_values.get("randomize_order", original_data.get("randomize_order", True)),
            True,
        )
        force_radio = self._coerce_bool(
            self.runtime_values.get("force_radio", original_data.get("force_radio", True)),
            True,
        )
        if num_correct != 1:
            force_radio = False

        self.runtime_values["options"] = options
        self.runtime_values["grading_method"] = method
        self.runtime_values["randomize_order"] = randomize
        self.runtime_values["force_radio"] = force_radio
        self.cleaned_data["options"] = original_data.get("options", options)
        self.cleaned_data["grading_method"] = method
        self.cleaned_data["randomize_order"] = randomize
        self.cleaned_data["force_radio"] = force_radio
        return len(self.errors) == 0

    def evaluate_output(self):
        options = self.runtime_values.get("options")
        if options is None:
            if not self.is_valid():
                raise ValueError("Cannot evaluate multipleChoiceAnswer: configuration is invalid.")
            options = self.runtime_values.get("options") or []

        self.output_types = ["content"]
        lines = []
        for opt in options:
            if not opt.get("is_correct"):
                continue
            text = str(opt.get("content_resolved") or opt.get("content") or "").strip()
            if text:
                lines.append(text)
        return "\n".join(lines) if lines else ""

    def grade_answer(self, student_input, points_available):
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0

        options = self.runtime_values.get("options")
        if options is None:
            options = self._normalize_options(self.data.get("options", []))

        correct_ids = {str(o["id"]).strip() for o in options if o.get("is_correct")}
        incorrect_ids = {str(o["id"]).strip() for o in options if not o.get("is_correct")}
        all_ids = {str(o["id"]).strip() for o in options}

        selected = []
        if isinstance(student_input, dict):
            raw_sel = student_input.get("selected", student_input.get("value", []))
            if isinstance(raw_sel, str):
                selected = [raw_sel] if raw_sel.strip() else []
            elif isinstance(raw_sel, (list, tuple)):
                selected = [str(x) for x in raw_sel if x is not None and str(x).strip() != ""]
        elif isinstance(student_input, (list, tuple)):
            selected = [str(x) for x in student_input if x is not None and str(x).strip() != ""]
        elif student_input is not None and str(student_input).strip() != "":
            selected = [str(student_input)]

        # Prefer option ids; also accept content / resolved display text as a fallback
        # (broken/older frontends occasionally submitted the visible label text).
        content_to_id = {}
        for o in options:
            oid = str(o["id"]).strip()
            for key in (o.get("content"), o.get("content_resolved")):
                text = str(key or "").strip()
                if text and text not in content_to_id:
                    content_to_id[text] = oid

        selected_set = set()
        for s in selected:
            token = str(s).strip()
            if not token:
                continue
            if token in all_ids:
                selected_set.add(token)
            elif token in content_to_id:
                selected_set.add(content_to_id[token])

        # Zero keyed-correct options: full credit only when nothing is selected.
        if not correct_ids:
            if not selected_set:
                return {
                    "earned": pts,
                    "max": pts,
                    "detail": "Correct: no options selected",
                }
            return {
                "earned": 0.0,
                "max": pts,
                "detail": "Incorrect: at least one option was selected (none are correct)",
            }

        if not selected and not selected_set:
            return {"earned": 0.0, "max": pts, "detail": "No student input"}
        if not selected_set:
            return {"earned": 0.0, "max": pts, "detail": "Selected choices did not match any option"}

        method = str(
            self.runtime_values.get(
                "grading_method",
                self.data.get("grading_method", "all_or_nothing"),
            )
        ).strip()
        if method not in self.GRADING_METHODS:
            method = "all_or_nothing"

        correct_selected = len(selected_set & correct_ids)
        wrong_selected = len(selected_set & incorrect_ids)
        num_correct = len(correct_ids)
        num_incorrect = len(incorrect_ids)

        if method == "all_or_nothing":
            if selected_set == correct_ids:
                return {"earned": pts, "max": pts, "detail": "All or nothing: correct"}
            return {"earned": 0.0, "max": pts, "detail": "All or nothing: incorrect"}

        if method == "practical":
            points_per_correct = pts / num_correct
            penalty_per_wrong = points_per_correct / 2.0
            earned = correct_selected * points_per_correct - wrong_selected * penalty_per_wrong
            if earned < 0:
                earned = 0.0
            return {
                "earned": earned,
                "max": pts,
                "detail": f"Practical: {correct_selected}/{num_correct} correct, {wrong_selected} wrong",
            }

        # proportional

        correct_term = correct_selected / num_correct
        if num_incorrect <= 0:
            wrong_term = 0.0
        else:
            wrong_term = wrong_selected / num_incorrect
        earned = pts * (correct_term - wrong_term)
        if earned < 0:
            earned = 0.0
        return {
            "earned": earned,
            "max": pts,
            "detail": f"Proportional: {correct_selected}/{num_correct} correct, {wrong_selected}/{num_incorrect or 0} wrong",
        }


class SlopeFieldGraphEntity(BaseEntity):
    """
    Answer-field slope field: validate dy/dx = f(x,y), axis lattice, and selected points.
    evaluate_output returns a JSON manifest with precomputed slopes for SVG rendering.
    """
    MAX_LATTICE_DIM = 40

    def is_valid(self):
        if not super().is_valid():
            return False

        raw_equation = self.data.get("equation") or self.runtime_values.get("equation") or ""
        display_eq, rhs = self._normalize_equation(raw_equation)
        if not rhs:
            self.errors["equation"] = "A slope field equation is required (e.g. dy/dx = x + y)."
            return False

        try:
            local_dict = {
                "x": sp.Symbol("x"),
                "y": sp.Symbol("y"),
                "pi": sp.pi,
                "E": sp.E,
                "exp": sp.exp,
                "sin": sp.sin,
                "cos": sp.cos,
                "tan": sp.tan,
                "log": sp.log,
                "sqrt": sp.sqrt,
            }
            parsed = self.parse_math_expression(rhs, local_dict=local_dict, evaluate=False)
            free = {str(s) for s in getattr(parsed, "free_symbols", set())}
            allowed = {"x", "y"}
            extras = free - allowed
            if extras:
                self.errors["equation"] = (
                    f"Slope equation may only use variables x and y "
                    f"(found: {', '.join(sorted(extras))})."
                )
                return False
        except Exception as exc:
            self.errors["equation"] = f"Could not parse slope equation: {exc}"
            return False

        x_range = self._parse_axis_range("x-axis range", self.data.get("x-axis range"), [-5.0, 5.0, 1.0])
        y_range = self._parse_axis_range("y-axis range", self.data.get("y-axis range"), [-5.0, 5.0, 1.0])
        if self.errors:
            return False

        x_count = self._lattice_count(x_range)
        y_count = self._lattice_count(y_range)
        if x_count > self.MAX_LATTICE_DIM or y_count > self.MAX_LATTICE_DIM:
            self.errors["x-axis range" if x_count > self.MAX_LATTICE_DIM else "y-axis range"] = (
                f"Lattice is too dense (max {self.MAX_LATTICE_DIM} points per axis). "
                f"Increase the step or shrink the range."
            )
            return False

        lattice_keys = set()
        for xv in self._iter_axis(x_range):
            for yv in self._iter_axis(y_range):
                lattice_keys.add(self._point_key(xv, yv))

        # Build slopes early so we can prune non-selectable teacher marks
        lattice_entries = self._build_lattice_entries(parsed, x_range, y_range)
        selectable_keys = {
            self._point_key(e["x"], e["y"])
            for e in lattice_entries
            if e.get("selectable")
        }

        raw_selected = self.data.get("selected_points", [])
        if isinstance(raw_selected, str):
            try:
                raw_selected = json.loads(raw_selected) if raw_selected.strip() else []
            except Exception:
                raw_selected = []
        if not isinstance(raw_selected, list):
            raw_selected = []

        cleaned_selected = []
        seen = set()
        for item in raw_selected:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            try:
                px = float(item[0])
                py = float(item[1])
            except (TypeError, ValueError):
                continue
            key = self._point_key(px, py)
            if key in lattice_keys and key in selectable_keys and key not in seen:
                seen.add(key)
                cleaned_selected.append([round(px, 10), round(py, 10)])

        self.runtime_values["equation_display"] = display_eq
        self.runtime_values["equation_rhs"] = rhs
        self.runtime_values["parsed_slope_expr"] = parsed
        self.runtime_values["resolved_x-axis range"] = x_range
        self.runtime_values["resolved_y-axis range"] = y_range
        self.runtime_values["selected_points"] = cleaned_selected
        self.runtime_values["lattice_entries"] = lattice_entries

        show_instructions = self._coerce_bool(self.data.get("show_instructions", False))
        self.runtime_values["show_instructions"] = show_instructions
        self.cleaned_data["show_instructions"] = show_instructions

        self.cleaned_data["equation"] = display_eq
        self.cleaned_data["x-axis range"] = x_range
        self.cleaned_data["y-axis range"] = y_range
        self.cleaned_data["selected_points"] = cleaned_selected
        # Flat keys for frontend rehydration
        self.cleaned_data["x_min"] = x_range[0]
        self.cleaned_data["x_max"] = x_range[1]
        self.cleaned_data["x_step"] = x_range[2]
        self.cleaned_data["y_min"] = y_range[0]
        self.cleaned_data["y_max"] = y_range[1]
        self.cleaned_data["y_step"] = y_range[2]

        return True

    def _coerce_bool(self, raw):
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _normalize_equation(self, raw):
        s = str(raw or "").strip()
        if not s:
            return "", ""
        display = s
        lower = s.lower().replace(" ", "")
        rhs = s
        # Strip common LHS forms: dy/dx = ..., y' = ..., dydx = ...
        m = re.match(
            r"^\s*(?:d\s*y\s*/\s*d\s*x|dy\s*/\s*dx|y\s*'|dydx)\s*=\s*(.+)$",
            s,
            flags=re.IGNORECASE,
        )
        if m:
            rhs = m.group(1).strip()
            display = f"dy/dx = {rhs}"
        elif "=" in s and not lower.startswith("dy/dx"):
            # Generic "lhs = rhs" — keep RHS only for evaluation
            parts = s.split("=", 1)
            if len(parts) == 2 and parts[1].strip():
                rhs = parts[1].strip()
                display = f"dy/dx = {rhs}"
        else:
            display = f"dy/dx = {rhs}"
        return display, rhs

    def _parse_axis_range(self, key, raw, default_triple):
        if not raw or not isinstance(raw, list) or len(raw) != 3:
            # Fall back to individual flat keys if present
            prefix = "x_" if key.startswith("x") else "y_"
            flat = [
                self.data.get(f"{prefix}min"),
                self.data.get(f"{prefix}max"),
                self.data.get(f"{prefix}step"),
            ]
            if all(v not in (None, "", "null") for v in flat):
                raw = flat
            else:
                raw = default_triple
        try:
            min_val = float(raw[0])
            max_val = float(raw[1])
            step_val = float(raw[2])
        except (TypeError, ValueError):
            self.errors[key] = "Axis bounds must be numeric [min, max, step]."
            return list(default_triple)

        if min_val >= max_val:
            self.errors[key] = "The coordinate minimum cannot be greater than or equal to its maximum."
        if step_val <= 0:
            self.errors[key] = "The step interval must be greater than zero."
        return [min_val, max_val, step_val]

    def _lattice_count(self, axis_range):
        min_val, max_val, step_val = axis_range
        if step_val <= 0:
            return 0
        count = 0
        val = min_val
        # Guard against floating drift
        while val <= max_val + step_val * 1e-9:
            count += 1
            val = round(val + step_val, 10)
            if count > self.MAX_LATTICE_DIM + 5:
                break
        return count

    def _iter_axis(self, axis_range):
        min_val, max_val, step_val = axis_range
        val = min_val
        n = 0
        while val <= max_val + step_val * 1e-9 and n <= self.MAX_LATTICE_DIM:
            yield round(val, 10)
            val = round(val + step_val, 10)
            n += 1

    def _point_key(self, x, y):
        return (round(float(x), 8), round(float(y), 8))

    def _slopes_match(self, m1, m2, rel_tol=1e-8, abs_tol=1e-9):
        if m1 is None or m2 is None:
            return False
        try:
            a = float(m1)
            b = float(m2)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(a) or not math.isfinite(b):
            return False
        return abs(a - b) <= max(abs_tol, rel_tol * max(1.0, abs(a), abs(b)))

    def _undirected_angles_match(self, angle_a, angle_b, eps=1e-6):
        """Compare undirected line angles (mod π)."""
        try:
            a = float(angle_a)
            b = float(angle_b)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(a) or not math.isfinite(b):
            return False

        def fold(theta):
            t = math.fmod(theta, math.pi)
            if t < 0:
                t += math.pi
            return t

        d = abs(fold(a) - fold(b))
        return min(d, math.pi - d) <= eps

    def _mark_lattice_selectable(self, lattice):
        """Point P is selectable if undefined, or some other lattice Q shares P's field slope."""
        for entry in lattice:
            if not entry.get("finite", True) or entry.get("slope") is None:
                entry["selectable"] = True
                continue
            m = entry["slope"]
            try:
                m = float(m)
            except (TypeError, ValueError):
                entry["selectable"] = True
                continue
            if not math.isfinite(m):
                entry["selectable"] = True
                continue

            px, py = entry["x"], entry["y"]
            selectable = False
            for other in lattice:
                if other is entry:
                    continue
                dx = other["x"] - px
                dy = other["y"] - py
                if abs(dx) < 1e-12:
                    # Vertical neighbor — only matches an infinite field slope
                    continue
                if self._slopes_match(dy / dx, m):
                    selectable = True
                    break
            entry["selectable"] = selectable
        return lattice

    def _build_lattice_entries(self, expr, x_range, y_range):
        x_sym = sp.Symbol("x")
        y_sym = sp.Symbol("y")
        lattice = []
        for xv in self._iter_axis(x_range):
            for yv in self._iter_axis(y_range):
                entry = {"x": xv, "y": yv, "slope": 0.0, "finite": True, "selectable": False}
                try:
                    val = expr.subs({x_sym: xv, y_sym: yv})
                    val = sp.N(val)
                    if val.has(sp.zoo) or val.has(sp.oo) or val.has(-sp.oo) or val.has(sp.nan):
                        entry["finite"] = False
                        entry["slope"] = None
                    else:
                        entry["slope"] = float(val)
                except Exception:
                    entry["finite"] = False
                    entry["slope"] = None
                lattice.append(entry)
        return self._mark_lattice_selectable(lattice)

    def evaluate_output(self):
        rhs = self.runtime_values.get("equation_rhs", "0")
        display = self.runtime_values.get("equation_display", f"dy/dx = {rhs}")
        x_range = self.runtime_values.get("resolved_x-axis range", [-5.0, 5.0, 1.0])
        y_range = self.runtime_values.get("resolved_y-axis range", [-5.0, 5.0, 1.0])
        selected = self.runtime_values.get("selected_points", [])
        expr = self.runtime_values.get("parsed_slope_expr")

        if expr is None:
            local_dict = {"x": sp.Symbol("x"), "y": sp.Symbol("y")}
            expr = self.parse_math_expression(rhs, local_dict=local_dict, evaluate=False)

        lattice = self.runtime_values.get("lattice_entries")
        if not lattice:
            lattice = self._build_lattice_entries(expr, x_range, y_range)

        manifest = {
            "archetype": "slopeFieldGraph",
            "equation": rhs,
            "equation_display": display,
            "bounds": {
                "x_range": {"min": x_range[0], "max": x_range[1], "step": x_range[2]},
                "y_range": {"min": y_range[0], "max": y_range[1], "step": y_range[2]},
            },
            "selected_points": selected,
            "lattice": lattice,
            "show_instructions": bool(self.runtime_values.get("show_instructions", False)),
        }
        return json.dumps(manifest)

    def grade_answer(self, student_input, points_available):
        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0

        selected = self.runtime_values.get("selected_points") or []
        max_total = pts * len(selected)

        lattice = self.runtime_values.get("lattice_entries")
        if not lattice:
            expr = self.runtime_values.get("parsed_slope_expr")
            x_range = self.runtime_values.get("resolved_x-axis range", [-5.0, 5.0, 1.0])
            y_range = self.runtime_values.get("resolved_y-axis range", [-5.0, 5.0, 1.0])
            if expr is not None:
                lattice = self._build_lattice_entries(expr, x_range, y_range)
            else:
                lattice = []

        lattice_by_key = {
            self._point_key(e["x"], e["y"]): e for e in lattice
        }

        marks = []
        if isinstance(student_input, dict):
            raw_marks = student_input.get("marks")
            if isinstance(raw_marks, list):
                marks = raw_marks
        elif isinstance(student_input, list):
            marks = student_input

        marks_by_key = {}
        for mark in marks:
            if not isinstance(mark, dict):
                continue
            try:
                mx = float(mark.get("x"))
                my = float(mark.get("y"))
            except (TypeError, ValueError):
                continue
            marks_by_key[self._point_key(mx, my)] = mark

        if not selected:
            empty = not marks
            return {
                "earned": 0.0,
                "max": 0.0,
                "detail": "No coordinates selected for grading" if empty else "0/0 coordinates correct",
            }

        correct = 0
        for pair in selected:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            key = self._point_key(pair[0], pair[1])
            entry = lattice_by_key.get(key)
            mark = marks_by_key.get(key)
            if mark is None:
                continue

            kind = str(mark.get("kind") or "").strip().lower()
            is_undefined = (
                entry is None
                or not entry.get("finite", True)
                or entry.get("slope") is None
            )
            if is_undefined:
                if kind == "undefined":
                    correct += 1
                continue

            if kind != "slope":
                continue
            try:
                angle = float(mark.get("angle"))
            except (TypeError, ValueError):
                continue
            field_angle = math.atan(float(entry["slope"]))
            if self._undirected_angles_match(angle, field_angle):
                correct += 1

        earned = pts * correct
        return {
            "earned": float(earned),
            "max": float(max_total),
            "detail": f"{correct}/{len(selected)} coordinates correct",
        }


class GraphBetweenPointsEntity(BaseEntity):
    """
    Answer field: piecewise graph from author segments (line / parabola / cubic)
    with optional vertices and optional student-drawn hidden segments.
    """

    SEGMENT_TYPES = (
        "concave_down_parabola",
        "concave_up_parabola",
        "line",
        "cubic_parabola",
    )
    START_DIVIDERS = ("<", "<=", "none", "arrow")
    END_DIVIDERS = (">", ">=", "none", "arrow")

    def _coerce_bool(self, raw, default=False):
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _parse_axis_range(self, field_name, raw, default):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw.strip() else None
            except Exception:
                raw = None
        if not isinstance(raw, (list, tuple)) or len(raw) < 3:
            # Flat keys fallback
            prefix = "x_" if field_name.startswith("x") else "y_"
            try:
                mn = self.data.get(f"{prefix}min")
                mx = self.data.get(f"{prefix}max")
                st = self.data.get(f"{prefix}step")
                if mn is not None and mx is not None and st is not None:
                    raw = [mn, mx, st]
            except Exception:
                raw = None
        if not isinstance(raw, (list, tuple)) or len(raw) < 3:
            raw = default
        try:
            mn = float(raw[0])
            mx = float(raw[1])
            st = float(raw[2])
        except (TypeError, ValueError):
            self.errors[field_name] = "Axis range must be three numbers: min, max, step."
            return list(default)
        if not (math.isfinite(mn) and math.isfinite(mx) and math.isfinite(st)):
            self.errors[field_name] = "Axis range values must be finite."
            return list(default)
        if mn >= mx:
            self.errors[field_name] = "Axis min must be less than max."
            return list(default)
        if st <= 0:
            self.errors[field_name] = "Axis step must be positive."
            return list(default)
        return [mn, mx, st]

    def _parse_point(self, raw):
        if isinstance(raw, str):
            s = raw.strip()
            if s.startswith("["):
                try:
                    raw = json.loads(s)
                except Exception:
                    parts = [p.strip() for p in s.strip("[]()").split(",")]
                    raw = parts
            else:
                parts = [p.strip() for p in s.split(",")]
                raw = parts
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            return None
        try:
            return [float(raw[0]), float(raw[1])]
        except (TypeError, ValueError):
            return None

    def _parse_json_list(self, raw, default=None):
        if default is None:
            default = []
        if raw is None:
            return list(default)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw) if raw.strip() else default
            except Exception:
                return list(default)
        if not isinstance(raw, list):
            return list(default)
        return raw

    def is_valid(self):
        # Soft base validation — blueprint keys are flexible for nested arrays
        if not isinstance(self.data, dict):
            self.errors["inputs"] = "Inputs must be a structured map."
            return False

        from assessment_tool.graph_between_points_geometry import (
            build_segment_samples,
            point_in_bounds,
            segment_x_covers,
        )

        show_grid = self._coerce_bool(self.data.get("show_grid", True), True)
        let_student_draw = self._coerce_bool(self.data.get("let_student_draw", False), False)
        x_range = self._parse_axis_range("x-axis range", self.data.get("x-axis range"), [-5.0, 5.0, 1.0])
        y_range = self._parse_axis_range("y-axis range", self.data.get("y-axis range"), [-5.0, 5.0, 1.0])
        if self.errors:
            return False

        x_min, x_max = x_range[0], x_range[1]
        y_min, y_max = y_range[0], y_range[1]

        raw_segments = self._parse_json_list(self.data.get("segments"), [])
        segments = []
        for idx, item in enumerate(raw_segments):
            if not isinstance(item, dict):
                continue
            sid = str(item.get("id") or f"seg_{idx + 1}").strip() or f"seg_{idx + 1}"
            start = self._parse_point(item.get("start"))
            end = self._parse_point(item.get("end"))
            if not start or not end:
                self.errors["segments"] = f"Segment {sid} needs two valid coordinates."
                return False
            if not point_in_bounds(start[0], start[1], x_min, x_max, y_min, y_max):
                self.errors["segments"] = (
                    f"Segment {sid} start is outside allowed bounds "
                    f"(y must be strictly inside axis; x within range)."
                )
                return False
            if not point_in_bounds(end[0], end[1], x_min, x_max, y_min, y_max):
                self.errors["segments"] = (
                    f"Segment {sid} end is outside allowed bounds "
                    f"(y must be strictly inside axis; x within range)."
                )
                return False
            stype = str(item.get("type") or "").strip()
            if stype not in self.SEGMENT_TYPES:
                self.errors["segments"] = f"Segment {sid} has an invalid type."
                return False
            sd = str(item.get("start_divider") or "none").strip()
            ed = str(item.get("end_divider") or "none").strip()
            if sd not in self.START_DIVIDERS:
                sd = "none"
            if ed not in self.END_DIVIDERS:
                ed = "none"
            student_draw = self._coerce_bool(item.get("student_draw"), False) and let_student_draw
            segments.append({
                "id": sid,
                "start": start,
                "end": end,
                "type": stype,
                "start_divider": sd,
                "end_divider": ed,
                "student_draw": student_draw,
            })

        if len(segments) < 1:
            self.errors["segments"] = "Add at least one graph segment."
            return False

        seg_by_id = {s["id"]: s for s in segments}
        raw_vertices = self._parse_json_list(self.data.get("vertices"), [])
        vertices = []
        for idx, item in enumerate(raw_vertices):
            if not isinstance(item, dict):
                continue
            vid = str(item.get("id") or f"vtx_{idx + 1}").strip() or f"vtx_{idx + 1}"
            preferred = str(item.get("segment_id") or "").strip()
            if not preferred or preferred not in seg_by_id:
                continue
            target = seg_by_id[preferred]
            if target["type"] == "line":
                continue
            # Caps
            already = [v for v in vertices if v["segment_id"] == preferred]
            if target["type"] in ("concave_down_parabola", "concave_up_parabola") and len(already) >= 1:
                continue
            if target["type"] == "cubic_parabola" and len(already) >= 2:
                continue
            # Point is auto-calculated; ignore author-provided coordinates.
            vertices.append({"id": vid, "point": [], "segment_id": preferred})

        # Segments with vertices cannot be student-drawn
        verts_by_seg = {}
        for v in vertices:
            verts_by_seg.setdefault(v["segment_id"], []).append(v)
        for s in segments:
            if verts_by_seg.get(s["id"]):
                s["student_draw"] = False

        raw_seeds = self.data.get("curve_seeds") or {}
        if isinstance(raw_seeds, str):
            try:
                raw_seeds = json.loads(raw_seeds) if raw_seeds.strip() else {}
            except Exception:
                raw_seeds = {}
        if not isinstance(raw_seeds, dict):
            raw_seeds = {}
        curve_seeds = {}
        for s in segments:
            sid = s["id"]
            try:
                curve_seeds[sid] = int(raw_seeds.get(sid, hash(sid) & 0xFFFFFFFF))
            except (TypeError, ValueError):
                curve_seeds[sid] = hash(sid) & 0xFFFFFFFF

        # Build samples (validates geometry / synthesis)
        built = []
        for s in segments:
            try:
                built.append(
                    build_segment_samples(
                        s, vertices, x_range, y_range, curve_seeds[s["id"]]
                    )
                )
            except ValueError as exc:
                self.errors["segments"] = f"{s['id']}: {exc}"
                return False

        # Fill auto-calculated vertex coordinates from resolved peaks/extrema
        pending_by_seg = {}
        for v in vertices:
            pending_by_seg.setdefault(v["segment_id"], []).append(v)
        for seg in built:
            sid = seg.get("id")
            resolved = seg.get("resolved_vertices") or []
            rows = pending_by_seg.get(sid) or []
            for i, v in enumerate(rows):
                if i < len(resolved):
                    v["point"] = [float(resolved[i][0]), float(resolved[i][1])]
        # Drop any vertex that still has no point (failed resolve)
        vertices = [v for v in vertices if isinstance(v.get("point"), list) and len(v["point"]) >= 2]

        self.runtime_values["show_grid"] = show_grid
        self.runtime_values["let_student_draw"] = let_student_draw
        self.runtime_values["resolved_x-axis range"] = x_range
        self.runtime_values["resolved_y-axis range"] = y_range
        self.runtime_values["segments"] = segments
        self.runtime_values["vertices"] = vertices
        self.runtime_values["curve_seeds"] = curve_seeds
        self.runtime_values["built_segments"] = built

        self.cleaned_data["show_grid"] = show_grid
        self.cleaned_data["let_student_draw"] = let_student_draw
        self.cleaned_data["x-axis range"] = x_range
        self.cleaned_data["y-axis range"] = y_range
        self.cleaned_data["x_min"] = x_range[0]
        self.cleaned_data["x_max"] = x_range[1]
        self.cleaned_data["x_step"] = x_range[2]
        self.cleaned_data["y_min"] = y_range[0]
        self.cleaned_data["y_max"] = y_range[1]
        self.cleaned_data["y_step"] = y_range[2]
        self.cleaned_data["segments"] = segments
        self.cleaned_data["vertices"] = vertices
        self.cleaned_data["curve_seeds"] = curve_seeds
        return True

    def evaluate_output(self):
        if self.runtime_values.get("built_segments") is None:
            if not self.is_valid():
                raise ValueError("Cannot evaluate graphBetweenPoints: configuration is invalid.")
        x_range = self.runtime_values["resolved_x-axis range"]
        y_range = self.runtime_values["resolved_y-axis range"]
        built = self.runtime_values["built_segments"]
        let_draw = self.runtime_values.get("let_student_draw", False)

        author_visible = []
        student_targets = []
        for seg in built:
            entry = {
                "id": seg["id"],
                "type": seg["type"],
                "start": seg["start"],
                "end": seg["end"],
                "start_divider": seg["start_divider"],
                "end_divider": seg["end_divider"],
                "student_draw": bool(seg.get("student_draw")),
                "samples": seg.get("samples") or [],
                "markers": seg.get("markers") or {},
                "resolved_vertices": seg.get("resolved_vertices") or [],
                "equation": seg.get("equation") or "",
            }
            if let_draw and seg.get("student_draw"):
                student_targets.append({
                    "id": seg["id"],
                    "type": seg["type"],
                    "start": seg["start"],
                    "end": seg["end"],
                    "start_divider": seg["start_divider"],
                    "end_divider": seg["end_divider"],
                })
            else:
                author_visible.append(entry)

        manifest = {
            "archetype": "graphBetweenPoints",
            "bounds": {
                "x_range": {"min": x_range[0], "max": x_range[1], "step": x_range[2]},
                "y_range": {"min": y_range[0], "max": y_range[1], "step": y_range[2]},
            },
            "visualization": {
                "show_grid_overlay": bool(self.runtime_values.get("show_grid", True)),
            },
            "let_student_draw": let_draw,
            "segments": built,
            "author_visible": author_visible,
            "student_targets": student_targets,
            "vertices": self.runtime_values.get("vertices") or [],
            "curve_seeds": self.runtime_values.get("curve_seeds") or {},
        }
        self.output_types = ["content"]
        return json.dumps(manifest)

    def grade_answer(self, student_input, points_available):
        from assessment_tool.graph_between_points_geometry import segments_match

        try:
            pts = float(points_available) if points_available is not None else 0.0
        except (TypeError, ValueError):
            pts = 0.0
        if not math.isfinite(pts) or pts < 0:
            pts = 0.0

        if self.runtime_values.get("segments") is None:
            self.is_valid()

        targets = [
            s for s in (self.runtime_values.get("segments") or [])
            if s.get("student_draw")
        ]
        n = len(targets)
        if n == 0:
            return {"earned": 0.0, "max": 0.0, "detail": "No student-drawn segments"}

        student_segs = []
        if isinstance(student_input, dict):
            raw = student_input.get("segments", [])
            if isinstance(raw, list):
                student_segs = [s for s in raw if isinstance(s, dict)]
        elif isinstance(student_input, list):
            student_segs = [s for s in student_input if isinstance(s, dict)]

        remaining = list(student_segs)
        matches = 0
        for key in targets:
            found = None
            for i, cand in enumerate(remaining):
                if segments_match(key, cand):
                    found = i
                    break
            if found is not None:
                matches += 1
                remaining.pop(found)

        sub = pts / n
        earned = matches * sub
        return {
            "earned": float(earned),
            "max": float(pts),
            "detail": f"{matches}/{n} segments matched",
        }


def get_entity_validator(token_string, data_payload, pattern_blueprint, all_entities_payload=None):
    """
    Factory helper utility that returns the matching validation engine sub-class
    configured to handle target structural verification logic mappings.
    """
    # Map token names to dedicated sub-classes
    validator_mapping = {
        "randInt": RandomIntegerEntity,
        "rand": RandomDoubleEntity,
        "primeFactors": PrimeFactorsEntity,
        "formula": FormulaEntity,
        "graph": GraphEntity,
        "matrix": MatrixEntity,
        "matrixResultByIndex": MatrixResultByIndexEntity,
        "numAnswer": NumAnswerEntity,
        "shortAnswer": ShortAnswerEntity,
        "longAnswer": LongAnswerEntity,
        "canvas": CanvasEntity,
        "arrayMatchingUnordered": ArrayMatchingUnorderedEntity,
        "answersOrDne": AnswersOrDneEntity,
        "multipleChoiceAnswer": MultipleChoiceAnswerEntity,
        "matrixAnswer": MatrixAnswerEntity,
        "slopeFieldGraph": SlopeFieldGraphEntity,
        "graphBetweenPoints": GraphBetweenPointsEntity,
    }
    
    # Fallback to base configuration validator if a custom token model isn't written yet
    validator_class = validator_mapping.get(token_string, BaseEntity)
    
    # 🎯 Pass down the global sibling token list to the instantiator context
    return validator_class(data_payload, pattern_blueprint, all_entities_payload=all_entities_payload)

def get_blueprint_for_token(token_string):
    """
    Helper to fetch a blueprint dictionary directly by its 
    EntityType name during background recursive token resolution.
    """
    try:
        EntityType = apps.get_model('assessment_tool', 'EntityType')
        record = EntityType.objects.get(name=token_string)
        pattern = record.format_pattern
        return json.loads(pattern) if isinstance(pattern, str) else pattern
    except Exception:
        return {}


def evaluate_and_format_entity(archetype_name, sequence_token, clean_inputs, pattern_blueprint, all_entities_payload):
    """
    Unified evaluation runner that runs an entity validator, tracks simulated results,
    and returns a standardized dictionary matching the frontend cache schema.
    """
    validator = get_entity_validator(
        token_string=archetype_name,
        data_payload=clean_inputs,
        pattern_blueprint=pattern_blueprint,
        all_entities_payload=all_entities_payload
    )
    
    is_valid = validator.is_valid()
    errors = getattr(validator, 'errors', {}) if not is_valid else {}
    
    evaluated_output = "???"
    latex_output = "???"
    extracted_vars = []

    # Shared variable tracking storage
    sym_set = set()

    if is_valid:
        try:
            evaluated_res = validator.evaluate_output()
            evaluated_output = str(evaluated_res)
            
            # 🎯 Component Type Specific Pre-Formatting Overrides
            if archetype_name == 'graph':
                latex_output = "[Graph Component]"
            elif archetype_name == 'slopeFieldGraph':
                latex_output = "[Slope Field Graph]"
            elif archetype_name == 'graphBetweenPoints':
                latex_output = "[Graph Between Points]"
            elif archetype_name == 'matrix' or archetype_name == 'matrixResultByIndex':
                # Matrix / cell extract: format SymPy results as LaTeX
                if hasattr(validator, 'last_computed_sympy_result'):
                    result_obj = validator.last_computed_sympy_result
                    latex_output = sp.latex(result_obj)
                    
                    # Scrape free variables from every calculation cell inside the Matrix frame shape
                    if hasattr(result_obj, 'free_symbols'):
                        sym_set = result_obj.free_symbols
                else:
                    latex_output = evaluated_output
            elif archetype_name == 'matrixAnswer':
                # evaluated_output is JSON; latex box shows the human summary
                try:
                    parsed = json.loads(evaluated_output) if isinstance(evaluated_output, str) else evaluated_output
                    if isinstance(parsed, dict) and parsed.get("summary"):
                        latex_output = str(parsed["summary"])
                    else:
                        latex_output = evaluated_output
                except Exception:
                    latex_output = evaluated_output
            else:
                latex_output = evaluated_output
            
            # Dynamically update the shared context ledger for downstream dependency cascading
            target_entry = next((x for x in all_entities_payload if x.get('sequence_token') == sequence_token), None)
            if target_entry:
                target_entry['simulated_value'] = evaluated_output

            # --- SymPy LaTeX Rendering Factory for Formulas ---
            if archetype_name.lower().startswith('formula'):
                # Prefer free symbols from the expression being operated on
                # (e.g. linked formula1 output before simplify-for-target).
                if hasattr(validator, 'last_extracted_free_symbols') and validator.last_extracted_free_symbols:
                    sym_set = set(validator.last_extracted_free_symbols)

                if hasattr(validator, 'last_computed_sympy_result'):
                    try:
                        result_obj = validator.last_computed_sympy_result
                        # sp.latex(None) → \text{None}; keep evaluated string instead
                        if result_obj is None:
                            latex_output = evaluated_output
                        elif isinstance(result_obj, tuple) and len(result_obj) >= 2:
                            # Preserve <= / >= / < / > from the formula (do not hard-code "=").
                            display_op = getattr(validator, "last_relation_display_op", None)
                            if not display_op:
                                op_match = re.search(
                                    r"(<=|>=|==|<|>|=)",
                                    str(evaluated_output or ""),
                                )
                                display_op = op_match.group(1) if op_match else "="
                            if display_op == "==":
                                display_op = "="
                            op_tex = {
                                "<=": r"\leq",
                                ">=": r"\geq",
                                "<": "<",
                                ">": ">",
                                "=": "=",
                            }.get(display_op, "=")
                            latex_output = (
                                f"{sp.latex(result_obj[0])} {op_tex} {sp.latex(result_obj[1])}"
                            )
                            if not sym_set:
                                sym_set = result_obj[0].free_symbols.union(result_obj[1].free_symbols)
                        else:
                            if isinstance(result_obj, sp.Symbol):
                                eval_str = str(evaluated_output)
                                if '[' in eval_str and ']' in eval_str:
                                    inner = eval_str.split('[', 1)[1].rsplit(']', 1)[0]
                                    raw_solutions = [s.strip() for s in inner.split(',') if s.strip()]
                                    latex_solutions = []
                                    
                                    parsing_env = {str(result_obj): result_obj}
                                    if hasattr(result_obj, 'free_symbols'):
                                        for sym in result_obj.free_symbols:
                                            parsing_env[str(sym)] = sym

                                    for sol in raw_solutions:
                                        try:
                                            parsed_sol = sp.parse_expr(sol, local_dict=parsing_env, global_dict=sp.__dict__)
                                            latex_solutions.append(sp.latex(parsed_sol))
                                        except Exception:
                                            latex_solutions.append(sol)
                                            
                                    latex_output = f"{str(result_obj)} = [{', '.join(latex_solutions)}]"
                                else:
                                    latex_output = eval_str
                            else:
                                latex_output = sp.latex(result_obj)
                                
                            if not sym_set:
                                sym_set = result_obj.free_symbols if hasattr(result_obj, 'free_symbols') else set()

                    except Exception as e:
                        logger.exception(
                            "Failed converting formula result to LaTeX for token <%s>: %s",
                            sequence_token,
                            e,
                        )

            # --- Unified Variable Extraction Pass (Formulas & Matrices) ---
            if sym_set:
                for sym in sym_set:
                    sym_str = str(sym)
                    ok, _err = _is_valid_algebraic_variable_name(sym_str)
                    if ok:
                        extracted_vars.append(sym_str)

        except Exception as eval_err:
            logger.exception(
                "Entity evaluation failed for <%s> (%s): %s",
                sequence_token,
                archetype_name,
                eval_err,
            )
            evaluated_output = "⚠️ Error"
            latex_output = "⚠️ Error"
            is_valid = False
            # Field-scoped so the workspace banner and save draft path can surface it
            error_field = "formula"
            if archetype_name == "matrix":
                error_field = "matrix_data"
            elif archetype_name == "matrixResultByIndex":
                error_field = "matrix"
            elif archetype_name == "graph":
                error_field = "formulas"
            elif archetype_name == "slopeFieldGraph":
                error_field = "equation"
            elif archetype_name == "graphBetweenPoints":
                error_field = "segments"
            elif archetype_name == "numAnswer":
                error_field = "value"
            elif archetype_name == "shortAnswer":
                error_field = "value"
            elif archetype_name == "longAnswer":
                error_field = "inputs"
            elif archetype_name == "canvas":
                error_field = "source"
            elif archetype_name == "arrayMatchingUnordered":
                error_field = "results"
            elif archetype_name == "answersOrDne":
                error_field = "answers"
            elif archetype_name == "multipleChoiceAnswer":
                error_field = "options"
            elif archetype_name == "matrixAnswer":
                error_field = "matrix"
            errors = {
                error_field: (
                    f"Expression could not be evaluated after resolving linked "
                    f"entities: {eval_err}"
                )
            }
    else:
        # Fallback parsing for invalid states
        try:
            if archetype_name == 'numAnswer':
                evaluated_output = "[Invalid Numeric Answer]"
                latex_output = "[Invalid Numeric Answer]"
            elif archetype_name == 'shortAnswer':
                evaluated_output = "[Invalid Short Answer]"
                latex_output = "[Invalid Short Answer]"
            elif archetype_name == 'longAnswer':
                evaluated_output = "[Invalid Long Answer]"
                latex_output = "[Invalid Long Answer]"
            elif archetype_name == 'canvas':
                evaluated_output = "[Invalid Canvas]"
                latex_output = "[Invalid Canvas]"
            elif archetype_name == 'arrayMatchingUnordered':
                evaluated_output = "[Invalid Array Matching]"
                latex_output = "[Invalid Array Matching]"
            elif archetype_name == 'answersOrDne':
                evaluated_output = "[Invalid Answers or DNE]"
                latex_output = "[Invalid Answers or DNE]"
            elif archetype_name == 'multipleChoiceAnswer':
                evaluated_output = "[Invalid Multiple Choice]"
                latex_output = "[Invalid Multiple Choice]"
            elif archetype_name == 'matrixAnswer':
                # Matrix linked but incomplete (e.g. no solve cells yet): still
                # return the grid JSON so the author card can paint toggle cells.
                try:
                    if getattr(validator, "runtime_values", {}).get("rows_display") is not None:
                        evaluated_output = str(validator.evaluate_output())
                        try:
                            parsed = json.loads(evaluated_output)
                            latex_output = str(parsed.get("summary") or evaluated_output)
                        except Exception:
                            latex_output = evaluated_output
                    elif clean_inputs.get("matrix"):
                        # is_valid failed before hydrate (e.g. resolve error) —
                        # attempt a soft evaluate for author UI.
                        evaluated_output = str(validator.evaluate_output())
                        try:
                            parsed = json.loads(evaluated_output)
                            latex_output = str(parsed.get("summary") or evaluated_output)
                        except Exception:
                            latex_output = evaluated_output
                    else:
                        evaluated_output = "[Link a matrix]"
                        latex_output = "[Link a matrix]"
                except Exception:
                    evaluated_output = "[Invalid Matrix Answer]"
                    latex_output = "[Invalid Matrix Answer]"
            elif clean_inputs.get('formula') and archetype_name == 'formula':
                evaluated_output = str(validator.evaluate_output())
                latex_output = evaluated_output
            elif archetype_name == 'graph':
                evaluated_output = "[Invalid Graph Config]"
                latex_output = "[Invalid Graph Config]"
            elif archetype_name == 'slopeFieldGraph':
                evaluated_output = "[Invalid Slope Field Config]"
                latex_output = "[Invalid Slope Field Config]"
            elif archetype_name == 'graphBetweenPoints':
                evaluated_output = "[Invalid Graph Between Points]"
                latex_output = "[Invalid Graph Between Points]"
            elif archetype_name == 'matrix':
                evaluated_output = "[Invalid Matrix Config]"
                latex_output = "[Invalid Matrix Config]"
            elif archetype_name == 'matrixResultByIndex':
                evaluated_output = "[Invalid Matrix Cell Index]"
                latex_output = "[Invalid Matrix Cell Index]"
            else:
                evaluated_output = "0"
                latex_output = "0"
        except Exception:
            evaluated_output = clean_inputs.get('formula', clean_inputs.get('nodes', '0'))
            latex_output = str(evaluated_output)

    # Post-processing string cleanup for evaluate=False *1 artifacts (formula + matrix)
    if archetype_name.lower().startswith('formula') or archetype_name in ('matrix', 'matrixResultByIndex'):
        if isinstance(evaluated_output, str):
            evaluated_output = re.sub(r'\b-1\*1\b', '-1', evaluated_output)
            evaluated_output = re.sub(r'\b1\*', '', evaluated_output)
            evaluated_output = re.sub(r'\*1\b', '', evaluated_output)

        if isinstance(latex_output, str):
            latex_output = re.sub(r'\\left\(-1\\right\)\s+1\b', r'\\left(-1\\right)', latex_output)
            latex_output = re.sub(r'\b-1\s+\\cdot\s+1\b', '-1', latex_output)
            latex_output = re.sub(r'\s+\\cdot\s+1\b', '', latex_output)
            latex_output = re.sub(r'\\left\(-1\\right\)\s+\\cdot\s+', '-', latex_output)
            latex_output = re.sub(r'\b1\s+\\cdot\s*', '', latex_output)
            latex_output = re.sub(r'\b1\s+([a-zA-Z\\])', r'\1', latex_output)

    extracted_vars.sort()

    output_types = []
    if is_valid and hasattr(validator, 'output_types'):
        output_types = list(getattr(validator, 'output_types') or [])

    return {
        'is_valid': is_valid,
        'errors': errors,
        'evaluated_output': evaluated_output,
        'latex_output': latex_output,
        'extracted_variables': ", ".join(extracted_vars),
        'output_types': output_types,
    }
