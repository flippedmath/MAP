// ✅ Top-level function accessible by your HTML template dropdown listener
function handleStatusFieldMutation(assessmentId, newStatus) {
    const autoOpenCell = document.querySelector(`.auto-open-cell[data-assessment-id="${assessmentId}"]`);
    
    if (autoOpenCell) {
        if (newStatus === 'upcoming') {
            autoOpenCell.classList.remove('status-not-upcoming');
            
            const errorMsg = autoOpenCell.querySelector('.assessment-window-error-msg');
            const startInput = autoOpenCell.querySelector('.start-time-picker');
            const endInput = autoOpenCell.querySelector('.end-time-picker');
            
            if (errorMsg && (!startInput?.value || !endInput?.value)) {
                errorMsg.style.display = 'block'; 
            }
        } else {
            autoOpenCell.classList.add('status-not-upcoming');
            
            const errorMsg = autoOpenCell.querySelector('.assessment-window-error-msg');
            if (errorMsg) {
                errorMsg.style.display = 'none';
            }
        }

        // 🔄 Recalculate the countdown text immediately on status changes
        if (typeof updateCountdownLabel === 'function') {
            updateCountdownLabel(autoOpenCell);
        }
    }
}

/** Parse a UTC/offset ISO string as an absolute instant (naive → UTC). */
function parseUtcInstant(iso) {
    if (!iso) return null;
    let text = String(iso).trim();
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(text)) {
        text += 'Z';
    }
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return null;
    return date;
}

/** Format a Date as YYYY-MM-DDTHH:mm for datetime-local (browser local TZ). */
function toDatetimeLocalValue(date) {
    if (!date) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
        `T${pad(date.getHours())}:${pad(date.getMinutes())}`
    );
}

/** datetime-local wall clock → ISO UTC for the server. */
function localInputToUtcIso(value) {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return date.toISOString();
}

function hydrateWindowInputsFromUtc(cell) {
    cell.querySelectorAll('.window-input[data-utc-iso]').forEach((input) => {
        const iso = input.getAttribute('data-utc-iso');
        const date = parseUtcInstant(iso);
        input.value = date ? toDatetimeLocalValue(date) : '';
    });
}

// 🕒 Helper function to compute countdown string fields
function updateCountdownLabel(cell) {
    const countdownSpan = cell.querySelector('.window-status-countdown');
    if (!countdownSpan) return;

    // Clear previous state
    countdownSpan.innerHTML = "";

    // Non-upcoming rows leave the Auto-Open cell blank.
    if (cell.classList.contains('status-not-upcoming')) {
        return;
    }

    const startInput = cell.querySelector('.start-time-picker');
    const endInput = cell.querySelector('.end-time-picker');
    
    // If it IS upcoming but the dates haven't been selected yet
    if (!startInput || !endInput || !startInput.value || !endInput.value) {
        countdownSpan.innerHTML = '<span style="color: #ef4444;">Missing Window Schedule</span>';
        return;
    }

    const now = new Date();
    const startDate = new Date(startInput.value);
    const endDate = new Date(endInput.value);

    // 2️⃣ Scenario A: Start date is in the future
    if (startDate > now) {
        const diffMs = startDate - now;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        const diffHours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
        const diffMinutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

        let timeString = "Starts in: ";
        if (diffDays > 0) timeString += `${diffDays}d `;
        if (diffHours > 0 || diffDays > 0) timeString += `${diffHours}h `;
        timeString += `${diffMinutes}m`;

        countdownSpan.style.color = "#475569";
        countdownSpan.innerText = timeString;
    } 
    // 3️⃣ Scenario B: Start date is in the past, End date is in the future
    else if (startDate <= now && endDate >= now) {
        const diffMs = endDate - now;
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
        const diffMinutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
        countdownSpan.innerHTML =
            `<span style="color: #10b981;">CURRENTLY OPEN — ends in ${diffHours}h ${diffMinutes}m</span>`;
    } else if (endDate < now) {
        countdownSpan.innerHTML = '<span style="color: #ef4444;">Window ended (will auto-close)</span>';
    }
}

// 🕒 Manage Datetime-Local Windows & Lock Actions
document.addEventListener('DOMContentLoaded', function() {
    
    // Initial run to build countdown text values on loaded inputs
    document.querySelectorAll('.auto-open-cell').forEach(cell => {
        hydrateWindowInputsFromUtc(cell);
        updateCountdownLabel(cell);

        const assessmentId = cell.getAttribute('data-assessment-id');
        const startInput = cell.querySelector('.start-time-picker');
        const endInput = cell.querySelector('.end-time-picker');
        const lockCheckbox = cell.querySelector('.disable-window-checkbox');

        if (!startInput || !endInput) return;

        if (lockCheckbox && lockCheckbox.checked) {
            startInput.disabled = true;
            endInput.disabled = true;
        }

        if (lockCheckbox) {
            lockCheckbox.addEventListener('change', function() {
                if (this.checked) {
                    startInput.disabled = true;
                    endInput.disabled = true;
                    if (startInput.value || endInput.value) {
                        saveWindowTimestamps(
                            assessmentId,
                            localInputToUtcIso(startInput.value),
                            localInputToUtcIso(endInput.value)
                        );
                    }
                } else {
                    startInput.disabled = false;
                    endInput.disabled = false;
                }
                updateCountdownLabel(cell);
            });
        }

        function handleDateChange() {
            if (lockCheckbox && lockCheckbox.checked) return;

            const startVal = startInput.value;
            const endVal = endInput.value;

            if (startVal && endVal) {
                const startDate = new Date(startVal);
                const endDate = new Date(endVal);

                if (startDate >= endDate) {
                    startInput.value = "";
                    startInput.style.borderColor = "#ef4444";
                    setTimeout(() => startInput.style.borderColor = "#cbd5e1", 1500);
                    updateCountdownLabel(cell);
                    return;
                }
            }
            
            // Trigger dynamic live label refresh
            updateCountdownLabel(cell);
            saveWindowTimestamps(
                assessmentId,
                localInputToUtcIso(startVal),
                localInputToUtcIso(endVal)
            );
        }

        startInput.addEventListener('change', handleDateChange);
        endInput.addEventListener('change', handleDateChange);
    });

    // Refresh countdown labels once a minute while the page is open.
    window.setInterval(() => {
        document.querySelectorAll('.auto-open-cell').forEach((cell) => {
            updateCountdownLabel(cell);
        });
    }, 60000);

    async function saveWindowTimestamps(assessmentId, startTime, endTime) {
        try {
            const response = await fetch(`/courses/api/assessment/${assessmentId}/update-window/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({
                    start_time: startTime,
                    end_time: endTime
                })
            });

            const data = await response.json();
            if (!response.ok) {
                console.error(`Backend Exception: ${data.error || 'Failed saving window parameters.'}`);
                return;
            }
            const cell = document.querySelector(
                `.auto-open-cell[data-assessment-id="${assessmentId}"]`
            );
            if (cell && data.start_time != null) {
                const startInput = cell.querySelector('.start-time-picker');
                const endInput = cell.querySelector('.end-time-picker');
                if (startInput) startInput.setAttribute('data-utc-iso', data.start_time || '');
                if (endInput) endInput.setAttribute('data-utc-iso', data.end_time || '');
            }
        } catch (err) {
            console.error("Transmission error updating window fields:", err);
        }
    }

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function normalizeAssessmentName(value) {
        return String(value || '').trim().replace(/\s+/g, ' ');
    }

    function autosizeAssessmentTitle(input) {
        input.style.height = 'auto';
        input.style.height = `${input.scrollHeight}px`;
    }

    document.querySelectorAll('.assessment-title-input').forEach((input) => {
        const savedBadge = input.parentElement?.querySelector('.assessment-name-saved');
        autosizeAssessmentTitle(input);

        const saveName = async () => {
            const cleanValue = normalizeAssessmentName(input.value);
            const previous = input.getAttribute('data-previous') || '';
            if (!cleanValue) {
                input.value = previous;
                autosizeAssessmentTitle(input);
                return;
            }
            if (cleanValue === previous) {
                input.value = cleanValue;
                autosizeAssessmentTitle(input);
                return;
            }

            const renameUrl = input.getAttribute('data-rename-url');
            const assessmentId = input.getAttribute('data-assessment-id');
            if (!renameUrl || !assessmentId) return;

            input.disabled = true;
            try {
                const response = await fetch(renameUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken'),
                    },
                    body: JSON.stringify({
                        assessment_id: assessmentId,
                        name: cleanValue,
                    }),
                });
                const data = await response.json().catch(() => ({}));
                if (response.ok && data.success) {
                    const savedName = data.name || cleanValue;
                    input.value = savedName;
                    input.setAttribute('data-previous', savedName);
                    const optionsBtn = input.closest('tr')?.querySelector('[data-assessment-options]');
                    if (optionsBtn) optionsBtn.setAttribute('data-assessment-name', savedName);
                    if (savedBadge) {
                        savedBadge.hidden = false;
                        window.clearTimeout(savedBadge._hideTimer);
                        savedBadge._hideTimer = window.setTimeout(() => {
                            savedBadge.hidden = true;
                        }, 1600);
                    }
                } else {
                    alert(data.error || 'Failed to rename assessment.');
                    input.value = previous;
                }
            } catch (err) {
                console.error('Assessment rename failed:', err);
                alert('Connection error while renaming assessment.');
                input.value = previous;
            } finally {
                input.disabled = false;
                autosizeAssessmentTitle(input);
            }
        };

        input.addEventListener('input', () => autosizeAssessmentTitle(input));
        input.addEventListener('blur', saveName);
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                input.blur();
            } else if (event.key === 'Escape') {
                event.preventDefault();
                input.value = input.getAttribute('data-previous') || '';
                autosizeAssessmentTitle(input);
                input.blur();
            }
        });
    });

    window.addEventListener('resize', () => {
        document.querySelectorAll('.assessment-title-input').forEach(autosizeAssessmentTitle);
    });

    document.querySelectorAll('.btn-trash-assessment').forEach(button => {
        button.addEventListener('click', async function(e) {
            e.preventDefault();
            
            const assessmentId = this.getAttribute('data-assessment-id');
            const targetedRow = this.closest('tr');

            const userConfirmed = confirm("Are you sure you want to delete this assessment? This will move its structural files to the Trash folder and remove it from your active dashboard.");
            if (!userConfirmed) return;

            try {
                const response = await fetch(`/courses/api/assessment/${assessmentId}/trash/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken')
                    },
                    body: JSON.stringify({}) // No need to manually forward branch_group_id anymore!
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    // Smoothly slide out and remove the row from the viewport without breaking focus
                    targetedRow.style.transition = "all 0.4s ease";
                    targetedRow.style.opacity = "0";
                    targetedRow.style.transform = "translateX(-20px)";
                    
                    setTimeout(() => {
                        targetedRow.remove();
                        
                        // If no assessments are left visible, reload to display your native empty state placeholder
                        const remainingRows = document.querySelectorAll('#assessments-datatable tbody tr:not(#empty-state-row)');
                        if (remainingRows.length === 0) {
                            window.location.reload();
                        }
                    }, 400);
                } else {
                    alert(data.error || "An error occurred while attempting to remove this assessment blueprint.");
                }
            } catch (err) {
                console.error("Communication failure running trash modification routine:", err);
                alert("Connection link failure encountered while moving item to Trash.");
            }
        });
    });


    const tableBody = document.querySelector('#assessments-datatable tbody');
    if (tableBody) {
        // Initialize Drag & Drop targeting the handles exclusively
        new Sortable(tableBody, {
            handle: '.drag-handle', // Only trigger drag via the ☰ icon cell
            animation: 150,
            ghostClass: 'sortable-ghost', // Styling hook for the moving row placeholder
            
            onEnd: async function (evt) {
                const movedRow = evt.item;
                const assessmentId = movedRow.getAttribute('data-id');
                
                // Look up neighboring elements relative to the DOM row container after movement drops
                const prevRow = movedRow.previousElementSibling;
                const nextRow = movedRow.nextElementSibling;
                
                const prevId = prevRow ? prevRow.getAttribute('data-id') : null;
                const nextId = nextRow ? nextRow.getAttribute('data-id') : null;
                
                // Extract the course ID from your existing page scope architecture configuration context url
                const currentUrl = window.location.pathname; 
                const courseIdMatch = currentUrl.match(/\/course\/(\d+)\//);
                if (!courseIdMatch) return;
                const courseId = courseIdMatch[1];

                try {
                    const response = await fetch(`/courses/api/course/${courseId}/reorder-assessments/`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCookie('csrftoken')
                        },
                        body: JSON.stringify({
                            assessment_id: assessmentId,
                            prev_id: prevId,
                            next_id: nextId
                        })
                    });

                    const data = await response.json();
                    if (response.ok && data.success) {
                        // Update data-order attribute dynamically on the row elements
                        movedRow.setAttribute('data-order', data.new_order);
                    } else {
                        alert(data.error || "Failed to save position modifications.");
                    }
                } catch (err) {
                    console.error("Sorting transaction error across endpoint link channels:", err);
                    alert("Connection link failure encountered while tracking item placement.");
                }
            }
        });
    }
});
