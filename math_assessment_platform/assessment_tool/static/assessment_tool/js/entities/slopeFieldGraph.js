import { safeNumValue, ensureLatexRenderBox } from './helpers.js';

/**
 * slopeFieldGraph — answer-field slope field with teacher selection + student preview.
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
        case 'applyBatchSync':
            return applyBatchSync(contextData);
        case 'renderPreviewToken':
            return renderPreviewToken(contextData);
        case 'getOutputTypes':
            return ['content'];
        case 'hideRefreshButton':
            return true;
        case 'needsLatexRenderBox':
            return true;
        default:
            return null;
    }
}

function getAxisTriple(savedValues, axis) {
    const legacy = savedValues[`${axis}-axis range`];
    if (Array.isArray(legacy) && legacy.length === 3) {
        return [
            safeNumValue(legacy[0], -5),
            safeNumValue(legacy[1], 5),
            safeNumValue(legacy[2], 1)
        ];
    }
    return [
        safeNumValue(savedValues[`${axis}_min`], -5),
        safeNumValue(savedValues[`${axis}_max`], 5),
        safeNumValue(savedValues[`${axis}_step`], 1)
    ];
}

function getFieldsHtml(savedValues) {
    const equation = savedValues.equation || 'dy/dx = x + y';
    const [xMin, xMax, xStep] = getAxisTriple(savedValues, 'x');
    const [yMin, yMax, yStep] = getAxisTriple(savedValues, 'y');
    const selectedJson = JSON.stringify(Array.isArray(savedValues.selected_points) ? savedValues.selected_points : []);

    return `
        <div style="display: flex; flex-direction: column; gap: 10px; width: 100%; box-sizing: border-box;">
            <div class="linked-input-wrapper" data-input-key="equation" data-input-type="text" style="display: flex; flex-direction: column; gap: 4px; width: 100%;">
                <label style="font-size: 0.75rem; color: #475569; font-weight: 500;">Slope Field Equation:
                    <input type="text" class="val-slope-equation" value="${escapeAttr(equation)}" placeholder="dy/dx = x + y" style="width:100%; box-sizing:border-box; font-size:0.8rem; padding:4px; border:1px solid #cbd5e1; border-radius:4px; font-family:monospace;">
                </label>
            </div>

            <div style="display: flex; flex-direction: column; gap: 4px; border-top: 1px dashed #cbd5e1; padding-top: 6px;">
                <span style="font-size: 0.72rem; font-weight: 600; color: #64748b;">Axis Limits (min / max / step):</span>
                <div style="display: grid; grid-template-columns: 45px repeat(3, 1fr); gap: 6px; align-items: center;">
                    <span style="font-size: 0.75rem; color: #475569; font-weight: 500;">X-Axis:</span>
                    <div class="linked-input-wrapper" data-input-key="x_min" data-input-type="double">
                        <input type="number" step="any" class="val-slope-x-min" value="${xMin}" placeholder="Min" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    </div>
                    <div class="linked-input-wrapper" data-input-key="x_max" data-input-type="double">
                        <input type="number" step="any" class="val-slope-x-max" value="${xMax}" placeholder="Max" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    </div>
                    <div class="linked-input-wrapper" data-input-key="x_step" data-input-type="double">
                        <input type="number" step="any" class="val-slope-x-step" value="${xStep}" placeholder="Step" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: 45px repeat(3, 1fr); gap: 6px; align-items: center;">
                    <span style="font-size: 0.75rem; color: #475569; font-weight: 500;">Y-Axis:</span>
                    <div class="linked-input-wrapper" data-input-key="y_min" data-input-type="double">
                        <input type="number" step="any" class="val-slope-y-min" value="${yMin}" placeholder="Min" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    </div>
                    <div class="linked-input-wrapper" data-input-key="y_max" data-input-type="double">
                        <input type="number" step="any" class="val-slope-y-max" value="${yMax}" placeholder="Max" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    </div>
                    <div class="linked-input-wrapper" data-input-key="y_step" data-input-type="double">
                        <input type="number" step="any" class="val-slope-y-step" value="${yStep}" placeholder="Step" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    </div>
                </div>
            </div>

            <input type="hidden" class="val-slope-selected-points" value='${escapeAttr(selectedJson)}'>
            <div class="slope-field-card-host" data-selected-points='${escapeAttr(selectedJson)}' style="width:100%; min-height:240px; background:#ffffff; border:1px solid #e2e8f0; border-radius:4px;"></div>
            <span style="font-size:0.7rem; color:#64748b;">Click a lattice dot to mark/unmark that slope tick (dark = selected).</span>
        </div>
    `;
}

function escapeAttr(val) {
    return String(val)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function bindEvents({ card, updateWorkspaceSimulationPreview }) {
    if (!card) return null;

    const host = card.querySelector('.slope-field-card-host');
    if (host && !host.dataset.boundAuthorClicks) {
        host.dataset.boundAuthorClicks = '1';
        // Selection clicks are bound inside renderSlopeFieldCanvas(author mode)
    }

    // Checkbox-like change isn't needed; axis/equation already fire card input → preview
    return true;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;

    const equation = card.querySelector('.val-slope-equation')?.value?.trim() || 'dy/dx = x + y';
    const xMin = parseFloat(card.querySelector('.val-slope-x-min')?.value);
    const xMax = parseFloat(card.querySelector('.val-slope-x-max')?.value);
    const xStep = parseFloat(card.querySelector('.val-slope-x-step')?.value);
    const yMin = parseFloat(card.querySelector('.val-slope-y-min')?.value);
    const yMax = parseFloat(card.querySelector('.val-slope-y-max')?.value);
    const yStep = parseFloat(card.querySelector('.val-slope-y-step')?.value);

    inputsCollected.equation = equation;
    inputsCollected['x-axis range'] = [
        Number.isFinite(xMin) ? xMin : -5,
        Number.isFinite(xMax) ? xMax : 5,
        Number.isFinite(xStep) ? xStep : 1
    ];
    inputsCollected['y-axis range'] = [
        Number.isFinite(yMin) ? yMin : -5,
        Number.isFinite(yMax) ? yMax : 5,
        Number.isFinite(yStep) ? yStep : 1
    ];
    inputsCollected.x_min = inputsCollected['x-axis range'][0];
    inputsCollected.x_max = inputsCollected['x-axis range'][1];
    inputsCollected.x_step = inputsCollected['x-axis range'][2];
    inputsCollected.y_min = inputsCollected['y-axis range'][0];
    inputsCollected.y_max = inputsCollected['y-axis range'][1];
    inputsCollected.y_step = inputsCollected['y-axis range'][2];

    const host = card.querySelector('.slope-field-card-host');
    const hidden = card.querySelector('.val-slope-selected-points');
    let selected = [];
    try {
        const raw = host?.getAttribute('data-selected-points') || hidden?.value || '[]';
        selected = JSON.parse(raw);
        if (!Array.isArray(selected)) selected = [];
    } catch (e) {
        selected = [];
    }
    selected = pruneSelectedToAxisRanges(
        selected,
        inputsCollected['x-axis range'],
        inputsCollected['y-axis range']
    );
    writeSelectedToHost(card, selected);
    inputsCollected.selected_points = selected;
    return inputsCollected;
}

function pointKey(x, y) {
    return `${Number(x).toFixed(8)},${Number(y).toFixed(8)}`;
}

/** Keep only selected points that still lie on the visible lattice. */
function pruneSelectedToLattice(selected, lattice) {
    if (!Array.isArray(selected) || !selected.length) return [];
    const keys = new Set(
        (Array.isArray(lattice) ? lattice : []).map((p) => pointKey(p.x, p.y))
    );
    return selected.filter((pair) => {
        if (!Array.isArray(pair) || pair.length < 2) return false;
        return keys.has(pointKey(pair[0], pair[1]));
    });
}

/** Client-side lattice rebuild for serialize before server response. */
function pruneSelectedToAxisRanges(selected, xRange, yRange) {
    if (!Array.isArray(selected) || !selected.length) return [];
    const [xMin, xMax, xStep] = xRange;
    const [yMin, yMax, yStep] = yRange;
    if (!(xStep > 0) || !(yStep > 0) || !(xMin < xMax) || !(yMin < yMax)) {
        return [];
    }
    const keys = new Set();
    const maxPts = 40;
    let xi = 0;
    for (let x = xMin; x <= xMax + xStep * 1e-9 && xi <= maxPts; x = Math.round((x + xStep) * 1e10) / 1e10, xi++) {
        let yi = 0;
        for (let y = yMin; y <= yMax + yStep * 1e-9 && yi <= maxPts; y = Math.round((y + yStep) * 1e10) / 1e10, yi++) {
            keys.add(pointKey(x, y));
        }
    }
    return selected.filter((pair) => {
        if (!Array.isArray(pair) || pair.length < 2) return false;
        return keys.has(pointKey(pair[0], pair[1]));
    });
}

function parseSlopeConfig(raw) {
    if (raw == null || raw === '') return null;
    if (typeof raw === 'object') {
        return raw.archetype === 'slopeFieldGraph' ? raw : null;
    }
    if (typeof raw !== 'string') return null;
    const trimmed = raw.trim();
    if (!trimmed.startsWith('{')) return null;
    const parsed = JSON.parse(trimmed);
    return (parsed && parsed.archetype === 'slopeFieldGraph') ? parsed : null;
}

function applyBatchSync({ card, result, token }) {
    if (!card || !result) return null;

    const targetDisplay = ensureLatexRenderBox(card);
    const host = card.querySelector('.slope-field-card-host');
    if (!host) return null;

    // Keep latex box compact; paint into dedicated host
    if (targetDisplay) {
        targetDisplay.style.display = 'none';
    }

    try {
        let rawOutput = result.evaluated_output;
        if (typeof rawOutput === 'string' && rawOutput.startsWith('[Invalid')) {
            host.innerHTML = `<div style="padding:12px; color:#dc2626; font-size:0.85rem; text-align:center;">⚠️ ${rawOutput.replace(/[\[\]]/g, '')}</div>`;
            return true;
        }

        const config = parseSlopeConfig(rawOutput);
        if (!config) {
            host.innerHTML = `<div style="padding:12px; color:#64748b; font-size:0.85rem; text-align:center; font-style:italic;">Enter a valid slope equation to render the field...</div>`;
            return true;
        }

        // Drop teacher-selected points that are no longer on the visible lattice
        let selected = host.hasAttribute('data-selected-points')
            ? readSelectedFromHost(host)
            : (Array.isArray(config.selected_points) ? config.selected_points : []);
        selected = pruneSelectedToLattice(selected, config.lattice || []);
        writeSelectedToHost(card, selected);
        config.selected_points = selected;

        renderSlopeFieldCanvas(host, config, {
            mode: 'author',
            width: Math.min(340, host.clientWidth || 340),
            height: 240,
            onSelectionChange: (points) => {
                writeSelectedToHost(card, points);
                // Bubble so overlay marks unsaved + runs live sync / preview refresh
                const probe = card.querySelector('.val-slope-equation') || card;
                probe.dispatchEvent(new Event('input', { bubbles: true }));
            }
        });
    } catch (err) {
        console.error('Slope field card render failed:', err);
        host.innerHTML = `<div style="padding:12px; color:#dc2626; font-size:0.85rem; text-align:center;">⚠️ Could not render slope field.</div>`;
    }
    return true;
}

function readSelectedFromHost(host) {
    try {
        const raw = host.getAttribute('data-selected-points') || '[]';
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        return [];
    }
}

function writeSelectedToHost(card, points) {
    const host = card.querySelector('.slope-field-card-host');
    const hidden = card.querySelector('.val-slope-selected-points');
    const json = JSON.stringify(points || []);
    if (host) host.setAttribute('data-selected-points', json);
    if (hidden) hidden.value = json;
}

function renderPreviewToken({
    displayVal,
    cleanToken,
    card,
    registerPreviewGraph,
    previewInstanceId
}) {
    let config = null;
    try {
        config = parseSlopeConfig(displayVal);
    } catch (e) {
        config = null;
    }
    if (!config && card) {
        try {
            config = parseSlopeConfig(card.getAttribute('data-simulated-value'));
        } catch (e) {
            config = null;
        }
    }

    const canvasId = previewInstanceId || `slope-preview-${cleanToken}-${Date.now()}`;

    if (!config) {
        return `
            <div class="simulated-live-slope-preview-container" style="display:inline-block; vertical-align:middle; margin:4px 2px; padding:8px 12px; border:1px dashed #cbd5e1; border-radius:4px; color:#64748b; font-size:0.8rem; font-style:italic;">
                Slope field preview loading…
            </div>
        `;
    }

    if (typeof registerPreviewGraph === 'function') {
        registerPreviewGraph({
            canvasId,
            graphConfig: config,
            cleanToken,
            kind: 'slopeFieldGraph'
        });
    }

    return `
        <div class="simulated-live-slope-preview-container" style="display:inline-block; vertical-align:middle; margin:4px 2px; max-width:348px; width:100%;">
            <div id="${canvasId}" class="live-preview-slope-canvas" style="width:100%; min-height:240px; background:#fff; border:1px solid #e2e8f0; border-radius:4px;"></div>
        </div>
    `;
}

/**
 * Shared SVG slope-field painter.
 * @param {HTMLElement} targetEl
 * @param {object} config - server manifest
 * @param {{ mode: 'author'|'student', width?: number, height?: number, onSelectionChange?: Function }} options
 */
export function renderSlopeFieldCanvas(targetEl, config, options = {}) {
    if (!targetEl || !config || config.archetype !== 'slopeFieldGraph') return;

    const mode = options.mode || 'author';
    const width = Math.max(120, Math.round(options.width || 340));
    const height = Math.max(120, Math.round(options.height || 240));
    const padL = 36;
    const padR = 12;
    const padT = 12;
    const padB = 28;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    const xMin = config.bounds?.x_range?.min ?? -5;
    const xMax = config.bounds?.x_range?.max ?? 5;
    const xStep = config.bounds?.x_range?.step ?? 1;
    const yMin = config.bounds?.y_range?.min ?? -5;
    const yMax = config.bounds?.y_range?.max ?? 5;
    const yStep = config.bounds?.y_range?.step ?? 1;
    // Tick length in graph units = one step (use average of axis steps if they differ)
    const tickLen = (Math.abs(xStep) + Math.abs(yStep)) / 2;

    const lattice = Array.isArray(config.lattice) ? config.lattice : [];
    let selected = Array.isArray(config.selected_points) ? config.selected_points.slice() : [];

    const xToPx = (x) => padL + ((x - xMin) / (xMax - xMin || 1)) * plotW;
    const yToPx = (y) => padT + ((yMax - y) / (yMax - yMin || 1)) * plotH;
    const pxToX = (px) => xMin + ((px - padL) / (plotW || 1)) * (xMax - xMin);
    const pxToY = (py) => yMax - ((py - padT) / (plotH || 1)) * (yMax - yMin);

    const selectedSet = () => new Set(selected.map(([x, y]) => `${roundKey(x)},${roundKey(y)}`));
    const isSelected = (x, y, set) => set.has(`${roundKey(x)},${roundKey(y)}`);

    function pointKey(x, y) {
        return `${roundKey(x)},${roundKey(y)}`;
    }

    function roundKey(n) {
        return Number(n).toFixed(8);
    }

    function tickEndpoints(x, y, slope, finite) {
        const cx = xToPx(x);
        const cy = yToPx(y);
        // Half-length in graph units along the direction vector of length tickLen
        let dx = tickLen / 2;
        let dy = 0;
        if (!finite || slope === null || slope === undefined || !Number.isFinite(Number(slope))) {
            // Vertical
            dx = 0;
            dy = tickLen / 2;
        } else {
            const m = Number(slope);
            const angle = Math.atan(m);
            dx = (tickLen / 2) * Math.cos(angle);
            dy = (tickLen / 2) * Math.sin(angle);
        }
        // Convert graph deltas to pixels (y inverted)
        const scaleX = plotW / (xMax - xMin || 1);
        const scaleY = plotH / (yMax - yMin || 1);
        const pdx = dx * scaleX;
        const pdy = -dy * scaleY;
        return { x1: cx - pdx, y1: cy - pdy, x2: cx + pdx, y2: cy + pdy, cx, cy };
    }

    function endpointsFromAngle(x, y, angleRad) {
        const cx = xToPx(x);
        const cy = yToPx(y);
        const dx = (tickLen / 2) * Math.cos(angleRad);
        const dy = (tickLen / 2) * Math.sin(angleRad);
        const scaleX = plotW / (xMax - xMin || 1);
        const scaleY = plotH / (yMax - yMin || 1);
        const pdx = dx * scaleX;
        const pdy = -dy * scaleY;
        return { x1: cx - pdx, y1: cy - pdy, x2: cx + pdx, y2: cy + pdy, cx, cy };
    }

    // Build lattice lookup for snapping
    const latticePoints = lattice.map((p) => ({ x: p.x, y: p.y, slope: p.slope, finite: p.finite !== false }));

    function nearestLattice(mx, my) {
        let best = null;
        let bestDist = Infinity;
        for (const p of latticePoints) {
            const dx = p.x - mx;
            const dy = p.y - my;
            const d = dx * dx + dy * dy;
            if (d < bestDist) {
                bestDist = d;
                best = p;
            }
        }
        return best;
    }

    targetEl.innerHTML = '';

    const equationLabel = document.createElement('div');
    equationLabel.className = 'slope-field-equation-label';
    const equationText = config.equation_display
        || (config.equation ? `dy/dx = ${config.equation}` : '');
    equationLabel.textContent = equationText;
    equationLabel.style.cssText = 'padding: 6px 10px 4px; font-size: 0.85rem; font-weight: 600; color: #334155; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; text-align: center; line-height: 1.3;';
    if (equationText) {
        targetEl.appendChild(equationLabel);
    }

    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', String(width));
    svg.setAttribute('height', String(height));
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.style.cssText = 'display:block; width:100%; height:auto; user-select:none;';
    targetEl.appendChild(svg);

    // Plot background
    const bg = document.createElementNS(svgNS, 'rect');
    bg.setAttribute('x', String(padL));
    bg.setAttribute('y', String(padT));
    bg.setAttribute('width', String(plotW));
    bg.setAttribute('height', String(plotH));
    bg.setAttribute('fill', '#ffffff');
    bg.setAttribute('stroke', '#e2e8f0');
    svg.appendChild(bg);

    // Axes (no grid)
    const axisStroke = '#94a3b8';
    if (xMin <= 0 && xMax >= 0) {
        const x0 = xToPx(0);
        const yAxis = document.createElementNS(svgNS, 'line');
        yAxis.setAttribute('x1', String(x0));
        yAxis.setAttribute('y1', String(padT));
        yAxis.setAttribute('x2', String(x0));
        yAxis.setAttribute('y2', String(padT + plotH));
        yAxis.setAttribute('stroke', axisStroke);
        yAxis.setAttribute('stroke-width', '1');
        svg.appendChild(yAxis);
    }
    if (yMin <= 0 && yMax >= 0) {
        const y0 = yToPx(0);
        const xAxis = document.createElementNS(svgNS, 'line');
        xAxis.setAttribute('x1', String(padL));
        xAxis.setAttribute('y1', String(y0));
        xAxis.setAttribute('x2', String(padL + plotW));
        xAxis.setAttribute('y2', String(y0));
        xAxis.setAttribute('stroke', axisStroke);
        xAxis.setAttribute('stroke-width', '1');
        svg.appendChild(xAxis);
    }

    // Axis labels (min/max)
    const labelStyle = { fill: '#64748b', 'font-size': '10px', 'font-family': 'system-ui,sans-serif' };
    function addText(x, y, text, anchor = 'middle') {
        const t = document.createElementNS(svgNS, 'text');
        t.setAttribute('x', String(x));
        t.setAttribute('y', String(y));
        t.setAttribute('text-anchor', anchor);
        t.setAttribute('fill', labelStyle.fill);
        t.setAttribute('font-size', labelStyle['font-size']);
        t.setAttribute('font-family', labelStyle['font-family']);
        t.textContent = text;
        svg.appendChild(t);
    }
    addText(padL, height - 8, String(xMin), 'start');
    addText(padL + plotW, height - 8, String(xMax), 'end');
    addText(8, padT + 4, String(yMax), 'start');
    addText(8, padT + plotH, String(yMin), 'start');

    const selSet = selectedSet();
    const ticksLayer = document.createElementNS(svgNS, 'g');
    ticksLayer.setAttribute('class', 'slope-ticks-layer');
    svg.appendChild(ticksLayer);
    const dotsLayer = document.createElementNS(svgNS, 'g');
    dotsLayer.setAttribute('class', 'slope-dots-layer');
    svg.appendChild(dotsLayer);
    const studentLayer = document.createElementNS(svgNS, 'g');
    studentLayer.setAttribute('class', 'slope-student-layer');
    svg.appendChild(studentLayer);

    function drawAuthorTicks() {
        ticksLayer.innerHTML = '';
        const set = selectedSet();
        for (const p of latticePoints) {
            const ep = tickEndpoints(p.x, p.y, p.slope, p.finite);
            const line = document.createElementNS(svgNS, 'line');
            line.setAttribute('x1', String(ep.x1));
            line.setAttribute('y1', String(ep.y1));
            line.setAttribute('x2', String(ep.x2));
            line.setAttribute('y2', String(ep.y2));
            const marked = isSelected(p.x, p.y, set);
            line.setAttribute('stroke', marked ? '#0f172a' : '#cbd5e1');
            line.setAttribute('stroke-width', marked ? '2.25' : '1.25');
            line.setAttribute('stroke-linecap', 'round');
            line.setAttribute('data-x', String(p.x));
            line.setAttribute('data-y', String(p.y));
            line.setAttribute('pointer-events', 'none');
            ticksLayer.appendChild(line);
        }
    }

    function drawDots() {
        dotsLayer.innerHTML = '';
        const set = selectedSet();
        for (const p of latticePoints) {
            const cx = xToPx(p.x);
            const cy = yToPx(p.y);
            const circle = document.createElementNS(svgNS, 'circle');
            circle.setAttribute('cx', String(cx));
            circle.setAttribute('cy', String(cy));
            circle.setAttribute('r', mode === 'student' && isSelected(p.x, p.y, set) ? '4.5' : '3.25');
            const marked = isSelected(p.x, p.y, set);
            if (mode === 'student') {
                circle.setAttribute('fill', marked ? '#d97706' : '#64748b');
                circle.style.cursor = marked ? 'pointer' : 'default';
            } else {
                circle.setAttribute('fill', marked ? '#0f172a' : '#475569');
                circle.style.cursor = 'pointer';
            }
            circle.setAttribute('data-x', String(p.x));
            circle.setAttribute('data-y', String(p.y));
            circle.setAttribute('data-marked', marked ? '1' : '0');
            circle.setAttribute('class', 'slope-lattice-dot');
            dotsLayer.appendChild(circle);
        }
    }

    if (mode === 'author') {
        drawAuthorTicks();
        drawDots();

        svg.addEventListener('click', (evt) => {
            const dot = evt.target.closest?.('.slope-lattice-dot');
            if (!dot || !svg.contains(dot)) return;
            const x = parseFloat(dot.getAttribute('data-x'));
            const y = parseFloat(dot.getAttribute('data-y'));
            if (!Number.isFinite(x) || !Number.isFinite(y)) return;

            const key = pointKey(x, y);
            const idx = selected.findIndex(([sx, sy]) => pointKey(sx, sy) === key);
            if (idx >= 0) {
                selected.splice(idx, 1);
            } else {
                selected.push([x, y]);
            }
            targetEl.setAttribute('data-selected-points', JSON.stringify(selected));
            drawAuthorTicks();
            drawDots();
            if (typeof options.onSelectionChange === 'function') {
                options.onSelectionChange(selected.slice());
            }
        });
    } else {
        // Student mode: dots only; marked dots interactive
        drawDots();

        /** @type {Map<string, {x:number,y:number,angle:number,el:SVGLineElement}>} */
        const locked = new Map();
        let draft = null; // { x, y, angle, el }

        function removeDraft() {
            if (draft?.el) draft.el.remove();
            draft = null;
        }

        function setDraftLine(x, y, angle) {
            const ep = endpointsFromAngle(x, y, angle);
            if (!draft) {
                const line = document.createElementNS(svgNS, 'line');
                line.setAttribute('stroke', '#2563eb');
                line.setAttribute('stroke-width', '2.5');
                line.setAttribute('stroke-linecap', 'round');
                line.setAttribute('class', 'slope-student-draft');
                studentLayer.appendChild(line);
                draft = { x, y, angle, el: line };
            }
            draft.angle = angle;
            draft.el.setAttribute('x1', String(ep.x1));
            draft.el.setAttribute('y1', String(ep.y1));
            draft.el.setAttribute('x2', String(ep.x2));
            draft.el.setAttribute('y2', String(ep.y2));
        }

        function lockDraft() {
            if (!draft) return;
            const key = pointKey(draft.x, draft.y);
            // Replace any existing lock at this point
            const existing = locked.get(key);
            if (existing?.el) existing.el.remove();

            draft.el.setAttribute('stroke', '#0f172a');
            draft.el.setAttribute('class', 'slope-student-locked');
            draft.el.setAttribute('data-x', String(draft.x));
            draft.el.setAttribute('data-y', String(draft.y));
            draft.el.style.cursor = 'pointer';
            locked.set(key, { x: draft.x, y: draft.y, angle: draft.angle, el: draft.el });
            draft = null;
        }

        function svgPointFromEvent(evt) {
            const pt = svg.createSVGPoint();
            pt.x = evt.clientX;
            pt.y = evt.clientY;
            const ctm = svg.getScreenCTM();
            if (!ctm) return null;
            const local = pt.matrixTransform(ctm.inverse());
            return { px: local.x, py: local.y, x: pxToX(local.x), y: pxToY(local.y) };
        }

        function angleTowardNearest(fromX, fromY, mouseX, mouseY) {
            const near = nearestLattice(mouseX, mouseY);
            if (!near) return 0;
            const dx = near.x - fromX;
            const dy = near.y - fromY;
            if (Math.abs(dx) < 1e-12 && Math.abs(dy) < 1e-12) return 0;
            return Math.atan2(dy, dx);
        }

        svg.addEventListener('mousemove', (evt) => {
            if (!draft) return;
            const p = svgPointFromEvent(evt);
            if (!p) return;
            const angle = angleTowardNearest(draft.x, draft.y, p.x, p.y);
            setDraftLine(draft.x, draft.y, angle);
        });

        svg.addEventListener('click', (evt) => {
            // Remove locked segment if clicked
            const lockedLine = evt.target.closest?.('.slope-student-locked');
            if (lockedLine && studentLayer.contains(lockedLine)) {
                const lx = lockedLine.getAttribute('data-x');
                const ly = lockedLine.getAttribute('data-y');
                locked.delete(pointKey(parseFloat(lx), parseFloat(ly)));
                lockedLine.remove();
                removeDraft();
                evt.stopPropagation();
                return;
            }

            if (draft) {
                // Second click: lock current angle (optionally re-snap on click position)
                const p = svgPointFromEvent(evt);
                if (p) {
                    const angle = angleTowardNearest(draft.x, draft.y, p.x, p.y);
                    setDraftLine(draft.x, draft.y, angle);
                }
                lockDraft();
                return;
            }

            const dot = evt.target.closest?.('.slope-lattice-dot');
            if (!dot || !svg.contains(dot)) return;
            if (dot.getAttribute('data-marked') !== '1') return;

            const x = parseFloat(dot.getAttribute('data-x'));
            const y = parseFloat(dot.getAttribute('data-y'));
            if (!Number.isFinite(x) || !Number.isFinite(y)) return;

            // Start draft horizontal (angle 0)
            const key = pointKey(x, y);
            const existing = locked.get(key);
            if (existing?.el) {
                existing.el.remove();
                locked.delete(key);
            }
            setDraftLine(x, y, 0);
        });
    }
}
