"""Error catalog triggers, endpoint listing surfaces, and immediate
consistency of mutation responses."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_contract,
    create_pool,
    create_practice_in,
    create_statement,
    draft_agreement,
    enter_allocation,
    finalize_statement,
    get_success_data,
    make_market_committee_chair_headers,
    make_practice_executive_headers,
    onboard_practice,
    post_batch,
    settle_batch,
    setup_affiliated,
    setup_group_market,
    setup_practice_onboarding,
    setup_wave_in_cutover,
    validate_error,
    validate_paginated,
    validate_success,
)

GA = TEST_USERS["group_admin_headers"]
PCO = TEST_USERS["payer_officer_headers"]
GFC = TEST_USERS["group_financial_controller_headers"]


def test_error_duplicate_batch_triggered(api):
    """PRD §3.6: "Only one batch may exist per practice, contract, and
    period combination; a duplicate is rejected with `ERR_DUPLICATE_BATCH`."

    Design: Corner/errors/error_duplicate_batch_triggered
    """
    ctx = setup_affiliated()
    post_batch(ctx["practice"], ctx["contract"], period="2026-09", posted_amount_cents=100000)

    resp = api.create_collection_batch(
        {
            "practice_id": ctx["practice"]["id"],
            "payer_contract_id": ctx["contract"]["id"],
            "period": "2026-09",
            "posted_amount_cents": 200000,
        },
        TEST_USERS["distribution_accountant_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BATCH, expected_status=409)

    rows, meta = validate_paginated(api.list_collection_batches(GA))
    assert len(rows) == 1


def test_error_no_eligible_allocations_triggered(api):
    """PRD §3.7: "Allocation moves a `SCORING` pool to `ALLOCATED` — a pool
    in any other state fails with `ERR_POOL_NOT_SCORING` — and requires at
    least one `ENTERED` allocation whose `quality_score` is at least the
    pool's `quality_threshold`, else `ERR_NO_ELIGIBLE_ALLOCATIONS`."

    Design: Corner/errors/error_no_eligible_allocations_triggered
    """
    ctx = setup_affiliated()
    pool = create_pool(ctx["contract"], period="2026-09", pool_amount_cents=1000000)
    alloc = enter_allocation(pool, ctx["practice"], quality_score=59.9, attributed_lives=1000)
    validate_success(api.close_entries_incentive_pool(pool["id"], GFC))

    resp = api.allocate_incentive_pool(pool["id"], GFC)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ALLOCATIONS, expected_status=422)

    pool_after = validate_success(api.get_incentive_pool(pool["id"], GA))
    assert pool_after["status"] == "SCORING"

    alloc_after = validate_success(api.get_incentive_allocation(alloc["id"], GA))
    assert alloc_after["status"] == "ENTERED"


def test_error_group_not_operating_triggered(api):
    """PRD §3.1: "Payer-contract negotiation requires an `OPERATING` group
    — opening a contract while the group is still `FORMING` is rejected with
    `ERR_GROUP_NOT_OPERATING`."

    Design: Corner/errors/error_group_not_operating_triggered
    """
    from test_helpers import create_group, set_clock

    set_clock()
    group = create_group(active=False)
    resp = api.create_payer_contract(
        {
            "medical_group_id": group["id"],
            "payer_name": "Lone Star Health Plan",
            "contract_type": "HYBRID",
            "effective_date": "2026-09-01",
        },
        PCO,
    )
    validate_error(resp, ApiErrorId.ERR_GROUP_NOT_OPERATING, expected_status=409)

    rows, meta = validate_paginated(api.list_payer_contracts(GA))
    assert len(rows) == 0


def test_error_no_wave_in_cutover_blocks_agreement_execute(api):
    """PRD §3.2: "If no wave in the practice's market is currently
    `IN_CUTOVER`, the execution fails with `ERR_NO_WAVE_IN_CUTOVER` and the
    practice remains `PROSPECT`."

    Design: Corner/errors/error_no_wave_in_cutover_blocks_agreement_execute
    """
    from test_helpers import create_wave_for

    ctx = setup_group_market()
    # Wave exists but stays PLANNED (never locked / started).
    create_wave_for(ctx["market"])
    practice = create_practice_in(ctx["group"], ctx["market"])
    agreement = draft_agreement(practice)

    resp = api.execute_affiliation_agreement(
        agreement["id"], make_practice_executive_headers(practice["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NO_WAVE_IN_CUTOVER, expected_status=409)

    agreement_after = validate_success(api.get_affiliation_agreement(agreement["id"], GA))
    assert agreement_after["status"] == "DRAFT"

    practice_after = validate_success(api.get_practice(practice["id"], GA))
    assert practice_after["status"] == "PROSPECT"


def test_error_no_eligible_voters_blocks_vote_creation(api):
    """PRD §3.5: "A vote that would snapshot zero eligible voters is
    rejected with `ERR_NO_ELIGIBLE_VOTERS`."

    Design: Corner/errors/error_no_eligible_voters_blocks_vote_creation
    """
    ctx = setup_group_market()
    contract = create_contract(ctx["group"])

    resp = api.create_committee_vote(
        {
            "market_id": ctx["market"]["id"],
            "motion_type": "PAYER_CONTRACT_RATIFICATION",
            "subject_contract_id": contract["id"],
        },
        make_market_committee_chair_headers("00000000-0000-4000-8000-0000000000aa"),
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_VOTERS, expected_status=422)

    rows, meta = validate_paginated(api.list_committee_votes(GA))
    assert len(rows) == 0


def test_finalize_effects_visible_in_same_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify
    a resource will return the created or updated resource object in the data
    field."
    PRD §3.6: "The final variant then computes `gross_collections_cents` as
    the sum of `net_settled_cents` over `SETTLED` and `ADJUSTED` batches only
    — `POSTED` batches never enter the final basis —"

    Design: Corner/consistency_model/finalize_effects_visible_in_same_response
    """
    ctx = setup_affiliated()
    batch = post_batch(ctx["practice"], ctx["contract"], period="2026-09", posted_amount_cents=30000000)
    settle_batch(batch, 0)
    statement = create_statement(ctx["practice"], period="2026-09")

    final = validate_success(api.finalize_distribution_statement(statement["id"], GFC))
    assert final["status"] == "FINAL_ISSUED"
    assert final["gross_collections_cents"] == 30000000
    assert final["shared_services_fee_cents"] == 2100000
    assert final["net_distribution_cents"] == 27900000
    assert final["payout_cents"] == 27900000
    assert final["carried_forward_out_cents"] == 0

    # A subsequent read returns identical values — no drift, no recompute lag.
    reread = validate_success(api.get_distribution_statement(statement["id"], GA))
    assert reread["status"] == "FINAL_ISSUED"
    assert reread["gross_collections_cents"] == final["gross_collections_cents"]
    assert reread["shared_services_fee_cents"] == final["shared_services_fee_cents"]
    assert reread["net_distribution_cents"] == final["net_distribution_cents"]
    assert reread["payout_cents"] == final["payout_cents"]
    assert reread["carried_forward_out_cents"] == final["carried_forward_out_cents"]
