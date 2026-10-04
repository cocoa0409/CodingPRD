"""Grooming risk screening: the two nested ceilings inside the score formula.

The score has four weighted terms and two of them are capped — the pet's own
history at 100 points and the matched breed rule's contribution at 25 points —
so the value a booking reports is not the naive sum of its inputs. A second
claim in this file checks that the matched breed rule's tier acts as a floor on
the derived handling level rather than as a cap.
"""

from test_helpers import (
    create_booking,
    create_breed_rule,
    create_incident,
    get_success_data,
    read_pet,
    screen_booking,
    setup_completed_grooming_booking,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


def _second_booking_and_screen(api, world, health_condition_points=0):
    """Raise a fresh grooming booking for the same pet and screen it."""
    store_id = world["store"]["id"]
    pet = read_pet(api, world["pet"]["id"])
    booking = create_booking(
        api,
        store_id,
        world["bay"]["id"],
        pet["id"],
        pet["version"],
        service_type="GROOMING",
        starts_at="2026-07-05T09:00:00Z",
        ends_at="2026-07-05T10:00:00Z",
    )
    screened = screen_booking(
        api,
        store_id,
        booking,
        pet["version"],
        health_condition_points=health_condition_points,
        aggression_acknowledged=True,
    )
    return pet, screened


def test_screening_caps_the_breed_contribution_at_twenty_five(api):
    """A 30-point breed rule contributes only 25, and the pet term caps at 100.

    PRD §3.2: "The second term comes from the breed handling rule matched to the
    pet, where the match is case-insensitive on the breed name and must also
    agree on species; an unmatched breed contributes zero."
    PRD §3.2: "That breed contribution is then subject to a soft ceiling of 25
    points: if the rule's `risk_points` is 25 or fewer the full amount is used,
    and if it exceeds 25 the contribution is capped at 25."
    PRD §3.2: "The third term comes from weight, at two bands: a pet weighing 40
    kilogrammes or more contributes 10 points, a pet weighing at least 25
    kilogrammes but less than 40 contributes 5 points, and anything lighter
    contributes nothing."

    Design: Difficulty/combinatorial_formula/grooming_screening_score_nested_caps
    """
    create_breed_rule(
        api,
        breed="German Shepherd",
        species="CANINE",
        risk_points=30,
        handling_tier="HIGH_RISK",
        allowed_for_grooming=True,
    )
    world = setup_completed_grooming_booking(
        api, pet=("Rex", "CANINE", "German Shepherd", 38.0)
    )
    store_id = world["store"]["id"]
    # One SEVERE incident applies 40 risk points, which is the pet-history term.
    create_incident(
        api,
        store_id,
        world["booking"]["id"],
        world["pet"]["id"],
        severity="SEVERE",
        incident_type="BITE",
        claim_amount_cents=25000,
    )
    pet, screened = _second_booking_and_screen(api, world)

    assert pet["risk_score"] == 40
    # 40 pet points (uncapped, below 100) + 25 breed points (capped from 30)
    # + 5 weight-band points for 38.0 kg + 0 condition points.
    assert screened["screening_score"] == 70
    assert screened["status"] == "SCREENED"


def test_screening_score_is_the_capped_sum_and_the_screening_row_records_it(api):
    """The recorded screening carries the same capped total the booking reports.

    PRD §3.2: "The four terms are added, with the pet term and the breed term
    each capped as described and the weight and condition terms contributing in
    full, and the resulting total is then clamped into the range from zero to
    160"
    PRD §3.2: "Recording the screening also appends an immutable
    `GroomingRiskScreening` row capturing the booking, the `risk_total`, the
    `health_condition_points`, the derived `handling_level`, the
    `aggression_acknowledged` flag and the `recorded_at` instant"

    Design: Difficulty/combinatorial_formula/grooming_screening_score_nested_caps
    """
    create_breed_rule(
        api,
        breed="German Shepherd",
        species="CANINE",
        risk_points=30,
        handling_tier="STANDARD",
        allowed_for_grooming=True,
    )
    world = setup_completed_grooming_booking(
        api, pet=("Rex", "CANINE", "German Shepherd", 38.0)
    )
    store_id = world["store"]["id"]
    create_incident(
        api,
        store_id,
        world["booking"]["id"],
        world["pet"]["id"],
        severity="MODERATE",
        incident_type="PET_INJURY",
        claim_amount_cents=20000,
    )
    pet, screened = _second_booking_and_screen(api, world, health_condition_points=30)

    assert pet["risk_score"] == 25
    # 25 pet + 25 breed (capped from 30) + 5 weight + 30 cardiac condition.
    assert screened["screening_score"] == 85

    screenings = get_success_data(
        api.list_booking_risk_screenings(store_id, screened["id"], ADMIN, {"limit": 100})
    )
    assert len(screenings) == 1, f"expected exactly one screening row, got {len(screenings)}"
    assert screenings[0]["risk_total"] == 85
    assert screenings[0]["health_condition_points"] == 30
    assert screenings[0]["aggression_acknowledged"] is True


def test_screening_handling_level_is_a_breed_tier_floor_not_a_ceiling(api):
    """A HIGH_RISK breed is HIGH_RISK at any score, not only at 70 points.

    PRD §3.2: "The screening concludes by deriving a `handling_level` from the
    score and from the matched breed rule's tier, and the two inputs are combined
    by treating the breed tier as a floor rather than a ceiling."
    PRD §3.2: "If that tier is `HIGH_RISK`, or if the `screening_score` is at
    least 70, the handling level is `HIGH_RISK`."
    PRD §3.2: "Both comparisons are inclusive at their boundary, which is why a
    `STANDARD` breed reaches `HIGH_RISK` at exactly 70 points, while a
    `HIGH_RISK` breed is `HIGH_RISK` even at a screening score of zero."

    Design: Difficulty/combinatorial_formula/grooming_screening_score_nested_caps
    """
    create_breed_rule(
        api,
        breed="Chow Chow",
        species="CANINE",
        risk_points=0,
        handling_tier="HIGH_RISK",
        allowed_for_grooming=True,
    )
    world = setup_completed_grooming_booking(api, pet=("Lark", "CANINE", "Chow Chow", 12.0))
    pet, screened = _second_booking_and_screen(api, world)

    # 0 pet + 0 breed + 0 weight (12.0 kg) + 0 condition — far below 70.
    assert screened["screening_score"] == 0
    assert screened["handling_level"] == "HIGH_RISK"