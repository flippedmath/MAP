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
from sympy.parsing.sympy_parser import parse_expr
from sympy.parsing.latex import parse_latex
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


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
            r'exp|log|ln|sqrt|'
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
            # 🎯 Compiled regex pattern matching any lowercase Greek letter base name
            greek_pattern = r'^(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lamda|mu|nu|xi|omicron|rho|sigma|tau|upsilon|phi|chi|psi|omega)'
            
            raw_elements = [v.strip() for v in str(variables_str).split(",") if v.strip()]
            for item in raw_elements:
                # 🎯 FIX: Block SymPy internal protected constants E and I from being used as variables
                if item in ('E', 'I'):
                    self.errors["variables"] = f"'{item}' is a reserved mathematical constant in SymPy and cannot be used as a variable identifier."
                    break

                item_lower = item.lower()
                # Standard character checks (e.g., x, y3, z_2)
                is_standard = bool(re.match(r'^[a-zA-Z][0-9]*$', item))
                is_subscript = bool(re.match(r'^[a-zA-Z]_[0-9]+$', item))
                
                # 🎯 FIXED: Greek character checks supporting subscripts (e.g., alpha, alpha3, alpha_3)
                is_greek_base = bool(re.match(greek_pattern + r'$', item_lower))
                is_greek_num  = bool(re.match(greek_pattern + r'[0-9]+$', item_lower))
                is_greek_sub  = bool(re.match(greek_pattern + r'_[0-9]+$', item_lower))
                
                if not (is_standard or is_subscript or is_greek_base or is_greek_num or is_greek_sub):
                    self.errors["variables"] = f"'{item}' is not a valid algebraic variable identifier."
                    break
                    
                parsed_variables.append(item)
        
        if "variables" not in self.errors:
            self.runtime_values["parsed_variables_array"] = parsed_variables

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

        if solve_for_target in ["-- N/A --", "-- choose variable --"]:
            solve_for_target = ""


        if not formula_str:
            return "0"

        # Build local substitutions structures
        subs_map = self.data.get('substitutions', {}) or {}
        if not isinstance(subs_map, dict):
            subs_map = {}
            
        for k, v in self.data.items():
            if k.startswith('sub_') and v is not None:
                var_name = k.replace('sub_', '').strip()
                subs_map[var_name] = v

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
            try:
                if not solve_for_target:
                    if not has_relation:
                        parsed_expr = parse_segment(processed_formula_clean)
                        result = sp.simplify(parsed_expr.doit())
                    else:
                        left_raw, right_raw = processed_formula_clean.split(rel_op, 1)
                        left_parsed = parse_segment(left_raw)
                        right_parsed = parse_segment(right_raw)
                        left_simplified = sp.simplify(left_parsed.doit())
                        right_simplified = sp.simplify(right_parsed.doit())
                        self.last_computed_sympy_result = (left_simplified, right_simplified)
                        return f"{left_simplified} {display_op} {right_simplified}"
                else:
                    target_symbol = sp.Symbol(solve_for_target)
                    if not has_relation:
                        parsed_expr = parse_segment(processed_formula_clean)
                        equation = sp.Eq(parsed_expr.doit(), 0)
                        rel_op = "="
                    else:
                        left_raw, right_raw = processed_formula_clean.split(rel_op, 1)
                        left_parsed = parse_segment(left_raw).doit()
                        right_parsed = parse_segment(right_raw).doit()
                        if rel_op in ["=", "=="]: equation = sp.Eq(left_parsed, right_parsed)
                        elif rel_op == "<":   equation = sp.Lt(left_parsed, right_parsed)
                        elif rel_op == "<=":  equation = sp.Le(left_parsed, right_parsed)
                        elif rel_op == ">":   equation = sp.Gt(left_parsed, right_parsed)
                        elif rel_op == ">=":  equation = sp.Ge(left_parsed, right_parsed)

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
                        if len(solutions) == 1: resolved_right_side = solutions[0]
                        elif len(solutions) > 1: resolved_right_side = f"[{', '.join(str(s) for s in solutions)}]"
                        else: resolved_right_side = "0"
                    else:
                        resolved_right_side = solutions

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
                
                if sympy_subs_map:
                    with sp.evaluate(False):
                        if isinstance(parsed_expr, tuple):
                            result_left = parsed_expr[0].subs(sympy_subs_map)
                            result_right = parsed_expr[1].subs(sympy_subs_map)
                            self.last_computed_sympy_result = (result_left, result_right)
                            return f"{result_left} {display_op} {result_right}"
                        else:
                            result = parsed_expr.subs(sympy_subs_map)
                else:
                    if isinstance(parsed_expr, tuple):
                        self.last_computed_sympy_result = parsed_expr
                        return f"{parsed_expr[0]} {display_op} {parsed_expr[1]}"
                    result = parsed_expr
            else:
                result = parsed_expr

        self.last_computed_sympy_result = result
        return str(result)



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

            greek_pattern = r'^(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lamda|mu|nu|xi|omicron|rho|sigma|tau|upsilon|phi|chi|psi|omega)'
            
            for item, raw_val in variables_dict.items():
                item = item.strip()
                if item in ('E', 'I'):
                    self.errors["variables"] = f"'{item}' is a reserved mathematical constant in SymPy."
                    break

                item_lower = item.lower()
                is_standard = bool(re.match(r'^[a-zA-Z][0-9]*$', item))
                is_subscript = bool(re.match(r'^[a-zA-Z]_[0-9]+$', item))
                is_greek_base = bool(re.match(greek_pattern + r'$', item_lower))
                is_greek_num  = bool(re.match(greek_pattern + r'[0-9]+$', item_lower))
                is_greek_sub  = bool(re.match(greek_pattern + r'_[0-9]+$', item_lower))
                
                if not (is_standard or is_subscript or is_greek_base or is_greek_num or is_greek_sub):
                    self.errors["variables"] = f"'{item}' is not a valid algebraic variable identifier."
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
                raw = float(sp.N(raw))
            else:
                raw = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(raw):
            return None
        return raw

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
    """

    def is_valid(self):
        if not super().is_valid():
            return False

        raw_value = self.runtime_values.get("value", self.data.get("value"))
        trimmed = self._trim_str(raw_value)
        if not trimmed:
            self.errors["value"] = "A correct answer is required (text or linked formula)."
            return False

        simplified = self._simplify_key(trimmed)
        self.runtime_values["resolved_value"] = trimmed
        self.runtime_values["simplified_key"] = simplified
        self.cleaned_data["value"] = self.data.get("value", trimmed)
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
    Answer-field unordered comma-separated list matching.
    Numbers compare after round(..., 3); strings after trim+lowercase.
    Multiset matching. Optional partial credit with ±sub / −½ sub penalties.
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

    def _normalize_token(self, piece):
        text = str(piece).strip().lower()
        if not text:
            return None
        try:
            num = float(text)
            if math.isfinite(num):
                return ("num", round(num, 3))
        except (TypeError, ValueError):
            pass
        return ("str", text)

    def _parse_list(self, raw):
        s = self._raw_to_str(raw).strip()
        if not s:
            return []
        items = []
        for part in s.split(","):
            token = self._normalize_token(part)
            if token is not None:
                items.append(token)
        return items

    def _format_token(self, token):
        kind, val = token
        if kind == "num":
            if float(val).is_integer():
                return str(int(val))
            return str(val)
        return str(val)

    def _format_list(self, items):
        return ", ".join(self._format_token(t) for t in items)

    def _match_counts(self, key_items, student_items):
        """Greedy multiset match. Returns (matches, missing, extras)."""
        remaining = list(student_items)
        matches = 0
        for key in key_items:
            found_idx = None
            for i, stud in enumerate(remaining):
                if stud == key:
                    found_idx = i
                    break
            if found_idx is not None:
                matches += 1
                remaining.pop(found_idx)
        missing = len(key_items) - matches
        extras = len(remaining)
        return matches, missing, extras

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

        self.runtime_values["key_items"] = key_items
        self.runtime_values["key_display"] = self._format_list(key_items)
        self.runtime_values["partial_credit"] = partial
        self.cleaned_data["results"] = self.data.get("results", raw_results)
        self.cleaned_data["partial_credit"] = partial
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
        matches, missing, extras = self._match_counts(key_items, student_items)
        partial = self._coerce_bool(
            self.runtime_values.get(
                "partial_credit",
                self.data.get("partial_credit", False),
            )
        )

        if not partial:
            if matches == n and extras == 0:
                return {"earned": pts, "max": pts, "detail": "All correct"}
            return {"earned": 0.0, "max": pts, "detail": "Incorrect"}

        sub = pts / n
        earned = matches * sub - 0.5 * sub * (missing + extras)
        if earned < 0:
            earned = 0.0
        return {
            "earned": earned,
            "max": pts,
            "detail": f"{matches}/{n} matched (partial)",
        }


class MultipleChoiceAnswerEntity(BaseEntity):
    """
    Multiple-choice answer field with dynamic options, optional radio mode,
    and grading methods: all_or_nothing (default), practical, proportional.
    """

    GRADING_METHODS = ("all_or_nothing", "practical", "proportional")

    def _coerce_bool(self, raw, default=False):
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "yes", "checked", "on")

    def _resolve_content(self, raw):
        if raw is None:
            return ""
        text = str(raw).strip()
        if not text:
            return ""
        if re.match(r"^<([^>]+)>$", text):
            try:
                return str(self.resolve_token_dependency(text)).strip()
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
            if not str(opt.get("content_resolved") or "").strip() and not str(opt.get("content") or "").strip():
                self.errors["options"] = "Each choice must have text or a linked Dynamic Variable."
                return False
            # Linked but failed resolve already set errors
            if str(opt.get("content") or "").strip().startswith("<") and not str(opt.get("content_resolved") or "").strip():
                if "options" not in self.errors:
                    self.errors["options"] = f"Could not resolve linked option {opt.get('id')}."
                return False

        num_correct = sum(1 for o in options if o.get("is_correct"))
        if num_correct < 1:
            self.errors["options"] = "At least one choice must be marked as correct."
            return False

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

        n = len(options)
        k = sum(1 for o in options if o.get("is_correct"))
        method = self.runtime_values.get("grading_method", "all_or_nothing")
        method_label = {
            "all_or_nothing": "all-or-nothing",
            "practical": "practical",
            "proportional": "proportional",
        }.get(method, method)
        self.output_types = ["content"]
        return f"{n} options, {k} correct ({method_label})"

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
            if num_correct <= 0:
                return {"earned": 0.0, "max": pts, "detail": "Practical: no correct options"}
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
        if num_correct <= 0:
            # Defensive: not allowed by validation
            if num_incorrect <= 0:
                earned = 0.0
            else:
                earned = pts * (wrong_selected / num_incorrect)
            if earned < 0:
                earned = 0.0
            return {
                "earned": earned,
                "max": pts,
                "detail": f"Proportional: {correct_selected} correct selected, {wrong_selected} wrong",
            }

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
        "arrayMatchingUnordered": ArrayMatchingUnorderedEntity,
        "multipleChoiceAnswer": MultipleChoiceAnswerEntity,
        "matrixAnswer": MatrixAnswerEntity,
        "slopeFieldGraph": SlopeFieldGraphEntity,
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
                if hasattr(validator, 'last_computed_sympy_result'):
                    try:
                        result_obj = validator.last_computed_sympy_result
                        if isinstance(result_obj, tuple):
                            latex_output = f"{sp.latex(result_obj[0])} = {sp.latex(result_obj[1])}"
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
                                
                            sym_set = result_obj.free_symbols if hasattr(result_obj, 'free_symbols') else set()

                    except Exception as e:
                        logger.exception(
                            "Failed converting formula result to LaTeX for token <%s>: %s",
                            sequence_token,
                            e,
                        )

            # --- Unified Variable Extraction Pass (Formulas & Matrices) ---
            if sym_set:
                # 🎯 Compiled regex pattern matching any lowercase Greek letter
                greek_pattern = r'^(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lamda|mu|nu|xi|omicron|rho|sigma|tau|upsilon|phi|chi|psi|omega)'
                
                for sym in sym_set:
                    sym_str = str(sym)
                    
                    is_standard = bool(re.match(r'^[a-zA-Z]\d*$', sym_str))
                    is_subscript = bool(re.match(r'^[a-zA-Z]_\d+$', sym_str))
                    is_greek_base = bool(re.match(greek_pattern + r'$', sym_str, re.IGNORECASE))
                    is_greek_sub = bool(re.match(greek_pattern + r'_\d+$', sym_str, re.IGNORECASE))
                    is_greek_num = bool(re.match(greek_pattern + r'\d+$', sym_str, re.IGNORECASE))
                    
                    if is_standard or is_subscript or is_greek_base or is_greek_sub or is_greek_num:
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
            elif archetype_name == "numAnswer":
                error_field = "value"
            elif archetype_name == "shortAnswer":
                error_field = "value"
            elif archetype_name == "longAnswer":
                error_field = "inputs"
            elif archetype_name == "arrayMatchingUnordered":
                error_field = "results"
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
            elif archetype_name == 'arrayMatchingUnordered':
                evaluated_output = "[Invalid Array Matching]"
                latex_output = "[Invalid Array Matching]"
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
