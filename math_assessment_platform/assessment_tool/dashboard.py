"""Dashboard context helpers for course lists and related display data."""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Q

from .models import ParentUserCourse, UsersInCourse
from .notifications import utc_isoformat


def user_display_name(user) -> str:
    """
    Informal label: "Display Last" when a display name exists, else "First Last",
    else username.
    """
    if user is None:
        return ""
    display = (getattr(user, "user_display_name", None) or "").strip()
    first = (getattr(user, "user_first_name", None) or "").strip()
    last = (getattr(user, "user_last_name", None) or "").strip()
    if display:
        return f"{display} {last}".strip()
    full = f"{first} {last}".strip()
    if full:
        return full
    return getattr(user, "username", "") or ""


def user_greeting_name(user) -> str:
    """Preferred short greeting: display name, else first name, else username."""
    if user is None:
        return ""
    display = (getattr(user, "user_display_name", None) or "").strip()
    if display:
        return display
    first = (getattr(user, "user_first_name", None) or "").strip()
    if first:
        return first
    return getattr(user, "username", "") or ""


def user_roster_formal_name(user) -> str:
    """
    Roster label: "Last, Display" when a display name exists, else "Last, First M"
    (middle initials from extra first-name tokens). Falls back to username when
    name fields are empty.
    """
    if user is None:
        return "?"
    username = (getattr(user, "username", None) or "").strip() or "?"
    display = (getattr(user, "user_display_name", None) or "").strip()
    first = (getattr(user, "user_first_name", None) or "").strip()
    last = (getattr(user, "user_last_name", None) or "").strip()
    if display:
        if last:
            return f"{last}, {display}"
        return display
    if not first and not last:
        return username
    parts = first.split()
    given = parts[0] if parts else ""
    middle_initials = " ".join(p[0].upper() for p in parts[1:] if p)
    if last and given and middle_initials:
        return f"{last}, {given} {middle_initials}"
    if last and given:
        return f"{last}, {given}"
    if last:
        return last
    if given and middle_initials:
        return f"{given} {middle_initials}"
    return given or username


def _status_label(status: str) -> str:
    raw = (status or "").strip()
    if not raw:
        return "Unknown"
    return raw.replace("_", " ").capitalize()


def _teachers_by_course(course_ids):
    teachers_map = defaultdict(list)
    if not course_ids:
        return teachers_map
    rows = (
        UsersInCourse.objects.filter(
            course_id__in=course_ids,
            user__isnull=False,
            user__user_type__in=("Teacher", "IT_Support"),
            user_access="active",
        )
        .select_related("user")
        .order_by("user__user_last_name", "user__user_first_name", "user__username")
    )
    seen = defaultdict(set)
    for row in rows:
        cid = row.course_id
        uid = row.user_id
        if uid in seen[cid]:
            continue
        seen[cid].add(uid)
        teachers_map[cid].append(user_display_name(row.user))
    return teachers_map


def _student_counts_by_course(course_ids):
    if not course_ids:
        return {}
    return {
        row["course_id"]: row["c"]
        for row in (
            UsersInCourse.objects.filter(
                course_id__in=course_ids,
                user__isnull=False,
                user__user_type="Student",
            )
            .values("course_id")
            .annotate(c=Count("id"))
        )
    }


def _enrollment_dates_for_pairs(pairs):
    """pairs: iterable of (student_id, course_id) -> creation_date map."""
    pair_list = [(sid, cid) for sid, cid in pairs if sid and cid]
    if not pair_list:
        return {}
    q = Q()
    for student_id, course_id in pair_list:
        q |= Q(user_id=student_id, course_id=course_id)
    result = {}
    for row in UsersInCourse.objects.filter(q).filter(user__isnull=False):
        result[(row.user_id, row.course_id)] = row.creation_date
    return result


def _sort_dashboard_courses(rows):
    def sort_key(row):
        is_non_active = 0 if row["status"] == "active" else 1
        if row["status"] == "active":
            return (is_non_active, (row["name"] or "").casefold(), row["course_id"])
        enrolled = row.get("enrolled_at")
        # Null enrollment dates sort last within the non-active group.
        ts = enrolled.timestamp() if enrolled is not None else float("inf")
        return (is_non_active, ts, (row["name"] or "").casefold(), row["course_id"])

    return sorted(rows, key=sort_key)


def _build_row(
    *,
    course,
    enrolled_at,
    teachers,
    show_student_count,
    student_count,
    is_parent,
    child_name=None,
    child_id=None,
):
    status = course.status or ""
    is_closed = status == "closed"
    close_date = course.close_date
    return {
        "course_id": course.pk,
        "name": course.name or "",
        "status": status,
        "status_label": _status_label(status),
        "teachers": teachers,
        "teachers_display": ", ".join(teachers) if teachers else "—",
        "enrolled_at": enrolled_at,
        "enrolled_at_utc": utc_isoformat(enrolled_at) if enrolled_at else None,
        "close_date": close_date,
        "close_date_utc": utc_isoformat(close_date) if close_date else None,
        "is_closed": is_closed,
        "show_enrollment_span": is_closed,
        "show_student_count": show_student_count,
        "student_count": student_count if show_student_count else None,
        "is_parent": is_parent,
        "child_name": child_name,
        "child_id": child_id,
        "has_course_link": not is_parent,
    }


def dashboard_parent_groups_for_user(user):
    """
    Group ParentUserCourse links by Student for Active vs Closed course cards.

    Returns:
      {
        "has_access": bool,
        "children": [
          {
            "student_id": int,
            "child_name": str,
            "active_courses": [row, ...],
            "closed_courses": [row, ...],
          },
          ...
        ],
      }
    """
    empty = {"has_access": False, "children": []}
    if user is None or not getattr(user, "is_authenticated", False):
        return empty
    if getattr(user, "user_type", None) != "Parent":
        return empty

    links = list(
        ParentUserCourse.objects.filter(parent=user).select_related("course", "student")
    )
    if not links:
        return empty

    course_ids = [link.course_id for link in links]
    teachers_map = _teachers_by_course(course_ids)
    enroll_map = _enrollment_dates_for_pairs(
        (link.student_id, link.course_id) for link in links
    )

    by_student: dict[int, dict] = {}
    for link in links:
        course = link.course
        if (course.status or "") == "deleted":
            continue
        enrolled_at = enroll_map.get((link.student_id, link.course_id))
        row = _build_row(
            course=course,
            enrolled_at=enrolled_at,
            teachers=teachers_map.get(course.pk, []),
            show_student_count=False,
            student_count=None,
            is_parent=True,
            child_name=user_display_name(link.student),
            child_id=link.student_id,
        )
        group = by_student.get(link.student_id)
        if group is None:
            group = {
                "student_id": link.student_id,
                "child_name": user_display_name(link.student),
                "active_courses": [],
                "closed_courses": [],
            }
            by_student[link.student_id] = group
        if row["is_closed"]:
            group["closed_courses"].append(row)
        else:
            group["active_courses"].append(row)

    if not by_student:
        return empty

    children = []
    for student_id, group in by_student.items():
        group["active_courses"] = _sort_dashboard_courses(group["active_courses"])
        group["closed_courses"] = _sort_dashboard_courses(group["closed_courses"])
        children.append(group)
    children.sort(key=lambda g: ((g["child_name"] or "").casefold(), g["student_id"]))
    return {"has_access": True, "children": children}


def dashboard_courses_for_user(user):
    """Build sorted course rows for the dashboard My Courses card."""
    if user is None or not getattr(user, "is_authenticated", False):
        return []

    user_type = getattr(user, "user_type", None)
    show_student_count = user_type in ("Teacher", "IT_Support")

    if user_type == "Parent":
        # Parent dashboard uses dashboard_parent_groups_for_user instead.
        return []

    enrollments = list(
        UsersInCourse.objects.filter(user=user)
        .select_related("course")
        .order_by("creation_date")
    )
    # Students see closed courses only on the historic grades card.
    # Trashed courses are excluded for everyone until restored.
    enrollments = [
        e for e in enrollments if (e.course.status or "") != "deleted"
    ]
    if user_type == "Student":
        enrollments = [
            e for e in enrollments if (e.course.status or "") != "closed"
        ]
    course_ids = [e.course_id for e in enrollments]
    teachers_map = _teachers_by_course(course_ids)
    student_counts = (
        _student_counts_by_course(course_ids) if show_student_count else {}
    )

    rows = []
    for enrollment in enrollments:
        course = enrollment.course
        rows.append(
            _build_row(
                course=course,
                enrolled_at=enrollment.creation_date,
                teachers=teachers_map.get(course.pk, []),
                show_student_count=show_student_count,
                student_count=student_counts.get(course.pk, 0),
                is_parent=False,
            )
        )
    return _sort_dashboard_courses(rows)


def dashboard_student_closed_grades_for_user(user):
    """
    Closed-course rows for a Student's historic grades dashboard card.

    Returns [] when there are no closed enrollments (card should not render).
    """
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or getattr(user, "user_type", None) != "Student"
    ):
        return []

    enrollments = list(
        UsersInCourse.objects.filter(user=user, course__status="closed")
        .select_related("course")
        .order_by("creation_date")
    )
    if not enrollments:
        return []

    course_ids = [e.course_id for e in enrollments]
    teachers_map = _teachers_by_course(course_ids)
    rows = []
    for enrollment in enrollments:
        course = enrollment.course
        row = _build_row(
            course=course,
            enrolled_at=enrollment.creation_date,
            teachers=teachers_map.get(course.pk, []),
            show_student_count=False,
            student_count=None,
            is_parent=False,
        )
        # Historic grades only — no live course link.
        row["has_course_link"] = False
        rows.append(row)
    return _sort_dashboard_courses(rows)


def teacher_manual_grading_for_user(user):
    """Assessments in the teacher's courses that still require manual grading."""
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or getattr(user, "user_type", None) != "Teacher"
    ):
        return []

    from .assessment_grades import unfinished_manual_grading
    from .models import Assessment, Course

    course_rows = (
        Course.objects.filter(Q(owner=user) | Q(usersincourse__user=user))
        .distinct()
        .order_by("name", "id")
    )
    courses = {course.id: course for course in course_rows}
    if not courses:
        return []

    assessments = (
        Assessment.objects.filter(
            course_id__in=courses,
            parent_assessment__isnull=True,
            user__isnull=True,
        )
        .exclude(status="deleted")
        .order_by("course__name", "order", "id")
    )

    rows = []
    for assessment in assessments:
        pending = unfinished_manual_grading(assessment)
        if not pending:
            continue
        rows.append(
            {
                "course_id": assessment.course_id,
                "course_name": courses[assessment.course_id].name or "",
                "assessment_id": assessment.id,
                "assessment_name": assessment.name or f"Assessment {assessment.id}",
                "student_count": len({row["student_id"] for row in pending}),
            }
        )
    return rows


def teacher_active_retakes_for_user(user):
    """Active per-student retake grants grouped by assessment."""
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or getattr(user, "user_type", None) not in ("Teacher", "IT_Support")
    ):
        return []

    from .models import (
        Course,
        OpenStudentAssessmentOverwrite,
        UserProfile,
    )

    course_rows = (
        Course.objects.filter(Q(owner=user) | Q(usersincourse__user=user))
        .distinct()
        .order_by("name", "id")
    )
    courses = {course.id: course for course in course_rows}
    if not courses:
        return []

    grants = list(
        OpenStudentAssessmentOverwrite.objects.filter(
            a__course_id__in=courses,
            a__parent_assessment__isnull=True,
            a__user__isnull=True,
            status_open=True,
        )
        .values(
            "a_id",
            "a__name",
            "a__course_id",
            "u_id",
        )
        .order_by("a__course__name", "a__order", "a_id", "u_id")
    )
    student_ids = {grant["u_id"] for grant in grants if grant["u_id"]}
    students = {
        student.pk: student
        for student in UserProfile.objects.filter(pk__in=student_ids)
    }

    grouped = {}
    for grant in grants:
        assessment_id = grant["a_id"]
        course_id = grant["a__course_id"]
        row = grouped.setdefault(
            assessment_id,
            {
                "course_id": course_id,
                "course_name": courses[course_id].name or "",
                "assessment_id": assessment_id,
                "assessment_name": (
                    grant["a__name"] or f"Assessment {assessment_id}"
                ),
                "student_ids": set(),
                "student_names": [],
            },
        )
        student_id = grant["u_id"]
        if not student_id or student_id in row["student_ids"]:
            continue
        row["student_ids"].add(student_id)
        row["student_names"].append(
            user_roster_formal_name(students.get(student_id))
        )

    rows = []
    for row in grouped.values():
        row["student_names"].sort(key=str.casefold)
        row["student_count"] = len(row.pop("student_ids"))
        rows.append(row)
    rows.sort(
        key=lambda row: (
            row["course_name"].casefold(),
            row["assessment_name"].casefold(),
            row["assessment_id"],
        )
    )
    return rows


def teacher_grade_releases_for_user(user):
    """Assessments waiting for the teacher to release ready grades."""
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or getattr(user, "user_type", None) not in ("Teacher", "IT_Support")
    ):
        return []

    from .assessment_grades import assessment_needs_teacher_release
    from .models import Assessment, Course

    course_rows = (
        Course.objects.filter(Q(owner=user) | Q(usersincourse__user=user))
        .distinct()
        .order_by("name", "id")
    )
    courses = {course.id: course for course in course_rows}
    if not courses:
        return []

    assessments = (
        Assessment.objects.filter(
            course_id__in=courses,
            parent_assessment__isnull=True,
            user__isnull=True,
        )
        .exclude(status="deleted")
        .order_by("course__name", "order", "id")
    )
    rows = []
    for assessment in assessments:
        if not assessment_needs_teacher_release(assessment):
            continue
        rows.append(
            {
                "course_id": assessment.course_id,
                "course_name": courses[assessment.course_id].name or "",
                "assessment_id": assessment.id,
                "assessment_name": assessment.name or f"Assessment {assessment.id}",
            }
        )
    return rows


def teacher_focus_unlocks_for_user(user):
    """Currently focus-locked attempts in courses this teacher can manage."""
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or getattr(user, "user_type", None) not in ("Teacher", "IT_Support")
    ):
        return []

    from .models import Course, StudentAssessmentFocusLock
    from .student_attempts import course_template_assessment

    course_rows = (
        Course.objects.filter(Q(owner=user) | Q(usersincourse__user=user))
        .distinct()
        .order_by("name", "id")
    )
    courses = {course.id: course for course in course_rows}
    if not courses:
        return []

    locks = (
        StudentAssessmentFocusLock.objects.filter(
            attempt__course_id__in=courses,
            attempt__status="in_progress",
            unlocked_at__isnull=True,
        )
        .select_related(
            "attempt",
            "attempt__user",
            "attempt__assessment",
            "attempt__assessment__parent_assessment",
        )
        .order_by("locked_at", "id")
    )
    rows = []
    for focus_lock in locks:
        attempt = focus_lock.attempt
        assessment = course_template_assessment(attempt.assessment)
        if assessment is None or assessment.course_id not in courses:
            continue
        rows.append(
            {
                "lock_id": focus_lock.id,
                "locked_at": focus_lock.locked_at,
                "locked_at_utc": utc_isoformat(focus_lock.locked_at),
                "attempt_id": attempt.id,
                "student_id": attempt.user_id,
                "student_name": user_roster_formal_name(attempt.user),
                "course_id": assessment.course_id,
                "course_name": courses[assessment.course_id].name or "",
                "assessment_id": assessment.id,
                "assessment_name": (
                    assessment.name or f"Assessment {assessment.id}"
                ),
            }
        )
    return rows
