"""
trend.py
Predictive early warning: fits a simple linear trend to the last
TREND_WINDOW_SECONDS of person-count samples and projects forward
TREND_PREDICTION_SECONDS. If the projected count would cross
CROWD_THRESHOLD, we raise an early warning *before* it actually happens —
giving authorities a head start instead of reacting only after the fact.
"""

import time
from collections import deque

import numpy as np

import config


class TrendAnalyzer:
    def __init__(self):
        self._samples = deque()  # list of (timestamp, count)

    def update(self, count: int):
        now = time.time()
        self._samples.append((now, count))
        cutoff = now - config.TREND_WINDOW_SECONDS
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def predict(self):
        """
        Returns (will_cross: bool, eta_seconds: float|None, projected_count: float|None)
        """
        if len(self._samples) < config.TREND_MIN_SAMPLES:
            return False, None, None

        times = np.array([t for t, _ in self._samples])
        counts = np.array([c for _, c in self._samples])
        t0 = times[0]
        x = times - t0  # seconds since window start, for numerical stability

        # Linear fit: count = slope * t + intercept
        slope, intercept = np.polyfit(x, counts, 1)

        if slope <= 0:
            return False, None, None  # crowd isn't growing, no warning needed

        now_x = times[-1] - t0
        current_projected = slope * now_x + intercept
        future_x = now_x + config.TREND_PREDICTION_SECONDS
        future_projected = slope * future_x + intercept

        if future_projected >= config.CROWD_THRESHOLD and current_projected < config.CROWD_THRESHOLD:
            # Solve for when it crosses the threshold
            eta = (config.CROWD_THRESHOLD - intercept) / slope - now_x
            eta = max(0.0, eta)
            return True, eta, future_projected

        return False, None, None
