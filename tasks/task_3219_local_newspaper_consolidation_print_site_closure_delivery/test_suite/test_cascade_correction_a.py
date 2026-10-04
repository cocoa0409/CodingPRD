"""Difficulty queue A — transitive_cascade from the edition-correction trigger.

Correcting a delivered edition flags the correction, that correction cost itself
recomputes the market's transfer ledger so the credit is non-zero, and that ledger
recompute itself re-examines the hub's legal-notice ratio and sets the block.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_site,
    create_region,
    create_market,
    create_route,
    create_edition,
    create_contractor,
    create_delivery_route,
    create_stop,
    plan_transfer,
    deliver_edition,
    dispatch_edition,
    correct_edition,
    get_print_market,
    validate_success,
    setup_ratio_at_floor_with_sites,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

PRINT_OPS = TEST_USERS["print_ops_headers"]


@pytest.fixture
def correction_scenario():
    """Hub whose counted ratio sits exactly on the floor, plus a corrigible edition.

    One of the two counted markets carries a delivered, legal-notice-bearing edition;
    the other is already late, so the ratio is exactly 1 of 2 against a floor of 90.
    """
    hub = create_hub(min_on_time_ratio_pct=90)
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    riverton = create_market(region["id"], guaranteed_floor_copies=0,
                             publication_deadline_utc="05:30",
                             on_time_margin_minutes=30,
                             single_copy_market_rule="carrier")
    route = create_route(site["id"], riverton["id"])
    # One delivery stop in the market is what lifts the route's transport cost to the
    # pinned 91.25, so the correction's route re-run term is 91.25 * 1.40.
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], riverton["id"])
    create_stop(delivery_route["id"], riverton["id"], stop_code="S1")
    plan_transfer(riverton["id"], site["id"], hub_id=hub["id"])
    edition = create_edition(riverton["id"], site["id"], slug="2026-09-21",
                             page_count=12, requested_print_run_copies=20000,
                             legal_notice_count=1)
    dispatch_edition(edition["id"])
    deliver_edition(edition["id"])
    return hub, site, region, riverton, route, edition


def test_correction_books_the_redispatch_cost_on_the_edition(correction_scenario):
    """PRD §3.5: "The redispatch cost is the edition's `press_run_hours` multiplied
    by 2,500.00 dollars of reprint press cost per hour, plus the route's
    `route_transport_cost` multiplied by 1.40".

    PRD §3.5: "A delivered edition that carried at least one legal notice may be
    corrected: this sets `correction_open` true".

    Design: Difficulty/transitive_cascade/edition_correction_cascade_market_to_hub_ratio
    """
    hub, site, region, riverton, route, edition = correction_scenario

    corrected = correct_edition(edition["id"])

    assert corrected["correction_open"] is True
    assert corrected["status"] == "reverted_to_digital"
    # 0.25 press hours * 2500.00 plus route_transport_cost 91.25 * 1.40 = 752.75.
    assert corrected["correction_redispatch_cost_cents"] == pytest.approx(752.75, abs=0.01), (
        f"got {corrected['correction_redispatch_cost_cents']}"
    )


def test_the_correction_flag_recomputes_the_market_ledger(correction_scenario):
    """PRD §3.5: "then `print_site_transfer_credit_cents` is zero while the market
    is not `withdrawn` and no correction is open, and is exactly the negation of the
    cost once the market is `withdrawn` or a correction has stopped the press".

    Design: Difficulty/transitive_cascade/edition_correction_cascade_market_to_hub_ratio
    """
    hub, site, region, riverton, route, edition = correction_scenario

    before = get_print_market(riverton["id"])
    assert before["print_site_transfer_credit_cents"] == pytest.approx(0.0, abs=0.01)

    correct_edition(edition["id"])
    after = get_print_market(riverton["id"])

    assert after["print_site_transfer_credit_cents"] == pytest.approx(-92.00, abs=0.01), (
        f"hop 4: the open correction must post the negated cost, got "
        f"{after['print_site_transfer_credit_cents']}"
    )
    assert after["net_print_site_transfer_cost_cents"] == pytest.approx(0.0, abs=0.01)


def test_the_ledger_recompute_reexamines_the_hub_ratio(correction_scenario):
    """PRD §3.5: "A delivered edition that carried at least one legal notice may be
    corrected: this sets `correction_open` true, computes
    `correction_redispatch_cost_cents`, re-examines the edition's market under the
    legal-notice ratio gate of §2.9, and pushes the edition to
    `reverted_to_digital`."
    PRD §2.9: "If there are no counted markets at all, there is no compliance basis
    and the gate fails."

    Design: Difficulty/transitive_cascade/edition_correction_cascade_market_to_hub_ratio
    """
    hub, site, region, riverton, route, edition = correction_scenario

    correct_edition(edition["id"])
    refreshed_hub = validate_success(api.get_hub(hub["id"], PRINT_OPS), 200)
    compliance = validate_success(
        api.get_hub_compliance(hub["id"], TEST_USERS["auditor_headers"]), 200)

    assert compliance["counted_market_count"] == 1
    assert compliance["is_legal_notice_ratio_compliant"] is False, (
        "the reverted edition is no longer on time, so the sole counted market "
        "cannot carry the ratio"
    )
    assert refreshed_hub["legal_notice_block"] is True, (
        "hop 5: the re-examined ratio sets the block"
    )