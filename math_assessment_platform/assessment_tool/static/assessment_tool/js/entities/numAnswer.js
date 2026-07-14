import { safeNumValue, ensureLatexRenderBox } from './helpers.js';

/**
 * numAnswer — numeric answer field with decimal-place rounding comparison.
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
            return ['double'];
        case 'hideRefreshButton':
            return true;
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

function isRoundingNoteEnabled(savedValues) {
    const raw = savedValues?.show_rounding_note;
    if (raw === true || raw === 1) return true;
    if (typeof raw === 'string') {
        return ['true', '1', 'yes', 'checked', 'on'].includes(raw.trim().toLowerCase());
    }
    return false;
}

function getFieldsHtml(savedValues) {
    const linkedValue = typeof savedValues.value === 'string' && /^<[^>]+>$/.test(savedValues.value.trim())
        ? savedValues.value.trim()
        : '';
    const isLinked = !!linkedValue;
    const numericValue = isLinked ? '' : safeNumValue(savedValues.value, '');
    const decimalPlaces = safeNumValue(savedValues.decimal_places, 3);
    const showNote = isRoundingNoteEnabled(savedValues);

    return `
        <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">
            <div class="linked-input-wrapper" data-input-key="value" data-input-type="double" style="position: relative; display: flex; align-items: flex-end; gap: 4px; width: 100%; box-sizing: border-box;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Correct answer:
                    <input type="number" step="any" class="val-num-answer-value" value="${numericValue}" ${isLinked ? 'disabled' : ''} placeholder="Number or link…" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                <button type="button" class="btn-input-link-trigger ${isLinked ? 'is-linked' : ''}" title="Link integer/double token" style="background: #ffffff; border: 1px solid ${isLinked ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${isLinked ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                    <i class="fas ${isLinked ? 'fa-times' : 'fa-link'}"></i>
                </button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>

            <div class="linked-input-wrapper" data-input-key="decimal_places" data-input-type="integer" style="display: flex; flex-direction: column; gap: 4px; width: 100%;">
                <label style="font-size: 0.75rem; color: #475569; font-weight: 500;">Decimal places (rounding):
                    <input type="number" min="0" step="1" class="val-num-answer-decimals" value="${decimalPlaces}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            </div>

            <div class="linked-input-wrapper" data-input-key="show_rounding_note" data-input-type="checkbox" style="display:flex; align-items:center; gap:8px;">
                <label style="font-size:0.75rem; color:#475569; font-weight:500; display:inline-flex; align-items:center; gap:6px; cursor:pointer; margin:0;">
                    <input type="checkbox" class="val-num-answer-show-note" ${showNote ? 'checked' : ''} style="cursor:pointer;">
                    Show rounding note in preview
                </label>
            </div>
        </div>
    `;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    const valueWrapper = card.querySelector('.linked-input-wrapper[data-input-key="value"]');
    const boundToken = valueWrapper?.getAttribute('data-bound-token');
    if (boundToken) {
        let cleanToken = boundToken.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
        if (!cleanToken.startsWith('<')) cleanToken = `<${cleanToken}`;
        if (!cleanToken.endsWith('>')) cleanToken = `${cleanToken}>`;
        inputsCollected.value = cleanToken;
    } else {
        const raw = card.querySelector('.val-num-answer-value')?.value;
        if (raw !== undefined && raw !== null && String(raw).trim() !== '') {
            inputsCollected.value = String(raw).trim();
        }
    }

    const placesRaw = card.querySelector('.val-num-answer-decimals')?.value;
    let places = parseInt(placesRaw, 10);
    if (!Number.isFinite(places) || places < 0) places = 3;
    inputsCollected.decimal_places = places;

    inputsCollected.show_rounding_note = !!card.querySelector('.val-num-answer-show-note')?.checked;
    return inputsCollected;
}

function bindEvents({ card, updateWorkspaceSimulationPreview }) {
    if (!card) return null;

    const noteCheckbox = card.querySelector('.val-num-answer-show-note');
    if (noteCheckbox && !noteCheckbox.dataset.numAnswerNoteBound) {
        noteCheckbox.dataset.numAnswerNoteBound = '1';
        noteCheckbox.addEventListener('change', () => {
            const probe = card.querySelector('.val-num-answer-value') || card;
            probe.dispatchEvent(new Event('input', { bubbles: true }));
            if (typeof updateWorkspaceSimulationPreview === 'function') {
                updateWorkspaceSimulationPreview();
            }
        });
    }

    const decimalsInput = card.querySelector('.val-num-answer-decimals');
    if (decimalsInput && !decimalsInput.dataset.numAnswerDecimalsBound) {
        decimalsInput.dataset.numAnswerDecimalsBound = '1';
        const sync = () => {
            if (typeof updateWorkspaceSimulationPreview === 'function') {
                updateWorkspaceSimulationPreview();
            }
        };
        decimalsInput.addEventListener('change', sync);
        decimalsInput.addEventListener('input', sync);
    }

    return true;
}

function applyBatchSync({ card, result }) {
    if (!card || !result) return null;

    const targetDisplay = ensureLatexRenderBox(card);
    if (targetDisplay) {
        targetDisplay.style.textAlign = 'center';
        targetDisplay.style.fontSize = '0.95rem';
        targetDisplay.style.fontWeight = '600';
        targetDisplay.style.color = '#0f172a';
        const out = result.evaluated_output;
        if (out && out !== '???' && !String(out).startsWith('[Invalid') && !String(out).startsWith('⚠️')) {
            targetDisplay.textContent = out;
        } else if (result.latex_output && result.latex_output !== '???' && !String(result.latex_output).startsWith('⚠️')) {
            targetDisplay.textContent = result.latex_output;
        } else {
            targetDisplay.textContent = '';
        }
    }
    return true;
}

function renderPreviewToken({ cleanToken, card, initialValue }) {
    const token = cleanToken || '';
    let places = 3;
    let showNote = false;
    if (card) {
        const placesRaw = card.querySelector('.val-num-answer-decimals')?.value;
        const parsed = parseInt(placesRaw, 10);
        if (Number.isFinite(parsed) && parsed >= 0) places = parsed;
        showNote = !!card.querySelector('.val-num-answer-show-note')?.checked;
    }

    const restored = (initialValue !== undefined && initialValue !== null)
        ? String(initialValue)
        : '';

    // Use <span> only — a <div> inside Quill <p> breaks the paragraph and
    // either adds a large gap or (with absolute positioning) gets clipped.
    const noteHtml = showNote
        ? `<span class="preview-num-answer-rounding-note" style="display:block; margin:1px 0 0 0; padding:0 2px; font-size:0.65rem; line-height:1; color:#64748b; font-style:italic;">Round to ${places} decimal place${places === 1 ? '' : 's'}</span>`
        : '';

    return `
        <span class="simulated-num-answer-wrapper" data-token="${token}" style="display:inline-block; vertical-align:middle; margin:2px; max-width:180px; width:auto; line-height:1;">
            <input type="number" step="any" class="preview-num-answer-input" data-token="${token}" value="${escapeAttr(restored)}" placeholder="Number" inputmode="decimal" style="background:#ffffff; border:1px solid #cbd5e1; padding:4px 8px; border-radius:4px; font-size:0.9rem; width:140px; box-sizing:border-box; margin:0; display:block; line-height:1.2;">
            ${noteHtml}
        </span>
    `;
}

function escapeAttr(val) {
    return String(val)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}
