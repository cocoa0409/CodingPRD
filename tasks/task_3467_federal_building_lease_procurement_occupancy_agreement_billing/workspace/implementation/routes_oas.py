"""OccupancyAgreement endpoints (PRD section 3.5, excluding billing)."""
from flask import Blueprint, request

from cascade import oa_terminal_cascade, sync_building
from dates import parse_date
from envelope import success
from errors import ApiError
from middleware import (ALL_ROLES, agency_scope, body, is_int, paginate,
                        require_auth)
from store import DB, bump, make_entity, now_str, pub, sorted_items

bp = Blueprint("oas", __name__)


def _get_oa(oid):
    oa = DB["oas"].get(oid)
    if not oa:
        raise ApiError("ERR_NOT_FOUND", 404, "OccupancyAgreement not found")
    return oa


def _committed_on_building(building_id):
    return sum(o["assigned_sf"] for o in DB["oas"].values()
               if o.get("building_id") == building_id and o["status"] in ("DRAFT", "ACTIVE"))


def _committed_on_lease(lease_id):
    return sum(o["assigned_sf"] for o in DB["oas"].values()
               if o.get("lease_id") == lease_id and o["status"] in ("DRAFT", "ACTIVE"))


@bp.route("/leasing/occupancy-agreements", methods=["POST"])
def create_oa():
    require_auth(["GSALeasingOfficer"])
    b = body()
    lease_id = b.get("lease_id")
    building_id = b.get("building_id")
    agency_id = b.get("agency_id")
    # priority 4: body ids left to right — lease_id, building_id, agency_id
    if lease_id is not None and lease_id not in DB["leases"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Lease not found")
    if building_id is not None and building_id not in DB["buildings"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Building not found")
    if agency_id is not None and agency_id not in DB["agencies"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Agency not found")
    # priority 5: shape and field domains
    if not isinstance(agency_id, str) or agency_id == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "agency_id is required")
    if not is_int(b.get("assigned_sf")) or b["assigned_sf"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "assigned_sf must be an integer > 0")
    sd = parse_date(b.get("start_date"))
    ed = parse_date(b.get("end_date"))
    if sd is None or ed is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "start_date and end_date must be ISO dates")
    if ed <= sd:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_date must be after start_date")
    shell_eq = b.get("shell_equivalent_rate_per_sf_yr_cents")
    op_rate = b.get("operating_rate_per_sf_yr_cents")
    if shell_eq is not None and (not is_int(shell_eq) or shell_eq < 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "shell_equivalent_rate_per_sf_yr_cents must be >= 0")
    if op_rate is not None and (not is_int(op_rate) or op_rate < 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "operating_rate_per_sf_yr_cents must be >= 0")
    # priority 10: referential structure
    if (lease_id is None) == (building_id is None):
        raise ApiError("ERR_OA_TENANCY_AMBIGUOUS", 422, "Exactly one of lease_id / building_id must be present")
    if building_id is not None:
        bld = DB["buildings"][building_id]
        if bld["ownership_type"] != "FEDERALLY_OWNED":
            raise ApiError("ERR_BUILDING_NOT_OWNED", 422, "building_id OAs are only valid on FEDERALLY_OWNED buildings")
        if shell_eq is None or op_rate is None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Owned OAs require shell_equivalent_rate_per_sf_yr_cents and operating_rate_per_sf_yr_cents")
        lease = None
    else:
        lease = DB["leases"][lease_id]
        bld = None
        # the lease window check applies only once the lease has pinned dates
        # (i.e. once it has commenced); it is skipped while AWARDED
        if lease["status"] != "AWARDED":
            if sd < parse_date(lease["commencement_date"]) or ed > parse_date(lease["end_date"]):
                raise ApiError("ERR_OA_TERM_EXCEEDS_LEASE", 422,
                               "Leased OA window must lie within the lease term")
    # priority 11: capacity
    if bld is not None:
        if _committed_on_building(bld["id"]) + b["assigned_sf"] > bld["total_sf"]:
            raise ApiError("ERR_BUILDING_CAPACITY_EXCEEDED", 422, "Committed square footage would exceed total_sf")
    else:
        if _committed_on_lease(lease["id"]) + b["assigned_sf"] > lease["leased_sf"]:
            raise ApiError("ERR_LEASE_SPACE_EXCEEDED", 422, "Committed square footage would exceed the lease's leased_sf")
    e = make_entity()
    e.update({
        "lease_id": lease_id,
        "building_id": building_id,
        "agency_id": agency_id,
        "assigned_sf": b["assigned_sf"],
        "start_date": b["start_date"],
        "end_date": b["end_date"],
        "shell_equivalent_rate_per_sf_yr_cents": shell_eq if building_id is not None else None,
        "operating_rate_per_sf_yr_cents": op_rate if building_id is not None else None,
        "pricing_source": "LEASE_PASS_THROUGH" if lease_id is not None else "OWNED_MARKET",
        "status": "DRAFT",
        "pending_service_credit_cents": 0,
        "receivable_outstanding_cents": 0,
        "terminal_writeoff_cents": 0,
        "amendment_history": [],
    })
    DB["oas"][e["id"]] = e
    if bld is not None:
        sync_building(bld)  # owned OA reserves its space from creation
    return success(pub(e), 201)


@bp.route("/leasing/occupancy-agreements/<oid>", methods=["GET"])
def get_oa(oid):
    require_auth(ALL_ROLES)
    return success(pub(_get_oa(oid)))


@bp.route("/leasing/occupancy-agreements", methods=["GET"])
def list_oas():
    require_auth(ALL_ROLES)
    items = list(DB["oas"].values())
    for f in ("lease_id", "building_id", "agency_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [o for o in items if o.get(f) == v]
    page, pagination = paginate(sorted_items(items))
    return success([pub(o) for o in page], 200, pagination)


@bp.route("/leasing/occupancy-agreements/<oid>/activate", methods=["POST"])
def activate_oa(oid):
    uid, role = require_auth(["AgencyManager"])
    oa = _get_oa(oid)
    agency_scope(uid, role, oa["agency_id"])
    if oa["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a DRAFT occupancy agreement can be activated")
    if oa.get("lease_id"):
        lease = DB["leases"][oa["lease_id"]]
        if lease["status"] not in ("COMMENCED", "EXPIRING"):
            raise ApiError("ERR_LEASE_NOT_COMMENCED", 409,
                           "A leased OA may activate only while its lease is COMMENCED or EXPIRING")
    oa["status"] = "ACTIVE"
    bump(oa)
    return success(pub(oa))


@bp.route("/leasing/occupancy-agreements/<oid>/terminate", methods=["POST"])
def terminate_oa(oid):
    require_auth(["GSALeasingOfficer"])
    oa = _get_oa(oid)
    if oa["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a DRAFT or ACTIVE occupancy agreement can be terminated")
    oa_terminal_cascade(oa, "TERMINATED")
    return success(pub(oa))


@bp.route("/leasing/occupancy-agreements/<oid>/amend", methods=["POST"])
def amend_oa(oid):
    require_auth(["GSALeasingOfficer"])
    oa = _get_oa(oid)
    b = body()
    # priority 5: shape
    if not is_int(b.get("expected_oa_version")):
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_oa_version is required")
    delta = b.get("delta_sf")
    if delta is None:
        delta = 0
    if not is_int(delta):
        raise ApiError("ERR_INVALID_REQUEST", 400, "delta_sf must be an integer")
    new_end = b.get("new_end_date")
    if new_end is not None and parse_date(new_end) is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "new_end_date must be an ISO date")
    new_shell = b.get("new_shell_equivalent_rate_per_sf_yr_cents")
    new_op = b.get("new_operating_rate_per_sf_yr_cents")
    if new_shell is not None and (not is_int(new_shell) or new_shell < 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "new_shell_equivalent_rate_per_sf_yr_cents must be >= 0")
    if new_op is not None and (not is_int(new_op) or new_op < 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "new_operating_rate_per_sf_yr_cents must be >= 0")
    note = b.get("note")
    # priority 7: OA must be ACTIVE
    if oa["status"] != "ACTIVE":
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "Only an ACTIVE occupancy agreement can be amended")
    # OCC: expected version must match
    if b["expected_oa_version"] != oa["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "The occupancy agreement's version has advanced; re-read and rebase")
    lease = DB["leases"].get(oa["lease_id"]) if oa.get("lease_id") else None
    # priority 10: leased OA end may not exceed the lease end
    if new_end is not None and lease is not None:
        if parse_date(new_end) > parse_date(lease["end_date"]):
            raise ApiError("ERR_OA_TERM_EXCEEDS_LEASE", 422, "new_end_date exceeds the lease's end_date")
    # priority 11: capacity re-check when growing the footprint
    if delta > 0:
        if oa.get("building_id"):
            bld = DB["buildings"][oa["building_id"]]
            if _committed_on_building(bld["id"]) + delta > bld["total_sf"]:
                raise ApiError("ERR_BUILDING_CAPACITY_EXCEEDED", 422, "Committed square footage would exceed total_sf")
        else:
            if _committed_on_lease(lease["id"]) + delta > lease["leased_sf"]:
                raise ApiError("ERR_LEASE_SPACE_EXCEEDED", 422, "Committed square footage would exceed the lease's leased_sf")
    old_sf = oa["assigned_sf"]
    oa["assigned_sf"] = old_sf + delta
    if new_end is not None:
        oa["end_date"] = new_end
    if oa.get("building_id"):
        if new_shell is not None:
            oa["shell_equivalent_rate_per_sf_yr_cents"] = new_shell
        if new_op is not None:
            oa["operating_rate_per_sf_yr_cents"] = new_op
    oa["amendment_history"].append({
        "amended_at": now_str(),
        "delta_sf": delta,
        "old_sf": old_sf,
        "new_sf": oa["assigned_sf"],
        "note": note,
    })
    bump(oa)
    if oa.get("building_id"):
        sync_building(DB["buildings"][oa["building_id"]])
    return success(pub(oa))
