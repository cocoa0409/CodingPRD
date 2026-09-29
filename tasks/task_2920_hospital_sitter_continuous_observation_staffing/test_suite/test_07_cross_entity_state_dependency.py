"""
Transitions whose legality is decided by the state of another entity: a watch that
depends on its sitter's duty posture, and a console whose offlining depends on the
collection state of its feeds.
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
    DOC_PENDING,
    ERR_INVALID_STATION_STATE,
    ERR_STAFF_NOT_AVAILABLE,
    ERR_STATION_HAS_ACTIVE_FEEDS,
    FEED_RELEASED,
    MODALITY_ONE_TO_ONE_SITTER,
    MODALITY_VIDEO_MONITORING,
    POOL_INTERNAL_FLOAT,
    RELEASE_OBSERVER_RELEASE,
    RISK_ELOPEMENT,
    RISK_FALL,
    STAFF_AVAILABLE,
    STAFF_ON_ASSIGNMENT,
    STATION_ACTIVE_MONITORING,
    STATION_IDLE,
    STATION_OFFLINE,
    WATCH_ON_WATCH,
    WATCH_SCHEDULED,
)
from test_helpers.factories import feed_payload
from test_helpers.fixtures import (
    advance_clock,
    make_assignment,
    make_feed,
    make_order,
    make_patient,
    make_staff,
    make_station,
    make_unit,
    read_assignment,
    read_feed,
    read_staff,
    read_station,
    station_feeds,
    unit_head,
)
from test_helpers.test_users import make_remote_observer_headers, make_sitter_headers


def _unit_n_dual_duty_staff(api: ObservationApiClient) -> dict:
    """
    UNIT-N: one staff member is both the scheduled sitter on patient A's order and the
    observer of a console carrying an ACTIVE feed for patient B.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-N",
        name="Mixed Acuity Unit N",
        budget_cents=500000,
        video_monitoring_enabled=True,
    )
    patient_a = make_patient(
        api, unit["id"], mrn="MRN-9401", full_name="Pat Fifteen", age_years=60
    )
    patient_b = make_patient(
        api, unit["id"], mrn="MRN-9402", full_name="Pat Sixteen", age_years=60
    )
    staff = make_staff(
        api,
        unit["id"],
        full_name="Dual Duty En",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    sitter_order = make_order(
        api,
        patient_a["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Fall precautions, sitter at bedside",
    )
    video_order = make_order(
        api,
        patient_b["id"],
        risk_categories=[RISK_ELOPEMENT],
        required_modality=MODALITY_VIDEO_MONITORING,
        clinical_rationale="Remote observation for exit-seeking",
    )
    assignment = make_assignment(
        api,
        sitter_order["id"],
        staff["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=16),
        expected_order_version=sitter_order["version"],
    )
    station = make_station(api, staff["id"], station_label="CONSOLE-N1", declared_max_span=2)
    feed = make_feed(
        api,
        station["id"],
        video_order["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=12),
        staff["id"],
    )
    advance_clock(api, instant(CLOCK_START, hours=8))
    return {
        "unit": unit,
        "staff": staff,
        "assignment": assignment,
        "station": station,
        "feed": feed,
    }


class TestStartWatchDependsOnTheDutyPostureSetByAConsoleFeed:
    """Nothing about the watch changes between the refusal and the success."""

    def test_the_watch_cannot_start_while_a_console_feed_holds_the_sitter_on_assignment(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.5: "The observer's duty posture must be `AVAILABLE`; an observer who is
        already `ON_ASSIGNMENT` on another watch or staffing a console, or who is
        `SUSPENDED`, is refused with `ERR_STAFF_NOT_AVAILABLE`."

        The posture was set by an unrelated entity — admitting the feed moved this
        same `Staff` row to ON_ASSIGNMENT — and the refusal leaves the watch exactly
        as scheduling left it.

        Design: Difficulty/cross_entity_state_dependency/start_watch_depends_on_staff_duty_posture_set_by_a_console_feed
        """
        world = _unit_n_dual_duty_staff(api)
        assert read_staff(api, world["staff"]["id"])["status"] == STAFF_ON_ASSIGNMENT

        validate_error(
            api.start_watch(
                world["assignment"]["id"], make_sitter_headers(world["staff"]["id"])
            ),
            ERR_STAFF_NOT_AVAILABLE,
            HTTP_CONFLICT,
        )
        assert_fields(
            read_assignment(api, world["assignment"]["id"]),
            label="watch after the refusal",
            watch_status=WATCH_SCHEDULED,
            current_segment_started_at=None,
            documentation_status=DOC_PENDING,
        )

    def test_releasing_the_feed_frees_the_sitter_and_the_identical_call_then_succeeds(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.7: "The console recomputes `active_feed_count`, `active_acuity_weight` and
        `effective_span_limit`; when `active_feed_count` reaches 0 the console
        transitions `ACTIVE_MONITORING → IDLE`, with `active_acuity_weight` back at 0.0
        and `effective_span_limit` back at the full `declared_max_span`, and its
        observer moves `ON_ASSIGNMENT → AVAILABLE`."

        Freeing the staff row through the console is what makes the second
        start-watch legal, and the watch then reclaims the same posture for its own
        reasons.

        Design: Difficulty/cross_entity_state_dependency/start_watch_depends_on_staff_duty_posture_set_by_a_console_feed
        """
        world = _unit_n_dual_duty_staff(api)
        api.start_watch(world["assignment"]["id"], make_sitter_headers(world["staff"]["id"]))

        validate_success(
            api.release_feed(
                world["feed"]["id"], make_remote_observer_headers(world["staff"]["id"])
            )
        )
        assert_fields(
            read_station(api, world["station"]["id"]),
            label="console after the release",
            status=STATION_IDLE,
            active_feed_count=0,
        )
        assert read_staff(api, world["staff"]["id"])["status"] == STAFF_AVAILABLE
        released = read_feed(api, world["feed"]["id"])
        assert_fields(
            released,
            label="released feed",
            status=FEED_RELEASED,
            release_reason=RELEASE_OBSERVER_RELEASE,
        )
        assert_instant(
            released["released_at"], instant(CLOCK_START, hours=8), "feed.released_at"
        )

        started = validate_success(
            api.start_watch(
                world["assignment"]["id"], make_sitter_headers(world["staff"]["id"])
            )
        )
        assert started["watch_status"] == WATCH_ON_WATCH
        assert_instant(
            started["current_segment_started_at"],
            instant(CLOCK_START, hours=8),
            "assignment.current_segment_started_at",
        )
        assert read_staff(api, world["staff"]["id"])["status"] == STAFF_ON_ASSIGNMENT
        assert unit_head(api, world["unit"]["id"]) == 16000, (
            "only the watch's provisional entry is on the ledger; feeds post nothing"
        )


def _unit_o_console_with_one_feed(api: ObservationApiClient) -> dict:
    """UNIT-O: an ELOPEMENT-only video order carried on a console with one live feed."""
    unit = make_unit(
        api,
        unit_code="UNIT-O",
        name="Remote Monitoring Unit O",
        budget_cents=500000,
        video_monitoring_enabled=True,
    )
    patient = make_patient(
        api, unit["id"], mrn="MRN-9501", full_name="Pat Seventeen", age_years=60
    )
    observer = make_staff(
        api,
        unit["id"],
        full_name="Observer Oh",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_ELOPEMENT],
        required_modality=MODALITY_VIDEO_MONITORING,
        clinical_rationale="Exit-seeking, remote observation approved",
    )
    station = make_station(api, observer["id"], station_label="CONSOLE-O1", declared_max_span=2)
    feed = make_feed(
        api,
        station["id"],
        order["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=12),
        observer["id"],
    )
    return {
        "unit": unit,
        "order": order,
        "observer": observer,
        "station": station,
        "feed": feed,
    }


class TestStationOfflineDependsOnWhetherAnyFeedIsStillActive:
    """The console's own transition is gated on its children, and then it locks down."""

    def test_the_console_refuses_to_go_offline_while_a_feed_is_active(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.7: "A console in `ACTIVE_MONITORING` — equivalently, one whose
        `active_feed_count` is greater than 0 — cannot be taken offline, and the attempt
        is rejected with `ERR_STATION_HAS_ACTIVE_FEEDS`; the observer must release the
        live feeds first."

        The refusal changes nothing about the console, so its occupancy triple and
        its null `offlined_at` still describe a live console.

        Design: Difficulty/cross_entity_state_dependency/station_offline_depends_on_whether_any_feed_is_still_active
        """
        world = _unit_o_console_with_one_feed(api)
        validate_error(
            api.offline_station(
                world["station"]["id"], make_remote_observer_headers(world["observer"]["id"])
            ),
            ERR_STATION_HAS_ACTIVE_FEEDS,
            HTTP_CONFLICT,
        )
        assert_fields(
            read_station(api, world["station"]["id"]),
            label="console after the refusal",
            status=STATION_ACTIVE_MONITORING,
            active_feed_count=1,
            active_acuity_weight=2.0,
            effective_span_limit=2,
            offlined_at=None,
        )

    def test_once_idle_the_console_goes_offline_and_then_refuses_a_new_feed(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.7: "The console must not be `OFFLINE`; an `OFFLINE` console accepts
        nothing further and the attempt is rejected with `ERR_INVALID_STATION_STATE`."

        Releasing the last feed is what makes the offlining legal, and the dependency
        then runs the other way: the offline console will not accept a new feed, and
        offlining never disturbs the observer's own availability.

        Design: Difficulty/cross_entity_state_dependency/station_offline_depends_on_whether_any_feed_is_still_active
        """
        world = _unit_o_console_with_one_feed(api)
        observer_headers = make_remote_observer_headers(world["observer"]["id"])
        api.offline_station(world["station"]["id"], observer_headers)

        validate_success(api.release_feed(world["feed"]["id"], observer_headers))
        assert_fields(
            read_station(api, world["station"]["id"]),
            label="console after the release",
            status=STATION_IDLE,
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=2,
        )
        assert read_staff(api, world["observer"]["id"])["status"] == STAFF_AVAILABLE

        offlined = validate_success(
            api.offline_station(world["station"]["id"], observer_headers)
        )
        assert offlined["status"] == STATION_OFFLINE
        assert_instant(offlined["offlined_at"], CLOCK_START, "station.offlined_at")

        validate_error(
            api.create_feed(
                feed_payload(
                    world["station"]["id"],
                    world["order"]["id"],
                    instant(CLOCK_START, hours=13),
                    instant(CLOCK_START, hours=15),
                ),
                observer_headers,
            ),
            ERR_INVALID_STATION_STATE,
            HTTP_CONFLICT,
        )
        feeds = station_feeds(api, world["station"]["id"])
        assert_row_count(feeds, 1, "feeds ever admitted to the console")
        assert feeds[0]["status"] == FEED_RELEASED
        assert read_staff(api, world["observer"]["id"])["status"] == STAFF_AVAILABLE
