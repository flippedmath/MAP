// -------------------------------------------------------------
// Global Problem Workspace Overlay Controller Engine
// -------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function() {
    const workspaceOverlay = document.getElementById('problem-workspace-overlay');
    // 🎯 FIX: Target the editable input text field in your new layout instead of an h2 tag
    const overlayTitleField = document.getElementById('overlay-problem-title-field');
    const closeOverlayBtn = document.getElementById('close-workspace-overlay');
    
    // Core sub-containers inside the workspace overlay columns
    const variablesContainer = document.getElementById('sidebar-variables-list');
    const inputsContainer = document.getElementById('sidebar-inputs-list');
    const htmlCanvasEditor = document.getElementById('editor-html-insert-canvas');
    const tokensLedger = document.getElementById('overlay-tokens-wrapper-line');

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

        // Initialize display properties instantly for responsive feel
        if (overlayTitleField) overlayTitleField.value = problemTitle;
        workspaceOverlay.setAttribute('data-current-problem-id', problemId);
        
        // Show overlay framework and freeze background scrolling
        workspaceOverlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        // 🎯 NEW: Fetch problem data specifications asynchronously from the database
        try {
            if (variablesContainer) variablesContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">Loading components...</p>';
            if (inputsContainer) inputsContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">Loading components...</p>';
            if (tokensLedger) tokensLedger.innerHTML = '';
            if (htmlCanvasEditor) htmlCanvasEditor.innerHTML = '';

            const response = await fetch(`/get-item-preview/problem/${problemId}/`);
            if (!response.ok) throw new Error("Failed to load problem data maps.");
            
            const data = await response.json();
            
            // 🎯 FUTURE STEP: Render data down into the UI layouts
            // You will pass data.entities and data.html_content into builder functions here.
            if (htmlCanvasEditor && data.html_content) {
                htmlCanvasEditor.innerHTML = data.html_content;
            } else if (htmlCanvasEditor) {
                htmlCanvasEditor.innerHTML = '';
            }
            
            // Temporary confirmation placeholder visual layout clear
            if (variablesContainer) variablesContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">No dynamic variables defined.</p>';
            if (inputsContainer) inputsContainer.innerHTML = '<p style="color:#94a3b8; font-size:0.85rem; font-style:italic;">No answer forms attached.</p>';

        } catch (err) {
            console.error("Workspace configuration loader error:", err);
            if (variablesContainer) variablesContainer.innerHTML = '<p style="color:#ef4444; font-size:0.85rem;">Failed to synchronize elements.</p>';
        }
    });

    // 2. Global Close Controller Action
    if (closeOverlayBtn) {
        closeOverlayBtn.addEventListener('click', function() {
            workspaceOverlay.style.display = 'none';
            workspaceOverlay.removeAttribute('data-current-problem-id');
            document.body.style.overflow = ''; // Restore background scroll paths
        });
    }
});