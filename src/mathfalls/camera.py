from __future__ import annotations

import os
import math
from pathlib import Path
import time
from dataclasses import dataclass

import tempfile

_temp_dir = Path(tempfile.gettempdir())
os.environ.setdefault("MPLCONFIGDIR", str(_temp_dir / "mathfalls-mpl"))
os.environ.setdefault("XDG_CACHE_HOME", str(_temp_dir / "mathfalls-cache"))

import cv2
from mediapipe.python.solutions import face_mesh, hands


def discover_cameras(max_index: int = 6) -> list[int]:
    cameras: list[int] = []
    for index in range(max_index):
        capture = cv2.VideoCapture(index)
        if capture.isOpened():
            ok, _ = capture.read()
            if ok:
                cameras.append(index)
        capture.release()
    return cameras or [0]


@dataclass
class FaceState:
    face_id: int
    x: float
    y: float
    eyes_closed: bool
    mouth_open: bool
    blink_event: bool
    mouth_event: bool
    seen_at: float


@dataclass
class HandState:
    x: float
    y: float
    open_palm: bool
    fingers_up: int


class CameraTracker:
    def __init__(self, camera_index: int = 0) -> None:
        self.flip_horizontal = True
        self.capture = cv2.VideoCapture(camera_index)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self._mesh = None
        self._hands = None
        self._backend = "haar"
        self._hands_backend = "opencv"
        try:
            self._mesh = face_mesh.FaceMesh(
                max_num_faces=2,
                refine_landmarks=True,
                min_detection_confidence=0.55,
                min_tracking_confidence=0.55,
            )
            self._backend = "facemesh"
        except RuntimeError as exc:
            print(f"FaceMesh no pudo iniciar; usando fallback OpenCV: {exc}")

        try:
            self._hands = hands.Hands(
                static_image_mode=False,
                max_num_hands=4,
                min_detection_confidence=0.55,
                min_tracking_confidence=0.55,
            )
            self._hands_backend = "mediapipe"
        except RuntimeError as exc:
            print(f"Hands no pudo iniciar; usando fallback OpenCV para palmas: {exc}")

        cascade_dir = Path(cv2.data.haarcascades)
        self._face_cascade = cv2.CascadeClassifier(str(cascade_dir / "haarcascade_frontalface_default.xml"))
        self._eye_cascade = cv2.CascadeClassifier(str(cascade_dir / "haarcascade_eye_tree_eyeglasses.xml"))
        self._smile_cascade = cv2.CascadeClassifier(str(cascade_dir / "haarcascade_smile.xml"))
        self._last_eyes: dict[int, bool] = {}
        self._last_mouth: dict[int, bool] = {}
        self.last_frame_rgb = None
        self.hands: list[HandState] = []
        self.open_palms = 0
        self.fingers_up = 0

    def close(self) -> None:
        self.capture.release()
        if self._mesh is not None:
            self._mesh.close()
        if self._hands is not None:
            self._hands.close()

    def read(self) -> tuple[bool, list[FaceState]]:
        ok, frame = self.capture.read()
        if not ok:
            return False, []
        if self.flip_horizontal:
            frame = cv2.flip(frame, 1)

        self.last_frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._update_hands(self.last_frame_rgb)

        if self._backend == "haar" or self._mesh is None:
            return True, self._read_haar(frame)

        return True, self._read_facemesh(self.last_frame_rgb)

    def _read_facemesh(self, rgb_frame) -> list[FaceState]:
        result = self._mesh.process(rgb_frame)
        if not result.multi_face_landmarks:
            self._last_eyes.clear()
            self._last_mouth.clear()
            return []

        raw_faces = []
        for landmarks in result.multi_face_landmarks[:2]:
            points = landmarks.landmark
            cx = sum(point.x for point in points) / len(points)
            cy = sum(point.y for point in points) / len(points)
            raw_faces.append((cx, cy, points))

        raw_faces.sort(key=lambda item: item[0])
        now = time.monotonic()
        faces: list[FaceState] = []
        for face_id, (cx, cy, points) in enumerate(raw_faces):
            ear = (_eye_ratio(points, (33, 133, 159, 145)) + _eye_ratio(points, (263, 362, 386, 374))) / 2
            mar = _mouth_ratio(points)
            eyes_closed = ear < 0.18
            mouth_open = mar > 0.32
            blink_event = eyes_closed and not self._last_eyes.get(face_id, False)
            mouth_event = mouth_open and not self._last_mouth.get(face_id, False)
            self._last_eyes[face_id] = eyes_closed
            self._last_mouth[face_id] = mouth_open
            faces.append(
                FaceState(
                    face_id=face_id,
                    x=_clamp(cx, 0.0, 1.0),
                    y=_clamp(cy, 0.0, 1.0),
                    eyes_closed=eyes_closed,
                    mouth_open=mouth_open,
                    blink_event=blink_event,
                    mouth_event=mouth_event,
                    seen_at=now,
                )
            )

        return faces

    def _update_hands(self, rgb_frame) -> None:
        self.hands = []
        self.open_palms = 0
        self.fingers_up = 0
        if self._hands is None:
            self._update_hands_opencv(rgb_frame)
            return

        result = self._hands.process(rgb_frame)
        if not result.multi_hand_landmarks:
            return

        handedness = result.multi_handedness or []
        for index, hand_landmarks in enumerate(result.multi_hand_landmarks[:4]):
            points = hand_landmarks.landmark
            label = ""
            if index < len(handedness) and handedness[index].classification:
                label = handedness[index].classification[0].label
            fingers_up = _fingers_up(points, label)
            open_palm = fingers_up >= 4
            cx = sum(point.x for point in points) / len(points)
            cy = sum(point.y for point in points) / len(points)
            self.hands.append(
                HandState(
                    x=_clamp(cx, 0.0, 1.0),
                    y=_clamp(cy, 0.0, 1.0),
                    open_palm=open_palm,
                    fingers_up=fingers_up,
                )
            )
            if open_palm:
                self.open_palms += 1
            self.fingers_up = max(self.fingers_up, min(fingers_up, 4))

    def _update_hands_opencv(self, rgb_frame) -> None:
        ycrcb = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2YCrCb)
        mask = cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        height, width = mask.shape[:2]

        candidates: list[tuple[float, HandState]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 2500:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w < 35 or h < 45:
                continue
            ratio = w / max(h, 1)
            if ratio < 0.18 or ratio > 2.7:
                continue
            defects = _convexity_defect_count(contour)
            hull_area = cv2.contourArea(cv2.convexHull(contour))
            solidity = area / max(hull_area, 1)
            fingers_up = int(_clamp(defects + 1, 1, 4))
            open_palm = defects >= 3 or (area > 9000 and solidity < 0.82)
            hand = HandState(
                x=_clamp((x + w / 2) / width, 0.0, 1.0),
                y=_clamp((y + h / 2) / height, 0.0, 1.0),
                open_palm=open_palm,
                fingers_up=fingers_up,
            )
            candidates.append((area, hand))

        candidates.sort(key=lambda item: item[0], reverse=True)
        self.hands = [hand for _, hand in candidates[:4]]
        self.open_palms = sum(1 for hand in self.hands if hand.open_palm)
        self.fingers_up = max((hand.fingers_up for hand in self.hands), default=0)

    def _read_haar(self, frame) -> list[FaceState]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detections = self._face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(90, 90))
        faces_rects = sorted(detections, key=lambda rect: rect[0])[:2]
        if len(faces_rects) == 0:
            self._last_eyes.clear()
            self._last_mouth.clear()
            return []

        height, width = gray.shape[:2]
        now = time.monotonic()
        faces: list[FaceState] = []
        for face_id, (x, y, w, h) in enumerate(faces_rects):
            roi = gray[y : y + h, x : x + w]
            upper = roi[: h // 2, :]
            lower = roi[h // 2 :, :]
            eyes = self._eye_cascade.detectMultiScale(upper, scaleFactor=1.1, minNeighbors=4, minSize=(18, 18))
            smiles = self._smile_cascade.detectMultiScale(lower, scaleFactor=1.7, minNeighbors=18, minSize=(30, 20))

            eyes_closed = len(eyes) == 0
            mouth_open = len(smiles) > 0
            blink_event = eyes_closed and not self._last_eyes.get(face_id, False)
            mouth_event = mouth_open and not self._last_mouth.get(face_id, False)
            self._last_eyes[face_id] = eyes_closed
            self._last_mouth[face_id] = mouth_open

            faces.append(
                FaceState(
                    face_id=face_id,
                    x=_clamp((x + w / 2) / width, 0.0, 1.0),
                    y=_clamp((y + h / 2) / height, 0.0, 1.0),
                    eyes_closed=eyes_closed,
                    mouth_open=mouth_open,
                    blink_event=blink_event,
                    mouth_event=mouth_event,
                    seen_at=now,
                )
            )

        return faces


def _distance(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _eye_ratio(points, indexes: tuple[int, int, int, int]) -> float:
    outer, inner, top, bottom = indexes
    width = max(_distance(points[outer], points[inner]), 0.001)
    height = _distance(points[top], points[bottom])
    return height / width


def _mouth_ratio(points) -> float:
    width = max(_distance(points[61], points[291]), 0.001)
    height = _distance(points[13], points[14])
    return height / width


def _fingers_up(points, handedness: str) -> int:
    extended = 0
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        if points[tip].y < points[pip].y:
            extended += 1

    thumb_is_open = False
    if handedness == "Right":
        thumb_is_open = points[4].x < points[3].x
    elif handedness == "Left":
        thumb_is_open = points[4].x > points[3].x
    else:
        thumb_is_open = abs(points[4].x - points[3].x) > 0.035

    if thumb_is_open:
        extended += 1
    return extended


def _convexity_defect_count(contour) -> int:
    if len(contour) < 5:
        return 0
    hull = cv2.convexHull(contour, returnPoints=False)
    if hull is None or len(hull) < 4:
        return 0
    defects = cv2.convexityDefects(contour, hull)
    if defects is None:
        return 0
    count = 0
    for defect in defects[:, 0]:
        _, _, _, depth = defect
        if depth > 900:
            count += 1
    return count


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
