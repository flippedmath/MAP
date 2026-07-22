import { safeNumValue, triggerCardLiveSync, escapeHtmlText } from './helpers.js';

/**
 * randInt entity module — integer random value generator.
 * Exclude rows accept literal integers or linked integer-producing entities (e.g. other randInt).
 */
export function processEntity(contextData) {
    if (!contextData || !contextData.action) return null;

    switch (contextData.action) {
        case 'fieldsHtml':
            return getFieldsHtml(contextData.savedValues || {});
        case 'bindEvents':
            return bindEvents(contextData);
        case 'serialize':
            return serialize(contextData);
        case 'evaluate':
            return evaluate(contextData);
        case 'renderPreviewToken':
            return renderPreviewToken(contextData);
        case 'getOutputTypes':
            return ['integer'];
        case 'hideRefreshButton':
            return false;
        case 'needsLatexRenderBox':
            return false;
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

/**
 * Return a canonical `<token>` for linked exclude entries, or '' for literals.
 * Never wrap bare integers (e.g. "0") — that incorrectly became "<0>" pills.
 */
function normalizeExcludeToken(raw) {
    let tok = String(raw ?? '')
        .replace(/&lt;/gi, '<')
        .replace(/&gt;/gi, '>')
        .trim();
    if (!tok) return '';

    // Plain integer excludes stay as text-field literals
    if (/^-?\d+$/.test(tok)) return '';

    if (/^<[^<>]+>$/.test(tok)) {
        const inner = tok.slice(1, -1).trim();
        // Recover corrupted saves where "0" was wrapped as "<0>"
        if (/^-?\d+$/.test(inner)) return '';
        return tok;
    }

    // Bare entity identifier (e.g. randInt4) — wrap as a link token
    if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(tok)) {
        return `<${tok}>`;
    }
    return '';
}

function parseSavedExclusions(savedValues = {}) {
    const raw = savedValues.exclude;
    if (raw == null || raw === '') return [];

    if (Array.isArray(raw)) {
        return raw.map(v => String(v).trim()).filter(Boolean);
    }

    return String(raw)
        .split(',')
        .map(v => v.trim())
        .filter(Boolean);
}

function coerceBool(raw, defaultValue = false) {
    if (raw == null || raw === '') return defaultValue;
    if (typeof raw === 'boolean') return raw;
    const s = String(raw).trim().toLowerCase();
    if (['true', '1', 'yes', 'on', 'checked'].includes(s)) return true;
    if (['false', '0', 'no', 'off'].includes(s)) return false;
    return defaultValue;
}

/** Inclusive [min,max] or exclusive (min,max) lattice endpoints for step sampling. */
function effectiveRandIntLattice(minVal, maxVal, stepVal, exclusive) {
    if (!(stepVal > 0) || Number.isNaN(minVal) || Number.isNaN(maxVal)) {
        return null;
    }
    const start = exclusive ? minVal + stepVal : minVal;
    if (exclusive) {
        if (start >= maxVal) return null;
        const maxK = Math.floor((maxVal - start - 1) / stepVal);
        if (maxK < 0) return null;
        return { start, maxK };
    }
    if (start > maxVal) return null;
    const maxK = Math.floor((maxVal - start) / stepVal);
    if (maxK < 0) return null;
    return { start, maxK };
}

function getFieldsHtml(savedValues) {
    const exclusions = parseSavedExclusions(savedValues);
    const excludeRowsHtml = exclusions.map((value, index) => buildExcludeRowHtml(value, index)).join('');
    const exclusiveBounds = coerceBool(savedValues.exclusive_bounds, false);

    return `
        <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">
                <div class="linked-input-wrapper" data-input-key="min" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px;">
                    <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Min: 
                        <input type="number" step="1" class="val-input-min" value="${safeNumValue(savedValues.min, 1)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                    </label>
                    <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
                </div>
                
                <div class="linked-input-wrapper" data-input-key="max" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px;">
                    <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Max: 
                        <input type="number" step="1" class="val-input-max" value="${safeNumValue(savedValues.max, 9)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                    </label>
                    <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
                </div>

                <div class="linked-input-wrapper" data-input-key="step" data-input-type="integer" style="position: relative; display: flex; align-items: flex-end; gap: 4px;">
                    <label style="font-size: 0.75rem; color: #475569; flex-grow: 1;">Step: 
                        <input type="number" step="1" class="val-input-step" value="${safeNumValue(savedValues.step, 1)}" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px;">
                    </label>
                    <button type="button" class="btn-input-link-trigger" title="Link token dependency" style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 4px; color: #94a3b8; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;"><i class="fas fa-link"></i></button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
                </div>
            </div>

            <div class="linked-input-wrapper" data-input-key="exclusive_bounds" data-input-type="checkbox" style="display: flex; align-items: center; gap: 8px; width: 100%; flex-wrap: wrap;">
                <label style="font-size: 0.75rem; color: #475569; font-weight: 500; display: inline-flex; align-items: center; gap: 6px; cursor: pointer; margin: 0;">
                    <input type="checkbox" class="val-randint-exclusive-bounds" ${exclusiveBounds ? 'checked' : ''} style="cursor: pointer;">
                    Exclusive min/max (open interval)
                </label>
                <span style="font-size: 0.7rem; color: #94a3b8;">Default unchecked: inclusive. Checked: exclude the min and max endpoints.</span>
            </div>

            <div class="randint-exclude-section" style="display: flex; flex-direction: column; gap: 6px; width: 100%; box-sizing: border-box; border-top: 1px dashed #cbd5e1; padding-top: 8px;">
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                    <span style="font-size: 0.75rem; font-weight: 600; color: #475569;">Exclude integers</span>
                    <button type="button" class="btn-add-randint-exclude" style="background: #eff6ff; border: 1px solid #bfdbfe; color: #1e40af; font-size: 0.72rem; padding: 3px 8px; border-radius: 4px; font-weight: 600; cursor: pointer;">
                        <i class="fas fa-plus"></i> Add number to exclude
                    </button>
                </div>
                <div class="randint-exclude-list" style="display: flex; flex-direction: column; gap: 6px;">
                    ${excludeRowsHtml}
                </div>
                <p class="randint-exclude-empty-hint" style="display: ${exclusions.length ? 'none' : 'block'}; margin: 0; font-size: 0.72rem; color: #94a3b8; font-style: italic;">
                    No excluded integers. Add a literal integer or link another randInt / integer token.
                </p>
            </div>
        </div>
    `;
}

function buildExcludeRowHtml(value = '', index = 0) {
    const linkedToken = normalizeExcludeToken(value);
    const linked = !!linkedToken;
    const numericValue = linked ? '' : String(value ?? '').replace(/"/g, '&quot;');
    const displayTok = linked ? linkedToken.replace(/[<>]/g, '') : '';

    return `
        <div class="randint-exclude-row linked-input-wrapper" data-input-key="exclude_${index}" data-input-type="integer" data-row-index="${index}" ${linked ? `data-bound-token="${escapeHtmlAttr(linkedToken)}"` : ''} style="position: relative; display: flex; align-items: center; gap: 8px; width: 100%; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; padding: 4px 6px; box-sizing: border-box;">
            <label style="font-size: 0.75rem; color: #64748b; flex-grow: 1; display: ${linked ? 'none' : 'flex'}; align-items: center; gap: 6px; margin: 0;">
                <span style="white-space: nowrap;">Exclude:</span>
                <input type="number" step="1" class="val-randint-exclude" value="${numericValue}" placeholder="integer" style="flex-grow: 1; width: 100%; box-sizing: border-box; font-size: 0.8rem; padding: 4px; border: 1px solid #cbd5e1; border-radius: 4px;">
            </label>
            ${linked ? `<span class="linked-token-pill" data-indexed-token="${escapeHtmlAttr(displayTok)}" style="background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; padding: 4px 8px; border-radius: 4px; font-family: monospace; font-weight: 600; font-size: 0.75rem; display: inline-block; flex-grow: 1; box-sizing: border-box; text-align: center;">${escapeHtmlAttr(linkedToken)}</span>` : ''}
            <button type="button" class="btn-input-link-trigger ${linked ? 'is-linked' : ''}" title="${linked ? 'Unlink' : 'Link integer token'}" style="background: #ffffff; border: 1px solid ${linked ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${linked ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 26px; width: 26px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                <i class="fas ${linked ? 'fa-times' : 'fa-link'}"></i>
            </button>
            <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 140px; padding: 4px 0; margin-top: 2px;"></div>
            <button type="button" class="btn-remove-randint-exclude" title="Remove exclusion" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.85rem; padding: 2px 4px; flex-shrink: 0;">
                <i class="fas fa-times-circle"></i>
            </button>
        </div>
    `;
}

function reindexExcludeRows(card) {
    if (!card) return;
    card.querySelectorAll('.randint-exclude-row').forEach((row, i) => {
        row.setAttribute('data-row-index', String(i));
        row.setAttribute('data-input-key', `exclude_${i}`);
    });
}

function refreshExcludeEmptyHint(card) {
    if (!card) return;
    const list = card.querySelector('.randint-exclude-list');
    const hint = card.querySelector('.randint-exclude-empty-hint');
    if (!list || !hint) return;
    hint.style.display = list.children.length ? 'none' : 'block';
}

function bindEvents({ card }) {
    if (!card) return null;

    const addBtn = card.querySelector('.btn-add-randint-exclude');
    const list = card.querySelector('.randint-exclude-list');
    if (!addBtn || !list) return true;

    addBtn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        const nextIndex = list.querySelectorAll('.randint-exclude-row').length;
        list.insertAdjacentHTML('beforeend', buildExcludeRowHtml('', nextIndex));
        refreshExcludeEmptyHint(card);
        const newest = list.querySelector('.randint-exclude-row:last-child .val-randint-exclude');
        if (newest) newest.focus();
        triggerCardLiveSync(card);
    });

    card.addEventListener('click', function(e) {
        const removeBtn = e.target.closest('.btn-remove-randint-exclude');
        if (!removeBtn || !card.contains(removeBtn)) return;
        e.preventDefault();
        e.stopPropagation();
        removeBtn.closest('.randint-exclude-row')?.remove();
        reindexExcludeRows(card);
        refreshExcludeEmptyHint(card);
        triggerCardLiveSync(card);
    });

    return true;
}

function collectExcludeEntries(card) {
    if (!card) return [];
    const values = [];
    card.querySelectorAll('.randint-exclude-row').forEach((row) => {
        const bound = normalizeExcludeToken(row.getAttribute('data-bound-token') || '');
        if (bound) {
            values.push(bound);
            return;
        }
        const input = row.querySelector('.val-randint-exclude');
        const raw = String(input?.value ?? '').trim();
        if (raw === '') return;
        values.push(raw);
    });
    return values;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    inputsCollected.exclusive_bounds = !!card.querySelector('.val-randint-exclusive-bounds')?.checked;

    const excludes = collectExcludeEntries(card);
    inputsCollected.exclude = excludes.length ? excludes.join(', ') : '';

    // Drop per-row keys so only the comma-separated exclude field is persisted
    Object.keys(inputsCollected).forEach((k) => {
        if (/^exclude_\d+$/.test(k)) delete inputsCollected[k];
    });
    return inputsCollected;
}

function evaluate({ card, tokenIdentifier, visitedTokens = [], getLiveComponentValue }) {
    if (!card || typeof getLiveComponentValue !== 'function') return null;

    const minStr = getLiveComponentValue(card, 'min', '1', visitedTokens);
    const maxStr = getLiveComponentValue(card, 'max', '9', visitedTokens);
    const stepStr = getLiveComponentValue(card, 'step', '1', visitedTokens);
    const exclusive = !!card.querySelector('.val-randint-exclusive-bounds')?.checked;

    const minVal = parseInt(minStr, 10);
    const maxVal = parseInt(maxStr, 10);
    const stepVal = parseInt(stepStr, 10);

    const excludeSet = new Set();
    card.querySelectorAll('.randint-exclude-row').forEach((row) => {
        const key = row.getAttribute('data-input-key');
        if (!key) return;
        const resolved = String(getLiveComponentValue(card, key, '', visitedTokens) ?? '').trim();
        if (/^-?\d+$/.test(resolved)) {
            excludeSet.add(parseInt(resolved, 10));
        }
    });

    const lattice = effectiveRandIntLattice(minVal, maxVal, stepVal, exclusive);
    if (!lattice) {
        const mode = exclusive ? 'exclusive' : 'inclusive';
        return `⚠️ Error: no integers in ${mode} range from ${minVal} to ${maxVal} (step ${stepVal}).`;
    }

    const pool = [];
    for (let k = 0; k <= lattice.maxK; k += 1) {
        const current = lattice.start + k * stepVal;
        if (!excludeSet.has(current)) {
            pool.push(current);
        }
    }

    if (pool.length > 0) {
        const seedAttr = card.getAttribute('data-shuffle-seed');
        let targetIndex = 0;
        if (seedAttr) {
            targetIndex = Math.floor(parseFloat(seedAttr) * pool.length);
        } else {
            const baseTextSeed = tokenIdentifier.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
            targetIndex = baseTextSeed % pool.length;
        }
        if (targetIndex >= pool.length) targetIndex = pool.length - 1;
        return pool[targetIndex].toString();
    }
    return '⚠️ Error: all candidate integers were removed by the exclude list.';
}

function renderPreviewToken({ displayVal }) {
    // Numeric value as inline LaTeX (no green badge). Preview pipeline
    // KaTeX-renders .simulated-math-formula-render spans after HTML insert.
    return `<span class="simulated-math-formula-render" style="display: inline-block; padding: 2px 4px;">${escapeHtmlText(displayVal)}</span>`;
}
