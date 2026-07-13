import { safeNumValue } from './helpers.js';

/**
 * randInt entity module — integer random value generator.
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
            return false;
        case 'needsLatexRenderBox':
            return false;
        default:
            return null;
    }
}

function getFieldsHtml(savedValues) {
    return `
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">
            <div class="linked-input-wrapper" data-input-key="min" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Min: 
                    <input type="number" class="val-input-min" value="${safeNumValue(savedValues.min, -9)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>
            
            <div class="linked-input-wrapper" data-input-key="max" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Max: 
                    <input type="number" class="val-input-max" value="${safeNumValue(savedValues.max, 9)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>

            <div class="linked-input-wrapper" data-input-key="step" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Step: 
                    <input type="number" class="val-input-step" value="${safeNumValue(savedValues.step, 1)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>
        </div>
    `;
}

function evaluate({ card, tokenIdentifier, visitedTokens = [], getLiveComponentValue }) {
    if (!card || typeof getLiveComponentValue !== 'function') return null;

    const minStr = getLiveComponentValue(card, 'min', '-9', visitedTokens);
    const maxStr = getLiveComponentValue(card, 'max', '9', visitedTokens);
    const stepStr = getLiveComponentValue(card, 'step', '1', visitedTokens);

    const minVal = parseInt(minStr, 10);
    const maxVal = parseInt(maxStr, 10);
    const stepVal = parseInt(stepStr, 10);

    if (!isNaN(minVal) && !isNaN(maxVal) && stepVal > 0 && minVal <= maxVal) {
        const pool = [];
        let current = minVal;
        while (current <= maxVal) { pool.push(current); current += stepVal; }

        if (pool.length > 0) {
            const seedAttr = card.getAttribute('data-shuffle-seed');
            let targetIndex = 0;
            if (seedAttr) {
                targetIndex = Math.floor(parseFloat(seedAttr) * pool.length);
            } else {
                const baseTextSeed = tokenIdentifier.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                targetIndex = baseTextSeed % pool.length;
            }
            if (targetIndex >= pool.length) targetIndex = pool.length - 1;
            return pool[targetIndex].toString();
        }
    }
    return null;
}
