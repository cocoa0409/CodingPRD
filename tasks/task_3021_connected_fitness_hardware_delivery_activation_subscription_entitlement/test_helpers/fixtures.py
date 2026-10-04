"""Composite setup helpers — multi-step preconditions built from scratch.

The test harness restarts the API server before every individual test, so each
helper below constructs its entire world out of PRD-declared endpoints. Setup
steps use `get_success_data()` so a broken precondition raises a clear
"Setup step failed" error rather than a confusing assertion failure.

Identity threading: `MembershipOwner` is entity-backed by `Membership`, so every
ownership-gated call uses `make_membership_owner_headers(<membership id>)`.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DELIVERY,
    CLOCK_START,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_membership_owner_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]
INSTRUCTOR = TEST_USERS["instructor_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ─── Primitive steps ───────────────────────────────────

def set_clock(instant: str, headers=None):
    """Set the logical clock for all subsequent calls."""
    return get_success_data(api_client.set_clock(instant, headers or ADMIN))


def owner_headers(membership_id: str) -> dict:
    """Ownership-gated headers for the household that owns `membership_id`."""
    return make_membership_owner_headers(membership_id)


def create_membership(household_name=None, billing_email=None, plan_tier=None,
                      monthly_fee_cents=None, concurrent_limit_override=None,
                      headers=None):
    payload = {
        "household_name": household_name or TEST_DEFAULTS["HOUSEHOLD_NAME"],
        "billing_email": billing_email or TEST_DEFAULTS["BILLING_EMAIL"],
        "plan_tier": plan_tier or TEST_DEFAULTS["PLAN_TIER"],
        "monthly_fee_cents": (monthly_fee_cents if monthly_fee_cents is not None
                              else TEST_DEFAULTS["MONTHLY_FEE_CENTS"]),
    }
    if concurrent_limit_override is not None:
        payload["concurrent_limit_override"] = concurrent_limit_override
    return get_success_data(
        api_client.create_membership(payload, headers or TEST_USERS["membership_owner_headers"])
    )


def add_household_user(membership_id, display_name=None, email=None, role="MEMBER",
                       verify=True):
    """Create a household user and (by default) consume its verification token."""
    payload = {
        "display_name": display_name or TEST_DEFAULTS["DISPLAY_NAME"],
        "email": email or f"user-{display_name or 'ada'}@x.com".replace(" ", ""),
        "role": role,
    }
    user = get_success_data(
        api_client.create_household_user(membership_id, payload, owner_headers(membership_id))
    )
    if verify:
        user = verify_household_user(user["id"], user["verification_token"])
    return user


def verify_household_user(user_id, token):
    return get_success_data(
        api_client.verify_household_user(user_id, {"verification_token": token}, ANON)
    )


def mint_device(membership_id, hardware_sku=None, serial=None):
    payload = {
        "hardware_sku": hardware_sku or TEST_DEFAULTS["DEVICE_SKU"],
        "serial": serial or TEST_DEFAULTS["DEVICE_SERIAL"],
    }
    return get_success_data(api_client.create_device(membership_id, payload, TECH))


def place_order(membership_id, device_id=None, hardware_sku=None, subtotal_cents=None,
                financing_method="FULL_PAYMENT", **extra):
    payload = {
        "hardware_sku": hardware_sku or TEST_DEFAULTS["DEVICE_SKU"],
        "subtotal_cents": (subtotal_cents if subtotal_cents is not None
                           else TEST_DEFAULTS["HARDWARE_SUBTOTAL_CENTS"]),
        "financing_method": financing_method,
    }
    if device_id is not None:
        payload["device_id"] = device_id
    payload.update(extra)
    return get_success_data(
        api_client.create_hardware_order(membership_id, payload, owner_headers(membership_id))
    )


def create_service_order(payload, headers=None):
    """Dispatch a service order and return its response data (PRD §3.6)."""
    return get_success_data(api_client.create_service_order(payload, headers or TECH))


def create_appointment(device_id, order_id, start_at, end_at, zone="METRO",
                       crew=None, stair_flights=0, has_elevator=False):
    payload = {
        "device_id": device_id,
        "hardware_order_id": order_id,
        "start_at": start_at,
        "end_at": end_at,
        "zone": zone,
        "technician_crew_code": crew or TEST_DEFAULTS["CREW_CODE"],
        "stair_flights": stair_flights,
        "has_elevator": has_elevator,
    }
    return get_success_data(api_client.create_delivery_appointment(payload, TECH))


def schedule_appointment(appointment_id, start_at, end_at):
    return get_success_data(api_client.schedule_delivery_appointment(
        appointment_id, {"start_at": start_at, "end_at": end_at}, TECH))


def start_appointment(appointment_id):
    return get_success_data(api_client.start_delivery_appointment(appointment_id, {}, TECH))


def complete_appointment(appointment_id, grade="CLEAN"):
    return get_success_data(api_client.complete_delivery_appointment(
        appointment_id, {"completion_grade": grade}, TECH))


def failure_response(fn, *args, **kwargs):
    """Run a call expected to be refused and return the parsed error body."""
    res = fn(*args, **kwargs)
    assert res.status_code >= 400, f"expected a refusal, got {res.status_code}: {res.text}"
    return res.json()["data"]


def device_version(device_id):
    return get_success_data(api_client.get_device(device_id, TECH))["version"]


def membership_version(membership_id):
    return get_success_data(
        api_client.get_membership(membership_id, owner_headers(membership_id))
    )["version"]


def link_device(device_id, serial, membership_id):
    payload = {
        "serial": serial,
        "membership_id": membership_id,
        "expected_device_version": device_version(device_id),
    }
    return get_success_data(api_client.link_device(device_id, payload, TECH))


def activate_membership(membership_id):
    payload = {"expected_membership_version": membership_version(membership_id)}
    return get_success_data(
        api_client.activate_membership(membership_id, payload, owner_headers(membership_id))
    )


def get_membership(membership_id):
    return get_success_data(
        api_client.get_membership(membership_id, owner_headers(membership_id))
    )


def get_device(device_id):
    return get_success_data(api_client.get_device(device_id, TECH))


def get_order(order_id, membership_id):
    return get_success_data(
        api_client.get_hardware_order(order_id, owner_headers(membership_id))
    )


def get_plan(plan_id, membership_id):
    return get_success_data(
        api_client.get_financing_plan(plan_id, owner_headers(membership_id))
    )


def get_part(part_id):
    return get_success_data(api_client.get_part(part_id, TECH))


def get_service_order(service_order_id):
    return get_success_data(api_client.get_service_order(service_order_id, TECH))


def get_session(session_id):
    return get_success_data(api_client.get_class_session(session_id, INSTRUCTOR))


def cancel_membership(membership_id):
    payload = {"expected_membership_version": membership_version(membership_id)}
    return get_success_data(
        api_client.cancel_membership(membership_id, payload, owner_headers(membership_id))
    )


# ─── Tier 1: State progression ─────────────────────────

def setup_active_membership(clock_utc=CLOCK_DELIVERY,
                            plan_tier="PLUS",
                            monthly_fee_cents=6000,
                            concurrent_limit_override=None,
                            sku="TREAD",
                            serial="TREAD-0001",
                            subtotal_cents=296_000,
                            financing_method="FINANCE_SCHEDULED",
                            zone="METRO",
                            crew="CREW-A",
                            stair_flights=0,
                            has_elevator=False,
                            complete=True,
                            grade="CLEAN",
                            link=True,
                            activate=True,
                            start_clock=CLOCK_START,
                            household_name=None):
    """Membership + verified OWNER + device + order + delivery visit.

    With the default flags the whole chain runs to a live household: a
    PROVISIONAL membership, a verified OWNER, a newly minted device, an order
    placed before any appointment exists, a scheduled and started METRO visit,
    a CLEAN completion, the link, and the activation that flips the device live.

    Flags let callers stop earlier:
      complete=False -> the visit is left IN_PROGRESS (nothing is linked)
      link=False     -> the device stays DELIVERED
      activate=False -> the membership stays PROVISIONAL
    """
    set_clock(start_clock)
    membership = create_membership(
        household_name=household_name,
        plan_tier=plan_tier,
        monthly_fee_cents=monthly_fee_cents,
        concurrent_limit_override=concurrent_limit_override,
    )
    m_id = membership["id"]
    owner = add_household_user(m_id, display_name="Ada Fernwood", email="ada@x.com",
                               role="OWNER")
    device = mint_device(m_id, hardware_sku=sku, serial=serial)
    order = place_order(m_id, device["id"], hardware_sku=sku, subtotal_cents=subtotal_cents,
                        financing_method=financing_method)

    start_at = clock_utc
    end_at = _plus_hours(clock_utc, 2)
    appointment = create_appointment(device["id"], order["id"], start_at, end_at,
                                     zone=zone, crew=crew,
                                     stair_flights=stair_flights,
                                     has_elevator=has_elevator)
    set_clock(clock_utc)
    appointment = schedule_appointment(appointment["id"], start_at, end_at)
    appointment = start_appointment(appointment["id"])

    result = {
        "membership": membership,
        "membership_id": m_id,
        "owner": owner,
        "device": device,
        "device_id": device["id"],
        "order": order,
        "order_id": order["id"],
        "appointment": appointment,
        "appointment_id": appointment["id"],
        "serial": serial,
        "headers": owner_headers(m_id),
    }

    if not complete:
        return result

    appointment = complete_appointment(appointment["id"], grade)
    result["appointment"] = appointment
    result["device"] = get_device(device["id"])
    result["order"] = get_order(order["id"], m_id)

    if link:
        result["device"] = link_device(device["id"], serial, m_id)
    if activate:
        result["membership"] = activate_membership(m_id)
        result["device"] = get_device(device["id"])
    return result


def _plus_hours(instant: str, hours: int) -> str:
    from datetime import datetime, timedelta
    base = datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ")
    return (base + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_days(instant: str, days: int) -> str:
    from datetime import datetime, timedelta
    base = datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ")
    return (base + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def setup_member_users(membership_id, count, verified=True, start_index=1):
    """Add `count` MEMBER household users (verified by default)."""
    users = []
    for i in range(count):
        users.append(add_household_user(
            membership_id,
            display_name=f"Member {start_index + i}",
            email=f"member{start_index + i}@x.com",
            role="MEMBER",
            verify=verified,
        ))
    return users


# ─── Tier 3: Lifecycle shortcuts ───────────────────────

def setup_financing_plan(base=None, principal_cents=119_900, term_months=12, apr_bps=900):
    """Active household plus an ORIGINATED installment plan on its delivered order."""
    base = base or setup_active_membership(financing_method="FINANCE_SCHEDULED")
    plan = get_success_data(api_client.create_financing_plan({
        "membership_id": base["membership_id"],
        "order_id": base["order_id"],
        "principal_cents": principal_cents,
        "term_months": term_months,
        "apr_bps": apr_bps,
    }, owner_headers(base["membership_id"])))
    base["plan"] = plan
    base["plan_id"] = plan["id"]
    return base


def pay_installments(base, count):
    results = []
    for _ in range(count):
        results.append(get_success_data(api_client.pay_installment(
            base["plan_id"], {}, owner_headers(base["membership_id"]))))
    base["plan"] = results[-1] if results else base["plan"]
    return results


def fail_installments(base, count):
    results = []
    for _ in range(count):
        results.append(get_success_data(
            api_client.fail_installment(base["plan_id"], {}, ADMIN)))
    base["plan"] = results[-1] if results else base["plan"]
    return results


def setup_delinquent_household(base=None, principal_cents=119_900):
    """Active household driven to DELINQUENT by three failed installments."""
    base = setup_financing_plan(base, principal_cents=principal_cents, term_months=12,
                                apr_bps=900)
    pay_installments(base, 1)
    fail_installments(base, 3)
    base["membership"] = get_membership(base["membership_id"])
    return base


def setup_plan_near_paid_off(base=None, principal_cents=120_000, term_months=6,
                             apr_bps=0, paid=5):
    """Active household with a zero-APR plan one payment short of PAID_OFF."""
    base = setup_financing_plan(base, principal_cents=principal_cents,
                                term_months=term_months, apr_bps=apr_bps)
    pay_installments(base, paid)
    return base


def setup_parts_scenario(base=None, restock_qty=7, safety_stock_qty=2,
                         fault_code="BELT_SLIP", sku="TREAD", part_sku="TREAD"):
    """Active household, a registered+restocked part, and a dispatched service order."""
    base = base or setup_active_membership(sku=sku)
    part = get_success_data(api_client.create_part({
        "part_code": TEST_DEFAULTS["PART_CODE"],
        "compatible_sku": part_sku,
        "safety_stock_qty": safety_stock_qty,
        "part_lot_key": TEST_DEFAULTS["PART_LOT_KEY"],
    }, ADMIN))
    if restock_qty:
        part = get_success_data(api_client.restock_part(
            part["id"], {"quantity": restock_qty}, ADMIN))
    service_order = get_success_data(api_client.create_service_order({
        "device_id": base["device_id"],
        "reported_fault_code": fault_code,
        "diagnosis_note": "reported by the household",
    }, TECH))
    base["part"] = part
    base["part_id"] = part["id"]
    base["service_order"] = service_order
    base["service_order_id"] = service_order["id"]
    return base


def setup_published_session(instructor_name=None, discipline="CYCLING",
                            delivery_mode="ON_DEMAND",
                            starts_at="2026-09-10T09:00:00Z",
                            ends_at="2026-09-10T11:00:00Z",
                            capacity=100,
                            license_starts_at="2026-09-10T00:00:00Z",
                            license_ends_at="2026-09-20T00:00:00Z",
                            title="Threshold Ride"):
    """Author and publish a class session; returns the published session."""
    session = get_success_data(api_client.create_class_session({
        "title": title,
        "instructor_name": instructor_name or TEST_DEFAULTS["INSTRUCTOR_NAME"],
        "discipline": discipline,
        "delivery_mode": delivery_mode,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "license_starts_at": license_starts_at,
        "license_ends_at": license_ends_at,
    }, INSTRUCTOR))
    return get_success_data(api_client.publish_class_session(session["id"], {}, INSTRUCTOR))


def setup_one_hour_session(base=None, discipline="CYCLING",
                           starts_at="2026-09-10T09:00:00Z",
                           ends_at="2026-09-10T10:00:00Z", capacity=100):
    """Active household plus a published one-hour on-demand session."""
    base = base or setup_active_membership()
    session = setup_published_session(discipline=discipline, delivery_mode="ON_DEMAND",
                                      starts_at=starts_at, ends_at=ends_at,
                                      capacity=capacity)
    base["session"] = session
    base["session_id"] = session["id"]
    return base


def enroll(base, session_id=None, user_id=None, device_id=None):
    session_id = session_id or base["session_id"]
    device_id = device_id or base["device_id"]
    user_id = user_id or base["owner"]["id"]
    enrollment = get_success_data(api_client.create_class_enrollment({
        "class_session_id": session_id,
        "device_id": device_id,
        "enroller_user_id": user_id,
    }, owner_headers(base["membership_id"])))
    return enrollment


def decommission_device(device_id, stale_days=181):
    """Drive a live device to the terminal DECOMMISSIONED state.

    PRD §3.4: a membership cancelled and swept past its 180-day termination
    grace terminates, and every device on it becomes DECOMMISSIONED. A source
    device for a refurbishment batch must be DECOMMISSIONED or itself
    resale-originated, so this is the PRD-sanctioned way to make a fresh
    (non-resale) device an eligible refurbishment source.
    """
    membership_id = get_success_data(
        api_client.get_device(device_id, TECH))["membership_id"]
    anchor = get_membership(membership_id)["billing_cycle_start_at"]
    cancel_membership(membership_id)
    set_clock(plus_days(anchor, stale_days))
    get_success_data(api_client.run_ops({}, ADMIN))
    return get_success_data(api_client.get_device(device_id, TECH))


def setup_refurb_source(clock_utc="2026-09-05T13:30:00Z", **kwargs):
    """Return an eligible refurbishment source device and its household.

    PRD §3.7 requires the source to be DECOMMISSIONED or resale-originated, so
    the household's unit is driven to DECOMMISSIONED through the termination
    cascade. The clock is restored to `clock_utc` afterward so the caller can
    open the batch at its own pinned instant.
    """
    base = setup_active_membership(clock_utc=clock_utc, **kwargs)
    decommission_device(base["device_id"])
    set_clock(clock_utc)
    base["source_device"] = get_device(base["device_id"])
    return base


def setup_buying_household(clock_utc="2026-09-05T13:30:00Z", **kwargs):
    """A second, live household able to buy a refurbished unit (PRD §3.7)."""
    return setup_active_membership(
        clock_utc=clock_utc, household_name="Larkspur Household",
        serial="TREAD-0002", crew="CREW-B", **kwargs)


def setup_refurb_chain(base=None, depth=3):
    """Mint a self-referential certification lineage of the requested length.

    A batch may only open over a DECOMMISSIONED or resale-originated source, so
    the seed device is first decommissioned through the PRD's own termination
    cascade; each later hop sources an already resale-originated minted unit.

    Returns the base setup plus `devices` — index 0 is the seed device and each
    later entry is the unit minted by the next batch sale — and `batches`.
    """
    base = base or setup_active_membership()
    seed_household = base["membership_id"]
    buyer = setup_buying_household()
    seed = decommission_device(base["device_id"])
    devices = [base["device_id"]]
    batches = []
    source = base["device_id"]
    for _ in range(depth):
        batch = get_success_data(api_client.create_refurb_batch({
            "source_device_id": source,
            "certification_grade": "A",
            "performance_resale_enabled": True,
        }, TECH))
        batch = get_success_data(api_client.certify_refurb_batch(batch["id"], {}, TECH))
        batch = get_success_data(
            api_client.list_refurb_batch_for_resale(batch["id"], {}, ADMIN))
        sold = get_success_data(api_client.sell_refurb_batch(
            batch["id"], {"buying_membership_id": buyer["membership_id"]}, ADMIN))
        batches.append(sold)
        source = sold["sold_device_id"]
        devices.append(source)
    base["devices"] = devices
    base["batches"] = batches
    base["seed_device"] = seed
    base["buyer"] = buyer
    base["seed_household_id"] = seed_household
    return base


def setup_terminated_membership(base=None, clock_utc="2026-09-05T13:30:00Z",
                                stale_days=181, with_owner=True):
    """Cancel an active household and sweep it past the 180-day termination grace."""
    base = base or setup_active_membership(clock_utc=clock_utc)
    base["membership"] = cancel_membership(base["membership_id"])
    set_clock(plus_days(clock_utc, stale_days))
    sweep = get_success_data(api_client.run_ops({}, ADMIN))
    base["sweep"] = sweep
    base["membership"] = get_membership(base["membership_id"])
    base["device"] = get_device(base["device_id"])
    return base


def setup_cancelled_membership(base=None, clock_utc="2026-09-01T00:00:00Z",
                               cancel_clock="2026-09-17T12:00:00Z"):
    """Active household cancelled mid-cycle (13.5 days of cycle remaining).

    The activation instant is pinned to `clock_utc` so the cycle anchors sit at
    exactly 30 days, and the cancellation is issued on `cancel_clock`.
    """
    base = base or setup_active_membership(clock_utc=clock_utc)
    set_clock(cancel_clock)
    base["membership"] = cancel_membership(base["membership_id"])
    return base