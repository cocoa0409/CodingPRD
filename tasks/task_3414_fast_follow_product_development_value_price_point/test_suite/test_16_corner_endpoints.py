"""Endpoint-behavior corners: the fixed error envelope, pagination defaults
interacting with filters, the three temporal gates on slot creation, the
launch-window gate at execution, successor validation on discontinuation,
the sampling cap boundary, DISTRIBUTE's two gates, and atomic capacity
rejection when only ACTIVE slots overflow.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    PRODUCT_MANAGER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    create_discontinuation_review_payload,
    create_line_review,
    create_partner,
    create_planogram_slot_payload,
    create_product,
    create_sample_distribution_payload,
    create_selected_concept,
    create_selected_trend,
    open_line_review,
    propose_discontinuation,
    read_launch_plan,
    read_line_review,
    read_partner,
    read_planogram_slot,
    read_product,
    record_sample_event,
    set_clock,
    set_sampling_status,
    setup_approved_plan,
    setup_executed_plan,
    setup_executed_plan_with_sampling,
    setup_launch_ready_product,
    validate_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_PM = TEST_USERS["product_manager_headers"]
_PLANNER = TEST_USERS["retail_planner_headers"]
_MARKETING = TEST_USERS["marketing_lead_headers"]


def test_error_responses_carry_the_fixed_envelope_shape(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format:" with `response_type` of "error" and a `data`
    object carrying `error_id` and `message`; "- The `meta` object for error
    responses contains only `api_request_id` and `api_request_timestamp`."
    Demonstrated on a 404 concept read.

    Design: Corner/endpoints/error_responses_carry_the_fixed_envelope_shape
    """
    set_clock()

    response = api.get_concept(NON_EXISTENT_UUID, headers=_ADMIN)

    error = validate_error(response, ApiErrorId.ERR_CONCEPT_NOT_FOUND.value)
    assert isinstance(error["message"], str) and error["message"]
    body = response.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_products_list_applies_pagination_defaults_and_status_filter(api):
    """PRD §2.3: "List endpoints accept two query parameters: `limit`, the
    page size, defaulting to 10 with a minimum of 1 and a maximum of 100; and
    `offset`, the number of records to skip, defaulting to 0. Every list
    response reports `limit`, `offset`, `total_count`, and `has_more` in its
    `meta` object."
    PRD §3.3: "Products can be listed filtered by `concept_id`,
    `successor_product_id`, `status`, or `tooling_code`..."
    One FORMULATION product: defaults report limit 10 / offset 0 / total 1;
    status=LAUNCHED filters to empty; status=FORMULATION and the concept FK
    filter each return the product.

    Design: Corner/endpoints/products_list_applies_pagination_defaults_and_status_filter
    """
    set_clock()
    trend = create_selected_trend()
    concept = create_selected_concept(trend["id"])
    product = create_product(concept["id"])

    rows, meta = validate_paginated(api.list_products(headers=_ADMIN))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_products(headers=_ADMIN, params={"status": "LAUNCHED"})
    )
    assert rows == []
    assert meta["total_count"] == 0

    rows, meta = validate_paginated(
        api.list_products(headers=_ADMIN, params={"status": "FORMULATION"})
    )
    assert [row["id"] for row in rows] == [product["id"]]

    rows, meta = validate_paginated(
        api.list_products(headers=_ADMIN, params={"concept_id": concept["id"]})
    )
    assert meta["total_count"] == 1


def test_slot_creation_temporal_gates(api):
    """PRD §3.7: "The review must be in `SUBMISSION_OPEN` — a state
    precondition reported as `ERR_INVALID_STATE` — and the logical clock must
    be inside the submission window, else `ERR_SUBMISSION_WINDOW_CLOSED`."
    PRD §3.7: "the planner opens submissions, moving it to `SUBMISSION_OPEN`,
    only when the logical clock reads at or after `submission_window_start`
    and strictly before `submission_window_end`, else
    `ERR_SUBMISSION_WINDOW_CLOSED`."
    Before the window the SCHEDULED review rejects creation (409); opening
    early is 422; and once the window has passed, even a SUBMISSION_OPEN
    review rejects creation (422).

    Design: Corner/endpoints/slot_creation_temporal_gates
    """
    ctx = setup_launch_ready_product()
    ctx["partner"] = create_partner()
    ctx["line_review"] = create_line_review(ctx["partner"]["id"])
    review_id = ctx["line_review"]["id"]

    early_create = api.create_planogram_slot(
        create_planogram_slot_payload(
            line_review_id=review_id,
            product_id=ctx["product"]["id"],
            facings=4,
            expected_line_review_version=ctx["line_review"]["version"],
        ),
        _PLANNER,
    )
    validate_error(early_create, ApiErrorId.ERR_INVALID_STATE.value)

    early_open = api.patch_line_review(review_id, {"status": "SUBMISSION_OPEN"}, _PLANNER)
    validate_error(early_open, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED.value)

    open_line_review(review_id)
    set_clock("2026-10-16T00:00:00Z")
    late_create = api.create_planogram_slot(
        create_planogram_slot_payload(
            line_review_id=review_id,
            product_id=ctx["product"]["id"],
            facings=4,
            expected_line_review_version=read_line_review(review_id)["version"],
        ),
        _PLANNER,
    )
    validate_error(late_create, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED.value)

    rows, meta = validate_paginated(
        api.list_planogram_slots(headers=_PLANNER, params={"line_review_id": review_id})
    )
    assert meta["total_count"] == 0


def test_launch_execute_before_occupancy_start_rejected(api):
    """PRD §3.8: "Execution — `APPROVED` to `EXECUTED` — waits for the shelf:
    the logical clock must have reached the slot's `occupancy_start`, else
    `ERR_LAUNCH_WINDOW_NOT_OPEN`."
    At 2026-10-21 with occupancy starting 2026-11-01, execution is a 422 and
    no cascade fires.

    Design: Corner/endpoints/launch_execute_before_occupancy_start_rejected
    """
    ctx = setup_approved_plan()

    response = api.patch_launch_plan(ctx["plan"]["id"], {"status": "EXECUTED"}, _PM)

    validate_error(response, ApiErrorId.ERR_LAUNCH_WINDOW_NOT_OPEN.value)
    assert read_launch_plan(ctx["plan"]["id"])["status"] == "APPROVED"
    assert read_product(ctx["product"]["id"])["status"] == "LAUNCH_READY"
    assert read_planogram_slot(ctx["slot"]["id"])["status"] == "COMMITTED"


def test_discontinuation_successor_validation(api):
    """PRD §3.9: "The retired product must be `LAUNCHED` — a state
    precondition reported as `ERR_INVALID_STATE` — and the successor, when
    present, must be a `LAUNCH_READY` product different from the retired one,
    else `ERR_SUCCESSOR_INVALID`. The proposal records the proposer's
    `X-User-ID` as `proposed_by_user_id`, and the review starts `PROPOSED`."
    A FORMULATION successor: 422. The product as its own successor: 422. No
    successor: 201, PROPOSED, proposer recorded.

    Design: Corner/endpoints/discontinuation_successor_validation
    """
    ctx = setup_executed_plan()
    concept_b = create_selected_concept(ctx["trend"]["id"], name="Second Skin")
    product_b = create_product(concept_b["id"])

    validate_error(
        api.create_discontinuation_review(
            create_discontinuation_review_payload(
                product_id=ctx["product"]["id"],
                reason="REFRESH_CADENCE",
                successor_product_id=product_b["id"],
            ),
            _PM,
        ),
        ApiErrorId.ERR_SUCCESSOR_INVALID.value,
    )
    validate_error(
        api.create_discontinuation_review(
            create_discontinuation_review_payload(
                product_id=ctx["product"]["id"],
                reason="REFRESH_CADENCE",
                successor_product_id=ctx["product"]["id"],
            ),
            _PM,
        ),
        ApiErrorId.ERR_SUCCESSOR_INVALID.value,
    )

    review = propose_discontinuation(ctx["product"]["id"], reason="TREND_DECAY")
    assert review["status"] == "PROPOSED"
    assert review["proposed_by_user_id"] == PRODUCT_MANAGER_USER_ID


def test_sample_commit_at_and_over_cap_boundary(api):
    """PRD §3.8: "A `COMMIT` event reserves units for sampling: the running
    total of `samples_committed` plus `samples_distributed` plus the new units
    must stay within the sampling cap — the floor of ten percent of
    `qty_locked_units` — else the event is rejected with
    `ERR_SAMPLE_OVERDRAW`; the units must also fit within
    `retail_units_available`; a committed event adds its units to
    `samples_committed`."
    Locked at 800, the cap is exactly 80: COMMIT 80 succeeds, a further
    COMMIT 1 is 422.

    Design: Corner/endpoints/sample_commit_at_and_over_cap_boundary
    """
    ctx = setup_executed_plan_with_sampling()
    plan_id = ctx["plan"]["id"]

    committed = record_sample_event(plan_id, "COMMIT", 80, channel="COMMUNITY")
    assert committed["samples_committed"] == 80

    response = api.create_sample_distribution(
        plan_id, create_sample_distribution_payload("COMMIT", 1, channel="COMMUNITY"),
        _MARKETING,
    )

    validate_error(response, ApiErrorId.ERR_SAMPLE_OVERDRAW.value)
    after = read_launch_plan(plan_id)
    assert after["samples_committed"] == 80
    assert after["retail_units_available"] == 720


def test_distribute_gates_on_sampling_status_and_committed_units(api):
    """PRD §3.8: "A `DISTRIBUTE` event fulfills committed units: the count
    must not exceed `samples_committed`, the program must be `ACTIVE`, and the
    event charges the sampling budget by adding the units times
    `landed_locked_cents` to `sample_spend_cents`, which must never exceed
    `sample_budget_cents`, else `ERR_SAMPLE_OVERDRAW`; the units move from
    `samples_committed` to `samples_distributed`."
    While PLANNED any distribution is 409; once ACTIVE, 10 against a
    committed pool of 5 is 422, and distributing exactly the pool succeeds at
    5 * 237 == 1185 cents of spend.

    Design: Corner/endpoints/distribute_gates_on_sampling_status_and_committed_units
    """
    ctx = setup_executed_plan()
    plan_id = ctx["plan"]["id"]
    set_sampling_status(plan_id, "PLANNED")

    response = api.create_sample_distribution(
        plan_id, create_sample_distribution_payload("DISTRIBUTE", 1, channel="CREATOR"),
        _MARKETING,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    set_sampling_status(plan_id, "ACTIVE")
    record_sample_event(plan_id, "COMMIT", 5, channel="CREATOR")

    response = api.create_sample_distribution(
        plan_id, create_sample_distribution_payload("DISTRIBUTE", 10, channel="CREATOR"),
        _MARKETING,
    )
    validate_error(response, ApiErrorId.ERR_SAMPLE_OVERDRAW.value)

    done = record_sample_event(plan_id, "DISTRIBUTE", 5, channel="CREATOR")
    assert done["samples_distributed"] == 5
    assert done["sample_spend_cents"] == 1185


def test_capacity_shrink_blocked_by_active_slot_is_atomic(api):
    """PRD §3.7: "If `ACTIVE` slots alone still exceed the new capacity after
    every `COMMITTED` slot has been evicted, the whole capacity revision is
    rejected with `ERR_CAPACITY_EXCEEDED` and nothing is evicted — the
    reduction is atomic."
    The only EYES slot is ACTIVE at 10 of 10; shrinking EYES to 5 cannot
    evict anything, so the PATCH is rejected and capacities, slot, and plan
    are unchanged.

    Design: Corner/endpoints/capacity_shrink_blocked_by_active_slot_is_atomic
    """
    ctx = setup_executed_plan()

    response = api.patch_retail_partner(
        ctx["partner"]["id"],
        {"category_capacities": {"EYES": 5, "LIPS": 8}},
        _PLANNER,
    )

    validate_error(response, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)
    partner = read_partner(ctx["partner"]["id"])
    assert partner["category_capacities"]["EYES"] == 10
    assert read_planogram_slot(ctx["slot"]["id"])["status"] == "ACTIVE"
    assert read_launch_plan(ctx["plan"]["id"])["status"] == "EXECUTED"
