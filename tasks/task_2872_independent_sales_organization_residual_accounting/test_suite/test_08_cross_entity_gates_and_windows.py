"""Gates that live on a different entity than the one being operated on."""

from test_helpers import (
    ANALYST,
    CONTROLLER,
    ApiErrorId,
    add_line,
    api_client,
    book_canonical_chargebacks,
    create_residual_batch_payload,
    fetch_batch,
    fetch_program,
    fetch_statement_by_id,
    list_rows,
    make_active_merchant,
    make_agent,
    make_batch,
    make_program,
    normalize_batch,
    post_batch,
    reinstate_program,
    require_statement,
    suspend_program,
    validate_error,
    validate_success,
)


def _normalized_batch_on_a_suspended_program() -> dict:
    """A legal NORMALIZED batch whose program is switched off after ingest."""
    program = make_program()
    agent = make_agent()
    merchant = make_active_merchant(agent["id"], program["id"], mid="MID-9001")
    batch = make_batch(program["id"], file_checksum="sha256:susp-0001")
    add_line(batch["id"], merchant["id"])
    normalize_batch(batch["id"])
    suspend_program(program["id"])
    return {
        "program": program,
        "agent": agent,
        "merchant": merchant,
        "batch": batch,
    }


def test_posting_is_refused_because_another_entity_is_suspended():
    """The batch is NORMALIZED and untouched; only the program's status refuses the post.

    PRD: "the refusal applies even to batches that were ingested before the suspension"

    Design: Difficulty/cross_entity_state_dependency/batch_post_gated_by_processor_program_status
    """
    scenario = _normalized_batch_on_a_suspended_program()
    batch_id = scenario["batch"]["id"]

    validate_error(
        api_client.post_residual_batch(batch_id, CONTROLLER),
        ApiErrorId.ERR_PROGRAM_SUSPENDED.value,
        409,
    )

    after = fetch_batch(batch_id)
    assert after["state"] == "NORMALIZED", "the refused post left the batch alone"
    assert after["posted_at"] is None
    assert after["iso_retained_cents"] == 0

    _, meta = list_rows(
        api_client.list_merchant_profitability, {"residual_batch_id": batch_id}
    )
    assert meta["total_count"] == 0, "a refused post writes no profitability row"
    assert fetch_program(scenario["program"]["id"])["status"] == "SUSPENDED"


def test_reinstating_the_program_lets_the_identical_post_call_through():
    """Nothing about the batch or the request changes — only the other entity's status.

    PRD: "Moving a program from `ACTIVE` to `SUSPENDED` stops four operations dead"

    Design: Difficulty/cross_entity_state_dependency/batch_post_gated_by_processor_program_status
    """
    scenario = _normalized_batch_on_a_suspended_program()
    batch_id = scenario["batch"]["id"]

    validate_error(
        api_client.post_residual_batch(batch_id, CONTROLLER),
        ApiErrorId.ERR_PROGRAM_SUSPENDED.value,
        409,
    )

    reinstated = reinstate_program(scenario["program"]["id"])
    assert reinstated["status"] == "ACTIVE"

    validate_success(api_client.post_residual_batch(batch_id, CONTROLLER), 200)
    assert fetch_batch(batch_id)["state"] == "POSTED"

    rows, meta = list_rows(
        api_client.list_residual_allocations, {"merchant_id": scenario["merchant"]["id"]}
    )
    assert meta["total_count"] == 1
    # basis 40939 - 0 chargeback - 3900 equipment = 37039; 0.45 x 37039 = 16667.55 -> 16668
    assert rows[0]["gross_allocation_cents"] == 16668
    assert rows[0]["allocation_type"] == "DIRECT_SPLIT"
    assert fetch_program(scenario["program"]["id"])["posted_batch_count"] == 1


def _sibling_program_batch_left_normalized() -> dict:
    """A1's July statement is fully fed, but a second program's July file is still open."""
    program_one = make_program()
    program_two = make_program(
        name="Second Processor", buy_rate_bps=50, buy_rate_per_item_cents=5
    )
    agent = make_agent()
    merchant = make_active_merchant(agent["id"], program_one["id"], mid="MID-1001")
    book_canonical_chargebacks(merchant["id"], "2026-07")

    batch_one = make_batch(program_one["id"], file_checksum="sha256:aaa1")
    add_line(batch_one["id"], merchant["id"])
    normalize_batch(batch_one["id"])
    post_batch(batch_one["id"])

    batch_two = make_batch(program_two["id"], file_checksum="sha256:bbb1")
    normalize_batch(batch_two["id"])

    return {
        "agent": agent,
        "merchant": merchant,
        "batch_one": batch_one,
        "batch_two": batch_two,
        "statement": require_statement(agent["id"], "2026-07"),
    }


def test_a_line_less_batch_of_an_unrelated_program_blocks_the_issue():
    """The statement references nothing about program two, yet its July file gates the issue.

    PRD: "A single batch for that period still sitting in `RECEIVED` or `NORMALIZED`
    blocks the issue of *every* statement of that period with `ERR_BATCHES_NOT_POSTED`"

    Design: Difficulty/cross_entity_state_dependency/statement_issue_gated_by_sibling_batch_state_of_another_program
    """
    scenario = _sibling_program_batch_left_normalized()
    statement_id = scenario["statement"]["id"]

    validate_error(
        api_client.issue_agent_statement(statement_id, CONTROLLER),
        ApiErrorId.ERR_BATCHES_NOT_POSTED.value,
        409,
    )

    after = fetch_statement_by_id(statement_id)
    assert after["lifecycle_state"] == "DRAFT"
    assert after["issued_at"] is None
    assert after["minimum_true_up_cents"] == 0

    sibling = fetch_batch(scenario["batch_two"]["id"])
    assert sibling["line_count"] == 0
    assert sibling["total_normalized_net_revenue_cents"] == 0


def test_posting_the_empty_sibling_batch_unblocks_the_same_issue_call():
    """Posting a batch with no lines writes no derived rows but closes the period out.

    PRD: "The period must also be closed out on the ingestion side: every batch anywhere
    in the system whose `period_month` equals the statement's `period_month` must have a
    `state` of `POSTED` or `REVERSED`."

    Design: Difficulty/cross_entity_state_dependency/statement_issue_gated_by_sibling_batch_state_of_another_program
    """
    scenario = _sibling_program_batch_left_normalized()
    statement_id = scenario["statement"]["id"]
    sibling_id = scenario["batch_two"]["id"]

    validate_error(
        api_client.issue_agent_statement(statement_id, CONTROLLER),
        ApiErrorId.ERR_BATCHES_NOT_POSTED.value,
        409,
    )

    post_batch(sibling_id)
    sibling = fetch_batch(sibling_id)
    assert sibling["state"] == "POSTED"
    assert sibling["iso_retained_cents"] == 0
    _, profitability_meta = list_rows(
        api_client.list_merchant_profitability, {"residual_batch_id": sibling_id}
    )
    assert profitability_meta["total_count"] == 0

    issued = validate_success(
        api_client.issue_agent_statement(statement_id, CONTROLLER), 200
    )
    assert issued["lifecycle_state"] == "ISSUED"
    assert issued["gross_after_trueup_cents"] == 14643
    assert issued["net_payable_cents"] == 14643
    assert issued["issued_at"] is not None


def _ragged_july_window() -> dict:
    """One program whose July file spills to 2026-08-10 exclusive."""
    program = make_program()
    batch = make_batch(
        program["id"],
        period_month="2026-07",
        coverage_start="2026-07-01",
        coverage_end="2026-08-10",
        file_checksum="sha256:ov-0001",
    )
    return {"program": program, "batch": batch}


def test_windows_that_merely_touch_the_ragged_end_are_both_accepted():
    """2026-08-10 as a start and 2026-07-01 as an end both abut B1 without overlapping.

    PRD: "Touching intervals do not overlap — an existing window that ends on 10 August
    and a new window that starts on 10 August are both accepted, because the earlier
    window excludes its end day."

    Design: Difficulty/resource_temporal_overlap/coverage_interval_half_open_adjacency_versus_overlap
    """
    scenario = _ragged_july_window()
    program_id = scenario["program"]["id"]

    adjacent_above = validate_success(
        api_client.create_residual_batch(
            create_residual_batch_payload(
                program_id,
                period_month="2026-08",
                coverage_start="2026-08-10",
                coverage_end="2026-09-01",
                file_checksum="sha256:ov-0002",
            ),
            ANALYST,
        ),
        201,
    )
    assert adjacent_above["coverage_start"] == "2026-08-10"
    assert adjacent_above["state"] == "RECEIVED"

    adjacent_below = validate_success(
        api_client.create_residual_batch(
            create_residual_batch_payload(
                program_id,
                period_month="2026-06",
                coverage_start="2026-06-01",
                coverage_end="2026-07-01",
                file_checksum="sha256:ov-0004",
            ),
            ANALYST,
        ),
        201,
    )
    assert adjacent_below["coverage_end"] == "2026-07-01"


def test_a_window_strictly_inside_the_ragged_july_file_is_rejected():
    """[08-05, 08-09) touches neither neighbour's endpoint but lies inside B1.

    PRD: "the half-open day interval from `coverage_start` up to but excluding
    `coverage_end` may not overlap the interval of any existing batch of the same program
    whose `state` is anything other than `REVERSED`"

    Design: Difficulty/resource_temporal_overlap/coverage_interval_half_open_adjacency_versus_overlap
    """
    scenario = _ragged_july_window()
    program_id = scenario["program"]["id"]

    validate_success(
        api_client.create_residual_batch(
            create_residual_batch_payload(
                program_id,
                period_month="2026-08",
                coverage_start="2026-08-10",
                coverage_end="2026-09-01",
                file_checksum="sha256:ov-0002",
            ),
            ANALYST,
        ),
        201,
    )
    validate_error(
        api_client.create_residual_batch(
            create_residual_batch_payload(
                program_id,
                period_month="2026-08",
                coverage_start="2026-08-05",
                coverage_end="2026-08-09",
                file_checksum="sha256:ov-0003",
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_COVERAGE_OVERLAP.value,
        409,
    )
    validate_success(
        api_client.create_residual_batch(
            create_residual_batch_payload(
                program_id,
                period_month="2026-06",
                coverage_start="2026-06-01",
                coverage_end="2026-07-01",
                file_checksum="sha256:ov-0004",
            ),
            ANALYST,
        ),
        201,
    )

    _, meta = list_rows(
        api_client.list_residual_batches, {"processor_program_id": program_id}
    )
    assert meta["total_count"] == 3, "the rejected ingest created nothing"
