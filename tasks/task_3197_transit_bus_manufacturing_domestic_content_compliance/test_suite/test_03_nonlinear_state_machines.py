"""Depth tests: non-linear state machines (configuration revision cycle,
parallel bus build/payment dimensions)."""
from test_helpers import (
    TEST_USERS,
    build_bus_to_accepted,
    create_bus_configuration_payload,
    create_draft_contract,
    create_agency,
    create_component,
    get_success_data,
    setup_accepted_bus,
    setup_active_contract,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]


def test_configuration_revision_cycle_accumulates_freeze_version(api):
    """PRD section 3.3: "A successful freeze computes the `seat_count` from
    the seating layout, locks it, moves the configuration
    `ENGINEERING_REVIEW` → `FROZEN`, and increments `freeze_version` by one —
    the revision counter that accumulates across the configuration's life."
    PRD section 3.3: "a `FROZEN` configuration may also be returned to
    `DRAFT` — unlocking its `seat_count` — provided no bus unit references it
    in any status other than `ORDERED`."

    Design: Difficulty/non_linear_state_machine/bus_configuration_revision_cycle
    """
    agency = create_agency()
    contract = create_draft_contract(agency["id"], base_quantity=3,
                                     escalation_index="CPI_U")
    component = create_component()
    resp = api.create_bus_configuration(
        create_bus_configuration_payload(contract["id"], [component["id"]]),
        CE,
    )
    cfg = get_success_data(resp)
    get_success_data(api.submit_review_configuration(cfg["id"], CE))
    resp = api.freeze_configuration(
        cfg["id"], {"expected_contract_version": contract["version"]}, CE
    )
    frozen1 = validate_success(resp)
    assert frozen1["freeze_version"] == 1, (
        f"first freeze must set freeze_version 1, got {frozen1['freeze_version']}"
    )

    # Revision loop: FROZEN -> DRAFT -> ENGINEERING_REVIEW -> FROZEN.
    get_success_data(api.return_to_draft_configuration(cfg["id"], CE))
    get_success_data(api.submit_review_configuration(cfg["id"], CE))
    contract = get_success_data(api.get_contract(contract["id"], PO))
    resp = api.freeze_configuration(
        cfg["id"], {"expected_contract_version": contract["version"]}, CE
    )
    frozen2 = validate_success(resp)
    assert frozen2["status"] == "FROZEN"
    assert frozen2["freeze_version"] == 2, (
        "freeze_version accumulates across the revision loop: second freeze "
        f"must set freeze_version 2, got {frozen2['freeze_version']}"
    )


def test_configuration_seat_count_locked_on_each_freeze(api):
    """PRD section 3.3: "A successful freeze computes the `seat_count` from
    the seating layout, locks it, moves the configuration
    `ENGINEERING_REVIEW` → `FROZEN`, and increments `freeze_version` by one —
    the revision counter that accumulates across the configuration's life."
    PRD section 3.3: "Configurations are revisable."

    Design: Difficulty/non_linear_state_machine/bus_configuration_revision_cycle
    """
    agency = create_agency()
    contract = create_draft_contract(agency["id"], base_quantity=3,
                                     escalation_index="CPI_U")
    component = create_component()
    resp = api.create_bus_configuration(
        create_bus_configuration_payload(contract["id"], [component["id"]]),
        CE,
    )
    cfg = get_success_data(resp)
    get_success_data(api.submit_review_configuration(cfg["id"], CE))
    resp = api.freeze_configuration(
        cfg["id"], {"expected_contract_version": contract["version"]}, CE
    )
    frozen1 = validate_success(resp)
    seat_count_1 = frozen1["seat_count"]
    assert isinstance(seat_count_1, int) and seat_count_1 >= 10

    get_success_data(api.return_to_draft_configuration(cfg["id"], CE))
    get_success_data(api.submit_review_configuration(cfg["id"], CE))
    contract = get_success_data(api.get_contract(contract["id"], PO))
    resp = api.freeze_configuration(
        cfg["id"], {"expected_contract_version": contract["version"]}, CE
    )
    frozen2 = validate_success(resp)
    # Same seating layout re-frozen: seat_count is recomputed and locked again.
    assert frozen2["seat_count"] == seat_count_1, (
        "seat_count is locked per freeze from the same seating layout; got "
        f"{frozen2['seat_count']} vs {seat_count_1}"
    )


def test_acceptance_advances_payment_to_invoiced(api):
    """PRD section 3.8: "Acceptance also starts the money moving: the bus's
    `payment_status` advances `UNPAID` → `INVOICED`."
    PRD section 3.8: "Payment is an independent, parallel dimension of the
    bus's life, tracked in `payment_status` separately from the
    build-and-delivery `status`."

    Design: Difficulty/non_linear_state_machine/bus_unit_parallel_status_and_payment_dimensions
    """
    setup = setup_accepted_bus()
    bus = setup["bus"]
    assert bus["status"] == "ACCEPTED"
    assert bus["payment_status"] == "INVOICED", (
        "acceptance advances payment_status UNPAID -> INVOICED, got "
        f"{bus['payment_status']}"
    )


def test_record_payment_advances_payment_without_touching_build_status(api):
    """PRD section 3.8: "Once a bus is `ACCEPTED` and its `payment_status` is
    `INVOICED`, a `ProcurementOfficer` records the agency's payment, advancing
    `payment_status` from `INVOICED` to `PAID`."
    PRD section 3.8: "Payment is an independent, parallel dimension of the
    bus's life, tracked in `payment_status` separately from the
    build-and-delivery `status`."

    Design: Difficulty/non_linear_state_machine/bus_unit_parallel_status_and_payment_dimensions
    """
    setup = setup_accepted_bus()
    bus = setup["bus"]
    assert bus["payment_status"] == "INVOICED"

    resp = api.record_payment(bus["id"], PO)
    paid = validate_success(resp)
    assert paid["payment_status"] == "PAID", (
        f"record-payment advances INVOICED -> PAID, got {paid['payment_status']}"
    )
    assert paid["status"] == "ACCEPTED", (
        "payment must not touch the build-and-delivery status; got "
        f"{paid['status']}"
    )
