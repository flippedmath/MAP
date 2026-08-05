/**
 * Teacher overlays for course default / per-assessment options.
 * Changes apply automatically when the overlay closes.
 */
(function () {
  const COUNTDOWN_TIME_LIMIT_CHOICE = '3';
  const COUNTDOWN_GROUP = '7';

  function getCookie(name) {
    const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : '';
  }

  function ensureOverlay() {
    let el = document.getElementById('grades-options-overlay');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'grades-options-overlay';
    el.className = 'grades-modal-overlay';
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML = `
      <div class="grades-modal-card grades-options-card" role="dialog" aria-modal="true" aria-labelledby="grades-options-title">
        <div class="grades-options-header">
          <div>
            <h3 id="grades-options-title">Assessment options</h3>
            <p class="grades-modal-sub" id="grades-options-sub"></p>
          </div>
          <button type="button" class="grades-options-close" id="grades-options-close" aria-label="Close">×</button>
        </div>
        <div id="grades-options-body" class="grades-options-body"></div>
        <div id="grades-options-print-actions" class="grades-options-print-actions" hidden></div>
        <p class="grades-modal-status" id="grades-options-status" aria-live="polite"></p>
      </div>
    `;
    document.body.appendChild(el);
    el.addEventListener('click', (evt) => {
      if (evt.target === el) closeAndApply();
    });
    el.querySelector('#grades-options-close').addEventListener('click', () => closeAndApply());
    return el;
  }

  let pending = null;
  let baselineKey = '';
  let applying = false;

  function currentKey() {
    const { selections, timeLimit } = collectSelections();
    return JSON.stringify({ selections, timeLimit });
  }

  function closeOverlayOnly() {
    const el = document.getElementById('grades-options-overlay');
    if (!el) return;
    el.classList.remove('is-open');
    el.setAttribute('aria-hidden', 'true');
    pending = null;
    baselineKey = '';
  }

  async function closeAndApply() {
    if (applying) return;
    const el = document.getElementById('grades-options-overlay');
    if (!el || !el.classList.contains('is-open')) return;
    if (!pending || !pending.saveUrl || !pending.payload) {
      closeOverlayOnly();
      return;
    }
    const nextKey = currentKey();
    if (nextKey === baselineKey) {
      closeOverlayOnly();
      return;
    }
    applying = true;
    const statusEl = el.querySelector('#grades-options-status');
    statusEl.textContent = 'Saving…';
    try {
      const { selections, timeLimit } = collectSelections();
      const body = { selections };
      if (pending.scope === 'course') {
        body.default_time_limit_minutes = timeLimit;
        if (pending.subset) body.subset = pending.subset;
      } else {
        body.time_limit_minutes = timeLimit;
        if (pending.subset) body.subset = pending.subset;
      }
      const res = await fetch(pending.saveUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        statusEl.textContent = data.error || 'Save failed.';
        applying = false;
        return;
      }
      window.location.reload();
    } catch (err) {
      statusEl.textContent = err.message || 'Save failed.';
      applying = false;
    }
  }

  function selectedMap(payload) {
    const raw = payload.selected || {};
    const out = {};
    Object.keys(raw).forEach((k) => {
      out[String(k)] = raw[k];
    });
    return out;
  }

  function syncTimeLimitVisibility(block) {
    const checked = block.querySelector(`input[name="opt-g-${COUNTDOWN_GROUP}"]:checked`);
    const wrap = block.querySelector('[data-time-limit-wrap]');
    if (!wrap) return;
    const show = checked && checked.value === COUNTDOWN_TIME_LIMIT_CHOICE;
    wrap.hidden = !show;
  }

  function renderPrintActions() {
    const el = ensureOverlay();
    const tray = el.querySelector('#grades-options-print-actions');
    if (!tray) return;
    tray.innerHTML = '';
    tray.hidden = true;
    if (!pending || pending.subset !== 'delivery' || !pending.printUrl) return;

    tray.hidden = false;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-modal btn-modal-submit grades-options-print-btn';
    btn.innerHTML = '<i class="fas fa-print"></i> Print assessment + answer key';
    btn.addEventListener('click', (evt) => {
      evt.preventDefault();
      evt.stopPropagation();
      if (pending.canPrint === false) {
        const statusEl = el.querySelector('#grades-options-status');
        if (statusEl) {
          statusEl.textContent =
            'Printing requires an unlocked teacher account. Buy credits in Account Settings to unlock.';
        }
        return;
      }
      window.open(pending.printUrl, '_blank', 'noopener');
    });
    const hint = document.createElement('p');
    hint.className = 'grades-options-print-hint';
    hint.textContent =
      'Opens a compact printout (assessment, blank page, answer key) with a shared match key. Use the browser Print dialog to save a PDF.';
    tray.appendChild(btn);
    tray.appendChild(hint);
  }

  function renderBody(payload) {
    const el = ensureOverlay();
    const body = el.querySelector('#grades-options-body');
    const selected = selectedMap(payload);
    const isAssessment = payload.scope === 'assessment';
    body.innerHTML = '';

    if (pending && pending.note) {
      const note = document.createElement('p');
      note.className = 'grades-options-note';
      note.textContent = pending.note;
      body.appendChild(note);
    }

    (payload.groups || []).forEach((group) => {
      const gnum = String(group.group_num);
      const block = document.createElement('fieldset');
      block.className = 'grades-options-group';
      const legend = document.createElement('legend');
      legend.textContent = group.label || `Group ${gnum}`;
      block.appendChild(legend);

      if (isAssessment) {
        const useDefault = document.createElement('label');
        useDefault.className = 'grades-release-option grades-options-default-row';
        const checked = !selected[gnum];
        useDefault.innerHTML = `
          <input type="radio" name="opt-g-${gnum}" value="__default__" ${checked ? 'checked' : ''} />
          <span>Use Course Default Setting</span>
        `;
        block.appendChild(useDefault);
      }

      (group.choices || []).forEach((ch) => {
        const label = document.createElement('label');
        label.className = 'grades-release-option';
        const isSel =
          selected[gnum] && Number(selected[gnum].choice) === Number(ch.choice);
        label.innerHTML = `
          <input type="radio" name="opt-g-${gnum}" value="${ch.choice}" ${isSel ? 'checked' : ''} />
          <span>${escapeHtml(ch.description || '')}</span>
        `;
        block.appendChild(label);
      });

      if (String(group.group_num) === COUNTDOWN_GROUP) {
        const mins =
          isAssessment
            ? (payload.time_limit_minutes != null
                ? payload.time_limit_minutes
                : payload.default_time_limit_minutes)
            : payload.default_time_limit_minutes;
        const wrap = document.createElement('div');
        wrap.className = 'grades-options-time-limit';
        wrap.setAttribute('data-time-limit-wrap', '1');
        wrap.innerHTML = `
          <span>Time limit (minutes):</span>
          <input type="number" min="1" step="1" id="grades-options-time-limit"
            value="${mins != null ? escapeHtml(mins) : ''}" placeholder="e.g. 45" />
        `;
        block.appendChild(wrap);
        block.querySelectorAll(`input[name="opt-g-${COUNTDOWN_GROUP}"]`).forEach((input) => {
          input.addEventListener('change', () => syncTimeLimitVisibility(block));
        });
        syncTimeLimitVisibility(block);
      }

      body.appendChild(block);
    });

    renderPrintActions();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function openOptions(opts) {
    const el = ensureOverlay();
    pending = opts;
    applying = false;
    const title =
      opts.scope === 'course'
        ? opts.subset === 'assessments'
          ? 'Course Assessments display options'
          : 'Course default assessment options'
        : opts.subset === 'delivery'
          ? 'Assessment delivery options'
          : opts.subset === 'grades'
            ? 'Assessment grade options'
            : 'Assessment options';
    el.querySelector('#grades-options-title').textContent = title;
    el.querySelector('#grades-options-sub').textContent =
      opts.scope === 'course'
        ? opts.subset === 'assessments'
          ? 'These settings control columns on the Course Assessments page. Changes apply when you close this panel.'
          : 'These defaults apply to assessments unless an assessment overrides them. Changes apply when you close this panel.'
        : (opts.assessmentName || '') + ' — changes apply when you close this panel.';
    el.querySelector('#grades-options-status').textContent = 'Loading…';
    const printTray = el.querySelector('#grades-options-print-actions');
    if (printTray) {
      printTray.innerHTML = '';
      printTray.hidden = true;
    }
    el.classList.add('is-open');
    el.setAttribute('aria-hidden', 'false');

    const res = await fetch(opts.loadUrl, {
      headers: { Accept: 'application/json' },
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      el.querySelector('#grades-options-status').textContent =
        data.error || 'Failed to load options.';
      return;
    }
    pending.payload = data;
    renderBody(data);
    baselineKey = currentKey();
    el.querySelector('#grades-options-status').textContent = '';
  }

  function collectSelections() {
    const el = ensureOverlay();
    const payload = pending && pending.payload;
    if (!payload) return { selections: [], timeLimit: null };
    const isAssessment = payload.scope === 'assessment';
    const selections = [];
    (payload.groups || []).forEach((group) => {
      const gnum = group.group_num;
      const checked = el.querySelector(`input[name="opt-g-${gnum}"]:checked`);
      if (!checked) return;
      if (isAssessment) {
        if (checked.value === '__default__') {
          selections.push({ group_num: gnum, clear: true });
        } else {
          selections.push({ group_num: gnum, choice: Number(checked.value) });
        }
      } else {
        selections.push({
          group_num: gnum,
          choice: Number(checked.value),
          default_setting: true,
        });
      }
    });
    const timeInput = el.querySelector('#grades-options-time-limit');
    const timeLimit = timeInput && timeInput.value !== '' ? Number(timeInput.value) : null;
    return { selections, timeLimit };
  }

  document.addEventListener('keydown', (evt) => {
    if (evt.key !== 'Escape') return;
    const el = document.getElementById('grades-options-overlay');
    if (el && el.classList.contains('is-open')) {
      evt.preventDefault();
      closeAndApply();
    }
  });

  document.addEventListener('click', (evt) => {
    const gear = evt.target.closest('[data-course-options]');
    if (gear) {
      evt.preventDefault();
      openOptions({
        scope: 'course',
        subset: gear.getAttribute('data-options-subset') || '',
        loadUrl: gear.getAttribute('data-options-load-url'),
        saveUrl: gear.getAttribute('data-options-save-url'),
      });
      return;
    }
    const btn = evt.target.closest('[data-assessment-options]');
    if (btn) {
      evt.preventDefault();
      evt.stopPropagation();
      openOptions({
        scope: 'assessment',
        subset: btn.getAttribute('data-options-subset') || '',
        note: btn.getAttribute('data-options-note') || '',
        assessmentName: btn.getAttribute('data-assessment-name') || '',
        loadUrl: btn.getAttribute('data-options-load-url'),
        saveUrl: btn.getAttribute('data-options-save-url'),
        printUrl: btn.getAttribute('data-print-url') || '',
        canPrint: btn.getAttribute('data-can-print') !== '0',
      });
    }
  });

  window.GradesOptionsUI = { open: openOptions, close: closeAndApply };
})();
