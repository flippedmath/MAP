/**
 * course_intro.js
 * Handles frontend interactions for the Course Introduction pane,
 * including external link interception and Quill editor management.
 */

let quillInstance = null;

// Scans and configures external link targets
function configureLinkTargets() {
    const displayContainer = document.getElementById('intro-display-view');
    if (!displayContainer) return;

    const links = displayContainer.querySelectorAll('a');
    const currentHost = window.location.host;

    links.forEach(link => {
        const absoluteHref = link.href; 
        if (absoluteHref) {
            const isWebLink = absoluteHref.startsWith('http://') || absoluteHref.startsWith('https://');
            if (isWebLink) {
                const isInternal = absoluteHref.includes(currentHost);
                const isLocalMatch = (currentHost.includes('localhost') && absoluteHref.includes('127.0.0.1')) ||
                                     (currentHost.includes('127.0.0.1') && absoluteHref.includes('localhost'));

                if (!isInternal && !isLocalMatch) {
                    link.setAttribute('target', '_blank');
                    link.setAttribute('rel', 'noopener noreferrer');
                } else {
                    link.removeAttribute('target');
                }
            }
        }
    });
}


// Toggles visibility between display mode and edit mode
function toggleIntroEditor(showEditor) {
    const displayDiv = document.getElementById('intro-display-view');
    const editorDiv = document.getElementById('intro-editor-view');
    const editBtn = document.getElementById('edit-intro-btn');
    const payloadInput = document.getElementById('id_introduction_payload');

    if (showEditor) {
        if (displayDiv) displayDiv.style.display = 'none';
        if (editorDiv) editorDiv.style.display = 'block';
        if (editBtn) editBtn.style.display = 'none';

        if (!quillInstance && typeof Quill !== 'undefined' && document.getElementById('quill-editor-container')) {
            quillInstance = new Quill('#quill-editor-container', {
                theme: 'snow',
                modules: {
                    table: { operationMenu: true },
                    toolbar: [
                        [{ 'font': [] }, { 'size': [] }],
                        ['bold', 'italic', 'underline', 'strike'],
                        [{ 'color': [] }, { 'background': [] }],
                        [{ 'list': 'ordered'}, { 'list': 'bullet' }],
                        [{ 'indent': '-1'}, { 'indent': '+1' }, { 'align': [] }],
                        ['link', 'image', 'formula'],
                        ['table'], 
                        ['clean']
                    ],
                    clipboard: {
                        matchers: [
                            // 🎯 FIX 1: Robust Table cell fallback catcher to keep layout parser from crashing
                            ['TD, TH', function(node, delta) {
                                // If row properties contain javascript objects or errors, sanitize them on insertion
                                if (node.getAttribute('data-row') === '[object Object]') {
                                    node.setAttribute('data-row', 'true');
                                }
                                return delta;
                            }],
                            ['table', function(node, delta) {
                                if (node && node.classList && node.classList.contains('no-border')) {
                                    if (delta && typeof delta.forEach === 'function') {
                                        delta.forEach(op => {
                                            if (op && op.attributes && op.attributes.table) {
                                                op.attributes.table = { ...op.attributes.table, className: 'no-border' };
                                            }
                                        });
                                    }
                                }
                                return delta;
                            }]
                        ]
                    }
                }
            });

            setupTableContextMenu();
        }
        
        if (quillInstance && payloadInput) {
            let cleanHtml = "";
            let rawValue = payloadInput.value ? payloadInput.value.trim() : "";

            // console.log("Raw Payload Value being loaded:", rawValue);

            // Handle parsing strategies
            if (rawValue) {
                if (rawValue.startsWith('{') && rawValue.endsWith('}')) {
                    try {
                        const parsedData = JSON.parse(rawValue);
                        cleanHtml = parsedData.html_content || "";
                    } catch (e) {
                        console.warn("Strategy 1 parse failed. Trying regex extraction...");
                    }
                }

                if (!cleanHtml) {
                    const match = rawValue.match(/(?:"html_content"|'html_content'|html_content&quot;)\s*:\s*trim_start"(.*)"\s*}/s) ||
                                  rawValue.match(/(?:"html_content"|'html_content'|html_content&quot;)\s*:\s*"(.*)"\s*}/s) ||
                                  rawValue.match(/(?:"html_content"|'html_content'|html_content&quot;)\s*:\s*'(.*)'\s*}/s);
                    if (match && match[1]) {
                        cleanHtml = match[1]
                            .replace(/\\"/g, '"')    
                            .replace(/\\'/g, "'")    
                            .replace(/\\n/g, '\n')   
                            .replace(/\\t/g, '\t');  
                    }
                }

                if (!cleanHtml && rawValue.includes('&quot;')) {
                    try {
                        const decodedJson = rawValue.replace(/&quot;/g, '"').replace(/&#x27;/g, "'");
                        const parsedData = JSON.parse(decodedJson);
                        cleanHtml = parsedData.html_content || "";
                    } catch (err) {
                        console.warn("Strategy 3 double-unescape failed.");
                    }
                }

                if (!cleanHtml) {
                    cleanHtml = rawValue;
                }
            }

            // Sanitize literal "[object Object]" instances in the string code
            if (cleanHtml) {
                cleanHtml = cleanHtml.replace(/data-row="\[object Object\]"/g, 'data-row="true"');
            }

            // 🎯 FIXED STRATEGY: Parse HTML string into an isolated DOM tree to prune KaTeX remnants perfectly
            if (cleanHtml) {
                const tempParser = new DOMParser();
                const doc = tempParser.parseFromString(cleanHtml, 'text/html');
                
                // Find all formula spans
                const formulas = doc.querySelectorAll('.ql-formula');
                formulas.forEach(formula => {
                    // 1. Completely hollow out the inside of the formula span so Quill can rebuild it fresh
                    formula.innerHTML = '';
                    
                    // 2. Look for any orphaned .katex-html sibling containers that leaked right next to it and remove them
                    let nextSibling = formula.nextSibling;
                    while (nextSibling && (
                        (nextSibling.nodeType === Node.ELEMENT_NODE && (
                            nextSibling.classList.contains('katex-html') || 
                            nextSibling.classList.contains('katex')
                        )) || 
                        (nextSibling.nodeType === Node.TEXT_NODE && !nextSibling.textContent.trim()) // skip whitespace
                    )) {
                        const toRemove = nextSibling;
                        nextSibling = nextSibling.nextSibling;
                        if (toRemove.nodeType === Node.ELEMENT_NODE) {
                            toRemove.remove();
                        }
                    }
                });
                
                // Export our pristine normalized string layout
                cleanHtml = doc.body.innerHTML;
            }

            console.log("Sanitized HTML string passing to Quill clipboard:", cleanHtml);

            // Clear editor before pasting to ensure canvas state is clean
            quillInstance.setText('');
            
            // Load the clean structural shells into the Quill engine
            quillInstance.clipboard.dangerouslyPasteHTML(0, cleanHtml);
            
            setTimeout(() => {
                if (quillInstance) {
                    quillInstance.update('user');
                }
            }, 50);
        }
        
    } else {
        if (displayDiv) displayDiv.style.display = 'block';
        if (editorDiv) editorDiv.style.display = 'none';
        if (editBtn) editBtn.style.display = 'inline-block';
    }
}


// Builds and attaches a custom interactive point-and-click context menu
function setupTableContextMenu() {
    const editorContainer = document.getElementById('quill-editor-container');
    if (!editorContainer) return;

    // Create a single reusable menu element block
    let menu = document.getElementById('custom-quill-table-menu');
    if (!menu) {
        menu = document.createElement('div');
        menu.id = 'custom-quill-table-menu';
        menu.className = 'custom-ql-context-menu';
        document.body.appendChild(menu);
    }

    // Hide the menu whenever the user clicks anywhere else on the screen
    document.addEventListener('click', function() {
        menu.style.display = 'none';
    });

    // Listen for right clicks inside the editor container bounds
    editorContainer.addEventListener('contextmenu', function(e) {
        const cell = e.target.closest('td, th');
        if (!cell || !quillInstance) return;

        // Prevent the default browser options panel from opening
        e.preventDefault();

        const tableModule = quillInstance.getModule('table');
        if (!tableModule) return;

        // Find the parent table element to see if borders are currently hidden
        const parentTable = cell.closest('table');
        const hasHiddenBorders = parentTable ? parentTable.classList.contains('no-border') : false;

        // Populate menu with specific command types parsed by our refactored handler
        menu.innerHTML = `
            <div class="menu-item" data-command="toggle-borders" style="font-weight: 600; color: #2563eb;">
                ${hasHiddenBorders ? '👁️ Show Table Borders' : '🙈 Hide Table Borders'}
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

        // Position the menu exactly at the mouse pointer coordinates
        menu.style.left = `${e.pageX}px`;
        menu.style.top = `${e.pageY}px`;
        menu.style.display = 'block';

        // Bind clicks to handle Quill 2.0 API calls safely
        const items = menu.querySelectorAll('.menu-item');
        items.forEach(item => {
            item.onclick = function() {
                const command = item.getAttribute('data-command');
                const arg = parseInt(item.getAttribute('data-arg'), 10);

                if (command === 'toggle-borders') {
                    if (parentTable) {
                        // Toggle the border layout class directly on the live DOM table node
                        parentTable.classList.toggle('no-border');
                        // Notify Quill that a text modification happened to trigger change tracks
                        quillInstance.update('user'); 
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
            };
        });
    });
}

// Scans the static container and converts raw formulas safely
function renderStaticFormulas() {
    const displayContainer = document.getElementById('intro-display-view');
    if (!displayContainer || typeof katex === 'undefined') return;

    // Target the true formula tags saved via innerHTML
    const formulaSpans = displayContainer.querySelectorAll('.ql-formula');
    formulaSpans.forEach(span => {
        const latex = span.getAttribute('data-value');
        if (latex) {
            try {
                katex.render(latex, span, { 
                    displayMode: false, 
                    throwOnError: false 
                });
            } catch (err) {
                console.error("KaTeX standard render error:", err);
            }
        }
    });
}

// Ensure link checker, formula typesetter, and click handlers bind once the DOM finishes loading
document.addEventListener("DOMContentLoaded", function() {
    configureLinkTargets();
    
    // 🎯 STEP 1: Backup the clean HTML string BEFORE KaTeX runs and alters the DOM nodes
    const displayContainer = document.getElementById('intro-display-view');
    const payloadInput = document.getElementById('id_introduction_payload');
    
    if (displayContainer && payloadInput && !payloadInput.value.trim()) {
        // If the database payload input rendered empty, populate it using the current visible HTML
        payloadInput.value = displayContainer.innerHTML;
    }
    
    // 🎯 STEP 2: Now it is safe to turn saved formulas into visual calculus graphics
    renderStaticFormulas();

    const editBtn = document.getElementById('edit-intro-btn');
    if (editBtn) {
        editBtn.addEventListener('click', function() {
            toggleIntroEditor(true);
        });
    }

    const cancelBtn = document.getElementById('cancel-intro-btn');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', function() {
            toggleIntroEditor(false);
            renderStaticFormulas();
        });
    }

    const saveForm = document.getElementById('intro-save-form');
    if (saveForm) {
        saveForm.addEventListener('submit', function(e) {
            if (quillInstance) {
                // 🎯 FIX: Use root.innerHTML to lock in <span class="ql-formula" data-value="..."> elements
                const htmlOutput = quillInstance.root.innerHTML;
                const jsonPayload = JSON.stringify({ html_content: htmlOutput });
                const payloadInput = document.getElementById('id_introduction_payload');
                if (payloadInput) {
                    payloadInput.value = jsonPayload;
                }
            }
        });
    }
});
