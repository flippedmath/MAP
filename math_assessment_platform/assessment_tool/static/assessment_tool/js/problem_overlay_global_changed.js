// 1. Define the supported entity type list
const SUPPORTED_ENTITIES = [
    'randInt',
    'rand', 
    'primeFactors',
    'formula',
    'matrix',
    'graph'
];

/**
 * Processes a token by dynamically loading its respective Javascript file.
 * 
 * @param {string} token - The token string (e.g., 'matrix', 'rand')
 * @param {Object} contextData - Any data the entity file needs to do its job
 */
async function getEntityInformation(token, contextData) {
    // 2. Check if the token exists in our supported list
    if (!SUPPORTED_ENTITIES.includes(token)) {
        console.warn(`Token "${token}" is not a recognized entity type.`);
        return null;
    }

    try {
        // 3. Dynamically import the respective entity javascript file
        // Note: Adjust the relative path depending on your project structure
        const entityModule = await import(`./entities/${token}.js`);
        
        // 4. Call the standardized function to obtain the required information
        const entityData = await entityModule.processEntity(contextData);
        
        return entityData;

    } catch (error) {
        console.error(`Failed to load or execute entity file for token: ${token}`, error);
        return null;
    }
}

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
                removePlaceholders(targetContainer);
                createTokenBadge(tokenSelected);
                createNewBlockInstanceUI(tokenSelected, targetContainer, {});
                
                const builtCards = targetContainer.querySelectorAll('.workspace-block-card');
                const newestCard = builtCards[builtCards.length - 1];
                const cardTokenId = newestCard?.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');

                if (typeof dispatchWorkspaceBatchSync === 'function' && cardTokenId) {
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
            // Differentiate missing data from an empty new workspace
            if (!segments) {
                console.warn("⚠️ Database segment array payload is missing from network packet.");
                clearAndShowPlaceholders();
                return;
            }

            if (segments.length === 0) {
                console.log("ℹ️ Workspace payload is empty. Preparing pristine workspace layout states.");
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
                const latestCard = createNewBlockInstanceUI(segment.token, targetContainer, segment.inputs, segment.points, savedSequenceToken);
            
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
                return fallback; 
            }
            return val ?? fallback;
        };

        let fieldsHtml = '';

        // 🎯 NEW ARCHITECTURE: DELEGATE HTML RENDERING TO SUB-ENTITY SCRIPTS IF LOADED
        if (window.SubEntityHandlers && window.SubEntityHandlers[token] && typeof window.SubEntityHandlers[token].getFieldsHtml === 'function') {
            fieldsHtml = window.SubEntityHandlers[token].getFieldsHtml(savedValues, safeNumValue, indexedTokenString);
        }
        // Add new entity Step 1: if new fields exist, then add the html here for the new entity
        else if (token === 'randInt') {
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
        } else if (token === 'formula') {
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
        } else if (token === 'graph') {
            const initialFormulas = Array.isArray(savedValues.formulas) ? savedValues.formulas : (savedValues.formulas ? [savedValues.formulas] : ['']);
            const showGridChecked = savedValues.show_grid !== false;

            const legacyX = savedValues['x-axis range'] || [];
            const xMinVal = savedValues['x_min'] !== undefined ? savedValues['x_min'] : (legacyX[0] !== undefined ? legacyX[0] : '');
            const xMaxVal = savedValues['x_max'] !== undefined ? savedValues['x_max'] : (legacyX[1] !== undefined ? legacyX[1] : '');
            const xStepVal = savedValues['x_step'] !== undefined ? savedValues['x_step'] : (legacyX[2] !== undefined ? legacyX[2] : '');

            const legacyY = savedValues['y-axis range'] || [];
            const yMinVal = savedValues['y_min'] !== undefined ? savedValues['y_min'] : (legacyY[0] !== undefined ? legacyY[0] : '');
            const yMaxVal = savedValues['y_max'] !== undefined ? savedValues['y_max'] : (legacyY[1] !== undefined ? legacyY[1] : '');
            const yStepVal = savedValues['y_step'] !== undefined ? savedValues['y_step'] : (legacyY[2] !== undefined ? legacyY[2] : '');

            fieldsHtml = `
                <div style="display: flex; flex-direction: column; gap: 8px; width: 100%;">
                    <!-- Dynamic List of Formula Inputs -->
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
                        <!-- Hidden variable input ensures serialization script keeps working out of view -->
                        <input type="hidden" class="val-graph-variables" value="${savedValues.variables || 'x,y'}">
                        
                        <div style="display: flex; align-items: center; padding: 6px 0;">
                            <label style="font-size: 0.75rem; color: #475569; display: flex; align-items: center; gap: 6px; cursor: pointer;">
                                <input type="checkbox" class="val-graph-show-grid" ${showGridChecked ? 'checked' : ''} style="cursor: pointer;"> Visualize Grid Layout
                            </label>
                        </div>
                    </div>

                    <!-- Configurable Bounds Ranges -->
                    <div style="display: flex; flex-direction: column; gap: 4px; border-top: 1px dashed #cbd5e1; padding-top: 6px; margin-top: 4px;">
                        <span style="font-size: 0.72rem; font-weight: 600; color: #64748b;">Axis Limits Configuration (Leave empty to Auto-Calculate):</span>
                        
                        <!-- X Axis Bounds -->
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

                        <!-- Y Axis Bounds -->
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
        } else if (token === 'matrix') {
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

            fieldsHtml = `
                <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">
                    
                    <!-- Matrix Source Override Selector -->
                    <div class="linked-input-wrapper" data-input-key="linked_matrix" data-input-type="matrix" style="position: relative; display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; box-sizing: border-box; background: #f1f5f9; padding: 6px 8px; border-radius: 4px; border: 1px dashed #cbd5e1;">
                        <div style="display: flex; flex-direction: column; min-width: 0; flex-grow: 1;">
                            <span style="font-size: 0.75rem; font-weight: 600; color: #334155;">Link Source Matrix Override</span>
                            <span class="link-status-text" style="font-size: 0.75rem; color: ${isLinked ? '#0284c7' : '#64748b'}; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                                ${isLinked ? `Linked to: ${linkedMatrixToken}` : 'Local Grid Active (Unlinked)'}
                            </span>
                        </div>
                        <input type="hidden" class="val-matrix-linked" value="${linkedMatrixToken}">
                        <div style="position: relative; display: flex; align-items: center; flex-shrink: 0;">
                            <!-- 🎯 FIX: Added dynamic class, color, and icon mutations based on link state -->
                            <button type="button" class="btn-input-link-trigger ${isLinked ? 'is-linked' : ''}" title="Link matrix token" style="background: #ffffff; border: 1px solid ${isLinked ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${isLinked ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 28px; width: 28px; display: flex; align-items: center; justify-content: center; box-sizing: border-box;">
                                <i class="fas ${isLinked ? 'fa-times' : 'fa-link'}"></i>
                            </button>
                            <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: auto; right: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 150px; padding: 4px 0; margin-top: 4px; box-sizing: border-box;"></div>
                        </div>
                    </div>

                    <!-- Structured Variable Substitutions (Always Visible) -->
                    <div class="row-variable-substitutions" style="display: flex; flex-direction: column; gap: 6px; width: 100%; border-bottom: 1px dashed #cbd5e1; padding-bottom: 8px; box-sizing: border-box;">
                        <span style="font-size: 0.72rem; font-weight: 600; color: #475569;">Matrix Variable Substitutions:</span>
                        <div class="substitutions-list-container" style="display: flex; flex-direction: column; gap: 6px;">
                            <!-- Dynamic evaluation input rows go here -->
                        </div>
                        <div class="substitution-picker-wrapper" style="display: flex; align-items: center; gap: 6px; margin-top: 2px;">
                            <span style="font-size: 0.75rem; color: #64748b;">Assign value to:</span>
                            <select class="picker-unused-variables" style="flex-grow: 1; font-size: 0.75rem; padding: 3px; border: 1px dashed #cbd5e1; border-radius: 4px; color: #475569; background: white;">
                                <!-- Populate dynamically using your variables extraction loop -->
                            </select>
                        </div>
                    </div>

                    <!-- Local Grid Configuration Layout Block (Hidden when linked) -->
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

                    <!-- Operation Configuration Block -->
                    <div style="display: grid; grid-template-columns: 1fr; gap: 8px; border-top: 1px dashed #cbd5e1; padding-top: 8px; box-sizing: border-box; width: 100%;">
                        <div class="linked-input-wrapper" data-input-key="calculate" data-input-type="text" style="display: flex; flex-direction: column; gap: 4px; box-sizing: border-box; width: 100%;">
                            <label style="font-size: 0.75rem; color: #475569; font-weight: 500;">Transformation Operation:</label>
                            <select class="val-matrix-calculate" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                                <option value="leave as matrix" ${currentCalcMode === 'leave as matrix' ? 'selected' : ''}>leave as matrix</option>
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

                    <!-- Secondary Matrix Target Selection Box -->
                    <div class="row-matrix-b-dependency linked-input-wrapper" data-input-key="matrix B" data-input-type="matrix" style="display: ${['multiply', 'add', 'subtract'].includes(currentCalcMode) ? 'flex' : 'none'}; position: relative; align-items: center; justify-content: space-between; gap: 8px; width: 100%; box-sizing: border-box; background: #f8fafc; padding: 6px 8px; border-radius: 4px; border: 1px solid #e2e8f0;">
                        <div style="display: flex; flex-direction: column; min-width: 0; flex-grow: 1;">
                            <span style="font-size: 0.75rem; font-weight: 600; color: #475569;">Secondary Matrix B Target</span>
                            <span class="matrix-b-status-text" style="font-size: 0.75rem; color: ${linkedMatrixBToken ? '#16a34a' : '#ef4444'}; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                                ${linkedMatrixBToken ? `Linked to: ${linkedMatrixBToken}` : 'Required: Select a matrix (e.g. matrix2)'}
                            </span>
                        </div>
                        <input type="hidden" class="val-matrix-b-target" value="${linkedMatrixBToken}">
                        <div style="position: relative; display: flex; align-items: center; flex-shrink: 0;">
                            <!-- 🎯 FIXED: Replaced 'isLinked' with '!!linkedMatrixBToken' to correctly trigger class mutations and change the icon layout to fa-times -->
                            <button type="button" class="btn-input-link-trigger ${linkedMatrixBToken ? 'is-linked' : ''}" title="Link matrix token" style="background: #ffffff; border: 1px solid ${linkedMatrixBToken ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${linkedMatrixBToken ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 28px; width: 28px; display: flex; align-items: center; justify-content: center; box-sizing: border-box;">
                                <i class="fas ${linkedMatrixBToken ? 'fa-times' : 'fa-link'}"></i>
                            </button>
                            <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: auto; right: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 150px; padding: 4px 0; margin-top: 4px; box-sizing: border-box;"></div>
                        </div>
                    </div>

                    <!-- Scalar Multiplier Input Field -->
                    <div class="row-matrix-scalar-dependency linked-input-wrapper" data-input-key="scalar" data-input-type="double" style="display: ${currentCalcMode === 'scalar' ? 'flex' : 'none'}; position: relative; align-items: flex-end; gap: 4px; width: 100%; box-sizing: border-box;">
                        <label style="font-size: 0.75rem; color: #475569; flex-grow: 1; display: block; width: 100%;">Scalar Factor Multiplier (c): 
                            <input type="number" step="any" class="val-matrix-scalar-factor" value="${savedValues.scalar !== undefined ? savedValues.scalar : 1.0}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                        </label>
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
                        <div class="workspace-info-tooltip-container" 
                             style="position: relative; display: inline-block;"
                             onmouseenter="(() => {
                                 const overlay = this.querySelector('.workspace-info-tooltip-overlay');
                                 const container = this.closest('div[style*=\\'overflow-y: auto\\']');
                                 if (!overlay || !container) return;
                                 
                                 // Reset to default first
                                 overlay.style.bottom = '102%';
                                 overlay.style.top = 'auto';
                                 
                                 // Shift down flush to top if it clips the ceiling
                                 if (overlay.getBoundingClientRect().top < container.getBoundingClientRect().top) {
                                     overlay.style.bottom = 'auto';
                                     overlay.style.top = '0px';
                                 }
                             })()">
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

        // 🎯 NEW ARCHITECTURE: DELEGATE EVENT BINDING TO SUB-ENTITIES
        if (window.SubEntityHandlers && window.SubEntityHandlers[token] && typeof window.SubEntityHandlers[token].bindEvents === 'function') {
            window.SubEntityHandlers[token].bindEvents(card, updateWorkspaceSimulationPreview);
        }

        if (token === 'formula') {
            card.addEventListener('input', function() {
                updateWorkspaceSimulationPreview();
            });
        }

        // --- NEW BINDING LOGIC: Handle multi-formula arrays inside Graphs dynamically ---
        if (token === 'graph') {
            const container = card.querySelector('.graph-formulas-container');
            const addBtn = card.querySelector('.btn-add-graph-formula');

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
                updateWorkspaceSimulationPreview();
            });

            container.addEventListener('click', function(e) {
                const removeBtn = e.target.closest('.btn-remove-graph-formula');
                if (removeBtn) {
                    console.group("%c🗑️ [Graph UI Deletion] Remove Button Clicked", "background: #ef4444; color: white; padding: 2px 6px; border-radius: 4px;");
                    
                    const row = removeBtn.closest('.graph-formula-row');
                    row.remove();
                    
                    const remainingRows = container.querySelectorAll('.val-graph-formula-expr');
                    updateWorkspaceSimulationPreview();

                    if (remainingRows.length > 0) {
                        remainingRows[0].dispatchEvent(new Event('input', { bubbles: true }));
                    } else {
                        const neighboringInput = card.querySelector('.val-graph-x-min');
                        if (neighboringInput) {
                            neighboringInput.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                    }
                    console.groupEnd();
                }
            });
        }

        // --- MATRIX ENGINE BINDING LOGIC: Handle runtime layout & visibility shifts ---
        if (token === 'matrix') {
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

        if (!card.hasAttribute('data-shuffle-seed') || card.getAttribute('data-shuffle-seed') === '') {
            const freshSeed = Math.random().toString();
            card.setAttribute('data-shuffle-seed', freshSeed);
        }

        if (token === 'formula') {
            bindLiveFormulaEvaluation(card, savedValues || {});
        }

        const newlyCreatedWrappers = card.querySelectorAll(
            '.linked-input-wrapper:not(.substitutions-list-container .linked-input-wrapper)'
        );
        newlyCreatedWrappers.forEach(wrapper => {
            const inputKey = wrapper.getAttribute('data-input-key');
            const savedValue = savedValues[inputKey];

            if (savedValue && typeof savedValue === 'string' && savedValue.trim().match(/^<([^>]+)>$/)) {
                const cleanTokenString = savedValue.trim();
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
                if (typeof saveStatusSpan !== 'undefined' && saveStatusSpan) {
                    saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                }
                updateWorkspaceSimulationPreview();
            }
        });

        updateWorkspaceSimulationPreview();
        console.groupEnd();

        return card;
    }

    // -------------------------------------------------------------------------
    // 🎯 REFACTOR: Unified component row value retriever with recursive link tracking
    // -------------------------------------------------------------------------
    function getLiveComponentValue(card, inputKey, defaultFallback, visitedTokens = []) {
        if (!card) return defaultFallback;
        
        let rawValue = '';
        let linkedTokenName = null;

        const wrapper = card.querySelector(`.linked-input-wrapper[data-input-key="${inputKey}"]`);
        if (wrapper) {
            const rawBoundToken = wrapper.getAttribute('data-bound-token');
            if (rawBoundToken) {
                linkedTokenName = rawBoundToken.replace(/[<>]/g, '').trim();
            }
            const nativeInput = wrapper.querySelector('input, select, textarea');
            rawValue = (nativeInput && nativeInput.value !== '') ? nativeInput.value.trim() : '';
        } else {
            const legacyInput = card.querySelector(`.val-input-${inputKey}`);
            rawValue = legacyInput ? legacyInput.value.trim() : '';
        }

        if (!linkedTokenName && rawValue !== '') {
            const match = String(rawValue).match(/^<([a-zA-Z0-9_]+)>$/);
            if (match) {
                linkedTokenName = match[1].trim();
            }
        }

        if (linkedTokenName) {
            if (visitedTokens.includes(linkedTokenName)) {
                console.error(`🛑 [Circular Dependency Blocked] Token loop detected targeting: "${linkedTokenName}". Defensively utilizing fallback fallback: "${defaultFallback}"`);
                return defaultFallback;
            }
            
            const upstreamCard = Array.from(document.querySelectorAll('.workspace-component-card')).find(c => {
                const delBtn = c.querySelector('.btn-delete-workspace-component');
                return delBtn && delBtn.getAttribute('data-indexed-token') === linkedTokenName;
            });

            if (upstreamCard) {
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

        // 🎯 NEW ARCHITECTURE: DELEGATE EVALUATION TO SUB-ENTITY IF AVAILABLE
        if (window.SubEntityHandlers && window.SubEntityHandlers[baseArchetype] && typeof window.SubEntityHandlers[baseArchetype].evaluate === 'function') {
            val = window.SubEntityHandlers[baseArchetype].evaluate(card, tokenIdentifier, visitedTokens, getLiveComponentValue);
        }
        // 🎯 PRIORITY B: Local Calculation engines serve purely as a cold bootstrap backup if server state isn't injected yet
        else if (baseArchetype === 'randInt') {
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
            
            const formulaStr = getLiveComponentValue(card, 'formula', tokenIdentifier, visitedTokens);
            console.groupEnd();
            return formulaStr;
        }
        else if (baseArchetype === 'graph') {
            const graphNodes = getLiveComponentValue(card, 'nodes', '[]', visitedTokens);
            const graphEdges = getLiveComponentValue(card, 'edges', '[]', visitedTokens);
            const graphData  = getLiveComponentValue(card, 'data', '', visitedTokens);

            if (graphData && graphData !== '') {
                val = graphData;
            } else {
                val = `Graph(${graphNodes || 'empty'}, ${graphEdges || 'empty'})`;
            }
        }

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

        function extractVariablesFromFormulaString(formulaStr) {
            if (!formulaStr) return [];
            
            const cleanStr = formulaStr.trim();
            const tokenMatch = cleanStr.match(/^<([^>]+)>$/);
            
            if (tokenMatch) {
                const targetTokenIndexName = tokenMatch[1].strip ? tokenMatch[1].strip() : tokenMatch[1];
                const sourceCard = document.querySelector(`[data-indexed-token="${targetTokenIndexName}"], [data-token="${targetTokenIndexName}"]`);
                if (sourceCard) {
                    const sourceVarsInput = sourceCard.querySelector('.val-input-variables');
                    if (sourceVarsInput && sourceVarsInput.value) {
                        return sourceVarsInput.value.split(',').map(v => v.trim()).filter(v => v.length > 0);
                    }
                }
                return [];
            }

            const greekRegexStr = '^(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lamda|mu|nu|xi|omicron|rho|sigma|tau|upsilon|phi|chi|psi|omega)';
            const allWordMatches = formulaStr.match(/\b[a-zA-Z][a-zA-Z0-9_]*\b/g) || [];
            
            const variableMatches = allWordMatches.filter(word => {
                const lowerWord = word.toLowerCase();
                if (word === 'E' || word === 'I') return false;
                if (/^[a-zA-Z][0-9]*$/.test(word)) return true;
                if (/^[a-zA-Z]_[0-9]+$/.test(word)) return true;
                if (new RegExp(greekRegexStr + '$').test(lowerWord)) return true;
                if (new RegExp(greekRegexStr + '_[0-9]+$').test(lowerWord)) return true;
                if (new RegExp(greekRegexStr + '[0-9]+$').test(lowerWord)) return true;
                
                return false;
            });
            
            return [...new Set(variableMatches)];
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

    // -------------------------------------------------------------
    // LIVE PREVIEW SIMULATION RENDERING ENGINE (DYNAMIC RE-CALCULATION)
    // -------------------------------------------------------------
    function updateWorkspaceSimulationPreview() {
        if (window.isHydratingWorkspace) return; 
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
        const tokenRegex = /&lt;([a-zA-Z0-9_]+)&gt;/g;

        let simulatedHtml = workingHtml.replace(tokenRegex, function(match, tokenText) {
            try {
                const cleanToken = tokenText.trim(); 
                let baseArchetypeToken = cleanToken.replace(/\d+$/, ''); 

                const card = Array.from(document.querySelectorAll('.workspace-component-card')).find(c => {
                    const delBtn = c.querySelector('.btn-delete-workspace-component');
                    return delBtn && delBtn.getAttribute('data-indexed-token') === cleanToken;
                });

                if (card && card.getAttribute('data-token')) {
                    baseArchetypeToken = card.getAttribute('data-token');
                }

                const inDynamicVarsList = dynamicVarsTokens.some(v => v.token === baseArchetypeToken);
                const isFormulaCondition = baseArchetypeToken === 'formula';
                const isVar = inDynamicVarsList || isFormulaCondition || ['randInt', 'rand', 'primeFactors', 'graph', 'matrix'].includes(baseArchetypeToken);

                if (isVar) {
                    let displayVal = formulaLiveLatexCache[cleanToken];
                    const isServerValueValid = displayVal !== undefined && displayVal !== null && displayVal !== '' && displayVal !== '0' && displayVal !== '???';

                    if (baseArchetypeToken === 'formula') {
                        if (!isServerValueValid && card) {
                            displayVal = card.getAttribute('data-simulated-value') || cleanToken;
                        }
                    } else {
                        if (card) {
                            displayVal = evaluateSingleCardOutput(card, cleanToken);
                        } else {
                            console.warn(`⚠️ [Canvas Render Warning] Token "${cleanToken}" matched a known archetype list, but its workspace card DOM node could not be found on the page.`);
                        }
                    }

                    if (!displayVal || displayVal === '???') {
                        displayVal = cleanToken;
                    }

                    console.groupEnd();

                    if (baseArchetypeToken === 'formula') {
                        return `<span class="simulated-math-formula-render" style="display: inline-block; padding: 2px 4px;">${displayVal}</span>`;
                    }
                    else if (baseArchetypeToken === 'graph') {
                        try {
                            const graphConfig = typeof displayVal === 'string' ? JSON.parse(displayVal) : displayVal;
                            const previewCanvasId = `live-preview-canvas-${cleanToken}`;
                            
                            if (graphConfig && graphConfig.formulas) {
                                graphConfig.formulas = graphConfig.formulas.map(fStr => {
                                    let rhs = fStr.split('=')[1] || fStr;
                                    return rhs.replace(/\*\*/g, '^').trim();
                                });
                            }

                            setTimeout(() => {
                                if (typeof renderGraphComponentCanvas === 'function') {
                                    renderGraphComponentCanvas(previewCanvasId, graphConfig);
                                }
                            }, 0);

                            return `
                                <div class="simulated-live-graph-preview-container" style="display: block; margin: 12px auto; max-width: 360px; padding: 8px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;">
                                    <div id="${previewCanvasId}" style="display: flex; justify-content: center; width: 100%;"></div>
                                </div>
                            `;
                        } catch (jsonErr) {
                            console.error("Malformed graph entity JSON stream block encountered during rendering pass:", jsonErr);
                            return `<span style="color: #ef4444; font-family: monospace;">[Malformed Graph State Data]</span>`;
                        }
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

            let baseArchetypeToken = token.replace(/[0-9]/g, '');

            const databaseBlueprints = window.DATABASE_BLUEPRINTS || {};
            const matchedBlueprint = databaseBlueprints[baseArchetypeToken] || {};
            const blueprintInputsSchema = matchedBlueprint.inputs || {};

            const inputsCollected = {};

            Object.entries(blueprintInputsSchema).forEach(([inputKey, schemaConfig]) => {
                if (schemaConfig && schemaConfig.default !== undefined) {
                    inputsCollected[inputKey] = schemaConfig.default;
                } else {
                    inputsCollected[inputKey] = "";
                }
            });

            card.querySelectorAll('.linked-input-wrapper').forEach(wrapper => {
                const key = wrapper.getAttribute('data-input-key');
                if (!key || (key.startsWith('sub_') && baseArchetypeToken !== 'matrix')) return;

                const boundToken = wrapper.getAttribute('data-bound-token');
                const tokenPill = wrapper.querySelector('.linked-token-pill');
                
                if (boundToken) {
                    let cleanToken = boundToken.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
                    if (!cleanToken.startsWith('<')) cleanToken = `<${cleanToken}`;
                    if (!cleanToken.endsWith('>')) cleanToken = `${cleanToken}>`;
                    inputsCollected[key] = cleanToken;
                } else if (tokenPill) {
                    const rawPillId = tokenPill.getAttribute('data-indexed-token') || tokenPill.textContent || "";
                    let cleanPill = rawPillId.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
                    cleanPill = cleanPill.replace(/[<>]/g, ''); 
                    inputsCollected[key] = cleanPill ? `<${cleanPill}>` : "";
                } else {
                    const nativeField = wrapper.querySelector('input, select, textarea');
                    if (nativeField) {
                        inputsCollected[key] = nativeField.value.trim();
                    }
                }
            });

            // 🎯 NEW ARCHITECTURE: DELEGATE SERIALIZATION TO SUB-ENTITIES IF LOADED
            if (window.SubEntityHandlers && window.SubEntityHandlers[baseArchetypeToken] && typeof window.SubEntityHandlers[baseArchetypeToken].serialize === 'function') {
                const subEntityData = window.SubEntityHandlers[baseArchetypeToken].serialize(card, inputsCollected);
                Object.assign(inputsCollected, subEntityData);
            }
            // 3. ARCHETYPE SPECIFIC OVERRIDES: Apply specialized structure extensions ONLY to formula types
            else if (baseArchetypeToken === 'formula') {
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
                console.log("Cleaned substitutions mapping payload: ", inputsCollected["substitutions"]);
            } 
            else if (baseArchetypeToken === 'graph') {
                console.group("%c💾 [Serializer] Packaging Graph Payload", "background: #3b82f6; color: white; padding: 2px 6px; border-radius: 4px;");
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
                        let cleanToken = boundToken.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
                        if (!cleanToken.startsWith('<')) cleanToken = `<${cleanToken}`;
                        if (!cleanToken.endsWith('>')) cleanToken = `${cleanToken}>`;
                        finalRowVal = cleanToken;

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
                console.log("Final compiled fields payload object structure:", JSON.parse(JSON.stringify(inputsCollected)));
                console.groupEnd();
            }
            else if (baseArchetypeToken === 'matrix') {
                console.group(`%c💾 [Serializer] Packaging Matrix Payload for [${token}]`, "background: #0284c7; color: white; padding: 2px 6px; border-radius: 4px;");
                
                const rowsInput = card.querySelector('.val-matrix-rows');
                const colsInput = card.querySelector('.val-matrix-columns');
                
                const rowCount = parseInt(rowsInput?.value) || 3;
                const colCount = parseInt(colsInput?.value) || 3;

                // 🎯 COMPLETION: Map matrix structures accurately into the backend payload
                const structureGrid = Array.from({ length: rowCount }, (_, r) => 
                    Array.from({ length: colCount }, (_, c) => {
                        const cell = card.querySelector(`.val-matrix-cell[data-row="${r}"][data-col="${c}"]`);
                        return cell ? cell.value.trim() : "0";
                    })
                );
                
                inputsCollected["matrix_data"] = structureGrid;
                inputsCollected["rows"] = rowCount;
                inputsCollected["columns"] = colCount;

                const linkedMatrixInput = card.querySelector('.val-matrix-linked');
                if (linkedMatrixInput) inputsCollected["linked_matrix"] = linkedMatrixInput.value;

                const calcSelect = card.querySelector('.val-matrix-calculate');
                if (calcSelect) inputsCollected["calculate"] = calcSelect.value;

                const matrixBInput = card.querySelector('.val-matrix-b-target');
                if (matrixBInput) inputsCollected["matrix B"] = matrixBInput.value;

                const scalarInput = card.querySelector('.val-matrix-scalar-factor');
                if (scalarInput) inputsCollected["scalar"] = parseFloat(scalarInput.value) || 1.0;
                
                console.groupEnd();
            }

            entities.push({
                token: baseArchetypeToken,
                sequence_token: token,
                inputs: inputsCollected,
                points: parseFloat(card.getAttribute('data-points')) || 0.0,
                simulated_value: card.getAttribute('data-simulated-value') || null,
                shuffle_seed: card.getAttribute('data-shuffle-seed') || null
            });
        });

        return entities;
    }

    // -------------------------------------------------------------
    // ENGINE API SYNCHRONIZATION
    // -------------------------------------------------------------
    function dispatchWorkspaceBatchSync(triggerContext = null) {
        if (isWorkspaceInitializing) {
            console.log("⏳ Workspace is currently hydrating. Bypassing network sync.");
            return;
        }

        const now = Date.now();
        if (now - activeBatchSyncTimestamp < 500) {
            console.log("⏳ Rapid sync debounced.");
            return;
        }
        activeBatchSyncTimestamp = now;

        console.group(`%c🚀 [Network] Dispatching Workspace Batch Sync (Trigger: ${triggerContext})`, "background: #f59e0b; color: white; padding: 2px 6px; border-radius: 4px;");
        
        if (saveStatusSpan) {
            saveStatusSpan.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Saving...`;
            saveStatusSpan.style.color = '#eab308';
        }

        const payload = serializeAllWorkspaceEntities();
        console.log("📦 Compiled Batch Payload Data:", payload);

        updateWorkspaceSimulationPreview();

        // Server POST simulation timeout
        setTimeout(() => {
            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-check-circle"></i> Saved`;
                saveStatusSpan.style.color = '#10b981';
            }
            console.groupEnd();
        }, 800);
    }

    // -------------------------------------------------------------
    // GLOBAL EVENT LISTENERS & INITIALIZATION
    // -------------------------------------------------------------
    if (saveDraftBtn) {
        saveDraftBtn.addEventListener('click', () => dispatchWorkspaceBatchSync('manual_save'));
    }

    if (closeOverlayBtn) {
        closeOverlayBtn.addEventListener('click', () => {
            if (workspaceOverlay) workspaceOverlay.style.display = 'none';
        });
    }

    function checkEmptyColumns() {
        if (variablesContainer && variablesContainer.children.length === 0) {
            variablesContainer.innerHTML = '<div class="empty-placeholder" style="padding: 12px; text-align: center; color: #94a3b8; font-style: italic; font-size: 0.85rem; border: 1px dashed #cbd5e1; border-radius: 6px;">No variables defined yet.</div>';
        }
        if (inputsContainer && inputsContainer.children.length === 0) {
            inputsContainer.innerHTML = '<div class="empty-placeholder" style="padding: 12px; text-align: center; color: #94a3b8; font-style: italic; font-size: 0.85rem; border: 1px dashed #cbd5e1; border-radius: 6px;">No input fields defined yet.</div>';
        }
    }

    function removePlaceholders(container) {
        const placeholder = container.querySelector('.empty-placeholder');
        if (placeholder) placeholder.remove();
    }

    function clearAndShowPlaceholders() {
        if (variablesContainer) variablesContainer.innerHTML = '';
        if (inputsContainer) inputsContainer.innerHTML = '';
        checkEmptyColumns();
    }

    function createTokenBadge(token, savedSequenceToken) {
        if (!tokensLedger) return;
        const badge = document.createElement('span');
        badge.className = 'ledger-badge';
        badge.style.cssText = 'background: #f1f5f9; border: 1px solid #cbd5e1; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; margin-right: 4px; display: inline-block; font-family: monospace;';
        badge.innerText = savedSequenceToken || token;
        tokensLedger.appendChild(badge);
    }

}); // End of DOMContentLoaded Controller Scope