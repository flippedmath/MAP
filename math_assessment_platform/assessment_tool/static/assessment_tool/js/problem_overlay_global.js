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
        // console.log(`⚙️ [Dropdown Router Setup] Configuring trigger handler for ID: '#${triggerId}'`);
        const trigger = document.getElementById(triggerId);
        const menu = document.getElementById(menuId);
        if (!trigger || !menu) {
            console.warn(`⚠️ Interface binding canceled: Element mismatch on selector tracking tokens. Trigger exists=${!!trigger}, Menu exists=${!!menu}`);
            return;
        }

        let tokensArray = [];
        if (Array.isArray(tokens)) {
            tokensArray = tokens;
        } else if (tokens && typeof tokens === 'object') {
            tokensArray = Object.values(tokens);
        }

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
            // console.log(`🖱️ Dropdown Menu Click Intercepted: Toggling panel visibility context for: '#${menuId}'`);
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
            console.group(`%c➕ [User Action] Sidebar Option Selection Triggered: <${tokenSelected}>`, "background: #16a34a; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;");
            
            const isVariable = dynamicVarsTokens.some(item => item.token === tokenSelected);
            const targetContainer = isVariable ? variablesContainer : inputsContainer;

            if (targetContainer) {
                // console.log(`Target placement layout panel resolved. Appending new block instance component.`);
                removePlaceholders(targetContainer);
                createTokenBadge(tokenSelected);
                createNewBlockInstanceUI(tokenSelected, targetContainer, {});
                
                const builtCards = targetContainer.querySelectorAll('.workspace-block-card');
                const newestCard = builtCards[builtCards.length - 1];
                const cardTokenId = newestCard?.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                // console.log(`Extracted identifying component sequence tracking token label: "${cardTokenId}"`);

                if (typeof dispatchWorkspaceBatchSync === 'function' && cardTokenId) {
                    // console.log(`Forwarding new component tracking parameters directly to network evaluation pipeline...`);
                    dispatchWorkspaceBatchSync(cardTokenId);
                } else {
                    updateWorkspaceSimulationPreview();
                }
            } else {
                console.error("❌ Missing layout container references wrapper. Block instantiation aborted.");
            }
            
            menu.style.display = 'none';
            console.groupEnd();
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
        console.group(`%c🔄 [Workspace Rehydration] Initializing Layout Hydration Loop`, "background: #7c3aed; color: white; padding: 3px 6px; border-radius: 4px; font-weight: bold;");

        isWorkspaceInitializing = true; 
        window.isHydratingWorkspace = true; // Set both flags at the top

        try {
            if (!segments || segments.length === 0) {
                console.warn("⚠️ Database segment array payload is unpopulated or missing. Resetting sidebar panels to initial default states.");
                clearAndShowPlaceholders();
                return; // 🌟 Safe early exit! The 'finally' block will still unlock the state.
            }

            if (variablesContainer) variablesContainer.innerHTML = '';
            if (inputsContainer) inputsContainer.innerHTML = '';
            if (tokensLedger) tokensLedger.innerHTML = '';

            segments.forEach((segment, idx) => {
                console.group(`Segment Iterator Node [Index: ${idx}] ➔ Processing: <${segment.token}>`);
                const isVariable = dynamicVarsTokens.some(item => item.token === segment.token);
                const targetContainer = isVariable ? variablesContainer : inputsContainer;

                if (!targetContainer) {
                    console.error("❌ Panel target DOM node reference lookup returned undefined. Skipping rehydration pass.");
                    console.groupEnd();
                    return;
                }

                removePlaceholders(targetContainer);
                
                const savedSequenceToken = segment.sequence_token; 
                createTokenBadge(segment.token, savedSequenceToken);
                createNewBlockInstanceUI(segment.token, targetContainer, segment.inputs, segment.points, savedSequenceToken);
            
                const builtCards = targetContainer.querySelectorAll('.workspace-block-card');
                const latestCard = builtCards[builtCards.length - 1];
                if (latestCard) {
                    if (segment.simulated_value !== undefined) {
                        latestCard.setAttribute('data-simulated-value', segment.simulated_value);
                    }
                    if (segment.shuffle_seed !== undefined && segment.shuffle_seed !== null && segment.shuffle_seed !== '') {
                        latestCard.setAttribute('data-shuffle-seed', segment.shuffle_seed);
                    }
                }
                console.groupEnd();
            });

            // Run structural cleanups
            checkEmptyColumns();

            // Run calculation triggers
            if (typeof dispatchWorkspaceBatchSync === 'function') {
                // Pass 'initial_load' instead of null to bypass the initialization block
                dispatchWorkspaceBatchSync('initial_load');
            } else {
                updateWorkspaceSimulationPreview();
            }

        } catch (error) {
            console.error("💥 Critical error during workspace rehydration:", error);
        } finally {
            // 🔓 This block ALWAYS executes, saving the application state from lockouts
            isWorkspaceInitializing = false; 
            window.isHydratingWorkspace = false;
            console.groupEnd();
        }
    }


    /**
     * Unified Form Element Interface Constructor Factory
     */
    function createNewBlockInstanceUI(token, containerElement, savedValues = {}, points = 0.0, overrideSequenceToken = undefined) {
        console.group(`%c🔨 [UI Builder] Instantiating Component Card: <${token}>`, "background: #0ea5e9; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;");
        // console.log("Input Configuration Arguments:", { savedValues, points, overrideSequenceToken });

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
            // console.log(`🏷️ Sequence token explicitly overridden by parameters: "${indexedTokenString}"`);
        } else {
            // console.log("🔍 No explicit sequence token supplied. Calculating look-ahead array position indices...");
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
            // console.log(`🔢 Incremental matching layout index determined. Next generated sequence ID signature: "${indexedTokenString}"`);
        }

        const tokenSourceArray = isVariable ? dynamicVarsTokens : answerFieldsTokens;
        const matchingTokenData = tokenSourceArray.find(item => item.token === token);
        const tokenNoteHint = matchingTokenData ? (matchingTokenData.note || '') : '';

        // Helper function to prevent inserting literal token strings into type="number" inputs
        const safeNumValue = (val, fallback) => {
            if (typeof val === 'string' && val.trim().match(/^<([^>]+)>$/)) {
                // console.log(`🔗 Defensive Intercept: Value '${val}' is an upstream link token shortcut. Masking input with fallback standard default: ${fallback}`);
                return fallback; 
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

        if (token === 'formula') {
            card.addEventListener('input', function() {
                // console.log(`📝 Keystroke detected inside Formula expression container [${indexedTokenString}]. Triggering fast canvas preview re-render.`);
                updateWorkspaceSimulationPreview();
            });
        }

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
        // console.log(`✅ Appended card [${indexedTokenString}] to sidebar layout wrapper tree node.`);

        if (!card.hasAttribute('data-shuffle-seed') || card.getAttribute('data-shuffle-seed') === '') {
            const freshSeed = Math.random().toString();
            card.setAttribute('data-shuffle-seed', freshSeed);
            // console.log(`🎲 Generated persistent math randomization seed for [${indexedTokenString}]:`, freshSeed);
        }

        if (token === 'formula') {
            // console.log(`🔗 Executing deep sub-binding logic 'bindLiveFormulaEvaluation' for expression card.`);
            bindLiveFormulaEvaluation(card, savedValues || {});
        }

        // console.log("🛠️ Scanning nested layout wrapper wrappers for pre-existing macro links...");
        const newlyCreatedWrappers = card.querySelectorAll(
            '.linked-input-wrapper:not(.substitutions-list-container .linked-input-wrapper)'
        );
        newlyCreatedWrappers.forEach(wrapper => {
            const inputKey = wrapper.getAttribute('data-input-key');
            const savedValue = savedValues[inputKey];

            if (savedValue && typeof savedValue === 'string' && savedValue.trim().match(/^<([^>]+)>$/)) {
                const cleanTokenString = savedValue.trim();
                // console.log(`  📍 Found active dependency link rule under field row [${inputKey}] targeting: "${cleanTokenString}"`);
                const linkBtn = wrapper.querySelector('.btn-input-link-trigger');
                
                const labelEl = wrapper.querySelector('label');
                if (labelEl) {
                    labelEl.style.display = 'none';
                } else {
                    const inputEl = wrapper.querySelector('input, select');
                    if (inputEl) inputEl.style.display = 'none';
                }
                
                wrapper.setAttribute('data-bound-token', cleanTokenString);

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

        card.addEventListener('input', function(e) {
            if (e.target.matches('input, select, textarea')) {
                if (saveStatusSpan) {
                    saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                }
                updateWorkspaceSimulationPreview();
            }
        });

        updateWorkspaceSimulationPreview();
        console.groupEnd();
    }

    // Streamlined lookup: reads local fields directly with recursive link token traversal
    function getLiveComponentValue(card, inputKey, defaultFallback) {
        console.group(`%c🔍 [Live Component Lookup] Key: "${inputKey}"`, "color: #94a3b8; font-style: italic;");
        if (!card) {
            console.warn(`⚠️ getLiveComponentValue aborting: 'card' DOM reference parameter is null. Returning fallback: "${defaultFallback}"`);
            console.groupEnd();
            return defaultFallback;
        }
        
        let rawValue = '';
        let linkedTokenName = null;

        // Check if wrapped in a structured input wrapper
        const wrapper = card.querySelector(`.linked-input-wrapper[data-input-key="${inputKey}"]`);
        if (wrapper) {
            // 🎯 STEP 1: Safely read the bound token and strip any brackets immediately
            const rawBoundToken = wrapper.getAttribute('data-bound-token');
            if (rawBoundToken) {
                linkedTokenName = rawBoundToken.replace(/[<>]/g, '').trim();
            }
            
            const nativeInput = wrapper.querySelector('input, select');
            rawValue = (nativeInput && nativeInput.value !== '') ? nativeInput.value.trim() : '';
            // console.log(`📍 Found structured input wrapper. Raw value: "${rawValue}", Target Clean Token: "${linkedTokenName}"`);
        } else {
            // Legacy fallback class check
            const legacyInput = card.querySelector(`.val-input-${inputKey}`);
            rawValue = legacyInput ? legacyInput.value.trim() : '';
            // console.log(`📍 Falling back to standard class matching lookup. Raw value: "${rawValue}"`);
        }

        // 🎯 STEP 2: Parse raw input content string macro tag if data-bound-token wasn't set on the wrapper
        if (!linkedTokenName && rawValue !== '') {
            const dynamicTokenRegex = /^<([a-zA-Z0-9_]+)>$/;
            const match = String(rawValue).match(dynamicTokenRegex);
            if (match) {
                linkedTokenName = match[1].trim();
            }
        }

        // 🎯 STEP 3: If an upstream link token relationship is established, resolve it recursively
        if (linkedTokenName) {
            // console.log(`🔗 [Link Intercept] Resolving active layout link dependency row targeting token: "${linkedTokenName}"`);
            
            // Locate the active interactive workspace card row using case-sensitive matching logic
            const upstreamCard = Array.from(document.querySelectorAll('.workspace-component-card')).find(c => {
                const delBtn = c.querySelector('.btn-delete-workspace-component');
                // Target 'data-indexed-token' on delete button or 'data-token' if used as custom backup signature
                const tokenSignature = delBtn ? delBtn.getAttribute('data-indexed-token') : null;
                return tokenSignature === linkedTokenName;
            });

            if (upstreamCard) {
                // console.log(`%c✔ Upstream card found for "${linkedTokenName}". Cascading recursive calculation...`, "color: #38bdf8; font-weight: bold;");
                
                // Recursively compute live numbers up the variable dependency chain
                const computedUpstreamValue = evaluateSingleCardOutput(upstreamCard, linkedTokenName);
                
                // console.log(`🏁 Recursive resolution complete. Token "${linkedTokenName}" mapped to value: "${computedUpstreamValue}"`);
                console.groupEnd();
                return computedUpstreamValue || defaultFallback;
            } else {
                console.warn(`⚠️ Upstream card reference for link token "${linkedTokenName}" is not available in the DOM tree yet.`);
            }
        }

        // Step 4: Fall back to native primitive input values if no active link dependencies exist
        const finalReturnedValue = rawValue !== '' ? rawValue : defaultFallback;
        // console.log(`📍 Primitive value evaluated successfully: "${finalReturnedValue}"`);
        console.groupEnd();
        return finalReturnedValue;
    }

    // -------------------------------------------------------------------------
    // 🎯 REFACTOR: Unified component row value retriever with recursive link tracking
    // -------------------------------------------------------------------------
    function getLiveComponentValue(card, inputKey, defaultFallback, visitedTokens = []) {
        if (!card) return defaultFallback;
        
        let rawValue = '';
        let linkedTokenName = null;

        // Inspect layout to determine if structured token wrappers are present
        const wrapper = card.querySelector(`.linked-input-wrapper[data-input-key="${inputKey}"]`);
        if (wrapper) {
            const rawBoundToken = wrapper.getAttribute('data-bound-token');
            if (rawBoundToken) {
                // Instantly strip angle brackets if present
                linkedTokenName = rawBoundToken.replace(/[<>]/g, '').trim();
            }
            const nativeInput = wrapper.querySelector('input, select, textarea');
            rawValue = (nativeInput && nativeInput.value !== '') ? nativeInput.value.trim() : '';
        } else {
            // Standard fallback signature check
            const legacyInput = card.querySelector(`.val-input-${inputKey}`);
            rawValue = legacyInput ? legacyInput.value.trim() : '';
        }

        // Parse token if added explicitly as text inside raw text element values
        if (!linkedTokenName && rawValue !== '') {
            const match = String(rawValue).match(/^<([a-zA-Z0-9_]+)>$/);
            if (match) {
                linkedTokenName = match[1].trim();
            }
        }

        // Trace and resolve dynamic dependency macros recursively
        if (linkedTokenName) {
            // 🛑 INFINITE LOOP PROTECTION: Short-circuit if a dependency loops back onto itself
            if (visitedTokens.includes(linkedTokenName)) {
                console.error(`🛑 [Circular Dependency Blocked] Token loop detected targeting: "${linkedTokenName}". Defensively utilizing fallback fallback: "${defaultFallback}"`);
                return defaultFallback;
            }

            // console.log(`🔗 [Link Trace] "${inputKey}" field resolves to upstream variable macro: "${linkedTokenName}"`);
            
            const upstreamCard = Array.from(document.querySelectorAll('.workspace-component-card')).find(c => {
                const delBtn = c.querySelector('.btn-delete-workspace-component');
                return delBtn && delBtn.getAttribute('data-indexed-token') === linkedTokenName;
            });

            if (upstreamCard) {
                // Pass downstream state references recursively up the execution trace line
                return evaluateSingleCardOutput(upstreamCard, linkedTokenName, [...visitedTokens]);
            } else {
                console.warn(`⚠️ Upstream component card reference targeting token "${linkedTokenName}" is missing from DOM.`);
            }
        }

        return rawValue !== '' ? rawValue : defaultFallback;
    }

    // -------------------------------------------------------------------------
    // ⚙️ CORE MATRIX: Updated Simulation Calculation Loop
    // -------------------------------------------------------------------------
    function evaluateSingleCardOutput(card, tokenIdentifier, visitedTokens = []) {
        if (!card) {
            console.warn(`[🔍 EVAL TRACE] evaluateSingleCardOutput called without a valid card element for token: "${tokenIdentifier}"`);
            return tokenIdentifier;
        }
        
        const baseArchetype = card.getAttribute('data-token');
        let val = null;

        // Push current node validation identifier to trace array sequence context
        if (!visitedTokens.includes(tokenIdentifier)) {
            visitedTokens.push(tokenIdentifier);
        }

        console.group(`%c⚙️ Local Math Calc: <${tokenIdentifier}> [Archetype: ${baseArchetype}]`, "background: #1e1e2e; color: #cdd6f4; padding: 3px 6px; border-radius: 4px; font-weight: bold;");

        // 🎯 PRIORITY A: Check if the server has stored a verified calculated value directly on the card markup
        const calculatedValueFallback = card.getAttribute('data-simulated-value');
        if (calculatedValueFallback !== null && calculatedValueFallback !== undefined && calculatedValueFallback !== '' && calculatedValueFallback !== 'None' && calculatedValueFallback !== 'null') {
            console.log(`%c✓ ${baseArchetype} reading directly from synchronized server state: "${calculatedValueFallback}"`, "color: #89b4fa; font-weight: bold;");
            console.groupEnd();
            return calculatedValueFallback;
        }

        // 🎯 PRIORITY B: Local Calculation engines serve purely as a cold bootstrap backup if server state isn't injected yet
        if (baseArchetype === 'randInt') {
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
                    val = pool[targetIndex].toString();
                }
            }
        } 
        else if (baseArchetype === 'rand') {
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
                    val = finalValue.toFixed(decimalPlaces);
                }
            }
        } 
        else if (baseArchetype === 'primeFactors') {
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
                val = factors.join(', ');
            } else {
                val = "";
            }
        }
        else if (baseArchetype === 'formula') {
            if (window.formulaLiveLatexCache && window.formulaLiveLatexCache[tokenIdentifier]) {
                console.groupEnd();
                return window.formulaLiveLatexCache[tokenIdentifier];
            }
            
            // Formulas accept dynamic variable evaluations safely via input keys
            const formulaStr = getLiveComponentValue(card, 'formula', tokenIdentifier, visitedTokens);
            console.groupEnd();
            return formulaStr;
        }

        // Final Output Summary Resolution (Fallback check if local engine rules fell through)
        const finalReturnedValue = (val !== null && val !== undefined && val !== '') ? val : tokenIdentifier;
        console.groupEnd();

        return finalReturnedValue;
    }

    function bindLiveFormulaEvaluation(card, savedValues = {}) {
        if (card.getAttribute('data-formula-listener-bound') === 'true') {
            return;
        }
        card.setAttribute('data-formula-listener-bound', 'true');

        const variablesField = card.querySelector('.val-input-variables');
        const solveMethodSelect = card.querySelector('.val-input-solve-method');
        
        // 🎯 Modern UI Rows and Dropdown Selectors
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

        // Alternates visibility matching your active layout contexts
        function syncSolveForDropdown() {
            const selectedMethod = solveMethodSelect?.value || "leave as formula";
            const previousMethod = card.getAttribute('data-last-method') || "";

            // If switching away from variable substitution, clear out evaluation entries list
            if (previousMethod === 'variable substitution' && selectedMethod !== 'variable substitution') {
                if (substitutionsContainer) substitutionsContainer.innerHTML = '';
                refreshUnusedVariablesPicker();
            }
            card.setAttribute('data-last-method', selectedMethod);

            // Hide everything by default first
            if (simplifyWrapper) simplifyWrapper.style.display = 'none';
            if (substitutionWrapper) substitutionWrapper.style.display = 'none';
            if (substitutionsWrapper) substitutionsWrapper.style.display = 'none';

            // Enable matching nodes conditionally
            if (selectedMethod === 'simplify') {
                if (simplifyWrapper) simplifyWrapper.style.display = 'flex';
                if (substitutionSelect) substitutionSelect.value = ""; 
                populateVariablesDropdown(simplifySelect);
            } 
            else if (selectedMethod === 'variable substitution') {
                // 🛑 FIXED: We keep 'substitutionWrapper' hidden so the "target variable" dropdown doesn't show up.
                // We ONLY display the rows container where actual variable substitutions happen.
                if (substitutionsWrapper) substitutionsWrapper.style.display = 'flex';
                
                // Clear out values on the unneeded selects
                if (simplifySelect) simplifySelect.value = ""; 
                if (substitutionSelect) substitutionSelect.value = "";
                
                refreshUnusedVariablesPicker();
            }
            else {
                if (simplifySelect) simplifySelect.value = "";
                if (substitutionSelect) substitutionSelect.value = "";
            }
        }

        // ✅ REFACTORED TO ONE FUNCTION: Accepts a target element to update seamlessly
        function populateVariablesDropdown(targetSelectElement) {
            if (!targetSelectElement || !variablesField) return;
            
            const currentVars = variablesField.value.split(',')
                .map(v => v.trim())
                .filter(v => v.length > 0);

            const savedTarget = savedValues['variable to simplify'] || savedValues['variable to substitute'] || savedValues['variable to solve for'] || "";
            
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

        function createSubstitutionRow(varName, initialValue = "") {
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
            card.dispatchEvent(new Event('change', { bubbles: true }));
        }

        if (unusedVariablesPicker) {
            unusedVariablesPicker.addEventListener('change', function() {
                const pickedVar = this.value;
                if (!pickedVar) return;
                createSubstitutionRow(pickedVar);
                this.value = ""; 
            });
        }

        if (savedValues) {
            if (solveMethodSelect && savedValues['solve method']) {
                solveMethodSelect.value = savedValues['solve method'];
                card.setAttribute('data-last-method', savedValues['solve method']);
            }

            // 🎯 FIXED: Assign incoming saved values to the matching contextual element
            const incomingVal = savedValues['variable to simplify'] || savedValues['variable to substitute'] || savedValues['variable to solve for'] || "";
            if (incomingVal) {
                if (simplifySelect) simplifySelect.setAttribute('data-saved-value', incomingVal);
                if (substitutionSelect) substitutionSelect.setAttribute('data-saved-value', incomingVal);
            }

            syncSolveForDropdown();

            Object.entries(savedValues).forEach(([key, vVal]) => {
                if (key.startsWith('sub_')) {
                    createSubstitutionRow(key.replace('sub_', ''), vVal);
                }
            });
        }

        syncSolveForDropdown();
        refreshUnusedVariablesPicker();

        // CAPTURE CARD INPUT MUTATIONS AND BUBBLE FRESH EVENTS UPSTREAM
        card.addEventListener('input', (e) => {
            const target = e.target;

            if (!target.matches('.val-input-formula, .val-input-solve-method, .val-input-simplify-target, .val-input-substitution-target, .val-substitution-input')) {
                return;
            }

            // 💾 Just cache the state; do NOT run structural rebuilds for this target here
            if (target.matches('.val-input-simplify-target')) {
                card.setAttribute('data-selected-variable', target.value);
                console.log(`%c💾 [STATE PERSIST] Saved user selection state to card attribute: "${target.value}"`, "color: #10b981;");
                
                // Skip syncSolveForDropdown() for changes to the dropdown itself to prevent flickering
                refreshUnusedVariablesPicker();
                card.dispatchEvent(new Event('change', { bubbles: true }));
                return;
            }

            if (target.matches('.val-substitution-input')) {
                target.setAttribute('value', target.value);
            }

            // 👁️ VISIBILITY TOGGLE: If the solve method changed, adjust dropdown display instantly
            if (target.matches('.val-input-solve-method')) {
                const solveMethod = target.value;
                // Find the closest wrapper layout container for the dropdown row
                const simplifyDropdownContainer = card.querySelector('.val-input-simplify-target')?.closest('.form-group, .input-row, div');
                
                if (simplifyDropdownContainer) {
                    if (solveMethod === 'variable substitution') {
                        simplifyDropdownContainer.style.display = 'none';
                        // Clean out client-side cached selection state so it doesn't leak
                        card.removeAttribute('data-selected-variable'); 
                    } else {
                        simplifyDropdownContainer.style.display = ''; // Restore default layout display (block/flex/etc)
                    }
                }
            }

            if (target.matches('.val-input-formula')) {
                const rawFormula = target.value;
                const variableMatches = rawFormula.match(/\b[a-zA-Z][0-9]*\b/g) || [];
                
                const coreTokensBlacklist = ['randInt', 'rand', 'primeFactor', 'sin', 'cos', 'tan', 'sqrt', 'log', 'pi'];
                const uniqueVars = [...new Set(variableMatches)].filter(v => !coreTokensBlacklist.includes(v));

                if (variablesField) {
                    variablesField.value = uniqueVars.join(', ');
                }
            }

            // Only update dropdown layout structure if things like the formula text change
            syncSolveForDropdown();
            refreshUnusedVariablesPicker();

            card.dispatchEvent(new Event('change', { bubbles: true }));
        });

        if (solveMethodSelect) {
            solveMethodSelect.addEventListener('change', () => {
                syncSolveForDropdown();
                card.dispatchEvent(new Event('change', { bubbles: true }));
            });
        }

        // 🎯 FIXED: Bound generic state-change triggers to both active variable drop downs
        [simplifySelect, substitutionSelect].forEach(selectEl => {
            if (selectEl) {
                selectEl.addEventListener('change', () => {
                    card.dispatchEvent(new Event('change', { bubbles: true }));
                });
            }
        });
    }

    // -------------------------------------------------------------
    // LIVE PREVIEW SIMULATION RENDERING ENGINE (DYNAMIC RE-CALCULATION)
    // -------------------------------------------------------------
    function updateWorkspaceSimulationPreview() {
        if (window.isHydratingWorkspace) return; // 🛑 Halt execution during hydration loop
        console.group("%c🖥️ [Canvas Preview] Triggering Markdown Render Pass", "color: #a855f7; font-weight: bold;");
        const renderTarget = document.getElementById('simulation-render-target');
        if (!renderTarget) {
            console.warn("❌ Aborting Canvas update: '#simulation-render-target' element is missing from the layout DOM.");
            console.groupEnd();
            return;
        }

        let canvasContent = workspaceQuillInstance ? workspaceQuillInstance.root.innerHTML.trim() : '';
        console.log("Raw Rich-Text content collected from Quill instance:", canvasContent);

        if (!canvasContent || canvasContent === '<p><br></p>') {
            console.log("Empty or unpopulated canvas content detected. Injecting layout placeholder message.");
            renderTarget.innerHTML = '<p style="color: #94a3b8; font-style: italic; margin: 0;">Interactive layout testing view builds dynamically here...</p>';
            console.groupEnd();
            return;
        }

        if (typeof renderPreviewCanvasMarkup === 'function') {
            console.log("🎯 Dispatched canvas content to downstream static macro replacement layout compiler.");
            renderPreviewCanvasMarkup(canvasContent, renderTarget);
        } else {
            console.warn("❌ Downstream utility token parser 'renderPreviewCanvasMarkup' is not declared on global window namespace.");
        }
        console.groupEnd();
    }

    // 🎯 HELPER SUB-ROUTINE: HANDLES REGEX STRING REPLACEMENT & KATEX PARSING
    function renderPreviewCanvasMarkup(canvasContent, renderTarget) {
        console.group("%c🎨 [MARKUP ENGINE] Executing Patched Regex Text Substitution", "background: #7c3aed; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold;");
        
        const tempContainer = document.createElement('div');
        tempContainer.innerHTML = canvasContent;

        // Strip text-editor formula nodes and transition them into preview layouts
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
        
        // 🎯 FIX 1: Tighten regex to ONLY match escaped token wrappers like &lt;randInt1&gt;
        // This stops the engine from intercepting core layout blocks like <p> or </div>
        const tokenRegex = /&lt;([a-zA-Z0-9_]+)&gt;/g;

        console.log("Processing replacements over working HTML layout strings...");

        let simulatedHtml = workingHtml.replace(tokenRegex, function(match, tokenText) {
            try {
                // Safely isolate the alphanumeric token key identifier reference string
                const cleanToken = tokenText.trim(); 
                let baseArchetypeToken = cleanToken.replace(/\d+$/, ''); 

                // 🔍 DIAGNOSTIC LOG 1: Track what the layout parser is trying to match
                console.group(`🔍 [Canvas Trace] Processing Token Tag: "${match}"`);
                console.log(`Targeting Clean Token Reference: "${cleanToken}"`);

                console.group(`🔍 [Canvas Match Attempt] Token Found in Text: "${match}" (Cleaned: "${cleanToken}")`);
                // 🔍 Print out all component cards currently residing in the DOM to inspect their names
                const availableCards = Array.from(document.querySelectorAll('.workspace-component-card')).map(c => {
                    return {
                        archetype: c.getAttribute('data-token'),
                        indexedTokenAttr: c.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token')
                    };
                });
                console.log("Current layout cards present in DOM tree:", availableCards);

                // Locate the active interactive workspace card row using case-insensitive matching logic
                const card = Array.from(document.querySelectorAll('.workspace-component-card')).find(c => {
                    const delBtn = c.querySelector('.btn-delete-workspace-component');
                    return delBtn && delBtn.getAttribute('data-indexed-token') === cleanToken;
                });

                console.log(`Card resolved matching clean token "${cleanToken}":`, card);

                if (card && card.getAttribute('data-token')) {
                    baseArchetypeToken = card.getAttribute('data-token');
                }

                // Check variable validation token lists or structural layout conditions
                const inDynamicVarsList = dynamicVarsTokens.some(v => v.token === baseArchetypeToken);
                const isFormulaCondition = baseArchetypeToken === 'formula';
                
                // If it looks like a known archetype, treat it as a variable processing path
                const isVar = inDynamicVarsList || isFormulaCondition || ['randInt', 'rand', 'primeFactors'].includes(baseArchetypeToken);

                if (isVar) {
                    let displayVal = formulaLiveLatexCache[cleanToken];

                    // 🎯 FIX 2: Defend against server stomping mathematical values into "0" or "???"
                    const isServerValueValid = displayVal !== undefined && displayVal !== null && displayVal !== '' && displayVal !== '0' && displayVal !== '???';

                    if (baseArchetypeToken === 'formula') {
                        if (!isServerValueValid && card) {
                            displayVal = card.getAttribute('data-simulated-value') || cleanToken;
                        }
                    } else {
                        // FORCE math generators (rand, randInt, primeFactors) to compute purely client-side
                        if (card) {
                            console.log(`Bypassing server cache value ("${displayVal}") for math generator variable type. Firing live local client evaluation pass.`);
                            
                            console.log(`📊 [Canvas Render Check] Checking Card state before evaluation:`, {
                                token: cleanToken,
                                dataToken: card.getAttribute('data-token'),
                                shuffleSeed: card.getAttribute('data-shuffle-seed'),
                                currentMinInput: card.querySelector('.val-input-min')?.value,
                                currentMaxInput: card.querySelector('.val-input-max')?.value,
                                currentNumberInput: card.querySelector('.val-input-number')?.value,
                                wrapperBoundToken: card.querySelector('.linked-input-wrapper')?.getAttribute('data-bound-token')
                            });
                            displayVal = evaluateSingleCardOutput(card, cleanToken);
                        } else {
                            // 🔍 ADD THIS WARNING HERE:
                            console.warn(`⚠️ [Canvas Render Warning] Token "${cleanToken}" matched a known archetype list, but its workspace card DOM node could not be found on the page.`);
                        }
                    }

                    // Strict validation fallback loop parameter checks
                    if (!displayVal || displayVal === '???') {
                        displayVal = cleanToken;
                    }

                    console.log(`%c✔ Render Success -> Target Replacement: "${match}" -> Computed Result Value: "${displayVal}"`, "color: #16a34a; font-weight: bold;");
                    console.groupEnd();

                    if (baseArchetypeToken === 'formula') {
                        return `<span class="simulated-math-formula-render" style="display: inline-block; padding: 2px 4px;">${displayVal}</span>`;
                    }
                    return `<span class="simulated-math-variable-badge" style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.9rem; display: inline-block; margin: 0 2px;">${displayVal}</span>`;
                
                } else if (answerFieldsTokens.some(i => i.token === baseArchetypeToken)) {
                    console.groupEnd();
                    return `
                        <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px;">
                            <input type="text" placeholder="Input slot..." disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; width: 140px;">
                        </div>
                    `;
                }
                
                console.groupEnd();
                return match;
            } catch (err) {
                console.error(`Token regex processing failed for element token chunk ${match}:`, err);
                console.groupEnd();
                return `<span style="color: red; font-family: monospace;">[Token Error]</span>`;
            }
        });

        renderTarget.innerHTML = simulatedHtml;

        // 🎯 STEP 3: RUN KATEX DISPATCH OVER DYNAMIC HTML TARGETS
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
        console.groupEnd();
    }

    // Serializes active layout properties into structural object dictionaries matching database specifications
    function serializeAllWorkspaceEntities() {
        const entities = [];
        document.querySelectorAll('.workspace-block-card').forEach(card => {
            const delBtn = card.querySelector('.btn-delete-workspace-component');
            const token = delBtn ? delBtn.getAttribute('data-indexed-token') : null;
            if (!token) return;

            console.log(`Payload Pack -> Token: ${token}, Value: ${card.getAttribute('data-simulated-value')}`);

            // 🎯 Determine base archetype and correct case-matching for database key lookups
            let baseArchetypeToken = token.replace(/[0-9]/g, '');

            // 🎯 Dynamic Lookup from your database blueprints global map
            const databaseBlueprints = window.DATABASE_BLUEPRINTS || {};
            const matchedBlueprint = databaseBlueprints[baseArchetypeToken] || {};
            const blueprintInputsSchema = matchedBlueprint.inputs || {};

            const inputsCollected = {};

            // 1. Seed base default blueprint schemas keys from database patterns
            Object.entries(blueprintInputsSchema).forEach(([inputKey, schemaConfig]) => {
                if (schemaConfig && schemaConfig.default !== undefined) {
                    inputsCollected[inputKey] = schemaConfig.default;
                } else {
                    inputsCollected[inputKey] = "";
                }
            });

            // 2. UNIVERSAL FIELD EXTRACTOR: Look through wrapper elements for user selections or linked macro pills
            card.querySelectorAll('.linked-input-wrapper').forEach(wrapper => {
                const key = wrapper.getAttribute('data-input-key');
                if (!key || key.startsWith('sub_')) return;

                // Priority A: Check if an active macro token is linked to this input
                const boundToken = wrapper.getAttribute('data-bound-token');
                const tokenPill = wrapper.querySelector('.linked-token-pill');
                
                if (boundToken) {
                    // 🎯 FIX 1: Unescape HTML entity characters (&lt; and &gt;) to literal raw angle brackets
                    let cleanToken = boundToken.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
                    if (!cleanToken.startsWith('<')) cleanToken = `<${cleanToken}`;
                    if (!cleanToken.endsWith('>')) cleanToken = `${cleanToken}>`;
                    inputsCollected[key] = cleanToken;
                } else if (tokenPill) {
                    // Fallback visual token identifier reader extraction path
                    const rawPillId = tokenPill.getAttribute('data-indexed-token') || tokenPill.textContent || "";
                    let cleanPill = rawPillId.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
                    cleanPill = cleanPill.replace(/[<>]/g, ''); // Strip existing brackets for uniform re-wrapping
                    inputsCollected[key] = cleanPill ? `<${cleanPill}>` : "";
                } else {
                    // Priority B: Fallback cleanly to reading the standard text/numeric/dropdown value
                    const nativeField = wrapper.querySelector('input, select, textarea');
                    if (nativeField) {
                        inputsCollected[key] = nativeField.value.trim();
                    }
                }
            });

            // 3. ARCHETYPE SPECIFIC OVERRIDES: Apply specialized structure extensions ONLY to formula types
            if (baseArchetypeToken === 'formula') {
                const solveMethod = card.querySelector('.val-input-solve-method')?.value || "leave as formula";
                inputsCollected["solve method"] = solveMethod;
                
                // 🎯 FORCE LIVE VALUE EVALUATION VIA COMBINED SELECTORS
                const simplifySelect = card.querySelector('.val-input-simplify-target');
                const substitutionSelect = card.querySelector('.val-input-substitution-target');

                // Read values directly using indexed selections to bypass timing delays
                const simplifyVal = simplifySelect && simplifySelect.selectedIndex >= 0 ? 
                                    simplifySelect.options[simplifySelect.selectedIndex].value : "";
                                    
                const substitutionVal = substitutionSelect && substitutionSelect.selectedIndex >= 0 ? 
                                        substitutionSelect.options[substitutionSelect.selectedIndex].value : "";

                // 🎯 Explicitly save these back to the payload keys
                inputsCollected["variable to simplify"] = simplifyVal;
                inputsCollected["variable to substitute"] = substitutionVal;

                // 🎯 Unify the active value under a single backend variable namespace for Python processing
                const chosenTarget = (solveMethod === 'simplify') ? simplifyVal : ((solveMethod === 'variable substitution') ? substitutionVal : "");
                inputsCollected["variable substitution"] = chosenTarget;
                inputsCollected["variable to solve for"] = chosenTarget;

                // Build sub-entries list for assignments mapping
                const substitutions = {};
                const subsContainer = card.querySelector('.substitutions-list-container');
                if (subsContainer && solveMethod === 'variable substitution') {
                    subsContainer.querySelectorAll('.substitution-row-item').forEach(row => {
                        const vName = row.getAttribute('data-var-name');
                        if (!vName) return;

                        // Locate the wrapper element holding the states
                        const inputWrapper = row.querySelector('.linked-input-wrapper');
                        const tokenPill = inputWrapper ? inputWrapper.querySelector('.linked-token-pill') : null;
                        const nativeInput = inputWrapper ? inputWrapper.querySelector('input') : null;

                        let rawTokenValue = "";
                        let isLinkedToken = false; // 🎯 TRACK ORIGIN

                        if (inputWrapper && inputWrapper.hasAttribute('data-bound-token')) {
                            rawTokenValue = inputWrapper.getAttribute('data-bound-token');
                            isLinkedToken = true;
                        } else if (tokenPill) {
                            rawTokenValue = tokenPill.getAttribute('data-indexed-token') || tokenPill.textContent;
                            isLinkedToken = true;
                        } else if (nativeInput) {
                            rawTokenValue = nativeInput.value;
                            isLinkedToken = false; // Value came from manual user typing
                        }

                        // Clean up formatting
                        if (rawTokenValue && rawTokenValue.trim() !== "") {
                            let cleanString = rawTokenValue.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
                            cleanString = cleanString.replace(/[<>]/g, ''); 
                            
                            // 🎯 FIX: Only wrap if it's a known structural link, OR if the raw text matches a token format (e.g. formula1, rand3)
                            const looksLikeToken = /^[a-zA-Z]+\d+$/.test(cleanString);
                            
                            if (isLinkedToken || looksLikeToken) {
                                substitutions[vName] = `<${cleanString}>`;
                            } else {
                                substitutions[vName] = cleanString; // ✅ Keeps raw inputs like "6" or "5*y" clean!
                            }
                        } else {
                            substitutions[vName] = "";
                        }
                    });
                }
                inputsCollected["substitutions"] = substitutions;

                console.log("Cleaned substitutions mapping payload: ", inputsCollected["substitutions"]);
            }

            // 🎯 NEW CACHE LOCK BREAKER: Check if the user is actively editing this card
            let finalSimulatedValue = card.getAttribute('data-simulated-value');
            const activeElement = document.activeElement;
            const isCardBeingEdited = activeElement && card.contains(activeElement);

            if (isCardBeingEdited) {
                console.log(`🧼 [Serializer] Active input edit caught on [${token}]. Clearing simulated_value payload to force backend re-roll.`);
                finalSimulatedValue = null;
            }

            // 🎯 FIXED: Restructure output model parameters to mirror Python context lookup keys
            entities.push({
                token: baseArchetypeToken,      // e.g. "randInt"
                sequence_token: token,          // e.g. "randInt2"
                inputs: inputsCollected,
                simulated_value: finalSimulatedValue // ✅ Sends null when actively typed in
            });
        });
        
        return entities;
    }

    // Client-Side DAG: Filters list down to an entity, its descendants, AND its required ancestors
    function getDownstreamDependencies(allEntities, editedToken) {
        // Formulate the structured fallback object on initial cold-boots!
        if (!editedToken || editedToken === 'initial_load') {
            return {
                familyGroup: allEntities, // Everything is context on load
                mutationTargets: allEntities.map(e => e.indexed_token || e.sequence_token || e.token) // Everything evaluates on load
            };
        }

        // 1. Build a map of immediate dependencies (who relies on whom) using UNIQUE IDs
        const parentToChildrenMap = {};
        const childToParentsMap = {};
        
        allEntities.forEach(e => { 
            // 🎯 FIX: Map keys must use the unique instance ID (e.g., 'randInt1') instead of archetype ('randInt')
            const uniqueKey = e.indexed_token || e.sequence_token || e.token;
            parentToChildrenMap[uniqueKey] = []; 
            childToParentsMap[uniqueKey] = [];
        });

        allEntities.forEach(e => {
            // 🎯 FIX: Track current component by its unique instance ID
            const currentToken = e.indexed_token || e.sequence_token || e.token;
            
            // Scan ALL values inside the inputs dictionary (handles fields like min, max, value, formula)
            const inputStrings = [];
            Object.values(e.inputs || {}).forEach(val => {
                if (typeof val === 'string') {
                    inputStrings.push(val);
                } else if (typeof val === 'object' && val !== null) {
                    // Extract deeply nested objects like inputs.substitutions row mappings
                    inputStrings.push(JSON.stringify(val));
                }
            });
            
            const combinedInputText = inputStrings.join(' ');

            // Universal regex matching any token tags (e.g., <randInt1>, formula2, primeFactors3)
            const regex = /(?:<([a-zA-Z0-9_]+)>)|([a-zA-Z]+)(\d+)/gi;
            let match;
            const combinedMatches = [];

            while ((match = regex.exec(combinedInputText)) !== null) {
                if (match[1]) {
                    combinedMatches.push(match[1]);
                } else {
                    combinedMatches.push((match[2] + match[3]));
                }
            }
            
            // Filter unique entries to eliminate redundant tree crawls
            const uniqueDeps = [...new Set(combinedMatches)];

            uniqueDeps.forEach(parentDep => {
                // Now this lookup succeeds perfectly because keys like 'randInt1' are registered!
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
        const affected = new Set([editedToken]);

        // 3. Trace DOWNSTREAM (Descendants who need recalculation)
        const downstreamQueue = [editedToken];
        while (downstreamQueue.length > 0) {
            const current = downstreamQueue.shift();
            (parentToChildrenMap[current] || []).forEach(child => {
                if (!affected.has(child)) {
                    affected.add(child);
                    downstreamQueue.push(child);
                }
            });
        }

        // 🎯 NEW: Create a separate set to track ONLY the token itself and its descendants
        const downstreamOnly = new Set([editedToken]);
        const downQueue = [editedToken];
        while (downQueue.length > 0) {
            const current = downQueue.shift();
            (parentToChildrenMap[current] || []).forEach(child => {
                if (!downstreamOnly.has(child)) {
                    downstreamOnly.add(child);
                    downQueue.push(child);
                }
            });
        }

        // 4. Trace UPSTREAM (Ancestors needed by the backend to resolve math strings)
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

        // 5. Build and return the updated structured object payload instead of a plain array
        const familyGroup = allEntities.filter(e => {
            const uniqueKey = e.indexed_token || e.sequence_token || e.token;
            return affected.has(uniqueKey);
        });

        const mutationTargets = allEntities
            .map(e => e.indexed_token || e.sequence_token || e.token)
            .filter(key => downstreamOnly.has(key));

        return {
            familyGroup: familyGroup,
            mutationTargets: mutationTargets
        };
    }


    function dispatchWorkspaceBatchSync(triggeringToken = null, options = {}) {
        console.group(`%c🛰️ [Network Batch Dispatch] Initiating Dependency Evaluation Request`, "background: #2563eb; color: white; padding: 3px 6px; border-radius: 4px; font-weight: bold;");
        
        if (isWorkspaceInitializing && triggeringToken !== 'initial_load') {
            console.warn(`🛑 Sync Blocked: Workspace initialization latch is active. Suppressed single card refresh for token: [${triggeringToken}]`);
            console.groupEnd();
            return;
        }
        
        console.log(`Step 1: Parsing workspace layout tree components...`);
        const allEntities = serializeAllWorkspaceEntities();
        console.log("Total active workspace elements found:", allEntities);

        // 🎯 FIX: Destructure the new object format returned by the updated DAG engine
        const dependencyData = getDownstreamDependencies(allEntities, triggeringToken);
        const affectedEntities = dependencyData.familyGroup; // Contains full tree context (Ancestors + Descendants)
        const mutationTargets = dependencyData.mutationTargets; // Contains ONLY trigger + Descendants
        
        console.log(`Post refresh token name: ${triggeringToken}`);
        console.log(`Step 2: Tracking dependencies affected by event driver [${triggeringToken || 'initial_load'}]:`, affectedEntities);
        console.log(`Execution path (Mutation Targets):`, mutationTargets);

        // Check against the familyGroup array length to see if anything was matched
        if (affectedEntities.length === 0 && !options.forceRefresh) {
            console.log(`triggeringToken: ${triggeringToken}`);
            console.warn("⚠️ No relevant components matched tree criteria. Network communication suppressed.");
            console.groupEnd();
            return;
        }
        console.log("🚀 Syncing components:", affectedEntities);

        const currentTimestamp = Date.now();
        activeBatchSyncTimestamp = currentTimestamp;
        console.log(`Step 3: Stamping outgoing request token signature timestamp: ${currentTimestamp}`);

        fetch('/assessment/api/validate-component-preview/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({
                trigger_token: triggeringToken,
                entities: affectedEntities,    // Context validation ledger (unchanged variable name)
                mutation_targets: mutationTargets // Explicitly tell the backend what to calculate
            })
        })
        .then(res => {
            console.log(`📡 Server Connection Made! HTTP Response Code status returned: ${res.status}`);
            return res.json();
        })
        .then(data => {
            console.group(`%c📥 [Network Sync Response Received]`, "background: #059669; color: white; padding: 2px 6px; border-radius: 4px;");
            console.log("Server payload returned object data:", data);

            const errorBanner = document.getElementById('workspace-validation-error-banner');
            const errorsList = document.getElementById('workspace-validation-errors-list');
            
            // Clear out any old lingering feedback items
            errorsList.innerHTML = '';
            
            // Check if errors exist in the payload object
            if (data.errors && Object.keys(data.errors).length > 0) {
                errorBanner.style.display = 'flex'; // Unhide banner block
                
                // Loop through each component variable signature (e.g., 'rand1')
                Object.entries(data.errors).forEach(([tokenKey, fieldErrors]) => {
                    // Loop through individual field failures on that component card
                    Object.entries(fieldErrors).forEach(([fieldKey, errorMessage]) => {
                        const errorItem = document.createElement('div');
                        errorItem.style.display = 'flex';
                        errorItem.style.gap = '6px';
                        errorItem.style.marginBottom = '2px';
                        errorItem.innerHTML = `
                            <span style="color: #ef4444; font-weight: 700;">[${tokenKey} ➔ ${fieldKey.toUpperCase()}]:</span>
                            <span style="color: #b91c1c;">${errorMessage}</span>
                        `;
                        errorsList.appendChild(errorItem);
                    });
                });
            } else {
                // Safe transaction state reached: keep banner cleanly hidden away
                errorBanner.style.display = 'none';
            }

            // 🎯 RACE CONDITION GUARD
            if (currentTimestamp !== activeBatchSyncTimestamp) {
                console.warn(`⏳ Stale response detected! Current global lock index is [${activeBatchSyncTimestamp}] but this network request returned from index [${currentTimestamp}]. Dropping updates to prevent screen stutters.`);
                console.groupEnd();
                console.groupEnd();
                return;
            }

            if (!data.success) {
                console.error("❌ Math Validation Engine reported system operational failures:", data.error);
                console.groupEnd();
                console.groupEnd();
                return;
            }

            console.group("🔄 Applying Engine Values to DOM Component Nodes");
            Object.keys(data.updated_cache).forEach(token => {
                const result = data.updated_cache[token];
                
                console.group(`📝 Mutating Layout States For Element Card Reference Key: [${token}]`);
                console.log(`Assigned values received: Evaluated String='${result.evaluated_output}', LaTeX Output='${result.latex_output}', Free Variables='${result.extracted_variables}'`);

                formulaLiveLatexCache[token] = result.latex_output;
                
                const card = Array.from(document.querySelectorAll('.workspace-block-card')).find(c => 
                    c.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token') === token
                );
                
                if (!card) {
                    console.warn(`❌ DOM Mismatch: Unable to locate any visible block card with custom query token ID selector: [${token}]`);
                    console.groupEnd();
                    return;
                }

                card.setAttribute('data-simulated-value', result.evaluated_output);
                console.log(`Updated wrapper tracking parameter attribute 'data-simulated-value' ➔ '${result.evaluated_output}'`);

                const baseArchetype = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-token');
                let targetDisplay = card.querySelector('.latex-render-box');
                console.log(`Determined operational asset token archetype model: '${baseArchetype}'`);

                if (baseArchetype === 'primeFactors' || baseArchetype === 'formula') {
                    if (!targetDisplay) {
                        const fieldsWrapper = card.querySelector('.component-fields-wrapper');
                        if (fieldsWrapper) {
                            targetDisplay = document.createElement('div');
                            targetDisplay.className = 'latex-render-box';
                            targetDisplay.style.cssText = 'margin-top: 8px; padding: 6px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; min-height: 24px; font-size: 0.9rem; text-align: center;';
                            fieldsWrapper.appendChild(targetDisplay);
                        }
                    }
                }
                if (baseArchetype === 'formula') {
                    if (targetDisplay && typeof katex !== 'undefined') {
                        katex.render(result.latex_output, targetDisplay, { throwOnError: false });
                    } else if (typeof katex === 'undefined') {
                        console.error("❌ KaTeX script dependencies are not present on page framework view layout.");
                    }
                } else {
                    if (targetDisplay) {
                        targetDisplay.textContent = result.evaluated_output;
                    }
                }

                // 🔍 DEBUG LOG: Look for select elements inside the card to verify their class names
                const allSelectsOnCard = Array.from(card.querySelectorAll('select')).map(s => ({ className: s.className, name: s.name, value: s.value }));
                console.log("🔍 [DEBUG] Dropdowns currently existing on this component card:", allSelectsOnCard);

                const varsInput = card.querySelector('.val-input-variables');
                if (varsInput && result.extracted_variables !== undefined) {
                    varsInput.value = result.extracted_variables;
                }

                const varArray = result.extracted_variables
                    ? result.extracted_variables.split(',').map(v => v.trim()).filter(v => v.length > 0).sort()
                    : [];

                const unusedVariablesPicker = card.querySelector('.picker-unused-variables');
                if (unusedVariablesPicker) {
                    const currentlyAssignedVars = Array.from(card.querySelectorAll('.substitutions-list-container .substitution-row-item'))
                        .map(row => row.getAttribute('data-var-name'));

                    const unusedVars = varArray.filter(v => !currentlyAssignedVars.includes(v));

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

                // 🎯 FIXED DROPDOWN TRACK OVERRIDE
                const solveForSelect = card.querySelector('.val-input-simplify-target');
                if (solveForSelect) {
                    const methodSelect = card.querySelector('.val-input-solve-method');
                    const activeMethod = methodSelect ? methodSelect.value : "";
                    const simplifyDropdownContainer = solveForSelect.closest('.form-group, .input-row, div');

                    // If the card is configured for variable substitution, hide this element wrapper row out of view
                    if (activeMethod != 'simplify') {
                        if (simplifyDropdownContainer) {
                            simplifyDropdownContainer.style.display = 'none';
                        }
                    } else {
                        if (simplifyDropdownContainer) {
                            simplifyDropdownContainer.style.display = '';
                        }

                        const currentSelection = card.getAttribute('data-selected-variable') || solveForSelect.value || "";
                        const existingDropdownOptions = Array.from(solveForSelect.options)
                            .map(opt => opt.value.trim())
                            .filter(val => val.length > 0)
                            .sort();

                        const dropdownOptionsStructurallyChanged = 
                            varArray.length !== existingDropdownOptions.length || 
                            !varArray.every((v, i) => v === existingDropdownOptions[i]);

                        if (dropdownOptionsStructurallyChanged) {
                            console.log(`🔄 Variable list updates match structural changes. Rebuilding options list...`);
                            
                            solveForSelect.options.length = 0;
                            
                            const defaultOpt = document.createElement('option');
                            defaultOpt.value = "";
                            defaultOpt.textContent = "-- select variable --";
                            solveForSelect.appendChild(defaultOpt);
                            
                            varArray.forEach(v => {
                                const opt = document.createElement('option');
                                opt.value = v;
                                opt.textContent = v;
                                solveForSelect.appendChild(opt);
                            });
                        }
                        
                        // 🎯 --- SELECTION RESOLUTION PIPELINE ---
                        if (currentSelection && varArray.includes(currentSelection)) {
                            solveForSelect.value = currentSelection;
                        } else {
                            solveForSelect.value = '';
                            card.removeAttribute('data-selected-variable');
                        }
                    }
                }
                
                console.groupEnd();
            });

            console.groupEnd(); // End variable parsing loop

            console.log("⚡ View components re-indexed. Re-triggering canvas preview compilation pipeline update passes.");
            updateWorkspaceSimulationPreview();
            console.groupEnd(); // End Main success trace block
            console.groupEnd(); // End Fetch top-level engine block
        })
        .catch(err => {
            console.error("❌ Consolidated batch synchronization network connection dispatch crashed entirely:", err);
            console.groupEnd();
        });
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

            // Clear the simulation cache for this specific card
            // If you have a data-simulated-value attribute, wipe it so the engine is forced to re-calculate
            cardElement.removeAttribute('data-simulated-value');

            // 🎯 UPDATE: Pull the token ID of this specific card to recalculate its dependencies
            const cardTokenId = cardElement.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');

            if (typeof dispatchWorkspaceBatchSync === 'function' && cardTokenId) {
                dispatchWorkspaceBatchSync(cardTokenId, { forceRefresh: true });
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

            // 🎯 STEP 2 FIX: Hydrate the unified frontend blueprint map straight from the AJAX payload
            window.DATABASE_BLUEPRINTS = {};
            const combinedOptions = [
                ...(data.dynamic_variables_options || []),
                ...(data.answer_fields_options || [])
            ];
            
            combinedOptions.forEach(opt => {
                if (opt.token) {
                    window.DATABASE_BLUEPRINTS[opt.token] = {
                        name: opt.name,
                        inputs: opt.inputs || {} // Captures the blueprint inputs dictionary you added in Django
                    };
                }
            });
            // console.log("🛠️ [WORKSPACE] Database entity type blueprints successfully hydrated:", window.DATABASE_BLUEPRINTS);

            // 🎯 CORRECTED FIX: Explicitly target your actual wrapper line element ID
            if (tokensLedger) {
                // console.log("🧼 Flushing stale visual tokens from the ledger wrapper...");
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
            // console.log("Save button clicked. Building workspace configuration payload...");
            
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
                const baseToken = card.getAttribute('data-token');
                if (!baseToken) return;

                const shuffleSeedValue = card.getAttribute('data-shuffle-seed') || '';
                const deleteBtn = card.querySelector('.btn-delete-workspace-component');
                const indexedTokenString = deleteBtn ? deleteBtn.getAttribute('data-indexed-token') : baseToken;

                const inputValues = {};

                // 1. EXTRACTION: Explicitly pull dropdowns first
                const solveMethodSelect = card.querySelector('.val-input-solve-method');
                if (solveMethodSelect) {
                    inputValues['solve method'] = solveMethodSelect.value.trim();
                }

                if (baseToken === 'formula') {
                    const solveForSelect = card.querySelector('.val-input-simplify-target');
                    // Ensure the key exists even if empty to maintain database schema consistency
                    inputValues['variable to solve for'] = solveForSelect ? solveForSelect.value.trim() : '';
                }

                // 2. EXTRACTION: Standard Wrapper-based inputs
                const inputWrappers = card.querySelectorAll('.linked-input-wrapper:not(.row-variable-substitutions .linked-input-wrapper)');
                inputWrappers.forEach(wrapper => {
                    const inputKey = wrapper.getAttribute('data-input-key');
                    const boundToken = wrapper.getAttribute('data-bound-token');
                    
                    if (boundToken) {
                        inputValues[inputKey] = boundToken;
                    } else {
                        const interactiveField = wrapper.querySelector('input, select');
                        // Exclude inputs that are part of the 'solve-for' dropdown already captured above
                        if (interactiveField && !interactiveField.classList.contains('val-input-simplify-target')) {
                            inputValues[inputKey] = interactiveField.value.trim();
                        }
                    }
                });

                // 3. EXTRACTION: Dynamic Substitution rows
                if (baseToken === 'formula') {
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

                // Debug log to confirm what is actually getting pushed to the server
                // console.log(`Final payload for [${indexedTokenString}]:`, inputValues);

                inputsPayloadList.push({
                    token: baseToken,
                    sequence_token: indexedTokenString,
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
                    // console.log("Database transaction complete:", result.message);
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
                    // console.log(`🧼 Token unlink action cleared on [${cardId}]. Packaging updated graph topology...`);
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
        
        // console.log(`\n--- 🏁 Linker Diagnostics Started ---`);
        // console.log(`Target Input Key: "${wrapper.getAttribute('data-input-key')}"`);
        // console.log(`Target Raw Type Attribute: "${targetTypeAttr}"`);

        // 🎯 1. Normalize the field's accepted types into an array.
        let acceptedTargetTypes = [targetTypeAttr];
        if (targetTypeAttr === 'double') {
            acceptedTargetTypes.push('integer');
        }
        // console.log(`Normalized Accepted Types Array:`, acceptedTargetTypes);
        // console.log(`Global Database Registry (dynamicVarsTokens):`, dynamicVarsTokens);

        let availableOptionsHtml = '';
        
        activeCards.forEach(card => {
            // Prevent linking a card back into itself
            if (card === currentCard) return;

            const deleteBtn = card.querySelector('.btn-delete-workspace-component');
            if (!deleteBtn) return;

            const indexedToken = deleteBtn.getAttribute('data-indexed-token'); // e.g., "randInt2"
            const baseArchetype = card.getAttribute('data-token');             // e.g., "rand"

            // console.log(`\nEvaluating Sidebar Option Card -> [${indexedToken}] (Archetype: "${baseArchetype}")`);

            // 🎯 2. LOOK UP DATA DIRECTLY FROM YOUR ENTITY_TYPE DATABASE LEDGER
            const tokenDefinition = dynamicVarsTokens.find(t => t.token === baseArchetype);
            
            if (!tokenDefinition) {
                console.error(`❌ DATABASE MISMATCH: No token schema configuration row found matching archetype: "${baseArchetype}" in dynamicVarsTokens ledger.`);
                return;
            }
            
            // console.log(`Found Registry Schema Definition for "${baseArchetype}":`, tokenDefinition);

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
            
            // console.log(`Normalized Token Source Outputs:`, derivedOutputs);

            // Check if the input key is a template substitution row
            const inputKey = wrapper.getAttribute('data-input-key') || '';
            
            // 🎯 3. Determine compatibility dynamically via array intersection (.some)
            let isCompatible = derivedOutputs.some(type => acceptedTargetTypes.includes(type));
            // console.log(`Intersection Type Match Result (derivedOutputs vs acceptedTargetTypes): ${isCompatible}`);

            // FORCE COMPATIBILITY OVERRIDE: permit substitution inputs to couple with double, integer, or formula tokens
            if (inputKey.startsWith('sub_')) {
                const isSubCompatible = derivedOutputs.some(type => ['double', 'integer', 'formula'].includes(type));
                isCompatible = isSubCompatible;
            }

            if (isCompatible) {
                // console.log(`✅ MATCH SUCCESS: Adding <${indexedToken}> into dropdown list.`);
                availableOptionsHtml += `
                    <button type="button" class="select-link-token-option" data-target-token="&lt;${indexedToken}&gt;" style="width: 100%; text-align: left; padding: 6px 12px; background: none; border: none; font-size: 0.75rem; cursor: pointer; transition: background 0.15s; color: #334155;">
                        &lt;${indexedToken}&gt;
                    </button>
                `;
            } else {
                // console.log(`🚫 MATCH FAILED: <${indexedToken}> is incompatible with fields requiring ${targetTypeAttr}.`);
            }
        });

        // console.log(`\n--- 🏁 Linker Diagnostics Complete. Total generated choices: ${availableOptionsHtml ? 'Options Present' : 'Zero Options Found'} ---`);

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
                // console.log(`🔗 Token dependency linkage created on [${cardId}]. Syncing network compilation tree...`);
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
            
            if (!target.matches('input, select, textarea')) return;

            const card = target.closest('.workspace-component-card') || target.closest('.workspace-block-card');
            if (!card) return;

            const cardId = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
            if (!cardId) return;

            console.group(`%c⚡ Input Activity Hooked [Event Type: '${e.type}'] on Token identifier [${cardId}]`, "color: #eab308; font-weight: bold;");
            // console.log(`DOM Trigger Intercepted input element node reference:`, target);
            // console.log(`Active field input field payload name value: '${target.name || target.className}' ➔ String Content value inputted: '${target.value}'`);

            if (debouncedNetworkDispatches[cardId]) {
                // console.log(`⏳ Debounce intercept: Overriding pending network countdown reference matching index context for [${cardId}]. Resetting timeout interval limits.`);
                clearTimeout(debouncedNetworkDispatches[cardId]);
            }

            debouncedNetworkDispatches[cardId] = setTimeout(() => {
                delete debouncedNetworkDispatches[cardId];

                console.group(`%c🚀 Debounce Interval Trigger Window Closed ➔ Dispatching [${cardId}]`, "background: #10b981; color: white; padding: 2px 6px; border-radius: 4px; font-weight: bold;");
                // console.log("Current targeting element select dropdown value node tracking before network handshake:", card.querySelector('.val-input-simplify-target')?.value);
                console.groupEnd();

                if (typeof dispatchWorkspaceBatchSync === 'function') {
                    dispatchWorkspaceBatchSync(cardId);
                } else {
                    updateWorkspaceSimulationPreview();
                }
            }, 400);
            console.groupEnd();
        }

        document.addEventListener('input', triggerLiveSync);
        document.addEventListener('change', triggerLiveSync);
    })();

});