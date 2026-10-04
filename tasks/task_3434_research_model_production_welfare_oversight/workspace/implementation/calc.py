"""The eight PRD calculation rules (section 1.3 of the scaffold / section 3
of the PRD) plus entity serializers that embed the computed read fields."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db, fmt_dt, now

SECONDS_PER_DAY = 86400
DAYS_PER_WEEK = 7
SURVIVAL_RATE = Decimal("0.8")
CAGE_DENSITY = 5
MIN_ORDER_LEAD_DAYS = 14
MAX_TRANSIT_HOURS = 48
SANITIZATION_WINDOW_HOURS = 72
TIER1_QTY = 100
TIER1_DISCOUNT = Decimal("0.10")
TIER2_QTY = 250
TIER2_DISCOUNT = Decimal("0.20")
IMMUNO_SURCHARGE = Decimal("0.25")
VF_PREMIUM = Decimal("0.20")
GERM_FREE_PREMIUM = Decimal("0.40")
LIGHT_MAX_G = 15
HEAVY_MIN_G = 25
LIGHT_PER_BOX = 10
STANDARD_PER_BOX = 6
HEAVY_PER_BOX = 4
VIABILITY_FLOOR = 70

GROSS_STATUSES = {"SOURCING", "BACKORDERED", "ALLOCATED", "SCHEDULED", "SHIPPED", "DELIVERED"}
LIVE_COHORT_STATUSES = {"WEANED", "HOLD", "PARTIALLY_ALLOCATED", "FULLY_ALLOCATED"}


def age_weeks(birth, as_of):
    """cohort_age_weeks: floor elapsed to whole days, then to whole weeks."""
    secs = (as_of - birth).total_seconds()
    age_days = math.floor(secs / SECONDS_PER_DAY)
    return math.floor(age_days / DAYS_PER_WEEK)


def cohort_reserved(cohort_id):
    m = f = 0
    for a in db["allocations"].values():
        if a["cohort_id"] == cohort_id and a["status"] == "RESERVED":
            m += a["qty_male"]
            f += a["qty_female"]
    return m, f


def cohort_has_reserved(cohort_id):
    for a in db["allocations"].values():
        if a["cohort_id"] == cohort_id and a["status"] == "RESERVED":
            return True
    return False


def order_allocated(order_id):
    m = f = 0
    for a in db["allocations"].values():
        if a["order_id"] == order_id and a["status"] == "RESERVED":
            m += a["qty_male"]
            f += a["qty_female"]
    return m, f


def colony_forecast(colony):
    """colony_availability_forecast: (CONFIRMED_ONLY, PROJECTED) variants."""
    confirmed = 0
    for c in db["cohorts"].values():
        if c["colony_id"] == colony["id"] and c["status"] in ("HOLD", "PARTIALLY_ALLOCATED"):
            rm, rf = cohort_reserved(c["id"])
            confirmed += c["count_male"] + c["count_female"] - rm - rf
    projected = confirmed
    if colony["lifecycle_status"] == "PRODUCTION" and colony["genetic_status"] != "DRIFT_DETECTED":
        strain = db["strains"].get(colony["strain_id"])
        litter = strain["typical_litter_size"] if strain else 0
        projected += int((Decimal(colony["breeding_pair_count"]) * Decimal(litter) * SURVIVAL_RATE) // 1)
    return confirmed, projected


def credit_positions(customer):
    """customer_credit_positions: (NET_BILLED outstanding, GROSS exposure).

    outstanding_balance_cents is the posted-billing accumulator (a CLOSED
    order's billed amount remains owed, per PRD 3.8); credit_exposure_cents
    is derived live from the order status set."""
    outstanding = customer.get("_billed_cents", 0)
    exposure = 0
    for o in db["orders"].values():
        if (
            o["customer_id"] == customer["id"]
            and o["status"] in GROSS_STATUSES
            and o["quoted_total_cents"] is not None
        ):
            exposure += o["quoted_total_cents"]
    return outstanding, exposure


def order_quote(order, strain):
    """order_quote: tier discount first (round half-up), surcharges second
    (round half-up). Integer cents."""
    qty = order["quantity_male"] + order["quantity_female"]
    subtotal = Decimal(qty * strain["base_price_cents"])
    if qty >= TIER2_QTY:
        disc = TIER2_DISCOUNT
    elif qty >= TIER1_QTY:
        disc = TIER1_DISCOUNT
    else:
        disc = Decimal("0")
    discounted = (subtotal * (Decimal("1") - disc)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    surcharge = Decimal("0")
    if strain["immune_class"] == "IMMUNOCOMPROMISED":
        surcharge += IMMUNO_SURCHARGE
    if order["min_health_status"] == "GERM_FREE":
        surcharge += GERM_FREE_PREMIUM
    elif order["min_health_status"] == "VF":
        surcharge += VF_PREMIUM
    total = (discounted * (Decimal("1") + surcharge)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(total)


def box_count_for_order(order_id):
    """shipment_box_count: ceiling per (allocation, sex) line, then sum."""
    boxes = 0
    for a in db["allocations"].values():
        if a["order_id"] != order_id or a["status"] != "RESERVED":
            continue
        cohort = db["cohorts"].get(a["cohort_id"])
        if cohort is None:
            continue
        for qty_key, w_key in (("qty_male", "avg_weight_g_male"), ("qty_female", "avg_weight_g_female")):
            qty = a[qty_key]
            if qty <= 0:
                continue
            w = cohort[w_key]
            if w < LIGHT_MAX_G:
                per = LIGHT_PER_BOX
            elif w >= HEAVY_MIN_G:
                per = HEAVY_PER_BOX
            else:
                per = STANDARD_PER_BOX
            boxes += math.ceil(qty / per)
    return boxes


def occupied_cages(room_id):
    """room_occupied_cages: breeding pairs of non-RETIRED colonies plus the
    per-cohort ceiling of live headcount / CAGE_DENSITY."""
    total = 0
    colony_ids = set()
    for co in db["colonies"].values():
        if co["room_id"] == room_id:
            colony_ids.add(co["id"])
            if co["lifecycle_status"] != "RETIRED":
                total += co["breeding_pair_count"]
    for c in db["cohorts"].values():
        if c["colony_id"] in colony_ids and c["status"] in LIVE_COHORT_STATUSES:
            total += math.ceil((c["count_male"] + c["count_female"]) / CAGE_DENSITY)
    return total


def protocol_animals_used(protocol_id):
    """protocol_animals_used: monotonic accumulator (2 per breeding pair plus
    each cohort's immutable initial_count_total)."""
    total = 0
    colony_ids = set()
    for co in db["colonies"].values():
        if co["protocol_id"] == protocol_id:
            total += 2 * co["breeding_pair_count"]
            colony_ids.add(co["id"])
    for c in db["cohorts"].values():
        if c["colony_id"] in colony_ids:
            total += c["initial_count_total"]
    return total


def eligible_projected_supply(order):
    """PROJECTED availability summed over eligible colonies of the order's
    strain (SUBMITTED -> SOURCING feasibility, PRD 3.6)."""
    total = 0
    for co in db["colonies"].values():
        if co["strain_id"] != order["strain_id"]:
            continue
        room = db["rooms"].get(co["room_id"])
        if room is None or room["status"] != "ACTIVE":
            continue
        fac = db["facilities"].get(room["facility_id"])
        if fac is None or fac["registration_status"] != "REGISTERED":
            continue
        if co["genetic_status"] == "DRIFT_DETECTED":
            continue
        from validation import BARRIER_RANK
        if BARRIER_RANK[room["barrier_level"]] < BARRIER_RANK[order["min_health_status"]]:
            continue
        _, projected = colony_forecast(co)
        total += projected
    return total


# --------------------------------------------------------------------------
# Serializers (computed read fields embedded).
# --------------------------------------------------------------------------

def _fmt_or_none(dt):
    return fmt_dt(dt) if dt is not None else None


def ser_facility(f):
    return {
        "id": f["id"],
        "name": f["name"],
        "site_code": f["site_code"],
        "registration_number": f["registration_number"],
        "registration_status": f["registration_status"],
        "registration_expires_at": _fmt_or_none(f["registration_expires_at"]),
        "suspension_reason": f["suspension_reason"],
        "created_at": fmt_dt(f["created_at"]),
        "updated_at": fmt_dt(f["updated_at"]),
        "version": f["version"],
    }


def ser_room(r):
    return {
        "id": r["id"],
        "facility_id": r["facility_id"],
        "room_code": r["room_code"],
        "barrier_level": r["barrier_level"],
        "excluded_agents": r["excluded_agents"],
        "cage_capacity": r["cage_capacity"],
        "occupied_cages": occupied_cages(r["id"]),
        "status": r["status"],
        "quarantined_at": _fmt_or_none(r["quarantined_at"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_strain(s):
    return {
        "id": s["id"],
        "strain_code": s["strain_code"],
        "species": s["species"],
        "immune_class": s["immune_class"],
        "breeding_type": s["breeding_type"],
        "min_barrier_level": s["min_barrier_level"],
        "gestation_days": s["gestation_days"],
        "wean_age_days": s["wean_age_days"],
        "typical_litter_size": s["typical_litter_size"],
        "base_price_cents": s["base_price_cents"],
        "created_at": fmt_dt(s["created_at"]),
    }


def ser_colony(co):
    confirmed, projected = colony_forecast(co)
    return {
        "id": co["id"],
        "room_id": co["room_id"],
        "strain_id": co["strain_id"],
        "protocol_id": co["protocol_id"],
        "breeding_pair_count": co["breeding_pair_count"],
        "generation_number": co["generation_number"],
        "lifecycle_status": co["lifecycle_status"],
        "genetic_status": co["genetic_status"],
        "last_snp_panel_at": _fmt_or_none(co["last_snp_panel_at"]),
        "snp_panel_interval_weeks": co["snp_panel_interval_weeks"],
        "confirmed_available_count": confirmed,
        "projected_pipeline_count": projected,
        "created_at": fmt_dt(co["created_at"]),
        "updated_at": fmt_dt(co["updated_at"]),
        "version": co["version"],
    }


def ser_cohort(c):
    rm, rf = cohort_reserved(c["id"])
    return {
        "id": c["id"],
        "colony_id": c["colony_id"],
        "birth_date": fmt_dt(c["birth_date"]),
        "count_male": c["count_male"],
        "count_female": c["count_female"],
        "initial_count_total": c["initial_count_total"],
        "reserved_male": rm,
        "reserved_female": rf,
        "avg_weight_g_male": c["avg_weight_g_male"],
        "avg_weight_g_female": c["avg_weight_g_female"],
        "health_status": c["health_status"],
        "status": c["status"],
        "age_weeks": age_weeks(c["birth_date"], now()),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_health_screen(h):
    return {
        "id": h["id"],
        "room_id": h["room_id"],
        "panel_type": h["panel_type"],
        "scheduled_at": fmt_dt(h["scheduled_at"]),
        "status": h["status"],
        "results": h["results"],
        "resulted_at": _fmt_or_none(h["resulted_at"]),
        "created_at": fmt_dt(h["created_at"]),
    }


def ser_customer(cu):
    outstanding, exposure = credit_positions(cu)
    return {
        "id": cu["id"],
        "institution_name": cu["institution_name"],
        "account_number": cu["account_number"],
        "credit_limit_cents": cu["credit_limit_cents"],
        "account_status": cu["account_status"],
        "accepted_min_health_status": cu["accepted_min_health_status"],
        "is_commercial": cu["is_commercial"],
        "outstanding_balance_cents": outstanding,
        "credit_exposure_cents": exposure,
        "created_at": fmt_dt(cu["created_at"]),
        "updated_at": fmt_dt(cu["updated_at"]),
        "version": cu["version"],
    }


def ser_order(o):
    am, af = order_allocated(o["id"])
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "strain_id": o["strain_id"],
        "quantity_male": o["quantity_male"],
        "quantity_female": o["quantity_female"],
        "min_age_weeks": o["min_age_weeks"],
        "max_age_weeks": o["max_age_weeks"],
        "min_weight_g": o["min_weight_g"],
        "max_weight_g": o["max_weight_g"],
        "required_delivery_date": fmt_dt(o["required_delivery_date"]),
        "min_health_status": o["min_health_status"],
        "status": o["status"],
        "quoted_total_cents": o["quoted_total_cents"],
        "allocated_male": am,
        "allocated_female": af,
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def ser_allocation(a):
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "cohort_id": a["cohort_id"],
        "qty_male": a["qty_male"],
        "qty_female": a["qty_female"],
        "status": a["status"],
        "created_at": fmt_dt(a["created_at"]),
    }


def ser_shipment(s):
    return {
        "id": s["id"],
        "order_id": s["order_id"],
        "vehicle_code": s["vehicle_code"],
        "vehicle_barrier_cert": s["vehicle_barrier_cert"],
        "sanitized_at": fmt_dt(s["sanitized_at"]),
        "departure_date": fmt_dt(s["departure_date"]),
        "planned_arrival_date": fmt_dt(s["planned_arrival_date"]),
        "actual_arrival_at": _fmt_or_none(s["actual_arrival_at"]),
        "box_count": s["box_count"],
        "received_male": s["received_male"],
        "received_female": s["received_female"],
        "status": s["status"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_protocol(p):
    return {
        "id": p["id"],
        "facility_id": p["facility_id"],
        "protocol_number": p["protocol_number"],
        "pi_name": p["pi_name"],
        "species": p["species"],
        "approved_animal_quota": p["approved_animal_quota"],
        "animals_used": protocol_animals_used(p["id"]),
        "effective_date": fmt_dt(p["effective_date"]),
        "expiration_date": fmt_dt(p["expiration_date"]),
        "submitted_by_user_id": p["submitted_by_user_id"],
        "status": p["status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_inspection(i):
    return {
        "id": i["id"],
        "facility_id": i["facility_id"],
        "customer_id": i["customer_id"],
        "inspection_type": i["inspection_type"],
        "scheduled_date": fmt_dt(i["scheduled_date"]),
        "findings": i["findings"],
        "corrective_deadline": _fmt_or_none(i["corrective_deadline"]),
        "reported_by_user_id": i["reported_by_user_id"],
        "status": i["status"],
        "created_at": fmt_dt(i["created_at"]),
    }


def ser_contract(c):
    return {
        "id": c["id"],
        "customer_id": c["customer_id"],
        "contract_type": c["contract_type"],
        "source_strain_id": c["source_strain_id"],
        "new_strain_spec": c["new_strain_spec"],
        "ip_ownership": c["ip_ownership"],
        "exclusivity_fee_cents": c["exclusivity_fee_cents"],
        "royalty_rate_pct": c["royalty_rate_pct"],
        "straw_count": c["straw_count"],
        "viability_pct": c["viability_pct"],
        "generated_strain_id": c["generated_strain_id"],
        "milestone_status": c["milestone_status"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }
