"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the server is restarted before each individual test.
Setup steps use the lenient `get_success_data()` validator so a broken
precondition surfaces as a clear "Setup failed" error rather than a
confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from . import constants as C
from .api_client import api_client
from .factories import (
    create_appointment_payload,
    create_batch_payload,
    create_buyer_payload,
    create_completion_payload,
    create_configuration_payload,
    create_delivery_center_payload,
    create_diagnostic_report_payload,
    create_financing_application_payload,
    create_jurisdiction_payload,
    create_mobile_visit_payload,
    create_order_payload,
    create_service_appointment_payload,
)
from .test_users import TEST_USERS, make_buyer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
PLATFORM_ADMIN_HEADERS = ADMIN
ADVISOR = TEST_USERS["delivery_advisor_headers"]
TECH = TEST_USERS["service_technician_headers"]
TRADEIN = TEST_USERS["trade_in_specialist_headers"]
FINANCE = TEST_USERS["finance_partner_headers"]
PARTS = TEST_USERS["parts_coordinator_headers"]

_VIN_SEQUENCE = iter(range(400, 600))
_EMAIL_SEQUENCE = iter(range(1, 10 ** 6))


def next_email_token():
    """The account email must be unique across all accounts (PRD §3.1), so a
    fixture that builds several accounts in one scenario needs a fresh one each
    time rather than a name-derived value two callers can collide on."""
    return next(_EMAIL_SEQUENCE)


def next_vin(prefix: str = "7SAYGDEE1PF000") -> str:
    """Unique VIN for each minted unit."""
    return f"{prefix}{next(_VIN_SEQUENCE)}"


# ═══ Tier 0: Clock ════════════════════════════════════

def set_clock(instant: str = C.CLOCK_START):
    """Set the logical clock to a known instant."""
    return get_success_data(api_client.set_current_utc(instant, ADMIN))


def advance_clock(instant: str):
    """Advance the logical clock; this also runs every scheduled sweep."""
    return get_success_data(api_client.set_current_utc(instant, ADMIN))


# ═══ Tier 1: State progression ════════════════════════

def create_buyer(full_name="Dana V", email=None, residency_state_code="TX", **overrides):
    """Create a buying account. Returns the PENDING_VERIFICATION Buyer."""
    payload = create_buyer_payload(
        full_name=full_name,
        email=email or f"{full_name.lower().replace(' ', '.')}@example.com",
        residency_state_code=residency_state_code,
        **overrides,
    )
    return get_success_data(api_client.create_buyer(payload, TEST_USERS["anonymous_headers"]))


def create_verified_buyer(full_name="Dana V", email=None, residency_state_code="TX"):
    """Create a buying account and confirm its identity so it reaches ACTIVE."""
    buyer = create_buyer(full_name=full_name, email=email,
                         residency_state_code=residency_state_code)
    verified = get_success_data(
        api_client.verify_buyer_identity(buyer["id"], ADMIN))
    assert verified["status"] == "ACTIVE", "Setup failed: buyer did not reach ACTIVE"
    assert verified["identity_verified"] is True, "Setup failed: identity not verified"
    return verified


def create_and_enact_jurisdiction(**overrides):
    """Create a state regime and bring it into force. Returns the ENACTED row."""
    jur = get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), ADMIN))
    enacted = get_success_data(api_client.enact_jurisdiction(jur["id"], ADMIN))
    assert enacted["status"] == "ENACTED", "Setup failed: jurisdiction not ENACTED"
    return enacted


def create_center(**overrides):
    """Create a physical site. Defaults to an ACTIVE TX DELIVERY_CENTER."""
    return get_success_data(
        api_client.create_delivery_center(create_delivery_center_payload(**overrides), ADMIN))


def create_published_configuration(model_code=None, base_price_cents=None, options=None):
    """Create a trim plus one or more options. Returns (configuration, [options])."""
    config = get_success_data(api_client.create_configuration(
        create_configuration_payload(
            model_code=model_code or C.TEST_DEFAULTS["MODEL_CODE_Y"],
            base_price_cents=(base_price_cents
                              if base_price_cents is not None
                              else C.TEST_DEFAULTS["BASE_PRICE_CENTS_Y"]),
        ), ADMIN))
    created = []
    for option in (options or []):
        row = get_success_data(
            api_client.create_configuration_option(config["id"], option, ADMIN))
        merged = dict(option)
        merged["id"] = row["id"]
        created.append(merged)
    refreshed = get_success_data(api_client.get_configuration(config["id"], ADMIN))
    return refreshed, created


def create_order(buyer_id, configuration_id, jurisdiction_id, delivery_center_id,
                 order_fee_cents=None, actor=None, **overrides):
    """Open a VehicleOrder. Returns the DRAFT order."""
    payload = create_order_payload(
        buyer_id, configuration_id, jurisdiction_id, delivery_center_id,
        **overrides)
    if order_fee_cents is not None:
        payload["order_fee_cents"] = order_fee_cents
    return get_success_data(api_client.create_order(payload, actor or ADMIN))


def settle_order_fee(order_id):
    """Settle the order fee through the payment simulator."""
    return get_success_data(api_client.simulate_payment(
        {"order_id": order_id, "outcome": "SUCCEEDED"}, ADMIN))


def cover_order_total(order_id):
    """Capture whatever the order's recomputed total still needs to be covered.

    PRD 3.7 decides the readiness posture by comparing `order_fee_paid_cents` to
    the provisional total, and PRD 3.5 will only fund a loan against a READY
    order. The capture is posted as an ORDER_FEE_PAYMENT entry, which is the
    entry type the order's paid amount is summed over (PRD 2.8), so the fixture
    can bring the order to READY through the API alone.
    """
    order = get_order(order_id)
    shortfall = order["order_total_due_cents"] - order["order_fee_paid_cents"]
    if shortfall <= 0:
        return order
    get_success_data(api_client.post_ledger_entry(
        order_id,
        {"entry_type": "ORDER_FEE_PAYMENT", "amount_cents": shortfall,
         "reason_code": "FEE_BALANCE_CAPTURED"}, ADMIN))
    return get_order(order_id)


def place_order(order_id, expected_order_version, buyer_id):
    """Place the order on behalf of its owning buyer."""
    placed = get_success_data(api_client.place_order(
        order_id, expected_order_version, make_buyer_headers(buyer_id)))
    assert placed["status"] == "PLACED", "Setup failed: order not PLACED"
    return placed


def lock_order(order_id, expected_order_version):
    """Lock the configuration explicitly."""
    locked = get_success_data(api_client.lock_configuration(
        order_id, expected_order_version, ADMIN))
    assert locked["status"] == "CONFIG_LOCKED", "Setup failed: order not CONFIG_LOCKED"
    return locked


def create_and_start_batch(vin=None, prefer_misses=6, **overrides):
    """Create a production batch, start it, and mint one unit. Returns (batch, unit)."""
    batch = get_success_data(
        api_client.create_production_batch(create_batch_payload(**overrides), ADMIN))
    batch = get_success_data(api_client.start_batch(batch["id"], ADMIN))
    unit = get_success_data(
        api_client.mint_allocation_unit(batch["id"], vin or next_vin(), ADMIN))
    return batch, unit


def allocate_order(order_id, batch_id, expected_order_version):
    """Match an unassigned unit to a CONFIG_LOCKED order."""
    allocated = get_success_data(api_client.allocate_order(
        order_id, batch_id, expected_order_version, ADMIN))
    assert allocated["status"] == "ALLOCATED", "Setup failed: order not ALLOCATED"
    return allocated


def dispatch_and_arrive(order_id):
    """Hand the unit to transport, then record arrival at the handover site."""
    get_success_data(api_client.dispatch_to_transport(order_id, ADMIN))
    return get_success_data(api_client.arrive_at_center(order_id, ADMIN))


def get_order(order_id, actor=None):
    return get_success_data(api_client.get_order(order_id, actor or ADMIN))


def get_center(center_id, actor=None):
    return get_success_data(api_client.get_delivery_center(center_id, actor or ADMIN))


# ═══ Tier 2: Entity hierarchy ═════════════════════════

def setup_catalog(state_code="TX", center_overrides=None, options=None,
                  jurisdiction_overrides=None):
    """ENACTED regime + one site + one configuration with options."""
    jur = create_and_enact_jurisdiction(state_code=state_code,
                                        **(jurisdiction_overrides or {}))
    center = create_center(state_code=state_code, **(center_overrides or {}))
    config, opts = create_published_configuration(options=options)
    return jur, center, config, opts


def setup_order_context(state_code="TX", buyer_name="Dana V", options=None,
                        jurisdiction_overrides=None, center_overrides=None,
                        order_overrides=None):
    """Verified buyer + ENACTED regime + site + configuration + DRAFT order.

    Any `options` the caller names are created on the trim and then attached to
    the order through the declared configuration-change endpoint, which is the
    only route by which an option becomes part of what the order owes (PRD 3.2).

    Returns (buyer, jurisdiction, center, configuration, order).
    """
    jur, center, config, created = setup_catalog(
        state_code=state_code,
        center_overrides=center_overrides,
        options=options,
        jurisdiction_overrides=jurisdiction_overrides,
    )
    buyer = create_verified_buyer(full_name=buyer_name,
                                  email=f"{buyer_name.lower().replace(' ', '.')}"
                                        f".{state_code.lower()}"
                                        f".{next_email_token()}@example.com",
                                  residency_state_code=state_code)
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"],
                         **(order_overrides or {}))
    if created:
        get_success_data(api_client.change_configuration(
            order["id"],
            {"add_option_ids": [o["id"] for o in created], "remove_option_ids": [],
             "expected_order_version": get_order(order["id"])["version"]},
            make_buyer_headers(buyer["id"])))
        order = get_order(order["id"])
    return buyer, jur, center, config, order


# ═══ Tier 3: Full lifecycle shortcuts ═════════════════

def walk_order_to_at_delivery_center(buyer=None, jurisdiction=None, center=None,
                                     configuration=None, order=None,
                                     options=None, vin=None,
                                     batch_overrides=None,
                                     jurisdiction_overrides=None,
                                     center_overrides=None,
                                     buyer_name="Dana V",
                                     order_overrides=None,
                                     settle_fee=True):
    """Create (or accept) the full order chain and walk it to AT_DELIVERY_CENTER.

    Returns dict with buyer, jurisdiction, center, configuration, order,
    batch, unit, vehicle.
    """
    if order is None:
        buyer, jurisdiction, center, configuration, order = setup_order_context(
            buyer_name=buyer_name,
            options=options,
            jurisdiction_overrides=jurisdiction_overrides,
            center_overrides=center_overrides,
            order_overrides=order_overrides,
        )
    if settle_fee:
        settle_order_fee(order["id"])
        order = get_order(order["id"])
    placed = place_order(order["id"], order["version"], buyer["id"])
    locked = lock_order(order["id"], placed["version"])
    batch, unit = create_and_start_batch(vin=vin, **(batch_overrides or {}))
    allocated = allocate_order(order["id"], batch["id"], locked["version"])
    dispatch_and_arrive(order["id"])
    refreshed = get_order(order["id"])
    vehicle_list = get_success_data(
        api_client.list_order_vehicles(order["id"], TECH))
    vehicles = vehicle_list if isinstance(vehicle_list, list) else []
    assert len(vehicles) == 1, (
        f"Setup failed: expected exactly 1 vehicle for the order, got {len(vehicles)}")
    return {
        "buyer": buyer,
        "jurisdiction": jurisdiction,
        "center": center,
        "configuration": configuration,
        "order": refreshed,
        "batch": batch,
        "unit": unit,
        "vehicle": vehicles[0],
        "allocated": allocated,
    }


def book_appointment(order_id, center_id, expected_order_version,
                     start="2026-09-22T15:00:00Z", end="2026-09-22T16:00:00Z",
                     mode="CENTER", **overrides):
    """Book a handover at a center or by home delivery."""
    return get_success_data(api_client.book_delivery_appointment(
        create_appointment_payload(
            order_id, center_id, expected_order_version,
            delivery_mode=mode, scheduled_start=start, scheduled_end=end,
            **overrides),
        ADVISOR))


def confirm_appointment(appointment_id):
    return get_success_data(
        api_client.confirm_delivery_appointment(appointment_id, ADVISOR))


def complete_appointment(appointment_id, expected_order_version,
                         result="CLEAN", issues=None, **overrides):
    return get_success_data(api_client.complete_delivery_appointment(
        appointment_id,
        create_completion_payload(expected_order_version,
                                  acceptance_inspection_result=result,
                                  documented_issues=issues or [],
                                  **overrides),
        ADVISOR))


def walk_order_to_delivered(buyer_name="Dana V", options=None,
                            appointment_start="2026-09-22T15:00:00Z",
                            appointment_end="2026-09-22T16:00:00Z",
                            inspection_result="CLEAN", documented_issues=None,
                            jurisdiction_overrides=None, center_overrides=None,
                            batch_overrides=None, vin=None):
    """Full chain through an accepted handover. Returns dict of the whole scenario.

    The caller's `options` are created on the trim and attached to the order by
    the setup helpers, so they stay part of what the order owes all the way
    through the handover — which is what makes the delivered total reflect them.
    """
    ctx = walk_order_to_at_delivery_center(
        buyer_name=buyer_name,
        options=options,
        jurisdiction_overrides=jurisdiction_overrides,
        center_overrides=center_overrides,
        batch_overrides=batch_overrides,
        vin=vin,
    )
    buyer = ctx["buyer"]
    order = ctx["order"]
    # Funding requires the order's posture to be READY, which turns on the
    # provisional total being covered (PRD 3.5, 3.7), so the outstanding balance
    # is captured before the loan is filed.
    cover_order_total(order["id"])
    venture = get_success_data(api_client.create_financing_application(
        order["id"],
        create_financing_application_payload(term_months=60, down_payment_cents=0),
        make_buyer_headers(buyer["id"])))
    decided = get_success_data(api_client.decide_financing_application(
        venture["id"], "APPROVED", FINANCE))
    reviewed = get_success_data(api_client.contract_review(
        venture["id"], decided["version"], FINANCE))
    funded = get_success_data(api_client.fund_application(
        venture["id"], reviewed["version"], FINANCE))
    ctx["application"] = funded

    order = get_order(ctx["order"]["id"])
    appt = book_appointment(order["id"], ctx["center"]["id"], order["version"],
                            start=appointment_start, end=appointment_end)
    confirm_appointment(appt["id"])
    order = get_order(order["id"])
    appt = complete_appointment(appt["id"], order["version"],
                                result=inspection_result,
                                issues=documented_issues)
    ctx["order"] = get_order(order["id"])
    ctx["appointment"] = appt
    ctx["vehicle"] = get_success_data(api_client.get_vehicle(ctx["vehicle"]["id"], TECH))
    return ctx


def create_funded_order(buyer_name="Dana V", term_months=60, down_payment_cents=0,
                        options=None, appointment_start="2026-09-22T15:00:00Z",
                        appointment_end="2026-09-22T16:00:00Z",
                        jurisdiction_overrides=None, center_overrides=None,
                        vin=None):
    """Walk an order to AT_DELIVERY_CENTER, fund its loan, and book the handover."""
    ctx = walk_order_to_at_delivery_center(
        buyer_name=buyer_name, options=options,
        jurisdiction_overrides=jurisdiction_overrides,
        center_overrides=center_overrides, vin=vin)
    application = get_success_data(api_client.create_financing_application(
        ctx["order"]["id"],
        create_financing_application_payload(term_months=term_months,
                                             down_payment_cents=down_payment_cents),
        make_buyer_headers(ctx["buyer"]["id"])))
    decided = get_success_data(api_client.decide_financing_application(
        application["id"], "APPROVED", FINANCE))
    reviewed = get_success_data(api_client.contract_review(
        application["id"], decided["version"], FINANCE))
    funded = get_success_data(api_client.fund_application(
        application["id"], reviewed["version"], FINANCE))
    ctx["application"] = funded
    order = get_order(ctx["order"]["id"])
    ctx["order"] = order
    ctx["appointment"] = book_appointment(order["id"], ctx["center"]["id"],
                                          order["version"],
                                          start=appointment_start, end=appointment_end)
    return ctx


# ═══ Tier 4: Accumulation / threshold targeting ═══════

def create_entitlements(vehicle_id, entries, source="PURCHASE", **overrides):
    """Grant one bundle and return the created rows."""
    payload = {
        "feature_entries": entries,
        "entitlement_source": source,
    }
    payload.update(overrides)
    rows = get_success_data(api_client.grant_entitlements(vehicle_id, payload, ADMIN))
    return rows if isinstance(rows, list) else [rows]


def activate_entitlement_count(vehicle_id, count, price_cents=0):
    """Bring a vehicle to exactly `count` ACTIVE entitlements before the test bundle.

    Each grant is minted under its own feature code, so the vehicle's ACTIVE
    count lands deterministically at `count`.
    """
    for index in range(count):
        create_entitlements(
            vehicle_id,
            [{"feature_code": f"SEED_{index}", "price_cents": price_cents}],
            source="FACTORY_OPTION")


def setup_vehicle_with_entitlements(count, delivered_context=None,
                                    price_cents=0, buyer_name="Dana V"):
    """Delivered vehicle already carrying `count` ACTIVE entitlements."""
    ctx = delivered_context or walk_order_to_delivered(buyer_name=buyer_name)
    activate_entitlement_count(ctx["vehicle"]["id"], count, price_cents=price_cents)
    return ctx


def setup_service_vehicle(fault_code="HVAC-0442", severity="MEDIUM",
                          is_driveable=True, odometer_miles=None,
                          prior_reports=None, buyer_name="Dana V",
                          jurisdiction_overrides=None, vin=None,
                          center_kind="SERVICE_CENTER"):
    """Delivered vehicle, optional odometer, plus one triage report.

    Returns dict with the delivered scenario, the report, and the service center.
    """
    ctx = walk_order_to_delivered(
        buyer_name=buyer_name, vin=vin,
        jurisdiction_overrides=jurisdiction_overrides)
    vehicle = ctx["vehicle"]
    if odometer_miles is not None:
        # The odometer is telemetry-supplied; re-read after the seeded value.
        vehicle = get_success_data(api_client.get_vehicle(vehicle["id"], TECH))
    service_center = ctx["center"]
    if center_kind != "DELIVERY_CENTER":
        service_center = create_center(center_name="Austin Service",
                                       center_kind=center_kind, state_code="TX",
                                       bay_count=3, home_delivery_radius_miles=0,
                                       van_count=0)
    for prior in (prior_reports or []):
        api_client.pull_diagnostic_report(vehicle["id"], prior, TECH)
    report = get_success_data(api_client.pull_diagnostic_report(
        vehicle["id"],
        create_diagnostic_report_payload(fault_code=fault_code, severity=severity,
                                         is_driveable=is_driveable),
        TECH))
    ctx["vehicle"] = vehicle
    ctx["report"] = report
    ctx["service_center"] = service_center
    return ctx


def open_service_appointment(vehicle_id, report_id, center_id,
                             start="2026-09-25T14:00:00Z", end="2026-09-25T16:00:00Z",
                             **overrides):
    return get_success_data(api_client.create_service_appointment(
        create_service_appointment_payload(vehicle_id, report_id, center_id,
                                           scheduled_start=start, scheduled_end=end,
                                           **overrides),
        TECH))


def dispatch_mobile_visit(appointment_id, hub_id, appointment_version,
                          start="2026-09-26T14:00:00Z", end="2026-09-26T17:00:00Z",
                          **overrides):
    return get_success_data(api_client.dispatch_mobile_visit(
        create_mobile_visit_payload(appointment_id, hub_id, appointment_version,
                                    visit_start=start, visit_end=end, **overrides),
        TECH))


def setup_triaged_mobile_appointment(fault_code="HVAC-0442", severity="MEDIUM",
                                     is_driveable=True, buyer_name="Dana V",
                                     center_kind="SERVICE_CENTER",
                                     jurisdiction_overrides=None):
    """Delivered vehicle + MOBILE_REQUIRED report + TRIAGED service appointment.

    Returns dict with scenario, hub, report, appointment.
    """
    ctx = setup_service_vehicle(fault_code=fault_code, severity=severity,
                                is_driveable=is_driveable, buyer_name=buyer_name,
                                center_kind=center_kind,
                                jurisdiction_overrides=jurisdiction_overrides)
    # Every helper here creates its own fixtures through PRD-declared endpoints,
    # so the state_code a site declares is a plain attribute of that new row and
    # does not need to collide with an existing regime's code.
    hub = create_center(center_name="Oklahoma Parts Hub", center_kind="PARTS_HUB",
                        state_code="OK", bay_count=1,
                        home_delivery_radius_miles=0, van_count=0)
    ctx["hub"] = hub
    appointment = open_service_appointment(
        ctx["vehicle"]["id"], ctx["report"]["id"], ctx["service_center"]["id"])
    ctx["appointment"] = appointment
    return ctx


# ═══ Tier 5: Terminal / finalization states ═══════════

def setup_delivered_order_with_issue(buyer_name="Dana V", issue_code="PAINT_CHIP",
                                     blocked_handover=True, observed_mileage=4):
    """Delivered order whose acceptance inspection documented one blocking issue."""
    ctx = walk_order_to_delivered(
        buyer_name=buyer_name,
        inspection_result="ISSUES_DOCUMENTED",
        documented_issues=[{"issue_code": issue_code,
                            "observed_mileage": observed_mileage,
                            "blocked_handover": blocked_handover}])
    notes = get_success_data(api_client.list_order_issue_notes(ctx["order"]["id"], ADMIN))
    note_list = notes if isinstance(notes, list) else notes.get("data", [])
    assert note_list, "Setup failed: no issue note was recorded for the order"
    ctx["notes"] = note_list
    return ctx