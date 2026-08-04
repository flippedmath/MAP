/**
 * Compact print-ready assessment + numbered answer key.
 * Hydrates student problems via PracticeTestPreviewAPI; strips digital inputs.
 */

function escapeHtml(val) {
  return String(val ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

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

  // Mixed "(A) latex(...)" style MC answers
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

function waitForPreviewApi(timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      if (window.PracticeTestPreviewAPI && window.PracticeTestPreviewAPI.ready) {
        resolve(window.PracticeTestPreviewAPI);
        return;
      }
      if (Date.now() - started > timeoutMs) {
        reject(new Error('Preview engine did not load in time.'));
        return;
      }
      requestAnimationFrame(tick);
    };
    tick();
  });
}

function buildSegmentMap(segments) {
  const map = new Map();
  (segments || []).forEach((seg) => {
    const key = String(seg.sequence_token || '').trim();
    if (key) map.set(key, seg);
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

function workSpaceLines(problem) {
  const fields = problem.answer_fields || [];
  const onlyMc =
    fields.length > 0 &&
    fields.every((f) => {
      const arch = String(f.archetype || f.token || '').replace(/\d+$/, '');
      return arch === 'multipleChoiceAnswer';
    });
  if (onlyMc) return 0;

  if (problem.work_space == null || problem.work_space === '') return 2;
  const n = Number(problem.work_space);
  if (!Number.isFinite(n) || n <= 0) return 2;
  if (n <= 12) return Math.max(1, Math.min(4, Math.round(n)));
  return Math.max(1, Math.min(4, Math.round(n / 24)));
}

/** Replace digital answer widgets with handwriting blanks. Keep MC choice text. */
function replaceAnswerInputsWithBlanks(root) {
  if (!root) return;
  const selectors = [
    '.simulated-short-answer-wrapper',
    '.simulated-num-answer-wrapper',
    '.simulated-answers-or-dne-wrapper',
    '.simulated-long-answer-wrapper',
    '.simulated-matrix-answer-wrapper',
    '.simulated-canvas-wrapper',
    '.simulated-array-matching-wrapper',
  ].join(',');

  root.querySelectorAll(selectors).forEach((el) => {
    const blank = document.createElement('span');
    const isBlock =
      el.classList.contains('simulated-answers-or-dne-wrapper') ||
      el.classList.contains('simulated-long-answer-wrapper') ||
      el.classList.contains('simulated-canvas-wrapper');
    blank.className = isBlock
      ? 'print-handwrite-blank print-handwrite-blank--block'
      : 'print-handwrite-blank';
    el.replaceWith(blank);
  });

  // Keep choice labels; hide interactive radios/checkboxes (students circle on paper).
  root.querySelectorAll('.preview-mc-choice').forEach((input) => {
    input.setAttribute('aria-hidden', 'true');
    input.tabIndex = -1;
    input.style.cssText =
      'position:absolute;opacity:0;width:0;height:0;pointer-events:none;';
  });
  root.querySelectorAll('.mc-options-list').forEach((list) => {
    list.querySelectorAll('.mc-option-preview-row').forEach((row, idx) => {
      if (row.querySelector('.print-mc-letter')) return;
      const letterChar = String.fromCharCode(65 + (idx % 26));
      row.setAttribute('data-print-letter', letterChar);
      const letter = document.createElement('span');
      letter.className = 'print-mc-letter';
      letter.textContent = `(${letterChar}) `;
      const label = row.querySelector('.mc-option-preview-label');
      if (label) label.prepend(letter);
      else row.prepend(letter);
    });
  });
}

/** Map option id → printed letter from the student card (respects MC shuffle order). */
function mcLetterMapForSlot(studentHost, slot) {
  const safeSlot = String(slot).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const card = studentHost.querySelector(
    `.print-problem[data-slot-index="${safeSlot}"]`
  );
  const map = {};
  if (!card) return map;
  card.querySelectorAll('.mc-option-preview-row').forEach((row) => {
    const id = row.getAttribute('data-option-id') || '';
    const letter = row.getAttribute('data-print-letter') || '';
    if (id && letter) map[id] = letter;
  });
  return map;
}

function appendWorkSpace(card, lines) {
  if (!lines || lines <= 0) return;
  const work = document.createElement('div');
  work.className = 'print-work-space';
  work.setAttribute('data-lines', String(lines));
  for (let i = 0; i < lines; i += 1) {
    const rule = document.createElement('div');
    rule.className = 'print-work-line';
    work.appendChild(rule);
  }
  card.appendChild(work);
}

/** Unclip Quill tables so formulas/graphs inside cells can paint for print. */
function prepareTablesForPrint(root) {
  if (!root) return;
  root.querySelectorAll('table').forEach((table) => {
    table.classList.add('ql-table-expand-entities');
    table.setAttribute('data-expand-entities', 'true');
    table.classList.remove('ql-table-fixed-entities');
    table.style.maxWidth = '100%';
    // Allow natural growth; locked editor heights clip KaTeX/graphs on paper.
    table.querySelectorAll('tr').forEach((tr) => {
      tr.style.height = 'auto';
      tr.style.minHeight = '';
    });
    table.querySelectorAll('td, th').forEach((cell) => {
      cell.style.height = 'auto';
      cell.style.minHeight = '';
      cell.style.overflow = 'visible';
    });
  });
  root.querySelectorAll('.ql-preview-fit-viewport').forEach((el) => {
    el.style.overflow = 'visible';
    el.style.maxHeight = 'none';
    el.style.transform = 'none';
  });
}

function createProblemShell(problem, idx) {
  const slot = problem.slot_index || idx + 1;
  const card = document.createElement('article');
  const wide = !!(problem.full_width || problem.has_media);
  card.className = `print-problem ${wide ? 'print-problem--wide' : 'print-problem--narrow'}`;
  card.dataset.slotIndex = String(slot);
  card.dataset.wide = wide ? '1' : '0';
  card._printProblem = problem;
  card._printIdx = idx;

  card.innerHTML = `
    <div class="print-problem-num">${slot}.</div>
    <div class="print-problem-body">
      <div class="print-preview-target" data-role="preview"></div>
      <div class="print-stub-host" data-role="stubs" aria-hidden="true"></div>
    </div>
  `;
  return card;
}

/** Hydrate after the card is in the document so table/graph layout has real widths. */
function hydrateProblemCard(api, card) {
  const problem = card._printProblem || {};
  const idx = card._printIdx || 0;
  const slot = problem.slot_index || idx + 1;
  const previewTarget = card.querySelector('[data-role="preview"]');
  const stubHost = card.querySelector('[data-role="stubs"]');
  const segments = problem.loaded_segments || [];

  api.buildStubCards(stubHost, segments);
  api.renderPreview(previewTarget, problem.body_html || '<p><br></p>', {
    cardScope: stubHost,
    segmentMap: buildSegmentMap(segments),
    latexByToken: buildLatexByToken(segments),
    studentAnswers: {},
    previewNamePrefix: `stu${slot}`,
  });
  prepareTablesForPrint(previewTarget);
  replaceAnswerInputsWithBlanks(previewTarget);
  appendWorkSpace(card.querySelector('.print-problem-body'), workSpaceLines(problem));
}

function flushPair(host, pair) {
  if (!pair.length) return;
  if (pair.length === 1) {
    pair[0].classList.remove('print-problem--narrow');
    pair[0].classList.add('print-problem--wide');
    host.appendChild(pair[0]);
    pair.length = 0;
    return;
  }
  const row = document.createElement('div');
  row.className = 'print-problem-row';
  pair.forEach((card) => row.appendChild(card));
  host.appendChild(row);
  pair.length = 0;
}

function renderStudentProblems(api, host, problems) {
  let lastSection = null;
  const pair = [];
  const cards = [];

  problems.forEach((problem, idx) => {
    const section = String(problem.section_name || '').trim();
    if (section && section !== lastSection) {
      flushPair(host, pair);
      const banner = document.createElement('div');
      banner.className = 'print-section-banner';
      banner.textContent = section;
      host.appendChild(banner);
      lastSection = section;
    }

    const card = createProblemShell(problem, idx);
    cards.push(card);
    if (card.dataset.wide === '1') {
      flushPair(host, pair);
      host.appendChild(card);
    } else {
      pair.push(card);
      if (pair.length >= 2) flushPair(host, pair);
    }
  });
  flushPair(host, pair);

  // Paint only after layout attachment (critical for graphs inside tables).
  cards.forEach((card) => hydrateProblemCard(api, card));
}

function formatKeyRow(row, letterMap) {
  if (!row) return '';
  if (row.kind === 'mc') {
    const ids = String(row.correct_option_ids || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    const letters = ids.map((id) => letterMap[id]).filter(Boolean);
    const body = formatExpectedAnswerHtml(row.text);
    if (letters.length && body) {
      return `<span class="print-key-text">(${escapeHtml(letters.join(','))}) ${body}</span>`;
    }
    if (letters.length) {
      return `<span class="print-key-text">(${escapeHtml(letters.join(','))})</span>`;
    }
    return `<span class="print-key-text">${body || '—'}</span>`;
  }
  return `<span class="print-key-text">${formatExpectedAnswerHtml(row.text)}</span>`;
}

function renderAnswerKey(host, problems, studentHost) {
  const list = document.createElement('ol');
  list.className = 'print-key-list';

  problems.forEach((problem, idx) => {
    const slot = problem.slot_index || idx + 1;
    const li = document.createElement('li');
    li.value = slot;
    const summary = problem.answer_summary || [];
    const letterMap = mcLetterMapForSlot(studentHost, slot);
    if (!summary.length) {
      li.innerHTML = '<span class="print-key-empty">—</span>';
    } else if (summary.length === 1) {
      const row = summary[0];
      li.innerHTML = formatKeyRow(row, letterMap);
      if (row.kind === 'manual') li.classList.add('is-manual');
    } else {
      li.innerHTML = summary
        .map((row) => formatKeyRow(row, letterMap))
        .join('<span class="print-key-sep">; </span>');
    }
    list.appendChild(li);
  });

  host.appendChild(list);
}

document.addEventListener('DOMContentLoaded', async () => {
  const cfg = window.ASSESSMENT_PRINT_CONFIG || {};
  const statusEl = document.getElementById('print-status');
  const printBtn = document.getElementById('print-btn');
  const studentHost = document.getElementById('print-student-problems');
  const keyHost = document.getElementById('print-key-problems');
  const problems = Array.isArray(cfg.problems) ? cfg.problems : [];

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg || '';
  }

  if (printBtn) {
    printBtn.addEventListener('click', () => window.print());
  }

  if (!problems.length) {
    setStatus('No printable problems found for this assessment.');
    if (studentHost) {
      studentHost.innerHTML = '<p>This assessment has no complete problems to print.</p>';
    }
    return;
  }

  try {
    setStatus(`Rendering ${problems.length} problem${problems.length === 1 ? '' : 's'}…`);
    const api = await waitForPreviewApi();
    renderStudentProblems(api, studentHost, problems);
    // Table fit / graph paint settle on delayed timers inside the preview engine.
    await new Promise((r) => setTimeout(r, 250));
    studentHost.querySelectorAll('.print-preview-target').forEach((el) => {
      prepareTablesForPrint(el);
    });
    await new Promise((r) => setTimeout(r, 350));
    renderAnswerKey(keyHost, problems, studentHost);

    setStatus('Ready — use Print / Save PDF. Match key is on every page.');
    if (printBtn) printBtn.disabled = false;

    const params = new URLSearchParams(window.location.search);
    if (params.get('autoprint') === '1') {
      setTimeout(() => window.print(), 200);
    }
  } catch (err) {
    console.error(err);
    setStatus(err.message || 'Failed to render printout.');
  }
});
