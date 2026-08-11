"""
privacy.py
Privacy-preserving mode: blurs faces before the frame is displayed/recorded,
so the system can count and track people without storing identifiable
footage. Uses OpenCV's bundled Haar cascade — no internet/model download
needed, and it only needs to run inside each already-detected person box,
which keeps it fast.
"""

import cv2
import numpy as np

import config

_face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


def blur_faces_in_boxes(frame: np.ndarray, person_boxes) -> np.ndarray:
    """
    person_boxes: iterable of (x1, y1, x2, y2) person bounding boxes.
    Searches for faces only within each person box (faster + fewer false
    positives than scanning the whole frame), then Gaussian-blurs them.
    """
    h, w = frame.shape[:2]
    for (x1, y1, x2, y2) in person_boxes:
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            continue

        roi = frame[y1:y2, x1:x2]
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        faces = _face_cascade.detectMultiScale(gray_roi, scaleFactor=1.1, minNeighbors=4)

        for (fx, fy, fw, fh) in faces:
            face_region = roi[fy:fy + fh, fx:fx + fw]
            if face_region.size == 0:
                continue
            blurred = cv2.GaussianBlur(face_region, config.FACE_BLUR_KERNEL, 0)
            roi[fy:fy + fh, fx:fx + fw] = blurred

        frame[y1:y2, x1:x2] = roi
    return frame
