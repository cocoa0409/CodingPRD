"""Allowances: the frozen approval tier, the bounded revision cycle and the posting cascade.

Covers PRD section 3.6 (raising, submitting, returning for revision, approving and
the four-hop posting cascade) together with PRD section 3.8 (report supersession)
and PRD section 2.10 (segregation of duties).
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_empty,
    assert_fields,
    assert_int,
    assert_money,
    assert_money_fields,
    assert_row_count,
    single,
)
from test_helpers.test_users import (
    AUDITOR,
    AUDITOR_2,
    CONTROLLER,
    FRONT_DESK,
    REVENUE_MANAGER,
    REVENUE_MANAGER_2,
)


def _allowance_at_the_revision_limit(api):
    """A 300.00 allowance submitted for the third time, both revision rounds spent."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-6001",
        guest_name="Jo Uribe",
        room_number="601",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])
    allowance = fx.create_allowance(
        api,
        folio["id"],
        bd["id"],
        300.00,
        FRONT_DESK,
        reason_code="MANAGER_DISCRETION",
        narrative="Goodwill for a construction-noise complaint.",
    )
    validate_success(api.submit_allowance(allowance["id"], FRONT_DESK))
    for round_number in (1, 2):
        validate_success(
            api.return_allowance_for_revision(allowance["id"], REVENUE_MANAGER)
        )
        validate_success(
            api.submit_allowance(
                allowance["id"],
                FRONT_DESK,
                {"narrative": f"Revision {round_number} - paperwork attached."},
            )
        )
    return prop, bd, folio, allowance


def test_a_third_return_for_revision_is_refused_and_moves_nothing(api):
    """The cycle permits at most two round trips.

    PRD section 3.6 refuses a return-for-revision on an allowance whose
    `revision_round` has already reached two with ERR_REVISION_LIMIT_REACHED
    (HTTP 409), and the refused transition neither raises the counter nor moves the
    allowance out of SUBMITTED.

    Design: Difficulty/non_linear_state_machine/allowance_revision_cycle_capped_at_two_with_tier_frozen
    """
    _prop, _bd, _folio, allowance = _allowance_at_the_revision_limit(api)

    validate_error(
        api.return_allowance_for_revision(allowance["id"], REVENUE_MANAGER),
        E.ERR_REVISION_LIMIT_REACHED,
    )

    row = fx.read_allowance(api, allowance["id"])
    assert_int(row["revision_round"], 2, "revision_round")
    assert_fields(row, {"status": "SUBMITTED"})


def test_the_approval_tier_stays_frozen_across_the_whole_revision_cycle(api):
    """A 300.00 request keeps its RevenueManager tier even when 10.00 is granted.

    PRD section 3.6 derives `required_approval_role` from `requested_amount` alone at
    creation and never re-derives it — not by a later `approved_amount`, however
    small, and not by any number of revision rounds. So the manager may still grant
    10.00, far below the 250.00 manager threshold, and the tier reads RevenueManager
    on the posted allowance.

    Design: Difficulty/non_linear_state_machine/allowance_revision_cycle_capped_at_two_with_tier_frozen
    """
    _prop, _bd, _folio, allowance = _allowance_at_the_revision_limit(api)
    assert_fields(
        fx.read_allowance(api, allowance["id"]),
        {"required_approval_role": "RevenueManager"},
    )

    posted = validate_success(
        api.approve_allowance(
            allowance["id"], f.build_approve_payload(10.00), REVENUE_MANAGER_2
        )
    )
    assert_fields(
        posted, {"status": "POSTED", "required_approval_role": "RevenueManager"}
    )
    assert_money(posted["approved_amount"], 10.00, "approved_amount")


def test_a_night_auditor_cannot_approve_the_frozen_manager_tier(api):
    """The frozen tier keeps the lowest role out however small the grant is.

    PRD section 3.6 refuses an acting role below `required_approval_role` on the
    NightAuditor < RevenueManager < Controller ladder with
    ERR_APPROVAL_TIER_INSUFFICIENT (HTTP 403). Re-deriving the tier from an
    `approved_amount` of 10.00 would wrongly admit a NightAuditor.

    Design: Difficulty/non_linear_state_machine/allowance_revision_cycle_capped_at_two_with_tier_frozen
    """
    _prop, _bd, _folio, allowance = _allowance_at_the_revision_limit(api)

    validate_error(
        api.approve_allowance(
            allowance["id"], f.build_approve_payload(10.00), AUDITOR_2
        ),
        E.ERR_APPROVAL_TIER_INSUFFICIENT,
    )
    assert_fields(fx.read_allowance(api, allowance["id"]), {"status": "SUBMITTED"})


def _distributed_report_over_a_reopened_day(api):
    """A reopened day carrying a distributed report and a submitted 60.00 allowance."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(
        api,
        prop["id"],
        "2026-08-01",
        out_of_order_room_count=4,
        benchmark_calendar_room_revenue_amount=400.00,
        benchmark_weekday_room_revenue_amount=520.00,
    )
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-7001",
        guest_name="Kit Vance",
        room_number="701",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.drive_to_settlement_review(api, bd["id"])
    report_one = fx.create_report(
        api, bd["id"], ["RevenueManager"], pace_basis="CALENDAR_ALIGNED"
    )
    fx.distribute_report(api, report_one["id"])
    fx.balance_business_date(api, bd["id"])
    fx.close_business_date(api, bd["id"])
    validate_success(api.reopen_business_date(bd["id"], CONTROLLER))
    report_two = fx.create_report(
        api, bd["id"], ["RevenueManager", "Controller"], pace_basis="CALENDAR_ALIGNED"
    )
    fx.distribute_report(api, report_two["id"])
    allowance = fx.submitted_allowance(
        api,
        folio["id"],
        bd["id"],
        60.00,
        FRONT_DESK,
        reason_code="GUEST_DISPUTE",
        narrative="Rate disputed at departure.",
    )
    return prop, bd, folio, report_one, report_two, allowance


def test_approval_posts_through_approved_and_mints_one_workflow_credit_line(api):
    """Hops 1 and 2: the allowance lands POSTED and a single negative line appears.

    PRD section 3.6 carries an approved allowance straight on to POSTED inside the
    same request and appends an ALLOWANCE journal line of the negated
    `approved_amount` with `source_channel` ALLOWANCE_WORKFLOW and `allowance_id`
    naming the allowance.

    Design: Difficulty/transitive_cascade/allowance_approval_cascades_four_hops_to_supersede_distributed_report
    """
    _prop, _bd, _folio, _one, _two, allowance = _distributed_report_over_a_reopened_day(api)

    posted = validate_success(
        api.approve_allowance(
            allowance["id"], f.build_approve_payload(60.00), AUDITOR_2
        )
    )
    assert_fields(posted, {"status": "POSTED"})
    assert_money(posted["approved_amount"], 60.00, "approved_amount")

    rows = validate_success(
        api.list_journal_postings(AUDITOR, allowance_id=allowance["id"])
    )
    assert_row_count(rows, 1, "ALLOWANCE lines for the allowance")
    line = single(rows)
    assert_fields(
        line, {"charge_type": "ALLOWANCE", "source_channel": "ALLOWANCE_WORKFLOW"}
    )
    assert_money(line["amount"], -60.00, "allowance line amount")


def test_the_credit_line_re_derives_the_account_and_the_operating_day(api):
    """Hop 3: the account nets down and the day's revenue statistics follow.

    PRD section 3.6 re-derives the account's totals and the day's
    `room_night_revenue_amount`, `allowance_credit_amount`, `room_revenue_amount`,
    `total_revenue_amount`, `adr_amount` and `revpar_amount` from the credit line. PRD
    section 3.3 keeps the ROOM line in place, so the occupied-room count does not
    fall even though the average daily rate does.

    Design: Difficulty/transitive_cascade/allowance_approval_cascades_four_hops_to_supersede_distributed_report
    """
    _prop, bd, folio, _one, _two, allowance = _distributed_report_over_a_reopened_day(api)

    validate_success(
        api.approve_allowance(
            allowance["id"], f.build_approve_payload(60.00), AUDITOR_2
        )
    )

    account = fx.read_folio(api, folio["id"])
    assert_money_fields(
        account,
        {
            "charges_total_amount": 217.75,
            "credits_total_amount": -60.00,
            "balance_amount": 157.75,
        },
    )
    assert_fields(account, {"settlement_status": "PARTIALLY_SETTLED"})

    day = fx.read_business_date(api, bd["id"])
    assert_money_fields(
        day,
        {
            "allowance_credit_amount": -60.00,
            "room_night_revenue_amount": 140.00,
            "room_revenue_amount": 140.00,
            "tax_revenue_amount": 17.75,
            "total_revenue_amount": 157.75,
            "adr_amount": 140.00,
            "revpar_amount": 1.46,
            "occupancy_pct": 1.04,
        },
    )
    assert_int(day["rooms_occupied_count"], 1, "rooms_occupied_count")


def test_the_cascade_supersedes_a_distributed_report_without_thawing_its_snapshot(api):
    """Hop 4: the live report flips to SUPERSEDED while its frozen figures stand.

    PRD section 3.6 sets every DRAFT or DISTRIBUTED report of the day to SUPERSEDED
    when the day's aggregates change, and PRD section 3.8 makes a report a snapshot
    rather than a view, so the superseded report still carries the pre-allowance
    200.00 room revenue, 200.00 average daily rate and 50.00 pace index. The report
    superseded earlier by the reopen is not touched a second time.

    Design: Difficulty/transitive_cascade/allowance_approval_cascades_four_hops_to_supersede_distributed_report
    """
    _prop, _bd, _folio, report_one, report_two, allowance = (
        _distributed_report_over_a_reopened_day(api)
    )
    assert_fields(fx.read_report(api, report_two["id"]), {"status": "DISTRIBUTED"})

    validate_success(
        api.approve_allowance(
            allowance["id"], f.build_approve_payload(60.00), AUDITOR_2
        )
    )

    live = fx.read_report(api, report_two["id"])
    assert_fields(live, {"status": "SUPERSEDED"})
    assert_money_fields(
        live,
        {
            "room_revenue_amount": 200.00,
            "adr_amount": 200.00,
            "pace_index_pct": 50.00,
        },
    )
    assert_fields(fx.read_report(api, report_one["id"]), {"status": "SUPERSEDED"})


def _two_allowances_astride_the_manager_threshold(api):
    """Two submitted allowances on one account, for exactly 250.00 and for 249.99."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-9301",
        guest_name="Pia Coe",
        room_number="904",
        nights_count=1,
        contracted_rate_amount=200.00,
        settlement_method="CASH",
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])
    at_threshold = fx.submitted_allowance(
        api, folio["id"], bd["id"], 250.00, FRONT_DESK, narrative="At the threshold."
    )
    below = fx.submitted_allowance(
        api,
        folio["id"],
        bd["id"],
        249.99,
        FRONT_DESK,
        narrative="One cent below the threshold.",
    )
    return prop, bd, folio, at_threshold, below


def test_the_manager_threshold_is_inclusive_so_one_cent_decides_the_tier(api):
    """250.00 demands a RevenueManager; 249.99 does not.

    PRD section 3.6 derives `required_approval_role` from `requested_amount` with
    inclusive comparisons, so a request of exactly `allowance_manager_threshold_amount`
    requires a RevenueManager while one cent below it needs only a NightAuditor. A
    NightAuditor reaching for the at-threshold allowance is refused with
    ERR_APPROVAL_TIER_INSUFFICIENT.

    Design: Difficulty/boundary_precision_check/allowance_manager_threshold_inclusive_at_two_fifty
    """
    _prop, _bd, _folio, at_threshold, below = _two_allowances_astride_the_manager_threshold(api)

    assert_fields(
        fx.read_allowance(api, at_threshold["id"]),
        {"required_approval_role": "RevenueManager"},
    )
    assert_fields(
        fx.read_allowance(api, below["id"]),
        {"required_approval_role": "NightAuditor"},
    )

    validate_error(
        api.approve_allowance(
            at_threshold["id"], f.build_approve_payload(250.00), AUDITOR_2
        ),
        E.ERR_APPROVAL_TIER_INSUFFICIENT,
    )


def test_each_allowance_posts_at_the_rung_its_own_amount_demands(api):
    """The sub-threshold request clears at auditor level, the other at manager level.

    PRD section 3.6 admits any acting role at or above `required_approval_role` on the
    NightAuditor < RevenueManager < Controller ladder, so 249.99 posts for a
    NightAuditor and 250.00 posts for a RevenueManager.

    Design: Difficulty/boundary_precision_check/allowance_manager_threshold_inclusive_at_two_fifty
    """
    _prop, _bd, _folio, at_threshold, below = _two_allowances_astride_the_manager_threshold(api)

    posted_below = validate_success(
        api.approve_allowance(below["id"], f.build_approve_payload(249.99), AUDITOR_2)
    )
    assert_fields(posted_below, {"status": "POSTED"})

    posted_at = validate_success(
        api.approve_allowance(
            at_threshold["id"], f.build_approve_payload(250.00), REVENUE_MANAGER
        )
    )
    assert_fields(posted_at, {"status": "POSTED"})


def _controller_tier_allowance_awaiting_paperwork(api):
    """A 1000.00 RATE_ERROR rebate sitting SUBMITTED at the Controller tier."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(api, prop["id"], "2026-08-01", out_of_order_room_count=4)
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-DOC1",
        guest_name="Xan Juba",
        room_number="1201",
        nights_count=1,
        contracted_rate_amount=200.00,
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])
    allowance = fx.create_allowance(
        api,
        folio["id"],
        bd["id"],
        1000.00,
        FRONT_DESK,
        reason_code="RATE_ERROR",
        supporting_document_reference="GRP-2026-114",
    )
    submitted = validate_success(
        api.submit_allowance(
            allowance["id"],
            FRONT_DESK,
            {"reason_code": "RATE_ERROR", "supporting_document_reference": "GRP-2026-114"},
        )
    )
    return prop, bd, folio, submitted


def test_the_controller_tier_needs_active_paperwork_and_a_pending_file_is_not_enough(api):
    """Rank alone does not buy the approval: the rebate document gate is separate.

    PRD section 3.6 keys the rebate-paperwork requirement to `requested_amount` reaching
    `allowance_controller_threshold_amount`, and refuses approval with
    ERR_ALLOWANCE_DOCUMENT_MISSING (HTTP 409) unless an ALLOWANCE_APPROVAL document names
    this allowance and is ACTIVE. PRD section 3.6 also makes a PENDING document satisfy no
    gate whatsoever, so filing without review changes nothing and no ALLOWANCE line
    appears.

    Design: Difficulty/cross_entity_state_dependency/controller_tier_allowance_requires_active_matching_approval_document
    """
    prop, _bd, folio, allowance = _controller_tier_allowance_awaiting_paperwork(api)
    assert_fields(
        allowance, {"required_approval_role": "Controller", "status": "SUBMITTED"}
    )

    validate_error(
        api.approve_allowance(allowance["id"], f.build_approve_payload(1000.00), CONTROLLER),
        E.ERR_ALLOWANCE_DOCUMENT_MISSING,
    )
    assert_empty(
        validate_success(
            api.list_journal_postings(AUDITOR, folio_id=folio["id"], charge_type="ALLOWANCE")
        ),
        "ALLOWANCE lines",
    )

    document = fx.create_authorization_document(
        api,
        prop["id"],
        AUDITOR,
        doc_type="ALLOWANCE_APPROVAL",
        allowance_id=allowance["id"],
        document_reference="ALW-2026-0801",
        valid_from_date="2026-08-01",
        valid_to_date="2026-08-31",
    )
    assert_fields(document, {"status": "PENDING"})
    validate_error(
        api.approve_allowance(allowance["id"], f.build_approve_payload(1000.00), CONTROLLER),
        E.ERR_ALLOWANCE_DOCUMENT_MISSING,
    )

    fx.review_document(api, document["id"], "APPROVE", REVENUE_MANAGER)
    posted = validate_success(
        api.approve_allowance(allowance["id"], f.build_approve_payload(1000.00), CONTROLLER)
    )
    assert_fields(posted, {"status": "POSTED"})
    assert_money(posted["approved_amount"], 1000.00, "approved_amount")

    account = fx.read_folio(api, folio["id"])
    assert_money_fields(
        account,
        {
            "charges_total_amount": 217.75,
            "credits_total_amount": -1000.00,
            "balance_amount": -782.25,
        },
    )
    assert_fields(account, {"settlement_status": "PARTIALLY_SETTLED"})


def test_the_paperwork_must_name_the_rebate_alone_and_only_above_the_threshold(api):
    """A document naming both targets is malformed, and one cent below the tier needs none.

    PRD section 3.6 requires an ALLOWANCE_APPROVAL document to carry `allowance_id` and
    not `folio_id`, rejecting either disagreement with ERR_DOCUMENT_TARGET_MISMATCH
    (HTTP 422). And because the requirement is keyed to `requested_amount` reaching
    `allowance_controller_threshold_amount`, a 999.99 rebate sits at the RevenueManager
    tier and is approved by a Controller with no paperwork at all.

    Design: Difficulty/cross_entity_state_dependency/controller_tier_allowance_requires_active_matching_approval_document
    """
    prop, bd, folio, allowance = _controller_tier_allowance_awaiting_paperwork(api)

    validate_error(
        api.create_authorization_document(
            f.build_authorization_document_payload(
                prop["id"],
                doc_type="ALLOWANCE_APPROVAL",
                allowance_id=allowance["id"],
                folio_id=folio["id"],
                valid_from_date="2026-08-01",
                valid_to_date="2026-08-31",
            ),
            AUDITOR,
        ),
        E.ERR_DOCUMENT_TARGET_MISMATCH,
    )

    smaller = fx.submitted_allowance(
        api,
        folio["id"],
        bd["id"],
        999.99,
        FRONT_DESK,
        reason_code="SERVICE_RECOVERY",
    )
    assert_fields(smaller, {"required_approval_role": "RevenueManager"})
    granted = validate_success(
        api.approve_allowance(smaller["id"], f.build_approve_payload(999.99), CONTROLLER)
    )
    assert_fields(granted, {"status": "POSTED"})


def _posted_rebate_ready_to_reverse(api):
    """A 60.00 GUEST_DISPUTE rebate POSTED against a 200.00 room night."""
    fx.set_clock(api, "2026-08-01T09:00:00.000Z")
    prop = fx.create_property(api)
    bd = fx.create_business_date(
        api,
        prop["id"],
        "2026-08-01",
        out_of_order_room_count=4,
        benchmark_calendar_room_revenue_amount=400.00,
        benchmark_weekday_room_revenue_amount=520.00,
    )
    folio = fx.create_folio(
        api,
        prop["id"],
        bd["id"],
        confirmation_code="CF-REV1",
        guest_name="Zev Lund",
        room_number="1401",
        nights_count=1,
        contracted_rate_amount=200.00,
        scheduled_checkout_at="2026-08-02T11:00:00.000Z",
    )
    fx.check_in(api, folio["id"])
    fx.post_room_and_tax(api, bd["id"])
    allowance = fx.posted_allowance(
        api,
        folio["id"],
        bd["id"],
        60.00,
        FRONT_DESK,
        AUDITOR_2,
        reason_code="GUEST_DISPUTE",
    )
    return prop, bd, folio, allowance


def test_reversing_a_rebate_restores_every_net_figure_but_no_gross_one(api):
    """The balance and the day's revenue come back exactly; the account's totals do not.

    PRD section 3.6 states that a reversal returns `balance_amount` to exactly its
    pre-approval value while `charges_total_amount` *rises* by `approved_amount` and
    `credits_total_amount` keeps the original negative figure, so `settlement_status` is
    re-derived from the new pair rather than restored. PRD section 3.3 brings the day's
    room-night revenue back to the full 200.00 with `allowance_credit_amount` at exactly
    0.00, and the statistics of PRD section 3.8 follow — 200.00 over 96 available rooms.

    Design: Difficulty/compensating_invariant/allowance_reversal_restores_net_money_but_not_gross_totals
    """
    _prop, bd, folio, allowance = _posted_rebate_ready_to_reverse(api)

    validate_success(api.reverse_allowance(allowance["id"], REVENUE_MANAGER))

    account = fx.read_folio(api, folio["id"])
    assert_money(account["balance_amount"], 217.75, "balance_amount")
    assert_money_fields(
        account,
        {"charges_total_amount": 277.75, "credits_total_amount": -60.00},
    )
    assert_fields(account, {"settlement_status": "PARTIALLY_SETTLED"})

    day = fx.read_business_date(api, bd["id"])
    assert_money_fields(
        day,
        {
            "room_night_revenue_amount": 200.00,
            "allowance_credit_amount": 0.00,
            "room_revenue_amount": 200.00,
            "tax_revenue_amount": 17.75,
            "total_revenue_amount": 217.75,
            "adr_amount": 200.00,
            "revpar_amount": 2.08,
        },
    )


def test_the_reversal_mints_a_compensating_rebate_that_cannot_be_reversed_again(api):
    """Two ALLOWANCE lines, one compensating rebate, and both terminal states hold.

    PRD section 3.6 mints a second allowance born POSTED whose `reverses_allowance_id`
    names the original and whose requested and approved amounts both equal the original's
    `approved_amount`, alongside a positive ALLOWANCE journal line carrying
    `reverses_posting_id`. PRD section 3.6 then refuses a second reversal of the original
    with ERR_ALLOWANCE_NOT_POSTED and refuses reversing the compensator at all with
    ERR_ALREADY_A_REVERSAL, both HTTP 409.

    Design: Difficulty/compensating_invariant/allowance_reversal_restores_net_money_but_not_gross_totals
    """
    _prop, _bd, folio, allowance = _posted_rebate_ready_to_reverse(api)
    validate_success(api.reverse_allowance(allowance["id"], REVENUE_MANAGER))

    lines = validate_success(
        api.list_journal_postings(AUDITOR, folio_id=folio["id"], charge_type="ALLOWANCE")
    )
    assert_row_count(lines, 2, "ALLOWANCE lines")
    credits = [row for row in lines if row["reverses_posting_id"] is None]
    mirrors = [row for row in lines if row["reverses_posting_id"] is not None]
    assert_row_count(credits, 1, "original ALLOWANCE lines")
    assert_row_count(mirrors, 1, "reversing ALLOWANCE lines")
    assert_money(credits[0]["amount"], -60.00, "the rebate credit")
    assert_money(mirrors[0]["amount"], 60.00, "the compensating line")
    assert_fields(mirrors[0], {"reverses_posting_id": credits[0]["id"]})

    original = fx.read_allowance(api, allowance["id"])
    assert_fields(original, {"status": "REVERSED"})
    assert_money(original["approved_amount"], 60.00, "approved_amount")

    listed = validate_success(
        api.list_allowances(AUDITOR, reverses_allowance_id=allowance["id"])
    )
    assert_row_count(listed, 1, "compensating allowances")
    minted = single(listed)
    assert_fields(
        minted,
        {
            "status": "POSTED",
            "reason_code": "GUEST_DISPUTE",
            "reverses_allowance_id": allowance["id"],
        },
    )
    assert_money_fields(minted, {"requested_amount": 60.00, "approved_amount": 60.00})

    validate_error(
        api.reverse_allowance(allowance["id"], CONTROLLER), E.ERR_ALLOWANCE_NOT_POSTED
    )
    validate_error(
        api.reverse_allowance(minted["id"], CONTROLLER), E.ERR_ALREADY_A_REVERSAL
    )
