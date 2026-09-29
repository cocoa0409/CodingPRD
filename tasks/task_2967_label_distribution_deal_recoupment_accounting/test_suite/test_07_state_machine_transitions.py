"""
The declared state machines of the deal, the release, the agreement, the
marketing spend, the revenue report, the physical run and the artist statement:
initial states, guarded edges, forks that rejoin, cross-entity cascades,
idempotency and terminal lockdown (PRD Sections 2.4, 2.8, 3.1-3.4, 3.7-3.9).

Every test here translates one instance of the corner-case index section
`state_machines`.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import (
    AGREEMENT_STATUS_ACTIVE,
    AGREEMENT_STATUS_DRAFT,
    AGREEMENT_STATUS_SUPERSEDED,
    AGREEMENT_STATUS_TERMINATED,
    ANALYST,
    AUDIT_COST_BEARER_ARTIST,
    AUDIT_STATUS_DENIED,
    AUDIT_STATUS_NONE,
    AUDIT_STATUS_REQUESTED,
    BASIS_VARIANT_FINAL,
    BASIS_VARIANT_PROVISIONAL,
    BIZ_AFFAIRS,
    DEAL_STATUS_CLOSED,
    DEAL_STATUS_DRAFT,
    DEAL_STATUS_EXECUTED,
    DEAL_STATUS_EXPIRED,
    DEAL_STATUS_POST_TERM_COLLECTION,
    DEAL_STATUS_TERMINATION_NOTICE,
    DEFAULT_CLOCK_INSTANT,
    ERR_INVALID_AGREEMENT_STATE,
    ERR_INVALID_DEAL_STATE,
    ERR_INVALID_RELEASE_STATE,
    ERR_INVALID_REPORT_STATE,
    ERR_INVALID_RUN_STATE,
    ERR_INVALID_SPEND_STATE,
    ERR_INVALID_STATEMENT_STATE,
    ERR_PERIOD_OUTSIDE_TERM,
    FORMAT_CD,
    FORMAT_DIGITAL,
    FORMAT_VINYL,
    INITIAL_VERSION,
    LABEL_ADMIN,
    RECOUPABILITY_FULL,
    RECOUPMENT_STATUS_RECOUPED,
    RECOUPMENT_STATUS_UNRECOUPED,
    RELEASE_STATUS_PLANNED,
    RELEASE_STATUS_RELEASED,
    RELEASE_STATUS_REVERSION_PENDING,
    RELEASE_STATUS_REVERTED,
    REPORT_STATUS_DRAFT,
    RESERVE_STATUS_HELD,
    RESERVE_STATUS_LIQUIDATED,
    RESERVE_STATUS_PARTIALLY_LIQUIDATED,
    RUN_STATUS_MANUFACTURED,
    RUN_STATUS_PLANNED,
    RUN_STATUS_RECONCILED,
    RUN_STATUS_SHIPPED,
    SPEND_CATEGORY_DIGITAL_ADS,
    SPEND_CATEGORY_PUBLICITY,
    SPEND_CATEGORY_RADIO_PROMO,
    SPEND_DECISION_APPROVE,
    SPEND_DECISION_REJECT,
    SPEND_DECISION_REQUEST_REVISION,
    SPEND_STATUS_APPROVED,
    SPEND_STATUS_DRAFT,
    SPEND_STATUS_REJECTED,
    SPEND_STATUS_REVISION_REQUESTED,
    SPEND_STATUS_SETTLED,
    SPEND_STATUS_SUBMITTED,
    SPEND_STATUS_VOIDED,
    STATEMENT_STATUS_DRAFT,
    STATEMENT_STATUS_FINALIZED,
    STATEMENT_STATUS_PREPARED,
    STATEMENT_STATUS_VOIDED,
    assert_date,
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
    do_activate_agreement,
    do_close_deal,
    do_decide_spend,
    do_enter_post_term_collection,
    do_execute_deal,
    do_finalize_statement,
    do_issue_statement,
    do_manufacture,
    do_prepare_statement,
    do_record_returns,
    do_request_audit,
    do_set_clock,
    do_settle_spend,
    do_ship,
    do_submit_spend,
    do_terminate_deal,
    find_by_id,
    given_active_agreement,
    given_draft_deal,
    given_executed_deal,
    given_released_catalog,
    mk_agreement,
    mk_deal,
    mk_release,
    mk_report,
    mk_run,
    mk_spend,
    mk_statement,
    read_agreement,
    read_artist,
    read_deal,
    read_release,
    read_report,
    read_run,
    read_spend,
    read_statement,
    run_version,
    validate_list,
)

CLOCK_DATE = "2026-08-01"


def test_freshly_created_deal_release_agreement_and_spend_sit_at_their_initial_states(api):
    """"A freshly created deal has status `DRAFT`", "A new release has status
    `PLANNED`", "A drafted agreement has status `DRAFT`, a null
    `active_royalty_rate_pct` ... and both recoupment balances ... sitting at 0"
    and "A new spend has status `DRAFT`". Four dimensions on four freshly created
    rows, every derived counter at 0 and every lifecycle stamp null, with the
    spend's `recoupability` at `FULLY_RECOUPABLE` because its category is
    `DIGITAL_ADS`.

    Design: Corner/state_machines/initial_state_of_every_state_machine_dimension
    """
    ctx = given_draft_deal(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 500000,
        },
        releases=[
            {
                "title": "Initial State A",
                "planned_release_date": "2026-03-01",
                "formats": (FORMAT_DIGITAL, FORMAT_VINYL),
            }
        ],
    )
    agreement = mk_agreement(
        api,
        ctx["artist_id"],
        ctx["release_id"],
        advance_amount_cents=150000,
        recording_costs_cents=100000,
        recording_recoupable_pct=f.pct4("0.5000"),
    )
    spend = mk_spend(
        api,
        ctx["release_id"],
        category=SPEND_CATEGORY_DIGITAL_ADS,
        amount_cents=100000,
        vendor="Northline Media",
    )

    deal = validate_success(api.get_deal(ctx["deal_id"], LABEL_ADMIN), 200)
    assert_status(deal, DEAL_STATUS_DRAFT)
    assert_version_is(deal, INITIAL_VERSION, entity="deal")
    assert_null(
        deal,
        "advance_payment_reference",
        "executed_at",
        "termination_effective_date",
        "post_term_collection_end_date",
    )
    assert_field(deal, "recoupment_status", RECOUPMENT_STATUS_UNRECOUPED)
    assert_fields_money(
        deal,
        advance_recouped_cents=0,
        unrecouped_advance_cents=0,
        net_receipts_to_date_cents=0,
        post_recoupment_net_receipts_cents=0,
        marketing_committed_cents=0,
    )

    release = validate_success(api.get_release(ctx["release_id"], LABEL_ADMIN), 200)
    assert_status(release, RELEASE_STATUS_PLANNED)
    assert_version_is(release, INITIAL_VERSION, entity="release")
    assert_null(release, "actual_release_date", "reversion_eligible_date")
    assert_fields_money(
        release,
        net_receipts_to_date_cents=0,
        release_advance_recouped_cents=0,
        unrecouped_advance_share_cents=0,
        recoupable_marketing_applied_cents=0,
    )

    read_back = validate_success(api.get_agreement(agreement["id"], LABEL_ADMIN), 200)
    assert_status(read_back, AGREEMENT_STATUS_DRAFT)
    assert_version_is(read_back, INITIAL_VERSION, entity="agreement")
    assert_null(
        read_back,
        "active_royalty_rate_pct",
        "proposed_royalty_rate_pct",
        "proposed_advance_amount_cents",
        "post_term_collection_end_date",
    )
    assert_fields_money(
        read_back,
        unrecouped_artist_advance_cents=0,
        unrecouped_recording_cents=0,
    )

    spend_read = validate_success(api.get_spend(spend["id"], LABEL_ADMIN), 200)
    assert_status(spend_read, SPEND_STATUS_DRAFT)
    assert_version_is(spend_read, INITIAL_VERSION, entity="spend")
    assert_null(
        spend_read,
        "requested_by_user_id",
        "decided_by_user_id",
        "approved_at",
        "settled_amount_cents",
        "revision_note",
    )
    assert_field(spend_read, "recoupability", RECOUPABILITY_FULL)


def test_new_physical_run_opens_planned_on_fulfilment_and_held_on_the_money_axis(api):
    """"A new run opens with `status` at `PLANNED` and `reserve_status` at
    `HELD`", and when `returns_reserve_pct` "is omitted it is copied from the
    shipping partner's `default_returns_reserve_pct`". Both dimensions of the same
    row are read at their own initial value and the inherited baseline is 0.1000.

    Design: Corner/state_machines/initial_state_of_every_state_machine_dimension
    """
    ctx = given_draft_deal(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        deal_kw={"distribution_fee_pct": f.pct4("0.1500")},
        releases=[
            {
                "title": "Initial State A",
                "planned_release_date": "2026-03-01",
                "formats": (FORMAT_DIGITAL, FORMAT_VINYL),
            }
        ],
    )
    run = mk_run(
        api,
        ctx["release_id"],
        ctx["dist_id"],
        units_planned=1000,
        unit_manufacturing_cost_cents=250,
        window_start="2026-04-01",
        window_end="2026-06-30",
    )

    read_back = validate_success(api.get_run(run["id"], LABEL_ADMIN), 200)
    assert_status(read_back, RUN_STATUS_PLANNED)
    assert_status(read_back, RESERVE_STATUS_HELD, field="reserve_status")
    assert_version_is(read_back, INITIAL_VERSION, entity="run")
    assert_pct_equals(
        read_back["returns_reserve_pct"], f.pct4("0.1000"), field="returns_reserve_pct"
    )


def test_new_revenue_report_and_new_statement_open_at_their_initial_states(api):
    """A report "begins in `DRAFT` with a null `submitted_by_user_id`, a null
    `accepted_at`, a null `dispute_reason`" and its four money fields at 0, and
    "A new statement is `DRAFT` with `audit_status` at `NONE` and every money
    field zeroed". The statement's second dimension is populated rather than null
    on a brand-new row, and all eight waterfall money fields read 0.

    Design: Corner/state_machines/initial_state_of_every_state_machine_dimension
    """
    ctx = given_executed_deal(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
        },
        releases=[{"title": "Initial State B", "planned_release_date": "2026-03-01"}],
    )
    agreement = mk_agreement(
        api,
        ctx["artist_id"],
        ctx["release_id"],
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.0000"),
    )
    agreement = do_activate_agreement(api, agreement["id"])
    report = mk_report(
        api,
        ctx["deal_id"],
        ctx["partner_headers"],
        period_start="2026-01-01",
        period_end="2026-03-31",
    )
    statement = mk_statement(
        api,
        agreement["id"],
        period_start="2026-01-01",
        period_end="2026-03-31",
        basis_variant=BASIS_VARIANT_PROVISIONAL,
    )

    report_read = validate_success(api.get_report(report["id"], ANALYST), 200)
    assert_status(report_read, REPORT_STATUS_DRAFT)
    assert_version_is(report_read, INITIAL_VERSION, entity="report")
    assert_fields_money(
        report_read,
        gross_receipts_cents=0,
        distributor_share_cents=0,
        net_receipts_cents=0,
        advance_applied_cents=0,
    )
    assert_null(report_read, "submitted_by_user_id", "accepted_at", "dispute_reason")

    statement_read = validate_success(api.get_statement(statement["id"], ANALYST), 200)
    assert_status(statement_read, STATEMENT_STATUS_DRAFT)
    assert_status(statement_read, AUDIT_STATUS_NONE, field="audit_status")
    assert_version_is(statement_read, INITIAL_VERSION, entity="statement")
    assert_fields_money(
        statement_read,
        digital_royalty_base_cents=0,
        physical_royalty_base_cents=0,
        gross_royalty_cents=0,
        advance_applied_cents=0,
        recording_applied_cents=0,
        marketing_applied_cents=0,
        reserve_withheld_cents=0,
        net_payable_cents=0,
    )


def test_for_cause_termination_dates_the_window_off_the_clock_and_moves_the_catalog(api):
    """The for-cause fork "sets `termination_effective_date` to the logical
    clock's calendar date and `post_term_collection_end_date` to that date plus
    the deal's `post_term_collection_days`", then "every release in `RELEASED`
    moves to `REVERSION_PENDING` ... while every release still in `PLANNED` ...
    moves straight to `REVERTED`". At the default clock of 2026-08-01 with a
    90-day tail the window closes 2026-10-30.

    Design: Corner/state_machines/deal_diamond_fork_and_join_both_arms
    """
    ctx = given_released_catalog(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
            "post_term_collection_days": 90,
        },
        releases=[
            {"title": "Fork T Planned", "planned_release_date": "2026-03-01"},
            {"title": "Fork T Released", "planned_release_date": "2026-03-01"},
        ],
        release_indexes=[1],
        actual_release_date="2026-03-01",
    )
    planned_id = ctx["releases"][0]["id"]
    released_id = ctx["releases"][1]["id"]

    deal = validate_success(api.terminate_deal(ctx["deal_id"], LABEL_ADMIN), 200)
    assert_status(deal, DEAL_STATUS_TERMINATION_NOTICE)
    assert_date(
        deal["termination_effective_date"], CLOCK_DATE, field="termination_effective_date"
    )
    assert_date(
        deal["post_term_collection_end_date"],
        "2026-10-30",
        field="post_term_collection_end_date",
    )

    went_to_market = read_release(api, released_id)
    assert_status(went_to_market, RELEASE_STATUS_REVERSION_PENDING)
    assert_date(
        went_to_market["reversion_eligible_date"],
        "2026-10-30",
        field="reversion_eligible_date",
    )

    never_shipped = read_release(api, planned_id)
    assert_status(never_shipped, RELEASE_STATUS_REVERTED)


def test_natural_expiry_dates_the_window_off_term_end_and_moves_no_release(api):
    """The natural-expiry fork "sets `post_term_collection_end_date` to
    `term_end_date` plus `post_term_collection_days` and leaves
    `termination_effective_date` null", and "every release in `PLANNED` or
    `RELEASED` receives `reversion_eligible_date`, but **no release changes
    state**". A term ending 2026-06-30 with a 90-day tail closes 2026-09-28.

    Design: Corner/state_machines/deal_diamond_fork_and_join_both_arms
    """
    ctx = given_released_catalog(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-06-30",
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
            "post_term_collection_days": 90,
        },
        releases=[
            {"title": "Fork E Planned", "planned_release_date": "2026-03-01"},
            {"title": "Fork E Released", "planned_release_date": "2026-03-01"},
        ],
        release_indexes=[1],
        actual_release_date="2026-03-01",
    )
    planned_id = ctx["releases"][0]["id"]
    released_id = ctx["releases"][1]["id"]

    deal = validate_success(api.expire_deal(ctx["deal_id"], LABEL_ADMIN), 200)
    assert_status(deal, DEAL_STATUS_EXPIRED)
    assert_null(deal, "termination_effective_date")
    assert_date(
        deal["post_term_collection_end_date"],
        "2026-09-28",
        field="post_term_collection_end_date",
    )

    still_planned = read_release(api, planned_id)
    assert_status(still_planned, RELEASE_STATUS_PLANNED)
    assert_date(
        still_planned["reversion_eligible_date"],
        "2026-09-28",
        field="reversion_eligible_date",
    )

    still_released = read_release(api, released_id)
    assert_status(still_released, RELEASE_STATUS_RELEASED)
    assert_date(
        still_released["reversion_eligible_date"],
        "2026-09-28",
        field="reversion_eligible_date",
    )


def test_both_deal_forks_join_at_post_term_collection_without_normalising_the_arms(api):
    """"Entering post-term collection moves the deal `TERMINATION_NOTICE →
    POST_TERM_COLLECTION` or `EXPIRED → POST_TERM_COLLECTION` with identical
    preconditions and identical side effects from either side." Both arms reach the
    join, yet the terminated deal keeps `termination_effective_date` 2026-08-01
    while the expired deal keeps it null.

    Design: Corner/state_machines/deal_diamond_fork_and_join_both_arms
    """
    ctx = given_executed_deal(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
            "post_term_collection_days": 90,
        },
        releases=[{"title": "Fork T Planned", "planned_release_date": "2026-03-01"}],
        advance_payment_reference="WIRE-T",
    )
    deal_e = mk_deal(
        api,
        ctx["dist_id"],
        distribution_fee_pct=f.pct4("0.1500"),
        term_start_date="2026-01-01",
        term_end_date="2026-06-30",
        advance_amount_cents=0,
        marketing_budget_cents=0,
        post_term_collection_days=90,
    )
    mk_release(
        api,
        deal_e["id"],
        ctx["artist_id"],
        title="Fork E Planned",
        planned_release_date="2026-03-01",
    )
    do_execute_deal(api, deal_e["id"], advance_payment_reference="WIRE-E")

    do_terminate_deal(api, ctx["deal_id"])
    expired = validate_success(api.expire_deal(deal_e["id"], LABEL_ADMIN), 200)
    assert_status(expired, DEAL_STATUS_EXPIRED)

    joined_from_notice = validate_success(
        api.enter_post_term_collection(ctx["deal_id"], LABEL_ADMIN), 200
    )
    joined_from_expiry = validate_success(
        api.enter_post_term_collection(deal_e["id"], LABEL_ADMIN), 200
    )
    assert_status(joined_from_notice, DEAL_STATUS_POST_TERM_COLLECTION)
    assert_status(joined_from_expiry, DEAL_STATUS_POST_TERM_COLLECTION)
    assert_date(
        joined_from_notice["termination_effective_date"],
        CLOCK_DATE,
        field="termination_effective_date",
    )
    assert_null(joined_from_expiry, "termination_effective_date")


def test_deal_state_outranks_the_street_date_window_when_promoting_a_release(api):
    """"A caller who echoes a stale parent version *and* targets a record in the
    wrong state receives the 412, not the 409" states the ladder principle, and
    here rank 8 `ERR_INVALID_DEAL_STATE` precedes rank 10
    `ERR_PERIOD_OUTSIDE_TERM`. The identical 2027-01-05 payload changes error class
    from 409 to 422 purely because the deal moved `DRAFT → EXECUTED`.

    Design: Corner/state_machines/release_promotion_rejected_outside_term_and_on_a_draft_deal
    """
    ctx = given_draft_deal(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
        },
        releases=[{"title": "Street Date Probe", "planned_release_date": "2026-03-01"}],
    )

    on_draft_deal = api.release_to_market(
        ctx["release_id"], f.release_to_market_payload("2027-01-05"), LABEL_ADMIN
    )
    validate_error(on_draft_deal, ERR_INVALID_DEAL_STATE, 409)

    do_execute_deal(api, ctx["deal_id"], advance_payment_reference="WIRE-CAIRN")

    after_execution = api.release_to_market(
        ctx["release_id"], f.release_to_market_payload("2027-01-05"), LABEL_ADMIN
    )
    validate_error(after_execution, ERR_PERIOD_OUTSIDE_TERM, 422)

    untouched = read_release(api, ctx["release_id"])
    assert_status(untouched, RELEASE_STATUS_PLANNED)
    assert_null(untouched, "actual_release_date")
    assert_version_is(untouched, INITIAL_VERSION, entity="release")


def test_release_promotion_accepts_a_street_date_on_the_terms_inclusive_lower_bound(api):
    """"The supplied `actual_release_date` must itself fall on or between the
    deal's `term_start_date` and `term_end_date`", so a street date exactly equal
    to `term_start_date` 2026-01-01 is inside the window and promotes the release
    to `RELEASED` with its version stepping from 1 to 2.

    Design: Corner/state_machines/release_promotion_rejected_outside_term_and_on_a_draft_deal
    """
    ctx = given_executed_deal(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
        },
        releases=[{"title": "Street Date Probe", "planned_release_date": "2026-03-01"}],
        advance_payment_reference="WIRE-CAIRN",
    )

    promoted = validate_success(
        api.release_to_market(
            ctx["release_id"], f.release_to_market_payload("2026-01-01"), LABEL_ADMIN
        ),
        200,
    )
    assert_status(promoted, RELEASE_STATUS_RELEASED)
    assert_date(promoted["actual_release_date"], "2026-01-01", field="actual_release_date")
    assert_version_is(promoted, INITIAL_VERSION + 1, entity="release")


def test_execution_stamps_the_logical_clock_and_branches_the_advance_ledger(api):
    """"Execution stamps `executed_at` from the logical clock, sets
    `advance_recouped_cents` to 0 and `unrecouped_advance_cents` to the full
    `advance_amount_cents` ... a deal whose advance is zero is `RECOUPED` from the
    outset, and any positive advance leaves it `UNRECOUPED`." The 200,000-cent deal
    lands UNRECOUPED at 2026-08-01T00:00:00.000Z with version 2; the zero-advance
    deal lands RECOUPED on the same edge.

    Design: Corner/state_machines/execute_side_effects_write_ledger_and_recompute_parent_count
    """
    ctx = given_draft_deal(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 200000,
            "marketing_budget_cents": 0,
        },
        releases=[{"title": "Ledger X", "planned_release_date": "2026-03-01"}],
    )
    deal_y = mk_deal(
        api,
        ctx["dist_id"],
        distribution_fee_pct=f.pct4("0.1500"),
        advance_amount_cents=0,
        marketing_budget_cents=0,
    )
    mk_release(
        api,
        deal_y["id"],
        ctx["artist_id"],
        title="Ledger Y",
        planned_release_date="2026-03-01",
    )

    with_advance = validate_success(
        api.execute_deal(
            ctx["deal_id"], f.execute_payload("WIRE-X-2026-08"), LABEL_ADMIN
        ),
        200,
    )
    assert_status(with_advance, DEAL_STATUS_EXECUTED)
    assert_field(with_advance, "advance_payment_reference", "WIRE-X-2026-08")
    assert_instant_equals(
        with_advance["executed_at"], DEFAULT_CLOCK_INSTANT, field="executed_at"
    )
    assert_fields_money(
        with_advance,
        advance_recouped_cents=0,
        unrecouped_advance_cents=200000,
        post_recoupment_net_receipts_cents=0,
    )
    assert_field(with_advance, "recoupment_status", RECOUPMENT_STATUS_UNRECOUPED)
    assert_version_is(with_advance, INITIAL_VERSION + 1, entity="deal")

    without_advance = validate_success(
        api.execute_deal(deal_y["id"], f.execute_payload("WIRE-Y-2026-08"), LABEL_ADMIN),
        200,
    )
    assert_status(without_advance, DEAL_STATUS_EXECUTED)
    assert_field_money(without_advance, "unrecouped_advance_cents", 0)
    assert_field(without_advance, "recoupment_status", RECOUPMENT_STATUS_RECOUPED)


def test_execution_recomputes_the_distributors_active_deal_count_over_every_executed_deal(api):
    """"The distributor's `active_deal_count` is recomputed" on execution, so the
    counter is a recount rather than a local increment: it reads 0 while both deals
    are `DRAFT` and 2 once both have been executed against the same distributor.

    Design: Corner/state_machines/execute_side_effects_write_ledger_and_recompute_parent_count
    """
    ctx = given_draft_deal(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 200000,
            "marketing_budget_cents": 0,
        },
        releases=[{"title": "Ledger X", "planned_release_date": "2026-03-01"}],
    )
    deal_y = mk_deal(
        api,
        ctx["dist_id"],
        distribution_fee_pct=f.pct4("0.1500"),
        advance_amount_cents=0,
        marketing_budget_cents=0,
    )
    mk_release(
        api,
        deal_y["id"],
        ctx["artist_id"],
        title="Ledger Y",
        planned_release_date="2026-03-01",
    )

    before = validate_success(api.get_distributor(ctx["dist_id"], LABEL_ADMIN), 200)
    assert_field(before, "active_deal_count", 0)

    do_execute_deal(api, ctx["deal_id"], advance_payment_reference="WIRE-X-2026-08")
    do_execute_deal(api, deal_y["id"], advance_payment_reference="WIRE-Y-2026-08")

    after = validate_success(api.get_distributor(ctx["dist_id"], LABEL_ADMIN), 200)
    assert_field(after, "active_deal_count", 2)


def test_a_trigger_absent_from_the_current_states_transition_list_is_refused_per_entity(api):
    """Seven entities each refuse a trigger their current state does not declare,
    with their own priority-8 error id: close from `EXECUTED`, release from
    `RELEASED`, propose-amendment from `DRAFT` ("propose-amendment is only declared
    from ACTIVE"), settle from `DRAFT`, accept from `DRAFT`, manufacture from
    `MANUFACTURED` and issue from `DRAFT`. The statement case also shows that the
    state gate precedes `ERR_PROVISIONAL_NOT_ISSUABLE`.

    Design: Corner/state_machines/invalid_trigger_from_each_state_rejected
    """
    ctx = given_released_catalog(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
            "advance_amount_cents": 100000,
            "marketing_budget_cents": 500000,
        },
        releases=[
            {
                "title": "Wrong Trigger One",
                "planned_release_date": "2026-03-01",
                "formats": (FORMAT_DIGITAL, FORMAT_CD),
            },
            {"title": "Wrong Trigger Two", "planned_release_date": "2026-03-01"},
        ],
        release_indexes=[0],
        actual_release_date="2026-03-01",
    )
    released_id = ctx["releases"][0]["id"]
    draft_agreement = mk_agreement(
        api,
        ctx["artist_id"],
        released_id,
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.0000"),
    )
    ctx = given_active_agreement(
        api,
        ctx,
        release_index=1,
        agreement_kw={
            "advance_amount_cents": 0,
            "recording_costs_cents": 0,
            "recording_recoupable_pct": f.pct4("0.0000"),
        },
    )
    spend = mk_spend(
        api,
        released_id,
        category=SPEND_CATEGORY_DIGITAL_ADS,
        amount_cents=100000,
        vendor="Trellis Ads",
    )
    run = mk_run(
        api,
        released_id,
        ctx["dist_id"],
        units_planned=1000,
        unit_manufacturing_cost_cents=250,
        window_start="2026-04-01",
        window_end="2026-06-30",
        returns_reserve_pct=f.pct4("0.1000"),
    )
    do_manufacture(api, run["id"], 1000)
    report = mk_report(
        api,
        ctx["deal_id"],
        ctx["partner_headers"],
        period_start="2026-01-01",
        period_end="2026-03-31",
    )
    statement = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-01-01",
        period_end="2026-03-31",
        basis_variant=BASIS_VARIANT_PROVISIONAL,
    )
    echoed_deal_version = deal_version(api, ctx["deal_id"])

    validate_error(
        api.close_deal(ctx["deal_id"], LABEL_ADMIN), ERR_INVALID_DEAL_STATE, 409
    )
    validate_error(
        api.release_to_market(
            released_id, f.release_to_market_payload("2026-04-01"), LABEL_ADMIN
        ),
        ERR_INVALID_RELEASE_STATE,
        409,
    )
    validate_error(
        api.propose_amendment(
            draft_agreement["id"],
            f.propose_amendment_payload(f.pct4("0.1500"), 50000),
            LABEL_ADMIN,
        ),
        ERR_INVALID_AGREEMENT_STATE,
        409,
    )
    validate_error(
        api.settle_spend(spend["id"], f.settle_spend_payload(50000), LABEL_ADMIN),
        ERR_INVALID_SPEND_STATE,
        409,
    )
    validate_error(
        api.accept_report(
            report["id"], f.accept_report_payload(echoed_deal_version), ANALYST
        ),
        ERR_INVALID_REPORT_STATE,
        409,
    )
    validate_error(
        api.manufacture_run(run["id"], f.manufacture_payload(1000), LABEL_ADMIN),
        ERR_INVALID_RUN_STATE,
        409,
    )
    validate_error(
        api.issue_statement(statement["id"], BIZ_AFFAIRS),
        ERR_INVALID_STATEMENT_STATE,
        409,
    )

    assert_status(read_deal(api, ctx["deal_id"]), DEAL_STATUS_EXECUTED)
    assert_status(read_release(api, released_id), RELEASE_STATUS_RELEASED)
    assert_status(read_agreement(api, draft_agreement["id"]), AGREEMENT_STATUS_DRAFT)
    assert_status(read_spend(api, spend["id"]), SPEND_STATUS_DRAFT)
    assert_status(read_report(api, report["id"]), REPORT_STATUS_DRAFT)
    assert_status(read_run(api, run["id"]), RUN_STATUS_MANUFACTURED)
    assert_status(read_statement(api, statement["id"]), STATEMENT_STATUS_DRAFT)
    assert_version_is(
        read_deal(api, ctx["deal_id"]), echoed_deal_version, entity="deal"
    )
    assert_version_is(read_spend(api, spend["id"]), INITIAL_VERSION, entity="spend")
    assert_version_is(read_report(api, report["id"]), INITIAL_VERSION, entity="report")
    assert_version_is(
        read_statement(api, statement["id"]), INITIAL_VERSION, entity="statement"
    )


def test_replaying_execute_neither_overwrites_the_reference_nor_doubles_the_advance(api):
    """"the deal must still be `DRAFT`" for execution, so a replay is refused with
    `ERR_INVALID_DEAL_STATE` and writes nothing: the reference stays WIRE-FIRST,
    `unrecouped_advance_cents` stays 200,000 rather than doubling to 400,000, and
    the version does not move.

    Design: Corner/state_machines/idempotency_second_execute_and_second_activate_rejected
    """
    ctx = given_executed_deal(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 200000,
            "marketing_budget_cents": 0,
        },
        releases=[{"title": "Replay Probe", "planned_release_date": "2026-03-01"}],
        advance_payment_reference="WIRE-FIRST",
    )
    version_after_first = ctx["deal"]["version"]

    validate_error(
        api.execute_deal(
            ctx["deal_id"], f.execute_payload("WIRE-SECOND"), LABEL_ADMIN
        ),
        ERR_INVALID_DEAL_STATE,
        409,
    )

    deal = read_deal(api, ctx["deal_id"])
    assert_status(deal, DEAL_STATUS_EXECUTED)
    assert_field(deal, "advance_payment_reference", "WIRE-FIRST")
    assert_fields_money(
        deal, unrecouped_advance_cents=200000, advance_recouped_cents=0
    )
    assert_version_is(deal, version_after_first, entity="deal")


def test_replaying_activate_does_not_seed_the_artist_ledger_twice(api):
    """Activation is declared only from `DRAFT`, and "`unrecouped_recording_cents`
    is seeded from ... `recording_costs_cents` multiplied by
    `recording_recoupable_pct`, rounded half up" exactly once: after the refused
    replay the balances are still 150,000 and 50,000 rather than 300,000 and
    100,000.

    Design: Corner/state_machines/idempotency_second_execute_and_second_activate_rejected
    """
    ctx = given_executed_deal(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 200000,
            "marketing_budget_cents": 0,
        },
        releases=[{"title": "Replay Probe", "planned_release_date": "2026-03-01"}],
        advance_payment_reference="WIRE-FIRST",
    )
    ctx = given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "advance_amount_cents": 150000,
            "recording_costs_cents": 100000,
            "recording_recoupable_pct": f.pct4("0.5000"),
        },
    )
    version_after_first = ctx["agreement"]["version"]

    validate_error(
        api.activate_agreement(ctx["agreement_id"], LABEL_ADMIN),
        ERR_INVALID_AGREEMENT_STATE,
        409,
    )

    agreement = read_agreement(api, ctx["agreement_id"])
    assert_status(agreement, AGREEMENT_STATUS_ACTIVE)
    assert_fields_money(
        agreement,
        unrecouped_artist_advance_cents=150000,
        unrecouped_recording_cents=50000,
    )
    assert_version_is(agreement, version_after_first, entity="agreement")


def _manufactured_cd_run(api):
    """An EXECUTED zero-advance deal, one CD release and one run of 1,200 units
    pressed at 250 cents each, with a 0.1000 baseline reserve inherited from the
    shipping partner."""
    ctx = given_executed_deal(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
        },
        releases=[
            {
                "title": "Two Axis Probe",
                "planned_release_date": "2026-03-01",
                "formats": (FORMAT_CD,),
            }
        ],
    )
    run = mk_run(
        api,
        ctx["release_id"],
        ctx["dist_id"],
        units_planned=1200,
        unit_manufacturing_cost_cents=250,
        window_start="2026-04-01",
        window_end="2026-06-30",
        returns_reserve_pct=f.pct4("0.1000"),
    )
    do_manufacture(api, run["id"], 1200)
    ctx["run_id"] = run["id"]
    return ctx


def test_recording_returns_resizes_the_reserve_without_advancing_either_run_axis(api):
    """"Recording returns advances neither axis: it is a self-loop that leaves the
    run in `SHIPPED` and leaves the reserve axis alone", while "Each recording
    re-runs the reserve sizing from scratch". 100 returns of 1,000 shipped is a
    0.1000 rate, which lifts the 0.1000 baseline by 0.0500 to 0.1500 and the
    reserve from 90,000 to 135,000 cents.

    Design: Corner/state_machines/physical_run_two_dimensions_move_independently
    """
    ctx = _manufactured_cd_run(api)

    shipped = validate_success(
        api.ship_run(ctx["run_id"], f.ship_payload(1000, 900), ctx["partner_headers"]),
        200,
    )
    assert_status(shipped, RUN_STATUS_SHIPPED)
    assert_status(shipped, RESERVE_STATUS_HELD, field="reserve_status")
    assert_pct_equals(shipped["returns_rate"], f.pct4("0.0000"), field="returns_rate")
    assert_pct_equals(
        shipped["effective_reserve_pct"], f.pct4("0.1000"), field="effective_reserve_pct"
    )
    assert_fields_money(
        shipped,
        reserve_initial_cents=90000,
        reserve_held_cents=90000,
        reserve_liquidated_cents=0,
        physical_net_receipts_cents=600000,
    )
    assert_reserve_conserved(shipped)

    returned = validate_success(
        api.record_returns(
            ctx["run_id"], f.record_returns_payload(100), ctx["partner_headers"]
        ),
        200,
    )
    assert_status(returned, RUN_STATUS_SHIPPED)
    assert_status(returned, RESERVE_STATUS_HELD, field="reserve_status")
    assert_pct_equals(returned["returns_rate"], f.pct4("0.1000"), field="returns_rate")
    assert_pct_equals(
        returned["effective_reserve_pct"],
        f.pct4("0.1500"),
        field="effective_reserve_pct",
    )
    assert_fields_money(
        returned,
        units_returned=100,
        reserve_initial_cents=135000,
        reserve_held_cents=135000,
        reserve_liquidated_cents=0,
        physical_net_receipts_cents=510000,
    )
    assert_reserve_conserved(returned)


def test_only_a_full_liquidation_drags_the_fulfilment_axis_and_a_void_releases_it(api):
    """"**This is the one coupling between the two dimensions**: whenever the
    reserve axis reaches `LIQUIDATED` in a request, the fulfilment axis moves
    `SHIPPED → RECONCILED`", and from `LIQUIDATED` a void moves it back
    `RECONCILED → SHIPPED`. On a 135,000-cent reserve a 0.4000 release moves 54,000
    and leaves the run `SHIPPED`; a 1.0000 release moves the whole 135,000 and
    closes it.

    Design: Corner/state_machines/physical_run_two_dimensions_move_independently
    """
    ctx = _manufactured_cd_run(api)
    do_ship(api, ctx["run_id"], 1000, 900, ctx["partner_headers"])
    do_record_returns(api, ctx["run_id"], 100, ctx["partner_headers"])

    partial = validate_success(
        api.liquidate_reserve(
            ctx["run_id"],
            f.liquidate_payload(run_version(api, ctx["run_id"]), f.pct4("0.4000")),
            ANALYST,
        ),
        200,
    )
    assert_status(partial, RUN_STATUS_SHIPPED)
    assert_status(partial, RESERVE_STATUS_PARTIALLY_LIQUIDATED, field="reserve_status")
    assert_fields_money(
        partial,
        reserve_initial_cents=135000,
        reserve_held_cents=81000,
        reserve_liquidated_cents=54000,
    )
    assert_reserve_conserved(partial)

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
    assert_fields_money(
        voided,
        reserve_initial_cents=135000,
        reserve_held_cents=135000,
        reserve_liquidated_cents=0,
    )

    fully = validate_success(
        api.liquidate_reserve(
            ctx["run_id"],
            f.liquidate_payload(run_version(api, ctx["run_id"]), f.pct4("1.0000")),
            ANALYST,
        ),
        200,
    )
    assert_status(fully, RUN_STATUS_RECONCILED)
    assert_status(fully, RESERVE_STATUS_LIQUIDATED, field="reserve_status")
    assert_fields_money(
        fully,
        reserve_initial_cents=135000,
        reserve_held_cents=0,
        reserve_liquidated_cents=135000,
    )

    reopened = validate_success(
        api.void_liquidation(
            ctx["run_id"],
            f.void_liquidation_payload(run_version(api, ctx["run_id"])),
            ANALYST,
        ),
        200,
    )
    assert_status(reopened, RUN_STATUS_SHIPPED)
    assert_status(reopened, RESERVE_STATUS_HELD, field="reserve_status")
    assert_fields_money(
        reopened,
        reserve_initial_cents=135000,
        reserve_held_cents=135000,
        reserve_liquidated_cents=0,
    )


def test_agreement_activation_is_blocked_by_its_releases_post_term_state(api):
    """"The governed release must be `PLANNED` or `RELEASED`, otherwise
    `ERR_INVALID_RELEASE_STATE` (409) - an agreement cannot be activated onto a
    release that is already reverting or reverted." Both `REVERSION_PENDING` and
    `REVERTED` block, while the identical call on a `PLANNED` release succeeds and,
    the deal being zero-advance and therefore `RECOUPED`, selects the escalated
    0.1800 rate.

    Design: Corner/state_machines/agreement_activation_guarded_by_release_state
    """
    ctx = given_released_catalog(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
            "post_term_collection_days": 90,
        },
        releases=[
            {"title": "Guard G One", "planned_release_date": "2026-03-01"},
            {"title": "Guard G Two", "planned_release_date": "2026-03-01"},
        ],
        release_indexes=[0],
        actual_release_date="2026-03-01",
    )
    on_marketed_release = mk_agreement(
        api,
        ctx["artist_id"],
        ctx["releases"][0]["id"],
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.0000"),
    )
    on_unmarketed_release = mk_agreement(
        api,
        ctx["artist_id"],
        ctx["releases"][1]["id"],
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.0000"),
    )
    do_terminate_deal(api, ctx["deal_id"])

    deal_h = mk_deal(
        api,
        ctx["dist_id"],
        distribution_fee_pct=f.pct4("0.1500"),
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        advance_amount_cents=0,
        marketing_budget_cents=0,
    )
    release_h = mk_release(
        api,
        deal_h["id"],
        ctx["artist_id"],
        title="Guard H One",
        planned_release_date="2026-03-01",
    )
    do_execute_deal(api, deal_h["id"], advance_payment_reference="WIRE-ALDAN-H")
    on_planned_release = mk_agreement(
        api,
        ctx["artist_id"],
        release_h["id"],
        royalty_rate_pct=f.pct4("0.1200"),
        escalated_royalty_rate_pct=f.pct4("0.1800"),
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.0000"),
    )

    assert_status(
        read_release(api, ctx["releases"][0]["id"]), RELEASE_STATUS_REVERSION_PENDING
    )
    assert_status(read_release(api, ctx["releases"][1]["id"]), RELEASE_STATUS_REVERTED)

    validate_error(
        api.activate_agreement(on_marketed_release["id"], LABEL_ADMIN),
        ERR_INVALID_RELEASE_STATE,
        409,
    )
    validate_error(
        api.activate_agreement(on_unmarketed_release["id"], LABEL_ADMIN),
        ERR_INVALID_RELEASE_STATE,
        409,
    )

    for refused_id in (on_marketed_release["id"], on_unmarketed_release["id"]):
        refused = read_agreement(api, refused_id)
        assert_status(refused, AGREEMENT_STATUS_DRAFT)
        assert_version_is(refused, INITIAL_VERSION, entity="agreement")
        assert_null(refused, "active_royalty_rate_pct")

    activated = validate_success(
        api.activate_agreement(on_planned_release["id"], LABEL_ADMIN), 200
    )
    assert_status(activated, AGREEMENT_STATUS_ACTIVE)
    assert_pct_equals(
        activated["active_royalty_rate_pct"],
        f.pct4("0.1800"),
        field="active_royalty_rate_pct",
    )


def _closed_deal_with_one_release_and_one_agreement(api):
    """A deal driven all the way to `CLOSED`, dragging its release to `REVERTED`
    and its agreement to `TERMINATED` through the two three-hop cascades."""
    ctx = given_released_catalog(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-06-30",
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
            "post_term_collection_days": 90,
        },
        releases=[{"title": "Lockdown Probe", "planned_release_date": "2026-03-01"}],
        actual_release_date="2026-03-01",
    )
    ctx = given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "advance_amount_cents": 0,
            "recording_costs_cents": 0,
            "recording_recoupable_pct": f.pct4("0.0000"),
        },
    )
    do_terminate_deal(api, ctx["deal_id"])
    do_enter_post_term_collection(api, ctx["deal_id"])
    do_set_clock(api, "2026-11-01T00:00:00.000Z")
    ctx["deal"] = do_close_deal(api, ctx["deal_id"])
    return ctx


def test_no_trigger_whatsoever_leaves_a_closed_deal(api):
    """"`CLOSED` is terminal", so all five deal actions are refused with the
    priority-8 `ERR_INVALID_DEAL_STATE` - including a repeat of close itself, which
    does NOT surface the priority-10 `ERR_POST_TERM_COLLECTION_ACTIVE` even though
    the clock now sits past `post_term_collection_end_date` 2026-10-30.

    Design: Corner/state_machines/terminal_state_lockdown_closed_deal_reverted_release_terminated_agreement
    """
    ctx = _closed_deal_with_one_release_and_one_agreement(api)
    assert_status(ctx["deal"], DEAL_STATUS_CLOSED)
    version_when_closed = ctx["deal"]["version"]

    validate_error(
        api.execute_deal(ctx["deal_id"], f.execute_payload("WIRE-AGAIN"), LABEL_ADMIN),
        ERR_INVALID_DEAL_STATE,
        409,
    )
    validate_error(
        api.terminate_deal(ctx["deal_id"], LABEL_ADMIN), ERR_INVALID_DEAL_STATE, 409
    )
    validate_error(
        api.expire_deal(ctx["deal_id"], LABEL_ADMIN), ERR_INVALID_DEAL_STATE, 409
    )
    validate_error(
        api.enter_post_term_collection(ctx["deal_id"], LABEL_ADMIN),
        ERR_INVALID_DEAL_STATE,
        409,
    )
    validate_error(
        api.close_deal(ctx["deal_id"], LABEL_ADMIN), ERR_INVALID_DEAL_STATE, 409
    )

    deal = read_deal(api, ctx["deal_id"])
    assert_status(deal, DEAL_STATUS_CLOSED)
    assert_version_is(deal, version_when_closed, entity="deal")


def test_a_reverted_release_and_a_terminated_agreement_refuse_their_own_triggers(api):
    """The closure cascade leaves the release `REVERTED` and the agreement
    `TERMINATED`, and "`CLOSED` is terminal, as are `REVERTED` for a release,
    `SUPERSEDED` and `TERMINATED` for an agreement". Re-promoting the release and
    amending the agreement are each refused with the target entity's own
    priority-8 error id.

    Design: Corner/state_machines/terminal_state_lockdown_closed_deal_reverted_release_terminated_agreement
    """
    ctx = _closed_deal_with_one_release_and_one_agreement(api)
    assert_status(read_release(api, ctx["release_id"]), RELEASE_STATUS_REVERTED)
    assert_status(read_agreement(api, ctx["agreement_id"]), AGREEMENT_STATUS_TERMINATED)

    validate_error(
        api.release_to_market(
            ctx["release_id"], f.release_to_market_payload("2026-04-01"), LABEL_ADMIN
        ),
        ERR_INVALID_RELEASE_STATE,
        409,
    )
    validate_error(
        api.propose_amendment(
            ctx["agreement_id"],
            f.propose_amendment_payload(f.pct4("0.1500"), 10000),
            LABEL_ADMIN,
        ),
        ERR_INVALID_AGREEMENT_STATE,
        409,
    )


def _agreement_pair_awaiting_supersession(api):
    """An EXECUTED deal carrying a 200,000-cent advance (so it stays
    `UNRECOUPED`), one PLANNED release, an ACTIVE predecessor agreement A1 with a
    150,000-cent advance and 100,000 of recording costs at 0.5000, two PROVISIONAL
    statements on A1 (one left `DRAFT`, one driven to `PREPARED`), and a DRAFT
    successor A2 that declares zero balances of its own."""
    ctx = given_executed_deal(
        api,
        deal_kw={
            "advance_amount_cents": 200000,
            "marketing_budget_cents": 0,
        },
        releases=[
            {"title": "Supersession Probe", "planned_release_date": "2026-03-01"}
        ],
    )
    a1 = mk_agreement(
        api,
        ctx["artist_id"],
        ctx["release_id"],
        royalty_rate_pct=f.pct4("0.1200"),
        escalated_royalty_rate_pct=f.pct4("0.1800"),
        advance_amount_cents=150000,
        recording_costs_cents=100000,
        recording_recoupable_pct=f.pct4("0.5000"),
        marketing_recoup_share_pct=f.pct4("0.5000"),
    )
    do_activate_agreement(api, a1["id"])
    s1 = mk_statement(
        api,
        a1["id"],
        period_start="2026-01-01",
        period_end="2026-03-31",
        basis_variant=BASIS_VARIANT_PROVISIONAL,
    )
    s2 = mk_statement(
        api,
        a1["id"],
        period_start="2026-04-01",
        period_end="2026-06-30",
        basis_variant=BASIS_VARIANT_PROVISIONAL,
    )
    do_prepare_statement(api, s2["id"])
    a2 = mk_agreement(
        api,
        ctx["artist_id"],
        ctx["release_id"],
        royalty_rate_pct=f.pct4("0.1400"),
        escalated_royalty_rate_pct=f.pct4("0.2000"),
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.0000"),
        marketing_recoup_share_pct=f.pct4("0.5000"),
        supersedes_agreement_id=a1["id"],
    )
    ctx["a1_id"] = a1["id"]
    ctx["a2_id"] = a2["id"]
    ctx["s1_id"] = s1["id"]
    ctx["s2_id"] = s2["id"]
    return ctx


def test_supersession_moves_the_predecessors_balances_onto_the_successor(api):
    """"whatever remained of the predecessor's `unrecouped_artist_advance_cents`
    is added to the successor's freshly seeded advance balance ... The
    predecessor's own two balances are then zeroed". A2 declares a zero advance
    and zero recording costs, so its 150,000 and 50,000 can only have come from
    A1, whose balances read 0 afterwards, and the artist's rollup — which counts
    only `ACTIVE`, `AMENDMENT_PENDING` and `POST_TERM` agreements — still totals
    150,000 rather than 300,000.

    Design: Corner/state_machines/supersession_cross_entity_voids_draft_and_prepared_statements
    """
    ctx = _agreement_pair_awaiting_supersession(api)
    a1_before = read_agreement(api, ctx["a1_id"])

    activated = validate_success(
        api.activate_agreement(ctx["a2_id"], LABEL_ADMIN), 200
    )
    assert_status(activated, AGREEMENT_STATUS_ACTIVE)
    assert_fields_money(
        activated,
        unrecouped_artist_advance_cents=150000,
        unrecouped_recording_cents=50000,
    )
    assert_pct_equals(
        activated["active_royalty_rate_pct"],
        f.pct4("0.1400"),
        field="active_royalty_rate_pct",
    )

    a1_after = read_agreement(api, ctx["a1_id"])
    assert_status(a1_after, AGREEMENT_STATUS_SUPERSEDED)
    assert_fields_money(
        a1_after,
        unrecouped_artist_advance_cents=0,
        unrecouped_recording_cents=0,
    )
    assert_version_is(
        a1_after, a1_before["version"] + 1, entity="superseded agreement"
    )

    assert_field_money(
        read_artist(api, ctx["artist_id"]), "unrecouped_advance_total_cents", 150000
    )


def test_supersession_voids_the_predecessors_draft_and_prepared_statements(api):
    """"any statement of the predecessor still sitting in `DRAFT` or `PREPARED` is
    voided, because unissued working papers computed against a superseded
    agreement can no longer be published". One statement is voided out of `DRAFT`
    and the other out of `PREPARED`, each with its `version` up by exactly 1.

    Design: Corner/state_machines/supersession_cross_entity_voids_draft_and_prepared_statements
    """
    ctx = _agreement_pair_awaiting_supersession(api)
    s1_before = read_statement(api, ctx["s1_id"])
    s2_before = read_statement(api, ctx["s2_id"])
    assert_status(s1_before, STATEMENT_STATUS_DRAFT)
    assert_status(s2_before, STATEMENT_STATUS_PREPARED)

    validate_success(api.activate_agreement(ctx["a2_id"], LABEL_ADMIN), 200)

    s1_after = read_statement(api, ctx["s1_id"])
    assert_status(s1_after, STATEMENT_STATUS_VOIDED)
    assert_version_is(
        s1_after, s1_before["version"] + 1, entity="voided draft statement"
    )

    s2_after = read_statement(api, ctx["s2_id"])
    assert_status(s2_after, STATEMENT_STATUS_VOIDED)
    assert_version_is(
        s2_after, s2_before["version"] + 1, entity="voided prepared statement"
    )


def _terminated_deal_with_six_spends(api):
    """A TERMINATION_NOTICE deal whose single release carries six 100,000-cent
    spends parked in six different states: DRAFT, SUBMITTED, REVISION_REQUESTED,
    APPROVED, REJECTED and SETTLED (at 80,000)."""
    ctx = given_executed_deal(
        api,
        deal_kw={
            "advance_amount_cents": 0,
            "marketing_budget_cents": 1000000,
            "post_term_collection_days": 90,
        },
        releases=[
            {"title": "Conditional Cascade", "planned_release_date": "2026-03-01"}
        ],
    )
    rel_id = ctx["release_id"]

    s_draft = mk_spend(
        api, rel_id, category=SPEND_CATEGORY_DIGITAL_ADS, amount_cents=100000,
        vendor="Kite Draft",
    )
    s_submitted = mk_spend(
        api, rel_id, category=SPEND_CATEGORY_DIGITAL_ADS, amount_cents=100000,
        vendor="Kite Submitted",
    )
    do_submit_spend(api, s_submitted["id"], LABEL_ADMIN)

    s_revision = mk_spend(
        api, rel_id, category=SPEND_CATEGORY_RADIO_PROMO, amount_cents=100000,
        vendor="Kite Revision",
    )
    do_submit_spend(api, s_revision["id"], LABEL_ADMIN)
    do_decide_spend(
        api,
        s_revision["id"],
        SPEND_DECISION_REQUEST_REVISION,
        BIZ_AFFAIRS,
        revision_note="split the buy by territory",
    )

    s_approved = mk_spend(
        api, rel_id, category=SPEND_CATEGORY_DIGITAL_ADS, amount_cents=100000,
        vendor="Kite Approved",
    )
    do_submit_spend(api, s_approved["id"], LABEL_ADMIN)
    do_decide_spend(api, s_approved["id"], SPEND_DECISION_APPROVE, BIZ_AFFAIRS)

    s_rejected = mk_spend(
        api, rel_id, category=SPEND_CATEGORY_PUBLICITY, amount_cents=100000,
        vendor="Kite Rejected",
    )
    do_submit_spend(api, s_rejected["id"], LABEL_ADMIN)
    do_decide_spend(api, s_rejected["id"], SPEND_DECISION_REJECT, BIZ_AFFAIRS)

    s_settled = mk_spend(
        api, rel_id, category=SPEND_CATEGORY_DIGITAL_ADS, amount_cents=100000,
        vendor="Kite Settled",
    )
    do_submit_spend(api, s_settled["id"], LABEL_ADMIN)
    do_decide_spend(api, s_settled["id"], SPEND_DECISION_APPROVE, BIZ_AFFAIRS)
    do_settle_spend(api, s_settled["id"], 80000, LABEL_ADMIN)

    do_terminate_deal(api, ctx["deal_id"], LABEL_ADMIN)

    ctx["spend_ids"] = {
        "draft": s_draft["id"],
        "submitted": s_submitted["id"],
        "revision": s_revision["id"],
        "approved": s_approved["id"],
        "rejected": s_rejected["id"],
        "settled": s_settled["id"],
    }
    return ctx


def test_entering_post_term_collection_voids_exactly_the_three_open_spend_states(api):
    """"every marketing spend on the deal's releases sitting in `DRAFT`,
    `SUBMITTED` or `REVISION_REQUESTED` moves to `VOIDED` ... Spends already
    `APPROVED` or `SETTLED` are untouched". Six spends in six states: the three
    open rows are voided with their `version` up by 1, while APPROVED, REJECTED
    and SETTLED keep both their status and their pre-trigger `version`.

    Design: Corner/state_machines/enter_post_term_collection_voids_only_open_marketing_spends
    """
    ctx = _terminated_deal_with_six_spends(api)
    ids = ctx["spend_ids"]
    before = {key: read_spend(api, spend_id) for key, spend_id in ids.items()}
    assert_status(before["draft"], SPEND_STATUS_DRAFT)
    assert_status(before["submitted"], SPEND_STATUS_SUBMITTED)
    assert_status(before["revision"], SPEND_STATUS_REVISION_REQUESTED)
    assert_status(before["approved"], SPEND_STATUS_APPROVED)
    assert_status(before["rejected"], SPEND_STATUS_REJECTED)
    assert_status(before["settled"], SPEND_STATUS_SETTLED)

    joined = validate_success(
        api.enter_post_term_collection(ctx["deal_id"], LABEL_ADMIN), 200
    )
    assert_status(joined, DEAL_STATUS_POST_TERM_COLLECTION)

    items, _meta = validate_list(
        api.list_spends(LABEL_ADMIN, params={"release_id": ctx["release_id"]})
    )
    after = {key: find_by_id(items, spend_id) for key, spend_id in ids.items()}

    for key in ("draft", "submitted", "revision"):
        assert_status(after[key], SPEND_STATUS_VOIDED)
        assert_version_is(
            after[key], before[key]["version"] + 1, entity="voided spend " + key
        )

    assert_status(after["approved"], SPEND_STATUS_APPROVED)
    assert_status(after["rejected"], SPEND_STATUS_REJECTED)
    assert_status(after["settled"], SPEND_STATUS_SETTLED)
    for key in ("approved", "rejected", "settled"):
        assert_version_is(
            after[key], before[key]["version"], entity="untouched spend " + key
        )


def test_voiding_open_spends_leaves_the_committed_marketing_total_alone(api):
    """The committed total is defined so that "a spend in `SETTLED` contributes its
    `settled_amount_cents` and a spend in `APPROVED` contributes its
    `amount_cents`, while spends in `DRAFT`, `SUBMITTED`, `REJECTED`,
    `REVISION_REQUESTED` or `VOIDED` contribute nothing at all", so
    with one APPROVED row at 100,000 and one SETTLED row at 80,000 it reads
    180,000 both before and after the freeze, and the revision-requested row keeps
    its `revision_note` on the way to `VOIDED`.

    Design: Corner/state_machines/enter_post_term_collection_voids_only_open_marketing_spends
    """
    ctx = _terminated_deal_with_six_spends(api)
    assert_field_money(
        read_deal(api, ctx["deal_id"]), "marketing_committed_cents", 180000
    )

    validate_success(api.enter_post_term_collection(ctx["deal_id"], LABEL_ADMIN), 200)

    assert_field_money(
        read_deal(api, ctx["deal_id"]), "marketing_committed_cents", 180000
    )
    voided_revision = read_spend(api, ctx["spend_ids"]["revision"])
    assert_status(voided_revision, SPEND_STATUS_VOIDED)
    assert_field(voided_revision, "revision_note", "split the buy by territory")


def test_shipping_then_returns_push_a_total_and_then_a_delta_up_both_ancestors(api):
    """Shipping raises "both the release's and the deal's
    `net_receipts_to_date_cents` by the run's `physical_net_receipts_cents`", while
    the returns self-loop adjusts them "by the **delta** between the new figure and
    the old one rather than by the new figure itself". 1,000 units at 900 less a
    300,000-cent pressing is 600,000; 100 returns drop it to 510,000, so both
    ancestors must read 510,000 and never 1,110,000.

    Design: Corner/state_machines/ship_ledger_sync_lifts_release_and_deal_net_receipts
    """
    ctx = _manufactured_cd_run(api)
    assert_field_money(
        read_release(api, ctx["release_id"]), "net_receipts_to_date_cents", 0
    )

    shipped = validate_success(
        api.ship_run(ctx["run_id"], f.ship_payload(1000, 900), ctx["partner_headers"]),
        200,
    )
    assert_field_money(shipped, "physical_net_receipts_cents", 600000)
    assert_field_money(
        read_release(api, ctx["release_id"]), "net_receipts_to_date_cents", 600000
    )
    assert_field_money(
        read_deal(api, ctx["deal_id"]), "net_receipts_to_date_cents", 600000
    )

    returned = validate_success(
        api.record_returns(
            ctx["run_id"], f.record_returns_payload(100), ctx["partner_headers"]
        ),
        200,
    )
    assert_field_money(returned, "physical_net_receipts_cents", 510000)
    assert_field_money(
        read_release(api, ctx["release_id"]), "net_receipts_to_date_cents", 510000
    )

    deal = read_deal(api, ctx["deal_id"])
    assert_field_money(deal, "net_receipts_to_date_cents", 510000)
    assert_field_money(deal, "advance_recouped_cents", 0)
    assert_field(deal, "recoupment_status", RECOUPMENT_STATUS_RECOUPED)


AUDIT_CLOCK_INSTANT = "2026-09-01T00:00:00.000Z"


def _finalized_statement_with_out_of_scope_audit_request(api):
    """A FINALIZED statement for 2026-01-01..2026-03-31 with no revenue behind it,
    on an ACTIVE agreement carrying a 150,000-cent advance and 50,000 of recoupable
    recording costs, against which the artist has requested an audit whose scope
    starts three months before the statement's own `period_start`."""
    ctx = given_executed_deal(
        api,
        deal_kw={
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
            "objection_window_days": 30,
        },
        releases=[
            {"title": "Audit Scope Probe", "planned_release_date": "2026-03-01"}
        ],
    )
    agreement = mk_agreement(
        api,
        ctx["artist_id"],
        ctx["release_id"],
        royalty_rate_pct=f.pct4("0.1200"),
        escalated_royalty_rate_pct=f.pct4("0.1800"),
        advance_amount_cents=150000,
        recording_costs_cents=100000,
        recording_recoupable_pct=f.pct4("0.5000"),
        marketing_recoup_share_pct=f.pct4("0.5000"),
    )
    do_activate_agreement(api, agreement["id"])

    statement = mk_statement(
        api,
        agreement["id"],
        period_start="2026-01-01",
        period_end="2026-03-31",
        basis_variant=BASIS_VARIANT_FINAL,
    )
    do_prepare_statement(api, statement["id"], ANALYST)
    do_issue_statement(api, statement["id"], BIZ_AFFAIRS)
    do_set_clock(api, AUDIT_CLOCK_INSTANT)
    finalized = do_finalize_statement(api, statement["id"], BIZ_AFFAIRS)

    ctx["agreement_id"] = agreement["id"]
    ctx["statement_id"] = statement["id"]
    ctx["finalized"] = finalized
    ctx["requested"] = do_request_audit(
        api,
        statement["id"],
        ctx["artist_headers"],
        "2025-10-01",
        "2026-03-31",
        "Halvard Audit LLP",
    )
    return ctx


def test_an_out_of_scope_audit_is_denied_without_reopening_the_statement(api):
    """"If instead `audit_scope_period_start` falls before the statement's
    `period_start` ... the audit axis moves `AUDIT_REQUESTED → AUDIT_DENIED` ... On
    this edge `audit_findings_adjustment_cents` stays null whatever was supplied,
    `audit_cost_bearer` is set to `ARTIST`, and the accounting axis does not move".
    A 2025-10-01 scope start against a 2026-01-01 period start takes the denial
    edge even though the supplied 100,000 would clear the materiality gate on the
    other edge, so the statement stays `FINALIZED` and the agreement keeps its
    150,000 and 50,000 balances.

    Design: Corner/state_machines/audit_denied_when_scope_reaches_outside_the_statement_period
    """
    ctx = _finalized_statement_with_out_of_scope_audit_request(api)
    requested = ctx["requested"]
    assert_field(requested, "audit_status", AUDIT_STATUS_REQUESTED)
    assert_date(
        requested["audit_scope_period_start"],
        "2025-10-01",
        field="audit_scope_period_start",
    )
    assert_date(
        requested["audit_scope_period_end"],
        "2026-03-31",
        field="audit_scope_period_end",
    )
    assert_field_money(ctx["finalized"], "net_payable_cents", 0)
    assert_fields_money(
        read_agreement(api, ctx["agreement_id"]),
        unrecouped_artist_advance_cents=150000,
        unrecouped_recording_cents=50000,
    )

    concluded = validate_success(
        api.conclude_audit(
            ctx["statement_id"], f.conclude_audit_payload(100000), BIZ_AFFAIRS
        ),
        200,
    )
    assert_field(concluded, "audit_status", AUDIT_STATUS_DENIED)
    assert_null(concluded, "audit_findings_adjustment_cents")
    assert_field(concluded, "audit_cost_bearer", AUDIT_COST_BEARER_ARTIST)
    assert_status(concluded, STATEMENT_STATUS_FINALIZED)
    assert_instant_equals(
        concluded["finalized_at"], AUDIT_CLOCK_INSTANT, field="finalized_at"
    )
    assert_version_is(
        concluded, requested["version"] + 1, entity="denied statement"
    )
    assert_fields_money(
        read_agreement(api, ctx["agreement_id"]),
        unrecouped_artist_advance_cents=150000,
        unrecouped_recording_cents=50000,
    )


def test_a_denied_audit_cannot_be_concluded_a_second_time(api):
    """"the audit axis moves `AUDIT_REQUESTED → AUDIT_DENIED`, which is terminal"
    and "`AUDIT_DENIED` on a statement's audit axis" is listed among the terminal
    states, so replaying the same trigger is refused with
    `ERR_INVALID_STATEMENT_STATE` (409) and writes nothing — the statement's
    `version` is unchanged by the refusal.

    Design: Corner/state_machines/audit_denied_when_scope_reaches_outside_the_statement_period
    """
    ctx = _finalized_statement_with_out_of_scope_audit_request(api)
    denied = validate_success(
        api.conclude_audit(
            ctx["statement_id"], f.conclude_audit_payload(100000), BIZ_AFFAIRS
        ),
        200,
    )
    assert_field(denied, "audit_status", AUDIT_STATUS_DENIED)

    validate_error(
        api.conclude_audit(
            ctx["statement_id"], f.conclude_audit_payload(0), BIZ_AFFAIRS
        ),
        ERR_INVALID_STATEMENT_STATE,
        409,
    )
    after = read_statement(api, ctx["statement_id"])
    assert_field(after, "audit_status", AUDIT_STATUS_DENIED)
    assert_status(after, STATEMENT_STATUS_FINALIZED)
    assert_version_is(after, denied["version"], entity="statement after refused replay")
