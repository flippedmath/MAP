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

    // Targets for the creation trigger buttons
    const addVariableTrigger = document.getElementById('add-variable-trigger');
    const addInputTrigger = document.getElementById('add-input-trigger');

    const saveDraftBtn = document.getElementById('btn-save-master-problem');
    const saveStatusSpan = document.getElementById('overlay-save-status');

    // 🎯 NEW: Global Workspace Quill Editor Tracker Instance
    let workspaceQuillInstance = null;

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
            
            // Clear active canvas state values completely
            if (htmlCanvasEditor) htmlCanvasEditor.innerHTML = '';

            const response = await fetch(`/api/problem/${problemId}/workspace-data/`);
            if (!response.ok) throw new Error("Failed to load problem data maps.");
            
            const data = await response.json();
            
            // 🎯 FIXED: Clean out all previous systemic classes and wrappers entirely
            if (htmlCanvasEditor) {
                htmlCanvasEditor.removeAttribute('class'); // Strip all structural classes
                htmlCanvasEditor.innerHTML = ''; // Ensure it's a completely blank slate
            }

            // 🎯 Clean Lazy-Initialize for Quill 2.0.2
            if (!workspaceQuillInstance && typeof Quill !== 'undefined' && htmlCanvasEditor) {
                try {
                    workspaceQuillInstance = new Quill('#editor-html-insert-canvas', {
                        theme: 'snow',
                        modules: {
                            toolbar: '#workspace-quill-toolbar-container'
                        }
                    });

                    console.log("✅ SUCCESS: Workspace Quill instance spawned with math capabilities.");

                    workspaceQuillInstance.on('text-change', function() {
                        updateWorkspaceSimulationPreview();
                        if (saveStatusSpan) {
                            saveStatusSpan.innerHTML = `<i class="fas fa-cloud"></i> Unsaved changes`;
                        }
                    });

                } catch (quillInitError) {
                    console.error("Quill initialization exception:", quillInitError);
                }
            }

            // 🎯 POPULATE CONTENT SAFELY
            if (workspaceQuillInstance && workspaceQuillInstance.root) {
                // Ensure the editor container is explicitly enabled for editing
                workspaceQuillInstance.enable(true);
                
                if (data.html_content) {
                    // Create an isolated safe virtual document check
                    const parser = new DOMParser();
                    const doc = parser.parseFromString(data.html_content, 'text/html');
                    const embeddedCanvas = doc.getElementById('editor-html-insert-canvas');
                    
                    if (embeddedCanvas) {
                        // If it somehow extracted the outer skeleton wrapper, pluck just the clean inner content
                        workspaceQuillInstance.root.innerHTML = embeddedCanvas.innerHTML;
                    } else {
                        // Otherwise, your backend data is already a perfect raw HTML string! Inject it straight in.
                        workspaceQuillInstance.root.innerHTML = data.html_content;
                    }
                } else {
                    workspaceQuillInstance.root.innerHTML = '<p><br></p>';
                }
                
                // Run immediate simulation verification cycle
                updateWorkspaceSimulationPreview();
                if (saveStatusSpan) {
                    saveStatusSpan.innerHTML = `<i class="fas fa-check-circle" style="color: #10b981;"></i> Synced`;
                }
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

    // 3. Component Add Instantiation Events
    if (addVariableTrigger) {
        addVariableTrigger.addEventListener('click', function(e) {
            e.stopPropagation();
            const existingMenu = document.getElementById('active-variable-dropdown-menu');
            if (existingMenu) { existingMenu.remove(); return; }

            const menu = document.createElement('div');
            menu.id = 'active-variable-dropdown-menu';
            menu.style.cssText = 'position: absolute; background: #ffffff; border: 1px solid #cbd5e1; border-radius: 6px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); padding: 4px 0; min-width: 180px; z-index: 10005; display: flex; flex-direction: column;';
            
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
                    // Replace broad lookups with explicit direct-descendant selections:
                    const currentVarsCount = variablesContainer.querySelectorAll(':scope > .workspace-component-card').length + 1;
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

            const rect = addVariableTrigger.getBoundingClientRect();
            menu.style.top = `${window.scrollY + rect.bottom + 4}px`;
            menu.style.left = `${window.scrollX + rect.left}px`;
            document.body.appendChild(menu);
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
                    // Do the same for inputsContainer layout calculations:
                    const currentInputsCount = inputsContainer.querySelectorAll(':scope > .workspace-component-card').length + 1;
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

    // -------------------------------------------------------------
    // LIVE PREVIEW SIMULATION RENDERING ENGINE
    // -------------------------------------------------------------
    function updateWorkspaceSimulationPreview() {
        const renderTarget = document.getElementById('simulation-render-target');
        if (!renderTarget) return;

        // Read output markup data via root.innerHTML out of Quill instead of raw text elements
        let canvasContent = workspaceQuillInstance ? workspaceQuillInstance.root.innerHTML.trim() : '';

        if (!canvasContent || canvasContent === '<p><br></p>') {
            renderTarget.innerHTML = '<p style="color: #94a3b8; font-style: italic; margin: 0;">Interactive layout testing view builds dynamically here...</p>';
            return;
        }

        // 1. 🎯 CREATE AN IN-MEMORY DOM TREE FOR THE PREVIEW
        // This isolates the content from the active editor so we can safely strip KaTeX elements.
        const tempContainer = document.createElement('div');
        tempContainer.innerHTML = canvasContent;

        // 2. 🎯 FIND AND CONVERT ALL ACTIVE QUILL FORMULAS TO PREVIEW SLOTS
        // We find elements with class 'ql-formula', grab their raw LaTeX data string,
        // and replace them with a safe placeholder class that the tokenizer won't touch.
        const formulaNodes = tempContainer.querySelectorAll('.ql-formula');
        formulaNodes.forEach(formula => {
            const latexValue = formula.getAttribute('data-value') || '';
            const mathSpan = document.createElement('span');
            mathSpan.className = 'preview-static-latex'; // Safe signature class
            mathSpan.textContent = latexValue;           // Store raw string temporarily inside text context
            formula.parentNode.replaceChild(mathSpan, formula);
        });

        // 🎯 FIX A: Handle Quill alignment classes safely (Supporting blocks and lists)
        const alignedElements = tempContainer.querySelectorAll('.ql-align-right, .ql-align-center, .ql-align-justify');
        alignedElements.forEach(el => {
            let alignType = 'left';
            if (el.classList.contains('ql-align-right')) alignType = 'right';
            if (el.classList.contains('ql-align-center')) alignType = 'center';
            if (el.classList.contains('ql-align-justify')) alignType = 'justify';
            
            el.style.textAlign = alignType;
            
            // If it's a list item being aligned, force its inner block container layout to obey directionality
            if (el.tagName === 'LI') {
                el.style.listStylePosition = 'inside';
            }
        });

        // 🎯 FIX B: Group consecutive <li> elements sequentially into unified lists
        const listItems = tempContainer.querySelectorAll('li[data-list]');
        if (listItems.length > 0) {
            let currentWrapper = null;
            let currentType = null;

            Array.from(listItems).forEach(li => {
                const listType = li.getAttribute('data-list'); // 'bullet' or 'ordered'
                const targetTagName = listType === 'bullet' ? 'UL' : 'OL';

                // Check if the previous element in the markup is an active wrapper of the exact same type
                const previousElement = li.previousElementSibling;
                const isContinuation = previousElement && previousElement.tagName === targetTagName && currentType === listType;

                if (!isContinuation) {
                    // Only build a brand new parent container if the chain broke or changed type
                    currentWrapper = document.createElement(targetTagName);
                    currentWrapper.style.paddingLeft = '24px';
                    currentWrapper.style.margin = '8px 0';
                    
                    if (listType === 'bullet') {
                        currentWrapper.style.listStyleType = 'disc';
                    }

                    // If the item has alignment styling, pass the text alignment up to the parent wrapper
                    if (li.style.textAlign === 'right' || li.style.textAlign === 'center') {
                        currentWrapper.style.textAlign = li.style.textAlign;
                    }

                    li.parentNode.insertBefore(currentWrapper, li);
                    currentType = listType;
                }

                // Move the element into the grouped list block execution stream
                currentWrapper.appendChild(li);
                li.removeAttribute('data-list');
            });
        }

        // Pull out the sanitized template HTML string to run through your existing tokenizer
        let workingHtml = tempContainer.innerHTML;

        // 3. 🎯 TOKEN MATCH ENGINE (REDUCED TO MATCH ONLY YOUR EXPLICIT TEMPLATE TOKENS)
        // Restricted to capture template tags and ignore raw structural tags
        const tokenRegex = /&lt;([^&>]+)&gt;|<(math\d+|mc\d+|numInput\d+|textInput\d+|matrixInput\d+|num\d+|equation\d+|matrix\d+|stringArray\d+)>/g;

        let simulatedHtml = workingHtml.replace(tokenRegex, function(match, tokenText) {
            const cleanToken = (tokenText || match).replace(/[<>&]/g, '').trim();

            if (cleanToken.startsWith('num') && !cleanToken.startsWith('numInput') || 
                cleanToken.startsWith('equation') || 
                cleanToken.startsWith('matrix') && !cleanToken.startsWith('matrixInput') || 
                cleanToken.startsWith('stringArray')) {
                return `<span class="simulated-math-variable-badge" style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.9rem; display: inline-block; margin: 0 2px;">[x]</span>`;
            } 
            else if (cleanToken.startsWith('math')) {
                return `
                    <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px;">
                        <input type="text" placeholder="Enter math answer..." disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; width: 160px; font-family: monospace; color: #334155;">
                        <span style="font-size: 0.75rem; color: #16a34a; font-weight: 600; margin-left: 4px;"><i class="fas fa-square-root-alt"></i></span>
                    </div>
                `;
            } 
            else if (cleanToken.startsWith('mc')) {
                return `
                    <div style="margin: 8px 0; background: #ffffff; border: 1px solid #e2e8f0; padding: 10px; border-radius: 6px; max-width: 300px;">
                        <label style="display: flex; align-items: center; gap: 8px; font-size: 0.85rem; color: #475569;"><input type="radio" disabled> Option selection placeholder layout slot</label>
                    </div>
                `;
            } 
            else if (cleanToken.startsWith('numInput')) {
                return `
                    <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px;">
                        <input type="text" placeholder="0.00" disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 4px 8px; border-radius: 4px; font-size: 0.9rem; width: 90px; text-align: right; font-family: monospace; color: #334155;">
                        <span style="font-size: 0.75rem; color: #64748b; font-weight: 500; margin-left: 4px;">&plusmn; tol</span>
                    </div>
                `;
            } 
            else if (cleanToken.startsWith('textInput')) {
                return `
                    <div class="simulated-input-wrapper" style="display: inline-block; vertical-align: middle; margin: 4px 2px; width: 100%; max-width: 280px;">
                        <input type="text" placeholder="Type short answer response..." disabled style="background: #ffffff; border: 1px solid #cbd5e1; padding: 6px 10px; border-radius: 4px; font-size: 0.85rem; width: 100%; box-sizing: border-box; color: #334155;">
                    </div>
                `;
            } 
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
            return match;
        });

        // Write tokenized result into the target panel DOM layout structure
        renderTarget.innerHTML = simulatedHtml;

        // 4. 🎯 RENDER KATED EXPRESSIONS INSIDE THE SIMULATED PREVIEW
        // Now that the raw HTML string is updated without leaking artifacts,
        // we call KaTeX to convert our placeholder elements into beautifully rendered math equations.
        if (typeof katex !== 'undefined') {
            const staticFormulas = renderTarget.querySelectorAll('.preview-static-latex');
            staticFormulas.forEach(span => {
                const formulaString = span.textContent.trim();
                try {
                    katex.render(formulaString, span, { 
                        displayMode: false, 
                        throwOnError: false 
                    });
                } catch (err) {
                    console.error("Preview math rendering breakdown:", err);
                }
            });
        }
    }

    function createTokenBadge(token) {
        if (!tokensLedger) return;
        if (Array.from(tokensLedger.children).some(b => b.innerText === `<${token}>`)) return;

        const badge = document.createElement('span');
        badge.className = 'token-badge-clickable';
        badge.style.cssText = 'background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; cursor: pointer; user-select: none; transition: all 0.15s;';
        badge.innerText = `<${token}>`;
        
        badge.addEventListener('mouseover', () => { badge.style.background = '#bae6fd'; });
        badge.addEventListener('mouseout', () => { badge.style.background = '#e0f2fe'; });
        
        // 🎯 NEW: Upgraded Quill Token Injection Routine targeting current selection coordinates
        badge.addEventListener('click', function() {
            if (!workspaceQuillInstance) return;
            
            // Look up where the user's focus cursor is located inside the text
            const range = workspaceQuillInstance.getSelection(true);
            if (range) {
                // Drop the token string precisely at the caret location index
                workspaceQuillInstance.insertText(range.index, `<${token}>`, 'user');
                // Advance the caret cursor position past the newly added token characters
                workspaceQuillInstance.setSelection(range.index + token.length + 2, 'user');
            }
        });

        tokensLedger.appendChild(badge);
    }

    function handleComponentDeletion(e) {
        const deleteBtn = e.target.closest('.btn-delete-workspace-component');
        if (!deleteBtn) return;

        e.stopPropagation();
        const tokenToRemove = deleteBtn.getAttribute('data-token');
        const cardElement = deleteBtn.closest('.workspace-component-card');
        
        if (!cardElement) return;
        cardElement.remove();

        if (tokensLedger) {
            const badges = tokensLedger.querySelectorAll('.token-badge-clickable');
            badges.forEach(badge => {
                if (badge.innerText === `<${tokenToRemove}>`) badge.remove();
            });
        }

        // 🎯 NEW: Perform automated cascading cleanup inside Quill's rich text core innerHTML parameters
        if (workspaceQuillInstance) {
            let currentText = workspaceQuillInstance.root.innerHTML;
            const escapePatterns = [`<${tokenToRemove}>`, `&lt;${tokenToRemove}&gt;`];
            escapePatterns.forEach(pattern => {
                currentText = currentText.replaceAll(pattern, '');
            });
            workspaceQuillInstance.root.innerHTML = currentText;
        }

        checkEmptyColumns();
        updateWorkspaceSimulationPreview();
    }

    if (variablesContainer) variablesContainer.addEventListener('click', handleComponentDeletion);
    if (inputsContainer) inputsContainer.addEventListener('click', handleComponentDeletion);

    // -------------------------------------------------------------
    // UI Builder Render Framework Functions
    // -------------------------------------------------------------
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
                    <label style="font-size: 0.75rem; color: #475569;">Min: <input type="number" class="val-input-min" value="${schema.min ?? -9}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Max: <input type="number" class="val-input-max" value="${schema.max ?? 9}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Step: <input type="number" class="val-input-step" value="${schema.step ?? 1}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                </div>
                <label style="font-size: 0.75rem; color: #475569; display:block; margin-top:4px;">Exclude (Comma-separated): 
                    <input type="text" class="val-input-exclude" value="${(schema.exclude || []).join(', ')}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        } else if (entity.type === 'variable_equation') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569;">Formula expression string: 
                    <input type="text" class="val-input-formula" value="${schema.formula || ''}" placeholder="e.g. 3*x + 5" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        } else if (entity.type === 'variable_matrix') {
            fieldsHtml = `
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 4px;">
                    <label style="font-size: 0.75rem; color: #475569;">Rows: <input type="number" class="val-input-rows" value="${schema.rows ?? 3}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">Cols: <input type="number" class="val-input-cols" value="${schema.cols ?? 3}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                </div>
                <div style="background: #ffffff; border: 1px dashed #cbd5e1; padding: 6px; border-radius: 4px; font-size: 0.75rem; text-align: center; color: #64748b;"><i class="fas fa-th"></i> Matrix grid mapped</div>
            `;
        } else if (entity.type === 'variable_string_array') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569; display:block; margin-bottom:4px;">Array values (Comma-separated text): 
                    <input type="text" class="val-input-strings" value="${(schema.strings || ['A', 'B', 'C']).join(', ')}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        }

        card.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px dashed #e2e8f0; padding-bottom: 6px; margin-bottom: 4px;">
                <span style="font-weight: 600; font-size: 0.85rem; color: #0284c7;"><i class="fas fa-calculator"></i> &lt;${tokenName}&gt;</span>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 0.7rem; background:#e0f2fe; color:#0369a1; padding:1px 6px; border-radius:10px; font-weight:500;">Variable</span>
                    <button type="button" class="btn-delete-workspace-component" data-token="${tokenName}" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.8rem;"><i class="fas fa-trash"></i></button>
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
                    <input type="text" class="val-input-correct-formula" value="${schema.correct_formula || ''}" placeholder="e.g. factor(x**2 - 1)" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
                <label style="font-size: 0.75rem; color: #475569; display:block;">Evaluation Structural Target Form:
                    <select class="val-input-structural-form" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
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
                <button type="button" style="width:100%; background:#ffffff; border:1px solid #cbd5e1; font-size:0.75rem; padding:4px; border-radius:4px; color:#475569;"><i class="fas fa-list-ul"></i> Edit Options</button>
            `;
        } else if (entity.type === 'numeric_tolerance') {
            fieldsHtml = `
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
                    <label style="font-size: 0.75rem; color: #475569;">Value: <input type="text" class="val-input-correct-value" value="${schema.correct_value || ''}" placeholder="e.g. 3.141" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                    <label style="font-size: 0.75rem; color: #475569;">&plusmn; Tolerance: <input type="number" class="val-input-tolerance" step="0.001" value="${schema.tolerance ?? 0.01}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:2px; border:1px solid #cbd5e1; border-radius:4px;"></label>
                </div>
            `;
        } else if (entity.type === 'short_text_input') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569; display:block;">Expected text answer string: 
                    <input type="text" class="val-input-expected" value="${(schema.expected_answers || []).join(', ')}" placeholder="e.g. true, false" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        } else if (entity.type === 'matrix_input') {
            fieldsHtml = `
                <label style="font-size: 0.75rem; color: #475569; display:block;">Correct matrix variable link: 
                    <input type="text" class="val-input-matrix-var" value="${schema.correct_matrix_variable || ''}" placeholder="e.g. <matrix1>" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                </label>
            `;
        }

        card.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px dashed #e2e8f0; padding-bottom: 6px; margin-bottom: 4px;">
                <span style="font-weight: 600; font-size: 0.85rem; color: #16a34a;"><i class="fas fa-pen-alt"></i> &lt;${tokenName}&gt;</span>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 0.7rem; background:#dcfce7; color:#166534; padding:1px 6px; border-radius:10px; font-weight:500;">${entity.points} Pts</span>
                    <button type="button" class="btn-delete-workspace-component" data-token="${tokenName}" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.8rem;"><i class="fas fa-trash"></i></button>
                </div>
            </div>
            <div class="component-fields-wrapper">${fieldsHtml}</div>
        `;
        inputsContainer.appendChild(card);
    }

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

    // 🎯 2. DRAFT PROGRESS SAVE ACTION HANDLER
    if (saveDraftBtn) {
        saveDraftBtn.addEventListener('click', function() {
            const problemId = workspaceOverlay.getAttribute('data-current-problem-id');
            
            if (!problemId) {
                alert("Error: No target problem identification selected.");
                return;
            }

            // Provide visual feedback state changes while transmitting data via AJAX
            saveDraftBtn.disabled = true;
            if (saveStatusSpan) {
                saveStatusSpan.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Saving changes...`;
            }

            // Gathers current rich-text layout markup directly out of the editor core canvas surface
            const htmlContent = workspaceQuillInstance ? workspaceQuillInstance.root.innerHTML : '';

            // 🎯 NEW: Scrape active configurations straight from the left sidebar DOM entries
            const activeEntities = [];

            // Combine both list containers to loop through all configurations seamlessly
            const componentCards = document.querySelectorAll('#sidebar-variables-list .workspace-component-card, #sidebar-inputs-list .workspace-component-card');

            componentCards.forEach(card => {
                const entityType = card.getAttribute('data-entity-type');
                
                // Pull token out of the data-token attribute on the delete button
                const deleteBtn = card.querySelector('.btn-delete-workspace-component');
                const token = deleteBtn ? deleteBtn.getAttribute('data-token') : '';

                if (!token) return; // Skip if token extraction fails

                // Establish a baseline object payload for the entity segment
                const entityData = {
                    token: token,
                    type: entityType
                };

                // 🛠️ Dynamic Variables Parsing Group
                if (entityType === 'variable_numeric') {
                    entityData.min = card.querySelector('.val-input-min')?.value || '-9';
                    entityData.max = card.querySelector('.val-input-max')?.value || '9';
                    entityData.step = card.querySelector('.val-input-step')?.value || '1';
                    entityData.exclude = card.querySelector('.val-input-exclude')?.value || '';
                } 
                else if (entityType === 'variable_equation') {
                    entityData.formula = card.querySelector('.val-input-formula')?.value || '';
                } 
                else if (entityType === 'variable_matrix') {
                    entityData.rows = card.querySelector('.val-input-rows')?.value || '3';
                    entityData.cols = card.querySelector('.val-input-cols')?.value || '3';
                } 
                else if (entityType === 'variable_string_array') {
                    entityData.strings = card.querySelector('.val-input-strings')?.value || '';
                }
                
                // 🛠️ Answer Input Fields Parsing Group
                else if (entityType === 'mathematical_expression') {
                    entityData.correct_formula = card.querySelector('.val-input-correct-formula')?.value || '';
                    entityData.structural_form = card.querySelector('.val-input-structural-form')?.value || 'Factor';
                    entityData.points = 1.0;
                } 
                else if (entityType === 'multiple_choice') {
                    entityData.mode = 'Manual';
                    entityData.points = 1.0;
                    // If you manage an option checklist array globally or within a sub-container, 
                    // you can push it here: entityData.options = []
                } 
                else if (entityType === 'numeric_tolerance') {
                    entityData.correct_value = card.querySelector('.val-input-correct-value')?.value || '';
                    entityData.tolerance = card.querySelector('.val-input-tolerance')?.value || '0.01';
                    entityData.points = 1.0;
                } 
                else if (entityType === 'short_text_input') {
                    entityData.expected = card.querySelector('.val-input-expected')?.value || '';
                    entityData.points = 1.0;
                } 
                else if (entityType === 'matrix_input') {
                    entityData.matrix_var = card.querySelector('.val-input-matrix-var')?.value || '';
                    entityData.points = 1.0;
                }

                activeEntities.push(entityData);
            });

            // Build payload properties targeting the Django update view receiver
            const payload = {
                problem_id: problemId,
                title: overlayTitleField ? overlayTitleField.value.trim() : '',
                body_html: htmlContent,
                active_entities: activeEntities // 🎯 Explicitly tracked configurations
            };

            console.log("Transmitting relational ledger payload state down to database:", payload);

            // Post down to the background view route asynchronously
            fetch(window.AQG_CONFIG.saveProblemUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken()
                },
                body: JSON.stringify(payload)
            })
            .then(response => response.json())
            .then(data => {
                console.log("Server Response Payload Object:", data);
                if (data.success) {
                    if (saveStatusSpan) {
                        saveStatusSpan.innerHTML = `<i class="fas fa-check-circle" style="color: #10b981;"></i> Draft Saved`;
                    }
                    
                    // Update matching title labels over on the underlying course dashboard rows instantly
                    const dashboardRowTitle = document.querySelector(`.problem-item-row[data-id="${problemId}"] .problem-title-text`);
                    if (dashboardRowTitle && payload.title) {
                        dashboardRowTitle.textContent = payload.title;
                    }
                } else {
                    alert("Error saving workspace configuration: " + (data.error || "Unknown server response fault exception."));
                    if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-exclamation-triangle" style="color: #ef4444;"></i> Sync Failed`;
                }
            })
            .catch(err => {
                console.error("Workspace persistence transactional operation error:", err);
                if (saveStatusSpan) saveStatusSpan.innerHTML = `<i class="fas fa-exclamation-triangle" style="color: #ef4444;"></i> Connection Lost`;
            })
            .finally(() => {
                saveDraftBtn.disabled = false;
            });
        });
    }

    // Small standalone security helper to extract active CSRF middleware tokens safely
    function getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }
});