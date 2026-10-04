"""CustomerSite and InstalledZone endpoints (PRD 3.3), including the site
decommission cascade (PRD 2.9)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import authenticate, authorize, forbid
from calcs import zone_code_in_use
from constants import ALL_ROLES, CONTRACTOR_BUFFER_SECONDS, INSTALLATION_SYSTEMS
from envelope import list_endpoint, success
from errors import ApiError
from serialize import serialize_site, serialize_zone
from store import STORE, new_common, touch
from util import get_body, req_bool, req_decimal, req_dt, req_enum, req_int, req_str

bp = Blueprint("sites", __name__)

IN_FLIGHT_TAKEBACK_STATES = ("REQUESTED", "SCHEDULED", "COLLECTED")


@bp.route("/carpetloop/sites", methods=["POST"])
def create_site():
    uid, role = authenticate()
    authorize(role, {"Specifier"})
    body = get_body()
    # Priority 11: request shape. Install window is a CLOSED interval; the end
    # must not be earlier than the start (PRD 2.5).
    contractor_name = req_str(body, "contractor_name")
    address = req_str(body, "address")
    window_start = req_dt(body, "install_window_start")
    window_end = req_dt(body, "install_window_end")
    installation_system = req_enum(body, "installation_system", INSTALLATION_SYSTEMS)
    certified = req_bool(body, "adhesive_free_certified")
    cert_expires = req_dt(body, "cert_expires_on")
    budget = req_int(body, "annual_replacement_budget_cents", min_inclusive=0)
    if window_end < window_start:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "install_window_end must not precede install_window_start"
        )
    s = new_common(STORE)
    s.update(
        {
            "created_by": uid,
            "contractor_name": contractor_name,
            "address": address,
            "install_window_start": window_start,
            "install_window_end": window_end,
            "installation_system": installation_system,
            "adhesive_free_certified": certified,
            "cert_expires_on": cert_expires,
            "annual_replacement_budget_cents": budget,
            "spent_replacement_cents": 0,
            "status": "PLANNED",
        }
    )
    STORE.sites[s["id"]] = s
    return success(serialize_site(s), 201)


@bp.route("/carpetloop/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    s = STORE.sites.get(site_id)
    if s is None:
        raise ApiError("ERR_SITE_NOT_FOUND", 404, "Site does not exist")
    return success(serialize_site(s), 200)


def _installer_site(site_id, uid):
    """Priority 3 ownership (when the anchor exists) then priority 4."""
    s = STORE.sites.get(site_id)
    if s is not None and uid != s["contractor_name"]:
        forbid("X-User-ID must equal the site's contractor_name")
    if s is None:
        raise ApiError("ERR_SITE_NOT_FOUND", 404, "Site does not exist")
    return s


@bp.route("/carpetloop/sites/<site_id>/install", methods=["POST"])
def install_site(site_id):
    uid, role = authenticate()
    authorize(role, {"Installer"})
    s = _installer_site(site_id, uid)
    # Priority 5: PLANNED -> INSTALLED is the only install transition.
    if s["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Site is not in PLANNED")
    # Priority 9: an ADHESIVE_FREE installation requires the certified flag.
    if s["installation_system"] == "ADHESIVE_FREE" and not s["adhesive_free_certified"]:
        raise ApiError(
            "ERR_ADHESIVE_FREE_CERT_REQUIRED",
            422,
            "ADHESIVE_FREE installation requires adhesive_free_certified",
        )
    # Priority 10: whenever the contractor is recorded as certified, the
    # certification must be strictly later than the window's opening.
    if s["adhesive_free_certified"] and not (
        s["cert_expires_on"] > s["install_window_start"]
    ):
        raise ApiError(
            "ERR_CONTRACTOR_CERT_EXPIRED",
            422,
            "cert_expires_on must be strictly later than install_window_start",
        )
    # Priority 11: one contractor cannot be in two places at once. Each closed
    # window is extended by one full day at both ends before judging conflict.
    buf = timedelta(seconds=CONTRACTOR_BUFFER_SECONDS)
    s1, e1 = s["install_window_start"], s["install_window_end"]
    for other in STORE.sites.values():
        if other["id"] == s["id"]:
            continue
        if other["contractor_name"] != s["contractor_name"]:
            continue
        if other["status"] not in ("INSTALLED", "IN_SERVICE"):
            continue
        s2, e2 = other["install_window_start"], other["install_window_end"]
        if (s1 - buf) <= (e2 + buf) and (s2 - buf) <= (e1 + buf):
            raise ApiError(
                "ERR_CONTRACTOR_WINDOW_CONFLICT",
                409,
                "Install window conflicts with another site of the same contractor",
            )
    s["status"] = "INSTALLED"
    touch(STORE, s)
    return success(serialize_site(s), 200)


@bp.route("/carpetloop/sites/<site_id>/decommission", methods=["POST"])
def decommission_site(site_id):
    uid, role = authenticate()
    authorize(role, {"Installer"})
    s = _installer_site(site_id, uid)
    # Priority 5: decommission transitions exist from PLANNED and IN_SERVICE.
    if s["status"] not in ("PLANNED", "IN_SERVICE"):
        raise ApiError("ERR_INVALID_STATE", 409, "Site cannot be decommissioned from its state")
    # Priority 6: no take-back of the site may be in flight.
    for t in STORE.takebacks.values():
        if t["site_id"] == site_id and t["status"] in IN_FLIGHT_TAKEBACK_STATES:
            raise ApiError(
                "ERR_TAKEBACK_IN_FLIGHT", 409, "A take-back of this site is still in flight"
            )
    if s["status"] == "IN_SERVICE":
        # Decommission cascade (PRD 2.9): reclaim zones, cancel non-terminal
        # orders with the orders' full cancellation side effects.
        from routes_orders import cancel_order

        for z in STORE.zones.values():
            if z["site_id"] == site_id and z["status"] == "IN_SERVICE":
                z["status"] = "RECLAIMED"
                touch(STORE, z)
        for o in list(STORE.orders.values()):
            if o["site_id"] == site_id and o["status"] in ("DRAFT", "MATCHED", "MATCH_FAILED"):
                cancel_order(STORE, o)
    s["status"] = "DECOMMISSIONED"
    touch(STORE, s)
    return success(serialize_site(s), 200)


@bp.route("/carpetloop/sites/<site_id>/zones", methods=["POST"])
def create_zone(site_id):
    uid, role = authenticate()
    authorize(role, {"Installer"})
    s = _installer_site(site_id, uid)
    body = get_body()
    # Priority 4: body FK (batch) after the path site.
    batch = None
    if body.get("batch_id") is not None:
        batch = STORE.batches.get(body["batch_id"])
        if batch is None:
            raise ApiError("ERR_BATCH_NOT_FOUND", 404, "Batch does not exist")
    # Priority 6: batch RELEASED first, then site INSTALLED|IN_SERVICE.
    if batch is not None and batch["status"] != "RELEASED":
        raise ApiError("ERR_BATCH_NOT_RELEASED", 409, "Batch is not in RELEASED")
    if s["status"] not in ("INSTALLED", "IN_SERVICE"):
        raise ApiError("ERR_SITE_NOT_INSTALLED", 409, "Site is not INSTALLED or IN_SERVICE")
    # Priority 11: request shape, then zone-code uniqueness among IN_SERVICE.
    req_str(body, "batch_id")
    zone_code = req_str(body, "zone_code")
    area_m2 = req_decimal(body, "area_m2", min_exclusive=0)
    if zone_code_in_use(STORE, site_id, zone_code):
        raise ApiError(
            "ERR_ZONE_CODE_CONFLICT",
            409,
            "zone_code duplicates an IN_SERVICE zone at this site",
        )
    # Priority 12: capacity within the batch's availability.
    if area_m2 > batch["available_m2"]:
        raise ApiError("ERR_AREA_EXCEEDS_BATCH", 422, "area_m2 exceeds the batch's available_m2")
    z = new_common(STORE)
    z.update(
        {
            "site_id": site_id,
            "batch_id": batch["id"],
            "zone_code": zone_code,
            "area_m2": area_m2,
            "status": "IN_SERVICE",
        }
    )
    STORE.zones[z["id"]] = z
    batch["available_m2"] -= area_m2
    if batch["available_m2"] == 0:
        batch["status"] = "EXHAUSTED"
    touch(STORE, batch)
    # The site's first zone bubbles INSTALLED -> IN_SERVICE.
    if s["status"] == "INSTALLED":
        s["status"] = "IN_SERVICE"
        touch(STORE, s)
    return success(serialize_zone(z), 201)


@bp.route("/carpetloop/zones/<zone_id>", methods=["GET"])
def get_zone(zone_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    z = STORE.zones.get(zone_id)
    if z is None:
        raise ApiError("ERR_ZONE_NOT_FOUND", 404, "Zone does not exist")
    return success(serialize_zone(z), 200)


@bp.route("/carpetloop/zones", methods=["GET"])
def list_zones():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    filters = {}
    for f in ("site_id", "batch_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters[f] = v
    return list_endpoint(STORE.zones.values(), request.args, filters, serialize_zone)
