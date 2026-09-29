"""Quote acceptance seen from the capacity graph rather than the money graph."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers.assertions import assert_ledger_entry, assert_page_meta
from test_helpers.fixtures import (
    accept_quote,
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    present_quote,
    read_territory,
    record_opening,
)
from test_helpers.test_users import franchisee_headers


def _capacity_one_fixture(api):
    """A territory holding one live lead at a time, with two more leads waiting."""
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=1,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory)
    first = intake_lead(api, territory, customer_name="Ana Ruiz",
                        source="WEB_FORM",
                        requested_at="2026-08-01T08:00:00.000Z",
                        child_occupied_dwelling=False)
    second = intake_lead(api, territory, customer_name="Bo Chen",
                         source="REFERRAL",
                         requested_at="2026-08-01T09:00:00.000Z",
                         child_occupied_dwelling=False)
    third = intake_lead(api, territory, customer_name="Cy Doyle",
                        source="WALK_IN",
                        requested_at="2026-08-01T10:00:00.000Z",
                        child_occupied_dwelling=False)
    consultation = book_consultation(
        api, designer, first,
        scheduled_start_at="2026-08-04T14:00:00.000Z",
        scheduled_end_at="2026-08-04T15:00:00.000Z",
    )
    opening = record_opening(api, designer, consultation,
                             label="Nursery west", room_type="NURSERY")
    configure_opening(api, designer, opening, fabric_code="LT-SHEER",
                      lift_system="CORDLESS", motorization_option="NONE")
    quote = build_quote(api, designer, consultation)
    present_quote(api, designer, quote)
    return territory, designer, first, second, third, quote


def test_accepting_a_quote_promotes_exactly_one_of_two_queued_leads(api):
    """Freeing one unit of weekly capacity promotes one waiting lead and no more.

    "Exactly one lead is promoted per unit of freed capacity: the `QUEUED` lead
    with the smallest `created_at`, tie-broken by the smallest `postal_code` and
    then by the smallest `customer_name`."

    Design: Difficulty/transitive_cascade/quote_acceptance_cascades_three_hops_into_a_queued_lead_promotion
    """
    territory, designer, first, second, third, quote = _capacity_one_fixture(api)
    owner = franchisee_headers(territory["id"])

    before = read_territory(api, territory)
    assert before["open_leads_count"] == 1
    assert validate_success(api.get_lead(first["id"], owner))["status"] == "ROUTED"
    queued_two = validate_success(api.get_lead(second["id"], owner))
    assert queued_two["status"] == "QUEUED"
    assert queued_two["territory_id"] is None
    assert validate_success(api.get_lead(third["id"], owner))["status"] == "QUEUED"

    accepted = accept_quote(api, designer, quote)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["net_sales_cents"] == 6760

    assert validate_success(api.get_lead(first["id"], owner))["status"] == "CONVERTED"

    promoted = validate_success(api.get_lead(second["id"], owner))
    assert promoted["status"] == "ROUTED"
    assert promoted["territory_id"] == territory["id"]
    assert promoted["routed_at"] is not None

    still_waiting = validate_success(api.get_lead(third["id"], owner))
    assert still_waiting["status"] == "QUEUED"
    assert still_waiting["territory_id"] is None

    after = read_territory(api, territory)
    assert after["open_leads_count"] == 1
    assert after["version"] > before["version"]


def test_acceptance_accrues_one_royalty_row_at_the_territorys_rate(api):
    """The provisional royalty is the whole net sales figure at the charter rate.

    "A ledger row of type `NET_SALES_ROYALTY` is appended whose `amount_cents` is
    the recognized basis multiplied by the territory's `royalty_rate_pct` and
    rounded half up to a whole cent, whose `basis_cents` is the recognized basis,
    whose `source_entity_type` is `QUOTE` and whose `memo` is `quote_accepted`;
    that amount raises the territory's `royalty_accrued_cents`."

    Design: Difficulty/transitive_cascade/quote_acceptance_cascades_three_hops_into_a_queued_lead_promotion
    """
    territory, designer, _first, _second, _third, quote = _capacity_one_fixture(api)

    accepted = accept_quote(api, designer, quote)
    assert accepted["recognized_net_sales_cents"] == 6760
    assert accepted["credited_net_sales_cents"] == 0

    counters = read_territory(api, territory)
    assert counters["net_sales_cents"] == 6760
    assert counters["royalty_accrued_cents"] == 372

    rows, meta = validate_paginated(
        api.list_ledger_entries(territory["id"],
                                franchisee_headers(territory["id"]),
                                entry_type="NET_SALES_ROYALTY")
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert_ledger_entry(rows[0], "NET_SALES_ROYALTY", 372, 6760, "quote_accepted",
                        "QUOTE", source_entity_id=quote["id"],
                        territory_id=territory["id"])
