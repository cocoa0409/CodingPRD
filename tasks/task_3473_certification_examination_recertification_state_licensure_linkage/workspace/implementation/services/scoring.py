"""cat_adaptive_scoring (PRD §3.4): difficulty-weighted accuracy, provisional
outcome at MIN_ITEMS, confidence-band stopping rule for the final outcome."""

import math

from db import MIN_ITEMS, Z_SCORE
from util import round_half_up_4dp


def score_attempt(responses, cut_score):
    """Score a CAT submission.

    responses: list of {"item_id", "difficulty_b", "correct"} in delivery order.
    Returns (provisional_outcome, final_outcome, theta_final, items_delivered_count).
    All pass/fail comparisons use unrounded doubles; theta_final is stored
    round-half-up to 4 decimal places.
    """
    n = len(responses)
    diffs = [float(r["difficulty_b"]) for r in responses]
    correct = [1.0 if r["correct"] else 0.0 for r in responses]

    def theta(k):
        sw = sum(diffs[:k])
        if sw <= 0:
            return 0.0
        return sum(d * c for d, c in zip(diffs[:k], correct[:k])) / sw

    provisional = None
    if n >= MIN_ITEMS:
        provisional = "PASS" if theta(MIN_ITEMS) >= cut_score else "FAIL"

    final = None
    items_delivered = n
    if n >= MIN_ITEMS:
        for k in range(MIN_ITEMS, n + 1):
            t = theta(k)
            if t <= 0.0 or t >= 1.0:
                sem = 0.0
            else:
                sem = math.sqrt(t * (1.0 - t) / k)
            lcb = t - Z_SCORE * sem
            ucb = t + Z_SCORE * sem
            if lcb >= cut_score:
                final = "PASS"
                items_delivered = k
                break
            if ucb < cut_score:
                final = "FAIL"
                items_delivered = k
                break
        if final is None:
            final = "PASS" if theta(n) >= cut_score else "FAIL"
            items_delivered = n
    else:
        final = "PASS" if (n > 0 and theta(n) >= cut_score) else (
            "PASS" if 0.0 >= cut_score else "FAIL")
        items_delivered = n

    theta_final = round_half_up_4dp(theta(items_delivered)) if items_delivered > 0 else 0.0
    return provisional, final, theta_final, items_delivered
