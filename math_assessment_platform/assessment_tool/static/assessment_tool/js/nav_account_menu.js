(function () {
  function closeAllDropdowns(exceptRoot) {
    document.querySelectorAll(".nav-dropdown, .nav-account-dropdown").forEach(function (root) {
      if (exceptRoot && root === exceptRoot) return;
      var trigger = root.querySelector(".nav-dropdown-trigger, .nav-account-trigger");
      var menu = root.querySelector(".nav-dropdown-menu, .nav-account-menu");
      if (!trigger || !menu) return;
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      if (root.classList.contains("nav-account-dropdown")) {
        syncAccountDots(root, false);
      }
    });
  }

  function syncAccountDots(root, menuOpen) {
    var triggerDot = root.querySelector(".nav-unread-dot--trigger");
    var itemDot = root.querySelector(".nav-unread-dot--item");
    var hasUnread = root.getAttribute("data-has-unread") === "true";
    if (!hasUnread) return;
    if (menuOpen) {
      if (triggerDot) triggerDot.classList.add("is-hidden");
      if (itemDot) itemDot.classList.remove("is-hidden");
    } else {
      if (triggerDot) triggerDot.classList.remove("is-hidden");
      if (itemDot) itemDot.classList.add("is-hidden");
    }
  }

  function initDropdown(root, triggerSelector, menuSelector) {
    var trigger = root.querySelector(triggerSelector);
    var menu = root.querySelector(menuSelector);
    if (!trigger || !menu) return;

    function setOpen(open) {
      if (open) {
        closeAllDropdowns(root);
        menu.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
        if (root.classList.contains("nav-account-dropdown")) {
          syncAccountDots(root, true);
        }
      } else {
        menu.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        if (root.classList.contains("nav-account-dropdown")) {
          syncAccountDots(root, false);
        }
      }
    }

    trigger.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(menu.hidden);
    });
  }

  function initNavToggle() {
    var nav = document.querySelector(".site-nav--admin");
    var toggle = document.getElementById("nav-toggle");
    var links = document.getElementById("site-nav-links");
    if (!nav || !toggle || !links) return;

    function setNavOpen(open) {
      nav.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      if (!open) closeAllDropdowns(null);
    }

    toggle.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      setNavOpen(!nav.classList.contains("is-open"));
    });

    document.addEventListener("click", function (event) {
      var insideDropdown = event.target.closest(
        ".nav-dropdown, .nav-account-dropdown"
      );
      if (!insideDropdown) {
        closeAllDropdowns(null);
      }
      if (!nav.contains(event.target)) {
        setNavOpen(false);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        setNavOpen(false);
        closeAllDropdowns(null);
      }
    });

    window.addEventListener("resize", function () {
      if (window.matchMedia("(min-width: 901px)").matches) {
        setNavOpen(false);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".nav-admin-dropdown").forEach(function (root) {
      initDropdown(root, ".nav-dropdown-trigger", ".nav-dropdown-menu");
    });
    document.querySelectorAll(".nav-account-dropdown").forEach(function (root) {
      initDropdown(root, ".nav-account-trigger", ".nav-account-menu");
    });
    initNavToggle();
  });
})();
