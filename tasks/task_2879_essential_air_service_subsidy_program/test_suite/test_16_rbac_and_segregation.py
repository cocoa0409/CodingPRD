"""Access-control corners: the authentication rung answering before anything
else, endpoint- and action-level role exclusivity, ownership for the two
entity-backed roles, and the two segregation-of-duties controls.

The harness restarts the API against an empty database before every test, so
each test builds all of its own preconditions through declared endpoints.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_money, assert_ratio, assert_score
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    DEFAULT_CLOCK,
    EVAL_SELECTED,
    PAYMENT_APPROVE,
    PAYMENT_APPROVED,
    PAYMENT_COMPUTED,
    PAYMENT_DISBURSE,
    PAYMENT_DISBURSED,
    PERIOD_OPEN,
    PERIOD_PAID,
    PERIOD_REPORTED,
    PROPOSAL_SUBMITTED,
    PROPOSAL_WITHDRAW,
    RENEG_ACCEPT,
    RENEG_REJECT,
    RENEG_REJECTED,
    RENEG_REQUESTED,
    RENEG_WITHDRAW,
    ROLE_ELIGIBILITY_ANALYST,
    ROLE_PROGRAM_ADMIN,
    ROLE_SELECTION_OFFICER,
    SOLICITATION_CLOSED,
)
from test_helpers.test_users import (
    ADMIN,
    ADMIN_NEGOTIATOR,
    ANALYST,
    OFFICER,
    USER_ADMIN,
    USER_ANALYST,
    headers_empty_role,
    headers_empty_user_id,
    headers_missing_role,
    headers_missing_user_id,
    headers_unknown_role,
    make_carrier_headers,
    make_community_rep_headers,
    make_operator_headers,
)


DUAL_ANALYST_USER = "analyst-dual"
DUAL_ADMIN_USER = "admin-both"
INDEPENDENT_ADMIN_USER = "admin-second"

# A twelve-month agreement at 1,200,000.00 pays exactly 100,000.00 a month.
TWELVE_MONTH_TERMS = {
    "annual_subsidy_request_usd": 1200000.00,
    "term_months": 12,
}

CLEAN_MONTH = {
    "scheduled_departures": 100,
    "completed_departures": 100,
    "cancelled_carrier_departures": 0,
    "cancelled_weather_departures": 0,
    "seats_offered": 1900,
    "passengers_enplaned": 700,
}

# 2026-08-01T00:00:00Z advanced by the 180-day cooling-off period.
COOLING_OFF_BOUNDARY = "2027-01-28T00:00:00Z"


def _closed_solicitation_certified_by(api: ApiClient, analyst_user: str):
    """One community whose determination was certified by `analyst_user`, with a
    CLOSED solicitation carrying a single submitted twelve-month candidate."""
    fx.set_clock(api, DEFAULT_CLOCK)
    community = validate_success(
        api.create_community(f.community_payload(), ADMIN), 201
    )
    determination = validate_success(
        api.create_eligibility_determination(
            community["id"],
            f.determination_payload(),
            make_operator_headers(analyst_user, ROLE_ELIGIBILITY_ANALYST),
        ),
        201,
    )
    assert determination["certified_by_user_id"] == analyst_user
    aircraft = validate_success(
        api.create_aircraft_type(f.aircraft_type_payload(), ADMIN), 201
    )
    carrier = validate_success(api.create_carrier(f.carrier_payload(), ADMIN), 201)
    fx.publish_fuel_index(api, "2026-08", 2.4000)
    solicitation = fx.open_solicitation(api, community["id"])
    proposal = fx.submitted_proposal(
        api,
        solicitation["id"],
        carrier["id"],
        aircraft["id"],
        **TWELVE_MONTH_TERMS,
    )
    solicitation = fx.close_solicitation(api, solicitation["id"])
    return {
        "community": community,
        "carrier": carrier,
        "solicitation": solicitation,
        "proposal": proposal,
    }


# ─── rbac / requests_without_a_usable_identity_are_rejected_first ─────

def test_reads_with_an_unusable_identity_header_are_unauthenticated(api: ApiClient):
    """Absent and empty identity headers are all refused before the row is read.

    "If either header is absent, present but empty, or if `X-User-Role` does not name one of the five roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/requests_without_a_usable_identity_are_rejected_first
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    community = validate_success(
        api.create_community(f.community_payload(), ADMIN), 201
    )

    for headers in (
        headers_missing_user_id(ROLE_PROGRAM_ADMIN),
        headers_empty_user_id(ROLE_PROGRAM_ADMIN),
        headers_missing_role(USER_ADMIN),
        headers_empty_role(USER_ADMIN),
    ):
        refused = api.get_community(community["id"], headers)
        validate_error(refused, E.ERR_UNAUTHENTICATED, 401)

    readable = validate_success(api.get_community(community["id"], ADMIN))
    assert readable["code"] == "HYS"


def test_a_write_with_an_empty_user_id_leaves_nothing_behind(api: ApiClient):
    """The authentication rung fires before the row would be created.

    "Every request to this API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role that user is acting in."

    Design: Corner/rbac/requests_without_a_usable_identity_are_rejected_first
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    validate_success(api.create_community(f.community_payload(), ADMIN), 201)

    refused = api.create_community(
        f.second_community_payload(), headers_empty_user_id(ROLE_PROGRAM_ADMIN)
    )
    validate_error(refused, E.ERR_UNAUTHENTICATED, 401)

    rows, meta = validate_paginated(api.list_communities(ADMIN))
    assert meta["total_count"] == 1
    assert [row["code"] for row in rows] == ["HYS"]


def test_an_undeclared_role_name_is_unauthenticated_rather_than_unauthorized(api: ApiClient):
    """A role outside the declared five never reaches the authorisation rung.

    "The five roles are `ProgramAdmin`, `EligibilityAnalyst`, `SelectionOfficer`, `CommunityRepresentative` and `Carrier`."

    Design: Corner/rbac/requests_without_a_usable_identity_are_rejected_first
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    validate_success(api.create_community(f.community_payload(), ADMIN), 201)

    refused = api.list_communities(headers_unknown_role("auditor-1", "Auditor"))
    validate_error(refused, E.ERR_UNAUTHENTICATED, 401)

    _, meta = validate_paginated(api.list_communities(ADMIN))
    assert meta["total_count"] == 1


# ─── rbac / exclusive_operations_are_refused_to_every_other_role ──────

def test_reference_data_and_determinations_stay_with_their_own_roles(api: ApiClient):
    """The analyst cannot register a community and the admin cannot determine one.

    "An `EligibilityAnalyst` determines community eligibility, distance bands and per-passenger caps, and nothing else."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    community = validate_success(
        api.create_community(f.community_payload(), ADMIN), 201
    )
    validate_success(
        api.create_eligibility_determination(
            community["id"], f.determination_payload(), ANALYST
        ),
        201,
    )

    analyst_write = api.create_community(f.second_community_payload(), ANALYST)
    validate_error(analyst_write, E.ERR_UNAUTHORIZED, 403)
    _, community_meta = validate_paginated(api.list_communities(ADMIN))
    assert community_meta["total_count"] == 1

    admin_determination = api.create_eligibility_determination(
        community["id"], f.determination_payload(waiver_requested=True), ADMIN
    )
    validate_error(admin_determination, E.ERR_UNAUTHORIZED, 403)
    rows, determination_meta = validate_paginated(
        api.list_eligibility_determinations(community["id"], ADMIN)
    )
    assert determination_meta["total_count"] == 1
    assert rows[0]["certified_by_user_id"] == USER_ANALYST


def test_awarding_and_period_opening_are_refused_to_the_wrong_role(api: ApiClient):
    """A carrier cannot award itself and the awarding officer cannot open a month.

    "When both headers are well formed but the named role is not authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    setup = _closed_solicitation_certified_by(api, USER_ANALYST)
    carrier_headers = make_carrier_headers(setup["carrier"]["id"])

    carrier_award = api.create_selection_order(
        setup["solicitation"]["id"],
        f.selection_order_payload(order_note="carrier awarding itself"),
        carrier_headers,
    )
    validate_error(carrier_award, E.ERR_UNAUTHORIZED, 403)
    still_closed = validate_success(
        api.get_solicitation(setup["solicitation"]["id"], ADMIN)
    )
    assert still_closed["status"] == SOLICITATION_CLOSED

    agreement = fx.issue_selection_order(api, setup["solicitation"]["id"])
    assert agreement["status"] == AGREEMENT_ACTIVE

    officer_period = api.create_service_period(
        f.service_period_payload(agreement["id"], "2026-08"), OFFICER
    )
    validate_error(officer_period, E.ERR_UNAUTHORIZED, 403)
    _, period_meta = validate_paginated(
        api.list_service_periods(ADMIN, {"agreement_id": agreement["id"]})
    )
    assert period_meta["total_count"] == 0

    opened = validate_success(
        api.create_service_period(
            f.service_period_payload(agreement["id"], "2026-08"), ADMIN
        ),
        201,
    )
    assert opened["status"] == PERIOD_OPEN


def test_the_renegotiation_action_endpoint_splits_below_the_role(api: ApiClient):
    """Owning the renegotiation does not give the carrier the program's verbs.

    "The rate-renegotiation action endpoint admits both `ProgramAdmin` and `Carrier`, but `COUNTER`, `ACCEPT` and `REJECT` are reserved to `ProgramAdmin` while `REVISE` and `WITHDRAW` are reserved to `Carrier`."

    Design: Corner/rbac/exclusive_operations_are_refused_to_every_other_role
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK, with_second_carrier=False)
    fx.set_clock(api, COOLING_OFF_BOUNDARY)
    renegotiation = fx.file_cost_renegotiation(api, award, 0.0400, 1660000.00)
    assert renegotiation["status"] == RENEG_REQUESTED

    carrier_accept = api.renegotiation_action(
        renegotiation["id"],
        f.renegotiation_action_payload(
            RENEG_ACCEPT, action_note="carrier accepting its own request"
        ),
        award.carrier_headers,
    )
    validate_error(carrier_accept, E.ERR_UNAUTHORIZED, 403)

    admin_withdraw = api.renegotiation_action(
        renegotiation["id"],
        f.renegotiation_action_payload(
            RENEG_WITHDRAW, action_note="program office withdrawing for the carrier"
        ),
        ADMIN_NEGOTIATOR,
    )
    validate_error(admin_withdraw, E.ERR_UNAUTHORIZED, 403)

    unchanged = validate_success(api.get_rate_renegotiation(renegotiation["id"], ADMIN))
    assert unchanged["status"] == RENEG_REQUESTED
    assert unchanged["revision_count"] == 0

    rejected = validate_success(
        api.renegotiation_action(
            renegotiation["id"],
            f.renegotiation_action_payload(RENEG_REJECT, action_note="not documented"),
            ADMIN_NEGOTIATOR,
        )
    )
    assert rejected["status"] == RENEG_REJECTED


# ─── rbac / entity_backed_roles_cannot_reach_another_owners_rows ───────

def _two_carriers_one_award(api: ApiClient):
    """Carrier 1 holds the award for community 1 with an OPEN 2026-08 month;
    carrier 2 has only its own draft proposal on community 2's solicitation."""
    reference = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    second_community = fx.register_second_community(api)
    first_solicitation = fx.open_solicitation(api, reference.community_id)
    second_solicitation = fx.open_solicitation(api, second_community["id"])
    first_proposal = fx.submitted_proposal(
        api,
        first_solicitation["id"],
        reference.carrier_id,
        reference.aircraft_type_id,
    )
    second_proposal = fx.draft_proposal(
        api,
        second_solicitation["id"],
        reference.second_carrier_id,
        reference.aircraft_type_id,
        annual_subsidy_request_usd=1550000.00,
    )
    fx.close_solicitation(api, first_solicitation["id"])
    agreement = fx.issue_selection_order(api, first_solicitation["id"])
    period = fx.open_period(api, agreement["id"], "2026-08")
    return {
        "ref": reference,
        "second_community": second_community,
        "first_solicitation": validate_success(
            api.get_solicitation(first_solicitation["id"], ADMIN)
        ),
        "second_solicitation": validate_success(
            api.get_solicitation(second_solicitation["id"], ADMIN)
        ),
        "first_proposal": first_proposal,
        "second_proposal": second_proposal,
        "agreement": agreement,
        "period": period,
    }


def test_a_carrier_cannot_act_on_another_carriers_proposal(api: ApiClient):
    """The ownership rung answers before the proposal's own state is considered.

    "Concretely, a `Carrier` may only act on proposals whose `carrier_id` equals its own `X-User-ID`, on service periods whose agreement's `carrier_id` equals it, and on rate renegotiations whose agreement's `carrier_id` equals it; a `CommunityRepresentative` may only file preferences against solicitations whose community is itself, and may only file or withdraw termination petitions whose `community_id` equals it."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_another_owners_rows
    """
    world = _two_carriers_one_award(api)
    intruder = make_carrier_headers(world["ref"].second_carrier_id)

    refused = api.proposal_action(
        world["first_proposal"]["id"],
        f.proposal_action_payload(PROPOSAL_WITHDRAW),
        intruder,
    )
    validate_error(refused, E.ERR_FORBIDDEN_RESOURCE_OWNER, 403)

    unchanged = validate_success(
        api.get_proposal(world["first_proposal"]["id"], ADMIN)
    )
    assert unchanged["submission_state"] == PROPOSAL_SUBMITTED
    assert unchanged["evaluation_state"] == EVAL_SELECTED


def test_a_carrier_cannot_report_or_renegotiate_on_another_carriers_agreement(api: ApiClient):
    """Carrier ownership is reached through the parent agreement, not a column.

    "An authenticated, endpoint-authorised caller that reaches for a resource belonging to somebody else is rejected with `ERR_FORBIDDEN_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_another_owners_rows
    """
    world = _two_carriers_one_award(api)
    intruder = make_carrier_headers(world["ref"].second_carrier_id)

    foreign_report = api.report_service_period(
        world["period"]["id"],
        f.report_payload(
            scheduled_departures=100,
            completed_departures=60,
            cancelled_carrier_departures=40,
            cancelled_weather_departures=0,
            seats_offered=1140,
            passengers_enplaned=400,
        ),
        intruder,
    )
    validate_error(foreign_report, E.ERR_FORBIDDEN_RESOURCE_OWNER, 403)
    untouched = validate_success(api.get_service_period(world["period"]["id"], ADMIN))
    assert untouched["status"] == PERIOD_OPEN
    assert untouched["scheduled_departures"] == 0
    assert untouched["completed_departures"] == 0
    assert untouched["period_completion_factor"] is None

    foreign_renegotiation = api.create_rate_renegotiation(
        f.cost_renegotiation_payload(
            world["agreement"]["id"],
            0.0400,
            1660000.00,
            justification="another carriers agreement",
        ),
        intruder,
    )
    validate_error(foreign_renegotiation, E.ERR_FORBIDDEN_RESOURCE_OWNER, 403)
    _, renegotiation_meta = validate_paginated(api.list_rate_renegotiations(ADMIN))
    assert renegotiation_meta["total_count"] == 0

    owner_report = validate_success(
        api.report_service_period(
            world["period"]["id"],
            f.report_payload(**CLEAN_MONTH),
            make_carrier_headers(world["ref"].carrier_id),
        )
    )
    assert owner_report["status"] == PERIOD_REPORTED
    assert_ratio(
        owner_report["period_completion_factor"], 1.0000, "period_completion_factor"
    )


def test_a_community_representative_cannot_file_for_another_community(api: ApiClient):
    """Community ownership is checked before the expected-version comparison.

    "The ownership rule guards exactly nine write operations: proposal creation, proposal submission-dimension actions, preference filing, monthly report filing, report amendment, petition filing, petition withdrawal, renegotiation filing and renegotiation actions."

    Design: Corner/rbac/entity_backed_roles_cannot_reach_another_owners_rows
    """
    world = _two_carriers_one_award(api)
    foreign_solicitation = world["second_solicitation"]

    refused_filing = api.file_preferences(
        foreign_solicitation["id"],
        f.preference_filing_payload(
            foreign_solicitation["version"] + 5,
            f.ranking_entries(world["second_proposal"]["id"]),
            rationale="wrong community filing",
        ),
        make_community_rep_headers(world["ref"].community_id),
    )
    validate_error(refused_filing, E.ERR_FORBIDDEN_RESOURCE_OWNER, 403)
    still_unfiled = validate_success(
        api.get_solicitation(foreign_solicitation["id"], ADMIN)
    )
    assert still_unfiled["preference_filing_count"] == 0
    assert still_unfiled["version"] == foreign_solicitation["version"]

    refused_petition = api.create_termination_petition(
        f.petition_payload(
            world["ref"].community_id,
            world["agreement"]["id"],
            narrative="filed by the wrong community",
        ),
        make_community_rep_headers(world["second_community"]["id"]),
    )
    validate_error(refused_petition, E.ERR_FORBIDDEN_RESOURCE_OWNER, 403)
    _, petition_meta = validate_paginated(api.list_termination_petitions(ADMIN))
    assert petition_meta["total_count"] == 0


# ─── rbac / one_user_may_not_hold_both_sides_of_a_control ──────────────

def test_the_certifying_analyst_may_not_issue_that_communitys_selection_order(api: ApiClient):
    """The same user id cannot both certify eligibility and award the carrier.

    "When a selection order is issued for a community, the acting `X-User-ID` must differ from the `certified_by_user_id` recorded on that community's latest eligibility determination — the determination with the greatest `created_at` for the community."

    Design: Corner/rbac/one_user_may_not_hold_both_sides_of_a_control
    """
    setup = _closed_solicitation_certified_by(api, DUAL_ANALYST_USER)

    refused = api.create_selection_order(
        setup["solicitation"]["id"],
        f.selection_order_payload(order_note="the certifying analyst awarding"),
        make_operator_headers(DUAL_ANALYST_USER, ROLE_SELECTION_OFFICER),
    )
    validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES, 403)

    still_closed = validate_success(
        api.get_solicitation(setup["solicitation"]["id"], ADMIN)
    )
    assert still_closed["status"] == SOLICITATION_CLOSED
    assert still_closed["selected_proposal_id"] is None
    unscored = validate_success(api.get_proposal(setup["proposal"]["id"], ADMIN))
    assert unscored["composite_score"] is None
    _, agreement_meta = validate_paginated(api.list_service_agreements(ADMIN))
    assert agreement_meta["total_count"] == 0

    agreement = validate_success(
        api.create_selection_order(
            setup["solicitation"]["id"],
            f.selection_order_payload(order_note="an independent officer awarding"),
            OFFICER,
        ),
        201,
    )
    assert agreement["status"] == AGREEMENT_ACTIVE
    scored = validate_success(api.get_proposal(setup["proposal"]["id"], ADMIN))
    assert_score(scored["composite_score"], 60.0000, "composite_score")


def test_the_approving_admin_may_not_disburse_the_same_payment(api: ApiClient):
    """Cash needs two different operator ids, not merely two ProgramAdmin calls.

    "When a subsidy payment is disbursed, the acting `X-User-ID` must differ from the payment's `approved_by_user_id`: the operator who approved a payment may not release its cash."

    Design: Corner/rbac/one_user_may_not_hold_both_sides_of_a_control
    """
    setup = _closed_solicitation_certified_by(api, USER_ANALYST)
    agreement = fx.issue_selection_order(api, setup["solicitation"]["id"])
    period = fx.open_period(api, agreement["id"], "2026-08")
    fx.file_report(api, period["id"], setup["carrier"]["id"], **CLEAN_MONTH)
    fx.certify_period(api, period["id"])
    payment = fx.payment_for_period(api, period["id"])
    assert payment["status"] == PAYMENT_COMPUTED

    approved = validate_success(
        api.payment_action(
            payment["id"],
            f.payment_action_payload(PAYMENT_APPROVE),
            make_operator_headers(DUAL_ADMIN_USER, ROLE_PROGRAM_ADMIN),
        )
    )
    assert approved["status"] == PAYMENT_APPROVED
    assert approved["approved_by_user_id"] == DUAL_ADMIN_USER

    refused = api.payment_action(
        payment["id"],
        f.payment_action_payload(PAYMENT_DISBURSE),
        make_operator_headers(DUAL_ADMIN_USER, ROLE_PROGRAM_ADMIN),
    )
    validate_error(refused, E.ERR_SEGREGATION_OF_DUTIES, 403)

    unchanged = validate_success(api.get_subsidy_payment(payment["id"], ADMIN))
    assert unchanged["status"] == PAYMENT_APPROVED
    assert unchanged["disbursed_by_user_id"] is None
    held = validate_success(api.get_service_agreement(agreement["id"], ADMIN))
    assert_money(held["disbursed_to_date_usd"], 0.00, "disbursed_to_date_usd")

    disbursed = validate_success(
        api.payment_action(
            payment["id"],
            f.payment_action_payload(PAYMENT_DISBURSE),
            make_operator_headers(INDEPENDENT_ADMIN_USER, ROLE_PROGRAM_ADMIN),
        )
    )
    assert disbursed["status"] == PAYMENT_DISBURSED
    assert disbursed["disbursed_by_user_id"] == INDEPENDENT_ADMIN_USER
    paid = validate_success(api.get_service_period(period["id"], ADMIN))
    assert paid["status"] == PERIOD_PAID
    ledger = validate_success(api.get_service_agreement(agreement["id"], ADMIN))
    assert_money(ledger["disbursed_to_date_usd"], 100000.00, "disbursed_to_date_usd")
