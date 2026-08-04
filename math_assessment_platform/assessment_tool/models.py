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
from django.dispatch import receiver
from imagekit.models import ProcessedImageField
from imagekit.processors import ResizeToFill
import os
import uuid
from .util import clone_node_recursive, get_course_image_path, assign_user_to_course, generate_unique_course_version


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

    def create_parent_user(self, **fields):
        fields.setdefault('user_type', 'Parent')
        fields.setdefault('unactivated_account', True)
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


class _PsycopgJSONField(models.JSONField):
    """JSONField that tolerates psycopg returning already-decoded dict/list."""

    def from_db_value(self, value, expression, connection):
        if isinstance(value, (dict, list)):
            return value
        return super().from_db_value(value, expression, connection)


class QA(models.Model):
    title = models.CharField(max_length=150, blank=True, null=True)
    answer = _PsycopgJSONField(
        db_comment='The content could be anything from text to an embedded video',
    )
    user_restriction_level = models.TextField(
        blank=True,
        null=True,
        db_comment=(
            "This identifies which users the Q&A can be seen by. Different users "
            "have different Q&A needs. 'null' means publicly viewable."
        ),
    )
    creation_date = models.DateTimeField()
    modification_date = models.DateTimeField()
    view_count = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'Q_A'
        db_table_comment = (
            "IT Support->Teacher->Student->Parent->public - In this order the "
            "higher tier can view lower tier Q&A. Tags live in qa_tag / "
            "qa_tag_assignment for lookup and filtering."
        )


class QaTag(models.Model):
    name = models.CharField(max_length=64)

    class Meta:
        managed = False
        db_table = 'qa_tag'


class QaTagAssignment(models.Model):
    id = models.AutoField(primary_key=True)
    qa = models.ForeignKey(
        QA,
        models.DO_NOTHING,
        db_column='qa_id',
        related_name='tag_assignments',
    )
    tag = models.ForeignKey(
        QaTag,
        models.DO_NOTHING,
        db_column='tag_id',
        related_name='article_assignments',
    )

    class Meta:
        managed = False
        db_table = 'qa_tag_assignment'
        unique_together = (('qa', 'tag'),)


class Assessment(models.Model):
    course = models.ForeignKey(
        'Course',
        models.DO_NOTHING,
        related_name='assessments',
        blank=True,
        null=True,
        db_comment=(
            'Course this assessment belongs to. NULL for standalone library '
            'assessments (Workspace / shared) that are not student-facing until '
            'attached to a course.'
        ),
    )
    name = models.CharField(max_length=255)
    order = models.CharField(max_length=100, blank=True, null=True, db_comment="Will only be 'null' if it's the copied version assigned to a student for test taking")
    parent_assessment = models.ForeignKey('self', models.DO_NOTHING, blank=True, null=True, db_comment="Will only exist if it's a version being taken for a student")
    user = models.ForeignKey('UserProfile', models.DO_NOTHING, blank=True, null=True, db_comment="Will only exist if it's a version being taken for a student")
    points_weight = models.FloatField(blank=True, null=True, db_comment='Legacy tilt multiplier; prefer grade_weight / curve bonus setting')
    grade_weight = models.FloatField(
        default=1,
        db_comment='Relative weight for percent-of-final-grade course totals. 0 excludes the assessment.',
    )
    curve_max_points = models.FloatField(
        default=0,
        db_comment='Bonus points added to every recorded student grade for this assessment.',
    )
    time_limit_minutes = models.IntegerField(
        blank=True,
        null=True,
        db_comment='Allotted minutes when forcibly-end countdown option is active.',
    )
    status = models.TextField(blank=True, null=True, db_comment="Postgres enum assessment_status_enum: closed | open | upcoming | hidden (teacher lifecycle); deleted (trash).")  # This field type is a guess.
    is_historic = models.BooleanField(db_comment="When 'true' this is used to determine if the assessment is a static, needs to be unchanged, assessment that a Student is specifically assigned to complete with a single static (with concrete, not variable, inputs) answer tied to the problems. When 'false' it determines the assessment has questions with multiple answers tied to the problems.")
    branch_location = models.OneToOneField('BranchGroup', models.CASCADE, db_column='branch_location', related_name='assessment', db_comment="Just like 'course' this points to a branch location")
    start_time = models.DateTimeField(blank=True, null=True, db_comment="only an available option for the 'parent' assessment")
    end_time = models.DateTimeField(blank=True, null=True, db_comment="only an available option for the 'parent' assessment")
    creation_date = models.DateTimeField(blank=True, null=True)
    modified_date = models.DateTimeField(blank=True, null=True)
    scores_released = models.BooleanField(
        default=False,
        db_comment='When true, students may see scores for this assessment (teacher release).',
    )
    scores_released_at = models.DateTimeField(blank=True, null=True)
    student_release_mode = models.CharField(
        max_length=32,
        default='hidden',
        db_comment='hidden | scores_only | full_review',
    )
    counts_toward_grade = models.BooleanField(
        default=True,
        db_comment='When false, score may be visible but excluded from course totals.',
    )

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
        db_table_comment = "Growable enum of assessment settings. Active groups: student view, course total, retake scoring, timers, lock on focus, synchronize tests, curve."


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
    branch_location = models.OneToOneField('BranchGroup', models.CASCADE, db_column='branch_location', related_name='aqg', db_comment="acts the same way as in 'assessment' and 'course' for the same field")

    class Meta:
        managed = False
        db_table = 'assessment_question_group'


class BranchGroup(models.Model):
    class FolderType(models.TextChoices):
        FOLDER = 'folder', 'Folder'
        COURSE = 'course', 'Course'
        ASSESSMENT = 'assessment', 'Assessment'
        CQD = 'cqd', 'Custom Question Distribution'
        AQG = 'aqg', 'Assessment Question Group'
    
    parent = models.ForeignKey('self', models.CASCADE, db_column='parent', blank=True, null=True, related_name='children')
    order = models.CharField(max_length=100, blank=True, null=True)
    owner = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='owner')
    name = models.CharField(max_length=255)
    folder_type = models.CharField(max_length=20,choices=FolderType.choices,default=FolderType.FOLDER)
    creation_date = models.DateTimeField(blank=True, null=True)
    modification_date = models.DateTimeField(blank=True, null=True)
    # Tracking fields for the Restore Engine
    previous_parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='historical_children')
    previous_status = models.CharField(max_length=50, null=True, blank=True)
    trashed_at = models.DateTimeField(blank=True, null=True, db_comment='Set when moved to Trash; cleared on restore. Used for 30-day purge.')
    share_group = models.ForeignKey(
        'PermissionGroup',
        models.DO_NOTHING,
        db_column='share_group_id',
        blank=True,
        null=True,
        related_name='share_roots',
        db_comment='When set, this branch is a share root linked to a permission_group.',
    )

    def get_parent_path(self):
        """Returns the path of the folder containing this item."""
        if not self.parent:
            path = f"/Users/"
        else:
            # Recursively get the parent's path and append the parent's name
            path = f"{self.parent.get_parent_path()}{self.parent.name}/"

        return path

    @property
    def linked_object(self):
        if self.folder_type == self.FolderType.COURSE:
            return getattr(self, 'course', None)
        if self.folder_type == self.FolderType.ASSESSMENT:
            return getattr(self, 'assessment', None)
        if self.folder_type == self.FolderType.CQD:
            return getattr(self, 'cqd', None)
        if self.folder_type == self.FolderType.AQG:
            return getattr(self, 'aqg', None)
        # or 'folder' = none, since there is no required linked table for this one
        return None


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
    creation_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'contact_us'



class Course(models.Model):
    # TODO: use the ProcessedImageField, description here: https://pypi.org/project/django-imagekit/
    # image = models.BinaryField(blank=True, null=True)
    # ProcessedImageField will resize the image to 400x400 and compress it to 90% quality
    image = ProcessedImageField(
        upload_to=get_course_image_path,
        processors=[ResizeToFill(400, 400)],
        format='JPEG',
        options={'quality': 90},
        blank=True, 
        null=True
    )
    status = models.TextField()  # Enum for one of these: 'active', 'template', 'hidden', 'developing', 'closed', 'deleted'
    owner = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='owner')
    short_desc = models.CharField(max_length=255, blank=True, null=True)
    name = models.CharField(max_length=255)
    branch_location = models.OneToOneField(BranchGroup, models.CASCADE, db_column='branch_location', related_name='course', db_comment='Every course, in any form, will create branch directories for all problems. course(id)->assessment(id)->assessment_question_group(id)->problem(id)')
    creation_date = models.DateTimeField(blank=True, null=True)
    close_date = models.DateTimeField(
        blank=True,
        null=True,
        db_comment=(
            "Scheduled/actual course close time. Intended to be maintained as "
            "12 months after the most recent student enrollment change."
        ),
    )
    version = models.CharField(max_length=100, blank=True, null=True, unique=True)
    introduction = models.TextField(blank=True, null=True)
    grade_aggregation_mode = models.CharField(
        max_length=32,
        default='equal_weight',
        db_comment='equal_weight | sum_points — course total calculation for student grades.',
    )
    default_time_limit_minutes = models.IntegerField(
        blank=True,
        null=True,
        db_comment='Default allotted minutes for forcibly-end countdown when assessments do not override.',
    )

    @classmethod
    def create_developing(cls, owner, name, short_desc, image_file=None):
        """Creates a fresh course with 'developing' status and associated folder."""
        
        # 1. Generate correct version for the 'developing' course: #.#.#.#
        # e.g., 6.0.0.1
        # <subject>.<template ID>.<template version>.<course copy number>
        name = " ".join(name.strip().split())
        version_str = generate_unique_course_version(dest_status='developing')

        # 2. Locate the "Courses" parent folder
        # Assuming root is /Users/username_root/ and Courses is a subfolder
        try:
            # We look for the folder named 'Courses' owned by this user
            # that lives directly under the user's root.
            courses_parent = BranchGroup.objects.get(
                name='Courses', 
                owner=owner,
                parent__name=f"{owner.username}_root" 
            )
        except BranchGroup.DoesNotExist:
            raise ValueError('The Courses folder under the user root directory must exist! Contact support for help.')

        # 3. Create the BranchGroup for this specific course
        # We set folder_type to 'course' as per your new Enum design
        new_folder = BranchGroup.objects.create(
            owner=owner,
            name=name,
            parent=courses_parent,
            folder_type="course",
            order=name            # Ensuring alphabetical sorting works
        )

        # 4. Create and return the Course
        return cls.objects.create(
            owner=owner,
            status="developing",
            name=name,
            short_desc=short_desc,
            version=version_str,
            branch_location=new_folder,
            image=image_file,
            creation_date=timezone.now()
        )

    def duplicate_course(self, user, target_transition):
        with transaction.atomic():
            username = user.username
            courses_root_folder = BranchGroup.objects.get(
                name='Courses', 
                parent__name=f"{username}_root"
            )

            user_type = user.user_type

            # Determine resulting status configuration based on transition choice
            resulting_status = 'active'
            if target_transition == 'developing_to_template':
                resulting_status = 'template'


            # Run your recursive duplicating logic engine setup
            context = {'course': None, 'assessment': None, 'aqg': None, 'cqd': None}
            
            # 1. Duplicate Folder Structure
            new_folder = clone_node_recursive(
                self.branch_location, 
                courses_root_folder, 
                user, 
                context,
                starter_node=True,
            )

            # 2. Update the cloned payload attributes
            new_course = new_folder.course
            new_course.status = resulting_status
            new_course.name = new_folder.name #f"Copy of {self.name}"
            new_course.owner = user
            new_course.version = generate_unique_course_version(dest_status=resulting_status, source_course=self)
            new_course.save()


            if not (target_transition == 'developing_to_template'):
                # if a new course was successfully made, then I need to add the 
                #   Teacher to the users_in_course table, but only if the new
                #   course is an 'active' course, this does not apply to 
                #   developing -> new template
                # This only applies to 
                #   closed-> new active OR 
                #   template -> new active
                assign_user_to_course(user, new_course)
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
    DEFAULT_NAME = "Problem Set"

    assigned_folder = models.OneToOneField(BranchGroup, on_delete=models.CASCADE, db_column='assigned_folder', related_name='cqd')
    suggested_count = models.IntegerField()
    name = models.CharField(max_length=255, default=DEFAULT_NAME)

    def get_unique_name(self):
        """Internal branch_group folder label (must stay unique-ish in explorer trees)."""
        label = (self.name or self.DEFAULT_NAME).strip() or self.DEFAULT_NAME
        if self.id:
            return f"{label} ({self.id})"
        return label

    def get_display_name(self):
        label = (self.name or "").strip()
        return label or self.DEFAULT_NAME

    def get_problem_pool_count(self):
        """Number of concrete problems currently inside this problem set."""
        if hasattr(self, "num_pairs"):
            try:
                return int(self.num_pairs or 0)
            except (TypeError, ValueError):
                return 0
        if not self.assigned_folder_id:
            return 0
        try:
            return self.assigned_folder.children.filter(folder_type="problem").count()
        except Exception:
            return 0

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


class PasswordResetRequest(models.Model):
    u = models.ForeignKey(
        'UserProfile',
        models.DO_NOTHING,
        db_column='u_id',
        related_name='password_reset_requests',
    )
    code = models.CharField(max_length=255, unique=True)
    timeout = models.DateTimeField()
    creation_date = models.DateTimeField(blank=True, null=True)
    requested_identifier = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'password_reset_request'
        db_table_comment = (
            'Pending forgot-password tokens. Deleted on successful reset, '
            'login, or replacement request.'
        )


class EntitySegment(models.Model):
    default_answer = models.BooleanField(db_comment='When true, this will make this student interactable answer type shown by default when solving the problem')
    points = models.FloatField(blank=True, null=True)
    problem = models.ForeignKey('Problem', models.CASCADE, blank=True, null=True)
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
    entity_name_list = models.TextField() 

    class Meta:
        managed = False
        db_table = 'entity_type'
        db_table_comment = "This table will be populated with all of the variations of problem categories that a problem can have a student provide an answer for. Examples include: problem, number, string, formula, paragraph_block, radio_selection, checkbox_selection, dropdown_selection, matrix, unordered_list, etc. Also includes: 'formula_prompt', 'number_prompt', 'paragraph_prompt', 'string_prompt'"


class AssessmentGenerationJob(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETE = 'complete'
    STATUS_FAILED = 'failed'

    assessment = models.ForeignKey(Assessment, models.DO_NOTHING, db_column='assessment_id')
    status = models.CharField(max_length=16, default=STATUS_PENDING)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    total_students = models.IntegerField(default=0)
    completed_students = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = 'assessment_generation_job'


class AssessmentSynchronizedForm(models.Model):
    assessment = models.ForeignKey(
        Assessment,
        models.CASCADE,
        db_column='assessment_id',
        related_name='synchronized_forms',
    )
    attempt_number = models.IntegerField()
    cohort_number = models.IntegerField()
    blueprint_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    is_current = models.BooleanField(default=True)
    unsynchronized_history_acknowledged_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        'UserProfile',
        models.SET_NULL,
        db_column='created_by_id',
        blank=True,
        null=True,
    )
    creation_date = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = 'assessment_synchronized_form'
        unique_together = (('assessment', 'attempt_number', 'cohort_number'),)
        constraints = [
            models.CheckConstraint(
                check=models.Q(attempt_number__gte=1),
                name='assessment_sync_form_attempt_number_check',
            ),
            models.CheckConstraint(
                check=models.Q(cohort_number__gte=1),
                name='assessment_sync_form_cohort_number_check',
            ),
            models.UniqueConstraint(
                fields=('assessment', 'attempt_number'),
                condition=models.Q(is_current=True),
                name='uq_assessment_sync_form_current',
            ),
        ]


class AssessmentSynchronizedProblem(models.Model):
    synchronized_form = models.ForeignKey(
        AssessmentSynchronizedForm,
        models.CASCADE,
        db_column='synchronized_form_id',
        related_name='problems',
    )
    slot_index = models.IntegerField()
    section_name = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    source_problem_id = models.IntegerField(blank=True, null=True)
    body_html = models.TextField()
    render_payload = models.JSONField(default=dict)
    answer_key = models.JSONField(default=dict)
    answer_fields = models.JSONField(default=list)
    max_points = models.FloatField(default=0)

    class Meta:
        managed = False
        db_table = 'assessment_synchronized_problem'
        unique_together = (('synchronized_form', 'slot_index'),)


class StudentCourseEnrollment(models.Model):
    """One enrollment stint for a student in a course; survives kick/finish for grade history."""

    STATUS_ACTIVE = 'active'
    STATUS_ENDED = 'ended'

    END_REASON_KICKED = 'kicked'
    END_REASON_COMPLETED = 'completed'
    END_REASON_COURSE_CLOSED = 'course_closed'

    user = models.ForeignKey('UserProfile', models.DO_NOTHING)
    course = models.ForeignKey(Course, models.DO_NOTHING)
    status = models.CharField(max_length=16, default=STATUS_ACTIVE)
    end_reason = models.CharField(max_length=64, blank=True, null=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(blank=True, null=True)
    slot = models.ForeignKey(
        'UsersInCourse',
        models.DO_NOTHING,
        blank=True,
        null=True,
        db_comment='Optional link to the current users_in_course seat while status=active',
    )

    class Meta:
        managed = False
        db_table = 'student_course_enrollment'
        db_table_comment = (
            'One row per student enrollment stint in a course. Survives kick/finish so grades '
            'can be scoped to that instance. users_in_course remains the current seat/slot only.'
        )


class StudentAssessmentAttempt(models.Model):
    STATUS_READY = 'ready'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_SUBMITTED = 'submitted'

    user = models.ForeignKey('UserProfile', models.DO_NOTHING, db_column='user_id')
    enrollment = models.ForeignKey(
        StudentCourseEnrollment, models.DO_NOTHING, db_column='enrollment_id'
    )
    assessment = models.ForeignKey(
        Assessment, models.DO_NOTHING, db_column='assessment_id', blank=True, null=True
    )
    course = models.ForeignKey(Course, models.DO_NOTHING, db_column='course_id')
    status = models.CharField(max_length=16, default=STATUS_READY)
    started_at = models.DateTimeField(blank=True, null=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    auto_graded_at = models.DateTimeField(blank=True, null=True)
    earned_points = models.FloatField(blank=True, null=True)
    max_points = models.FloatField(blank=True, null=True)
    original_earned_points = models.FloatField(
        blank=True,
        null=True,
        db_comment='Earned points before teacher attempt-level adjustment.',
    )
    original_max_points = models.FloatField(
        blank=True,
        null=True,
        db_comment='Max points before teacher attempt-level adjustment.',
    )
    score_voided = models.BooleanField(
        default=False,
        db_comment='Voided attempts are excluded from grade counting.',
    )
    branch = models.ForeignKey(
        BranchGroup, models.DO_NOTHING, db_column='branch_id', blank=True, null=True
    )
    synchronized_form = models.ForeignKey(
        AssessmentSynchronizedForm,
        models.SET_NULL,
        db_column='synchronized_form_id',
        blank=True,
        null=True,
        related_name='student_attempts',
    )
    creation_date = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'student_assessment_attempt'


class StudentAssessmentFocusLock(models.Model):
    REASON_TEACHER = 'teacher'
    REASON_SUBMITTED = 'submitted'
    REASON_WINDOW_ENDED = 'window_ended'
    REASON_ASSESSMENT_CLOSED = 'assessment_closed'

    attempt = models.ForeignKey(
        StudentAssessmentAttempt,
        models.CASCADE,
        db_column='attempt_id',
        related_name='focus_locks',
    )
    locked_at = models.DateTimeField(default=timezone.now)
    unlocked_at = models.DateTimeField(blank=True, null=True)
    unlocked_by = models.ForeignKey(
        UserProfile,
        models.SET_NULL,
        db_column='unlocked_by_id',
        blank=True,
        null=True,
        related_name='released_assessment_focus_locks',
    )
    unlock_reason = models.CharField(max_length=32, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'student_assessment_focus_lock'
        constraints = [
            models.UniqueConstraint(
                fields=('attempt',),
                condition=models.Q(unlocked_at__isnull=True),
                name='uq_student_assessment_focus_lock_active',
            ),
        ]


class StudentAssessmentProblem(models.Model):
    attempt = models.ForeignKey(
        StudentAssessmentAttempt, models.DO_NOTHING, db_column='attempt_id',
        related_name='problems',
    )
    slot_index = models.IntegerField()
    section_name = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)
    source_problem_id = models.IntegerField(blank=True, null=True)
    body_html = models.TextField()
    render_payload = models.JSONField(default=dict)
    answer_key = models.JSONField(default=dict)
    answer_fields = models.JSONField(default=list)
    earned_points = models.FloatField(blank=True, null=True)
    max_points = models.FloatField(blank=True, null=True)
    requires_manual_grading = models.BooleanField(default=False)
    branch = models.ForeignKey(
        BranchGroup, models.DO_NOTHING, db_column='branch_id', blank=True, null=True
    )

    class Meta:
        managed = False
        db_table = 'student_assessment_problem'


class StudentAssessmentAnswer(models.Model):
    problem = models.ForeignKey(
        StudentAssessmentProblem, models.DO_NOTHING, db_column='problem_id',
        related_name='answers',
    )
    field_token = models.CharField(max_length=255)
    content = models.JSONField(blank=True, null=True)
    points_score = models.FloatField(blank=True, null=True)
    auto_points_score = models.FloatField(blank=True, null=True)
    detail = models.JSONField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'student_assessment_answer'


class FinalGradeCalculation(models.Model):
    course = models.ForeignKey(Course, models.DO_NOTHING)
    weight = models.IntegerField(default=1)
    user = models.ForeignKey('UserProfile', models.DO_NOTHING)
    assessment = models.ForeignKey(Assessment, models.DO_NOTHING, blank=True, null=True, db_comment="Will only be 'null' if the 'delete: set null' activates")
    assessment_grade_points = models.FloatField(blank=True, null=True, db_comment='This identifies the numeric score of a given assessment for the student')
    assessment_grade_max_points = models.FloatField(blank=True, null=True, db_comment='This identifies the maximum possible score of a given assessment for a student')
    enrollment = models.ForeignKey(
        StudentCourseEnrollment,
        models.DO_NOTHING,
        db_column='enrollment_id',
        related_name='final_grades',
        db_comment='Student course enrollment stint this grade belongs to. Separates prior vs re-enrollment history.',
    )

    class Meta:
        managed = False
        db_table = 'final_grade_calculation'
        db_table_comment = (
            'Grades scoped to a student_course_enrollment stint (course close, kick, or '
            'assessment-close zeros). Assessment/course may later be deleted; grades remain.'
        )


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
    is_read = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(
        blank=True,
        null=True,
        db_comment='When set, the notification is in the user trash. Permanently purged ~30 days after this timestamp.',
    )

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
    id = models.AutoField(primary_key=True)
    student = models.ForeignKey(
        UserProfile,
        models.DO_NOTHING,
        related_name='parent_course_links_as_student',
    )
    parent = models.ForeignKey(
        UserProfile,
        models.DO_NOTHING,
        related_name='parentusercourse_parent_set',
    )
    course = models.ForeignKey(Course, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'parent_user_course'
        unique_together = (('student', 'parent', 'course'),)
        db_table_comment = "Table used to identify that a parent can see their kid's grades for a particular course"


class ParentCourseInvitation(models.Model):
    STATUS_PENDING = 'pending'

    course = models.ForeignKey(Course, models.DO_NOTHING)
    student = models.ForeignKey(
        UserProfile,
        models.DO_NOTHING,
        related_name='parent_invitations_as_student',
    )
    temp_email = models.CharField(max_length=255)
    code = models.CharField(unique=True, max_length=255)
    timeout = models.DateTimeField()
    status = models.CharField(max_length=32, default=STATUS_PENDING)
    target_user = models.ForeignKey(
        UserProfile,
        models.DO_NOTHING,
        blank=True,
        null=True,
        related_name='parent_course_invitations',
    )
    created_by = models.ForeignKey(
        UserProfile,
        models.DO_NOTHING,
        blank=True,
        null=True,
        related_name='created_parent_course_invitations',
    )
    creation_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'parent_course_invitation'
        db_table_comment = (
            'Pending Parent invites for grade access to a Student in a Course. '
            'Void and accept delete the row.'
        )


class PermissionGroup(models.Model):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        'UserProfile',
        models.DO_NOTHING,
        db_column='owner_id',
        blank=True,
        null=True,
        related_name='owned_permission_groups',
        db_comment='Optional user owner. Prefer owner_pg for system groups like public.',
    )
    owner_pg = models.ForeignKey(
        'self',
        models.DO_NOTHING,
        db_column='owner_pg_id',
        blank=True,
        null=True,
        related_name='owned_as_group',
        db_comment='When set, this group is owned by another permission_group (e.g. public → admins).',
    )
    system_protected = models.BooleanField(
        default=False,
        db_comment='System groups (admins, public) cannot be deleted even when empty.',
    )

    class Meta:
        managed = False
        db_table = 'permission_group'
        db_table_comment = 'Simply creates virtual groups that a set of permissions can apply to. For instance, to mass enable certain folder access by adding a user to the permission group.'


class PermissionGroupSubgroup(models.Model):
    """Nesting of permission groups. Postgres PK is (parent_pg_id, child_pg_id)."""

    parent = models.ForeignKey(
        PermissionGroup,
        models.DO_NOTHING,
        db_column='parent_pg_id',
        primary_key=True,
        related_name='child_subgroup_links',
    )
    child = models.ForeignKey(
        PermissionGroup,
        models.DO_NOTHING,
        db_column='child_pg_id',
        related_name='parent_subgroup_links',
    )
    permissions = models.CharField(
        max_length=32,
        db_comment='Inherited branch access cap through this edge: edit | read_only.',
    )

    class Meta:
        managed = False
        db_table = 'permission_group_subgroup'
        unique_together = (('parent', 'child'),)
        db_table_comment = 'Child group nested under parent; used for transitive share ACL.'


class Problem(models.Model):
    aqg = models.ForeignKey(AssessmentQuestionGroup, models.DO_NOTHING, blank=True, null=True, db_comment='If aqg_id is not null, then it points to the assessment_question_group that is part of an assessment')
    cqd = models.ForeignKey(CustomQuestionDistribution, models.DO_NOTHING, blank=True, null=True, db_comment='if cqd_id is not null, then it points to the custom_question_distribution that contains a list of problems that it will randomize from')
    branch_location = models.OneToOneField('BranchGroup', models.CASCADE, db_column='branch_location', related_name='problem', db_comment="Will always have a branch location. The problem gets copied to any location it is sent to")
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
    problem = models.ForeignKey(Problem, models.CASCADE)
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
    access_token = models.CharField(max_length=64)
    priority = models.TextField(blank=True, null=True)  # ticket_priority_enum
    modification_date = models.DateTimeField()
    last_comment_at = models.DateTimeField(blank=True, null=True)
    admin_unread = models.BooleanField(default=False)
    client_notified_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ticket'
        db_table_comment = "Might want to add a 'tags' field when I actually implement this"


class TicketDiscussion(models.Model):
    commentor_email = models.CharField(max_length=255)
    ticket_reference = models.ForeignKey(Ticket, models.DO_NOTHING)
    comment = _PsycopgJSONField()
    creation_date = models.DateTimeField(blank=True, null=True)
    is_system = models.BooleanField(default=False)
    author_user = models.ForeignKey(
        'UserProfile',
        models.DO_NOTHING,
        db_column='author_user_id',
        related_name='ticket_discussion_authored_set',
        blank=True,
        null=True,
    )

    class Meta:
        managed = False
        db_table = 'ticket_discussion'
        db_table_comment = 'Essentially the chat history for a given ticket'


class TicketAdminFilterPref(models.Model):
    user = models.OneToOneField(
        'UserProfile',
        models.DO_NOTHING,
        db_column='user_id',
        primary_key=True,
        related_name='ticket_admin_filter_pref',
    )
    filters = _PsycopgJSONField(default=dict)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'ticket_admin_filter_pref'
        db_table_comment = (
            'Saved default Tickets-list filter/sort settings for an IT Support user.'
        )


class TeacherCourseInvitation(models.Model):
    course = models.ForeignKey(Course, models.DO_NOTHING)
    invitee = models.ForeignKey(
        'UserProfile',
        models.DO_NOTHING,
        related_name='teacher_course_invitation_invitee_set',
    )
    invited_by = models.ForeignKey(
        'UserProfile',
        models.DO_NOTHING,
        related_name='teacher_course_invitation_invited_by_set',
    )
    code = models.CharField(max_length=255)
    creation_date = models.DateTimeField(blank=True, null=True)
    timeout = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'teacher_course_invitation'
        db_table_comment = (
            'Pending co-Teacher invites. Deleted on accept, reject, or void.'
        )


class UserCourseActivation(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_VOIDED = 'voided'

    course = models.ForeignKey(Course, models.DO_NOTHING)
    slot = models.ForeignKey('UsersInCourse', models.DO_NOTHING, db_comment='This represents the Class slot the Teacher made available')
    temp_email = models.CharField(max_length=255, blank=True, null=True, db_comment='CONSTRAINT check_lowercase_email CHECK (LOWER(temp_email) = temp_email)')
    code = models.CharField(max_length=255, db_comment='Redeem token for the course invitation link')
    timeout = models.DateTimeField(db_comment='Invite expiry; redeem rejected after this time')
    status = models.CharField(
        max_length=32,
        default=STATUS_PENDING,
        db_comment='pending while open; accepted/voided are legacy — successful accept and void now delete the row',
    )
    invited_username = models.CharField(max_length=255, blank=True, null=True)
    target_user = models.ForeignKey(
        'UserProfile',
        models.DO_NOTHING,
        db_column='target_user_id',
        related_name='course_invitations_targeted',
        blank=True,
        null=True,
        db_comment='Existing invitee at create time, or claimed new user after signup start',
    )
    created_by = models.ForeignKey(
        'UserProfile',
        models.DO_NOTHING,
        db_column='created_by_id',
        related_name='course_invitations_created',
        blank=True,
        null=True,
    )
    creation_date = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'user_course_activation'
        unique_together = (('course', 'temp_email', 'slot'),)


class UserPermissionGroup(models.Model):
    """Membership of a user in a named PermissionGroup.

    Postgres PK is (user_id, pg_id). Django 4.2 has no composite PK, so
    ``user`` is marked primary_key for ORM convenience; always filter by both
    columns when updating a specific membership.
    """

    PERM_OWNER = 'owner'
    PERM_EDIT = 'edit'
    PERM_READ_ONLY = 'read_only'

    user = models.ForeignKey(
        UserProfile,
        models.DO_NOTHING,
        db_column='user_id',
        primary_key=True,
        related_name='permission_group_memberships',
    )
    permission_group = models.ForeignKey(
        PermissionGroup,
        models.DO_NOTHING,
        db_column='pg_id',
        related_name='memberships',
    )
    permissions = models.CharField(
        max_length=32,
        db_comment='Membership role: owner | edit | read_only.',
    )

    class Meta:
        managed = False
        db_table = 'user_permission_group'
        unique_together = (('user', 'permission_group'),)
        db_table_comment = 'Pairs users with groups and their role within that group.'


class UsersGroup(models.Model):
    """Branch ACL rows. Postgres has no surrogate id — use raw SQL helpers in collaboration.py."""

    PERM_OWNER = 'owner'
    PERM_EDIT = 'edit'
    PERM_READ_ONLY = 'read_only'

    branch = models.ForeignKey(BranchGroup, models.DO_NOTHING, db_column='branch_id', primary_key=True)
    user = models.ForeignKey(UserProfile, models.DO_NOTHING, blank=True, null=True, db_comment='This or permission_group need to be specified')
    permission_group = models.ForeignKey(PermissionGroup, models.DO_NOTHING, db_column='permission_group', blank=True, null=True, db_comment='This or user_id need to be specified')
    permissions = models.CharField(max_length=32, db_comment='Branch ACL: owner | edit | read_only.')
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

