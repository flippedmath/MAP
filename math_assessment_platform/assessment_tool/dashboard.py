"""Dashboard context helpers for course lists and related display data."""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Q

from .models import ParentUserCourse, UsersInCourse
from .notifications import utc_isoformat


def user_display_name(user) -> str:
    if user is None:
        return ""
    display = (getattr(user, "user_display_name", None) or "").strip()
    if display:
        return display
    first = (getattr(user, "user_first_name", None) or "").strip()
    last = (getattr(user, "user_last_name", None) or "").strip()
    full = f"{first} {last}".strip()
    if full:
        return full
    return getattr(user, "username", "") or ""


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
            user__user_type="Teacher",
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


def dashboard_courses_for_user(user):
    """Build sorted course rows for the dashboard My Courses card."""
    if user is None or not getattr(user, "is_authenticated", False):
        return []

    user_type = getattr(user, "user_type", None)
    show_student_count = user_type in ("Teacher", "IT_Support")

    if user_type == "Parent":
        links = list(
            ParentUserCourse.objects.filter(parent=user).select_related(
                "course", "student"
            )
        )
        course_ids = [link.course_id for link in links]
        teachers_map = _teachers_by_course(course_ids)
        enroll_map = _enrollment_dates_for_pairs(
            (link.student_id, link.course_id) for link in links
        )
        rows = []
        for link in links:
            course = link.course
            enrolled_at = enroll_map.get((link.student_id, link.course_id))
            rows.append(
                _build_row(
                    course=course,
                    enrolled_at=enrolled_at,
                    teachers=teachers_map.get(course.pk, []),
                    show_student_count=False,
                    student_count=None,
                    is_parent=True,
                    child_name=user_display_name(link.student),
                    child_id=link.student_id,
                )
            )
        return _sort_dashboard_courses(rows)

    enrollments = list(
        UsersInCourse.objects.filter(user=user)
        .select_related("course")
        .order_by("creation_date")
    )
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
