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
                latestCard.setAttribute('data-simulated-value', segment.simulated_value);
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

        let fieldsHtml = '';
        // Add new entity Step 1: if new fields exist, then add the html here for the new entity
        if (token === 'randInt') {
            fieldsHtml = `
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px;">
                    <label style="font-size: 0.75rem; color: #475569;">Min: <input type="number" class="val-input-min" value="${savedValues.min ?? -9}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Max: <input type="number" class="val-input-max" value="${savedValues.max ?? 9}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Step: <input type="number" class="val-input-step" value="${savedValues.step ?? 1}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                </div>
            `;
        } else if (token === 'rand') {
            fieldsHtml = `
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px;">
                    <label style="font-size: 0.75rem; color: #475569;">Min: <input type="number" step="any" class="val-input-min" value="${savedValues.min ?? 0.0}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Max: <input type="number" step="any" class="val-input-max" value="${savedValues.max ?? 1.0}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Step: <input type="number" step="any" class="val-input-step" value="${savedValues.step ?? 0.01}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                </div>
            `;
        } else if (token === 'primeFactors') {
            fieldsHtml = `
                <div style="display: grid; grid-template-columns: 1fr; gap: 6px;">
                    <label style="font-size: 0.75rem; color: #475569;">Number to Factor: 
                        <input type="number" class="val-input-number" value="${savedValues['number to factor'] ?? 12}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;">
                    </label>
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

        // Track live typing modifications to clear synced status tracking layers
        card.addEventListener('input', function(e) {
            if (e.target.matches('input, select, textarea')) {
                if (saveStatusSpan) {
                    saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                }
                updateWorkspaceSimulationPreview();
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
            const cleanToken = (tokenText || match).replace(/[<>&]/g, '').trim(); // e.g., "randInt2"
            
            let evaluationValue = null;
            
            // Look across variables and inputs sidebar blocks to locate an active configuration block match
            const allCards = document.querySelectorAll('.workspace-block-card');
            allCards.forEach(card => {
                const deleteBtn = card.querySelector('.btn-delete-workspace-component');
                if (deleteBtn && deleteBtn.getAttribute('data-indexed-token') === cleanToken) {
                    
                    const baseArchetype = card.getAttribute('data-token');
                    
                    // Add new entity Step 2: if new fields exist, then add the javascript version of the identical server-side computations
                    // 🎯 CLIENT-SIDE RANDOMIZATION SEED EVALUATION MATRIX
                    if (baseArchetype === 'randInt') {
                        const minVal = parseInt(card.querySelector('.val-input-min')?.value ?? -9, 10);
                        const maxVal = parseInt(card.querySelector('.val-input-max')?.value ?? 9, 10);
                        const stepVal = parseInt(card.querySelector('.val-input-step')?.value ?? 1, 10);
                        
                        if (!isNaN(minVal) && !isNaN(maxVal) && stepVal > 0 && minVal <= maxVal) {
                            const pool = [];
                            let current = minVal;
                            while (current <= maxVal) {
                                pool.push(current);
                                current += stepVal;
                            }
                            if (pool.length > 0) {
                                // Read our random factor string
                                const seedAttr = card.getAttribute('data-shuffle-seed');
                                
                                let targetIndex = 0;
                                if (seedAttr) {
                                    // 🚀 CRITICAL FIX: Direct fractional translation. 
                                    // This guarantees an unpredictable jump every single time across any sized pool.
                                    const randomMultiplier = parseFloat(seedAttr);
                                    targetIndex = Math.floor(randomMultiplier * pool.length);
                                } else {
                                    // Fallback deterministic default index for when the card first cold-loads 
                                    // from the database before a user clicks refresh
                                    const baseTextSeed = cleanToken.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                                    targetIndex = baseTextSeed % pool.length;
                                }
                                
                                // Defensively clamp index to prevent array index out of bounds exceptions
                                if (targetIndex >= pool.length) targetIndex = pool.length - 1;
                                if (targetIndex < 0) targetIndex = 0;

                                evaluationValue = pool[targetIndex].toString();
                            }
                        }
                    } else if (baseArchetype === 'rand') {
                        const minVal = parseFloat(card.querySelector('.val-input-min')?.value ?? 0.0);
                        const maxVal = parseFloat(card.querySelector('.val-input-max')?.value ?? 1.0);
                        const stepVal = parseFloat(card.querySelector('.val-input-step')?.value ?? 0.01);

                        if (!isNaN(minVal) && !isNaN(maxVal) && stepVal > 0 && minVal <= maxVal) {
                            // Calculate the max number of intervals mathematically (O(1) Memory Safe)
                            const totalRange = maxVal - minVal;
                            const maxSteps = Math.floor((totalRange + 1e-9) / stepVal);

                            if (maxSteps >= 0) {
                                const seedAttr = card.getAttribute('data-shuffle-seed');
                                let targetStepMultiplier = 0;

                                if (seedAttr) {
                                    const randomMultiplier = parseFloat(seedAttr);
                                    targetStepMultiplier = Math.floor(randomMultiplier * (maxSteps + 1));
                                } else {
                                    const baseTextSeed = cleanToken.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
                                    targetStepMultiplier = baseTextSeed % (maxSteps + 1);
                                    if (isNaN(targetStepMultiplier)) targetStepMultiplier = 0;
                                }

                                // Clamp the step multiplier inside bounds
                                if (targetStepMultiplier > maxSteps) targetStepMultiplier = maxSteps;
                                if (targetStepMultiplier < 0) targetStepMultiplier = 0;

                                let finalValue = minVal + (targetStepMultiplier * stepVal);
                                if (finalValue > maxVal) finalValue = maxVal;

                                // Dynamically calculate precision format length based on step size decimal places
                                const stepStr = stepVal.toString();
                                let decimalPlaces = 4;
                                if (stepStr.includes('.')) {
                                    decimalPlaces = stepStr.split('.')[1].length;
                                }

                                evaluationValue = finalValue.toFixed(decimalPlaces);
                            }
                        }
                    } else if (baseArchetype === 'primeFactors') {
                        let targetNum = parseInt(card.querySelector('.val-input-number')?.value ?? 12, 10);
                        
                        if (!isNaN(targetNum) && targetNum > 1) {
                            const factors = [];
                            
                            // Extract factors of 2
                            while (targetNum % 2 === 0) {
                                factors.push(2);
                                targetNum = Math.floor(targetNum / 2);
                            }
                            
                            // Check odd factors up to the square root
                            let factor = 3;
                            while (factor * factor <= targetNum) {
                                while (targetNum % factor === 0) {
                                    factors.push(factor);
                                    targetNum = Math.floor(targetNum / factor);
                                }
                                factor += 2;
                            }
                            
                            // If anything remains, it must be prime
                            if (targetNum > 1) {
                                factors.push(targetNum);
                            }
                            
                            evaluationValue = factors.join(', ');
                        } else {
                            evaluationValue = ""; // Graceful empty fallback if boundaries are invalid (< 2)
                        }
                    }
                    else if (baseArchetype === 'formula') {
                        evaluationValue = card.querySelector('.val-input-formula')?.value.trim() || '3*x + 5';
                    }
                    
                    // If client-side processing didn't catch the token or fields are completely blank, 
                    // fall back gracefully onto the initial server token string attribute
                    if (evaluationValue === null || evaluationValue === '') {
                        evaluationValue = card.getAttribute('data-simulated-value');
                    }
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

                // Find the delete button to read the custom calculated sequential label string
                const deleteBtn = card.querySelector('.btn-delete-workspace-component');
                const indexedTokenString = deleteBtn ? deleteBtn.getAttribute('data-indexed-token') : baseToken; // e.g., "randInt1"

                const inputValues = {};

                // Add new entity Step 3: if new fields exist, then add them here so I can extract the values
                const minEl = card.querySelector('.val-input-min');
                const maxEl = card.querySelector('.val-input-max');
                const stepEl = card.querySelector('.val-input-step');

                if (minEl) inputValues.min = minEl.value;
                if (maxEl) inputValues.max = maxEl.value;
                if (stepEl) inputValues.step = stepEl.value;

                const formulaEl = card.querySelector('.val-input-formula');
                if (formulaEl) inputValues.formula = formulaEl.value.trim();

                const correctFormulaEl = card.querySelector('.val-input-correct-formula');
                if (correctFormulaEl) inputValues.correct_formula = correctFormulaEl.value.trim();

                const numberEl = card.querySelector('.val-input-number');
                if (numberEl) {
                    inputValues['number to factor'] = numberEl.value;
                }

                // 🚀 FIX: Send the clean base database token, and pass the indexed tracking sequence string separately
                inputsPayloadList.push({
                    token: baseToken,                       // Keeps Django's database lookup clean (e.g. "randInt")
                    sequence_token: indexedTokenString,    // Lets the backend know its order index (e.g. "randInt1")
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
});