"""Assistance tiering and the two conserved ledgers.

Sources: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8 rules `combinatorial_formula`
and `compensating_invariant`.
"""
from test_helpers.assertions import (
    assert_infusion_appointment,
    assert_instant_equals,
    assert_money_ledger,
    assert_unit_ledger,
)
from test_helpers.constants import CLOCK_DEFAULT, instant
from test_helpers.fixtures import (
    ADMIN,
    active_enrollment,
    active_episode,
    administer_appointment,
    cancel_appointment,
    reverse_administration,
    schedule_appointment,
    set_clock,
)


def _assisted_practice():
    """An `ACTIVE` Infliximab episode on Meridian PPO with six approved units,
    an open ambulatory chair and one `ACTIVE` manufacturer copay card carrying
    500000 cents, so no dose is capped by the remaining benefit."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    scenario = active_episode(requested_units=6)
    active_enrollment(scenario)
    return scenario


# ---------------------------------------------------------------------------
# combinatorial_formula /
# assistance_tier_evaluation_order_pins_applied_and_out_of_pocket
# ---------------------------------------------------------------------------
def test_first_dose_tier_is_keyed_on_the_gross_share_not_the_residual():
    """A 138759 gross share sits at or above 100000 and takes the 80-percent tier.

    PRD §3.7: "the program covers the whole amount when `dose_cost_share_cents`
    is strictly below 20,000 cents (two hundred dollars), covers 90 percent of it
    when the share is at least 20,000 cents but strictly below 100,000 cents (one
    thousand dollars), and covers 80 percent of it at or above 100,000 cents."

    PRD §3.7: "The tier is keyed on the gross share and never on any residual
    amount."

    Design: Difficulty/combinatorial_formula/assistance_tier_evaluation_order_pins_applied_and_out_of_pocket
    """
    scenario = _assisted_practice()

    first = schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))

    assert_infusion_appointment(first)
    assert first["dose_sequence"] == 1
    assert first["dose_cost_share_cents"] == 138_759
    assert first["assistance_applied_cents"] == 111_007, (
        "0.80 of a 138759 gross share rounds half up to 111007, got "
        f"{first['assistance_applied_cents']}"
    )
    assert first["patient_out_of_pocket_cents"] == 27_752
    assert first["assistance_applied_cents"] != 124_883, (
        "124883 is the answer produced by keying the tier on the residual out-of-pocket"
    )
    assert first["reserved_enrollment_id"] == scenario.enrollment_id


def test_second_dose_re_derives_its_own_tier_from_its_own_gross_share():
    """A 56259 gross share falls in the 90-percent tier independently.

    PRD §3.7: "**Third**, the gross assistance is that share multiplied by the
    coverage fraction, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/assistance_tier_evaluation_order_pins_applied_and_out_of_pocket
    """
    scenario = _assisted_practice()

    schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))
    second = schedule_appointment(scenario, instant(2026, 8, 12, 12, 0, 0))

    assert second["dose_sequence"] == 2
    assert second["dose_cost_share_cents"] == 56_259
    assert second["assistance_applied_cents"] == 50_633, (
        "0.90 of a 56259 gross share rounds half up to 50633, got "
        f"{second['assistance_applied_cents']}"
    )
    assert second["patient_out_of_pocket_cents"] == 5_626
    assert second["reserved_enrollment_id"] == scenario.enrollment_id


def test_the_two_tiers_reserve_the_sum_of_both_applied_amounts():
    """Both reservations land in the enrollment's `benefit_reserved_cents`.

    PRD §3.7: "**Sixth**, the books are settled: `patient_out_of_pocket_cents` is
    the gross share less `assistance_applied_cents`, `reserved_enrollment_id`
    records the chosen enrollment, that amount is added to the enrollment's
    `benefit_reserved_cents` and subtracted from its `benefit_remaining_cents`,
    and if `benefit_remaining_cents` thereby reaches exactly zero the enrollment
    moves `ACTIVE → EXHAUSTED` and its `version` increments by one."

    Design: Difficulty/combinatorial_formula/assistance_tier_evaluation_order_pins_applied_and_out_of_pocket
    """
    scenario = _assisted_practice()

    first = schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))
    second = schedule_appointment(scenario, instant(2026, 8, 12, 12, 0, 0))

    assert first["assistance_applied_cents"] + second["assistance_applied_cents"] == 161_640

    enrollment = scenario.refresh_enrollment()
    assert_money_ledger(enrollment, used=0, reserved=161_640, remaining=338_360)
    assert enrollment["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# compensating_invariant /
# authorization_unit_conservation_across_administration_and_reversal
# ---------------------------------------------------------------------------
def _unit_ledger_practice():
    """An `ACTIVE` Infliximab episode with an `APPROVED` six-unit authorization
    and no assistance enrollment, so the unit ledger is observed in isolation."""
    set_clock(CLOCK_DEFAULT, ADMIN)
    return active_episode(requested_units=6)


def test_scheduling_moves_one_unit_from_remaining_into_reserved():
    """Booking a chair reserves exactly one unit.

    PRD §2.8: "Scheduling a dose moves exactly one unit from `units_remaining`
    into `units_reserved`."

    Design: Difficulty/compensating_invariant/authorization_unit_conservation_across_administration_and_reversal
    """
    scenario = _unit_ledger_practice()
    assert_unit_ledger(scenario.refresh_authorization(), reserved=0, consumed=0, remaining=6)
    assert scenario.authorization["approved_units"] == 6

    schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))

    assert_unit_ledger(scenario.refresh_authorization(), reserved=1, consumed=0, remaining=5)


def test_administration_moves_the_unit_from_reserved_into_consumed():
    """Administering the dose consumes the reserved unit and leaves remaining alone.

    PRD §2.8: "Administering that dose moves the same unit from `units_reserved`
    into `units_consumed`, leaving `units_remaining` untouched."

    Design: Difficulty/compensating_invariant/authorization_unit_conservation_across_administration_and_reversal
    """
    scenario = _unit_ledger_practice()
    schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))

    set_clock(instant(2026, 8, 12, 9, 0, 0), ADMIN)
    administered = administer_appointment(scenario)

    assert administered["status"] == "ADMINISTERED"
    assert_instant_equals(administered["administered_at"], instant(2026, 8, 12, 9, 0, 0))
    assert_unit_ledger(scenario.refresh_authorization(), reserved=0, consumed=1, remaining=5)
    assert scenario.refresh_episode()["doses_administered"] == 1
    assert scenario.refresh_patient()["administered_dose_total"] == 1


def test_reversal_returns_the_unit_to_reserved_rather_than_to_remaining():
    """The four observation points each sum to the six approved units.

    PRD §2.8: "Reversing an administration moves the unit from `units_consumed`
    back into `units_reserved`."

    PRD §2.8: "Reversal is not a cancellation — the dose returns to a scheduled
    state holding its reservations, rather than releasing them."

    Design: Difficulty/compensating_invariant/authorization_unit_conservation_across_administration_and_reversal
    """
    scenario = _unit_ledger_practice()
    assert_unit_ledger(scenario.refresh_authorization(), reserved=0, consumed=0, remaining=6)

    schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))
    assert_unit_ledger(scenario.refresh_authorization(), reserved=1, consumed=0, remaining=5)

    set_clock(instant(2026, 8, 12, 9, 0, 0), ADMIN)
    administer_appointment(scenario)
    assert_unit_ledger(scenario.refresh_authorization(), reserved=0, consumed=1, remaining=5)

    reversed_dose = reverse_administration(
        scenario, reversal_reason="DOCUMENTATION_ERROR"
    )

    assert reversed_dose["status"] == "SCHEDULED"
    assert reversed_dose["administered_at"] is None
    assert reversed_dose["reversal_reason"] == "DOCUMENTATION_ERROR"

    authorization = scenario.refresh_authorization()
    assert_unit_ledger(authorization, reserved=1, consumed=0, remaining=5)
    assert authorization["units_remaining"] == 5, (
        "the reversal returns the unit to the reservation, it does not release it"
    )
    assert authorization["units_remaining"] != 6
    assert scenario.refresh_episode()["doses_administered"] == 0
    assert scenario.refresh_patient()["administered_dose_total"] == 0


# ---------------------------------------------------------------------------
# compensating_invariant /
# assistance_benefit_conservation_across_reservation_and_cancellation
# ---------------------------------------------------------------------------
def test_scheduling_reserves_the_assistance_dollars_without_exhausting_them():
    """The money ledger holds at 0 / 111007 / 388993 after one reservation.

    PRD §2.8: "Scheduling a dose moves the assistance amount applied to that dose
    out of `benefit_remaining_cents` and into `benefit_reserved_cents`."

    Design: Difficulty/compensating_invariant/assistance_benefit_conservation_across_reservation_and_cancellation
    """
    scenario = _assisted_practice()
    assert_money_ledger(scenario.refresh_enrollment(), used=0, reserved=0, remaining=500_000)
    assert scenario.enrollment["annual_benefit_cents"] == 500_000
    assert scenario.enrollment["status"] == "ACTIVE"

    appointment = schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))
    assert appointment["assistance_applied_cents"] == 111_007

    enrollment = scenario.refresh_enrollment()
    assert_money_ledger(enrollment, used=0, reserved=111_007, remaining=388_993)
    assert enrollment["status"] == "ACTIVE", (
        "remaining never hit zero, so no EXHAUSTED transition may fire"
    )


def test_cancellation_returns_the_dollars_to_remaining_not_to_used():
    """Cancelling a dose that was never dispensed restores the whole benefit.

    PRD §2.8: "Cancelling the dose returns the amount from
    `benefit_reserved_cents` to `benefit_remaining_cents`, and reversing an
    administration returns it from `benefit_used_cents` to
    `benefit_reserved_cents`."

    Design: Difficulty/compensating_invariant/assistance_benefit_conservation_across_reservation_and_cancellation
    """
    scenario = _assisted_practice()
    schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))

    cancelled = cancel_appointment(scenario, cancellation_reason="PATIENT_REQUEST")

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "PATIENT_REQUEST"

    enrollment = scenario.refresh_enrollment()
    assert_money_ledger(enrollment, used=0, reserved=0, remaining=500_000)
    assert enrollment["benefit_used_cents"] == 0, (
        "a cancelled dose was never dispensed, so the dollars return to remaining"
    )
    assert enrollment["benefit_used_cents"] != 111_007
    assert enrollment["status"] == "ACTIVE"


def test_the_cancellation_releases_the_unit_ledger_in_the_same_compensation():
    """Cancelling releases the authorization unit alongside the dollars.

    PRD §2.8: "Cancelling a scheduled dose moves the unit from `units_reserved`
    back into `units_remaining`."

    Design: Difficulty/compensating_invariant/assistance_benefit_conservation_across_reservation_and_cancellation
    """
    scenario = _assisted_practice()

    schedule_appointment(scenario, instant(2026, 8, 12, 9, 0, 0))
    assert_unit_ledger(scenario.refresh_authorization(), reserved=1, consumed=0, remaining=5)

    cancel_appointment(scenario, cancellation_reason="PATIENT_REQUEST")

    assert_unit_ledger(scenario.refresh_authorization(), reserved=0, consumed=0, remaining=6)
    assert_money_ledger(scenario.refresh_enrollment(), used=0, reserved=0, remaining=500_000)
