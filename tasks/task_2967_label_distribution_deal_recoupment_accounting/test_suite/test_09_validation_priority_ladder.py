"""
The twelve-rank validation priority ladder: which error id wins when a single
request breaks two rules at once (PRD Sections 2.1, 2.8, 3.1-3.9).

Every test here translates one instance of the corner index section
`validations`. Each ordering instance asserts the higher-ranked id first and then
relaxes only the higher violation so the lower-ranked rule is shown to be live
rather than merely unreachable.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import (
    AGREEMENT_STATUS_POST_TERM,
    AGREEMENT_STATUS_TERMINATED,
    ANALYST,
    BIZ_AFFAIRS,
    BIZ_AFFAIRS_2,
    DEAL_STATUS_CLOSED,
    DEAL_STATUS_DRAFT,
    DEAL_STATUS_EXPIRED,
    DEAL_STATUS_POST_TERM_COLLECTION,
    DEAL_TYPE_DISTRIBUTION_FEE,
    DEAL_TYPE_LABEL_SERVICES,
    DEAL_TYPE_PROFIT_SHARE,
    DEFAULT_CLOCK_DATE,
    DEFAULT_CLOCK_INSTANT,
    ERR_ADVANCE_ALLOCATION_EXCEEDED,
    ERR_ARTIST_NOT_FOUND,
    ERR_DEAL_NOT_FOUND,
    ERR_DUPLICATE_UPC,
    ERR_INVALID_REPORT_STATE,
    ERR_INVALID_REQUEST,
    ERR_MARKETING_SPEND_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OBJECTION_WINDOW_OPEN,
    ERR_OPEN_OBJECTIONS_BLOCK_CLOSE,
    ERR_POST_TERM_COLLECTION_ACTIVE,
    ERR_RATE_CARD_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_DEAL_VERSION,
    ERR_TERM_NOT_ENDED,
    ERR_UNAUTHENTICATED,
    FORMAT_VINYL,
    INITIAL_VERSION,
    LABEL_ADMIN,
    OBJECTION_REASON_RESERVE_DISPUTE,
    RECOUPABILITY_FULL,
    RECOUPMENT_STATUS_UNRECOUPED,
    RELEASE_STATUS_PLANNED,
    RELEASE_STATUS_RELEASED,
    RELEASE_STATUS_REVERSION_PENDING,
    RELEASE_STATUS_REVERTED,
    REPORT_STATUS_ACCEPTED,
    REPORT_STATUS_DRAFT,
    RESOLUTION_DENIED,
    SPEND_CATEGORY_DIGITAL_ADS,
    SPEND_DECISION_APPROVE,
    SPEND_STATUS_APPROVED,
    SPEND_STATUS_SUBMITTED,
    STATEMENT_STATUS_FINALIZED,
    STATEMENT_STATUS_ISSUED,
    TIER_AD_SUPPORTED,
    TIER_PREMIUM,
    USER_BIZ_AFFAIRS,
    USER_LABEL_ADMIN,
    assert_date,
    assert_field,
    assert_field_money,
    assert_fields,
    assert_fields_money,
    assert_instant_equals,
    assert_instant_precision,
    assert_null,
    assert_pct_equals,
    assert_status,
    assert_version_bumped,
    assert_version_is,
    do_enter_post_term_collection,
    do_execute_deal,
    do_object,
    do_resolve_objection,
    do_set_clock,
    do_submit_spend,
    do_terminate_deal,
    given_accepted_report,
    given_active_agreement,
    given_distributor_and_artist,
    given_issued_statement,
    given_rate_cards,
    given_released_catalog,
    given_shipped_run,
    headers_blank_role,
    ids_of,
    make_analyst_headers,
    make_partner_headers,
    make_unknown_role_headers,
    mk_deal,
    mk_distributor,
    mk_line,
    mk_rate_card,
    mk_release,
    mk_report,
    mk_spend,
    read_agreement,
    read_deal,
    read_release,
    read_release_lines,
    read_report,
    read_report_lines,
    read_spend,
    validate_list,
)

ZERO_RECOUP_AGREEMENT = {
    "royalty_rate_pct": "0.1000",
    "escalated_royalty_rate_pct": "0.1000",
    "advance_amount_cents": 0,
    "recording_costs_cents": 0,
    "recording_recoupable_pct": "0.0000",
    "marketing_recoup_share_pct": "0.0000",
}


def test_approving_a_spend_at_the_budget_ceiling_writes_the_decision(api):
    """When no rank of the ladder is violated the write lands: the budget test is
    inclusive because "already-committed marketing plus this spend's
    `amount_cents` must not exceed the deal's `marketing_budget_cents`". A
    100,000-cent DIGITAL_ADS spend against a 100,000-cent budget is APPROVED at
    the 2026-08-01 clock, FULLY_RECOUPABLE, two versions above its draft.

    Design: Corner/validations/every_priority_satisfied_lets_the_write_through
    """
    ctx = given_released_catalog(api, deal_kw={"marketing_budget_cents": 100000})
    draft = mk_spend(
        api,
        ctx["release_id"],
        category=SPEND_CATEGORY_DIGITAL_ADS,
        amount_cents=100000,
    )
    submitted = do_submit_spend(api, draft["id"], headers=LABEL_ADMIN)
    assert_status(submitted, SPEND_STATUS_SUBMITTED)

    resp = api.decide_spend(
        draft["id"], f.decide_spend_payload(SPEND_DECISION_APPROVE), BIZ_AFFAIRS
    )
    decided = validate_success(resp, 200)

    assert_status(decided, SPEND_STATUS_APPROVED)
    assert_fields(
        decided,
        decided_by_user_id=USER_BIZ_AFFAIRS,
        requested_by_user_id=USER_LABEL_ADMIN,
        recoupability=RECOUPABILITY_FULL,
    )
    assert_instant_equals(decided["approved_at"], DEFAULT_CLOCK_INSTANT, "approved_at")
    assert_instant_precision(decided["approved_at"], "approved_at")
    assert_version_bumped(submitted, decided, entity="marketing spend")
    assert decided["version"] == draft["version"] + 2

    assert_field_money(read_deal(api, ctx["deal_id"]), "marketing_committed_cents", 100000)


def test_spend_decision_reports_auth_then_role_then_path_then_shape(api):
    """Ranks 1, 2, 3 and 5 in order on one endpoint: "a header supplied as an
    empty string, or containing nothing but whitespace, counts as absent" and the
    request is 401, an unpermitted or unrecognised role gives
    `ERR_ROLE_NOT_PERMITTED`, then the path id 404, and only last the malformed
    `decision`. Every call carries the same invalid decision "MAYBE" so the four
    higher ranks are the only thing that changes.

    Design: Corner/validations/auth_ladder_401_before_403_before_404_before_400_rejected
    """
    ctx = given_released_catalog(api, deal_kw={"marketing_budget_cents": 500000})
    draft = mk_spend(api, ctx["release_id"], amount_cents=100000)
    submitted = do_submit_spend(api, draft["id"], headers=LABEL_ADMIN)
    bad_body = f.decide_spend_payload("MAYBE")

    resp = api.decide_spend(
        NON_EXISTENT_UUID, bad_body, headers_blank_role(USER_BIZ_AFFAIRS)
    )
    validate_error(resp, ERR_UNAUTHENTICATED, 401)

    resp = api.decide_spend(NON_EXISTENT_UUID, bad_body, ctx["artist_headers"])
    validate_error(resp, ERR_ROLE_NOT_PERMITTED, 403)

    resp = api.decide_spend(
        NON_EXISTENT_UUID, bad_body, make_unknown_role_headers(USER_BIZ_AFFAIRS)
    )
    validate_error(resp, ERR_ROLE_NOT_PERMITTED, 403)

    resp = api.decide_spend(NON_EXISTENT_UUID, bad_body, BIZ_AFFAIRS)
    err = validate_error(resp, ERR_MARKETING_SPEND_NOT_FOUND, 404)
    assert "id" not in err
    assert err["message"]

    resp = api.decide_spend(draft["id"], bad_body, BIZ_AFFAIRS)
    validate_error(resp, ERR_INVALID_REQUEST, 400)

    after = read_spend(api, draft["id"])
    assert_status(after, SPEND_STATUS_SUBMITTED)
    assert_version_is(after, submitted["version"], entity="marketing spend")
    assert_null(after, "decided_by_user_id", "approved_at")


def test_release_creation_reports_a_malformed_upc_before_unresolved_parents(api):
    """Rank 5 precedes rank 6: the request-shape rank requires "`upc` between 12
    and 14 ASCII digits", and only once the body is well-formed are the foreign
    keys resolved in the pinned order `deal_id` then `primary_artist_id`. A
    two-digit upc alongside two fabricated parents is therefore 400, not 404.

    Design: Corner/validations/body_schema_400_rejects_before_body_foreign_keys_are_resolved
    """
    ctx = given_distributor_and_artist(api)
    deal = mk_deal(api, ctx["dist_id"])
    upc = f.next_upc()

    resp = api.create_release(
        f.release_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, upc="12", title="Malformed"
        ),
        LABEL_ADMIN,
    )
    validate_error(resp, ERR_INVALID_REQUEST, 400)

    resp = api.create_release(
        f.release_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID, upc=upc, title="Malformed"),
        LABEL_ADMIN,
    )
    validate_error(resp, ERR_DEAL_NOT_FOUND, 404)

    resp = api.create_release(
        f.release_payload(deal["id"], NON_EXISTENT_UUID, upc=upc, title="Malformed"),
        LABEL_ADMIN,
    )
    validate_error(resp, ERR_ARTIST_NOT_FOUND, 404)

    resp = api.create_release(
        f.release_payload(deal["id"], ctx["artist_id"], upc=upc, title="Malformed"),
        LABEL_ADMIN,
    )
    created = validate_success(resp, 201)
    assert_field(created, "upc", upc)
    assert_status(created, RELEASE_STATUS_PLANNED)

    items, meta = validate_list(
        api.list_releases(
            LABEL_ADMIN, params={"deal_id": deal["id"], "limit": 50, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(items) == [created["id"]]


def test_a_stranger_partner_is_refused_before_the_report_state_is_examined(api):
    """Rank 4 precedes rank 8: "Ownership is enforced on exactly seven
    operations: appending a revenue line to a report, submitting a report", so a
    second distributor gets `ERR_NOT_RESOURCE_OWNER` on an already-ACCEPTED
    report while the owner gets the 409. The report keeps its 100,000-cent gross
    (250,000 streams at 4,000 micros) and its version.

    Design: Corner/validations/resource_owner_403_outranks_report_state_409_rejected
    """
    ctx = given_released_catalog(api)
    stranger = mk_distributor(
        api, name="Harbourside Physical", legal_entity="Harbourside Physical Ltd"
    )
    stranger_headers = make_partner_headers(stranger["id"])
    ctx = given_accepted_report(api, ctx, lines=[{"stream_count": 250000}])
    accepted = ctx["report"]
    assert_status(accepted, REPORT_STATUS_ACCEPTED)

    resp = api.submit_report(accepted["id"], stranger_headers)
    validate_error(resp, ERR_NOT_RESOURCE_OWNER, 403)

    resp = api.append_line(
        accepted["id"],
        f.line_payload(ctx["release_id"], stream_count=999),
        stranger_headers,
    )
    err = validate_error(resp, ERR_NOT_RESOURCE_OWNER, 403)
    assert "id" not in err
    assert "gross_receipts_cents" not in err

    resp = api.submit_report(accepted["id"], ctx["partner_headers"])
    validate_error(resp, ERR_INVALID_REPORT_STATE, 409)

    after = read_report(api, accepted["id"])
    assert_status(after, REPORT_STATUS_ACCEPTED)
    assert_version_is(after, accepted["version"], entity="revenue report")
    assert_field_money(after, "gross_receipts_cents", 100000)
    assert len(read_report_lines(api, accepted["id"])) == 1


def test_a_stale_deal_echo_beats_the_draft_report_state(api):
    """Rank 7 precedes rank 8: "A caller who echoes a stale parent version *and*
    targets a record in the wrong state receives the 412, not the 409". Accepting
    a DRAFT report with the deal's create-time version gives
    `ERR_STALE_DEAL_VERSION`; the current version then exposes the 409.

    Design: Corner/validations/stale_version_412_outranks_report_state_409_rejected
    """
    ctx = given_distributor_and_artist(api)
    deal = mk_deal(api, ctx["dist_id"])
    release = mk_release(api, deal["id"], ctx["artist_id"], title="Guard Order")
    stale_version = deal["version"]
    executed = do_execute_deal(api, deal["id"])
    assert executed["version"] == stale_version + 1

    ctx["deal_id"] = deal["id"]
    given_rate_cards(api, ctx)
    report = mk_report(api, deal["id"], ctx["partner_headers"])
    mk_line(
        api,
        report["id"],
        release["id"],
        ctx["partner_headers"],
        territory_code="US",
        tier=TIER_PREMIUM,
        stream_count=250000,
    )

    resp = api.accept_report(
        report["id"], f.accept_report_payload(stale_version), ANALYST
    )
    validate_error(resp, ERR_STALE_DEAL_VERSION, 412)

    resp = api.accept_report(
        report["id"], f.accept_report_payload(executed["version"]), ANALYST
    )
    validate_error(resp, ERR_INVALID_REPORT_STATE, 409)

    after = read_report(api, report["id"])
    assert_status(after, REPORT_STATUS_DRAFT)
    assert_version_is(after, report["version"], entity="revenue report")
    assert_fields_money(
        after,
        gross_receipts_cents=0,
        distributor_share_cents=0,
        net_receipts_cents=0,
    )
    assert_null(after, "accepted_at")

    deal_after = read_deal(api, deal["id"])
    assert_version_is(deal_after, executed["version"], entity="distribution deal")
    assert_field_money(deal_after, "net_receipts_to_date_cents", 0)


def test_the_preparer_is_barred_from_finalizing_before_the_window_is_checked(api):
    """Rank 9 precedes rank 10: "the operator who prepared a statement may not
    issue it, resolve an objection on it, finalize it, or conclude its audit",
    while finalization also "requires the logical clock to be strictly past
    `objection_deadline`". biz-affairs-01 prepared under the RoyaltyAnalyst role,
    so its finalize is 403; biz-affairs-02 at the same 2026-08-01 clock is 422
    against the 2026-08-31 deadline, and 200 once the clock reads 2026-09-01.

    Design: Corner/validations/segregation_403_outranks_objection_window_422
    """
    ctx = given_released_catalog(api, deal_kw={"objection_window_days": 30})
    ctx = given_active_agreement(api, ctx, agreement_kw=dict(ZERO_RECOUP_AGREEMENT))
    ctx = given_issued_statement(
        api,
        ctx,
        prepare_headers=make_analyst_headers(USER_BIZ_AFFAIRS),
        issue_headers=BIZ_AFFAIRS_2,
    )
    issued = ctx["statement"]
    assert_field(issued, "prepared_by_user_id", USER_BIZ_AFFAIRS)
    assert_instant_equals(
        issued["objection_deadline"], "2026-08-31T00:00:00.000Z", "objection_deadline"
    )

    resp = api.finalize_statement(issued["id"], BIZ_AFFAIRS)
    validate_error(resp, ERR_SEGREGATION_OF_DUTIES, 403)

    resp = api.finalize_statement(issued["id"], BIZ_AFFAIRS_2)
    validate_error(resp, ERR_OBJECTION_WINDOW_OPEN, 422)

    do_set_clock(api, "2026-09-01T00:00:00.000Z")
    finalized = validate_success(api.finalize_statement(issued["id"], BIZ_AFFAIRS_2), 200)

    assert_status(finalized, STATEMENT_STATUS_FINALIZED)
    assert_instant_equals(
        finalized["finalized_at"], "2026-09-01T00:00:00.000Z", "finalized_at"
    )
    assert_version_bumped(issued, finalized, entity="artist statement")


def test_closing_reports_the_open_collection_tail_before_the_open_objection(api):
    """Rank 10 precedes rank 11 on closure: "The logical clock's calendar date
    must be strictly after `post_term_collection_end_date`, otherwise
    `ERR_POST_TERM_COLLECTION_ACTIVE` (422)", and only then does the unanswered
    objection surface as `ERR_OPEN_OBJECTIONS_BLOCK_CLOSE` (409). Termination on
    2026-08-01 with a 90-day tail pins the end date at 2026-10-30.

    Design: Corner/validations/post_term_collection_422_outranks_open_objections_409
    """
    ctx = given_released_catalog(
        api,
        distributor_kw={
            "name": "Harbourside Physical",
            "legal_entity": "Harbourside Physical Ltd",
            "default_returns_reserve_pct": f.pct4("0.1000"),
        },
        deal_kw={"objection_window_days": 30, "post_term_collection_days": 90},
        releases=[{"title": "Pressed Late", "formats": (FORMAT_VINYL,)}],
    )
    ctx = given_active_agreement(api, ctx, agreement_kw=dict(ZERO_RECOUP_AGREEMENT))
    ctx = given_shipped_run(
        api,
        ctx,
        units_manufactured=1200,
        units_shipped=1000,
        wholesale_unit_price_cents=900,
    )
    assert_fields_money(
        ctx["run"], physical_net_receipts_cents=600000, reserve_held_cents=90000
    )

    ctx = given_issued_statement(api, ctx)
    statement = ctx["statement"]
    assert_fields_money(
        statement, reserve_withheld_cents=9000, net_payable_cents=51000
    )
    do_object(
        api,
        statement["id"],
        ctx["artist_headers"],
        OBJECTION_REASON_RESERVE_DISPUTE,
        1000,
        "Reserve percentage looks high for a vinyl-only run.",
    )

    terminated = do_terminate_deal(api, ctx["deal_id"])
    assert_date(
        terminated["termination_effective_date"],
        DEFAULT_CLOCK_DATE,
        "termination_effective_date",
    )
    assert_date(
        terminated["post_term_collection_end_date"],
        "2026-10-30",
        "post_term_collection_end_date",
    )
    do_enter_post_term_collection(api, ctx["deal_id"])

    resp = api.close_deal(ctx["deal_id"], LABEL_ADMIN)
    validate_error(resp, ERR_POST_TERM_COLLECTION_ACTIVE, 422)

    assert_status(read_deal(api, ctx["deal_id"]), DEAL_STATUS_POST_TERM_COLLECTION)
    assert_status(read_release(api, ctx["release_id"]), RELEASE_STATUS_REVERSION_PENDING)
    assert_status(read_agreement(api, ctx["agreement_id"]), AGREEMENT_STATUS_POST_TERM)

    do_set_clock(api, "2026-11-01T00:00:00.000Z")
    resp = api.close_deal(ctx["deal_id"], LABEL_ADMIN)
    validate_error(resp, ERR_OPEN_OBJECTIONS_BLOCK_CLOSE, 409)

    resolved = do_resolve_objection(
        api, statement["id"], RESOLUTION_DENIED, headers=BIZ_AFFAIRS_2
    )
    assert_status(resolved, STATEMENT_STATUS_ISSUED)
    assert_field(resolved, "objection_resolution", RESOLUTION_DENIED)

    closed = validate_success(api.close_deal(ctx["deal_id"], LABEL_ADMIN), 200)
    assert_status(closed, DEAL_STATUS_CLOSED)
    assert_status(read_release(api, ctx["release_id"]), RELEASE_STATUS_REVERTED)
    assert_status(read_agreement(api, ctx["agreement_id"]), AGREEMENT_STATUS_TERMINATED)


def test_a_duplicate_upc_is_reported_before_the_advance_is_over_allocated(api):
    """Rank 11 precedes rank 12: a `upc` "must be unique across every release in
    the system; a duplicate is rejected with `ERR_DUPLICATE_UPC` (409)", while
    "the shares must never sum to more than the deal's `advance_amount_cents`" is
    the later 422. Against a 100,000-cent advance already carrying a 60,000 share,
    a second 60,000 share overshoots but 40,000 exactly is accepted.

    Design: Corner/validations/duplicate_upc_409_outranks_advance_allocation_422
    """
    ctx = given_distributor_and_artist(api)
    deal = mk_deal(api, ctx["dist_id"], advance_amount_cents=100000)
    taken_upc = f.next_upc()
    first = mk_release(
        api,
        deal["id"],
        ctx["artist_id"],
        upc=taken_upc,
        title="First Pressing",
        advance_share_cents=60000,
    )

    resp = api.create_release(
        f.release_payload(
            deal["id"],
            ctx["artist_id"],
            upc=taken_upc,
            title="Clash",
            planned_release_date="2026-03-01",
            advance_share_cents=60000,
        ),
        LABEL_ADMIN,
    )
    validate_error(resp, ERR_DUPLICATE_UPC, 409)

    resp = api.create_release(
        f.release_payload(
            deal["id"],
            ctx["artist_id"],
            upc=f.next_upc(),
            title="Clash",
            planned_release_date="2026-03-01",
            advance_share_cents=60000,
        ),
        LABEL_ADMIN,
    )
    validate_error(resp, ERR_ADVANCE_ALLOCATION_EXCEEDED, 422)

    resp = api.create_release(
        f.release_payload(
            deal["id"],
            ctx["artist_id"],
            upc=f.next_upc(),
            title="Clash",
            planned_release_date="2026-03-01",
            advance_share_cents=40000,
        ),
        LABEL_ADMIN,
    )
    third = validate_success(resp, 201)
    assert_field_money(third, "advance_share_cents", 40000)

    items, meta = validate_list(
        api.list_releases(
            LABEL_ADMIN, params={"deal_id": deal["id"], "limit": 50, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert sorted(ids_of(items)) == sorted([first["id"], third["id"]])
    assert_version_is(read_deal(api, deal["id"]), deal["version"], entity="distribution deal")


def test_a_deal_type_missing_one_of_its_own_fee_fields_is_rejected(api):
    """The required half of the pairing: "A `DISTRIBUTION_FEE` deal requires
    `distribution_fee_pct`" and "A `LABEL_SERVICES` deal requires both of its two
    components", so omitting one it does use "is a request-shape violation
    reported as `ERR_INVALID_REQUEST`" at rank 5 (HTTP 400).

    Design: Corner/validations/deal_type_conditional_fields_rejects_mismatched_pairings
    """
    distributor = mk_distributor(api)

    no_fee_at_all = f.deal_payload(
        distributor["id"],
        deal_type=DEAL_TYPE_DISTRIBUTION_FEE,
        cross_collateralized=False,
    )
    no_fee_at_all.pop("distribution_fee_pct")
    validate_error(
        api.create_deal(no_fee_at_all, LABEL_ADMIN), ERR_INVALID_REQUEST, 400
    )

    half_a_services_deal = f.deal_payload(
        distributor["id"],
        deal_type=DEAL_TYPE_LABEL_SERVICES,
        services_fee_pct=f.pct4("0.1000"),
        cross_collateralized=False,
    )
    assert "services_monthly_fee_cents" not in half_a_services_deal
    validate_error(
        api.create_deal(half_a_services_deal, LABEL_ADMIN), ERR_INVALID_REQUEST, 400
    )


def test_a_deal_carrying_a_foreign_fee_field_is_rejected_both_ways(api):
    """The must-be-null half of the same rule: "Supplying a fee field that the
    chosen structure does not use, or omitting one it does, is a request-shape
    violation reported as `ERR_INVALID_REQUEST`", symmetric across the types.
    0.6000 is inside
    `profit_share_label_pct`'s own 0.3000..0.9000 range and still 400 on a
    DISTRIBUTION_FEE deal; the two well-paired bodies are DRAFT at version 1.

    Design: Corner/validations/deal_type_conditional_fields_rejects_mismatched_pairings
    """
    distributor = mk_distributor(api)

    fee_deal_with_profit_share = f.deal_payload(
        distributor["id"],
        deal_type=DEAL_TYPE_DISTRIBUTION_FEE,
        distribution_fee_pct=f.pct4("0.1500"),
        profit_share_label_pct=f.pct4("0.6000"),
        cross_collateralized=False,
    )
    validate_error(
        api.create_deal(fee_deal_with_profit_share, LABEL_ADMIN),
        ERR_INVALID_REQUEST,
        400,
    )

    profit_deal_with_fee = f.deal_payload(
        distributor["id"],
        deal_type=DEAL_TYPE_PROFIT_SHARE,
        profit_share_label_pct=f.pct4("0.6000"),
        distribution_fee_pct=f.pct4("0.1500"),
        cross_collateralized=False,
    )
    validate_error(
        api.create_deal(profit_deal_with_fee, LABEL_ADMIN), ERR_INVALID_REQUEST, 400
    )

    profit_deal = validate_success(
        api.create_deal(
            f.deal_payload(
                distributor["id"],
                deal_type=DEAL_TYPE_PROFIT_SHARE,
                profit_share_label_pct=f.pct4("0.6000"),
                cross_collateralized=False,
            ),
            LABEL_ADMIN,
        ),
        201,
    )
    assert_pct_equals(
        profit_deal["profit_share_label_pct"], "0.6000", "profit_share_label_pct"
    )
    assert_null(
        profit_deal,
        "distribution_fee_pct",
        "services_fee_pct",
        "services_monthly_fee_cents",
    )

    services_deal = validate_success(
        api.create_deal(
            f.deal_payload(
                distributor["id"],
                deal_type=DEAL_TYPE_LABEL_SERVICES,
                services_fee_pct=f.pct4("0.1000"),
                services_monthly_fee_cents=25000,
                cross_collateralized=False,
            ),
            LABEL_ADMIN,
        ),
        201,
    )
    assert_pct_equals(services_deal["services_fee_pct"], "0.1000", "services_fee_pct")
    assert_field_money(services_deal, "services_monthly_fee_cents", 25000)
    assert_null(services_deal, "distribution_fee_pct", "profit_share_label_pct")

    for deal in (profit_deal, services_deal):
        assert_status(deal, DEAL_STATUS_DRAFT)
        assert_version_is(deal, INITIAL_VERSION, entity="distribution deal")
        assert_field(deal, "recoupment_status", RECOUPMENT_STATUS_UNRECOUPED)
        assert_field_money(deal, "advance_recouped_cents", 0)


def test_natural_expiry_waits_for_the_day_after_the_term_ends(api):
    """Rank 10 on the expiry fork: expiry "may only be taken once the term has
    actually run out: the logical clock's calendar date must be strictly after
    `term_end_date`, otherwise `ERR_TERM_NOT_ENDED` (422)". The last instant of
    2026-12-31 is still refused; on 2027-01-01 the deal expires with
    `post_term_collection_end_date` 2027-03-31 (term end + 90, not clock + 90) and
    no release changes state.

    Design: Corner/validations/expire_rejected_until_the_clock_passes_term_end
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"post_term_collection_days": 90},
        releases=[
            {"title": "Out Now"},
            {"title": "Still Planned", "planned_release_date": "2026-11-01"},
        ],
        release_indexes=[0],
    )
    deal = ctx["deal"]

    validate_error(api.expire_deal(ctx["deal_id"], LABEL_ADMIN), ERR_TERM_NOT_ENDED, 422)

    do_set_clock(api, "2026-12-31T23:59:59.999Z")
    validate_error(api.expire_deal(ctx["deal_id"], LABEL_ADMIN), ERR_TERM_NOT_ENDED, 422)

    do_set_clock(api, "2027-01-01T00:00:00.000Z")
    expired = validate_success(api.expire_deal(ctx["deal_id"], LABEL_ADMIN), 200)

    assert_status(expired, DEAL_STATUS_EXPIRED)
    assert_null(expired, "termination_effective_date")
    assert_date(
        expired["post_term_collection_end_date"],
        "2027-03-31",
        "post_term_collection_end_date",
    )
    assert_version_bumped(deal, expired, entity="distribution deal")

    promoted = read_release(api, ctx["releases"][0]["id"])
    unpromoted = read_release(api, ctx["releases"][1]["id"])
    assert_status(promoted, RELEASE_STATUS_RELEASED)
    assert_status(unpromoted, RELEASE_STATUS_PLANNED)
    for release in (promoted, unpromoted):
        assert_date(
            release["reversion_eligible_date"], "2027-03-31", "reversion_eligible_date"
        )


def test_one_unpriceable_line_rejects_the_whole_report_submission(api):
    """Rank 11 all-or-nothing pricing: "If a line has no candidate at all, the
    entire submission is rejected with `ERR_RATE_CARD_NOT_FOUND` (422); no line is
    priced and no report figure changes." With no STRM/GB/PREMIUM card the submit
    is refused; adding one at 3,000 micros prices the three lines to a 160,000-cent
    gross, a 24,000-cent 0.1500 distributor share and 136,000 net.

    Design: Corner/validations/missing_rate_card_rejects_the_whole_submit
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"territory_codes": ("US", "GB")},
        releases=[{"title": "Two Territories"}],
    )
    given_rate_cards(
        api,
        ctx,
        [
            {"territory_code": "US", "tier": TIER_PREMIUM, "rate_micros_per_stream": 4000},
            {
                "territory_code": "US",
                "tier": TIER_AD_SUPPORTED,
                "rate_micros_per_stream": 1200,
            },
        ],
    )
    report = mk_report(api, ctx["deal_id"], ctx["partner_headers"])
    for territory, tier, streams in (
        ("US", TIER_PREMIUM, 100000),
        ("US", TIER_AD_SUPPORTED, 500000),
        ("GB", TIER_PREMIUM, 200000),
    ):
        mk_line(
            api,
            report["id"],
            ctx["release_id"],
            ctx["partner_headers"],
            territory_code=territory,
            tier=tier,
            stream_count=streams,
        )

    resp = api.submit_report(report["id"], ctx["partner_headers"])
    validate_error(resp, ERR_RATE_CARD_NOT_FOUND, 422)

    unpriced = read_report(api, report["id"])
    assert_status(unpriced, REPORT_STATUS_DRAFT)
    assert_version_is(unpriced, report["version"], entity="revenue report")
    assert_fields_money(
        unpriced,
        gross_receipts_cents=0,
        distributor_share_cents=0,
        net_receipts_cents=0,
    )
    assert_null(unpriced, "submitted_by_user_id")

    lines = read_release_lines(api, ctx["release_id"], limit=50, offset=0)
    assert len(lines) == 3
    for line in lines:
        assert_null(line, "applied_rate_micros_per_stream", "resolved_revenue_cents")

    mk_rate_card(
        api, territory_code="GB", tier=TIER_PREMIUM, rate_micros_per_stream=3000
    )
    priced = validate_success(api.submit_report(report["id"], ctx["partner_headers"]), 200)
    assert_fields_money(
        priced,
        gross_receipts_cents=160000,
        distributor_share_cents=24000,
        net_receipts_cents=136000,
    )

    repriced = read_release_lines(api, ctx["release_id"], limit=50, offset=0)
    assert sorted(int(line["applied_rate_micros_per_stream"]) for line in repriced) == [
        1200,
        3000,
        4000,
    ]
    for line in repriced:
        assert_null(line, "net_receipts_cents")
