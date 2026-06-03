// math_assessment_platform/static/assessment_tool/js/assessment_setup.js

document.addEventListener("DOMContentLoaded", function() {
    const modal = document.getElementById('create-aqg-modal');
    const triggerBtn = document.getElementById('trigger-create-aqg-modal');
    const closeBtn = document.getElementById('close-aqg-modal');
    const submitBtn = document.getElementById('submit-aqg-creation');
    const nameInput = document.getElementById('new-aqg-name-input');
    const canvasList = document.getElementById('aqg-canvas-list');
    const emptyState = document.getElementById('aqg-empty-placeholder');

    // -------------------------------------------------------------
    // Helper: Normalize double spaces and margins
    // -------------------------------------------------------------
    function normalizeStringSpaces(str) {
        return str.trim().replace(/\s+/g, ' ');
    }

    // -------------------------------------------------------------
    // Creation Modal Toggles
    // -------------------------------------------------------------
    if (triggerBtn) {
        triggerBtn.addEventListener('click', () => {
            nameInput.value = '';
            modal.classList.add('is-visible');
            nameInput.focus();
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', () => modal.classList.remove('is-visible'));
    }

    // Close on backdrop overlay selection
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.classList.remove('is-visible');
        });
    }

    // -------------------------------------------------------------
    // Helper: Attach Rename (Blur/Enter) Listeners
    // -------------------------------------------------------------
    function attachInputListeners(inputElement) {
        if (!inputElement) return;

        const card = inputElement.closest('.aqg-section-card');
        const aqgId = card.getAttribute('data-id');
        const badge = card.querySelector('.save-status-indicator');

        const saveChanges = async () => {
            const cleanValue = normalizeStringSpaces(inputElement.value);
            const originalValue = inputElement.getAttribute('data-previous');

            // If empty, rollback to last saved value
            if (!cleanValue) {
                inputElement.value = originalValue;
                return;
            }

            // If nothing changed, do not fire an AJAX transaction
            if (cleanValue === originalValue) return;

            try {
                const response = await fetch(AQG_CONFIG.renameUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        id: aqgId,
                        name: cleanValue
                    })
                });

                const data = await response.json();
                if (response.ok && data.success) {
                    inputElement.setAttribute('data-previous', cleanValue);
                    inputElement.value = cleanValue;

                    // Flash save completion confirmation text badge
                    if (badge) {
                        badge.style.display = 'inline-block';
                        setTimeout(() => { badge.style.display = 'none'; }, 2000);
                    }
                } else {
                    alert(data.error || "Failed updating section name.");
                    inputElement.value = originalValue;
                }
            } catch (err) {
                console.error("Rename submission error:", err);
                alert("Communication error during rename update processing.");
                inputElement.value = originalValue;
            }
        };

        inputElement.addEventListener('blur', saveChanges);
        inputElement.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                inputElement.blur(); // Triggers blur listener logic naturally
            }
        });
    }

    // -------------------------------------------------------------
    // Helper: Attach Inline Problem Title Rename (Blur/Enter) Listeners
    // -------------------------------------------------------------
    function attachProblemInputListeners(inputElement) {
        if (!inputElement) return;

        const row = inputElement.closest('.problem-item-row');
        const problemId = row.getAttribute('data-problem-id');
        const badge = row.querySelector('.problem-save-status');

        const saveProblemChanges = async () => {
            const cleanValue = normalizeStringSpaces(inputElement.value);
            const originalValue = inputElement.getAttribute('data-previous');

            // If empty, rollback to last saved title configuration
            if (!cleanValue) {
                inputElement.value = originalValue;
                return;
            }

            // Skip transaction completely if no changes were committed
            if (cleanValue === originalValue) return;

            try {
                const response = await fetch('/rename-item/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        id: parseInt(problemId),
                        type: 'problem',           // 🎯 Tells the server model_map to choose Problem
                        new_name: cleanValue       // 🎯 Maps directly to your backend schema expectations
                    })
                });

                const data = await response.json();
                if (response.ok && data.status === 'success') {
                    // Update historical state anchors safely
                    inputElement.setAttribute('data-previous', data.new_name);
                    inputElement.value = data.new_name;

                    // Flash instant visual success validation badge confirmation
                    if (badge) {
                        badge.style.display = 'inline-block';
                        setTimeout(() => { badge.style.display = 'none'; }, 2000);
                    }
                } else {
                    alert(data.error || "Failed updating problem title.");
                    inputElement.value = originalValue;
                }
            } catch (err) {
                console.error("Problem rename error:", err);
                alert("Communication error during problem rename validation.");
                inputElement.value = originalValue;
            }
        };

        inputElement.addEventListener('blur', saveProblemChanges);
        inputElement.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                inputElement.blur();
            }
        });
    }

    // -------------------------------------------------------------
    // Helper: Wire Up Cascade Folder Deletion (Trash Icon)
    // -------------------------------------------------------------
    function attachDeleteListener(cardElement) {
        const deleteBtn = cardElement.querySelector('.btn-delete-aqg');
        if (!deleteBtn) return;

        deleteBtn.addEventListener('click', async function(e) {
            e.preventDefault();
            e.stopPropagation();

            const aqgId = cardElement.getAttribute('data-id');
            const sectionName = cardElement.querySelector('.aqg-title-input')?.value || "this section";

            // 1. Prompt native user warning verification dialog window
            const confirmed = confirm(`Are you sure you want to permanently delete "${sectionName}"?\nThis will recursively erase this section and all problems inside it.`);
            if (!confirmed) return;

            try {
                // 2. Dispatch payload to your unified direct backend deletion layout view
                const response = await fetch('/delete-item/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        id: parseInt(aqgId),
                        type: 'assessment_selection' // 🎯 Reuses your preconfigured mapping keyword string
                    })
                });

                const data = await response.json();
                if (response.ok && data.status === 'success') {
                    // 3. Remove the section element cleanly out of your DOM tree dashboard layout
                    cardElement.remove();
                    
                    // 4. Force reload page to render the native dashboard empty placeholder state card if no rows remain
                    if (canvasList && canvasList.querySelectorAll('.aqg-section-card').length === 0) {
                        window.location.reload();
                    }
                } else {
                    alert(data.error || "An error occurred during the filesystem deletion task.");
                }
            } catch (err) {
                console.error("Deletion transaction dropped:", err);
                alert("Network communication exception encountered when trying to delete the section.");
            }
        });
    }

    // -------------------------------------------------------------
    // Initialization: Bind Existing Elements on Initial Page Render
    // -------------------------------------------------------------
    document.querySelectorAll('.aqg-title-input').forEach(input => {
        attachInputListeners(input);
    });

    document.querySelectorAll('.problem-title-input').forEach(input => {
        attachProblemInputListeners(input); // 🎯 Hydrates items on initial page load
    });

    document.querySelectorAll('.aqg-section-card').forEach(card => {
        attachDeleteListener(card);
    });

    // -------------------------------------------------------------
    // AJAX: Create Section Payload Dispatcher (Server Side UI Fragments)
    // -------------------------------------------------------------
    if (submitBtn) {
        submitBtn.addEventListener('click', async function() {
            const cleanName = normalizeStringSpaces(nameInput.value);
            if (!cleanName) {
                alert("Section title name field constraint error: Value cannot be left empty.");
                return;
            }

            try {
                const response = await fetch(AQG_CONFIG.createUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({ name: cleanName })
                });

                const data = await response.json();
                if (response.ok && data.success) {
                    modal.classList.remove('is-visible');
                    
                    if (emptyState) emptyState.remove();

                    // Inject the clean server-rendered HTML string directly without redundancy!
                    canvasList.insertAdjacentHTML('beforeend', data.html);
                    
                    const newCard = canvasList.lastElementChild;
                    
                    // Hydrate functional hooks immediately on the brand new node element
                    attachInputListeners(newCard.querySelector('.aqg-title-input'));
                    attachDeleteListener(newCard);
                    
                    nameInput.value = '';
                } else {
                    alert(data.error || "Failed creating section group framework.");
                }
            } catch (err) {
                console.error("AJAX deployment runtime failure:", err);
                alert("Network communication error during layout creation operations.");
            }
        });
    }

    // -------------------------------------------------------------
    // SortableJS: Drag-and-Drop Handling Logic
    // -------------------------------------------------------------
    if (canvasList) {
        Sortable.create(canvasList, {
            handle: '.aqg-drag-handle',
            animation: 150,
            ghostClass: 'sortable-ghost',
            onEnd: async function(evt) {
                const movedCard = evt.item;
                const aqgId = movedCard.getAttribute('data-id');
                
                const prevCard = movedCard.previousElementSibling;
                const nextCard = movedCard.nextElementSibling;
                
                const prevId = prevCard ? prevCard.getAttribute('data-id') : null;
                const nextId = nextCard ? nextCard.getAttribute('data-id') : null;

                try {
                    const response = await fetch(AQG_CONFIG.reorderUrl, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({
                            aqg_id: aqgId,
                            prev_id: prevId,
                            next_id: nextId
                        })
                    });

                    const data = await response.json();
                    if (response.ok && data.success) {
                        movedCard.setAttribute('data-order', data.new_order);
                    } else {
                        alert(data.error || "Failed to persist group positioning modification layouts.");
                    }
                } catch (err) {
                    console.error("Sorting channel transaction connection error:", err);
                    alert("A transmission linkage failure occurred while resetting container structure sequences.");
                }
            }
        });
    }

    // -------------------------------------------------------------
    // AJAX: Add Problem Operations Handler (Event Delegation Loop)
    // -------------------------------------------------------------
    if (canvasList) {
        canvasList.addEventListener('click', async function(e) {
            // 1. Locate trigger targets matching the Add Problem element class
            const addBtn = e.target.closest('.btn-add-problem');
            if (!addBtn) return;

            // 2. Traversal up to read the unique ID tracking database attributes on the section card container
            const card = addBtn.closest('.aqg-section-card');
            const aqgId = card.getAttribute('data-id');
            const problemsBody = card.querySelector('.aqg-problems-body');

            // Visually toggle state interactions during processing latency
            addBtn.disabled = true;
            const originalText = addBtn.innerHTML;
            addBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Adding...`;

            try {
                const response = await fetch(window.AQG_CONFIG.addProblemUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({ aqg_id: aqgId })
                });

                const data = await response.json();

                if (response.ok) {
                    // 3. Locate or create the wrapper element list container inside the layout view context
                    let listWrapper = problemsBody.querySelector('.problems-list-wrapper');
                    const emptyPlaceholder = problemsBody.querySelector('.empty-problems-placeholder');
                    
                    // Clear the hardcoded string or empty container node out of the layout viewport block if it exists
                    if (emptyPlaceholder) {
                        emptyPlaceholder.remove();
                    }
                    // Clean fallback for un-refreshed stale UI sessions that still contain the raw fallback string snippet
                    if (problemsBody.innerText.includes("No problems added to this section yet")) {
                        problemsBody.innerHTML = '';
                    }
                    
                    if (!listWrapper) {
                        listWrapper = document.createElement('div');
                        listWrapper.className = 'problems-list-wrapper';
                        listWrapper.style.display = 'flex';
                        listWrapper.style.flexDirection = 'column';
                        listWrapper.style.gap = '8px';
                        problemsBody.appendChild(listWrapper);
                    }

                    // 4. Build an interactive DOM row element replicating problem_card.html properties explicitly
                    const row = document.createElement('div');
                    row.className = 'problem-item-row';
                    row.setAttribute('data-problem-id', data.problem_id);
                    row.setAttribute('data-branch-id', data.branch_id);
                    row.style.background = '#ffffff';
                    row.style.padding = '10px 12px';
                    row.style.border = '1px solid #e2e8f0';
                    row.style.borderRadius = '6px';
                    row.style.display = 'flex';
                    row.style.alignItems = 'center';
                    row.style.justifyContent = 'space-between';
                    row.style.boxShadow = '0 1px 2px rgba(0,0,0,0.02)';

                    // Ensure this string matches your step 1 markup framework precisely!
                    row.innerHTML = `
                        <div style="display: flex; align-items: center; gap: 8px; flex-grow: 1; margin-right: 16px;">
                            <input type="text" 
                                   class="problem-title-input" 
                                   value="${data.allocated_name}" 
                                   data-previous="${data.allocated_name}" 
                                   placeholder="Enter problem title..."
                                   style="font-weight: 500; color: #334155; border: 1px solid transparent; background: transparent; padding: 2px 6px; border-radius: 4px; font-size: 0.9rem; width: 100%; outline: none; transition: all 0.15s ease;">
                            <span class="problem-save-status" style="display: none; color: #10b981; font-size: 0.75rem; font-weight: 600; white-space: nowrap;"><i class="fas fa-check"></i> Saved</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <span class="problem-status-badge" style="font-size: 0.75rem; background: #f1f5f9; padding: 2px 6px; border-radius: 4px; color: #64748b; font-weight: 600; text-transform: uppercase;">draft</span>
                        </div>
                    `;

                    // 🎯 HYDRATE THE NEWLY GENERATED INPUT FIELD RIGHT AWAY!
                    attachProblemInputListeners(row.querySelector('.problem-title-input'));

                    // Inject the new problem node straight into the display list layer framework immediately
                    listWrapper.appendChild(row);
                } else {
                    alert(`Failed to add problem: ${data.error}`);
                }
            } catch (err) {
                console.error(err);
                alert("A critical networking transmission failure occurred.");
            } finally {
                addBtn.disabled = false;
                addBtn.innerHTML = originalText;
            }
        });
    }
});