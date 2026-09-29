"""Field-level and cross-entity guards, and which one answers when two fire."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ADR_LINES_EXCEEDED,
    ERR_CROSS_PROJECT_REFERENCE,
    ERR_DELIVERABLE_STILL_OPEN,
    ERR_INVALID_STATE,
    ERR_MIXER_DAILY_LIMIT_EXCEEDED,
    ERR_NO_DELIVERED_DELIVERABLE,
    ERR_SPEC_PLATFORM_MISMATCH,
    ERR_STAGE_NO_REMOTE_REVIEW,
    ERR_STEM_NOT_CONFORMED,
    ERR_TALENT_DAILY_CAP_EXCEEDED,
    ERR_TALENT_WINDOW_CONFLICT,
    ERR_WINDOW_AFTER_DEADLINE,
    ERR_WINDOW_ELAPSED,
    ERR_WINDOW_INVALID,
)
from test_helpers.assertions import assert_decimal, assert_instants_equal
from test_helpers.constants import QC_VERDICT_PASS
from test_helpers.test_users import EDITOR_HEADERS, SUPERVISOR_HEADERS, mixer_headers


class TestWindowShapeBeforeTheDeliveryDeadline:
    """A window is checked for shape first and for lateness only afterwards."""

    def _facility_with_a_near_deadline(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Window Wren", certified_platforms=["STREAMING"])
        project = world.project(
            title="Window Shape", delivery_deadline_utc="2026-09-20T00:00:00Z"
        )
        assert project["picture_status"] == "NOT_LOCKED"
        return stage, mixer, project

    def _premix(self, version, project, stage, mixer, start, end):
        return f.mix_booking_payload(
            version,
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc=start,
            window_end_utc=end,
        )

    def test_the_shape_guard_answers_even_when_the_window_is_also_too_late(self, world, api):
        """A zero-length, an inverted and a late window, then one that is legal.

        PRD §2.11: "**Rung 31** — `window_end_utc` is at or before `window_start_utc`, on
        booking creation and ADR session creation: `ERR_WINDOW_INVALID`, 422."

        Design: Corner/validations/window_shape_is_checked_before_the_delivery_deadline
        """
        stage, mixer, project = self._facility_with_a_near_deadline(world)
        version = world.project_version(project["id"])

        zero_length = api.create_mix_booking(
            self._premix(
                version, project, stage, mixer,
                "2026-09-14T12:00:00Z", "2026-09-14T12:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        )
        validate_error(zero_length, ERR_WINDOW_INVALID, 422)

        inverted = api.create_mix_booking(
            self._premix(
                version, project, stage, mixer,
                "2026-09-14T14:00:00Z", "2026-09-14T13:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        )
        validate_error(inverted, ERR_WINDOW_INVALID, 422)

        past_deadline = api.create_mix_booking(
            self._premix(
                version, project, stage, mixer,
                "2026-09-21T10:00:00Z", "2026-09-21T13:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        )
        validate_error(past_deadline, ERR_WINDOW_AFTER_DEADLINE, 422)

        both_defects = api.create_mix_booking(
            self._premix(
                version, project, stage, mixer,
                "2026-09-21T13:00:00Z", "2026-09-21T10:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        )
        validate_error(both_defects, ERR_WINDOW_INVALID, 422)

        accepted = validate_success(
            api.create_mix_booking(
                self._premix(
                    version, project, stage, mixer,
                    "2026-09-14T10:00:00Z", "2026-09-14T13:00:00Z",
                ),
                SUPERVISOR_HEADERS,
            ),
            201,
        )
        assert accepted["status"] == "RESERVED"
        assert_decimal(accepted["reserved_hours"], 3.00)

        assert world.project_version(project["id"]) == version + 1
        _bookings, meta = validate_paginated(
            api.list_mix_bookings(SUPERVISOR_HEADERS, {"project_id": project["id"]})
        )
        assert meta["total_count"] == 1


class TestRemoteAttendanceNeedsAWiredRoom:
    """The capability lives on the stage, so the same room still takes an onsite client."""

    def _two_rooms_and_two_projects(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        unwired = world.mix_stage(
            display_name="Stage V2X (no remote)",
            hourly_rate_cents=100000,
            supports_remote_review=False,
        )
        wired = world.mix_stage(
            display_name="Stage V2Y (remote ok)",
            hourly_rate_cents=100000,
            supports_remote_review=True,
        )
        mixer = world.mixer(full_name="Remote Rae", certified_platforms=["STREAMING"])
        first = world.project(title="Remote Gate A")
        second = world.project(title="Remote Gate B")
        return unwired, wired, mixer, first, second

    def test_remote_is_refused_on_the_unwired_room_and_accepted_on_the_wired_one(
        self, world, api
    ):
        """Onsite attendance on the same unwired stage is accepted without complaint.

        PRD §3.6: "Remote attendance requires a wired room: a `client_attendance` of
        `REMOTE` against a stage whose `supports_remote_review` is false is rejected with
        `ERR_STAGE_NO_REMOTE_REVIEW`."

        Design: Corner/validations/remote_attendance_requires_a_remote_capable_stage
        """
        unwired, wired, mixer, first, second = self._two_rooms_and_two_projects(world)
        version = world.project_version(first["id"])

        refused = api.create_mix_booking(
            f.mix_booking_payload(
                version,
                first["id"],
                unwired["id"],
                mixer["id"],
                booking_type="PREMIX",
                platform="STREAMING",
                window_start_utc="2026-09-14T10:00:00Z",
                window_end_utc="2026-09-14T12:00:00Z",
                client_attendance="REMOTE",
            ),
            SUPERVISOR_HEADERS,
        )
        validate_error(refused, ERR_STAGE_NO_REMOTE_REVIEW, 422)

        onsite = world.booking(
            first["id"],
            unwired["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
            client_attendance="ONSITE",
        )
        assert onsite["client_attendance"] == "ONSITE"
        assert onsite["status"] == "RESERVED"

        remote = world.booking(
            second["id"],
            wired["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
            client_attendance="REMOTE",
        )
        assert remote["client_attendance"] == "REMOTE"
        assert remote["client_signoff_at_utc"] is None

        assert_decimal(world.get_project(first["id"])["stage_hours_reserved"], 2.00)
        assert_decimal(world.get_project(second["id"])["stage_hours_reserved"], 2.00)


class TestMixerDailyHoursAreAWholeDayAggregate:
    """Each session is legal alone; the mixer's day is what fills up."""

    def _three_same_day_sessions_and_one_the_next_day(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=100000, changeover_minutes=45)
        mixer = world.mixer(
            full_name="Daily Dana", certified_platforms=["STREAMING"], max_daily_hours=6.00
        )
        busy_day = world.locked_project(title="Daily Limit A")
        next_day = world.project(title="Daily Limit B")

        first = world.booking(
            busy_day["id"], stage["id"], mixer["id"],
            booking_type="PREMIX", platform="STREAMING",
            window_start_utc="2026-09-14T08:00:00Z", window_end_utc="2026-09-14T11:00:00Z",
        )
        second = world.booking(
            busy_day["id"], stage["id"], mixer["id"],
            booking_type="FINAL_MIX", platform="STREAMING",
            window_start_utc="2026-09-14T12:00:00Z", window_end_utc="2026-09-14T15:00:00Z",
        )
        third = world.booking(
            busy_day["id"], stage["id"], mixer["id"],
            booking_type="PRINTMASTER", platform="STREAMING",
            window_start_utc="2026-09-14T16:00:00Z", window_end_utc="2026-09-14T19:00:00Z",
        )
        fourth = world.booking(
            next_day["id"], stage["id"], mixer["id"],
            booking_type="PREMIX", platform="STREAMING",
            window_start_utc="2026-09-15T08:00:00Z", window_end_utc="2026-09-15T11:00:00Z",
        )
        for booking in (first, second, third, fourth):
            assert booking["status"] == "RESERVED"
            assert_decimal(booking["reserved_hours"], 3.00)
        return stage, mixer, busy_day, next_day, first, second, third, fourth

    def test_two_acceptances_reach_the_cap_exactly_and_the_third_is_refused(self, world, api):
        """Reserved hours never count, so all four reservations are created first.

        PRD §3.6: "It also enforces the mixer's own workload: the sum of `reserved_hours`
        over that mixer's bookings whose `status` is `CONFIRMED`, `IN_PROGRESS` or
        `COMPLETED` and whose `window_start_utc` falls on the same UTC calendar day, plus
        this booking's `reserved_hours`, must not exceed the mixer's `max_daily_hours`;
        exceeding it is rejected with `ERR_MIXER_DAILY_LIMIT_EXCEEDED`."

        Design: Corner/validations/mixer_daily_hours_are_an_aggregate_over_one_utc_day
        """
        _stage, mixer, busy_day, _next_day, first, second, third, fourth = (
            self._three_same_day_sessions_and_one_the_next_day(world)
        )

        assert world.confirm_booking(first["id"], mixer["id"])["status"] == "CONFIRMED"
        assert world.confirm_booking(second["id"], mixer["id"])["status"] == "CONFIRMED"

        over_the_limit = api.confirm_mix_booking(third["id"], {}, mixer_headers(mixer["id"]))
        validate_error(over_the_limit, ERR_MIXER_DAILY_LIMIT_EXCEEDED, 409)
        assert world.get_booking(third["id"])["status"] == "RESERVED"

        assert world.confirm_booking(fourth["id"], mixer["id"])["status"] == "CONFIRMED"

        assert_decimal(world.get_project(busy_day["id"])["stage_hours_reserved"], 9.00)
        _confirmed, meta = validate_paginated(
            api.list_mix_bookings(
                SUPERVISOR_HEADERS, {"mixer_id": mixer["id"], "status": "CONFIRMED"}
            )
        )
        assert meta["total_count"] == 3


class TestTalentOverlapOutranksTheDailyCap:
    """A request that both collides and overruns reports the collision."""

    def _talent_with_a_full_day(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        talent = world.voice_talent(
            full_name="Overlap Ola", union_status="UNION", daily_cap_minutes=60,
            min_call_minutes=60,
        )
        project = world.locked_project(title="Overlap Before Cap")
        booked = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T10:00:00Z",
            lines_scheduled=10,
        )
        assert world.confirm_adr(booked["id"])["status"] == "CONFIRMED"
        return talent, project, booked

    def test_the_overlapping_window_reports_the_conflict_and_the_clear_one_the_cap(
        self, world, api
    ):
        """Both requests are over the 60-minute cap, yet they answer differently.

        PRD §2.11: "**Rung 34** — the requested ADR window strictly overlaps an existing
        session of the same talent, on ADR session creation: `ERR_TALENT_WINDOW_CONFLICT`,
        409."

        Design: Corner/validations/talent_window_conflict_is_checked_before_the_daily_cap
        """
        talent, project, _booked = self._talent_with_a_full_day(world)

        overlapping = api.create_adr_session(
            f.adr_session_payload(
                project["id"],
                talent["id"],
                window_start_utc="2026-09-14T09:30:00Z",
                window_end_utc="2026-09-14T10:30:00Z",
                lines_scheduled=10,
            ),
            EDITOR_HEADERS,
        )
        validate_error(overlapping, ERR_TALENT_WINDOW_CONFLICT, 409)

        clear_of_the_booking = api.create_adr_session(
            f.adr_session_payload(
                project["id"],
                talent["id"],
                window_start_utc="2026-09-14T11:00:00Z",
                window_end_utc="2026-09-14T12:00:00Z",
                lines_scheduled=10,
            ),
            EDITOR_HEADERS,
        )
        validate_error(clear_of_the_booking, ERR_TALENT_DAILY_CAP_EXCEEDED, 409)

        next_day = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-15T09:00:00Z",
            window_end_utc="2026-09-15T10:00:00Z",
            lines_scheduled=10,
        )
        assert next_day["status"] == "PROPOSED"
        assert_decimal(next_day["billable_minutes"], 60.00)

        _sessions, meta = validate_paginated(
            api.list_adr_sessions(EDITOR_HEADERS, {"voice_talent_id": talent["id"]})
        )
        assert meta["total_count"] == 2
        assert world.ledger(project["id"])["adr_cost_cents"] == 54000


class TestSpecMismatchOutranksTheForeignReference:
    """Platform agreement is settled before ownership of the referenced records."""

    def _two_projects_and_two_specs(self, world):
        environment = world.prepared_environment(
            prepare=False,
            platform="THEATRICAL",
            spec={"spec_label": "Theatrical Priority Spec"},
            project={"title": "Priority Project A"},
            mixer={"full_name": "Mismatch Mel"},
        )
        streaming_spec = world.platform_spec(
            platform="STREAMING",
            spec_label="Streaming Priority Spec",
            target_lufs=-16.00,
            tolerance_lu=1.00,
            true_peak_max_dbtp=-1.00,
            channel_layout="STEREO",
        )
        foreign_project = world.locked_project(title="Priority Project B")
        foreign_package = world.conformed_package(foreign_project["id"])
        return environment, streaming_spec, foreign_package

    def test_the_mismatched_spec_answers_even_with_a_foreign_stem_package(self, world, api):
        """Each defect alone reports its own code; together the platform code wins.

        PRD §2.11: "**Rung 28** — the platform specification's `platform` differs from the
        `platform` of the booking the deliverable references, on deliverable creation:
        `ERR_SPEC_PLATFORM_MISMATCH`, 422."

        Design: Corner/validations/spec_platform_mismatch_outranks_cross_project_reference
        """
        environment, streaming_spec, foreign_package = self._two_projects_and_two_specs(world)
        project_id = environment["project"]["id"]
        booking_id = environment["booking"]["id"]
        own_package_id = environment["package"]["id"]
        version = world.project_version(project_id)

        def create(spec_id, stem_package_id):
            return api.create_deliverable(
                f.deliverable_payload(
                    version, project_id, spec_id, stem_package_id, booking_id
                ),
                SUPERVISOR_HEADERS,
            )

        validate_error(
            create(environment["spec"]["id"], foreign_package["id"]),
            ERR_CROSS_PROJECT_REFERENCE,
            422,
        )
        validate_error(
            create(streaming_spec["id"], own_package_id), ERR_SPEC_PLATFORM_MISMATCH, 422
        )
        validate_error(
            create(streaming_spec["id"], foreign_package["id"]),
            ERR_SPEC_PLATFORM_MISMATCH,
            422,
        )

        prepared = validate_success(
            create(environment["spec"]["id"], own_package_id), 201
        )
        assert prepared["status"] == "PREPARED"
        assert prepared["stem_package_id"] == own_package_id
        assert world.project_version(project_id) == version + 1

        _deliverables, meta = validate_paginated(
            api.list_deliverables(SUPERVISOR_HEADERS, {"project_id": project_id})
        )
        assert meta["total_count"] == 1


class TestDraftStemPackageBlocksPreparation:
    """The gate reads the package's status, not whether it holds cues."""

    def _facility_with_a_draft_package(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        spec = world.platform_spec(
            platform="THEATRICAL", spec_label="Theatrical Conform Gate Spec"
        )
        stage = world.mix_stage(hourly_rate_cents=120000)
        mixer = world.mixer(full_name="Conform Cass", certified_platforms=["THEATRICAL"])
        project = world.locked_project(title="Conform Gate")
        package = world.stem_package(project["id"])
        world.add_cue(package["id"], cue_number="1M1", duration_seconds=120)
        assert world.get_stem_package(package["id"])["status"] == "DRAFT"
        booking = world.completed_booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="FINAL_MIX",
            platform="THEATRICAL",
        )
        return spec, project, package, booking

    def test_the_identical_request_succeeds_once_the_package_is_conformed(self, world, api):
        """Nothing but the package's status changes between the refusal and the 201.

        PRD §2.11: "**Rung 20** — the referenced stem package's `status` is not
        `CONFORMED`, on deliverable creation, QC submission and delivery:
        `ERR_STEM_NOT_CONFORMED`, 409."

        Design: Corner/validations/draft_stem_package_cannot_be_prepared_then_conform_unblocks_it
        """
        spec, project, package, booking = self._facility_with_a_draft_package(world)

        refused = api.create_deliverable(
            f.deliverable_payload(
                world.project_version(project["id"]),
                project["id"],
                spec["id"],
                package["id"],
                booking["id"],
            ),
            SUPERVISOR_HEADERS,
        )
        validate_error(refused, ERR_STEM_NOT_CONFORMED, 409)

        conformed = world.conform(package["id"])
        assert conformed["status"] == "CONFORMED"
        assert conformed["conform_fee_cents"] == 3000

        prepared = world.deliverable(
            project["id"], spec["id"], package["id"], booking["id"]
        )
        assert prepared["status"] == "PREPARED"
        assert prepared["stem_package_id"] == package["id"]
        assert prepared["mix_booking_id"] == booking["id"]

        ledger = world.ledger(project["id"])
        assert ledger["conform_fee_total_cents"] == 3000
        assert ledger["billing_total_cents"] == 363000


class TestRecordedLinesCannotExceedTheSchedule:
    """The boundary sits at equality: ten of ten is accepted, eleven is not."""

    def _confirmed_session_inside_its_window(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        talent = world.voice_talent(
            full_name="Lines Lena", union_status="UNION", daily_cap_minutes=240,
            min_call_minutes=60,
        )
        project = world.locked_project(title="Line Count")
        session = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T10:00:00Z",
            lines_scheduled=10,
        )
        world.confirm_adr(session["id"])
        world.set_clock("2026-09-14T09:30:00Z")
        return talent, project, session

    def test_eleven_of_ten_lines_is_refused_and_ten_is_recorded(self, world, api):
        """The refusal leaves the session confirmed with nothing recorded against it.

        PRD §2.11: "**Rung 39** — `lines_recorded` exceeds the session's `lines_scheduled`,
        on ADR session recording: `ERR_ADR_LINES_EXCEEDED`, 422."

        Design: Corner/validations/adr_record_cannot_exceed_the_scheduled_line_count
        """
        _talent, project, session = self._confirmed_session_inside_its_window(world)

        over = api.record_adr_session(
            session["id"], f.adr_record_payload(lines_recorded=11), EDITOR_HEADERS
        )
        validate_error(over, ERR_ADR_LINES_EXCEEDED, 422)

        untouched = world.get_adr(session["id"])
        assert untouched["status"] == "CONFIRMED"
        assert untouched["lines_recorded"] == 0

        recorded = world.record_adr(session["id"], lines_recorded=10)
        assert recorded["status"] == "RECORDED"
        assert recorded["lines_recorded"] == 10
        assert recorded["session_cost_cents"] == 54000

        assert world.ledger(project["id"])["adr_cost_cents"] == 54000


class TestOpeningAfterTheWindowHasElapsed:
    """The temporal guard fires at the window's end, not at its start."""

    def _two_confirmed_sessions_on_separate_rooms(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        first_stage = world.mix_stage(display_name="Stage V8A", hourly_rate_cents=100000)
        second_stage = world.mix_stage(display_name="Stage V8B", hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Elapse Eli", certified_platforms=["STREAMING"])
        first_project = world.project(title="Elapsed A")
        second_project = world.project(title="Elapsed B")

        early = world.booking(
            first_project["id"], first_stage["id"], mixer["id"],
            booking_type="PREMIX", platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z", window_end_utc="2026-09-14T12:00:00Z",
        )
        late = world.booking(
            second_project["id"], second_stage["id"], mixer["id"],
            booking_type="PREMIX", platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z", window_end_utc="2026-09-14T12:00:00Z",
        )
        world.confirm_booking(early["id"], mixer["id"])
        world.confirm_booking(late["id"], mixer["id"])
        return mixer, second_project, early, late

    def test_one_minute_before_the_end_opens_and_the_end_instant_itself_does_not(
        self, world, api
    ):
        """The clock reaching `window_end_utc` exactly closes the door on the session.

        PRD §2.11: "**Rung 37** — the logical clock is already at or past the booking's
        `window_end_utc`, on booking start: `ERR_WINDOW_ELAPSED`, 409."

        Design: Corner/validations/booking_start_after_the_window_has_elapsed_is_rejected
        """
        mixer, second_project, early, late = self._two_confirmed_sessions_on_separate_rooms(
            world
        )

        world.set_clock("2026-09-14T11:59:00Z")
        opened = world.start_booking(early["id"], mixer["id"])
        assert opened["status"] == "IN_PROGRESS"
        assert_instants_equal(opened["actual_start_utc"], "2026-09-14T11:59:00Z")

        world.set_clock("2026-09-14T12:00:00Z")
        elapsed = api.start_mix_booking(late["id"], {}, mixer_headers(mixer["id"]))
        validate_error(elapsed, ERR_WINDOW_ELAPSED, 409)

        unopened = world.get_booking(late["id"])
        assert unopened["status"] == "CONFIRMED"
        assert unopened["actual_start_utc"] is None

        project_after = world.get_project(second_project["id"])
        assert_decimal(project_after["stage_hours_reserved"], 2.00)
        assert_decimal(project_after["stage_hours_consumed"], 0.00)


class TestArchiveGatesCheckDeliveredBeforeStillOpen:
    """With nothing delivered and one deliverable open, the delivery gate answers."""

    def _project_with_one_prepared_deliverable(self, world):
        environment = world.prepared_environment(
            platform="THEATRICAL",
            spec={"spec_label": "Theatrical Archive Gate Spec One"},
            project={"title": "Archive Gates"},
            mixer={"full_name": "Gate Gina"},
        )
        return environment

    def test_the_delivery_gate_answers_first_and_the_open_gate_answers_next(self, world, api):
        """Delivering the first deliverable and preparing a second leaves one gate standing.

        PRD §2.11: "**Rung 40** — the project has zero deliverables in `DELIVERED` status,
        on archival: `ERR_NO_DELIVERED_DELIVERABLE`, 409."

        Design: Corner/validations/archive_gates_check_delivered_before_still_open
        """
        environment = self._project_with_one_prepared_deliverable(world)
        project_id = environment["project"]["id"]
        package_id = environment["package"]["id"]
        first_id = environment["deliverable"]["id"]

        nothing_delivered = api.create_archive_package(
            project_id, f.archive_package_payload(session_file_count=8), SUPERVISOR_HEADERS
        )
        # PRD §3.8 lists two independent archival preconditions that both fail here: "The
        # project's `pipeline_stage` must be `DELIVERED`" (still `QC` at this point, which
        # rung 19 reports as `ERR_INVALID_STATE`) and "The project must have at least one
        # deliverable whose `status` is `DELIVERED`, or the request is rejected with
        # `ERR_NO_DELIVERED_DELIVERABLE`".  PRD does not say which code the pipeline-stage
        # precondition carries, so either rung may legitimately answer.
        validate_error_is_one_of(
            nothing_delivered, [ERR_NO_DELIVERED_DELIVERABLE, ERR_INVALID_STATE]
        )

        world.qc_submit(
            first_id,
            measured_integrated_lufs=-24.10,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )
        assert world.qc_evaluate(first_id)["verdict"] == QC_VERDICT_PASS
        delivered = world.deliver(first_id, delivery_reference="DCP-V9-A")
        assert delivered["status"] == "DELIVERED"
        assert delivered["delivery_reference"] == "DCP-V9-A"
        assert world.get_project(project_id)["pipeline_stage"] == "DELIVERED"

        second_spec = world.platform_spec(
            platform="THEATRICAL",
            spec_label="Theatrical Archive Gate Spec Two",
            channel_layout="7_1",
        )
        second = world.deliverable(
            project_id, second_spec["id"], package_id, environment["booking"]["id"]
        )
        assert second["status"] == "PREPARED"

        still_open = api.create_archive_package(
            project_id, f.archive_package_payload(session_file_count=8), SUPERVISOR_HEADERS
        )
        validate_error(still_open, ERR_DELIVERABLE_STILL_OPEN, 409)

        _packages, meta = validate_paginated(
            api.list_archive_packages(project_id, SUPERVISOR_HEADERS)
        )
        assert meta["total_count"] == 0
        assert world.get_stem_package(package_id)["status"] == "CONFORMED"
