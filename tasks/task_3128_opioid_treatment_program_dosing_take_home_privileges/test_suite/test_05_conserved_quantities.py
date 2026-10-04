"""Depth tests: the conserved quantities that must hold across every action."""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    setup_clinic,
    setup_approvable_carry_patient,
    hold_privilege,
    evaluate_privilege,
    list_doses,
    validate_success,
    validate_paginated,
    ApiErrorId,
)


def _quota(clinic):
    data = validate_success(
        api_client.get_carry_quota(clinic["program"]["id"], clinic["admin_headers"]))
    return data[0] if isinstance(data, list) else data


def _ledger(clinic, patient_id):
    data, _meta = validate_paginated(api_client.list_carry_ledgers(
        clinic["director_headers"], {"patient_id": patient_id}))
    return data[0]


class TestCarryQuotaConservation:
    """C1: allotted_carries == granted_carries + available_carries."""

    def _setup(self):
        # The pool cap is the floor of half the remaining carries (PRD 3.7), so
        # a request of 6 against a ten-carry pool is capped at 5. The patient is
        # placed at 540 days so PRD 3.7's time-in-treatment table allowance is
        # 13 and the pool, not the table, is the binding term — otherwise the
        # table's single carry at a ~105-day tenure would cap the grant at 1 and
        # the pool arithmetic would never be exercised.
        clinic = setup_clinic(allotted_carries=10)
        patient, order = setup_approvable_carry_patient(
            clinic, time_in_treatment_days=600, ordered_daily_mg=90.0)
        priv = hold_privilege(clinic, patient["id"], patient["version"], requested_carries=6)
        return clinic, patient, order, priv

    def test_approval_debits_the_pool_and_preserves_the_identity(self):
        """PRD 2.7: "From these the ledger derives `available_carries`, the
        global conserved quantity C1, which must equal `allotted_carries` minus
        `granted_carries` at all times."
        PRD 3.7: "Once the grant is recorded, the program's `granted_carries` is
        increased by `approved_carries` and `available_carries` is restated as
        `allotted_carries` minus `granted_carries`, preserving the C1 identity."

        Design: Difficulty/compensating_invariant/carry_quota_conservation_closed_over_approve_and_revoke
        """
        clinic, patient, order, priv = self._setup()
        validate_success(evaluate_privilege(clinic, priv["id"]))
        quota = _quota(clinic)
        assert quota["allotted_carries"] == 10
        assert quota["granted_carries"] == 5
        assert quota["available_carries"] == 5
        assert quota["available_carries"] == quota["allotted_carries"] - quota["granted_carries"]

    def test_revocation_restores_the_pool_exactly(self):
        """PRD 3.10: "The decision becomes `REVOKED`, `freed_carries` is set to
        the privilege's `approved_carries` so the program pool can reclaim the
        slots, and `approved_carries` is reset to 0."
        PRD 2.7: "the released figure is a reporting field only and is never
        added back into the pool."

        Design: Difficulty/compensating_invariant/carry_quota_conservation_closed_over_approve_and_revoke
        """
        clinic, patient, order, priv = self._setup()
        validate_success(evaluate_privilege(clinic, priv["id"]))
        validate_success(api_client.revoke_privilege(priv["id"], clinic["director_headers"]))

        after = validate_success(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        assert after["freed_carries"] == 5

        quota = _quota(clinic)
        assert quota["allotted_carries"] == 10
        assert quota["granted_carries"] == 0
        assert quota["available_carries"] == 10
        assert quota["available_carries"] == quota["allotted_carries"] - quota["granted_carries"]


class TestCarriedMilligramConservation:
    """C2: the milligram total balances across issue and privilege void.

    PRD 2.7's C2 identity also carries a dispensed and a consumed term, but
    neither is reachable for a take-home row through the endpoints the PRD
    declares: PRD 3.4 refuses check-in outright for a row whose `source_type` is
    `TAKE_HOME_ISSUANCE` ("a carry is issued, not walked in to be swallowed
    under observation"), and the dispense step's precondition is the
    `NURSE_VERIFIED` state that only check-in and verify can produce. Those two
    terms are therefore exercised on observed rows elsewhere; the assertions
    here pin the issued, voided and balance terms, plus the identity itself.
    """

    def _setup(self):
        # PRD 3.7's time-in-treatment table grants 2 carries at 180 days, so the
        # patient is placed at 600 days; the request for 2 is then capped by
        # neither the table (13) nor the pool (half of 20).
        clinic = setup_clinic(allotted_carries=20,
                              lot_overrides={"lot_number": "LOT-A1",
                                             "reusable_for_take_home": True})
        patient, order = setup_approvable_carry_patient(
            clinic, time_in_treatment_days=600, ordered_daily_mg=90.0)
        priv = hold_privilege(clinic, patient["id"], patient["version"], requested_carries=2)
        validate_success(evaluate_privilege(clinic, priv["id"]))
        priv = get_success_data(api_client.get_privilege(priv["id"], clinic["director_headers"]))
        rows = list_doses(clinic, {"privilege_id": priv["id"]}, clinic["director_headers"])
        assert len(rows) == 2, f"expected two synthesized take-home rows, got {len(rows)}"
        return clinic, patient, order, priv, rows

    def test_revocation_voids_the_issued_milligrams_and_balances_the_identity(self):
        """PRD 2.7: "The patient-level ledger also holds the milligram conservation
        identity C2: `carried_balance_mg` carries the expression
        `carried_issued_mg` minus `carried_voided_mg` minus
        `carried_dispensed_mg` minus `carried_consumed_mg`, and must remain 0.0
        across every take-home dispense, waste, return and privilege void."
        PRD 3.10: "Every take-home dose row belonging to this privilege that is
        still `SCHEDULED` is cancelled, and the sum of those rows' `ordered_mg`
        is added to the patient's `carried_voided_mg`."

        Design: Difficulty/compensating_invariant/carried_milligram_conservation_closed_over_dispense_waste_and_void
        """
        clinic, patient, order, priv, rows = self._setup()
        validate_success(api_client.revoke_privilege(priv["id"], clinic["director_headers"]))

        ledger = _ledger(clinic, patient["id"])
        assert ledger["carried_issued_mg"] == pytest.approx(180.0, abs=0.01)
        assert ledger["carried_voided_mg"] == pytest.approx(180.0, abs=0.01)
        assert ledger["carried_dispensed_mg"] == pytest.approx(0.0, abs=0.01)
        assert ledger["carried_consumed_mg"] == pytest.approx(0.0, abs=0.01)
        assert ledger["carried_balance_mg"] == pytest.approx(0.0, abs=0.01)

    def test_the_identity_holds_term_by_term(self):
        """PRD 2.7: "`carried_issued_mg` is the sum of `ordered_mg` over
        take-home dose rows ever created for the patient."
        PRD 2.7: "`carried_voided_mg` is the sum of `ordered_mg` over take-home
        dose rows cancelled because their privilege was revoked before the dose
        completed."
        PRD 2.7: "`carried_balance_mg` carries the expression `carried_issued_mg`
        minus `carried_voided_mg` minus `carried_dispensed_mg` minus
        `carried_consumed_mg`."

        Design: Difficulty/compensating_invariant/carried_milligram_conservation_closed_over_dispense_waste_and_void
        """
        clinic, patient, order, priv, rows = self._setup()
        first, second = rows[0], rows[1]

        before = _ledger(clinic, patient["id"])
        assert before["carried_issued_mg"] == pytest.approx(180.0, abs=0.01)
        assert before["carried_voided_mg"] == pytest.approx(0.0, abs=0.01)
        assert before["carried_balance_mg"] == pytest.approx(
            before["carried_issued_mg"] - before["carried_voided_mg"]
            - before["carried_dispensed_mg"] - before["carried_consumed_mg"], abs=0.01)

        validate_success(api_client.revoke_privilege(priv["id"], clinic["director_headers"]))

        for row in (first, second):
            after_row = validate_success(api_client.get_dose_dispense(
                row["id"], clinic["director_headers"]))
            assert after_row["status"] == "CANCELLED"

        ledger = _ledger(clinic, patient["id"])
        expected = (ledger["carried_issued_mg"] - ledger["carried_voided_mg"]
                    - ledger["carried_dispensed_mg"] - ledger["carried_consumed_mg"])
        assert ledger["carried_balance_mg"] == pytest.approx(expected, abs=0.01)
        assert ledger["carried_balance_mg"] == pytest.approx(0.0, abs=0.01)

    def test_carry_variance_stays_zero_across_the_actions(self):
        """PRD 2.7: "`carry_variance` is a second conserved quantity that must
        stay at 0 across every privilege and exception action."
        PRD 3.10: "The patient's carry ledger `carries_used` is reduced by the
        number of cancelled take-home dose rows — floored at 0."

        Design: Difficulty/compensating_invariant/carried_milligram_conservation_closed_over_dispense_waste_and_void
        """
        clinic, patient, order, priv, rows = self._setup()
        ledger = _ledger(clinic, patient["id"])
        assert ledger["carry_variance"] == 0

        validate_success(api_client.revoke_privilege(priv["id"], clinic["director_headers"]))

        ledger = _ledger(clinic, patient["id"])
        assert ledger["carry_variance"] == 0
