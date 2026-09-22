"""Connected-region labelling over a block grid. Shared by the block-based forensic methods."""

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class Region:
    """A connected cluster of flagged blocks, in *original* image pixel coordinates."""

    x: int
    y: int
    width: int
    height: int
    blocks: int
    value: float  # mean of the per-block statistic over the cluster

    def to_json(self, value_key: str = "value") -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "blocks": self.blocks,
            value_key: self.value,
        }


def connected_regions(
    mask: NDArray[np.bool_],
    values: NDArray[np.floating[Any]],
    *,
    block: int,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    min_blocks: int = 2,
    max_regions: int = 8,
) -> list[Region]:
    """4-connected components of ``mask``, largest first, scaled to original pixel coordinates."""
    bh, bw = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    found: list[Region] = []
    for sy in range(bh):
        for sx in range(bw):
            if not mask[sy, sx] or seen[sy, sx]:
                continue
            queue: deque[tuple[int, int]] = deque([(sy, sx)])
            seen[sy, sx] = True
            cells: list[tuple[int, int]] = []
            while queue:
                y, x = queue.popleft()
                cells.append((y, x))
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < bh and 0 <= nx < bw and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
            if len(cells) < min_blocks:
                continue
            ys = [c[0] for c in cells]
            xs = [c[1] for c in cells]
            x0, x1 = min(xs) * block, (max(xs) + 1) * block
            y0, y1 = min(ys) * block, (max(ys) + 1) * block
            found.append(
                Region(
                    x=round(x0 * scale_x),
                    y=round(y0 * scale_y),
                    width=max(1, round((x1 - x0) * scale_x)),
                    height=max(1, round((y1 - y0) * scale_y)),
                    blocks=len(cells),
                    value=round(float(np.mean([values[y, x] for y, x in cells])), 2),
                )
            )
    found.sort(key=lambda r: r.blocks, reverse=True)
    return found[:max_regions]
