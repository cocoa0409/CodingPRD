"""The sample library: a promise ledger of closed holds over physical inventory."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_SAMPLE_KIT_HOLD_CONFLICT
from test_helpers.assertions import (
    assert_instant_equals,
    assert_kit_conservation,
    assert_page_meta,
)
from test_helpers.fixtures import (
    add_sample_kit,
    book_consultation,
    charter_territory,
    checkout_kit,
    hire_designer,
    intake_lead,
    read_territory,
    return_kit,
    set_clock,
)
from test_helpers.test_users import designer_headers, franchisee_headers


def _library(api, kit_specs):
    """A territory whose library holds the given kits, plus one future appointment."""
    territory = charter_territory(api, royalty_rate_pct=0.055,
                                 lead_capacity_per_week=5,
                                 credit_limit_cents=2000000,
                                 liability_window="ROLLING_180D")
    designer = hire_designer(api, territory)
    kits = [add_sample_kit(api, territory, kit_code=code,
                           replacement_value_cents=value)
            for code, value in kit_specs]
    lead = intake_lead(api, territory, customer_name="Ana Ruiz",
                       source="REFERRAL",
                       requested_at="2026-08-01T08:00:00.000Z",
                       child_occupied_dwelling=False)
    consultation = book_consultation(
        api, designer, lead,
        scheduled_start_at="2026-08-09T14:00:00.000Z",
        scheduled_end_at="2026-08-09T15:00:00.000Z",
    )
    return territory, designer, kits, consultation


def test_a_returned_hold_still_blocks_a_new_hold_that_starts_on_its_end_instant(api):
    """The kit is physically back on 08-04, yet its promise runs to 08-07T17:00 inclusive.

    "A requested interval is refused with `ERR_SAMPLE_KIT_HOLD_CONFLICT` when it
    overlaps the recorded hold interval of any check-out on the same kit whose
    `status` is `OPEN` **or** `RETURNED`. Both endpoints of both intervals are
    inclusive, so a new hold that starts exactly on an earlier hold's `hold_end_at`
    collides — and it collides even if that earlier kit came back early, because the
    library ledger records where the kit was promised to be, not only where it
    physically is."

    Design: Difficulty/resource_temporal_overlap/sample_kit_holds_are_closed_intervals_that_survive_an_early_return
    """
    territory, designer, kits, consultation = _library(
        api, [("SHEERS-A", 50000)])
    kit = kits[0]

    first = checkout_kit(api, designer, kit, consultation,
                         "2026-08-03T09:00:00.000Z", "2026-08-07T17:00:00.000Z")
    set_clock(api, "2026-08-04T10:00:00.000Z")
    returned = return_kit(api, designer, first)
    assert returned["status"] == "RETURNED"
    assert_instant_equals(returned["returned_at"], "2026-08-04T10:00:00.000Z",
                          "returned_at")
    assert returned["days_late"] == 0
    assert returned["late_fee_cents"] == 0
    assert validate_success(api.get_sample_kit(
        kit["id"], franchisee_headers(territory["id"])))["status"] == "AVAILABLE"

    set_clock(api, "2026-08-05T09:00:00.000Z")
    validate_error(
        api.create_sample_checkout(
            f.sample_checkout_payload(kit["id"], consultation["id"],
                                      "2026-08-07T17:00:00.000Z",
                                      "2026-08-09T17:00:00.000Z"),
            designer_headers(designer["id"])),
        ERR_SAMPLE_KIT_HOLD_CONFLICT, 409)

    admitted = validate_success(
        api.create_sample_checkout(
            f.sample_checkout_payload(kit["id"], consultation["id"],
                                      "2026-08-07T17:00:00.001Z",
                                      "2026-08-09T17:00:00.000Z"),
            designer_headers(designer["id"])), 201)
    assert admitted["status"] == "OPEN"
    assert_instant_equals(admitted["hold_start_at"], "2026-08-07T17:00:00.001Z",
                          "hold_start_at")

    reread = validate_success(api.get_sample_kit(
        kit["id"], franchisee_headers(territory["id"])))
    assert reread["status"] == "ON_LOAN"
    assert reread["loan_count"] == 2
    assert reread["open_loan_count"] == 1

    counters = read_territory(api, territory)
    assert counters["available_kit_count"] == 0
    assert counters["on_loan_kit_count"] == 1
    assert_kit_conservation(counters, 1)


def test_an_early_return_writes_no_money_row_at_all(api):
    """A kit handed back before its due instant is free, so the ledger stays empty.

    "If `returned_at` is at or before `due_at`, `days_late` is zero."

    "When `late_fee_cents` is greater than zero a ledger row of type
    `SAMPLE_LATE_FEE` is appended for that amount, with `basis_cents` equal to the
    kit's `replacement_value_cents`, `source_entity_type` `SAMPLE_CHECKOUT` and
    `memo` `sample_late`; a fee of zero writes no row."

    Design: Difficulty/resource_temporal_overlap/sample_kit_holds_are_closed_intervals_that_survive_an_early_return
    """
    territory, designer, kits, consultation = _library(
        api, [("SHEERS-A", 50000)])

    checkout = checkout_kit(api, designer, kits[0], consultation,
                            "2026-08-03T09:00:00.000Z",
                            "2026-08-07T17:00:00.000Z")
    assert_instant_equals(checkout["due_at"], "2026-08-07T17:00:00.000Z",
                          "due_at")
    set_clock(api, "2026-08-04T10:00:00.000Z")
    return_kit(api, designer, checkout)

    _rows, meta = validate_paginated(api.list_ledger_entries(
        territory["id"], franchisee_headers(territory["id"])))
    assert_page_meta(meta, total_count=0, has_more=False)


def _two_free_cycles(api):
    """Two complete loan cycles on one of two kits, both returned before due."""
    territory, designer, kits, consultation = _library(
        api, [("SHEERS-A", 50000), ("WOODS-B", 42000)])
    borrowed, untouched = kits

    before = read_territory(api, territory)
    assert before["available_kit_count"] == 2

    first = checkout_kit(api, designer, borrowed, consultation,
                         "2026-08-03T09:00:00.000Z", "2026-08-05T17:00:00.000Z")
    midway = read_territory(api, territory)
    set_clock(api, "2026-08-04T10:00:00.000Z")
    first = return_kit(api, designer, first)

    second = checkout_kit(api, designer, borrowed, consultation,
                          "2026-08-06T09:00:00.000Z",
                          "2026-08-08T17:00:00.000Z")
    set_clock(api, "2026-08-07T10:00:00.000Z")
    second = return_kit(api, designer, second)

    return {"territory": territory, "designer": designer,
            "borrowed": borrowed, "untouched": untouched,
            "midway": midway, "returns": (first, second)}


def test_the_three_way_kit_partition_holds_at_every_observable_moment(api):
    """One kit out and one kit idle still add up to the two rows the library owns.

    "For any territory, `available_kit_count` plus `on_loan_kit_count` plus
    `lost_kit_count` equals the total number of kit rows the territory owns;
    `on_loan_kit_count` equals the number of check-outs in status `OPEN` whose kit
    belongs to that territory; and a kit's `open_loan_count` is always either zero or
    one, and is one exactly when the kit's `status` is `ON_LOAN`."

    Design: Difficulty/compensating_invariant/a_checkout_and_return_pair_restores_inventory_while_loan_count_ratchets
    """
    world = _two_free_cycles(api)
    midway = world["midway"]
    assert midway["available_kit_count"] == 1
    assert midway["on_loan_kit_count"] == 1
    assert_kit_conservation(midway, 2)

    for record in world["returns"]:
        assert record["status"] == "RETURNED"
        assert record["days_late"] == 0
        assert record["late_fee_cents"] == 0

    after = read_territory(api, world["territory"])
    assert after["available_kit_count"] == 2
    assert after["on_loan_kit_count"] == 0
    assert after["lost_kit_count"] == 0
    assert_kit_conservation(after, 2)


def test_the_compensating_pair_restores_inventory_while_loan_count_ratchets(api):
    """Two cycles leave the inventory as it began and `loan_count` permanently at two.

    "`loan_count` records history rather than inventory: it counts every check-out
    ever created against the kit and never decreases. A check-out followed by an
    ordinary return is therefore an exact compensating pair on the inventory
    counters, while `loan_count` keeps its increment."

    Design: Difficulty/compensating_invariant/a_checkout_and_return_pair_restores_inventory_while_loan_count_ratchets
    """
    world = _two_free_cycles(api)
    territory = world["territory"]
    owner = franchisee_headers(territory["id"])

    borrowed = validate_success(
        api.get_sample_kit(world["borrowed"]["id"], owner))
    assert borrowed["status"] == "AVAILABLE"
    assert borrowed["open_loan_count"] == 0
    assert borrowed["loan_count"] == 2

    untouched = validate_success(
        api.get_sample_kit(world["untouched"]["id"], owner))
    assert untouched["status"] == "AVAILABLE"
    assert untouched["loan_count"] == 0
    assert untouched["open_loan_count"] == 0

    # The whole episode is visible only in counters: it wrote no money.
    _rows, ledger_meta = validate_paginated(
        api.list_ledger_entries(territory["id"], owner))
    assert_page_meta(ledger_meta, total_count=0, has_more=False)

    _all_rows, all_meta = validate_paginated(api.list_sample_checkouts(
        designer_headers(world["designer"]["id"]),
        sample_kit_id=world["borrowed"]["id"]))
    assert_page_meta(all_meta, total_count=2, has_more=False)

    _open_rows, open_meta = validate_paginated(api.list_sample_checkouts(
        designer_headers(world["designer"]["id"]),
        sample_kit_id=world["borrowed"]["id"], status="OPEN"))
    assert_page_meta(open_meta, total_count=0, has_more=False)
