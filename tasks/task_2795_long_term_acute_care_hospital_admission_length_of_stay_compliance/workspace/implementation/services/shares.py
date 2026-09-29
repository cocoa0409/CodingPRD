"""The 25-percent-rule referral-mix recomputation (PRD 3.3)."""

import calc
from store import db, touch


def recompute_all_shares(period):
    """Rewrite share_pct, threshold_pct and monitoring_state for every referring hospital.

    The sweep is idempotent: a hospital whose three derived fields are unchanged is
    not re-stamped, so running the recompute twice yields identical rows.
    """
    total_admissions = period["total_admissions"] if period is not None else 0
    for hospital in db.hospitals.values():
        threshold = calc.hospital_threshold_pct(hospital)
        share = calc.share_pct(hospital["admissions_in_period"], total_admissions)
        state = calc.monitoring_state(share, threshold, total_admissions)
        if (hospital["threshold_pct"] != threshold
                or hospital["share_pct"] != share
                or hospital["monitoring_state"] != state):
            hospital["threshold_pct"] = threshold
            hospital["share_pct"] = share
            hospital["monitoring_state"] = state
            touch(hospital)
