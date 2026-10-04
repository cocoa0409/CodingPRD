"""Role-based access control: context headers, per-target role permission, and
entity-backed ownership."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_active_university,
    create_approved_employer,
    create_posting,
    create_student,
    make_career_center_admin_headers,
    make_employer_recruiter_headers,
    make_student_headers,
    register_employer,
    request_approval,
    set_clock,
    transition_posting,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PA


class TestUserContextHeaders:
    def test_request_missing_role_header_returns_user_context_error(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming their operational
        capacity. A request missing either header, or carrying a role the system does
        not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."
        PRD §2.9: "When a request would fail more than one check, the first failure in
        the following fixed order wins; later checks are not evaluated once an earlier
        one has failed:"

        Design: Corner/validations/request_missing_header_returns_user_context_error
        """
        set_clock()
        # X-User-Role withheld entirely; the target id would otherwise 404.
        headers = {"X-User-ID": "test-caller-1", "Content-Type": "application/json"}
        response = api.get_employer(NON_EXISTENT_UUID, headers)
        error = validate_error(
            response, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400
        )
        assert error["error_id"] != "ERR_EMPLOYER_NOT_FOUND"


class TestRolePermissionPerTarget:
    def test_student_cannot_publish_job_posting(self, api):
        """PRD §3.4: "From `SUBMITTED`, only a `PlatformAdmin` may move it to
        `PUBLISHED` — the platform publication gate"
        PRD §2.1: "A caller whose role is not permitted for the endpoint — or not
        permitted for the specific target it named, such as a `Student` sending `to` as
        `PUBLISHED` on a posting transition, or a `Student` writing `status` or outcome
        fields on the student self-update — is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/student_cannot_publish_job_posting
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        student = create_student(
            university["id"], email="sam@stateu.edu", full_name="Sam Lee",
            major="CS", graduation_year=2027, work_authorization="US_CITIZEN",
        )
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        posting = create_posting(employer["id"], title="SWE Intern")
        transition_posting(
            posting["id"], "SUBMITTED", make_employer_recruiter_headers(employer["id"])
        )
        response = api.transition_job_posting(
            posting["id"], {"to": "PUBLISHED"}, make_student_headers(student["id"])
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        read = validate_success(api.get_job_posting(posting["id"], PA), 200)
        assert read["status"] == "SUBMITTED"


class TestEntityBackedOwnership:
    def test_career_center_cannot_decide_other_university_approval(self, api):
        """PRD §3.3: "The decision belongs to the `CareerCenterAdmin` of the approval's
        university — the caller's university must equal the approval's `university_id`"
        PRD §2.1: "An entity-backed caller acting outside its owned scope is rejected
        with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/career_center_cannot_decide_other_university_approval
        """
        set_clock()
        university = create_active_university(
            name="State University", primary_domain="stateu.edu",
            employer_daily_message_cap=10,
        )
        tech = create_active_university(
            name="Tech Institute", primary_domain="tech.edu",
            employer_daily_message_cap=3,
        )
        employer = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        approval = request_approval(employer["id"], university["id"])
        response = api.decide_employer_approval(
            approval["id"],
            {"decision": "APPROVE", "expected_employer_version": employer["version"]},
            make_career_center_admin_headers(tech["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        read = validate_success(api.get_employer_approval(approval["id"], PA), 200)
        assert read["status"] == "PENDING"
        assert read["decided_at"] is None

    def test_recruiter_cannot_transition_other_employers_posting(self, api):
        """PRD §2.1: "When `X-User-Role` is `EmployerRecruiter`, `X-User-ID` is the
        `id` of the `Employer` being operated; ownership checks compare the target's
        `employer_id` (or the owning employer of a posting or an application) to
        `X-User-ID`."
        PRD §2.1: "An entity-backed caller acting outside its owned scope is rejected
        with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/recruiter_cannot_transition_other_employers_posting
        """
        set_clock()
        acme = create_approved_employer(
            company_name="Acme Corp", website_domain="acme.com",
            contact_email="hr@acme.com",
        )
        posting = create_posting(acme["id"], title="SWE Intern")
        globex = register_employer(
            company_name="Globex", website_domain="globex.com",
            contact_email="jobs@gmail.com",
        )
        response = api.transition_job_posting(
            posting["id"], {"to": "SUBMITTED"},
            make_employer_recruiter_headers(globex["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        read = validate_success(api.get_job_posting(posting["id"], PA), 200)
        assert read["status"] == "DRAFT"
