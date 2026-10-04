"""Error catalogue corners: funding overlap and referential integrity."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId, PASSENGER_OPERATOR_HEADERS, STATE_SPONSOR_HEADERS, factories, fixtures


def test_overlapping_committed_funding_period_rejected(api):
    """A second COMMITTED agreement for the same corridor+state with overlapping period fails.

    The first IL agreement covers September; the second overlaps mid-September
    to mid-October.

    PRD: "Commitment is refused with `ERR_FUNDING_PERIOD_OVERLAP` when another `COMMITTED` funding agreement for the same corridor and state already covers an overlapping period."
    Design: Corner/errors/funding_period_overlap_rejected_on_second_commit
    """
    net = fixtures.setup_network(api)
    fa1 = fixtures.create_funding(api, net, "IL", period_start="2026-09-01", period_end="2026-09-30")
    fixtures.commit_funding(api, fa1["id"])
    fa2 = fixtures.create_funding(api, net, "IL", period_start="2026-09-15", period_end="2026-10-15")

    response = api.commit_funding_agreement(fa2["id"], STATE_SPONSOR_HEADERS)

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_FUNDING_PERIOD_OVERLAP)


def test_non_overlapping_funding_period_commits_with_fresh_allocation(api):
    """A disjoint December period commits fine and computes its own state's rounded line.

    December has 31 days: the rounded period cost is 849,315 and the IL line
    over 10.0 of 40.0 miles rounds 212,328.75 to 212,329.

    PRD: "Commitment is refused with `ERR_FUNDING_PERIOD_OVERLAP` when another `COMMITTED` funding agreement for the same corridor and state already covers an overlapping period."
    PRD: "First, the period's allocatable cost is the corridor's `annual_cost_cents` prorated by the inclusive day count of the period over 365, rounded half-up to whole cents — this is rounding step one. Second, the corridor's total mileage is the sum over its segments (of any status) of `milepost_end` minus `milepost_start`, and each state's line is the rounded period cost multiplied by the sum of segment miles lying in that state and divided by the corridor's total miles, rounded half-up to whole cents per line — this is rounding step two, applied to each state line independently."
    Design: Corner/errors/funding_period_overlap_rejected_on_second_commit
    """
    net = fixtures.setup_network(api)
    fa1 = fixtures.create_funding(api, net, "IL", period_start="2026-09-01", period_end="2026-09-30")
    fixtures.commit_funding(api, fa1["id"])
    fa3 = fixtures.create_funding(api, net, "IL", period_start="2026-12-01", period_end="2026-12-31")

    response = api.commit_funding_agreement(fa3["id"], STATE_SPONSOR_HEADERS)

    assert response.status_code == 200
    committed = response.json()["data"]
    assert committed["status"] == "COMMITTED"
    assert committed["allocated_cost_cents"] == 212329


def test_timetable_corridor_must_match_agreement_corridor(api):
    """A timetable whose corridor differs from its agreement's corridor is rejected.

    PRD: "The timetable's `corridor_id` must equal the operating agreement's `corridor_id`; a mismatch is rejected with `ERR_REFERENTIAL_INTEGRITY`."
    Design: Corner/errors/referential_integrity_timetable_corridor_mismatch
    """
    net = fixtures.setup_network(api)
    corridor2 = fixtures.create_corridor(
        api,
        net["host"]["id"],
        code="GP-2",
        name="Prairie",
        endpoint_a="STL",
        endpoint_b="OMA",
        service_type="LONG_DISTANCE",
        annual_cost_cents=7_000_000,
    )
    agreement2 = fixtures.create_agreement(
        api,
        net,
        corridor_id=corridor2["id"],
        on_time_threshold_minutes=30,
        penalty_rate_cents_per_minute=40,
        incentive_rate_cents_per_train_mile=10,
        otp_target_pct=0.75,
        running_time_allowance_pct=0.20,
    )

    response = api.create_timetable(
        factories.timetable_payload(
            net["corridor"]["id"], agreement2["id"],
            service_date_start="2026-09-05", service_date_end="2026-09-05",
        ),
        PASSENGER_OPERATOR_HEADERS,
    )

    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


def test_incident_passage_must_belong_to_the_coded_run(api):
    """An incident carrying a passage of a different run is rejected.

    PRD: "optionally with a `segment_passage_id` localizing the delay — and when a passage is supplied it must belong to that run, else `ERR_REFERENTIAL_INTEGRITY`"
    Design: Corner/errors/referential_integrity_incident_passage_of_other_run
    """
    net = fixtures.setup_published_timetable(api, trains_per_day=2, service_date="2026-09-03")
    r1, r2 = net["runs"]
    (r1p1, _r1p2) = net["passages"][0]

    response = api.create_delay_incident(
        factories.delay_incident_payload(r2["id"], "HOST_SIGNAL", 5, segment_passage_id=r1p1["id"]),
        net["host_headers"],
    )

    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)
