"""Premise notifications, the refusal cycle and what a final refusal costs."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, assert_customer_notification, escalate, notify,
    read_line, read_notification, read_plan, read_span, respond,
    setup_completed_span_with_draft_line, setup_in_progress_span, setup_released_span,
    setup_notification_in_state, validate_error, validate_success,
)

ADVOCATE = TEST_USERS["advocate_headers"]
FORESTER = TEST_USERS["forester_headers"]
PLANNER = TEST_USERS["planner_headers"]


class TestRefusalCycle:
    """NOTIFIED → REFUSED → ESCALATED → NOTIFIED, capped at three rounds."""

    def test_each_escalation_increments_the_round_and_redelivery_preserves_it(self, api):
        """PRD §3.5: "Escalating a refusal moves it `REFUSED → ESCALATED` and increases
        `refusal_round` by 1, and the program permits at most three rounds: if the round that
        escalation would produce would exceed 3, the request is rejected with
        `ERR_NOTIFICATION_ROUND_LIMIT` (HTTP 422)."
        PRD §3.5: "A delivery made from `ESCALATED` closes the refusal loop
        `NOTIFIED → REFUSED → ESCALATED → NOTIFIED` and leaves `refusal_round` exactly at the
        value the escalation set; re-delivery never resets the round counter."

        Design: Difficulty/non_linear_state_machine/customer_notification_refusal_cycle_reenters_notified_with_round_increment
        """
        world = setup_released_span()
        record = _open_notification(api, world["span"]["id"])
        assert record["refusal_round"] == 0 and record["status"] == "PENDING"

        notify(record["id"])
        respond(record["id"], "REFUSED")
        after_first = escalate(record["id"])
        assert after_first["status"] == "ESCALATED" and after_first["refusal_round"] == 1

        redelivered = notify(record["id"], contact_method="CERTIFIED_MAIL")
        assert redelivered["status"] == "NOTIFIED"
        assert redelivered["refusal_round"] == 1, "re-delivery never resets the round counter"

        respond(record["id"], "REFUSED")
        assert escalate(record["id"])["refusal_round"] == 2
        notify(record["id"], contact_method="PHONE")
        respond(record["id"], "REFUSED")
        assert escalate(record["id"])["refusal_round"] == 3

    def test_a_fourth_escalation_breaches_the_round_cap(self, api):
        """PRD §3.5: "Escalating a refusal moves it `REFUSED → ESCALATED` and increases
        `refusal_round` by 1, and the program permits at most three rounds: if the round that
        escalation would produce would exceed 3, the request is rejected with
        `ERR_NOTIFICATION_ROUND_LIMIT` (HTTP 422)."
        PRD §3.5: "Delivering the notification moves it `PENDING → NOTIFIED` and stamps
        `notified_at` from the logical clock; the advocate may supply a `contact_method` on
        delivery to record a change from the originally planned channel."

        Design: Difficulty/non_linear_state_machine/customer_notification_refusal_cycle_reenters_notified_with_round_increment
        """
        world = setup_released_span()
        record = _open_notification(api, world["span"]["id"])
        for channel in (None, "CERTIFIED_MAIL", "PHONE"):
            notify(record["id"], contact_method=channel)
            respond(record["id"], "REFUSED")
            escalate(record["id"])
        notify(record["id"])
        respond(record["id"], "REFUSED")

        resp = api.escalate_customer_notification(record["id"], ADVOCATE)

        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_ROUND_LIMIT.value)
        assert resp.status_code == 422
        after = read_notification(record["id"])
        assert after["status"] == "REFUSED"
        assert after["refusal_round"] == 3
        assert after["contact_method"] == "PHONE", \
            "the third delivery recorded the channel change and the fourth left it alone"


def _open_notification(api, work_order_id, premise_code="PRM-1",
                       contact_method="DOOR_HANGER", unit_count_at_premise=30):
    resp = api.create_customer_notification({
        "work_order_id": work_order_id, "premise_code": premise_code,
        "contact_method": contact_method,
        "unit_count_at_premise": unit_count_at_premise}, ADVOCATE)
    record = validate_success(resp, 201)
    assert_customer_notification(record)
    return record


class TestFinalRefusalCascade:
    """Accepting a refusal withholds units, reprices the draft and moves the ledger."""

    @staticmethod
    def _span_with_draft_line_and_escalated_premise():
        world = setup_completed_span_with_draft_line()
        world["notification"] = setup_notification_in_state(
            world["span"]["id"], "ESCALATED", premise_code="PRM-1",
            unit_count_at_premise=30, rounds=2)
        return world

    def test_finalizing_a_refusal_withholds_the_premise_units(self, api):
        """PRD §3.5: "Second, the span's `refusal_blocked_unit_count` is recomputed as the sum
        of `unit_count_at_premise` across every notification of that span whose `status` is
        `FINAL_REFUSAL` — and only `FINAL_REFUSAL`, so records merely at `REFUSED` or
        `ESCALATED` withhold nothing."
        PRD §3.5: "Finalization moves the record `ESCALATED → FINAL_REFUSAL`, which is
        terminal, and then runs a four-hop cascade."

        Design: Difficulty/transitive_cascade/final_refusal_cascades_notification_to_span_to_draft_line_to_plan_ledger
        """
        world = self._span_with_draft_line_and_escalated_premise()
        assert read_span(world["span"]["id"])["refusal_blocked_unit_count"] == 0

        finalized = validate_success(
            api.finalize_refusal(world["notification"]["id"], FORESTER), 200)

        assert finalized["status"] == "FINAL_REFUSAL"
        span = read_span(world["span"]["id"])
        assert span["refusal_blocked_unit_count"] == 30
        assert span["actual_units_completed"] == 180, "production is never discarded"

    def test_finalizing_a_refusal_reprices_the_draft_line_and_the_plan_ledger(self, api):
        """PRD §3.5: "Third, the changed withholding forces every `DRAFT` billing line on that
        span to reprice from scratch: `billable_units`, `density_multiplier`, `gross_cents`,
        `retainage_cents`, `net_payable_cents`, `mobilization_credit_cents` and
        `final_payable_cents` are all recomputed."
        PRD §3.5: "Fourth, the changed `final_payable_cents` forces the owning plan's
        `committed_cents` to be recomputed."

        Design: Difficulty/transitive_cascade/final_refusal_cascades_notification_to_span_to_draft_line_to_plan_ledger
        """
        world = self._span_with_draft_line_and_escalated_premise()
        plan_id, line_id = world["plan"]["id"], world["line"]["id"]
        assert read_plan(plan_id)["committed_cents"] == 820800
        assert read_line(line_id)["gross_cents"] == 864000

        api.finalize_refusal(world["notification"]["id"], FORESTER)

        line = read_line(line_id)
        assert line["billable_units"] == 150, "180 produced less 30 withheld"
        assert line["density_multiplier"] == pytest.approx(1.00, abs=0.001)
        assert line["gross_cents"] == 720000
        assert line["retainage_cents"] == 36000
        assert line["final_payable_cents"] == 684000
        assert line["status"] == "DRAFT"
        assert read_plan(plan_id)["committed_cents"] == 684000


class TestRefusalBlocksCompletionAndRoles:

    def test_a_span_with_a_refused_premise_cannot_be_completed(self, api):
        """PRD §3.3: "If any notification on the span is still in `REFUSED` or `ESCALATED`,
        completion is rejected with `ERR_CUSTOMER_REFUSAL_BLOCKING` (HTTP 409) — an unresolved
        refusal must be either acknowledged, or escalated and then finalized, before the crew's
        work on that span can be closed out."

        Design: Corner/validations/corner_complete_with_refused_notification_is_rejected
        """
        world = setup_in_progress_span()
        from test_helpers import file_production
        file_production(world["booking"]["id"], world["crew"]["id"],
                        work_date="2026-08-03", units_trimmed=180, labor_hours=8,
                        equipment_hours=6, disposal_tons=1)
        record = setup_notification_in_state(world["span"]["id"], "REFUSED")

        resp = api.complete_work_order(world["span"]["id"], PLANNER)

        validate_error(resp, ApiErrorId.ERR_CUSTOMER_REFUSAL_BLOCKING.value)
        assert resp.status_code == 409
        span = read_span(world["span"]["id"])
        assert span["execution_status"] == "IN_PROGRESS"
        assert span["billing_status"] == "NOT_BILLABLE"
        assert read_notification(record["id"])["status"] == "REFUSED"

    def test_the_customer_advocate_may_not_finalize_a_refusal(self, api):
        """PRD §3.5: "Finalization is a utility decision, not a contractor or advocate one —
        only a `UtilityForester` may take it, and this is the one notification operation the
        `CustomerAdvocate` cannot perform."
        PRD §2.1: "The `CustomerAdvocate` opens premise notifications, delivers them, records
        the customer's response, and escalates a refusal. It cannot finalize a refusal."

        Design: Corner/rbac/corner_customer_advocate_cannot_finalize_a_refusal
        """
        world = setup_released_span()
        record = setup_notification_in_state(world["span"]["id"], "ESCALATED", rounds=2)

        resp = api.finalize_refusal(record["id"], ADVOCATE)

        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
        assert resp.status_code == 403
        after = read_notification(record["id"])
        assert after["status"] == "ESCALATED"
        assert after["refusal_round"] == 2
        assert read_span(world["span"]["id"])["refusal_blocked_unit_count"] == 0
