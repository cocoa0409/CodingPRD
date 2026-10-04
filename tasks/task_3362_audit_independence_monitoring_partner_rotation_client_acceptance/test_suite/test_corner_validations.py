"""Breadth claims about the authentication and authorization checks."""

import pytest

from test_helpers import (
    ApiErrorId,
    COMMITTEE_HEADERS,
    LIAISON_HEADERS,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN_HEADERS,
    acceptance_payload,
    assert_same_instant,
    client_payload,
    fixtures,
    get_assignment_data,
    get_engagement_data,
    get_professional_data,
    headers_without_auth,
    headers_without_user_id,
    make_engagement_partner_headers,
    validate_error,
    validate_success,
)


class TestAuthenticationHeaders:
    """Header presence is checked before anything else about the request."""

    def test_missing_auth_headers_are_reported_before_existence(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        `ERR_MISSING_AUTH_HEADERS` and HTTP status 401 before any other
        processing occurs."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        fixtures.set_clock(api)
        response = api.get_client(NON_EXISTENT_UUID, headers_without_auth())
        validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401)

    def test_role_without_user_id_is_rejected_the_same_way(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        fixtures.set_clock(api)
        response = api.get_client(NON_EXISTENT_UUID, headers_without_user_id("PlatformAdmin"))
        validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401)


class TestRoleAuthorization:
    """A syntactically valid role outside the endpoint's list is refused."""

    def test_a_valid_role_outside_the_endpoint_list_is_rejected(self, api):
        """PRD §2.1: "When both headers are present but the value of
        `X-User-Role` is not among the roles authorized for the targeted
        operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE` and HTTP
        status 403."

        Design: Corner/validations/unauthorized_role_returns_unauthorized_role
        """
        fixtures.set_clock(api)
        affiliate = fixtures.seed_affiliate(api)
        acting = fixtures.seed_professional(api, affiliate["id"], rotation_role_class="NONE")
        ep_headers = make_engagement_partner_headers(acting["id"])
        client = fixtures.seed_client(api, legal_name="Marlow Freight")
        engagement = fixtures.open_engagement(api, client["id"], ep_headers)

        # The liaison does not own acceptance decisions.
        refused_acceptance = api.create_acceptance(
            acceptance_payload(client["id"], engagement["id"]),
            LIAISON_HEADERS,
        )
        validate_error(refused_acceptance, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        # The engagement partner does not own reference data.
        refused_client = api.create_client(
            client_payload(legal_name="Marlow Holdings"), ep_headers
        )
        validate_error(refused_client, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_the_authorized_roles_still_succeed(self, api):
        """PRD §2.12: "Acceptance decisions belong exclusively to the
        `ClientAcceptanceCommittee`" and "Reference data and the logical clock
        are the `PlatformAdmin`'s exclusive domain."

        Design: Corner/validations/unauthorized_role_returns_unauthorized_role
        """
        fixtures.set_clock(api)
        world = fixtures.seed_reference_data(api, legal_name="Marlow Freight")

        acceptance = fixtures.open_acceptance(
            api, world["client"]["id"], world["engagement"]["id"]
        )
        assert acceptance["status"] == "DRAFT"

        created = validate_success(
            api.create_client(client_payload(legal_name="Marlow Holdings"), PLATFORM_ADMIN_HEADERS),
            201,
        )
        assert created["status"] == "PROSPECT"


class TestCleanAssignment:
    """The negative control for the whole staffing gate stack."""

    def test_a_clean_assignment_passes_every_gate_and_returns_201(self, api):
        """PRD §3.3: "The new assignment starts in `ACTIVE` status with
        `ended_on` null".
        PRD §3.3: "This step-1 value is what the assignment stores in its own
        `workload_points`".

        Design: Corner/validations/clean_assignment_satisfies_every_gate_and_returns_201
        """
        world = fixtures.scenario_assignment_gates(api)
        engagement_id = world["engagement"]["id"]
        professional_id = world["professional"]["id"]
        version_before = world["engagement"]["version"]

        response = fixtures.staff(
            api, engagement_id, professional_id, "LEAD_PARTNER",
            "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        assignment = validate_success(response, 201)

        assert assignment["status"] == "ACTIVE"
        assert assignment["rotation_status"] == "ON_SERVICE"
        assert assignment["consecutive_service_months"] == 0
        assert assignment["workload_points"] == 40
        assert_same_instant(assignment["started_on"], "2026-10-01T00:00:00Z")

        professional = get_professional_data(api, professional_id)
        engagement = get_engagement_data(api, engagement_id)
        assert professional["active_workload_points"] == 40
        assert engagement["lead_partner_id"] == professional_id
        assert engagement["assigned_workload_points"] == 40
        assert engagement["version"] == version_before + 1

        stored = get_assignment_data(api, assignment["id"])
        assert stored["ended_on"] is None
