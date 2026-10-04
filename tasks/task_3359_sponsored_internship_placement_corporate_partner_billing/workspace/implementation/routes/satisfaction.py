"""Partner satisfaction records (PRD 3.6)."""

from flask import Blueprint

import db
import middleware
import response
import timeutil
import validators
from routes.common import must_get_body, require_owner
from services import billing_svc, credit_svc

RATING_MIN = 0.0
RATING_MAX = 5.0

bp = Blueprint("satisfaction", __name__)


@bp.post("/satisfaction-records")
def create_satisfaction_record():
    actor = middleware.require(("Partner",))
    data = validators.body()

    raw_placement_id = data.get("placement_id")
    if not isinstance(raw_placement_id, str) or not raw_placement_id.strip():
        validators.fail("field 'placement_id' is required")
    placement = must_get_body("placements", raw_placement_id.strip(), "placement_id")

    supervisor_rating = validators.as_number(
        data, "supervisor_rating", minimum=RATING_MIN, maximum=RATING_MAX
    )
    project_rating = validators.as_number(
        data, "project_rating", minimum=RATING_MIN, maximum=RATING_MAX
    )
    communication_rating = validators.as_number(
        data, "communication_rating", minimum=RATING_MIN, maximum=RATING_MAX
    )

    agreement = db.get("agreements", placement["agreement_id"])
    partner = billing_svc.partner_of_agreement(agreement)
    require_owner(actor, partner["id"] if partner else None, "placement %s" % placement["id"])

    composite = credit_svc.composite_score(
        supervisor_rating, project_rating, communication_rating
    )

    row = db.make_row(
        placement_id=placement["id"],
        supervisor_rating=supervisor_rating,
        project_rating=project_rating,
        communication_rating=communication_rating,
        composite_score=composite,
        submitted_at=timeutil.now(),
        converted_to_hire=False,
    )
    db.insert("satisfaction_records", row)

    placement["satisfaction_score"] = composite
    db.touch(placement)

    if partner is not None:
        partner["placement_quality_score"] = composite
        db.touch(partner)

    return response.success(row, status=201)
