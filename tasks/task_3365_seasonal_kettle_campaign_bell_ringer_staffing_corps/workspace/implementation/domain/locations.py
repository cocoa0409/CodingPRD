"""Kettle locations: placement discipline and the location lifecycle (PRD 3.1)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import owner_guard, require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

PLACEMENTS = ("INDOOR", "OUTDOOR", "DRIVE_THROUGH")
LOCATION_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")
IN_FLIGHT_DEPOSITS = ("SUBMITTED", "VERIFIED", "VARIANCE_HOLD")


def host_site_for(location):
    return store.find("host_sites", location.get("host_site_id"))


def campaign_for(location):
    return store.find("campaigns", location.get("campaign_id"))


def active_location_count(site_id):
    count = 0
    for location in store.rows("kettle_locations"):
        if location.get("host_site_id") == site_id and location.get("status") in ("ACTIVE", "SUSPENDED"):
            count += 1
    return count


def _touching_or_overlapping(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def exclusivity_conflict(location, exclude_id=None):
    site = host_site_for(location)
    if site is None:
        return False
    p_start = clock.parse(location.get("placement_starts_on"))
    p_end = clock.parse(location.get("placement_ends_on"))
    if p_start is None or p_end is None:
        return False
    for other in store.rows("kettle_locations"):
        if other["id"] == (exclude_id or location.get("id")):
            continue
        if other.get("status") == "CLOSED":
            continue
        other_site = host_site_for(other)
        if other_site is None:
            continue
        if other_site.get("retailer_name") != site.get("retailer_name"):
            continue
        if other_site.get("store_number") != site.get("store_number"):
            continue
        if site.get("exclusivity_scope") != "EXCLUSIVE" and other_site.get("exclusivity_scope") != "EXCLUSIVE":
            continue
        o_start = clock.parse(other.get("placement_starts_on"))
        o_end = clock.parse(other.get("placement_ends_on"))
        if o_start is None or o_end is None:
            continue
        if _touching_or_overlapping(p_start, p_end, o_start, o_end):
            return True
    return False


def window_contained(location):
    site = host_site_for(location)
    if site is None:
        return False
    perm_start = clock.parse(site.get("permission_starts_on"))
    perm_end = clock.parse(site.get("permission_ends_on"))
    p_start = clock.parse(location.get("placement_starts_on"))
    p_end = clock.parse(location.get("placement_ends_on"))
    if None in (perm_start, perm_end, p_start, p_end):
        return False
    return p_start >= perm_start and p_end <= perm_end


def recompute_location_counters(location):
    site = host_site_for(location)
    if site is not None:
        from domain.hostsites import recompute_host_site

        recompute_host_site(site)
    campaign = campaign_for(location)
    if campaign is not None:
        campaign["active_location_count"] = len(
            [
                loc
                for loc in store.rows("kettle_locations")
                if loc.get("campaign_id") == campaign["id"] and loc.get("status") == "ACTIVE"
            ]
        )
        store.touch(campaign)


@bp.route("/kettle-locations", methods=["POST"])
def create_kettle_location():
    require_role(["KettleCoordinator", "CorpsOfficer"])
    values = validate.shape(
        [
            validate.f("host_site_id", validate.STRING, required=True),
            validate.f("campaign_id", validate.STRING, required=True),
            validate.f("location_code", validate.STRING, required=True),
            validate.f("placement", validate.ENUM, required=True, enum=PLACEMENTS),
            validate.f("placement_starts_on", validate.DATETIME, required=True),
            validate.f("placement_ends_on", validate.DATETIME, required=True),
            validate.f("daily_required_minutes", validate.INTEGER),
        ]
    )
    site = validate.reference("host_sites", values["host_site_id"], "host site")
    validate.reference("campaigns", values["campaign_id"], "campaign")
    if site.get("campaign_id") != values["campaign_id"]:
        validate.scope_mismatch("The host site belongs to a different campaign.")

    for existing in store.rows("kettle_locations"):
        if existing.get("campaign_id") == values["campaign_id"] and existing.get("location_code") == values[
            "location_code"
        ]:
            raise ApiError("ERR_DUPLICATE_LOCATION_CODE")

    location = {
        "host_site_id": values["host_site_id"],
        "campaign_id": values["campaign_id"],
        "location_code": values["location_code"],
        "placement": values["placement"],
        "status": "DRAFT",
        "placement_starts_on": clock.fmt(values["placement_starts_on"]),
        "placement_ends_on": clock.fmt(values["placement_ends_on"]),
        "daily_required_minutes": int(
            values.get("daily_required_minutes", 480) if values.get("daily_required_minutes") is not None else 480
        ),
        "covered_minutes": 0,
        "location_total_cents": 0,
        "cents_per_hour": 0,
        "performance_tier": "UNRATED",
    }

    if not window_contained(location):
        raise ApiError("ERR_PLACEMENT_WINDOW_OUTSIDE_PERMISSION")
    if exclusivity_conflict(location):
        raise ApiError("ERR_EXCLUSIVITY_CONFLICT")

    store.insert("kettle_locations", location)
    return success(store.public(location)), 201


@bp.route("/kettle-locations", methods=["GET"])
def list_kettle_locations():
    require_role(
        [
            "PlatformAdmin",
            "KettleCoordinator",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "HostSiteManager",
            "FinanceOfficer",
            "VolunteerCoordinator",
        ]
    )
    args = request.args
    rows = store.ordered("kettle_locations")
    for field in ("host_site_id", "campaign_id", "status"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    return page([store.public(r) for r in rows], args)


@bp.route("/kettle-locations/<location_id>", methods=["GET"])
def get_kettle_location(location_id):
    role, user_id = require_role(
        [
            "PlatformAdmin",
            "KettleCoordinator",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "HostSiteManager",
            "FinanceOfficer",
            "VolunteerCoordinator",
        ]
    )
    location = validate.path_row("kettle_locations", location_id, "kettle location")
    if role == "HostSiteManager":
        owner_guard(role, user_id, location.get("host_site_id"))
    return success(store.public(location))


@bp.route("/kettle-locations/<location_id>/activate", methods=["POST"])
def activate_kettle_location(location_id):
    require_role(["KettleCoordinator", "CorpsOfficer"])
    values = validate.shape([validate.optional_version("expected_kettle_location_version")])
    location = validate.path_row("kettle_locations", location_id, "kettle location")
    validate.expect_version(
        location, values.get("expected_kettle_location_version"), "expected_kettle_location_version"
    )

    status = location.get("status")
    if status == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("DRAFT", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    campaign = campaign_for(location)
    if campaign is None or campaign.get("status") != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE")
    site = host_site_for(location)
    if site is None or site.get("permission_status") != "APPROVED":
        raise ApiError("ERR_HOST_SITE_NOT_PERMITTED")

    if status == "DRAFT":
        if not window_contained(location):
            raise ApiError("ERR_PLACEMENT_WINDOW_OUTSIDE_PERMISSION")
        if exclusivity_conflict(location):
            raise ApiError("ERR_EXCLUSIVITY_CONFLICT")
        if active_location_count(site["id"]) >= int(site.get("max_kettles", 1) or 1):
            raise ApiError("ERR_KETTLE_CAP_EXCEEDED")

    location["status"] = "ACTIVE"
    store.touch(location)
    recompute_location_counters(location)
    return success(store.public(location))


@bp.route("/kettle-locations/<location_id>/suspend", methods=["POST"])
def suspend_kettle_location(location_id):
    require_role(["KettleCoordinator", "CorpsOfficer"])
    location = validate.path_row("kettle_locations", location_id, "kettle location")
    status = location.get("status")
    if status == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    location["status"] = "SUSPENDED"
    store.touch(location)
    from domain.hostsites import cancel_location_shifts

    cancel_location_shifts(location)
    recompute_location_counters(location)
    return success(store.public(location))


@bp.route("/kettle-locations/<location_id>/close", methods=["POST"])
def close_kettle_location(location_id):
    require_role(["KettleCoordinator", "TerritorialCommander"])
    location = validate.path_row("kettle_locations", location_id, "kettle location")
    status = location.get("status")
    if status == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    for collection in store.rows("kettle_collections"):
        if collection.get("kettle_location_id") != location["id"]:
            continue
        if collection.get("deposit_status") in IN_FLIGHT_DEPOSITS:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "A collection at this location is still in flight.",
            )

    location["status"] = "CLOSED"
    store.touch(location)
    if status == "ACTIVE":
        from domain.hostsites import cancel_location_shifts

        cancel_location_shifts(location)
    recompute_location_counters(location)
    return success(store.public(location))


@bp.route("/kettle-locations/<location_id>/performance", methods=["GET"])
def location_performance(location_id):
    require_role(
        [
            "PlatformAdmin",
            "KettleCoordinator",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "HostSiteManager",
            "FinanceOfficer",
        ]
    )
    location = validate.path_row("kettle_locations", location_id, "kettle location")
    on_date_raw = request.args.get("on_date")
    if on_date_raw:
        parsed = clock.parse(on_date_raw)
        if parsed is None:
            raise ApiError("ERR_INVALID_REQUEST", "on_date must be an ISO 8601 date.")
        on_date = parsed.date()
    else:
        on_date = clock.now().date()

    snap = calcs.performance_snapshot(location["id"])
    covered, coverage_pct, understaffed = calcs.coverage_for_date(location, on_date)
    data = {
        "location_id": location["id"],
        "location_total_cents": snap["location_total_cents"],
        "covered_minutes": snap["covered_minutes"],
        "covered_hours": snap["covered_hours"],
        "cents_per_hour": snap["cents_per_hour"],
        "performance_index": snap["performance_index"],
        # PRD §3.9: the read exposes the grade computed from the live counters
        # (location_total_cents, covered_minutes, disruption record). Returning
        # the stored snapshot instead would ignore no-shows and any money that
        # arrived after the last recompute, contradicting §3.9's own formula.
        "performance_tier": snap["performance_tier"],
        "coverage_pct": coverage_pct,
        "understaffed": understaffed,
    }
    return success(data)
