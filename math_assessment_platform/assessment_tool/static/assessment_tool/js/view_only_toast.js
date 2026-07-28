/**
 * Show a brief red toast when the server rejects a save because of explorer view-only mode.
 */
(function () {
  const TOAST_ID = 'map-view-only-toast';
  const CODE = 'content_view_only';
  const DEFAULT_MSG =
    "You are in view-only mode and cannot save edits. Open the item in Edit mode from the explorer to make changes.";

  function ensureToastEl() {
    let el = document.getElementById(TOAST_ID);
    if (el) return el;
    el = document.createElement('div');
    el.id = TOAST_ID;
    el.setAttribute('role', 'alert');
    el.style.cssText = [
      'display:none',
      'position:fixed',
      'top:72px',
      'left:50%',
      'transform:translateX(-50%)',
      'z-index:100000',
      'max-width:min(560px,90vw)',
      'padding:12px 16px',
      'border-radius:8px',
      'border:1px solid #fecaca',
      'background:#fee2e2',
      'color:#991b1b',
      'box-shadow:0 8px 24px rgba(15,23,42,0.18)',
      'font-size:0.95rem',
      'font-weight:600',
      'text-align:center',
      'pointer-events:none',
    ].join(';');
    document.body.appendChild(el);
    return el;
  }

  let hideTimer = null;
  window.showViewOnlyToast = function showViewOnlyToast(message) {
    const el = ensureToastEl();
    el.textContent = message || DEFAULT_MSG;
    el.style.display = 'block';
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      el.style.display = 'none';
    }, 4500);
  };

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function mapFetchWithViewOnlyToast(...args) {
    const response = await originalFetch(...args);
    if (response.status === 403) {
      try {
        const data = await response.clone().json();
        if (data && data.code === CODE) {
          window.showViewOnlyToast(data.error || DEFAULT_MSG);
        }
      } catch (_err) {
        /* non-JSON 403 */
      }
    }
    return response;
  };
})();
