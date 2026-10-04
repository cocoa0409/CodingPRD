"""State authorities — PRD §3.7, endpoints 11-14."""

import db
import services
from core import ApiError
from response import ok, page_of
from http_util import bind, pagination, must_get, coerce_int
from routes._common import route
from models import create

PUBLIC = ["state_code", "authority_name", "autonomous_hours_allowed",
          "requires_safety_case_filed", "engagement_window_days"]


def register(app):

    @route(app, "/api/state-authorities", ["POST"], ["RegulatoryLiaison"])
    def create_authority():
        payload = bind("StateAuthority", PUBLIC)
        payload["autonomous_hours_allowed"] = coerce_int(
            payload.get("autonomous_hours_allowed", 24))
        payload["engagement_window_days"] = coerce_int(
            payload.get("engagement_window_days", 30))
        payload["requires_safety_case_filed"] = bool(
            payload.get("requires_safety_case_filed", True))
        row = create("StateAuthority", payload)
        # §3.7: registration zeroes hours_used and clears filing_required_next.
        row["hours_used"] = 0
        row["filing_required_next"] = False
        services.recompute_authority(row)
        services.flush(row)
        return ok(row, 201)

    @route(app, "/api/state-authorities", ["GET"], ["Any"])
    def list_authorities():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("state_authorities")), limit, offset)

    @route(app, "/api/state-authorities/<rid>", ["GET"], ["Any"])
    def get_authority(rid):
        return ok(must_get("StateAuthority", rid))

    @route(app, "/api/state-authorities/<rid>/regulatory-engagements", ["GET"], ["Any"])
    def authority_engagements(rid):
        must_get("StateAuthority", rid)
        limit, offset = pagination()
        return page_of(db.sort_created(db.by("regulatory_engagements", "state_authority_id", rid)),
                       limit, offset)