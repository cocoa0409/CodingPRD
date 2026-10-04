"""Boundary precision: strict comparisons and floored ratios."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    create_activated_account,
    create_kpi,
    evaluate_kpi,
    begin_offboarding,
    create_transition_task,
    start_transition_task,
    complete_transition_task,
    TEST_USERS,
    ae_headers,
)

GM = TEST_USERS["governance_manager_headers"]
TRANS = TEST_USERS["transition_manager_headers"]


class TestEscalationMarginBoundary:

    def test_shortfall_of_exactly_500_does_not_open(self, api):
        """PRD §2.11: "when a BPS row's actual_value falls more than 500 basis
        points below its target_value, the row's escalation_status becomes OPEN".
        PRD §2.11: "Both boundaries are strict — a shortfall of exactly 500 basis
        points ... does not open an escalation and leaves escalation_status at
        NONE."

        Design: Difficulty/boundary_precision_check/escalation_exact_margin_does_not_open
        """
        account = create_activated_account()
        kpi = create_kpi(account, target_value=9100)
        evaluated = evaluate_kpi(kpi, 8600)
        assert evaluated["escalation_status"] == "NONE"
        # 3,000,000 * (9100 - 8600) / 10000 = 150,000.00
        assert evaluated["penalty_cents"] == pytest.approx(150_000.00, abs=0.01)
        assert evaluated["penalty_cents"] != pytest.approx(152_000.00, abs=0.01)

    def test_shortfall_of_501_opens(self, api):
        """PRD §2.11: "when a BPS row's actual_value falls more than 500 basis
        points below its target_value, the row's escalation_status becomes OPEN".
        PRD §2.11: "Because the count of open escalations feeds the governance
        posture rollup, a boundary flip changes the account's posture."

        Design: Difficulty/boundary_precision_check/escalation_exact_margin_does_not_open
        """
        account = create_activated_account()
        kpi = create_kpi(account, target_value=9100)
        evaluated = evaluate_kpi(kpi, 8599)
        assert evaluated["escalation_status"] == "OPEN"
        # 3,000,000 * 501 / 10000 = 150,300.00
        assert evaluated["penalty_cents"] == pytest.approx(150_300.00, abs=0.01)


class TestCompletionFloor:

    def test_two_of_three_tasks_floor_to_6666(self, api):
        """PRD §3.8: "the completion is the progressed count multiplied by 10,000
        and divided by the eligible count, floored to a whole number of basis
        points."
        PRD §3.8: "The floor is observable: one task done out of three yields
        3,333 basis points, never 3,334".

        Design: Difficulty/boundary_precision_check/completion_floor_two_of_three_tasks
        """
        account = create_activated_account()
        account = begin_offboarding(account)
        tasks = []
        for seq, (name, ttype) in enumerate(
            [
                ("Handover", "DATA_HANDOVER"),
                ("Records", "RECORDS_TRANSFER"),
                ("Vendor wind-down", "VENDOR_TERMINATION"),
            ],
            start=1,
        ):
            tasks.append(
                create_transition_task(
                    account,
                    task_name=name,
                    task_type=ttype,
                    sequence_no=seq,
                    blocking=seq < 3,
                )
            )
        for task in tasks[:2]:
            start_transition_task(task)
            api.complete_transition_task(task["id"], TRANS)
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["completion_pct_bps"] == 6666
        assert current["completion_pct_bps"] != 6667

    def test_every_task_terminal_reaches_exactly_10000(self, api):
        """PRD §3.8: "completion reaches exactly 10,000 only when every task is
        terminal."
        PRD §3.8: "Closure compares against exactly 10,000 and does not accept a
        value at or above it from any other path."

        Design: Difficulty/boundary_precision_check/completion_floor_two_of_three_tasks
        """
        account = create_activated_account()
        account = begin_offboarding(account)
        tasks = []
        for seq, (name, ttype) in enumerate(
            [
                ("Handover", "DATA_HANDOVER"),
                ("Records", "RECORDS_TRANSFER"),
                ("Vendor wind-down", "VENDOR_TERMINATION"),
            ],
            start=1,
        ):
            tasks.append(
                create_transition_task(
                    account,
                    task_name=name,
                    task_type=ttype,
                    sequence_no=seq,
                    blocking=seq < 3,
                )
            )
        for task in tasks:
            start_transition_task(task)
            api.complete_transition_task(task["id"], TRANS)
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["completion_pct_bps"] == 10_000