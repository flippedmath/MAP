(function () {
  function initAccountMenu(root) {
    var trigger = root.querySelector(".nav-account-trigger");
    var menu = root.querySelector(".nav-account-menu");
    var triggerDot = root.querySelector(".nav-unread-dot--trigger");
    var itemDot = root.querySelector(".nav-unread-dot--item");
    if (!trigger || !menu) {
      return;
    }

    var hasUnread = root.getAttribute("data-has-unread") === "true";

    function setOpen(open) {
      if (open) {
        menu.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
        if (hasUnread) {
          if (triggerDot) triggerDot.classList.add("is-hidden");
          if (itemDot) itemDot.classList.remove("is-hidden");
        }
      } else {
        menu.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        if (hasUnread) {
          if (triggerDot) triggerDot.classList.remove("is-hidden");
          if (itemDot) itemDot.classList.add("is-hidden");
        }
      }
    }

    trigger.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(menu.hidden);
    });

    document.addEventListener("click", function (event) {
      if (!root.contains(event.target)) {
        setOpen(false);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".nav-account-dropdown").forEach(initAccountMenu);
  });
})();
