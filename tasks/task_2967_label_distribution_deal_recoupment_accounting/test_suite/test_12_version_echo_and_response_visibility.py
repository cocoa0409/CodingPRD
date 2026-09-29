"""
The optimistic-concurrency version echo on the four ledger-mutating writes, the
per-mutation version counter, and the immediate visibility of a cascade and of a
compensation in the mutating response itself (PRD Sections 2.4, 2.7, 3.6, 3.7).

Every test here translates one instance of the corner-case index sections
`cross_cutting_complexity_layers` and `consistency_model`.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import (
    ANALYST,
    LABEL_ADMIN,
    make_partner_headers,
    DEFAULT_CLOCK_INSTANT,
    INITIAL_VERSION,
    DEAL_STATUS_EXECUTED,
    FORMAT_DIGITAL,
    FORMAT_VINYL,
    RECOUPMENT_STATUS_RECOUPED,
    RECOUPMENT_STATUS_UNRECOUPED,
    RELEASE_STATUS_RELEASED,
    REPORT_STATUS_ACCEPTED,
    REPORT_STATUS_DISPUTED,
    REPORT_STATUS_SUBMITTED,
    RESERVE_STATUS_HELD,
    RESERVE_STATUS_PARTIALLY_LIQUIDATED,
    RUN_STATUS_SHIPPED,
    VARIANT_CROSS_COLLATERALIZED,
    ERR_STALE_DEAL_VERSION,
    ERR_STALE_RUN_VERSION,
    assert_advance_conserved,
    assert_field,
    assert_field_money,
    assert_fields_money,
    assert_instant_equals,
    assert_null,
    assert_pct_equals,
    assert_reserve_conserved,
    assert_status,
    assert_version_is,
    deal_version,
    do_liquidate,
    do_manufacture,
    do_ship,
    do_submit_report,
    find_by_id,
    given_accepted_report,
    given_active_agreement,
    given_rate_cards,
    given_released_catalog,
    given_submitted_report,
    mk_artist,
    mk_distributor,
    mk_line,
    mk_rate_card,
    mk_report,
    mk_run,
    read_agreement,
    read_deal,
    read_release,
    read_release_lines,
    read_report,
    read_run,
    validate_list,
)

ESCALATING_AGREEMENT = {
    "royalty_rate_pct": "0.1000",
    "escalated_royalty_rate_pct": "0.1500",
    "advance_amount_cents": 0,
    "recording_costs_cents": 0,
    "recording_recoupable_pct": "0.0000",
    "marketing_recoup_share_pct": "0.0000",
}


def _two_submitted_reports(api):
    """One EXECUTED deal carrying a 500,000-cent advance and two SUBMITTED
    reports for disjoint quarters, each priced at 100,000 gross / 85,000 net."""
    ctx = given_released_catalog(
        api,
        deal_kw={"advance_amount_cents": 500000, "cross_collateralized": True,
                 "objection_window_days": 30, "post_term_collection_days": 90},
        releases=[{"advance_share_cents": 500000, "title": "Version Echo"}],
    )
    ctx = given_rate_cards(api, ctx)
    partner = ctx["partner_headers"]

    report_a = mk_report(
        api, ctx["deal_id"], partner,
        period_start="2026-01-01", period_end="2026-03-31")
    mk_line(api, report_a["id"], ctx["release_id"], partner, stream_count=250000)
    do_submit_report(api, report_a["id"], partner)

    report_b = mk_report(
        api, ctx["deal_id"], partner,
        period_start="2026-04-01", period_end="2026-06-30")
    mk_line(api, report_b["id"], ctx["release_id"], partner, stream_count=250000)
    do_submit_report(api, report_b["id"], partner)

    return ctx, report_a["id"], report_b["id"]


def test_a_replayed_deal_version_is_refused_on_the_second_report_accept(api):
    """"If any other writer ... has advanced the deal's version since the caller
    read it, the acceptance is rejected with ERR_STALE_DEAL_VERSION (HTTP 412)",
    and "Re-reading the deal and retrying with the fresh version succeeds". Each
    accept applies 85,000 of the 500,000 advance, so the retry leaves
    advance_recouped_cents at 170,000 and unrecouped_advance_cents at 330,000.

    Design: Corner/cross_cutting_complexity_layers/stale_deal_version_rejects_the_second_accept
    """
    ctx, report_a, report_b = _two_submitted_reports(api)
    version_0 = deal_version(api, ctx["deal_id"], headers=ANALYST)

    accepted_a = validate_success(
        api.accept_report(report_a, f.accept_report_payload(version_0), ANALYST),
        200)
    assert_status(accepted_a, REPORT_STATUS_ACCEPTED)
    assert_field_money(accepted_a, "advance_applied_cents", 85000)

    validate_error(
        api.accept_report(report_b, f.accept_report_payload(version_0), ANALYST),
        ERR_STALE_DEAL_VERSION)

    untouched = read_report(api, report_b, headers=ANALYST)
    assert_status(untouched, REPORT_STATUS_SUBMITTED)
    assert_field_money(untouched, "advance_applied_cents", 0)
    deal_1 = read_deal(api, ctx["deal_id"], headers=ANALYST)
    assert_field_money(deal_1, "advance_recouped_cents", 85000)
    assert_version_is(deal_1, version_0 + 1, "distribution deal")

    accepted_b = validate_success(
        api.accept_report(
            report_b, f.accept_report_payload(deal_1["version"]), ANALYST),
        200)
    assert_status(accepted_b, REPORT_STATUS_ACCEPTED)
    assert_field_money(accepted_b, "advance_applied_cents", 85000)

    deal_2 = read_deal(api, ctx["deal_id"], headers=ANALYST)
    assert_version_is(deal_2, deal_1["version"] + 1, "distribution deal")
    assert_fields_money(
        deal_2,
        net_receipts_to_date_cents=170000,
        advance_recouped_cents=170000,
        unrecouped_advance_cents=330000,
    )
    assert_advance_conserved(deal_2)


def test_a_stale_deal_version_is_refused_on_the_dispute_reversal(api):
    """The reverse channel carries the same guard: "the request must supply
    expected_deal_version matching the deal's current version, and a mismatch is
    rejected with ERR_STALE_DEAL_VERSION (HTTP 412)". "Disputing report A remains
    legitimate whether or not report B has since been accepted", and the refreshed
    retry reverses exactly report A's 85,000, leaving 415,000 outstanding.

    Design: Corner/cross_cutting_complexity_layers/stale_deal_version_rejects_the_dispute_reversal
    """
    ctx, report_a, report_b = _two_submitted_reports(api)
    version_0 = deal_version(api, ctx["deal_id"], headers=ANALYST)
    validate_success(
        api.accept_report(report_a, f.accept_report_payload(version_0), ANALYST),
        200)
    version_1 = deal_version(api, ctx["deal_id"], headers=ANALYST)

    accepted_b = validate_success(
        api.accept_report(report_b, f.accept_report_payload(version_1), ANALYST),
        200)
    assert_status(accepted_b, REPORT_STATUS_ACCEPTED)

    reason = "Territory split misreported for the January period."
    validate_error(
        api.dispute_report(
            report_a, f.dispute_report_payload(version_1, reason), ANALYST),
        ERR_STALE_DEAL_VERSION)

    untouched = read_report(api, report_a, headers=ANALYST)
    assert_status(untouched, REPORT_STATUS_ACCEPTED)
    assert_field_money(untouched, "advance_applied_cents", 85000)
    deal_2 = read_deal(api, ctx["deal_id"], headers=ANALYST)
    assert_field_money(deal_2, "advance_recouped_cents", 170000)
    assert_version_is(deal_2, version_1 + 1, "distribution deal")

    disputed = validate_success(
        api.dispute_report(
            report_a, f.dispute_report_payload(deal_2["version"], reason), ANALYST),
        200)
    assert_status(disputed, REPORT_STATUS_DISPUTED)
    assert_field_money(disputed, "advance_applied_cents", 0)

    deal_3 = read_deal(api, ctx["deal_id"], headers=ANALYST)
    assert_version_is(deal_3, deal_2["version"] + 1, "distribution deal")
    assert_fields_money(
        deal_3,
        net_receipts_to_date_cents=85000,
        advance_recouped_cents=85000,
        unrecouped_advance_cents=415000,
    )
    assert_advance_conserved(deal_3)


def _shipped_vinyl_run(api, unit_manufacturing_cost_cents=300):
    """A SHIPPED run: 1,000 pressed, 900 shipped at 1,000 cents wholesale on a
    0.1000 reserve, so reserve_initial_cents is 900 * 1000 * 0.1000 = 90,000."""
    ctx = given_released_catalog(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        releases=[{"formats": (FORMAT_DIGITAL, FORMAT_VINYL),
                   "title": "Pressing Plant"}],
    )
    run = mk_run(
        api, ctx["release_id"], ctx["dist_id"],
        units_planned=1000,
        unit_manufacturing_cost_cents=unit_manufacturing_cost_cents,
        window_start="2026-03-01", window_end="2026-05-31",
        returns_reserve_pct=f.pct4("0.1000"))
    do_manufacture(api, run["id"], 1000)
    shipped = do_ship(api, run["id"], 900, 1000, ctx["partner_headers"])
    return ctx, shipped


def test_a_replayed_run_version_is_refused_on_the_second_liquidation(api):
    """The reserve guard hangs off a different parent and a different error id:
    "The request must therefore carry expected_run_version matching the current
    version of the PhysicalRun ...; a mismatch is rejected with
    ERR_STALE_RUN_VERSION (HTTP 412)". "the percentage always applies to
    reserve_initial_cents", so 0.3000 then 0.2000 of 90,000 release 27,000 then
    18,000, leaving 45,000 held - the 412 is not a fiscal-ceiling refusal.

    Design: Corner/cross_cutting_complexity_layers/stale_run_version_rejects_the_second_liquidation
    """
    ctx, shipped = _shipped_vinyl_run(api)
    assert_field_money(shipped, "reserve_initial_cents", 90000)
    assert_status(shipped, RESERVE_STATUS_HELD, "reserve_status")
    version_0 = shipped["version"]

    first = validate_success(
        api.liquidate_reserve(
            shipped["id"], f.liquidate_payload(version_0, f.pct4("0.3000")),
            ANALYST),
        200)
    assert_fields_money(
        first, reserve_held_cents=63000, reserve_liquidated_cents=27000)
    assert_status(first, RESERVE_STATUS_PARTIALLY_LIQUIDATED, "reserve_status")

    validate_error(
        api.liquidate_reserve(
            shipped["id"], f.liquidate_payload(version_0, f.pct4("0.2000")),
            ANALYST),
        ERR_STALE_RUN_VERSION)

    refreshed = read_run(api, shipped["id"], headers=ANALYST)
    assert_field_money(refreshed, "reserve_held_cents", 63000)
    assert_version_is(refreshed, version_0 + 1, "physical run")

    second = validate_success(
        api.liquidate_reserve(
            shipped["id"],
            f.liquidate_payload(refreshed["version"], f.pct4("0.2000")),
            ANALYST),
        200)
    assert_fields_money(
        second,
        reserve_initial_cents=90000,
        reserve_held_cents=45000,
        reserve_liquidated_cents=45000,
    )
    assert_status(second, RESERVE_STATUS_PARTIALLY_LIQUIDATED, "reserve_status")
    assert_status(second, RUN_STATUS_SHIPPED)
    assert_version_is(second, refreshed["version"] + 1, "physical run")
    assert_reserve_conserved(second)


def test_a_stale_run_version_is_refused_when_voiding_a_liquidation(api):
    """Voiding takes the echo as its whole payload: "expected_run_version must
    match the run's current version, and a mismatch is rejected with
    ERR_STALE_RUN_VERSION (HTTP 412)". The refreshed retry pulls back every
    liquidated cent at once - "reserve_liquidated_cents returns to
    reserve_held_cents and is set to 0" - restoring 90,000 held from 45,000.

    Design: Corner/cross_cutting_complexity_layers/stale_run_version_rejects_the_void_reversal
    """
    ctx, shipped = _shipped_vinyl_run(api)
    first = do_liquidate(api, shipped["id"], shipped["version"], f.pct4("0.3000"))
    assert_field_money(first, "reserve_liquidated_cents", 27000)
    version_1 = first["version"]

    second = validate_success(
        api.liquidate_reserve(
            shipped["id"], f.liquidate_payload(version_1, f.pct4("0.2000")),
            ANALYST),
        200)
    assert_field_money(second, "reserve_liquidated_cents", 45000)
    assert_version_is(second, version_1 + 1, "physical run")

    validate_error(
        api.void_liquidation(
            shipped["id"], f.void_liquidation_payload(version_1), ANALYST),
        ERR_STALE_RUN_VERSION)

    refreshed = read_run(api, shipped["id"], headers=ANALYST)
    assert_field_money(refreshed, "reserve_liquidated_cents", 45000)
    assert_status(refreshed, RESERVE_STATUS_PARTIALLY_LIQUIDATED, "reserve_status")
    assert_version_is(refreshed, second["version"], "physical run")

    voided = validate_success(
        api.void_liquidation(
            shipped["id"],
            f.void_liquidation_payload(refreshed["version"]), ANALYST),
        200)
    assert_fields_money(
        voided,
        reserve_initial_cents=90000,
        reserve_held_cents=90000,
        reserve_liquidated_cents=0,
    )
    assert_status(voided, RESERVE_STATUS_HELD, "reserve_status")
    assert_status(voided, RUN_STATUS_SHIPPED)
    assert_version_is(voided, refreshed["version"] + 1, "physical run")
    assert_reserve_conserved(voided)


def test_a_physical_runs_version_advances_by_one_per_accepted_write(api):
    """"version is an integer that begins at 1 when the record is created and
    increases by exactly 1 on every mutation of that record". A six-hop walk pins
    the sequence 1..6 across create, manufacture, ship, the record-returns
    self-loop, liquidate and void, and a plain GET in between advances nothing.
    45 returns of 900 shipped is a returns_rate of 0.0500.

    Design: Corner/cross_cutting_complexity_layers/every_mutation_advances_the_version_by_exactly_one
    """
    ctx = given_released_catalog(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        releases=[{"formats": (FORMAT_DIGITAL, FORMAT_VINYL),
                   "title": "Six Hop Walk"}],
    )
    partner = ctx["partner_headers"]

    run = validate_success(
        api.create_run(
            f.run_payload(
                ctx["release_id"], ctx["dist_id"], units_planned=1000,
                unit_manufacturing_cost_cents=300,
                window_start="2026-03-01", window_end="2026-05-31",
                returns_reserve_pct=f.pct4("0.1000")),
            LABEL_ADMIN),
        201)
    assert_version_is(run, INITIAL_VERSION, "physical run")

    read_back = validate_success(api.get_run(run["id"], ANALYST), 200)
    assert_version_is(read_back, INITIAL_VERSION, "physical run")

    manufactured = validate_success(
        api.manufacture_run(run["id"], f.manufacture_payload(1000), LABEL_ADMIN),
        200)
    assert_version_is(manufactured, 2, "physical run")

    shipped = validate_success(
        api.ship_run(run["id"], f.ship_payload(900, 1000), partner), 200)
    assert_version_is(shipped, 3, "physical run")

    returned = validate_success(
        api.record_returns(run["id"], f.record_returns_payload(45), partner), 200)
    assert_version_is(returned, 4, "physical run")
    assert_status(returned, RUN_STATUS_SHIPPED)
    assert_pct_equals(returned["returns_rate"], f.pct4("0.0500"), "returns_rate")

    liquidated = validate_success(
        api.liquidate_reserve(
            run["id"],
            f.liquidate_payload(returned["version"], f.pct4("0.5000")), ANALYST),
        200)
    assert_version_is(liquidated, 5, "physical run")

    voided = validate_success(
        api.void_liquidation(
            run["id"], f.void_liquidation_payload(liquidated["version"]), ANALYST),
        200)
    assert_version_is(voided, 6, "physical run")
    assert_status(voided, RESERVE_STATUS_HELD, "reserve_status")


def test_deal_and_release_versions_advance_by_one_including_on_a_cascade(api):
    """The same convention holds on the other entity families, "including
    mutations a record suffers as a side effect of an operation aimed at some
    other record". A deal is 1 on create and 2 on execute; a release is 1 on
    create and 2 on going to market; the accept cascade then bumps both to 3,
    since "each cascaded release and agreement bumps its own version as well".

    Design: Corner/cross_cutting_complexity_layers/every_mutation_advances_the_version_by_exactly_one
    """
    distributor = mk_distributor(api, default_returns_reserve_pct=f.pct4("0.1000"))
    artist = mk_artist(api)
    mk_rate_card(api)
    partner = make_partner_headers(distributor["id"])

    deal = validate_success(
        api.create_deal(
            f.deal_payload(
                distributor["id"], advance_amount_cents=500000,
                objection_window_days=30, post_term_collection_days=90),
            LABEL_ADMIN),
        201)
    assert_version_is(deal, INITIAL_VERSION, "distribution deal")

    release = validate_success(
        api.create_release(
            f.release_payload(
                deal["id"], artist["id"], title="Cascade Counter",
                advance_share_cents=500000),
            LABEL_ADMIN),
        201)
    assert_version_is(release, INITIAL_VERSION, "release")

    executed = validate_success(
        api.execute_deal(deal["id"], f.execute_payload(), LABEL_ADMIN), 200)
    assert_status(executed, DEAL_STATUS_EXECUTED)
    assert_version_is(executed, 2, "distribution deal")

    unchanged = validate_success(api.get_deal(deal["id"], ANALYST), 200)
    assert_version_is(unchanged, 2, "distribution deal")

    marketed = validate_success(
        api.release_to_market(
            release["id"], f.release_to_market_payload(), LABEL_ADMIN),
        200)
    assert_status(marketed, RELEASE_STATUS_RELEASED)
    assert_version_is(marketed, 2, "release")

    report = mk_report(api, deal["id"], partner)
    mk_line(api, report["id"], release["id"], partner, stream_count=250000)
    do_submit_report(api, report["id"], partner)
    accepted = validate_success(
        api.accept_report(
            report["id"], f.accept_report_payload(2), ANALYST),
        200)
    assert_status(accepted, REPORT_STATUS_ACCEPTED)

    deal_after = read_deal(api, deal["id"], headers=ANALYST)
    assert_version_is(deal_after, 3, "distribution deal")
    release_after = read_release(api, release["id"], headers=ANALYST)
    assert_version_is(release_after, 3, "release")
    assert_field_money(release_after, "net_receipts_to_date_cents", 85000)


def test_the_accept_response_and_every_downstream_read_agree_immediately(api):
    """The accept's own 200 body already carries the settlement - "Acceptance
    stamps accepted_at from the logical clock and then runs a five-hop cascade" -
    and the deepest hop is visible on the very next read: under a RECOUPED deal
    "every one of those agreements now pays escalated_royalty_rate_pct". 85,000
    net fully recoups a 50,000 advance and leaves 35,000 of excess.

    Design: Corner/consistency_model/cascade_is_visible_in_the_mutation_response_itself
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"advance_amount_cents": 50000, "cross_collateralized": True,
                 "objection_window_days": 30, "post_term_collection_days": 90},
        releases=[{"advance_share_cents": 50000, "title": "Immediate Cascade"}],
    )
    ctx = given_active_agreement(api, ctx, agreement_kw=ESCALATING_AGREEMENT)
    ctx = given_submitted_report(api, ctx, lines=[{"stream_count": 250000}])

    before_lines = read_release_lines(api, ctx["release_id"], headers=ANALYST)
    assert_null(before_lines[0], "net_receipts_cents")
    before_agreement = read_agreement(api, ctx["agreement_id"], headers=ANALYST)
    assert_pct_equals(
        before_agreement["active_royalty_rate_pct"], f.pct4("0.1000"),
        "active_royalty_rate_pct")

    version = deal_version(api, ctx["deal_id"], headers=ANALYST)
    accepted = validate_success(
        api.accept_report(
            ctx["report_id"], f.accept_report_payload(version), ANALYST),
        200)
    assert_status(accepted, REPORT_STATUS_ACCEPTED)
    assert_fields_money(
        accepted,
        gross_receipts_cents=100000,
        distributor_share_cents=15000,
        net_receipts_cents=85000,
        advance_applied_cents=50000,
    )
    assert_instant_equals(
        accepted["accepted_at"], DEFAULT_CLOCK_INSTANT, "accepted_at")

    deal = read_deal(api, ctx["deal_id"], headers=ANALYST)
    assert_fields_money(
        deal,
        net_receipts_to_date_cents=85000,
        advance_recouped_cents=50000,
        unrecouped_advance_cents=0,
        post_recoupment_net_receipts_cents=35000,
    )
    assert_field(deal, "recoupment_status", RECOUPMENT_STATUS_RECOUPED)
    assert_advance_conserved(deal)

    release = read_release(api, ctx["release_id"], headers=ANALYST)
    assert_fields_money(
        release,
        net_receipts_to_date_cents=85000,
        release_advance_recouped_cents=50000,
        unrecouped_advance_share_cents=0,
    )

    lines, _meta = validate_list(
        api.list_release_revenue_lines(ctx["release_id"], ANALYST))
    assert_field_money(lines[0], "net_receipts_cents", 85000)

    agreement = read_agreement(api, ctx["agreement_id"], headers=ANALYST)
    assert_pct_equals(
        agreement["active_royalty_rate_pct"], f.pct4("0.1500"),
        "active_royalty_rate_pct")

    summary = validate_success(
        api.get_recoupment_summary(
            ctx["deal_id"], ANALYST, variant=VARIANT_CROSS_COLLATERALIZED),
        200)
    assert_field(summary, "variant", VARIANT_CROSS_COLLATERALIZED)
    assert_fields_money(
        summary,
        pool_net_receipts_cents=85000,
        advance_amount_cents=50000,
        advance_applied_cents=50000,
        unrecouped_advance_cents=0,
        post_recoupment_net_receipts_cents=35000,
    )
    assert_field(summary, "recoupment_status", RECOUPMENT_STATUS_RECOUPED)


def test_the_dispute_response_shows_the_unwound_ledger_immediately(api):
    """The compensation is visible in the request that caused it: the dispute
    "zeroes the report's own advance_applied_cents", and "when
    unrecouped_advance_cents becomes positive again ... every affected agreement's
    active_royalty_rate_pct reverts to its royalty_rate_pct". The run's own reserve
    is untouched, since the compensation never reaches the PhysicalRun.

    Design: Corner/consistency_model/compensation_is_visible_in_the_mutation_response_itself
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"advance_amount_cents": 50000, "cross_collateralized": True,
                 "objection_window_days": 30, "post_term_collection_days": 90},
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        releases=[{"formats": (FORMAT_DIGITAL, FORMAT_VINYL),
                   "advance_share_cents": 50000, "title": "Unwound"}],
    )
    ctx = given_active_agreement(api, ctx, agreement_kw=ESCALATING_AGREEMENT)
    ctx = given_accepted_report(api, ctx, lines=[{"stream_count": 250000}])

    run = mk_run(
        api, ctx["release_id"], ctx["dist_id"], units_planned=1000,
        unit_manufacturing_cost_cents=1000,
        window_start="2026-03-01", window_end="2026-05-31",
        returns_reserve_pct=f.pct4("0.1000"))
    do_manufacture(api, run["id"], 1000)
    shipped = do_ship(api, run["id"], 900, 1000, ctx["partner_headers"])
    assert_fields_money(
        shipped, physical_net_receipts_cents=0, reserve_initial_cents=90000)
    liquidated = do_liquidate(
        api, run["id"], shipped["version"], f.pct4("0.3000"))
    assert_field_money(liquidated, "reserve_held_cents", 63000)

    before = read_deal(api, ctx["deal_id"], headers=ANALYST)
    assert_field_money(before, "advance_recouped_cents", 50000)
    assert_field(before, "recoupment_status", RECOUPMENT_STATUS_RECOUPED)

    reason = "Premium tier streams double-counted for the quarter."
    disputed = validate_success(
        api.dispute_report(
            ctx["report_id"],
            f.dispute_report_payload(before["version"], reason), ANALYST),
        200)
    assert_status(disputed, REPORT_STATUS_DISPUTED)
    assert_field_money(disputed, "advance_applied_cents", 0)
    assert_field(disputed, "dispute_reason", reason)

    deal_after = read_deal(api, ctx["deal_id"], headers=ANALYST)
    assert_fields_money(
        deal_after,
        net_receipts_to_date_cents=0,
        advance_recouped_cents=0,
        unrecouped_advance_cents=50000,
        post_recoupment_net_receipts_cents=0,
    )
    assert_field(deal_after, "recoupment_status", RECOUPMENT_STATUS_UNRECOUPED)
    assert_advance_conserved(deal_after)

    lines, _meta = validate_list(
        api.list_release_revenue_lines(ctx["release_id"], ANALYST))
    assert_null(lines[0], "net_receipts_cents")

    agreement = read_agreement(api, ctx["agreement_id"], headers=ANALYST)
    assert_pct_equals(
        agreement["active_royalty_rate_pct"], f.pct4("0.1000"),
        "active_royalty_rate_pct")

    run_after = read_run(api, run["id"], headers=ANALYST)
    assert_field_money(run_after, "reserve_held_cents", 63000)
    assert_version_is(run_after, liquidated["version"], "physical run")


def test_the_void_response_shows_the_restored_reserve_immediately(api):
    """The other compensating action is equally immediate: voiding means
    "reserve_liquidated_cents returns to reserve_held_cents and is set to 0, the
    axis returns to HELD, and reserve_initial_cents is unchanged" - all of it in
    the void's own body - and the reserve_status-filtered listing serves the
    restored 90,000 in the same breath.

    Design: Corner/consistency_model/compensation_is_visible_in_the_mutation_response_itself
    """
    ctx, shipped = _shipped_vinyl_run(api)
    liquidated = do_liquidate(
        api, shipped["id"], shipped["version"], f.pct4("0.3000"))
    assert_fields_money(
        liquidated, reserve_held_cents=63000, reserve_liquidated_cents=27000)
    assert_status(
        liquidated, RESERVE_STATUS_PARTIALLY_LIQUIDATED, "reserve_status")

    voided = validate_success(
        api.void_liquidation(
            shipped["id"],
            f.void_liquidation_payload(liquidated["version"]), ANALYST),
        200)
    assert_fields_money(
        voided,
        reserve_initial_cents=90000,
        reserve_held_cents=90000,
        reserve_liquidated_cents=0,
    )
    assert_status(voided, RESERVE_STATUS_HELD, "reserve_status")
    assert_status(voided, RUN_STATUS_SHIPPED)
    assert_reserve_conserved(voided)

    runs, _meta = validate_list(
        api.list_runs(
            ANALYST,
            {"release_id": ctx["release_id"],
             "reserve_status": RESERVE_STATUS_HELD}))
    listed = find_by_id(runs, shipped["id"])
    assert_field_money(listed, "reserve_held_cents", 90000)
    assert_status(listed, RESERVE_STATUS_HELD, "reserve_status")
    assert_version_is(listed, voided["version"], "physical run")
