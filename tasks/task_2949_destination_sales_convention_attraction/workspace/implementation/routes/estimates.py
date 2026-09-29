"""Economic impact estimates (PRD 3.6)."""

from flask import Blueprint

import domain
import impact
import resolve
import serialize
from auth import BOARD_ANALYST, SALES_MANAGER, endpoint
from errors import ApiError
from response import created
from validation import body_json, req_enum, req_ref

bp = Blueprint("estimates", __name__)


@bp.route("/economic-impact-estimates", methods=["POST"])
@endpoint(BOARD_ANALYST, SALES_MANAGER)
def create_estimate():
    body = body_json()
    opportunity_id = req_ref(body, "opportunity_id")
    variant = req_enum(body, "variant", domain.ESTIMATE_VARIANTS)
    opportunity = resolve.opportunity(opportunity_id)

    # a FINAL estimate is meaningless before any pickup has been reported
    if variant == "FINAL" and not impact.final_variant_available(opportunity["id"]):
        raise ApiError("ERR_ESTIMATE_VARIANT_NOT_AVAILABLE",
                       "No pickup has been reported on any commitment of this lead.")

    row = impact.create_estimate(opportunity, variant)
    return created(serialize.estimate(row))
