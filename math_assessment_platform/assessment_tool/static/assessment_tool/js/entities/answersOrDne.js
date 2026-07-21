import { ensureLatexRenderBox } from './helpers.js';

/**
 * answersOrDne — one-or-more linked answer keys OR author DNE.
 * Student preview: Add answer (formula/string | coordinates | number) or DNE.
 */

const ALLOWED_KEY_TYPES = ['shortAnswer', 'arrayMatchingUnordered', 'numAnswer', 'formula'];
const STUDENT_ENTRY_TYPES = ['shortAnswer', 'arrayMatchingUnordered', 'numAnswer'];

const TYPE_LABELS = {
    shortAnswer: 'formula/string',
    arrayMatchingUnordered: 'coordinates',
    numAnswer: 'number',
};

function findWorkspaceCardByToken(sequenceToken) {
    const clean = String(sequenceToken || '').replace(/[<>]/g, '').trim();
    if (!clean) return null;
    const deleteBtns = document.querySelectorAll('.btn-delete-workspace-component');
    for (const btn of deleteBtns) {
        if (btn.getAttribute('data-indexed-token') === clean) {
            return btn.closest('.workspace-block-card, .workspace-component-card');
        }
    }
    return null;
}

function isFormulaSimplifyEligible(sourceCard) {
    if (!sourceCard) return false;
    const method = sourceCard.querySelector('.val-input-solve-method')?.value || '';
    const target = (sourceCard.querySelector('.val-input-simplify-target')?.value || '').trim();
    if (method !== 'simplify') return false;
    if (!target || target === '-- N/A --' || target === '-- choose variable --') return false;
    return true;
}

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
            return true;
        case 'needsLatexRenderBox':
            return true;
        case 'applyBatchSync':
            return applyBatchSync(contextData);
        case 'renderPreviewToken':
            return renderPreviewToken(contextData);
        case 'mountPreviewAnswersOrDne':
            return mountPreviewAnswersOrDne(contextData);
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

function coerceBool(raw, defaultVal = false) {
    if (raw === true || raw === 1) return true;
    if (raw === false || raw === 0) return false;
    if (typeof raw === 'string') {
        return ['true', '1', 'yes', 'checked', 'on'].includes(raw.trim().toLowerCase());
    }
    return defaultVal;
}

function normalizeAnswers(savedValues) {
    let raw = savedValues?.answers;
    if (typeof raw === 'string') {
        const s = raw.trim();
        if (!s) return [];
        if (s.startsWith('[')) {
            try {
                raw = JSON.parse(s);
            } catch (_) {
                return /^<[^>]+>$/.test(s) ? [s] : [];
            }
        } else if (/^<[^>]+>$/.test(s)) {
            return [s];
        } else {
            return [];
        }
    }
    if (!Array.isArray(raw)) return [];
    return raw.map((item) => {
        let tok = typeof item === 'string' ? item : (item?.token || item?.value || '');
        tok = String(tok).replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
        if (!tok) return '';
        if (!tok.startsWith('<')) tok = `<${tok}`;
        if (!tok.endsWith('>')) tok = `${tok}>`;
        return /^<[^>]+>$/.test(tok) ? tok : '';
    }).filter(Boolean);
}

function keyRowHtml(token, index) {
    const linked = typeof token === 'string' && /^<[^>]+>$/.test(token.trim());
    const display = linked ? token.replace(/[<>]/g, '') : '';
    return `
        <div class="answers-or-dne-key-row linked-input-wrapper" data-input-key="aod_answer_${index}" data-input-type="entity" data-row-index="${index}" ${linked ? `data-bound-token="${escapeHtmlAttr(token.trim())}"` : ''} style="position:relative; display:flex; align-items:center; gap:8px; width:100%; box-sizing:border-box; background:#f8fafc; padding:6px 8px; border-radius:4px; border:1px dashed #cbd5e1;">
            <div style="display:flex; flex-direction:column; min-width:0; flex-grow:1;">
                <span style="font-size:0.72rem; font-weight:600; color:#334155;">Answer key</span>
                <span class="link-status-text" style="font-size:0.72rem; color:${linked ? '#0284c7' : '#94a3b8'}; font-family:monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    ${linked ? `Linked to: ${escapeHtmlAttr(display)}` : 'Link shortAnswer / coordinates / numAnswer / simplify-formula'}
                </span>
            </div>
            ${linked ? `<span class="linked-token-pill" style="background:#f0fdf4; color:#166534; border:1px solid #bbf7d0; padding:4px 8px; border-radius:4px; font-family:monospace; font-weight:600; font-size:0.75rem;">${escapeHtmlAttr(token.trim())}</span>` : ''}
            <button type="button" class="btn-input-link-trigger ${linked ? 'is-linked' : ''}" title="Link answer key" style="background:#fff; border:1px solid ${linked ? '#fca5a5' : '#cbd5e1'}; border-radius:4px; color:${linked ? '#ef4444' : '#94a3b8'}; cursor:pointer; font-size:0.75rem; height:26px; width:26px; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
                <i class="fas ${linked ? 'fa-times' : 'fa-link'}"></i>
            </button>
            <div class="linkable-tokens-dropdown" style="display:none; position:absolute; top:100%; left:0; background:white; border:1px solid #cbd5e1; border-radius:4px; box-shadow:0 4px 6px -1px rgb(0 0 0 / 0.1); z-index:50; min-width:140px; padding:4px 0; margin-top:2px;"></div>
            <button type="button" class="btn-remove-aod-key" title="Remove key" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem; padding:4px; flex-shrink:0;"><i class="fas fa-minus-circle"></i></button>
        </div>
    `;
}

function getFieldsHtml(savedValues) {
    let dne = coerceBool(savedValues.correct_is_dne, false);
    let answers = normalizeAnswers(savedValues);
    if (dne) answers = [];
    if (answers.length > 0) dne = false;
    const mode = savedValues.grading_mode === 'per_answer' ? 'per_answer' : 'all_or_nothing';

    return `
        <div class="answers-or-dne-fields" style="display:flex; flex-direction:column; gap:10px; width:100%; box-sizing:border-box;">
            <div class="linked-input-wrapper" data-input-key="correct_is_dne" data-input-type="checkbox" style="display:flex; align-items:center; gap:8px;">
                <label style="font-size:0.75rem; color:#475569; font-weight:500; display:inline-flex; align-items:center; gap:6px; cursor:pointer; margin:0;">
                    <input type="checkbox" class="val-aod-dne" ${dne ? 'checked' : ''} style="cursor:pointer;">
                    Correct answer is DNE
                </label>
            </div>

            <div class="linked-input-wrapper" data-input-key="grading_mode" data-input-type="dropdown" style="display:flex; flex-direction:column; gap:4px;">
                <label style="font-size:0.75rem; color:#475569; font-weight:500;">Grading method:
                    <select class="val-aod-grading-mode" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                        <option value="all_or_nothing" ${mode === 'all_or_nothing' ? 'selected' : ''}>All or nothing</option>
                        <option value="per_answer" ${mode === 'per_answer' ? 'selected' : ''}>Split points per correct answer</option>
                    </select>
                </label>
            </div>

            <div class="aod-keys-section" style="display:${dne ? 'none' : 'flex'}; flex-direction:column; gap:8px; width:100%;">
                <span style="font-size:0.75rem; font-weight:600; color:#475569;">Answer keys (link one per row):</span>
                <div class="aod-keys-container" style="display:flex; flex-direction:column; gap:8px; width:100%;">
                    ${answers.map((tok, i) => keyRowHtml(tok, i)).join('')}
                </div>
                <button type="button" class="btn-add-aod-key" style="align-self:flex-start; background:#f1f5f9; border:1px dashed #cbd5e1; border-radius:4px; color:#475569; font-size:0.72rem; padding:3px 8px; cursor:pointer;">
                    <i class="fas fa-plus"></i> Add answer key
                </button>
            </div>
        </div>
    `;
}

function reindexKeyRows(card) {
    card.querySelectorAll('.answers-or-dne-key-row').forEach((row, i) => {
        row.setAttribute('data-row-index', String(i));
        row.setAttribute('data-input-key', `aod_answer_${i}`);
    });
}

function clearAllKeyLinks(card) {
    const container = card.querySelector('.aod-keys-container');
    if (container) container.innerHTML = '';
}

function syncDneUi(card) {
    const dneCb = card.querySelector('.val-aod-dne');
    const section = card.querySelector('.aod-keys-section');
    const hasLinks = !!card.querySelector('.answers-or-dne-key-row[data-bound-token]');
    if (hasLinks && dneCb?.checked) {
        dneCb.checked = false;
    }
    if (section) {
        section.style.display = dneCb?.checked ? 'none' : 'flex';
    }
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    inputsCollected.correct_is_dne = !!card.querySelector('.val-aod-dne')?.checked;
    const modeSel = card.querySelector('.val-aod-grading-mode');
    inputsCollected.grading_mode = modeSel?.value === 'per_answer' ? 'per_answer' : 'all_or_nothing';

    const answers = [];
    if (!inputsCollected.correct_is_dne) {
        card.querySelectorAll('.answers-or-dne-key-row').forEach((row) => {
            let tok = row.getAttribute('data-bound-token') || '';
            tok = tok.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
            if (!tok) return;
            if (!tok.startsWith('<')) tok = `<${tok}`;
            if (!tok.endsWith('>')) tok = `${tok}>`;
            if (/^<[^>]+>$/.test(tok)) answers.push(tok);
        });
    }
    inputsCollected.answers = answers;

    // Drop transient per-row keys from universal extractor
    Object.keys(inputsCollected).forEach((k) => {
        if (/^aod_answer_\d+$/.test(k)) delete inputsCollected[k];
    });
    return inputsCollected;
}

function bindEvents({ card, updateWorkspaceSimulationPreview, dispatchWorkspaceBatchSync }) {
    if (!card || card.dataset.aodBound === '1') return true;
    card.dataset.aodBound = '1';

    const bump = () => {
        const probe = card.querySelector('.val-aod-dne') || card;
        probe.dispatchEvent(new Event('input', { bubbles: true }));
        const id = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
        if (id && typeof dispatchWorkspaceBatchSync === 'function') {
            dispatchWorkspaceBatchSync(id);
        } else if (typeof updateWorkspaceSimulationPreview === 'function') {
            updateWorkspaceSimulationPreview();
        }
    };

    card.addEventListener('change', (e) => {
        if (e.target.classList.contains('val-aod-dne')) {
            if (e.target.checked) {
                clearAllKeyLinks(card);
            }
            syncDneUi(card);
            bump();
        }
        if (e.target.classList.contains('val-aod-grading-mode')) {
            bump();
        }
    });

    card.addEventListener('click', (e) => {
        const addBtn = e.target.closest('.btn-add-aod-key');
        if (addBtn && card.contains(addBtn)) {
            e.preventDefault();
            const dneCb = card.querySelector('.val-aod-dne');
            if (dneCb?.checked) {
                dneCb.checked = false;
            }
            syncDneUi(card);
            const container = card.querySelector('.aod-keys-container');
            if (!container) return;
            const idx = container.querySelectorAll('.answers-or-dne-key-row').length;
            container.insertAdjacentHTML('beforeend', keyRowHtml('', idx));
            bump();
            return;
        }
        const removeBtn = e.target.closest('.btn-remove-aod-key');
        if (removeBtn && card.contains(removeBtn)) {
            e.preventDefault();
            removeBtn.closest('.answers-or-dne-key-row')?.remove();
            reindexKeyRows(card);
            bump();
        }
    });

    // When a link is applied/removed via overlay handlers, uncheck DNE if linked
    card.addEventListener('click', (e) => {
        const linkBtn = e.target.closest('.btn-input-link-trigger');
        if (!linkBtn || !card.contains(linkBtn)) return;
        // After overlay toggles link, sync on next tick
        setTimeout(() => {
            const row = linkBtn.closest('.answers-or-dne-key-row');
            if (row?.getAttribute('data-bound-token')) {
                const dneCb = card.querySelector('.val-aod-dne');
                if (dneCb) dneCb.checked = false;
            }
            syncDneUi(card);
            bump();
        }, 0);
    });

    syncDneUi(card);
    return true;
}

function isLinkCompatible({ inputKey, sourceArchetype, sourceToken }) {
    if (!inputKey || !String(inputKey).startsWith('aod_answer_')) return null;
    if (sourceArchetype === 'formula') {
        const srcCard = findWorkspaceCardByToken(sourceToken);
        return isFormulaSimplifyEligible(srcCard);
    }
    return ['shortAnswer', 'arrayMatchingUnordered', 'numAnswer'].includes(sourceArchetype);
}

function applyBatchSync({ card, result }) {
    if (!card || !result) return null;
    const targetDisplay = ensureLatexRenderBox(card);
    if (targetDisplay) {
        targetDisplay.style.textAlign = 'left';
        targetDisplay.style.fontSize = '0.9rem';
        targetDisplay.style.fontWeight = '600';
        targetDisplay.style.color = '#0f172a';
        targetDisplay.style.whiteSpace = 'pre-line';
        const out = result.evaluated_output || result.latex_output || '';
        if (String(out).startsWith('[Invalid') || String(out).startsWith('⚠️')) {
            targetDisplay.textContent = '';
        } else {
            const lines = String(out).split('\n').map((l) => l.trim()).filter(Boolean);
            if (lines.length && typeof katex !== 'undefined') {
                targetDisplay.innerHTML = lines.map((line) => {
                    const span = document.createElement('div');
                    span.style.margin = '2px 0';
                    span.style.lineHeight = '1.35';
                    try {
                        // Intervals like [-oo,-1] and fractions render via KaTeX
                        const tex = line
                            .replace(/-oo/g, '-\\infty')
                            .replace(/\boo\b/g, '\\infty')
                            .replace(/(-?\d+)\/(\d+)/g, '\\frac{$1}{$2}');
                        katex.render(tex, span, { throwOnError: false, displayMode: false });
                    } catch (_) {
                        span.textContent = line;
                    }
                    return span.outerHTML;
                }).join('');
            } else {
                targetDisplay.textContent = out;
            }
        }
    }
    return true;
}

function renderPreviewToken({ cleanToken, initialValue }) {
    const token = cleanToken || '';
    let dne = false;
    let entries = [];
    if (initialValue && typeof initialValue === 'object') {
        dne = !!initialValue.dne;
        if (Array.isArray(initialValue.entries)) entries = initialValue.entries;
    }

    return `
        <div class="simulated-answers-or-dne-wrapper" data-token="${escapeHtmlAttr(token)}" style="display:block; width:100%; max-width:420px; margin:8px 0; box-sizing:border-box; border:1px solid #e2e8f0; border-radius:6px; background:#f8fafc; padding:10px;">
            <div class="aod-preview-entries" style="display:flex; flex-direction:column; gap:8px;"></div>
            <div class="aod-preview-chooser" style="display:none; flex-wrap:wrap; gap:6px; margin-top:8px;"></div>
            <div class="aod-preview-actions" style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:10px;">
                <button type="button" class="btn-aod-add-answer" style="font-size:0.78rem; padding:5px 10px; border:1px dashed #94a3b8; border-radius:4px; background:#fff; color:#334155; cursor:pointer;">Add answer</button>
                <label class="aod-preview-dne-label" style="font-size:0.78rem; color:#475569; display:inline-flex; align-items:center; gap:6px; cursor:pointer; margin:0;">
                    <input type="checkbox" class="preview-aod-dne" ${dne ? 'checked' : ''} style="cursor:pointer;">
                    DNE
                </label>
            </div>
        </div>
    `;
}

function entryRowHtml(type, value, token) {
    const label = TYPE_LABELS[type] || type;
    let field = '';
    if (type === 'numAnswer') {
        field = `<input type="number" step="any" class="preview-aod-entry-input" data-entry-type="numAnswer" data-token="${escapeHtmlAttr(token)}" value="${escapeHtmlAttr(value ?? '')}" placeholder="Number" inputmode="decimal" style="flex:1; min-width:0; box-sizing:border-box; font-size:0.85rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px;">`;
    } else if (type === 'arrayMatchingUnordered') {
        field = `<input type="text" class="preview-aod-entry-input" data-entry-type="arrayMatchingUnordered" data-token="${escapeHtmlAttr(token)}" value="${escapeHtmlAttr(value ?? '')}" placeholder="e.g. [2,3] or 2,3" style="flex:1; min-width:0; box-sizing:border-box; font-size:0.85rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px;">`;
    } else {
        field = `<input type="text" class="preview-aod-entry-input" data-entry-type="shortAnswer" data-token="${escapeHtmlAttr(token)}" value="${escapeHtmlAttr(value ?? '')}" placeholder="formula or string" style="flex:1; min-width:0; box-sizing:border-box; font-size:0.85rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px;">`;
    }
    return `
        <div class="aod-preview-entry-row" data-entry-type="${escapeHtmlAttr(type)}" style="display:flex; align-items:center; gap:6px; width:100%;">
            <span style="font-size:0.68rem; color:#64748b; min-width:72px; flex-shrink:0;">${escapeHtmlAttr(label)}</span>
            ${field}
            <button type="button" class="btn-aod-remove-entry" title="Remove" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem; padding:4px; flex-shrink:0;"><i class="fas fa-trash"></i></button>
        </div>
    `;
}

function mountPreviewAnswersOrDne({ wrapper, onChange, scheduleGradeRefresh, initialValue }) {
    const wrap = wrapper;
    if (!wrap || wrap.dataset.aodMounted === '1') return true;
    wrap.dataset.aodMounted = '1';

    const token = wrap.getAttribute('data-token') || '';
    const entriesEl = wrap.querySelector('.aod-preview-entries');
    const chooserEl = wrap.querySelector('.aod-preview-chooser');
    const dneLabel = wrap.querySelector('.aod-preview-dne-label');
    const dneCb = wrap.querySelector('.preview-aod-dne');
    const addBtn = wrap.querySelector('.btn-aod-add-answer');

    let entries = [];
    if (initialValue && typeof initialValue === 'object' && Array.isArray(initialValue.entries)) {
        entries = initialValue.entries
            .filter((e) => e && STUDENT_ENTRY_TYPES.includes(e.type))
            .map((e) => ({ type: e.type, value: e.value ?? '' }));
    }
    if (initialValue?.dne && entries.length === 0 && dneCb) {
        dneCb.checked = true;
    }

    function publish() {
        const payload = collectPayload();
        if (typeof onChange === 'function') onChange(token, payload);
        if (typeof scheduleGradeRefresh === 'function') scheduleGradeRefresh();
    }

    function collectPayload() {
        const rows = Array.from(wrap.querySelectorAll('.aod-preview-entry-row'));
        const list = rows.map((row) => {
            const type = row.getAttribute('data-entry-type');
            const input = row.querySelector('.preview-aod-entry-input');
            return { type, value: input ? input.value : '' };
        }).filter((e) => STUDENT_ENTRY_TYPES.includes(e.type));
        const dne = list.length === 0 && !!dneCb?.checked;
        return { dne, entries: list };
    }

    function syncDneVisibility() {
        const hasRows = wrap.querySelectorAll('.aod-preview-entry-row').length > 0;
        if (dneLabel) dneLabel.style.display = hasRows ? 'none' : 'inline-flex';
        if (hasRows && dneCb) dneCb.checked = false;
        if (chooserEl) chooserEl.style.display = 'none';
    }

    function renderEntries() {
        if (!entriesEl) return;
        entriesEl.innerHTML = entries.map((e) => entryRowHtml(e.type, e.value, token)).join('');
        syncDneVisibility();
    }

    function showChooser() {
        if (!chooserEl) return;
        chooserEl.style.display = 'flex';
        chooserEl.innerHTML = `
            <button type="button" class="btn-aod-pick-type" data-type="shortAnswer" style="font-size:0.72rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px; background:#fff; color:#334155; cursor:pointer;">formula/string</button>
            <button type="button" class="btn-aod-pick-type" data-type="arrayMatchingUnordered" style="font-size:0.72rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px; background:#fff; color:#334155; cursor:pointer;">coordinates</button>
            <button type="button" class="btn-aod-pick-type" data-type="numAnswer" style="font-size:0.72rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px; background:#fff; color:#334155; cursor:pointer;">number</button>
            <button type="button" class="btn-aod-cancel-chooser" style="font-size:0.72rem; padding:4px 8px; border:none; background:transparent; color:#94a3b8; cursor:pointer;">Cancel</button>
        `;
    }

    addBtn?.addEventListener('click', () => showChooser());

    wrap.addEventListener('click', (e) => {
        const pick = e.target.closest('.btn-aod-pick-type');
        if (pick && wrap.contains(pick)) {
            const type = pick.getAttribute('data-type');
            if (!STUDENT_ENTRY_TYPES.includes(type)) return;
            entriesEl.insertAdjacentHTML('beforeend', entryRowHtml(type, '', token));
            if (chooserEl) chooserEl.style.display = 'none';
            syncDneVisibility();
            publish();
            return;
        }
        if (e.target.closest('.btn-aod-cancel-chooser') && wrap.contains(e.target)) {
            if (chooserEl) chooserEl.style.display = 'none';
            return;
        }
        const remove = e.target.closest('.btn-aod-remove-entry');
        if (remove && wrap.contains(remove)) {
            remove.closest('.aod-preview-entry-row')?.remove();
            syncDneVisibility();
            publish();
        }
    });

    wrap.addEventListener('input', (e) => {
        if (e.target.classList.contains('preview-aod-entry-input') || e.target.classList.contains('preview-aod-dne')) {
            if (e.target.classList.contains('preview-aod-dne') && e.target.checked) {
                // ensure no rows when DNE selected
                if (wrap.querySelectorAll('.aod-preview-entry-row').length > 0) {
                    e.target.checked = false;
                }
            }
            publish();
        }
    });
    wrap.addEventListener('change', (e) => {
        if (e.target.classList.contains('preview-aod-dne')) publish();
    });

    // Restore initial rows into DOM
    if (entries.length) {
        renderEntries();
    } else {
        syncDneVisibility();
    }
    publish();
    return true;
}
