from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import Course, UsersInCourse, UserProfile, ParentUserCourse
from .models import (
    BranchGroup, Assessment, Problem, 
    CustomQuestionDistribution, AssessmentQuestionGroup, 
    CustomQuestionDistribution, CqdPair,
    QuestionBlock, EntitySegment,
    EntityType, Notification,
    FinalGradeCalculation, StudentCourseEnrollment,
    AssessmentGenerationJob, StudentAssessmentAttempt,
    AssessmentOptions,
)
from .dashboard import (
    dashboard_courses_for_user,
    dashboard_parent_groups_for_user,
    dashboard_student_closed_grades_for_user,
    teacher_active_retakes_for_user,
    teacher_focus_unlocks_for_user,
    teacher_grade_releases_for_user,
    teacher_manual_grading_for_user,
    user_display_name,
    user_greeting_name,
)
from .course_lifecycle import (
    apply_course_status,
    course_is_closed,
    course_is_deleted,
    deny_unavailable_course_entry,
    student_can_view_course_grades,
    user_can_close_or_reactivate_course,
)
from .util import get_valid_unique_name, send_to_trash, restore_item_from_trash, calculate_midpoint_order, duplicate_problem_in_aqg, move_problem_to_aqg, move_problem_to_cqd, remove_problem_from_cqd, refresh_cqd_identity, _clear_cqd_membership, SymPyAssessmentEngine, get_entity_validator, get_blueprint_for_token, evaluate_and_format_entity, assemble_practice_test, grade_entities_payload
import html
import json
from django.http import JsonResponse, Http404

from django.db import transaction
from .forms import (
    TeacherRegistrationForm,
    CourseInviteForm,
    ParentCourseInviteForm,
    ParentRegistrationForm,
    StudentRegistrationForm,
)
from .models import (
    EmailAuthentication,
    UserCourseActivation,
    ParentCourseInvitation,
    TeacherCourseInvitation,
    PasswordResetRequest,
    QA,
    QaTag,
    QaTagAssignment,
    ContactUs,
    ContentImage,
    CreditInvoice,
    CreditLedger,
    CreditPurchase,
    Ticket,
    TicketDiscussion,
    TicketAdminFilterPref,
)
from .course_enrollment import (
    enrollment_within_credit_reimbursement_window,
    ensure_active_enrollment,
    get_active_enrollment,
    kick_student_from_course,
)
from .collaboration import can_edit_branch, can_read_branch
from .view_mode import apply_explorer_mode_from_request
from .course_invites import (
    INVITE_SESSION_KEY,
    claim_invite_for_new_user,
    complete_course_invite_if_pending,
    create_course_invite,
    enroll_user_from_invite,
    get_invite_by_code,
    handle_already_enrolled_invite_access,
    invite_status_label,
    is_unclaimed_email_invite,
    redeem_block_reason,
    user_already_enrolled_in_course,
    user_can_access_course_management,
    user_can_manage_course,
    user_matches_invite,
    void_course_invite,
)
from .parent_invites import (
    PARENT_INVITE_SESSION_KEY,
    accept_parent_invite,
    claim_parent_invite_for_new_user,
    complete_parent_invite_if_pending,
    create_parent_invite,
    get_parent_invite_by_code,
    grant_parent_access,
    handle_non_parent_invite_access,
    handle_parent_already_has_access,
    is_unclaimed_parent_email_invite,
    parent_access_rows_for_course,
    parent_has_course_access,
    parent_invite_status_label,
    parent_redeem_block_reason,
    parent_user_matches_invite,
    revoke_parent_access,
    void_parent_invite,
)
from .teacher_invites import (
    accept_teacher_invite,
    create_teacher_invite,
    leave_course_as_teacher,
    list_course_teacher_rows,
    lookup_teacher_for_invite,
    reject_teacher_invite,
    remove_teacher_from_course,
    teacher_invite_is_redeemable,
    transfer_course_ownership,
    user_can_manage_teachers,
    void_teacher_invite,
)
import secrets
import random
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from django.db import IntegrityError
from django.views.decorators.http import require_POST, require_GET, require_http_methods
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
import traceback
import logging
from django.views.decorators.csrf import csrf_protect

logger = logging.getLogger(__name__)

import sympy as sp
from sympy.parsing.latex import parse_latex
# 🎯 WORKAROUND MONKEYPATCH: Trick SymPy into accepting antlr4-python3-runtime 4.13.x
import importlib.metadata
_orig_version = importlib.metadata.version

def patched_version(package_name):
    if package_name == 'antlr4-python3-runtime':
        return '4.11.1'  # Return the exact string SymPy's regex check is looking for
    return _orig_version(package_name)

# Overwrite the metadata version checker at runtime
importlib.metadata.version = patched_version


class HomeDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'assessment_tool/dashboard.html'

    def get_context_data(self, **kwargs):
        from .notifications import (
            reason_label_for,
            unread_notifications_for_user,
            utc_isoformat,
        )

        context = super().get_context_data(**kwargs)
        user = self.request.user

        context['greeting_name'] = user_greeting_name(user)
        context['dashboard_courses'] = dashboard_courses_for_user(user)
        context['parent_dashboard'] = (
            dashboard_parent_groups_for_user(user)
            if user.user_type == 'Parent'
            else None
        )
        context['student_closed_grades'] = (
            dashboard_student_closed_grades_for_user(user)
            if user.user_type == 'Student'
            else []
        )

        if user.user_type == 'Student':
            context['ongoing_test'] = False
            from .student_attempts import open_takeable_assessments_for_student
            context['open_assessments'] = open_takeable_assessments_for_student(user)
        else:
            context['open_assessments'] = []
        context['manual_grading_assessments'] = teacher_manual_grading_for_user(user)
        context['active_retake_assessments'] = teacher_active_retakes_for_user(user)
        context['focus_unlock_requests'] = teacher_focus_unlocks_for_user(user)
        context['grade_release_assessments'] = teacher_grade_releases_for_user(user)

        unread_rows = []
        for note in unread_notifications_for_user(user, include_content=False):
            unread_rows.append({
                "id": note.pk,
                "title": note.title,
                "reason": note.reason,
                "reason_label": reason_label_for(note.reason),
                "creation_date": note.creation_date,
                "creation_date_utc": (
                    utc_isoformat(note.creation_date) if note.creation_date else None
                ),
            })
        context['unread_notifications'] = unread_rows

        return context


@login_required
def teacher_live_attention_ajax(request):
    """Small polling payload for active focus-lock requests."""
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    rows = teacher_focus_unlocks_for_user(request.user)
    payload = []
    for row in rows:
        payload.append(
            {
                **row,
                "locked_at": row["locked_at_utc"],
                "manage_url": (
                    reverse(
                        "course_grades_assessment",
                        kwargs={
                            "course_id": row["course_id"],
                            "assessment_id": row["assessment_id"],
                        },
                    )
                    + f"#attempt-{row['attempt_id']}"
                ),
                "action_url": reverse(
                    "course_grades_attempt_action",
                    kwargs={
                        "course_id": row["course_id"],
                        "assessment_id": row["assessment_id"],
                        "attempt_id": row["attempt_id"],
                    },
                ),
            }
        )
    return JsonResponse({"success": True, "focus_unlock_requests": payload})


@login_required
def parent_grade_summary_view(request, student_id, course_id):
    """Parent-facing grades for a linked student/course (read-only)."""
    if request.user.user_type != 'Parent':
        messages.error(request, "Only parent accounts can view grade summaries.")
        return redirect('dashboard')

    link = ParentUserCourse.objects.filter(
        parent=request.user,
        student_id=student_id,
        course_id=course_id,
    ).select_related('student', 'course').first()
    if link is None:
        messages.error(request, "Grade summary not found for this student and course.")
        return redirect('dashboard')
    if course_is_deleted(link.course):
        messages.warning(
            request,
            "This course is in Trash. Grades are unavailable until it is restored.",
        )
        return redirect('dashboard')

    from .assessment_grades import student_grades_for_course
    from .dashboard import user_display_name

    payload = student_grades_for_course(link.course, link.student)
    student_name = user_display_name(link.student)
    return render(
        request,
        'assessment_tool/course_grades_student.html',
        {
            'course': link.course,
            'active_tab': 'grades',
            'grade_rows': payload['rows'],
            'grade_total': payload['total'],
            'grade_aggregation_mode': payload['grade_aggregation_mode'],
            'is_teacher_viewer': False,
            'parent_viewer': True,
            'student': link.student,
            'student_name': student_name,
            'grades_subtitle': f"Grades for {student_name} in this course.",
        },
    )


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
                        auth = EmailAuthentication.generate_auth_record(user, form.cleaned_data['email'])
                        from .mail import send_verification_code_email
                        send_verification_code_email(to_email=auth.temp_email, code=auth.code)

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
                    auth = EmailAuthentication.generate_auth_record(request.user, new_email)
                    from .mail import send_verification_code_email
                    send_verification_code_email(to_email=auth.temp_email, code=auth.code)
                    messages.success(request, f"Email changed to {new_email}. A new code has been sent.")
                    return redirect('verify_email')

        # If the button 'resend' was pressed
        if 'resend' in request.POST:
            # We use the email currently stored in the auth_record
            if auth_record:
                auth = EmailAuthentication.generate_auth_record(request.user, auth_record.temp_email)
                from .mail import send_verification_code_email
                send_verification_code_email(to_email=auth.temp_email, code=auth.code)
                messages.success(request, "A new activation code has been sent!")
                return redirect('verify_email')

        if 'code' in request.POST:
            input_code = request.POST.get('code')
            if not is_expired and input_code == auth_record.code:
                user = request.user
                previous_email = user.user_email
                new_email = auth_record.temp_email
                was_email_update = not bool(user.unactivated_account)
                user.user_email = new_email
                user.unactivated_account = False
                user.save()
                EmailAuthentication.objects.filter(u_id=user).delete()
                if was_email_update:
                    from .account_settings import notify_email_updated

                    notify_email_updated(
                        user=user,
                        previous_email=previous_email,
                        new_email=new_email,
                    )
                    messages.success(request, "Email updated successfully!")
                else:
                    messages.success(request, "Account activated successfully!")
                invite_code = request.session.pop(INVITE_SESSION_KEY, None)
                enrolled, invite_msg = complete_course_invite_if_pending(user, invite_code)
                if invite_msg:
                    if enrolled:
                        messages.success(request, invite_msg)
                    else:
                        messages.warning(request, invite_msg)
                parent_invite_code = request.session.pop(PARENT_INVITE_SESSION_KEY, None)
                granted, parent_msg = complete_parent_invite_if_pending(
                    user, parent_invite_code
                )
                if parent_msg:
                    if granted:
                        messages.success(request, parent_msg)
                    else:
                        messages.warning(request, parent_msg)
                if was_email_update:
                    return redirect('account_settings')
                return redirect('dashboard')
            elif is_expired:
                messages.error(request, "This code has expired. Please resend a new one.")
            else:
                messages.error(request, "Invalid code.")
    
        if 'cancel_activation' in request.POST:
            user = request.user
            was_email_update = not bool(user.unactivated_account)
            # Mark the account as active
            user.unactivated_account = False
            user.save()
            
            # Wipe the pending authentication data
            EmailAuthentication.objects.filter(u_id=user.user_id).delete()
            
            messages.info(request, "Email verification cancelled. Your account is now active with your current email.")
            if was_email_update:
                return redirect('account_settings')
            return redirect('dashboard')

    return render(request, 'assessment_tool/verify_email.html', {
        'minutes_left': max(0, minutes_left),
        'temp_email': auth_record.temp_email,
        'is_expired': is_expired,
        'is_already_active': not request.user.unactivated_account,
        'current_email': request.user.user_email
    })


@login_required
def account_settings_view(request):
    from .account_settings import (
        cancel_pending_email_change,
        gender_label,
        pending_email_for_user,
        reset_password,
        start_email_change,
        update_display_name,
        update_organization,
    )
    from .credit_views import account_credits_context, handle_account_credit_post

    user = request.user
    if request.method == 'POST':
        action = request.POST.get('action') or ''
        if action in (
            'buy_credits',
            'request_credits',
            'attach_purchase_invoice',
            'transfer_credits',
        ):
            return handle_account_credit_post(request)
        if action == 'update_display_name':
            changed, _new_value = update_display_name(
                user, request.POST.get('display_name')
            )
            if changed:
                messages.success(request, "Display name updated.")
            else:
                messages.info(request, "Display name was unchanged.")
            return redirect('account_settings')
        if action == 'update_organization':
            try:
                changed, _new_value = update_organization(
                    user, request.POST.get('organization')
                )
                if changed:
                    messages.success(request, "Organization updated.")
                else:
                    messages.info(request, "Organization was unchanged.")
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('account_settings')
        if action == 'start_email_change':
            try:
                start_email_change(
                    user=user,
                    new_email_raw=request.POST.get('new_email') or '',
                    password=request.POST.get('password') or '',
                )
                messages.success(
                    request,
                    "Email change started. Enter the verification code sent to your new email.",
                )
                return redirect('verify_email')
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('account_settings')
        if action == 'cancel_email_change':
            if cancel_pending_email_change(user):
                messages.info(
                    request,
                    "Pending email change cancelled. Your current email was kept.",
                )
            else:
                messages.info(request, "There was no pending email change to cancel.")
            return redirect('account_settings')
        if action == 'reset_password':
            try:
                from django.contrib.auth import update_session_auth_hash

                reset_password(
                    user=user,
                    new_password=request.POST.get('new_password') or '',
                    confirm_password=request.POST.get('confirm_password') or '',
                    current_password=request.POST.get('password') or '',
                )
                update_session_auth_hash(request, user)
                messages.success(request, "Password updated.")
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('account_settings')

    pending = pending_email_for_user(user)
    active_tab = (request.GET.get('tab') or 'profile').strip().lower()
    if active_tab not in ('profile', 'credits'):
        active_tab = 'profile'
    if active_tab == 'credits' and user.user_type not in ('Teacher', 'IT_Support'):
        active_tab = 'profile'
    context = {
        'profile': user,
        'gender_label': gender_label(user.gender),
        'display_name_value': user.user_display_name or '',
        'organization_value': user.organization or '',
        'pending_email': pending.temp_email if pending else None,
        'show_organization': user.user_type in ('Teacher', 'IT_Support'),
        'current_email': (user.user_email or '').strip().lower(),
        'account_active_tab': active_tab,
    }
    context.update(account_credits_context(user))
    return render(request, 'assessment_tool/account_settings.html', context)


@user_passes_test(lambda u: u.is_superuser, login_url='/dashboard/')
def database_viewer(request):
    # Get the table selection from the GET request
    table_name = request.GET.get('table', 'user_profile')

    # Map the dropdown values to the actual Models
    model_map = {
        'user_profile': UserProfile,
        'email_authentication': EmailAuthentication,
        'password_reset_request': PasswordResetRequest,
        'Q_A': QA,
        'qa_tag': QaTag,
        'qa_tag_assignment': QaTagAssignment,
        'user_course_activation': UserCourseActivation,
        'parent_course_invitation': ParentCourseInvitation,
        'teacher_course_invitation': TeacherCourseInvitation,
        'student_course_enrollment': StudentCourseEnrollment,
        'final_grade_calculation': FinalGradeCalculation,
        'course': Course,
        'branch_group': BranchGroup,
        'users_in_course': UsersInCourse,
        'assessment': Assessment,
        'aqg': AssessmentQuestionGroup,
        'cqd': CustomQuestionDistribution,
        'problem': Problem,
        'question_block': QuestionBlock,
        'entity_segment': EntitySegment,
        'entity_type': EntityType,
        'student_assessment_attempt': StudentAssessmentAttempt,
        'assessment_generation_job': AssessmentGenerationJob,
        'notification': Notification,
        'contact_us': ContactUs,
        'content_image': ContentImage,
        'credit_invoice': CreditInvoice,
        'credit_ledger': CreditLedger,
        'credit_purchase': CreditPurchase,
        'ticket': Ticket,
        'ticket_discussion': TicketDiscussion,
        'ticket_admin_filter_pref': TicketAdminFilterPref,
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
def notifications_view(request):
    from .notifications import (
        NOTIFICATIONS_PAGE_SIZE,
        delete_all_read_notifications_for_user,
        empty_notification_trash_for_user,
        mark_all_active_notifications_read,
        notifications_page_for_user,
        reason_label_for,
        trashed_notifications_for_user,
        user_has_read_list_notifications,
        user_has_trashed_notifications,
        user_has_unread_list_notifications,
        utc_isoformat,
    )

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "empty_trash":
            removed = empty_notification_trash_for_user(request.user)
            if removed:
                messages.success(
                    request,
                    f"Emptied trash ({removed} notification{'s' if removed != 1 else ''} permanently removed).",
                )
            else:
                messages.info(request, "Trash was already empty.")
            return redirect("notifications")
        if action == "mark_all_read":
            updated = mark_all_active_notifications_read(request.user)
            if updated:
                messages.success(
                    request,
                    f"Marked {updated} notification{'s' if updated != 1 else ''} as read.",
                )
            else:
                messages.info(request, "No unread notifications to mark.")
            return redirect("notifications")
        if action == "delete_all_read":
            removed = delete_all_read_notifications_for_user(request.user)
            if removed:
                messages.success(
                    request,
                    f"Moved {removed} read notification{'s' if removed != 1 else ''} to trash.",
                )
            else:
                messages.info(request, "No read notifications to delete.")
            return redirect("notifications")

    rows, _total_count, has_more = notifications_page_for_user(
        request.user, offset=0, limit=NOTIFICATIONS_PAGE_SIZE
    )

    trash_rows = []
    for note in trashed_notifications_for_user(request.user, include_content=False):
        trash_rows.append({
            "id": note.pk,
            "title": note.title,
            "reason": note.reason,
            "reason_label": reason_label_for(note.reason),
            "creation_date": note.creation_date,
            "creation_date_utc": (
                utc_isoformat(note.creation_date) if note.creation_date else None
            ),
            "deleted_at": note.deleted_at,
            "deleted_at_utc": (
                utc_isoformat(note.deleted_at) if note.deleted_at else None
            ),
            "is_read": note.is_read,
        })

    return render(request, "assessment_tool/notifications.html", {
        "notifications": rows,
        "trashed_notifications": trash_rows,
        "has_trashed_notifications": user_has_trashed_notifications(request.user),
        "show_mark_all_read": user_has_unread_list_notifications(request.user),
        "show_delete_all_read": user_has_read_list_notifications(request.user),
        "has_more_notifications": has_more,
        "notifications_page_size": NOTIFICATIONS_PAGE_SIZE,
        "notifications_loaded_count": len(rows),
    })


@login_required
@require_GET
def notifications_load_more_ajax(request):
    from .notifications import NOTIFICATIONS_PAGE_SIZE, notifications_page_for_user

    try:
        offset = int(request.GET.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0

    rows, total_count, has_more = notifications_page_for_user(
        request.user, offset=offset, limit=NOTIFICATIONS_PAGE_SIZE
    )
    return JsonResponse({
        "notifications": rows,
        "total_count": total_count,
        "next_offset": offset + len(rows),
        "has_more": has_more,
        "page_size": NOTIFICATIONS_PAGE_SIZE,
    })


@login_required
def notification_detail_view(request, notification_id):
    from .notifications import (
        build_notification_detail,
        get_notification_for_user,
        mark_notification_read,
    )

    note = get_notification_for_user(
        request.user, notification_id, include_trashed=False
    )
    if note is None:
        from django.http import Http404
        raise Http404("Notification not found")

    mark_notification_read(request.user, notification_id)
    note.refresh_from_db()
    detail = build_notification_detail(note)
    return render(request, "assessment_tool/notification_detail.html", {
        "notification": detail,
    })


@login_required
@require_POST
def notification_delete_view(request, notification_id):
    from .notifications import delete_notification_for_user

    deleted = delete_notification_for_user(request.user, notification_id)
    if deleted:
        messages.success(request, "Notification moved to trash.")
    else:
        messages.error(request, "Notification not found.")
    return redirect("notifications")


@login_required
@require_POST
def notification_restore_view(request, notification_id):
    from .notifications import restore_notification_for_user

    restored = restore_notification_for_user(request.user, notification_id)
    if restored:
        messages.success(request, "Notification restored.")
    else:
        messages.error(request, "Trashed notification not found.")
    return redirect("notifications")


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
            Q(owner=user)
            | Q(status='template')
            | Q(
                usersincourse__user=user,
                usersincourse__user_access='active',
            )
        ).select_related('owner', 'branch_location').annotate(
            status_order=status_priority
        ).distinct().order_by('status_order', 'name')

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
            apply_course_status(course, new_status)
            messages.success(request, f"Updated '{course.name}' status to {new_status}.")
            return get_sticky_redirect()
        
        # 2. Handling the "Create by Copying"
        if 'copy_course' in request.POST:
            source_id = request.POST.get('source_course_id')
            target_transition = request.POST.get('target_transition') # e.g. 'developing_to_template'
            source_course = get_object_or_404(Course, id=source_id)

            try:
                from .credits import CreditError, assert_can_create_course
                assert_can_create_course(user)
                source_course.duplicate_course(user=user, target_transition=target_transition)
                messages.success(request, f"Successfully branched new course from '{source_course.name}'.")
                return redirect('course_list')
            except CreditError as exc:
                messages.error(request, str(exc))
                return redirect('course_list')
            except Exception:
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
    # Returning to the explorer exits content view-only mode.
    from .view_mode import SESSION_KEY
    if request.session.get(SESSION_KEY):
        request.session[SESSION_KEY] = False

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
        'load_problem_workspace': True,
    })

# AJAX view to get contents of a specific folder

from django.db.models import Count

def get_folder_contents(request, group_id):
    from .folder_roots import (
        FOLDER_STUDENT_PROVIDED,
        FOLDER_COLLABORATION,
        FOLDER_PUBLIC_LIBRARY,
        FOLDER_TRASH,
        FOLDER_WORKSPACE,
        protected_subtree_prefixes,
        user_root_path,
    )
    from .collaboration import (
        can_read_branch,
        collaboration_share_roots_for_user,
        effective_permission,
        public_library_roots_for_user,
        shared_branch_id_set,
    )

    group = get_object_or_404(BranchGroup, id=group_id)
    username = request.user.username
    current_path = group.get_parent_path() + group.name + "/"
    root_sys = user_root_path(username)

    owns = group.owner_id == request.user.user_id
    if not owns and not can_read_branch(request.user, group):
        return JsonResponse({'error': 'Permission denied.'}, status=403)

    folders_list = []
    trash_folder = None
    show_manage_groups = False

    if owns and group.parent_id is not None and group.name == FOLDER_COLLABORATION:
        folders_list = collaboration_share_roots_for_user(request.user)
        show_manage_groups = request.user.user_type in ('Teacher', 'IT_Support')
    elif owns and group.parent_id is not None and group.name == FOLDER_PUBLIC_LIBRARY:
        folders_list = public_library_roots_for_user(request.user)
    else:
        folders_qs = (
            BranchGroup.objects.filter(parent=group)
            .select_related('parent__parent', 'owner')
            .prefetch_related('course', 'assessment', 'cqd', 'aqg', 'problem')
            .order_by('order')
        )
        if group.parent_id is None and getattr(request.user, 'user_type', None) != 'Student':
            folders_qs = folders_qs.exclude(
                name__in=[
                    FOLDER_STUDENT_PROVIDED,
                    'Student Generated Assessments by Course',
                ]
            )
        if group.parent_id is None:
            others = []
            for f in folders_qs:
                if f.name == FOLDER_TRASH:
                    trash_folder = f
                else:
                    others.append(f)
            folders_list = others
        else:
            folders_list = list(folders_qs)

    # Mark shared items under Workspace for UI indicator + delete gating.
    under_workspace = (
        f"/{username}_root/{FOLDER_WORKSPACE}/" in current_path
        or (owns and group.name == FOLDER_WORKSPACE)
    )
    under_collaboration = owns and group.name == FOLDER_COLLABORATION
    if under_workspace and folders_list:
        shared_ids = shared_branch_id_set([f.id for f in folders_list])
        for f in folders_list:
            f.is_shared = f.id in shared_ids
            f.collab_list_owned = None
    else:
        for f in folders_list:
            f.is_shared = False
            if under_collaboration:
                f.collab_list_owned = f.owner_id == request.user.user_id
            else:
                f.collab_list_owned = None

    for f in folders_list:
        if f.owner_id == request.user.user_id:
            f.viewer_perm = 'owner'
        else:
            f.viewer_perm = effective_permission(request.user, f) or ''

    problems_qs = Problem.objects.none()
    has_items = bool(folders_list) or bool(trash_folder)

    is_protected = (
        current_path == root_sys
        or any(current_path.startswith(p) for p in protected_subtree_prefixes(username))
    )
    if owns and group.name in (FOLDER_COLLABORATION, FOLDER_PUBLIC_LIBRARY, FOLDER_TRASH):
        is_protected = True

    from .branch_hierarchy import parent_allows_new_folder

    parent_folder_type = group.folder_type or 'folder'
    allow_new_folder = (not is_protected) and parent_allows_new_folder(parent_folder_type)

    return render(request, 'assessment_tool/partials/column.html', {
        'contents': {
            'folders': folders_list,
            'problems': problems_qs,
            'has_items': has_items,
            'trash_folder': trash_folder,
        },
        'parent_id': group.id,
        'level': int(request.GET.get('level', 1)),
        'is_protected': is_protected,
        'allow_new_folder': allow_new_folder,
        'parent_folder_type': parent_folder_type,
        'current_path': current_path,
        'show_manage_groups': show_manage_groups,
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
    
    from .folder_roots import protected_subtree_prefixes, user_root_path
    from .branch_hierarchy import branch_placement_error
    root = user_root_path(username)
    # Block creation inside Courses / Collaboration / Student Provided / Public Library / Trash.
    # Workspace intentionally allows sub-folders.
    if parent_full_path == root or any(
        parent_full_path.startswith(p) for p in protected_subtree_prefixes(username)
    ):
        return JsonResponse({
            'error': 'This directory is managed by the system. Sub-folders cannot be added here.'
        }, status=403)

    placement_err = branch_placement_error(parent_folder.folder_type, 'folder')
    if placement_err:
        return JsonResponse({'error': placement_err}, status=400)

    # Use the helper logic
    unique_name, error = get_valid_unique_name(BranchGroup, parent_folder, requested_name)
    
    if error:
        return JsonResponse({'error': error}, status=400)

    # Create the folder
    new_folder = BranchGroup.objects.create(
        name=unique_name,
        order=unique_name,
        parent=parent_folder,
        owner=request.user,
        folder_type='folder',
    )

    return JsonResponse({'status': 'success', 'id': new_folder.id})


def delete_item(request, item_type=None, item_id=None):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    # 1. Flexible Extraction Layer (Handles both URL parameters and JSON bodies fluidly)
    if not item_id or not item_type:
        try:
            data = json.loads(request.body)
            item_id = item_id or data.get('id')
            item_type = item_type or data.get('type')
        except Exception:
            return JsonResponse({'error': 'Malformed request JSON payload content structure.'}, status=400)

    if not item_id or not item_type:
        return JsonResponse({'error': 'Missing required identifier parameters.'}, status=400)

    # Convert ID to int to keep unmanaged queries tracking reliably
    try:
        item_id = int(item_id)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid format: ID identifier must be an integer.'}, status=400)

    # 2. Resolve Object & Path with strict Ownership Verification
    try:
        if item_type in ['folder', 'course', 'assessment', 'assessment_selection', 'question_selection', 'problem']:
            if item_type in ['folder', 'course', 'assessment']:
                if request.user.user_type == 'IT_Support':
                    obj = get_object_or_404(BranchGroup, id=item_id)
                else:
                    obj = get_object_or_404(BranchGroup, id=item_id, owner=request.user)

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
                    return JsonResponse({'error': f'User not authenticated to delete: {item_type}'}, status=403)
                    
            elif item_type == 'question_selection':
                if request.user.user_type == 'IT_Support':
                    cqd_item = get_object_or_404(CustomQuestionDistribution, id=item_id)
                else:
                    cqd_item = get_object_or_404(CustomQuestionDistribution, id=item_id, assigned_folder__owner=request.user)
                obj = cqd_item.assigned_folder
                
            elif item_type == 'problem':
                problem_item = get_object_or_404(Problem.objects.select_related('branch_location'), id=item_id)
                if request.user.user_type != 'IT_Support' and problem_item.branch_location.owner != request.user:
                    return JsonResponse({'error': 'Permission Denied: You do not own this resource.'}, status=403)
                obj = problem_item.branch_location

            if not obj:
                return JsonResponse({'error': 'Target branch directory location tracking error.'}, status=400)

            item_full_path = obj.get_parent_path() + obj.name + "/"
        else:
            return JsonResponse({'error': f'Unsupported item type: {item_type}'}, status=400)
            
    except Exception as e:
        return JsonResponse({
            'error': f"Python Exception: {str(e)}",
            'item_id_received': item_id,
            'item_type_received': item_type
        }, status=400)

    # 3. System Protection Check
    username = request.user.username
    from .folder_roots import core_top_level_paths
    protected = core_top_level_paths(username)

    if item_full_path in protected:
        return JsonResponse({'error': 'System folders cannot be deleted.'}, status=403)

    # 4–5. Soft-delete to Trash unless already in Trash (then hard-delete).
    # Non-empty Workspace trees are allowed (entire subtree moves with the root).
    from .folder_roots import FOLDER_TRASH, FOLDER_WORKSPACE
    trash_prefix = f"/Users/{username}_root/{FOLDER_TRASH}/"
    workspace_prefix = f"/Users/{username}_root/{FOLDER_WORKSPACE}/"
    already_in_trash = item_full_path.startswith(trash_prefix) or (
        obj.parent and obj.parent.name == FOLDER_TRASH
    )

    if not already_in_trash:
        from .collaboration import share_root_has_non_owner_collaborators
        if share_root_has_non_owner_collaborators(obj):
            return JsonResponse({
                'error': (
                    'This item is still shared. Unshare it (remove all collaborators) '
                    'before moving it to Trash.'
                ),
                'code': 'shared_blocked',
            }, status=400)
        # Soft-delete: move selected root into Trash (children stay attached).
        with transaction.atomic():
            # Resolve branch node for problem deletes
            branch_node = obj
            if item_type == 'problem':
                branch_node = obj
            send_to_trash(branch_node, request.user)
        return JsonResponse({'status': 'success', 'action': 'trashed'})

    # Hard-delete from Trash (selected trash root only; nested items cannot be deleted alone).
    if obj.parent is None or obj.parent.name != FOLDER_TRASH:
        return JsonResponse({
            'error': 'Only top-level Trash items can be permanently deleted. Restore the parent or empty from the trash root.'
        }, status=400)

    with transaction.atomic():
        if item_type == 'problem':
            problem_item = (
                Problem.objects.select_related('cqd', 'branch_location')
                .filter(id=item_id)
                .first()
            )
            old_cqd = None
            if problem_item:
                old_cqd = _clear_cqd_membership(problem_item)
                if problem_item.cqd_id is not None:
                    problem_item.cqd = None
                    problem_item.save(update_fields=['cqd'])
            obj.delete()
            if old_cqd is not None:
                refresh_cqd_identity(old_cqd)
        elif item_type in ['folder', 'course', 'assessment', 'assessment_selection', 'question_selection']:
            obj.delete()
        else:
            return JsonResponse({'error': f'Unsupported purge routing requested for type: {item_type}.'}, status=403)

    return JsonResponse({'status': 'success', 'action': 'purged'})


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

        # Map client identifiers to core model definitions
        model_map = {
            'folder': (BranchGroup, 'name'),
            'course': (Course, 'name'), 
            'assessment': (Assessment, 'name'),
            'aqg': (AssessmentQuestionGroup, 'name'),
            'cqd': (CustomQuestionDistribution, 'name'),
            'problem': (Problem, 'title'),
            'assessment_selection': (AssessmentQuestionGroup, 'name'),
            'question_selection': (CustomQuestionDistribution, 'name'),
        }

        if item_type not in model_map:
            return JsonResponse({'error': 'Unknown item type.'}, status=400)

        model_class, field_name = model_map[item_type]
        
        # --- COMPONENT FETCH AND SECURITY CLEARANCE ---
        if item_type in ['folder', 'course', 'assessment', 'aqg', 'cqd']:
            obj = get_object_or_404(BranchGroup, id=item_id)
            
            # Since verify_workspace_clearance expects a Problem instance, 
            # we handle Folder/Course/Assessment node ownership directly or fallback on IT_Support
            if request.user.user_type != 'IT_Support' and obj.owner != request.user:
                return JsonResponse({'error': 'You do not have permission to rename this system element.'}, status=403)
                
            item_full_path = obj.get_parent_path() + obj.name + "/"
            parent = obj.parent
            exclude_branch_id = obj.id
        else:
            # Independent payload rows. Explorer context menu may pass either the
            # payload id or the linked BranchGroup id for problems / AQG / CQD.
            if item_type == 'problem':
                obj = (
                    Problem.objects.select_related('branch_location')
                    .filter(id=item_id)
                    .first()
                )
                if obj is None:
                    obj = get_object_or_404(
                        Problem.objects.select_related('branch_location'),
                        branch_location_id=item_id,
                    )
            elif item_type in ('assessment_selection', 'question_selection'):
                obj = get_object_or_404(
                    model_class.objects.select_related(
                        'branch_location' if item_type == 'assessment_selection' else 'assigned_folder'
                    ),
                    id=item_id,
                )
            else:
                obj = get_object_or_404(
                    model_class.objects.select_related('branch_location'),
                    id=item_id,
                )
            
            if item_type == 'problem':
                # Pass your problem record straight to your specialized security matrix mapping routine
                if not verify_workspace_clearance(request.user, obj):
                    return JsonResponse({'error': 'You do not have workspace clearance to rename this problem.'}, status=403)
            else:
                # Fallback security check for other independent items (like assessment_selection groups)
                branch = getattr(obj, 'branch_location', None) or getattr(obj, 'assigned_folder', None)
                if request.user.user_type != 'IT_Support' and branch and branch.owner != request.user:
                    return JsonResponse({'error': 'You do not have permission to rename this resource.'}, status=403)

            branch = getattr(obj, 'branch_location', None) or getattr(obj, 'assigned_folder', None)
            if not branch:
                return JsonResponse({'error': 'Item is missing its linked folder location.'}, status=400)

            item_full_path = branch.get_parent_path() + branch.name + "/"
            # Sibling uniqueness is among folders under the same parent (AQG section, etc.)
            parent = branch.parent
            exclude_branch_id = branch.id

        # Uniqueness among sibling BranchGroup folders under `parent`, excluding this node
        new_name, error = get_valid_unique_name(
            BranchGroup, parent, new_name, exclude_id=exclude_branch_id
        )
        if error:
            return JsonResponse({'error': error}, status=400)

        username = request.user.username
        from .folder_roots import core_top_level_paths, user_root_path
        protected_roots = core_top_level_paths(username)

        if item_full_path in protected_roots:
            return JsonResponse({'error': 'Cannot rename system folders.'}, status=403)

        if item_full_path.startswith(f"{user_root_path(username)}Courses/") and not request.resolver_match.view_name == 'course_list':
            if request.user.user_type != 'IT_Support' and item_type == 'folder' and obj.name in ['Courses', 'Trash']:
                return JsonResponse({'error': 'Cannot rename Course items here.'}, status=403)

        # --- EXECUTE SYNCHRONIZED DATABASE ATOMIC WRITE ---
        with transaction.atomic():
            if item_type in ['course', 'assessment', 'aqg']:
                obj.name = new_name
                obj.save()

                payload_relation_str = {
                    'course': 'course',
                    'assessment': 'assessment',
                    'aqg': 'aqg',
                }[item_type]
                if hasattr(obj, payload_relation_str):
                    payload_obj = getattr(obj, payload_relation_str)
                    setattr(payload_obj, field_name, new_name)
                    payload_obj.save()

            elif item_type == 'cqd':
                obj.name = new_name
                obj.save()
                if hasattr(obj, 'cqd'):
                    obj.cqd.name = new_name
                    obj.cqd.save(update_fields=['name'])
                    
            elif item_type == 'folder':
                obj.name = new_name
                obj.save()
                
                if hasattr(obj, 'course'):
                    obj.course.name = new_name
                    obj.course.save()
                elif hasattr(obj, 'assessment'):
                    obj.assessment.name = new_name
                    obj.assessment.save()

            elif item_type == 'problem':
                branch = obj.branch_location
                obj.title = new_name
                obj.save()

                # Keep the linked BranchGroup folder name in lockstep with the problem title
                branch.name = new_name
                branch.save()
            else:
                setattr(obj, field_name, new_name)
                obj.save()
                branch = getattr(obj, 'branch_location', None) or getattr(obj, 'assigned_folder', None)
                if branch:
                    branch.name = new_name
                    branch.save()

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

        # Only trash-root children can be restored (not nested descendants).
        if not folder.parent or folder.parent.name != 'Trash':
            return JsonResponse({
                'error': 'Only items at the top of Trash can be restored. Restore the parent folder instead.'
            }, status=400)

        restore_item_from_trash(request, folder)

        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
def _safe_login_next(request, candidate=None):
    """Allow only same-host relative redirect targets after login."""
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = candidate if candidate is not None else (
        request.POST.get('next') or request.GET.get('next') or ''
    )
    nxt = (nxt or '').strip()
    if not nxt:
        return None
    if url_has_allowed_host_and_scheme(
        nxt,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return nxt
    return None


def login_view(request):
    from .auth_throttle import (
        LOCKED_MESSAGE,
        SCOPE_LOGIN,
        apply_progressive_delay,
        clear_failures,
        is_locked,
        record_failure,
    )

    # 1. HANDLE USERS ALREADY LOGGED IN (GET Requests)
    if request.user.is_authenticated and request.method == 'GET':
        if request.user.user_type == 'Student':
            logout(request)
            return redirect('login')
        else:
            nxt = _safe_login_next(request)
            return redirect(nxt or 'dashboard')

    # 2. HANDLE AUTHENTICATION ATTEMPTS (POST Requests)
    if request.method == 'POST':
        if request.user.is_authenticated:
            logout(request)

        identity = (request.POST.get('username') or '').strip()
        nxt = _safe_login_next(request)

        if is_locked(scope=SCOPE_LOGIN, request=request, identity=identity):
            messages.error(request, LOCKED_MESSAGE)
            if nxt:
                return redirect(f"{reverse('login')}?next={nxt}")
            return redirect('login')

        apply_progressive_delay(
            scope=SCOPE_LOGIN, request=request, identity=identity
        )

        # Initialize the standard form with post data
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            # Extract authenticated user records from the valid form payload
            user = form.get_user()
            clear_failures(scope=SCOPE_LOGIN, request=request, identity=identity)
            # Also clear under the authenticated username/email aliases.
            clear_failures(
                scope=SCOPE_LOGIN,
                request=request,
                identity=getattr(user, "username", None),
            )
            if getattr(user, "user_email", None):
                clear_failures(
                    scope=SCOPE_LOGIN,
                    request=request,
                    identity=user.user_email,
                )
            login(request, user)
            try:
                from .password_reset import nullify_password_resets_on_login

                nullify_password_resets_on_login(user)
            except Exception:
                logger.exception(
                    "Failed to nullify password resets after login for user_id=%s",
                    getattr(user, "user_id", None),
                )
            messages.success(request, f"Welcome back, {user_greeting_name(user)}!")
            invite_code = request.session.get(INVITE_SESSION_KEY)
            if invite_code:
                return redirect('course_invite_redeem', code=invite_code)
            parent_invite_code = request.session.get(PARENT_INVITE_SESSION_KEY)
            if parent_invite_code:
                return redirect('parent_invite_redeem', code=parent_invite_code)
            return redirect(nxt or 'dashboard')

        record_failure(scope=SCOPE_LOGIN, request=request, identity=identity)
        if is_locked(scope=SCOPE_LOGIN, request=request, identity=identity):
            messages.error(request, LOCKED_MESSAGE)
        else:
            messages.error(request, "Invalid username or password. Please try again.")
        if nxt:
            return redirect(f"{reverse('login')}?next={nxt}")
        return redirect('login')

    # 3. RENDER BLANK LOGIN FORM (GET Requests)
    form = AuthenticationForm() # Empty form instance for the template context
    reason = request.GET.get('reason')
    if reason == 'multiple_tabs':
        messages.warning(request, "You were logged out because the platform was opened in another tab.")
        
    return render(request, 'assessment_tool/login.html', {
        'form': form,
        'next': _safe_login_next(request) or '',
    })


def forgot_password_view(request):
    from .auth_throttle import (
        LOCKED_MESSAGE,
        SCOPE_PASSWORD_RESET,
        apply_progressive_delay,
        is_locked,
        record_failure,
    )

    if request.user.is_authenticated:
        return redirect('account_settings')

    identifier = ''
    if request.method == 'POST':
        identifier = (request.POST.get('identifier') or '').strip()
        if not identifier:
            messages.error(request, "Enter a username or email.")
            return render(request, 'assessment_tool/forgot_password.html', {
                'identifier': identifier,
            })

        if is_locked(
            scope=SCOPE_PASSWORD_RESET, request=request, identity=identifier
        ):
            messages.error(request, LOCKED_MESSAGE)
            return render(request, 'assessment_tool/forgot_password.html', {
                'identifier': identifier,
            })

        apply_progressive_delay(
            scope=SCOPE_PASSWORD_RESET, request=request, identity=identifier
        )

        from .password_reset import create_password_reset_request

        create_password_reset_request(identifier=identifier)
        # Count every reset request (match or not) so bots cannot spray freely.
        record_failure(
            scope=SCOPE_PASSWORD_RESET, request=request, identity=identifier
        )

        messages.success(
            request,
            "If that username or email matches an account, a password reset link "
            "was sent. The link expires in 15 minutes.",
        )
        return redirect('login')

    return render(request, 'assessment_tool/forgot_password.html', {
        'identifier': identifier,
    })


def password_reset_confirm_view(request, code):
    from .password_reset import (
        complete_password_reset,
        get_reset_by_code,
        reset_is_expired,
    )

    row = get_reset_by_code(code)
    if row is None:
        return render(request, 'assessment_tool/password_reset_confirm.html', {
            'error': "This password reset link is invalid or has already been used.",
        })
    if reset_is_expired(row):
        try:
            row.delete()
        except Exception:
            logger.exception("Failed to delete expired password reset id=%s", getattr(row, "pk", None))
        return render(request, 'assessment_tool/password_reset_confirm.html', {
            'error': "This password reset link has expired. Request a new one.",
        })

    user = row.u
    timeout_time = row.timeout
    if timezone.is_naive(timeout_time):
        timeout_time = timezone.make_aware(timeout_time)
    minutes_left = max(
        0,
        int((timeout_time - timezone.now()).total_seconds() // 60),
    )

    if request.method == 'POST':
        try:
            updated_user = complete_password_reset(
                reset_row=row,
                new_password=request.POST.get('new_password') or '',
                confirm_password=request.POST.get('confirm_password') or '',
            )
            if request.user.is_authenticated:
                logout(request)
            login(
                request,
                updated_user,
                backend='assessment_tool.backends.UsernameOrEmailBackend',
            )
            messages.success(request, "Your password was updated. You are now signed in.")
            return redirect('dashboard')
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect('password_reset_confirm', code=code)

    return render(request, 'assessment_tool/password_reset_confirm.html', {
        'username': getattr(user, 'username', '') or getattr(user, 'user_email', ''),
        'minutes_left': minutes_left,
        'error': None,
    })


@login_required
def course_detail_view(request, course_id):
    course = get_object_or_404(
        Course.objects.select_related('branch_location'),
        id=course_id,
    )
    user_type = request.user.user_type # Pulling from your established profile engine
    unavailable_denied = deny_unavailable_course_entry(request, course)
    if unavailable_denied:
        return unavailable_denied
    if not _user_can_access_course_page(request.user, course):
        messages.error(request, "You do not have access to this course.")
        return redirect('dashboard')

    allow_edit = _user_can_mutate_course_content(request.user, course)
    apply_explorer_mode_from_request(request, allow_edit=allow_edit)

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
        if user_type not in ['Teacher', 'IT_Support'] or not allow_edit:
            messages.error(request, "Unauthorized operation framework.")
            return redirect('course_detail', course_id=course.id)
            
        raw_json_str = request.POST.get('introduction_payload')
        try:
            # Ensure incoming transmission is validated JSON structured block
            json.loads(raw_json_str)
            previous_introduction = course.introduction or ""
            course.introduction = raw_json_str
            course.save()
            from .content_images import track_content_image_html_change
            track_content_image_html_change(
                previous_html=previous_introduction,
                new_html=raw_json_str,
            )
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
def course_management_view(request, course_id):
    course = get_object_or_404(
        Course.objects.select_related('branch_location'),
        id=course_id,
    )
    if not user_can_manage_course(request.user, course):
        messages.error(request, "You do not have permission to manage this course.")
        return redirect('dashboard')
    unavailable_denied = deny_unavailable_course_entry(request, course)
    if unavailable_denied:
        return unavailable_denied
    if not user_can_access_course_management(request.user, course):
        from .folder_roots import WORKSPACE_COURSE_MANAGEMENT_MESSAGE
        messages.error(request, WORKSPACE_COURSE_MANAGEMENT_MESSAGE)
        return redirect('course_detail', course_id=course.id)

    invite_form = CourseInviteForm()
    parent_invite_form = ParentCourseInviteForm()

    if request.method == 'POST':
        action = request.POST.get('action') or ''
        if action == 'close_course':
            if not user_can_close_or_reactivate_course(request.user, course):
                messages.error(
                    request,
                    "Only the main teacher (or IT Support) can close this course.",
                )
                return redirect('course_management', course_id=course.id)
            if course.status != 'active':
                messages.error(
                    request,
                    "Only an active course can be closed from Course Management.",
                )
                return redirect('course_management', course_id=course.id)
            apply_course_status(course, 'closed')
            messages.success(
                request,
                f"Closed '{course.name}'. Students no longer have live access; "
                "they and linked parents can still view historic grades from the Dashboard. "
                "Reactivate the course from the Courses page if you need to edit it again.",
            )
            return redirect('course_list')
        if action == 'create_invite':
            invite_form = CourseInviteForm(request.POST)
            if invite_form.is_valid():
                try:
                    invite = create_course_invite(
                        course=course,
                        created_by=request.user,
                        recipient_raw=invite_form.cleaned_data['recipient'],
                    )
                    redeem_url = request.build_absolute_uri(
                        reverse('course_invite_redeem', kwargs={'code': invite.code})
                    )
                    if invite.target_user_id:
                        messages.success(
                            request,
                            "Invitation created. The student was notified and must open "
                            f"the invite link to accept before they are enrolled. Link: {redeem_url}",
                        )
                    else:
                        messages.success(
                            request,
                            f"Invitation created. Share this link with the student: {redeem_url}",
                        )
                    return redirect('course_management', course_id=course.id)
                except ValueError as exc:
                    messages.error(request, str(exc))
                except IntegrityError:
                    messages.error(
                        request,
                        "Could not create invitation (duplicate pending invite or database conflict).",
                    )
        elif action == 'void_invite':
            invite_id = request.POST.get('invite_id')
            invite = get_object_or_404(
                UserCourseActivation,
                pk=invite_id,
                course=course,
            )
            try:
                void_course_invite(invite)
                messages.success(
                    request,
                    "Invitation voided and removed. "
                    "Any seat credit spent on this unused invite was reimbursed.",
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('course_management', course_id=course.id)
        elif action == 'kick_student':
            student_id = request.POST.get('student_id')
            student = get_object_or_404(
                UserProfile,
                pk=student_id,
                user_type='Student',
            )
            try:
                summary = kick_student_from_course(
                    course=course,
                    student=student,
                    removed_by=request.user,
                )
                msg = (
                    f"{student.username} was removed from the course. "
                    "Their live progress for this enrollment was deleted."
                )
                if summary.get("credit_reimbursement_pending"):
                    msg += (
                        " Recorded grades for this enrollment period were not kept "
                        "on a transcript because the student was enrolled for less than one week. "
                        "The seat credit for this student was reimbursed."
                    )
                elif summary.get("grade_rows"):
                    msg += (
                        f" {summary['grade_rows']} grade record(s) were kept on the "
                        "transcript for this enrollment period."
                    )
                else:
                    msg += (
                        " No grade transcript was recorded for this enrollment period."
                    )
                messages.success(request, msg)
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('course_management', course_id=course.id)
        elif action == 'grant_parent_access':
            parent_id = request.POST.get('parent_id')
            student_id = request.POST.get('student_id')
            parent = get_object_or_404(UserProfile, pk=parent_id, user_type='Parent')
            student = get_object_or_404(UserProfile, pk=student_id, user_type='Student')
            try:
                grant_parent_access(
                    course=course,
                    parent=parent,
                    student=student,
                    created_by=request.user,
                )
                messages.success(
                    request,
                    f"Granted grade access for {parent.username} to view {student.username}.",
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('course_management', course_id=course.id)
        elif action == 'revoke_parent_access':
            parent_id = request.POST.get('parent_id')
            student_id = request.POST.get('student_id')
            parent = get_object_or_404(UserProfile, pk=parent_id, user_type='Parent')
            student = get_object_or_404(UserProfile, pk=student_id, user_type='Student')
            try:
                removed = revoke_parent_access(
                    course=course,
                    parent=parent,
                    student=student,
                )
                if removed:
                    messages.success(
                        request,
                        f"Revoked grade access for {parent.username} "
                        f"(student {student.username}) in this course.",
                    )
                else:
                    messages.info(request, "That parent did not have access for this course.")
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('course_management', course_id=course.id)
        elif action == 'create_parent_invite':
            parent_invite_form = ParentCourseInviteForm(request.POST)
            if parent_invite_form.is_valid():
                student = get_object_or_404(
                    UserProfile,
                    pk=parent_invite_form.cleaned_data['student_id'],
                    user_type='Student',
                )
                try:
                    invite = create_parent_invite(
                        course=course,
                        created_by=request.user,
                        student=student,
                        parent_email_raw=parent_invite_form.cleaned_data['parent_email'],
                    )
                    redeem_url = request.build_absolute_uri(
                        reverse('parent_invite_redeem', kwargs={'code': invite.code})
                    )
                    if invite.target_user_id:
                        messages.success(
                            request,
                            "Parent invitation created. The parent was notified and must open "
                            f"the invite link to accept. Link: {redeem_url}",
                        )
                    else:
                        messages.success(
                            request,
                            f"Parent invitation created. Share this link: {redeem_url}",
                        )
                    return redirect('course_management', course_id=course.id)
                except ValueError as exc:
                    messages.error(request, str(exc))
                except IntegrityError:
                    messages.error(
                        request,
                        "Could not create parent invitation "
                        "(duplicate pending invite or database conflict).",
                    )
        elif action == 'void_parent_invite':
            invite_id = request.POST.get('invite_id')
            invite = ParentCourseInvitation.objects.filter(
                pk=invite_id,
                course=course,
            ).first()
            if invite is None:
                messages.warning(
                    request,
                    "This parent invitation cannot be voided because it was already "
                    "accepted. Refresh the page, then use Revoke on the parent’s grade "
                    "access for that student if you no longer want them to view grades "
                    "for this course.",
                )
            else:
                try:
                    void_parent_invite(invite)
                    messages.success(request, "Parent invitation voided and removed.")
                except ValueError as exc:
                    messages.error(request, str(exc))
            return redirect('course_management', course_id=course.id)
        elif action == 'lookup_teacher':
            # Handled via dedicated JSON endpoint; keep for safety.
            messages.error(request, "Use the teacher lookup field to preview before inviting.")
            return redirect('course_management', course_id=course.id)
        elif action == 'invite_teacher':
            if not user_can_manage_teachers(request.user, course):
                messages.error(request, "Only the main teacher can invite co-teachers.")
                return redirect('course_management', course_id=course.id)
            recipient = (request.POST.get('teacher_recipient') or '').strip()
            try:
                invite = create_teacher_invite(
                    course=course,
                    created_by=request.user,
                    recipient_raw=recipient,
                )
                messages.success(
                    request,
                    f"Invitation sent to {invite.invitee.username}. "
                    "They must accept from Notifications before gaining access.",
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            except IntegrityError:
                messages.error(
                    request,
                    "Could not create co-teacher invitation (duplicate or database conflict).",
                )
            return redirect('course_management', course_id=course.id)
        elif action == 'void_teacher_invite':
            invite_id = request.POST.get('invite_id')
            invite = TeacherCourseInvitation.objects.filter(
                pk=invite_id, course=course
            ).first()
            if invite is None:
                messages.warning(request, "That co-teacher invitation was already removed.")
            else:
                try:
                    void_teacher_invite(invite, by_user=request.user)
                    messages.success(request, "Co-teacher invitation voided.")
                except ValueError as exc:
                    messages.error(request, str(exc))
            return redirect('course_management', course_id=course.id)
        elif action == 'remove_teacher':
            teacher_id = request.POST.get('teacher_id')
            teacher = get_object_or_404(
                UserProfile.objects.filter(user_type__in=("Teacher", "IT_Support")),
                pk=teacher_id,
            )
            try:
                remove_teacher_from_course(
                    course=course,
                    teacher=teacher,
                    removed_by=request.user,
                )
                messages.success(
                    request,
                    f"Removed {teacher.username} as a teacher of this course.",
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('course_management', course_id=course.id)
        elif action == 'leave_as_teacher':
            try:
                leave_course_as_teacher(course=course, teacher=request.user)
                messages.success(request, "You left this course as a co-teacher.")
                return redirect('dashboard')
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('course_management', course_id=course.id)
        elif action == 'transfer_ownership':
            teacher_id = request.POST.get('teacher_id')
            new_owner = get_object_or_404(
                UserProfile.objects.filter(user_type__in=("Teacher", "IT_Support")),
                pk=teacher_id,
            )
            try:
                transfer_course_ownership(
                    course=course,
                    new_owner=new_owner,
                    by_user=request.user,
                )
                messages.success(
                    request,
                    f"Ownership transferred to {new_owner.username}. "
                    "They are now the main teacher.",
                )
            except ValueError as exc:
                messages.error(request, str(exc))
            return redirect('course_management', course_id=course.id)

    enrolled_slots = (
        UsersInCourse.objects.filter(
            course=course,
            user__isnull=False,
            user__user_type='Student',
        )
        .select_related('user')
        .order_by(
            'user__user_last_name',
            'user__user_first_name',
            'user__username',
        )
    )
    enrolled_students = []
    for slot in enrolled_slots:
        student = slot.user
        enrollment = get_active_enrollment(course, student)
        if enrollment is None:
            enrollment = ensure_active_enrollment(
                course=course, user=student, slot=slot
            )
        within_week = enrollment_within_credit_reimbursement_window(enrollment)
        enrolled_students.append({
            'user_id': student.user_id,
            'display_name': user_display_name(student),
            'username': student.username,
            'email': student.user_email or '',
            'user_access': slot.user_access or '',
            'enrolled_at': enrollment.started_at or slot.creation_date,
            'within_reimbursement_window': within_week,
        })

    invites = list(
        UserCourseActivation.objects.filter(
            course=course,
            status=UserCourseActivation.STATUS_PENDING,
        )
        .select_related('target_user', 'created_by', 'slot')
        .order_by('-creation_date', '-pk')
    )
    # Live check: unclaimed email invites may match an account created after the invite.
    emails_to_check = {
        (inv.temp_email or '').strip().lower()
        for inv in invites
        if not inv.target_user_id and inv.temp_email
    }
    existing_emails = set()
    if emails_to_check:
        existing_emails = {
            (email or '').strip().lower()
            for email in UserProfile.objects.filter(
                user_email__in=emails_to_check
            ).values_list('user_email', flat=True)
        }

    invite_rows = []
    for inv in invites:
        target = inv.target_user
        if target:
            recipient = target.username
            if target.user_email:
                recipient = f"{target.username} ({target.user_email})"
            account_exists = True
        else:
            recipient = inv.temp_email or inv.invited_username or '—'
            email_key = (inv.temp_email or '').strip().lower()
            account_exists = bool(email_key and email_key in existing_emails)
            if not account_exists and inv.invited_username:
                # Username invites normally set target_user; keep a live fallback.
                account_exists = UserProfile.objects.filter(
                    username__iexact=inv.invited_username
                ).exists()
        invite_kind = 'username' if inv.invited_username else 'email'
        status = inv.status
        invite_rows.append({
            'invite': inv,
            'recipient': recipient,
            'kind': invite_kind,
            'status': status,
            'status_label': invite_status_label(status),
            'awaiting_student': status == UserCourseActivation.STATUS_PENDING,
            'account_exists': account_exists,
            'redeem_url': request.build_absolute_uri(
                reverse('course_invite_redeem', kwargs={'code': inv.code})
            ),
            'can_void': status == UserCourseActivation.STATUS_PENDING,
        })

    parent_access_rows = parent_access_rows_for_course(course)

    parent_invites = list(
        ParentCourseInvitation.objects.filter(
            course=course,
            status=ParentCourseInvitation.STATUS_PENDING,
        )
        .select_related('target_user', 'created_by', 'student')
        .order_by('-creation_date', '-pk')
    )
    parent_emails_to_check = {
        (inv.temp_email or '').strip().lower()
        for inv in parent_invites
        if not inv.target_user_id and inv.temp_email
    }
    parent_existing_emails = set()
    if parent_emails_to_check:
        parent_existing_emails = {
            (email or '').strip().lower()
            for email in UserProfile.objects.filter(
                user_email__in=parent_emails_to_check
            ).values_list('user_email', flat=True)
        }

    parent_invite_rows = []
    for inv in parent_invites:
        target = inv.target_user
        if target:
            recipient = target.username
            if target.user_email:
                recipient = f"{target.username} ({target.user_email})"
            account_exists = True
        else:
            recipient = inv.temp_email or '—'
            email_key = (inv.temp_email or '').strip().lower()
            account_exists = bool(email_key and email_key in parent_existing_emails)
        student = inv.student
        parent_invite_rows.append({
            'invite': inv,
            'recipient': recipient,
            'student_name': user_display_name(student) if student else '—',
            'student_username': student.username if student else '—',
            'status': inv.status,
            'status_label': parent_invite_status_label(inv.status),
            'account_exists': account_exists,
            'redeem_url': request.build_absolute_uri(
                reverse('parent_invite_redeem', kwargs={'code': inv.code})
            ),
            'can_void': inv.status == ParentCourseInvitation.STATUS_PENDING,
        })

    from .credits import get_balance, teacher_is_unlocked

    # Fresh balance after invite/void/kick redirects.
    acting_teacher = UserProfile.objects.filter(pk=request.user.pk).first() or request.user

    return render(request, 'assessment_tool/course_management.html', {
        'course': course,
        'user_type': request.user.user_type,
        'active_tab': 'management',
        'invite_form': invite_form,
        'parent_invite_form': parent_invite_form,
        'enrolled_students': enrolled_students,
        'invite_rows': invite_rows,
        'parent_access_rows': parent_access_rows,
        'parent_invite_rows': parent_invite_rows,
        'teacher_rows': list_course_teacher_rows(course=course, viewer=request.user),
        'can_manage_teachers': user_can_manage_teachers(request.user, course),
        'can_close_course': (
            user_can_close_or_reactivate_course(request.user, course)
            and course.status == 'active'
        ),
        'teacher_lookup_url': reverse(
            'course_teacher_lookup', kwargs={'course_id': course.id}
        ),
        'highlight_invite_id': request.GET.get('invite'),
        'highlight_parent_invite_id': request.GET.get('parent_invite'),
        'credit_balance': get_balance(acting_teacher),
        'teacher_credits_unlocked': teacher_is_unlocked(acting_teacher),
        'credits_account_url': reverse('account_settings') + '?tab=credits',
    })


@login_required
@require_GET
def course_teacher_lookup_api(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if not user_can_manage_course(request.user, course):
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    if not user_can_manage_teachers(request.user, course):
        return JsonResponse(
            {'error': 'Only the main teacher can look up co-teachers.'},
            status=403,
        )
    recipient = (request.GET.get('q') or '').strip()
    try:
        preview = lookup_teacher_for_invite(course=course, recipient_raw=recipient)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'teacher': preview})


@login_required
@require_http_methods(['GET', 'POST'])
def teacher_invite_redeem_view(request, code):
    invite = (
        TeacherCourseInvitation.objects.select_related(
            'course', 'invitee', 'invited_by'
        )
        .filter(code=code)
        .first()
    )
    if invite is None or not teacher_invite_is_redeemable(invite):
        return render(
            request,
            'assessment_tool/teacher_invite_redeem.html',
            {
                'error': (
                    'This co-teacher invitation is invalid, expired, or already used.'
                ),
                'invite': invite,
            },
        )

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        try:
            if action == 'accept':
                accept_teacher_invite(invite=invite, user=request.user)
                messages.success(
                    request,
                    f"You joined “{invite.course.name}” as a co-teacher.",
                )
                return redirect('course_detail', course_id=invite.course_id)
            if action == 'reject':
                reject_teacher_invite(invite=invite, user=request.user)
                messages.success(request, "Invitation declined.")
                return redirect('notifications')
            messages.error(request, "Unknown action.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect('teacher_invite_redeem', code=code)

    return render(
        request,
        'assessment_tool/teacher_invite_redeem.html',
        {
            'invite': invite,
            'course': invite.course,
            'inviter_name': user_display_name(invite.invited_by)
            or invite.invited_by.username,
            'is_invitee': request.user.user_id == invite.invitee_id,
        },
    )


def course_invite_redeem_view(request, code):
    invite = get_invite_by_code(code)
    block = redeem_block_reason(invite)
    if block:
        return render(request, 'assessment_tool/invite_redeem.html', {
            'error': block,
            'invite': invite,
        })

    # Unclaimed email invite: let visitor choose signup vs existing-account login
    if is_unclaimed_email_invite(invite) and not request.user.is_authenticated:
        request.session[INVITE_SESSION_KEY] = code
        return render(request, 'assessment_tool/invite_redeem.html', {
            'invite': invite,
            'mode': 'choose',
            'course': invite.course,
            'invited_email': invite.temp_email,
        })

    # Claimed by a new user who still needs to verify, or existing / alternate accept path
    if request.user.is_authenticated:
        if request.user.user_type != 'Student':
            return render(request, 'assessment_tool/invite_redeem.html', {
                'error': (
                    f"Your account is registered as {request.user.user_type}, not as a Student, "
                    "so it cannot be enrolled in a course with a student invitation. "
                    "Log out and use a Student account, or ask your teacher to invite you "
                    "as a co-Teacher (see Q&A for details) if that applies."
                ),
                'invite': invite,
                'mode': 'non_student',
            })

        if user_already_enrolled_in_course(invite.course, request.user):
            msg = handle_already_enrolled_invite_access(invite, request.user)
            request.session.pop(INVITE_SESSION_KEY, None)
            return render(request, 'assessment_tool/invite_redeem.html', {
                'invite': invite,
                'mode': 'already_enrolled',
                'course': invite.course,
                'message': msg,
            })

        matches = user_matches_invite(request.user, invite)
        alternate_ok = is_unclaimed_email_invite(invite) and not matches
        if not matches and not alternate_ok:
            messages.error(
                request,
                "This invitation is for a different account. Log out and use the correct account.",
            )
            return render(request, 'assessment_tool/invite_redeem.html', {
                'error': 'Invitation does not match the signed-in account.',
                'invite': invite,
            })

        if request.user.unactivated_account:
            request.session[INVITE_SESSION_KEY] = code
            messages.info(request, "Verify your email before joining the course.")
            return redirect('verify_email')

        if request.method == 'POST' and request.POST.get('action') == 'accept':
            enrolled, msg = enroll_user_from_invite(invite, request.user)
            request.session.pop(INVITE_SESSION_KEY, None)
            if enrolled:
                messages.success(request, msg)
                return redirect('dashboard')
            # Already enrolled (or other soft failure) — show on invite page when relevant
            if user_already_enrolled_in_course(invite.course, request.user):
                return render(request, 'assessment_tool/invite_redeem.html', {
                    'invite': invite,
                    'mode': 'already_enrolled',
                    'course': invite.course,
                    'message': msg,
                })
            messages.warning(request, msg)
            return redirect('dashboard')

        different_email = bool(
            alternate_ok
            or (
                invite.temp_email
                and request.user.user_email
                and invite.temp_email.lower() != request.user.user_email.lower()
            )
        )
        return render(request, 'assessment_tool/invite_redeem.html', {
            'invite': invite,
            'mode': 'accept_alternate' if different_email else 'accept',
            'course': invite.course,
            'invited_email': invite.temp_email,
            'account_email': request.user.user_email,
            'account_username': request.user.username,
        })

    # Logged out: claimed / existing-user invite → login first
    request.session[INVITE_SESSION_KEY] = code
    messages.info(request, "Log in to accept this course invitation.")
    return redirect('login')


def course_invite_signup_view(request, code):
    invite = get_invite_by_code(code)
    block = redeem_block_reason(invite)
    if block:
        return render(request, 'assessment_tool/invite_redeem.html', {
            'error': block,
            'invite': invite,
        })

    if invite.target_user_id:
        # Already claimed — send them to redeem/accept/verify
        return redirect('course_invite_redeem', code=code)

    if not invite.temp_email:
        return render(request, 'assessment_tool/invite_redeem.html', {
            'error': 'This invitation cannot be used for new account signup.',
            'invite': invite,
        })

    # If email now belongs to an existing user, switch to redeem/accept
    if UserProfile.objects.filter(user_email__iexact=invite.temp_email).exists():
        return redirect('course_invite_redeem', code=code)

    if request.user.is_authenticated:
        # Existing signed-in student can accept an unclaimed email invite instead
        if request.user.user_type == 'Student' and is_unclaimed_email_invite(invite):
            return redirect('course_invite_redeem', code=code)
        messages.info(request, "Log out before creating a new student account from an invitation.")
        return redirect('dashboard')

    request.session[INVITE_SESSION_KEY] = code

    if request.method == 'POST':
        form = StudentRegistrationForm(request.POST, locked_email=invite.temp_email)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = UserProfile.objects.create_student_user(
                        username=form.cleaned_data['username'],
                        user_email=form.cleaned_data['email'],
                        password=form.cleaned_data['password'],
                        user_first_name=form.cleaned_data['first_name'],
                        user_last_name=form.cleaned_data['last_name'],
                        gender=form.cleaned_data['gender'],
                        user_display_name=form.cleaned_data.get('display_name'),
                        unactivated_account=True,
                    )
                    auth = EmailAuthentication.generate_auth_record(user, form.cleaned_data['email'])
                    claim_invite_for_new_user(invite, user)
                    request.session[INVITE_SESSION_KEY] = code
                    from .mail import send_verification_code_email
                    send_verification_code_email(to_email=auth.temp_email, code=auth.code)
                    messages.success(
                        request,
                        "Account created. Log in, then enter the email verification code "
                        "sent to your email.",
                    )
                    return redirect('login')
            except ValueError as exc:
                messages.error(request, str(exc))
            except IntegrityError as e:
                err_msg = str(e)
                if 'user_email' in err_msg:
                    messages.error(request, "That email is already registered.")
                elif 'username' in err_msg:
                    messages.error(request, "That username is already taken.")
                else:
                    messages.error(request, "A database error occurred. Please try again.")
    else:
        form = StudentRegistrationForm(locked_email=invite.temp_email)

    return render(request, 'assessment_tool/student_register.html', {
        'form': form,
        'invite': invite,
        'course': invite.course,
        'locked_email': invite.temp_email,
        'invite_code': code,
    })


def parent_invite_redeem_view(request, code):
    invite = get_parent_invite_by_code(code)
    block = parent_redeem_block_reason(invite)
    if block:
        return render(request, 'assessment_tool/parent_invite_redeem.html', {
            'error': block,
            'invite': invite,
        })

    student_name = user_display_name(invite.student)

    if is_unclaimed_parent_email_invite(invite) and not request.user.is_authenticated:
        request.session[PARENT_INVITE_SESSION_KEY] = code
        return render(request, 'assessment_tool/parent_invite_redeem.html', {
            'invite': invite,
            'mode': 'choose',
            'course': invite.course,
            'student_name': student_name,
            'invited_email': invite.temp_email,
        })

    if request.user.is_authenticated:
        if request.user.user_type != 'Parent':
            msg = handle_non_parent_invite_access(invite, request.user)
            return render(request, 'assessment_tool/parent_invite_redeem.html', {
                'error': msg,
                'invite': invite,
                'mode': 'non_parent',
            })

        if parent_has_course_access(
            parent=request.user,
            student=invite.student,
            course=invite.course,
        ):
            msg = handle_parent_already_has_access(invite, request.user)
            request.session.pop(PARENT_INVITE_SESSION_KEY, None)
            return render(request, 'assessment_tool/parent_invite_redeem.html', {
                'invite': invite,
                'mode': 'already_has_access',
                'course': invite.course,
                'student_name': student_name,
                'message': msg,
            })

        matches = parent_user_matches_invite(request.user, invite)
        alternate_ok = is_unclaimed_parent_email_invite(invite) and not matches
        if not matches and not alternate_ok:
            messages.error(
                request,
                "This invitation is for a different account. Log out and use the correct account.",
            )
            return render(request, 'assessment_tool/parent_invite_redeem.html', {
                'error': 'Invitation does not match the signed-in account.',
                'invite': invite,
            })

        if request.user.unactivated_account:
            request.session[PARENT_INVITE_SESSION_KEY] = code
            messages.info(request, "Verify your email before accepting parent grade access.")
            return redirect('verify_email')

        if request.method == 'POST' and request.POST.get('action') == 'accept':
            granted, msg = accept_parent_invite(invite, request.user)
            request.session.pop(PARENT_INVITE_SESSION_KEY, None)
            if granted:
                messages.success(request, msg)
                return redirect('dashboard')
            if parent_has_course_access(
                parent=request.user,
                student=invite.student,
                course=invite.course,
            ):
                return render(request, 'assessment_tool/parent_invite_redeem.html', {
                    'invite': invite,
                    'mode': 'already_has_access',
                    'course': invite.course,
                    'student_name': student_name,
                    'message': msg,
                })
            messages.warning(request, msg)
            return redirect('dashboard')

        different_email = bool(
            alternate_ok
            or (
                invite.temp_email
                and request.user.user_email
                and invite.temp_email.lower() != request.user.user_email.lower()
            )
        )
        return render(request, 'assessment_tool/parent_invite_redeem.html', {
            'invite': invite,
            'mode': 'accept_alternate' if different_email else 'accept',
            'course': invite.course,
            'student_name': student_name,
            'invited_email': invite.temp_email,
            'account_email': request.user.user_email,
            'account_username': request.user.username,
        })

    request.session[PARENT_INVITE_SESSION_KEY] = code
    messages.info(request, "Log in to accept this parent grade-access invitation.")
    return redirect('login')


def parent_invite_signup_view(request, code):
    invite = get_parent_invite_by_code(code)
    block = parent_redeem_block_reason(invite)
    if block:
        return render(request, 'assessment_tool/parent_invite_redeem.html', {
            'error': block,
            'invite': invite,
        })

    if invite.target_user_id:
        return redirect('parent_invite_redeem', code=code)

    if not invite.temp_email:
        return render(request, 'assessment_tool/parent_invite_redeem.html', {
            'error': 'This invitation cannot be used for new account signup.',
            'invite': invite,
        })

    if UserProfile.objects.filter(user_email__iexact=invite.temp_email).exists():
        return redirect('parent_invite_redeem', code=code)

    if request.user.is_authenticated:
        if request.user.user_type == 'Parent' and is_unclaimed_parent_email_invite(invite):
            return redirect('parent_invite_redeem', code=code)
        messages.info(request, "Log out before creating a new Parent account from an invitation.")
        return redirect('dashboard')

    request.session[PARENT_INVITE_SESSION_KEY] = code

    if request.method == 'POST':
        form = ParentRegistrationForm(request.POST, locked_email=invite.temp_email)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = UserProfile.objects.create_parent_user(
                        username=form.cleaned_data['username'],
                        user_email=form.cleaned_data['email'],
                        password=form.cleaned_data['password'],
                        user_first_name=form.cleaned_data['first_name'],
                        user_last_name=form.cleaned_data['last_name'],
                        gender=form.cleaned_data['gender'],
                        user_display_name=form.cleaned_data.get('display_name'),
                        unactivated_account=True,
                    )
                    auth = EmailAuthentication.generate_auth_record(user, form.cleaned_data['email'])
                    claim_parent_invite_for_new_user(invite, user)
                    request.session[PARENT_INVITE_SESSION_KEY] = code
                    from .mail import send_verification_code_email
                    send_verification_code_email(to_email=auth.temp_email, code=auth.code)
                    messages.success(
                        request,
                        "Parent account created. Log in, then enter the email verification code "
                        "sent to your email.",
                    )
                    return redirect('login')
            except ValueError as exc:
                messages.error(request, str(exc))
            except IntegrityError as e:
                err_msg = str(e)
                if 'user_email' in err_msg:
                    messages.error(request, "That email is already registered.")
                elif 'username' in err_msg:
                    messages.error(request, "That username is already taken.")
                else:
                    messages.error(request, "A database error occurred. Please try again.")
    else:
        form = ParentRegistrationForm(locked_email=invite.temp_email)

    return render(request, 'assessment_tool/parent_register.html', {
        'form': form,
        'invite': invite,
        'course': invite.course,
        'student_name': user_display_name(invite.student),
        'locked_email': invite.temp_email,
        'invite_code': code,
    })


@login_required
def assessment_view(request, course_id):
    # 1. Grab the current course structure context
    course = get_object_or_404(Course, id=course_id)

    unavailable_denied = deny_unavailable_course_entry(request, course)
    if unavailable_denied:
        return unavailable_denied
    if not _user_can_access_course_page(request.user, course):
        messages.error(request, "You do not have access to this course.")
        return redirect('dashboard')

    # 2. Extract current user type session flags from user request profile if needed
    user_type = getattr(request.user, 'user_type', 'Student')

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

    from .student_attempts import (
        assessment_is_takeable,
        generation_job_blocks_edits,
        job_status_payload,
        latest_generation_job,
    )
    from .course_enrollment import get_active_enrollment as _get_active_enrollment

    highlight_id = request.GET.get("highlight")
    try:
        highlight_id = int(highlight_id) if highlight_id else None
    except (TypeError, ValueError):
        highlight_id = None

    is_student = user_type == "Student"
    assessment_rows = []
    now = timezone.now()
    if is_student:
        from .assessment_options import select_counting_attempt
        from .student_attempts import (
            student_facing_assessment_status,
            student_may_start_attempt,
        )

        assessments = assessments.exclude(
            status__in=("hidden", "deleted")
        )
        enrollment = _get_active_enrollment(course=course, user=request.user)
        attempts_by_assessment = {}
        if enrollment:
            from .student_attempts import (
                assessment_ids_for_template,
                course_template_assessment,
            )

            take_ids = []
            for a in assessments:
                take_ids.extend(assessment_ids_for_template(a))
            for att in StudentAssessmentAttempt.objects.filter(
                enrollment=enrollment,
                assessment_id__in=take_ids,
            ).select_related("assessment").order_by("id"):
                root = course_template_assessment(att.assessment)
                if root is None:
                    continue
                attempts_by_assessment.setdefault(root.id, []).append(att)

        for assessment in assessments:
            attempts = attempts_by_assessment.get(assessment.id) or []
            counting = select_counting_attempt(attempts, assessment)
            submitted_attempts = [
                a
                for a in attempts
                if a.status == StudentAssessmentAttempt.STATUS_SUBMITTED
                or a.auto_graded_at is not None
            ]
            in_progress = next(
                (
                    a
                    for a in reversed(attempts)
                    if a.status == StudentAssessmentAttempt.STATUS_IN_PROGRESS
                ),
                None,
            )
            display_attempt = counting or in_progress or (attempts[-1] if attempts else None)
            takeable = assessment_is_takeable(assessment, now=now)
            can_start = student_may_start_attempt(
                assessment, request.user, attempts, now=now
            )
            submitted = bool(submitted_attempts)
            from .assessment_grades import student_may_review_attempt

            reviewable_attempts = [
                a
                for a in submitted_attempts
                if student_may_review_attempt(assessment, a)
            ]
            can_review = bool(reviewable_attempts)
            review_attempts = []
            for a in sorted(
                reviewable_attempts,
                key=lambda x: x.submitted_at or x.creation_date or x.id,
                reverse=True,
            ):
                review_attempts.append(
                    {
                        "attempt_id": a.id,
                        "status": a.status,
                        "submitted_at": a.submitted_at.isoformat()
                        if a.submitted_at
                        else None,
                        "earned_points": a.earned_points,
                        "max_points": a.max_points,
                        "is_counting": counting is not None and a.id == counting.id,
                        "review_url": reverse(
                            "course_grades_attempt",
                            args=[course.id, assessment.id, a.id],
                        ),
                    }
                )

            counting_reviewable = (
                counting
                if counting is not None and student_may_review_attempt(assessment, counting)
                else None
            )
            facing_status = student_facing_assessment_status(assessment, now=now)
            assessment_rows.append(
                {
                    "assessment": assessment,
                    "takeable": takeable,
                    "can_start": can_start,
                    "submitted": submitted,
                    "attempt_status": display_attempt.status if display_attempt else None,
                    "counting_attempt_id": counting.id if counting else None,
                    "can_review": can_review,
                    "review_attempt_count": len(reviewable_attempts),
                    "review_url": (
                        reverse(
                            "course_grades_attempt",
                            args=[course.id, assessment.id, counting_reviewable.id],
                        )
                        if counting_reviewable
                        else (
                            reverse(
                                "course_grades_attempt",
                                args=[
                                    course.id,
                                    assessment.id,
                                    reviewable_attempts[0].id,
                                ],
                            )
                            if reviewable_attempts
                            else None
                        )
                    ),
                    "review_attempts": review_attempts,
                    "review_attempts_json": json.dumps(review_attempts),
                    "highlight": highlight_id == assessment.id,
                    "display_status": facing_status,
                    "show_auto_open": facing_status == "upcoming",
                }
            )
    else:
        from .assessment_options import ASSESSMENT_DELIVERY_OPTION_GROUPS
        from .student_attempts import (
            assessment_has_submissions,
            normalize_assessment_status,
        )

        custom_delivery_ids = set(
            AssessmentOptions.objects.filter(
                assessment_id__in=[a.id for a in assessments],
                option_type_id__in=ASSESSMENT_DELIVERY_OPTION_GROUPS,
            )
            .values_list("assessment_id", flat=True)
            .distinct()
        )

        for assessment in assessments:
            job = latest_generation_job(assessment)
            stored_status = normalize_assessment_status(assessment.status)
            assessment_rows.append(
                {
                    "assessment": assessment,
                    "generating": generation_job_blocks_edits(assessment),
                    "job": job_status_payload(assessment),
                    "highlight": highlight_id == assessment.id,
                    "has_custom_delivery_options": assessment.id in custom_delivery_ids,
                    "has_submissions": assessment_has_submissions(assessment),
                    "display_status": stored_status,
                    "show_auto_open": stored_status == "upcoming",
                }
            )

    show_auto_open_column = any(r.get("show_auto_open") for r in assessment_rows)
    show_submission_column = is_student and any(
        r.get("can_review") for r in assessment_rows
    )
    if is_student:
        empty_colspan = 3  # name, status, actions
        if show_auto_open_column:
            empty_colspan += 1
        if show_submission_column:
            empty_colspan += 1
    else:
        empty_colspan = 5  # drag, name, status, questions, actions
        if show_auto_open_column:
            empty_colspan += 1

    from .credits import assert_can_print

    context = {
        'course': course,
        'user_type': user_type,
        'assessments': assessments,
        'assessment_rows': assessment_rows,
        'is_student': is_student,
        'show_submission_column': show_submission_column,
        'show_auto_open_column': show_auto_open_column,
        'empty_colspan': empty_colspan,
        'active_tab': 'assessments',
        'current_time': now,
        'highlight_id': highlight_id,
        'can_print_assessments': (not is_student) and assert_can_print(request.user),
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
                status='hidden',  # Not visible to students until opened
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
    from .student_attempts import (
        ASSESSMENT_STATUSES,
        assessment_has_submissions,
        normalize_assessment_status,
    )

    new_status = normalize_assessment_status(new_status)
    if new_status not in ASSESSMENT_STATUSES:
        return JsonResponse(
            {'error': 'Target lifecycle flag is not registered inside status enum.'},
            status=400,
        )

    assessment = get_object_or_404(Assessment, id=assessment_id, course_id=course_id)

    from .student_attempts import generation_job_blocks_edits, start_generation_job, job_status_payload

    course = assessment.course
    if course is not None and (
        course_is_deleted(course)
        or (
            course_is_closed(course)
            and getattr(request.user, "user_type", None) == "Teacher"
        )
    ):
        return JsonResponse(
            {"error": "This course is unavailable. Restore or reactivate it first."},
            status=403,
        )

    if generation_job_blocks_edits(assessment):
        return JsonResponse(
            {
                'error': 'Unique student assessments are still being generated. Status cannot be changed yet.',
                'code': 'generation_in_progress',
                'job': job_status_payload(assessment),
            },
            status=409,
        )

    if new_status == 'hidden' and assessment_has_submissions(assessment):
        return JsonResponse(
            {
                'error': (
                    'Cannot hide an assessment that already has student submissions.'
                ),
            },
            status=400,
        )

    if new_status in ('open', 'upcoming'):
        from .assessment_sync import synchronization_preflight

        sync_result = synchronization_preflight(
            assessment,
            1,
            decision=data.get('synchronization_decision'),
            created_by=request.user,
        )
        if not sync_result.get('ready'):
            return JsonResponse(sync_result, status=409)

    assessment.status = new_status
    assessment.save(update_fields=['status'])

    finalize_payload = None
    if new_status == 'closed':
        from .student_attempts import close_assessment_and_finalize_attempts

        finalize_payload = close_assessment_and_finalize_attempts(
            assessment,
            reason='teacher_closed',
            set_status=False,  # already saved above
        )

    job_payload = None
    if new_status == 'open':
        job = start_generation_job(assessment)
        job_payload = job_status_payload(assessment) if job else None

    return JsonResponse({
        'success': True,
        'job': job_payload,
        'finalize': finalize_payload,
    })


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

    from .student_attempts import generation_job_blocks_edits, job_status_payload

    if generation_job_blocks_edits(assessment):
        return JsonResponse(
            {
                'error': 'Unique student assessments are still being generated. Window cannot be changed yet.',
                'code': 'generation_in_progress',
                'job': job_status_payload(assessment),
            },
            status=409,
        )

    # Process updates or strip values to None if matching disable checks
    parsed_start = None
    parsed_end = None

    def _parse_window_instant(raw):
        """Parse ISO (preferring explicit offset/Z) into an aware UTC datetime."""
        text = str(raw).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = timezone.datetime.fromisoformat(text)
        if timezone.is_naive(dt):
            # Legacy datetime-local without offset: treat as server TIME_ZONE.
            return timezone.make_aware(dt)
        return dt

    if start_raw and end_raw:
        try:
            parsed_start = _parse_window_instant(start_raw)
            parsed_end = _parse_window_instant(end_raw)
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Invalid date string layout tracking parameters.'}, status=400)

        # 🛑 Backend Validation Rule Check: Start must precede End
        if parsed_start >= parsed_end:
            return JsonResponse({'error': 'The start date configuration must be before the terminal target boundary.'}, status=400)

    # Persist values to database
    assessment.start_time = parsed_start
    assessment.end_time = parsed_end
    assessment.modified_date = timezone.now()
    assessment.save(update_fields=["start_time", "end_time", "modified_date"])

    return JsonResponse({
        'success': True,
        'assessment_id': assessment.id,
        'status': assessment.status,
        'start_time': assessment.start_time.isoformat() if assessment.start_time else None,
        'end_time': assessment.end_time.isoformat() if assessment.end_time else None,
    })


@login_required
@require_GET
def assessment_generation_status_ajax(request, course_id, assessment_id):
    user_type = getattr(request.user, 'user_type', 'Student')
    if user_type not in ['Teacher', 'IT_Support']:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    assessment = get_object_or_404(Assessment, id=assessment_id, course_id=course_id)
    from .student_attempts import job_status_payload

    return JsonResponse({'success': True, 'job': job_status_payload(assessment)})

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


def _user_can_open_assessment_setup(user, course, assessment) -> bool:
    if course is not None and course_is_deleted(course):
        return False
    if course is not None and course_is_closed(course):
        ut = getattr(user, 'user_type', 'Student')
        if not (getattr(user, 'is_staff', False) or ut == 'IT_Support'):
            return False
    user_type = getattr(user, 'user_type', 'Student')
    if user.is_staff or user_type == 'IT_Support':
        return True
    if course is not None and Course.objects.filter(
        id=course.id,
        usersincourse__user=user,
        usersincourse__user__user_type='Teacher',
    ).exists():
        return True
    branch = getattr(assessment, 'branch_location', None)
    if branch is not None and can_read_branch(user, branch):
        return True
    # Standalone library assessments: owner may open setup.
    if (
        course is None
        and assessment is not None
        and getattr(assessment, 'course_id', None) is None
        and getattr(assessment, 'branch_location', None) is not None
        and assessment.branch_location.owner_id == getattr(user, 'user_id', None)
    ):
        return True
    return False


def _user_can_mutate_assessment_setup(user, course, assessment) -> bool:
    if course is not None and course_is_deleted(course):
        return False
    if course is not None and course_is_closed(course):
        ut = getattr(user, 'user_type', 'Student')
        if not (getattr(user, 'is_staff', False) or ut == 'IT_Support'):
            return False
    user_type = getattr(user, 'user_type', 'Student')
    if user.is_staff or user_type == 'IT_Support':
        return True
    branch = getattr(assessment, 'branch_location', None)
    if branch is not None and can_edit_branch(user, branch):
        return True
    if course is not None and Course.objects.filter(
        id=course.id,
        usersincourse__user=user,
        usersincourse__user__user_type='Teacher',
    ).exists():
        return True
    if (
        course is None
        and assessment is not None
        and getattr(assessment, 'course_id', None) is None
        and branch is not None
        and branch.owner_id == getattr(user, 'user_id', None)
    ):
        return True
    return False


# URL sentinel for standalone (course_id IS NULL) library assessments.
STANDALONE_ASSESSMENT_COURSE_URL_ID = 0


def resolve_assessment_course_id(course_id):
    """
    Map URL course_id to DB course_id.

    ``0`` means a standalone library assessment (``assessment.course_id`` IS NULL).
    """
    try:
        scoped = int(course_id)
    except (TypeError, ValueError):
        raise Http404("Invalid course scope.")
    if scoped == STANDALONE_ASSESSMENT_COURSE_URL_ID:
        return None
    return scoped


def assessment_course_url_id(assessment_or_course_id) -> int:
    """Inverse of resolve_assessment_course_id for template/url reverse."""
    if assessment_or_course_id is None:
        return STANDALONE_ASSESSMENT_COURSE_URL_ID
    if hasattr(assessment_or_course_id, 'course_id'):
        cid = assessment_or_course_id.course_id
        return STANDALONE_ASSESSMENT_COURSE_URL_ID if cid is None else int(cid)
    return int(assessment_or_course_id)


def get_scoped_assessment(assessment_id, course_id, *, select_related=None):
    """
    Load an assessment for course-scoped setup URLs.

    ``course_id=0`` addresses standalone library assessments (``course_id`` NULL).
    """
    db_course_id = resolve_assessment_course_id(course_id)
    qs = Assessment.objects.all()
    if select_related:
        qs = qs.select_related(*select_related)
    return get_object_or_404(qs, id=assessment_id, course_id=db_course_id)


def _user_can_access_course_page(user, course) -> bool:
    user_type = getattr(user, 'user_type', 'Student')
    # Trashed courses are inaccessible from live pages for everyone (restore on Courses).
    if course_is_deleted(course):
        return False
    if user.is_staff or user_type == 'IT_Support':
        return True
    # Closed courses are not live for Teachers or Students (grades are separate).
    if course_is_closed(course) and user_type in ('Teacher', 'Student'):
        return False
    if getattr(course, 'owner_id', None) == getattr(user, 'user_id', None):
        return True
    if UsersInCourse.objects.filter(course=course, user=user).exists():
        return True
    branch = getattr(course, 'branch_location', None)
    return branch is not None and can_read_branch(user, branch)


def _user_can_mutate_course_content(user, course) -> bool:
    if course is None or course_is_deleted(course):
        return False
    user_type = getattr(user, 'user_type', 'Student')
    # Closed courses: only IT/staff may mutate (Teachers must reactivate first).
    if course_is_closed(course) and not (
        getattr(user, 'is_staff', False) or user_type == 'IT_Support'
    ):
        return False
    if user.is_staff or user_type == 'IT_Support':
        return True
    branch = getattr(course, 'branch_location', None)
    if branch is not None and can_edit_branch(user, branch):
        return True
    if UsersInCourse.objects.filter(
        course=course,
        user=user,
        user__user_type='Teacher',
    ).exists():
        return True
    return False


def _render_assessment_setup(request, course, assessment, *, disable_back_to_course=False):
    allow_edit = _user_can_mutate_assessment_setup(request.user, course, assessment)
    apply_explorer_mode_from_request(request, allow_edit=allow_edit)
    user_type = getattr(request.user, 'user_type', 'Student')
    aqg_groups = AssessmentQuestionGroup.objects.filter(assessment=assessment).order_by('order')
    context = {
        'course': course,
        'course_url_id': assessment_course_url_id(assessment),
        'assessment': assessment,
        'aqg_groups': aqg_groups,
        'user_type': user_type if user_type == 'IT_Support' else 'Teacher',
        'load_problem_workspace': True,
        'disable_assessment_back': disable_back_to_course or course is None,
        'active_tab': 'assessments',
    }
    return render(request, 'assessment_tool/assessment_setup.html', context)


@login_required
def assessment_setup_view(request, course_id, assessment_id):
    db_course_id = resolve_assessment_course_id(course_id)
    assessment = get_object_or_404(
        Assessment.objects.select_related('branch_location', 'course'),
        id=assessment_id,
        course_id=db_course_id,
    )
    course = assessment.course
    if course is not None:
        unavailable = deny_unavailable_course_entry(request, course)
        if unavailable:
            return unavailable
    if not _user_can_open_assessment_setup(request.user, course, assessment):
        messages.error(request, "You do not have access to manage this assessment configuration.")
        if course is None:
            return redirect('file_explorer')
        return redirect('course_detail', course_id=course.id)
    return _render_assessment_setup(
        request,
        course,
        assessment,
        disable_back_to_course=(course is None),
    )


@login_required
def assessment_edit_by_id_view(request, assessment_id):
    """Open assessment setup from explorer (no course navigation context)."""
    assessment = get_object_or_404(
        Assessment.objects.select_related('branch_location', 'course'),
        id=assessment_id,
    )
    course = assessment.course
    if not _user_can_open_assessment_setup(request.user, course, assessment):
        messages.error(request, "You do not have access to this assessment.")
        return redirect('file_explorer')
    # Loaded as a standalone assessment entry — back to course is not meaningful.
    return _render_assessment_setup(request, course, assessment, disable_back_to_course=True)


@login_required
@require_POST
def create_aqg_ajax(request, course_id, assessment_id):
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location',),
    )
    if not _user_can_manage_assessment(request, course_id, assessment):
        return JsonResponse({'success': False, 'error': 'Unauthorized action.'}, status=403)

    try:
        data = json.loads(request.body)
        raw_name = data.get('name', '').strip()
        
        clean_name = re.sub(r'\s+', ' ', raw_name)
        if not clean_name:
            return JsonResponse({'success': False, 'error': 'Section name cannot be empty.'}, status=400)
        
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
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location',),
    )
    if not _user_can_manage_assessment(request, course_id, assessment):
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
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location',),
    )
    if not _user_can_manage_assessment(request, course_id, assessment):
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
            prev_order = AssessmentQuestionGroup.objects.get(id=prev_id, assessment_id=assessment_id).order or ""
        if next_id:
            next_order = AssessmentQuestionGroup.objects.get(id=next_id, assessment_id=assessment_id).order or ""

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


@require_POST
@login_required
def add_problem_to_aqg_ajax(request, course_id, assessment_id):
    """
    Creates a new sequential Problem child item inside an Assessment Question Group.
    Provisions a companion identity BranchGroup node nested securely within the target location frame.
    """
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location',),
    )
    if not _user_can_manage_assessment(request, course_id, assessment):
        return JsonResponse({'error': 'Unauthorized deployment verification state access failed.'}, status=403)

    try:
        data = json.loads(request.body)
        aqg_id = data.get('aqg_id')
        
        # 2. Fetch the target parent AssessmentQuestionGroup layer container location framework
        aqg = get_object_or_404(
            AssessmentQuestionGroup.objects.select_related('branch_location'), 
            id=aqg_id, 
            assessment_id=assessment_id
        )
        parent_directory = aqg.branch_location

        if not parent_directory:
            return JsonResponse({'error': 'Target base group context mapping location identity mismatch error.'}, status=400)

        # 3. Handle sequential layout naming definitions
        # Trace current child problem structural nodes to determine starting title index string
        existing_problem_nodes = BranchGroup.objects.filter(parent=parent_directory, folder_type='problem')
        problem_count = existing_problem_nodes.count() + 1
        requested_item_name = f"Problem {problem_count}"

        # Resolve unique naming contexts cleanly using your existing utility script
        final_item_name, name_err = get_valid_unique_name(
            model_class=BranchGroup,
            parent_obj=parent_directory,
            requested_name=requested_item_name
            # Keeps item_type='folder' implicitly to verify parent sibling contexts cleanly!
        )
        if name_err:
            return JsonResponse({'error': name_err}, status=400)

        # Determine structural lexicographical midpoint sorting strings
        last_problem_node = existing_problem_nodes.order_by('order').last()
        prev_order_val = last_problem_node.order if last_problem_node else ""
        
        new_order = calculate_midpoint_order(prev_order_val, "")

        # 4. Synchronized Database Atomic Transaction Block
        with transaction.atomic():
            # A. Provision the silent structural BranchGroup identity tracker node
            problem_branch_node = BranchGroup.objects.create(
                owner=request.user,
                name=final_item_name,
                parent=parent_directory,
                folder_type='problem',
                order=new_order
            )

            # B. Allocate the companion concrete math problem payload row layer
            new_problem_item = Problem.objects.create(
                branch_location=problem_branch_node,  # Coordinates link
                title=final_item_name,                # Suffix incremented calculated name
                aqg=aqg,                              # Assessment structural layout frame hook
                problem_status='draft'                # Status = 'draft' or 'complete'
            )

        # 5. 🎯 NEW: Render the problem_card component into a raw HTML string snippet
        # This matches the exact variable scope context ('prob') expected by problem_card.html
        problem_html = render_to_string(
            'assessment_tool/components/problem_card.html', 
            {'prob': new_problem_item}, 
            request=request
        )

        return JsonResponse({
            'status': 'success',
            'branch_id': problem_branch_node.id,
            'problem_id': new_problem_item.id,
            'allocated_name': final_item_name,
            'html': problem_html  # 🎯 Send the complete pre-rendered component string to the UI
        }, status=201)

    except Exception as e:
        return JsonResponse({'error': f"Operation failed: {str(e)}"}, status=400)


@login_required
@require_POST
def duplicate_problem_in_aqg_ajax(request, course_id, assessment_id):
    """
    Duplicate an existing problem inside the same Assessment Question Group section.
    Creates a fully independent copy (question body + entities) titled 'Copy of …'.
    """
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location',),
    )
    if not _user_can_manage_assessment(request, course_id, assessment):
        return JsonResponse({'error': 'Unauthorized.'}, status=403)

    db_course_id = resolve_assessment_course_id(course_id)
    try:
        data = json.loads(request.body)
        problem_id = data.get('problem_id')
        if not problem_id:
            return JsonResponse({'error': 'Missing problem_id.'}, status=400)

        source_problem = get_object_or_404(
            Problem.objects.select_related('branch_location', 'aqg', 'aqg__assessment'),
            id=problem_id,
            aqg__assessment_id=assessment_id,
            aqg__assessment__course_id=db_course_id,
        )

        if not verify_workspace_clearance(request.user, source_problem):
            return JsonResponse({'error': 'You do not have permission to duplicate this problem.'}, status=403)

        new_problem, err = duplicate_problem_in_aqg(source_problem, request.user)
        if err:
            return JsonResponse({'error': err}, status=400)

        problem_html = render_to_string(
            'assessment_tool/components/problem_card.html',
            {'prob': new_problem},
            request=request,
        )

        return JsonResponse({
            'status': 'success',
            'problem_id': new_problem.id,
            'branch_id': new_problem.branch_location_id,
            'allocated_name': new_problem.title,
            'html': problem_html,
        }, status=201)

    except Exception as e:
        return JsonResponse({'error': f"Duplication failed: {str(e)}"}, status=400)


@login_required
@require_POST
def move_problem_to_aqg_ajax(request, course_id, assessment_id):
    """
    Move an existing problem to another Assessment Question Group section
    within the same assessment, appending it to the end of that section.
    """
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location',),
    )
    if not _user_can_manage_assessment(request, course_id, assessment):
        return JsonResponse({'error': 'Unauthorized.'}, status=403)

    db_course_id = resolve_assessment_course_id(course_id)
    try:
        data = json.loads(request.body)
        problem_id = data.get('problem_id')
        target_aqg_id = data.get('target_aqg_id')
        if not problem_id or not target_aqg_id:
            return JsonResponse({'error': 'Missing problem_id or target_aqg_id.'}, status=400)

        problem = get_object_or_404(
            Problem.objects.select_related('branch_location', 'aqg', 'aqg__assessment'),
            id=problem_id,
            aqg__assessment_id=assessment_id,
            aqg__assessment__course_id=db_course_id,
        )

        if not verify_workspace_clearance(request.user, problem):
            return JsonResponse({'error': 'You do not have permission to move this problem.'}, status=403)

        target_aqg = get_object_or_404(
            AssessmentQuestionGroup.objects.select_related('branch_location'),
            id=target_aqg_id,
            assessment_id=assessment_id,
            assessment__course_id=db_course_id,
        )

        moved_problem, err = move_problem_to_aqg(problem, target_aqg)
        if err:
            return JsonResponse({'error': err}, status=400)

        return JsonResponse({
            'status': 'success',
            'problem_id': moved_problem.id,
            'branch_id': moved_problem.branch_location_id,
            'target_aqg_id': target_aqg.id,
            'allocated_name': moved_problem.title,
        }, status=200)

    except Exception as e:
        return JsonResponse({'error': f"Move failed: {str(e)}"}, status=400)


@login_required
@require_POST
def move_problem_to_cqd_ajax(request, course_id, assessment_id):
    """
    Move an existing problem into a problem set (CQD) folder within the assessment.
    """
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location',),
    )
    if not _user_can_manage_assessment(request, course_id, assessment):
        return JsonResponse({'error': 'Unauthorized.'}, status=403)

    db_course_id = resolve_assessment_course_id(course_id)
    try:
        data = json.loads(request.body)
        problem_id = data.get('problem_id')
        target_cqd_id = data.get('target_cqd_id')
        if not problem_id or not target_cqd_id:
            return JsonResponse({'error': 'Missing problem_id or target_cqd_id.'}, status=400)

        problem = get_object_or_404(
            Problem.objects.select_related('branch_location', 'aqg', 'aqg__assessment', 'cqd'),
            id=problem_id,
        )

        if not verify_workspace_clearance(request.user, problem):
            return JsonResponse({'error': 'You do not have permission to move this problem.'}, status=403)

        # Ensure problem belongs to this assessment (via aqg, or via current folder ancestry)
        problem_assessment_id = None
        if problem.aqg_id:
            problem_assessment_id = problem.aqg.assessment_id
        elif problem.branch_location and problem.branch_location.parent_id:
            parent = problem.branch_location.parent
            parent_aqg = AssessmentQuestionGroup.objects.filter(branch_location_id=parent.id).first()
            if not parent_aqg and parent.parent_id:
                parent_aqg = AssessmentQuestionGroup.objects.filter(branch_location_id=parent.parent_id).first()
            if parent_aqg:
                problem_assessment_id = parent_aqg.assessment_id

        if problem_assessment_id != assessment_id:
            return JsonResponse({'error': 'Problem does not belong to this assessment.'}, status=400)

        target_cqd = get_object_or_404(
            CustomQuestionDistribution.objects.select_related('assigned_folder', 'assigned_folder__parent'),
            id=target_cqd_id,
        )
        cqd_aqg = AssessmentQuestionGroup.objects.filter(
            branch_location_id=target_cqd.assigned_folder.parent_id,
            assessment_id=assessment_id,
            assessment__course_id=db_course_id,
        ).first()
        if not cqd_aqg:
            return JsonResponse({'error': 'Problem set is not part of this assessment.'}, status=400)

        old_cqd_id = problem.cqd_id
        moved_problem, err = move_problem_to_cqd(problem, target_cqd)
        if err:
            return JsonResponse({'error': err}, status=400)

        old_display = None
        old_count = None
        if old_cqd_id and old_cqd_id != target_cqd.id:
            old_cqd = CustomQuestionDistribution.objects.filter(id=old_cqd_id).first()
            if old_cqd:
                old_display, old_count = refresh_cqd_identity(old_cqd)

        return JsonResponse({
            'status': 'success',
            'problem_id': moved_problem.id,
            'branch_id': moved_problem.branch_location_id,
            'target_cqd_id': target_cqd.id,
            'allocated_name': moved_problem.title,
            'cqd_display_name': getattr(moved_problem, '_cqd_display_name', target_cqd.get_display_name()),
            'cqd_count': getattr(moved_problem, '_cqd_count', None),
            'old_cqd_id': old_cqd_id if old_cqd_id != target_cqd.id else None,
            'old_cqd_display_name': old_display,
            'old_cqd_count': old_count,
        }, status=200)

    except Exception as e:
        return JsonResponse({'error': f"Move to problem set failed: {str(e)}"}, status=400)


@login_required
@require_POST
def remove_problem_from_cqd_ajax(request, course_id, assessment_id):
    """
    Remove a problem from its problem set and place it immediately after that
    set inside the same question group section.
    """
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location',),
    )
    if not _user_can_manage_assessment(request, course_id, assessment):
        return JsonResponse({'error': 'Unauthorized.'}, status=403)

    db_course_id = resolve_assessment_course_id(course_id)
    try:
        data = json.loads(request.body)
        problem_id = data.get('problem_id')
        if not problem_id:
            return JsonResponse({'error': 'Missing problem_id.'}, status=400)

        problem = get_object_or_404(
            Problem.objects.select_related(
                'branch_location',
                'branch_location__parent',
                'aqg',
                'aqg__assessment',
                'cqd',
                'cqd__assigned_folder',
            ),
            id=problem_id,
        )

        if not verify_workspace_clearance(request.user, problem):
            return JsonResponse({'error': 'You do not have permission to move this problem.'}, status=403)

        # Resolve the problem set / section before mutating so we can authorize
        cqd = problem.cqd
        if not cqd and problem.branch_location and problem.branch_location.parent_id:
            cqd = CustomQuestionDistribution.objects.filter(
                assigned_folder_id=problem.branch_location.parent_id
            ).select_related('assigned_folder').first()
        if not cqd or not cqd.assigned_folder_id:
            return JsonResponse({'error': 'Problem is not inside a problem set.'}, status=400)

        section_aqg = AssessmentQuestionGroup.objects.filter(
            branch_location_id=cqd.assigned_folder.parent_id,
            assessment_id=assessment_id,
            assessment__course_id=db_course_id,
        ).first()
        if not section_aqg:
            return JsonResponse({'error': 'Problem set is not part of this assessment.'}, status=400)

        moved_problem, err = remove_problem_from_cqd(problem)
        if err:
            return JsonResponse({'error': err}, status=400)

        return JsonResponse({
            'status': 'success',
            'problem_id': moved_problem.id,
            'branch_id': moved_problem.branch_location_id,
            'aqg_id': getattr(moved_problem, '_aqg_id', section_aqg.id),
            'source_cqd_id': getattr(moved_problem, '_source_cqd_id', cqd.id),
            'allocated_name': moved_problem.title,
            'cqd_display_name': getattr(moved_problem, '_cqd_display_name', None),
            'cqd_count': getattr(moved_problem, '_cqd_count', None),
        }, status=200)

    except Exception as e:
        return JsonResponse({'error': f"Remove from problem set failed: {str(e)}"}, status=400)


@login_required
@require_http_methods(["GET", "POST"])
def cqd_problems_list_ajax(request, course_id, assessment_id, cqd_id):
    """
    Return rendered problem cards for all problems inside a problem set (CQD).
    """
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location',),
    )
    if not _user_can_manage_assessment(request, course_id, assessment):
        return JsonResponse({'error': 'Unauthorized.'}, status=403)

    db_course_id = resolve_assessment_course_id(course_id)
    try:
        cqd = get_object_or_404(
            CustomQuestionDistribution.objects.select_related('assigned_folder'),
            id=cqd_id,
        )
        section_aqg = AssessmentQuestionGroup.objects.filter(
            branch_location_id=cqd.assigned_folder.parent_id,
            assessment_id=assessment_id,
            assessment__course_id=db_course_id,
        ).first()
        if not section_aqg:
            return JsonResponse({'error': 'Problem set is not part of this assessment.'}, status=404)

        child_branches = list(
            BranchGroup.objects.filter(parent=cqd.assigned_folder)
            .order_by('order', 'id')
        )
        branch_ids = [b.id for b in child_branches]
        problems_by_branch = {
            p.branch_location_id: p
            for p in Problem.objects.filter(branch_location_id__in=branch_ids).select_related('branch_location')
        }

        cards_html = []
        for branch in child_branches:
            prob = problems_by_branch.get(branch.id)
            if not prob:
                continue
            cards_html.append(
                render_to_string(
                    'assessment_tool/components/problem_card.html',
                    {'prob': prob},
                    request=request,
                )
            )

        display_name, count = refresh_cqd_identity(cqd)

        return JsonResponse({
            'status': 'success',
            'cqd_id': cqd.id,
            'display_name': display_name,
            'count': count,
            'aqg_id': section_aqg.id,
            'html': ''.join(cards_html),
        }, status=200)

    except Exception as e:
        return JsonResponse({'error': f"Failed to load problem set: {str(e)}"}, status=400)


@login_required
def add_cqd_to_aqg_ajax(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        data = json.loads(request.body)
        aqg_id = data.get('aqg_id')
        
        if not aqg_id:
            return JsonResponse({'error': 'Missing section group identifier constraint.'}, status=400)
            
        # Fetch the active section group component context container
        aqg = get_object_or_404(AssessmentQuestionGroup.objects.select_related('branch_location'), id=aqg_id)
        parent_directory = aqg.branch_location
        
        # Calculate sequential ordering positions inside the folder layout tree branch
        last_child = BranchGroup.objects.filter(parent=parent_directory).order_by('order').last()
        
        # 🚀 FIX: Fallback to an empty string instead of a whitespace character " "
        # (Alternatively, if your midpoint logic prefers starting from the beginning of the alphabet, use "a")
        prev_order = last_child.order if last_child else "" 
        
        new_order = calculate_midpoint_order(prev_order, "z")
        
        # Generation identity config fields
        final_item_name = f"A placeholder name"
        
        with transaction.atomic():
            # 1. Provision the structural BranchGroup framework node container
            cqd_branch_node = BranchGroup.objects.create(
                owner=request.user,
                name=final_item_name,
                parent=parent_directory,
                folder_type='cqd',  
                order=new_order,
                creation_date=timezone.now(),
                modification_date=timezone.now()
            )
            
            # 2. Allocate the concrete CustomQuestionDistribution database payload row layer
            new_cqd_item = CustomQuestionDistribution.objects.create(
                assigned_folder=cqd_branch_node,
                suggested_count=1,
                name=CustomQuestionDistribution.DEFAULT_NAME,
            )

            # Pool starts empty; folder label uses id + display name
            new_cqd_item.num_pairs = 0
            cqd_branch_node.name = new_cqd_item.get_unique_name()
            cqd_branch_node.save(update_fields=['name', 'modification_date']) 
        
        # 3. Pre-compile the standalone component template context snapshot layout fragment string snippet
        cqd_html = render_to_string(
            'assessment_tool/components/cqd_card.html',
            {'cqd': new_cqd_item},
            request=request
        )
        
        return JsonResponse({
            'status': 'success',
            'html': cqd_html
        }, status=201)
        
    except Exception as e:
        return JsonResponse({'error': f"Internal Server Exception Process Fault: {str(e)}"}, status=500)


@login_required
def update_cqd_count_ajax(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        data = json.loads(request.body)
        cqd_id = data.get('cqd_id')
        suggested_count = data.get('suggested_count')

        # Clean validation conversion safeguard
        try:
            new_count = int(suggested_count)
            if new_count < 0:
                new_count = 0
        except (TypeError, ValueError):
            new_count = 0

        # Locate the record and confirm ownership against the virtual folder owner field
        if request.user.user_type == 'IT_Support':
            cqd_item = get_object_or_404(CustomQuestionDistribution, id=cqd_id)
        else:
            cqd_item = get_object_or_404(CustomQuestionDistribution, id=cqd_id, assigned_folder__owner=request.user)

        # Update and save the model state
        cqd_item.suggested_count = new_count
        cqd_item.save(update_fields=['suggested_count'])

        return JsonResponse({
            'status': 'success',
            'new_count': cqd_item.suggested_count
        }, status=200)

    except Exception as e:
        return JsonResponse({'error': f"Database Write Operation Failure: {str(e)}"}, status=500)


@login_required
def update_cqd_name_ajax(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        cqd_id = data.get('cqd_id')
        raw_name = str(data.get('name') or '').strip()
        clean_name = re.sub(r'\s+', ' ', raw_name)

        if not clean_name:
            return JsonResponse({'success': False, 'error': 'Problem set name cannot be empty.'}, status=400)
        if len(clean_name) > 255:
            return JsonResponse({'success': False, 'error': 'Problem set name is too long.'}, status=400)

        if getattr(request.user, 'user_type', None) == 'IT_Support' or request.user.is_staff:
            cqd_item = get_object_or_404(
                CustomQuestionDistribution.objects.select_related('assigned_folder'),
                id=cqd_id,
            )
        else:
            cqd_item = get_object_or_404(
                CustomQuestionDistribution.objects.select_related('assigned_folder'),
                id=cqd_id,
                assigned_folder__owner=request.user,
            )

        with transaction.atomic():
            cqd_item.name = clean_name
            cqd_item.save(update_fields=['name'])
            display_name, count = refresh_cqd_identity(cqd_item)

        return JsonResponse({
            'success': True,
            'name': display_name,
            'count': count,
        }, status=200)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    

@login_required
@require_POST
def reorder_nested_item_ajax(request):
    """
    Persist order for a problem / CQD branch node after drag-and-drop inside an
    assessment question group section.

    Rebuilds lexicographic order keys for all siblings so duplicate/inverted
    keys (common after repeated reorders) cannot block the write.
    """
    try:
        data = json.loads(request.body)
        branch_id = data.get('branch_id')
        prev_branch_id = data.get('prev_branch_id')
        next_branch_id = data.get('next_branch_id')

        if not branch_id:
            return JsonResponse({'success': False, 'error': 'Missing targets.'}, status=400)

        try:
            branch_id = int(branch_id)
            prev_branch_id = int(prev_branch_id) if prev_branch_id not in (None, '', 'null') else None
            next_branch_id = int(next_branch_id) if next_branch_id not in (None, '', 'null') else None
        except (TypeError, ValueError):
            return JsonResponse({'success': False, 'error': 'Invalid branch identifiers.'}, status=400)

        target_node = get_object_or_404(BranchGroup, id=branch_id)

        # Authorize: staff/IT, branch owner, or teacher on the parent assessment's course
        user_type = getattr(request.user, 'user_type', 'Student')
        is_privileged = user_type == 'IT_Support' or request.user.is_staff
        is_owner = target_node.owner_id == request.user.pk

        is_course_teacher = False
        if not is_privileged and not is_owner:
            # Direct child of an AQG section, or nested under a CQD inside an AQG
            parent_aqg = AssessmentQuestionGroup.objects.filter(
                branch_location_id=target_node.parent_id
            ).select_related('assessment').first()
            if not parent_aqg and target_node.parent_id:
                parent_folder = BranchGroup.objects.filter(id=target_node.parent_id).first()
                if parent_folder and parent_folder.parent_id:
                    parent_aqg = AssessmentQuestionGroup.objects.filter(
                        branch_location_id=parent_folder.parent_id
                    ).select_related('assessment').first()
            if parent_aqg:
                is_course_teacher = UsersInCourse.objects.filter(
                    course_id=parent_aqg.assessment.course_id,
                    user=request.user,
                    user__user_type='Teacher'
                ).exists()

        if not (is_privileged or is_owner or is_course_teacher):
            return JsonResponse({'success': False, 'error': 'Unauthorized action.'}, status=403)

        parent_id = target_node.parent_id
        siblings = list(
            BranchGroup.objects.filter(parent_id=parent_id).order_by('order', 'id')
        )
        sibling_ids = [node.id for node in siblings if node.id != target_node.id]

        if prev_branch_id is not None and prev_branch_id not in sibling_ids:
            return JsonResponse(
                {'success': False, 'error': 'Previous sibling is not in the same section.'},
                status=400,
            )
        if next_branch_id is not None and next_branch_id not in sibling_ids:
            return JsonResponse(
                {'success': False, 'error': 'Next sibling is not in the same section.'},
                status=400,
            )

        # Rebuild the visual sibling sequence from the drop neighbors
        ordered_ids = list(sibling_ids)
        if prev_branch_id is None and next_branch_id is None:
            ordered_ids = [target_node.id]
        elif prev_branch_id is None:
            insert_at = ordered_ids.index(next_branch_id)
            ordered_ids.insert(insert_at, target_node.id)
        else:
            insert_at = ordered_ids.index(prev_branch_id) + 1
            ordered_ids.insert(insert_at, target_node.id)

        now = timezone.now()
        new_order_for_target = None
        with transaction.atomic():
            running_order = ""
            for node_id in ordered_ids:
                running_order = calculate_midpoint_order(running_order, "")
                BranchGroup.objects.filter(id=node_id).update(
                    order=running_order,
                    modification_date=now,
                )
                if node_id == target_node.id:
                    new_order_for_target = running_order

        return JsonResponse({'success': True, 'new_order': new_order_for_target})

    except Exception as e:
        logger.exception("Nested item reorder failed: %s", e)
        return JsonResponse({'success': False, 'error': f"Sorting failed: {str(e)}"}, status=400)
    


@login_required
def student_assessment_take_view(request, course_id, assessment_id):
    """Student take UI for a frozen attempt."""
    if getattr(request.user, "user_type", None) != "Student":
        return redirect("assessment_view", course_id=course_id)
    course = get_object_or_404(Course, id=course_id)
    unavailable_denied = deny_unavailable_course_entry(request, course)
    if unavailable_denied:
        return unavailable_denied
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course=course,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .student_attempts import (
        assessment_available_to_student,
        assessment_taking_ended,
        current_attempt_for_student,
        finalize_student_attempt_if_open,
        get_or_create_attempt_for_student,
        student_may_start_attempt,
    )

    if assessment_taking_ended(assessment) and not student_may_start_attempt(
        assessment, request.user
    ):
        attempt = current_attempt_for_student(assessment, request.user)
        from .student_attempts import attempt_may_continue_while_closed

        # Do not force-submit an authorized retake when the class row is closed.
        if attempt is not None and not attempt_may_continue_while_closed(
            attempt, assessment, request.user
        ):
            finalize_student_attempt_if_open(attempt)
        messages.error(
            request,
            "This assessment has been closed. Any answers you had entered were submitted.",
        )
        return redirect("assessment_view", course_id=course_id)

    try:
        attempt = get_or_create_attempt_for_student(assessment, request.user)
    except PermissionError as exc:
        messages.error(request, str(exc))
        return redirect("assessment_view", course_id=course_id)

    if attempt.status == StudentAssessmentAttempt.STATUS_SUBMITTED:
        messages.info(request, "You have already submitted this assessment.")
        return redirect("assessment_view", course_id=course_id)

    # READY / IN_PROGRESS means the student already has an authorized take
    # (including a per-student retake on a closed class assessment).
    if attempt.status not in (
        StudentAssessmentAttempt.STATUS_READY,
        StudentAssessmentAttempt.STATUS_IN_PROGRESS,
    ) and not assessment_available_to_student(assessment, request.user):
        messages.error(request, "This assessment is not currently open.")
        return redirect("assessment_view", course_id=course_id)

    from .assessment_options import show_count_up_timer

    return render(
        request,
        "assessment_tool/student_assessment_take.html",
        {
            "course": course,
            "assessment": assessment,
            "attempt": attempt,
            "active_tab": "assessments",
            "show_count_up_timer": show_count_up_timer(assessment),
            # Needed so base.html loads problem_overlay_global + overlay DOM
            # (PracticeTestPreviewAPI only initializes when #problem-workspace-overlay exists).
            "load_problem_workspace": True,
        },
    )


@login_required
@require_POST
def student_assessment_start_ajax(request, course_id, assessment_id):
    if getattr(request.user, "user_type", None) != "Student":
        return JsonResponse({"error": "Unauthorized"}, status=403)
    course = get_object_or_404(Course, id=course_id)
    if course_is_closed(course) or course_is_deleted(course):
        return JsonResponse(
            {"error": "This course is closed.", "code": "course_closed"},
            status=403,
        )
    assessment = get_object_or_404(
        Assessment, id=assessment_id, course_id=course_id, parent_assessment__isnull=True, user__isnull=True
    )
    from .student_attempts import (
        assessment_available_to_student,
        assessment_taking_ended,
        begin_attempt_for_student,
        client_problems_for_attempt,
        current_attempt_for_student,
        finalize_student_attempt_if_open,
        get_or_create_attempt_for_student,
        student_may_start_attempt,
    )

    if assessment_taking_ended(assessment) and not student_may_start_attempt(
        assessment, request.user
    ):
        attempt = current_attempt_for_student(assessment, request.user)
        from .student_attempts import attempt_may_continue_while_closed

        if attempt is not None and not attempt_may_continue_while_closed(
            attempt, assessment, request.user
        ):
            finalize_student_attempt_if_open(attempt)
        return JsonResponse(
            {
                "error": "This assessment has been closed.",
                "code": "assessment_closed",
                "closed": True,
            },
            status=409,
        )

    try:
        attempt = get_or_create_attempt_for_student(assessment, request.user)
    except PermissionError as exc:
        return JsonResponse({"error": str(exc)}, status=403)

    if attempt.status == StudentAssessmentAttempt.STATUS_SUBMITTED:
        return JsonResponse({"error": "Already submitted."}, status=400)

    if attempt.status not in (
        StudentAssessmentAttempt.STATUS_READY,
        StudentAssessmentAttempt.STATUS_IN_PROGRESS,
    ) and not assessment_available_to_student(assessment, request.user):
        return JsonResponse({"error": "Assessment is not takeable."}, status=400)

    attempt = begin_attempt_for_student(attempt)

    from .assessment_options import countdown_timer_payload, show_count_up_timer
    from .student_attempts import (
        _aware,
        assessment_window_bounds,
        normalize_assessment_status,
        upcoming_window_contains,
    )

    now = timezone.now()
    elapsed_seconds = 0
    if attempt.started_at is not None:
        started = _aware(attempt.started_at)
        if started is not None:
            elapsed_seconds = max(
                0, int((now - started).total_seconds())
            )

    _start, end = assessment_window_bounds(assessment)
    window_ends_at = None
    remaining_seconds = None
    if (
        normalize_assessment_status(assessment.status) == "upcoming"
        and upcoming_window_contains(assessment, now=now)
        and end is not None
    ):
        window_ends_at = end.isoformat()
        remaining_seconds = max(0, int((end - now).total_seconds()))
    countdown = countdown_timer_payload(
        assessment,
        attempt,
        window_end=end if window_ends_at else None,
        now=now,
    )
    from .assessment_focus_lock import (
        focus_lock_enabled,
        focus_lock_payload,
    )

    return JsonResponse(
        {
            "success": True,
            "attempt_id": attempt.id,
            "status": attempt.status,
            "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
            "elapsed_seconds": elapsed_seconds,
            "show_count_up_timer": show_count_up_timer(assessment),
            "window_ends_at": window_ends_at,
            "remaining_seconds": remaining_seconds,
            **countdown,
            "focus_lock_enabled": focus_lock_enabled(assessment),
            **focus_lock_payload(attempt),
            "problems": client_problems_for_attempt(attempt),
        }
    )


@login_required
def student_assessment_take_status_ajax(request, course_id, assessment_id):
    """Heartbeat for the take page: detect close / forced submit."""
    if getattr(request.user, "user_type", None) != "Student":
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course_id=course_id,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .student_attempts import (
        assessment_taking_ended,
        assessment_window_bounds,
        attempt_may_continue_while_closed,
        current_attempt_for_student,
        finalize_student_attempt_if_open,
        normalize_assessment_status,
        student_facing_assessment_status,
        student_may_start_attempt,
        upcoming_window_contains,
    )
    from .assessment_options import countdown_timer_payload

    now = timezone.now()
    attempt = current_attempt_for_student(assessment, request.user)
    from .student_attempts import attempt_must_stop_taking

    closed = assessment_taking_ended(assessment, now=now)
    stop = attempt_must_stop_taking(assessment, attempt, now=now)
    # If the upcoming window / time limit just ended, finalize this student's open take so the
    # poll kick does not wait on the periodic close job. Never finalize an
    # in-flight retake / open retake grant — those outlive class closed status.
    if (
        stop.get("must_stop")
        and attempt is not None
        and attempt.status
        in (
            StudentAssessmentAttempt.STATUS_READY,
            StudentAssessmentAttempt.STATUS_IN_PROGRESS,
        )
    ):
        finalize_student_attempt_if_open(attempt)
        attempt.refresh_from_db()
    elif (
        closed
        and attempt is not None
        and attempt.status
        in (
            StudentAssessmentAttempt.STATUS_READY,
            StudentAssessmentAttempt.STATUS_IN_PROGRESS,
        )
        and not attempt_may_continue_while_closed(
            attempt, assessment, request.user
        )
    ):
        finalize_student_attempt_if_open(attempt)
        attempt.refresh_from_db()

    attempt_status = attempt.status if attempt else None
    submitted = bool(
        attempt
        and (
            attempt.status == StudentAssessmentAttempt.STATUS_SUBMITTED
            or attempt.auto_graded_at is not None
        )
    )
    taking_allowed = student_may_start_attempt(
        assessment, request.user, now=now
    )
    # `closed` must mean "this student's take session should end", NOT merely
    # that the class assessment row is closed — otherwise retakes on a closed
    # class are force-submitted by clients that key off `closed`.
    session_closed = not taking_allowed
    _start, end = assessment_window_bounds(assessment)
    window_ends_at = None
    remaining_seconds = None
    if (
        normalize_assessment_status(assessment.status) == "upcoming"
        and upcoming_window_contains(assessment, now=now)
        and end is not None
    ):
        window_ends_at = end.isoformat()
        remaining_seconds = max(0, int((end - now).total_seconds()))
    countdown = countdown_timer_payload(
        assessment,
        attempt,
        window_end=end if window_ends_at else None,
        now=now,
    )
    from .assessment_focus_lock import (
        focus_lock_enabled,
        focus_lock_payload,
    )

    return JsonResponse(
        {
            "success": True,
            "closed": session_closed,
            "class_closed": closed,
            "force_close": session_closed,
            "assessment_status": assessment.status,
            "display_status": student_facing_assessment_status(assessment, now=now),
            "attempt_status": attempt_status,
            "submitted": submitted,
            "taking_allowed": taking_allowed,
            "window_ends_at": window_ends_at,
            "remaining_seconds": remaining_seconds,
            **countdown,
            "focus_lock_enabled": focus_lock_enabled(assessment),
            **focus_lock_payload(attempt),
        }
    )


@login_required
@require_POST
def student_assessment_autosave_ajax(request, course_id, assessment_id):
    if getattr(request.user, "user_type", None) != "Student":
        return JsonResponse({"error": "Unauthorized"}, status=403)
    course = get_object_or_404(Course, id=course_id)
    if course_is_closed(course) or course_is_deleted(course):
        return JsonResponse(
            {"error": "This course is closed.", "code": "course_closed"},
            status=403,
        )
    assessment = get_object_or_404(
        Assessment, id=assessment_id, course_id=course_id, parent_assessment__isnull=True
    )
    from .student_attempts import (
        assessment_taking_ended,
        attempt_must_stop_taking,
        begin_attempt_for_student,
        current_attempt_for_student,
        finalize_student_attempt_if_open,
        upsert_answers,
    )

    attempt = current_attempt_for_student(assessment, request.user)
    if not attempt:
        return JsonResponse({"error": "No attempt found."}, status=404)
    if attempt.status == StudentAssessmentAttempt.STATUS_SUBMITTED:
        return JsonResponse(
            {
                "error": "Already submitted.",
                "code": "already_submitted",
                "closed": assessment_taking_ended(assessment),
                "submitted": True,
            },
            status=400,
        )
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    from .assessment_focus_lock import active_focus_lock

    lock = active_focus_lock(attempt)
    if lock is not None:
        return JsonResponse(
            {
                "error": "This assessment is locked until your teacher releases it.",
                "code": "focus_locked",
                "focus_locked": True,
                "focus_locked_at": lock.locked_at.isoformat(),
            },
            status=423,
        )

    stop = attempt_must_stop_taking(assessment, attempt)
    if stop.get("must_stop"):
        # Accept the last payload, then finalize — no further editing.
        if isinstance(data.get("problems"), list) or data:
            upsert_answers(attempt, data)
        finalize_student_attempt_if_open(attempt)
        return JsonResponse(
            {
                "success": True,
                "closed": True,
                "force_close": True,
                "submitted": True,
                "taking_allowed": False,
                "code": "assessment_closed",
                "force_submit_reason": stop.get("reason"),
            }
        )

    upsert_answers(attempt, data)
    begin_attempt_for_student(attempt)
    return JsonResponse(
        {
            "success": True,
            "closed": False,
            "taking_allowed": True,
        }
    )


@login_required
@require_POST
def student_assessment_submit_ajax(request, course_id, assessment_id):
    if getattr(request.user, "user_type", None) != "Student":
        return JsonResponse({"error": "Unauthorized"}, status=403)
    course = get_object_or_404(Course, id=course_id)
    if course_is_closed(course) or course_is_deleted(course):
        return JsonResponse(
            {"error": "This course is closed.", "code": "course_closed"},
            status=403,
        )
    assessment = get_object_or_404(
        Assessment, id=assessment_id, course_id=course_id, parent_assessment__isnull=True
    )
    from .student_attempts import current_attempt_for_student

    attempt = current_attempt_for_student(assessment, request.user)
    if not attempt:
        return JsonResponse({"error": "No attempt found."}, status=404)
    if attempt.status == StudentAssessmentAttempt.STATUS_SUBMITTED:
        return JsonResponse(
            {
                "success": True,
                "already_submitted": True,
                "closed": True,
                "message": "Already submitted.",
            }
        )
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    from .assessment_focus_lock import active_focus_lock, focus_lock_enabled
    from .student_attempts import (
        attempt_must_stop_taking,
        notify_teachers_focus_enforcement_bypassed,
        submit_and_grade_attempt,
        upsert_answers,
    )

    stop = attempt_must_stop_taking(assessment, attempt)
    lock = active_focus_lock(attempt)
    force_submit = bool(data.pop("force_submit", False))
    server_forced = bool(stop.get("must_stop"))
    # Client force_submit may bypass focus lock only when the server deadline expired.
    if lock is not None and not (force_submit and server_forced):
        return JsonResponse(
            {
                "error": "This assessment is locked until your teacher releases it.",
                "code": "focus_locked",
                "focus_locked": True,
                "focus_locked_at": lock.locked_at.isoformat(),
            },
            status=423,
        )

    focus_client_active = bool(data.pop("focus_client_active", False))
    if focus_lock_enabled(assessment) and not focus_client_active:
        notify_teachers_focus_enforcement_bypassed(attempt)

    from .assessment_grades import scores_visible_to_student
    from .student_attempts import course_template_assessment

    if data:
        upsert_answers(attempt, data)
    try:
        result = submit_and_grade_attempt(
            attempt,
            focus_unlock_reason=(
                "window_ended" if (force_submit or server_forced) else "submitted"
            ),
        )
    except ValueError as exc:
        return JsonResponse(
            {
                "success": True,
                "already_submitted": True,
                "message": str(exc),
            }
        )

    attempt.refresh_from_db()
    template = course_template_assessment(assessment) or assessment
    visible = scores_visible_to_student(template, attempt)
    payload = {
        "success": True,
        "scores_visible": visible,
        "requires_manual_grading": result.get("requires_manual_grading", False),
        "closed": bool(server_forced),
    }
    if visible:
        payload["earned_total"] = result.get("earned_total")
        payload["max_total"] = result.get("max_total")
        payload["problems"] = result.get("problems")
    else:
        payload["message"] = (
            "Submitted. Your score will be available when your teacher "
            "releases grades."
        )
    return JsonResponse(payload)


@login_required
@require_POST
def student_assessment_focus_lock_ajax(request, course_id, assessment_id):
    if getattr(request.user, "user_type", None) != "Student":
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course_id=course_id,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .student_attempts import current_attempt_for_student

    attempt = current_attempt_for_student(assessment, request.user)
    if attempt is None:
        return JsonResponse({"error": "No attempt found."}, status=404)
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    from .assessment_focus_lock import lock_attempt_for_focus

    result = lock_attempt_for_focus(attempt, data)
    status = 200 if result.get("success") else 400
    return JsonResponse(result, status=status)


@login_required
@require_POST
@transaction.atomic
def student_assessment_submit_locked_ajax(request, course_id, assessment_id):
    """Submit saved answers and erase only the active lock event by student choice."""
    if getattr(request.user, "user_type", None) != "Student":
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course_id=course_id,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .student_attempts import (
        current_attempt_for_student,
        submit_and_grade_attempt,
    )

    attempt = current_attempt_for_student(assessment, request.user)
    if attempt is None:
        return JsonResponse({"error": "No attempt found."}, status=404)
    if attempt.status == StudentAssessmentAttempt.STATUS_SUBMITTED:
        return JsonResponse(
            {"success": True, "already_submitted": True, "closed": True}
        )

    from .assessment_focus_lock import active_focus_lock, delete_active_focus_lock

    if active_focus_lock(attempt) is None:
        return JsonResponse(
            {"error": "This assessment is no longer locked."},
            status=409,
        )
    delete_active_focus_lock(attempt)
    result = submit_and_grade_attempt(attempt)

    from .assessment_grades import scores_visible_to_student
    from .student_attempts import course_template_assessment

    attempt.refresh_from_db()
    template = course_template_assessment(assessment) or assessment
    visible = scores_visible_to_student(template, attempt)
    payload = {
        "success": True,
        "scores_visible": visible,
        "requires_manual_grading": result.get("requires_manual_grading", False),
        "closed": True,
    }
    if visible:
        payload["earned_total"] = result.get("earned_total")
        payload["max_total"] = result.get("max_total")
    else:
        payload["message"] = "Your saved assessment answers were submitted."
    return JsonResponse(payload)


def _teacher_grades_access(request, course):
    """Return None on success, or an HttpResponse/redirect on denial."""
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        messages.error(request, "Teachers only.")
        return redirect("dashboard")
    unavailable_denied = deny_unavailable_course_entry(request, course)
    if unavailable_denied:
        return unavailable_denied
    if not _user_can_access_course_page(request.user, course):
        messages.error(request, "You do not have access to this course.")
        return redirect("dashboard")
    return None


@login_required
def course_grades_view(request, course_id):
    course = get_object_or_404(Course, id=course_id)

    user_type = getattr(request.user, "user_type", None)
    if user_type in ("Teacher", "IT_Support"):
        unavailable_denied = deny_unavailable_course_entry(request, course)
        if unavailable_denied:
            return unavailable_denied
        if not _user_can_access_course_page(request.user, course):
            messages.error(request, "You do not have access to this course.")
            return redirect("dashboard")
        from .assessment_grades import (
            grades_overview_for_course,
            grades_overview_meta,
            teacher_course_gradebook,
        )

        grade_rows = grades_overview_for_course(course)
        meta = grades_overview_meta(course, grade_rows)
        gradebook = teacher_course_gradebook(course)
        return render(
            request,
            "assessment_tool/course_grades.html",
            {
                "course": course,
                "active_tab": "grades",
                "grade_rows": grade_rows,
                "show_weight_column": meta["show_weight_column"],
                "show_points_column": meta["show_points_column"],
                "show_curve_column": meta["show_curve_column"],
                "show_manual_pending_column": meta["show_manual_pending_column"],
                "show_release_column": meta["show_release_column"],
                "grade_aggregation_mode": meta["grade_aggregation_mode"],
                "gradebook": gradebook,
            },
        )

    if user_type != "Student":
        messages.error(request, "Unauthorized.")
        return redirect("dashboard")

    if not student_can_view_course_grades(request.user, course):
        messages.error(request, "You do not have access to this course.")
        return redirect("dashboard")

    # Closed course: historic grades only (same read-only surface as parent).
    historic_viewer = course_is_closed(course)
    if not historic_viewer and not _user_can_access_course_page(request.user, course):
        messages.error(request, "You do not have access to this course.")
        return redirect("dashboard")

    from .assessment_grades import student_grades_for_course

    payload = student_grades_for_course(course, request.user)
    return render(
        request,
        "assessment_tool/course_grades_student.html",
        {
            "course": course,
            "active_tab": "grades",
            "grade_rows": payload["rows"],
            "grade_total": payload["total"],
            "grade_aggregation_mode": payload["grade_aggregation_mode"],
            "is_teacher_viewer": False,
            "historic_viewer": historic_viewer,
            "grades_subtitle": (
                "Your historic scores for this closed course."
                if historic_viewer
                else None
            ),
        },
    )


@login_required
def course_grades_assessment_view(request, course_id, assessment_id):
    course = get_object_or_404(Course, id=course_id)
    denied = _teacher_grades_access(request, course)
    if denied:
        return denied
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course=course,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .assessment_grades import (
        assessment_has_retake_attempts,
        assessment_grade_question_choices,
        student_rows_for_assessment,
        unfinished_manual_grading,
        scores_visible_for_assessment,
        assessment_release_mode,
        assessment_counts_toward_grade,
    )

    student_rows = student_rows_for_assessment(assessment)
    return render(
        request,
        "assessment_tool/course_grades_assessment.html",
        {
            "course": course,
            "assessment": assessment,
            "active_tab": "grades",
            "student_rows": student_rows,
            "show_retake_column": assessment_has_retake_attempts(student_rows),
            "show_focus_lock_column": any(
                row.get("focus_lock_count") for row in student_rows
            ),
            "unfinished": unfinished_manual_grading(assessment),
            "question_choices": assessment_grade_question_choices(assessment),
            "scores_visible_to_students": scores_visible_for_assessment(assessment),
            "student_release_mode": assessment_release_mode(assessment),
            "counts_toward_grade": assessment_counts_toward_grade(assessment),
            "assessment_is_open": (assessment.status or "").lower()
            in ("open", "upcoming", "active", "retake available"),
        },
    )


@login_required
def course_grades_assessment_performance_view(request, course_id, assessment_id):
    """Per-question averages for each student's grade-counting attempt."""
    from django.utils.http import url_has_allowed_host_and_scheme

    course = get_object_or_404(Course, id=course_id)
    denied = _teacher_grades_access(request, course)
    if denied:
        return denied
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course=course,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .assessment_grades import assessment_performance_summary

    fallback_url = reverse("course_grades", kwargs={"course_id": course.id})
    back_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or ""
    if not url_has_allowed_host_and_scheme(
        back_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        back_url = fallback_url

    return render(
        request,
        "assessment_tool/course_grades_assessment_performance.html",
        {
            "course": course,
            "assessment": assessment,
            "performance": assessment_performance_summary(assessment),
            "back_url": back_url,
        },
    )


@login_required
def course_grades_manual_batch_view(request, course_id, assessment_id):
    """Temporary batch page: all questions still needing manual grading."""
    course = get_object_or_404(Course, id=course_id)
    denied = _teacher_grades_access(request, course)
    if denied:
        return denied
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course=course,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    return render(
        request,
        "assessment_tool/course_grades_manual_batch.html",
        {
            "course": course,
            "assessment": assessment,
            "active_tab": "grades",
            "load_problem_workspace": True,
        },
    )


@login_required
def course_grades_manual_batch_payload_ajax(request, course_id, assessment_id):
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course=course,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .assessment_grades import manual_batch_review_payload

    payload = manual_batch_review_payload(assessment)
    return JsonResponse({"success": True, **payload})


@login_required
def course_grades_question_batch_view(request, course_id, assessment_id, slot_index):
    """One question for all students who have a score on that slot."""
    from django.utils.http import url_has_allowed_host_and_scheme

    course = get_object_or_404(Course, id=course_id)
    denied = _teacher_grades_access(request, course)
    if denied:
        return denied
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course=course,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .assessment_grades import assessment_grade_question_choices

    fallback_url = reverse(
        "course_grades_assessment",
        kwargs={"course_id": course.id, "assessment_id": assessment.id},
    )
    back_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or ""
    if not url_has_allowed_host_and_scheme(
        back_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        back_url = fallback_url

    choices = assessment_grade_question_choices(assessment)
    try:
        slot_i = int(slot_index)
    except (TypeError, ValueError):
        messages.error(request, "Invalid question.")
        return redirect(back_url)
    current = next((c for c in choices if c["slot_index"] == slot_i), None)
    other_choices = [c for c in choices if c["slot_index"] != slot_i]
    return render(
        request,
        "assessment_tool/course_grades_question_batch.html",
        {
            "course": course,
            "assessment": assessment,
            "active_tab": "grades",
            "load_problem_workspace": True,
            "slot_index": slot_i,
            "question_title": (current or {}).get("title") or f"Question {slot_i}",
            "other_question_choices": other_choices,
            "back_url": back_url,
        },
    )


@login_required
def course_grades_question_batch_payload_ajax(
    request, course_id, assessment_id, slot_index
):
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course=course,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .assessment_grades import question_batch_review_payload

    payload = question_batch_review_payload(assessment, slot_index)
    return JsonResponse({"success": True, **payload})


@login_required
@require_POST
def course_grades_attempt_action_ajax(request, course_id, assessment_id, attempt_id):
    """Teacher per-student actions: open retake, adjust score, void score."""
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course=course,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .student_attempts import get_attempt_for_template

    attempt = get_attempt_for_template(assessment, attempt_id)
    if attempt is None:
        return JsonResponse({"error": "Attempt not found."}, status=404)
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    action = str(body.get("action") or "").strip().lower()
    from .student_assessment_actions import (
        adjust_attempt_score,
        close_test_for_retake,
        open_test_for_retake,
        void_attempt_score,
    )

    if action == "open_retake":
        result = open_test_for_retake(
            assessment,
            attempt.user,
            synchronization_decision=body.get("synchronization_decision"),
            created_by=request.user,
        )
    elif action == "close_retake":
        result = close_test_for_retake(assessment, attempt.user)
    elif action == "adjust_score":
        result = adjust_attempt_score(
            attempt,
            earned_points=body.get("earned_points"),
            max_points=body.get("max_points"),
        )
    elif action == "void_score":
        result = void_attempt_score(attempt)
    elif action == "unlock_focus":
        from .assessment_focus_lock import release_focus_lock

        result = release_focus_lock(
            attempt,
            released_by=request.user,
            reason="teacher",
        )
    elif action == "regrade":
        from .student_attempts import regrade_attempt

        result = regrade_attempt(attempt, preserve_teacher_scores=True)
    else:
        return JsonResponse({"error": "Unknown action."}, status=400)

    status = (
        200
        if result.get("success")
        else (409 if result.get("code") == "synchronization_decision_required" else 400)
    )
    return JsonResponse(result, status=status)


@login_required
@require_POST
def course_grades_aggregation_ajax(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    from .assessment_grades import set_course_grade_aggregation_mode

    result = set_course_grade_aggregation_mode(course, body.get("mode") or "")
    status = 200 if result.get("success") else 400
    return JsonResponse(result, status=status)


@login_required
def course_grades_options_ajax(request, course_id):
    """GET/POST course default assessment options (gear icon)."""
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    from .assessment_options import (
        course_default_options_payload,
        save_course_default_options,
    )

    if request.method == "GET":
        return JsonResponse(course_default_options_payload(course))
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    result = save_course_default_options(
        course,
        body.get("selections") or [],
        default_time_limit_minutes=body.get("default_time_limit_minutes"),
    )
    status = 200 if result.get("success") else 400
    return JsonResponse(result, status=status)


@login_required
def course_grades_assessment_options_ajax(request, course_id, assessment_id):
    """GET/POST per-assessment option overrides."""
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment, id=assessment_id, course=course, parent_assessment__isnull=True
    )
    from .assessment_options import (
        assessment_options_payload,
        save_assessment_options,
    )

    subset = request.GET.get("subset") or None
    if request.method == "GET":
        return JsonResponse(assessment_options_payload(assessment, subset=subset))
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    subset = body.get("subset") or subset
    result = save_assessment_options(
        assessment,
        body.get("selections") or [],
        time_limit_minutes=body.get("time_limit_minutes"),
        subset=subset,
    )
    status = 200 if result.get("success") else 400
    return JsonResponse(result, status=status)


@login_required
@require_POST
def course_grades_assessment_weight_ajax(request, course_id, assessment_id):
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment, id=assessment_id, course=course, parent_assessment__isnull=True
    )
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    from .assessment_grades import set_assessment_grade_weight

    result = set_assessment_grade_weight(assessment, body.get("grade_weight"))
    status = 200 if result.get("success") else 400
    return JsonResponse(result, status=status)


@login_required
@require_POST
def course_grades_assessment_curve_ajax(request, course_id, assessment_id):
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment, id=assessment_id, course=course, parent_assessment__isnull=True
    )
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    from .assessment_grades import (
        grades_overview_for_course,
        set_assessment_curve_bonus_points,
        teacher_course_gradebook,
    )

    result = set_assessment_curve_bonus_points(
        assessment, body.get("curve_bonus_points")
    )
    if result.get("success"):
        overview_rows = grades_overview_for_course(course)
        result["overview_row"] = next(
            (row for row in overview_rows if row["assessment_id"] == assessment.id),
            None,
        )
        result["gradebook"] = teacher_course_gradebook(course)
    status = 200 if result.get("success") else 400
    return JsonResponse(result, status=status)


@login_required
@require_POST
def course_grades_assessment_release_ajax(request, course_id, assessment_id):
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment,
        id=assessment_id,
        course=course,
        parent_assessment__isnull=True,
        user__isnull=True,
    )
    from .assessment_grades import (
        assessment_counts_toward_grade,
        assessment_needs_teacher_release,
        assessment_release_mode,
        apply_assessment_release,
        scores_ready_for_release,
    )
    from .assessment_options import score_release_requires_teacher

    if not score_release_requires_teacher(assessment):
        return JsonResponse(
            {
                "success": False,
                "error": "This assessment releases grades automatically.",
            },
            status=400,
        )
    if bool(getattr(assessment, "scores_released", False)):
        return JsonResponse(
            {
                "success": True,
                "already_released": True,
                "scores_released": True,
                "needs_teacher_release": False,
            }
        )
    if not scores_ready_for_release(assessment):
        return JsonResponse(
            {
                "success": False,
                "error": "No grades are ready to release yet.",
            },
            status=400,
        )
    mode = assessment_release_mode(assessment)
    result = apply_assessment_release(
        assessment,
        mode=mode,
        counts_toward_grade=assessment_counts_toward_grade(assessment),
        force=True,
    )
    if result.get("success"):
        result["needs_teacher_release"] = assessment_needs_teacher_release(assessment)
    status = 200 if result.get("success") else 400
    return JsonResponse(result, status=status)


@login_required
def course_grades_attempt_view(request, course_id, assessment_id, attempt_id):
    course = get_object_or_404(Course, id=course_id)
    assessment = get_object_or_404(
        Assessment, id=assessment_id, course=course, parent_assessment__isnull=True
    )
    from .student_attempts import get_attempt_for_template

    attempt = get_attempt_for_template(assessment, attempt_id)
    if attempt is None or attempt.course_id != course.id:
        messages.error(request, "Attempt not found.")
        return redirect("dashboard")
    from .assessment_grades import (
        scores_visible_for_assessment,
        student_may_review_attempt,
    )

    user_type = getattr(request.user, "user_type", None)
    student_readonly = False
    parent_viewer = False
    historic_viewer = False
    if user_type in ("Teacher", "IT_Support"):
        unavailable_denied = deny_unavailable_course_entry(request, course)
        if unavailable_denied:
            return unavailable_denied
        if not _user_can_access_course_page(request.user, course):
            messages.error(request, "You do not have access to this course.")
            return redirect("dashboard")
    elif user_type == "Student" and attempt.user_id == request.user.user_id:
        if not student_can_view_course_grades(request.user, course):
            messages.error(request, "You do not have access to this course.")
            return redirect("dashboard")
        historic_viewer = course_is_closed(course)
        if not historic_viewer and not _user_can_access_course_page(request.user, course):
            messages.error(request, "You do not have access to this course.")
            return redirect("dashboard")
        if not student_may_review_attempt(assessment, attempt):
            messages.error(
                request,
                "Your teacher has not enabled submission review for this assessment.",
            )
            if historic_viewer:
                return redirect("course_grades", course_id=course.id)
            return redirect("assessment_view", course_id=course.id)
        student_readonly = True
    elif user_type == "Parent" and parent_has_course_access(
        parent=request.user,
        student=attempt.user,
        course=course,
    ):
        if course_is_deleted(course):
            messages.warning(
                request,
                "This course is in Trash. Grades are unavailable until it is restored.",
            )
            return redirect("dashboard")
        if not student_may_review_attempt(assessment, attempt):
            messages.error(
                request,
                "Submission review is not available for this assessment.",
            )
            return redirect(
                "grade_summary",
                student_id=attempt.user_id,
                course_id=course.id,
            )
        student_readonly = True
        parent_viewer = True
    else:
        messages.error(request, "Unauthorized.")
        return redirect("dashboard")

    return render(
        request,
        "assessment_tool/course_grades_review.html",
        {
            "course": course,
            "assessment": assessment,
            "attempt": attempt,
            "active_tab": "grades",
            "load_problem_workspace": True,
            "scores_visible_to_students": scores_visible_for_assessment(assessment),
            "student_readonly": student_readonly,
            "parent_viewer": parent_viewer,
            "historic_viewer": historic_viewer,
        },
    )


@login_required
def course_grades_attempt_payload_ajax(request, course_id, assessment_id, attempt_id):
    course = get_object_or_404(Course, id=course_id)
    assessment = get_object_or_404(
        Assessment, id=assessment_id, course=course, parent_assessment__isnull=True
    )
    from .student_attempts import get_attempt_for_template

    attempt = get_attempt_for_template(assessment, attempt_id)
    if attempt is None:
        return JsonResponse({"error": "Attempt not found."}, status=404)
    user_type = getattr(request.user, "user_type", None)
    student_readonly = False
    if user_type in ("Teacher", "IT_Support"):
        if course_is_deleted(course) or (
            course_is_closed(course) and user_type == "Teacher"
        ):
            return JsonResponse({"error": "Course is closed."}, status=403)
        if not _user_can_access_course_page(request.user, course):
            return JsonResponse({"error": "Unauthorized"}, status=403)
    elif user_type == "Student" and attempt.user_id == request.user.user_id:
        if not student_can_view_course_grades(request.user, course):
            return JsonResponse({"error": "Unauthorized"}, status=403)
        if not course_is_closed(course) and not _user_can_access_course_page(
            request.user, course
        ):
            return JsonResponse({"error": "Unauthorized"}, status=403)
        from .assessment_grades import student_may_review_attempt

        if not student_may_review_attempt(assessment, attempt):
            return JsonResponse({"error": "Review not available."}, status=403)
        student_readonly = True
    elif user_type == "Parent" and parent_has_course_access(
        parent=request.user,
        student=attempt.user,
        course=course,
    ):
        if course_is_deleted(course):
            return JsonResponse({"error": "Course is in Trash."}, status=403)
        from .assessment_grades import student_may_review_attempt

        if not student_may_review_attempt(assessment, attempt):
            return JsonResponse({"error": "Review not available."}, status=403)
        student_readonly = True
    else:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    from .assessment_grades import teacher_review_payload

    payload = teacher_review_payload(attempt)
    payload["student_readonly"] = student_readonly
    return JsonResponse({"success": True, **payload})


@login_required
@require_POST
def course_grades_attempt_save_ajax(request, course_id, assessment_id, attempt_id):
    course = get_object_or_404(Course, id=course_id)
    if getattr(request.user, "user_type", None) not in ("Teacher", "IT_Support"):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    if course_is_deleted(course) or (
        course_is_closed(course)
        and getattr(request.user, "user_type", None) == "Teacher"
    ):
        return JsonResponse({"error": "Course is unavailable."}, status=403)
    if not _user_can_access_course_page(request.user, course):
        return JsonResponse({"error": "Unauthorized"}, status=403)
    assessment = get_object_or_404(
        Assessment, id=assessment_id, course=course, parent_assessment__isnull=True
    )
    from .student_attempts import get_attempt_for_template

    attempt = get_attempt_for_template(assessment, attempt_id)
    if attempt is None:
        return JsonResponse({"error": "Attempt not found."}, status=404)
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    from .assessment_grades import apply_teacher_scores

    result = apply_teacher_scores(attempt, body.get("updates") or [])
    status = 200 if result.get("success") else 400
    return JsonResponse(result, status=status)


# Legacy session stubs retired — use student_assessment_* endpoints above.
@login_required
@require_POST
def start_student_assessment_session(request, assessment_id):
    return JsonResponse(
        {
            "error": "Deprecated. Use the student assessment take flow.",
            "code": "deprecated",
        },
        status=410,
    )


@login_required
@require_POST
def submit_student_assessment_evaluation(request, assessment_id):
    return JsonResponse(
        {
            "error": "Deprecated. Use the student assessment take flow.",
            "code": "deprecated",
        },
        status=410,
    )


def verify_workspace_clearance(user, problem):
    """
    Validates structural user clearance across three conditions:
    - User is 'IT_Support'
    - User has ≥ edit ACL on the problem branch (includes owner)
    - User is a 'Teacher' registered inside the course ancestry track
    """
    if not user.is_authenticated or user.user_type == 'Student':
        return False
        
    if user.user_type == 'IT_Support':
        return True

    branch = getattr(problem, 'branch_location', None)
    if branch is not None and can_edit_branch(user, branch):
        return True
        
    if problem.branch_location and problem.branch_location.owner == user:
        return True
        
    if problem.aqg_id:
        has_group_clearance = UsersInCourse.objects.filter(
            user=user,
            user__user_type='Teacher',
            course__assessment_id_originator__assessmentquestiongroup__problem=problem
        ).exists()
        if has_group_clearance:
            return True
            
    return False


def verify_workspace_read_clearance(user, problem):
    """Read access for problem workspace overlay (view or edit ACL)."""
    if verify_workspace_clearance(user, problem):
        return True
    if not user.is_authenticated or user.user_type == 'Student':
        return False
    branch = getattr(problem, 'branch_location', None)
    return branch is not None and can_read_branch(user, branch)






# Workspace tokens always end with a trailing index (e.g. primeFactors1); avoid matching HTML tags like <br>
_ENTITY_TOKEN_RE = re.compile(r'(?:&lt;|<)([a-zA-Z][a-zA-Z0-9_]*\d+)(?:&gt;|>)')


def _is_quill_display_empty(body_html):
    """True when the problem display canvas has no meaningful teacher text/tokens."""
    if not body_html or not str(body_html).strip():
        return True
    raw = str(body_html)
    # Quill stores tokens as &lt;primeFactors1&gt;; count those before stripping HTML
    has_entity_token = bool(_ENTITY_TOKEN_RE.search(raw))
    without_tokens = _ENTITY_TOKEN_RE.sub(' ', raw)
    text = html.unescape(without_tokens)
    text = re.sub(r'<[^>]+>', ' ', text).replace('\xa0', ' ').strip()
    return not text and not has_entity_token


def _entity_is_referenced_anywhere(sequence_token, body_html, all_entities):
    """True when a token is used in the display HTML or linked from another entity."""
    raw_html = body_html or ""
    # Quill persists literal tokens as &lt;token&gt; rather than raw <token>
    markers = (f"<{sequence_token}>", f"&lt;{sequence_token}&gt;")
    if any(marker in raw_html for marker in markers):
        return True
    if f"<{sequence_token}>" in html.unescape(raw_html):
        return True
    for entity in all_entities:
        if entity.get("sequence_token") == sequence_token:
            continue
        serialized = json.dumps(entity.get("inputs", {}))
        if any(marker in serialized for marker in markers):
            return True
        if f"<{sequence_token}>" in html.unescape(serialized):
            return True
    return False


@require_POST
@login_required
def grade_problem_workspace_preview(request, problem_id):
    """
    Ephemeral server-side grading for the workspace simulation preview.
    Does not persist scores or student answers.
    """
    try:
        problem = Problem.objects.get(pk=problem_id)
    except Problem.DoesNotExist:
        return JsonResponse({"success": False, "error": "Problem not found"}, status=404)

    if not verify_workspace_clearance(request.user, problem):
        return JsonResponse({
            "success": False,
            "error": "Permission Denied: Insufficient authorization clearing."
        }, status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Malformed JSON payload."}, status=400)

    entities = payload.get("entities") or []
    context_entities = payload.get("all_entities") or entities
    student_answers = payload.get("student_answers") or {}
    if not isinstance(entities, list):
        return JsonResponse({"success": False, "error": "entities must be an array."}, status=400)
    if not isinstance(context_entities, list):
        return JsonResponse({"success": False, "error": "all_entities must be an array."}, status=400)
    if not isinstance(student_answers, dict):
        return JsonResponse({"success": False, "error": "student_answers must be an object."}, status=400)

    graded = grade_entities_payload(entities, context_entities, student_answers)
    return JsonResponse({
        "success": True,
        "items": graded["items"],
        "earned_total": graded["earned_total"],
        "max_total": graded["max_total"],
    })


def _user_can_manage_assessment(request, course_id, assessment=None):
    """Course teacher / IT, or ≥ edit ACL on the assessment or course branch."""
    user = request.user
    user_type = getattr(user, 'user_type', 'Student')
    if user_type == 'IT_Support' or user.is_staff:
        return True
    db_course_id = resolve_assessment_course_id(course_id)
    if db_course_id is not None and UsersInCourse.objects.filter(
        course_id=db_course_id,
        user=user,
        user__user_type='Teacher',
    ).exists():
        return True
    branch = getattr(assessment, 'branch_location', None) if assessment is not None else None
    if branch is None and db_course_id is not None:
        course = (
            Course.objects.filter(pk=db_course_id)
            .select_related('branch_location')
            .first()
        )
        branch = getattr(course, 'branch_location', None) if course else None
    return bool(branch is not None and can_edit_branch(user, branch))


@login_required
def assessment_practice_test_view(request, course_id, assessment_id):
    """Teacher practice-test page for an assessment (ephemeral, not saved)."""
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location', 'course'),
    )
    course = assessment.course
    if not _user_can_open_assessment_setup(request.user, course, assessment):
        messages.error(request, "You do not have access to preview this assessment.")
        if course is None:
            return redirect('file_explorer')
        return redirect('course_dashboard', course_id=course.id)

    user_type = getattr(request.user, 'user_type', 'Student')
    return render(request, 'assessment_tool/assessment_practice_test.html', {
        'course': course,
        'course_url_id': assessment_course_url_id(assessment),
        'assessment': assessment,
        'user_type': user_type if user_type == 'IT_Support' else 'Teacher',
        'load_problem_workspace': True,
        'active_tab': 'assessments',
    })


@login_required
@require_POST
def assessment_practice_test_start_ajax(request, course_id, assessment_id):
    """Assemble fully rendered practice-test instances for this assessment."""
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location', 'course'),
    )
    if not _user_can_open_assessment_setup(request.user, assessment.course, assessment):
        return JsonResponse({'success': False, 'error': 'Unauthorized.'}, status=403)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = {}

    confirm_drafts = bool(data.get('confirm_drafts'))
    confirm_zero_sets = bool(data.get('confirm_zero_sets'))

    from .view_mode import is_content_view_only

    assembled = assemble_practice_test(
        assessment,
        actor_user=request.user,
        allow_status_mutation=not is_content_view_only(request),
    )
    skipped_drafts = assembled.get('skipped_drafts') or []
    zero_count_sets = assembled.get('zero_count_sets') or []
    omitted_render_failures = assembled.get('omitted_render_failures') or []

    needs = []
    if skipped_drafts and not confirm_drafts:
        needs.append('drafts')
    if zero_count_sets and not confirm_zero_sets:
        needs.append('zero_sets')

    if needs:
        return JsonResponse({
            'success': False,
            'needs_confirmation': True,
            'needs': needs,
            'skipped_drafts': skipped_drafts,
            'zero_count_sets': zero_count_sets,
            'message': 'Confirmation required before starting the practice test.',
        }, status=200)

    return JsonResponse({
        'success': True,
        'assessment_id': assessment.id,
        'assessment_name': assessment.name,
        'problems': assembled.get('problems') or [],
        'skipped_drafts': skipped_drafts,
        'zero_count_sets': zero_count_sets,
        'omitted_render_failures': omitted_render_failures,
        'problem_count': assembled.get('problem_count', 0),
    }, status=200)


@login_required
@require_POST
def assessment_practice_test_grade_ajax(request, course_id, assessment_id):
    """Batch-grade an ephemeral practice test in one request."""
    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=('branch_location', 'course'),
    )
    if not _user_can_open_assessment_setup(request.user, assessment.course, assessment):
        return JsonResponse({'success': False, 'error': 'Unauthorized.'}, status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Malformed JSON payload.'}, status=400)

    problems_payload = payload.get('problems') or []
    if not isinstance(problems_payload, list):
        return JsonResponse({'success': False, 'error': 'problems must be an array.'}, status=400)

    results = []
    earned_total = 0.0
    max_total = 0.0

    for slot in problems_payload:
        if not isinstance(slot, dict):
            continue
        problem_id = slot.get('problem_id')
        title = slot.get('title') or f'Problem {problem_id}'
        slot_index = slot.get('slot_index')
        entities = slot.get('entities') or slot.get('answer_fields') or []
        all_entities = slot.get('all_entities') or entities
        student_answers = slot.get('student_answers') or {}
        if not isinstance(entities, list) or not isinstance(all_entities, list) or not isinstance(student_answers, dict):
            continue

        graded = grade_entities_payload(entities, all_entities, student_answers)
        earned_total += graded['earned_total']
        max_total += graded['max_total']
        results.append({
            'problem_id': problem_id,
            'title': title,
            'slot_index': slot_index,
            'earned': graded['earned_total'],
            'max': graded['max_total'],
            'fields': graded['items'],
        })

    return JsonResponse({
        'success': True,
        'problems': results,
        'earned_total': earned_total,
        'max_total': max_total,
    }, status=200)


@require_POST
@login_required
def save_problem_workspace(request, problem_id):
    """
    Save the problem workspace canvas + entities.

    Incomplete / invalid work is allowed. When unfinished reasons exist and the
    client has not confirmed draft save, return needs_confirmation with reasons.
    Confirmed unfinished saves set problem_status='draft'; clean saves set 'complete'.
    With force_complete_div0 + confirm_draft, division-by-zero / non-finite warnings
    are ignored for status so the problem can still be marked complete.
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Malformed JSON payload specification request."}, status=400)

    try:
        problem = Problem.objects.select_related('branch_location').get(pk=problem_id)
    except Problem.DoesNotExist:
        return JsonResponse({"success": False, "error": f"Problem reference ID {problem_id} not found."}, status=404)

    if not verify_workspace_clearance(request.user, problem):
        return JsonResponse({'success': False, 'error': 'Permission Denied: Insufficient authorization clearing.'}, status=403)

    user_inputs = payload.get("inputs", [])
    body_html = payload.get("body_html", "").strip()
    confirm_draft = bool(payload.get("confirm_draft", False))
    force_complete_div0 = bool(payload.get("force_complete_div0", False))

    if not isinstance(user_inputs, list):
        return JsonResponse({"success": False, "error": "The workspace inputs block layout must be an array list structure."}, status=400)

    unfinished_reasons = []

    if _is_quill_display_empty(body_html):
        unfinished_reasons.append("The problem display area has no student-facing content yet.")

    # =========================================================================
    # Topological sort so dependency chains validate in order
    # =========================================================================
    sorted_user_inputs = []
    visited_tokens = set()
    input_map = {entity.get("sequence_token"): entity for entity in user_inputs if entity.get("sequence_token")}

    def visit_node(node_token):
        if node_token in visited_tokens:
            return
        node_data = input_map.get(node_token)
        if not node_data:
            return

        inputs_str = json.dumps(node_data.get("inputs", {}))
        for token_key in input_map.keys():
            if f"<{token_key}>" in inputs_str and token_key != node_token:
                visit_node(token_key)

        visited_tokens.add(node_token)
        sorted_user_inputs.append(node_data)

    for entity in user_inputs:
        seq = entity.get("sequence_token")
        if seq and seq not in visited_tokens:
            visit_node(seq)

    for entity in user_inputs:
        if not entity.get("sequence_token"):
            sorted_user_inputs.append(entity)
    # =========================================================================

    for entity_data in sorted_user_inputs:
        sequence_token = entity_data.get("sequence_token") or entity_data.get("token")
        if sequence_token and not _entity_is_referenced_anywhere(sequence_token, body_html, sorted_user_inputs):
            unfinished_reasons.append(
                f"Entity '{sequence_token}' is not used in the display area or linked by any other entity."
            )

    cached_patterns = {}
    persistable_engines = []
    locally_validated_tokens = set()

    for index, entity_data in enumerate(sorted_user_inputs):
        token_id = entity_data.get("token")
        sequence_token = entity_data.get("sequence_token", token_id)

        if not token_id:
            unfinished_reasons.append(f"Workspace entity at position {index + 1} is missing its type token.")
            continue

        if token_id not in cached_patterns:
            try:
                entity_type_record = EntityType.objects.get(name=token_id)
                pattern_data = entity_type_record.format_pattern
                if isinstance(pattern_data, str):
                    pattern_data = json.loads(pattern_data)
                cached_patterns[token_id] = pattern_data
            except EntityType.DoesNotExist:
                unfinished_reasons.append(
                    f"Entity '{sequence_token or token_id}' uses unknown type '{token_id}'."
                )
                continue

        blueprint = cached_patterns[token_id]
        provided_fields = entity_data.get("inputs", {}) or {}
        display_name = blueprint.get('name', token_id)
        label = sequence_token or display_name

        substitutions_map = {}
        cleaned_provided_fields = {}
        solve_method = provided_fields.get("solve method", "")

        for key, value in provided_fields.items():
            if key == "substitutions" and isinstance(value, dict):
                for sub_k, sub_v in value.items():
                    substitutions_map[f"sub_{sub_k}"] = sub_v
            elif key.startswith('sub_'):
                substitutions_map[key] = value
            else:
                cleaned_provided_fields[key] = value

        if token_id == 'formula':
            if not cleaned_provided_fields.get('formula'):
                cleaned_provided_fields['formula'] = "0"

            if solve_method == 'variable substitution':
                has_substitutions = len(substitutions_map) > 0 or "substitutions" in provided_fields
                if not has_substitutions:
                    is_linked_dependency = any(
                        f"<{sequence_token}>" in str(entity.get("inputs", {}))
                        for entity in sorted_user_inputs if entity.get("sequence_token") != sequence_token
                    )
                    if not is_linked_dependency:
                        unfinished_reasons.append(
                            f"[{label}] Variable substitution mode has no substitution rows."
                        )
                cleaned_provided_fields['variable to solve for'] = ""

            elif solve_method == 'simplify':
                cleaned_provided_fields['variable to solve for'] = cleaned_provided_fields.get(
                    'variable to solve for', ''
                ).strip()
            else:
                vars_list = [
                    v.strip()
                    for v in cleaned_provided_fields.get('variables', '').split(',')
                    if v.strip()
                ]
                if vars_list and not cleaned_provided_fields.get('variable to solve for'):
                    cleaned_provided_fields['variable to solve for'] = vars_list[0]
                else:
                    cleaned_provided_fields['variable to solve for'] = cleaned_provided_fields.get(
                        'variable to solve for', ''
                    ).strip()

        # Formula/matrix substitutions live under sub_* / substitutions — merge so
        # evaluate_output and structural checks see the same links as the preview.
        # Prefer the nested substitutions map (serialize always brackets tokens) over
        # any bare sub_* values collected from data-bound-token.
        if token_id in ('formula', 'matrix') and substitutions_map:
            cleaned_provided_fields.update(substitutions_map)
        if token_id in ('formula', 'matrix') and isinstance(provided_fields.get('substitutions'), dict):
            cleaned_provided_fields['substitutions'] = provided_fields['substitutions']
            for sub_k, sub_v in provided_fields['substitutions'].items():
                if sub_v is None or sub_v == '':
                    continue
                cleaned_provided_fields[f'sub_{sub_k}'] = sub_v
                substitutions_map[f'sub_{sub_k}'] = sub_v

        runtime_payload = []
        for entity in sorted_user_inputs:
            entity_copy = dict(entity)
            ent_seq = entity_copy.get("sequence_token")
            if ent_seq in locally_validated_tokens:
                entity_copy["is_validated_dependency"] = True
                entity_copy["outstanding_errors"] = False
            runtime_payload.append(entity_copy)

        # Ensure nested formula expansion can identify this card
        if sequence_token:
            cleaned_provided_fields.setdefault('sequence_token', sequence_token)

        validator = get_entity_validator(
            token_id,
            cleaned_provided_fields,
            blueprint,
            all_entities_payload=runtime_payload
        )

        is_valid = validator.is_valid()

        # Schema/syntax checks replace linked tokens with placeholders, so an
        # entity can pass is_valid() and still blow up when the resolved sympy
        # form is evaluated (e.g. formula referencing another Integral result).
        if is_valid and token_id in ('formula', 'matrix', 'graph', 'matrixResultByIndex', 'slopeFieldGraph', 'graphBetweenPoints'):
            try:
                eval_result = validator.evaluate_output()
                # Sample evaluation can yield zoo/oo without raising — treat as unfinished.
                if token_id == 'formula':
                    result_obj = getattr(validator, 'last_computed_sympy_result', None)
                    zoo_hit = False
                    try:
                        if result_obj is not None and hasattr(result_obj, 'has'):
                            zoo_hit = bool(
                                result_obj.has(sp.zoo)
                                or result_obj.has(sp.oo)
                                or result_obj.has(-sp.oo)
                                or result_obj.has(sp.nan)
                            )
                    except Exception:
                        zoo_hit = False
                    if not zoo_hit and isinstance(eval_result, str):
                        lowered = eval_result.strip().lower()
                        zoo_hit = lowered in ('zoo', 'nan', 'oo', 'complex_infinity') or 'zoo' in lowered
                    if zoo_hit:
                        is_valid = False
                        validator.errors["evaluation"] = (
                            "Expression evaluates to a non-finite value (possible division by zero)."
                        )
            except Exception as eval_err:
                is_valid = False
                validator.errors["evaluation"] = (
                    f"Expression could not be evaluated after resolving linked "
                    f"entities: {eval_err}"
                )

        # Structural range check: linked rand/randInt mins/maxes can force a zero denominator.
        # Prefer an actionable message that includes a min/max Suggestion over an upstream
        # free-variable-only warning (same issue, but the downstream card can propose a fix).
        div0_only_failure = False
        if token_id == 'formula' and hasattr(validator, 'check_possible_division_by_zero'):
            already_has_actionable_div0 = any(
                'Possible division by zero' in reason and 'Suggestion:' in reason
                for reason in unfinished_reasons
            )
            if not already_has_actionable_div0:
                try:
                    div0_msg = validator.check_possible_division_by_zero()
                except Exception:
                    div0_msg = None
                if div0_msg:
                    is_valid = False
                    div0_only_failure = True
                    labeled = f"[{label}] {div0_msg}"
                    if 'Suggestion:' in div0_msg:
                        unfinished_reasons = [
                            r for r in unfinished_reasons
                            if 'Possible division by zero' not in r
                        ]
                        unfinished_reasons.append(labeled)
                    elif not any('Possible division by zero' in r for r in unfinished_reasons):
                        unfinished_reasons.append(labeled)

        if not is_valid:
            if not div0_only_failure:
                error_details = "; ".join([f"{k}: {v}" for k, v in validator.errors.items()])
                if error_details:
                    unfinished_reasons.append(f"[{label}] {error_details}")
            # Persist raw teacher inputs so unfinished drafts can be reopened exactly
            draft_content = dict(cleaned_provided_fields)
            for sub_key, sub_value in substitutions_map.items():
                draft_content[sub_key] = sub_value
            content_source = draft_content
        else:
            if sequence_token:
                locally_validated_tokens.add(sequence_token)
            content_source = dict(validator.cleaned_data)
            if token_id in ['formula', 'matrix']:
                for sub_key, sub_value in substitutions_map.items():
                    content_source[sub_key] = sub_value
            # Keep formula / shortAnswer UI checkboxes even when blueprint hasn't been re-seeded yet
            if token_id == 'formula':
                for checkbox_key in ('output rhs only', 'simplify after substitution'):
                    if checkbox_key in cleaned_provided_fields:
                        content_source[checkbox_key] = cleaned_provided_fields[checkbox_key]
                    elif checkbox_key not in content_source:
                        content_source[checkbox_key] = False
            elif token_id == 'shortAnswer':
                for checkbox_key in ('accept_rounded_decimals',):
                    if checkbox_key in cleaned_provided_fields:
                        content_source[checkbox_key] = cleaned_provided_fields[checkbox_key]
                    elif checkbox_key not in content_source:
                        content_source[checkbox_key] = False

        persistable_engines.append({
            "token_id": token_id,
            "sequence_token": sequence_token,
            "shuffle_seed": entity_data.get("shuffle_seed", ""),
            "points": entity_data.get("points"),
            "blueprint": blueprint,
            "content_source": content_source,
            "is_valid": is_valid,
        })

    # Deduplicate while preserving order
    seen_reasons = set()
    unique_reasons = []
    for reason in unfinished_reasons:
        if reason not in seen_reasons:
            seen_reasons.add(reason)
            unique_reasons.append(reason)
    unfinished_reasons = unique_reasons

    def _is_div0_unfinished_reason(reason):
        text = str(reason or "")
        return (
            "Possible division by zero" in text
            or "non-finite value (possible division by zero)" in text
        )

    # Teacher may acknowledge zoo / structural div0 warnings and still mark complete.
    # Other unfinished issues continue to force draft status.
    status_reasons = unfinished_reasons
    if force_complete_div0 and confirm_draft:
        status_reasons = [r for r in unfinished_reasons if not _is_div0_unfinished_reason(r)]

    if unfinished_reasons and not confirm_draft:
        return JsonResponse({
            "success": False,
            "needs_confirmation": True,
            "unfinished_reasons": unfinished_reasons,
            "message": "Problem is unfinished and requires draft confirmation before saving."
        }, status=200)

    problem_status = 'draft' if status_reasons else 'complete'

    with transaction.atomic():
        problem.title = payload.get("title", problem.title)
        problem.problem_status = problem_status
        problem.save()

        # Keep linked folder name aligned when workspace save changes the title
        if problem.branch_location_id and problem.branch_location.name != problem.title:
            problem.branch_location.name = problem.title
            problem.branch_location.save()

        structured_json_string = json.dumps({"html_content": body_html})
        previous_block_content = ""
        q_block, created = QuestionBlock.objects.get_or_create(
            problem=problem,
            defaults={'content': structured_json_string}
        )
        if not created:
            previous_block_content = q_block.content or ""
            q_block.content = structured_json_string
            q_block.save()

        from .content_images import track_content_image_html_change
        track_content_image_html_change(
            previous_html=previous_block_content,
            new_html=structured_json_string,
        )

        EntitySegment.objects.filter(problem=problem).delete()

        for engine_item in persistable_engines:
            token_id = engine_item["token_id"]
            sequence_token = engine_item["sequence_token"]
            shuffle_seed = engine_item["shuffle_seed"]
            blueprint = engine_item["blueprint"]
            content_payload = dict(engine_item["content_source"])

            # Use this engine item's own points — not leftover entity_data from the
            # validation loop (which incorrectly copied the last entity's Pts onto all).
            points_value = engine_item.get("points")
            if points_value is None:
                points_value = content_payload.get("points")
            if points_value is None:
                points_value = blueprint.get("points", {}).get("default", 0.0)
            content_payload["answer_field"] = blueprint.get("answer_field", False)
            content_payload["sequence_token"] = sequence_token
            content_payload["shuffle_seed"] = shuffle_seed

            blueprint_default = blueprint.get("default_answer")
            default_answer_fallback = (
                str(blueprint_default).lower() in ['true', '1', 'yes']
                if blueprint_default not in [True, False]
                else blueprint_default
            )

            EntitySegment.objects.create(
                problem=problem,
                problem_type_id_originator=EntityType.objects.get(name=token_id),
                content=json.dumps(content_payload),
                points=float(points_value) if points_value is not None else 0.0,
                default_answer=str(default_answer_fallback)
            )

    return JsonResponse({
        "success": True,
        "message": (
            "Workspace saved as draft."
            if problem_status == 'draft'
            else "Workspace saved as complete."
        ),
        "problem_status": problem_status,
        "unfinished_reasons": unfinished_reasons,
    })



@login_required
@user_passes_test(
    lambda u: getattr(u, 'user_type', None) in ('Teacher', 'IT_Support') or u.is_staff,
    login_url='/dashboard/',
)
def problem_workspace_editor(request, problem_id):
    try:
        problem = Problem.objects.select_related('branch_location').get(pk=problem_id)
    except Problem.DoesNotExist:
        return JsonResponse({"success": False, "error": "Problem not found"}, status=404)

    if not verify_workspace_read_clearance(request.user, problem):
        return JsonResponse({"success": False, "error": "Permission denied."}, status=403)

    allow_edit = verify_workspace_clearance(request.user, problem)
    apply_explorer_mode_from_request(request, allow_edit=allow_edit)
    
    # 1. Fetch available EntityType options
    all_types = EntityType.objects.all()
    dynamic_variables_options = []
    answer_fields_options = []
    
    for entity_type in all_types:
        try:
            pattern = entity_type.format_pattern
            if isinstance(pattern, str):
                pattern = json.loads(pattern)
            name_list = entity_type.entity_name_list
            if isinstance(name_list, str):
                name_list = json.loads(name_list)
        except (json.JSONDecodeError, TypeError):
            continue
            
        if pattern.get("disabled") is True:
            continue
            
        token_info = {
            "token": entity_type.name,
            "name": pattern.get("name", entity_type.name),
            "note": pattern.get("note", ""),
            "inputs": pattern.get("inputs", {}),
            "points_default": (pattern.get("points") or {}).get("default", 1.0),
        }
        
        if "Dynamic Variables" in name_list:
            dynamic_variables_options.append(token_info)
        elif "Answer Input Fields" in name_list:
            answer_fields_options.append(token_info)

    # 2. Load existing segments for *this* specific problem
    saved_segments_records = EntitySegment.objects.filter(problem=problem).order_by('id')
    
    # 🎯 FIRST: Build the full workspace environment registry for cross-component lookups
    all_entities_payload = []
    prepped_segments = []
    
    for segment in saved_segments_records:
        if isinstance(segment.content, dict):
            content_data = segment.content
        elif isinstance(segment.content, str) and segment.content.strip():
            try:
                content_data = json.loads(segment.content)
            except json.JSONDecodeError:
                content_data = {}
        else:
            content_data = {}

        token_name = segment.problem_type_id_originator.name
        sequence_token = content_data.get("sequence_token") or token_name
        archetype_name = re.sub(r'\d+$', '', token_name)

        # Create a thoroughly sanitized input payload copy for evaluation engines
        clean_inputs = dict(content_data)
        clean_inputs.pop("answer_field", None)
        clean_inputs.pop("sequence_token", None)
        clean_inputs.pop("shuffle_seed", None)

        all_entities_payload.append({
            'token': archetype_name,
            'sequence_token': str(sequence_token).strip(),
            'inputs': clean_inputs, # 🎯 Clean inputs matching preview structures
            'simulated_value': "" 
        })
        # Keep clean_inputs coupled with the segment block state 
        prepped_segments.append((segment, content_data, clean_inputs, token_name, sequence_token, archetype_name))

    loaded_segments = []
    # 🎯 SECOND: Process each asset using the shared environmental ledger context
    for segment, content_data, clean_inputs, token_name, sequence_token, archetype_name in prepped_segments:
        blueprint_pattern = segment.problem_type_id_originator.format_pattern
        if isinstance(blueprint_pattern, str):
            try:
                blueprint_pattern = json.loads(blueprint_pattern)
            except json.JSONDecodeError:
                blueprint_pattern = {}

        # 🚀 CALL ENCAPSULATED UTILITY
        render_results = evaluate_and_format_entity(
            archetype_name=archetype_name,
            sequence_token=sequence_token,
            clean_inputs=clean_inputs,
            pattern_blueprint=blueprint_pattern,
            all_entities_payload=all_entities_payload
        )

        loaded_segments.append({
            "id": segment.id,
            "token": archetype_name,
            "sequence_token": sequence_token,
            "points": segment.points,
            "inputs": clean_inputs,
            "simulated_value": render_results['evaluated_output'], # Keep for internal map symmetry
            "evaluated_output": render_results['evaluated_output'],
            "latex_output": render_results['latex_output'],
            "output_types": render_results.get('output_types', []),
        })

    # 3. Safely pull Quill rich text from QuestionBlock
    q_block = QuestionBlock.objects.filter(problem=problem).first()
    body_html = "<p><br></p>"
    if q_block and q_block.content:
        # 🎯 FIX: Defensively verify if content is already a dictionary or an unparsed string
        if isinstance(q_block.content, dict):
            content_data = q_block.content
        elif isinstance(q_block.content, str) and q_block.content.strip():
            try:
                content_data = json.loads(q_block.content)
            except json.JSONDecodeError:
                content_data = {}
        else:
            content_data = {}

        # Safely extract the HTML content markup or fallback
        if isinstance(content_data, dict):
            body_html = content_data.get("html_content", "<p><br></p>")
        else:
            body_html = q_block.content

    # 🎯 Return EVERYTHING as a fast, clean AJAX payload response
    return JsonResponse({
        "success": True,
        "title": problem.title,
        "body_html": body_html,
        "dynamic_variables_options": dynamic_variables_options,
        "answer_fields_options": answer_fields_options,
        "loaded_segments": loaded_segments
    })


@csrf_protect
@require_POST
def validate_component_preview(request):
    try:
        payload = json.loads(request.body)
        entities_list = payload.get('entities', [])
        
        
        if not entities_list:
            return JsonResponse({'success': True, 'updated_cache': {}, 'errors': {}})

        trigger_token = payload.get('trigger_token', '')
        mutation_targets = payload.get('mutation_targets', [trigger_token]) # Fallback to just trigger if missing

        # 🎯 FIX: Build a completely bulletproof sibling ledger using uniform lowercase lookups
        all_entities_payload = []
        for item in entities_list:
            token_raw = item.get('token', '')
            sequence_token_raw = str(item.get('sequence_token') or token_raw).strip()
            archetype_name = re.sub(r'\d+$', '', token_raw)
            
            # 🎯 ENFORCED BACKEND LOCK-BREAKER:
            # If this component is targeted for mutation/re-calculation, wipe out its 
            # incoming simulated value so the math engine is forced to evaluate the new inputs.
            if sequence_token_raw in mutation_targets:
                clean_sim_value = ""
            else:
                raw_sim_value = item.get('simulated_value')
                if raw_sim_value is None or str(raw_sim_value).strip() in ["", "None", "null"]:
                    clean_sim_value = ""
                else:
                    clean_sim_value = str(raw_sim_value).strip()

            all_entities_payload.append({
                'token': archetype_name,
                'sequence_token': sequence_token_raw,
                'inputs': item.get('inputs', {}) or {},
                'simulated_value': clean_sim_value
            })

        updated_cache = {}
        global_errors_ledger = {}

        # 1. Map entities by sequence_token for O(1) out-of-order topological tree navigation
        entities_map = {}
        for item in entities_list:
            token_raw = item.get('token', '')
            seq_id = item.get('sequence_token', token_raw).strip()
            entities_map[seq_id] = item

        # 2. 🔀 TOPOLOGICAL SORT: Arrange targets so dependencies compute before consumers
        ordered_targets = []
        visited = set()

        def dfs_topological_sort(node_id):
            if node_id in visited:
                return
            if node_id not in entities_map:
                return
            
            # Extract inputs to scan for raw macro injections like <randInt1>
            current_item = entities_map[node_id]
            input_text_blob = json.dumps(current_item.get('inputs', {}))
            parent_tokens = re.findall(r'(?:<([a-zA-Z0-9_]+)>)', input_text_blob)
            
            for parent_id in parent_tokens:
                # If a structural dependency exists inside our execution track, solve it first
                if parent_id in mutation_targets:
                    dfs_topological_sort(parent_id)
            
            visited.add(node_id)
            ordered_targets.append(node_id)

        for target in mutation_targets:
            dfs_topological_sort(target)


        # 3. Iterate sequentially through our safely ordered DAG pipeline
        for sequence_token_id in ordered_targets:
            item = entities_map[sequence_token_id]
            token_raw = item.get('token', '')
            archetype_name = re.sub(r'\d+$', '', token_raw)
            
            pattern_blueprint = get_blueprint_for_token(archetype_name)
            entity_inputs = item.get('inputs', {}) or {}
            entity_inputs['sequence_token'] = sequence_token_id
            
            # REFRESH LOCK-BREAKER
            if sequence_token_id != trigger_token and archetype_name.lower() in ['rand', 'randint']:
                target_payload = next((x for x in all_entities_payload if x.get("sequence_token") == sequence_token_id), None)
                if target_payload:
                    target_payload['simulated_value'] = ""

            # 🚀 CALL ENCAPSULATED UTILITY
            render_results = evaluate_and_format_entity(
                archetype_name=archetype_name,
                sequence_token=sequence_token_id,
                clean_inputs=entity_inputs,
                pattern_blueprint=pattern_blueprint,
                all_entities_payload=all_entities_payload
            )
            
            if not render_results['is_valid'] and render_results['errors']:
                global_errors_ledger[sequence_token_id] = render_results['errors']

            updated_cache[sequence_token_id] = {
                'evaluated_output': render_results['evaluated_output'],
                'latex_output': render_results['latex_output'],
                'extracted_variables': render_results['extracted_variables'],
                'output_types': render_results.get('output_types', []),
            }

        return JsonResponse({
            'success': len(global_errors_ledger) == 0,
            'updated_cache': updated_cache,
            'errors': global_errors_ledger,
            'error': None
        })

    except Exception as e:
        logger.exception("Component preview evaluation crashed: %s", e)
        return JsonResponse({
            'success': False,
            'updated_cache': {},
            'errors': {},
            'error': f"Math Evaluation Warning: {str(e)}"
        }, status=400)

