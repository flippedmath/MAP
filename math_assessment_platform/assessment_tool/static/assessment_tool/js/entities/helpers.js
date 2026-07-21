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

/**
 * CSRF token for workspace preview API posts.
 * @returns {string}
 */
export function getCsrfToken() {
    const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (csrfInput?.value) return csrfInput.value;
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
}

/**
 * Convert an expression string to LaTeX the same way a formula card does
 * (leave as formula → SymPy → sp.latex via validate-component-preview).
 * @param {string} expression
 * @returns {Promise<string|null>} latex string, or null if not formula-renderable
 */
export async function fetchFormulaStyleLatex(expression) {
    const expr = String(expression ?? '').trim();
    if (!expr) return null;

    const seq = `_aod_formula_preview_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
    let data;
    try {
        const res = await fetch('/assessment/api/validate-component-preview/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({
                trigger_token: seq,
                mutation_targets: [seq],
                entities: [{
                    token: 'formula',
                    sequence_token: seq,
                    inputs: {
                        formula: expr,
                        'solve method': 'leave as formula',
                        variables: '',
                    },
                    simulated_value: '',
                }],
            }),
        });
        data = await res.json();
    } catch (_) {
        return null;
    }

    const entry = data?.updated_cache?.[seq];
    const latex = entry?.latex_output;
    if (latex == null || latex === '') return null;
    const text = String(latex).trim();
    if (!text || text === '???' || text.startsWith('⚠️') || text.startsWith('[Invalid') || text.startsWith('[Evaluation')) {
        return null;
    }
    // Single bare identifier (e.g. "hello") is not a useful formula preview.
    if (/^[A-Za-z][A-Za-z0-9_]*$/.test(text) && !/[\d^\\{}_]/.test(expr)) {
        return null;
    }
    return text;
}

const GREEK_VAR_REGEX_STR = '^(?:alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lamda|mu|nu|xi|omicron|rho|sigma|tau|upsilon|phi|chi|psi|omega)';

/** Bare names reserved as SymPy special functions — not allowed as plain variables. */
export const RESERVED_SYMPY_GREEK_FUNCTIONS = ['beta', 'gamma', 'zeta'];

/**
 * Shared algebraic variable extraction used by formula cards and matrix cells.
 * Rejects reserved SymPy constants E/I; accepts single-letter, subscript, and greek forms.
 * Bare beta/gamma/zeta are excluded (SymPy functions); use beta_1 / gamma2 / etc. instead.
 * Linked tokens `<tokenId>` recurse into the source card's `.val-input-variables` when present.
 *
 * @param {string} formulaStr
 * @returns {string[]}
 */
function findWorkspaceCardByIndexedToken(indexedTokenName) {
    const clean = String(indexedTokenName || '').replace(/[<>]/g, '').trim();
    if (!clean) return null;
    // data-indexed-token lives on the delete button (and pills), not the card root.
    return Array.from(document.querySelectorAll('.workspace-component-card, .workspace-block-card'))
        .find((card) => {
            const delBtn = card.querySelector('.btn-delete-workspace-component');
            return delBtn && delBtn.getAttribute('data-indexed-token') === clean;
        }) || null;
}

function filterAlgebraicVariableTokens(wordMatches) {
    return wordMatches.filter((word) => {
        const lowerWord = word.toLowerCase();

        if (word === 'E' || word === 'I') return false;

        // SymPy special functions — not extractable as free variables
        if (RESERVED_SYMPY_GREEK_FUNCTIONS.includes(lowerWord)) return false;

        if (/^[a-zA-Z][0-9]*$/.test(word)) return true;
        if (/^[a-zA-Z]_[0-9]+$/.test(word)) return true;

        if (new RegExp(GREEK_VAR_REGEX_STR + '$').test(lowerWord)) return true;
        if (new RegExp(GREEK_VAR_REGEX_STR + '_[0-9]+$').test(lowerWord)) return true;
        if (new RegExp(GREEK_VAR_REGEX_STR + '[0-9]+$').test(lowerWord)) return true;

        return false;
    });
}

/**
 * Bare beta / gamma / zeta tokens appearing in a formula (not beta_1, gamma2, …).
 * @param {string} formulaStr
 * @returns {string[]} sorted unique reserved names found
 */
export function findReservedSympyGreekFunctionsInFormula(formulaStr) {
    if (!formulaStr) return [];
    const words = String(formulaStr).match(/\b[a-zA-Z][a-zA-Z0-9_]*\b/g) || [];
    const found = new Set();
    words.forEach((word) => {
        const lower = word.toLowerCase();
        if (RESERVED_SYMPY_GREEK_FUNCTIONS.includes(lower)) {
            found.add(lower);
        }
    });
    return [...found].sort();
}

export function extractVariablesFromFormulaString(formulaStr) {
    if (!formulaStr) return [];

    const cleanStr = String(formulaStr).trim();
    const tokenMatch = cleanStr.match(/^<([^>]+)>$/);

    if (tokenMatch) {
        const targetTokenIndexName = (tokenMatch[1] || '').trim();
        const sourceCard = findWorkspaceCardByIndexedToken(targetTokenIndexName);
        if (sourceCard) {
            const sourceVarsInput = sourceCard.querySelector('.val-input-variables');
            if (sourceVarsInput && sourceVarsInput.value) {
                return sourceVarsInput.value.split(',').map(v => v.trim()).filter(v => v.length > 0);
            }
            // Fall back to scraping free symbols from the upstream evaluated preview text
            const previewText = sourceCard.querySelector('.latex-render-box')?.textContent
                || sourceCard.getAttribute('data-simulated-value')
                || '';
            if (previewText) {
                const fromPreview = extractVariablesFromFormulaString(previewText);
                if (fromPreview.length) return fromPreview;
            }
        }
        return [];
    }

    const allWordMatches = cleanStr.match(/\b[a-zA-Z][a-zA-Z0-9_]*\b/g) || [];
    return [...new Set(filterAlgebraicVariableTokens(allWordMatches))];
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
