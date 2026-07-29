/**
 * Teacher attempt review: render frozen problems + rescore fields.
 */

function getCookie(name) {
  if (typeof window.getCookie === 'function') {
    const fromGlobal = window.getCookie(name);
    if (fromGlobal != null && fromGlobal !== '') return fromGlobal;
  }
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

function csrfToken() {
  const fromCookie = getCookie('csrftoken');
  if (fromCookie) return fromCookie;
  const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
  return input ? input.value : '';
}

function escapeHtml(val) {
  return String(val ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Render expected / student answer text with KaTeX for latex(...) and \(...\).
 * Mirrors practice_test.js formatExpectedAnswerHtml.
 */
function formatExpectedAnswerHtml(raw) {
  const text = String(raw ?? '').trim();
  if (!text) return '';

  const latexFn = text.match(/^latex\s*\(([\s\S]*)\)\s*$/i);
  if (latexFn && typeof katex !== 'undefined') {
    const span = document.createElement('span');
    try {
      katex.render(latexFn[1], span, { displayMode: false, throwOnError: false });
      return span.innerHTML;
    } catch (_) {
      return escapeHtml(text);
    }
  }

  const inlineMath = text.match(/^\\\(([\s\S]*)\\\)$/);
  if (inlineMath && typeof katex !== 'undefined') {
    const span = document.createElement('span');
    try {
      katex.render(inlineMath[1], span, { displayMode: false, throwOnError: false });
      return span.innerHTML;
    } catch (_) {
      return escapeHtml(text);
    }
  }

  if (/latex\s*\(/i.test(text) || text.includes('\\(')) {
    let out = '';
    let i = 0;
    const s = text;
    while (i < s.length) {
      if (s.startsWith('\\(', i)) {
        const end = s.indexOf('\\)', i + 2);
        if (end !== -1) {
          const latex = s.slice(i + 2, end);
          if (typeof katex !== 'undefined') {
            const span = document.createElement('span');
            try {
              katex.render(latex, span, { displayMode: false, throwOnError: false });
              out += span.innerHTML;
            } catch (_) {
              out += escapeHtml(latex);
            }
          } else {
            out += escapeHtml(latex);
          }
          i = end + 2;
          continue;
        }
      }
      const fnMatch = s.slice(i).match(/^latex\s*\(/i);
      if (fnMatch && (i === 0 || !/[A-Za-z0-9_]/.test(s[i - 1]))) {
        let depth = 1;
        let j = i + fnMatch[0].length;
        while (j < s.length && depth > 0) {
          if (s[j] === '(') depth += 1;
          else if (s[j] === ')') depth -= 1;
          if (depth === 0) break;
          j += 1;
        }
        if (depth === 0) {
          const latex = s.slice(i + fnMatch[0].length, j);
          if (typeof katex !== 'undefined') {
            const span = document.createElement('span');
            try {
              katex.render(latex, span, { displayMode: false, throwOnError: false });
              out += span.innerHTML;
            } catch (_) {
              out += escapeHtml(latex);
            }
          } else {
            out += escapeHtml(latex);
          }
          i = j + 1;
          continue;
        }
      }
      out += escapeHtml(s[i]);
      i += 1;
    }
    return out;
  }

  if (typeof katex !== 'undefined' && /[\\^_{}]/.test(text) && !/</.test(text)) {
    const span = document.createElement('span');
    try {
      katex.render(text, span, { displayMode: false, throwOnError: false });
      return span.innerHTML;
    } catch (_) {
      return escapeHtml(text);
    }
  }

  return escapeHtml(text);
}

function formatAnswerLinesHtml(lines) {
  const cleaned = (lines || [])
    .map((x) => String(x ?? '').trim())
    .filter(Boolean);
  if (!cleaned.length) return '<em>blank</em>';
  if (cleaned.length === 1) return formatExpectedAnswerHtml(cleaned[0]);
  return `<ul class="grade-answer-lines">${cleaned
    .map((line) => `<li>${formatExpectedAnswerHtml(line)}</li>`)
    .join('')}</ul>`;
}

const mcVisualConfigById = new Map();
const reviewVisualPreviewById = new Map();

/**
 * MC linked graphs/matrices arrive as structured parts (latex / graph / text).
 * Falls back to plain lines when parts are absent.
 */
function formatAnswerPartsHtml(parts, linesFallback) {
  const list = Array.isArray(parts) ? parts.filter((p) => p && typeof p === 'object') : [];
  if (!list.length) return formatAnswerLinesHtml(linesFallback);

  const blocks = list.map((part, idx) => {
    const kind = String(part.kind || 'text');
    if ((kind === 'graph' || kind === 'slopeFieldGraph') && part.config) {
      const visualId = `mc-vis-${Date.now()}-${idx}-${Math.random().toString(36).slice(2, 8)}`;
      mcVisualConfigById.set(visualId, { kind, config: part.config });
      const canvasId = `${visualId}-canvas`;
      return `<div class="grade-answer-visual" data-role="mc-visual" data-visual-id="${escapeHtml(visualId)}" data-canvas-id="${escapeHtml(canvasId)}">
        <div id="${escapeHtml(canvasId)}" class="grade-mc-graph-canvas" style="width:260px;height:180px;max-width:100%;box-sizing:border-box;border:1px solid #e2e8f0;border-radius:6px;background:#fff;"></div>
      </div>`;
    }
    if (kind === 'latex') {
      return `<div class="grade-answer-part">${formatExpectedAnswerHtml(part.value || '')}</div>`;
    }
    const text = String(part.value ?? '').trim();
    return text
      ? `<div class="grade-answer-part">${formatExpectedAnswerHtml(text)}</div>`
      : '';
  }).filter(Boolean);

  if (!blocks.length) return formatAnswerLinesHtml(linesFallback);
  if (blocks.length === 1) return blocks[0];
  return `<div class="grade-answer-parts">${blocks.join('')}</div>`;
}

function formatVisualCompareHtml(field, previewId) {
  const preview = field?.visual_preview;
  const kind = preview?.kind;
  if (!previewId || !preview?.config) return '';
  if (kind !== 'slopeFieldGraph' && kind !== 'graphBetweenPoints') return '';
  return `
    <div class="practice-visual-compare grade-visual-compare" data-visual-id="${escapeHtml(previewId)}" data-visual-kind="${escapeHtml(kind)}">
      <div class="practice-visual-pair">
        <div class="practice-visual-pane grade-student-block" style="margin:0;">
          <div class="grade-answer-label">Student answer</div>
          <div class="practice-visual-host" data-role="visual-student"></div>
        </div>
        <div class="practice-visual-pane grade-expected-block" style="margin:0;">
          <div class="grade-answer-label">Expected</div>
          <div class="practice-visual-host" data-role="visual-expected"></div>
        </div>
      </div>
    </div>
  `;
}

function mountMcAnswerVisuals(root, api) {
  if (!root || !api) return;
  root.querySelectorAll('[data-role="mc-visual"]').forEach((wrap) => {
    if (wrap.getAttribute('data-mounted') === '1') return;
    const visualId = wrap.getAttribute('data-visual-id') || '';
    const canvasId = wrap.getAttribute('data-canvas-id') || '';
    const entry = mcVisualConfigById.get(visualId);
    if (!entry || !entry.config) return;
    try {
      if (entry.kind === 'graph' && typeof api.renderGraphComponentCanvas === 'function') {
        api.renderGraphComponentCanvas(canvasId, entry.config, { width: 260, height: 180 });
      } else if (entry.kind === 'slopeFieldGraph' && typeof api.renderSlopeFieldCanvas === 'function') {
        const host = document.getElementById(canvasId);
        if (!host) return;
        api.renderSlopeFieldCanvas(host, entry.config, {
          mode: 'author',
          readOnly: true,
          width: 260,
          height: 180,
        });
      } else {
        return;
      }
      wrap.setAttribute('data-mounted', '1');
    } catch (err) {
      console.warn('Failed to render MC answer visual', err);
    }
  });
}

function mountReviewVisualPreviews(root, api) {
  if (!root || !api) return;
  root.querySelectorAll('.grade-visual-compare').forEach((wrap) => {
    if (wrap.getAttribute('data-mounted') === '1') return;
    const previewId = wrap.getAttribute('data-visual-id') || '';
    const preview = reviewVisualPreviewById.get(previewId);
    if (!preview || !preview.config) return;
    const config = preview.config;
    const studentHost = wrap.querySelector('[data-role="visual-student"]');
    const expectedHost = wrap.querySelector('[data-role="visual-expected"]');
    if (studentHost) studentHost.innerHTML = '';
    if (expectedHost) expectedHost.innerHTML = '';
    const size = { width: 280, height: 200 };
    try {
      if (preview.kind === 'slopeFieldGraph') {
        if (typeof api.renderSlopeFieldCanvas !== 'function') return;
        const marks = Array.isArray(preview.student_marks) ? preview.student_marks : [];
        if (studentHost) {
          api.renderSlopeFieldCanvas(studentHost, config, {
            mode: 'student',
            initialMarks: marks,
            readOnly: true,
            ...size,
          });
        }
        if (expectedHost) {
          api.renderSlopeFieldCanvas(expectedHost, config, {
            mode: 'author',
            readOnly: true,
            ...size,
          });
        }
      } else if (preview.kind === 'graphBetweenPoints') {
        if (typeof api.renderGraphBetweenPointsCanvas !== 'function') return;
        const studentSegs = Array.isArray(preview.student_segments)
          ? preview.student_segments
          : [];
        const expectedSegs = Array.isArray(preview.expected_segments)
          ? preview.expected_segments
          : [];
        if (studentHost) {
          api.renderGraphBetweenPointsCanvas(studentHost, config, {
            mode: 'student',
            studentSegments: studentSegs,
            ...size,
          });
        }
        if (expectedHost) {
          api.renderGraphBetweenPointsCanvas(expectedHost, config, {
            mode: 'student',
            studentSegments: expectedSegs,
            ...size,
          });
        }
      } else {
        return;
      }
      wrap.setAttribute('data-mounted', '1');
    } catch (err) {
      console.warn('Failed to render review visual preview', err);
    }
  });
}

function formatExpectedList(expectedAnswers, fallbackExpected) {
  let list = Array.isArray(expectedAnswers) ? expectedAnswers.filter(Boolean) : [];
  if (!list.length && fallbackExpected != null && fallbackExpected !== '') {
    list = [fallbackExpected];
  }
  return formatAnswerLinesHtml(list);
}

function buildSegmentMap(segments) {
  const map = {};
  (segments || []).forEach((seg) => {
    const key = String(seg.sequence_token || '').trim();
    if (key) map[key] = seg;
  });
  return map;
}

function buildLatexByToken(segments) {
  const out = {};
  (segments || []).forEach((seg) => {
    const key = String(seg.sequence_token || '').trim();
    if (!key) return;
    if (seg.latex_output !== undefined && seg.latex_output !== null && seg.latex_output !== '') {
      out[key] = seg.latex_output;
    }
  });
  return out;
}

function waitForPreviewApi(timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    (function tick() {
      if (window.PracticeTestPreviewAPI && window.PracticeTestPreviewAPI.ready) {
        resolve(window.PracticeTestPreviewAPI);
        return;
      }
      if (Date.now() - start > timeoutMs) {
        reject(new Error('Preview API failed to load.'));
        return;
      }
      setTimeout(tick, 50);
    })();
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  const cfg = window.GRADE_REVIEW_CONFIG || {};
  const statusEl = document.getElementById('grade-review-status');
  const problemsEl = document.getElementById('grade-review-problems');
  const saveStatus = document.getElementById('grade-save-status');
  const showExpectedCb = document.getElementById('grade-show-expected');
  const studentReadonly = !!cfg.studentReadonly;

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || '';
  }

  function applyExpectedVisibility() {
    if (!problemsEl || !showExpectedCb) return;
    problemsEl.classList.toggle('show-expected', !!showExpectedCb.checked);
    // Re-paint expected canvases after they become visible (hidden hosts measure as 0×0).
    if (showExpectedCb.checked && window.PracticeTestPreviewAPI) {
      problemsEl.querySelectorAll('.grade-visual-compare[data-mounted="1"]').forEach((wrap) => {
        wrap.removeAttribute('data-mounted');
      });
      mountReviewVisualPreviews(problemsEl, window.PracticeTestPreviewAPI);
    }
  }

  if (showExpectedCb) {
    showExpectedCb.addEventListener('change', applyExpectedVisibility);
  }

  try {
    setStatus('Loading attempt…');
    const res = await fetch(cfg.payloadUrl, {
      headers: { Accept: 'application/json' },
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Failed to load attempt.');
    }
    const api = await waitForPreviewApi();
    // Teacher/student review: show submitted interactive answers without allowing edits.
    window.__PREVIEW_INTERACTIVE_READONLY = true;
    const problems = data.problems || [];
    problemsEl.innerHTML = '';
    mcVisualConfigById.clear();
    reviewVisualPreviewById.clear();

    problems.forEach((problem) => {
      const slot = problem.slot_index;
      const card = document.createElement('article');
      card.className = 'practice-problem-card';
      card.dataset.problemRowId = String(problem.problem_row_id);

      const manualBadge = problem.requires_manual_grading
        ? '<span class="manual-pill" data-role="manual-pill">Needs manual grade</span>'
        : '';
      const acceptZeroBtn =
        !studentReadonly && problem.requires_manual_grading
          ? '<button type="button" class="btn-accept-zero" data-role="accept-zero">Accept 0 as the score</button>'
          : '';

      card.innerHTML = `
        <div class="practice-problem-meta">
          <h3 class="practice-problem-title">${slot}. ${escapeHtml(problem.title || `Question ${slot}`)}</h3>
          ${manualBadge}
          <span class="practice-problem-chip">${escapeHtml(problem.earned_points ?? '—')} / ${escapeHtml(problem.max_points ?? '—')}</span>
          ${acceptZeroBtn}
        </div>
        <div class="practice-preview-target" data-role="preview"></div>
        <div class="practice-stub-host" data-role="stubs" aria-hidden="true"></div>
        <div class="grade-fields" data-role="fields"></div>
      `;
      problemsEl.appendChild(card);

      const previewTarget = card.querySelector('[data-role="preview"]');
      const stubHost = card.querySelector('[data-role="stubs"]');
      const fieldsHost = card.querySelector('[data-role="fields"]');
      const segments = problem.loaded_segments_full || problem.loaded_segments || [];
      api.buildStubCards(stubHost, segments);
      api.renderPreview(previewTarget, problem.body_html || '<p><br></p>', {
        cardScope: stubHost,
        segmentMap: buildSegmentMap(segments),
        latexByToken: buildLatexByToken(segments),
        studentAnswers: problem.student_answers || {},
        previewNamePrefix: `review${slot}`,
      });
      previewTarget.querySelectorAll('input, textarea, button, select').forEach((el) => {
        el.disabled = true;
      });

      (problem.fields || []).forEach((field, fieldIdx) => {
        const row = document.createElement('div');
        const isManual = !!field.requires_manual_grading;
        const showCompare = field.show_answer_compare !== false;
        row.className = 'grade-field-row' + (isManual ? ' manual-flag' : '');
        const val =
          field.points_score != null && field.points_score !== ''
            ? field.points_score
            : '';

        const visualKind = field.visual_preview?.kind;
        const hasVisual =
          showCompare
          && field.visual_preview?.config
          && (visualKind === 'slopeFieldGraph' || visualKind === 'graphBetweenPoints');
        let visualCompareHtml = '';
        if (hasVisual) {
          const previewId = `review-p${problem.problem_row_id}-f${fieldIdx}-${String(field.field_token || fieldIdx)}`;
          reviewVisualPreviewById.set(previewId, field.visual_preview);
          visualCompareHtml = formatVisualCompareHtml(field, previewId);
        }

        const studentHtml = hasVisual
          ? ''
          : formatAnswerPartsHtml(field.student_answer_parts, field.student_answer_lines);
        const expectedHtml = hasVisual
          ? ''
          : (Array.isArray(field.expected_answer_parts) && field.expected_answer_parts.length
            ? formatAnswerPartsHtml(field.expected_answer_parts, field.expected_answers)
            : formatExpectedList(field.expected_answers, field.expected));
        const maxVal =
          field.max_points != null && field.max_points !== ''
            ? field.max_points
            : field.base_max_points != null
              ? field.base_max_points
              : '';
        const baseHint =
          field.base_max_points != null &&
          Number(field.base_max_points) !== Number(maxVal)
            ? ` <span class="grade-auto-result">(base ${escapeHtml(field.base_max_points)})</span>`
            : '';
        const extraCreditHint =
          Number(maxVal) === 0
            ? ' <span class="grade-auto-result" title="Earned points count; max 0 does not add to the denominator">extra credit</span>'
            : '';
        const scoreControl = studentReadonly
          ? `<span class="grade-auto-result"><strong>${escapeHtml(val === '' ? '—' : val)}</strong> / ${escapeHtml(maxVal === '' ? '—' : maxVal)}${extraCreditHint}</span>`
          : `<input type="number" step="any" min="0"
              data-role="earned"
              data-problem-row-id="${escapeHtml(problem.problem_row_id)}"
              data-field-token="${escapeHtml(field.field_token)}"
              value="${escapeHtml(val)}" />
            <span class="grade-auto-result">/</span>
            <input type="number" step="any" min="0"
              data-role="max"
              data-problem-row-id="${escapeHtml(problem.problem_row_id)}"
              data-field-token="${escapeHtml(field.field_token)}"
              value="${escapeHtml(maxVal)}"
              title="Base / max points for this field. Set to 0 for extra credit."
              style="width:4.5rem;" />
            ${field.auto_points_score != null ? `<span class="grade-auto-result">(auto ${escapeHtml(field.auto_points_score)})</span>` : ''}
            ${baseHint}${extraCreditHint}`;

        row.innerHTML = `
          <div class="grade-field-main">
            ${isManual ? '<span class="manual-pill">Manual</span>' : ''}
            <label>${escapeHtml(field.label || field.field_token)}</label>
            <span style="font-size:0.8rem;color:#64748b;">${escapeHtml(field.archetype || '')}</span>
            ${scoreControl}
          </div>
          ${
            hasVisual
              ? visualCompareHtml
              : (
                showCompare
                  ? `<div class="grade-student-block">
                       <div class="grade-answer-label">Student answer</div>
                       <div>${studentHtml}</div>
                     </div>`
                  : ''
              )
          }
          ${
            !hasVisual
            && showCompare
            && !isManual
            && expectedHtml
            && expectedHtml !== '<em>blank</em>'
              ? `<div class="grade-expected-block">
                   <div class="grade-answer-label">Expected</div>
                   <div>${expectedHtml}</div>
                 </div>`
              : ''
          }
        `;
        fieldsHost.appendChild(row);
      });
      mountMcAnswerVisuals(fieldsHost, api);
      mountReviewVisualPreviews(fieldsHost, api);
    });

    applyExpectedVisibility();

    setStatus(
      `${problems.length} question${problems.length === 1 ? '' : 's'} · ` +
        `Total ${data.earned_points ?? '—'} / ${data.max_points ?? '—'}`
    );

    if (!studentReadonly) {
      let saveTimer = null;
      let saveNoteTimer = null;
      let saving = false;
      let queuedInput = null;

      function fieldRowFor(input) {
        return input.closest('.grade-field-row');
      }

      function collectFieldUpdate(input) {
        const row = fieldRowFor(input);
        if (!row) return null;
        const earnedInput = row.querySelector('input[data-role="earned"]');
        const maxInput = row.querySelector('input[data-role="max"]');
        if (!earnedInput) return null;
        const problemRowId = Number(earnedInput.dataset.problemRowId);
        const fieldToken = earnedInput.dataset.fieldToken;
        if (!Number.isFinite(problemRowId) || !fieldToken) return null;

        // Allow blank earned while typing; treat blank as 0 when max is being set
        let pts;
        if (earnedInput.value === '') {
          if (input === maxInput) {
            pts = 0;
          } else {
            return null;
          }
        } else {
          pts = Number(earnedInput.value);
          if (!Number.isFinite(pts)) return { error: 'Invalid score value.' };
        }

        const update = {
          problem_row_id: problemRowId,
          field_token: fieldToken,
          points_score: pts,
        };
        if (maxInput && maxInput.value !== '') {
          const maxPts = Number(maxInput.value);
          if (!Number.isFinite(maxPts) || maxPts < 0) {
            return { error: 'Invalid max points value.' };
          }
          update.max_points = maxPts;
        }
        return { update, row };
      }

      function showSavedNote(row) {
        if (!row) return;
        let note = row.querySelector('[data-role="score-save-note"]');
        if (!note) {
          note = document.createElement('span');
          note.dataset.role = 'score-save-note';
          note.className = 'grade-score-save-note';
          const main = row.querySelector('.grade-field-main');
          (main || row).appendChild(note);
        }
        note.textContent = 'Score edit saved';
        note.classList.add('is-visible');
        if (saveNoteTimer) window.clearTimeout(saveNoteTimer);
        saveNoteTimer = window.setTimeout(() => {
          note.classList.remove('is-visible');
          note.textContent = '';
        }, 1800);
        if (saveStatus) saveStatus.textContent = '';
      }

      function showRowError(input, message) {
        const row = fieldRowFor(input);
        if (!row) {
          if (saveStatus) saveStatus.textContent = message;
          return;
        }
        let note = row.querySelector('[data-role="score-save-note"]');
        if (!note) {
          note = document.createElement('span');
          note.dataset.role = 'score-save-note';
          note.className = 'grade-score-save-note';
          const main = row.querySelector('.grade-field-main');
          (main || row).appendChild(note);
        }
        note.textContent = message;
        note.classList.add('is-visible');
      }

      function updateCardTotals(card) {
        if (!card) return;
        let earned = 0;
        let max = 0;
        card.querySelectorAll('input[data-role="earned"]').forEach((el) => {
          const n = Number(el.value);
          if (Number.isFinite(n)) earned += n;
        });
        card.querySelectorAll('input[data-role="max"]').forEach((el) => {
          const n = Number(el.value);
          if (Number.isFinite(n) && n > 0) max += n;
        });
        const chip = card.querySelector('.practice-problem-chip');
        if (chip) chip.textContent = `${earned} / ${max}`;
      }

      function clearProblemManualChrome(card) {
        if (!card) return;
        const pill = card.querySelector('[data-role="manual-pill"]');
        if (pill) pill.remove();
        const btn = card.querySelector('[data-role="accept-zero"]');
        if (btn) btn.remove();
      }

      function markFieldGraded(row) {
        if (!row) return;
        row.classList.remove('manual-flag');
        const fieldPill = row.querySelector('.manual-pill');
        if (fieldPill) fieldPill.remove();
      }

      async function postScoreUpdates(updates) {
        const token = csrfToken();
        if (!token) {
          throw new Error('Missing CSRF token — refresh the page and try again.');
        }
        const saveRes = await fetch(cfg.saveUrl, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': token,
          },
          body: JSON.stringify({ updates }),
        });
        let saveData = {};
        try {
          saveData = await saveRes.json();
        } catch (_) {
          saveData = {};
        }
        if (!saveRes.ok || !saveData.success) {
          throw new Error(saveData.error || `Save failed (${saveRes.status}).`);
        }
        if (saveData.earned_total != null || saveData.max_total != null) {
          setStatus(
            `${problems.length} question${problems.length === 1 ? '' : 's'} · ` +
              `Total ${saveData.earned_total ?? '—'} / ${saveData.max_total ?? '—'}`
          );
        }
        return saveData;
      }

      async function saveField(input) {
        const collected = collectFieldUpdate(input);
        if (!collected) return;
        if (collected.error) {
          showRowError(input, collected.error);
          return;
        }
        if (saving) {
          queuedInput = input;
          return;
        }
        saving = true;
        try {
          await postScoreUpdates([collected.update]);
          showSavedNote(collected.row);
          const card = input.closest('.practice-problem-card');
          updateCardTotals(card);
          markFieldGraded(collected.row);
          if (card && !card.querySelector('.grade-field-row.manual-flag')) {
            clearProblemManualChrome(card);
          }
        } catch (err) {
          console.error(err);
          showRowError(input, err.message || 'Save failed.');
        } finally {
          saving = false;
          if (queuedInput) {
            const next = queuedInput;
            queuedInput = null;
            scheduleSave(next);
          }
        }
      }

      function scheduleSave(input) {
        if (saveTimer) window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(() => saveField(input), 400);
      }

      problemsEl.querySelectorAll('input[data-role="earned"], input[data-role="max"]').forEach((input) => {
        input.addEventListener('change', () => scheduleSave(input));
        input.addEventListener('blur', () => scheduleSave(input));
        input.addEventListener('input', () => scheduleSave(input));
      });

      problemsEl.querySelectorAll('[data-role="accept-zero"]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const card = btn.closest('.practice-problem-card');
          if (!card) return;
          const manualRows = Array.from(
            card.querySelectorAll('.grade-field-row.manual-flag')
          );
          const targetRows = manualRows.length
            ? manualRows
            : Array.from(card.querySelectorAll('.grade-field-row'));
          const updates = [];
          const rows = [];
          targetRows.forEach((row) => {
            const earnedInput = row.querySelector('input[data-role="earned"]');
            if (!earnedInput) return;
            if (earnedInput.value === '') earnedInput.value = '0';
            const collected = collectFieldUpdate(earnedInput);
            if (!collected || collected.error || !collected.update) return;
            updates.push(collected.update);
            rows.push(row);
          });
          if (!updates.length) {
            if (saveStatus) saveStatus.textContent = 'Nothing to save for this question.';
            return;
          }
          btn.disabled = true;
          try {
            await postScoreUpdates(updates);
            rows.forEach((row) => {
              showSavedNote(row);
              markFieldGraded(row);
            });
            updateCardTotals(card);
            clearProblemManualChrome(card);
          } catch (err) {
            console.error(err);
            if (saveStatus) saveStatus.textContent = err.message || 'Save failed.';
            btn.disabled = false;
          }
        });
      });
    }
  } catch (err) {
    console.error(err);
    setStatus(err.message || 'Failed to load attempt.');
  }
});
