"""Digital giving and attribution (PRD 3.5)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

CHANNELS = ("QR", "SMS", "TERMINAL", "ONLINE")
ATTRIBUTION_STATUSES = ("RECEIVED", "UNATTRIBUTED", "ATTRIBUTED", "REVERSED")


def refresh_totals(gift):
    location = store.find("kettle_locations", gift.get("kettle_location_id"))
    if location is not None:
        location["location_total_cents"] = calcs.location_total_cents(location["id"])
        store.touch(location)
        campaign = store.find("campaigns", location.get("campaign_id"))
        if campaign is not None:
            campaign["total_raised_cents"] = calcs.campaign_total_raised(campaign["id"])
            store.touch(campaign)
            return
    campaign = store.find("campaigns", gift.get("campaign_id"))
    if campaign is not None:
        campaign["total_raised_cents"] = calcs.campaign_total_raised(campaign["id"])
        store.touch(campaign)


def gift_target_error(location, campaign_id):
    if location.get("campaign_id") != campaign_id:
        raise ApiError("ERR_REFERENCE_SCOPE_MISMATCH", "The kettle location belongs to a different campaign.")
    site = store.find("host_sites", location.get("host_site_id"))
    if site is None or site.get("permission_status") != "APPROVED":
        raise ApiError("ERR_HOST_SITE_NOT_PERMITTED")
    if location.get("status") != "ACTIVE":
        raise ApiError("ERR_LOCATION_NOT_ACTIVE")


@bp.route("/digital-givings", methods=["POST"])
def create_digital_giving():
    require_role(["DigitalGivingProcessor", "FinanceOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("campaign_id", validate.STRING, required=True),
            validate.f("unit_id", validate.STRING, required=True),
            validate.f("amount_cents", validate.INTEGER, required=True),
            validate.f("channel", validate.ENUM, required=True, enum=CHANNELS),
            validate.f("occurred_at", validate.DATETIME, required=True),
            validate.f("external_ref", validate.STRING, required=True),
            validate.f("kettle_location_id", validate.STRING),
        ]
    )
    campaign = validate.reference("campaigns", values["campaign_id"], "campaign")
    validate.reference("units", values["unit_id"], "unit")
    location_id = values.get("kettle_location_id")
    if location_id:
        location = validate.reference("kettle_locations", location_id, "kettle location")
        if location.get("campaign_id") != values["campaign_id"]:
            validate.scope_mismatch("The kettle location belongs to a different campaign.")

    if campaign.get("status") != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE")

    for existing in store.rows("digital_givings"):
        if existing.get("campaign_id") == values["campaign_id"] and existing.get("external_ref") == values[
            "external_ref"
        ]:
            raise ApiError("ERR_DUPLICATE_EXTERNAL_REF")

    occurred_at = values["occurred_at"]
    starts_on = clock.parse(campaign.get("starts_on"))
    ends_on = clock.parse(campaign.get("ends_on"))
    if starts_on is None or ends_on is None or not (starts_on <= occurred_at <= ends_on):
        raise ApiError("ERR_GIVING_OUTSIDE_CAMPAIGN_WINDOW")

    amount = int(values["amount_cents"])
    if amount <= 0 or amount > calcs.MAX_DIGITAL_GIFT_CENTS:
        raise ApiError("ERR_INVALID_GIFT_AMOUNT")

    gift = {
        "kettle_location_id": location_id or None,
        "campaign_id": values["campaign_id"],
        "unit_id": values["unit_id"],
        "amount_cents": amount,
        "channel": values["channel"],
        "occurred_at": clock.fmt(occurred_at),
        "external_ref": values["external_ref"],
        "attribution_status": "RECEIVED",
        "attributed_cents": 0,
        "reversed_reason": None,
    }
    store.insert("digital_givings", gift)
    return success(store.public(gift)), 201


@bp.route("/digital-givings", methods=["GET"])
def list_digital_givings():
    require_role(
        [
            "PlatformAdmin",
            "DigitalGivingProcessor",
            "FinanceOfficer",
            "KettleCoordinator",
            "TerritorialCommander",
            "DivisionalOfficer",
            "CorpsOfficer",
        ]
    )
    args = request.args
    rows = store.ordered("digital_givings")
    for field in ("kettle_location_id", "campaign_id", "unit_id", "attribution_status"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    return page([store.public(r) for r in rows], args)


@bp.route("/digital-givings/<gift_id>", methods=["GET"])
def get_digital_giving(gift_id):
    require_role(
        [
            "PlatformAdmin",
            "DigitalGivingProcessor",
            "FinanceOfficer",
            "KettleCoordinator",
            "TerritorialCommander",
            "DivisionalOfficer",
            "CorpsOfficer",
        ]
    )
    gift = validate.path_row("digital_givings", gift_id, "digital giving")
    return success(store.public(gift))


@bp.route("/digital-givings/<gift_id>/attribute", methods=["POST"])
def attribute_digital_giving(gift_id):
    require_role(["DigitalGivingProcessor", "FinanceOfficer", "PlatformAdmin"])
    values = validate.shape([validate.f("kettle_location_id", validate.STRING)])
    gift = validate.path_row("digital_givings", gift_id, "digital giving")

    status = gift.get("attribution_status")
    if status == "REVERSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("RECEIVED", "UNATTRIBUTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    target_id = values.get("kettle_location_id")
    if target_id:
        location = validate.reference("kettle_locations", target_id, "kettle location")
        gift_target_error(location, gift.get("campaign_id"))
    else:
        location = calcs.select_attribution_location(gift.get("campaign_id"))
        if location is None:
            if status == "RECEIVED":
                gift["attribution_status"] = "UNATTRIBUTED"
                store.touch(gift)
            raise ApiError("ERR_NO_ELIGIBLE_LOCATION")

    gift["attribution_status"] = "ATTRIBUTED"
    gift["kettle_location_id"] = location["id"]
    gift["attributed_cents"] = int(gift.get("amount_cents", 0) or 0)
    store.touch(gift)
    refresh_totals(gift)
    return success(store.public(gift))


@bp.route("/digital-givings/<gift_id>/reverse", methods=["POST"])
def reverse_digital_giving(gift_id):
    require_role(["DigitalGivingProcessor", "FinanceOfficer", "PlatformAdmin"])
    values = validate.shape([validate.f("reason", validate.STRING, required=True)])
    gift = validate.path_row("digital_givings", gift_id, "digital giving")
    reason = values["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError("ERR_INVALID_REQUEST", "reason must be a non-empty string.")

    status = gift.get("attribution_status")
    if status == "REVERSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("ATTRIBUTED", "RECEIVED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    was_attributed = status == "ATTRIBUTED"
    gift["attribution_status"] = "REVERSED"
    gift["attributed_cents"] = 0
    gift["reversed_reason"] = reason
    store.touch(gift)
    if was_attributed:
        refresh_totals(gift)
    return success(store.public(gift))
