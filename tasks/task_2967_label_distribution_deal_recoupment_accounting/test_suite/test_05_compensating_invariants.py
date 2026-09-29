"""
The three compensating actions and the conserved identities they must restore:
disputing an accepted report, voiding a reserve liquidation and concluding a
material audit (PRD Sections 2.9, 3.6, 3.7, 3.9).

Every test here translates one instance of the difficulty index rule
`compensating_invariant`. Each asserts the conserved identity before the forward
action, after it, and after the compensating action that undoes it.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import (
    ANALYST,
    AUDIT_COST_BEARER_LABEL,
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_NONE,
    AUDIT_STATUS_REQUESTED,
    BASIS_VARIANT_FINAL,
    BIZ_AFFAIRS,
    FORMAT_DIGITAL,
    FORMAT_VINYL,
    RECOUPMENT_STATUS_RECOUPED,
    RECOUPMENT_STATUS_UNRECOUPED,
    REPORT_STATUS_DISPUTED,
    RESERVE_STATUS_HELD,
    RESERVE_STATUS_LIQUIDATED,
    RESERVE_STATUS_PARTIALLY_LIQUIDATED,
    RUN_STATUS_RECONCILED,
    RUN_STATUS_SHIPPED,
    SPEND_CATEGORY_DIGITAL_ADS,
    STATEMENT_STATUS_FINALIZED,
    STATEMENT_STATUS_REVISED,
    TIER_PREMIUM,
    assert_advance_conserved,
    assert_field,
    assert_field_money,
    assert_fields_money,
    assert_instant_equals,
    assert_null,
    assert_pct_equals,
    assert_reserve_conserved,
    assert_status,
    assert_version_bumped,
    deal_version,
    do_finalize_statement,
    do_request_audit,
    do_set_clock,
    find_by_id,
    given_active_agreement,
    given_issued_statement,
    given_released_catalog,
    given_settled_spend,
    given_shipped_run,
    given_submitted_report,
    read_agreement,
    read_artist,
    read_deal,
    read_release,
    read_report,
    read_report_lines,
    read_run,
    read_statement,
    run_version,
)


def _submitted_report_over_a_fifty_thousand_cent_advance(api):
    """An EXECUTED cross-collateralized deal carrying a 50,000-cent advance, one
    DIGITAL release holding the whole share, an ACTIVE agreement at 0.1200 base
    and 0.1800 escalated, and one SUBMITTED report worth 100,000 cents gross."""
    ctx = given_released_catalog(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "cross_collateralized": True,
            "advance_amount_cents": 50000,
            "marketing_budget_cents": 500000,
            "objection_window_days": 30,
            "post_term_collection_days": 90,
        },
        releases=[
            {
                "title": "Reversible",
                "formats": (FORMAT_DIGITAL,),
                "advance_share_cents": 50000,
            }
        ],
    )
    ctx = given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "royalty_rate_pct": f.pct4("0.1200"),
            "escalated_royalty_rate_pct": f.pct4("0.1800"),
            "advance_amount_cents": 0,
            "recording_costs_cents": 0,
            "recording_recoupable_pct": f.pct4("0.0000"),
            "marketing_recoup_share_pct": f.pct4("0.5000"),
        },
    )
    return given_submitted_report(
        api,
        ctx,
        lines=[{"territory_code": "US", "tier": TIER_PREMIUM, "stream_count": 250000}],
    )


def test_disputing_an_accepted_report_restores_the_advance_identity_exactly(api):
    """The dispute is the exact inverse of the acceptance on the deal's advance
    ledger: "advance_amount_cents is advance_recouped_cents plus
    unrecouped_advance_cents, with no drift, after every acceptance and after
    every dispute". A 100,000-cent gross less the 15% fee gives an 85,000-cent
    pool, so acceptance moves 50,000 == 50,000 + 0 with 35,000 post-recoupment
    excess, and the dispute lands back on 50,000 == 0 + 50,000.

    Design: Difficulty/compensating_invariant/dispute_reverses_accept_with_zero_advance_drift
    """
    ctx = _submitted_report_over_a_fifty_thousand_cent_advance(api)

    before = read_deal(api, ctx["deal_id"])
    assert_advance_conserved(before)
    assert_fields_money(
        before,
        advance_amount_cents=50000,
        advance_recouped_cents=0,
        unrecouped_advance_cents=50000,
        net_receipts_to_date_cents=0,
        post_recoupment_net_receipts_cents=0,
    )
    assert_field(before, "recoupment_status", RECOUPMENT_STATUS_UNRECOUPED)

    accepted = validate_success(
        api.accept_report(
            ctx["report_id"], f.accept_report_payload(before["version"]), ANALYST
        ),
        200,
    )
    assert_field_money(accepted, "advance_applied_cents", 50000)

    after_accept = read_deal(api, ctx["deal_id"])
    assert_advance_conserved(after_accept)
    assert_fields_money(
        after_accept,
        advance_amount_cents=50000,
        advance_recouped_cents=50000,
        unrecouped_advance_cents=0,
        net_receipts_to_date_cents=85000,
        post_recoupment_net_receipts_cents=35000,
    )
    assert_field(after_accept, "recoupment_status", RECOUPMENT_STATUS_RECOUPED)

    disputed = validate_success(
        api.dispute_report(
            ctx["report_id"],
            f.dispute_report_payload(
                after_accept["version"],
                "Territory misallocation on the US premium tier",
            ),
            ANALYST,
        ),
        200,
    )
    assert_status(disputed, REPORT_STATUS_DISPUTED)

    after_dispute = read_deal(api, ctx["deal_id"])
    assert_advance_conserved(after_dispute)
    assert_fields_money(
        after_dispute,
        advance_amount_cents=50000,
        advance_recouped_cents=0,
        unrecouped_advance_cents=50000,
        net_receipts_to_date_cents=0,
        post_recoupment_net_receipts_cents=0,
    )
    assert_field(after_dispute, "recoupment_status", RECOUPMENT_STATUS_UNRECOUPED)


def test_disputing_an_accepted_report_walks_back_release_report_and_rate(api):
    """The compensation's first hop "clears net_receipts_cents back to null on
    every line of the report", the second and third subtract the release's own
    figures back out, and the fourth reverts every affected agreement's
    active_royalty_rate_pct to its royalty_rate_pct. The release returns to
    0/0/50,000, the report keeps its 100,000-cent gross while
    advance_applied_cents returns to 0, and the rate walks 0.1200 → 0.1800 →
    0.1200.

    Design: Difficulty/compensating_invariant/dispute_reverses_accept_with_zero_advance_drift
    """
    ctx = _submitted_report_over_a_fifty_thousand_cent_advance(api)
    line_id = ctx["lines"][0]["id"]

    release_before = read_release(api, ctx["release_id"])
    # PRD 3.2: "A new release has ... four derived counters at 0"; the
    # unrecouped share is only recomputed as "advance_share_cents less
    # release_advance_recouped_cents" by the acceptance settle of PRD 3.6,
    # which has not run yet.
    assert_fields_money(
        release_before,
        net_receipts_to_date_cents=0,
        release_advance_recouped_cents=0,
        unrecouped_advance_share_cents=0,
    )
    agreement_before = read_agreement(api, ctx["agreement_id"])
    assert_pct_equals(
        agreement_before["active_royalty_rate_pct"],
        f.pct4("0.1200"),
        "active_royalty_rate_pct",
    )

    validate_success(
        api.accept_report(
            ctx["report_id"],
            f.accept_report_payload(deal_version(api, ctx["deal_id"])),
            ANALYST,
        ),
        200,
    )

    release_accepted = read_release(api, ctx["release_id"])
    assert_fields_money(
        release_accepted,
        net_receipts_to_date_cents=85000,
        release_advance_recouped_cents=50000,
        unrecouped_advance_share_cents=0,
    )
    assert_pct_equals(
        read_agreement(api, ctx["agreement_id"])["active_royalty_rate_pct"],
        f.pct4("0.1800"),
        "active_royalty_rate_pct",
    )
    line_accepted = find_by_id(read_report_lines(api, ctx["report_id"]), line_id)
    assert_field_money(line_accepted, "net_receipts_cents", 85000)

    validate_success(
        api.dispute_report(
            ctx["report_id"],
            f.dispute_report_payload(
                deal_version(api, ctx["deal_id"]),
                "Territory misallocation on the US premium tier",
            ),
            ANALYST,
        ),
        200,
    )

    release_after = read_release(api, ctx["release_id"])
    assert_fields_money(
        release_after,
        net_receipts_to_date_cents=0,
        release_advance_recouped_cents=0,
        unrecouped_advance_share_cents=50000,
    )
    report_after = read_report(api, ctx["report_id"])
    assert_fields_money(
        report_after, advance_applied_cents=0, gross_receipts_cents=100000
    )
    line_after = find_by_id(read_report_lines(api, ctx["report_id"]), line_id)
    assert_null(line_after, "net_receipts_cents")
    assert_field(line_after, "applied_rate_micros_per_stream", 4000)
    assert_pct_equals(
        read_agreement(api, ctx["agreement_id"])["active_royalty_rate_pct"],
        f.pct4("0.1200"),
        "active_royalty_rate_pct",
    )


def _shipped_run_holding_a_ninety_thousand_cent_reserve(api):
    """A SHIPPED run: 1,000 of 1,200 units pressed at 250 cents each shipped at
    900 cents, reserved at 0.1000, so the reserve sizes to 90,000 cents and
    physical net receipts to 600,000."""
    ctx = given_released_catalog(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 500000,
        },
        releases=[
            {
                "title": "Pressed Twice",
                "formats": (FORMAT_VINYL,),
                "advance_share_cents": 0,
            }
        ],
    )
    return given_shipped_run(
        api,
        ctx,
        run_kw={
            "returns_reserve_pct": f.pct4("0.1000"),
            "units_planned": 1200,
            "unit_manufacturing_cost_cents": 250,
            "window_start": "2026-04-01",
            "window_end": "2026-06-30",
        },
        units_manufactured=1200,
        units_shipped=1000,
        wholesale_unit_price_cents=900,
    )


def test_voiding_a_liquidation_returns_every_cent_to_the_held_reserve(api):
    """Voiding "pulls every liquidated cent back: reserve_liquidated_cents
    returns to reserve_held_cents and is set to 0, the axis returns to HELD, and
    reserve_initial_cents is unchanged". Because "the percentage always applies
    to reserve_initial_cents", a 0.4000 then a 0.6000 release of a 90,000-cent
    reserve move 36,000 then 54,000, and the void restores 90,000 == 90,000 + 0
    while physical_net_receipts_cents stays 600,000 throughout.

    Design: Difficulty/compensating_invariant/void_liquidation_preserves_reserve_initial_identity
    """
    ctx = _shipped_run_holding_a_ninety_thousand_cent_reserve(api)

    at_ship = read_run(api, ctx["run_id"])
    assert_reserve_conserved(at_ship)
    assert_fields_money(
        at_ship,
        reserve_initial_cents=90000,
        reserve_held_cents=90000,
        reserve_liquidated_cents=0,
        physical_net_receipts_cents=600000,
    )

    partial = validate_success(
        api.liquidate_reserve(
            ctx["run_id"],
            f.liquidate_payload(at_ship["version"], f.pct4("0.4000")),
            ANALYST,
        ),
        200,
    )
    assert_reserve_conserved(partial)
    assert_fields_money(
        partial,
        reserve_initial_cents=90000,
        reserve_held_cents=54000,
        reserve_liquidated_cents=36000,
        physical_net_receipts_cents=600000,
    )

    full = validate_success(
        api.liquidate_reserve(
            ctx["run_id"],
            f.liquidate_payload(partial["version"], f.pct4("0.6000")),
            ANALYST,
        ),
        200,
    )
    assert_reserve_conserved(full)
    assert_fields_money(
        full,
        reserve_initial_cents=90000,
        reserve_held_cents=0,
        reserve_liquidated_cents=90000,
        physical_net_receipts_cents=600000,
    )

    voided = validate_success(
        api.void_liquidation(
            ctx["run_id"], f.void_liquidation_payload(full["version"]), ANALYST
        ),
        200,
    )
    assert_reserve_conserved(voided)
    assert_fields_money(
        voided,
        reserve_initial_cents=90000,
        reserve_held_cents=90000,
        reserve_liquidated_cents=0,
        physical_net_receipts_cents=600000,
    )


def test_voiding_a_full_liquidation_reopens_the_run_and_bumps_each_write(api):
    """The reserve axis is independent of the fulfilment axis except at one
    point: "From LIQUIDATED the void also reverses the coupling, moving the
    fulfilment axis RECONCILED → SHIPPED so that a reopened reserve reopens the
    run", while "a compensating action still bumps the version of every record it
    touches; reversal restores balances, not counters". The axes therefore walk
    HELD/SHIPPED → PARTIALLY_LIQUIDATED/SHIPPED → LIQUIDATED/RECONCILED →
    HELD/SHIPPED across three writes that each add exactly 1 to version.

    Design: Difficulty/compensating_invariant/void_liquidation_preserves_reserve_initial_identity
    """
    ctx = _shipped_run_holding_a_ninety_thousand_cent_reserve(api)

    at_ship = read_run(api, ctx["run_id"])
    assert_status(at_ship, RUN_STATUS_SHIPPED)
    assert_status(at_ship, RESERVE_STATUS_HELD, field="reserve_status")

    partial = validate_success(
        api.liquidate_reserve(
            ctx["run_id"],
            f.liquidate_payload(run_version(api, ctx["run_id"]), f.pct4("0.4000")),
            ANALYST,
        ),
        200,
    )
    assert_status(partial, RUN_STATUS_SHIPPED)
    assert_status(
        partial, RESERVE_STATUS_PARTIALLY_LIQUIDATED, field="reserve_status"
    )
    assert_version_bumped(at_ship, partial, entity="PhysicalRun")

    full = validate_success(
        api.liquidate_reserve(
            ctx["run_id"],
            f.liquidate_payload(run_version(api, ctx["run_id"]), f.pct4("0.6000")),
            ANALYST,
        ),
        200,
    )
    assert_status(full, RUN_STATUS_RECONCILED)
    assert_status(full, RESERVE_STATUS_LIQUIDATED, field="reserve_status")
    assert_version_bumped(at_ship, full, by=2, entity="PhysicalRun")

    voided = validate_success(
        api.void_liquidation(
            ctx["run_id"],
            f.void_liquidation_payload(run_version(api, ctx["run_id"])),
            ANALYST,
        ),
        200,
    )
    assert_status(voided, RUN_STATUS_SHIPPED)
    assert_status(voided, RESERVE_STATUS_HELD, field="reserve_status")
    assert_version_bumped(full, voided, entity="PhysicalRun")


def _issued_final_statement_ready_to_finalize(api):
    """A FINAL statement ISSUED on 2026-07-01 over one 600,000-cent physical run
    and one 20,000-cent settled marketing spend, with the clock parked on
    2026-08-01 - strictly past the 2026-07-31 objection deadline the 30-day
    window stamped."""
    ctx = given_released_catalog(
        api,
        clock="2026-03-01T00:00:00.000Z",
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 500000,
            "objection_window_days": 30,
            "post_term_collection_days": 90,
        },
        releases=[
            {
                "title": "Audited Pressing",
                "formats": (FORMAT_VINYL,),
                "advance_share_cents": 0,
            }
        ],
    )
    ctx = given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "royalty_rate_pct": f.pct4("0.1200"),
            "escalated_royalty_rate_pct": f.pct4("0.1800"),
            "advance_amount_cents": 40000,
            "recording_costs_cents": 40000,
            "recording_recoupable_pct": f.pct4("0.5000"),
            "marketing_recoup_share_pct": f.pct4("0.5000"),
        },
    )
    ctx = given_settled_spend(
        api,
        ctx,
        spend_kw={"category": SPEND_CATEGORY_DIGITAL_ADS, "amount_cents": 25000},
        settled_amount_cents=20000,
    )
    do_set_clock(api, "2026-07-01T00:00:00.000Z")
    ctx = given_shipped_run(
        api,
        ctx,
        run_kw={
            "returns_reserve_pct": f.pct4("0.1000"),
            "units_planned": 1200,
            "unit_manufacturing_cost_cents": 250,
            "window_start": "2026-04-01",
            "window_end": "2026-06-30",
        },
        units_manufactured=1200,
        units_shipped=1000,
        wholesale_unit_price_cents=900,
    )
    ctx = given_issued_statement(
        api,
        ctx,
        statement_kw={
            "period_start": "2026-04-01",
            "period_end": "2026-06-30",
            "basis_variant": BASIS_VARIANT_FINAL,
        },
    )
    do_set_clock(api, "2026-08-01T00:00:00.000Z")
    return ctx


def test_a_material_audit_finding_credits_back_every_finalized_ledger(api):
    """A material finding moves the accounting axis back and undoes the only
    transition that ever debits the artist, "reversing the finalize debit
    exactly: unrecouped_artist_advance_cents is increased by
    advance_applied_cents, unrecouped_recording_cents by recording_applied_cents,
    and the release's recoupable_marketing_applied_cents is decreased by
    marketing_applied_cents". The waterfall charges 40,000 advance, 20,000
    recording and 10,000 marketing out of a 108,000-cent gross royalty and
    withholds 16,200 of reserve, so the three ledgers walk 40,000/20,000/0 →
    0/0/10,000 → 40,000/20,000/0 while the run is never touched.

    Design: Difficulty/compensating_invariant/conclude_audit_credits_back_every_statement_ledger
    """
    ctx = _issued_final_statement_ready_to_finalize(api)

    prepared = read_statement(api, ctx["statement_id"])
    assert_pct_equals(
        prepared["applied_royalty_rate_pct"],
        f.pct4("0.1800"),
        "applied_royalty_rate_pct",
    )
    assert_fields_money(
        prepared,
        digital_royalty_base_cents=0,
        physical_royalty_base_cents=600000,
        gross_royalty_cents=108000,
        advance_applied_cents=40000,
        recording_applied_cents=20000,
        marketing_applied_cents=10000,
        reserve_withheld_cents=16200,
        net_payable_cents=21800,
    )

    agreement_before = read_agreement(api, ctx["agreement_id"])
    assert_fields_money(
        agreement_before,
        unrecouped_artist_advance_cents=40000,
        unrecouped_recording_cents=20000,
    )
    assert_field_money(
        read_release(api, ctx["release_id"]), "recoupable_marketing_applied_cents", 0
    )

    finalized = validate_success(
        api.finalize_statement(ctx["statement_id"], BIZ_AFFAIRS), 200
    )
    assert_instant_equals(
        finalized["finalized_at"], "2026-08-01T00:00:00.000Z", "finalized_at"
    )
    assert_fields_money(
        read_agreement(api, ctx["agreement_id"]),
        unrecouped_artist_advance_cents=0,
        unrecouped_recording_cents=0,
    )
    assert_field_money(
        read_release(api, ctx["release_id"]),
        "recoupable_marketing_applied_cents",
        10000,
    )
    assert_field_money(read_artist(api, ctx["artist_id"]), "lifetime_paid_cents", 21800)

    do_request_audit(
        api, ctx["statement_id"], ctx["artist_headers"], "2026-04-01", "2026-06-30"
    )
    validate_success(
        api.conclude_audit(
            ctx["statement_id"], f.conclude_audit_payload(5000), BIZ_AFFAIRS
        ),
        200,
    )

    assert_fields_money(
        read_agreement(api, ctx["agreement_id"]),
        unrecouped_artist_advance_cents=40000,
        unrecouped_recording_cents=20000,
    )
    assert_field_money(
        read_release(api, ctx["release_id"]), "recoupable_marketing_applied_cents", 0
    )
    assert_fields_money(
        read_run(api, ctx["run_id"]),
        reserve_held_cents=90000,
        reserve_initial_cents=90000,
    )


def test_a_material_audit_finding_reopens_the_finalized_statement(api):
    """Materiality is measured against the statement itself - the bearer is
    "LABEL when the absolute value of the finding is at least five percent of
    net_payable_cents" - and "a material finding also moves the accounting axis
    FINALIZED → REVISED ... issued_at, objection_deadline and finalized_at are
    all cleared to null ... and both the statement's and the agreement's version
    increase by 1". A 5,000-cent finding clears the 1,090-cent threshold on a
    21,800-cent net payable, so the statement lands REVISED with
    AUDIT_COMPLETED.

    Design: Difficulty/compensating_invariant/conclude_audit_credits_back_every_statement_ledger
    """
    ctx = _issued_final_statement_ready_to_finalize(api)

    finalized = do_finalize_statement(api, ctx["statement_id"])
    assert_status(finalized, STATEMENT_STATUS_FINALIZED)
    assert_status(finalized, AUDIT_STATUS_NONE, field="audit_status")

    requested = validate_success(
        api.request_audit(
            ctx["statement_id"],
            f.request_audit_payload("2026-04-01", "2026-06-30"),
            ctx["artist_headers"],
        ),
        200,
    )
    assert_status(requested, STATEMENT_STATUS_FINALIZED)
    assert_status(requested, AUDIT_STATUS_REQUESTED, field="audit_status")
    assert_field(requested, "auditor_name", "Harrow & Vance")

    agreement_before = read_agreement(api, ctx["agreement_id"])
    concluded = validate_success(
        api.conclude_audit(
            ctx["statement_id"], f.conclude_audit_payload(5000), BIZ_AFFAIRS
        ),
        200,
    )
    assert_status(concluded, STATEMENT_STATUS_REVISED)
    assert_status(concluded, AUDIT_STATUS_COMPLETED, field="audit_status")
    assert_field(concluded, "audit_cost_bearer", AUDIT_COST_BEARER_LABEL)
    assert_field_money(concluded, "audit_findings_adjustment_cents", 5000)
    assert_null(concluded, "issued_at", "objection_deadline", "finalized_at")
    assert_version_bumped(requested, concluded, entity="ArtistStatement")
    assert_version_bumped(
        agreement_before,
        read_agreement(api, ctx["agreement_id"]),
        entity="ArtistAgreement",
    )
