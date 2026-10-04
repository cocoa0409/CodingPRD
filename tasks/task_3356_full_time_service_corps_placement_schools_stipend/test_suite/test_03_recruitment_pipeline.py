"""Recruitment, eligibility, and enrollment: hard gates at creation, the
ordered pipeline, and the member-creating ENROLLED transition."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    make_applicant_headers,
)


class TestApplicationCreation:
    def test_application_create_initial_state_and_envelope(self, api):
        """PRD §3.3: "A submission passing all three lands in `SUBMITTED`
        status, with `rejection_reason` null — it is only ever set when the
        application lands in `REJECTED`, `WITHDRAWN`, or `DECLINED`."
        PRD §3.3: "The application's `enrolled_member_id`, null until this
        moment, is set to the new member's `id`, closing the loop between the
        two records."

        Design: Corner/entities/application_create_initial_state_and_envelope"""
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        resp = api.create_application(
            factories.application_payload(
                site["id"],
                full_name="Sam Ortega",
                date_of_birth="2002-01-15",
                education_level="ASSOCIATES",
                citizenship_status="US_NATIONAL",
                prior_service_terms=1,
                prior_full_awards_received=0,
            ),
            make_applicant_headers("app-sam"),
        )
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        application = body["data"]
        assert application["status"] == "SUBMITTED"
        assert application["version"] == 1
        assert application["rejection_reason"] is None
        assert application["enrolled_member_id"] is None


class TestEligibilityGates:
    def test_application_age_boundaries_17_and_25_ok(self, api):
        """PRD §3.3: "the applicant's age at the site's `service_year_start`
        must be at least 17 and at most 25 — computed from `date_of_birth`,
        with a birthday falling exactly on `service_year_start` counting as
        having reached that age".

        Design: Corner/validations/application_age_boundaries_17_and_25_ok
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)

        # Exactly 17 on 2026-09-01: the lower bound is inclusive.
        young = fixtures.submit_application(
            api, site["id"], "app-young", full_name="Young Min", date_of_birth="2009-09-01",
            education_level="HS_DIPLOMA",
        )
        assert young["status"] == "SUBMITTED"

        # Exactly 25 on 2026-09-01: the upper bound is inclusive.
        old = fixtures.submit_application(
            api, site["id"], "app-old", full_name="Old Max", date_of_birth="2001-09-01",
            education_level="HS_DIPLOMA",
        )
        assert old["status"] == "SUBMITTED"

    def test_application_age_16_rejected(self, api):
        """PRD §3.3: "Age is evaluated first: the applicant's age at the site's
        `service_year_start` must be at least 17 and at most 25 — computed
        from `date_of_birth`, with a birthday falling exactly on
        `service_year_start` counting as having reached that age — otherwise
        the submission is rejected with `ERR_AGE_INELIGIBLE`."

        Design: Corner/validations/application_age_16_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        # Born one day after the boundary birthday: 16 at the year start.
        resp = api.create_application(
            factories.application_payload(site["id"], full_name="Too Young", date_of_birth="2009-09-02",
                                          education_level="HS_DIPLOMA"),
            make_applicant_headers("app-younger"),
        )
        validate_error(resp, ApiErrorId.ERR_AGE_INELIGIBLE.value)

    def test_application_age_26_rejected(self, api):
        """PRD §3.3: "Age is evaluated first: the applicant's age at the site's
        `service_year_start` must be at least 17 and at most 25 — computed
        from `date_of_birth`, with a birthday falling exactly on
        `service_year_start` counting as having reached that age — otherwise
        the submission is rejected with `ERR_AGE_INELIGIBLE`."

        Design: Corner/validations/application_age_26_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        # Turned 26 the day before the year start.
        resp = api.create_application(
            factories.application_payload(site["id"], full_name="Too Old", date_of_birth="2000-08-31"),
            make_applicant_headers("app-older"),
        )
        validate_error(resp, ApiErrorId.ERR_AGE_INELIGIBLE.value)

    def test_application_education_rejected(self, api):
        """PRD §3.3: "an `education_level` of `LESS_THAN_HS` is ineligible and
        rejected with `ERR_EDUCATION_INELIGIBLE`, while `HS_DIPLOMA`, `GED`,
        `SOME_COLLEGE`, `ASSOCIATES`, and `BACHELORS_PLUS` are eligible."

        Design: Corner/validations/application_education_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        resp = api.create_application(
            factories.application_payload(site["id"], full_name="No Diploma", education_level="LESS_THAN_HS"),
            make_applicant_headers("app-nodip"),
        )
        validate_error(resp, ApiErrorId.ERR_EDUCATION_INELIGIBLE.value)

    def test_application_service_ineligible_variants(self, api):
        """PRD §3.3: "a `citizenship_status` of `OTHER` is ineligible
        (`US_CITIZEN`, `US_NATIONAL`, and `PERMANENT_RESIDENT` are eligible),
        `prior_service_terms` must be fewer than 4, and
        `prior_full_awards_received` must be fewer than 2; any failure is
        rejected with `ERR_SERVICE_INELIGIBLE`."

        Design: Corner/validations/application_service_ineligible_variants
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)

        citizenship = api.create_application(
            factories.application_payload(site["id"], full_name="Other Citizen", citizenship_status="OTHER"),
            make_applicant_headers("app-oc"),
        )
        validate_error(citizenship, ApiErrorId.ERR_SERVICE_INELIGIBLE.value)

        terms = api.create_application(
            factories.application_payload(site["id"], full_name="Four Terms", prior_service_terms=4),
            make_applicant_headers("app-4t"),
        )
        validate_error(terms, ApiErrorId.ERR_SERVICE_INELIGIBLE.value)

        awards = api.create_application(
            factories.application_payload(
                site["id"], full_name="Two Awards", prior_service_terms=2, prior_full_awards_received=2
            ),
            make_applicant_headers("app-2a"),
        )
        validate_error(awards, ApiErrorId.ERR_SERVICE_INELIGIBLE.value)


class TestPipelineOrder:
    def test_application_submitted_to_offered_rejected(self, api):
        """PRD §3.3: "From `SCREENED_ELIGIBLE`, a `ProgramManager` moves the
        candidate to `INTERVIEWED`, and from `INTERVIEWED` either to `OFFERED`
        or — again recording `BACKGROUND_CHECK_FAILED` — to `REJECTED`."

        Design: Corner/state_machines/application_submitted_to_offered_rejected
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        application = fixtures.submit_application(api, site["id"])

        # The screening and interview branches must be traversed first.
        blocked = api.transition_application(
            application["id"], {"to_status": "OFFERED"}, PROGRAM_MANAGER_HEADERS
        )
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value)

        after, _meta = validate_paginated(api.list_site_applications(site["id"], PROGRAM_MANAGER_HEADERS))
        mine = [a for a in after if a["id"] == application["id"]]
        assert mine and mine[0]["status"] == "SUBMITTED"

    def test_enroll_creates_member_side_effect(self, api):
        """PRD §3.3: "At that moment the system creates the CorpsMember:
        `site_id` and `full_name` are copied from the application,
        `service_status` begins at `ENROLLED`, `stipend_status` at
        `NOT_STARTED`, `award_status` at `NOT_EARNED`, and every computed
        counter starts at zero."

        Design: Corner/state_machines/enroll_creates_member_side_effect
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        application = fixtures.submit_application(api, site["id"])
        fixtures.advance_application(api, application["id"], "SCREEN", PROGRAM_MANAGER_HEADERS)
        fixtures.advance_application(api, application["id"], "INTERVIEWED", PROGRAM_MANAGER_HEADERS)
        fixtures.advance_application(api, application["id"], "OFFERED", PROGRAM_MANAGER_HEADERS)
        fixtures.advance_application(
            api, application["id"], "ACCEPTED", make_applicant_headers("app-jordan")
        )

        enrolled = validate_success(
            api.transition_application(application["id"], {"to_status": "ENROLLED"}, PROGRAM_MANAGER_HEADERS)
        )
        assert enrolled["status"] == "ENROLLED"
        new_member_id = enrolled["enrolled_member_id"]
        assert new_member_id

        members, meta = validate_paginated(api.list_site_members(site["id"], PROGRAM_MANAGER_HEADERS))
        assert meta["total_count"] == 1
        member = members[0]
        assert member["id"] == new_member_id
        assert member["service_status"] == "ENROLLED"
        assert member["stipend_status"] == "NOT_STARTED"
        assert member["award_status"] == "NOT_EARNED"

    def test_member_activation_cascades_stipend_active(self, api):
        """PRD §3.7: "Activation — `ENROLLED` to `ACTIVE` — requires the site
        to be `ACTIVE` (else `ERR_INVALID_STATE`) and cascades inside the
        member record: `stipend_status` moves from `NOT_STARTED` to `ACTIVE`,
        and the site's `projected_obligations_cents` and `funding_posture` are
        recomputed."

        Design: Corner/state_machines/member_activation_cascades_stipend_active
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.enroll_member(api, site["id"])

        resp = api.transition_member(
            member["id"], {"to_status": "ACTIVE", "dimension": "SERVICE"}, PROGRAM_MANAGER_HEADERS
        )
        activated = validate_success(resp)
        # A single request moves both dimensions.
        assert activated["service_status"] == "ACTIVE"
        assert activated["stipend_status"] == "ACTIVE"
