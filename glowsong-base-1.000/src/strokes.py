"""Measuring stroke weight, and restoring it after horizontal compression.

Squeezing a proportional glyph into a monospace cell scales x by s. That thins
vertical stems by s while leaving horizontals untouched, so the latin ends up
lighter than the CJK beside it. Compensation moves x only, which is why the
horizontals survive: a horizontal edge's normal has no horizontal component.

The compensation amount is computed **per edge**. Stroke weights inside one
glyph differ by a factor of two - Song's `N` has 9-unit stems against a 26-unit
diagonal - so no single amount can serve both. Two earlier approaches failed
for that reason: computing from the stems left diagonals thin, and scaling the
amount up for diagonal-heavy characters also scaled up that glyph's own stems.

Everything here assumes **counter-clockwise outer contours**. `_thicken_dx`'s
"outward" direction flips with the winding, so a clockwise source would have its
strokes thinned rather than thickened. Sources are normalised on the way in, see
`vector.Source.reverse_contours`.
"""
from math import hypot

from build.outline import Contour, Point

# Edges flatter than this contribute no thickness measurement: near-horizontal
# edges measure a stroke's length rather than its width.
DX_MEASURE = 0.50

# Floor on the normal's horizontal component when dividing by it, so that a
# near-horizontal edge is not pushed out by a huge multiple.
MIN_NORMAL_COMPONENT = 0.35

# Two edges are treated as one smooth chain while they stay within ~35 degrees.
CHAIN_COS = 0.82

# A ray only measures a stroke when it lands on a roughly anti-parallel edge;
# 0.70 allows 45 degrees of slack for curved flanks.
ANTIPARALLEL_COS = 0.70

# Positions along an edge at which thickness is probed.
PROBE_POSITIONS = (0.1, 0.3, 0.5, 0.7, 0.9)

DX_TIE = 0.05                # |dx| closer than this counts as a tie
PARALLEL_SIN = 0.02          # below this sine, adjacent edges count as parallel
ON_SEGMENT = 0.30            # how far past an edge its intersection may land
MAX_VERTEX_RISE = 24.0       # cap on vertical vertex migration, upem 256


def _thicken_dx(p1: Point, p2: Point) -> float:
    """How far along x the edge p1->p2 must move to make the ink thicker.

    Always `vy / L`, which works for outer and inner contours alike: for a
    counter-clockwise outer contour this is the outward normal's x component,
    and for a clockwise inner contour it is the *inward* normal's. So outer
    contours expand while counters shrink, and both thicken the stroke.

    A vertical edge gives +-1 (full displacement), a horizontal edge 0 (none) -
    exactly "thicken the stems, leave the horizontals alone".
    """
    vy = p2[1] - p1[1]
    length = hypot(p2[0] - p1[0], vy)
    return vy / length if length else 0.0


def _seg_intersect_ray(ox: float, oy: float, nx: float, ny: float,
                       p1: Point, p2: Point) -> float | None:
    """Distance along ray (o, n) to segment p1->p2, or None if it misses."""
    ex, ey = p2[0] - p1[0], p2[1] - p1[1]
    denom = nx * ey - ny * ex
    if abs(denom) < 1e-9:
        return None
    dx, dy = p1[0] - ox, p1[1] - oy
    distance = (dx * ey - dy * ex) / denom
    along = (dx * ny - dy * nx) / denom
    if distance <= 1e-6 or not 0.0 <= along <= 1.0:
        return None
    return distance


def _probe(contours: list[Contour], ci: int, ei: int,
           ox: float, oy: float, nx: float, ny: float,
           ux: float, uy: float, max_reach: float) -> float | None:
    """Nearest hit from one point, casting along the normal in both directions.

    Both directions are needed. Casting one way only works for one winding, and
    on the other the ray finds nothing at all and the compensation drops to
    zero - measured as `M`'s stems crushed to 10% of their width.

    A hit only counts when the edge it lands on runs roughly **anti-parallel**
    to the edge the ray started from, `(ux, uy)`. The two flanks of a stroke
    always do, whichever contour each belongs to, because they are traversed in
    opposite directions. A ray that escapes across a counter or down the inside
    of a stem lands on something perpendicular instead, and the distance it
    reports is the glyph's width rather than a stroke's: `n` measured 120 units
    that way and `g` 101, and thinning from those numbers cut the strokes in
    half.
    """
    best: float | None = None
    for sign in (1.0, -1.0):
        rx, ry = nx * sign, ny * sign
        for cj, other in enumerate(contours):
            count = len(other)
            for ej in range(count):
                if cj == ci and ej == ei:
                    continue
                p1, p2 = other[ej], other[(ej + 1) % count]
                ex, ey = p2[0] - p1[0], p2[1] - p1[1]
                length = hypot(ex, ey)
                if length < 1e-9:
                    continue
                if (ux * ex + uy * ey) / length > -ANTIPARALLEL_COS:
                    continue
                hit = _seg_intersect_ray(ox, oy, rx, ry, p1, p2)
                if hit is not None and hit <= max_reach:
                    if best is None or hit < best:
                        best = hit
    return best


def edge_thickness(contours: list[Contour], ci: int, ei: int,
                   max_reach: float = 120.0) -> tuple[float, float] | None:
    """Stroke thickness along edge `contours[ci][ei]`, as (median, minimum).

    The edge is probed at several points, never just one. A ray fired where a
    crossbar meets a stem travels the whole width of the letter, and whether
    that happens depends on nothing more than where the outline's points fall:
    a stem flank kept as one long edge had its midpoint land exactly at crossbar
    height, so a midpoint-only probe read 78 units instead of 15 and the
    compensation thickened the stems to 175%.

    Both statistics are wanted. The median describes the stroke, and is what any
    weight change should be computed from. The minimum describes its narrowest
    point, which is what has to be protected: where an arch meets a stem the
    stroke thins well below its own median, and taking the median's share off
    there cuts straight through - measured as the joins of `g`, `n` and `u`
    collapsing to half a unit.
    """
    contour = contours[ci]
    count = len(contour)
    p1, p2 = contour[ei], contour[(ei + 1) % count]
    vx, vy = p2[0] - p1[0], p2[1] - p1[1]
    length = hypot(vx, vy)
    if length < 1e-6:
        return None
    nx, ny = -vy / length, vx / length

    samples = []
    for position in PROBE_POSITIONS:
        hit = _probe(contours, ci, ei,
                     p1[0] + vx * position, p1[1] + vy * position,
                     nx, ny, vx / length, vy / length, max_reach)
        if hit is not None:
            samples.append(hit)
    if not samples:
        return None
    samples.sort()
    return samples[len(samples) // 2], samples[0]


def local_thickness(contours: list[Contour], ci: int, ei: int,
                    max_reach: float = 120.0) -> float | None:
    """Median stroke thickness along one edge. See `edge_thickness`."""
    measured = edge_thickness(contours, ci, ei, max_reach)
    return measured[0] if measured else None


def chains(contour: Contour, min_cos: float = CHAIN_COS) -> list[list[int]]:
    """Split a contour's edges into smooth chains, returned as edge indices.

    A chain is one continuous stroke flank. Straight strokes are a single edge;
    a curved flank is the many short edges simplification left behind. Chains
    break at corners and end caps.

    Grouping matters because a curve's flank cannot be judged one edge at a
    time: `o`'s left side is a dozen 10-unit edges across a 23-unit stroke, so
    any per-edge length test would throw the whole thing away.
    """
    count = len(contour)
    directions: list[tuple[float, float]] = []
    for i in range(count):
        p1, p2 = contour[i], contour[(i + 1) % count]
        vx, vy = p2[0] - p1[0], p2[1] - p1[1]
        length = hypot(vx, vy)
        directions.append((vx / length, vy / length) if length > 1e-9 else (0.0, 0.0))

    breaks = [i for i in range(count)
              if directions[i - 1] != (0.0, 0.0) and directions[i] != (0.0, 0.0)
              and directions[i - 1][0] * directions[i][0]
              + directions[i - 1][1] * directions[i][1] < min_cos]
    if not breaks:
        return [list(range(count))]          # smooth all the way round, like `o`

    out: list[list[int]] = []
    for k, start in enumerate(breaks):
        end = breaks[(k + 1) % len(breaks)]
        run, j = [], start
        while True:
            run.append(j)
            j = (j + 1) % count
            if j == end:
                break
        out.append(run)
    return out


def _weighted_median(pairs: list[tuple[float, float]]) -> float:
    """Median of (value, weight) pairs. Weights are edge lengths."""
    pairs = sorted(pairs)
    half = sum(weight for _, weight in pairs) / 2
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= half:
            return value
    return pairs[-1][0]


def compressed_thickness_ratio(dx: float, scale: float) -> float:
    """Fraction of its thickness a stroke keeps after compressing x by `scale`.

    With the stroke at angle phi from vertical, its normal's horizontal
    component is `dx = cos phi` and the thickness becomes

        r(phi) = s / sqrt(s^2 * (1 - dx^2) + dx^2)

    Checks out at both ends: a vertical stroke (dx=1) gives r=s, a horizontal
    one (dx=0) gives r=1. At 45 degrees with s=0.4, r=0.525 - a diagonal loses
    *less* thickness than a stem, so it needs *less* compensation, not more.
    """
    squared = min(1.0, max(0.0, dx * dx))
    denom = (scale * scale * (1.0 - squared) + squared) ** 0.5
    return scale / denom if denom >= 1e-9 else 1.0


def _pick_vertex_shift(sa: float, da: float, sb: float, db: float,
                       tie: float = DX_TIE) -> float:
    """Choose one shift for a vertex from its two adjacent edges.

    Only edges with a non-zero shift compete: otherwise an end cap whose
    measurement was rejected would cancel its neighbour's compensation. When
    both are live, the more vertical edge wins, since it is the one compression
    hits hardest; magnitude only breaks a near-tie.
    """
    a_live, b_live = abs(sa) > 1e-9, abs(sb) > 1e-9
    if not a_live:
        return sb if b_live else 0.0
    if not b_live:
        return sa
    if abs(da - db) > tie:
        return sa if da > db else sb
    return sa if abs(sa) >= abs(sb) else sb


def _offset_vertex(prv: Point, cur: Point, nxt: Point,
                   sa: float, sb: float, da: float, db: float) -> Point:
    """Move a vertex to where its two offset edges now intersect.

    This is exact polygon offsetting. Each edge translates horizontally by its
    own amount - a horizontal edge by zero, so no y coordinate moves - and the
    vertex lands on both translated lines. The intersection may carry some
    vertical movement, which is where a corner genuinely belongs.

    Picking one of the two adjacent shifts instead does not work. Where a thin
    stroke meets a thick one the two edges want opposite directions and differ
    threefold in magnitude, so either choice skews the other edge along its
    whole length: `V`'s thin diagonal dropped from 10 units to 4 that way, `W`'s
    to 2, and `N`'s diagonal fell from 26 to 16.

    Two cases fall back to a single shift: adjacent edges close to parallel,
    where the intersection is numerically unstable and the two amounts are
    nearly equal anyway; and an intersection landing outside both edges' own
    spans, which means the contour has degenerated and offsetting would grow a
    spike.

    Vertical movement is capped separately by `MAX_VERTEX_RISE`. The exact
    answer at a sharp angle is geometrically right but eats the white space:
    restoring `W`'s four strokes after compressing to 0.43 needs more width than
    a half cell has, and the notches close up - the valley floor rises to y=56
    and the gap at y=60 is down to one unit, fusing all four strokes. Some
    stroke weight has to give. Displacement is linear in the two amounts, so
    scaling them back proportionally is enough.
    """
    ax, ay = cur[0] - prv[0], cur[1] - prv[1]
    bx, by = nxt[0] - cur[0], nxt[1] - cur[1]
    len_a, len_b = hypot(ax, ay), hypot(bx, by)
    fallback = (cur[0] + _pick_vertex_shift(sa, da, sb, db), cur[1], cur[2])
    if len_a < 1e-9 or len_b < 1e-9:
        return fallback

    cross = ax * by - ay * bx
    if abs(cross / (len_a * len_b)) < PARALLEL_SIN:
        return fallback

    px, py = prv[0] + sa, prv[1]
    qx, qy = cur[0] + sb, cur[1]
    along_a = ((qx - px) * by - (qy - py) * bx) / cross
    along_b = ((qx - px) * ay - (qy - py) * ax) / cross
    if not -ON_SEGMENT <= along_a <= 1.0 + ON_SEGMENT:
        return fallback
    if not -ON_SEGMENT <= along_b <= 1.0 + ON_SEGMENT:
        return fallback

    mx = px + ax * along_a - cur[0]
    my = py + ay * along_a - cur[1]
    if abs(my) > MAX_VERTEX_RISE:
        factor = MAX_VERTEX_RISE / abs(my)
        mx, my = mx * factor, my * factor
    return (cur[0] + mx, cur[1] + my, cur[2])


def restore_stroke_widths(contours: list[Contour], scale: float,
                          min_component: float = MIN_NORMAL_COMPONENT,
                          max_amount: float = 24.0) -> list[Contour]:
    """Undo the thinning that compressing x by `scale` caused.

    `contours` must be the already-compressed outline, and `scale` the factor
    already applied.

    Per chain: measure the thickness, work out how much of it survived
    compression, and move each edge out by half the difference.

    The thickness that comes back from `local_thickness` is the *compressed*
    one, `t'`. The original is `t = t' / r`, so the normal displacement needed
    is `(t - t') / 2`, i.e. `t' * (1 - r) / (2r)`. Dropping that `/r` halves the
    correction - measured as `H`'s stems going 22 -> 12 and only back to 16.

    Thickness is pooled **per chain**, as a length-weighted median, not taken
    edge by edge. A ray need not cross the stroke it started from: a stem flank
    probed at crossbar height measures the crossbar, reading 61 on `H` and 63 at
    the top of `Z`'s diagonal, and compensating from that pushes the outline out
    by the 24-unit cap and grows a spike. The stem chain's samples read
    [10,10,10,61,10,10,10], whose median is 10.

    A chain whose thickness exceeds its own length is an end cap that measured a
    stroke's length, and is skipped. `N`'s lower serif tip is an 8-unit edge
    whose ray crosses the whole serif for 34; compensating there splays the
    serif by 16 a side, and the ink explodes, so the fitting loop compresses
    harder and the stems collapse with it.

    Only edges with `|dx| >= DX_MEASURE` contribute a measurement, or a fully
    smooth contour like `o` would fold its top - where the ray measures the
    horizontal stroke - into the median and drag the side stems down with it.
    """
    if scale >= 1.0:
        return contours

    out: list[Contour] = []
    for ci, contour in enumerate(contours):
        count = len(contour)
        if count < 3:
            out.append(list(contour))
            continue

        signed_dx = [_thicken_dx(contour[ei], contour[(ei + 1) % count])
                     for ei in range(count)]
        edge_dx = [abs(value) for value in signed_dx]
        edge_shift = [0.0] * count

        for run in chains(contour):
            samples: list[tuple[float, float]] = []
            chain_length = 0.0
            for ei in run:
                p1, p2 = contour[ei], contour[(ei + 1) % count]
                length = hypot(p2[0] - p1[0], p2[1] - p1[1])
                chain_length += length
                if edge_dx[ei] < DX_MEASURE:
                    continue
                thickness = local_thickness(contours, ci, ei)
                if thickness is not None and thickness > 0:
                    samples.append((thickness, length))
            if not samples:
                continue
            thickness = _weighted_median(samples)
            if thickness > chain_length:
                continue                     # an end cap, not a flank

            for ei in run:
                dx = edge_dx[ei]
                if dx < 1e-6:
                    continue
                ratio = compressed_thickness_ratio(dx, scale)
                if ratio <= 1e-6:
                    continue
                normal_shift = thickness * (1.0 - ratio) / (2.0 * ratio)
                shift = min(normal_shift / max(dx, min_component), max_amount)
                edge_shift[ei] = shift if signed_dx[ei] > 0 else -shift

        out.append([_offset_vertex(contour[i - 1], contour[i],
                                   contour[(i + 1) % count],
                                   edge_shift[i - 1], edge_shift[i],
                                   edge_dx[i - 1], edge_dx[i])
                    for i in range(count)])
    return out


def scanline_runs(contours: list[Contour], y: float) -> list[float]:
    """Widths of the ink runs a horizontal line at `y` crosses.

    Edges are treated as straight and off-curve points as ordinary vertices.
    Accurate enough for measuring stroke widths, and it does not require the
    glyph to have truly vertical edges.
    """
    xs: list[float] = []
    for contour in contours:
        count = len(contour)
        for i in range(count):
            p1, p2 = contour[i], contour[(i + 1) % count]
            y1, y2 = p1[1], p2[1]
            if y1 == y2 or not min(y1, y2) <= y < max(y1, y2):
                continue
            along = (y - y1) / (y2 - y1)
            xs.append(p1[0] + along * (p2[0] - p1[0]))
    xs.sort()
    return [xs[i + 1] - xs[i] for i in range(0, len(xs) - 1, 2)]


def visual_center(contours: list[Contour], y_lo: float = 4.0,
                  y_hi: float = 112.0) -> float | None:
    """Horizontal centre of the ink between `y_lo` and `y_hi`.

    Ascenders and descenders are excluded on purpose. `j`'s hook reaches left,
    `f`'s top reaches right and `y`'s tail reaches left, so centring on the full
    bounding box pushes the part of the glyph the eye reads - the stem - off to
    one side. The default band covers x-height, where usually only stems live.
    """
    xs = [p[0] for contour in contours for p in contour if y_lo <= p[1] <= y_hi]
    return (min(xs) + max(xs)) / 2 if xs else None
