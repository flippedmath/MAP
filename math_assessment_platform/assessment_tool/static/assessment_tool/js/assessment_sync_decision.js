(function () {
  const LABELS = {
    reuse_existing: 'Reuse existing',
    generate_new: 'Generate new',
    proceed: 'Continue with synchronized tests',
    cancel: 'Cancel',
  };

  function ensureStyles() {
    if (document.getElementById('assessment-sync-decision-styles')) return;
    const style = document.createElement('style');
    style.id = 'assessment-sync-decision-styles';
    style.textContent = `
      .assessment-sync-overlay{position:fixed;inset:0;z-index:10050;display:flex;
        align-items:center;justify-content:center;padding:24px;background:rgba(15,23,42,.58)}
      .assessment-sync-card{width:min(560px,100%);border-radius:14px;background:#fff;
        box-shadow:0 24px 70px rgba(15,23,42,.28);padding:24px;color:#0f172a}
      .assessment-sync-card h3{margin:0 0 10px;font-size:1.25rem}
      .assessment-sync-card p{margin:8px 0;line-height:1.5;color:#475569}
      .assessment-sync-warning{border-left:4px solid #f59e0b;padding:8px 12px;
        border-radius:5px;background:#fffbeb;color:#92400e!important}
      .assessment-sync-actions{display:flex;justify-content:flex-end;gap:10px;
        flex-wrap:wrap;margin-top:20px}
      .assessment-sync-actions button{border:1px solid #cbd5e1;border-radius:8px;
        background:#fff;padding:9px 14px;cursor:pointer;font-weight:600}
      .assessment-sync-actions button[data-decision="generate_new"],
      .assessment-sync-actions button[data-decision="proceed"]{
        border-color:#2563eb;background:#2563eb;color:#fff}
    `;
    document.head.appendChild(style);
  }

  window.requestAssessmentSynchronizationDecision = function (payload) {
    ensureStyles();
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'assessment-sync-overlay';
      overlay.setAttribute('role', 'presentation');
      const card = document.createElement('div');
      card.className = 'assessment-sync-card';
      card.setAttribute('role', 'dialog');
      card.setAttribute('aria-modal', 'true');
      card.setAttribute('aria-labelledby', 'assessment-sync-title');

      const title = document.createElement('h3');
      title.id = 'assessment-sync-title';
      title.textContent = payload.title || 'Synchronize tests';
      const message = document.createElement('p');
      message.textContent = payload.message || '';
      card.append(title, message);

      if (payload.history_warning) {
        const warning = document.createElement('p');
        warning.className = 'assessment-sync-warning';
        warning.textContent =
          'Some earlier attempts were generated independently. They will remain unchanged.';
        card.appendChild(warning);
      }
      if (payload.settings_hint) {
        const hint = document.createElement('p');
        hint.className = 'assessment-sync-warning';
        hint.textContent = payload.settings_hint;
        card.appendChild(hint);
      }

      const actions = document.createElement('div');
      actions.className = 'assessment-sync-actions';
      const decisions = payload.decisions || ['cancel'];
      decisions.forEach((decision) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.decision = decision;
        button.textContent = LABELS[decision] || decision;
        actions.appendChild(button);
      });
      card.appendChild(actions);
      overlay.appendChild(card);
      document.body.appendChild(overlay);

      let finished = false;
      function finish(decision) {
        if (finished) return;
        finished = true;
        document.removeEventListener('keydown', onKeydown);
        overlay.remove();
        resolve(decision === 'cancel' ? null : decision);
      }
      function onKeydown(event) {
        if (event.key === 'Escape') finish(null);
      }
      actions.addEventListener('click', (event) => {
        const button = event.target.closest('[data-decision]');
        if (button) finish(button.dataset.decision);
      });
      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) finish(null);
      });
      document.addEventListener('keydown', onKeydown);
      const first = actions.querySelector('button:not([data-decision="cancel"])')
        || actions.querySelector('button');
      if (first) first.focus();
    });
  };
})();
