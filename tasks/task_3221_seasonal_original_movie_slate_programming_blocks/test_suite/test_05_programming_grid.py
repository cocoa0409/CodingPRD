"""Programming grid: blocks, premiere cadence, encore cap, buffers, OCC on block."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, make_studio, make_locked_season, make_title, approve_title,
    make_program_block, make_published_block, make_air_slot,
    create_air_slot_payload, setup_locked_season_with_approved_title,
)
from test_helpers.fixtures import ADMIN, PLANNER, PROD, EXEC


class TestBlockPublishGuard:
    def test_publish_against_draft_season_rejected(self, api):
        """PRD §3.5: "A `ProgrammingExec` publishes a `DRAFT` block, which requires
        the owning season to be `LOCKED` — otherwise `ERR_SEASON_NOT_LOCKED`".

        Design: Corner/state_machines/block_publish_requires_locked_season
        """
        studio = make_studio()
        season = get_success_data(api_client.create_season(
            {"studio_id": studio["id"], "year": 2027, "label": "Countdown",
             "required_title_count": 1, "air_window_start": "2027-11-01T00:00:00Z",
             "air_window_end": "2027-12-31T00:00:00Z",
             "delivery_deadline": "2027-10-01T00:00:00Z", "max_shoot_days": 100}, ADMIN))
        block = make_program_block(season["id"])
        resp = api_client.publish_program_block(block["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_LOCKED)

    def test_publish_after_lock_succeeds(self, api):
        """PRD §3.5: "publishes a `DRAFT` block, which requires the owning season
        to be `LOCKED`" and "moves the block `DRAFT → PUBLISHED`, incrementing
        the block's `version` by 1."

        Design: Corner/state_machines/block_publish_requires_locked_season
        """
        studio = make_studio()
        season, sv = make_locked_season(studio["id"])
        block = make_program_block(season["id"])
        published = validate_success(api_client.publish_program_block(block["id"], EXEC))
        assert published["status"] == "PUBLISHED"
        assert published["version"] == block["version"] + 1


class TestPremiereCadenceGrid:
    def test_off_grid_premiere_rejected(self, api):
        """PRD §3.5: "a `PREMIERE` must sit exactly on the block's cadence grid:"
        and "any offset from the grid is rejected with
        `ERR_PREMIERE_CADENCE_VIOLATION`."

        Design: Corner/state_machines/premiere_cadence_grid_violation
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"])
        # 6 days after block_start is off the 7-day grid
        resp = api_client.create_air_slot(
            create_air_slot_payload(block_id=block["id"], title_id=ctx["title"]["id"],
                                    air_start="2027-11-11T00:00:00Z", kind="PREMIERE",
                                    expected_block_version=bv), EXEC)
        validate_error(resp, ApiErrorId.ERR_PREMIERE_CADENCE_VIOLATION)

    def test_on_grid_premiere_and_off_grid_encore_accepted(self, api):
        """PRD §3.5: "the number of whole seconds between the slot's `air_start`
        and the block's `block_start` must be an exact multiple of the cadence
        expressed in seconds" and "`PREMIERE` slots are exempt from the cap" —
        the cadence grid applies to premieres; encores are exempt from the grid.

        Design: Corner/state_machines/premiere_cadence_grid_violation
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"])
        # exactly 7 days after block_start: on grid
        premiere = make_air_slot(block["id"], ctx["title"]["id"],
                                 "2027-11-12T00:00:00Z", "PREMIERE", bv)
        assert premiere["status"] == "PLANNED"
        block = get_success_data(api_client.get_program_block(block["id"], EXEC))
        # ENCORE one day later: exempt from the grid; 24h gap >= 1440 min buffer
        encore = make_air_slot(block["id"], ctx["title"]["id"],
                               "2027-11-13T00:00:00Z", "ENCORE", block["version"])
        assert encore["status"] == "PLANNED"


class TestEncoreCapEqualityBoundary:
    def test_encore_reaching_exact_cap_succeeds(self, api):
        """PRD §3.5: "creating the encore that brings the count exactly to the cap
        succeeds, and only the one beyond it fails."

        Design: Difficulty/boundary_precision_check/encore_cap_equality_boundary
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"], max_encores_per_title=2)
        e1 = make_air_slot(block["id"], ctx["title"]["id"], "2027-11-07T00:00:00Z", "ENCORE", bv)
        block = get_success_data(api_client.get_program_block(block["id"], EXEC))
        e2 = make_air_slot(block["id"], ctx["title"]["id"], "2027-11-09T00:00:00Z", "ENCORE",
                           block["version"])
        assert e2["status"] == "PLANNED"

    def test_encore_beyond_cap_rejected(self, api):
        """PRD §3.5: "a new `ENCORE` slot counts the block's existing `ENCORE`
        slots for the same title in `PLANNED` or `AIRED` status and is rejected
        with `ERR_ENCORE_CAP_EXCEEDED` when that count has already reached
        `max_encores_per_title`".

        Design: Difficulty/boundary_precision_check/encore_cap_equality_boundary
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"], max_encores_per_title=2)
        make_air_slot(block["id"], ctx["title"]["id"], "2027-11-07T00:00:00Z", "ENCORE", bv)
        block = get_success_data(api_client.get_program_block(block["id"], EXEC))
        make_air_slot(block["id"], ctx["title"]["id"], "2027-11-09T00:00:00Z", "ENCORE",
                      block["version"])
        block = get_success_data(api_client.get_program_block(block["id"], EXEC))
        resp = api_client.create_air_slot(
            create_air_slot_payload(block_id=block["id"], title_id=ctx["title"]["id"],
                                    air_start="2027-11-11T00:00:00Z", kind="ENCORE",
                                    expected_block_version=block["version"]), EXEC)
        validate_error(resp, ApiErrorId.ERR_ENCORE_CAP_EXCEEDED)


class TestSameTitleBufferExactBoundary:
    def test_gap_one_minute_less_rejected(self, api):
        """PRD §3.5: "a gap of exactly that many minutes passes, while one minute
        less fails with `ERR_AIRSLOT_OVERLAP`."

        Design: Corner/calculations/same_title_buffer_exact_boundary
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"], max_encores_per_title=5,
                                         min_minutes_between_airings=1440)
        make_air_slot(block["id"], ctx["title"]["id"], "2027-11-07T00:00:00Z", "ENCORE", bv)
        block = get_success_data(api_client.get_program_block(block["id"], EXEC))
        bv2 = block["version"]
        resp = api_client.create_air_slot(
            create_air_slot_payload(block_id=block["id"], title_id=ctx["title"]["id"],
                                    air_start="2027-11-07T23:59:00Z", kind="ENCORE",
                                    expected_block_version=bv2), EXEC)
        validate_error(resp, ApiErrorId.ERR_AIRSLOT_OVERLAP)
        block_after = get_success_data(api_client.get_program_block(block["id"], EXEC))
        assert block_after["version"] == bv2, "failed creation must not bump block version"

    def test_gap_exactly_at_buffer_passes(self, api):
        """PRD §3.5: "for every existing air slot in the same block carrying the
        same title and still in `PLANNED` or `AIRED`, the absolute start-to-start
        gap between it and the new slot must be at least
        `min_minutes_between_airings` minutes; a gap of exactly that many minutes
        passes".

        Design: Corner/calculations/same_title_buffer_exact_boundary
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"], max_encores_per_title=5,
                                         min_minutes_between_airings=1440)
        make_air_slot(block["id"], ctx["title"]["id"], "2027-11-07T00:00:00Z", "ENCORE", bv)
        block = get_success_data(api_client.get_program_block(block["id"], EXEC))
        encore = make_air_slot(block["id"], ctx["title"]["id"], "2027-11-08T00:00:00Z", "ENCORE",
                               block["version"])
        assert encore["status"] == "PLANNED"


class TestAirSlotWindowContainment:
    def test_air_start_at_exclusive_window_end_rejected(self, api):
        """PRD §3.5: "the `air_start` must lie within the owning season's air
        window — at or after `air_window_start` and strictly before
        `air_window_end` — otherwise `ERR_INVALID_WINDOW`."

        Design: Corner/state_machines/air_slot_outside_season_window_rejected
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"])
        resp = api_client.create_air_slot(
            create_air_slot_payload(block_id=block["id"], title_id=ctx["title"]["id"],
                                    air_start="2027-12-31T00:00:00Z", kind="ENCORE",
                                    expected_block_version=bv), EXEC)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_air_start_inside_window_accepted(self, api):
        """PRD §3.5: "the `air_start` must lie within the owning season's air
        window — at or after `air_window_start` and strictly before
        `air_window_end`".

        Design: Corner/state_machines/air_slot_outside_season_window_rejected
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"])
        encore = make_air_slot(block["id"], ctx["title"]["id"], "2027-12-30T00:00:00Z",
                               "ENCORE", bv)
        assert encore["status"] == "PLANNED"


class TestMarkAiredTiming:
    def test_mark_aired_before_air_start_rejected(self, api):
        """PRD §3.5: "a clock reading earlier than `air_start` is rejected with
        `ERR_AIRSLOT_TOO_EARLY`".

        Design: Corner/state_machines/mark_aired_before_air_start_rejected
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"])
        air = make_air_slot(block["id"], ctx["title"]["id"], "2027-11-05T00:00:00Z",
                            "PREMIERE", bv)
        set_clock("2027-11-04T23:59:59Z")
        resp = api_client.mark_air_slot_aired(air["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_AIRSLOT_TOO_EARLY)

    def test_mark_aired_at_exactly_air_start_succeeds(self, api):
        """PRD §3.5: "a `ProgrammingExec` marks a `PLANNED` slot aired once the
        logical clock has reached the slot's `air_start`" and "when the slot's
        `kind` is `PREMIERE`, the season's `premiered_title_count` is recomputed".

        Design: Corner/state_machines/mark_aired_before_air_start_rejected
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"])
        air = make_air_slot(block["id"], ctx["title"]["id"], "2027-11-05T00:00:00Z",
                            "PREMIERE", bv)
        set_clock("2027-11-05T00:00:00Z")
        aired = validate_success(api_client.mark_air_slot_aired(air["id"], EXEC))
        assert aired["status"] == "AIRED"
        season_after = get_success_data(api_client.get_season(ctx["season"]["id"], ADMIN))
        assert season_after["premiered_title_count"] == 1


class TestOccStaleBlockVersion:
    def test_first_slot_creation_succeeds_and_bumps_block_version(self, api):
        """PRD §3.5: "Every successful creation increments the block's `version`
        by 1, which is why the OCC token is required on this endpoint."

        Design: Corner/endpoints/occ_stale_block_version_on_air_slot_returns_412
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"])
        air = make_air_slot(block["id"], ctx["title"]["id"], "2027-11-05T00:00:00Z",
                            "PREMIERE", bv)
        assert air["status"] == "PLANNED"
        block_after = get_success_data(api_client.get_program_block(block["id"], EXEC))
        assert block_after["version"] == bv + 1

    def test_second_creation_with_stale_block_version_rejected_412(self, api):
        """PRD §2.9: "Each successful air-slot creation bumps the block's
        `version`, so any creation attempted against a version the block has
        since advanced past is rejected with `ERR_STALE_VERSION`."

        Design: Corner/endpoints/occ_stale_block_version_on_air_slot_returns_412
        """
        set_clock("2027-03-01T00:00:00Z")
        studio_ctx = setup_locked_season_with_approved_title(required_title_count=2)
        season_id = studio_ctx["season"]["id"]
        season = get_success_data(api_client.get_season(season_id, ADMIN))
        t2 = make_title(season_id, name="T2", genre="FAMILY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        block, bv = make_published_block(season_id)
        make_air_slot(block["id"], studio_ctx["title"]["id"], "2027-11-05T00:00:00Z",
                      "PREMIERE", bv)
        resp = api_client.create_air_slot(
            create_air_slot_payload(block_id=block["id"], title_id=t2["id"],
                                    air_start="2027-11-12T00:00:00Z", kind="PREMIERE",
                                    expected_block_version=bv), EXEC)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        block_after = get_success_data(api_client.get_program_block(block["id"], EXEC))
        assert block_after["version"] == bv + 1, "only the first creation applied"


class TestTemporalBeatsQuotaOnAirSlot:
    def test_buffer_violation_and_cap_excess_reports_overlap(self, api):
        """PRD §2.7: "When a request fails several rules at once, the error the
        caller observes is determined by a fixed priority order" with "8.
        **Temporal rules**" listed before "10. **Aggregate quota rules**".

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_quota_on_air_slot_create
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"], max_encores_per_title=1,
                                         min_minutes_between_airings=1440)
        make_air_slot(block["id"], ctx["title"]["id"], "2027-11-07T00:00:00Z", "ENCORE", bv)
        block = get_success_data(api_client.get_program_block(block["id"], EXEC))
        # 60 minutes after the existing encore: buffer violation AND over the cap
        resp = api_client.create_air_slot(
            create_air_slot_payload(block_id=block["id"], title_id=ctx["title"]["id"],
                                    air_start="2027-11-07T01:00:00Z", kind="ENCORE",
                                    expected_block_version=block["version"]), EXEC)
        validate_error(resp, ApiErrorId.ERR_AIRSLOT_OVERLAP)

    def test_cap_excess_alone_reports_encore_cap(self, api):
        """PRD §3.5: "is rejected with `ERR_ENCORE_CAP_EXCEEDED` when that count
        has already reached `max_encores_per_title`".

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_quota_on_air_slot_create
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        block, bv = make_published_block(ctx["season"]["id"], max_encores_per_title=1,
                                         min_minutes_between_airings=1440)
        make_air_slot(block["id"], ctx["title"]["id"], "2027-11-07T00:00:00Z", "ENCORE", bv)
        block = get_success_data(api_client.get_program_block(block["id"], EXEC))
        # 2 days later: buffer satisfied, only the cap trips
        resp = api_client.create_air_slot(
            create_air_slot_payload(block_id=block["id"], title_id=ctx["title"]["id"],
                                    air_start="2027-11-09T00:00:00Z", kind="ENCORE",
                                    expected_block_version=block["version"]), EXEC)
        validate_error(resp, ApiErrorId.ERR_ENCORE_CAP_EXCEEDED)
