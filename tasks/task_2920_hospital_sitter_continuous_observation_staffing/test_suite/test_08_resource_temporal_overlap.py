"""
Two readings of "already busy": pairwise half-open comparison against one peer shift
for a person, and aggregate simultaneous occupancy against a shrinking ceiling for a
console.
"""

from test_helpers import (
    HTTP_CONFLICT,
    ObservationApiClient,
    instant,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_fields, assert_instant, assert_row_count
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    ERR_SPAN_OF_CONTROL_EXCEEDED,
    ERR_STAFF_REST_BUFFER_VIOLATION,
    ERR_STAFF_SHIFT_OVERLAP,
    FEED_ACTIVE,
    MODALITY_ONE_TO_ONE_SITTER,
    MODALITY_VIDEO_MONITORING,
    POOL_INTERNAL_FLOAT,
    RISK_ELOPEMENT,
    RISK_FALL,
    STAFF_ON_ASSIGNMENT,
    STATION_ACTIVE_MONITORING,
    UNIT_OPEN,
    WATCH_SCHEDULED,
)
from test_helpers.factories import assignment_payload, feed_payload
from test_helpers.fixtures import (
    make_assignment,
    make_feed,
    make_order,
    make_patient,
    make_staff,
    make_station,
    make_unit,
    order_assignments,
    order_feeds,
    read_feed,
    read_order,
    read_staff,
    read_station,
    read_unit,
)
from test_helpers.test_users import COORDINATOR, make_remote_observer_headers


def _unit_p_peer_shift(api: ObservationApiClient) -> dict:
    """
    UNIT-P: one sitter already booked 08:00-16:00 on patient A's order, with patient
    B's order untouched at version 1 so every probe may replay the same version.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-P",
        name="Observation Unit P",
        budget_cents=500000,
        video_monitoring_enabled=False,
    )
    patient_a = make_patient(
        api, unit["id"], mrn="MRN-9601", full_name="Pat Eighteen", age_years=60
    )
    patient_b = make_patient(
        api, unit["id"], mrn="MRN-9602", full_name="Pat Nineteen", age_years=60
    )
    sitter = make_staff(
        api,
        unit["id"],
        full_name="Sitter Pea",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    day_order = make_order(
        api,
        patient_a["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Day-shift fall precautions",
    )
    night_order = make_order(
        api,
        patient_b["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Night-shift fall precautions",
    )
    make_assignment(
        api,
        day_order["id"],
        sitter["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=16),
        expected_order_version=day_order["version"],
    )
    return {"unit": unit, "sitter": sitter, "night_order": night_order}


def _probe(api: ObservationApiClient, world: dict, start: str, end: str):
    """Schedule the same sitter onto the untouched second order over a given window."""
    return api.create_assignment(
        assignment_payload(
            world["night_order"]["id"],
            world["sitter"]["id"],
            start,
            end,
            world["night_order"]["version"],
        ),
        COORDINATOR,
    )


class TestHalfOpenOverlapThenTheExactRestBuffer:
    """Touching windows do not overlap; a gap of exactly 480 minutes is enough rest."""

    def test_a_window_that_merely_touches_the_peer_shift_fails_only_the_rest_buffer(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.11: "two windows overlap only when each one starts strictly before the
        other ends, so a shift that ends at exactly the instant the next shift begins
        does **not** overlap it, and a feed that ends at exactly the instant a candidate
        feed begins does **not** count against that candidate's span."

        A 16:00 start against a peer ending at 16:00 leaves the overlap rule silent,
        so the answer is the rest-buffer code and not the overlap code.

        Design: Difficulty/resource_temporal_overlap/staff_pairwise_half_open_overlap_then_exact_480_minute_rest_buffer
        """
        world = _unit_p_peer_shift(api)
        validate_error(
            _probe(api, world, instant(CLOCK_START, hours=16), instant(CLOCK_START, hours=24)),
            ERR_STAFF_REST_BUFFER_VIOLATION,
            HTTP_CONFLICT,
        )

    def test_starting_one_minute_earlier_makes_it_an_overlap_and_the_overlap_code_wins(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.4: "Two shifts of the same observer conflict when their half-open windows
        overlap — that is, when each window starts strictly before the other ends — and
        a conflict is rejected with `ERR_STAFF_SHIFT_OVERLAP`."

        Moving the start one minute earlier makes each window start strictly before
        the other ends, and although the buffer is violated as well, the earlier rung
        answers.

        Design: Difficulty/resource_temporal_overlap/staff_pairwise_half_open_overlap_then_exact_480_minute_rest_buffer
        """
        world = _unit_p_peer_shift(api)
        validate_error(
            _probe(
                api,
                world,
                instant(CLOCK_START, hours=15, minutes=59),
                instant(CLOCK_START, hours=23, minutes=59),
            ),
            ERR_STAFF_SHIFT_OVERLAP,
            HTTP_CONFLICT,
        )

    def test_a_gap_of_exactly_four_hundred_and_eighty_minutes_is_accepted(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.4: "The rest-buffer comparison is inclusive in the observer's favour: a
        gap of exactly 480 minutes passes."

        Only the accepted probe bumps the order version, which is why the two refused
        probes could replay the same `expected_order_version`, and the overnight
        window costs the same as the day peer because the provisional variant knows no
        night differential.

        Design: Difficulty/resource_temporal_overlap/staff_pairwise_half_open_overlap_then_exact_480_minute_rest_buffer
        """
        world = _unit_p_peer_shift(api)
        _probe(api, world, instant(CLOCK_START, hours=16), instant(CLOCK_START, hours=24))
        _probe(
            api,
            world,
            instant(CLOCK_START, hours=15, minutes=59),
            instant(CLOCK_START, hours=23, minutes=59),
        )

        accepted = validate_success(
            _probe(api, world, instant(CLOCK_START, hours=24), instant(CLOCK_START, hours=32)),
            201,
        )
        assert_fields(
            accepted,
            label="the accepted watch",
            watch_status=WATCH_SCHEDULED,
            scheduled_minutes=480,
            provisional_cost_cents=16000,
        )
        assert (
            read_order(api, world["night_order"]["id"])["version"]
            == world["night_order"]["version"] + 1
        ), "only the accepted probe advanced the order"
        rows = order_assignments(api, world["night_order"]["id"])
        assert_row_count(rows, 1, "watches on the second order")
        assert rows[0]["id"] == accepted["id"]

        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit ledger",
            observed_cost_to_date_cents=32000,
            status=UNIT_OPEN,
        )
        assert_instant(
            read_staff(api, world["sitter"]["id"])["last_shift_end_at"],
            instant(CLOCK_START, hours=32),
            "staff.last_shift_end_at",
        )


def _unit_q_console_at_weight_six(api: ObservationApiClient) -> dict:
    """
    UNIT-Q: console CONSOLE-Q1 rated for 3 patients, carrying three ACTIVE feeds
    whose frozen weights sum to 6.0 — the tier that costs two slots, leaving an
    operative ceiling of 1. Two spare orders R4 and R5 are left unfed so the same
    console can be probed with an overlapping and a non-overlapping candidate.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-Q",
        name="Remote Hub Unit Q",
        budget_cents=500000,
        video_monitoring_enabled=True,
    )
    observer = make_staff(
        api,
        unit["id"],
        full_name="Observer Cue",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    station = make_station(
        api, observer["id"], station_label="CONSOLE-Q1", declared_max_span=3
    )

    spec = [
        ("MRN-9701", "Pat Twenty", [RISK_FALL], "Remote fall watch one"),
        ("MRN-9702", "Pat Twentyone", [RISK_ELOPEMENT], "Remote elopement watch two"),
        (
            "MRN-9703",
            "Pat Twentytwo",
            [RISK_FALL, RISK_ELOPEMENT],
            "Remote combined watch three",
        ),
        ("MRN-9704", "Pat Twentythree", [RISK_FALL], "Remote fall watch four"),
        ("MRN-9705", "Pat Twentyfour", [RISK_FALL], "Remote fall watch five"),
    ]
    orders = []
    for mrn, full_name, categories, rationale in spec:
        patient = make_patient(api, unit["id"], mrn=mrn, full_name=full_name, age_years=60)
        orders.append(
            make_order(
                api,
                patient["id"],
                risk_categories=categories,
                required_modality=MODALITY_VIDEO_MONITORING,
                clinical_rationale=rationale,
            )
        )

    windows = [(8, 12), (9, 13), (10, 11)]
    feeds = [
        make_feed(
            api,
            station["id"],
            order["id"],
            instant(CLOCK_START, hours=start),
            instant(CLOCK_START, hours=end),
            observer["id"],
        )
        for order, (start, end) in zip(orders[:3], windows)
    ]
    return {
        "unit": unit,
        "observer": observer,
        "station": station,
        "orders": orders,
        "feeds": feeds,
    }


class TestStationCapacityIsAggregateAgainstAShrinkingCeiling:
    """
    One console, one ceiling of 1, two candidates: the refusal and the admission
    differ only in whether the candidate's window touches the live feeds.
    """

    def test_the_three_setup_feeds_shrink_the_operative_ceiling_to_one(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.7: "From that weight a penalty is derived over inclusive thresholds: a
        weight of 6.0 or higher costs 2 slots, a weight below 6.0 but 4.0 or higher
        costs 1 slot, and anything below 4.0 costs nothing. The console's
        `effective_span_limit` is then its `declared_max_span` reduced by that penalty,
        but never allowed below a floor of 1 — a console rated for 2 patients carrying
        a heavy weight still retains capacity for one."

        The three admissions were each legal against the limit that stood before them,
        and their frozen weights of 1.0, 2.0 and 3.0 sum to exactly the 6.0 threshold
        that costs two of the console's three slots.

        Design: Difficulty/resource_temporal_overlap/station_aggregate_capacity_with_limit_shrinking_under_acuity_weight
        """
        world = _unit_q_console_at_weight_six(api)

        assert_fields(
            read_station(api, world["station"]["id"]),
            label="CONSOLE-Q1 carrying three feeds",
            active_feed_count=3,
            active_acuity_weight=6.0,
            effective_span_limit=1,
            declared_max_span=3,
            status=STATION_ACTIVE_MONITORING,
        )
        for feed, weight in zip(world["feeds"], (1.0, 2.0, 3.0)):
            assert_fields(
                read_feed(api, feed["id"]),
                label="admitted feed",
                status=FEED_ACTIVE,
                acuity_weight=weight,
            )

    def test_an_overlapping_fourth_feed_is_refused_and_leaves_its_order_unfed(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.7: "Occupancy, on the other hand, **includes** the candidate: the server
        counts the console's feeds in `status` `ACTIVE` whose window overlaps the
        candidate's window — each starting strictly before the other ends, per the
        half-open convention of §2.11 — and adds 1 for the candidate itself."

        The [10:30, 11:30) candidate overlaps all three live feeds, so occupancy is
        3 + 1 == 4 against the pre-candidate ceiling of 1 — measured against the
        *number* of overlapping feeds rather than against any single one of them.

        Design: Difficulty/resource_temporal_overlap/station_aggregate_capacity_with_limit_shrinking_under_acuity_weight
        """
        world = _unit_q_console_at_weight_six(api)
        crowded_order = world["orders"][3]

        validate_error(
            api.create_feed(
                feed_payload(
                    world["station"]["id"],
                    crowded_order["id"],
                    instant(CLOCK_START, hours=10, minutes=30),
                    instant(CLOCK_START, hours=11, minutes=30),
                ),
                make_remote_observer_headers(world["observer"]["id"]),
            ),
            ERR_SPAN_OF_CONTROL_EXCEEDED,
            HTTP_CONFLICT,
        )
        assert_row_count(
            order_feeds(api, crowded_order["id"]), 0, "feeds on the refused order"
        )
        assert_fields(
            read_station(api, world["station"]["id"]),
            label="CONSOLE-Q1 after the refusal",
            active_feed_count=3,
            active_acuity_weight=6.0,
            effective_span_limit=1,
        )

    def test_a_non_overlapping_feed_is_admitted_past_the_declared_span(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.7: "Note carefully that this is an **aggregate capacity rule over
        instants, not a pairwise rule over rows**: a console may legitimately hold more
        `ACTIVE` feeds than its `effective_span_limit`, provided no single instant is
        covered by more feeds than the limit allows."

        The [14:00, 15:00) candidate starts after the last live window ends, so its
        overlapping occupancy is 0 + 1 == 1, which equals the ceiling of 1 and is
        admitted — carrying `active_feed_count` to 4 above a `declared_max_span` of 3.

        Design: Difficulty/resource_temporal_overlap/station_aggregate_capacity_with_limit_shrinking_under_acuity_weight
        """
        world = _unit_q_console_at_weight_six(api)
        spare_order = world["orders"][4]

        admitted = validate_success(
            api.create_feed(
                feed_payload(
                    world["station"]["id"],
                    spare_order["id"],
                    instant(CLOCK_START, hours=14),
                    instant(CLOCK_START, hours=15),
                ),
                make_remote_observer_headers(world["observer"]["id"]),
            ),
            201,
        )
        assert_fields(
            admitted,
            label="the non-overlapping feed",
            status=FEED_ACTIVE,
            acuity_weight=1.0,
        )
        assert_fields(
            read_station(api, world["station"]["id"]),
            label="CONSOLE-Q1 after the fourth admission",
            active_feed_count=4,
            active_acuity_weight=7.0,
            effective_span_limit=1,
            declared_max_span=3,
            status=STATION_ACTIVE_MONITORING,
        )
        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit ledger",
            observed_cost_to_date_cents=0,
            status=UNIT_OPEN,
        )
        assert (
            read_staff(api, world["observer"]["id"])["status"] == STAFF_ON_ASSIGNMENT
        ), "the observer's posture was set once by the first feed and never re-set"
