"""Copy-move (cloning) indicators. Pure, deterministic; no I/O beyond in-memory PNG encoding.

A cloned region is a patch of the picture that reappears elsewhere in the same
picture, shifted by a constant displacement. We use the textbook block-matching
approach (Fridrich et al. 2003): overlapping blocks are described by a small,
coarsely quantised feature; features are sorted lexicographically so near-identical
blocks become neighbours; pairs whose features agree and whose displacement is
shared by many other pairs point at a duplicated region.

What this can and cannot do:
* It finds *translated* copies only. Rotated, scaled, mirrored or heavily
  retouched copies are not matched.
* Genuinely repeated content (tiles, brickwork, text, patterns, product shots)
  produces the same signal, so a hit is a POSSIBLE signal at most.
* Flat areas (sky, walls) are excluded because every flat block matches every
  other flat block.
* The image is downscaled to a working size first; both copies scale equally, so
  the match survives, but very small clones can be lost.
"""

import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

COPY_MOVE_VERSION = "v1"
METHOD = "copy_move"

BLOCK = 16
STRIDE = 1  # every pixel position; see _block_features
POOL = 4  # feature = BLOCK/POOL x BLOCK/POOL mean-pooled grid
QUANT = 6.0  # grey levels per feature step; absorbs JPEG noise
MIN_BLOCK_STD = 6.0  # flat blocks are ignored
SORT_NEIGHBOURS = 6  # compare each sorted feature with the next k rows
FEATURE_TOLERANCE = 2  # summed |difference| in quantised steps
MIN_SIDE = 96
MAX_REGIONS = 3
# A coherent clone fills its bounding box; scattered coincidences do not.
MIN_DENSITY = 0.15
MAX_PAIRS = 400_000

LIMITATIONS = [
    "Copy-move matching is a heuristic. Repeated real content (tiles, brickwork, text, "
    "patterns, identical products) produces the same signal without any editing.",
    "Only translated copies are found. Rotated, scaled, mirrored or heavily retouched "
    "copies are not matched.",
    "Flat areas are excluded from matching, so a clone within sky, a wall or a shadow is "
    "not assessed.",
    "Analysis runs on a downscaled working copy; very small clones can be lost.",
    "Regions are bounding boxes of matched blocks and may include surrounding pixels.",
]


@dataclass(frozen=True)
class CloneMatch:
    """A source region that reappears displaced by (shift_x, shift_y), original pixel coords."""

    source_x: int
    source_y: int
    target_x: int
    target_y: int
    width: int
    height: int
    shift_x: int
    shift_y: int
    pairs: int
    density: float

    def to_json(self) -> dict[str, Any]:
        return {
            "source_x": self.source_x,
            "source_y": self.source_y,
            "target_x": self.target_x,
            "target_y": self.target_y,
            "width": self.width,
            "height": self.height,
            "shift_x": self.shift_x,
            "shift_y": self.shift_y,
            "pairs": self.pairs,
            "density": self.density,
        }


@dataclass(frozen=True)
class CopyMoveResult:
    measured: bool
    width: int
    height: int
    working_width: int
    working_height: int
    downscaled: bool
    blocks_total: int
    blocks_textured: int
    candidate_pairs: int
    matches: list[CloneMatch]
    detected: bool
    observation: str
    visualization_png: bytes = field(repr=False, default=b"")
    confidence: str = "low"

    def to_json(self) -> dict[str, Any]:
        return {
            "method": METHOD,
            "version": COPY_MOVE_VERSION,
            "applicable": True,
            "measured": self.measured,
            "width": self.width,
            "height": self.height,
            "working_width": self.working_width,
            "working_height": self.working_height,
            "downscaled": self.downscaled,
            "blocks_total": self.blocks_total,
            "blocks_textured": self.blocks_textured,
            "candidate_pairs": self.candidate_pairs,
            "matches": [m.to_json() for m in self.matches],
            "detected": self.detected,
            "confidence": self.confidence,
            "observation": self.observation,
            "limitations": list(LIMITATIONS),
        }


# -- core ---------------------------------------------------------------------------------------


def _load_gray(data: bytes, max_side: int) -> tuple[NDArray[np.float32], int, int, bool]:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        ow, oh = img.size
        g = img.convert("L")
    downscaled = False
    if max(ow, oh) > max_side:
        scale = max_side / max(ow, oh)
        g = g.resize((max(1, round(ow * scale)), max(1, round(oh * scale))), Image.Resampling.BOX)
        downscaled = True
    return np.asarray(g, dtype=np.float32), ow, oh, downscaled


def _window_mean(gray: NDArray[np.float32], size: int) -> NDArray[np.float32]:
    """Mean of every size x size window (top-left anchored) via an integral image."""
    ii = np.zeros((gray.shape[0] + 1, gray.shape[1] + 1), dtype=np.float64)
    ii[1:, 1:] = gray.cumsum(axis=0).cumsum(axis=1)
    s = ii[size:, size:] - ii[:-size, size:] - ii[size:, :-size] + ii[:-size, :-size]
    return (s / (size * size)).astype(np.float32)


def _block_features(
    gray: NDArray[np.float32],
) -> tuple[NDArray[np.int8], NDArray[np.int32], NDArray[np.int32], int]:
    """Quantised mean-pooled features for every textured block at *every* pixel position.

    A clone can sit at any offset, so the block grid must have stride 1; integral
    images keep that cheap. Returns (feat, ys, xs, total_blocks).
    """
    h, w = gray.shape
    p = BLOCK // POOL
    ny, nx = h - BLOCK + 1, w - BLOCK + 1
    if ny <= 0 or nx <= 0:
        return np.zeros((0, p * p), np.int8), np.zeros(0, np.int32), np.zeros(0, np.int32), 0
    m4 = _window_mean(gray, POOL)  # (h-3, w-3): 4x4 mean anchored at each pixel
    m16 = _window_mean(gray, BLOCK)  # block mean
    sq16 = _window_mean(gray * gray, BLOCK)
    std = np.sqrt(np.maximum(sq16 - m16 * m16, 0.0))  # (ny, nx)
    keep = std >= MIN_BLOCK_STD
    ys, xs = np.nonzero(keep)
    feat = np.empty((len(ys), p * p), dtype=np.int8)
    for i in range(p):
        for j in range(p):
            feat[:, i * p + j] = np.clip(
                np.round(m4[ys + i * POOL, xs + j * POOL] / QUANT), -127, 127
            ).astype(np.int8)
    return feat, ys.astype(np.int32), xs.astype(np.int32), ny * nx


def _candidate_pairs(
    feat: NDArray[np.int8], ys: NDArray[np.int32], xs: NDArray[np.int32], min_shift: int
) -> tuple[NDArray[np.int32], NDArray[np.int32], int]:
    """Indices (a, b) of near-identical blocks >= ``min_shift`` px apart, plus a count weight.

    The weight is > 1 only when the pair list was subsampled (repeating patterns).
    """
    if len(feat) < 2:
        return np.zeros(0, np.int32), np.zeros(0, np.int32), 1
    # Pack the 16 small non-negative features into two 64-bit keys: one sort instead of 16.
    v = np.clip(feat.astype(np.int64), 0, 63)
    shifts = (np.arange(8, dtype=np.int64) * 6)[::-1]
    key1 = (v[:, :8] << shifts).sum(axis=1)
    key2 = (v[:, 8:] << shifts).sum(axis=1)
    order = np.lexsort((key2, key1))
    sf, sy, sx = feat[order], ys[order], xs[order]
    a_list: list[NDArray[np.int32]] = []
    b_list: list[NDArray[np.int32]] = []
    for k in range(1, SORT_NEIGHBOURS + 1):
        if k >= len(sf):
            break
        d = np.abs(sf[k:].astype(np.int16) - sf[:-k].astype(np.int16)).sum(axis=1)
        dy = sy[k:] - sy[:-k]
        dx = sx[k:] - sx[:-k]
        ok = (d <= FEATURE_TOLERANCE) & (np.maximum(np.abs(dx), np.abs(dy)) >= min_shift)
        i = np.nonzero(ok)[0]
        a_list.append(order[i].astype(np.int32))
        b_list.append(order[i + k].astype(np.int32))
    a = np.concatenate(a_list) if a_list else np.zeros(0, np.int32)
    b = np.concatenate(b_list) if b_list else np.zeros(0, np.int32)
    weight = 1
    if len(a) > MAX_PAIRS:  # repeating patterns explode; a deterministic subsample suffices
        weight = -(-len(a) // MAX_PAIRS)
        a, b = a[::weight], b[::weight]
    return a.astype(np.int32), b.astype(np.int32), weight


def _paint(
    mask: NDArray[np.uint8], ys: NDArray[np.int32], xs: NDArray[np.int32], value: int
) -> None:
    """Mark every pixel covered by a BLOCK x BLOCK block anchored at (ys, xs); vectorised."""
    h, w = mask.shape
    anchors = np.zeros((h + BLOCK - 1, w + BLOCK - 1), dtype=np.float32)
    anchors[ys + BLOCK - 1, xs + BLOCK - 1] = 1.0
    covered = _window_mean(anchors, BLOCK) > 0  # (h, w): any anchor in [y-15..y] x [x-15..x]
    mask[covered] = np.maximum(mask[covered], value)


def _observation(*, measured: bool, detected: bool, matches: list[CloneMatch]) -> str:
    if not measured:
        return "The image is too small for block matching."
    if detected:
        m = matches[0]
        return (
            f"{len(matches)} duplicated region(s) found. The largest, about {m.width} x {m.height} "
            f"px at ({m.source_x}, {m.source_y}), reappears displaced by ({m.shift_x}, "
            f"{m.shift_y}) px ({m.pairs} matching block pairs). This is consistent with a "
            "copy-move (cloning) edit, and equally with genuinely repeated content such as "
            "tiles, patterns or text."
        )
    return (
        "No translated duplicate regions were found. Rotated, scaled or retouched copies, "
        "and clones inside flat areas, would not be detected."
    )


def analyze_copy_move(
    data: bytes, *, max_side: int = 1024, min_matches: int = 200, min_shift: int = 32
) -> CopyMoveResult:
    gray, ow, oh, downscaled = _load_gray(data, max_side)
    h, w = gray.shape
    if h < MIN_SIDE or w < MIN_SIDE:
        return CopyMoveResult(
            False, ow, oh, w, h, downscaled, 0, 0, 0, [], False,
            _observation(measured=False, detected=False, matches=[]),
        )  # fmt: skip

    feat, ys, xs, total = _block_features(gray)
    a, b, weight = _candidate_pairs(feat, ys, xs, min_shift)
    sx_, sy_ = ow / w, oh / h
    matches: list[CloneMatch] = []
    mask = np.zeros((h, w), dtype=np.uint8)

    if len(a):
        # Canonical displacement: make (dx, dy) point "forward" so a<->b order does not matter.
        dx = xs[b] - xs[a]
        dy = ys[b] - ys[a]
        flip = (dx < 0) | ((dx == 0) & (dy < 0))
        dx = np.where(flip, -dx, dx)
        dy = np.where(flip, -dy, dy)
        src_x = np.where(flip, xs[b], xs[a])
        src_y = np.where(flip, ys[b], ys[a])
        key = dy.astype(np.int64) * (2 * w + 1) + dx.astype(np.int64)
        _, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
        for gi in np.argsort(counts)[::-1][: MAX_REGIONS * 4]:
            n = int(counts[gi]) * weight
            if n < min_matches:
                break
            sel = inverse == gi
            bx0, bx1 = int(src_x[sel].min()), int(src_x[sel].max()) + BLOCK
            by0, by1 = int(src_y[sel].min()), int(src_y[sel].max()) + BLOCK
            area = (bx1 - bx0) * (by1 - by0)
            density = n * STRIDE * STRIDE / max(area, 1)
            if density < MIN_DENSITY:
                continue
            ddx, ddy = int(dx[sel][0]), int(dy[sel][0])
            matches.append(
                CloneMatch(
                    source_x=round(bx0 * sx_),
                    source_y=round(by0 * sy_),
                    target_x=round((bx0 + ddx) * sx_),
                    target_y=round((by0 + ddy) * sy_),
                    width=max(1, round((bx1 - bx0) * sx_)),
                    height=max(1, round((by1 - by0) * sy_)),
                    shift_x=round(ddx * sx_),
                    shift_y=round(ddy * sy_),
                    pairs=n,
                    density=round(float(density), 3),
                )
            )
            _paint(mask, src_y[sel], src_x[sel], 128)
            _paint(mask, src_y[sel] + ddy, src_x[sel] + ddx, 255)
            if len(matches) >= MAX_REGIONS:
                break

    detected = len(matches) > 0
    out = io.BytesIO()
    Image.fromarray(mask, mode="L").save(out, format="PNG", optimize=True)
    return CopyMoveResult(
        measured=True,
        width=ow,
        height=oh,
        working_width=w,
        working_height=h,
        downscaled=downscaled,
        blocks_total=total,
        blocks_textured=len(feat),
        candidate_pairs=len(a) * weight,
        matches=matches,
        detected=detected,
        observation=_observation(measured=True, detected=detected, matches=matches),
        visualization_png=out.getvalue(),
    )
