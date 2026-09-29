"""
Two conserved quantities and their compensating actions: the money in a unit's
observation ledger, undone by voiding a watch, and a console's occupancy triple,
undone by releasing the feeds that filled it.
"""

from test_helpers import (
    ObservationApiClient,
    instant,
    validate_success,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_row_count,
    final_segment_rows,
    provisional_row,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    COST_REVERSED,
    DOC_WAIVED,
    ENTRY_KIND_PROVISIONAL,
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
    UNIT_OPEN,
    WATCH_VOIDED,
)
from test_helpers.fixtures import (
    advance_clock,
    assignment_cost_entries,
    make_assignment,
    make_feed,
    make_order,
    make_patient,
    make_staff,
    make_station,
    make_unit,
    read_assignment,
    read_feed,
    read_order,
    read_staff,
    read_station,
    read_unit,
    station_feeds,
)
from test_helpers.test_users import MANAGER, make_remote_observer_headers


def _unit_r_scheduled_but_never_started(api: ObservationApiClient) -> dict:
    """
    UNIT-R: a ledger head of 0 lifted to 19200 by one eight-hour internal-float
    shift at 2400 cents/hour, with the watch deliberately never started so no
    FINAL_SEGMENT row can exist. The clock is then moved to 07:00Z so the
    reversal stamp is distinguishable from the posting stamp.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-R",
        name="Observation Unit R",
        budget_cents=500000,
        video_monitoring_enabled=False,
    )
    patient = make_patient(
        api, unit["id"], mrn="MRN-9801", full_name="Pat Twentyfive", age_years=60
    )
    sitter = make_staff(
        api,
        unit["id"],
        full_name="Sitter Arr",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2400,
        competency_level=COMPETENCY_ADVANCED,
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Fall precautions pending mobility review",
    )
    assignment = make_assignment(
        api,
        order["id"],
        sitter["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=16),
        expected_order_version=order["version"],
    )
    advance_clock(api, instant(CLOCK_START, hours=7))
    return {"unit": unit, "sitter": sitter, "order": order, "assignment": assignment}


class TestVoidReturnsTheUnitLedgerHeadToZero:
    """
    The forward action posted 19200 cents; the compensating action must take the
    head back to the exact number it held before the watch existed.
    """

    def test_the_head_returns_to_its_pre_schedule_value_with_no_residue(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.10: "Scheduling a watch and then voiding it must leave
        `observed_cost_to_date_cents` at precisely the number it held before the
        schedule, with zero drift, no matter how many other posts and reversals
        happened in between."

        The pre-schedule head was 0 and the provisional charge was 19200, so the
        post-void head is the only figure that can prove the recomputation ran over
        the whole posted set rather than as a delta.

        Design: Difficulty/compensating_invariant/void_reverses_the_provisional_charge_leaving_the_unit_ledger_at_zero
        """
        world = _unit_r_scheduled_but_never_started(api)
        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit before the void",
            observed_cost_to_date_cents=19200,
        )
        assert (
            read_assignment(api, world["assignment"]["id"])["provisional_cost_cents"]
            == 19200
        ), "the eight-hour internal-float shift posted 2400 * 8 cents"

        validate_success(api.void_assignment(world["assignment"]["id"], MANAGER))

        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit after the void",
            observed_cost_to_date_cents=0,
            status=UNIT_OPEN,
        )

    def test_the_voided_watch_keeps_the_figure_it_was_charged(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.5: "Voiding stamps `voided_at`, moves `documentation_status` `PENDING →
        WAIVED`, and sets the assignment's `PROVISIONAL` ledger row to `REVERSED` with
        `reversed_at` stamped and `amount_cents` untouched."

        `provisional_cost_cents` records what was charged and is not zeroed by the
        compensation. `final_cost_cents` is untouched by the void: PRD 3.4 lands a
        new assignment with "`final_cost_cents` ... null", and the void paragraph
        above enumerates the void's effects without naming that field, so a watch
        that never started still carries a null final figure — the only writer of
        `final_cost_cents` is a completion, which this watch never reached.

        Design: Difficulty/compensating_invariant/void_reverses_the_provisional_charge_leaving_the_unit_ledger_at_zero
        """
        world = _unit_r_scheduled_but_never_started(api)

        validate_success(api.void_assignment(world["assignment"]["id"], MANAGER))

        voided = read_assignment(api, world["assignment"]["id"])
        assert_fields(
            voided,
            label="the voided watch",
            watch_status=WATCH_VOIDED,
            documentation_status=DOC_WAIVED,
            provisional_cost_cents=19200,
            final_cost_cents=None,
            watch_segment_count=0,
            watched_minutes=0,
        )
        assert_instant(
            voided["voided_at"], instant(CLOCK_START, hours=7), "assignment.voided_at"
        )
        assert read_staff(api, world["sitter"]["id"])["status"] == STAFF_AVAILABLE
        assert (
            read_order(api, world["order"]["id"])["coverage_gap_flag"] is False
        ), "voiding a watch that never began is not an uncovered gap"

    def test_the_ledger_row_is_flipped_rather_than_edited_or_deleted(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.10: "When an action needs to be undone, the row is not adjusted and not
        deleted: its `status` moves to `REVERSED` and `reversed_at` is stamped, while
        `amount_cents` stays exactly as posted."

        That is what makes the compensation auditable: the single row still reads
        19200 at the posting instant it was written, with the reversal recorded
        alongside it at 07:00Z, and no FINAL_SEGMENT row was ever created.

        Design: Difficulty/compensating_invariant/void_reverses_the_provisional_charge_leaving_the_unit_ledger_at_zero
        """
        world = _unit_r_scheduled_but_never_started(api)

        validate_success(api.void_assignment(world["assignment"]["id"], MANAGER))

        rows = assignment_cost_entries(api, world["assignment"]["id"])
        assert_row_count(rows, 1, "ledger rows on the voided watch")
        entry = provisional_row(rows)
        assert_fields(
            entry,
            label="the reversed provisional row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            amount_cents=19200,
            status=COST_REVERSED,
        )
        assert_instant(entry["posted_at"], CLOCK_START, "entry.posted_at")
        assert_instant(
            entry["reversed_at"], instant(CLOCK_START, hours=7), "entry.reversed_at"
        )
        assert_row_count(
            final_segment_rows(rows), 0, "final-segment rows on a watch that never began"
        )


def _unit_s_console_and_two_video_orders(api: ObservationApiClient) -> dict:
    """
    UNIT-S: console CONSOLE-S1 rated for 3 patients and idle, with two
    VIDEO_MONITORING orders waiting — T1 on a FALL-only order (weight 1.0) and T2
    on a FALL plus ELOPEMENT order (weight 3.0). No feed is admitted here so each
    test can walk the occupancy triple step by step.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-S",
        name="Remote Hub Unit S",
        budget_cents=500000,
        video_monitoring_enabled=True,
    )
    patient_one = make_patient(
        api, unit["id"], mrn="MRN-9901", full_name="Pat Twentysix", age_years=60
    )
    patient_two = make_patient(
        api, unit["id"], mrn="MRN-9902", full_name="Pat Twentyseven", age_years=60
    )
    observer = make_staff(
        api,
        unit["id"],
        full_name="Observer Ess",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    station = make_station(
        api, observer["id"], station_label="CONSOLE-S1", declared_max_span=3
    )
    low_acuity_order = make_order(
        api,
        patient_one["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_VIDEO_MONITORING,
        clinical_rationale="Remote fall watch, low acuity",
    )
    high_acuity_order = make_order(
        api,
        patient_two["id"],
        risk_categories=[RISK_FALL, RISK_ELOPEMENT],
        required_modality=MODALITY_VIDEO_MONITORING,
        clinical_rationale="Remote combined watch, higher acuity",
    )
    return {
        "unit": unit,
        "observer": observer,
        "station": station,
        "low_acuity_order": low_acuity_order,
        "high_acuity_order": high_acuity_order,
    }


def _occupancy(api: ObservationApiClient, station_id: str) -> tuple:
    """The console's occupancy triple: count, weight, and derived span limit."""
    station = read_station(api, station_id)
    return (
        station["active_feed_count"],
        station["active_acuity_weight"],
        station["effective_span_limit"],
    )


def _admit_both_feeds(api: ObservationApiClient, world: dict) -> tuple:
    """F1 over [08:00, 12:00) and F2 over the overlapping [09:00, 13:00)."""
    observer_id = world["observer"]["id"]
    first = make_feed(
        api,
        world["station"]["id"],
        world["low_acuity_order"]["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=12),
        observer_id,
    )
    second = make_feed(
        api,
        world["station"]["id"],
        world["high_acuity_order"]["id"],
        instant(CLOCK_START, hours=9),
        instant(CLOCK_START, hours=13),
        observer_id,
    )
    return first, second


class TestFeedReleaseRestoresConsoleOccupancyWithoutDrift:
    """
    Two admissions and two releases in reverse order: every counter must retrace
    its path exactly, including the mid-sequence dip in the derived ceiling.
    """

    def test_the_occupancy_triple_retraces_its_path_exactly(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.10: "A monitoring station's `active_feed_count` is a full recount of the
        feeds on that station whose `status` is `ACTIVE`, never an incremented counter,
        and admitting a feed and then releasing that same feed must return both
        `active_feed_count` and `effective_span_limit` to their exact pre-admission
        values."

        The ceiling dips to 2 while the live weight sits at 4.0 and comes back to 3
        the moment the heavier feed is released, which is only possible if the limit
        is re-derived from the live weight rather than decremented and re-incremented.

        Design: Difficulty/compensating_invariant/feed_release_restores_station_occupancy_and_span_limit_without_drift
        """
        world = _unit_s_console_and_two_video_orders(api)
        station_id = world["station"]["id"]
        at_creation = _occupancy(api, station_id)
        assert at_creation == (0, 0.0, 3), f"new console opened at {at_creation}"

        first, second = _admit_both_feeds(api, world)
        assert _occupancy(api, station_id) == (2, 4.0, 2), (
            "two live feeds weigh 1.0 + 3.0 == 4.0, which costs one of the three slots"
        )

        observer_headers = make_remote_observer_headers(world["observer"]["id"])
        validate_success(api.release_feed(second["id"], observer_headers))
        assert _occupancy(api, station_id) == (1, 1.0, 3), (
            "dropping the heavier feed re-derives the ceiling upward again"
        )

        validate_success(api.release_feed(first["id"], observer_headers))
        assert _occupancy(api, station_id) == at_creation, (
            "the triple after both releases must equal the triple at creation"
        )

    def test_the_console_idles_only_when_the_last_feed_is_released(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.7: "The console recomputes `active_feed_count`, `active_acuity_weight` and
        `effective_span_limit`; when `active_feed_count` reaches 0 the console
        transitions `ACTIVE_MONITORING → IDLE`, with `active_acuity_weight` back at 0.0
        and `effective_span_limit` back at the full `declared_max_span`, and its
        observer moves `ON_ASSIGNMENT → AVAILABLE`."

        The first release drops the count to 1, not to 0, so both the console posture
        and the observer's duty posture must stay exactly where the admissions put
        them; only the second release may move either one.

        Design: Difficulty/compensating_invariant/feed_release_restores_station_occupancy_and_span_limit_without_drift
        """
        world = _unit_s_console_and_two_video_orders(api)
        station_id = world["station"]["id"]
        observer_id = world["observer"]["id"]
        observer_headers = make_remote_observer_headers(observer_id)
        first, second = _admit_both_feeds(api, world)

        validate_success(api.release_feed(second["id"], observer_headers))
        assert_fields(
            read_station(api, station_id),
            label="console after the first release",
            status=STATION_ACTIVE_MONITORING,
            active_feed_count=1,
        )
        assert read_staff(api, observer_id)["status"] == STAFF_ON_ASSIGNMENT

        validate_success(api.release_feed(first["id"], observer_headers))
        assert_fields(
            read_station(api, station_id),
            label="console after the second release",
            status=STATION_IDLE,
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=3,
        )
        assert read_staff(api, observer_id)["status"] == STAFF_AVAILABLE

    def test_released_feeds_keep_the_weight_they_froze_on_admission(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.7: "Each feed freezes an `acuity_weight` at the moment it is admitted,
        computed from the risk categories of the order it serves: a `FALL` criterion
        contributes 1.0, an `ELOPEMENT` criterion contributes 2.0, and a `SELF_HARM`
        criterion contributes 3.0, with the sum rounded half up to one decimal place."

        The console's weight recovers because released feeds are excluded from its
        sum, not because their frozen weights were cleared — both rows still read
        1.0 and 3.0 after the releases, and both survive as history on the console.

        Design: Difficulty/compensating_invariant/feed_release_restores_station_occupancy_and_span_limit_without_drift
        """
        world = _unit_s_console_and_two_video_orders(api)
        observer_headers = make_remote_observer_headers(world["observer"]["id"])
        first, second = _admit_both_feeds(api, world)

        validate_success(api.release_feed(second["id"], observer_headers))
        validate_success(api.release_feed(first["id"], observer_headers))

        for feed_id, weight in ((first["id"], 1.0), (second["id"], 3.0)):
            released = read_feed(api, feed_id)
            assert_fields(
                released,
                label="released feed",
                status=FEED_RELEASED,
                release_reason=RELEASE_OBSERVER_RELEASE,
                acuity_weight=weight,
            )
            assert_instant(released["released_at"], CLOCK_START, "feed.released_at")

        rows = station_feeds(api, world["station"]["id"])
        assert_row_count(rows, 2, "feeds ever admitted to CONSOLE-S1")
        assert all(row["status"] == FEED_RELEASED for row in rows), rows
        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit ledger",
            observed_cost_to_date_cents=0,
            status=UNIT_OPEN,
        )
