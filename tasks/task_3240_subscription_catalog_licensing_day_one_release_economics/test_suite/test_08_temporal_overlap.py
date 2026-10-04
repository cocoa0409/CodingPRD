"""Interval semantics over resource windows.

Two half-open maintenance windows that share only their boundary instant do not
overlap; a success-rejected pair is all-or-nothing. Renewal tightens a deal's
term window around the removal dates of its existing entries.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_region,
    list_maintenances,
    scenario_with_two_expiring_deals,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

NA_WINDOWS = [
    {"maintenance_start": "2026-10-01T00:00:00Z",
     "maintenance_end": "2026-10-05T00:00:00Z",
     "capacity_reduction_pct": 0.25},
    {"maintenance_start": "2026-10-05T00:00:00Z",
     "maintenance_end": "2026-10-10T00:00:00Z",
     "capacity_reduction_pct": 0.25},
]

EU_WINDOWS = [
    {"maintenance_start": "2026-10-01T00:00:00Z",
     "maintenance_end": "2026-10-05T00:00:00Z",
     "capacity_reduction_pct": 0.25},
    {"maintenance_start": "2026-10-04T23:59:59Z",
     "maintenance_end": "2026-10-10T00:00:00Z",
     "capacity_reduction_pct": 0.25},
]


def test_adjacent_maintenance_windows_are_accepted(api):
    """PRD §3.1: "windows of the same region whose intervals overlap and which
    are not explicitly marked as tolerating overlap are rejected with
    `ERR_MAINTENANCE_WINDOW_OVERLAP`".
    PRD §2.7: "A `CatalogMaintenance` window names the `region_code` it applies
    to, an inclusive `maintenance_start`, an exclusive `maintenance_end` and a
    `capacity_reduction_pct` between 0 and 1."

    Design: Difficulty/resource_temporal_overlap/adjacent_maintenance_windows_touch_but_do_not_overlap
    """
    set_clock(api, "2026-09-02T00:00:00Z")
    region = validate_success(
        api.create_region(
            {
                "region_code": "NA",
                "currency_code": "USD",
                "price_multiplier": 1.20,
                "availability_ceiling_titles": 4000,
                "catalog_tier_floor": "ESSENTIAL",
                "maintenance_windows": NA_WINDOWS,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert region["region_code"] == "NA"

    rows, meta = validate_paginated(
        api.list_catalog_maintenances(ADMIN, params={"region_code": "NA"})
    )
    assert len(rows) == 2, "one CatalogMaintenance row per submitted window"
    assert meta["total_count"] == 2
    for row in rows:
        assert row["status"] == "SCHEDULED"
    # 2026-10-05T00:00:00Z is the exclusive end of the first window and the
    # inclusive start of the second, so the pair touches without overlapping.
    starts = sorted(row["maintenance_start"] for row in rows)
    ends = sorted(row["maintenance_end"] for row in rows)
    assert ends[0] == starts[1] == "2026-10-05T00:00:00.000Z", \
        "the shared instant is rendered as an ISO 8601 UTC timestamp with three " \
        "fractional digits (PRD §2.5)"


def test_a_one_second_overlap_rejects_the_whole_region_creation(api):
    """PRD §3.1: "A region may also be created with a `maintenance_windows`
    list, in which case one `CatalogMaintenance` row is instantiated per
    submitted window".

    Design: Difficulty/resource_temporal_overlap/adjacent_maintenance_windows_touch_but_do_not_overlap
    """
    set_clock(api, "2026-09-02T00:00:00Z")
    create_region(api, region_code="NA", currency_code="USD", price_multiplier=1.20,
                  maintenance_windows=NA_WINDOWS)

    validate_error(
        api.create_region(
            {
                "region_code": "EU",
                "currency_code": "EUR",
                "price_multiplier": 1.20,
                "availability_ceiling_titles": 4000,
                "catalog_tier_floor": "ESSENTIAL",
                "maintenance_windows": EU_WINDOWS,
            },
            ADMIN,
        ),
        "ERR_MAINTENANCE_WINDOW_OVERLAP",
    )

    eu_rows, meta = validate_paginated(
        api.list_catalog_maintenances(ADMIN, params={"region_code": "EU"})
    )
    assert eu_rows == []
    assert meta["total_count"] == 0, "the rejection is all-or-nothing"
    validate_error(api.get_region("EU", ADMIN), "ERR_REGION_NOT_FOUND")


def test_renewal_is_accepted_when_every_removal_date_sits_inside_the_new_term(api):
    """PRD §3.2: "The extension supplies a `renew_term_end_date` which must be
    later than the current `term_end_date`, and the logical clock must still be
    before the current `term_end_date`; the operation moves the deal back from
    `EXPIRING` to `LIVE`. Extending the term rewrites `term_end_date`, recomputes
    `removal_effective_date` as the new end minus two days, recomputes
    `compensation_floor_cents` and `payable_compensation_cents` against the
    longer term, refreshes the publisher's `lifetime_licensing_cost_cents`, and
    reverts every entry of that deal currently in `REMOVING` back to `ADDED`."

    Design: Difficulty/resource_temporal_overlap/renewal_tightens_the_term_window_around_existing_removal_dates
    """
    sc = scenario_with_two_expiring_deals(api)

    renewed_b = validate_success(
        api.renew_licensing_deal(sc.deal_b["id"],
                                 {"renew_term_end_date": "2027-05-15T00:00:00Z"}, ADMIN)
    )
    assert renewed_b["status"] == "LIVE", \
        "a later renew_term_end_date moves the EXPIRING deal back to LIVE"
    assert renewed_b["term_end_date"].startswith("2027-05-15")
    assert renewed_b["removal_effective_date"].startswith("2027-05-13"), \
        "the removal effective date is the new term end minus two days"

    renewed_a = validate_success(
        api.renew_licensing_deal(sc.deal_a["id"],
                                 {"renew_term_end_date": "2027-09-01T00:00:00Z"}, ADMIN)
    )
    assert renewed_a["status"] == "LIVE"
    assert renewed_a["term_end_date"].startswith("2027-09-01")
    assert renewed_a["removal_effective_date"].startswith("2027-08-30")

    entry_a = validate_success(api.get_catalog_entry(sc.entry_a["id"], ADMIN))
    assert entry_a["status"] == "ADDED", \
        "extending the term reverts the deal's REMOVING entries back to ADDED"