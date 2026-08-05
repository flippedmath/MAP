(function () {
  var root = document.getElementById("teacher-focus-lock-nav");
  if (!root) return;

  var pollUrl = root.getAttribute("data-live-url");
  if (!pollUrl) return;

  var currentCourseId = root.getAttribute("data-course-id") || "";
  var activeTab = root.getAttribute("data-active-tab") || "";
  var onGradesOverview = root.getAttribute("data-on-grades-overview") === "true";
  var pollMs = 8000;

  function syncTriggerDots() {
    document.querySelectorAll(".nav-account-dropdown").forEach(function (dropdown) {
      var hasLocks = dropdown.getAttribute("data-has-focus-locks") === "true";
      var hasUnread = dropdown.getAttribute("data-has-unread") === "true";
      var menu = dropdown.querySelector(".nav-account-menu");
      var menuOpen = menu && !menu.hidden;
      var triggerDot = dropdown.querySelector(".nav-focus-lock-dot--trigger");
      if (!triggerDot) return;
      if (!hasLocks) {
        triggerDot.classList.add("is-hidden");
        return;
      }
      // Keep the account trigger badge visible while locks exist (even if menu open).
      triggerDot.classList.toggle("is-hidden", false);
      // Unread dots keep their own behavior; focus-lock badge is independent.
      void hasUnread;
      void menuOpen;
    });
  }

  function renderAccountItems(courses) {
    var rows = courses || [];
    document.querySelectorAll(".nav-account-dropdown").forEach(function (dropdown) {
      dropdown.setAttribute("data-has-focus-locks", rows.length ? "true" : "false");
      var host = dropdown.querySelector("[data-focus-lock-menu-host]");
      if (!host) return;
      host.replaceChildren();
      rows.forEach(function (course) {
        var link = document.createElement("a");
        link.className = "nav-account-menu-item nav-focus-lock-menu-item";
        link.setAttribute("role", "menuitem");
        link.href = course.manage_url || "#";
        var label = document.createElement("span");
        var count = Number(course.count) || 0;
        var name = course.course_name || ("Course " + course.course_id);
        label.textContent =
          count === 1
            ? "1 student locked — " + name
            : count + " students locked — " + name;
        var badge = document.createElement("span");
        badge.className = "nav-focus-lock-dot nav-focus-lock-dot--item";
        badge.setAttribute("aria-hidden", "true");
        link.append(label, badge);
        host.appendChild(link);
      });
      var divider = dropdown.querySelector("[data-focus-lock-menu-divider]");
      if (divider) divider.hidden = !rows.length;
    });
    syncTriggerDots();
  }

  function renderSidebarBadge(courses) {
    var gradesLink = document.querySelector(
      '.course-sidebar .nav-item[data-sidebar-grades="true"]'
    );
    if (!gradesLink) return;
    var badge = gradesLink.querySelector("[data-grades-lock-badge]");
    if (!badge) return;
    if (activeTab === "grades") {
      badge.hidden = true;
      return;
    }
    var courseId = Number(currentCourseId);
    var match = (courses || []).find(function (row) {
      return Number(row.course_id) === courseId;
    });
    if (!match || !match.count) {
      badge.hidden = true;
      badge.textContent = "";
      return;
    }
    badge.hidden = false;
    badge.textContent = String(match.count);
    badge.setAttribute(
      "aria-label",
      match.count === 1
        ? "1 student awaiting unlock"
        : match.count + " students awaiting unlock"
    );
  }

  function renderGradesOverviewBadges(courses) {
    if (!onGradesOverview || !currentCourseId) return;
    var courseId = Number(currentCourseId);
    var match = (courses || []).find(function (row) {
      return Number(row.course_id) === courseId;
    });
    var lockedIds = {};
    if (match && Array.isArray(match.assessment_ids)) {
      match.assessment_ids.forEach(function (id) {
        lockedIds[String(id)] = true;
      });
    }
    document.querySelectorAll("[data-view-student-assessments]").forEach(function (link) {
      var assessmentId = link.getAttribute("data-assessment-id");
      var badge = link.querySelector("[data-view-assessments-lock-badge]");
      if (!badge) return;
      var locked = !!(assessmentId && lockedIds[String(assessmentId)]);
      badge.hidden = !locked;
    });
    document.querySelectorAll("[data-grades-overview-row]").forEach(function (row) {
      var assessmentId = row.getAttribute("data-assessment-id");
      var locked = !!(assessmentId && lockedIds[String(assessmentId)]);
      row.classList.toggle("has-focus-lock-alert", locked);
      var nameBadge = row.querySelector("[data-assessment-name-lock-badge]");
      if (nameBadge) nameBadge.hidden = !locked;
    });
  }

  function applyPayload(data) {
    var courses = (data && data.focus_unlock_courses) || [];
    renderAccountItems(courses);
    renderSidebarBadge(courses);
    renderGradesOverviewBadges(courses);
  }

  async function poll() {
    try {
      var response = await fetch(pollUrl, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!response.ok) return;
      var data = await response.json();
      if (!data || data.success !== true) return;
      applyPayload(data);
    } catch (_) {
      // Ignore transient poll failures.
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    poll();
    window.setInterval(poll, pollMs);
  });
})();
