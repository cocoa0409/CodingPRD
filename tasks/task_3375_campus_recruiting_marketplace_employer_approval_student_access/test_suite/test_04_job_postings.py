"""Job posting lifecycle, clearance, read-time expiry projection, and versioning."""
from test_helpers import (
    ApiErrorId,
    apply_as_student,
    create_approved_employer,
    create_document,
    create_job_posting_payload,
    create_posting,
    create_published_posting,
    create_student,
    make_career_center_admin_headers,
    make_employer_recruiter_headers,
    make_student_headers,
    set_clock,
    setup_base_marketplace,
    transition_posting,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PA


class TestPublishPauseCycle:
    def test_apply_rejected_while_paused(self, api):
        """PRD §3.7: "the posting's stored status must be `PUBLISHED` — a posting in
        `DRAFT`, `SUBMITTED`, or `PAUSED` fails with `ERR_POSTING_NOT_PUBLISHED`
        (HTTP 409)."
        PRD §3.4: "Once live, the owning recruiter may pause a posting from `PUBLISHED`
        to `PAUSED` and resume it from `PAUSED` back to `PUBLISHED`, resumption again
        requiring the employer to be `APPROVED`."

        Design: Difficulty/non_linear_state_machine/job_posting_published_paused_cycle
        """
        ctx = setup_base_marketplace()
        posting = ctx["posting"]
        paused = transition_posting(
            posting["id"], "PAUSED", make_employer_recruiter_headers(ctx["employer"]["id"])
        )
        assert paused["status"] == "PAUSED"
        response = api.create_application(
            {
                "student_id": ctx["student"]["id"],
                "job_posting_id": posting["id"],
                "submitted_documents": [
                    create_document("RESUME", "s3://docs/sam-resume.pdf")
                ],
            },
            make_student_headers(ctx["student"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_POSTING_NOT_PUBLISHED, 409)

    def test_resume_republishes_and_apply_succeeds(self, api):
        """PRD §3.4: "Once live, the owning recruiter may pause a posting from
        `PUBLISHED` to `PAUSED` and resume it from `PAUSED` back to `PUBLISHED`,
        resumption again requiring the employer to be `APPROVED`."
        PRD §3.4: "Each accepted transition increments the posting's `version` by 1."

        Design: Difficulty/non_linear_state_machine/job_posting_published_paused_cycle
        """
        ctx = setup_base_marketplace()
        posting = ctx["posting"]
        recruiter = make_employer_recruiter_headers(ctx["employer"]["id"])
        transition_posting(posting["id"], "PAUSED", recruiter)
        resumed = transition_posting(posting["id"], "PUBLISHED", recruiter)
        assert resumed["status"] == "PUBLISHED"
        # create 1, SUBMITTED 2, PUBLISHED 3, PAUSED 4, resume-PUBLISHED 5.
        assert resumed["version"] == 5
        application = apply_as_student(
            ctx["student"]["id"], posting["id"],
            submitted_documents=[create_document("RESUME", "s3://docs/sam-resume.pdf")],
        )
        assert application["status"] == "SUBMITTED"


class TestPostingCreation:
    def test_missing_application_deadline_returns_invalid_request(self, api):
        """PRD §3.4: "The posting carries a `title`; a `position_type` of `FULL_TIME`,
        `INTERNSHIP`, or `COOP`; and the eligibility filter set: `required_majors` (an
        array defaulting to empty, where empty means every major is eligible and a
        non-empty list requires the student's `major` to be a member),
        `min_graduation_year` and `max_graduation_year` (inclusive lower and upper
        bounds on the student's `graduation_year`; a `min_graduation_year` greater than
        `max_graduation_year` is a shape error, `ERR_INVALID_REQUEST`),
        `accepted_work_authorizations` (an array defaulting to empty, where empty means
        every authorization is accepted and a non-empty list requires membership),
        `required_documents` (an array defaulting to empty, whose members are drawn
        from `RESUME`, `COVER_LETTER`, `TRANSCRIPT`, and `PORTFOLIO`), and the
        inclusive `application_deadline`."
        PRD §2.9: "Malformed-body residual: a missing required field, a wrong-typed
        value, an out-of-enum member, a `min_graduation_year` greater than
        `max_graduation_year`, a `capacity` below 1, an in-person session without a
        room, or a virtual session carrying one — otherwise `ERR_INVALID_REQUEST`
        (400)."

        Design: Corner/entities/job_posting_create_missing_deadline_returns_invalid_request
        """
        set_clock()
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        payload = create_job_posting_payload(
            employer["id"], title="SWE Intern", position_type="INTERNSHIP",
            min_graduation_year=2026, max_graduation_year=2028,
        )
        del payload["application_deadline"]
        response = api.create_job_posting(
            payload, make_employer_recruiter_headers(employer["id"])
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        rows, _meta = validate_paginated(
            api.list_job_postings(PA, params={"employer_id": employer["id"]})
        )
        assert len(rows) == 0, "the rejected create must not persist a posting"


class TestPostingTerminalState:
    def test_closed_rejects_further_transitions(self, api):
        """PRD §3.4: "The owning recruiter may close a posting from any of `DRAFT`,
        `SUBMITTED`, `PUBLISHED`, or `PAUSED` into `CLOSED`, which is terminal: any
        transition out of `CLOSED` is rejected with `ERR_POSTING_TERMINAL` (HTTP 409),
        and any other illegal source-target pair with `ERR_INVALID_POSTING_TRANSITION`
        (HTTP 409)."

        Design: Corner/state_machines/posting_closed_rejects_further_transitions
        """
        set_clock()
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        posting = create_posting(employer["id"], title="SWE Intern")
        recruiter = make_employer_recruiter_headers(employer["id"])
        closed = validate_success(
            api.transition_job_posting(posting["id"], {"to": "CLOSED"}, recruiter), 200
        )
        assert closed["status"] == "CLOSED"
        response = api.transition_job_posting(posting["id"], {"to": "SUBMITTED"}, recruiter)
        validate_error(response, ApiErrorId.ERR_POSTING_TERMINAL, 409)
        read = validate_success(api.get_job_posting(posting["id"], PA), 200)
        assert read["status"] == "CLOSED"


class TestExpiryProjection:
    def test_projects_expired_after_deadline_without_rewrite(self, api):
        """PRD §2.10: "A posting whose stored status is `PUBLISHED` is reported as
        `EXPIRED` on every read — single read or list — once the logical clock has
        moved strictly past its `application_deadline`."
        PRD §2.10: "The stored status is never rewritten by this projection; `EXPIRED`
        exists only in read output."

        Design: Corner/endpoints/posting_status_projects_expired_after_deadline_without_rewrite
        """
        set_clock()
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        posting = create_published_posting(
            employer["id"], title="Deadline Intern",
            application_deadline="2026-10-01T12:00:00Z",
        )
        set_clock("2026-10-02T00:00:00Z")
        projected = validate_success(api.get_job_posting(posting["id"], PA), 200)
        assert projected["status"] == "EXPIRED", (
            f"stored PUBLISHED past deadline must project EXPIRED, got {projected['status']}"
        )
        # PAUSED is legal only from stored PUBLISHED — proof the row was not rewritten.
        paused = validate_success(
            api.transition_job_posting(
                posting["id"], {"to": "PAUSED"},
                make_employer_recruiter_headers(employer["id"]),
            ),
            200,
        )
        assert paused["status"] == "PAUSED"
        reread = validate_success(api.get_job_posting(posting["id"], PA), 200)
        assert reread["status"] == "PAUSED"


class TestPostingClearance:
    def test_block_cascades_then_clear_restores(self, api):
        """PRD §3.4: "`BLOCK` appends the university to the posting's
        `blocked_university_ids` and fires the same application-level cascade as an
        employer block: applications from students of that university to this posting,
        while in `SUBMITTED`, `UNDER_REVIEW`, or `INTERVIEWING`, move to
        `AUTO_WITHDRAWN` with their `SCHEDULED` interviews moving to `CANCELLED` and
        each transition decrementing the posting's `active_application_count`, while
        applications at `OFFER_EXTENDED` survive. `CLEAR` removes the university from
        the list."
        PRD §3.7: "and the posting's `blocked_university_ids` must not contain the
        student's university, otherwise `ERR_POSTING_BLOCKED_FOR_UNIVERSITY` (HTTP 403)."

        Design: Corner/endpoints/posting_clearance_block_cascades_then_clear_restores
        """
        ctx = setup_base_marketplace()
        university_id = ctx["university"]["id"]
        posting_id = ctx["posting"]["id"]
        cc = make_career_center_admin_headers(university_id)

        application = apply_as_student(
            ctx["student"]["id"], posting_id,
            submitted_documents=[create_document("RESUME", "s3://docs/sam-resume.pdf")],
        )
        sally = create_student(
            university_id, email="sally@stateu.edu", full_name="Sally Kim",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
            profile_visibility="PUBLIC_TO_APPROVED_EMPLOYERS",
        )

        blocked = validate_success(
            api.clearance_job_posting(
                posting_id, {"university_id": university_id, "decision": "BLOCK"}, cc
            ),
            200,
        )
        assert university_id in blocked["blocked_university_ids"]

        cascaded = validate_success(api.get_application(application["id"], PA), 200)
        assert cascaded["status"] == "AUTO_WITHDRAWN"
        posting = validate_success(api.get_job_posting(posting_id, PA), 200)
        assert posting["active_application_count"] == 0

        response = api.create_application(
            {
                "student_id": sally["id"],
                "job_posting_id": posting_id,
                "submitted_documents": [
                    create_document("RESUME", "s3://docs/sally-resume.pdf")
                ],
            },
            make_student_headers(sally["id"]),
        )
        validate_error(response, ApiErrorId.ERR_POSTING_BLOCKED_FOR_UNIVERSITY, 403)

        cleared = validate_success(
            api.clearance_job_posting(
                posting_id, {"university_id": university_id, "decision": "CLEAR"}, cc
            ),
            200,
        )
        assert cleared["blocked_university_ids"] == []

        restored = apply_as_student(
            sally["id"], posting_id,
            submitted_documents=[create_document("RESUME", "s3://docs/sally-resume.pdf")],
        )
        assert restored["status"] == "SUBMITTED"


class TestPostingVersioning:
    def test_version_increments_on_every_transition(self, api):
        """PRD §2.4: "`version` (integer): starts at 1 at creation and increments by 1
        on every mutation of the resource"
        PRD §3.4: "Each accepted transition increments the posting's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/posting_version_increments_on_every_transition
        """
        set_clock()
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        posting = create_posting(employer["id"], title="SWE Intern")
        assert posting["version"] == 1
        recruiter = make_employer_recruiter_headers(employer["id"])

        v_sub = validate_success(
            api.transition_job_posting(posting["id"], {"to": "SUBMITTED"}, recruiter), 200
        )["version"]
        v_pub = validate_success(
            api.transition_job_posting(posting["id"], {"to": "PUBLISHED"}, PA), 200
        )["version"]
        v_pau = validate_success(
            api.transition_job_posting(posting["id"], {"to": "PAUSED"}, recruiter), 200
        )["version"]
        v_res = validate_success(
            api.transition_job_posting(posting["id"], {"to": "PUBLISHED"}, recruiter), 200
        )["version"]
        assert (v_sub, v_pub, v_pau, v_res) == (2, 3, 4, 5)
        read = validate_success(api.get_job_posting(posting["id"], PA), 200)
        assert read["version"] == 5
        assert read["status"] == "PUBLISHED"
