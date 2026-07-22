(function () {
  var DATE_OPTS = {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  };

  /**
   * Parse an ISO timestamp as an absolute UTC instant.
   * Strings without an explicit offset/Z are treated as UTC (DB convention),
   * not as the browser's local wall clock.
   */
  function parseUtcInstant(iso) {
    if (!iso) return null;
    var text = String(iso).trim();
    if (
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(text)
    ) {
      text += "Z";
    }
    var date = new Date(text);
    if (Number.isNaN(date.getTime())) return null;
    return date;
  }

  function formatLocal(iso) {
    var date = parseUtcInstant(iso);
    if (!date) return "";
    return date.toLocaleString(undefined, DATE_OPTS);
  }

  function hydrateLocalDatetimes(root) {
    var scope = root || document;
    scope.querySelectorAll("time.local-datetime[datetime]").forEach(function (el) {
      var formatted = formatLocal(el.getAttribute("datetime"));
      if (formatted) {
        el.textContent = formatted;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    hydrateLocalDatetimes(document);
  });

  window.MAPHydrateLocalDatetimes = hydrateLocalDatetimes;
})();
