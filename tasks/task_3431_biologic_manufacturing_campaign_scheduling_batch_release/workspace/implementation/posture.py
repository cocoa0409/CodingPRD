"""site_release_posture calculation (PRD 2.9) and the one-way freeze cascade.

FROZEN      if open_critical_finding_count >= 1
            OR open_critical_deviation_count >= CRITICAL_DEVIATION_FREEZE_THRESHOLD
CONDITIONAL if open_critical_deviation_count == 1
CLEAR       otherwise

Transition INTO FROZEN preempts every COMMERCIAL campaign in PROPOSED at the
site; transition OUT OF FROZEN resurrects nothing.
"""
import store
from constants import CRITICAL_DEVIATION_FREEZE_THRESHOLD, OPEN_DEVIATION_STATUSES


def site_of_batch(batch):
    campaign = store.get("campaigns", batch["campaign_id"])
    train = store.get("trains", campaign["train_id"])
    return train["site_id"]


def site_of_campaign(campaign):
    train = store.get("trains", campaign["train_id"])
    return train["site_id"]


def count_open_critical_deviations(site_id):
    n = 0
    for dev in store.all_recs("deviations"):
        if dev["severity"] != "CRITICAL" or dev["status"] not in OPEN_DEVIATION_STATUSES:
            continue
        batch = store.get("batches", dev["batch_lot_id"])
        if batch is None:
            continue
        if site_of_batch(batch) == site_id:
            n += 1
    return n


def sum_open_critical_findings(site_id):
    total = 0
    for insp in store.all_recs("inspections"):
        if insp["site_id"] == site_id and insp["status"] == "FINDINGS_ISSUED":
            total += insp["open_critical_finding_count"]
    return total


def recompute_site(site_id):
    """Recompute counters and posture; run the freeze cascade if entering FROZEN."""
    site_rec = store.get("sites", site_id)
    if site_rec is None:
        return
    old_posture = site_rec["release_posture"]
    devs = count_open_critical_deviations(site_id)
    finds = sum_open_critical_findings(site_id)
    if finds >= 1 or devs >= CRITICAL_DEVIATION_FREEZE_THRESHOLD:
        new_posture = "FROZEN"
    elif devs == 1:
        new_posture = "CONDITIONAL"
    else:
        new_posture = "CLEAR"
    changed = (
        site_rec["open_critical_deviation_count"] != devs
        or site_rec["open_critical_finding_count"] != finds
        or old_posture != new_posture
    )
    site_rec["open_critical_deviation_count"] = devs
    site_rec["open_critical_finding_count"] = finds
    site_rec["release_posture"] = new_posture
    if changed:
        store.touch(site_rec)
    if new_posture == "FROZEN" and old_posture != "FROZEN":
        _freeze_cascade(site_id)


def _freeze_cascade(site_id):
    """Every COMMERCIAL campaign in PROPOSED at this site -> PREEMPTED."""
    for c in store.all_recs("campaigns"):
        if c["status"] == "PROPOSED" and c["demand_type"] == "COMMERCIAL" \
                and site_of_campaign(c) == site_id:
            c["status"] = "PREEMPTED"
            store.touch(c)
