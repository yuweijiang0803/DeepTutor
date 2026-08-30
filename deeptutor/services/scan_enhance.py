"""Document scan enhancement: deskew + denoise + adaptive binarization.

Used by the crop modal's "scan effect": the client uploads the full page
photo, we straighten it (deskew), remove sensor noise, and return a clean
black-on-white image that prints well. OpenCV is imported lazily so the
rest of the app keeps working on installs without it.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import numpy as np

try:
    import cv2

    _HAVE_CV2 = True
except ImportError:  # pragma: no cover - environments without cv2
    cv2 = None  # type: ignore[assignment]
    _HAVE_CV2 = False


@dataclass
class ScanEnhanceOptions:
    """Tuning knobs for :func:`enhance_scan`."""

    deskew: bool = True
    denoise: bool = True
    cleanup: bool = True
    # Adaptive-threshold window (odd) and offset. Larger ``block_size`` /
    # smaller ``c`` → whiter background.
    block_size: int = 31
    c: float = 15.0


def _decode_data_url(data_url: str) -> np.ndarray:
    raw = base64.b64decode(data_url.split(",", 1)[-1])
    arr = np.frombuffer(raw, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode the supplied image")
    return img


def _encode_png(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Could not encode the processed image")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _estimate_deskew_angle(gray: np.ndarray) -> float:
    """Median ink-component angle in degrees; 0 when nothing looks tilted."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    angles: list[float] = []
    for cnt in contours:
        if cv2.contourArea(cnt) < 100:
            continue
        angle = cv2.minAreaRect(cnt)[2]
        if angle < -45:
            angle += 90
        if abs(angle) > 30:
            continue
        angles.append(angle)
    return float(np.median(angles)) if angles else 0.0


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Rotate a grayscale page image so text lines run horizontal."""
    h, w = gray.shape[:2]
    scale = min(1.0, 1200.0 / max(h, w))
    small = (
        cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else gray
    )
    angle = _estimate_deskew_angle(small)
    if abs(angle) < 0.3:
        return gray
    center = (w / 2, h / 2)
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def enhance_scan(data_url: str, options: ScanEnhanceOptions | None = None) -> str:
    """Return a PNG data URL for the deskewed + binarized page image."""
    if not _HAVE_CV2:
        raise RuntimeError(
            "opencv-python-headless is required for scan enhancement and is not installed"
        )
    opts = options or ScanEnhanceOptions()
    img = _decode_data_url(data_url)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if opts.deskew:
        gray = _deskew(gray)
    if opts.denoise:
        # Fast median filter removes sensor salt-and-pepper without the cost
        # of fastNlMeans on a full-page photo.
        gray = cv2.medianBlur(gray, 3)

    block = max(3, opts.block_size if opts.block_size % 2 == 1 else opts.block_size + 1)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, opts.c
    )

    if opts.cleanup:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    return _encode_png(binary)


__all__ = ["ScanEnhanceOptions", "enhance_scan"]
