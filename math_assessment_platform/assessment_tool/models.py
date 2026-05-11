# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager #, PermissionsMixin
from django.utils import timezone
import secrets
from datetime import timedelta
from django.db import transaction
from django.db.models.functions import Lower

class MyUserManager(BaseUserManager):
    def _format_user_data(self, gender, first_name, last_name, display_name):
        """Helper to format strings and validate gender."""
        # Gender validation
        gender = gender[0].lower() if gender else 'o'
        if gender not in ['m', 'f', 'o']:
            raise ValueError('Gender must be (m)ale, (f)emale, or (o)ther.')

        # Name formatting helper
        def clean_name(name, required=True):
            name = " ".join(name.split()) if name else ""
            if not name and required:
                raise ValueError("Name values cannot be blank")
            return name.capitalize() if name else None

        return (
            gender,
            clean_name(first_name),
            clean_name(last_name),
            clean_name(display_name, required=False)
        )
    
    def create_user(self, user_email, username, gender, user_first_name, user_last_name, password=None, **extra_fields):
        """The base method used by all other creation methods."""
        if user_email:
            user_email = self.normalize_email(user_email)
        
        # Format names and gender
        gender, f_name, l_name, d_name = self._format_user_data(
            gender, user_first_name, user_last_name, extra_fields.pop('user_display_name', '')
        )

        extra_fields.setdefault('creation_date', timezone.now())

        user = self.model(
            user_email=user_email,
            username=username,
            gender=gender,
            user_first_name=f_name,
            user_last_name=l_name,
            user_display_name=d_name,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_student_user(self, **fields):
        fields.setdefault('user_type', 'Student')
        fields.setdefault('unactivated_account', False)
        fields.setdefault('ongoing_assessment', False)
        fields.setdefault('ban_account', False)
        return self.create_user(**fields)
    
    def create_teacher_user(self, **fields):
        fields.setdefault('user_type', 'Teacher')
        fields.setdefault('unactivated_account', True)
        fields.setdefault('ongoing_assessment', False)
        fields.setdefault('ban_account', False)
        fields.setdefault('user_credit', 0)
        return self.create_user(**fields)

    def create_superuser(self, user_email, username, gender, user_first_name, user_last_name, **extra_fields):
        # IT Support users are required to have an email
        if not user_email:
            raise ValueError('Users must have an email address')
        
        extra_fields.setdefault('user_type', 'IT_Support')
        extra_fields.setdefault('unactivated_account', False)
        extra_fields.setdefault('ongoing_assessment', False)
        extra_fields.setdefault('ban_account', False)
        
        user = self.create_user(
            user_email=user_email,
            username=username,
            gender=gender,
            user_first_name=user_first_name,
            user_last_name=user_last_name,
            **extra_fields
        )
        # user.is_superuser = True

        return user

class UserProfile(AbstractBaseUser): #, PermissionsMixin):
    user_id = models.AutoField(primary_key=True)
    username = models.CharField(unique=True, max_length=255, db_comment='CONSTRAINT check_lowercase_username CHECK (LOWER(username) = username)')
    user_email = models.CharField(unique=True, max_length=255, db_comment='CONSTRAINT check_lowercase_email CHECK (LOWER(user_email) = user_email)')
    password = models.CharField(max_length=255, db_column='user_password')
    user_type = models.TextField()  # This field type is a guess.
    gender = models.CharField(max_length=5, blank=True, null=True, db_comment="CONSTRAINT chk_Gender CHECK (LOWER(Gender) IN ('m', 'f', 'other'));")
    user_first_name = models.CharField(max_length=255, blank=True, null=True)
    user_last_name = models.CharField(max_length=255, blank=True, null=True)
    user_display_name = models.CharField(max_length=255, blank=True, null=True)
    user_credit = models.IntegerField(blank=True, null=True, db_comment='Default is null generally; application logic should set 0 when user_type is Teacher')
    organization = models.CharField(max_length=255, blank=True, null=True)
    creation_date = models.DateTimeField(default=timezone.now, blank=True, null=True)
    unactivated_account = models.BooleanField(blank=True, null=True, db_comment="When an account has a required email that hasn't been verified, then the account is not activated")
    ban_account = models.BooleanField(blank=True, null=True)
    ongoing_assessment = models.BooleanField(blank=True, null=True, db_comment='Use this as a quick check to see if the user is currently ongoing a test')
    last_login = models.DateTimeField(default=timezone.now, blank=True, null=True)
    last_session_key = models.CharField(max_length=40, null=True, blank=True)


    # Link the manager
    objects = MyUserManager()

    # Tell Django which fields to use for login
    USERNAME_FIELD = 'user_email' 
    # Add any other NOT NULL fields here to be prompted in the terminal
    #  (besides USERNAME_FIELD and 'password' which are included by default)
    REQUIRED_FIELDS = ['username', 'gender', 'user_first_name', 'user_last_name']

    @property
    def is_staff(self):
        # Allow IT_Support to access the admin
        return self.user_type in ['IT_Support']

    # You must manually define these properties so Django doesn't crash 
    # when it tries to check permissions in the Admin panel
    @property
    def is_superuser(self):
        return self.user_type == 'IT_Support' # Or however you define a top-level admin

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_superuser

    def save(self, *args, **kwargs):
        # Force username to lowercase before hitting the DB
        if self.username:
            self.username = self.username.lower()
        super().save(*args, **kwargs)

        # Note: The email from the '@' on is forced to lowercase in MyUserManage using 'normalize_email',
        #  but I won't allow a second user to have an email that matches if they are both lowercase

    class Meta:
        managed = False
        db_table = 'user_profile'
        constraints = [
            models.UniqueConstraint(
                Lower('user_email'), 
                name='unique_email_case_insensitive'
            ),
            models.UniqueConstraint(
                Lower('username'), 
                name='unique_username_case_insensitive'
            )
        ]


class QA(models.Model):
    title = models.CharField(max_length=150, blank=True, null=True)
    answer = models.TextField(db_comment='The content could be anything from text to an embedded video')  # This field type is a guess.
    user_restriction_level = models.TextField(blank=True, null=True, db_comment="This identifies which users the Q&A can be seen by. Different users have different Q&A needs. 'null' means publicly viewable.")  # This field type is a guess.
    creation_date = models.DateTimeField()
    modification_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'Q_A'
        db_table_comment = "IT Support->Teacher->Student->Parent->public - In this order the higher tier can view lower tier Q&A.\nI mentioned in the Requirements Document that I will allow 'tags' to be assigned to the Q&A for easier lookup later. I decided now is not the time to implement this."


class Assessment(models.Model):
    course = models.ForeignKey('Course', models.DO_NOTHING, related_name='assessments')
    name = models.CharField(max_length=255)
    order = models.CharField(max_length=100, blank=True, null=True, db_comment="Will only be 'null' if it's the copied version assigned to a student for test taking")
    parent_assessment = models.ForeignKey('self', models.DO_NOTHING, blank=True, null=True, db_comment="Will only exist if it's a version being taken for a student")
    user = models.ForeignKey('UserProfile', models.DO_NOTHING, blank=True, null=True, db_comment="Will only exist if it's a version being taken for a student")
    points_weight = models.FloatField(blank=True, null=True, db_comment='This is used to make the assessment grade for all students be tilted')
    status = models.TextField(blank=True, null=True, db_comment="closed, open, locked, retake available, submitted, active, inactive, upcoming. 'null' means it's not tied to an individual (like a template course)")  # This field type is a guess.
    is_historic = models.BooleanField(db_comment="When 'true' this is used to determine if the assessment is a static, needs to be unchanged, assessment that a Student is specifically assigned to complete with a single static (with concrete, not variable, inputs) answer tied to the problems. When 'false' it determines the assessment has questions with multiple answers tied to the problems.")
    branch_location = models.ForeignKey('BranchGroup', models.DO_NOTHING, db_column='branch_location', db_comment="Just like 'course' this points to a branch location")
    start_time = models.DateTimeField(blank=True, null=True, db_comment="only an available option for the 'parent' assessment")
    end_time = models.DateTimeField(blank=True, null=True, db_comment="only an available option for the 'parent' assessment")
    creation_date = models.DateTimeField(blank=True, null=True)
    modified_date = models.DateTimeField(blank=True, null=True)

    def duplicate_assessment(self, new_course, new_owner):
        """Duplicates the assessment and all its related questions."""
        new_assessment = self
        new_assessment.pk = None
        new_assessment.id = None
        new_assessment.order = self.order
        new_assessment.name = self.name
        new_assessment.course = new_course
        new_assessment.owner = new_owner
        # new_assessment.branch_location = ??
        new_assessment.save()

        # Trigger duplication for all related problems
        for problem in self.problems.all():
            problem.duplicate_problem(new_assessment)
        
        return new_assessment


    class Meta:
        managed = False
        db_table = 'assessment'


class AssessmentOptionGroup(models.Model):
    #  In your PostgreSQL schema, AssessmentOptionGroup has a UNIQUE ("group_num", "choice") constraint. However, group_num on its own is not unique—it repeats for every choice in a group. Django's standard ForeignKey requires the target field to be unique, which is why it’s throwing fields.E311.
    # Since you are keeping managed = False, we can solve this by "lying" to Django about the uniqueness of that field to satisfy the system check, or by adjusting how the relationship is mapped.
    # Change group_num to include unique=True
    # This satisfies the Django check. Because managed = False, 
    # Django won't actually try to change your database.
    group_num = models.IntegerField(unique=True, db_comment='This is designed so there exists a database restriction on choosing more than 1 option of the same group')
    choice = models.IntegerField(db_comment='This is essentially the enum choice')
    description = models.CharField(max_length=1023)
    deprecated = models.BooleanField()

    class Meta:
        managed = False
        db_table = 'assessment_option_group'
        # This is the real database constraint. The 'unique=True' on 'group_num' is fake and doesn't actually apply because managed=False
        unique_together = (('group_num', 'choice'),)
        db_table_comment = "See 'database actions' for list of options. (I added the table name where I specified options.) count-up timer, count-down timer, desmos, lock_on, whiteboard, multiple_choice, synchronize_test, same_questions_for_each_student"


class AssessmentOptions(models.Model):
    assessment = models.ForeignKey('Assessment', models.DO_NOTHING)
    option_type = models.ForeignKey('AssessmentOptionGroup', models.DO_NOTHING, db_column='option_type_id', to_field='group_num', db_comment='Represents the option group to pick from')
    choice = models.IntegerField(db_comment='Represents the sub-option of the specified group')

    class Meta:
        managed = False
        db_table = 'assessment_options'
        unique_together = (('assessment', 'option_type'),)


class AssessmentQuestionGroup(models.Model):
    assessment = models.ForeignKey(Assessment, models.DO_NOTHING)
    order = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    branch_location = models.ForeignKey('BranchGroup', models.DO_NOTHING, db_column='branch_location', db_comment="acts the same way as in 'assessment' and 'course' for the same field")

    class Meta:
        managed = False
        db_table = 'assessment_question_group'


class BranchGroup(models.Model):
    parent = models.ForeignKey('self', models.DO_NOTHING, db_column='parent', blank=True, null=True)
    location = models.CharField(unique=True, max_length=255)
    order = models.CharField(max_length=100, blank=True, null=True)
    owner = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='owner')
    name = models.CharField(max_length=255)
    creation_date = models.DateTimeField(blank=True, null=True)
    modification_date = models.DateTimeField(blank=True, null=True)

    def get_parent_path(self):
        """Returns the path of the folder containing this item."""
        if not self.parent:
            path = f"/Users/"
        else:
            # Recursively get the parent's path and append the parent's name
            path = f"{self.parent.get_parent_path()}{self.parent.name}/"

        return path


    class Meta:
        managed = False
        db_table = 'branch_group'
        db_table_comment = "This is essentially the same thing as a virtual 'folder'."


class ContactUs(models.Model):
    subject = models.CharField(max_length=255)
    contact_purpose = models.TextField()  # This field type is a guess.
    username = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='username', blank=True, null=True)
    respond_to_email = models.CharField(max_length=255)
    first_name = models.CharField(max_length=255, db_comment='So the response knows who to address')
    inquiry = models.TextField()

    class Meta:
        managed = False
        db_table = 'contact_us'


class Course(models.Model):
    image = models.BinaryField(blank=True, null=True)
    status = models.TextField()  # Enum for one of these: 'active', 'template', 'hidden', 'developing', 'closed', 'deleted'
    owner = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='owner')
    short_desc = models.CharField(max_length=255, blank=True, null=True)
    name = models.CharField(max_length=255)
    branch_location = models.ForeignKey(BranchGroup, models.DO_NOTHING, db_column='branch_location', db_comment='Every course, in any form, will create branch directories for all problems. course(id)->assessment(id)->assessment_question_group(id)->problem(id)')
    creation_date = models.DateTimeField(blank=True, null=True)
    version = models.CharField(max_length=100, blank=True, null=True)
    introduction = models.TextField(blank=True, null=True)  # This field type is a guess.

    @classmethod
    def create_developing(cls, owner, name, short_desc):
        """Creates a fresh course with 'developing' status."""
        return cls.objects.create(
            owner=owner,
            status="developing",
            name=name,
            short_desc=short_desc,
            # version-> firstnumber+1.0.0.0
        )

    def duplicate_course(self, new_owner, new_status):
        """Duplicates the course and all its related assessments."""
        with transaction.atomic():
            new_course = self
            new_course.pk = None
            new_course.id = None
            new_course.owner = new_owner
            new_course.status = new_status
            new_course.short_desc = self.short_desc
            new_course.introduction = self.introduction
            # new_course.version = # It's different depending on the status that it gets changed to. Incorporate later
            new_course.course_name = f"Copy of {self.course_name}"
            new_course.save()

            # Trigger duplication for all related assessments
            for assessment in self.assessments.all():
                assessment.duplicate_assessment(new_course, new_owner)
            
            return new_course

    class Meta:
        managed = False
        db_table = 'course'


class CourseDefaultAssessmentOptions(models.Model):
    course = models.ForeignKey(Course, models.DO_NOTHING)
    option_type = models.ForeignKey(AssessmentOptionGroup, models.DO_NOTHING, db_column='option_type_id', to_field='group_num')
    choice = models.IntegerField(db_comment='Represents the sub-section of the specified option group')
    default_setting = models.BooleanField()

    class Meta:
        managed = False
        db_table = 'course_default_assessment_options'
        db_table_comment = "I didn't add a method to allow only a single student to view historic, this setting is for the whole class of students that can be toggled on and off."


class CqdPair(models.Model):
    parent_aqd = models.ForeignKey('CustomQuestionDistribution', models.DO_NOTHING)
    branch = models.ForeignKey(BranchGroup, models.DO_NOTHING, blank=True, null=True)
    problem = models.ForeignKey('Problem', models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'cqd_pair'
        db_table_comment = "Identifies the list of rows by ID that the cqd table is using.\nNote: It's possible to have a circular loop if for some reason the aqg_id identifies a folder at a higher level than the cqd, perhaps put a restriction somewhere that only allows sub folders/problems to get added. (This could be a database restriction using 'constraint', but it sounds complicated and I think I'd rather program it in the javascript).. just be aware it's a problem"


class CustomQuestionDistribution(models.Model):
    assigned_folder = models.ForeignKey(BranchGroup, models.DO_NOTHING, db_column='assigned_folder')
    suggested_count = models.IntegerField()

    def get_unique_name(self):
        # Check if 'num_pairs' was already calculated by the view
        # if not (e.g., in the admin panel), fall back to a standard count
        num = getattr(self, 'num_pairs', self.cqdpair.count())
        return f"ID ({self.id}) - Count = {num}"

    class Meta:
        managed = False
        db_table = 'custom_question_distribution'


class EmailAuthentication(models.Model):
    u = models.ForeignKey('UserProfile', models.DO_NOTHING, blank=True, null=True)
    temp_email = models.CharField(unique=True, max_length=255, db_comment='CONSTRAINT check_lowercase_email CHECK (LOWER(temp_email) = temp_email)')
    code = models.CharField(max_length=255, db_comment='This gets generated per user when email is changed originally. User is emailed, and needs to return the code for verification')
    timeout = models.DateTimeField()

    @classmethod
    def generate_auth_record(cls, user, email):
        # Normalize the email (lowercase domain, etc.)
        normalized_email = BaseUserManager.normalize_email(email)

        with transaction.atomic():
            # 1. Delete any existing codes for this user to prevent clutter
            cls.objects.filter(u_id=user.user_id).delete()
            
            # 2. Create the new record
            return cls.objects.create(
                u_id=user.user_id,
                temp_email=normalized_email,
                code=secrets.token_urlsafe(20), # Randomized string
                timeout=timezone.now() + timedelta(minutes=60)
            )

    class Meta:
        managed = False
        db_table = 'email_authentication'
        constraints = [
            models.UniqueConstraint(
                Lower('temp_email'), 
                name='unique_temp_email_case_insensitive'
            )
        ]


class EntitySegment(models.Model):
    default_answer = models.BooleanField(db_comment='When true, this will make this student interactable answer type shown by default when solving the problem')
    points = models.FloatField(blank=True, null=True)
    problem = models.ForeignKey('Problem', models.DO_NOTHING, blank=True, null=True)
    problem_type_id_originator = models.ForeignKey('EntityType', models.DO_NOTHING, db_column='problem_type_id_originator')
    content = models.TextField()  # This field type is a guess.
    parent_entity = models.ForeignKey('self', models.DO_NOTHING, db_column='parent_entity', blank=True, null=True, db_comment='The parent entity of the self entity. I will keep track of entity segments separately to make it easy to prevent circular entity recursion')
    is_answer_to_multi_choice = models.BooleanField(blank=True, null=True, db_comment="This marks the child (self) entity as a correct answer choice or not. When 'null', it means the entity is not a 'choice' option (multiple choice/checkbox/radio/dropdown/custom/etc). Should add a constraint to make sure the parent_entity.problem_type_id_originator.name is one of the allowed options if this is null.")
    space_allocation = models.TextField(blank=True, null=True)  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'entity_segment'
        db_table_comment = "I no longer need a 'entity_num' or 'entity_tag_list' field to track the entity string tag. I am keeping this info in the 'content' json under 'entity_name_list'"


class EntityType(models.Model):
    name = models.CharField(unique=True, max_length=255)
    format_pattern = models.TextField(db_comment="This will be an html section with the <<childEntity>> inside the string in various places. There will also be a <<addOptionButton>> if applicable, which will add the 'insert_entity_pattern' into the designated <<patternInsert>> location. I used <<element>> as an example, but the json actually stores a json array list")  # This field type is a guess.
    insert_entity_pattern = models.TextField(db_comment="Uses exact strings existing in the 'problem_type' name columns. If I don't use exact names, it won't work right.")  # This field type is a guess.
    entity_name_list = models.TextField()  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'entity_type'
        db_table_comment = "This table will be populated with all of the variations of problem categories that a problem can have a student provide an answer for. Examples include: problem, number, string, formula, paragraph_block, radio_selection, checkbox_selection, dropdown_selection, matrix, unordered_list, etc. Also includes: 'formula_prompt', 'number_prompt', 'paragraph_prompt', 'string_prompt'"


class EntityUserInput(models.Model):
    entity = models.ForeignKey(EntitySegment, models.DO_NOTHING)
    points_score = models.FloatField(blank=True, null=True, db_comment="Score can be initially set to 'null' if it requires Teacher to do the grading.")
    content = models.TextField(blank=True, null=True, db_comment='Depending on the entity_type that is tied to the entity_segment, how the json is read as information will change. It is a good idea to consistently organize all data as a json though. This could be a string, an image (canvas/graph), a series of data representing a canvas/graph, a number/float, a formula, etc')  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'entity_user_input'
        db_table_comment = 'The json will identify the difference between a student answer to the question, a calculated answer, or just an entity calculation that sets up the problem'


class FinalGradeCalculation(models.Model):
    course = models.ForeignKey(Course, models.DO_NOTHING)
    weight = models.IntegerField()
    user = models.ForeignKey('UserProfile', models.DO_NOTHING)
    assessment = models.ForeignKey(Assessment, models.DO_NOTHING, blank=True, null=True, db_comment="Will only be 'null' if the 'delete: set null' activates")
    assessment_grade_points = models.FloatField(blank=True, null=True, db_comment='This identifies the numeric score of a given assessment for the student')
    assessment_grade_max_points = models.FloatField(blank=True, null=True, db_comment='This identifies the maximum possible score of a given assessment for a student')

    class Meta:
        managed = False
        db_table = 'final_grade_calculation'
        db_table_comment = 'I primarily intend this table to be used as a source of obtaining the grades after the course has been closed. The assessment and course can be deleted, but the grades will remain.'


class Invoice(models.Model):
    user = models.ForeignKey('UserProfile', models.DO_NOTHING, blank=True, null=True)
    invoice_number = models.CharField(unique=True, max_length=100)
    status = models.TextField()  # This field type is a guess.
    issue_date = models.DateField()
    due_date = models.DateField(blank=True, null=True)
    currency = models.CharField(max_length=10)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.CharField(max_length=1024, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'invoice'


class LoginLogs(models.Model):
    u = models.ForeignKey('UserProfile', models.DO_NOTHING)
    log_entry = models.TextField()  # This field type is a guess.
    state = models.BooleanField(blank=True, null=True, db_comment="For login attempts, this will be marked 'true' for successful login or 'false' for unsuccessful login attempts")
    notes = models.TextField(blank=True, null=True)
    entry_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'login_logs'


class Notification(models.Model):
    receiver = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='receiver')
    content = models.TextField(blank=True, null=True)  # This field type is a guess.
    creation_date = models.DateTimeField(blank=True, null=True)
    title = models.CharField(max_length=255)
    sender = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='sender', related_name='notification_sender_set', blank=True, null=True)
    send_on = models.DateTimeField(blank=True, null=True)
    expr_date = models.DateTimeField(blank=True, null=True, db_comment='If there is a system update for instance, no need to still bring this notification to attention after the update has been scheduled to be completed.')
    reason = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'notification'


class OpenStudentAssessmentOverwrite(models.Model):
    a = models.OneToOneField(Assessment, models.DO_NOTHING, primary_key=True, db_comment='assessment.id')  # The composite primary key (a_id, u_id) found, that is not supported. The first column is selected.
    u = models.ForeignKey('UserProfile', models.DO_NOTHING, db_comment='user_profile.id')
    status_open = models.BooleanField(blank=True, null=True, db_comment="true means 'open', false means 'closed'")

    class Meta:
        managed = False
        db_table = 'open_student_assessment_overwrite'
        unique_together = (('a', 'u'),)
        db_table_comment = 'There should only be a Student user id in this table. This is for when a Teacher opens an assessment for a single Student rather than the whole class.'


class ParentUserCourse(models.Model):
    student = models.OneToOneField(UserProfile, models.DO_NOTHING, primary_key=True)  # The composite primary key (student_id, parent_id, course_id) found, that is not supported. The first column is selected.
    parent = models.ForeignKey(UserProfile, models.DO_NOTHING, related_name='parentusercourse_parent_set')
    course = models.ForeignKey(Course, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'parent_user_course'
        unique_together = (('student', 'parent', 'course'),)
        db_table_comment = "Table used to identify that a parent can see their kid's grades for a particular course"


class PermissionGroup(models.Model):
    name = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = 'permission_group'
        db_table_comment = 'Simply creates virtual groups that a set of permissions can apply to. For instance, to mass enable certain folder access by adding a user to the permission group.'


class Problem(models.Model):
    aqg = models.ForeignKey(AssessmentQuestionGroup, models.DO_NOTHING, blank=True, null=True, db_comment='If aqg_id is not null, then it points to the assessment_question_group that is part of an assessment')
    cqd = models.ForeignKey(CustomQuestionDistribution, models.DO_NOTHING, blank=True, null=True, db_comment='if cqd_id is not null, then it points to the custom_question_distribution that contains a list of problems that it will randomize from')
    branch_location = models.ForeignKey(BranchGroup, models.DO_NOTHING, db_column='branch_location', db_comment="Will always have a branch location. If 'aqg_id' is null, then it's an isolated problem, if 'aqg_is' is not null, then it's part of a course->problem branch")
    problem_status = models.TextField()  # This field type is a guess.
    title = models.CharField(max_length=255)

    def duplicate_problem(self, new_assessment):
        """Duplicates the problem and all its related options."""
        new_problem = self
        new_problem.pk = None
        new_problem.id = None
        new_problem.assessment = new_assessment
        new_problem.save()

        # Trigger duplication for all related multiple-choice options
        for option in self.options.all():
            option.duplicate_option(new_problem)
            
        return new_problem

    class Meta:
        managed = False
        db_table = 'problem'
        db_table_comment = 'It is possible for both aqg_id and cqd_id to be null or not null at the same time since they can fulfill both roles simultaneously'


class ProblemCategories(models.Model):
    problem_tag = models.OneToOneField('ProblemTags', models.DO_NOTHING, db_column='problem_tag', primary_key=True)  # The composite primary key (problem_tag, problem_id) found, that is not supported. The first column is selected.
    problem = models.ForeignKey(Problem, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'problem_categories'
        unique_together = (('problem_tag', 'problem'),)


class ProblemTags(models.Model):
    name = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = 'problem_tags'
        db_table_comment = "List (perhaps large list) of tag names associated with a problem that can be used later to filter problems. This could be anything from 'generated problem' to 'points above 5' to 'matrix'/'multiple choice'"


class QuestionBlock(models.Model):
    problem = models.ForeignKey(Problem, models.DO_NOTHING)
    content = models.TextField(db_comment="This is the main paragraph content the question resides in. The content can hold 'answer' insert tag entities that will replace the inner data with other things later compiled.")  # This field type is a guess.
    space_allocation = models.TextField(blank=True, null=True)  # This field type is a guess.

    class Meta:
        managed = False
        db_table = 'question_block'


class QuestionGroupFilters(models.Model):
    assessment_question_group = models.OneToOneField(AssessmentQuestionGroup, models.DO_NOTHING, primary_key=True)  # The composite primary key (assessment_question_group_id, question_type_id) found, that is not supported. The first column is selected.
    question_type = models.ForeignKey('QuestionType', models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'question_group_filters'
        unique_together = (('assessment_question_group', 'question_type'),)


class QuestionType(models.Model):
    name = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = 'question_type'
        db_table_comment = "This will be a large table of 'tags' covering all sorts of subjects. It could be as high level as 'calculus', 'trig', or other levels like 'linear', 'factoring' 'matrix', 'integral' 'derivative', etc. It will be used to filter types of math problems. (and see how many of each type of question reside inside the group)"


class SubscriptionTransactions(models.Model):
    transaction_id = models.CharField(primary_key=True, max_length=255, db_comment='Unique ID from payment provider')
    subscription = models.ForeignKey('Subscriptions', models.DO_NOTHING, blank=True, null=True)
    user = models.ForeignKey('UserProfile', models.DO_NOTHING)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10)
    status = models.CharField(max_length=50)
    transaction_type = models.CharField(max_length=50, blank=True, null=True)
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    payment_date = models.DateTimeField(blank=True, null=True)
    notes = models.CharField(max_length=1024, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'subscription_transactions'


class Subscriptions(models.Model):
    user = models.OneToOneField('UserProfile', models.DO_NOTHING)
    status = models.CharField(max_length=20, db_comment='active, canceled, past_due')
    subscription_id = models.CharField(unique=True, blank=True, null=True, db_comment='e.g., sub_456')
    customer_id = models.CharField(unique=True, blank=True, null=True, db_comment='e.g., cus_abc123')
    default_payment_method_id = models.CharField(blank=True, null=True, db_comment='e.g., pm_xyz789')
    total_credits_purchased = models.IntegerField(blank=True, null=True)
    current_period_start = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True, db_comment='When credits might renew')
    auto_renew = models.BooleanField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'subscriptions'


class Ticket(models.Model):
    status = models.TextField(blank=True, null=True)  # This field type is a guess.
    title = models.CharField(max_length=255)
    contact_purpose = models.TextField()  # This field type is a guess.
    username = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='username', blank=True, null=True)
    respond_to_email = models.CharField(max_length=255)
    first_name = models.CharField(max_length=255, db_comment='So the response knows who to address')
    assigned_to = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='assigned_to', related_name='ticket_assigned_to_set', blank=True, null=True, db_comment='This would be an IT Support user')
    creation_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'ticket'
        db_table_comment = "Might want to add a 'tags' field when I actually implement this"


class TicketDiscussion(models.Model):
    commentor_email = models.CharField(max_length=255)
    ticket_reference = models.ForeignKey(Ticket, models.DO_NOTHING)
    comment = models.TextField()  # This field type is a guess.
    creation_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ticket_discussion'
        db_table_comment = 'Essentially the chat history for a given ticket'


class UserCourseActivation(models.Model):
    course = models.ForeignKey(Course, models.DO_NOTHING)
    slot = models.ForeignKey('UsersInCourse', models.DO_NOTHING, db_comment='This represents the Class slot the Teacher made available')
    temp_email = models.CharField(unique=True, max_length=255, db_comment='CONSTRAINT check_lowercase_email CHECK (LOWER(temp_email) = temp_email)')
    code = models.CharField(max_length=255, db_comment='This gets generated per user when email is changed originally. User is emailed, and needs to return the code for verification')
    timeout = models.DateTimeField(db_comment='Perhaps there is no timeout here')

    class Meta:
        managed = False
        db_table = 'user_course_activation'
        unique_together = (('course', 'temp_email', 'slot'),)


class UserPermissionGroup(models.Model):
    user = models.OneToOneField(PermissionGroup, models.DO_NOTHING, primary_key=True)  # The composite primary key (user_id, pg_id) found, that is not supported. The first column is selected.
    pg_id = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'user_permission_group'
        unique_together = (('user', 'pg_id'),)
        db_table_comment = 'Pairs users with groups. It will show they have respective permissions the given group has.'


class UsersGroup(models.Model):
    branch = models.ForeignKey(BranchGroup, models.DO_NOTHING)
    user = models.ForeignKey(UserProfile, models.DO_NOTHING, blank=True, null=True, db_comment='This or permission_group need to be specified')
    permission_group = models.ForeignKey(PermissionGroup, models.DO_NOTHING, db_column='permission_group', blank=True, null=True, db_comment='This or user_id need to be specified')
    permissions = models.TextField()  # This field type is a guess.
    creation_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'users_group'
        unique_together = (('branch', 'user'),)
        db_table_comment = "This is essentially the same thing as a permission list per 'branch_group' folder"


class UsersInCourse(models.Model):
    user = models.ForeignKey(UserProfile, models.DO_NOTHING, blank=True, null=True, db_comment="If it is 'null', then it will show up as a Student Slot for the Teacher's view")
    course = models.ForeignKey(Course, models.DO_NOTHING)
    user_access = models.TextField()  # This field type is a guess.
    creation_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'users_in_course'
        unique_together = (('user', 'course'),)
        db_table_comment = 'If a user is listed in this table, then they automatically are assigned to the course. Teachers will show up as Teachers, Students will show up as Students.'


from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=UserProfile)
def create_user_folder_structure(sender, instance, created, **kwargs):
    if created:
        # 1. Create the Master Root Folder
        root = BranchGroup.objects.create(
            name=instance.username,
            owner=instance,
            parent=None,
            location=f"{instance.username}_root",
        )

        # 2. Define the default sub-folders
        default_folders = ['courses', 'assessments', 'standalone problems']

        # 3. Create each sub-folder nested under the root
        for folder_name in default_folders:
            BranchGroup.objects.create(
                name=folder_name,
                owner=instance,
                parent=root,
                location=f"{instance.username}/{folder_name.replace(' ', '_')}",
            )
