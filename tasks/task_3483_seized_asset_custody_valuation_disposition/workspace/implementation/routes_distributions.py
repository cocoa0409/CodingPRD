"""Distribution endpoints (PRD §3.7): equitable sharing with the SoD-guarded
approve/rescind compensating pair that conserves the case's proceeds pool.
"""

from flask import Blueprint

import errors
import store
from constants import USAGE_RESTRICTIONS, EQUITABLE_SHARE_MIN_CENTS
from middleware import require_roles
from response import ok_object
from serialize import ser_distribution
from util import get_body, req_str, req_enum, req_int

bp = Blueprint("distributions", __name__)


def _load_distribution(distribution_id):
    distribution = store.DISTRIBUTIONS.get(distribution_id)
    if distribution is None:
        raise errors.not_found("Distribution not found: %s" % distribution_id)
    return distribution


@bp.route("/custody/distributions", methods=["POST"])
def create_distribution():
    user_id, _ = require_roles("FundAdministrator")
    # Tier 3: request shape; manually created distributions are always
    # EQUITABLE_SHARE and must carry a non-null usage_restriction.
    data = get_body()
    seizure_case_id = req_str(data, "seizure_case_id")
    payee_ref = req_str(data, "payee_ref")
    amount_cents = req_int(data, "amount_cents")
    usage_restriction = data.get("usage_restriction")
    if usage_restriction is None:
        raise errors.invalid_request(
            "EQUITABLE_SHARE distributions require a usage_restriction"
        )
    if not isinstance(usage_restriction, str) or usage_restriction not in USAGE_RESTRICTIONS:
        raise errors.invalid_request(
            "usage_restriction must be one of %s" % ", ".join(USAGE_RESTRICTIONS)
        )
    # Tier 4: case must exist.
    case = store.CASES.get(seizure_case_id)
    if case is None:
        raise errors.not_found("SeizureCase not found: %s" % seizure_case_id)
    # Tier 6: the case must be FORFEITED.
    if case["status"] != "FORFEITED":
        raise errors.case_not_forfeited(
            "Distributions may be created only against a FORFEITED case"
        )
    # Tier 9: statutory floor, then pool sufficiency (creation-time check).
    if amount_cents < EQUITABLE_SHARE_MIN_CENTS:
        raise errors.ApiError(
            errors.ERR_SHARE_BELOW_MINIMUM,
            422,
            "EQUITABLE_SHARE amount_cents is below the 10000-cent minimum",
        )
    if amount_cents > case["available_proceeds_cents"]:
        raise errors.ApiError(
            errors.ERR_INSUFFICIENT_PROCEEDS,
            422,
            "amount_cents exceeds the case's available_proceeds_cents",
        )
    distribution = store.new_entity(
        {
            "seizure_case_id": case["id"],
            "distribution_kind": "EQUITABLE_SHARE",
            "payee_ref": payee_ref,
            "amount_cents": amount_cents,
            "usage_restriction": usage_restriction,
            "status": "PENDING",
            "created_by_user_id": user_id,
            "approved_by_user_id": None,
        }
    )
    store.DISTRIBUTIONS[distribution["id"]] = distribution
    return ok_object(ser_distribution(distribution), status=201)


@bp.route("/custody/distributions/<distribution_id>/approve", methods=["POST"])
def approve_distribution(distribution_id):
    user_id, _ = require_roles("FundAdministrator")
    get_body()
    distribution = _load_distribution(distribution_id)
    # Tier 6: only a PENDING distribution can be approved (fires before SoD).
    if distribution["status"] != "PENDING":
        raise errors.invalid_state(
            "Only a PENDING distribution can be approved (status=%s)"
            % distribution["status"]
        )
    # Tier 7: segregation of duties — approver must differ from creator.
    if user_id == distribution["created_by_user_id"]:
        raise errors.sod_violation(
            "The approving FundAdministrator must differ from the creator"
        )
    # Tier 9: pool sufficiency re-checked at approval time.
    case = store.CASES.get(distribution["seizure_case_id"])
    if case is None or distribution["amount_cents"] > case["available_proceeds_cents"]:
        raise errors.ApiError(
            errors.ERR_INSUFFICIENT_PROCEEDS,
            422,
            "amount_cents exceeds the case's current available_proceeds_cents",
        )
    distribution["status"] = "PAID"
    distribution["approved_by_user_id"] = user_id
    store.touch(distribution)
    # Debit the pool: approval is where money actually moves.
    case["equitable_shares_paid_cents"] += distribution["amount_cents"]
    store.rederive_available(case)
    store.touch(case)
    return ok_object(ser_distribution(distribution))


@bp.route("/custody/distributions/<distribution_id>/rescind", methods=["POST"])
def rescind_distribution(distribution_id):
    require_roles("FundAdministrator")
    get_body()
    distribution = _load_distribution(distribution_id)
    # Tier 6: rescind from PENDING or PAID.
    if distribution["status"] not in ("PENDING", "PAID"):
        raise errors.invalid_state(
            "Only a PENDING or PAID distribution can be rescinded (status=%s)"
            % distribution["status"]
        )
    was_paid_equitable = (
        distribution["status"] == "PAID"
        and distribution["distribution_kind"] == "EQUITABLE_SHARE"
    )
    distribution["status"] = "VOIDED"
    store.touch(distribution)
    if was_paid_equitable:
        # Compensating pair: credit the pool back.
        case = store.CASES.get(distribution["seizure_case_id"])
        if case is not None:
            case["equitable_shares_paid_cents"] -= distribution["amount_cents"]
            store.rederive_available(case)
            store.touch(case)
    return ok_object(ser_distribution(distribution))
