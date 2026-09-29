"""ADR capacity guards: the daily cap, the overlap set and the picture-lock gate."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_PICTURE_NOT_LOCKED,
    ERR_TALENT_DAILY_CAP_EXCEEDED,
    ERR_TALENT_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_decimal
from test_helpers.test_users import EDITOR_HEADERS


class TestTalentDailyCapBoundary:
    """Billable minutes, not scheduled minutes, fill up the talent's day."""

    def _talent_at_two_sessions(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        talent = world.voice_talent(
            union_status="UNION", daily_cap_minutes=120, min_call_minutes=60
        )
        project = world.locked_project()
        first = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T09:45:00Z",
        )
        second = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T10:45:00Z",
        )
        return talent, project, first, second

    def test_two_short_union_sessions_fill_the_cap_exactly_and_are_both_accepted(self, world):
        """Each 45-minute window bills the 60-minute call, landing exactly on 120.

        PRD §3.5: "It is `billable_minutes`, not `scheduled_minutes`, that counts against
        a talent's capacity."

        Design: Difficulty/boundary_precision_check/talent_daily_cap_exactly_at_limit_accepted_next_minute_rejected
        """
        _talent, project, first, second = self._talent_at_two_sessions(world)

        for session in (first, second):
            assert session["status"] == "PROPOSED"
            assert_decimal(session["scheduled_minutes"], 45.00)
            assert_decimal(session["billable_minutes"], 60.00)
            assert session["session_cost_cents"] == 54000

        world.confirm_adr(first["id"])
        world.confirm_adr(second["id"])

        ledger = world.ledger(project["id"])
        assert ledger["adr_cost_cents"] == 108000
        assert ledger["billing_total_cents"] == 108000

    def test_a_third_session_of_any_length_is_over_the_cap_and_is_refused(self, world, api):
        """The cap is already met at 120 minutes, so the next request is rejected.

        PRD §2.11: "**Rung 35** — the talent's same-UTC-day billable minutes would exceed
        their daily cap, on ADR session creation: `ERR_TALENT_DAILY_CAP_EXCEEDED`, 409."

        Design: Difficulty/boundary_precision_check/talent_daily_cap_exactly_at_limit_accepted_next_minute_rejected
        """
        talent, project, _first, _second = self._talent_at_two_sessions(world)

        response = api.create_adr_session(
            f.adr_session_payload(
                project["id"],
                talent["id"],
                window_start_utc="2026-09-14T11:00:00Z",
                window_end_utc="2026-09-14T11:45:00Z",
            ),
            EDITOR_HEADERS,
        )
        validate_error(response, ERR_TALENT_DAILY_CAP_EXCEEDED, 409)

        by_project, project_meta = validate_paginated(
            api.list_adr_sessions(EDITOR_HEADERS, {"project_id": project["id"]})
        )
        assert project_meta["total_count"] == 2
        assert len(by_project) == 2

        by_talent, talent_meta = validate_paginated(
            api.list_adr_sessions(EDITOR_HEADERS, {"voice_talent_id": talent["id"]})
        )
        assert talent_meta["total_count"] == 2
        assert len(by_talent) == 2


class TestTalentAdjacencyAndNoShow:
    """The overlap set and the cap set diverge once a session goes NO_SHOW."""

    def _two_adjacent_sessions(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        talent = world.voice_talent(
            union_status="UNION", daily_cap_minutes=240, min_call_minutes=60
        )
        project = world.locked_project()
        first = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T10:00:00Z",
        )
        world.confirm_adr(first["id"])
        return talent, project, first

    def test_a_session_starting_at_the_previous_end_instant_is_accepted(self, world, api):
        """Back-to-back calls are legal, but a straddling window still conflicts.

        PRD §3.5: "Adjacency is explicitly allowed, and there is no buffer for talent: a
        session that begins at exactly another session's `window_end_utc` does not
        conflict."

        Design: Difficulty/resource_temporal_overlap/talent_adjacency_allowed_and_no_show_releases_the_window_but_not_the_cap
        """
        talent, project, first = self._two_adjacent_sessions(world)

        adjacent = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T11:00:00Z",
        )
        assert adjacent["status"] == "PROPOSED"
        assert_decimal(adjacent["billable_minutes"], 60.00)
        assert adjacent["session_cost_cents"] == 54000
        world.confirm_adr(adjacent["id"])

        straddling = api.create_adr_session(
            f.adr_session_payload(
                project["id"],
                talent["id"],
                window_start_utc="2026-09-14T10:30:00Z",
                window_end_utc="2026-09-14T11:30:00Z",
            ),
            EDITOR_HEADERS,
        )
        validate_error(straddling, ERR_TALENT_WINDOW_CONFLICT, 409)

        assert world.get_adr(first["id"])["status"] == "CONFIRMED"
        ledger = world.ledger(project["id"])
        assert ledger["adr_cost_cents"] == 108000
        assert ledger["billing_total_cents"] == 108000

    def test_a_no_show_frees_the_window_while_still_billing_the_day(self, world, api):
        """The vacated slot becomes bookable, yet the money and the cap both stand.

        PRD §3.5: "The asymmetry is intentional: a no-show consumed the talent's day even
        though nobody was in the booth, so it stays in the cap set while leaving the
        overlap set."

        Design: Difficulty/resource_temporal_overlap/talent_adjacency_allowed_and_no_show_releases_the_window_but_not_the_cap
        """
        talent, project, first = self._two_adjacent_sessions(world)
        adjacent = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T11:00:00Z",
        )
        world.confirm_adr(adjacent["id"])

        world.set_clock("2026-09-14T10:00:00Z")
        no_show = world.cancel_adr(adjacent["id"], cancellation_reason="TALENT_NO_SHOW")
        assert no_show["status"] == "NO_SHOW"
        assert no_show["cancellation_reason"] == "TALENT_NO_SHOW"
        assert no_show["session_cost_cents"] == 54000

        retry = validate_success(
            api.create_adr_session(
                f.adr_session_payload(
                    project["id"],
                    talent["id"],
                    window_start_utc="2026-09-14T10:30:00Z",
                    window_end_utc="2026-09-14T11:30:00Z",
                ),
                EDITOR_HEADERS,
            ),
            201,
        )
        assert retry["status"] == "PROPOSED"
        assert_decimal(retry["billable_minutes"], 60.00)

        assert world.get_adr(first["id"])["status"] == "CONFIRMED"
        _sessions, meta = validate_paginated(
            api.list_adr_sessions(EDITOR_HEADERS, {"voice_talent_id": talent["id"]})
        )
        assert meta["total_count"] == 3

        ledger = world.ledger(project["id"])
        assert ledger["adr_cost_cents"] == 108000
        assert ledger["billing_total_cents"] == 108000


class TestAdrSchedulingNeedsALockedPicture:
    """The ADR gate reads a status that lives on another entity entirely."""

    def _unlocked_project(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        talent = world.voice_talent(
            union_status="UNION", daily_cap_minutes=240, min_call_minutes=60
        )
        project = world.project()
        assert project["picture_status"] == "NOT_LOCKED"
        assert project["pipeline_stage"] == "INTAKE"
        return talent, project

    def test_scheduling_against_an_unlocked_cut_is_refused(self, world, api):
        """No session exists while the picture can still move.

        PRD §3.5: "ADR sessions are booked against a picture-locked project — the whole
        point of an ADR pass is to replace lines against a cut that will not move again,
        so scheduling a session on a project whose `picture_status` is anything other than
        `LOCKED` is rejected with `ERR_PICTURE_NOT_LOCKED`, and so is confirming one."

        Design: Difficulty/cross_entity_state_dependency/adr_session_create_gated_on_project_picture_status
        """
        talent, project = self._unlocked_project(world)

        response = api.create_adr_session(
            f.adr_session_payload(
                project["id"],
                talent["id"],
                window_start_utc="2026-09-14T09:00:00Z",
                window_end_utc="2026-09-14T09:45:00Z",
                lines_scheduled=10,
            ),
            EDITOR_HEADERS,
        )
        validate_error(response, ERR_PICTURE_NOT_LOCKED, 409)

        _sessions, meta = validate_paginated(
            api.list_adr_sessions(EDITOR_HEADERS, {"project_id": project["id"]})
        )
        assert meta["total_count"] == 0
        assert world.ledger(project["id"])["adr_cost_cents"] == 0

    def test_locking_the_picture_admits_the_identical_request(self, world, api):
        """The same payload succeeds once the cut is frozen, and confirmation bills it.

        PRD §2.11: "**Rung 18** — the project's `picture_status` is not `LOCKED` and the
        operation requires a locked picture. The requiring operations are exactly four:
        ADR session creation, ADR session confirmation, booking creation whose
        `booking_type` is `FINAL_MIX` or `PRINTMASTER`, and deliverable creation."

        Design: Difficulty/cross_entity_state_dependency/adr_session_create_gated_on_project_picture_status
        """
        talent, project = self._unlocked_project(world)
        payload = f.adr_session_payload(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T09:45:00Z",
            lines_scheduled=10,
        )
        validate_error(
            api.create_adr_session(payload, EDITOR_HEADERS), ERR_PICTURE_NOT_LOCKED, 409
        )

        locked = world.lock_picture(project["id"], picture_lock_note="locked for ADR")
        assert locked["picture_status"] == "LOCKED"
        assert locked["pipeline_stage"] == "EDITORIAL"

        session = validate_success(api.create_adr_session(payload, EDITOR_HEADERS), 201)
        assert session["status"] == "PROPOSED"
        assert session["lines_recorded"] == 0
        assert_decimal(session["billable_minutes"], 60.00)
        assert session["session_cost_cents"] == 54000

        confirmed = world.confirm_adr(session["id"])
        assert confirmed["status"] == "CONFIRMED"

        ledger = world.ledger(project["id"])
        assert ledger["adr_cost_cents"] == 54000
        assert ledger["billing_total_cents"] == 54000
