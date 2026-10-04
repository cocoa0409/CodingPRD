"""Season lifecycle: creation shape, lock/archive, archive cascades, delivery timing."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, make_studio, make_season, make_locked_season, make_title, approve_title,
    make_location, book_slot, make_published_block, make_air_slot, make_talent,
    make_deal, make_casting, confirm_casting, make_streaming_window,
    create_season_payload, setup_locked_season_with_approved_title,
    setup_delivered_title, setup_talent_with_deal,
)
from test_helpers.fixtures import ADMIN, PLANNER, PROD, EXEC, STREAM


class TestSeasonCreationShape:
    def test_deadline_after_air_window_start_rejected(self, api):
        """PRD §3.1: "Two window-shape rules guard season creation:
        `air_window_end` must be strictly later than `air_window_start`, and
        `delivery_deadline` must be strictly earlier than `air_window_start`" and
        "for window-shape failures, `ERR_INVALID_WINDOW`."

        Design: Corner/entities/season_create_applies_defaults_and_rejects_bad_window
        """
        studio = make_studio(ad_budget_cents=500000)
        resp = api_client.create_season(
            create_season_payload(studio_id=studio["id"], label="Bad Window",
                                  delivery_deadline="2027-11-05T00:00:00Z"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_wellformed_season_gets_draft_and_zero_counters(self, api):
        """PRD §3.1: "A new season starts in `DRAFT` status with all three
        aggregate counters at zero: `booked_shoot_days`, `committed_title_count`,
        and `premiered_title_count`."

        Design: Corner/entities/season_create_applies_defaults_and_rejects_bad_window
        """
        studio = make_studio(ad_budget_cents=500000)
        season = make_season(studio["id"], required_title_count=3)
        assert season["status"] == "DRAFT"
        assert season["version"] == 1
        assert season["booked_shoot_days"] == 0
        assert season["committed_title_count"] == 0
        assert season["premiered_title_count"] == 0


class TestSeasonLockGating:
    def test_relock_locked_season_is_invalid_state(self, api):
        """PRD §2.7: "**State legality** — the resource is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`)." PRD §3.1: "a
        `ProgrammingExec` locks the season, transitioning `DRAFT → LOCKED`".

        Design: Corner/state_machines/season_lock_is_gated_transition_not_race
        """
        studio = make_studio()
        season, sv = make_locked_season(studio["id"])
        resp = api_client.lock_season(season["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_relock_does_not_bump_version(self, api):
        """PRD §3.1: "When the plan is ready, a `ProgrammingExec` locks the season,
        transitioning `DRAFT → LOCKED` and incrementing the season's `version` by
        1." — only a successful lock bumps the version.

        Design: Corner/state_machines/season_lock_is_gated_transition_not_race
        """
        studio = make_studio()
        season, sv = make_locked_season(studio["id"])
        assert sv == 2  # created at 1, lock bumped to 2
        resp = api_client.lock_season(season["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["version"] == 2


class TestSeasonArchiveOpenTitles:
    def test_archive_blocked_by_approved_title(self, api):
        """PRD §3.1: "A `ProgrammingExec` may archive a `LOCKED` season only when
        every title in the season has reached a terminal slate state —
        `DELIVERED`, `REJECTED`, or `CANCELLED` — and no air slot belonging to
        the season remains in `PLANNED`; otherwise the archive is refused with
        `ERR_SEASON_HAS_OPEN_TITLES`."

        Design: Corner/state_machines/season_archive_blocked_by_open_titles
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title(required_title_count=2)
        resp = api_client.archive_season(ctx["season"]["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_SEASON_HAS_OPEN_TITLES)

    def test_archive_succeeds_after_title_cancelled(self, api):
        """PRD §3.1: "A successful archive transitions the season
        `LOCKED → ARCHIVED`, increments its `version` by 1".

        Design: Corner/state_machines/season_archive_blocked_by_open_titles
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title(required_title_count=2)
        validate_success(api_client.cancel_title(ctx["title"]["id"], PLANNER))
        archived = validate_success(api_client.archive_season(ctx["season"]["id"], EXEC))
        assert archived["status"] == "ARCHIVED"


class TestSeasonArchiveCascadeBreachesDeal:
    def test_archive_closes_published_block_and_scheduled_window(self, api):
        """PRD §3.1: "First, every program block of the season still in
        `PUBLISHED` is moved to `CLOSED`, which in turn cancels every air slot of
        such a block still in `PLANNED`. Second, every streaming window of the
        season still in `SCHEDULED` is moved directly to `CLOSED`."

        Design: Difficulty/transitive_cascade/season_archive_cascade_breaches_deal
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_delivered_title(required_title_count=2)
        season_id = ctx["season"]["id"]
        block, bv = make_published_block(season_id)
        win = make_streaming_window(season_id, ctx["title"]["id"], platform="PARTNER_STREAMER",
                                    window_start="2028-01-05T00:00:00Z",
                                    window_end="2028-02-05T00:00:00Z")
        archived = validate_success(api_client.archive_season(season_id, EXEC))
        assert archived["status"] == "ARCHIVED"
        block_after = get_success_data(api_client.get_program_block(block["id"], EXEC))
        assert block_after["status"] == "CLOSED"
        win_after = get_success_data(api_client.get_streaming_window(win["id"], STREAM))
        assert win_after["status"] == "CLOSED"

    def test_archive_breaches_underfulfilled_active_deal(self, api):
        """PRD §3.1: "Third, every talent deal tied to the season that is still
        `ACTIVE` is evaluated exactly once: if the deal's `fulfilled_pictures`
        falls short of its `picture_commitment`, the deal transitions
        `ACTIVE → BREACHED`, a terminal state."

        Design: Difficulty/transitive_cascade/season_archive_cascade_breaches_deal
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio()
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        season = get_success_data(api_client.get_season(season["id"], ADMIN))
        t2 = make_title(season["id"], name="T2", genre="COMEDY", tone_rating="GENTLE")
        approve_title(t2["id"], season["version"])
        validate_success(api_client.cancel_title(t2["id"], PLANNER))
        talent, agent, deal = setup_talent_with_deal(
            season["id"], studio["id"], picture_commitment=2,
            availability_windows=[{"start": "2027-03-01T00:00:00Z", "end": "2027-06-01T00:00:00Z"}])
        loc = make_location(studio["id"], name="Stage 1")
        slot = book_slot(t1["id"], loc["id"])
        validate_success(api_client.wrap_production_slot(slot["id"], PROD))
        c1 = make_casting(t1["id"], talent["id"], agent)
        confirm_casting(c1["id"], agent)
        validate_success(api_client.deliver_title(t1["id"], PROD))
        archived = validate_success(api_client.archive_season(season["id"], EXEC))
        assert archived["status"] == "ARCHIVED"
        deal_after = get_success_data(api_client.get_deal(deal["id"], agent))
        assert deal_after["status"] == "BREACHED"
        assert deal_after["fulfilled_pictures"] == 1


class TestDeliveryGates:
    def test_deliver_without_wrapped_shoot_rejected(self, api):
        """PRD §3.2: "delivery requires at least one of the title's production
        slots to be in `WRAPPED` (otherwise `ERR_NO_WRAPPED_SHOOT`)".

        Design: Corner/state_machines/title_deliver_without_wrapped_shoot_returns_no_wrapped_shoot
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        loc = make_location(ctx["studio"]["id"])
        book_slot(ctx["title"]["id"], loc["id"])  # BOOKED, not wrapped
        resp = api_client.deliver_title(ctx["title"]["id"], PROD)
        validate_error(resp, ApiErrorId.ERR_NO_WRAPPED_SHOOT)
        title_after = get_success_data(api_client.get_title(ctx["title"]["id"], PLANNER))
        assert title_after["status"] == "IN_PRODUCTION"
        assert title_after["delivered_at"] is None

    def test_deliver_one_second_past_deadline_rejected(self, api):
        """PRD §3.2: "a clock reading strictly after the deadline is rejected with
        `ERR_DELIVERY_LATE`, while a reading exactly at the deadline succeeds."

        Design: Corner/state_machines/title_deliver_after_deadline_returns_delivery_late
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        loc = make_location(ctx["studio"]["id"])
        slot = book_slot(ctx["title"]["id"], loc["id"])
        validate_success(api_client.wrap_production_slot(slot["id"], PROD))
        set_clock("2027-10-01T00:00:01Z")
        resp = api_client.deliver_title(ctx["title"]["id"], PROD)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_LATE)

    def test_deliver_at_exactly_deadline_succeeds(self, api):
        """PRD §3.2: "requires the logical clock to read no later than the
        season's `delivery_deadline`" and "Successful delivery moves the title
        `IN_PRODUCTION → DELIVERED` and stamps `delivered_at` with the current
        logical-clock instant."

        Design: Corner/state_machines/title_deliver_after_deadline_returns_delivery_late
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        loc = make_location(ctx["studio"]["id"])
        slot = book_slot(ctx["title"]["id"], loc["id"])
        validate_success(api_client.wrap_production_slot(slot["id"], PROD))
        set_clock("2027-10-01T00:00:00Z")
        delivered = validate_success(api_client.deliver_title(ctx["title"]["id"], PROD))
        assert delivered["status"] == "DELIVERED"
        assert delivered["delivered_at"] == "2027-10-01T00:00:00Z"
