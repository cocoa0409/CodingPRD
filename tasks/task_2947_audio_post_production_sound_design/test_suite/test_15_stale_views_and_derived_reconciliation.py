"""Optimistic concurrency on the two parents, and derived totals over siblings."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_STALE_PROJECT_VERSION,
    ERR_STALE_STEM_PACKAGE_VERSION,
)
from test_helpers.assertions import assert_decimal, assert_hour_ledger
from test_helpers.constants import SUPERVISOR_USER_ID
from test_helpers.test_users import EDITOR_HEADERS, SUPERVISOR_HEADERS


class TestStaleProjectVersionOnBookingCreation:
    """The version read at intake is spent by the picture lock."""

    def _project_locked_after_its_version_was_read(self, world, api):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(display_name="Stage C1", hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Occ Otto", certified_platforms=["THEATRICAL"])
        project = world.project(title="Occ Booking")
        assert project["version"] == 1
        locked = validate_success(
            api.picture_lock(project["id"], f.picture_lock_payload(), SUPERVISOR_HEADERS), 200
        )
        assert locked["version"] == 2
        return stage, mixer, project

    def _create(self, api, version, project, stage, mixer):
        return api.create_mix_booking(
            f.mix_booking_payload(
                version,
                project["id"],
                stage["id"],
                mixer["id"],
                booking_type="FINAL_MIX",
                platform="THEATRICAL",
                window_start_utc="2026-09-14T10:00:00Z",
                window_end_utc="2026-09-14T12:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        )

    def test_the_version_from_before_the_lock_is_refused_and_the_re_read_one_reserves(
        self, world, api
    ):
        """The refused create neither reserves an hour nor moves the version itself.

        PRD §2.7: "If that value does not equal the project's current `version`, the request
        is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_project_version_blocks_booking_creation
        """
        stage, mixer, project = self._project_locked_after_its_version_was_read(world, api)

        stale = self._create(api, 1, project, stage, mixer)
        validate_error(stale, ERR_STALE_PROJECT_VERSION, 412)

        after_rejection = world.get_project(project["id"])
        assert after_rejection["version"] == 2
        assert_hour_ledger(after_rejection, 0.00, 0.00, 40.00)

        booking = validate_success(self._create(api, 2, project, stage, mixer), 201)
        assert booking["status"] == "RESERVED"
        assert_decimal(booking["reserved_hours"], 2.00)
        assert booking["provisional_cost_cents"] == 200000

        assert world.get_project(project["id"])["version"] == 3


class TestStaleProjectVersionOnDeliverableCreation:
    """A request valid in every other respect is still refused on its version."""

    def _environment_ready_for_preparation(self, world):
        return world.prepared_environment(
            platform="THEATRICAL",
            spec={"spec_label": "Theatrical Occ Spec"},
            stage={"display_name": "Stage C2", "hourly_rate_cents": 100000},
            mixer={"full_name": "Occ Ada"},
            project={"title": "Occ Deliverable"},
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
            prepare=False,
        )

    def test_the_decremented_version_is_refused_before_any_reference_rule_runs(
        self, world, api
    ):
        """The observed version then prepares the deliverable the stale one could not.

        PRD §2.7: "A deliverable-creation request against `POST /deliverables` must likewise
        carry `expected_project_version` matching the target project's current `version`, and
        a mismatch is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_project_version_blocks_deliverable_creation
        """
        environment = self._environment_ready_for_preparation(world)
        project_id = environment["project"]["id"]
        observed = world.project_version(project_id)

        def create(version):
            return api.create_deliverable(
                f.deliverable_payload(
                    version,
                    project_id,
                    environment["spec"]["id"],
                    environment["package"]["id"],
                    environment["booking"]["id"],
                ),
                SUPERVISOR_HEADERS,
            )

        validate_error(create(observed - 1), ERR_STALE_PROJECT_VERSION, 412)

        _rows, meta = validate_paginated(
            api.list_deliverables(SUPERVISOR_HEADERS, {"project_id": project_id})
        )
        assert meta["total_count"] == 0
        assert world.project_version(project_id) == observed

        prepared = validate_success(create(observed), 201)
        assert prepared["status"] == "PREPARED"
        assert prepared["remediation_round"] == 0
        assert prepared["prepared_by_user_id"] == SUPERVISOR_USER_ID
        assert world.project_version(project_id) == observed + 1


class TestStaleStemPackageVersionOnCueCreation:
    """The package's own counter is the guarded parent for cue writes."""

    def _draft_package_at_version_one(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.project(title="Occ Cues")
        package = world.stem_package(project["id"])
        assert package["version"] == 1
        return package

    def _add(self, api, package_id, version, cue_number):
        return api.create_music_cue(
            package_id,
            f.music_cue_payload(version, cue_number=cue_number, duration_seconds=90),
            EDITOR_HEADERS,
        )

    def test_the_version_consumed_by_the_first_cue_cannot_admit_the_second(self, world, api):
        """A different cue number supersedes nothing, so both cues end up active.

        PRD §2.7: "A music-cue-creation request against
        `POST /stem-packages/{id}/music-cues` must carry `expected_stem_package_version`
        matching the current `version` of the stem package named in the path."

        Design: Corner/complexity_layers/occ_stale_stem_package_version_blocks_cue_creation
        """
        package = self._draft_package_at_version_one(world)

        first = validate_success(self._add(api, package["id"], 1, "1M1"), 201)
        assert world.get_stem_package(package["id"])["version"] == 2

        stale = self._add(api, package["id"], 1, "1M2")
        validate_error(stale, ERR_STALE_STEM_PACKAGE_VERSION, 412)

        _cues, meta = validate_paginated(
            api.list_music_cues(package["id"], EDITOR_HEADERS)
        )
        assert meta["total_count"] == 1
        assert world.get_stem_package(package["id"])["version"] == 2

        second = validate_success(self._add(api, package["id"], 2, "1M2"), 201)
        assert second["cue_number"] == "1M2"
        assert second["status"] == "ACTIVE"
        assert world.get_stem_package(package["id"])["version"] == 3

        active, active_meta = validate_paginated(
            api.list_music_cues(package["id"], EDITOR_HEADERS, {"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 2
        assert {cue["id"] for cue in active} == {first["id"], second["id"]}


class TestDerivedCountsReconcileAcrossSiblingPackages:
    """Project counts aggregate over every package, not over the last write."""

    def _two_packages_each_with_one_two_minute_cue(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.project(title="Sibling Counts")
        package_a = world.stem_package(project["id"], reel_label="R1")
        world.add_cue(
            package_a["id"], cue_number="1M1", duration_seconds=120,
            source="COMPOSER_ORIGINAL",
        )
        package_b = world.stem_package(project["id"], reel_label="R2")
        original_cue = world.add_cue(
            package_b["id"], cue_number="2M1", duration_seconds=120,
            source="COMPOSER_ORIGINAL",
        )
        return project, package_a, package_b, original_cue

    def test_a_revision_in_one_sibling_moves_the_counts_and_a_reconform_restores_them(
        self, world, api
    ):
        """The accrued 3000 is never clawed back; the reconform reprices to 6000 on top.

        PRD §3.3: "A re-conform out of `STALE` decrements the stale count and increments the
        conformed count, and its posture recomputation can lift a project from `RESTRICTED`
        back to `OPEN` — but only once `stale_stem_count` has reached 0 **and**
        `unlicensed_usage_count` is also 0."

        Design: Corner/complexity_layers/derived_counts_reconcile_across_two_sibling_stem_packages
        """
        project, package_a, package_b, original_cue = (
            self._two_packages_each_with_one_two_minute_cue(world)
        )

        assert world.conform(package_a["id"])["conform_fee_cents"] == 3000
        assert world.conform(package_b["id"])["conform_fee_cents"] == 3000

        after_both = world.ledger(project["id"])
        assert after_both["conform_fee_total_cents"] == 6000
        assert after_both["conformed_stem_count"] == 2
        assert after_both["stale_stem_count"] == 0
        assert after_both["posture"] == "OPEN"

        revised_cue = world.add_cue(
            package_b["id"], cue_number="2M1", duration_seconds=240,
            source="COMPOSER_ORIGINAL",
        )
        stale_package = world.get_stem_package(package_b["id"])
        assert stale_package["status"] == "STALE"
        assert stale_package["stale_reason"] == "CUE_REVISED"
        assert stale_package["conform_fee_cents"] == 3000

        after_revision = world.ledger(project["id"])
        assert after_revision["conformed_stem_count"] == 1
        assert after_revision["stale_stem_count"] == 1
        assert after_revision["posture"] == "RESTRICTED"
        assert after_revision["conform_fee_total_cents"] == 6000

        assert revised_cue["status"] == "ACTIVE"
        active_cues, active_meta = validate_paginated(
            api.list_music_cues(package_b["id"], EDITOR_HEADERS, {"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 1
        assert [cue["id"] for cue in active_cues] == [revised_cue["id"]]
        superseded, superseded_meta = validate_paginated(
            api.list_music_cues(package_b["id"], EDITOR_HEADERS, {"status": "SUPERSEDED"})
        )
        assert superseded_meta["total_count"] == 1
        assert [cue["id"] for cue in superseded] == [original_cue["id"]]

        reconformed = world.conform(package_b["id"])
        assert reconformed["conform_fee_cents"] == 6000
        assert reconformed["conform_round"] == 2
        assert_decimal(reconformed["total_stem_minutes"], 4.00)

        final = world.ledger(project["id"])
        assert final["conform_fee_total_cents"] == 9000
        assert final["conformed_stem_count"] == 2
        assert final["stale_stem_count"] == 0
        assert final["posture"] == "OPEN"
        assert final["billing_total_cents"] == 9000

        untouched = world.get_stem_package(package_a["id"])
        assert untouched["status"] == "CONFORMED"
        assert untouched["conform_round"] == 1
        assert untouched["conform_fee_cents"] == 3000


class TestEveryDerivedFigureIsVisibleInTheWritingResponse:
    """No read-after-write lag: the write itself already carries the recomputation."""

    def _project_with_one_cue_and_a_stage(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(display_name="Stage M1", hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Immediate Ida", certified_platforms=["STREAMING"])
        project = world.project(title="Immediate Consistency")
        package = world.stem_package(project["id"])
        world.add_cue(
            package["id"], cue_number="1M1", duration_seconds=120,
            source="COMPOSER_ORIGINAL",
        )
        return stage, mixer, project, package

    def test_the_conform_and_booking_responses_agree_with_the_ledger_read_that_follows(
        self, world, api
    ):
        """A merely reserved booking is already money in the subtotal the client reads.

        PRD §3.8: "Step one, `stage_cost_subtotal_cents` is the sum over the project's
        bookings of `final_cost_cents` for each booking whose `status` is `COMPLETED` and of
        `provisional_cost_cents` for each booking whose `status` is `RESERVED`, `CONFIRMED` or
        `IN_PROGRESS`; bookings in `RELEASED` and `SUPERSEDED` contribute 0."

        Design: Corner/consistency_model/immediate_visibility_of_every_derived_field_in_the_writing_response
        """
        stage, mixer, project, package = self._project_with_one_cue_and_a_stage(world)

        conform_response = api.conform_stem_package(package["id"], {}, EDITOR_HEADERS)
        conformed = validate_success(conform_response, 200)
        assert conformed["status"] == "CONFORMED"
        assert conformed["conform_fee_cents"] == 3000
        conform_body = conform_response.json()
        assert conform_body["response_type"] == "object"
        assert conform_body["meta"]["api_request_id"].startswith("req_")

        after_conform = world.ledger(project["id"])
        assert after_conform["conform_fee_total_cents"] == 3000
        assert after_conform["conformed_stem_count"] == 1

        booking_response = api.create_mix_booking(
            f.mix_booking_payload(
                world.project_version(project["id"]),
                project["id"],
                stage["id"],
                mixer["id"],
                booking_type="PREMIX",
                platform="STREAMING",
                window_start_utc="2026-09-14T10:00:00Z",
                window_end_utc="2026-09-14T12:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        )
        booking = validate_success(booking_response, 201)
        assert_decimal(booking["reserved_hours"], 2.00)
        assert booking["provisional_cost_cents"] == 200000
        booking_body = booking_response.json()
        assert booking_body["response_type"] == "object"
        assert booking_body["meta"]["api_request_id"].startswith("req_")

        after_booking = world.ledger(project["id"])
        assert_hour_ledger(after_booking, 2.00, 0.00, 38.00)
        assert after_booking["stage_cost_subtotal_cents"] == 200000
        assert after_booking["billing_total_cents"] == 203000
        assert world.get_project(project["id"])["billing_total_cents"] == 203000
