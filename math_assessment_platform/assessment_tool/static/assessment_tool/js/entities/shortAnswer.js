import { ensureLatexRenderBox } from './helpers.js';

/**
 * shortAnswer — text/expression answer field.
 * Exact match (trim + lowercase) or sympy equivalence without needing further simplify.
 * Optional: accept answers that match after rounding both sides to 3 decimal places.
 * Links only to formula Dynamic Variable entities.
 */

const ROUNDED_DECIMAL_PLACES = 3;

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
            return ['string'];
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

function isAcceptRoundedEnabled(savedValues) {
    const raw = savedValues?.accept_rounded_decimals;
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
    const textValue = isLinked ? '' : escapeHtmlAttr(savedValues.value ?? '');
    const acceptRounded = isAcceptRoundedEnabled(savedValues);

    return `
        <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">
            <div class="linked-input-wrapper" data-input-key="value" data-input-type="formula" style="position: relative; display: flex; align-items: flex-end; gap: 4px; width: 100%; box-sizing: border-box;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Correct answer:
                    <input type="text" class="val-short-answer-value" value="${textValue}" ${isLinked ? 'disabled' : ''} placeholder="Text, expression, or link formula…" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                <button type="button" class="btn-input-link-trigger ${isLinked ? 'is-linked' : ''}" title="Link formula token" style="background: #ffffff; border: 1px solid ${isLinked ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${isLinked ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                    <i class="fas ${isLinked ? 'fa-times' : 'fa-link'}"></i>
                </button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>

            <div class="linked-input-wrapper" data-input-key="accept_rounded_decimals" data-input-type="checkbox" style="display:flex; flex-direction:column; gap:4px; width:100%;">
                <label style="font-size:0.75rem; color:#475569; font-weight:500; display:inline-flex; align-items:center; gap:6px; cursor:pointer; margin:0;">
                    <input type="checkbox" class="val-short-answer-accept-rounded" ${acceptRounded ? 'checked' : ''} style="cursor:pointer;">
                    Accept rounded decimal answers
                </label>
                <span class="short-answer-rounding-hint" style="display:${acceptRounded ? 'block' : 'none'}; font-size:0.72rem; color:#64748b; font-style:italic; padding-left:22px;">
                    Rounded to ${ROUNDED_DECIMAL_PLACES} decimal places
                </span>
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
        const raw = card.querySelector('.val-short-answer-value')?.value;
        if (raw !== undefined && raw !== null) {
            inputsCollected.value = String(raw).trim();
        }
    }

    inputsCollected.accept_rounded_decimals = !!card.querySelector('.val-short-answer-accept-rounded')?.checked;
    return inputsCollected;
}

function bindEvents({ card, updateWorkspaceSimulationPreview }) {
    if (!card) return null;

    const roundedCheckbox = card.querySelector('.val-short-answer-accept-rounded');
    if (roundedCheckbox && !roundedCheckbox.dataset.shortAnswerRoundedBound) {
        roundedCheckbox.dataset.shortAnswerRoundedBound = '1';
        roundedCheckbox.addEventListener('change', () => {
            const hint = card.querySelector('.short-answer-rounding-hint');
            if (hint) {
                hint.style.display = roundedCheckbox.checked ? 'block' : 'none';
            }
            const probe = card.querySelector('.val-short-answer-value') || card;
            probe.dispatchEvent(new Event('input', { bubbles: true }));
            if (typeof updateWorkspaceSimulationPreview === 'function') {
                updateWorkspaceSimulationPreview();
            }
        });
    }

    return true;
}

function isLinkCompatible({ inputKey, sourceArchetype }) {
    if (inputKey !== 'value') return null;
    return sourceArchetype === 'formula';
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
    const acceptRounded = card
        ? !!card.querySelector('.val-short-answer-accept-rounded')?.checked
        : false;

    const restored = (initialValue !== undefined && initialValue !== null)
        ? String(initialValue)
        : '';

    const noteHtml = acceptRounded
        ? `<span class="preview-short-answer-rounding-note" style="display:block; margin:1px 0 0 0; padding:0 2px; font-size:0.65rem; line-height:1; color:#64748b; font-style:italic;">Accepts fractions or decimals (to ${ROUNDED_DECIMAL_PLACES} places)</span>`
        : '';

    return `
        <span class="simulated-short-answer-wrapper" data-token="${token}" style="display:inline-block; vertical-align:middle; margin:2px; max-width:220px; width:auto; line-height:1;">
            <input type="text" class="preview-short-answer-input" data-token="${token}" value="${escapeHtmlAttr(restored)}" placeholder="string or equation" style="background:#ffffff; border:1px solid #cbd5e1; padding:4px 8px; border-radius:4px; font-size:0.9rem; width:180px; box-sizing:border-box; margin:0; display:block; line-height:1.2;">
            ${noteHtml}
        </span>
    `;
}
