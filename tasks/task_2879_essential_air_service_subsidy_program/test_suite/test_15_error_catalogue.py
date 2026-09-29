"""Error catalogue corners: resource-specific not-found and state errors, the
payment and renegotiation sequencing refusals, the continuity guard on an
immediate termination grant, and the fiscal ceiling on certification.

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
from test_helpers.assertions import (
    assert_error_meta_only,
    assert_instant,
    assert_money,
    assert_obligation_identity,
    assert_ratio,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    AGREEMENT_HOLD_IN,
    COMMUNITY_HOLD_IN,
    COMMUNITY_REGISTERED,
    COMMUNITY_SUBSIDIZED,
    CREATED_REASON_INITIAL,
    CREATED_REASON_REPLACEMENT,
    DECISION_GRANT_IMMEDIATE,
    DECISION_GRANT_WITH_HOLD_IN,
    DEFAULT_CLOCK,
    PAYMENT_APPROVE,
    PAYMENT_APPROVED,
    PAYMENT_COMPUTED,
    PAYMENT_DISBURSE,
    PAYMENT_DISBURSED,
    PERIOD_CERTIFIED,
    PERIOD_PAID,
    PERIOD_REPORTED,
    PETITION_GRANTED_WITH_HOLD_IN,
    PETITION_REASON_SERVICE_QUALITY,
    PETITION_UNDER_REVIEW,
    RENEG_ACCEPT,
    RENEG_REQUESTED,
    RENEG_WITHDRAW,
    RENEG_WITHDRAWN,
    SOLICITATION_OPEN,
)
from test_helpers.test_users import (
    ADMIN,
    ADMIN_APPROVER,
    ADMIN_DISBURSER,
    ADMIN_NEGOTIATOR,
    ADMIN_SECOND,
    OFFICER,
    USER_ADMIN_APPROVER,
)


UNKNOWN_PERIOD_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_PAYMENT_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_PETITION_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_RENEGOTIATION_ID = "00000000-0000-4000-8000-000000000004"

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

TERM_MONTHS_2026_08_TO_2027_07 = (
    "2026-08", "2026-09", "2026-10", "2026-11", "2026-12", "2027-01",
    "2027-02", "2027-03", "2027-04", "2027-05", "2027-06", "2027-07",
)

# 2026-08-01T00:00:00Z advanced by the 180-day cooling-off period.
COOLING_OFF_BOUNDARY = "2027-01-28T00:00:00Z"


def _twelve_month_award(api: ApiClient):
    return fx.build_award(
        api,
        clock=DEFAULT_CLOCK,
        proposal_overrides=dict(TWELVE_MONTH_TERMS),
        with_second_carrier=False,
    )


# ─── errors / unknown_ids_return_the_resource_specific_not_found_error ─

def test_unknown_ids_return_the_resource_specific_not_found_error(api: ApiClient):
    """Four empty collections answer with four different not-found ids.

    "The failing lookup selects the error: `ERR_COMMUNITY_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`, `ERR_AIRCRAFT_TYPE_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_SERVICE_PERIOD_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_PETITION_NOT_FOUND` or `ERR_RENEGOTIATION_NOT_FOUND` (all HTTP 404)."

    Design: Corner/errors/unknown_ids_return_the_resource_specific_not_found_error
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    period_response = api.get_service_period(UNKNOWN_PERIOD_ID, ADMIN)
    period_error = validate_error(
        period_response, E.ERR_SERVICE_PERIOD_NOT_FOUND, 404
    )
    assert isinstance(period_error["message"], str) and period_error["message"]
    assert period_response.json()["response_type"] == "error"
    assert_error_meta_only(period_response)

    payment_error = validate_error(
        api.get_subsidy_payment(UNKNOWN_PAYMENT_ID, ADMIN),
        E.ERR_PAYMENT_NOT_FOUND,
        404,
    )
    petition_error = validate_error(
        api.get_termination_petition(UNKNOWN_PETITION_ID, ADMIN),
        E.ERR_PETITION_NOT_FOUND,
        404,
    )
    renegotiation_error = validate_error(
        api.get_rate_renegotiation(UNKNOWN_RENEGOTIATION_ID, ADMIN),
        E.ERR_RENEGOTIATION_NOT_FOUND,
        404,
    )

    reported = [
        period_error["error_id"],
        payment_error["error_id"],
        petition_error["error_id"],
        renegotiation_error["error_id"],
    ]
    assert len(set(reported)) == 4, f"Not-found ids must be distinct: {reported}"


# ─── errors / wrong_state_writes_are_rejected_with_the_resource_specific_error_id

def test_soliciting_a_community_that_was_never_assessed_is_refused(api: ApiClient):
    """A REGISTERED community may not be solicited.

    "A solicitation may only be opened for a community whose `status` is `ELIGIBLE`, `SUBSIDIZED` or `HOLD_IN`; a `REGISTERED`, `INELIGIBLE` or `TERMINATED` community may not be solicited and the attempt is refused with `ERR_COMMUNITY_NOT_ELIGIBLE`."

    Design: Corner/errors/wrong_state_writes_are_rejected_with_the_resource_specific_error_id
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    community = validate_success(
        api.create_community(
            f.community_payload(
                code="GDV",
                name="Glendive",
                state_code="MT",
                driving_miles_to_nearest_hub=220.0,
                enplanements_prior_year=4000,
                min_required_weekly_round_trips=6,
                min_required_weekly_seats=180,
            ),
            ADMIN,
        ),
        201,
    )
    assert community["status"] == COMMUNITY_REGISTERED

    refused = api.create_solicitation(
        f.solicitation_payload(community["id"], closes_at="2026-09-20T00:00:00Z"), ADMIN
    )
    validate_error(refused, E.ERR_COMMUNITY_NOT_ELIGIBLE, 409)

    unchanged = validate_success(api.get_community(community["id"], ADMIN))
    assert unchanged["status"] == COMMUNITY_REGISTERED
    _, meta = validate_paginated(
        api.list_community_solicitations(community["id"], ADMIN)
    )
    assert meta["total_count"] == 0


def test_selection_order_on_an_open_solicitation_names_the_solicitation_error(api: ApiClient):
    """The order demands a CLOSED round even with a live candidate on the table.

    "Issuing the selection order is the `SelectionOfficer`'s exclusive act, takes an optional `order_note`, and is only admissible while the solicitation's `status` is `CLOSED`; from any other status the refusal is `ERR_SOLICITATION_NOT_CLOSED`."

    Design: Corner/errors/wrong_state_writes_are_rejected_with_the_resource_specific_error_id
    """
    reference = fx.make_reference_data(
        api, clock=DEFAULT_CLOCK, with_second_carrier=False
    )
    solicitation = fx.open_solicitation(api, reference.community_id)
    fx.submitted_proposal(
        api, solicitation["id"], reference.carrier_id, reference.aircraft_type_id
    )

    refused = api.create_selection_order(
        solicitation["id"],
        f.selection_order_payload(order_note="ordering before the window closes"),
        OFFICER,
    )
    validate_error(refused, E.ERR_SOLICITATION_NOT_CLOSED, 409)

    unchanged = validate_success(api.get_solicitation(solicitation["id"], ADMIN))
    assert unchanged["status"] == SOLICITATION_OPEN
    assert unchanged["selected_proposal_id"] is None
    _, meta = validate_paginated(
        api.list_service_agreements(ADMIN, {"community_id": reference.community_id})
    )
    assert meta["total_count"] == 0

def test_a_second_report_on_the_same_month_names_the_period_report_error(api: ApiClient):
    """Once a month is REPORTED it cannot be reported again.

    "A report is admissible only while the period's `status` is `OPEN` — otherwise `ERR_PERIOD_NOT_REPORTABLE` — and only while the parent agreement's `status` is `ACTIVE` or `HOLD_IN`, since a suspended or terminated agreement has no service to report; a report against any other agreement status is refused with `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Corner/errors/wrong_state_writes_are_rejected_with_the_resource_specific_error_id
    """
    award = _twelve_month_award(api)
    period = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08", **CLEAN_MONTH
    )
    assert period["status"] == PERIOD_REPORTED
    assert_ratio(period["period_completion_factor"], 1.0000, "period_completion_factor")

    refused = api.report_service_period(
        period["id"], f.report_payload(**CLEAN_MONTH), award.carrier_headers
    )
    validate_error(refused, E.ERR_PERIOD_NOT_REPORTABLE, 409)

    unchanged = validate_success(api.get_service_period(period["id"], ADMIN))
    assert unchanged["status"] == PERIOD_REPORTED
    assert unchanged["amendment_count"] == 0
    assert unchanged["completed_departures"] == 100
    assert unchanged["version"] == period["version"]


def test_amending_a_certified_month_names_the_period_amendment_error(api: ApiClient):
    """Certification closes the correction window on a month.

    "An amendment replaces all six reported figures at once and is admissible only while the period's `status` is `REPORTED`; against any other status the refusal is `ERR_PERIOD_NOT_AMENDABLE`."

    Design: Corner/errors/wrong_state_writes_are_rejected_with_the_resource_specific_error_id
    """
    award = _twelve_month_award(api)
    month = fx.certified_month(
        api, award.agreement_id, award.carrier_id, "2026-08", **CLEAN_MONTH
    )
    assert month["period"]["status"] == PERIOD_CERTIFIED
    assert month["period"]["amendment_count"] == 0
    assert_money(month["payment"]["net_payment_usd"], 100000.00, "net_payment_usd")

    before = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    refused = api.amend_service_period(
        month["period"]["id"],
        f.amend_payload(
            before["version"],
            scheduled_departures=100,
            completed_departures=98,
            cancelled_carrier_departures=2,
            cancelled_weather_departures=0,
            seats_offered=1862,
            passengers_enplaned=700,
        ),
        award.carrier_headers,
    )
    validate_error(refused, E.ERR_PERIOD_NOT_AMENDABLE, 409)

    unchanged = validate_success(api.get_service_period(month["period"]["id"], ADMIN))
    assert unchanged["status"] == PERIOD_CERTIFIED
    assert unchanged["amendment_count"] == 0
    assert unchanged["completed_departures"] == 100
    after = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert after["version"] == before["version"]
    assert after["cumulative_completed_departures"] == 100


# ─── errors / payment_and_renegotiation_actions_rejected_out_of_sequence ─

def test_payment_actions_are_refused_until_the_status_they_demand_is_reached(api: ApiClient):
    """Disbursement before approval is refused, and a second approval afterwards too.

    "A different `ProgramAdmin` **disburses** it, which moves it `APPROVED → DISBURSED`; a payment in any other status is refused with `ERR_PAYMENT_NOT_DISBURSABLE`, an acting user equal to `approved_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`, and a `net_payment_usd` greater than the agreement's `obligated_remaining_usd` is refused with `ERR_OBLIGATION_EXCEEDED`."

    Design: Corner/errors/payment_and_renegotiation_actions_rejected_out_of_sequence
    """
    award = _twelve_month_award(api)
    month = fx.certified_month(
        api, award.agreement_id, award.carrier_id, "2026-08", **CLEAN_MONTH
    )
    payment = month["payment"]
    assert payment["status"] == PAYMENT_COMPUTED
    assert payment["approved_by_user_id"] is None
    assert payment["disbursed_by_user_id"] is None

    too_early = api.payment_action(
        payment["id"], f.payment_action_payload(PAYMENT_DISBURSE), ADMIN_DISBURSER
    )
    validate_error(too_early, E.ERR_PAYMENT_NOT_DISBURSABLE, 409)
    still_computed = validate_success(api.get_subsidy_payment(payment["id"], ADMIN))
    assert still_computed["status"] == PAYMENT_COMPUTED
    assert still_computed["disbursed_by_user_id"] is None

    approved = validate_success(
        api.payment_action(
            payment["id"], f.payment_action_payload(PAYMENT_APPROVE), ADMIN_APPROVER
        )
    )
    assert approved["status"] == PAYMENT_APPROVED
    assert approved["approved_by_user_id"] == USER_ADMIN_APPROVER

    second_approval = api.payment_action(
        payment["id"], f.payment_action_payload(PAYMENT_APPROVE), ADMIN_SECOND
    )
    validate_error(second_approval, E.ERR_PAYMENT_NOT_APPROVABLE, 409)
    after = validate_success(api.get_subsidy_payment(payment["id"], ADMIN))
    assert after["status"] == PAYMENT_APPROVED
    assert after["approved_by_user_id"] == USER_ADMIN_APPROVER

    disbursed = validate_success(
        api.payment_action(
            payment["id"], f.payment_action_payload(PAYMENT_DISBURSE), ADMIN_DISBURSER
        )
    )
    assert disbursed["status"] == PAYMENT_DISBURSED
    paid_period = validate_success(
        api.get_service_period(month["period"]["id"], ADMIN)
    )
    assert paid_period["status"] == PERIOD_PAID
    ledger = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert_money(ledger["disbursed_to_date_usd"], 100000.00, "disbursed_to_date_usd")
    assert_money(ledger["obligated_remaining_usd"], 1100000.00, "obligated_remaining_usd")
    assert_obligation_identity(ledger)


def test_accepting_a_withdrawn_renegotiation_is_refused_and_the_rate_stands(api: ApiClient):
    """A withdrawn negotiation is terminal, so acceptance cannot revive it.

    "An action attempted from a status that does not admit it — countering something not `REQUESTED`, revising something not `COUNTERED`, or accepting, rejecting or withdrawing something that is neither `REQUESTED` nor `COUNTERED` — is refused with `ERR_RENEGOTIATION_NOT_ACTIONABLE`."

    Design: Corner/errors/payment_and_renegotiation_actions_rejected_out_of_sequence
    """
    award = _twelve_month_award(api)
    fx.set_clock(api, COOLING_OFF_BOUNDARY)
    renegotiation = fx.file_cost_renegotiation(api, award, 0.0400, 1240000.00)
    assert renegotiation["status"] == RENEG_REQUESTED
    assert renegotiation["revision_count"] == 0
    assert_money(renegotiation["justified_delta_usd"], 48000.00, "justified_delta_usd")
    assert_money(
        renegotiation["ceiling_annual_subsidy_usd"], 1248000.00, "ceiling_annual_subsidy_usd"
    )
    assert renegotiation["approved_annual_subsidy_usd"] is None

    withdrawn = validate_success(
        api.renegotiation_action(
            renegotiation["id"],
            f.renegotiation_action_payload(RENEG_WITHDRAW),
            award.carrier_headers,
        )
    )
    assert withdrawn["status"] == RENEG_WITHDRAWN

    refused = api.renegotiation_action(
        renegotiation["id"],
        f.renegotiation_action_payload(RENEG_ACCEPT),
        ADMIN_NEGOTIATOR,
    )
    validate_error(refused, E.ERR_RENEGOTIATION_NOT_ACTIONABLE, 409)

    unchanged = validate_success(api.get_rate_renegotiation(renegotiation["id"], ADMIN))
    assert unchanged["status"] == RENEG_WITHDRAWN
    assert unchanged["approved_annual_subsidy_usd"] is None
    assert unchanged["effective_at"] is None
    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert_money(agreement["annual_subsidy_usd"], 1200000.00, "annual_subsidy_usd")
    assert_money(agreement["total_committed_usd"], 1200000.00, "total_committed_usd")
    assert_obligation_identity(agreement)


# ─── errors / immediate_grant_cannot_strand_a_community_without_service ─

def test_immediate_grant_is_refused_when_it_would_strand_the_community(api: ApiClient):
    """The only carrier cannot be released outright on a service-quality petition.

    "It is admissible only when the petition's `reason_code` is `AIRPORT_CLOSURE` — there is nothing left to serve — or when the community holds another agreement whose `status` is `ACTIVE`, so service continues regardless. Otherwise the decision is refused with `ERR_HOLD_IN_REQUIRED`: the community may not be left with no air service."

    Design: Corner/errors/immediate_grant_cannot_strand_a_community_without_service
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK, with_second_carrier=False)
    petition = fx.petition_under_review(api, award.agreement)
    assert petition["status"] == PETITION_UNDER_REVIEW
    assert petition["reason_code"] == PETITION_REASON_SERVICE_QUALITY

    refused = api.petition_decision(
        petition["id"],
        f.petition_decision_payload(
            DECISION_GRANT_IMMEDIATE, decision_note="release the carrier outright"
        ),
        OFFICER,
    )
    validate_error(refused, E.ERR_HOLD_IN_REQUIRED, 409)

    unchanged_petition = validate_success(
        api.get_termination_petition(petition["id"], ADMIN)
    )
    assert unchanged_petition["status"] == PETITION_UNDER_REVIEW
    assert unchanged_petition["decided_by_user_id"] is None
    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert agreement["status"] == AGREEMENT_ACTIVE
    assert agreement["terminated_at"] is None
    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_SUBSIDIZED
    assert community["active_agreement_count"] == 1
    rows, _ = validate_paginated(
        api.list_community_solicitations(award.community_id, ADMIN)
    )
    assert [row["created_reason"] for row in rows] == [CREATED_REASON_INITIAL]


def test_the_same_petition_may_be_granted_with_a_hold_in(api: ApiClient):
    """Granting with hold-in keeps the carrier flying and opens the replacement round.

    "In the same request the community moves `SUBSIDIZED → HOLD_IN` with its `active_agreement_count` decreased by 1, and the program opens a replacement solicitation for that community with `created_reason` `REPLACEMENT`, `status` `OPEN`, `round_number` 1 and a `closes_at` 60 days after the current logical clock reading."

    Design: Corner/errors/immediate_grant_cannot_strand_a_community_without_service
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK, with_second_carrier=False)
    petition = fx.petition_under_review(api, award.agreement)

    granted = validate_success(
        api.petition_decision(
            petition["id"],
            f.petition_decision_payload(
                DECISION_GRANT_WITH_HOLD_IN, decision_note="continuity first"
            ),
            OFFICER,
        )
    )
    assert granted["status"] == PETITION_GRANTED_WITH_HOLD_IN
    assert granted["decision_note"] == "continuity first"

    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert agreement["status"] == AGREEMENT_HOLD_IN
    assert agreement["terminated_at"] is None
    community = validate_success(api.get_community(award.community_id, ADMIN))
    assert community["status"] == COMMUNITY_HOLD_IN
    assert community["active_agreement_count"] == 0

    rows, _ = validate_paginated(
        api.list_community_solicitations(award.community_id, ADMIN)
    )
    replacements = [
        row for row in rows if row["created_reason"] == CREATED_REASON_REPLACEMENT
    ]
    assert len(replacements) == 1
    replacement = replacements[0]
    assert replacement["status"] == SOLICITATION_OPEN
    assert replacement["round_number"] == 1
    assert_instant(replacement["closes_at"], "2026-09-30T00:00:00Z", "closes_at")


# ─── errors / certification_is_refused_once_the_obligation_is_exhausted ─

def test_the_thirteenth_month_cannot_be_certified_once_the_obligation_is_spent(api: ApiClient):
    """Twelve settled months exhaust a twelve-month commitment exactly.

    "Before the payment is created, the program checks that the monthly entitlement less the cancellation adjustment, rounded half-up to cents, is no greater than the agreement's `obligated_remaining_usd`; if it is greater, certification is refused with `ERR_OBLIGATION_EXCEEDED`."

    Design: Corner/errors/certification_is_refused_once_the_obligation_is_exhausted
    """
    award = _twelve_month_award(api)
    booked = award.agreement
    assert_money(booked["total_committed_usd"], 1200000.00, "total_committed_usd")
    assert_money(booked["obligated_remaining_usd"], 1200000.00, "obligated_remaining_usd")

    for index, month in enumerate(TERM_MONTHS_2026_08_TO_2027_07, start=1):
        settled = fx.settled_month(
            api, award.agreement_id, award.carrier_id, month, **CLEAN_MONTH
        )
        payment = settled["payment"]
        assert settled["period"]["status"] == PERIOD_PAID
        assert payment["status"] == PAYMENT_DISBURSED
        assert payment["credited_departures"] == 100
        assert_money(
            payment["monthly_entitlement_usd"], 100000.00, "monthly_entitlement_usd"
        )
        assert_money(payment["per_departure_rate_usd"], 1000.00, "per_departure_rate_usd")
        assert_money(
            payment["cancellation_adjustment_usd"], 0.00, "cancellation_adjustment_usd"
        )
        assert_ratio(payment["withholding_pct"], 0.0000, "withholding_pct")
        assert_money(payment["net_payment_usd"], 100000.00, "net_payment_usd")
        ledger = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
        assert_money(
            ledger["disbursed_to_date_usd"], 100000.00 * index, "disbursed_to_date_usd"
        )
        assert_money(
            ledger["obligated_remaining_usd"],
            1200000.00 - 100000.00 * index,
            "obligated_remaining_usd",
        )
        assert_obligation_identity(ledger)

    exhausted = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert_money(exhausted["total_committed_usd"], 1200000.00, "total_committed_usd")
    assert_money(exhausted["disbursed_to_date_usd"], 1200000.00, "disbursed_to_date_usd")
    assert_money(exhausted["obligated_remaining_usd"], 0.00, "obligated_remaining_usd")

    thirteenth = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2027-08", **CLEAN_MONTH
    )
    refused = api.certify_service_period(
        thirteenth["id"], f.certify_payload(), ADMIN
    )
    validate_error(refused, E.ERR_OBLIGATION_EXCEEDED, 422)

    still_reported = validate_success(api.get_service_period(thirteenth["id"], ADMIN))
    assert still_reported["status"] == PERIOD_REPORTED
    payments, payment_meta = validate_paginated(api.list_subsidy_payments(ADMIN))
    assert payment_meta["total_count"] == 12
    assert all(row["status"] == PAYMENT_DISBURSED for row in payments)
    after = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert_money(after["disbursed_to_date_usd"], 1200000.00, "disbursed_to_date_usd")
    assert_money(after["obligated_remaining_usd"], 0.00, "obligated_remaining_usd")
    assert_obligation_identity(after)
