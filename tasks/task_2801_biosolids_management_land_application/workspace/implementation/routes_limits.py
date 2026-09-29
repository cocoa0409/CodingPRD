"""Pollutant limit endpoints (PRD 2.12)."""

from flask import Blueprint

import store
from auth import roles
from envelope import object_response
from errors import fail
from listing import emit_list
from store import ANALYTES, now_iso, public, touch
from validate import get_body, qenum, venum, vnum

bp = Blueprint("limits", __name__, url_prefix="/api/v1/pollutant-limits")

LIMIT_STATUSES = ("ACTIVE", "SUPERSEDED")
READ_ROLES = ("ComplianceOfficer", "LabAnalyst", "Agronomist", "FacilityOperator",
              "PublicLiaison")


@bp.post("")
@roles("ComplianceOfficer")
def create_limit():
    body = get_body()
    analyte = venum(body, "analyte", ANALYTES, required=True)
    ceiling = vnum(body, "ceiling_mg_kg", required=True, ge=0)
    monthly = vnum(body, "monthly_avg_mg_kg", required=False, default=None, ge=0,
                   nullable=True)
    aplr = vnum(body, "aplr_kg_per_hectare_yr", required=False, default=None, ge=0,
                nullable=True)
    cplr = vnum(body, "cplr_kg_per_hectare", required=False, default=None, ge=0,
                nullable=True)
    advisory = vnum(body, "advisory_threshold_mg_kg", required=False, default=None, ge=0,
                    nullable=True)
    for existing in store.limits.values():
        if existing["analyte"] == analyte and existing["status"] == "ACTIVE":
            existing["status"] = "SUPERSEDED"
            touch(existing)
    row = store.new_record({
        "analyte": analyte,
        "ceiling_mg_kg": ceiling,
        "monthly_avg_mg_kg": monthly,
        "aplr_kg_per_hectare_yr": aplr,
        "cplr_kg_per_hectare": cplr,
        "advisory_threshold_mg_kg": advisory,
        "status": "ACTIVE",
        "updated_at": now_iso(),
        "version": 1,
    })
    store.limits[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/<limit_id>")
@roles(*READ_ROLES)
def read_limit(limit_id):
    row = store.limits.get(limit_id)
    if row is None:
        fail("ERR_LIMIT_NOT_FOUND", "Pollutant limit %s does not exist." % limit_id)
    return object_response(public(row))


@bp.get("")
@roles(*READ_ROLES)
def list_limits():
    analyte = qenum("analyte", ANALYTES)
    status = qenum("status", LIMIT_STATUSES)
    rows = [r for r in store.limits.values()
            if (analyte is None or r["analyte"] == analyte)
            and (status is None or r["status"] == status)]
    return emit_list(rows, ("analyte", "created_at"))
