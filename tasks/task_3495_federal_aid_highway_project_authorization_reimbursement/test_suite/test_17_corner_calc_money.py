"""Corner queue — calculations (money): ineligible line strikes, the
fiscal-constraint equality boundary, the change-order draw against a short
cell, and the reimbursement clamped to the remaining obligation
(PRD §3.7, §3.2, §3.8)."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    api_client,
    concur_change_order,
    create_apportionment,
    create_change_order,
    create_draft_voucher,
    create_funding_program,
    create_line_item,
    create_project,
    create_stip,
    decide_stip,
    decide_voucher,
    get_success_data,
    set_clock,
    setup_project_under_construction,
    submit_stip,
    submit_voucher,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestMoneyCalculations:
    def test_voucher_ineligible_line_indexes_excluded_from_reimbursement(self, api):
        """PRD §3.7: "Approval accepts an optional `ineligible_line_indexes`
        array striking individual lines; each entry must be a valid 0-based
        index into `line_items`, else `ERR_INVALID_REQUEST`."
        PRD §3.7: "The approved lines are `line_items` with the struck indexes
        removed; the voucher's `eligible_amount_cents` becomes the sum of the
        approved lines' `eligible_amount_cents`."

        Striking index 1 removes its 50,000 from the 150,000 claim: eligible
        is 100,000 and, at the pinned 0.80 share, reimbursable is 80,000.

        Design: Corner/calculations/voucher_ineligible_line_indexes_excluded_from_reimbursement
        """
        ctx = setup_project_under_construction(
            project_cost_cents=250_000,
            apportioned_cents=1_000_000,
            initial_obligated_cents=200_000,
            agreement_number="FA-IL",
        )
        auth_id = ctx["authorization"]["id"]
        voucher = create_draft_voucher(
            auth_id,
            line_items=[
                create_line_item("eligible work", 100_000),
                create_line_item("disallowed catering", 50_000),
            ],
        )
        submit_voucher(voucher["id"])
        decided = decide_voucher(voucher["id"], "APPROVE", [1])
        assert decided["status"] == "APPROVED"
        assert decided["eligible_amount_cents"] == 100_000
        assert decided["federal_reimbursable_cents"] == 80_000, (
            "0.80 x 100,000 = 80,000 after striking line 1, got "
            f"{decided['federal_reimbursable_cents']}"
        )
        assert decided["ineligible_line_indexes"] == [1]

        authorization = get_success_data(
            api.get_authorization(auth_id, H["fhwa_reviewer"])
        )
        assert authorization["reimbursed_cents"] == 80_000

    def test_fiscal_constraint_equality_passes(self, api):
        """PRD §3.2: "Programmed must not exceed capacity, with equality
        passing; if any single program fails, the whole approval is rejected
        with `ERR_FISCAL_CONSTRAINT_VIOLATED` (422)."
        PRD §3.2: "the sum, over every Apportionment row for that program and
        this STIP's `state_code` whose fiscal year falls within the STIP's
        four-year span (missing cells contribute 0), of `apportioned_cents`
        minus `obligated_cents`."

        The lone FFY-2027 cell (800,000) is the whole four-year capacity
        (2028-2030 cells contribute 0); the project's provisional estimate is
        round(1,000,000 x 0.80) = 800,000 — exact equality passes.

        Design: Corner/calculations/fiscal_constraint_equality_passes
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        create_apportionment(
            program["id"], state_code="ID", federal_fiscal_year=2027,
            apportioned_cents=800_000,
        )
        stip = create_stip(state_code="ID", land_pct=0.0, start_ffy=2027)
        add_stip_comment(stip["id"])
        create_project(
            stip["id"], program["id"], route_name="US-95", description="P",
            activity_code="ROAD_RESURFACING", is_interstate_system=False,
            dbe_goal_pct=0.10, total_estimated_cost_cents=1_000_000,
        )
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])

        decided = decide_stip(stip["id"], "APPROVE")
        assert decided["status"] == "APPROVED", (
            "programmed 800,000 == capacity 800,000: equality passes, got "
            f"{decided['status']}"
        )
        assert decided["total_programmed_federal_cents"] == 800_000

    def test_change_order_draw_blocked_when_apportionment_short(self, api):
        """PRD §3.8: "The draw must then fit the apportionment cell: the cell's
        `available_cents` must cover the computed participation, with equality
        passing, else `ERR_APPORTIONMENT_EXCEEDED` (422)."

        The cap-clamped participation (min(480,000 eligible, 200,000 cap) =
        200,000) does not fit the cell's remaining 100,000, so the federal
        approval fails and the change order stays STATE_CONCURRED with no
        participation posted.

        Design: Corner/calculations/change_order_draw_blocked_when_apportionment_short
        """
        ctx = setup_project_under_construction(
            project_cost_cents=1_000_000,
            apportioned_cents=1_100_000,
            initial_obligated_cents=1_000_000,
            agreement_number="FA-CD",
        )
        auth_id = ctx["authorization"]["id"]

        change_order = create_change_order(auth_id, 600_000, "CO")
        concurred = concur_change_order(change_order["id"])
        assert concurred["status"] == "STATE_CONCURRED"

        resp = api.federal_decide_change_order(
            change_order["id"], {"decision": "APPROVE"}, H["fhwa_reviewer"]
        )
        error = validate_error(resp, ApiErrorId.ERR_APPORTIONMENT_EXCEEDED)
        assert resp.status_code == 422, (
            "participation 200,000 exceeds the remaining 100,000; got "
            f"{resp.status_code} ({error})"
        )

        rows, _meta = validate_paginated(
            api.list_authorization_change_orders(auth_id, H["fhwa_reviewer"])
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "STATE_CONCURRED"
        assert rows[0]["federal_participation_cents"] is None

        authorization = get_success_data(
            api.get_authorization(auth_id, H["fhwa_reviewer"])
        )
        assert authorization["obligated_cents"] == 1_000_000

    def test_final_voucher_reimbursement_clamped_to_remaining_obligation(self, api):
        """PRD §3.7: "Each approved line contributes its own federal share —
        the line's `eligible_amount_cents` multiplied by the Authorization's
        pinned `federal_share_pct`, rounded half-up to whole cents — and
        `federal_reimbursable_cents` is the lesser of that per-line sum and the
        Authorization's remaining obligation (`obligated_cents` minus
        `reimbursed_cents`), so a voucher can never overdraw the agreement."
        PRD §3.5: "When a voucher approval raises `reimbursed_cents` to exactly
        `obligated_cents`, the system moves the Authorization from `OBLIGATED`
        to `FULLY_DRAWN`".

        The second voucher computes 190 federal cents against only 100
        remaining, so it reimburses exactly 100 and flips the authorization to
        FULLY_DRAWN at 290 == 290.

        Design: Corner/calculations/final_voucher_reimbursement_clamped_to_remaining_obligation
        """
        ctx = setup_project_under_construction(
            program_code="HSIP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            activity_code="ROAD_RESURFACING",
            land_pct=0.02,
            project_cost_cents=400,
            apportioned_cents=100_000,
            initial_obligated_cents=290,
            agreement_number="FA-CL",
        )
        auth_id = ctx["authorization"]["id"]
        assert ctx["authorization"]["federal_share_pct"] == 0.90

        voucher1 = create_draft_voucher(
            auth_id,
            period_start_date="2027-01-01T00:00:00Z",
            period_end_date="2027-02-01T00:00:00Z",
            line_items=[create_line_item("a", 105), create_line_item("b", 105)],
        )
        submit_voucher(voucher1["id"])
        decided1 = decide_voucher(voucher1["id"], "APPROVE")
        assert decided1["federal_reimbursable_cents"] == 190

        voucher2 = create_draft_voucher(
            auth_id,
            period_start_date="2027-02-01T00:00:00Z",
            period_end_date="2027-03-01T00:00:00Z",
            line_items=[create_line_item("a2", 105), create_line_item("b2", 105)],
        )
        submit_voucher(voucher2["id"])
        decided2 = decide_voucher(voucher2["id"], "APPROVE")
        assert decided2["federal_reimbursable_cents"] == 100, (
            "min(190 computed, 290 - 190 remaining) = 100, got "
            f"{decided2['federal_reimbursable_cents']}"
        )

        authorization = get_success_data(
            api.get_authorization(auth_id, H["fhwa_reviewer"])
        )
        assert authorization["reimbursed_cents"] == 290
        assert authorization["status"] == "FULLY_DRAWN", (
            "reimbursed 290 == obligated 290 must flip the authorization to "
            f"FULLY_DRAWN, got {authorization['status']}"
        )
