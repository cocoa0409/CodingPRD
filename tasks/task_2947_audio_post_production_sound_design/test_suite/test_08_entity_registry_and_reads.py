"""Entity creation echoes, defaults, system fields, reads, listings and references."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_PROJECT_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_STEM_PACKAGE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_created_at_descending,
    assert_decimal,
    assert_domain_instant,
    assert_envelope,
    assert_identity_fields,
    assert_immutable_record,
    assert_instants_equal,
)
from test_helpers.constants import UNKNOWN_ID
from test_helpers.test_users import (
    ADMIN_HEADERS,
    EDITOR_HEADERS,
    SUPERVISOR_HEADERS,
    mixer_headers,
)


class TestPlatformSpecCreation:
    """The specification create response is the whole record, not a stub."""

    def test_the_create_response_echoes_all_nine_declared_fields(self, world, api):
        """A 201 carries every specification field back under an object envelope.

        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/entities/platform_spec_create_returns_every_declared_field
        """
        world.set_clock("2026-09-01T00:00:00Z")
        response = api.create_platform_spec(
            f.platform_spec_payload(
                platform="STREAMING",
                spec_label="Streaming Stereo -16",
                target_lufs=-16.00,
                tolerance_lu=1.00,
                true_peak_max_dbtp=-1.00,
                channel_layout="STEREO",
                requires_me_stems=False,
                max_remediation_rounds=3,
                qc_turnaround_hours=12,
            ),
            ADMIN_HEADERS,
        )
        spec = validate_success(response, 201)

        assert spec["platform"] == "STREAMING"
        assert spec["spec_label"] == "Streaming Stereo -16"
        assert_decimal(spec["target_lufs"], -16.00)
        assert_decimal(spec["tolerance_lu"], 1.00)
        assert_decimal(spec["true_peak_max_dbtp"], -1.00)
        assert spec["channel_layout"] == "STEREO"
        assert spec["requires_me_stems"] is False
        assert spec["max_remediation_rounds"] == 3
        assert spec["qc_turnaround_hours"] == 12
        assert_immutable_record(spec)

        assert_envelope(response.json(), "object")


class TestProjectIntakeDefaults:
    """The two optional commercial terms have pinned defaults."""

    def test_omitting_both_terms_yields_standard_and_forty_hours(self, world, api):
        """The defaults are real values, not nulls, and they feed the hour ledger.

        PRD §3.2: "Two commercial terms are optional: `turnaround_class` is one of
        `STANDARD`, `EXPEDITED` or `RUSH` and defaults to `STANDARD`;
        `stage_hours_authorized` is the mix-stage hours the client has authorised, must be
        greater than zero, is carried to two decimal places, and defaults to **40.00**."

        Design: Corner/entities/project_create_applies_turnaround_and_stage_hour_defaults
        """
        world.set_clock("2026-09-01T00:00:00Z")
        payload = {
            "title": "Default Title",
            "client_name": "Distributor Co",
            "client_user_id": "client-user-1",
            "delivery_deadline_utc": "2026-12-31T00:00:00Z",
        }
        project = validate_success(api.create_project(payload, SUPERVISOR_HEADERS), 201)

        assert project["turnaround_class"] == "STANDARD"
        assert_decimal(project["stage_hours_authorized"], 40.00)
        assert_decimal(project["stage_hours_available"], 40.00)
        assert_decimal(project["stage_hours_reserved"], 0.00)
        assert_decimal(project["stage_hours_consumed"], 0.00)


class TestProjectSystemFields:
    """Every status and ledger field on a new project is server-stamped."""

    def test_a_new_project_is_not_locked_at_intake_and_open(self, world, api):
        """The client seeds none of the status dimensions or ledgers.

        PRD §3.2: "A newly created project sits in `picture_status` `NOT_LOCKED` with
        `picture_locked_at_utc` null and `picture_lock_revision` 0, in `pipeline_stage`
        `INTAKE`, with `posture` `OPEN`."

        Design: Corner/entities/project_system_fields_are_server_generated_on_create
        """
        world.set_clock("2026-09-01T00:00:00Z")
        project = validate_success(
            api.create_project(
                f.project_payload(
                    title="System Fields",
                    turnaround_class="EXPEDITED",
                    stage_hours_authorized=12.50,
                ),
                SUPERVISOR_HEADERS,
            ),
            201,
        )

        assert project["picture_status"] == "NOT_LOCKED"
        assert project["pipeline_stage"] == "INTAKE"
        assert project["posture"] == "OPEN"
        assert project["picture_lock_revision"] == 0
        assert project["picture_locked_at_utc"] is None
        assert project["version"] == 1
        assert_identity_fields(project)
        assert project["updated_at"] is not None
        assert project["billing_total_cents"] == 0
        assert project["license_fee_accrued_cents"] == 0
        assert_decimal(project["stage_hours_available"], 12.50)


class TestStemPackageComputedFields:
    """The conform totals are computed at conform time, never seeded."""

    def test_a_new_package_is_draft_with_every_total_at_zero(self, world, api):
        """A package opened on an unlocked project starts empty.

        PRD §3.3: "A new package lands in `DRAFT` with `conform_round` 0, `cue_count` 0,
        `total_stem_minutes` 0.00, `conform_fee_cents` 0, `conformed_at_utc` null and
        `stale_reason` null."

        Design: Corner/entities/stem_package_computed_fields_start_at_zero_on_create
        """
        project = world.project(title="Computed Fields")
        assert project["picture_status"] == "NOT_LOCKED"

        package = validate_success(
            api.create_stem_package(
                f.stem_package_payload(project["id"], stem_layout="ATMOS", includes_me_stems=True),
                EDITOR_HEADERS,
            ),
            201,
        )

        assert package["status"] == "DRAFT"
        assert package["cue_count"] == 0
        assert_decimal(package["total_stem_minutes"], 0.00)
        assert package["conform_fee_cents"] == 0
        assert package["conform_round"] == 0
        assert package["conformed_at_utc"] is None
        assert package["stale_reason"] is None
        assert package["version"] == 1
        assert package["includes_me_stems"] is True

        project_after = world.get_project(project["id"])
        assert project_after["conformed_stem_count"] == 0
        assert project_after["pipeline_stage"] == "INTAKE"


class TestMixStageRequiredFields:
    """A stage with no rate would silently price every booking at zero."""

    def test_omitting_the_hourly_rate_is_an_invalid_request(self, world, api):
        """The rate has no default, so the create must fail and store nothing.

        PRD §2.11: "**Rung 12** — a required input field is missing or null, of the wrong
        type, an unknown enum member, a negative quantity where a non-negative one is
        required, or a malformed ISO-8601 instant, on every endpoint that takes a request
        body: `ERR_INVALID_REQUEST`, 400."

        Design: Corner/entities/mix_stage_create_without_hourly_rate_is_invalid_request
        """
        world.set_clock("2026-09-01T00:00:00Z")
        response = api.create_mix_stage(
            {"room_code": "STAGE_X", "display_name": "Stage X", "supports_remote_review": True},
            ADMIN_HEADERS,
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["message"]

        accepted = validate_success(
            api.create_mix_stage(
                {
                    "room_code": "STAGE_X",
                    "display_name": "Stage X",
                    "supports_remote_review": True,
                    "hourly_rate_cents": 120000,
                },
                ADMIN_HEADERS,
            ),
            201,
        )
        assert accepted["hourly_rate_cents"] == 120000


class TestVoiceTalentEnumConstraint:
    """The union status enum is closed, so an unknown member cannot be stored."""

    def test_an_out_of_enum_union_status_is_rejected(self, world, api):
        """GUILD is not a union status and must not fall through to non-union pricing.

        PRD §3.1: "**Voice talent** is registered with `full_name` (1 to 120 characters)
        and `union_status`, either `UNION` or `NON_UNION`."

        Design: Corner/entities/voice_talent_create_rejects_unknown_union_status_enum
        """
        world.set_clock("2026-09-01T00:00:00Z")
        response = api.create_voice_talent(
            {
                "full_name": "Guild Gwen",
                "union_status": "GUILD",
                "daily_cap_minutes": 240,
                "min_call_minutes": 60,
            },
            ADMIN_HEADERS,
        )
        validate_error(response, ERR_INVALID_REQUEST, 400)

        legitimate = world.voice_talent(full_name="Union Ursula", union_status="UNION")
        assert legitimate["union_status"] == "UNION"


class TestUnknownProjectRead:
    """An unknown spine identifier is a typed 404, not an empty success."""

    def test_a_valid_but_unknown_project_id_is_a_project_not_found(self, world, api):
        """A real project exists alongside, so the 404 is not an empty table.

        PRD §2.6: "A request to a path of the form `/projects/{id}` or any path beginning
        `/projects/{id}/` whose identifier does not resolve to a project is rejected with
        `ERR_PROJECT_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/project_get_with_unknown_id_returns_project_not_found
        """
        real = world.project(title="Real Project")

        validate_error(
            api.get_project(UNKNOWN_ID, SUPERVISOR_HEADERS), ERR_PROJECT_NOT_FOUND, 404
        )

        still_there = validate_success(api.get_project(real["id"], SUPERVISOR_HEADERS), 200)
        assert still_there["id"] == real["id"]


class TestBookingReadBack:
    """A reserved booking reads back its window and its provisional price only."""

    def test_the_read_returns_the_stored_window_at_whole_second_precision(self, world, api):
        """The half-open window, 3.00 hours and 360000 cents, with no final figures yet.

        PRD §2.4: "Instants supplied by clients and instants emitted by the service in
        domain fields use ISO-8601 UTC at whole-second precision with a trailing `Z`, for
        example `2026-09-14T10:00:00Z`."

        Design: Corner/entities/mix_booking_retrieval_returns_stored_window_and_provisional_cost
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=120000, changeover_minutes=45)
        mixer = world.mixer(full_name="Read Rita", certified_platforms=["THEATRICAL"])
        project = world.project(title="Retrieval Project")
        created = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="THEATRICAL",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T13:00:00Z",
        )

        booking = validate_success(
            api.get_mix_booking(created["id"], mixer_headers(mixer["id"])), 200
        )

        assert booking["status"] == "RESERVED"
        assert_instants_equal(booking["window_start_utc"], "2026-09-14T10:00:00Z")
        assert_instants_equal(booking["window_end_utc"], "2026-09-14T13:00:00Z")
        assert_domain_instant(booking["window_start_utc"])
        assert_decimal(booking["reserved_hours"], 3.00)
        assert booking["provisional_cost_cents"] == 360000
        assert booking["final_cost_cents"] is None
        assert booking["actual_start_utc"] is None
        assert booking["client_signoff_at_utc"] is None


class TestLibraryAssetListing:
    """Paging reports the unpaginated count and a truthful has_more."""

    def test_two_pages_partition_three_assets_and_the_filter_narrows_them(self, world, api):
        """total_count stays 3 across both pages, and has_more flips on page two.

        PRD §2.3: "`total_count` is the number of records matching the request's filters
        before the page window is applied, and `has_more` is true when records matching
        the filters remain beyond the current window."

        Design: Corner/entities/library_asset_listing_paginates_with_total_count_and_has_more
        """
        world.set_clock("2026-09-01T00:00:00Z")
        one = world.library_asset(
            asset_code="PAGE-1", kind="SFX", license_type="ROYALTY_FREE", fee_cents=1000
        )
        two = world.library_asset(
            asset_code="PAGE-2", kind="FOLEY", license_type="ROYALTY_FREE", fee_cents=2000
        )
        three = world.library_asset(
            asset_code="PAGE-3", kind="MUSIC_LIBRARY", license_type="RIGHTS_MANAGED", fee_cents=3000
        )

        first_response = api.list_library_assets(ADMIN_HEADERS, {"limit": 2, "offset": 0})
        first_page, first_meta = validate_paginated(first_response)
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert_envelope(first_response.json(), "array")

        second_page, second_meta = validate_paginated(
            api.list_library_assets(ADMIN_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        seen = [record["id"] for record in first_page + second_page]
        assert sorted(seen) == sorted([one["id"], two["id"], three["id"]])
        assert_created_at_descending(first_page + second_page)

        filtered, filtered_meta = validate_paginated(
            api.list_library_assets(ADMIN_HEADERS, {"license_type": "RIGHTS_MANAGED"})
        )
        assert filtered_meta["total_count"] == 1
        assert [record["id"] for record in filtered] == [three["id"]]


class TestPlatformSpecImmutability:
    """Facility configuration carries no revision counter at all."""

    def test_the_specification_read_exposes_no_version_field(self, world, api):
        """Only id and created_at accompany the declared fields.

        PRD §2.5: "Three record types are deliberately immutable and therefore carry only
        `id` and `created_at` — they expose **no** `updated_at` and **no** `version` field
        at all, and no endpoint exists to update them."

        Design: Corner/entities/platform_spec_is_immutable_and_exposes_no_version
        """
        world.set_clock("2026-09-01T00:00:00Z")
        created = world.platform_spec(
            platform="BROADCAST",
            spec_label="ATSC A/85 5.1",
            target_lufs=-24.00,
            tolerance_lu=2.00,
            true_peak_max_dbtp=-2.00,
            channel_layout="5_1",
            requires_me_stems=False,
        )

        spec = validate_success(api.get_platform_spec(created["id"], SUPERVISOR_HEADERS), 200)

        assert "version" not in spec
        assert "updated_at" not in spec
        assert_immutable_record(spec)
        assert_decimal(spec["target_lufs"], -24.00)
        assert_decimal(spec["tolerance_lu"], 2.00)


class TestUnknownStemPackagePath:
    """The path segment is resolved before the stale-view token is examined."""

    def test_a_cue_under_an_unknown_package_is_a_stem_package_not_found(self, world, api):
        """The OCC token is genuine, yet the path 404 answers first.

        PRD §2.6: "URL path parameters are resolved strictly left to right, before any body
        content is examined."

        Design: Corner/entities/music_cue_create_under_unknown_stem_package_is_not_found
        """
        project = world.project(title="Parent Check")
        package = world.stem_package(project["id"], stem_layout="STEREO")
        genuine_version = package["version"]

        response = api.create_music_cue(
            UNKNOWN_ID,
            f.music_cue_payload(genuine_version, cue_number="1M1", duration_seconds=60),
            EDITOR_HEADERS,
        )
        validate_error(response, ERR_STEM_PACKAGE_NOT_FOUND, 404)

        cues, meta = validate_paginated(api.list_music_cues(package["id"], EDITOR_HEADERS))
        assert cues == []
        assert meta["total_count"] == 0

        unchanged = world.get_stem_package(package["id"])
        assert unchanged["version"] == genuine_version
        assert unchanged["cue_count"] == 0


class TestUnresolvedBodyForeignKey:
    """A body reference gets its own 404 code, distinct from the path family."""

    def test_an_unknown_library_asset_in_the_body_is_a_reference_not_found(self, world, api):
        """No half-formed usage row is left behind and no money accrues.

        PRD §2.6: "Those are checked in the order the endpoint declares its input fields,
        and the first one that does not resolve to an existing record is reported as
        `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/asset_usage_body_foreign_key_unknown_asset_is_reference_not_found
        """
        project = world.project(title="FK Check")
        package = world.stem_package(project["id"], stem_layout="STEREO")

        response = api.create_asset_usage(
            f.asset_usage_payload(
                UNKNOWN_ID, package["id"], usage_seconds=60, territory_declared="WORLDWIDE"
            ),
            EDITOR_HEADERS,
        )
        validate_error(response, ERR_REFERENCE_NOT_FOUND, 404)

        usages, meta = validate_paginated(
            api.list_asset_usages(EDITOR_HEADERS, {"stem_package_id": package["id"]})
        )
        assert usages == []
        assert meta["total_count"] == 0
        assert world.get_project(project["id"])["license_fee_accrued_cents"] == 0


class TestAssetUsageIsARealJunction:
    """One asset reaches two reels and one reel carries two assets."""

    def test_both_directions_of_the_junction_are_listable(self, world, api):
        """The two foreign-key filters each return their own two rows.

        PRD §3.4: "Cutting a library asset into a reel creates an **asset usage** — a
        junction record joining one library asset to one stem package."

        Design: Corner/entities/asset_usage_junction_supports_many_to_many_in_both_directions
        """
        world.set_clock("2026-09-01T00:00:00Z")
        asset_a = world.library_asset(
            asset_code="JUNC-A", kind="SFX", license_type="ROYALTY_FREE", fee_cents=5000
        )
        asset_b = world.library_asset(
            asset_code="JUNC-B", kind="FOLEY", license_type="ROYALTY_FREE", fee_cents=7000
        )
        project_one = world.project(title="Junction One")
        project_two = world.project(title="Junction Two")
        package_one = world.stem_package(project_one["id"], stem_layout="STEREO")
        package_two = world.stem_package(project_two["id"], stem_layout="STEREO")

        usage_a1 = world.asset_usage(asset_a["id"], package_one["id"], usage_seconds=30)
        usage_a2 = world.asset_usage(asset_a["id"], package_two["id"], usage_seconds=30)
        usage_b1 = world.asset_usage(asset_b["id"], package_one["id"], usage_seconds=30)

        by_asset, _asset_meta = validate_paginated(
            api.list_asset_usages(EDITOR_HEADERS, {"library_asset_id": asset_a["id"]})
        )
        assert {record["id"] for record in by_asset} == {usage_a1["id"], usage_a2["id"]}

        by_package_one, _one_meta = validate_paginated(
            api.list_asset_usages(EDITOR_HEADERS, {"stem_package_id": package_one["id"]})
        )
        assert {record["id"] for record in by_package_one} == {usage_a1["id"], usage_b1["id"]}

        by_package_two, _two_meta = validate_paginated(
            api.list_asset_usages(EDITOR_HEADERS, {"stem_package_id": package_two["id"]})
        )
        assert [record["id"] for record in by_package_two] == [usage_a2["id"]]

        assert usage_a1["accrued_fee_cents"] == 5000
        assert usage_b1["accrued_fee_cents"] == 7000
        assert world.get_project(project_one["id"])["license_fee_accrued_cents"] == 12000
        assert world.get_project(project_two["id"])["license_fee_accrued_cents"] == 5000
