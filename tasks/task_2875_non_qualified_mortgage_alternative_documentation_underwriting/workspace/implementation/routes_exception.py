"""Exception requests and the fork-join authority decision."""
from flask import Blueprint, request

from core import (ApiError, Field, authenticate, dec, ordered, paginate, raw_body,
                  respond_collection, respond_created, respond_object, validate_body)
from store import Tx, db, resolve_fk
import services
from routes_loanfile import gate_segregation

bp = Blueprint("exceptions", __name__)

EXCEPTION_READERS = ("Underwriter", "CreditCommittee", "ChiefCreditOfficer",
                     "PostCloseAuditor")
OPEN_FILE_STATUSES = ("DOC_TYPE_SELECTED", "UNDERWRITING", "SUSPENDED")
LIVE_STATUSES = ("PENDING_REVIEW", "AWAITING_SECOND_SIGNATURE", "APPROVED")

EXCEPTION_FIELDS = [
    Field("loan_file_id", "str", True),
    Field("overlay_id", "str", True),
    Field("justification", "str", True),
    Field("compensating_factors", "str_array"),
]


@bp.post("/exception-requests")
def create_exception():
    actor = authenticate(("Underwriter",))
    raw = raw_body()
    loan_file = resolve_fk(raw, "loan_file_id", "loan_files")
    overlay = resolve_fk(raw, "overlay_id", "overlays")
    values = validate_body(EXCEPTION_FIELDS)
    # priority 10
    if loan_file["status"] not in OPEN_FILE_STATUSES:
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "loan file status %s does not permit an exception request"
                       % loan_file["status"])
    # priority 31
    if overlay["overlay_code"] not in (loan_file.get("overlay_breach_codes") or []):
        raise ApiError("ERR_OVERLAY_NOT_BREACHED",
                       "the overlay is not currently breached by this loan file")
    if not overlay["waivable_flag"]:
        raise ApiError("ERR_OVERLAY_NOT_BREACHED", "the overlay is not waivable")
    for existing in services.exceptions_of(loan_file):
        if existing["overlay_id"] == overlay["id"] and existing["status"] in LIVE_STATUSES:
            raise ApiError("ERR_OVERLAY_NOT_BREACHED",
                           "a live exception request already exists for this overlay")

    pinned = services.metric_value(loan_file, overlay["rule_metric"])
    row = db.insert("exceptions", {
        "loan_file_id": loan_file["id"],
        "overlay_id": overlay["id"],
        "justification": values["justification"],
        "compensating_factors": values.get("compensating_factors", []),
        "requested_by_user_id": actor.user_id,
        "pinned_metric_value": pinned,
        "pinned_overlay_version": int(overlay["version"]),
        "required_authority_tier": services.computed_authority_tier(overlay),
        "status": "PENDING_REVIEW",
        "first_signoff_user_id": None,
        "second_signoff_user_id": None,
        "decision_reason": None,
    })
    return respond_created(row)


@bp.get("/exception-requests/<ident>")
def read_exception(ident):
    authenticate(EXCEPTION_READERS)
    return respond_object(db.fetch("exceptions", ident))


@bp.get("/exception-requests")
def list_exceptions():
    authenticate(EXCEPTION_READERS)
    rows = db.rows("exceptions")
    for key in ("loan_file_id", "overlay_id", "status"):
        wanted = request.args.get(key)
        if wanted:
            rows = [r for r in rows if r[key] == wanted]
    page, limit, offset, total = paginate(ordered(rows))
    return respond_collection(page, limit, offset, total)


def _authority_ok(role, tier, status):
    """validations priority 35."""
    if status == "AWAITING_SECOND_SIGNATURE":
        return role == "ChiefCreditOfficer"
    if tier == 1:
        return role in ("CreditCommittee", "ChiefCreditOfficer")
    return role == "CreditCommittee"


@bp.post("/exception-requests/<ident>/decision")
def decide_exception(ident):
    actor = authenticate(("CreditCommittee", "ChiefCreditOfficer"))
    excepted = db.fetch("exceptions", ident)
    values = validate_body([
        Field("decision", "enum", True, ("APPROVE", "DENY")),
        Field("decision_reason", "str"),
    ])
    decision = values["decision"]
    tier = int(excepted["required_authority_tier"])
    status = excepted["status"]
    # priority 14
    if status not in ("PENDING_REVIEW", "AWAITING_SECOND_SIGNATURE"):
        raise ApiError("ERR_EXCEPTION_STATE_INVALID",
                       "exception status %s accepts no further decision" % status)
    loan_file = db.find("loan_files", excepted["loan_file_id"])
    overlay = db.find("overlays", excepted["overlay_id"])
    if decision == "APPROVE":
        if loan_file["status"] not in ("UNDERWRITING", "SUSPENDED"):
            raise ApiError("ERR_EXCEPTION_STATE_INVALID",
                           "the loan file is not under active underwriting")
        live = services.metric_value(loan_file, overlay["rule_metric"])
        pinned = excepted["pinned_metric_value"]
        if live is None or pinned is None or dec(live) != dec(pinned):
            raise ApiError("ERR_EXCEPTION_STATE_INVALID",
                           "the pinned metric value no longer matches the live value")
    # priority 23 clause (b)
    if actor.user_id == excepted["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the requester may not decide their own exception")
    if (status == "AWAITING_SECOND_SIGNATURE"
            and actor.user_id == excepted["first_signoff_user_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the second signature must come from a different operator")
    # priority 35
    if not _authority_ok(actor.role, tier, status):
        raise ApiError("ERR_EXCEPTION_AUTHORITY_INSUFFICIENT",
                       "%s does not hold the authority this exception requires"
                       % actor.role)

    tx = Tx()
    tx.watch(excepted)
    tx.watch(loan_file)
    if "decision_reason" in values:
        excepted["decision_reason"] = values["decision_reason"]
    if decision == "DENY":
        excepted["status"] = "DENIED"
        services.sweep_and_cascade(loan_file, tx, force_suspend=True)
    elif status == "PENDING_REVIEW":
        excepted["first_signoff_user_id"] = actor.user_id
        if tier == 1:
            excepted["status"] = "APPROVED"
            services.sweep_and_cascade(loan_file, tx)
        else:
            excepted["status"] = "AWAITING_SECOND_SIGNATURE"
            services.recompute_eligibility(loan_file)
    else:
        excepted["second_signoff_user_id"] = actor.user_id
        excepted["status"] = "APPROVED"
        loan_file["investor_notification_required"] = True
        services.sweep_and_cascade(loan_file, tx)
    tx.commit()
    return respond_object(excepted)
