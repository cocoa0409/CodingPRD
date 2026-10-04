"""Corner queue — state_machines (Voucher/ChangeOrder/Authorization):
APPROVED-voucher and FEDERAL_REJECTED-change-order terminal lockdown, and the
FULLY_DRAWN -> OBLIGATED reverse auto-transition on change-order approval
(PRD §3.7, §3.8, §3.5)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    concur_change_order,
    create_approved_voucher,
    create_change_order,
    create_draft_voucher,
    create_line_item,
    decide_voucher,
    federal_decide_change_order,
    get_success_data,
    setup_fully_drawn_authorization,
    setup_project_under_construction,
    submit_voucher,
    validate_error,
    validate_paginated,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestVoucherChangeOrderAuthorizationMachines:
    def test_voucher_submit_on_approved_returns_invalid_state(self, api):
        """PRD §3.7: "Submission moves a `DRAFT` voucher to `UNDER_REVIEW`; the
        same action also resubmits a `REJECTED` voucher".
        PRD §3.7: "`REJECTED` is not terminal for a voucher; `APPROVED` is."
        PRD §2.7: "6. State gate: the target resource must be in a valid
        from-state for the requested action, else `ERR_INVALID_STATE` (409)."

        Submit is defined from DRAFT and REJECTED only; an APPROVED voucher is
        terminal, so the resubmission attempt is a wrong-state call.

        Design: Corner/state_machines/voucher_submit_on_approved_returns_invalid_state
        """
        ctx = setup_project_under_construction(
            project_cost_cents=100_000,
            apportioned_cents=1_000_000,
            initial_obligated_cents=80_000,
            agreement_number="FA-VS",
        )
        voucher = create_approved_voucher(
            ctx["authorization"]["id"],
            line_items=[create_line_item("w", 10_000)],
        )
        assert voucher["status"] == "APPROVED"
        assert voucher["resubmission_count"] == 0

        resp = api.submit_voucher(voucher["id"], H["state_dot_engineer"])
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

        rows, _meta = validate_paginated(
            api.list_authorization_vouchers(
                ctx["authorization"]["id"], H["fhwa_reviewer"]
            )
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "APPROVED"
        assert rows[0]["resubmission_count"] == 0

    def test_change_order_federal_decide_twice_returns_invalid_state(self, api):
        """PRD §3.8: "A `decision` of `REJECT` moves the ChangeOrder to the
        terminal `FEDERAL_REJECTED` status and posts nothing."
        PRD §2.7: "6. State gate: the target resource must be in a valid
        from-state for the requested action, else `ERR_INVALID_STATE` (409)."

        The federal decision is defined from STATE_CONCURRED; a second
        decision on the terminal FEDERAL_REJECTED order is a wrong-state call
        and posts no participation.

        Design: Corner/state_machines/change_order_federal_decide_twice_returns_invalid_state
        """
        ctx = setup_project_under_construction(
            project_cost_cents=100_000,
            apportioned_cents=1_000_000,
            initial_obligated_cents=80_000,
            agreement_number="FA-CT",
        )
        auth_id = ctx["authorization"]["id"]
        change_order = create_change_order(auth_id, 5_000, "CO")
        concur_change_order(change_order["id"])
        rejected = federal_decide_change_order(change_order["id"], "REJECT")
        assert rejected["status"] == "FEDERAL_REJECTED"

        resp = api.federal_decide_change_order(
            change_order["id"], {"decision": "APPROVE"}, H["fhwa_reviewer"]
        )
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

        rows, _meta = validate_paginated(
            api.list_authorization_change_orders(auth_id, H["fhwa_reviewer"])
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "FEDERAL_REJECTED"
        assert rows[0]["federal_participation_cents"] is None

    def test_fully_drawn_authorization_returns_to_obligated_on_change_order(self, api):
        """PRD §3.5: "A later change-order approval that raises
        `obligated_cents` above `reimbursed_cents` returns it from
        `FULLY_DRAWN` to `OBLIGATED`, reopening billing."
        PRD §3.8: "change-order creation accepts an authorization in either
        `OBLIGATED` or `FULLY_DRAWN` status, precisely so that a fully drawn
        agreement can be reopened".

        The 190-cent authorization is drawn to exactly zero remaining
        (FULLY_DRAWN); approving a 100,000-cent change order computes
        participation min(round(100,000 x 0.90), round(190 x 0.20)) =
        min(90,000, 38) = 38, raising the obligation to 228 > 190 and flipping
        the status back to OBLIGATED.

        Design: Corner/state_machines/fully_drawn_authorization_returns_to_obligated_on_change_order
        """
        ctx = setup_fully_drawn_authorization()
        authorization = ctx["authorization"]
        assert authorization["status"] == "FULLY_DRAWN"
        assert authorization["reimbursed_cents"] == 190
        assert authorization["obligated_cents"] == 190

        change_order = create_change_order(authorization["id"], 100_000, "Overrun")
        concur_change_order(change_order["id"])
        decided = federal_decide_change_order(change_order["id"], "APPROVE")
        assert decided["status"] == "FEDERAL_APPROVED"
        assert decided["federal_participation_cents"] == 38, (
            "cap round(190 x 0.20) = 38 is below the 90,000 eligible amount, "
            f"got {decided['federal_participation_cents']}"
        )

        reread = get_success_data(
            api.get_authorization(authorization["id"], H["fhwa_reviewer"])
        )
        assert reread["status"] == "OBLIGATED", (
            "the new headroom must return the authorization to OBLIGATED, got "
            f"{reread['status']}"
        )
        assert reread["obligated_cents"] == 228
        assert reread["reimbursed_cents"] == 190
