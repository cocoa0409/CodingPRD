"""Enterprise and Site lifecycle tests: creation, activation, pagination,
decommission terminality, and RBAC auth failures.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_enterprise,
    assert_site,
    create_enterprise_payload,
    create_enterprise_with_site,
    create_site_payload,
    create_survey_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

NA = TEST_USERS["network_architect_headers"]
RFE = TEST_USERS["rf_engineer_headers"]
SC = TEST_USERS["spectrum_coordinator_headers"]
FT = TEST_USERS["field_technician_headers"]


class TestEnterpriseCreation:
    def test_create_enterprise_returns_201_with_defaults(self):
        """PRD §3.1: "The new Enterprise enters `ONBOARDING` with
        `sla_credit_balance_cents` and `active_site_count` both starting at 0."
        PRD §3.1: "An optional `security_posture` may be supplied as `STANDARD`,
        `ELEVATED`, or `CRITICAL`; when omitted it defaults to `STANDARD`".

        Design: Corner/entities/enterprise_create_returns_201_and_server_minted_id
        """
        payload = create_enterprise_payload()
        payload.pop("security_posture", None)  # omit to exercise the default
        resp = api_client.create_enterprise(payload, NA)
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        data = validate_success(resp, expected_status=201)
        assert_enterprise(data)
        assert data["version"] == 1
        assert data["status"] == "ONBOARDING"
        assert data["security_posture"] == "STANDARD"
        assert data["sla_credit_balance_cents"] == 0
        assert data["active_site_count"] == 0

    def test_create_enterprise_explicit_posture_and_version_one(self):
        """PRD §3.1: "An optional `security_posture` may be supplied as
        `STANDARD`, `ELEVATED`, or `CRITICAL`".
        PRD §2.4: "a `version` field, an integer starting at 1 that increments
        by exactly 1 on every mutation of the resource."

        Design: Corner/entities/enterprise_create_returns_201_and_server_minted_id
        """
        resp = api_client.create_enterprise(
            create_enterprise_payload(security_posture="ELEVATED"), NA
        )
        data = validate_success(resp, expected_status=201)
        assert data["version"] == 1
        assert data["security_posture"] == "ELEVATED"
        assert data["status"] == "ONBOARDING"


class TestSiteReadAndPagination:
    def test_get_site_nonexistent_returns_404(self):
        """PRD §2.6: "A failure at any segment is rejected with `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/site_get_returns_404_for_nonexistent_id
        """
        resp = api_client.get_site(NON_EXISTENT_UUID, NA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_get_site_nonexistent_via_get_404_error_id(self):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.6: "A failure at any segment is rejected with `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/site_get_returns_404_for_nonexistent_id
        """
        resp = api_client.get_site(NON_EXISTENT_UUID, RFE)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] == "ERR_NOT_FOUND"

    def test_list_sites_pagination_envelope(self):
        """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1,
        and may not exceed 100. The `offset` parameter defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`,
        where `has_more` indicates whether additional results exist beyond the
        returned window."

        Design: Corner/entities/list_sites_pagination_envelope
        """
        resp = api_client.create_enterprise(create_enterprise_payload(), NA)
        ent = validate_success(resp, expected_status=201)
        for code in ("P1", "P2", "P3"):
            r = api_client.create_site(
                ent["id"], create_site_payload(site_code=code), NA
            )
            validate_success(r, expected_status=201)

        resp = api_client.list_enterprise_sites(ent["id"], NA, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2
        for s in data:
            assert_site(s)

    def test_list_sites_sorted_by_created_at_ascending(self):
        """PRD §2.3: "Results are always returned sorted by `created_at` in
        ascending order."

        Design: Corner/entities/list_sites_pagination_envelope
        """
        resp = api_client.create_enterprise(create_enterprise_payload(), NA)
        ent = validate_success(resp, expected_status=201)
        for code in ("Q1", "Q2", "Q3"):
            api_client.create_site(ent["id"], create_site_payload(site_code=code), NA)

        resp = api_client.list_enterprise_sites(ent["id"], NA, params={"limit": 10})
        data, _meta = validate_paginated(resp)
        assert len(data) == 3
        stamps = [s["created_at"] for s in data]
        assert stamps == sorted(stamps)


class TestSiteTerminalState:
    def test_decommissioned_site_rejects_activate_with_already_terminal(self):
        """PRD §2.9: "the same operation on an already-terminal resource is
        `ERR_ALREADY_TERMINAL`, and the terminal-state check is the one that
        surfaces when both could apply to a terminal resource."

        Design: Corner/state_machines/terminal_decommissioned_site_rejects_further_actions
        """
        ent, site = create_enterprise_with_site()
        resp = api_client.decommission_site(site["id"], NA)
        validate_success(resp)

        resp = api_client.activate_site(site["id"], NA)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_decommissioned_site_rejects_survey_creation_with_already_terminal(self):
        """PRD §2.9: "attempting to mutate a resource already in a terminal
        state — `DECOMMISSIONED`, `RETIRED`, `TERMINATED`, `RESOLVED`,
        `REGISTERED`, `REJECTED`, `WITHDRAWN`, `COMPLETED`, `FALSE_ALARM`,
        `OFFBOARDED`, `CANCELLED`, `EXPIRED`, and the like — yields
        `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/terminal_decommissioned_site_rejects_further_actions
        """
        ent, site = create_enterprise_with_site()
        api_client.decommission_site(site["id"], NA)

        resp = api_client.create_survey(site["id"], create_survey_payload(), FT)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestAuthenticationAndAuthorization:
    def test_missing_role_header_returns_401(self):
        """PRD §2.1: "A request missing either header, or carrying an
        unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_returns_401
        """
        # Headers carrying only X-User-ID and no X-User-Role.
        headers = {"X-User-ID": "someone"}
        resp = api_client.list_enterprises(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unrecognized_role_returns_401(self):
        """PRD §2.1: "A request missing either header, or carrying an
        unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_returns_401
        """
        headers = {"X-User-ID": "someone", "X-User-Role": "NotARealRole"}
        resp = api_client.list_enterprises(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_wrong_role_returns_403(self):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /private-wireless/enterprises is authorized for
        NetworkArchitect only.

        Design: Corner/validations/wrong_role_returns_403
        """
        resp = api_client.create_enterprise(create_enterprise_payload(), FT)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_regulator_cannot_create_enterprise(self):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`SpectrumRegulator` — the external regulator (an FCC/SAS
        administrator proxy); approves or rejects coordination requests and may
        read spectrum leases, contracts, and coordination requests."

        Design: Corner/validations/wrong_role_returns_403
        """
        resp = api_client.create_enterprise(
            create_enterprise_payload(), TEST_USERS["spectrum_regulator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
