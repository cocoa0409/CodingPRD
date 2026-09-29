"""
Two operations whose answer is decided by a neighbouring record's state: intake
reads the contractor's standing with the trust funds, and referral issuance
reads the member's standing with the local.
"""

from test_helpers import (
    DELINQUENT_TRUST_FUNDS,
    DISPATCHER,
    ERR_CONTRACTOR_NOT_SIGNATORY,
    ERR_MEMBER_NOT_IN_GOOD_STANDING,
    JOB_REQUEST_OPEN,
    JOB_REQUEST_SUSPENDED,
    REFERRAL_ISSUED,
    REFERRAL_KIND_NAMED_CALL,
    REGISTRATION_REGISTERED,
    SIGNATORY,
    SLOT_JOURNEYWORKER,
    STANDING_DELINQUENT,
    STANDING_GOOD,
    TERMINATED,
    VARIANT_NOT_APPLICABLE,
    expect_created,
    expect_error,
    factories as f,
    fixtures as fx,
    make_contractor_rep_headers,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── Intake against a contractor's signatory state ────────────────────────────

INTAKE_JOB_SITE = "Mill Street Riser"
INTAKE_REPORT_AT = "2026-09-28T07:00:00.000Z"
INTAKE_RATE_CENTS = 5100
INTAKE_DURATION_DAYS = 30
INTAKE_JOURNEYWORKERS = 2

# ─── Issuance against a member's standing ─────────────────────────────────────

ISSUANCE_JOB_SITE = "Depot Retrofit"
ISSUANCE_REPORT_AT = "2026-09-28T07:00:00.000Z"
ISSUANCE_RATE_CENTS = 5250
ISSUANCE_DURATION_DAYS = 30


def _delinquent_contractor(api):
    """A contractor entered straight into arrears, with no work of its own yet."""
    fx.set_clock(api, CLOCK)
    home = fx.add_home_local(api)
    contractor = fx.add_contractor(
        api, name="Midvale Piping", signatory_status=DELINQUENT_TRUST_FUNDS
    )
    return {"home": home, "contractor": contractor}


def _attempt_intake(api, contractor_id):
    """The one intake payload every leg of the scenario repeats unchanged."""
    return api.create_job_request(
        f.job_request_payload(
            contractor_id,
            job_site=INTAKE_JOB_SITE,
            journeyworkers_requested=INTAKE_JOURNEYWORKERS,
            apprentices_requested=0,
            expected_duration_days=INTAKE_DURATION_DAYS,
            report_at=INTAKE_REPORT_AT,
            hourly_rate_cents=INTAKE_RATE_CENTS,
        ),
        make_contractor_rep_headers(contractor_id),
    )


def _named_member_on_an_open_call(api):
    """One registrant, and a call that names that registrant by right."""
    hall = fx.standard_hall(api, clock=CLOCK)
    elle = fx.add_journeyworker(api, hall["home_local_id"], "Elle Fry", 9000)
    registration = fx.sign_book(api, elle["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name="Northline Systems")
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=ISSUANCE_JOB_SITE,
        journeyworkers_requested=1,
        apprentices_requested=0,
        expected_duration_days=ISSUANCE_DURATION_DAYS,
        report_at=ISSUANCE_REPORT_AT,
        hourly_rate_cents=ISSUANCE_RATE_CENTS,
        named_call_member_ids=[elle["id"]],
    )
    return {
        "hall": hall,
        "elle": elle,
        "registration": registration,
        "contractor": contractor,
        "job_request": job_request,
    }


def _attempt_named_call(api, job_request_id, member_id):
    """The one issuance payload every leg of the scenario repeats unchanged."""
    version = fx.job_request_version(api, job_request_id)
    return api.create_referral(
        job_request_id,
        f.named_call_referral_payload(version, member_id, slot_kind=SLOT_JOURNEYWORKER),
        DISPATCHER,
    )


class TestIntakeDependsOnContractorSignatoryState:
    """The identical payload is refused, accepted and refused again."""

    def test_a_contractor_in_arrears_cannot_open_work_at_all(self, api):
        """
        PRD §3.5: "A contractor whose `signatory_status` is not `SIGNATORY` at the
        moment of intake cannot open work at all: intake is refused with
        `ERR_CONTRACTOR_NOT_SIGNATORY`."

        Design: Difficulty/cross_entity_state_dependency/job_request_intake_depends_on_contractor_signatory_state
        """
        scene = _delinquent_contractor(api)
        assert scene["contractor"]["signatory_status"] == DELINQUENT_TRUST_FUNDS

        response = _attempt_intake(api, scene["contractor"]["id"])

        expect_error(response, ERR_CONTRACTOR_NOT_SIGNATORY)

    def test_the_same_payload_is_accepted_once_the_contractor_signs(self, api):
        """
        PRD §3.5: "On successful intake the request's `open_journeyworker_slots` and
        `open_apprentice_slots` are initialized to the two requested counts, its
        `accepted_journeyworker_count` and `accepted_apprentice_count` begin at 0,
        and its `max_apprentices_allowed` is initialized from the ratio computation
        of §3.6 — which yields 0 until a journeyworker referral has actually been
        accepted."

        Design: Difficulty/cross_entity_state_dependency/job_request_intake_depends_on_contractor_signatory_state
        """
        scene = _delinquent_contractor(api)
        expect_error(
            _attempt_intake(api, scene["contractor"]["id"]),
            ERR_CONTRACTOR_NOT_SIGNATORY,
        )

        fx.set_signatory_status(api, scene["contractor"]["id"], SIGNATORY)
        created = expect_created(_attempt_intake(api, scene["contractor"]["id"]))

        assert created["status"] == JOB_REQUEST_OPEN
        assert created["open_journeyworker_slots"] == INTAKE_JOURNEYWORKERS
        assert created["accepted_journeyworker_count"] == 0
        assert created["max_apprentices_allowed"] == 0

    def test_termination_closes_intake_again(self, api):
        """
        PRD §2.7: "The contractor behind a new job request has `signatory_status` of
        `SIGNATORY`, failing with `ERR_CONTRACTOR_NOT_SIGNATORY`."

        Design: Difficulty/cross_entity_state_dependency/job_request_intake_depends_on_contractor_signatory_state
        """
        scene = _delinquent_contractor(api)
        fx.set_signatory_status(api, scene["contractor"]["id"], SIGNATORY)
        expect_created(_attempt_intake(api, scene["contractor"]["id"]))

        fx.set_signatory_status(api, scene["contractor"]["id"], TERMINATED)
        response = _attempt_intake(api, scene["contractor"]["id"])

        expect_error(response, ERR_CONTRACTOR_NOT_SIGNATORY)

    def test_termination_also_suspends_the_request_already_opened(self, api):
        """
        PRD §3.5: "the first hop moves every `OPEN` or `PARTIALLY_FILLED` job
        request of that contractor to `SUSPENDED`, recording the status it held in
        `suspended_from_status`"

        Design: Difficulty/cross_entity_state_dependency/job_request_intake_depends_on_contractor_signatory_state
        """
        scene = _delinquent_contractor(api)
        fx.set_signatory_status(api, scene["contractor"]["id"], SIGNATORY)
        opened = expect_created(_attempt_intake(api, scene["contractor"]["id"]))

        fx.set_signatory_status(api, scene["contractor"]["id"], TERMINATED)

        suspended = fx.read_job_request(api, opened["id"])
        assert suspended["status"] == JOB_REQUEST_SUSPENDED
        assert suspended["suspended_from_status"] == JOB_REQUEST_OPEN


class TestIssuanceDependsOnMemberStandingState:
    """The identical named call is refused while the member is in arrears."""

    def test_delinquency_alone_makes_the_member_undispatchable(self, api):
        """
        PRD §3.1: "Finally, `dispatch_eligible` is true when the member's `standing`
        is `GOOD_STANDING` and either `re_registration_eligible_at` is null or the
        current instant has reached or passed it; it is false otherwise, and a member
        who is not `dispatch_eligible` is invisible to every ranked candidate set the
        hall computes."

        Design: Difficulty/cross_entity_state_dependency/referral_issue_depends_on_member_standing_state
        """
        scene = _named_member_on_an_open_call(api)
        assert scene["elle"]["standing"] == STANDING_GOOD
        assert scene["elle"]["dispatch_eligible"] is True
        assert scene["registration"]["position_number"] == 1

        delinquent = fx.set_standing(api, scene["elle"]["id"], STANDING_DELINQUENT)

        assert delinquent["standing"] == STANDING_DELINQUENT
        assert delinquent["dispatch_eligible"] is False
        # No registration of this member was removed, so no cooling-off horizon
        # explains the change.
        assert delinquent["re_registration_eligible_at"] is None

    def test_a_named_call_on_a_delinquent_member_is_refused(self, api):
        """
        PRD §3.6: "The member must be `dispatch_eligible` — in `GOOD_STANDING` and
        past any cooling-off period — failing with
        `ERR_MEMBER_NOT_IN_GOOD_STANDING`."

        Design: Difficulty/cross_entity_state_dependency/referral_issue_depends_on_member_standing_state
        """
        scene = _named_member_on_an_open_call(api)
        fx.set_standing(api, scene["elle"]["id"], STANDING_DELINQUENT)

        response = _attempt_named_call(
            api, scene["job_request"]["id"], scene["elle"]["id"]
        )

        expect_error(response, ERR_MEMBER_NOT_IN_GOOD_STANDING)

    def test_the_refused_issuance_leaves_both_neighbours_untouched(self, api):
        """
        PRD §3.1: "First, `dispatch_eligible` is recomputed, which silently removes
        a newly delinquent member from every candidate pool."

        Design: Difficulty/cross_entity_state_dependency/referral_issue_depends_on_member_standing_state
        """
        scene = _named_member_on_an_open_call(api)
        fx.set_standing(api, scene["elle"]["id"], STANDING_DELINQUENT)
        expect_error(
            _attempt_named_call(api, scene["job_request"]["id"], scene["elle"]["id"]),
            ERR_MEMBER_NOT_IN_GOOD_STANDING,
        )

        registration = fx.read_registration(api, scene["registration"]["id"])
        job_request = fx.read_job_request(api, scene["job_request"]["id"])
        assert registration["status"] == REGISTRATION_REGISTERED
        assert registration["position_number"] == 1
        assert job_request["status"] == JOB_REQUEST_OPEN
        assert job_request["open_journeyworker_slots"] == 1

    def test_restoring_good_standing_lets_the_identical_call_through(self, api):
        """
        PRD §3.6: "A `NAMED_CALL` referral bypasses the ranking entirely and goes to
        the member the contractor named — which must be a member appearing in the
        request's `named_call_member_ids`, or the issuance is refused with
        `ERR_NAMED_CALL_NOT_DECLARED` — and records `variant_applied` as
        `NOT_APPLICABLE` with a null `list_position_at_issue`."

        Design: Difficulty/cross_entity_state_dependency/referral_issue_depends_on_member_standing_state
        """
        scene = _named_member_on_an_open_call(api)
        assert scene["job_request"]["named_call_allowance"] == 1
        fx.set_standing(api, scene["elle"]["id"], STANDING_DELINQUENT)
        expect_error(
            _attempt_named_call(api, scene["job_request"]["id"], scene["elle"]["id"]),
            ERR_MEMBER_NOT_IN_GOOD_STANDING,
        )

        fx.set_standing(api, scene["elle"]["id"], STANDING_GOOD)
        issued = expect_created(
            _attempt_named_call(api, scene["job_request"]["id"], scene["elle"]["id"])
        )

        assert issued["status"] == REFERRAL_ISSUED
        assert issued["registration_id"] == scene["registration"]["id"]
        assert issued["referral_kind"] == REFERRAL_KIND_NAMED_CALL
        assert issued["variant_applied"] == VARIANT_NOT_APPLICABLE
        assert issued["list_position_at_issue"] is None
