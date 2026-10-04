"""Corner queue — validations (authentication/authorization) and rbac: the
401/403 gates and role exclusivity on voucher review (PRD §2.1, §4)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_funding_program,
    create_draft_voucher,
    create_line_item,
    set_clock,
    setup_project_under_construction,
    submit_voucher,
    validate_error,
    validate_paginated,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestAuthAndRbac:
    def test_clock_set_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does
        not name one of these five roles is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.7: "1. Authentication: a missing or unrecognized `X-User-Role`
        yields `ERR_UNAUTHENTICATED` (401)."

        The clock capability is called with no headers at all, so the
        authentication check fires before any role, existence, or payload
        logic.

        Design: Corner/validations/clock_set_missing_auth_header_returns_unauthenticated
        """
        resp = api.set_clock({"current_utc": "2026-09-02T00:00:00Z"}, None)
        error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401, f"expected 401, got {resp.status_code} ({error})"

    def test_state_dot_engineer_cannot_create_stip_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is authenticated but not in the
        target endpoint's authorized role list is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "The `StateDOTPlanner` builds the STIP, shepherds public
        involvement, and nominates and patches projects."

        STIP creation is exclusive to StateDOTPlanner; the engineering role is
        authenticated but not authorized.

        Design: Corner/validations/state_dot_engineer_cannot_create_stip_returns_forbidden
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_stip(
            {
                "state_code": "AZ",
                "state_federal_land_pct": 0.0,
                "start_federal_fiscal_year": 2027,
                "description": "Forbidden STIP",
            },
            H["state_dot_engineer"],
        )
        error = validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403, f"expected 403, got {resp.status_code} ({error})"

    def test_fhwa_reviewer_cannot_record_apportionment_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is authenticated but not in the
        target endpoint's authorized role list is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "The `FHWADivisionAdmin` records apportionments, decides STIP
        approvals, determines project eligibility, and authorizes projects."

        Both roles are federal, yet apportionment recording is exclusive to
        the division administrator.

        Design: Corner/validations/fhwa_reviewer_cannot_record_apportionment_returns_forbidden
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        resp = api.create_apportionment(
            {
                "funding_program_id": program["id"],
                "state_code": "AZ",
                "federal_fiscal_year": 2027,
                "apportioned_cents": 100,
            },
            H["fhwa_reviewer"],
        )
        error = validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403, f"expected 403, got {resp.status_code} ({error})"

    def test_state_dot_planner_cannot_decide_voucher_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is authenticated but not in the
        target endpoint's authorized role list is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.1: "The `FHWAReviewer` decides clearances, concurs on awards
        with DBE review, decides vouchers and change orders at the federal
        level, and conducts audits through closeout."
        PRD §3.7: "An `FHWAReviewer` decides an `UNDER_REVIEW` voucher with a
        `decision` of `APPROVE` or `REJECT`."

        The planner who nominated the project cannot approve its billings.

        Design: Corner/rbac/state_dot_planner_cannot_decide_voucher_returns_forbidden
        """
        ctx = setup_project_under_construction(
            project_cost_cents=100_000,
            apportioned_cents=1_000_000,
            initial_obligated_cents=80_000,
            agreement_number="FA-RB",
        )
        voucher = create_draft_voucher(
            ctx["authorization"]["id"],
            line_items=[create_line_item("w", 10_000)],
        )
        submit_voucher(voucher["id"])

        resp = api.decide_voucher(
            voucher["id"], {"decision": "APPROVE"}, H["state_dot_planner"]
        )
        error = validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403, f"expected 403, got {resp.status_code} ({error})"

        rows, _meta = validate_paginated(
            api.list_authorization_vouchers(
                ctx["authorization"]["id"], H["fhwa_reviewer"]
            )
        )
        assert len(rows) == 1 and rows[0]["status"] == "UNDER_REVIEW"
