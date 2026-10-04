"""Field boundaries and the prescription workflow (PRD section 3.3)."""

from flask import Blueprint, request

from auth import (
    as_date,
    as_dt,
    as_enum,
    as_int,
    as_num,
    as_str,
    as_zones,
    body_json,
    caller,
    can_see_scope,
    find_active_grant,
    get_or_404,
    list_resources,
    need,
    require_role,
    scoped_gate,
    access_denied,
)
from db import STORES, now
from domain import compute_prescription_totals, new_record, serialize, touch
from envelope import created, ok, ok_list
from errors import (
    ERR_FEATURE_NOT_LICENSED,
    ERR_FIELD_HAS_OPEN_PRESCRIPTIONS,
    ERR_FIELD_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
    ERR_MACHINE_POSTURE_BLOCKED,
    ERR_ORG_SUSPENDED,
    ERR_PRESCRIPTION_EXPIRED,
    ERR_STALE_FIELD_BOUNDARY_VERSION,
    ApiError,
    invalid_state,
)

bp = Blueprint("agronomy", __name__)

FIELD_READ_ROLES = {"GrowerManager", "Agronomist", "CoopAnalyst", "PartnerApp", "PlatformAdmin"}
CROP_TYPES = {"CORN", "SOY", "WHEAT", "COTTON"}


# ---------------------------------------------------------------------------
# Field boundaries
# ---------------------------------------------------------------------------

@bp.post("/field-boundaries")
def create_field():
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    b = body_json()
    organization_id = as_str(need(b, "organization_id"), "organization_id")
    name = as_str(need(b, "name"), "name")
    season_year = as_int(need(b, "season_year"), "season_year")
    area_hectares = as_num(need(b, "area_hectares"), "area_hectares")
    get_or_404("organizations", organization_id, "organization")
    if uid != organization_id:
        raise access_denied("grower may create fields only for its own organization")
    rec = new_record(
        {
            "organization_id": organization_id,
            "name": name,
            "season_year": season_year,
            "area_hectares": area_hectares,
            "status": "DRAFT",
        }
    )
    STORES["field_boundaries"][rec["id"]] = rec
    return created(serialize(rec))


@bp.get("/field-boundaries/<fid>")
def get_field(fid):
    uid, role = caller()
    require_role(role, FIELD_READ_ROLES)
    f = get_or_404("field_boundaries", fid, "field boundary")
    scoped_gate(f["organization_id"], role, uid, "AGRONOMIC")
    return ok(serialize(f))


@bp.get("/field-boundaries")
def list_fields():
    uid, role = caller()
    require_role(role, FIELD_READ_ROLES)
    org_filter = request.args.get("organization_id")
    filters = []
    for f in ("organization_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "PlatformAdmin":
        visible = lambda r: True
    elif role == "GrowerManager":
        if org_filter is not None and org_filter != uid:
            raise access_denied("grower may list only its own organization")
        visible = lambda r: r["organization_id"] == uid
    else:
        if org_filter is not None and not can_see_scope(org_filter, role, uid, "AGRONOMIC"):
            raise access_denied("no AGRONOMIC grant on the requested organization")
        visible = lambda r: can_see_scope(r["organization_id"], role, uid, "AGRONOMIC")
    page, total, limit, offset = list_resources("field_boundaries", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/field-boundaries/<fid>/activate")
def activate_field(fid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    f = get_or_404("field_boundaries", fid, "field boundary")
    if uid != f["organization_id"]:
        raise access_denied("field belongs to another organization")
    if f["status"] != "DRAFT":
        raise invalid_state("field boundary is not DRAFT")
    f["status"] = "ACTIVE"
    touch(f)
    return ok(serialize(f))


@bp.post("/field-boundaries/<fid>/archive")
def archive_field(fid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    f = get_or_404("field_boundaries", fid, "field boundary")
    if uid != f["organization_id"]:
        raise access_denied("field belongs to another organization")
    if f["status"] != "ACTIVE":
        raise invalid_state("field boundary is not ACTIVE")
    for p in STORES["prescriptions"].values():
        if p["field_boundary_id"] == fid and p["status"] in ("DRAFT", "APPROVED", "SENT"):
            raise ApiError(
                ERR_FIELD_HAS_OPEN_PRESCRIPTIONS,
                409,
                "field has prescriptions in DRAFT, APPROVED or SENT",
            )
    f["status"] = "ARCHIVED"
    touch(f)
    return ok(serialize(f))


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------

def _prescription_write_gate(rec, role, uid):
    """GrowerManager owns the organization; an Agronomist needs an ACTIVE
    AGRONOMIC grant on it."""
    if role == "GrowerManager":
        if uid != rec["organization_id"]:
            raise access_denied("prescription belongs to another organization")
    elif role == "Agronomist":
        if find_active_grant(rec["organization_id"], role, uid, "AGRONOMIC") is None:
            raise access_denied("agronomist lacks an AGRONOMIC grant on the organization")


@bp.post("/prescriptions")
def create_prescription():
    uid, role = caller()
    require_role(role, {"GrowerManager", "Agronomist"})
    b = body_json()
    organization_id = as_str(need(b, "organization_id"), "organization_id")
    field_boundary_id = as_str(need(b, "field_boundary_id"), "field_boundary_id")
    machine_id = as_str(need(b, "machine_id"), "machine_id")
    crop_type = as_enum(need(b, "crop_type"), "crop_type", CROP_TYPES)
    zones = as_zones(need(b, "zones"))
    valid_from = as_dt(need(b, "valid_from"), "valid_from")
    valid_until = as_dt(need(b, "valid_until"), "valid_until")
    expected_field_boundary_version = as_int(
        need(b, "expected_field_boundary_version"), "expected_field_boundary_version"
    )
    if not valid_from < valid_until:
        raise ApiError(ERR_INVALID_REQUEST, 400, "valid_from must precede valid_until")
    # Existence: body foreign keys in declared input order
    get_or_404("organizations", organization_id, "organization")
    field = get_or_404("field_boundaries", field_boundary_id, "field boundary")
    machine = get_or_404("machines", machine_id, "machine")
    # Scope gate
    if role == "GrowerManager":
        if uid != organization_id:
            raise access_denied("grower may create prescriptions only for its own organization")
    else:
        if find_active_grant(organization_id, role, uid, "AGRONOMIC") is None:
            raise access_denied("agronomist lacks an AGRONOMIC grant on the organization")
    # State: only ACTIVE fields accept new prescriptions
    if field["status"] != "ACTIVE":
        raise ApiError(ERR_FIELD_NOT_ACTIVE, 409, "field boundary is not ACTIVE")
    # Cross-references must agree
    if field["organization_id"] != organization_id or machine["organization_id"] != organization_id:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "prescription organization must equal the field's and the machine's organization",
        )
    # Optimistic concurrency last, after every domain rule has passed
    if expected_field_boundary_version != field["version"]:
        raise ApiError(ERR_STALE_FIELD_BOUNDARY_VERSION, 412, "field boundary version is stale")
    total, avg = compute_prescription_totals(zones)
    rec = new_record(
        {
            "organization_id": organization_id,
            "field_boundary_id": field_boundary_id,
            "machine_id": machine_id,
            "crop_type": crop_type,
            "zones": zones,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "status": "DRAFT",
            "revision": 1,
            "total_product_liters": total,
            "weighted_avg_rate_l_per_ha": avg,
            "superseded_by_id": None,
            "applied_total_liters": None,
            "applied_coverage_ha": None,
            "applied_at": None,
        }
    )
    STORES["prescriptions"][rec["id"]] = rec
    # The prescription attaches to a specific field snapshot
    touch(field)
    return created(serialize(rec))


@bp.get("/prescriptions/<pid>")
def get_prescription(pid):
    uid, role = caller()
    require_role(role, FIELD_READ_ROLES)
    r = get_or_404("prescriptions", pid, "prescription")
    scoped_gate(r["organization_id"], role, uid, "AGRONOMIC")
    return ok(serialize(r))


@bp.get("/prescriptions")
def list_prescriptions():
    uid, role = caller()
    require_role(role, FIELD_READ_ROLES)
    org_filter = request.args.get("organization_id")
    filters = []
    for f in ("organization_id", "field_boundary_id", "machine_id", "status", "superseded_by_id"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "PlatformAdmin":
        visible = lambda r: True
    elif role == "GrowerManager":
        if org_filter is not None and org_filter != uid:
            raise access_denied("grower may list only its own organization")
        visible = lambda r: r["organization_id"] == uid
    else:
        if org_filter is not None and not can_see_scope(org_filter, role, uid, "AGRONOMIC"):
            raise access_denied("no AGRONOMIC grant on the requested organization")
        visible = lambda r: can_see_scope(r["organization_id"], role, uid, "AGRONOMIC")
    page, total, limit, offset = list_resources("prescriptions", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/prescriptions/<pid>/approve")
def approve_prescription(pid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    r = get_or_404("prescriptions", pid, "prescription")
    _prescription_write_gate(r, role, uid)
    if r["status"] != "DRAFT":
        raise invalid_state("prescription is not DRAFT")
    r["status"] = "APPROVED"
    touch(r)
    return ok(serialize(r))


@bp.post("/prescriptions/<pid>/revise")
def revise_prescription(pid):
    uid, role = caller()
    require_role(role, {"GrowerManager", "Agronomist"})
    r = get_or_404("prescriptions", pid, "prescription")
    _prescription_write_gate(r, role, uid)
    if r["status"] != "APPROVED":
        raise invalid_state("prescription is not APPROVED")
    r["status"] = "DRAFT"
    r["revision"] += 1
    touch(r)
    return ok(serialize(r))


@bp.post("/prescriptions/<pid>/send-to-machine")
def send_prescription(pid):
    uid, role = caller()
    require_role(role, {"GrowerManager", "Agronomist"})
    r = get_or_404("prescriptions", pid, "prescription")
    _prescription_write_gate(r, role, uid)
    if r["status"] != "APPROVED":
        raise invalid_state("prescription is not APPROVED")
    org = STORES["organizations"].get(r["organization_id"])
    if org is None or org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, 409, "owning organization is SUSPENDED")
    machine = STORES["machines"].get(r["machine_id"])
    if machine is None or machine["connectivity_posture"] != "CONNECTED":
        raise ApiError(ERR_MACHINE_POSTURE_BLOCKED, 409, "machine posture is not CONNECTED")
    # Capacity gate (priority 8) precedes the temporal window (priority 10)
    if len(r["zones"]) > 1:
        licensed = any(
            lic["machine_id"] == r["machine_id"]
            and lic["feature_code"] == "SECTION_CONTROL"
            and lic["status"] == "ACTIVATED"
            for lic in STORES["feature_licenses"].values()
        )
        if not licensed:
            raise ApiError(
                ERR_FEATURE_NOT_LICENSED,
                409,
                "multi-zone send requires an ACTIVATED SECTION_CONTROL license",
            )
    if now() > r["valid_until"]:
        raise ApiError(ERR_PRESCRIPTION_EXPIRED, 409, "prescription validity window has passed")
    r["status"] = "SENT"
    touch(r)
    # Supersede every other SENT prescription of the same field
    for other in STORES["prescriptions"].values():
        if (
            other["field_boundary_id"] == r["field_boundary_id"]
            and other["id"] != r["id"]
            and other["status"] == "SENT"
        ):
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = r["id"]
            touch(other)
    return ok(serialize(r))


@bp.post("/prescriptions/<pid>/report-as-applied")
def report_as_applied(pid):
    uid, role = caller()
    require_role(role, {"System"})
    b = body_json()
    applied_total_liters = as_num(need(b, "applied_total_liters"), "applied_total_liters")
    applied_coverage_ha = as_num(need(b, "applied_coverage_ha"), "applied_coverage_ha")
    r = get_or_404("prescriptions", pid, "prescription")
    if r["status"] != "SENT":
        raise invalid_state("prescription is not SENT")
    r["status"] = "ACKNOWLEDGED"
    r["applied_total_liters"] = applied_total_liters
    r["applied_coverage_ha"] = applied_coverage_ha
    r["applied_at"] = now()
    touch(r)
    return ok(serialize(r))
