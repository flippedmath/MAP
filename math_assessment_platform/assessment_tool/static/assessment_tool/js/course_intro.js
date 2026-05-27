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
    const sourceBank = document.getElementById('intro-raw-source');

    if (showEditor) {
        if (displayDiv) displayDiv.style.display = 'none';
        if (editorDiv) editorDiv.style.display = 'block';
        if (editBtn) editBtn.style.display = 'none';

        // Lazy initialize Quill framework container if it doesn't exist yet
        if (!quillInstance && typeof Quill !== 'undefined' && document.getElementById('quill-editor-container')) {
            quillInstance = new Quill('#quill-editor-container', {
                theme: 'snow',
                modules: {
                    table: {
                        operationMenu: true
                    },
                    toolbar: [
                        [{ 'font': [] }, { 'size': [] }],
                        ['bold', 'italic', 'underline', 'strike'],
                        [{ 'color': [] }, { 'background': [] }],
                        [{ 'list': 'ordered'}, { 'list': 'bullet' }],
                        [{ 'indent': '-1'}, { 'indent': '+1' }, { 'align': [] }],
                        ['link', 'image'],
                        ['table'], 
                        ['clean']
                    ],
                    // 🎯 FIX: Intercept the clipboard parser to preserve the no-border class
                    clipboard: {
                        matchers: [
                            ['table', function(node, delta) {
                                if (node.classList.contains('no-border')) {
                                    delta.forEach(op => {
                                        if (op.attributes && op.attributes.table) {
                                            // Carry over the custom configuration into Quill's memory attributes
                                            op.attributes.table = { 
                                                ...op.attributes.table,
                                                className: 'no-border' 
                                            };
                                        }
                                    });
                                }
                                return delta;
                            }]
                        ]
                    }
                }
            });

            // Intercept right-clicks to show custom context menu
            setupTableContextMenu();
        }
        
        if (quillInstance && sourceBank) {
            const contentPayload = sourceBank.innerHTML;
            quillInstance.clipboard.dangerouslyPasteHTML(contentPayload);
            
            // 🎯 RUNTIME SYNC: Force the live DOM node in the editor to sync classes right after pasting
            setTimeout(() => {
                const rawSourceDiv = document.createElement('div');
                rawSourceDiv.innerHTML = contentPayload;
                const sourceTables = rawSourceDiv.querySelectorAll('table');
                const editorTables = document.querySelectorAll('#quill-editor-container table');
                
                sourceTables.forEach((srcTable, index) => {
                    if (srcTable.classList.contains('no-border') && editorTables[index]) {
                        editorTables[index].classList.add('no-border');
                    }
                });
            }, 10);
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

// Ensure link checker and click handlers bind once the DOM finishes loading
document.addEventListener("DOMContentLoaded", function() {
    configureLinkTargets();

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
        });
    }

    const saveForm = document.getElementById('intro-save-form');
    if (saveForm) {
        saveForm.addEventListener('submit', function(e) {
            if (quillInstance) {
                const htmlOutput = quillInstance.getSemanticHTML();
                const jsonPayload = JSON.stringify({ html_content: htmlOutput });
                const payloadInput = document.getElementById('id_introduction_payload');
                if (payloadInput) {
                    payloadInput.value = jsonPayload;
                }
            }
        });
    }
});
