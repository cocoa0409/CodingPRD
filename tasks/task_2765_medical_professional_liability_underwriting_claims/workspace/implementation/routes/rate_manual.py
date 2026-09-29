"""Specialty classes and rate filings (PRD 3.1)."""
from flask import Blueprint, g

import constants as C
from auth import deny_self_decision, endpoint, find, rate_filing, specialty_class
from envelope import created, listing, ok, pagination
from errors import ApiError
from routes import common
from store import all_of, db, new_record, touch
from val import ZERO, body, d, r2, v_date, v_decimal, v_enum, v_money, v_str
from services import actuarial, rating

bp = Blueprint("rate_manual", __name__, url_prefix=C.API_PREFIX)


@bp.post("/specialty-classes")
@endpoint([C.R_ANALYST, C.R_CHIEF])
def create_specialty_class():
    payload = body()
    specialty_code = v_enum(payload, "specialty_code", C.SPECIALTY_CODES)
    base_class_code = v_enum(payload, "base_class_code", C.BASE_CLASS_CODES)
    base_rate = v_money(
        payload, "base_rate_per_million", minimum=ZERO, exclusive_minimum=True
    )
    hazard_index = v_decimal(
        payload,
        "hazard_index",
        places=6,
        minimum=C.HAZARD_INDEX_MIN,
        maximum=C.HAZARD_INDEX_MAX,
    )
    benchmark = v_money(
        payload, "benchmark_severity", minimum=ZERO, exclusive_minimum=True
    )
    for existing in db.specialty_classes.values():
        if existing["specialty_code"] == specialty_code:
            raise ApiError(
                "ERR_VALIDATION", "specialty_code is already used by another class."
            )
    record = new_record(
        {
            "specialty_code": specialty_code,
            "base_class_code": base_class_code,
            "base_rate_per_million": base_rate,
            "hazard_index": hazard_index,
            "benchmark_severity": benchmark,
            "rate_revision_index": 0,
            "last_approved_rate_change_pct": None,
        }
    )
    db.specialty_classes[record["id"]] = record
    return created(record)


@bp.get("/specialty-classes/<record_id>")
@endpoint(C.CARRIER_ROLES)
def get_specialty_class(record_id):
    return ok(specialty_class(record_id))


@bp.get("/specialty-classes")
@endpoint(C.CARRIER_ROLES)
def list_specialty_classes():
    limit, offset = pagination()
    records = all_of(db.specialty_classes)
    records = common.eq(records, "specialty_code", common.arg("specialty_code"))
    records = common.eq(records, "base_class_code", common.arg("base_class_code"))
    return listing(records, limit, offset)


@bp.post("/rate-filings")
@endpoint([C.R_ANALYST, C.R_CHIEF])
def create_rate_filing():
    payload = body()
    class_id = v_str(payload, "specialty_class_id")
    method = v_enum(payload, "indication_method", C.INDICATION_METHODS)
    proposed = v_decimal(
        payload,
        "proposed_rate_change_pct",
        places=2,
        minimum=C.RATE_CHANGE_MIN_PCT,
        maximum=C.RATE_CHANGE_MAX_PCT,
    )
    period_start = v_date(payload, "experience_period_start")
    period_end = v_date(payload, "experience_period_end")
    effective_date = v_date(payload, "effective_date")

    specialty_class(class_id)

    if not (d(period_end) > d(period_start)) or d(effective_date) < d(period_end):
        raise ApiError("ERR_EXPERIENCE_PERIOD_INVALID")

    record = new_record(
        {
            "specialty_class_id": class_id,
            "filing_number": db.next_filing_number(),
            "indication_method": method,
            "proposed_rate_change_pct": proposed,
            "experience_period_start": period_start,
            "experience_period_end": period_end,
            "effective_date": effective_date,
            "claim_count_in_scope": 0,
            "in_scope_premium_total": r2(ZERO),
            "actuarial_incurred_total": r2(ZERO),
            "experience_loss_ratio": None,
            "indicated_change_pct": None,
            "credibility_weight": ZERO,
            "credibility_weighted_indication_pct": None,
            "carried_reserve_total": r2(ZERO),
            "required_reserve_total": r2(ZERO),
            "reserve_adequacy_ratio": None,
            "adequacy_flag": "NOT_EVALUABLE",
            "status": "DRAFT",
            "prepared_by_user_id": g.user_id,
            "decided_by_user_id": None,
            "approved_rate_change_pct": None,
            "decision_note": None,
        }
    )
    actuarial.run_block(record)
    db.rate_filings[record["id"]] = record
    return created(record)


@bp.get("/rate-filings/<record_id>")
@endpoint(C.CARRIER_ROLES)
def get_rate_filing(record_id):
    return ok(rate_filing(record_id))


@bp.get("/rate-filings")
@endpoint(C.CARRIER_ROLES)
def list_rate_filings():
    limit, offset = pagination()
    records = all_of(db.rate_filings)
    records = common.eq(records, "specialty_class_id", common.arg("specialty_class_id"))
    records = common.eq(records, "status", common.arg("status"))
    records = common.eq(records, "adequacy_flag", common.arg("adequacy_flag"))
    records = common.eq(records, "indication_method", common.arg("indication_method"))
    return listing(records, limit, offset)


@bp.post("/rate-filings/<record_id>/submission")
@endpoint([C.R_ANALYST, C.R_CHIEF])
def submit_rate_filing(record_id):
    filing = rate_filing(record_id)
    if filing["status"] != "DRAFT":
        raise ApiError("ERR_FILING_STATE_INVALID")
    actuarial.run_block(filing)
    filing["status"] = "SUBMITTED"
    touch(filing)
    return ok(filing)


@bp.post("/rate-filings/<record_id>/decision")
@endpoint([C.R_CHIEF])
def decide_rate_filing(record_id):
    raw = body()
    candidate = find(db.rate_filings, record_id)
    if candidate is not None and raw.get("decision") in ("APPROVE", "REJECT"):
        deny_self_decision(candidate)

    decision = v_enum(raw, "decision", C.FILING_DECISIONS)
    note = v_str(raw, "decision_note")

    filing = rate_filing(record_id)

    if decision in ("APPROVE", "REJECT"):
        if filing["status"] != "SUBMITTED":
            raise ApiError("ERR_FILING_STATE_INVALID")
    elif filing["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_FILING_STATE_INVALID")

    if decision == "APPROVE" and filing["adequacy_flag"] == "DEFICIENT":
        raise ApiError("ERR_RESERVE_DEFICIENCY_BLOCKS_FILING")

    filing["decision_note"] = note
    if decision == "WITHDRAW":
        filing["status"] = "WITHDRAWN"
    elif decision == "REJECT":
        filing["status"] = "REJECTED"
        filing["decided_by_user_id"] = g.user_id
    else:
        filing["status"] = "APPROVED"
        filing["decided_by_user_id"] = g.user_id
        approved = filing["proposed_rate_change_pct"]
        filing["approved_rate_change_pct"] = approved
        specialty = db.specialty_classes[filing["specialty_class_id"]]
        specialty["base_rate_per_million"] = r2(
            specialty["base_rate_per_million"] * (1 + approved / 100)
        )
        specialty["rate_revision_index"] = int(specialty["rate_revision_index"]) + 1
        specialty["last_approved_rate_change_pct"] = approved
        touch(specialty)
        rating.rerate_specialty_class(specialty["id"])
    touch(filing)
    return ok(filing)
