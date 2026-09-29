"""Initial states, refused transitions, terminal lockdown and supersession."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_INVALID_STATE, ERR_PROJECT_ARCHIVED
from test_helpers.assertions import assert_decimal, assert_hour_ledger, assert_instants_equal
from test_helpers.constants import SUPERVISOR_USER_ID
from test_helpers.test_users import EDITOR_HEADERS, SUPERVISOR_HEADERS, mixer_headers


class TestAdrSessionInitialState:
    """A scheduled call is only a proposal until somebody accepts it."""

    def test_a_new_session_is_proposed_and_bills_nothing_yet(self, world):
        """A non-union 45-minute call prices at 27000 and stays out of the ledger.

        PRD §3.5: "A newly scheduled session lands in `PROPOSED` with `lines_recorded` 0
        and `cancellation_reason` null, and it contributes nothing to the project's money
        yet — a proposed session's `session_cost_cents` is outside `adr_cost_cents`."

        Design: Corner/state_machines/adr_session_initial_state_is_proposed
        """
        world.set_clock("2026-09-01T00:00:00Z")
        talent = world.voice_talent(
            full_name="Init Ivy", union_status="NON_UNION", daily_cap_minutes=240,
            min_call_minutes=60,
        )
        project = world.locked_project(title="Initial State")

        session = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T09:45:00Z",
            lines_scheduled=9,
        )

        assert session["status"] == "PROPOSED"
        assert session["lines_recorded"] == 0
        assert session["cancellation_reason"] is None
        assert_decimal(session["scheduled_minutes"], 45.00)
        assert_decimal(session["billable_minutes"], 45.00)
        assert session["session_cost_cents"] == 27000

        assert world.ledger(project["id"])["adr_cost_cents"] == 0


class TestBookingAcceptanceIsNotIdempotent:
    """Accepting a second time is a transition the booking no longer has."""

    def _confirmed_premix(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Idem Ike", certified_platforms=["STREAMING"])
        project = world.project(title="Idempotency")
        booking = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
        )
        accepted = world.confirm_booking(booking["id"], mixer["id"])
        assert accepted["status"] == "CONFIRMED"
        return mixer, project, booking

    def test_the_second_acceptance_is_refused_and_the_hours_are_counted_once(self, world, api):
        """The rejected repeat leaves the status, the ledger and the version alone.

        PRD §2.11: "**Rung 19** — the target entity's current status has no transition for
        the requested action, on every action endpoint: `ERR_INVALID_STATE`, 409."

        Design: Corner/state_machines/booking_confirm_twice_second_call_is_invalid_state
        """
        mixer, project, booking = self._confirmed_premix(world)
        version_after_first = world.project_version(project["id"])

        response = api.confirm_mix_booking(booking["id"], {}, mixer_headers(mixer["id"]))
        validate_error(response, ERR_INVALID_STATE, 409)

        assert world.get_booking(booking["id"])["status"] == "CONFIRMED"
        project_after = world.get_project(project["id"])
        assert_decimal(project_after["stage_hours_reserved"], 2.00)
        assert project_after["version"] == version_after_first
        assert world.ledger(project["id"])["stage_cost_subtotal_cents"] == 200000


class TestOpeningRequiresAnAcceptedBooking:
    """A reserved slot cannot be walked into."""

    def test_opening_a_merely_reserved_slot_is_refused(self, world, api):
        """The stage stays shut, so no start instant is stamped and no hours are used.

        PRD §3.6: "**Opening** the stage moves the booking `CONFIRMED → IN_PROGRESS`,
        stamps `actual_start_utc` with the logical clock's current instant, and requires
        the project's `posture` not to be `FROZEN`."

        Design: Corner/state_machines/start_booking_directly_from_reserved_is_invalid_transition
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Skip Sam", certified_platforms=["STREAMING"])
        project = world.project(title="Skip Confirm")
        booking = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
        )
        assert booking["status"] == "RESERVED"
        world.set_clock("2026-09-14T10:00:00Z")

        response = api.start_mix_booking(booking["id"], {}, mixer_headers(mixer["id"]))
        validate_error(response, ERR_INVALID_STATE, 409)

        unopened = world.get_booking(booking["id"])
        assert unopened["status"] == "RESERVED"
        assert unopened["actual_start_utc"] is None
        assert_decimal(world.get_project(project["id"])["stage_hours_consumed"], 0.00)


class TestCompletionIsTerminal:
    """Consumed hours can never be handed back through a release."""

    def test_releasing_a_closed_session_is_refused(self, world, api):
        """The clawback fails and the two consumed hours stay consumed.

        PRD §3.6: "**Releasing** a slot is a `PostSupervisor` action carrying a mandatory
        `release_reason`, permitted out of `RESERVED` and out of `CONFIRMED` and requiring
        that the project's `pipeline_stage` not be `ARCHIVED`."

        Design: Corner/state_machines/release_after_completion_is_blocked_by_terminal_state
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Term Tess", certified_platforms=["STREAMING"])
        project = world.project(title="Terminal Lockdown")
        closed = world.completed_booking(
            project["id"],
            stage["id"],
            mixer["id"],
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
            booking_type="PREMIX",
            platform="STREAMING",
        )
        assert closed["status"] == "COMPLETED"

        response = api.release_mix_booking(
            closed["id"], f.release_payload(release_reason="attempted clawback"),
            SUPERVISOR_HEADERS,
        )
        validate_error(response, ERR_INVALID_STATE, 409)

        booking = world.get_booking(closed["id"])
        assert booking["status"] == "COMPLETED"
        assert booking["release_reason"] is None
        assert_decimal(booking["billable_hours_final"], 2.00)
        assert booking["final_cost_cents"] == 200000

        assert_hour_ledger(world.get_project(project["id"]), 0.00, 2.00, 38.00)
        assert world.ledger(project["id"])["billing_total_cents"] == 200000


class TestRecordingRequiresAnAcceptedSession:
    """The temporal precondition being met does not create the transition."""

    def test_recording_a_proposed_session_is_refused(self, world, api):
        """The clock is inside the window and the line count fits, yet record fails.

        PRD §3.5: "Recording is likewise a `SoundEditor` action, moving the session
        `CONFIRMED → RECORDED` while storing the supplied `lines_recorded`."

        Design: Corner/state_machines/adr_record_before_confirm_is_invalid_transition
        """
        world.set_clock("2026-09-01T00:00:00Z")
        talent = world.voice_talent(
            full_name="Rec Rhea", union_status="UNION", daily_cap_minutes=240,
            min_call_minutes=60,
        )
        project = world.locked_project(title="Record Guard")
        session = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T10:00:00Z",
            lines_scheduled=12,
        )
        assert session["status"] == "PROPOSED"
        world.set_clock("2026-09-14T09:30:00Z")

        response = api.record_adr_session(
            session["id"], f.adr_record_payload(lines_recorded=5), EDITOR_HEADERS
        )
        validate_error(response, ERR_INVALID_STATE, 409)

        unchanged = world.get_adr(session["id"])
        assert unchanged["status"] == "PROPOSED"
        assert unchanged["lines_recorded"] == 0
        assert world.ledger(project["id"])["adr_cost_cents"] == 0


class TestClientRequestCancellationIsTheFullInverse:
    """A cancelled call leaves the money, the daily cap and the overlap set."""

    def test_the_freed_day_and_window_take_a_replacement_session(self, world, api):
        """Cancelling the second of two calls drops 108000 to 54000 and reopens the slot.

        PRD §3.5: "A reason of `CLIENT_REQUEST` or `SCHEDULE_CONFLICT` moves the session to
        `CANCELLED`, which is permitted from `PROPOSED` and from `CONFIRMED`; the session's
        `cancellation_reason` is recorded and the session leaves both the talent overlap
        set and the talent daily-cap set."

        Design: Corner/state_machines/adr_cancel_client_request_leaves_both_overlap_and_cap_sets
        """
        world.set_clock("2026-09-01T00:00:00Z")
        talent = world.voice_talent(
            full_name="Cancel Cora", union_status="UNION", daily_cap_minutes=120,
            min_call_minutes=60,
        )
        project = world.locked_project(title="Cancellation")
        first = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T09:00:00Z",
            window_end_utc="2026-09-14T10:00:00Z",
            lines_scheduled=12,
        )
        world.confirm_adr(first["id"])
        second = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T11:00:00Z",
            lines_scheduled=12,
        )
        world.confirm_adr(second["id"])
        assert world.ledger(project["id"])["adr_cost_cents"] == 108000

        cancelled = world.cancel_adr(second["id"], cancellation_reason="CLIENT_REQUEST")
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "CLIENT_REQUEST"
        assert world.ledger(project["id"])["adr_cost_cents"] == 54000

        replacement = validate_success(
            api.create_adr_session(
                f.adr_session_payload(
                    project["id"],
                    talent["id"],
                    window_start_utc="2026-09-14T10:30:00Z",
                    window_end_utc="2026-09-14T11:30:00Z",
                    lines_scheduled=6,
                ),
                EDITOR_HEADERS,
            ),
            201,
        )
        assert replacement["status"] == "PROPOSED"
        assert_decimal(replacement["billable_minutes"], 60.00)

        assert world.get_adr(first["id"])["status"] == "CONFIRMED"
        _cancelled, meta = validate_paginated(
            api.list_adr_sessions(
                EDITOR_HEADERS, {"voice_talent_id": talent["id"], "status": "CANCELLED"}
            )
        )
        assert meta["total_count"] == 1

        ledger = world.ledger(project["id"])
        assert ledger["adr_cost_cents"] == 54000
        assert ledger["billing_total_cents"] == 54000


class TestCueRevisionRestalesTheConformedPackage:
    """Re-cutting one cue number replaces that cue and invalidates the conform."""

    def test_the_re_cut_cue_supersedes_its_predecessor(self, world, api):
        """1M1 at 150 seconds displaces 1M1 at 60 seconds and stales the reel.

        PRD §3.3: "When an incoming cue's `cue_number` matches that of an existing `ACTIVE`
        cue on the same package, that existing cue moves `ACTIVE → SUPERSEDED` — a terminal
        state — while the incoming cue is created `ACTIVE` in its place."

        Design: Corner/state_machines/cue_revision_supersedes_prior_cue_and_restales_the_package
        """
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.locked_project(title="Cue Revision")
        package = world.stem_package(project["id"])
        original = world.add_cue(package["id"], cue_number="1M1", duration_seconds=60)
        conformed = world.conform(package["id"])
        assert conformed["status"] == "CONFORMED"
        assert conformed["conform_fee_cents"] == 1500

        revision = world.add_cue(package["id"], cue_number="1M1", duration_seconds=150)

        assert revision["status"] == "ACTIVE"
        assert revision["duration_seconds"] == 150
        cues, _meta = validate_paginated(api.list_music_cues(package["id"], EDITOR_HEADERS))
        by_id = {cue["id"]: cue for cue in cues}
        assert by_id[original["id"]]["status"] == "SUPERSEDED"

        restaled = world.get_stem_package(package["id"])
        assert restaled["status"] == "STALE"
        assert restaled["stale_reason"] == "CUE_REVISED"
        assert restaled["conform_fee_cents"] == 1500

        project_after = world.get_project(project["id"])
        assert project_after["stale_stem_count"] == 1
        assert project_after["conformed_stem_count"] == 0
        assert project_after["posture"] == "RESTRICTED"
        assert project_after["picture_status"] == "LOCKED"

        active, active_meta = validate_paginated(
            api.list_music_cues(package["id"], EDITOR_HEADERS, {"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 1
        assert [cue["id"] for cue in active] == [revision["id"]]
        assert world.ledger(project["id"])["conform_fee_total_cents"] == 1500


class TestConformIsReEnterable:
    """A stale reel can be conformed again, and the second pass reprices it."""

    def test_the_second_pass_advances_the_round_and_reprices_the_current_cue_set(self, world):
        """Two cues and four stem minutes replace the pinned 3000-cent first pass.

        PRD §3.3: "It is permitted out of `DRAFT` and out of `STALE` — the transitions
        `DRAFT → CONFORMED` and `STALE → CONFORMED` — and both require that the package hold
        at least one `ACTIVE` music cue, that the owning project's `posture` is not
        `FROZEN`, and that the project's `pipeline_stage` is not `ARCHIVED`."

        Design: Corner/state_machines/reconform_after_stale_increments_conform_round_and_reprices
        """
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.locked_project(title="Re-conform")
        package = world.stem_package(project["id"])
        world.add_cue(package["id"], cue_number="1M1", duration_seconds=120)
        first_pass = world.conform(package["id"])
        assert first_pass["conform_round"] == 1
        assert first_pass["conform_fee_cents"] == 3000

        world.break_lock(project["id"], break_reason="recut for re-conform")
        relocked = world.lock_picture(project["id"])
        assert relocked["posture"] == "RESTRICTED"

        stale = world.get_stem_package(package["id"])
        assert stale["status"] == "STALE"
        assert stale["stale_reason"] == "PICTURE_LOCK_BROKEN"
        assert stale["conform_fee_cents"] == 3000

        world.add_cue(package["id"], cue_number="1M2", duration_seconds=120)
        second_pass = world.conform(package["id"])

        assert second_pass["status"] == "CONFORMED"
        assert second_pass["conform_round"] == 2
        assert second_pass["cue_count"] == 2
        assert_decimal(second_pass["total_stem_minutes"], 4.00)
        assert second_pass["conform_fee_cents"] == 6000
        assert second_pass["stale_reason"] is None

        project_after = world.get_project(project["id"])
        assert project_after["stale_stem_count"] == 0
        assert project_after["conformed_stem_count"] == 1
        assert project_after["posture"] == "OPEN"
        assert project_after["picture_lock_revision"] == 2
        assert world.ledger(project["id"])["billing_total_cents"] == 6000


class TestDeliverablePreparationSupersedesItsSibling:
    """A second cut for the same specification retires the first."""

    def test_the_first_deliverable_is_superseded_rather_than_invalidated(self, world, api):
        """The displaced cut keeps a null invalidation reason and a readable QC history.

        PRD §3.7: "Like booking creation, preparation supersedes a sibling: any existing
        non-terminal deliverable of the project for the **same** `platform_spec_id` — one in
        `PREPARED`, `QC_SUBMITTED`, `QC_REJECTED`, `REMEDIATION` or `QC_PASSED` — moves to
        the terminal `SUPERSEDED`, frozen out of the QC loop, though its accumulated QC
        reports remain readable."

        Design: Corner/state_machines/second_deliverable_for_same_spec_supersedes_the_first
        """
        environment = world.prepared_environment(
            spec={"spec_label": "Theatrical Supersede Spec"}, project={"title": "Supersession"}
        )
        project_id = environment["project"]["id"]
        first = environment["deliverable"]

        second = validate_success(
            api.create_deliverable(
                f.deliverable_payload(
                    world.project_version(project_id),
                    project_id,
                    environment["spec"]["id"],
                    environment["package"]["id"],
                    environment["booking"]["id"],
                ),
                SUPERVISOR_HEADERS,
            ),
            201,
        )

        displaced = world.get_deliverable(first["id"])
        assert displaced["status"] == "SUPERSEDED"
        assert displaced["invalidation_reason"] is None

        assert second["status"] == "PREPARED"
        assert second["remediation_round"] == 0
        assert second["qc_rejection_codes"] == []
        assert second["prepared_by_user_id"] == SUPERVISOR_USER_ID

        _all_cuts, all_meta = validate_paginated(
            api.list_deliverables(SUPERVISOR_HEADERS, {"project_id": project_id})
        )
        assert all_meta["total_count"] == 2
        prepared, prepared_meta = validate_paginated(
            api.list_deliverables(
                SUPERVISOR_HEADERS, {"project_id": project_id, "status": "PREPARED"}
            )
        )
        assert prepared_meta["total_count"] == 1
        assert [cut["id"] for cut in prepared] == [second["id"]]

        history, history_meta = validate_paginated(
            api.list_qc_reports(first["id"], SUPERVISOR_HEADERS)
        )
        assert history == []
        assert history_meta["total_count"] == 0
        assert world.get_booking(environment["booking"]["id"])["status"] == "COMPLETED"


class TestPictureLockHasNoTransitionFromLocked:
    """Declaring the lock twice does not advance the revision counter."""

    def test_a_second_lock_on_a_locked_project_is_refused(self, world, api):
        """The first lock's instant, revision and stage all survive the rejected repeat.

        PRD §3.2: "It is permitted from `NOT_LOCKED` and from `LOCK_BROKEN` — the two
        transitions `NOT_LOCKED → LOCKED` and `LOCK_BROKEN → LOCKED` — and in both cases the
        project's `pipeline_stage` must not be `ARCHIVED`."

        Design: Corner/state_machines/picture_lock_when_already_locked_is_invalid_state
        """
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.project(title="Double Lock")
        locked = world.lock_picture(project["id"], picture_lock_note="first lock")
        assert locked["picture_lock_revision"] == 1

        response = api.picture_lock(
            project["id"], f.picture_lock_payload(picture_lock_note="second lock"),
            SUPERVISOR_HEADERS,
        )
        validate_error(response, ERR_INVALID_STATE, 409)

        after = world.get_project(project["id"])
        assert after["picture_status"] == "LOCKED"
        assert after["picture_lock_revision"] == 1
        assert after["pipeline_stage"] == "EDITORIAL"
        assert_instants_equal(after["picture_locked_at_utc"], "2026-09-01T00:00:00Z")


class TestArchiveSealClosesTheAggregate:
    """Sealing bubbles the stem packages up and then locks the project out."""

    def test_the_seal_retires_the_stems_and_refuses_every_later_write(self, world, api):
        """The conformed reel becomes RETIRED, dropping its fee out of the billing total.

        PRD §3.8: "Every stem package that was `CONFORMED` then moves
        `CONFORMED → RETIRED`, which is terminal, and the project's `conformed_stem_count`
        is recomputed accordingly."

        Design: Corner/state_machines/archive_seal_retires_stems_and_locks_the_project_out
        """
        environment = world.delivered_environment(project={"title": "Archive Seal"})
        project_id = environment["project"]["id"]
        package_id = environment["package"]["id"]
        assert environment["deliverable"]["status"] == "DELIVERED"
        assert environment["project"]["pipeline_stage"] == "DELIVERED"

        sealed = world.archive(project_id, session_file_count=12)

        assert sealed["session_file_count"] == 12
        assert sealed["retention_years"] == 10
        assert sealed["stem_manifest_count"] == 1
        assert sealed["archived_stem_package_ids"] == [package_id]
        assert sealed["delivered_deliverable_count"] == 1
        assert_instants_equal(sealed["sealed_at_utc"], "2026-09-14T13:00:00Z")
        assert sealed["sealed_by_user_id"] == SUPERVISOR_USER_ID

        assert world.get_stem_package(package_id)["status"] == "RETIRED"
        project_after = world.get_project(project_id)
        assert project_after["pipeline_stage"] == "ARCHIVED"
        assert project_after["conformed_stem_count"] == 0

        ledger = world.ledger(project_id)
        assert ledger["conform_fee_total_cents"] == 0
        assert ledger["billing_total_cents"] == 360000

        validate_error(
            api.create_archive_package(
                project_id, f.archive_package_payload(session_file_count=12), SUPERVISOR_HEADERS
            ),
            ERR_PROJECT_ARCHIVED,
            409,
        )
        validate_error(
            api.create_stem_package(
                f.stem_package_payload(project_id, reel_label="R2"), EDITOR_HEADERS
            ),
            ERR_PROJECT_ARCHIVED,
            409,
        )

        packages, meta = validate_paginated(
            api.list_archive_packages(project_id, SUPERVISOR_HEADERS)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in packages] == [sealed["id"]]
