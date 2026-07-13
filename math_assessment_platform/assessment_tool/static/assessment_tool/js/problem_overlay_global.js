import { processEntity as randIntProcessor } from './entities/randInt.js';
import { processEntity as randProcessor } from './entities/rand.js';
import { processEntity as primeFactorsProcessor } from './entities/primeFactors.js';
import { processEntity as formulaProcessor } from './entities/formula.js';
import { processEntity as matrixProcessor } from './entities/matrix.js';
import { processEntity as graphProcessor } from './entities/graph.js';
import { ensureLatexRenderBox } from './entities/helpers.js';

// Map tokens directly to their synchronous entity processors
const ENTITY_REGISTRY = {
    'randInt': randIntProcessor,
    'rand': randProcessor,
    'primeFactors': primeFactorsProcessor,
    'formula': formulaProcessor,
    'matrix': matrixProcessor,
    'graph': graphProcessor,
};


/**
 * Processes a token synchronously using the pre-loaded registry.
 *
 * @param {string} token - The token string (e.g., 'randInt')
 * @param {Object} contextData - Any data the entity file needs to do its job
 */
function getEntityInformation(token, contextData) {
    const processor = ENTITY_REGISTRY[token];

    if (!processor) {
        if (contextData?.action === 'fieldsHtml') {
            console.warn(`Entity token "${token}" is not registered.`);
        }
        return null;
    }

    try {
        return processor(contextData);
    } catch (error) {
        console.error(`Entity processor failed for "${token}":`, error);
        return null;
    }
}

// -------------------------------------------------------------
// Global Problem Workspace Overlay Controller Engine
// -------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function() {
    const workspaceOverlay = document.getElementById('problem-workspace-overlay');
    if (!workspaceOverlay) return;

    // One-time entity global listeners (e.g. matrix substitution picker)
    Object.keys(ENTITY_REGISTRY).forEach(token => {
        getEntityInformation(token, { action: 'initGlobalListeners' });
    });

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
            console.warn('Dropdown binding skipped: trigger or menu element missing.');
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
                console.error('Cannot add entity card: sidebar container missing.');
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

        isWorkspaceInitializing = true; 
        window.isHydratingWorkspace = true; // Set both flags at the top

        try {
            // Differentiate missing data from an empty new workspace
            if (!segments) {
                console.warn('Workspace load response missing segments array.');
                clearAndShowPlaceholders();
                return;
            }

            if (segments.length === 0) {
                clearAndShowPlaceholders();
                return; // 🌟 Safe early exit! The 'finally' block will still unlock the state.
            }

            if (variablesContainer) variablesContainer.innerHTML = '';
            if (inputsContainer) inputsContainer.innerHTML = '';
            if (tokensLedger) tokensLedger.innerHTML = '';

            segments.forEach((segment, idx) => {
                try {
                    const isVariable = dynamicVarsTokens.some(item => item.token === segment.token);
                    const targetContainer = isVariable ? variablesContainer : inputsContainer;

                    if (!targetContainer) {
                        console.error('Cannot rehydrate entity card: target sidebar panel missing.');
                        return;
                    }

                    removePlaceholders(targetContainer);

                    const savedSequenceToken = segment.sequence_token;
                    createTokenBadge(segment.token, savedSequenceToken);
                    const latestCard = createNewBlockInstanceUI(segment.token, targetContainer, segment.inputs, segment.points, savedSequenceToken);

                    if (latestCard) {
                        if (segment.simulated_value !== undefined && segment.simulated_value !== null) {
                            latestCard.setAttribute('data-simulated-value', segment.simulated_value);
                        }
                        // Seed preview LaTeX immediately so the canvas does not wait on async batch sync
                        if (segment.latex_output !== undefined && segment.latex_output !== null && segment.latex_output !== '') {
                            latestCard.setAttribute('data-latex-output', segment.latex_output);
                            if (savedSequenceToken) {
                                formulaLiveLatexCache[savedSequenceToken] = segment.latex_output;
                            }
                        }
                        if (segment.shuffle_seed !== undefined && segment.shuffle_seed !== null && segment.shuffle_seed !== '') {
                            latestCard.setAttribute('data-shuffle-seed', segment.shuffle_seed);
                        }
                    }
                } catch (segmentErr) {
                    console.error(`Failed rehydrating entity <${segment?.sequence_token || segment?.token || idx}>:`, segmentErr);
                } finally {
                }
            });

            // Run structural cleanups
            checkEmptyColumns();

            // Run calculation triggers
            if (typeof dispatchWorkspaceBatchSync === 'function') {
                // Pass 'initial_load' instead of null to bypass the initialization block
                dispatchWorkspaceBatchSync('initial_load', { forceRefresh: true });
            }

        } catch (error) {
            console.error('Workspace rehydration failed:', error);
        } finally {
            // 🔓 This block ALWAYS executes, saving the application state from lockouts
            isWorkspaceInitializing = false; 
            window.isHydratingWorkspace = false;
            // Paint preview from seeded latex_output / simulated values before async batch returns
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
                return fallback; 
            }
            return val ?? fallback;
        };

        let fieldsHtml = getEntityInformation(token, {
            action: 'fieldsHtml',
            savedValues
        });
        if (fieldsHtml === null || fieldsHtml === undefined || fieldsHtml === '') {
            fieldsHtml = `<p style="font-size:0.8rem; color:#64748b; margin:0;">Standard attributes container template wrapper.</p>`;
        }

        card.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px dashed #e2e8f0; padding-bottom: 6px; margin-bottom: 4px;">
                <span style="font-weight: 600; font-size: 0.85rem; color: ${headerColor};"><i class="fas fa-cube"></i> &lt;${indexedTokenString}&gt;</span>
                <div style="display: flex; align-items: center; gap: 8px;">
                    
                    ${!getEntityInformation(token, { action: 'hideRefreshButton' }) ? `
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

        getEntityInformation(token, {
            action: 'bindEvents',
            card,
            savedValues: savedValues || {},
            updateWorkspaceSimulationPreview
        });

        const newlyCreatedWrappers = card.querySelectorAll(
            '.linked-input-wrapper:not(.substitutions-list-container .linked-input-wrapper)'
        );
        newlyCreatedWrappers.forEach(wrapper => {
            try {
                const inputKey = wrapper.getAttribute('data-input-key');
                const savedValue = savedValues[inputKey];

                if (savedValue && typeof savedValue === 'string' && savedValue.trim().match(/^<([^>]+)>$/)) {
                    const cleanTokenString = savedValue.trim();
                    const linkBtn = wrapper.querySelector('.btn-input-link-trigger');

                    const labelEl = wrapper.querySelector('label');
                    if (labelEl) {
                        labelEl.style.display = 'none';
                    } else {
                        const inputEl = wrapper.querySelector('input:not([type="hidden"]), select');
                        if (inputEl) inputEl.style.display = 'none';
                    }

                    wrapper.setAttribute('data-bound-token', cleanTokenString);

                    // Avoid duplicate pills when matrix templates already render a linked state
                    if (!wrapper.querySelector('.linked-token-pill')) {
                        const pill = document.createElement('span');
                        pill.className = 'linked-token-pill';
                        pill.style.cssText = 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 4px 8px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.8rem; display: inline-block; width: 100%; box-sizing: border-box; text-align: center;';
                        pill.innerText = cleanTokenString;
                        // linkBtn may live inside a nested relative wrapper (matrix B / linked_matrix)
                        if (linkBtn && typeof linkBtn.before === 'function') {
                            linkBtn.before(pill);
                        } else if (linkBtn && linkBtn.parentNode) {
                            linkBtn.parentNode.insertBefore(pill, linkBtn);
                        } else {
                            wrapper.appendChild(pill);
                        }
                    }

                    if (linkBtn) {
                        linkBtn.innerHTML = '<i class="fas fa-times"></i>';
                        linkBtn.className = 'btn-input-link-trigger is-linked';
                        linkBtn.style.color = '#ef4444';
                        linkBtn.style.borderColor = '#fca5a5';
                    }
                }
            } catch (linkRestoreErr) {
                console.warn("Failed restoring linked-token UI; continuing card build.", linkRestoreErr);
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

        return card;
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
                console.error(`Circular dependency blocked for token "${linkedTokenName}"; using fallback "${defaultFallback}".`);
                return defaultFallback;
            }

            
            const upstreamCard = Array.from(document.querySelectorAll('.workspace-component-card')).find(c => {
                const delBtn = c.querySelector('.btn-delete-workspace-component');
                return delBtn && delBtn.getAttribute('data-indexed-token') === linkedTokenName;
            });

            if (upstreamCard) {
                // Pass downstream state references recursively up the execution trace line
                return evaluateSingleCardOutput(upstreamCard, linkedTokenName, [...visitedTokens]);
            } else {
                console.warn(`Linked upstream card "<${linkedTokenName}>" not found in the workspace DOM.`);
            }
        }

        return rawValue !== '' ? rawValue : defaultFallback;
    }

    // -------------------------------------------------------------------------
    // ⚙️ CORE MATRIX: Updated Simulation Calculation Loop
    // -------------------------------------------------------------------------
    function evaluateSingleCardOutput(card, tokenIdentifier, visitedTokens = []) {
        if (!card) {
            console.warn(`evaluateSingleCardOutput called without a card for token "${tokenIdentifier}".`);
            return tokenIdentifier;
        }
        
        const baseArchetype = card.getAttribute('data-token');
        let val = null;

        // Push current node validation identifier to trace array sequence context
        if (!visitedTokens.includes(tokenIdentifier)) {
            visitedTokens.push(tokenIdentifier);
        }


        // 🎯 PRIORITY A: Check if the server has stored a verified calculated value directly on the card markup
        const calculatedValueFallback = card.getAttribute('data-simulated-value');
        if (calculatedValueFallback !== null && calculatedValueFallback !== undefined && calculatedValueFallback !== '' && calculatedValueFallback !== 'None' && calculatedValueFallback !== 'null') {
            return calculatedValueFallback;
        }

        // 🎯 PRIORITY B: Local Calculation engines serve purely as a cold bootstrap backup if server state isn't injected yet
        const evaluated = getEntityInformation(baseArchetype, {
            action: 'evaluate',
            card,
            tokenIdentifier,
            visitedTokens,
            getLiveComponentValue,
            formulaLiveLatexCache
        });
        if (evaluated !== null && evaluated !== undefined) {
            // Formula evaluate may return early via cache/string — short-circuit like original
            if (baseArchetype === 'formula') {
                return evaluated;
            }
            val = evaluated;
        }


        // Final Output Summary Resolution (Fallback check if local engine rules fell through)
        const finalReturnedValue = (val !== null && val !== undefined && val !== '') ? val : tokenIdentifier;

        return finalReturnedValue;
    }

    // -------------------------------------------------------------
    // LIVE PREVIEW SIMULATION RENDERING ENGINE (DYNAMIC RE-CALCULATION)
    // -------------------------------------------------------------
    function updateWorkspaceSimulationPreview() {
        if (window.isHydratingWorkspace) return; // 🛑 Halt execution during hydration loop
        const renderTarget = document.getElementById('simulation-render-target');
        if (!renderTarget) {
            console.warn("Simulation preview aborted: #simulation-render-target is missing.");
            return;
        }

        let canvasContent = workspaceQuillInstance ? workspaceQuillInstance.root.innerHTML.trim() : '';

        if (!canvasContent || canvasContent === '<p><br></p>') {
            renderTarget.innerHTML = '<p style="color: #94a3b8; font-style: italic; margin: 0;">Interactive layout testing view builds dynamically here...</p>';
            return;
        }

        if (typeof renderPreviewCanvasMarkup === 'function') {
            renderPreviewCanvasMarkup(canvasContent, renderTarget);
        } else {
            console.warn("Simulation preview aborted: renderPreviewCanvasMarkup is not available.");
        }
    }

    // 🎯 HELPER SUB-ROUTINE: HANDLES REGEX STRING REPLACEMENT & KATEX PARSING
    function renderPreviewCanvasMarkup(canvasContent, renderTarget) {
        
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


        let simulatedHtml = workingHtml.replace(tokenRegex, function(match, tokenText) {
            try {
                // Safely isolate the alphanumeric token key identifier reference string
                const cleanToken = tokenText.trim(); 
                let baseArchetypeToken = cleanToken.replace(/\d+$/, ''); 

                // 🔍 DIAGNOSTIC LOG 1: Track what the layout parser is trying to match

                // 🔍 Print out all component cards currently residing in the DOM to inspect their names
                const availableCards = Array.from(document.querySelectorAll('.workspace-component-card')).map(c => {
                    return {
                        archetype: c.getAttribute('data-token'),
                        indexedTokenAttr: c.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token')
                    };
                });

                // Locate the active interactive workspace card row using case-insensitive matching logic
                const card = Array.from(document.querySelectorAll('.workspace-component-card')).find(c => {
                    const delBtn = c.querySelector('.btn-delete-workspace-component');
                    return delBtn && delBtn.getAttribute('data-indexed-token') === cleanToken;
                });


                if (card && card.getAttribute('data-token')) {
                    baseArchetypeToken = card.getAttribute('data-token');
                }

                // Check variable validation token lists or structural layout conditions
                const inDynamicVarsList = dynamicVarsTokens.some(v => v.token === baseArchetypeToken);
                const isFormulaCondition = baseArchetypeToken === 'formula';
                
                // If it looks like a known archetype, treat it as a variable processing path
                const isVar = inDynamicVarsList || isFormulaCondition || ['randInt', 'rand', 'primeFactors', 'graph', 'matrix'].includes(baseArchetypeToken);

                if (isVar) {
                    let displayVal = formulaLiveLatexCache[cleanToken];

                    // Prefer server/cached LaTeX; never treat valid latex "0" as missing
                    const isServerValueValid = displayVal !== undefined && displayVal !== null && displayVal !== '' && displayVal !== '???';

                    if (baseArchetypeToken === 'formula' || baseArchetypeToken === 'matrix') {
                        if (!isServerValueValid && card) {
                            displayVal = card.getAttribute('data-latex-output')
                                || card.getAttribute('data-simulated-value')
                                || cleanToken;
                        }
                    } else {
                        // FORCE math generators (rand, randInt, primeFactors) to compute purely client-side
                        if (card) {
                            
                            // Prefer loaded latex when present; otherwise live-evaluate
                            const loadedLatex = card.getAttribute('data-latex-output') || formulaLiveLatexCache[cleanToken];
                            if (loadedLatex && loadedLatex !== '???' && loadedLatex !== '') {
                                displayVal = loadedLatex;
                            } else {
                                displayVal = evaluateSingleCardOutput(card, cleanToken);
                            }
                        } else {
                            // 🔍 ADD THIS WARNING HERE:
                            console.warn(`Preview token "<${cleanToken}>" has no matching entity card in the DOM.`);
                        }
                    }

                    // Strict validation fallback loop parameter checks
                    if (!displayVal || displayVal === '???') {
                        displayVal = cleanToken;
                    }


                    // Delegate entity-specific preview rendering (formula, graph, etc.)
                    const previewHtml = getEntityInformation(baseArchetypeToken, {
                        action: 'renderPreviewToken',
                        displayVal,
                        cleanToken,
                        card,
                        renderGraphComponentCanvas
                    });
                    if (previewHtml) {
                        return previewHtml;
                    }

                    // 🎯 STEP 3: Fallback for all other standard variable badges (rand, randInt, etc)
                    return `<span class="simulated-math-variable-badge" style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.9rem; display: inline-block; margin: 0 2px;">${displayVal}</span>`;
                
                } else if (answerFieldsTokens.some(i => i.token === baseArchetypeToken)) {
                    return `
                        <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px;">
                            <input type="text" placeholder="Input slot..." disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; width: 140px;">
                        </div>
                    `;
                }
                
                return match;
            } catch (err) {
                console.error(`Failed processing preview token ${match}:`, err);
                return `<span style="color: red; font-family: monospace;">[Token Error]</span>`;
            }
        });

        renderTarget.innerHTML = simulatedHtml;

        // 🎯 STEP 3: RUN KATEX DISPATCH OVER DYNAMIC HTML TARGETS
        if (typeof katex !== 'undefined') {
            renderTarget.querySelectorAll('.preview-static-latex').forEach(span => {
                try {
                    katex.render(span.textContent.trim(), span, { displayMode: false, throwOnError: false });
                } catch (err) { console.error("KaTeX failed rendering static preview latex:", err); }
            });

            renderTarget.querySelectorAll('.simulated-math-formula-render').forEach(span => {
                try {
                    const expression = span.textContent.trim();
                    if (expression) {
                        katex.render(expression, span, { displayMode: false, throwOnError: false });
                    }
                } catch (err) { 
                    console.error("KaTeX failed rendering formula preview:", err); 
                }
            });
        }
    }

    // Serializes active layout properties into structural object dictionaries matching database specifications
    function serializeAllWorkspaceEntities() {
        const entities = [];
        document.querySelectorAll('.workspace-block-card').forEach(card => {
            const delBtn = card.querySelector('.btn-delete-workspace-component');
            const token = delBtn ? delBtn.getAttribute('data-indexed-token') : null;
            if (!token) return;


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
                if (!key || (key.startsWith('sub_') && baseArchetypeToken !== 'matrix')) return;

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

            // 3. ARCHETYPE SPECIFIC OVERRIDES via entity modules
            const serializedInputs = getEntityInformation(baseArchetypeToken, {
                action: 'serialize',
                card,
                inputsCollected
            });
            if (serializedInputs && typeof serializedInputs === 'object') {
                Object.assign(inputsCollected, serializedInputs);
            }

            // 🎯 NEW CACHE LOCK BREAKER: Check if the user is actively editing this card
            let finalSimulatedValue = card.getAttribute('data-simulated-value');
            const activeElement = document.activeElement;
            const isCardBeingEdited = activeElement && card.contains(activeElement);

            if (isCardBeingEdited) {
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
        
        if (isWorkspaceInitializing && triggeringToken !== 'initial_load') {
            return;
        }
        
        const allEntities = serializeAllWorkspaceEntities();

        // 🎯 FIX: Destructure the new object format returned by the updated DAG engine
        const dependencyData = getDownstreamDependencies(allEntities, triggeringToken);
        const affectedEntities = dependencyData.familyGroup; // Contains full tree context (Ancestors + Descendants)
        const mutationTargets = dependencyData.mutationTargets; // Contains ONLY trigger + Descendants
        

        // Check against the familyGroup array length to see if anything was matched
        if (affectedEntities.length === 0 && !options.forceRefresh) {
            return;
        }

        const currentTimestamp = Date.now();
        activeBatchSyncTimestamp = currentTimestamp;

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
            return res.json();
        })
        .then(data => {

            const errorBanner = document.getElementById('workspace-validation-error-banner');
            const errorsList = document.getElementById('workspace-validation-errors-list');
            
            errorsList.innerHTML = '';
            
            // 🎯 MOVE THIS ABOVE: Process errors regardless of global execution flags
            if (data.errors && Object.keys(data.errors).length > 0) {
                if (errorBanner) errorBanner.style.display = 'flex';
                
                Object.entries(data.errors).forEach(([tokenKey, fieldErrors]) => {
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
                if (errorBanner) errorBanner.style.display = 'none';
            }

            if (currentTimestamp !== activeBatchSyncTimestamp) {
                return;
            }

            // 🎯 ADJUSTED GUARD: Only throw a terminal platform error if there are no validation errors to review
            if (!data.success && (!data.errors || Object.keys(data.errors).length === 0)) {
                console.error("Workspace validation failed:", data.error);
                return;
            }

            Object.keys(data.updated_cache).forEach(token => {
                const result = data.updated_cache[token];
                

                formulaLiveLatexCache[token] = result.latex_output;
                
                const card = Array.from(document.querySelectorAll('.workspace-block-card')).find(c => 
                    c.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token') === token
                );
                
                if (!card) {
                    return;
                }

                card.setAttribute('data-simulated-value', result.evaluated_output);
                if (result.latex_output !== undefined && result.latex_output !== null) {
                    card.setAttribute('data-latex-output', result.latex_output);
                }

                const baseArchetype = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-token');
                let targetDisplay = card.querySelector('.latex-render-box');

                if (getEntityInformation(baseArchetype, { action: 'needsLatexRenderBox' })) {
                    targetDisplay = ensureLatexRenderBox(card) || targetDisplay;
                }

                const batchApplied = getEntityInformation(baseArchetype, {
                    action: 'applyBatchSync',
                    card,
                    result,
                    targetDisplay,
                    formulaLiveLatexCache,
                    renderGraphComponentCanvas,
                    token
                });

                if (!batchApplied && targetDisplay) {
                    targetDisplay.style.textAlign = 'center';
                    targetDisplay.textContent = result.evaluated_output;
                }

                // 🔍 DEBUG LOG: Look for select elements inside the card to verify their class names
                const allSelectsOnCard = Array.from(card.querySelectorAll('select')).map(s => ({ className: s.className, name: s.name, value: s.value }));

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
                
            });


            updateWorkspaceSimulationPreview();
        })
        .catch(err => {
            console.error("Batch preview sync request failed:", err);
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

            // 🎯 CORRECTED FIX: Explicitly target your actual wrapper line element ID
            if (tokensLedger) {
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

            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Synced`;
            }

        } catch (err) {
            console.error("Failed loading problem workspace:", err);
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
    const draftConfirmModal = document.getElementById('draft-save-confirm-modal');
    const draftConfirmReasonsList = document.getElementById('draft-save-confirm-reasons');
    const draftConfirmBtn = document.getElementById('btn-confirm-draft-save');
    const draftCancelBtn = document.getElementById('btn-cancel-draft-save');
    let pendingDraftSavePayload = null;

    function collectWorkspaceSavePayload() {
        const problemId = workspaceOverlay.getAttribute('data-current-problem-id');
        const titleValue = overlayTitleField ? overlayTitleField.value.trim() : '';
        const canvasHtml = workspaceQuillInstance ? workspaceQuillInstance.root.innerHTML.trim() : '';
        const inputsPayloadList = [];
        const activeCards = Array.from(document.querySelectorAll('.workspace-block-card'));

        activeCards.forEach(card => {
            const baseToken = card.getAttribute('data-token');
            if (!baseToken) return;

            const shuffleSeedValue = card.getAttribute('data-shuffle-seed') || '';
            const deleteBtn = card.querySelector('.btn-delete-workspace-component');
            const indexedTokenString = deleteBtn ? deleteBtn.getAttribute('data-indexed-token') : baseToken;
            const inputValues = {};

            const inputWrappers = card.querySelectorAll('.linked-input-wrapper:not(.row-variable-substitutions .linked-input-wrapper):not(.substitutions-list-container .linked-input-wrapper)');
            inputWrappers.forEach(wrapper => {
                const inputKey = wrapper.getAttribute('data-input-key');
                if (!inputKey) return;

                const boundToken = wrapper.getAttribute('data-bound-token');
                if (boundToken) {
                    inputValues[inputKey] = boundToken;
                } else {
                    const interactiveField = wrapper.querySelector('input, select');
                    if (interactiveField && !interactiveField.classList.contains('val-input-simplify-target')) {
                        inputValues[inputKey] = interactiveField.value.trim();
                    }
                }
            });

            const serializedInputs = getEntityInformation(baseToken, {
                action: 'serialize',
                card,
                inputsCollected: inputValues
            });
            if (serializedInputs && typeof serializedInputs === 'object') {
                Object.assign(inputValues, serializedInputs);
            }

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

                let variablesArray = inputValues['variables']
                    ? String(inputValues['variables']).split(',').map(v => v.trim()).filter(Boolean)
                    : [];

                Object.keys(inputValues).forEach(key => {
                    if (key.startsWith('sub_')) {
                        const impliedVar = key.replace('sub_', '').trim();
                        if (impliedVar && !variablesArray.includes(impliedVar)) {
                            variablesArray.push(impliedVar);
                        }
                    }
                });

                if (variablesArray.length > 0) {
                    inputValues['variables'] = variablesArray.join(', ');
                }
            }

            inputsPayloadList.push({
                token: baseToken,
                sequence_token: indexedTokenString,
                shuffle_seed: shuffleSeedValue,
                inputs: inputValues
            });
        });

        return {
            problemId,
            payload: {
                title: titleValue,
                body_html: canvasHtml,
                inputs: inputsPayloadList
            }
        };
    }

    function hideDraftConfirmModal() {
        if (draftConfirmModal) {
            draftConfirmModal.classList.remove('is-visible');
            draftConfirmModal.style.display = 'none';
            draftConfirmModal.style.visibility = 'hidden';
            draftConfirmModal.style.opacity = '0';
        }
        pendingDraftSavePayload = null;
    }

    function showDraftConfirmModal(reasons) {
        if (!draftConfirmModal || !draftConfirmReasonsList) return;
        draftConfirmReasonsList.innerHTML = '';
        (reasons || []).forEach(reason => {
            const li = document.createElement('li');
            li.textContent = reason;
            li.style.marginBottom = '4px';
            draftConfirmReasonsList.appendChild(li);
        });
        // .modal-overlay CSS defaults to visibility:hidden / opacity:0 until .is-visible
        draftConfirmModal.style.display = 'flex';
        draftConfirmModal.style.visibility = 'visible';
        draftConfirmModal.style.opacity = '1';
        draftConfirmModal.classList.add('is-visible');
    }

    function updateProblemStatusBadge(problemId, status) {
        if (!problemId || !status) return;
        const card = document.querySelector(`.problem-item-row[data-id="${problemId}"], .problem-item-row[data-problem-id="${problemId}"]`);
        const badge = card?.querySelector('.problem-status-badge');
        if (badge) {
            badge.textContent = status;
        }
    }

    async function persistWorkspaceSave({ confirmDraft = false } = {}) {
        const collected = collectWorkspaceSavePayload();
        const problemId = collected.problemId;
        if (!problemId) {
            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-exclamation-triangle" style="color:#ef4444;"></i> Missing problem id`;
            }
            return;
        }

        const payload = {
            ...collected.payload,
            confirm_draft: confirmDraft
        };

        if (saveStatusSpan) {
            saveStatusSpan.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${confirmDraft ? 'Saving draft...' : 'Checking workspace...'}`;
        }
        if (saveDraftBtn) saveDraftBtn.disabled = true;

        try {
            const response = await fetch(`/api/problem/${problemId}/save-workspace/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify(payload)
            });

            let result = {};
            try {
                result = await response.json();
            } catch (_) {
                result = {};
            }

            if (response.ok && result.needs_confirmation) {
                pendingDraftSavePayload = collected.payload;
                showDraftConfirmModal(result.unfinished_reasons || []);
                if (saveStatusSpan) {
                    saveStatusSpan.innerHTML = `<i class="fas fa-info-circle" style="color:#d97706;"></i> Draft confirmation needed`;
                }
                return;
            }

            if (response.ok && result.success) {
                hideDraftConfirmModal();
                updateProblemStatusBadge(problemId, result.problem_status);
                if (saveStatusSpan) {
                    const statusLabel = result.problem_status === 'complete' ? 'Saved as complete' : 'Saved as draft';
                    saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> ${statusLabel}`;
                }
                return;
            }

            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-exclamation-triangle" style="color:#ef4444;"></i> Save Failed`;
            }
            console.error("Workspace save failed:", result.error || response.status);
        } catch (error) {
            console.error("Workspace save network error:", error);
            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-exclamation-triangle" style="color:#ef4444;"></i> Connection Error`;
            }
        } finally {
            resetSaveButtonState();
        }
    }

    if (saveDraftBtn) {
        saveDraftBtn.addEventListener('click', async function() {
            hideDraftConfirmModal();
            await persistWorkspaceSave({ confirmDraft: false });
        });
    }

    if (draftCancelBtn) {
        draftCancelBtn.addEventListener('click', function() {
            hideDraftConfirmModal();
            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Not saved`;
            }
        });
    }

    if (draftConfirmBtn) {
        draftConfirmBtn.addEventListener('click', async function() {
            await persistWorkspaceSave({ confirmDraft: true });
        });
    }

    if (draftConfirmModal) {
        draftConfirmModal.addEventListener('click', function(e) {
            if (e.target === draftConfirmModal) {
                hideDraftConfirmModal();
                if (saveStatusSpan) {
                    saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Not saved`;
                }
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
            
            const inputKey = wrapper.getAttribute('data-input-key') || ''; // <-- Keep track of this key

            // 🌟 MATRIX FIX: If unlinking the main matrix override, reveal local grids again
            if (inputKey === 'linked_matrix') {
                const statusLabel = wrapper.querySelector('.link-status-text');
                if (statusLabel) {
                    statusLabel.textContent = 'Local Grid Active (Unlinked)';
                    statusLabel.style.color = '#64748b';
                }
                const activeCard = linkBtn.closest('.workspace-block-card') || linkBtn.closest('.workspace-component-card');
                if (activeCard) {
                    const localGridGroup = activeCard.querySelector('.matrix-local-grid-config-group');
                    if (localGridGroup) localGridGroup.style.display = 'flex'; // Unhide!
                }
                
                const rawInput = wrapper.querySelector('input, select');
                if (rawInput) rawInput.value = '';

                linkBtn.innerHTML = '<i class="fas fa-link"></i>';
                linkBtn.className = 'btn-input-link-trigger';
                linkBtn.style.color = '#94a3b8';
                linkBtn.style.borderColor = '#cbd5e1';

                if (rawInput) {
                    rawInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
                
                if (activeCard) {
                    const cardId = activeCard.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                    if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
                        dispatchWorkspaceBatchSync(cardId);
                    } else {
                        updateWorkspaceSimulationPreview();
                    }
                } else {
                    updateWorkspaceSimulationPreview();
                }
                return; // 🚀 EXIT EARLY
            }

            // 🎯 🌟 MATRIX FIX: Reset matrix B status text and clear out hidden inputs cleanly
            if (inputKey === 'matrix B') {
                const bStatusLabel = wrapper.querySelector('.matrix-b-status-text');
                if (bStatusLabel) {
                    bStatusLabel.textContent = 'Required: Select a matrix (e.g. matrix2)';
                    bStatusLabel.style.color = '#ef4444';
                }
                
                // Clear the hidden payload backup field value
                const rawInput = wrapper.querySelector('input.val-matrix-b-target, input, select');
                if (rawInput) rawInput.value = '';

                linkBtn.innerHTML = '<i class="fas fa-link"></i>';
                linkBtn.className = 'btn-input-link-trigger';
                linkBtn.style.color = '#94a3b8';
                linkBtn.style.borderColor = '#cbd5e1';

                if (rawInput) {
                    rawInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
                
                const activeCard = linkBtn.closest('.workspace-block-card') || linkBtn.closest('.workspace-component-card');
                if (activeCard) {
                    const cardId = activeCard.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                    if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
                        dispatchWorkspaceBatchSync(cardId);
                    } else {
                        updateWorkspaceSimulationPreview();
                    }
                } else {
                    updateWorkspaceSimulationPreview();
                }
                return; // 🚀 EXIT EARLY
            }
            // 🎯 🌟 ADDED OVERRIDE: Handle unlinking variable substitution rows smoothly
            if (inputKey && inputKey.startsWith('sub_')) {
                wrapper.removeAttribute('data-bound-token');

                // Purge any green pill indicator visual layout node tags out of view
                const pill = wrapper.querySelector('.linked-token-pill');
                if (pill) pill.remove();

                // Re-reveal the editable input box layout surface cleanly
                const rawInput = wrapper.querySelector('.val-substitution-input');
                if (rawInput) {
                    rawInput.value = '';
                    rawInput.style.display = '';
                }

                // Restore the link button look back to standard default slate styling
                linkBtn.innerHTML = '<i class="fas fa-link"></i>';
                linkBtn.className = 'btn-input-link-trigger';
                linkBtn.style.color = '#94a3b8';
                linkBtn.style.borderColor = '#cbd5e1';

                const activeCard = wrapper.closest('.workspace-block-card') || wrapper.closest('.workspace-component-card');
                if (activeCard) {
                    const cardId = activeCard.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                    if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
                        dispatchWorkspaceBatchSync(cardId);
                    } else {
                        updateWorkspaceSimulationPreview();
                    }
                } else {
                    updateWorkspaceSimulationPreview();
                }
                return; // 🚀 EXIT EARLY
            }

            // Safely find the input or label to restore viewports accurately without breaking sub_ layouts
            const labelEl = wrapper.querySelector('label');
            if (labelEl) {
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

            // 🎯 FIX: Notify the layout index compiler that the formula is empty or unlinked 
            if (rawInput) {
                rawInput.dispatchEvent(new Event('input', { bubbles: true }));
            }

            // 🚀 FIX: Pull the parent workspace component block token ID
            const activeCard = linkBtn.closest('.workspace-block-card') || linkBtn.closest('.workspace-component-card');
            if (activeCard) {
                const cardId = activeCard.querySelector('.btn-delete-workspace-component')
                                         ?.getAttribute('data-indexed-token');
                
                if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
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
        const currentCard = linkBtn.closest('.workspace-block-card') || linkBtn.closest('.workspace-component-card');
        const activeCards = Array.from(document.querySelectorAll('.workspace-block-card, .workspace-component-card'));
        
        let acceptedTargetTypes = [targetTypeAttr];
        if (targetTypeAttr === 'double') {
            acceptedTargetTypes.push('integer');
        }

        let availableOptionsHtml = '';
        
        activeCards.forEach(card => {
            if (card === currentCard) return;

            const deleteBtn = card.querySelector('.btn-delete-workspace-component');
            if (!deleteBtn) return;

            const indexedToken = deleteBtn.getAttribute('data-indexed-token'); // e.g., "randInt2"
            const baseArchetype = card.getAttribute('data-token');             // e.g., "rand"

            const tokenDefinition = dynamicVarsTokens.find(t => t.token === baseArchetype);
            if (!tokenDefinition) return;

            let blueprintData = {};
            if (tokenDefinition.format_pattern) {
                try {
                    blueprintData = typeof tokenDefinition.format_pattern === 'string'
                        ? JSON.parse(tokenDefinition.format_pattern)
                        : tokenDefinition.format_pattern;
                } catch (e) {}
            }

            let rawOutput = blueprintData.output || tokenDefinition.output;

            if (!rawOutput) {
                rawOutput = getEntityInformation(baseArchetype, { action: 'getOutputTypes' }) || [];
            }

            const derivedOutputs = Array.isArray(rawOutput) ? rawOutput : [rawOutput];
            const inputKey = wrapper.getAttribute('data-input-key') || '';
            let isCompatible = derivedOutputs.some(type => acceptedTargetTypes.includes(type));
            
            if (inputKey.startsWith('sub_')) {
                isCompatible = derivedOutputs.some(type => ['double', 'integer', 'formula'].includes(type));
            }

            const linkOverride = getEntityInformation(currentCard.getAttribute('data-token'), {
                action: 'isLinkCompatible',
                inputKey,
                targetTypeAttr,
                derivedOutputs,
                acceptedTargetTypes
            });
            if (linkOverride === true) {
                isCompatible = true;
            } else if (targetTypeAttr === 'text' && (inputKey.startsWith('formula_') || currentCard.getAttribute('data-token') === 'graph')) {
                if (derivedOutputs.includes('formula') || derivedOutputs.includes('double') || derivedOutputs.includes('integer')) {
                    isCompatible = true;
                }
            }

            if (isCompatible) {
                availableOptionsHtml += `
                    <button type="button" class="select-link-token-option" data-target-token="&lt;${indexedToken}&gt;" style="width: 100%; text-align: left; padding: 6px 12px; background: none; border: none; font-size: 0.75rem; cursor: pointer; transition: background 0.15s; color: #334155;">
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

    // -------------------------------------------------------------
    // ATTACH SELECTION EVENT DELEGATOR TO DRIVEN DROPDOWN OPTIONS
    // -------------------------------------------------------------
    document.body.addEventListener('click', function(e) {
        const optionBtn = e.target.closest('.select-link-token-option');
        if (!optionBtn) return;

        e.stopPropagation();
        const chosenTokenString = optionBtn.getAttribute('data-target-token'); // e.g., "<formula3>"
        
        // 🎯 FIX: Extract the raw unbracketed ID string (e.g., "formula3") for matching
        const rawTokenId = chosenTokenString.replace(/[<>]/g, '');

        const wrapper = optionBtn.closest('.linked-input-wrapper');
        const linkBtn = wrapper.querySelector('.btn-input-link-trigger');
        
        // 🌟 MATRIX FIX: Identify which input key is being updated
        const inputKey = wrapper.getAttribute('data-input-key') || '';

        // 🌟 MATRIX FIX: Handle main matrix override tracking
        if (inputKey === 'linked_matrix') {
            const statusLabel = wrapper.querySelector('.link-status-text');
            if (statusLabel) {
                statusLabel.textContent = `Linked to: ${rawTokenId}`;
                statusLabel.style.color = '#0284c7';
            }

            // Hide the local grid group container
            const activeCard = wrapper.closest('.workspace-block-card') || wrapper.closest('.workspace-component-card');
            if (activeCard) {
                const localGridGroup = activeCard.querySelector('.matrix-local-grid-config-group');
                if (localGridGroup) localGridGroup.style.display = 'none'; // Hide grid layout
            }

            // Save the value safely directly onto your tracking node
            const actualInputNode = wrapper.querySelector('input, select');
            if (actualInputNode) {
                actualInputNode.value = chosenTokenString;
            }

            // Transform link icon to an active red delete close asset marker
            linkBtn.innerHTML = '<i class="fas fa-times"></i>';
            linkBtn.className = 'btn-input-link-trigger is-linked';
            linkBtn.style.color = '#ef4444';
            linkBtn.style.borderColor = '#fca5a5';

            // Close options dropdown picker instance frame
            wrapper.querySelector('.linkable-tokens-dropdown').style.display = 'none';

            // Bubble a simulated keystroke notice so live variables parser extracts immediately
            if (actualInputNode) {
                actualInputNode.dispatchEvent(new Event('input', { bubbles: true }));
            }

            // Trigger workspace preview validation updates
            if (activeCard) {
                const cardId = activeCard.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
                    dispatchWorkspaceBatchSync(cardId);
                } else {
                    updateWorkspaceSimulationPreview();
                }
            } else {
                updateWorkspaceSimulationPreview();
            }
            return; // 🚀 EXIT EARLY
        }

        // 🎯 🌟 MATRIX FIX: Handle Matrix B tracking and icon conversions gracefully
        if (inputKey === 'matrix B') {
            const bStatusLabel = wrapper.querySelector('.matrix-b-status-text');
            if (bStatusLabel) {
                bStatusLabel.textContent = `Linked to: ${rawTokenId}`;
                bStatusLabel.style.color = '#16a34a';
            }

            const actualInputNode = wrapper.querySelector('input.val-matrix-b-target, input, select');
            if (actualInputNode) {
                actualInputNode.value = chosenTokenString;
            }

            linkBtn.innerHTML = '<i class="fas fa-times"></i>';
            linkBtn.className = 'btn-input-link-trigger is-linked';
            linkBtn.style.color = '#ef4444';
            linkBtn.style.borderColor = '#fca5a5';

            wrapper.querySelector('.linkable-tokens-dropdown').style.display = 'none';

            if (actualInputNode) {
                actualInputNode.dispatchEvent(new Event('input', { bubbles: true }));
            }

            const activeCard = wrapper.closest('.workspace-block-card') || wrapper.closest('.workspace-component-card');
            if (activeCard) {
                const cardId = activeCard.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
                    dispatchWorkspaceBatchSync(cardId);
                } else {
                    updateWorkspaceSimulationPreview();
                }
            } else {
                updateWorkspaceSimulationPreview();
            }
            return; // 🚀 EXIT EARLY: Avoid creating an inline green pill for this custom container layout row!
        }
        // 🎯 🌟 ADDED OVERRIDE: Precise visual layout insertion for Matrix dynamic variable sub rows
        if (inputKey && inputKey.startsWith('sub_')) {
            wrapper.setAttribute('data-bound-token', chosenTokenString);

            // Hide the text field input safely out of the layout row flex stream
            const rawInput = wrapper.querySelector('.val-substitution-input');
            if (rawInput) {
                rawInput.value = chosenTokenString;
                rawInput.style.display = 'none';
            }

            // Create or update an inline visual token indicator pill tailored for this flex spacing
            let pill = wrapper.querySelector('.linked-token-pill');
            if (!pill) {
                pill = document.createElement('span');
                pill.className = 'linked-token-pill';
                pill.setAttribute('data-indexed-token', rawTokenId);
                pill.style.cssText = 'background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; font-family: monospace; font-size: 0.75rem; font-weight: bold; padding: 2px 6px; border-radius: 4px; margin-left: 4px; display: inline-block;';
                
                // Nest it cleanly inside the inner label wrapper div right after the "=" sign label
                const innerFlexContainer = wrapper.firstElementChild;
                if (innerFlexContainer) {
                    innerFlexContainer.appendChild(pill);
                } else if (linkBtn && typeof linkBtn.before === 'function') {
                    linkBtn.before(pill);
                } else if (linkBtn && linkBtn.parentNode) {
                    linkBtn.parentNode.insertBefore(pill, linkBtn);
                } else {
                    wrapper.appendChild(pill);
                }
            }
            pill.textContent = chosenTokenString;

            // Transform the link icon into a red delete cross action button
            linkBtn.innerHTML = '<i class="fas fa-times"></i>';
            linkBtn.className = 'btn-input-link-trigger is-linked';
            linkBtn.style.color = '#ef4444';
            linkBtn.style.borderColor = '#fca5a5';

            // Close the current token picker selection menu drop box viewport
            const dropdown = wrapper.querySelector('.linkable-tokens-dropdown');
            if (dropdown) dropdown.style.display = 'none';

            // Sync alterations upward to layout cache layers
            const activeCard = wrapper.closest('.workspace-block-card') || wrapper.closest('.workspace-component-card');
            if (activeCard) {
                const cardId = activeCard.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
                if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
                    dispatchWorkspaceBatchSync(cardId);
                } else {
                    updateWorkspaceSimulationPreview();
                }
            } else {
                updateWorkspaceSimulationPreview();
            }
            return; // 🚀 EXIT EARLY
        }
        
        // 🎯 FIX: Find the targeted raw input tag control inside this layout wrapper frame
        const actualInputNode = wrapper.querySelector('input, select');
        if (actualInputNode) {
            actualInputNode.value = chosenTokenString; // Sync value to "<formula3>"
        }

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
        if (linkBtn && typeof linkBtn.before === 'function') {
            linkBtn.before(pill);
        } else if (linkBtn && linkBtn.parentNode) {
            linkBtn.parentNode.insertBefore(pill, linkBtn);
        } else {
            wrapper.appendChild(pill);
        }

        // Transform link icon to an active red delete close asset marker
        linkBtn.innerHTML = '<i class="fas fa-times"></i>';
        linkBtn.className = 'btn-input-link-trigger is-linked';
        linkBtn.style.color = '#ef4444';
        linkBtn.style.borderColor = '#fca5a5';

        // Close options dropdown picker instance frame
        wrapper.querySelector('.linkable-tokens-dropdown').style.display = 'none';

        // 🎯 FIX: Bubble a simulated keystroke notice so live variables parser extracts immediately
        if (actualInputNode) {
            actualInputNode.dispatchEvent(new Event('input', { bubbles: true }));
        }
        
        // 🚀 FIX: Find the enclosing formula card element container
        const activeCard = wrapper.closest('.workspace-component-card') || wrapper.closest('.workspace-block-card');
        if (activeCard) {
            const cardId = activeCard.querySelector('.btn-delete-workspace-component')
                                     ?.getAttribute('data-indexed-token');
            
            if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
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

            // 🎯 FIX: Ignore 'change' events on text and number inputs. 
            // The 'input' event catches these changes in real-time, making 'change' redundant.
            if (e.type === 'change' && (target.type === 'text' || target.type === 'number' || target.tagName === 'TEXTAREA')) {
                return;
            }

            const card = target.closest('.workspace-component-card') || target.closest('.workspace-block-card');
            if (!card) return;

            const cardId = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
            if (!cardId) return;


            if (debouncedNetworkDispatches[cardId]) {
                clearTimeout(debouncedNetworkDispatches[cardId]);
            }

            debouncedNetworkDispatches[cardId] = setTimeout(() => {
                delete debouncedNetworkDispatches[cardId];


                if (typeof dispatchWorkspaceBatchSync === 'function') {
                    dispatchWorkspaceBatchSync(cardId);
                } else {
                    updateWorkspaceSimulationPreview();
                }
            }, 400);
        }

        document.addEventListener('input', triggerLiveSync);
        document.addEventListener('change', triggerLiveSync);
    })();


    /**
     * 🎨 Unified Graph Rendering Engine Coordinator
     * Safely initializes or updates a functionPlot canvas element.
     * 
     * @param {string} targetCanvasId - The absolute DOM selector ID of the target canvas div
     * @param {Object} graphConfig - The structured backend JSON configuration packet
     */
    function renderGraphComponentCanvas(targetCanvasId, graphConfig) {
        if (!graphConfig || graphConfig.archetype !== 'graph') return;

        // 1. Grab the direct, native browser-compiled instance from window scope
        const activePlotEngine = window.functionPlot || (typeof functionPlot !== 'undefined' ? functionPlot : null);
        if (!activePlotEngine) return;

        const xMin = graphConfig.bounds?.x_range?.min ?? -5;
        const xMax = graphConfig.bounds?.x_range?.max ?? 5;
        const xStep = graphConfig.bounds?.x_range?.step ?? 1;

        const yMin = graphConfig.bounds?.y_range?.min ?? -5;
        const yMax = graphConfig.bounds?.y_range?.max ?? 5;
        const yStep = graphConfig.bounds?.y_range?.step ?? 1;

        // 🧮 Compute uniform tick alignment arrays
        const xTicks = [];
        for (let val = xMin; val <= xMax; val = parseFloat((val + xStep).toFixed(4))) xTicks.push(val);
        
        const yTicks = [];
        for (let val = yMin; val <= yMax; val = parseFloat((val + yStep).toFixed(4))) yTicks.push(val);

        const showGrid = graphConfig.visualization?.show_grid_overlay ?? true;

        // 🗺️ Map formula items cleanly to uniform polylines
        const formattedFnEntries = (graphConfig.formulas || []).map(formula => ({
            fn: formula,
            graphType: 'polyline',
            nSamples: 250
        }));

        // 🚀 Step 1: Initialize/Update the plot
        const chartInstance = activePlotEngine({
            target: `#${targetCanvasId}`,
            width: 340,
            height: 240,
            disableZoom: true,
            grid: showGrid,
            xAxis: {
                domain: [xMin, xMax],
                label: graphConfig.axis_names?.[0] || 'x',
                ticks: xTicks,
                tickValues: xTicks
            },
            yAxis: {
                domain: [yMin, yMax],
                label: graphConfig.axis_names?.[1] || 'y',
                ticks: yTicks,
                tickValues: yTicks
            },
            data: formattedFnEntries
        });

        // 🚀 Step 2: Clear cached configuration arrays to bypass the initialization cache locks
        if (chartInstance && chartInstance.meta) {
            if (chartInstance.options) {
                chartInstance.options.data = formattedFnEntries;
            }
            if (chartInstance.meta.xAxis) {
                chartInstance.meta.xAxis.tickValues(xTicks);
                chartInstance.meta.xAxis.tickSize(showGrid ? -chartInstance.meta.height : 0);
            }
            if (chartInstance.meta.yAxis) {
                chartInstance.meta.yAxis.tickValues(yTicks);
                chartInstance.meta.yAxis.tickSize(showGrid ? -chartInstance.meta.width : 0);
            }
            chartInstance.draw();
        }

        return chartInstance;
    }
});