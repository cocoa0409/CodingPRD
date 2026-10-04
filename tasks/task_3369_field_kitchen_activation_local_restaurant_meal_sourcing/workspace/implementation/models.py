"""Entity creation, derived-field recomputation and JSON serialisation.

Field names and ordering follow SCAFFOLD `entities`; every `source: computed`
field is recomputed here whenever its inputs change, and a recomputation that
changes a stored value mutates the row (updated_at refreshed, version +1).
"""

from datetime import timedelta

from calculations import (
    assessment_feeding_priority,
    field_kitchen_food_safety_score,
    incident_aggregates,
    meal_order_cost_buildup,
    partner_kitchen_quality_score,
    run_delivered_meals,
    run_pending_planned_meals,
    run_returned_meals,
    supplier_counts,
    supplier_reliability_score,
    supplier_standing,
)
from core import (
    DB, assign, day_bucket, dec, fmt_dt, make_row, now, round_half_up, touch,
)
from errors import fail
from validations import ref_row, same_incident

# --------------------------------------------------------------------------
# Serialisation: exact declared field set per entity, timestamps formatted.
# --------------------------------------------------------------------------

_INCIDENT = ["id", "name", "country_code", "disaster_type", "severity_level",
             "target_daily_meals", "funding_ceiling_cents", "currency_code",
             "population_dietary_requirements", "status", "activated_at",
             "wind_down_started_at", "closed_at", "committed_cents", "spent_cents",
             "delivered_meal_total", "local_sourcing_pct", "cost_per_meal_cents",
             "created_at", "updated_at", "version"]
_INCIDENT_DT = {"activated_at", "wind_down_started_at", "closed_at", "created_at", "updated_at"}

_ASSESSMENT = ["id", "incident_id", "assessed_at", "population_affected",
               "estimated_daily_meal_need", "access_constraint", "water_available",
               "power_available", "partner_kitchens_identified", "assessment_mode",
               "feeding_priority_score", "status", "created_at", "updated_at", "version"]
_ASSESSMENT_DT = {"assessed_at", "created_at", "updated_at"}

_FIELD_KITCHEN = ["id", "incident_id", "assessment_id", "site_name", "latitude",
                  "longitude", "power_source", "water_source",
                  "refrigeration_hours_available", "daily_capacity_meals",
                  "site_status", "food_safety_score", "last_inspection_at",
                  "suspended_at", "activated_at", "demobilized_at",
                  "runs_today_count", "created_at", "updated_at", "version"]
_FIELD_KITCHEN_DT = {"last_inspection_at", "suspended_at", "activated_at",
                     "demobilized_at", "created_at", "updated_at"}

_PARTNER_KITCHEN = ["id", "incident_id", "business_name", "owner_name", "cuisine_tags",
                    "daily_capacity_meals", "per_meal_price_cents", "bank_verified",
                    "vetting_score", "contract_status", "production_status",
                    "quality_score", "meals_produced_total", "meals_produced_today",
                    "production_started_at", "cooldown_until", "contracted_at",
                    "terminated_at", "created_at", "updated_at", "version"]
_PARTNER_KITCHEN_DT = {"production_started_at", "cooldown_until", "contracted_at",
                       "terminated_at", "created_at", "updated_at"}

_MEAL_ORDER = ["id", "incident_id", "partner_kitchen_id", "distribution_run_id",
               "menu_name", "dietary_tags", "ordered_meals", "scheduled_start",
               "production_hours", "status", "produced_meals", "rejected_meals",
               "accepted_meals", "rework_count", "quality_check_score",
               "subtotal_cents", "logistics_fee_cents", "volume_discount_cents",
               "provisional_cost_cents", "final_cost_cents", "placed_at", "ready_at",
               "delivered_at", "cancel_reason", "created_at", "updated_at", "version"]
_MEAL_ORDER_DT = {"scheduled_start", "placed_at", "ready_at", "delivered_at",
                  "created_at", "updated_at"}

_SUPPLIER = ["id", "incident_id", "producer_name", "locality", "product_categories",
             "payment_terms_days", "status", "cash_flow_received_cents",
             "reliability_score", "delivered_purchase_count", "disputed_purchase_count",
             "created_at", "updated_at", "version"]
_SUPPLIER_DT = {"created_at", "updated_at"}

_PURCHASE = ["id", "incident_id", "supplier_id", "partner_kitchen_id",
             "item_description", "quantity_kg", "unit_price_cents_per_kg",
             "amount_cents", "status", "requested_at", "delivered_at", "paid_at",
             "dispute_reason", "created_at", "updated_at", "version"]
_PURCHASE_DT = {"requested_at", "delivered_at", "paid_at", "created_at", "updated_at"}

_SITE = ["id", "incident_id", "site_name", "site_type", "population_served",
         "daily_meal_request", "access_constraint", "status", "received_meals_total",
         "skipped_stop_count", "delivered_stop_count", "created_at", "updated_at",
         "version"]
_SITE_DT = {"created_at", "updated_at"}

_RUN = ["id", "incident_id", "field_kitchen_id", "driver_name", "driver_phone",
        "driver_safety_training_completed", "vehicle_type", "planned_date",
        "window_start", "window_end", "loaded_meals", "fuel_cost_cents",
        "handling_cost_cents", "status", "total_cost_cents", "unallocated_cost_cents",
        "delivered_meals", "returned_meals", "completed_at", "abort_reason",
        "created_at", "updated_at", "version"]
_RUN_DT = {"planned_date", "window_start", "window_end", "completed_at",
           "created_at", "updated_at"}

_STOP = ["id", "distribution_run_id", "distribution_site_id", "stop_sequence",
         "planned_meals", "delivered_meals", "allocated_cost_cents", "status",
         "failure_reason", "delivered_at", "created_at", "updated_at", "version"]
_STOP_DT = {"delivered_at", "created_at", "updated_at"}

_COMMITMENT = ["id", "incident_id", "donor_name", "amount_cents", "earmark", "status",
               "received_at", "allocated_cents", "disbursed_cents", "remaining_cents",
               "created_at", "updated_at", "version"]
_COMMITMENT_DT = {"received_at", "created_at", "updated_at"}

_SPECS = {
    "incidents": (_INCIDENT, _INCIDENT_DT),
    "assessments": (_ASSESSMENT, _ASSESSMENT_DT),
    "field_kitchens": (_FIELD_KITCHEN, _FIELD_KITCHEN_DT),
    "partner_kitchens": (_PARTNER_KITCHEN, _PARTNER_KITCHEN_DT),
    "meal_orders": (_MEAL_ORDER, _MEAL_ORDER_DT),
    "suppliers": (_SUPPLIER, _SUPPLIER_DT),
    "ingredient_purchases": (_PURCHASE, _PURCHASE_DT),
    "distribution_sites": (_SITE, _SITE_DT),
    "distribution_runs": (_RUN, _RUN_DT),
    "distribution_stops": (_STOP, _STOP_DT),
    "donor_commitments": (_COMMITMENT, _COMMITMENT_DT),
}


def ser(kind, row):
    fields, dts = _SPECS[kind]
    return {name: (fmt_dt(row.get(name)) if name in dts else row.get(name))
            for name in fields}


# --------------------------------------------------------------------------
# Derived-field recomputation.  Each helper only mutates the row when a stored
# value actually changes, so a no-op refresh leaves version untouched.
# --------------------------------------------------------------------------

def refresh_incident(row):
    agg = incident_aggregates(row["id"])
    assign(row, "committed_cents", agg["committed_cents"])
    assign(row, "spent_cents", agg["spent_cents"])
    assign(row, "delivered_meal_total", agg["delivered_meal_total"])
    assign(row, "local_sourcing_pct", agg["local_sourcing_pct"])
    assign(row, "cost_per_meal_cents", agg["cost_per_meal_cents"])


def refresh_field_kitchen(row):
    today = day_bucket(now())
    count = sum(1 for run in DB["distribution_runs"].values()
                if run["field_kitchen_id"] == row["id"]
                and day_bucket(run["planned_date"]) == today)
    assign(row, "runs_today_count", count)


def refresh_partner_kitchen(row):
    events = row.get("_production_events") or []
    today = day_bucket(now())
    assign(row, "meals_produced_total", sum(e["meals"] for e in events))
    assign(row, "meals_produced_today",
           sum(e["meals"] for e in events if day_bucket(e["at"]) == today))


def refresh_meal_order(row):
    produced = row.get("produced_meals")
    accepted = 0 if produced is None else produced - (row.get("rejected_meals") or 0)
    assign(row, "accepted_meals", accepted)


def refresh_supplier(row):
    delivered, disputed = supplier_counts(row["id"])
    assign(row, "delivered_purchase_count", delivered)
    assign(row, "disputed_purchase_count", disputed)
    assign(row, "reliability_score", supplier_reliability_score(delivered, disputed))


def refresh_distribution_site(row):
    stops = [s for s in DB["distribution_stops"].values()
             if s["distribution_site_id"] == row["id"]]
    assign(row, "received_meals_total",
           sum(s["delivered_meals"] for s in stops if s["status"] == "DELIVERED"))
    assign(row, "skipped_stop_count", sum(1 for s in stops if s["status"] == "SKIPPED"))
    assign(row, "delivered_stop_count", sum(1 for s in stops if s["status"] == "DELIVERED"))


def refresh_distribution_run(row):
    assign(row, "total_cost_cents",
           (row.get("fuel_cost_cents") or 0) + (row.get("handling_cost_cents") or 0))
    assign(row, "delivered_meals", run_delivered_meals(row["id"]))
    assign(row, "returned_meals", run_returned_meals(row))


def refresh_donor_commitment(row):
    assign(row, "remaining_cents",
           row["amount_cents"] - (row.get("disbursed_cents") or 0))


_REFRESH = {
    "incidents": refresh_incident,
    "field_kitchens": refresh_field_kitchen,
    "partner_kitchens": refresh_partner_kitchen,
    "meal_orders": refresh_meal_order,
    "suppliers": refresh_supplier,
    "distribution_sites": refresh_distribution_site,
    "distribution_runs": refresh_distribution_run,
    "donor_commitments": refresh_donor_commitment,
}


def refresh(kind, row):
    """Recompute every derived field of a row, mutating it only on real change."""
    fn = _REFRESH.get(kind)
    if fn is not None:
        fn(row)
    return row


def recompute_partner_quality(row):
    score = partner_kitchen_quality_score(row["id"])
    if score is not None:
        assign(row, "quality_score", score)


def record_production(row, meals):
    """Append a production event so meals_produced_today is day-bucket aware."""
    events = row.setdefault("_production_events", [])
    events.append({"at": now(), "meals": meals})
    refresh_partner_kitchen(row)


# --------------------------------------------------------------------------
# Creation paths.  Rule-1 body validation happens in parsers.py before the auth
# checks; these functions run from rule 7 (foreign keys) onwards.
# --------------------------------------------------------------------------

def create_incident(data):
    row = make_row(
        name=data["name"],
        country_code=data["country_code"],
        disaster_type=data["disaster_type"],
        severity_level=data["severity_level"],
        target_daily_meals=data["target_daily_meals"],
        funding_ceiling_cents=data["funding_ceiling_cents"],
        currency_code=data.get("currency_code") or "USD",
        population_dietary_requirements=data.get("population_dietary_requirements") or [],
        status="MONITORING",
        activated_at=None,
        wind_down_started_at=None,
        closed_at=None,
        committed_cents=0,
        spent_cents=0,
        delivered_meal_total=0,
        local_sourcing_pct=0,
        cost_per_meal_cents=0,
    )
    DB["incidents"][row["id"]] = row
    return row


def create_assessment(data):
    incident = ref_row("incidents", data["incident_id"])
    assessed_at = data["assessed_at"]
    if assessed_at < incident["created_at"]:
        fail("ERR_ASSESSMENT_BEFORE_ACTIVATION")
    score = assessment_feeding_priority(
        data["population_affected"], data["estimated_daily_meal_need"],
        data["access_constraint"], data["water_available"], data["power_available"],
        data["partner_kitchens_identified"], data["assessment_mode"])
    row = make_row(
        incident_id=incident["id"],
        assessed_at=assessed_at,
        population_affected=data["population_affected"],
        estimated_daily_meal_need=data["estimated_daily_meal_need"],
        access_constraint=data["access_constraint"],
        water_available=data["water_available"],
        power_available=data["power_available"],
        partner_kitchens_identified=data["partner_kitchens_identified"],
        assessment_mode=data["assessment_mode"],
        feeding_priority_score=score,
        status="SUBMITTED",
    )
    DB["assessments"][row["id"]] = row
    return row


def create_field_kitchen(data):
    incident = ref_row("incidents", data["incident_id"])
    assessment = ref_row("assessments", data["assessment_id"])
    same_incident(incident["id"], assessment)
    score = field_kitchen_food_safety_score(
        data["power_source"], data["water_source"],
        data["refrigeration_hours_available"], data["daily_capacity_meals"])
    row = make_row(
        incident_id=incident["id"],
        assessment_id=assessment["id"],
        site_name=data["site_name"],
        latitude=data["latitude"],
        longitude=data["longitude"],
        power_source=data["power_source"],
        water_source=data["water_source"],
        refrigeration_hours_available=data["refrigeration_hours_available"],
        daily_capacity_meals=data["daily_capacity_meals"],
        site_status="SITED",
        food_safety_score=score,
        last_inspection_at=None,
        suspended_at=None,
        activated_at=None,
        demobilized_at=None,
        runs_today_count=0,
    )
    DB["field_kitchens"][row["id"]] = row
    return row


def create_partner_kitchen(data):
    incident = ref_row("incidents", data["incident_id"])
    row = make_row(
        incident_id=incident["id"],
        business_name=data["business_name"],
        owner_name=data["owner_name"],
        cuisine_tags=data["cuisine_tags"],
        daily_capacity_meals=data["daily_capacity_meals"],
        per_meal_price_cents=data["per_meal_price_cents"],
        bank_verified=data["bank_verified"],
        vetting_score=0,
        contract_status="PROSPECT",
        production_status="IDLE",
        quality_score=0,
        meals_produced_total=0,
        meals_produced_today=0,
        production_started_at=None,
        cooldown_until=None,
        contracted_at=None,
        terminated_at=None,
        _production_events=[],
    )
    DB["partner_kitchens"][row["id"]] = row
    return row


def kitchen_window_conflict(kitchen_id, scheduled_start, production_hours):
    """Rule 24: intersecting half-open windows, plus the 8h post-rejection buffer."""
    new_start = scheduled_start
    new_end = scheduled_start + timedelta(hours=production_hours)
    for order in DB["meal_orders"].values():
        if order["partner_kitchen_id"] != kitchen_id:
            continue
        if order["status"] in ("PLACED", "IN_PRODUCTION", "QUALITY_HOLD", "READY", "DISPATCHED"):
            other_start = order["scheduled_start"]
            other_end = other_start + timedelta(hours=order["production_hours"])
            if new_start < other_end and other_start < new_end:
                return True
        elif order["status"] == "REJECTED":
            rejected_at = order.get("_rejected_at")
            if rejected_at is not None and rejected_at <= new_start < rejected_at + timedelta(hours=8):
                return True
    return False


def create_meal_order(data):
    incident = ref_row("incidents", data["incident_id"])
    kitchen = ref_row("partner_kitchens", data["partner_kitchen_id"])

    # Rule 10 -- optimistic concurrency on the parent kitchen.
    if data["expected_partner_kitchen_version"] != kitchen["version"]:
        fail("ERR_STALE_VERSION")
    # Rule 11 -- the restaurant must be contracted.
    if kitchen["contract_status"] != "CONTRACTED":
        fail("ERR_PARTNER_KITCHEN_NOT_CONTRACTED")
    # Rule 22 -- dietary coverage of the affected population.
    required = set(incident.get("population_dietary_requirements") or [])
    if not required.issubset(set(data["dietary_tags"])):
        fail("ERR_DIETARY_REQUIREMENT_UNMET")
    # Rule 24 -- production-window conflict.
    if kitchen_window_conflict(kitchen["id"], data["scheduled_start"], data["production_hours"]):
        fail("ERR_KITCHEN_WINDOW_CONFLICT")

    subtotal, _tier, logistics, discount, total = meal_order_cost_buildup(
        data["ordered_meals"], kitchen["per_meal_price_cents"])

    # Rule 29 -- the funding ceiling of the activation.
    refresh_incident(incident)
    if incident["spent_cents"] + total > incident["funding_ceiling_cents"]:
        fail("ERR_FUNDING_CEILING_EXCEEDED")
    # Rule 31 -- single-activation reference.
    same_incident(incident["id"], kitchen)

    row = make_row(
        incident_id=incident["id"],
        partner_kitchen_id=kitchen["id"],
        distribution_run_id=None,
        menu_name=data["menu_name"],
        dietary_tags=data["dietary_tags"],
        ordered_meals=data["ordered_meals"],
        scheduled_start=data["scheduled_start"],
        production_hours=data["production_hours"],
        status="PLACED",
        produced_meals=None,
        rejected_meals=None,
        accepted_meals=0,
        rework_count=0,
        quality_check_score=None,
        subtotal_cents=subtotal,
        logistics_fee_cents=logistics,
        volume_discount_cents=discount,
        provisional_cost_cents=total,
        final_cost_cents=None,
        placed_at=now(),
        ready_at=None,
        delivered_at=None,
        cancel_reason=None,
    )
    DB["meal_orders"][row["id"]] = row
    touch(kitchen)              # placing a batch bumps the kitchen's version by 1
    refresh_incident(incident)
    return row


def create_supplier(data):
    incident = ref_row("incidents", data["incident_id"])
    row = make_row(
        incident_id=incident["id"],
        producer_name=data["producer_name"],
        locality=data["locality"],
        product_categories=data["product_categories"],
        payment_terms_days=data["payment_terms_days"],
        status="PROSPECT",
        cash_flow_received_cents=0,
        reliability_score=0,
        delivered_purchase_count=0,
        disputed_purchase_count=0,
    )
    DB["suppliers"][row["id"]] = row
    refresh_supplier(row)
    return row


def create_ingredient_purchase(data):
    incident = ref_row("incidents", data["incident_id"])
    supplier = ref_row("suppliers", data["supplier_id"])
    kitchen = ref_row("partner_kitchens", data["partner_kitchen_id"])
    same_incident(incident["id"], supplier, kitchen)
    amount = round_half_up(dec(data["quantity_kg"]) * dec(data["unit_price_cents_per_kg"]))
    row = make_row(
        incident_id=incident["id"],
        supplier_id=supplier["id"],
        partner_kitchen_id=kitchen["id"],
        item_description=data["item_description"],
        quantity_kg=data["quantity_kg"],
        unit_price_cents_per_kg=data["unit_price_cents_per_kg"],
        amount_cents=amount,
        status="REQUESTED",
        requested_at=now(),
        delivered_at=None,
        paid_at=None,
        dispute_reason=None,
    )
    DB["ingredient_purchases"][row["id"]] = row
    return row


def create_distribution_site(data):
    incident = ref_row("incidents", data["incident_id"])
    row = make_row(
        incident_id=incident["id"],
        site_name=data["site_name"],
        site_type=data["site_type"],
        population_served=data["population_served"],
        daily_meal_request=data["daily_meal_request"],
        access_constraint=data["access_constraint"],
        status="REGISTERED",
        received_meals_total=0,
        skipped_stop_count=0,
        delivered_stop_count=0,
    )
    DB["distribution_sites"][row["id"]] = row
    return row


def create_distribution_run(data):
    incident = ref_row("incidents", data["incident_id"])
    kitchen = ref_row("field_kitchens", data["field_kitchen_id"])

    # Rule 23 -- the volunteer driver must be briefed.
    if not data["driver_safety_training_completed"]:
        fail("ERR_DRIVER_SAFETY_TRAINING_REQUIRED")
    # Rule 25 -- at most 3 runs per origin kitchen per UTC calendar day.
    bucket = day_bucket(data["planned_date"])
    same_day = sum(1 for run in DB["distribution_runs"].values()
                   if run["field_kitchen_id"] == kitchen["id"]
                   and day_bucket(run["planned_date"]) == bucket)
    if same_day >= 3:
        fail("ERR_KITCHEN_DAILY_RUN_CAP")
    # Rule 31 -- single-activation reference.
    same_incident(incident["id"], kitchen)

    row = make_row(
        incident_id=incident["id"],
        field_kitchen_id=kitchen["id"],
        driver_name=data["driver_name"],
        driver_phone=data["driver_phone"],
        driver_safety_training_completed=data["driver_safety_training_completed"],
        vehicle_type=data["vehicle_type"],
        planned_date=data["planned_date"],
        window_start=data["window_start"],
        window_end=data["window_end"],
        loaded_meals=0,
        fuel_cost_cents=data["fuel_cost_cents"],
        handling_cost_cents=data["handling_cost_cents"],
        status="PLANNED",
        total_cost_cents=data["fuel_cost_cents"] + data["handling_cost_cents"],
        unallocated_cost_cents=0,
        delivered_meals=0,
        returned_meals=0,
        completed_at=None,
        abort_reason=None,
    )
    DB["distribution_runs"][row["id"]] = row
    refresh_field_kitchen(kitchen)
    return row


def create_distribution_stop(data):
    run = ref_row("distribution_runs", data["distribution_run_id"])
    site = ref_row("distribution_sites", data["distribution_site_id"])

    # Rule 10 -- optimistic concurrency on the parent run.
    if data["expected_distribution_run_version"] != run["version"]:
        fail("ERR_STALE_VERSION")
    # Rule 21 -- a BLOCKED receiving site cannot be served.
    if site["access_constraint"] == "BLOCKED":
        fail("ERR_SITE_ACCESS_BLOCKED")
    # Rule 26 -- pending planned meals must stay within the loaded figure.
    pending_after = run_pending_planned_meals(run["id"]) + data["planned_meals"]
    if pending_after > (run.get("loaded_meals") or 0):
        fail("ERR_RUN_LOAD_EXCEEDS_CAPACITY")
    # Rule 27 -- stop_sequence is unique inside the run.
    for stop in DB["distribution_stops"].values():
        if stop["distribution_run_id"] == run["id"] \
                and stop["stop_sequence"] == data["stop_sequence"]:
            fail("ERR_DUPLICATE_STOP_SEQUENCE")
    # Rule 28 -- a receiving site appears at most once per run.
    for stop in DB["distribution_stops"].values():
        if stop["distribution_run_id"] == run["id"] \
                and stop["distribution_site_id"] == site["id"]:
            fail("ERR_DUPLICATE_STOP_SITE")
    # Rule 31 -- single-activation reference.
    same_incident(run["incident_id"], site)

    row = make_row(
        distribution_run_id=run["id"],
        distribution_site_id=site["id"],
        stop_sequence=data["stop_sequence"],
        planned_meals=data["planned_meals"],
        delivered_meals=0,
        allocated_cost_cents=0,
        status="PENDING",
        failure_reason=None,
        delivered_at=None,
    )
    DB["distribution_stops"][row["id"]] = row
    touch(run)                  # adding a stop bumps the run's version by 1
    refresh_distribution_run(run)
    return row


def create_donor_commitment(data):
    incident = ref_row("incidents", data["incident_id"])
    row = make_row(
        incident_id=incident["id"],
        donor_name=data["donor_name"],
        amount_cents=data["amount_cents"],
        earmark=data["earmark"],
        status="PLEDGED",
        received_at=None,
        allocated_cents=0,
        disbursed_cents=0,
        remaining_cents=data["amount_cents"],
    )
    DB["donor_commitments"][row["id"]] = row
    return row
