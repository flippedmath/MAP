import { safeNumValue, ensureLatexRenderBox } from './helpers.js';

/**
 * graphBetweenPoints — piecewise graph answer field with optional student-drawn segments.
 */

const SEGMENT_TYPES = [
    { value: 'concave_down_parabola', label: 'concave-down parabola' },
    { value: 'concave_up_parabola', label: 'concave-up parabola' },
    { value: 'line', label: 'line' },
    { value: 'cubic_polynomial', label: 'cubic polynomial' },
];

const START_DIVIDERS = [
    { value: 'none', label: 'none' },
    { value: '<', label: '<' },
    { value: '<=', label: '≤' },
    { value: 'arrow', label: '→' },
];

const END_DIVIDERS = [
    { value: 'none', label: 'none' },
    { value: '>', label: '>' },
    { value: '>=', label: '≥' },
    { value: 'arrow', label: '→' },
];

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

function escapeAttr(val) {
    return String(val ?? '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function getAxisTriple(savedValues, axis) {
    const legacy = savedValues[`${axis}-axis range`];
    if (Array.isArray(legacy) && legacy.length === 3) {
        return [
            safeNumValue(legacy[0], -5),
            safeNumValue(legacy[1], 5),
            safeNumValue(legacy[2], 1),
        ];
    }
    return [
        safeNumValue(savedValues[`${axis}_min`], -5),
        safeNumValue(savedValues[`${axis}_max`], 5),
        safeNumValue(savedValues[`${axis}_step`], 1),
    ];
}

function parsePointInput(raw) {
    if (Array.isArray(raw) && raw.length >= 2) {
        const x = parseFloat(raw[0]);
        const y = parseFloat(raw[1]);
        if (Number.isFinite(x) && Number.isFinite(y)) return [x, y];
        return null;
    }
    const s = String(raw ?? '').trim();
    if (!s) return null;
    const cleaned = s.replace(/^\[/, '').replace(/\]$/, '');
    const parts = cleaned.split(',').map((p) => p.trim());
    if (parts.length < 2) return null;
    const x = parseFloat(parts[0]);
    const y = parseFloat(parts[1]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    return [x, y];
}

function formatPoint(pt) {
    if (!pt || pt.length < 2) return '';
    return `${pt[0]},${pt[1]}`;
}

function pointInBounds(x, y, xMin, xMax, yMin, yMax) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return false;
    if (x < xMin || x > xMax) return false;
    if (y <= yMin || y >= yMax) return false;
    return true;
}

function normalizeSegments(saved) {
    let raw = saved.segments;
    if (typeof raw === 'string') {
        try { raw = JSON.parse(raw); } catch (_) { raw = []; }
    }
    if (!Array.isArray(raw) || !raw.length) {
        return [{
            id: 'seg_1',
            start: [],
            start_divider: 'none',
            type: 'line',
            end_divider: 'none',
            end: [],
            student_draw: false,
        }];
    }
    return raw.map((item, i) => ({
        id: String(item?.id || `seg_${i + 1}`),
        start: Array.isArray(item?.start) ? item.start : parsePointInput(item?.start) || [],
        end: Array.isArray(item?.end) ? item.end : parsePointInput(item?.end) || [],
        start_divider: START_DIVIDERS.some((d) => d.value === item?.start_divider) ? item.start_divider : 'none',
        end_divider: END_DIVIDERS.some((d) => d.value === item?.end_divider) ? item.end_divider : 'none',
        type: SEGMENT_TYPES.some((t) => t.value === item?.type) ? item.type : 'line',
        student_draw: !!item?.student_draw,
    }));
}

function normalizeVertices(saved) {
    let raw = saved.vertices;
    if (typeof raw === 'string') {
        try { raw = JSON.parse(raw); } catch (_) { raw = []; }
    }
    if (!Array.isArray(raw)) return [];
    return raw.map((item, i) => ({
        id: String(item?.id || `vtx_${i + 1}`),
        point: Array.isArray(item?.point) ? item.point : parsePointInput(item?.point) || [],
        segment_id: String(item?.segment_id || ''),
    }));
}

function normalizeSeeds(saved) {
    let raw = saved.curve_seeds;
    if (typeof raw === 'string') {
        try { raw = JSON.parse(raw); } catch (_) { raw = {}; }
    }
    return raw && typeof raw === 'object' ? raw : {};
}

function optionsHtml(list, selected) {
    return list.map((o) => (
        `<option value="${escapeAttr(o.value)}" ${o.value === selected ? 'selected' : ''}>${escapeAttr(o.label)}</option>`
    )).join('');
}

function segmentRowHtml(seg, index, { letStudentDraw, hasVertex }) {
    const startStr = formatPoint(seg.start);
    const endStr = formatPoint(seg.end);
    const drawDisabled = hasVertex;
    const drawChecked = !!seg.student_draw && letStudentDraw && !hasVertex;
    const equation = (seg.equation || '').trim();
    return `
        <div class="gbp-segment-row" data-seg-id="${escapeAttr(seg.id)}" data-row-index="${index}" style="display:flex; flex-direction:column; gap:4px; width:100%; box-sizing:border-box; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:4px; padding:6px 8px;">
            <div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center; width:100%;">
                <span style="font-size:0.68rem; font-weight:700; color:#64748b; min-width:28px;">#${index + 1}</span>
                ${letStudentDraw ? `
                    <label style="font-size:0.68rem; color:#475569; display:inline-flex; align-items:center; gap:4px; ${drawDisabled ? 'opacity:0.45;' : ''}" title="${drawDisabled ? 'Segments with a vertex cannot be student-drawn' : 'Student must draw this segment'}">
                        <input type="checkbox" class="val-gbp-student-draw" ${drawChecked ? 'checked' : ''} ${drawDisabled ? 'disabled' : ''}>
                        student
                    </label>
                ` : ''}
                <input type="text" class="val-gbp-start" value="${escapeAttr(startStr)}" placeholder="x,y" style="width:72px; font-size:0.75rem; padding:3px 4px; border:1px solid #cbd5e1; border-radius:4px;">
                <select class="val-gbp-start-div" style="font-size:0.72rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">${optionsHtml(START_DIVIDERS, seg.start_divider)}</select>
                <select class="val-gbp-type" style="font-size:0.72rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px; max-width:140px;">${optionsHtml(SEGMENT_TYPES, seg.type)}</select>
                <select class="val-gbp-end-div" style="font-size:0.72rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">${optionsHtml(END_DIVIDERS, seg.end_divider)}</select>
                <input type="text" class="val-gbp-end" value="${escapeAttr(endStr)}" placeholder="x,y" style="width:72px; font-size:0.75rem; padding:3px 4px; border:1px solid #cbd5e1; border-radius:4px;">
                <button type="button" class="btn-remove-gbp-seg" title="Remove segment" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem;"><i class="fas fa-minus-circle"></i></button>
            </div>
            <div class="gbp-seg-equation" title="Equation used to render this segment" style="font-size:0.72rem; font-family:ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; color:#334155; background:#eef2ff; border:1px solid #c7d2fe; border-radius:4px; padding:3px 8px; line-height:1.35; word-break:break-word; ${equation ? '' : 'display:none;'}">${escapeAttr(equation || '')}</div>
        </div>
    `;
}

function vertexRowHtml(vtx, segments, allVertices = []) {
    const pt = formatPoint(vtx.point);
    const eligible = assignableSegmentOptions(segments, allVertices, vtx.id);
    const selected = eligible.some((s) => s.id === vtx.segment_id)
        ? vtx.segment_id
        : (eligible[0]?.id || '');
    const opts = eligible.length
        ? eligible.map((s) => {
            const rowNum = segments.findIndex((seg) => seg.id === s.id) + 1;
            return `<option value="${escapeAttr(s.id)}" ${s.id === selected ? 'selected' : ''}>Row #${rowNum}</option>`;
        }).join('')
        : '<option value="">(no parabola/cubic row available)</option>';
    return `
        <div class="gbp-vertex-row" data-vtx-id="${escapeAttr(vtx.id)}" style="display:flex; flex-wrap:wrap; gap:6px; align-items:center; width:100%; box-sizing:border-box; background:#fff7ed; border:1px dashed #fdba74; border-radius:4px; padding:6px 8px;">
            <label style="font-size:0.68rem; color:#9a3412; display:inline-flex; align-items:center; gap:4px;">
                vertex
                <input type="text" class="val-gbp-vertex-point" value="${escapeAttr(pt)}" placeholder="auto" disabled readonly title="Auto-calculated from the selected row" style="width:88px; font-size:0.75rem; padding:3px 4px; border:1px solid #cbd5e1; border-radius:4px; background:#f1f5f9; color:#64748b; cursor:not-allowed;">
            </label>
            <label style="font-size:0.68rem; color:#9a3412; display:inline-flex; align-items:center; gap:4px;">
                row #
                <select class="val-gbp-vertex-seg" style="font-size:0.72rem; padding:3px; border:1px solid #fdba74; border-radius:4px;">${opts}</select>
            </label>
            <button type="button" class="btn-remove-gbp-vtx" title="Remove vertex" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size:0.85rem;"><i class="fas fa-minus-circle"></i></button>
        </div>
    `;
}

/** Segments that can receive a vertex assignment (parabola/cubic with endpoints). */
function assignableSegmentOptions(segments, allVertices = [], currentVtxId = null) {
    const counts = {};
    (allVertices || []).forEach((v) => {
        if (!v?.segment_id) return;
        if (currentVtxId && v.id === currentVtxId) return;
        counts[v.segment_id] = (counts[v.segment_id] || 0) + 1;
    });
    return segments.filter((s) => {
        if (s.type === 'line') return false;
        if (!Array.isArray(s.start) || s.start.length < 2 || !Array.isArray(s.end) || s.end.length < 2) {
            return false;
        }
        const used = counts[s.id] || 0;
        if (s.type === 'concave_down_parabola' || s.type === 'concave_up_parabola') {
            return used < 1;
        }
        if (s.type === 'cubic_polynomial') {
            return used < 2;
        }
        return false;
    });
}

function coveringSegmentOptions(point, segments) {
    const pt = Array.isArray(point) && point.length >= 2 ? point : parsePointInput(point);
    if (!pt) return [];
    const [vx] = pt;
    return segments.filter((s) => {
        if (s.type === 'line') return false;
        if (!Array.isArray(s.start) || s.start.length < 2 || !Array.isArray(s.end) || s.end.length < 2) return false;
        const x1 = Number(s.start[0]);
        const x2 = Number(s.end[0]);
        if (!Number.isFinite(x1) || !Number.isFinite(x2)) return false;
        const lo = Math.min(x1, x2);
        const hi = Math.max(x1, x2);
        return vx >= lo && vx <= hi;
    });
}

/** Client-side polyline samples for student preview (no vertex → mid-ish synthesis). */
function sampleStudentSegment(seg, bounds) {
    const start = Array.isArray(seg.start) && seg.start.length >= 2 ? seg.start : null;
    const end = Array.isArray(seg.end) && seg.end.length >= 2 ? seg.end : null;
    if (!start || !end) return [];
    const x1 = Number(start[0]);
    const y1 = Number(start[1]);
    const x2 = Number(end[0]);
    const y2 = Number(end[1]);
    if (![x1, y1, x2, y2].every(Number.isFinite)) return [];

    const type = seg.type || 'line';
    const n = 48;
    const samples = [];
    const lerp = (a, b, t) => a + (b - a) * t;

    if (type === 'line') {
        for (let i = 0; i < n; i += 1) {
            const t = i / (n - 1);
            samples.push([lerp(x1, x2, t), lerp(y1, y2, t)]);
        }
        return samples;
    }

    const xMin = Number(bounds?.xMin);
    const xMax = Number(bounds?.xMax);
    const yMin = Number(bounds?.yMin);
    const yMax = Number(bounds?.yMax);
    const lo = Math.min(x1, x2);
    const hi = Math.max(x1, x2);
    const span = hi - lo || 1;

    if (type === 'concave_down_parabola' || type === 'concave_up_parabola') {
        // Place vertex so concavity matches the selected type (not a fixed 40% x).
        const mid = (x1 + x2) / 2;
        const higherX = y1 >= y2 ? x1 : x2;
        const lowerX = y1 < y2 ? x1 : x2;
        let h;
        let k;
        let a;

        if (Math.abs(y1 - y2) < 1e-9) {
            // Level chord: only midpoint x yields a real vertical parabola.
            h = mid;
            if (Number.isFinite(xMin) && Number.isFinite(xMax)) {
                h = Math.min(Math.max(h, xMin), xMax);
            }
            const chordY = y1;
            if (type === 'concave_down_parabola') {
                const room = Number.isFinite(yMax) ? (yMax - chordY) * 0.55 : Math.abs(span) * 0.4;
                k = chordY + Math.max(0.35, room * 0.7);
                if (Number.isFinite(yMax)) k = Math.min(k, yMax - 0.05);
            } else {
                const room = Number.isFinite(yMin) ? (chordY - yMin) * 0.55 : Math.abs(span) * 0.4;
                k = chordY - Math.max(0.35, room * 0.7);
                if (Number.isFinite(yMin)) k = Math.max(k, yMin + 0.05);
            }
            const d = (x1 - h) ** 2 || 1;
            a = (chordY - k) / d;
        } else {
            // Closer to higher endpoint → concave down; closer to lower → concave up.
            const targetX = type === 'concave_down_parabola' ? higherX : lowerX;
            h = mid + 0.55 * (targetX - mid);
            h = Math.min(Math.max(h, lo + 0.08 * span), hi - 0.08 * span);
            if (Number.isFinite(xMin) && Number.isFinite(xMax)) {
                h = Math.min(Math.max(h, xMin), xMax);
            }
            const d1 = (x1 - h) ** 2;
            const d2 = (x2 - h) ** 2;
            if (Math.abs(d1 - d2) < 1e-9) {
                a = type === 'concave_down_parabola' ? -0.2 : 0.2;
                k = y1 - a * d1;
            } else {
                a = (y1 - y2) / (d1 - d2);
                k = y1 - a * d1;
            }
            // If float/clamp flipped the sign, mirror toward the other side of mid.
            const wantDown = type === 'concave_down_parabola';
            if ((wantDown && a >= 0) || (!wantDown && a <= 0)) {
                h = mid - 0.55 * (h - mid);
                h = Math.min(Math.max(h, lo + 0.08 * span), hi - 0.08 * span);
                const e1 = (x1 - h) ** 2;
                const e2 = (x2 - h) ** 2;
                if (Math.abs(e1 - e2) >= 1e-9) {
                    a = (y1 - y2) / (e1 - e2);
                    k = y1 - a * e1;
                }
            }
        }
        for (let i = 0; i < n; i += 1) {
            const t = i / (n - 1);
            const x = lerp(lo, hi, t);
            samples.push([x, a * (x - h) ** 2 + k]);
        }
        return samples;
    }

    if (type === 'cubic_polynomial') {
        // Smooth cubic wiggle between endpoints (two interior extrema vibe)
        const midY = (y1 + y2) / 2;
        const amp = Math.max(0.6, Math.abs(y2 - y1) * 0.45 + Math.abs(span) * 0.15);
        let sign = 1;
        if (Number.isFinite(yMax) && midY + amp >= yMax) sign = -1;
        if (Number.isFinite(yMin) && midY - amp <= yMin) sign = 1;
        for (let i = 0; i < n; i += 1) {
            const t = i / (n - 1);
            const x = lerp(x1, x2, t);
            const base = lerp(y1, y2, t);
            // sin(2πt) gives one full up-down between ends
            const y = base + sign * amp * Math.sin(2 * Math.PI * t);
            samples.push([x, y]);
        }
        return samples;
    }

    for (let i = 0; i < n; i += 1) {
        const t = i / (n - 1);
        samples.push([lerp(x1, x2, t), lerp(y1, y2, t)]);
    }
    return samples;
}

function markerKindFromDivider(side, divider) {
    if (divider === 'arrow') return 'arrow';
    if (side === 'start') {
        if (divider === '<') return 'open';
        if (divider === '<=') return 'filled';
    } else {
        if (divider === '>') return 'open';
        if (divider === '>=') return 'filled';
    }
    return null;
}

function getFieldsHtml(savedValues) {
    const [xMin, xMax, xStep] = getAxisTriple(savedValues, 'x');
    const [yMin, yMax, yStep] = getAxisTriple(savedValues, 'y');
    const showGrid = savedValues.show_grid !== false;
    const letStudentDraw = !!savedValues.let_student_draw;
    const segments = normalizeSegments(savedValues);
    const vertices = normalizeVertices(savedValues);
    const seeds = normalizeSeeds(savedValues);
    const vtxBySeg = {};
    vertices.forEach((v) => {
        if (v.segment_id) vtxBySeg[v.segment_id] = true;
    });

    return `
        <div class="gbp-fields" style="display:flex; flex-direction:column; gap:10px; width:100%; box-sizing:border-box;">
            <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
                <label style="font-size:0.75rem; color:#475569; display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
                    <input type="checkbox" class="val-gbp-show-grid" ${showGrid ? 'checked' : ''}> Visualize Grid Layout
                </label>
                <label style="font-size:0.75rem; color:#475569; display:inline-flex; align-items:center; gap:6px; cursor:pointer;">
                    <input type="checkbox" class="val-gbp-let-student-draw" ${letStudentDraw ? 'checked' : ''}> Let student draw
                </label>
            </div>

            <div style="display:flex; flex-direction:column; gap:4px; border-top:1px dashed #cbd5e1; padding-top:6px;">
                <span style="font-size:0.72rem; font-weight:600; color:#64748b;">Axis Limits (min / max / step):</span>
                <div style="display:grid; grid-template-columns:45px repeat(3,1fr); gap:6px; align-items:center;">
                    <span style="font-size:0.75rem; color:#475569; font-weight:500;">X-Axis:</span>
                    <input type="number" step="any" class="val-gbp-x-min" value="${xMin}" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    <input type="number" step="any" class="val-gbp-x-max" value="${xMax}" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    <input type="number" step="any" class="val-gbp-x-step" value="${xStep}" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                </div>
                <div style="display:grid; grid-template-columns:45px repeat(3,1fr); gap:6px; align-items:center;">
                    <span style="font-size:0.75rem; color:#475569; font-weight:500;">Y-Axis:</span>
                    <input type="number" step="any" class="val-gbp-y-min" value="${yMin}" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    <input type="number" step="any" class="val-gbp-y-max" value="${yMax}" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                    <input type="number" step="any" class="val-gbp-y-step" value="${yStep}" style="width:100%; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                </div>
            </div>

            <div style="display:flex; flex-direction:column; gap:6px;">
                <span style="font-size:0.75rem; font-weight:600; color:#475569;">Graph segments:</span>
                <div class="gbp-segments-container" style="display:flex; flex-direction:column; gap:6px;">
                    ${segments.map((s, i) => segmentRowHtml(s, i, { letStudentDraw, hasVertex: !!vtxBySeg[s.id] })).join('')}
                </div>
                <button type="button" class="btn-add-gbp-seg" style="align-self:flex-start; background:#f1f5f9; border:1px dashed #cbd5e1; border-radius:4px; color:#475569; font-size:0.72rem; padding:3px 8px; cursor:pointer;">
                    <i class="fas fa-plus"></i> Add graph segment
                </button>
            </div>

            <div style="display:flex; flex-direction:column; gap:6px;">
                <span style="font-size:0.75rem; font-weight:600; color:#475569;">Vertices (optional):</span>
                <div class="gbp-vertices-container" style="display:flex; flex-direction:column; gap:6px;">
                    ${vertices.map((v) => vertexRowHtml(v, segments, vertices)).join('')}
                </div>
                <button type="button" class="btn-add-gbp-vtx" style="align-self:flex-start; background:#fff7ed; border:1px dashed #fdba74; border-radius:4px; color:#9a3412; font-size:0.72rem; padding:3px 8px; cursor:pointer;">
                    <i class="fas fa-plus"></i> Add vertex
                </button>
                <span style="font-size:0.68rem; color:#94a3b8;">Pick a parabola/cubic row — the vertex coordinate is calculated automatically (lattice when possible).</span>
            </div>

            <input type="hidden" class="val-gbp-curve-seeds" value='${escapeAttr(JSON.stringify(seeds))}'>
            <div class="gbp-card-host" style="width:100%; min-height:220px; background:#fff; border:1px solid #e2e8f0; border-radius:4px;"></div>
            <span style="font-size:0.68rem; color:#94a3b8;">Coords must be strictly inside the y-range; x may sit on x min/max. Invalid points clear automatically.</span>
        </div>
    `;
}

function readAxis(card) {
    return {
        xMin: parseFloat(card.querySelector('.val-gbp-x-min')?.value),
        xMax: parseFloat(card.querySelector('.val-gbp-x-max')?.value),
        xStep: parseFloat(card.querySelector('.val-gbp-x-step')?.value),
        yMin: parseFloat(card.querySelector('.val-gbp-y-min')?.value),
        yMax: parseFloat(card.querySelector('.val-gbp-y-max')?.value),
        yStep: parseFloat(card.querySelector('.val-gbp-y-step')?.value),
    };
}

function collectSegmentsFromDom(card) {
    return Array.from(card.querySelectorAll('.gbp-segment-row')).map((row, i) => {
        const start = parsePointInput(row.querySelector('.val-gbp-start')?.value);
        const end = parsePointInput(row.querySelector('.val-gbp-end')?.value);
        return {
            id: row.getAttribute('data-seg-id') || `seg_${i + 1}`,
            start: start || [],
            end: end || [],
            start_divider: row.querySelector('.val-gbp-start-div')?.value || 'none',
            end_divider: row.querySelector('.val-gbp-end-div')?.value || 'none',
            type: row.querySelector('.val-gbp-type')?.value || 'line',
            student_draw: !!row.querySelector('.val-gbp-student-draw')?.checked,
        };
    });
}

function collectVerticesFromDom(card) {
    return Array.from(card.querySelectorAll('.gbp-vertex-row')).map((row, i) => ({
        id: row.getAttribute('data-vtx-id') || `vtx_${i + 1}`,
        point: parsePointInput(row.querySelector('.val-gbp-vertex-point')?.value) || [],
        segment_id: row.querySelector('.val-gbp-vertex-seg')?.value || '',
    }));
}

function syncStudentDrawPts(card) {
    const letDraw = !!card.querySelector('.val-gbp-let-student-draw')?.checked;
    const segs = collectSegmentsFromDom(card);
    const n = letDraw ? segs.filter((s) => s.student_draw).length : 0;
    const ptsInput = card.querySelector('.val-answer-field-points');
    if (letDraw && ptsInput && n > 0) {
        ptsInput.value = String(n);
        card.setAttribute('data-points', String(n));
    }
}

function sanitizeCardCoords(card) {
    const axis = readAxis(card);
    if (![axis.xMin, axis.xMax, axis.yMin, axis.yMax].every(Number.isFinite)) return;

    card.querySelectorAll('.gbp-segment-row').forEach((row) => {
        ['.val-gbp-start', '.val-gbp-end'].forEach((sel) => {
            const input = row.querySelector(sel);
            if (!input) return;
            const pt = parsePointInput(input.value);
            if (!pt) return;
            if (!pointInBounds(pt[0], pt[1], axis.xMin, axis.xMax, axis.yMin, axis.yMax)) {
                input.value = '';
            }
        });
    });
}

function refreshVertexDropdowns(card) {
    const segments = collectSegmentsFromDom(card);
    const allVertices = collectVerticesFromDom(card);
    const vtxBySeg = {};

    card.querySelectorAll('.gbp-vertex-row').forEach((row) => {
        const vtxId = row.getAttribute('data-vtx-id');
        const sel = row.querySelector('.val-gbp-vertex-seg');
        if (!sel) return;

        const eligible = assignableSegmentOptions(segments, allVertices, vtxId);
        if (!eligible.length) {
            // No eligible row left — drop this vertex assignment
            row.remove();
            return;
        }
        const current = sel.value;
        const chosen = eligible.some((c) => c.id === current) ? current : eligible[0].id;
        sel.innerHTML = eligible.map((s) => {
            const rowNum = segments.findIndex((seg) => seg.id === s.id) + 1;
            return `<option value="${escapeAttr(s.id)}" ${s.id === chosen ? 'selected' : ''}>Row #${rowNum}</option>`;
        }).join('');
        vtxBySeg[chosen] = true;
        // Keep point field disabled; server sync fills the value
        const ptInput = row.querySelector('.val-gbp-vertex-point');
        if (ptInput) {
            ptInput.disabled = true;
            ptInput.readOnly = true;
        }
    });

    const letDraw = !!card.querySelector('.val-gbp-let-student-draw')?.checked;
    card.querySelectorAll('.gbp-segment-row').forEach((row) => {
        const sid = row.getAttribute('data-seg-id');
        const cb = row.querySelector('.val-gbp-student-draw');
        const label = cb?.closest('label');
        if (!cb) return;
        if (!letDraw) {
            cb.closest('label')?.remove();
            return;
        }
        const hasVtx = !!vtxBySeg[sid];
        cb.disabled = hasVtx;
        if (hasVtx) cb.checked = false;
        if (label) label.style.opacity = hasVtx ? '0.45' : '1';
    });
}

function reindexSegmentLabels(card) {
    card.querySelectorAll('.gbp-segment-row').forEach((row, i) => {
        row.setAttribute('data-row-index', String(i));
        const label = row.querySelector('span');
        if (label && label.textContent.startsWith('#')) label.textContent = `#${i + 1}`;
    });
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;
    sanitizeCardCoords(card);
    const axis = readAxis(card);
    inputsCollected.show_grid = !!card.querySelector('.val-gbp-show-grid')?.checked;
    inputsCollected.let_student_draw = !!card.querySelector('.val-gbp-let-student-draw')?.checked;
    inputsCollected['x-axis range'] = [axis.xMin, axis.xMax, axis.xStep];
    inputsCollected['y-axis range'] = [axis.yMin, axis.yMax, axis.yStep];
    inputsCollected.x_min = axis.xMin;
    inputsCollected.x_max = axis.xMax;
    inputsCollected.x_step = axis.xStep;
    inputsCollected.y_min = axis.yMin;
    inputsCollected.y_max = axis.yMax;
    inputsCollected.y_step = axis.yStep;

    let segments = collectSegmentsFromDom(card);
    // Vertices are row assignments only — point is filled by the server
    let vertices = collectVerticesFromDom(card)
        .filter((v) => v.segment_id)
        .map((v) => ({
            id: v.id,
            segment_id: v.segment_id,
            point: Array.isArray(v.point) && v.point.length >= 2 ? v.point : [],
        }));

    const vtxSegs = new Set(vertices.map((v) => v.segment_id));
    segments = segments.map((s) => ({
        ...s,
        student_draw: inputsCollected.let_student_draw && !!s.student_draw && !vtxSegs.has(s.id),
    }));

    let seeds = {};
    try {
        seeds = JSON.parse(card.querySelector('.val-gbp-curve-seeds')?.value || '{}') || {};
    } catch (_) { seeds = {}; }
    segments.forEach((s) => {
        if (seeds[s.id] == null) seeds[s.id] = Math.floor(Math.random() * 1e9);
    });
    const seedInput = card.querySelector('.val-gbp-curve-seeds');
    if (seedInput) seedInput.value = JSON.stringify(seeds);

    inputsCollected.segments = segments;
    inputsCollected.vertices = vertices;
    inputsCollected.curve_seeds = seeds;
    return inputsCollected;
}

function bindEvents({ card, updateWorkspaceSimulationPreview, dispatchWorkspaceBatchSync }) {
    if (!card || card.dataset.gbpBound === '1') return true;
    card.dataset.gbpBound = '1';

    const bump = () => {
        sanitizeCardCoords(card);
        refreshVertexDropdowns(card);
        syncStudentDrawPts(card);
        const probe = card.querySelector('.val-gbp-show-grid') || card;
        probe.dispatchEvent(new Event('input', { bubbles: true }));
        const id = card.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
        if (id && typeof dispatchWorkspaceBatchSync === 'function') {
            dispatchWorkspaceBatchSync(id);
        } else if (typeof updateWorkspaceSimulationPreview === 'function') {
            updateWorkspaceSimulationPreview();
        }
    };

    const axisSnapshot = () => ({ ...readAxis(card) });
    let lastGoodAxis = axisSnapshot();

    card.addEventListener('change', (e) => {
        if (e.target.classList.contains('val-gbp-let-student-draw')) {
            // Rebuild segment rows to show/hide student checkboxes
            const segs = collectSegmentsFromDom(card);
            const verts = collectVerticesFromDom(card);
            const vtxBySeg = {};
            verts.forEach((v) => { if (v.segment_id) vtxBySeg[v.segment_id] = true; });
            const letDraw = e.target.checked;
            const container = card.querySelector('.gbp-segments-container');
            if (container) {
                container.innerHTML = segs.map((s, i) => segmentRowHtml(s, i, {
                    letStudentDraw: letDraw,
                    hasVertex: !!vtxBySeg[s.id],
                })).join('');
            }
            syncStudentDrawPts(card);
            bump();
            return;
        }
        if (['val-gbp-x-min', 'val-gbp-x-max', 'val-gbp-y-min', 'val-gbp-y-max', 'val-gbp-x-step', 'val-gbp-y-step']
            .some((c) => e.target.classList.contains(c))) {
            const axis = readAxis(card);
            const segs = collectSegmentsFromDom(card);
            const verts = collectVerticesFromDom(card);
            const pts = [
                ...segs.flatMap((s) => [s.start, s.end]),
                ...verts.map((v) => v.point),
            ].filter((p) => Array.isArray(p) && p.length >= 2);
            const ok = pts.every((p) => pointInBounds(p[0], p[1], axis.xMin, axis.xMax, axis.yMin, axis.yMax));
            if (!ok || !(axis.xMin < axis.xMax) || !(axis.yMin < axis.yMax)) {
                // Revert axis fields
                card.querySelector('.val-gbp-x-min').value = lastGoodAxis.xMin;
                card.querySelector('.val-gbp-x-max').value = lastGoodAxis.xMax;
                card.querySelector('.val-gbp-x-step').value = lastGoodAxis.xStep;
                card.querySelector('.val-gbp-y-min').value = lastGoodAxis.yMin;
                card.querySelector('.val-gbp-y-max').value = lastGoodAxis.yMax;
                card.querySelector('.val-gbp-y-step').value = lastGoodAxis.yStep;
                return;
            }
            lastGoodAxis = axisSnapshot();
        }
        bump();
    });

    card.addEventListener('input', (e) => {
        if (e.target.classList.contains('val-gbp-start')
            || e.target.classList.contains('val-gbp-end')
            || e.target.classList.contains('val-gbp-vertex-point')) {
            // Debounced clear of illegal coords handled on blur/change via bump
        }
    });

    card.addEventListener('focusout', (e) => {
        if (e.target.classList.contains('val-gbp-start')
            || e.target.classList.contains('val-gbp-end')) {
            sanitizeCardCoords(card);
            refreshVertexDropdowns(card);
            bump();
        }
    });

    card.addEventListener('click', (e) => {
        if (e.target.closest('.btn-add-gbp-seg')) {
            e.preventDefault();
            const container = card.querySelector('.gbp-segments-container');
            const letDraw = !!card.querySelector('.val-gbp-let-student-draw')?.checked;
            const idx = container.querySelectorAll('.gbp-segment-row').length;
            const seg = {
                id: `seg_${Date.now()}`,
                start: [],
                end: [],
                start_divider: 'none',
                end_divider: 'none',
                type: 'line',
                student_draw: false,
            };
            container.insertAdjacentHTML('beforeend', segmentRowHtml(seg, idx, { letStudentDraw: letDraw, hasVertex: false }));
            bump();
            return;
        }
        if (e.target.closest('.btn-remove-gbp-seg')) {
            e.preventDefault();
            const row = e.target.closest('.gbp-segment-row');
            const sid = row?.getAttribute('data-seg-id');
            row?.remove();
            // Cascade delete vertices
            card.querySelectorAll('.gbp-vertex-row').forEach((vrow) => {
                if (vrow.querySelector('.val-gbp-vertex-seg')?.value === sid) vrow.remove();
            });
            reindexSegmentLabels(card);
            refreshVertexDropdowns(card);
            bump();
            return;
        }
        if (e.target.closest('.btn-add-gbp-vtx')) {
            e.preventDefault();
            const container = card.querySelector('.gbp-vertices-container');
            const segments = collectSegmentsFromDom(card);
            const existing = collectVerticesFromDom(card);
            const eligible = assignableSegmentOptions(segments, existing, null);
            if (!eligible.length) {
                return;
            }
            const vtx = {
                id: `vtx_${Date.now()}`,
                point: [],
                segment_id: eligible[0].id,
            };
            container.insertAdjacentHTML('beforeend', vertexRowHtml(vtx, segments, [...existing, vtx]));
            bump();
            return;
        }
        if (e.target.closest('.btn-remove-gbp-vtx')) {
            e.preventDefault();
            e.target.closest('.gbp-vertex-row')?.remove();
            refreshVertexDropdowns(card);
            bump();
        }
    });

    return true;
}

function parseManifest(result) {
    const raw = result?.evaluated_output || result?.latex_output || '';
    if (typeof raw !== 'string') return null;
    try {
        const parsed = JSON.parse(raw);
        return parsed?.archetype === 'graphBetweenPoints' ? parsed : null;
    } catch (_) {
        return null;
    }
}

function applyBatchSync({ card, result }) {
    if (!card || !result) return null;
    const targetDisplay = ensureLatexRenderBox(card);
    if (targetDisplay) {
        targetDisplay.style.textAlign = 'center';
        targetDisplay.style.fontSize = '0.85rem';
        targetDisplay.style.fontWeight = '600';
        const out = result.evaluated_output;
        if (String(out || '').startsWith('[Invalid') || String(out || '').startsWith('⚠️')) {
            targetDisplay.textContent = '';
        } else {
            targetDisplay.textContent = '[Graph Between Points]';
        }
    }

    const manifest = parseManifest(result);
    const host = card.querySelector('.gbp-card-host');
    if (host && manifest) {
        renderGraphBetweenPointsCanvas(host, manifest, { mode: 'author', width: 340, height: 240 });
    }
    // Keep seeds from server
    if (manifest?.curve_seeds) {
        const seedInput = card.querySelector('.val-gbp-curve-seeds');
        if (seedInput) seedInput.value = JSON.stringify(manifest.curve_seeds);
    }
    // Sync vertex inputs when server snapped/replaced a peak to match the drawn curve
    if (manifest && Array.isArray(manifest.vertices)) {
        const bySeg = {};
        manifest.vertices.forEach((v) => {
            if (v && v.segment_id && Array.isArray(v.point) && v.point.length >= 2) {
                bySeg[v.segment_id] = v.point;
            }
        });
        card.querySelectorAll('.gbp-vertex-row').forEach((row) => {
            const sid = row.querySelector('.val-gbp-vertex-seg')?.value;
            const pt = sid ? bySeg[sid] : null;
            if (!pt) return;
            const input = row.querySelector('.val-gbp-vertex-point');
            if (input) input.value = `${pt[0]},${pt[1]}`;
        });
    }
    // Show the equation actually used to render each segment
    const outStr = String(result.evaluated_output || '');
    const invalid = outStr.startsWith('[Invalid') || outStr.startsWith('⚠️') || !manifest;
    if (invalid) {
        card.querySelectorAll('.gbp-seg-equation').forEach((el) => {
            el.textContent = '';
            el.style.display = 'none';
        });
    } else {
        const eqById = {};
        (manifest.segments || []).forEach((s) => {
            if (s && s.id) eqById[s.id] = (s.equation || '').trim();
        });
        card.querySelectorAll('.gbp-segment-row').forEach((row) => {
            const sid = row.getAttribute('data-seg-id');
            const el = row.querySelector('.gbp-seg-equation');
            if (!el) return;
            const eq = sid ? (eqById[sid] || '') : '';
            el.textContent = eq;
            el.style.display = eq ? '' : 'none';
        });
    }
    return true;
}

function renderPreviewToken(contextData = {}) {
    const {
        cleanToken,
        card,
        displayVal,
        initialValue,
        registerPreviewGraph,
        previewInstanceId,
    } = contextData;

    let config = null;
    const raw = displayVal || card?.getAttribute('data-simulated-value') || '';
    if (typeof raw === 'string' && raw.trim().startsWith('{')) {
        try { config = JSON.parse(raw); } catch (_) { config = null; }
    }
    if (!config || config.archetype !== 'graphBetweenPoints') {
        return `
            <div class="simulated-gbp-wrapper" data-token="${escapeAttr(cleanToken || '')}" style="display:block; margin:6px 0; padding:8px; border:1px dashed #cbd5e1; border-radius:4px; color:#94a3b8; font-size:0.8rem;">
                Graph Between Points preview loading…
            </div>
        `;
    }

    const canvasId = previewInstanceId || `gbp-preview-${cleanToken}-${Math.random().toString(36).slice(2, 8)}`;
    if (typeof registerPreviewGraph === 'function') {
        registerPreviewGraph({
            canvasId,
            graphConfig: config,
            cleanToken,
            kind: 'graphBetweenPoints',
            width: 340,
            height: 240,
            initialValue: initialValue && typeof initialValue === 'object' ? initialValue : null,
        });
    }

    const showStudentUi = !!config.let_student_draw && Array.isArray(config.student_targets) && config.student_targets.length > 0;
    return `
        <div class="simulated-gbp-wrapper" data-token="${escapeAttr(cleanToken || '')}" style="display:block; width:100%; max-width:420px; margin:8px 0; box-sizing:border-box;">
            <div id="${escapeAttr(canvasId)}" class="live-preview-gbp-canvas" style="width:100%; min-height:220px; background:#fff; border:1px solid #e2e8f0; border-radius:4px;"></div>
            ${showStudentUi ? `
                <div class="gbp-student-segments" data-token="${escapeAttr(cleanToken || '')}" style="display:flex; flex-direction:column; gap:6px; margin-top:8px;"></div>
                <button type="button" class="btn-gbp-add-student-seg" data-token="${escapeAttr(cleanToken || '')}" style="margin-top:6px; font-size:0.75rem; padding:4px 8px; border:1px dashed #94a3b8; border-radius:4px; background:#fff; color:#334155; cursor:pointer;">Add graph segment</button>
            ` : ''}
        </div>
    `;
}

/**
 * Paint axes + polylines + endpoint markers into targetEl.
 */
export function renderGraphBetweenPointsCanvas(targetEl, config, options = {}) {
    if (!targetEl || !config || config.archetype !== 'graphBetweenPoints') return;

    const mode = options.mode || 'author';
    const width = Math.max(160, Math.round(options.width || 340));
    const height = Math.max(140, Math.round(options.height || 240));
    const padL = 36;
    const padR = 14;
    const padT = 14;
    const padB = 28;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    const xr = config.bounds?.x_range || { min: -5, max: 5, step: 1 };
    const yr = config.bounds?.y_range || { min: -5, max: 5, step: 1 };
    const xMin = Number(xr.min);
    const xMax = Number(xr.max);
    const yMin = Number(yr.min);
    const yMax = Number(yr.max);
    const xStep = Number(xr.step) || 1;
    const yStep = Number(yr.step) || 1;
    const showGrid = config.visualization?.show_grid_overlay !== false;

    const sx = (x) => padL + ((x - xMin) / (xMax - xMin || 1)) * plotW;
    const sy = (y) => padT + ((yMax - y) / (yMax - yMin || 1)) * plotH;

    const ticksX = [];
    for (let x = xMin; x <= xMax + 1e-9; x += xStep) ticksX.push(Number(x.toFixed(8)));
    const ticksY = [];
    for (let y = yMin; y <= yMax + 1e-9; y += yStep) ticksY.push(Number(y.toFixed(8)));

    let grid = '';
    if (showGrid) {
        grid = ticksX.map((x) => `<line x1="${sx(x)}" y1="${padT}" x2="${sx(x)}" y2="${padT + plotH}" stroke="#e2e8f0" stroke-width="1"/>`).join('')
            + ticksY.map((y) => `<line x1="${padL}" y1="${sy(y)}" x2="${padL + plotW}" y2="${sy(y)}" stroke="#e2e8f0" stroke-width="1"/>`).join('');
    }

    const axis = `
        <line x1="${padL}" y1="${sy(0)}" x2="${padL + plotW}" y2="${sy(0)}" stroke="#0f172a" stroke-width="1.5"/>
        <line x1="${sx(0)}" y1="${padT}" x2="${sx(0)}" y2="${padT + plotH}" stroke="#0f172a" stroke-width="1.5"/>
        <text x="${padL + plotW + 4}" y="${sy(0) + 4}" font-size="11" fill="#334155">x</text>
        <text x="${sx(0) + 4}" y="${padT + 10}" font-size="11" fill="#334155">y</text>
    `;

    const tickLabels = ticksX.map((x) => (
        `<text x="${sx(x)}" y="${padT + plotH + 14}" font-size="9" text-anchor="middle" fill="#64748b">${x}</text>`
    )).join('') + ticksY.map((y) => (
        `<text x="${padL - 4}" y="${sy(y) + 3}" font-size="9" text-anchor="end" fill="#64748b">${y}</text>`
    )).join('');

    const segsToDraw = mode === 'student'
        ? (config.author_visible || [])
        : (config.segments || config.author_visible || []);

    // Student overlays from options.studentSegments
    const studentSegs = Array.isArray(options.studentSegments) ? options.studentSegments : [];

    const pathFor = (samples, color) => {
        if (!Array.isArray(samples) || samples.length < 2) return '';
        const d = samples.map((p, i) => `${i === 0 ? 'M' : 'L'}${sx(p[0]).toFixed(2)},${sy(p[1]).toFixed(2)}`).join(' ');
        return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;
    };

    const tangentUnitScreen = (samples, which) => {
        if (!Array.isArray(samples) || samples.length < 2) return null;
        const n = samples.length;
        let i0;
        let i1;
        if (which === 'start') {
            i0 = 0;
            i1 = 1;
            while (i1 < n - 1) {
                const dx = samples[i1][0] - samples[i0][0];
                const dy = samples[i1][1] - samples[i0][1];
                if (Math.hypot(dx, dy) > 1e-9) break;
                i1 += 1;
            }
        } else {
            i1 = n - 1;
            i0 = n - 2;
            while (i0 > 0) {
                const dx = samples[i1][0] - samples[i0][0];
                const dy = samples[i1][1] - samples[i0][1];
                if (Math.hypot(dx, dy) > 1e-9) break;
                i0 -= 1;
            }
        }
        const ax = sx(samples[i0][0]);
        const ay = sy(samples[i0][1]);
        const bx = sx(samples[i1][0]);
        const by = sy(samples[i1][1]);
        let dx = bx - ax;
        let dy = by - ay;
        const len = Math.hypot(dx, dy);
        if (len < 1e-6) return null;
        return { ux: dx / len, uy: dy / len };
    };

    const markersFor = (seg, color) => {
        const m = seg.markers || {};
        const start = seg.start || samplesFirst(seg);
        const end = seg.end || samplesLast(seg);
        const samples = Array.isArray(seg.samples) && seg.samples.length >= 2
            ? seg.samples
            : (start && end ? [start, end] : null);
        let html = '';
        const drawMark = (pt, kind, which) => {
            if (!pt || pt.length < 2 || !kind) return '';
            const cx = sx(pt[0]);
            const cy = sy(pt[1]);
            if (kind === 'filled') {
                return `<circle cx="${cx}" cy="${cy}" r="4.5" fill="${color}" stroke="${color}"/>`;
            }
            if (kind === 'open') {
                return `<circle cx="${cx}" cy="${cy}" r="4.5" fill="#fff" stroke="${color}" stroke-width="2"/>`;
            }
            if (kind === 'arrow') {
                const tan = tangentUnitScreen(samples, which);
                if (!tan) return '';
                const arrowLen = 11;
                const halfW = 5;
                const tipX = cx;
                const tipY = cy;
                // Tip at endpoint, pointing opposite sample travel
                // (180° from the previous orientation).
                const baseX = tipX + tan.ux * arrowLen;
                const baseY = tipY + tan.uy * arrowLen;
                const px = -tan.uy * halfW;
                const py = tan.ux * halfW;
                const p1x = (baseX + px).toFixed(2);
                const p1y = (baseY + py).toFixed(2);
                const p2x = (baseX - px).toFixed(2);
                const p2y = (baseY - py).toFixed(2);
                return `<polygon points="${tipX.toFixed(2)},${tipY.toFixed(2)} ${p1x},${p1y} ${p2x},${p2y}" fill="${color}" stroke="${color}" stroke-width="1" stroke-linejoin="round"/>`;
            }
            return '';
        };
        html += drawMark(start, m.start, 'start');
        html += drawMark(end, m.end, 'end');
        return html;
    };

    function samplesFirst(seg) {
        return Array.isArray(seg.samples) && seg.samples[0] ? seg.samples[0] : seg.start;
    }
    function samplesLast(seg) {
        return Array.isArray(seg.samples) && seg.samples.length
            ? seg.samples[seg.samples.length - 1]
            : seg.end;
    }

    // Student overlays — sample by type (not always a straight line)
    const studentPaths = studentSegs.map((seg) => {
        const samples = Array.isArray(seg.samples) && seg.samples.length >= 2
            ? seg.samples
            : sampleStudentSegment(seg, {
                xMin,
                xMax,
                yMin,
                yMax,
            });
        const fake = {
            ...seg,
            samples,
            markers: {
                start: markerKindFromDivider('start', seg.start_divider),
                end: markerKindFromDivider('end', seg.end_divider),
            },
        };
        return pathFor(samples, '#2563eb') + markersFor(fake, '#2563eb');
    }).join('');

    const authorPaths = segsToDraw.map((seg) => (
        pathFor(seg.samples, '#0f172a') + markersFor(seg, '#0f172a')
    )).join('');

    targetEl.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" style="display:block; background:#fff; border-radius:4px;">
            ${grid}
            ${axis}
            ${tickLabels}
            ${authorPaths}
            ${studentPaths}
        </svg>
    `;

    // Student UI mount (preview wrapper) — skip when review/read-only
    if (
        mode === 'student'
        && typeof options.onStudentAnswerChange === 'function'
        && !options.readOnly
    ) {
        const wrap = targetEl.closest('.simulated-gbp-wrapper');
        if (wrap && !wrap.dataset.gbpStudentBound) {
            mountStudentSegmentUi(wrap, config, options);
        } else if (wrap && options.studentSegments) {
            // re-paint only
        }
    }
}

function mountStudentSegmentUi(wrap, config, options) {
    wrap.dataset.gbpStudentBound = '1';
    const list = wrap.querySelector('.gbp-student-segments');
    const addBtn = wrap.querySelector('.btn-gbp-add-student-seg');
    const canvas = wrap.querySelector('.live-preview-gbp-canvas') || wrap.firstElementChild;
    if (!list || !addBtn) return;

    let segments = [];
    if (options.initialValue && Array.isArray(options.initialValue.segments)) {
        segments = options.initialValue.segments.map((s) => ({ ...s }));
    }

    const axis = {
        xMin: Number(config.bounds?.x_range?.min),
        xMax: Number(config.bounds?.x_range?.max),
        yMin: Number(config.bounds?.y_range?.min),
        yMax: Number(config.bounds?.y_range?.max),
    };

    let suppressFocusOut = false;

    function publish() {
        const cleaned = segments.map((s) => ({
            start: s.start,
            end: s.end,
            start_divider: s.start_divider || 'none',
            end_divider: s.end_divider || 'none',
            type: s.type || 'line',
        })).filter((s) => Array.isArray(s.start) && s.start.length >= 2 && Array.isArray(s.end) && s.end.length >= 2);

        if (typeof options.onStudentAnswerChange === 'function') {
            options.onStudentAnswerChange({ segments: cleaned });
        }
        if (canvas) {
            renderGraphBetweenPointsCanvas(canvas, config, {
                mode: 'student',
                width: options.width || 340,
                height: options.height || 240,
                studentSegments: cleaned,
            });
        }
    }

    function rowHtml(seg, index) {
        return `
            <div class="gbp-student-seg-row" data-idx="${index}" style="display:flex; flex-wrap:wrap; gap:6px; align-items:center; background:#f8fafc; border:1px dashed #cbd5e1; border-radius:4px; padding:6px;">
                <input type="text" class="val-gbp-s-start" value="${escapeAttr(formatPoint(seg.start))}" placeholder="x,y" style="width:70px; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                <select class="val-gbp-s-start-div" style="font-size:0.72rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">${optionsHtml(START_DIVIDERS, seg.start_divider || 'none')}</select>
                <select class="val-gbp-s-type" style="font-size:0.72rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px; max-width:130px;">${optionsHtml(SEGMENT_TYPES, seg.type || 'line')}</select>
                <select class="val-gbp-s-end-div" style="font-size:0.72rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">${optionsHtml(END_DIVIDERS, seg.end_divider || 'none')}</select>
                <input type="text" class="val-gbp-s-end" value="${escapeAttr(formatPoint(seg.end))}" placeholder="x,y" style="width:70px; font-size:0.75rem; padding:3px; border:1px solid #cbd5e1; border-radius:4px;">
                <button type="button" class="btn-gbp-s-remove" style="background:none; border:none; color:#ef4444; cursor:pointer;"><i class="fas fa-trash"></i></button>
            </div>
        `;
    }

    function renderList() {
        list.innerHTML = segments.map((s, i) => rowHtml(s, i)).join('');
    }

    function readListFromDom() {
        segments = Array.from(list.querySelectorAll('.gbp-student-seg-row')).map((row) => {
            let start = parsePointInput(row.querySelector('.val-gbp-s-start')?.value);
            let end = parsePointInput(row.querySelector('.val-gbp-s-end')?.value);
            if (start && !pointInBounds(start[0], start[1], axis.xMin, axis.xMax, axis.yMin, axis.yMax)) {
                row.querySelector('.val-gbp-s-start').value = '';
                start = null;
            }
            if (end && !pointInBounds(end[0], end[1], axis.xMin, axis.xMax, axis.yMin, axis.yMax)) {
                row.querySelector('.val-gbp-s-end').value = '';
                end = null;
            }
            return {
                start: start || [],
                end: end || [],
                start_divider: row.querySelector('.val-gbp-s-start-div')?.value || 'none',
                end_divider: row.querySelector('.val-gbp-s-end-div')?.value || 'none',
                type: row.querySelector('.val-gbp-s-type')?.value || 'line',
            };
        });
    }

    addBtn.addEventListener('click', () => {
        segments.push({
            start: [],
            end: [],
            start_divider: 'none',
            end_divider: 'none',
            type: 'line',
        });
        renderList();
        publish();
    });

    // Use pointerdown so delete wins over focusout→renderList (which would destroy the button
    // before click fires). Suppress the trailing focusout so it cannot re-read a half-updated DOM.
    list.addEventListener('pointerdown', (e) => {
        const btn = e.target.closest('.btn-gbp-s-remove');
        if (!btn || !list.contains(btn)) return;
        e.preventDefault();
        e.stopPropagation();
        const row = btn.closest('.gbp-student-seg-row');
        if (!row) return;
        suppressFocusOut = true;
        row.remove();
        readListFromDom();
        renderList();
        publish();
        queueMicrotask(() => { suppressFocusOut = false; });
    });

    list.addEventListener('change', () => {
        readListFromDom();
        publish();
    });
    list.addEventListener('focusout', (e) => {
        if (suppressFocusOut) return;
        // Skip rebuild when focus is moving to a control inside the list (e.g. delete).
        if (e.relatedTarget && list.contains(e.relatedTarget)) return;
        readListFromDom();
        // Don't rewrite the DOM on every blur — only sanitize invalid coords in place.
        list.querySelectorAll('.gbp-student-seg-row').forEach((row, i) => {
            const seg = segments[i];
            if (!seg) return;
            const startInput = row.querySelector('.val-gbp-s-start');
            const endInput = row.querySelector('.val-gbp-s-end');
            if (startInput) startInput.value = formatPoint(seg.start);
            if (endInput) endInput.value = formatPoint(seg.end);
        });
        publish();
    });

    renderList();
    publish();
}
