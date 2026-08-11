"""
heatmap.py
Builds a grid-based crowd density heatmap and blends it onto the frame.
Unlike a single aggregate count, this shows WHERE density is building up.
"""

from typing import List, Tuple

import numpy as np
import cv2

import config


def compute_heatmap_overlay(frame: np.ndarray, centroids: List[Tuple[int, int]]) -> np.ndarray:
    h, w = frame.shape[:2]
    cols, rows = config.HEATMAP_GRID_COLS, config.HEATMAP_GRID_ROWS
    cell_w, cell_h = w / cols, h / rows

    grid = np.zeros((rows, cols), dtype=np.float32)
    for (cx, cy) in centroids:
        col = min(int(cx / cell_w), cols - 1)
        row = min(int(cy / cell_h), rows - 1)
        grid[row, col] += 1

    if grid.max() > 0:
        norm = (grid / grid.max() * 255).astype(np.uint8)
    else:
        norm = grid.astype(np.uint8)

    # Upscale the small grid to full frame size with smoothing, then colorize
    heat_small = cv2.resize(norm, (w, h), interpolation=cv2.INTER_CUBIC)
    heat_small = cv2.GaussianBlur(heat_small, (0, 0), sigmaX=w / (cols * 2))
    heat_color = cv2.applyColorMap(heat_small, cv2.COLORMAP_JET)

    blended = cv2.addWeighted(heat_color, config.HEATMAP_ALPHA, frame, 1 - config.HEATMAP_ALPHA, 0)
    return blended
