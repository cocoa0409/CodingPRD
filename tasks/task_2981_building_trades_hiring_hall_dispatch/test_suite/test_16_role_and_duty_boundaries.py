"""
Who may do what, and who may not: the one operation the dispatcher holds alone,
two more fences that hold even for a role already acting on the same record, one
operation shared by exactly two roles and refused to the other three, and a
separation that is drawn around a user id rather than around a role name.
"""

from test_helpers import (
    BUSINESS_MANAGER,
    BUSINESS_MANAGER_USER_ID,
    CLAIM_IMPROPER_NAMED_CALL,
    DECISION_DENIED,
    DECISION_SUSTAINED,
    DISPATCH_LAID_OFF,
    DISPATCH_WORKING,
    DISPATCHER,
    DISPATCHER_USER_ID,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    GRIEVANCE_DENIED,
    GRIEVANCE_FILED,
    GRIEVANCE_UNDER_REVIEW,
    HALL_ADMIN,
    REMEDY_NONE,
    SLOT_JOURNEYWORKER,
    assert_instant_equals,
    expect_created,
    expect_error,
    expect_ok,
    factories as f,
    fixtures as fx,
    make_business_manager_headers,
    make_contractor_rep_headers,
    make_member_headers,
)

CLOCK = "2026-09-01T00:00:00.000Z"

# ─── The dispatcher's sole exclusive operation ─────────────────────────────────

SOLE_SIGNER = "Nils Aberg"
SOLE_SIGNER_HOURS = 9000
ISSUE_JOB_SITE = "Cooling Tower"
ISSUE_DURATION_DAYS = 20
ISSUE_RATE_CENTS = 5000

# ─── Review, adjudication and recall ──────────────────────────────────────────

WORKING_MEMBER = "Ola Bright"
WORKING_HOURS = 9000
GRIEVING_MEMBER = "Petra Ilves"
GRIEVING_HOURS = 8000
FENCE_JOB_SITE = "Bag House"
FENCE_JOURNEYWORKERS = 2
FENCE_REPORT_AT = "2026-09-10T07:00:00.000Z"
FENCE_DURATION_DAYS = 20
FENCE_RATE_CENTS = 5000
FENCE_NARRATIVE = "This was a named call in disguise."
LAYOFF_CLOCK = "2026-09-20T07:00:00.000Z"
LAYOFF_HOURS = 80
RECALL_WINDOW_ENDS_AT = "2026-09-27T07:00:00.000Z"
RECALL_REPORT_AT = "2026-09-24T07:00:00.000Z"

# ─── The shared housekeeping sweep ────────────────────────────────────────────

IDLE_MEMBER = "Quinn Barros"
IDLE_MEMBER_HOURS = 9000

# ─── Segregation by user id ───────────────────────────────────────────────────

ISSUED_TO_MEMBER = "Rex Halloran"
ISSUED_TO_HOURS = 9000
PASSED_OVER_MEMBER = "Sena Duro"
PASSED_OVER_HOURS = 8000
SOD_JOB_SITE = "Ash Handling"
SOD_JOURNEYWORKERS = 2
SOD_DURATION_DAYS = 20
SOD_RATE_CENTS = 5000
SOD_NARRATIVE = "The dispatcher skipped the list."
SOD_NOTE = "Nothing to see here."


def _one_signer_and_one_open_call(api):
    """A single registrant and a single open journeyworker slot to fill."""
    hall = fx.standard_hall(api, clock=CLOCK)
    member = fx.add_journeyworker(
        api, hall["home_local_id"], SOLE_SIGNER, SOLE_SIGNER_HOURS
    )
    registration = fx.sign_book(api, member["id"], hall["group_1_id"])
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=ISSUE_JOB_SITE,
        expected_duration_days=ISSUE_DURATION_DAYS,
        hourly_rate_cents=ISSUE_RATE_CENTS,
    )
    return {
        "hall": hall,
        "member": member,
        "registration": registration,
        "contractor": contractor,
        "job_request": job_request,
    }


def _issue_as(api, scene, headers):
    """The identical issuance body, offered under whatever headers are supplied."""
    return api.create_referral(
        scene["job_request"]["id"],
        f.referral_payload(
            scene["job_request"]["version"], slot_kind=SLOT_JOURNEYWORKER
        ),
        headers,
    )


class TestIssuingAReferralIsTheDispatchersAlone:
    """
    Four other roles offer the identical body and are all turned away — including
    the administrator who entered every record and the employer who owns the call.
    """

    def test_the_administrator_and_the_manager_are_both_refused(self, api):
        """
        PRD §2.1: "A `Dispatcher` works the out-of-work lists and is the only role
        permitted to issue a referral."

        PRD §2.7: "Role permission — the acting role appears in the endpoint's
        authorized-role list — on every endpoint, failing with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/only_the_dispatcher_may_issue_a_referral
        """
        scene = _one_signer_and_one_open_call(api)

        expect_error(
            _issue_as(api, scene, HALL_ADMIN), ERR_ROLE_NOT_PERMITTED, status=403
        )
        expect_error(
            _issue_as(api, scene, BUSINESS_MANAGER), ERR_ROLE_NOT_PERMITTED, status=403
        )

    def test_owning_the_call_does_not_earn_the_right_to_fill_it(self, api):
        """
        The employer's own representative is refused as a role rather than as a stranger,
        because the role check runs ahead of the ownership check.

        PRD §2.1: "Once the caller is authenticated, the acting role must appear in the
        authorized-role list published for the requested endpoint in §4; otherwise the
        request is rejected with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."

        Design: Corner/rbac/only_the_dispatcher_may_issue_a_referral
        """
        scene = _one_signer_and_one_open_call(api)

        as_owner = _issue_as(
            api, scene, make_contractor_rep_headers(scene["contractor"]["id"])
        )
        expect_error(as_owner, ERR_ROLE_NOT_PERMITTED, status=403)

        as_the_registrant = _issue_as(
            api, scene, make_member_headers(scene["member"]["id"])
        )
        expect_error(as_the_registrant, ERR_ROLE_NOT_PERMITTED, status=403)

    def test_the_dispatcher_succeeds_and_the_refusals_wrote_nothing(self, api):
        """
        The one role that holds the operation gets it, and the four refusals before it left
        no referral behind.

        PRD §2.1: "A `Dispatcher` works the out-of-work lists and is the only role permitted
        to issue a referral."

        Design: Corner/rbac/only_the_dispatcher_may_issue_a_referral
        """
        scene = _one_signer_and_one_open_call(api)
        for headers in (HALL_ADMIN, BUSINESS_MANAGER):
            expect_error(
                _issue_as(api, scene, headers), ERR_ROLE_NOT_PERMITTED, status=403
            )

        issued = expect_created(_issue_as(api, scene, DISPATCHER))

        assert issued["member_id"] == scene["member"]["id"]
        assert issued["issued_by_user_id"] == DISPATCHER_USER_ID
        rows = fx.referrals_on(api, scene["job_request"]["id"])
        assert [row["id"] for row in rows] == [issued["id"]]


def _a_laid_off_dispatch_and_an_unopened_grievance(api):
    """
    One member worked and was laid off by the administrator on a phoned-in report,
    and the member behind him on the list has filed against the referral.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    signed = fx.register_journeyworkers(
        api,
        hall["home_local_id"],
        hall["group_1_id"],
        [(WORKING_MEMBER, WORKING_HOURS), (GRIEVING_MEMBER, GRIEVING_HOURS)],
    )
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=FENCE_JOB_SITE,
        journeyworkers_requested=FENCE_JOURNEYWORKERS,
        report_at=FENCE_REPORT_AT,
        expected_duration_days=FENCE_DURATION_DAYS,
        hourly_rate_cents=FENCE_RATE_CENTS,
    )
    referral = fx.issue_referral(api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER)
    dispatch = fx.accept_referral(api, referral["id"], signed[0]["member"]["id"])
    grievance = fx.file_grievance(
        api,
        referral["id"],
        signed[1]["member"]["id"],
        claim_type=CLAIM_IMPROPER_NAMED_CALL,
        narrative=FENCE_NARRATIVE,
    )
    fx.set_clock(api, LAYOFF_CLOCK)
    laid_off = expect_ok(
        api.layoff_dispatch(
            dispatch["id"], f.layoff_payload(LAYOFF_HOURS), HALL_ADMIN
        )
    )
    return {
        "hall": hall,
        "worked": signed[0],
        "grieved": signed[1],
        "contractor": contractor,
        "job_request": job_request,
        "referral": referral,
        "dispatch": dispatch,
        "grievance": grievance,
        "laid_off": laid_off,
    }


class TestReviewAdjudicateAndRecallStayWithTheirOwners:
    """
    Sharing one action on a record does not carry the next one: the administrator
    may close the employment but may not reopen it, and neither of the two roles
    around the dispatch may touch the grievance file.
    """

    def test_only_the_business_manager_may_open_the_file(self, api):
        """
        PRD §3.9: "Its `status` begins at `FILED`, and the business manager opens it for
        consideration, moving it to `UNDER_REVIEW` and incrementing its `version` by 1."

        Design: Corner/rbac/review_adjudicate_and_recall_stay_inside_their_owning_roles
        """
        scene = _a_laid_off_dispatch_and_an_unopened_grievance(api)
        assert scene["grievance"]["status"] == GRIEVANCE_FILED

        expect_error(
            api.review_grievance(scene["grievance"]["id"], DISPATCHER),
            ERR_ROLE_NOT_PERMITTED,
            status=403,
        )
        expect_error(
            api.review_grievance(scene["grievance"]["id"], HALL_ADMIN),
            ERR_ROLE_NOT_PERMITTED,
            status=403,
        )

        opened = expect_ok(
            api.review_grievance(scene["grievance"]["id"], BUSINESS_MANAGER)
        )
        assert opened["status"] == GRIEVANCE_UNDER_REVIEW

    def test_the_administrator_may_close_the_job_but_not_reopen_it(self, api):
        """
        PRD §3.8: "Only the contractor's own representative may recall, and only a dispatch
        whose `status` is `LAID_OFF` is recallable — a `WORKING`, `TERMINATED_FOR_CAUSE`, or
        `QUIT` record is refused with `ERR_RECALL_NOT_ELIGIBLE`."

        Design: Corner/rbac/review_adjudicate_and_recall_stay_inside_their_owning_roles
        """
        scene = _a_laid_off_dispatch_and_an_unopened_grievance(api)
        assert scene["laid_off"]["status"] == DISPATCH_LAID_OFF
        assert_instant_equals(
            scene["laid_off"]["recall_window_ends_at"], RECALL_WINDOW_ENDS_AT
        )

        expect_error(
            api.recall_dispatch(
                scene["dispatch"]["id"], f.recall_payload(RECALL_REPORT_AT), HALL_ADMIN
            ),
            ERR_ROLE_NOT_PERMITTED,
            status=403,
        )

        recalled = expect_created(
            api.recall_dispatch(
                scene["dispatch"]["id"],
                f.recall_payload(RECALL_REPORT_AT),
                make_contractor_rep_headers(scene["contractor"]["id"]),
            )
        )
        assert recalled["status"] == DISPATCH_WORKING
        assert recalled["recall_of_dispatch_id"] == scene["dispatch"]["id"]

    def test_the_dispatcher_cannot_decide_the_file_it_created(self, api):
        """
        PRD §2.1: "A `BusinessManager` is the elected officer who reviews and decides
        grievances, awards make-whole remedies, and rules on member standing and contractor
        signatory status; the role never issues referrals, which is what makes adjudication
        structurally separable from dispatch."

        Design: Corner/rbac/review_adjudicate_and_recall_stay_inside_their_owning_roles
        """
        scene = _a_laid_off_dispatch_and_an_unopened_grievance(api)
        opened = expect_ok(
            api.review_grievance(scene["grievance"]["id"], BUSINESS_MANAGER)
        )
        assert opened["status"] == GRIEVANCE_UNDER_REVIEW

        refused = api.adjudicate_grievance(
            scene["grievance"]["id"],
            f.adjudication_payload(decision=DECISION_DENIED, remedy=REMEDY_NONE),
            DISPATCHER,
        )

        expect_error(refused, ERR_ROLE_NOT_PERMITTED, status=403)
        still_open = expect_ok(
            api.get_grievance(scene["grievance"]["id"], BUSINESS_MANAGER)
        )
        assert still_open["status"] == GRIEVANCE_UNDER_REVIEW
        assert still_open["decided_by_user_id"] is None


def _an_idle_hall(api):
    """
    Books opened and nobody on them: one local, one list group, one member who
    never signed, and one employer who never called — so every bucket is zero.
    """
    fx.set_clock(api, CLOCK)
    home_local = fx.add_home_local(api)
    group = fx.add_list_group(api, f.group_one_payload())
    member = fx.add_journeyworker(
        api, home_local["id"], IDLE_MEMBER, IDLE_MEMBER_HOURS
    )
    contractor = fx.add_contractor(api)
    return {
        "home_local": home_local,
        "group": group,
        "member": member,
        "contractor": contractor,
    }


class TestTheSweepIsSharedByExactlyTwoRoles:
    """
    A shared operation has to work for every role on its list and for nobody else,
    and on an idle hall it reports zeros rather than refusing.
    """

    def test_the_administrator_runs_it_against_the_logical_clock(self, api):
        """
        PRD §3.4: "Everything the hall would otherwise do on a timer is instead driven
        explicitly by a housekeeping sweep, which a `HallAdmin` or `Dispatcher` runs against
        the current logical clock."

        Design: Corner/rbac/the_sweep_is_shared_by_hall_admin_and_dispatcher_only
        """
        _an_idle_hall(api)

        summary = fx.run_sweep(api, HALL_ADMIN)

        assert_instant_equals(summary["run_at"], CLOCK)
        assert summary["expired_referral_count"] == 0
        assert summary["expired_registration_count"] == 0

    def test_the_dispatcher_runs_the_same_sweep_to_the_same_shape(self, api):
        """
        PRD §3.4: "The sweep reports what it did: `run_at` echoes the instant the run was
        evaluated against, `expired_referral_count` the number of referrals expired in step
        one, `demoted_registration_count` the number of registrations returned to the book
        with a demotion charged, `removed_registration_count` the number removed for a third
        strike, `expired_registration_count` the number expired for a lapsed re-sign, and
        `purged_ledger_entry_count` the number of ledger snapshots purged."

        Design: Corner/rbac/the_sweep_is_shared_by_hall_admin_and_dispatcher_only
        """
        _an_idle_hall(api)

        summary = fx.run_sweep(api, DISPATCHER)

        assert_instant_equals(summary["run_at"], CLOCK)
        assert summary["expired_referral_count"] == 0
        assert summary["demoted_registration_count"] == 0
        assert summary["removed_registration_count"] == 0
        assert summary["expired_registration_count"] == 0
        assert summary["purged_ledger_entry_count"] == 0

    def test_the_other_three_roles_are_refused_the_sweep(self, api):
        """
        PRD §2.7: "Role permission — the acting role appears in the endpoint's
        authorized-role list — on every endpoint, failing with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/the_sweep_is_shared_by_hall_admin_and_dispatcher_only
        """
        scene = _an_idle_hall(api)

        expect_error(
            api.run_dispatch_run(BUSINESS_MANAGER), ERR_ROLE_NOT_PERMITTED, status=403
        )
        expect_error(
            api.run_dispatch_run(
                make_contractor_rep_headers(scene["contractor"]["id"])
            ),
            ERR_ROLE_NOT_PERMITTED,
            status=403,
        )
        expect_error(
            api.run_dispatch_run(make_member_headers(scene["member"]["id"])),
            ERR_ROLE_NOT_PERMITTED,
            status=403,
        )


def _a_file_open_against_the_dispatchers_own_referral(api):
    """
    disp-01 issues the referral, the passed-over member grieves it, and bm-09
    opens the file — so the issuer's id is on the record under challenge.
    """
    hall = fx.standard_hall(api, clock=CLOCK)
    signed = fx.register_journeyworkers(
        api,
        hall["home_local_id"],
        hall["group_1_id"],
        [(ISSUED_TO_MEMBER, ISSUED_TO_HOURS), (PASSED_OVER_MEMBER, PASSED_OVER_HOURS)],
    )
    contractor = fx.add_contractor(api)
    job_request = fx.open_job_request(
        api,
        contractor["id"],
        job_site=SOD_JOB_SITE,
        journeyworkers_requested=SOD_JOURNEYWORKERS,
        expected_duration_days=SOD_DURATION_DAYS,
        hourly_rate_cents=SOD_RATE_CENTS,
    )
    referral = fx.issue_referral(api, job_request["id"], slot_kind=SLOT_JOURNEYWORKER)
    grievance = fx.grievance_under_review(
        api,
        referral["id"],
        signed[1]["member"]["id"],
        claim_type=CLAIM_IMPROPER_NAMED_CALL,
        narrative=SOD_NARRATIVE,
    )
    return {
        "hall": hall,
        "referred": signed[0],
        "grieved": signed[1],
        "job_request": job_request,
        "referral": referral,
        "grievance": grievance,
    }


def _decide_as(api, grievance, headers, decision, remedy, **extra):
    """One adjudication attempt under a specific user id, left unwrapped."""
    return api.adjudicate_grievance(
        grievance["id"],
        f.adjudication_payload(decision=decision, remedy=remedy, **extra),
        headers,
    )


class TestSegregationIsDrawnAroundTheUserIdNotTheRole:
    """
    The manager's hat is not the question: the same person who issued the referral
    cannot decide the grievance about it, and a different manager can.
    """

    def test_the_issuers_own_id_cannot_decide_the_grievance(self, api):
        """
        PRD §2.10: "At a small local the same person may legitimately hold a dispatcher's
        job and be elected business manager, so the system does not forbid one human from
        holding both roles; it forbids one `X-User-ID` from deciding a grievance about a
        referral that the same `X-User-ID` issued."

        Design: Corner/rbac/the_issuing_users_own_id_cannot_adjudicate_the_grievance_it_caused
        """
        scene = _a_file_open_against_the_dispatchers_own_referral(api)
        assert scene["referral"]["issued_by_user_id"] == DISPATCHER_USER_ID
        assert scene["grievance"]["status"] == GRIEVANCE_UNDER_REVIEW

        refused = _decide_as(
            api,
            scene["grievance"],
            make_business_manager_headers(DISPATCHER_USER_ID),
            DECISION_DENIED,
            REMEDY_NONE,
            note=SOD_NOTE,
        )

        expect_error(refused, ERR_SEGREGATION_OF_DUTIES, status=403)
        mid = expect_ok(api.get_grievance(scene["grievance"]["id"], BUSINESS_MANAGER))
        assert mid["status"] == GRIEVANCE_UNDER_REVIEW
        assert mid["decided_at"] is None

    def test_a_different_manager_decides_the_identical_payload(self, api):
        """
        PRD §2.10: "The referral's `issued_by_user_id` and the adjudicator's `X-User-ID` are
        compared directly, and equality is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_issuing_users_own_id_cannot_adjudicate_the_grievance_it_caused
        """
        scene = _a_file_open_against_the_dispatchers_own_referral(api)
        expect_error(
            _decide_as(
                api,
                scene["grievance"],
                make_business_manager_headers(DISPATCHER_USER_ID),
                DECISION_DENIED,
                REMEDY_NONE,
                note=SOD_NOTE,
            ),
            ERR_SEGREGATION_OF_DUTIES,
            status=403,
        )

        decided = expect_ok(
            _decide_as(
                api,
                scene["grievance"],
                BUSINESS_MANAGER,
                DECISION_DENIED,
                REMEDY_NONE,
                note=SOD_NOTE,
            )
        )

        assert decided["status"] == GRIEVANCE_DENIED
        assert decided["decided_by_user_id"] == BUSINESS_MANAGER_USER_ID
        assert_instant_equals(decided["decided_at"], CLOCK)

    def test_the_identity_check_still_answers_after_the_file_is_closed(self, api):
        """
        A decided grievance would also fail the state check, but the identity check is
        evaluated first and is the one reported.

        PRD §2.7: "Segregation of duties on grievance adjudication, failing with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_issuing_users_own_id_cannot_adjudicate_the_grievance_it_caused
        """
        scene = _a_file_open_against_the_dispatchers_own_referral(api)
        expect_ok(
            _decide_as(
                api,
                scene["grievance"],
                BUSINESS_MANAGER,
                DECISION_DENIED,
                REMEDY_NONE,
                note=SOD_NOTE,
            )
        )

        refused = _decide_as(
            api,
            scene["grievance"],
            make_business_manager_headers(DISPATCHER_USER_ID),
            DECISION_SUSTAINED,
            REMEDY_NONE,
        )

        expect_error(refused, ERR_SEGREGATION_OF_DUTIES, status=403)
        assert (
            expect_ok(api.get_grievance(scene["grievance"]["id"], BUSINESS_MANAGER))[
                "status"
            ]
            == GRIEVANCE_DENIED
        )
