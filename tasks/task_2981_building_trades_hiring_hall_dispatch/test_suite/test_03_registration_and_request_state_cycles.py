"""
Two lifecycles that leave a state and come back to it: a registration that is
referred, turned down and restored to the book, and a job request that is
suspended by a delinquent contractor and reinstated to the status it left.
"""

from test_helpers import (
    DELINQUENT_TRUST_FUNDS,
    DISPATCHER,
    ERR_JOB_REQUEST_SUSPENDED,
    JOB_REQUEST_OPEN,
    JOB_REQUEST_PARTIALLY_FILLED,
    JOB_REQUEST_SUSPENDED,
    REFERRAL_ISSUED,
    REFERRAL_REFUSED,
    REGISTRATION_REFERRED,
    REGISTRATION_REGISTERED,
    SIGNATORY,
    SLOT_JOURNEYWORKER,
    VARIANT_STRICT_GROUP_ORDER,
    expect_created,
    expect_error,
    factories as f,
    fixtures as fx,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── The refusal cycle ────────────────────────────────────────────────────────

REFUSAL_JOB_SITE = "Northgate Plant"
REFUSAL_REPORT_AT = "2026-09-25T14:00:00.000Z"
REFUSAL_RATE_CENTS = 5000
REFUSAL_DURATION_DAYS = 20

# ─── The suspend and resume cycle ─────────────────────────────────────────────

SUSPEND_JOB_SITE = "Pier 9 Erection"
SUSPEND_REPORT_AT = "2026-09-25T07:00:00.000Z"
SUSPEND_RATE_CENTS = 5400
SUSPEND_DURATION_DAYS = 40


def _two_registrant_call(api, contractor_name, job_site, days, report_at, rate_cents,
                         first_name, second_name):
    """
    A rank-one group holding two journeyworkers in seniority order, plus one
    signatory contractor's two-journeyworker long call.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    first = fx.add_journeyworker(api, hall["home_local_id"], first_name, 9000)
    second = fx.add_journeyworker(api, hall["home_local_id"], second_name, 8000)
    first_registration = fx.sign_book(api, first["id"], hall["group_1_id"])
    second_registration = fx.sign_book(api, second["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api, name=contractor_name)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=job_site,
        journeyworkers_requested=2,
        apprentices_requested=0,
        expected_duration_days=days,
        report_at=report_at,
        hourly_rate_cents=rate_cents,
    )
    return {
        "hall": hall,
        "first": first,
        "second": second,
        "first_registration": first_registration,
        "second_registration": second_registration,
        "contractor": contractor,
        "job_request": job_request,
    }


def _refusal_scene(api):
    return _two_registrant_call(
        api,
        "Acme Mechanical",
        REFUSAL_JOB_SITE,
        REFUSAL_DURATION_DAYS,
        REFUSAL_REPORT_AT,
        REFUSAL_RATE_CENTS,
        "Pat Nolan",
        "Quinn Vale",
    )


def _suspension_scene(api):
    return _two_registrant_call(
        api,
        "Bridgeport Steel",
        SUSPEND_JOB_SITE,
        SUSPEND_DURATION_DAYS,
        SUSPEND_REPORT_AT,
        SUSPEND_RATE_CENTS,
        "Rae Ellis",
        "Sam Iyer",
    )


def _issue_journeyworker_referral(api, job_request_id):
    return fx.issue_referral(api, job_request_id, slot_kind=SLOT_JOURNEYWORKER)


class TestRegistrationRefusalCycle:
    """REGISTERED to REFERRED and back to REGISTERED, one ordinal lower."""

    def test_issuance_takes_the_rank_one_registration_off_the_numbered_book(self, api):
        """
        PRD §3.6: "On the list side, the selected registration moves from
        `REGISTERED` to `REFERRED`, its own `position_number` becomes null, and
        every remaining `REGISTERED` registration on the same list is renumbered
        from 1 through the group's `registered_count` under the strict-group-order
        intra-list key; the group's `registered_count` is decremented by 1."

        Design: Difficulty/non_linear_state_machine/registration_refusal_cycle_returns_to_registered
        """
        scene = _refusal_scene(api)
        assert scene["first_registration"]["position_number"] == 1
        assert scene["second_registration"]["position_number"] == 2

        referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])

        assert referral["status"] == REFERRAL_ISSUED
        assert referral["registration_id"] == scene["first_registration"]["id"]
        assert referral["member_id"] == scene["first"]["id"]
        assert referral["list_position_at_issue"] == 1
        assert referral["variant_applied"] == VARIANT_STRICT_GROUP_ORDER

        referred = fx.read_registration(api, scene["first_registration"]["id"])
        assert referred["status"] == REGISTRATION_REFERRED
        assert referred["position_number"] is None
        assert fx.read_registration(api, scene["second_registration"]["id"])[
            "position_number"
        ] == 1
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 1

    def test_a_bare_refusal_returns_the_registration_to_the_book_one_place_down(
        self, api
    ):
        """
        PRD §3.7: "The referral becomes `REFUSED` with a null cause code, the
        registration's `demotion_count` is incremented by 1 — which ranks it
        behind every peer on its list carrying a lower `demotion_count`, since
        `demotion_count` sorts ahead of the ordering-policy key in both variants —
        the registration and every peer on the list have their `position_number`
        recomputed, the request's open-slot counters are recomputed and its
        `version` increments by 1, and a `REFERRAL_REFUSED` entry is appended
        whose `snapshot_json` records that no good cause was claimed."

        Design: Difficulty/non_linear_state_machine/registration_refusal_cycle_returns_to_registered
        """
        scene = _refusal_scene(api)
        referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])

        refused = fx.refuse_referral(api, referral["id"], scene["first"]["id"])

        assert refused["status"] == REFERRAL_REFUSED
        assert refused["refusal_good_cause_code"] is None

        back_on_book = fx.read_registration(api, scene["first_registration"]["id"])
        assert back_on_book["status"] == REGISTRATION_REGISTERED
        assert back_on_book["demotion_count"] == 1
        # The higher-hours registrant is now behind the peer it outranked, purely
        # on the demotion it just took.
        assert back_on_book["position_number"] == 2
        assert fx.read_registration(api, scene["second_registration"]["id"])[
            "position_number"
        ] == 1
        assert fx.read_list_group(api, scene["hall"]["group_1_id"])[
            "registered_count"
        ] == 2

    def test_the_next_referral_goes_to_the_registration_now_standing_first(self, api):
        """
        PRD §3.2: "then by `demotion_count` ascending, so a registration carrying
        fewer charged demotions ranks ahead of one carrying more"

        Design: Difficulty/non_linear_state_machine/registration_refusal_cycle_returns_to_registered
        """
        scene = _refusal_scene(api)
        first_referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])
        fx.refuse_referral(api, first_referral["id"], scene["first"]["id"])

        # The request's version moved with the refusal, so the second issuance
        # pins the freshly read value.
        second_referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])

        assert second_referral["registration_id"] == scene["second_registration"]["id"]
        assert second_referral["member_id"] == scene["second"]["id"]
        assert second_referral["list_position_at_issue"] == 1
        assert second_referral["status"] == REFERRAL_ISSUED

    def test_the_refused_registration_can_be_referred_again(self, api):
        """
        PRD §3.3: "Registrations may be listed and filtered by `member_id`, by
        `list_id`, by `status`, and by `predecessor_registration_id`, and any
        single registration can be read with its computed `position_number`,
        `credited_seniority_hours`, `demotion_count`, and `priority_flag`."

        Design: Difficulty/non_linear_state_machine/registration_refusal_cycle_returns_to_registered
        """
        scene = _refusal_scene(api)
        first_referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])
        fx.refuse_referral(api, first_referral["id"], scene["first"]["id"])
        _issue_journeyworker_referral(api, scene["job_request"]["id"])

        registered = fx.registrations_on(
            api, scene["hall"]["group_1_id"], status=REGISTRATION_REGISTERED
        )

        # Only the refused registration is left on the numbered book, and it is
        # back at ordinal one now that its peer has been referred out.
        assert [row["id"] for row in registered] == [
            scene["first_registration"]["id"]
        ]
        assert registered[0]["position_number"] == 1
        assert registered[0]["demotion_count"] == 1


class TestJobRequestSuspendResumeCycle:
    """OPEN to PARTIALLY_FILLED to SUSPENDED and back to PARTIALLY_FILLED."""

    def test_one_acceptance_advances_an_open_request_to_partially_filled(self, api):
        """
        PRD §3.5: "When an acceptance leaves the accepted headcount —
        journeyworkers plus apprentices — greater than zero but still short of the
        total requested, an `OPEN` request advances to `PARTIALLY_FILLED`."

        Design: Difficulty/non_linear_state_machine/job_request_suspend_resume_cycle
        """
        scene = _suspension_scene(api)
        assert scene["job_request"]["status"] == JOB_REQUEST_OPEN
        assert scene["job_request"]["open_journeyworker_slots"] == 2
        assert scene["job_request"]["suspended_from_status"] is None

        referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])
        fx.accept_referral(api, referral["id"], scene["first"]["id"])

        partially_filled = fx.read_job_request(api, scene["job_request"]["id"])
        assert partially_filled["status"] == JOB_REQUEST_PARTIALLY_FILLED
        assert partially_filled["open_journeyworker_slots"] == 1
        assert partially_filled["accepted_journeyworker_count"] == 1

    def test_contractor_delinquency_records_the_status_the_request_left(self, api):
        """
        PRD §3.5: "the first hop moves every `OPEN` or `PARTIALLY_FILLED` job
        request of that contractor to `SUSPENDED`, recording the status it held in
        `suspended_from_status` — a field that is null unless the request is
        suspended and otherwise holds `OPEN` or `PARTIALLY_FILLED` — and
        incrementing each request's `version`."

        Design: Difficulty/non_linear_state_machine/job_request_suspend_resume_cycle
        """
        scene = _suspension_scene(api)
        referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])
        fx.accept_referral(api, referral["id"], scene["first"]["id"])

        fx.set_signatory_status(
            api, scene["contractor"]["id"], DELINQUENT_TRUST_FUNDS
        )

        suspended = fx.read_job_request(api, scene["job_request"]["id"])
        assert suspended["status"] == JOB_REQUEST_SUSPENDED
        assert suspended["suspended_from_status"] == JOB_REQUEST_PARTIALLY_FILLED

    def test_no_referral_may_be_issued_while_the_request_is_suspended(self, api):
        """
        PRD §3.5: "A referral issued against a suspended request is refused with
        `ERR_JOB_REQUEST_SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/job_request_suspend_resume_cycle
        """
        scene = _suspension_scene(api)
        referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])
        fx.accept_referral(api, referral["id"], scene["first"]["id"])
        fx.set_signatory_status(
            api, scene["contractor"]["id"], DELINQUENT_TRUST_FUNDS
        )

        version = fx.job_request_version(api, scene["job_request"]["id"])
        response = api.create_referral(
            scene["job_request"]["id"],
            f.referral_payload(version, slot_kind=SLOT_JOURNEYWORKER),
            DISPATCHER,
        )

        expect_error(response, ERR_JOB_REQUEST_SUSPENDED)

    def test_reinstatement_restores_the_recorded_status_and_reopens_the_slot(
        self, api
    ):
        """
        PRD §3.5: "When the contractor's `signatory_status` returns to
        `SIGNATORY`, each `SUSPENDED` request returns to whichever value its
        `suspended_from_status` recorded — `OPEN` or `PARTIALLY_FILLED` — that
        field is cleared back to null, the open-slot counters are recomputed, and
        `version` increments."

        Design: Difficulty/non_linear_state_machine/job_request_suspend_resume_cycle
        """
        scene = _suspension_scene(api)
        referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])
        fx.accept_referral(api, referral["id"], scene["first"]["id"])
        fx.set_signatory_status(
            api, scene["contractor"]["id"], DELINQUENT_TRUST_FUNDS
        )

        fx.set_signatory_status(api, scene["contractor"]["id"], SIGNATORY)

        resumed = fx.read_job_request(api, scene["job_request"]["id"])
        assert resumed["status"] == JOB_REQUEST_PARTIALLY_FILLED
        assert resumed["suspended_from_status"] is None
        assert resumed["open_journeyworker_slots"] == 1

    def test_the_reopened_slot_is_dispatched_from_the_list_again(self, api):
        """
        PRD §3.5: "The withdrawn referrals are **not** reissued; the reopened
        slots must be dispatched from the list again, which means the members who
        were pulled back take their chances in the ranking exactly like everybody
        else."

        Design: Difficulty/non_linear_state_machine/job_request_suspend_resume_cycle
        """
        scene = _suspension_scene(api)
        first_referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])
        fx.accept_referral(api, first_referral["id"], scene["first"]["id"])
        fx.set_signatory_status(
            api, scene["contractor"]["id"], DELINQUENT_TRUST_FUNDS
        )
        fx.set_signatory_status(api, scene["contractor"]["id"], SIGNATORY)

        version = fx.job_request_version(api, scene["job_request"]["id"])
        second_referral = expect_created(
            api.create_referral(
                scene["job_request"]["id"],
                f.referral_payload(version, slot_kind=SLOT_JOURNEYWORKER),
                DISPATCHER,
            )
        )

        assert second_referral["registration_id"] == scene["second_registration"]["id"]
        assert second_referral["status"] == REFERRAL_ISSUED

    def test_every_leg_of_the_cycle_advances_the_request_version(self, api):
        """
        PRD §3.5: "Issuance itself never changes `status`, because status derives
        from accepted referrals only."

        Design: Difficulty/non_linear_state_machine/job_request_suspend_resume_cycle
        """
        scene = _suspension_scene(api)
        version_at_intake = scene["job_request"]["version"]

        referral = _issue_journeyworker_referral(api, scene["job_request"]["id"])
        version_after_issue = fx.job_request_version(api, scene["job_request"]["id"])
        assert (
            fx.read_job_request(api, scene["job_request"]["id"])["status"]
            == JOB_REQUEST_OPEN
        )

        fx.accept_referral(api, referral["id"], scene["first"]["id"])
        version_after_accept = fx.job_request_version(api, scene["job_request"]["id"])

        fx.set_signatory_status(
            api, scene["contractor"]["id"], DELINQUENT_TRUST_FUNDS
        )
        version_after_suspend = fx.job_request_version(api, scene["job_request"]["id"])

        fx.set_signatory_status(api, scene["contractor"]["id"], SIGNATORY)
        version_after_resume = fx.job_request_version(api, scene["job_request"]["id"])

        assert (
            version_at_intake
            < version_after_issue
            < version_after_accept
            < version_after_suspend
            < version_after_resume
        )
