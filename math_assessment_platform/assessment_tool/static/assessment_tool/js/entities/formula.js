import { ensureLatexRenderBox, escapeHtmlText, extractVariablesFromFormulaString } from './helpers.js';

/**
 * formula entity module — expression editor with solve methods and substitutions.
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
            return ['double', 'integer', 'formula'];
        case 'hideRefreshButton':
            return false;
        case 'needsLatexRenderBox':
            return true;
        default:
            return null;
    }
}

function getFieldsHtml(savedValues) {
    return `
        <div style="display: flex; flex-direction: column; gap: 8px; width: 100%;">
            
            <div class="linked-input-wrapper" data-input-key="formula" data-input-type="formula" style="position: relative; display: flex; align-items: flex-end; gap: 4px; width: 100%;">
                <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Formula expression string: 
                    <input type="text" class="val-input-formula" value="${savedValues.formula || ''}" placeholder="e.g. 3*x + 5" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                <div class="linked-input-wrapper" data-input-key="solve method" data-input-type="text" style="display: flex; flex-direction: column; gap: 4px;">
                    <label style="font-size: 0.75rem; color: #475569;">Solve Method:</label>
                    <select class="val-input-solve-method" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                        <option value="leave as formula" ${(savedValues['solve method'] || 'leave as formula') === 'leave as formula' ? 'selected' : ''}>leave as formula</option>
                        <option value="simplify" ${savedValues['solve method'] === 'simplify' ? 'selected' : ''}>simplify</option>
                        <option value="expand polynomial" ${savedValues['solve method'] === 'expand polynomial' ? 'selected' : ''}>expand polynomial</option>
                        <option value="factor polynomial" ${savedValues['solve method'] === 'factor polynomial' ? 'selected' : ''}>factor polynomial</option>
                        <option value="variable substitution" ${savedValues['solve method'] === 'variable substitution' ? 'selected' : ''}>variable substitution</option>
                    </select>
                </div>

                <div class="linked-input-wrapper" data-input-key="variables" data-input-type="text">
                    <label style="font-size: 0.75rem; color: #475569; display: block; width: 100%;">Variables (automatically extracted): 
                        <input type="text" class="val-input-variables" value="${savedValues.variables || ''}" placeholder="e.g. x, y" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;" disabled readonly>
                    </label>
                </div>
            </div>

            <div class="row-simplify-target linked-input-wrapper" data-input-key="variable to simplify" data-input-type="text" style="display: none; flex-direction: column; gap: 4px; width: 100%;">
                <label style="font-size: 0.75rem; color: #475569; width: 100%;">Target Variable to Simplify: 
                    <select class="val-input-simplify-target" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                    </select>
                </label>
            </div>

            <div class="row-substitution-target linked-input-wrapper" data-input-key="variable to substitute" data-input-type="text" style="display: none; flex-direction: column; gap: 4px; width: 100%;">
                <label style="font-size: 0.75rem; color: #475569; width: 100%;">Target Variable to Replace: 
                    <select class="val-input-substitution-target" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                    </select>
                </label>
            </div>

            <div class="row-variable-substitutions" style="display: none; flex-direction: column; gap: 6px; width: 100%; border-top: 1px dashed #cbd5e1; padding-top: 8px;">
                <span style="font-size: 0.72rem; font-weight: 600; color: #475569;">Variable Substitutions / Evaluations:</span>
                <div class="substitutions-list-container" style="display: flex; flex-direction: column; gap: 6px;"></div>
                <div class="substitution-picker-wrapper" style="display: flex; align-items: center; gap: 6px; margin-top: 2px;">
                    <span style="font-size: 0.75rem; color: #64748b;">Assign value to:</span>
                    <select class="picker-unused-variables" style="flex-grow: 1; font-size: 0.75rem; padding: 3px; border: 1px dashed #cbd5e1; border-radius: 4px; color: #475569;">
                    </select>
                </div>
            </div>

        </div>
    `;
}

function bindEvents({ card, savedValues = {}, updateWorkspaceSimulationPreview }) {
    if (!card) return null;

    // Live preview on any keystroke inside the formula card
    card.addEventListener('input', function() {
        if (typeof updateWorkspaceSimulationPreview === 'function') {
            updateWorkspaceSimulationPreview();
        }
    });

    bindLiveFormulaEvaluation(card, savedValues || {});
    return true;
}

function bindLiveFormulaEvaluation(card, savedValues = {}) {
    if (card.getAttribute('data-formula-listener-bound') === 'true') {
        return;
    }
    card.setAttribute('data-formula-listener-bound', 'true');

    const variablesField = card.querySelector('.val-input-variables');
    const solveMethodSelect = card.querySelector('.val-input-solve-method');

    const simplifyWrapper = card.querySelector('.row-simplify-target');
    const simplifySelect = card.querySelector('.val-input-simplify-target');

    const substitutionsWrapper = card.querySelector('.row-variable-substitutions');
    const substitutionWrapper = card.querySelector('.row-substitution-target');
    const substitutionSelect = card.querySelector('.val-input-substitution-target');

    const substitutionsContainer = card.querySelector('.substitutions-list-container');
    const unusedVariablesPicker = card.querySelector('.picker-unused-variables');

    const initialMethod = solveMethodSelect?.value || "leave as formula";
    card.setAttribute('data-last-method', initialMethod);

    if (variablesField) {
        variablesField.disabled = true;
        variablesField.readOnly = true;
        variablesField.style.backgroundColor = '#f1f5f9';
        variablesField.style.cursor = 'not-allowed';
    }

    function updateVariablesIndexAndSyncUI(preserveExistingVars = false) {
        const formulaInput = card.querySelector('.val-input-formula');
        if (!formulaInput || !variablesField) return;

        if (!preserveExistingVars) {
            const extractedVars = extractVariablesFromFormulaString(formulaInput.value);
            variablesField.value = extractedVars.join(', ');
        }

        syncSolveForDropdown();
        refreshUnusedVariablesPicker();
    }

    function syncSolveForDropdown() {
        const selectedMethod = solveMethodSelect?.value || "leave as formula";
        const previousMethod = card.getAttribute('data-last-method') || "";

        if (previousMethod === 'variable substitution' && selectedMethod !== 'variable substitution') {
            if (substitutionsContainer) substitutionsContainer.innerHTML = '';
            refreshUnusedVariablesPicker();
        }
        card.setAttribute('data-last-method', selectedMethod);

        if (simplifyWrapper) simplifyWrapper.style.display = 'none';
        if (substitutionWrapper) substitutionWrapper.style.display = 'none';
        if (substitutionsWrapper) substitutionsWrapper.style.display = 'none';

        if (selectedMethod === 'simplify') {
            if (simplifyWrapper) simplifyWrapper.style.display = 'flex';
            if (substitutionSelect) substitutionSelect.value = "";

            card.removeAttribute('data-selected-variable');
            if (simplifySelect) simplifySelect.value = "";

            populateVariablesDropdown(simplifySelect);
        }
        else if (selectedMethod === 'variable substitution') {
            if (substitutionsWrapper) substitutionsWrapper.style.display = 'flex';

            if (simplifySelect) simplifySelect.value = "";
            if (substitutionSelect) substitutionSelect.value = "";

            refreshUnusedVariablesPicker();
        }
        else {
            if (simplifySelect) simplifySelect.value = "";
            if (substitutionSelect) substitutionSelect.value = "";
        }
    }

    function populateVariablesDropdown(targetSelectElement) {
        if (!targetSelectElement || !variablesField) return;

        const currentVars = variablesField.value.split(',')
            .map(v => v.trim())
            .filter(v => v.length > 0);

        const savedTarget = savedValues['variable to solve for'] || "";

        targetSelectElement.innerHTML = '<option value="">-- N/A --</option>';
        currentVars.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v;
            opt.textContent = v;
            if (v === savedTarget) {
                opt.selected = true;
            }
            targetSelectElement.appendChild(opt);
        });
    }

    function refreshUnusedVariablesPicker() {
        if (!variablesField || !unusedVariablesPicker) return;

        const allVars = variablesField.value.split(',')
            .map(v => v.trim())
            .filter(v => v.length > 0);

        const currentlyAssignedVars = Array.from(substitutionsContainer.querySelectorAll('.substitution-row-item'))
            .map(row => row.getAttribute('data-var-name'));

        const unusedVars = allVars.filter(v => !currentlyAssignedVars.includes(v));

        if (unusedVars.length === 0) {
            unusedVariablesPicker.parentElement.style.display = 'none';
        } else {
            unusedVariablesPicker.parentElement.style.display = 'flex';
            unusedVariablesPicker.innerHTML = '<option value="">-- N/A --</option>';
            unusedVars.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v;
                opt.textContent = v;
                unusedVariablesPicker.appendChild(opt);
            });
        }
    }

    function createSubstitutionRow(varName, initialValue = "", silent = false) {
        if (substitutionsContainer.querySelector(`[data-var-name="${varName}"]`)) {
            return;
        }

        const row = document.createElement('div');
        row.className = 'substitution-row-item';
        row.setAttribute('data-var-name', varName);
        row.style.cssText = 'display: flex; align-items: center; gap: 6px; width: 100%; margin-bottom: 4px;';

        row.innerHTML = `
            <span style="font-size: 0.8rem; font-family: monospace; font-weight: bold; min-width: 24px; text-align: right; color: #334155;">${varName} =</span>
            
            <div class="linked-input-wrapper" data-input-key="sub_${varName}" data-input-type="text" style="position: relative; display: flex; align-items: center; gap: 4px; flex-grow: 1;">
                <input type="text" class="val-substitution-input" value="${initialValue}" placeholder="Value or expression" style="flex-grow: 1; font-size: 0.8rem; padding: 4px; border: 1px solid #cbd5e1; border-radius: 4px;">
                <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.7rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            </div>

            <button type="button" class="btn-delete-substitution-row" title="Remove assignment" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.8rem; padding: 4px; transition: color 0.15s;"><i class="fas fa-times-circle"></i></button>
        `;

        const delBtn = row.querySelector('.btn-delete-substitution-row');
        delBtn.addEventListener('click', () => {
            row.remove();
            refreshUnusedVariablesPicker();
            card.dispatchEvent(new Event('change', { bubbles: true }));
        });

        substitutionsContainer.appendChild(row);
        refreshUnusedVariablesPicker();
        if (!silent) {
            card.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }

    if (unusedVariablesPicker) {
        unusedVariablesPicker.addEventListener('change', function() {
            const pickedVar = this.value;
            if (!pickedVar) return;
            createSubstitutionRow(pickedVar);
            this.value = "";
        });
    }

    if (savedValues && Object.keys(savedValues).length > 0) {
        if (solveMethodSelect && savedValues['solve method']) {
            solveMethodSelect.value = savedValues['solve method'];
            card.setAttribute('data-last-method', savedValues['solve method']);
        }

        if (variablesField && savedValues['variables']) {
            variablesField.value = savedValues['variables'];
        }

        const incomingVal = savedValues['variable to solve for'] || "";
        if (incomingVal) {
            if (simplifySelect) simplifySelect.setAttribute('data-saved-value', incomingVal);
            if (substitutionSelect) substitutionSelect.setAttribute('data-saved-value', incomingVal);
        }

        updateVariablesIndexAndSyncUI(true);

        Object.entries(savedValues).forEach(([key, vVal]) => {
            if (key.startsWith('sub_')) {
                createSubstitutionRow(key.replace('sub_', ''), vVal, true);
            }
        });
        card.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
        updateVariablesIndexAndSyncUI();
    }

    card.addEventListener('input', (e) => {
        const target = e.target;

        if (!target.matches('.val-input-formula, .val-input-solve-method, .val-input-simplify-target, .val-input-substitution-target, .val-substitution-input')) {
            return;
        }

        if (target.matches('.val-input-simplify-target')) {
            card.setAttribute('data-selected-variable', target.value);
            refreshUnusedVariablesPicker();
            card.dispatchEvent(new Event('change', { bubbles: true }));
            return;
        }

        if (target.matches('.val-substitution-input')) {
            target.setAttribute('value', target.value);
        }

        if (target.matches('.val-input-solve-method')) {
            const solveMethod = target.value;
            const simplifyDropdownContainer = card.querySelector('.val-input-simplify-target')?.closest('.form-group, .input-row, div');

            if (simplifyDropdownContainer) {
                if (solveMethod === 'variable substitution') {
                    simplifyDropdownContainer.style.display = 'none';
                    card.removeAttribute('data-selected-variable');
                } else {
                    simplifyDropdownContainer.style.display = '';
                }
            }
        }

        if (target.matches('.val-input-formula')) {
            updateVariablesIndexAndSyncUI();
        } else {
            syncSolveForDropdown();
            refreshUnusedVariablesPicker();
        }

        card.dispatchEvent(new Event('change', { bubbles: true }));
    });

    if (solveMethodSelect) {
        solveMethodSelect.addEventListener('change', () => {
            syncSolveForDropdown();
            card.dispatchEvent(new Event('change', { bubbles: true }));
        });
    }

    [simplifySelect, substitutionSelect].forEach(selectEl => {
        if (selectEl) {
            selectEl.addEventListener('change', () => {
                card.dispatchEvent(new Event('change', { bubbles: true }));
            });
        }
    });
}

function evaluate({ card, tokenIdentifier, visitedTokens = [], getLiveComponentValue, formulaLiveLatexCache }) {
    if (!card) return null;

    const cache = formulaLiveLatexCache || (typeof window !== 'undefined' ? window.formulaLiveLatexCache : null);
    if (cache && cache[tokenIdentifier]) {
        return cache[tokenIdentifier];
    }

    if (typeof getLiveComponentValue !== 'function') return tokenIdentifier;
    return getLiveComponentValue(card, 'formula', tokenIdentifier, visitedTokens);
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    const solveMethod = card.querySelector('.val-input-solve-method')?.value || "leave as formula";
    inputsCollected["solve method"] = solveMethod;

    const simplifySelect = card.querySelector('.val-input-simplify-target');
    const substitutionSelect = card.querySelector('.val-input-substitution-target');

    const simplifyVal = simplifySelect && simplifySelect.selectedIndex >= 0 ?
        simplifySelect.options[simplifySelect.selectedIndex].value : "";

    const substitutionVal = substitutionSelect && substitutionSelect.selectedIndex >= 0 ?
        substitutionSelect.options[substitutionSelect.selectedIndex].value : "";

    inputsCollected["variable to simplify"] = simplifyVal;
    inputsCollected["variable to substitute"] = substitutionVal;

    const chosenTarget = (solveMethod === 'simplify') ? simplifyVal : ((solveMethod === 'variable substitution') ? substitutionVal : "");
    inputsCollected["variable substitution"] = chosenTarget;
    inputsCollected["variable to solve for"] = chosenTarget;

    const substitutions = {};
    const subsContainer = card.querySelector('.substitutions-list-container');
    if (subsContainer && solveMethod === 'variable substitution') {
        subsContainer.querySelectorAll('.substitution-row-item').forEach(row => {
            const vName = row.getAttribute('data-var-name');
            if (!vName) return;

            const inputWrapper = row.querySelector('.linked-input-wrapper');
            const tokenPill = inputWrapper ? inputWrapper.querySelector('.linked-token-pill') : null;
            const nativeInput = inputWrapper ? inputWrapper.querySelector('input') : null;

            let rawTokenValue = "";
            let isLinkedToken = false;

            if (inputWrapper && inputWrapper.hasAttribute('data-bound-token')) {
                rawTokenValue = inputWrapper.getAttribute('data-bound-token');
                isLinkedToken = true;
            } else if (tokenPill) {
                rawTokenValue = tokenPill.getAttribute('data-indexed-token') || tokenPill.textContent;
                isLinkedToken = true;
            } else if (nativeInput) {
                rawTokenValue = nativeInput.value;
                isLinkedToken = false;
            }

            if (rawTokenValue && rawTokenValue.trim() !== "") {
                let cleanString = rawTokenValue.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
                cleanString = cleanString.replace(/[<>]/g, '');

                const looksLikeToken = /^[a-zA-Z]+\d+$/.test(cleanString);

                if (isLinkedToken || looksLikeToken) {
                    substitutions[vName] = `<${cleanString}>`;
                } else {
                    substitutions[vName] = cleanString;
                }
            } else {
                substitutions[vName] = "";
            }
        });
    }
    inputsCollected["substitutions"] = substitutions;

    return inputsCollected;
}

function applyBatchSync({ card, result }) {
    if (!card || !result) return null;

    const targetDisplay = ensureLatexRenderBox(card);
    if (targetDisplay && typeof katex !== 'undefined') {
        targetDisplay.style.textAlign = 'center';
        katex.render(result.latex_output, targetDisplay, { throwOnError: false });
    } else if (typeof katex === 'undefined') {
        console.error("KaTeX is not loaded; formula preview/render will be unavailable.");
    }
    return true;
}

function renderPreviewToken({ displayVal }) {
    // Escape so values like "x < 5" cannot break surrounding HTML (e.g. MC option rows).
    // KaTeX later reads textContent, which resolves entities back to the raw expression.
    return `<span class="simulated-math-formula-render" style="display: inline-block; padding: 2px 4px;">${escapeHtmlText(displayVal)}</span>`;
}
