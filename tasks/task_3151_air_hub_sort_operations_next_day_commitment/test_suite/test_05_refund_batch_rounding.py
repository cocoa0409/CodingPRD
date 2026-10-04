"""Nested rounding of the money-back batch total, and the rate/surcharge composition."""
import pytest

from test_helpers import (
    CLOCK_1500,
    create_package,
    get_refund_summary,
    record_failure,
    set_clock,
    setup_night,
)
from test_helpers import api_client as api
from test_helpers import TEST_USERS as H


@pytest.fixture
def night():
    ctx = setup_night()
    set_clock(CLOCK_1500)
    return ctx


def _package(night, tracking_number: str, weight: int, service_level: str = "NEXT_DAY_AIR",
             commodity_class: str = "GENERAL"):
    return create_package(night["hub_id"], night["ac1_id"], tracking_number=tracking_number,
                          commodity_class=commodity_class, service_level=service_level,
                          planned_weight_grams=weight, dimension_weight_grams=weight)


def test_each_failure_rounds_before_the_batch_sums(night):
    """PRD §3.11: "Rounding each failure first and summing afterwards is the required
    order; summing first and rounding once at the end is forbidden and produces a
    different number."
    PRD §3.11: "the pinned order yields 96270 per failure for a total of 192540, while
    the forbidden order yields 192539."

    Design: Difficulty/combinatorial_formula/refund_batch_nested_rounding_order_pinned
    """
    first = _package(night, "1Z-RB-0001", 250050)
    second = _package(night, "1Z-RB-0002", 250050, )
    fail_a = record_failure(night["hub_id"], first["id"], "SORT_MISS", 1500)
    record_failure(night["hub_id"], second["id"], "SORT_MISS", 1500)

    assert fail_a["refund_amount_cents"] == 96270, (
        "gross round_half_up(250.050 * 550) == 137528, provisional "
        "round_half_up(137528 * 0.70) == round_half_up(96269.6) == 96270"
    )
    summary = get_refund_summary(night["hub_id"])
    assert summary["batch_total_cents"] == 192540
    assert summary["batch_total_cents"] != 192539, "the forbidden sum-then-round reading"


def test_finalizing_one_failure_moves_the_batch_to_the_mixed_figure(night):
    """PRD §3.11: "a failure that has been finalized pays the gross figure in full."

    Design: Difficulty/combinatorial_formula/refund_batch_nested_rounding_order_pinned
    """
    first = _package(night, "1Z-RB-0003", 250050)
    second = _package(night, "1Z-RB-0004", 250050)
    fail_a = record_failure(night["hub_id"], first["id"], "SORT_MISS", 1500)
    record_failure(night["hub_id"], second["id"], "SORT_MISS", 1500)

    api.finalize_failure(fail_a["id"], H["refund_adjuster_headers"])
    summary = get_refund_summary(night["hub_id"])
    assert summary["batch_total_cents"] == 233798, (
        "137528 finalized plus 96270 still provisional"
    )


def test_only_carrier_attributed_failures_contribute_to_the_batch(night):
    """PRD §3.11: "Only failures attributed to the carrier on that hub contribute;
    failures attributed to the customer, the weather event or the mechanical event
    contribute zero and are excluded from the sum."

    Design: Difficulty/combinatorial_formula/refund_batch_nested_rounding_order_pinned
    """
    package = _package(night, "1Z-RB-0005", 250050)
    carrier = record_failure(night["hub_id"], package["id"], "SORT_MISS", 1500)
    customer = record_failure(night["hub_id"], package["id"], "REVENUE_PRORATE", 1500)
    assert customer["refund_amount_cents"] == 0

    summary = get_refund_summary(night["hub_id"])
    assert summary["batch_total_cents"] == 96270, "only the carrier failure is counted"
    assert summary["eligible_failure_count"] == 1
    summary_after_finalize = None
    api.finalize_failure(carrier["id"], H["refund_adjuster_headers"])
    summary_after_finalize = get_refund_summary(night["hub_id"])
    assert summary_after_finalize["batch_total_cents"] == 137528


def test_the_refund_rate_is_keyed_on_service_level_and_the_surcharge_on_commodity(night):
    """PRD §3.11: "a package that is both perishable and next-day collects both, because
    the rate is keyed on the service level while the surcharge is keyed on the commodity
    class — two independent dimensions."

    Design: Difficulty/combinatorial_formula/refund_batch_nested_rounding_order_pinned
    """
    next_day = _package(night, "1Z-RB-0006", 100000)
    second_day = _package(night, "1Z-RB-0007", 100000, service_level="SECOND_DAY_AIR")
    ground = _package(night, "1Z-RB-0008", 100000, service_level="GROUND")
    perishable = _package(night, "1Z-RB-0009", 100000, commodity_class="PERISHABLE")

    amounts = [
        record_failure(night["hub_id"], pkg["id"], "NO_SCAN", 1500)["refund_amount_cents"]
        for pkg in (next_day, second_day, ground, perishable)
    ]
    assert amounts == [38500, 21000, 9800, 38675], (
        "550 x 100 kg provisional is 38500, 300 x 100 kg is 21000, 140 x 100 kg is 9800, "
        "and the perishable next-day package adds the 250-cent surcharge before the "
        "provisional scaling"
    )