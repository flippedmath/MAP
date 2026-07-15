import { processEntity as randIntProcessor } from './entities/randInt.js';
import { processEntity as randProcessor } from './entities/rand.js';
import { processEntity as primeFactorsProcessor } from './entities/primeFactors.js';
import { processEntity as formulaProcessor } from './entities/formula.js';
import { processEntity as matrixProcessor } from './entities/matrix.js';
import { processEntity as matrixResultByIndexProcessor } from './entities/matrixResultByIndex.js';
import { processEntity as graphProcessor } from './entities/graph.js';
import {
    processEntity as slopeFieldGraphProcessor,
    renderSlopeFieldCanvas
} from './entities/slopeFieldGraph.js';
import { processEntity as numAnswerProcessor } from './entities/numAnswer.js';
import { processEntity as shortAnswerProcessor } from './entities/shortAnswer.js';
import { processEntity as arrayMatchingUnorderedProcessor } from './entities/arrayMatchingUnordered.js';
import { processEntity as multipleChoiceAnswerProcessor } from './entities/multipleChoiceAnswer.js';
import { ensureLatexRenderBox } from './entities/helpers.js';

// Map tokens directly to their synchronous entity processors
const ENTITY_REGISTRY = {
    'randInt': randIntProcessor,
    'rand': randProcessor,
    'primeFactors': primeFactorsProcessor,
    'formula': formulaProcessor,
    'matrix': matrixProcessor,
    'matrixResultByIndex': matrixResultByIndexProcessor,
    'graph': graphProcessor,
    'slopeFieldGraph': slopeFieldGraphProcessor,
    'numAnswer': numAnswerProcessor,
    'shortAnswer': shortAnswerProcessor,
    'arrayMatchingUnordered': arrayMatchingUnorderedProcessor,
    'multipleChoiceAnswer': multipleChoiceAnswerProcessor,
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

    // Ephemeral student answers from Workspace Simulation Preview only.
    // Never included in save-workspace payloads; cleared when closing/reloading the overlay.
    // Real student-answer persistence belongs elsewhere (future assessment flow).
    const previewStudentAnswers = {};
    let previewGradeRefreshTimer = null;
    let previewGradeRequestId = 0;

    function clearPreviewStudentAnswers() {
        Object.keys(previewStudentAnswers).forEach((key) => {
            delete previewStudentAnswers[key];
        });
    }

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
                const tokenSourceArray = isVariable ? dynamicVarsTokens : answerFieldsTokens;
                const matchingTokenData = tokenSourceArray.find(item => item.token === tokenSelected);
                const defaultPoints = matchingTokenData?.points_default ?? 1.0;
                createNewBlockInstanceUI(tokenSelected, targetContainer, {}, defaultPoints);
                
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
                        if (Array.isArray(segment.output_types) && segment.output_types.length) {
                            latestCard.setAttribute('data-output-types', segment.output_types.join(','));
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
    function createNewBlockInstanceUI(token, containerElement, savedValues = {}, points = undefined, overrideSequenceToken = undefined) {

        const card = document.createElement('div');
        card.className = 'workspace-component-card workspace-block-card';
        card.setAttribute('data-token', token);
        card.style.cssText = 'background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; position: relative;';

        const isVariable = dynamicVarsTokens.some(item => item.token === token);
        const headerColor = isVariable ? '#0284c7' : '#16a34a';
        const tokenSourceArray = isVariable ? dynamicVarsTokens : answerFieldsTokens;
        const matchingTokenData = tokenSourceArray.find(item => item.token === token);
        const resolvedPoints = (points !== undefined && points !== null && points !== '')
            ? Number(points)
            : Number(matchingTokenData?.points_default ?? 1.0);
        const safePoints = Number.isFinite(resolvedPoints) ? resolvedPoints : 1.0;

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

        const pointsBadgeHtml = isVariable
            ? `<span style="font-size: 0.77rem; background:#e0f2fe; color:#0369a1; padding:1px 6px; border-radius:10px; font-weight:500;">Variable</span>`
            : `<label style="font-size: 0.72rem; background:#dcfce7; color:#166534; padding:2px 6px; border-radius:10px; font-weight:500; display:inline-flex; align-items:center; gap:4px; cursor:pointer;" title="Points value for this answer field">
                    <input type="number" min="0" step="any" class="val-answer-field-points" value="${safePoints}" style="width:48px; font-size:0.72rem; padding:1px 4px; border:1px solid #86efac; border-radius:4px; background:#fff; color:#166534; font-weight:600;">
                    Pts
               </label>`;

        card.setAttribute('data-points', String(safePoints));

        card.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px dashed #e2e8f0; padding-bottom: 6px; margin-bottom: 4px;">
                <span style="font-weight: 600; font-size: 0.85rem; color: ${headerColor};"><i class="fas fa-cube"></i> &lt;${indexedTokenString}&gt;</span>
                <div style="display: flex; align-items: center; gap: 8px;">
                    
                    ${!getEntityInformation(token, { action: 'hideRefreshButton' }) ? `
                        <button type="button" class="btn-refresh-workspace-component-value" title="${token === 'multipleChoiceAnswer' ? 'Re-randomize preview choice order' : 'Shuffle simulation instance sample value'}" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.8rem; padding: 2px 4px; display: flex; align-items: center; justify-content: center; transition: color 0.15s, transform 0.15s;">
                            <i class="fas fa-redo-alt"></i>
                        </button>
                    ` : ''}

                    ${pointsBadgeHtml}
                    
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
                if (e.target.classList.contains('val-answer-field-points')) {
                    const parsed = parseFloat(e.target.value);
                    if (Number.isFinite(parsed)) {
                        card.setAttribute('data-points', String(parsed));
                    }
                    scheduleWorkspacePreviewGradeRefresh(200);
                }
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
    function normalizeWorkspaceLatexInput(rawLatex) {
        if (rawLatex == null) return '';
        let latex = String(rawLatex).trim();
        // Allow users to paste $...$ or $$...$$ wrappers; Quill/KaTeX expect bare math.
        if (/^\$\$[\s\S]*\$\$$/.test(latex)) {
            latex = latex.slice(2, -2).trim();
        } else if (/^\$[\s\S]*\$$/.test(latex)) {
            latex = latex.slice(1, -1).trim();
        }
        return latex;
    }

    function updateWorkspaceSimulationPreview() {
        if (window.isHydratingWorkspace || window.__workspacePreviewQuiet) return; // 🛑 Halt during hydration / Quill HTML load
        const renderTarget = document.getElementById('simulation-render-target');
        if (!renderTarget) {
            console.warn("Simulation preview aborted: #simulation-render-target is missing.");
            return;
        }

        // Preserve in-progress preview answers before the DOM is replaced
        capturePreviewAnswersFromDom(renderTarget);

        let canvasContent = workspaceQuillInstance ? getWorkspaceQuillHtmlForSave() : '';

        if (!canvasContent || canvasContent === '<p><br></p>') {
            renderTarget.innerHTML = '<p style="color: #94a3b8; font-style: italic; margin: 0;">Interactive layout testing view builds dynamically here...</p>';
            scheduleWorkspacePreviewGradeRefresh();
            return;
        }

        if (typeof renderPreviewCanvasMarkup === 'function') {
            renderPreviewCanvasMarkup(canvasContent, renderTarget);
        } else {
            console.warn("Simulation preview aborted: renderPreviewCanvasMarkup is not available.");
        }
        scheduleWorkspacePreviewGradeRefresh();
    }

    function capturePreviewAnswersFromDom(root) {
        if (!root) return;
        // Group by data-token so orphaned checkboxes (broken markup) still count
        const byToken = {};
        root.querySelectorAll('.preview-mc-choice').forEach((el) => {
            const tokenKey = el.getAttribute('data-token') || '';
            if (!tokenKey) return;
            if (!byToken[tokenKey]) byToken[tokenKey] = [];
            if (el.checked) {
                const id = el.getAttribute('data-option-id') || el.value;
                if (id) byToken[tokenKey].push(id);
            }
        });
        Object.entries(byToken).forEach(([tokenKey, selected]) => {
            previewStudentAnswers[tokenKey] = { selected };
        });
        // Also keep wrappers that exist but had zero choices scanned (clear them)
        root.querySelectorAll('.simulated-mc-wrapper').forEach((wrap) => {
            const tokenKey = wrap.getAttribute('data-token') || '';
            if (!tokenKey || Object.prototype.hasOwnProperty.call(byToken, tokenKey)) return;
            previewStudentAnswers[tokenKey] = { selected: [] };
        });
        root.querySelectorAll('.preview-num-answer-input').forEach((input) => {
            const tokenKey = input.getAttribute('data-token') || '';
            if (!tokenKey) return;
            previewStudentAnswers[tokenKey] = { value: input.value };
        });
        root.querySelectorAll('.preview-short-answer-input').forEach((input) => {
            const tokenKey = input.getAttribute('data-token') || '';
            if (!tokenKey) return;
            previewStudentAnswers[tokenKey] = { value: input.value };
        });
        root.querySelectorAll('.preview-array-matching-input').forEach((input) => {
            const tokenKey = input.getAttribute('data-token') || '';
            if (!tokenKey) return;
            previewStudentAnswers[tokenKey] = { value: input.value };
        });
    }

    function scheduleWorkspacePreviewGradeRefresh(delayMs = 280) {
        if (previewGradeRefreshTimer) clearTimeout(previewGradeRefreshTimer);
        previewGradeRefreshTimer = setTimeout(() => {
            previewGradeRefreshTimer = null;
            refreshWorkspacePreviewGrades();
        }, delayMs);
    }

    function collectAnswerFieldEntitiesForGrading() {
        const entities = [];
        const answerCards = inputsContainer
            ? inputsContainer.querySelectorAll('.workspace-block-card')
            : document.querySelectorAll('#sidebar-inputs-list .workspace-block-card');

        answerCards.forEach(card => {
            const baseToken = card.getAttribute('data-token');
            if (!baseToken) return;
            if (!answerFieldsTokens.some(item => item.token === baseToken)) return;

            const delBtn = card.querySelector('.btn-delete-workspace-component');
            const sequenceToken = delBtn?.getAttribute('data-indexed-token') || baseToken;
            const matchingMeta = answerFieldsTokens.find(item => item.token === baseToken);
            const label = matchingMeta?.name
                ? `${matchingMeta.name} (<${sequenceToken}>)`
                : `<${sequenceToken}>`;

            const inputValues = {};
            card.querySelectorAll('.linked-input-wrapper:not(.row-variable-substitutions .linked-input-wrapper):not(.substitutions-list-container .linked-input-wrapper)').forEach(wrapper => {
                const inputKey = wrapper.getAttribute('data-input-key');
                if (!inputKey) return;
                const boundToken = wrapper.getAttribute('data-bound-token');
                if (boundToken) {
                    let cleanToken = boundToken.replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
                    if (!cleanToken.startsWith('<')) cleanToken = `<${cleanToken}`;
                    if (!cleanToken.endsWith('>')) cleanToken = `${cleanToken}>`;
                    inputValues[inputKey] = cleanToken;
                } else {
                    const interactiveField = wrapper.querySelector('input, select, textarea');
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

            const rawPts = card.querySelector('.val-answer-field-points')?.value;
            let points = parseFloat(rawPts);
            if (!Number.isFinite(points)) {
                points = parseFloat(card.getAttribute('data-points'));
            }
            if (!Number.isFinite(points)) points = 0;

            entities.push({
                token: sequenceToken,
                sequence_token: sequenceToken,
                archetype: baseToken,
                label,
                points,
                inputs: inputValues,
                simulated_value: card.getAttribute('data-simulated-value') || ''
            });
        });

        return entities;
    }

    function renderWorkspacePreviewGradeResults(data) {
        const target = document.getElementById('workspace-preview-grade-target');
        if (!target) return;

        const items = Array.isArray(data?.items) ? data.items : [];
        if (!items.length) {
            target.innerHTML = '<p style="color: #94a3b8; font-style: italic; margin: 0;">No answer input fields in this problem yet.</p>';
            return;
        }

        const rows = items.map(item => {
            const earned = Number(item.earned) || 0;
            const max = Number(item.max) || 0;
            const detail = item.detail ? `<div style="font-size:0.72rem; color:#64748b; margin-top:2px;">${escapeHtmlText(item.detail)}</div>` : '';
            const label = escapeHtmlText(item.label || item.token || 'Answer field');
            return `
                <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start; padding:8px 0; border-bottom:1px solid #e2e8f0;">
                    <div style="min-width:0;">
                        <div style="font-size:0.85rem; font-weight:600; color:#0f172a;">${label}</div>
                        ${detail}
                    </div>
                    <div style="font-size:0.85rem; font-weight:700; color:#166534; white-space:nowrap;">${formatGradeNumber(earned)} / ${formatGradeNumber(max)}</div>
                </div>
            `;
        }).join('');

        const earnedTotal = Number(data.earned_total) || 0;
        const maxTotal = Number(data.max_total) || 0;
        target.innerHTML = `
            <div>${rows}</div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px; padding-top:10px; border-top:2px solid #cbd5e1;">
                <span style="font-size:0.85rem; font-weight:700; color:#334155; text-transform:uppercase; letter-spacing:0.03em;">Total</span>
                <span style="font-size:1rem; font-weight:800; color:#0f172a;">${formatGradeNumber(earnedTotal)} / ${formatGradeNumber(maxTotal)}</span>
            </div>
        `;
    }

    function formatGradeNumber(n) {
        if (!Number.isFinite(n)) return '0';
        if (Number.isInteger(n)) return String(n);
        return String(Math.round(n * 1000) / 1000);
    }

    function escapeHtmlText(val) {
        return String(val)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function refreshWorkspacePreviewGrades() {
        const target = document.getElementById('workspace-preview-grade-target');
        const problemId = workspaceOverlay.getAttribute('data-current-problem-id');
        // Capture latest preview choices before grading (important for multi-select MC)
        const renderTarget = document.getElementById('simulation-render-target');
        capturePreviewAnswersFromDom(renderTarget);
        const entities = collectAnswerFieldEntitiesForGrading();
        // Sibling dynamic variables (and all cards) so linked answer keys can resolve
        const all_entities = typeof serializeAllWorkspaceEntities === 'function'
            ? serializeAllWorkspaceEntities()
            : entities;

        if (!target) return;
        if (!problemId) {
            target.innerHTML = '<p style="color: #94a3b8; font-style: italic; margin: 0;">Open a problem to grade preview answers.</p>';
            return;
        }
        if (!entities.length) {
            renderWorkspacePreviewGradeResults({ items: [], earned_total: 0, max_total: 0 });
            return;
        }

        const student_answers = {};
        entities.forEach(entity => {
            const key = entity.sequence_token || entity.token;
            const stored = previewStudentAnswers[key];
            student_answers[key] = (stored === undefined) ? null : stored;
        });

        const requestId = ++previewGradeRequestId;
        try {
            const response = await fetch(`/api/problem/${problemId}/grade-workspace-preview/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({ entities, all_entities, student_answers })
            });
            const data = await response.json();
            if (requestId !== previewGradeRequestId) return;
            if (!response.ok || data.success === false) {
                target.innerHTML = `<p style="color:#dc2626; margin:0; font-size:0.85rem;">${escapeHtmlText(data.error || 'Grading request failed.')}</p>`;
                return;
            }
            renderWorkspacePreviewGradeResults(data);
        } catch (err) {
            if (requestId !== previewGradeRequestId) return;
            console.error('Preview grading failed:', err);
            target.innerHTML = '<p style="color:#dc2626; margin:0; font-size:0.85rem;">Grading request failed.</p>';
        }
    }

    // 🎯 HELPER SUB-ROUTINE: HANDLES REGEX STRING REPLACEMENT & KATEX PARSING
    function renderPreviewCanvasMarkup(canvasContent, renderTarget) {
        const pendingGraphRenders = [];
        let previewGraphSeq = 0;
        
        const tempContainer = document.createElement('div');
        tempContainer.innerHTML = canvasContent;

        // Strip text-editor formula nodes and transition them into preview layouts
        const formulaNodes = tempContainer.querySelectorAll('.ql-formula');
        formulaNodes.forEach(formula => {
            const latexValue = normalizeWorkspaceLatexInput(formula.getAttribute('data-value') || '');
            const mathSpan = document.createElement('span');
            mathSpan.className = 'preview-static-latex';
            mathSpan.textContent = latexValue;
            formula.parentNode.replaceChild(mathSpan, formula);
        });

        // Ensure nested table embeds render their grid in the preview (from data-value + live HTML)
        tempContainer.querySelectorAll('.ql-workspace-nested-table').forEach(node => {
            syncWorkspaceNestedTableNode(node);
            const config = parseNestedTableConfig(node.getAttribute('data-value') || '');
            // Rebuild grid for preview so BR / size / latex from data-value are authoritative
            config.cells = (config.cells || []).map(row =>
                (row || []).map(cell => ensureNestedCellHtmlLineBreaks(cell))
            );
            const table = document.createElement('table');
            table.className = 'ql-nested-table-inner';
            if (config.noBorder) table.classList.add('no-border');
            if (config.expandEntities) {
                table.classList.add('ql-table-expand-entities');
                table.setAttribute('data-expand-entities', 'true');
            } else {
                table.classList.remove('ql-table-expand-entities');
                table.setAttribute('data-expand-entities', 'false');
            }
            for (let r = 0; r < config.rows; r++) {
                const tr = document.createElement('tr');
                for (let c = 0; c < config.cols; c++) {
                    const td = document.createElement('td');
                    fillNestedTdFromHtml(td, (config.cells[r] && config.cells[r][c]) || '');
                    td.removeAttribute('contenteditable');
                    tr.appendChild(td);
                }
                table.appendChild(tr);
            }
            node.innerHTML = '';
            node.appendChild(table);
            applyNestedInnerLayout(table, config.colWidths, config.rowHeights);
            // Expand row heights to fit multi-line content in preview
            const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
            const heights = rows.map(tr => {
                let contentH = NESTED_MIN_ROW;
                Array.from(tr.children).filter(el => el.matches('td, th')).forEach(td => {
                    contentH = Math.max(contentH, Math.ceil(td.scrollHeight) || NESTED_MIN_ROW);
                });
                return Math.max(NESTED_MIN_ROW, contentH);
            });
            if (heights.some((h, i) => h !== (config.rowHeights[i] || 0))) {
                config.rowHeights = heights;
                applyNestedInnerLayout(table, config.colWidths, config.rowHeights);
            }
            hydrateNestedLatexSpans(node);
        });

        // Nested latex outside rebuilt path (if any)
        tempContainer.querySelectorAll('.workspace-nested-latex').forEach(span => {
            const latexValue = normalizeWorkspaceLatexInput(span.getAttribute('data-value') || '');
            const mathSpan = document.createElement('span');
            mathSpan.className = 'preview-static-latex';
            mathSpan.textContent = latexValue;
            span.parentNode.replaceChild(mathSpan, span);
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
                const isVar = inDynamicVarsList || isFormulaCondition || ['randInt', 'rand', 'primeFactors', 'graph', 'matrix', 'matrixResultByIndex'].includes(baseArchetypeToken);

                if (isVar) {
                    let displayVal = formulaLiveLatexCache[cleanToken];

                    // Prefer server/cached LaTeX; never treat valid latex "0" as missing
                    const isServerValueValid = displayVal !== undefined && displayVal !== null && displayVal !== '' && displayVal !== '???';

                    if (baseArchetypeToken === 'graph') {
                        // Graph preview needs the JSON manifest (evaluated_output), not latex_output
                        // which is only a placeholder like "[Graph Component]".
                        if (card) {
                            displayVal = card.getAttribute('data-simulated-value')
                                || evaluateSingleCardOutput(card, cleanToken);
                        }
                    } else if (baseArchetypeToken === 'formula' || baseArchetypeToken === 'matrix' || baseArchetypeToken === 'matrixResultByIndex') {
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
                        }
                        // Missing card is expected during early Quill paste before segments land —
                        // fall through to token/cache fallbacks without console noise.
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
                        renderGraphComponentCanvas,
                        previewInstanceId: `live-preview-canvas-${cleanToken}-${++previewGraphSeq}`,
                        registerPreviewGraph: (job) => {
                            if (job) pendingGraphRenders.push(job);
                        }
                    });
                    if (previewHtml) {
                        return previewHtml;
                    }

                    // 🎯 STEP 3: Fallback for all other standard variable badges (rand, randInt, etc)
                    return `<span class="simulated-math-variable-badge" style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.9rem; display: inline-block; margin: 0 2px;">${displayVal}</span>`;
                
                } else if (answerFieldsTokens.some(i => i.token === baseArchetypeToken)) {
                    // Prefer entity-specific preview (e.g. slopeFieldGraph) over generic stub
                    let answerDisplayVal = null;
                    if (card) {
                        answerDisplayVal = card.getAttribute('data-simulated-value')
                            || formulaLiveLatexCache[cleanToken]
                            || null;
                    }
                    const answerPreviewHtml = getEntityInformation(baseArchetypeToken, {
                        action: 'renderPreviewToken',
                        displayVal: answerDisplayVal,
                        cleanToken,
                        card,
                        renderGraphComponentCanvas,
                        renderSlopeFieldCanvas,
                        previewInstanceId: `live-preview-canvas-${cleanToken}-${++previewGraphSeq}`,
                        registerPreviewGraph: (job) => {
                            if (job) pendingGraphRenders.push(job);
                        },
                        getEntityInformation,
                        evaluateSingleCardOutput,
                        formulaLiveLatexCache,
                        initialValue: (() => {
                            const stored = previewStudentAnswers[cleanToken];
                            if (!stored || typeof stored !== 'object') return '';
                            if (Array.isArray(stored.selected)) return stored;
                            if (Array.isArray(stored.marks)) return stored;
                            if (stored.value != null) return stored.value;
                            return '';
                        })()
                    });
                    if (answerPreviewHtml) {
                        return answerPreviewHtml;
                    }
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

        // Quill wraps tokens in <p>. Block widgets (MC lists, graphs) cannot live inside
        // <p> without the browser closing the paragraph early — hoist them out first.
        hoistBlockPreviewsOutOfParagraphs(renderTarget);

        // Apply persisted table col/row sizes so preview images constrain like the editor
        Array.from(renderTarget.querySelectorAll('table')).forEach(table => {
            if (table.classList.contains('ql-nested-table-inner') || table.closest('.ql-workspace-nested-table')) {
                const embed = table.closest('.ql-workspace-nested-table');
                if (embed) {
                    const cfg = parseNestedTableConfig(embed.getAttribute('data-value') || '');
                    applyNestedInnerLayout(table, cfg.colWidths, cfg.rowHeights);
                    if (cfg.expandEntities) {
                        table.classList.add('ql-table-expand-entities');
                        table.setAttribute('data-expand-entities', 'true');
                    } else {
                        table.classList.remove('ql-table-expand-entities');
                        table.setAttribute('data-expand-entities', 'false');
                    }
                }
                return;
            }
            reapplyWorkspaceTableLayout(table);
            if (table.getAttribute('data-expand-entities') === 'false') {
                table.classList.remove('ql-table-expand-entities');
            } else {
                table.classList.add('ql-table-expand-entities');
                table.setAttribute('data-expand-entities', 'true');
            }
        });
        renderTarget.querySelectorAll('table td img, table th img').forEach(img => {
            img.style.maxWidth = '100%';
            img.style.height = 'auto';
            img.style.width = 'auto';
            img.style.display = 'block';
        });

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

        // Paint graphs only after preview DOM exists (setTimeout-from-replace races with tables)
        flushPreviewGraphRenders(renderTarget, pendingGraphRenders);
        bindPreviewNumAnswerInputs(renderTarget);
        bindPreviewShortAnswerInputs(renderTarget);
        bindPreviewArrayMatchingInputs(renderTarget);
        bindPreviewMultipleChoiceInputs(renderTarget);

        // After entities/KaTeX/graphs paint: expand flagged tables, or shrink into fixed cells
        applyPreviewTableEntityFitModes(renderTarget);
        // Remeasure once plot SVG layout settles
        setTimeout(() => applyPreviewTableEntityFitModes(renderTarget), 40);
        setTimeout(() => applyPreviewTableEntityFitModes(renderTarget), 200);
    }

    function bindPreviewNumAnswerInputs(root) {
        if (!root) return;
        root.querySelectorAll('.preview-num-answer-input').forEach((input) => {
            if (input.dataset.previewNumBound === '1') return;
            input.dataset.previewNumBound = '1';
            const tokenKey = input.getAttribute('data-token') || '';
            const sync = () => {
                if (!tokenKey) return;
                previewStudentAnswers[tokenKey] = { value: input.value };
                scheduleWorkspacePreviewGradeRefresh(180);
            };
            input.addEventListener('input', sync);
            input.addEventListener('change', sync);
        });
    }

    function bindPreviewShortAnswerInputs(root) {
        if (!root) return;
        root.querySelectorAll('.preview-short-answer-input').forEach((input) => {
            if (input.dataset.previewShortBound === '1') return;
            input.dataset.previewShortBound = '1';
            const tokenKey = input.getAttribute('data-token') || '';
            const sync = () => {
                if (!tokenKey) return;
                previewStudentAnswers[tokenKey] = { value: input.value };
                scheduleWorkspacePreviewGradeRefresh(180);
            };
            input.addEventListener('input', sync);
            input.addEventListener('change', sync);
        });
    }

    function bindPreviewArrayMatchingInputs(root) {
        if (!root) return;
        root.querySelectorAll('.preview-array-matching-input').forEach((input) => {
            if (input.dataset.previewArrayMatchingBound === '1') return;
            input.dataset.previewArrayMatchingBound = '1';
            const tokenKey = input.getAttribute('data-token') || '';
            const sync = () => {
                if (!tokenKey) return;
                previewStudentAnswers[tokenKey] = { value: input.value };
                scheduleWorkspacePreviewGradeRefresh(180);
            };
            input.addEventListener('input', sync);
            input.addEventListener('change', sync);
        });
    }

    function bindPreviewMultipleChoiceInputs(root) {
        if (!root) return;

        const collectSelectedForToken = (tokenKey) => Array.from(root.querySelectorAll('.preview-mc-choice'))
            .filter((el) => el.getAttribute('data-token') === tokenKey && el.checked)
            .map((el) => el.getAttribute('data-option-id') || el.value)
            .filter(Boolean);

        const syncChoice = (choice) => {
            const tokenKey = choice?.getAttribute('data-token') || '';
            if (!tokenKey) return;
            previewStudentAnswers[tokenKey] = { selected: collectSelectedForToken(tokenKey) };
            scheduleWorkspacePreviewGradeRefresh(180);
        };

        // Event delegation on the preview root so choices still grade even if
        // nested block HTML (e.g. a graph) previously broke the MC wrapper.
        if (root.dataset.previewMcDelegated !== '1') {
            root.dataset.previewMcDelegated = '1';
            root.addEventListener('change', (e) => {
                const choice = e.target.closest?.('.preview-mc-choice');
                if (!choice || !root.contains(choice)) return;
                syncChoice(choice);
            });
            root.addEventListener('click', (e) => {
                const row = e.target.closest?.('.mc-option-preview-row');
                if (!row || !root.contains(row)) return;
                const choice = row.querySelector('.preview-mc-choice');
                if (!choice) return;

                // Don't toggle from interactions inside the embedded graph itself
                const inGraph = e.target.closest?.(
                    '.live-preview-graph-canvas, .simulated-live-graph-preview-container svg, .simulated-live-slope-preview-container'
                );
                if (!inGraph && e.target !== choice) {
                    if (choice.type === 'radio') {
                        choice.checked = true;
                    } else {
                        choice.checked = !choice.checked;
                    }
                }
                setTimeout(() => syncChoice(choice), 0);
            });
        }
        // Seed stored answers from any pre-checked restore for each MC instance
        root.querySelectorAll('.simulated-mc-wrapper').forEach((wrap) => {
            const tokenKey = wrap.getAttribute('data-token') || '';
            if (!tokenKey) return;
            previewStudentAnswers[tokenKey] = { selected: collectSelectedForToken(tokenKey) };
        });
    }

    /**
     * Lift block-level preview widgets out of Quill <p> wrappers so nested graphs
     * and MC option lists stay intact.
     */
    function hoistBlockPreviewsOutOfParagraphs(root) {
        if (!root) return;
        const blockSelector = [
            '.simulated-mc-wrapper',
            '.simulated-live-graph-preview-container',
            '.simulated-live-slope-preview-container'
        ].join(', ');

        root.querySelectorAll(blockSelector).forEach((block) => {
            const p = block.closest('p');
            if (!p || !p.parentNode || !p.contains(block)) return;
            // Only hoist when the paragraph is an ancestor of the block
            if (block.parentElement !== p && !p.contains(block.parentElement)) return;
            p.parentNode.insertBefore(block, p);
            // Drop empty leftovers from Quill's paragraph shell
            if (!p.textContent.trim() && p.children.length === 0) {
                p.remove();
            }
        });
    }

    /**
     * Paint deferred graph previews into the live simulation DOM, sizing to table cells
     * when expand-entities is off, and using full plot size when expand is on.
     */
    function flushPreviewGraphRenders(root, jobs) {
        if (!root || !Array.isArray(jobs) || jobs.length === 0) return;

        jobs.forEach((job) => {
            if (!job || !job.canvasId || !job.graphConfig) return;
            const canvasEl = document.getElementById(job.canvasId);
            if (!canvasEl) return;

            const hostTd = canvasEl.closest('td, th');
            const hostTable = hostTd ? hostTd.closest('table') : null;
            const shouldExpand = hostTable ? previewTableShouldExpandEntities(hostTable) : true;
            const container = canvasEl.closest('.simulated-live-graph-preview-container, .simulated-live-slope-preview-container');

            let width = Number(job.width) > 0 ? Math.round(job.width) : 340;
            if (hostTd) {
                const cs = window.getComputedStyle(hostTd);
                const padX = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
                const avail = Math.floor((hostTd.clientWidth || 0) - padX - 12);
                if (shouldExpand) {
                    // Prefer full plot; cell will grow via expandPreviewTablesForEntities
                    width = Number(job.width) > 0 ? Math.round(job.width) : 340;
                } else if (avail > 0) {
                    width = Math.max(100, Math.min(width, avail));
                }
            } else if (canvasEl.closest('.simulated-mc-wrapper') && !(Number(job.width) > 0)) {
                // Default slightly smaller when embedded as an MC choice
                width = 280;
            }

            const height = Number(job.height) > 0
                ? Math.round(job.height)
                : Math.max(100, Math.round(width * (240 / 340)));
            canvasEl.style.width = '100%';
            if (container) {
                container.style.maxWidth = `${width + 8}px`;
                container.style.width = '100%';
            }

            try {
                if (job.kind === 'slopeFieldGraph' || job.graphConfig?.archetype === 'slopeFieldGraph') {
                    // Let the host grow for equation label + optional instruction text
                    canvasEl.style.height = 'auto';
                    canvasEl.style.minHeight = '';
                    canvasEl.style.overflow = 'visible';
                    canvasEl.innerHTML = '';
                    const tokenKey = job.cleanToken || '';
                    const stored = tokenKey ? previewStudentAnswers[tokenKey] : null;
                    const initialMarks = (stored && Array.isArray(stored.marks)) ? stored.marks : [];
                    renderSlopeFieldCanvas(canvasEl, job.graphConfig, {
                        mode: 'student',
                        width,
                        height,
                        initialMarks,
                        onStudentAnswerChange: (marks) => {
                            if (!tokenKey) return;
                            previewStudentAnswers[tokenKey] = { marks: Array.isArray(marks) ? marks : [] };
                            scheduleWorkspacePreviewGradeRefresh(180);
                        }
                    });
                } else {
                    canvasEl.style.height = `${height}px`;
                    canvasEl.style.minHeight = `${height}px`;
                    canvasEl.innerHTML = '';
                    renderGraphComponentCanvas(job.canvasId, job.graphConfig, { width, height });
                }
            } catch (err) {
                console.error('Preview graph paint failed:', err);
            }
        });
    }

    function applyPreviewTableEntityFitModes(root) {
        if (!root) return;
        expandPreviewTablesForEntities(root);
        shrinkFitFixedPreviewTableContents(root);
    }

    /** Expand is the default when the flag is unset; only explicit false disables it. */
    function resolveExpandEntitiesFlag(raw, { hasOwnKey = null } = {}) {
        if (raw === false || raw === 'false' || raw === 0 || raw === '0') return false;
        if (raw === true || raw === 'true' || raw === 1 || raw === '1') return true;
        if (hasOwnKey === false) return true; // key missing → default on
        return true;
    }

    function previewTableShouldExpandEntities(table) {
        if (!table) return false;
        const attr = table.getAttribute('data-expand-entities');
        if (attr === 'false') return false;
        if (attr === 'true' || table.classList.contains('ql-table-expand-entities')) return true;
        const embed = table.closest('.ql-workspace-nested-table');
        if (embed) {
            let parsed = {};
            try {
                parsed = JSON.parse(embed.getAttribute('data-value') || '{}') || {};
            } catch (err) {
                parsed = {};
            }
            return resolveExpandEntitiesFlag(parsed.expandEntities, {
                hasOwnKey: Object.prototype.hasOwnProperty.call(parsed, 'expandEntities')
            });
        }
        // Outer tables with no attribute yet → expand by default in preview
        return true;
    }

    /**
     * Preview-only (fixed / expand-off): scale each cell's content down uniformly
     * so rendered entities fit inside the editor-locked cell box instead of clipping.
     */
    function shrinkFitFixedPreviewTableContents(root) {
        if (!root) return;
        const tables = Array.from(root.querySelectorAll('table')).filter(t => !previewTableShouldExpandEntities(t));
        tables.forEach(table => {
            table.classList.remove('ql-table-expand-entities');
            table.setAttribute('data-expand-entities', 'false');
            table.classList.add('ql-table-fixed-entities');

            const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
            if (!rows.length) return;
            const firstCells = Array.from(rows[0].children).filter(el => el.matches('td, th'));
            const colCount = firstCells.length;
            if (!colCount) return;

            // Use editor-persisted sizes (not live client sizes bloated by KaTeX)
            const widthAttr = (table.getAttribute('data-col-widths') || '').split(',').map(v => parseFloat(v));
            const heightAttr = (table.getAttribute('data-row-heights') || '').split(',').map(v => parseFloat(v));
            const lockedWidths = firstCells.map((cell, i) => {
                const fromData = widthAttr[i];
                const fromStyle = parseFloat(cell.style.width);
                return Math.max(
                    14,
                    (!Number.isNaN(fromData) && fromData > 0) ? Math.round(fromData) : 0,
                    (!Number.isNaN(fromStyle) && fromStyle > 0) ? Math.round(fromStyle) : 0,
                    40
                );
            });
            const lockedHeights = rows.map((tr, i) => {
                const fromData = heightAttr[i];
                const fromStyle = parseFloat(tr.style.height);
                return Math.max(
                    16,
                    (!Number.isNaN(fromData) && fromData > 0) ? Math.round(fromData) : 0,
                    (!Number.isNaN(fromStyle) && fromStyle > 0) ? Math.round(fromStyle) : 0,
                    28
                );
            });

            // Pull content out of table layout flow first so KaTeX cannot inflate rows
            rows.forEach((tr, ri) => {
                Array.from(tr.children).filter(el => el.matches('td, th')).forEach((td, ci) => {
                    if (td.classList.contains('ql-has-nested-table') || td.querySelector('.ql-workspace-nested-table')) {
                        return;
                    }
                    ensurePreviewFitViewport(td);
                    td.style.overflow = 'hidden';
                });
            });

            // Force locked geometry
            const lockGeometry = () => {
                if (table.classList.contains('ql-nested-table-inner') || table.closest('.ql-workspace-nested-table')) {
                    applyNestedInnerLayout(table, lockedWidths, lockedHeights);
                } else {
                    applyColumnWidths(table, lockedWidths);
                }
                rows.forEach((tr, i) => {
                    const h = lockedHeights[i];
                    setRowHeightExclusive(tr, h, table);
                    tr.style.maxHeight = `${h}px`;
                    Array.from(tr.children).filter(el => el.matches('td, th')).forEach(td => {
                        td.style.maxHeight = `${h}px`;
                    });
                });
            };
            lockGeometry();

            rows.forEach((tr, ri) => {
                Array.from(tr.children).filter(el => el.matches('td, th')).forEach((td, ci) => {
                    if (td.classList.contains('ql-has-nested-table') || td.querySelector('.ql-workspace-nested-table')) {
                        return;
                    }
                    shrinkFitPreviewCellContent(td, lockedWidths[ci], lockedHeights[ri]);
                });
            });

            lockGeometry();
        });
    }

    function ensurePreviewFitViewport(td) {
        if (!td || td.querySelector(':scope > .ql-preview-fit-viewport')) return;
        const viewport = document.createElement('div');
        viewport.className = 'ql-preview-fit-viewport';
        const wrap = document.createElement('div');
        wrap.className = 'ql-preview-fit-scale';
        const existingWrap = td.querySelector(':scope > .ql-preview-fit-scale');
        if (existingWrap) {
            while (existingWrap.firstChild) wrap.appendChild(existingWrap.firstChild);
            existingWrap.remove();
        } else {
            while (td.firstChild) wrap.appendChild(td.firstChild);
        }
        wrap.style.position = 'absolute';
        wrap.style.top = '0';
        wrap.style.left = '0';
        viewport.appendChild(wrap);
        td.appendChild(viewport);
    }

    function getPreviewCellContentBox(td, lockedW = null, lockedH = null) {
        const cs = window.getComputedStyle(td);
        const padL = parseFloat(cs.paddingLeft) || 0;
        const padR = parseFloat(cs.paddingRight) || 0;
        const padT = parseFloat(cs.paddingTop) || 0;
        const padB = parseFloat(cs.paddingBottom) || 0;
        const borderL = parseFloat(cs.borderLeftWidth) || 0;
        const borderR = parseFloat(cs.borderRightWidth) || 0;
        const borderT = parseFloat(cs.borderTopWidth) || 0;
        const borderB = parseFloat(cs.borderBottomWidth) || 0;

        // Prefer live client box after geometry lock (clientWidth includes padding, excludes border)
        let boxW;
        let boxH;
        if (td.clientWidth > 0 && td.clientHeight > 0) {
            boxW = td.clientWidth - padL - padR;
            boxH = td.clientHeight - padT - padB;
        } else {
            // border-box locked sizes → subtract padding + border
            const outerW = (lockedW != null && lockedW > 0)
                ? lockedW
                : (td.getBoundingClientRect().width || 40);
            const outerH = (lockedH != null && lockedH > 0)
                ? lockedH
                : (td.getBoundingClientRect().height || 28);
            boxW = outerW - padL - padR - borderL - borderR;
            boxH = outerH - padT - padB - borderT - borderB;
        }

        // Small inset so scaled glyphs don't kiss the border
        const inset = 1;
        return {
            width: Math.max(1, Math.floor(boxW) - inset),
            height: Math.max(1, Math.floor(boxH) - inset),
            padL,
            padT
        };
    }

    function shrinkFitPreviewCellContent(td, lockedW = null, lockedH = null) {
        if (!td) return;
        ensurePreviewFitViewport(td);

        const box = getPreviewCellContentBox(td, lockedW, lockedH);
        const targetW = box.width;
        const targetH = box.height;
        if (targetW < 2 || targetH < 2) return;

        const viewport = td.querySelector(':scope > .ql-preview-fit-viewport');
        const wrap = viewport && viewport.querySelector(':scope > .ql-preview-fit-scale');
        if (!viewport || !wrap) return;

        // Viewport fills only the content box (not the padding ring)
        viewport.style.boxSizing = 'border-box';
        viewport.style.width = `${targetW}px`;
        viewport.style.height = `${targetH}px`;
        viewport.style.maxWidth = '100%';
        viewport.style.maxHeight = '100%';
        viewport.style.overflow = 'hidden';
        viewport.style.position = 'relative';
        viewport.style.display = 'block';
        viewport.style.margin = '0';

        wrap.style.transform = 'none';
        wrap.style.transformOrigin = 'top left';
        wrap.style.width = 'max-content';
        wrap.style.maxWidth = 'none';
        wrap.style.height = 'auto';
        wrap.style.display = 'inline-block';
        wrap.style.verticalAlign = 'top';
        wrap.style.margin = '0';
        wrap.style.position = 'absolute';
        wrap.style.top = '0';
        wrap.style.left = '0';

        const contentW = Math.max(wrap.scrollWidth || 0, wrap.offsetWidth || 0, 1);
        const contentH = Math.max(wrap.scrollHeight || 0, wrap.offsetHeight || 0, 1);
        const scale = Math.min(1, targetW / contentW, targetH / contentH);
        wrap.style.transform = scale < 0.999 ? `scale(${scale})` : '';

        td.style.overflow = 'hidden';
        if (lockedW != null && lockedW > 0) {
            td.style.width = `${lockedW}px`;
            td.style.minWidth = `${lockedW}px`;
            td.style.maxWidth = `${lockedW}px`;
        }
        if (lockedH != null && lockedH > 0) {
            td.style.height = `${lockedH}px`;
            td.style.minHeight = `${lockedH}px`;
            td.style.maxHeight = `${lockedH}px`;
        }
    }

    /**
     * Preview-only: grow col/row sizes (never shrink below editor sizes) so
     * rendered entities (KaTeX, matrix, graphs) are not clipped by overflow:hidden.
     */
    function expandPreviewTablesForEntities(root) {
        if (!root) return;
        const tables = Array.from(root.querySelectorAll('table')).filter(previewTableShouldExpandEntities);
        tables.forEach(table => {
            table.classList.add('ql-table-expand-entities');
            table.classList.remove('ql-table-fixed-entities');
            table.setAttribute('data-expand-entities', 'true');

            const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
            if (!rows.length) return;
            const firstCells = Array.from(rows[0].children).filter(el => el.matches('td, th'));
            const colCount = firstCells.length;
            if (!colCount) return;

            const widthAttr = (table.getAttribute('data-col-widths') || '').split(',').map(v => parseFloat(v));
            const heightAttr = (table.getAttribute('data-row-heights') || '').split(',').map(v => parseFloat(v));
            const floorWidths = firstCells.map((cell, i) => {
                const fromData = widthAttr[i];
                const fromStyle = parseFloat(cell.style.width);
                const live = Math.round(cell.getBoundingClientRect().width) || 40;
                return Math.max(
                    14,
                    (!Number.isNaN(fromData) && fromData > 0) ? Math.round(fromData) : 0,
                    (!Number.isNaN(fromStyle) && fromStyle > 0) ? Math.round(fromStyle) : 0,
                    live
                );
            });
            const floorHeights = rows.map((tr, i) => {
                const fromData = heightAttr[i];
                const fromStyle = parseFloat(tr.style.height);
                const live = Math.round(tr.getBoundingClientRect().height) || 28;
                return Math.max(
                    16,
                    (!Number.isNaN(fromData) && fromData > 0) ? Math.round(fromData) : 0,
                    (!Number.isNaN(fromStyle) && fromStyle > 0) ? Math.round(fromStyle) : 0,
                    live
                );
            });

            // Temporarily release fixed heights so scroll metrics reflect rendered entities
            rows.forEach(tr => {
                tr.style.height = 'auto';
                tr.style.minHeight = '';
                Array.from(tr.children).filter(el => el.matches('td, th')).forEach(td => {
                    td.style.overflow = 'visible';
                    td.style.height = 'auto';
                    td.style.minHeight = '';
                    td.style.maxHeight = 'none';
                });
            });

            const nextWidths = floorWidths.slice();
            const nextHeights = floorHeights.slice();
            rows.forEach((tr, ri) => {
                let rowH = floorHeights[ri] || 16;
                Array.from(tr.children).filter(el => el.matches('td, th')).forEach((td, ci) => {
                    const neededW = Math.ceil(Math.max(td.scrollWidth || 0, td.getBoundingClientRect().width || 0));
                    const neededH = Math.ceil(Math.max(td.scrollHeight || 0, td.getBoundingClientRect().height || 0));
                    if (ci < nextWidths.length) {
                        nextWidths[ci] = Math.max(nextWidths[ci], neededW);
                    }
                    rowH = Math.max(rowH, neededH);
                });
                nextHeights[ri] = rowH;
            });

            if (table.classList.contains('ql-nested-table-inner') || table.closest('.ql-workspace-nested-table')) {
                applyNestedInnerLayout(table, nextWidths, nextHeights);
                // If nested grew, also enlarge the outer host cell so the preview isn't clipped by the parent cell
                const embed = table.closest('.ql-workspace-nested-table');
                const host = embed ? embed.closest('td, th') : null;
                const outerTable = host ? host.closest('table') : null;
                if (host && outerTable && !isNestedTableElement(outerTable) && previewTableShouldExpandEntities(outerTable)) {
                    const neededW = nextWidths.reduce((a, b) => a + b, 0);
                    const neededH = nextHeights.reduce((a, b) => a + b, 0);
                    const outerRows = Array.from(outerTable.querySelectorAll(':scope > tr, :scope > tbody > tr'));
                    const outerRow = host.parentElement;
                    const outerRowIndex = outerRows.indexOf(outerRow);
                    const outerCells = outerRow
                        ? Array.from(outerRow.children).filter(el => el.matches('td, th'))
                        : [];
                    const outerColIndex = outerCells.indexOf(host);
                    const outerWidths = readLiveColumnWidths(outerTable);
                    const outerHeights = outerRows.map((tr, i) => {
                        const fromStyle = parseFloat(tr.style.height);
                        return Math.max(
                            16,
                            Math.round((!Number.isNaN(fromStyle) && fromStyle > 0)
                                ? fromStyle
                                : (tr.getBoundingClientRect().height || 28))
                        );
                    });
                    if (outerColIndex >= 0) {
                        while (outerWidths.length <= outerColIndex) outerWidths.push(40);
                        outerWidths[outerColIndex] = Math.max(outerWidths[outerColIndex] || 0, neededW);
                    }
                    if (outerRowIndex >= 0) {
                        while (outerHeights.length <= outerRowIndex) outerHeights.push(28);
                        outerHeights[outerRowIndex] = Math.max(outerHeights[outerRowIndex] || 0, neededH);
                    }
                    applyColumnWidths(outerTable, outerWidths);
                    outerRows.forEach((tr, i) => setRowHeightExclusive(tr, outerHeights[i], outerTable));
                    host.style.overflow = 'visible';
                }
            } else {
                applyColumnWidths(table, nextWidths);
                rows.forEach((tr, i) => setRowHeightExclusive(tr, nextHeights[i], table));
                // Preview-only attrs — do not write back through save path (this DOM is ephemeral)
                table.setAttribute('data-col-widths', nextWidths.join(','));
                table.setAttribute('data-row-heights', nextHeights.join(','));
            }

            table.querySelectorAll(':scope > tr > td, :scope > tr > th, :scope > tbody > tr > td, :scope > tbody > tr > th').forEach(td => {
                td.style.overflow = 'visible';
            });
        });
    }

    // Serializes active layout properties into structural object dictionaries matching database specifications
    function serializeAllWorkspaceEntities() {
        const entities = [];
        document.querySelectorAll('.workspace-block-card').forEach(card => {
            const delBtn = card.querySelector('.btn-delete-workspace-component');
            const token = delBtn ? delBtn.getAttribute('data-indexed-token') : null;
            if (!token) return;


            // 🎯 Determine base archetype (trailing index only — keep digits inside names)
            let baseArchetypeToken = token.replace(/\d+$/, '');

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

    // Allow entity modules to request a sync after local UI mutations (e.g. slope selection)
    window.dispatchWorkspaceBatchSync = dispatchWorkspaceBatchSync;


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
            const tokenText = `<${indexedTokenString}>`;
            // Plain-text entity tags are fine inside nested cells (as typed text)
            if (isFocusInsideNestedTable()) {
                document.execCommand('insertText', false, tokenText);
                const active = getActiveNestedEmbedAndCell();
                if (active) {
                    syncWorkspaceNestedTableNode(active.embed, { relayout: false });
                    growNestedEmbedToContentAndFitOuter(active.embed);
                }
                scheduleNestedPreviewUpdate();
                return;
            }
            const range = workspaceQuillInstance.getSelection(true);
            if (range) {
                workspaceQuillInstance.insertText(range.index, tokenText, 'user');
                workspaceQuillInstance.setSelection(range.index + tokenText.length, 'user');
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

            if (indexedTokenToRemove && Object.prototype.hasOwnProperty.call(previewStudentAnswers, indexedTokenToRemove)) {
                delete previewStudentAnswers[indexedTokenToRemove];
            }

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
            scheduleWorkspacePreviewGradeRefresh();
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

            // MC re-shuffle: clear ephemeral preview selections so the new order
            // starts unchecked (must clear DOM before capture-on-remount).
            if (
                cardElement.getAttribute('data-token') === 'multipleChoiceAnswer'
                && cardTokenId
            ) {
                delete previewStudentAnswers[cardTokenId];
                const renderTarget = document.getElementById('simulation-render-target');
                renderTarget?.querySelectorAll('.simulated-mc-wrapper').forEach((wrap) => {
                    if (wrap.getAttribute('data-token') !== cardTokenId) return;
                    wrap.querySelectorAll('.preview-mc-choice').forEach((el) => {
                        el.checked = false;
                    });
                });
            }

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
        clearPreviewStudentAnswers();

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
                registerWorkspaceNestedTableBlot();
                registerWorkspaceSoftBreakBlot();
                workspaceQuillInstance = new Quill('#editor-html-insert-canvas', {
                    theme: 'snow',
                    modules: {
                        table: { operationMenu: true },
                        keyboard: {
                            bindings: {
                                // Keep Enter inside Quill table cells (native Enter splits the table)
                                'workspace-table-enter': {
                                    key: 'Enter',
                                    handler(range) {
                                        if (isSelectionInsideQuillTableCell()) {
                                            insertSoftBreakInQuillTableCell(range);
                                            return false;
                                        }
                                        return true;
                                    }
                                }
                            }
                        },
                        toolbar: {
                            container: '#workspace-quill-toolbar-container',
                            handlers: {
                                // Nested-table contenteditable supports basic rich text via execCommand
                                bold() {
                                    if (applyNestedInlineFormat('bold')) return;
                                    workspaceQuillInstance.format('bold', !workspaceQuillInstance.getFormat().bold);
                                },
                                italic() {
                                    if (applyNestedInlineFormat('italic')) return;
                                    workspaceQuillInstance.format('italic', !workspaceQuillInstance.getFormat().italic);
                                },
                                underline() {
                                    if (applyNestedInlineFormat('underline')) return;
                                    workspaceQuillInstance.format('underline', !workspaceQuillInstance.getFormat().underline);
                                },
                                strike() {
                                    if (applyNestedInlineFormat('strikeThrough')) return;
                                    workspaceQuillInstance.format('strike', !workspaceQuillInstance.getFormat().strike);
                                },
                                size(value) {
                                    if (applyNestedFontSize(value)) return;
                                    workspaceQuillInstance.format('size', value);
                                },
                                font(value) {
                                    if (applyNestedFontFamily(value)) return;
                                    workspaceQuillInstance.format('font', value);
                                },
                                // Custom handler: accept any LaTeX string (default Quill tooltip
                                // is often clipped inside the overlay scroll containers).
                                formula() {
                                    openWorkspaceLatexInputModal();
                                },
                                // Nested cells use a DOM <img> (Quill image embeds freeze there)
                                image() {
                                    promptAndInsertWorkspaceImage();
                                },
                                table() {
                                    if (isFocusInsideNestedTable()) return; // no table-in-nested-table
                                    openWorkspaceTableSizePicker(this);
                                },
                                // Pseudo-lists inside table cells (real Quill lists would escape the table)
                                list(value) {
                                    if (applyNestedListFormat(value)) return;
                                    if (applyListFormattingInsideTableCell(value)) return;
                                    workspaceQuillInstance.format('list', value);
                                },
                                // Cell align when editing a cell; whole-table align only when table object is selected.
                                align(value) {
                                    if (isFocusInsideNestedTable()) {
                                        applyNestedInlineFormat(value === 'center' ? 'justifyCenter'
                                            : value === 'right' ? 'justifyRight'
                                            : value === 'justify' ? 'justifyFull'
                                            : 'justifyLeft');
                                        return;
                                    }
                                    if (selectedWorkspaceTable && document.contains(selectedWorkspaceTable)) {
                                        applyWorkspaceTableAlignment(value, selectedWorkspaceTable);
                                        return;
                                    }
                                    workspaceQuillInstance.format('align', value);
                                }
                            }
                        },
                        clipboard: {
                            matchers: [
                                ['BR', function(node, delta) {
                                    const cell = node.closest && node.closest('td, th');
                                    if (!cell || (node.closest && node.closest('.ql-workspace-nested-table'))) {
                                        return delta;
                                    }
                                    // Mid-cell soft newlines only. Quill empty cells and
                                    // trailing <br> after text must NOT become softBreak embeds
                                    // — those are contenteditable=false and block caret entry on reload.
                                    let hasFollowingContent = false;
                                    for (let sib = node.nextSibling; sib; sib = sib.nextSibling) {
                                        if (sib.nodeType === Node.TEXT_NODE) {
                                            if ((sib.textContent || '').replace(/[\u200B\uFEFF]/g, '').length) {
                                                hasFollowingContent = true;
                                                break;
                                            }
                                            continue;
                                        }
                                        if (sib.nodeType === Node.ELEMENT_NODE) {
                                            hasFollowingContent = true;
                                            break;
                                        }
                                    }
                                    const Delta = Quill.import('delta');
                                    if (!hasFollowingContent) {
                                        return new Delta();
                                    }
                                    return new Delta().insert({ softBreak: true });
                                }],
                                ['.ql-soft-break', function(node, delta) {
                                    const Delta = Quill.import('delta');
                                    const cell = node.closest && node.closest('td, th');
                                    if (cell && !(node.closest && node.closest('.ql-workspace-nested-table'))) {
                                        // Orphan soft-break left alone in an empty cell (bad save/reload) — drop it
                                        const hasOther = Array.from(cell.childNodes).some(child => {
                                            if (child === node) return false;
                                            if (child.nodeType === Node.TEXT_NODE) {
                                                return !!(child.textContent || '').replace(/[\u200B\uFEFF]/g, '').length;
                                            }
                                            if (child.nodeType === Node.ELEMENT_NODE) {
                                                return true;
                                            }
                                            return false;
                                        });
                                        if (!hasOther) {
                                            return new Delta();
                                        }
                                    }
                                    return new Delta().insert({ softBreak: true });
                                }],
                                ['TD, TH', function(node, delta) {
                                    if (node.closest && (
                                        node.closest('.ql-workspace-nested-table') ||
                                        node.closest('.ql-nested-table-inner')
                                    )) {
                                        return delta;
                                    }
                                    // Repair corrupted Quill row ids before they flatten the grid
                                    const raw = node.getAttribute('data-row');
                                    if (!raw || raw === '[object Object]' || raw === 'true' || raw.startsWith('{')) {
                                        const tr = node.parentElement;
                                        const table = node.closest('table');
                                        const rows = table ? Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr')) : [];
                                        const rowIndex = tr ? rows.indexOf(tr) : 0;
                                        node.setAttribute('data-row', `row-${rowIndex}-${Math.random().toString(36).slice(2, 6)}`);
                                    }
                                    return delta;
                                }],
                                // Force each HTML <tr> onto a unique Quill table-format id (fixes 5x5 → 1x25 reload).
                                ['tr', function(node, delta) {
                                    if (node.closest && node.closest('.ql-workspace-nested-table')) {
                                        return delta;
                                    }
                                    const table = node.parentElement?.tagName === 'TABLE'
                                        ? node.parentElement
                                        : node.parentElement?.parentElement;
                                    const rows = table ? Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr')) : [];
                                    const rowIndex = rows.indexOf(node);
                                    let rowId = null;
                                    const firstCell = node.querySelector && node.querySelector('td, th');
                                    if (firstCell) {
                                        const existing = firstCell.getAttribute('data-row');
                                        if (existing && existing !== '[object Object]' && existing !== 'true' && !existing.startsWith('{')) {
                                            rowId = existing;
                                        }
                                    }
                                    if (!rowId) {
                                        rowId = `row-${Math.max(0, rowIndex)}-${Math.random().toString(36).slice(2, 6)}`;
                                    }
                                    if (delta && Array.isArray(delta.ops)) {
                                        delta.ops.forEach(op => {
                                            if (!op.insert) return;
                                            op.attributes = { ...(op.attributes || {}), table: rowId };
                                        });
                                    }
                                    return delta;
                                }],
                                ['table', function(node, delta) {
                                    // Persist layout markers Quill otherwise drops from TABLE nodes
                                    if (node && node.classList && node.classList.contains('no-border')) {
                                        node.setAttribute('data-no-border', 'true');
                                    }
                                    if (node && node.classList && node.classList.contains('ql-table-expand-entities')) {
                                        node.setAttribute('data-expand-entities', 'true');
                                    }
                                    // IMPORTANT: never rewrite attributes.table (row id) into an object —
                                    // that becomes "[object Object]" and collapses every row into one.
                                    return delta;
                                }]
                            ]
                        }
                    }
                });
                workspaceQuillInstance.on('text-change', (delta, oldDelta, source) => {
                    if (window.__workspaceTableLayoutQuiet || window.__workspacePreviewQuiet) return;
                    // Re-applying nested/outer layouts on every keystroke mutates the DOM and can
                    // retrigger Quill optimize/text-change (freeze). Only re-layout when table ops
                    // are involved.
                    const touchesTable = !!(delta && Array.isArray(delta.ops) && delta.ops.some(op =>
                        (op.attributes && op.attributes.table != null)
                        || (op.insert && typeof op.insert === 'object' && op.insert.workspaceNestedTable)
                    ));
                    if (source === 'user' && touchesTable) {
                        window.__workspaceTableLayoutQuiet = true;
                        try {
                            reapplyAllWorkspaceTableLayouts();
                            lockOuterCellsThatContainNestedTables();
                        } finally {
                            requestAnimationFrame(() => { window.__workspaceTableLayoutQuiet = false; });
                        }
                    } else if (source === 'user') {
                        lockOuterCellsThatContainNestedTables();
                    }
                    updateWorkspaceSimulationPreview();
                    if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                });
                setupWorkspaceTableCellPasteHandler();
                setupWorkspaceTableContextMenu();
                setupEmptyOuterTableCellClick();
                setupWorkspaceTableResize();
                setupWorkspaceTableObjectSelection();
                setupWorkspaceTableHoverTip();
                setupNestedExclusiveCellGuards();
                const toolbarEl = document.getElementById('workspace-quill-toolbar-container');
                if (toolbarEl && toolbarEl.dataset.nestedGuardBound !== '1') {
                    toolbarEl.dataset.nestedGuardBound = '1';
                    toolbarEl.addEventListener('mousedown', function(e) {
                        if (!isFocusInsideNestedTable()) return;
                        // Block embeds that freeze Quill when targeted at nested contenteditable cells
                        if (e.target.closest('.ql-table, .ql-video')) {
                            e.preventDefault();
                            e.stopPropagation();
                            return;
                        }
                        // Image / formula use custom handlers — preserve nested selection
                        if (e.target.closest('.ql-image, .ql-formula')) {
                            e.preventDefault();
                            return;
                        }
                        // Keep nested selection alive so bold/italic/size/etc still apply
                        if (e.target.closest('button, .ql-picker, .ql-picker-label, .ql-picker-item')) {
                            e.preventDefault();
                        }
                    }, true);
                }
                // Ensure Enter soft-breaks win over Quill's default table-splitting Enter
                try {
                    const keyboard = workspaceQuillInstance.getModule('keyboard');
                    if (keyboard && keyboard.bindings) {
                        const enterKey = keyboard.bindings.Enter || keyboard.bindings[13];
                        if (Array.isArray(enterKey)) {
                            enterKey.unshift({
                                key: 'Enter',
                                handler(range) {
                                    if (isSelectionInsideQuillTableCell()) {
                                        insertSoftBreakInQuillTableCell(range);
                                        return false;
                                    }
                                    return true;
                                }
                            });
                        }
                    }
                } catch (err) {
                    console.warn('Could not prioritize table Enter binding:', err);
                }
            }

            // Restore entity cards first so Quill paste / preview can resolve tokens
            rehydrateWorkspaceSegments(data.loaded_segments || []);

            if (workspaceQuillInstance) {
                loadWorkspaceQuillHtml(data.body_html || '<p><br></p>');
            }

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
            clearPreviewStudentAnswers();
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

    // 🎯 4b. WORKSPACE LATEX INSERT MODAL (Quill formula toolbar)
    const latexInputModal = document.getElementById('workspace-latex-input-modal');
    const latexInputField = document.getElementById('workspace-latex-input-field');
    const latexInsertBtn = document.getElementById('btn-insert-workspace-latex');
    const latexCancelBtn = document.getElementById('btn-cancel-workspace-latex');
    let nestedLatexInsertTarget = null;

    function hideWorkspaceLatexInputModal() {
        nestedLatexInsertTarget = null;
        if (latexInputModal) {
            latexInputModal.classList.remove('is-visible');
            latexInputModal.style.display = 'none';
            latexInputModal.style.visibility = 'hidden';
            latexInputModal.style.opacity = '0';
        }
        if (latexInputField) latexInputField.value = '';
    }

    function openWorkspaceLatexInputModal() {
        if (!latexInputModal || !latexInputField) return;
        nestedLatexInsertTarget = null;
        if (isFocusInsideNestedTable()) {
            const active = getActiveNestedEmbedAndCell();
            const sel = window.getSelection();
            if (active && sel && sel.rangeCount) {
                nestedLatexInsertTarget = {
                    embed: active.embed,
                    cell: active.cell,
                    range: sel.getRangeAt(0).cloneRange()
                };
            }
        }
        latexInputField.value = '';
        latexInputModal.style.display = 'flex';
        latexInputModal.style.visibility = 'visible';
        latexInputModal.style.opacity = '1';
        latexInputModal.classList.add('is-visible');
        setTimeout(() => latexInputField.focus(), 0);
    }

    function insertNestedLatexFormula(latex) {
        const target = nestedLatexInsertTarget;
        nestedLatexInsertTarget = null;
        if (!target || !target.cell || !target.embed) return false;

        const span = document.createElement('span');
        span.className = 'workspace-nested-latex';
        span.setAttribute('contenteditable', 'false');
        span.setAttribute('data-value', latex);
        if (typeof katex !== 'undefined') {
            try {
                katex.render(latex, span, { displayMode: false, throwOnError: false });
            } catch (err) {
                span.textContent = latex;
            }
        } else {
            span.textContent = latex;
        }

        try {
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(target.range);
            target.range.deleteContents();
            target.range.insertNode(span);
            // Place caret after the formula
            const after = document.createRange();
            after.setStartAfter(span);
            after.collapse(true);
            sel.removeAllRanges();
            sel.addRange(after);
        } catch (err) {
            target.cell.appendChild(span);
        }

        syncWorkspaceNestedTableNode(target.embed, { relayout: false });
        growNestedEmbedToContentAndFitOuter(target.embed);
        scheduleNestedPreviewUpdate();
        if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
        return true;
    }

    function isSafeNestedImageSrc(src) {
        const value = String(src || '').trim();
        if (!value) return false;
        if (/^data:image\/(png|jpe?g|gif|webp|svg\+xml);base64,/i.test(value)) return true;
        if (/^https?:\/\//i.test(value)) return true;
        if (value.startsWith('/') && !value.startsWith('//')) return true;
        return false;
    }

    function createWorkspaceNestedImage(src) {
        const img = document.createElement('img');
        img.className = 'workspace-nested-image';
        img.setAttribute('src', src);
        img.setAttribute('alt', '');
        img.setAttribute('contenteditable', 'false');
        img.draggable = false;
        return img;
    }

    function insertNestedImageAt(embed, cell, range, src) {
        if (!embed || !cell || !isSafeNestedImageSrc(src)) return false;
        const img = createWorkspaceNestedImage(src);
        const onReady = () => {
            syncWorkspaceNestedTableNode(embed, { relayout: false });
            growNestedEmbedToContentAndFitOuter(embed);
            scheduleNestedPreviewUpdate();
            if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
        };
        img.addEventListener('load', onReady, { once: true });
        img.addEventListener('error', onReady, { once: true });

        try {
            const sel = window.getSelection();
            if (range) {
                sel.removeAllRanges();
                sel.addRange(range);
                range.deleteContents();
                range.insertNode(img);
                const after = document.createRange();
                after.setStartAfter(img);
                after.collapse(true);
                sel.removeAllRanges();
                sel.addRange(after);
            } else {
                cell.appendChild(img);
            }
        } catch (err) {
            cell.appendChild(img);
        }

        // If already cached/complete, grow immediately
        if (img.complete) onReady();
        return true;
    }

    function promptAndInsertWorkspaceImage() {
        if (!workspaceQuillInstance) return;

        // Capture nested target before the file dialog steals focus
        let nestedTarget = null;
        const active = getActiveNestedEmbedAndCell();
        if (active) {
            let range = null;
            try {
                const sel = window.getSelection();
                if (sel && sel.rangeCount && active.cell.contains(sel.anchorNode)) {
                    range = sel.getRangeAt(0).cloneRange();
                }
            } catch (err) {
                range = null;
            }
            nestedTarget = { embed: active.embed, cell: active.cell, range };
        }

        const input = document.createElement('input');
        input.setAttribute('type', 'file');
        input.setAttribute('accept', 'image/png,image/jpeg,image/gif,image/webp,image/svg+xml');
        input.style.display = 'none';
        document.body.appendChild(input);
        input.addEventListener('change', function() {
            const file = input.files && input.files[0];
            input.remove();
            if (!file || !String(file.type || '').startsWith('image/')) return;
            const reader = new FileReader();
            reader.onload = function() {
                const src = reader.result;
                if (!isSafeNestedImageSrc(src)) return;
                if (nestedTarget) {
                    insertNestedImageAt(nestedTarget.embed, nestedTarget.cell, nestedTarget.range, src);
                    return;
                }
                try {
                    const range = workspaceQuillInstance.getSelection(true)
                        || { index: workspaceQuillInstance.getLength(), length: 0 };
                    if (range.length > 0) {
                        workspaceQuillInstance.deleteText(range.index, range.length, Quill.sources.USER);
                    }
                    workspaceQuillInstance.insertEmbed(range.index, 'image', src, Quill.sources.USER);
                    workspaceQuillInstance.setSelection(range.index + 1, 0, Quill.sources.USER);
                    updateWorkspaceSimulationPreview();
                    if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                } catch (err) {
                    console.error('Failed inserting workspace image:', err);
                }
            };
            reader.readAsDataURL(file);
        });
        input.click();
    }

    function insertWorkspaceLatexFormula() {
        if (!workspaceQuillInstance || typeof Quill === 'undefined') {
            hideWorkspaceLatexInputModal();
            return;
        }

        const latex = normalizeWorkspaceLatexInput(latexInputField ? latexInputField.value : '');
        const nestedTarget = nestedLatexInsertTarget;
        nestedLatexInsertTarget = null;
        hideWorkspaceLatexInputModal();
        if (!latex) return;

        if (typeof katex === 'undefined') {
            console.error('KaTeX is required to insert LaTeX formulas.');
            return;
        }

        // Nested cells use a DOM KaTeX span — Quill formula embeds freeze the editor there
        if (nestedTarget) {
            nestedLatexInsertTarget = nestedTarget;
            insertNestedLatexFormula(latex);
            return;
        }

        const range = workspaceQuillInstance.getSelection(true) || { index: workspaceQuillInstance.getLength(), length: 0 };
        if (range.length > 0) {
            workspaceQuillInstance.deleteText(range.index, range.length, Quill.sources.USER);
        }
        workspaceQuillInstance.insertEmbed(range.index, 'formula', latex, Quill.sources.USER);
        workspaceQuillInstance.insertText(range.index + 1, ' ', Quill.sources.USER);
        workspaceQuillInstance.setSelection(range.index + 2, Quill.sources.USER);
        updateWorkspaceSimulationPreview();
    }

    if (latexInsertBtn) {
        latexInsertBtn.addEventListener('click', insertWorkspaceLatexFormula);
    }
    if (latexCancelBtn) {
        latexCancelBtn.addEventListener('click', hideWorkspaceLatexInputModal);
    }
    if (latexInputModal) {
        latexInputModal.addEventListener('click', function(e) {
            if (e.target === latexInputModal) {
                hideWorkspaceLatexInputModal();
            }
        });
    }
    if (latexInputField) {
        latexInputField.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                hideWorkspaceLatexInputModal();
            } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                insertWorkspaceLatexFormula();
            }
        });
    }

    // 🎯 4c. WORKSPACE TABLE INSERT / EDIT / RESIZE
    const TABLE_SIZE_MAX = 5;
    const NESTED_TABLE_SOFT_MAX = 20;
    const NESTED_MIN_COL = 14;
    const NESTED_MIN_ROW = 16;
    const tableSizePicker = document.getElementById('workspace-table-size-picker');
    const tableSizeGrid = document.getElementById('workspace-table-size-grid');
    const tableSizeLabel = document.getElementById('workspace-table-size-label');
    let tableSizeHover = { rows: 1, cols: 1 };
    let tableResizeState = null;
    let tableContextMenuBound = false;
    let tableResizeBound = false;
    let tableObjectSelectionBound = false;
    let selectedWorkspaceTable = null;

    function isNestedTableElement(table) {
        return !!(table && (
            table.classList.contains('ql-nested-table-inner') ||
            table.closest('.ql-workspace-nested-table')
        ));
    }

    function queryWorkspaceQuillTables(root) {
        if (!root) return [];
        return Array.from(root.querySelectorAll('table')).filter(t => !isNestedTableElement(t));
    }

    function registerWorkspaceNestedTableBlot() {
        if (typeof Quill === 'undefined' || window.__workspaceNestedTableRegistered) return;
        const Embed = Quill.import('blots/embed');

        class WorkspaceNestedTable extends Embed {
            static blotName = 'workspaceNestedTable';
            static className = 'ql-workspace-nested-table';
            static tagName = 'SPAN';

            static create(value) {
                const node = super.create(value);
                node.setAttribute('contenteditable', 'false');
                const config = parseNestedTableConfig(value);
                node.setAttribute('data-value', JSON.stringify(config));
                renderNestedTableIntoNode(node, config);
                return node;
            }

            static value(domNode) {
                return domNode.getAttribute('data-value') || '';
            }

            static syncFromDom(node) {
                syncWorkspaceNestedTableNode(node);
            }
        }

        Quill.register(WorkspaceNestedTable, true);
        window.__workspaceNestedTableRegistered = true;
    }

    function parseNestedTableConfig(value) {
        let config = { rows: 2, cols: 2, cells: [], colWidths: [], rowHeights: [] };
        try {
            if (typeof value === 'string' && value.trim()) {
                config = { ...config, ...JSON.parse(value) };
            } else if (value && typeof value === 'object') {
                config = { ...config, ...value };
            }
        } catch (err) {
            // keep defaults
        }
        const rows = Math.max(1, Math.min(NESTED_TABLE_SOFT_MAX, parseInt(config.rows, 10) || 2));
        const cols = Math.max(1, Math.min(NESTED_TABLE_SOFT_MAX, parseInt(config.cols, 10) || 2));
        const cells = Array.from({ length: rows }, (_, r) => (
            Array.from({ length: cols }, (_, c) => {
                const row = Array.isArray(config.cells) ? config.cells[r] : null;
                return (row && row[c] != null) ? String(row[c]) : '';
            })
        ));
        let colWidths = Array.isArray(config.colWidths)
            ? config.colWidths.map(w => Math.max(NESTED_MIN_COL, Math.round(parseFloat(w) || NESTED_MIN_COL)))
            : [];
        while (colWidths.length < cols) colWidths.push(Math.max(NESTED_MIN_COL, 48));
        colWidths = colWidths.slice(0, cols);

        let rowHeights = Array.isArray(config.rowHeights)
            ? config.rowHeights.map(h => Math.max(NESTED_MIN_ROW, Math.round(parseFloat(h) || NESTED_MIN_ROW)))
            : [];
        while (rowHeights.length < rows) rowHeights.push(Math.max(NESTED_MIN_ROW, 28));
        rowHeights = rowHeights.slice(0, rows);

        const expandOwn = Object.prototype.hasOwnProperty.call(config, 'expandEntities');
        return {
            rows,
            cols,
            cells,
            colWidths,
            rowHeights,
            noBorder: !!config.noBorder,
            expandEntities: resolveExpandEntitiesFlag(config.expandEntities, { hasOwnKey: expandOwn })
        };
    }

    function nestedCellTextFromTd(td) {
        if (!td) return '';
        const clone = td.cloneNode(true);
        clone.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
        return clone.textContent || '';
    }

    function htmlFragmentToPlainText(html) {
        const div = document.createElement('div');
        div.innerHTML = html == null ? '' : String(html);
        return div.textContent || '';
    }

    function escapeNestedPlainText(text) {
        return String(text == null ? '' : text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function getNestedLineIndexAtPoint(td, container, offset) {
        if (!td || !container) return 0;
        try {
            const r = document.createRange();
            r.selectNodeContents(td);
            r.setEnd(container, offset);
            const div = document.createElement('div');
            div.appendChild(r.cloneContents());
            return div.querySelectorAll('br').length;
        } catch (err) {
            return 0;
        }
    }

    function getNestedSelectedLineIndices(td) {
        if (!td) return [0];
        const parts = (td.innerHTML || '').split(/<br\s*\/?>/i);
        const last = Math.max(0, parts.length - 1);
        const sel = window.getSelection();
        if (!sel || !sel.rangeCount) return [0];
        const anchor = sel.anchorNode;
        if (!anchor || !td.contains(anchor)) return [0];
        const range = sel.getRangeAt(0);
        let startL = getNestedLineIndexAtPoint(td, range.startContainer, range.startOffset);
        let endL = range.collapsed
            ? startL
            : getNestedLineIndexAtPoint(td, range.endContainer, range.endOffset);
        startL = Math.max(0, Math.min(last, startL));
        endL = Math.max(0, Math.min(last, endL));
        if (endL < startL) {
            const tmp = startL;
            startL = endL;
            endL = tmp;
        }
        const indices = [];
        for (let i = startL; i <= endL; i++) indices.push(i);
        return indices.length ? indices : [0];
    }

    function insertNestedLineBreak(td) {
        if (!td) return false;
        const sel = window.getSelection();
        if (!sel) return false;
        try {
            td.focus();
            let range;
            if (sel.rangeCount && td.contains(sel.anchorNode)) {
                range = sel.getRangeAt(0);
            } else {
                range = document.createRange();
                range.selectNodeContents(td);
                range.collapse(false);
            }
            range.deleteContents();
            const br = document.createElement('br');
            const zwsp = document.createTextNode('\u200B');
            range.insertNode(br);
            if (br.nextSibling) {
                br.parentNode.insertBefore(zwsp, br.nextSibling);
            } else {
                br.parentNode.appendChild(zwsp);
            }
            const after = document.createRange();
            after.setStart(zwsp, 1);
            after.collapse(true);
            sel.removeAllRanges();
            sel.addRange(after);
            return true;
        } catch (err) {
            try {
                document.execCommand('insertHTML', false, '<br>\u200B');
                return true;
            } catch (err2) {
                return false;
            }
        }
    }

    function getLeadingListPrefix(plain) {
        const text = String(plain == null ? '' : plain).replace(/^\u200B+/, '');
        const bullet = text.match(/^•\s/);
        if (bullet) return bullet[0];
        const ordered = text.match(/^\d+\.\s/);
        if (ordered) return ordered[0];
        return '';
    }

    function parseLeadingOrderedNumber(plain) {
        const text = String(plain == null ? '' : plain).replace(/^\u200B+/, '');
        const m = text.match(/^(\d+)\.\s/);
        return m ? parseInt(m[1], 10) : null;
    }

    /** Continue numbering from the line above the first targeted line when it is already ordered. */
    function resolveOrderedStartNumber(plains, targetIndices) {
        const sorted = [...targetIndices].filter(i => i >= 0).sort((a, b) => a - b);
        if (!sorted.length) return 1;
        const first = sorted[0];
        if (first <= 0) return 1;
        const prevNum = parseLeadingOrderedNumber(plains[first - 1]);
        return prevNum != null ? prevNum + 1 : 1;
    }

    function stripLeadingPlainFromHtml(html, prefixLen) {
        if (!prefixLen) return html == null ? '' : String(html);
        const wrap = document.createElement('div');
        wrap.innerHTML = html == null ? '' : String(html);
        let remaining = prefixLen;
        const walker = document.createTreeWalker(wrap, NodeFilter.SHOW_TEXT);
        let node = walker.nextNode();
        while (node && remaining > 0) {
            const t = node.textContent || '';
            if (!t.length) {
                node = walker.nextNode();
                continue;
            }
            if (t.length <= remaining) {
                remaining -= t.length;
                node.textContent = '';
            } else {
                node.textContent = t.slice(remaining);
                remaining = 0;
            }
            node = walker.nextNode();
        }
        return wrap.innerHTML;
    }

    function applyListToggleToHtmlFragments(parts, value, onlyIndices = null) {
        const targetIdx = onlyIndices && onlyIndices.length
            ? new Set(onlyIndices)
            : null;
        const plains = parts.map(htmlFragmentToPlainText);
        const targetPlains = plains
            .map((l, i) => ({ l, i }))
            .filter(({ l, i }) => (!targetIdx || targetIdx.has(i)) && String(l).replace(/^\u200B+/, '').trim().length)
            .map(({ l }) => l.replace(/^\u200B+/, ''));
        const isBullet = targetPlains.length > 0 && targetPlains.every(l => /^•\s/.test(l));
        const isOrdered = targetPlains.length > 0 && targetPlains.every(l => /^\d+\.\s/.test(l));

        const targetIndices = plains
            .map((l, i) => i)
            .filter(i => (!targetIdx || targetIdx.has(i)) && String(plains[i] || '').replace(/^\u200B+/, '').trim().length);
        let n = resolveOrderedStartNumber(plains, targetIndices);

        return parts.map((html, i) => {
            if (targetIdx && !targetIdx.has(i)) return html;
            const plain = (plains[i] || '').replace(/^\u200B+/, '');
            if (!plain.trim()) return html;
            const existing = getLeadingListPrefix(plain);
            let next = html;
            if (existing) next = stripLeadingPlainFromHtml(next, existing.length);

            if (value === 'bullet') {
                if (isBullet) return next; // already stripped
                return `• ${next}`;
            }
            if (value === 'ordered') {
                if (isOrdered) return next;
                return `${n++}. ${next}`;
            }
            return next; // clear any list prefix
        });
    }

    function applyListToggleToPlainLines(lines, value, onlyIndices = null) {
        const targetIdx = onlyIndices && onlyIndices.length
            ? new Set(onlyIndices)
            : null;
        const targetLines = lines
            .map((l, i) => ({ l, i }))
            .filter(({ l, i }) => (!targetIdx || targetIdx.has(i)) && String(l).trim().length);
        const nonEmpty = targetLines.map(({ l }) => l);
        const isBullet = nonEmpty.length > 0 && nonEmpty.every(l => /^•\s/.test(l));
        const isOrdered = nonEmpty.length > 0 && nonEmpty.every(l => /^\d+\.\s/.test(l));

        const targetIndices = targetLines.map(({ i }) => i);
        let n = resolveOrderedStartNumber(lines, targetIndices);
        return lines.map((line, i) => {
            if (targetIdx && !targetIdx.has(i)) return line;
            if (!String(line).trim()) return line;
            if (value === 'bullet') {
                return isBullet
                    ? line.replace(/^•\s/, '')
                    : `• ${line.replace(/^•\s/, '').replace(/^\d+\.\s/, '')}`;
            }
            if (value === 'ordered') {
                if (isOrdered) return line.replace(/^\d+\.\s/, '');
                const cleaned = line.replace(/^•\s/, '').replace(/^\d+\.\s/, '');
                return `${n++}. ${cleaned}`;
            }
            return line.replace(/^•\s/, '').replace(/^\d+\.\s/, '');
        });
    }

    function sanitizeNestedCellHtml(html) {
        const wrap = document.createElement('div');
        wrap.innerHTML = html == null ? '' : String(html);
        const allowed = new Set(['B', 'STRONG', 'I', 'EM', 'U', 'S', 'STRIKE', 'BR', 'SPAN', 'FONT', 'IMG']);
        const walk = (parent) => {
            Array.from(parent.childNodes).forEach(node => {
                if (node.nodeType === Node.TEXT_NODE) return;
                if (node.nodeType !== Node.ELEMENT_NODE) {
                    node.remove();
                    return;
                }
                const tag = node.tagName;
                if (tag === 'IMG') {
                    const src = node.getAttribute('src') || '';
                    if (!isSafeNestedImageSrc(src)) {
                        node.remove();
                        return;
                    }
                    node.className = 'workspace-nested-image';
                    node.setAttribute('src', src);
                    node.setAttribute('alt', node.getAttribute('alt') || '');
                    node.setAttribute('contenteditable', 'false');
                    [...node.attributes].forEach(attr => {
                        if (!['src', 'alt', 'class', 'style', 'contenteditable', 'width', 'height'].includes(attr.name)) {
                            node.removeAttribute(attr.name);
                        }
                    });
                    // Keep only sizing styles that constrain within the cell
                    const style = node.getAttribute('style') || '';
                    const cleaned = style
                        .split(';')
                        .map(s => s.trim())
                        .filter(s => /^(max-width|width|height|max-height|object-fit|display|vertical-align)\s*:/i.test(s))
                        .join('; ');
                    if (cleaned) node.setAttribute('style', cleaned);
                    else node.removeAttribute('style');
                    return;
                }
                if (!allowed.has(tag) || tag === 'TABLE' || tag === 'VIDEO' || tag === 'IFRAME') {
                    // unwrap text children, drop the element
                    while (node.firstChild) parent.insertBefore(node.firstChild, node);
                    node.remove();
                    return;
                }
                // Drop Quill embed chrome / nested tables (keep nested latex spans)
                if (node.classList && (
                    node.classList.contains('ql-formula')
                    || node.classList.contains('ql-workspace-nested-table')
                    || node.classList.contains('ql-cursor')
                )) {
                    node.remove();
                    return;
                }
                if (node.classList && node.classList.contains('workspace-nested-latex')) {
                    // Keep latex marker + data-value; drop heavy KaTeX child chrome for storage
                    const latex = node.getAttribute('data-value') || node.textContent || '';
                    node.setAttribute('data-value', latex);
                    node.setAttribute('contenteditable', 'false');
                    node.className = 'workspace-nested-latex';
                    [...node.attributes].forEach(attr => {
                        if (!['style', 'class', 'data-value', 'contenteditable'].includes(attr.name)) {
                            node.removeAttribute(attr.name);
                        }
                    });
                    node.innerHTML = '';
                    node.textContent = latex;
                    return;
                }
                // Keep only style/class attrs we care about
                [...node.attributes].forEach(attr => {
                    if (!['style', 'class'].includes(attr.name)) node.removeAttribute(attr.name);
                });
                // Keep Quill size classes; strip other noisy classes
                if (node.classList && node.classList.length) {
                    const keep = ['ql-size-small', 'ql-size-large', 'ql-size-huge', 'workspace-nested-latex'];
                    Array.from(node.classList).forEach(cls => {
                        if (!keep.includes(cls)) node.classList.remove(cls);
                    });
                }
                walk(node);
            });
        };
        walk(wrap);
        wrap.querySelectorAll('table, video, iframe, script, style').forEach(n => n.remove());
        wrap.querySelectorAll('img:not(.workspace-nested-image)').forEach(n => {
            if (!isSafeNestedImageSrc(n.getAttribute('src') || '')) {
                n.remove();
                return;
            }
            n.className = 'workspace-nested-image';
            n.setAttribute('contenteditable', 'false');
        });
        return wrap.innerHTML;
    }

    function fillNestedTdFromText(td, text) {
        if (!td) return;
        // Legacy plain-text path (newlines → br)
        td.innerHTML = '';
        const parts = String(text == null ? '' : text).split('\n');
        parts.forEach((part, i) => {
            if (i > 0) td.appendChild(document.createElement('br'));
            td.appendChild(document.createTextNode(part));
        });
    }

    function hydrateNestedLatexSpans(root) {
        if (!root) return;
        root.querySelectorAll('.workspace-nested-latex').forEach(span => {
            const latex = normalizeWorkspaceLatexInput(span.getAttribute('data-value') || span.textContent || '');
            span.setAttribute('data-value', latex);
            span.setAttribute('contenteditable', 'false');
            span.className = 'workspace-nested-latex';
            if (typeof katex !== 'undefined' && latex) {
                try {
                    katex.render(latex, span, { displayMode: false, throwOnError: false });
                } catch (err) {
                    span.textContent = latex;
                }
            } else {
                span.textContent = latex;
            }
        });
    }

    function ensureNestedCellHtmlLineBreaks(html) {
        let raw = html == null ? '' : String(html);
        if (!raw) return '';
        // Legacy plain cells may store \n instead of <br>
        if (raw.includes('\n') && !/<br\s*\/?>/i.test(raw)) {
            raw = raw
                .split('\n')
                .map((part, i) => (i ? '<br>' : '') + part)
                .join('');
        }
        return raw;
    }

    function fillNestedTdFromHtml(td, htmlOrText) {
        if (!td) return;
        let raw = ensureNestedCellHtmlLineBreaks(htmlOrText == null ? '' : String(htmlOrText));
        if (!raw) {
            td.innerHTML = '';
            return;
        }
        // Entity tokens must never be parsed as HTML tags. Allow formatting + nested image tags only.
        // (sanitizeNestedCellHtml still validates img src / strips unsafe attributes.)
        const allowedOpen = /^(b|strong|i|em|u|s|strike|br|span|font|img)$/i;
        raw = raw.replace(/<\/?([a-zA-Z][a-zA-Z0-9_]*)(\s[^>]*)?>/g, (match, tag) => {
            if (allowedOpen.test(tag)) return match;
            return match.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        });
        // Escaped tokens (&lt;matrix1&gt;) must use HTML path once so they become text "<matrix1>"
        if (raw.includes('<') || raw.includes('&lt;') || raw.includes('&amp;')) {
            td.innerHTML = sanitizeNestedCellHtml(raw);
            hydrateNestedLatexSpans(td);
            return;
        }
        fillNestedTdFromText(td, raw);
    }

    function nestedCellHtmlFromTd(td) {
        if (!td) return '';
        return ensureNestedCellHtmlLineBreaks(sanitizeNestedCellHtml(td.innerHTML || ''));
    }

    function isFocusInsideNestedTable() {
        const ae = document.activeElement;
        if (ae && ae.closest && ae.closest('.ql-workspace-nested-table')) return true;
        const sel = window.getSelection();
        if (sel && sel.rangeCount) {
            let node = sel.anchorNode;
            if (node && node.nodeType === Node.TEXT_NODE) node = node.parentElement;
            if (node && node.closest && node.closest('.ql-workspace-nested-table')) return true;
        }
        return false;
    }


    function getActiveNestedEmbedAndCell() {
        if (!isFocusInsideNestedTable()) return null;
        const sel = window.getSelection();
        let node = sel && sel.anchorNode;
        if (node && node.nodeType === Node.TEXT_NODE) node = node.parentElement;
        if (!node || !node.closest) return null;
        const embed = node.closest('.ql-workspace-nested-table');
        const cell = node.closest('.ql-nested-table-inner td, .ql-nested-table-inner th');
        if (!embed || !cell) return null;
        return { embed, cell };
    }

    function applyNestedInlineFormat(command) {
        const active = getActiveNestedEmbedAndCell();
        if (!active) return false;
        document.execCommand(command);
        syncWorkspaceNestedTableNode(active.embed, { relayout: false });
        growNestedEmbedToContentAndFitOuter(active.embed);
        scheduleNestedPreviewUpdate();
        return true;
    }

    function applyNestedFontSize(value) {
        const active = getActiveNestedEmbedAndCell();
        if (!active) return false;
        const sel = window.getSelection();
        if (!sel || !sel.rangeCount) return true;

        const classMap = {
            small: 'ql-size-small',
            large: 'ql-size-large',
            huge: 'ql-size-huge'
        };
        const sizeClass = value ? classMap[value] : '';

        // Avoid execCommand('fontSize', 7) — with styleWithCSS it leaves xxx-large ("huge") forever.
        // Use the legacy font size command to mark the selection, then normalize to Quill classes.
        document.execCommand('styleWithCSS', false, false);
        document.execCommand('fontSize', false, '3');

        active.cell.querySelectorAll('font[size]').forEach(fontEl => {
            if (!sel.containsNode(fontEl, true) && fontEl !== active.cell) {
                // Still convert if selection collapsed inside this font
                const inSel = (() => {
                    try { return sel.containsNode(fontEl, true); } catch (err) { return false; }
                })();
                if (!inSel) return;
            }
            const span = document.createElement('span');
            // Strip prior size classes from wrapped content
            fontEl.querySelectorAll('span.ql-size-small, span.ql-size-large, span.ql-size-huge').forEach(s => {
                s.classList.remove('ql-size-small', 'ql-size-large', 'ql-size-huge');
            });
            while (fontEl.firstChild) span.appendChild(fontEl.firstChild);
            if (sizeClass) {
                span.classList.add(sizeClass);
            }
            // Also clear inline font-size leftovers
            span.style.fontSize = '';
            fontEl.replaceWith(span);
            if (!sizeClass) {
                // Normal size — unwrap empty class span
                const parent = span.parentNode;
                if (parent) {
                    while (span.firstChild) parent.insertBefore(span.firstChild, span);
                    span.remove();
                }
            }
        });

        // Clean any leftover size classes / inline sizes still selected
        if (!sizeClass && sel.rangeCount) {
            active.cell.querySelectorAll('span.ql-size-small, span.ql-size-large, span.ql-size-huge, span[style*="font-size"]').forEach(el => {
                try {
                    if (!sel.containsNode(el, true)) return;
                } catch (err) {
                    return;
                }
                el.classList.remove('ql-size-small', 'ql-size-large', 'ql-size-huge');
                el.style.fontSize = '';
                if (!el.classList.length && !el.getAttribute('style')) {
                    const parent = el.parentNode;
                    if (!parent) return;
                    while (el.firstChild) parent.insertBefore(el.firstChild, el);
                    el.remove();
                }
            });
        }

        syncWorkspaceNestedTableNode(active.embed, { relayout: false });
        growNestedEmbedToContentAndFitOuter(active.embed);
        scheduleNestedPreviewUpdate();
        return true;
    }

    function applyNestedFontFamily(value) {
        const active = getActiveNestedEmbedAndCell();
        if (!active) return false;
        document.execCommand('styleWithCSS', false, true);
        document.execCommand('fontName', false, value || 'sans-serif');
        syncWorkspaceNestedTableNode(active.embed, { relayout: false });
        scheduleNestedPreviewUpdate();
        return true;
    }

    function applyNestedListFormat(value) {
        const active = getActiveNestedEmbedAndCell();
        if (!active) return false;
        const parts = (active.cell.innerHTML || '').split(/<br\s*\/?>/i);
        const indices = getNestedSelectedLineIndices(active.cell);
        const nextParts = applyListToggleToHtmlFragments(parts, value, indices);
        active.cell.innerHTML = nextParts.join('<br>');
        try {
            const sel = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(active.cell);
            range.collapse(false);
            sel.removeAllRanges();
            sel.addRange(range);
        } catch (err) {
            // ignore
        }
        syncWorkspaceNestedTableNode(active.embed, { relayout: false });
        growNestedEmbedToContentAndFitOuter(active.embed);
        scheduleNestedPreviewUpdate();
        return true;
    }

    function tidyHostCellAroundNestedEmbed(embed) {
        const host = getHostOuterCellForNested(embed);
        if (!host || !embed) return;
        // Nested tables exclusively own their host cell — remove siblings that cause the downward shift
        Array.from(host.childNodes).forEach(node => {
            if (node !== embed) node.remove();
        });
        if (!host.contains(embed)) host.appendChild(embed);
        host.classList.add('ql-has-nested-table');
        // Clear inline offsets so CSS absolute-fill can pin the embed flush
        embed.style.margin = '0';
        embed.style.top = '';
        embed.style.left = '';
        embed.style.position = '';

        // Also prune parchment siblings when possible so Quill delta matches the DOM
        try {
            if (typeof Quill !== 'undefined') {
                const blot = Quill.find(embed, true) || Quill.find(embed);
                if (blot && blot.parent && blot.parent.children) {
                    let child = blot.parent.children.head;
                    while (child) {
                        const next = child.next;
                        if (child !== blot) {
                            try { child.remove(); } catch (err) { /* ignore */ }
                        }
                        child = next;
                    }
                }
            }
        } catch (err) {
            // DOM-only cleanup is still enough for visual alignment
        }
    }

    function scheduleNestedHostRealign(embed) {
        if (!embed) return;
        const run = () => {
            if (!embed.isConnected) return;
            window.__workspaceTableLayoutQuiet = true;
            try {
                tidyHostCellAroundNestedEmbed(embed);
                growNestedEmbedToContentAndFitOuter(embed);
                tidyHostCellAroundNestedEmbed(embed);
            } finally {
                requestAnimationFrame(() => { window.__workspaceTableLayoutQuiet = false; });
            }
        };
        run();
        requestAnimationFrame(() => {
            run();
            setTimeout(run, 50);
            setTimeout(run, 150);
        });
    }

    function lockOuterCellsThatContainNestedTables() {
        if (!workspaceQuillInstance) return;
        workspaceQuillInstance.root.querySelectorAll('td, th').forEach(cell => {
            if (cell.closest('.ql-workspace-nested-table')) return;
            const embed = cell.querySelector('.ql-workspace-nested-table');
            if (embed && getHostOuterCellForNested(embed) === cell) {
                tidyHostCellAroundNestedEmbed(embed);
            } else {
                cell.classList.remove('ql-has-nested-table');
            }
        });
    }

    function isOuterCellExclusiveNestedHost(cell) {
        return !!(cell && cell.classList.contains('ql-has-nested-table')
            && cell.querySelector('.ql-workspace-nested-table')
            && !cell.closest('.ql-workspace-nested-table'));
    }

    function setupNestedExclusiveCellGuards() {
        if (!htmlCanvasEditor || htmlCanvasEditor.dataset.nestedExclusiveGuard === '1') return;
        htmlCanvasEditor.dataset.nestedExclusiveGuard = '1';
        htmlCanvasEditor.addEventListener('beforeinput', function(e) {
            if (isFocusInsideNestedTable()) return;
            const cell = getOuterQuillTableCellAtSelection();
            if (isOuterCellExclusiveNestedHost(cell)) {
                e.preventDefault();
            }
        }, true);
        htmlCanvasEditor.addEventListener('keydown', function(e) {
            if (isFocusInsideNestedTable()) return;
            const cell = getOuterQuillTableCellAtSelection();
            if (!isOuterCellExclusiveNestedHost(cell)) return;
            // Allow navigation / modifiers; block typing and Enter/paste content changes
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Escape', 'Tab', 'Shift'].includes(e.key)) return;
            e.preventDefault();
            e.stopPropagation();
        }, true);
        htmlCanvasEditor.addEventListener('paste', function(e) {
            if (isFocusInsideNestedTable()) return;
            const cell = getOuterQuillTableCellAtSelection();
            if (isOuterCellExclusiveNestedHost(cell)) {
                e.preventDefault();
                e.stopPropagation();
            }
        }, true);
    }

    let nestedPreviewTimer = null;
    function scheduleNestedPreviewUpdate() {
        if (nestedPreviewTimer) clearTimeout(nestedPreviewTimer);
        nestedPreviewTimer = setTimeout(() => {
            nestedPreviewTimer = null;
            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
            }
            updateWorkspaceSimulationPreview();
        }, 180);
    }

    function bindNestedTableCellEvents(node, td) {
        if (!td || td.dataset.nestedBound === '1') return;
        td.dataset.nestedBound = '1';
        td.contentEditable = 'true';
        td.addEventListener('mousedown', (e) => e.stopPropagation());
        td.addEventListener('click', (e) => e.stopPropagation());
        td.addEventListener('dragover', (e) => { e.preventDefault(); e.stopPropagation(); });
        td.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const file = e.dataTransfer && e.dataTransfer.files && Array.from(e.dataTransfer.files).find(f =>
                String(f.type || '').startsWith('image/')
            );
            if (!file) return;
            const reader = new FileReader();
            reader.onload = () => {
                insertNestedImageAt(node, td, null, reader.result);
            };
            reader.readAsDataURL(file);
        });
        td.addEventListener('keydown', (e) => {
            e.stopPropagation();
            // Formatting shortcuts inside nested cells
            if ((e.metaKey || e.ctrlKey) && !e.altKey) {
                const key = (e.key || '').toLowerCase();
                const map = { b: 'bold', i: 'italic', u: 'underline' };
                if (map[key]) {
                    e.preventDefault();
                    document.execCommand(map[key]);
                    syncWorkspaceNestedTableNode(node, { relayout: false });
                    scheduleNestedPreviewUpdate();
                    return;
                }
            }
            if (e.key === 'Enter') {
                e.preventDefault();
                insertNestedLineBreak(td);
                syncWorkspaceNestedTableNode(node, { relayout: false });
                growNestedEmbedToContentAndFitOuter(node);
                scheduleNestedPreviewUpdate();
            }
        });
        td.addEventListener('paste', (e) => {
            e.preventDefault();
            e.stopPropagation();

            // Prefer clipboard image files (screenshots, etc.)
            const items = e.clipboardData && e.clipboardData.items
                ? Array.from(e.clipboardData.items)
                : [];
            const imageItem = items.find(item => item && item.type && item.type.startsWith('image/'));
            if (imageItem) {
                const file = imageItem.getAsFile();
                if (file) {
                    const reader = new FileReader();
                    reader.onload = () => insertNestedImageAt(node, td, null, reader.result);
                    reader.readAsDataURL(file);
                    return;
                }
            }

            const html = (e.clipboardData || window.clipboardData)?.getData('text/html');
            const text = (e.clipboardData || window.clipboardData)?.getData('text/plain') || '';
            if (html && /<(table|video|iframe)\b/i.test(html) && !/<img\b/i.test(html)) {
                const normalized = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
                document.execCommand('insertText', false, normalized);
            } else if (html) {
                const clean = sanitizeNestedCellHtml(html);
                document.execCommand('insertHTML', false, clean || text);
            } else {
                const normalized = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
                // Prefer HTML with BRs for newlines
                const withBreaks = normalized.split('\n').map((p, i) =>
                    (i ? '<br>' : '') + p.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                ).join('');
                document.execCommand('insertHTML', false, withBreaks);
            }
            setTimeout(() => {
                // Strip nested-table and media nodes that freeze Quill; keep nested latex + images
                td.querySelectorAll('table, video, iframe, .ql-formula, .ql-workspace-nested-table').forEach(n => n.remove());
                td.querySelectorAll('img:not(.workspace-nested-image)').forEach(n => {
                    if (isSafeNestedImageSrc(n.getAttribute('src') || '')) {
                        n.className = 'workspace-nested-image';
                        n.setAttribute('contenteditable', 'false');
                    } else {
                        n.remove();
                    }
                });
                syncWorkspaceNestedTableNode(node, { relayout: false });
                growNestedEmbedToContentAndFitOuter(node);
                scheduleNestedPreviewUpdate();
            }, 0);
        });
        td.addEventListener('input', () => {
            td.querySelectorAll('table, video, iframe, .ql-formula, .ql-workspace-nested-table').forEach(n => n.remove());
            td.querySelectorAll('img:not(.workspace-nested-image)').forEach(n => {
                if (isSafeNestedImageSrc(n.getAttribute('src') || '')) {
                    n.className = 'workspace-nested-image';
                    n.setAttribute('contenteditable', 'false');
                } else {
                    n.remove();
                }
            });
            syncWorkspaceNestedTableNode(node, { relayout: false });
            if (node.__growFitTimer) clearTimeout(node.__growFitTimer);
            node.__growFitTimer = setTimeout(() => {
                growNestedEmbedToContentAndFitOuter(node);
                scheduleNestedPreviewUpdate();
            }, 60);
        });
        // Grow outer host when nested images finish loading (after hydrate/reload)
        td.querySelectorAll('img.workspace-nested-image').forEach(img => {
            if (img.dataset.growBound === '1') return;
            img.dataset.growBound = '1';
            const kick = () => {
                growNestedEmbedToContentAndFitOuter(node);
                scheduleNestedPreviewUpdate();
            };
            if (img.complete) {
                // defer so layout has settled after hydrate
                requestAnimationFrame(kick);
            } else {
                img.addEventListener('load', kick, { once: true });
            }
        });
    }

    function markWorkspaceUnsavedAndPreview() {
        if (saveStatusSpan) {
            saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
        }
        updateWorkspaceSimulationPreview();
    }

    function applyNestedInnerLayout(table, colWidths, rowHeights) {
        if (!table) return;
        const widths = (colWidths || []).map(w => Math.max(NESTED_MIN_COL, Math.round(w)));
        const heights = (rowHeights || []).map(h => Math.max(NESTED_MIN_ROW, Math.round(h)));
        const totalW = widths.reduce((a, b) => a + b, 0);
        const totalH = heights.reduce((a, b) => a + b, 0);
        table.style.tableLayout = 'fixed';
        table.style.width = `${totalW}px`;
        table.style.minWidth = `${totalW}px`;
        table.style.height = `${totalH}px`;
        table.style.minHeight = `${totalH}px`;

        let colgroup = table.querySelector(':scope > colgroup');
        if (!colgroup) {
            colgroup = document.createElement('colgroup');
            table.insertBefore(colgroup, table.firstChild);
        }
        while (colgroup.children.length < widths.length) {
            colgroup.appendChild(document.createElement('col'));
        }
        while (colgroup.children.length > widths.length) {
            colgroup.lastElementChild.remove();
        }
        widths.forEach((w, i) => {
            if (colgroup.children[i]) {
                colgroup.children[i].style.width = `${w}px`;
                colgroup.children[i].style.minWidth = `${w}px`;
            }
        });

        const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
        rows.forEach((tr, r) => {
            const h = heights[r] || NESTED_MIN_ROW;
            tr.style.height = `${h}px`;
            tr.style.minHeight = `${h}px`;
            Array.from(tr.children).filter(el => el.matches('td, th')).forEach((td, c) => {
                const w = widths[c] || NESTED_MIN_COL;
                td.style.width = `${w}px`;
                td.style.minWidth = `${w}px`;
                td.style.height = `${h}px`;
                td.style.minHeight = `${h}px`;
            });
        });

        const embed = table.closest('.ql-workspace-nested-table');
        if (embed) {
            embed.style.display = 'block';
            embed.style.verticalAlign = 'top';
            embed.style.margin = '0';
            embed.style.width = `${totalW}px`;
            embed.style.minWidth = `${totalW}px`;
            embed.style.height = `${totalH}px`;
            embed.style.minHeight = `${totalH}px`;
            embed.setAttribute('data-col-widths', widths.join(','));
            embed.setAttribute('data-row-heights', heights.join(','));
        }
    }

    function renderNestedTableIntoNode(node, config) {
        node.innerHTML = '';
        const table = document.createElement('table');
        table.className = 'ql-nested-table-inner';
        if (config.noBorder) table.classList.add('no-border');
        if (config.expandEntities) {
            table.classList.add('ql-table-expand-entities');
            table.setAttribute('data-expand-entities', 'true');
        } else {
            table.classList.remove('ql-table-expand-entities');
            table.setAttribute('data-expand-entities', 'false');
        }
        for (let r = 0; r < config.rows; r++) {
            const tr = document.createElement('tr');
            for (let c = 0; c < config.cols; c++) {
                const td = document.createElement('td');
                fillNestedTdFromHtml(td, config.cells[r][c] || '');
                bindNestedTableCellEvents(node, td);
                tr.appendChild(td);
            }
            table.appendChild(tr);
        }
        node.appendChild(table);
        applyNestedInnerLayout(table, config.colWidths, config.rowHeights);
    }

    function readNestedLayoutFromDom(table) {
        if (!table) return { colWidths: [], rowHeights: [] };
        const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
        const first = rows[0];
        const cells = first ? Array.from(first.children).filter(el => el.matches('td, th')) : [];
        const colgroup = table.querySelector(':scope > colgroup');
        const colWidths = cells.map((cell, i) => {
            const fromCol = colgroup && colgroup.children[i]
                ? parseFloat(colgroup.children[i].style.width)
                : NaN;
            const fromStyle = parseFloat(cell.style.width);
            const w = (!Number.isNaN(fromCol) && fromCol > 0 ? fromCol : null)
                || (!Number.isNaN(fromStyle) && fromStyle > 0 ? fromStyle : null)
                || cell.getBoundingClientRect().width
                || NESTED_MIN_COL;
            return Math.max(NESTED_MIN_COL, Math.round(w));
        });
        const rowHeights = rows.map(tr => {
            const fromStyle = parseFloat(tr.style.height);
            const h = (!Number.isNaN(fromStyle) && fromStyle > 0)
                ? fromStyle
                : (tr.getBoundingClientRect().height || NESTED_MIN_ROW);
            return Math.max(NESTED_MIN_ROW, Math.round(h));
        });
        return { colWidths, rowHeights };
    }

    function syncWorkspaceNestedTableNode(node, options = {}) {
        if (!node) return;
        let table = node.querySelector('table.ql-nested-table-inner');
        if (!table) {
            const config = parseNestedTableConfig(node.getAttribute('data-value') || '');
            renderNestedTableIntoNode(node, config);
            node.setAttribute('data-value', JSON.stringify(config));
            return;
        }
        const cells = [];
        table.querySelectorAll(':scope > tr, :scope > tbody > tr').forEach(tr => {
            const row = [];
            tr.querySelectorAll(':scope > td, :scope > th').forEach(td => row.push(nestedCellHtmlFromTd(td)));
            cells.push(row);
        });
        const layout = readNestedLayoutFromDom(table);
        const config = {
            rows: cells.length,
            cols: cells[0] ? cells[0].length : 0,
            cells,
            colWidths: layout.colWidths,
            rowHeights: layout.rowHeights,
            noBorder: table.classList.contains('no-border'),
            expandEntities: (() => {
                if (table.getAttribute('data-expand-entities') === 'false') return false;
                if (
                    table.classList.contains('ql-table-expand-entities')
                    || table.getAttribute('data-expand-entities') === 'true'
                ) return true;
                return parseNestedTableConfig(node.getAttribute('data-value') || '').expandEntities;
            })()
        };
        node.setAttribute('data-value', JSON.stringify(config));
        if (options.relayout) {
            applyNestedInnerLayout(table, config.colWidths, config.rowHeights);
        }
    }

    function hydrateWorkspaceNestedTableEmbed(node) {
        if (!node) return;
        const config = parseNestedTableConfig(node.getAttribute('data-value') || '');
        const existing = node.querySelector('table.ql-nested-table-inner');
        if (existing) {
            if (config.noBorder) existing.classList.add('no-border');
            if (config.expandEntities) {
                existing.classList.add('ql-table-expand-entities');
                existing.setAttribute('data-expand-entities', 'true');
            } else {
                existing.classList.remove('ql-table-expand-entities');
                existing.setAttribute('data-expand-entities', 'false');
            }
            syncWorkspaceNestedTableNode(node, { relayout: true });
        } else {
            renderNestedTableIntoNode(node, config);
            node.setAttribute('data-value', JSON.stringify(config));
        }
        const table = node.querySelector('table.ql-nested-table-inner');
        if (!table) return;
        const latest = parseNestedTableConfig(node.getAttribute('data-value') || '');
        table.classList.toggle('no-border', !!latest.noBorder);
        table.classList.toggle('ql-table-expand-entities', !!latest.expandEntities);
        table.setAttribute('data-expand-entities', latest.expandEntities ? 'true' : 'false');
        table.querySelectorAll('td').forEach(td => bindNestedTableCellEvents(node, td));
        scheduleNestedHostRealign(node);
    }

    function getHostOuterCellForNested(embed) {
        return embed ? embed.closest('td, th') : null;
    }

    function getOuterTableCellCoords(cell) {
        if (!cell) return null;
        const table = cell.closest('table');
        if (!table || isNestedTableElement(table)) return null;
        const row = cell.parentElement;
        const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
        const rowIndex = rows.indexOf(row);
        const cells = Array.from(row.children).filter(el => el.matches('td, th'));
        const colIndex = cells.indexOf(cell);
        if (rowIndex < 0 || colIndex < 0) return null;
        return { table, row, rows, rowIndex, colIndex, cell };
    }

    function growNestedEmbedToContentAndFitOuter(embed) {
        if (!embed) return;
        const table = embed.querySelector('table.ql-nested-table-inner');
        if (!table) return;
        const config = parseNestedTableConfig(embed.getAttribute('data-value') || '');
        const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));

        // Temporarily release fixed heights so scrollHeight reflects content (newlines, wrap)
        rows.forEach(tr => {
            tr.style.height = 'auto';
            tr.style.minHeight = '';
            Array.from(tr.children).filter(el => el.matches('td, th')).forEach(td => {
                td.style.height = 'auto';
                td.style.minHeight = '';
            });
        });

        config.rowHeights = rows.map(tr => {
            let contentH = NESTED_MIN_ROW;
            Array.from(tr.children).filter(el => el.matches('td, th')).forEach(td => {
                contentH = Math.max(contentH, Math.ceil(td.scrollHeight) || NESTED_MIN_ROW);
            });
            return Math.max(NESTED_MIN_ROW, contentH);
        });

        while (config.colWidths.length < config.cols) config.colWidths.push(Math.max(NESTED_MIN_COL, 48));
        config.colWidths = config.colWidths.slice(0, config.cols);
        config.rows = rows.length;
        config.cols = config.colWidths.length;
        nodeSetNestedConfig(embed, config);
        applyNestedInnerLayout(table, config.colWidths, config.rowHeights);
        tidyHostCellAroundNestedEmbed(embed);
        fitOuterCellToNestedEmbed(embed);
        tidyHostCellAroundNestedEmbed(embed);
    }

    function fitOuterCellToNestedEmbed(embed) {
        if (!embed || !workspaceQuillInstance) return;
        syncWorkspaceNestedTableNode(embed, { relayout: true });
        tidyHostCellAroundNestedEmbed(embed);
        const host = getHostOuterCellForNested(embed);
        const coords = getOuterTableCellCoords(host);
        const inner = embed.querySelector('table.ql-nested-table-inner');
        if (!coords || !inner) return;

        const config = parseNestedTableConfig(embed.getAttribute('data-value') || '');
        const sumW = config.colWidths.reduce((a, b) => a + b, 0);
        const sumH = config.rowHeights.reduce((a, b) => a + b, 0);
        // Use config content sizes only — absolute-fill makes live embed rect mirror the host
        const limits = getTableSizeLimits(coords.table);
        const neededW = Math.max(limits.minCol, sumW);
        const neededH = Math.max(limits.minRow, sumH);

        window.__workspaceTableLayoutQuiet = true;
        try {
            const widths = readLiveColumnWidths(coords.table);
            while (widths.length <= coords.colIndex) widths.push(limits.minCol);
            widths[coords.colIndex] = Math.max(limits.minCol, neededW);
            applyColumnWidths(coords.table, widths);

            const heights = coords.rows.map((tr, i) => {
                if (i === coords.rowIndex) return Math.max(limits.minRow, neededH);
                const fromStyle = parseFloat(tr.style.height);
                return Math.max(
                    limits.minRow,
                    Math.round((!Number.isNaN(fromStyle) && fromStyle > 0) ? fromStyle : (tr.getBoundingClientRect().height || 36))
                );
            });
            heights.forEach((h, i) => {
                if (coords.rows[i]) setRowHeightExclusive(coords.rows[i], h, coords.table);
            });
            persistWorkspaceTableLayoutAttrs(coords.table, widths, heights);
            tidyHostCellAroundNestedEmbed(embed);
            // Re-apply after outer column pass so nested cells keep their own widths
            applyNestedInnerLayout(inner, config.colWidths, config.rowHeights);
            host.style.verticalAlign = 'top';
        } finally {
            requestAnimationFrame(() => { window.__workspaceTableLayoutQuiet = false; });
        }
    }

    function scaleNestedTableToFillHost(embed) {
        if (!embed) return;
        const host = getHostOuterCellForNested(embed);
        const inner = embed.querySelector('table.ql-nested-table-inner');
        if (!host || !inner) return;

        const config = parseNestedTableConfig(embed.getAttribute('data-value') || '');
        const targetW = Math.max(NESTED_MIN_COL * config.cols, Math.round(host.clientWidth) || 0);
        const targetH = Math.max(NESTED_MIN_ROW * config.rows, Math.round(host.clientHeight) || 0);
        if (!targetW || !targetH) return;

        const wSum = config.colWidths.reduce((a, b) => a + b, 0) || config.cols;
        const hSum = config.rowHeights.reduce((a, b) => a + b, 0) || config.rows;
        let colWidths = config.colWidths.map(w => Math.max(NESTED_MIN_COL, Math.round((w / wSum) * targetW)));
        let rowHeights = config.rowHeights.map(h => Math.max(NESTED_MIN_ROW, Math.round((h / hSum) * targetH)));

        // Fix rounding drift so nested exactly fills the host
        const colDrift = targetW - colWidths.reduce((a, b) => a + b, 0);
        if (colWidths.length) colWidths[colWidths.length - 1] = Math.max(NESTED_MIN_COL, colWidths[colWidths.length - 1] + colDrift);
        const rowDrift = targetH - rowHeights.reduce((a, b) => a + b, 0);
        if (rowHeights.length) rowHeights[rowHeights.length - 1] = Math.max(NESTED_MIN_ROW, rowHeights[rowHeights.length - 1] + rowDrift);

        config.colWidths = colWidths;
        config.rowHeights = rowHeights;
        nodeSetNestedConfig(embed, config);
        applyNestedInnerLayout(inner, colWidths, rowHeights);
    }

    function nodeSetNestedConfig(embed, config) {
        embed.setAttribute('data-value', JSON.stringify(config));
    }

    function scaleNestedTablesInOuterTable(table, affectedColIndex = null, affectedRowIndex = null) {
        if (!table || isNestedTableElement(table)) return;
        const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
        rows.forEach((tr, rowIndex) => {
            if (affectedRowIndex != null && rowIndex !== affectedRowIndex) {
                // still scale nests in other rows if column changed
            }
            Array.from(tr.children).filter(el => el.matches('td, th')).forEach((cell, colIndex) => {
                const colHit = affectedColIndex == null || colIndex === affectedColIndex;
                const rowHit = affectedRowIndex == null || rowIndex === affectedRowIndex;
                if (!colHit && !rowHit) return;
                cell.querySelectorAll(':scope > .ql-workspace-nested-table, .ql-workspace-nested-table').forEach(embed => {
                    // Only direct cell embeds — avoid accidental distant matches
                    if (getHostOuterCellForNested(embed) !== cell) return;
                    scaleNestedTableToFillHost(embed);
                });
            });
        });
    }

    function mutateNestedTable(embed, cell, command, arg) {
        if (!embed) return;
        const config = parseNestedTableConfig(embed.getAttribute('data-value') || '');
        const table = embed.querySelector('table.ql-nested-table-inner');
        if (!table) return;

        const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
        const rowEl = cell ? cell.parentElement : rows[0];
        const rowIndex = Math.max(0, rows.indexOf(rowEl));
        const colIndex = cell
            ? Array.from(rowEl.children).filter(el => el.matches('td, th')).indexOf(cell)
            : 0;

        if (command === 'row') {
            if (config.rows >= NESTED_TABLE_SOFT_MAX && (arg === 0 || arg === 1)) return;
            const insertAt = arg === 0 ? rowIndex : rowIndex + 1;
            const newRow = Array.from({ length: config.cols }, () => '');
            config.cells.splice(insertAt, 0, newRow);
            const seedH = config.rowHeights[rowIndex] || NESTED_MIN_ROW;
            config.rowHeights.splice(insertAt, 0, seedH);
            config.rows = config.cells.length;
        } else if (command === 'col') {
            if (config.cols >= NESTED_TABLE_SOFT_MAX && (arg === 0 || arg === 1)) return;
            const insertAt = arg === 0 ? colIndex : colIndex + 1;
            config.cells.forEach(row => row.splice(insertAt, 0, ''));
            const seedW = config.colWidths[colIndex] || NESTED_MIN_COL;
            config.colWidths.splice(insertAt, 0, seedW);
            config.cols = config.cells[0] ? config.cells[0].length : 0;
        } else if (command === 'delete-row') {
            if (config.rows <= 1) return;
            config.cells.splice(rowIndex, 1);
            config.rowHeights.splice(rowIndex, 1);
            config.rows = config.cells.length;
        } else if (command === 'delete-col') {
            if (config.cols <= 1) return;
            config.cells.forEach(row => row.splice(colIndex, 1));
            config.colWidths.splice(colIndex, 1);
            config.cols = config.cells[0] ? config.cells[0].length : 0;
        } else if (command === 'delete-table') {
            const host = getHostOuterCellForNested(embed);
            embed.remove();
            if (host && workspaceQuillInstance) {
                try {
                    workspaceQuillInstance.update('user');
                } catch (err) {
                    // ignore
                }
            }
            markWorkspaceUnsavedAndPreview();
            return;
        } else if (command === 'toggle-borders') {
            const inner = embed.querySelector('table.ql-nested-table-inner');
            if (!inner) return;
            inner.classList.toggle('no-border');
            config.noBorder = inner.classList.contains('no-border');
            nodeSetNestedConfig(embed, config);
            markWorkspaceUnsavedAndPreview();
            return;
        } else if (command === 'toggle-expand-entities') {
            const inner = embed.querySelector('table.ql-nested-table-inner');
            if (!inner) return;
            const currentlyOn = resolveExpandEntitiesFlag(
                config.expandEntities,
                { hasOwnKey: Object.prototype.hasOwnProperty.call(config, 'expandEntities') }
            ) || inner.classList.contains('ql-table-expand-entities')
                || inner.getAttribute('data-expand-entities') === 'true';
            const on = !currentlyOn;
            inner.classList.toggle('ql-table-expand-entities', on);
            inner.setAttribute('data-expand-entities', on ? 'true' : 'false');
            config.expandEntities = on;
            nodeSetNestedConfig(embed, config);
            markWorkspaceUnsavedAndPreview();
            return;
        } else {
            return;
        }

        nodeSetNestedConfig(embed, config);
        renderNestedTableIntoNode(embed, config);
        lockOuterCellsThatContainNestedTables();
        scheduleNestedHostRealign(embed);
        markWorkspaceUnsavedAndPreview();
    }

    function getOuterQuillTableCellAtSelection() {
        if (!workspaceQuillInstance) return null;
        const range = workspaceQuillInstance.getSelection(true);
        if (!range) return null;
        try {
            const [leaf] = workspaceQuillInstance.getLeaf(range.index);
            let node = leaf && leaf.domNode;
            if (node && node.nodeType === Node.TEXT_NODE) node = node.parentElement;
            if (!node || !node.closest) return null;
            const nested = node.closest('.ql-workspace-nested-table');
            if (nested) return nested.closest('td, th');
            const cell = node.closest('td, th');
            if (cell && cell.closest('.ql-workspace-nested-table')) {
                return cell.closest('.ql-workspace-nested-table')?.closest('td, th') || null;
            }
            return cell;
        } catch (err) {
            return null;
        }
    }

    function isSelectionInsideQuillTableCell() {
        if (!workspaceQuillInstance) return false;
        const range = workspaceQuillInstance.getSelection(true);
        if (!range) return false;
        try {
            const [leaf] = workspaceQuillInstance.getLeaf(range.index);
            let node = leaf && leaf.domNode;
            if (node && node.nodeType === Node.TEXT_NODE) node = node.parentElement;
            if (!node || !node.closest) return false;
            if (node.closest('.ql-workspace-nested-table')) return false;
            const cell = node.closest('td, th');
            return !!(cell && !isNestedTableElement(cell.closest('table')));
        } catch (err) {
            return false;
        }
    }

    function insertSoftBreakInQuillTableCell(range) {
        if (!workspaceQuillInstance || !range) return false;
        try {
            // Soft break + ZWSP keeps a real caret target on the next visual line
            workspaceQuillInstance.insertEmbed(range.index, 'softBreak', true, Quill.sources.USER);
            workspaceQuillInstance.insertText(range.index + 1, '\u200b', Quill.sources.USER);
            workspaceQuillInstance.setSelection(range.index + 2, 0, Quill.sources.SILENT);
            return true;
        } catch (err) {
            return false;
        }
    }

    function readQuillRangeAsLines(index, length) {
        if (!workspaceQuillInstance || length <= 0) return [''];
        const delta = workspaceQuillInstance.getContents(index, length);
        const lines = [''];
        (delta.ops || []).forEach(op => {
            if (typeof op.insert === 'string') {
                const parts = op.insert.replace(/\r/g, '').split('\n');
                lines[lines.length - 1] += parts[0];
                for (let i = 1; i < parts.length; i++) lines.push(parts[i]);
            } else if (op.insert && (op.insert.softBreak || op.insert.break)) {
                lines.push('');
            }
        });
        if (lines.length > 1 && lines[lines.length - 1] === '') lines.pop();
        return lines;
    }

    function applyListFormattingInsideTableCell(value) {
        if (!workspaceQuillInstance || !isSelectionInsideQuillTableCell()) return false;
        const cell = getOuterQuillTableCellAtSelection();
        if (!cell) return false;

        let blot;
        try {
            blot = Quill.find(cell, true) || Quill.find(cell);
        } catch (err) {
            blot = null;
        }
        if (!blot || typeof blot.offset !== 'function') return false;

        const cellStart = blot.offset(workspaceQuillInstance.scroll);
        const cellLength = Math.max(0, blot.length() - 1);
        const lineInfos = [];
        const delta = workspaceQuillInstance.getContents(cellStart, cellLength);
        let offset = cellStart;
        let lineStart = cellStart;
        let lineText = '';
        (delta.ops || []).forEach(op => {
            if (typeof op.insert === 'string') {
                lineText += op.insert.replace(/\r/g, '');
                offset += op.insert.length;
            } else if (op.insert && (op.insert.softBreak || op.insert.break)) {
                lineInfos.push({ start: lineStart, end: offset, text: lineText });
                offset += 1;
                lineStart = offset;
                lineText = '';
            } else if (op.insert && typeof op.insert === 'object') {
                offset += 1;
            }
        });
        lineInfos.push({ start: lineStart, end: offset, text: lineText });

        const sel = workspaceQuillInstance.getSelection(true) || { index: cellStart, length: 0 };
        const selStart = Math.max(cellStart, sel.index);
        const selEnd = Math.max(selStart, Math.min(cellStart + cellLength, sel.index + Math.max(sel.length, 0)));
        const selectedIndices = [];
        lineInfos.forEach((line, i) => {
            if (sel.length === 0) {
                if (selStart >= line.start && selStart <= line.end) selectedIndices.push(i);
            } else if (selEnd > line.start && selStart < line.end) {
                selectedIndices.push(i);
            }
        });
        if (!selectedIndices.length) {
            const idx = lineInfos.findIndex(line => selStart >= line.start && selStart <= line.end);
            selectedIndices.push(idx >= 0 ? idx : 0);
        }

        const selectedPlains = selectedIndices
            .map(i => (lineInfos[i]?.text || '').replace(/^\u200b+/g, ''))
            .filter(l => l.trim().length);
        const isBullet = selectedPlains.length > 0 && selectedPlains.every(l => /^•\s/.test(l));
        const isOrdered = selectedPlains.length > 0 && selectedPlains.every(l => /^\d+\.\s/.test(l));

        // Prefix-only edits (high → low) preserve inline formatting on each line
        const selectedAsc = [...selectedIndices].sort((a, b) => a - b);
        const orderedAssign = new Map();
        if (value === 'ordered' && !isOrdered) {
            const plains = lineInfos.map(line => (line.text || '').replace(/^\u200b+/g, ''));
            let n = resolveOrderedStartNumber(plains, selectedAsc.filter(i => {
                const plain = plains[i] || '';
                return !!plain.trim();
            }));
            selectedAsc.forEach(i => {
                const plain = plains[i] || '';
                if (plain.trim()) orderedAssign.set(i, n++);
            });
        }

        [...selectedIndices].sort((a, b) => b - a).forEach(i => {
            const line = lineInfos[i];
            if (!line) return;
            const plain = (line.text || '').replace(/^\u200b+/g, '');
            if (!plain.trim()) return;
            const existing = getLeadingListPrefix(plain);
            if (existing) {
                workspaceQuillInstance.deleteText(line.start, existing.length, Quill.sources.USER);
            }
            if (value === 'bullet' && !isBullet) {
                workspaceQuillInstance.insertText(line.start, '• ', Quill.sources.USER);
            } else if (value === 'ordered' && !isOrdered) {
                const n = orderedAssign.get(i) || 1;
                workspaceQuillInstance.insertText(line.start, `${n}. `, Quill.sources.USER);
            }
        });

        workspaceQuillInstance.setSelection(selStart, 0, Quill.sources.SILENT);
        markWorkspaceUnsavedAndPreview();
        return true;
    }

    function registerWorkspaceSoftBreakBlot() {
        if (typeof Quill === 'undefined' || window.__workspaceSoftBreakRegistered) return;
        const Embed = Quill.import('blots/embed');
        class SoftBreak extends Embed {
            static blotName = 'softBreak';
            static className = 'ql-soft-break';
            static tagName = 'SPAN';
            static create() {
                const node = super.create();
                node.classList.add('ql-soft-break');
                node.setAttribute('contenteditable', 'false');
                return node;
            }
            static value() {
                return true;
            }
            length() {
                return 1;
            }
        }
        Quill.register(SoftBreak, true);
        window.__workspaceSoftBreakRegistered = true;
    }

    function setupWorkspaceTableCellPasteHandler() {
        if (!workspaceQuillInstance || workspaceQuillInstance.root.dataset.tablePasteBound === '1') return;
        workspaceQuillInstance.root.dataset.tablePasteBound = '1';
        workspaceQuillInstance.root.addEventListener('paste', function(e) {
            if (!isSelectionInsideQuillTableCell()) return;
            const text = (e.clipboardData || window.clipboardData)?.getData('text/plain');
            if (!text || (!text.includes('\n') && !text.includes('\r'))) return;
            e.preventDefault();
            e.stopPropagation();
            const range = workspaceQuillInstance.getSelection(true);
            if (!range) return;
            if (range.length) {
                workspaceQuillInstance.deleteText(range.index, range.length, Quill.sources.USER);
            }
            const lines = String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');
            let cursor = range.index;
            lines.forEach((line, i) => {
                if (i > 0) {
                    workspaceQuillInstance.insertEmbed(cursor, 'softBreak', true, Quill.sources.USER);
                    cursor += 1;
                }
                if (line) {
                    workspaceQuillInstance.insertText(cursor, line, Quill.sources.USER);
                    cursor += line.length;
                }
            });
            workspaceQuillInstance.setSelection(cursor, 0, Quill.sources.SILENT);
            markWorkspaceUnsavedAndPreview();
        }, true);
    }

    function makeQuillTableRowId(seed = '') {
        return `row-${seed}${Math.random().toString(36).slice(2, 6)}`;
    }

    function isCorruptQuillRowId(value) {
        return !value || value === '[object Object]' || value === 'true' || String(value).startsWith('{');
    }

    /**
     * Quill groups cells by data-row. Identical / corrupted ids collapse a grid into one row.
     * Normalize each HTML <tr> to a unique shared row id before paste/save.
     */
    function normalizeQuillTableHtml(rawHtml) {
        let cleanHtml = (rawHtml || '').trim() || '<p><br></p>';
        try {
            const tempParser = new DOMParser();
            const doc = tempParser.parseFromString(cleanHtml, 'text/html');

            doc.querySelectorAll('.ql-formula').forEach(formula => {
                formula.innerHTML = '';
                let nextSibling = formula.nextSibling;
                while (nextSibling && (
                    (nextSibling.nodeType === Node.ELEMENT_NODE && (
                        nextSibling.classList.contains('katex-html') ||
                        nextSibling.classList.contains('katex')
                    )) ||
                    (nextSibling.nodeType === Node.TEXT_NODE && !nextSibling.textContent.trim())
                )) {
                    const toRemove = nextSibling;
                    nextSibling = nextSibling.nextSibling;
                    if (toRemove.nodeType === Node.ELEMENT_NODE) {
                        toRemove.remove();
                    }
                }
            });

            doc.querySelectorAll('table').forEach(table => {
                if (isNestedTableElement(table)) return;
                if (table.getAttribute('data-no-border') === 'true' || table.classList.contains('no-border')) {
                    table.classList.add('no-border');
                    table.setAttribute('data-no-border', 'true');
                }
                if (table.getAttribute('data-compact-cells') === 'true' || table.classList.contains('ql-table-compact')) {
                    table.classList.add('ql-table-compact');
                    table.setAttribute('data-compact-cells', 'true');
                }
                if (table.getAttribute('data-expand-entities') === 'false') {
                    table.classList.remove('ql-table-expand-entities');
                    table.setAttribute('data-expand-entities', 'false');
                } else {
                    table.classList.add('ql-table-expand-entities');
                    table.setAttribute('data-expand-entities', 'true');
                }
                const align = table.getAttribute('data-table-align');
                if (align) {
                    table.classList.remove('ql-table-align-left', 'ql-table-align-center', 'ql-table-align-right');
                    table.classList.add(`ql-table-align-${align}`);
                }

                const usedIds = new Set();
                table.querySelectorAll(':scope > tr, :scope > tbody > tr').forEach((tr, rowIndex) => {
                    const cells = Array.from(tr.querySelectorAll(':scope > td, :scope > th'));
                    if (!cells.length) return;

                    let rowId = cells.map(c => c.getAttribute('data-row')).find(id => !isCorruptQuillRowId(id) && !usedIds.has(id));
                    if (!rowId) {
                        rowId = makeQuillTableRowId(`${rowIndex}-`);
                    }
                    usedIds.add(rowId);
                    cells.forEach(td => td.setAttribute('data-row', rowId));
                });

                // Empty cells that only hold soft-break embeds are not clickable after
                // reload — restore Quill's normal empty-cell <br>.
                table.querySelectorAll(':scope > tr > td, :scope > tr > th, :scope > tbody > tr > td, :scope > tbody > tr > th').forEach(cell => {
                    if (cell.classList.contains('ql-has-nested-table')) return;
                    if (cell.querySelector('.ql-workspace-nested-table')) return;
                    const plain = (cell.textContent || '').replace(/[\u200B\uFEFF]/g, '').trim();
                    if (plain.length) return;
                    const hasNonBreakEl = Array.from(cell.children).some(el =>
                        !el.classList.contains('ql-soft-break') && el.tagName !== 'BR'
                    );
                    if (hasNonBreakEl) return;
                    if (cell.querySelector('.ql-soft-break')) {
                        cell.innerHTML = '<br>';
                    }
                });
            });

            // Keep nested-table embeds hydrated from data-value for save/preview HTML
            doc.querySelectorAll('.ql-workspace-nested-table').forEach(node => {
                syncWorkspaceNestedTableNode(node);
            });

            cleanHtml = doc.body.innerHTML || '<p><br></p>';
        } catch (err) {
            console.warn('Failed normalizing workspace Quill tables:', err);
        }
        return cleanHtml;
    }

    function loadWorkspaceQuillHtml(rawHtml) {
        if (!workspaceQuillInstance) return;
        const cleanHtml = normalizeQuillTableHtml(rawHtml);

        // Quill rebuilds <table> nodes from deltas and drops custom attrs — capture first.
        let tableMetas = [];
        try {
            const metaDoc = new DOMParser().parseFromString(cleanHtml, 'text/html');
            tableMetas = queryWorkspaceQuillTables(metaDoc).map(t => ({
                colWidths: t.getAttribute('data-col-widths'),
                rowHeights: t.getAttribute('data-row-heights'),
                align: t.getAttribute('data-table-align'),
                noBorder: t.getAttribute('data-no-border') === 'true' || t.classList.contains('no-border'),
                compact: t.getAttribute('data-compact-cells') === 'true' || t.classList.contains('ql-table-compact'),
                expandEntities: t.getAttribute('data-expand-entities') !== 'false'
            }));
        } catch (err) {
            tableMetas = [];
        }

        // setText / paste / update fire text-change → preview; suppress until layout settles
        window.__workspacePreviewQuiet = true;
        try {
            workspaceQuillInstance.setText('');
            workspaceQuillInstance.clipboard.dangerouslyPasteHTML(0, cleanHtml);
        } catch (pasteErr) {
            window.__workspacePreviewQuiet = false;
            throw pasteErr;
        }

        setTimeout(() => {
            if (!workspaceQuillInstance) {
                window.__workspacePreviewQuiet = false;
                return;
            }
            try {
                const tableModule = workspaceQuillInstance.getModule('table');
                if (tableModule && typeof tableModule.balanceTables === 'function') {
                    tableModule.balanceTables();
                }

                const liveTables = queryWorkspaceQuillTables(workspaceQuillInstance.root);
                liveTables.forEach((table, i) => {
                    const meta = tableMetas[i];
                    if (!meta) return;
                    if (meta.colWidths) table.setAttribute('data-col-widths', meta.colWidths);
                    if (meta.rowHeights) table.setAttribute('data-row-heights', meta.rowHeights);
                    if (meta.align) table.setAttribute('data-table-align', meta.align);
                    if (meta.noBorder) table.setAttribute('data-no-border', 'true');
                    if (meta.compact) table.setAttribute('data-compact-cells', 'true');
                    if (meta.expandEntities === false) {
                        table.classList.remove('ql-table-expand-entities');
                        table.setAttribute('data-expand-entities', 'false');
                    } else {
                        table.classList.add('ql-table-expand-entities');
                        table.setAttribute('data-expand-entities', 'true');
                    }
                    reapplyWorkspaceTableLayout(table);
                });

                // Restore interactive cells on nested embeds after Quill paste
                workspaceQuillInstance.root.querySelectorAll('.ql-workspace-nested-table').forEach(node => {
                    hydrateWorkspaceNestedTableEmbed(node);
                });

                workspaceQuillInstance.update('user');
                lockOuterCellsThatContainNestedTables();
                repairOrphanSoftBreakEmptyOuterCells();
                workspaceQuillInstance.root.querySelectorAll('.ql-workspace-nested-table').forEach(node => {
                    scheduleNestedHostRealign(node);
                });
            } finally {
                window.__workspacePreviewQuiet = false;
                updateWorkspaceSimulationPreview();
            }
        }, 50);
    }

    /** Remove softBreak-only empty outer cells left from older saves / clipboard matchers. */
    function repairOrphanSoftBreakEmptyOuterCells() {
        if (!workspaceQuillInstance) return;
        const cells = Array.from(workspaceQuillInstance.root.querySelectorAll('td, th')).filter(cell => {
            if (cell.closest('.ql-workspace-nested-table')) return false;
            if (cell.classList.contains('ql-has-nested-table')) return false;
            if (!isEmptyOuterQuillCell(cell)) return false;
            return !!cell.querySelector(':scope > .ql-soft-break, .ql-soft-break');
        });
        cells.forEach(cell => {
            try {
                let blot = Quill.find(cell, true) || Quill.find(cell);
                if (!blot || typeof blot.offset !== 'function') return;
                const start = blot.offset(workspaceQuillInstance.scroll);
                const len = Math.max(0, blot.length() - 1);
                if (len > 0) {
                    workspaceQuillInstance.deleteText(start, len, Quill.sources.SILENT);
                }
            } catch (err) {
                // Last resort: clear DOM and let Quill reconcile
                cell.innerHTML = '<br>';
            }
        });
        if (cells.length) {
            try {
                workspaceQuillInstance.update('silent');
            } catch (err) {
                // ignore
            }
        }
    }

    function getTableSizeLimits(table) {
        const compact = !!(table && (
            table.classList.contains('ql-table-compact') ||
            table.getAttribute('data-compact-cells') === 'true'
        ));
        return compact
            ? { minCol: 14, minRow: 16 }
            : { minCol: 40, minRow: 28 };
    }

    function getWorkspaceQuillHtmlForSave() {
        if (!workspaceQuillInstance) return '';
        // Capture current layout markers onto the live DOM before serializing
        queryWorkspaceQuillTables(workspaceQuillInstance.root).forEach(table => {
            persistWorkspaceTableLayoutAttrs(table);
        });
        workspaceQuillInstance.root.querySelectorAll('.ql-workspace-nested-table').forEach(node => {
            syncWorkspaceNestedTableNode(node);
        });
        return normalizeQuillTableHtml(workspaceQuillInstance.root.innerHTML.trim());
    }

    function persistWorkspaceTableLayoutAttrs(table, widthOverride = null, heightOverride = null) {
        if (!table) return;
        if (table.classList.contains('no-border')) {
            table.setAttribute('data-no-border', 'true');
        } else {
            table.removeAttribute('data-no-border');
        }

        if (table.classList.contains('ql-table-compact')) {
            table.setAttribute('data-compact-cells', 'true');
        } else {
            table.removeAttribute('data-compact-cells');
        }

        if (table.getAttribute('data-expand-entities') === 'false') {
            table.classList.remove('ql-table-expand-entities');
            table.setAttribute('data-expand-entities', 'false');
        } else {
            // Default on (missing attr or true)
            table.classList.add('ql-table-expand-entities');
            table.setAttribute('data-expand-entities', 'true');
        }

        ['left', 'center', 'right'].forEach(align => {
            if (table.classList.contains(`ql-table-align-${align}`)) {
                table.setAttribute('data-table-align', align);
            }
        });

        const { minCol } = getTableSizeLimits(table);
        const firstRow = table.querySelector('tr');
        if (!firstRow) return;
        const cells = Array.from(firstRow.children).filter(el => el.matches('td, th'));
        const colCount = cells.length;
        if (!colCount) return;

        let widths = Array.isArray(widthOverride) ? widthOverride : null;
        if (!widths || widths.length !== colCount) {
            const colgroup = table.querySelector(':scope > colgroup');
            widths = [];
            for (let i = 0; i < colCount; i++) {
                const col = colgroup ? colgroup.children[i] : null;
                const cell = cells[i];
                const fromCol = col ? parseFloat(col.style.width) : NaN;
                const fromCellStyle = cell ? parseFloat(cell.style.width) : NaN;
                const fromData = (table.getAttribute('data-col-widths') || '').split(',').map(v => parseFloat(v))[i];
                const width = (!Number.isNaN(fromCol) && fromCol > 0 ? fromCol : null)
                    || (!Number.isNaN(fromCellStyle) && fromCellStyle > 0 ? fromCellStyle : null)
                    || (!Number.isNaN(fromData) && fromData > 0 ? fromData : null)
                    || (cell && cell.getBoundingClientRect().width)
                    || 100;
                widths.push(Math.max(minCol, Math.round(width)));
            }
        } else {
            widths = widths.map(w => Math.max(minCol, Math.round(w)));
        }

        table.setAttribute('data-col-widths', widths.join(','));
        const total = widths.reduce((a, b) => a + b, 0);
        table.style.width = `${total}px`;
        table.style.minWidth = `${total}px`;
        table.style.maxWidth = 'none';

        const { minRow } = getTableSizeLimits(table);
        let heights = Array.isArray(heightOverride) ? heightOverride : null;
        if (!heights) {
            heights = [];
            table.querySelectorAll(':scope > tr, :scope > tbody > tr').forEach(tr => {
                const fromStyle = parseFloat(tr.style.height);
                const h = (!Number.isNaN(fromStyle) && fromStyle > 0)
                    ? fromStyle
                    : (tr.getBoundingClientRect().height || 36);
                heights.push(Math.max(minRow, Math.round(h)));
            });
        } else {
            heights = heights.map(h => Math.max(minRow, Math.round(h)));
        }
        if (heights.length) {
            table.setAttribute('data-row-heights', heights.join(','));
        }
    }

    function reapplyWorkspaceTableLayout(table) {
        if (!table) return;

        if (table.getAttribute('data-no-border') === 'true') {
            table.classList.add('no-border');
        }
        if (table.getAttribute('data-compact-cells') === 'true') {
            table.classList.add('ql-table-compact');
        } else {
            table.classList.remove('ql-table-compact');
        }
        if (table.getAttribute('data-expand-entities') === 'false') {
            table.classList.remove('ql-table-expand-entities');
        } else {
            table.classList.add('ql-table-expand-entities');
            if (table.getAttribute('data-expand-entities') !== 'false') {
                table.setAttribute('data-expand-entities', 'true');
            }
        }

        const align = table.getAttribute('data-table-align');
        table.classList.remove('ql-table-align-left', 'ql-table-align-center', 'ql-table-align-right');
        if (align) {
            table.classList.add(`ql-table-align-${align}`);
        }

        const { minCol } = getTableSizeLimits(table);
        const widthAttr = table.getAttribute('data-col-widths');
        if (widthAttr) {
            const widths = widthAttr.split(',').map(v => parseFloat(v)).filter(n => !Number.isNaN(n) && n > 0);
            if (widths.length) {
                applyColumnWidths(table, widths.map(w => Math.max(minCol, w)));
            }
        }

        const heightAttr = table.getAttribute('data-row-heights');
        if (heightAttr) {
            const heights = heightAttr.split(',').map(v => parseFloat(v)).filter(n => !Number.isNaN(n) && n > 0);
            const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
            heights.forEach((h, i) => {
                if (rows[i]) setRowHeightExclusive(rows[i], h, table);
            });
        }
    }

    function reapplyAllWorkspaceTableLayouts() {
        if (!workspaceQuillInstance) return;
        queryWorkspaceQuillTables(workspaceQuillInstance.root).forEach(table => {
            reapplyWorkspaceTableLayout(table);
        });
    }

    function clearWorkspaceTableSelection() {
        if (selectedWorkspaceTable) {
            selectedWorkspaceTable.classList.remove('ql-table-object-selected');
        }
        selectedWorkspaceTable = null;
        if (workspaceQuillInstance) {
            workspaceQuillInstance.root.querySelectorAll('table.ql-table-object-selected').forEach(t => {
                t.classList.remove('ql-table-object-selected');
            });
        }
    }

    function selectWorkspaceTable(table) {
        if (!table || isNestedTableElement(table) || !workspaceQuillInstance || !workspaceQuillInstance.root.contains(table)) return;
        clearWorkspaceTableSelection();
        hideWorkspaceTableHoverTip();
        selectedWorkspaceTable = table;
        table.classList.add('ql-table-object-selected');
        // Blur cell caret so toolbar align clearly targets the table object
        try {
            workspaceQuillInstance.setSelection(null);
        } catch (err) {
            // ignore
        }
    }

    function isWorkspaceTableSelectHotspot(table, clientX, clientY) {
        if (!table || isNestedTableElement(table)) return false;
        const rect = table.getBoundingClientRect();
        // Top-left of first cell (⧉ cue lives inside the cell to avoid table ::before)
        return clientX >= rect.left
            && clientX <= rect.left + 24
            && clientY >= rect.top
            && clientY <= rect.top + 24;
    }

    function ensureWorkspaceTableHoverTip() {
        let tip = document.getElementById('workspace-quill-table-hover-tip');
        if (!tip) {
            tip = document.createElement('div');
            tip.id = 'workspace-quill-table-hover-tip';
            tip.textContent = '🖱️ Right-click cells for row/column options';
            document.body.appendChild(tip);
        }
        return tip;
    }

    function hideWorkspaceTableHoverTip() {
        const tip = document.getElementById('workspace-quill-table-hover-tip');
        if (tip) tip.style.display = 'none';
    }

    function showWorkspaceTableHoverTip(table) {
        if (!table || isNestedTableElement(table) || table.classList.contains('ql-table-object-selected')) {
            hideWorkspaceTableHoverTip();
            return;
        }
        const tip = ensureWorkspaceTableHoverTip();
        const rect = table.getBoundingClientRect();
        tip.style.display = 'block';
        // Prefer above the table; if clipped by viewport, place just inside top-left.
        let top = rect.top - 24;
        let left = rect.left + 28;
        if (top < 8) top = rect.top + 4;
        const tipWidth = tip.offsetWidth || 280;
        if (left + tipWidth > window.innerWidth - 8) {
            left = Math.max(8, window.innerWidth - tipWidth - 8);
        }
        tip.style.top = `${top}px`;
        tip.style.left = `${left}px`;
    }

    function setupWorkspaceTableHoverTip() {
        if (!htmlCanvasEditor || htmlCanvasEditor.dataset.tableHoverTipBound === '1') return;
        htmlCanvasEditor.dataset.tableHoverTipBound = '1';
        htmlCanvasEditor.addEventListener('mouseover', function(e) {
            const table = e.target.closest && e.target.closest('table');
            if (!table || !workspaceQuillInstance?.root.contains(table) || isNestedTableElement(table)) {
                return;
            }
            showWorkspaceTableHoverTip(table);
        });
        htmlCanvasEditor.addEventListener('mouseout', function(e) {
            const fromTable = e.target.closest && e.target.closest('table');
            const toTable = e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('table');
            if (fromTable && fromTable !== toTable) {
                hideWorkspaceTableHoverTip();
            }
        });
        htmlCanvasEditor.addEventListener('scroll', hideWorkspaceTableHoverTip, true);
        window.addEventListener('scroll', hideWorkspaceTableHoverTip, true);
    }

    function applyWorkspaceTableAlignment(value, tableArg = null) {
        const table = tableArg || selectedWorkspaceTable;
        if (!table || !workspaceQuillInstance || !workspaceQuillInstance.root.contains(table)) {
            return false;
        }

        table.classList.remove('ql-table-align-left', 'ql-table-align-center', 'ql-table-align-right');
        if (value) {
            table.classList.add(`ql-table-align-${value}`);
            table.setAttribute('data-table-align', value);
        } else {
            table.removeAttribute('data-table-align');
        }
        persistWorkspaceTableLayoutAttrs(table);
        updateWorkspaceSimulationPreview();
        if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
        return true;
    }

    function isEmptyOuterQuillCell(cell) {
        if (!cell || cell.classList.contains('ql-has-nested-table')) return false;
        if (cell.closest('.ql-workspace-nested-table')) return false;
        const table = cell.closest('table');
        if (!table || isNestedTableElement(table)) return false;
        if (cell.querySelector('img, .ql-formula, video, iframe, .ql-workspace-nested-table')) return false;
        const plain = (cell.textContent || '').replace(/[\u200B\uFEFF]/g, '').trim();
        return plain.length === 0;
    }

    function getOuterQuillCellFromPoint(clientX, clientY) {
        if (!workspaceQuillInstance) return null;
        const stack = (typeof document.elementsFromPoint === 'function')
            ? document.elementsFromPoint(clientX, clientY)
            : [document.elementFromPoint(clientX, clientY)].filter(Boolean);
        for (const el of stack) {
            if (!(el && el.closest)) continue;
            if (el.closest('.ql-workspace-nested-table')) continue;
            const cell = el.closest('td, th');
            if (!cell || !workspaceQuillInstance.root.contains(cell)) continue;
            if (cell.classList.contains('ql-has-nested-table')) continue;
            const table = cell.closest('table');
            if (!table || isNestedTableElement(table)) continue;
            return cell;
        }
        return null;
    }

    function distanceToCellEdges(clientX, clientY, cell) {
        const r = cell.getBoundingClientRect();
        return Math.min(
            clientX - r.left,
            r.right - clientX,
            clientY - r.top,
            r.bottom - clientY
        );
    }

    function placeCaretInOuterTableCell(cell) {
        if (!workspaceQuillInstance || !cell) return false;
        try {
            // Loaded empty cells may only contain softBreak embeds — clear them so Quill
            // can host a real caret (same as a fresh `<br>` empty cell).
            if (
                isEmptyOuterQuillCell(cell) &&
                cell.querySelector('.ql-soft-break')
            ) {
                let blotClear = Quill.find(cell, true) || Quill.find(cell);
                if (blotClear && typeof blotClear.offset === 'function') {
                    const start = blotClear.offset(workspaceQuillInstance.scroll);
                    const len = Math.max(0, blotClear.length() - 1);
                    if (len > 0) {
                        workspaceQuillInstance.deleteText(start, len, Quill.sources.SILENT);
                    }
                }
            }

            workspaceQuillInstance.focus();
            let blot = null;
            const br = cell.querySelector(':scope > br, br');
            if (br) blot = Quill.find(br, true) || Quill.find(br);
            if (!blot) blot = Quill.find(cell, true) || Quill.find(cell);
            if (blot && typeof blot.offset === 'function') {
                const index = blot.offset(workspaceQuillInstance.scroll);
                workspaceQuillInstance.setSelection(index, 0, Quill.sources.USER);
                return true;
            }
            // Fallback when Quill blot lookup fails on sparse empty cells
            const sel = window.getSelection();
            if (!sel) return false;
            const range = document.createRange();
            range.selectNodeContents(cell);
            range.collapse(true);
            sel.removeAllRanges();
            sel.addRange(range);
            return true;
        } catch (err) {
            return false;
        }
    }

    function setupEmptyOuterTableCellClick() {
        if (!htmlCanvasEditor || htmlCanvasEditor.dataset.emptyOuterCellClick === '1') return;
        htmlCanvasEditor.dataset.emptyOuterCellClick = '1';

        const RESIZE_EDGE_RESERVE = 4;

        function tryPlaceCaretFromPointer(e) {
            if (!workspaceQuillInstance || e.button !== 0 || e.altKey) return false;
            if (e.target.closest && e.target.closest('.ql-workspace-nested-table')) return false;

            const cell = getOuterQuillCellFromPoint(e.clientX, e.clientY)
                || (e.target.closest && e.target.closest('td, th'));
            if (!cell || !workspaceQuillInstance.root.contains(cell)) return false;
            if (!isEmptyOuterQuillCell(cell)) return false;

            // Leave a thin strip for column/row resize handles
            if (distanceToCellEdges(e.clientX, e.clientY, cell) <= RESIZE_EDGE_RESERVE) return false;

            // Do not stop/prevent the event — letting it reach the cell keeps
            // contenteditable + Quill caret placement working. Resize skips these
            // clicks via the deep-inside-outer-cell guard. We only reinforce the caret.
            clearWorkspaceTableSelection();
            hideWorkspaceTableHoverTip();

            const placed = placeCaretInOuterTableCell(cell);
            if (!placed) {
                requestAnimationFrame(() => placeCaretInOuterTableCell(cell));
            } else {
                requestAnimationFrame(() => {
                    placeCaretInOuterTableCell(cell);
                });
            }
            return true;
        }

        // Capture before resize so caret placement runs even if a false resize
        // claim later calls stopImmediatePropagation (guarded separately below).
        htmlCanvasEditor.addEventListener('mousedown', tryPlaceCaretFromPointer, true);
        // Backup: some empty cells only settle a caret on click
        htmlCanvasEditor.addEventListener('click', function(e) {
            if (!workspaceQuillInstance || e.button !== 0 || e.altKey) return;
            if (e.target.closest && e.target.closest('.ql-workspace-nested-table')) return;
            const cell = getOuterQuillCellFromPoint(e.clientX, e.clientY)
                || (e.target.closest && e.target.closest('td, th'));
            if (!isEmptyOuterQuillCell(cell)) return;
            if (distanceToCellEdges(e.clientX, e.clientY, cell) <= RESIZE_EDGE_RESERVE) return;
            const range = workspaceQuillInstance.getSelection(true);
            if (range) {
                try {
                    const [leaf] = workspaceQuillInstance.getLeaf(range.index);
                    let node = leaf && leaf.domNode;
                    if (node && node.nodeType === Node.TEXT_NODE) node = node.parentElement;
                    if (node && cell.contains(node)) return; // already in this cell
                } catch (err) {
                    // fall through and place
                }
            }
            placeCaretInOuterTableCell(cell);
        }, true);
    }

    function setupWorkspaceTableObjectSelection() {
        if (tableObjectSelectionBound || !htmlCanvasEditor) return;
        tableObjectSelectionBound = true;

        htmlCanvasEditor.addEventListener('mousedown', function(e) {
            if (!workspaceQuillInstance || e.button !== 0) return;
            if (e.target.closest && e.target.closest('.ql-workspace-nested-table')) return;
            const table = e.target.closest && e.target.closest('table');
            if (table && isNestedTableElement(table)) return;

            // Alt/Option-click anywhere on a table selects the whole table object
            if (table && e.altKey) {
                e.preventDefault();
                e.stopPropagation();
                selectWorkspaceTable(table);
                return;
            }

            if (table && isWorkspaceTableSelectHotspot(table, e.clientX, e.clientY)) {
                e.preventDefault();
                e.stopPropagation();
                selectWorkspaceTable(table);
                return;
            }

            // Clicking inside a cell edits that cell — clear whole-table selection
            if (e.target.closest && e.target.closest('td, th')) {
                clearWorkspaceTableSelection();
                hideWorkspaceTableHoverTip();
                return;
            }

            // Click outside tables clears selection
            if (!table) {
                clearWorkspaceTableSelection();
                hideWorkspaceTableHoverTip();
            }
        }, true);

        if (workspaceQuillInstance) {
            workspaceQuillInstance.on('selection-change', function(range) {
                if (!range || !selectedWorkspaceTable) return;
                // If the user places a caret inside any cell, drop table-object selection
                try {
                    const [leaf] = workspaceQuillInstance.getLeaf(range.index);
                    let node = leaf && leaf.domNode ? leaf.domNode : null;
                    if (node && node.nodeType === Node.TEXT_NODE) node = node.parentElement;
                    if (node && node.closest && node.closest('td, th')) {
                        clearWorkspaceTableSelection();
                    }
                } catch (err) {
                    // ignore
                }
            });
        }
    }

    function hideWorkspaceTableSizePicker() {
        if (!tableSizePicker) return;
        tableSizePicker.style.display = 'none';
        tableSizePicker.setAttribute('aria-hidden', 'true');
    }

    function updateTableSizePickerHighlight(rows, cols) {
        tableSizeHover = {
            rows: Math.max(1, Math.min(TABLE_SIZE_MAX, rows)),
            cols: Math.max(1, Math.min(TABLE_SIZE_MAX, cols))
        };
        if (tableSizeLabel) {
            tableSizeLabel.textContent = `${tableSizeHover.rows} × ${tableSizeHover.cols}`;
        }
        if (!tableSizeGrid) return;
        tableSizeGrid.querySelectorAll('.table-size-cell').forEach(cell => {
            const r = parseInt(cell.getAttribute('data-row'), 10);
            const c = parseInt(cell.getAttribute('data-col'), 10);
            cell.classList.toggle('is-active', r <= tableSizeHover.rows && c <= tableSizeHover.cols);
        });
    }

    function ensureTableSizePickerGrid() {
        if (!tableSizeGrid || tableSizeGrid.childElementCount > 0) return;
        for (let r = 1; r <= TABLE_SIZE_MAX; r++) {
            for (let c = 1; c <= TABLE_SIZE_MAX; c++) {
                const cell = document.createElement('div');
                cell.className = 'table-size-cell';
                cell.setAttribute('data-row', String(r));
                cell.setAttribute('data-col', String(c));
                cell.addEventListener('mouseenter', () => updateTableSizePickerHighlight(r, c));
                cell.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    insertWorkspaceTable(r, c);
                    hideWorkspaceTableSizePicker();
                });
                tableSizeGrid.appendChild(cell);
            }
        }
    }

    function openWorkspaceTableSizePicker(toolbarModule) {
        if (isFocusInsideNestedTable()) return;
        if (!tableSizePicker) return;
        ensureTableSizePickerGrid();
        updateTableSizePickerHighlight(1, 1);

        const anchorBtn = (toolbarModule && toolbarModule.container)
            ? toolbarModule.container.querySelector('.ql-table')
            : document.querySelector('#workspace-quill-toolbar-container .ql-table');
        const rect = anchorBtn ? anchorBtn.getBoundingClientRect() : { left: 24, bottom: 80, right: 64 };
        const pickerWidth = 168;
        let left = rect.left;
        if (left + pickerWidth > window.innerWidth - 12) {
            left = Math.max(12, window.innerWidth - pickerWidth - 12);
        }
        tableSizePicker.style.left = `${left}px`;
        tableSizePicker.style.top = `${rect.bottom + 6}px`;
        tableSizePicker.style.display = 'block';
        tableSizePicker.setAttribute('aria-hidden', 'false');
    }

    function insertWorkspaceTable(rows, cols) {
        if (!workspaceQuillInstance) return;
        // Nested-in-nested tables break layout — disable entirely
        if (isFocusInsideNestedTable()) return;
        workspaceQuillInstance.focus();
        let range = workspaceQuillInstance.getSelection(true);
        if (!range) {
            workspaceQuillInstance.setSelection(workspaceQuillInstance.getLength(), 0, Quill.sources.SILENT);
            range = workspaceQuillInstance.getSelection(true);
        }

        const safeRows = Math.max(1, Math.min(TABLE_SIZE_MAX, rows));
        const safeCols = Math.max(1, Math.min(TABLE_SIZE_MAX, cols));

        // Quill cannot nest native tables — embed an editable nested grid inside a cell
        if (getOuterQuillTableCellAtSelection()) {
            const cells = Array.from({ length: safeRows }, () => Array.from({ length: safeCols }, () => ''));
            const colWidths = Array.from({ length: safeCols }, () => Math.max(NESTED_MIN_COL, 48));
            const rowHeights = Array.from({ length: safeRows }, () => Math.max(NESTED_MIN_ROW, 28));
            const payload = JSON.stringify({
                rows: safeRows,
                cols: safeCols,
                cells,
                colWidths,
                rowHeights,
                expandEntities: true
            });
            workspaceQuillInstance.insertEmbed(range.index, 'workspaceNestedTable', payload, Quill.sources.USER);
            workspaceQuillInstance.setSelection(range.index + 1, 0, Quill.sources.SILENT);
            setTimeout(() => {
                lockOuterCellsThatContainNestedTables();
                workspaceQuillInstance.root.querySelectorAll('.ql-workspace-nested-table').forEach(node => {
                    hydrateWorkspaceNestedTableEmbed(node);
                });
                lockOuterCellsThatContainNestedTables();
                updateWorkspaceSimulationPreview();
            }, 0);
            if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
            return;
        }

        const tableModule = workspaceQuillInstance.getModule('table');
        if (!tableModule || typeof tableModule.insertTable !== 'function') {
            console.error('Quill table module is unavailable.');
            return;
        }
        tableModule.insertTable(safeRows, safeCols);
        setTimeout(() => {
            // Default to left float so following/prev text wraps beside the table (image-like).
            const tables = queryWorkspaceQuillTables(workspaceQuillInstance.root);
            const newest = tables[tables.length - 1];
            if (newest && !newest.getAttribute('data-table-align')) {
                newest.classList.add('ql-table-align-left');
                newest.setAttribute('data-table-align', 'left');
            }
            if (newest && newest.getAttribute('data-expand-entities') == null) {
                newest.classList.add('ql-table-expand-entities');
                newest.setAttribute('data-expand-entities', 'true');
            }
            if (newest) persistWorkspaceTableLayoutAttrs(newest);
            reapplyAllWorkspaceTableLayouts();
            updateWorkspaceSimulationPreview();
        }, 0);
        if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
    }

    function setupWorkspaceTableContextMenu() {
        if (tableContextMenuBound || !htmlCanvasEditor) return;
        tableContextMenuBound = true;

        let menu = document.getElementById('workspace-quill-table-menu');
        if (!menu) {
            menu = document.createElement('div');
            menu.id = 'workspace-quill-table-menu';
            menu.className = 'custom-ql-context-menu';
            document.body.appendChild(menu);
        }

        document.addEventListener('click', function() {
            menu.style.display = 'none';
        });

        htmlCanvasEditor.addEventListener('contextmenu', function(e) {
            const cell = e.target.closest('td, th');
            if (!cell || !workspaceQuillInstance) return;

            const nestedEmbed = cell.closest('.ql-workspace-nested-table');
            if (nestedEmbed) {
                e.preventDefault();
                e.stopPropagation();
                const nestedTable = nestedEmbed.querySelector('table.ql-nested-table-inner');
                const hasHiddenBorders = nestedTable ? nestedTable.classList.contains('no-border') : false;
                const expandsEntities = nestedTable
                    ? previewTableShouldExpandEntities(nestedTable)
                    : true;
                menu.innerHTML = `
                    <div class="menu-item" data-command="toggle-borders" style="font-weight: 600; color: #2563eb;">
                        ${hasHiddenBorders ? '👁️ Show Inner Table Borders' : '🙈 Hide Inner Table Borders'}
                    </div>
                    <div class="menu-item" data-command="toggle-expand-entities" style="font-weight: 600; color: #2563eb;">
                        ${expandsEntities ? '🔒 Shrink Content to Fixed Preview Size' : '🧩 Expand Preview Cells for Entities'}
                    </div>
                    <div class="menu-divider"></div>
                    <div class="menu-item" data-command="row" data-arg="0">🔺 Insert Inner Row Above</div>
                    <div class="menu-item" data-command="row" data-arg="1">🔻 Insert Inner Row Below</div>
                    <div class="menu-divider"></div>
                    <div class="menu-item" data-command="col" data-arg="0">⏪ Insert Inner Column Left</div>
                    <div class="menu-item" data-command="col" data-arg="1">⏩ Insert Inner Column Right</div>
                    <div class="menu-divider"></div>
                    <div class="menu-item menu-item-danger" data-command="delete-row">🗑️ Delete Inner Row</div>
                    <div class="menu-item menu-item-danger" data-command="delete-col">🗑️ Delete Inner Column</div>
                    <div class="menu-item menu-item-danger" data-command="delete-table">❌ Delete Inner Table</div>
                `;
                menu.style.left = `${e.pageX}px`;
                menu.style.top = `${e.pageY}px`;
                menu.style.display = 'block';
                menu.querySelectorAll('.menu-item').forEach(item => {
                    item.onclick = function(ev) {
                        ev.preventDefault();
                        ev.stopPropagation();
                        mutateNestedTable(
                            nestedEmbed,
                            cell,
                            item.getAttribute('data-command'),
                            parseInt(item.getAttribute('data-arg'), 10)
                        );
                        menu.style.display = 'none';
                    };
                });
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            const tableModule = workspaceQuillInstance.getModule('table');
            if (!tableModule) return;

            try {
                const blot = Quill.find(cell);
                if (blot && typeof blot.offset === 'function') {
                    const index = blot.offset(workspaceQuillInstance.scroll);
                    workspaceQuillInstance.setSelection(index, 0, Quill.sources.SILENT);
                }
            } catch (err) {
                // Selection sync is best-effort
            }

            const parentTable = cell.closest('table');
            if (!parentTable || isNestedTableElement(parentTable)) return;
            const hasHiddenBorders = parentTable ? parentTable.classList.contains('no-border') : false;
            const isCompact = parentTable ? parentTable.classList.contains('ql-table-compact') : false;
            const expandsEntities = parentTable ? previewTableShouldExpandEntities(parentTable) : true;

            menu.innerHTML = `
                <div class="menu-item" data-command="select-table" style="font-weight: 600; color: #2563eb;">
                    ⧉ Select Entire Table
                </div>
                <div class="menu-divider"></div>
                <div class="menu-item" data-command="align-table" data-align="left">⬅️ Align Table Left (wrap text)</div>
                <div class="menu-item" data-command="align-table" data-align="center">↔️ Align Table Center</div>
                <div class="menu-item" data-command="align-table" data-align="right">➡️ Align Table Right (wrap text)</div>
                <div class="menu-divider"></div>
                <div class="menu-item" data-command="toggle-borders" style="font-weight: 600; color: #2563eb;">
                    ${hasHiddenBorders ? '👁️ Show Table Borders' : '🙈 Hide Table Borders'}
                </div>
                <div class="menu-item" data-command="toggle-compact" style="font-weight: 600; color: #2563eb;">
                    ${isCompact ? '📏 Use Standard Cell Minimum' : '📐 Use Compact Cell Minimum'}
                </div>
                <div class="menu-item" data-command="toggle-expand-entities" style="font-weight: 600; color: #2563eb;">
                    ${expandsEntities ? '🔒 Shrink Content to Fixed Preview Size' : '🧩 Expand Preview Cells for Entities'}
                </div>
                <div class="menu-divider"></div>
                <div class="menu-item" data-command="row" data-arg="0">🔺 Insert Row Above</div>
                <div class="menu-item" data-command="row" data-arg="1">🔻 Insert Row Below</div>
                <div class="menu-divider"></div>
                <div class="menu-item" data-command="col" data-arg="0">⏪ Insert Column Left</div>
                <div class="menu-item" data-command="col" data-arg="1">⏩ Insert Column Right</div>
                <div class="menu-divider"></div>
                <div class="menu-item menu-item-danger" data-command="delete-row">🗑️ Delete Current Row</div>
                <div class="menu-item menu-item-danger" data-command="delete-col">🗑️ Delete Current Column</div>
                <div class="menu-item menu-item-danger" data-command="delete-table">❌ Delete Entire Table</div>
            `;

            menu.style.left = `${e.pageX}px`;
            menu.style.top = `${e.pageY}px`;
            menu.style.display = 'block';

            menu.querySelectorAll('.menu-item').forEach(item => {
                item.onclick = function(ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    const command = item.getAttribute('data-command');
                    const arg = parseInt(item.getAttribute('data-arg'), 10);

                    if (command === 'select-table') {
                        if (parentTable) selectWorkspaceTable(parentTable);
                    } else if (command === 'align-table') {
                        if (parentTable) {
                            selectWorkspaceTable(parentTable);
                            applyWorkspaceTableAlignment(item.getAttribute('data-align'), parentTable);
                        }
                    } else if (command === 'toggle-borders') {
                        if (parentTable) {
                            parentTable.classList.toggle('no-border');
                            if (parentTable.classList.contains('no-border')) {
                                parentTable.setAttribute('data-no-border', 'true');
                            } else {
                                parentTable.removeAttribute('data-no-border');
                            }
                            persistWorkspaceTableLayoutAttrs(parentTable);
                            workspaceQuillInstance.update('user');
                        }
                    } else if (command === 'toggle-compact') {
                        if (parentTable) {
                            parentTable.classList.toggle('ql-table-compact');
                            if (parentTable.classList.contains('ql-table-compact')) {
                                parentTable.setAttribute('data-compact-cells', 'true');
                            } else {
                                parentTable.removeAttribute('data-compact-cells');
                            }
                            persistWorkspaceTableLayoutAttrs(parentTable);
                            reapplyWorkspaceTableLayout(parentTable);
                            workspaceQuillInstance.update('user');
                        }
                    } else if (command === 'toggle-expand-entities') {
                        if (parentTable) {
                            const currentlyOn = previewTableShouldExpandEntities(parentTable);
                            const on = !currentlyOn;
                            parentTable.classList.toggle('ql-table-expand-entities', on);
                            parentTable.setAttribute('data-expand-entities', on ? 'true' : 'false');
                            persistWorkspaceTableLayoutAttrs(parentTable);
                            workspaceQuillInstance.update('user');
                        }
                    } else if (command === 'row') {
                        if (arg === 0 && typeof tableModule.insertRowAbove === 'function') {
                            tableModule.insertRowAbove();
                        } else if (arg === 1 && typeof tableModule.insertRowBelow === 'function') {
                            tableModule.insertRowBelow();
                        } else if (typeof tableModule.insertRow === 'function') {
                            tableModule.insertRow(arg);
                        }
                    } else if (command === 'col') {
                        if (arg === 0 && typeof tableModule.insertColumnLeft === 'function') {
                            tableModule.insertColumnLeft();
                        } else if (arg === 1 && typeof tableModule.insertColumnRight === 'function') {
                            tableModule.insertColumnRight();
                        } else if (typeof tableModule.insertColumn === 'function') {
                            tableModule.insertColumn(arg);
                        }
                    } else if (command === 'delete-row' && typeof tableModule.deleteRow === 'function') {
                        tableModule.deleteRow();
                    } else if (command === 'delete-col' && typeof tableModule.deleteColumn === 'function') {
                        tableModule.deleteColumn();
                    } else if (command === 'delete-table' && typeof tableModule.deleteTable === 'function') {
                        tableModule.deleteTable();
                    }

                    menu.style.display = 'none';
                    setTimeout(() => {
                        reapplyAllWorkspaceTableLayouts();
                        updateWorkspaceSimulationPreview();
                    }, 0);
                    if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                };
            });
        });
    }

    function ensureTableColgroup(table, seedFromCells = true) {
        if (!table) return null;
        const firstRow = table.querySelector(':scope > tr, :scope > tbody > tr');
        if (!firstRow) return null;
        const cells = Array.from(firstRow.children).filter(el => el.matches('td, th'));
        const colCount = cells.length;
        if (!colCount) return null;
        const { minCol } = getTableSizeLimits(table);

        let colgroup = table.querySelector(':scope > colgroup');
        if (!colgroup) {
            colgroup = document.createElement('colgroup');
            table.insertBefore(colgroup, table.firstChild);
        }

        while (colgroup.children.length < colCount) {
            const col = document.createElement('col');
            const idx = colgroup.children.length;
            const width = seedFromCells && cells[idx]
                ? Math.max(minCol, Math.round(cells[idx].getBoundingClientRect().width) || 100)
                : Math.max(minCol, 100);
            col.style.width = `${width}px`;
            col.style.minWidth = `${width}px`;
            colgroup.appendChild(col);
        }
        while (colgroup.children.length > colCount) {
            colgroup.lastElementChild.remove();
        }

        if (seedFromCells) {
            for (let i = 0; i < colCount; i++) {
                const col = colgroup.children[i];
                if (!col) continue;
                const current = parseFloat(col.style.width);
                if (!current || Number.isNaN(current)) {
                    const measured = cells[i]
                        ? Math.max(minCol, Math.round(cells[i].getBoundingClientRect().width) || 100)
                        : Math.max(minCol, 100);
                    col.style.width = `${measured}px`;
                    col.style.minWidth = `${measured}px`;
                } else {
                    col.style.minWidth = `${Math.round(current)}px`;
                }
            }
        }

        table.style.tableLayout = 'fixed';
        table.style.maxWidth = 'none';
        return colgroup;
    }

    function readLiveColumnWidths(table) {
        const { minCol } = getTableSizeLimits(table);
        const firstRow = table.querySelector(':scope > tr, :scope > tbody > tr');
        if (!firstRow) return [];
        const cells = Array.from(firstRow.children).filter(el => el.matches('td, th'));
        const colgroup = table.querySelector(':scope > colgroup');
        const fromData = (table.getAttribute('data-col-widths') || '')
            .split(',')
            .map(v => parseFloat(v));

        return cells.map((cell, i) => {
            const fromCol = colgroup && colgroup.children[i]
                ? parseFloat(colgroup.children[i].style.width)
                : NaN;
            const fromCellStyle = parseFloat(cell.style.width);
            const width = (!Number.isNaN(fromCol) && fromCol > 0 ? fromCol : null)
                || (!Number.isNaN(fromCellStyle) && fromCellStyle > 0 ? fromCellStyle : null)
                || (!Number.isNaN(fromData[i]) && fromData[i] > 0 ? fromData[i] : null)
                || cell.getBoundingClientRect().width
                || 100;
            return Math.max(minCol, Math.round(width));
        });
    }

    function applyColumnWidths(table, widths) {
        if (!table || !widths || !widths.length) return;
        const { minCol } = getTableSizeLimits(table);
        const normalized = widths.map(w => Math.max(minCol, Math.round(w)));
        ensureTableColgroup(table, true);
        const colgroup = table.querySelector(':scope > colgroup');
        // Only direct table rows — never walk into nested ql-nested-table-inner rows
        const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
        normalized.forEach((width, i) => {
            if (colgroup && colgroup.children[i]) {
                colgroup.children[i].style.width = `${width}px`;
                colgroup.children[i].style.minWidth = `${width}px`;
            }
            rows.forEach(tr => {
                const cell = Array.from(tr.children).filter(el => el.matches('td, th'))[i];
                if (cell) {
                    cell.style.width = `${width}px`;
                    cell.style.minWidth = `${width}px`;
                }
            });
        });
        const total = normalized.reduce((a, b) => a + b, 0);
        table.style.tableLayout = 'fixed';
        table.style.width = `${total}px`;
        table.style.minWidth = `${total}px`;
        table.style.maxWidth = 'none';
        table.setAttribute('data-col-widths', normalized.join(','));
    }

    function setRowHeightExclusive(row, heightPx, table = null) {
        if (!row) return;
        const hostTable = table || row.closest('table');
        const { minRow } = getTableSizeLimits(hostTable);
        const height = Math.max(minRow, Math.round(heightPx));
        row.style.height = `${height}px`;
        row.style.minHeight = `${height}px`;
        Array.from(row.children).forEach(td => {
            if (!td.matches('td, th')) return;
            td.style.height = `${height}px`;
            td.style.minHeight = `${height}px`;
        });
    }

    function setupWorkspaceTableResize() {
        if (tableResizeBound || !htmlCanvasEditor) return;
        tableResizeBound = true;

        const EDGE_PX = 4;
        const SELECT_INSET_PX = 4;

        function pointerDeepInsideOuterCell(clientX, clientY) {
            const cell = getOuterQuillCellFromPoint(clientX, clientY);
            if (!cell) return null;
            if (distanceToCellEdges(clientX, clientY, cell) <= SELECT_INSET_PX) return null;
            return cell;
        }

        function hitTestTableGrid(table, clientX, clientY, extras = {}) {
            const tableRect = table.getBoundingClientRect();
            if (
                clientX < tableRect.left - EDGE_PX ||
                clientX > tableRect.right + EDGE_PX ||
                clientY < tableRect.top - EDGE_PX ||
                clientY > tableRect.bottom + EDGE_PX
            ) {
                return null;
            }

            const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
            if (!rows.length) return null;
            const firstRowCells = Array.from(rows[0].children).filter(el => el.matches('td, th'));
            if (!firstRowCells.length) return null;

            for (let colIndex = 0; colIndex < firstRowCells.length; colIndex++) {
                const boundaryX = firstRowCells[colIndex].getBoundingClientRect().right;
                if (
                    Math.abs(clientX - boundaryX) <= EDGE_PX &&
                    clientY >= tableRect.top - EDGE_PX &&
                    clientY <= tableRect.bottom + EDGE_PX
                ) {
                    return {
                        type: 'col',
                        table,
                        row: rows[0],
                        rowIndex: 0,
                        colIndex,
                        cell: firstRowCells[colIndex],
                        ...extras
                    };
                }
            }

            for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
                const row = rows[rowIndex];
                const rowCells = Array.from(row.children).filter(el => el.matches('td, th'));
                if (!rowCells.length) continue;
                const boundaryY = Math.max(...rowCells.map(c => c.getBoundingClientRect().bottom));
                if (
                    Math.abs(clientY - boundaryY) <= EDGE_PX &&
                    clientX >= tableRect.left - EDGE_PX &&
                    clientX <= tableRect.right + EDGE_PX
                ) {
                    return {
                        type: 'row',
                        table,
                        row,
                        rowIndex,
                        colIndex: 0,
                        cell: rowCells[0],
                        ...extras
                    };
                }
            }
            return null;
        }

        function findResizeTarget(clientX, clientY) {
            if (!workspaceQuillInstance) return null;

            // Clicks deep inside a normal outer cell (esp. empty ones) must never
            // start a resize — Quill only places a caret there if default isn't canceled.
            const outerCell = getOuterQuillCellFromPoint(clientX, clientY);
            if (
                outerCell &&
                !outerCell.classList.contains('ql-has-nested-table') &&
                distanceToCellEdges(clientX, clientY, outerCell) > SELECT_INSET_PX
            ) {
                return null;
            }

            // Prefer nested edges when the pointer is over/near nested, so coinciding
            // outer walls don't steal nested resize — but only after the empty-cell guard.
            const nestedTables = Array.from(
                workspaceQuillInstance.root.querySelectorAll('table.ql-nested-table-inner')
            );
            for (const table of nestedTables) {
                const embed = table.closest('.ql-workspace-nested-table');
                const tableRect = table.getBoundingClientRect();
                const nearNested = (
                    clientX >= tableRect.left - EDGE_PX &&
                    clientX <= tableRect.right + EDGE_PX &&
                    clientY >= tableRect.top - EDGE_PX &&
                    clientY <= tableRect.bottom + EDGE_PX
                );
                if (!nearNested) continue;

                // If the top hit is another outer cell (not the nested embed), skip nest prefer
                const stack = (typeof document.elementsFromPoint === 'function')
                    ? document.elementsFromPoint(clientX, clientY)
                    : [document.elementFromPoint(clientX, clientY)].filter(Boolean);
                const overNested = stack.some(el =>
                    el && el.closest && el.closest('.ql-workspace-nested-table') === embed
                );
                if (!overNested && outerCell && !outerCell.classList.contains('ql-has-nested-table')) {
                    continue;
                }

                const hit = hitTestTableGrid(table, clientX, clientY, {
                    isNested: true,
                    nestedEmbed: embed
                });
                if (hit) return hit;
            }

            // Empty/short outer cells: don't steal clicks that are clearly inside a cell
            if (pointerDeepInsideOuterCell(clientX, clientY)) return null;

            const tables = queryWorkspaceQuillTables(workspaceQuillInstance.root);
            for (const table of tables) {
                const hit = hitTestTableGrid(table, clientX, clientY, { isNested: false });
                if (hit) return hit;
            }
            return null;
        }

        function clearResizeHoverCursor() {
            const root = workspaceQuillInstance?.root;
            if (!root) return;
            root.classList.remove('workspace-col-resize', 'workspace-row-resize');
            root.style.cursor = '';
            if (htmlCanvasEditor) htmlCanvasEditor.style.cursor = '';
        }

        function setResizeHoverCursor(type) {
            const root = workspaceQuillInstance?.root;
            if (!root) return;
            root.classList.remove('workspace-col-resize', 'workspace-row-resize');
            if (type === 'col') root.classList.add('workspace-col-resize');
            if (type === 'row') root.classList.add('workspace-row-resize');
        }

        htmlCanvasEditor.addEventListener('mousemove', function(e) {
            if (tableResizeState) return;
            const hit = findResizeTarget(e.clientX, e.clientY);
            if (hit) setResizeHoverCursor(hit.type);
            else clearResizeHoverCursor();
        }, true);

        htmlCanvasEditor.addEventListener('mousedown', function(e) {
            if (e.button !== 0) return;
            const hit = findResizeTarget(e.clientX, e.clientY);
            if (!hit) return;

            e.preventDefault();
            e.stopPropagation();
            if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();

            if (hit.isNested) {
                const embed = hit.nestedEmbed;
                const config = parseNestedTableConfig(embed?.getAttribute('data-value') || '');
                applyNestedInnerLayout(hit.table, config.colWidths, config.rowHeights);
                if (hit.type === 'col') {
                    tableResizeState = {
                        type: 'col',
                        isNested: true,
                        nestedEmbed: embed,
                        table: hit.table,
                        colIndex: hit.colIndex,
                        startX: e.clientX,
                        startWidth: config.colWidths[hit.colIndex],
                        widths: config.colWidths.slice(),
                        heights: config.rowHeights.slice()
                    };
                } else {
                    tableResizeState = {
                        type: 'row',
                        isNested: true,
                        nestedEmbed: embed,
                        table: hit.table,
                        row: hit.row,
                        rowIndex: hit.rowIndex,
                        startY: e.clientY,
                        startHeight: config.rowHeights[hit.rowIndex],
                        widths: config.colWidths.slice(),
                        heights: config.rowHeights.slice()
                    };
                }
                setResizeHoverCursor(hit.type);
            } else if (hit.type === 'col') {
                const widths = readLiveColumnWidths(hit.table);
                applyColumnWidths(hit.table, widths);
                tableResizeState = {
                    type: 'col',
                    isNested: false,
                    table: hit.table,
                    colIndex: hit.colIndex,
                    startX: e.clientX,
                    startWidth: widths[hit.colIndex],
                    widths: widths.slice()
                };
                setResizeHoverCursor('col');
            } else {
                const heights = Array.from(hit.table.querySelectorAll(':scope > tr, :scope > tbody > tr')).map(tr => {
                    const h = Math.max(
                        getTableSizeLimits(hit.table).minRow,
                        Math.round(tr.getBoundingClientRect().height) || 36
                    );
                    setRowHeightExclusive(tr, h, hit.table);
                    return h;
                });
                tableResizeState = {
                    type: 'row',
                    isNested: false,
                    table: hit.table,
                    row: hit.row,
                    rowIndex: hit.rowIndex,
                    startY: e.clientY,
                    startHeight: heights[hit.rowIndex] || hit.row.getBoundingClientRect().height,
                    heights: heights.slice()
                };
                setResizeHoverCursor('row');
            }

            workspaceQuillInstance?.root?.classList.add('workspace-table-resizing');
        }, true);

        document.addEventListener('mousemove', function(e) {
            if (!tableResizeState) return;
            e.preventDefault();

            if (tableResizeState.isNested) {
                if (tableResizeState.type === 'col') {
                    const dx = e.clientX - tableResizeState.startX;
                    const newWidth = Math.max(NESTED_MIN_COL, Math.round(tableResizeState.startWidth + dx));
                    tableResizeState.widths[tableResizeState.colIndex] = newWidth;
                    applyNestedInnerLayout(tableResizeState.table, tableResizeState.widths, tableResizeState.heights);
                    const config = parseNestedTableConfig(tableResizeState.nestedEmbed.getAttribute('data-value') || '');
                    config.colWidths = tableResizeState.widths.slice();
                    config.rowHeights = tableResizeState.heights.slice();
                    nodeSetNestedConfig(tableResizeState.nestedEmbed, config);
                    fitOuterCellToNestedEmbed(tableResizeState.nestedEmbed);
                } else {
                    const dy = e.clientY - tableResizeState.startY;
                    const newHeight = Math.max(NESTED_MIN_ROW, Math.round(tableResizeState.startHeight + dy));
                    tableResizeState.heights[tableResizeState.rowIndex] = newHeight;
                    applyNestedInnerLayout(tableResizeState.table, tableResizeState.widths, tableResizeState.heights);
                    const config = parseNestedTableConfig(tableResizeState.nestedEmbed.getAttribute('data-value') || '');
                    config.colWidths = tableResizeState.widths.slice();
                    config.rowHeights = tableResizeState.heights.slice();
                    nodeSetNestedConfig(tableResizeState.nestedEmbed, config);
                    fitOuterCellToNestedEmbed(tableResizeState.nestedEmbed);
                }
                return;
            }

            if (tableResizeState.type === 'col') {
                const { minCol } = getTableSizeLimits(tableResizeState.table);
                const dx = e.clientX - tableResizeState.startX;
                const newWidth = Math.max(minCol, Math.round(tableResizeState.startWidth + dx));
                tableResizeState.widths[tableResizeState.colIndex] = newWidth;
                applyColumnWidths(tableResizeState.table, tableResizeState.widths);
                scaleNestedTablesInOuterTable(tableResizeState.table, tableResizeState.colIndex, null);
            } else if (tableResizeState.type === 'row') {
                const dy = e.clientY - tableResizeState.startY;
                const newHeight = Math.max(
                    getTableSizeLimits(tableResizeState.table).minRow,
                    Math.round(tableResizeState.startHeight + dy)
                );
                tableResizeState.heights[tableResizeState.rowIndex] = newHeight;
                setRowHeightExclusive(tableResizeState.row, newHeight, tableResizeState.table);
                scaleNestedTablesInOuterTable(tableResizeState.table, null, tableResizeState.rowIndex);
            }
        });

        document.addEventListener('mouseup', function() {
            if (!tableResizeState) return;
            const state = tableResizeState;
            const table = state.table;

            if (state.isNested) {
                const config = parseNestedTableConfig(state.nestedEmbed.getAttribute('data-value') || '');
                config.colWidths = state.widths.slice();
                config.rowHeights = state.heights.slice();
                nodeSetNestedConfig(state.nestedEmbed, config);
                applyNestedInnerLayout(table, config.colWidths, config.rowHeights);
                fitOuterCellToNestedEmbed(state.nestedEmbed);
                workspaceQuillInstance?.root?.classList.remove('workspace-table-resizing');
                tableResizeState = null;
                clearResizeHoverCursor();
                updateWorkspaceSimulationPreview();
                if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                return;
            }

            const finalWidths = state.type === 'col' ? state.widths.slice() : null;
            const finalHeights = state.type === 'row' ? state.heights.slice() : null;
            const affectedCol = state.type === 'col' ? state.colIndex : null;
            const affectedRow = state.type === 'row' ? state.rowIndex : null;

            persistWorkspaceTableLayoutAttrs(table, finalWidths, finalHeights);
            if (finalWidths) applyColumnWidths(table, finalWidths);
            if (finalHeights) {
                const rows = Array.from(table.querySelectorAll(':scope > tr, :scope > tbody > tr'));
                finalHeights.forEach((h, i) => {
                    if (rows[i]) setRowHeightExclusive(rows[i], h, table);
                });
            }
            scaleNestedTablesInOuterTable(table, affectedCol, affectedRow);

            workspaceQuillInstance?.root?.classList.remove('workspace-table-resizing');
            tableResizeState = null;
            clearResizeHoverCursor();

            requestAnimationFrame(() => {
                if (finalWidths) {
                    table.setAttribute('data-col-widths', finalWidths.join(','));
                    applyColumnWidths(table, finalWidths);
                }
                if (finalHeights) {
                    table.setAttribute('data-row-heights', finalHeights.join(','));
                }
                reapplyWorkspaceTableLayout(table);
                scaleNestedTablesInOuterTable(table, affectedCol, affectedRow);
                updateWorkspaceSimulationPreview();
            });
            if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
        });
    }

    document.addEventListener('click', function(e) {
        if (!tableSizePicker || tableSizePicker.style.display === 'none') return;
        if (tableSizePicker.contains(e.target)) return;
        if (e.target.closest && e.target.closest('.ql-table')) return;
        hideWorkspaceTableSizePicker();
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') hideWorkspaceTableSizePicker();
    });

    // 🎯 5. DRAFT PROGRESS SAVE ACTION HANDLER
    const draftConfirmModal = document.getElementById('draft-save-confirm-modal');
    const draftConfirmReasonsList = document.getElementById('draft-save-confirm-reasons');
    const draftConfirmBtn = document.getElementById('btn-confirm-draft-save');
    const draftCancelBtn = document.getElementById('btn-cancel-draft-save');
    let pendingDraftSavePayload = null;

    function collectWorkspaceSavePayload() {
        // Preview student answers (previewStudentAnswers) are intentionally omitted —
        // only teacher authoring state is persisted from this overlay.
        const problemId = workspaceOverlay.getAttribute('data-current-problem-id');
        const titleValue = overlayTitleField ? overlayTitleField.value.trim() : '';
        const canvasHtml = getWorkspaceQuillHtmlForSave();
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
                points: (() => {
                    const isAnswerField = answerFieldsTokens.some(item => item.token === baseToken);
                    if (!isAnswerField) return undefined;
                    const raw = card.querySelector('.val-answer-field-points')?.value;
                    const parsed = parseFloat(raw);
                    return Number.isFinite(parsed) ? parsed : (Number(card.getAttribute('data-points')) || 0);
                })(),
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

            // matrixResultByIndex source matrix unlink
            if (inputKey === 'matrix') {
                const statusLabel = wrapper.querySelector('.link-status-text');
                if (statusLabel) {
                    statusLabel.textContent = 'Required: Select a matrix';
                    statusLabel.style.color = '#ef4444';
                }

                const rawInput = wrapper.querySelector('input.val-matrix-result-source, input, select');
                if (rawInput) rawInput.value = '';

                const pill = wrapper.querySelector('.linked-token-pill');
                if (pill) pill.remove();

                linkBtn.innerHTML = '<i class="fas fa-link"></i>';
                linkBtn.className = 'btn-input-link-trigger';
                linkBtn.style.color = '#94a3b8';
                linkBtn.style.borderColor = '#cbd5e1';

                if (rawInput) {
                    rawInput.dispatchEvent(new Event('input', { bubbles: true }));
                }

                const activeCard = linkBtn.closest('.workspace-block-card') || linkBtn.closest('.workspace-component-card');
                if (activeCard) {
                    activeCard.removeAttribute('data-output-types');
                    const cardId = activeCard.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
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

            // Prefer live card output types (e.g. matrixResultByIndex cell classification,
            // matrix determinate → double) when the entity processor returns an array;
            // otherwise use blueprint output / data-output-types attribute.
            let rawOutput = getEntityInformation(baseArchetype, {
                action: 'getOutputTypes',
                card
            });
            if (!Array.isArray(rawOutput) || rawOutput.length === 0) {
                const attrTypes = (card.getAttribute('data-output-types') || '')
                    .split(',')
                    .map(t => t.trim())
                    .filter(Boolean);
                if (attrTypes.length) {
                    rawOutput = attrTypes;
                } else {
                    rawOutput = blueprintData.output || tokenDefinition.output || [];
                }
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
                acceptedTargetTypes,
                sourceArchetype: baseArchetype,
                sourceToken: indexedToken
            });
            if (linkOverride === true) {
                isCompatible = true;
            } else if (linkOverride === false) {
                isCompatible = false;
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

        // matrixResultByIndex source matrix link
        if (inputKey === 'matrix') {
            const statusLabel = wrapper.querySelector('.link-status-text');
            if (statusLabel) {
                statusLabel.textContent = `Linked to: ${rawTokenId}`;
                statusLabel.style.color = '#0284c7';
            }

            const actualInputNode = wrapper.querySelector('input.val-matrix-result-source, input, select');
            if (actualInputNode) {
                actualInputNode.value = chosenTokenString;
            }

            const existingPill = wrapper.querySelector('.linked-token-pill');
            if (existingPill) existingPill.remove();

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
            return;
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
    function renderGraphComponentCanvas(targetCanvasId, graphConfig, sizeOptions = {}) {
        if (!graphConfig || graphConfig.archetype !== 'graph') return;

        // 1. Grab the direct, native browser-compiled instance from window scope
        const activePlotEngine = window.functionPlot || (typeof functionPlot !== 'undefined' ? functionPlot : null);
        if (!activePlotEngine) return;

        const targetEl = typeof targetCanvasId === 'string'
            ? document.getElementById(targetCanvasId)
            : null;
        if (!targetEl) return;
        // Clear prior SVG so re-paints inside tables don't stack / miss the node
        targetEl.innerHTML = '';

        const plotWidth = Math.max(80, Math.round(sizeOptions.width || 340));
        const plotHeight = Math.max(80, Math.round(sizeOptions.height || 240));

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

        // 🚀 Step 1: Initialize/Update the plot (use element target — safer than #id in nested tables)
        const chartInstance = activePlotEngine({
            target: targetEl,
            width: plotWidth,
            height: plotHeight,
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