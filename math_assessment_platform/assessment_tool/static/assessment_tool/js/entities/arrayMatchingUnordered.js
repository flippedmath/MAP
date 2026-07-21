import { ensureLatexRenderBox } from './helpers.js';

/**
 * arrayMatchingUnordered — comma-separated list answer field.
 * Server strips outer ()/[], splits on commas outside nesting, grades each
 * item like a short answer. Optional ordered matching + partial credit.
 * Links only to primeFactors Dynamic Variable entities.
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

function isCheckboxEnabled(savedValues, key) {
    const raw = savedValues?.[key];
    if (raw === true || raw === 1) return true;
    if (typeof raw === 'string') {
        return ['true', '1', 'yes', 'checked', 'on'].includes(raw.trim().toLowerCase());
    }
    return false;
}

function getFieldsHtml(savedValues) {
    const linkedValue = typeof savedValues.results === 'string' && /^<[^>]+>$/.test(savedValues.results.trim())
        ? savedValues.results.trim()
        : '';
    const isLinked = !!linkedValue;
    const textValue = isLinked ? '' : escapeHtmlAttr(savedValues.results ?? '');
    const partial = isCheckboxEnabled(savedValues, 'partial_credit');
    const ordered = isCheckboxEnabled(savedValues, 'ordered');

    return `
        <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">
            <div class="linked-input-wrapper" data-input-key="results" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px; width: 100%; box-sizing: border-box;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Correct answers (comma-separated):
                    <input type="text" class="val-array-matching-results" value="${textValue}" ${isLinked ? 'disabled' : ''} placeholder="e.g. [2,3] or x+1, 3-x, hello" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                <button type="button" class="btn-input-link-trigger ${isLinked ? 'is-linked' : ''}" title="Link primeFactors token" style="background: #ffffff; border: 1px solid ${isLinked ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${isLinked ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                    <i class="fas ${isLinked ? 'fa-times' : 'fa-link'}"></i>
                </button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>

            <div class="linked-input-wrapper" data-input-key="ordered" data-input-type="checkbox" style="display:flex; align-items:center; gap:8px;">
                <label style="font-size:0.75rem; color:#475569; font-weight:500; display:inline-flex; align-items:center; gap:6px; cursor:pointer; margin:0;">
                    <input type="checkbox" class="val-array-matching-ordered" ${ordered ? 'checked' : ''} style="cursor:pointer;">
                    Require order (e.g. coordinates)
                </label>
            </div>

            <div class="linked-input-wrapper" data-input-key="partial_credit" data-input-type="checkbox" style="display:flex; align-items:center; gap:8px;">
                <label style="font-size:0.75rem; color:#475569; font-weight:500; display:inline-flex; align-items:center; gap:6px; cursor:pointer; margin:0;">
                    <input type="checkbox" class="val-array-matching-partial" ${partial ? 'checked' : ''} style="cursor:pointer;">
                    Partial credit for partial answer
                </label>
            </div>
        </div>
    `;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    const resultsWrapper = card.querySelector('.linked-input-wrapper[data-input-key="results"]');
    const boundToken = resultsWrapper?.getAttribute('data-bound-token');
    if (boundToken) {
        let cleanToken = boundToken.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
        if (!cleanToken.startsWith('<')) cleanToken = `<${cleanToken}`;
        if (!cleanToken.endsWith('>')) cleanToken = `${cleanToken}>`;
        inputsCollected.results = cleanToken;
    } else {
        const raw = card.querySelector('.val-array-matching-results')?.value;
        if (raw !== undefined && raw !== null) {
            inputsCollected.results = String(raw).trim();
        }
    }

    inputsCollected.ordered = !!card.querySelector('.val-array-matching-ordered')?.checked;
    inputsCollected.partial_credit = !!card.querySelector('.val-array-matching-partial')?.checked;
    return inputsCollected;
}

function bindCheckboxSync(card, selector, datasetFlag, updateWorkspaceSimulationPreview) {
    const el = card.querySelector(selector);
    if (!el || el.dataset[datasetFlag]) return;
    el.dataset[datasetFlag] = '1';
    el.addEventListener('change', () => {
        const probe = card.querySelector('.val-array-matching-results') || card;
        probe.dispatchEvent(new Event('input', { bubbles: true }));
        if (typeof updateWorkspaceSimulationPreview === 'function') {
            updateWorkspaceSimulationPreview();
        }
    });
}

function bindEvents({ card, updateWorkspaceSimulationPreview }) {
    if (!card) return null;
    bindCheckboxSync(card, '.val-array-matching-partial', 'arrayMatchingPartialBound', updateWorkspaceSimulationPreview);
    bindCheckboxSync(card, '.val-array-matching-ordered', 'arrayMatchingOrderedBound', updateWorkspaceSimulationPreview);
    return true;
}

function isLinkCompatible({ inputKey, sourceArchetype }) {
    if (inputKey !== 'results') return null;
    return sourceArchetype === 'primeFactors';
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
        <span class="simulated-array-matching-wrapper" data-token="${token}" style="display:inline-block; vertical-align:middle; margin:2px; max-width:280px; width:auto; line-height:1;">
            <input type="text" class="preview-array-matching-input" data-token="${token}" value="${escapeHtmlAttr(restored)}" placeholder="comma-separated or [x,y]" style="background:#ffffff; border:1px solid #cbd5e1; padding:4px 8px; border-radius:4px; font-size:0.9rem; width:220px; box-sizing:border-box; margin:0; display:block; line-height:1.2;">
        </span>
    `;
}
