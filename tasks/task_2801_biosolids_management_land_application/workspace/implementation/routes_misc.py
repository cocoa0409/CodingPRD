"""Flat audit-row readers, the logical clock and weather observations."""

from flask import Blueprint

import store
from auth import roles
from derive import derive_site_odor, derive_weather_clearance
from envelope import object_response
from errors import fail
from listing import emit_list
from store import ANALYTES, iso, now_iso, parse_dt, public, touch
from validate import (get_body, present, qbool, qint, qstr, resolve_fks, vbool,
                      vdt, vnum)

bp = Blueprint("misc", __name__, url_prefix="/api/v1")

RESULT_READ_ROLES = ("LabAnalyst", "ComplianceOfficer", "FacilityOperator",
                     "Agronomist")
TICKET_READ_ROLES = ("FacilityOperator", "ComplianceOfficer", "Agronomist")
LEDGER_READ_ROLES = ("Agronomist", "ComplianceOfficer", "FacilityOperator")
ALL_ROLES = ("FacilityOperator", "ComplianceOfficer", "Agronomist", "LabAnalyst",
             "Farmer", "PublicLiaison")
ENTRY_TYPES = ("APPLICATION", "REVERSAL")


# --- laboratory results ----------------------------------------------------

@bp.get("/lab-results/<result_id>")
@roles(*RESULT_READ_ROLES)
def read_lab_result(result_id):
    result = store.lab_results.get(result_id)
    if result is None:
        fail("ERR_LAB_RESULT_NOT_FOUND",
             "Laboratory result %s does not exist." % result_id)
    return object_response(public(result))


@bp.get("/lab-results")
@roles(*RESULT_READ_ROLES)
def list_lab_results():
    batch_id = qstr("batch_id")
    analyte = qstr("analyte")
    sampling_event_index = qint("sampling_event_index")
    exceeds_ceiling = qbool("exceeds_ceiling")
    rows = [r for r in store.lab_results.values()
            if (batch_id is None or r["batch_id"] == batch_id)
            and (analyte is None or r["analyte"] == analyte)
            and (sampling_event_index is None
                 or r["sampling_event_index"] == sampling_event_index)
            and (exceeds_ceiling is None
                 or r["exceeds_ceiling"] is exceeds_ceiling)]
    return emit_list(rows, ("created_at",))


# --- haul tickets ----------------------------------------------------------

@bp.get("/haul-tickets/<ticket_id>")
@roles(*TICKET_READ_ROLES)
def read_haul_ticket(ticket_id):
    ticket = store.haul_tickets.get(ticket_id)
    if ticket is None:
        fail("ERR_HAUL_TICKET_NOT_FOUND",
             "Haul ticket %s does not exist." % ticket_id)
    return object_response(public(ticket))


@bp.get("/haul-tickets")
@roles(*TICKET_READ_ROLES)
def list_haul_tickets():
    event_id = qstr("event_id")
    truck_id = qstr("truck_id")
    rows = [t for t in store.haul_tickets.values()
            if (event_id is None or t["event_id"] == event_id)
            and (truck_id is None or t["truck_id"] == truck_id)]
    return emit_list(rows, ("depart_at", "created_at"))


# --- loading ledger --------------------------------------------------------

@bp.get("/loading-ledger-entries/<entry_id>")
@roles(*LEDGER_READ_ROLES)
def read_ledger_entry(entry_id):
    entry = store.ledger.get(entry_id)
    if entry is None:
        fail("ERR_LEDGER_ENTRY_NOT_FOUND",
             "Loading ledger entry %s does not exist." % entry_id)
    return object_response(public(entry))


@bp.get("/loading-ledger-entries")
@roles(*LEDGER_READ_ROLES)
def list_ledger_entries():
    site_id = qstr("site_id")
    source_event_id = qstr("source_event_id")
    reversal_of_id = qstr("reversal_of_id")
    analyte = qstr("analyte")
    applied_year = qint("applied_year")
    entry_type = qstr("entry_type")
    rows = [e for e in store.ledger.values()
            if (site_id is None or e["site_id"] == site_id)
            and (source_event_id is None or e["source_event_id"] == source_event_id)
            and (reversal_of_id is None or e["reversal_of_id"] == reversal_of_id)
            and (analyte is None or e["analyte"] == analyte)
            and (applied_year is None or e["applied_year"] == applied_year)
            and (entry_type is None or e["entry_type"] == entry_type)]
    return emit_list(rows, ("created_at",))


# --- logical clock ---------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@roles(*ALL_ROLES)
def set_clock():
    body = get_body()
    moment = vdt(body, "now", required=True)
    store.set_clock(moment)
    expired = 0
    agreements = sorted(store.agreements.values(),
                        key=lambda a: (a["created_at"], a["_seq"]))
    for agreement in agreements:
        if agreement["status"] != "ACTIVE":
            continue
        term_end = parse_dt(agreement["term_end"])
        if term_end is not None and term_end <= moment:
            agreement["status"] = "EXPIRED"
            touch(agreement)
            expired += 1
    for site in store.sites.values():
        derive_site_odor(site)
    return object_response({"now": iso(moment), "expired_agreement_count": expired})


# --- weather observations --------------------------------------------------

@bp.post("/_weather/observations")
@roles("FacilityOperator", "Agronomist", "ComplianceOfficer")
def post_weather_observation():
    body = get_body()
    fks = resolve_fks(body, ("site_id",))
    site_id = body.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        fail("ERR_INVALID_REQUEST", "Field 'site_id' is required.")
    site = fks["site_id"]
    rainfall = vnum(body, "rainfall_in_24h", required=True)
    forecast = vnum(body, "forecast_rainfall_in_48h", required=True)
    frozen = vbool(body, "frozen_ground", required=True)
    observed_at = vdt(body, "observed_at", required=False, default=None)
    site["latest_rainfall_in_24h"] = rainfall
    site["latest_forecast_rainfall_in_48h"] = forecast
    site["latest_frozen_ground"] = frozen
    site["latest_weather_observed_at"] = (iso(observed_at) if observed_at is not None
                                          else now_iso())
    derive_weather_clearance(site)
    touch(site)
    return object_response(public(site))
