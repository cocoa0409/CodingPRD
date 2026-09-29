"""Exact-boundary behaviour: the delinquency threshold and the first-reading edge."""

import pytest
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import (
    assert_cents,
    assert_freeboard,
    assert_instant,
)
from test_helpers.constants import (
    ALERT_CRITICAL,
    ALERT_NORMAL,
    DELINQUENCY_CURRENT,
    DELINQUENCY_DELINQUENT,
    ENTRY_ANNUAL_REGISTRATION_FEE,
    ENTRY_CIVIL_PENALTY,
    EVENT_EMERGENCY,
    EVENT_MONITORING,
)


# ---------------------------------------------------------------------------
# The 25,000-cent delinquency threshold is inclusive
# ---------------------------------------------------------------------------
@pytest.fixture()
def owner_one_cent_short(program):
    """An owner whose replayed balance sits exactly one cent below the threshold."""
    owner = program.create_owner()
    program.post_ledger_entry(
        owner["id"],
        entry_type=ENTRY_ANNUAL_REGISTRATION_FEE,
        amount_cents=24999,
        memo="2026 registration fee.",
    )
    return owner


def test_a_balance_one_cent_below_the_threshold_is_still_current(
    program, owner_one_cent_short
):
    """24,999 cents does not cross the threshold, so the owner stays current.

    PRD 3.8: "`delinquency_status` is a pure function of the replayed balance and is recomputed on every posting: it reads `DELINQUENT` when `fee_balance_cents` is at or above 25,000 cents — two hundred and fifty dollars, and the threshold is inclusive, so a balance of exactly 25,000 cents is delinquent — and `CURRENT` otherwise."

    Design: Difficulty/boundary_precision_check/delinquency_threshold_is_inclusive_at_exactly_25000_cents
    """
    owner_id = owner_one_cent_short["id"]
    rows, meta = program.ledger(owner_id)
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == ENTRY_ANNUAL_REGISTRATION_FEE
    assert rows[0]["sequence_no"] == 1
    assert_cents(rows[0]["amount_cents"], 24999, "amount_cents")
    assert_cents(rows[0]["balance_after_cents"], 24999, "balance_after_cents")

    owner = program.get_owner(owner_id)
    assert_cents(owner["fee_balance_cents"], 24999, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_CURRENT


def test_one_more_cent_lands_exactly_on_the_threshold_and_flips_delinquency(
    program, owner_one_cent_short
):
    """A one-cent penalty takes the balance to exactly 25,000 cents and it is delinquent.

    PRD 3.8: "The replay walks the owner's entries in ascending `sequence_no`, accumulating the signed amounts, and writes the accumulated figure into each entry's `balance_after_cents`; the final accumulated figure is the owner's `fee_balance_cents`."

    Design: Difficulty/boundary_precision_check/delinquency_threshold_is_inclusive_at_exactly_25000_cents
    """
    owner_id = owner_one_cent_short["id"]
    posted = program.post_ledger_entry(
        owner_id,
        entry_type=ENTRY_CIVIL_PENALTY,
        amount_cents=1,
        memo="One-cent administrative penalty.",
    )
    assert posted["sequence_no"] == 2
    assert_cents(posted["amount_cents"], 1, "amount_cents")
    assert_cents(posted["balance_after_cents"], 25000, "balance_after_cents")

    owner = program.get_owner(owner_id)
    assert_cents(owner["fee_balance_cents"], 25000, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT


def test_the_owner_listing_filters_on_the_recomputed_delinquency_flag(
    api, program, owner_one_cent_short
):
    """The flag is queryable the instant the balance crosses the threshold.

    PRD 3.1: "Inventory reads are broad. Dams can be listed filtered by `owner_id`, `river_reach_id`, `hazard_class`, `safety_status`, `regulatory_status` and the boolean `inspection_overdue`; owners by `delinquency_status`; engineers by `license_status`."

    Design: Difficulty/boundary_precision_check/delinquency_threshold_is_inclusive_at_exactly_25000_cents
    """
    owner_id = owner_one_cent_short["id"]
    before, _meta = validate_paginated(
        api.list_owners(program.admin, {"delinquency_status": DELINQUENCY_DELINQUENT})
    )
    assert [row["id"] for row in before] == []

    program.post_ledger_entry(
        owner_id,
        entry_type=ENTRY_CIVIL_PENALTY,
        amount_cents=1,
        memo="One-cent administrative penalty.",
    )

    after, meta = validate_paginated(
        api.list_owners(program.admin, {"delinquency_status": DELINQUENCY_DELINQUENT})
    )
    assert [row["id"] for row in after] == [owner_id]
    assert meta["total_count"] == 1

    current, _m = validate_paginated(
        api.list_owners(program.admin, {"delinquency_status": DELINQUENCY_CURRENT})
    )
    assert owner_id not in [row["id"] for row in current]


# ---------------------------------------------------------------------------
# The first reading of an event has no predecessor
# ---------------------------------------------------------------------------
@pytest.fixture()
def monitored_event(program, base):
    """A declared high-water event on an unclassified dam with a 1042.5-ft crest."""
    return program.declare_event(
        base.dam_id,
        declared_at="2026-08-01T00:00:00Z",
        trigger_description="Forecast 6-inch rainfall on a saturated basin.",
        declared_inflow_cfs=950,
    )


def test_the_first_reading_is_never_rising_so_a_critical_pool_cannot_escalate(
    program, base, monitored_event
):
    """A critical alert level alone leaves the event in MONITORING.

    PRD 3.7: "The boolean `rising` compares the reading to its predecessor — the event's reading with the greatest `reading_at` strictly earlier than this one, ties broken by `created_at` ascending and never by `id` — and is true exactly when such a predecessor exists and this reading's `pool_elevation_ft` is strictly greater than the predecessor's."

    Design: Difficulty/boundary_precision_check/first_event_reading_has_no_predecessor_so_it_cannot_escalate
    """
    assert monitored_event["status"] == EVENT_MONITORING
    assert monitored_event["reading_count"] == 0
    assert monitored_event["current_alert_level"] == ALERT_NORMAL
    assert monitored_event["peak_pool_elevation_ft"] is None

    program.set_clock("2026-08-01T02:00:00Z")
    first = program.add_reading(
        monitored_event["id"],
        "2026-08-01T02:00:00Z",
        1041.5,
        observed_inflow_cfs=1100,
    )
    # Crest 1042.50 less pool 1041.50 is exactly 1.00 ft, the inclusive upper
    # bound of the CRITICAL band.
    assert_freeboard(first["freeboard_ft"], 1.00, "freeboard_ft")
    assert first["alert_level"] == ALERT_CRITICAL
    assert first["rising"] is False

    event = program.get_event(monitored_event["id"])
    assert event["status"] == EVENT_MONITORING
    assert event["escalated_at"] is None
    assert event["current_alert_level"] == ALERT_CRITICAL
    assert event["reading_count"] == 1
    assert event["peak_pool_elevation_ft"] == pytest.approx(1041.5, abs=0.005)


def test_the_second_reading_gains_a_predecessor_and_escalates_the_event(
    program, base, monitored_event
):
    """One tenth of a foot of rise is enough to trigger auto-escalation.

    PRD 3.7: "If the event is still `MONITORING` and the new reading's `alert_level` is `CRITICAL` or `OVERTOPPING` **and** its `rising` flag is true, the event moves `MONITORING → EMERGENCY` and `escalated_at` is stamped with the logical clock."

    Design: Difficulty/boundary_precision_check/first_event_reading_has_no_predecessor_so_it_cannot_escalate
    """
    program.set_clock("2026-08-01T02:00:00Z")
    program.add_reading(
        monitored_event["id"],
        "2026-08-01T02:00:00Z",
        1041.5,
        observed_inflow_cfs=1100,
    )
    program.set_clock("2026-08-01T04:00:00Z")
    second = program.add_reading(
        monitored_event["id"],
        "2026-08-01T04:00:00Z",
        1041.6,
        observed_inflow_cfs=1250,
    )
    assert_freeboard(second["freeboard_ft"], 0.90, "freeboard_ft")
    assert second["alert_level"] == ALERT_CRITICAL
    assert second["rising"] is True

    event = program.get_event(monitored_event["id"])
    assert event["status"] == EVENT_EMERGENCY
    assert_instant(event["escalated_at"], "2026-08-01T04:00:00Z", "escalated_at")
    assert event["reading_count"] == 2
    assert event["peak_pool_elevation_ft"] == pytest.approx(1041.6, abs=0.005)
