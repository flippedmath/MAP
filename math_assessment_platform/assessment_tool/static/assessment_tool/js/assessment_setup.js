// math_assessment_platform/static/assessment_tool/js/assessment_setup.js

function initAssessmentSetupPage() {
    const modal = document.getElementById('create-aqg-modal');
    const aqgMenuTrigger = document.getElementById('trigger-aqg-menu');
    const aqgMenuOverlay = document.getElementById('aqg-menu-overlay');
    const aqgMenuContainer = document.querySelector('.add-aqg-dropdown-container');
    const triggerBtn = document.getElementById('trigger-create-aqg-modal');
    const copyAqgTriggerBtn = document.getElementById('trigger-copy-aqg-from-explorer');
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

    function ensureProblemsListWrapper(problemsBody) {
        let listWrapper = problemsBody.querySelector('.problems-list-wrapper');
        const emptyPlaceholder = problemsBody.querySelector('.empty-problems-placeholder');
        if (emptyPlaceholder) emptyPlaceholder.remove();
        if (problemsBody.innerText.includes('No problems added to this section yet')) {
            problemsBody.innerHTML = '';
        }
        if (!listWrapper) {
            listWrapper = document.createElement('div');
            listWrapper.className = 'problems-list-wrapper';
            listWrapper.style.display = 'flex';
            listWrapper.style.flexDirection = 'column';
            listWrapper.style.gap = '8px';
            problemsBody.appendChild(listWrapper);
            initializeSortableOnNestedList(listWrapper);
        }
        return listWrapper;
    }

    function hydrateAqgCard(card) {
        if (!card) return;
        attachInputListeners(card.querySelector('.aqg-title-input'));
        attachDeleteListener(card);
        card.querySelectorAll('.cqd-name-input').forEach(attachCqdNameListeners);
        card.querySelectorAll('.problem-title-input').forEach(attachProblemInputListeners);
        const nestedList = card.querySelector('.problems-list-wrapper');
        if (nestedList) initializeSortableOnNestedList(nestedList);
    }

    async function openExplorerCopyPicker({ title, hint, selectableTypes, onCopy }) {
        async function notify(titleText, message) {
            if (typeof mapAlert === 'function') {
                await mapAlert({ title: titleText, message });
            } else {
                alert(message);
            }
        }
        if (typeof openBranchPicker !== 'function') {
            await notify(
                'Unavailable',
                'Branch picker failed to load. Hard-refresh the page (Cmd-Shift-R) and try again.'
            );
            return;
        }
        const cfg = window.AQG_CONFIG || {};
        if (!cfg.explorerRootFolderId) {
            await notify('Unavailable', 'Explorer root folder was not found for your account.');
            return;
        }
        await openBranchPicker({
            title,
            hint,
            rootFolderId: cfg.explorerRootFolderId,
            rootFolderName: cfg.explorerRootFolderName || 'Home',
            contentsUrlTemplate: cfg.branchPickerContentsUrlTemplate || '/api/branch-picker/{id}/',
            selectableTypes,
            commitLabel: 'Copy',
            onSelect: onCopy,
        });
    }

    // -------------------------------------------------------------
    // Creation Modal Toggles + header "Add Question Group" dropdown
    // -------------------------------------------------------------
    function closeAqgHeaderMenu() {
        if (aqgMenuOverlay) aqgMenuOverlay.style.display = 'none';
    }

    if (aqgMenuTrigger && aqgMenuOverlay && aqgMenuContainer) {
        aqgMenuTrigger.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const open = aqgMenuOverlay.style.display === 'flex';
            aqgMenuOverlay.style.display = open ? 'none' : 'flex';
        });
        aqgMenuContainer.addEventListener('mouseleave', () => {
            window.setTimeout(closeAqgHeaderMenu, 150);
        });
        document.addEventListener('click', (e) => {
            if (!aqgMenuContainer.contains(e.target)) closeAqgHeaderMenu();
        });
    }

    if (triggerBtn) {
        triggerBtn.addEventListener('click', () => {
            closeAqgHeaderMenu();
            nameInput.value = '';
            modal.classList.add('is-visible');
            nameInput.focus();
        });
    }

    if (copyAqgTriggerBtn) {
        copyAqgTriggerBtn.addEventListener('click', async () => {
            closeAqgHeaderMenu();
            try {
                await openExplorerCopyPicker({
                    title: 'Copy question group section',
                    hint: 'Browse your explorer and select a question group section you can view. A deep copy (including problems and problem sets) is added to this assessment.',
                    selectableTypes: ['aqg'],
                    onCopy: async (item) => {
                        const response = await fetch(window.AQG_CONFIG.copyAqgUrl, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': getCookie('csrftoken'),
                            },
                            body: JSON.stringify({ source_branch_id: item.id }),
                        });
                        const data = await response.json().catch(() => ({}));
                        if (!response.ok || !data.success) {
                            throw new Error(data.error || 'Copy failed.');
                        }
                        const emptyEl = document.getElementById('aqg-empty-placeholder');
                        if (emptyEl) emptyEl.remove();
                        canvasList.insertAdjacentHTML('beforeend', data.html);
                        hydrateAqgCard(canvasList.lastElementChild);
                    },
                });
            } catch (err) {
                console.error('Copy question group failed:', err);
                if (typeof mapAlert === 'function') {
                    await mapAlert({
                        title: 'Copy failed',
                        message: err.message || 'Copy failed.',
                    });
                } else {
                    alert(err.message || 'Copy failed.');
                }
            }
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

    function attachCqdNameListeners(inputElement) {
        if (!inputElement || inputElement.dataset.cqdNameBound === '1') return;
        inputElement.dataset.cqdNameBound = '1';

        const row = inputElement.closest('.cqd-item-row');
        const cqdId = row?.getAttribute('data-cqd-id') || row?.getAttribute('data-id');
        if (!cqdId) return;

        inputElement.addEventListener('click', (e) => e.stopPropagation());
        inputElement.addEventListener('mousedown', (e) => e.stopPropagation());

        const saveCqdName = async () => {
            const cleanValue = normalizeStringSpaces(inputElement.value);
            const originalValue = inputElement.getAttribute('data-previous') || '';

            if (!cleanValue) {
                inputElement.value = originalValue;
                return;
            }
            if (cleanValue === originalValue) return;

            const renameUrl = window.AQG_CONFIG?.renameCqdUrl || '/update-cqd-name-ajax/';
            try {
                const response = await fetch(renameUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        cqd_id: parseInt(cqdId, 10),
                        name: cleanValue
                    })
                });
                const data = await response.json();
                if (response.ok && data.success) {
                    const saved = data.name || cleanValue;
                    inputElement.setAttribute('data-previous', saved);
                    inputElement.value = saved;
                    refreshCqdCardLabel(cqdId, saved, data.count);
                } else {
                    alert(data.error || 'Failed updating problem set name.');
                    inputElement.value = originalValue;
                }
            } catch (err) {
                console.error('Problem set rename error:', err);
                alert('Communication error while renaming the problem set.');
                inputElement.value = originalValue;
            }
        };

        inputElement.addEventListener('blur', saveCqdName);
        inputElement.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                inputElement.blur();
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
            const confirmed = (await mapConfirm({ title: 'Confirm', message: `Are you sure you want to permanently delete "${sectionName}"?\nThis will recursively erase this section and all problems inside it.`, danger: true, confirmLabel: 'Delete' }));
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
    document.querySelectorAll('.cqd-name-input').forEach(input => {
        attachCqdNameListeners(input);
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
    // -------------------------------------------------------------
    // SortableJS: Isolated Initialization Helper for Problem Lists
    // -------------------------------------------------------------
    function initializeSortableOnNestedList(listContainer) {
        if (!listContainer || listContainer.dataset.sortableInitialized) return;

        Sortable.create(listContainer, {
            animation: 150,
            draggable: '.problem-item-row',
            filter: 'input, button, a, .cqd-clickable-count',
            preventOnFilter: false,
            ghostClass: 'sortable-ghost',
            onEnd: async function(evt) {
                if (evt.oldIndex === evt.newIndex) return;

                const movedCard = evt.item;
                const branchId = movedCard.getAttribute('data-branch-id');
                if (!branchId) {
                    console.error("Nested reorder aborted: moved item is missing data-branch-id.");
                    return;
                }

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
                        console.error("Nested reorder failed:", data.error || response.status);
                        alert(data.error || "Failed to save problem order.");
                    }
                } catch (err) {
                    console.error("Nested sorting channel transaction linkage error:", err);
                    alert("A transmission linkage failure occurred while resetting problem item sequences.");
                }
            }
        });

        // Mark it as initialized so we never double-bind Sortable instances to it
        listContainer.dataset.sortableInitialized = "true";
    }

    // -------------------------------------------------------------
    // SortableJS: Initial Page Load Instantiation
    // -------------------------------------------------------------
    if (canvasList) {
        // 1. Make the Top-Level Sections rearrangeable and persist order
        Sortable.create(canvasList, {
            animation: 150,
            handle: '.aqg-drag-handle',
            draggable: '.aqg-section-card',
            ghostClass: 'sortable-ghost',
            onEnd: async function(evt) {
                if (evt.oldIndex === evt.newIndex) return;

                const movedCard = evt.item;
                const aqgId = movedCard.getAttribute('data-id');
                if (!aqgId || !window.AQG_CONFIG?.reorderUrl) {
                    console.error("Section reorder aborted: missing aqg id or reorderUrl.");
                    return;
                }

                const prevCard = movedCard.previousElementSibling;
                const nextCard = movedCard.nextElementSibling;
                const prevId = prevCard?.classList.contains('aqg-section-card')
                    ? prevCard.getAttribute('data-id')
                    : null;
                const nextId = nextCard?.classList.contains('aqg-section-card')
                    ? nextCard.getAttribute('data-id')
                    : null;

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
                        alert(data.error || "Failed to save question group section order.");
                    }
                } catch (err) {
                    console.error("Section reorder save failed:", err);
                    alert("Network error while saving question group section order.");
                }
            }
        });

        // 2. Query and initialize all initial nested lists present on page load
        const initialWrappers = document.querySelectorAll('.problems-list-wrapper');
        initialWrappers.forEach(listContainer => {
            initializeSortableOnNestedList(listContainer);
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

                            initializeSortableOnNestedList(listWrapper);
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
                    console.error("Assessment setup request failed:", err);
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

                const confirmed = (await mapConfirm({ title: 'Confirm', message: `Are you sure you want to permanently delete "${problemTitle}"?`, danger: true, confirmLabel: 'Delete' }));
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
                        const listWrapper = ensureProblemsListWrapper(problemsBody);

                        // Inject pre-rendered server layout snippet structure fluidly
                        listWrapper.insertAdjacentHTML('beforeend', data.html);
                        const newCqdRow = listWrapper.lastElementChild;
                        attachCqdNameListeners(newCqdRow?.querySelector('.cqd-name-input'));

                    } else {
                        alert(`Failed to add problem group collection: ${data.error}`);
                    }
                } catch (err) {
                    console.error("Assessment setup request failed:", err);
                    alert("A critical networking transmission failure occurred while trying to append the item distribution row.");
                }
                return;
            }

            // --- HANDLER: Copy problem / problem set from explorer into this AQG ---
            const copyFromExplorerBtn = e.target.closest('.btn-copy-from-explorer');
            if (copyFromExplorerBtn) {
                const card = copyFromExplorerBtn.closest('.aqg-section-card');
                const aqgId = card.getAttribute('data-id');
                const problemsBody = card.querySelector('.aqg-problems-body');
                const dropdownMenu = copyFromExplorerBtn.closest('.problems-menu-overlay');
                if (dropdownMenu) dropdownMenu.style.display = 'none';

                try {
                    await openExplorerCopyPicker({
                        title: 'Copy into this section',
                        hint: 'Browse your explorer and select a problem or problem set you can view. A deep copy is added to this section.',
                        selectableTypes: ['problem', 'cqd'],
                        onCopy: async (item) => {
                            const response = await fetch(window.AQG_CONFIG.copyIntoAqgUrl, {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'X-CSRFToken': getCookie('csrftoken'),
                                },
                                body: JSON.stringify({
                                    aqg_id: parseInt(aqgId, 10),
                                    source_branch_id: item.id,
                                }),
                            });
                            const data = await response.json().catch(() => ({}));
                            if (!response.ok || !data.success) {
                                throw new Error(data.error || 'Copy failed.');
                            }
                            const listWrapper = ensureProblemsListWrapper(problemsBody);
                            listWrapper.insertAdjacentHTML('beforeend', data.html);
                            const newRow = listWrapper.lastElementChild;
                            if (data.copied_type === 'cqd') {
                                attachCqdNameListeners(newRow?.querySelector('.cqd-name-input'));
                            } else {
                                attachProblemInputListeners(newRow?.querySelector('.problem-title-input'));
                            }
                        },
                    });
                } catch (err) {
                    console.error('Copy from explorer failed:', err);
                    await mapAlert({
                        title: 'Copy failed',
                        message: err.message || 'Copy failed.',
                    });
                }
                return;
            }

            const deleteBtn = e.target.closest('.btn-delete-item');
            if (deleteBtn) {
                e.preventDefault();
                e.stopPropagation();

                const itemRow = deleteBtn.closest('.cqd-item-row, .problem-item-row');
                if (!itemRow) return;

                const itemType = deleteBtn.getAttribute('data-type');
                const itemId = itemRow.getAttribute('data-problem-id') || itemRow.getAttribute('data-id');

                if (itemType === 'problem') {
                    const problemTitle = itemRow.querySelector('.problem-title-input')?.value || "this problem";
                    if (!(await mapConfirm({ title: 'Confirm', message: `Are you sure you want to permanently delete "${problemTitle}"?`, danger: true, confirmLabel: 'Delete' }))) return;

                    deleteBtn.disabled = true;
                    const originalIcon = deleteBtn.innerHTML;
                    deleteBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i>`;

                    try {
                        const response = await fetch('/delete-item/', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': getCookie('csrftoken')
                            },
                            body: JSON.stringify({
                                id: parseInt(itemId, 10),
                                type: 'problem'
                            })
                        });
                        const data = await response.json();
                        if (response.ok && data.status === 'success') {
                            const listWrapper = itemRow.parentElement;
                            const sourceCard = itemRow.closest('.aqg-section-card');
                            const inOverlay = !!itemRow.closest('#cqd-overlay-problems-list');
                            const openCqdId = cqdProblemsOverlay?.getAttribute('data-cqd-id');
                            itemRow.remove();

                            if (inOverlay) {
                                updateOverlayEmptyState();
                                if (openCqdId) {
                                    refreshCqdCardLabel(openCqdId);
                                }
                            } else {
                                restoreEmptyPlaceholderIfNeeded(sourceCard);
                            }
                        } else {
                            alert(data.error || "Failed to remove the problem item.");
                            deleteBtn.disabled = false;
                            deleteBtn.innerHTML = originalIcon;
                        }
                    } catch (err) {
                        console.error("Deletion connection error:", err);
                        alert("A critical networking transmission failure occurred.");
                        deleteBtn.disabled = false;
                        deleteBtn.innerHTML = originalIcon;
                    }
                    return;
                }

                if ((await mapConfirm({ title: 'Confirm', message: "Are you sure you want to delete this problem group?", danger: true, confirmLabel: 'Delete' }))) {
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
                            const sourceCard = itemRow.closest('.aqg-section-card');
                            itemRow.remove();
                            restoreEmptyPlaceholderIfNeeded(sourceCard);
                            if (cqdProblemsOverlay?.getAttribute('data-cqd-id') === String(itemId)) {
                                closeCqdOverlay();
                            }
                        } else {
                            alert(`Error: ${data.error}`);
                        }
                    } catch (err) {
                        console.error("Assessment setup request failed:", err);
                        alert("A network transmission error occurred during deletion.");
                    }
                }
                return;
            }

            // Open problem-set overlay
            const openCqdBtn = e.target.closest('.btn-open-cqd-overlay');
            if (openCqdBtn) {
                e.preventDefault();
                const cqdRow = openCqdBtn.closest('.cqd-item-row');
                const cqdId = cqdRow?.getAttribute('data-cqd-id') || cqdRow?.getAttribute('data-id');
                if (cqdId) {
                    openCqdOverlay(cqdId);
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
            let userInput = (await mapPrompt({ title: 'Selection count', message: "Enter how many problems to randomly choose from this set (0 or more):", defaultValue: currentCount, okLabel: 'Save' }));
            
            // If the user hits cancel, exit early
            if (userInput === null) return;

            // 2. Enforce rules: non-negative integers (0 allowed = sample none from set)
            let parsedCount = parseInt(userInput, 10);
            if (isNaN(parsedCount) || parsedCount < 0 || String(parsedCount) !== userInput.trim()) {
                parsedCount = 0;
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
                console.error("Assessment setup request failed:", err);
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

    // -------------------------------------------------------------
    // Right-click context menu + problem-set overlay
    // -------------------------------------------------------------
    const problemContextMenu = document.getElementById('problem-context-menu');
    const moveSectionSubmenu = document.getElementById('problem-move-section-submenu');
    const moveSectionToggle = problemContextMenu
        ? problemContextMenu.querySelector('[data-action="move-to-section-toggle"]')
        : null;
    const addToSetSubmenu = document.getElementById('problem-add-to-set-submenu');
    const addToSetToggle = problemContextMenu
        ? problemContextMenu.querySelector('[data-action="add-to-set-toggle"]')
        : null;
    const addToSetMenuWrap = document.getElementById('add-to-set-menu-wrap');
    const removeFromSetBtn = document.getElementById('menu-remove-from-set');
    const cqdProblemsOverlay = document.getElementById('cqd-problems-overlay');
    const cqdOverlayList = document.getElementById('cqd-overlay-problems-list');
    const cqdOverlayTitle = document.getElementById('cqd-overlay-title');
    const closeCqdOverlayBtn = document.getElementById('close-cqd-overlay');
    let contextMenuTargetRow = null;

    function hideSubmenu(submenu, toggle) {
        if (!submenu || !toggle) return;
        submenu.style.display = 'none';
        submenu.hidden = true;
        submenu.classList.remove('is-flipped-left');
        toggle.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
    }

    function hideMoveSectionSubmenu() {
        hideSubmenu(moveSectionSubmenu, moveSectionToggle);
    }

    function hideAddToSetSubmenu() {
        hideSubmenu(addToSetSubmenu, addToSetToggle);
    }

    function hideProblemContextMenu() {
        hideMoveSectionSubmenu();
        hideAddToSetSubmenu();
        if (problemContextMenu) {
            problemContextMenu.style.display = 'none';
        }
        if (contextMenuTargetRow) {
            contextMenuTargetRow.classList.remove('context-menu-active');
            contextMenuTargetRow = null;
        }
    }

    function positionProblemContextMenu(clientX, clientY) {
        if (!problemContextMenu) return;

        problemContextMenu.style.display = 'block';
        problemContextMenu.style.left = '0px';
        problemContextMenu.style.top = '0px';

        const menuRect = problemContextMenu.getBoundingClientRect();
        const pad = 8;
        let left = clientX;
        let top = clientY;

        if (left + menuRect.width > window.innerWidth - pad) {
            left = Math.max(pad, window.innerWidth - menuRect.width - pad);
        }
        if (top + menuRect.height > window.innerHeight - pad) {
            top = Math.max(pad, window.innerHeight - menuRect.height - pad);
        }

        problemContextMenu.style.left = `${left}px`;
        problemContextMenu.style.top = `${top}px`;
    }

    function showFlyoutSubmenu(submenu, toggle) {
        if (!submenu || !toggle || toggle.disabled) return;
        submenu.hidden = false;
        submenu.style.display = 'block';
        submenu.classList.remove('is-flipped-left');
        toggle.classList.add('is-open');
        toggle.setAttribute('aria-expanded', 'true');

        const submenuRect = submenu.getBoundingClientRect();
        if (submenuRect.right > window.innerWidth - 8) {
            submenu.classList.add('is-flipped-left');
        }
    }

    function collectOtherSections(currentAqgId, includeCurrent) {
        const sections = [];
        document.querySelectorAll('.aqg-section-card').forEach((card) => {
            const aqgId = card.getAttribute('data-id');
            if (!aqgId) return;
            if (!includeCurrent && String(aqgId) === String(currentAqgId)) return;
            const titleInput = card.querySelector('.aqg-title-input');
            const name = (titleInput?.value || titleInput?.getAttribute('data-previous') || `Section ${aqgId}`).trim();
            sections.push({ id: aqgId, name });
        });
        return sections;
    }

    function resolveSectionCardForRow(row) {
        return row.closest('.aqg-section-card')
            || (cqdProblemsOverlay?.classList.contains('is-visible')
                ? canvasList?.querySelector(`.aqg-section-card[data-id="${cqdProblemsOverlay.getAttribute('data-aqg-id')}"]`)
                : null);
    }

    function collectProblemSetsInSection(sectionCard, excludeCqdId) {
        const sets = [];
        if (!sectionCard) return sets;
        sectionCard.querySelectorAll('.cqd-item-row').forEach((row) => {
            const cqdId = row.getAttribute('data-cqd-id') || row.getAttribute('data-id');
            if (!cqdId || String(cqdId) === String(excludeCqdId)) return;
            const nameInput = row.querySelector('.cqd-name-input');
            const name = (
                nameInput?.value
                || nameInput?.getAttribute('data-previous')
                || row.querySelector('.cqd-display-identity')?.textContent
                || `Problem Set ${cqdId}`
            ).trim();
            sets.push({ id: cqdId, name });
        });
        return sets;
    }

    function populateMoveSectionSubmenu(currentAqgId, includeCurrentSection) {
        if (!moveSectionSubmenu || !moveSectionToggle) return;

        const sections = collectOtherSections(currentAqgId, !!includeCurrentSection);
        moveSectionSubmenu.innerHTML = '';

        if (sections.length === 0) {
            moveSectionToggle.disabled = true;
            moveSectionToggle.classList.add('is-disabled');
            moveSectionSubmenu.innerHTML = '<div class="problem-context-submenu-empty">No other sections</div>';
            return;
        }

        moveSectionToggle.disabled = false;
        moveSectionToggle.classList.remove('is-disabled');

        sections.forEach((section) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'problem-context-menu-item';
            btn.setAttribute('data-action', 'move-to-section');
            btn.setAttribute('data-aqg-id', section.id);
            btn.setAttribute('role', 'menuitem');
            btn.title = section.name;
            btn.textContent = section.name;
            moveSectionSubmenu.appendChild(btn);
        });
    }

    function populateAddToSetSubmenu(sectionCard, excludeCqdId) {
        if (!addToSetSubmenu || !addToSetToggle) return;

        const sets = collectProblemSetsInSection(sectionCard, excludeCqdId);
        addToSetSubmenu.innerHTML = '';

        if (sets.length === 0) {
            addToSetToggle.disabled = true;
            addToSetToggle.classList.add('is-disabled');
            addToSetSubmenu.innerHTML = '<div class="problem-context-submenu-empty">No problem sets in this section</div>';
            return;
        }

        addToSetToggle.disabled = false;
        addToSetToggle.classList.remove('is-disabled');

        sets.forEach((set) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'problem-context-menu-item';
            btn.setAttribute('data-action', 'add-to-set');
            btn.setAttribute('data-cqd-id', set.id);
            btn.setAttribute('role', 'menuitem');
            btn.title = set.name;
            btn.textContent = set.name;
            addToSetSubmenu.appendChild(btn);
        });
    }

    function ensureTargetSectionList(targetCard) {
        const problemsBody = targetCard.querySelector('.aqg-problems-body');
        if (!problemsBody) return null;

        let listWrapper = problemsBody.querySelector('.problems-list-wrapper');
        const emptyPlaceholder = problemsBody.querySelector('.empty-problems-placeholder');
        if (emptyPlaceholder) emptyPlaceholder.remove();

        if (!listWrapper) {
            problemsBody.innerHTML = '';
            listWrapper = document.createElement('div');
            listWrapper.className = 'problems-list-wrapper';
            listWrapper.style.display = 'flex';
            listWrapper.style.flexDirection = 'column';
            listWrapper.style.gap = '8px';
            problemsBody.appendChild(listWrapper);
            initializeSortableOnNestedList(listWrapper);
        }
        return listWrapper;
    }

    function restoreEmptyPlaceholderIfNeeded(sourceCard) {
        if (!sourceCard) return;
        const problemsBody = sourceCard.querySelector('.aqg-problems-body');
        if (!problemsBody) return;

        const listWrapper = problemsBody.querySelector('.problems-list-wrapper');
        if (listWrapper && listWrapper.querySelectorAll('.problem-item-row, .cqd-item-row').length === 0) {
            listWrapper.remove();
            problemsBody.innerHTML = `
                <div class="empty-problems-placeholder" style="text-align: center; color: #94a3b8;">
                    No problems added to this section yet. Click "+ Add Problems" to start building.
                </div>
            `;
        }
    }

    function setCqdPoolCountDisplay(card, poolCount) {
        if (!card || poolCount == null || Number.isNaN(Number(poolCount))) return;
        const count = Math.max(0, parseInt(poolCount, 10) || 0);
        const numberEl = card.querySelector('.cqd-pool-count-number');
        const labelEl = card.querySelector('.cqd-pool-count-label');
        if (numberEl) numberEl.textContent = String(count);
        if (labelEl) labelEl.textContent = count === 1 ? 'problem' : 'problems';
    }

    function refreshCqdCardLabel(cqdId, displayName, poolCount) {
        const card = canvasList?.querySelector(`.cqd-item-row[data-cqd-id="${cqdId}"], .cqd-item-row[data-id="${cqdId}"]`);
        if (!card) return;

        const nameInput = card.querySelector('.cqd-name-input');
        const legacyLabel = card.querySelector('.cqd-display-identity');
        if (displayName) {
            if (nameInput) {
                nameInput.value = displayName;
                nameInput.setAttribute('data-previous', displayName);
            } else if (legacyLabel) {
                legacyLabel.textContent = displayName;
            }
        }

        let resolvedCount = poolCount;
        if (resolvedCount == null
            && String(cqdProblemsOverlay?.getAttribute('data-cqd-id')) === String(cqdId)
            && cqdOverlayList) {
            resolvedCount = cqdOverlayList.querySelectorAll('.problem-item-row[data-problem-id]').length;
        }
        setCqdPoolCountDisplay(card, resolvedCount);

        if (cqdOverlayTitle && String(cqdProblemsOverlay?.getAttribute('data-cqd-id')) === String(cqdId)) {
            const title = displayName
                || nameInput?.value
                || nameInput?.getAttribute('data-previous')
                || legacyLabel?.textContent
                || 'Problem Set';
            cqdOverlayTitle.textContent = title;
        }
    }

    function updateOverlayEmptyState() {
        if (!cqdOverlayList) return;
        const hasProblems = cqdOverlayList.querySelectorAll('.problem-item-row[data-problem-id]').length > 0;
        let empty = cqdOverlayList.querySelector('.cqd-overlay-empty');
        if (hasProblems) {
            if (empty) empty.remove();
            return;
        }
        if (!empty) {
            cqdOverlayList.innerHTML = `
                <div class="cqd-overlay-empty" style="text-align: center; color: #94a3b8; padding: 24px 12px;">
                    No problems in this problem set yet.
                </div>
            `;
        }
    }

    function closeCqdOverlay() {
        if (!cqdProblemsOverlay) return;
        cqdProblemsOverlay.classList.remove('is-visible');
        cqdProblemsOverlay.setAttribute('aria-hidden', 'true');
        cqdProblemsOverlay.removeAttribute('data-cqd-id');
        cqdProblemsOverlay.removeAttribute('data-aqg-id');
        hideProblemContextMenu();
    }

    async function openCqdOverlay(cqdId) {
        if (!cqdProblemsOverlay || !cqdOverlayList || !window.AQG_CONFIG?.problemSetProblemsUrlTemplate) {
            alert("Problem set overlay is not available.");
            return;
        }

        const url = window.AQG_CONFIG.problemSetProblemsUrlTemplate.replace('{cqd_id}', String(cqdId));
        cqdOverlayList.innerHTML = `
            <div style="text-align: center; color: #94a3b8; padding: 24px 12px;">
                <i class="fas fa-spinner fa-spin"></i> Loading problems...
            </div>
        `;
        cqdProblemsOverlay.classList.add('is-visible');
        cqdProblemsOverlay.setAttribute('aria-hidden', 'false');
        cqdProblemsOverlay.setAttribute('data-cqd-id', String(cqdId));

        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: { 'X-CSRFToken': getCookie('csrftoken') }
            });
            const data = await response.json();
            if (!response.ok || data.status !== 'success') {
                alert(data.error || "Failed to load problem set.");
                closeCqdOverlay();
                return;
            }

            if (data.aqg_id) {
                cqdProblemsOverlay.setAttribute('data-aqg-id', String(data.aqg_id));
            }
            if (cqdOverlayTitle) {
                cqdOverlayTitle.textContent = data.display_name || 'Problem Set';
            }
            refreshCqdCardLabel(cqdId, data.display_name, data.count);

            cqdOverlayList.innerHTML = data.html || '';
            if (!data.html) {
                updateOverlayEmptyState();
            } else {
                cqdOverlayList.querySelectorAll('.problem-title-input').forEach((input) => {
                    attachProblemInputListeners(input);
                });
                initializeSortableOnNestedList(cqdOverlayList);
            }
        } catch (err) {
            console.error("Failed to open problem set overlay:", err);
            alert("A network error occurred while loading the problem set.");
            closeCqdOverlay();
        }
    }

    function openContextMenuForRow(row, clientX, clientY) {
        hideProblemContextMenu();
        contextMenuTargetRow = row;
        row.classList.add('context-menu-active');

        const sectionCard = resolveSectionCardForRow(row);
        const currentAqgId = sectionCard?.getAttribute('data-id')
            || cqdProblemsOverlay?.getAttribute('data-aqg-id');
        const currentCqdId = cqdProblemsOverlay?.classList.contains('is-visible')
            ? cqdProblemsOverlay.getAttribute('data-cqd-id')
            : null;

        populateMoveSectionSubmenu(currentAqgId, !!currentCqdId);

        if (currentCqdId) {
            if (addToSetMenuWrap) addToSetMenuWrap.style.display = 'none';
            if (removeFromSetBtn) removeFromSetBtn.style.display = 'flex';
            hideAddToSetSubmenu();
        } else {
            if (addToSetMenuWrap) addToSetMenuWrap.style.display = '';
            if (removeFromSetBtn) removeFromSetBtn.style.display = 'none';
            populateAddToSetSubmenu(sectionCard, null);
        }

        positionProblemContextMenu(clientX, clientY);
    }

    if (problemContextMenu) {
        const contextMenuRoots = [canvasList, cqdOverlayList].filter(Boolean);
        contextMenuRoots.forEach((root) => {
            root.addEventListener('contextmenu', function(e) {
                const row = e.target.closest('.problem-item-row[data-problem-id]');
                if (!row || !root.contains(row)) return;
                e.preventDefault();
                e.stopPropagation();
                openContextMenuForRow(row, e.clientX, e.clientY);
            });
        });

        problemContextMenu.addEventListener('click', async function(e) {
            const actionBtn = e.target.closest('[data-action]');
            if (!actionBtn || !contextMenuTargetRow) return;

            const action = actionBtn.getAttribute('data-action');
            const sourceRow = contextMenuTargetRow;
            const problemId = sourceRow.getAttribute('data-problem-id');
            const sourceCard = resolveSectionCardForRow(sourceRow);
            const inOverlay = !!sourceRow.closest('#cqd-overlay-problems-list');

            if (action === 'move-to-section-toggle') {
                e.preventDefault();
                e.stopPropagation();
                if (actionBtn.disabled) return;
                hideAddToSetSubmenu();
                if (moveSectionSubmenu && moveSectionSubmenu.style.display === 'block') {
                    hideMoveSectionSubmenu();
                } else {
                    showFlyoutSubmenu(moveSectionSubmenu, moveSectionToggle);
                }
                return;
            }

            if (action === 'add-to-set-toggle') {
                e.preventDefault();
                e.stopPropagation();
                if (actionBtn.disabled) return;
                hideMoveSectionSubmenu();
                if (addToSetSubmenu && addToSetSubmenu.style.display === 'block') {
                    hideAddToSetSubmenu();
                } else {
                    showFlyoutSubmenu(addToSetSubmenu, addToSetToggle);
                }
                return;
            }

            if (action === 'move-to-section') {
                e.preventDefault();
                e.stopPropagation();

                const targetAqgId = actionBtn.getAttribute('data-aqg-id');
                const targetCard = canvasList.querySelector(`.aqg-section-card[data-id="${targetAqgId}"]`);
                const openCqdId = cqdProblemsOverlay?.getAttribute('data-cqd-id');

                hideProblemContextMenu();

                if (!problemId || !targetAqgId || !window.AQG_CONFIG?.moveProblemUrl) {
                    alert("Move is not available right now.");
                    return;
                }
                if (!targetCard) {
                    alert("Could not find the target section.");
                    return;
                }

                try {
                    const response = await fetch(window.AQG_CONFIG.moveProblemUrl, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({
                            problem_id: parseInt(problemId, 10),
                            target_aqg_id: parseInt(targetAqgId, 10)
                        })
                    });

                    const data = await response.json();
                    if (!response.ok || data.status !== 'success') {
                        alert(data.error || "Failed to move the problem.");
                        return;
                    }

                    const targetList = ensureTargetSectionList(targetCard);
                    if (!targetList) {
                        alert("Could not place the problem in the target section.");
                        return;
                    }

                    targetList.appendChild(sourceRow);
                    if (data.allocated_name) {
                        const titleInput = sourceRow.querySelector('.problem-title-input');
                        if (titleInput) {
                            titleInput.value = data.allocated_name;
                            titleInput.setAttribute('data-previous', data.allocated_name);
                        }
                    }

                    if (inOverlay) {
                        updateOverlayEmptyState();
                        if (openCqdId) refreshCqdCardLabel(openCqdId);
                    } else {
                        restoreEmptyPlaceholderIfNeeded(sourceCard);
                    }
                } catch (err) {
                    console.error("Problem move failed:", err);
                    alert("A network error occurred while moving the problem.");
                }
                return;
            }

            if (action === 'add-to-set') {
                e.preventDefault();
                e.stopPropagation();

                const targetCqdId = actionBtn.getAttribute('data-cqd-id');
                const openCqdId = cqdProblemsOverlay?.getAttribute('data-cqd-id');
                hideProblemContextMenu();

                if (!problemId || !targetCqdId || !window.AQG_CONFIG?.moveProblemToSetUrl) {
                    alert("Add to problem set is not available right now.");
                    return;
                }

                try {
                    const response = await fetch(window.AQG_CONFIG.moveProblemToSetUrl, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({
                            problem_id: parseInt(problemId, 10),
                            target_cqd_id: parseInt(targetCqdId, 10)
                        })
                    });

                    const data = await response.json();
                    if (!response.ok || data.status !== 'success') {
                        alert(data.error || "Failed to add the problem to the set.");
                        return;
                    }

                    if (data.allocated_name) {
                        const titleInput = sourceRow.querySelector('.problem-title-input');
                        if (titleInput) {
                            titleInput.value = data.allocated_name;
                            titleInput.setAttribute('data-previous', data.allocated_name);
                        }
                    }

                    // If the destination set overlay is open, keep the row there; otherwise remove from current list
                    if (cqdProblemsOverlay?.classList.contains('is-visible')
                        && String(cqdProblemsOverlay.getAttribute('data-cqd-id')) === String(targetCqdId)) {
                        const empty = cqdOverlayList.querySelector('.cqd-overlay-empty');
                        if (empty) empty.remove();
                        cqdOverlayList.appendChild(sourceRow);
                    } else {
                        sourceRow.remove();
                        if (inOverlay) {
                            updateOverlayEmptyState();
                        } else {
                            restoreEmptyPlaceholderIfNeeded(sourceCard);
                        }
                    }

                    if (data.cqd_display_name) {
                        refreshCqdCardLabel(targetCqdId, data.cqd_display_name, data.cqd_count);
                    }
                    if (data.old_cqd_id && data.old_cqd_display_name) {
                        refreshCqdCardLabel(data.old_cqd_id, data.old_cqd_display_name, data.old_cqd_count);
                    } else if (inOverlay && openCqdId && String(openCqdId) !== String(targetCqdId)) {
                        refreshCqdCardLabel(openCqdId);
                    }
                } catch (err) {
                    console.error("Add to problem set failed:", err);
                    alert("A network error occurred while adding the problem to the set.");
                }
                return;
            }

            if (action === 'remove-from-set') {
                e.preventDefault();
                e.stopPropagation();
                hideProblemContextMenu();

                if (!problemId || !window.AQG_CONFIG?.removeProblemFromSetUrl) {
                    alert("Remove from problem set is not available right now.");
                    return;
                }

                const openCqdId = cqdProblemsOverlay?.getAttribute('data-cqd-id');
                const sectionAqgId = cqdProblemsOverlay?.getAttribute('data-aqg-id')
                    || sourceCard?.getAttribute('data-id');

                try {
                    const response = await fetch(window.AQG_CONFIG.removeProblemFromSetUrl, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({
                            problem_id: parseInt(problemId, 10)
                        })
                    });

                    const data = await response.json();
                    if (!response.ok || data.status !== 'success') {
                        alert(data.error || "Failed to remove the problem from the set.");
                        return;
                    }

                    if (data.allocated_name) {
                        const titleInput = sourceRow.querySelector('.problem-title-input');
                        if (titleInput) {
                            titleInput.value = data.allocated_name;
                            titleInput.setAttribute('data-previous', data.allocated_name);
                        }
                    }

                    const aqgId = data.aqg_id || sectionAqgId;
                    const targetCard = aqgId
                        ? canvasList.querySelector(`.aqg-section-card[data-id="${aqgId}"]`)
                        : sourceCard;
                    const cqdId = data.source_cqd_id || openCqdId;
                    const cqdRow = cqdId
                        ? targetCard?.querySelector(`.cqd-item-row[data-cqd-id="${cqdId}"], .cqd-item-row[data-id="${cqdId}"]`)
                        : null;

                    const targetList = targetCard ? ensureTargetSectionList(targetCard) : null;
                    if (targetList && cqdRow) {
                        cqdRow.insertAdjacentElement('afterend', sourceRow);
                    } else if (targetList) {
                        targetList.appendChild(sourceRow);
                    }

                    if (inOverlay) {
                        updateOverlayEmptyState();
                    }

                    if (cqdId && data.cqd_display_name) {
                        refreshCqdCardLabel(cqdId, data.cqd_display_name, data.cqd_count);
                    } else if (cqdId) {
                        refreshCqdCardLabel(cqdId);
                    }
                } catch (err) {
                    console.error("Remove from problem set failed:", err);
                    alert("A network error occurred while removing the problem from the set.");
                }
                return;
            }

            hideProblemContextMenu();

            if (action !== 'duplicate') return;
            if (!problemId || !window.AQG_CONFIG?.duplicateProblemUrl) {
                alert("Duplicate is not available right now.");
                return;
            }

            try {
                const response = await fetch(window.AQG_CONFIG.duplicateProblemUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({ problem_id: parseInt(problemId, 10) })
                });

                const data = await response.json();
                if (!response.ok || !(data.status === 'success' || data.html)) {
                    alert(data.error || "Failed to duplicate the problem.");
                    return;
                }

                const listWrapper = sourceRow.closest('.problems-list-wrapper')
                    || sourceRow.parentElement;
                if (!listWrapper) {
                    alert("Could not place the duplicated problem in the list.");
                    return;
                }

                const empty = listWrapper.querySelector('.cqd-overlay-empty');
                if (empty) empty.remove();

                sourceRow.insertAdjacentHTML('afterend', data.html);
                const newRow = sourceRow.nextElementSibling;
                if (newRow) {
                    attachProblemInputListeners(newRow.querySelector('.problem-title-input'));
                }

                if (inOverlay) {
                    const openCqdId = cqdProblemsOverlay.getAttribute('data-cqd-id');
                    if (openCqdId) refreshCqdCardLabel(openCqdId);
                }
            } catch (err) {
                console.error("Problem duplicate failed:", err);
                alert("A network error occurred while duplicating the problem.");
            }
        });

        document.addEventListener('click', function(e) {
            if (!problemContextMenu || problemContextMenu.style.display === 'none') return;
            if (problemContextMenu.contains(e.target)) return;
            hideProblemContextMenu();
        });

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                if (problemContextMenu && problemContextMenu.style.display !== 'none') {
                    hideProblemContextMenu();
                    return;
                }
                if (cqdProblemsOverlay?.classList.contains('is-visible')) {
                    closeCqdOverlay();
                }
            }
        });

        window.addEventListener('scroll', hideProblemContextMenu, true);
        window.addEventListener('resize', hideProblemContextMenu);
    }

    if (cqdProblemsOverlay) {
        if (closeCqdOverlayBtn) {
            closeCqdOverlayBtn.addEventListener('click', function(e) {
                e.preventDefault();
                closeCqdOverlay();
            });
        }

        cqdProblemsOverlay.addEventListener('click', async function(e) {
            if (e.target === cqdProblemsOverlay) {
                closeCqdOverlay();
                return;
            }

            const deleteBtn = e.target.closest('.btn-delete-item[data-type="problem"]');
            if (!deleteBtn) return;

            e.preventDefault();
            e.stopPropagation();

            const itemRow = deleteBtn.closest('.problem-item-row');
            if (!itemRow || !cqdOverlayList?.contains(itemRow)) return;

            const itemId = itemRow.getAttribute('data-problem-id') || itemRow.getAttribute('data-id');
            const problemTitle = itemRow.querySelector('.problem-title-input')?.value || "this problem";
            if (!(await mapConfirm({ title: 'Confirm', message: `Are you sure you want to permanently delete "${problemTitle}"?`, danger: true, confirmLabel: 'Delete' }))) return;

            deleteBtn.disabled = true;
            const originalIcon = deleteBtn.innerHTML;
            deleteBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i>`;

            try {
                const response = await fetch('/delete-item/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({
                        id: parseInt(itemId, 10),
                        type: 'problem'
                    })
                });
                const data = await response.json();
                if (response.ok && data.status === 'success') {
                    const openCqdId = cqdProblemsOverlay.getAttribute('data-cqd-id');
                    itemRow.remove();
                    updateOverlayEmptyState();
                    if (openCqdId) refreshCqdCardLabel(openCqdId);
                } else {
                    alert(data.error || "Failed to remove the problem item.");
                    deleteBtn.disabled = false;
                    deleteBtn.innerHTML = originalIcon;
                }
            } catch (err) {
                console.error("Overlay deletion error:", err);
                alert("A critical networking transmission failure occurred.");
                deleteBtn.disabled = false;
                deleteBtn.innerHTML = originalIcon;
            }
        });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAssessmentSetupPage);
} else {
    initAssessmentSetupPage();
}