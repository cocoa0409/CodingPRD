"""Monthly availability report endpoint (PRD section 3.5)."""

from flask import Blueprint, request

import calc
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import ApiError, ERR_INVALID_REQUEST

bp = Blueprint("availability", __name__)


@bp.get("/api/sites/<site_id>/availability-report")
@require_roles("SiteManager", "BillingOperator")
def availability_report(site_id):
    helpers.get_site(site_id)
    month = request.args.get("month")
    if month is None or v.parse_month(month) is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "month query parameter (YYYY-MM) is required")
    return envelope.ok(calc.availability_report(site_id, month), 200)
