// -------------------------------------------------------------
// Global Problem Workspace Overlay Controller Engine
// -------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function() {
    const workspaceOverlay = document.getElementById('problem-workspace-overlay');
    if (!workspaceOverlay) return;

    const overlayTitleField = document.getElementById('overlay-problem-title-field');
    const closeOverlayBtn = document.getElementById('close-workspace-overlay');
    
    // Core sub-containers inside the workspace overlay columns
    const variablesContainer = document.getElementById('sidebar-variables-list');
    const inputsContainer = document.getElementById('sidebar-inputs-list');
    const htmlCanvasEditor = document.getElementById('editor-html-insert-canvas');
    const tokensLedger = document.getElementById('overlay-tokens-wrapper-line');

    // Targets for the execution trigger action buttons
    const saveDraftBtn = document.getElementById('btn-save-master-problem');
    const saveStatusSpan = document.getElementById('overlay-save-status');

    // 🎯 1. GLOBAL MUTABLE TOKEN ARRAYS POPULATED VIA THE AJAX FETCH PIPELINE
    let dynamicVarsTokens = [];
    let answerFieldsTokens = [];

    // 🎯 Live formula cache to prevent lagging network requests on rendering passes
    let formulaLiveLatexCache = {};

    // Global Workspace Quill Editor Tracker Instance
    let workspaceQuillInstance = null;


    /**
     * Toggles layout option menus dynamically based on your database rows
     */
    function setupDropdownMenu(triggerId, menuId, tokens) {
        const trigger = document.getElementById(triggerId);
        const menu = document.getElementById(menuId);
        if (!trigger || !menu) return;

        // Defensively verify 'tokens' is an actual array list.
        let tokensArray = [];
        if (Array.isArray(tokens)) {
            tokensArray = tokens;
        } else if (tokens && typeof tokens === 'object') {
            tokensArray = Object.values(tokens);
        }

        // 1. Clean dropdown item render without the internal note text blocks
        if (tokensArray.length === 0) {
            menu.innerHTML = `<div style="padding: 8px 12px; font-size: 0.8rem; color: #94a3b8; font-style: italic;">No options available</div>`;
        } else {
            menu.innerHTML = tokensArray.map(t => `
                <button type="button" class="entity-menu-item" data-token="${t.token}" style="width: 100%; text-align: left; padding: 8px 12px; background: none; border: none; cursor: pointer; transition: background 0.15s;">
                    <strong>+ ${t.name}</strong>
                </button>
            `).join('');
        }

        trigger.onclick = function(e) {
            e.stopPropagation();
            document.querySelectorAll('.entity-menu-dropdown').forEach(m => {
                if (m !== menu) m.style.display = 'none';
            });
            menu.style.display = menu.style.display === 'block' ? 'none' : 'block';
        };

        menu.onclick = function(e) {
            const btn = e.target.closest('.entity-menu-item');
            if (!btn) return;
            
            e.stopPropagation();
            const tokenSelected = btn.getAttribute('data-token');
            
            const isVariable = dynamicVarsTokens.some(item => item.token === tokenSelected);
            const targetContainer = isVariable ? variablesContainer : inputsContainer;

            if (targetContainer) {
                removePlaceholders(targetContainer);
                createTokenBadge(tokenSelected);
                createNewBlockInstanceUI(tokenSelected, targetContainer, {});
                updateWorkspaceSimulationPreview();
            }
            
            menu.style.display = 'none';
        };
    }

    // Close open menus if user clicks away into void space elements
    document.addEventListener('click', function() {
        document.querySelectorAll('.entity-menu-dropdown').forEach(m => m.style.display = 'none');
    });


    /**
     * Loops through saved entity segments extracted from database layers on load
     */
    function rehydrateWorkspaceSegments(segments) {
        if (!segments || segments.length === 0) {
            clearAndShowPlaceholders();
            return;
        }

        if (variablesContainer) variablesContainer.innerHTML = '';
        if (inputsContainer) inputsContainer.innerHTML = '';
        if (tokensLedger) tokensLedger.innerHTML = '';

        segments.forEach(segment => {
            const isVariable = dynamicVarsTokens.some(item => item.token === segment.token);
            const targetContainer = isVariable ? variablesContainer : inputsContainer;

            if (!targetContainer) return;

            removePlaceholders(targetContainer);
            
            // 🚀 FIX: Extract the persistent sequence token sent down by Django, 
            // or pass undefined so it defaults to dynamic look-ahead calculation
            const savedSequenceToken = segment.sequence_token; 

            // Flow execution order synchronously, explicitly supplying the permanent token name string
            createTokenBadge(segment.token, savedSequenceToken);
            createNewBlockInstanceUI(segment.token, targetContainer, segment.inputs, segment.points, savedSequenceToken);
        
            // 🎯 NEW: After card UI construction, tuck the evaluated value onto the card wrapper element
            const builtCards = targetContainer.querySelectorAll('.workspace-block-card');
            const latestCard = builtCards[builtCards.length - 1];
            if (latestCard && segment.simulated_value !== undefined) {
                if (segment.simulated_value !== undefined) {
                    latestCard.setAttribute('data-simulated-value', segment.simulated_value);
                }
                // Restore the shuffle seed attribute to persist randomized evaluations between overlay sessions
                if (segment.shuffle_seed !== undefined && segment.shuffle_seed !== null && segment.shuffle_seed !== '') {
                    latestCard.setAttribute('data-shuffle-seed', segment.shuffle_seed);
                }
            }

        });

        checkEmptyColumns();
    }


    /**
     * Unified Form Element Interface Constructor Factory
     */
    function createNewBlockInstanceUI(token, containerElement, savedValues = {}, points = 0.0, overrideSequenceToken = undefined) {
        const card = document.createElement('div');
        card.className = 'workspace-component-card workspace-block-card';
        card.setAttribute('data-token', token);
        card.style.cssText = 'background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; position: relative;';

        const isVariable = dynamicVarsTokens.some(item => item.token === token);
        const headerColor = isVariable ? '#0284c7' : '#16a34a';
        const typeBadgeText = isVariable ? 'Variable' : `${points} Pts`;

        let indexedTokenString = "";

        if (overrideSequenceToken) {
            indexedTokenString = overrideSequenceToken;
        } else {
            const matchingCardsOnPage = document.querySelectorAll(`.workspace-block-card[data-token="${token}"]`);
            let maxIndex = 0;

            matchingCardsOnPage.forEach(existingCard => {
                const deleteBtn = existingCard.querySelector('.btn-delete-workspace-component');
                if (deleteBtn) {
                    const existingIndexedToken = deleteBtn.getAttribute('data-indexed-token') || '';
                    const numericMatch = existingIndexedToken.match(/\d+$/);
                    if (numericMatch) {
                        const indexNum = parseInt(numericMatch[0], 10);
                        if (indexNum > maxIndex) maxIndex = indexNum;
                    }
                }
            });
            const nextSequenceIndex = maxIndex + 1;
            indexedTokenString = `${token}${nextSequenceIndex}`;
        }

        const tokenSourceArray = isVariable ? dynamicVarsTokens : answerFieldsTokens;
        const matchingTokenData = tokenSourceArray.find(item => item.token === token);
        const tokenNoteHint = matchingTokenData ? (matchingTokenData.note || '') : '';

        // Helper function to prevent inserting literal token strings into type="number" inputs
        const safeNumValue = (val, fallback) => {
            if (typeof val === 'string' && val.trim().match(/^<([^>]+)>$/)) {
                return fallback; // Return the standard numeric default for the HTML attribute
            }
            return val ?? fallback;
        };

        let fieldsHtml = '';
        // Add new entity Step 1: if new fields exist, then add the html here for the new entity
        if (token === 'randInt') {
            fieldsHtml = `
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
        } else if (token === 'rand') {
            fieldsHtml = `
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
        } else if (token === 'primeFactors') {
            fieldsHtml = `
                <div class="linked-input-wrapper" data-input-key="number to factor" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px; width: 100%;">
                    <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Number to Factor: 
                        <input type="number" class="val-input-number" value="${safeNumValue(savedValues['number to factor'], 12)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                    </label>
                    <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
                </div>
            `;
        }
        else if (token === 'formula') {
            fieldsHtml = `
                <div style="display: flex; flex-direction: column; gap: 8px; width: 100%;">
                    
                    <div class="linked-input-wrapper" data-input-key="formula" data-input-type="text" style="position: relative; display: flex; align-items: flex-end; gap: 4px; width: 100%;">
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
                                <option value="solve for _" ${savedValues['solve method'] === 'solve for _' ? 'selected' : ''}>solve for _</option>
                            </select>
                        </div>

                        <div class="linked-input-wrapper" data-input-key="variables" data-input-type="text">
                            <label style="font-size: 0.75rem; color: #475569; display: block; width: 100%;">Variables (automatically extracted): 
                                <input type="text" class="val-input-variables" value="${savedValues.variables || ''}" placeholder="e.g. x, y" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                            </label>
                        </div>
                        
                    </div>

                    <div class="row-solve-for-target linked-input-wrapper" data-input-key="solve for _" data-input-type="text" style="position: relative; display: none; flex-direction: column; gap: 4px; width: 100%;">
                        <label style="font-size: 0.75rem; color: #475569; width: 100%;">Solve For Target variable: 
                            <select class="val-input-solve-for" data-saved-value="${savedValues['solve for _'] || ''}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
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
        } else {
            fieldsHtml = `<p style="font-size:0.8rem; color:#64748b; margin:0;">Standard attributes container template wrapper.</p>`;
        }

        card.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px dashed #e2e8f0; padding-bottom: 6px; margin-bottom: 4px;">
                <span style="font-weight: 600; font-size: 0.85rem; color: ${headerColor};"><i class="fas fa-cube"></i> &lt;${indexedTokenString}&gt;</span>
                <div style="display: flex; align-items: center; gap: 8px;">
                    
                    ${token !== 'primeFactors' ? `
                        <button type="button" class="btn-refresh-workspace-component-value" title="Shuffle simulation instance sample value" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.8rem; padding: 2px 4px; display: flex; align-items: center; justify-content: center; transition: color 0.15s, transform 0.15s;">
                            <i class="fas fa-redo-alt"></i>
                        </button>
                    ` : ''}

                    <span style="font-size: 0.77rem; background:${isVariable ? '#e0f2fe' : '#dcfce7'}; color:${isVariable ? '#0369a1' : '#166534'}; padding:1px 6px; border-radius:10px; font-weight:500;">${typeBadgeText}</span>
                    
                    ${tokenNoteHint ? `
                        <div class="workspace-info-tooltip-container" style="position: relative; display: inline-block;">
                            <i class="fas fa-info-circle" style="color: #94a3b8; cursor: pointer; font-size: 0.85rem; transition: color 0.15s;"></i>
                            <div class="workspace-info-tooltip-overlay">
                                <strong>&lt;${indexedTokenString}&gt; Definition Note:</strong><br>
                                ${tokenNoteHint}
                            </div>
                        </div>
                    ` : ''}

                    <button type="button" class="btn-delete-workspace-component" data-token="${token}" data-indexed-token="${indexedTokenString}" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.8rem; transition: color 0.15s;"><i class="fas fa-trash"></i></button>
                </div>
            </div>
            <div class="component-fields-wrapper">${fieldsHtml}</div>
        `;

        // Bind an input event listener to the card structure so any keystroke 
        // inside the formula card immediately triggers a simulation preview update!
        if (token === 'formula') {
            card.addEventListener('input', function() {
                updateWorkspaceSimulationPreview();
            });
        }

        // Interactive UI hover transitions
        const refreshIconBtn = card.querySelector('.btn-refresh-workspace-component-value');
        if (refreshIconBtn) {
            refreshIconBtn.onmouseenter = () => refreshIconBtn.style.color = '#0284c7';
            refreshIconBtn.onmouseleave = () => refreshIconBtn.style.color = '#94a3b8';
        }

        const trashIcon = card.querySelector('.btn-delete-workspace-component');
        if (trashIcon) {
            trashIcon.onmouseenter = () => trashIcon.style.color = '#ef4444';
            trashIcon.onmouseleave = () => trashIcon.style.color = '#94a3b8';
        }

        containerElement.appendChild(card);

        // 🎯 FIX: Bake a permanent random shuffle seed onto the newly created node immediately
        // if one doesn't exist, ensuring un-shuffled entities get saved with a static seed value.
        if (!card.hasAttribute('data-shuffle-seed') || card.getAttribute('data-shuffle-seed') === '') {
            card.setAttribute('data-shuffle-seed', Math.random().toString());
        }

        if (token === 'formula') {
            bindLiveFormulaEvaluation(card, savedValues || {});
        }

        // 🎯 NEW REHYDRATION RE-LINKING MATRIX
        // Scan all newly created input wrappers on this card to check if their saved values are tokens
        const newlyCreatedWrappers = card.querySelectorAll(
            '.linked-input-wrapper:not(.substitutions-list-container .linked-input-wrapper)'
        );
        newlyCreatedWrappers.forEach(wrapper => {
            const inputKey = wrapper.getAttribute('data-input-key');
            const savedValue = savedValues[inputKey];

            if (savedValue && typeof savedValue === 'string' && savedValue.trim().match(/^<([^>]+)>$/)) {
                const cleanTokenString = savedValue.trim();
                const linkBtn = wrapper.querySelector('.btn-input-link-trigger');
                
                // 🚀 FIX: Look for a label element defensively to avoid null crashes
                const labelEl = wrapper.querySelector('label');
                if (labelEl) {
                    labelEl.style.display = 'none';
                } else {
                    // Fallback for substitution rows where the input sits directly in the wrapper
                    const inputEl = wrapper.querySelector('input, select');
                    if (inputEl) inputEl.style.display = 'none';
                }
                
                wrapper.setAttribute('data-bound-token', cleanTokenString);

                // Inject tracking pill
                const pill = document.createElement('span');
                pill.className = 'linked-token-pill';
                pill.style.cssText = 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 4px 8px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.8rem; display: inline-block; width: 100%; box-sizing: border-box; text-align: center;';
                pill.innerText = cleanTokenString;
                wrapper.insertBefore(pill, linkBtn);

                if (linkBtn) {
                    linkBtn.innerHTML = '<i class="fas fa-times"></i>';
                    linkBtn.className = 'btn-input-link-trigger is-linked';
                    linkBtn.style.color = '#ef4444';
                    linkBtn.style.borderColor = '#fca5a5';
                }
            }
        });

        // Track live typing modifications to clear synced status tracking layers
        card.addEventListener('input', function(e) {
            if (e.target.matches('input, select, textarea')) {
                if (saveStatusSpan) {
                    saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                }
                updateWorkspaceSimulationPreview();
            }
        });

        // Trigger simulation update to reflect changes
        updateWorkspaceSimulationPreview();
    }

    // -------------------------------------------------------------
    // INNER RECURSIVE VALUE RESOLUTION ENGINE (WITH CYCLE DETECTION)
    // -------------------------------------------------------------
    function getLiveComponentValue(card, inputKey, defaultFallback, visitedTokens = []) {
        if (!card) return defaultFallback;
        
        // Query for standard linkage structural container wrappers
        const wrapper = card.querySelector(`.linked-input-wrapper[data-input-key="${inputKey}"]`);
        if (!wrapper) {
            // Fallback catch-all logic for legacy unbound field classes (like formula)
            const legacyInput = card.querySelector(`.val-input-${inputKey}`);
            return legacyInput ? legacyInput.value.trim() : defaultFallback;
        }

        // Check if input parameter context is currently chained to an output token dependency
        const boundToken = wrapper.getAttribute('data-bound-token');
        if (boundToken) {
            const cleanTargetToken = boundToken.replace(/[<>]/g, '').trim(); // e.g., "randInt2"
            
            // 🛑 CYCLE BREAK ENGINE: Prevent infinite recursive call stack loops
            if (visitedTokens.includes(cleanTargetToken)) {
                return defaultFallback;
            }

            const activeCards = document.querySelectorAll('.workspace-block-card');
            let resolvedValue = defaultFallback;

            activeCards.forEach(srcCard => {
                const deleteBtn = srcCard.querySelector('.btn-delete-workspace-component');
                if (deleteBtn && deleteBtn.getAttribute('data-indexed-token') === cleanTargetToken) {
                    // Recursively compute value based on the linked element card branch configuration
                    resolvedValue = evaluateSingleCardOutput(srcCard, cleanTargetToken, [...visitedTokens, cleanTargetToken]);
                }
            });
            return resolvedValue;
        }

        // No active link: extract current string out of standard native input element field lines
        const nativeInput = wrapper.querySelector('input');
        return (nativeInput && nativeInput.value !== '') ? nativeInput.value.trim() : defaultFallback;
    }

    // Isolate the core calculation matrix out of the main loop so it can be resolved recursively
    function evaluateSingleCardOutput(card, tokenIdentifier, visitedTokens = []) {
        const baseArchetype = card.getAttribute('data-token');
        let val = null;

        if (baseArchetype === 'randInt') {
            const minVal = parseInt(getLiveComponentValue(card, 'min', -9, visitedTokens), 10);
            const maxVal = parseInt(getLiveComponentValue(card, 'max', 9, visitedTokens), 10);
            const stepVal = parseInt(getLiveComponentValue(card, 'step', 1, visitedTokens), 10);
            
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
                    val = pool[targetIndex].toString();
                }
            }
        } 
        else if (baseArchetype === 'rand') {
            const minVal = parseFloat(getLiveComponentValue(card, 'min', 0.0, visitedTokens));
            const maxVal = parseFloat(getLiveComponentValue(card, 'max', 1.0, visitedTokens));
            const stepVal = parseFloat(getLiveComponentValue(card, 'step', 0.01, visitedTokens));

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

                    const stepStr = stepVal.toString();
                    let decimalPlaces = 4;
                    if (stepStr.includes('.')) {
                        decimalPlaces = stepStr.split('.')[1].length;
                    }
                    val = finalValue.toFixed(decimalPlaces);
                }
            }
        } 
        else if (baseArchetype === 'primeFactors') {
            let targetNum = parseInt(getLiveComponentValue(card, 'number to factor', 12, visitedTokens), 10);
            
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
                val = factors.join(', ');
            } else {
                val = "";
            }
        }
        else if (baseArchetype === 'formula') {
            const formulaVal = getLiveComponentValue(card, 'formula', '', visitedTokens);
            const methodVal = getLiveComponentValue(card, 'solve method', 'leave as formula', visitedTokens);
            const varsVal = getLiveComponentValue(card, 'variables', '', visitedTokens);
            const solveForVal = getLiveComponentValue(card, 'solve for _', '', visitedTokens);

            console.log(`🧐 [evaluateSingleCardOutput] Evaluating formula card. Raw fields read from DOM:`, {
                formulaVal, methodVal, varsVal, solveForVal
            });

            // 🎯 1. Dynamically scan for active substitution row items to align cache payload perfectly
            const subsPayload = {};
            card.querySelectorAll('.substitution-row-item').forEach(row => {
                const varName = row.getAttribute('data-var-name');
                const inputEl = row.querySelector('input, select');
                if (varName && inputEl) {
                    subsPayload[varName] = inputEl.value.trim();
                }
            });

            // 🎯 2. Structural input validation serialization payload setup (FIXED: Added structural nested 'inputs' tier)
            const inputsPayload = {
                inputs: {
                    "formula": formulaVal,
                    "solve method": methodVal,
                    "variables": varsVal,
                    "solve for _": solveForVal,
                    "substitutions": subsPayload
                }
            };

            // 🎯 3. Build identical matching cache keys matching network requests
            const cardId = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token') || tokenIdentifier;
            
            // This now successfully passes the nested structural block into your string normalizer
            const normalizedKeyString = typeof normalizePayloadKey === 'function' ? normalizePayloadKey(inputsPayload) : JSON.stringify(inputsPayload);
            const cacheKey = `${cardId}_${normalizedKeyString}`;

            // 🎯 TEMP LOG 2: What is the UI looking for?
            console.log("🔍 [UI READ KEY]:", cacheKey);
            console.log("📦 [UI READ PAYLOAD OBJECT]:", inputsPayload);

            // 🎯 4. Route explicit placeholders directly if not evaluating baseline choices
            if (methodVal === 'simplify') {
                console.log("🔀 [UI Route] Matching 'simplify' placeholder.");
                return "[Placeholder: Simplify Method Display]";
            } else if (methodVal === 'expand polynomial') {
                console.log("🔀 [UI Route] Matching 'expand polynomial' placeholder.");
                return "[Placeholder: Expand Polynomial Method Display]";
            } else if (methodVal === 'solve for _') {
                console.log(`🔀 [UI Route] Matching 'solve for ${solveForVal}' placeholder.`);
                return `[Placeholder: Solve for ${solveForVal || '_'} Method Display]`;
            }

            // 🎯 5. Look up compiled LaTeX out of your global cache dictionary map
            if (formulaLiveLatexCache && formulaLiveLatexCache[cacheKey]) {
                console.log(`🎯 [CACHE HIT] Found LaTeX in cache for key: "${cacheKey}". Value: "${formulaLiveLatexCache[cacheKey]}"`);
                return formulaLiveLatexCache[cacheKey];
            } else {
                console.log(`💨 [CACHE MISS] No cache entry found for key: "${cacheKey}"`);
            }

            // Fallback to old attribute snapshot context if it has one seeded
            const databaseValueFallback = card.getAttribute('data-simulated-value');
            if (databaseValueFallback) {
                console.log(`🗄️ [Fallback] Using data-simulated-value attribute fallback: "${databaseValueFallback}"`);
                return databaseValueFallback;
            }

            // 🎯 6. Fire asynchronous API translation pass if cache is empty
            if (formulaVal && typeof fetchLiveFormulaLatex === 'function') {
                console.log(`🚀 [Asynchronous Dispatch] Dispatching network request fetchLiveFormulaLatex for Card ID: ${cardId}`);
                fetchLiveFormulaLatex(cardId, 'formula', inputsPayload);
            } else {
                console.warn(`⚠️ [Skip Dispatch] fetchLiveFormulaLatex not triggered. formulaVal empty or function missing.`);
            }

            // Fallback variable assignments if cache hasn't returned yet
            val = formulaVal || '3*x + 5';
            console.log(`🩹 [Value Fallback] Cache empty. Returning raw formula expression text to preview frame: "${val}"`);
        }

        if (val === null || val === '') {
            val = card.getAttribute('data-simulated-value');
        }
        return val;
    }

    function bindLiveFormulaEvaluation(card, savedValues = {}) {
        if (card.getAttribute('data-formula-listener-bound') === 'true') {
            return;
        }
        card.setAttribute('data-formula-listener-bound', 'true');

        const variablesField = card.querySelector('.val-input-variables');
        const solveMethodSelect = card.querySelector('.val-input-solve-method');
        const solveForSelect = card.querySelector('.val-input-solve-for');
        const solveForWrapper = card.querySelector('.row-solve-for-target');
        
        // 🎯 Target the new Substitution Elements
        const substitutionsWrapper = card.querySelector('.row-variable-substitutions');
        const substitutionsContainer = card.querySelector('.substitutions-list-container');
        const unusedVariablesPicker = card.querySelector('.picker-unused-variables');

        if (variablesField) {
            variablesField.disabled = true;
            variablesField.readOnly = true;
            variablesField.style.backgroundColor = '#f1f5f9';
            variablesField.style.cursor = 'not-allowed';
        }

        // 🎯 REBUILD THE UNUSED VARIABLES SELECTOR PICKER
        function refreshUnusedVariablesPicker() {
            if (!variablesField || !unusedVariablesPicker) return;

            // Get all currently extracted variables
            const allVars = variablesField.value.split(',')
                .map(v => v.trim())
                .filter(v => v.length > 0);

            // Find which variables are already drawn in active dynamic input rows
            const currentlyAssignedVars = Array.from(substitutionsContainer.querySelectorAll('.substitution-row-item'))
                .map(row => row.getAttribute('data-var-name'));

            // Filter out variables already used
            const unusedVars = allVars.filter(v => !currentlyAssignedVars.includes(v));

            // Rebuild picker options
            if (unusedVars.length === 0) {
                unusedVariablesPicker.parentElement.style.display = 'none'; // Hide selection bar entirely if zero options remain
            } else {
                unusedVariablesPicker.parentElement.style.display = 'flex';
                unusedVariablesPicker.innerHTML = '<option value="">-- choose variable --</option>';
                unusedVars.forEach(v => {
                    const opt = document.createElement('option');
                    opt.value = v;
                    opt.textContent = v;
                    unusedVariablesPicker.appendChild(opt);
                });
            }
        }

        // 🎯 HELPER FUNCTION TO SPAWN A SUBSTITUTION INPUT LINE
        function createSubstitutionRow(varName, initialValue = "") {
            const row = document.createElement('div');
            row.className = 'substitution-row-item';
            row.setAttribute('data-var-name', varName);
            row.style.cssText = 'display: flex; align-items: center; gap: 6px; width: 100%;';

            row.innerHTML = `
                <span style="font-size: 0.8rem; font-family: monospace; font-weight: bold; min-width: 24px; text-align: right; color: #334155;">${varName} =</span>
                
                <div class="linked-input-wrapper" data-input-key="sub_${varName}" data-input-type="text" style="position: relative; display: flex; align-items: center; gap: 4px; flex-grow: 1;">
                    <input type="text" class="val-substitution-input" value="${initialValue}" placeholder="Value or expression" style="flex-grow: 1; font-size: 0.8rem; padding: 4px; border: 1px solid #cbd5e1; border-radius: 4px;">
                    <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.7rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
                </div>

                <button type="button" class="btn-delete-substitution-row" title="Remove assignment" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.8rem; padding: 4px; transition: color 0.15s;"><i class="fas fa-times-circle"></i></button>
            `;

            // Bind active styling feedback for delete button hover animations natively
            const delBtn = row.querySelector('.btn-delete-substitution-row');
            delBtn.addEventListener('mouseenter', () => delBtn.style.color = '#ef4444');
            delBtn.addEventListener('mouseleave', () => delBtn.style.color = '#94a3b8');

            // Handle deletion action click
            delBtn.addEventListener('click', () => {
                row.remove();
                refreshUnusedVariablesPicker();
                // Fire layout refresh event bubble to sync network configuration simulation states
                unusedVariablesPicker.dispatchEvent(new Event('change', { bubbles: true }));
            });

            substitutionsContainer.appendChild(row);
            refreshUnusedVariablesPicker();
        }

        // 🎯 INITIAL VISIBILITY AND DROPDOWN CONFIG SYNCHRONIZER
        function syncSolveForDropdown() {
            const selectedMethod = solveMethodSelect?.value || "leave as formula";
            
            // Mode A: simplify view states configuration
            if (selectedMethod === 'simplify') {
                solveForWrapper.style.display = 'flex';
                substitutionsWrapper.style.display = 'none';
            } 
            // Mode B: solve for _ view states configuration
            else if (selectedMethod === 'solve for _') {
                solveForWrapper.style.display = 'none';
                substitutionsWrapper.style.display = 'flex';
                if (solveForSelect) solveForSelect.value = "";
                refreshUnusedVariablesPicker();
            } 
            // Default clear states configuration
            else {
                solveForWrapper.style.display = 'none';
                substitutionsWrapper.style.display = 'none';
                if (solveForSelect) solveForSelect.value = "";
                return;
            }

            // Rebuild select options for the normal 'simplify' target variable field
            if (selectedMethod === 'simplify' && solveForSelect && variablesField) {
                const currentVars = variablesField.value.split(',')
                    .map(v => v.trim())
                    .filter(v => v.length > 0);

                const previousSelection = solveForSelect.value || solveForSelect.getAttribute('data-saved-value') || "";
                
                solveForSelect.innerHTML = '<option value="">-- select target --</option>';
                currentVars.forEach(v => {
                    const option = document.createElement('option');
                    option.value = v;
                    option.textContent = v;
                    if (v === previousSelection) option.selected = true;
                    solveForSelect.appendChild(option);
                });
            }
        }


        // Spawn row item instantly upon user option dropdown picking
        unusedVariablesPicker?.addEventListener('change', (e) => {
            const pickedVar = e.target.value;
            if (!pickedVar) return;
            
            createSubstitutionRow(pickedVar);
            e.target.value = ""; // clear selection option index placeholder pointer reset
            
            // Dispatch bubbling event upward context framework to trigger automated validation payload execution
            unusedVariablesPicker.dispatchEvent(new Event('change', { bubbles: true }));
        });

        // 🎯 UPDATED: Auto-populate flat substitution values (e.g., "sub_z") on load
        if (savedValues) {
            Object.entries(savedValues).forEach(([key, vVal]) => {
                if (key.startsWith('sub_')) {
                    const varName = key.replace('sub_', '');
                    
                    // 1. Re-render row context lines
                    createSubstitutionRow(varName, vVal); 

                    // 2. Wrap as active token pill if it maps to a dependency container
                    if (vVal && vVal.startsWith('<') && vVal.endsWith('>')) {
                        const rowItem = substitutionsContainer.querySelector(`.substitution-row-item[data-var-name="${varName}"]`);
                        const rowWrapper = rowItem?.querySelector('.linked-input-wrapper');
                        const linkBtn = rowWrapper?.querySelector('.btn-input-link-trigger');
                        const inputEl = rowWrapper?.querySelector('.val-substitution-input');

                        if (rowWrapper && linkBtn && inputEl) {
                            rowWrapper.setAttribute('data-bound-token', vVal);
                            inputEl.style.display = 'none';
                            
                            const pill = document.createElement('span');
                            pill.className = 'linked-token-pill';
                            pill.style.cssText = 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 4px 8px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.8rem; display: inline-block; width: 100%; box-sizing: border-box; text-align: center;';
                            pill.innerText = vVal;
                            rowWrapper.insertBefore(pill, linkBtn);

                            linkBtn.innerHTML = '<i class="fas fa-times"></i>';
                            linkBtn.className = 'btn-input-link-trigger is-linked';
                            linkBtn.style.color = '#ef4444';
                            linkBtn.style.borderColor = '#fca5a5';
                        }
                    }
                }
            });
        }

        // Execute state syncer tracking layouts setup
        syncSolveForDropdown();

        // Core delegation listener hook
        card.addEventListener('change', async (e) => {
            const target = e.target;

            // Add validation checking hooks for internal dynamic values inside the substitution inputs too!
            if (!target.matches('.val-input-formula, .val-input-solve-method, .val-input-solve-for, .val-substitution-input, .picker-unused-variables')) {
                return;
            }

            const formulaInputEl = card.querySelector('.val-input-formula');
            const wrapper = formulaInputEl?.closest('.linked-input-wrapper');
            
            card.querySelectorAll('.formula-inline-error-msg').forEach(el => el.remove());

            // Extract substitution list parameters directly to bundle down to API endpoints
            const substitutionsPayload = {};
            substitutionsContainer.querySelectorAll('.substitution-row-item').forEach(row => {
                const vName = row.getAttribute('data-var-name');
                const vVal = row.querySelector('.val-substitution-input')?.value || "";
                substitutionsPayload[vName] = vVal;
            });

            const payloadInputs = {
                "formula": formulaInputEl?.value.trim() || "",
                "solve method": solveMethodSelect?.value || "leave as formula",
                "variables": variablesField?.value.trim() || "",
                "solve for _": solveForSelect?.value || "",
                "substitutions": substitutionsPayload // Packed payload container parameters passed seamlessly
            };

            if (!payloadInputs.formula) {
                card.style.border = "1px solid #e2e8f0";
                if (variablesField) variablesField.value = "";
                substitutionsContainer.innerHTML = "";
                syncSolveForDropdown();
                updateWorkspaceSimulationPreview();
                return;
            }

            try {
                const response = await fetch('/assessment/api/validate-component-preview/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: JSON.stringify({
                        token: 'formula',
                        sequence_token: card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token'),
                        inputs: payloadInputs
                    })
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    card.setAttribute('data-simulated-value', data.evaluated_output);
                    card.style.border = "1px solid #e2e8f0"; 

                    // 🎯 FIX: Build the matching cache key structure and cache the fresh server LaTeX
                    const cardId = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token') || tokenIdentifier;
                    const inputsPayloadForCache = { inputs: payloadInputs };
                    
                    const normalizedKeyString = typeof normalizePayloadKey === 'function' 
                        ? normalizePayloadKey(inputsPayloadForCache) 
                        : JSON.stringify(inputsPayloadForCache);
                        
                    const cacheKey = `${cardId}_${normalizedKeyString}`;
                    
                    if (data.latex_output) {
                        console.log(`💾 [Change Listener Cache Write] Key: "${cacheKey}" -> LaTeX: "${data.latex_output}"`);
                        formulaLiveLatexCache[cacheKey] = data.latex_output;
                    }

                    // Process updated automated parameters listings
                    const rawFormula = formulaInputEl.value;
                    const variableMatches = rawFormula.match(/\b[a-zA-Z][0-9]*\b/g) || [];
                    const uniqueVars = [...new Set(variableMatches)];

                    if (variablesField) {
                        variablesField.value = uniqueVars.join(', ');
                    }

                    syncSolveForDropdown();

                } else {
                    card.style.border = "1px solid #ef4444";
                    
                    if (wrapper) {
                        wrapper.style.flexWrap = 'wrap';
                        const errorSpan = document.createElement('span');
                        errorSpan.className = 'formula-inline-error-msg';
                        errorSpan.style.cssText = 'color: #ef4444; font-size: 0.72rem; flex-basis: 100%; margin-top: 6px; font-weight: 500; display: block;';
                        errorSpan.innerText = data.error || "Math Evaluation Warning: syntax check failed.";
                        wrapper.appendChild(errorSpan);
                    }
                }

                updateWorkspaceSimulationPreview();

            } catch (err) {
                console.error("Failed to synchronize formula evaluation state:", err);
            }
        });
    }

    // -------------------------------------------------------------
    // LIVE PREVIEW SIMULATION RENDERING ENGINE (DYNAMIC RE-CALCULATION)
    // -------------------------------------------------------------
    function updateWorkspaceSimulationPreview() {
        const renderTarget = document.getElementById('simulation-render-target');
        if (!renderTarget) return;

        let canvasContent = workspaceQuillInstance ? workspaceQuillInstance.root.innerHTML.trim() : '';

        if (!canvasContent || canvasContent === '<p><br></p>') {
            renderTarget.innerHTML = '<p style="color: #94a3b8; font-style: italic; margin: 0;">Interactive layout testing view builds dynamically here...</p>';
            return;
        }


        // -------------------------------------------------------------
        // HTML LAYOUT PARSING AND FORMATTING REPLACEMENTS
        // -------------------------------------------------------------
        const tempContainer = document.createElement('div');
        tempContainer.innerHTML = canvasContent;

        const formulaNodes = tempContainer.querySelectorAll('.ql-formula');
        formulaNodes.forEach(formula => {
            const latexValue = formula.getAttribute('data-value') || '';
            const mathSpan = document.createElement('span');
            mathSpan.className = 'preview-static-latex';
            mathSpan.textContent = latexValue;
            formula.parentNode.replaceChild(mathSpan, formula);
        });

        tempContainer.querySelectorAll('.ql-align-right, .ql-align-center, .ql-align-justify').forEach(el => {
            let alignType = el.classList.contains('ql-align-right') ? 'right' : el.classList.contains('ql-align-center') ? 'center' : 'left';
            el.style.textAlign = alignType;
        });

        let workingHtml = tempContainer.innerHTML;
        const tokenRegex = /&lt;([^&>]+)&gt;|<([^>]+)>/g;

        let simulatedHtml = workingHtml.replace(tokenRegex, function(match, tokenText) {
            try {
                const cleanToken = (tokenText || match).replace(/[<>&]/g, '').trim(); 
                let evaluationValue = null;
                let baseArchetypeToken = cleanToken.replace(/\d+$/, '').toLowerCase(); // 🎯 Force lowercase natively
                
                // Scan through available live DOM items to match our tracking token target
                const allCards = document.querySelectorAll('.workspace-block-card');
                allCards.forEach(card => {
                    const deleteBtn = card.querySelector('.btn-delete-workspace-component');
                    if (deleteBtn && deleteBtn.getAttribute('data-indexed-token') === cleanToken) {
                        evaluationValue = evaluateSingleCardOutput(card, cleanToken);
                        // 🎯 Protect against capitalization variant mappings ("Formula" vs "formula")
                        if (card.getAttribute('data-token')) {
                            baseArchetypeToken = card.getAttribute('data-token').toLowerCase();
                        }
                    }
                });

                const isVar = dynamicVarsTokens.some(v => v.token.toLowerCase() === baseArchetypeToken) || baseArchetypeToken === 'formula';
                
                if (isVar) {
                    const displayVal = evaluationValue !== null ? evaluationValue : cleanToken;
                    
                    // 🎯 FIX: Removed data-expr attribute to protect LaTeX escape backslashes from browser string mutations
                    if (baseArchetypeToken === 'formula' && !displayVal.startsWith('[Placeholder:')) {
                        return `<span class="simulated-math-formula-render" style="display: inline-block; padding: 2px 4px;">${displayVal}</span>`;
                    }
                    
                    // Standard plain text fallback for random numbers/factors badges
                    return `<span class="simulated-math-variable-badge" style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.9rem; display: inline-block; margin: 0 2px;">${displayVal}</span>`;
                } else if (answerFieldsTokens.some(i => i.token.toLowerCase() === baseArchetypeToken)) {
                    return `
                        <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px;">
                            <input type="text" placeholder="Input slot..." disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; width: 140px;">
                        </div>
                    `;
                }
                return match;
            } catch (cardError) {
                // 🎯 SAFE BLOCK DEFENSE: If one card crashes, log it but let the match pass safely 
                // so the rest of the canvas items can still compile without getting blocked!
                console.warn(`Token substitution skipped for ${match}:`, cardError);
                return `<span style="color: red; font-family: monospace;">[Token Error]</span>`;
            }
        });

        renderTarget.innerHTML = simulatedHtml;

        // 🎯 Loop through your new live formulas and run KaTeX over them immediately
        if (typeof katex !== 'undefined') {
            // Render static canvas items
            renderTarget.querySelectorAll('.preview-static-latex').forEach(span => {
                try {
                    katex.render(span.textContent.trim(), span, { displayMode: false, throwOnError: false });
                } catch (err) { console.error(err); }
            });

            // Render live dynamic formula token components using the parsed equation strings
            renderTarget.querySelectorAll('.simulated-math-formula-render').forEach(span => {
                try {
                    // 🎯 FIX: Read the layout string natively out of textContent so macros compile perfectly
                    const expression = span.textContent.trim();
                    if (expression) {
                        katex.render(expression, span, { 
                            displayMode: false, 
                            throwOnError: false 
                        });
                    }
                } catch (err) { 
                    console.error("Dynamic formula KaTeX compilation failed:", err); 
                }
            });
        }
    }


    /**
     * Builds and manages ledger tokens badges
     */
    function createTokenBadge(token, overrideSequenceToken = undefined) {
        if (!tokensLedger) return;

        let indexedTokenString = "";

        // 🚀 FIX: Balance the name assignment calculations to mirror structural rendering parameters
        if (overrideSequenceToken) {
            indexedTokenString = overrideSequenceToken;
        } else {
            const matchingCardsOnPage = document.querySelectorAll(`.workspace-block-card[data-token="${token}"]`);
            let maxIndex = 0;

            matchingCardsOnPage.forEach(existingCard => {
                const deleteBtn = existingCard.querySelector('.btn-delete-workspace-component');
                if (deleteBtn) {
                    const existingIndexedToken = deleteBtn.getAttribute('data-indexed-token') || '';
                    const numericMatch = existingIndexedToken.match(/\d+$/);
                    if (numericMatch) {
                        const indexNum = parseInt(numericMatch[0], 10);
                        if (indexNum > maxIndex) maxIndex = indexNum;
                    }
                }
            });

            const currentNextIndex = maxIndex + 1;
            indexedTokenString = `${token}${currentNextIndex}`;
        }

        if (Array.from(tokensLedger.children).some(b => b.innerText === `<${indexedTokenString}>`)) return;

        const badge = document.createElement('span');
        badge.className = 'token-badge-clickable';
        badge.style.cssText = 'background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; cursor: pointer; user-select: none; transition: all 0.15s; margin-right: 4px;';
        badge.innerText = `<${indexedTokenString}>`;
        
        badge.addEventListener('click', function() {
            if (!workspaceQuillInstance) return;
            const range = workspaceQuillInstance.getSelection(true);
            if (range) {
                workspaceQuillInstance.insertText(range.index, `<${indexedTokenString}>`, 'user');
                workspaceQuillInstance.setSelection(range.index + indexedTokenString.length + 2, 'user');
            }
        });

        tokensLedger.appendChild(badge);
    }


    // -------------------------------------------------------------
    // SHARED SIDEBAR COMPONENT CLICK DELEGATION ROUTER
    // -------------------------------------------------------------
    function handleSidebarComponentActions(e) {
        // 1. Check if the user clicked a Delete Button
        const deleteBtn = e.target.closest('.btn-delete-workspace-component');
        if (deleteBtn) {
            e.stopPropagation();
            const tokenToRemove = deleteBtn.getAttribute('data-token');
            const indexedTokenToRemove = deleteBtn.getAttribute('data-indexed-token');
            const cardElement = deleteBtn.closest('.workspace-component-card');
            
            if (cardElement) cardElement.remove();

            // Remove the exact matching indexed text badge wrapper from the top tracking row ledger
            if (tokensLedger && indexedTokenToRemove) {
                tokensLedger.querySelectorAll('.token-badge-clickable').forEach(badge => {
                    if (badge.innerText === `<${indexedTokenToRemove}>`) badge.remove();
                });
            }

            // Clean instances out of the editor text context canvas safely using the indexed token label
            if (workspaceQuillInstance && indexedTokenToRemove) {
                let currentText = workspaceQuillInstance.root.innerHTML;
                [`<${indexedTokenToRemove}>`, `&lt;${indexedTokenToRemove}&gt;`].forEach(p => {
                    currentText = currentText.replaceAll(p, '');
                });
                workspaceQuillInstance.root.innerHTML = currentText;
            }

            checkEmptyColumns();
            updateWorkspaceSimulationPreview();
            return;
        }

        // 2. Check if the user clicked your Refresh Shuffler Button
        const refreshBtn = e.target.closest('.btn-refresh-workspace-component-value');
        if (refreshBtn) {
            e.stopPropagation();
            const cardElement = refreshBtn.closest('.workspace-block-card');
            if (!cardElement) return;

            // Animate the rotation icon briefly for high-fidelity visual feedback
            const icon = refreshBtn.querySelector('.fa-redo-alt');
            if (icon) {
                icon.style.transform = 'rotate(360deg)';
                icon.style.transition = 'transform 0.4s ease';
                setTimeout(() => {
                    icon.style.transform = 'none';
                    icon.style.transition = 'none';
                }, 400);
            }

            // 🎯 UPGRADED: Assign a completely unique, non-sequential random float multiplier 
            // so it breaks any repeating cyclic loops when evaluating the pool.
            cardElement.setAttribute('data-shuffle-seed', Math.random().toString());

            // Force engine view sync redraw transaction
            updateWorkspaceSimulationPreview();
            return;
        }
    }

    // Connect our multi-action router directly to both sidebars
    if (variablesContainer) variablesContainer.addEventListener('click', handleSidebarComponentActions);
    if (inputsContainer) inputsContainer.addEventListener('click', handleSidebarComponentActions);


    // 🎯 4. GLOBAL EDIT TRIGGER CONTROLLER HANDLER: Fetch Data on demand from database
    document.body.addEventListener('click', async function(e) {
        const editBtn = e.target.closest('.btn-edit-problem-details');
        if (!editBtn) return;

        e.preventDefault();
        const itemRow = editBtn.closest('[data-id], .problem-item-row');
        if (!itemRow) return;

        const problemId = itemRow.getAttribute('data-id');
        workspaceOverlay.setAttribute('data-current-problem-id', problemId);
        workspaceOverlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        if (saveStatusSpan) {
            saveStatusSpan.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Loading workspace options...`;
        }

        try {
            // 🚀 Fetch real-time row options and saved elements compiled for this specific problem instance
            const response = await fetch(`/problem/${problemId}/workspace/`);
            const data = await response.json();

            if (!data.success) {
                alert(`Error initializing workspace environment: ${data.error}`);
                return;
            }

            // Write live elements arrays straight to mutable global tracking parameters
            dynamicVarsTokens = data.dynamic_variables_options || [];
            answerFieldsTokens = data.answer_fields_options || [];

            if (overlayTitleField) {
                overlayTitleField.value = data.title || '';
            }

            // Rebuild option dropdown interfaces straight from active tables definitions arrays
            setupDropdownMenu('add-variable-trigger', 'dropdown-menu-variables', dynamicVarsTokens);
            setupDropdownMenu('add-input-trigger', 'dropdown-menu-inputs', answerFieldsTokens);

            // Lazy-Initialize Quill text frame securely
            if (!workspaceQuillInstance && typeof Quill !== 'undefined' && htmlCanvasEditor) {
                workspaceQuillInstance = new Quill('#editor-html-insert-canvas', {
                    theme: 'snow',
                    modules: { toolbar: '#workspace-quill-toolbar-container' }
                });
                workspaceQuillInstance.on('text-change', () => {
                    updateWorkspaceSimulationPreview();
                    if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                });
            }

            if (workspaceQuillInstance) {
                workspaceQuillInstance.root.innerHTML = data.body_html || '<p><br></p>';
            }

            // Restore active workspace variables configuration blocks columns rows items
            rehydrateWorkspaceSegments(data.loaded_segments || []);
            updateWorkspaceSimulationPreview();

            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Synced`;
            }

        } catch (err) {
            console.error("Failed cold-loading problem metrics payload:", err);
            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-exclamation-triangle" style="color:#ef4444;"></i> Loading Failed`;
            }
        }
    });

    if (closeOverlayBtn) {
        closeOverlayBtn.addEventListener('click', function() {
            workspaceOverlay.style.display = 'none';
            document.body.style.overflow = '';
        });
    }

    // Structural Helpers
    function removePlaceholders(container) {
        if (!container) return;
        const italicText = container.querySelector('p');
        if (italicText && italicText.style.fontStyle === 'italic') italicText.remove();
    }

    function checkEmptyColumns() {
        if (variablesContainer && variablesContainer.children.length === 0) {
            variablesContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">No dynamic variables defined.</p>';
        }
        if (inputsContainer && inputsContainer.children.length === 0) {
            inputsContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">No answer forms attached.</p>';
        }
    }

    function clearAndShowPlaceholders() {
        if (variablesContainer) variablesContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">No dynamic variables defined.</p>';
        if (inputsContainer) inputsContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">No answer forms attached.</p>';
    }

    // 🎯 5. DRAFT PROGRESS SAVE ACTION HANDLER
    if (saveDraftBtn) {
        saveDraftBtn.addEventListener('click', async function() {
            console.log("Save button clicked. Building workspace configuration payload...");
            
            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Saving draft...`;
            }
            saveDraftBtn.disabled = true;

            const problemId = workspaceOverlay.getAttribute('data-current-problem-id');
            const titleValue = overlayTitleField ? overlayTitleField.value.trim() : '';
            const canvasHtml = workspaceQuillInstance ? workspaceQuillInstance.root.innerHTML.trim() : '';

            if (!problemId) {
                alert("Error: Missing target problem identifier instance anchor.");
                resetSaveButtonState();
                return;
            }

            const inputsPayloadList = [];
            const activeCards = Array.from(document.querySelectorAll('.workspace-block-card'));

            activeCards.forEach(card => {
                const baseToken = card.getAttribute('data-token'); // e.g., "randInt"
                if (!baseToken) return;

                // 🎯 GRAB THE SHUFFLE SEED VALUE TO PERSIST THROUGH THE DATABASE PIPELINE
                const shuffleSeedValue = card.getAttribute('data-shuffle-seed') || '';
                // Find the delete button to read the custom calculated sequential label string
                const deleteBtn = card.querySelector('.btn-delete-workspace-component');
                const indexedTokenString = deleteBtn ? deleteBtn.getAttribute('data-indexed-token') : baseToken; // e.g., "randInt1"

                const inputValues = {};

                // 🎯 FIXED: Exclude dynamic row wrappers from the main configuration selector block
                const inputWrappers = card.querySelectorAll('.linked-input-wrapper:not(.row-variable-substitutions .linked-input-wrapper)');
                
                if (inputWrappers.length > 0) {
                    inputWrappers.forEach(wrapper => {
                        const inputKey = wrapper.getAttribute('data-input-key'); // e.g., "min", "max", "formula", "solve method"
                        const boundToken = wrapper.getAttribute('data-bound-token'); // e.g., "<randInt1>" or null
                        
                        if (boundToken) {
                            // Link is active: grab the cross-referenced variable token tag string directly
                            inputValues[inputKey] = boundToken;
                        } else {
                            // Looks for both standard text inputs AND dropdown select configurations!
                            const interactiveField = wrapper.querySelector('input, select');
                            if (interactiveField) {
                                inputValues[inputKey] = interactiveField.value.trim();
                            }
                        }
                    });

                    // 🎯 FIX: Directly read values if elements exist, removing condition overrides
                    if (baseToken === 'formula') {
                        // 1. Snag the explicit target variable dropdown selection value directly if present
                        const solveForSelect = card.querySelector('.val-input-solve-for');
                        if (solveForSelect && solveForSelect.value) {
                            inputValues['solve for _'] = solveForSelect.value.trim();
                        } else {
                            // Ensure it defaults to an empty string if no element or value is selected
                            inputValues['solve for _'] = inputValues['solve for _'] || '';
                        }

                        // 2. Loop through and capture the substitution rows accurately
                        card.querySelectorAll('.substitutions-list-container .substitution-row-item').forEach(row => {
                            const varName = row.getAttribute('data-var-name');
                            const rowWrapper = row.querySelector('.linked-input-wrapper');
                            const boundTokenValue = rowWrapper?.getAttribute('data-bound-token');
                            
                            if (boundTokenValue) {
                                inputValues[`sub_${varName}`] = boundTokenValue;
                            } else {
                                const inputField = row.querySelector('.val-substitution-input');
                                if (inputField) {
                                    inputValues[`sub_${varName}`] = inputField.value.trim();
                                }
                            }
                        });
                    }
                } else {
                    // 🛡️ Safe fallback block for legacy nodes (like mathAnswer) 
                    const formulaEl = card.querySelector('.val-input-formula');
                    if (formulaEl) inputValues.formula = formulaEl.value.trim();

                    const correctFormulaEl = card.querySelector('.val-input-correct-formula');
                    if (correctFormulaEl) inputValues.correct_formula = correctFormulaEl.value.trim();
                }

                // 🚀 Send the clean base database token, and pass the indexed tracking sequence string separately
                inputsPayloadList.push({
                    token: baseToken,                       // Keeps Django's database lookup clean (e.g. "randInt")
                    sequence_token: indexedTokenString,    // Lets the backend know its order index (e.g. "randInt1")
                    shuffle_seed: shuffleSeedValue,
                    inputs: inputValues
                });
            });
            
            const payload = {
                title: titleValue,
                body_html: canvasHtml,
                inputs: inputsPayloadList
            };

            try {
                const response = await fetch(`/api/problem/${problemId}/save-workspace/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: JSON.stringify(payload)
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    if (saveStatusSpan) {
                        saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Synced`;
                    }
                    console.log("Database transaction complete:", result.message);
                } else {
                    if (saveStatusSpan) {
                        saveStatusSpan.innerHTML = `<i class="fas fa-exclamation-triangle" style="color:#ef4444;"></i> Save Failed`;
                    }
                    alert(`Compilation Error:\n${result.error || 'Unknown tracking malfunction.'}`);
                }
            } catch (error) {
                console.error("AJAX Communication failure:", error);
                if (saveStatusSpan) {
                    saveStatusSpan.innerHTML = `<i class="fas fa-exclamation-triangle" style="color:#ef4444;"></i> Connection Error`;
                }
                alert("Network communication timeout occurred processing save transaction.");
            } finally {
                resetSaveButtonState();
            }
        });
    }

    function resetSaveButtonState() {
        if (saveDraftBtn) {
            saveDraftBtn.disabled = false;
        }
    }

    function getCsrfToken() {
        const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return csrfInput ? csrfInput.value : '';
    }

    // -------------------------------------------------------------
    // DYNAMIC INPUT CHAINING / TOKEN LINKING CONTROLLER
    // -------------------------------------------------------------
    document.body.addEventListener('click', function(e) {
        const linkBtn = e.target.closest('.btn-input-link-trigger');
        if (!linkBtn) return;
        
        e.stopPropagation();
        const wrapper = linkBtn.closest('.linked-input-wrapper');
        const dropdown = wrapper.querySelector('.linkable-tokens-dropdown');
        
        // ❌ UNLINK ACTION: If the field is already linked, hitting the "X" resets it
        if (linkBtn.classList.contains('is-linked')) {
            wrapper.removeAttribute('data-bound-token');
            
            // 🎯 FIXED: Safely find the input or label to restore viewports accurately without breaking sub_ layouts
            const labelEl = wrapper.querySelector('label');
            if (labelEl) {
                const inputKey = wrapper.getAttribute('data-input-key') || '';
                // Dynamic sub_ rows use block, standard inputs use default blank flex layouts
                labelEl.style.display = inputKey.startsWith('sub_') ? 'block' : '';
            }
            
            const rawInput = wrapper.querySelector('input, select');
            if (rawInput) {
                rawInput.value = ''; // Reset back to empty string value so user can type/pick fresh
            }
            
            const badge = wrapper.querySelector('.linked-token-pill');
            if (badge) badge.remove();
            
            linkBtn.innerHTML = '<i class="fas fa-link"></i>';
            linkBtn.className = 'btn-input-link-trigger';
            linkBtn.style.color = '#94a3b8';
            linkBtn.style.borderColor = '#cbd5e1';
            updateWorkspaceSimulationPreview();
            return;
        }

        // Toggle dropdown open status
        if (dropdown.style.display === 'block') {
            dropdown.style.display = 'none';
            return;
        }

        // Close all other dropdown open channels
        document.querySelectorAll('.linkable-tokens-dropdown').forEach(d => d.style.display = 'none');

        // 🔍 RE-INDEX COMPATIBILITY BY INSPECTING LIVE ACTIVE DOM SIDEBAR CARDS
        const targetType = wrapper.getAttribute('data-input-type'); // e.g., 'integer'
        const currentCard = linkBtn.closest('.workspace-block-card');
        const activeCards = Array.from(document.querySelectorAll('.workspace-block-card'));
        
        let availableOptionsHtml = '';
        
        activeCards.forEach(card => {
            // Prevent linking a card back into itself
            if (card === currentCard) return;

            const deleteBtn = card.querySelector('.btn-delete-workspace-component');
            if (!deleteBtn) return;

            const indexedToken = deleteBtn.getAttribute('data-indexed-token'); // e.g., "randInt2"
            const baseArchetype = card.getAttribute('data-token');             // e.g., "randInt"

            // Compute output configurations dynamically based on the model token archetype specifications
            let derivedOutputs = [];
            if (baseArchetype === 'randInt') derivedOutputs = ['integer'];
            else if (baseArchetype === 'rand') derivedOutputs = ['double'];
            else if (baseArchetype === 'formula') derivedOutputs = ['double', 'integer', 'formula'];
            else if (baseArchetype === 'matrix') derivedOutputs = ['matrix'];
            
            // Check if the output configuration satisfies the data field expectation rules
            const inputKey = wrapper.getAttribute('data-input-key') || '';
            let isCompatible = derivedOutputs.includes(targetType);

            // 🎯 FORCE COMPATIBILITY CHECK: permit substitution inputs to couple with double, integer, or formula tokens
            if (inputKey.startsWith('sub_')) {
                isCompatible = derivedOutputs.some(type => ['double', 'integer', 'formula'].includes(type));
            }

            if (isCompatible) {
                availableOptionsHtml += `
                    <button type="button" class="select-link-token-option" data-target-token="<${indexedToken}>" style="width: 100%; text-align: left; padding: 6px 12px; background: none; border: none; font-size: 0.75rem; cursor: pointer; transition: background 0.15s; color: #334155;">
                        &lt;${indexedToken}&gt;
                    </button>
                `;
            }
        });

        if (!availableOptionsHtml) {
            availableOptionsHtml = `<div style="padding: 6px 12px; font-size: 0.7rem; color: #94a3b8; font-style: italic;">No matching outputs</div>`;
        }

        dropdown.innerHTML = availableOptionsHtml;
        dropdown.style.display = 'block';
    });

    // Handle token option assignment action click events
    document.body.addEventListener('click', function(e) {
        const optionBtn = e.target.closest('.select-link-token-option');
        if (!optionBtn) return;

        e.stopPropagation();
        const chosenTokenString = optionBtn.getAttribute('data-target-token');
        const wrapper = optionBtn.closest('.linked-input-wrapper');
        const linkBtn = wrapper.querySelector('.btn-input-link-trigger');
        
        // 🎯 FIX: Safely check if a label exists before modifying its display style
        const labelEl = wrapper.querySelector('label');
        if (labelEl) {
            labelEl.style.display = 'none';
        } else {
            // If there's no label wrapper, hide the text input element instead
            const inputEl = wrapper.querySelector('.val-substitution-input');
            if (inputEl) inputEl.style.display = 'none';
        }
        
        // Save dependency configuration explicitly onto the node wrapper properties
        wrapper.setAttribute('data-bound-token', chosenTokenString);

        // Inject the visual element capsule tracking pill design
        const pill = document.createElement('span');
        pill.className = 'linked-token-pill';
        pill.style.cssText = 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 4px 8px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.8rem; display: inline-block; width: 100%; box-sizing: border-box; text-align: center;';
        pill.innerText = chosenTokenString;
        wrapper.insertBefore(pill, linkBtn);

        // 🎯 Transform link icon to an active red delete close asset marker
        linkBtn.innerHTML = '<i class="fas fa-times"></i>';
        linkBtn.className = 'btn-input-link-trigger is-linked';
        linkBtn.style.color = '#ef4444';
        linkBtn.style.borderColor = '#fca5a5';

        // Close options dropdown picker instance frame
        wrapper.querySelector('.linkable-tokens-dropdown').style.display = 'none';
        updateWorkspaceSimulationPreview();
    });

    // Close options dropdown panels automatically if clicking outward away from tracking structures
    document.addEventListener('click', function() {
        document.querySelectorAll('.linkable-tokens-dropdown').forEach(d => d.style.display = 'none');
    });


    /**
     * Dispatches input payloads to the validation matrix engine, caching responses
     */
    function fetchLiveFormulaLatex(cardId, token, inputsPayload) {
        const cacheKey = `${cardId}_${normalizePayloadKey(inputsPayload)}`;
        
        console.log(`📡 [fetchLiveFormulaLatex] Triggered for Card: "${cardId}", Token: "${token}"`);
        console.log(`🔑 [fetchLiveFormulaLatex] Generated CacheKey: "${cacheKey}"`);

        // 🎯 THE FIX: Bypass the early return if the cache entry is just a plain-text fallback string
        if (formulaLiveLatexCache[cacheKey]) {
            const cachedVal = formulaLiveLatexCache[cacheKey];
            const isRawTextFallback = /^(Integral|Derivative|Limit|Sum|Matrix)/i.test(cachedVal) || !cachedVal.includes('\\');
            
            console.log(`🗄️ [fetchLiveFormulaLatex] Existing cache entry found: "${cachedVal}". Is raw text fallback? ${isRawTextFallback}`);

            // If it's a real LaTeX expression, skip network traffic. 
            // If it's plain text, break out and force a server validation request!
            if (!isRawTextFallback) {
                console.log(`🛑 [fetchLiveFormulaLatex] Cache contains valid LaTeX. Aborting redundant network request.`);
                return;
            }
            console.log(`🔄 [fetchLiveFormulaLatex] Cache contains plain text fallback. Forcing network refresh...`);
        }

        // Fetch CSRF security cookies natively out of the browser layer
        const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';

        const requestBody = { token: token, inputs: inputsPayload };
        console.log(`📤 [fetchLiveFormulaLatex] Sending POST Request Payload:`, JSON.stringify(requestBody, null, 2));

        fetch('/assessment/api/validate-component-preview/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify({ token: token, inputs: inputsPayload.inputs })
        })
        .then(res => {
            console.log(`📥 [fetchLiveFormulaLatex] Network HTTP Response Status: ${res.status} (${res.statusText})`);
            // 🎯 FIX: Intercept the 400 Bad Request error payload rather than skipping straight to .catch()
            if (!res.ok) {
                return res.json().then(errData => {
                    console.error(`❌ [fetchLiveFormulaLatex] Server returned non-200 error object:`, errData);
                    throw new Error(errData.error || "Syntax Error");
                });
            }
            return res.json();
        })
        .then(data => {
            console.log(`📥 [fetchLiveFormulaLatex] Server Raw Response Data JSON:`, data);
            
            if (data.success && data.latex_output) {
                console.log(`✅ [fetchLiveFormulaLatex] SUCCESS! Writing server LaTeX to cache: "${data.latex_output}"`);
                // Pin the output string map directly to our tracking cache dictionary
                formulaLiveLatexCache[cacheKey] = data.latex_output;

                // 🎯 TEMP LOG 1: What did the network write to?
                console.log("💾 [NETWORK WRITE KEY]:", cacheKey);
            } else {
                console.warn(`⚠️ [fetchLiveFormulaLatex] API responded with success=false or missing latex_output. falling back to warning formatting.`);
                // Handle case where success is false but status code was 200
                formulaLiveLatexCache[cacheKey] = `\\text{\\color{red}{${data.error || 'Syntax Error'}}}`;
            }
            // Force a layout re-calc pass now that we have the real data
            console.log(`🔄 [fetchLiveFormulaLatex] Request cycle complete. Triggering layout refresh preview window...`);
            updateWorkspaceSimulationPreview();
        })
        .catch(err => {
            console.warn("Live LaTeX conversion syntax issue:", err);
            // 🎯 FIX: Explicitly cache the error message so the component un-freezes immediately
            const cleanMsg = err.message.replace("Error: ", "");
            formulaLiveLatexCache[cacheKey] = `\\text{\\color{red}{[${cleanMsg}]}}`;
            // Re-render layout matrices to instantly clear the preview back into an editable state
            updateWorkspaceSimulationPreview();
        });
    }

    /**
     * Normalizes an inputs object to ensure consistent string serialization keys
     */
    function normalizePayloadKey(inputsPayload) {
        if (!inputsPayload) return '';
        
        const copy = JSON.parse(JSON.stringify(inputsPayload));
        
        if (copy.inputs && copy.inputs.formula) {
            const originalForm = copy.inputs.formula;
            copy.inputs.formula = copy.inputs.formula
                .replace(/\s+/g, '')     
                .replace(/\*\*/g, '^');
            console.log(`🧹 [Normalization Input Formula]: "${originalForm}" -> Normalized to: "${copy.inputs.formula}"`);
        }
        
        const finalizedString = JSON.stringify(copy);
        console.log("🧬 [Normalization Resulting Payload String]:", finalizedString);
        return finalizedString;
    }
});