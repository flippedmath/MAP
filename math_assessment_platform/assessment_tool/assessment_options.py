"""
Course default + per-assessment option settings backed by
assessment_option_group / course_default_assessment_options / assessment_options.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import math
from pathlib import Path

from django.db import connection, transaction
from django.utils import timezone

# Group numbers (stable IDs; removed groups are deprecated in DB)
GROUP_STUDENT_VIEW = 2
GROUP_GRADE_AGGREGATION = 3
GROUP_RETAKE_SCORING = 4
GROUP_COUNT_UP = 6
GROUP_COUNT_DOWN = 7
GROUP_LOCK_FOCUS = 9
GROUP_SYNC_TESTS = 12
GROUP_CURVE = 14
GROUP_SCORE_RELEASE = 15

# Group 2
CHOICE_VIEW_SCORES_ONLY = 1
CHOICE_VIEW_FULL_REVIEW = 2

# Group 3 — maps onto Course.grade_aggregation_mode
CHOICE_EQUAL_WEIGHT = 2  # each assessment is a % of final grade
CHOICE_SUM_POINTS = 3  # accumulated points

# Group 4
CHOICE_RETAKE_HIGHEST = 1
CHOICE_RETAKE_LATEST = 2

# Group 6
CHOICE_COUNT_UP_OFF = 1
CHOICE_COUNT_UP_SHOW = 2

# Group 7
CHOICE_COUNTDOWN_OFF = 1
CHOICE_COUNTDOWN_END_TIME = 2
CHOICE_COUNTDOWN_TIME_LIMIT = 3

# Group 9
CHOICE_LOCK_ON = 1
CHOICE_LOCK_OFF = 2

# Group 12
CHOICE_SYNC_OFF = 1
CHOICE_SYNC_ON = 2

# Group 14
CHOICE_CURVE_OFF = 1
CHOICE_CURVE_ON = 2

# Group 15
CHOICE_RELEASE_AUTO = 1
CHOICE_RELEASE_TEACHER = 2

GROUP_LABELS = {
    GROUP_STUDENT_VIEW: "Student view of graded assessments",
    GROUP_GRADE_AGGREGATION: "Course total calculation",
    GROUP_RETAKE_SCORING: "Retake assessment scoring",
    GROUP_COUNT_UP: "Count-up timer",
    GROUP_COUNT_DOWN: "Count-down timer",
    GROUP_LOCK_FOCUS: "Lock on focus leave",
    GROUP_SYNC_TESTS: "Synchronize tests",
    GROUP_CURVE: "Curve",
    GROUP_SCORE_RELEASE: "Score release",
}

# Shown only on the course gear overlay — not per-assessment Settings.
COURSE_ONLY_OPTION_GROUPS = frozenset(
    {
        GROUP_GRADE_AGGREGATION,
        GROUP_CURVE,
    }
)

# Per-assessment Settings on the Grades page
ASSESSMENT_GRADES_OPTION_GROUPS = frozenset(
    {
        GROUP_STUDENT_VIEW,
        GROUP_RETAKE_SCORING,
        GROUP_SCORE_RELEASE,
    }
)

# Per-assessment gear on the Course Assessments page
ASSESSMENT_DELIVERY_OPTION_GROUPS = frozenset(
    {
        GROUP_COUNT_UP,
        GROUP_COUNT_DOWN,
        GROUP_LOCK_FOCUS,
        GROUP_SYNC_TESTS,
    }
)

ASSESSMENT_OPTION_SUBSETS = {
    "grades": ASSESSMENT_GRADES_OPTION_GROUPS,
    "delivery": ASSESSMENT_DELIVERY_OPTION_GROUPS,
}


def resolve_assessment_option_subset(subset) -> frozenset[int] | None:
    """
    Return allowed group nums for an assessment options panel, or None for all
    non-course-only groups (legacy).
    """
    if subset is None or subset == "":
        return None
    key = str(subset).strip().lower()
    if key not in ASSESSMENT_OPTION_SUBSETS:
        return None
    return ASSESSMENT_OPTION_SUBSETS[key]

# Documented defaults when a course has not yet saved a row for the group
DEFAULT_CHOICES = {
    GROUP_STUDENT_VIEW: CHOICE_VIEW_SCORES_ONLY,
    GROUP_GRADE_AGGREGATION: CHOICE_EQUAL_WEIGHT,
    GROUP_RETAKE_SCORING: CHOICE_RETAKE_HIGHEST,
    GROUP_COUNT_UP: CHOICE_COUNT_UP_OFF,
    GROUP_COUNT_DOWN: CHOICE_COUNTDOWN_OFF,
    GROUP_LOCK_FOCUS: CHOICE_LOCK_OFF,
    GROUP_SYNC_TESTS: CHOICE_SYNC_OFF,
    GROUP_CURVE: CHOICE_CURVE_OFF,
    GROUP_SCORE_RELEASE: CHOICE_RELEASE_AUTO,
}


def _models():
    from . import models as m

    return m


def sync_option_groups() -> int:
    """Apply sync SQL (upsert/deprecate) then ensure seed rows exist."""
    base = Path(__file__).resolve().parent / "sql"
    sync_path = base / "sync_assessment_option_group.sql"
    seed_path = base / "seed_assessment_option_group.sql"
    with connection.cursor() as cursor:
        if sync_path.is_file():
            cursor.execute(sync_path.read_text(encoding="utf-8"))
        elif seed_path.is_file():
            cursor.execute(seed_path.read_text(encoding="utf-8"))
    return _models().AssessmentOptionGroup.objects.filter(deprecated=False).count()


def ensure_option_group_seeded() -> int:
    """Keep option enum in sync with the revised catalog."""
    return sync_option_groups()


def list_option_groups(*, include_deprecated: bool = False) -> list[dict]:
    ensure_option_group_seeded()
    m = _models()
    qs = m.AssessmentOptionGroup.objects.all().order_by("group_num", "choice")
    if not include_deprecated:
        qs = qs.filter(deprecated=False)
    by_group: dict[int, list] = defaultdict(list)
    for row in qs:
        by_group[int(row.group_num)].append(
            {
                "choice": int(row.choice),
                "description": row.description,
                "deprecated": bool(row.deprecated),
            }
        )
    out = []
    for group_num in sorted(by_group.keys()):
        if not include_deprecated and group_num not in GROUP_LABELS:
            continue
        out.append(
            {
                "group_num": group_num,
                "label": GROUP_LABELS.get(group_num, f"Option group {group_num}"),
                "choices": by_group[group_num],
                "supports_time_limit": group_num == GROUP_COUNT_DOWN,
            }
        )
    return out


def course_default_options_payload(course) -> dict:
    m = _models()
    groups = list_option_groups()
    selected = {
        int(r.option_type_id): {
            "choice": int(r.choice),
            "default_setting": bool(r.default_setting),
        }
        for r in m.CourseDefaultAssessmentOptions.objects.filter(course=course)
        if int(r.option_type_id) in GROUP_LABELS
    }
    if GROUP_GRADE_AGGREGATION not in selected:
        mode = str(getattr(course, "grade_aggregation_mode", "") or "").strip().lower()
        selected[GROUP_GRADE_AGGREGATION] = {
            "choice": CHOICE_SUM_POINTS if mode == "sum_points" else CHOICE_EQUAL_WEIGHT,
            "default_setting": True,
        }
    for group in groups:
        gnum = int(group["group_num"])
        if gnum in selected:
            continue
        preferred = DEFAULT_CHOICES.get(gnum)
        choices = group.get("choices") or []
        choice_vals = {int(c["choice"]) for c in choices}
        if preferred is not None and preferred in choice_vals:
            pick = preferred
        elif choices:
            pick = int(choices[0]["choice"])
        else:
            continue
        selected[gnum] = {"choice": pick, "default_setting": True}
    return {
        "success": True,
        "scope": "course",
        "course_id": course.id,
        "groups": groups,
        "selected": selected,
        "grade_aggregation_mode": getattr(course, "grade_aggregation_mode", "equal_weight"),
        "default_time_limit_minutes": getattr(course, "default_time_limit_minutes", None),
    }


def assessment_options_payload(assessment, *, subset=None) -> dict:
    m = _models()
    allowed = resolve_assessment_option_subset(subset)
    # Course-scoped options stay on the course gear only.
    groups = []
    for g in list_option_groups():
        gnum = int(g["group_num"])
        if gnum in COURSE_ONLY_OPTION_GROUPS:
            continue
        if allowed is not None and gnum not in allowed:
            continue
        groups.append(g)
    selected = {
        int(r.option_type_id): {"choice": int(r.choice)}
        for r in m.AssessmentOptions.objects.filter(assessment=assessment)
        if int(r.option_type_id) in GROUP_LABELS
        and int(r.option_type_id) not in COURSE_ONLY_OPTION_GROUPS
        and (allowed is None or int(r.option_type_id) in allowed)
    }
    course_defaults = {}
    if assessment.course_id:
        course_defaults = {
            int(r.option_type_id): {
                "choice": int(r.choice),
                "default_setting": bool(r.default_setting),
            }
            for r in m.CourseDefaultAssessmentOptions.objects.filter(
                course_id=assessment.course_id
            )
            if int(r.option_type_id) in GROUP_LABELS
            and int(r.option_type_id) not in COURSE_ONLY_OPTION_GROUPS
            and (allowed is None or int(r.option_type_id) in allowed)
        }
    return {
        "success": True,
        "scope": "assessment",
        "subset": (
            str(subset).strip().lower()
            if subset and str(subset).strip().lower() in ASSESSMENT_OPTION_SUBSETS
            else None
        ),
        "assessment_id": assessment.id,
        "assessment_name": getattr(assessment, "name", "") or "",
        "groups": groups,
        "selected": selected,
        "course_defaults": course_defaults,
        "time_limit_minutes": getattr(assessment, "time_limit_minutes", None),
        "default_time_limit_minutes": (
            getattr(assessment.course, "default_time_limit_minutes", None)
            if assessment.course_id
            else None
        ),
    }


def _valid_choice(group_num: int, choice: int) -> bool:
    m = _models()
    return m.AssessmentOptionGroup.objects.filter(
        group_num=group_num, choice=choice, deprecated=False
    ).exists()


def save_course_default_options(
    course, selections: list[dict], *, default_time_limit_minutes=None
) -> dict:
    """
    selections: [{group_num|option_type_id, choice}, ...]
    Optional default_time_limit_minutes when countdown forcibly-end is selected.
    """
    m = _models()
    ensure_option_group_seeded()
    if not isinstance(selections, list):
        return {"success": False, "error": "selections must be a list."}

    with transaction.atomic():
        for item in selections:
            if not isinstance(item, dict):
                continue
            try:
                group_num = int(item.get("group_num", item.get("option_type_id")))
                choice = int(item.get("choice"))
            except (TypeError, ValueError):
                return {"success": False, "error": "Invalid group_num or choice."}
            if group_num not in GROUP_LABELS:
                continue
            if not _valid_choice(group_num, choice):
                return {
                    "success": False,
                    "error": f"Invalid option ({group_num}, {choice}).",
                }
            default_setting = True

            existing = m.CourseDefaultAssessmentOptions.objects.filter(
                course=course, option_type_id=group_num
            ).first()
            if existing:
                existing.choice = choice
                existing.default_setting = default_setting
                existing.save(update_fields=["choice", "default_setting"])
            else:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO course_default_assessment_options
                          (id, course_id, option_type_id, choice, default_setting)
                        VALUES (nextval('course_default_assessment_options_id_seq'), %s, %s, %s, %s)
                        """,
                        [course.id, group_num, choice, default_setting],
                    )

            if group_num == GROUP_GRADE_AGGREGATION:
                mode = (
                    "sum_points"
                    if choice == CHOICE_SUM_POINTS
                    else "equal_weight"
                )
                if hasattr(course, "grade_aggregation_mode"):
                    course.grade_aggregation_mode = mode
                    course.save(update_fields=["grade_aggregation_mode"])

            if group_num == GROUP_STUDENT_VIEW:
                from .assessment_grades import sync_assessment_release_mode_from_options

                # Sync assessments that inherit course default (no override for group 2)
                assessments = m.Assessment.objects.filter(
                    course=course,
                    parent_assessment__isnull=True,
                    user__isnull=True,
                ).exclude(status="deleted")
                overridden = set(
                    m.AssessmentOptions.objects.filter(
                        assessment__in=assessments,
                        option_type_id=GROUP_STUDENT_VIEW,
                    ).values_list("assessment_id", flat=True)
                )
                for assessment in assessments:
                    if assessment.id in overridden:
                        continue
                    sync_assessment_release_mode_from_options(assessment)

            if group_num == GROUP_SCORE_RELEASE:
                from .assessment_grades import sync_assessment_release_mode_from_options

                assessments = m.Assessment.objects.filter(
                    course=course,
                    parent_assessment__isnull=True,
                    user__isnull=True,
                ).exclude(status="deleted")
                overridden = set(
                    m.AssessmentOptions.objects.filter(
                        assessment__in=assessments,
                        option_type_id=GROUP_SCORE_RELEASE,
                    ).values_list("assessment_id", flat=True)
                )
                for assessment in assessments:
                    if assessment.id in overridden:
                        continue
                    sync_assessment_release_mode_from_options(assessment)

        if default_time_limit_minutes is not None and hasattr(
            course, "default_time_limit_minutes"
        ):
            try:
                mins = int(default_time_limit_minutes)
                if mins < 1:
                    mins = None
            except (TypeError, ValueError):
                mins = None
            course.default_time_limit_minutes = mins
            course.save(update_fields=["default_time_limit_minutes"])

    return course_default_options_payload(course)


def save_assessment_options(
    assessment, selections: list[dict], *, time_limit_minutes=None, subset=None
) -> dict:
    """
    selections: [{group_num|option_type_id, choice}, ...]
    Pass clear:true to remove an override (fall back to course default).
    subset: 'grades' | 'delivery' — only those groups are accepted from the panel.
    """
    m = _models()
    ensure_option_group_seeded()
    if not isinstance(selections, list):
        return {"success": False, "error": "selections must be a list."}
    allowed = resolve_assessment_option_subset(subset)

    with transaction.atomic():
        student_view_touched = False
        score_release_touched = False
        for item in selections:
            if not isinstance(item, dict):
                continue
            try:
                group_num = int(item.get("group_num", item.get("option_type_id")))
            except (TypeError, ValueError):
                return {"success": False, "error": "Invalid group_num."}
            if group_num not in GROUP_LABELS:
                continue
            if group_num in COURSE_ONLY_OPTION_GROUPS:
                # Course-only settings; ignore if sent from assessment overlay.
                continue
            if allowed is not None and group_num not in allowed:
                continue

            if group_num == GROUP_STUDENT_VIEW:
                student_view_touched = True
            if group_num == GROUP_SCORE_RELEASE:
                score_release_touched = True

            if item.get("clear") or item.get("choice") is None:
                m.AssessmentOptions.objects.filter(
                    assessment=assessment, option_type_id=group_num
                ).delete()
                continue

            try:
                choice = int(item.get("choice"))
            except (TypeError, ValueError):
                return {"success": False, "error": "Invalid choice."}
            if not _valid_choice(group_num, choice):
                return {
                    "success": False,
                    "error": f"Invalid option ({group_num}, {choice}).",
                }

            existing = m.AssessmentOptions.objects.filter(
                assessment=assessment, option_type_id=group_num
            ).first()
            if existing:
                existing.choice = choice
                existing.save(update_fields=["choice"])
            else:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO assessment_options
                          (id, assessment_id, option_type_id, choice)
                        VALUES (nextval('assessment_options_id_seq'), %s, %s, %s)
                        """,
                        [assessment.id, group_num, choice],
                    )

        # Only touch time_limit when this panel includes the countdown group.
        if (
            time_limit_minutes is not None
            and hasattr(assessment, "time_limit_minutes")
            and (allowed is None or GROUP_COUNT_DOWN in allowed)
        ):
            try:
                mins = int(time_limit_minutes)
                if mins < 1:
                    mins = None
            except (TypeError, ValueError):
                mins = None
            assessment.time_limit_minutes = mins
            assessment.save(update_fields=["time_limit_minutes"])

        if student_view_touched or score_release_touched:
            from .assessment_grades import sync_assessment_release_mode_from_options

            sync_assessment_release_mode_from_options(assessment)

    return assessment_options_payload(assessment, subset=subset)


def resolved_assessment_option(assessment, group_num: int) -> int | None:
    """Assessment override, else course default (if default_setting), else catalog default."""
    m = _models()
    row = m.AssessmentOptions.objects.filter(
        assessment=assessment, option_type_id=group_num
    ).first()
    if row:
        return int(row.choice)
    if assessment.course_id:
        crow = m.CourseDefaultAssessmentOptions.objects.filter(
            course_id=assessment.course_id, option_type_id=group_num
        ).first()
        if crow and crow.default_setting:
            return int(crow.choice)
    return DEFAULT_CHOICES.get(group_num)


def show_count_up_timer(assessment) -> bool:
    """True when students should see a live count-up timer while taking."""
    return resolved_assessment_option(assessment, GROUP_COUNT_UP) == CHOICE_COUNT_UP_SHOW


def select_counting_attempt(attempts: list, assessment) -> object | None:
    """
    From a list of attempts (typically one student + one series), pick the
    attempt that counts toward the grade per Retake assessment scoring
    (highest vs latest). Prefers submitted attempts; if none, returns None.

    Callers that have multi-series history should group by series first and
    call this once per series (see select_counting_attempts_by_series).
    """
    submitted = [
        a
        for a in (attempts or [])
        if (
            getattr(a, "status", None) == "submitted"
            or getattr(a, "auto_graded_at", None) is not None
        )
        and not getattr(a, "score_voided", False)
    ]
    if not submitted:
        return None

    choice = resolved_assessment_option(assessment, GROUP_RETAKE_SCORING)
    if choice == CHOICE_RETAKE_LATEST:
        def latest_key(a):
            return (
                a.submitted_at or a.auto_graded_at or a.creation_date or a.id,
                a.id,
            )

        return max(submitted, key=latest_key)

    def highest_key(a):
        # Curve bonus is applied after selection for display/final grades.
        # Comparing raw scores keeps "highest attempt" independent of curve.
        earned = a.earned_points
        max_pts = a.max_points
        if earned is None:
            ratio = -1.0
            earned_v = -1.0
        else:
            earned_v = float(earned)
            try:
                max_v = float(max_pts) if max_pts is not None else 0.0
            except (TypeError, ValueError):
                max_v = 0.0
            ratio = (earned_v / max_v) if max_v > 0 else earned_v
        stamp = a.submitted_at or a.auto_graded_at or a.creation_date
        return (ratio, earned_v, stamp, a.id)

    return max(submitted, key=highest_key)


def select_counting_attempts_by_series(attempts: list, assessment) -> list:
    """
    One counting attempt per retake_series for a student's attempts.
    Each series contributes separately to course grade totals.
    """
    by_series: dict[int, list] = {}
    for attempt in attempts or []:
        try:
            series = int(getattr(attempt, "retake_series", 1) or 1)
        except (TypeError, ValueError):
            series = 1
        if series < 1:
            series = 1
        by_series.setdefault(series, []).append(attempt)
    selected = []
    for series in sorted(by_series.keys()):
        chosen = select_counting_attempt(by_series[series], assessment)
        if chosen is not None:
            selected.append(chosen)
    return selected


def score_release_requires_teacher(assessment) -> bool:
    """True when grades stay hidden until a teacher explicitly releases them."""
    return (
        resolved_assessment_option(assessment, GROUP_SCORE_RELEASE)
        == CHOICE_RELEASE_TEACHER
    )


def student_may_view_submissions(assessment) -> bool:
    """True when full-review student-view option is active for this assessment."""
    return (
        resolved_assessment_option(assessment, GROUP_STUDENT_VIEW)
        == CHOICE_VIEW_FULL_REVIEW
    )


def resolved_time_limit_minutes(assessment) -> int | None:
    choice = resolved_assessment_option(assessment, GROUP_COUNT_DOWN)
    if choice != CHOICE_COUNTDOWN_TIME_LIMIT:
        return None
    mins = getattr(assessment, "time_limit_minutes", None)
    if mins is not None:
        try:
            mins = int(mins)
            return mins if mins >= 1 else None
        except (TypeError, ValueError):
            return None
    if assessment.course_id:
        c_mins = getattr(assessment.course, "default_time_limit_minutes", None)
        try:
            c_mins = int(c_mins) if c_mins is not None else None
            return c_mins if c_mins and c_mins >= 1 else None
        except (TypeError, ValueError):
            return None
    return None


def countdown_timer_payload(assessment, attempt, *, window_end=None, now=None) -> dict:
    """
    Resolve the visible countdown and client-side forced-submit deadline.

    Assessment overrides take precedence through resolved_assessment_option().
    The global assessment window still closes a take even when the countdown
    display is disabled.
    """
    now = now or timezone.now()
    choice = resolved_assessment_option(assessment, GROUP_COUNT_DOWN)

    def aware(value):
        if value is None:
            return None
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value

    global_end = aware(window_end)
    time_limit_end = None
    if choice == CHOICE_COUNTDOWN_TIME_LIMIT and attempt is not None:
        started_at = aware(getattr(attempt, "started_at", None))
        minutes = resolved_time_limit_minutes(assessment)
        if started_at is not None and minutes is not None:
            time_limit_end = started_at + timedelta(minutes=minutes)

    force_candidates = [
        (global_end, "assessment_end"),
        (time_limit_end, "time_limit"),
    ]
    force_candidates = [(end, reason) for end, reason in force_candidates if end]
    force_end = None
    force_reason = None
    if force_candidates:
        force_end, force_reason = min(force_candidates, key=lambda item: item[0])

    visible_end = None
    if choice == CHOICE_COUNTDOWN_END_TIME:
        visible_end = global_end
    elif choice == CHOICE_COUNTDOWN_TIME_LIMIT:
        # Show the time until the take will actually end, including an earlier
        # global assessment-window close.
        visible_end = force_end

    def remaining_seconds(end):
        return max(0, int((end - now).total_seconds())) if end is not None else None

    return {
        "countdown_choice": choice,
        "show_countdown_timer": visible_end is not None,
        "countdown_ends_at": visible_end.isoformat() if visible_end else None,
        "countdown_remaining_seconds": remaining_seconds(visible_end),
        "force_submit_at": force_end.isoformat() if force_end else None,
        "force_submit_remaining_seconds": remaining_seconds(force_end),
        "force_submit_reason": force_reason,
    }


def resolved_course_option(course, group_num: int) -> int | None:
    """Course-level option choice, else catalog default."""
    m = _models()
    if course is None:
        return DEFAULT_CHOICES.get(group_num)
    course_id = course.id if hasattr(course, "id") else course
    crow = m.CourseDefaultAssessmentOptions.objects.filter(
        course_id=course_id,
        option_type_id=group_num,
    ).first()
    if crow:
        return int(crow.choice)
    return DEFAULT_CHOICES.get(group_num)


def curve_allowed_for_course(course) -> bool:
    return resolved_course_option(course, GROUP_CURVE) == CHOICE_CURVE_ON


def curve_allowed_for_assessment(assessment) -> bool:
    """Curve is course-scoped; per-assessment overrides are ignored."""
    return curve_allowed_for_course(getattr(assessment, "course", None) or assessment.course_id)


def any_assessment_allows_curve(course) -> bool:
    return curve_allowed_for_course(course)
