"""Two requests that trip two guards at once, and which code each must report."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_MIXER_NOT_CERTIFIED,
    ERR_PROJECT_FROZEN,
    ERR_STAGE_HOURS_EXCEEDED,
    ERR_STAGE_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_decimal, assert_hour_ledger
from test_helpers.test_users import SUPERVISOR_HEADERS


class TestFrozenPostureOutranksTheStageConflict:
    """A frozen project never gets as far as the room's occupancy check."""

    def _frozen_project_with_an_occupied_room(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=120000, changeover_minutes=45)
        mixer = world.mixer(certified_platforms=["THEATRICAL", "STREAMING"])
        project = world.locked_project(turnaround_class="STANDARD", stage_hours_authorized=40.00)
        occupant = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="FINAL_MIX",
            platform="THEATRICAL",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T13:00:00Z",
        )
        assert occupant["status"] == "RESERVED"
        broken = world.break_lock(project["id"], break_reason="new cut delivered by editorial")
        assert broken["posture"] == "FROZEN"
        assert world.get_booking(occupant["id"])["status"] == "RESERVED"
        return stage, mixer, project, occupant

    def _colliding_premix(self, world, project, stage, mixer):
        return f.mix_booking_payload(
            world.project_version(project["id"]),
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="THEATRICAL",
            window_start_utc="2026-09-14T11:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
        )

    def test_the_posture_gate_answers_before_the_occupancy_check(self, world, api):
        """A window squarely inside an occupied slot still reports the frozen project.

        PRD §2.11: "**Rung 16** — the project's derived posture blocks the operation, as
        specified in §2.9, on every child write of a project: `ERR_PROJECT_FROZEN`, 409."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_priority16_beats_stage_window_conflict_priority33
        """
        stage, mixer, project, occupant = self._frozen_project_with_an_occupied_room(world)

        response = api.create_mix_booking(
            self._colliding_premix(world, project, stage, mixer), SUPERVISOR_HEADERS
        )
        validate_error(response, ERR_PROJECT_FROZEN, 409)

        assert world.get_booking(occupant["id"])["status"] == "RESERVED"
        _listed, meta = validate_paginated(
            api.list_mix_bookings(SUPERVISOR_HEADERS, {"project_id": project["id"]})
        )
        assert meta["total_count"] == 1
        assert_decimal(world.get_project(project["id"])["stage_hours_reserved"], 3.00)

    def test_relocking_lets_the_lower_rung_answer_the_identical_request(self, world, api):
        """With the posture gate lifted, the same payload reports the room collision.

        PRD §2.11: "**Rung 33** — the requested stage window plus the stage's changeover
        buffer overlaps an occupying booking on the same stage, on booking creation:
        `ERR_STAGE_WINDOW_CONFLICT`, 409."

        Design: Difficulty/priority_pair_validation_conflict/frozen_posture_priority16_beats_stage_window_conflict_priority33
        """
        stage, mixer, project, occupant = self._frozen_project_with_an_occupied_room(world)
        validate_error(
            api.create_mix_booking(
                self._colliding_premix(world, project, stage, mixer), SUPERVISOR_HEADERS
            ),
            ERR_PROJECT_FROZEN,
            409,
        )

        relocked = world.lock_picture(project["id"], picture_lock_note="cut v2 locked")
        assert relocked["picture_status"] == "LOCKED"
        assert relocked["posture"] == "OPEN"

        retry = api.create_mix_booking(
            self._colliding_premix(world, project, stage, mixer), SUPERVISOR_HEADERS
        )
        validate_error(retry, ERR_STAGE_WINDOW_CONFLICT, 409)

        assert world.get_booking(occupant["id"])["status"] == "RESERVED"
        _listed, meta = validate_paginated(
            api.list_mix_bookings(SUPERVISOR_HEADERS, {"project_id": project["id"]})
        )
        assert meta["total_count"] == 1


class TestCertificationOutranksTheHourBudget:
    """A request that is both mis-staffed and over budget reports the staffing defect."""

    def _over_budget_request(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=100000)
        uncertified = world.mixer(full_name="Streaming Only", certified_platforms=["STREAMING"])
        certified = world.mixer(full_name="Theatrical Mixer", certified_platforms=["THEATRICAL"])
        project = world.locked_project(turnaround_class="STANDARD", stage_hours_authorized=4.00)
        return stage, uncertified, certified, project

    def _six_hour_premix(self, world, project, stage, mixer):
        return f.mix_booking_payload(
            world.project_version(project["id"]),
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="THEATRICAL",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T16:00:00Z",
        )

    def test_an_uncertified_mixer_is_reported_ahead_of_the_hour_overrun(self, world, api):
        """Six hours against a four-hour budget still answers with the certification code.

        PRD §3.6: "That guard sits deliberately **after** the mixer-certification guard in
        the precedence ladder of §2.11, so a request that both names an uncertified mixer
        and blows the hour budget reports the certification defect."

        Design: Difficulty/priority_pair_validation_conflict/mixer_certification_priority24_beats_stage_hours_priority42
        """
        stage, uncertified, _certified, project = self._over_budget_request(world)
        version_before = world.project_version(project["id"])

        response = api.create_mix_booking(
            self._six_hour_premix(world, project, stage, uncertified), SUPERVISOR_HEADERS
        )
        validate_error(response, ERR_MIXER_NOT_CERTIFIED, 422)

        project_after = world.get_project(project["id"])
        assert project_after["version"] == version_before
        assert_hour_ledger(project_after, 0.00, 0.00, 4.00)
        _listed, meta = validate_paginated(
            api.list_mix_bookings(SUPERVISOR_HEADERS, {"project_id": project["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_certified_mixer_exposes_the_fiscal_guard_underneath(self, world, api):
        """Fixing the staffing defect alone leaves the budget defect to answer.

        PRD §2.11: "**Rung 42** — the requested booking's `reserved_hours` exceeds the
        project's `stage_hours_available` as computed after excluding any booking this same
        request supersedes, on booking creation: `ERR_STAGE_HOURS_EXCEEDED`, 409."

        Design: Difficulty/priority_pair_validation_conflict/mixer_certification_priority24_beats_stage_hours_priority42
        """
        stage, uncertified, certified, project = self._over_budget_request(world)
        validate_error(
            api.create_mix_booking(
                self._six_hour_premix(world, project, stage, uncertified), SUPERVISOR_HEADERS
            ),
            ERR_MIXER_NOT_CERTIFIED,
            422,
        )

        response = api.create_mix_booking(
            self._six_hour_premix(world, project, stage, certified), SUPERVISOR_HEADERS
        )
        validate_error(response, ERR_STAGE_HOURS_EXCEEDED, 409)

        project_after = world.get_project(project["id"])
        assert_decimal(project_after["stage_hours_reserved"], 0.00)
        assert_decimal(project_after["stage_hours_available"], 4.00)
        assert project_after["stage_cost_subtotal_cents"] == 0
        _listed, meta = validate_paginated(
            api.list_mix_bookings(SUPERVISOR_HEADERS, {"project_id": project["id"]})
        )
        assert meta["total_count"] == 0
