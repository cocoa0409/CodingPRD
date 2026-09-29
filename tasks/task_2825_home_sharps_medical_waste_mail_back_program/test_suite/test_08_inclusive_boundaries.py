"""Inclusive edges: a risk total landing exactly on the suspension threshold, and a
demand figure landing exactly on a container's capacity."""

from test_helpers import (
    SECOND_INTAKE_TECHNICIAN_USER_ID,
    acknowledge_kit,
    add_screened_kit_cycle,
    assert_enrollment,
    assert_kit,
    assert_patient_risk,
    assert_program_balances,
    issue_kit_for,
    read_enrollment,
    read_kit,
    read_patient,
    read_program,
    screen_shipment,
    seal_kit_for,
    setup_active_enrollment,
)


def _normalised_instant(value):
    """Split an ISO 8601 UTC instant into its second-precision head and a three-digit
    fractional tail so an omitted fraction and an explicit `.000` compare equal."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    body = value[:-1]
    head, _, fraction = body.partition(".")
    return head, (fraction + "000")[:3]


# --------------------------------------------------------------------------
# 15 + 45 lands exactly on the threshold of 60
# --------------------------------------------------------------------------
def _fifteen_points_banked_and_a_second_parcel_awaiting_screening(api):
    """Kit 1 rejected for MISSING_ABSORBENT (15 points) and kit 2 delivered but not yet
    screened. The clock never moves, so no event decays."""
    ctx = setup_active_enrollment(api)
    ctx["cycle_one"] = add_screened_kit_cycle(
        api, ctx, outcome="NON_CONFORMING", reason_code="MISSING_ABSORBENT"
    )
    ctx["cycle_two"] = add_screened_kit_cycle(
        api, ctx, screen=False, scheduled_intake_date="2026-08-11"
    )
    return ctx


def _reject_the_second_parcel_for_loose_sharps(api, ctx):
    return screen_shipment(
        api,
        ctx,
        shipment=ctx["cycle_two"]["shipment"],
        outcome="NON_CONFORMING",
        observed_gross_weight_grams=1520,
        reason_code="LOOSE_SHARPS_IN_BOX",
        technician_user_id=SECOND_INTAKE_TECHNICIAN_USER_ID,
    )


def test_01_a_score_of_exactly_sixty_suspends_the_patient(api):
    """15 plus 45 is exactly 60, and the threshold comparison is "at least 60", so the
    suspension fires on the edge rather than one point later.

    PRD 3.7: "Third, and only when that recomputed score reaches at least 60 while the patient is `ENROLLED`, the patient is suspended, which is itself a multi-hop cascade covered in §3.9."
    PRD 3.9: "When a conformance screening recomputes `screening_risk_score` to at least 60 while the patient is `ENROLLED`, the patient is suspended."

    Design: Difficulty/boundary_precision_check/risk_score_exactly_at_suspend_threshold_suspends_patient
    """
    ctx = _fifteen_points_banked_and_a_second_parcel_awaiting_screening(api)
    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=15,
        status="ENROLLED",
    )

    _reject_the_second_parcel_for_loose_sharps(api, ctx)

    assert_patient_risk(
        read_patient(api, ctx["patient"]["id"]),
        screening_risk_score=60,
        status="SUSPENDED",
    )


def test_02_the_suspension_instant_is_the_logical_clock(api):
    """`suspended_at` is stamped from the logical clock, which has not moved off
    2026-08-01T00:00:00Z at any point in the chain.

    PRD 3.9: "The first hop moves the patient `ENROLLED → SUSPENDED` and sets `suspended_at` to the current logical-clock instant."

    Design: Difficulty/boundary_precision_check/risk_score_exactly_at_suspend_threshold_suspends_patient
    """
    ctx = _fifteen_points_banked_and_a_second_parcel_awaiting_screening(api)

    _reject_the_second_parcel_for_loose_sharps(api, ctx)

    patient = read_patient(api, ctx["patient"]["id"])
    assert _normalised_instant(patient["suspended_at"]) == _normalised_instant(
        "2026-08-01T00:00:00Z"
    )


def test_03_the_edge_case_still_fires_the_whole_downstream_cascade(api):
    """A threshold met exactly is a threshold met: the enrollment pauses, its due date
    clears, and the two parcels already in the facility's hands are left at RECEIVED.

    PRD 3.9: "The second hop moves every enrollment of that patient whose status is `ACTIVE` to `PAUSED`."
    PRD 3.9: "The third hop applies to each of those newly paused enrollments: its `next_autoship_due_date` is cleared to null, and every kit of that enrollment whose status is `ISSUED` moves to `VOIDED` with `void_reason` set to `ENROLLMENT_PAUSED` — kits already in `ACTIVE_FILLING` are physically in the patient's hands and are pointedly **not** voided."

    Design: Difficulty/boundary_precision_check/risk_score_exactly_at_suspend_threshold_suspends_patient
    """
    ctx = _fifteen_points_banked_and_a_second_parcel_awaiting_screening(api)

    _reject_the_second_parcel_for_loose_sharps(api, ctx)

    assert_enrollment(
        read_enrollment(api, ctx["enrollment"]["id"]),
        status="PAUSED",
        next_autoship_due_date=None,
    )
    assert_kit(read_kit(api, ctx["cycle_one"]["kit"]["id"]), status="RECEIVED")
    assert_kit(read_kit(api, ctx["cycle_two"]["kit"]["id"]), status="RECEIVED")
    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=2930,
        committed_cents=0,
    )


# --------------------------------------------------------------------------
# 99.22857... ceilings to exactly one container's capacity
# --------------------------------------------------------------------------
_IRIS = {
    "full_name": "Iris Vega",
    "therapy_type": "INSULIN_PEN_NEEDLES",
    "weekly_sharps_count": 4,
    "contact_email": "iris@example.com",
}
_LONG_CADENCE = {"cadence_days": 151, "kits_authorized": 5}


def _kit_sized_at_the_capacity_edge(api):
    """4 sharps a week at 1 unit each over a 151-day cadence with the 15 percent margin
    is 99.22857..., which ceilings to exactly ONE_QUART's capacity of 100."""
    ctx = setup_active_enrollment(
        api, patient_overrides=_IRIS, enrollment_overrides=_LONG_CADENCE
    )
    issue_kit_for(api, ctx)
    return ctx


def test_04_the_single_ceiling_is_applied_to_the_final_quotient(api):
    """4 x 1 x 151 x 115 / 700 is 99.22857..., and the one rounding-up step takes it to
    100; a floor or a truncation would leave 99.

    PRD 3.4: "The computation multiplies the weekly count by that factor, then by the number of cadence days, then by 115, divides the product by 700, and rounds the single resulting quotient up to the next whole number."
    PRD 3.4: "The per-item factor counts how many catalogue units one discarded item consumes: an insulin pen needle counts as 1 unit, an insulin syringe as 2, an autoinjector pen as 6, an infusion set as 9, and a lancet as 1."

    Design: Difficulty/boundary_precision_check/container_sizing_at_exact_capacity_boundary_with_single_ceiling
    """
    ctx = _kit_sized_at_the_capacity_edge(api)

    assert_kit(read_kit(api, ctx["kit"]["id"]), required_units=100)


def test_05_capacity_equal_to_demand_still_qualifies_as_a_candidate(api):
    """ONE_QUART holds exactly 100 units, and the capacity condition is inclusive, so
    the cheapest container wins rather than the 2600-cent TWO_GALLON.

    PRD 3.4: "A catalogue row is a **candidate** for this kit when four conditions all hold: its volume is at most the patient's state cap `max_container_volume_liters`, inclusively; its capacity is at least `required_units`, inclusively; if the patient's therapy is `INFUSION_SETS`, its volume is at least 7.6 litres; and if the patient's therapy is `LANCETS_ONLY`, its volume is at most 11.4 litres."
    PRD 3.4: "`ONE_QUART` holds 0.9 litres, 100 units, and costs 1450 cents. `TWO_GALLON` holds 7.6 litres, 800 units, and costs 2600 cents."

    Design: Difficulty/boundary_precision_check/container_sizing_at_exact_capacity_boundary_with_single_ceiling
    """
    ctx = _kit_sized_at_the_capacity_edge(api)

    assert_kit(
        read_kit(api, ctx["kit"]["id"]),
        container_size="ONE_QUART",
        capacity_units=100,
        volume_liters=0.9,
        provisional_cost_cents=1465,
    )


def test_06_a_fill_exactly_at_capacity_is_not_an_overfill(api):
    """Declaring 100 units into a 100-unit container sits on the inclusive edge of the
    overfill guard, so the seal succeeds.

    PRD 3.5: "Finally `fill_units` must not exceed the kit's `capacity_units`; an overfilled sharps container is a needlestick hazard for everyone who handles the parcel downstream, so this check lives in the safety band and its refusal is `ERR_CONTAINER_OVERFILLED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/container_sizing_at_exact_capacity_boundary_with_single_ceiling
    """
    ctx = _kit_sized_at_the_capacity_edge(api)
    acknowledge_kit(api, ctx)

    sealed = seal_kit_for(api, ctx, fill_units=100, sealed_gross_weight_grams=1500)

    assert_kit(sealed, status="SEALED", fill_units=100)


def test_07_the_two_date_derivations_cross_the_year_boundary(api):
    """A 151-day cadence from 2026-08-01 lands the auto-ship date on 2026-12-30, and the
    extra 14-day grace pushes the seal deadline into the next year.

    PRD 3.4: "Its `seal_deadline_date` is the UTC calendar date of `issued_at` advanced by the enrollment's `cadence_days` plus a 14-day grace period; a kit still unsealed after that date is a late kit for audit purposes."
    PRD 3.4: "*Fifth*, the enrollment's `next_autoship_due_date` is set to the UTC calendar date of `issued_at` advanced by `cadence_days`, its `kits_issued` is recomputed, and its `version` is incremented by 1."

    Design: Difficulty/boundary_precision_check/container_sizing_at_exact_capacity_boundary_with_single_ceiling
    """
    ctx = _kit_sized_at_the_capacity_edge(api)

    assert_kit(read_kit(api, ctx["kit"]["id"]), seal_deadline_date="2027-01-13")
    assert_enrollment(
        read_enrollment(api, ctx["enrollment"]["id"]),
        next_autoship_due_date="2026-12-30",
    )


def test_08_the_cheaper_container_reserves_the_cheaper_figure(api):
    """Because the inclusive comparison kept the kit at ONE_QUART, the program reserves
    1465 cents rather than a two-gallon container's price.

    PRD 3.4: "*Third*, a `RESERVATION` ledger entry for the positive `provisional_cost_cents` is appended at the next `sequence_no` and the program's `reserved_cents` rises by that amount."
    PRD 2.9: "`available_cents` is `funding_ceiling_cents` less `reserved_cents` less `committed_cents`, recomputed after every append."

    Design: Difficulty/boundary_precision_check/container_sizing_at_exact_capacity_boundary_with_single_ceiling
    """
    ctx = _kit_sized_at_the_capacity_edge(api)

    assert_program_balances(
        read_program(api, ctx["sponsorship_program"]["id"]),
        reserved_cents=1465,
        committed_cents=0,
        available_cents=498535,
        status="ACTIVE",
    )
