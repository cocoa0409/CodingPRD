"""Who may act: peer roles, record ownership and segregated duties."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_NOT_ASSIGNED_MIXER,
    ERR_NOT_PROJECT_CLIENT,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import assert_decimal, assert_hour_ledger, assert_instants_equal
from test_helpers.constants import QC_ONE_USER_ID, QC_TWO_USER_ID, QC_VERDICT_PASS
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLIENT_HEADERS,
    EDITOR_HEADERS,
    OTHER_CLIENT_HEADERS,
    QC_ONE_HEADERS,
    QC_TWO_HEADERS,
    SUPERVISOR_HEADERS,
    mixer_headers,
)


class TestBookingActionsBelongToTheAssignedMixer:
    """Two mixers, one booking: the role is shared and the record is not."""

    def _booking_assigned_to_the_first_mixer(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(display_name="Stage R1", hourly_rate_cents=100000)
        owner = world.mixer(full_name="Owner Olga", certified_platforms=["STREAMING"])
        interloper = world.mixer(
            full_name="Interloper Ian", certified_platforms=["STREAMING"]
        )
        project = world.project(title="Mixer Ownership")
        booking = world.booking(
            project["id"],
            stage["id"],
            owner["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
        )
        return owner, interloper, project, booking

    def test_the_other_mixer_is_refused_all_three_actions_the_owner_performs(
        self, world, api
    ):
        """Each refusal leaves the booking exactly where the owner's last call left it.

        PRD §2.11: "**Rung 10** — the acting `Mixer`'s `X-User-ID` does not equal the
        booking's `mixer_id`, on booking confirmation, booking start and booking completion:
        `ERR_NOT_ASSIGNED_MIXER`, 403."

        Design: Corner/rbac/rbac_booking_actions_are_reserved_to_the_assigned_mixer
        """
        owner, interloper, project, booking = self._booking_assigned_to_the_first_mixer(world)
        stranger = mixer_headers(interloper["id"])

        validate_error(
            api.confirm_mix_booking(booking["id"], {}, stranger),
            ERR_NOT_ASSIGNED_MIXER,
            403,
        )
        assert world.get_booking(booking["id"])["status"] == "RESERVED"
        assert world.confirm_booking(booking["id"], owner["id"])["status"] == "CONFIRMED"

        world.set_clock("2026-09-14T10:30:00Z")
        validate_error(
            api.start_mix_booking(booking["id"], {}, stranger), ERR_NOT_ASSIGNED_MIXER, 403
        )
        assert world.get_booking(booking["id"])["status"] == "CONFIRMED"
        assert world.start_booking(booking["id"], owner["id"])["status"] == "IN_PROGRESS"

        world.set_clock("2026-09-14T12:00:00Z")
        validate_error(
            api.complete_mix_booking(booking["id"], {}, stranger),
            ERR_NOT_ASSIGNED_MIXER,
            403,
        )
        assert world.get_booking(booking["id"])["status"] == "IN_PROGRESS"

        closed = world.complete_booking(booking["id"], owner["id"])
        assert closed["status"] == "COMPLETED"
        assert_decimal(closed["billable_hours_final"], 2.00)
        assert closed["final_cost_cents"] == 200000

        assert_hour_ledger(world.get_project(project["id"]), 0.00, 2.00, 38.00)


class TestExclusiveOperationsAcrossPeerRoles:
    """The three production roles are peers, and one endpoint is genuinely shared."""

    def _project_with_an_editor_owned_package(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(display_name="Stage R2", hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Peer Pete", certified_platforms=["STREAMING"])
        project = world.project(title="Peer Roles")
        package = world.stem_package(project["id"])
        world.add_cue(
            package["id"], cue_number="1M1", duration_seconds=120,
            source="COMPOSER_ORIGINAL",
        )
        return stage, mixer, project, package

    def test_three_cross_role_attempts_are_refused_and_the_shared_create_is_not(
        self, world, api
    ):
        """The supervisor may open a stem package but may never conform one.

        PRD §2.1: "If `X-User-Role` is absent, is not one of the six role names defined
        below, or names a role that the target endpoint does not authorise, the request is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/rbac_exclusive_operations_are_denied_across_peer_roles
        """
        stage, mixer, project, package = self._project_with_an_editor_owned_package(world)

        editor_booking = api.create_mix_booking(
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
            EDITOR_HEADERS,
        )
        validate_error(editor_booking, ERR_ROLE_NOT_PERMITTED, 403)

        supervisor_conform = api.conform_stem_package(package["id"], {}, SUPERVISOR_HEADERS)
        validate_error(supervisor_conform, ERR_ROLE_NOT_PERMITTED, 403)

        qc_lock = api.picture_lock(project["id"], f.picture_lock_payload(), QC_ONE_HEADERS)
        validate_error(qc_lock, ERR_ROLE_NOT_PERMITTED, 403)
        assert world.get_project(project["id"])["picture_status"] == "NOT_LOCKED"

        shared = validate_success(
            api.create_stem_package(
                f.stem_package_payload(project["id"], reel_label="R2"), SUPERVISOR_HEADERS
            ),
            201,
        )
        assert shared["status"] == "DRAFT"
        assert shared["reel_label"] == "R2"

        conformed = world.conform(package["id"])
        assert conformed["status"] == "CONFORMED"
        assert conformed["conform_fee_cents"] == 3000

        _bookings, meta = validate_paginated(
            api.list_mix_bookings(SUPERVISOR_HEADERS, {"project_id": project["id"]})
        )
        assert meta["total_count"] == 0


class TestLedgerReadIsDoublyGated:
    """Money needs a permitted role first and then the right client identity."""

    def _project_with_one_conformed_reel(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.project(title="Ledger Access")
        package = world.stem_package(project["id"])
        world.add_cue(
            package["id"], cue_number="1M1", duration_seconds=120,
            source="COMPOSER_ORIGINAL",
        )
        world.conform(package["id"])
        return project

    def test_two_roles_are_refused_by_role_a_stranger_by_ownership_and_three_agree(
        self, world, api
    ):
        """The three permitted readers see one identical set of figures.

        PRD §2.11: "**Rung 11** — the acting `ClientReviewer`'s `X-User-ID` does not equal
        the `client_user_id` of the project (reached directly, or through the booking for a
        sign-off), on remote-review sign-off, single-project read and project-ledger read:
        `ERR_NOT_PROJECT_CLIENT`, 403."

        Design: Corner/rbac/rbac_ledger_read_needs_both_a_permitted_role_and_client_ownership
        """
        project = self._project_with_one_conformed_reel(world)

        validate_error(
            api.get_project_ledger(project["id"], EDITOR_HEADERS), ERR_ROLE_NOT_PERMITTED, 403
        )
        validate_error(
            api.get_project_ledger(project["id"], QC_ONE_HEADERS), ERR_ROLE_NOT_PERMITTED, 403
        )
        validate_error(
            api.get_project_ledger(project["id"], OTHER_CLIENT_HEADERS),
            ERR_NOT_PROJECT_CLIENT,
            403,
        )

        client_view = validate_success(
            api.get_project_ledger(project["id"], CLIENT_HEADERS), 200
        )
        assert client_view["billing_total_cents"] == 3000
        assert client_view["conform_fee_total_cents"] == 3000

        supervisor_view = validate_success(
            api.get_project_ledger(project["id"], SUPERVISOR_HEADERS), 200
        )
        admin_view = validate_success(
            api.get_project_ledger(project["id"], ADMIN_HEADERS), 200
        )
        assert supervisor_view["billing_total_cents"] == 3000
        assert admin_view["billing_total_cents"] == 3000

        for view in (client_view, supervisor_view, admin_view):
            assert view["posture"] == "OPEN"
            assert view["conformed_stem_count"] == 1
            assert_decimal(view["stage_hours_available"], 40.00)


class TestOneOperatorCannotMeasureAndJudgeTheSameRound:
    """Both actors hold the QC role, so only the identity comparison can refuse."""

    def _submitted_round_from_the_first_operator(self, world):
        environment = world.prepared_environment(
            platform="THEATRICAL",
            spec={"spec_label": "Theatrical SoD Spec"},
            stage={"display_name": "Stage R4", "hourly_rate_cents": 100000},
            mixer={"full_name": "Duty Dov"},
            project={"title": "Segregation"},
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
        )
        submitted = world.qc_submit(
            environment["deliverable"]["id"],
            submitter=QC_ONE_USER_ID,
            measured_integrated_lufs=-24.10,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )
        assert submitted["status"] == "QC_SUBMITTED"
        return environment["deliverable"]["id"]

    def test_the_submitter_is_refused_and_the_second_operator_closes_the_round(
        self, world, api
    ):
        """One report, two distinct user ids, and nothing appended by the refusal.

        PRD §3.7: "**Evaluation** takes no request body, is permitted only out of
        `QC_SUBMITTED`, and requires that the acting `X-User-ID` differ from the
        `submitted_by_user_id` of the round being evaluated — one operator may not both
        measure and judge a round, and doing so is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/rbac_same_operator_cannot_submit_and_evaluate_one_qc_round
        """
        deliverable_id = self._submitted_round_from_the_first_operator(world)

        own_judgement = api.qc_evaluate(deliverable_id, {}, QC_ONE_HEADERS)
        validate_error(own_judgement, ERR_SEGREGATION_OF_DUTIES, 403)
        assert world.get_deliverable(deliverable_id)["status"] == "QC_SUBMITTED"

        report = validate_success(
            api.qc_evaluate(deliverable_id, {}, QC_TWO_HEADERS), 201
        )
        assert report["verdict"] == QC_VERDICT_PASS
        assert report["round"] == 0
        assert report["submitted_by_user_id"] == QC_ONE_USER_ID
        assert report["evaluated_by_user_id"] == QC_TWO_USER_ID
        assert_decimal(report["deviation_lu"], 0.10)
        assert report["rejection_codes"] == []
        assert_instants_equal(report["evaluated_at_utc"], "2026-09-14T12:00:00Z")

        assert world.get_deliverable(deliverable_id)["status"] == "QC_PASSED"

        _reports, meta = validate_paginated(
            api.list_qc_reports(deliverable_id, SUPERVISOR_HEADERS)
        )
        assert meta["total_count"] == 1
