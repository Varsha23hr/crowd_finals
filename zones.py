"""
zones.py
Zone-based ROI density analysis. Each zone is a polygon in normalized
(0-1) coordinates. For every frame we:
  1. Scale each zone's polygon to the current frame size.
  2. Assign every detected person (by centroid) to the zone that contains it.
  3. Compute per-zone counts, per-zone status, and — for zones flagged as
     exits — recommend whichever exit currently has the lowest density.
"""

from typing import List, Tuple, Dict

import numpy as np
import cv2

import config


def scale_polygon(polygon: List[Tuple[float, float]], width: int, height: int) -> np.ndarray:
    return np.array([[int(x * width), int(y * height)] for x, y in polygon], dtype=np.int32)


def build_zones(width: int, height: int) -> List[Dict]:
    """Returns a working copy of config.ZONES with pixel-space polygons attached."""
    zones = []
    for z in config.ZONES:
        zones.append({
            "name": z["name"],
            "polygon_px": scale_polygon(z["polygon"], width, height),
            "threshold": z["threshold"],
            "is_exit": z.get("is_exit", False),
            "count": 0,
        })
    return zones


def assign_and_count(zones: List[Dict], centroids: List[Tuple[int, int]]) -> None:
    """Resets and refills the 'count' field of each zone based on current centroids."""
    for z in zones:
        z["count"] = 0
    for (cx, cy) in centroids:
        for z in zones:
            if cv2.pointPolygonTest(z["polygon_px"], (float(cx), float(cy)), False) >= 0:
                z["count"] += 1
                break  # a person belongs to the first matching zone only


def zone_status(zone: Dict) -> Tuple[str, Tuple[int, int, int]]:
    if zone["count"] >= zone["threshold"]:
        return "CRITICAL", (0, 0, 255)
    if zone["count"] >= zone["threshold"] * 0.6:
        return "WARNING", (0, 200, 255)
    return "SAFE", (0, 200, 0)


def recommend_exit(zones: List[Dict]):
    """Returns (zone_name, count) for the least-congested exit zone, or None."""
    exits = [z for z in zones if z["is_exit"]]
    if not exits:
        return None
    best = min(exits, key=lambda z: z["count"])
    return best["name"], best["count"]


def draw_zones(frame: np.ndarray, zones: List[Dict], recommended_exit) -> np.ndarray:
    overlay = frame.copy()
    for z in zones:
        status, color = zone_status(z)
        cv2.polylines(overlay, [z["polygon_px"]], isClosed=True, color=color, thickness=2)
        cv2.fillPoly(overlay, [z["polygon_px"]], color)

        M = cv2.moments(z["polygon_px"])
        if M["m00"] != 0:
            cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
        else:
            cx, cy = z["polygon_px"][0]

        label = f"{z['name']}: {z['count']}/{z['threshold']}"
        if z["is_exit"]:
            label += " [EXIT]"
        if recommended_exit and z["name"] == recommended_exit[0]:
            label += " <- RECOMMENDED"

        cv2.putText(frame, label, (cx - 60, cy), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (255, 255, 255), 1, cv2.LINE_AA)

    cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
    return frame
