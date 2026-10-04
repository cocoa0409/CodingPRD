"""Persistency measurement and renewal income (PRD §3.7, §2.8 closed windows)."""

from db import db, ts, parse_dt
from errors import (
    err,
    ERR_PERSISTENCY_NOT_FOUND,
    ERR_ADVISOR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_PERSISTENCY_WINDOW_OVERLAP,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from services import calc, derived


def get(record_id):
    row = db.persistency.get(record_id)
    if row is None:
        raise err(ERR_PERSISTENCY_NOT_FOUND,
                  "no persistency record with id %s" % record_id)
    return row


def open_record(data):
    advisor_id = data.get("advisor_id")
    if advisor_id is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "advisor_id is required")
    if advisor_id not in db.advisors:
        raise err(ERR_ADVISOR_NOT_FOUND, "no advisor with id %s" % advisor_id)

    from middleware import require_fields
    require_fields(data, ["measurement_period", "measurement_start", "measurement_end",
                          "policies_issued", "policies_persisted"])
    start = parse_dt(data.get("measurement_start"))
    end = parse_dt(data.get("measurement_end"))
    # CLOSED [measurement_start, measurement_end]; a shared boundary instant is
    # an overlap (PRD §2.8).
    for row in db.persistency.values():
        if row["advisor_id"] != advisor_id:
            continue
        if start <= row["measurement_end"] and row["measurement_start"] <= end:
            raise err(ERR_PERSISTENCY_WINDOW_OVERLAP,
                      "the measurement window shares an instant with another window")

    record = {
        "advisor_id": advisor_id,
        "measurement_period": data.get("measurement_period"),
        "measurement_start": start,
        "measurement_end": end,
        "policies_issued": int(data.get("policies_issued") or 0),
        "policies_persisted": int(data.get("policies_persisted") or 0),
        "persistency_pct": None,
        "persistency_tier": None,
        "renewal_rate_pct": None,
        "renewal_commission_cents": 0,
        "status": "PROVISIONAL",
    }
    db.stamp_create(record)
    db.insert(db.persistency, record)
    return record


def dispute(record, actor_id):
    """Ownership-scoped (PRD §3.7): X-User-ID must equal the record's advisor_id."""
    if actor_id != record["advisor_id"]:
        raise err(ERR_INSUFFICIENT_PERMISSIONS,
                  "only the measured advisor may dispute this record")
    if record["status"] == "FINALIZED":
        raise err(ERR_ALREADY_TERMINAL, "the record is finalized")
    if record["status"] != "PROVISIONAL":
        raise err(ERR_INVALID_STATE, "the record is not PROVISIONAL")
    record["status"] = "DISPUTED"
    db.touch(record)
    return record


def resolve_dispute(record):
    if record["status"] == "FINALIZED":
        raise err(ERR_ALREADY_TERMINAL, "the record is finalized")
    if record["status"] != "DISPUTED":
        raise err(ERR_INVALID_STATE, "the record is not DISPUTED")
    record["status"] = "PROVISIONAL"
    db.touch(record)
    return record


def _renewal_base(advisor_id, measurement_start, measurement_end):
    """Sum of annual_premium_cents over the advisor's policies whose status is
    ACTIVE at the instant of measurement_end within the CLOSED window (PRD §3.7)."""
    total = 0
    for policy in db.policies.values():
        if policy["writing_advisor_id"] != advisor_id:
            continue
        if policy["status"] != "ACTIVE":
            continue
        if measurement_start <= measurement_end:
            total += int(policy["annual_premium_cents"])
    return total


def finalize(record):
    advisor = db.advisors.get(record["advisor_id"])
    if advisor is None:
        raise err(ERR_ADVISOR_NOT_FOUND, "the measured advisor no longer exists")

    if record["status"] == "FINALIZED":
        raise err(ERR_ALREADY_TERMINAL, "the record is already finalized")
    if record["status"] == "PROVISIONAL":
        if advisor["contract_status"] != "VALIDATED" or advisor["validation_posture"] != "VALIDATED":
            raise err(ERR_INVALID_STATE,
                      "finalization requires a VALIDATED contract and posture")
    elif record["status"] == "DISPUTED":
        if advisor["contract_status"] != "VALIDATED":
            raise err(ERR_INVALID_STATE,
                      "finalization requires a VALIDATED contract")
    else:
        raise err(ERR_INVALID_STATE, "the record is not finalizable")

    pct = calc.persistency_pct(record["policies_issued"], record["policies_persisted"])
    tier, rate = calc.persistency_tier(pct)
    base = _renewal_base(advisor["id"], record["measurement_start"], record["measurement_end"])
    renewal = calc.renewal_commission(base, rate) if tier != "INELIGIBLE" else 0

    record["persistency_pct"] = calc.f2(pct)
    record["persistency_tier"] = tier
    record["renewal_rate_pct"] = float(rate)
    record["renewal_commission_cents"] = renewal
    record["status"] = "FINALIZED"
    db.touch(record)

    # The advisor's renewal_commission_cents accrues by ADDITION here (§2.7).
    advisor["renewal_commission_cents"] = int(advisor["renewal_commission_cents"]) + renewal
    db.touch(advisor)

    credit = {
        "policy_id": None,
        "advisor_id": advisor["id"],
        "credit_type": "RENEWAL",
        "credit_pct": 0.0,
        "gross_commission_cents": renewal,
        "net_commission_cents": renewal,
        "advanced_paid_cents": 0,
        "case_gross_commission_cents": 0,
        "chargeback_assessed_cents": 0,
        "recovered_cents": 0,
        "chargeback_reason": None,
        "status": "ACCRUED",
    }
    db.stamp_create(credit)
    db.insert(db.credits, credit)

    if tier == "INELIGIBLE":
        _demote_ineligible(advisor)
    derived.cascade_rollups()
    return record


def _demote_ineligible(advisor):
    """VALIDATED -> AT_RISK on an INELIGIBLE finalization (PRD §3.7)."""
    if advisor["contract_status"] == "VALIDATED":
        advisor["contract_status"] = "AT_RISK"
        advisor["validation_posture"] = "AT_RISK"
        advisor["orphan_pool_access"] = False
        advisor["renewal_commission_cents"] = 0
        db.touch(advisor)
        for contract in db.contracts.values():
            if contract["advisor_id"] == advisor["id"] and contract["contract_status"] == "VALIDATED":
                contract["contract_status"] = "AT_RISK"
                db.touch(contract)
        for credit in db.credits.values():
            if credit["advisor_id"] == advisor["id"] and credit["status"] == "ACCRUED":
                derived.refresh_credit_amounts(credit)
                db.touch(credit)
    derived.recompute_team_production(advisor["id"])