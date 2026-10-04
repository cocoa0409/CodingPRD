"""Match campaigns: create with half-open-window overlap guard; read."""
import store
from envelope import ok
from errors import bad_request, conflict, not_found
from security import actor, require_roles
from serializers import match_campaign_json
from util_time import parse_dt
from validators import (
    TARGET_TYPES,
    as_enum,
    as_int,
    as_num,
    as_str,
    json_body,
    optional_int,
    require_present,
)


def register(app):
    @app.route("/giving/match-campaigns", methods=["POST"])
    def create_campaign():
        data = json_body()
        sponsor_name = as_str(require_present(data, "sponsor_name"), "sponsor_name")
        match_ratio = as_num(require_present(data, "match_ratio"), "match_ratio")
        if not (match_ratio > 0 and match_ratio <= 2.0):
            raise bad_request("match_ratio must be greater than 0 and at most 2.0")
        budget_cents = as_int(require_present(data, "budget_cents"), "budget_cents")
        if budget_cents < 1:
            raise bad_request("budget_cents must be at least 1")
        target_type = as_enum(require_present(data, "target_type"), "target_type", TARGET_TYPES)
        target_value = as_str(require_present(data, "target_value"), "target_value")
        starts_at = parse_dt(require_present(data, "starts_at"))
        if starts_at is None:
            raise bad_request("starts_at must be an ISO 8601 timestamp")
        ends_at = parse_dt(require_present(data, "ends_at"))
        if ends_at is None:
            raise bad_request("ends_at must be an ISO 8601 timestamp")
        min_donation_cents = optional_int(data, "min_donation_cents", minimum=0)
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        # Half-open overlap: existing.starts < new.ends AND new.starts < existing.ends;
        # windows that merely touch are allowed. Only ACTIVE campaigns block.
        for existing in store.match_campaigns.values():
            if (
                existing["status"] == "ACTIVE"
                and existing["sponsor_name"] == sponsor_name
                and existing["target_type"] == target_type
                and existing["target_value"] == target_value
                and existing["starts_at"] < ends_at
                and starts_at < existing["ends_at"]
            ):
                raise conflict(
                    "ERR_CAMPAIGN_WINDOW_OVERLAP",
                    "Window overlaps an ACTIVE campaign with the same sponsor and target",
                )
        rec = store.base_record()
        rec.update({
            "sponsor_name": sponsor_name,
            "match_ratio": match_ratio,
            "budget_cents": budget_cents,
            "matched_so_far_cents": 0,
            "remaining_budget_cents": budget_cents,
            "min_donation_cents": min_donation_cents if min_donation_cents is not None else 0,
            "target_type": target_type,
            "target_value": target_value,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "status": "ACTIVE",
        })
        store.match_campaigns[rec["id"]] = rec
        return ok(match_campaign_json(rec), 201)

    @app.route("/giving/match-campaigns/<campaign_id>", methods=["GET"])
    def get_campaign(campaign_id):
        _, role = actor()
        require_roles(role, ("PlatformAdmin", "Reviewer", "Donor"))
        campaign = store.match_campaigns.get(campaign_id)
        if campaign is None:
            raise not_found("Match campaign not found")
        return ok(match_campaign_json(campaign), 200)
