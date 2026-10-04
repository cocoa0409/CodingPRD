"""The live planning volume and the hub posture it drives."""
import pytest

from test_helpers import (
    CONGESTION_THRESHOLD_GRAMS,
    cancel_aircraft,
    clear_contingency,
    create_package,
    declare_contingency,
    get_hub,
    get_package,
    land_second_aircraft,
    setup_night_with_second_aircraft,
)

AC2_UNLOAD_MINUTE = 1405


@pytest.fixture
def night():
    return setup_night_with_second_aircraft()


def test_both_live_rows_drive_the_consolidated_posture(night):
    """PRD §2.6: "The hub's `live_planned_package_total` is the sum of
    `planned_weight_grams` over every package on that hub whose `handling_status` is
    neither `DIVERTED` nor `HOLD_AT_HUB` and whose `commitment_status` is neither
    `VOIDED` nor `UPGRADED_HELD`."
    PRD §2.5: "Above the congestion threshold but at or below the lockdown threshold, the
    hub reads `CONGESTED`;"

    Design: Difficulty/dual_variant_calc/hub_posture_settled_vs_provisional_row_set_variant
    """
    land_second_aircraft(night, inbound_weight_grams=400000,
                         unload_minutes=AC2_UNLOAD_MINUTE, complete=True)
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-HP-0001",
                   planned_weight_grams=200000, dimension_weight_grams=200000)
    create_package(night["hub_id"], night["ac2_id"], tracking_number="1Z-HP-0002",
                   destination_hub_code="ORD",
                   planned_weight_grams=400000, dimension_weight_grams=400000)

    hub = get_hub(night["hub_id"])
    assert hub["live_planned_package_total"] == 600000
    assert hub["live_planned_package_total"] > CONGESTION_THRESHOLD_GRAMS, (
        "600000 is above the floored congestion threshold of 360000"
    )
    assert hub["posture"] == "CONGESTED"


def test_one_row_leaving_the_live_set_reopens_the_hub(night):
    """PRD §2.6: "a package leaves the live total the instant it is diverted or parked
    at the hub, and it returns the instant it is cleared back."
    PRD §2.5: "at or below the congestion threshold it reads `OPEN`."

    Design: Difficulty/dual_variant_calc/hub_posture_settled_vs_provisional_row_set_variant
    """
    land_second_aircraft(night, inbound_weight_grams=400000,
                         unload_minutes=AC2_UNLOAD_MINUTE, complete=True)
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-HP-0003",
                   planned_weight_grams=200000, dimension_weight_grams=200000)
    second = create_package(night["hub_id"], night["ac2_id"], tracking_number="1Z-HP-0004",
                            destination_hub_code="ORD",
                            planned_weight_grams=400000, dimension_weight_grams=400000)
    assert get_hub(night["hub_id"])["posture"] == "CONGESTED"

    # Cancelling the inbound aircraft parks every package aboard on the hold,
    # so the 400000-gram row leaves the live set.
    cancel_aircraft(night["ac2_id"], "MECHANICAL")

    hub = get_hub(night["hub_id"])
    held = get_package(second["id"])
    assert hub["live_planned_package_total"] == 200000, (
        "only the package that is still live counts"
    )
    assert hub["posture"] == "OPEN"
    assert held["commitment_status"] == "UPGRADED_HELD"
    assert held["handling_status"] == "HOLD_AT_HUB"
    assert hub["contingency_mode"] is False


def test_declared_volume_that_has_not_landed_does_not_move_posture(night):
    """PRD §2.6: "read while a bank is still `EN_ROUTE` or `UNLOADING`, it counts only
    packages that have already been recorded, so a hub may read `OPEN` or `CONGESTED`
    before the bank's volume has landed."

    Design: Difficulty/dual_variant_calc/hub_posture_settled_vs_provisional_row_set_variant
    """
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-HP-0005",
                   planned_weight_grams=200000, dimension_weight_grams=200000)
    hub = get_hub(night["hub_id"])
    assert hub["live_planned_package_total"] == 200000
    assert hub["posture"] == "OPEN", (
        "the second aircraft is still SCHEDULED, so its declared 400000 grams are not counted"
    )


def test_clearing_the_contingency_restores_the_volume_driven_branch(night):
    """PRD §2.5: "While `contingency_mode` is true, posture is `LOCKDOWN` for every
    volume, including zero, and the volume-driven branch is restored only when the
    contingency is cleared."

    Design: Difficulty/dual_variant_calc/hub_posture_settled_vs_provisional_row_set_variant
    """
    create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-HP-0006",
                   planned_weight_grams=200000, dimension_weight_grams=200000)
    assert get_hub(night["hub_id"])["posture"] == "OPEN"

    declared = declare_contingency(night["hub_id"])
    assert declared["posture"] == "LOCKDOWN", "contingency dominates regardless of volume"

    cleared = clear_contingency(night["hub_id"])
    assert cleared["posture"] == "OPEN", (
        "with the mode false the posture returns to OPEN purely as a function of live volume"
    )
    assert get_hub(night["hub_id"])["live_planned_package_total"] == 200000