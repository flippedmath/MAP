"""
Printable assessment + answer-key page (browser Print → Save as PDF).

Builds one frozen instance (synchronized form when available, otherwise a fresh
assemble_practice_test result), generates an ephemeral match key, and renders
a compact print-ready HTML document.
"""

from __future__ import annotations

import json
import re
import secrets
import string
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

MATCH_KEY_ALPHABET = string.ascii_uppercase + string.digits
# Avoid ambiguous characters in match keys printed on paper.
MATCH_KEY_ALPHABET = "".join(ch for ch in MATCH_KEY_ALPHABET if ch not in "O01IL")


def generate_match_key() -> str:
    """Short human-readable code shared by the test and answer-key sections."""
    left = "".join(secrets.choice(MATCH_KEY_ALPHABET) for _ in range(4))
    right = "".join(secrets.choice(MATCH_KEY_ALPHABET) for _ in range(2))
    return f"{left}-{right}"


def _parse_space_allocation(raw) -> float | None:
    """Return a relative work-space height multiplier, or None for default."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        data = json.loads(text) if text[:1] in "{[" else text
    except (TypeError, ValueError, json.JSONDecodeError):
        data = text
    if isinstance(data, dict):
        for key in ("lines", "height", "space", "rem", "value"):
            if key in data:
                try:
                    return max(0.0, float(data[key]))
                except (TypeError, ValueError):
                    pass
        return None
    try:
        return max(0.0, float(data))
    except (TypeError, ValueError):
        return None


def _space_map_for_problem_ids(problem_ids: list[int]) -> dict[int, float | None]:
    from . import models as m

    if not problem_ids:
        return {}
    out: dict[int, float | None] = {}
    for row in m.QuestionBlock.objects.filter(problem_id__in=problem_ids).values(
        "problem_id", "space_allocation"
    ):
        out[int(row["problem_id"])] = _parse_space_allocation(row.get("space_allocation"))
    return out


_MEDIA_ARCHETYPES = frozenset(
    {"graph", "graphBetweenPoints", "slopeFieldGraph", "canvas"}
)
_IMG_RE = re.compile(r"<img\b", re.IGNORECASE)
_TABLE_RE = re.compile(
    r"<table\b|ql-workspace-nested-table|ql-has-nested-table",
    re.IGNORECASE,
)
_LINKED_TOKEN_RE = re.compile(r"^<([^<>]+)>$")


def _archetype(field_or_seg: dict) -> str:
    return re.sub(
        r"\d+$",
        "",
        str(field_or_seg.get("archetype") or field_or_seg.get("token") or ""),
    ).strip()


def _problem_has_media(body_html: str, loaded_segments: list) -> bool:
    if body_html and _IMG_RE.search(body_html):
        return True
    for seg in loaded_segments or []:
        if not isinstance(seg, dict):
            continue
        if _archetype(seg) in _MEDIA_ARCHETYPES:
            return True
    return False


def _problem_needs_full_width(body_html: str, loaded_segments: list) -> bool:
    """
    Full-width (not 2-col) when the problem has graphs/images or Quill tables.
    Tables clip badly when squeezed into a half-page column.
    """
    if _problem_has_media(body_html, loaded_segments):
        return True
    return bool(body_html and _TABLE_RE.search(body_html))


def _segment_answer_text(seg: dict | None) -> str:
    if not isinstance(seg, dict):
        return ""
    latex = str(seg.get("latex_output") or "").strip()
    evaluated = seg.get("evaluated_output")
    if evaluated is None or evaluated == "":
        evaluated = seg.get("simulated_value")
    evaluated_s = "" if evaluated is None else str(evaluated).strip()
    if evaluated_s.lstrip().startswith("{") and '"archetype"' in evaluated_s:
        evaluated_s = ""
    if latex.startswith("[Invalid") or latex.startswith("⚠️"):
        latex = ""
    if evaluated_s.startswith("[Invalid") or evaluated_s.startswith("⚠️"):
        evaluated_s = ""
    # Prefer latex when it is real math, not the generic graph stub.
    if latex and latex not in ("[Graph Component]", "???"):
        return latex
    return evaluated_s or latex


def _answers_or_dne_fallback_text(field: dict, segs: dict) -> str:
    """
    When answersOrDne evaluation failed (common with some linked formulas),
    rebuild a printable key from linked answer tokens / DNE flag.
    """
    inputs = field.get("inputs") if isinstance(field.get("inputs"), dict) else {}
    if inputs.get("correct_is_dne") is True:
        return "DNE"
    raw_answers = inputs.get("answers") or []
    if isinstance(raw_answers, str):
        try:
            raw_answers = json.loads(raw_answers)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_answers = [raw_answers]
    texts = []
    for item in raw_answers or []:
        tok = str(item or "").strip()
        match = _LINKED_TOKEN_RE.match(tok)
        if match:
            tok = match.group(1).strip()
        if not tok:
            continue
        body = _segment_answer_text(segs.get(tok))
        if body:
            texts.append(body)
    return "\n".join(texts)


def _answer_summary_lines(answer_fields: list, loaded_segments: list) -> list[dict[str, str]]:
    """
    Compact per-field answer lines for the numbered answer key.
    Resolves MC option content (not internal opt_N ids) and expands embedded
    ``<formulaN>`` / ``<randIntN>`` tags using frozen segment values.
    """
    from .assessment_grades import _resolve_angle_tokens, _segment_display_map
    from .util import (
        _display_part_plaintext,
        _mc_option_display_part,
        _segments_by_sequence_token,
    )

    segs = _segments_by_sequence_token(loaded_segments or [])
    display_map = _segment_display_map(loaded_segments or [])

    def _expand(text: str) -> str:
        return _resolve_angle_tokens(str(text or ""), display_map).strip()

    lines: list[dict[str, str]] = []
    for field in answer_fields or []:
        if not isinstance(field, dict):
            continue
        arch = _archetype(field)
        if arch in ("graph", "graphBetweenPoints", "slopeFieldGraph"):
            continue
        if arch in ("longAnswer", "canvas"):
            lines.append({"text": "(manual)", "kind": "manual", "is_latex": "0"})
            continue
        if arch == "multipleChoiceAnswer":
            inputs = field.get("inputs") if isinstance(field.get("inputs"), dict) else {}
            options = inputs.get("options") if isinstance(inputs.get("options"), list) else []
            texts = []
            correct_ids = []
            for opt in options:
                if not isinstance(opt, dict) or not opt.get("is_correct"):
                    continue
                opt_id = str(opt.get("id") or "").strip()
                if opt_id:
                    correct_ids.append(opt_id)
                part = _mc_option_display_part(opt, segs)
                body = _display_part_plaintext(part) if part else ""
                if not body:
                    body = str(
                        opt.get("content_resolved") or opt.get("content") or ""
                    ).strip()
                body = _expand(body)
                if body:
                    texts.append(body)
            # Field-level evaluated_output is often already token-resolved for MC.
            if not texts:
                field_eval = _expand(
                    str(field.get("evaluated_output") or field.get("latex_output") or "")
                )
                if field_eval and not field_eval.startswith("[Invalid"):
                    texts.append(field_eval)
            text = "; ".join(texts) if texts else "(correct option)"
            lines.append(
                {
                    "text": text,
                    "kind": "mc",
                    "is_latex": "0",
                    "correct_option_ids": ",".join(correct_ids),
                }
            )
            continue

        latex = str(field.get("latex_output") or "").strip()
        evaluated = field.get("evaluated_output")
        if evaluated is None or evaluated == "":
            evaluated = field.get("simulated_value")
        evaluated_s = "" if evaluated is None else str(evaluated).strip()
        if evaluated_s.lstrip().startswith("{") and '"archetype"' in evaluated_s:
            evaluated_s = ""
        text = latex or evaluated_s
        if (
            arch == "answersOrDne"
            and (not text or text.startswith("[Invalid") or text.startswith("⚠️"))
        ):
            text = _answers_or_dne_fallback_text(field, segs)
        text = _expand(text)
        if not text:
            continue
        if text.startswith("[Invalid") or text.startswith("⚠️"):
            continue
        lines.append(
            {
                "text": text,
                "kind": "value",
                "is_latex": "1" if (latex and latex != evaluated_s) or "\\" in text else "0",
            }
        )
    return lines


def _serialize_problem_common(
    *,
    problem_id,
    slot_index,
    section_name,
    title,
    body_html,
    loaded,
    answer_fields,
    all_entities,
    work_space,
) -> dict:
    summary = _answer_summary_lines(answer_fields, loaded)
    return {
        "problem_id": problem_id,
        "slot_index": slot_index,
        "section_name": section_name,
        "title": title,
        "body_html": body_html,
        "loaded_segments": loaded,
        "answer_fields": answer_fields,
        "all_entities": all_entities or [],
        "work_space": work_space,
        "has_media": _problem_has_media(body_html or "", loaded),
        "full_width": _problem_needs_full_width(body_html or "", loaded),
        "answer_summary": summary,
    }


def _serialize_assembled_problem(instance: dict, space_by_pid: dict[int, float | None]) -> dict:
    from .student_attempts import _freeze_instance

    answer_key, _render_payload, _client_fields, body_html = _freeze_instance(instance)
    answer_fields = answer_key.get("answer_fields") or []
    loaded = answer_key.get("loaded_segments") or []
    pid = instance.get("problem_id")
    try:
        pid_int = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        pid_int = None
    return _serialize_problem_common(
        problem_id=pid,
        slot_index=instance.get("slot_index"),
        section_name=instance.get("section_name"),
        title=instance.get("title"),
        body_html=body_html,
        loaded=loaded,
        answer_fields=answer_fields,
        all_entities=answer_key.get("all_entities") or [],
        work_space=space_by_pid.get(pid_int) if pid_int is not None else None,
    )


def _serialize_sync_problem(row, space_by_pid: dict[int, float | None]) -> dict:
    answer_key = row.answer_key if isinstance(row.answer_key, dict) else {}
    answer_fields = answer_key.get("answer_fields") or row.answer_fields or []
    loaded = answer_key.get("loaded_segments") or []
    if not loaded:
        loaded = (row.render_payload or {}).get("loaded_segments") or []
    src = row.source_problem_id
    try:
        src_int = int(src) if src is not None else None
    except (TypeError, ValueError):
        src_int = None
    return _serialize_problem_common(
        problem_id=src,
        slot_index=row.slot_index,
        section_name=row.section_name,
        title=row.title,
        body_html=row.body_html or "",
        loaded=loaded,
        answer_fields=answer_fields,
        all_entities=answer_key.get("all_entities") or [],
        work_space=space_by_pid.get(src_int) if src_int is not None else None,
    )


def build_print_payload(assessment, *, actor_user=None, allow_status_mutation=True) -> dict:
    """
    Return problems + metadata for the print page.

    Prefers the current synchronized form when Synchronize tests is on;
    otherwise assembles a fresh practice-test instance (auto-continues past
    draft / zero-set warnings).
    """
    from .assessment_sync import current_synchronized_form, synchronized_tests_enabled
    from . import models as m
    from .util import assemble_practice_test

    warnings: list[str] = []
    source = "assembled"
    problems: list[dict] = []

    if synchronized_tests_enabled(assessment):
        # Class-wide printouts use attempt ordinal 1 (primary sitting).
        form = current_synchronized_form(assessment, 1)
        if form is not None:
            rows = list(
                m.AssessmentSynchronizedProblem.objects.filter(synchronized_form=form)
                .order_by("slot_index", "id")
            )
            if rows:
                pids = [
                    int(r.source_problem_id)
                    for r in rows
                    if r.source_problem_id is not None
                ]
                space_by_pid = _space_map_for_problem_ids(pids)
                problems = [_serialize_sync_problem(r, space_by_pid) for r in rows]
                source = "synchronized"
            else:
                warnings.append(
                    "Synchronize tests is on, but the current form has no problems yet. "
                    "A fresh instance was generated instead."
                )
        else:
            warnings.append(
                "Synchronize tests is on, but no current synchronized form exists yet. "
                "A fresh instance was generated instead."
            )

    if not problems:
        assembled = assemble_practice_test(
            assessment,
            actor_user=actor_user,
            allow_status_mutation=allow_status_mutation,
        )
        raw_problems = assembled.get("problems") or []
        skipped = assembled.get("skipped_drafts") or []
        zero_sets = assembled.get("zero_count_sets") or []
        omitted = assembled.get("omitted_render_failures") or []
        if skipped:
            warnings.append(
                f"{len(skipped)} draft problem(s) were skipped (incomplete status)."
            )
        if zero_sets:
            warnings.append(
                f"{len(zero_sets)} problem set(s) with suggested count 0 were omitted."
            )
        if omitted:
            warnings.append(
                f"{len(omitted)} problem(s) could not be rendered and were omitted."
            )
        pids = []
        for inst in raw_problems:
            try:
                pids.append(int(inst.get("problem_id")))
            except (TypeError, ValueError):
                pass
        space_by_pid = _space_map_for_problem_ids(pids)
        problems = [_serialize_assembled_problem(inst, space_by_pid) for inst in raw_problems]
        source = "assembled"

    match_key = generate_match_key()
    return {
        "match_key": match_key,
        "source": source,
        "warnings": warnings,
        "problems": problems,
        "problem_count": len(problems),
    }


@login_required
def assessment_print_view(request, course_id, assessment_id):
    """Teacher print-ready assessment + answer key (browser Print → PDF)."""
    from .credits import assert_can_print
    from .views import (
        _user_can_open_assessment_setup,
        assessment_course_url_id,
        get_scoped_assessment,
    )
    from .view_mode import is_content_view_only

    assessment = get_scoped_assessment(
        assessment_id,
        course_id,
        select_related=("branch_location", "course"),
    )
    course = assessment.course
    if not _user_can_open_assessment_setup(request.user, course, assessment):
        messages.error(request, "You do not have access to print this assessment.")
        if course is None:
            return redirect("file_explorer")
        return redirect("assessment_view", course_id=course.id)

    if not assert_can_print(request.user):
        messages.error(
            request,
            "Printing assessments requires an unlocked teacher account. "
            "Buy enough credits to unlock, then try again.",
        )
        if course is None:
            return redirect("account_settings")
        return redirect("assessment_view", course_id=course.id)

    payload = build_print_payload(
        assessment,
        actor_user=request.user,
        allow_status_mutation=not is_content_view_only(request),
    )

    user_type = getattr(request.user, "user_type", "Student")
    back_url = (
        reverse("assessment_view", args=[course.id])
        if course is not None
        else reverse("file_explorer")
    )

    return render(
        request,
        "assessment_tool/assessment_print.html",
        {
            "course": course,
            "course_url_id": assessment_course_url_id(assessment),
            "assessment": assessment,
            "user_type": user_type if user_type == "IT_Support" else "Teacher",
            "load_problem_workspace": True,
            "match_key": payload["match_key"],
            "print_source": payload["source"],
            "print_warnings": payload["warnings"],
            "print_problems": payload["problems"],
            "problem_count": payload["problem_count"],
            "back_url": back_url,
        },
    )
