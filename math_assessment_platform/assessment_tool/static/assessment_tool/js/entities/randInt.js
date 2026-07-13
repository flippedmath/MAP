import { safeNumValue, triggerCardLiveSync } from './helpers.js';

/**
 * randInt entity module — integer random value generator.
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

function getFieldsHtml(savedValues) {
    const exclusions = parseSavedExclusions(savedValues);
    const excludeRowsHtml = exclusions.map(value => buildExcludeRowHtml(value)).join('');

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

            <div class="randint-exclude-section linked-input-wrapper" data-input-key="exclude" data-input-type="text" style="display: flex; flex-direction: column; gap: 6px; width: 100%; box-sizing: border-box; border-top: 1px dashed #cbd5e1; padding-top: 8px;">
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
                    No excluded integers. Click "Add number to exclude" to remove specific values from the random pool.
                </p>
            </div>
        </div>
    `;
}

function buildExcludeRowHtml(value = '') {
    const safeValue = String(value ?? '').replace(/"/g, '&quot;');
    return `
        <div class="randint-exclude-row" style="display: flex; align-items: center; gap: 8px; width: 100%; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; padding: 4px 6px; box-sizing: border-box;">
            <label style="font-size: 0.75rem; color: #64748b; flex-grow: 1; display: flex; align-items: center; gap: 6px; margin: 0;">
                <span style="white-space: nowrap;">Exclude:</span>
                <input type="number" step="1" class="val-randint-exclude" value="${safeValue}" placeholder="integer" style="flex-grow: 1; width: 100%; box-sizing: border-box; font-size: 0.8rem; padding: 4px; border: 1px solid #cbd5e1; border-radius: 4px;">
            </label>
            <button type="button" class="btn-remove-randint-exclude" title="Remove exclusion" style="background: none; border: none; color: #94a3b8; cursor: pointer; font-size: 0.85rem; padding: 2px 4px;">
                <i class="fas fa-times-circle"></i>
            </button>
        </div>
    `;
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
        list.insertAdjacentHTML('beforeend', buildExcludeRowHtml(''));
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
        refreshExcludeEmptyHint(card);
        triggerCardLiveSync(card);
    });

    return true;
}

function collectExcludeIntegers(card) {
    if (!card) return [];
    const values = [];
    card.querySelectorAll('.val-randint-exclude').forEach(input => {
        const raw = String(input.value ?? '').trim();
        if (raw === '') return;
        values.push(raw);
    });
    return values;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    const excludes = collectExcludeIntegers(card);
    // Persist as comma-separated integers for RandomIntegerEntity server parsing
    inputsCollected.exclude = excludes.length ? excludes.join(', ') : '';
    return inputsCollected;
}

function evaluate({ card, tokenIdentifier, visitedTokens = [], getLiveComponentValue }) {
    if (!card || typeof getLiveComponentValue !== 'function') return null;

    const minStr = getLiveComponentValue(card, 'min', '1', visitedTokens);
    const maxStr = getLiveComponentValue(card, 'max', '9', visitedTokens);
    const stepStr = getLiveComponentValue(card, 'step', '1', visitedTokens);

    const minVal = parseInt(minStr, 10);
    const maxVal = parseInt(maxStr, 10);
    const stepVal = parseInt(stepStr, 10);

    const excludeSet = new Set();
    collectExcludeIntegers(card).forEach(raw => {
        if (/^-?\d+$/.test(raw)) {
            excludeSet.add(parseInt(raw, 10));
        }
    });

    if (!isNaN(minVal) && !isNaN(maxVal) && stepVal > 0 && minVal <= maxVal) {
        const pool = [];
        let current = minVal;
        while (current <= maxVal) {
            if (!excludeSet.has(current)) {
                pool.push(current);
            }
            current += stepVal;
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
    }
    return null;
}
