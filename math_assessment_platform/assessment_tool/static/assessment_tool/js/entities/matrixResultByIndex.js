import { safeNumValue, ensureLatexRenderBox } from './helpers.js';

/**
 * matrixResultByIndex — extract one cell from a linked matrix (1-based row/col).
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
            return getOutputTypes(contextData);
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

function isSimplifyEnabled(savedValues) {
    const raw = savedValues?.simplify;
    if (raw === true || raw === 1) return true;
    if (typeof raw === 'string') {
        return ['true', '1', 'yes', 'checked', 'on'].includes(raw.trim().toLowerCase());
    }
    return false;
}

function getFieldsHtml(savedValues) {
    const linkedMatrixToken = savedValues.matrix || '';
    const isLinked = !!linkedMatrixToken;
    const rowVal = safeNumValue(savedValues.row, 1);
    const colVal = safeNumValue(savedValues.column, 1);
    const simplifyChecked = isSimplifyEnabled(savedValues);

    return `
        <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">
            <div class="linked-input-wrapper" data-input-key="matrix" data-input-type="matrix" style="position: relative; display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; box-sizing: border-box; background: #f1f5f9; padding: 6px 8px; border-radius: 4px; border: 1px dashed #cbd5e1;">
                <div style="display: flex; flex-direction: column; min-width: 0; flex-grow: 1;">
                    <span style="font-size: 0.75rem; font-weight: 600; color: #334155;">Source Matrix</span>
                    <span class="link-status-text" style="font-size: 0.75rem; color: ${isLinked ? '#0284c7' : '#ef4444'}; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                        ${isLinked ? `Linked to: ${String(linkedMatrixToken).replace(/[<>]/g, '')}` : 'Required: Select a matrix'}
                    </span>
                </div>
                <input type="hidden" class="val-matrix-result-source" value="${isLinked ? linkedMatrixToken : ''}">
                <div style="position: relative; display: flex; align-items: center; flex-shrink: 0;">
                    <button type="button" class="btn-input-link-trigger ${isLinked ? 'is-linked' : ''}" title="Link matrix token" style="background: #ffffff; border: 1px solid ${isLinked ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${isLinked ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 28px; width: 28px; display: flex; align-items: center; justify-content: center; box-sizing: border-box;">
                        <i class="fas ${isLinked ? 'fa-times' : 'fa-link'}"></i>
                    </button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: auto; right: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 150px; padding: 4px 0; margin-top: 4px; box-sizing: border-box;"></div>
                </div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; width: 100%; box-sizing: border-box;">
                <div class="linked-input-wrapper" data-input-key="row" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px; width: 100%; box-sizing: border-box;">
                    <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Row (1 = top):
                        <input type="number" min="1" class="val-matrix-result-row" value="${rowVal}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                    </label>
                    <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
                </div>
                <div class="linked-input-wrapper" data-input-key="column" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px; width: 100%; box-sizing: border-box;">
                    <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Column (1 = left):
                        <input type="number" min="1" class="val-matrix-result-column" value="${colVal}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                    </label>
                    <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
                </div>
            </div>

            <div style="display: flex; align-items: center; padding: 2px 0;">
                <label style="font-size: 0.75rem; color: #475569; display: flex; align-items: center; gap: 6px; cursor: pointer;">
                    <input type="checkbox" class="val-matrix-result-simplify" ${simplifyChecked ? 'checked' : ''} style="cursor: pointer;">
                    Simplify result
                </label>
            </div>
        </div>
    `;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;
    const isChecked = card.querySelector('.val-matrix-result-simplify')?.checked ?? false;
    inputsCollected.simplify = isChecked;
    return inputsCollected;
}

function bindEvents({ card, updateWorkspaceSimulationPreview }) {
    if (!card) return null;
    const simplifyCheckbox = card.querySelector('.val-matrix-result-simplify');
    if (!simplifyCheckbox) return null;

    simplifyCheckbox.addEventListener('change', function() {
        if (typeof updateWorkspaceSimulationPreview === 'function') {
            updateWorkspaceSimulationPreview();
        }
    });
    return true;
}

function getOutputTypes({ card } = {}) {
    if (!card) return [];
    const raw = card.getAttribute('data-output-types') || '';
    const types = raw.split(',').map(t => t.trim()).filter(Boolean);
    return types;
}

function applyBatchSync({ card, result }) {
    if (!card || !result) return null;

    const types = Array.isArray(result.output_types) ? result.output_types : [];
    if (types.length) {
        card.setAttribute('data-output-types', types.join(','));
    } else {
        card.removeAttribute('data-output-types');
    }

    const targetDisplay = ensureLatexRenderBox(card);
    if (targetDisplay) {
        targetDisplay.style.textAlign = 'center';
        const latex = result.latex_output;
        if (latex && latex !== '???' && typeof katex !== 'undefined') {
            katex.render(latex, targetDisplay, { throwOnError: false });
        } else {
            targetDisplay.textContent = result.evaluated_output || '';
        }
    }
    return true;
}

function renderPreviewToken({ displayVal }) {
    return `<span class="simulated-math-formula-render" style="display: inline-block; padding: 2px 4px;">${displayVal}</span>`;
}
