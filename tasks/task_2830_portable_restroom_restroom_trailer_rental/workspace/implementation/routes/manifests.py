"""WasteManifest endpoints: opening, sealing and facility acceptance."""
from flask import Blueprint

from auth import ALL_ROLES, endpoint
import constants as C
from db import db, insert, ordered, serialize, touch
from errors import fail
from responses import created, ok
from routes.common import list_response, resolve
import services
import validation as V

bp = Blueprint("manifests", __name__)


@bp.post("/waste-manifests")
@endpoint(["DriverOperator"])
def create_manifest():
    body = V.body()
    route_id = V.str_field(body, "route_id", 1)
    disposal_site_id = V.str_field(body, "disposal_site_id", 1)
    manifest_date = V.date_field(body, "manifest_date")
    waste_class = V.enum_field(body, "waste_class", C.WASTE_CLASSES)

    route = resolve("routes", route_id)
    disposal_site = resolve("disposal_sites", disposal_site_id)

    row = insert("waste_manifests", {
        "route_id": route["id"],
        "disposal_site_id": disposal_site["id"],
        "manifest_date": manifest_date,
        "waste_class": waste_class,
        "gallons_total": services.manifest_rollup(route["id"], manifest_date),
        "state": "OPEN",
    })
    return created(serialize(row))


@bp.get("/waste-manifests/<manifest_id>")
@endpoint(ALL_ROLES)
def read_manifest(manifest_id):
    return ok(serialize(resolve("waste_manifests", manifest_id)))


@bp.get("/waste-manifests")
@endpoint(ALL_ROLES)
def list_manifests():
    limit, offset = V.pagination()
    route_id = V.q_str("route_id")
    disposal_site_id = V.q_str("disposal_site_id")
    state = V.q_enum("state", C.MANIFEST_STATES)
    manifest_date = V.q_date("manifest_date")
    rows = ordered(db.waste_manifests.values())
    if route_id is not None:
        rows = [r for r in rows if r["route_id"] == route_id]
    if disposal_site_id is not None:
        rows = [r for r in rows if r["disposal_site_id"] == disposal_site_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if manifest_date is not None:
        rows = [r for r in rows if r["manifest_date"] == manifest_date]
    return list_response(rows, limit, offset)


@bp.post("/waste-manifests/<manifest_id>/seal")
@endpoint(["DriverOperator"])
def seal_manifest(manifest_id):
    body = V.body()
    expected_route_version = V.int_field(body, "expected_route_version", 0)
    V.str_field(body, "seal_note", 1, None, required=False)
    manifest = resolve("waste_manifests", manifest_id)
    route = db.routes.get(manifest["route_id"])
    disposal_site = db.disposal_sites.get(manifest["disposal_site_id"])

    if route is None or expected_route_version != route["version"]:
        fail("ERR_STALE_ROUTE_VERSION")
    if manifest["state"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION")
    if disposal_site is not None and disposal_site["status"] != "ACCEPTING":
        fail("ERR_DISPOSAL_SITE_CLOSED")
    if (disposal_site is not None
            and manifest["waste_class"] not in disposal_site["accepted_waste_classes"]):
        fail("ERR_DISPOSAL_CLASS_NOT_ACCEPTED")
    if not services.serviced_visits(manifest["route_id"], manifest["manifest_date"]):
        fail("ERR_MANIFEST_NO_SERVICED_VISITS")

    gallons_total = services.manifest_rollup(manifest["route_id"],
                                             manifest["manifest_date"])
    if disposal_site is not None:
        already = services.committed_for_date(
            disposal_site["id"], manifest["manifest_date"],
            exclude_manifest_id=manifest["id"])
        if already + gallons_total > disposal_site["daily_gallon_cap"]:
            fail("ERR_DISPOSAL_CAP_EXCEEDED")

    manifest["gallons_total"] = gallons_total
    manifest["state"] = "SEALED"
    touch(manifest)
    if disposal_site is not None:
        services.recompute_committed_gallons_today(disposal_site)
    touch(route)
    return ok(serialize(manifest))


@bp.post("/waste-manifests/<manifest_id>/accept")
@endpoint(["ComplianceOfficer"])
def accept_manifest(manifest_id):
    body = V.body()
    V.str_field(body, "acceptance_note", 1, None, required=False)
    manifest = resolve("waste_manifests", manifest_id)
    disposal_site = db.disposal_sites.get(manifest["disposal_site_id"])

    if manifest["state"] != "SEALED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if disposal_site is not None and disposal_site["status"] != "ACCEPTING":
        fail("ERR_DISPOSAL_SITE_CLOSED")

    manifest["state"] = "ACCEPTED"
    touch(manifest)
    if disposal_site is not None:
        services.recompute_committed_gallons_today(disposal_site)
    return ok(serialize(manifest))
