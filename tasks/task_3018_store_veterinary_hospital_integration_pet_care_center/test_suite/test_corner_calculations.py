"""Weighted and aggregated calculations at their inputs' edges."""

import pytest

from test_helpers import (
    ApiErrorId,
    advance_cycle,
    confirm_booking,
    create_breed_rule,
    get_success_data,
    read_member,
    read_store,
    setup_completed_grooming_booking,
    setup_member_with_package,
    setup_store_at_capacity,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
GROOMER = TEST_USERS["grooming_staff_headers"]


def test_a_sensitive_breed_rule_lifts_a_zero_score_pet_to_sensitive(api):
    """The breed tier is a floor, so the score threshold is never consulted.

    PRD §3.2: "The breed rule's `handling_tier` is taken where the breed matches
    case-insensitively, and defaults to `STANDARD` when no rule matches."
    PRD §3.2: "Otherwise, if the tier is `SENSITIVE`, or if the `screening_score`
    is at least 40, the handling level is `SENSITIVE`."
    PRD §3.2: "The four terms are added, with the pet term and the breed term each
    capped as described and the weight and condition terms contributing in full"

    Design: Corner/calculations/handling_level_floor_from_breed_tier_with_zero_score
    """
    from test_helpers import create_booking, read_pet, screen_booking

    create_breed_rule(
        api, breed="Chow Chow", species="CANINE", risk_points=0, handling_tier="SENSITIVE"
    )
    world = setup_completed_grooming_booking(api, pet=("Lark", "CANINE", "Chow Chow", 26.0))
    store_id = world["store"]["id"]
    pet = read_pet(api, world["pet"]["id"])
    booking = create_booking(
        api, store_id, world["bay"]["id"], pet["id"], pet["version"],
        service_type="GROOMING", starts_at="2026-07-05T09:00:00Z", ends_at="2026-07-05T10:00:00Z",
    )
    screened = screen_booking(
        api, store_id, booking, pet["version"], health_condition_points=0,
        aggression_acknowledged=False,
    )
    # 0 pet + 0 breed + 5 weight-band points for 26.0 kg + 0 condition.
    assert screened["screening_score"] == 5
    assert screened["handling_level"] == "SENSITIVE"

    # 5 is far below the 70-point acknowledgement threshold, so the confirmation
    # is admissible even though the advisory was not acknowledged.
    confirmed = confirm_booking(api, store_id, screened)
    assert confirmed["status"] == "BAY_CONFIRMED"


def test_hospital_occupancy_counts_scheduled_encounters_while_the_posture_counts_occupied_ones(api):
    """Occupancy and the occupied ratio are two different quantities.

    PRD §2.7: "Each store carries a `hospital_capacity`, the maximum number of
    patients its in-store veterinary hospital will hold at once, and a
    `hospital_occupancy`, recomputed as the number of that store's encounters
    currently in `SCHEDULED`, `CHECKED_IN` or `IN_EXAM`."
    PRD §2.7: "A scheduled appointment that has not yet checked in raises
    `hospital_occupancy` but not the occupied count, so a store can be full on
    paper while an examination room stands empty."
    PRD §2.7: "The posture decision is made by dividing the occupied count by the
    store's `hospital_capacity` and comparing that ratio against three boundaries,
    inclusive at each: a ratio of at least 0.80 escalates the store to
    `RESTRICTED`"

    Design: Corner/calculations/occupancy_recalculation_refuses_a_capacity_one_overbooking
    """
    world = setup_store_at_capacity(api, hospital_capacity=10, encounter_count=8)
    store_id = world["store"]["id"]
    store = read_store(api, store_id)

    # Eight scheduled encounters against a capacity of ten raise occupancy to
    # eight, while the occupied count — SCHEDULED does not count — stays at zero,
    # so the posture stays OPEN.
    assert store["hospital_occupancy"] == 8
    assert store["hospital_posture"] == "OPEN"

    from test_helpers import bump_occupancy

    bumped = bump_occupancy(api, store_id, store["version"], 1)
    # One of the eight moves into CHECKED_IN, so the broader three-state count is
    # unchanged while the occupied ratio is still far below every boundary.
    assert bumped["hospital_occupancy"] == 8
    assert bumped["hospital_posture"] == "OPEN"

    # PRD §3.4: "A hospital booking may be created at exactly one occupancy slot
    # above capacity and no more; a further booking past that is refused with
    # `ERR_HOSPITAL_AT_CAPACITY`." The one-slot allowance is exhausted by a store
    # already holding capacity-plus-one live encounters.
    from test_helpers import factories, validate_error

    full = setup_store_at_capacity(
        api, store_code="ST-0002", hospital_capacity=10, encounter_count=11
    )
    full_store = read_store(api, full["store"]["id"])
    assert full_store["hospital_occupancy"] == 11

    refused = api.create_encounter(
        full["store"]["id"],
        factories.encounter_payload(
            pet_id=full["pet"]["id"], scheduled_at="2026-08-30T09:00:00Z"
        ),
        TEST_USERS["veterinary_staff_headers"],
    )
    validate_error(refused, ApiErrorId.HOSPITAL_AT_CAPACITY.value)
    # The refusal changed nothing: the encounter counter is still the one that
    # was already there.
    assert read_store(api, full["store"]["id"])["hospital_occupancy"] == 11


def test_the_posture_ladder_sits_at_the_restricted_rung_without_escalating_further(api):
    """Eight occupied against a capacity of ten is the inclusive RESTRICTED boundary.

    PRD §2.7: "The comparisons are inclusive, so a capacity of 10 with 8 patients
    occupied is `RESTRICTED`, and 7 occupied is `OPEN`; a store at 8 occupied
    stays `RESTRICTED` until it falls to 7."
    PRD §2.7: "A ratio strictly between 0.70 and 0.80 leaves the posture where it
    is, which is deliberate — the gap between the escalation boundary and the
    release boundary is hysteresis"
    PRD §2.7: "A scheduled appointment that has not yet checked in raises
    `hospital_occupancy` but not the occupied count"

    Design: Corner/calculations/occupancy_recalculation_refuses_a_capacity_one_overbooking
    """
    from test_helpers import bump_occupancy

    world = setup_store_at_capacity(api, hospital_capacity=10, encounter_count=8)
    store_id = world["store"]["id"]
    store = read_store(api, store_id)

    # Eight of the ten scheduled encounters move into CHECKED_IN together, which
    # puts the occupied ratio at exactly 0.80 — the inclusive escalation rung.
    restricted = bump_occupancy(api, store_id, store["version"], 8)
    assert restricted["hospital_occupancy"] == 8
    assert restricted["hospital_posture"] == "RESTRICTED"


def test_a_cycle_bills_only_the_visits_consumed_inside_it(api):
    """A visit consumed in the first cycle is not deferred into the second.

    PRD §3.8: "The cycle's charge is computed from the visits consumed inside
    that cycle window alone: the grooming visits consumed in the cycle multiplied
    by 2500 cents"
    PRD §3.8: "A visit completed outside the cycle window contributes nothing to
    that cycle and is not deferred to a later one; the cost of a visit lands in
    the cycle during which it was consumed or it lands nowhere."
    PRD §3.8: "A new billing cycle record is created with a 1-based `cycle_index`
    identifying its position within the package"

    Design: Corner/calculations/cycle_bill_excludes_visits_consumed_outside_the_cycle
    """
    world = setup_member_with_package(
        api, tier="PLUS", state_code="TX", state_sales_tax_rate=0.0,
        billing_cycle_count=3, monthly_fee_cents=5000,
    )
    store_id = world["store"]["id"]
    member_id = world["member"]["id"]

    first = advance_cycle(api, store_id, member_id, world["package"], grooming_visits_consumed=1)
    assert first["cycle_total_cents"] == pytest.approx(2500.00, abs=0.01)
    assert first["tax_cents"] == pytest.approx(0.00, abs=0.01)
    assert first["cycle_index"] == 1

    package = get_success_data(api.get_package(world["package"]["id"], ADMIN))
    assert package["cycles_consumed"] == 1
    assert package["consumed_visits"] == 1

    # The first cycle's visit is charged to the first cycle and nowhere else, so
    # a second cycle that consumed nothing bills nothing.
    second = advance_cycle(api, store_id, member_id, package)
    assert second["cycle_total_cents"] == pytest.approx(0.00, abs=0.01)
    assert second["cycle_index"] == 2

    member = read_member(api, member_id)
    # Three prepaid cycles at 5000 each is 15000; only the first cycle was billed.
    assert member["outstanding_balance_cents"] == pytest.approx(12500.00, abs=0.01)


def test_a_zero_fee_package_falls_back_to_the_tier_default(api):
    """A submitted fee of zero means the tier's default applies outright.

    PRD §3.8: "A submitted fee of zero means the default applies: an `ESSENTIAL`
    package defaults to 3999 cents per month, a `PLUS` package to 6999 and an
    `UNLIMITED` package to 11999."
    PRD §3.8: "A non-zero fee does not adjust the default, it replaces it
    entirely, so a submitted fee of 5000 cents on a `PLUS` package bills 5000
    cents per month rather than some blend of the two figures."
    PRD §3.8: "An `ESSENTIAL` package includes one grooming visit and one
    vaccination visit per cycle and no veterinary visit."

    Design: Corner/calculations/cycle_bill_excludes_visits_consumed_outside_the_cycle
    """
    default_world = setup_member_with_package(
        api, tier="ESSENTIAL", state_code="CA", state_sales_tax_rate=0.0,
        billing_cycle_count=1, monthly_fee_cents=0,
    )
    assert default_world["package"]["monthly_total_cents"] == pytest.approx(3999.00, abs=0.01)
    assert default_world["package"]["grooming_visits_included"] == 1
    assert default_world["package"]["vet_visits_included"] == 0
    assert default_world["package"]["vaccine_visits_included"] == 1
    assert default_world["package"]["included_visits_total"] == 2

    override_world = setup_member_with_package(
        api, store_code="ST-0002", tier="ESSENTIAL", state_code="CA", state_sales_tax_rate=0.0,
        billing_cycle_count=1, monthly_fee_cents=5000,
    )
    # The non-zero fee replaces the default rather than blending with it.
    assert override_world["package"]["monthly_total_cents"] == pytest.approx(5000.00, abs=0.01)