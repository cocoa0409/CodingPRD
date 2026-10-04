"""Difficulty queue — non_linear_state_machine: the STIP amendment loop
(APPROVED -> PUBLIC_INVOLVEMENT -> SUBMITTED -> APPROVED) and the voucher
reject/resubmit cycle on a single row (PRD §3.2, §3.7)."""
from test_helpers import (
    TEST_USERS,
    add_stip_comment,
    api_client,
    create_draft_voucher,
    create_line_item,
    create_stip,
    decide_stip,
    decide_voucher,
    get_success_data,
    set_clock,
    setup_project_under_construction,
    submit_stip,
    submit_voucher,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestNonLinearStateMachine:
    def test_stip_amendment_cycle_requires_fresh_comment_window(self, api):
        """PRD §3.2: "Either path sets the status back to `PUBLIC_INVOLVEMENT`,
        restamps `comment_period_opened_at` from the current logical clock so a
        fresh comment window opens, and increments `amendment_count` by 1."
        PRD §3.2: "And the logical clock must have reached at least 30 days
        after the window opened — a submission at exactly 30 days elapsed
        passes — else `ERR_COMMENT_PERIOD_OPEN` (409)."
        PRD §3.2: "The public record must contain at least 1 comment whose
        `created_at` is on or after `comment_period_opened_at`, else
        `ERR_PUBLIC_INVOLVEMENT_INCOMPLETE` (422)."

        The amendment loop resets the window: with a fresh comment recorded in
        the reopened window (so the participation check is satisfied), an
        immediate resubmission 31 days into the ORIGINAL window still fails —
        the reopened window is 0 days old. After 31 fresh days the resubmission
        succeeds and the loop closes back to APPROVED.

        Design: Difficulty/non_linear_state_machine/stip_amendment_cycle_requires_fresh_comment_window
        """
        set_clock("2026-09-01T00:00:00Z")
        stip = create_stip(
            state_code="CA", land_pct=0.0, start_ffy=2027,
            description="Amendment cycle STIP",
        )
        add_stip_comment(stip["id"], comment_text="First window comment.")
        set_clock("2026-10-02T00:00:00Z")
        submit_stip(stip["id"])
        approved = decide_stip(stip["id"], "APPROVE")
        assert approved["status"] == "APPROVED"
        assert approved["amendment_count"] == 0

        reopened = get_success_data(api.open_stip_amendment(stip["id"], H["state_dot_planner"]))
        assert reopened["status"] == "PUBLIC_INVOLVEMENT"
        assert reopened["amendment_count"] == 1
        assert reopened["comment_period_opened_at"] == "2026-10-02T00:00:00Z"

        # A fresh in-window comment isolates the window gate (otherwise the
        # priority-15 participation check would report first, per §2.7).
        add_stip_comment(stip["id"], comment_text="Amendment window comment.")
        resp = api.submit_stip(stip["id"], H["state_dot_planner"])
        validate_error(resp, ApiErrorId.ERR_COMMENT_PERIOD_OPEN)
        still_open = get_success_data(api.get_stip(stip["id"], H["state_dot_planner"]))
        assert still_open["status"] == "PUBLIC_INVOLVEMENT"

        set_clock("2026-11-02T00:00:00Z")  # 31 days into the reopened window
        resubmitted = submit_stip(stip["id"])
        assert resubmitted["status"] == "SUBMITTED"
        reapproved = decide_stip(stip["id"], "APPROVE")
        assert reapproved["status"] == "APPROVED"
        assert reapproved["amendment_count"] == 1

    def test_voucher_reject_resubmit_cycle(self, api):
        """PRD §3.7: "Submission moves a `DRAFT` voucher to `UNDER_REVIEW`; the
        same action also resubmits a `REJECTED` voucher, in which case the
        payload may carry revised `period_start_date`, `period_end_date`,
        `line_items`, or `documentation_complete` values that replace the
        stored ones, with `claimed_amount_cents` recomputed and
        `resubmission_count` incremented by 1."
        PRD §3.7: "`REJECTED` is not terminal for a voucher; `APPROVED` is."

        One voucher row cycles UNDER_REVIEW -> REJECTED -> UNDER_REVIEW ->
        APPROVED: the resubmission replaces the stored lines (claimed amount
        30,000 becomes 50,000), increments resubmission_count, and the approval
        posts 0.80 x 50,000 = 40,000 federal cents.

        Design: Difficulty/non_linear_state_machine/voucher_reject_resubmit_cycle
        """
        ctx = setup_project_under_construction(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            activity_code="ROAD_RESURFACING",
            project_cost_cents=1_500_000,
            apportioned_cents=2_000_000,
            initial_obligated_cents=1_000_000,
            agreement_number="FA-V-001",
        )
        auth_id = ctx["authorization"]["id"]

        voucher = create_draft_voucher(
            auth_id,
            line_items=[create_line_item("initial", 30_000)],
        )
        submit_voucher(voucher["id"])
        rejected = decide_voucher(voucher["id"], "REJECT")
        assert rejected["status"] == "REJECTED"

        resubmitted = submit_voucher(
            voucher["id"],
            revisions={"line_items": [create_line_item("revised", 50_000)]},
        )
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["resubmission_count"] == 1
        assert resubmitted["claimed_amount_cents"] == 50_000, (
            "revised line_items replace the stored ones and claimed_amount_cents "
            f"is recomputed, got {resubmitted['claimed_amount_cents']}"
        )

        approved = decide_voucher(voucher["id"], "APPROVE")
        assert approved["status"] == "APPROVED"
        assert approved["eligible_amount_cents"] == 50_000
        assert approved["federal_reimbursable_cents"] == 40_000, (
            "0.80 x 50,000 = 40,000, got "
            f"{approved['federal_reimbursable_cents']}"
        )
        assert approved["resubmission_count"] == 1
