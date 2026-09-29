"""Per diem exposure and fleet utilization (PRD section 3.9)."""
import db
from services import money


def _input_movements(road_id):
    """Segments where this road is the handler, hire liable, OPEN or CLOSED."""
    return [
        m
        for m in db.movements.values()
        if m["handling_road_id"] == road_id
        and m["hire_liable"]
        and m["status"] in ("OPEN", "CLOSED")
    ]


def _accrue_open(movement, horizon):
    """Accrue an open segment as if it closed at ``horizon``: time only."""
    car = db.cars.get(movement["car_id"])
    if car is None:
        return 0
    car_type = db.car_types.get(car["car_type_id"])
    if car_type is None:
        return 0
    if horizon <= movement["start_at"]:
        return 0
    elapsed = money.elapsed_hours(movement["start_at"], horizon)
    charge_hours = money.chargeable_hours(elapsed, car_type["free_time_hours"])
    _, time_cents = money.time_component(car_type, charge_hours)
    return time_cents


def exposure_figures(road, variant="SNAPSHOT"):
    road_id = road["id"]
    horizon = db.now()
    if variant == "PROJECTED":
        horizon = horizon + db.hours(db.PROJECTION_HORIZON_HOURS)

    open_count = 0
    open_accrued = 0
    closed_unsettled = 0
    for m in _input_movements(road_id):
        if m["status"] == "OPEN":
            open_count += 1
            open_accrued += _accrue_open(m, horizon)
        else:
            closed_unsettled += int(m["net_hire_cents"] or 0)

    settled_paid = 0
    for c in db.cycles.values():
        if c["payer_road_id"] == road_id and c["status"] == "SETTLED":
            settled_paid += int(c["net_settlement_cents"] or 0)

    exposure_cents = open_accrued + closed_unsettled - settled_paid
    return {
        "variant_applied": variant,
        "exposure_cents": exposure_cents,
        "open_movement_count": open_count,
        "closed_unsettled_cents": closed_unsettled,
        "settled_paid_cents": settled_paid,
    }


def fleet_figures(road):
    road_id = road["id"]
    owned = [c for c in db.cars.values() if c["owner_road_id"] == road_id]
    owned_car_count = len(owned)
    on_foreign = 0
    bad_order = 0
    serviceable_foreign = 0
    for c in owned:
        away = c["current_handling_road_id"] != road_id
        if away:
            on_foreign += 1
        if c["mechanical_status"] in ("BAD_ORDER", "UNDER_REPAIR"):
            bad_order += 1
        if away and c["mechanical_status"] == "SERVICEABLE":
            serviceable_foreign += 1
    return {
        "owned_car_count": owned_car_count,
        "on_foreign_count": on_foreign,
        "bad_order_count": bad_order,
        "serviceable_foreign_count": serviceable_foreign,
        "utilization_pct": money.utilization_pct(serviceable_foreign, owned_car_count),
    }


def snapshot_cents(road):
    return exposure_figures(road, "SNAPSHOT")["exposure_cents"]


def read(road, variant):
    from services import serialize

    figures = exposure_figures(road, variant)
    fleet = fleet_figures(road)
    limit = int(road["per_diem_credit_limit_cents"])
    return {
        "railroad_id": road["id"],
        "variant_applied": figures["variant_applied"],
        "exposure_cents": figures["exposure_cents"],
        "open_movement_count": figures["open_movement_count"],
        "closed_unsettled_cents": figures["closed_unsettled_cents"],
        "settled_paid_cents": figures["settled_paid_cents"],
        "credit_limit_cents": limit,
        "credit_headroom_cents": limit - figures["exposure_cents"],
        "owned_car_count": fleet["owned_car_count"],
        "on_foreign_count": fleet["on_foreign_count"],
        "bad_order_count": fleet["bad_order_count"],
        "serviceable_foreign_count": fleet["serviceable_foreign_count"],
        "utilization_pct": money.num2(fleet["utilization_pct"]),
        "foreign_car_balance": serialize.foreign_car_balance(road["id"]),
    }
