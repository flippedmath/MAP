import { safeNumValue, escapeHtmlText } from './helpers.js';

/**
 * rand entity module — floating-point random value generator.
 */
export function processEntity(contextData) {
    if (!contextData || !contextData.action) return null;

    switch (contextData.action) {
        case 'fieldsHtml':
            return getFieldsHtml(contextData.savedValues || {});
        case 'evaluate':
            return evaluate(contextData);
        case 'renderPreviewToken':
            return renderPreviewToken(contextData);
        case 'getOutputTypes':
            return ['double'];
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
            <div class="linked-input-wrapper" data-input-key="min" data-input-type="double" style="position: relative; display: flex; align-items: flex-end; gap: 4px;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Min: <input type="number" step="any" class="val-input-min" value="${safeNumValue(savedValues.min, 0.0)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                <button type="button" class="btn-input-link-trigger" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>
            <div class="linked-input-wrapper" data-input-key="max" data-input-type="double" style="position: relative; display: flex; align-items: flex-end; gap: 4px;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Max: <input type="number" step="any" class="val-input-max" value="${safeNumValue(savedValues.max, 1.0)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                <button type="button" class="btn-input-link-trigger" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>
            <div class="linked-input-wrapper" data-input-key="step" data-input-type="double" style="position: relative; display: flex; align-items: flex-end; gap: 4px;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Step: <input type="number" step="any" class="val-input-step" value="${safeNumValue(savedValues.step, 0.01)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                <button type="button" class="btn-input-link-trigger" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>
        </div>
    `;
}

function evaluate({ card, tokenIdentifier, visitedTokens = [], getLiveComponentValue }) {
    if (!card || typeof getLiveComponentValue !== 'function') return null;

    const minStr = getLiveComponentValue(card, 'min', '0.0', visitedTokens);
    const maxStr = getLiveComponentValue(card, 'max', '1.0', visitedTokens);
    const stepStr = getLiveComponentValue(card, 'step', '0.01', visitedTokens);

    const minVal = parseFloat(minStr);
    const maxVal = parseFloat(maxStr);
    const stepVal = parseFloat(stepStr);

    if (!isNaN(minVal) && !isNaN(maxVal) && stepVal > 0 && minVal <= maxVal) {
        const totalRange = maxVal - minVal;
        const maxSteps = Math.floor((totalRange + 1e-9) / stepVal);

        if (maxSteps >= 0) {
            const seedAttr = card.getAttribute('data-shuffle-seed');
            let targetStepMultiplier = 0;

            if (seedAttr) {
                targetStepMultiplier = Math.floor(parseFloat(seedAttr) * (maxSteps + 1));
            } else {
                const baseTextSeed = tokenIdentifier.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                targetStepMultiplier = baseTextSeed % (maxSteps + 1);
                if (isNaN(targetStepMultiplier)) targetStepMultiplier = 0;
            }

            if (targetStepMultiplier > maxSteps) targetStepMultiplier = maxSteps;
            if (targetStepMultiplier < 0) targetStepMultiplier = 0;

            let finalValue = minVal + (targetStepMultiplier * stepVal);
            if (finalValue > maxVal) finalValue = maxVal;

            const precisionStr = stepVal.toString();
            let decimalPlaces = 4;
            if (precisionStr.includes('.')) {
                decimalPlaces = precisionStr.split('.')[1].length;
            }
            return finalValue.toFixed(decimalPlaces);
        }
    }
    return null;
}

function renderPreviewToken({ displayVal }) {
    // Numeric value as inline LaTeX (no green badge). Preview pipeline
    // KaTeX-renders .simulated-math-formula-render spans after HTML insert.
    return `<span class="simulated-math-formula-render" style="display: inline-block; padding: 2px 4px;">${escapeHtmlText(displayVal)}</span>`;
}
