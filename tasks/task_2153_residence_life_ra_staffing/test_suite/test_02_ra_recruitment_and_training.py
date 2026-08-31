"""Recruiting the RA corps, and the two lifecycle dimensions an RA carries."""
from test_helpers import (
    ApiErrorId,
    assert_ra,
    assert_timestamp_equals,
    create_ra,
    read_application,
    read_ra,
    setup_application_at_revision_cap,
    setup_hall_with_floor,
    validate_error,
    validate_success,
)


class TestParallelLifecycleDimensions:
    def test_suspending_an_ra_leaves_the_certification_dimension_untouched(
        self, api, director_headers
    ):
        """PRD §2.10: "An action on one dimension never writes the other: suspending
        an RA leaves their certification exactly as it was, and letting a
        certification lapse leaves their employment exactly as it was."
        PRD §3.3: "Suspension takes an `ACTIVE` RA to `SUSPENDED` and reinstatement
        brings them back; neither writes the certification dimension."

        Design: Difficulty/non_linear_state_machine/ra_employment_and_certification_are_independent_parallel_dimensions
        """
        base = setup_hall_with_floor()
        staff = create_ra(floor_id=base["floor"]["id"])
        ra_id = staff["ra"]["id"]
        assert staff["ra"]["employment_status"] == "ACTIVE"
        assert staff["ra"]["certification_status"] == "CERTIFIED"

        suspended = validate_success(
            api.ra_employment(
                ra_id, {"action": "SUSPEND", "reason": "policy review"}, director_headers
            )
        )

        assert_ra(suspended)
        assert suspended["employment_status"] == "SUSPENDED"
        assert suspended["certification_status"] == "CERTIFIED", (
            "SUSPEND must not write the training dimension"
        )
        assert suspended["training_credits_earned"] == 12

    def test_lapse_and_reinstate_each_leave_the_other_dimension_untouched(
        self, api, director_headers
    ):
        """PRD §2.10: "It is entirely legitimate for an RA to be `ACTIVE` while
        `UNCERTIFIED`, or `CERTIFIED` while `SUSPENDED`."
        PRD §3.3: "Letting a certification lapse moves `CERTIFIED → LAPSED`; it
        explicitly does **not** disturb shifts the RA already holds, and only new
        assignments and swap approvals are then refused with `ERR_RA_NOT_CERTIFIED`."

        Design: Difficulty/non_linear_state_machine/ra_employment_and_certification_are_independent_parallel_dimensions
        """
        base = setup_hall_with_floor()
        staff = create_ra(floor_id=base["floor"]["id"])
        ra_id = staff["ra"]["id"]
        certified_at = staff["ra"]["certified_at"]

        validate_success(
            api.ra_employment(
                ra_id, {"action": "SUSPEND", "reason": "policy review"}, director_headers
            )
        )
        lapsed = validate_success(
            api.ra_certification(ra_id, {"action": "LAPSE"}, director_headers)
        )
        assert lapsed["certification_status"] == "LAPSED"
        assert lapsed["employment_status"] == "SUSPENDED", (
            "LAPSE must not write the employment dimension"
        )

        reinstated = validate_success(
            api.ra_employment(ra_id, {"action": "REINSTATE"}, director_headers)
        )
        assert reinstated["employment_status"] == "ACTIVE"
        assert reinstated["certification_status"] == "LAPSED", (
            "REINSTATE must leave the training dimension where LAPSE left it"
        )
        assert reinstated["training_credits_earned"] == 12
        assert reinstated["certified_at"] == certified_at, (
            "certified_at is stamped by CERTIFY alone"
        )


class TestApplicationRevisionCycle:
    def test_third_revision_request_is_refused_at_the_two_round_cap(
        self, api, director_headers
    ):
        """PRD §3.2: "`REQUEST_REVISION` sends the application back to
        `REVISION_REQUESTED`, increments `revision_count` by one and stores the
        supplied `revision_notes`; it is permitted only while `revision_count` is
        strictly below the two-round revision cap, and a third attempt is refused with
        `ERR_REVISION_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/ra_application_revision_cycle_capped_at_two_rounds
        """
        base = setup_application_at_revision_cap()
        application = base["application"]
        assert application["revision_count"] == 2

        response = api.decide_application(
            application["id"],
            {"decision": "REQUEST_REVISION", "revision_notes": "third pass"},
            director_headers,
        )

        validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, 409)
        assert read_application(application["id"])["revision_count"] == 2

    def test_capped_application_stays_under_review_with_its_last_review_intact(
        self, api, director_headers
    ):
        """PRD §3.2: "An application in `REVISION_REQUESTED` returns to `SUBMITTED`
        when its applicant submits again, closing the cycle `UNDER_REVIEW →
        REVISION_REQUESTED → SUBMITTED → UNDER_REVIEW`; the second submit re-stamps
        `submitted_at`."
        PRD §3.2: "A director then opens review by recording an `interview_score` — a
        number from 0 to 100 carried to one decimal place — which takes the application
        `SUBMITTED → UNDER_REVIEW` and stamps `reviewed_by_user_id` with the reviewing
        director's identifier."

        Design: Difficulty/non_linear_state_machine/ra_application_revision_cycle_capped_at_two_rounds
        """
        base = setup_application_at_revision_cap()
        application = base["application"]

        refused = api.decide_application(
            application["id"],
            {"decision": "REQUEST_REVISION", "revision_notes": "third pass"},
            director_headers,
        )
        validate_error(refused, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, 409)

        after = read_application(application["id"])
        assert after["status"] == "UNDER_REVIEW", (
            f"the refused decision must leave the row UNDER_REVIEW, got {after['status']}"
        )
        assert after["interview_score"] == 80
        assert after["revision_notes"] == "still thin on conflict handling", (
            "the refused decision must not overwrite the stored revision notes"
        )


class TestCertificationGates:
    def test_eleven_training_credits_is_refused_as_insufficient(self, api, director_headers):
        """PRD §3.3: "The RA must have accumulated at least twelve training credits;
        the comparison is inclusive, so exactly twelve certifies, and anything below
        draws `ERR_TRAINING_CREDITS_INSUFFICIENT`."
        PRD §3.3: "Because the three mandatory modules together carry only eleven
        credits, every certification requires at least one elective on top of them."

        Design: Difficulty/boundary_precision_check/certification_credit_threshold_eleven_fails_twelve_passes
        """
        base = setup_hall_with_floor()
        staff = create_ra(
            floor_id=base["floor"]["id"],
            modules=["CRISIS", "TITLE_IX", "FIRE_SAFETY"],
            certify=False,
        )
        ra_id = staff["ra"]["id"]
        assert staff["ra"]["training_credits_earned"] == 11

        response = api.ra_certification(ra_id, {"action": "CERTIFY"}, director_headers)

        validate_error(response, ApiErrorId.ERR_TRAINING_CREDITS_INSUFFICIENT.value, 409)
        refused = read_ra(ra_id)
        assert refused["training_credits_earned"] == 11
        assert refused["certification_status"] == "IN_TRAINING"
        assert refused["employment_status"] == "ACTIVE"

    def test_exactly_twelve_credits_certifies_and_stamps_certified_at(
        self, api, director_headers
    ):
        """PRD §3.3: "The RA must have accumulated at least twelve training credits;
        the comparison is inclusive, so exactly twelve certifies, and anything below
        draws `ERR_TRAINING_CREDITS_INSUFFICIENT`."
        PRD §3.3: "Certifying an RA takes `certification_status` from `IN_TRAINING` to
        `CERTIFIED` and stamps `certified_at` with the logical clock."
        PRD §2.5: "Before any operator sets it, that clock reads exactly
        `2026-08-01T00:00:00Z`, which is also the term start instant used by the
        backward-looking duty-load figure."

        Design: Difficulty/boundary_precision_check/certification_credit_threshold_eleven_fails_twelve_passes
        """
        base = setup_hall_with_floor()
        staff = create_ra(
            floor_id=base["floor"]["id"],
            modules=["CRISIS", "TITLE_IX", "FIRE_SAFETY"],
            certify=False,
        )
        ra_id = staff["ra"]["id"]

        topped_up = validate_success(
            api.log_training_module(ra_id, {"module_code": "DIVERSITY"}, director_headers)
        )
        assert topped_up["training_credits_earned"] == 12, (
            "DIVERSITY carries one credit on top of the eleven mandatory ones"
        )

        certified = validate_success(
            api.ra_certification(ra_id, {"action": "CERTIFY"}, director_headers)
        )
        assert certified["certification_status"] == "CERTIFIED"
        assert_timestamp_equals(
            certified["certified_at"], "2026-08-01T00:00:00Z", "certified_at"
        )
        assert certified["employment_status"] == "ACTIVE"


def test_certifying_an_uncertified_ra_is_refused_as_a_state_breach(api, director_headers):
    """PRD §3.3: "Certifying an RA takes `certification_status` from `IN_TRAINING` to
    `CERTIFIED` and stamps `certified_at` with the logical clock."
    PRD §3.3: "the module is only loggable while the RA is `IN_TRAINING`; logging
    against any other certification state is `ERR_RA_STATE_INVALID`."
    PRD §2.7: "The target resource must be in a state from which the requested
    transition is declared, otherwise the state code for that resource type (HTTP 409)."

    Design: Corner/state_machines/certify_an_uncertified_ra_returns_ra_state_invalid
    """
    setup_hall_with_floor()
    staff = create_ra(activate=False, start_training=False, interview_score=84)
    ra_id = staff["ra"]["id"]
    assert staff["ra"]["certification_status"] == "UNCERTIFIED"

    response = api.ra_certification(ra_id, {"action": "CERTIFY"}, director_headers)

    validate_error(response, ApiErrorId.ERR_RA_STATE_INVALID.value, 409)
    refused = read_ra(ra_id)
    assert refused["certification_status"] == "UNCERTIFIED"
    assert refused["employment_status"] == "PROVISIONAL"
    assert refused["certified_at"] is None
    application = read_application(staff["application"]["id"])
    assert application["status"] == "ACCEPTED"
    assert application["created_ra_id"] == ra_id


def test_logging_the_same_training_module_twice_is_refused(api, director_headers):
    """PRD §3.3: "Because a module already present in `completed_module_codes` would
    double-count its credits, logging a repeat is refused with
    `ERR_MODULE_ALREADY_COMPLETED`."
    PRD §3.3: "the catalogue is fixed at five credits for `CRISIS`, four for
    `TITLE_IX`, two for `FIRE_SAFETY`, three for `MEDIATION`, one for `DIVERSITY` and
    two for `PROGRAMMING`."

    Design: Corner/validations/logging_the_same_training_module_twice_returns_module_already_completed
    """
    staff = create_ra(activate=False, modules=["CRISIS"], certify=False)
    ra_id = staff["ra"]["id"]

    response = api.log_training_module(ra_id, {"module_code": "CRISIS"}, director_headers)

    validate_error(response, ApiErrorId.ERR_MODULE_ALREADY_COMPLETED.value, 409)
    refused = read_ra(ra_id)
    assert refused["training_credits_earned"] == 5, (
        "the repeat must not double-count the module's credits"
    )
    assert refused["completed_module_codes"] == ["CRISIS"]
    assert refused["certification_status"] == "IN_TRAINING"


def test_certifying_without_a_mandatory_module_reports_the_module_gap(api, director_headers):
    """PRD §3.3: "The RA must also have completed all three mandatory modules —
    `CRISIS`, `TITLE_IX` and `FIRE_SAFETY` — and a missing one draws
    `ERR_MANDATORY_MODULE_MISSING`."
    PRD §3.3: "The credit check is evaluated before the mandatory-module check, so an
    RA short on both reports the insufficient-credit code."

    Design: Corner/validations/certify_with_enough_credits_but_a_missing_mandatory_module_is_rejected
    """
    staff = create_ra(
        activate=False,
        modules=["CRISIS", "TITLE_IX", "MEDIATION", "DIVERSITY", "PROGRAMMING"],
        certify=False,
    )
    ra_id = staff["ra"]["id"]
    assert staff["ra"]["training_credits_earned"] == 15, (
        "the credit gate must already be satisfied so the module gate is the one under test"
    )

    response = api.ra_certification(ra_id, {"action": "CERTIFY"}, director_headers)

    validate_error(response, ApiErrorId.ERR_MANDATORY_MODULE_MISSING.value, 409)
    refused = read_ra(ra_id)
    assert refused["training_credits_earned"] == 15
    assert refused["certification_status"] == "IN_TRAINING"
    assert refused["certified_at"] is None
