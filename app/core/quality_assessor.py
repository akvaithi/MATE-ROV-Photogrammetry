"""
Pure functions for frame quality assessment.
No Qt, no side effects — fully unit-testable.
"""
from __future__ import annotations

import cv2
import numpy as np


def laplacian_sharpness(gray: np.ndarray) -> float:
    """
    Measure focus/sharpness via Laplacian variance.
    Higher = sharper. Typical sharp image: >100. Blurry: <30.
    """
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def motion_score(prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
    """
    Mean absolute pixel difference between two consecutive grayscale frames.
    Low = still camera. High = moving camera or scene motion.
    """
    return float(cv2.absdiff(prev_gray, curr_gray).mean())


def compute_hsv_hist(bgr: np.ndarray) -> np.ndarray:
    """
    Compute a normalised 2D HSV histogram (Hue x Saturation) for novelty checks.
    Returns a flat float32 array ready for cv2.compareHist.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist, alpha=1, norm_type=cv2.NORM_L1)
    return hist


def novelty_score(new_hist: np.ndarray, saved_hists: list[np.ndarray]) -> float:
    """
    Bhattacharyya distance between new_hist and the nearest saved histogram.
    0.0 = identical, 1.0 = completely different.
    Returns 1.0 (maximum novelty) when no frames have been saved yet.
    """
    if not saved_hists:
        return 1.0
    distances = [
        cv2.compareHist(new_hist, h, cv2.HISTCMP_BHATTACHARYYA)
        for h in saved_hists
    ]
    return float(min(distances))


# Saliency runs on a small downscaled copy for speed; the detector only needs
# to localise a bbox, and the result is returned in normalised [0, 1] coords.
_SALIENCY_SIZE = 192
_CENTER_PRIOR_CACHE: dict[tuple[int, int], np.ndarray] = {}


def _center_prior(h: int, w: int) -> np.ndarray:
    """Cached Gaussian centre-bias kernel — avoids rebuilding each tick."""
    key = (h, w)
    prior = _CENTER_PRIOR_CACHE.get(key)
    if prior is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cy, cx = h / 2.0, w / 2.0
        sigma = min(h, w) * 0.45
        prior = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sigma * sigma))
        prior = prior.astype(np.float32)
        _CENTER_PRIOR_CACHE[key] = prior
    return prior


def _downscaled(gray: np.ndarray) -> np.ndarray:
    """Resize so the longer edge is _SALIENCY_SIZE, preserving aspect ratio."""
    h, w = gray.shape
    scale = _SALIENCY_SIZE / float(max(h, w))
    if scale >= 1.0:
        return gray
    nh = max(1, int(round(h * scale)))
    nw = max(1, int(round(w * scale)))
    return cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_AREA)


def _focus_edge_map(gray: np.ndarray) -> np.ndarray:
    """Raw focus+edge density, normalised 0..1, unweighted by position.
    Uses a small box filter (O(1) per pixel) instead of Gaussian — fast."""
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    focus = cv2.boxFilter(np.abs(lap), ddepth=-1, ksize=(9, 9))
    sx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edges = cv2.boxFilter(cv2.magnitude(sx, sy), ddepth=-1, ksize=(9, 9))

    def _norm(x: np.ndarray) -> np.ndarray:
        mx = float(x.max())
        return (x / mx) if mx > 1e-6 else x

    return (0.55 * _norm(focus) + 0.45 * _norm(edges)).astype(np.float32)


def saliency_map(gray: np.ndarray) -> np.ndarray:
    """
    Subject-localisation map for a handheld object shoot.

    Combines three cues that together pick out the thing the user is
    photographing, even for smooth / low-texture objects like a water bottle:
      1. **Local focus density** — the object is where the lens is focused.
      2. **Edge density** — silhouette/contour strength via Sobel gradient.
      3. **Centre prior** — a Gaussian weight biasing toward the middle.

    Operates on a downscaled copy (~192 px long edge) for speed; returns a
    float32 map at that small resolution, normalised to 0..1.
    """
    small = _downscaled(gray)
    base = _focus_edge_map(small)
    prior = _center_prior(*small.shape)
    combined = base * prior
    mx = float(combined.max())
    return (combined / mx).astype(np.float32) if mx > 1e-6 else combined.astype(np.float32)


def framing_score(
    gray: np.ndarray,
    ideal_coverage: float = 0.30,
) -> tuple[float, tuple[float, float, float, float] | None]:
    """
    Evaluate how well the principal subject is framed.

    Returns (score in [0, 1], normalised bbox (x, y, w, h) in [0, 1] or None).
    Three factors, each 0..1:
      - Centering: subject centroid near image centre
      - Coverage: subject area in a reasonable range (peak at `ideal_coverage`)
      - Edge clearance: subject not clipping the frame edges
    """
    # All the heavy lifting happens on a small downscaled copy.
    small = _downscaled(gray)

    # Check the *raw* focus/edge map first: the centre prior would otherwise
    # invent a peak even on a flat frame.
    raw = _focus_edge_map(small)
    if float(raw.max()) < 0.15 or float(raw.mean()) / (float(raw.max()) + 1e-6) > 0.65:
        # Frame is either featureless or uniformly busy — no distinct subject.
        return 0.0, None

    prior = _center_prior(*small.shape)
    combined = raw * prior
    mx = float(combined.max())
    sal = (combined / mx).astype(np.float32) if mx > 1e-6 else combined.astype(np.float32)

    # Threshold at 40% of the peak — forgiving enough that low-contrast
    # subjects still produce a connected mask.
    mask = (sal > 0.4).astype(np.uint8) * 255
    num, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num <= 1:
        return 0.0, None

    # Largest non-background component
    areas = stats[1:, cv2.CC_STAT_AREA]
    idx = 1 + int(np.argmax(areas))
    x, y, bw, bh, _area = stats[idx]

    H, W = small.shape
    coverage = (bw * bh) / float(W * H)

    # Coverage: plateau near ideal, hard cut below 5% or above 65% (huge
    # bboxes usually mean no real subject).
    if coverage < 0.05 or coverage > 0.65:
        coverage_score = 0.0
    else:
        coverage_score = max(0.0, 1.0 - abs(coverage - ideal_coverage) / 0.30)

    # Centering: normalised distance from image centre (0 = centred)
    cx_sub, cy_sub = x + bw / 2.0, y + bh / 2.0
    dx = (cx_sub - W / 2.0) / (W / 2.0)
    dy = (cy_sub - H / 2.0) / (H / 2.0)
    dist = float(np.hypot(dx, dy))
    # Full score within 25% of centre; linear falloff to 0 at 80% toward corner
    center_score = max(0.0, min(1.0, (0.80 - dist) / 0.55))

    # Edge clearance: penalise boxes clipping the frame (but only mildly)
    margin = min(x, y, W - (x + bw), H - (y + bh)) / float(min(W, H))
    clearance_score = min(1.0, max(0.0, margin * 20.0))

    score = 0.5 * center_score + 0.4 * coverage_score + 0.1 * clearance_score
    bbox_norm = (x / W, y / H, bw / W, bh / H)
    return float(score), bbox_norm


def is_capturable(
    prev_gray: np.ndarray,
    curr_gray: np.ndarray,
    curr_bgr: np.ndarray,
    saved_hists: list[np.ndarray],
    motion_threshold: float,
    sharpness_threshold: float,
    novelty_threshold: float,
    framing_threshold: float = 0.0,
) -> tuple[bool, dict]:
    """
    Four-gate acceptance pipeline.
    Returns (accept: bool, scores: dict) where scores always contains all metrics.
    """
    scores: dict = {}

    # Always compute framing score so the UI meter updates in real time.
    fscore, fbbox = framing_score(curr_gray)
    scores["framing"] = fscore
    scores["framing_bbox"] = fbbox

    # Gate 1 — motion rejection (cheapest, run first)
    scores["motion"] = motion_score(prev_gray, curr_gray)
    if scores["motion"] > motion_threshold:
        scores["sharpness"] = 0.0
        scores["novelty"] = 0.0
        scores["reject_reason"] = "motion"
        return False, scores

    # Gate 2 — sharpness
    scores["sharpness"] = laplacian_sharpness(curr_gray)
    if scores["sharpness"] < sharpness_threshold:
        scores["novelty"] = 0.0
        scores["reject_reason"] = "blur"
        return False, scores

    # Gate 3 — novelty
    new_hist = compute_hsv_hist(curr_bgr)
    scores["novelty"] = novelty_score(new_hist, saved_hists)
    if scores["novelty"] < novelty_threshold:
        scores["reject_reason"] = "duplicate"
        return False, scores

    # Gate 4 — framing (ML-based saliency composition check)
    if framing_threshold > 0.0 and fscore < framing_threshold:
        scores["reject_reason"] = "framing"
        return False, scores

    scores["reject_reason"] = None
    return True, scores
