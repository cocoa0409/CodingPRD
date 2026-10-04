"""Duplicate-key, replay and gate-ordering corners on the validation surface."""

from test_helpers import (
    store_version,
    ApiErrorId,
    api_client,
    clerk_headers,
    create_batch_payload,
    create_catering_order_payload,
    get_success_data,
    manager_headers,
    open_markdown_window,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    validate_error,
    validate_success,
)


def test_a_stale_store_version_returns_precondition_failed():
    """PRD §2.10: "In all three cases, the rule is stale-version rejection. If the
    supplied expected version does not match the parent's current `version` at the
    moment the request is evaluated, the write is rejected with
    `ERR_STALE_VERSION` and HTTP status 412, and no part of the operation takes
    effect."

    Design: Corner/validations/stale_occ_version_returns_precondition_failed
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=2)
    observed = store_version(master.s)

    first = get_success_data(
        api_client.create_batch(
            create_batch_payload(
                store_id=master.s, deli_item_id=master.j4["id"], slicer_id=master.slicers[0]["id"],
                produced_by_associate_id=master.a1["id"], batch_code="B-X", planned_lbs=4,
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    second = get_success_data(
        api_client.create_batch(
            create_batch_payload(
                store_id=master.s, deli_item_id=master.j4["id"], slicer_id=master.slicers[1]["id"],
                produced_by_associate_id=master.a1["id"], batch_code="B-Y", planned_lbs=4,
            ),
            clerk_headers(master.a1["id"]),
        )
    )

    started = validate_success(
        api_client.start_batch(first["id"], store_version(master.s), clerk_headers(master.a1["id"]))
    )
    assert started["production_status"] == "IN_PRODUCTION"

    # `observed` predates the first start, which advanced the store's version.
    stale = api_client.start_batch(second["id"], observed, clerk_headers(master.a1["id"]))
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    rejected = validate_success(api_client.get_batch(second["id"], platform_admin_headers()))
    assert rejected["production_status"] == "PLANNED", "the rejected attempt left the batch untouched"

    fresh = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    accepted = validate_success(
        api_client.start_batch(second["id"], fresh["version"], clerk_headers(master.a1["id"]))
    )
    assert accepted["production_status"] == "IN_PRODUCTION"


def test_a_replayed_catering_request_id_surfaces_as_the_duplicate_error():
    """PRD §3.7: "It must be unique across the store, and a repeated `request_id`
    is treated as a replayed request rather than a new order, rejected with
    `ERR_DUPLICATE_REQUEST`."
    PRD §2.11: "The duplicate-request replay check on catering orders runs above
    the deeper state checks, so a replayed `request_id` surfaces as
    `ERR_DUPLICATE_REQUEST` and never as a state error."

    Design: Corner/validations/catering_duplicate_request_id_before_window_and_headcount_checks
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=0)

    first = get_success_data(
        api_client.create_catering_order(
            create_catering_order_payload(
                store_id=master.s, platter_deli_item_id=master.p1["id"],
                certified_planner_associate_id=master.a1["id"], request_id="REQ-DUP",
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    replay = api_client.create_catering_order(
        create_catering_order_payload(
            store_id=master.s, platter_deli_item_id=master.p1["id"],
            lead_time_hours=4, pickup_window_start="2026-09-02T07:00:00Z",
            pickup_window_end="2026-09-02T07:30:00Z",
            certified_planner_associate_id=master.a1["id"], request_id="REQ-DUP",
        ),
        clerk_headers(master.a1["id"]),
    )
    validate_error(replay, ApiErrorId.ERR_DUPLICATE_REQUEST)

    listing = api_client.list_catering_orders(
        clerk_headers(master.a1["id"]), {"store_id": master.s}
    )
    assert [row["id"] for row in listing.json()["data"]] == [first["id"]], (
        "the replay minted nothing"
    )


def test_an_unknown_store_id_is_reported_before_any_field_validation():
    """PRD §2.11: "a missing store yields `ERR_STORE_NOT_FOUND` before the child
    addressed under it is examined at all."

    Design: Corner/errors/store_not_found_error_is_triggered_by_an_unknown_store_filter
    """
    set_clock("2026-09-02T06:00:00Z")
    missing = api_client.create_associate(
        {"store_id": "00000000-0000-4000-8000-000000000000", "employee_number": "E-9001",
         "full_name": "Phantom Payroll", "primary_role": "DELI_CLERK"},
        platform_admin_headers(),
    )
    validate_error(missing, ApiErrorId.ERR_STORE_NOT_FOUND)

    master = setup_deli_master_data(slicer_count=0)
    present = validate_success(
        api_client.create_associate(
            {"store_id": master.s, "employee_number": "E-9002", "full_name": "Real Payroll",
             "primary_role": "DELI_CLERK"},
            platform_admin_headers(),
        ),
        expected_status=201,
    )
    assert present["status"] == "ACTIVE"


def test_a_waste_backlog_blocks_production_above_the_slicer_safety_checks():
    """PRD §2.11: "The unverified-waste backlog check sits below those gates but
    above the resource-level checks it accompanies; on the batch-start path it
    fires before the slicer sanitation checks."

    Design: Corner/validations/backlog_fiscal_check_precedes_slicer_safety_checks
    """
    set_clock("2026-09-02T06:00:00Z")
    # The case must stay within capacity: PRD §2.6's RESTRICTED posture rejects
    # creation before the backlog check is ever reached.
    master = setup_deli_master_data(capacity=3000, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    slicer = master.slicers[0]

    blocked = get_success_data(
        api_client.create_batch(
            create_batch_payload(
                store_id=master.s, deli_item_id=master.j3["id"], slicer_id=slicer["id"],
                produced_by_associate_id=master.a1["id"], batch_code="B-BLOCK", planned_lbs=4,
            ),
            clerk_headers(master.a1["id"]),
        )
    )

    for index in range(1, 4):
        batch = produce_batch(master.s, master.j2["id"], master.a1["id"], f"B-{index:02d}", 125,
                              produced_lbs=125, slicer_id=slicer["id"])
        open_markdown_window(batch, master.j2)
        get_success_data(api_client.mark_down_batch(batch["id"], clerk_headers(master.a1["id"])))

    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["pending_waste_verification_count"] == 3
    slicer_now = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert slicer_now["sanitation_status"] == "NEEDS_SANITATION"

    response = api_client.start_batch(blocked["id"], store["version"], clerk_headers(master.a1["id"]))
    validate_error(response, ApiErrorId.ERR_UNVERIFIED_WASTE_BACKLOG)


def test_a_batch_code_is_unique_within_its_store_rather_than_chain_wide():
    """PRD §3.1: "It is created with a `batch_code` that is unique within its
    store."

    Design: Corner/validations/same_second_duplicate_batch_code_is_a_business_constraint
    """
    set_clock("2026-09-02T06:00:00Z")
    first = setup_deli_master_data(capacity=420, store_number="101", store_name="Store One",
                                   slicer_count=0)
    second = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)

    original = validate_success(
        api_client.create_batch(
            create_batch_payload(
                store_id=first.s, deli_item_id=first.j4["id"], produced_by_associate_id=first.a1["id"],
                batch_code="B-SCOPE", planned_lbs=4,
            ),
            clerk_headers(first.a1["id"]),
        ),
        expected_status=201,
    )
    assert original["batch_code"] == "B-SCOPE"

    duplicate = api_client.create_batch(
        create_batch_payload(
            store_id=first.s, deli_item_id=first.j4["id"], produced_by_associate_id=first.a1["id"],
            batch_code="B-SCOPE", planned_lbs=4,
        ),
        clerk_headers(first.a1["id"]),
    )
    assert duplicate.status_code >= 400, "the same code is rejected inside one store"

    elsewhere = validate_success(
        api_client.create_batch(
            create_batch_payload(
                store_id=second.s, deli_item_id=second.j4["id"],
                produced_by_associate_id=second.a1["id"], batch_code="B-SCOPE", planned_lbs=4,
            ),
            clerk_headers(second.a1["id"]),
        ),
        expected_status=201,
    )
    assert elsewhere["batch_code"] == "B-SCOPE", "the scope is per store, not chain-wide"


def test_the_half_open_pickup_lockout_blocks_batch_creation():
    """PRD §3.7: "While a catering order sits past its `pickup_window_end` but
    short of `PICKED_UP`, the store is under a half-open pickup-window lockout,
    and that lockout blocks four operations: creating a sub ticket, ticketing a
    sub ticket, creating a production batch, and completing a production batch."
    PRD §3.7: "All four are refused with `ERR_HACCP_WINDOW_FREEZE`."

    Design: Corner/validations/posture_gate_chains_rank_freeze_above_sweep_actions
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=420, store_number="101", store_name="Store One",
                                    slicer_count=0)
    produce_batch(master.s, master.j1["id"], master.a1["id"], "B-A", 3, produced_lbs=3)

    missed = get_success_data(
        api_client.create_catering_order(
            create_catering_order_payload(
                store_id=master.s, platter_deli_item_id=master.p1["id"],
                customer_name="Late Party", lead_time_hours=4,
                pickup_window_start="2026-09-02T11:00:00Z",
                pickup_window_end="2026-09-02T11:45:00Z",
                certified_planner_associate_id=master.a1["id"], request_id="REQ-LATE",
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    validate_success(api_client.confirm_catering_order(missed["id"], clerk_headers(master.a1["id"])))

    set_clock("2026-09-02T12:00:00Z")
    frozen = api_client.create_batch(
        create_batch_payload(
            store_id=master.s, deli_item_id=master.j2["id"], produced_by_associate_id=master.a1["id"],
            batch_code="B-NEW", planned_lbs=3,
        ),
        clerk_headers(master.a1["id"]),
    )
    validate_error(frozen, ApiErrorId.ERR_HACCP_WINDOW_FREEZE)

    validate_success(
        api_client.cancel_catering_order(missed["id"], "unclaimed", manager_headers(master.a2["id"]))
    )
    thawed = validate_success(
        api_client.create_batch(
            create_batch_payload(
                store_id=master.s, deli_item_id=master.j2["id"],
                produced_by_associate_id=master.a1["id"], batch_code="B-THAW", planned_lbs=3,
            ),
            clerk_headers(master.a1["id"]),
        ),
        expected_status=201,
    )
    assert thawed["production_status"] == "PLANNED", "resolving the missed window lifts the freeze"


def test_a_routine_cycle_is_refused_until_the_cut_threshold_is_reached():
    """PRD §3.2: "A `ROUTINE` cycle is due when the slicer's
    `cuts_since_sanitation` is greater than or equal to its
    `sanitation_cycle_limit` — the threshold is inclusive, so a slicer sitting at
    exactly its limit is due."
    PRD §3.2: "Requesting a routine or timed cycle before it is due fails with
    `ERR_SANITATION_CYCLE_NOT_DUE`."

    120 lbs of slicing leaves the slicer at ceil(120 / 5) = 24 cuts, one below
    its default 25-cut limit, so the ROUTINE cycle is refused and nothing is
    occupied.

    Design: Corner/validations/sanitation_cycle_not_due_rejects_an_early_cycle
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=1)
    slicer = master.slicers[0]
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-120", 120, produced_lbs=120,
                  slicer_id=slicer["id"])

    before = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert before["cuts_since_sanitation"] == 24, (
        "PRD 3.1: cuts_since_sanitation increments by ceil(produced_lbs / 5)"
    )

    early = api_client.create_sanitation_cycle(
        {"store_id": master.s, "slicer_id": slicer["id"], "cycle_type": "ROUTINE",
         "cycle_minutes": 10},
        clerk_headers(master.a1["id"]),
    )
    validate_error(early, ApiErrorId.ERR_SANITATION_CYCLE_NOT_DUE)
    unchanged = validate_success(api_client.get_slicer(slicer["id"], platform_admin_headers()))
    assert unchanged["sanitation_status"] == "NEEDS_SANITATION", (
        "the rejection recorded no partial occupancy"
    )
    assert unchanged["open_sanitation_cycle_id"] is None, "no cycle row was opened"
