import { ensureLatexRenderBox, escapeHtmlText } from './helpers.js';

/**
 * matrixAnswer — link a matrix DV, toggle provided vs solve cells, grade blanks
 * like shortAnswer with per_cell / whole_matrix / points_per_cell modes.
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
        case 'getOutputTypes':
            return ['content'];
        case 'isLinkCompatible':
            return isLinkCompatible(contextData);
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

function normalizeGradingMode(raw) {
    const mode = String(raw || '').trim();
    if (['points_per_cell', 'whole_matrix', 'per_cell'].includes(mode)) return mode;
    return 'points_per_cell';
}

function normalizeSolveCells(raw) {
    let cells = raw;
    if (typeof cells === 'string') {
        try {
            cells = JSON.parse(cells);
        } catch (_) {
            cells = [];
        }
    }
    if (!Array.isArray(cells)) return [];
    const seen = new Set();
    const out = [];
    for (const item of cells) {
        if (!Array.isArray(item) || item.length < 2) continue;
        const r = parseInt(item[0], 10);
        const c = parseInt(item[1], 10);
        if (!Number.isFinite(r) || !Number.isFinite(c) || r < 0 || c < 0) continue;
        const key = `${r},${c}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push([r, c]);
    }
    return out;
}

function parseEvaluatedPayload(raw) {
    if (!raw || raw === '???' || String(raw).startsWith('[Invalid') || String(raw).startsWith('⚠️')) {
        return null;
    }
    if (typeof raw === 'object' && raw !== null) return raw;
    if (typeof raw !== 'string') return null;
    const s = raw.trim();
    if (!s.startsWith('{')) return null;
    try {
        return JSON.parse(s);
    } catch (_) {
        return null;
    }
}

function getCardPoints(card) {
    const raw = card.querySelector('.val-answer-field-points')?.value;
    let pts = parseFloat(raw);
    if (!Number.isFinite(pts)) {
        pts = parseFloat(card.getAttribute('data-points'));
    }
    if (!Number.isFinite(pts) || pts < 0) pts = 0;
    return pts;
}

function setCardPoints(card, value) {
    const pts = Number(value);
    if (!Number.isFinite(pts)) return;
    const input = card.querySelector('.val-answer-field-points');
    if (input) input.value = String(pts);
    card.setAttribute('data-points', String(pts));
}

function readSolveCellsFromCard(card) {
    const hidden = card.querySelector('.val-matrix-answer-solve-cells');
    return normalizeSolveCells(hidden?.value || '[]');
}

function writeSolveCellsToCard(card, cells) {
    const normalized = normalizeSolveCells(cells);
    const hidden = card.querySelector('.val-matrix-answer-solve-cells');
    if (hidden) hidden.value = JSON.stringify(normalized);
    return normalized;
}

function updatePointsPerCellNote(card) {
    const note = card.querySelector('.matrix-answer-ppc-note');
    if (!note) return;
    const mode = normalizeGradingMode(card.querySelector('.val-matrix-answer-grading-mode')?.value);
    if (mode !== 'points_per_cell') {
        note.style.display = 'none';
        note.textContent = '';
        return;
    }
    const n = readSolveCellsFromCard(card).length;
    const p = getCardPoints(card);
    note.style.display = 'block';
    note.textContent = `${n} cell${n === 1 ? '' : 's'} × ${p} pt${p === 1 ? '' : 's'} = ${n * p} pts available`;
}

function authorCellStyle(isSolve) {
    if (isSolve) {
        return 'background:#fef3c7; border:1px solid #f59e0b; color:#92400e; cursor:pointer;';
    }
    return 'background:#ffffff; border:1px solid #cbd5e1; color:#0f172a; cursor:pointer;';
}

function paintAuthorGrid(card, rows, solveCells) {
    const host = card.querySelector('.matrix-answer-author-grid');
    if (!host) return;

    const solveSet = new Set(
        normalizeSolveCells(solveCells).map(([r, c]) => `${r},${c}`)
    );

    if (!Array.isArray(rows) || !rows.length) {
        host.innerHTML = '<span style="font-size:0.75rem; color:#94a3b8;">Link a matrix to mark cells provided vs set to solve.</span>';
        return;
    }

    const tableRows = rows.map((row, r) => {
        const cells = (Array.isArray(row) ? row : []).map((val, c) => {
            const key = `${r},${c}`;
            const isSolve = solveSet.has(key);
            const label = isSolve ? 'Set to solve (click to provide)' : 'Provided (click to set to solve)';
            return `<td class="matrix-answer-author-cell" data-row="${r}" data-col="${c}" data-solve="${isSolve ? '1' : '0'}" title="${label}" style="padding:6px 10px; text-align:center; font-size:0.8rem; font-family:monospace; min-width:36px; ${authorCellStyle(isSolve)}">${escapeHtmlText(val)}</td>`;
        }).join('');
        return `<tr>${cells}</tr>`;
    }).join('');

    host.innerHTML = `
        <div style="font-size:0.7rem; color:#64748b; margin-bottom:4px;">Click a cell to toggle <strong>provided</strong> vs <strong>set to solve</strong>.</div>
        <table class="matrix-answer-author-table" style="border-collapse:collapse; margin:0 auto;">
            <tbody>${tableRows}</tbody>
        </table>
    `;
}

function getFieldsHtml(savedValues) {
    const linkedMatrixToken = (typeof savedValues.matrix === 'string' && /^<[^>]+>$/.test(savedValues.matrix.trim()))
        ? savedValues.matrix.trim()
        : '';
    const isLinked = !!linkedMatrixToken;
    const mode = normalizeGradingMode(savedValues.grading_mode);
    const solveCells = normalizeSolveCells(savedValues.solve_cells);
    const showPpcNote = mode === 'points_per_cell';

    return `
        <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">
            <div class="linked-input-wrapper" data-input-key="matrix" data-input-type="matrix" style="position: relative; display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; box-sizing: border-box; background: #f1f5f9; padding: 6px 8px; border-radius: 4px; border: 1px dashed #cbd5e1;">
                <div style="display: flex; flex-direction: column; min-width: 0; flex-grow: 1;">
                    <span style="font-size: 0.75rem; font-weight: 600; color: #334155;">Source Matrix</span>
                    <span class="link-status-text" style="font-size: 0.75rem; color: ${isLinked ? '#0284c7' : '#ef4444'}; font-family: monospace; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                        ${isLinked ? `Linked to: ${String(linkedMatrixToken).replace(/[<>]/g, '')}` : 'Required: Select a matrix'}
                    </span>
                </div>
                <div style="position: relative; display: flex; align-items: center; flex-shrink: 0;">
                    <button type="button" class="btn-input-link-trigger ${isLinked ? 'is-linked' : ''}" title="Link matrix token" style="background: #ffffff; border: 1px solid ${isLinked ? '#fca5a5' : '#cbd5e1'}; border-radius: 4px; color: ${isLinked ? '#ef4444' : '#94a3b8'}; cursor: pointer; font-size: 0.75rem; height: 28px; width: 28px; display: flex; align-items: center; justify-content: center; box-sizing: border-box;">
                        <i class="fas ${isLinked ? 'fa-times' : 'fa-link'}"></i>
                    </button>
                    <div class="linkable-tokens-dropdown" style="display: none; position: absolute; top: 100%; left: auto; right: 0; background: white; border: 1px solid #cbd5e1; border-radius: 4px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); z-index: 50; min-width: 150px; padding: 4px 0; margin-top: 4px; box-sizing: border-box;"></div>
                </div>
                <input type="hidden" class="val-matrix-answer-source" value="${isLinked ? escapeHtmlAttr(linkedMatrixToken) : ''}">
            </div>

            <div class="linked-input-wrapper" data-input-key="grading_mode" data-input-type="dropdown" style="display: flex; flex-direction: column; gap: 4px; width: 100%; box-sizing: border-box;">
                <label style="font-size: 0.75rem; color: #475569;">Grading mode:
                    <select class="val-matrix-answer-grading-mode" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px; margin-top:2px;">
                        <option value="points_per_cell" ${mode === 'points_per_cell' ? 'selected' : ''}>Points per cell</option>
                        <option value="whole_matrix" ${mode === 'whole_matrix' ? 'selected' : ''}>All or nothing</option>
                        <option value="per_cell" ${mode === 'per_cell' ? 'selected' : ''}>Split points per cell</option>
                    </select>
                </label>
                <div class="matrix-answer-ppc-note" style="display:${showPpcNote ? 'block' : 'none'}; font-size:0.7rem; color:#92400e; background:#fffbeb; border:1px solid #fde68a; border-radius:4px; padding:4px 6px;">
                    ${showPpcNote ? `${solveCells.length} cells × 1 pt = ${solveCells.length} pts available` : ''}
                </div>
            </div>

            <input type="hidden" class="val-matrix-answer-solve-cells" value="${escapeHtmlAttr(JSON.stringify(solveCells))}">
            <div class="matrix-answer-author-grid" style="width:100%; box-sizing:border-box; padding:6px; border:1px dashed #e2e8f0; border-radius:4px; background:#f8fafc; min-height:40px;">
                <span style="font-size:0.75rem; color:#94a3b8;">Link a matrix to mark cells provided vs set to solve.</span>
            </div>
        </div>
    `;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    const matrixWrapper = card.querySelector('.linked-input-wrapper[data-input-key="matrix"]');
    const boundToken = matrixWrapper?.getAttribute('data-bound-token');
    const hiddenVal = card.querySelector('.val-matrix-answer-source')?.value?.trim();
    const raw = boundToken || hiddenVal || '';
    if (raw) {
        let cleanToken = String(raw).replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
        if (!cleanToken.startsWith('<')) cleanToken = `<${cleanToken}`;
        if (!cleanToken.endsWith('>')) cleanToken = `${cleanToken}>`;
        inputsCollected.matrix = cleanToken;
    }

    const mode = normalizeGradingMode(card.querySelector('.val-matrix-answer-grading-mode')?.value);
    inputsCollected.grading_mode = mode;
    inputsCollected.solve_cells = readSolveCellsFromCard(card);
    return inputsCollected;
}

function isLinkCompatible({ inputKey, sourceArchetype }) {
    if (inputKey !== 'matrix') return null;
    return sourceArchetype === 'matrix';
}

function bindEvents({ card, updateWorkspaceSimulationPreview, dispatchWorkspaceBatchSync }) {
    if (!card) return null;

    const refreshPreviewAndSync = () => {
        // Preview first so blanks appear immediately from the card's solve_cells.
        if (typeof updateWorkspaceSimulationPreview === 'function') {
            updateWorkspaceSimulationPreview();
        }
        const cardId = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
        if (cardId && typeof dispatchWorkspaceBatchSync === 'function') {
            dispatchWorkspaceBatchSync(cardId);
        }
    };

    const modeSelect = card.querySelector('.val-matrix-answer-grading-mode');
    if (modeSelect && modeSelect.dataset.matrixAnswerModeBound !== '1') {
        modeSelect.dataset.matrixAnswerModeBound = '1';
        modeSelect.addEventListener('change', () => {
            const mode = normalizeGradingMode(modeSelect.value);
            if (mode === 'points_per_cell') {
                setCardPoints(card, 1);
            }
            updatePointsPerCellNote(card);
            refreshPreviewAndSync();
        });
    }

    const pointsInput = card.querySelector('.val-answer-field-points');
    if (pointsInput && pointsInput.dataset.matrixAnswerPtsBound !== '1') {
        pointsInput.dataset.matrixAnswerPtsBound = '1';
        const syncPts = () => {
            const parsed = parseFloat(pointsInput.value);
            if (Number.isFinite(parsed)) {
                card.setAttribute('data-points', String(parsed));
            }
            updatePointsPerCellNote(card);
            refreshPreviewAndSync();
        };
        pointsInput.addEventListener('change', syncPts);
        pointsInput.addEventListener('input', () => updatePointsPerCellNote(card));
    }

    const host = card.querySelector('.matrix-answer-author-grid');
    if (host && host.dataset.matrixAnswerGridBound !== '1') {
        host.dataset.matrixAnswerGridBound = '1';
        host.addEventListener('click', (e) => {
            const cell = e.target.closest?.('.matrix-answer-author-cell');
            if (!cell || !host.contains(cell)) return;
            const r = parseInt(cell.getAttribute('data-row'), 10);
            const c = parseInt(cell.getAttribute('data-col'), 10);
            if (!Number.isFinite(r) || !Number.isFinite(c)) return;

            const current = readSolveCellsFromCard(card);
            const idx = current.findIndex(([rr, cc]) => rr === r && cc === c);
            if (idx >= 0) {
                current.splice(idx, 1);
            } else {
                current.push([r, c]);
            }
            writeSolveCellsToCard(card, current);

            const isSolve = idx < 0;
            cell.setAttribute('data-solve', isSolve ? '1' : '0');
            cell.style.cssText = `padding:6px 10px; text-align:center; font-size:0.8rem; font-family:monospace; min-width:36px; ${authorCellStyle(isSolve)}`;
            cell.title = isSolve ? 'Set to solve (click to provide)' : 'Provided (click to set to solve)';

            updatePointsPerCellNote(card);
            refreshPreviewAndSync();
        });
    }

    updatePointsPerCellNote(card);
    return true;
}

function applyBatchSync({ card, result }) {
    if (!card || !result) return null;

    const payload = parseEvaluatedPayload(result.evaluated_output);
    const targetDisplay = ensureLatexRenderBox(card);
    if (targetDisplay) {
        targetDisplay.style.textAlign = 'center';
        targetDisplay.style.fontSize = '0.95rem';
        targetDisplay.style.fontWeight = '600';
        targetDisplay.style.color = '#0f172a';
        if (payload?.summary) {
            targetDisplay.textContent = payload.summary;
        } else if (result.latex_output && result.latex_output !== '???') {
            targetDisplay.textContent = result.latex_output;
        } else {
            targetDisplay.textContent = '';
        }
    }

    if (payload && Array.isArray(payload.rows)) {
        let solveCells = readSolveCellsFromCard(card);
        const nrows = payload.rows.length;
        const ncols = nrows ? (payload.rows[0] || []).length : 0;
        solveCells = solveCells.filter(([r, c]) => r >= 0 && c >= 0 && r < nrows && c < ncols);
        // Prefer server solve_cells if hidden was empty / freshly linked
        if (!solveCells.length && Array.isArray(payload.solve_cells)) {
            solveCells = normalizeSolveCells(payload.solve_cells);
        }
        writeSolveCellsToCard(card, solveCells);
        paintAuthorGrid(card, payload.rows, solveCells);
    } else {
        paintAuthorGrid(card, null, []);
    }

    updatePointsPerCellNote(card);
    return true;
}

function renderPreviewToken({ cleanToken, displayVal, card, initialValue }) {
    const token = cleanToken || '';
    let payload = parseEvaluatedPayload(displayVal);
    if (!payload && card) {
        payload = parseEvaluatedPayload(card.getAttribute('data-simulated-value'));
    }

    const restoredCells = (initialValue && typeof initialValue === 'object' && initialValue.cells
        && typeof initialValue.cells === 'object')
        ? initialValue.cells
        : {};

    if (!payload || !Array.isArray(payload.rows) || !payload.rows.length) {
        return `
            <div class="simulated-matrix-answer-wrapper" data-token="${escapeHtmlAttr(token)}" style="display:inline-block; vertical-align:middle; margin:4px 2px;">
                <span style="font-size:0.85rem; color:#94a3b8;">[Matrix answer]</span>
            </div>
        `;
    }

    // Live author selection on the card is source of truth (cached payload can lag).
    let solveCells = normalizeSolveCells(payload.solve_cells);
    if (card) {
        const fromCard = readSolveCellsFromCard(card);
        solveCells = fromCard;
    }

    const solveSet = new Set(solveCells.map(([r, c]) => `${r},${c}`));

    const tableRows = payload.rows.map((row, r) => {
        const cells = (Array.isArray(row) ? row : []).map((val, c) => {
            const key = `${r},${c}`;
            if (solveSet.has(key)) {
                const restored = restoredCells[key] != null ? String(restoredCells[key]) : '';
                return `<td style="padding:3px;"><input type="text" class="preview-matrix-answer-cell" data-token="${escapeHtmlAttr(token)}" data-row="${r}" data-col="${c}" value="${escapeHtmlAttr(restored)}" placeholder="?" style="width:72px; box-sizing:border-box; font-size:0.85rem; padding:4px 6px; border:1px solid #f59e0b; border-radius:4px; background:#fffbeb; text-align:center;"></td>`;
            }
            return `<td style="padding:6px 10px; text-align:center; font-size:0.9rem; font-family:monospace; background:#f8fafc; border:1px solid #e2e8f0;">${escapeHtmlText(val)}</td>`;
        }).join('');
        return `<tr>${cells}</tr>`;
    }).join('');

    return `
        <div class="simulated-matrix-answer-wrapper" data-token="${escapeHtmlAttr(token)}" style="display:inline-block; vertical-align:middle; margin:6px 2px;">
            <table class="preview-matrix-answer-table" style="border-collapse:collapse; margin:0 auto;">
                <tbody>${tableRows}</tbody>
            </table>
        </div>
    `;
}
