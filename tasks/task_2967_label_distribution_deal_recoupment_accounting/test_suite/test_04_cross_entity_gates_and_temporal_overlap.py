"""
Cross-entity state gates and the two opposite interval conventions
(PRD Sections 2.8, 3.2, 3.3, 3.5, 3.7, 3.8).

Every test here translates one instance of the difficulty index rules
`cross_entity_state_dependency` and `resource_temporal_overlap`. Each gate
instance is exercised from both sides: once with the depended-upon record in the
blocking state, asserting the identifier the gate names, and once with that one
record moved into an admissible state, proving nothing else was blocking the
call. Each interval instance exercises the exact touch and the exact adjacency,
because the rate-card window is half-open while the statement period is closed.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import (
    AGREEMENT_STATUS_ACTIVE,
    AGREEMENT_STATUS_SUPERSEDED,
    ANALYST,
    AUDIT_STATUS_NONE,
    BASIS_VARIANT_FINAL,
    DEAL_STATUS_DRAFT,
    DEAL_STATUS_EXECUTED,
    DEFAULT_DSP_CODE,
    ERR_AGREEMENT_NOT_STATEMENTABLE,
    ERR_INVALID_DEAL_STATE,
    ERR_INVALID_STATEMENT_STATE,
    ERR_RATE_CARD_OVERLAP,
    ERR_STATEMENT_PERIOD_NOT_CONTIGUOUS,
    ERR_STATEMENT_PERIOD_OVERLAP,
    FORMAT_VINYL,
    LABEL_ADMIN,
    RELEASE_STATUS_PLANNED,
    RELEASE_STATUS_RELEASED,
    RESERVE_STATUS_HELD,
    RESERVE_STATUS_PARTIALLY_LIQUIDATED,
    RUN_STATUS_SHIPPED,
    STATEMENT_STATUS_DRAFT,
    STATEMENT_STATUS_FINALIZED,
    STATEMENT_STATUS_ISSUED,
    STATEMENT_STATUS_PREPARED,
    TIER_AD_SUPPORTED,
    TIER_PREMIUM,
    assert_date,
    assert_field,
    assert_fields_money,
    assert_null,
    assert_pagination_meta,
    assert_pct_equals,
    assert_reserve_conserved,
    assert_status,
    do_execute_deal,
    do_prepare_statement,
    given_active_agreement,
    given_draft_deal,
    given_finalized_statement,
    given_issued_statement,
    given_liquidated_run,
    given_released_catalog,
    given_superseded_agreement,
    mk_rate_card,
    mk_statement,
    read_agreement,
    read_deal,
    read_release,
    read_run,
    read_statement,
    run_version,
    validate_list,
)


def test_a_release_cannot_go_to_market_under_a_draft_deal(api):
    """The release's own status is a perfectly valid PLANNED, so the only thing
    wrong is the parent: "the parent deal must be EXECUTED at that moment - a
    release cannot go to market under a draft, terminated, expired or closed
    agreement, and an attempt is rejected with ERR_INVALID_DEAL_STATE (409)".
    The 409 therefore names the deal, not the release.

    Design: Difficulty/cross_entity_state_dependency/release_promotion_requires_deal_executed
    """
    ctx = given_draft_deal(api)
    assert_status(read_deal(api, ctx["deal_id"]), DEAL_STATUS_DRAFT)

    response = api.release_to_market(
        ctx["release_id"], f.release_to_market_payload("2026-02-01"), LABEL_ADMIN
    )
    validate_error(response, ERR_INVALID_DEAL_STATE)

    unchanged = read_release(api, ctx["release_id"])
    assert_status(unchanged, RELEASE_STATUS_PLANNED)
    assert_null(unchanged, "actual_release_date")


def test_the_identical_release_call_succeeds_once_the_deal_is_executed(api):
    """Executing the deal is legal because "it must already carry at least one
    release whose status is PLANNED or RELEASED", and with the parent now
    EXECUTED the same call is the ordinary transition: "taking a release to
    market advances it PLANNED -> RELEASED and records the street date supplied
    as actual_release_date". Only the deal's state changed between the two runs.

    Design: Difficulty/cross_entity_state_dependency/release_promotion_requires_deal_executed
    """
    ctx = given_draft_deal(api)
    do_execute_deal(api, ctx["deal_id"])
    assert_status(read_deal(api, ctx["deal_id"]), DEAL_STATUS_EXECUTED)

    response = api.release_to_market(
        ctx["release_id"], f.release_to_market_payload("2026-02-01"), LABEL_ADMIN
    )
    released = validate_success(response, 200)

    assert_status(released, RELEASE_STATUS_RELEASED)
    assert_date(released["actual_release_date"], "2026-02-01", "actual_release_date")


def test_no_statement_may_be_opened_against_a_superseded_agreement(api):
    """Supersession is terminal for the predecessor and closes it to accounting:
    "opening a statement against a SUPERSEDED or TERMINATED agreement is refused
    with ERR_AGREEMENT_NOT_STATEMENTABLE (409)". The paperwork moved the money
    rather than forgiving it - the predecessor's 30,000-cent advance and
    10,000-cent recording balance (20,000 at 0.5000 recoupable) are carried onto
    the successor and its own two balances are zeroed.

    Design: Difficulty/cross_entity_state_dependency/statement_creation_requires_statementable_agreement
    """
    ctx = given_released_catalog(api)
    ctx = given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "advance_amount_cents": 30000,
            "recording_costs_cents": 20000,
            "recording_recoupable_pct": f.pct4("0.5000"),
        },
    )
    ctx = given_superseded_agreement(
        api,
        ctx,
        successor_kw={
            "advance_amount_cents": 0,
            "recording_costs_cents": 0,
            "recording_recoupable_pct": f.pct4("0.0000"),
        },
    )
    predecessor_id = ctx["predecessor"]["id"]
    predecessor = read_agreement(api, predecessor_id)
    assert_status(predecessor, AGREEMENT_STATUS_SUPERSEDED)
    assert_fields_money(
        predecessor,
        unrecouped_artist_advance_cents=0,
        unrecouped_recording_cents=0,
    )
    successor = read_agreement(api, ctx["agreement_id"])
    assert_status(successor, AGREEMENT_STATUS_ACTIVE)
    assert_fields_money(
        successor,
        unrecouped_artist_advance_cents=30000,
        unrecouped_recording_cents=10000,
    )

    response = api.create_statement(
        f.statement_payload(
            predecessor_id,
            period_start="2026-04-01",
            period_end="2026-06-30",
            basis_variant=BASIS_VARIANT_FINAL,
        ),
        ANALYST,
    )
    validate_error(response, ERR_AGREEMENT_NOT_STATEMENTABLE)

    items, _ = validate_list(api.list_statements(ANALYST))
    assert items == [], "the refused creation must not have written a statement"


def test_the_same_period_opens_freely_on_the_successor_agreement(api):
    """Moving nothing but the named agreement proves the block was a state
    dependency and not a rule about the release or the period: the successor is
    ACTIVE, one of the statuses at which "the agreement must be accountable at
    that moment", so the identical period is opened - "a new statement is DRAFT
    with audit_status at NONE and every money field zeroed".

    Design: Difficulty/cross_entity_state_dependency/statement_creation_requires_statementable_agreement
    """
    ctx = given_released_catalog(api)
    ctx = given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "advance_amount_cents": 30000,
            "recording_costs_cents": 20000,
            "recording_recoupable_pct": f.pct4("0.5000"),
        },
    )
    ctx = given_superseded_agreement(
        api,
        ctx,
        successor_kw={
            "advance_amount_cents": 0,
            "recording_costs_cents": 0,
            "recording_recoupable_pct": f.pct4("0.0000"),
        },
    )

    response = api.create_statement(
        f.statement_payload(
            ctx["agreement_id"],
            period_start="2026-04-01",
            period_end="2026-06-30",
            basis_variant=BASIS_VARIANT_FINAL,
        ),
        ANALYST,
    )
    opened = validate_success(response, 201)

    assert_status(opened, STATEMENT_STATUS_DRAFT)
    assert_status(opened, AUDIT_STATUS_NONE, "audit_status")
    assert_field(opened, "basis_variant", BASIS_VARIANT_FINAL)
    assert_field(opened, "artist_agreement_id", ctx["agreement_id"])
    assert_fields_money(
        opened,
        digital_royalty_base_cents=0,
        physical_royalty_base_cents=0,
        gross_royalty_cents=0,
        advance_applied_cents=0,
        recording_applied_cents=0,
        marketing_applied_cents=0,
        reserve_withheld_cents=0,
        net_payable_cents=0,
    )


def test_a_finalized_statement_freezes_the_runs_void_liquidation(api):
    """The dependency runs backwards, from the downstream statement to the
    upstream run: "if any statement in FINALIZED has already read this run's
    reserve_held_cents, the void is refused with ERR_INVALID_STATEMENT_STATE
    (409)". The FINAL statement read the 54,000 cents still held and withheld the
    artist's 0.1800 of it - 9,720 against a 108,000-cent gross on a 600,000-cent
    physical base, leaving 98,280 payable - so the run's own PARTIALLY_LIQUIDATED
    axis and its current version echo are both fine and only the statement bars it.

    Design: Difficulty/cross_entity_state_dependency/void_liquidation_blocked_by_finalized_statement
    """
    ctx = given_released_catalog(api, releases=[{"formats": (FORMAT_VINYL,)}])
    ctx = given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "royalty_rate_pct": f.pct4("0.1800"),
            "escalated_royalty_rate_pct": f.pct4("0.1800"),
        },
    )
    ctx = given_liquidated_run(
        api, ctx, run_kw={"returns_reserve_pct": f.pct4("0.1000")}
    )
    assert_fields_money(
        ctx["run"],
        reserve_initial_cents=90000,
        reserve_liquidated_cents=36000,
        reserve_held_cents=54000,
        physical_net_receipts_cents=600000,
    )
    assert_status(ctx["run"], RUN_STATUS_SHIPPED)
    assert_status(ctx["run"], RESERVE_STATUS_PARTIALLY_LIQUIDATED, "reserve_status")

    ctx = given_finalized_statement(
        api, ctx, finalize_clock="2026-09-01T00:00:00.000Z"
    )
    statement = read_statement(api, ctx["statement_id"])
    assert_status(statement, STATEMENT_STATUS_FINALIZED)
    assert_pct_equals(
        statement["applied_royalty_rate_pct"], "0.1800", "applied_royalty_rate_pct"
    )
    assert_fields_money(
        statement,
        physical_royalty_base_cents=600000,
        gross_royalty_cents=108000,
        reserve_withheld_cents=9720,
        net_payable_cents=98280,
    )

    version = run_version(api, ctx["run_id"])
    response = api.void_liquidation(
        ctx["run_id"], f.void_liquidation_payload(version), ANALYST
    )
    validate_error(response, ERR_INVALID_STATEMENT_STATE)

    unchanged = read_run(api, ctx["run_id"])
    assert_fields_money(
        unchanged,
        reserve_initial_cents=90000,
        reserve_liquidated_cents=36000,
        reserve_held_cents=54000,
    )
    assert_status(unchanged, RESERVE_STATUS_PARTIALLY_LIQUIDATED, "reserve_status")
    assert unchanged["version"] == version, "a refused void must not bump the run"


def test_with_no_finalized_statement_the_void_pulls_every_liquidated_cent_back(api):
    """Removing only the downstream statement lets the compensating action run:
    "reserve_liquidated_cents returns to reserve_held_cents and is set to 0, the
    axis returns to HELD, and reserve_initial_cents is unchanged". The identical
    run and the identical version echo now answer 200 with 36,000 cents back in
    the held balance and the 90,000-cent total conserved.

    Design: Difficulty/cross_entity_state_dependency/void_liquidation_blocked_by_finalized_statement
    """
    ctx = given_released_catalog(api, releases=[{"formats": (FORMAT_VINYL,)}])
    ctx = given_liquidated_run(
        api, ctx, run_kw={"returns_reserve_pct": f.pct4("0.1000")}
    )

    version = run_version(api, ctx["run_id"])
    response = api.void_liquidation(
        ctx["run_id"], f.void_liquidation_payload(version), ANALYST
    )
    voided = validate_success(response, 200)

    assert_fields_money(
        voided,
        reserve_initial_cents=90000,
        reserve_liquidated_cents=0,
        reserve_held_cents=90000,
    )
    assert_reserve_conserved(voided)
    assert_status(voided, RESERVE_STATUS_HELD, "reserve_status")
    assert_status(voided, RUN_STATUS_SHIPPED)


def test_a_statement_still_only_issued_does_not_freeze_the_void(api):
    """The guard names one status and not the whole published set: only a
    statement "in FINALIZED has already read this run's reserve_held_cents", and
    an ISSUED statement has debited nothing, since "the debits happen only at
    finalization". The same 36,000 cents therefore returns to the held balance
    while the statement stays ISSUED.

    Design: Difficulty/cross_entity_state_dependency/void_liquidation_blocked_by_finalized_statement
    """
    ctx = given_released_catalog(api, releases=[{"formats": (FORMAT_VINYL,)}])
    ctx = given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "royalty_rate_pct": f.pct4("0.1800"),
            "escalated_royalty_rate_pct": f.pct4("0.1800"),
        },
    )
    ctx = given_liquidated_run(
        api, ctx, run_kw={"returns_reserve_pct": f.pct4("0.1000")}
    )
    ctx = given_issued_statement(api, ctx)

    version = run_version(api, ctx["run_id"])
    response = api.void_liquidation(
        ctx["run_id"], f.void_liquidation_payload(version), ANALYST
    )
    voided = validate_success(response, 200)

    assert_fields_money(
        voided,
        reserve_initial_cents=90000,
        reserve_liquidated_cents=0,
        reserve_held_cents=90000,
    )
    assert_status(voided, RESERVE_STATUS_HELD, "reserve_status")
    assert_status(read_statement(api, ctx["statement_id"]), STATEMENT_STATUS_ISSUED)


def test_a_rate_card_starting_on_its_predecessors_exclusive_end_is_adjacent(api):
    """`effective_to` "is its exclusive end", so "a card whose effective_from
    falls exactly on another's effective_to is adjacent, not overlapping, and is
    accepted". A 2026-01-01..2026-04-01 card therefore admits a
    2026-04-01..2026-07-01 successor, and an open-ended card from 2026-07-01
    tiles onto that one in turn - three cards on the one triple, listed oldest
    first at 4,000, 4,200 and 4,400 micros.

    Design: Difficulty/resource_temporal_overlap/rate_card_half_open_window_overlap_rejected_adjacency_allowed
    """
    mk_rate_card(
        api,
        rate_micros_per_stream=4000,
        effective_from="2026-01-01",
        effective_to="2026-04-01",
    )

    response = api.create_rate_card(
        f.rate_card_payload(
            rate_micros_per_stream=4200,
            effective_from="2026-04-01",
            effective_to="2026-07-01",
        ),
        LABEL_ADMIN,
    )
    adjacent = validate_success(response, 201)
    assert adjacent["rate_micros_per_stream"] == 4200
    assert_date(adjacent["effective_from"], "2026-04-01", "effective_from")

    open_ended = api.create_rate_card(
        f.rate_card_payload(
            rate_micros_per_stream=4400,
            effective_from="2026-07-01",
            effective_to=None,
        ),
        LABEL_ADMIN,
    )
    tail = validate_success(open_ended, 201)
    assert_null(tail, "effective_to")

    items, meta = validate_list(
        api.list_rate_cards(
            LABEL_ADMIN,
            params={
                "dsp_code": DEFAULT_DSP_CODE,
                "territory_code": "US",
                "tier": TIER_PREMIUM,
            },
        )
    )
    assert [card["rate_micros_per_stream"] for card in items] == [4000, 4200, 4400]
    assert_pagination_meta(meta, total_count=3, has_more=False)


def test_a_rate_card_straddling_the_boundary_by_one_day_is_an_overlap(api):
    """One day the other side of the same boundary is a genuine intersection:
    "any genuine intersection of windows on the same combination of dsp_code,
    territory_code and tier is rejected with ERR_RATE_CARD_OVERLAP (409)". A
    2026-03-31..2026-05-01 window covers 2026-03-31, which the incumbent
    2026-01-01..2026-04-01 card still owns, and rate cards being immutable the
    rejected publication leaves the book at one row.

    Design: Difficulty/resource_temporal_overlap/rate_card_half_open_window_overlap_rejected_adjacency_allowed
    """
    mk_rate_card(
        api,
        rate_micros_per_stream=4000,
        effective_from="2026-01-01",
        effective_to="2026-04-01",
    )

    response = api.create_rate_card(
        f.rate_card_payload(
            rate_micros_per_stream=4300,
            effective_from="2026-03-31",
            effective_to="2026-05-01",
        ),
        LABEL_ADMIN,
    )
    validate_error(response, ERR_RATE_CARD_OVERLAP)

    items, meta = validate_list(
        api.list_rate_cards(
            LABEL_ADMIN,
            params={
                "dsp_code": DEFAULT_DSP_CODE,
                "territory_code": "US",
                "tier": TIER_PREMIUM,
            },
        )
    )
    assert [card["rate_micros_per_stream"] for card in items] == [4000]
    assert_pagination_meta(meta, total_count=1, has_more=False)


def test_an_open_ended_card_blocks_every_later_window_on_the_same_triple_only(api):
    """"A card whose effective_to is null is open-ended", so it owns everything
    from its `effective_from` onward and a second card starting 2026-08-01 is a
    genuine intersection - ERR_RATE_CARD_OVERLAP again. The very same window is
    free on the AD_SUPPORTED tier, because the exclusion is keyed on "the same
    combination of dsp_code, territory_code and tier".

    Design: Difficulty/resource_temporal_overlap/rate_card_half_open_window_overlap_rejected_adjacency_allowed
    """
    mk_rate_card(
        api,
        rate_micros_per_stream=4400,
        effective_from="2026-07-01",
        effective_to=None,
    )

    response = api.create_rate_card(
        f.rate_card_payload(
            rate_micros_per_stream=4500,
            effective_from="2026-08-01",
            effective_to=None,
        ),
        LABEL_ADMIN,
    )
    validate_error(response, ERR_RATE_CARD_OVERLAP)

    other_tier = api.create_rate_card(
        f.rate_card_payload(
            tier=TIER_AD_SUPPORTED,
            rate_micros_per_stream=1200,
            effective_from="2026-07-01",
            effective_to=None,
        ),
        LABEL_ADMIN,
    )
    admitted = validate_success(other_tier, 201)
    assert_field(admitted, "tier", TIER_AD_SUPPORTED)
    assert admitted["rate_micros_per_stream"] == 1200


def test_a_final_period_beginning_the_day_after_the_last_one_is_prepared(api):
    """The statement period is closed and inclusive, so the tiling rule reads off
    the calendar day: a FINAL period "must begin on the day immediately after the
    latest such period ends". With 2026-01-01..2026-03-31 already prepared, a
    period opening 2026-04-01 is exactly that day and is accepted, which is how
    "FINAL statements therefore tile the agreement's history with no gaps and no
    double counting".

    Design: Difficulty/resource_temporal_overlap/final_statement_closed_period_overlap_and_contiguity
    """
    ctx = given_released_catalog(api)
    ctx = given_active_agreement(api, ctx)
    first = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-01-01",
        period_end="2026-03-31",
        basis_variant=BASIS_VARIANT_FINAL,
    )
    do_prepare_statement(api, first["id"])
    second = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-04-01",
        period_end="2026-06-30",
        basis_variant=BASIS_VARIANT_FINAL,
    )

    response = api.prepare_statement(second["id"], ANALYST)
    prepared = validate_success(response, 200)

    assert_status(prepared, STATEMENT_STATUS_PREPARED)
    assert_date(prepared["period_start"], "2026-04-01", "period_start")
    assert_status(read_statement(api, first["id"]), STATEMENT_STATUS_PREPARED)


def test_a_final_period_touching_an_existing_one_by_a_single_day_is_an_overlap(api):
    """Unlike the half-open rate-card window, a statement period owns both of its
    endpoints: a FINAL period "may not intersect one of their periods, not even
    by a single day, which is ERR_STATEMENT_PERIOD_OVERLAP (409)". Starting on
    2026-03-31 - the last day of the first prepared period - is that single-day
    intersection, and the refused statement stays DRAFT with nothing computed.

    Design: Difficulty/resource_temporal_overlap/final_statement_closed_period_overlap_and_contiguity
    """
    ctx = given_released_catalog(api)
    ctx = given_active_agreement(api, ctx)
    first = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-01-01",
        period_end="2026-03-31",
        basis_variant=BASIS_VARIANT_FINAL,
    )
    do_prepare_statement(api, first["id"])
    second = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-04-01",
        period_end="2026-06-30",
        basis_variant=BASIS_VARIANT_FINAL,
    )
    do_prepare_statement(api, second["id"])
    touching = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-03-31",
        period_end="2026-06-30",
        basis_variant=BASIS_VARIANT_FINAL,
    )

    response = api.prepare_statement(touching["id"], ANALYST)
    validate_error(response, ERR_STATEMENT_PERIOD_OVERLAP)

    unchanged = read_statement(api, touching["id"])
    assert_status(unchanged, STATEMENT_STATUS_DRAFT)
    assert_fields_money(unchanged, gross_royalty_cents=0, net_payable_cents=0)


def test_a_final_period_leaving_a_one_day_gap_is_not_contiguous(api):
    """A gap overlaps nothing, so it is caught by the other half of the rule and
    with a different status: the period "must begin on the day immediately after
    the latest such period ends, which is ERR_STATEMENT_PERIOD_NOT_CONTIGUOUS
    (422)". After periods ending 2026-06-30, a start of 2026-07-02 leaves
    2026-07-01 unaccounted, and 422 rather than the overlap rule's 409 is what
    distinguishes the two failures.

    Design: Difficulty/resource_temporal_overlap/final_statement_closed_period_overlap_and_contiguity
    """
    ctx = given_released_catalog(api)
    ctx = given_active_agreement(api, ctx)
    first = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-01-01",
        period_end="2026-03-31",
        basis_variant=BASIS_VARIANT_FINAL,
    )
    do_prepare_statement(api, first["id"])
    second = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-04-01",
        period_end="2026-06-30",
        basis_variant=BASIS_VARIANT_FINAL,
    )
    do_prepare_statement(api, second["id"])
    gapped = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-07-02",
        period_end="2026-09-30",
        basis_variant=BASIS_VARIANT_FINAL,
    )

    response = api.prepare_statement(gapped["id"], ANALYST)
    validate_error(response, ERR_STATEMENT_PERIOD_NOT_CONTIGUOUS)

    unchanged = read_statement(api, gapped["id"])
    assert_status(unchanged, STATEMENT_STATUS_DRAFT)
    assert_fields_money(unchanged, gross_royalty_cents=0, net_payable_cents=0)


def test_the_same_gapped_period_is_prepared_once_it_starts_the_next_day(api):
    """The rule is contiguity, not a ban on a third period: shifting the very
    same 2026-09-30 end back to a 2026-07-01 start makes it "begin on the day
    immediately after the latest such period ends" and the statement prepares,
    which is what keeps the two rejections about the calendar rather than about
    the number of FINAL statements an agreement may carry.

    Design: Difficulty/resource_temporal_overlap/final_statement_closed_period_overlap_and_contiguity
    """
    ctx = given_released_catalog(api)
    ctx = given_active_agreement(api, ctx)
    first = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-01-01",
        period_end="2026-03-31",
        basis_variant=BASIS_VARIANT_FINAL,
    )
    do_prepare_statement(api, first["id"])
    second = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-04-01",
        period_end="2026-06-30",
        basis_variant=BASIS_VARIANT_FINAL,
    )
    do_prepare_statement(api, second["id"])
    third = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-07-01",
        period_end="2026-09-30",
        basis_variant=BASIS_VARIANT_FINAL,
    )

    response = api.prepare_statement(third["id"], ANALYST)
    prepared = validate_success(response, 200)

    assert_status(prepared, STATEMENT_STATUS_PREPARED)
    assert_date(prepared["period_start"], "2026-07-01", "period_start")
    assert_date(prepared["period_end"], "2026-09-30", "period_end")
