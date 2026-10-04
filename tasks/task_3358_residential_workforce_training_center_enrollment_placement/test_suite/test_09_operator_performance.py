"""Operator contracts: dual-variant performance rates, pinned payment rounding,
period close-out, governance cycle."""
import pytest

from test_helpers import (
    ADMIN,
    MANAGER,
    ApiErrorId,
    api_client,
    assert_performance_snapshot,
    assign_applicant,
    create_center,
    create_operator_contract,
    create_trade_program,
    enroll_applicant,
    fetch_transition_plan,
    get_operator_contract,
    make_eligible_applicant,
    record_service,
    set_clock,
    validate_error,
    validate_success,
)


def _enroll_into(program, full_name, barrier):
    """Applicant -> ELIGIBLE -> assigned -> enrolled into the given program.
    Exactly one WELDING center exists in these tests, so the selector's rank-1
    is deterministic."""
    applicant, _case = make_eligible_applicant(
        full_name=full_name, barrier_flags=[barrier]
    )
    assign_applicant(applicant)
    return enroll_applicant(applicant["id"], program["id"])


def _complete(enrollment):
    return validate_success(
        api_client.transition_enrollment(
            enrollment["id"], {"action": "complete"}, MANAGER
        ),
        200,
    )


def _separate(enrollment, reason="PERSONAL"):
    return validate_success(
        api_client.transition_enrollment(
            enrollment["id"], {"action": "separate", "reason": reason}, MANAGER
        ),
        200,
    )


def _complete_with_placement(enrollment, starting_wage):
    _complete(enrollment)
    plan = fetch_transition_plan(enrollment["id"])
    record_service(plan["id"], "JOB_PLACEMENT", "COMPLETED",
                   starting_wage_cents=starting_wage)


class TestDualVariantPerformance:
    def _cohort(self):
        """One graduate, one leaver, one still-TRAINING enrollment, all at the
        contract's center; contract opened at the 2026-09-01 clock and
        evaluated the next day."""
        set_clock("2026-09-01T00:00:00Z")
        center = create_center(name="Center One", total_beds=2)
        program = create_trade_program(center["id"], capacity=10)
        _complete(_enroll_into(program, "Stu Grad", "FOSTER_CARE"))
        _separate(_enroll_into(program, "Stu Leave", "HOMELESS"))
        _enroll_into(program, "Stu Active", "OFFENDER")  # stays TRAINING
        contract = create_operator_contract(center["id"], contract_code="K-100")
        set_clock("2026-09-02T00:00:00Z")
        return center, contract

    def test_provisional_preview_counts_actives_as_projected_graduates(self):
        """PRD section 3.8: "The PROVISIONAL variant — computed on demand by
        the preview and never persisted — additionally counts the center's
        still-active enrollments (those in REMEDIATION or TRAINING) as
        projected graduates in both the numerator and the denominator" and
        "the preview surfaces this count as projected_actives_count."

        Design: Difficulty/dual_variant_calc/performance_rate_provisional_vs_final
        """
        _center, contract = self._cohort()
        preview = validate_success(
            api_client.get_performance_preview(contract["id"], ADMIN)
        )
        assert preview["variant"] == "PROVISIONAL"
        assert preview["projected_actives_count"] == 1
        assert preview["graduation_rate"] == pytest.approx(0.6667, abs=1e-9)

    def test_final_close_excludes_actives_and_trips_floor(self):
        """PRD section 3.8: "The FINAL variant — the one persisted at period
        close — computes graduation_rate as graduates divided by the sum of
        graduates and leavers, rounded half-up to four decimal places" and "a
        persisted snapshot whose graduation_rate falls below 0.6, or whose
        cohort produced at least one graduate while its placement_rate falls
        below 0.7, moves the contract to PROBATION".

        Design: Difficulty/dual_variant_calc/performance_rate_provisional_vs_final
        """
        _center, contract = self._cohort()
        snapshot = validate_success(
            api_client.close_period(contract["id"], ADMIN), 201
        )
        assert_performance_snapshot(snapshot)
        assert snapshot["variant"] == "FINAL"
        assert snapshot["graduates_count"] == 1
        assert snapshot["leavers_count"] == 1
        assert snapshot["graduation_rate"] == pytest.approx(0.5)
        assert snapshot["payment_cents"] == 0
        assert get_operator_contract(contract["id"])["status"] == "PROBATION"


class TestPaymentRoundingOrder:
    def _two_placed_graduates(self):
        set_clock("2026-09-01T00:00:00Z")
        center = create_center(name="Pay Center", total_beds=2)
        program = create_trade_program(center["id"], capacity=10)
        _complete_with_placement(
            _enroll_into(program, "Grad One", "FOSTER_CARE"), 149999
        )
        _complete_with_placement(
            _enroll_into(program, "Grad Two", "HOMELESS"), 149999
        )
        contract = create_operator_contract(center["id"], contract_code="K-200")
        set_clock("2026-09-02T00:00:00Z")
        return center, contract

    def test_per_graduate_round_then_sum(self):
        """PRD section 3.8: "Rounding each award first and summing second is
        the conforming order — two placed graduates at 149999 cents each pay
        399998 cents under the pinned order but 399997 cents if the raw
        products were summed before a single rounding, and only the former is
        correct."

        Design: Difficulty/combinatorial_formula/operator_payment_per_graduate_rounding_order
        """
        _center, contract = self._two_placed_graduates()
        snapshot = validate_success(
            api_client.close_period(contract["id"], ADMIN), 201
        )
        assert snapshot["payment_cents"] == 399998, (
            "199999 + 199999; sum-then-round would give 399997"
        )
        assert snapshot["avg_starting_wage_cents"] == 149999
        assert snapshot["graduation_rate"] == pytest.approx(1.0)
        assert snapshot["placement_rate"] == pytest.approx(1.0)

    def test_contract_stays_active_when_both_floors_met(self):
        """PRD section 3.8: "a persisted snapshot whose graduation_rate falls
        below 0.6, or whose cohort produced at least one graduate while its
        placement_rate falls below 0.7, moves the contract to PROBATION" —
        with both floors met, no probation transition fires.

        Design: Difficulty/combinatorial_formula/operator_payment_per_graduate_rounding_order
        """
        _center, contract = self._two_placed_graduates()
        validate_success(api_client.close_period(contract["id"], ADMIN), 201)
        assert get_operator_contract(contract["id"])["status"] == "ACTIVE"


class TestPreviewNeverPersists:
    def test_previews_leave_snapshot_store_empty_until_close(self):
        """PRD section 3.8: "The PROVISIONAL variant — computed on demand by
        the preview and never persisted" and "A successful close persists a
        performance snapshot — always with variant set to FINAL".

        Design: Corner/calculations/performance_preview_never_persists_snapshot
        """
        set_clock("2026-09-01T00:00:00Z")
        center = create_center(name="Snap Center", total_beds=2)
        program = create_trade_program(center["id"], capacity=5)
        _complete(_enroll_into(program, "Snap Stu", "FOSTER_CARE"))
        contract = create_operator_contract(center["id"], contract_code="K-300")
        set_clock("2026-09-02T00:00:00Z")
        preview = validate_success(
            api_client.get_performance_preview(contract["id"], ADMIN)
        )
        assert preview["variant"] == "PROVISIONAL"
        validate_success(api_client.get_performance_preview(contract["id"],
                                                            ADMIN))
        rows = validate_success(
            api_client.list_performance_snapshots(contract["id"], ADMIN)
        )
        assert rows == [], "previews must never persist a snapshot"
        snapshot = validate_success(
            api_client.close_period(contract["id"], ADMIN), 201
        )
        assert snapshot["variant"] == "FINAL"
        rows = validate_success(
            api_client.list_performance_snapshots(contract["id"], ADMIN)
        )
        assert len(rows) == 1
        assert rows[0]["variant"] == "FINAL"


class TestEmptyCohortClose:
    def _empty_center_contract(self):
        set_clock("2026-09-01T00:00:00Z")
        center = create_center(name="Empty Center", region_code="R-SOUTH",
                               total_beds=2)
        contract = create_operator_contract(center["id"], operator_name="QuietCo",
                                            contract_code="K-400")
        set_clock("2026-09-10T00:00:00Z")
        return center, contract

    def test_zero_rates_and_auto_probation(self):
        """PRD section 3.8: "reading 0.0 when that denominator is zero" and "a
        persisted snapshot whose graduation_rate falls below 0.6, or whose
        cohort produced at least one graduate while its placement_rate falls
        below 0.7, moves the contract to PROBATION".

        Design: Corner/calculations/empty_cohort_closes_with_zero_rates_and_probation
        """
        _center, contract = self._empty_center_contract()
        snapshot = validate_success(
            api_client.close_period(contract["id"], ADMIN), 201
        )
        assert snapshot["graduates_count"] == 0
        assert snapshot["leavers_count"] == 0
        assert snapshot["graduation_rate"] == pytest.approx(0.0)
        assert snapshot["placement_rate"] == pytest.approx(0.0)
        assert snapshot["payment_cents"] == 0
        assert get_operator_contract(contract["id"])["status"] == "PROBATION"

    def test_period_window_advances_after_close(self):
        """PRD section 3.8: "The close then advances current_period_start to
        the day after period_end, increments period_sequence by 1".

        Design: Corner/calculations/empty_cohort_closes_with_zero_rates_and_probation
        """
        _center, contract = self._empty_center_contract()
        validate_success(api_client.close_period(contract["id"], ADMIN), 201)
        after = get_operator_contract(contract["id"])
        assert after["period_sequence"] == 2
        assert after["current_period_start"] == "2026-09-11"


class TestClosePeriodGate:
    def test_same_day_close_rejected_then_next_day_succeeds(self):
        """PRD section 3.8: "Closing a period is allowed only when the logical
        clock date is strictly later than current_period_start and the
        contract is ACTIVE or PROBATION; otherwise the close is rejected with
        ERR_PERIOD_NOT_CLOSABLE."

        Design: Corner/validations/close_period_same_day_not_closable
        """
        set_clock("2026-09-01T00:00:00Z")
        center = create_center(name="Close Center", total_beds=2)
        contract = create_operator_contract(center["id"], operator_name="CloseCo",
                                            contract_code="K-500")
        resp = api_client.close_period(contract["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSABLE)
        set_clock("2026-09-02T00:00:00Z")
        snapshot = validate_success(
            api_client.close_period(contract["id"], ADMIN), 201
        )
        assert snapshot["variant"] == "FINAL"
        rows = validate_success(
            api_client.list_center_operator_contracts(center["id"], ADMIN)
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "PROBATION"


class TestContractCycle:
    def test_manual_probate_reinstate_terminate_then_terminal_lockdown(self):
        """PRD section 3.8: "probating moves ACTIVE to PROBATION, reinstating
        moves PROBATION back to ACTIVE — a cycle that may repeat across review
        periods — and terminating from either state lands in TERMINATED, which
        is terminal."

        Design: Corner/state_machines/contract_manual_probate_reinstate_terminate_cycle
        """
        set_clock("2026-09-01T00:00:00Z")
        center = create_center(name="Cycle Center", total_beds=2)
        contract = create_operator_contract(center["id"], operator_name="CycleCo",
                                            contract_code="K-600")
        for action, expected in [("probate", "PROBATION"),
                                 ("reinstate", "ACTIVE"),
                                 ("terminate", "TERMINATED")]:
            data = validate_success(
                api_client.transition_operator_contract(
                    contract["id"], {"action": action}, ADMIN
                ),
                200,
            )
            assert data["status"] == expected
        resp = api_client.transition_operator_contract(
            contract["id"], {"action": "reinstate"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        resp = api_client.close_period(contract["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSABLE)
