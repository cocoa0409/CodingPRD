"""Host sites: negotiated retail permissions (PRD 3.1)."""
from flask import request

from core import clock, store, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

PERMISSION_STATUSES = ("PENDING", "APPROVED", "DENIED", "EXPIRED", "REVOKED")
EXCLUSIVITY_SCOPES = ("EXCLUSIVE", "NON_EXCLUSIVE")


def recompute_host_site(site):
    count = 0
    for location in store.rows("kettle_locations"):
        if location.get("host_site_id") == site["id"] and location.get("status") in ("ACTIVE", "SUSPENDED"):
            count += 1
    site["active_kettle_count"] = count
    store.touch(site)
    return site


def cancel_location_shifts(location, after=None):
    for shift in store.rows("shifts"):
        if shift.get("kettle_location_id") != location["id"]:
            continue
        if shift.get("status") not in ("SCHEDULED", "CONFIRMED"):
            continue
        if after is not None:
            start = clock.parse(shift.get("starts_at"))
            if start is None or not (start > after):
                continue
        shift["_prev_status"] = shift.get("status")
        shift["status"] = "CANCELLED"
        store.touch(shift)
        ringer = store.find("bell_ringers", shift.get("bell_ringer_id"))
        if ringer is not None:
            from core import calcs

            calcs.recompute_scheduled_hours(ringer)


def expire_host_site(site):
    """APPROVED -> EXPIRED once the clock passes permission_ends_on."""
    expiry = clock.parse(site.get("permission_ends_on"))
    site["permission_status"] = "EXPIRED"
    store.touch(site)
    for location in store.rows("kettle_locations"):
        if location.get("host_site_id") != site["id"] or location.get("status") != "ACTIVE":
            continue
        location["status"] = "SUSPENDED"
        store.touch(location)
        cancel_location_shifts(location, after=expiry)
    recompute_host_site(site)
    return site


def apply_clock_events(site):
    if site.get("permission_status") != "APPROVED":
        return site
    expiry = clock.parse(site.get("permission_ends_on"))
    if expiry is not None and clock.now() > expiry:
        expire_host_site(site)
    return site


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.route("/host-sites", methods=["POST"])
def create_host_site():
    require_role(["KettleCoordinator", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("campaign_id", validate.STRING, required=True),
            validate.f("retailer_name", validate.STRING, required=True),
            validate.f("store_number", validate.STRING, required=True),
            validate.f("city", validate.STRING, required=True),
            validate.f("state_code", validate.STRING, required=True),
            validate.f("permission_starts_on", validate.DATETIME, required=True),
            validate.f("permission_ends_on", validate.DATETIME, required=True),
            validate.f("exclusivity_scope", validate.ENUM, enum=EXCLUSIVITY_SCOPES),
            validate.f("max_kettles", validate.INTEGER),
        ]
    )
    validate.reference("campaigns", values["campaign_id"], "campaign")
    site = {
        "campaign_id": values["campaign_id"],
        "retailer_name": values["retailer_name"],
        "store_number": values["store_number"],
        "city": values["city"],
        "state_code": values["state_code"],
        "permission_status": "PENDING",
        "permission_starts_on": clock.fmt(values["permission_starts_on"]),
        "permission_ends_on": clock.fmt(values["permission_ends_on"]),
        "exclusivity_scope": values.get("exclusivity_scope") or "NON_EXCLUSIVE",
        "max_kettles": int(values.get("max_kettles", 1) if values.get("max_kettles") is not None else 1),
        "active_kettle_count": 0,
    }
    store.insert("host_sites", site)
    return success(store.public(site)), 201


@bp.route("/host-sites", methods=["GET"])
def list_host_sites():
    require_role(
        [
            "PlatformAdmin",
            "KettleCoordinator",
            "TerritorialCommander",
            "DivisionalOfficer",
            "CorpsOfficer",
            "HostSiteManager",
        ]
    )
    args = request.args
    rows = store.ordered("host_sites")
    for field in ("campaign_id", "permission_status", "retailer_name", "store_number"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    return page([store.public(r) for r in rows], args)


@bp.route("/host-sites/<site_id>", methods=["GET"])
def get_host_site(site_id):
    role, user_id = require_role(
        [
            "PlatformAdmin",
            "KettleCoordinator",
            "TerritorialCommander",
            "DivisionalOfficer",
            "CorpsOfficer",
            "HostSiteManager",
        ]
    )
    site = validate.path_row("host_sites", site_id, "host site")
    from core.auth import owner_guard

    owner_guard(role, user_id, site["id"])
    apply_clock_events(site)
    return success(store.public(site))


@bp.route("/host-sites/<site_id>/approve", methods=["POST"])
def approve_host_site(site_id):
    role, _user_id = require_role(["KettleCoordinator", "TerritorialCommander"])
    values = validate.shape(
        [
            validate.f("decision", validate.STRING),
            validate.optional_version("expected_host_site_version"),
        ]
    )
    site = validate.path_row("host_sites", site_id, "host site")
    validate.expect_version(site, values.get("expected_host_site_version"), "expected_host_site_version")

    decision = (values.get("decision") or "APPROVE").strip().upper()
    if decision not in ("APPROVE", "DENY", "REVOKE"):
        raise ApiError("ERR_INVALID_REQUEST", "decision must be one of APPROVE, DENY or REVOKE.")

    status = site.get("permission_status")
    if decision == "REVOKE":
        if role != "TerritorialCommander":
            raise ApiError("ERR_FORBIDDEN", "Only a TerritorialCommander may revoke a permission.")
        if status in ("REVOKED", "DENIED"):
            raise ApiError("ERR_ALREADY_TERMINAL")
        if status != "APPROVED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        site["permission_status"] = "REVOKED"
        store.touch(site)
        for location in store.rows("kettle_locations"):
            if location.get("host_site_id") != site["id"]:
                continue
            if location.get("status") in ("DRAFT", "ACTIVE", "SUSPENDED"):
                location["status"] = "CLOSED"
                store.touch(location)
        recompute_host_site(site)
        return success(store.public(site))

    if decision == "DENY":
        if status in ("DENIED", "REVOKED"):
            raise ApiError("ERR_ALREADY_TERMINAL")
        if status != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        site["permission_status"] = "DENIED"
        store.touch(site)
        return success(store.public(site))

    # APPROVE
    if status in ("DENIED", "REVOKED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    starts_on = clock.parse(site.get("permission_starts_on"))
    ends_on = clock.parse(site.get("permission_ends_on"))
    if starts_on is None or ends_on is None or not (ends_on > starts_on):
        raise ApiError("ERR_INVALID_REQUEST", "permission_ends_on must be later than permission_starts_on.")
    campaign = store.find("campaigns", site.get("campaign_id"))
    if campaign is None or campaign.get("status") not in ("ACTIVE", "PLANNING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The owning campaign must be ACTIVE or PLANNING.")
    site["permission_status"] = "APPROVED"
    store.touch(site)
    return success(store.public(site))


@bp.route("/host-sites/<site_id>/renew", methods=["POST"])
def renew_host_site(site_id):
    require_role(["KettleCoordinator", "TerritorialCommander"])
    values = validate.shape(
        [
            validate.f("permission_starts_on", validate.DATETIME),
            validate.f("permission_ends_on", validate.DATETIME, required=True),
        ]
    )
    site = validate.path_row("host_sites", site_id, "host site")
    if site.get("permission_status") != "EXPIRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    new_end = values["permission_ends_on"]
    if not (new_end > clock.now()):
        raise ApiError("ERR_INVALID_REQUEST", "permission_ends_on must be later than the current instant.")
    new_start = clock.now()

    for other in store.rows("host_sites"):
        if other["id"] == site["id"]:
            continue
        if other.get("retailer_name") != site.get("retailer_name"):
            continue
        if other.get("store_number") != site.get("store_number"):
            continue
        if other.get("permission_status") != "APPROVED":
            continue
        other_start = clock.parse(other.get("permission_starts_on"))
        other_end = clock.parse(other.get("permission_ends_on"))
        if other_start is None or other_end is None:
            continue
        if _overlaps(new_start, new_end, other_start, other_end):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Another host site for this retailer and store already holds an overlapping permission.",
            )

    site["permission_status"] = "APPROVED"
    site["permission_starts_on"] = clock.fmt(new_start)
    site["permission_ends_on"] = clock.fmt(new_end)
    store.touch(site)
    for location in store.rows("kettle_locations"):
        if location.get("host_site_id") != site["id"] or location.get("status") != "SUSPENDED":
            continue
        p_start = clock.parse(location.get("placement_starts_on"))
        p_end = clock.parse(location.get("placement_ends_on"))
        if p_start is None or p_end is None:
            continue
        if p_start >= new_start and p_end <= new_end:
            location["status"] = "ACTIVE"
            store.touch(location)
    recompute_host_site(site)
    return success(store.public(site))
