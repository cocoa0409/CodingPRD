"""
Unbounded lifecycle cycles and the multi-hop cascades they sit inside: the
agreement amendment cycle, the report accept/dispute/resubmit cycle, the
statement objection cycle, the three-hop termination cascade and the five-hop
acceptance cascade (PRD Sections 3.3, 3.5, 3.6, 3.8, 3.9).

Every test here translates one instance of the difficulty index rules
`non_linear_state_machine` and `transitive_cascade`.
"""

from test_helpers import factories as f
from test_helpers import (
    AGREEMENT_STATUS_ACTIVE,
    AGREEMENT_STATUS_AMENDMENT_PENDING,
    AGREEMENT_STATUS_POST_TERM,
    AMENDMENT_DECISION_ACCEPT,
    AMENDMENT_DECISION_REJECT,
    BASIS_VARIANT_FINAL,
    BASIS_VARIANT_PROVISIONAL,
    DEAL_STATUS_EXPIRED,
    DEAL_STATUS_TERMINATION_NOTICE,
    DEAL_TYPE_DISTRIBUTION_FEE,
    OBJECTION_REASON_RATE_DISPUTE,
    RECOUPMENT_STATUS_RECOUPED,
    RECOUPMENT_STATUS_UNRECOUPED,
    RELEASE_STATUS_PLANNED,
    RELEASE_STATUS_RELEASED,
    RELEASE_STATUS_REVERSION_PENDING,
    RELEASE_STATUS_REVERTED,
    REPORT_STATUS_ACCEPTED,
    REPORT_STATUS_DISPUTED,
    REPORT_STATUS_SUBMITTED,
    RESOLUTION_DENIED,
    RESOLUTION_UPHELD,
    STATEMENT_STATUS_DRAFT,
    STATEMENT_STATUS_ISSUED,
    STATEMENT_STATUS_OBJECTED,
    STATEMENT_STATUS_PREPARED,
    STATEMENT_STATUS_REVISED,
    STATEMENT_STATUS_VOIDED,
    TIER_PREMIUM,
    assert_advance_conserved,
    assert_date,
    assert_field_money,
    assert_fields,
    assert_fields_money,
    assert_instant_equals,
    assert_null,
    assert_pct_equals,
    assert_status,
    assert_version_bumped,
    assert_version_unchanged,
    do_accept_report,
    do_dispute_report,
    do_expire_deal,
    do_issue_statement,
    do_object,
    do_prepare_statement,
    do_propose_amendment,
    do_resolve_amendment,
    do_resolve_objection,
    do_set_clock,
    do_submit_report,
    do_terminate_deal,
    given_accepted_report,
    given_active_agreement,
    given_released_catalog,
    given_submitted_report,
    mk_line,
    mk_statement,
    read_agreement,
    read_artist,
    read_deal,
    read_distributor,
    read_release,
    read_report_lines,
    read_statement,
)

# One STRM/US/PREMIUM card at four tenths of a cent, plus a GB card at three
# tenths for the re-priced second pass of the report cycle.
_US_AND_GB_CARDS = (
    {
        "territory_code": "US",
        "tier": TIER_PREMIUM,
        "rate_micros_per_stream": 4000,
        "effective_from": "2026-01-01",
    },
    {
        "territory_code": "GB",
        "tier": TIER_PREMIUM,
        "rate_micros_per_stream": 3000,
        "effective_from": "2026-01-01",
    },
)

# 250,000 US streams at 4,000 micros price at exactly 100,000 cents, which a
# 0.1500 fee splits into 15,000 for the distributor and 85,000 net.
_ONE_LINE_85000_NET = ({"territory_code": "US", "tier": TIER_PREMIUM, "stream_count": 250000},)


def _amendable_agreement(
    api, *, deal_advance_cents=200000, agreement_advance_cents=100000
):
    """One RELEASED release under a DISTRIBUTION_FEE deal, with one ACTIVE
    agreement whose 80,000-cent recording spend is half recoupable."""
    ctx = given_released_catalog(
        api,
        deal_kw={
            "deal_type": DEAL_TYPE_DISTRIBUTION_FEE,
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": deal_advance_cents,
            "marketing_budget_cents": 500000,
            "territory_codes": ("US", "GB"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
        },
        releases=[
            {"title": "Slow Tide", "advance_share_cents": deal_advance_cents}
        ],
    )
    return given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "royalty_rate_pct": f.pct4("0.1200"),
            "escalated_royalty_rate_pct": f.pct4("0.1800"),
            "advance_amount_cents": agreement_advance_cents,
            "recording_costs_cents": 80000,
            "recording_recoupable_pct": f.pct4("0.5000"),
            "marketing_recoup_share_pct": f.pct4("0.5000"),
        },
    )


def test_amendment_cycle_runs_twice_with_accept_then_reject_side_effects(api):
    """The cycle "the agreement may traverse without bound" is walked twice and the
    two return edges share a state but not a side-effect set. ACCEPT copies
    0.1400 and 150,000 into the live terms and lifts the artist advance balance
    from 100,000 to 150,000; the second REJECT then "left exactly as they were"
    keeps 0.1400, 150,000 and 150,000 rather than adopting the parked 0.2000 and
    90,000. Both edges clear the parked pair and both bump the version.

    Design: Difficulty/non_linear_state_machine/agreement_amendment_cycle_repeats_with_disjoint_side_effects
    """
    ctx = _amendable_agreement(api)
    active = ctx["agreement"]
    assert_status(active, AGREEMENT_STATUS_ACTIVE)
    assert_fields_money(
        active,
        advance_amount_cents=100000,
        unrecouped_artist_advance_cents=100000,
        unrecouped_recording_cents=40000,
    )
    assert_pct_equals(
        active["active_royalty_rate_pct"],
        f.pct4("0.1200"),
        field="active_royalty_rate_pct",
    )
    assert_status(
        read_deal(api, ctx["deal_id"]),
        RECOUPMENT_STATUS_UNRECOUPED,
        field="recoupment_status",
    )

    pending = do_propose_amendment(
        api, ctx["agreement_id"], f.pct4("0.1400"), 150000
    )
    assert_status(pending, AGREEMENT_STATUS_AMENDMENT_PENDING)
    assert_pct_equals(
        pending["proposed_royalty_rate_pct"],
        f.pct4("0.1400"),
        field="proposed_royalty_rate_pct",
    )
    assert_field_money(pending, "proposed_advance_amount_cents", 150000)
    assert_pct_equals(
        pending["royalty_rate_pct"], f.pct4("0.1200"), field="royalty_rate_pct"
    )
    assert_fields_money(
        pending,
        advance_amount_cents=100000,
        unrecouped_artist_advance_cents=100000,
    )
    assert_version_bumped(active, pending, entity="agreement")

    accepted = do_resolve_amendment(
        api, ctx["agreement_id"], AMENDMENT_DECISION_ACCEPT
    )
    assert_status(accepted, AGREEMENT_STATUS_ACTIVE)
    assert_pct_equals(
        accepted["royalty_rate_pct"], f.pct4("0.1400"), field="royalty_rate_pct"
    )
    assert_pct_equals(
        accepted["active_royalty_rate_pct"],
        f.pct4("0.1400"),
        field="active_royalty_rate_pct",
    )
    assert_fields_money(
        accepted,
        advance_amount_cents=150000,
        unrecouped_artist_advance_cents=150000,
        unrecouped_recording_cents=40000,
    )
    assert_null(accepted, "proposed_royalty_rate_pct", "proposed_advance_amount_cents")
    assert_version_bumped(pending, accepted, entity="agreement")
    assert_field_money(
        read_artist(api, ctx["artist_id"]), "unrecouped_advance_total_cents", 150000
    )

    reproposed = do_propose_amendment(
        api, ctx["agreement_id"], f.pct4("0.2000"), 90000
    )
    assert_status(reproposed, AGREEMENT_STATUS_AMENDMENT_PENDING)
    assert_pct_equals(
        reproposed["proposed_royalty_rate_pct"],
        f.pct4("0.2000"),
        field="proposed_royalty_rate_pct",
    )
    assert_field_money(reproposed, "proposed_advance_amount_cents", 90000)
    assert_pct_equals(
        reproposed["royalty_rate_pct"], f.pct4("0.1400"), field="royalty_rate_pct"
    )
    assert_version_bumped(accepted, reproposed, entity="agreement")

    rejected = do_resolve_amendment(
        api, ctx["agreement_id"], AMENDMENT_DECISION_REJECT
    )
    assert_status(rejected, AGREEMENT_STATUS_ACTIVE)
    assert_pct_equals(
        rejected["royalty_rate_pct"], f.pct4("0.1400"), field="royalty_rate_pct"
    )
    assert_pct_equals(
        rejected["active_royalty_rate_pct"],
        f.pct4("0.1400"),
        field="active_royalty_rate_pct",
    )
    assert_fields_money(
        rejected,
        advance_amount_cents=150000,
        unrecouped_artist_advance_cents=150000,
        unrecouped_recording_cents=40000,
    )
    assert_null(rejected, "proposed_royalty_rate_pct", "proposed_advance_amount_cents")
    assert_version_bumped(reproposed, rejected, entity="agreement")
    assert_field_money(
        read_artist(api, ctx["artist_id"]), "unrecouped_advance_total_cents", 150000
    )


def test_amendment_accept_of_a_reduced_advance_never_claws_back_the_balance(api):
    """The accept edge's balance side-effect is a floored delta, not an assignment:
    "with a negative difference treated as zero so that a reduced advance never
    claws back a balance already recouped". Cutting the advance from 100,000 to
    40,000 leaves `unrecouped_artist_advance_cents` at 100,000 while
    `advance_amount_cents` becomes 40,000 and the rate becomes 0.1000.

    Design: Difficulty/non_linear_state_machine/agreement_amendment_cycle_repeats_with_disjoint_side_effects
    """
    ctx = _amendable_agreement(api)
    active = ctx["agreement"]
    assert_field_money(active, "unrecouped_artist_advance_cents", 100000)

    pending = do_propose_amendment(
        api, ctx["agreement_id"], f.pct4("0.1000"), 40000
    )
    assert_status(pending, AGREEMENT_STATUS_AMENDMENT_PENDING)
    assert_field_money(pending, "proposed_advance_amount_cents", 40000)

    accepted = do_resolve_amendment(
        api, ctx["agreement_id"], AMENDMENT_DECISION_ACCEPT
    )
    assert_status(accepted, AGREEMENT_STATUS_ACTIVE)
    assert_pct_equals(
        accepted["royalty_rate_pct"], f.pct4("0.1000"), field="royalty_rate_pct"
    )
    assert_pct_equals(
        accepted["active_royalty_rate_pct"],
        f.pct4("0.1000"),
        field="active_royalty_rate_pct",
    )
    assert_fields_money(
        accepted,
        advance_amount_cents=40000,
        unrecouped_artist_advance_cents=100000,
        unrecouped_recording_cents=40000,
    )
    assert_null(accepted, "proposed_royalty_rate_pct", "proposed_advance_amount_cents")
    assert_version_bumped(pending, accepted, entity="agreement")
    assert_field_money(
        read_artist(api, ctx["artist_id"]), "unrecouped_advance_total_cents", 100000
    )


def test_amendment_accept_reselects_the_active_rate_rather_than_copying_it(api):
    """The accept edge does not copy the accepted rate into the effective rate:
    "The `active_royalty_rate_pct` is then re-selected". Under a RECOUPED deal the
    escalated 0.1800 keeps winning, so accepting 0.1400 moves `royalty_rate_pct`
    to 0.1400 and the advance to 150,000 while `active_royalty_rate_pct` stays
    0.1800.

    Design: Difficulty/non_linear_state_machine/agreement_amendment_cycle_repeats_with_disjoint_side_effects
    """
    ctx = _amendable_agreement(api, deal_advance_cents=0)
    assert_status(
        read_deal(api, ctx["deal_id"]),
        RECOUPMENT_STATUS_RECOUPED,
        field="recoupment_status",
    )
    active = ctx["agreement"]
    assert_pct_equals(
        active["active_royalty_rate_pct"],
        f.pct4("0.1800"),
        field="active_royalty_rate_pct",
    )
    assert_pct_equals(
        active["royalty_rate_pct"], f.pct4("0.1200"), field="royalty_rate_pct"
    )

    do_propose_amendment(api, ctx["agreement_id"], f.pct4("0.1400"), 150000)
    accepted = do_resolve_amendment(
        api, ctx["agreement_id"], AMENDMENT_DECISION_ACCEPT
    )
    assert_status(accepted, AGREEMENT_STATUS_ACTIVE)
    assert_pct_equals(
        accepted["royalty_rate_pct"], f.pct4("0.1400"), field="royalty_rate_pct"
    )
    assert_pct_equals(
        accepted["active_royalty_rate_pct"],
        f.pct4("0.1800"),
        field="active_royalty_rate_pct",
    )
    assert_fields_money(
        accepted,
        advance_amount_cents=150000,
        unrecouped_artist_advance_cents=150000,
    )


def _report_cycle_ctx(api):
    """A one-release DISTRIBUTION_FEE deal carrying a 100,000-cent advance, with a
    SUBMITTED report holding a single 250,000-stream US line."""
    ctx = given_released_catalog(
        api,
        deal_kw={
            "deal_type": DEAL_TYPE_DISTRIBUTION_FEE,
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 100000,
            "cross_collateralized": True,
            "territory_codes": ("US", "GB"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
        },
        releases=[{"title": "Harbour Lights", "advance_share_cents": 100000}],
    )
    return given_submitted_report(
        api, ctx, lines=_ONE_LINE_85000_NET, cards=_US_AND_GB_CARDS
    )


def test_report_cycle_accept_dispute_resubmit_reprices_against_the_grown_line_set(api):
    """The cycle "`ACCEPTED → DISPUTED → SUBMITTED → ACCEPTED` may repeat without
    bound" is walked once end to end, and the return edge is a real re-pricing:
    "every figure is recomputed from scratch against the report's current lines and
    the current rate book". The first pass posts 85,000 net and 85,000 of advance;
    the dispute unwinds all four hops to 0 and 100,000; adding a 30,000-cent GB
    line and resubmitting yields 130,000 gross, 19,500 share, 110,500 net, and the
    second acceptance clears the advance with 10,500 of post-recoupment excess.

    Design: Difficulty/non_linear_state_machine/report_accept_dispute_resubmit_cycle_returns_to_accepted
    """
    ctx = _report_cycle_ctx(api)
    report_id = ctx["report_id"]
    deal_id = ctx["deal_id"]
    release_id = ctx["release_id"]

    submitted = ctx["report"]
    assert_status(submitted, REPORT_STATUS_SUBMITTED)
    assert_fields_money(
        submitted,
        gross_receipts_cents=100000,
        distributor_share_cents=15000,
        net_receipts_cents=85000,
        advance_applied_cents=0,
    )

    deal_pre = read_deal(api, deal_id)
    accepted = do_accept_report(api, report_id, deal_pre["version"])
    assert_status(accepted, REPORT_STATUS_ACCEPTED)
    assert_field_money(accepted, "advance_applied_cents", 85000)
    assert_version_bumped(submitted, accepted, entity="report")

    deal_accepted = read_deal(api, deal_id)
    assert_fields_money(
        deal_accepted,
        advance_recouped_cents=85000,
        unrecouped_advance_cents=15000,
        net_receipts_to_date_cents=85000,
        post_recoupment_net_receipts_cents=0,
    )
    assert_status(
        deal_accepted, RECOUPMENT_STATUS_UNRECOUPED, field="recoupment_status"
    )
    assert_advance_conserved(deal_accepted)
    assert_version_bumped(deal_pre, deal_accepted, entity="deal")

    release_accepted = read_release(api, release_id)
    assert_fields_money(
        release_accepted,
        net_receipts_to_date_cents=85000,
        release_advance_recouped_cents=85000,
        unrecouped_advance_share_cents=15000,
    )
    lines_accepted = read_report_lines(api, report_id)
    assert len(lines_accepted) == 1
    assert_field_money(lines_accepted[0], "net_receipts_cents", 85000)

    reason = "GB streams were omitted from the first submission"
    disputed = do_dispute_report(
        api, report_id, deal_accepted["version"], reason
    )
    assert_status(disputed, REPORT_STATUS_DISPUTED)
    assert_fields(disputed, dispute_reason=reason)
    assert_field_money(disputed, "advance_applied_cents", 0)
    assert_version_bumped(accepted, disputed, entity="report")

    deal_disputed = read_deal(api, deal_id)
    assert_fields_money(
        deal_disputed,
        advance_recouped_cents=0,
        unrecouped_advance_cents=100000,
        net_receipts_to_date_cents=0,
        post_recoupment_net_receipts_cents=0,
    )
    assert_status(
        deal_disputed, RECOUPMENT_STATUS_UNRECOUPED, field="recoupment_status"
    )
    assert_advance_conserved(deal_disputed)
    assert_version_bumped(deal_accepted, deal_disputed, entity="deal")

    release_disputed = read_release(api, release_id)
    assert_fields_money(
        release_disputed,
        net_receipts_to_date_cents=0,
        release_advance_recouped_cents=0,
        unrecouped_advance_share_cents=100000,
    )
    assert_null(read_report_lines(api, report_id)[0], "net_receipts_cents")

    mk_line(
        api,
        report_id,
        release_id,
        ctx["partner_headers"],
        territory_code="GB",
        tier=TIER_PREMIUM,
        stream_count=100000,
    )
    resubmitted = do_submit_report(api, report_id, ctx["partner_headers"])
    assert_status(resubmitted, REPORT_STATUS_SUBMITTED)
    assert_null(resubmitted, "dispute_reason")
    assert_fields_money(
        resubmitted,
        gross_receipts_cents=130000,
        distributor_share_cents=19500,
        net_receipts_cents=110500,
        advance_applied_cents=0,
    )
    assert_version_bumped(disputed, resubmitted, entity="report")

    reaccepted = do_accept_report(api, report_id, deal_disputed["version"])
    assert_status(reaccepted, REPORT_STATUS_ACCEPTED)
    assert_field_money(reaccepted, "advance_applied_cents", 100000)
    assert_version_bumped(resubmitted, reaccepted, entity="report")

    deal_final = read_deal(api, deal_id)
    assert_fields_money(
        deal_final,
        advance_recouped_cents=100000,
        unrecouped_advance_cents=0,
        net_receipts_to_date_cents=110500,
        post_recoupment_net_receipts_cents=10500,
    )
    assert_status(deal_final, RECOUPMENT_STATUS_RECOUPED, field="recoupment_status")
    assert_advance_conserved(deal_final)
    assert_version_bumped(deal_disputed, deal_final, entity="deal")

    release_final = read_release(api, release_id)
    assert_fields_money(
        release_final,
        net_receipts_to_date_cents=110500,
        release_advance_recouped_cents=100000,
        unrecouped_advance_share_cents=0,
    )
    by_territory = {
        line["territory_code"]: line for line in read_report_lines(api, report_id)
    }
    assert_field_money(by_territory["US"], "net_receipts_cents", 85000)
    assert_field_money(by_territory["GB"], "net_receipts_cents", 25500)


def test_dispute_from_submitted_unwinds_nothing_and_the_cycle_still_closes(api):
    """The cycle has two entry edges into `DISPUTED` and only one of them
    compensates: "From `SUBMITTED`, the dispute moves the report `SUBMITTED →
    DISPUTED` and does nothing but store `dispute_reason`". The priced 100,000 /
    15,000 / 85,000 figures survive, the deal's ledgers stay at 0 and 100,000, and
    the line's `net_receipts_cents` is still null; resubmitting then clears the
    reason and the acceptance posts the same 85,000.

    Design: Difficulty/non_linear_state_machine/report_accept_dispute_resubmit_cycle_returns_to_accepted
    """
    ctx = _report_cycle_ctx(api)
    report_id = ctx["report_id"]
    deal_id = ctx["deal_id"]

    submitted = ctx["report"]
    deal_pre = read_deal(api, deal_id)
    reason = "The US premium rate card applied here looks stale"
    disputed = do_dispute_report(api, report_id, deal_pre["version"], reason)
    assert_status(disputed, REPORT_STATUS_DISPUTED)
    assert_fields(disputed, dispute_reason=reason)
    assert_fields_money(
        disputed,
        gross_receipts_cents=100000,
        distributor_share_cents=15000,
        net_receipts_cents=85000,
        advance_applied_cents=0,
    )
    assert_version_bumped(submitted, disputed, entity="report")

    deal_disputed = read_deal(api, deal_id)
    assert_fields_money(
        deal_disputed,
        advance_recouped_cents=0,
        unrecouped_advance_cents=100000,
        net_receipts_to_date_cents=0,
        post_recoupment_net_receipts_cents=0,
    )
    assert_status(
        deal_disputed, RECOUPMENT_STATUS_UNRECOUPED, field="recoupment_status"
    )
    release_disputed = read_release(api, ctx["release_id"])
    # PRD 3.2: "A new release has ... four derived counters at 0", and a dispute
    # from SUBMITTED "does nothing but store dispute_reason", so the release is
    # untouched and still carries its creation-time zeros.
    assert_fields_money(
        release_disputed,
        net_receipts_to_date_cents=0,
        release_advance_recouped_cents=0,
        unrecouped_advance_share_cents=0,
    )
    assert_null(read_report_lines(api, report_id)[0], "net_receipts_cents")

    resubmitted = do_submit_report(api, report_id, ctx["partner_headers"])
    assert_status(resubmitted, REPORT_STATUS_SUBMITTED)
    assert_null(resubmitted, "dispute_reason")
    assert_fields_money(
        resubmitted,
        gross_receipts_cents=100000,
        distributor_share_cents=15000,
        net_receipts_cents=85000,
    )

    reaccepted = do_accept_report(api, report_id, deal_disputed["version"])
    assert_status(reaccepted, REPORT_STATUS_ACCEPTED)
    assert_field_money(reaccepted, "advance_applied_cents", 85000)
    deal_final = read_deal(api, deal_id)
    assert_fields_money(
        deal_final,
        advance_recouped_cents=85000,
        unrecouped_advance_cents=15000,
        net_receipts_to_date_cents=85000,
        post_recoupment_net_receipts_cents=0,
    )
    assert_advance_conserved(deal_final)


def _statement_cycle_ctx(api):
    """A RECOUPED, zero-advance deal at 2026-07-01 whose single agreement pays the
    escalated 0.1800 rate on one accepted 85,000-cent quarter, with a 30-day
    objection window."""
    ctx = given_released_catalog(
        api,
        clock="2026-07-01T00:00:00.000Z",
        deal_kw={
            "deal_type": DEAL_TYPE_DISTRIBUTION_FEE,
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "objection_window_days": 30,
            "post_term_collection_days": 90,
            "territory_codes": ("US",),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
        },
        releases=[{"title": "Paper Lantern", "advance_share_cents": 0}],
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
    return given_accepted_report(
        api, ctx, lines=_ONE_LINE_85000_NET, cards=(_US_AND_GB_CARDS[0],)
    )


def _prepared_final_statement(api, ctx):
    statement = mk_statement(
        api,
        ctx["agreement_id"],
        basis_variant=BASIS_VARIANT_FINAL,
        period_start="2026-04-01",
        period_end="2026-06-30",
    )
    return do_prepare_statement(api, statement["id"])


def test_upheld_objection_reprepare_folds_the_adjustment_and_mints_a_fresh_deadline(api):
    """Walking `ISSUED → OBJECTED → REVISED → PREPARED → ISSUED` is not a return to
    the same statement: "`revision_count` increases by 1" on the `REVISED` re-entry
    and the granted adjustment "is added back into `net_payable_cents` on the next
    preparation". A 15,300-cent statement issued at 2026-07-01 with a deadline of
    2026-07-31 comes back as 17,300 with `revision_count` 1, re-issued at
    2026-07-10 with a fresh 2026-08-09 deadline.

    Design: Difficulty/non_linear_state_machine/statement_issue_object_uphold_reprepare_cycle_increments_revision_count
    """
    ctx = _statement_cycle_ctx(api)
    prepared = _prepared_final_statement(api, ctx)
    statement_id = prepared["id"]
    assert_status(prepared, STATEMENT_STATUS_PREPARED)
    assert_pct_equals(
        prepared["applied_royalty_rate_pct"],
        f.pct4("0.1800"),
        field="applied_royalty_rate_pct",
    )
    assert_fields_money(
        prepared,
        digital_royalty_base_cents=85000,
        physical_royalty_base_cents=0,
        gross_royalty_cents=15300,
        marketing_cap_cents=25500,
        advance_applied_cents=0,
        recording_applied_cents=0,
        marketing_applied_cents=0,
        reserve_withheld_cents=0,
        net_payable_cents=15300,
    )
    assert_fields(prepared, revision_count=0)
    assert_null(prepared, "issued_at", "objection_deadline", "objection_resolution")

    issued = do_issue_statement(api, statement_id)
    assert_status(issued, STATEMENT_STATUS_ISSUED)
    assert_instant_equals(
        issued["issued_at"], "2026-07-01T00:00:00.000Z", field="issued_at"
    )
    assert_instant_equals(
        issued["objection_deadline"],
        "2026-07-31T00:00:00.000Z",
        field="objection_deadline",
    )
    assert_version_bumped(prepared, issued, entity="statement")

    objected = do_object(
        api,
        statement_id,
        ctx["artist_headers"],
        OBJECTION_REASON_RATE_DISPUTE,
        5000,
        "The escalated rate was applied a quarter too early",
    )
    assert_status(objected, STATEMENT_STATUS_OBJECTED)
    assert_instant_equals(
        objected["objection_filed_at"],
        "2026-07-01T00:00:00.000Z",
        field="objection_filed_at",
    )
    assert_fields(objected, objection_reason_code=OBJECTION_REASON_RATE_DISPUTE)
    assert_field_money(objected, "objection_disputed_amount_cents", 5000)
    assert_null(objected, "objection_resolution")
    assert_version_bumped(issued, objected, entity="statement")

    revised = do_resolve_objection(
        api,
        statement_id,
        resolution=RESOLUTION_UPHELD,
        objection_adjustment_cents=2000,
    )
    assert_status(revised, STATEMENT_STATUS_REVISED)
    assert_fields(
        revised, objection_resolution=RESOLUTION_UPHELD, revision_count=0
    )
    assert_field_money(revised, "objection_adjustment_cents", 2000)
    assert_null(
        revised, "issued_at", "issued_by_user_id", "objection_deadline"
    )
    assert_version_bumped(objected, revised, entity="statement")

    do_set_clock(api, "2026-07-10T00:00:00.000Z")
    reprepared = do_prepare_statement(api, statement_id)
    assert_status(reprepared, STATEMENT_STATUS_PREPARED)
    assert_fields(reprepared, revision_count=1)
    assert_fields_money(
        reprepared,
        digital_royalty_base_cents=85000,
        gross_royalty_cents=15300,
        advance_applied_cents=0,
        recording_applied_cents=0,
        marketing_applied_cents=0,
        reserve_withheld_cents=0,
        net_payable_cents=17300,
    )
    assert_version_bumped(revised, reprepared, entity="statement")

    reissued = do_issue_statement(api, statement_id)
    assert_status(reissued, STATEMENT_STATUS_ISSUED)
    assert_instant_equals(
        reissued["issued_at"], "2026-07-10T00:00:00.000Z", field="issued_at"
    )
    assert_instant_equals(
        reissued["objection_deadline"],
        "2026-08-09T00:00:00.000Z",
        field="objection_deadline",
    )
    assert_fields(reissued, revision_count=1)
    assert_version_bumped(reprepared, reissued, entity="statement")

    assert_field_money(
        read_agreement(api, ctx["agreement_id"]),
        "unrecouped_artist_advance_cents",
        0,
    )
    assert_field_money(read_artist(api, ctx["artist_id"]), "lifetime_paid_cents", 0)


def test_denied_objection_returns_to_issued_without_revising_or_reopening_the_window(api):
    """The other resolution arm leaves the cycle rather than closing it: `DENIED`
    "returns the statement `OBJECTED → ISSUED`, stores `objection_resolution` as
    `DENIED`, leaves `objection_adjustment_cents` null, and ... leaves
    `objection_deadline` exactly as it was". The 15,300-cent net payable and the
    2026-07-31 deadline are untouched and `revision_count` stays 0.

    Design: Difficulty/non_linear_state_machine/statement_issue_object_uphold_reprepare_cycle_increments_revision_count
    """
    ctx = _statement_cycle_ctx(api)
    prepared = _prepared_final_statement(api, ctx)
    statement_id = prepared["id"]
    issued = do_issue_statement(api, statement_id)
    assert_instant_equals(
        issued["objection_deadline"],
        "2026-07-31T00:00:00.000Z",
        field="objection_deadline",
    )

    objected = do_object(
        api,
        statement_id,
        ctx["artist_headers"],
        OBJECTION_REASON_RATE_DISPUTE,
        5000,
        "The escalated rate was applied a quarter too early",
    )
    assert_status(objected, STATEMENT_STATUS_OBJECTED)

    denied = do_resolve_objection(api, statement_id, resolution=RESOLUTION_DENIED)
    assert_status(denied, STATEMENT_STATUS_ISSUED)
    assert_fields(
        denied, objection_resolution=RESOLUTION_DENIED, revision_count=0
    )
    assert_null(denied, "objection_adjustment_cents")
    assert_instant_equals(
        denied["objection_deadline"],
        "2026-07-31T00:00:00.000Z",
        field="objection_deadline",
    )
    assert_instant_equals(
        denied["issued_at"], "2026-07-01T00:00:00.000Z", field="issued_at"
    )
    assert_field_money(denied, "net_payable_cents", 15300)
    assert_field_money(denied, "gross_royalty_cents", 15300)
    assert_version_bumped(objected, denied, entity="statement")


def _wind_down_ctx(api):
    """A two-release deal - one RELEASED, one still PLANNED - with an ACTIVE
    agreement on each, one accepted 85,000-cent quarter, and two unissued
    PROVISIONAL statements on the first agreement (one PREPARED, one DRAFT)."""
    ctx = given_released_catalog(
        api,
        deal_kw={
            "deal_type": DEAL_TYPE_DISTRIBUTION_FEE,
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "objection_window_days": 30,
            "post_term_collection_days": 90,
            "territory_codes": ("US",),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
        },
        releases=[
            {"title": "Slate Rain", "advance_share_cents": 0},
            {
                "title": "Ochre Field",
                "planned_release_date": "2026-11-01",
                "advance_share_cents": 0,
            },
        ],
        release_indexes=[0],
    )
    agreement_kw = {
        "royalty_rate_pct": f.pct4("0.1200"),
        "escalated_royalty_rate_pct": f.pct4("0.1800"),
        "advance_amount_cents": 0,
        "recording_costs_cents": 0,
        "recording_recoupable_pct": f.pct4("0.0000"),
        "marketing_recoup_share_pct": f.pct4("0.5000"),
    }
    ctx = given_active_agreement(
        api, ctx, release_index=0, agreement_kw=agreement_kw
    )
    ctx = given_active_agreement(
        api, ctx, release_index=1, agreement_kw=agreement_kw
    )
    ctx = given_accepted_report(
        api, ctx, lines=_ONE_LINE_85000_NET, cards=(_US_AND_GB_CARDS[0],)
    )
    first_agreement_id = ctx["agreements"][0]["id"]
    ctx["prepared_statement"] = do_prepare_statement(
        api,
        mk_statement(
            api,
            first_agreement_id,
            basis_variant=BASIS_VARIANT_PROVISIONAL,
            period_start="2026-04-01",
            period_end="2026-06-30",
        )["id"],
    )
    ctx["draft_statement"] = mk_statement(
        api,
        first_agreement_id,
        basis_variant=BASIS_VARIANT_PROVISIONAL,
        period_start="2026-04-01",
        period_end="2026-06-30",
    )
    return ctx


def test_for_cause_termination_cascades_releases_agreements_and_unissued_statements(api):
    """All three hops must fire: "every release in `RELEASED` moves to
    `REVERSION_PENDING` ... while every release still in `PLANNED` ... moves
    straight to `REVERTED`", then every governing agreement to `POST_TERM`, then
    "every statement of one of those agreements sitting in `DRAFT` or `PREPARED`
    moves to `VOIDED`". Terminating on 2026-08-01 with a 90-day tail pins
    2026-10-30 onto the deal, the reverting release and both agreements, and bumps
    seven version counters.

    Design: Difficulty/transitive_cascade/terminate_cascades_release_then_agreement_then_statement
    """
    ctx = _wind_down_ctx(api)
    released_id = ctx["releases"][0]["id"]
    planned_id = ctx["releases"][1]["id"]
    first_agreement_id = ctx["agreements"][0]["id"]
    second_agreement_id = ctx["agreements"][1]["id"]

    prepared_before = ctx["prepared_statement"]
    draft_before = ctx["draft_statement"]
    assert_status(prepared_before, STATEMENT_STATUS_PREPARED)
    assert_field_money(prepared_before, "net_payable_cents", 15300)
    assert_status(draft_before, STATEMENT_STATUS_DRAFT)

    deal_before = read_deal(api, ctx["deal_id"])
    released_before = read_release(api, released_id)
    planned_before = read_release(api, planned_id)
    first_before = read_agreement(api, first_agreement_id)
    second_before = read_agreement(api, second_agreement_id)
    assert_status(released_before, RELEASE_STATUS_RELEASED)
    assert_status(planned_before, RELEASE_STATUS_PLANNED)
    assert_status(first_before, AGREEMENT_STATUS_ACTIVE)
    assert_status(second_before, AGREEMENT_STATUS_ACTIVE)

    terminated = do_terminate_deal(api, ctx["deal_id"])
    assert_status(terminated, DEAL_STATUS_TERMINATION_NOTICE)
    assert_date(
        terminated["termination_effective_date"],
        "2026-08-01",
        field="termination_effective_date",
    )
    assert_date(
        terminated["post_term_collection_end_date"],
        "2026-10-30",
        field="post_term_collection_end_date",
    )
    assert_version_bumped(deal_before, terminated, entity="deal")

    released_after = read_release(api, released_id)
    assert_status(released_after, RELEASE_STATUS_REVERSION_PENDING)
    assert_date(
        released_after["reversion_eligible_date"],
        "2026-10-30",
        field="reversion_eligible_date",
    )
    assert_version_bumped(released_before, released_after, entity="release")

    planned_after = read_release(api, planned_id)
    assert_status(planned_after, RELEASE_STATUS_REVERTED)
    assert_version_bumped(planned_before, planned_after, entity="release")

    first_after = read_agreement(api, first_agreement_id)
    assert_status(first_after, AGREEMENT_STATUS_POST_TERM)
    assert_date(
        first_after["post_term_collection_end_date"],
        "2026-10-30",
        field="post_term_collection_end_date",
    )
    assert_version_bumped(first_before, first_after, entity="agreement")

    second_after = read_agreement(api, second_agreement_id)
    assert_status(second_after, AGREEMENT_STATUS_POST_TERM)
    assert_date(
        second_after["post_term_collection_end_date"],
        "2026-10-30",
        field="post_term_collection_end_date",
    )
    assert_version_bumped(second_before, second_after, entity="agreement")

    prepared_after = read_statement(api, prepared_before["id"])
    assert_status(prepared_after, STATEMENT_STATUS_VOIDED)
    assert_field_money(prepared_after, "net_payable_cents", 15300)
    assert_version_bumped(prepared_before, prepared_after, entity="statement")

    draft_after = read_statement(api, draft_before["id"])
    assert_status(draft_after, STATEMENT_STATUS_VOIDED)
    assert_version_bumped(draft_before, draft_after, entity="statement")

    assert_fields(read_distributor(api, ctx["dist_id"]), active_deal_count=1)


def test_natural_expiry_moves_no_release_agreement_or_statement(api):
    """The sibling fork stamps dates and stops: "every release in `PLANNED` or
    `RELEASED` receives `reversion_eligible_date`, but **no release changes
    state**, no agreement moves to `POST_TERM`, and consequently no statement is
    voided". Expiring on 2027-01-05 pins 2027-03-31 (term end plus the 90-day
    tail) onto both releases while leaving both agreements `ACTIVE` with a null
    collection end and both statements exactly as they were.

    Design: Difficulty/transitive_cascade/terminate_cascades_release_then_agreement_then_statement
    """
    ctx = _wind_down_ctx(api)
    released_id = ctx["releases"][0]["id"]
    planned_id = ctx["releases"][1]["id"]
    first_agreement_id = ctx["agreements"][0]["id"]
    second_agreement_id = ctx["agreements"][1]["id"]
    prepared_before = ctx["prepared_statement"]
    draft_before = ctx["draft_statement"]

    do_set_clock(api, "2027-01-05T00:00:00.000Z")
    deal_before = read_deal(api, ctx["deal_id"])
    released_before = read_release(api, released_id)
    planned_before = read_release(api, planned_id)
    first_before = read_agreement(api, first_agreement_id)
    second_before = read_agreement(api, second_agreement_id)

    expired = do_expire_deal(api, ctx["deal_id"])
    assert_status(expired, DEAL_STATUS_EXPIRED)
    assert_null(expired, "termination_effective_date")
    assert_date(
        expired["post_term_collection_end_date"],
        "2027-03-31",
        field="post_term_collection_end_date",
    )
    assert_version_bumped(deal_before, expired, entity="deal")

    released_after = read_release(api, released_id)
    assert_status(released_after, RELEASE_STATUS_RELEASED)
    assert_date(
        released_after["reversion_eligible_date"],
        "2027-03-31",
        field="reversion_eligible_date",
    )
    assert_version_bumped(released_before, released_after, entity="release")

    planned_after = read_release(api, planned_id)
    assert_status(planned_after, RELEASE_STATUS_PLANNED)
    assert_date(
        planned_after["reversion_eligible_date"],
        "2027-03-31",
        field="reversion_eligible_date",
    )
    assert_version_bumped(planned_before, planned_after, entity="release")

    first_after = read_agreement(api, first_agreement_id)
    assert_status(first_after, AGREEMENT_STATUS_ACTIVE)
    assert_null(first_after, "post_term_collection_end_date")
    assert_version_unchanged(first_before, first_after, entity="agreement")

    second_after = read_agreement(api, second_agreement_id)
    assert_status(second_after, AGREEMENT_STATUS_ACTIVE)
    assert_null(second_after, "post_term_collection_end_date")
    assert_version_unchanged(second_before, second_after, entity="agreement")

    prepared_after = read_statement(api, prepared_before["id"])
    assert_status(prepared_after, STATEMENT_STATUS_PREPARED)
    assert_field_money(prepared_after, "net_payable_cents", 15300)
    assert_version_unchanged(prepared_before, prepared_after, entity="statement")

    draft_after = read_statement(api, draft_before["id"])
    assert_status(draft_after, STATEMENT_STATUS_DRAFT)
    assert_version_unchanged(draft_before, draft_after, entity="statement")

    assert_fields(read_distributor(api, ctx["dist_id"]), active_deal_count=0)


def _acceptance_cascade_ctx(api, *, advance_cents):
    """A cross-collateralized deal carrying ``advance_cents``, one RELEASED release
    holding the whole advance share, one ACTIVE agreement that escalates from
    0.1200 to 0.1800, and a SUBMITTED report worth 85,000 net."""
    ctx = given_released_catalog(
        api,
        deal_kw={
            "deal_type": DEAL_TYPE_DISTRIBUTION_FEE,
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": advance_cents,
            "cross_collateralized": True,
            "territory_codes": ("US",),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
        },
        releases=[{"title": "Copper Wire", "advance_share_cents": advance_cents}],
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
        api, ctx, lines=_ONE_LINE_85000_NET, cards=(_US_AND_GB_CARDS[0],)
    )


def test_acceptance_cascade_runs_five_hops_to_the_escalated_royalty_rate(api):
    """Acceptance "runs a five-hop cascade, each hop caused by the one before it",
    and the fifth hop is only reachable through the fourth: "when the recomputation
    leaves `unrecouped_advance_cents` at exactly 0, the deal's `recoupment_status`
    flips `UNRECOUPED → RECOUPED`". An 85,000-cent pool against a 50,000-cent
    advance therefore posts 85,000 to the line and the release, applies 50,000,
    banks 35,000 of excess and lifts the agreement from 0.1200 to 0.1800.

    Design: Difficulty/transitive_cascade/accept_cascades_lines_to_release_to_deal_to_recoupment_to_royalty_rate
    """
    ctx = _acceptance_cascade_ctx(api, advance_cents=50000)
    report_id = ctx["report_id"]
    release_id = ctx["release_id"]
    agreement_id = ctx["agreement_id"]

    submitted = ctx["report"]
    assert_status(submitted, REPORT_STATUS_SUBMITTED)
    assert_fields_money(
        submitted,
        gross_receipts_cents=100000,
        distributor_share_cents=15000,
        net_receipts_cents=85000,
        advance_applied_cents=0,
    )
    deal_before = read_deal(api, ctx["deal_id"])
    release_before = read_release(api, release_id)
    agreement_before = read_agreement(api, agreement_id)
    assert_status(
        deal_before, RECOUPMENT_STATUS_UNRECOUPED, field="recoupment_status"
    )
    assert_pct_equals(
        agreement_before["active_royalty_rate_pct"],
        f.pct4("0.1200"),
        field="active_royalty_rate_pct",
    )
    assert_null(read_report_lines(api, report_id)[0], "net_receipts_cents")

    accepted = do_accept_report(api, report_id, deal_before["version"])
    assert_status(accepted, REPORT_STATUS_ACCEPTED)
    assert_field_money(accepted, "advance_applied_cents", 50000)
    assert_version_bumped(submitted, accepted, entity="report")

    lines = read_report_lines(api, report_id)
    assert len(lines) == 1
    assert_field_money(lines[0], "net_receipts_cents", 85000)

    release_after = read_release(api, release_id)
    assert_fields_money(
        release_after,
        net_receipts_to_date_cents=85000,
        release_advance_recouped_cents=50000,
        unrecouped_advance_share_cents=0,
    )
    assert_version_bumped(release_before, release_after, entity="release")

    deal_after = read_deal(api, ctx["deal_id"])
    assert_fields_money(
        deal_after,
        net_receipts_to_date_cents=85000,
        advance_recouped_cents=50000,
        unrecouped_advance_cents=0,
        post_recoupment_net_receipts_cents=35000,
    )
    assert_status(deal_after, RECOUPMENT_STATUS_RECOUPED, field="recoupment_status")
    assert_advance_conserved(deal_after)
    assert_version_bumped(deal_before, deal_after, entity="deal")

    agreement_after = read_agreement(api, agreement_id)
    assert_pct_equals(
        agreement_after["active_royalty_rate_pct"],
        f.pct4("0.1800"),
        field="active_royalty_rate_pct",
    )
    assert_pct_equals(
        agreement_after["royalty_rate_pct"],
        f.pct4("0.1200"),
        field="royalty_rate_pct",
    )
    assert_status(agreement_after, AGREEMENT_STATUS_ACTIVE)
    assert_version_bumped(agreement_before, agreement_after, entity="agreement")


def test_acceptance_stops_at_the_third_hop_when_the_pool_cannot_clear_the_advance(api):
    """The fourth and fifth hops fire only on an exact clearance: the flip happens
    "when the recomputation leaves `unrecouped_advance_cents` at exactly 0". The
    same 85,000-cent pool against a 100,000-cent advance applies all 85,000, leaves
    15,000 outstanding and 0 of excess, so the deal stays `UNRECOUPED` and the
    agreement is never touched - it keeps 0.1200 and its version.

    Design: Difficulty/transitive_cascade/accept_cascades_lines_to_release_to_deal_to_recoupment_to_royalty_rate
    """
    ctx = _acceptance_cascade_ctx(api, advance_cents=100000)
    report_id = ctx["report_id"]
    release_id = ctx["release_id"]
    agreement_id = ctx["agreement_id"]

    deal_before = read_deal(api, ctx["deal_id"])
    release_before = read_release(api, release_id)
    agreement_before = read_agreement(api, agreement_id)

    accepted = do_accept_report(api, report_id, deal_before["version"])
    assert_status(accepted, REPORT_STATUS_ACCEPTED)
    assert_field_money(accepted, "advance_applied_cents", 85000)

    assert_field_money(
        read_report_lines(api, report_id)[0], "net_receipts_cents", 85000
    )

    release_after = read_release(api, release_id)
    assert_fields_money(
        release_after,
        net_receipts_to_date_cents=85000,
        release_advance_recouped_cents=85000,
        unrecouped_advance_share_cents=15000,
    )
    assert_version_bumped(release_before, release_after, entity="release")

    deal_after = read_deal(api, ctx["deal_id"])
    assert_fields_money(
        deal_after,
        net_receipts_to_date_cents=85000,
        advance_recouped_cents=85000,
        unrecouped_advance_cents=15000,
        post_recoupment_net_receipts_cents=0,
    )
    assert_status(
        deal_after, RECOUPMENT_STATUS_UNRECOUPED, field="recoupment_status"
    )
    assert_advance_conserved(deal_after)
    assert_version_bumped(deal_before, deal_after, entity="deal")

    agreement_after = read_agreement(api, agreement_id)
    assert_pct_equals(
        agreement_after["active_royalty_rate_pct"],
        f.pct4("0.1200"),
        field="active_royalty_rate_pct",
    )
    assert_status(agreement_after, AGREEMENT_STATUS_ACTIVE)
    assert_version_unchanged(agreement_before, agreement_after, entity="agreement")
