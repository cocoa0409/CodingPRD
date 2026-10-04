"""Domain logic: rules, identity matching, risk scoring, clock sweep, events."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from util import fmt_dt, add_years

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RULE_DEFAULTS = {
    "retention_years": 7,
    "reinvestigation_days": 30,
    "correction_hold_days": 45,
    "data_freeze_days": 60,
    "reciprocity_lag_threshold_days": 45,
    "max_outstanding_inquiries": 50,
    "min_batch_claims": 1,
    "max_batch_claims": 500,
    "disclosure_window_days": 5,
    "premium_weight_cap_cents": 500000,
}

LOSS_TYPES = {"COLLISION", "COMPREHENSIVE", "LIABILITY", "PROPERTY", "OTHER"}
CLAIM_STATUS_CODES = {"OPEN", "CLOSED_WITH_PAYMENT", "CLOSED_WITHOUT_PAYMENT", "SUBROGATED"}
PERMISSIBLE_PURPOSES = {"UNDERWRITING", "CLAIMS", "CONSUMER_REQUEST"}
DISPUTE_REASONS = {"NOT_MY_CLAIM", "WRONG_AMOUNT", "WRONG_DATE", "ALREADY_REMOVED", "OTHER"}
RESOLUTION_CODES = {"VERIFIED_ACCURATE", "AMENDED", "DELETED"}
NOTICE_ACTION_TYPES = {"DECLINE", "RATE_INCREASE", "NON_RENEWAL", "CANCELLATION"}

GRADE_POINTS = {"EXACT": 50, "FUZZY": 25, "MISMATCH": 0, "ABSENT": 0}
GRADE_RANK = {"EXACT": 3, "FUZZY": 2, "MISMATCH": 1, "ABSENT": 0}


def get_rules():
    """Return the rulebook dict, or declared defaults when uninitialized."""
    if db.exchange_rule is not None:
        return db.exchange_rule
    return dict(RULE_DEFAULTS)


# ---------------------------------------------------------------------------
# Audit events (immutable snapshot kind: id + created_at only)
# ---------------------------------------------------------------------------

def add_event(event_type, carrier_id=None, consumer_id=None, details=None):
    now = db.now()
    ev = {
        "id": db.new_id(),
        "carrier_id": carrier_id,
        "consumer_id": consumer_id,
        "event_type": event_type,
        "event_at": fmt_dt(now),
        "details": details or {},
        "created_at": fmt_dt(now),
        "_seq": db.next_seq(),
    }
    db.audit_events[ev["id"]] = ev
    return ev


def serialize_event(ev):
    return {k: v for k, v in ev.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Carrier standing / contribution lag
# ---------------------------------------------------------------------------

def carrier_lag_days(carrier):
    """Whole days since the most recent COMPLETED batch, minus the submission
    day itself, floored at zero. None when the carrier has never completed."""
    completed = [b for b in db.batches.values()
                 if b["carrier_id"] == carrier["id"] and b["status"] == "COMPLETED"]
    if not completed:
        return None
    latest = max(b["_submitted_dt"] for b in completed)
    delta = db.now() - latest
    days = int(delta.total_seconds() // 86400)
    return max(0, days - 1)


def maybe_suspend_or_reactivate(carrier, suspended_out=None, reactivated_out=None):
    """Re-evaluate one carrier's standing against the current clock."""
    rules = get_rules()
    threshold = rules["reciprocity_lag_threshold_days"]
    lag = carrier_lag_days(carrier)
    if lag is None:
        return
    if lag >= threshold and carrier["status"] == "ACTIVE":
        carrier["status"] = "SUSPENDED"
        touch(carrier)
        add_event("CARRIER_SUSPENDED", carrier_id=carrier["id"],
                  details={"contribution_lag_days": lag})
        if suspended_out is not None:
            suspended_out.append(carrier["id"])
    elif lag < threshold and carrier["status"] == "SUSPENDED":
        carrier["status"] = "ACTIVE"
        touch(carrier)
        add_event("CARRIER_REACTIVATED", carrier_id=carrier["id"],
                  details={"contribution_lag_days": lag})
        if reactivated_out is not None:
            reactivated_out.append(carrier["id"])


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------

def stamp_new(rec):
    now = fmt_dt(db.now())
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = fmt_dt(db.now())
    rec["version"] += 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_by_creation(recs):
    return sorted(recs, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Identity matching (identity_match_score)
# ---------------------------------------------------------------------------

def _retention_passing_active_claims(consumer_id):
    rules = get_rules()
    clock_date = db.now().date()
    out = []
    for c in db.claims.values():
        if c["consumer_id"] != consumer_id:
            continue
        if c["status"] != "ACTIVE":
            continue
        carrier = db.carriers.get(c["contributing_carrier_id"])
        if carrier is not None and carrier["status"] == "WITHDRAWN":
            continue
        if clock_date < c["_retention_expires_date"]:
            out.append(c)
    return out


def _consumer_has_vehicle(consumer_id, vin):
    if not vin:
        return False
    for c in db.claims.values():
        if c["consumer_id"] == consumer_id and c["vehicle_identifier"] and \
                c["vehicle_identifier"] == vin:
            return True
    return False


def compute_match(subject_name, subject_dob, subject_address, subject_dl,
                  subject_vehicle):
    """Returns (matched_consumer_or_None, grades_dict, match_score,
    disposition)."""
    dl = subject_dl or ""
    veh = subject_vehicle or ""

    # Candidate bundle: consumers sharing at least one identifier signal.
    candidates = []
    for c in db.consumers.values():
        shared = False
        if dl and c["driver_license_number"] == dl:
            shared = True
        if c["full_name"] == subject_name and c["date_of_birth"] == subject_dob:
            shared = True
        if subject_address and c["address_line"] == subject_address:
            shared = True
        if veh and _consumer_has_vehicle(c["id"], veh):
            shared = True
        if shared:
            candidates.append(c)

    if not candidates:
        return None, None, 0, "UNMATCHED"

    best = None  # (score, consumer)
    grade_max = {"individual": "ABSENT", "address": "ABSENT", "vehicle": "ABSENT"}

    for c in candidates:
        # Individual grade: driver license dominates; fall back to name+DOB.
        if dl and c["driver_license_number"] == dl:
            ind = "EXACT"
        elif c["full_name"] == subject_name and c["date_of_birth"] == subject_dob:
            ind = "FUZZY"
        else:
            ind = "ABSENT"
        addr_g = "EXACT" if (subject_address and
                             c["address_line"] == subject_address) else "ABSENT"
        veh_g = "EXACT" if (veh and _consumer_has_vehicle(c["id"], veh)) else "ABSENT"

        for dim, g in (("individual", ind), ("address", addr_g), ("vehicle", veh_g)):
            if GRADE_RANK[g] > GRADE_RANK[grade_max[dim]]:
                grade_max[dim] = g

        included = _retention_passing_active_claims(c["id"])
        loss_units = len(included)

        if ind == "EXACT":
            ind_term = 100 * GRADE_POINTS["EXACT"]          # 5000
        elif ind == "FUZZY":
            ind_term = 50 * GRADE_POINTS["FUZZY"]           # 1250
        else:
            ind_term = 0
        score = (ind_term
                 + 30 * GRADE_POINTS[veh_g]
                 + 20 * GRADE_POINTS[addr_g]
                 + 50 * loss_units)

        if best is None or score > best[0] or (
                score == best[0] and c["_seq"] < best[1]["_seq"]):
            best = (score, c)

    score, winner = best
    if score >= 7000:
        disposition = "DEFINITE"
    elif score >= 5500:
        disposition = "PROBABLE"
    elif score >= 4000:
        disposition = "POSSIBLE"
    else:
        disposition = "UNMATCHED"

    if disposition == "UNMATCHED":
        return None, grade_max, score, disposition
    return winner, grade_max, score, disposition


# ---------------------------------------------------------------------------
# Report issuance (report_inclusion_set, risk_certainty_score, risk_score_dual)
# ---------------------------------------------------------------------------

def issue_report(inquiry, carrier, consumer, match_disposition, match_score):
    rules = get_rules()
    included = _retention_passing_active_claims(consumer["id"])
    # Ordering: loss_date DESC, then created_at ASC (insertion order).
    included.sort(key=lambda c: (-c["_loss_date_ord"], c["_seq"]))

    certainty = Decimal(match_score) / Decimal(100)
    certainty = certainty.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    n = len(included)
    risk_count = int((Decimal(n) * certainty).quantize(Decimal("1"),
                                                      rounding=ROUND_HALF_UP))
    cap = rules["premium_weight_cap_cents"]
    base_cents = sum(min(c["paid_amount_cents"], cap) for c in included)
    risk_premium = int((Decimal(base_cents) * certainty / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))

    now = fmt_dt(db.now())
    report = {
        "id": db.new_id(),
        "inquiry_id": inquiry["id"],
        "carrier_id": carrier["id"],
        "consumer_id": consumer["id"],
        "match_disposition": match_disposition,
        "risk_score_certainty": float(certainty),
        "risk_score_count": risk_count,
        "risk_score_premium_weighted_cents": risk_premium,
        "claim_count_reported": n,
        "status": "ISSUED",
        "delivered_at": now,
    }
    stamp_new(report)
    db.reports[report["id"]] = report

    for i, c in enumerate(included, start=1):
        entry = {
            "id": db.new_id(),
            "report_id": report["id"],
            "loss_claim_id": c["id"],
            "consumer_id": consumer["id"],
            "entry_sequence": i,
            "loss_date": c["loss_date"],
            "loss_type": c["loss_type"],
            "cause_of_loss_code": c["cause_of_loss_code"],
            "paid_amount_cents": c["paid_amount_cents"],
            "claim_status_code": c["claim_status_code"],
            "contributing_carrier_id": c["contributing_carrier_id"],
            "created_at": now,
            "_seq": db.next_seq(),
        }
        db.entries[entry["id"]] = entry

    add_event("REPORT_ISSUED", carrier_id=carrier["id"],
              consumer_id=consumer["id"],
              details={"report_id": report["id"], "inquiry_id": inquiry["id"],
                       "match_disposition": match_disposition,
                       "claim_count_reported": n})
    return report


# ---------------------------------------------------------------------------
# Clock sweep
# ---------------------------------------------------------------------------

def sweep_clock():
    """Run after the logical clock moves. Returns the sweep payload sets."""
    rules = get_rules()
    now = db.now()

    suspended_ids = []
    reactivated_ids = []
    for carrier in list(db.carriers.values()):
        maybe_suspend_or_reactivate(carrier, suspended_ids, reactivated_ids)

    expired_freeze_ids = []
    for consumer in list(db.consumers.values()):
        if consumer["file_frozen"] and consumer["_frozen_until_dt"] is not None \
                and now >= consumer["_frozen_until_dt"]:
            consumer["file_frozen"] = False
            consumer["frozen_until"] = None
            consumer["_frozen_until_dt"] = None
            touch(consumer)
            add_event("DATA_FREEZE_LIFTED", consumer_id=consumer["id"],
                      details={})
            expired_freeze_ids.append(consumer["id"])

    overdue_ids = []
    for dispute in list(db.disputes.values()):
        if dispute["status"] in ("FILED", "UNDER_REINVESTIGATION") \
                and not dispute.get("_overdue_flagged") \
                and now >= dispute["_due_dt"]:
            dispute["_overdue_flagged"] = True
            claim = db.claims.get(dispute["loss_claim_id"])
            add_event("DISPUTE_OVERDUE",
                      carrier_id=claim["contributing_carrier_id"] if claim else None,
                      consumer_id=dispute["consumer_id"],
                      details={"dispute_id": dispute["id"]})
            overdue_ids.append(dispute["id"])

    redacted_ids = []
    clock_date = now.date()
    for claim in list(db.claims.values()):
        if claim.get("_retention_redacted"):
            continue
        if claim["status"] == "WITHDRAWN":
            continue
        if clock_date >= claim["_retention_expires_date"]:
            claim["_retention_redacted"] = True
            add_event("RETENTION_REDACTED",
                      carrier_id=claim["contributing_carrier_id"],
                      consumer_id=claim["consumer_id"],
                      details={"claim_id": claim["id"]})
            redacted_ids.append(claim["id"])

    return {
        "current_utc": fmt_dt(now),
        "suspended_carrier_ids": suspended_ids,
        "reactivated_carrier_ids": reactivated_ids,
        "expired_freeze_consumer_ids": expired_freeze_ids,
        "overdue_dispute_ids": overdue_ids,
        "retention_redacted_claim_ids": redacted_ids,
    }
