"""Manufacturer warranty claims and the cost re-point (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint

from calc import INVERTER_WARRANTY_YEARS, MAX_CLAIM_REVISIONS, MODULE_WARRANTY_YEARS
from core import (
    ApiError, add_years, clock, fmt_date, parse_date, sorted_rows, stamp_new, store,
    touch,
)
from guards import lookup
from serialize import warranty_claim_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("warranty_routes", __name__)

COMPONENT_TYPES = ("MODULE", "INVERTER")
CLAIM_STATUSES = ("DRAFT", "SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED")
CLAIMABLE_CAUSES = {"MODULE": "MODULE_DEFECT", "INVERTER": "INVERTER_FAULT"}

MANUFACTURER_CODE = lambda v: v.isalnum() and v.upper() == v

CLAIM_SPECS = [
    {"name": "truck_roll_id", "kind": "id", "required": True},
    {"name": "component_type", "kind": "enum", "required": True,
     "values": COMPONENT_TYPES},
    {"name": "manufacturer_code", "kind": "str", "required": True, "minlen": 2,
     "maxlen": 24, "pattern": MANUFACTURER_CODE},
    {"name": "serial_number", "kind": "str", "required": True, "minlen": 1,
     "maxlen": 40, "nonblank": True},
    {"name": "component_install_date", "kind": "date", "required": True},
    {"name": "claim_amount_cents", "kind": "int", "required": True, "min": 1},
]


@bp.post("/servicing/warranty-claims")
def create_claim():
    authenticate(("FieldOpsCoordinator",))
    body = validate_body(CLAIM_SPECS)
    roll = lookup("truck_rolls", body["truck_roll_id"])
    # rung 12 — four independent claimability conditions, one code
    reason = None
    if roll["status"] != "COMPLETED":
        reason = "the truck roll is not COMPLETED"
    elif roll["root_cause"] not in ("INVERTER_FAULT", "MODULE_DEFECT"):
        reason = "the diagnosed root_cause is not manufacturer-owned"
    elif CLAIMABLE_CAUSES[body["component_type"]] != roll["root_cause"]:
        reason = "component_type does not agree with the diagnosed root_cause"
    else:
        for existing in store.warranty_claims.values():
            if (existing["truck_roll_id"] == roll["id"]
                    and existing["status"] != "DENIED"):
                reason = "a claim that is not DENIED already exists on that roll"
                break
    if reason is not None:
        raise ApiError("ERR_TRUCK_ROLL_NOT_CLAIMABLE",
                       "This truck roll is not claimable: %s." % reason)

    install = parse_date(body["component_install_date"])
    term = (MODULE_WARRANTY_YEARS if body["component_type"] == "MODULE"
            else INVERTER_WARRANTY_YEARS)
    claim = {
        "truck_roll_id": roll["id"],
        "agreement_id": roll["agreement_id"],
        "component_type": body["component_type"],
        "manufacturer_code": body["manufacturer_code"],
        "serial_number": body["serial_number"],
        "component_install_date": fmt_date(install),
        "claim_amount_cents": body["claim_amount_cents"],
        "warranty_term_years": term,
        "warranty_expires_on": fmt_date(add_years(install, term) - timedelta(days=1)),
        "approved_amount_cents": None,
        "info_request_note": None,
        "revision_count": 0,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "status": "DRAFT",
    }
    stamp_new(claim)
    store.warranty_claims[claim["id"]] = claim
    return created(warranty_claim_view(claim))


@bp.get("/servicing/warranty-claims/<warranty_claim_id>")
def get_claim(warranty_claim_id):
    authenticate(("FieldOpsCoordinator", "ServicingAgent", "PortfolioAdmin"))
    return ok(warranty_claim_view(lookup("warranty_claims", warranty_claim_id)))


@bp.get("/servicing/warranty-claims")
def list_claims():
    authenticate(("FieldOpsCoordinator", "ServicingAgent", "PortfolioAdmin"))
    limit, offset = pagination()
    flt = filters([
        ("truck_roll_id", "str", None),
        ("agreement_id", "str", None),
        ("component_type", "enum", COMPONENT_TYPES),
        ("manufacturer_code", "str", None),
        ("status", "enum", CLAIM_STATUSES),
    ])
    rows = apply_filters(sorted_rows(list(store.warranty_claims.values())), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([warranty_claim_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/warranty-claims/<warranty_claim_id>/submit")
def submit_claim(warranty_claim_id):
    user_id, role = authenticate(("FieldOpsCoordinator",))
    validate_body([])
    claim = lookup("warranty_claims", warranty_claim_id)
    if claim["status"] not in ("DRAFT", "INFO_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a DRAFT or INFO_REQUESTED claim may be submitted.")
    # rung 11
    if clock.today() > parse_date(claim["warranty_expires_on"]):
        raise ApiError("ERR_WARRANTY_WINDOW_EXPIRED",
                       "The component's warranty window closed on %s."
                       % claim["warranty_expires_on"])
    # rung 13
    if (claim["status"] == "INFO_REQUESTED"
            and claim["revision_count"] >= MAX_CLAIM_REVISIONS):
        raise ApiError("ERR_CLAIM_REVISION_LIMIT",
                       "This claim has already been revised %d times."
                       % MAX_CLAIM_REVISIONS)
    if claim["status"] == "INFO_REQUESTED":
        claim["revision_count"] += 1
        claim["info_request_note"] = None
    claim["submitted_by_user_id"] = user_id
    claim["status"] = "SUBMITTED"
    touch(claim)
    return ok(warranty_claim_view(claim))


@bp.post("/servicing/warranty-claims/<warranty_claim_id>/request-info")
def request_info(warranty_claim_id):
    authenticate(("FieldOpsCoordinator", "PortfolioAdmin"))
    body = validate_body([{"name": "info_request_note", "kind": "str",
                           "required": True, "minlen": 1, "maxlen": 500,
                           "nonblank": True}])
    claim = lookup("warranty_claims", warranty_claim_id)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED claim may have information requested.")
    claim["info_request_note"] = body["info_request_note"]
    claim["status"] = "INFO_REQUESTED"
    touch(claim)
    return ok(warranty_claim_view(claim))


def repoint_roll(claim, billable_to):
    """PRD §3.6: the chain re-points at most once, and only out of
    PENDING_MANUFACTURER. labor_cost_cents is never re-priced."""
    roll = store.truck_rolls.get(claim["truck_roll_id"])
    if roll is not None and roll["billable_to"] == "PENDING_MANUFACTURER":
        roll["billable_to"] = billable_to
        touch(roll)


@bp.post("/servicing/warranty-claims/<warranty_claim_id>/approve")
def approve_claim(warranty_claim_id):
    user_id, role = authenticate(("FieldOpsCoordinator", "PortfolioAdmin"))
    body = validate_body([{"name": "approved_amount_cents", "kind": "int",
                           "required": True, "min": 0}])
    claim = lookup("warranty_claims", warranty_claim_id)
    # rung 7
    if (claim["submitted_by_user_id"] is not None
            and claim["submitted_by_user_id"] == user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The submitting user may not decide the same claim.")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED claim may be approved.")
    # rung 13
    if body["approved_amount_cents"] > claim["claim_amount_cents"]:
        raise ApiError("ERR_APPROVED_AMOUNT_EXCEEDS_CLAIM",
                       "approved_amount_cents may not exceed claim_amount_cents.")
    claim["approved_amount_cents"] = body["approved_amount_cents"]
    claim["decided_by_user_id"] = user_id
    claim["status"] = "APPROVED"
    touch(claim)
    repoint_roll(claim, "WARRANTY")
    return ok(warranty_claim_view(claim))


@bp.post("/servicing/warranty-claims/<warranty_claim_id>/deny")
def deny_claim(warranty_claim_id):
    user_id, role = authenticate(("FieldOpsCoordinator", "PortfolioAdmin"))
    validate_body([])
    claim = lookup("warranty_claims", warranty_claim_id)
    # rung 7
    if (claim["submitted_by_user_id"] is not None
            and claim["submitted_by_user_id"] == user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The submitting user may not decide the same claim.")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED claim may be denied.")
    claim["approved_amount_cents"] = 0
    claim["decided_by_user_id"] = user_id
    claim["status"] = "DENIED"
    touch(claim)
    repoint_roll(claim, "SUNRUN_OM")
    return ok(warranty_claim_view(claim))
