"""
optical_flow.py
Dense optical flow (Farneback) based motion-energy anomaly detector.
Sudden, high-magnitude, spatially coordinated motion can indicate a
stampede/rush/panic event even before the person COUNT crosses the
overcrowding threshold — this is the "precursor" signal the report's
literature review calls out as missing from pure counting-based systems.
"""

import cv2
import numpy as np

import config


class OpticalFlowAnalyzer:
    def __init__(self):
        self._prev_gray = None
        self._frame_counter = 0

    def analyze(self, frame: np.ndarray):
        """
        Returns (mean_magnitude: float, is_anomalous: bool, flow_vis: np.ndarray|None)
        flow_vis is a small BGR visualization of the flow field (or None if skipped).
        """
        self._frame_counter += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self._prev_gray is None:
            self._prev_gray = gray
            return 0.0, False, None

        if self._frame_counter % config.FLOW_SAMPLE_EVERY_N_FRAMES != 0:
            return 0.0, False, None

        flow = cv2.calcOpticalFlowFarneback(
            self._prev_gray, gray, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        self._prev_gray = gray

        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
        mean_mag = float(np.mean(magnitude))
        is_anomalous = mean_mag >= config.FLOW_MAGNITUDE_THRESHOLD

        return mean_mag, is_anomalous, magnitude

    @staticmethod
    def draw_motion_indicator(frame, mean_mag: float, is_anomalous: bool):
        h, w = frame.shape[:2]
        color = (0, 0, 255) if is_anomalous else (0, 200, 0)
        label = f"Motion: {mean_mag:.2f}" + ("  RAPID MOVEMENT!" if is_anomalous else "")
        cv2.putText(frame, label, (12, h - 15), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, color, 2, cv2.LINE_AA)
        return frame
