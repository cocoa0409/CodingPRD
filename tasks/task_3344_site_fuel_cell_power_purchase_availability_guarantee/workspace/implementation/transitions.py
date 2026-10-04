"""State machines, cascades and deferred actions."""

from datetime import timedelta

import calc
import constants as C
import store
from errors import (
    ERR_DRAW_POSITION_BELOW_RESUME, ERR_INVALID_STATE, ERR_SITE_FROZEN,
    ERR_TRANSFER_BLOCKED, ApiError,
)


# --- transition records ------------------------------------------------------
def add_transition(ppa, from_state, to_state, trigger_code, actor_role):
    record = {
        "id": store.new_id(),
        "created_at": store.now_iso(),
        "_seq": store.next_seq(),
        "ppa_id": ppa["id"],
        "from_state": from_state,
        "to_state": to_state,
        "trigger_code": trigger_code,
        "actor_role": actor_role,
        "transition_reversed": False,
    }
    store.transitions[record["id"]] = record
    return record


def latest_transition(ppa):
    rows = store.by_created(store.ppa_transitions(ppa["id"]))
    return rows[-1] if rows else None


# --- service plan helpers ----------------------------------------------------
def plan_of(ppa):
    plan_id = ppa.get("assigned_service_plan_id")
    return store.get_service_plan(plan_id) if plan_id else None


def set_plan_state(plan, state):
    plan["lifecycle_state"] = state


def suspend_plans_of(ppa):
    plan = plan_of(ppa)
    if plan is None:
        return plan
    if plan.get("lifecycle_state") in ("SERVICE_ACTIVE", "SERVICE_MAINTENANCE_WINDOW_OPEN"):
        set_plan_state(plan, "SERVICE_SUSPENDED")
    if plan.get("module_replacement_stage") == "REPLACEMENT_SCHEDULED":
        plan["module_replacement_stage"] = "REPLACEMENT_BLOCKED"
    store.touch(plan)
    return plan


def restore_plans_of(ppa):
    plan = plan_of(ppa)
    if plan is None:
        return plan
    if plan.get("lifecycle_state") == "SERVICE_SUSPENDED":
        set_plan_state(plan, "SERVICE_ACTIVE")
    if plan.get("module_replacement_stage") == "REPLACEMENT_BLOCKED" \
            and plan.get("lifecycle_state") == "SERVICE_ACTIVE":
        plan["module_replacement_stage"] = "REPLACEMENT_SCHEDULED"
    store.touch(plan)
    return plan


def archive_plan_of(ppa):
    plan = plan_of(ppa)
    if plan is None:
        return plan
    if plan.get("lifecycle_state") != "SERVICE_ARCHIVED":
        set_plan_state(plan, "SERVICE_ARCHIVED")
        store.touch(plan)
    return plan


# --- contract activation -----------------------------------------------------
def activate(ppa, actor_role):
    site = store.get_site(ppa["site_id"])
    customer = store.get_customer(ppa["customer_id"])
    site_status = site.get("status") if site else None
    if site_status == "SITE_SUSPENDED":
        raise ApiError(ERR_SITE_FROZEN, "site is suspended", 409)
    if customer is None or customer.get("status") != "CUSTOMER_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "customer is not active", 409)
    if ppa.get("state") != "PPA_DRAFT":
        raise ApiError(ERR_INVALID_STATE, "contract is not a draft", 409)
    if not (int(site.get("active_ppa_count") or 0) == 0
            or site.get("lifecycle_state") == "RESOURCE_DRAWING"):
        raise ApiError(ERR_INVALID_STATE, "site is not in draw posture", 409)

    ppa["state"] = "PPA_ACTIVE"
    ppa["state_entered_at"] = store.now_iso()
    add_transition(ppa, "PPA_DRAFT", "PPA_ACTIVE", "PPA_ACTIVATED", actor_role)

    site["lifecycle_state"] = "RESOURCE_DRAWING"

    plan = {
        "ppa_id": ppa["id"],
        "remote_monitoring_status": "MONITORING_LINKED",
        "lifecycle_state": "SERVICE_PLAN_DRAFT",
        "module_replacement_stage": "REPLACEMENT_NONE",
        "radius_buffer_m": 0.0,
        "monitoring_degraded_at": None,
        "monitoring_degraded_days": 0,
        "rollout_schedule_compliant": True,
        "window_start_iso8601": None,
        "window_end_iso8601": None,
        "dispatch_hold": False,
    }
    store.create(store.service_plans, plan)
    ppa["assigned_service_plan_id"] = plan["id"]
    set_plan_state(plan, "SERVICE_ACTIVE")
    store.touch(plan)
    # PRD §3.7: "A plan moves from `SERVICE_PLAN_DRAFT` to `SERVICE_ACTIVE`
    # when its contract enters `PPA_ACTIVE` in the same transaction". A plan
    # hand-created against the contract while it was still a draft therefore
    # rides the same edge as the one the cascade just made.
    for other in store.ppa_plans(ppa["id"]):
        if other.get("id") != plan["id"] \
                and other.get("lifecycle_state") == "SERVICE_PLAN_DRAFT":
            set_plan_state(other, "SERVICE_ACTIVE")
            store.touch(other)

    calc.recompute_site(site)
    calc.recompute_ppa(ppa)
    calc.recompute_customer(customer)
    store.touch(ppa)
    store.touch(site)
    store.touch(customer)
    return ppa


# --- site freeze / unfreeze --------------------------------------------------
def freeze(site, reason, actor_role):
    if site.get("status") != "SITE_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "site is not active", 409)
    live = [p for p in store.site_ppas(site["id"]) if p.get("state") == "PPA_ACTIVE"]
    if not live:
        raise ApiError(ERR_INVALID_STATE, "site has no active contracts", 409)

    site["status"] = "SITE_SUSPENDED"
    affected_customers = set()
    for ppa in live:
        ppa["state"] = "PPA_SUSPENDED"
        ppa["state_entered_at"] = store.now_iso()
        add_transition(ppa, "PPA_ACTIVE", "PPA_SUSPENDED", "SITE_FROZEN", actor_role)
        suspend_plans_of(ppa)
        calc.recompute_ppa(ppa)
        store.touch(ppa)
        if ppa.get("customer_id"):
            affected_customers.add(ppa["customer_id"])

    if reason == "GRID_INTERCONNECT_FAILURE" and site.get("lifecycle_state") == "RESOURCE_DRAWING":
        site["lifecycle_state"] = "RESOURCE_CLOSED"

    for customer_id in affected_customers:
        customer = store.get_customer(customer_id)
        if customer is None:
            continue
        if customer.get("credit_tier") == "CREDIT_SUBSTANDARD":
            customer["hold_armed"] = True
        if reason in ("NONPAYMENT", "CUSTOMER_REQUEST") and customer.get("status") == "CUSTOMER_ACTIVE":
            customer["status"] = "CUSTOMER_SUSPENDED"
        calc.recompute_customer(customer)
        store.touch(customer)

    calc.recompute_site(site)
    store.touch(site)
    return site


def unfreeze(site, actor_role):
    if site.get("status") != "SITE_SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "site is not suspended", 409)
    if float(site.get("draw_position_therms") or 0) < C.MIN_RESUME_DRAW_THERMS:
        raise ApiError(ERR_DRAW_POSITION_BELOW_RESUME,
                       "draw position is below the resume floor", 422)
    for plan in store.site_plans(site["id"]):
        if plan.get("lifecycle_state") == "SERVICE_MAINTENANCE_WINDOW_OPEN":
            raise ApiError(ERR_INVALID_STATE, "a service plan is in a maintenance window", 409)
    suspended = [p for p in store.site_ppas(site["id"]) if p.get("state") == "PPA_SUSPENDED"]
    for ppa in suspended:
        customer = store.get_customer(ppa.get("customer_id"))
        if customer is not None and customer.get("renewal_stage") == "RENEWAL_DECLINED":
            raise ApiError(ERR_INVALID_STATE, "a customer has declined renewal", 409)

    site["status"] = "SITE_ACTIVE"
    affected_customers = set()
    for ppa in suspended:
        ppa["state"] = "PPA_ACTIVE"
        ppa["state_entered_at"] = store.now_iso()
        add_transition(ppa, "PPA_SUSPENDED", "PPA_ACTIVE", "SITE_UNFROZEN", actor_role)
        restore_plans_of(ppa)
        calc.recompute_ppa(ppa)
        store.touch(ppa)
        if ppa.get("customer_id"):
            affected_customers.add(ppa["customer_id"])

    for customer_id in affected_customers:
        customer = store.get_customer(customer_id)
        if customer is None:
            continue
        if customer.get("status") == "CUSTOMER_SUSPENDED":
            customer["status"] = "CUSTOMER_ACTIVE"
        if customer.get("credit_tier") != "CREDIT_SUBSTANDARD":
            customer["hold_armed"] = False
        calc.recompute_customer(customer)
        store.touch(customer)

    if site.get("lifecycle_state") == "RESOURCE_CLOSED":
        site["lifecycle_state"] = "RESOURCE_AVAILABLE"
    calc.recompute_site(site)
    store.touch(site)
    return site


# --- exit / cure / terminate / renew -----------------------------------------
def request_exit(ppa, actor_role):
    if ppa.get("transfer_stage") == "TRANSFER_BLOCKED":
        raise ApiError(ERR_TRANSFER_BLOCKED, "contract is blocked from moving", 409)
    state = ppa.get("state")
    if state not in ("PPA_ACTIVE", "PPA_SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "contract does not admit an exit request", 409)
    site = store.get_site(ppa["site_id"])
    if state == "PPA_ACTIVE" and (site is None or site.get("status") != "SITE_ACTIVE"):
        raise ApiError(ERR_SITE_FROZEN, "site is suspended", 409)

    ppa["state"] = "PPA_EXIT_PENDING"
    ppa["state_entered_at"] = store.now_iso()
    calc.recompute_ppa(ppa)
    trigger = "EXIT_REQUESTED" if state == "PPA_ACTIVE" else "EXIT_REQUESTED_FROM_SUSPENDED"
    add_transition(ppa, state, "PPA_EXIT_PENDING", trigger, actor_role)
    ppa["exit_deadline_iso8601"] = store.ts(
        store.parse_dt(ppa["state_entered_at"])
        + timedelta(days=int(ppa.get("customer_cure_deadline_days") or 0)))
    store.touch(ppa)
    if site is not None:
        calc.recompute_site(site)
        store.touch(site)
    return ppa


def cure(ppa, actor_role):
    if ppa.get("state") != "PPA_EXIT_PENDING":
        raise ApiError(ERR_INVALID_STATE, "contract is not pending exit", 409)
    site = store.get_site(ppa["site_id"])
    if site is None or site.get("status") != "SITE_ACTIVE":
        raise ApiError(ERR_SITE_FROZEN, "site is suspended", 409)
    deadline = store.parse_dt(ppa["state_entered_at"]) + timedelta(
        days=int(ppa.get("customer_cure_deadline_days") or 0))
    if store.clock() > deadline:
        raise ApiError(ERR_INVALID_STATE, "the cure window has lapsed", 409)

    ppa["state"] = "PPA_ACTIVE"
    ppa["state_entered_at"] = store.now_iso()
    previous = latest_transition(ppa)
    if previous is not None:
        previous["transition_reversed"] = True
    add_transition(ppa, "PPA_EXIT_PENDING", "PPA_ACTIVE", "EXIT_CURED", actor_role)
    ppa["exit_deadline_iso8601"] = None
    calc.recompute_ppa(ppa)
    # PRD §3.8: on acceptance "its `exit_fee_cents` is reset to zero". The
    # fan-out above re-derives the field from the interconnection basis, so the
    # reset has to land after it to be the value the cure leaves behind.
    ppa["exit_fee_cents"] = 0
    store.touch(ppa)
    calc.recompute_site(site)
    store.touch(site)
    return ppa


def terminate(ppa, actor_role):
    state = ppa.get("state")
    if state == "PPA_TERMINATED":
        raise ApiError("ERR_ALREADY_TERMINAL", "contract is already terminated", 409)
    if state != "PPA_EXIT_PENDING":
        raise ApiError(ERR_INVALID_STATE, "contract is not pending exit", 409)
    deadline = store.parse_dt(ppa["state_entered_at"]) + timedelta(
        days=int(ppa.get("customer_cure_deadline_days") or 0))
    if store.clock() <= deadline:
        raise ApiError(ERR_INVALID_STATE, "the cure window has not lapsed", 409)

    site = store.get_site(ppa["site_id"])
    ppa["state"] = "PPA_TERMINATED"
    ppa["state_entered_at"] = store.now_iso()
    ppa["exit_deadline_iso8601"] = None
    add_transition(ppa, "PPA_EXIT_PENDING", "PPA_TERMINATED", "PPA_TERMINATED", actor_role)
    archive_plan_of(ppa)
    calc.recompute_ppa(ppa)
    store.touch(ppa)

    if site is not None:
        calc.recompute_site(site)
        if int(site.get("active_ppa_count") or 0) == 0 \
                and float(site.get("draw_position_therms") or 0) > 0:
            site["lifecycle_state"] = "RESOURCE_AVAILABLE"
        store.touch(site)
    customer = store.get_customer(ppa.get("customer_id"))
    if customer is not None:
        calc.recompute_customer(customer)
        store.touch(customer)
    return ppa


def renew(ppa, actor_role):
    if ppa.get("state") != "PPA_TERMINATED":
        raise ApiError(ERR_INVALID_STATE, "contract is not terminated", 409)
    if ppa.get("transfer_stage") == "TRANSFER_BLOCKED":
        raise ApiError(ERR_TRANSFER_BLOCKED, "contract is blocked from moving", 409)
    customer = store.get_customer(ppa.get("customer_id"))
    site = store.get_site(ppa["site_id"])
    if customer is None or customer.get("status") != "CUSTOMER_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "customer is not active", 409)
    if customer.get("renewal_stage") != "RENEWAL_ACCEPTED":
        raise ApiError(ERR_INVALID_STATE, "renewal has not been accepted", 409)
    if site is None or site.get("status") != "SITE_ACTIVE":
        raise ApiError(ERR_SITE_FROZEN, "site is suspended", 409)

    ppa["state"] = "PPA_ACTIVE"
    ppa["state_entered_at"] = store.now_iso()
    add_transition(ppa, "PPA_TERMINATED", "PPA_ACTIVE", "PPA_RENEWED", actor_role)
    site["lifecycle_state"] = "RESOURCE_DRAWING"
    customer["renewal_stage"] = "RENEWAL_NONE"
    plan = plan_of(ppa)
    if plan is not None and plan.get("lifecycle_state") == "SERVICE_ARCHIVED":
        set_plan_state(plan, "SERVICE_ACTIVE")
        store.touch(plan)
    calc.recompute_ppa(ppa)
    calc.recompute_site(site)
    calc.recompute_customer(customer)
    store.touch(ppa)
    store.touch(site)
    store.touch(customer)
    return ppa


# --- customer relationship ---------------------------------------------------
def apply_exposure_hold(customer, actor_role):
    if customer.get("credit_tier") == "CREDIT_PRIME" or float(customer.get("exposure_hold_pct") or 0) <= 0:
        raise ApiError("ERR_CREDIT_TIER_INELIGIBLE", "credit tier is not eligible", 422)
    if customer.get("status") != "CUSTOMER_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "customer is not active", 409)

    customer["status"] = "CUSTOMER_CREDIT_HOLD"
    customer["hold_armed"] = True
    affected_sites = set()
    for ppa in store.customer_ppas(customer["id"]):
        if ppa.get("state") != "PPA_ACTIVE":
            continue
        ppa["state"] = "PPA_SUSPENDED"
        ppa["state_entered_at"] = store.now_iso()
        add_transition(ppa, "PPA_ACTIVE", "PPA_SUSPENDED", "EXPOSURE_HOLD_ARMED", actor_role)
        suspend_plans_of(ppa)
        calc.recompute_ppa(ppa)
        store.touch(ppa)
        affected_sites.add(ppa["site_id"])
    for site_id in affected_sites:
        site = store.get_site(site_id)
        if site is not None:
            calc.recompute_site(site)
            store.touch(site)
    calc.recompute_customer(customer)
    store.touch(customer)
    return customer


def release_exposure_hold(customer, actor_role):
    if customer.get("status") != "CUSTOMER_CREDIT_HOLD":
        raise ApiError(ERR_INVALID_STATE, "customer is not in credit hold", 409)
    if int(customer.get("outstanding_balance_cents") or 0) != 0:
        raise ApiError(ERR_INVALID_STATE, "outstanding balance is not clear", 409)
    owned = store.customer_ppas(customer["id"])
    for ppa in owned:
        site = store.get_site(ppa["site_id"])
        if site is None or site.get("status") != "SITE_ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "a hosting site is not active", 409)

    customer["status"] = "CUSTOMER_ACTIVE"
    customer["hold_armed"] = False
    affected_sites = set()
    for ppa in owned:
        if ppa.get("state") != "PPA_SUSPENDED":
            continue
        ppa["state"] = "PPA_ACTIVE"
        ppa["state_entered_at"] = store.now_iso()
        add_transition(ppa, "PPA_SUSPENDED", "PPA_ACTIVE", "EXPOSURE_HOLD_RELEASED", actor_role)
        restore_plans_of(ppa)
        calc.recompute_ppa(ppa)
        store.touch(ppa)
        affected_sites.add(ppa["site_id"])
    for site_id in affected_sites:
        site = store.get_site(site_id)
        if site is not None:
            calc.recompute_site(site)
            store.touch(site)
    calc.recompute_customer(customer)
    store.touch(customer)
    return customer


# --- deferred actions --------------------------------------------------------
def process_deferred():
    """Fire the clock-driven actions that no endpoint drives directly.

    The exit-termination timer is armed by request-exit but is deliberately left
    to the explicit terminate endpoint: PRD 3.8 makes termination an operator act
    with its own precondition, and auto-firing it would pre-empt that call.
    """
    now = store.clock()
    for plan in list(store.service_plans.values()):
        if plan.get("module_replacement_stage") == "REPLACEMENT_DISPATCHED":
            armed = plan.get("_replacement_revert_at")
            if armed and now >= store.parse_dt(armed):
                plan["module_replacement_stage"] = "REPLACEMENT_NONE"
                plan["_replacement_revert_at"] = None
                store.touch(plan)
        if plan.get("lifecycle_state") == "SERVICE_ACTIVE" \
                and plan.get("window_start_iso8601") and plan.get("window_end_iso8601"):
            start = store.parse_dt(plan["window_start_iso8601"])
            end = store.parse_dt(plan["window_end_iso8601"])
            if start <= now <= end:
                ppa = store.get_ppa(plan["ppa_id"])
                site = store.get_site(ppa["site_id"]) if ppa else None
                if site is not None and (calc.site_clearance_used(site)
                                         + float(plan.get("radius_buffer_m") or 0)
                                         <= float(site.get("clearance_zone_capacity") or 0)):
                    plan["lifecycle_state"] = "SERVICE_MAINTENANCE_WINDOW_OPEN"
                    calc.recompute_site(site)
                    store.touch(plan)
                    store.touch(site)
                    # PRD §3.7: entering a maintenance window "recomputes the
                    # parent contract's `effective_tariff_cents_per_kwh` and
                    # `availability_penalty_cents_per_kwh`". PRD §2.4 makes a
                    # recomputation of a derived field a modification, so the
                    # contract's `version` moves with it.
                    if ppa is not None:
                        calc.recompute_ppa(ppa)
                        store.touch(ppa)
        elif plan.get("lifecycle_state") == "SERVICE_MAINTENANCE_WINDOW_OPEN" \
                and plan.get("window_end_iso8601"):
            if now > store.parse_dt(plan["window_end_iso8601"]):
                plan["lifecycle_state"] = "SERVICE_ACTIVE"
                ppa = store.get_ppa(plan["ppa_id"])
                site = store.get_site(ppa["site_id"]) if ppa else None
                if site is not None:
                    calc.recompute_site(site)
                    store.touch(site)
                store.touch(plan)
