"""Derived state, conserved quantities and cascades (PRD 2.8-2.11)."""

from decimal import Decimal

import store
from calc import SEVERITY_WEIGHT, vsr_van_kleeck  # noqa: F401
from store import D, days, floor_int, now, now_iso, parse_dt, r2, r3, r4, touch

OPEN_EVENT_STATUSES = ("SCHEDULED", "WEATHER_HOLD", "DEFERRED", "IN_PROGRESS")
PRE_FIELD_STATUSES = ("SCHEDULED", "WEATHER_HOLD")
RESERVING_STATUSES = ("SCHEDULED", "WEATHER_HOLD", "DEFERRED", "IN_PROGRESS")
CONSUMING_ORDER_STATUSES = ("DRAFT", "COMMITTED", "SETTLED")


# --- pollutant limits ------------------------------------------------------


def active_limits():
    out = {}
    for row in store.limits.values():
        if row["status"] == "ACTIVE":
            out[row["analyte"]] = row
    return out


def active_limit_for(analyte):
    return active_limits().get(analyte)


# --- lookups ---------------------------------------------------------------


def events_of_batch(batch_id):
    return [e for e in store.events.values() if e["batch_id"] == batch_id]


def events_of_site(site_id):
    return [e for e in store.events.values() if e["site_id"] == site_id]


def orders_of_batch(batch_id):
    return [o for o in store.orders.values() if o["batch_id"] == batch_id]


def results_of_batch(batch_id):
    return [r for r in store.lab_results.values() if r["batch_id"] == batch_id]


def current_round_results(batch):
    return [r for r in results_of_batch(batch["id"])
            if r["sampling_event_index"] == batch["retest_round"]]


def facility_of_site(site):
    return store.facilities.get(site["facility_id"])


def facility_of_event(event):
    site = store.sites.get(event["site_id"])
    return facility_of_site(site) if site else None


# --- batch conserved quantity ---------------------------------------------


def recompute_batch_balance(batch):
    reserved = Decimal(0)
    applied = Decimal(0)
    for event in events_of_batch(batch["id"]):
        if event["status"] in RESERVING_STATUSES:
            reserved += D(event["planned_dry_tons"])
        elif event["status"] == "COMPLETED":
            applied += D(event["applied_dry_tons"])
    diverted = Decimal(0)
    for order in orders_of_batch(batch["id"]):
        if order["status"] in CONSUMING_ORDER_STATUSES:
            diverted += D(order["dry_tons"])
    unallocated = r3(D(batch["dry_tons_produced"]) - reserved - applied - diverted)
    batch["unallocated_dry_tons"] = unallocated
    allocated = reserved + applied + diverted
    if allocated == 0:
        batch["disposition"] = "HELD"
    elif unallocated == 0:
        batch["disposition"] = "FULLY_COMMITTED"
    else:
        batch["disposition"] = "PARTIALLY_COMMITTED"
    return unallocated


# --- facility derived figures ---------------------------------------------


def recompute_facility_storage(facility):
    used = Decimal(0)
    for batch in store.batches.values():
        if batch["facility_id"] == facility["id"]:
            used += D(batch["wet_tons"])
    for event in store.events.values():
        if event["status"] != "COMPLETED":
            continue
        site = store.sites.get(event["site_id"])
        if site is not None and site["facility_id"] == facility["id"]:
            used -= D(event["applied_wet_tons"])
    for order in store.orders.values():
        if order["status"] != "SETTLED":
            continue
        batch = store.batches.get(order["batch_id"])
        if batch is not None and batch["facility_id"] == facility["id"]:
            used -= D(order["wet_tons"])
    facility["storage_used_wet_tons"] = r2(used)
    capacity = D(facility["storage_capacity_wet_tons"])
    if capacity == 0:
        facility["storage_utilization_pct"] = r2(0)
    else:
        facility["storage_utilization_pct"] = r2(
            D(facility["storage_used_wet_tons"]) / capacity * Decimal(100))
    # `days_of_capacity` is the drawdown projection of 3.1; it is restated
    # whenever the storage figures it reads move.
    facility["days_of_capacity"] = storage_projection(facility)["days_of_capacity"]


def recompute_open_ceiling_exceedances(facility):
    count = 0
    for batch in store.batches.values():
        if (batch["facility_id"] == facility["id"] and batch["ceiling_exceedance_flag"]
                and batch["quality_status"] == "REJECTED"):
            count += 1
    facility["open_ceiling_exceedance_count"] = count


def recompute_substantiated_30d(facility):
    threshold = now() - days(30)
    count = 0
    for complaint in store.complaints.values():
        if complaint["facility_id"] != facility["id"]:
            continue
        if complaint["status"] != "SUBSTANTIATED":
            continue
        received = parse_dt(complaint["received_at"])
        if received is not None and received >= threshold:
            count += 1
    facility["substantiated_complaint_count_30d"] = count


def derive_posture(facility):
    utilization = D(facility["storage_utilization_pct"])
    if facility["open_ceiling_exceedance_count"] > 0 or utilization >= Decimal("98.00"):
        facility["posture"] = "FROZEN"
    elif (utilization >= Decimal("90.00")
          or facility["substantiated_complaint_count_30d"] >= 3):
        facility["posture"] = "RESTRICTED"
    else:
        facility["posture"] = "OPEN"
    return facility["posture"]


def storage_projection(facility):
    used = D(facility["storage_used_wet_tons"])
    capacity = D(facility["storage_capacity_wet_tons"])
    available = r2(capacity - used)
    start = now()
    end = start + days(30)
    outflow = Decimal(0)
    for event in store.events.values():
        if event["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        site = store.sites.get(event["site_id"])
        if site is None or site["facility_id"] != facility["id"]:
            continue
        window_start = parse_dt(event["window_start"])
        if window_start is not None and start <= window_start < end:
            outflow += D(event["planned_wet_tons"])
    for order in store.orders.values():
        if order["status"] != "COMMITTED":
            continue
        batch = store.batches.get(order["batch_id"])
        if batch is not None and batch["facility_id"] == facility["id"]:
            outflow += D(order["wet_tons"])
    outflow = r2(outflow)
    daily_production = D(facility["daily_production_wet_tons"])
    inflow = r2(daily_production * Decimal(30))
    daily_removal = r4(outflow / Decimal(30))
    daily_net = r4(daily_production - daily_removal)
    if daily_net <= 0:
        capacity_days = 9999
    else:
        capacity_days = floor_int(available / daily_net)
    return {
        "facility_id": facility["id"],
        "storage_used_wet_tons": r2(used),
        "storage_capacity_wet_tons": capacity,
        "storage_utilization_pct": D(facility["storage_utilization_pct"]),
        "projected_outflow_wet_tons": outflow,
        "projected_inflow_wet_tons": inflow,
        "days_of_capacity": capacity_days,
        "posture": facility["posture"],
    }


def facility_view(facility):
    # A new facility is created with the sentinel 9999 (3.1); the stored figure
    # is restated by recompute_facility_storage on every storage mutation.
    return store.public(facility)


# --- loading ledger projections -------------------------------------------


def entries_of_site(site_id):
    return [e for e in store.ledger.values() if e["site_id"] == site_id]


def recompute_site_loading(site):
    cumulative = {}
    annual = {}
    for entry in entries_of_site(site["id"]):
        analyte = entry["analyte"]
        delta = D(entry["kg_per_hectare_delta"])
        cumulative[analyte] = cumulative.get(analyte, Decimal(0)) + delta
        key = "%d:%s" % (entry["applied_year"], analyte)
        annual[key] = annual.get(key, Decimal(0)) + delta
    site["cumulative_loading_kg_per_hectare"] = {
        k: cumulative[k] for k in sorted(cumulative)}
    site["annual_loading_kg_per_hectare"] = {k: annual[k] for k in sorted(annual)}


def cumulative_loading(site, analyte):
    return D(site["cumulative_loading_kg_per_hectare"].get(analyte, 0))


def annual_loading(site, year, analyte):
    return D(site["annual_loading_kg_per_hectare"].get("%d:%s" % (year, analyte), 0))


def cplr_trigger_reached(site):
    """True when any analyte's cumulative loading is at or above 0.90 * CPLR."""
    for analyte, limit in active_limits().items():
        cplr = limit.get("cplr_kg_per_hectare")
        if cplr is None:
            continue
        if cumulative_loading(site, analyte) >= Decimal("0.90") * D(cplr):
            return True
    return False


def cplr_all_below_trigger(site):
    for analyte, limit in active_limits().items():
        cplr = limit.get("cplr_kg_per_hectare")
        if cplr is None:
            continue
        if not cumulative_loading(site, analyte) < Decimal("0.90") * D(cplr):
            return False
    return True


# --- odor scores -----------------------------------------------------------


def complaints_for_site(site_id):
    return [c for c in store.complaints.values() if c.get("site_id") == site_id]


def _in_odor_window(complaint):
    received = parse_dt(complaint["received_at"])
    if received is None:
        return False
    return received >= now() - days(365)


def _is_substantiated_set(complaint):
    if complaint["status"] == "SUBSTANTIATED":
        return True
    if complaint["status"] == "CLOSED":
        return (complaint.get("resolution_action") or "NONE") != "NONE"
    return False


def derive_site_odor(site):
    substantiated = Decimal(0)
    open_weight = Decimal(0)
    for complaint in complaints_for_site(site["id"]):
        if not _in_odor_window(complaint):
            continue
        weight = SEVERITY_WEIGHT.get(complaint["severity"], Decimal(0))
        if _is_substantiated_set(complaint):
            substantiated += weight
        elif complaint["status"] in ("RECEIVED", "INVESTIGATING"):
            open_weight += weight
    historical = min(Decimal("100.0"), substantiated * Decimal("4.0"))
    multiplier = Decimal("1.5") if site["pfas_advisory_flag"] else Decimal("1.0")
    precautionary = min(Decimal("100.0"),
                        (substantiated + open_weight) * Decimal("4.0") * multiplier)
    site["odor_risk_score_historical"] = r2(historical)
    site["odor_risk_score_precautionary"] = r2(precautionary)
    if D(site["nearest_residence_ft"]) < Decimal(1500):
        site["gating_risk_score"] = site["odor_risk_score_precautionary"]
    else:
        site["gating_risk_score"] = site["odor_risk_score_historical"]


def derive_weather_clearance(site):
    rain = site.get("latest_rainfall_in_24h")
    forecast = site.get("latest_forecast_rainfall_in_48h")
    frozen = site.get("latest_frozen_ground")
    if rain is None or forecast is None or frozen is None:
        site["weather_clearance_ok"] = False
        return False
    ok = (D(rain) < Decimal("0.50") and D(forecast) < Decimal("1.00")
          and frozen is False)
    site["weather_clearance_ok"] = bool(ok)
    return site["weather_clearance_ok"]


# --- outlet ----------------------------------------------------------------


def recompute_outlet_ytd(outlet):
    year = now().year
    total = Decimal(0)
    for order in store.orders.values():
        if order["outlet_id"] != outlet["id"]:
            continue
        if order["status"] not in ("COMMITTED", "SETTLED"):
            continue
        committed = parse_dt(order.get("committed_at")) if order.get("committed_at") else None
        if committed is not None and committed.year == year:
            total += D(order["wet_tons"])
    outlet["ytd_accepted_wet_tons"] = r2(total)
    return outlet["ytd_accepted_wet_tons"]


# --- cascades --------------------------------------------------------------


def defer_pre_field_events(site_id, defer_reason):
    count = 0
    for event in events_of_site(site_id):
        if event["status"] in PRE_FIELD_STATUSES:
            event["status"] = "DEFERRED"
            event["defer_reason"] = defer_reason
            touch(event)
            count += 1
    return count


def defer_events_of_agreement(agreement_id, defer_reason):
    count = 0
    for event in store.events.values():
        if event.get("agreement_id") != agreement_id:
            continue
        if event["status"] in PRE_FIELD_STATUSES:
            event["status"] = "DEFERRED"
            event["defer_reason"] = defer_reason
            touch(event)
            count += 1
    return count


def restrict_site(site, restriction_reason, defer_reason, bump_site=True):
    site["status"] = "RESTRICTED"
    site["restriction_reason"] = restriction_reason
    if bump_site:
        touch(site)
    else:
        site["updated_at"] = now_iso()
    defer_pre_field_events(site["id"], defer_reason)


def refresh_facility_storage(facility):
    """Storage change: restate storage, re-derive posture, bump version."""
    recompute_facility_storage(facility)
    derive_posture(facility)
    touch(facility)


def refresh_facility_exceedances(facility):
    recompute_open_ceiling_exceedances(facility)
    derive_posture(facility)
    touch(facility)


def ceiling_rejection_cascade(batch):
    """PRD 3.4: three hops from a ceiling-exceeding laboratory result."""
    # Hop 1
    batch["ceiling_exceedance_flag"] = True
    was_qualified = batch["quality_status"] == "QUALIFIED"
    batch["quality_status"] = "REJECTED"
    batch["rejection_reason"] = "CEILING_EXCEEDED"
    if was_qualified:
        batch["certified_at"] = None
        batch["certified_by_user_id"] = None
    touch(batch)
    # Hop 2
    for event in events_of_batch(batch["id"]):
        if event["status"] in PRE_FIELD_STATUSES or event["status"] == "DEFERRED":
            event["status"] = "CANCELLED"
            event["reserved_dry_tons"] = r3(0)
            touch(event)
    for order in orders_of_batch(batch["id"]):
        if order["status"] == "DRAFT":
            order["status"] = "VOIDED"
            order["void_reason"] = "BATCH_REJECTED"
            touch(order)
    recompute_batch_balance(batch)
    # Hop 3
    facility = store.facilities.get(batch["facility_id"])
    if facility is not None:
        refresh_facility_exceedances(facility)


def pfos_advisory_cascade(batch):
    """PRD 3.4: PFOS advisory exceedance flags sites with a completed event."""
    for site in store.sites.values():
        if site["status"] not in ("PERMITTED", "RESTRICTED"):
            continue
        has_completed = any(
            e["site_id"] == site["id"] and e["status"] == "COMPLETED"
            for e in events_of_batch(batch["id"]))
        if not has_completed:
            continue
        site["pfas_advisory_flag"] = True
        derive_site_odor(site)
        touch(site)
