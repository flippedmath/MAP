import { ensureLatexRenderBox } from './helpers.js';

/**
 * shortAnswer — text/expression answer field.
 * Exact match (trim + lowercase) or sympy equivalence without needing further simplify.
 * Links only to formula Dynamic Variable entities.
 */
export function processEntity(contextData) {
    if (!contextData || !contextData.action) return null;

    switch (contextData.action) {
        case 'fieldsHtml':
            return getFieldsHtml(contextData.savedValues || {});
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

function getFieldsHtml(savedValues) {
    const linkedValue = typeof savedValues.value === 'string' && /^<[^>]+>$/.test(savedValues.value.trim())
        ? savedValues.value.trim()
        : '';
    const isLinked = !!linkedValue;
    const textValue = isLinked ? '' : escapeHtmlAttr(savedValues.value ?? '');

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
    return inputsCollected;
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

function renderPreviewToken({ cleanToken, initialValue }) {
    const token = cleanToken || '';
    const restored = (initialValue !== undefined && initialValue !== null)
        ? String(initialValue)
        : '';

    return `
        <span class="simulated-short-answer-wrapper" data-token="${token}" style="display:inline-block; vertical-align:middle; margin:2px; max-width:220px; width:auto; line-height:1;">
            <input type="text" class="preview-short-answer-input" data-token="${token}" value="${escapeHtmlAttr(restored)}" placeholder="string or equation" style="background:#ffffff; border:1px solid #cbd5e1; padding:4px 8px; border-radius:4px; font-size:0.9rem; width:180px; box-sizing:border-box; margin:0; display:block; line-height:1.2;">
        </span>
    `;
}
