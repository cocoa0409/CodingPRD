"""Requests blocked by state living on an entity the request body never names.

An election submission is gated on a sibling determination's status, and an
election approval is gated on the second, orthogonal status dimension of the
plan option.
"""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ANALYST_1,
    ANALYST_2,
    COMPLIANCE_1,
    COUNSELOR_1,
    COUNSELOR_2,
    make_compliance_officer_headers,
    make_eligibility_analyst_headers,
    make_enrollment_counselor_headers,
)


R2_WORKING_AGED = {
    "other_group_coverage_employer_size": 25,
    "active_employment_flag": True,
}


def _draft_determination_ready_to_elect(api):
    """Everything an ANNUAL_OPEN election needs except a certified determination.

    Returns {"plan_year_id", "pre65_core_id", "retiree_id", "determination"}. The
    determination sits in DRAFT with outcome already ELIGIBLE, so only its status
    stands in the way.
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    retiree = fx.make_retiree_r1(api)
    determination = fx.make_determination(
        api, retiree, plan_year_id, certify=False, creator_user_id=ANALYST_1
    )
    assert determination["status"] == "DRAFT"
    assert determination["outcome"] == "ELIGIBLE"
    assert determination["points"] == 75
    return {
        "plan_year_id": plan_year_id,
        "pre65_core_id": program["pre65_core"]["id"],
        "retiree_id": retiree["id"],
        "determination": determination,
    }


def _election_request(state):
    return f.election_event_payload(
        state["retiree_id"],
        state["plan_year_id"],
        state["pre65_core_id"],
        "ANNUAL_OPEN",
        "2026-10-20",
    )


def test_election_submission_is_blocked_while_the_determination_is_draft(api):
    """A DRAFT determination with an ELIGIBLE outcome still refuses the election.

    PRD 3.5: "The retiree must already hold a `CERTIFIED` determination for that
    plan year, otherwise `ERR_DETERMINATION_NOT_CERTIFIED`, and that
    determination's `outcome` must be `ELIGIBLE`, otherwise
    `ERR_NOT_ELIGIBLE_FOR_RETIREE_MEDICAL`." The outcome is already ELIGIBLE, and
    the status rung sits above the outcome rung in PRD 2.8, so the reported
    failure is the status one. Nothing is written, so the retiree still has no
    election event.

    Design: Difficulty/cross_entity_state_dependency/election_creation_blocked_by_uncertified_determination
    """
    state = _draft_determination_ready_to_elect(api)

    response = api.create_election_event(
        _election_request(state), make_enrollment_counselor_headers(COUNSELOR_1)
    )

    error = validate_error(
        response, ApiErrorId.ERR_DETERMINATION_NOT_CERTIFIED.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_NOT_ELIGIBLE_FOR_RETIREE_MEDICAL.value

    rows, _meta = validate_paginated(
        api.list_election_events(
            make_enrollment_counselor_headers(COUNSELOR_1),
            {"retiree_id": state["retiree_id"]},
        )
    )
    assert rows == []


def test_certifying_the_determination_admits_the_identical_election(api):
    """The same request succeeds once the sibling determination is CERTIFIED.

    PRD 3.4: "On success the determination records `certified_by_user_id` as the
    certifying user's `X-User-ID` and `certified_at` at the logical clock". Only
    that row changed between the two attempts, and PRD 3.5 fixes what the admitted
    election then records: "For an `ANNUAL_OPEN` election, `window_deadline` is the
    plan year's `open_enrollment_end`" and "Its `coverage_effective_date` is the
    plan year's `coverage_start`."

    Design: Difficulty/cross_entity_state_dependency/election_creation_blocked_by_uncertified_determination
    """
    state = _draft_determination_ready_to_elect(api)
    retiree_before = fx.reload_retiree(api, state["retiree_id"])
    option_before = fx.reload_plan_option(api, state["pre65_core_id"])

    validate_error(
        api.create_election_event(
            _election_request(state), make_enrollment_counselor_headers(COUNSELOR_1)
        ),
        ApiErrorId.ERR_DETERMINATION_NOT_CERTIFIED.value,
        expected_status=409,
    )

    certified = validate_success(
        api.certify_determination(
            state["determination"]["id"],
            make_eligibility_analyst_headers(ANALYST_2),
        )
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == ANALYST_2
    assert_instant_equals(
        certified["certified_at"], "2026-10-20T00:00:00.000Z", "certified_at"
    )

    election = validate_success(
        api.create_election_event(
            _election_request(state), make_enrollment_counselor_headers(COUNSELOR_1)
        ),
        expected_status=201,
    )

    assert election["status"] == "SUBMITTED"
    assert_instant_equals(
        election["coverage_effective_date"],
        "2027-01-01T00:00:00.000Z",
        "coverage_effective_date",
    )
    assert election["resulting_enrollment_id"] is None

    option_after = fx.reload_plan_option(api, state["pre65_core_id"])
    assert option_after["version"] == option_before["version"]
    assert option_after["enrolled_count"] == 0
    assert fx.reload_retiree(api, state["retiree_id"])["hire_date"] == (
        retiree_before["hire_date"]
    )


def _attested_but_uncertified_med_wrap_election(api):
    """An UNDER_REVIEW election onto an ACTIVE MED-WRAP whose subsidy dimension
    stopped at ATTESTED.

    Returns {"plan_option_id", "election_id", "retiree_id"}.
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    option = fx.make_med_wrap(api, plan_year["id"], certify=False)
    assert option["status"] == "ACTIVE"
    assert option["subsidy_certification_status"] == "ATTESTED"

    certified = fx.make_certified_retiree(
        api, plan_year["id"], f.retiree_r2_payload(R2_WORKING_AGED)
    )
    election = fx.make_election_event(
        api,
        certified["retiree"]["id"],
        plan_year["id"],
        option["id"],
        review=True,
    )
    assert election["status"] == "UNDER_REVIEW"
    return {
        "plan_option_id": option["id"],
        "election_id": election["id"],
        "retiree_id": certified["retiree"]["id"],
    }


def test_election_approval_is_blocked_while_the_subsidy_is_only_attested(api):
    """An ACTIVE option is not enough: the subsidy dimension must be CERTIFIED.

    PRD 3.5: "When the requested option's `subsidy_vehicle` is `RDS` or `EGWP`,
    its `subsidy_certification_status` must be `CERTIFIED`, otherwise
    `ERR_SUBSIDY_NOT_CERTIFIED`." The availability dimension was ACTIVE
    throughout, which is what makes the block cross-dimensional; PRD 2.11 insists
    the two are separable: "A `PlanOption` carries `status` alongside
    `subsidy_certification_status`: activating an option or closing it to new
    entrants leaves the certification dimension untouched". Nothing materialises,
    so the election stays UNDER_REVIEW with no enrollment.

    Design: Difficulty/cross_entity_state_dependency/election_approval_blocked_by_uncertified_egwp_subsidy
    """
    state = _attested_but_uncertified_med_wrap_election(api)

    response = api.decide_election_event(
        state["election_id"],
        f.election_decision_payload("APPROVE"),
        make_enrollment_counselor_headers(COUNSELOR_2),
    )

    validate_error(
        response, ApiErrorId.ERR_SUBSIDY_NOT_CERTIFIED.value, expected_status=409
    )

    election = fx.reload_election_event(api, state["election_id"])
    assert election["status"] == "UNDER_REVIEW"
    assert election["resulting_enrollment_id"] is None

    option = fx.reload_plan_option(api, state["plan_option_id"])
    assert option["status"] == "ACTIVE"
    assert option["subsidy_certification_status"] == "ATTESTED"
    assert option["enrolled_count"] == 0


def test_compliance_certification_unblocks_the_identical_approval(api):
    """Certifying the subsidy lets the same approval through and derive the MSP.

    PRD 3.2: "`CERTIFY` moves `subsidy_certification_status` from `ATTESTED` to
    `CERTIFIED`" while "Neither branch touches the option's availability
    `status`, its premium, or its attested values." The surviving approval then
    derives the enrollment, and PRD 3.6 pins the branch this retiree lands on:
    "Otherwise, if `active_employment_flag` is true and
    `other_group_coverage_employer_size` is at least 20, then `payer_order` is
    `GROUP_PRIMARY_WORKING_AGED` with `msp_basis_code`
    `WORKING_AGED_LARGE_EMPLOYER`." Coverage opens PENDING because PRD 3.5 says
    "Its `coverage_status` is `ACTIVE` when the logical clock has already reached
    that `coverage_effective_date` and `PENDING` when it has not".

    Design: Difficulty/cross_entity_state_dependency/election_approval_blocked_by_uncertified_egwp_subsidy
    """
    state = _attested_but_uncertified_med_wrap_election(api)

    validate_error(
        api.decide_election_event(
            state["election_id"],
            f.election_decision_payload("APPROVE"),
            make_enrollment_counselor_headers(COUNSELOR_2),
        ),
        ApiErrorId.ERR_SUBSIDY_NOT_CERTIFIED.value,
        expected_status=409,
    )

    certified_option = validate_success(
        api.certify_subsidy(
            state["plan_option_id"],
            f.subsidy_certification_payload("CERTIFY"),
            make_compliance_officer_headers(COMPLIANCE_1),
        )
    )
    assert certified_option["subsidy_certification_status"] == "CERTIFIED"
    assert certified_option["certified_by_user_id"] == COMPLIANCE_1
    assert certified_option["status"] == "ACTIVE"

    approved = validate_success(
        api.decide_election_event(
            state["election_id"],
            f.election_decision_payload("APPROVE"),
            make_enrollment_counselor_headers(COUNSELOR_2),
        )
    )
    assert approved["status"] == "APPROVED"

    enrollment = fx.reload_enrollment(api, approved["resulting_enrollment_id"])
    assert enrollment["coverage_status"] == "PENDING"
    assert enrollment["billing_status"] == "CURRENT"
    assert enrollment["payer_order"] == "GROUP_PRIMARY_WORKING_AGED"
    assert enrollment["msp_basis_code"] == "WORKING_AGED_LARGE_EMPLOYER"
    assert enrollment["monthly_retiree_premium_cents"] == 3406

    assert fx.reload_plan_option(api, state["plan_option_id"])["enrolled_count"] == 1
