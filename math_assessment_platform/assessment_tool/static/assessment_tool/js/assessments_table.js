// ✅ Top-level function accessible by your HTML template dropdown listener
function handleStatusFieldMutation(assessmentId, newStatus) {
    const autoOpenCell = document.querySelector(`.auto-open-cell[data-assessment-id="${assessmentId}"]`);
    
    if (autoOpenCell) {
        if (newStatus === 'upcoming') {
            autoOpenCell.classList.remove('status-not-upcoming');
            
            const errorMsg = autoOpenCell.querySelector('.assessment-window-error-msg');
            const startInput = autoOpenCell.querySelector('.start-time-picker');
            const endInput = autoOpenCell.querySelector('.end-time-picker');
            
            if (errorMsg && (!startInput.value || !endInput.value)) {
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

// 🕒 Helper function to compute countdown string fields
function updateCountdownLabel(cell) {
    const countdownSpan = cell.querySelector('.window-status-countdown');
    if (!countdownSpan) return;

    // Clear previous state
    countdownSpan.innerHTML = "";

    // 1️⃣ Match your extra HTML elif block: If the cell is NOT upcoming, show the blue message
    if (cell.classList.contains('status-not-upcoming')) {
        countdownSpan.innerHTML = '<span style="color: #6fadbb;">Not in effect unless \'status\' = \'upcoming\'</span>';
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
        countdownSpan.innerHTML = '<span style="color: #10b981;">CURRENTLY OPEN</span>';
    }
}

// 🕒 Manage Datetime-Local Windows & Lock Actions
document.addEventListener('DOMContentLoaded', function() {
    
    // Initial run to build countdown text values on loaded inputs
    document.querySelectorAll('.auto-open-cell').forEach(cell => {
        updateCountdownLabel(cell);

        const assessmentId = cell.getAttribute('data-assessment-id');
        const startInput = cell.querySelector('.start-time-picker');
        const endInput = cell.querySelector('.end-time-picker');
        const lockCheckbox = cell.querySelector('.disable-window-checkbox');

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
                        saveWindowTimestamps(assessmentId, startInput.value || null, endInput.value || null);
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
            saveWindowTimestamps(assessmentId, startVal || null, endVal || null);
        }

        if (startInput) startInput.addEventListener('change', handleDateChange);
        if (endInput) endInput.addEventListener('change', handleDateChange);
    });

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
});