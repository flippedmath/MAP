import { ensureLatexRenderBox } from './helpers.js';

/**
 * canvas — scratch-paper drawing board with optional linked underlay.
 * Ink tools never erase the underlay. Unlinked save format = strokes;
 * linked = cropped composite PNG (underlay + ink).
 */

const ZOOM_MIN = 0.4;
const ZOOM_MAX = 3.0;
const ZOOM_STEP = 0.15;
const DRAW_WIDTH = 2.5;
const ERASE_WIDTH = 18;
const MIN_BOARD_H = 180;
const MAX_BOARD_H = 720;
const MIN_BOARD_W = 240;
const MAX_BOARD_W = 900;
const DEFAULT_BOARD_H = 280;
const DEFAULT_BOARD_W = 480;

const controllers = new WeakMap();

export function processEntity(contextData) {
    if (!contextData || !contextData.action) return null;

    switch (contextData.action) {
        case 'fieldsHtml':
            return getFieldsHtml(contextData.savedValues || {});
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
        case 'mountPreviewCanvas':
            return mountPreviewCanvas(contextData);
        case 'refreshCanvasUnderlay':
            return refreshCanvasUnderlay(contextData);
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

function getFieldsHtml(savedValues) {
    const linked = (typeof savedValues.source === 'string' && /^<[^>]+>$/.test(savedValues.source.trim()))
        ? savedValues.source.trim()
        : '';
    const isLinked = !!linked;

    return `
        <div style="display:flex; flex-direction:column; gap:10px; width:100%; box-sizing:border-box;">
            <p style="margin:0; font-size:0.78rem; color:#64748b; line-height:1.4;">
                Scratch paper for freehand work in the preview. Points default to 0.
                If Pts &gt; 0, grading is manual. Optional link prepopulates a background
                (ink tools do not erase it).
            </p>
            <div class="linked-input-wrapper" data-input-key="source" data-input-type="content" style="position:relative; display:flex; align-items:center; justify-content:space-between; gap:8px; width:100%; box-sizing:border-box; background:#f1f5f9; padding:6px 8px; border-radius:4px; border:1px dashed #cbd5e1;">
                <div style="display:flex; flex-direction:column; min-width:0; flex-grow:1;">
                    <span style="font-size:0.75rem; font-weight:600; color:#334155;">Background source (optional)</span>
                    <span class="link-status-text" style="font-size:0.75rem; color:${isLinked ? '#0284c7' : '#94a3b8'}; font-family:monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                        ${isLinked ? `Linked to: ${String(linked).replace(/[<>]/g, '')}` : 'None — blank scratch paper'}
                    </span>
                </div>
                <div style="position:relative; display:flex; align-items:center; flex-shrink:0;">
                    <button type="button" class="btn-input-link-trigger ${isLinked ? 'is-linked' : ''}" title="Link any entity as background" style="background:#ffffff; border:1px solid ${isLinked ? '#fca5a5' : '#cbd5e1'}; border-radius:4px; color:${isLinked ? '#ef4444' : '#94a3b8'}; cursor:pointer; font-size:0.75rem; height:28px; width:28px; display:flex; align-items:center; justify-content:center; box-sizing:border-box;">
                        <i class="fas ${isLinked ? 'fa-times' : 'fa-link'}"></i>
                    </button>
                    <div class="linkable-tokens-dropdown" style="display:none; position:absolute; top:100%; left:auto; right:0; background:white; border:1px solid #cbd5e1; border-radius:4px; box-shadow:0 4px 6px -1px rgb(0 0 0 / 0.1); z-index:50; min-width:150px; padding:4px 0; margin-top:4px; box-sizing:border-box;"></div>
                </div>
                <input type="hidden" class="val-canvas-source" value="${isLinked ? escapeHtmlAttr(linked) : ''}">
            </div>
        </div>
    `;
}

function serialize({ card, inputsCollected }) {
    if (!card || !inputsCollected) return inputsCollected;
    const wrapper = card.querySelector('.linked-input-wrapper[data-input-key="source"]');
    const bound = wrapper?.getAttribute('data-bound-token');
    const hidden = card.querySelector('.val-canvas-source')?.value?.trim();
    const raw = bound || hidden || '';
    if (raw) {
        let clean = String(raw).replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
        if (!clean.startsWith('<')) clean = `<${clean}`;
        if (!clean.endsWith('>')) clean = `${clean}>`;
        inputsCollected.source = clean;
    } else {
        inputsCollected.source = null;
    }
    return inputsCollected;
}

function isLinkCompatible({ inputKey }) {
    if (inputKey !== 'source') return null;
    return true;
}

function applyBatchSync({ card, result }) {
    if (!card || !result) return null;
    const targetDisplay = ensureLatexRenderBox(card);
    if (targetDisplay) {
        targetDisplay.style.textAlign = 'center';
        targetDisplay.style.fontSize = '0.95rem';
        targetDisplay.style.fontWeight = '600';
        targetDisplay.style.color = '#0f172a';
        const out = result.evaluated_output || result.latex_output || 'Canvas (scratch paper)';
        if (String(out).startsWith('[Invalid') || String(out).startsWith('⚠️')) {
            targetDisplay.textContent = 'Canvas (scratch paper)';
        } else {
            targetDisplay.textContent = out;
        }
    }
    return true;
}

function renderPreviewToken({ cleanToken, card, initialValue }) {
    const token = cleanToken || '';
    const w = DEFAULT_BOARD_W;
    const h = DEFAULT_BOARD_H;
    let restoredStrokes = '[]';
    if (initialValue && typeof initialValue === 'object' && Array.isArray(initialValue.strokes)) {
        try {
            restoredStrokes = JSON.stringify(initialValue.strokes);
        } catch (_) {
            restoredStrokes = '[]';
        }
    }

    return `
        <div class="simulated-canvas-wrapper" data-token="${escapeHtmlAttr(token)}" data-strokes="${escapeHtmlAttr(restoredStrokes)}" style="display:block; width:100%; max-width:${MAX_BOARD_W}px; margin:10px 0; box-sizing:border-box; border:1px solid #cbd5e1; border-radius:6px; background:#f8fafc; overflow:hidden;">
            <div class="canvas-toolbar" style="display:flex; flex-wrap:wrap; gap:4px; align-items:center; padding:6px 8px; border-bottom:1px solid #e2e8f0; background:#fff;">
                <button type="button" class="canvas-tool-btn" data-tool="pan" title="Pan" style="font-size:0.72rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px; background:#fff; cursor:pointer; color:#475569;">Pan</button>
                <button type="button" class="canvas-tool-btn is-active" data-tool="draw" title="Draw" style="font-size:0.72rem; padding:4px 8px; border:1px solid #0284c7; border-radius:4px; background:#e0f2fe; cursor:pointer; color:#0369a1; font-weight:600;">Draw</button>
                <button type="button" class="canvas-tool-btn" data-tool="eraser" title="Eraser" style="font-size:0.72rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px; background:#fff; cursor:pointer; color:#475569;">Eraser</button>
                <button type="button" class="canvas-tool-btn" data-action="undo" title="Undo" style="font-size:0.72rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px; background:#fff; cursor:pointer; color:#475569;">Undo</button>
                <button type="button" class="canvas-tool-btn" data-action="erase-all" title="Erase all ink" style="font-size:0.72rem; padding:4px 8px; border:1px solid #fca5a5; border-radius:4px; background:#fff; cursor:pointer; color:#dc2626;">Erase all</button>
                <span style="flex:1 1 auto;"></span>
                <button type="button" class="canvas-tool-btn" data-action="zoom-out" title="Zoom out" style="font-size:0.72rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px; background:#fff; cursor:pointer; color:#475569;">−</button>
                <span class="canvas-zoom-label" style="font-size:0.7rem; color:#64748b; min-width:40px; text-align:center;">100%</span>
                <button type="button" class="canvas-tool-btn" data-action="zoom-in" title="Zoom in" style="font-size:0.72rem; padding:4px 8px; border:1px solid #cbd5e1; border-radius:4px; background:#fff; cursor:pointer; color:#475569;">+</button>
            </div>
            <div class="canvas-board" style="position:relative; width:100%; height:${h}px; min-height:${MIN_BOARD_H}px; background:#ffffff; overflow:hidden; touch-action:none;">
                <div class="canvas-world" style="position:absolute; left:0; top:0; width:100%; height:100%; transform-origin:0 0;">
                    <div class="canvas-underlay" style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; pointer-events:none; z-index:1; padding:12px; box-sizing:border-box; overflow:hidden;"></div>
                    <canvas class="canvas-ink-layer" width="${w}" height="${h}" style="position:absolute; left:0; top:0; width:100%; height:100%; z-index:2; display:block;"></canvas>
                </div>
            </div>
            <div class="canvas-resize-handle" title="Drag to resize" style="height:10px; cursor:ns-resize; background:linear-gradient(to bottom, #f1f5f9, #e2e8f0); border-top:1px solid #e2e8f0; display:flex; align-items:center; justify-content:center;">
                <span style="width:36px; height:3px; border-radius:2px; background:#94a3b8;"></span>
            </div>
        </div>
    `;
}

function getSourceTokenFromCard(card) {
    if (!card) return '';
    const wrapper = card.querySelector('.linked-input-wrapper[data-input-key="source"]');
    const bound = wrapper?.getAttribute('data-bound-token');
    const hidden = card.querySelector('.val-canvas-source')?.value?.trim();
    let raw = (bound || hidden || '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
    if (!raw) return '';
    if (!raw.startsWith('<')) raw = `<${raw}`;
    if (!raw.endsWith('>')) raw = `${raw}>`;
    return /^<[^>]+>$/.test(raw) ? raw : '';
}

function findSourceCard(sourceToken) {
    if (!sourceToken) return null;
    const clean = sourceToken.replace(/[<>]/g, '');
    return Array.from(document.querySelectorAll('.workspace-block-card, .workspace-component-card')).find((c) => {
        const id = c.querySelector('.btn-delete-workspace-component')?.getAttribute('data-indexed-token');
        return id === clean;
    }) || null;
}

function findLiveGraphPreview(sourceToken) {
    const clean = String(sourceToken || '').replace(/[<>]/g, '');
    if (!clean) return null;
    const byAttr = document.querySelector(
        `.simulated-live-graph-preview-container[data-graph-token="${clean}"]`
    );
    if (byAttr) return byAttr;
    // Slope / deferred graph canvases encode the token in their element id
    const byId = document.querySelector(
        `[id^="live-preview-canvas-${clean}"], [id^="slope-preview-${clean}"]`
    );
    if (byId) {
        return byId.closest(
            '.simulated-live-graph-preview-container, .simulated-live-slope-preview-container'
        ) || byId.parentElement;
    }
    // Author card plot (graph always paints here even when not in problem body)
    const authorPlot = document.getElementById(`graph-plot-${clean}`);
    if (authorPlot) return authorPlot;
    return null;
}

function findSourceGraphSvg(sourceCard, sourceToken) {
    const live = findLiveGraphPreview(sourceToken);
    const fromLive = live?.querySelector?.('svg');
    if (fromLive) return fromLive;
    if (sourceCard) {
        const fromCard = sourceCard.querySelector(
            '.slope-field-card-host svg, [id^="graph-plot-"] svg, .live-preview-graph-canvas svg'
        );
        if (fromCard) return fromCard;
    }
    return null;
}

function parseGraphConfigFromCard(sourceCard) {
    if (!sourceCard) return null;
    const raw = sourceCard.getAttribute('data-simulated-value') || '';
    const trimmed = String(raw).trim();
    if (!trimmed.startsWith('{')) return null;
    try {
        const parsed = JSON.parse(trimmed);
        if (parsed && (parsed.archetype === 'graph' || parsed.archetype === 'slopeFieldGraph')) {
            return parsed;
        }
    } catch (_) {
        /* ignore */
    }
    return null;
}

function isGraphPlaceholderLatex(latex) {
    const s = String(latex || '').trim();
    return /^\[(Graph\s*Component|Slope\s*Field\s*Graph|Invalid[^\]]*)\]$/i.test(s)
        || s === '???'
        || s.startsWith('⚠️');
}

function buildUnderlayHtml(sourceCard, sourceToken) {
    if (!sourceCard) {
        return `<span style="font-size:0.8rem; color:#cbd5e1;">${escapeHtmlAttr(sourceToken || '')}</span>`;
    }
    const latex = sourceCard.getAttribute('data-latex-output') || '';
    const sim = sourceCard.getAttribute('data-simulated-value') || '';
    const archetype = sourceCard.getAttribute('data-token') || '';

    // Graphs are painted into the underlay DOM by refreshUnderlay (not via HTML string)
    if (archetype === 'graph' || archetype === 'slopeFieldGraph') {
        return `<span style="font-size:0.75rem; color:#94a3b8; font-style:italic;">Graph loading…</span>`;
    }

    if (
        latex
        && !isGraphPlaceholderLatex(latex)
        && typeof katex !== 'undefined'
    ) {
        try {
            // HTML-only: avoids MathML+HTML double paint when CSS is missing (PNG export)
            return katex.renderToString(latex, {
                throwOnError: false,
                displayMode: true,
                output: 'html',
            });
        } catch (_) {
            /* fall through */
        }
    }

    const display = (latex && !isGraphPlaceholderLatex(latex)) ? latex : (sim || sourceToken);
    if (typeof display === 'string' && display.trim().startsWith('{')) {
        return `<span style="font-size:0.75rem; color:#94a3b8; font-style:italic;">Loading…</span>`;
    }
    return `<span style="font-size:1rem; font-weight:600; color:#0f172a; font-family:monospace;">${escapeHtmlAttr(display)}</span>`;
}

function loadImageFromUrl(url) {
    return new Promise((resolve) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => resolve(null);
        img.src = url;
    });
}

/**
 * Copy computed styles from a live DOM subtree onto a clone so SVG foreignObject
 * rasterization does not depend on page stylesheets (blocked inside data: SVGs).
 */
function cloneUnderlayWithInlineStyles(sourceEl) {
    const clone = sourceEl.cloneNode(true);
    // Belt-and-suspenders if any MathML remnant slipped in
    clone.querySelectorAll('.katex-mathml').forEach((n) => n.remove());

    const srcAll = [sourceEl, ...sourceEl.querySelectorAll('*')];
    const dstAll = [clone, ...clone.querySelectorAll('*')];
    for (let i = 0; i < srcAll.length; i += 1) {
        const src = srcAll[i];
        const dst = dstAll[i];
        if (!src || !dst || src.nodeType !== 1 || dst.nodeType !== 1) continue;
        const cs = window.getComputedStyle(src);
        let cssText = '';
        for (let j = 0; j < cs.length; j += 1) {
            const prop = cs[j];
            cssText += `${prop}:${cs.getPropertyValue(prop)};`;
        }
        dst.setAttribute('style', cssText);
    }
    return clone;
}

function mountPreviewCanvas({
    root,
    wrapper,
    card,
    onChange,
    scheduleGradeRefresh,
    renderGraphComponentCanvas,
    renderSlopeFieldCanvas,
}) {
    const wrap = wrapper || root?.querySelector?.('.simulated-canvas-wrapper');
    if (!wrap || wrap.dataset.canvasMounted === '1') {
        if (wrap && controllers.get(wrap)) {
            controllers.get(wrap).refreshUnderlay();
            controllers.get(wrap).publish();
        }
        return true;
    }
    wrap.dataset.canvasMounted = '1';

    const board = wrap.querySelector('.canvas-board');
    const world = wrap.querySelector('.canvas-world');
    const underlay = wrap.querySelector('.canvas-underlay');
    const ink = wrap.querySelector('.canvas-ink-layer');
    const zoomLabel = wrap.querySelector('.canvas-zoom-label');
    if (!board || !world || !ink) return false;

    let strokes = [];
    try {
        strokes = JSON.parse(wrap.getAttribute('data-strokes') || '[]');
        if (!Array.isArray(strokes)) strokes = [];
    } catch (_) {
        strokes = [];
    }

    const state = {
        tool: 'draw',
        zoom: 1,
        panX: 0,
        panY: 0,
        strokes,
        drawing: false,
        current: null,
        lastX: 0,
        lastY: 0,
        exportTimer: null,
    };

    const ctx = ink.getContext('2d');

    function boardSize() {
        return {
            w: Math.max(1, board.clientWidth || DEFAULT_BOARD_W),
            h: Math.max(1, board.clientHeight || DEFAULT_BOARD_H),
        };
    }

    function syncCanvasPixels() {
        const { w, h } = boardSize();
        const dpr = window.devicePixelRatio || 1;
        ink.width = Math.floor(w * dpr);
        ink.height = Math.floor(h * dpr);
        ink.style.width = `${w}px`;
        ink.style.height = `${h}px`;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        redraw();
    }

    function applyWorldTransform() {
        world.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
        if (zoomLabel) zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
    }

    function screenToWorld(clientX, clientY) {
        const rect = board.getBoundingClientRect();
        const sx = clientX - rect.left;
        const sy = clientY - rect.top;
        return {
            x: (sx - state.panX) / state.zoom,
            y: (sy - state.panY) / state.zoom,
        };
    }

    function drawStrokePath(c, stroke, transform) {
        if (!stroke?.points?.length) return;
        const pts = stroke.points;
        c.save();
        if (transform) {
            c.setTransform(1, 0, 0, 1, 0, 0);
            // caller sets transform for export
        }
        if (stroke.tool === 'erase') {
            c.globalCompositeOperation = 'destination-out';
            c.strokeStyle = 'rgba(0,0,0,1)';
            c.lineWidth = stroke.width || ERASE_WIDTH;
        } else {
            c.globalCompositeOperation = 'source-over';
            c.strokeStyle = '#0f172a';
            c.lineWidth = stroke.width || DRAW_WIDTH;
        }
        c.lineCap = 'round';
        c.lineJoin = 'round';
        c.beginPath();
        c.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i += 1) {
            c.lineTo(pts[i][0], pts[i][1]);
        }
        c.stroke();
        c.restore();
    }

    function redraw() {
        const { w, h } = boardSize();
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, ink.width, ink.height);
        ctx.restore();
        // Draw in world coords mapped through pan/zoom via CSS on world; ink canvas
        // is inside world so draw in world pixels matching CSS size of board at zoom 1.
        // Ink layer stretches with world transform via being a child — draw in local
        // board pixel space at zoom=1 size (board CSS size).
        ctx.clearRect(0, 0, w, h);
        // Because ink is inside .canvas-world which is transformed, stroke coords are world coords
        // equal to board CSS pixels when pan=0,zoom=1. Keep canvas bitmap = board CSS size.
        state.strokes.forEach((s) => drawStrokePath(ctx, s));
        if (state.current) drawStrokePath(ctx, state.current);
    }

    function setTool(tool) {
        state.tool = tool;
        wrap.querySelectorAll('.canvas-tool-btn[data-tool]').forEach((btn) => {
            const active = btn.getAttribute('data-tool') === tool;
            btn.classList.toggle('is-active', active);
            btn.style.borderColor = active ? '#0284c7' : '#cbd5e1';
            btn.style.background = active ? '#e0f2fe' : '#fff';
            btn.style.color = active ? '#0369a1' : '#475569';
            btn.style.fontWeight = active ? '600' : '400';
        });
        board.style.cursor = tool === 'pan' ? 'grab' : (tool === 'eraser' ? 'cell' : 'crosshair');
    }

    function paintGraphIntoUnderlay(sourceCard, sourceToken) {
        const archetype = sourceCard?.getAttribute('data-token') || '';
        const existingSvg = findSourceGraphSvg(sourceCard, sourceToken);
        if (existingSvg) {
            const clone = existingSvg.cloneNode(true);
            if (!clone.getAttribute('xmlns')) {
                clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
            }
            // Fit inside the board without overflowing
            clone.style.maxWidth = '100%';
            clone.style.maxHeight = '100%';
            clone.style.width = 'auto';
            clone.style.height = 'auto';
            underlay.innerHTML = '';
            underlay.appendChild(clone);
            return true;
        }

        const config = parseGraphConfigFromCard(sourceCard);
        let plotConfig = config;
        if (plotConfig && Array.isArray(plotConfig.formulas)) {
            plotConfig = {
                ...plotConfig,
                formulas: plotConfig.formulas.map((fStr) => {
                    const rhs = String(fStr).split('=')[1] || fStr;
                    return String(rhs).replace(/\*\*/g, '^').trim();
                }),
            };
        }
        const cleanToken = String(sourceToken || '').replace(/[<>]/g, '');
        const hostId = `canvas-underlay-plot-${wrap.getAttribute('data-token') || cleanToken}`;
        const { w, h } = boardSize();
        const plotW = Math.min(340, Math.max(200, w - 24));
        const plotH = Math.min(240, Math.max(160, h - 24));

        underlay.innerHTML = `<div id="${hostId}" style="width:${plotW}px;height:${plotH}px;max-width:100%;"></div>`;

        if (archetype === 'slopeFieldGraph' || plotConfig?.archetype === 'slopeFieldGraph') {
            const host = document.getElementById(hostId);
            if (host && plotConfig && typeof renderSlopeFieldCanvas === 'function') {
                renderSlopeFieldCanvas(host, plotConfig, {
                    mode: 'author',
                    width: plotW,
                    height: plotH,
                });
                return !!host.querySelector('svg');
            }
        } else if (plotConfig && typeof renderGraphComponentCanvas === 'function') {
            renderGraphComponentCanvas(hostId, plotConfig, { width: plotW, height: plotH });
            const host = document.getElementById(hostId);
            return !!host?.querySelector('svg');
        }

        underlay.innerHTML = `<span style="font-size:0.75rem; color:#94a3b8; font-style:italic;">Graph loading…</span>`;
        return false;
    }

    function refreshUnderlay() {
        const sourceToken = card ? getSourceTokenFromCard(card) : '';
        wrap.dataset.sourceToken = sourceToken || '';
        if (!underlay) return;
        if (!sourceToken) {
            underlay.innerHTML = '';
            return;
        }
        const sourceCard = findSourceCard(sourceToken);
        const archetype = sourceCard?.getAttribute('data-token') || '';
        if (archetype === 'graph' || archetype === 'slopeFieldGraph') {
            paintGraphIntoUnderlay(sourceCard, sourceToken);
            return;
        }
        underlay.innerHTML = buildUnderlayHtml(sourceCard, sourceToken);
    }

    function hasInk() {
        return state.strokes.some((s) => Array.isArray(s.points) && s.points.length > 0);
    }

    function isLinked() {
        return !!(card && getSourceTokenFromCard(card));
    }

    function strokeBounds(list) {
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        list.forEach((s) => {
            const half = (s.width || DRAW_WIDTH) / 2 + 2;
            (s.points || []).forEach(([x, y]) => {
                minX = Math.min(minX, x - half);
                minY = Math.min(minY, y - half);
                maxX = Math.max(maxX, x + half);
                maxY = Math.max(maxY, y + half);
            });
        });
        if (!Number.isFinite(minX)) return null;
        return { minX, minY, maxX, maxY };
    }

    function paintStrokesToContext(c, list, offsetX, offsetY) {
        list.forEach((stroke) => {
            if (!stroke?.points?.length) return;
            c.save();
            if (stroke.tool === 'erase') {
                c.globalCompositeOperation = 'destination-out';
                c.strokeStyle = 'rgba(0,0,0,1)';
                c.lineWidth = stroke.width || ERASE_WIDTH;
            } else {
                c.globalCompositeOperation = 'source-over';
                c.strokeStyle = '#0f172a';
                c.lineWidth = stroke.width || DRAW_WIDTH;
            }
            c.lineCap = 'round';
            c.lineJoin = 'round';
            c.beginPath();
            c.moveTo(stroke.points[0][0] - offsetX, stroke.points[0][1] - offsetY);
            for (let i = 1; i < stroke.points.length; i += 1) {
                c.lineTo(stroke.points[i][0] - offsetX, stroke.points[i][1] - offsetY);
            }
            c.stroke();
            c.restore();
        });
    }

    function liveContentWorldBox(el) {
        if (!el || !board) return null;
        // Same mapping as screenToWorld — must match stroke coordinates exactly
        const br = board.getBoundingClientRect();
        const cr = el.getBoundingClientRect();
        const zoom = state.zoom || 1;
        if (!(zoom > 0) || !(br.width > 0) || !(br.height > 0)) return null;
        return {
            x: (cr.left - br.left - state.panX) / zoom,
            y: (cr.top - br.top - state.panY) / zoom,
            w: Math.max(1, cr.width / zoom),
            h: Math.max(1, cr.height / zoom),
        };
    }

    function opaqueInkBounds(imgOrCanvas) {
        const w = imgOrCanvas.naturalWidth || imgOrCanvas.width;
        const h = imgOrCanvas.naturalHeight || imgOrCanvas.height;
        if (!(w > 0) || !(h > 0)) return null;
        const tmp = document.createElement('canvas');
        tmp.width = w;
        tmp.height = h;
        const ctx = tmp.getContext('2d');
        ctx.drawImage(imgOrCanvas, 0, 0);
        const data = ctx.getImageData(0, 0, w, h).data;
        let minX = w;
        let minY = h;
        let maxX = -1;
        let maxY = -1;
        for (let y = 0; y < h; y += 1) {
            for (let x = 0; x < w; x += 1) {
                const i = (y * w + x) * 4;
                if (data[i + 3] > 12) {
                    if (x < minX) minX = x;
                    if (y < minY) minY = y;
                    if (x > maxX) maxX = x;
                    if (y > maxY) maxY = y;
                }
            }
        }
        if (maxX < minX) return null;
        return { x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 };
    }

    function drawImageIntoWorldBox(ctx, img, box) {
        if (!img || !box) return;
        const ink = opaqueInkBounds(img);
        if (ink && ink.w > 1 && ink.h > 1) {
            // Map visible ink → live KaTeX box (drops uneven MathML / SVG padding)
            ctx.drawImage(img, ink.x, ink.y, ink.w, ink.h, box.x, box.y, box.w, box.h);
        } else {
            ctx.drawImage(img, box.x, box.y, box.w, box.h);
        }
    }

    async function rasterizeSvgToBoard(svgEl, boardW, boardH) {
        const clone = svgEl.cloneNode(true);
        if (!clone.getAttribute('xmlns')) {
            clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        }
        // Prefer intrinsic SVG size; fall back to live box in world coords
        const box = liveContentWorldBox(svgEl);
        const sw = Math.max(
            1,
            Math.round(Number(svgEl.getAttribute('width'))) || Math.round(box?.w) || boardW
        );
        const sh = Math.max(
            1,
            Math.round(Number(svgEl.getAttribute('height'))) || Math.round(box?.h) || boardH
        );
        clone.setAttribute('width', String(sw));
        clone.setAttribute('height', String(sh));
        if (!clone.getAttribute('viewBox') && svgEl.viewBox?.baseVal) {
            const vb = svgEl.viewBox.baseVal;
            if (vb.width > 0 && vb.height > 0) {
                clone.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.width} ${vb.height}`);
            }
        }
        const xml = new XMLSerializer().serializeToString(clone);
        const img = await loadImageFromUrl(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`);
        if (!img) return null;
        const canvas = document.createElement('canvas');
        canvas.width = boardW;
        canvas.height = boardH;
        const ctx = canvas.getContext('2d');
        if (box) {
            // Place where the live SVG sits in world/stroke space (matches ink)
            ctx.drawImage(img, box.x, box.y, box.w, box.h);
        } else {
            ctx.drawImage(img, (boardW - sw) / 2, (boardH - sh) / 2, sw, sh);
        }
        return canvas;
    }

    function measureHtmlNaturalSize(html) {
        const probe = document.createElement('div');
        probe.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
        probe.style.cssText = 'position:absolute;left:-10000px;top:0;visibility:hidden;display:inline-block;white-space:nowrap;line-height:normal;';
        probe.innerHTML = html;
        document.body.appendChild(probe);
        const nw = Math.max(1, Math.ceil(probe.offsetWidth || probe.getBoundingClientRect().width || 1));
        const nh = Math.max(1, Math.ceil(probe.offsetHeight || probe.getBoundingClientRect().height || 1));
        probe.remove();
        return { w: nw, h: nh };
    }

    async function rasterizeHtmlToImage(html, width, height) {
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
            <foreignObject width="100%" height="100%">
                <div xmlns="http://www.w3.org/1999/xhtml" style="width:${width}px;height:${height}px;margin:0;padding:0;overflow:visible;background:transparent;">
                    ${html}
                </div>
            </foreignObject>
        </svg>`;
        return loadImageFromUrl(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
    }

    /**
     * Bake formula/matrix underlay into stroke/world space.
     * Placement uses the same board→world mapping as ink. Prefer a live KaTeX
     * DOM snapshot (1:1 like graphs); MathML fallback maps ink→box to kill padding drift.
     */
    async function rasterizeKatexUnderlayToBoard(boardW, boardH) {
        const content = underlay.querySelector('.katex-display')
            || underlay.querySelector('.katex')
            || underlay.firstElementChild;
        if (!content) return null;
        const box = liveContentWorldBox(content);
        if (!box) return null;

        const sourceToken = card ? getSourceTokenFromCard(card) : '';
        const sourceCard = sourceToken ? findSourceCard(sourceToken) : null;
        const latex = sourceCard?.getAttribute('data-latex-output') || '';

        const canvas = document.createElement('canvas');
        canvas.width = boardW;
        canvas.height = boardH;
        const ctx = canvas.getContext('2d');

        // Prefer live KaTeX DOM snapshot — same layout the student drew against
        try {
            const styled = cloneUnderlayWithInlineStyles(content);
            styled.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
            styled.style.margin = '0';
            styled.style.transform = 'none';
            styled.style.position = 'static';
            const serialized = new XMLSerializer().serializeToString(styled);
            const lw = Math.max(1, Math.ceil(content.offsetWidth || box.w));
            const lh = Math.max(1, Math.ceil(content.offsetHeight || box.h));
            const liveImg = await rasterizeHtmlToImage(serialized, lw, lh);
            if (liveImg) {
                const ink = opaqueInkBounds(liveImg);
                if (ink && ink.w >= 4 && ink.h >= 4) {
                    // 1:1 place by live screen box (do not re-stretch ink — preserves alignment)
                    ctx.drawImage(liveImg, box.x, box.y, box.w, box.h);
                    return canvas;
                }
            }
        } catch (_) {
            /* fall through to MathML */
        }

        if (latex && !isGraphPlaceholderLatex(latex) && typeof katex !== 'undefined') {
            let bodyHtml = '';
            try {
                bodyHtml = katex.renderToString(latex, {
                    throwOnError: false,
                    displayMode: true,
                    output: 'mathml',
                });
            } catch (_) {
                bodyHtml = '';
            }
            if (bodyHtml) {
                const natural = measureHtmlNaturalSize(bodyHtml);
                const dpr = Math.max(2, Math.ceil(window.devicePixelRatio || 1));
                const scaledHtml = `<div style="display:inline-block;transform:scale(${dpr});transform-origin:top left;line-height:normal;">${bodyHtml}</div>`;
                const img = await rasterizeHtmlToImage(
                    scaledHtml,
                    Math.max(2, natural.w * dpr),
                    Math.max(2, natural.h * dpr)
                );
                if (img) {
                    // MathML has uneven padding vs KaTeX — map ink extents onto the live box
                    drawImageIntoWorldBox(ctx, img, box);
                    return canvas;
                }
            }
        }

        return null;
    }

    async function rasterizeUnderlay(width, height) {
        if (!underlay || !underlay.innerHTML.trim()) return null;
        const { w, h } = boardSize();

        // Graphs: bake the live SVG into its on-board world box
        const plotSvg = underlay.querySelector('svg');
        if (plotSvg && !underlay.querySelector('.katex')) {
            return rasterizeSvgToBoard(plotSvg, w, h);
        }

        const sourceToken = card ? getSourceTokenFromCard(card) : '';
        const sourceCard = sourceToken ? findSourceCard(sourceToken) : null;
        const archetype = sourceCard?.getAttribute('data-token') || '';
        if (archetype === 'graph' || archetype === 'slopeFieldGraph') {
            const fallbackSvg = findSourceGraphSvg(sourceCard, sourceToken);
            if (fallbackSvg) {
                return rasterizeSvgToBoard(fallbackSvg, w, h);
            }
            return null;
        }

        // Formulas / matrices: pin export to the live KaTeX bounding box
        if (underlay.querySelector('.katex')) {
            return rasterizeKatexUnderlayToBoard(w, h);
        }

        // Generic HTML underlay fallback
        const styled = cloneUnderlayWithInlineStyles(underlay);
        styled.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
        const bodyHtml = new XMLSerializer().serializeToString(styled);
        const svgFallback = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}">
            <foreignObject width="100%" height="100%">${bodyHtml}</foreignObject>
        </svg>`;
        return loadImageFromUrl(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgFallback)}`);
    }

    function cropOpaque(canvas) {
        const c = canvas.getContext('2d');
        const { width, height } = canvas;
        const data = c.getImageData(0, 0, width, height).data;
        let minX = width;
        let minY = height;
        let maxX = -1;
        let maxY = -1;
        for (let y = 0; y < height; y += 1) {
            for (let x = 0; x < width; x += 1) {
                const i = (y * width + x) * 4;
                const a = data[i + 3];
                // Ignore transparent and near-white fill so crop hugs content
                if (a > 8) {
                    const r = data[i];
                    const g = data[i + 1];
                    const b = data[i + 2];
                    if (r > 250 && g > 250 && b > 250 && a > 250) continue;
                    if (x < minX) minX = x;
                    if (y < minY) minY = y;
                    if (x > maxX) maxX = x;
                    if (y > maxY) maxY = y;
                }
            }
        }
        if (maxX < minX) return null;
        const pad = 12;
        minX = Math.max(0, minX - pad);
        minY = Math.max(0, minY - pad);
        maxX = Math.min(width - 1, maxX + pad);
        maxY = Math.min(height - 1, maxY + pad);
        const cw = maxX - minX + 1;
        const ch = maxY - minY + 1;
        const out = document.createElement('canvas');
        out.width = cw;
        out.height = ch;
        out.getContext('2d').drawImage(canvas, minX, minY, cw, ch, 0, 0, cw, ch);
        return out;
    }

    function compositeOnWhite(srcCanvas) {
        const out = document.createElement('canvas');
        out.width = srcCanvas.width;
        out.height = srcCanvas.height;
        const ctx = out.getContext('2d');
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, out.width, out.height);
        ctx.drawImage(srcCanvas, 0, 0);
        return out;
    }

    async function buildLinkedResultPng() {
        const { w, h } = boardSize();
        const pad = 40;
        // Transparent composite so cropOpaque can find content bounds (white fill
        // made the whole board "opaque" and left a tiny matrix in a huge PNG).
        const full = document.createElement('canvas');
        full.width = w + pad * 2;
        full.height = h + pad * 2;
        const fc = full.getContext('2d');
        fc.clearRect(0, 0, full.width, full.height);

        const underImg = await rasterizeUnderlay(w, h);
        if (underImg) {
            fc.drawImage(underImg, pad, pad, w, h);
        } else if (isLinked()) {
            fc.fillStyle = '#64748b';
            fc.font = '14px monospace';
            fc.textAlign = 'center';
            fc.fillText(getSourceTokenFromCard(card) || '[background]', pad + w / 2, pad + h / 2);
        }

        // Ink in world coords — same space as underlay placement
        paintStrokesToContext(fc, state.strokes, -pad, -pad);

        const cropped = cropOpaque(full);
        if (!cropped) {
            const box = document.createElement('canvas');
            box.width = w;
            box.height = h;
            const bc = box.getContext('2d');
            bc.fillStyle = '#ffffff';
            bc.fillRect(0, 0, w, h);
            if (underImg) bc.drawImage(underImg, 0, 0, w, h);
            paintStrokesToContext(bc, state.strokes, 0, 0);
            return box.toDataURL('image/png');
        }
        return compositeOnWhite(cropped).toDataURL('image/png');
    }

    function buildStrokesDisplayPng() {
        const bounds = strokeBounds(state.strokes);
        if (!bounds) return null;
        const pad = 16;
        const width = Math.max(1, Math.ceil(bounds.maxX - bounds.minX + pad * 2));
        const height = Math.max(1, Math.ceil(bounds.maxY - bounds.minY + pad * 2));
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const c = canvas.getContext('2d');
        c.fillStyle = '#ffffff';
        c.fillRect(0, 0, width, height);
        paintStrokesToContext(c, state.strokes, bounds.minX - pad, bounds.minY - pad);
        return canvas.toDataURL('image/png');
    }

    async function publish() {
        const token = wrap.getAttribute('data-token') || '';
        const linked = isLinked();
        let payload;
        if (linked) {
            const result_png = (hasInk() || underlay?.innerHTML.trim())
                ? await buildLinkedResultPng()
                : null;
            payload = {
                format: 'png',
                result_png,
                strokes: state.strokes, // session-only for undo restore
            };
            wrap.dataset.resultPng = result_png || '';
            wrap.dataset.format = 'png';
        } else {
            payload = {
                format: 'strokes',
                version: 1,
                strokes: state.strokes,
            };
            // Display-only raster for grade panel
            const display = hasInk() ? buildStrokesDisplayPng() : null;
            payload._display_png = display;
            wrap.dataset.resultPng = display || '';
            wrap.dataset.format = 'strokes';
        }
        wrap.setAttribute('data-strokes', JSON.stringify(state.strokes));
        if (typeof onChange === 'function') {
            onChange(token, payload);
        }
        if (typeof scheduleGradeRefresh === 'function') {
            scheduleGradeRefresh();
        }
    }

    function schedulePublish() {
        if (state.exportTimer) clearTimeout(state.exportTimer);
        state.exportTimer = setTimeout(() => {
            state.exportTimer = null;
            publish();
        }, 200);
    }

    // Pointer handlers
    board.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        board.setPointerCapture(e.pointerId);
        const worldPt = screenToWorld(e.clientX, e.clientY);
        state.drawing = true;
        state.lastX = e.clientX;
        state.lastY = e.clientY;

        if (state.tool === 'pan') {
            board.style.cursor = 'grabbing';
            return;
        }

        state.current = {
            tool: state.tool === 'eraser' ? 'erase' : 'draw',
            width: state.tool === 'eraser' ? ERASE_WIDTH : DRAW_WIDTH,
            points: [[worldPt.x, worldPt.y]],
        };
        redraw();
    });

    board.addEventListener('pointermove', (e) => {
        if (!state.drawing) return;
        if (state.tool === 'pan') {
            const dx = e.clientX - state.lastX;
            const dy = e.clientY - state.lastY;
            state.panX += dx;
            state.panY += dy;
            state.lastX = e.clientX;
            state.lastY = e.clientY;
            applyWorldTransform();
            return;
        }
        if (!state.current) return;
        const worldPt = screenToWorld(e.clientX, e.clientY);
        const last = state.current.points[state.current.points.length - 1];
        if (!last || (Math.abs(last[0] - worldPt.x) + Math.abs(last[1] - worldPt.y)) > 0.5) {
            state.current.points.push([worldPt.x, worldPt.y]);
            redraw();
        }
    });

    function endStroke() {
        if (!state.drawing) return;
        state.drawing = false;
        board.style.cursor = state.tool === 'pan' ? 'grab' : (state.tool === 'eraser' ? 'cell' : 'crosshair');
        if (state.tool === 'pan') return;
        if (state.current && state.current.points.length) {
            state.strokes.push(state.current);
        }
        state.current = null;
        redraw();
        schedulePublish();
    }

    board.addEventListener('pointerup', endStroke);
    board.addEventListener('pointercancel', endStroke);

    board.addEventListener('wheel', (e) => {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        const factor = e.deltaY < 0 ? (1 + ZOOM_STEP) : (1 - ZOOM_STEP);
        const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, state.zoom * factor));
        // Zoom toward pointer
        const rect = board.getBoundingClientRect();
        const sx = e.clientX - rect.left;
        const sy = e.clientY - rect.top;
        const wx = (sx - state.panX) / state.zoom;
        const wy = (sy - state.panY) / state.zoom;
        state.zoom = next;
        state.panX = sx - wx * state.zoom;
        state.panY = sy - wy * state.zoom;
        applyWorldTransform();
    }, { passive: false });

    wrap.querySelector('.canvas-toolbar')?.addEventListener('click', (e) => {
        const btn = e.target.closest('.canvas-tool-btn');
        if (!btn) return;
        const tool = btn.getAttribute('data-tool');
        const action = btn.getAttribute('data-action');
        if (tool) {
            setTool(tool);
            return;
        }
        if (action === 'undo') {
            state.strokes.pop();
            redraw();
            schedulePublish();
        } else if (action === 'erase-all') {
            state.strokes = [];
            redraw();
            schedulePublish();
        } else if (action === 'zoom-in') {
            state.zoom = Math.min(ZOOM_MAX, state.zoom + ZOOM_STEP);
            applyWorldTransform();
        } else if (action === 'zoom-out') {
            state.zoom = Math.max(ZOOM_MIN, state.zoom - ZOOM_STEP);
            applyWorldTransform();
        }
    });

    // Resize handle
    const handle = wrap.querySelector('.canvas-resize-handle');
    if (handle) {
        let resizing = false;
        let startY = 0;
        let startH = 0;
        handle.addEventListener('pointerdown', (e) => {
            resizing = true;
            startY = e.clientY;
            startH = board.clientHeight;
            handle.setPointerCapture(e.pointerId);
            e.preventDefault();
        });
        handle.addEventListener('pointermove', (e) => {
            if (!resizing) return;
            const next = Math.min(MAX_BOARD_H, Math.max(MIN_BOARD_H, startH + (e.clientY - startY)));
            board.style.height = `${next}px`;
            syncCanvasPixels();
        });
        handle.addEventListener('pointerup', () => {
            resizing = false;
            schedulePublish();
        });
    }

    const api = {
        refreshUnderlay: () => {
            refreshUnderlay();
            schedulePublish();
        },
        publish,
        getPayload: () => {
            const linked = isLinked();
            if (linked) {
                return {
                    format: 'png',
                    result_png: wrap.dataset.resultPng || null,
                    strokes: state.strokes,
                };
            }
            return {
                format: 'strokes',
                version: 1,
                strokes: state.strokes,
                _display_png: wrap.dataset.resultPng || null,
            };
        },
    };

    controllers.set(wrap, api);
    setTool('draw');
    applyWorldTransform();
    refreshUnderlay();
    syncCanvasPixels();
    // Initial publish after layout
    requestAnimationFrame(() => {
        syncCanvasPixels();
        publish();
    });
    return true;
}

function refreshCanvasUnderlay({ wrapper, card, renderGraphComponentCanvas, renderSlopeFieldCanvas }) {
    const wrap = wrapper;
    if (!wrap) return null;
    const ctrl = controllers.get(wrap);
    if (ctrl) {
        ctrl.refreshUnderlay();
        return true;
    }
    return mountPreviewCanvas({
        wrapper: wrap,
        card,
        renderGraphComponentCanvas,
        renderSlopeFieldCanvas,
    });
}
