"""Two interval resources with deliberately different geometry: measurement
windows are half-open and excluded per provenance, while hold coverage intervals
are closed and demand more than a day of separation from every active neighbour.
"""

from test_helpers import (
    INVESTIGATOR,
    OFFICER,
    ApiErrorId,
    assert_cents,
    assert_funds,
    assert_instant_equals,
    assert_posture,
    assert_rate,
    canonical_instant,
    credit,
    evaluate,
    file_snapshot,
    file_violation,
    hold_payload,
    open_hold,
    open_investigation,
    publish_rule,
    read_holds,
    read_seller,
    register_seller,
    release_hold,
    set_clock,
    snapshot_payload,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00.000Z"

# The straddling window, filed twice under two different provenances.
STRADDLE_START = "2026-06-15T00:00:00.000Z"
STRADDLE_END = "2026-07-15T00:00:00.000Z"
STRADDLE_COUNTERS = {
    "order_volume": 400,
    "delivered_or_refunded_volume": 390,
    "defect_claims_pending": 11,
    "defect_claims_substantiated": 1,
    "late_shipments": 4,
    "pre_fulfillment_cancellations": 2,
    "shipments_total": 395,
    "shipments_with_valid_tracking": 390,
}


# --------------------------------------------------------------------------
# Half-open measurement windows, excluded per (seller, source)
# --------------------------------------------------------------------------
def _seller_with_two_touching_windows(api):
    """June and July under PLATFORM_PIPELINE, the second starting exactly where the
    first ends. No rule and no violation exists, so nothing but a snapshot or an
    evaluation can move this seller's postures."""
    set_clock(api, CLOCK)
    seller = register_seller(
        api, legal_name="Ambervale Bath LLC", email="ops@ambervale-bath.example",
        tax_id_hash="TAX-AM-0001", payout_bank_token="BANK-AM-0001",
        address_fingerprint="ADDR-AM-0001",
    )
    june = file_snapshot(
        api, seller["id"], "2026-06-01T00:00:00.000Z", "2026-07-01T00:00:00.000Z",
        order_volume=900, delivered_or_refunded_volume=880, defect_claims_pending=3,
        defect_claims_substantiated=2, late_shipments=10, pre_fulfillment_cancellations=4,
        shipments_total=890, shipments_with_valid_tracking=880, source="PLATFORM_PIPELINE",
    )
    july = file_snapshot(
        api, seller["id"], "2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z",
        order_volume=950, delivered_or_refunded_volume=930, defect_claims_pending=7,
        defect_claims_substantiated=3, late_shipments=12, pre_fulfillment_cancellations=5,
        shipments_total=940, shipments_with_valid_tracking=930, source="PLATFORM_PIPELINE",
    )
    return seller, june, july


def _straddling_attempt(api, seller_id, source):
    return api.create_snapshot(
        snapshot_payload(seller_id, STRADDLE_START, STRADDLE_END, source=source,
                         **STRADDLE_COUNTERS),
        OFFICER,
    )


def test_touching_windows_tile_but_a_straddling_one_of_the_same_source_is_refused(api):
    """PRD §3.3: "Two windows of the same seller from the same `source` may not
    overlap; an attempt to file one that does is refused with
    `ERR_SNAPSHOT_WINDOW_OVERLAP`. Because the intervals are half-open, windows
    that merely touch do not overlap: a new window whose `window_start` equals an
    existing window's `window_end` is accepted."

    Design: Difficulty/resource_temporal_overlap/snapshot_half_open_windows_touch_legally_but_overlap_is_rejected_per_source
    """
    seller, june, july = _seller_with_two_touching_windows(api)

    # Both rows exist: July's window_start is exactly June's window_end.
    assert_instant_equals(july["window_start"], june["window_end"], "window_start")
    filed = validate_success(api.list_seller_snapshots(seller["id"], OFFICER))
    assert {row["id"] for row in filed} == {june["id"], july["id"]}

    response = _straddling_attempt(api, seller["id"], "PLATFORM_PIPELINE")

    validate_error(response, ApiErrorId.SNAPSHOT_WINDOW_OVERLAP.value)
    still_filed = validate_success(api.list_seller_snapshots(seller["id"], OFFICER))
    assert len(still_filed) == 2, f"the refused window was filed anyway: {still_filed}"


def test_the_identical_window_is_free_under_the_other_provenance(api):
    """PRD §3.3: "The exclusion is scoped to the pair of seller and provenance, so
    a `MANUAL_CORRECTION` window is free to cover exactly the same period as a
    `PLATFORM_PIPELINE` window of the same seller — that is precisely how a
    correction is filed."

    Design: Difficulty/resource_temporal_overlap/snapshot_half_open_windows_touch_legally_but_overlap_is_rejected_per_source
    """
    seller, _, _ = _seller_with_two_touching_windows(api)
    validate_error(
        _straddling_attempt(api, seller["id"], "PLATFORM_PIPELINE"),
        ApiErrorId.SNAPSHOT_WINDOW_OVERLAP.value,
    )

    correction = validate_success(
        _straddling_attempt(api, seller["id"], "MANUAL_CORRECTION"), 201
    )

    assert correction["source"] == "MANUAL_CORRECTION"
    assert_instant_equals(correction["window_start"], STRADDLE_START, "window_start")
    assert_instant_equals(correction["window_end"], STRADDLE_END, "window_end")

    # The refreshed exposure figure reads the greatest window_end, which is the
    # July row's 2026-08-01, and not the row that happens to be newest by creation.
    after = read_seller(api, seller["id"])
    assert after["open_defect_claim_units"] == 7


def test_the_input_set_truncates_across_both_provenances_by_window_end(api):
    """PRD §3.4: "Candidates are ordered by `window_end` descending, ties broken by
    `created_at` ascending, and the ordered list is truncated to its first two
    rows."

    Design: Difficulty/resource_temporal_overlap/snapshot_half_open_windows_touch_legally_but_overlap_is_rejected_per_source
    """
    seller, _, _ = _seller_with_two_touching_windows(api)
    validate_success(_straddling_attempt(api, seller["id"], "MANUAL_CORRECTION"), 201)

    evaluation = evaluate(api, seller["id"], INVESTIGATOR)

    # July (window_end 2026-08-01) and the correction (2026-07-15) survive the
    # truncation; the June row falls outside it entirely.
    assert evaluation["input_snapshot_count"] == 2
    assert_instant_equals(evaluation["input_window_start"], STRADDLE_START,
                          "input_window_start")
    assert_instant_equals(evaluation["input_window_end"], "2026-08-01T00:00:00.000Z",
                          "input_window_end")
    assert evaluation["order_volume_final"] == 1350
    # (3 + 1) / (930 + 390) = 0.0030303, rounded half-up to four decimals.
    assert_rate(evaluation["odr_final"], "0.0030", "odr_final")
    assert evaluation["breached_metrics"] == []
    assert evaluation["metric_tier"] == "HEALTHY"

    # A fixture built only to exercise interval geometry leaves the postures alone.
    assert_posture(read_seller(api, seller["id"]), enforcement_state="ACTIVE",
                   disbursement_state="NORMAL")


# --------------------------------------------------------------------------
# Closed coverage intervals with a twenty-four-hour buffer
# --------------------------------------------------------------------------
def _seller_with_one_active_coverage_interval(api):
    """300000 cents credited, one violation left UNDER_INVESTIGATION so the funds
    posture authorises reserves at TIER_1, and h1 covering [08-01, 08-10] for
    10 percent of the balance."""
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code="LA-INT-1", category="LISTING_ACCURACY", base_severity_weight=1.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = register_seller(
        api, legal_name="Bellhaven Toys LLC", email="ops@bellhaven-toys.example",
        tax_id_hash="TAX-BE-0001", payout_bank_token="BANK-BE-0001",
        address_fingerprint="ADDR-BE-0001",
    )
    credit(api, seller["id"], 300000, "PAYOUT-CYCLE-2026-07-F")
    violation = file_violation(
        api, seller["id"], rule["id"], reporter_type="BUYER",
        evidence_reference="EV-BE-0001",
    )
    open_investigation(api, violation["id"])
    first = open_hold(
        api, seller["id"], CLOCK, "2026-08-10T00:00:00.000Z", reserve_basis="ROLLING"
    )
    return seller, first


def _coverage_attempt(api, seller_id, coverage_start, coverage_end):
    """The version is re-read immediately beforehand so the stage-11 concurrency
    check can never fire in place of the interval-geometry check."""
    return api.create_hold(
        hold_payload(
            seller_id, coverage_start, coverage_end,
            read_seller(api, seller_id, INVESTIGATOR)["version"],
            hold_type="RESERVE", reserve_basis="ROLLING",
        ),
        INVESTIGATOR,
    )


def test_a_contained_interval_is_an_overlap_and_a_forty_eight_hour_gap_is_not(api):
    """PRD §3.9: "Coverage intervals are **closed** at both ends, so
    `coverage_start` and `coverage_end` are both inclusive, and `coverage_end` must
    be strictly later than `coverage_start`."

    Design: Difficulty/resource_temporal_overlap/hold_coverage_closed_intervals_require_buffer_separation
    """
    seller, first = _seller_with_one_active_coverage_interval(api)
    assert_cents(first["held_amount_cents"], 30000, "held_amount_cents")
    assert first["risk_tier"] == "TIER_1"
    assert_funds(read_seller(api, seller["id"]), available=270000, held=30000,
                 credited=300000, debited=0)

    contained = _coverage_attempt(api, seller["id"], "2026-08-03T00:00:00.000Z",
                                  "2026-08-05T00:00:00.000Z")

    # [08-03, 08-05] sits wholly inside the closed interval [08-01, 08-10].
    validate_error(contained, ApiErrorId.HOLD_COVERAGE_OVERLAP.value)

    second = open_hold(
        api, seller["id"], "2026-08-12T00:00:00.000Z", "2026-08-20T00:00:00.000Z",
        reserve_basis="ROLLING",
    )

    # Forty-eight hours clear of 08-10, and priced at 10 percent of the already
    # reduced 270000 rather than of the original 300000.
    assert_cents(second["held_amount_cents"], 27000, "held_amount_cents")
    assert second["reserve_basis"] == "ROLLING"
    assert second["risk_tier"] == "TIER_1"
    assert_funds(read_seller(api, seller["id"]), available=243000, held=57000,
                 credited=300000, debited=0)


def test_a_released_interval_stops_reserving_the_period_it_covered(api):
    """PRD §3.9: "Unlike measurement windows, coverage intervals may not merely
    avoid overlapping: a new interval must be separated from the interval of every
    other `ACTIVE` hold of the same seller by strictly more than twenty-four hours,
    and a new interval that touches, overlaps, or sits within a full day of an
    existing active one is refused with `ERR_HOLD_COVERAGE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/hold_coverage_closed_intervals_require_buffer_separation
    """
    seller, first = _seller_with_one_active_coverage_interval(api)
    open_hold(api, seller["id"], "2026-08-12T00:00:00.000Z", "2026-08-20T00:00:00.000Z",
              reserve_basis="ROLLING")

    # inv-1 created the hold, so co-1 is the one who may release it by hand.
    released = release_hold(api, first["id"], "MANUAL", OFFICER)
    assert released["state"] == "RELEASED"
    assert released["release_reason"] == "MANUAL"
    assert_funds(read_seller(api, seller["id"]), available=273000, held=27000,
                 credited=300000, debited=0)

    third = open_hold(
        api, seller["id"], "2026-08-05T00:00:00.000Z", "2026-08-09T00:00:00.000Z",
        reserve_basis="ROLLING",
    )

    # [08-05, 08-09] sits inside the interval h1 used to cover, which is legal now
    # that h1 has left ACTIVE, and is priced at 10 percent of 273000.
    assert third["state"] == "ACTIVE"
    assert_cents(third["held_amount_cents"], 27300, "held_amount_cents")
    assert canonical_instant(third["coverage_start"]) > \
        canonical_instant(first["coverage_start"])
    assert canonical_instant(third["coverage_end"]) < \
        canonical_instant(first["coverage_end"])

    after = read_seller(api, seller["id"])
    # The whole walk is 300000 -> 270000 -> 243000 -> 273000 -> 245700, and the
    # funds identity of §2.6 holds at every step.
    assert_funds(after, available=245700, held=54300, credited=300000, debited=0)
    active = read_holds(api, params={"seller_id": seller["id"], "state": "ACTIVE"})
    assert len(active) == 2, f"expected two active holds, got {active}"
