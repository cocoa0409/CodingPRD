"""Validation rules: authentication, temporal windows, referential checks, aggregates (PRD §2.1, §2.9, §3.2-§3.5, §3.7)."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    LOGISTICS_COORDINATOR_HEADERS,
    PLANT_SCHEDULER_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    RETAIL_DESIGNER_HEADERS,
    WEEK_MINUS_1,
    WEEK_NEXT,
    WEEK_PLUS_2,
    WEEK_PLUS_4,
    factories,
    headers_without_role,
    make_claims_adjuster_headers,
    make_dealer_rep_headers,
    make_retail_designer_headers,
    order_line,
)
from test_helpers import fixtures


def test_missing_role_header_unauthenticated(api):
    """A request without the role header is rejected before anything else runs.

    PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity."
    PRD §2.1: "A request missing either header, or presenting a role value outside the recognized set, is rejected with `ERR_UNAUTHENTICATED`."
    Design: Corner/validations/missing_role_header_unauthenticated
    """
    resp = api.list_programs(headers_without_role())
    validate_error(resp, "ERR_UNAUTHENTICATED")


def test_claim_window_day14_inclusive_day15_expired(api):
    """The claim window closes after delivered_at + 14 days, inclusively.

    PRD §3.5: "the filing must fall no later than 14 days after the shipment's `delivered_at` — the deadline is inclusive, so a filing exactly 14 days after delivery passes, while a later one fails with `ERR_CLAIM_WINDOW_EXPIRED`"
    Design: Corner/validations/claim_window_day14_inclusive_day15_expired
    """
    world = fixtures.setup_delivered_order(
        api,
        order_overrides={"lines": [order_line(quantity=2)]},
        slot_overrides={"week": WEEK_NEXT, "capacity_units": 10},
    )
    shipment = world["shipment"]

    # Delivery happened at the default clock (2026-09-01); day 14 passes.
    fixtures.reset_clock(api, "2026-09-15T00:00:00Z")
    day14 = api.create_claim(
        factories.claim_payload(shipment["id"], world["order"]["id"], claimed_qty=1),
        LOGISTICS_COORDINATOR_HEADERS,
    )
    claim = validate_success(day14, 201)
    assert claim["status"] == "FILED"

    fixtures.reset_clock(api, "2026-09-16T00:00:00Z")
    day15 = api.create_claim(
        factories.claim_payload(shipment["id"], world["order"]["id"], claimed_qty=1),
        LOGISTICS_COORDINATOR_HEADERS,
    )
    validate_error(day15, "ERR_CLAIM_WINDOW_EXPIRED")


def test_disposition_deadline_gates_all_actions_except_destroy(api):
    """Past the 90-day disposition deadline, RTV is refused while DESTROY still
    drains the remainder.

    PRD §3.7: "Once the logical clock has passed the program's `disposition_deadline`, `RTV`, `LIQUIDATE`, and `TRANSFER` actions are rejected with `ERR_DISPOSITION_WINDOW_EXPIRED`; `DESTROY` remains lawful past the deadline."
    PRD §3.7: "The program moves `ACTIVE` → `TRANSITIONING`, stamping `transition_started_at` from the logical clock and computing two deadlines: `display_reset_deadline` at 45 days after the transition start, and `disposition_deadline` at 90 days after it."
    Design: Corner/validations/disposition_deadline_gates_all_actions_except_destroy
    """
    world = fixtures.setup_transitioning_program(api, store_codes=["ST-1"], disposition_qty=50)
    line1 = world["line1"]
    assert line1["remaining_disposition_qty"] == 50

    # 2026-09-01 + 90 days = 2026-11-30; 2026-12-01 is past the deadline.
    fixtures.reset_clock(api, "2026-12-01T00:00:00Z")

    expired = api.append_disposition_action(
        line1["id"], factories.disposition_action_payload("RTV", 10), PROGRAM_MANAGER_HEADERS
    )
    validate_error(expired, "ERR_DISPOSITION_WINDOW_EXPIRED")

    destroyed = api.append_disposition_action(
        line1["id"], factories.disposition_action_payload("DESTROY", 10), PROGRAM_MANAGER_HEADERS
    )
    line = validate_success(destroyed, 201)
    assert line["remaining_disposition_qty"] == 40


def test_store_not_in_account_codes_rejected(api):
    """A design job may only be booked at a store the account operates.

    PRD §3.2: "The store must be an element of the account's `store_codes` (`ERR_STORE_NOT_SERVICED`), the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the window must be well-formed: `measure_window_end` strictly after `measure_window_start`, with `measure_window_start` not earlier than the logical clock (`ERR_MEASURE_WINDOW_INVALID`)."
    Design: Corner/validations/store_not_in_account_codes_rejected
    """
    world = fixtures.setup_active_program(api, retail=True, store_codes=["ST-1"])

    refused = api.create_design_job(
        factories.design_job_payload(
            world["account"]["id"], world["program"]["id"], store_code="ST-9"
        ),
        RETAIL_DESIGNER_HEADERS,
    )
    validate_error(refused, "ERR_STORE_NOT_SERVICED")


def test_measure_window_in_past_rejected(api):
    """A measurement window starting before the logical clock is malformed.

    PRD §3.2: "The store must be an element of the account's `store_codes` (`ERR_STORE_NOT_SERVICED`), the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the window must be well-formed: `measure_window_end` strictly after `measure_window_start`, with `measure_window_start` not earlier than the logical clock (`ERR_MEASURE_WINDOW_INVALID`)."
    Design: Corner/validations/measure_window_in_past_rejected
    """
    world = fixtures.setup_active_program(api, retail=True, store_codes=["ST-1"])

    refused = api.create_design_job(
        factories.design_job_payload(
            world["account"]["id"], world["program"]["id"],
            measure_window_start="2026-08-30T09:00:00Z",
            measure_window_end="2026-08-30T10:00:00Z",
        ),
        RETAIL_DESIGNER_HEADERS,
    )
    validate_error(refused, "ERR_MEASURE_WINDOW_INVALID")


def test_delivery_week_before_lead_window_rejected(api):
    """Requested W37 with a 3-week lead backs production into W34, before the
    current W36.

    PRD §3.3: "The `requested_delivery_week` must be feasible: subtracting the smallest `base_lead_weeks` among the ordered families from it must not land before the current week (`ERR_DELIVERY_WEEK_INVALID`)."
    Design: Corner/validations/delivery_week_before_lead_window_rejected
    """
    world = fixtures.setup_active_program(api)

    refused = api.create_order(
        factories.order_payload(
            world["account"]["id"], world["program"]["id"],
            requested_delivery_week=WEEK_NEXT,  # 2026-W37
        ),
        make_dealer_rep_headers(world["account"]["id"]),
    )
    validate_error(refused, "ERR_DELIVERY_WEEK_INVALID")


def test_duplicate_slot_plant_family_week_rejected(api):
    """The (plant_code, family_code, week) triple is unique.

    PRD §3.4: "The combination of `plant_code`, `family_code`, and `week` is unique (`ERR_SLOT_EXISTS`), and a slot may not be opened for a week before the current one (`ERR_SLOT_WEEK_PAST`)."
    Design: Corner/validations/duplicate_slot_plant_family_week_rejected
    """
    fixtures.reset_clock(api)
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=50)

    duplicate = api.create_production_slot(
        factories.production_slot_payload(week=WEEK_NEXT, capacity_units=80),
        PLANT_SCHEDULER_HEADERS,
    )
    validate_error(duplicate, "ERR_SLOT_EXISTS")

    slots, meta = validate_paginated(
        api.list_production_slots(
            PLANT_SCHEDULER_HEADERS, params={"family_code": "F1", "week": "2026-W37"}
        )
    )
    assert meta["total_count"] == 1
    assert slots[0]["capacity_units"] == 50


def test_slot_for_past_week_rejected(api):
    """A bucket for a week before the current one cannot be opened.

    PRD §3.4: "The combination of `plant_code`, `family_code`, and `week` is unique (`ERR_SLOT_EXISTS`), and a slot may not be opened for a week before the current one (`ERR_SLOT_WEEK_PAST`)."
    Design: Corner/validations/slot_for_past_week_rejected
    """
    fixtures.reset_clock(api)
    refused = api.create_production_slot(
        factories.production_slot_payload(week=WEEK_MINUS_1), PLANT_SCHEDULER_HEADERS
    )
    validate_error(refused, "ERR_SLOT_WEEK_PAST")


def test_claim_quantity_aggregate_across_claims_exceeded(api):
    """Two individually-legal claims over the same line exceed the shipped
    quantity in aggregate.

    PRD §3.5: "the aggregate `claimed_qty` across all non-`DENIED` claims against the same shipment and `line_index` must not exceed the shipped line quantity (`ERR_CLAIM_QUANTITY_EXCEEDED`)"
    Design: Corner/validations/claim_quantity_aggregate_across_claims_exceeded
    """
    world = fixtures.setup_delivered_order(
        api,
        order_overrides={"lines": [order_line(quantity=2)]},
        slot_overrides={"week": WEEK_NEXT, "capacity_units": 10},
    )
    shipment = world["shipment"]

    first = api.create_claim(
        factories.claim_payload(shipment["id"], world["order"]["id"], claimed_qty=2),
        LOGISTICS_COORDINATOR_HEADERS,
    )
    assert validate_success(first, 201)["claimed_qty"] == 2

    second = api.create_claim(
        factories.claim_payload(shipment["id"], world["order"]["id"], claimed_qty=1),
        LOGISTICS_COORDINATOR_HEADERS,
    )
    validate_error(second, "ERR_CLAIM_QUANTITY_EXCEEDED")

    claims, meta = validate_paginated(
        api.list_claims(PROGRAM_MANAGER_HEADERS, params={"shipment_id": shipment["id"]})
    )
    assert meta["total_count"] == 1


def test_adjuster_cannot_decide_own_filed_claim(api):
    """The filer may not adjudicate; a different adjuster decides and is
    recorded.

    PRD §3.5: "A `ClaimsAdjuster` moves a claim `FILED` → `UNDER_REVIEW`, and decides it to `APPROVED` or `DENIED` — denial being reachable from either `FILED` or `UNDER_REVIEW` — but never on a claim whose `filed_by_user_id` equals the decider's own `X-User-ID` (`ERR_SEGREGATION_OF_DUTIES`)."
    PRD §3.5: "The decider's identity is recorded as `decided_by_user_id`."
    Design: Corner/validations/adjuster_cannot_decide_own_filed_claim
    """
    world = fixtures.setup_delivered_order(api, slot_overrides={"week": WEEK_NEXT})
    claim = fixtures.file_claim(
        api, world["shipment"], world["order"],
        filer_headers=make_claims_adjuster_headers("ca-9"), claimed_qty=1,
    )
    assert claim["filed_by_user_id"] == "ca-9"
    fixtures.review_claim(api, claim["id"], make_claims_adjuster_headers("ca-10"))

    own = api.transition_claim(
        claim["id"], {"to_status": "APPROVED", "resolution": "CREDIT"},
        make_claims_adjuster_headers("ca-9"),
    )
    validate_error(own, "ERR_SEGREGATION_OF_DUTIES")

    other = api.transition_claim(
        claim["id"], {"to_status": "APPROVED", "resolution": "CREDIT"},
        make_claims_adjuster_headers("ca-10"),
    )
    decided = validate_success(other, 200)
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == "ca-10"
    # base = min(1 x 9500, round(1 x 10000 x 1.20)); same-day approval -> x1.0.
    assert decided["settlement_cents"] == 9500


def test_retail_channel_direct_order_rejected(api):
    """A RETAIL account cannot order directly; retail orders exist only through
    design-job conversion.

    PRD §3.3: "Channel discipline is enforced in both directions: a `RETAIL` account may not place a direct order at all, and a dealer or builder order never carries a `design_job_id` — both are rejected with `ERR_CHANNEL_REQUIRES_DESIGN_JOB`."
    PRD §3.2: "Retail-channel orders are never placed directly; they are born from a kitchen design engagement."
    Design: Corner/validations/retail_channel_direct_order_rejected
    """
    world = fixtures.setup_active_program(api, retail=True, store_codes=["ST-1"])

    refused = api.create_order(
        factories.store_order_payload(
            world["account"]["id"], world["program"]["id"], "ST-1",
            requested_delivery_week=WEEK_PLUS_4,
        ),
        make_dealer_rep_headers(world["account"]["id"]),
    )
    validate_error(refused, "ERR_CHANNEL_REQUIRES_DESIGN_JOB")


def test_convert_with_stale_quote_after_supersede_rejected(api):
    """A quote priced against a superseded line cannot convert; revising and
    re-quoting under the new ACTIVE line restores it.

    PRD §3.2: "Converting a `QUOTED` job requires the owning designer, an `ACTIVE` account, a program in `ACTIVE` or `TRANSITIONING` (`ERR_PROGRAM_NOT_ACTIVE`), and a quote that is still fresh: `quoted_line_id` must still identify a ProgramLine in `ACTIVE` status, or the conversion fails with `ERR_QUOTE_STALE` and the job must be revised and re-quoted."
    Design: Corner/validations/convert_with_stale_quote_after_supersede_rejected
    """
    world = fixtures.setup_quoted_design_job(api, "des-1", [order_line(quantity=1)])
    job = world["job"]
    assert job["quoted_total_cents"] == 10000
    assert job["quoted_line_id"] == world["line"]["id"]

    fixtures.supersede_program_line(
        api,
        world["program"]["id"],
        line_code="L2",
        effective_start_week=WEEK_PLUS_2,
        families=[factories.family_spec(standard_price_cents=11000, base_lead_weeks=3)],
        include_disposition_qty=True,
    )

    stale = api.convert_design_job(
        job["id"], factories.design_job_convert_payload(), make_retail_designer_headers("des-1")
    )
    validate_error(stale, "ERR_QUOTE_STALE")

    fixtures.transition_design_job(
        api, job["id"], "LAYOUT_READY", "des-1", layout_lines=[order_line(quantity=1)]
    )
    fixtures.transition_design_job(api, job["id"], "QUOTED", "des-1")

    converted = api.convert_design_job(
        job["id"], factories.design_job_convert_payload(), make_retail_designer_headers("des-1")
    )
    order = validate_success(converted, 201)
    assert order["status"] == "SUBMITTED"
    assert order["quoted_total_cents"] == 11000
    assert order["design_job_id"] == job["id"]

    assert fixtures.get_design_job(api, job["id"], PROGRAM_MANAGER_HEADERS)["status"] == "CONVERTED"
