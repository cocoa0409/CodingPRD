"""Pattern-of-violations weighted score (PRD section 3.7).

Rolling 365-day window: a citation counts iff issued_at is strictly after
window_start and on or before screened_at. VACATED citations never count; the
SCREENING variant also counts citations under an unresolved contest (status
CONTESTED), while FINAL_DETERMINATION excludes them. Imminent-danger orders
are always counted regardless of their status.
"""
from datetime import timedelta

import store
from constants import (
    IDO_WEIGHT,
    NEGLIGENCE_BONUS,
    POV_BONUS_NEGLIGENCE,
    POV_WINDOW_DAYS,
    SS_WEIGHT,
)


def compute_pov(mine_id, screened_at, variant):
    """Returns (ss_citation_count, weighted_score)."""
    window_start = screened_at - timedelta(days=POV_WINDOW_DAYS)
    counted = []
    for citation in store.citations.values():
        if citation["mine_id"] != mine_id:
            continue
        if citation["contest_status"] == "VACATED":
            continue
        if variant == "FINAL_DETERMINATION" and citation["contest_status"] == "CONTESTED":
            continue
        if not (window_start < citation["issued_at"] <= screened_at):
            continue
        counted.append(citation)
    ss_count = sum(1 for c in counted if c["significant_and_substantial"])
    negligence_bonus = sum(1 for c in counted if c["negligence"] in POV_BONUS_NEGLIGENCE)
    ido_count = sum(
        1
        for order in store.idos.values()
        if order["mine_id"] == mine_id
        and window_start < order["issued_at"] <= screened_at
    )
    weighted_score = SS_WEIGHT * ss_count + NEGLIGENCE_BONUS * negligence_bonus + IDO_WEIGHT * ido_count
    return ss_count, weighted_score
