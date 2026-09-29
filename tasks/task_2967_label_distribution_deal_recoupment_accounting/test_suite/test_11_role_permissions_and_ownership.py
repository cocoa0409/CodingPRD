"""
Role permissions, resource ownership and segregation of duties across the whole
endpoint surface (PRD Sections 2.1, 2.8 and the Section 4 endpoint/role table).

Every test here translates one instance of the corner-case index section `rbac`.
The three distinct 403 outcomes are kept strictly apart: ERR_ROLE_NOT_PERMITTED
(wrong role for the operation), ERR_NOT_RESOURCE_OWNER (right role, another
entity's record) and ERR_SEGREGATION_OF_DUTIES (right role, right record, but the
actor already played the incompatible part).
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID, validate_error, validate_success,
)

from test_helpers import factories as f
from test_helpers import (
    ANALYST,
    BIZ_AFFAIRS,
    BIZ_AFFAIRS_2,
    LABEL_ADMIN,
    USER_ANALYST,
    USER_BIZ_AFFAIRS,
    USER_LABEL_ADMIN,
    make_analyst_headers,
    make_artist_headers,
    make_biz_affairs_headers,
    make_partner_headers,
    DEFAULT_CLOCK_INSTANT,
    DEFAULT_DSP_CODE,
    INITIAL_VERSION,
    AUDIT_COST_BEARER_ARTIST,
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_NONE,
    AUDIT_STATUS_REQUESTED,
    DEAL_STATUS_EXECUTED,
    FORMAT_CASSETTE,
    OBJECTION_REASON_COST_DISPUTE,
    OBJECTION_REASON_MISSING_REVENUE,
    OBJECTION_REASON_RATE_DISPUTE,
    RECOUPABILITY_FULL,
    REPORT_STATUS_ACCEPTED,
    REPORT_STATUS_SUBMITTED,
    RESOLUTION_DENIED,
    SPEND_CATEGORY_DIGITAL_ADS,
    SPEND_DECISION_APPROVE,
    SPEND_STATUS_APPROVED,
    SPEND_STATUS_SUBMITTED,
    STATEMENT_STATUS_FINALIZED,
    STATEMENT_STATUS_ISSUED,
    STATEMENT_STATUS_OBJECTED,
    STATEMENT_STATUS_PREPARED,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    assert_field,
    assert_field_money,
    assert_fields_money,
    assert_instant_equals,
    assert_null,
    assert_pct_equals,
    assert_status,
    assert_version_is,
    deal_version,
    do_finalize_statement,
    do_issue_statement,
    do_manufacture,
    do_object,
    do_prepare_statement,
    do_request_audit,
    do_set_clock,
    do_submit_spend,
    given_accepted_report,
    given_active_agreement,
    given_rate_cards,
    given_released_catalog,
    mk_artist,
    mk_distributor,
    mk_run,
    mk_spend,
    mk_statement,
    read_deal,
    read_distributor,
    read_report_lines,
    read_spend,
    read_statement,
)

FLAT_AGREEMENT = {
    "advance_amount_cents": 0,
    "recording_costs_cents": 0,
    "recording_recoupable_pct": "0.0000",
    "marketing_recoup_share_pct": "0.0000",
}


def _flat_agreement(rate):
    terms = dict(FLAT_AGREEMENT)
    terms["royalty_rate_pct"] = rate
    terms["escalated_royalty_rate_pct"] = rate
    return terms


def test_each_role_drives_its_own_leg_of_the_revenue_reporting_chain(api):
    """Section 4 gives each leg of the revenue chain to one role only. The
    `DistributionPartner` alone may open a report and submit it, which "resolves
    every line's rate card and prices the report"; the `RoyaltyAnalyst` alone may
    accept it, which "allocates net receipts to lines and releases". A
    250,000-stream line at 0.0004/stream grosses 100,000 cents, the 0.1500
    distribution fee takes 15,000 and net receipts are 85,000.

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"advance_amount_cents": 0, "objection_window_days": 30,
                 "post_term_collection_days": 90},
        releases=[{"advance_share_cents": 0, "title": "Role Relay"}],
    )
    ctx = given_rate_cards(api, ctx)
    partner = ctx["partner_headers"]

    report = validate_success(
        api.create_report(f.report_payload(ctx["deal_id"]), partner), 201)
    validate_success(
        api.append_line(
            report["id"],
            f.line_payload(ctx["release_id"], stream_count=250000),
            partner),
        201)
    submitted = validate_success(api.submit_report(report["id"], partner), 200)
    assert_status(submitted, REPORT_STATUS_SUBMITTED)
    assert_fields_money(
        submitted,
        gross_receipts_cents=100000,
        distributor_share_cents=15000,
        net_receipts_cents=85000,
    )

    version = deal_version(api, ctx["deal_id"], headers=ANALYST)
    accepted = validate_success(
        api.accept_report(report["id"], f.accept_report_payload(version), ANALYST),
        200)
    assert_status(accepted, REPORT_STATUS_ACCEPTED)
    assert_field_money(accepted, "advance_applied_cents", 0)

    lines = read_report_lines(api, report["id"], headers=ANALYST)
    assert len(lines) == 1
    assert_field_money(lines[0], "net_receipts_cents", 85000)


def test_statement_publication_hands_off_between_the_back_office_roles(api):
    """Section 4 splits statement publication three ways: the `RoyaltyAnalyst`
    prepares it, "Publication is a business-affairs action", and objecting is
    where "the artist files an objection inside the window". "Issuing stamps
    issued_at from the logical clock, records issued_by_user_id, and sets
    objection_deadline to issued_at plus the deal's objection_window_days". On
    85,000 net receipts a 0.1000 royalty pays 8,500 cents, and a 30-day window
    from 2026-08-01 gives a deadline of 2026-08-31T00:00:00.000Z.

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"advance_amount_cents": 0, "objection_window_days": 30,
                 "post_term_collection_days": 90},
        releases=[{"advance_share_cents": 0, "title": "Hand Off"}],
    )
    ctx = given_active_agreement(
        api, ctx, agreement_kw=_flat_agreement("0.1000"))
    ctx = given_accepted_report(api, ctx, lines=[{"stream_count": 250000}])

    created = validate_success(
        api.create_statement(f.statement_payload(ctx["agreement_id"]), ANALYST),
        201)
    prepared = validate_success(
        api.prepare_statement(created["id"], ANALYST), 200)
    assert_status(prepared, STATEMENT_STATUS_PREPARED)
    assert_field_money(prepared, "net_payable_cents", 8500)
    assert_field(prepared, "prepared_by_user_id", USER_ANALYST)

    issued = validate_success(
        api.issue_statement(created["id"], BIZ_AFFAIRS), 200)
    assert_status(issued, STATEMENT_STATUS_ISSUED)
    assert_field(issued, "issued_by_user_id", USER_BIZ_AFFAIRS)
    assert_instant_equals(
        issued["objection_deadline"], "2026-08-31T00:00:00.000Z",
        "objection_deadline")

    objected = validate_success(
        api.object_statement(
            created["id"],
            f.object_payload(
                OBJECTION_REASON_MISSING_REVENUE, 1000,
                "One territory looks under-reported."),
            ctx["artist_headers"]),
        200)
    assert_status(objected, STATEMENT_STATUS_OBJECTED)
    assert_field(objected, "objection_reason_code", OBJECTION_REASON_MISSING_REVENUE)
    assert_instant_equals(
        objected["objection_filed_at"], DEFAULT_CLOCK_INSTANT,
        "objection_filed_at")


def test_back_office_roles_cannot_run_each_others_exclusive_operations(api):
    """Section 4's "Authorized Role(s) column is exhaustive: a role absent from a
    row is refused with ERR_ROLE_NOT_PERMITTED", and Section 2.8 ranks role
    authorization (2) above path existence (3), so the wrong role loses even on an
    id that does not exist.

    Design: Corner/rbac/cross_role_exclusive_operations_are_rejected
    """
    validate_error(
        api.issue_statement(NON_EXISTENT_UUID, LABEL_ADMIN),
        ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.decide_spend(
            NON_EXISTENT_UUID, f.decide_spend_payload(SPEND_DECISION_APPROVE),
            ANALYST),
        ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.prepare_statement(NON_EXISTENT_UUID, BIZ_AFFAIRS),
        ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.accept_report(
            NON_EXISTENT_UUID, f.accept_report_payload(INITIAL_VERSION),
            BIZ_AFFAIRS),
        ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.object_statement(
            NON_EXISTENT_UUID,
            f.object_payload(
                OBJECTION_REASON_RATE_DISPUTE, 1, "Not my statement."),
            BIZ_AFFAIRS),
        ERR_ROLE_NOT_PERMITTED)


def test_entity_backed_roles_are_refused_operations_outside_their_list(api):
    """The two entity-backed roles are confined to their own rows of Section 4's
    table, where "the Authorized Role(s) column is exhaustive: a role absent from
    a row is refused with ERR_ROLE_NOT_PERMITTED". A refused write must leave the
    probe distributor at its creation version of 1.

    Design: Corner/rbac/cross_role_exclusive_operations_are_rejected
    """
    distributor = mk_distributor(
        api, name="Gate Probe", legal_entity="Gate Probe Holdings Ltd",
        default_returns_reserve_pct=f.pct4("0.1000"))
    artist = mk_artist(api, legal_name="Ilse Marrow")
    artist_headers = make_artist_headers(artist["id"])
    partner_headers = make_partner_headers(distributor["id"])

    validate_error(
        api.finalize_statement(NON_EXISTENT_UUID, artist_headers),
        ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.liquidate_reserve(
            NON_EXISTENT_UUID,
            f.liquidate_payload(INITIAL_VERSION, f.pct4("0.5000")),
            artist_headers),
        ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.create_distributor(
            f.distributor_payload(
                name="Rogue Setup", legal_entity="Rogue Setup Ltd"),
            partner_headers),
        ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.request_audit(
            NON_EXISTENT_UUID,
            f.request_audit_payload("2026-04-01", "2026-06-30"),
            partner_headers),
        ERR_ROLE_NOT_PERMITTED)

    still = read_distributor(api, distributor["id"])
    assert_field(still, "name", "Gate Probe")
    assert_version_is(still, INITIAL_VERSION, "distributor")


def test_only_the_owning_partner_may_ship_or_record_returns_on_a_run(api):
    """Ownership is a distinct, lower-ranked gate than role: "Ownership is
    enforced on exactly seven operations: ... shipping a manufacturing run,
    recording returns against a run". Shipping 900 units at 700 cents grosses
    630,000 less 200,000 manufacturing cost, and 50 returns cut net receipts to
    (900-50)*700 - 200,000 = 395,000.

    Design: Corner/rbac/distribution_partner_cannot_ship_another_distributors_run
    """
    ctx = given_released_catalog(
        api,
        distributor_kw={
            "name": "Harbourside Physical",
            "legal_entity": "Harbourside Physical Ltd",
            "default_returns_reserve_pct": f.pct4("0.1000"),
        },
        releases=[{"formats": (FORMAT_CASSETTE,), "advance_share_cents": 0,
                   "title": "Tape Only"}],
    )
    other = mk_distributor(
        api, name="Kettle Row Distribution",
        legal_entity="Kettle Row Distribution GmbH",
        default_returns_reserve_pct=f.pct4("0.2000"))
    stranger = make_partner_headers(other["id"])

    run = mk_run(
        api, ctx["release_id"], ctx["dist_id"],
        units_planned=1000, unit_manufacturing_cost_cents=200)
    run = do_manufacture(api, run["id"], 1000)
    baseline = run["version"]

    ship_body = f.ship_payload(900, 700)
    validate_error(
        api.ship_run(run["id"], ship_body, stranger), ERR_NOT_RESOURCE_OWNER)
    shipped = validate_success(
        api.ship_run(run["id"], ship_body, ctx["partner_headers"]), 200)
    assert_fields_money(
        shipped, physical_net_receipts_cents=430000, reserve_initial_cents=63000)

    returns_body = f.record_returns_payload(50)
    validate_error(
        api.record_returns(run["id"], returns_body, stranger),
        ERR_NOT_RESOURCE_OWNER)
    returned = validate_success(
        api.record_returns(run["id"], returns_body, ctx["partner_headers"]), 200)
    assert_field(returned, "units_returned", 50)
    assert_field_money(returned, "physical_net_receipts_cents", 395000)
    assert_version_is(returned, baseline + 2, "physical run")

    seen = validate_success(api.get_run(run["id"], stranger), 200)
    assert_field(seen, "id", run["id"])


def test_an_artist_may_only_read_and_object_to_its_own_statement(api):
    """"An objection may be filed only by the artist the statement belongs to:
    the acting X-User-ID must equal the artist_id of the statement's agreement,
    otherwise ERR_NOT_RESOURCE_OWNER (403)", and the same ownership test guards
    reading a single statement and requesting its audit. On 85,000 net receipts
    the 0.1000 agreement pays 8,500 and the 0.0500 agreement pays 4,250.

    Design: Corner/rbac/artist_cannot_touch_another_artists_statement
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"advance_amount_cents": 0, "objection_window_days": 30,
                 "post_term_collection_days": 90},
        releases=[{"advance_share_cents": 0, "title": "Shared Credit"}],
    )
    artist_b = mk_artist(api, legal_name="Bo Lantern")
    b_headers = make_artist_headers(artist_b["id"])

    ctx = given_active_agreement(
        api, ctx, agreement_kw=_flat_agreement("0.1000"))
    agreement_a = ctx["agreement_id"]
    ctx = given_active_agreement(
        api, ctx, artist_id=artist_b["id"],
        agreement_kw=_flat_agreement("0.0500"))
    agreement_b = ctx["agreement_id"]
    ctx = given_accepted_report(api, ctx, lines=[{"stream_count": 250000}])

    statement_a = mk_statement(api, agreement_a)
    prepared_a = do_prepare_statement(api, statement_a["id"])
    assert_field_money(prepared_a, "net_payable_cents", 8500)
    do_issue_statement(api, statement_a["id"])

    statement_b = mk_statement(api, agreement_b)
    prepared_b = do_prepare_statement(api, statement_b["id"])
    assert_field_money(prepared_b, "net_payable_cents", 4250)
    do_issue_statement(api, statement_b["id"])

    objection = f.object_payload(
        OBJECTION_REASON_RATE_DISPUTE, 500, "The applied rate looks wrong.")
    validate_error(
        api.get_statement(statement_a["id"], b_headers), ERR_NOT_RESOURCE_OWNER)
    validate_error(
        api.object_statement(statement_a["id"], objection, b_headers),
        ERR_NOT_RESOURCE_OWNER)
    validate_error(
        api.request_audit(
            statement_a["id"],
            f.request_audit_payload("2026-04-01", "2026-06-30"),
            b_headers),
        ERR_NOT_RESOURCE_OWNER)

    untouched = read_statement(api, statement_a["id"])
    assert_status(untouched, STATEMENT_STATUS_ISSUED)
    assert_null(untouched, "objection_reason_code", "objection_filed_at")
    assert_field(untouched, "audit_status", AUDIT_STATUS_NONE)

    own = validate_success(api.get_statement(statement_b["id"], b_headers), 200)
    assert_field_money(own, "net_payable_cents", 4250)
    own_objected = validate_success(
        api.object_statement(statement_b["id"], objection, b_headers), 200)
    assert_status(own_objected, STATEMENT_STATUS_OBJECTED)

    a_own = validate_success(
        api.get_statement(statement_a["id"], ctx["artist_headers"]), 200)
    assert_field_money(a_own, "net_payable_cents", 8500)


def test_the_statements_preparer_may_neither_resolve_nor_conclude_on_it(api):
    """"the operator who prepared a statement may not issue it, resolve an
    objection on it, finalize it, or conclude its audit" - each of those refusals
    is ERR_SEGREGATION_OF_DUTIES (403). A second business-affairs operator may do
    all of them; on 8,500 net payable the audit materiality threshold is 425
    cents, so a 100-cent finding is immaterial and the artist bears the cost.

    Design: Corner/rbac/preparer_cannot_resolve_or_conclude_what_it_prepared
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"advance_amount_cents": 0, "objection_window_days": 30,
                 "post_term_collection_days": 90},
        releases=[{"advance_share_cents": 0, "title": "Four Eyes"}],
    )
    ctx = given_active_agreement(
        api, ctx, agreement_kw=_flat_agreement("0.1000"))
    ctx = given_accepted_report(api, ctx, lines=[{"stream_count": 250000}])

    preparer = make_analyst_headers(USER_BIZ_AFFAIRS)
    statement = mk_statement(api, ctx["agreement_id"], headers=preparer)
    prepared = do_prepare_statement(api, statement["id"], headers=preparer)
    assert_field(prepared, "prepared_by_user_id", USER_BIZ_AFFAIRS)
    assert_field_money(prepared, "net_payable_cents", 8500)

    validate_error(
        api.issue_statement(statement["id"], BIZ_AFFAIRS),
        ERR_SEGREGATION_OF_DUTIES)
    do_issue_statement(api, statement["id"], headers=BIZ_AFFAIRS_2)
    do_object(
        api, statement["id"], ctx["artist_headers"],
        OBJECTION_REASON_COST_DISPUTE, 500,
        "Recording cost recoupment is unclear.")
    baseline = read_statement(api, statement["id"])["version"]

    resolution = f.resolve_objection_payload(RESOLUTION_DENIED)
    validate_error(
        api.resolve_objection(statement["id"], resolution, BIZ_AFFAIRS),
        ERR_SEGREGATION_OF_DUTIES)
    still = read_statement(api, statement["id"])
    assert_status(still, STATEMENT_STATUS_OBJECTED)
    assert_null(still, "objection_resolution")
    assert_version_is(still, baseline, "statement")

    resolved = validate_success(
        api.resolve_objection(statement["id"], resolution, BIZ_AFFAIRS_2), 200)
    assert_status(resolved, STATEMENT_STATUS_ISSUED)
    assert_field(resolved, "objection_resolution", RESOLUTION_DENIED)

    do_set_clock(api, "2026-09-01T00:00:00.000Z")
    validate_error(
        api.finalize_statement(statement["id"], BIZ_AFFAIRS),
        ERR_SEGREGATION_OF_DUTIES)
    finalized = do_finalize_statement(api, statement["id"], headers=BIZ_AFFAIRS_2)
    assert_status(finalized, STATEMENT_STATUS_FINALIZED)

    requested = do_request_audit(
        api, statement["id"], ctx["artist_headers"], "2026-04-01", "2026-06-30")
    assert_field(requested, "audit_status", AUDIT_STATUS_REQUESTED)

    findings = f.conclude_audit_payload(100)
    validate_error(
        api.conclude_audit(statement["id"], findings, BIZ_AFFAIRS),
        ERR_SEGREGATION_OF_DUTIES)
    assert_field(
        read_statement(api, statement["id"]), "audit_status",
        AUDIT_STATUS_REQUESTED)

    concluded = validate_success(
        api.conclude_audit(statement["id"], findings, BIZ_AFFAIRS_2), 200)
    assert_field(concluded, "audit_status", AUDIT_STATUS_COMPLETED)
    assert_field(concluded, "audit_cost_bearer", AUDIT_COST_BEARER_ARTIST)
    assert_status(concluded, STATEMENT_STATUS_FINALIZED)
    assert_version_is(concluded, baseline + 4, "statement")


def test_the_operator_who_submitted_a_marketing_spend_may_not_decide_it(api):
    """"the operator who submitted a marketing spend may not decide it" - "an
    acting X-User-ID equal to the spend's stored requested_by_user_id is rejected
    with ERR_SEGREGATION_OF_DUTIES (403)". The requester is captured at
    submission, not creation: "A new spend has status DRAFT, with
    requested_by_user_id ... null" and submitting stores "the acting operator's
    X-User-ID ... as requested_by_user_id".

    Design: Corner/rbac/spend_requester_cannot_decide_its_own_spend
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"advance_amount_cents": 0, "marketing_budget_cents": 600000},
        releases=[{"advance_share_cents": 0, "title": "Campaign Trail"}],
    )
    spend = mk_spend(
        api, ctx["release_id"], category=SPEND_CATEGORY_DIGITAL_ADS,
        amount_cents=100000, vendor="Northlight Media")
    assert_null(spend, "requested_by_user_id", "decided_by_user_id", "approved_at")
    assert_field(spend, "recoupability", RECOUPABILITY_FULL)

    submitted = do_submit_spend(api, spend["id"], headers=LABEL_ADMIN)
    assert_status(submitted, SPEND_STATUS_SUBMITTED)
    assert_field(submitted, "requested_by_user_id", USER_LABEL_ADMIN)
    baseline = submitted["version"]

    decision = f.decide_spend_payload(SPEND_DECISION_APPROVE)
    validate_error(
        api.decide_spend(
            spend["id"], decision, make_biz_affairs_headers(USER_LABEL_ADMIN)),
        ERR_SEGREGATION_OF_DUTIES)
    still = read_spend(api, spend["id"])
    assert_status(still, SPEND_STATUS_SUBMITTED)
    assert_null(still, "decided_by_user_id", "approved_at")
    assert_version_is(still, baseline, "marketing spend")

    approved = validate_success(
        api.decide_spend(spend["id"], decision, BIZ_AFFAIRS), 200)
    assert_status(approved, SPEND_STATUS_APPROVED)
    assert_field(approved, "decided_by_user_id", USER_BIZ_AFFAIRS)
    assert_instant_equals(
        approved["approved_at"], DEFAULT_CLOCK_INSTANT, "approved_at")
    assert_version_is(approved, baseline + 1, "marketing spend")

    deal = read_deal(api, ctx["deal_id"], headers=ANALYST)
    assert_field_money(deal, "marketing_committed_cents", 100000)


def test_shared_reads_stop_at_each_roles_declared_endpoint_list(api):
    """A read is not universally shared just because it mutates nothing: Section
    4 admits only "LabelAdmin, DistributionPartner" on GET /distributors/{id},
    and omits Artist from GET /distribution-deals/{id}, GET /stream-rate-cards
    and GET /releases/{id}/dsp-revenue-lines. "the Authorized Role(s) column is
    exhaustive: a role absent from a row is refused with ERR_ROLE_NOT_PERMITTED".

    Design: Corner/rbac/shared_reads_stop_at_each_roles_declared_list
    """
    ctx = given_released_catalog(
        api,
        deal_kw={"advance_amount_cents": 0},
        releases=[{"advance_share_cents": 0, "title": "Read Scope"}],
    )
    ctx = given_active_agreement(
        api, ctx, agreement_kw=_flat_agreement("0.1000"))
    artist = ctx["artist_headers"]

    validate_error(
        api.get_distributor(ctx["dist_id"], ANALYST), ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.get_distributor(ctx["dist_id"], BIZ_AFFAIRS), ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.get_distributor(ctx["dist_id"], artist), ERR_ROLE_NOT_PERMITTED)
    owner_view = validate_success(
        api.get_distributor(ctx["dist_id"], ctx["partner_headers"]), 200)
    assert_field(owner_view, "name", "Vector Digital")

    validate_error(api.get_deal(ctx["deal_id"], artist), ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.list_rate_cards(artist, {"dsp_code": DEFAULT_DSP_CODE}),
        ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.list_release_revenue_lines(ctx["release_id"], artist),
        ERR_ROLE_NOT_PERMITTED)

    own_agreement = validate_success(
        api.get_agreement(ctx["agreement_id"], artist), 200)
    assert_pct_equals(
        own_agreement["royalty_rate_pct"], f.pct4("0.1000"), "royalty_rate_pct")

    deal = validate_success(api.get_deal(ctx["deal_id"], BIZ_AFFAIRS), 200)
    assert_status(deal, DEAL_STATUS_EXECUTED)
