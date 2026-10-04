"""Corner queue — validations (eligibility and voucher gates): activity
outside the program's eligible set, the isolated overlap check, final-voucher
uniqueness, and the two final-approval gates (PRD §3.3, §3.7)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_change_order,
    create_draft_voucher,
    create_line_item,
    decide_voucher,
    determine_project_eligible,
    get_success_data,
    setup_project_under_construction,
    setup_stip_pipeline,
    submit_voucher,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


def _construction_ctx(api, **overrides):
    kwargs = {
        "project_cost_cents": 100_000,
        "apportioned_cents": 1_000_000,
        "initial_obligated_cents": 80_000,
    }
    kwargs.update(overrides)
    return setup_project_under_construction(**kwargs)


class TestEligibilityAndVoucherGates:
    def test_determine_eligible_with_activity_outside_program_set_returns_error(self, api):
        """PRD §3.3: "A `determination` of `ELIGIBLE` additionally requires the
        `activity_code` to be a member of the funding program's
        `eligible_activity_codes`, else `ERR_INELIGIBLE_ACTIVITY` (422)".
        PRD §3.3: "A `determination` of `INELIGIBLE` moves the Project to the
        terminal `INELIGIBLE` status with no further checks."

        BRIDGE_REPLACEMENT is a recognized activity code but is absent from
        this program's eligible set; the ELIGIBLE determination fails while
        INELIGIBLE on the same project succeeds without that check.

        Design: Corner/validations/determine_eligible_with_activity_outside_program_set_returns_error
        """
        pipeline = setup_stip_pipeline(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            state_code="AZ",
            project_specs=[
                {
                    "route_name": "R1",
                    "description": "Bridge",
                    "activity_code": "BRIDGE_REPLACEMENT",
                    "total_estimated_cost_cents": 100_000,
                }
            ],
        )
        project = pipeline["projects"][0]

        resp = api.determine_eligibility(
            project["id"], {"determination": "ELIGIBLE"}, H["fhwa_division_admin"]
        )
        error = validate_error(resp, ApiErrorId.ERR_INELIGIBLE_ACTIVITY)
        assert resp.status_code == 422, f"expected 422, got {resp.status_code} ({error})"

        ineligible = api.determine_eligibility(
            project["id"], {"determination": "INELIGIBLE"}, H["fhwa_division_admin"]
        )
        assert validate_success(ineligible)["status"] == "INELIGIBLE"

    def test_submit_voucher_docs_true_exposes_overlap_error(self, api):
        """PRD §3.7: "the half-open period must not intersect the period of any
        non-`REJECTED` sibling voucher on the same authorization, else
        `ERR_BILLING_PERIOD_OVERLAP` (409) — adjacency is allowed, so one
        voucher's period ending exactly where the next begins is not an
        overlap."
        PRD §2.7: "13. Voucher documentation certification, else
        `ERR_DOCUMENTATION_INCOMPLETE` (422)."
        PRD §2.7: "19. Billing period overlap, else `ERR_BILLING_PERIOD_OVERLAP`
        (409)."

        With documentation_complete true the priority-13 check passes, so the
        period intersection with sibling voucher A is the failure that
        surfaces.

        Design: Corner/validations/submit_voucher_docs_true_exposes_overlap_error
        """
        ctx = _construction_ctx(api, agreement_number="FA-OV")
        auth_id = ctx["authorization"]["id"]

        voucher_a = create_draft_voucher(
            auth_id,
            period_start_date="2027-01-01T00:00:00Z",
            period_end_date="2027-02-01T00:00:00Z",
            line_items=[create_line_item("A", 10_000)],
        )
        submit_voucher(voucher_a["id"])
        voucher_b = create_draft_voucher(
            auth_id,
            period_start_date="2027-01-15T00:00:00Z",
            period_end_date="2027-02-15T00:00:00Z",
            line_items=[create_line_item("B", 10_000)],
            documentation_complete=True,
        )

        resp = api.submit_voucher(voucher_b["id"], H["state_dot_engineer"])
        error = validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

        rows, _meta = validate_paginated(
            api.list_authorization_vouchers(auth_id, H["fhwa_reviewer"])
        )
        by_id = {v["id"]: v for v in rows}
        assert by_id[voucher_b["id"]]["status"] == "DRAFT"
        assert by_id[voucher_a["id"]]["status"] == "UNDER_REVIEW"

    def test_second_final_voucher_rejected(self, api):
        """PRD §3.7: "At most one non-`REJECTED` final voucher may exist per
        authorization: creating a second with `is_final` true is rejected with
        `ERR_FINAL_VOUCHER_EXISTS` (409)."

        Design: Corner/validations/second_final_voucher_rejected
        """
        ctx = _construction_ctx(api, agreement_number="FA-FV")
        auth_id = ctx["authorization"]["id"]
        create_draft_voucher(
            auth_id,
            period_start_date="2027-01-01T00:00:00Z",
            period_end_date="2027-04-01T00:00:00Z",
            line_items=[create_line_item("all", 50_000)],
            is_final=True,
        )

        resp = api.create_voucher(
            {
                "authorization_id": auth_id,
                "period_start_date": "2027-04-01T00:00:00Z",
                "period_end_date": "2027-05-01T00:00:00Z",
                "line_items": [create_line_item("more", 10_000)],
                "documentation_complete": True,
                "is_final": True,
            },
            H["state_dot_engineer"],
        )
        error = validate_error(resp, ApiErrorId.ERR_FINAL_VOUCHER_EXISTS)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

        rows, meta = validate_paginated(
            api.list_authorization_vouchers(auth_id, H["fhwa_reviewer"])
        )
        assert len(rows) == 1 and meta["total_count"] == 1

    def test_final_voucher_approval_blocked_by_open_change_order(self, api):
        """PRD §3.7: "Two extra gates guard approval of a voucher whose
        `is_final` is true: the Project's right-of-way clearance must be
        `CLEARED` with `row_cert_level` equal to `LEVEL_1_FULL` — a final
        voucher under a `LEVEL_2_CONDITIONAL` certification is rejected with
        `ERR_ROW_NOT_CERTIFIED` (409) — and no ChangeOrder of the same
        authorization may sit in `REQUESTED` or `STATE_CONCURRED`, else
        `ERR_OPEN_CHANGE_ORDERS` (409)".

        A REQUESTED (never concurred) change order blocks the final approval;
        the voucher stays UNDER_REVIEW and the project stays
        UNDER_CONSTRUCTION.

        Design: Corner/validations/final_voucher_approval_blocked_by_open_change_order
        """
        ctx = _construction_ctx(api, agreement_number="FA-OC")
        auth_id = ctx["authorization"]["id"]
        change_order = create_change_order(auth_id, 5_000, "Pending CO")
        assert change_order["status"] == "REQUESTED"

        voucher = create_draft_voucher(
            auth_id,
            period_start_date="2027-01-01T00:00:00Z",
            period_end_date="2027-04-01T00:00:00Z",
            line_items=[create_line_item("all", 50_000)],
            is_final=True,
        )
        submit_voucher(voucher["id"])

        resp = api.decide_voucher(voucher["id"], {"decision": "APPROVE"}, H["fhwa_reviewer"])
        error = validate_error(resp, ApiErrorId.ERR_OPEN_CHANGE_ORDERS)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

        rows, _meta = validate_paginated(
            api.list_authorization_vouchers(auth_id, H["fhwa_reviewer"])
        )
        assert rows[0]["status"] == "UNDER_REVIEW"
        project = get_success_data(api.get_project(ctx["project"]["id"], H["fhwa_reviewer"]))
        assert project["status"] == "UNDER_CONSTRUCTION"

    def test_final_voucher_approval_requires_row_level_one(self, api):
        """PRD §3.7: "Two extra gates guard approval of a voucher whose
        `is_final` is true: the Project's right-of-way clearance must be
        `CLEARED` with `row_cert_level` equal to `LEVEL_1_FULL` — a final
        voucher under a `LEVEL_2_CONDITIONAL` certification is rejected with
        `ERR_ROW_NOT_CERTIFIED` (409) — and no ChangeOrder of the same
        authorization may sit in `REQUESTED` or `STATE_CONCURRED`, else
        `ERR_OPEN_CHANGE_ORDERS` (409)".
        PRD §3.4: "For right-of-way clearances, `CLEARED` means certified; the
        `row_cert_level` recorded at that point later decides whether a final
        voucher may be approved (§3.7)."

        LEVEL_2_CONDITIONAL is enough to authorize construction and to approve
        a non-final voucher, but not the final voucher.

        Design: Corner/validations/final_voucher_approval_requires_row_level_one
        """
        ctx = _construction_ctx(api, row_cert_level="LEVEL_2_CONDITIONAL",
                                agreement_number="FA-R2")
        auth_id = ctx["authorization"]["id"]

        progress = create_draft_voucher(
            auth_id,
            period_start_date="2027-01-01T00:00:00Z",
            period_end_date="2027-02-01T00:00:00Z",
            line_items=[create_line_item("progress", 10_000)],
        )
        submit_voucher(progress["id"])
        approved = decide_voucher(progress["id"], "APPROVE")
        assert approved["status"] == "APPROVED", (
            "a NON-final voucher approves fine under LEVEL_2_CONDITIONAL"
        )

        final_voucher = create_draft_voucher(
            auth_id,
            period_start_date="2027-02-01T00:00:00Z",
            period_end_date="2027-05-01T00:00:00Z",
            line_items=[create_line_item("final", 40_000)],
            is_final=True,
        )
        submit_voucher(final_voucher["id"])

        resp = api.decide_voucher(
            final_voucher["id"], {"decision": "APPROVE"}, H["fhwa_reviewer"]
        )
        error = validate_error(resp, ApiErrorId.ERR_ROW_NOT_CERTIFIED)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

        project = get_success_data(api.get_project(ctx["project"]["id"], H["fhwa_reviewer"]))
        assert project["status"] == "UNDER_CONSTRUCTION"
