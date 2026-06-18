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
                <label style="font-size: 0.75rem; color: #475569;">Formula expression string: 
                    <input type="text" class="val-input-formula" value="${savedValues.formula || ''}" placeholder="e.g. 3*x + 5" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        } else if (token === 'mathAnswer') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569; display:block; margin-bottom:4px;">Correct Target Formula: 
                    <input type="text" class="val-input-correct-formula" value="${savedValues.correct_formula || ''}" placeholder="e.g. factor(x**2 - 1)" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
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

        // Interactive UI hover transitions
        const refreshIconBtn = card.querySelector('.btn-refresh-workspace-component-value');
        if (refreshIconBtn) {
            refreshIconBtn.onmouseenter = () => refreshIconBtn.style.color = '#0284c7';
            refreshIconBtn.onmouseleave = () => refreshIconBtn.style.color = '#94a3b8';
        }

        const infoIcon = card.querySelector('.fa-info-circle');
        if (infoIcon) {
            infoIcon.onmouseenter = () => infoIcon.style.color = '#64748b';
            infoIcon.onmouseleave = () => infoIcon.style.color = '#94a3b8';
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

        // 🎯 NEW REHYDRATION RE-LINKING MATRIX
        // Scan all newly created input wrappers on this card to check if their saved values are tokens
        const newlyCreatedWrappers = card.querySelectorAll('.linked-input-wrapper');
        newlyCreatedWrappers.forEach(wrapper => {
            const inputKey = wrapper.getAttribute('data-input-key');
            const savedValue = savedValues[inputKey];

            // If the saved parameter is a linked token string (e.g., "<randInt4>")
            if (savedValue && typeof savedValue === 'string' && savedValue.trim().match(/^<([^>]+)>$/)) {
                const cleanTokenString = savedValue.trim();
                const linkBtn = wrapper.querySelector('.btn-input-link-trigger');
                
                // 1. Hide the native fallback input element label text
                wrapper.querySelector('label').style.display = 'none';
                
                // 2. Explicitly stamp the structural relation connection parameter
                wrapper.setAttribute('data-bound-token', cleanTokenString);

                // 3. Inject the green tracking pill capsule interface design
                const pill = document.createElement('span');
                pill.className = 'linked-token-pill';
                pill.style.cssText = 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 4px 8px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.8rem; display: inline-block; width: 100%; box-sizing: border-box; text-align: center;';
                pill.innerText = cleanTokenString;
                wrapper.insertBefore(pill, linkBtn);

                // 4. Pivot the link button into an active red close asset layout element
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
    // RECURSIVE DEPENDENCY RESOLUTION HELPER (WITH CYCLE DETECTION)
    // -------------------------------------------------------------
    function getLiveComponentValue(card, inputKey, defaultFallback, visitedTokens = []) {
        if (!card) return defaultFallback;
        
        // Find the specific wrapper container for this input parameter field
        const wrapper = card.querySelector(`.linked-input-wrapper[data-input-key="${inputKey}"]`);
        if (!wrapper) {
            // Fallback for elements without standard linkage wrappers yet (like formula inputs)
            const inputField = card.querySelector(`[class*="val-input-${inputKey}"]`);
            return inputField ? inputField.value.trim() : defaultFallback;
        }

        const boundToken = wrapper.getAttribute('data-bound-token');
        if (boundToken) {
            const cleanTargetToken = boundToken.replace(/[<>]/g, '').trim(); // e.g., "randInt2"
            
            // 🛑 CYCLE BREAK ENGINE: If this token is already being calculated in this call stack branch
            if (visitedTokens.includes(cleanTargetToken)) {
                return defaultFallback;
            }

            // Scan the DOM to locate the source variable component card
            const allCards = document.querySelectorAll('.workspace-block-card');
            let matchedValue = defaultFallback;

            allCards.forEach(sourceCard => {
                const deleteBtn = sourceCard.querySelector('.btn-delete-workspace-component');
                if (deleteBtn && deleteBtn.getAttribute('data-indexed-token') === cleanTargetToken) {
                    // Forward current tracking ledger plus the target token down the stack
                    matchedValue = evaluateSingleCardOutput(sourceCard, cleanTargetToken, [...visitedTokens, cleanTargetToken]);
                }
            });
            return matchedValue;
        }

        // No link: fallback directly onto the text/numeric input value parameter
        const inputField = wrapper.querySelector('input');
        return (inputField && inputField.value !== '') ? inputField.value.trim() : defaultFallback;
    }

    // Isolate the core calculation matrix out of the main loop so it can be resolved recursively
    function evaluateSingleCardOutput(card, tokenIdentifier, visitedTokens = []) {
        const baseArchetype = card.getAttribute('data-token');

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
                    return pool[targetIndex].toString();
                }
            }
        } 
        else if (baseArchetype === 'rand') {
            const minVal = parseFloat(getLiveComponentValue(card, 'min', 0.0, visitedTokens));
            const maxVal = parseFloat(getLiveComponentValue(card, 'max', 1.0, visitedTokens));
            const stepVal = parseFloat(getLiveComponentValue(card, 'step', 0.01, visitedTokens));
            return minVal.toString(); 
        }
        else if (baseArchetype === 'primeFactors') {
            let targetNum = parseInt(getLiveComponentValue(card, 'number to factor', 12, visitedTokens), 10);
            if (!isNaN(targetNum) && targetNum > 1) {
                const factors = [];
                while (targetNum % 2 === 0) { factors.push(2); targetNum = Math.floor(targetNum / 2); }
                let factor = 3;
                while (factor * factor <= targetNum) {
                    while (targetNum % factor === 0) { factors.push(factor); targetNum = Math.floor(targetNum / factor); }
                    factor += 2;
                }
                if (targetNum > 1) factors.push(targetNum);
                return factors.join(', ');
            }
            return "";
        }
        else if (baseArchetype === 'formula') {
            const formulaField = card.querySelector('.val-input-formula');
            return formulaField ? formulaField.value.trim() : '';
        }

        return card.getAttribute('data-simulated-value') || '';
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
                    // 🚀 FIXED: Changed 'cleanToken' to 'cleanTargetToken' to match correct scope variables
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
                val = getLiveComponentValue(card, 'formula', '3*x + 5', visitedTokens);
            }

            // Fallback cleanly onto seed attribute markers if evaluation results output blank string/null maps
            if (val === null || val === '') {
                val = card.getAttribute('data-simulated-value');
            }
            return val;
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
            const cleanToken = (tokenText || match).replace(/[<>&]/g, '').trim(); // e.g., "primeFactors1"
            let evaluationValue = null;
            
            // Scan through available live DOM items to match our tracking token target
            const allCards = document.querySelectorAll('.workspace-block-card');
            allCards.forEach(card => {
                const deleteBtn = card.querySelector('.btn-delete-workspace-component');
                if (deleteBtn && deleteBtn.getAttribute('data-indexed-token') === cleanToken) {
                    // Execute calculation engine matrix mapping dependencies down recursively
                    evaluationValue = evaluateSingleCardOutput(card, cleanToken);
                }
            });

            const baseArchetypeToken = cleanToken.replace(/\d+$/, '');
            const isVar = dynamicVarsTokens.some(v => v.token === baseArchetypeToken);
            
            if (isVar) {
                const displayVal = evaluationValue !== null ? evaluationValue : cleanToken;
                return `<span class="simulated-math-variable-badge" style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.9rem; display: inline-block; margin: 0 2px;">${displayVal}</span>`;
            } else if (answerFieldsTokens.some(i => i.token === baseArchetypeToken)) {
                return `
                    <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px;">
                        <input type="text" placeholder="Input slot..." disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; width: 140px;">
                    </div>
                `;
            }
            return match;
        });

        renderTarget.innerHTML = simulatedHtml;

        if (typeof katex !== 'undefined') {
            renderTarget.querySelectorAll('.preview-static-latex').forEach(span => {
                try {
                    katex.render(span.textContent.trim(), span, { displayMode: false, throwOnError: false });
                } catch (err) {
                    console.error(err);
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

                // 🎯 REPLACEMENT STRATEGY: Loop dynamically over your wrappers 
                // to support both raw user entries AND nested token output dependencies.
                const inputWrappers = card.querySelectorAll('.linked-input-wrapper');
                
                // Add new entity Step 3: if new fields exist, then add them here so I can extract the values

                if (inputWrappers.length > 0) {
                    inputWrappers.forEach(wrapper => {
                        const inputKey = wrapper.getAttribute('data-input-key'); // e.g., "min", "max", "number to factor"
                        const boundToken = wrapper.getAttribute('data-bound-token'); // e.g., "<randInt1>" or null
                        
                        if (boundToken) {
                            // Link is active: grab the cross-referenced variable token tag string directly
                            inputValues[inputKey] = boundToken;
                        } else {
                            // No link active: fall back to the standard input field value
                            const inputField = wrapper.querySelector('input');
                            if (inputField) {
                                inputValues[inputKey] = inputField.value.trim();
                            }
                        }
                    });
                } else {
                    // 🛡️ Safe fallback block for legacy nodes (like formula/mathAnswer) 
                    // until you choose to wrap them in .linked-input-wrapper structures as well.
                    const formulaEl = card.querySelector('.val-input-formula');
                    if (formulaEl) inputValues.formula = formulaEl.value.trim();

                    const correctFormulaEl = card.querySelector('.val-input-correct-formula');
                    if (correctFormulaEl) inputValues.correct_formula = correctFormulaEl.value.trim();
                }

                // 🚀 FIX: Send the clean base database token, and pass the indexed tracking sequence string separately
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
            wrapper.querySelector('label').style.display = 'block'; // Show input field again
            
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
            if (derivedOutputs.includes(targetType)) {
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
        const chosenTokenString = optionBtn.getAttribute('data-target-token'); // "<randInt1>"
        const wrapper = optionBtn.closest('.linked-input-wrapper');
        const linkBtn = wrapper.querySelector('.btn-input-link-trigger');
        
        // Hide the input field label completely
        wrapper.querySelector('label').style.display = 'none';
        
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
});