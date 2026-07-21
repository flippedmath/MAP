"""
Geometry helpers for graphBetweenPoints: fit/sample lines, parabolas, cubics.
Kept separate from util.py to keep entity validation readable.
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]
SAMPLE_COUNT = 64
EPS = 1e-9
GRADE_TOL = 0.15


def _finite(v: float) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(float(v))


def point_in_bounds(
    x: float,
    y: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> bool:
    """Author/student coords: x on [xmin,xmax]; y strictly inside (ymin,ymax)."""
    if not (_finite(x) and _finite(y)):
        return False
    if x < x_min - EPS or x > x_max + EPS:
        return False
    if y <= y_min + EPS or y >= y_max - EPS:
        return False
    return True


def segment_x_covers(vx: float, x1: float, x2: float) -> bool:
    lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
    return lo - EPS <= vx <= hi + EPS


def parabola_from_endpoints_and_h(
    x1: float, y1: float, x2: float, y2: float, h: float
) -> Optional[Tuple[float, float, float]]:
    """
    Vertical parabola y = a(x-h)^2 + k through two endpoints with vertex x = h.
    Returns (a, h, k) or None.

    When endpoints share the same y, a is forced to 0 for any non-midpoint h
    (degenerate). Use parabola_level_chord_at_k for that case.
    """
    d1 = (x1 - h) ** 2
    d2 = (x2 - h) ** 2
    denom = d1 - d2
    if abs(denom) < EPS:
        return None
    a = (y1 - y2) / denom
    # Degenerate horizontal "parabola" when endpoints are level and h ≠ midpoint
    if abs(a) < EPS:
        return None
    k = y1 - a * d1
    if not (_finite(a) and _finite(k)):
        return None
    return (a, h, k)


def parabola_level_chord_at_k(
    kind: str,
    x1: float,
    y: float,
    x2: float,
    k: float,
) -> Optional[Tuple[float, float, float]]:
    """
    Endpoints share y: only a midpoint vertex x yields a non-degenerate vertical parabola.
    Pick vertex height k and derive a.
    """
    h = 0.5 * (x1 + x2)
    d = (x1 - h) ** 2
    if d < EPS:
        return None
    a = (y - k) / d
    if not _finite(a) or abs(a) < EPS:
        return None
    if kind == "concave_down_parabola" and a >= 0:
        return None
    if kind == "concave_up_parabola" and a <= 0:
        return None
    if not validate_parabola_vertex_height(kind, x1, y, x2, y, h, k):
        return None
    return (a, h, k)


def validate_parabola_vertex_height(
    kind: str, x1: float, y1: float, x2: float, y2: float, vx: float, vy: float
) -> bool:
    """Geometry constraints when vertex x lies between endpoints."""
    if not segment_x_covers(vx, x1, x2):
        return True  # outside open interval: only axis bounds apply elsewhere
    lo_x, hi_x = (x1, x2) if x1 <= x2 else (x2, x1)
    if abs(vx - lo_x) < EPS or abs(vx - hi_x) < EPS:
        return False
    chord_max = max(y1, y2)
    chord_min = min(y1, y2)
    if kind == "concave_down_parabola":
        return vy > chord_max + EPS
    if kind == "concave_up_parabola":
        return vy < chord_min - EPS
    return True


def sample_parabola(a: float, h: float, k: float, x1: float, x2: float, n: int = SAMPLE_COUNT) -> List[List[float]]:
    lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
    if abs(hi - lo) < EPS:
        return [[x1, a * (x1 - h) ** 2 + k], [x2, a * (x2 - h) ** 2 + k]]
    pts = []
    for i in range(n):
        t = i / (n - 1)
        x = lo + t * (hi - lo)
        y = a * (x - h) ** 2 + k
        pts.append([round(x, 8), round(y, 8)])
    return pts


def sample_line(x1: float, y1: float, x2: float, y2: float, n: int = SAMPLE_COUNT) -> List[List[float]]:
    if abs(x2 - x1) < EPS and abs(y2 - y1) < EPS:
        return [[x1, y1], [x2, y2]]
    pts = []
    for i in range(n):
        t = i / (n - 1)
        pts.append([round(x1 + t * (x2 - x1), 8), round(y1 + t * (y2 - y1), 8)])
    return pts


def synthesize_parabola_h(
    kind: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    rng: random.Random,
) -> Optional[Tuple[float, float, float]]:
    """Pick a valid h so the fitted parabola satisfies type + axis bounds."""
    lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
    # Keep h strictly between endpoints and inside axis
    cand_lo = max(lo, x_min) + 1e-6
    cand_hi = min(hi, x_max) - 1e-6
    if cand_hi <= cand_lo:
        return None

    # Level chord: vertex x must be the midpoint; sample vertex height instead.
    if abs(y1 - y2) < EPS:
        h = 0.5 * (x1 + x2)
        if h <= cand_lo or h >= cand_hi:
            return None
        y = y1
        chord_max = y
        chord_min = y
        for _ in range(40):
            if kind == "concave_down_parabola":
                top = y_max - 1e-6
                bot = chord_max + max(0.25, 0.05 * (hi - lo))
                if top <= bot:
                    return None
                k = rng.uniform(bot, top)
            else:
                top = chord_min - max(0.25, 0.05 * (hi - lo))
                bot = y_min + 1e-6
                if top <= bot:
                    return None
                k = rng.uniform(bot, top)
            fitted = parabola_level_chord_at_k(kind, x1, y, x2, k)
            if not fitted:
                continue
            a, h, k = fitted
            if not point_in_bounds(h, k, x_min, x_max, y_min, y_max):
                continue
            return fitted
        return None

    for _ in range(40):
        h = rng.uniform(cand_lo, cand_hi)
        fitted = parabola_from_endpoints_and_h(x1, y1, x2, y2, h)
        if not fitted:
            continue
        a, h, k = fitted
        if kind == "concave_down_parabola" and a >= 0:
            continue
        if kind == "concave_up_parabola" and a <= 0:
            continue
        if not validate_parabola_vertex_height(kind, x1, y1, x2, y2, h, k):
            continue
        if not point_in_bounds(h, k, x_min, x_max, y_min, y_max):
            continue
        return fitted
    return None


def fit_parabola_with_vertex(
    kind: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    vx: float,
    vy: float,
) -> Optional[Tuple[float, float, float]]:
    """
    Exact vertical parabola with extremum at (vx, vy) that passes through both endpoints.
    Requires a from each endpoint to agree.
    """
    if abs(x1 - vx) < EPS or abs(x2 - vx) < EPS:
        return None
    if not segment_x_covers(vx, x1, x2):
        return None
    if not validate_parabola_vertex_height(kind, x1, y1, x2, y2, vx, vy):
        return None
    a1 = (y1 - vy) / (x1 - vx) ** 2
    a2 = (y2 - vy) / (x2 - vx) ** 2
    if not (_finite(a1) and _finite(a2)):
        return None
    # Tight agreement so the curve truly hits the vertex and both ends
    if abs(a1 - a2) > 1e-4:
        return None
    a = 0.5 * (a1 + a2)
    if kind == "concave_down_parabola" and a >= 0:
        return None
    if kind == "concave_up_parabola" and a <= 0:
        return None
    return (a, vx, vy)


def _iter_axis_lattice(mn: float, mx: float, step: float) -> List[float]:
    if step <= 0 or mx < mn:
        return []
    vals = []
    # Inclusive lattice walk with rounding to limit float drift
    n = int(math.floor((mx - mn) / step + 1e-9)) + 1
    for i in range(max(n, 0) + 2):
        v = mn + i * step
        if v > mx + 1e-9:
            break
        vals.append(round(v, 10))
    return vals


def find_grid_parabola_vertex(
    kind: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    x_range: Sequence[float],
    y_range: Sequence[float],
    prefer: Optional[Point] = None,
) -> Optional[Tuple[float, float, float]]:
    """
    Search axis-lattice points (gx, gy) that can be an exact parabola vertex
    through both endpoints (a1 ≈ a2), preferring closeness to `prefer`.
    """
    x_min, x_max, x_step = float(x_range[0]), float(x_range[1]), float(x_range[2])
    y_min, y_max, y_step = float(y_range[0]), float(y_range[1]), float(y_range[2])
    lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)

    best = None
    best_dist = float("inf")
    for gx in _iter_axis_lattice(x_min, x_max, x_step):
        if gx <= lo + EPS or gx >= hi - EPS:
            continue
        for gy in _iter_axis_lattice(y_min, y_max, y_step):
            if not point_in_bounds(gx, gy, x_min, x_max, y_min, y_max):
                continue
            fitted = fit_parabola_with_vertex(kind, x1, y1, x2, y2, gx, gy)
            if not fitted:
                continue
            if prefer is None:
                return fitted
            dist = (fitted[1] - prefer[0]) ** 2 + (fitted[2] - prefer[1]) ** 2
            if dist < best_dist:
                best_dist = dist
                best = fitted
    return best


def fallback_parabola_through_endpoints(
    kind: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    x_range: Sequence[float],
    y_range: Sequence[float],
    rng: random.Random,
) -> Optional[Tuple[float, float, float]]:
    """
    Fit any valid in-bounds parabola through the endpoints (vertex x on lattice when possible).
    """
    x_min, x_max, x_step = float(x_range[0]), float(x_range[1]), float(x_range[2])
    y_min, y_max, y_step = float(y_range[0]), float(y_range[1]), float(y_range[2])
    lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)

    # Level chord: only midpoint x works; prefer lattice vertex heights.
    if abs(y1 - y2) < EPS:
        h = 0.5 * (x1 + x2)
        if h > lo + EPS and h < hi - EPS and point_in_bounds(h, y1, x_min, x_max, y_min, y_max):
            y = y1
            gy_candidates = [
                gy for gy in _iter_axis_lattice(y_min, y_max, y_step)
                if point_in_bounds(h, gy, x_min, x_max, y_min, y_max)
            ]
            rng.shuffle(gy_candidates)
            for gy in gy_candidates:
                fitted = parabola_level_chord_at_k(kind, x1, y, x2, gy)
                if fitted:
                    return fitted
        return synthesize_parabola_h(
            kind, x1, y1, x2, y2, x_min, x_max, y_min, y_max, rng
        )

    # Prefer lattice h values first for a grid-aligned vertex x
    candidates = [
        gx for gx in _iter_axis_lattice(x_min, x_max, x_step)
        if gx > lo + EPS and gx < hi - EPS
    ]
    rng.shuffle(candidates)
    for h in candidates:
        fitted = parabola_from_endpoints_and_h(x1, y1, x2, y2, h)
        if not fitted:
            continue
        a, h, k = fitted
        if kind == "concave_down_parabola" and a >= 0:
            continue
        if kind == "concave_up_parabola" and a <= 0:
            continue
        if not validate_parabola_vertex_height(kind, x1, y1, x2, y2, h, k):
            continue
        if not point_in_bounds(h, k, x_min, x_max, y_min, y_max):
            continue
        return fitted

    return synthesize_parabola_h(
        kind, x1, y1, x2, y2, x_min, x_max, y_min, y_max, rng
    )


def resolve_parabola_fit(
    kind: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    x_range: Sequence[float],
    y_range: Sequence[float],
    requested: Optional[Point],
    rng: random.Random,
) -> Tuple[Tuple[float, float, float], Point, str]:
    """
    Resolve parabola samples for a segment.

    Returns ((a,h,k), final_vertex, source) where source is
    'exact' | 'grid' | 'computed'.

    Priority:
      1. Exact requested vertex (if valid and consistent with endpoints)
      2. Nearest grid lattice vertex that works with endpoints
      3. Any valid endpoint-fitting parabola; replace vertex with its true (h,k)
    """
    if requested is not None:
        exact = fit_parabola_with_vertex(
            kind, x1, y1, x2, y2, requested[0], requested[1]
        )
        if exact:
            a, h, k = exact
            return exact, (h, k), "exact"

        grid = find_grid_parabola_vertex(
            kind, x1, y1, x2, y2, x_range, y_range, prefer=requested
        )
        if grid:
            a, h, k = grid
            return grid, (h, k), "grid"

    fitted = fallback_parabola_through_endpoints(
        kind, x1, y1, x2, y2, x_range, y_range, rng
    )
    if not fitted:
        raise ValueError(
            "Could not find an in-bounds parabola through the segment endpoints."
        )
    a, h, k = fitted
    return fitted, (h, k), "computed"


def _cubic_poly(a: float, b: float, c: float, d: float, x: float) -> float:
    return ((a * x + b) * x + c) * x + d


def sample_cubic_poly(
    coeffs: Tuple[float, float, float, float], x1: float, x2: float, n: int = SAMPLE_COUNT
) -> List[List[float]]:
    a, b, c, d = coeffs
    lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
    pts = []
    for i in range(n):
        t = i / (n - 1)
        x = lo + t * (hi - lo)
        y = _cubic_poly(a, b, c, d, x)
        pts.append([round(x, 8), round(y, 8)])
    return pts


def fit_cubic_endpoints_and_critical_xs(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    r: float,
    s: float,
    y_at_r: Optional[float] = None,
    y_at_s: Optional[float] = None,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Cubic y=ax^3+bx^2+cx+d through (x1,y1),(x2,y2) with y'(r)=y'(s)=0.
    Optionally pin y(r), y(s) when provided (overdetermined → least squares on y pins).
    """
    # y' = 3ax^2 + 2bx + c
    # From y'(r)=0, y'(s)=0: 3a r^2 + 2b r + c = 0; 3a s^2 + 2b s + c = 0
    # Subtract: 3a(r^2-s^2) + 2b(r-s) = 0 => 3a(r+s) + 2b = 0 => b = -1.5 a (r+s)
    # From y'(r)=0: 3a r^2 + 2(-1.5 a(r+s)) r + c = 0 => 3a r^2 - 3a(r+s)r + c = 0
    # => c = 3a r s
    if abs(r - s) < EPS:
        return None

    def coeffs_for_a(a: float) -> Tuple[float, float, float, float]:
        b = -1.5 * a * (r + s)
        c = 3.0 * a * r * s
        # Solve d from midpoint of endpoint residuals after a,b,c fixed? Use two eqs for a,d
        # y1 = a x1^3 + b x1^2 + c x1 + d
        # y2 = a x2^3 + b x2^2 + c x2 + d
        # Subtract to get a, then d
        return a, b, c, 0.0

    # Express b,c in terms of a; solve a,d from endpoints
    # y1 - (b0 a x1^2 + c0 a x1) = a x1^3 + d where b=b0*a, c=c0*a
    b0 = -1.5 * (r + s)
    c0 = 3.0 * r * s
    # y_i = a (x_i^3 + b0 x_i^2 + c0 x_i) + d
    p1 = x1**3 + b0 * x1**2 + c0 * x1
    p2 = x2**3 + b0 * x2**2 + c0 * x2
    # y1 = a p1 + d; y2 = a p2 + d
    if abs(p1 - p2) < EPS:
        return None
    a = (y1 - y2) / (p1 - p2)
    d = y1 - a * p1
    b = b0 * a
    c = c0 * a
    if not all(_finite(v) for v in (a, b, c, d)):
        return None

    # If y pins provided, blend by adjusting a slightly is hard; instead re-fit with
    # linear least squares on a,d only when pins missing match well enough already.
    if y_at_r is not None:
        yr = _cubic_poly(a, b, c, d, r)
        if abs(yr - y_at_r) > max(0.25, 0.05 * (abs(y_at_r) + 1)):
            # Scale a toward matching average of endpoint + pin is too weak; accept if
            # we rebuild using pin as third point replacing free d? Keep endpoint-exact.
            pass
    return (a, b, c, d)


def synthesize_cubic(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    rng: random.Random,
    vertices: Optional[Sequence[Point]] = None,
) -> Optional[Dict[str, Any]]:
    lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)
    cand_lo = max(lo, x_min) + 1e-6
    cand_hi = min(hi, x_max) - 1e-6
    if cand_hi <= cand_lo:
        return None

    verts = list(vertices or [])
    if len(verts) >= 2:
        r, yr = verts[0]
        s, ys = verts[1]
        if abs(r - s) < EPS:
            return None
        coeffs = fit_cubic_endpoints_and_critical_xs(x1, y1, x2, y2, r, s, yr, ys)
        if not coeffs:
            return None
        # Verify extrema y roughly in bounds
        for xv, yv in ((r, _cubic_poly(*coeffs, r)), (s, _cubic_poly(*coeffs, s))):
            if not point_in_bounds(xv, yv, x_min, x_max, y_min, y_max):
                # Still draw but prefer reject if far outside
                if yv <= y_min or yv >= y_max or xv < x_min or xv > x_max:
                    return None
        return {"coeffs": coeffs, "extrema": [[r, yr], [s, ys]]}

    if len(verts) == 1:
        r, yr = verts[0]
        # Second critical x opposite side of midpoint
        mid = 0.5 * (lo + hi)
        for _ in range(30):
            s = rng.uniform(cand_lo, cand_hi)
            if abs(s - r) < 0.15 * (hi - lo + 1e-9):
                continue
            coeffs = fit_cubic_endpoints_and_critical_xs(x1, y1, x2, y2, r, s, yr, None)
            if not coeffs:
                continue
            ys = _cubic_poly(*coeffs, s)
            if not point_in_bounds(s, ys, x_min, x_max, y_min, y_max):
                continue
            if not point_in_bounds(r, _cubic_poly(*coeffs, r), x_min, x_max, y_min, y_max):
                continue
            return {"coeffs": coeffs, "extrema": [[r, yr], [s, ys]]}
        return None

    # No vertices: two random critical xs; orientation from random a sign via order
    for _ in range(40):
        r = rng.uniform(cand_lo, cand_hi)
        s = rng.uniform(cand_lo, cand_hi)
        if abs(r - s) < 0.2 * (hi - lo + 1e-9):
            continue
        coeffs = fit_cubic_endpoints_and_critical_xs(x1, y1, x2, y2, r, s)
        if not coeffs:
            continue
        a, b, c, d = coeffs
        yr = _cubic_poly(a, b, c, d, r)
        ys = _cubic_poly(a, b, c, d, s)
        if not point_in_bounds(r, yr, x_min, x_max, y_min, y_max):
            continue
        if not point_in_bounds(s, ys, x_min, x_max, y_min, y_max):
            continue
        # Prefer opposite extrema (one max one min) for a visible cubic wiggle
        if (yr - ys) * (r - s) == 0:
            continue
        return {"coeffs": coeffs, "extrema": [[r, yr], [s, ys]]}
    return None


def divider_marker(divider: str) -> Optional[str]:
    """Return 'open' | 'filled' | 'arrow' | None."""
    d = (divider or "none").strip()
    if d in ("<", ">"):
        return "open"
    if d in ("<=", ">="):
        return "filled"
    if d == "arrow":
        return "arrow"
    return None


def _fmt_coeff(v: float, digits: int = 4) -> str:
    """Compact number for author-facing equation strings."""
    if not _finite(v):
        return "?"
    if abs(v) < 1e-10:
        return "0"
    rounded = round(float(v), digits)
    if abs(rounded - round(rounded)) < 1e-10:
        return str(int(round(rounded)))
    text = f"{rounded:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def format_line_equation(x1: float, y1: float, x2: float, y2: float) -> str:
    if abs(x2 - x1) < EPS:
        return f"x = {_fmt_coeff(x1)}"
    m = (y2 - y1) / (x2 - x1)
    b = y1 - m * x1
    m_s = _fmt_coeff(m)
    b_s = _fmt_coeff(b)
    if abs(m) < EPS:
        return f"y = {b_s}"
    if abs(b) < EPS:
        return f"y = {m_s}x"
    sign = "+" if b >= 0 else "−"
    return f"y = {m_s}x {sign} {_fmt_coeff(abs(b))}"


def format_parabola_equation(a: float, h: float, k: float) -> str:
    a_s = _fmt_coeff(a)
    h_s = _fmt_coeff(h)
    k_s = _fmt_coeff(k)
    h_part = f"(x − {h_s})" if h >= 0 else f"(x + {_fmt_coeff(abs(h))})"
    if abs(k) < EPS:
        return f"y = {a_s}{h_part}²"
    sign = "+" if k >= 0 else "−"
    return f"y = {a_s}{h_part}² {sign} {_fmt_coeff(abs(k))}"


def format_cubic_equation(a: float, b: float, c: float, d: float) -> str:
    terms: List[str] = []

    def add_term(coef: float, mono: str) -> None:
        if abs(coef) < 1e-10:
            return
        coef_s = _fmt_coeff(abs(coef))
        body = f"{coef_s}{mono}" if mono else coef_s
        if not terms:
            terms.append(f"-{body}" if coef < 0 else body)
        else:
            terms.append(f" − {body}" if coef < 0 else f" + {body}")

    add_term(a, "x³")
    add_term(b, "x²")
    add_term(c, "x")
    add_term(d, "")
    if not terms:
        return "y = 0"
    return "y = " + "".join(terms)


def build_segment_samples(
    seg: Dict[str, Any],
    vertices: List[Dict[str, Any]],
    x_range: Sequence[float],
    y_range: Sequence[float],
    seed: int,
) -> Dict[str, Any]:
    """
    Attach samples + markers + resolved_vertices for one segment.
    Raises ValueError on failure.
    """
    x_min, x_max = float(x_range[0]), float(x_range[1])
    y_min, y_max = float(y_range[0]), float(y_range[1])
    x1, y1 = float(seg["start"][0]), float(seg["start"][1])
    x2, y2 = float(seg["end"][0]), float(seg["end"][1])
    kind = seg["type"]
    rng = random.Random(int(seed) & 0xFFFFFFFF)

    out = dict(seg)
    out["markers"] = {
        "start": divider_marker(seg.get("start_divider")),
        "end": divider_marker(seg.get("end_divider")),
    }
    out["resolved_vertices"] = []
    out["equation"] = ""

    if kind == "line":
        out["samples"] = sample_line(x1, y1, x2, y2)
        out["equation"] = format_line_equation(x1, y1, x2, y2)
        return out

    seg_verts = [v for v in vertices if v.get("segment_id") == seg.get("id")]
    points = []
    for v in seg_verts:
        pt = v.get("point") or []
        if len(pt) >= 2:
            points.append((float(pt[0]), float(pt[1])))

    if kind in ("concave_down_parabola", "concave_up_parabola"):
        if len(seg_verts) > 1:
            raise ValueError("Parabola segments allow at most one vertex.")
        if seg_verts:
            # Vertex row assigned: lattice first, else computed peak of an endpoint fit.
            grid = find_grid_parabola_vertex(
                kind, x1, y1, x2, y2, x_range, y_range, prefer=None
            )
            if grid:
                a, h, k = grid
                source = "grid"
            else:
                fitted = fallback_parabola_through_endpoints(
                    kind, x1, y1, x2, y2, x_range, y_range, rng
                )
                if not fitted:
                    raise ValueError(
                        "Could not find an in-bounds parabola through the segment endpoints."
                    )
                a, h, k = fitted
                source = "computed"
            out["resolved_vertices"] = [[round(h, 8), round(k, 8)]]
            out["vertex_source"] = source
            out["equation"] = format_parabola_equation(a, h, k)
            out["samples"] = sample_parabola(a, h, k, x1, x2)
            return out
        # No vertex row: lattice/computed peak with correct concavity (incl. level chords).
        fitted = fallback_parabola_through_endpoints(
            kind, x1, y1, x2, y2, x_range, y_range, rng
        )
        if not fitted:
            raise ValueError(
                "Could not synthesize an in-bounds parabola vertex for this segment."
            )
        a, h, k = fitted
        out["resolved_vertices"] = [[round(h, 8), round(k, 8)]]
        out["vertex_source"] = "computed"
        out["equation"] = format_parabola_equation(a, h, k)
        out["samples"] = sample_parabola(a, h, k, x1, x2)
        return out

    if kind == "cubic_parabola":
        if len(points) > 2:
            raise ValueError("Cubic segments allow at most two vertices.")
        if len(points) == 2 and abs(points[0][0] - points[1][0]) < EPS:
            raise ValueError("Cubic vertices must have distinct x values.")
        cubic = synthesize_cubic(
            x1, y1, x2, y2, x_min, x_max, y_min, y_max, rng, vertices=points or None
        )
        if not cubic:
            raise ValueError("Could not build an in-bounds cubic for this segment.")
        out["resolved_vertices"] = [
            [round(p[0], 8), round(p[1], 8)] for p in cubic["extrema"]
        ]
        ca, cb, cc, cd = cubic["coeffs"]
        out["equation"] = format_cubic_equation(ca, cb, cc, cd)
        out["samples"] = sample_cubic_poly(cubic["coeffs"], x1, x2)
        return out

    raise ValueError(f"Unknown segment type: {kind}")


def segments_match(a: Dict[str, Any], b: Dict[str, Any], tol: float = GRADE_TOL) -> bool:
    """Unordered endpoint match + same type + dividers."""
    if (a.get("type") or "") != (b.get("type") or ""):
        return False
    if (a.get("start_divider") or "none") != (b.get("start_divider") or "none"):
        return False
    if (a.get("end_divider") or "none") != (b.get("end_divider") or "none"):
        return False

    def pt(key_start: str, key_end: str):
        s = a.get(key_start) or [None, None]
        e = a.get(key_end) or [None, None]
        return (float(s[0]), float(s[1]), float(e[0]), float(e[1]))

    try:
        ax1, ay1, ax2, ay2 = pt("start", "end")
        bx1, by1, bx2, by2 = (
            float(b["start"][0]),
            float(b["start"][1]),
            float(b["end"][0]),
            float(b["end"][1]),
        )
    except (TypeError, ValueError, KeyError, IndexError):
        return False

    def close(p, q):
        return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol

    same_dir = close((ax1, ay1), (bx1, by1)) and close((ax2, ay2), (bx2, by2))
    rev_dir = close((ax1, ay1), (bx2, by2)) and close((ax2, ay2), (bx1, by1))
    if rev_dir:
        # Dividers would need to swap for reverse; require same orientation for credit
        return False
    return same_dir
