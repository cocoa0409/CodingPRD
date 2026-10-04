"""Optimistic concurrency on program lineage and immediate consistency (PRD §2.2, §2.7, §3.1)."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    PROGRAM_MANAGER_HEADERS,
    WEEK_PLUS_2,
    WEEK_PLUS_4,
    factories,
    family_spec,
)
from test_helpers import fixtures


def test_occ_stale_program_version_rejected(api):
    """A line create carrying a version the program has already advanced past
    is refused with 412 — the OCC check fires before the TRANSITIONING state
    gate.

    PRD §2.7: "Such a request must include `expected_program_version`, carrying the `version` of the program as the client last observed it."
    PRD §2.7: "If the program's current `version` has advanced since that observation — for example because another line creation has already superseded the line the client was reading and moved the program forward — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot build on a program state it never saw."
    PRD §2.9: "The stages, from first to last: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) authorization — the endpoint's role list, the per-transition role pins described in §3, entity-backed ownership, and claim segregation of duties (`ERR_FORBIDDEN`, `ERR_SEGREGATION_OF_DUTIES`); (3) existence of every path identifier and request-body reference (`ERR_NOT_FOUND`); (4) the optimistic-concurrency check on program-line creation (`ERR_STALE_VERSION`); (5) state legality — the entity's state machine plus the lifecycle gates (`ERR_INVALID_STATE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_TRANSITIONING`, `ERR_NO_ACTIVE_LINE`, `ERR_QUOTE_STALE`, `ERR_SHIPMENT_NOT_DELIVERED`, `ERR_ORDER_NOT_CANCELLABLE`); (6) referential business rules (`ERR_LINE_NOT_COVERED`, `ERR_STORE_NOT_SERVICED`, `ERR_NO_CURRENT_BATCH`, `ERR_INVALID_REQUEST`, `ERR_CHANNEL_REQUIRES_DESIGN_JOB`); (7) temporal rules (`ERR_DESIGNER_WINDOW_OVERLAP`, `ERR_MEASURE_WINDOW_INVALID`, `ERR_DELIVERY_WEEK_INVALID`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_SLOT_WEEK_PAST`, `ERR_DISPOSITION_WINDOW_EXPIRED`); (8) constraint checks (`ERR_SLOT_EXISTS`, `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_CLAIM_QUANTITY_EXCEEDED`, `ERR_COLOR_MISMATCH`, `ERR_NO_CAPACITY`, `ERR_DISPOSITION_OVERAGE`, `ERR_ACCOUNT_HAS_OPEN_ORDERS`); and finally (9) the fiscal gate at order scheduling (`ERR_CREDIT_HOLD`)."
    Design: Corner/complexity_layers/occ_stale_program_version_rejected
    """
    world = fixtures.setup_active_program(api)
    program = fixtures.get_program(api, world["program"]["id"])
    stale_version = program["version"]

    # The first supersede advances the program past the captured version.
    fixtures.supersede_program_line(
        api,
        program["id"],
        line_code="L2",
        effective_start_week=WEEK_PLUS_2,
        families=[family_spec(standard_price_cents=11000, base_lead_weeks=2)],
        include_disposition_qty=True,
    )

    stale = api.create_program_line(
        program["id"],
        factories.program_line_payload(
            stale_version,
            line_code="L3",
            effective_start_week=WEEK_PLUS_4,
            families=[family_spec(standard_price_cents=12000, base_lead_weeks=2)],
            include_disposition_qty=True,
        ),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)

    lines, meta = validate_paginated(
        api.list_lines(PROGRAM_MANAGER_HEADERS, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 2
    assert {line["line_code"] for line in lines} == {"L1", "L2"}


def test_occ_current_version_succeeds_and_version_increments(api):
    """A fresh version passes the OCC check, the program's version advances by
    exactly one, and a still-fresh follow-up then meets the state gate instead.

    PRD §3.1: "Creating a line is also a mutation of the program itself: the program's `version` advances by one on every line creation, which is exactly the staleness the `expected_program_version` check of §2.7 guards against."
    PRD §3.1: "Once a program has entered `TRANSITIONING` — the supersede flow of §3.7 — neither activation nor further line creation is permitted (`ERR_PROGRAM_TRANSITIONING`)."
    PRD §2.7: "No other endpoint accepts a version field; every other write conflict in the system is mediated by state-machine preconditions."
    Design: Corner/complexity_layers/occ_current_version_succeeds_and_version_increments
    """
    world = fixtures.setup_active_program(api)
    program = fixtures.get_program(api, world["program"]["id"])
    version_pre = program["version"]

    created = api.create_program_line(
        program["id"],
        factories.program_line_payload(
            version_pre,
            line_code="L2",
            effective_start_week=WEEK_PLUS_2,
            families=[family_spec(standard_price_cents=11000, base_lead_weeks=2)],
            include_disposition_qty=True,
        ),
        PROGRAM_MANAGER_HEADERS,
    )
    line2 = validate_success(created, 201)
    assert line2["status"] == "ACTIVE"
    assert line2["supersedes_line_id"] == world["line"]["id"]

    program_after = fixtures.get_program(api, program["id"])
    assert program_after["version"] == version_pre + 1
    assert program_after["status"] == "TRANSITIONING"

    # The OCC layer is satisfied by the fresh version; the state gate answers.
    transitioning = api.create_program_line(
        program["id"],
        factories.program_line_payload(
            program_after["version"],
            line_code="L3",
            effective_start_week=WEEK_PLUS_4,
            families=[family_spec(standard_price_cents=12000, base_lead_weeks=2)],
            include_disposition_qty=True,
        ),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(transitioning, "ERR_PROGRAM_TRANSITIONING")


def test_mutation_visible_immediately_in_same_response(api):
    """The acknowledge response body itself carries the mutated fields, and the
    account read right after shows the recomputed exposure.

    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.4: "Acknowledgement sets the order's `price_lock` to true and runs the credit evaluation of §2.8: if including the order pushes the account's `open_exposure_cents` strictly above its `credit_limit_cents`, the order's `payment_status` becomes `CREDIT_HOLD`; otherwise it stays `UNINVOICED`."
    PRD §2.8: "The exposure is recomputed — as an Account mutation in the sense of §2.5 — whenever an order of the account is created, acknowledged, or cancelled, whenever an order is invoiced or paid, whenever a line supersede reprices the account's orders, and whenever a suspended account returns to `ACTIVE`."
    Design: Corner/consistency_model/mutation_visible_immediately_in_same_response
    """
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": 1000000}
    )
    order = fixtures.place_order(api, world["account"], world["program"])
    assert order["status"] == "SUBMITTED"
    assert order["quoted_total_cents"] == 9500

    resp = api.transition_order(
        order["id"], {"to_status": "ACKNOWLEDGED"}, PROGRAM_MANAGER_HEADERS
    )
    acknowledged = validate_success(resp, 200)
    # The mutation is visible in the response body itself — no re-read needed.
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["price_lock"] is True
    assert acknowledged["payment_status"] == "UNINVOICED"

    account = fixtures.get_account(api, world["account"]["id"])
    assert account["open_exposure_cents"] == 9500
