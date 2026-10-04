"""Per-university employer approvals: creation, OCC-gated decisions, and the
BLOCK cascade across postings, applications, and interviews."""
from test_helpers import (
    ApiErrorId,
    advance_application,
    apply_as_student,
    assert_employer_approval,
    create_active_university,
    create_approved_employer,
    create_document,
    create_student,
    decide_approval,
    get_employer,
    make_career_center_admin_headers,
    request_approval,
    screen_employer,
    set_clock,
    setup_base_marketplace,
    setup_interviewing_application,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PA


def _setup_block_scenario(api):
    """Base marketplace plus Sam's application at INTERVIEWING with one SCHEDULED
    interview, and Sally's application at OFFER_EXTENDED on the same posting."""
    ctx = setup_base_marketplace()
    application, interview = setup_interviewing_application(ctx)
    sally = create_student(
        ctx["university"]["id"], email="sally@stateu.edu", full_name="Sally Kim",
        major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
    )
    offer = apply_as_student(
        sally["id"], ctx["posting"]["id"],
        submitted_documents=[create_document("RESUME", "s3://docs/sally-resume.pdf")],
    )
    advance_application(offer["id"], ctx["employer"]["id"], "OFFER_EXTENDED")
    ctx.update({"application": application, "interview": interview,
                "sally": sally, "offer": offer})
    return ctx


class TestApprovalCreation:
    def test_approval_created_in_pending(self, api):
        """PRD §3.3: "While an approval is `PENDING`, its `decision_reason`,
        `decided_at`, and `trust_tier_at_decision` are all null."
        PRD §3.3: "the old row moves to `SUPERSEDED`, and the new row is created in
        `PENDING` with its `supersedes_approval_id` pointing at the row it replaced; in
        every other case `supersedes_approval_id` is null."

        Design: Corner/state_machines/employer_approval_created_in_pending
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        approval = request_approval(employer["id"], university["id"])
        assert_employer_approval(approval)
        assert approval["status"] == "PENDING"
        assert approval["decided_at"] is None
        assert approval["decision_reason"] is None
        assert approval["trust_tier_at_decision"] is None
        assert approval["supersedes_approval_id"] is None


class TestBlockCascade:
    def test_block_cascades_to_posting_application_and_interview(self, api):
        """PRD §3.3: "`BLOCK` and `REVOKE` additionally fire the same three-hop cascade
        across the employer's footprint at this university. Hop one: for every posting
        of the employer whose stored status is `PUBLISHED`, this university's id is
        appended to the posting's `blocked_university_ids`, and each touched posting's
        `version` increments by 1. Hop two: every application from a student whose
        `university_id` is this university to one of those just-blocked postings, while
        in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING`, moves to `AUTO_WITHDRAWN`,
        and each such transition decrements its posting's `active_application_count` by
        1. Hop three: every interview still `SCHEDULED` on an application that just
        became `AUTO_WITHDRAWN` moves to `CANCELLED`."
        PRD §3.3: "pins `trust_tier_at_decision` from the employer's current
        `trust_tier` as of the decision"

        Design: Difficulty/transitive_cascade/block_approval_cascades_postings_applications_interviews
        """
        ctx = _setup_block_scenario(api)
        university_id = ctx["university"]["id"]
        # The approval is APPROVED once the footprint exists (applications
        # require it), so per PRD §3.3 the only legal block-side decision is
        # REVOKE — which fires the same three-hop cascade as BLOCK.
        decided = decide_approval(
            ctx["approval"]["id"], university_id, "REVOKE",
            decision_reason="fraud concern", employer_id=ctx["employer"]["id"],
        )
        assert decided["status"] == "REVOKED"
        assert decided["trust_tier_at_decision"] == "STANDARD"
        assert decided["decided_at"] is not None

        posting = validate_success(api.get_job_posting(ctx["posting"]["id"], PA), 200)
        assert university_id in posting["blocked_university_ids"], (
            "HOP 1: the blocked university must land in blocked_university_ids"
        )

        application = validate_success(
            api.get_application(ctx["application"]["id"], PA), 200
        )
        assert application["status"] == "AUTO_WITHDRAWN", (
            "HOP 2: the INTERVIEWING application must auto-withdraw"
        )

        interviews = validate_success(
            api.list_interviews(ctx["application"]["id"], PA), 200
        )
        assert len(interviews) == 1
        assert interviews[0]["id"] == ctx["interview"]["id"]
        assert interviews[0]["status"] == "CANCELLED", (
            "HOP 3: the SCHEDULED interview must be cancelled"
        )

    def test_block_leaves_offer_extended_applications_untouched(self, api):
        """PRD §3.3: "The cascade is deliberately conditional: applications already at
        `OFFER_EXTENDED` are not touched — an outstanding offer survives an employer
        block."
        PRD §3.4: "The `active_application_count` itself is a conserved quantity over
        the four active statuses — `SUBMITTED`, `UNDER_REVIEW`, `INTERVIEWING`, and
        `OFFER_EXTENDED`."

        Design: Difficulty/transitive_cascade/block_approval_cascades_postings_applications_interviews
        """
        ctx = _setup_block_scenario(api)
        # REVOKE from APPROVED fires the same cascade as BLOCK (PRD §3.3);
        # BLOCK is legal only from PENDING, where no footprint can exist.
        decide_approval(
            ctx["approval"]["id"], ctx["university"]["id"], "REVOKE",
            decision_reason="fraud concern", employer_id=ctx["employer"]["id"],
        )
        offer = validate_success(api.get_application(ctx["offer"]["id"], PA), 200)
        assert offer["status"] == "OFFER_EXTENDED", (
            "the OFFER_EXTENDED sibling must survive the block cascade"
        )
        posting = validate_success(api.get_job_posting(ctx["posting"]["id"], PA), 200)
        assert posting["active_application_count"] == 1, (
            "only the OFFER_EXTENDED application remains active (2 - 1 auto-withdrawn)"
        )


class TestDecideOptimisticConcurrency:
    def test_decide_with_stale_employer_version_returns_412(self, api):
        """PRD §2.8: "The career-center trust decision on an employer approval requires
        a non-optional `expected_employer_version` field equal to the target Employer's
        current `version`. A decision pins the employer's trust posture as the career
        center last observed it; if the Employer's `version` has advanced since — for
        example because a re-screen recomputed its fraud posture — the deciding view is
        stale and the request is rejected with `ERR_STALE_EMPLOYER_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/decide_with_stale_employer_version_returns_412
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        observed_version = employer["version"]
        assert observed_version == 3
        approval = request_approval(employer["id"], university["id"])
        # A re-screen between the career center's read and its decide call.
        screen_employer(employer["id"], "FLAG")
        response = api.decide_employer_approval(
            approval["id"],
            {"decision": "APPROVE", "expected_employer_version": observed_version},
            make_career_center_admin_headers(university["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STALE_EMPLOYER_VERSION, 412)

        approval_read = validate_success(
            api.get_employer_approval(approval["id"], PA), 200
        )
        assert approval_read["status"] == "PENDING", "the stale decision must not apply"
        assert approval_read["decided_at"] is None
        employer_read = get_employer(employer["id"])
        assert employer_read["version"] == 4
        assert employer_read["status"] == "UNDER_REVIEW"
