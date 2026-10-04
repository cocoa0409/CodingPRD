"""Risk assessments (PRD 3.3): SCREENING/REFINED, computed quotients."""
from flask import Blueprint

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store
from envelope import ok
from errors import err
from services.calcs import compute_risk
from validate import as_enum, as_num, as_str, parse_body, reject_unknown

bp = Blueprint("risk_assessments", __name__)


@bp.post("/risk-assessments")
def create_risk_assessment():
    caller = require_auth()
    require_role(caller, [constants.ROLE_RISK_ASSESSOR])
    data = parse_body()
    reject_unknown(data, ["application_id", "tier", "pct_crop_treated"])
    application_id = as_str(data, "application_id", required=True)
    tier = as_enum(data, "tier", constants.RISK_TIERS, required=True)
    pct = as_num(data, "pct_crop_treated", required=False, minimum=0, exclusive_minimum=True)
    # pct_crop_treated: required iff REFINED, forbidden on SCREENING; at most 1.
    if tier == "REFINED":
        if pct is None:
            err("ERR_INVALID_REQUEST", "pct_crop_treated is required for REFINED assessments.")
        if pct > 1:
            err("ERR_INVALID_REQUEST", "pct_crop_treated must be at most 1.")
    else:
        if pct is not None:
            err("ERR_INVALID_REQUEST", "pct_crop_treated is forbidden for SCREENING assessments.")

    application = store["applications"].get(application_id)
    if application is None:
        err("ERR_APPLICATION_NOT_FOUND", "Application %s does not exist." % application_id)
    if application["status"] not in ("IN_REVIEW", "DATA_DEFICIENCY"):
        err(
            "ERR_APPLICATION_NOT_IN_REVIEW",
            "Risk assessments require the application IN_REVIEW or DATA_DEFICIENCY.",
        )

    product = store["products"][application["product_id"]]
    results = compute_risk(product, application, tier, pct)

    seq = (
        max(
            (a["assessment_seq"] for a in store["risk_assessments"].values()
             if a["application_id"] == application_id),
            default=0,
        )
        + 1
    )

    row = new_row()
    row.update(
        {
            "application_id": application_id,
            "assessor_ref": caller["user_id"],
            "tier": tier,
            "pct_crop_treated": pct,
            "assessment_seq": seq,
            "assessed_at": clock.now(),
        }
    )
    row.update(results)
    store["risk_assessments"][row["id"]] = row
    return ok(row, status=201)
