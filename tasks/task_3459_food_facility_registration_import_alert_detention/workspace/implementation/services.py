"""Business-logic services: the SCAFFOLD section 1.3 calculation rules, the
detention lifecycle helpers shared by endpoints and cascades, and the
logical-clock ops checkpoint (PRD section 2.4).
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError

# --- prior_notice_window_check constants -----------------------------------
MIN_LEAD_HOURS = {"VESSEL": 8, "AIR": 4, "RAIL": 4, "ROAD": 2}
MAX_LEAD_HOURS = 720
AMENDMENT_MIN_DIVISOR = 2

# --- entry_screening_score constants ---------------------------------------
BASE_POINTS = {"LOW": 10, "STANDARD": 30, "HIGH": 60}
VC_CAP = 5
RC_CAP = 3
VC_WEIGHT_BASE = 8
RC_WEIGHT_BASE = 12
VC_WEIGHT_HISTORY = 16
RC_WEIGHT_HISTORY = 24
ALERT_TERM = 35
AMEND_TERM = 10
PROBATION_TERM = 15
SAMPLE_THRESHOLD = 40
SCORE_CAP = 100

# --- reconditioning_bond constants -----------------------------------------
BOND_RATE = Decimal("0.10")
STORAGE_DAILY_CENTS = 1500

# --- importer_standing_recompute constants ---------------------------------
PROBATION_REFUSALS = 2
REVOKED_REFUSALS = 4

# --- petition_compliance_streak constants ----------------------------------
REQUIRED_STREAK = 3

# --- facility_registration_expiry constants --------------------------------
REGISTRATION_PERIOD_DAYS = 730
RENEWAL_OPEN_DAYS_BEFORE = 90
RENEWAL_GRACE_DAYS_AFTER = 30

# --- recall_effectiveness constants ----------------------------------------
CLASS_II_THRESHOLD = Decimal("95.0")
CLASS_III_THRESHOLD = Decimal("90.0")

DETENTION_RESPONSE_HOURS = 240
SWEEP_GRACE_HOURS = 24

MISSING = object()


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# prior_notice_window_check (initial + amendment variants)
# ---------------------------------------------------------------------------
def check_notice_window(arrival_eta, transport_mode, amendment):
    """Raise ERR_NOTICE_TOO_LATE / ERR_NOTICE_TOO_EARLY. Lead is computed to
    whole minutes and compared at minute granularity; bounds are inclusive."""
    lead_seconds = (arrival_eta - db.now()).total_seconds()
    lead_minutes = math.floor(lead_seconds / 60)
    minimum = MIN_LEAD_HOURS[transport_mode]
    if amendment:
        minimum = math.ceil(minimum / AMENDMENT_MIN_DIVISOR)
    if lead_minutes < minimum * 60:
        raise ApiError("ERR_NOTICE_TOO_LATE")
    if lead_minutes > MAX_LEAD_HOURS * 60:
        raise ApiError("ERR_NOTICE_TOO_EARLY")


# ---------------------------------------------------------------------------
# Import alert scope matching
# ---------------------------------------------------------------------------
def alert_matches_entry(alert, entry):
    if alert["scope_type"] == "FIRM":
        return alert["facility_id"] == entry["facility_id"]
    facility = db.facilities.get(entry["facility_id"])
    return (
        facility is not None
        and facility["country_code"] == alert["country_code"]
        and entry["product_code"] == alert["product_code"]
    )


def matching_active_alert(entry):
    """The earliest-created ACTIVE alert matching the entry scope, or None.
    Ties are broken by server creation order, which is total."""
    matches = [
        a
        for a in db.alerts.values()
        if a["status"] == "ACTIVE" and alert_matches_entry(a, entry)
    ]
    if not matches:
        return None
    matches.sort(key=db.sort_key)
    return matches[0]


# ---------------------------------------------------------------------------
# entry_screening_score (BASE / HISTORY_WEIGHTED variants)
# ---------------------------------------------------------------------------
def screen_score(entry):
    """Return (score, variant, probation_adjustment, matching_alert)."""
    facility = db.facilities[entry["facility_id"]]
    importer = db.importers[entry["importer_id"]]
    if facility["violation_count"] == 0 and importer["refusal_count"] == 0:
        variant = "BASE"
        vc_weight, rc_weight = VC_WEIGHT_BASE, RC_WEIGHT_BASE
    else:
        variant = "HISTORY_WEIGHTED"
        vc_weight, rc_weight = VC_WEIGHT_HISTORY, RC_WEIGHT_HISTORY
    vc = min(facility["violation_count"], VC_CAP)
    rc = min(importer["refusal_count"], RC_CAP)
    alert = matching_active_alert(entry)
    alert_term = ALERT_TERM if alert is not None else 0
    amend_term = AMEND_TERM if entry["is_amendment_pn"] else 0
    probation = PROBATION_TERM if importer["standing"] == "PROBATION" else 0
    score = BASE_POINTS[entry["product_risk_class"]]
    score += vc_weight * vc + rc_weight * rc + alert_term + amend_term + probation
    return min(SCORE_CAP, score), variant, probation, alert


# ---------------------------------------------------------------------------
# importer_standing_recompute (pinned evaluation order, exact rationals)
# ---------------------------------------------------------------------------
def apply_terminal_outcome(importer, refused):
    """Step 1: apply the entry outcome to the counters; steps 2-3: ratio and
    standing; step 4: the new standing applies only to future filings."""
    if refused:
        importer["refusal_count"] += 1
    importer["terminal_entry_count"] += 1
    rc = importer["refusal_count"]
    tec = max(1, importer["terminal_entry_count"])
    if rc >= REVOKED_REFUSALS or rc * 2 >= tec:
        importer["standing"] = "REVOKED"
    elif rc >= PROBATION_REFUSALS or rc * 5 >= tec:
        importer["standing"] = "PROBATION"
    else:
        importer["standing"] = "GOOD_STANDING"
    db.touch(importer)


# ---------------------------------------------------------------------------
# Detention lifecycle (shared by screen / alert cascade / inspection cascade /
# VIOLATIVE sample / release / refuse / sweeps). Entry-units conservation
# (entry_units_conservation) is preserved by every helper here.
# ---------------------------------------------------------------------------
def detain_entry(entry, alert_id, at):
    """Open a detention exactly as PRD section 3.6 prescribes."""
    entry["disposition_status"] = "DETAINED"
    entry["detained_at"] = at
    entry["response_deadline_at"] = at + timedelta(hours=DETENTION_RESPONSE_HOURS)
    entry["units_held"] = entry["declared_units"]
    entry["detained_under_alert_id"] = alert_id
    facility = db.facilities[entry["facility_id"]]
    facility["open_detention_count"] += 1
    db.touch(facility, at)
    db.touch(entry, at)


def release_detained(entry, at):
    """DWPE release (ComplianceOfficer path or petition-approval cascade)."""
    facility = db.facilities[entry["facility_id"]]
    entry["units_released"] += entry["units_held"]
    entry["units_held"] = 0
    facility["open_detention_count"] -= 1
    db.touch(facility, at)
    entry["disposition_status"] = "RELEASED"
    if entry["disposition_completed_at"] is None:
        entry["disposition_completed_at"] = at
    db.touch(entry, at)
    apply_terminal_outcome(db.importers[entry["importer_id"]], refused=False)


def release_pending(entry, at):
    """Release of a SAMPLE-decision entry after a COMPLIANT result."""
    entry["units_released"] += entry["declared_units"] - entry["units_released"]
    entry["disposition_status"] = "RELEASED"
    if entry["disposition_completed_at"] is None:
        entry["disposition_completed_at"] = at
    db.touch(entry, at)
    apply_terminal_outcome(db.importers[entry["importer_id"]], refused=False)


def refuse_entry(entry, at):
    """Refusal of a detained entry (officer path and deadline sweep)."""
    facility = db.facilities[entry["facility_id"]]
    entry["units_refused"] += entry["units_held"]
    entry["units_held"] = 0
    facility["open_detention_count"] -= 1
    facility["violation_count"] += 1
    db.touch(facility, at)
    entry["disposition_status"] = "REFUSED"
    if entry["disposition_completed_at"] is None:
        entry["disposition_completed_at"] = at
    db.touch(entry, at)
    apply_terminal_outcome(db.importers[entry["importer_id"]], refused=True)


# ---------------------------------------------------------------------------
# reconditioning_bond (pinned rounding order: per lot, half up, then sum)
# ---------------------------------------------------------------------------
def compute_bond(lots, entry, at):
    bond_from_lots = 0
    for lot in lots:
        per_lot_value = lot["quantity"] * lot["unit_value_cents"]
        per_lot_bond = (Decimal(per_lot_value) * BOND_RATE).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        bond_from_lots += int(per_lot_bond)
    days_detained = int((at - entry["detained_at"]).total_seconds() // 86400)
    if days_detained < 0:
        days_detained = 0
    return bond_from_lots + days_detained * STORAGE_DAILY_CENTS


# ---------------------------------------------------------------------------
# active_recall_gate
# ---------------------------------------------------------------------------
def recall_gate_blocks(facility_id, product_code):
    for r in db.recalls.values():
        if (
            r["status"] == "CLASSIFIED"
            and r["classification"] == "CLASS_I"
            and r["facility_id"] == facility_id
            and r["product_code"] == product_code
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# petition_compliance_streak (computed at adjudication time)
# ---------------------------------------------------------------------------
def filer_in_scope(alert, filer_facility_id):
    if alert["scope_type"] == "FIRM":
        return filer_facility_id == alert["facility_id"]
    facility = db.facilities.get(filer_facility_id)
    if facility is None or facility["country_code"] != alert["country_code"]:
        return False
    product_code = alert["product_code"]
    for p in db.prior_notices.values():
        if p["facility_id"] == filer_facility_id and p["product_code"] == product_code:
            return True
    for e in db.entries.values():
        if e["facility_id"] == filer_facility_id and e["product_code"] == product_code:
            return True
    return False


def compliance_streak(alert):
    candidates = []
    for e in db.entries.values():
        if not alert_matches_entry(alert, e):
            continue
        if e["disposition_completed_at"] is None:
            continue
        if e["disposition_completed_at"] < alert["created_at"]:
            continue
        candidates.append(e)
    candidates.sort(key=lambda e: (e["disposition_completed_at"], e["created_at"], e["_seq"]))
    streak = 0
    for e in reversed(candidates):
        if e["disposition_status"] in ("RELEASED", "RECONDITIONED"):
            streak += 1
        else:
            break
    return streak


# ---------------------------------------------------------------------------
# Ops checkpoint (PRD section 2.4): facility expiry sweep, then the detention
# deadline sweep. Both comparisons are strictly-less-than.
# ---------------------------------------------------------------------------
def run_checkpoint(new_now):
    expired_facility_ids = []
    for f in sorted(db.facilities.values(), key=db.sort_key):
        if f["registration_status"] == "REGISTERED" and f["expires_at"] < new_now:
            f["registration_status"] = "EXPIRED"
            db.touch(f, new_now)
            expired_facility_ids.append(f["id"])
    auto_refused_entry_ids = []
    for e in sorted(db.entries.values(), key=db.sort_key):
        if e["disposition_status"] != "DETAINED":
            continue
        if e["response_deadline_at"] + timedelta(hours=SWEEP_GRACE_HOURS) < new_now:
            refuse_entry(e, new_now)
            auto_refused_entry_ids.append(e["id"])
    return expired_facility_ids, auto_refused_entry_ids
