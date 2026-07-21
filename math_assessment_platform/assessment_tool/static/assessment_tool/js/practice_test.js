/**
 * Teacher practice-test page: assemble ephemeral instances, render previews,
 * batch-grade once. Relies on window.PracticeTestPreviewAPI from problem_overlay_global.js.
 */

function getCookie(name) {
    if (typeof window.getCookie === 'function') {
        return window.getCookie(name);
    }
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : '';
}

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

    // Explicit LATEX(...) / latex(...) wrappers → KaTeX
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

    // \( ... \) wrapper
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

    // Mixed content with LATEX(...) segments
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

    // Heuristic: treat pure math-ish latex as KaTeX
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

function formatExpectedListHtml(expectedList, { multiline = false } = {}) {
    const parts = (expectedList || [])
        .filter(Boolean)
        .map((item) => formatExpectedAnswerHtml(item))
        .filter(Boolean);
    if (!parts.length) return '';
    if (multiline || parts.length > 1) {
        return `<ul class="practice-answer-lines">${parts.map((p) => `<li>${p}</li>`).join('')}</ul>`;
    }
    return parts[0];
}

function formatStudentAnswerHtml(field) {
    const lines = Array.isArray(field.student_answer_lines) && field.student_answer_lines.length
        ? field.student_answer_lines
        : (field.student_answer ? String(field.student_answer).split('\n') : []);
    const cleaned = lines.map((x) => String(x ?? '').trim()).filter(Boolean);
    if (!cleaned.length) {
        return '<em>blank</em>';
    }
    if (cleaned.length === 1) {
        return formatExpectedAnswerHtml(cleaned[0]);
    }
    return `<ul class="practice-answer-lines">${cleaned.map((line) => `<li>${formatExpectedAnswerHtml(line)}</li>`).join('')}</ul>`;
}

function formatGradeNumber(n) {
    const num = Number(n);
    if (!Number.isFinite(num)) return '0';
    if (Number.isInteger(num)) return String(num);
    return String(Math.round(num * 1000) / 1000);
}

function waitForPreviewApi(timeoutMs = 15000) {
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

document.addEventListener('DOMContentLoaded', () => {
    const cfg = window.PRACTICE_TEST_CONFIG || {};
    const statusEl = document.getElementById('practice-status');
    const warningsEl = document.getElementById('practice-warnings');
    const problemsEl = document.getElementById('practice-problems');
    const gradeBtn = document.getElementById('practice-grade-btn');
    const reloadBtn = document.getElementById('practice-reload-btn');
    const gradingSection = document.getElementById('practice-grading-section');
    const gradingResults = document.getElementById('practice-grading-results');
    const gradingTotal = document.getElementById('practice-grading-total');
    const showExpectedCb = document.getElementById('practice-show-expected');

    let practiceProblems = [];
    let confirmDrafts = false;
    let confirmZeroSets = false;
    let lastGradePayload = null;

    function setStatus(msg) {
        if (statusEl) statusEl.textContent = msg || '';
    }

    function renderWarnings(skippedDrafts, zeroCountSets) {
        if (!warningsEl) return;
        const parts = [];
        if (skippedDrafts && skippedDrafts.length) {
            const items = skippedDrafts.map((d) => {
                const where = d.problem_set
                    ? `${escapeHtml(d.section || '')} / ${escapeHtml(d.problem_set)}`
                    : escapeHtml(d.section || '');
                return `<li><strong>${escapeHtml(d.title || `Problem ${d.problem_id}`)}</strong> (${escapeHtml(d.status || 'draft')})${where ? ` — ${where}` : ''}</li>`;
            }).join('');
            parts.push(`<div><strong>Skipped incomplete problems</strong><ul>${items}</ul></div>`);
        }
        if (zeroCountSets && zeroCountSets.length) {
            const items = zeroCountSets.map((s) => {
                const note = s.note ? ` — ${escapeHtml(s.note)}` : '';
                return `<li><strong>${escapeHtml(s.name || 'Problem set')}</strong> in ${escapeHtml(s.section || '')}${note}</li>`;
            }).join('');
            parts.push(`<div style="margin-top:8px;"><strong>Problem sets with zero selections</strong><ul>${items}</ul></div>`);
        }
        if (!parts.length) {
            warningsEl.style.display = 'none';
            warningsEl.innerHTML = '';
            return;
        }
        warningsEl.style.display = 'block';
        warningsEl.innerHTML = parts.join('');
    }

    const confirmOverlay = document.getElementById('practice-confirm-overlay');
    const confirmTitleEl = document.getElementById('practice-confirm-title');
    const confirmMessageEl = document.getElementById('practice-confirm-message');
    const confirmListEl = document.getElementById('practice-confirm-list');
    const confirmCancelBtn = document.getElementById('practice-confirm-cancel');
    const confirmContinueBtn = document.getElementById('practice-confirm-continue');
    let confirmResolver = null;

    function closeConfirmOverlay(result) {
        if (confirmOverlay) {
            confirmOverlay.classList.remove('is-visible');
            confirmOverlay.setAttribute('aria-hidden', 'true');
        }
        const resolve = confirmResolver;
        confirmResolver = null;
        if (typeof resolve === 'function') resolve(!!result);
    }

    function showConfirmOverlay({ title, message, items }) {
        return new Promise((resolve) => {
            if (!confirmOverlay) {
                resolve(window.confirm([message, ...(items || [])].filter(Boolean).join('\n')));
                return;
            }
            confirmResolver = resolve;
            if (confirmTitleEl) confirmTitleEl.textContent = title || 'Continue?';
            if (confirmMessageEl) confirmMessageEl.textContent = message || '';
            if (confirmListEl) {
                const list = Array.isArray(items) ? items.filter(Boolean) : [];
                confirmListEl.innerHTML = list
                    .map((item) => `<li>${escapeHtml(item)}</li>`)
                    .join('');
            }
            confirmOverlay.classList.add('is-visible');
            confirmOverlay.setAttribute('aria-hidden', 'false');
            confirmContinueBtn?.focus();
        });
    }

    if (confirmCancelBtn) {
        confirmCancelBtn.addEventListener('click', () => closeConfirmOverlay(false));
    }
    if (confirmContinueBtn) {
        confirmContinueBtn.addEventListener('click', () => closeConfirmOverlay(true));
    }
    if (confirmOverlay) {
        confirmOverlay.addEventListener('click', (e) => {
            if (e.target === confirmOverlay) closeConfirmOverlay(false);
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        if (!confirmOverlay?.classList.contains('is-visible')) return;
        closeConfirmOverlay(false);
    });

    async function confirmIfNeeded(data) {
        const needs = data.needs || [];
        if (needs.includes('drafts') && !confirmDrafts) {
            const drafts = data.skipped_drafts || [];
            const items = drafts.slice(0, 12).map((d) => {
                const where = d.problem_set
                    ? `${d.section || ''} / ${d.problem_set}`
                    : (d.section || '');
                const title = d.title || `Problem ${d.problem_id}`;
                const status = d.status || 'draft';
                return where
                    ? `${title} (${status}) — ${where}`
                    : `${title} (${status})`;
            });
            if (drafts.length > 12) items.push('…');
            const ok = await showConfirmOverlay({
                title: 'Incomplete problems will be skipped',
                message: 'Some problems are not complete and will be skipped from this practice test. Continue anyway?',
                items,
            });
            if (!ok) return false;
            confirmDrafts = true;
        }
        if (needs.includes('zero_sets') && !confirmZeroSets) {
            const sets = data.zero_count_sets || [];
            const items = sets.slice(0, 12).map((s) => {
                const note = s.note ? ` — ${s.note}` : '';
                return `${s.name || 'Problem set'} (${s.section || ''})${note}`;
            });
            if (sets.length > 12) items.push('…');
            const ok = await showConfirmOverlay({
                title: 'Some problem sets are not ready',
                message: 'Some problem sets will contribute no questions (suggested count is 0 or the pool is empty). Continue anyway?',
                items,
            });
            if (!ok) return false;
            confirmZeroSets = true;
        }
        return true;
    }

    async function fetchStart() {
        const response = await fetch(cfg.startUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({
                confirm_drafts: confirmDrafts,
                confirm_zero_sets: confirmZeroSets,
            }),
        });
        return response.json();
    }

    async function startPracticeTest() {
        setStatus('Assembling practice test…');
        if (gradeBtn) gradeBtn.disabled = true;
        if (gradingSection) gradingSection.hidden = true;
        lastGradePayload = null;
        problemsEl.innerHTML = '';

        try {
            let data = await fetchStart();
            while (data && data.needs_confirmation) {
                const ok = await confirmIfNeeded(data);
                if (!ok) {
                    setStatus('Practice test cancelled.');
                    return;
                }
                data = await fetchStart();
            }

            if (!data || data.success === false) {
                setStatus(data?.error || data?.message || 'Failed to start practice test.');
                return;
            }

            practiceProblems = Array.isArray(data.problems) ? data.problems : [];
            renderWarnings(data.skipped_drafts, data.zero_count_sets);

            if (!practiceProblems.length) {
                setStatus('No complete problems available for this practice test.');
                return;
            }

            const api = await waitForPreviewApi();
            setStatus(`Rendering ${practiceProblems.length} problem${practiceProblems.length === 1 ? '' : 's'}…`);

            practiceProblems.forEach((problem, idx) => {
                const slot = problem.slot_index || (idx + 1);
                const card = document.createElement('article');
                card.className = 'practice-problem-card';
                card.dataset.slotIndex = String(slot);
                card.dataset.problemId = String(problem.problem_id || '');

                const metaBits = [];
                if (problem.section_name) {
                    metaBits.push(`<span class="practice-problem-chip">${escapeHtml(problem.section_name)}</span>`);
                }
                if (problem.from_problem_set) {
                    metaBits.push(`<span class="practice-problem-chip">From set: ${escapeHtml(problem.from_problem_set)}</span>`);
                }

                card.innerHTML = `
                    <div class="practice-problem-meta">
                        <h3 class="practice-problem-title">${slot}. ${escapeHtml(problem.title || `Problem ${problem.problem_id}`)}</h3>
                        ${metaBits.join('')}
                    </div>
                    <div class="practice-preview-target" data-role="preview"></div>
                    <div class="practice-stub-host" data-role="stubs" aria-hidden="true"></div>
                `;
                problemsEl.appendChild(card);

                const previewTarget = card.querySelector('[data-role="preview"]');
                const stubHost = card.querySelector('[data-role="stubs"]');
                const segments = problem.loaded_segments || [];
                api.buildStubCards(stubHost, segments);
                api.renderPreview(previewTarget, problem.body_html || '<p><br></p>', {
                    cardScope: stubHost,
                    segmentMap: buildSegmentMap(segments),
                    latexByToken: buildLatexByToken(segments),
                    studentAnswers: {},
                    previewNamePrefix: `slot${slot}`,
                });
            });

            setStatus(`${practiceProblems.length} problem${practiceProblems.length === 1 ? '' : 's'} ready. Answer below, then grade.`);
            if (gradeBtn) gradeBtn.disabled = false;
        } catch (err) {
            console.error(err);
            setStatus(err.message || 'Failed to load practice test.');
        }
    }

    function tokensReferencedInHtml(bodyHtml) {
        const haystack = String(bodyHtml || '')
            .replace(/&lt;/gi, '<')
            .replace(/&gt;/gi, '>');
        const referenced = new Set();
        const regex = /<([a-zA-Z][a-zA-Z0-9_]*)>/g;
        let match;
        while ((match = regex.exec(haystack)) !== null) {
            if (match[1]) referenced.add(match[1]);
        }
        return referenced;
    }

    function collectGradePayload(api) {
        const cards = Array.from(problemsEl.querySelectorAll('.practice-problem-card'));
        return cards.map((card, idx) => {
            const problem = practiceProblems[idx] || {};
            const previewRoot = card.querySelector('[data-role="preview"]');
            const student_answers = api.captureAnswers(previewRoot);
            const referenced = tokensReferencedInHtml(problem.body_html || '');
            const entities = (problem.answer_fields || []).filter((field) => {
                const seq = String(field.sequence_token || '').trim();
                return seq && referenced.has(seq);
            });
            return {
                problem_id: problem.problem_id,
                slot_index: problem.slot_index || (idx + 1),
                title: problem.title,
                entities,
                all_entities: problem.all_entities || problem.loaded_segments || [],
                student_answers,
            };
        });
    }

    function renderGradeResults(data) {
        if (!gradingSection || !gradingResults || !gradingTotal) return;
        gradingSection.hidden = false;
        lastGradePayload = data;

        const scoredProblems = (data.problems || []).filter((p) => {
            const maxPts = Number(p.max);
            return Number.isFinite(maxPts) && maxPts > 0;
        });

        const rows = scoredProblems.map((p) => {
            const fields = (p.fields || []).map((f) => {
                const incomplete = !f.fully_correct;
                const expected = Array.isArray(f.expected_answers) ? f.expected_answers.filter(Boolean) : [];
                const multilineExpected = f.archetype === 'answersOrDne' || expected.length > 1;
                const expectedHtml = (incomplete && expected.length)
                    ? `<div class="practice-reveal-answers practice-expected-answers">
                            <div class="practice-answer-label">Expected</div>
                            ${formatExpectedListHtml(expected, { multiline: multilineExpected })}
                       </div>`
                    : '';
                const studentHtml = incomplete
                    ? `<div class="practice-reveal-answers practice-student-answers">
                            <div class="practice-answer-label">Your answer</div>
                            <div class="practice-answer-body">${formatStudentAnswerHtml(f)}</div>
                       </div>`
                    : '';
                const detail = f.detail
                    ? `<div class="practice-grade-field-meta">${escapeHtml(f.detail)}</div>`
                    : '';
                return `
                    <div class="practice-grade-field" data-fully-correct="${f.fully_correct ? '1' : '0'}">
                        <div>
                            <div>${escapeHtml(f.label || f.token || 'Field')}</div>
                            ${detail}
                            ${studentHtml}
                            ${expectedHtml}
                        </div>
                        <div style="font-weight:700; color:#166534; white-space:nowrap;">
                            ${formatGradeNumber(f.earned)} / ${formatGradeNumber(f.max)}
                        </div>
                    </div>
                `;
            }).join('');

            return `
                <div class="practice-grade-problem">
                    <div class="practice-grade-problem-header">
                        <strong>${escapeHtml(String(p.slot_index || ''))}. ${escapeHtml(p.title || `Problem ${p.problem_id}`)}</strong>
                        <span>${formatGradeNumber(p.earned)} / ${formatGradeNumber(p.max)}</span>
                    </div>
                    ${fields || '<div class="practice-grade-field-meta">No answer fields.</div>'}
                </div>
            `;
        }).join('');

        gradingResults.innerHTML = rows || '<p style="color:#94a3b8;">No scored problems to display.</p>';

        const visibleEarned = scoredProblems.reduce((sum, p) => sum + (Number(p.earned) || 0), 0);
        const visibleMax = scoredProblems.reduce((sum, p) => sum + (Number(p.max) || 0), 0);
        gradingTotal.innerHTML = `
            <span>Total</span>
            <span>${formatGradeNumber(visibleEarned)} / ${formatGradeNumber(visibleMax)}</span>
        `;

        applyExpectedVisibility();
        gradingSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function applyExpectedVisibility() {
        if (!gradingSection || !showExpectedCb) return;
        gradingSection.classList.toggle('show-expected', !!showExpectedCb.checked);
    }

    async function gradePracticeTest() {
        if (!practiceProblems.length) return;
        try {
            const api = await waitForPreviewApi();
            setStatus('Grading…');
            if (gradeBtn) gradeBtn.disabled = true;

            const problems = collectGradePayload(api);
            const response = await fetch(cfg.gradeUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken'),
                },
                body: JSON.stringify({ problems }),
            });
            const data = await response.json();
            if (!response.ok || data.success === false) {
                setStatus(data.error || 'Grading failed.');
                if (gradeBtn) gradeBtn.disabled = false;
                return;
            }
            renderGradeResults(data);
            setStatus('Graded. Generate a new instance to try different random values.');
            if (gradeBtn) gradeBtn.disabled = false;
        } catch (err) {
            console.error(err);
            setStatus(err.message || 'Grading failed.');
            if (gradeBtn) gradeBtn.disabled = false;
        }
    }

    if (showExpectedCb) {
        showExpectedCb.addEventListener('change', applyExpectedVisibility);
    }
    if (gradeBtn) {
        gradeBtn.addEventListener('click', gradePracticeTest);
    }
    if (reloadBtn) {
        reloadBtn.addEventListener('click', () => {
            confirmDrafts = true;
            confirmZeroSets = true;
            startPracticeTest();
        });
    }

    startPracticeTest();
});
