import { ensureLatexRenderBox } from './helpers.js';

/**
 * longAnswer — free-response paragraph field. No auto-grading; preview shows
 * a plain textarea and the grade panel lists it as to be graded manually.
 */
export function processEntity(contextData) {
    if (!contextData || !contextData.action) return null;

    switch (contextData.action) {
        case 'fieldsHtml':
            return getFieldsHtml();
        case 'serialize':
            return serialize(contextData);
        case 'getOutputTypes':
            return ['content'];
        case 'hideRefreshButton':
            return true;
        case 'needsLatexRenderBox':
            return true;
        case 'applyBatchSync':
            return applyBatchSync(contextData);
        case 'renderPreviewToken':
            return renderPreviewToken(contextData);
        default:
            return null;
    }
}

function escapeHtmlAttr(val) {
    return String(val ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function getFieldsHtml() {
    return `
        <div style="display: flex; flex-direction: column; gap: 8px; width: 100%; box-sizing: border-box;">
            <p style="margin: 0; font-size: 0.78rem; color: #64748b; line-height: 1.4;">
                Students enter a paragraph response in the preview. Graded manually
                (preview score stays 0 of the card Points).
            </p>
        </div>
    `;
}

function serialize({ inputsCollected }) {
    return inputsCollected;
}

function applyBatchSync({ card, result }) {
    if (!card || !result) return null;

    const targetDisplay = ensureLatexRenderBox(card);
    if (targetDisplay) {
        targetDisplay.style.textAlign = 'center';
        targetDisplay.style.fontSize = '0.95rem';
        targetDisplay.style.fontWeight = '600';
        targetDisplay.style.color = '#0f172a';
        const out = result.evaluated_output;
        if (out && out !== '???' && !String(out).startsWith('[Invalid') && !String(out).startsWith('⚠️')) {
            targetDisplay.textContent = out;
        } else if (result.latex_output && result.latex_output !== '???' && !String(result.latex_output).startsWith('⚠️')) {
            targetDisplay.textContent = result.latex_output;
        } else {
            targetDisplay.textContent = 'Long answer (manual grading)';
        }
    }
    return true;
}

function renderPreviewToken({ cleanToken, initialValue }) {
    const token = cleanToken || '';
    let restored = '';
    if (initialValue !== undefined && initialValue !== null) {
        if (typeof initialValue === 'object' && initialValue.value != null) {
            restored = String(initialValue.value);
        } else {
            restored = String(initialValue);
        }
    }

    return `
        <div class="simulated-long-answer-wrapper" data-token="${escapeHtmlAttr(token)}" style="display:block; width:100%; max-width:560px; margin:8px 0; box-sizing:border-box;">
            <textarea class="preview-long-answer-input" data-token="${escapeHtmlAttr(token)}" rows="6" placeholder="Enter your response…" style="display:block; width:100%; box-sizing:border-box; background:#ffffff; border:1px solid #cbd5e1; border-radius:4px; padding:8px 10px; font-size:0.9rem; line-height:1.45; font-family:inherit; resize:vertical; min-height:120px;">${escapeHtmlAttr(restored)}</textarea>
        </div>
    `;
}
