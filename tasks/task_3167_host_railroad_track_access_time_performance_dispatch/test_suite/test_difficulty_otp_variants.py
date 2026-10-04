"""On-time performance variants and the arrival-delay threshold boundary."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import PASSENGER_OPERATOR_HEADERS, fixtures


def test_run_on_time_at_endpoint_but_late_at_an_intermediate_segment(api):
    """One completed run yields on_time_endpoint true while on_time_all_stations is false.

    The run departs on time; its segment-1 exit is 18 minutes late (beyond the
    15-minute threshold) while its destination arrival is exactly 15 minutes
    late (at the threshold).

    PRD: "`on_time_all_stations`, true when `on_time_endpoint` holds **and** every `ACTUALIZED` passage of the run exited within threshold — each passage's exit delay being its actual exit minus planned exit, floored to whole minutes, clamped at zero, and compared against the same threshold. These are deliberately two variants of the same measurement: identical run data can yield `on_time_endpoint` true while `on_time_all_stations` is false."
    PRD: "`on_time_endpoint`, true when the destination arrival delay is at most the agreement's `on_time_threshold_minutes`"
    Design: Difficulty/dual_variant_calc/otp_endpoint_vs_all_stations_divergence
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=1, service_date="2026-09-02")
    run = net["runs"][0]
    p1, p2 = net["passages"][0]
    fixtures.depart_run(api, net, run["id"], "2026-09-02T08:00:00Z")
    # Segment 1 exit 18 minutes late (planned 08:27 -> actual 08:45).
    fixtures.actualize_passage(api, net, p1["id"], "2026-09-02T08:00:00Z", "2026-09-02T08:45:00Z")
    fixtures.actualize_passage(api, net, p2["id"], "2026-09-02T08:45:00Z", "2026-09-02T09:32:00Z")

    completed = fixtures.complete_run(api, net, run["id"], "2026-09-02T09:32:00Z")

    assert completed["status"] == "COMPLETED"
    # Destination arrival 09:32 vs scheduled 09:17: 15 minutes late.
    assert completed["destination_arrival_delay_minutes"] == 15
    assert completed["on_time_endpoint"] is True
    # Segment 1 exited 18 minutes late, over the 15-minute threshold.
    assert completed["on_time_all_stations"] is False


def test_run_on_time_under_both_variants_when_every_segment_exit_is_within_threshold(api):
    """A run whose every segment exit is within threshold is on time under both variants.

    Run1 departs on time, segment exits at 08:27 (0 late) and 09:32 (15 late,
    at the threshold), arrival at 09:32 (15 late, at the threshold).

    PRD: "`on_time_all_stations`, true when `on_time_endpoint` holds **and** every `ACTUALIZED` passage of the run exited within threshold — each passage's exit delay being its actual exit minus planned exit, floored to whole minutes, clamped at zero, and compared against the same threshold."
    Design: Difficulty/dual_variant_calc/otp_endpoint_vs_all_stations_divergence
    """
    net = fixtures.runs_0903_one_ontime_one_late(api)
    run1 = fixtures.read_run(api, net["run1"]["id"])
    assert run1["destination_arrival_delay_minutes"] == 15
    assert run1["on_time_endpoint"] is True
    # Segment exits 0 and 15 minutes late, both within the 15-minute threshold.
    assert run1["on_time_all_stations"] is True


def test_arrival_delay_exactly_at_threshold_counts_as_on_time(api):
    """An arrival delayed by exactly the threshold counts as on time (inclusive boundary).

    Run1 arrives 15 minutes late against the 15-minute threshold.

    PRD: "`on_time_endpoint`, true when the destination arrival delay is at most the agreement's `on_time_threshold_minutes`"
    Design: Difficulty/boundary_precision_check/on_time_threshold_exact_equality
    """
    net = fixtures.runs_0903_one_ontime_one_late(api)
    run1 = fixtures.read_run(api, net["run1"]["id"])
    assert run1["destination_arrival_delay_minutes"] == 15
    assert run1["on_time_endpoint"] is True
    assert run1["status"] == "COMPLETED"


def test_arrival_delay_one_minute_past_threshold_is_late(api):
    """An arrival delayed by threshold + 1 counts as late.

    Run2 arrives 16 minutes late against the 15-minute threshold.

    PRD: "`on_time_endpoint`, true when the destination arrival delay is at most the agreement's `on_time_threshold_minutes`"
    Design: Difficulty/boundary_precision_check/on_time_threshold_exact_equality
    """
    net = fixtures.runs_0903_one_ontime_one_late(api)
    run2 = fixtures.read_run(api, net["run2"]["id"])
    assert run2["destination_arrival_delay_minutes"] == 16
    assert run2["on_time_endpoint"] is False


def test_statement_for_empty_period_has_null_otp_and_zero_money(api):
    """A period with no completed runs yields otp_pct null and zero penalty/incentive.

    The agreement is ACTIVE but no timetable was ever published, so the
    September statement covers zero completed runs.

    PRD: "When `completed_run_count` is zero, `otp_pct` is null — not zero, and not an error."
    PRD: "When `otp_pct` is null, both `penalty_cents` and `incentive_cents` are zero."
    Design: Difficulty/boundary_precision_check/settlement_zero_completed_runs_null_otp
    """
    net = fixtures.setup_active_agreement(api)

    response = api.create_settlement_statement(
        {"operating_agreement_id": net["agreement"]["id"], "period_start": "2026-10-01", "period_end": "2026-10-31"},
        PASSENGER_OPERATOR_HEADERS,
    )
    statement = validate_success(response, 201)
    assert statement["completed_run_count"] == 0
    assert statement["otp_pct"] is None
    assert statement["penalty_cents"] == 0
    assert statement["incentive_cents"] == 0
    assert statement["net_cents"] == 0


def test_empty_period_statement_is_not_an_error_and_not_zero_otp(api):
    """A zero-completed-run statement succeeds with 201 and otp_pct is null, never 0.

    PRD: "When `completed_run_count` is zero, `otp_pct` is null — not zero, and not an error."
    Design: Difficulty/boundary_precision_check/settlement_zero_completed_runs_null_otp
    """
    net = fixtures.setup_active_agreement(api)

    response = api.create_settlement_statement(
        {"operating_agreement_id": net["agreement"]["id"], "period_start": "2026-10-01", "period_end": "2026-10-31"},
        PASSENGER_OPERATOR_HEADERS,
    )
    statement = validate_success(response, 201)
    assert response.status_code == 201
    assert statement["otp_pct"] is None
    assert statement["otp_pct"] != 0
    assert statement["completed_run_count"] == 0
