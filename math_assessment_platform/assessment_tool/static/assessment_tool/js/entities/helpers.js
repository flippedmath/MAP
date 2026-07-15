/**
 * Shared helpers for entity modules under entities/.
 *
 * Each entity exports processEntity(contextData) and switches on contextData.action:
 *   fieldsHtml          -> HTML string for card fields
 *   bindEvents          -> attach card-local listeners (void)
 *   evaluate            -> local cold-bootstrap value (string|null)
 *   serialize           -> mutate/return inputsCollected object
 *   applyBatchSync      -> render batch-sync result into card DOM
 *   renderPreviewToken  -> HTML snippet for canvas token replacement
 *   getOutputTypes      -> array of output type strings for link compatibility
 *   isLinkCompatible    -> boolean override for link dropdown rules
 *   hideRefreshButton   -> boolean (true = hide shuffle button)
 *   needsLatexRenderBox -> boolean (true = ensure .latex-render-box exists)
 *   initGlobalListeners -> one-time document-level listeners (matrix)
 */

/**
 * Prevent inserting literal token strings into type="number" inputs.
 * @param {*} val
 * @param {*} fallback
 * @returns {*}
 */
export function safeNumValue(val, fallback) {
    if (typeof val === 'string' && val.trim().match(/^<([^>]+)>$/)) {
        return fallback;
    }
    return val ?? fallback;
}

/**
 * Escape raw text for safe interpolation into HTML attribute/text contexts.
 * Required for math preview spans so values like "x < 5" do not break surrounding markup
 * (e.g. multiple-choice option rows after a linked formula).
 * @param {*} val
 * @returns {string}
 */
export function escapeHtmlText(val) {
    return String(val ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/**
 * Normalize a bound/pill token string to "<tokenId>" form.
 * @param {string} raw
 * @returns {string}
 */
export function cleanTokenBrackets(raw) {
    if (!raw) return '';
    let clean = String(raw).replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
    if (!clean.startsWith('<')) clean = `<${clean}`;
    if (!clean.endsWith('>')) clean = `${clean}>`;
    return clean;
}

/**
 * Ensure a .latex-render-box exists inside the card's fields wrapper.
 * @param {HTMLElement} card
 * @returns {HTMLElement|null}
 */
export function ensureLatexRenderBox(card) {
    let targetDisplay = card.querySelector('.latex-render-box');
    if (!targetDisplay) {
        const fieldsWrapper = card.querySelector('.component-fields-wrapper');
        if (fieldsWrapper) {
            targetDisplay = document.createElement('div');
            targetDisplay.className = 'latex-render-box';
            targetDisplay.style.cssText = 'margin-top: 8px; padding: 6px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; min-height: 24px; font-size: 0.9rem; text-align: center;';
            fieldsWrapper.appendChild(targetDisplay);
        }
    }
    return targetDisplay;
}

const GREEK_VAR_REGEX_STR = '^(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lamda|mu|nu|xi|omicron|rho|sigma|tau|upsilon|phi|chi|psi|omega)';

/**
 * Shared algebraic variable extraction used by formula cards and matrix cells.
 * Rejects reserved SymPy constants E/I; accepts single-letter, subscript, and greek forms.
 * Linked tokens `<tokenId>` recurse into the source card's `.val-input-variables` when present.
 *
 * @param {string} formulaStr
 * @returns {string[]}
 */
export function extractVariablesFromFormulaString(formulaStr) {
    if (!formulaStr) return [];

    const cleanStr = String(formulaStr).trim();
    const tokenMatch = cleanStr.match(/^<([^>]+)>$/);

    if (tokenMatch) {
        const targetTokenIndexName = tokenMatch[1].strip ? tokenMatch[1].strip() : tokenMatch[1];
        const sourceCard = document.querySelector(
            `[data-indexed-token="${targetTokenIndexName}"], [data-token="${targetTokenIndexName}"]`
        );
        if (sourceCard) {
            const sourceVarsInput = sourceCard.querySelector('.val-input-variables');
            if (sourceVarsInput && sourceVarsInput.value) {
                return sourceVarsInput.value.split(',').map(v => v.trim()).filter(v => v.length > 0);
            }
        }
        return [];
    }

    const allWordMatches = cleanStr.match(/\b[a-zA-Z][a-zA-Z0-9_]*\b/g) || [];

    const variableMatches = allWordMatches.filter(word => {
        const lowerWord = word.toLowerCase();

        if (word === 'E' || word === 'I') return false;

        if (/^[a-zA-Z][0-9]*$/.test(word)) return true;
        if (/^[a-zA-Z]_[0-9]+$/.test(word)) return true;

        if (new RegExp(GREEK_VAR_REGEX_STR + '$').test(lowerWord)) return true;
        if (new RegExp(GREEK_VAR_REGEX_STR + '_[0-9]+$').test(lowerWord)) return true;
        if (new RegExp(GREEK_VAR_REGEX_STR + '[0-9]+$').test(lowerWord)) return true;

        return false;
    });

    return [...new Set(variableMatches)];
}

/**
 * Trigger workspace batch sync for a card via a real input event (live-sync only listens to form controls).
 * @param {HTMLElement} card
 */
export function triggerCardLiveSync(card) {
    if (!card) return;
    const probe = card.querySelector(
        'input:not([type="hidden"]), select, textarea, .val-matrix-cell, .val-matrix-rows, .val-input-formula'
    );
    if (probe) {
        probe.dispatchEvent(new Event('input', { bubbles: true }));
    } else {
        card.dispatchEvent(new Event('change', { bubbles: true }));
    }
}
