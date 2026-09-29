"""Application event endpoints (PRD 3.7 - 3.9)."""

from decimal import Decimal

from flask import Blueprint, g

import store
from auth import roles
from calc import (SENTINEL_RATE, loading_delta, per_unit_loading, plant_available_n)
from derive import (active_limits, annual_loading, cplr_all_below_trigger,
                    cplr_trigger_reached, cumulative_loading, current_round_results,
                    defer_pre_field_events, derive_site_odor, events_of_site,
                    facility_of_site, recompute_batch_balance, recompute_site_loading,
                    refresh_facility_storage)
from envelope import object_response
from errors import fail
from listing import emit_list
from store import (D, days, iso, now, now_iso, parse_dt, public, r2, r3, r4, touch)
from validate import (get_body, present, qenum, qstr, resolve_fks, vdt, venum, vnum,
                      vstr)

bp = Blueprint("events", __name__, url_prefix="/api/v1/application-events")

APPLICATION_METHODS = ("SURFACE", "INCORPORATED", "INJECTED")
EVENT_STATUSES = ("SCHEDULED", "WEATHER_HOLD", "DEFERRED", "IN_PROGRESS", "COMPLETED",
                  "CANCELLED", "VOIDED")
HOLD_REASONS = ("RAINFALL_24H", "FORECAST_48H", "FROZEN_GROUND", "OPERATOR_JUDGEMENT",
                "CLEARED")
PRE_FIELD = ("SCHEDULED", "WEATHER_HOLD", "DEFERRED")
BLOCKING_STATUSES = ("SCHEDULED", "WEATHER_HOLD", "DEFERRED", "IN_PROGRESS")
READ_ROLES = ("Agronomist", "ComplianceOfficer", "FacilityOperator", "Farmer")


def get_event(event_id):
    event = store.events.get(event_id)
    if event is None:
        fail("ERR_EVENT_NOT_FOUND", "Application event %s does not exist." % event_id)
    return event


def _site_of(event):
    return store.sites.get(event["site_id"])


def _batch_of(event):
    return store.batches.get(event["batch_id"])


def _agreement_of(event):
    return store.agreements.get(event["agreement_id"])


# --- screening helpers -----------------------------------------------------


def check_site_permitted(site):
    if site["status"] != "PERMITTED":
        fail("ERR_SITE_NOT_PERMITTED", "The site is not PERMITTED.")


def check_agreement_active(agreement):
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE", "The agreement is not ACTIVE.")


def check_batch_qualified(batch):
    if batch["quality_status"] != "QUALIFIED":
        fail("ERR_BATCH_NOT_QUALIFIED", "The batch quality_status is not QUALIFIED.")


def check_site_not_restricted(site):
    if site["status"] == "RESTRICTED":
        fail("ERR_SITE_RESTRICTED", "The site is RESTRICTED.")


def check_setbacks(site, application_method):
    water = D(site["setback_to_surface_water_ft"])
    if application_method == "SURFACE":
        if water < Decimal(100) or D(site["slope_pct"]) > Decimal("15.0"):
            fail("ERR_SETBACK_VIOLATION",
                 "Surface application setback or slope requirement failed.")
    elif application_method == "INCORPORATED":
        if water < Decimal(66):
            fail("ERR_SETBACK_VIOLATION",
                 "Incorporated application setback requirement failed.")
    else:
        if water < Decimal(33):
            fail("ERR_SETBACK_VIOLATION",
                 "Injected application setback requirement failed.")
    if D(site["setback_to_well_ft"]) < Decimal(100):
        fail("ERR_SETBACK_VIOLATION", "The well setback requirement failed.")


def check_odor_gate(site):
    if not D(site["gating_risk_score"]) < Decimal("60.00"):
        fail("ERR_ODOR_RISK_BLOCK", "gating_risk_score is at or above 60.00.")


def check_phosphorus(site):
    if not D(site["soil_p_index"]) < Decimal(100):
        fail("ERR_PHOSPHORUS_INDEX_BLOCK", "soil_p_index is at or above 100.")


def check_window_overlap(site, window_start, window_end, exclude_event_id=None):
    for other in events_of_site(site["id"]):
        if exclude_event_id is not None and other["id"] == exclude_event_id:
            continue
        if other["status"] not in BLOCKING_STATUSES:
            continue
        other_start = parse_dt(other["window_start"])
        other_end = parse_dt(other["window_end"])
        if window_start < other_end and other_start < window_end:
            fail("ERR_SITE_WINDOW_CONFLICT",
                 "The requested window overlaps another application event.")


def check_reapplication(site, window_start, exclude_event_id=None):
    latest_end = None
    for other in events_of_site(site["id"]):
        if exclude_event_id is not None and other["id"] == exclude_event_id:
            continue
        if other["status"] != "COMPLETED":
            continue
        end = parse_dt(other["window_end"])
        if end is not None and (latest_end is None or end > latest_end):
            latest_end = end
    if latest_end is None:
        return
    threshold = latest_end + days(int(site["reapplication_interval_days"]))
    if window_start < threshold:
        fail("ERR_REAPPLICATION_INTERVAL",
             "The reapplication interval for this site has not elapsed.")


def check_term_coverage(agreement, window_start, window_end):
    term_start = parse_dt(agreement["term_start"])
    term_end = parse_dt(agreement["term_end"])
    if window_start < term_start or window_end > term_end:
        fail("ERR_AGREEMENT_TERM_COVERAGE",
             "The application window is not covered by the agreement term.")


def check_crop_cycle(site, window_start):
    if window_start.month not in site["allowed_application_months"]:
        fail("ERR_CROP_CYCLE_CONFLICT",
             "The window month is not an allowed application month.")


def check_notice(agreement, window_start):
    threshold = now() + days(int(agreement["notice_days"]))
    if window_start < threshold:
        fail("ERR_NOTICE_PERIOD_NOT_MET", "The notice period has not been satisfied.")


def check_acreage(site, acres_treated):
    if not (acres_treated > 0 and acres_treated <= D(site["acres"])):
        fail("ERR_ACRES_EXCEED_SITE", "acres_treated exceeds the site acreage.")


def derive_rate_fields(site, batch, agreement, application_method, acres_treated,
                       planned_dry_tons, window_start):
    """PRD 3.7 steps 1-7. Returns the four pinned rate fields."""
    pan = plant_available_n(batch, application_method)
    if not pan > 0:
        fail("ERR_AGRONOMIC_RATE_UNDEFINED",
             "plant_available_n_lb_per_dry_ton is not strictly greater than 0.")

    nitrogen = D(site["crop_n_demand_lb_per_acre"]) / pan

    soil_p_index = D(site["soil_p_index"])
    if soil_p_index >= Decimal(75):
        denom = D(batch["total_p_mg_kg"]) * Decimal("0.002")
        phosphorus = (D(site["crop_p_removal_lb_per_acre"]) / denom
                      if denom != 0 else SENTINEL_RATE)
    else:
        phosphorus = SENTINEL_RATE

    limits = active_limits()
    results = {r["analyte"]: r for r in current_round_results(batch)}
    year = window_start.year
    aplr_candidates = []
    for analyte in sorted(limits):
        aplr = limits[analyte].get("aplr_kg_per_hectare_yr")
        if aplr is None or analyte not in results:
            continue
        unit = per_unit_loading(results[analyte]["concentration_mg_kg"])
        if unit == 0:
            continue
        headroom = D(aplr) - annual_loading(site, year, analyte)
        aplr_candidates.append(headroom / unit)
    aplr_rate = min(aplr_candidates) if aplr_candidates else SENTINEL_RATE

    agreement_rate = D(agreement["max_dry_tons_per_acre"])

    candidates = [("NITROGEN", nitrogen), ("PHOSPHORUS", phosphorus),
                  ("APLR", aplr_rate), ("AGREEMENT", agreement_rate)]
    minimum = min(value for _, value in candidates)
    binding = next(name for name, value in candidates if value == minimum)
    cap = r2(minimum)
    requested = r2(D(planned_dry_tons) / D(acres_treated))
    if requested > cap:
        fail("ERR_AGRONOMIC_RATE_EXCEEDED",
             "requested_rate_dry_tons_per_acre exceeds the agronomic rate cap.")
    return pan, cap, binding, requested


def screen_loading(site, batch, requested_rate, year):
    limits = active_limits()
    results = {r["analyte"]: r for r in current_round_results(batch)}
    increments = {}
    for analyte in sorted(results):
        increments[analyte] = loading_delta(requested_rate,
                                            results[analyte]["concentration_mg_kg"])
    for analyte in sorted(results):
        limit = limits.get(analyte)
        if limit is None:
            continue
        cplr = limit.get("cplr_kg_per_hectare")
        if cplr is None:
            continue
        projected = cumulative_loading(site, analyte) + increments[analyte]
        if projected > D(cplr):
            fail("ERR_CPLR_HEADROOM_EXCEEDED",
                 "Projected cumulative loading for %s exceeds its CPLR." % analyte)
    for analyte in sorted(results):
        limit = limits.get(analyte)
        if limit is None:
            continue
        aplr = limit.get("aplr_kg_per_hectare_yr")
        if aplr is None:
            continue
        projected = annual_loading(site, year, analyte) + increments[analyte]
        if projected > D(aplr):
            fail("ERR_APLR_EXCEEDED",
                 "Projected annual loading for %s exceeds its APLR." % analyte)


def planned_wet_from_dry(batch, planned_dry_tons):
    percent_solids = D(batch["percent_solids"])
    if percent_solids == 0:
        return r2(0)
    return r2(D(planned_dry_tons) / (percent_solids / Decimal(100)))


@bp.post("")
@roles("Agronomist")
def create_event():
    body = get_body()
    fks = resolve_fks(body, ("site_id", "batch_id", "agreement_id"))
    for key in ("site_id", "batch_id", "agreement_id"):
        value = body.get(key)
        if not isinstance(value, str) or not value.strip():
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    site = fks["site_id"]
    batch = fks["batch_id"]
    agreement = fks["agreement_id"]
    window_start = vdt(body, "window_start", required=True)
    window_end = vdt(body, "window_end", required=True)
    if not window_end > window_start:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")
    application_method = venum(body, "application_method", APPLICATION_METHODS,
                               required=True)
    acres_treated = vnum(body, "acres_treated", required=True, gt=0)
    planned_dry_tons = vnum(body, "planned_dry_tons", required=True, gt=0)
    incorporation = vnum(body, "incorporation_within_hours", required=False,
                         default=None, ge=0, nullable=True)
    acres_treated = r2(acres_treated)
    planned_dry_tons = r3(planned_dry_tons)

    check_site_permitted(site)
    check_agreement_active(agreement)
    check_batch_qualified(batch)
    facility = facility_of_site(site)
    if facility is not None and facility["posture"] == "FROZEN":
        fail("ERR_FACILITY_FROZEN", "Facility posture is FROZEN.")
    if facility is not None and facility["posture"] == "RESTRICTED":
        if window_start > now() + days(7):
            fail("ERR_FACILITY_RESTRICTED",
                 "A RESTRICTED facility accepts only windows within 7 days.")
    check_site_not_restricted(site)
    check_setbacks(site, application_method)
    check_odor_gate(site)
    check_phosphorus(site)
    check_window_overlap(site, window_start, window_end)
    check_reapplication(site, window_start)
    if agreement["site_id"] != site["id"]:
        fail("ERR_AGREEMENT_SITE_MISMATCH", "The agreement does not cover this site.")
    check_term_coverage(agreement, window_start, window_end)
    check_crop_cycle(site, window_start)
    check_notice(agreement, window_start)
    check_acreage(site, acres_treated)
    pan, cap, binding, requested = derive_rate_fields(
        site, batch, agreement, application_method, acres_treated, planned_dry_tons,
        window_start)
    screen_loading(site, batch, requested, window_start.year)
    if planned_dry_tons > D(batch["unallocated_dry_tons"]):
        fail("ERR_INSUFFICIENT_UNALLOCATED_TONS",
             "planned_dry_tons exceeds the batch unallocated_dry_tons.")

    event = store.new_record({
        "site_id": site["id"],
        "batch_id": batch["id"],
        "agreement_id": agreement["id"],
        "window_start": iso(window_start),
        "window_end": iso(window_end),
        "application_method": application_method,
        "acres_treated": acres_treated,
        "planned_dry_tons": planned_dry_tons,
        "planned_wet_tons": planned_wet_from_dry(batch, planned_dry_tons),
        "incorporation_within_hours": incorporation,
        "status": "SCHEDULED",
        "reserved_dry_tons": planned_dry_tons,
        "applied_dry_tons": r3(0),
        "applied_wet_tons": r2(0),
        "requested_rate_dry_tons_per_acre": requested,
        "plant_available_n_lb_per_dry_ton": pan,
        "agronomic_rate_cap_dry_tons_per_acre": cap,
        "binding_rate_constraint": binding,
        "hold_reason": None,
        "defer_reason": None,
        "completed_by_user_id": None,
        "voided_at": None,
        "updated_at": now_iso(),
        "version": 1,
    })
    store.events[event["id"]] = event
    recompute_batch_balance(batch)
    touch(batch)
    return object_response(public(event), 201)


@bp.get("/<event_id>")
@roles(*READ_ROLES)
def read_event(event_id):
    return object_response(public(get_event(event_id)))


@bp.get("")
@roles(*READ_ROLES)
def list_events():
    site_id = qstr("site_id")
    batch_id = qstr("batch_id")
    agreement_id = qstr("agreement_id")
    status = qenum("status", EVENT_STATUSES)
    rows = [e for e in store.events.values()
            if (site_id is None or e["site_id"] == site_id)
            and (batch_id is None or e["batch_id"] == batch_id)
            and (agreement_id is None or e["agreement_id"] == agreement_id)
            and (status is None or e["status"] == status)]
    return emit_list(rows, ("window_start", "created_at"))


@bp.post("/<event_id>/reschedule")
@roles("Agronomist")
def reschedule_event(event_id):
    event = get_event(event_id)
    body = get_body()
    window_start = vdt(body, "window_start", required=True)
    window_end = vdt(body, "window_end", required=True)
    if not window_end > window_start:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")
    application_method = venum(body, "application_method", APPLICATION_METHODS,
                               required=False, default=event["application_method"])
    acres_treated = vnum(body, "acres_treated", required=False,
                         default=D(event["acres_treated"]), gt=0)
    planned_dry_tons = vnum(body, "planned_dry_tons", required=False,
                            default=D(event["planned_dry_tons"]), gt=0)
    incorporation_supplied = present(body, "incorporation_within_hours")
    incorporation = vnum(body, "incorporation_within_hours", required=False,
                         default=event["incorporation_within_hours"], ge=0,
                         nullable=True)
    acres_treated = r2(acres_treated)
    planned_dry_tons = r3(planned_dry_tons)

    if event["status"] not in PRE_FIELD:
        fail("ERR_EVENT_NOT_SCHEDULED",
             "Only a pre-field application event may be rescheduled.")
    site = _site_of(event)
    batch = _batch_of(event)
    agreement = _agreement_of(event)
    check_site_permitted(site)
    check_agreement_active(agreement)
    check_site_not_restricted(site)
    check_setbacks(site, application_method)
    check_odor_gate(site)
    check_phosphorus(site)
    check_window_overlap(site, window_start, window_end, exclude_event_id=event["id"])
    check_reapplication(site, window_start, exclude_event_id=event["id"])
    check_term_coverage(agreement, window_start, window_end)
    check_crop_cycle(site, window_start)
    check_notice(agreement, window_start)
    check_acreage(site, acres_treated)
    pan, cap, binding, requested = derive_rate_fields(
        site, batch, agreement, application_method, acres_treated, planned_dry_tons,
        window_start)
    screen_loading(site, batch, requested, window_start.year)
    previous_dry_tons = D(event["planned_dry_tons"])
    tonnage_changed = planned_dry_tons != previous_dry_tons
    if tonnage_changed:
        delta = planned_dry_tons - previous_dry_tons
        if delta > D(batch["unallocated_dry_tons"]):
            fail("ERR_INSUFFICIENT_UNALLOCATED_TONS",
                 "The additional planned_dry_tons exceeds the batch "
                 "unallocated_dry_tons.")

    event["window_start"] = iso(window_start)
    event["window_end"] = iso(window_end)
    event["application_method"] = application_method
    event["acres_treated"] = acres_treated
    event["planned_dry_tons"] = planned_dry_tons
    event["planned_wet_tons"] = planned_wet_from_dry(batch, planned_dry_tons)
    if incorporation_supplied:
        event["incorporation_within_hours"] = incorporation
    event["status"] = "SCHEDULED"
    event["hold_reason"] = None
    event["defer_reason"] = None
    event["reserved_dry_tons"] = planned_dry_tons
    event["requested_rate_dry_tons_per_acre"] = requested
    event["plant_available_n_lb_per_dry_ton"] = pan
    event["agronomic_rate_cap_dry_tons_per_acre"] = cap
    event["binding_rate_constraint"] = binding
    touch(event)
    if tonnage_changed:
        recompute_batch_balance(batch)
        touch(batch)
    return object_response(public(event))


@bp.post("/<event_id>/weather-hold")
@roles("Agronomist", "FacilityOperator")
def weather_hold(event_id):
    event = get_event(event_id)
    body = get_body()
    hold_reason = venum(body, "hold_reason", HOLD_REASONS, required=True)
    site = _site_of(event)
    if hold_reason == "CLEARED":
        if event["status"] != "WEATHER_HOLD":
            fail("ERR_EVENT_NOT_SCHEDULED",
                 "Only an event on WEATHER_HOLD may be cleared.")
        if not site["weather_clearance_ok"]:
            fail("ERR_WEATHER_RESTRICTION", "The site does not have weather clearance.")
        event["status"] = "SCHEDULED"
        event["hold_reason"] = None
    else:
        if event["status"] != "SCHEDULED":
            fail("ERR_EVENT_NOT_SCHEDULED",
                 "Only a SCHEDULED event may be placed on weather hold.")
        if hold_reason != "OPERATOR_JUDGEMENT" and site["weather_clearance_ok"]:
            fail("ERR_WEATHER_RESTRICTION",
                 "The site currently has weather clearance.")
        event["status"] = "WEATHER_HOLD"
        event["hold_reason"] = hold_reason
    touch(event)
    return object_response(public(event))


@bp.post("/<event_id>/start")
@roles("FacilityOperator")
def start_event(event_id):
    event = get_event(event_id)
    get_body()
    if event["status"] != "SCHEDULED":
        fail("ERR_EVENT_NOT_SCHEDULED", "Only a SCHEDULED event may be started.")
    site = _site_of(event)
    batch = _batch_of(event)
    agreement = _agreement_of(event)
    check_site_permitted(site)
    check_agreement_active(agreement)
    check_batch_qualified(batch)
    check_site_not_restricted(site)
    if not site["weather_clearance_ok"]:
        fail("ERR_WEATHER_RESTRICTION", "The site does not have weather clearance.")
    window_start = parse_dt(event["window_start"])
    window_end = parse_dt(event["window_end"])
    if not (window_start <= now() < window_end):
        fail("ERR_OUTSIDE_APPLICATION_WINDOW",
             "The logical clock is outside the application window.")
    event["status"] = "IN_PROGRESS"
    touch(event)
    return object_response(public(event))


@bp.post("/<event_id>/cancel")
@roles("Agronomist", "ComplianceOfficer")
def cancel_event(event_id):
    event = get_event(event_id)
    get_body()
    if event["status"] not in PRE_FIELD:
        fail("ERR_EVENT_NOT_SCHEDULED",
             "Only a pre-field application event may be cancelled.")
    event["status"] = "CANCELLED"
    event["reserved_dry_tons"] = r3(0)
    touch(event)
    batch = _batch_of(event)
    if batch is not None:
        recompute_batch_balance(batch)
        touch(batch)
    return object_response(public(event))


def tickets_of_event(event_id):
    return [t for t in store.haul_tickets.values() if t["event_id"] == event_id]


def _write_application_entries(event, site, batch):
    applied_rate = D(event["applied_dry_tons"]) / D(event["acres_treated"])
    year = parse_dt(event["window_start"]).year
    results = {r["analyte"]: r for r in current_round_results(batch)}
    for analyte in sorted(results):
        entry = store.new_record({
            "site_id": site["id"],
            "source_event_id": event["id"],
            "analyte": analyte,
            "kg_per_hectare_delta": loading_delta(
                applied_rate, results[analyte]["concentration_mg_kg"]),
            "entry_type": "APPLICATION",
            "reversal_of_id": None,
            "applied_year": year,
        })
        store.ledger[entry["id"]] = entry


@bp.post("/<event_id>/complete")
@roles("ComplianceOfficer")
def complete_event(event_id):
    event = get_event(event_id)
    body = get_body()
    applied_dry_tons = vnum(body, "applied_dry_tons", required=False, default=None)
    incorporation_supplied = present(body, "incorporation_within_hours")
    incorporation = vnum(body, "incorporation_within_hours", required=False,
                         default=event["incorporation_within_hours"], ge=0,
                         nullable=True)
    if event["status"] != "IN_PROGRESS":
        fail("ERR_EVENT_NOT_IN_PROGRESS",
             "Only an IN_PROGRESS event may be closed out.")
    site = _site_of(event)
    batch = _batch_of(event)
    if g.user_id == batch.get("certified_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The closing officer certified the batch.")
    check_site_not_restricted(site)

    effective_incorporation = (incorporation if incorporation_supplied
                               else event["incorporation_within_hours"])
    option = batch["vector_option"]
    if option == "VAR_OPTION_9_INJECTION":
        if event["application_method"] != "INJECTED":
            fail("ERR_VECTOR_OPTION_METHOD_MISMATCH",
                 "The batch requires injection to demonstrate vector attraction "
                 "reduction.")
    elif option == "VAR_OPTION_10_INCORPORATION":
        if (effective_incorporation is None
                or D(effective_incorporation) > Decimal(6)):
            fail("ERR_VECTOR_OPTION_METHOD_MISMATCH",
                 "Incorporation within 6 hours was not demonstrated.")

    tickets = tickets_of_event(event["id"])
    if not tickets:
        fail("ERR_NO_HAUL_TICKET", "The event has no haul tickets.")
    applied_wet_tons = r2(sum((D(t["wet_tons"]) for t in tickets), Decimal(0)))

    if applied_dry_tons is None:
        applied_dry_tons = D(event["planned_dry_tons"])
    applied_dry_tons = r3(applied_dry_tons)
    if not (applied_dry_tons > 0 and applied_dry_tons <= D(event["planned_dry_tons"])):
        fail("ERR_APPLIED_TONS_INVALID",
             "applied_dry_tons must be greater than 0 and at most planned_dry_tons.")

    # Hop 1
    if incorporation_supplied:
        event["incorporation_within_hours"] = incorporation
    event["status"] = "COMPLETED"
    event["applied_dry_tons"] = applied_dry_tons
    event["applied_wet_tons"] = applied_wet_tons
    event["completed_by_user_id"] = g.user_id
    event["reserved_dry_tons"] = r3(0)
    touch(event)
    recompute_batch_balance(batch)
    touch(batch)
    # Hop 2
    _write_application_entries(event, site, batch)
    # Hop 3
    recompute_site_loading(site)
    # PFOS advisory refresh for this site
    pfos = next((r for r in current_round_results(batch) if r["analyte"] == "PFOS"),
                None)
    if pfos is not None and pfos["advisory_exceeded"] and not site["pfas_advisory_flag"]:
        site["pfas_advisory_flag"] = True
        derive_site_odor(site)
    touch(site)
    # Hop 4
    if site["status"] == "PERMITTED" and cplr_trigger_reached(site):
        site["status"] = "RESTRICTED"
        site["restriction_reason"] = "CPLR_HEADROOM_LOW"
        site["updated_at"] = now_iso()
        defer_pre_field_events(site["id"], "SITE_RESTRICTED")
    # Storage debit
    facility = facility_of_site(site)
    if facility is not None:
        refresh_facility_storage(facility)
    return object_response(public(event))


@bp.post("/<event_id>/void")
@roles("ComplianceOfficer")
def void_event(event_id):
    event = get_event(event_id)
    get_body()
    if event["status"] != "COMPLETED":
        fail("ERR_EVENT_NOT_COMPLETED", "Only a COMPLETED event may be voided.")
    site = _site_of(event)
    batch = _batch_of(event)
    facility = facility_of_site(site)
    year = parse_dt(event["window_start"]).year
    if facility is not None:
        for report in store.reports.values():
            if (report["facility_id"] == facility["id"]
                    and report["report_year"] == year
                    and report["status"] in ("SUBMITTED", "AMENDED")):
                fail("ERR_REPORTING_PERIOD_LOCKED",
                     "The reporting year %d is closed to voids." % year)

    # Hop 1
    originals = [e for e in store.ledger.values()
                 if e["source_event_id"] == event["id"]
                 and e["entry_type"] == "APPLICATION"]
    originals.sort(key=lambda e: (e["analyte"], e["created_at"], e["_seq"]))
    for original in originals:
        entry = store.new_record({
            "site_id": original["site_id"],
            "source_event_id": event["id"],
            "analyte": original["analyte"],
            "kg_per_hectare_delta": -D(original["kg_per_hectare_delta"]),
            "entry_type": "REVERSAL",
            "reversal_of_id": original["id"],
            "applied_year": original["applied_year"],
        })
        store.ledger[entry["id"]] = entry
    # Hop 2
    recompute_site_loading(site)
    touch(site)
    # Hop 3
    if (site["status"] == "RESTRICTED"
            and site["restriction_reason"] == "CPLR_HEADROOM_LOW"
            and cplr_all_below_trigger(site)):
        site["status"] = "PERMITTED"
        site["restriction_reason"] = None
        site["updated_at"] = now_iso()

    event["status"] = "VOIDED"
    event["voided_at"] = now_iso()
    touch(event)
    recompute_batch_balance(batch)
    touch(batch)
    if facility is not None:
        refresh_facility_storage(facility)
    return object_response(public(event))


@bp.post("/<event_id>/haul-tickets")
@roles("FacilityOperator")
def create_haul_ticket(event_id):
    event = get_event(event_id)
    body = get_body()
    truck_id = vstr(body, "truck_id", required=True, min_len=1, max_len=32)
    wet_tons = vnum(body, "wet_tons", required=True, gt=0)
    depart_at = vdt(body, "depart_at", required=True)
    return_at = vdt(body, "return_at", required=True)
    if not return_at > depart_at:
        fail("ERR_INVALID_REQUEST", "return_at must be strictly after depart_at.")
    odometer = vnum(body, "odometer_miles", required=False, default=Decimal("0.0"), ge=0)
    if event["status"] != "IN_PROGRESS":
        fail("ERR_EVENT_NOT_IN_PROGRESS",
             "Haul tickets are recorded against an IN_PROGRESS event only.")
    site = _site_of(event)
    facility = facility_of_site(site)
    occupied = 0
    for ticket in store.haul_tickets.values():
        other_event = store.events.get(ticket["event_id"])
        if other_event is None:
            continue
        other_site = store.sites.get(other_event["site_id"])
        if other_site is None or other_site["facility_id"] != site["facility_id"]:
            continue
        other_depart = parse_dt(ticket["depart_at"])
        other_return = parse_dt(ticket["return_at"])
        if other_depart <= return_at and depart_at <= other_return:
            occupied += 1
    if facility is not None and not occupied < int(facility["loadout_bay_count"]):
        fail("ERR_LOADOUT_BAY_CAPACITY",
             "All loadout bays are occupied for the requested interval.")

    ticket = store.new_record({
        "event_id": event["id"],
        "truck_id": truck_id,
        "wet_tons": r2(wet_tons),
        "depart_at": iso(depart_at),
        "return_at": iso(return_at),
        "odometer_miles": odometer,
    })
    store.haul_tickets[ticket["id"]] = ticket
    return object_response(public(ticket), 201)


@bp.get("/<event_id>/haul-tickets")
@roles("FacilityOperator", "ComplianceOfficer", "Agronomist")
def list_event_haul_tickets(event_id):
    event = get_event(event_id)
    truck_id = qstr("truck_id")
    rows = [t for t in tickets_of_event(event["id"])
            if truck_id is None or t["truck_id"] == truck_id]
    return emit_list(rows, ("depart_at", "created_at"))
