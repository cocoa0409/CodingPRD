"""Campaign governance and the seasonal clock (PRD 3.2)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

CAMPAIGN_STATUSES = ("PLANNING", "ACTIVE", "CLOSED")


def campaign_locations(campaign_id):
    return [loc for loc in store.rows("kettle_locations") if loc.get("campaign_id") == campaign_id]


def campaign_shifts(campaign_id):
    location_ids = {loc["id"] for loc in campaign_locations(campaign_id)}
    return [s for s in store.rows("shifts") if s.get("kettle_location_id") in location_ids]


def recompute_campaign(campaign):
    campaign["active_location_count"] = len(
        [loc for loc in campaign_locations(campaign["id"]) if loc.get("status") == "ACTIVE"]
    )
    campaign["labor_committed_cents"] = sum(
        int(s.get("paid_amount_cents", 0) or 0)
        for s in campaign_shifts(campaign["id"])
        if s.get("status") == "COMPLETED"
    )
    campaign["total_raised_cents"] = calcs.campaign_total_raised(campaign["id"])
    store.touch(campaign)
    return campaign


def cancel_shift(shift, recompute_ringer=True):
    shift["_prev_status"] = shift.get("status")
    shift["status"] = "CANCELLED"
    store.touch(shift)
    if recompute_ringer:
        ringer = store.find("bell_ringers", shift.get("bell_ringer_id"))
        if ringer is not None:
            calcs.recompute_scheduled_hours(ringer)


def close_campaign(campaign):
    """ACTIVE -> CLOSED plus the largest cascade in the system."""
    campaign["status"] = "CLOSED"
    store.touch(campaign)
    for location in campaign_locations(campaign["id"]):
        if location.get("status") in ("ACTIVE", "SUSPENDED"):
            location["status"] = "CLOSED"
            store.touch(location)
            for shift in store.rows("shifts"):
                if shift.get("kettle_location_id") != location["id"]:
                    continue
                if shift.get("status") in ("SCHEDULED", "CONFIRMED"):
                    cancel_shift(shift)
    campaign["active_location_count"] = 0
    store.touch(campaign)
    return campaign


def apply_clock_events(campaign):
    """A campaign in ACTIVE closes itself once the clock passes ends_on."""
    if campaign.get("status") != "ACTIVE":
        return campaign
    ends_on = clock.parse(campaign.get("ends_on"))
    if ends_on is not None and clock.now() > ends_on:
        close_campaign(campaign)
    return campaign


@bp.route("/campaigns", methods=["POST"])
def create_campaign():
    require_role(["PlatformAdmin", "TerritorialCommander"])
    values = validate.shape(
        [
            validate.f("name", validate.STRING, required=True),
            validate.f("season_year", validate.INTEGER, required=True),
            validate.f("starts_on", validate.DATETIME, required=True),
            validate.f("ends_on", validate.DATETIME, required=True),
            validate.f("goal_cents", validate.INTEGER, required=True),
            validate.f("labor_budget_cents", validate.INTEGER),
        ]
    )
    campaign = {
        "name": values["name"],
        "season_year": int(values["season_year"]),
        "starts_on": clock.fmt(values["starts_on"]),
        "ends_on": clock.fmt(values["ends_on"]),
        "status": "PLANNING",
        "goal_cents": int(values["goal_cents"]),
        "labor_budget_cents": int(values.get("labor_budget_cents", 0) or 0),
        "total_raised_cents": 0,
        "labor_committed_cents": 0,
        "active_location_count": 0,
    }
    store.insert("campaigns", campaign)
    return success(store.public(campaign)), 201


@bp.route("/campaigns", methods=["GET"])
def list_campaigns():
    require_role(
        [
            "PlatformAdmin",
            "TerritorialCommander",
            "DivisionalOfficer",
            "CorpsOfficer",
            "KettleCoordinator",
            "FinanceOfficer",
            "DigitalGivingProcessor",
            "AssistanceCaseworker",
            "HostSiteManager",
        ]
    )
    args = request.args
    rows = store.ordered("campaigns")
    status = args.get("status")
    season_year = args.get("season_year")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if season_year:
        try:
            year = int(season_year)
            rows = [r for r in rows if int(r.get("season_year", 0)) == year]
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "season_year must be an integer.")
    return page([store.public(r) for r in rows], args)


@bp.route("/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    require_role(
        [
            "PlatformAdmin",
            "TerritorialCommander",
            "DivisionalOfficer",
            "CorpsOfficer",
            "KettleCoordinator",
            "FinanceOfficer",
            "DigitalGivingProcessor",
            "AssistanceCaseworker",
            "HostSiteManager",
        ]
    )
    campaign = validate.path_row("campaigns", campaign_id, "campaign")
    apply_clock_events(campaign)
    return success(store.public(campaign))


@bp.route("/campaigns/<campaign_id>/activate", methods=["POST"])
def activate_campaign(campaign_id):
    require_role(["TerritorialCommander"])
    values = validate.shape([validate.optional_version("expected_campaign_version")])
    campaign = validate.path_row("campaigns", campaign_id, "campaign")
    validate.expect_version(campaign, values.get("expected_campaign_version"), "expected_campaign_version")

    if campaign.get("status") == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if campaign.get("status") != "PLANNING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    approved = [
        site
        for site in store.rows("host_sites")
        if site.get("campaign_id") == campaign_id and site.get("permission_status") == "APPROVED"
    ]
    if not approved:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "At least one host site with an APPROVED permission is required.",
        )
    ends_on = clock.parse(campaign.get("ends_on"))
    if ends_on is None or not (ends_on > clock.now()):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The campaign end instant must be in the future.")

    campaign["status"] = "ACTIVE"
    store.touch(campaign)
    return success(store.public(campaign))


@bp.route("/campaigns/<campaign_id>/summary", methods=["GET"])
def campaign_summary(campaign_id):
    require_role(
        ["PlatformAdmin", "TerritorialCommander", "DivisionalOfficer", "FinanceOfficer", "KettleCoordinator"]
    )
    campaign = validate.path_row("campaigns", campaign_id, "campaign")
    apply_clock_events(campaign)
    collections_total, digital_total = calcs.campaign_components(campaign_id)
    total_raised = collections_total + digital_total
    goal = int(campaign.get("goal_cents", 0) or 0)
    attainment = (100 * total_raised) // goal if goal > 0 else 0
    active_locations = len(
        [loc for loc in campaign_locations(campaign_id) if loc.get("status") == "ACTIVE"]
    )
    labor_committed = sum(
        int(s.get("paid_amount_cents", 0) or 0)
        for s in campaign_shifts(campaign_id)
        if s.get("status") == "COMPLETED"
    )
    data = {
        "campaign_id": campaign["id"],
        "status": campaign.get("status"),
        "goal_cents": goal,
        "total_raised_cents": total_raised,
        "collections_counted_cents": collections_total,
        "digital_attributed_cents": digital_total,
        "attainment_pct": attainment,
        "active_location_count": active_locations,
        "labor_committed_cents": labor_committed,
        "labor_budget_cents": int(campaign.get("labor_budget_cents", 0) or 0),
    }
    return success(data)
