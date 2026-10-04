"""The two dual-variant calculations and the two combinatorial formulas.

The ETA model switches between SCHEDULED_BASELINE and TELEMETRY_BLENDED on the
presence of telemetry, and the connection carries two deliberately divergent
quality views. The combinatorial instances pin the nested rounding order of
the authoritative quality score and the tiered detention exposure with its
adherent grace.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    fixtures,
)
from test_helpers import factories as f
from test_helpers.test_users import NETWORK_OPS_HEADERS


def _active_connection_world(api, channel="TELEMATICS"):
    """Clock at the base instant plus a carrier whose connection scored 100 and is ACTIVE."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_active_connection(api, carrier, channel=channel)
    shipper = fixtures.create_shipper(api)
    return carrier, connection, shipper


# ═══ dual_variant_calc / eta_scheduled_baseline_vs_telemetry_blended_diverge ═


def test_baseline_and_blended_variants_diverge_on_identical_plans(api):
    """Two shipments with identical planned timestamps land on different ETAs.

    PRD: "When a shipment has no non-voided tracking events, the
    `SCHEDULED_BASELINE` variant applies: `eta_at` equals `planned_arrival_at`,
    ignoring telemetry entirely, and `eta_variant` reads `SCHEDULED_BASELINE`."
    PRD: "As soon as at least one non-voided event exists, the
    `TELEMETRY_BLENDED` variant applies and `eta_variant` reads
    `TELEMETRY_BLENDED`."
    Design: Difficulty/dual_variant_calc/eta_scheduled_baseline_vs_telemetry_blended_diverge
    """
    carrier, connection, shipper = _active_connection_world(api)
    plan = {
        "planned_departure_at": "2026-09-01T00:00:00Z",
        "planned_arrival_at": "2026-09-03T00:00:00Z",
    }
    ship_a = fixtures.create_shipment(
        api, shipper, carrier, connection, tracking_reference="TRK-A", **plan
    )
    ship_b = fixtures.create_shipment(
        api, shipper, carrier, connection, tracking_reference="TRK-B", **plan
    )
    fixtures.ingest_event(api, ship_b, "2026-09-01T12:00:00Z", "DEPARTED")
    fixtures.ingest_event(api, ship_b, "2026-09-01T18:00:00Z", "DELAY_REPORTED", delay_minutes=180)

    read_a = fixtures.read_shipment(api, ship_a["id"])
    read_b = fixtures.read_shipment(api, ship_b["id"])

    assert read_a["eta_variant"] == "SCHEDULED_BASELINE"
    assert_instant_equal(read_a["eta_at"], "2026-09-03T00:00:00Z", "baseline eta")
    assert read_b["eta_variant"] == "TELEMETRY_BLENDED"
    # E = 18:00, p = 1080/2880, R*(1-p) = 1800 minutes, open delay 180.
    assert_instant_equal(read_b["eta_at"], "2026-09-03T03:00:00Z", "blended eta")
    # Quality 100, FRESH: halfwidth = 120 * (1 + 0/100).
    assert read_b["eta_confidence_halfwidth_minutes"] == 120


def test_voiding_the_only_event_returns_the_variant_to_baseline(api):
    """The variant selection replays the remaining event set after a void.

    PRD: "Voiding an event is a retroactive correction: the event is excluded
    from the replay set and the shipment's status is re-derived from what
    remains."
    PRD: "When a shipment has no non-voided tracking events, the
    `SCHEDULED_BASELINE` variant applies: `eta_at` equals `planned_arrival_at`,
    ignoring telemetry entirely, and `eta_variant` reads `SCHEDULED_BASELINE`."
    Design: Difficulty/dual_variant_calc/eta_scheduled_baseline_vs_telemetry_blended_diverge
    """
    carrier, connection, shipper = _active_connection_world(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    event = fixtures.ingest_event(api, shipment, "2026-09-01T12:00:00Z", "DEPARTED")

    blended = fixtures.read_shipment(api, shipment["id"])
    assert blended["eta_variant"] == "TELEMETRY_BLENDED"
    assert blended["tracking_status"] == "IN_TRANSIT"

    validate_success(api.void_event(shipment["id"], event["id"], NETWORK_OPS_HEADERS))

    reverted = fixtures.read_shipment(api, shipment["id"])
    assert reverted["eta_variant"] == "SCHEDULED_BASELINE"
    assert_instant_equal(reverted["eta_at"], "2026-09-03T00:00:00Z", "eta after void")
    assert reverted["tracking_status"] == "BOOKED"


# ═══ dual_variant_calc / quality_score_instantaneous_vs_epoch_windowed_diverge ═


def _two_heartbeat_testing_connection(api, completeness):
    """A TESTING TMS connection with two on-time heartbeats of one completeness.

    Heartbeats at 2026-09-01T10:00 and 2026-09-02T00:00; the caller then runs
    the checkpoint at 2026-09-05T04:00, a 6000-minute window with expected
    count floor(6000/240) = 25 and actual count 2.
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    fixtures.set_clock(api, "2026-09-01T10:00:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-01T10:00:00Z", completeness=completeness)
    fixtures.set_clock(api, "2026-09-02T00:00:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-02T00:00:00Z", completeness=completeness)
    fixtures.set_clock(api, "2026-09-05T04:00:00Z")
    return connection


def test_epoch_and_instantaneous_scores_diverge_on_identical_raw_data(api):
    """The same two heartbeats score 70 epoch-windowed and 92 instantaneous.

    PRD: "The final score is the round-half-up of the weighted blend: 40
    percent timeliness, 35 percent completeness, 25 percent cadence."
    PRD: "it is the round-half-up of 60 percent of the timeliness
    component — 100 when the heartbeat was `on_time`, 0 otherwise — plus 40
    percent of the heartbeat's `payload_completeness_pct`."
    PRD: "for identical raw data the two views can and do diverge, and only the
    authoritative one gates activation, feeds confidence intervals, and colors
    `health_status`."
    Design: Difficulty/dual_variant_calc/quality_score_instantaneous_vs_epoch_windowed_diverge
    """
    connection = _two_heartbeat_testing_connection(api, completeness=80)
    fixtures.run_checkpoint(api)

    read = fixtures.read_connection(api, connection["id"])
    # t = 100, c = 80, d = round(100 * 2/25) = 8 -> round(40 + 28 + 2) = 70.
    assert read["data_quality_score"] == 70
    # Latest heartbeat on time, completeness 80 -> round(60 + 32) = 92.
    assert read["instantaneous_quality_score"] == 92
    assert read["health_status"] == "HEALTHY"
    assert read["data_quality_score"] != read["instantaneous_quality_score"]


def test_instantaneous_moves_at_ingest_while_authoritative_waits_for_checkpoint(api):
    """Only the checkpoint advances the authoritative score.

    PRD: "Each ingest updates the connection's `last_heartbeat_at` and
    recomputes the `instantaneous_quality_score`."
    PRD: "The authoritative `data_quality_score` is computed per non-`RETIRED`
    connection at each ops-run checkpoint."
    Design: Difficulty/dual_variant_calc/quality_score_instantaneous_vs_epoch_windowed_diverge
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")

    before = fixtures.read_connection(api, connection["id"])
    assert before["data_quality_score"] is None
    assert before["instantaneous_quality_score"] is None

    fixtures.post_heartbeat(api, connection, "2026-09-01T00:00:00Z", completeness=80)
    after_ingest = fixtures.read_connection(api, connection["id"])
    # Instantaneous reacts immediately: round(0.60*100 + 0.40*80) = 92.
    assert after_ingest["instantaneous_quality_score"] == 92
    # The authoritative score stays null until the first checkpoint scores it.
    assert after_ingest["data_quality_score"] is None

    fixtures.set_clock(api, "2026-09-01T00:15:00Z")
    fixtures.run_checkpoint(api)
    after_run = fixtures.read_connection(api, connection["id"])
    assert after_run["data_quality_score"] is not None


# ═══ combinatorial_formula / quality_score_per_dimension_rounding_order ═


def test_nested_rounding_rounds_each_dimension_before_the_blend(api):
    """Cadence 33.33 rounds to 33 before the weighted blend yields 83.

    PRD: "Three dimension values are computed over that window, then each
    is individually rounded half-up to a whole number before being combined
    (nested rounding — this order is pinned): timeliness is the percentage
    of in-window heartbeats that were `on_time`; completeness is the average
    `payload_completeness_pct` across in-window heartbeats; cadence adherence
    compares the heartbeat count against the expected count, where the expected
    count is the whole-window minutes divided by `cadence_minutes` rounded
    down, and the adherence percentage is the actual count divided by the
    expected count capped at 1, times 100."
    PRD: "The final score is the round-half-up of the weighted blend: 40
    percent timeliness, 35 percent completeness, 25 percent cadence."
    Design: Difficulty/combinatorial_formula/quality_score_per_dimension_rounding_order
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    fixtures.set_clock(api, "2026-09-01T10:00:00Z")
    fixtures.post_heartbeat(api, connection, "2026-09-01T10:00:00Z", completeness=100)
    fixtures.set_clock(api, "2026-09-01T12:00:00Z")
    fixtures.run_checkpoint(api)

    read = fixtures.read_connection(api, connection["id"])
    # Window 720 minutes, expected floor(720/240) = 3, total 1:
    # t = 100, c = 100, d = round(33.33) = 33 -> round(40 + 35 + 8.25) = 83.
    assert read["data_quality_score"] == 83
    assert read["health_status"] == "HEALTHY"


def test_timeliness_dimension_flips_at_exactly_one_cadence_of_lag(api):
    """A gap of exactly cadence_minutes is on time; one minute more is not.

    PRD: "A heartbeat is considered `on_time` when the gap between its
    `recorded_at` ingest timestamp and the carrier-claimed `reported_at` send
    time is at most the connection's cadence."
    PRD: "timeliness is the percentage of in-window heartbeats that were
    `on_time`; completeness is the average `payload_completeness_pct` across
    in-window heartbeats; cadence adherence compares the heartbeat count against the expected
    count, where the expected count is the whole-window minutes divided by
    `cadence_minutes` rounded down, and the adherence percentage is the actual
    count divided by the expected count capped at 1, times 100."
    Design: Difficulty/combinatorial_formula/quality_score_per_dimension_rounding_order
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier_a = fixtures.create_carrier(api, carrier_name="OnTimeCo", scac_code="ONTA")
    conn_a = fixtures.create_testing_connection(api, carrier_a, channel="TMS")
    carrier_b = fixtures.create_carrier(api, carrier_name="LateCo", scac_code="LATB")
    conn_b = fixtures.create_testing_connection(api, carrier_b, channel="TMS")

    # Gap of exactly 240 minutes (the TMS cadence): on time.
    fixtures.set_clock(api, "2026-09-01T14:00:00Z")
    hb_a = fixtures.post_heartbeat(api, conn_a, "2026-09-01T10:00:00Z", completeness=100)
    # Gap of 241 minutes: late.
    fixtures.set_clock(api, "2026-09-01T14:01:00Z")
    hb_b = fixtures.post_heartbeat(api, conn_b, "2026-09-01T10:00:00Z", completeness=100)

    assert hb_a["on_time"] is True
    assert hb_b["on_time"] is False

    fixtures.run_checkpoint(api)
    read_a = fixtures.read_connection(api, conn_a["id"])
    read_b = fixtures.read_connection(api, conn_b["id"])
    # Both windows 841 minutes, expected floor(841/240) = 3, total 1, d = 33.
    assert read_a["data_quality_score"] == 83  # t = 100
    # t = 0 -> round(0 + 35 + 8.25) = 43, which is DEGRADED (>= 40, < 70).
    assert read_b["data_quality_score"] == 43
    assert read_b["health_status"] == "DEGRADED"


# ═══ combinatorial_formula / detention_exposure_tiered_free_time_and_adherence_grace ═


def _facility_with_two_appointments(api):
    """Facility + TESTING connection + TRUCKLOAD shipment, nothing booked."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    carrier = fixtures.create_carrier(api)
    connection = fixtures.create_testing_connection(api, carrier, channel="TMS")
    shipper = fixtures.create_shipper(api)
    shipment = fixtures.create_shipment(api, shipper, carrier, connection)
    facility = fixtures.create_facility(api)
    return carrier, shipment, facility


def test_adherent_grace_flips_the_tiered_exposure_result(api):
    """Adherent 120-minute dwell exposes 0; non-adherent 210 exposes 90.

    PRD: "Detention works from a per-mode free-time allowance — 240 minutes
    for `OCEAN`, 360 for `RAIL`, 0 for `PARCEL`, and 120 for `TRUCKLOAD` — to
    which an adherent arrival adds a 15-minute grace; the exposure is the dwell
    minus that allowance, floored at zero."
    PRD: "`adherent` is true exactly when the actual arrival falls within
    the half-open window — on or after `window_start` and strictly before
    `window_end`; and `exposure_minutes` is the detention exposure."
    Design: Difficulty/combinatorial_formula/detention_exposure_tiered_free_time_and_adherence_grace
    """
    carrier, shipment, facility = _facility_with_two_appointments(api)
    appt_x = fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z"
    )
    appt_y = fixtures.book_appointment(
        api, facility, shipment, "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z"
    )

    done_x = fixtures.complete_appointment(
        api, appt_x, carrier["id"], "2026-09-01T10:30:00Z", "2026-09-01T12:30:00Z"
    )
    done_y = fixtures.complete_appointment(
        api, appt_y, carrier["id"], "2026-09-02T11:30:00Z", "2026-09-02T15:00:00Z"
    )

    # Adherent: free 120 + 15 grace = 135 >= dwell 120 -> exposure 0.
    assert done_x["adherent"] is True
    assert done_x["dwell_minutes"] == 120
    assert done_x["exposure_minutes"] == 0
    # Non-adherent: free 120, dwell 210 -> exposure 90.
    assert done_y["adherent"] is False
    assert done_y["dwell_minutes"] == 210
    assert done_y["exposure_minutes"] == 90

    read_facility = fixtures.read_facility(api, facility["id"])
    assert read_facility["total_dwell_minutes"] == 330
    assert read_facility["detention_exposure_minutes"] == 90
    assert read_facility["appointment_adherence_pct"] == 50


def test_window_edges_decide_adherence(api):
    """Arrival exactly at window_start adheres; exactly at window_end does not.

    PRD: "Appointment windows are **half-open intervals**: an arrival at
    exactly `window_start` counts as within the window, an arrival at exactly
    `window_end` does not."
    Design: Difficulty/combinatorial_formula/detention_exposure_tiered_free_time_and_adherence_grace
    """
    carrier, shipment, facility = _facility_with_two_appointments(api)
    appt_start = fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z"
    )
    appt_end = fixtures.book_appointment(
        api, facility, shipment, "2026-09-01T13:00:00Z", "2026-09-01T14:00:00Z"
    )

    done_start = fixtures.complete_appointment(
        api, appt_start, carrier["id"], "2026-09-01T10:00:00Z", "2026-09-01T12:15:00Z"
    )
    done_end = fixtures.complete_appointment(
        api, appt_end, carrier["id"], "2026-09-01T14:00:00Z", "2026-09-01T15:00:00Z"
    )

    # Arrival on window_start: adherent, dwell 135, free 120 + 15 = 135, exposure 0.
    assert done_start["adherent"] is True
    assert done_start["exposure_minutes"] == 0
    # Arrival on window_end: not adherent, dwell 60, free 120, exposure 0.
    assert done_end["adherent"] is False
    assert done_end["exposure_minutes"] == 0

    read_facility = fixtures.read_facility(api, facility["id"])
    assert read_facility["appointment_adherence_pct"] == 50
