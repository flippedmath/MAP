// -------------------------------------------------------------
// Global Problem Workspace Overlay Controller Engine
// -------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function() {
    const workspaceOverlay = document.getElementById('problem-workspace-overlay');
    const overlayTitleField = document.getElementById('overlay-problem-title-field');
    const closeOverlayBtn = document.getElementById('close-workspace-overlay');
    
    // Core sub-containers inside the workspace overlay columns
    const variablesContainer = document.getElementById('sidebar-variables-list');
    const inputsContainer = document.getElementById('sidebar-inputs-list');
    const htmlCanvasEditor = document.getElementById('editor-html-insert-canvas');
    const tokensLedger = document.getElementById('overlay-tokens-wrapper-line');

    // 🎯 Targets for the creation trigger buttons
    const addVariableTrigger = document.getElementById('add-variable-trigger');
    const addInputTrigger = document.getElementById('add-input-trigger');

    if (!workspaceOverlay) return;

    // 1. Global Event Delegation: Catch edit requests from ANY page
    document.body.addEventListener('click', async function(e) {
        const editBtn = e.target.closest('.btn-edit-problem-details');
        if (!editBtn) return;

        e.preventDefault();

        const itemRow = editBtn.closest('[data-id], .problem-item-row');
        if (!itemRow) return;

        const problemId = itemRow.getAttribute('data-id');
        
        const titleInput = itemRow.querySelector('.problem-title-input');
        let problemTitle = "Untitled Problem";
        
        if (titleInput) {
            problemTitle = titleInput.value.trim();
        } else {
            const textContainer = itemRow.querySelector('.problem-title-text, .item-name');
            if (textContainer) problemTitle = textContainer.innerText.trim();
        }

        if (overlayTitleField) overlayTitleField.value = problemTitle;
        workspaceOverlay.setAttribute('data-current-problem-id', problemId);
        
        workspaceOverlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        // Fetch problem data specifications asynchronously from the database
        try {
            if (variablesContainer) variablesContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">Loading components...</p>';
            if (inputsContainer) inputsContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">Loading components...</p>';
            if (tokensLedger) tokensLedger.innerHTML = '';
            if (htmlCanvasEditor) htmlCanvasEditor.innerHTML = '';

            const response = await fetch(`/api/problem/${problemId}/workspace-data/`);
            if (!response.ok) throw new Error("Failed to load problem data maps.");
            
            const data = await response.json();
            
            if (htmlCanvasEditor) {
                htmlCanvasEditor.innerHTML = data.html_content || '';
                // 🎯 Run initial execution sweep right away on payload mount
                updateWorkspaceSimulationPreview();
            }
            
            if (variablesContainer) variablesContainer.innerHTML = '';
            if (inputsContainer) inputsContainer.innerHTML = '';
            if (tokensLedger) tokensLedger.innerHTML = '';

            if (!data.entities || data.entities.length === 0) {
                clearAndShowPlaceholders();
                return;
            }

            // PROCESS & RENDER COMPONENT ENTITIES
            data.entities.forEach(entity => {
                const schema = entity.content_schema || {};
                const tokenName = schema.token || `entity_${entity.id}`;
                
                createTokenBadge(tokenName);

                if (entity.type.startsWith('variable_')) {
                    renderVariableComponent(entity, schema, tokenName);
                } else {
                    renderInputFormComponent(entity, schema, tokenName);
                }
            });

            checkEmptyColumns();

        } catch (err) {
            console.error("Workspace configuration loader error:", err);
            if (variablesContainer) variablesContainer.innerHTML = '<p style="color:#ef4444; font-size:0.85rem;">Failed to synchronize variables.</p>';
            if (inputsContainer) inputsContainer.innerHTML = '<p style="color:#ef4444; font-size:0.85rem;">Failed to synchronize input layout.</p>';
        }
    });

    // 2. Global Close Controller Action
    if (closeOverlayBtn) {
        closeOverlayBtn.addEventListener('click', function() {
            workspaceOverlay.style.display = 'none';
            workspaceOverlay.removeAttribute('data-current-problem-id');
            document.body.style.overflow = '';
        });
    }

    // -------------------------------------------------------------
    // 🎯 NEW: Component Add Instantiation Events
    // -------------------------------------------------------------
    if (addVariableTrigger) {
        addVariableTrigger.addEventListener('click', function(e) {
            e.stopPropagation();
            
            // Remove any existing active dropdowns to prevent clutter
            const existingMenu = document.getElementById('active-variable-dropdown-menu');
            if (existingMenu) { existingMenu.remove(); return; }

            // Create a styled floating dropdown option menu panel
            const menu = document.createElement('div');
            menu.id = 'active-variable-dropdown-menu';
            menu.style.cssText = 'position: absolute; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); padding: 4px 0; min-width: 180px; z-index: 10005; display: flex; flex-direction: column;';
            
            // Define the structural variants supported by your catalog
            const options = [
                { type: 'variable_numeric', label: 'Numeric Range', icon: 'fa-sort-numeric-up' },
                { type: 'variable_equation', label: 'Equation/Formula String', icon: 'fa-square-root-alt' },
                { type: 'variable_matrix', label: 'Variable Matrix Grid', icon: 'fa-matrix', placeholderPrefix: 'matrix' },
                { type: 'variable_string_array', label: 'String Array List', icon: 'fa-tags', placeholderPrefix: 'stringArray' }
            ];

            options.forEach(opt => {
                const item = document.createElement('button');
                item.type = 'button';
                item.style.cssText = 'background: none; border: none; padding: 6px 12px; text-align: left; font-size: 0.8rem; color: #334155; cursor: pointer; display: flex; align-items: center; gap: 8px; width: 100%; transition: background 0.1s;';
                item.innerHTML = `<i class="fas ${opt.icon}" style="width:14px; color:#64748b;"></i> ${opt.label}`;
                
                item.addEventListener('mouseover', () => { item.style.background = '#f1f5f9'; });
                item.addEventListener('mouseout', () => { item.style.background = 'none'; });
                
                item.addEventListener('click', function() {
                    const prefix = opt.placeholderPrefix || 'num';
                    const currentVarsCount = variablesContainer.querySelectorAll('.workspace-component-card').length + 1;
                    const tokenName = `${prefix}${currentVarsCount}`;
                    
                    const mockEntity = { id: `new_${Date.now()}`, type: opt.type, points: 0.0 };
                    const mockSchema = { type: opt.type, token: tokenName };
                    
                    removePlaceholders(variablesContainer);
                    createTokenBadge(tokenName);
                    renderVariableComponent(mockEntity, mockSchema, tokenName);
                    updateWorkspaceSimulationPreview();
                    menu.remove();
                });
                menu.appendChild(item);
            });

            // Position the dropdown menu directly underneath the trigger button node frame
            const rect = addVariableTrigger.getBoundingClientRect();
            menu.style.top = `${window.scrollY + rect.bottom + 4}px`;
            menu.style.left = `${window.scrollX + rect.left}px`;
            document.body.appendChild(menu);

            // Close the menu automatically if the user clicks anywhere else on screen
            document.addEventListener('click', () => menu.remove(), { once: true });
        });
    }

    if (addInputTrigger) {
        addInputTrigger.addEventListener('click', function(e) {
            e.stopPropagation();
            
            const existingMenu = document.getElementById('active-input-dropdown-menu');
            if (existingMenu) { existingMenu.remove(); return; }

            const menu = document.createElement('div');
            menu.id = 'active-input-dropdown-menu';
            menu.style.cssText = 'position: absolute; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); padding: 4px 0; min-width: 220px; z-index: 10005; display: flex; flex-direction: column;';
            
            const options = [
                { type: 'mathematical_expression', label: 'SymPy Math Expression', icon: 'fa-square-root-alt', prefix: 'math' },
                { type: 'multiple_choice', label: 'Multiple Choice Radio Grid', icon: 'fa-list-ul', prefix: 'mc' },
                { type: 'numeric_tolerance', label: 'Numeric Entry w/ Tolerance', icon: 'fa-percentage', prefix: 'numInput' },
                { type: 'short_text_input', label: 'Short Text Response Field', icon: 'fa-minus', prefix: 'textInput' },
                { type: 'matrix_input', label: 'Matrix Vector Entry Grid', icon: 'fa-th', prefix: 'matrixInput' }
            ];

            options.forEach(opt => {
                const item = document.createElement('button');
                item.type = 'button';
                item.style.cssText = 'background: none; border: none; padding: 6px 12px; text-align: left; font-size: 0.8rem; color: #334155; cursor: pointer; display: flex; align-items: center; gap: 8px; width: 100%; transition: background 0.1s;';
                item.innerHTML = `<i class="fas ${opt.icon}" style="width:14px; color:#64748b;"></i> ${opt.label}`;
                
                item.addEventListener('mouseover', () => { item.style.background = '#f1f5f9'; });
                item.addEventListener('mouseout', () => { item.style.background = 'none'; });
                
                item.addEventListener('click', function() {
                    const currentInputsCount = inputsContainer.querySelectorAll('.workspace-component-card').length + 1;
                    const tokenName = `${opt.prefix}${currentInputsCount}`;
                    
                    const mockEntity = { id: `new_${Date.now()}`, type: opt.type, points: 1.0 };
                    const mockSchema = { type: opt.type, token: tokenName };
                    
                    removePlaceholders(inputsContainer);
                    createTokenBadge(tokenName);
                    renderInputFormComponent(mockEntity, mockSchema, tokenName);
                    updateWorkspaceSimulationPreview();
                    menu.remove();
                });
                menu.appendChild(item);
            });

            const rect = addInputTrigger.getBoundingClientRect();
            menu.style.top = `${window.scrollY + rect.bottom + 4}px`;
            menu.style.left = `${window.scrollX + rect.left}px`;
            document.body.appendChild(menu);

            document.addEventListener('click', () => menu.remove(), { once: true });
        });
    }

    if (htmlCanvasEditor) {
        htmlCanvasEditor.addEventListener('input', updateWorkspaceSimulationPreview);
    }

    // -------------------------------------------------------------
    // 🎯 WORKSPACE COMPONENT DELETION CLEANUP ENGINE
    // -------------------------------------------------------------
    function handleComponentDeletion(e) {
        const deleteBtn = e.target.closest('.btn-delete-workspace-component');
        if (!deleteBtn) return;

        e.stopPropagation();

        const tokenToRemove = deleteBtn.getAttribute('data-token');
        const cardElement = deleteBtn.closest('.workspace-component-card');
        
        if (!cardElement) return;

        // A. Remove the component card from the sidebar grid layout view
        cardElement.remove();

        // B. Remove the corresponding clickable token badge from the ledger line
        if (tokensLedger) {
            const badges = tokensLedger.querySelectorAll('.token-badge-clickable');
            badges.forEach(badge => {
                if (badge.innerText === `<${tokenToRemove}>`) {
                    badge.remove();
                }
            });
        }

        // C. Clean up the rich text canvas by stripping out references to the deleted token
        if (htmlCanvasEditor) {
            let currentText = htmlCanvasEditor.innerHTML;
            
            // Handle raw token text forms as well as safely escaped variations matching <token>
            const escapePatterns = [
                `<${tokenToRemove}>`,
                `&lt;${tokenToRemove}&gt;`
            ];
            
            escapePatterns.forEach(pattern => {
                currentText = currentText.replaceAll(pattern, '');
            });
            
            htmlCanvasEditor.innerHTML = currentText;
        }

        // D. Re-evaluate column layouts and force a full simulation interface repaint
        checkEmptyColumns();
        updateWorkspaceSimulationPreview();
    }

    // Bind delegation capture loops directly to the sidebar component list container parents
    if (variablesContainer) variablesContainer.addEventListener('click', handleComponentDeletion);
    if (inputsContainer) inputsContainer.addEventListener('click', handleComponentDeletion);

    // -------------------------------------------------------------
    // 🎯 LIVE PREVIEW SIMULATION RENDERING ENGINE
    // -------------------------------------------------------------
    function updateWorkspaceSimulationPreview() {
        const renderTarget = document.getElementById('simulation-render-target');
        if (!renderTarget || !htmlCanvasEditor) return;

        let canvasContent = htmlCanvasEditor.innerHTML.trim();

        // If the canvas is empty, restore the original italicized placeholder statement
        if (!canvasContent) {
            renderTarget.innerHTML = '<p style="color: #94a3b8; font-style: italic; margin: 0;">Interactive layout testing view builds dynamically here...</p>';
            return;
        }

        // Regex pattern to catch tokens like <num1>, <math2>, etc.
        const tokenRegex = /&lt;([^&>]+)&gt;|<([^>]+)>/g;

        // Replace tokens with interactive user elements matching the entity category types
        let simulatedHtml = canvasContent.replace(tokenRegex, function(match, tokenText) {
            // Normalize token matching strings regardless of contenteditable HTML escaping variations
            const cleanToken = (tokenText || match).replace(/[<>&]/g, '').trim();

            // A. CORE VARIABLES (Render as green inline mathematical parameter badges)
            if (cleanToken.startsWith('num') && !cleanToken.startsWith('numInput') || 
                cleanToken.startsWith('equation') || 
                cleanToken.startsWith('matrix') && !cleanToken.startsWith('matrixInput') || 
                cleanToken.startsWith('stringArray')) {
                return `<span class="simulated-math-variable-badge" style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.9rem; display: inline-block; margin: 0 2px;" title="Dynamic Student Variable Allocation Matrix Slot">[x]</span>`;
            } 
            
            // B. SYMPY MATHEMATICAL EXPRESSIONS
            else if (cleanToken.startsWith('math')) {
                return `
                    <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px;">
                        <input type="text" placeholder="Enter math answer..." disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; width: 160px; font-family: monospace; color: #334155;">
                        <span style="font-size: 0.75rem; color: #16a34a; font-weight: 600; margin-left: 4px;"><i class="fas fa-square-root-alt"></i></span>
                    </div>
                `;
            } 
            
            // C. MULTIPLE CHOICE RADIO BUTTON GRIDS
            else if (cleanToken.startsWith('mc')) {
                return `
                    <div style="margin: 8px 0; background: #ffffff; border: 1px solid #e2e8f0; padding: 10px; border-radius: 6px; max-width: 300px;">
                        <label style="display: flex; align-items: center; gap: 8px; font-size: 0.85rem; color: #475569;"><input type="radio" disabled> Option selection placeholder layout slot</label>
                    </div>
                `;
            } 
            
            // D. 🎯 NEW: NUMERIC ENTRY WITH TOLERANCE
            else if (cleanToken.startsWith('numInput')) {
                return `
                    <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px;">
                        <input type="text" placeholder="0.00" disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; width: 90px; text-align: right; font-family: monospace; color: #334155;">
                        <span style="font-size: 0.75rem; color: #64748b; font-weight: 500; margin-left: 4px;" title="Evaluated within a tolerance window">&plusmn; tol</span>
                    </div>
                `;
            } 
            
            // E. 🎯 NEW: SHORT TEXT SUBMISSIONS (Direct String Match)
            else if (cleanToken.startsWith('textInput')) {
                return `
                    <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px; width: 100%; max-width: 280px;">
                        <input type="text" placeholder="Type short answer response..." disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 6px 10px; border-radius: 4px; font-size: 0.85rem; width: 100%; box-sizing: border-box; color: #334155;">
                    </div>
                `;
            } 
            
            // F. 🎯 NEW: MATRIX SOLUTION GRIDS
            else if (cleanToken.startsWith('matrixInput')) {
                return `
                    <div style="display: inline-grid; grid-template-columns: repeat(2, 45px); gap: 4px; border-left: 2px solid #475569; border-right: 2px solid #475569; padding: 2px 6px; vertical-align: middle; margin: 6px 2px; border-radius: 4px;">
                        <input type="text" placeholder="0" disabled style="width:100%; text-align:center; font-size:0.8rem; padding:2px 0; border:1px solid #e2e8f0; border-radius:3px;">
                        <input type="text" placeholder="0" disabled style="width:100%; text-align:center; font-size:0.8rem; padding:2px 0; border:1px solid #e2e8f0; border-radius:3px;">
                        <input type="text" placeholder="0" disabled style="width:100%; text-align:center; font-size:0.8rem; padding:2px 0; border:1px solid #e2e8f0; border-radius:3px;">
                        <input type="text" placeholder="0" disabled style="width:100%; text-align:center; font-size:0.8rem; padding:2px 0; border:1px solid #e2e8f0; border-radius:3px;">
                    </div>
                `;
            }
            
            // If it doesn't match our tokens, return the original text intact
            return match;
        });

        renderTarget.innerHTML = simulatedHtml;
    }

    // -------------------------------------------------------------
    // UI Builder Render Framework Functions
    // -------------------------------------------------------------

    function createTokenBadge(token) {
        if (!tokensLedger) return;
        // Skip duplicate badges if token name is already registered in top ledger bar
        if (Array.from(tokensLedger.children).some(b => b.innerText === `<${token}>`)) return;

        const badge = document.createElement('span');
        badge.className = 'token-badge-clickable';
        badge.style.cssText = 'background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; cursor: pointer; user-select: none; transition: all 0.15s;';
        badge.innerText = `<${token}>`;
        
        badge.addEventListener('mouseover', () => { badge.style.background = '#bae6fd'; });
        badge.addEventListener('mouseout', () => { badge.style.background = '#e0f2fe'; });
        
        badge.addEventListener('click', function() {
            if (!htmlCanvasEditor) return;
            htmlCanvasEditor.focus();
            document.execCommand('insertText', false, `<${token}>`);
        });

        tokensLedger.appendChild(badge);
    }

    function renderVariableComponent(entity, schema, tokenName) {
        if (!variablesContainer) return;
        
        const card = document.createElement('div');
        card.className = 'workspace-component-card';
        card.setAttribute('data-entity-id', entity.id);
        card.setAttribute('data-entity-type', entity.type);
        card.style.cssText = 'background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px;';
        
        let fieldsHtml = '';
        
        if (entity.type === 'variable_numeric') {
            fieldsHtml = `
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px;">
                    <label style="font-size: 0.75rem; color: #475569;">Min: <input type="number" class="val-input" value="${schema.min ?? -9}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Max: <input type="number" class="val-input" value="${schema.max ?? 9}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Step: <input type="number" class="val-input" value="${schema.step ?? 1}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                </div>
                <label style="font-size: 0.75rem; color: #475569; display:block; margin-top:4px;">Exclude (Comma-separated): 
                    <input type="text" value="${(schema.exclude || []).join(', ')}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        } else if (entity.type === 'variable_equation') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569;">Formula expression string: 
                    <input type="text" value="${schema.formula || ''}" placeholder="e.g. 3*x + 5" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        } else if (entity.type === 'variable_matrix') {
            fieldsHtml = `
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 4px;">
                    <label style="font-size: 0.75rem; color: #475569;">Rows: <input type="number" value="${schema.rows ?? 3}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Cols: <input type="number" value="${schema.cols ?? 3}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                </div>
                <div style="background: #ffffff; border: 1px dashed #cbd5e1; padding: 6px; border-radius: 4px; font-size: 0.75rem; text-align: center; color: #64748b;"><i class="fas fa-th"></i> Matrix cell configuration matrix grid mapped</div>
            `;
        } else if (entity.type === 'variable_string_array') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569; display:block; margin-bottom:4px;">Array values (Comma-separated text): 
                    <input type="text" value="${(schema.strings || ['A', 'B', 'C']).join(', ')}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        } else {
            fieldsHtml = `<p style="font-size: 0.8rem; color:#64748b; margin:0;">Complex structural configurations [${entity.type}]</p>`;
        }

        card.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px dashed #e2e8f0; padding-bottom: 6px; margin-bottom: 4px;">
                <span style="font-weight: 600; font-size: 0.85rem; color: #0284c7;"><i class="fas fa-calculator"></i> &lt;${tokenName}&gt;</span>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 0.7rem; background:#e0f2fe; color:#0369a1; padding:1px 6px; border-radius:10px; font-weight:500;">Variable</span>
                    <button type="button" class="btn-delete-workspace-component" data-token="${tokenName}" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.8rem; padding: 2px; transition: color 0.15s;" onmouseover="this.style.color='#ef4444'" onmouseout="this.style.color='#94a3b8'"><i class="fas fa-trash"></i></button>
                </div>
            </div>
            <div class="component-fields-wrapper">${fieldsHtml}</div>
        `;
        
        variablesContainer.appendChild(card);
    }

    function renderInputFormComponent(entity, schema, tokenName) {
        if (!inputsContainer) return;

        const card = document.createElement('div');
        card.className = 'workspace-component-card';
        card.setAttribute('data-entity-id', entity.id);
        card.setAttribute('data-entity-type', entity.type);
        card.style.cssText = 'background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px;';
        
        let fieldsHtml = '';
        
        if (entity.type === 'mathematical_expression') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569; display:block; margin-bottom:4px;">Correct Target Formula: 
                    <input type="text" value="${schema.correct_formula || ''}" placeholder="e.g. factor(x**2 - 1)" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                <label style="font-size: 0.75rem; color: #475569; display:block;">Evaluation Structural Target Form:
                    <select style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                        <option value="Factor" ${schema.expected_structural_form === 'Factor' ? 'selected' : ''}>Factor Analysis Matching</option>
                        <option value="Simplify" ${schema.expected_structural_form === 'Simplify' ? 'selected' : ''}>Simplify Algebraic Equivalency</option>
                        <option value="Expand" ${schema.expected_structural_form === 'Expand' ? 'selected' : ''}>Expand Polynomial Statements</option>
                    </select>
                </label>
            `;
        } else if (entity.type === 'multiple_choice') {
            const choiceCount = schema.choices ? schema.choices.length : 0;
            fieldsHtml = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                    <span style="font-size: 0.75rem; color:#475569;">Mode: <strong>${schema.decoy_generation_mode || 'Manual'}</strong></span>
                    <span style="font-size: 0.75rem; color:#475569;">Options Array Count: <strong>${choiceCount}</strong></span>
                </div>
                <button type="button" style="width:100%; background:#ffffff; border:1px solid #cbd5e1; font-size:0.75rem; padding:4px; border-radius:4px; cursor:pointer; font-weight:500; color:#475569;"><i class="fas fa-list-ul"></i> Edit Options</button>
            `;
        } else if (entity.type === 'numeric_tolerance') {
            fieldsHtml = `
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
                    <label style="font-size: 0.75rem; color: #475569;">Value: <input type="text" value="${schema.correct_value || ''}" placeholder="e.g. 3.141" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">&plusmn; Tolerance: <input type="number" step="0.001" value="${schema.tolerance ?? 0.01}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                </div>
            `;
        } else if (entity.type === 'short_text_input') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569; display:block;">Expected text answer string: 
                    <input type="text" value="${(schema.expected_answers || []).join(', ')}" placeholder="e.g. true, false" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        } else if (entity.type === 'matrix_input') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569; display:block;">Correct target matrix expression reference: 
                    <input type="text" value="${schema.correct_matrix_variable || ''}" placeholder="e.g. <matrix1>" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        } else {
            fieldsHtml = `<p style="font-size: 0.8rem; color:#64748b; margin:0;">Form layout details config [${entity.type}]</p>`;
        }

        card.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px dashed #e2e8f0; padding-bottom: 6px; margin-bottom: 4px;">
                <span style="font-weight: 600; font-size: 0.85rem; color: #16a34a;"><i class="fas fa-pen-alt"></i> &lt;${tokenName}&gt;</span>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 0.7rem; background:#dcfce7; color:#166534; padding:1px 6px; border-radius:10px; font-weight:500;">${entity.points} Pts</span>
                    <button type="button" class="btn-delete-workspace-component" data-token="${tokenName}" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.8rem; padding: 2px; transition: color 0.15s;" onmouseover="this.style.color='#ef4444'" onmouseout="this.style.color='#94a3b8'"><i class="fas fa-trash"></i></button>
                </div>
            </div>
            <div class="component-fields-wrapper">${fieldsHtml}</div>
        `;
        
        inputsContainer.appendChild(card);
    }

    // Helper visibility clearing methods
    function removePlaceholders(container) {
        if (!container) return;
        const italicText = container.querySelector('p');
        if (italicText && italicText.style.fontStyle === 'italic') {
            italicText.remove();
        }
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
});