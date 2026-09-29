"""Growing-area closure and reopening (PRD §3.1, §3.2, §3.3).

A growing area carries two independent state dimensions on one row --
`classification` (the administrative sanitary survey verdict) and
`harvest_status` (the operational open/closed flag) -- plus an inclusive
`closure_reopen_eligible_at` instant and a validation ladder in which the
prohibited-area safety rung is ordered ahead of the temporal and clean-sample
rungs.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_growing_area,
    dw_area_payload,
    DW_CLOCK,
    get_success_data,
    ingest_rainfall_event,
    ingest_water_sample,
    iso,
    plus_days,
    record_classification_decision,
    set_clock,
    TEST_USERS,
    to_millis,
    validate_error,
    validate_success,
)

AUTHORITY = TEST_USERS["authority_headers"]

RAIN_AT = iso(2026, 7, 15)
REOPEN_ELIGIBLE_AT = iso(2026, 7, 19)


def _sample(area_id, collected_at, mpn):
    return ingest_water_sample(area_id, {
        "station_code": "ST-1",
        "collected_at": collected_at,
        "fecal_coliform_mpn": mpn,
        "water_temp_c": 24.0,
        "salinity_ppt": 30.0,
    })


def _read(area_id):
    return get_success_data(api_client.get_growing_area(area_id, AUTHORITY))


def _conditionally_approved_area():
    """An area with a conditional management plan on file, five clean accepted
    samples and an explicit CONDITIONALLY_APPROVED classification decision."""
    set_clock(DW_CLOCK)
    area = create_growing_area(
        dw_area_payload(conditional_management_plan_on_file=True))
    for offset in range(5):
        _sample(area["id"], plus_days("2026-07-01", offset) + "T09:00:00Z", 2)
    area = _read(area["id"])
    record_classification_decision(
        area, "CONDITIONALLY_APPROVED",
        {"decision_note": "conditional management plan in force"})
    return _read(area["id"])


def _rainfall_closed_conditional_area():
    area = _conditionally_approved_area()
    rainfall = ingest_rainfall_event(area["id"], {
        "gauge_code": "RG-7",
        "observed_at": RAIN_AT,
        "inches_24h": 1.50,
    })
    return _read(area["id"]), rainfall


def test_rainfall_closure_moves_harvest_status_without_touching_classification():
    """A rainfall reading at or above `rainfall_closure_threshold_in` sets
    `harvest_status` to CLOSED_RAINFALL and stamps `last_closure_started_at` and
    `closure_reopen_eligible_at` = `observed_at` + `rainfall_closure_hours` 96,
    while `classification` stays CONDITIONALLY_APPROVED: the combined state
    (CONDITIONALLY_APPROVED, CLOSED_RAINFALL) is reachable, so neither dimension
    implies the other.

    Design: Difficulty/non_linear_state_machine/growing_area_classification_and_harvest_status_evolve_independently
    """
    area, rainfall = _rainfall_closed_conditional_area()

    assert area["harvest_status"] == "CLOSED_RAINFALL"
    assert area["classification"] == "CONDITIONALLY_APPROVED"
    assert area["last_closure_started_at"] == to_millis(RAIN_AT)
    assert area["closure_reopen_eligible_at"] == to_millis(REOPEN_ELIGIBLE_AT)
    assert area["consecutive_clean_samples"] == 0
    assert rainfall["triggered_closure"] is True
    assert rainfall["voided_authorization_count"] == 0


def test_clean_samples_accumulate_while_the_area_stays_closed():
    """Ingesting samples during the closure advances `consecutive_clean_samples`
    and `accepted_sample_count` and recomputes the statistics, but does not by
    itself reopen the area: with 2 x5 then 5 x3 the geometric mean is 2.8 and
    the p90 is 5.2, `eligible_classification` is APPROVED (2.8 stays inside the
    14.0 approved limit so no sample sweep fires), and `harvest_status` is still
    CLOSED_RAINFALL.

    Design: Difficulty/non_linear_state_machine/growing_area_classification_and_harvest_status_evolve_independently
    """
    area, _rainfall = _rainfall_closed_conditional_area()
    for offset in range(3):
        _sample(area["id"], plus_days("2026-07-16", offset) + "T09:00:00Z", 5)

    area = _read(area["id"])

    assert area["consecutive_clean_samples"] == 3
    assert area["accepted_sample_count"] == 8
    assert area["geometric_mean_mpn"] == 2.8
    assert area["p90_mpn"] == 5.2
    assert area["eligible_classification"] == "APPROVED"
    assert area["harvest_status"] == "CLOSED_RAINFALL"
    assert area["classification"] == "CONDITIONALLY_APPROVED"


def test_reopen_completes_the_cycle_and_leaves_classification_pinned():
    """The reopen returns `harvest_status` to OPEN, resets
    `consecutive_clean_samples` to 0 and clears `closure_reopen_eligible_at` to
    null while retaining `last_closure_started_at` for the audit trail. Across
    the whole OPEN -> CLOSED_RAINFALL -> OPEN cycle `classification` never
    leaves CONDITIONALLY_APPROVED.

    Design: Difficulty/non_linear_state_machine/growing_area_classification_and_harvest_status_evolve_independently
    """
    area, _rainfall = _rainfall_closed_conditional_area()
    for offset in range(3):
        _sample(area["id"], plus_days("2026-07-16", offset) + "T09:00:00Z", 5)

    reopened = validate_success(api_client.reopen_growing_area(
        area["id"], {"reopen_note": "three clean samples on file"}, AUTHORITY))

    assert reopened["harvest_status"] == "OPEN"
    assert reopened["consecutive_clean_samples"] == 0
    assert reopened["closure_reopen_eligible_at"] is None
    assert reopened["classification"] == "CONDITIONALLY_APPROVED"
    assert reopened["last_closure_started_at"] == to_millis(RAIN_AT)
    assert _read(area["id"])["harvest_status"] == "OPEN"


# --------------------------------------------------------------------------
# The inclusive reopen-eligibility instant
# --------------------------------------------------------------------------
BOUNDARY_CLOSURE_AT = iso(2026, 8, 5)
BOUNDARY_ELIGIBLE_AT = iso(2026, 8, 9)
ONE_SECOND_EARLY = "2026-08-08T23:59:59Z"


def _area_closed_with_three_clean_samples():
    """A rainfall closure at 2026-08-05T00:00:00Z followed by exactly
    `reopen_sample_count_required` 3 clean samples, leaving only the temporal
    rung between the area and a reopen."""
    set_clock(BOUNDARY_CLOSURE_AT)
    area = create_growing_area(dw_area_payload())
    ingest_rainfall_event(area["id"], {
        "gauge_code": "RG-7",
        "observed_at": BOUNDARY_CLOSURE_AT,
        "inches_24h": 1.50,
    })
    set_clock("2026-08-08T12:00:00Z")
    for offset in range(3):
        _sample(area["id"], plus_days("2026-08-06", offset) + "T09:00:00Z", 5)
    return area


def test_reopen_exactly_at_the_reopen_eligible_instant_succeeds():
    """`closure_reopen_eligible_at` is 2026-08-05T00:00:00Z plus
    `rainfall_closure_hours` 96 = 2026-08-09T00:00:00Z, and the temporal
    comparison is inclusive, so a reopen with the clock at exactly that instant
    succeeds. Only three accepted samples are on file, so
    `eligible_classification` is INSUFFICIENT_DATA while `classification`
    remains the registration default APPROVED.

    Design: Difficulty/boundary_precision_check/reopen_exactly_at_reopen_eligible_at_succeeds
    """
    area = _area_closed_with_three_clean_samples()
    set_clock(BOUNDARY_ELIGIBLE_AT)

    reopened = validate_success(api_client.reopen_growing_area(
        area["id"], {"reopen_note": "96 hours elapsed, three clean samples"},
        AUTHORITY))

    assert reopened["harvest_status"] == "OPEN"
    assert reopened["consecutive_clean_samples"] == 0
    assert reopened["closure_reopen_eligible_at"] is None
    assert reopened["last_closure_started_at"] == to_millis(BOUNDARY_CLOSURE_AT)
    assert reopened["classification"] == "APPROVED"
    assert reopened["eligible_classification"] == "INSUFFICIENT_DATA"
    assert reopened["accepted_sample_count"] == 3


def test_reopen_one_second_before_the_eligible_instant_is_too_early():
    """One second short of the same instant the identical call is rejected with
    ERR_REOPEN_TOO_EARLY, which fixes the comparison as `>=` rather than `>` and
    leaves the closure state untouched.

    Design: Difficulty/boundary_precision_check/reopen_exactly_at_reopen_eligible_at_succeeds
    """
    area = _area_closed_with_three_clean_samples()
    set_clock(ONE_SECOND_EARLY)

    response = api_client.reopen_growing_area(
        area["id"], {"reopen_note": "96 hours elapsed, three clean samples"},
        AUTHORITY)

    validate_error(response, ApiErrorId.ERR_REOPEN_TOO_EARLY, 409)
    unchanged = _read(area["id"])
    assert unchanged["harvest_status"] == "CLOSED_RAINFALL"
    assert unchanged["consecutive_clean_samples"] == 3
    assert unchanged["closure_reopen_eligible_at"] == to_millis(BOUNDARY_ELIGIBLE_AT)


# --------------------------------------------------------------------------
# Ladder priority when three reopen rungs are violated at once
# --------------------------------------------------------------------------
def _prohibited_area_from_sample_sweep():
    """Five 200-MPN samples drive the automatic sample sweep: at the fifth
    sample the window holds `MIN_SAMPLES_FOR_DECISION` 5 rows, the geometric
    mean 200.0 exceeds every approved limit, and the eligible classification
    PROHIBITED outranks the current APPROVED, so the area is downgraded and
    closed."""
    set_clock(DW_CLOCK)
    area = create_growing_area(dw_area_payload())
    for offset in range(5):
        _sample(area["id"], plus_days("2026-07-01", offset) + "T09:00:00Z", 200)
    return _read(area["id"])


def test_reopening_a_prohibited_area_answers_the_safety_rung_first():
    """The reopen violates three rungs at once -- the area is PROHIBITED, the
    clock has not reached `closure_reopen_eligible_at` 2026-08-05T00:00:00Z, and
    zero clean samples are on file. All three carry HTTP 409, so only the ladder
    order can decide, and the response is the safety rung
    ERR_AREA_PROHIBITED rather than either of the two later rungs.

    Design: Difficulty/priority_pair_validation_conflict/reopen_prohibited_area_before_window_returns_safety_over_temporal
    """
    area = _prohibited_area_from_sample_sweep()

    response = api_client.reopen_growing_area(
        area["id"], {"reopen_note": "operator requests reopening"}, AUTHORITY)

    body = validate_error(response, ApiErrorId.ERR_AREA_PROHIBITED, 409)
    assert body["error_id"] != ApiErrorId.ERR_REOPEN_TOO_EARLY
    assert body["error_id"] != ApiErrorId.ERR_INSUFFICIENT_CLEAN_SAMPLES


def test_rejected_reopen_leaves_the_swept_prohibited_state_intact():
    """The sample sweep left `classification` PROHIBITED with `harvest_status`
    CLOSED_SAMPLE_FAILURE, `closure_reopen_eligible_at` 96 hours after the
    sweep instant and the five-sample statistics at 200.0/200.0; the rejected
    reopen changes none of it.

    Design: Difficulty/priority_pair_validation_conflict/reopen_prohibited_area_before_window_returns_safety_over_temporal
    """
    area = _prohibited_area_from_sample_sweep()
    api_client.reopen_growing_area(
        area["id"], {"reopen_note": "operator requests reopening"}, AUTHORITY)

    after = _read(area["id"])
    assert after["harvest_status"] == "CLOSED_SAMPLE_FAILURE"
    assert after["classification"] == "PROHIBITED"
    assert after["eligible_classification"] == "PROHIBITED"
    assert after["closure_reopen_eligible_at"] == to_millis(iso(2026, 8, 5))
    assert after["consecutive_clean_samples"] == 0
    assert after["geometric_mean_mpn"] == 200.0
    assert after["p90_mpn"] == 200.0
    assert after["accepted_sample_count"] == 5
