"""Cross-entity gates: account status gates order flow; shipment state gates claims (PRD §3.1, §3.3, §3.4, §3.5)."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    LOGISTICS_COORDINATOR_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    WEEK_NEXT,
    factories,
    make_dealer_rep_headers,
    order_line,
)
from test_helpers import fixtures


def test_acknowledge_blocked_while_account_suspended(api):
    """The acknowledge transition reads the account aggregate: SUSPENDED
    refuses, re-activation reopens.

    PRD §3.4: "An order moves from `SUBMITTED` to `ACKNOWLEDGED` only on a `ProgramManager`'s acknowledgement, gated on an `ACTIVE` account and a program in `ACTIVE` or `TRANSITIONING`."
    PRD §3.1: "A `PlatformAdmin` moves an account between `ACTIVE` and `SUSPENDED` in either direction by submitting the desired `to_status`, and from either of those states to terminal `CLOSED`."
    Design: Difficulty/cross_entity_state_dependency/order_acknowledge_gated_by_account_status
    """
    world = fixtures.setup_submitted_order(api)
    fixtures.set_account_status(api, world["account"]["id"], "SUSPENDED")

    blocked = api.transition_order(
        world["order"]["id"], {"to_status": "ACKNOWLEDGED"},
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(blocked, "ERR_ACCOUNT_NOT_ACTIVE")
    assert fixtures.get_order(api, world["order"]["id"])["status"] == "SUBMITTED"

    fixtures.set_account_status(api, world["account"]["id"], "ACTIVE")
    acknowledged = fixtures.acknowledge_order(api, world["order"]["id"])
    assert acknowledged["status"] == "ACKNOWLEDGED"


def test_order_create_and_program_activate_blocked_while_suspended(api):
    """The same account gate guards order placement and program activation.

    PRD §3.3: "The caller's `X-User-ID` must equal the order's `account_id` (`ERR_FORBIDDEN`), the account must be `ACTIVE` and the program `ACTIVE` or `TRANSITIONING` (`ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`), and every `family_code` must be covered by the program's `ACTIVE` line (`ERR_LINE_NOT_COVERED`)."
    PRD §3.1: "Activation then moves the program from `DRAFT` to `ACTIVE`, gated twice: the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the program must have exactly one `ACTIVE` line (`ERR_NO_ACTIVE_LINE`)."
    Design: Difficulty/cross_entity_state_dependency/order_acknowledge_gated_by_account_status
    """
    world = fixtures.setup_active_program(api)
    fixtures.set_account_status(api, world["account"]["id"], "SUSPENDED")

    order_attempt = api.create_order(
        factories.order_payload(world["account"]["id"], world["program"]["id"]),
        make_dealer_rep_headers(world["account"]["id"]),
    )
    validate_error(order_attempt, "ERR_ACCOUNT_NOT_ACTIVE")

    program2 = fixtures.create_program(api, world["account"]["id"], name="P2")
    fixtures.create_first_line(api, program2["id"], line_code="L1")
    activate_attempt = api.activate_program(
        program2["id"], PROGRAM_MANAGER_HEADERS
    )
    validate_error(activate_attempt, "ERR_ACCOUNT_NOT_ACTIVE")
    assert fixtures.get_program(api, program2["id"])["status"] == "DRAFT"


def test_claim_rejected_until_shipment_delivered(api):
    """Filing against an IN_TRANSIT shipment is refused; the identical filing
    succeeds once the shipment is DELIVERED and the order follows it.

    PRD §3.5: "Filing is gated on every side: the shipment must be `DELIVERED` (`ERR_SHIPMENT_NOT_DELIVERED`); the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`); the filing must fall no later than 14 days after the shipment's `delivered_at` — the deadline is inclusive, so a filing exactly 14 days after delivery passes, while a later one fails with `ERR_CLAIM_WINDOW_EXPIRED`; and the aggregate `claimed_qty` across all non-`DENIED` claims against the same shipment and `line_index` must not exceed the shipped line quantity (`ERR_CLAIM_QUANTITY_EXCEEDED`)."
    PRD §3.5: "Marking the shipment `DELIVERED` stamps `delivered_at` from the logical clock and moves the order `SHIPPED` → `DELIVERED`."
    Design: Difficulty/cross_entity_state_dependency/claim_filing_gated_by_shipment_state
    """
    world = fixtures.setup_scheduled_order(api, slot_overrides={"week": WEEK_NEXT})
    fixtures.start_production(api, world["order"]["id"])
    fixtures.complete_manufacturing(api, world["order"]["id"])
    shipment = fixtures.get_shipment_for_order(api, world["order"]["id"])
    fixtures.transition_shipment(api, shipment["id"], "LOADED")
    fixtures.transition_shipment(api, shipment["id"], "IN_TRANSIT")

    early = api.create_claim(
        factories.claim_payload(shipment["id"], world["order"]["id"], claimed_qty=1),
        LOGISTICS_COORDINATOR_HEADERS,
    )
    validate_error(early, "ERR_SHIPMENT_NOT_DELIVERED")

    fixtures.transition_shipment(api, shipment["id"], "DELIVERED")
    late = api.create_claim(
        factories.claim_payload(shipment["id"], world["order"]["id"], claimed_qty=1),
        LOGISTICS_COORDINATOR_HEADERS,
    )
    claim = validate_success(late, 201)
    assert claim["status"] == "FILED"

    order = fixtures.get_order(api, world["order"]["id"])
    assert order["status"] == "DELIVERED"


def test_claim_rejected_while_shipment_planned(api):
    """A shipment that exists but has not left PLANNED is likewise not
    DELIVERED, so the claim is refused with the same error.

    PRD §3.5: "Filing is gated on every side: the shipment must be `DELIVERED` (`ERR_SHIPMENT_NOT_DELIVERED`); the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`); the filing must fall no later than 14 days after the shipment's `delivered_at` — the deadline is inclusive, so a filing exactly 14 days after delivery passes, while a later one fails with `ERR_CLAIM_WINDOW_EXPIRED`; and the aggregate `claimed_qty` across all non-`DENIED` claims against the same shipment and `line_index` must not exceed the shipped line quantity (`ERR_CLAIM_QUANTITY_EXCEEDED`)."
    Design: Difficulty/cross_entity_state_dependency/claim_filing_gated_by_shipment_state
    """
    world = fixtures.setup_scheduled_order(api, slot_overrides={"week": WEEK_NEXT})
    fixtures.start_production(api, world["order"]["id"])
    fixtures.complete_manufacturing(api, world["order"]["id"])
    shipment = fixtures.get_shipment_for_order(api, world["order"]["id"])
    assert shipment["status"] == "PLANNED"

    refused = api.create_claim(
        factories.claim_payload(shipment["id"], world["order"]["id"], claimed_qty=1),
        LOGISTICS_COORDINATOR_HEADERS,
    )
    validate_error(refused, "ERR_SHIPMENT_NOT_DELIVERED")
