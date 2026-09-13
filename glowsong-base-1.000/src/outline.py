"""Contour simplification. Pure functions: points in, fewer points out.

The invariant: an off-curve control point is never deleted as if it were an
ordinary point. Deleting one turns a curve into a straight line and changes the
glyph. Only `flatten_shallow` removes off-curve points, and only when the point
already sits on the chord.

Parameters: upem 256, grid 1, max_err 1.0. Coarse grid
quantisation was measured and rejected (near-zero gain, and it made Song's thin
horizontals uneven), as was dropping tiny contours (no gain at all).
"""
from math import hypot

Point = tuple[int, int, bool]      # (x, y, on_curve)
Contour = list[Point]

MAX_ROUNDS = 8                     # convergence cap, guards against cycling


def quantize(contour: Contour, grid: int = 1) -> Contour:
    """Round coordinates onto `grid`.

    Uses banker's rounding, which avoids a systematic outward bias.
    """
    if grid == 1:
        return [(round(x), round(y), on) for x, y, on in contour]
    return [(round(x / grid) * grid, round(y / grid) * grid, on)
            for x, y, on in contour]


def drop_duplicates(contour: Contour) -> Contour:
    """Drop consecutive repeats, and a last point coinciding with the first.

    Compares the whole triple, not just coordinates: two points at the same
    place with different on-curve flags mean different things.
    """
    out: Contour = []
    for point in contour:
        if not out or point != out[-1]:
            out.append(point)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _cross(o: Point, a: Point, b: Point) -> int:
    """Cross product. Zero means collinear; magnitude scales with deviation."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def drop_collinear(contour: Contour, tol: int = 0) -> Contour:
    """Drop collinear intermediate on-curve points.

    All three consecutive points must be on-curve before the middle one can go.
    An off-curve middle point would straighten a curve; an off-curve neighbour
    would merge two curve segments into one.

    A single pass that never removes adjacent points, which keeps the shape safe
    and avoids quadratic behaviour. Gives up below three points rather than let
    the contour degenerate.
    """
    count = len(contour)
    if count < 4:
        return contour
    out: Contour = []
    just_removed = False
    for i in range(count):
        prv, cur, nxt = contour[i - 1], contour[i], contour[(i + 1) % count]
        removable = (prv[2] and cur[2] and nxt[2]
                     and abs(_cross(prv, cur, nxt)) <= tol)
        if removable and not just_removed:
            just_removed = True
            continue
        out.append(cur)
        just_removed = False
    return out if len(out) >= 3 else contour


def _deviation(a: Point, ctrl: Point, b: Point) -> float:
    """Perpendicular distance from the control point to the chord a-b."""
    chord = hypot(b[0] - a[0], b[1] - a[1])
    if chord == 0:
        return hypot(ctrl[0] - a[0], ctrl[1] - a[1])
    return abs(_cross(a, ctrl, b)) / chord


def flatten_shallow(contour: Contour, max_dev: float = 0.5) -> Contour:
    """Turn shallow arcs into straight lines.

    In an on-off-on run, the off-curve point goes when its distance from the
    chord falls below `max_dev`.

    Two consecutive off-curve points are TrueType's implied-on-curve shorthand
    and are left alone: handling them means interpolating the implied point
    first, which is not worth the complexity for the gain.
    """
    count = len(contour)
    if count < 3:
        return contour
    out: Contour = []
    for i in range(count):
        cur = contour[i]
        if cur[2]:
            out.append(cur)
            continue
        prv, nxt = contour[i - 1], contour[(i + 1) % count]
        if not (prv[2] and nxt[2]):
            out.append(cur)
            continue
        if _deviation(prv, cur, nxt) >= max_dev:
            out.append(cur)
    return out if len(out) >= 3 else contour


def simplify(contours: list[Contour], grid: int = 1, tol: int = 0,
             max_dev: float = 0.5) -> list[Contour]:
    """Run the whole pipeline to a fixed point, so it is idempotent."""
    out: list[Contour] = []
    for contour in contours:
        current = quantize(contour, grid)
        for _ in range(MAX_ROUNDS):
            before = current
            current = drop_duplicates(current)
            current = flatten_shallow(current, max_dev)
            current = drop_collinear(current, tol)
            if current == before:
                break
        if len(current) >= 3:
            out.append(current)
    return out


def count_points(contours: list[Contour]) -> int:
    return sum(len(contour) for contour in contours)


def x_span(contours: list[Contour]) -> tuple[float, float]:
    xs = [p[0] for contour in contours for p in contour]
    return (min(xs), max(xs)) if xs else (0.0, 0.0)
