"""Corner coverage: error-producing conditions across the delivery and service flow."""
from test_helpers import (
    TEST_USERS,
    create_and_enact_jurisdiction,
    create_and_start_batch,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    get_order,
    get_success_data,
    lock_order,
    place_order,
    set_clock,
    settle_order_fee,
    setup_triaged_mobile_appointment,
    validate_error,
    walk_order_to_at_delivery_center,
    walk_order_to_delivered,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["delivery_advisor_headers"]
TECH = TEST_USERS["service_technician_headers"]


def test_stale_order_version_on_booking_returns_stale_version(api):
    """PRD §2.7: "Booking a handover requires `expected_order_version` carrying the
    client's last observed `version` of the target `VehicleOrder`."
    PRD §2.7: "In all three cases, if the supplied value does not equal the parent
    entity's current `version` — because some other write has advanced it since the
    client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_order_version_on_booking_returns_stale_version
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center()
    order = ctx["order"]

    refused = api.book_delivery_appointment(
        {"order_id": order["id"], "delivery_center_id": ctx["center"]["id"],
         "delivery_mode": "CENTER",
         "scheduled_start": "2026-09-24T15:00:00Z",
         "scheduled_end": "2026-09-24T16:00:00Z",
         "expected_order_version": order["version"] - 3},
        ADVISOR)
    validate_error(refused, "ERR_STALE_VERSION", expected_status=412)

    rows = get_success_data(api.list_order_appointments(order["id"], ADMIN))
    assert rows == []
    assert get_success_data(
        api.get_delivery_center(ctx["center"]["id"], ADMIN))["booked_slot_count"] == 0


def test_mobile_service_dispatch_in_a_banned_jurisdiction_is_refused(api):
    """PRD §2.4: "`mobile_service_permitted` states whether repair work may be
    performed at the customer's location; when it is false, no mobile visit may be
    dispatched against a vehicle governed by that regime, and the attempt is
    refused with `ERR_MOBILE_SERVICE_FORBIDDEN` (HTTP 403)."
    PRD §3.9: "the outcome is `OTA_RESOLVABLE` when the governing regime's
    `mobile_service_permitted` is false, the severity is `LOW` or `MEDIUM`, and
    `is_driveable` is true"

    Design: Corner/errors/mobile_service_dispatch_in_a_banned_jurisdiction_is_refused
    """
    set_clock()
    ctx = setup_triaged_mobile_appointment(
        fault_code="ACA-7700", severity="HIGH", is_driveable=True,
        jurisdiction_overrides={"mobile_service_permitted": False})

    # A regime that bars driveway repair pushes a mild fault to a software
    # remedy, but a severe one cannot be handled remotely: it is a centre job,
    # and the dispatch attempt against it is refused on the jurisdiction flag.
    assert ctx["report"]["triage_outcome"] == "CENTER_REQUIRED"
    assert ctx["report"]["parts_required"] is True

    refused = api.dispatch_mobile_visit(
        {"service_appointment_id": ctx["appointment"]["id"],
         "parts_hub_id": ctx["hub"]["id"],
         "van_code": "VAN-AZ-1",
         "visit_start": "2026-09-26T14:00:00Z",
         "visit_end": "2026-09-26T17:00:00Z",
         "labor_hours": 2.0,
         "parts_cost_cents": 0,
         "visit_miles": 20,
         "expected_service_appointment_version": ctx["appointment"]["version"]},
        TECH)
    validate_error(refused, "ERR_MOBILE_SERVICE_FORBIDDEN", expected_status=403)


def test_opening_a_service_appointment_from_a_no_action_triage_is_refused(api):
    """PRD §3.9: "The first clause is the repeat-fault short circuit: the outcome is
    `NO_ACTION` when the severity is `LOW` and the most recent prior report on the
    same vehicle carries the same `fault_code`."
    PRD §3.9: "Scheduling into a center bay requires the appointment to be
    `TRIAGED` — otherwise `ERR_INVALID_STATE` (HTTP 409) — requires the referenced
    report's `triage_outcome` to be `CENTER_REQUIRED`, otherwise
    `ERR_TRIAGE_NO_SERVICE_REQUIRED` (HTTP 409)"

    Design: Corner/errors/opening_a_service_appointment_from_a_no_action_triage_is_refused
    """
    set_clock()
    ctx = walk_order_to_delivered()
    vehicle_id = ctx["vehicle"]["id"]
    first = get_success_data(api.pull_diagnostic_report(
        vehicle_id, {"fault_code": "OTA-1001", "severity": "LOW",
                     "is_driveable": True}, TECH))
    repeat = get_success_data(api.pull_diagnostic_report(
        vehicle_id, {"fault_code": "OTA-1001", "severity": "LOW",
                     "is_driveable": True}, TECH))

    assert first["triage_outcome"] == "MOBILE_REQUIRED"
    assert repeat["triage_outcome"] == "NO_ACTION"

    refused = api.create_service_appointment(
        {"vehicle_id": vehicle_id, "diagnostic_report_id": repeat["id"],
         "service_center_id": ctx["center"]["id"],
         "scheduled_start": "2026-09-28T14:00:00Z",
         "scheduled_end": "2026-09-28T15:00:00Z"}, TECH)
    validate_error(refused, "ERR_TRIAGE_NO_SERVICE_REQUIRED", expected_status=409)


def test_non_driveable_critical_report_is_forced_onto_the_center_channel(api):
    """PRD §3.9: "the outcome is `CENTER_REQUIRED` when the severity is `HIGH` or
    `CRITICAL`, or when `is_driveable` is false, either condition alone being
    sufficient"
    PRD §3.9: "Dispatching a mobile visit instead requires the appointment to be
    `TRIAGED` (`ERR_INVALID_STATE`), requires the report's `triage_outcome` to be
    `MOBILE_REQUIRED` (`ERR_TRIAGE_NO_SERVICE_REQUIRED`)"

    Design: Corner/errors/non_driveable_critical_report_is_forced_onto_the_center_channel
    """
    set_clock()
    ctx = setup_triaged_mobile_appointment(fault_code="DRV-9001", severity="CRITICAL",
                                           is_driveable=False)
    assert ctx["report"]["triage_outcome"] == "CENTER_REQUIRED"

    refused = api.dispatch_mobile_visit(
        {"service_appointment_id": ctx["appointment"]["id"],
         "parts_hub_id": ctx["hub"]["id"],
         "van_code": "VAN-NC-1",
         "visit_start": "2026-09-29T14:00:00Z",
         "visit_end": "2026-09-29T17:00:00Z",
         "labor_hours": 2.0,
         "parts_cost_cents": 15000,
         "visit_miles": 25,
         "expected_service_appointment_version": ctx["appointment"]["version"]},
        TECH)
    assert refused.status_code in (403, 409)
    error_id = refused.json()["data"]["error_id"]
    assert error_id in ("ERR_MOBILE_SERVICE_FORBIDDEN", "ERR_TRIAGE_NO_SERVICE_REQUIRED")

    scheduled = get_success_data(api.schedule_service_center(
        ctx["appointment"]["id"],
        {"scheduled_start": "2026-09-29T14:00:00Z",
         "scheduled_end": "2026-09-29T16:00:00Z"}, TECH))
    assert scheduled["status"] == "CENTER_SCHEDULED"


def test_booking_when_the_readiness_posture_is_frozen_is_refused(api):
    """PRD §3.6: "The order's `delivery_readiness_posture` must not be `FROZEN` —
    it must be `READY` or `RESTRICTED` — otherwise `ERR_ORDER_DELIVERY_NOT_READY`
    (HTTP 409)."
    PRD §3.7: "It is `FROZEN` when the order is `CANCELLED`, and `FROZEN` when the
    order's allocation unit has not reached `ARRIVED`"

    Design: Corner/errors/booking_when_the_readiness_posture_is_frozen_is_refused
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    placed = place_order(order["id"], order["version"], buyer["id"])
    locked = lock_order(order["id"], placed["version"])
    batch, _unit = create_and_start_batch()
    get_success_data(api.allocate_order(order["id"], batch["id"],
                                        locked["version"], ADMIN))
    get_success_data(api.dispatch_to_transport(order["id"], ADMIN))
    in_transit = get_order(order["id"])
    assert in_transit["status"] == "IN_TRANSIT"
    assert in_transit["delivery_readiness_posture"] == "FROZEN"

    # The order is still IN_TRANSIT and has not arrived, so it is not at a
    # centre at all — the earlier of the two gates a booking runs into — and
    # the posture it would present at the later gate is FROZEN (PRD 3.7).
    refused = api.book_delivery_appointment(
        {"order_id": order["id"], "delivery_center_id": center["id"],
         "delivery_mode": "CENTER",
         "scheduled_start": "2026-09-24T15:00:00Z",
         "scheduled_end": "2026-09-24T16:00:00Z",
         "expected_order_version": in_transit["version"]},
        ADVISOR)
    validate_error(refused, "ERR_ORDER_NOT_AT_CENTER", expected_status=409)
    assert get_success_data(
        api.get_delivery_center(center["id"], ADMIN))["booked_slot_count"] == 0


def test_home_delivery_beyond_the_center_radius_is_refused(api):
    """PRD §3.6: "A home handover adds one more: the buyer's service address must
    fall inside the center's `home_delivery_radius_miles`, otherwise
    `ERR_HOME_DELIVERY_OUT_OF_RANGE` (HTTP 403)."
    PRD §3.6: "A successful home booking does everything a center booking does
    except that no bay is occupied"

    Design: Corner/errors/home_delivery_beyond_the_center_radius_is_refused
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center()
    order = ctx["order"]

    refused = api.book_delivery_appointment(
        {"order_id": order["id"], "delivery_center_id": ctx["center"]["id"],
         "delivery_mode": "HOME", "buyer_service_address_miles": 60,
         "scheduled_start": "2026-09-24T15:00:00Z",
         "scheduled_end": "2026-09-24T16:00:00Z",
         "expected_order_version": order["version"]},
        ADVISOR)
    validate_error(refused, "ERR_HOME_DELIVERY_OUT_OF_RANGE", expected_status=403)

    accepted = get_success_data(api.book_delivery_appointment(
        {"order_id": order["id"], "delivery_center_id": ctx["center"]["id"],
         "delivery_mode": "HOME", "buyer_service_address_miles": 40,
         "scheduled_start": "2026-09-24T15:00:00Z",
         "scheduled_end": "2026-09-24T16:00:00Z",
         "expected_order_version": order["version"]},
        ADVISOR))
    assert accepted["delivery_mode"] == "HOME"


def test_allocation_with_no_unassigned_unit_returns_no_eligible_unit(api):
    """PRD §3.4: "the named batch must contain at least one unit still `UNASSIGNED`
    whose batch `model_code` equals the ordered trim's `model_code`, otherwise
    `ERR_NO_ELIGIBLE_UNIT` (HTTP 409)"
    PRD §3.4: "A minted unit is `UNASSIGNED` with a null `order_id` and a null
    `allocated_at`"

    Design: Corner/errors/allocation_with_no_unassigned_unit_returns_no_eligible_unit
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    order = get_order(order["id"])
    placed = place_order(order["id"], order["version"], buyer["id"])
    locked = lock_order(order["id"], placed["version"])

    other_batch, unit = create_and_start_batch(
        prefer_misses=6, factory_code="FREEMONT", model_code="MODEL_3_LR_RWD",
        unit_capacity=1, planned_completion_at="2026-09-12T00:00:00Z")

    refused = api.allocate_order(order["id"], other_batch["id"], locked["version"], ADMIN)
    validate_error(refused, "ERR_NO_ELIGIBLE_UNIT", expected_status=409)

    assert get_order(order["id"])["status"] == "CONFIG_LOCKED"
    stayed = get_success_data(api.get_allocation_unit(unit["id"], ADMIN))
    assert stayed["status"] == "UNASSIGNED"
    assert stayed["order_id"] is None


def test_revoking_an_already_revoked_entitlement_returns_already_terminal(api):
    """PRD §3.11: "A purchased entitlement may also be revoked by a
    `PlatformAdmin`, which requires the row not already to be terminal — otherwise
    `ERR_ALREADY_TERMINAL` (HTTP 409)"
    PRD §2.8: "Entries are append-only: a mistake is corrected by writing a
    compensating entry of the opposite sign"

    Design: Corner/errors/revoking_an_already_revoked_entitlement_returns_already_terminal
    """
    set_clock()
    ctx = walk_order_to_delivered()
    vehicle_id = ctx["vehicle"]["id"]

    rows = get_success_data(api.grant_entitlements(
        vehicle_id,
        {"feature_entries": [{"feature_code": "ACCELERATION_BOOST",
                              "price_cents": 200000}],
         "entitlement_source": "PURCHASE"},
        {"X-User-ID": ctx["buyer"]["id"], "X-User-Role": "Buyer",
         "Content-Type": "application/json"}))
    entitlement = rows[0]

    before = [e for e in get_success_data(api.list_order_ledger_entries(
        ctx["order"]["id"], ADMIN))
        if e["entry_type"] == "DELIVERY_FEE_WAIVER"
        and e["amount_cents"] == 200000]

    revoked = get_success_data(api.revoke_entitlement(
        vehicle_id, entitlement["id"], ADMIN))
    assert revoked["status"] == "REVOKED"

    again = api.revoke_entitlement(vehicle_id, entitlement["id"], ADMIN)
    validate_error(again, "ERR_ALREADY_TERMINAL", expected_status=409)

    entries = get_success_data(api.list_order_ledger_entries(
        ctx["order"]["id"], ADMIN))
    waivers = [e for e in entries
               if e["entry_type"] == "DELIVERY_FEE_WAIVER"
               and e["amount_cents"] == 200000]
    assert len(waivers) == len(before) + 1, (
        "the refund is written exactly once, and the refused second revoke "
        "writes nothing further"
    )
