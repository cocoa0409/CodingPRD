"""The plant capacity review — the single ops checkpoint where time-dependent
bookkeeping catches up with the logical clock (PRD §3.12)."""
from datetime import date

import db as dbmod
from services import calcs
from util import touch


def recompute_supplier_tier(supplier_id):
    tier = "STANDARD"
    for p in dbmod.db.collection_programs.values():
        if p["supplier_id"] == supplier_id and p["status"] == "ACTIVE":
            tier = "PREFERRED"
            break
    sup = dbmod.db.suppliers[supplier_id]
    if sup["quality_tier"] != tier:
        sup["quality_tier"] = tier
        touch(sup)


def recompute_reliability(supplier_id):
    lots = [l for l in dbmod.db.feedstock_lots.values() if l["supplier_id"] == supplier_id]
    total = len(lots)
    rejected = sum(1 for l in lots if l["status"] == "REJECTED")
    sup = dbmod.db.suppliers[supplier_id]
    if total == 0:
        score = 10000
    else:
        score = 10000 - (rejected * 10000) // total
    if sup["reliability_score_bp"] != score:
        sup["reliability_score_bp"] = score
        touch(sup)


def release_reservation(ac, plant):
    """Remove the reservation's remaining share from the reserved ledger."""
    line = ac["product_line_id"]
    remaining = ac.get("remaining_lf", ac["reserved_lf"])
    ledger = plant["reserved_fg_store"]
    ledger[line] = max(0, ledger.get(line, 0) - remaining)
    ac["remaining_lf"] = 0


def run_capacity_review(plant):
    review_date = dbmod.clock_date()
    review_date_str = review_date.isoformat()

    # 1. posture recompute
    plant["season_posture"] = calcs.compute_posture(plant, review_date)

    # 2. PCR decay
    calcs.decay_pcr(plant["id"], review_date)

    # 3. stale quarantine sweep: QUARANTINE lots received > 14 days before review
    for lot in dbmod.db.feedstock_lots.values():
        if lot["status"] != "QUARANTINE":
            continue
        rec = date.fromisoformat(lot["received_date"])
        if (review_date - rec).days > 14:
            lot["status"] = "REJECTED"
            touch(lot)
            recompute_reliability(lot["supplier_id"])

    # 4. reservation expiry: OPEN allocation commitments created > 90 days ago
    for ac in dbmod.db.allocation_commitments.values():
        if ac["status"] != "OPEN" or ac.get("plant_id") != plant["id"]:
            continue
        created = date.fromisoformat(ac.get("created_logical_date") or ac["created_at"][:10])
        if (review_date - created).days > 90:
            ac["status"] = "EXPIRED"
            release_reservation(ac, plant)
            touch(ac)
    # plant-level PCR provenance must stay consistent with the decayed balance
    origin = dbmod.db.pcr_origin.get(plant["id"])
    if origin is not None:
        bal = plant["resin_store"]["PCR_FILM"]
        total_tracked = origin["production_lbs"] + origin["support_lbs"]
        if total_tracked > bal:
            # decay shrinks support-stock provenance first (conservative: keep
            # production provenance while any remains)
            excess = total_tracked - bal
            from_support = min(origin["support_lbs"], excess)
            origin["support_lbs"] -= from_support
            origin["production_lbs"] -= (excess - from_support)

    # 5. lead expiry: ASSIGNED > 30 days
    for lead in dbmod.db.lead_referrals.values():
        if lead["status"] != "ASSIGNED":
            continue
        assigned_on = date.fromisoformat((lead.get("assigned_at") or lead["updated_at"])[:10])
        if (review_date - assigned_on).days > 30:
            lead["status"] = "EXPIRED"
            touch(lead)

    # 6. contractor lapse
    for c in dbmod.db.contractors.values():
        if c["status"] == "CERTIFIED":
            cert = c.get("certified_at")
            if cert:
                cert_date = date.fromisoformat(cert[:10])
                months = (review_date.year - cert_date.year) * 12 + (review_date.month - cert_date.month)
                if review_date.day < cert_date.day:
                    months -= 1
                if months > 24 and c.get("completed_project_count", 0) == 0:
                    c["status"] = "LAPSED"
                    touch(c)
        elif c["status"] == "SUSPENDED":
            susp = c.get("suspended_at")
            if susp:
                susp_date = date.fromisoformat(susp[:10])
                months = (review_date.year - susp_date.year) * 12 + (review_date.month - susp_date.month)
                if review_date.day < susp_date.day:
                    months -= 1
                if months > 24:
                    c["status"] = "LAPSED"
                    touch(c)

    touch(plant)
    return plant
