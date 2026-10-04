"""SeizureCase endpoints (PRD §3.1; scaffold §1.2 SeizureCase state machine)."""

from flask import Blueprint

import clock
import errors
import store
from constants import FORFEITURE_TYPES
from middleware import require_roles, require_business_role
from response import ok_object, ok_list
from serialize import ser_case, ser_asset, ser_distribution
from util import get_body, req_str, req_enum, parse_pagination, sort_and_page

bp = Blueprint("cases", __name__)

# Legal states that cascade to RETURN_PENDING on case dismissal.
_DISMISS_TRANSITION_STATES = (
    "SEIZED",
    "VALUATION_PENDING",
    "VALUED",
    "DISPOSITION_REVIEW",
    "SALE_AUTHORIZED",
)


def _load_case(case_id):
    case = store.CASES.get(case_id)
    if case is None:
        raise errors.not_found("SeizureCase not found: %s" % case_id)
    return case


@bp.route("/custody/cases", methods=["POST"])
def create_case():
    require_roles("CaseAgent")
    # Tier 3: request shape.
    data = get_body()
    case_number = req_str(data, "case_number", nonempty=True)
    judicial_district = req_str(data, "judicial_district")
    forfeiture_type = req_enum(data, "forfeiture_type", FORFEITURE_TYPES)
    lead_agency_code = req_str(data, "lead_agency_code")
    # Tier 8: case_number uniqueness across all cases.
    for existing in store.CASES.values():
        if existing["case_number"] == case_number:
            raise errors.ApiError(
                errors.ERR_DUPLICATE_CASE_NUMBER,
                409,
                "case_number already exists: %s" % case_number,
            )
    case = store.new_entity(
        {
            "case_number": case_number,
            "judicial_district": judicial_district,
            "forfeiture_type": forfeiture_type,
            "lead_agency_code": lead_agency_code,
            "status": "OPEN",
            "forfeited_at": None,
            "gross_proceeds_cents": 0,
            "auction_fees_cents": 0,
            "lien_payments_cents": 0,
            "cost_reimbursements_cents": 0,
            "sharing_pool_gross_basis_cents": 0,
            "sharing_pool_net_basis_cents": 0,
            "equitable_shares_paid_cents": 0,
            "available_proceeds_cents": 0,
        }
    )
    store.CASES[case["id"]] = case
    return ok_object(ser_case(case), status=201)


@bp.route("/custody/cases/<case_id>", methods=["GET"])
def get_case(case_id):
    require_business_role()
    case = _load_case(case_id)
    return ok_object(ser_case(case))


@bp.route("/custody/cases/<case_id>/assets", methods=["GET"])
def list_case_assets(case_id):
    require_business_role()
    case = _load_case(case_id)
    limit, offset = parse_pagination()
    page, total = sort_and_page(store.assets_of_case(case["id"]), limit, offset)
    return ok_list([ser_asset(a) for a in page], total, limit, offset)


@bp.route("/custody/cases/<case_id>/distributions", methods=["GET"])
def list_case_distributions(case_id):
    require_business_role()
    case = _load_case(case_id)
    limit, offset = parse_pagination()
    page, total = sort_and_page(store.distributions_of_case(case["id"]), limit, offset)
    return ok_list([ser_distribution(d) for d in page], total, limit, offset)


@bp.route("/custody/cases/<case_id>/file-forfeiture", methods=["POST"])
def file_forfeiture(case_id):
    require_roles("CaseAgent")
    get_body()  # no input fields; body ignored
    case = _load_case(case_id)
    # Tier 6: OPEN -> FORFEITURE_PENDING only.
    if case["status"] != "OPEN":
        raise errors.invalid_state(
            "Case must be OPEN to file forfeiture (status=%s)" % case["status"]
        )
    case["status"] = "FORFEITURE_PENDING"
    store.touch(case)
    return ok_object(ser_case(case))


@bp.route("/custody/cases/<case_id>/forfeit", methods=["POST"])
def forfeit_case(case_id):
    require_roles("CourtOfficial")
    get_body()
    case = _load_case(case_id)
    # Tier 6: FORFEITURE_PENDING -> FORFEITED only.
    if case["status"] != "FORFEITURE_PENDING":
        raise errors.invalid_state(
            "Case must be FORFEITURE_PENDING to forfeit (status=%s)" % case["status"]
        )
    case["status"] = "FORFEITED"
    case["forfeited_at"] = clock.now()
    store.touch(case)
    return ok_object(ser_case(case))


@bp.route("/custody/cases/<case_id>/dismiss", methods=["POST"])
def dismiss_case(case_id):
    require_roles("CourtOfficial")
    get_body()
    case = _load_case(case_id)
    # Tier 6: from-state must be OPEN or FORFEITURE_PENDING.
    if case["status"] not in ("OPEN", "FORFEITURE_PENDING"):
        raise errors.invalid_state(
            "Case must be OPEN or FORFEITURE_PENDING to dismiss (status=%s)"
            % case["status"]
        )
    assets = store.assets_of_case(case["id"])
    # Tier 6: no asset of this case may already be SOLD.
    if any(a["legal_state"] == "SOLD" for a in assets):
        raise errors.invalid_state(
            "Case cannot be dismissed: an asset has already been SOLD"
        )
    # Cascade link 1: transition in-scope assets to RETURN_PENDING.
    transitioned = [
        a for a in assets if a["legal_state"] in _DISMISS_TRANSITION_STATES
    ]
    for asset in transitioned:
        asset["legal_state"] = "RETURN_PENDING"
        store.touch(asset)
    # Cascade link 2 (caused by link 1): cancel open sale events on them.
    transitioned_ids = {a["id"] for a in transitioned}
    for sale in store.SALES.values():
        if (
            sale["asset_id"] in transitioned_ids
            and sale["status"] in ("OPEN_FOR_BIDS", "CLOSED_PENDING_SETTLEMENT")
        ):
            sale["status"] = "CANCELLED"
            store.touch(sale)
    case["status"] = "DISMISSED"
    store.touch(case)
    return ok_object(ser_case(case))
