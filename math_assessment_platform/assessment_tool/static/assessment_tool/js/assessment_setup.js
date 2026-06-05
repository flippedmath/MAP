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
                        type: 'problem',           // Tells the server model_map to choose Problem
                        new_name: cleanValue       // Maps directly to your backend schema expectations
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
                        type: 'assessment_selection' // Reuses your preconfigured mapping keyword string
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
        attachProblemInputListeners(input); // Hydrates items on initial page load
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

        // -------------------------------------------------------------
        // SortableJS: Nested Problem & CQD Drag-and-Drop Handling Logic
        // -------------------------------------------------------------
        const problemLists = document.querySelectorAll('.problems-list-wrapper');
        problemLists.forEach(listContainer => {
            Sortable.create(listContainer, {
                animation: 150,
                ghostClass: 'sortable-ghost',
                // You can add a handle attribute here if you choose to include drag handles later, 
                // otherwise dragging anywhere on the problem/cqd card row handles it.
                onEnd: async function(evt) {
                    const movedCard = evt.item;
                    // Grab the underlying tracking branch node identifier
                    const branchId = movedCard.getAttribute('data-branch-id');
                    
                    const prevCard = movedCard.previousElementSibling;
                    const nextCard = movedCard.nextElementSibling;
                    
                    const prevBranchId = prevCard ? prevCard.getAttribute('data-branch-id') : null;
                    const nextBranchId = nextCard ? nextCard.getAttribute('data-branch-id') : null;

                    try {
                        const response = await fetch('/course/api/setup/reorder-nested-item/', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': getCookie('csrftoken')
                            },
                            body: JSON.stringify({
                                branch_id: branchId,
                                prev_branch_id: prevBranchId,
                                next_branch_id: nextBranchId
                            })
                        });

                        const data = await response.json();
                        if (!response.ok || !data.success) {
                            alert(data.error || "Failed to persist nested structural positioning modification layouts.");
                            // Optional: Reload or revert DOM if synchronization fails
                        }
                    } catch (err) {
                        console.error("Nested sorting channel transaction linkage error:", err);
                        alert("A transmission linkage failure occurred while resetting problem item sequences.");
                    }
                }
            });
        });
    }

    // -------------------------------------------------------------
    // AJAX: Add/Delete Problem Operations Handler (Event Delegation Loop)
    // -------------------------------------------------------------
    if (canvasList) {
        canvasList.addEventListener('click', async function(e) {
            
            // --- HANDLER BRANCH A: "+ ADD PROBLEM" INTERACTION ---
            const addBtn = e.target.closest('.btn-add-problem');
            if (addBtn) {
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
                        // Locate or create the wrapper list container
                        let listWrapper = problemsBody.querySelector('.problems-list-wrapper');
                        const emptyPlaceholder = problemsBody.querySelector('.empty-problems-placeholder');
                        
                        // Clear placeholders or historical layout notes safely
                        if (emptyPlaceholder) {
                            emptyPlaceholder.remove();
                        }
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

                        // 🎯 DRY WIN: Inject backend-rendered HTML component fragment directly!
                        listWrapper.insertAdjacentHTML('beforeend', data.html);

                        // Capture the freshly injected node element out of the tree to hydrate rename functions
                        const newRow = listWrapper.lastElementChild;
                        attachProblemInputListeners(newRow.querySelector('.problem-title-input'));

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
                return;
            }

            // --- HANDLER BRANCH B: TRASH ICON DELETION INTERACTION ---
            const deleteProblemBtn = e.target.closest('.btn-delete-problem');
            if (deleteProblemBtn) {
                e.preventDefault();
                e.stopPropagation();

                const row = deleteProblemBtn.closest('.problem-item-row');
                const problemId = row.getAttribute('data-problem-id');
                const problemTitle = row.querySelector('.problem-title-input')?.value || "this problem";
                const problemsBody = row.closest('.aqg-problems-body');

                const confirmed = confirm(`Are you sure you want to permanently delete "${problemTitle}"?`);
                if (!confirmed) return;

                // Lock button layout during pipeline processing latency
                deleteProblemBtn.disabled = true;
                const originalIcon = deleteProblemBtn.innerHTML;
                deleteProblemBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i>`;

                try {
                    const response = await fetch('/delete-item/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({
                            id: parseInt(problemId),
                            type: 'problem' // Targets the Problem mapping in your backend router
                        })
                    });

                    const data = await response.json();
                    if (response.ok && data.status === 'success') {
                        const listWrapper = row.parentElement;
                        row.remove();

                        // If that was the final problem row component, restore empty UI placeholder
                        if (listWrapper && listWrapper.querySelectorAll('.problem-item-row').length === 0) {
                            listWrapper.remove();
                            
                            problemsBody.innerHTML = `
                                <div class="empty-problems-placeholder" style="text-align: center; color: #94a3b8;">
                                    No problems added to this section yet. Click "+ Add Problem" to start building.
                                </div>
                            `;
                        }
                    } else {
                        alert(data.error || "Failed to remove the problem item.");
                        deleteProblemBtn.disabled = false;
                        deleteProblemBtn.innerHTML = originalIcon;
                    }
                } catch (err) {
                    console.error("Deletion connection error:", err);
                    alert("A critical networking transmission failure occurred.");
                    deleteProblemBtn.disabled = false;
                    deleteProblemBtn.innerHTML = originalIcon;
                }
                return;
            }

            // --- HANDLER BRANCH C: "ADD NEW PROBLEM GROUP" INTERACTION ---
            const addCqdBtn = e.target.closest('.btn-add-cqd');
            if (addCqdBtn) {
                const card = addCqdBtn.closest('.aqg-section-card');
                const aqgId = card.getAttribute('data-id');
                const problemsBody = card.querySelector('.aqg-problems-body');
                const dropdownMenu = addCqdBtn.closest('.problems-menu-overlay');

                // Dismiss selection menu layer instantly
                if (dropdownMenu) dropdownMenu.style.display = 'none';

                try {
                    // Update this endpoint string to reference your newly established tracking route configuration setup
                    const response = await fetch('/add-cqd-ajax/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({ aqg_id: aqgId })
                    });

                    const data = await response.json();

                    if (response.ok) {
                        let listWrapper = problemsBody.querySelector('.problems-list-wrapper');
                        const emptyPlaceholder = problemsBody.querySelector('.empty-problems-placeholder');
                        
                        // Clear placeholders or empty dashboard structural cards out of the canvas viewport block layout
                        if (emptyPlaceholder) emptyPlaceholder.remove();
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

                        // Inject pre-rendered server layout snippet structure fluidly
                        listWrapper.insertAdjacentHTML('beforeend', data.html);

                    } else {
                        alert(`Failed to add problem group collection: ${data.error}`);
                    }
                } catch (err) {
                    console.error(err);
                    alert("A critical networking transmission failure occurred while trying to append the item distribution row.");
                }
                return;
            }

            const deleteBtn = e.target.closest('.btn-delete-item');
            if (deleteBtn) {
                e.preventDefault();
                
                const itemRow = deleteBtn.closest('.cqd-item-row, .problem-item-row');
                const itemId = itemRow.getAttribute('data-id');
                const itemType = deleteBtn.getAttribute('data-type'); // Evaluates to 'cqd'
                
                if (confirm("Are you sure you want to delete this problem group?")) {
                    try {
                        const response = await fetch(`/delete-item/${itemType}/${itemId}/`, {
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': getCookie('csrftoken'),
                                'Content-Type': 'application/json'
                            }
                        });
                        
                        const data = await response.json();
                        if (response.ok) {
                            // Smoothly remove the card row layout from the viewport canvas
                            itemRow.remove();
                        } else {
                            alert(`Error: ${data.error}`);
                        }
                    } catch (err) {
                        console.error(err);
                        alert("A network transmission error occurred during deletion.");
                    }
                }
                return;
            }

            // -------------------------------------------------------------
            // CQD Count Indicator: Click to Modify Suggested Count
            // -------------------------------------------------------------            
            const countBadge = e.target.closest('.cqd-clickable-count');
            if (!countBadge) return;

            e.preventDefault();
            
            const cqdId = countBadge.getAttribute('data-cqd-id');
            const displaySpan = countBadge.querySelector('.count-number-display');
            const currentCount = displaySpan.innerText.trim();

            // 1. Prompt the user for input
            let userInput = prompt("Enter the number of problems to randomly choose from this group:", currentCount);
            
            // If the user hits cancel, exit early
            if (userInput === null) return;

            // 2. Enforce rules: Parse and validate positive integers
            let parsedCount = parseInt(userInput, 10);
            if (isNaN(parsedCount) || parsedCount <= 0 || String(parsedCount) !== userInput.trim()) {
                parsedCount = 1; // Default fallback for invalid entries
            }

            try {
                const response = await fetch('/update-cqd-count-ajax/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        cqd_id: cqdId,
                        suggested_count: parsedCount
                    })
                });

                const data = await response.json();

                if (response.ok) {
                    // 3. Fluidly update the frontend visual text container row
                    displaySpan.innerText = data.new_count;
                } else {
                    alert(`Failed to save configuration: ${data.error}`);
                }
            } catch (err) {
                console.error(err);
                alert("A transmission exception blocked saving the updated question selection parameters.");
            }
        });
    }

    // -------------------------------------------------------------
    // Menu Overlay: Click To Show Selection Overlay Menu (Flicker-Free)
    // -------------------------------------------------------------
    if (canvasList) {
        canvasList.addEventListener('click', function(e) {
            const triggerBtn = e.target.closest('.btn-trigger-problems-menu');
            if (!triggerBtn) return;
            
            e.preventDefault();
            e.stopPropagation();
            
            const container = triggerBtn.closest('.add-problems-dropdown-container');
            const menuOverlay = container.querySelector('.problems-menu-overlay');
            
            // Toggle menu view layout display state safely
            if (menuOverlay.style.display === 'none' || menuOverlay.style.display === '') {
                menuOverlay.style.display = 'flex';
                
                // If a listener isn't already active on this container, bind it
                if (!container.dataset.hasMouseListener) {
                    container.dataset.hasMouseListener = 'true';
                    
                    // Handle Mouse Leaving the Dropdown Area
                    const handleMouseLeave = function() {
                        // Start a tiny timer before hiding (gives the user time to cross gaps)
                        container.dataset.leaveTimeout = setTimeout(() => {
                            menuOverlay.style.display = 'none';
                            cleanUpListeners();
                        }, 150); // 150ms buffer window
                    };
                    
                    // Handle Mouse Re-entering the Dropdown Area
                    const handleMouseEnter = function() {
                        // If they re-enter before the timer runs out, cancel the closing animation!
                        if (container.dataset.leaveTimeout) {
                            clearTimeout(parseInt(container.dataset.leaveTimeout));
                            container.removeAttribute('data-leave-timeout');
                        }
                    };
                    
                    // Helper to clean up memory footprints cleanly
                    const cleanUpListeners = function() {
                        container.removeAttribute('data-has-mouse-listener');
                        if (container.dataset.leaveTimeout) {
                            clearTimeout(parseInt(container.dataset.leaveTimeout));
                            container.removeAttribute('data-leave-timeout');
                        }
                        container.removeEventListener('mouseleave', handleMouseLeave);
                        container.removeEventListener('mouseenter', handleMouseEnter);
                    };

                    // Bind tracking handlers to the parent dropdown box unit
                    container.addEventListener('mouseleave', handleMouseLeave);
                    container.addEventListener('mouseenter', handleMouseEnter);
                }
            } else {
                menuOverlay.style.display = 'none';
            }
        });

        // Dismiss menu when an option is selected
        canvasList.addEventListener('click', function(e) {
            const menuOption = e.target.closest('.menu-option-item');
            if (menuOption && !menuOption.disabled) {
                const menuOverlay = menuOption.closest('.problems-menu-overlay');
                if (menuOverlay) {
                    menuOverlay.style.display = 'none';
                }
            }
        });
    }
});