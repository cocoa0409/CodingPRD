"""Action endpoints, computed reads and the not-found family they each own."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ADR_SESSION_NOT_FOUND,
    ERR_ALREADY_SIGNED_OFF,
    ERR_CLIENT_SIGNOFF_REQUIRED,
    ERR_DELIVERABLE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_LIBRARY_ASSET_NOT_FOUND,
    ERR_MIX_BOOKING_NOT_FOUND,
    ERR_NOT_PROJECT_CLIENT,
    ERR_REMEDIATION_LIMIT_EXCEEDED,
)
from test_helpers.assertions import (
    assert_billing_chain,
    assert_decimal,
    assert_error_envelope_meta,
    assert_hour_ledger,
    assert_instants_equal,
)
from test_helpers.constants import (
    CODE_LOUDNESS_OUT_OF_TOLERANCE,
    OTHER_CLIENT_USER_ID,
    QC_VERDICT_FAIL,
    UNKNOWN_ID,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLIENT_HEADERS,
    EDITOR_HEADERS,
    SUPERVISOR_HEADERS,
    client_headers,
    mixer_headers,
)


class TestClientSignoffIsOwnedByTheProjectClient:
    """One sign-off, from one user, before a remote session can be closed."""

    def _remote_session_in_progress(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(display_name="Stage E1", hourly_rate_cents=100000)
        mixer = world.mixer(full_name="Signoff Sid", certified_platforms=["STREAMING"])
        project = world.project(title="Remote Review")
        booking = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
            client_attendance="REMOTE",
        )
        world.confirm_booking(booking["id"], mixer["id"])
        world.set_clock("2026-09-14T10:00:00Z")
        world.start_booking(booking["id"], mixer["id"])
        world.set_clock("2026-09-14T12:00:00Z")
        return mixer, project, booking

    def test_a_stranger_cannot_sign_off_and_the_client_cannot_sign_off_twice(
        self, world, api
    ):
        """Only after the real client signs off does the mixer get to close the room.

        PRD §3.6: "Despite looking idempotent it is not: a second sign-off on a booking
        whose `client_signoff_at_utc` is already set is rejected with
        `ERR_ALREADY_SIGNED_OFF`."

        Design: Corner/endpoints/client_signoff_is_a_conditional_action_owned_by_the_project_client
        """
        mixer, project, booking = self._remote_session_in_progress(world)

        premature = api.complete_mix_booking(booking["id"], {}, mixer_headers(mixer["id"]))
        validate_error(premature, ERR_CLIENT_SIGNOFF_REQUIRED, 409)
        assert world.get_booking(booking["id"])["status"] == "IN_PROGRESS"

        stranger = api.client_signoff_mix_booking(
            booking["id"], {}, client_headers(OTHER_CLIENT_USER_ID)
        )
        validate_error(stranger, ERR_NOT_PROJECT_CLIENT, 403)
        assert world.get_booking(booking["id"])["client_signoff_at_utc"] is None

        signed = world.client_signoff(booking["id"], CLIENT_HEADERS)
        assert_instants_equal(signed["client_signoff_at_utc"], "2026-09-14T12:00:00Z")
        assert signed["status"] == "IN_PROGRESS"

        repeat = api.client_signoff_mix_booking(booking["id"], {}, CLIENT_HEADERS)
        validate_error(repeat, ERR_ALREADY_SIGNED_OFF, 409)

        closed = world.complete_booking(booking["id"], mixer["id"])
        assert closed["status"] == "COMPLETED"
        assert_decimal(closed["billable_hours_final"], 2.00)
        assert closed["final_cost_cents"] == 200000

        assert_hour_ledger(world.get_project(project["id"]), 0.00, 2.00, 38.00)


class TestProjectLedgerComputedRead:
    """One expedited project touching every term of the nine-step roll-up."""

    def _project_with_every_ledger_term(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(display_name="Stage E2", hourly_rate_cents=120000)
        mixer = world.mixer(full_name="Ledger Lena", certified_platforms=["STREAMING"])
        talent = world.voice_talent(
            full_name="Union Uma", union_status="UNION", daily_cap_minutes=240,
            min_call_minutes=60,
        )
        asset = world.library_asset(
            asset_code="LEDGER-RM", kind="MUSIC_LIBRARY", license_type="RIGHTS_MANAGED",
            territory_scope="WORLDWIDE", fee_cents=10000,
        )
        project = world.locked_project(title="Full Ledger", turnaround_class="EXPEDITED")
        package = world.stem_package(project["id"])
        world.add_cue(package["id"], cue_number="1M1", duration_seconds=120, source="LIBRARY")
        world.asset_usage(asset["id"], package["id"], usage_seconds=30)
        world.conform(package["id"])
        session = world.adr_session(
            project["id"],
            talent["id"],
            window_start_utc="2026-09-14T08:00:00Z",
            window_end_utc="2026-09-14T08:45:00Z",
            lines_scheduled=9,
        )
        world.confirm_adr(session["id"])
        world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="STREAMING",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T11:00:00Z",
        )
        return project

    def test_the_read_reports_every_term_and_the_surcharge_on_the_post_discount_base(
        self, world
    ):
        """367000 pre-discount, no tier discount, 36700 expedited surcharge, 403700 total.

        PRD §3.8: "Step eight, `rush_surcharge_cents` is `discounted_base_cents` multiplied
        by the surcharge percentage for the project's `turnaround_class` — 0.00 for
        `STANDARD`, 0.10 for `EXPEDITED` and 0.20 for `RUSH` — rounded half up to whole
        cents; the surcharge is computed on the **post-discount** base."

        Design: Corner/endpoints/project_ledger_computed_read_matches_the_pinned_step_order
        """
        project = self._project_with_every_ledger_term(world)
        ledger = world.ledger(project["id"])

        assert_decimal(ledger["stage_hours_authorized"], 40.00)
        assert_hour_ledger(ledger, 2.00, 0.00, 38.00)

        assert ledger["stage_cost_subtotal_cents"] == 300000
        assert ledger["adr_cost_cents"] == 54000
        assert ledger["conform_fee_total_cents"] == 3000
        assert ledger["license_fee_accrued_cents"] == 10000

        assert ledger["pre_discount_total_cents"] == 367000
        assert ledger["volume_discount_cents"] == 0
        assert ledger["discounted_base_cents"] == 367000
        assert ledger["rush_surcharge_cents"] == 36700
        assert ledger["billing_total_cents"] == 403700
        assert_billing_chain(ledger)

        assert_decimal(ledger["license_risk_score_intake"], 20.00)
        assert_decimal(ledger["license_risk_score_audit"], 20.00)
        assert ledger["unlicensed_usage_count"] == 0
        assert ledger["stale_stem_count"] == 0
        assert ledger["conformed_stem_count"] == 1
        assert ledger["posture"] == "OPEN"
        assert ledger["picture_status"] == "LOCKED"
        assert ledger["pipeline_stage"] == "PREMIX"

        assert world.get_project(project["id"])["billing_total_cents"] == (
            ledger["billing_total_cents"]
        )


class TestRevokingAnUnusedAsset:
    """The degenerate cascade still flips the row and bumps its version once."""

    def _one_unused_asset(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        asset = world.library_asset(
            asset_code="UNUSED-1", kind="FOLEY", license_type="ROYALTY_FREE",
            territory_scope="WORLDWIDE", fee_cents=2500,
        )
        assert asset["status"] == "ACTIVE"
        assert asset["version"] == 1
        return asset

    def test_the_second_revoke_is_refused_and_an_unknown_asset_is_not_found(self, world, api):
        """One revocation, one stored reason, one version increment and no third state.

        PRD §3.4: "The asset must currently be `ACTIVE`; the transition
        `ACTIVE → REVOKED` stores the reason and increases the asset's own `version` by 1."

        Design: Corner/endpoints/library_asset_revoke_action_on_an_unused_asset
        """
        asset = self._one_unused_asset(world)

        revoked = validate_success(
            api.revoke_library_asset(
                asset["id"],
                f.revoke_payload(revocation_reason="licensor withdrew the cue"),
                ADMIN_HEADERS,
            ),
            200,
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revocation_reason"] == "licensor withdrew the cue"
        assert revoked["version"] == 2

        second = api.revoke_library_asset(
            asset["id"], f.revoke_payload(revocation_reason="second attempt"), ADMIN_HEADERS
        )
        validate_error(second, ERR_INVALID_STATE, 409)
        unchanged = world.get_asset(asset["id"])
        assert unchanged["revocation_reason"] == "licensor withdrew the cue"
        assert unchanged["version"] == 2

        missing = api.revoke_library_asset(
            UNKNOWN_ID, f.revoke_payload(revocation_reason="ghost asset"), ADMIN_HEADERS
        )
        validate_error(missing, ERR_LIBRARY_ASSET_NOT_FOUND, 404)

        _revoked_rows, revoked_meta = validate_paginated(
            api.list_library_assets(ADMIN_HEADERS, {"status": "REVOKED"})
        )
        assert revoked_meta["total_count"] == 1
        _active_rows, active_meta = validate_paginated(
            api.list_library_assets(ADMIN_HEADERS, {"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 0


class TestEachPathPrefixOwnsItsNotFoundCode:
    """The same unresolvable identifier answers differently per spine."""

    def test_three_spines_report_three_distinct_not_found_codes(self, world, api):
        """No generic reference error stands in for a path that does not resolve.

        PRD §2.11: "**Rung 6** — the mix-booking path parameter does not resolve, on every
        path of the form `/mix-bookings/{id}/...`: `ERR_MIX_BOOKING_NOT_FOUND`, 404."

        Design: Corner/endpoints/action_path_not_found_family_for_bookings_sessions_and_deliverables
        """
        world.set_clock("2026-09-01T00:00:00Z")

        deliverable_read = api.get_deliverable(UNKNOWN_ID, SUPERVISOR_HEADERS)
        validate_error(deliverable_read, ERR_DELIVERABLE_NOT_FOUND, 404)
        booking_read = api.get_mix_booking(UNKNOWN_ID, SUPERVISOR_HEADERS)
        validate_error(booking_read, ERR_MIX_BOOKING_NOT_FOUND, 404)
        session_read = api.get_adr_session(UNKNOWN_ID, EDITOR_HEADERS)
        validate_error(session_read, ERR_ADR_SESSION_NOT_FOUND, 404)

        for response in (deliverable_read, booking_read, session_read):
            body = response.json()
            assert isinstance(body["data"]["message"], str)
            assert body["data"]["message"].strip() != ""
            assert_error_envelope_meta(body)


class TestRemediationStopsAtTheSpecLimit:
    """A specification allowing one remediation allows exactly one."""

    def _rejected_deliverable_under_a_one_round_spec(self, world):
        environment = world.prepared_environment(
            platform="STREAMING",
            spec={
                "spec_label": "Streaming One Remediation Spec",
                "target_lufs": -24.00,
                "tolerance_lu": 0.50,
                "true_peak_max_dbtp": -2.00,
                "channel_layout": "STEREO",
                "max_remediation_rounds": 1,
            },
            stage={"display_name": "Stage E5", "hourly_rate_cents": 100000},
            mixer={"full_name": "Round Rob"},
            project={"title": "Remediation Limit"},
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T12:00:00Z",
        )
        return environment

    def _fail_one_round(self, world, deliverable_id):
        world.qc_submit(
            deliverable_id,
            measured_integrated_lufs=-25.00,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )
        report = world.qc_evaluate(deliverable_id)
        assert report["verdict"] == QC_VERDICT_FAIL
        assert report["rejection_codes"] == [CODE_LOUDNESS_OUT_OF_TOLERANCE]
        assert_decimal(report["deviation_lu"], 1.00)
        return report

    def test_the_second_remediation_is_refused_and_both_rounds_stay_on_file(self, world, api):
        """Round zero remediates to round one; round one has nowhere left to go.

        PRD §2.11: "**Rung 27** — the deliverable's `remediation_round` is already at or
        above the governing specification's `max_remediation_rounds`, on remediation:
        `ERR_REMEDIATION_LIMIT_EXCEEDED`, 409."

        Design: Corner/endpoints/remediation_rounds_advance_until_the_spec_limit_is_reached
        """
        environment = self._rejected_deliverable_under_a_one_round_spec(world)
        deliverable_id = environment["deliverable"]["id"]
        project_id = environment["project"]["id"]

        first_report = self._fail_one_round(world, deliverable_id)
        assert first_report["round"] == 0

        reopened = world.remediate(deliverable_id, remediation_note="re-trim the dialogue bus")
        assert reopened["status"] == "REMEDIATION"
        assert reopened["remediation_round"] == 1

        second_report = self._fail_one_round(world, deliverable_id)
        assert second_report["round"] == 1

        exhausted = api.remediate_deliverable(
            deliverable_id, f.remediate_payload(remediation_note="one more pass"),
            SUPERVISOR_HEADERS,
        )
        validate_error(exhausted, ERR_REMEDIATION_LIMIT_EXCEEDED, 409)

        stuck = world.get_deliverable(deliverable_id)
        assert stuck["status"] == "QC_REJECTED"
        assert stuck["remediation_round"] == 1

        reports, meta = validate_paginated(
            api.list_qc_reports(deliverable_id, SUPERVISOR_HEADERS)
        )
        assert meta["total_count"] == 2
        assert [report["round"] for report in reports] == [0, 1]

        assert world.ledger(project_id)["billing_total_cents"] == 203000
