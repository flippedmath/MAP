(function() {
    const tabChannel = new BroadcastChannel('assessment_platform_tab_lock');
    const thisTabId = Math.random().toString(36).substring(2, 11); 
    let isMaster = true; 

    // Ping to see if other tabs are open
    tabChannel.postMessage({ type: 'PING_NEW_TAB', id: thisTabId });

    tabChannel.onmessage = function(event) {
        const msg = event.data;

        // If an older tab hears a new tab, or a tab hears another master re-asserting, freeze!
        if ((msg.type === 'PING_NEW_TAB' || msg.type === 'ASSERT_MASTER') && msg.id !== thisTabId) {
            isMaster = false;
            freezeDuplicateTab();
        }
    };

    function freezeDuplicateTab() {
        // Capture the exact URL path the user is currently on before wiping the DOM
        const currentUrl = window.location.href;

        // Completely clear the DOM so they cannot see or click any forms (Prevents 403s!)
        document.documentElement.innerHTML = `
            <html>
            <head>
                <title>Session Deactivated</title>
                <style>
                    body {
                        margin: 0; padding: 0;
                        display: flex; flex-direction: column;
                        justify-content: center; align-items: center;
                        height: 100vh; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                        background-color: #f8fafc; color: #1e293b; text-align: center;
                    }
                    .card {
                        background: white; padding: 30px; border-radius: 8px;
                        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06);
                        max-width: 400px; border-top: 4px solid #ef4444;
                    }
                    h1 { color: #ef4444; font-size: 1.5rem; margin-top: 0; }
                    p { font-size: 0.95rem; color: #475569; line-height: 1.5; }
                    .btn {
                        display: inline-block; margin-top: 15px; padding: 8px 16px;
                        background: #3b82f6; color: white; text-decoration: none;
                        border-radius: 4px; font-size: 0.9rem; font-weight: 500;
                        cursor: pointer; border: none;
                    }
                    .btn:hover { background: #2563eb; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>Multiple Tabs Detected</h1>
                    <p>The assessment platform can only be open in one browser tab at a time to maintain session security.</p>
                    <p>This tab has been deactivated because a newer tab was opened.</p>
                    <button onclick="window.location.reload();" class="btn">Re-activate This Tab</button>
                </div>
            </body>
            </html>
        `;
        
        // Stop any further background script execution on this stale page instance
        throw new Error("Tab execution halted due to multi-tab collision.");
    }

    // When the user switches focus back to this tab, verify if it's still master
    document.addEventListener('visibilitychange', function() {
        if (document.visibilityState === 'visible') {
            if (isMaster) {
                tabChannel.postMessage({ type: 'ASSERT_MASTER', id: thisTabId });
            } else {
                freezeDuplicateTab();
            }
        }
    });
})();