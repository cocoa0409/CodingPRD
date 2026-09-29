"""Read-only derivations (PRD §2.9) and the JSON projection of every entity.

A derived field is never patched incrementally - it is recomputed from its
source rows every time it is read or re-derived, which is exactly why a voided
charge line disappears from an aggregate simply by ceasing to match the
aggregate's filter.
"""

from calc import notification_acknowledged_at, notification_sent_at, storage_basis
from clockcal import fmt_instant
from store import db

# --------------------------------------------------------------------------
# row scans
# --------------------------------------------------------------------------

def cycles_of_customer(customer_id):
    return [c for c in db.cycles.values() if c["customer_id"] == customer_id]


def charge_of_cycle(cycle_id):
    for ch in db.charges.values():
        if ch["placement_cycle_id"] == cycle_id:
            return ch
    return None


def charges_of_customer(customer_id):
    out = []
    for ch in db.charges.values():
        cyc = db.cycles.get(ch["placement_cycle_id"])
        if cyc is not None and cyc["customer_id"] == customer_id:
            out.append(ch)
    return out


def notifications_of_cycle(cycle_id):
    rows = [n for n in db.notifications.values()
            if n["placement_cycle_id"] == cycle_id]
    rows.sort(key=lambda n: (n["created_at"], n["_seq"]))
    return rows


def evidence_of_dispute(dispute_id):
    rows = [e for e in db.evidence.values()
            if e["demurrage_dispute_id"] == dispute_id]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return rows


def disputes_of_invoice(invoice_id):
    return [d for d in db.disputes.values() if d["invoice_id"] == invoice_id]


def live_charges_of_invoice(invoice_id):
    """A line is live when its status is not VOIDED; voided lines are invisible
    to every aggregate (PRD §3.7)."""
    rows = [ch for ch in db.charges.values()
            if ch["invoice_id"] == invoice_id and ch["status"] != "VOIDED"]
    rows.sort(key=lambda ch: (ch["created_at"], ch["id"]))
    return rows


def open_agreement(customer_id, month):
    for ag in db.agreements.values():
        if (ag["customer_id"] == customer_id and ag["status"] == "OPEN"
                and ag["agreement_month"] == month):
            return ag
    return None


# --------------------------------------------------------------------------
# Customer derivations (PRD §3.1)
# --------------------------------------------------------------------------

def customer_credit_balance_cents(customer_id):
    total = 0
    for ch in charges_of_customer(customer_id):
        if ch["status"] in ("FINAL", "ADJUSTED"):
            total += ch["credit_applied_cents"]
    return total


def customer_dispute_posture(customer_id):
    statuses = set()
    for d in db.disputes.values():
        if d["customer_id"] == customer_id:
            statuses.add(d["status"])
    if "ESCALATED" in statuses:
        return "ESCALATED"
    if statuses & {"SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPEALED"}:
        return "UNDER_REVIEW"
    return "CLEAR"


# --------------------------------------------------------------------------
# Facility and RailCar derivations (PRD §3.1)
# --------------------------------------------------------------------------

def facility_occupied_spot_count(facility_id):
    return sum(1 for c in db.cycles.values()
               if c["facility_id"] == facility_id
               and c["movement_status"] == "ACTUALLY_PLACED")


def facility_last_switch_at(facility_id):
    best = None
    for c in db.cycles.values():
        if c["facility_id"] != facility_id:
            continue
        for key in ("actual_placement_at", "released_at"):
            value = c.get(key)
            if value is not None and (best is None or value > best):
                best = value
    return best


def car_active_cycle_count(rail_car_id):
    return sum(1 for c in db.cycles.values()
               if c["rail_car_id"] == rail_car_id
               and c["movement_status"] not in ("RELEASED", "VOIDED"))


# --------------------------------------------------------------------------
# Invoice rollup and compound status (PRD §3.7)
# --------------------------------------------------------------------------

def invoice_rollup(invoice):
    """attached_charge_count, the three totals and dispute_count, always
    rebuilt from the live lines."""
    lines = live_charges_of_invoice(invoice["id"])
    gross = sum(ch["gross_amount_cents"] for ch in lines)
    credit = sum(ch["credit_applied_cents"] for ch in lines)
    return {
        "attached_charge_count": len(lines),
        "total_gross_cents": gross,
        "total_credit_cents": credit,
        "total_net_cents": gross - credit,
        "dispute_count": len(disputes_of_invoice(invoice["id"])),
    }


def invoice_status(invoice):
    """The compound status.  The order of the tests is part of the contract:
    DRAFT stays DRAFT, CLOSED stays CLOSED, then DISPUTED wins over credited,
    and ISSUED is the fallthrough."""
    base = invoice["status_base"]
    if base in ("DRAFT", "CLOSED"):
        return base
    lines = live_charges_of_invoice(invoice["id"])
    for ch in lines:
        if ch["status"] == "DISPUTED":
            return "PARTIALLY_DISPUTED"
    for ch in lines:
        if ch["credit_applied_cents"] > 0:
            return "ADJUSTED"
    return "ISSUED"


def dispute_evidence_weight(dispute_id):
    return sum(e["weight_points"] for e in evidence_of_dispute(dispute_id))


# --------------------------------------------------------------------------
# JSON projections.  Common fields per PRD §2.4; a car notification and a
# piece of dispute evidence deliberately carry only id and created_at.
# --------------------------------------------------------------------------

def _common(rec):
    out = {"id": rec["id"], "created_at": fmt_instant(rec["created_at"])}
    if "version" in rec:
        out["updated_at"] = fmt_instant(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def customer_json(rec):
    out = _common(rec)
    out.update({
        "customer_code": rec["customer_code"],
        "name": rec["name"],
        "serving_station_code": rec["serving_station_code"],
        "notification_method": rec["notification_method"],
        "normal_daily_placement_capacity": rec["normal_daily_placement_capacity"],
        "status": rec["status"],
        "billing_posture": rec["billing_posture"],
        "credit_hold_reason": rec["credit_hold_reason"],
        "credit_balance_cents": customer_credit_balance_cents(rec["id"]),
        "dispute_posture": customer_dispute_posture(rec["id"]),
    })
    return out


_TARIFF_FIELDS = (
    "tariff_code", "car_ownership_scope", "free_time_hours_railroad",
    "free_time_hours_private", "tier1_day_count", "tier1_rate_cents_railroad",
    "tier1_rate_cents_private", "tier2_day_count", "tier2_rate_cents_railroad",
    "tier2_rate_cents_private", "tier3_rate_cents_railroad",
    "tier3_rate_cents_private", "weekend_excluded", "notification_grace_hours",
    "adjudication_days_base", "status", "challenge_count",
)


def tariff_json(rec):
    out = _common(rec)
    for name in _TARIFF_FIELDS:
        out[name] = rec[name]
    return out


_FACILITY_FIELDS = (
    "facility_code", "kind", "storage_clock_mode", "gate_open_hour",
    "gate_close_hour", "car_spot_capacity", "switch_buffer_minutes",
    "storage_free_hours", "storage_daily_rate_cents", "operates_weekends",
    "access_mode", "access_mode_reason",
)


def facility_json(rec):
    out = _common(rec)
    for name in _FACILITY_FIELDS:
        out[name] = rec[name]
    out["occupied_spot_count"] = facility_occupied_spot_count(rec["id"])
    out["last_switch_at"] = fmt_instant(facility_last_switch_at(rec["id"]))
    return out


def rail_car_json(rec):
    out = _common(rec)
    out.update({
        "car_mark": rec["car_mark"],
        "ownership": rec["ownership"],
        "car_type": rec["car_type"],
        "capacity_tons": rec["capacity_tons"],
        "active_cycle_count": car_active_cycle_count(rec["id"]),
    })
    return out


_CYCLE_INSTANTS = (
    "constructive_placement_at", "actual_placement_at", "released_at",
    "clock_start_at", "free_time_expires_at",
)


def cycle_json(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "rail_car_id": rec["rail_car_id"],
        "facility_id": rec["facility_id"],
        "tariff_rule_set_id": rec["tariff_rule_set_id"],
        "waybill_number": rec["waybill_number"],
        "movement_status": rec["movement_status"],
        "billing_status": rec["billing_status"],
        "constructive_reason_code": rec["constructive_reason_code"],
        "refusal_count": rec["refusal_count"],
        "clock_basis": rec["clock_basis"],
        "free_days": rec["free_days"],
        "chargeable_days": rec["chargeable_days"],
        "early_release_days": rec["early_release_days"],
    })
    for name in _CYCLE_INSTANTS:
        out[name] = fmt_instant(rec[name])
    notes = notifications_of_cycle(rec["id"])
    out["notification_sent_at"] = fmt_instant(notification_sent_at(notes))
    out["notification_acknowledged_at"] = fmt_instant(
        notification_acknowledged_at(notes))
    return out


def notification_json(rec):
    out = _common(rec)
    notes = notifications_of_cycle(rec["placement_cycle_id"])
    sequence = 1
    for index, note in enumerate(notes):
        if note["id"] == rec["id"]:
            sequence = index + 1
            break
    out.update({
        "placement_cycle_id": rec["placement_cycle_id"],
        "channel": rec["channel"],
        "sent_at": fmt_instant(rec["sent_at"]),
        "delivery_status": rec["delivery_status"],
        "acknowledged_at": fmt_instant(rec["acknowledged_at"]),
        "sequence_number": sequence,
    })
    return out


def charge_json(rec):
    out = _common(rec)
    billable = max(0, rec["chargeable_days"] - rec["bunching_exempt_days"])
    out.update({
        "placement_cycle_id": rec["placement_cycle_id"],
        "invoice_id": rec["invoice_id"],
        "charge_kind": rec["charge_kind"],
        "computation_basis": rec["computation_basis"],
        "chargeable_days": rec["chargeable_days"],
        "bunching_exempt_days": rec["bunching_exempt_days"],
        "billable_days": billable,
        "gross_amount_cents": rec["gross_amount_cents"],
        "credit_applied_cents": rec["credit_applied_cents"],
        "net_amount_cents": rec["gross_amount_cents"] - rec["credit_applied_cents"],
        "status": rec["status"],
    })
    return out


def invoice_json(rec):
    out = _common(rec)
    status = invoice_status(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "billing_period_start": fmt_instant(rec["billing_period_start"]),
        "billing_period_end": fmt_instant(rec["billing_period_end"]),
        "agreement_credit_cents": rec["agreement_credit_cents"],
        "dispute_deadline_at": fmt_instant(rec["dispute_deadline_at"]),
        "status": status,
    })
    roll = invoice_rollup(rec)
    out["attached_charge_count"] = roll["attached_charge_count"]
    out["dispute_count"] = roll["dispute_count"]
    if status == "DRAFT":
        # The money totals deliberately stay at zero until the invoice is
        # issued, because the credit calculation is part of issuing.
        out["total_gross_cents"] = 0
        out["total_credit_cents"] = 0
        out["total_net_cents"] = 0
    else:
        out["total_gross_cents"] = roll["total_gross_cents"]
        out["total_credit_cents"] = roll["total_credit_cents"]
        out["total_net_cents"] = roll["total_net_cents"]
    return out


def claim_json(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "cluster_window_start": fmt_instant(rec["cluster_window_start"]),
        "cluster_window_end": fmt_instant(rec["cluster_window_end"]),
        "method": rec["method"],
        "baseline_per_day": rec["baseline_per_day"],
        "delivered_car_count": rec["delivered_car_count"],
        "exempted_cycle_ids": list(rec["exempted_cycle_ids"]),
        "exempt_days_granted": rec["exempt_days_granted"],
        "cluster_chargeable_days": rec["cluster_chargeable_days"],
        "status": rec["status"],
    })
    return out


def dispute_json(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "invoice_id": rec["invoice_id"],
        "demurrage_charge_id": rec["demurrage_charge_id"],
        "bunching_claim_id": rec["bunching_claim_id"],
        "supersedes_dispute_id": rec["supersedes_dispute_id"],
        "scope": rec["scope"],
        "grounds": rec["grounds"],
        "narrative": rec["narrative"],
        "claimed_credit_cents": rec["claimed_credit_cents"],
        "target_charge_count": rec["target_charge_count"],
        "evidence_weight": dispute_evidence_weight(rec["id"]),
        "allowance_pct": rec["allowance_pct"],
        "allowed_credit_cents": rec["allowed_credit_cents"],
        "decision": rec["decision"],
        "decision_rationale": rec["decision_rationale"],
        "round_number": rec["round_number"],
        "info_request_count": rec["info_request_count"],
        "submitted_at": fmt_instant(rec["submitted_at"]),
        "adjudication_due_at": fmt_instant(rec["adjudication_due_at"]),
        "first_level_adjudicator_id": rec["first_level_adjudicator_id"],
        "appeal_adjudicator_id": rec["appeal_adjudicator_id"],
        "status": rec["status"],
    })
    return out


def evidence_json(rec):
    out = _common(rec)
    out.update({
        "demurrage_dispute_id": rec["demurrage_dispute_id"],
        "evidence_type": rec["evidence_type"],
        "observed_at": fmt_instant(rec["observed_at"]),
        "description": rec["description"],
        "weight_points": rec["weight_points"],
    })
    return out


def agreement_json(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "agreement_month": rec["agreement_month"],
        "credit_cap_ratio": rec["credit_cap_ratio"],
        "credit_days_earned": rec["credit_days_earned"],
        "debit_days_incurred": rec["debit_days_incurred"],
        "net_days": rec["net_days"],
        "agreement_credit_cents": rec["agreement_credit_cents"],
        "status": rec["status"],
    })
    return out


def complaint_json(rec):
    out = _common(rec)
    out.update({
        "demurrage_dispute_id": rec["demurrage_dispute_id"],
        "tariff_rule_set_id": rec["tariff_rule_set_id"],
        "complaint_type": rec["complaint_type"],
        "docket_narrative": rec["docket_narrative"],
        "docket_number": rec["docket_number"],
        "filed_at": fmt_instant(rec["filed_at"]),
        "response_due_at": fmt_instant(rec["response_due_at"]),
        "answer_narrative": rec["answer_narrative"],
        "ordered_credit_cents": rec["ordered_credit_cents"],
        "status": rec["status"],
    })
    return out


def storage_basis_of(facility):
    return storage_basis(facility)
