"""The gate order at the front door, the licensing gates, and page bounds."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_PAGINATION,
    ERR_LICENSE_RISK_TOO_HIGH,
    ERR_ROLE_NOT_PERMITTED,
    ERR_UNAUTHENTICATED,
    ERR_UNLICENSED_MATERIAL_PRESENT,
)
from test_helpers.assertions import assert_decimal
from test_helpers.constants import (
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    QC_VERDICT_PASS,
    ROLE_FACILITY_ADMIN,
    ROLE_POST_SUPERVISOR,
    UNLICENSED_REASON_TERRITORY_OUT_OF_SCOPE,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    EDITOR_HEADERS,
    SUPERVISOR_HEADERS,
    headers_blank_user_id,
)


class TestAuthenticationPrecedesRoleAndBothPrecedeTheBody:
    """An unusable identity is answered before anything else is examined."""

    def _one_unlocked_project(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        project = world.project(title="Gate Order")
        assert project["picture_status"] == "NOT_LOCKED"
        assert project["version"] == 1
        return project

    def test_a_blank_identity_answers_even_with_an_incomplete_body(self, world, api):
        """The role gate answers next, and only the permitted role writes anything.

        PRD §2.11: "**Rung 1** — `X-User-ID` absent or empty, on every endpoint except the
        two logical-clock capabilities: `ERR_UNAUTHENTICATED`, 401."

        Design: Corner/errors/error_auth_gate_precedes_the_role_gate_and_both_precede_the_body_check
        """
        project = self._one_unlocked_project(world)

        blank_identity = api.picture_lock(
            project["id"],
            f.picture_lock_payload(),
            headers_blank_user_id(ROLE_POST_SUPERVISOR),
        )
        validate_error(blank_identity, ERR_UNAUTHENTICATED, 401)

        wrong_role = api.picture_lock(
            project["id"], f.picture_lock_payload(), EDITOR_HEADERS
        )
        validate_error(wrong_role, ERR_ROLE_NOT_PERMITTED, 403)

        blank_with_bad_body = api.create_library_asset(
            {"asset_code": "AUTH-GATE-1"}, headers_blank_user_id(ROLE_FACILITY_ADMIN)
        )
        validate_error(blank_with_bad_body, ERR_UNAUTHENTICATED, 401)

        _assets, meta = validate_paginated(api.list_library_assets(ADMIN_HEADERS))
        assert meta["total_count"] == 0

        locked = validate_success(
            api.picture_lock(project["id"], f.picture_lock_payload(), SUPERVISOR_HEADERS),
            200,
        )
        assert locked["picture_status"] == "LOCKED"
        assert locked["version"] == 2
        assert world.get_project(project["id"])["pipeline_stage"] == "EDITORIAL"


class TestUnlicensedMaterialBlocksPreparation:
    """A territory-limited asset used worldwide poisons deliverable preparation."""

    def _conformed_package_carrying_an_unlicensed_usage(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        spec = world.platform_spec(
            platform="THEATRICAL", spec_label="Theatrical Unlicensed Gate Spec"
        )
        stage = world.mix_stage(display_name="Stage X1", hourly_rate_cents=120000)
        mixer = world.mixer(full_name="Territory Tom", certified_platforms=["THEATRICAL"])
        asset = world.library_asset(
            asset_code="DOMESTIC-ONLY-1", kind="MUSIC_LIBRARY",
            license_type="RIGHTS_MANAGED", territory_scope="DOMESTIC", fee_cents=4000,
        )
        project = world.locked_project(title="Unlicensed Gate")
        package = world.stem_package(project["id"])
        world.add_cue(package["id"], cue_number="1M1", duration_seconds=120, source="LIBRARY")
        usage = world.asset_usage(
            asset["id"], package["id"], usage_seconds=30, territory_declared="WORLDWIDE"
        )
        world.conform(package["id"])
        booking = world.completed_booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="FINAL_MIX",
            platform="THEATRICAL",
        )
        return spec, project, package, booking, usage

    def test_preparation_reports_the_licensing_code_rather_than_the_posture(self, world, api):
        """The conform went through under the restricted posture; preparation does not.

        PRD §3.7: "Preparation is additionally the **only** operation guarded by the
        standalone licensing check: if the project's `unlicensed_usage_count` is at least 1,
        preparation is rejected with `ERR_UNLICENSED_MATERIAL_PRESENT`."

        Design: Corner/errors/error_unlicensed_usage_blocks_deliverable_preparation
        """
        spec, project, package, booking, usage = (
            self._conformed_package_carrying_an_unlicensed_usage(world)
        )

        assert usage["clearance_status"] == "UNLICENSED"
        assert usage["unlicensed_reason"] == UNLICENSED_REASON_TERRITORY_OUT_OF_SCOPE
        assert usage["accrued_fee_cents"] == 0
        assert usage["cleared_at_utc"] is None
        assert world.get_stem_package(package["id"])["status"] == "CONFORMED"

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
        validate_error(refused, ERR_UNLICENSED_MATERIAL_PRESENT, 409)

        _deliverables, meta = validate_paginated(
            api.list_deliverables(SUPERVISOR_HEADERS, {"project_id": project["id"]})
        )
        assert meta["total_count"] == 0

        ledger = world.ledger(project["id"])
        assert ledger["unlicensed_usage_count"] == 1
        assert ledger["license_fee_accrued_cents"] == 0
        assert ledger["posture"] == "RESTRICTED"
        assert_decimal(ledger["license_risk_score_intake"], 0.00)
        assert_decimal(ledger["license_risk_score_audit"], 50.00)
        assert ledger["billing_total_cents"] == 363000


class TestLicenceRiskAtTheBlockThresholdStopsDelivery:
    """Three cleared rights-managed usages score 60.00 with the posture still open."""

    def _passed_deliverable_scoring_sixty(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        spec = world.platform_spec(
            platform="THEATRICAL", spec_label="Theatrical Risk Gate Spec"
        )
        stage = world.mix_stage(display_name="Stage X2", hourly_rate_cents=120000)
        mixer = world.mixer(full_name="Risk Rita", certified_platforms=["THEATRICAL"])
        assets = [
            world.library_asset(
                asset_code=f"RISK-RM-{index}", kind=kind,
                license_type="RIGHTS_MANAGED", territory_scope="WORLDWIDE", fee_cents=1000,
            )
            for index, kind in ((1, "MUSIC_LIBRARY"), (2, "SFX"), (3, "FOLEY"))
        ]
        project = world.locked_project(title="Risk Gate")
        package = world.stem_package(project["id"])
        world.add_cue(package["id"], cue_number="1M1", duration_seconds=120, source="LIBRARY")
        for asset, territory in zip(assets, ("WORLDWIDE", "WORLDWIDE", "DOMESTIC")):
            usage = world.asset_usage(
                asset["id"], package["id"], usage_seconds=30, territory_declared=territory
            )
            assert usage["clearance_status"] == "CLEARED"
            assert usage["accrued_fee_cents"] == 1000
        world.conform(package["id"])
        booking = world.completed_booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="FINAL_MIX",
            platform="THEATRICAL",
        )
        deliverable = world.deliverable(
            project["id"], spec["id"], package["id"], booking["id"]
        )
        world.qc_submit(
            deliverable["id"],
            measured_integrated_lufs=-24.10,
            measured_true_peak_dbtp=-3.00,
            me_stems_present=False,
        )
        report = world.qc_evaluate(deliverable["id"])
        assert report["verdict"] == QC_VERDICT_PASS
        return project, deliverable

    def test_the_licensing_gate_refuses_the_delivery_of_an_otherwise_passed_master(
        self, world, api
    ):
        """No unlicensed row and no frozen posture: only the audit score blocks the send.

        PRD §3.8: "The project's `license_risk_score_audit` must be **strictly below** the
        facility's risk block threshold of 50.00; a project at or above it is rejected with
        `ERR_LICENSE_RISK_TOO_HIGH`, which is why the audit variant of the licence score, and
        not the intake snapshot, is the gate that matters."

        Design: Corner/errors/error_license_risk_at_the_block_threshold_stops_delivery
        """
        project, deliverable = self._passed_deliverable_scoring_sixty(world)
        assert world.get_deliverable(deliverable["id"])["status"] == "QC_PASSED"

        refused = api.deliver_deliverable(
            deliverable["id"],
            f.deliver_payload(delivery_reference="DCP-RISK-1"),
            SUPERVISOR_HEADERS,
        )
        validate_error(refused, ERR_LICENSE_RISK_TOO_HIGH, 409)

        undelivered = world.get_deliverable(deliverable["id"])
        assert undelivered["status"] == "QC_PASSED"
        assert undelivered["delivery_reference"] is None
        assert undelivered["delivered_at_utc"] is None

        ledger = world.ledger(project["id"])
        assert_decimal(ledger["license_risk_score_audit"], 60.00)
        assert_decimal(ledger["license_risk_score_intake"], 60.00)
        assert ledger["posture"] == "OPEN"
        assert ledger["unlicensed_usage_count"] == 0
        assert ledger["license_fee_accrued_cents"] == 3000
        assert ledger["billing_total_cents"] == 366000
        assert ledger["pipeline_stage"] == "QC"


class TestPaginationBoundsAreRejectedBeforeAnyListing:
    """Out-of-range paging is an error, never a silently clamped page."""

    def _three_library_assets(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        first = world.library_asset(
            asset_code="PAGE-1", kind="SFX", license_type="ROYALTY_FREE",
            territory_scope="WORLDWIDE", fee_cents=100,
        )
        second = world.library_asset(
            asset_code="PAGE-2", kind="FOLEY", license_type="ROYALTY_FREE",
            territory_scope="WORLDWIDE", fee_cents=200,
        )
        third = world.library_asset(
            asset_code="PAGE-3", kind="MUSIC_LIBRARY", license_type="RIGHTS_MANAGED",
            territory_scope="WORLDWIDE", fee_cents=300,
        )
        return first, second, third

    def test_the_three_bad_windows_are_refused_and_the_good_ones_page_correctly(
        self, world, api
    ):
        """The status filter narrows the set before the page window is taken from it.

        PRD §2.3: "A `limit` that is not an integer or falls outside 1 through 100 inclusive,
        or an `offset` that is not an integer or is negative, is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/errors/error_pagination_bounds_are_rejected_before_any_listing_is_returned
        """
        _first, _second, third = self._three_library_assets(world)

        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            validate_error(
                api.list_library_assets(ADMIN_HEADERS, params), ERR_INVALID_PAGINATION, 400
            )

        first_page, first_meta = validate_paginated(
            api.list_library_assets(ADMIN_HEADERS, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        last_page, last_meta = validate_paginated(
            api.list_library_assets(ADMIN_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(last_page) == 1
        assert last_meta["total_count"] == 3
        assert last_meta["has_more"] is False

        defaulted, default_meta = validate_paginated(api.list_library_assets(ADMIN_HEADERS))
        assert len(defaulted) == 3
        assert default_meta["limit"] == DEFAULT_LIMIT
        assert default_meta["offset"] == DEFAULT_OFFSET
        assert default_meta["total_count"] == 3
        assert default_meta["has_more"] is False

        world.revoke_asset(third["id"], revocation_reason="paging fixture")

        filtered, filtered_meta = validate_paginated(
            api.list_library_assets(
                ADMIN_HEADERS, {"status": "ACTIVE", "limit": 1, "offset": 1}
            )
        )
        assert len(filtered) == 1
        assert filtered_meta["total_count"] == 2
        assert filtered_meta["has_more"] is False
