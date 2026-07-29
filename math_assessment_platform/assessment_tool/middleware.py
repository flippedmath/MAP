from django.contrib.auth import logout
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import Resolver404, resolve, reverse

from .view_mode import VIEW_ONLY_MESSAGE, should_block_content_mutation, view_only_json_response


class OneSessionPerUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            ###############
            # force user to authenticate email before navigating elsewhere
            ###############
            # Check if account is unactivated
            if request.user.unactivated_account:
                # Define paths that are ALLOWED (use the actual URL paths)
                # Adjust these strings to match your actual URLs in urls.py
                allowed_paths = ['/verify/', '/logout/', '/logout', '/verify']
                
                # If the current path is NOT in our allowed list, force redirect
                if request.path_info not in allowed_paths:
                    return redirect('verify_email')

            ###############
            # single sign on logic follows
            ###############
            stored_session_key = request.user.last_session_key
            
            # If a session exists in DB and doesn't match current browser session
            if stored_session_key and request.session.session_key != stored_session_key:
                # 1. Add the message FIRST while the session is still active
                if hasattr(request, '_messages'):
                    messages.error(request, "You have been logged out because someone else logged in from another device.")

                if getattr(request.user, "user_type", None) == "Student":
                    from .assessment_focus_lock import lock_attempt_for_focus
                    from .models import StudentAssessmentAttempt

                    active_attempt = (
                        StudentAssessmentAttempt.objects.filter(
                            user=request.user,
                            status=StudentAssessmentAttempt.STATUS_IN_PROGRESS,
                        )
                        .order_by("-started_at", "-id")
                        .first()
                    )
                    if active_attempt is not None:
                        lock_attempt_for_focus(active_attempt)
                
                # 2. Log out (this clears the current session)
                logout(request)
                
                # 3. Redirect
                return redirect('login')

        return self.get_response(request)


class ActiveAssessmentRedirectMiddleware:
    """
    Keep students on their authoritative in-progress attempt.

    Internal navigation redirects without locking. Logout is allowed but locks
    an enabled attempt before the session is cleared.
    """

    TAKE_ROUTE_NAMES = {
        "student_assessment_take",
        "student_assessment_start",
        "student_assessment_take_status",
        "student_assessment_autosave",
        "student_assessment_submit",
        "student_assessment_focus_lock",
        "student_assessment_submit_locked",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is None
            or not user.is_authenticated
            or getattr(user, "user_type", None) != "Student"
            or request.path.startswith(("/static/", "/media/"))
        ):
            return self.get_response(request)

        try:
            match = resolve(request.path_info)
        except Resolver404:
            match = None

        from .models import StudentAssessmentAttempt, UserProfile

        attempt = (
            StudentAssessmentAttempt.objects.filter(
                user=user,
                status=StudentAssessmentAttempt.STATUS_IN_PROGRESS,
            )
            .select_related("assessment", "assessment__parent_assessment")
            .order_by("-started_at", "-id")
            .first()
        )
        if attempt is None:
            if bool(getattr(user, "ongoing_assessment", False)):
                UserProfile.objects.filter(pk=user.pk).update(
                    ongoing_assessment=False
                )
                user.ongoing_assessment = False
            return self.get_response(request)

        if not bool(getattr(user, "ongoing_assessment", False)):
            UserProfile.objects.filter(pk=user.pk).update(ongoing_assessment=True)
            user.ongoing_assessment = True

        route_name = match.url_name if match else ""
        if route_name == "logout":
            from .assessment_focus_lock import lock_attempt_for_focus

            lock_attempt_for_focus(attempt)
            return self.get_response(request)

        from .student_attempts import course_template_assessment

        template = course_template_assessment(attempt.assessment)
        if template is None:
            return self.get_response(request)

        requested_assessment_id = (
            match.kwargs.get("assessment_id") if match else None
        )
        requested_course_id = match.kwargs.get("course_id") if match else None
        on_active_take_route = (
            route_name in self.TAKE_ROUTE_NAMES
            and int(requested_assessment_id or 0) == int(template.id)
            and int(requested_course_id or 0) == int(template.course_id)
        )
        if on_active_take_route:
            return self.get_response(request)

        return redirect(
            reverse(
                "student_assessment_take",
                kwargs={
                    "course_id": template.course_id,
                    "assessment_id": template.id,
                },
            )
        )


class ContentViewOnlyMiddleware:
    """Block course/assessment/problem/CQD/AQG saves while explorer view-only is set."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if should_block_content_mutation(request):
            wants_json = (
                "application/json" in (request.headers.get("Accept") or "")
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or (request.content_type or "").startswith("application/json")
                or request.path.startswith("/api/")
                or "/api/" in request.path
                or request.path.endswith("-ajax/")
                or "ajax" in request.path
            )
            if wants_json:
                return view_only_json_response()
            messages.error(request, VIEW_ONLY_MESSAGE)
            referer = request.META.get("HTTP_REFERER")
            if referer:
                return redirect(referer)
            return redirect("dashboard")
        return self.get_response(request)