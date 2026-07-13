import { safeNumValue, ensureLatexRenderBox } from './helpers.js';

/**
 * primeFactors entity module — integer factorization display.
 */
export function processEntity(contextData) {
    if (!contextData || !contextData.action) return null;

    switch (contextData.action) {
        case 'fieldsHtml':
            return getFieldsHtml(contextData.savedValues || {});
        case 'evaluate':
            return evaluate(contextData);
        case 'getOutputTypes':
            return ['integer'];
        case 'hideRefreshButton':
            return true;
        case 'needsLatexRenderBox':
            return true;
        case 'applyBatchSync':
            return applyBatchSync(contextData);
        default:
            return null;
    }
}

function getFieldsHtml(savedValues) {
    return `
        <div class="linked-input-wrapper" data-input-key="number to factor" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px; width: 100%;">
            <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Number to Factor: 
                <input type="number" class="val-input-number" value="${safeNumValue(savedValues['number to factor'], 12)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
            </label>
            <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
            <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
        </div>
    `;
}

function evaluate({ card, visitedTokens = [], getLiveComponentValue }) {
    if (!card || typeof getLiveComponentValue !== 'function') return null;

    const numStr = getLiveComponentValue(card, 'number to factor', '12', visitedTokens);
    let targetNum = parseInt(numStr, 10);

    if (!isNaN(targetNum) && targetNum > 1) {
        const factors = [];
        while (targetNum % 2 === 0) {
            factors.push(2);
            targetNum = Math.floor(targetNum / 2);
        }
        let factor = 3;
        while (factor * factor <= targetNum) {
            while (targetNum % factor === 0) {
                factors.push(factor);
                targetNum = Math.floor(targetNum / factor);
            }
            factor += 2;
        }
        if (targetNum > 1) {
            factors.push(targetNum);
        }
        return factors.join(', ');
    }
    return "";
}

function applyBatchSync({ card, result }) {
    if (!card || !result) return null;
    const targetDisplay = ensureLatexRenderBox(card);
    if (targetDisplay) {
        targetDisplay.style.textAlign = 'center';
        targetDisplay.textContent = result.evaluated_output;
    }
    return true;
}
