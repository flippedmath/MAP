import {
    ensureLatexRenderBox,
    extractVariablesFromFormulaString,
    triggerCardLiveSync
} from './helpers.js';

/**
 * matrix entity module — grid matrix with operations and substitutions.
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
        case 'applyBatchSync':
            return applyBatchSync(contextData);
        case 'renderPreviewToken':
            return renderPreviewToken(contextData);
        case 'getOutputTypes':
            return ['matrix'];
        case 'hideRefreshButton':
            return false;
        case 'needsLatexRenderBox':
            return true;
        case 'initGlobalListeners':
            return initGlobalListeners();
        default:
            return null;
    }
}

function getFieldsHtml(savedValues) {
    const rowCount = parseInt(savedValues.rows) || 3;
    const colCount = parseInt(savedValues.columns) || 3;
    const currentCalcMode = savedValues.calculate || 'leave as matrix';

    const linkedMatrixToken = savedValues.linked_matrix || '';
    const isLinked = !!linkedMatrixToken;
    const linkedMatrixBToken = savedValues['matrix B'] || '';

    let rawGrid = savedValues.matrix_data;
    if (!Array.isArray(rawGrid)) {
        rawGrid = Array.from({ length: rowCount }, (_, r) =>
            Array.from({ length: colCount }, (_, c) => (r === c ? "1" : "0"))
        );
    }

    return `
        <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">
            
            <div class="linked-input-wrapper" data-input-key="linked_matrix" data-input-type="matrix" style="position: relative; display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; box-sizing: border-box; background: #f1f5f9; padding: 6px 8px; border-radius: 4px; border: 1px dashed #cbd5e1;">
                <div style="display: flex; flex-direction: column; min-width: 0; flex-grow: 1;">
                    <span style="font-size: 0.75rem; font-weight: 600; color: #334155;">Link Source Matrix Override</span>
                    <span class="link-status-text" style="font-size: 0.75rem; color: ${isLinked ? '#0284c7' : '#64748b'}; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                        ${isLinked ? `Linked to: ${linkedMatrixToken}` : 'Local Grid Active (Unlinked)'}
                    </span>
                </div>
                <input type="hidden" class="val-matrix-linked" value="${linkedMatrixToken}">
                <div style="position: relative; display: flex; align-items: center; flex-shrink: 0;">
                    <button type="button" class="btn-input-link-trigger ${isLinked ? 'is-linked' : ''}" title="Link matrix token" style="background: #ffffff; border: 1px solid ${isLinked ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${isLinked ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 28px; width: 28px; display: flex; align-items: center; justify-content: center; box-sizing: border-box;">
                        <i class="fas ${isLinked ? 'fa-times' : 'fa-link'}"></i>
                    </button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: auto; right: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 150px; padding: 4px 0; margin-top: 4px; box-sizing: border-box;"></div>
                </div>
            </div>

            <div class="row-variable-substitutions" style="display: flex; flex-direction: column; gap: 6px; width: 100%; border-bottom: 1px dashed #cbd5e1; padding-bottom: 8px; box-sizing: border-box;">
                <span style="font-size: 0.72rem; font-weight: 600; color: #475569;">Matrix Variable Substitutions:</span>
                <div class="substitutions-list-container" style="display: flex; flex-direction: column; gap: 6px;">
                </div>
                <div class="substitution-picker-wrapper" style="display: flex; align-items: center; gap: 6px; margin-top: 2px;">
                    <span style="font-size: 0.75rem; color: #64748b;">Assign value to:</span>
                    <select class="picker-unused-variables" style="flex-grow: 1; font-size: 0.75rem; padding: 3px; border: 1px dashed #cbd5e1; border-radius: 4px; color: #475569; background: white;">
                    </select>
                </div>
            </div>

            <div class="matrix-local-grid-config-group" style="display: ${isLinked ? 'none' : 'flex'}; flex-direction: column; gap: 8px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px; box-sizing: border-box; width: 100%;">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; width: 100%; box-sizing: border-box;">
                    <div class="linked-input-wrapper" data-input-key="rows" data-input-type="integer" style="box-sizing: border-box;">
                        <label style="font-size: 0.75rem; color: #475569; display: block; width: 100%;">Grid Rows:
                            <input type="number" min="1" max="10" class="val-matrix-rows" value="${rowCount}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                        </label>
                    </div>
                    <div class="linked-input-wrapper" data-input-key="columns" data-input-type="integer" style="box-sizing: border-box;">
                        <label style="font-size: 0.75rem; color: #475569; display: block; width: 100%;">Grid Columns:
                            <input type="number" min="1" max="10" class="val-matrix-columns" value="${colCount}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                        </label>
                    </div>
                </div>

                <div class="linked-input-wrapper" data-input-key="matrix_data" data-input-type="grid" style="display: flex; flex-direction: column; gap: 4px; width: 100%; box-sizing: border-box;">
                    <span style="font-size: 0.75rem; font-weight: 500; color: #475569;">Matrix Indices Values:</span>
                    <div class="matrix-grid-cells-container" style="display: grid; grid-template-columns: repeat(${colCount}, 1fr); gap: 4px; width: 100%; max-height: 180px; overflow-y: auto; padding: 2px; box-sizing: border-box;">
                        ${Array.from({ length: rowCount }).map((_, r) =>
                            Array.from({ length: colCount }).map((_, c) => {
                                const val = (rawGrid[r] && rawGrid[r][c] !== undefined) ? rawGrid[r][c] : '0';
                                return `<input type="text" class="val-matrix-cell" data-row="${r}" data-col="${c}" value="${val}" style="width:100%; box-sizing:border-box; text-align:center; font-size:0.77rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px; font-family:monospace;">`;
                            }).join('')
                        ).join('')}
                    </div>
                </div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr; gap: 8px; border-top: 1px dashed #cbd5e1; padding-top: 8px; box-sizing: border-box; width: 100%;">
                <div class="linked-input-wrapper" data-input-key="calculate" data-input-type="text" style="display: flex; flex-direction: column; gap: 4px; box-sizing: border-box; width: 100%;">
                    <label style="font-size: 0.75rem; color: #475569; font-weight: 500;">Transformation Operation:</label>
                    <select class="val-matrix-calculate" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                        <option value="leave as matrix" ${currentCalcMode === 'leave as matrix' ? 'selected' : ''}>leave as matrix</option>
                        <option value="simplify" ${currentCalcMode === 'simplify' ? 'selected' : ''}>simplify</option>
                        <option value="multiply" ${currentCalcMode === 'multiply' ? 'selected' : ''}>multiply (AxB)</option>
                        <option value="add" ${currentCalcMode === 'add' ? 'selected' : ''}>add</option>
                        <option value="subtract" ${currentCalcMode === 'subtract' ? 'selected' : ''}>subtract</option>
                        <option value="inversion" ${currentCalcMode === 'inversion' ? 'selected' : ''}>inversion (A^-1)</option>
                        <option value="transpose" ${currentCalcMode === 'transpose' ? 'selected' : ''}>transpose</option>
                        <option value="scalar" ${currentCalcMode === 'scalar' ? 'selected' : ''}>scalar (A*c)</option>
                        <option value="determinate" ${currentCalcMode === 'determinate' ? 'selected' : ''}>determinate</option>
                    </select>
                </div>
            </div>

            <div class="row-matrix-b-dependency linked-input-wrapper" data-input-key="matrix B" data-input-type="matrix" style="display: ${['multiply', 'add', 'subtract'].includes(currentCalcMode) ? 'flex' : 'none'}; position: relative; align-items: center; justify-content: space-between; gap: 8px; width: 100%; box-sizing: border-box; background: #f8fafc; padding: 6px 8px; border-radius: 4px; border: 1px solid #e2e8f0;">
                <div style="display: flex; flex-direction: column; min-width: 0; flex-grow: 1;">
                    <span style="font-size: 0.75rem; font-weight: 600; color: #475569;">Secondary Matrix B Target</span>
                    <span class="matrix-b-status-text" style="font-size: 0.75rem; color: ${linkedMatrixBToken ? '#16a34a' : '#ef4444'}; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                        ${linkedMatrixBToken ? `Linked to: ${linkedMatrixBToken}` : 'Required: Select a matrix (e.g. matrix2)'}
                    </span>
                </div>
                <input type="hidden" class="val-matrix-b-target" value="${linkedMatrixBToken}">
                <div style="position: relative; display: flex; align-items: center; flex-shrink: 0;">
                    <button type="button" class="btn-input-link-trigger ${linkedMatrixBToken ? 'is-linked' : ''}" title="Link matrix token" style="background: #ffffff; border: 1px solid ${linkedMatrixBToken ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${linkedMatrixBToken ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 28px; width: 28px; display: flex; align-items: center; justify-content: center; box-sizing: border-box;">
                        <i class="fas ${linkedMatrixBToken ? 'fa-times' : 'fa-link'}"></i>
                    </button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: auto; right: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 150px; padding: 4px 0; margin-top: 4px; box-sizing: border-box;"></div>
                </div>
            </div>

            <div class="row-matrix-scalar-dependency linked-input-wrapper" data-input-key="scalar" data-input-type="double" style="display: ${currentCalcMode === 'scalar' ? 'flex' : 'none'}; position: relative; align-items: flex-end; gap: 4px; width: 100%; box-sizing: border-box;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1; display: block; width: 100%;">Scalar Factor Multiplier (c): 
                    <input type="number" step="any" class="val-matrix-scalar-factor" value="${savedValues.scalar !== undefined ? savedValues.scalar : 1.0}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            </div>

        </div>
    `;
}

/**
 * Parse saved substitution map from `variables` JSON and/or flat `sub_*` keys.
 */
function parseSavedSubstitutions(savedValues = {}) {
    const map = {};

    const rawVars = savedValues.variables;
    if (rawVars) {
        try {
            const parsed = typeof rawVars === 'string' ? JSON.parse(rawVars) : rawVars;
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                Object.entries(parsed).forEach(([k, v]) => {
                    if (k) map[k] = v;
                });
            }
        } catch (err) {
            console.warn('Matrix: failed to parse saved variables JSON', err);
        }
    }

    Object.entries(savedValues).forEach(([key, value]) => {
        if (key.startsWith('sub_')) {
            const varName = key.replace(/^sub_/, '');
            if (varName) map[varName] = value;
        }
    });

    return map;
}

function isLinkedTokenValue(val) {
    return typeof val === 'string' && !!val.trim().match(/^<([^>]+)>$/);
}

function escapeHtmlAttr(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/**
 * Create (or no-op if duplicate) a matrix substitution row.
 */
function createMatrixSubstitutionRow(card, varName, initialValue = '', silent = false) {
    const substitutionsContainer = card.querySelector('.substitutions-list-container');
    const picker = card.querySelector('.picker-unused-variables');
    if (!substitutionsContainer || !varName) return null;

    if (substitutionsContainer.querySelector(`[data-input-key="sub_${varName}"]`)) {
        return null;
    }

    const row = document.createElement('div');
    row.className = 'substitution-row-item linked-input-wrapper';
    row.setAttribute('data-var-name', varName);
    row.setAttribute('data-input-key', `sub_${varName}`);
    row.setAttribute('data-input-type', 'text');
    row.style.cssText = 'display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; margin-bottom: 6px; background: #ffffff; padding: 4px 6px; border-radius: 4px; border: 1px solid #cbd5e1; box-sizing: border-box;';

    const linked = isLinkedTokenValue(initialValue);
    const displayValue = linked ? '' : (initialValue ?? '');

    row.innerHTML = `
        <div style="display: flex; align-items: center; gap: 6px; flex-grow: 1; min-width: 0;">
            <span style="font-size: 0.8rem; font-family: monospace; font-weight: bold; background: #e2e8f0; padding: 2px 6px; border-radius: 3px; color: #0f172a; flex-shrink: 0;">${escapeHtmlAttr(varName)}</span>
            <span style="color: #94a3b8; font-size: 0.75rem; flex-shrink: 0;">=</span>
            <input type="text" class="val-substitution-input" value="${escapeHtmlAttr(displayValue)}" placeholder="Value or expression" style="flex-grow: 1; border: none; outline: none; font-size: 0.8rem; padding: 2px 4px; min-width: 0;${linked ? ' display: none;' : ''}">
        </div>
        
        <div style="position: relative; display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
            <button type="button" class="btn-input-link-trigger${linked ? ' is-linked' : ''}" title="Link token dependency" style="background: #ffffff; border: 1px solid ${linked ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${linked ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.7rem; height: 24px; width: 24px; display: flex; align-items: center; justify-content: center; box-sizing: border-box;">
                <i class="fas ${linked ? 'fa-times' : 'fa-link'}"></i>
            </button>
            <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: auto; right: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 4px; box-sizing: border-box;"></div>
            
            <button type="button" class="btn-delete-substitution-row" title="Remove assignment" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.85rem; padding: 2px; display: flex; align-items: center; justify-content: center; transition: color 0.15s;">
                <i class="fas fa-times-circle"></i>
            </button>
        </div>
    `;

    if (linked) {
        const cleanToken = initialValue.trim();
        row.setAttribute('data-bound-token', cleanToken);
        const pill = document.createElement('span');
        pill.className = 'linked-token-pill';
        pill.setAttribute('data-indexed-token', cleanToken.replace(/[<>]/g, ''));
        pill.style.cssText = 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; font-family: monospace; font-size: 0.75rem; font-weight: bold; padding: 2px 6px; border-radius: 4px; margin-left: 4px; display: inline-block;';
        pill.textContent = cleanToken;
        const innerFlex = row.firstElementChild;
        if (innerFlex) innerFlex.appendChild(pill);
    }

    const delBtn = row.querySelector('.btn-delete-substitution-row');
    delBtn.addEventListener('click', function(event) {
        event.stopPropagation();
        row.remove();

        if (picker) {
            const opt = document.createElement('option');
            opt.value = varName;
            opt.textContent = varName;
            picker.appendChild(opt);
            picker.parentElement.style.display = 'flex';
        }

        // Must sync through a real form control so latex-render-box updates
        triggerCardLiveSync(card);
    });

    substitutionsContainer.appendChild(row);

    if (picker) {
        const selectedOption = picker.querySelector(`option[value="${varName}"]`);
        if (selectedOption) selectedOption.remove();
        if (picker.options.length <= 1) {
            picker.parentElement.style.display = 'none';
        }
    }

    if (!silent) {
        triggerCardLiveSync(card);
    }

    return row;
}

/**
 * Collect free variables from all matrix cells using shared formula extraction rules.
 */
function extractVariablesFromMatrixCells(card) {
    const vars = new Set();
    card.querySelectorAll('.val-matrix-cell').forEach(cell => {
        extractVariablesFromFormulaString(cell.value).forEach(v => vars.add(v));
    });
    return [...vars].sort();
}

/**
 * Refresh the unused-variables picker from cell formulas, excluding already-assigned rows.
 */
function refreshMatrixUnusedVariablesPicker(card, allVars = null) {
    const picker = card.querySelector('.picker-unused-variables');
    const substitutionsContainer = card.querySelector('.substitutions-list-container');
    if (!picker || !substitutionsContainer) return;

    const discovered = allVars || extractVariablesFromMatrixCells(card);
    const assigned = Array.from(substitutionsContainer.querySelectorAll('.substitution-row-item'))
        .map(row => row.getAttribute('data-var-name'))
        .filter(Boolean);
    const unused = discovered.filter(v => !assigned.includes(v));

    if (unused.length === 0) {
        picker.parentElement.style.display = 'none';
        picker.innerHTML = '<option value="">-- N/A --</option>';
    } else {
        picker.parentElement.style.display = 'flex';
        picker.innerHTML = '<option value="">-- N/A --</option>';
        unused.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v;
            opt.textContent = v;
            picker.appendChild(opt);
        });
    }
}

function bindEvents({ card, savedValues = {} }) {
    if (!card) return null;

    const rowsInput = card.querySelector('.val-matrix-rows');
    const colsInput = card.querySelector('.val-matrix-columns');
    const cellsContainer = card.querySelector('.matrix-grid-cells-container');
    const linkedMatrixInput = card.querySelector('.val-matrix-linked');
    const localGridGroup = card.querySelector('.matrix-local-grid-config-group');
    const calcSelect = card.querySelector('.val-matrix-calculate');

    const matrixBRow = card.querySelector('.row-matrix-b-dependency');
    const scalarRow = card.querySelector('.row-matrix-scalar-dependency');

    const reconstructGrid = () => {
        if (!rowsInput || !colsInput || !cellsContainer) return;

        const rCount = Math.max(1, Math.min(10, parseInt(rowsInput.value) || 3));
        const cCount = Math.max(1, Math.min(10, parseInt(colsInput.value) || 3));

        const valueCache = {};
        card.querySelectorAll('.val-matrix-cell').forEach(cell => {
            const r = cell.getAttribute('data-row');
            const c = cell.getAttribute('data-col');
            valueCache[`${r}_${c}`] = cell.value;
        });

        cellsContainer.style.gridTemplateColumns = `repeat(${cCount}, 1fr)`;

        let newCellsHtml = '';
        for (let r = 0; r < rCount; r++) {
            for (let c = 0; c < cCount; c++) {
                const cachedVal = valueCache[`${r}_${c}`];
                const defaultVal = cachedVal !== undefined ? cachedVal : (r === c ? "1" : "0");

                newCellsHtml += `
                    <input type="text" class="val-matrix-cell" data-row="${r}" data-col="${c}" value="${defaultVal}" placeholder="0" title="Row ${r + 1}, Col ${c + 1}" style="width:100%; box-sizing:border-box; text-align:center; font-size:0.77rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px; font-family:monospace;">
                `;
            }
        }
        cellsContainer.innerHTML = newCellsHtml;
        refreshMatrixUnusedVariablesPicker(card);
    };

    if (rowsInput) rowsInput.addEventListener('input', reconstructGrid);
    if (colsInput) colsInput.addEventListener('input', reconstructGrid);

    card.addEventListener('input', function(e) {
        if (e.target === linkedMatrixInput) {
            const hasLink = !!linkedMatrixInput.value.trim();
            localGridGroup.style.display = hasLink ? 'none' : 'flex';
        }

        if (e.target === calcSelect) {
            const mode = calcSelect.value;

            if (matrixBRow) {
                matrixBRow.style.display = ['multiply', 'add', 'subtract'].includes(mode) ? 'flex' : 'none';
            }
            if (scalarRow) {
                scalarRow.style.display = (mode === 'scalar') ? 'flex' : 'none';
            }
        }

        // Shared formula rules: typing expressions in cells updates substitution picker
        if (e.target && e.target.classList.contains('val-matrix-cell')) {
            refreshMatrixUnusedVariablesPicker(card);
        }
    });

    // Restore substitution rows from saved workspace payload
    const savedSubs = parseSavedSubstitutions(savedValues);
    Object.entries(savedSubs).forEach(([varName, value]) => {
        createMatrixSubstitutionRow(card, varName, value, true);
    });

    // Seed picker from cell formulas (same extractor as formula entity)
    refreshMatrixUnusedVariablesPicker(card);

    return true;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    const token = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token') || 'matrix';
    console.group(`%c💾 [Serializer] Packaging Matrix Payload for [${token}]`, "background: #0284c7; color: white; padding: 2px 6px; border-radius: 4px;");

    const rowsInput = card.querySelector('.val-matrix-rows');
    const colsInput = card.querySelector('.val-matrix-columns');

    const rowCount = parseInt(rowsInput?.value) || 3;
    const colCount = parseInt(colsInput?.value) || 3;

    const structureGrid = Array.from({ length: rowCount }, () =>
        Array.from({ length: colCount }, () => "0")
    );

    card.querySelectorAll('.val-matrix-cell').forEach(cell => {
        const r = parseInt(cell.getAttribute('data-row'));
        const c = parseInt(cell.getAttribute('data-col'));

        if (r < rowCount && c < colCount) {
            structureGrid[r][c] = cell.value.trim() || "0";
        }
    });

    inputsCollected["rows"] = rowCount;
    inputsCollected["columns"] = colCount;
    inputsCollected["matrix_data"] = structureGrid;

    inputsCollected["calculate"] = card.querySelector('.val-matrix-calculate')?.value || "leave as matrix";
    inputsCollected["matrix B"] = card.querySelector('.val-matrix-b-target')?.value || "";
    inputsCollected["scalar"] = card.querySelector('.val-matrix-scalar-factor')?.value || "1.0";

    const substitutions = {};
    const subsContainer = card.querySelector('.substitutions-list-container');

    if (subsContainer) {
        subsContainer.querySelectorAll('.substitution-row-item').forEach(row => {
            const vName = row.getAttribute('data-var-name');
            if (!vName) return;

            const boundToken = row.getAttribute('data-bound-token');
            const nativeInput = row.querySelector('.val-substitution-input');
            let rawValue = "";

            if (boundToken) {
                rawValue = boundToken;
            } else if (nativeInput) {
                rawValue = nativeInput.value;
            }

            if (rawValue && rawValue.trim() !== "") {
                let cleanString = rawValue.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();

                const looksLikeToken = /^[a-zA-Z]+\d+$/.test(cleanString.replace(/[<>]/g, ''));
                if (boundToken || looksLikeToken) {
                    cleanString = cleanString.replace(/[<>]/g, '');
                    substitutions[vName] = `<${cleanString}>`;
                } else {
                    substitutions[vName] = cleanString;
                }
            } else {
                substitutions[vName] = "";
            }
        });
    }

    inputsCollected["variables"] = Object.keys(substitutions).length > 0 ? JSON.stringify(substitutions) : "";

    // Also emit flat sub_* keys so save-workspace / rehydrate mirrors formula persistence
    Object.keys(inputsCollected).forEach(key => {
        if (key.startsWith('sub_')) delete inputsCollected[key];
    });
    Object.entries(substitutions).forEach(([k, v]) => {
        inputsCollected[`sub_${k}`] = v;
    });

    if ("entries" in inputsCollected) {
        delete inputsCollected["entries"];
    }

    console.log("Compiled 2D grid matrix configuration:", structureGrid);
    console.log("Compiled Matrix Variables payload dictionary:", inputsCollected["variables"]);
    console.groupEnd();

    return inputsCollected;
}

function applyBatchSync({ card, result, token }) {
    if (!card || !result) return null;

    const targetDisplay = ensureLatexRenderBox(card);
    if (!targetDisplay) return null;

    const tokenId = token || card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token') || 'matrix';
    console.group(`%c🔄 [Batch Sync] Redrawing Matrix Component Card (${tokenId})`, "background: #0284c7; color: white; padding: 2px 6px; border-radius: 4px;");

    let rawOutput = result.evaluated_output;

    if (typeof rawOutput === 'string' && rawOutput.startsWith('[Invalid')) {
        targetDisplay.style.textAlign = 'center';
        targetDisplay.innerHTML = `<span style="color: #dc2626; font-size: 0.85rem;">⚠️ ${rawOutput.replace(/[\[\]]/g, '')}</span>`;
        console.groupEnd();
        return true;
    }

    if (result.latex_output && typeof katex !== 'undefined') {
        targetDisplay.style.textAlign = 'center';
        targetDisplay.textContent = '';
        katex.render(result.latex_output, targetDisplay, { throwOnError: false });
    } else {
        targetDisplay.style.textAlign = 'center';
        targetDisplay.style.fontFamily = 'monospace';
        targetDisplay.style.fontSize = '0.85rem';
        targetDisplay.textContent = rawOutput;
    }

    // Keep substitution picker aligned with free vars reported by the engine
    if (result.extracted_variables !== undefined) {
        const fromServer = result.extracted_variables
            ? result.extracted_variables.split(',').map(v => v.trim()).filter(Boolean)
            : [];
        const fromCells = extractVariablesFromMatrixCells(card);
        refreshMatrixUnusedVariablesPicker(card, [...new Set([...fromServer, ...fromCells])].sort());
    }

    console.groupEnd();
    return true;
}

function renderPreviewToken({ displayVal }) {
    // displayVal is expected to be LaTeX when preview path uses formulaLiveLatexCache
    return `<span class="simulated-math-formula-render" style="display: inline-block; padding: 2px 4px;">${displayVal}</span>`;
}

let globalListenersInitialized = false;

function initGlobalListeners() {
    if (globalListenersInitialized) return true;
    globalListenersInitialized = true;

    document.body.addEventListener('change', function(e) {
        const picker = e.target.closest('.picker-unused-variables');
        if (!picker) return;

        const card = picker.closest('.workspace-block-card, .workspace-component-card');
        const deleteBtn = card?.querySelector('.btn-delete-workspace-component');
        const isMatrixCard = deleteBtn?.getAttribute('data-token') === 'matrix';

        if (!isMatrixCard) return;

        const pickedVar = picker.value;
        if (!pickedVar || pickedVar === '-- N/A --') return;

        createMatrixSubstitutionRow(card, pickedVar, '', false);
        picker.value = "";
    });

    return true;
}
