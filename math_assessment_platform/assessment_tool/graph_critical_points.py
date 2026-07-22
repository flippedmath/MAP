"""
Critical-point annotations for the graph entity: extrema, inflection, intercepts.
Labels are display-only letters a, b, c… sorted left-to-right by x.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import sympy as sp
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

EPS = 1e-9
SAMPLE_COUNT = 320


def _coerce_bool(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ("true", "1", "yes", "checked", "on")


def index_to_label(index: int) -> str:
    """0 -> a, 25 -> z, 26 -> aa, …"""
    if index < 0:
        return "?"
    n = index
    chars: List[str] = []
    while True:
        chars.append(chr(ord("a") + (n % 26)))
        n = n // 26 - 1
        if n < 0:
            break
    return "".join(reversed(chars))


def extract_rhs(formula: str) -> Optional[str]:
    """
    Pull an explicit y = f(x) (or f(x) = …) RHS from a formula string.
    Returns None when the formula is not an explicit function of x alone.
    """
    if not formula or not str(formula).strip():
        return None
    text = str(formula).strip()
    # functionPlot-friendly caret powers
    text = text.replace("**", "^")

    if "=" in text:
        left, right = text.split("=", 1)
        left = left.strip()
        right = right.strip()
        # y = … or f(x) = …
        if re.fullmatch(r"[yY]", left) or re.fullmatch(r"[a-zA-Z]\d*\(\s*[xX]\s*\)", left):
            return right or None
        # … = y  (rare) — treat left as RHS
        if re.fullmatch(r"[yY]", right):
            return left or None
        # Bare "lhs = rhs" where lhs is not y: skip (implicit / relation)
        return None

    # Bare expression treated as y = expr
    return text


def _parse_expr(rhs: str, x: sp.Symbol) -> Optional[sp.Expr]:
    try:
        cleaned = rhs.replace("^", "**")
        transformations = standard_transformations + (implicit_multiplication_application,)
        expr = parse_expr(
            cleaned,
            local_dict={"x": x, "X": x},
            transformations=transformations,
            evaluate=True,
        )
        if not isinstance(expr, sp.Expr):
            return None
        free = {str(s) for s in expr.free_symbols}
        # Allow only x (and numeric constants)
        if free - {"x"}:
            return None
        return sp.simplify(expr)
    except Exception:
        return None


def _finite_float(val: Any) -> Optional[float]:
    try:
        if val is None:
            return None
        if isinstance(val, sp.Basic):
            if val.has(sp.oo, -sp.oo, sp.zoo, sp.nan):
                return None
            val = complex(val.evalf())
            if abs(val.imag) > 1e-8:
                return None
            f = float(val.real)
        else:
            f = float(val)
        if not math.isfinite(f):
            return None
        return f
    except Exception:
        return None


def _eval_f(expr: sp.Expr, x: sp.Symbol, x_val: float) -> Optional[float]:
    try:
        return _finite_float(expr.subs(x, x_val).evalf())
    except Exception:
        return None


def _in_bounds(v: float, lo: float, hi: float, pad: float = 0.0) -> bool:
    return (lo - pad) <= v <= (hi + pad)


def _collect_roots_exact(expr: sp.Expr, x: sp.Symbol, x_min: float, x_max: float) -> List[float]:
    roots: List[float] = []
    try:
        sol = sp.solveset(sp.Eq(expr, 0), x, domain=sp.Reals)
        if isinstance(sol, sp.FiniteSet):
            for item in sol:
                fv = _finite_float(item)
                if fv is not None and _in_bounds(fv, x_min, x_max):
                    roots.append(fv)
            return roots
    except Exception:
        pass
    try:
        sols = sp.solve(sp.Eq(expr, 0), x)
        if not isinstance(sols, (list, tuple)):
            sols = [sols]
        for item in sols:
            fv = _finite_float(item)
            if fv is not None and _in_bounds(fv, x_min, x_max):
                roots.append(fv)
    except Exception:
        pass
    return roots


def _collect_roots_numeric(
    expr: sp.Expr, x: sp.Symbol, x_min: float, x_max: float, n: int = SAMPLE_COUNT
) -> List[float]:
    """Sign-change brackets + nsolve fallback."""
    roots: List[float] = []
    if x_max <= x_min:
        return roots

    xs: List[float] = []
    ys: List[Optional[float]] = []
    for i in range(n + 1):
        xv = x_min + (x_max - x_min) * (i / n)
        xs.append(xv)
        ys.append(_eval_f(expr, x, xv))

    brackets: List[Tuple[float, float]] = []
    for i in range(len(xs) - 1):
        a, b = ys[i], ys[i + 1]
        if a is None or b is None:
            continue
        if abs(a) < 1e-10:
            roots.append(xs[i])
            continue
        if a * b < 0:
            brackets.append((xs[i], xs[i + 1]))

    f_num = sp.lambdify(x, expr, modules=["math"])
    for lo, hi in brackets:
        mid = 0.5 * (lo + hi)
        found = None
        try:
            found = float(sp.nsolve(expr, x, mid))
        except Exception:
            # Bisection fallback
            a, b = lo, hi
            fa = _eval_f(expr, x, a)
            for _ in range(40):
                m = 0.5 * (a + b)
                fm = _eval_f(expr, x, m)
                if fa is None or fm is None:
                    break
                if abs(fm) < 1e-10 or (b - a) < 1e-8:
                    found = m
                    break
                if fa * fm <= 0:
                    b = m
                else:
                    a, fa = m, fm
            else:
                found = 0.5 * (a + b)
        if found is not None and _in_bounds(found, x_min, x_max):
            # Verify it's near a zero
            yv = _eval_f(expr, x, found)
            if yv is not None and abs(yv) < 1e-2 * max(1.0, abs(x_max - x_min)):
                roots.append(found)
            elif yv is not None and abs(yv) < 0.5:
                # looser for noisy samples
                try:
                    if abs(f_num(found)) < 0.25:
                        roots.append(found)
                except Exception:
                    roots.append(found)

    return roots


def _unique_sorted_roots(values: Sequence[float], tol: float) -> List[float]:
    cleaned = sorted(v for v in values if math.isfinite(v))
    if not cleaned:
        return []
    out = [cleaned[0]]
    for v in cleaned[1:]:
        if abs(v - out[-1]) > tol:
            out.append(v)
    return out


def _concavity_changes(f2: sp.Expr, x: sp.Symbol, xv: float, span: float) -> bool:
    delta = max(1e-4, 0.01 * abs(span) if span else 1e-3)
    left = _eval_f(f2, x, xv - delta)
    right = _eval_f(f2, x, xv + delta)
    if left is None or right is None:
        # Fall back to third derivative sign
        try:
            f3 = sp.diff(f2, x)
            t = _eval_f(f3, x, xv)
            return t is not None and abs(t) > 1e-10
        except Exception:
            return True
    return left * right < 0 or (abs(left) < 1e-10) != (abs(right) < 1e-10)


def collect_points_for_formula(
    formula: str,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> List[Dict[str, Any]]:
    """Return unlabeled point dicts for one explicit y=f(x) formula."""
    rhs = extract_rhs(formula)
    if rhs is None:
        return []

    x = sp.symbols("x")
    expr = _parse_expr(rhs, x)
    if expr is None:
        return []

    span = max(abs(x_max - x_min), 1e-6)
    tol = max(1e-4, 1e-3 * span)
    points: List[Dict[str, Any]] = []

    try:
        f1 = sp.diff(expr, x)
        f2 = sp.diff(f1, x)
    except Exception:
        return []

    def add_point(xv: float, kind: str) -> None:
        if not _in_bounds(xv, x_min, x_max):
            return
        yv = _eval_f(expr, x, xv)
        if yv is None or not _in_bounds(yv, y_min, y_max):
            return
        points.append({
            "x": round(float(xv), 8),
            "y": round(float(yv), 8),
            "kind": kind,
        })

    # Extrema: f' = 0
    ext_roots = _collect_roots_exact(f1, x, x_min, x_max)
    if not ext_roots:
        ext_roots = _collect_roots_numeric(f1, x, x_min, x_max)
    for xv in _unique_sorted_roots(ext_roots, tol):
        add_point(xv, "extremum")

    # Inflection: f'' = 0 with concavity change
    inf_roots = _collect_roots_exact(f2, x, x_min, x_max)
    if not inf_roots:
        inf_roots = _collect_roots_numeric(f2, x, x_min, x_max)
    for xv in _unique_sorted_roots(inf_roots, tol):
        if _concavity_changes(f2, x, xv, span):
            add_point(xv, "inflection")

    # X-intercepts: f = 0
    xint_roots = _collect_roots_exact(expr, x, x_min, x_max)
    if not xint_roots:
        xint_roots = _collect_roots_numeric(expr, x, x_min, x_max)
    for xv in _unique_sorted_roots(xint_roots, tol):
        add_point(xv, "x_intercept")

    # Y-intercept
    if _in_bounds(0.0, x_min, x_max):
        add_point(0.0, "y_intercept")

    return points


def build_critical_annotations(
    formulas: Sequence[str],
    x_range: Sequence[float],
    y_range: Sequence[float],
) -> List[Dict[str, Any]]:
    """
    Collect critical points across all formulas and assign shared letters a, b, c…
    sorted by ascending x (then y).
    """
    try:
        x_min, x_max = float(x_range[0]), float(x_range[1])
        y_min, y_max = float(y_range[0]), float(y_range[1])
    except (TypeError, ValueError, IndexError):
        return []

    if not (math.isfinite(x_min) and math.isfinite(x_max) and x_min < x_max):
        return []
    if not (math.isfinite(y_min) and math.isfinite(y_max) and y_min < y_max):
        return []

    all_points: List[Dict[str, Any]] = []
    for formula in formulas or []:
        try:
            all_points.extend(
                collect_points_for_formula(str(formula), x_min, x_max, y_min, y_max)
            )
        except Exception:
            continue

    if not all_points:
        return []

    span = max(abs(x_max - x_min), 1e-6)
    tol = max(1e-4, 1e-3 * span)

    # Deduplicate near-identical (x,y), prefer keeping first kind encountered after sort
    all_points.sort(key=lambda p: (p["x"], p["y"], p.get("kind") or ""))
    deduped: List[Dict[str, Any]] = []
    for p in all_points:
        if deduped and abs(p["x"] - deduped[-1]["x"]) <= tol and abs(p["y"] - deduped[-1]["y"]) <= tol:
            # Prefer y_intercept / extremum labels when overlapping kinds at same spot
            kind_rank = {
                "extremum": 0,
                "inflection": 1,
                "x_intercept": 2,
                "y_intercept": 3,
            }
            if kind_rank.get(p["kind"], 9) < kind_rank.get(deduped[-1]["kind"], 9):
                deduped[-1] = p
            continue
        deduped.append(p)

    annotations: List[Dict[str, Any]] = []
    for i, p in enumerate(deduped):
        annotations.append({
            "label": index_to_label(i),
            "x": p["x"],
            "y": p["y"],
            "kind": p["kind"],
        })
    return annotations
