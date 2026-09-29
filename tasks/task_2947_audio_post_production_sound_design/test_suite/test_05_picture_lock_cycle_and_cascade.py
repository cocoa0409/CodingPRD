"""Breaking and re-declaring picture lock, and the four-hop invalidation chain."""

from test_helpers.assertions import assert_decimal, assert_hour_ledger


class TestBreakPictureLockCascade:
    """One destructive action reaching a stem package, a deliverable and a booking."""

    def _committed_project(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        spec = world.platform_spec(platform="THEATRICAL")
        stage = world.mix_stage(hourly_rate_cents=120000)
        mixer = world.mixer(certified_platforms=["THEATRICAL"])
        project = world.locked_project()
        package = world.conformed_package(project["id"], cue_durations=(120, 120))
        booking = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PRINTMASTER",
            platform="THEATRICAL",
        )
        world.confirm_booking(booking["id"], mixer["id"])
        deliverable = world.deliverable(project["id"], spec["id"], package["id"], booking["id"])
        before = world.ledger(project["id"])
        assert before["billing_total_cents"] == 366000
        return {
            "project": world.get_project(project["id"]),
            "package": package,
            "booking": booking,
            "deliverable": deliverable,
        }

    def test_the_break_stales_the_package_and_invalidates_the_deliverable(self, world):
        """Hops one to three: the project freezes, the stems go stale, the cut dies.

        PRD §2.10: "Second — **because** that stem package became stale — every
        deliverable whose `stem_package_id` is that package and whose `status` is one of
        `PREPARED`, `QC_SUBMITTED`, `QC_REJECTED`, `REMEDIATION` or `QC_PASSED` moves to
        `INVALIDATED` with `invalidation_reason` set to `STEM_STALE`."

        Design: Difficulty/transitive_cascade/break_picture_lock_depth_four_stem_deliverable_booking_ledger
        """
        environment = self._committed_project(world)
        world.break_lock(environment["project"]["id"], break_reason="reel 1 recut")

        project = world.get_project(environment["project"]["id"])
        assert project["picture_status"] == "LOCK_BROKEN"
        assert project["posture"] == "FROZEN"

        package = world.get_stem_package(environment["package"]["id"])
        assert package["status"] == "STALE"
        assert package["stale_reason"] == "PICTURE_LOCK_BROKEN"

        deliverable = world.get_deliverable(environment["deliverable"]["id"])
        assert deliverable["status"] == "INVALIDATED"
        assert deliverable["invalidation_reason"] == "STEM_STALE"

        assert project["stale_stem_count"] == 1
        assert project["conformed_stem_count"] == 0

    def test_the_released_booking_returns_its_hours_and_collapses_the_billing_total(self, world):
        """Hop four: the confirmed room is freed and 366000 falls back to 6000.

        PRD §2.10: "Each such release returns the booking's hours to the pool, so the
        project's `stage_hours_reserved`, `stage_hours_available`,
        `stage_cost_subtotal_cents` and `billing_total_cents` are recomputed."

        Design: Difficulty/transitive_cascade/break_picture_lock_depth_four_stem_deliverable_booking_ledger
        """
        environment = self._committed_project(world)
        stage_before = environment["project"]["pipeline_stage"]

        world.break_lock(environment["project"]["id"], break_reason="reel 1 recut")

        booking = world.get_booking(environment["booking"]["id"])
        assert booking["status"] == "RELEASED"
        assert booking["release_reason"] == "DELIVERABLE_INVALIDATED"
        assert booking["final_cost_cents"] is None

        project = world.get_project(environment["project"]["id"])
        assert_hour_ledger(project, 0.00, 0.00, 40.00)
        assert project["pipeline_stage"] == stage_before

        ledger = world.ledger(environment["project"]["id"])
        assert ledger["stage_cost_subtotal_cents"] == 0
        assert ledger["conform_fee_total_cents"] == 6000
        assert ledger["billing_total_cents"] == 6000


class TestPictureLockIsCyclicButThePipelineIsNot:
    """The two project status dimensions move independently."""

    def test_breaking_the_lock_at_qc_freezes_without_regressing_the_pipeline(self, world):
        """A project at QC stays at QC while its picture status and posture change.

        PRD §3.2: "What breaking the lock explicitly does **not** do is move
        `pipeline_stage`: a project three quarters of the way to delivery does not fall
        back to editorial because a new cut arrived."

        Design: Difficulty/non_linear_state_machine/picture_lock_break_and_relock_leaves_pipeline_stage_at_qc
        """
        environment = world.prepared_environment(prepare=False, cue_durations=(120,))
        project_id = environment["project"]["id"]
        assert environment["project"]["pipeline_stage"] == "QC"
        assert environment["project"]["picture_lock_revision"] == 1

        broken = world.break_lock(project_id, break_reason="new cut delivered by editorial")

        assert broken["picture_status"] == "LOCK_BROKEN"
        assert broken["posture"] == "FROZEN"
        assert broken["pipeline_stage"] == "QC"

        package = world.get_stem_package(environment["package"]["id"])
        assert package["status"] == "STALE"
        assert package["stale_reason"] == "PICTURE_LOCK_BROKEN"

    def test_the_relock_returns_to_locked_but_only_relaxes_to_restricted(self, world):
        """The stale package survives the cycle, so posture stops short of OPEN.

        PRD §3.2: "A re-lock out of `LOCK_BROKEN` leaves `pipeline_stage` exactly where it
        is, and its posture recomputation is the interesting one — a re-locked project
        leaves `FROZEN` behind but only reaches `OPEN` if it is otherwise clean, becoming
        `RESTRICTED` instead when `stale_stem_count` is at least 1 or
        `unlicensed_usage_count` is at least 1."

        Design: Difficulty/non_linear_state_machine/picture_lock_break_and_relock_leaves_pipeline_stage_at_qc
        """
        environment = world.prepared_environment(prepare=False, cue_durations=(120,))
        project_id = environment["project"]["id"]
        world.break_lock(project_id, break_reason="new cut delivered by editorial")

        relocked = world.lock_picture(project_id, picture_lock_note="cut v2 locked")

        assert relocked["picture_status"] == "LOCKED"
        assert relocked["picture_lock_revision"] == 2
        assert relocked["pipeline_stage"] == "QC"
        assert relocked["posture"] == "RESTRICTED"
        assert relocked["stale_stem_count"] == 1
        assert relocked["conformed_stem_count"] == 0

        package = world.get_stem_package(environment["package"]["id"])
        assert package["status"] == "STALE"
        assert_decimal(
            world.get_project(project_id)["stage_hours_consumed"], 3.00
        )
