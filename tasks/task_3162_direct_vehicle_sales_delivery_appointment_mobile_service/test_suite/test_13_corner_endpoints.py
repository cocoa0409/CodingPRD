"""Corner coverage: single-purpose endpoint guards."""
from test_helpers import (
    canonical_instant,
    TEST_USERS,
    create_and_enact_jurisdiction,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    dispatch_mobile_visit,
    get_order,
    get_success_data,
    place_order,
    set_clock,
    settle_order_fee,
    setup_triaged_mobile_appointment,
    validate_error,
    validate_paginated,
    walk_order_to_delivered,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]
PARTS = TEST_USERS["parts_coordinator_headers"]


def test_configuration_change_after_the_lock_deadline_is_refused(api):
    """PRD §3.2: "a revision arriving after that instant is refused with
    `ERR_CONFIG_LOCK_DEADLINE_PASSED` (HTTP 409)"
    PRD §3.2: "Once the order is `CONFIG_LOCKED`, every later configuration change
    request is rejected."

    Design: Corner/endpoints/configuration_change_after_the_lock_deadline_is_refused
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    option = get_success_data(api.create_configuration_option(
        config["id"],
        {"option_sku": "TOW_HITCH", "option_category": "TOWING", "price_cents": 130000},
        ADMIN))
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    order = get_order(order["id"])
    placed = place_order(order["id"], order["version"], buyer["id"])

    # A full day past the deadline, so the millisecond it carries is the whole
    # of the change being made.
    get_success_data(api.set_current_utc("2026-09-16T00:00:00.001Z", ADMIN))

    refused = api.change_configuration(
        order["id"],
        {"add_option_ids": [option["id"]], "remove_option_ids": [],
         "expected_order_version": placed["version"]},
        {"X-User-ID": buyer["id"], "X-User-Role": "Buyer",
         "Content-Type": "application/json"})
    validate_error(refused, "ERR_CONFIG_LOCK_DEADLINE_PASSED", expected_status=409)

    # The refused change attached nothing, so the total is the core plus the
    # order fee, the documentation fee, the delivery fee — and the late fee,
    # which the clock has now carried strictly past the lock deadline (PRD 3.7).
    assert get_order(order["id"])["order_total_due_cents"] == \
        4799000 + 25000 + 25000 + 7500 + 2500, (
        "the refused change attached no option"
    )
    rows = get_success_data(api.list_configuration_options(config["id"], ADMIN))
    assert rows[0]["status"] == "ACTIVE"


def test_issue_note_waiver_requires_a_reason(api):
    """PRD §3.6: "The waiver requires a non-empty `waiver_reason`, and a waiver
    without one is refused with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.12: "a waiver with an empty or absent `waiver_reason` is refused with
    `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/endpoints/issue_note_waiver_requires_a_reason
    """
    set_clock()
    ctx = walk_order_to_delivered(
        inspection_result="ISSUES_DOCUMENTED",
        documented_issues=[{"issue_code": "PAINT_CHIP", "observed_mileage": 4,
                            "blocked_handover": True}])
    notes = get_success_data(api.list_order_issue_notes(ctx["order"]["id"], ADMIN))
    assert len(notes) == 1
    note = notes[0]

    refused = api.waive_issue_note(note["id"], {"waiver_reason": ""}, ADMIN)
    validate_error(refused, "ERR_INVALID_REQUEST", expected_status=400)
    assert get_success_data(api.get_issue_note(note["id"], ADMIN))["status"] == "OPEN"

    waived = get_success_data(api.waive_issue_note(
        note["id"], {"waiver_reason": "buyer accepted documented chip"}, ADMIN))
    assert waived["status"] == "WAIVED"


def test_parts_shipment_confirmation_requires_the_parts_reserved_step(api):
    """PRD §3.10: "Starting the drive requires `parts_pre_shipped_at` to be
    non-null, otherwise the request is refused with `ERR_PARTS_NOT_PRE_SHIPPED`
    (HTTP 409) — a visit cannot go en route before its parts have left the depot"
    PRD §3.10: "reserving parts requires the visit to be `DRAFT` — otherwise
    `ERR_INVALID_STATE` — and requires the linked report to have `parts_required`
    true, otherwise `ERR_PARTS_NOT_REQUIRED` (HTTP 409); on success the visit
    becomes `PARTS_RESERVED`"

    Design: Corner/endpoints/parts_shipment_confirmation_requires_the_parts_reserved_step
    """
    set_clock()
    ctx = _mobile_scenario_needing_parts()
    visit = ctx["visit"]

    reserved = get_success_data(api.reserve_parts(visit["id"], PARTS))
    assert reserved["status"] == "PARTS_RESERVED"

    # The driven milestone is ordered strictly after the shipment one: neither
    # can be reached from a visit that has not earned its parts milestone.
    premature = api.start_mobile_visit(visit["id"], TECH)
    validate_error(premature, "ERR_INVALID_STATE", expected_status=409)

    shipped = get_success_data(api.confirm_parts_shipment(visit["id"], PARTS))
    assert shipped["status"] == "PARTS_SHIPPED"
    assert canonical_instant(shipped["parts_pre_shipped_at"]) == "2026-09-01T00:00:00.000Z"
    assert shipped["visit_cost_cents"] == 58500 + 26000 + 0

    en_route = get_success_data(api.start_mobile_visit(visit["id"], TECH))
    assert en_route["status"] == "EN_ROUTE"

    # A visit that has not yet had its parts reserved cannot be shipped either:
    # the same shipment endpoint refuses a row that has not reached PARTS_RESERVED.
    fresh_ctx = _mobile_scenario_needing_parts(van_code="VAN-SHIP-2",
                                               start="2026-09-29T14:00:00Z",
                                               end="2026-09-29T17:00:00Z")
    blocked = api.confirm_parts_shipment(fresh_ctx["visit"]["id"], PARTS)
    validate_error(blocked, "ERR_INVALID_STATE", expected_status=409)


def _mobile_scenario_needing_parts(van_code="VAN-SHIP-1",
                                   start="2026-09-28T14:00:00Z",
                                   end="2026-09-28T17:00:00Z"):
    """A delivered vehicle with a parts-requiring MOBILE report and a DRAFT visit."""
    scenario = setup_triaged_mobile_appointment(
        fault_code="SUS-5100", severity="MEDIUM", is_driveable=True)
    visit = dispatch_mobile_visit(
        scenario["appointment"]["id"], scenario["hub"]["id"],
        scenario["appointment"]["version"], van_code=van_code,
        start=start, end=end, labor_hours=3.0,
        parts_cost_cents=26000, visit_miles=18)
    scenario["visit"] = visit
    return scenario


def test_manual_ledger_posting_moves_the_buyer_balance(api):
    """PRD §2.8: "Money that moves is recorded as a `OrderFeeLedgerEntry` rather
    than as a direct edit to a balance."
    PRD §2.8: "Every ledger write recomputes the affected `Buyer`'s
    `order_credit_balance_cents`"

    Design: Corner/endpoints/manual_ledger_posting_moves_the_buyer_balance
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    place_order(order["id"], order["version"], buyer["id"])

    entry = get_success_data(api.post_ledger_entry(
        order["id"],
        {"entry_type": "DELIVERY_FEE_CHARGE", "amount_cents": -2500,
         "reason_code": "HOME_DELIVERY_SURCHARGE"}, ADMIN))
    assert entry["amount_cents"] == -2500
    assert entry["entry_type"] == "DELIVERY_FEE_CHARGE"
    assert entry["reason_code"] == "HOME_DELIVERY_SURCHARGE"

    buyer_after = get_success_data(api.get_buyer(buyer["id"], ADMIN))
    assert buyer_after["order_credit_balance_cents"] == 22500

    entries, _meta = validate_paginated(api.list_buyer_ledger_entries(buyer["id"], ADMIN))
    assert len(entries) == 2
