"""State-machine edges: precondition gates, terminal lockdown, auto-created resources (PRD §3.1-§3.5, §3.7)."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    LOGISTICS_COORDINATOR_HEADERS,
    PLANT_SCHEDULER_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    WEEK_NEXT,
    WEEK_PLUS_2,
    WEEK_PLUS_4,
    canonical_instant,
    family_spec,
    make_retail_designer_headers,
    order_line,
)
from test_helpers import fixtures


def test_program_activate_without_line_rejected(api):
    """Activation requires exactly one ACTIVE line; with none the program stays
    DRAFT.

    PRD §3.1: "Activation then moves the program from `DRAFT` to `ACTIVE`, gated twice: the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the program must have exactly one `ACTIVE` line (`ERR_NO_ACTIVE_LINE`)."
    Design: Corner/state_machines/program_activate_without_line_rejected
    """
    fixtures.reset_clock(api)
    account = fixtures.create_account(api, name="Dealer F", credit_limit_cents=1000000)
    program = fixtures.create_program(api, account["id"])

    blocked = api.activate_program(program["id"], PROGRAM_MANAGER_HEADERS)
    validate_error(blocked, "ERR_NO_ACTIVE_LINE")
    assert fixtures.get_program(api, program["id"])["status"] == "DRAFT"


def test_shipment_terminal_delivered_rejects_transition(api):
    """A DELIVERED shipment has no outbound edge; the attempt changes nothing.

    PRD §3.5: "Marking the shipment `DELIVERED` stamps `delivered_at` from the logical clock and moves the order `SHIPPED` → `DELIVERED`."
    PRD §3.5: "Once a shipment exists, a `LogisticsCoordinator` drives it: `PLANNED` → `LOADED` → `IN_TRANSIT`, the latter moving the linked order from `MFG_COMPLETE` to `SHIPPED`."
    Design: Corner/state_machines/shipment_terminal_delivered_rejects_transition
    """
    world = fixtures.setup_delivered_order(api, slot_overrides={"week": WEEK_NEXT})
    shipment = world["shipment"]
    assert shipment["status"] == "DELIVERED"

    blocked = api.transition_shipment(
        shipment["id"], {"to_status": "FAILED"}, LOGISTICS_COORDINATOR_HEADERS
    )
    validate_error(blocked, "ERR_INVALID_STATE")

    after = fixtures.get_shipment(api, shipment["id"])
    assert after["status"] == "DELIVERED"
    assert after["attempt_count"] == 0
    assert canonical_instant(after["delivered_at"]) == canonical_instant("2026-09-01T00:00:00Z")


def test_shipment_retry_cycle_exhausts_to_auto_returned(api):
    """The FAILED -> PLANNED loop is bounded: the third failure auto-returns the
    shipment, and RETURNED refuses a re-plan.

    PRD §3.5: "A failed attempt (`IN_TRANSIT` → `FAILED`) increments the shipment's `attempt_count`, and the third failure — `attempt_count` reaching 3 — automatically moves the shipment to `RETURNED`."
    PRD §3.5: "While fewer than 3 attempts have been made, a `FAILED` shipment may be re-planned back to `PLANNED` for another try; a re-plan request against a shipment that is already `RETURNED` is rejected with `ERR_INVALID_STATE`."
    Design: Corner/state_machines/shipment_retry_cycle_exhausts_to_auto_returned
    """
    world = fixtures.setup_scheduled_order(api, slot_overrides={"week": WEEK_NEXT})
    fixtures.start_production(api, world["order"]["id"])
    fixtures.complete_manufacturing(api, world["order"]["id"])
    shipment = fixtures.get_shipment_for_order(api, world["order"]["id"])

    for attempt in (1, 2):
        fixtures.transition_shipment(api, shipment["id"], "LOADED")
        fixtures.transition_shipment(api, shipment["id"], "IN_TRANSIT")
        failed = fixtures.transition_shipment(api, shipment["id"], "FAILED")
        assert failed["attempt_count"] == attempt
        replanned = fixtures.transition_shipment(api, shipment["id"], "PLANNED")
        assert replanned["status"] == "PLANNED"

    fixtures.transition_shipment(api, shipment["id"], "LOADED")
    fixtures.transition_shipment(api, shipment["id"], "IN_TRANSIT")
    third = fixtures.transition_shipment(api, shipment["id"], "FAILED")
    assert third["attempt_count"] == 3

    after = fixtures.get_shipment(api, shipment["id"])
    assert after["status"] == "RETURNED"

    blocked = api.transition_shipment(
        shipment["id"], {"to_status": "PLANNED"}, LOGISTICS_COORDINATOR_HEADERS
    )
    validate_error(blocked, "ERR_INVALID_STATE")


def test_order_skipping_states_rejected(api):
    """SUBMITTED has exactly one fulfillment edge; jumping to IN_PRODUCTION is
    refused and leaves the order untouched.

    PRD §3.6: "The fulfillment dimension, carried by the order's `status` field, runs `SUBMITTED` → `ACKNOWLEDGED` → `SCHEDULED` → `IN_PRODUCTION` → `MFG_COMPLETE` → `SHIPPED` → `DELIVERED`, with `CANCELLED` as the early exit; the payment dimension, carried by `payment_status`, runs `UNINVOICED` → `INVOICED` → `PAID`, with `CREDIT_HOLD` hanging off `UNINVOICED`."
    Design: Corner/state_machines/order_skipping_states_rejected
    """
    world = fixtures.setup_submitted_order(api)

    blocked = api.transition_order(
        world["order"]["id"], {"to_status": "IN_PRODUCTION"}, PLANT_SCHEDULER_HEADERS
    )
    validate_error(blocked, "ERR_INVALID_STATE")

    after = fixtures.get_order(api, world["order"]["id"])
    assert after["status"] == "SUBMITTED"
    assert after["payment_status"] == "UNINVOICED"


def test_order_mfg_complete_auto_creates_planned_shipment(api):
    """Manufacturing completion creates exactly one PLANNED shipment with the
    destination copied from the order; the shipment is discoverable through the
    order's reverse filter.

    PRD §3.4: "Manufacturing completion, `IN_PRODUCTION` → `MFG_COMPLETE`, automatically creates the order's shipment in `PLANNED` — exactly one shipment per order — with its destination details copied across."
    PRD §3.2: "A successful conversion moves the job `QUOTED` → `CONVERTED` and creates the order in `SUBMITTED` with `payment_status` `UNINVOICED`: the order's `lines` are copied from `layout_lines`, `account_id` and `program_id` are copied across, `design_job_id` points back at the job, quoted pricing and the `promised_delivery_week` are computed, and the account's credit exposure is recomputed."
    Design: Corner/state_machines/order_mfg_complete_auto_creates_planned_shipment
    """
    # A STORE destination requires the store to be one of the account's
    # store_codes, and only a retail account has any — so the order is born
    # from the design-service conversion path.
    world = fixtures.setup_active_program(api, retail=True, store_codes=["ST-7"])
    job = fixtures.create_design_job(
        api, world["account"], world["program"], "des-1", store_code="ST-7"
    )
    fixtures.quote_design_job(api, job["id"], "des-1", [order_line(quantity=1)])
    order = fixtures.convert_design_job(
        api, job["id"], "des-1",
        destination_type="STORE", store_code="ST-7",
        requested_delivery_week=WEEK_PLUS_4,
    )
    assert order["destination_type"] == "STORE"
    assert order["store_code"] == "ST-7"

    fixtures.create_production_slot(api, plant_code="PLANT_WEST", week=WEEK_NEXT, capacity_units=10)
    fixtures.create_finish_batch(api)
    fixtures.acknowledge_order(api, order["id"])
    fixtures.schedule_order(api, order["id"])
    fixtures.start_production(api, order["id"])
    completed = fixtures.complete_manufacturing(api, order["id"])
    assert completed["status"] == "MFG_COMPLETE"

    data, meta = validate_paginated(
        api.list_shipments(LOGISTICS_COORDINATOR_HEADERS, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 1
    shipment = data[0]
    assert shipment["status"] == "PLANNED"
    assert shipment["destination_type"] == "STORE"
    assert shipment["store_code"] == "ST-7"
    assert shipment["jobsite_address"] is None


def test_display_resets_auto_created_per_store_on_supersede(api):
    """Superseding a retail program's line creates one PLANNED reset per store
    code and stamps the transition deadlines from the logical clock.

    PRD §3.7: "And when the program's account is a `RETAIL` channel partner, one display reset per element of its `store_codes` is created in `PLANNED` for the sunsetting line — each reset recording the `program_id`, the `line_id` of that line, and the `store_code` it belongs to."
    PRD §3.7: "The program moves `ACTIVE` → `TRANSITIONING`, stamping `transition_started_at` from the logical clock and computing two deadlines: `display_reset_deadline` at 45 days after the transition start, and `disposition_deadline` at 90 days after it."
    Design: Corner/state_machines/display_resets_auto_created_per_store_on_supersede
    """
    world = fixtures.setup_active_program(api, retail=True, store_codes=["ST-1", "ST-2"])
    line2 = fixtures.supersede_program_line(
        api,
        world["program"]["id"],
        line_code="L2",
        effective_start_week=WEEK_PLUS_2,
        families=[family_spec(standard_price_cents=11000, base_lead_weeks=2)],
        include_disposition_qty=True,
    )
    assert line2["status"] == "ACTIVE"

    data, meta = validate_paginated(
        api.list_display_resets(
            PROGRAM_MANAGER_HEADERS, params={"program_id": world["program"]["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert {reset["store_code"] for reset in data} == {"ST-1", "ST-2"}
    for reset in data:
        assert reset["status"] == "PLANNED"
        assert reset["line_id"] == world["line"]["id"]
        assert reset["program_id"] == world["program"]["id"]

    program = fixtures.get_program(api, world["program"]["id"])
    assert program["status"] == "TRANSITIONING"
    assert canonical_instant(program["display_reset_deadline"]) == canonical_instant(
        "2026-10-16T00:00:00Z"
    )


def test_design_job_cancelled_terminal_rejects_transition(api):
    """Cancellation is immediate from REQUESTED and the cancelled job refuses
    any further move.

    PRD §3.2: "From `REQUESTED`, `MEASURED`, `LAYOUT_READY`, or `QUOTED` the designer may instead abandon the job entirely, moving it to `CANCELLED`."
    Design: Corner/state_machines/design_job_cancelled_terminal_rejects_transition
    """
    world = fixtures.setup_active_program(api, retail=True, store_codes=["ST-1"])
    job = fixtures.create_design_job(api, world["account"], world["program"], "des-1")
    cancelled = fixtures.transition_design_job(api, job["id"], "CANCELLED", "des-1")
    assert cancelled["status"] == "CANCELLED"

    blocked = api.transition_design_job(
        job["id"], {"to_status": "MEASURED"}, make_retail_designer_headers("des-1")
    )
    validate_error(blocked, "ERR_INVALID_STATE")

    after = fixtures.get_design_job(api, job["id"], PROGRAM_MANAGER_HEADERS)
    assert after["status"] == "CANCELLED"
