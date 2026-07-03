import re
# from .models import BranchGroup, UsersInCourse, EntitySegment ... instead of this, use --> BranchGroup = apps.get_model('assessment_tool', 'BranchGroup')
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
import random
import json
import sympy as sp
from sympy.parsing.sympy_parser import parse_expr
from sympy.parsing.latex import parse_latex
from django.core.exceptions import ValidationError



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


import random
import re

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
        
        print(f"    🔗 [DEPENDENCY RESOLVER] Linking asset detected: {token_string}")
        print(f"        Searching active workspace ledger for signature: '{clean_sequence_token}'")

        target_payload = next(
            (item for item in self.all_entities_payload if (item.get("sequence_token") or item.get("indexed_token") or "") == clean_sequence_token),
            None
        )
        
        if not target_payload:
            print(f"        ❌ [DEPENDENCY ERROR] Reference tracker could not locate '{clean_sequence_token}' inside structural map.")
            raise ValidationError(f"Linked reference token <{clean_sequence_token}> could not be found in active workspace components.")
        
        token_archetype = target_payload.get("token")
        token_inputs = target_payload.get("inputs", {})
        token_blueprint = get_blueprint_for_token(token_archetype)
        
        print(f"        📍 Located Parent Entity: Archetype='{token_archetype}', Inputs={token_inputs}")
        
        # 🎯 SHORT-CIRCUIT FOR RANDOM ARCHETYPES
        # If the target is an upstream random entity, reuse its client-side generated value
        # 🎯 CACHE HIT: Check if we already have a locked-in client string or a freshly computed value
        cached_val = target_payload.get('simulated_value', '')
        if token_archetype in ['rand', 'randInt'] and cached_val != "":
            print(f"        🎲 [CACHE HIT] Reusing active simulation value for '{clean_sequence_token}' ➔ '{cached_val}'")
            return cached_val

        # 🎯 CACHE MISS: If cached_val is "", evaluate via sub-engine sub-pipeline
        print(f"        🔄 [CACHE MISS / EVALUATION] Instantiating sub-engine validator for: {clean_sequence_token}")
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
            print(f"        💾 [CACHE WRITE-BACK] Saving rolled value '{resolved_value}' to state payload for token record: {clean_sequence_token}")
            target_payload['simulated_value'] = resolved_value  # This updates it in all_entities_payload by reference!

        print(f"        💎 [DEPENDENCY SUCCESS] Inter-component pipeline resolved {token_string} ➔ '{resolved_value}'")
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
        min_val = self.resolve_numeric_value("min", default_fallback=-9)
        max_val = self.resolve_numeric_value("max", default_fallback=9)
        step_val = self.resolve_numeric_value("step", default_fallback=1)
        exclude_raw = self.runtime_values.get("exclude", "")

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
                    upstream_min_bound = int(float(upstream_inputs.get("min", -9)))
                    
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
        if exclude_raw:
            elements = [item.strip() for item in str(exclude_raw).split(",") if item.strip()]
            parsed_integers = []
            for item in elements:
                if re.match(r"^<([^>]+)>$", item):
                    try:
                        resolved_item = self.resolve_token_dependency(item)
                        parsed_integers.append(int(float(resolved_item)))
                        continue
                    except Exception:
                        pass
                        
                if not re.match(r"^-?\d+$", item):
                    self.errors["exclude"] = f"Value '{item}' inside exclude filter is not a valid integer."
                    break
                parsed_integers.append(int(item))
            
            if "exclude" not in self.errors:
                self.runtime_values["exclude_array"] = parsed_integers

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
                    print(f"        🎲 [RAND ENGINE LOCK] Found existing cached state '{cached_val}' for self. Keeping it.")
                    return cached_val
                
        min_val = int(self.resolve_numeric_value("min", default_fallback=-9))
        max_val = int(self.resolve_numeric_value("max", default_fallback=9))
        step_val = int(self.resolve_numeric_value("step", default_fallback=1))
        exclude_set = set(self.runtime_values.get("exclude_array", []))

        print(f"    🎲 [RandomIntegerEntity] Processing pool calculations (O(1) Optimized):")
        print(f"        Bounds Range: {min_val} to {max_val} (Using Step Intervals: {step_val})")
        if exclude_set:
            print(f"        Exclusion Filter active elements: {exclude_set}")

        if min_val > max_val:
            print(f"        ⚠️ Boundary guard triggered (min > max) ➔ Output fallback: '{min_val}'")
            return str(min_val)

        # Calculate the absolute max step indices possible within this integer span
        total_range = max_val - min_val
        max_steps = total_range // step_val

        # If range or steps result in no legal spaces, fallback cleanly
        if max_steps < 0:
            print(f"        ⚠️ Legal step size context evaluated to empty ➔ Output fallback: '{min_val}'")
            return str(min_val)

        # 🎯 EXCLUSION LOOP GUARD: Direct sampling to guarantee O(1) space integrity
        attempts = 0
        max_attempts = 200 # Prevent infinite locks if a user accidentally excludes every number in range
        
        while attempts < max_attempts:
            random_step_multiplier = random.randint(0, max_steps)
            candidate_value = min_val + (random_step_multiplier * step_val)
            
            if candidate_value not in exclude_set:
                selected_choice = str(candidate_value)
                print(f"        ⚡ Calculated Random Step Index: {random_step_multiplier}/{max_steps}")
                print(f"        ➔ Computed Safe Integer Value Outcome: '{selected_choice}'")
                return selected_choice
            
            attempts += 1

        # Fallback Strategy: If random sampling kept hitting exclusions, loop once to find the absolute first unexcluded slot
        print(f"        ⚠️ High density exclusion collision detected. Reverting to linear first-match fallback.")
        current = min_val
        while current <= max_val:
            if current not in exclude_set:
                return str(current)
            current += step_val

        print(f"        ⚠️ No legal entries matched requirements! Falling back to min_val boundary default.")
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
                    print(f"        🎲 [RAND ENGINE LOCK] Found existing cached state '{cached_val}' for self. Keeping it.")
                    return cached_val
                
        min_val = self.resolve_numeric_value("min", default_fallback=0.0)
        max_val = self.resolve_numeric_value("max", default_fallback=1.0)
        step_val = self.resolve_numeric_value("step", default_fallback=0.01)

        print(f"    🎲 [RandomDoubleEntity] Computing dynamic float configurations:")
        print(f"        Resolved Bounds Range: {min_val} to {max_val} (Step decimal interval: {step_val})")

        if min_val >= max_val:
            val_out = str(round(min_val, 4))
            print(f"        ⚠️ Boundary logic guard triggered (min >= max) ➔ Output fallback: '{val_out}'")
            return val_out

        total_range = max_val - min_val
        max_steps = int((total_range + 1e-9) // step_val)

        if max_steps <= 0:
            val_out = str(round(min_val, 4))
            print(f"        ⚠️ Steps interval range calculated as zero or empty ➔ Output fallback: '{val_out}'")
            return val_out

        random_step_multiplier = random.randint(0, max_steps)
        result_value = min_val + (random_step_multiplier * step_val)

        if result_value > max_val:
            result_value = max_val

        step_str = str(step_val)
        decimal_places = len(step_str.split('.')[1]) if '.' in step_str else 4
        final_double_out = str(round(result_value, decimal_places))
        
        print(f"        ⚡ Calculated Random Multiplier Step Index: {random_step_multiplier}/{max_steps}")
        print(f"        ➔ Computed Continuous Decimal Value Outcome: '{final_double_out}'")
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
        print(f"    🔢 [PrimeFactorsEntity] Initiating factorization calculation workflow:")
        print(f"        Target input digit to decompose: {n}")

        if n <= 1:
            print(f"        ⚠️ Input number {n} is <= 1. No factorable matrix available.")
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
        print(f"        ⚡ Factorization chain decomposition completed successfully:")
        print(f"            {original_n} ➔ [{factors_result_str}]")
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

        print(f"    [FormulaEntity.is_valid] Runtime Values:")
        print(f"        formula_expr: {repr(formula_expr)}")
        print(f"        solve_method: {repr(solve_method)}")
        print(f"        solve_for_target: {repr(solve_for_target)}")

        if not formula_expr:
            if solve_method in ['variable substitution', 'simplify']:
                self.runtime_values["formula"] = "0"
                formula_expr = "0"
            else:
                self.errors["formula"] = "A mathematical expression or equation string is required."
                return False
        
        if formula_expr and str(formula_expr).strip() != "0":
            # Temporarily substitute macro tokens with an arbitrary integer for raw syntax evaluation
            clean_syntax_check = re.sub(r'&lt;([^&>]+)&gt;|<([^>]+)>', '1', str(formula_expr))
            print(f"        Formula string before SymPy validation check: {repr(clean_syntax_check)}")
            is_valid_syntax, syntax_error_msg = SymPyAssessmentEngine.check_syntax_validity(clean_syntax_check)
            if not is_valid_syntax:
                print(f"        ❌ SymPy Syntax Check Error found: {syntax_error_msg}")
                self.errors["formula"] = syntax_error_msg

        parsed_variables = []
        if variables_str:
            raw_elements = [v.strip() for v in str(variables_str).split(",") if v.strip()]
            for item in raw_elements:
                if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', item):
                    self.errors["variables"] = f"'{item}' is not a valid algebraic variable identifier."
                    break
                parsed_variables.append(item)
        
        if "variables" not in self.errors:
            self.runtime_values["parsed_variables_array"] = parsed_variables

        # 🎯 UPDATED BLOCK: ENFORCING N/A RECONCILIATION FOR SIMPLIFY METHOD
        if solve_method == "simplify":
            # If a target variable is selected, make sure it is defined in the variables index
            if parsed_variables and solve_for_target and (solve_for_target not in parsed_variables):
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

        print("What is the dropdown value?: {}, {}, {}".format(self.runtime_values.get("variable to simplify"), self.runtime_values.get("variable to substitute"), self.runtime_values.get("variable to solve for")))

        if solve_for_target in ["-- N/A --", "-- choose variable --"]:
            solve_for_target = ""

        print(f"    [FormulaEntity.evaluate_output] Executing...")
        print(f"        Original string: {repr(formula_str)}")
        print(f"        Target variable: {repr(solve_for_target)}")

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
                resolved_subs[var_name] = f"({self.resolve_token_dependency(var_value)})"
            else:
                resolved_subs[var_name] = var_value

        def bracket_replacer(match):
            target_token = match.group(1) if match.group(1) else match.group(2)
            resolved = f"({self.resolve_token_dependency(f'<{target_token.strip()}>')})"
            return resolved

        processed_formula = re.sub(r'&lt;([^&>]+)&gt;|<([^>]+)>', bracket_replacer, formula_str)
        print(f"        String after macro substitution pipeline: {repr(processed_formula)}")

        local_dict = {var: sp.Symbol(var) for var in var_list}
        if 'pi' not in local_dict:
            local_dict['pi'] = sp.pi

        if solve_method in ['leave as formula', 'variable substitution', 'simplify']:
            local_dict['integrate'] = sp.Integral
            local_dict['diff'] = sp.Derivative
            local_dict['limit'] = sp.Limit

        # Helper method to parse single standalone chunk strings via SymPy safely
        def parse_segment(expr_str):
            if "\\" in expr_str:
                return parse_latex(expr_str)
            return sp.parse_expr(expr_str, local_dict=local_dict, evaluate=False)

        # 🎯 CHOOSE CORRECT RELATION MATCH (Order sorted by length to prevent partial matches)
        rel_match = re.search(r'(<=|>=|==|<|>|=)', processed_formula)
        has_relation = rel_match is not None
        
        rel_op = rel_match.group(1) if has_relation else ""
        display_op = "=" if rel_op == "==" else rel_op

        print(f"~~~~~~~solve method: {solve_method}, relation operator: {repr(rel_op)}, solve_for_target: {solve_for_target}")

        # 🎯 PROCESS SIMPLIFY STRATEGIES
        if solve_method == 'simplify':

            # SCENARIO A: Target is "-- N/A --"
            if not solve_for_target:
                if not has_relation:
                    parsed_expr = parse_segment(processed_formula)
                    result = sp.simplify(parsed_expr.doit())
                else:
                    left_raw, right_raw = processed_formula.split(rel_op, 1)
                    left_parsed = parse_segment(left_raw)
                    right_parsed = parse_segment(right_raw)
                    
                    left_simplified = sp.simplify(left_parsed.doit())
                    right_simplified = sp.simplify(right_parsed.doit())
                    
                    self.last_computed_sympy_result = (left_simplified, right_simplified)
                    return f"{left_simplified} {display_op} {right_simplified}"

            # SCENARIO B: Target Variable is explicitly chosen
            else:
                target_symbol = sp.Symbol(solve_for_target)
                
                if not has_relation:
                    parsed_expr = parse_segment(processed_formula)
                    equation = sp.Eq(parsed_expr.doit(), 0)
                    rel_op = "="
                else:
                    left_raw, right_raw = processed_formula.split(rel_op, 1)
                    left_parsed = parse_segment(left_raw).doit()
                    right_parsed = parse_segment(right_raw).doit()
                    
                    if rel_op in ["=", "=="]: equation = sp.Eq(left_parsed, right_parsed)
                    elif rel_op == "<":   equation = sp.Lt(left_parsed, right_parsed)
                    elif rel_op == "<=":  equation = sp.Le(left_parsed, right_parsed)
                    elif rel_op == ">":   equation = sp.Gt(left_parsed, right_parsed)
                    elif rel_op == ">=":  equation = sp.Ge(left_parsed, right_parsed)

                # 🎯 AUTOMATIC SIGN FLIPPING HANDLER FOR INEQUALITIES
                if rel_op in ["<", "<=", ">", ">="]:
                    try:
                        solved_rel = sp.reduce_inequalities(equation, target_symbol)
                        self.last_computed_sympy_result = solved_rel
                        return str(solved_rel)
                    except Exception as e:
                        print(f"        ⚠️ Inequality solver fallback triggered: {e}")
                        solutions = sp.solve(equation, target_symbol)
                else:
                    solutions = sp.solve(equation, target_symbol)
                
                if isinstance(solutions, list):
                    if len(solutions) == 1:
                        resolved_right_side = solutions[0]
                    elif len(solutions) > 1:
                        resolved_right_side = f"[{', '.join(str(s) for s in solutions)}]"
                    else:
                        resolved_right_side = "0"
                else:
                    resolved_right_side = solutions

                if not isinstance(resolved_right_side, str):
                    self.last_computed_sympy_result = sp.Eq(target_symbol, resolved_right_side)
                else:
                    self.last_computed_sympy_result = target_symbol

                # For inequalities, reduce_inequalities handles output layout. For standard equations, maintain dynamic target = solution layout
                return f"{solve_for_target} = {resolved_right_side}"

        # 🎯 RETAIN OTHER NATIVE SOLVE METHODS AS IS
        else:
            if has_relation and solve_method == 'variable substitution':
                left_raw, right_raw = processed_formula.split(rel_op, 1)
                parsed_expr = (parse_segment(left_raw), parse_segment(right_raw))
            
            elif has_relation and solve_method == 'leave as formula':
                left_raw, right_raw = processed_formula.split(rel_op, 1)
                left_parsed = parse_segment(left_raw)
                right_parsed = parse_segment(right_raw)
                
                self.last_computed_sympy_result = (left_parsed, right_parsed)
                return f"{left_parsed} {display_op} {right_parsed}"
            
            else:
                parsed_expr = parse_segment(processed_formula)

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
                            # 🎯 FIX: Honor the actual operational sign during variable substitutions
                            return f"{result_left} {display_op} {result_right}"
                        else:
                            result = parsed_expr.subs(sympy_subs_map)
            else:
                result = parsed_expr

        print(f"        SymPy Final Computed Object: {repr(result)}")
        self.last_computed_sympy_result = result
        return str(result)


class MatrixEntity(BaseEntity):
    """
    Validation engine for the 'matrix' or 'matrixAnswer' token patterns.
    """
    def is_valid(self):
        if not super().is_valid():
            return False

        rows = self.cleaned_data.get("rows")
        cols = self.cleaned_data.get("cols")
        cells = self.data.get("inputs", {}).get("cells")  # Grab raw inputs array reference

        if not isinstance(cells, list):
            self.errors["cells"] = "Cells property must be a multi-dimensional array matrix layout."
            return False

        # 1. Rule: Row length validation
        if len(cells) != rows:
            self.errors["cells"] = f"Row multi-array count balance error. Expected {rows} rows, received {len(cells)}."
            return False

        # 2. Rule: Column elements uniform length validation matrices verification
        for index, row_item in enumerate(cells):
            if not isinstance(row_item, list):
                self.errors["cells"] = f"Row at matrix index {index} must be a valid list."
                return False
            if len(row_item) != cols:
                self.errors["cells"] = f"Column elements mismatch at row index {index}. Expected {cols} columns, received {len(row_item)}."
                return False

        # If everything balances out, clean up elements structure copies safely
        self.cleaned_data["cells"] = cells
        return len(self.errors) == 0
    
    def evaluate_output(self):
        # Placeholder layout text representation for matrix entities
        cells = self.cleaned_data.get("cells") or [[0,0],[0,0]]
        return str(cells)
    

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

    if is_valid:
        try:
            evaluated_res = validator.evaluate_output()
            evaluated_output = str(evaluated_res)
            latex_output = evaluated_output
            
            # Dynamically update the shared context ledger for downstream dependency cascading
            target_entry = next((x for x in all_entities_payload if x.get('sequence_token') == sequence_token), None)
            if target_entry:
                target_entry['simulated_value'] = evaluated_output

            # --- SymPy LaTeX Rendering Factory ---
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
                        
                        extracted_vars = [str(sym) for sym in sym_set if re.match(r'^[a-zA-Z]\d*$', str(sym))]
                    except Exception as e:
                        print(f"⚠️ Shared helper SymPy LaTeX conversion error: {str(e)}")

        except Exception as eval_err:
            print(f"❌ Evaluation crash on <{sequence_token}>: {str(eval_err)}")
            evaluated_output = "⚠️ Error"
            latex_output = "⚠️ Error"
    else:
        # Fallback string parsing for invalid states (matches preview function legacy fallback)
        try:
            if clean_inputs.get('formula'):
                evaluated_output = str(validator.evaluate_output())
                latex_output = evaluated_output
            else:
                evaluated_output = "0"
                latex_output = "0"
        except Exception:
            evaluated_output = clean_inputs.get('formula', '0')
            latex_output = str(evaluated_output)

    # Secondary Regex Parse if SymPy dropped variables
    if archetype_name.lower().startswith('formula') and not extracted_vars:
        try:
            raw_formula_text = str(clean_inputs.get('formula', ''))
            clean_text = re.sub(r'&lt;([^&>]+)&gt;|<([^>]+)>', '', raw_formula_text)
            matches = re.findall(r'\b[a-zA-Z]\d*\b', clean_text)
            extracted_vars = list(set(matches))
        except Exception:
            pass
    extracted_vars.sort()

    return {
        'is_valid': is_valid,
        'errors': errors,
        'evaluated_output': evaluated_output,
        'latex_output': latex_output,
        'extracted_variables': ", ".join(extracted_vars)
    }
