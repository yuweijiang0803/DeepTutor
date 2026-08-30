"""The scan-enhance service: deskew + denoise + adaptive binarization.

Skipped entirely when OpenCV is not installed (the module keeps the rest
of the app importable without it).
"""

from __future__ import annotations

import base64

import numpy as np
import pytest

from deeptutor.services.scan_enhance import (
    ScanEnhanceOptions,
    _estimate_deskew_angle,
    enhance_scan,
)

cv2 = pytest.importorskip("cv2")


def _data_url(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _make_tilted_page(angle_deg: float = 5) -> np.ndarray:
    """White page with a few dark horizontal bars, tilted by ``angle_deg``."""
    img = np.full((400, 600, 3), 255, np.uint8)
    for y in (80, 140, 200):
        cv2.rectangle(img, (80, y), (520, y + 20), (0, 0, 0), -1)
    center = (300, 200)
    m = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    return cv2.warpAffine(img, m, (600, 400), borderValue=(255, 255, 255))


def test_deskew_angle_estimation_detects_tilt() -> None:
    gray = cv2.cvtColor(_make_tilted_page(5), cv2.COLOR_BGR2GRAY)
    angle = _estimate_deskew_angle(gray)
    assert 2.0 <= abs(angle) <= 15.0


def test_enhance_scan_returns_binary_png() -> None:
    out = enhance_scan(_data_url(_make_tilted_page(5)))
    assert out.startswith("data:image/png;base64,")
    raw = base64.b64decode(out.split(",", 1)[1])
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert img is not None
    # Adaptive binarization: every pixel is exactly black or white.
    vals = set(np.unique(img).tolist())
    assert vals.issubset({0, 255})


def test_enhance_scan_without_deskew() -> None:
    out = enhance_scan(
        _data_url(_make_tilted_page(5)), ScanEnhanceOptions(deskew=False)
    )
    assert out.startswith("data:image/png;base64,")


def test_invalid_image_raises() -> None:
    with pytest.raises(ValueError):
        enhance_scan("data:image/png;base64,bm90LWFuLWltYWdl")
