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
    def substitute_tokens(cls, definition_string, evaluated_variables):
        """Replaces token patterns like <num1> with concrete evaluated string states."""
        for token, val in evaluated_variables.items():
            definition_string = definition_string.replace(f"<{token}>", str(val))
        return definition_string

    @classmethod
    def evaluate_variable(cls, content_json):
        """Evaluates structural variables down to individual numeric values or string expressions."""
        var_type = content_json.get('type')
        
        if var_type == 'variable_numeric':
            minimum = content_json.get('min', -9)
            maximum = content_json.get('max', 9)
            step = content_json.get('step', 1)
            exclude = content_json.get('exclude', [])
            
            # Generate valid range numbers
            choices = [x for x in range(int(minimum), int(maximum) + 1, int(step)) if x not in exclude]
            return random.choice(choices) if choices else 1
            
        return None

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
        # 🎯 TRACK SIBLINGS: Keep a reference to all sibling entities in the draft
        self.all_entities_payload = all_entities_payload or []
        self.cleaned_data = {}
        self.runtime_values = {} # 🎯 Holds real numbers for validation/evaluation
        self.errors = {}

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
                # Type-check the calculated raw value (converts string numbers to actual ints/floats)
                validated_result = self.validate_field_type(
                    input_key, value_to_validate, expected_field_type
                )
                
                # Runtime values always get the native type-casted value (e.g. 220)
                self.runtime_values[input_key] = validated_result
                
                # Cleaned data retains the blueprint layout pointer for the database write (e.g. "<randInt2>")
                self.cleaned_data[input_key] = user_value
                    
            except ValidationError as e:
                self.errors[input_key] = e.message

        return len(self.errors) == 0

    def resolve_token_dependency(self, token_string):
        """
        Recursively extracts the real-time simulation output value of a cross-referenced token tag.
        """
        clean_sequence_token = token_string.replace("<", "").replace(">", "").strip() # e.g. "randInt2"
        
        # Locate the targeted dependency configuration inside the sibling payload array context
        target_payload = next(
            (item for item in self.all_entities_payload if item.get("sequence_token") == clean_sequence_token),
            None
        )
        
        if not target_payload:
            raise ValidationError(f"Linked reference token <{clean_sequence_token}> could not be found in active workspace components.")

        # Avoid local circular lookups by importing factory at execution time
        
        token_archetype = target_payload.get("token")
        token_inputs = target_payload.get("inputs", {})
        token_blueprint = get_blueprint_for_token(token_archetype) # Fetch its blueprint dictionary profile
        
        # Build dependency engine instances, passing along the complete array context stack
        dependency_validator = get_entity_validator(
            token_archetype, 
            token_inputs, 
            token_blueprint, 
            all_entities_payload=self.all_entities_payload
        )
        
        if not dependency_validator.is_valid():
            raise ValidationError(f"Dependency error: Linked component <{clean_sequence_token}> has outstanding validation errors.")
            
        # Execute child computation tree evaluation recursively!
        return dependency_validator.evaluate_output()

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
        """
        🎯 CORE FORCE INTERFACE INTERACTION METHOD
        Calculates and produces evaluated simulation content data for live engine previews.
        """
        raise NotImplementedError("Child entity component sub-classes must override evaluate_output() configuration mappings.")
        

class RandomIntegerEntity(BaseEntity):
    """
    Validation engine for the 'randInt' token pattern.
    """
    def is_valid(self):
        if not super().is_valid():
            return False
            
        # 🎯 READ FROM runtime_values GUARANTEES NATIVE PYTHON NUMERICAL TYPES
        min_val = self.runtime_values.get("min")
        max_val = self.runtime_values.get("max")
        step_val = self.runtime_values.get("step")
        exclude_raw = self.runtime_values.get("exclude", "")

        if min_val is not None and max_val is not None and min_val > max_val:
            self.errors["min"] = f"Minimum bound ({min_val}) cannot be greater than maximum bound ({max_val})."

        if step_val is not None and step_val <= 0:
            self.errors["step"] = "Step value interval must be a positive integer greater than 0."

        if exclude_raw:
            elements = [item.strip() for item in str(exclude_raw).split(",") if item.strip()]
            parsed_integers = []
            for item in elements:
                if not re.match(r"^-?\d+$", item):
                    self.errors["exclude"] = f"Value '{item}' inside exclude filter is not a valid integer."
                    break
                parsed_integers.append(int(item))
            
            if "exclude" not in self.errors:
                self.runtime_values["exclude_array"] = parsed_integers

        return len(self.errors) == 0

    def evaluate_output(self):
        """
        🎯 CALCULATES REAL DYNAMIC INTEGERS ACCORDING TO USER PROPERTIES
        """
        # Read from runtime_values first, fallback to standard defaults if empty
        min_val = self.runtime_values.get("min") if self.runtime_values.get("min") is not None else -9
        max_val = self.runtime_values.get("max") if self.runtime_values.get("max") is not None else 9
        step_val = self.runtime_values.get("step") if self.runtime_values.get("step") is not None else 1
        exclude_set = set(self.runtime_values.get("exclude_array", []))

        possible_values = []
        current = min_val
        while current <= max_val:
            if current not in exclude_set:
                possible_values.append(current)
            current += step_val

        if not possible_values:
            return str(min_val)

        return str(random.choice(possible_values))


class RandomDoubleEntity(BaseEntity):
    """
    Validation engine for the 'rand' token pattern (Random Double/Decimal).
    """
    def is_valid(self):
        # 1. Execute parent class validation to guarantee type checking (e.g., matching "double" inputs)
        if not super().is_valid():
            return False
            
        min_val = self.runtime_values.get("min")
        max_val = self.runtime_values.get("max")
        step_val = self.runtime_values.get("step")

        # 2. Add domain-specific validation constraints for ranges and intervals
        if min_val is not None and max_val is not None and min_val > max_val:
            self.errors["min"] = f"Minimum bound ({min_val}) cannot be greater than maximum bound ({max_val})."

        if step_val is not None and step_val <= 0:
            self.errors["step"] = "Step decimal interval must be a positive number greater than 0."

        return len(self.errors) == 0

    def evaluate_output(self):
        """
        🎯 MEMORY SAFE CALCULATION: Computes random decimal steps mathematically 
        without instantiating large lists or hitting floating-point accumulation drift.
        """
        # Ensure safe fallbacks exist if unvalidated or missing
        min_val = self.runtime_values.get("min") if self.runtime_values.get("min") is not None else 0.0
        max_val = self.runtime_values.get("max") if self.runtime_values.get("max") is not None else 1.0
        step_val = self.runtime_values.get("step") if self.runtime_values.get("step") is not None else 0.01

        # Defensive fallback if bounds are invalid
        if min_val >= max_val:
            return str(round(min_val, 4))

        # 1. Find the total distance/span
        total_range = max_val - min_val

        # 2. Determine how many whole steps fit into this range.
        # Adding a tiny epsilon (1e-9) safely protects against rounding precision loss
        # dividing float thresholds (e.g., ensuring 0.3 / 0.1 evaluates cleanly to 3 steps).
        max_steps = int((total_range + 1e-9) // step_val)

        if max_steps <= 0:
            return str(round(min_val, 4))

        # 3. Choose a random step multiplier between 0 and max_steps inclusive
        random_step_multiplier = random.randint(0, max_steps)

        # 4. Multiply step size by our random multiplier to get the offset
        result_value = min_val + (random_step_multiplier * step_val)

        # 5. Cap the calculation defensively to prevent float math from overshooting max_val
        if result_value > max_val:
            result_value = max_val

        # 6. Determine decimal places in step_val to dynamically round the outcome
        # (e.g., if step is 0.001, we want to snap string display to 3 decimal spots)
        step_str = str(step_val)
        if '.' in step_str:
            decimal_places = len(step_str.split('.')[1])
        else:
            decimal_places = 4 # default sensible baseline fallback

        return str(round(result_value, decimal_places))
    

class PrimeFactorsEntity(BaseEntity):
    """
    Validation and evaluation engine for the 'primeFactors' token pattern.
    Expects an input field (e.g., 'number') to break down into its prime components.
    """
    def is_valid(self):
        # 1. Execute parent validation to guarantee types match structural blueprints
        if not super().is_valid():
            return False
            
        # Assuming the input key in your schema is named "number"
        target_num = self.runtime_values.get("number to factor")

        if target_num is not None:
            if target_num <= 1:
                self.errors["number"] = "The input number must be a positive integer greater than 1."

        return len(self.errors) == 0

    def evaluate_output(self):
        """
        🎯 COMPUTES PRIME FACTORS MATHEMATICALLY
        Breaks the number down into its prime factors using trial division.
        """
        # Ensure a safe fallback default if unvalidated or missing
        n = self.runtime_values.get("number to factor") if self.runtime_values.get("number to factor") is not None else 12

        # Defensive guard rails
        if n <= 1:
            return ""

        factors = []
        
        # Pull out the factor of 2 first
        while n % 2 == 0:
            factors.append(2)
            n //= 2
            
        # Check odd factors up to the square root of n
        factor = 3
        while factor * factor <= n:
            while n % factor == 0:
                factors.append(factor)
                n //= factor
            factor += 2
            
        # If n is still greater than 1, then the remaining n must be prime
        if n > 1:
            factors.append(n)

        # Format output cleanly as a comma-separated string (e.g., "2, 2, 3")
        return ", ".join(str(f) for f in factors)
    

class FormulaEntity(BaseEntity):
    """
    Validation engine for the 'formula' token pattern.
    """
    def is_valid(self):
        # Run standard property-type checks first
        if not super().is_valid():
            return False

        formula_text = self.cleaned_data.get("formula")
        solve_method = self.cleaned_data.get("solve method")
        solve_for_variable = self.cleaned_data.get("solve for _", "").strip()
        variables_raw = self.cleaned_data.get("variables", "")

        # 1. Rule: Validate cross-field dropdown dependency logic
        if solve_method == "solve for _" and not solve_for_variable:
            self.errors["solve for _"] = "You must provide a variable target when the solve method is configured to 'solve for _'."

        # 2. Rule: Validate variables array mapping layout if provided
        if variables_raw:
            # Clean comma or space-separated variable strings
            var_list = [v.strip() for v in re.split(r"[\s,]+", variables_raw) if v.strip()]
            self.cleaned_data["variables_array"] = var_list

            # 3. Rule: Ensure target solve variable matches declared variable options
            if solve_method == "solve for _" and solve_for_variable not in var_list:
                self.errors["solve for _"] = f"Target variable '{solve_for_variable}' must exist inside the specified variables index list: {var_list}."

        return len(self.errors) == 0
    
    def evaluate_output(self):
        # Placeholder fallback output for raw layout validation formula variables
        return self.cleaned_data.get("formula") or "3*x + 5"


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
        "matrix": MatrixEntity,
        "matrixAnswer": MatrixEntity,
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
