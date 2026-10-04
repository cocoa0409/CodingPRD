"""Numeric thresholds that switch on an exact value, on two independent scales.

The weight band switches between 39.9 and 40.0 kilogrammes; the derived handling
level switches at a screening score of exactly 70. A third claim pins an
endpoint reached from the other direction: a billing cycle that consumed nothing
bills zero rather than being refused.
"""

import pytest

from test_helpers import (
    advance_cycle,
    create_booking,
    create_breed_rule,
    create_incident,
    confirm_booking,
    read_member,
    read_pet,
    screen_booking,
    setup_completed_grooming_booking,
    setup_member_with_package,
    validate_error,
    ApiErrorId,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
GROOMER = TEST_USERS["grooming_staff_headers"]


def _screen_pair(api, world, health_condition_points=0, aggression_acknowledged=False):
    """Screen a fresh booking for the world's pet at a known condition score."""
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
    return screen_booking(
        api,
        store_id,
        booking,
        pet["version"],
        health_condition_points=health_condition_points,
        aggression_acknowledged=aggression_acknowledged,
    )


def test_weight_band_switches_between_39_9_and_40_0_kilogrammes(api):
    """40.0 kg earns the large band; 39.9 kg earns the medium band.

    PRD §3.2: "The third term comes from weight, at two bands: a pet weighing 40
    kilogrammes or more contributes 10 points, a pet weighing at least 25
    kilogrammes but less than 40 contributes 5 points, and anything lighter
    contributes nothing."
    PRD §3.2: "The four terms are added, with the pet term and the breed term
    each capped as described and the weight and condition terms contributing in
    full"
    PRD §3.2: "the `screening_score` is at least 40, the handling level is
    `SENSITIVE`"

    Design: Difficulty/boundary_precision_check/weight_band_and_risk_ceiling_boundaries
    """
    world = setup_completed_grooming_booking(api, pet=("Tiko", "CANINE", "Mixed Unknown", 40.0))
    heavy = _screen_pair(api, world, health_condition_points=30)

    assert heavy["screening_score"] == 40
    assert heavy["handling_level"] == "SENSITIVE"

    # The same breed one tenth of a kilogramme lighter drops to the medium band.
    world2 = setup_completed_grooming_booking(
        api, store_code="ST-0002", pet=("Pim", "CANINE", "Mixed Unknown", 39.9)
    )
    medium = _screen_pair(api, world2, health_condition_points=30)
    assert medium["screening_score"] == 35
    assert medium["handling_level"] == "STANDARD"


def test_screening_score_of_exactly_seventy_requires_acknowledgement_to_confirm(api):
    """70 points is HIGH_RISK and inclusive at the boundary.

    PRD §3.2: "A grooming booking whose `screening_score` stands at 70 or above
    may only be bay-confirmed when `aggression_acknowledged` is true; a
    confirmation attempt on a high-scoring booking whose aggression advisory was
    not acknowledged is refused with `ERR_HIGH_RISK_NOT_ACKNOWLEDGED`."
    PRD §3.2: "If that tier is `HIGH_RISK`, or if the `screening_score` is at
    least 70, the handling level is `HIGH_RISK`."
    PRD §3.2: "Both comparisons are inclusive at their boundary, which is why a
    `STANDARD` breed reaches `HIGH_RISK` at exactly 70 points"

    Design: Difficulty/boundary_precision_check/weight_band_and_risk_ceiling_boundaries
    """
    create_breed_rule(
        api, breed="German Shepherd", species="CANINE", risk_points=30, handling_tier="STANDARD"
    )
    world = setup_completed_grooming_booking(
        api, pet=("Rex", "CANINE", "German Shepherd", 38.0)
    )
    store_id = world["store"]["id"]
    create_incident(
        api, store_id, world["booking"]["id"], world["pet"]["id"],
        severity="SEVERE", incident_type="BITE", claim_amount_cents=25000,
    )
    screened = _screen_pair(api, world)
    # 40 pet + 25 breed (capped from 30) + 5 weight for 38.0 kg + 0 condition.
    assert screened["screening_score"] == 70
    assert screened["handling_level"] == "HIGH_RISK"

    resp = api.confirm_bay(
        store_id,
        screened["id"],
        {
            "expected_booking_version": screened["version"],
            "expected_pet_version": screened["pet_version"],
        },
        MANAGER,
    )
    validate_error(resp, ApiErrorId.HIGH_RISK_NOT_ACKNOWLEDGED.value)


def test_screening_score_below_seventy_confirms_without_acknowledgement(api):
    """65 points is SENSITIVE, and the confirmation is admissible unacknowledged.

    PRD §3.2: "Otherwise, if the tier is `SENSITIVE`, or if the `screening_score`
    is at least 40, the handling level is `SENSITIVE`."
    PRD §3.2: "A grooming booking whose `screening_score` stands at 70 or above
    may only be bay-confirmed when `aggression_acknowledged` is true"
    PRD §3.2: "Confirmation is a `StoreManager` act, and it is where the screening
    result is enforced."

    Design: Difficulty/boundary_precision_check/weight_band_and_risk_ceiling_boundaries
    """
    create_breed_rule(
        api, breed="German Shepherd", species="CANINE", risk_points=30, handling_tier="STANDARD"
    )
    world = setup_completed_grooming_booking(
        api,
        store_code="ST-0002",
        pet=("Rex Junior", "CANINE", "German Shepherd", 12.0),
    )
    store_id = world["store"]["id"]
    create_incident(
        api, store_id, world["booking"]["id"], world["pet"]["id"],
        severity="SEVERE", incident_type="BITE", claim_amount_cents=25000,
    )
    screened = _screen_pair(api, world)
    # 40 pet + 25 breed (capped) + 0 weight for 12.0 kg + 0 condition.
    assert screened["screening_score"] == 65
    assert screened["handling_level"] == "SENSITIVE"

    confirmed = confirm_booking(api, store_id, screened)
    assert confirmed["status"] == "BAY_CONFIRMED"


def test_a_cycle_that_consumed_nothing_bills_zero(api):
    """Zero consumption is inside the input set and bills 0.00 rather than failing.

    PRD §3.8: "A visit completed outside the cycle window contributes nothing to
    that cycle and is not deferred to a later one; the cost of a visit lands in
    the cycle during which it was consumed or it lands nowhere."
    PRD §3.8: "A new billing cycle record is created with a 1-based `cycle_index`
    identifying its position within the package, and it moves from `PENDING` to
    `BILLED` as part of the same operation"
    PRD §3.8: "The cycle's `tax_cents` is the cycle total multiplied by the tax
    rate and divided by one plus the tax rate, rounded half-up to two decimal
    places."

    Design: Difficulty/boundary_precision_check/empty_pool_and_zero_quantity_boundaries
    """
    world = setup_member_with_package(
        api, tier="UNLIMITED", state_code="FL", state_sales_tax_rate=0.07, billing_cycle_count=12
    )
    cycle = advance_cycle(
        api, world["store"]["id"], world["member"]["id"], world["package"],
        grooming_visits_consumed=0, vet_visits_consumed=0, vaccine_visits_consumed=0,
    )
    assert cycle["cycle_total_cents"] == pytest.approx(0.00, abs=0.01)
    assert cycle["tax_cents"] == pytest.approx(0.00, abs=0.01)
    assert cycle["overage_credit_cents"] == 0
    assert cycle["status"] == "BILLED"
    assert cycle["cycle_index"] == 1


def test_a_twelve_cycle_unlimited_package_bills_its_full_prepaid_value(api):
    """The included total is ten visits and the balance is the twelve-cycle total.

    PRD §3.8: "An `UNLIMITED` package includes six grooming visits, two
    veterinary visits and two vaccination visits per cycle."
    PRD §3.8: "The package's `grooming_visits_included`, `vet_visits_included` and
    `vaccine_visits_included` are set from the tier, and `included_visits_total`
    is their sum."
    PRD §2.9: "A member's `outstanding_balance_cents` equals the sum of
    `total_price_cents` across all of that member's service packages whose status
    is not `CANCELLED`"

    Design: Difficulty/boundary_precision_check/empty_pool_and_zero_quantity_boundaries
    """
    world = setup_member_with_package(
        api, tier="UNLIMITED", state_code="FL", state_sales_tax_rate=0.07, billing_cycle_count=12
    )
    package = world["package"]
    assert package["included_visits_total"] == 10
    assert package["grooming_visits_included"] == 6
    assert package["vet_visits_included"] == 2
    assert package["vaccine_visits_included"] == 2
    member = read_member(api, world["member"]["id"])
    assert member["outstanding_balance_cents"] == pytest.approx(154067.16, abs=0.01)