"""StateReturn endpoints: add, list, ready, remove."""
from flask import Blueprint

from core import (
    ApiError,
    check_ownership,
    db,
    endpoint,
    expected_version,
    f_date,
    f_int,
    f_str,
    body,
    bad_request,
    dump,
    new_row,
    paginate,
    parse_date,
    respond_object,
    touch,
)
import svc

bp = Blueprint("state_returns", __name__)


def _own(return_id):
    ret = svc.get_return(return_id)
    acct = db.accounts[ret["account_id"]]
    check_ownership(acct)
    return ret, acct


@bp.post("/tax/returns/<return_id>/state-returns")
@endpoint("Taxpayer")
def add_state_return(return_id):
    ret, acct = _own(return_id)
    payload = body()
    state_code = f_str(payload, "state_code")
    svc.require_account_active(acct)
    svc.require_return_editable(ret, error_id="ERR_INVALID_STATE")
    expected_version(payload, ret)

    # Uniqueness runs before residency-window and allocation checks (PRD 3.4).
    for sr in svc.state_returns_of(ret):
        if sr["status"] != "REMOVED" and sr["state_code"] == state_code:
            raise ApiError("ERR_DUPLICATE_STATE_RETURN", "A non-REMOVED StateReturn with this state_code already exists.")

    start = f_date(payload, "residency_start_date", required=False)
    end = f_date(payload, "residency_end_date", required=False)
    if start is not None:
        if end is None:
            bad_request("residency_end_date is required when residency_start_date is present.")
        if end <= start:
            bad_request("residency_end_date must be strictly later than residency_start_date.")
    # Half-open window overlap across non-REMOVED state returns.
    if start is not None:
        for sr in svc.state_returns_of(ret):
            if sr["status"] == "REMOVED":
                continue
            other_start = parse_date(sr["residency_start_date"]) if sr.get("residency_start_date") else None
            other_end = parse_date(sr["residency_end_date"]) if sr.get("residency_end_date") else None
            if other_start is None or other_end is None:
                continue
            if start < other_end and other_start < end:
                raise ApiError("ERR_RESIDENCY_OVERLAP", "Part-year residency windows overlap.")

    is_resident = state_code == acct["resident_state_code"]
    numerator = f_int(payload, "allocation_numerator_cents", required=False, default=0, minimum=0)
    denominator = f_int(payload, "allocation_denominator_cents", required=False, default=0, minimum=0)
    if not is_resident:
        if numerator > denominator or (numerator > 0 and denominator <= 0):
            raise ApiError("ERR_ALLOCATION_EXCEEDS_BASE", "allocation_numerator_cents exceeds the allocation base.")
    allocated = svc.compute_allocated_tax(acct, state_code, numerator, denominator)

    sr = new_row(
        "state_return",
        return_id=ret["id"],
        state_code=state_code,
        is_resident_state=is_resident,
        allocation_numerator_cents=numerator,
        allocation_denominator_cents=denominator,
        residency_start_date=payload.get("residency_start_date"),
        residency_end_date=payload.get("residency_end_date"),
        allocated_tax_cents=allocated,
        status="DRAFT",
    )
    db.state_returns[sr["id"]] = sr
    svc.recompute_fees(ret)
    touch(ret)
    return respond_object(dump(sr), status=201)


@bp.get("/tax/returns/<return_id>/state-returns")
@endpoint("Taxpayer", "ClaimsAdjuster")
def list_state_returns(return_id):
    ret, _acct = _own(return_id)
    return paginate(svc.state_returns_of(ret))


@bp.post("/tax/returns/<return_id>/state-returns/<sr_id>/ready")
@endpoint("Taxpayer")
def ready_state_return(return_id, sr_id):
    ret, acct = _own(return_id)
    sr = svc.get_state_return_on_return(ret, sr_id)
    payload = body()
    svc.require_account_active(acct)
    svc.require_return_editable(ret, error_id="ERR_INVALID_STATE")
    if sr["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "State return is not DRAFT.")
    expected_version(payload, ret)
    sr["status"] = "READY"
    touch(sr)
    touch(ret)
    return respond_object(dump(sr))


@bp.post("/tax/returns/<return_id>/state-returns/<sr_id>/remove")
@endpoint("Taxpayer")
def remove_state_return(return_id, sr_id):
    ret, acct = _own(return_id)
    sr = svc.get_state_return_on_return(ret, sr_id)
    payload = body()
    svc.require_account_active(acct)
    svc.require_return_editable(ret, error_id="ERR_INVALID_STATE")
    if sr["status"] not in ("DRAFT", "READY"):
        raise ApiError("ERR_INVALID_STATE", "State return cannot be removed from its current state.")
    expected_version(payload, ret)
    sr["status"] = "REMOVED"
    touch(sr)
    svc.recompute_fees(ret)
    touch(ret)
    return respond_object(dump(sr))
