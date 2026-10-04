"""Conserved quantities: a compensating pair restores the ledger balance exactly, and
one rapid disenrollment decrements each book-size counter exactly once.
"""
import pytest

from test_helpers import (
    validate_paginated, api_client, get_success_data, validate_error, validate_success,
    setup_agency_with_active_agent, setup_scope_and_completed_call,
    setup_effectuated_enrollment, set_clock,
    TEST_USERS, make_licensed_agent_headers,
)

DIRECTOR = TEST_USERS["director_of_sales_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


class TestReverseThenReinstateRestoresBalance:
    """The ledger's accessor is conserved across the compensating pair."""

    def _effectuated_with_entries(self):
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_effectuated_enrollment(scn)
        rows, _meta = validate_paginated(api_client.list_ledger_entries(
            DIRECTOR, params={"enrollment_id": scn["enrollment"]["id"]}))
        scn["entries"] = {r["entry_type"]: r for r in rows}
        return scn

    def test_the_compensating_pair_leaves_the_conserved_quantity_unchanged(self):
        """PRD §2.8: "A subsequent reinstatement returns the entry to the live ledger —
        either as `PROVISIONAL` or directly as `FINALIZED` — and the compensating pair must
        restore the pre-reversal balance exactly".
        PRD §3.8: "When the reversal is applied to an entry whose enrollment is
        simultaneously `EFFECTUATED` on the submission dimension and `ENROLLED` on the
        membership dimension, an `ADJUSTMENT` entry is additionally posted in status
        `PROVISIONAL`."

        Design: Difficulty/compensating_invariant/invariant_reverse_then_reinstate_restores_commission_balance
        """
        scn = self._effectuated_with_entries()
        initial_id = scn["entries"]["INITIAL"]["id"]
        adjustment = 1500 * 1 * 0.10  # the ADJUSTMENT the reversal itself posts

        before = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
        assert before["commission_balance_cents"] == pytest.approx(5400.00, abs=0.01)

        validate_success(api_client.reverse_ledger_entry(
            initial_id, {"reason": "Duplicate INITIAL posting"}, DIRECTOR), 200)
        after_reverse = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
        # The INITIAL drops out and the mandated ADJUSTMENT comes in beside the
        # RENEWAL: 1800.00 + 150.00.
        assert after_reverse["commission_balance_cents"] == pytest.approx(
            1800.00 + adjustment, abs=0.01)

        validate_success(api_client.reinstate_ledger_entry(initial_id, DIRECTOR), 200)
        after_reinstate = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
        assert after_reinstate["commission_balance_cents"] == pytest.approx(
            5400.00 + adjustment, abs=0.01)

    def test_reinstatement_returns_the_entry_to_provisional_with_its_amount(self):
        """PRD §2.8: "Every entry carries a `period_month` in `YYYY-MM` form, a `posted_on`
        instant, a `status` of `PROVISIONAL`, `FINALIZED` or `REVERSED`".
        PRD §3.8: "An `INITIAL` entry takes the annual initial commission as its
        `amount_cents`, unmodified."

        Design: Difficulty/compensating_invariant/invariant_reverse_then_reinstate_restores_commission_balance
        """
        scn = self._effectuated_with_entries()
        initial_id = scn["entries"]["INITIAL"]["id"]

        api_client.reverse_ledger_entry(initial_id, {"reason": "Duplicate INITIAL"}, DIRECTOR)
        reinstated = validate_success(
            api_client.reinstate_ledger_entry(initial_id, DIRECTOR), 200)
        assert reinstated["status"] == "PROVISIONAL"
        assert reinstated["amount_cents"] == pytest.approx(3600.00, abs=0.01)

    def test_the_sibling_entry_is_untouched_by_the_pair(self):
        """PRD §3.6: "a `RENEWAL` ledger entry is posted in status `PROVISIONAL`".
        PRD §3.8: "A `RENEWAL` entry takes the annual renewal commission as its
        `amount_cents`."

        Design: Difficulty/compensating_invariant/invariant_reverse_then_reinstate_restores_commission_balance
        """
        scn = self._effectuated_with_entries()
        initial_id = scn["entries"]["INITIAL"]["id"]
        renewal_id = scn["entries"]["RENEWAL"]["id"]

        api_client.reverse_ledger_entry(initial_id, {"reason": "Duplicate INITIAL"}, DIRECTOR)
        api_client.reinstate_ledger_entry(initial_id, DIRECTOR)

        renewal = get_success_data(api_client.get_ledger_entry(renewal_id, DIRECTOR))
        assert renewal["amount_cents"] == pytest.approx(1800.00, abs=0.01)
        assert renewal["status"] == "PROVISIONAL"


class TestRapidDisenrollmentDecrementsBookSizeOnce:
    """Both book-size counters drop exactly once on one rapid disenrollment."""

    def _enrolled_scenario(self):
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        setup_effectuated_enrollment(scn)
        return scn

    def test_before_the_disenrollment_both_counters_and_the_ratio_read_one_and_zero(self):
        """PRD §3.6: "the agent's `active_enrollment_count` and the plan's
        `enrolled_member_count` are recomputed".

        Design: Difficulty/compensating_invariant/invariant_rapid_disenrollment_decrements_book_size_once
        """
        scn = self._enrolled_scenario()
        plan = get_success_data(api_client.get_plan(scn["plan"]["id"], COMPLIANCE))
        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))

        assert plan["enrolled_member_count"] == 1
        assert agent["active_enrollment_count"] == 1
        assert agency["loss_ratio"] == pytest.approx(0.0, abs=1e-9)

    def test_the_finalized_chargeback_carries_the_day_zero_to_thirty_band(self):
        """PRD §3.7: "The first spans day 0 through day 30 inclusive and carries a base
        percentage of 1.00."
        PRD §3.7: "It posts a `CHARGEBACK` ledger entry in status `FINALIZED` whose
        `amount_cents` is strictly negative."

        Design: Difficulty/compensating_invariant/invariant_rapid_disenrollment_decrements_book_size_once
        """
        scn = self._enrolled_scenario()
        set_clock("2026-11-10T00:00:00Z")
        result = validate_success(api_client.disenroll_enrollment(
            scn["enrollment"]["id"],
            {"disenrollment_date": "2026-11-10T00:00:00Z",
             "disenrollment_reason": "BENEFICIARY_REQUEST"},
            CARRIER_INT), 200)

        assert result["disenrolled_day_number"] == 9
        assert result["is_rapid_disenrollment"] is True

        rows, _meta = validate_paginated(api_client.list_ledger_entries(
            DIRECTOR, params={"enrollment_id": scn["enrollment"]["id"]}))
        cb = [r for r in rows if r["entry_type"] == "CHARGEBACK"
              and r["status"] == "FINALIZED"][0]
        assert cb["amount_cents"] == pytest.approx(-3600.00, abs=0.01)
        assert cb["clawback_pct_applied"] == pytest.approx(1.00, abs=0.001)

    def test_one_rapid_disenrollment_decrements_each_counter_exactly_once(self):
        """PRD §3.7: "It recomputes the plan's `enrolled_member_count` and the agent's
        `active_enrollment_count`".
        PRD §3.7: "Its denominator is the count of the agency's enrollments whose
        `disenrollment_status` is `ENROLLED` — the live book — and that denominator is never
        permitted to fall below 1."

        Design: Difficulty/compensating_invariant/invariant_rapid_disenrollment_decrements_book_size_once
        """
        scn = self._enrolled_scenario()
        set_clock("2026-11-10T00:00:00Z")
        api_client.disenroll_enrollment(
            scn["enrollment"]["id"],
            {"disenrollment_date": "2026-11-10T00:00:00Z",
             "disenrollment_reason": "BENEFICIARY_REQUEST"},
            CARRIER_INT)

        plan = get_success_data(api_client.get_plan(scn["plan"]["id"], COMPLIANCE))
        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))

        assert plan["enrolled_member_count"] == 0
        assert agent["active_enrollment_count"] == 0
        # One FINALIZED negative chargeback over a live book floored at 1.
        assert agency["loss_ratio"] == pytest.approx(1.0, abs=1e-9)

    def test_the_as_earned_pass_bills_a_rapid_disenrolled_row_one_month(self):
        """PRD §3.5: "An enrollment that ended as a `RAPID_DISENROLLED` always contributes
        exactly 1 billed month, because the plan never ran a full month."

        Design: Difficulty/compensating_invariant/invariant_rapid_disenrollment_decrements_book_size_once
        """
        scn = self._enrolled_scenario()
        set_clock("2026-11-10T00:00:00Z")
        result = validate_success(api_client.disenroll_enrollment(
            scn["enrollment"]["id"],
            {"disenrollment_date": "2026-11-10T00:00:00Z",
             "disenrollment_reason": "BENEFICIARY_REQUEST"},
            CARRIER_INT), 200)

        assert result["final_commission_cents"] == pytest.approx(300.00, abs=0.01)