"""The four transitive cascades plus the shared invoice constructor."""
from core import new_record, ordered, store, touch
import calc
import derive


def supersede_reviews(plan_id):
    for r in ordered(store.engineering_reviews):
        if r["lift_plan_id"] == plan_id and r["status"] in ("UNDER_REVIEW", "CHANGES_REQUESTED",
                                                            "STAMPED"):
            r["status"] = "SUPERSEDED"
            touch(r)


def recompute_plan_standby(plan):
    plan["standby_hours_billable"] = calc.standby_merged_hours(plan["id"])


def clear_plan_configuration(plan):
    """Full teardown written by the gear-integrity demotion to SURVEYED."""
    plan["rigging_verified"] = False
    plan["lift_class"] = "NOT_CLASSIFIED"
    plan["utilization_pct"] = 0
    plan["net_capacity_lb"] = 0
    plan["chart_gross_capacity_lb"] = 0
    plan["hoist_line_capacity_lb"] = 0
    plan["total_load_lb"] = 0
    plan["rigging_weight_lb"] = sum(
        store.rigging_gear[a["gear_id"]]["weight_lb"]
        for a in derive.plan_active_assignments(plan["id"]))
    plan["bearing_variant"] = "NONE"
    plan["per_outrigger_load_lb"] = 0
    plan["bearing_pressure_psf"] = 0
    plan["matting_required"] = False
    plan["mat_area_required_sqft"] = 0
    plan["mat_count"] = 0
    plan["crane_id"] = None
    plan["operator_id"] = None
    plan["rigger_id"] = None
    plan["escort_required"] = False
    plan["permit_required"] = bool(plan["road_closure_requested"])


def gear_left_serviceable(gear):
    """Hops 2-4 of the gear-integrity cascade (FAIL / RETIRE / retire endpoint)."""
    touched_plan_ids = []
    for a in ordered(store.gear_assignments):
        if a["gear_id"] != gear["id"] or a["status"] != "ACTIVE":
            continue
        a["status"] = "VOIDED"
        touch(a)
        if a["lift_plan_id"] not in touched_plan_ids:
            touched_plan_ids.append(a["lift_plan_id"])

    for plan_id in touched_plan_ids:
        plan = store.lift_plans.get(plan_id)
        if plan is None:
            continue
        if plan["field_status"] != "NOT_MOBILIZED":
            continue
        if plan["plan_status"] not in ("CONFIGURED", "PENDING_ENGINEERING", "APPROVED", "RELEASED"):
            continue
        plan["plan_status"] = "SURVEYED"
        clear_plan_configuration(plan)
        touch(plan)
        supersede_reviews(plan["id"])


def crane_out_of_service_cascade(crane):
    """Hops 2-3 of the crane-out-of-service cascade."""
    for plan in ordered(store.lift_plans):
        if plan["crane_id"] != crane["id"]:
            continue
        if plan["field_status"] != "NOT_MOBILIZED":
            continue
        if plan["plan_status"] not in ("APPROVED", "RELEASED"):
            continue
        plan["plan_status"] = "CONFIGURED"
        touch(plan)
        for permit in ordered(store.permits):
            if permit["lift_plan_id"] == plan["id"] and permit["status"] == "APPROVED":
                permit["status"] = "SUSPENDED"
                touch(permit)


def sync_clock_driven_crane_expiry():
    """A crane whose annual inspection lapses on the logical clock runs the same cascade."""
    for crane in ordered(store.cranes):
        if crane["out_of_service_flag"]:
            continue
        if derive.crane_status(crane) == "OUT_OF_SERVICE":
            crane_out_of_service_cascade(crane)


def build_invoice(plan, billing_mode, on_site_hours, travel_hours, travel_miles,
                  lump_sum_cents, system_generated=False, status="DRAFT"):
    inv = new_record({
        "lift_plan_id": plan["id"],
        "customer_id": plan["customer_id"],
        "billing_mode": billing_mode,
        "on_site_hours": float(on_site_hours),
        "travel_hours": float(travel_hours),
        "travel_miles": float(travel_miles),
        "lump_sum_cents": int(lump_sum_cents),
        "standby_hours_source": plan["standby_hours_billable"],
        "billable_hours": 0,
        "regular_hours": 0,
        "overtime_hours": 0,
        "line_regular_cents": 0,
        "line_overtime_cents": 0,
        "line_standby_cents": 0,
        "line_travel_cents": 0,
        "line_mobdemob_cents": 0,
        "line_lump_sum_cents": 0,
        "line_permit_cancellation_cents": 0,
        "subtotal_cents": 0,
        "discount_pct": 0,
        "discount_cents": 0,
        "fuel_surcharge_cents": 0,
        "total_cents": 0,
        "system_generated": system_generated,
        "status": status,
    })
    calc.compute_invoice(inv, plan)
    store.invoices[inv["id"]] = inv
    return inv


def cancel_plan(plan, reason):
    """The depth-4 LiftPlan -> Permit -> Invoice -> Customer chain."""
    plan["plan_status"] = "CANCELLED"
    plan["cancellation_reason"] = reason

    for a in ordered(store.gear_assignments):
        if a["lift_plan_id"] == plan["id"] and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            touch(a)

    supersede_reviews(plan["id"])

    fee_total = 0
    for permit in ordered(store.permits):
        if permit["lift_plan_id"] != plan["id"]:
            continue
        if permit["status"] not in ("SUBMITTED", "APPROVED", "SUSPENDED"):
            continue
        was_approved = permit["status"] == "APPROVED"
        permit["status"] = "VOIDED"
        if was_approved:
            permit["cancellation_fee_cents"] = calc.permit_cancellation_fee(
                permit["permit_fee_cents"])
            fee_total += permit["cancellation_fee_cents"]
        touch(permit)

    if fee_total > 0:
        build_invoice(plan, "LUMP_SUM", 0, 0, 0, 0, system_generated=True, status="ISSUED")

    touch(plan)
