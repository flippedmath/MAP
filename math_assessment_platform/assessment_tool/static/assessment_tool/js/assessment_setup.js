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

                    // 🎯 Inject the clean server-rendered HTML string directly without redundancy!
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
});