"""Course status transitions and unavailable-course access rules."""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone

from .models import UsersInCourse

CLOSED_COURSE_TEACHER_MESSAGE = (
    "This course is closed. Reactivate it from the Courses page first "
    "if you need to make further edits."
)

CLOSED_COURSE_STUDENT_MESSAGE = (
    "This course is closed. You can still view your historic grades from the Dashboard."
)

DELETED_COURSE_MESSAGE = (
    "This course is in Trash. Restore it from the Courses page before opening "
    "or editing it."
)


def course_is_closed(course) -> bool:
    return (getattr(course, "status", None) or "") == "closed"


def course_is_deleted(course) -> bool:
    return (getattr(course, "status", None) or "") == "deleted"


def user_can_close_or_reactivate_course(user, course) -> bool:
    """Same authority as the Courses list status dropdown (owner or IT)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "user_type", None) == "IT_Support":
        return True
    owner_id = getattr(course, "owner_id", None)
    user_id = getattr(user, "user_id", None) or getattr(user, "pk", None)
    return bool(owner_id and user_id and owner_id == user_id)


def apply_course_status(course, new_status: str) -> None:
    """
    Persist a course status change.

    Closing stamps ``close_date`` when missing; reactivating to ``active``
    clears ``close_date`` so the enrollment span stays accurate.
    """
    course.status = new_status
    if new_status == "closed":
        if course.close_date is None:
            course.close_date = timezone.now()
        course.save(update_fields=["status", "close_date"])
    elif new_status == "active":
        course.close_date = None
        course.save(update_fields=["status", "close_date"])
    else:
        course.save(update_fields=["status"])


def user_enrolled_in_course(user, course) -> bool:
    if user is None or course is None:
        return False
    return UsersInCourse.objects.filter(course=course, user=user).exists()


def student_can_view_course_grades(user, course) -> bool:
    """
    Students keep grade access for open and closed enrollments.

    Trashed (deleted) courses are not grade-accessible until restored.
    """
    if getattr(user, "user_type", None) != "Student":
        return False
    if course_is_deleted(course):
        return False
    return user_enrolled_in_course(user, course)


def deny_deleted_course_entry(request, course):
    """
    Block all users from live pages of a trashed course.

    Restore / permanent delete remain on the Courses list only.
    """
    if not course_is_deleted(course):
        return None
    messages.warning(request, DELETED_COURSE_MESSAGE)
    return redirect("course_list")


def deny_closed_course_entry(request, course):
    """
    Block Teachers and Students from entering a closed course's live pages.

    IT Support is allowed through. Returns a redirect response, or None.
    """
    if not course_is_closed(course):
        return None
    user = request.user
    user_type = getattr(user, "user_type", None)
    if getattr(user, "is_staff", False) or user_type == "IT_Support":
        return None
    if user_type == "Teacher":
        messages.warning(request, CLOSED_COURSE_TEACHER_MESSAGE)
        return redirect("course_list")
    if user_type == "Student":
        messages.info(request, CLOSED_COURSE_STUDENT_MESSAGE)
        return redirect("dashboard")
    return None


def deny_unavailable_course_entry(request, course):
    """Deleted (Trash) first, then closed-course rules."""
    deleted = deny_deleted_course_entry(request, course)
    if deleted is not None:
        return deleted
    return deny_closed_course_entry(request, course)
