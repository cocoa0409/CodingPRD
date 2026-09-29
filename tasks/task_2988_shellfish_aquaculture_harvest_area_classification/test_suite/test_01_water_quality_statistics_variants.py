"""Water-quality statistics under the two window variants (PRD §3.2).

One stored set of fifteen accepted samples is read twice. The
`SYSTEMATIC_RANDOM` variant admits all fifteen; the `ADVERSE_CONDITION` variant
admits only the five collected inside the five-day adverse window after a
closure-triggering rainfall event. Both readings run the identical six
computation steps and the identical eligibility ladder, so any divergence is
window membership alone.
"""
from test_helpers import (
    api_client,
    assert_classification_summary,
    create_growing_area,
    dw_area_payload,
    DW_CLOCK,
    get_success_data,
    ingest_rainfall_event,
    ingest_water_sample,
    iso,
    plus_days,
    set_clock,
    TEST_USERS,
    to_millis,
)

AUTHORITY = TEST_USERS["authority_headers"]

# Ten fair-weather samples on 2026-07-01 .. 2026-07-10 at 09:00Z.
FAIR_WEATHER_MPNS = [2, 2, 2, 2, 2, 3, 3, 3, 3, 3]
# Five storm-influenced samples on 2026-07-20 .. 2026-07-24 at 06:00Z, all
# inside ADVERSE_WINDOW_HOURS of the 2026-07-20T00:00:00Z rainfall event.
STORM_MPNS = [160, 120, 90, 140, 80]

RAINFALL_OBSERVED_AT = iso(2026, 7, 20)


def _area_with_fifteen_accepted_samples():
    """Fifteen accepted samples at one station on fifteen distinct calendar
    dates, so no ingest supersedes an earlier row, five of them flagged
    `is_adverse_condition`."""
    set_clock(DW_CLOCK)
    area = create_growing_area(dw_area_payload())
    for offset, mpn in enumerate(FAIR_WEATHER_MPNS):
        ingest_water_sample(area["id"], {
            "station_code": "ST-1",
            "collected_at": plus_days("2026-07-01", offset) + "T09:00:00Z",
            "fecal_coliform_mpn": mpn,
            "water_temp_c": 24.0,
            "salinity_ppt": 30.0,
        })
    rainfall = ingest_rainfall_event(area["id"], {
        "gauge_code": "RG-7",
        "observed_at": RAINFALL_OBSERVED_AT,
        "inches_24h": 1.50,
    })
    for offset, mpn in enumerate(STORM_MPNS):
        ingest_water_sample(area["id"], {
            "station_code": "ST-1",
            "collected_at": plus_days("2026-07-20", offset) + "T06:00:00Z",
            "fecal_coliform_mpn": mpn,
            "water_temp_c": 25.0,
            "salinity_ppt": 28.0,
        })
    return area, rainfall


def _summary(area_id, variant):
    return get_success_data(api_client.get_classification_summary(
        area_id, AUTHORITY, params={"variant": variant}))


def test_systematic_random_summary_reads_all_fifteen_accepted_samples():
    """The default window is the last fifteen accepted samples by `collected_at`
    ascending. Over 2 x5, 3 x5, 160, 120, 90, 140, 80 the six steps give
    `mean_log10` 0.9451, a geometric mean of 8.8 and a p90 of 98.8, and the
    eligibility ladder answers RESTRICTED because 8.8 clears the 14.0 approved
    geometric-mean limit but 98.8 exceeds the 43.0 approved p90 limit while
    staying inside the 260.0 restricted limit.

    Design: Difficulty/dual_variant_calc/area_stats_diverge_between_systematic_and_adverse_variants
    """
    area, _rainfall = _area_with_fifteen_accepted_samples()

    summary = _summary(area["id"], "SYSTEMATIC_RANDOM")

    assert_classification_summary(summary)
    assert summary["variant"] == "SYSTEMATIC_RANDOM"
    assert summary["sample_count"] == 15
    assert summary["mean_log10"] == 0.9451
    assert summary["geometric_mean_mpn"] == 8.8
    assert summary["p90_mpn"] == 98.8
    assert summary["eligible_classification"] == "RESTRICTED"
    assert summary["window_start_at"] == to_millis("2026-07-01T09:00:00Z")
    assert summary["window_end_at"] == to_millis("2026-07-24T06:00:00Z")


def test_adverse_condition_summary_reads_only_the_five_flagged_samples():
    """Restricting the same stored rows to the five `is_adverse_condition`
    samples moves `mean_log10` to 2.0573, the geometric mean to 114.1 and the
    p90 to 165.8, which the ladder reads as PROHIBITED because 114.1 exceeds the
    88.0 restricted geometric-mean limit. The two variants therefore diverge by
    105.3 MPN and by two classification ranks over identical data.

    Design: Difficulty/dual_variant_calc/area_stats_diverge_between_systematic_and_adverse_variants
    """
    area, _rainfall = _area_with_fifteen_accepted_samples()

    systematic = _summary(area["id"], "SYSTEMATIC_RANDOM")
    adverse = _summary(area["id"], "ADVERSE_CONDITION")

    assert_classification_summary(adverse)
    assert adverse["variant"] == "ADVERSE_CONDITION"
    assert adverse["sample_count"] == 5
    assert adverse["mean_log10"] == 2.0573
    assert adverse["geometric_mean_mpn"] == 114.1
    assert adverse["p90_mpn"] == 165.8
    assert adverse["eligible_classification"] == "PROHIBITED"
    assert adverse["window_start_at"] == to_millis("2026-07-20T06:00:00Z")
    assert adverse["window_end_at"] == to_millis("2026-07-24T06:00:00Z")

    assert round(adverse["geometric_mean_mpn"] - systematic["geometric_mean_mpn"], 1) == 105.3
    assert adverse["eligible_classification"] != systematic["eligible_classification"]


def test_only_the_systematic_random_figures_are_persisted_on_the_area():
    """`geometric_mean_mpn`, `p90_mpn` and `eligible_classification` on the
    growing-area record always hold the `SYSTEMATIC_RANDOM` figures, so the
    PROHIBITED adverse reading never drives the sample sweep: the cumulative
    systematic geometric mean never exceeds 14.0, `classification` stays
    APPROVED, and `harvest_status` is CLOSED_RAINFALL only because of the
    rainfall event.

    Design: Difficulty/dual_variant_calc/area_stats_diverge_between_systematic_and_adverse_variants
    """
    area, rainfall = _area_with_fifteen_accepted_samples()

    stored = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))

    assert stored["geometric_mean_mpn"] == 8.8
    assert stored["p90_mpn"] == 98.8
    assert stored["eligible_classification"] == "RESTRICTED"
    assert stored["accepted_sample_count"] == 15
    assert stored["classification"] == "APPROVED"
    assert stored["harvest_status"] == "CLOSED_RAINFALL"
    assert rainfall["triggered_closure"] is True
    assert stored["last_closure_started_at"] == to_millis(RAINFALL_OBSERVED_AT)


# --------------------------------------------------------------------------
# The same six steps over the smallest decision-capable window (PRD §3.2)
# --------------------------------------------------------------------------
from test_helpers import (  # noqa: E402  (appended section, existing header kept intact)
    validate_paginated,
    validate_success,
)

# Five identical MPN-2 samples on 2026-07-01 .. 2026-07-05 at 09:00Z, exactly
# MIN_SAMPLES_FOR_DECISION rows on five distinct calendar dates.
CLEAN_MPNS = [2, 2, 2, 2, 2]
CLEAN_WINDOW_START_AT = "2026-07-01T09:00:00Z"
CLEAN_WINDOW_END_AT = "2026-07-05T09:00:00Z"
RESAMPLED_AT = "2026-07-05T15:00:00Z"


def _area_with_five_clean_samples():
    """One area carrying exactly five accepted MPN-2 samples at ST-1, one per
    calendar date, so no ingest supersedes an earlier row and the window is
    decision-capable at precisely the minimum sample count."""
    set_clock(DW_CLOCK)
    area = create_growing_area(dw_area_payload())
    for offset, mpn in enumerate(CLEAN_MPNS):
        ingest_water_sample(area["id"], {
            "station_code": "ST-1",
            "collected_at": plus_days("2026-07-01", offset) + "T09:00:00Z",
            "fecal_coliform_mpn": mpn,
            "water_temp_c": 24.0,
            "salinity_ppt": 30.0,
        })
    return area


def _default_variant_summary(area_id):
    """Read the classification summary with no `variant` query parameter at all,
    so the endpoint has to supply its own default."""
    return api_client.get_classification_summary(area_id, AUTHORITY)


def test_classification_summary_returns_the_systematic_random_statistics_for_five_clean_samples():
    """Five identical MPN-2 rows make every rounding step hand-checkable: each
    log10 is 0.3010 to four places, so `mean_log10` is 0.3010 and the geometric
    mean is 10 ** 0.3010 = 2.0 to one place. The n-1 sample standard deviation of
    five identical logs is exactly 0.0000, so the `P90_Z` 1.28 term contributes
    nothing and `p90_mpn` collapses onto the geometric mean at 2.0. Both limbs of
    the APPROVED rung pass (2.0 <= 14.0 and 2.0 <= 43.0), so the eligible
    classification is APPROVED. `SYSTEMATIC_RANDOM` is the variant the endpoint
    assumes when the client sends none, and its figures are the ones the area
    record itself persists.

    Design: Corner/calculations/classification_summary_returns_the_systematic_random_statistics_for_five_clean_samples
    """
    area = _area_with_five_clean_samples()

    response = _default_variant_summary(area["id"])
    summary = validate_success(response)

    assert response.json()["response_type"] == "object"
    assert_classification_summary(summary)
    assert summary["variant"] == "SYSTEMATIC_RANDOM"
    assert summary["sample_count"] == 5
    assert summary["mean_log10"] == 0.3010
    assert summary["geometric_mean_mpn"] == 2.0
    assert summary["p90_mpn"] == 2.0
    assert summary["p90_mpn"] == summary["geometric_mean_mpn"]
    assert summary["eligible_classification"] == "APPROVED"
    assert summary["window_start_at"] == to_millis(CLEAN_WINDOW_START_AT)
    assert summary["window_end_at"] == to_millis(CLEAN_WINDOW_END_AT)

    stored = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))
    assert stored["geometric_mean_mpn"] == 2.0
    assert stored["p90_mpn"] == 2.0
    assert stored["eligible_classification"] == "APPROVED"
    assert stored["classification"] == "APPROVED"
    assert stored["harvest_status"] == "OPEN"


def test_superseded_samples_are_excluded_from_the_statistics_window():
    """Re-sampling ST-1 later on 2026-07-05 supersedes the earlier row for the
    same area, station and collection date rather than adding to it, so n stays 5
    and the window becomes {2, 2, 2, 2, 900}. The four 0.3010 logs and one 2.9542
    log average to `mean_log10` 0.8316, giving a geometric mean of 6.8 and, with
    an n-1 standard deviation of 1.1865, a p90 of 224.0. The ladder answers
    RESTRICTED: 6.8 clears the 14.0 approved geometric-mean limit but 224.0 blows
    past the 43.0 approved p90 limit, while 6.8 <= 88.0 and 224.0 <= 260.0 both
    hold on the restricted rung. The sample sweep is keyed on the geometric mean
    alone, and 6.8 is not above 14.0, so the area keeps its APPROVED
    classification and OPEN harvest status despite the RESTRICTED eligibility.

    The design recipe asserted the supersession through
    `GET .../water-samples?sample_status=SUPERSEDED`, but the PRD's endpoint
    table declares no filter parameters for that list, so the assertion is made
    against the unfiltered list instead: six rows in all, exactly one of them
    SUPERSEDED, and that one is the 2026-07-05T09:00:00Z MPN-2 row.

    Design: Corner/calculations/superseded_samples_are_excluded_from_the_statistics_window
    """
    area = _area_with_five_clean_samples()

    resample = validate_success(api_client.create_water_sample(area["id"], {
        "station_code": "ST-1",
        "collected_at": RESAMPLED_AT,
        "fecal_coliform_mpn": 900,
        "water_temp_c": 24.0,
        "salinity_ppt": 30.0,
    }, AUTHORITY), 201)
    summary = validate_success(_default_variant_summary(area["id"]))

    assert resample["sample_status"] == "ACCEPTED"

    assert_classification_summary(summary)
    assert summary["sample_count"] == 5
    assert summary["mean_log10"] == 0.8316
    assert summary["geometric_mean_mpn"] == 6.8
    assert summary["p90_mpn"] == 224.0
    assert summary["eligible_classification"] == "RESTRICTED"

    stored = get_success_data(api_client.get_growing_area(area["id"], AUTHORITY))
    assert stored["classification"] == "APPROVED"
    assert stored["harvest_status"] == "OPEN"
    assert stored["accepted_sample_count"] == 5
    assert stored["eligible_classification"] == "RESTRICTED"

    rows, meta = validate_paginated(
        api_client.list_water_samples(area["id"], AUTHORITY))
    superseded = [row for row in rows if row["sample_status"] == "SUPERSEDED"]
    assert meta["total_count"] == 6
    assert len(superseded) == 1
    assert superseded[0]["collected_at"] == to_millis(CLEAN_WINDOW_END_AT)
    assert superseded[0]["fecal_coliform_mpn"] == 2
