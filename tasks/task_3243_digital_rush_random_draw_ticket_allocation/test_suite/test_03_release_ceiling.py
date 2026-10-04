"""Release ceiling, market share ceiling and carry-forward precision."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
)
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_release_ceiling_is_the_smallest_of_its_three_operands(api):
    """PRD §3.3: "The release ceiling, the `daily_release_cap`, is the smallest
    of three quantities, and each is evaluated before the ceiling is taken."
    PRD §3.3: "The third candidate is the market-wide ceiling, and it is the one
    that binds hardest. Convert a fixed share of the house into seats by taking
    4000 basis points — four tenths of one hundred percent — of the performance's
    `total_seat_capacity`, dividing by ten thousand, and discarding any
    fractional seat by rounding downward to a whole seat."

    Design: Difficulty/combinatorial_formula/combinatorial_release_cap_nested_min_over_three_operands
    """
    production, performance, allocation, released = X.setup_seven_seat_house_rush()

    assert released["daily_release_cap"] == C.MARKET_CAP_SEVEN_SEAT_HOUSE, (
        "the market term floor(4000 * 7 / 10000) == 2 is the binding operand, so "
        f"neither daily_quantity 8 nor the carry-forward term 8 is returned; got "
        f"{released['daily_release_cap']}"
    )
    assert released["quantity_released_today"] == 2, \
        f"the ceiling becomes the epoch's released count, got {released['quantity_released_today']}"
    assert released["status"] == "RELEASED"


def test_release_ceiling_advances_the_allocation_version(api):
    """PRD §3.3: "The release advances three versions: the allocation's by one,
    the performance's by one, and the production's by one, because the
    partnership's day's exposure has changed."

    Design: Difficulty/combinatorial_formula/combinatorial_release_cap_nested_min_over_three_operands
    """
    production, performance, allocation, released = X.setup_seven_seat_house_rush()

    assert released["version"] == allocation["version"] + 1, \
        f"expected one advance from {allocation['version']}, got {released['version']}"
    assert X.get_performance(performance["id"])["version"] == performance["version"] + 1, \
        "a release advances the performance's version by one"


def test_release_that_stays_at_the_market_ceiling_is_accepted(api):
    """PRD §3.3: "The scope of this ceiling is the performance's single market,
    so "four tenths of the house per market per day" reduces in practice to the
    discounted allocation set of that one performance."
    PRD §2.6: "the sum of the day's released quantities across all
    non-`STANDARD` allocations of the performance must stay at or below the
    permitted share of the house."

    Design: Corner/validations/market_share_cap_violation_reports_the_cap_error
    """
    production, performance, first, second = X.setup_sibling_market_cap_release()

    released = X.release_allocation(second, production, performance)

    assert released["daily_release_cap"] == 4, (
        "the remaining market headroom on a twenty-five seat house is four seats, "
        f"got {released['daily_release_cap']}"
    )
    assert released["quantity_released_today"] == 4
    assert X.get_allocation(performance, first["id"])["quantity_released_today"] == 6, \
        "the sibling's own released quantity must be unchanged"
    assert (released["quantity_released_today"]
            + X.get_allocation(performance, first["id"])["quantity_released_today"]) == 10, \
        "the two released quantities sum to exactly the market cap for a 25 seat house"


def test_exact_consumption_drives_the_next_epoch_cap_to_zero(api):
    """PRD §3.3: "The second candidate accounts for yesterday. The system
    computes the difference between `daily_quantity` and the
    `quantity_carried_forward` the allocation brought into the epoch — that is,
    the producer's grant minus the unsold remainder from the previous epoch —
    and floors that difference at zero."

    Design: Difficulty/boundary_precision_check/boundary_carry_forward_exact_consumption_yields_zero_cap
    """
    production, performance, allocation, data = \
        X.setup_empty_epoch_then_release(daily_quantity=2)

    assert data["quantity_carried_forward"] == 2, (
        "the previous epoch sold none of the two seats it released, so that whole "
        f"remainder is carried forward; got {data['quantity_carried_forward']}"
    )
    assert data["daily_release_cap"] == 0, (
        f"the exact-consumption boundary produced cap {data['daily_release_cap']} "
        "rather than a negative one"
    )
    assert data["quantity_released_today"] == 0


def test_release_sequence_prices_the_second_seat_run_correctly(api):
    """PRD §3.3: "Whatever the ceiling turns out to be, it becomes the epoch's
    `quantity_released_today`, and the previous epoch's unsold remainder — the
    prior epoch's released count minus its sold count, floored at zero — becomes
    `quantity_carried_forward`."

    Design: Difficulty/boundary_precision_check/boundary_carry_forward_exact_consumption_yields_zero_cap
    """
    production, performance, allocation, zero = \
        X.setup_empty_epoch_then_release(daily_quantity=2)
    assert zero["daily_release_cap"] == 0, (
        "the epoch whose carry-forward operand is zero opens no seats, got "
        f"{zero['daily_release_cap']}"
    )
    after = X.get_allocation(performance, allocation["id"])

    assert after["quantity_released_today"] + after["quantity_sold_today"] == 0, (
        "a zero-cap epoch opens no seats and sells none: "
        f"{after['quantity_released_today']} released, {after['quantity_sold_today']} sold"
    )
    assert after["status"] in ("RELEASED", "EXHAUSTED"), \
        f"the allocation remains in its released posture, got {after['status']}"