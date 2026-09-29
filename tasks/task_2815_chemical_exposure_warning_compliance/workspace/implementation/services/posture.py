"""The posture ladder, the derived product counters and channel coverage."""
from util import D
import db
from services import calc


def reachable_listed_chemicals(product):
    """Listed chemicals linked to any material in an active component's subtree."""
    material_ids = set()
    for component in calc.active_components(product["id"]):
        material = db.get("materials", component["material_id"])
        if material is None:
            continue
        for node in calc.subtree(material):
            material_ids.add(node["id"])
    out = []
    for link in db.rows("material_chemicals"):
        if link["material_id"] not in material_ids:
            continue
        chemical = db.get("listed_chemicals", link["chemical_id"])
        if chemical is not None and chemical["status"] == "LISTED" and chemical not in out:
            out.append(chemical)
    return out


def open_notice_count(product):
    return len([n for n in calc.notices_of(product["id"])
                if n["status"] in calc.OPEN_NOTICE_STATUSES])


def accrued_penalty_cents(product):
    total = 0
    for notice in calc.notices_of(product["id"]):
        for settlement in calc.settlements_of(notice["id"]):
            if settlement["status"] == "EXECUTED":
                total += int(settlement["adjusted_penalty_cents"] or 0)
    return total


def window_covers(effective_from, effective_to, instant):
    """Placement windows are CLOSED at both ends; a null end is +infinity."""
    if effective_from is not None and effective_from > instant:
        return False
    if effective_to is not None and instant > effective_to:
        return False
    return True


def covered_channel_count(determination, at=None, statuses=("IMPLEMENTED", "VERIFIED")):
    instant = at if at is not None else db.now()
    required = determination.get("required_channels") or []
    count = 0
    for channel in required:
        for placement in calc.placements_of(determination["id"]):
            if placement["channel"] != channel or placement["status"] not in statuses:
                continue
            if window_covers(placement["effective_from"], placement["effective_to"], instant):
                count += 1
                break
    return count


def refresh_covered_channel_count(determination):
    count = covered_channel_count(determination)
    if determination.get("covered_channel_count") != count:
        determination["covered_channel_count"] = count
        db.touch(determination)
    return count


def has_disclosure_gap(product):
    for component in calc.active_components(product["id"]):
        material = db.get("materials", component["material_id"])
        if material is None:
            continue
        for node in calc.subtree(material):
            if node.get("disclosure_status") in calc.DISCLOSURE_GAP:
                return True
    return False


def compute_posture(product):
    """Top-down ladder: the first matching clause wins (PRD 2.10)."""
    if open_notice_count(product) >= 1:
        return "ENFORCEMENT_HOLD"
    components = calc.active_components(product["id"])
    if not components:
        return "EXPOSURE_UNKNOWN"
    if has_disclosure_gap(product):
        return "EXPOSURE_UNKNOWN"
    for chemical in reachable_listed_chemicals(product):
        finals = [a for a in calc.assessments_of(product["id"], chemical["id"])
                  if a["status"] == "FINAL"]
        if not finals:
            return "EXPOSURE_UNKNOWN"
    for determination in calc.determinations_of(product["id"]):
        if determination["status"] != "APPROVED" or determination["decision"] != "WARNING_REQUIRED":
            continue
        required = determination.get("required_channels") or []
        if determination.get("covered_channel_count") == len(required):
            return "WARNING_ACTIVE"
    for assessment in calc.assessments_of(product["id"]):
        if assessment["status"] == "FINAL" and assessment["result"] in calc.QUALIFYING_RESULTS:
            return "WARNING_REQUIRED"
    return "CLEAR"


def recompute_posture(product):
    """Refreshes the derived counters and the posture; touches updated_at only."""
    if product is None:
        return None
    product["open_notice_count"] = open_notice_count(product)
    product["accrued_penalty_cents"] = accrued_penalty_cents(product)
    product["compliance_posture"] = compute_posture(product)
    db.touch(product, bump=False)
    return product["compliance_posture"]


def recompute_load(product):
    if product is None:
        return None
    product["total_listed_chemical_load_ug"] = calc.chemical_load(product)
    return product["total_listed_chemical_load_ug"]
