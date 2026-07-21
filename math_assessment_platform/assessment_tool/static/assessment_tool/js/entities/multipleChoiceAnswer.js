import { ensureLatexRenderBox } from './helpers.js';

/**
 * multipleChoiceAnswer — multi-option answer field with radio/checkbox preview
 * and all_or_nothing / practical / proportional grading.
 */
export function processEntity(contextData) {
    if (!contextData || !contextData.action) return null;

    switch (contextData.action) {
        case 'fieldsHtml':
            return getFieldsHtml(contextData.savedValues || {});
        case 'bindEvents':
            return bindEvents(contextData);
        case 'serialize':
            return serialize(contextData);
        case 'getOutputTypes':
            return ['content'];
        case 'isLinkCompatible':
            return isLinkCompatible(contextData);
        case 'hideRefreshButton':
            return false; // Show refresh so authors can re-shuffle preview option order
        case 'needsLatexRenderBox':
            return true;
        case 'applyBatchSync':
            return applyBatchSync(contextData);
        case 'renderPreviewToken':
            return renderPreviewToken(contextData);
        default:
            return null;
    }
}

function escapeHtmlAttr(val) {
    return String(val ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/**
 * Split option text into plain + LaTeX segments.
 * Supported wrappers (explicit only — not $...$):
 *   \( ... \)
 *   LATEX(...) / latex(...)  (balanced parentheses; case-insensitive "latex")
 */
function splitOptionContentWithLatex(raw) {
    const s = String(raw ?? '');
    const parts = [];
    if (!s) return parts;

    const tryParseLatexFnAt = (pos) => {
        if (pos > 0 && /[A-Za-z0-9_]/.test(s[pos - 1])) return null;
        const fnMatch = s.slice(pos).match(/^latex\s*\(/i);
        if (!fnMatch) return null;
        let depth = 1;
        let j = pos + fnMatch[0].length;
        while (j < s.length && depth > 0) {
            if (s[j] === '(') depth += 1;
            else if (s[j] === ')') depth -= 1;
            if (depth === 0) break;
            j += 1;
        }
        if (depth !== 0) return null;
        return { value: s.slice(pos + fnMatch[0].length, j), end: j + 1 };
    };

    const findNextMarker = (from) => {
        let best = -1;
        const inlineAt = s.indexOf('\\(', from);
        if (inlineAt !== -1) best = inlineAt;
        const re = /\blatex\s*\(/ig;
        re.lastIndex = from;
        const m = re.exec(s);
        if (m && (best === -1 || m.index < best)) best = m.index;
        return best;
    };

    let i = 0;
    while (i < s.length) {
        if (s.startsWith('\\(', i)) {
            const end = s.indexOf('\\)', i + 2);
            if (end !== -1) {
                parts.push({ type: 'latex', value: s.slice(i + 2, end) });
                i = end + 2;
                continue;
            }
        }

        const fn = tryParseLatexFnAt(i);
        if (fn) {
            parts.push({ type: 'latex', value: fn.value });
            i = fn.end;
            continue;
        }

        const next = findNextMarker(i + 1);
        if (next === -1 || next <= i) {
            parts.push({ type: 'text', value: s.slice(i) });
            break;
        }
        parts.push({ type: 'text', value: s.slice(i, next) });
        i = next;
    }

    return parts.filter((p) => p.value !== '' || p.type === 'latex');
}

/** HTML for a typed (non-linked) MC option, with optional explicit LaTeX wrappers. */
function renderTypedOptionContentHtml(content) {
    const parts = splitOptionContentWithLatex(content);
    const hasLatex = parts.some((p) => p.type === 'latex');
    if (!hasLatex) {
        return `<span>${escapeHtmlAttr(content || '')}</span>`;
    }
    return parts.map((p) => {
        if (p.type === 'latex') {
            return `<span class="mc-inline-latex preview-static-latex" style="display:inline-block; padding:0 1px;">${escapeHtmlAttr(p.value)}</span>`;
        }
        return `<span>${escapeHtmlAttr(p.value)}</span>`;
    }).join('');
}

const EMBEDDED_ENTITY_TOKEN_RE = /(?:&lt;|<)([A-Za-z][A-Za-z0-9_]*\d+)(?:&gt;|>)/g;

function resolveCardScope(ctx = {}) {
    if (ctx.cardScope && typeof ctx.cardScope.querySelectorAll === 'function') {
        return ctx.cardScope;
    }
    if (ctx.card && typeof ctx.card.closest === 'function') {
        const host = ctx.card.closest('.practice-stub-host');
        if (host) return host;
    }
    return document;
}

/**
 * Resolve a sequence token to a plain display string for inlining into choice text.
 * (Numbers / latex strings — not full preview widgets.)
 */
function resolveTokenPlainDisplay(cleanToken, ctx = {}) {
    const token = String(cleanToken || '').replace(/[<>]/g, '').trim();
    if (!token) return '';
    const baseArchetype = token.replace(/\d+$/, '');
    const scope = resolveCardScope(ctx);
    const srcCard = findSourceCard(token, scope);
    const cache = ctx.formulaLiveLatexCache || {};
    let displayVal = cache[token];
    const isServerValueValid = displayVal !== undefined && displayVal !== null && displayVal !== '' && displayVal !== '???';

    // Prefer locked server/stub values — never re-roll randoms for MC option text
    if (srcCard) {
        const simulated = srcCard.getAttribute('data-simulated-value');
        const latex = srcCard.getAttribute('data-latex-output');
        if (baseArchetype === 'graph' || baseArchetype === 'slopeFieldGraph') {
            displayVal = simulated || displayVal;
            if (displayVal && String(displayVal).trim().startsWith('{')) {
                displayVal = `[${baseArchetype}]`;
            }
        } else if (baseArchetype === 'formula' || baseArchetype === 'matrix' || baseArchetype === 'matrixResultByIndex') {
            if (!isServerValueValid) {
                displayVal = latex || simulated || token;
            }
        } else {
            // randInt / rand / etc.: locked simulated value wins
            if (simulated !== null && simulated !== undefined && simulated !== '' && simulated !== 'None' && simulated !== 'null') {
                displayVal = simulated;
            } else if (latex && latex !== '???' && latex !== '') {
                displayVal = latex;
            } else if (!isServerValueValid && typeof ctx.evaluateSingleCardOutput === 'function') {
                displayVal = ctx.evaluateSingleCardOutput(srcCard, token);
            }
        }
    } else if (baseArchetype === 'formula' || baseArchetype === 'matrix' || baseArchetype === 'matrixResultByIndex') {
        if (!isServerValueValid) {
            displayVal = token;
        }
    }

    if (!displayVal || displayVal === '???') {
        displayVal = token;
    }
    return String(displayVal);
}

/** Substitute embedded <randInt1>-style tokens, then apply LaTeX/plain rendering. */
function renderTypedOptionContentHtmlWithTokens(content, ctx = {}) {
    const raw = String(content ?? '');
    if (!EMBEDDED_ENTITY_TOKEN_RE.test(raw)) {
        // reset lastIndex after test()
        EMBEDDED_ENTITY_TOKEN_RE.lastIndex = 0;
        return renderTypedOptionContentHtml(raw);
    }
    EMBEDDED_ENTITY_TOKEN_RE.lastIndex = 0;
    const expanded = raw.replace(EMBEDDED_ENTITY_TOKEN_RE, (_match, seq) => (
        resolveTokenPlainDisplay(seq, ctx)
    ));
    return renderTypedOptionContentHtml(expanded);
}

function renderOptionLabelHtml(content, linkCtx = {}) {
    if (isLinkedContent(content)) {
        return renderLinkedOptionHtml(content, linkCtx);
    }
    return renderTypedOptionContentHtmlWithTokens(content, linkCtx);
}

function coerceBool(raw, defaultVal = false) {
    if (raw === undefined || raw === null) return defaultVal;
    if (typeof raw === 'boolean') return raw;
    if (raw === 1) return true;
    if (typeof raw === 'string') {
        return ['true', '1', 'yes', 'checked', 'on'].includes(raw.trim().toLowerCase());
    }
    return defaultVal;
}

function nextOptionId(existingIds) {
    let n = 1;
    const set = new Set(existingIds);
    while (set.has(`opt_${n}`)) n += 1;
    return `opt_${n}`;
}

function normalizeSavedOptions(savedValues) {
    let options = savedValues.options;
    if (typeof options === 'string') {
        try {
            options = JSON.parse(options);
        } catch (_) {
            options = null;
        }
    }
    if (!Array.isArray(options) || options.length < 2) {
        return [
            { id: 'opt_1', content: '', is_correct: false },
            { id: 'opt_2', content: '', is_correct: false }
        ];
    }
    return options.map((opt, i) => ({
        id: String(opt?.id || `opt_${i + 1}`),
        content: opt?.content != null ? String(opt.content) : '',
        is_correct: coerceBool(opt?.is_correct, false)
    }));
}

function isLinkedContent(content) {
    if (typeof content !== 'string') return false;
    const trimmed = content.trim()
        .replace(/&lt;/gi, '<')
        .replace(/&gt;/gi, '>');
    const match = trimmed.match(/^<([^<>]+)>$/);
    if (!match) return false;
    // Real sequence tokens look like archetype + index (formula1, randInt2).
    // Do NOT wrap arbitrary prose in <> first — that falsely marks it as linked
    // and sends it through KaTeX (spaces disappear in math mode).
    return /^[A-Za-z][A-Za-z0-9_]*\d+$/.test(match[1].trim());
}

function optionRowHtml(opt, forceRadio, soleCorrectId) {
    const linked = isLinkedContent(opt.content);
    const linkedToken = linked ? opt.content.trim() : '';
    const textValue = linked ? '' : escapeHtmlAttr(opt.content);
    const correctChecked = !!opt.is_correct;
    const disableCorrect = forceRadio && soleCorrectId && opt.id !== soleCorrectId;

    return `
        <div class="mc-option-row" data-option-id="${escapeHtmlAttr(opt.id)}" style="display:flex; align-items:flex-end; gap:6px; width:100%; box-sizing:border-box;">
            <label style="font-size:0.7rem; color:#166534; display:flex; flex-direction:column; gap:2px; flex-shrink:0; min-width:58px;">
                Correct
                <input type="checkbox" class="val-mc-option-correct" ${correctChecked ? 'checked' : ''} ${disableCorrect ? 'disabled' : ''} style="cursor:pointer; width:16px; height:16px;">
            </label>
            <div class="linked-input-wrapper" data-input-key="option_${escapeHtmlAttr(opt.id)}" data-input-type="text" ${linked ? `data-bound-token="${escapeHtmlAttr(linkedToken)}"` : ''} style="position:relative; display:flex; align-items:flex-end; gap:4px; flex-grow:1; min-width:0;">
                <label class="mc-option-text-label" style="font-size:0.75rem; color:#475569; flex-grow:1; ${linked ? 'display:none;' : ''}">Choice:
                    <input type="text" class="val-mc-option-content" value="${textValue}" ${linked ? 'disabled' : ''} placeholder="Text, \\(...\\), or &lt;entity&gt;…" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                ${linked ? `<span class="linked-token-pill" style="background:#f0fdf4; color:#166534; border:1px solid #bbf7d0; padding:4px 8px; border-radius:4px; font-family:monospace; font-weight:600; font-size:0.8rem; display:inline-block; width:100%; box-sizing:border-box; text-align:center;">${escapeHtmlAttr(linkedToken)}</span>` : ''}
                <button type="button" class="btn-input-link-trigger ${linked ? 'is-linked' : ''}" title="Link Dynamic Variable" style="background:#ffffff; border:1px solid ${linked ? '#fca5a5' : '#cbd5e1'}; border-radius:4px; color:${linked ? '#ef4444' : '#94a3b8'}; cursor:pointer; font-size:0.75rem; height:26px; width:26px; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
                    <i class="fas ${linked ? 'fa-times' : 'fa-link'}"></i>
                </button>
                <div class="linkable-tokens-dropdown" style="display:none; position:absolute; top:100%; left:0; background:white; border:1px solid #cbd5e1; border-radius:4px; box-shadow:0 4px 6px -1px rgb(0 0 0 / 0.1); z-index:50; min-width:140px; padding:4px 0; margin-top:2px;"></div>
            </div>
            <button type="button" class="btn-remove-mc-option" title="Remove choice" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem; padding:4px; flex-shrink:0;"><i class="fas fa-minus-circle"></i></button>
        </div>
    `;
}

function getFieldsHtml(savedValues) {
    const options = normalizeSavedOptions(savedValues);
    const randomize = coerceBool(savedValues.randomize_order, true);
    let forceRadio = coerceBool(savedValues.force_radio, true);
    const method = ['all_or_nothing', 'practical', 'proportional'].includes(savedValues.grading_method)
        ? savedValues.grading_method
        : 'all_or_nothing';

    const correctIds = options.filter(o => o.is_correct).map(o => o.id);
    const soleCorrectId = correctIds.length === 1 ? correctIds[0] : null;
    if (correctIds.length !== 1) forceRadio = false;
    else if (savedValues.force_radio === undefined) forceRadio = true;

    const showRadioToggle = correctIds.length === 1;

    return `
        <div class="mc-answer-fields" style="display:flex; flex-direction:column; gap:10px; width:100%; box-sizing:border-box;">
            <label style="font-size:0.75rem; color:#475569; font-weight:500; display:inline-flex; align-items:center; gap:6px; cursor:pointer; margin:0;">
                <input type="checkbox" class="val-mc-randomize" ${randomize ? 'checked' : ''} style="cursor:pointer;">
                Randomize answer order
            </label>

            <div class="linked-input-wrapper" data-input-key="grading_method" data-input-type="dropdown" style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:0.75rem; color:#475569; font-weight:500;">Grading method:
                    <select class="val-mc-grading-method" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                        <option value="all_or_nothing" ${method === 'all_or_nothing' ? 'selected' : ''}>All or nothing</option>
                        <option value="practical" ${method === 'practical' ? 'selected' : ''}>Practical</option>
                        <option value="proportional" ${method === 'proportional' ? 'selected' : ''}>Proportional</option>
                    </select>
                </label>
            </div>

            <div class="mc-force-radio-wrap" style="display:${showRadioToggle ? 'block' : 'none'};">
                <label style="font-size:0.75rem; color:#475569; font-weight:500; display:inline-flex; align-items:center; gap:6px; cursor:pointer; margin:0;">
                    <input type="checkbox" class="val-mc-force-radio" ${forceRadio ? 'checked' : ''} style="cursor:pointer;">
                    Display as radio buttons
                </label>
                <div style="font-size:0.65rem; color:#94a3b8; margin-top:2px;">Single correct answer — turn off to mark more answers correct.</div>
            </div>

            <div class="mc-zero-correct-note" style="display:${correctIds.length === 0 ? 'block' : 'none'}; font-size:0.72rem; color:#b45309; background:#fffbeb; border:1px solid #fcd34d; border-radius:4px; padding:6px 8px; line-height:1.35;">
                No choices are marked correct. Students must leave all answers unchecked to earn full points.
                Display as radio buttons is unavailable here because a radio selection cannot be cleared.
            </div>

            <div class="mc-options-container" style="display:flex; flex-direction:column; gap:8px; width:100%;">
                <span style="font-size:0.75rem; font-weight:600; color:#475569;">Choices:</span>
                ${options.map(opt => optionRowHtml(opt, forceRadio && showRadioToggle, soleCorrectId)).join('')}
            </div>
            <button type="button" class="btn-add-mc-option" style="align-self:flex-start; background:#f1f5f9; border:1px dashed #cbd5e1; border-radius:4px; color:#475569; font-size:0.72rem; padding:3px 8px; cursor:pointer;">
                <i class="fas fa-plus"></i> Add row
            </button>
        </div>
    `;
}

function collectOptionIds(card) {
    return Array.from(card.querySelectorAll('.mc-option-row'))
        .map(row => row.getAttribute('data-option-id'))
        .filter(Boolean);
}

function syncZeroCorrectNote(card) {
    const noteEl = card.querySelector('.mc-zero-correct-note');
    if (!noteEl) return;
    const checkedCount = card.querySelectorAll('.val-mc-option-correct:checked').length;
    noteEl.style.display = checkedCount === 0 ? 'block' : 'none';
}

function syncRadioCorrectLocks(card) {
    const forceWrap = card.querySelector('.mc-force-radio-wrap');
    const forceCheckbox = card.querySelector('.val-mc-force-radio');
    const correctBoxes = Array.from(card.querySelectorAll('.val-mc-option-correct'));
    const checked = correctBoxes.filter(cb => cb.checked);
    const soleId = checked.length === 1
        ? checked[0].closest('.mc-option-row')?.getAttribute('data-option-id')
        : null;

    syncZeroCorrectNote(card);

    if (forceWrap) {
        // Radio mode only when exactly one correct — not with zero (cannot uncheck a radio).
        forceWrap.style.display = checked.length === 1 ? 'block' : 'none';
    }

    if (checked.length !== 1) {
        if (forceCheckbox) forceCheckbox.checked = false;
        correctBoxes.forEach(cb => {
            cb.disabled = false;
            cb.title = '';
        });
        return;
    }

    // Exactly one correct: show radio toggle; default on when newly sole
    if (forceCheckbox && forceWrap?.dataset.mcWasSole !== '1') {
        forceCheckbox.checked = true;
    }
    if (forceWrap) forceWrap.dataset.mcWasSole = '1';

    const forceOn = !!forceCheckbox?.checked;
    correctBoxes.forEach(cb => {
        const rowId = cb.closest('.mc-option-row')?.getAttribute('data-option-id');
        const locked = forceOn && rowId !== soleId;
        cb.disabled = locked;
        cb.title = locked
            ? 'Turn off “Display as radio buttons” (or click to unlock) to mark more answers correct'
            : '';
    });
}

function bindEvents({ card, updateWorkspaceSimulationPreview }) {
    if (!card) return null;
    if (card.dataset.mcBound === '1') return true;
    card.dataset.mcBound = '1';

    const container = card.querySelector('.mc-options-container');
    const addBtn = card.querySelector('.btn-add-mc-option');
    const forceWrap = card.querySelector('.mc-force-radio-wrap');
    if (forceWrap && card.querySelectorAll('.val-mc-option-correct:checked').length === 1) {
        forceWrap.dataset.mcWasSole = '1';
    }

    const refresh = () => {
        syncRadioCorrectLocks(card);
        if (typeof updateWorkspaceSimulationPreview === 'function') {
            updateWorkspaceSimulationPreview();
        }
    };

    addBtn?.addEventListener('click', () => {
        const ids = collectOptionIds(card);
        const id = nextOptionId(ids);
        const forceOn = !!card.querySelector('.val-mc-force-radio')?.checked
            && card.querySelectorAll('.val-mc-option-correct:checked').length === 1;
        const soleId = forceOn
            ? card.querySelector('.val-mc-option-correct:checked')?.closest('.mc-option-row')?.getAttribute('data-option-id')
            : null;
        const wrap = document.createElement('div');
        wrap.innerHTML = optionRowHtml({ id, content: '', is_correct: false }, forceOn, soleId);
        const row = wrap.firstElementChild;
        container?.appendChild(row);
        refresh();
    });

    card.addEventListener('click', (e) => {
        const removeBtn = e.target.closest('.btn-remove-mc-option');
        if (removeBtn && card.contains(removeBtn)) {
            const rows = card.querySelectorAll('.mc-option-row');
            if (rows.length <= 2) {
                alert('Multiple choice requires at least 2 choices.');
                return;
            }
            removeBtn.closest('.mc-option-row')?.remove();
            refresh();
            return;
        }

        // Locked Correct boxes are disabled under radio mode — clicking unlocks
        // multi-correct editing instead of silently doing nothing.
        const optionRow = e.target.closest('.mc-option-row');
        const lockedCorrect = optionRow
            ? (
                e.target.closest('.val-mc-option-correct')
                || (e.target.closest('label')?.querySelector('.val-mc-option-correct') || null)
            )
            : null;
        if (lockedCorrect && card.contains(lockedCorrect) && lockedCorrect.disabled) {
            e.preventDefault();
            const forceCheckbox = card.querySelector('.val-mc-force-radio');
            if (forceCheckbox) forceCheckbox.checked = false;
            if (forceWrap) forceWrap.dataset.mcWasSole = '0';
            lockedCorrect.disabled = false;
            lockedCorrect.checked = true;
            refresh();
        }
    });

    card.addEventListener('change', (e) => {
        if (!card.contains(e.target)) return;
        if (e.target.classList.contains('val-mc-option-correct')) {
            const forceCheckbox = card.querySelector('.val-mc-force-radio');
            const checked = card.querySelectorAll('.val-mc-option-correct:checked');
            if (checked.length === 1 && forceWrap) {
                // Newly became sole correct — default radio on
                if (forceWrap.dataset.mcWasSole !== '1' && forceCheckbox) {
                    forceCheckbox.checked = true;
                }
            } else if (forceWrap) {
                forceWrap.dataset.mcWasSole = '0';
            }
            refresh();
            return;
        }
        if (e.target.classList.contains('val-mc-force-radio')) {
            refresh();
            return;
        }
        if (
            e.target.classList.contains('val-mc-randomize')
            || e.target.classList.contains('val-mc-grading-method')
            || e.target.classList.contains('val-mc-option-content')
        ) {
            if (typeof updateWorkspaceSimulationPreview === 'function') {
                updateWorkspaceSimulationPreview();
            }
        }
    });

    card.addEventListener('input', (e) => {
        if (e.target.classList.contains('val-mc-option-content')) {
            if (typeof updateWorkspaceSimulationPreview === 'function') {
                updateWorkspaceSimulationPreview();
            }
        }
    });

    syncRadioCorrectLocks(card);
    return true;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    inputsCollected.randomize_order = !!card.querySelector('.val-mc-randomize')?.checked;
    inputsCollected.grading_method = card.querySelector('.val-mc-grading-method')?.value || 'all_or_nothing';

    const options = [];
    card.querySelectorAll('.mc-option-row').forEach((row) => {
        let id = row.getAttribute('data-option-id') || '';
        if (!id) {
            id = nextOptionId(options.map(o => o.id));
            row.setAttribute('data-option-id', id);
        }
        const wrapper = row.querySelector('.linked-input-wrapper');
        let content = '';
        const bound = wrapper?.getAttribute('data-bound-token');
        if (bound) {
            let cleanToken = bound.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
            if (!cleanToken.startsWith('<')) cleanToken = `<${cleanToken}`;
            if (!cleanToken.endsWith('>')) cleanToken = `${cleanToken}>`;
            content = cleanToken;
        } else {
            content = String(row.querySelector('.val-mc-option-content')?.value || '').trim();
        }
        const correctBox = row.querySelector('.val-mc-option-correct');
        // .checked still works for disabled (sole-correct radio lock) boxes
        const isCorrect = !!(correctBox && correctBox.checked);
        options.push({
            id,
            content,
            is_correct: isCorrect
        });
        row.setAttribute('data-is-correct', isCorrect ? '1' : '0');
    });
    inputsCollected.options = options;

    const correctCount = options.filter(o => o.is_correct).length;
    // Radio mode only applies with exactly one keyed correct answer
    inputsCollected.force_radio = correctCount === 1
        && !!card.querySelector('.val-mc-force-radio')?.checked;

    // Drop per-row keys from universal extractor so payload stays clean
    Object.keys(inputsCollected).forEach((key) => {
        if (key.startsWith('option_')) delete inputsCollected[key];
    });

    return inputsCollected;
}

function isLinkCompatible({ inputKey }) {
    if (inputKey && String(inputKey).startsWith('option_')) return true;
    return null;
}

function applyBatchSync(contextData = {}) {
    const { card, result, formulaLiveLatexCache, renderGraphComponentCanvas, renderSlopeFieldCanvas, getEntityInformation, evaluateSingleCardOutput } = contextData;
    if (!card || !result) return null;
    const targetDisplay = ensureLatexRenderBox(card);
    if (!targetDisplay) return true;

    targetDisplay.style.textAlign = 'left';
    targetDisplay.style.fontSize = '0.85rem';
    targetDisplay.style.fontWeight = '600';
    targetDisplay.style.color = '#0f172a';
    targetDisplay.style.whiteSpace = 'normal';

    const out = result.evaluated_output;
    if (out && (String(out).startsWith('[Invalid') || String(out).startsWith('⚠️'))) {
        targetDisplay.textContent = '';
        return true;
    }

    const collected = {};
    serialize({ card, inputsCollected: collected });
    const options = Array.isArray(collected.options) ? collected.options : [];
    const correct = options.filter((o) => o && o.is_correct);

    if (!correct.length) {
        targetDisplay.textContent = '(none — leave all unchecked)';
        targetDisplay.style.fontStyle = 'italic';
        targetDisplay.style.color = '#64748b';
        targetDisplay.style.fontWeight = '500';
        return true;
    }

    targetDisplay.style.fontStyle = '';
    targetDisplay.style.color = '#0f172a';
    targetDisplay.style.fontWeight = '600';

    const linkCtx = {
        getEntityInformation,
        evaluateSingleCardOutput,
        formulaLiveLatexCache: formulaLiveLatexCache || {},
        renderGraphComponentCanvas,
        renderSlopeFieldCanvas,
        registerPreviewGraph: null
    };

    const pendingGraphs = [];
    if (typeof renderGraphComponentCanvas === 'function' || typeof renderSlopeFieldCanvas === 'function') {
        linkCtx.registerPreviewGraph = (job) => {
            if (job) pendingGraphs.push(job);
        };
    }

    const rowsHtml = correct.map((opt) => {
        const content = opt.content || '';
        const labelHtml = renderOptionLabelHtml(content, linkCtx);
        return `<div class="mc-correct-answer-row" style="margin:2px 0; line-height:1.35;">${labelHtml}</div>`;
    }).join('');

    targetDisplay.innerHTML = rowsHtml;

    if (typeof katex !== 'undefined') {
        targetDisplay.querySelectorAll('.simulated-math-formula-render').forEach((span) => {
            try {
                const expression = (span.textContent || '').trim();
                if (expression) {
                    katex.render(expression, span, { displayMode: false, throwOnError: false });
                }
            } catch (_) { /* keep text fallback */ }
        });
        // Some entity previews leave raw latex on the row itself
        targetDisplay.querySelectorAll('.preview-static-latex').forEach((span) => {
            try {
                katex.render((span.textContent || '').trim(), span, { displayMode: false, throwOnError: false });
            } catch (_) { /* keep text fallback */ }
        });
    }

    pendingGraphs.forEach((job) => {
        if (!job || !job.canvasId || !job.graphConfig) return;
        const canvasEl = document.getElementById(job.canvasId);
        if (!canvasEl) return;
        const width = Number(job.width) > 0 ? Math.round(job.width) : 220;
        const height = Number(job.height) > 0 ? Math.round(job.height) : Math.max(100, Math.round(width * (240 / 340)));
        try {
            if (job.kind === 'slopeFieldGraph' || job.graphConfig?.archetype === 'slopeFieldGraph') {
                if (typeof renderSlopeFieldCanvas === 'function') {
                    renderSlopeFieldCanvas(canvasEl, job.graphConfig, {
                        mode: 'author',
                        width,
                        height
                    });
                }
            } else if (typeof renderGraphComponentCanvas === 'function') {
                renderGraphComponentCanvas(job.canvasId, job.graphConfig, { width, height });
            }
        } catch (err) {
            console.warn('Failed rendering linked MC correct-answer graph in latex box:', err);
        }
    });

    return true;
}

function shuffleCopySeeded(arr, seedStr) {
    const a = arr.slice();
    let h = 2166136261 >>> 0;
    const s = String(seedStr ?? '0');
    for (let i = 0; i < s.length; i += 1) {
        h ^= s.charCodeAt(i);
        h = Math.imul(h, 16777619);
    }
    // mulberry32
    let state = h >>> 0;
    const rand = () => {
        state = (state + 0x6D2B79F5) >>> 0;
        let t = state;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    for (let i = a.length - 1; i > 0; i -= 1) {
        const j = Math.floor(rand() * (i + 1));
        [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
}

function normalizeBoundToken(raw) {
    if (raw == null) return '';
    let clean = String(raw).replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
    if (!clean) return '';
    if (!clean.startsWith('<')) clean = `<${clean}`;
    if (!clean.endsWith('>')) clean = `${clean}>`;
    return clean;
}

function findSourceCard(sequenceToken, scopeRoot = null) {
    const clean = String(sequenceToken || '').replace(/[<>]/g, '').trim();
    if (!clean) return null;
    const root = scopeRoot && typeof scopeRoot.querySelectorAll === 'function'
        ? scopeRoot
        : document;
    // Prefer non-practice cards when searching the whole document (workspace overlay),
    // but allow practice stubs when scoped to a stub host.
    const deleteBtns = root.querySelectorAll('.btn-delete-workspace-component');
    for (const btn of deleteBtns) {
        if (btn.getAttribute('data-indexed-token') !== clean) continue;
        const card = btn.closest('.workspace-block-card, .workspace-component-card');
        if (!card) continue;
        if (root === document && card.classList.contains('practice-stub-card')) {
            continue;
        }
        return card;
    }
    // Fallback: allow practice stubs when an unscoped search found nothing else
    if (root === document) {
        for (const btn of deleteBtns) {
            if (btn.getAttribute('data-indexed-token') === clean) {
                return btn.closest('.workspace-block-card, .workspace-component-card');
            }
        }
    }
    return null;
}

/**
 * Build the same preview markup Dynamic Variables use when substituted in the canvas.
 * Uses only inline-safe math when possible; block widgets (graph) are nested later
 * inside flow-content option rows (divs), never inside <label>/<span>/<p>.
 */
function renderLinkedOptionHtml(content, ctx) {
    const bound = normalizeBoundToken(content);
    if (!isLinkedContent(bound)) {
        return `<span>${escapeHtmlAttr(content || '')}</span>`;
    }

    const cleanToken = bound.replace(/[<>]/g, '').trim();
    const baseArchetype = cleanToken.replace(/\d+$/, '');
    const scope = resolveCardScope(ctx);
    const srcCard = findSourceCard(cleanToken, scope);
    const cache = ctx.formulaLiveLatexCache || {};
    let displayVal = cache[cleanToken];

    const isServerValueValid = displayVal !== undefined && displayVal !== null && displayVal !== '' && displayVal !== '???';

    if (baseArchetype === 'graph' || baseArchetype === 'slopeFieldGraph') {
        if (srcCard) {
            displayVal = srcCard.getAttribute('data-simulated-value')
                || (typeof ctx.evaluateSingleCardOutput === 'function'
                    ? ctx.evaluateSingleCardOutput(srcCard, cleanToken)
                    : null);
        }
    } else if (baseArchetype === 'formula' || baseArchetype === 'matrix' || baseArchetype === 'matrixResultByIndex') {
        if (!isServerValueValid && srcCard) {
            displayVal = srcCard.getAttribute('data-latex-output')
                || srcCard.getAttribute('data-simulated-value')
                || cleanToken;
        } else if (!isServerValueValid) {
            displayVal = cleanToken;
        }
    } else if (srcCard) {
        const simulated = srcCard.getAttribute('data-simulated-value');
        const loadedLatex = srcCard.getAttribute('data-latex-output') || formulaLiveSafe(cache, cleanToken);
        if (simulated !== null && simulated !== undefined && simulated !== '' && simulated !== 'None' && simulated !== 'null') {
            displayVal = simulated;
        } else if (loadedLatex && loadedLatex !== '???' && loadedLatex !== '') {
            displayVal = loadedLatex;
        } else if (typeof ctx.evaluateSingleCardOutput === 'function') {
            displayVal = ctx.evaluateSingleCardOutput(srcCard, cleanToken);
        } else {
            displayVal = cleanToken;
        }
    }

    if (!displayVal || displayVal === '???') {
        displayVal = cleanToken;
    }

    if (typeof ctx.getEntityInformation === 'function') {
        const previewHtml = ctx.getEntityInformation(baseArchetype, {
            action: 'renderPreviewToken',
            displayVal,
            cleanToken,
            card: srcCard,
            renderGraphComponentCanvas: ctx.renderGraphComponentCanvas,
            renderSlopeFieldCanvas: ctx.renderSlopeFieldCanvas,
            previewInstanceId: `mc-opt-${cleanToken}-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
            registerPreviewGraph: ctx.registerPreviewGraph,
            // Compact sizing hint for graphs embedded as MC choices
            sizeOptions: baseArchetype === 'graph' || baseArchetype === 'slopeFieldGraph'
                ? { width: 280, height: 180 }
                : undefined
        });
        if (previewHtml) return previewHtml;
    }

    // Fallback: KaTeX-friendly math span or plain text (always escaped)
    return `<span class="simulated-math-formula-render" style="display:inline-block; padding:0 2px;">${escapeHtmlAttr(displayVal)}</span>`;
}

function formulaLiveSafe(cache, token) {
    return cache && cache[token];
}

function renderPreviewToken(contextData = {}) {
    const {
        cleanToken,
        card,
        initialValue,
        getEntityInformation,
        evaluateSingleCardOutput,
        formulaLiveLatexCache,
        renderGraphComponentCanvas,
        renderSlopeFieldCanvas,
        registerPreviewGraph,
        previewNamePrefix
    } = contextData;

    const token = cleanToken || '';
    let options = [];
    let randomize = true;
    let forceRadio = true;
    if (card) {
        const collected = {};
        serialize({ card, inputsCollected: collected });
        options = Array.isArray(collected.options) ? collected.options : [];
        randomize = !!collected.randomize_order;
        forceRadio = !!collected.force_radio;
    }

    const correctCount = options.filter(o => o.is_correct).length;
    const useRadio = forceRadio && correctCount === 1;

    const linkCtx = {
        getEntityInformation,
        evaluateSingleCardOutput,
        formulaLiveLatexCache,
        renderGraphComponentCanvas,
        renderSlopeFieldCanvas,
        registerPreviewGraph,
        card,
        cardScope: contextData.cardScope || (card && card.closest && card.closest('.practice-stub-host')) || null,
    };

    let displayOptions = options.map(o => ({
        id: o.id,
        labelHtml: renderOptionLabelHtml(o.content || o.id, linkCtx)
    }));
    // Stable shuffle from card seed — re-randomized only when seed changes
    // (overlay card create / refresh icon), not on every preview redraw.
    if (randomize && displayOptions.length > 1) {
        const seed = (card && card.getAttribute('data-shuffle-seed'))
            || `${token}-default`;
        displayOptions = shuffleCopySeeded(displayOptions, seed);
    }

    let selected = [];
    if (initialValue && typeof initialValue === 'object' && Array.isArray(initialValue.selected)) {
        selected = initialValue.selected.map(String);
    } else if (Array.isArray(initialValue)) {
        selected = initialValue.map(String);
    }

    const ns = previewNamePrefix ? `${previewNamePrefix}-` : '';
    const name = `preview-mc-${ns}${token}`;
    // Use <div> (flow content) throughout — never <span>/<label> wrappers — so
    // nested graph/slope <div> widgets cannot break out of phrasing containers
    // and orphan later choices.
    const rows = displayOptions.map((opt) => {
        const isSel = selected.includes(opt.id);
        const inputType = useRadio ? 'radio' : 'checkbox';
        const inputName = useRadio ? name : `${name}__${opt.id}`;
        return `
            <div class="mc-option-preview-row" data-option-id="${escapeHtmlAttr(opt.id)}" style="display:flex; align-items:flex-start; gap:6px; font-size:0.85rem; color:#0f172a; margin:4px 0; cursor:pointer;">
                <input type="${inputType}" class="preview-mc-choice" name="${escapeHtmlAttr(inputName)}" value="${escapeHtmlAttr(opt.id)}" data-token="${escapeHtmlAttr(token)}" data-option-id="${escapeHtmlAttr(opt.id)}" ${isSel ? 'checked' : ''} style="margin-top:4px; flex-shrink:0;">
                <div class="mc-option-preview-label" style="min-width:0; flex:1;">${opt.labelHtml}</div>
            </div>
        `;
    }).join('');

    return `
        <div class="simulated-mc-wrapper" data-token="${escapeHtmlAttr(token)}" style="display:block; vertical-align:middle; margin:8px 0; max-width:420px; text-align:left; line-height:1.3;">
            ${rows
                ? `<div class="mc-options-list" style="display:flex; flex-direction:column; gap:2px;">${rows}</div>`
                : '<div style="color:#94a3b8; font-size:0.8rem;">No choices configured</div>'}
        </div>
    `;
}
