import { safeNumValue, cleanTokenBrackets, ensureLatexRenderBox } from './helpers.js';

/**
 * graph entity module — multi-formula plot with axis bounds.
 */
export function processEntity(contextData) {
    if (!contextData || !contextData.action) return null;

    switch (contextData.action) {
        case 'fieldsHtml':
            return getFieldsHtml(contextData.savedValues || {});
        case 'bindEvents':
            return bindEvents(contextData);
        case 'evaluate':
            return evaluate(contextData);
        case 'serialize':
            return serialize(contextData);
        case 'applyBatchSync':
            return applyBatchSync(contextData);
        case 'renderPreviewToken':
            return renderPreviewToken(contextData);
        case 'getOutputTypes':
            return ['content'];
        case 'isLinkCompatible':
            return isLinkCompatible(contextData);
        case 'hideRefreshButton':
            return false;
        case 'needsLatexRenderBox':
            return true;
        default:
            return null;
    }
}

function getFieldsHtml(savedValues) {
    const initialFormulas = Array.isArray(savedValues.formulas)
        ? savedValues.formulas
        : (savedValues.formulas ? [savedValues.formulas] : ['']);
    const showGridChecked = savedValues.show_grid !== false;

    const legacyX = savedValues['x-axis range'] || [];
    const xMinVal = savedValues['x_min'] !== undefined ? savedValues['x_min'] : (legacyX[0] !== undefined ? legacyX[0] : '');
    const xMaxVal = savedValues['x_max'] !== undefined ? savedValues['x_max'] : (legacyX[1] !== undefined ? legacyX[1] : '');
    const xStepVal = savedValues['x_step'] !== undefined ? savedValues['x_step'] : (legacyX[2] !== undefined ? legacyX[2] : '');

    const legacyY = savedValues['y-axis range'] || [];
    const yMinVal = savedValues['y_min'] !== undefined ? savedValues['y_min'] : (legacyY[0] !== undefined ? legacyY[0] : '');
    const yMaxVal = savedValues['y_max'] !== undefined ? savedValues['y_max'] : (legacyY[1] !== undefined ? legacyY[1] : '');
    const yStepVal = savedValues['y_step'] !== undefined ? savedValues['y_step'] : (legacyY[2] !== undefined ? legacyY[2] : '');

    return `
        <div style="display: flex; flex-direction: column; gap: 8px; width: 100%;">
            <div class="graph-formulas-container" style="display: flex; flex-direction: column; gap: 6px; width: 100%;">
                <span style="font-size: 0.75rem; font-weight: 600; color: #475569;">Formulas List:</span>
                ${initialFormulas.map((f, i) => `
                    <div class="graph-formula-row" style="display: flex; align-items: center; gap: 4px; width: 100%;">
                        <div class="linked-input-wrapper" data-input-key="formula_${i}" data-input-type="text" style="position: relative; display: flex; align-items: center; gap: 4px; flex-grow: 1;">
                            <input type="text" class="val-graph-formula-expr" value="${f}" placeholder="e.g. y = x^2 or 3*x" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                            <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                            <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
                        </div>
                        ${i > 0 ? `<button type="button" class="btn-remove-graph-formula" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem;"><i class="fas fa-minus-circle"></i></button>` : ''}
                    </div>
                `).join('')}
            </div>
            <button type="button" class="btn-add-graph-formula" style="align-self: flex-start; background: #f1f5f9; border: 1px dashed #cbd5e1; border-radius: 4px; color: #475569; font-size: 0.72rem; padding: 3px 8px; cursor: pointer;"><i class="fas fa-plus"></i> Add Plot Line Formula</button>

            <div style="display: flex; align-items: center; justify-content: flex-start; margin-top: 4px; margin-bottom: 4px;">
                <input type="hidden" class="val-graph-variables" value="${savedValues.variables || 'x,y'}">
                
                <div style="display: flex; align-items: center; padding: 6px 0;">
                    <label style="font-size: 0.75rem; color: #475569; display: flex; align-items: center; gap: 6px; cursor: pointer;">
                        <input type="checkbox" class="val-graph-show-grid" ${showGridChecked ? 'checked' : ''} style="cursor: pointer;"> Visualize Grid Layout
                    </label>
                </div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 4px; border-top: 1px dashed #cbd5e1; padding-top: 6px; margin-top: 4px;">
                <span style="font-size: 0.72rem; font-weight: 600; color: #64748b;">Axis Limits Configuration (Leave empty to Auto-Calculate):</span>
                
                <div style="display: grid; grid-template-columns: 45px repeat(3, 1fr); gap: 6px; align-items: center;">
                    <span style="font-size: 0.75rem; color: #475569; font-weight: 500;">X-Axis:</span>
                    <div class="linked-input-wrapper" data-input-key="x_min" data-input-type="double" style="position: relative; display: flex; align-items: center; gap: 2px;">
                        <input type="number" step="any" class="val-graph-x-min" value="${safeNumValue(xMinVal, '')}" placeholder="Min" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                        <button type="button" class="btn-input-link-trigger" style="background:#fff; border:1px solid #cbd5e1; border-radius:4px; color:#94a3b8; font-size:0.65rem; height:22px; width:22px; display:flex; align-items:center; justify-content:center; flex-shrink:0;"><i class="fas fa-link"></i></button>
                    </div>
                    <div class="linked-input-wrapper" data-input-key="x_max" data-input-type="double" style="position: relative; display: flex; align-items: center; gap: 2px;">
                        <input type="number" step="any" class="val-graph-x-max" value="${safeNumValue(xMaxVal, '')}" placeholder="Max" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                        <button type="button" class="btn-input-link-trigger" style="background:#fff; border:1px solid #cbd5e1; border-radius:4px; color:#94a3b8; font-size:0.65rem; height:22px; width:22px; display:flex; align-items:center; justify-content:center; flex-shrink:0;"><i class="fas fa-link"></i></button>
                    </div>
                    <div class="linked-input-wrapper" data-input-key="x_step" data-input-type="double" style="position: relative; display: flex; align-items: center; gap: 2px;">
                        <input type="number" step="any" class="val-graph-x-step" value="${safeNumValue(xStepVal, '')}" placeholder="Step" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                        <button type="button" class="btn-input-link-trigger" style="background:#fff; border:1px solid #cbd5e1; border-radius:4px; color:#94a3b8; font-size:0.65rem; height:22px; width:22px; display:flex; align-items:center; justify-content:center; flex-shrink:0;"><i class="fas fa-link"></i></button>
                    </div>
                </div>

                <div style="display: grid; grid-template-columns: 45px repeat(3, 1fr); gap: 6px; align-items: center;">
                    <span style="font-size: 0.75rem; color: #475569; font-weight: 500;">Y-Axis:</span>
                    <div class="linked-input-wrapper" data-input-key="y_min" data-input-type="double" style="position: relative; display: flex; align-items: center; gap: 2px;">
                        <input type="number" step="any" class="val-graph-y-min" value="${safeNumValue(yMinVal, '')}" placeholder="Min" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                        <button type="button" class="btn-input-link-trigger" style="background:#fff; border:1px solid #cbd5e1; border-radius:4px; color:#94a3b8; font-size:0.65rem; height:22px; width:22px; display:flex; align-items:center; justify-content:center; flex-shrink:0;"><i class="fas fa-link"></i></button>
                    </div>
                    <div class="linked-input-wrapper" data-input-key="y_max" data-input-type="double" style="position: relative; display: flex; align-items: center; gap: 2px;">
                        <input type="number" step="any" class="val-graph-y-max" value="${safeNumValue(yMaxVal, '')}" placeholder="Max" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                        <button type="button" class="btn-input-link-trigger" style="background:#fff; border:1px solid #cbd5e1; border-radius:4px; color:#94a3b8; font-size:0.65rem; height:22px; width:22px; display:flex; align-items:center; justify-content:center; flex-shrink:0;"><i class="fas fa-link"></i></button>
                    </div>
                    <div class="linked-input-wrapper" data-input-key="y_step" data-input-type="double" style="position: relative; display: flex; align-items: center; gap: 2px;">
                        <input type="number" step="any" class="val-graph-y-step" value="${safeNumValue(yStepVal, '')}" placeholder="Step" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                        <button type="button" class="btn-input-link-trigger" style="background:#fff; border:1px solid #cbd5e1; border-radius:4px; color:#94a3b8; font-size:0.65rem; height:22px; width:22px; display:flex; align-items:center; justify-content:center; flex-shrink:0;"><i class="fas fa-link"></i></button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function bindEvents({ card, updateWorkspaceSimulationPreview }) {
    if (!card) return null;

    const container = card.querySelector('.graph-formulas-container');
    const addBtn = card.querySelector('.btn-add-graph-formula');
    if (!container || !addBtn) return null;

    addBtn.addEventListener('click', function() {
        const rowIndex = container.querySelectorAll('.graph-formula-row').length;
        const row = document.createElement('div');
        row.className = 'graph-formula-row';
        row.style.cssText = 'display: flex; align-items: center; gap: 4px; width: 100%; margin-top: 4px;';
        row.innerHTML = `
            <div class="linked-input-wrapper" data-input-key="formula_${rowIndex}" data-input-type="text" style="position: relative; display: flex; align-items: center; gap: 4px; flex-grow: 1;">
                <input type="text" class="val-graph-formula-expr" value="" placeholder="e.g. y = x^2 or 3*x" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>
            <button type="button" class="btn-remove-graph-formula" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem;"><i class="fas fa-minus-circle"></i></button>
        `;
        container.appendChild(row);

        if (typeof updateWorkspaceSimulationPreview === 'function') {
            updateWorkspaceSimulationPreview();
        }
    });

    container.addEventListener('click', function(e) {
        const removeBtn = e.target.closest('.btn-remove-graph-formula');
        if (removeBtn) {

            const row = removeBtn.closest('.graph-formula-row');
            row.remove();

            const remainingRows = container.querySelectorAll('.val-graph-formula-expr');

            if (typeof updateWorkspaceSimulationPreview === 'function') {
                updateWorkspaceSimulationPreview();
            }

            if (remainingRows.length > 0) {
                remainingRows[0].dispatchEvent(new Event('input', { bubbles: true }));
            } else {
                const neighboringInput = card.querySelector('.val-graph-x-min');
                if (neighboringInput) {
                    neighboringInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }

        }
    });

    return true;
}

function evaluate({ card, visitedTokens = [], getLiveComponentValue }) {
    if (!card || typeof getLiveComponentValue !== 'function') return null;

    const graphNodes = getLiveComponentValue(card, 'nodes', '[]', visitedTokens);
    const graphEdges = getLiveComponentValue(card, 'edges', '[]', visitedTokens);
    const graphData = getLiveComponentValue(card, 'data', '', visitedTokens);


    if (graphData && graphData !== '') {
        return graphData;
    }
    return `Graph(${graphNodes || 'empty'}, ${graphEdges || 'empty'})`;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;


    const xMinVal = parseFloat(card.querySelector('.val-graph-x-min')?.value) || -5;
    const xMaxVal = parseFloat(card.querySelector('.val-graph-x-max')?.value) || 5;
    const xStepVal = parseFloat(card.querySelector('.val-graph-x-step')?.value) || 0.5;

    const yMinVal = parseFloat(card.querySelector('.val-graph-y-min')?.value) || -5;
    const yMaxVal = parseFloat(card.querySelector('.val-graph-y-max')?.value) || 5;
    const yStepVal = parseFloat(card.querySelector('.val-graph-y-step')?.value) || 0.5;

    const isGridChecked = card.querySelector('.val-graph-show-grid')?.checked ?? true;

    inputsCollected["x-axis range"] = [xMinVal, xMaxVal, xStepVal];
    inputsCollected["y-axis range"] = [yMinVal, yMaxVal, yStepVal];
    inputsCollected["show_grid"] = isGridChecked;
    inputsCollected["show_grid_overlay"] = isGridChecked;

    let purgeIdx = 0;
    while (inputsCollected[`formula_${purgeIdx}`] !== undefined) {
        delete inputsCollected[`formula_${purgeIdx}`];
        purgeIdx++;
    }

    const activeFormulas = [];
    const formulaWrappers = card.querySelectorAll('.graph-formulas-container .linked-input-wrapper');

    formulaWrappers.forEach((wrapper, index) => {
        let finalRowVal = "";
        const boundToken = wrapper.getAttribute('data-bound-token');
        const exprInput = wrapper.querySelector('.val-graph-formula-expr');

        if (boundToken) {
            finalRowVal = cleanTokenBrackets(boundToken);
            if (exprInput) {
                exprInput.style.display = 'none';
            }
        } else if (exprInput) {
            finalRowVal = exprInput.value.trim();
            exprInput.style.display = '';
        }

        if (finalRowVal) {
            activeFormulas.push(finalRowVal);
            inputsCollected[`formula_${index}`] = finalRowVal;
        }
    });

    inputsCollected["formulas"] = activeFormulas;

    return inputsCollected;
}

function sanitizeFormulas(graphConfig) {
    if (graphConfig && graphConfig.formulas) {
        graphConfig.formulas = graphConfig.formulas.map(fStr => {
            let rhs = fStr.split('=')[1] || fStr;
            return rhs.replace(/\*\*/g, '^').trim();
        });
    }
    return graphConfig;
}

function applyBatchSync({ card, result, renderGraphComponentCanvas, token }) {
    if (!card || !result) return null;

    let targetDisplay = ensureLatexRenderBox(card);
    if (!targetDisplay) return null;

    try {
        let rawOutput = result.evaluated_output;
        const tokenId = token || card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token') || 'graph';


        if (typeof rawOutput === 'string' && rawOutput.startsWith('[Invalid')) {
            targetDisplay.style.textAlign = 'center';
            targetDisplay.innerHTML = `<span style="color: #dc2626; font-size: 0.85rem;">⚠️ ${rawOutput.replace(/[\[\]]/g, '')}</span>`;
            return true;
        }

        let graphConfig = rawOutput;
        if (typeof graphConfig === 'string') {
            graphConfig = JSON.parse(graphConfig);
        }


        targetDisplay.textContent = '';
        targetDisplay.style.textAlign = 'left';

        const canvasId = `graph-plot-${tokenId}`;
        let canvasContainer = document.getElementById(canvasId);
        if (!canvasContainer) {
            canvasContainer = document.createElement('div');
            canvasContainer.id = canvasId;
            canvasContainer.style.cssText = 'margin: 10px auto; width: 100%; max-width: 340px; height: 240px;';
            targetDisplay.appendChild(canvasContainer);
        }
        canvasContainer.innerHTML = '';

        const formulasArray = graphConfig.formulas || [];
        if (formulasArray.length === 0) {
            canvasContainer.style.display = 'none';
            targetDisplay.style.textAlign = 'center';
            targetDisplay.innerHTML = `<span style="color: #64748b; font-size: 0.85rem; font-style: italic;">Enter a function formula above to render graph...</span>`;
            return true;
        } else {
            canvasContainer.style.display = 'block';
        }

        graphConfig = sanitizeFormulas(graphConfig);
        if (typeof renderGraphComponentCanvas === 'function') {
            renderGraphComponentCanvas(canvasId, graphConfig);
        } else {
            throw new Error("The global abstraction engine 'renderGraphComponentCanvas' is missing.");
        }
    } catch (err) {
        console.error("Graph canvas render failed:", err);
        targetDisplay.style.textAlign = 'center';
        targetDisplay.innerHTML = `<span style="color: #dc2626; font-size: 0.85rem;">⚠️ System error compiling graph visualization structure.</span>`;
    }

    return true;
}

function parseGraphConfigPayload(raw) {
    if (raw == null || raw === '') return null;
    if (typeof raw === 'object') {
        return raw.archetype === 'graph' ? raw : null;
    }
    if (typeof raw !== 'string') return null;
    const trimmed = raw.trim();
    // Placeholder latex_output / token names / legacy evaluate strings are not manifests
    if (!trimmed.startsWith('{')) return null;
    const parsed = JSON.parse(trimmed);
    return (parsed && parsed.archetype === 'graph') ? parsed : null;
}

function renderPreviewToken({
    displayVal,
    cleanToken,
    renderGraphComponentCanvas,
    card,
    registerPreviewGraph,
    previewInstanceId
}) {
    let sawJsonParseError = null;
    let graphConfig = null;

    try {
        graphConfig = parseGraphConfigPayload(displayVal);
    } catch (err) {
        sawJsonParseError = err;
        graphConfig = null;
    }

    // Fall back to the batch-sync JSON stored on the card (evaluated_output)
    if (!graphConfig && card) {
        try {
            graphConfig = parseGraphConfigPayload(card.getAttribute('data-simulated-value'));
        } catch (err) {
            sawJsonParseError = sawJsonParseError || err;
            graphConfig = null;
        }
    }

    // Quill hydration / text-change often runs before batch sync lands the JSON.
    // Treat that as a quiet pending state, not a hard failure.
    if (!graphConfig) {
        if (sawJsonParseError) {
            console.error("Malformed graph JSON; cannot render preview:", sawJsonParseError);
            return `<span style="color: #ef4444; font-family: monospace;">[Malformed Graph State Data]</span>`;
        }
        return `
            <div class="simulated-live-graph-preview-container" data-graph-token="${cleanToken}" data-graph-pending="1" style="display: block; margin: 8px auto; width: 100%; max-width: 360px; padding: 12px 8px; box-sizing: border-box; background: #ffffff; border: 1px dashed #cbd5e1; border-radius: 8px; text-align: center;">
                <span style="color: #94a3b8; font-size: 0.8rem; font-style: italic;">Graph preview loading…</span>
            </div>
        `;
    }

    // Unique per occurrence so duplicate tokens / nested+outer cells don't collide
    const previewCanvasId = previewInstanceId
        || `live-preview-canvas-${cleanToken}-${Math.random().toString(36).slice(2, 9)}`;

    graphConfig = sanitizeFormulas(graphConfig);

    if (typeof registerPreviewGraph === 'function') {
        // Prefer deferred paint after preview HTML is inserted (needed for table cells)
        registerPreviewGraph({ canvasId: previewCanvasId, graphConfig, cleanToken });
    } else if (typeof renderGraphComponentCanvas === 'function') {
        setTimeout(() => {
            renderGraphComponentCanvas(previewCanvasId, graphConfig);
        }, 0);
    }

    return `
        <div class="simulated-live-graph-preview-container" data-graph-token="${cleanToken}" style="display: block; margin: 8px auto; width: 100%; max-width: 360px; padding: 4px; box-sizing: border-box; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;">
            <div id="${previewCanvasId}" class="live-preview-graph-canvas" style="width: 100%; height: 240px; min-height: 120px; box-sizing: border-box;"></div>
        </div>
    `;
}

function isLinkCompatible({ inputKey, targetTypeAttr, derivedOutputs }) {
    if (targetTypeAttr === 'text' && inputKey && inputKey.startsWith('formula_')) {
        if (derivedOutputs.includes('formula') || derivedOutputs.includes('double') || derivedOutputs.includes('integer')) {
            return true;
        }
    }
    return null;
}
