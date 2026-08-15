"""Security perimeter: authentication, role authorization, affiliation scoping."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    case_version,
    create_case,
    create_case_payload,
    dismiss_case_payload,
    hearing_payload,
    make_advisor_headers,
    make_appeal_officer_headers,
    make_cast,
    make_coordinator_headers,
    make_investigator_headers,
    make_party_headers,
    no_contact_directive_payload,
    validate_error,
    validate_paginated,
)
from test_helpers import api_client


class TestAuthentication:
    def test_unauthenticated_and_unknown_identity_rejected(self, api):
        """PRD 2.1: "A request whose role header is missing, malformed, or names
        no declared role — or whose `X-User-ID` is missing — is rejected with
        `ERR_UNAUTHENTICATED` (401)."
        PRD 2.1: "When `X-User-Role` is `TitleIXCoordinator`, `Investigator`,
        `DecisionMaker`, `AppealOfficer`, `Party`, or `Advisor`, `X-User-ID` is
        the `id` of the acting `PartyProfile`; ownership and identity checks on
        any resource that references a `PartyProfile` compare the resource's
        foreign-key field to `X-User-ID`, and an entity-backed `X-User-ID` that
        does not resolve to an existing `PartyProfile` is itself an
        `ERR_UNAUTHENTICATED` failure."

        Design: Corner/validations/unauthenticated_and_unknown_identity_rejected
        """
        # No headers at all.
        validate_error(api.list_cases(headers={}), ApiErrorId.ERR_UNAUTHENTICATED)
        # Entity-backed role with an X-User-ID naming no PartyProfile.
        validate_error(
            api.list_cases(headers=build_user_headers(NON_EXISTENT_UUID, "Party")),
            ApiErrorId.ERR_UNAUTHENTICATED,
        )


class TestRoleAuthorization:
    def test_party_role_cannot_create_case_forbidden(self, api):
        """PRD 2.1: "When the role is valid but not on the endpoint's declared
        roles list, the request is rejected with `ERR_FORBIDDEN_ROLE` (403)."
        PRD 4: POST /api/cases is declared for "TitleIXCoordinator,
        CaseAdministrator".

        Design: Corner/validations/party_role_cannot_create_case_forbidden
        """
        cast = make_cast("comp", "resp", "coord")
        resp = api.create_case(
            create_case_payload(
                cast["comp"]["id"], cast["resp"]["id"], cast["coord"]["id"],
            ),
            make_party_headers(cast["comp"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        _, meta = validate_paginated(
            api.list_cases(make_coordinator_headers(cast["coord"]["id"]))
        )
        assert meta["total_count"] == 0

    def test_party_cannot_terminate_measure_forbidden(self, api):
        """PRD 4: POST /api/supportive-measures/{id}/terminate is declared for
        "TitleIXCoordinator".
        PRD 2.1: "When the role is valid but not on the endpoint's declared roles
        list, the request is rejected with `ERR_FORBIDDEN_ROLE` (403)."
        PRD 2.11: "Every request is evaluated against the validation tiers in a
        fixed ascending priority order, and the first failing tier short-circuits
        the remainder." (Role authorization is tier 2, before existence.)

        Design: Corner/rbac/party_cannot_terminate_measure_forbidden
        """
        cast = make_cast("comp")
        resp = api.terminate_supportive_measure(
            NON_EXISTENT_UUID, make_party_headers(cast["comp"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_investigator_cannot_dismiss_case_forbidden(self, api):
        """PRD 4: POST /api/cases/{id}/dismiss is declared for
        "TitleIXCoordinator".
        PRD 2.1: "When the role is valid but not on the endpoint's declared roles
        list, the request is rejected with `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/investigator_cannot_dismiss_case_forbidden
        """
        cast = make_cast("inv")
        resp = api.dismiss_case(
            NON_EXISTENT_UUID,
            dismiss_case_payload(dismissal_reason="MANDATORY_NO_JURISDICTION"),
            make_investigator_headers(cast["inv"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_advisor_cannot_rule_questions_forbidden(self, api):
        """PRD 4: POST /api/cross-exam-questions/{id}/rule is declared for
        "DecisionMaker" — advisors ask; only the decision-maker rules.
        PRD 2.1: "When the role is valid but not on the endpoint's declared roles
        list, the request is rejected with `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/advisor_cannot_rule_questions_forbidden
        """
        cast = make_cast("advc")
        resp = api.rule_cross_exam_question(
            NON_EXISTENT_UUID, {"ruling": "ALLOWED"},
            make_advisor_headers(cast["advc"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_party_cannot_issue_directive_forbidden(self, api):
        """PRD 4: POST /api/cases/{id}/no-contact-directives is declared for
        "TitleIXCoordinator".
        PRD 2.11: "Every request is evaluated against the validation tiers in a
        fixed ascending priority order, and the first failing tier short-circuits
        the remainder." (Role authorization is tier 2, before existence, state,
        and the OCC check.)

        Design: Corner/rbac/party_cannot_issue_directive_forbidden
        """
        cast = make_cast("comp", "resp", "coord")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        version = case_version(case["id"], cast["coord"]["id"])
        resp = api.create_no_contact_directive(
            case["id"],
            no_contact_directive_payload(
                version, party_side="RESPONDENT", restrictions=["IN_PERSON"],
            ),
            make_party_headers(cast["comp"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_appeal_officer_cannot_schedule_hearing_forbidden(self, api):
        """PRD 4: POST /api/cases/{id}/hearings is declared for
        "TitleIXCoordinator".
        PRD 2.1: "When the role is valid but not on the endpoint's declared roles
        list, the request is rejected with `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/appeal_officer_cannot_schedule_hearing_forbidden
        """
        cast = make_cast("ao")
        resp = api.schedule_hearing(
            NON_EXISTENT_UUID,
            hearing_payload(cast["ao"]["id"]),
            make_appeal_officer_headers(cast["ao"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestAffiliationScoping:
    def test_party_read_unaffiliated_case_denied(self, api):
        """PRD 2.6: "A `Party` reader may read only cases where the actor's
        identity equals the case's `complainant_id` or `respondent_id`, together
        with the descendants of such cases; an `Advisor` reader may read only
        cases where the actor holds an advisor appointment of any status. An
        unaffiliated read is rejected with `ERR_CASE_ACCESS_DENIED` (403) and is
        deliberately indistinguishable from ordinary authorization failure".

        Design: Corner/validations/party_read_unaffiliated_case_denied
        """
        cast = make_cast("comp", "resp", "coord", "out_student")
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        resp = api.get_case(case["id"], make_party_headers(cast["out_student"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CASE_ACCESS_DENIED)
