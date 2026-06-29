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

    // Global tracking to prevent race conditions
    let activeBatchSyncTimestamp = 0;
    let isWorkspaceInitializing = false;


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
                
                // 1. Appends the card element structure to the column layout
                createNewBlockInstanceUI(tokenSelected, targetContainer, {});
                
                // 2. Locate the fresh sequence tracking token string (e.g. "formula2") of the appended card
                const builtCards = targetContainer.querySelectorAll('.workspace-block-card');
                const newestCard = builtCards[builtCards.length - 1];
                const cardTokenId = newestCard?.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');

                // 3. Sync defaults to backend via single-batch query context pipeline
                if (typeof dispatchWorkspaceBatchSync === 'function' && cardTokenId) {
                    dispatchWorkspaceBatchSync(cardTokenId);
                } else {
                    updateWorkspaceSimulationPreview();
                }
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
        isWorkspaceInitializing = true; // 🔒 Lock network requests during build loop
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
        isWorkspaceInitializing = false; // 🔓 Unlock network requests
        if (typeof dispatchWorkspaceBatchSync === 'function') {
            dispatchWorkspaceBatchSync(null);
        } else {
            updateWorkspaceSimulationPreview();
        }
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
                                <input type="text" class="val-input-variables" value="${savedValues.variables || ''}" placeholder="e.g. x, y" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                            </label>
                        </div>
                        
                    </div>

                    <div class="row-solve-for-target linked-input-wrapper" data-input-key="variable to solve for" data-input-type="text" style="position: relative; display: none; flex-direction: column; gap: 4px; width: 100%;">
                        <label style="font-size: 0.75rem; color: #475569; width: 100%;">Solve For Target variable: 
                            <select class="val-input-solve-for" data-saved-value="${savedValues['variable to solve for'] || ''}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
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

    // Streamlined lookup: reads local fields directly without recursive traversals
    function getLiveComponentValue(card, inputKey, defaultFallback) {
        if (!card) return defaultFallback;
        
        // Check if wrapped in a structured input wrapper
        const wrapper = card.querySelector(`.linked-input-wrapper[data-input-key="${inputKey}"]`);
        if (wrapper) {
            const nativeInput = wrapper.querySelector('input, select');
            return (nativeInput && nativeInput.value !== '') ? nativeInput.value.trim() : defaultFallback;
        }

        // Legacy fallback class check
        const legacyInput = card.querySelector(`.val-input-${inputKey}`);
        return legacyInput ? legacyInput.value.trim() : defaultFallback;
    }

    // Isolate the core calculation matrix out of the main loop so it can be resolved from local caches
    function evaluateSingleCardOutput(card, tokenIdentifier, visitedTokens = []) {
        if (!card) return "0";
        
        const baseArchetype = card.getAttribute('data-token');
        let val = null;

        if (baseArchetype === 'randInt') {
            // Read directly from DOM input values safely without recursive traversal wrappers
            const minVal = parseInt(card.querySelector('.val-input-min')?.value || "-9", 10);
            const maxVal = parseInt(card.querySelector('.val-input-max')?.value || "9", 10);
            const stepVal = parseInt(card.querySelector('.val-input-step')?.value || "1", 10);
            
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
            const minVal = parseFloat(card.querySelector('.val-input-min')?.value || "0.0");
            const maxVal = parseFloat(card.querySelector('.val-input-max')?.value || "1.0");
            const stepVal = parseFloat(card.querySelector('.val-input-step')?.value || "0.01");

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
            let targetNum = parseInt(card.querySelector('.val-input-number')?.value || "12", 10);
            
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
            // 🎯 CORE IMPROVEMENT: Read directly from the compiled data output 
            // generated by your single batch server synchronization payload
            const lowerToken = tokenIdentifier.toLowerCase();
            
            if (formulaLiveLatexCache && formulaLiveLatexCache[lowerToken]) {
                return formulaLiveLatexCache[lowerToken];
            }

            const calculatedValueFallback = card.getAttribute('data-simulated-value');
            if (calculatedValueFallback) {
                return calculatedValueFallback;
            }

            return card.querySelector('.val-input-formula')?.value.trim() || tokenIdentifier;
        }

        if (val === null || val === '') {
            val = card.getAttribute('data-simulated-value');
        }
        return val || "0";
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
        
        // Target the correct Substitution Containers matching your DOM
        const substitutionsWrapper = card.querySelector('.row-variable-substitutions');
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

        // 🎯 REBUILD THE UNUSED VARIABLES SELECTOR PICKER OPTIONS
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
                unusedVariablesPicker.parentElement.style.display = 'none'; 
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
            // Guard: prevent duplication inside this component wrapper scope
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
            delBtn.addEventListener('mouseenter', () => delBtn.style.color = '#ef4444');
            delBtn.addEventListener('mouseleave', () => delBtn.style.color = '#94a3b8');

            delBtn.addEventListener('click', () => {
                row.remove();
                refreshUnusedVariablesPicker();
                
                const cardId = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                if (typeof dispatchWorkspaceBatchSync === 'function' && cardId) {
                    dispatchWorkspaceBatchSync(cardId);
                } else {
                    updateWorkspaceSimulationPreview();
                }
            });

            // Append row to the DOM container explicitly before running any calculation passes
            substitutionsContainer.appendChild(row);
            refreshUnusedVariablesPicker();

            // Notify structural synchronization engines about changes
            const cardId = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
            if (typeof dispatchWorkspaceBatchSync === 'function' && cardId) {
                dispatchWorkspaceBatchSync(cardId);
            } else if (typeof updateWorkspaceSimulationPreview === 'function') {
                updateWorkspaceSimulationPreview();
            }
        }

        // 🎯 DROPDOWN STATE CONFIGURATION SYNCHRONIZER
        function syncSolveForDropdown() {
            const selectedMethod = solveMethodSelect?.value || "leave as formula";
            const previousMethod = card.getAttribute('data-last-method') || "";

            if (previousMethod === 'variable substitution' && selectedMethod !== 'variable substitution') {
                substitutionsContainer.innerHTML = '';
                refreshUnusedVariablesPicker();
                const cardId = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                if (typeof dispatchWorkspaceBatchSync === 'function' && cardId) {
                    dispatchWorkspaceBatchSync(cardId);
                }
            }

            card.setAttribute('data-last-method', selectedMethod);

            if (selectedMethod === 'simplify') {
                solveForWrapper.style.display = 'flex';
                substitutionsWrapper.style.display = 'none';
            } 
            else if (selectedMethod === 'variable substitution') {
                solveForWrapper.style.display = 'none';
                substitutionsWrapper.style.display = 'flex';
                if (solveForSelect) solveForSelect.value = "";
                refreshUnusedVariablesPicker();
            } 
            else {
                solveForWrapper.style.display = 'none';
                substitutionsWrapper.style.display = 'none';
                if (solveForSelect) solveForSelect.value = "";
                return;
            }

            if (selectedMethod === 'simplify' && solveForSelect && variablesField) {
                // 🚀 Get the current list of variables from the input field
                const currentVars = variablesField.value.split(',')
                    .map(v => v.trim())
                    .filter(v => v.length > 0)
                    .sort();

                // 🚀 Extract what options are already drawn in the DOM to avoid redundant purges
                const existingOptions = Array.from(solveForSelect.options)
                    .map(opt => opt.value.trim())
                    .filter(val => val.length > 0)
                    .sort();

                // Check if the underlying variable schema changed 
                const optionsPoolChanged = currentVars.length !== existingOptions.length || 
                                           !currentVars.every((v, i) => v === existingOptions[i]);

                const previousSelection = solveForSelect.value || solveForSelect.getAttribute('data-saved-value') || "";
                
                // 🚀 FIX: Only clear innerHTML if variables actually mutated!
                if (optionsPoolChanged) {
                    console.log("🔄 Variable pool changed. Rebuilding dropdown options...");
                    // Match option string identically with backend template re-injection context
                    solveForSelect.innerHTML = '<option value="">-- select variable --</option>';
                    currentVars.forEach(v => {
                        const option = document.createElement('option');
                        option.value = v;
                        option.textContent = v;
                        if (v === previousSelection) option.selected = true;
                        solveForSelect.appendChild(option);
                    });
                } else {
                    // 🚀 PRESERVE: If options match, make sure your user's selection isn't lost
                    if (previousSelection && solveForSelect.value !== previousSelection) {
                        solveForSelect.value = previousSelection;
                    }
                }
            }
        }

        // 🎯 FIX: Listen to change directly on this card's select instance
        // This stops global document intercept collisions from mutating processing states
        if (unusedVariablesPicker) {
            unusedVariablesPicker.addEventListener('change', function(e) {
                const pickedVar = this.value;
                if (!pickedVar) return;

                // Fire initialization workflow
                createSubstitutionRow(pickedVar);
                
                // Clear selected value back to index placeholder
                this.value = ""; 
            });
        }

        // 🎯 AUTO-POPULATE SUBSTITUTION LINES ON INITIAL OVERLAY LOAD
        if (savedValues) {
            Object.entries(savedValues).forEach(([key, vVal]) => {
                if (key.startsWith('sub_')) {
                    const varName = key.replace('sub_', '');
                    createSubstitutionRow(varName, vVal); 

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

        syncSolveForDropdown();
        refreshUnusedVariablesPicker();

        // 🎯 INTERNAL CARD INPUT EVENTS DELEGATION
        card.addEventListener('input', (e) => {
            const target = e.target;

            if (!target.matches('.val-input-formula, .val-input-solve-method, .val-input-solve-for, .val-substitution-input')) {
                return;
            }

            if (target.matches('.val-substitution-input')) {
                target.setAttribute('value', target.value);
            }

            const formulaInputEl = card.querySelector('.val-input-formula');
            card.querySelectorAll('.formula-inline-error-msg').forEach(el => el.remove());

            if (formulaInputEl) {
                const rawFormula = formulaInputEl.value;
                const variableMatches = rawFormula.match(/\b[a-zA-Z][0-9]*\b/g) || [];
                const uniqueVars = [...new Set(variableMatches)];

                if (variablesField) {
                    variablesField.value = uniqueVars.join(', ');
                }
            }

            syncSolveForDropdown();
            refreshUnusedVariablesPicker();

            // 🚀 FIX: Force bubble a fresh change notice so the global debouncer 
            // captures the completely rendered DOM and cascading linked references!
            if (target.matches('.val-substitution-input')) {
                card.dispatchEvent(new Event('change', { bubbles: true }));
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

        // 1. Structural HTML layout adjustments
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

        // 2. Pure, fast local token replacement mapping
        let simulatedHtml = workingHtml.replace(tokenRegex, function(match, tokenText) {
            try {
                const cleanToken = (tokenText || match).replace(/[<>&]/g, '').trim().toLowerCase(); 
                let baseArchetypeToken = cleanToken.replace(/\d+$/, '').toLowerCase(); 

                // Find matching card state to accurately discover true archetype override tokens
                const card = Array.from(document.querySelectorAll('.workspace-block-card')).find(c => {
                    const delBtn = c.querySelector('.btn-delete-workspace-component');
                    return delBtn && delBtn.getAttribute('data-indexed-token').toLowerCase() === cleanToken;
                });

                if (card && card.getAttribute('data-token')) {
                    baseArchetypeToken = card.getAttribute('data-token').toLowerCase();
                }

                const isVar = dynamicVarsTokens.some(v => v.token.toLowerCase() === baseArchetypeToken) || baseArchetypeToken === 'formula';

                if (isVar) {
                    // 🎯 PURE RENDER: Check client-side live cache strings immediately
                    // Fall back gracefully to data attributes or the token name string
                    let displayVal = formulaLiveLatexCache[cleanToken];
                    if (!displayVal && card) {
                        displayVal = card.getAttribute('data-simulated-value') || cleanToken;
                    } else if (!displayVal) {
                        displayVal = cleanToken;
                    }

                    if (baseArchetypeToken === 'formula') {
                        return `<span class="simulated-math-formula-render" style="display: inline-block; padding: 2px 4px;">${displayVal}</span>`;
                    }
                    return `<span class="simulated-math-variable-badge" style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.9rem; display: inline-block; margin: 0 2px;">${displayVal}</span>`;
                } else if (answerFieldsTokens.some(i => i.token.toLowerCase() === baseArchetypeToken)) {
                    return `
                        <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px;">
                            <input type="text" placeholder="Input slot..." disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; width: 140px;">
                        </div>
                    `;
                }
                return match;
            } catch (err) {
                console.warn(`Token mapping failed for ${match}:`, err);
                return `<span style="color: red; font-family: monospace;">[Token Error]</span>`;
            }
        });

        renderTarget.innerHTML = simulatedHtml;

        // 3. Trigger KaTeX formatting over compiled elements
        if (typeof katex !== 'undefined') {
            renderTarget.querySelectorAll('.preview-static-latex').forEach(span => {
                try {
                    katex.render(span.textContent.trim(), span, { displayMode: false, throwOnError: false });
                } catch (err) { console.error(err); }
            });

            renderTarget.querySelectorAll('.simulated-math-formula-render').forEach(span => {
                try {
                    const expression = span.textContent.trim();
                    if (expression) {
                        katex.render(expression, span, { displayMode: false, throwOnError: false });
                    }
                } catch (err) { 
                    console.error("Dynamic formula preview compilation failure:", err); 
                }
            });
        }
    }

    // Serializes active layout properties into structural object dictionaries
    function serializeAllWorkspaceEntities() {
        const entities = [];
        document.querySelectorAll('.workspace-block-card').forEach(card => {
            const delBtn = card.querySelector('.btn-delete-workspace-component');
            const token = delBtn ? delBtn.getAttribute('data-indexed-token') : null;
            const archetype = card.getAttribute('data-archetype') || 'formula';
            
            if (!token) return;

            // 🚀 FIX: Check if the main formula input wrapper is currently substituted with a linked token pill
            const formulaWrapper = card.querySelector('.linked-input-wrapper[data-input-key="formula"]');
            const formulaTokenPill = formulaWrapper ? formulaWrapper.querySelector('.linked-token-pill') : null;
            
            let formulaInput = "";
            if (formulaTokenPill) {
                const rawPillId = formulaTokenPill.getAttribute('data-indexed-token') || formulaTokenPill.textContent || "";
                const pillMatch = rawPillId.match(/(formula\d+|variable\d+|var\d+)/i);
                formulaInput = pillMatch ? `<${pillMatch[1].trim()}>` : "";
            } else {
                formulaInput = card.querySelector('.val-input-formula')?.value.trim() || "";
            }

            const solveMethod = card.querySelector('.val-input-solve-method')?.value || "leave as formula";
            const variables = card.querySelector('.val-input-variables, input[name="variables"]')?.value.trim() || "";
            const variableSubstitution = card.querySelector('.val-input-solve-for')?.value || "";

            const substitutions = {};
            const subsContainer = card.querySelector('.substitutions-list-container, .substitutions-entries-list, .substitutions-container');
            
            if (subsContainer) {
                subsContainer.querySelectorAll('.substitution-row-item').forEach(row => {
                    const vName = row.getAttribute('data-var-name');
                    if (!vName) return;

                    const selectEl = row.querySelector('select.linked-token-dropdown, .token-selector');
                    const tokenBadge = row.querySelector('.linked-token-pill, [data-indexed-token], .token-badge');

                    // Link structural reference tokens instead of display strings
                    if (selectEl && selectEl.value) {
                        substitutions[vName] = `<${selectEl.value.trim()}>`;
                    } else if (tokenBadge) {
                        const rawText = tokenBadge.getAttribute('data-indexed-token') || tokenBadge.textContent || "";
                        const tokenMatch = rawText.match(/(formula\d+|variable\d+|var\d+)/i);
                        if (tokenMatch) {
                            substitutions[vName] = `<${tokenMatch[1].trim()}>`;
                        }
                    } else {
                        const inputEl = row.querySelector('.val-substitution-input, input');
                        substitutions[vName] = inputEl ? inputEl.value.trim() : "";
                    }
                });
            }

            entities.push({
                token: token,
                archetype: archetype,
                inputs: {
                    formula: formulaInput,
                    "solve method": solveMethod,
                    variables: variables,
                    "variable substitution": variableSubstitution,
                    substitutions: substitutions
                }
            });
        });
        return entities;
    }

    // Client-Side DAG: Filters list down to an entity, its descendants, AND its required ancestors
    function getDownstreamDependencies(allEntities, editedToken) {
        if (!editedToken || editedToken === 'initial_load') return allEntities; // Fetch all elements on load

        const lowerEditedToken = editedToken.toLowerCase();

        // 1. Build a map of immediate dependencies (who relies on whom)
        // parentToChildrenMap: parent -> [children]
        // childToParentsMap: child -> [parents]
        const parentToChildrenMap = {};
        const childToParentsMap = {};
        
        allEntities.forEach(e => { 
            const token = e.token.toLowerCase();
            parentToChildrenMap[token] = []; 
            childToParentsMap[token] = [];
        });

        allEntities.forEach(e => {
            const currentToken = e.token.toLowerCase();
            const formulaStr = e.inputs.formula || "";
            const subValues = Object.values(e.inputs.substitutions || {}).join(' ');
            const combinedMatches = `${formulaStr} ${subValues}`.match(/formula\d+|variable\d+|var\d+/gi) || [];
            
            combinedMatches.forEach(dep => {
                const parentDep = dep.toLowerCase();
                // If the dependency exists as a valid workspace entity
                if (parentToChildrenMap[parentDep]) {
                    if (!parentToChildrenMap[parentDep].includes(currentToken)) {
                        parentToChildrenMap[parentDep].push(currentToken);
                    }
                    if (!childToParentsMap[currentToken].includes(parentDep)) {
                        childToParentsMap[currentToken].push(parentDep);
                    }
                }
            });
        });

        // 2. Set to track everything we must send in our batch payload
        const affected = new Set([lowerEditedToken]);

        // 3. Trace DOWNSTREAM (Descendants who need recalculation)
        const downstreamQueue = [lowerEditedToken];
        while (downstreamQueue.length > 0) {
            const current = downstreamQueue.shift();
            (parentToChildrenMap[current] || []).forEach(child => {
                if (!affected.has(child)) {
                    affected.add(child);
                    downstreamQueue.push(child);
                }
            });
        }

        // 4. Trace UPSTREAM (Ancestors needed by the backend to resolve math strings)
        // We start our upstream search from all nodes currently marked as affected
        const upstreamQueue = Array.from(affected);
        while (upstreamQueue.length > 0) {
            const current = upstreamQueue.shift();
            (childToParentsMap[current] || []).forEach(parent => {
                if (!affected.has(parent)) {
                    affected.add(parent);
                    upstreamQueue.push(parent); // Continue climbing up to grandparents
                }
            });
        }

        // 5. Filter all entities down to our completed dependency group map
        return allEntities.filter(e => affected.has(e.token.toLowerCase()));
    }


    function dispatchWorkspaceBatchSync(triggeringToken = null) {
        // 🚀 Block single row micro-dispatches while rebuilding the UI
        if (isWorkspaceInitializing && triggeringToken !== 'initial_load') {
            return;
        }

        const allEntities = serializeAllWorkspaceEntities();
        const affectedEntities = getDownstreamDependencies(allEntities, triggeringToken);

        if (affectedEntities.length === 0) return;

        // Create a unique timestamp for this request
        const currentTimestamp = Date.now();
        activeBatchSyncTimestamp = currentTimestamp;

        console.log(`🛰️ [Batch Dispatch] Sending payload size (${affectedEntities.length}) triggered by: ${triggeringToken || 'initial_load'}`);

        fetch('/assessment/api/validate-component-preview/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                trigger_token: triggeringToken,
                entities: affectedEntities
            })
        })
        .then(res => res.json())
        .then(data => {
            // 🎯 RACE CONDITION GUARD: Ignore response if a newer request has already started
            if (currentTimestamp !== activeBatchSyncTimestamp) {
                console.warn("Discarding stale batch sync response.");
                return;
            }

            if (!data.success) {
                console.error("Batch engine processing error:", data.error);
                return;
            }

            // Sync cache and DOM
            Object.keys(data.updated_cache).forEach(token => {
                const result = data.updated_cache[token];
                const lowerToken = token.toLowerCase();
                
                formulaLiveLatexCache[lowerToken] = result.latex_output;
                
                const card = Array.from(document.querySelectorAll('.workspace-block-card')).find(c => 
                    c.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token')?.toLowerCase() === lowerToken
                );
                
                if (card) {
                    card.setAttribute('data-simulated-value', result.evaluated_output);
                    const targetDisplay = card.querySelector('.simulation-preview-render-pane, .latex-render-box');
                    if (targetDisplay && typeof katex !== 'undefined') {
                        katex.render(result.latex_output, targetDisplay, { throwOnError: false });
                    }

                    // 1. Always update the automatically extracted variables text field from the server result
                    const varsInput = card.querySelector('.val-input-variables');
                    if (varsInput && result.extracted_variables !== undefined) {
                        varsInput.value = result.extracted_variables;
                    }

                    // Parse clean collections to evaluate genuine mathematical structural changes
                    const varArray = result.extracted_variables
                        ? result.extracted_variables.split(',').map(v => v.trim()).filter(v => v.length > 0).sort()
                        : [];

                    // 🚀 NEW: Rebuild the "Variable Substitutions" unused picker immediately with the fresh server data.
                    // This resolves the timing bug when flipping back to 'variable substitution' mode!
                    const unusedVariablesPicker = card.querySelector('.picker-unused-variables');
                    if (unusedVariablesPicker) {
                        // Gather what variables are actively assigned rows on screen right now
                        const currentlyAssignedVars = Array.from(card.querySelectorAll('.substitutions-list-container .substitution-row-item'))
                            .map(row => row.getAttribute('data-var-name'));

                        // Filter the fresh mathematical server variables list down to unused ones
                        const unusedVars = varArray.filter(v => !currentlyAssignedVars.includes(v));

                        if (unusedVars.length === 0) {
                            unusedVariablesPicker.parentElement.style.display = 'none';
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

                    // 2. Safely capture the separate solve-for target variable dropdown element
                    const solveForSelect = card.querySelector('.val-input-solve-for');
                    
                    // Only adjust the "Solve For Target" dropdown choices if it is actively visible on screen (simplify mode)
                    if (solveForSelect && solveForSelect.offsetWidth > 0 && solveForSelect.offsetHeight > 0) {
                        
                        const existingDropdownOptions = Array.from(solveForSelect.options)
                            .map(opt => opt.value.trim())
                            .filter(val => val.length > 0)
                            .sort();

                        const dropdownOptionsStructurallyChanged = 
                            varArray.length !== existingDropdownOptions.length || 
                            !varArray.every((v, i) => v === existingDropdownOptions[i]);

                        const currentSelection = solveForSelect.value;

                        // Only rewrite the inner options if the core equations structural variables pool mutated
                        if (dropdownOptionsStructurallyChanged) {
                            console.log(`🔄 Formula variables changed for visible dropdown on [${lowerToken}]. Rebuilding options...`);
                            
                            let selectHtml = '<option value="">-- select variable --</option>';
                            varArray.forEach(v => {
                                const selectedAttr = (v === currentSelection) ? 'selected="selected"' : '';
                                selectHtml += `<option value="${v}" ${selectedAttr}>${v}</option>`;
                            });
                            
                            solveForSelect.innerHTML = selectHtml;
                            
                            // Keep selection intact if it survived the formula modification
                            if (currentSelection && varArray.includes(currentSelection)) {
                                solveForSelect.value = currentSelection;
                            } else {
                                solveForSelect.value = '';
                            }

                            // Trigger layout changes downstream since option choices altered
                            if (varsInput) {
                                varsInput.dispatchEvent(new Event('input', { bubbles: true }));
                                varsInput.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                            if (typeof syncSubstitutionRows === 'function') {
                                syncSubstitutionRows(card);
                            }
                        }
                    }
                }
            });

            updateWorkspaceSimulationPreview();
        })
        .catch(err => console.error("Consolidated batch synchronization dispatch failed:", err));
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
            // 🎯 UPDATE: Notify the batch sync pipeline that a card was deleted
            if (typeof dispatchWorkspaceBatchSync === 'function') {
                dispatchWorkspaceBatchSync(null);
            } else {
                updateWorkspaceSimulationPreview();
            }
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

            // UPGRADED: Assign a completely unique, non-sequential random float multiplier 
            // so it breaks any repeating cyclic loops when evaluating the pool.
            cardElement.setAttribute('data-shuffle-seed', Math.random().toString());

            // 🎯 UPDATE: Pull the token ID of this specific card to recalculate its dependencies
            const cardTokenId = cardElement.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');

            if (typeof dispatchWorkspaceBatchSync === 'function' && cardTokenId) {
                dispatchWorkspaceBatchSync(cardTokenId);
            } else {
                updateWorkspaceSimulationPreview();
            }
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

            // 🎯 CORRECTED FIX: Explicitly target your actual wrapper line element ID
            if (tokensLedger) {
                console.log("🧼 Flushing stale visual tokens from the ledger wrapper...");
                tokensLedger.innerHTML = ''; 
            }

            if (typeof formulaLiveLatexCache !== 'undefined') {
                formulaLiveLatexCache = {}; 
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

                    // Directly read values if elements exist, removing condition overrides
                    if (baseToken === 'formula') {
                        // 1. Snag the explicit target variable dropdown selection value directly if present
                        const solveForSelect = card.querySelector('.val-input-solve-for');
                        if (solveForSelect && solveForSelect.value) {
                            inputValues['variable to solve for'] = solveForSelect.value.trim();
                        } else {
                            // 🚀 FIX: Maintain key parity here so 'variable to solve for' is explicitly normalized to an empty string
                            inputValues['variable to solve for'] = '';
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
            
            // Safely find the input or label to restore viewports accurately without breaking sub_ layouts
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

            // 🚀 FIX: Pull the parent workspace component block token ID
            const activeCard = linkBtn.closest('.workspace-block-card');
            if (activeCard) {
                const cardId = activeCard.querySelector('.btn-delete-workspace-component')
                                         ?.getAttribute('data-indexed-token');
                
                if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
                    console.log(`🧼 Token unlink action cleared on [${cardId}]. Packaging updated graph topology...`);
                    // Call the background synchronization system for this structural node change
                    dispatchWorkspaceBatchSync(cardId);
                } else {
                    updateWorkspaceSimulationPreview();
                }
            } else {
                updateWorkspaceSimulationPreview();
            }
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
        const targetTypeAttr = wrapper.getAttribute('data-input-type') || ''; // e.g., 'double' or 'integer'
        const currentCard = linkBtn.closest('.workspace-block-card');
        const activeCards = Array.from(document.querySelectorAll('.workspace-block-card'));
        
        console.log(`\n--- 🏁 Linker Diagnostics Started ---`);
        console.log(`Target Input Key: "${wrapper.getAttribute('data-input-key')}"`);
        console.log(`Target Raw Type Attribute: "${targetTypeAttr}"`);

        // 🎯 1. Normalize the field's accepted types into an array.
        let acceptedTargetTypes = [targetTypeAttr];
        if (targetTypeAttr === 'double') {
            acceptedTargetTypes.push('integer');
        }
        console.log(`Normalized Accepted Types Array:`, acceptedTargetTypes);
        console.log(`Global Database Registry (dynamicVarsTokens):`, dynamicVarsTokens);

        let availableOptionsHtml = '';
        
        activeCards.forEach(card => {
            // Prevent linking a card back into itself
            if (card === currentCard) return;

            const deleteBtn = card.querySelector('.btn-delete-workspace-component');
            if (!deleteBtn) return;

            const indexedToken = deleteBtn.getAttribute('data-indexed-token'); // e.g., "randInt2"
            const baseArchetype = card.getAttribute('data-token');             // e.g., "rand"

            console.log(`\nEvaluating Sidebar Option Card -> [${indexedToken}] (Archetype: "${baseArchetype}")`);

            // 🎯 2. LOOK UP DATA DIRECTLY FROM YOUR ENTITY_TYPE DATABASE LEDGER
            const tokenDefinition = dynamicVarsTokens.find(t => t.token === baseArchetype);
            
            if (!tokenDefinition) {
                console.error(`❌ DATABASE MISMATCH: No token schema configuration row found matching archetype: "${baseArchetype}" in dynamicVarsTokens ledger.`);
                return;
            }
            
            console.log(`Found Registry Schema Definition for "${baseArchetype}":`, tokenDefinition);

            // 🎯 PARSE FORMAT PATTERN BLUUPRINT FROM THE SEED MODEL DYNAMICALLY
            let blueprintData = {};
            if (tokenDefinition.format_pattern) {
                try {
                    blueprintData = typeof tokenDefinition.format_pattern === 'string'
                        ? JSON.parse(tokenDefinition.format_pattern)
                        : tokenDefinition.format_pattern;
                } catch (e) {
                    console.warn(`⚠️ Failed to parse format_pattern for ${baseArchetype}:`, e);
                }
            }

            // Extract the output property from the parsed blueprint, or use tokenDefinition properties
            let rawOutput = blueprintData.output || tokenDefinition.output;

            // Strict fallback default values if the property is missing everywhere
            if (!rawOutput) {
                if (baseArchetype === 'randInt') rawOutput = ['integer'];
                else if (baseArchetype === 'rand') rawOutput = ['double'];
                else if (baseArchetype === 'formula') rawOutput = ['double', 'integer', 'formula'];
                else if (baseArchetype === 'matrix') rawOutput = ['matrix'];
            }

            // Normalize the output property into an array context seamlessly
            const derivedOutputs = Array.isArray(rawOutput) ? rawOutput : [rawOutput];
            
            console.log(`Normalized Token Source Outputs:`, derivedOutputs);

            // Check if the input key is a template substitution row
            const inputKey = wrapper.getAttribute('data-input-key') || '';
            
            // 🎯 3. Determine compatibility dynamically via array intersection (.some)
            let isCompatible = derivedOutputs.some(type => acceptedTargetTypes.includes(type));
            console.log(`Intersection Type Match Result (derivedOutputs vs acceptedTargetTypes): ${isCompatible}`);

            // FORCE COMPATIBILITY OVERRIDE: permit substitution inputs to couple with double, integer, or formula tokens
            if (inputKey.startsWith('sub_')) {
                const isSubCompatible = derivedOutputs.some(type => ['double', 'integer', 'formula'].includes(type));
                isCompatible = isSubCompatible;
            }

            if (isCompatible) {
                console.log(`✅ MATCH SUCCESS: Adding <${indexedToken}> into dropdown list.`);
                availableOptionsHtml += `
                    <button type="button" class="select-link-token-option" data-target-token="&lt;${indexedToken}&gt;" style="width: 100%; text-align: left; padding: 6px 12px; background: none; border: none; font-size: 0.75rem; cursor: pointer; transition: background 0.15s; color: #334155;">
                        &lt;${indexedToken}&gt;
                    </button>
                `;
            } else {
                console.log(`🚫 MATCH FAILED: <${indexedToken}> is incompatible with fields requiring ${targetTypeAttr}.`);
            }
        });

        console.log(`\n--- 🏁 Linker Diagnostics Complete. Total generated choices: ${availableOptionsHtml ? 'Options Present' : 'Zero Options Found'} ---`);

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
        const chosenTokenString = optionBtn.getAttribute('data-target-token'); // e.g., "<formula3>"
        
        // 🎯 FIX: Extract the raw unbracketed ID string (e.g., "formula3") for matching
        const rawTokenId = chosenTokenString.replace(/[<>]/g, '');

        const wrapper = optionBtn.closest('.linked-input-wrapper');
        const linkBtn = wrapper.querySelector('.btn-input-link-trigger');
        
        const labelEl = wrapper.querySelector('label');
        if (labelEl) {
            labelEl.style.display = 'none';
        } else {
            const inputEl = wrapper.querySelector('.val-substitution-input');
            if (inputEl) inputEl.style.display = 'none';
        }
        
        // Save dependency configuration explicitly onto the node wrapper properties
        wrapper.setAttribute('data-bound-token', chosenTokenString);

        // Inject the visual element capsule tracking pill design
        const pill = document.createElement('span');
        pill.className = 'linked-token-pill';
        
        // 🎯 FIX: Explicitly bind the clean index key so your scraping compiler loops can read it
        pill.setAttribute('data-indexed-token', rawTokenId);
        
        pill.style.cssText = 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 4px 8px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.8rem; display: inline-block; width: 100%; box-sizing: border-box; text-align: center;';
        pill.innerText = chosenTokenString;
        wrapper.insertBefore(pill, linkBtn);

        // Transform link icon to an active red delete close asset marker
        linkBtn.innerHTML = '<i class="fas fa-times"></i>';
        linkBtn.className = 'btn-input-link-trigger is-linked';
        linkBtn.style.color = '#ef4444';
        linkBtn.style.borderColor = '#fca5a5';

        // Close options dropdown picker instance frame
        wrapper.querySelector('.linkable-tokens-dropdown').style.display = 'none';
        
        // 🚀 FIX: Find the enclosing formula card element container
        const activeCard = wrapper.closest('.workspace-component-card');
        if (activeCard) {
            const cardId = activeCard.querySelector('.btn-delete-workspace-component')
                                     ?.getAttribute('data-indexed-token');
            
            if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
                console.log(`🔗 Token dependency linkage created on [${cardId}]. Syncing network compilation tree...`);
                // Force a network validation step for this specific component card and its dependencies
                dispatchWorkspaceBatchSync(cardId);
            } else {
                updateWorkspaceSimulationPreview();
            }
        } else {
            updateWorkspaceSimulationPreview();
        }
    });

    // Close options dropdown panels automatically if clicking outward away from tracking structures
    document.addEventListener('click', function() {
        document.querySelectorAll('.linkable-tokens-dropdown').forEach(d => d.style.display = 'none');
    });

    // =============================================================================
    // REAL-TIME COMPONENT LIVE-SYNC DISPATCHER
    // =============================================================================
    (function() {
        const debouncedNetworkDispatches = {};

        function triggerLiveSync(e) {
            const target = e.target;
            // Target any inputs or select dropdowns inside a formula workspace component card
            const card = target.closest('.workspace-component-card');
            
            if (card) {
                const cardId = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                if (!cardId) return;

                // Clear previous timeout for this specific card to debounce keystrokes
                if (debouncedNetworkDispatches[cardId]) {
                    clearTimeout(debouncedNetworkDispatches[cardId]);
                }

                // Set a brief delay so it fires after the user pauses typing or selecting
                debouncedNetworkDispatches[cardId] = setTimeout(() => {
                    console.log(`⚡ Live control change detected on [${cardId}]. Forcing single batch sync refresh...`);

                    // Call the batch sync pipeline for the modified element
                    if (typeof dispatchWorkspaceBatchSync === 'function') {
                        dispatchWorkspaceBatchSync(cardId);
                    } else {
                        updateWorkspaceSimulationPreview();
                    }
                }, 600); // 300ms window
            }
        }

        // Attach event listeners to the document level to catch dynamic elements bubbling up
        document.addEventListener('input', triggerLiveSync);
        document.addEventListener('change', triggerLiveSync);
    })();

});