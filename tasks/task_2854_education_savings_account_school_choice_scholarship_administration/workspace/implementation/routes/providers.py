"""Provider registration, fraud screening, admission banding and sanctions."""
from flask import Blueprint

import calc
import cascades
import lookups
from envelope import list_response, object_response, public, touch
from errors import fail, invalid
from store import by_seq, new_id, store
from validators import (EIN_RE, PROVIDER_TYPES, SCREENING_FLAGS, authenticate,
                        body, paginate, v_enum, v_flag_list, v_state_code,
                        v_str, v_str_list)

bp = Blueprint("providers", __name__)

ELEVATED_SCREENING_REASON = "ELEVATED_SCREENING_SCORE"


@bp.post("/providers")
def create_provider():
    authenticate("ProgramAdmin")
    payload = body()
    legal_name = v_str(payload, "legal_name")
    ein = v_str(payload, "ein")
    address_state = v_state_code(payload, "address_state")
    provider_type = v_enum(payload, "provider_type", PROVIDER_TYPES)
    if not EIN_RE.match(ein):
        invalid("ein must be exactly nine digits")
    for existing in store.providers.values():
        if existing["ein"] == ein:
            invalid("ein '%s' is already registered" % ein)

    created_at = store.next_created_at()
    record = {
        "id": new_id(),
        "legal_name": legal_name,
        "ein": ein,
        "address_state": address_state,
        "provider_type": provider_type,
        "status": "DRAFT",
        "authorized_category_codes": [],
        "screening_score": 0,
        "screening_flags": [],
        "screened_at": None,
        "surveillance_score": 0,
        "substantiated_case_count": 0,
        "sanction_reason": None,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.providers[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/providers/<pid>")
def read_provider(pid):
    authenticate("ProgramAdmin", "VendorScreener", "ComplianceOfficer",
                 "AppealsOfficer", "ExpenseReviewer", "Guardian", "Provider")
    return object_response(public(lookups.provider(pid)))


@bp.post("/providers/<pid>/fraud-screenings")
def create_screening(pid):
    user_id, _role = authenticate("VendorScreener")
    payload = body()
    flags = v_flag_list(payload, "flags", SCREENING_FLAGS)
    prov = lookups.provider(pid)
    if prov["status"] not in ("DRAFT", "SCREENED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a DRAFT or SCREENED provider may be screened")

    score = calc.screening_static_score(flags)
    screened_at = store.now()
    row = {
        "id": new_id(),
        "provider_id": pid,
        "flags": list(flags or []),
        "screening_score": score,
        "recommended_status": calc.recommended_status(score),
        "screened_by_user_id": user_id,
        "screened_at": screened_at,
        "created_at": store.next_created_at(),
        "_seq": store.next_seq(),
    }
    store.fraud_screenings[row["id"]] = row

    prov["status"] = "SCREENED"
    prov["screening_score"] = score
    prov["screening_flags"] = list(flags or [])
    prov["screened_at"] = screened_at
    prov["surveillance_score"] = score
    touch(prov)
    return object_response(public(row), 201)


@bp.get("/providers/<pid>/fraud-screenings")
def list_screenings(pid):
    authenticate("ProgramAdmin", "VendorScreener", "ComplianceOfficer",
                 "AppealsOfficer")
    lookups.provider(pid)
    rows = by_seq([s for s in store.fraud_screenings.values()
                   if s["provider_id"] == pid])
    page, meta = paginate(rows)
    return list_response([public(r) for r in page], meta)


@bp.post("/providers/<pid>/approve")
def approve_provider(pid):
    authenticate("VendorScreener")
    payload = body()
    codes = v_str_list(payload, "authorized_category_codes")
    prov = lookups.provider(pid)
    for code in codes:
        if lookups.category_by_code(code) is None:
            fail("ERR_EXPENSE_CATEGORY_NOT_FOUND",
                 "no catalogue entry with code '%s'" % code)
    if prov["status"] != "SCREENED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a SCREENED provider may be admitted")
    if prov["screening_score"] >= 60:
        fail("ERR_FRAUD_RISK_TOO_HIGH",
             "screening score %s is too high for admission"
             % prov["screening_score"])

    prov["authorized_category_codes"] = list(codes)
    if prov["screening_score"] < 40:
        prov["status"] = "APPROVED"
    else:
        prov["status"] = "PROBATION"
        prov["sanction_reason"] = ELEVATED_SCREENING_REASON
    touch(prov)
    return object_response(public(prov))


@bp.post("/providers/<pid>/sanctions")
def sanction_provider(pid):
    authenticate("ComplianceOfficer")
    payload = body()
    action = v_enum(payload, "action", ("PROBATION", "REINSTATE", "DELIST"))
    reason = v_str(payload, "reason")
    prov = lookups.provider(pid)

    if action == "PROBATION":
        if prov["status"] != "APPROVED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only an APPROVED provider may be placed on probation")
        prov["status"] = "PROBATION"
        prov["sanction_reason"] = reason
        touch(prov)
    elif action == "REINSTATE":
        if prov["status"] != "PROBATION":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only a provider on PROBATION may be reinstated")
        if prov["surveillance_score"] >= 75:
            fail("ERR_FRAUD_RISK_TOO_HIGH",
                 "surveillance score %s is too high for reinstatement"
                 % prov["surveillance_score"])
        prov["status"] = "APPROVED"
        prov["sanction_reason"] = None
        touch(prov)
    else:
        if prov["status"] not in ("APPROVED", "PROBATION"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "only an APPROVED or PROBATION provider may be delisted")
        cascades.delist_provider(prov, reason)
    return object_response(public(prov))
