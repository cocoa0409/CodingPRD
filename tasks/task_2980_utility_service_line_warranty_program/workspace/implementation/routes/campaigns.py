"""Marketing campaigns: drafting, brand review and the mail drop."""

from flask import Blueprint

import config
import derive
import serializers
import timeutil
from errors import ApiError
from response import object_response, paginate
from routes.partners import lookup_partner
from routes.products import lookup_product
from store import create_record, ordered, store, touch
from validation import Field, current_user_id, filter_enum, filter_value, parse_body, require_path_uuid, require_role

bp = Blueprint("campaigns", __name__)

READ_ROLES = (
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_MARKETING_OPS,
    config.ROLE_PARTNER_BRAND_REVIEWER,
    config.ROLE_CUSTOMER_SERVICE_REP,
    config.ROLE_REGULATORY_AFFAIRS,
    config.ROLE_OPERATIONS_ADMIN,
)

CREATE_SPEC = {
    "partner_id": Field("uuid", required=True),
    "product_id": Field("uuid", required=True),
    "name": Field("string", required=True, min_len=1, max_len=120),
    "piece_type": Field("enum", required=True, enum=config.PIECE_TYPES),
    "drop_date": Field("date", required=True),
    "requested_quantity": Field("integer", required=True, minimum=0, maximum=1000000),
}

SUBMISSION_SPEC = {"note": Field("string", max_len=1000)}

DECISION_SPEC = {
    "decision": Field("enum", required=True, enum=config.CAMPAIGN_DECISIONS),
    "decision_note": Field("string", required=True, min_len=1, max_len=1000),
    "approved_quantity": Field("integer", minimum=0, maximum=1000000),
}

MAIL_DROP_SPEC = {}

# Suppression precedence for a drop, highest precedence first.
DROP_PRECEDENCE = [
    "DNM_REQUEST",
    "BAD_ADDRESS",
    "REGULATOR_COMPLAINT_OPEN",
    "ACTIVE_ENROLLMENT",
    "OPEN_APPEAL",
    "CONTACT_FREQUENCY_CAP",
    "OWNERSHIP_INELIGIBLE",
]


def lookup_campaign(campaign_id):
    campaign = store.campaigns.get(campaign_id)
    if campaign is None:
        raise ApiError("ERR_CAMPAIGN_NOT_FOUND", "No campaign with id %s" % campaign_id)
    return campaign


@bp.post("/campaigns")
def create_campaign():
    current_user_id()
    require_role(config.ROLE_MARKETING_OPS)
    body = parse_body(CREATE_SPEC)
    partner = lookup_partner(body["partner_id"])
    product = lookup_product(body["product_id"])
    if product["partner_id"] != partner["id"]:
        raise ApiError("ERR_INVALID_REQUEST", "The product does not belong to the named partner")
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_NOT_ACTIVE", "The sponsoring partner is not ACTIVE")
    if product["status"] == "WITHDRAWN":
        raise ApiError("ERR_PRODUCT_WITHDRAWN", "The product has been withdrawn")
    record = create_record(
        store.campaigns,
        {
            "partner_id": partner["id"],
            "product_id": product["id"],
            "name": body["name"],
            "piece_type": body["piece_type"],
            "drop_date": timeutil.render_date(body["drop_date"]),
            "requested_quantity": body["requested_quantity"],
            "approved_quantity": None,
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "decision_by_user_id": None,
            "decision_note": None,
            "decided_at": None,
            "revision_count": 0,
            "mailed_count": 0,
            "suppressed_count": 0,
            "mail_dropped_at": None,
        },
    )
    return object_response(serializers.campaign(record), 201)


@bp.get("/campaigns")
def list_campaigns():
    current_user_id()
    require_role(*READ_ROLES)
    partner_id = filter_value("partner_id")
    product_id = filter_value("product_id")
    status = filter_enum("status", config.CAMPAIGN_STATUSES)

    def matches(campaign):
        if partner_id is not None and campaign["partner_id"] != partner_id:
            return False
        if product_id is not None and campaign["product_id"] != product_id:
            return False
        if status is not None and campaign["status"] != status:
            return False
        return True

    return paginate(ordered(store.campaigns, matches), serializers.campaign)


@bp.get("/campaigns/<campaign_id>")
def get_campaign(campaign_id):
    current_user_id()
    require_role(*READ_ROLES)
    require_path_uuid(campaign_id)
    return object_response(serializers.campaign(lookup_campaign(campaign_id)))


@bp.post("/campaigns/<campaign_id>/submission")
def submit_campaign(campaign_id):
    user_id = current_user_id()
    require_role(config.ROLE_MARKETING_OPS)
    require_path_uuid(campaign_id)
    body = parse_body(SUBMISSION_SPEC)
    campaign = lookup_campaign(campaign_id)

    if campaign["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE", "Only a DRAFT or REJECTED campaign may be submitted")
    resubmission = campaign["status"] == "REJECTED"
    if resubmission and campaign["revision_count"] >= config.CAMPAIGN_REVISION_LIMIT:
        raise ApiError("ERR_REVISION_LIMIT_REACHED", "The campaign has already been revised twice")

    partner = lookup_partner(campaign["partner_id"])
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_NOT_ACTIVE", "The sponsoring partner is not ACTIVE")
    _enforce_drop_window(campaign, partner)

    campaign["status"] = "PARTNER_REVIEW"
    campaign["submitted_by_user_id"] = user_id
    if body["note"] is not None:
        campaign["_submission_note"] = body["note"]
    if resubmission:
        campaign["revision_count"] += 1
    touch(campaign)
    return object_response(serializers.campaign(campaign))


def _enforce_drop_window(campaign, partner):
    """No two of a partner's live drops may sit closer than min_days_between_drops."""
    candidate = timeutil.parse_date(campaign["drop_date"])
    minimum = partner["min_days_between_drops"]
    for sibling in ordered(store.campaigns, lambda c: c["partner_id"] == partner["id"]):
        if sibling["id"] == campaign["id"]:
            continue
        if sibling["status"] not in ("PARTNER_REVIEW", "APPROVED", "MAILED"):
            continue
        gap = abs(timeutil.whole_days_between(timeutil.parse_date(sibling["drop_date"]), candidate))
        if gap < minimum:
            raise ApiError(
                "ERR_DROP_WINDOW_CONFLICT",
                "The drop date is within %d days of another live drop" % minimum,
            )


@bp.post("/campaigns/<campaign_id>/decision")
def decide_campaign(campaign_id):
    user_id = current_user_id()
    require_role(config.ROLE_PARTNER_BRAND_REVIEWER)
    require_path_uuid(campaign_id)
    body = parse_body(DECISION_SPEC)
    campaign = lookup_campaign(campaign_id)

    if user_id != campaign["partner_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the sponsoring partner's reviewer may decide this campaign")
    if campaign["submitted_by_user_id"] is not None and user_id == campaign["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The submitting operator may not decide the campaign")
    if campaign["status"] != "PARTNER_REVIEW":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE", "Only a campaign in PARTNER_REVIEW may be decided")

    if body["decision"] == "APPROVE":
        approved = body["approved_quantity"]
        if approved is None:
            approved = campaign["requested_quantity"]
        elif approved > campaign["requested_quantity"]:
            raise ApiError("ERR_INVALID_REQUEST", "approved_quantity may not exceed requested_quantity")
        campaign["status"] = "APPROVED"
        campaign["approved_quantity"] = approved
    else:
        campaign["status"] = "REJECTED"

    campaign["decision_by_user_id"] = user_id
    campaign["decision_note"] = body["decision_note"]
    campaign["decided_at"] = store.now_iso()
    touch(campaign)
    return object_response(serializers.campaign(campaign))


def _drop_suppression_reason(premises, campaign, product, partner):
    """The single winning reason for one address, or None when it survives."""
    if premises.get("do_not_mail"):
        return "DNM_REQUEST"
    if premises.get("address_status") == "BAD":
        return "BAD_ADDRESS"
    if premises.get("regulator_hold"):
        return "REGULATOR_COMPLAINT_OPEN"
    for enrollment in derive.enrollments_of_premises(premises["id"]):
        if enrollment["product_id"] == campaign["product_id"] and enrollment["coverage_status"] in config.LIVE_COVERAGE_STATUSES:
            return "ACTIVE_ENROLLMENT"
    if derive.premises_has_retention_hold(premises):
        return "OPEN_APPEAL"
    if derive.premises_mail_count_current_year(premises) >= partner["max_mailings_per_year"]:
        return "CONTACT_FREQUENCY_CAP"
    if product["required_owned_segment"] not in premises["owned_segments"]:
        return "OWNERSHIP_INELIGIBLE"
    return None


@bp.post("/campaigns/<campaign_id>/mail-drop")
def drop_campaign(campaign_id):
    current_user_id()
    require_role(config.ROLE_MARKETING_OPS)
    require_path_uuid(campaign_id)
    parse_body(MAIL_DROP_SPEC)
    campaign = lookup_campaign(campaign_id)

    if campaign["status"] != "APPROVED" or campaign["approved_quantity"] is None:
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE", "Only an APPROVED campaign with an approved quantity may drop")
    partner = lookup_partner(campaign["partner_id"])
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_NOT_ACTIVE", "The sponsoring partner is not ACTIVE")
    drop_date = timeutil.parse_date(campaign["drop_date"])
    if drop_date > store.today():
        raise ApiError("ERR_DROP_DATE_IN_FUTURE", "The drop date has not arrived yet")

    product = store.products.get(campaign["product_id"])
    addresses = ordered(store.premises, lambda p: p["partner_id"] == partner["id"])

    screened = []
    for premises in addresses:
        screened.append((premises, _drop_suppression_reason(premises, campaign, product, partner)))

    mailed_ids = []
    suppressed_by_reason = {}
    capacity = campaign["approved_quantity"]
    for premises, reason in screened:
        if reason is None:
            if len(mailed_ids) < capacity:
                premises["last_mailed_campaign_id"] = campaign["id"]
                premises["last_mail_decision"] = "MAILED"
                premises["last_mail_suppression_reason"] = None
                premises.setdefault("_mail_history", []).append(
                    {"campaign_id": campaign["id"], "drop_date": drop_date}
                )
                touch(premises)
                mailed_ids.append(premises["id"])
                continue
            reason = "QUANTITY_CAP"
        premises["last_mail_decision"] = "SUPPRESSED"
        premises["last_mail_suppression_reason"] = reason
        touch(premises)
        suppressed_by_reason[reason] = suppressed_by_reason.get(reason, 0) + 1

    campaign["status"] = "MAILED"
    campaign["mailed_count"] = len(mailed_ids)
    campaign["suppressed_count"] = sum(suppressed_by_reason.values())
    campaign["mail_dropped_at"] = store.now_iso()
    touch(campaign)

    return object_response(
        {
            "campaign_id": campaign["id"],
            "status": campaign["status"],
            "mailed_count": campaign["mailed_count"],
            "suppressed_count": campaign["suppressed_count"],
            "suppressed_by_reason": suppressed_by_reason,
            "mailed_premises_ids": mailed_ids,
        }
    )
