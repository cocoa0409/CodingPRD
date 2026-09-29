"""Row shapes at creation and at read time.

The declared initial state of a resident account, a law-enforcement agency and a
camera; the optional inputs whose defaults the server has to supply itself; the
fields a client may not write; the read-back and pagination surface of the camera
collection; and the four refusals that guard identity, required fields, body
foreign keys and declared value sets.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    ANONYMOUS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    make_resident_headers,
)

# A well-formed identifier that names no row in the portal.
_UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"

# An instant one hour past the pinned scenario clock.
_LATER_CLOCK = "2026-08-12T01:00:00Z"


def _seed_one_owner_three_cameras(
    api: ApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """One resident owning three cameras, plus a second resident owning one.

    The three cameras sit at distinct grid positions so no co-location rule is
    engaged, and the fourth belongs to a different account entirely.
    """
    owner = fixtures.register_resident(
        api,
        display_name="Pager One",
        email="pager1@example.test",
        home_x_m=0,
        home_y_m=10,
        alert_radius_m=0,
    )
    other = fixtures.register_resident(
        api,
        display_name="Pager Two",
        email="pager2@example.test",
        home_x_m=900,
        home_y_m=900,
        alert_radius_m=0,
    )
    owned_ids: List[str] = []
    for label, y in (("Cam A", 10), ("Cam B", 20), ("Cam C", 30)):
        device = fixtures.register_device(
            api, owner["id"], label=label, grid_x_m=0, grid_y_m=y
        )
        owned_ids.append(device["id"])
    fixtures.register_device(
        api, other["id"], label="Other Cam", grid_x_m=900, grid_y_m=900
    )
    return owner, other, owned_ids


def test_resident_registration_returns_declared_initial_state(
    api: ApiClient, clock: str
) -> None:
    """A registered resident account starts at every declared initial value and version 1.

    PRD: "The new account is created with `status` `ACTIVE`, `data_sharing_opt_out` false, `fatigue_state` `NORMAL`, `post_privilege_state` `UNRESTRICTED`, and every counter at zero — `notifications_sent_today`, `accuracy_strike_count`, `discrimination_strike_count`, `total_strike_score`, `lifetime_shared_footage_seconds`, `retained_footage_seconds` and `purged_footage_seconds`."
    PRD: "Most resources carry the full set of common properties: `id`, `created_at` (the ISO 8601 UTC instant of creation, with three fractional digits), `updated_at` (same format, refreshed on every mutation), and `version`, an integer that begins at 1 when the row is created and increments by exactly 1 on every mutation of that row."
    PRD: "Endpoints that create a new resource respond with HTTP 201; endpoints that modify, transition or read an existing resource respond with HTTP 200."

    Design: Corner/entities/resident_creation_returns_all_declared_fields
    """
    response = api.create_resident(
        f.resident_payload(
            display_name="Mina Okafor",
            email="mina@example.test",
            home_x_m=120,
            home_y_m=-40,
            alert_radius_m=900,
            notification_budget_per_day=8,
            notification_mute_enabled=False,
        ),
        ANONYMOUS_HEADERS,
    )
    resident = validate_success(response, 201)

    assertions.assert_subset(
        resident,
        {
            "status": k.RESIDENT_STATUS_ACTIVE,
            "data_sharing_opt_out": False,
            "fatigue_state": k.FATIGUE_NORMAL,
            "post_privilege_state": k.PRIVILEGE_UNRESTRICTED,
        },
    )
    assertions.assert_zero_counters(
        resident,
        "notifications_sent_today",
        "accuracy_strike_count",
        "discrimination_strike_count",
        "total_strike_score",
        "lifetime_shared_footage_seconds",
        "retained_footage_seconds",
        "purged_footage_seconds",
    )
    assertions.assert_footage_ledger(resident, lifetime=0, retained=0, purged=0)
    assertions.assert_strike_ladder(resident)
    assertions.assert_mutable_common_fields(resident, version=1)
    assertions.assert_created_equals_updated(resident)


def test_resident_registration_stores_every_supplied_input(
    api: ApiClient, clock: str
) -> None:
    """The four required inputs and the three optional preferences are stored as given.

    PRD: "Registration supplies a `display_name` of one to eighty characters, an `email` that must be unique across every resident account in the portal, and the home position on the planning grid as `home_x_m` and `home_y_m`."
    PRD: "Three notification preferences may be set at registration or left to their defaults: `alert_radius_m`, the radius in metres around the resident's home within which they wish to hear about neighbourhood posts, defaulting to 800 and constrained to between 0 and 5000 inclusive, where 0 means the resident wants no proximity post alerts whatsoever; `notification_budget_per_day`, the base number of notifications the resident is willing to receive per UTC calendar day, defaulting to 6 and constrained to between 0 and 100 inclusive, where 0 means every dispatch to them is suppressed for budget; and `notification_mute_enabled`, a hard mute that defaults to false."

    Design: Corner/entities/resident_creation_returns_all_declared_fields
    """
    created = validate_success(
        api.create_resident(
            f.resident_payload(
                display_name="Mina Okafor",
                email="mina@example.test",
                home_x_m=120,
                home_y_m=-40,
                alert_radius_m=900,
                notification_budget_per_day=8,
                notification_mute_enabled=False,
            ),
            ANONYMOUS_HEADERS,
        ),
        201,
    )
    supplied = {
        "display_name": "Mina Okafor",
        "email": "mina@example.test",
        "home_x_m": 120,
        "home_y_m": -40,
        "alert_radius_m": 900,
        "notification_budget_per_day": 8,
        "notification_mute_enabled": False,
    }
    assertions.assert_subset(created, supplied)

    stored = fixtures.read_resident(api, created["id"])
    assert stored["id"] == created["id"], "The read-back row is the row just created"
    assertions.assert_subset(stored, supplied)
    assertions.assert_mutable_common_fields(stored, version=1)
    assertions.assert_created_equals_updated(stored)
    assertions.assert_instant(stored["created_at"], created["created_at"], "created_at")


def test_resident_registration_applies_the_three_declared_defaults(
    api: ApiClient, clock: str
) -> None:
    """Omitting the three optional preferences yields 800, 6 and false, not 0 or null.

    PRD: "Three notification preferences may be set at registration or left to their defaults: `alert_radius_m`, the radius in metres around the resident's home within which they wish to hear about neighbourhood posts, defaulting to 800 and constrained to between 0 and 5000 inclusive, where 0 means the resident wants no proximity post alerts whatsoever; `notification_budget_per_day`, the base number of notifications the resident is willing to receive per UTC calendar day, defaulting to 6 and constrained to between 0 and 100 inclusive, where 0 means every dispatch to them is suppressed for budget; and `notification_mute_enabled`, a hard mute that defaults to false."

    Design: Corner/entities/resident_creation_applies_declared_defaults
    """
    created = validate_success(
        api.create_resident(
            f.resident_payload(
                display_name="Default Dana",
                email="dana@example.test",
                home_x_m=0,
                home_y_m=0,
            ),
            ANONYMOUS_HEADERS,
        ),
        201,
    )
    defaults = {
        "alert_radius_m": k.DEFAULT_ALERT_RADIUS_M,
        "notification_budget_per_day": k.DEFAULT_NOTIFICATION_BUDGET_PER_DAY,
        "notification_mute_enabled": False,
    }
    assertions.assert_subset(created, defaults)
    assertions.assert_subset(created, {"status": k.RESIDENT_STATUS_ACTIVE})
    assertions.assert_mutable_common_fields(created, version=1)
    assertions.assert_created_equals_updated(created)

    stored = fixtures.read_resident(api, created["id"])
    assertions.assert_subset(stored, defaults)


def test_agency_registration_applies_the_five_policy_defaults(
    api: ApiClient, clock: str
) -> None:
    """An agency registered with only its name and jurisdiction carries the five declared defaults.

    PRD: "The same payload may optionally pre-configure the five knobs the agency will later be measured against: `min_device_threshold`, the base number of eligible cameras it insists on before a canvass may be locked, which defaults to 5 and must be between 1 and 50 inclusive; `max_open_requests`, the ceiling on how many of its requests may be canvassing at one moment, which defaults to 3 and must be between 1 and 25 inclusive; `period_request_quota`, the total number of requests it may ever submit through the portal, which defaults to 20 and must be between 1 and 500 inclusive; `post_share_retention_days`, the agency-side retention window applied to every clip it receives, which defaults to 30 and must be between 1 and 365 inclusive; and `justification_min_chars`, the minimum length its own officers must write, which defaults to 80 and must be between 20 and 2000 inclusive."
    PRD: "A `PlatformAdmin` first registers an applicant by supplying its legal `name` (one to one hundred sixty characters) and the `jurisdiction_code` it files transparency returns under (one to thirty-two characters)."

    Design: Corner/entities/agency_creation_applies_configuration_defaults
    """
    created = validate_success(
        api.create_agency(
            f.agency_payload(name="Default Sheriff Office", jurisdiction_code="DS-001"),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )
    declared_defaults = {
        "min_device_threshold": k.DEFAULT_MIN_DEVICE_THRESHOLD,
        "max_open_requests": k.DEFAULT_MAX_OPEN_REQUESTS,
        "period_request_quota": k.DEFAULT_PERIOD_REQUEST_QUOTA,
        "post_share_retention_days": k.DEFAULT_POST_SHARE_RETENTION_DAYS,
        "justification_min_chars": k.DEFAULT_JUSTIFICATION_MIN_CHARS,
    }
    assertions.assert_subset(created, declared_defaults)
    assertions.assert_subset(
        created, {"name": "Default Sheriff Office", "jurisdiction_code": "DS-001"}
    )
    assertions.assert_mutable_common_fields(created, version=1)

    stored = fixtures.read_agency(api, created["id"])
    assertions.assert_subset(stored, declared_defaults)


def test_agency_registration_lands_under_review_with_empty_counters(
    api: ApiClient, clock: str
) -> None:
    """A freshly registered applicant is PENDING_REVIEW at version 1 with no request history.

    PRD: "A newly registered applicant lands in `PENDING_REVIEW` with `version` 1, `open_request_count` and `requests_submitted_count` both at 0, and `latest_report_id` null."
    PRD: "The applicant is inert until the platform records its onboarding decision."

    Design: Corner/entities/agency_creation_applies_configuration_defaults
    """
    created = validate_success(
        api.create_agency(
            f.agency_payload(name="Default Sheriff Office", jurisdiction_code="DS-001"),
            PLATFORM_ADMIN_HEADERS,
        ),
        201,
    )
    assertions.assert_subset(created, {"status": k.AGENCY_STATUS_PENDING_REVIEW})
    assertions.assert_zero_counters(
        created, "open_request_count", "requests_submitted_count"
    )
    assertions.assert_nulls(created, "latest_report_id")
    assertions.assert_mutable_common_fields(created, version=1)
    assertions.assert_created_equals_updated(created)

    stored = fixtures.read_agency(api, created["id"])
    assertions.assert_subset(
        stored,
        {
            "status": k.AGENCY_STATUS_PENDING_REVIEW,
            "open_request_count": 0,
            "requests_submitted_count": 0,
            "latest_report_id": None,
            "version": 1,
        },
    )


def test_resident_registration_ignores_client_supplied_system_fields(
    api: ApiClient, clock: str
) -> None:
    """A create body naming status, opt-out and the daily counter is accepted and its values ignored.

    PRD: "Registration supplies a `display_name` of one to eighty characters, an `email` that must be unique across every resident account in the portal, and the home position on the planning grid as `home_x_m` and `home_y_m`."
    PRD: "The new account is created with `status` `ACTIVE`, `data_sharing_opt_out` false, `fatigue_state` `NORMAL`, `post_privilege_state` `UNRESTRICTED`, and every counter at zero — `notifications_sent_today`, `accuracy_strike_count`, `discrimination_strike_count`, `total_strike_score`, `lifetime_shared_footage_seconds`, `retained_footage_seconds` and `purged_footage_seconds`."
    PRD: "Every other write is guarded by state preconditions alone, and supplying a version to an operation that does not ask for one has no effect."

    Design: Corner/entities/resident_creation_system_field_input_ignored
    """
    created = validate_success(
        api.create_resident(
            f.resident_payload(
                display_name="Sneaky Sam",
                email="sam@example.test",
                home_x_m=10,
                home_y_m=10,
                status=k.RESIDENT_STATUS_DEACTIVATED,
                data_sharing_opt_out=True,
                notifications_sent_today=99,
            ),
            ANONYMOUS_HEADERS,
        ),
        201,
    )
    honoured = {
        "status": k.RESIDENT_STATUS_ACTIVE,
        "data_sharing_opt_out": False,
        "notifications_sent_today": 0,
        "fatigue_state": k.FATIGUE_NORMAL,
        "post_privilege_state": k.PRIVILEGE_UNRESTRICTED,
        "home_x_m": 10,
        "home_y_m": 10,
    }
    assertions.assert_subset(created, honoured)
    assertions.assert_mutable_common_fields(created, version=1)
    assertions.assert_created_equals_updated(created)

    stored = fixtures.read_resident(api, created["id"])
    assertions.assert_subset(stored, honoured)
    assertions.assert_mutable_common_fields(stored, version=1)


def test_device_read_back_returns_exactly_the_row_that_was_registered(
    api: ApiClient, clock: str
) -> None:
    """A camera read by identifier reports the stored label, position and retention window.

    PRD: "Registering a camera names its `owner_resident_id`, an owner-supplied `label` of one to eighty characters, and its grid position as `grid_x_m` and `grid_y_m`."
    PRD: "A new camera is created with `status` `ACTIVE` — the three postures are `ACTIVE`, `OFFLINE` and `DECOMMISSIONED` — and with `solicitations_received_count` and `pending_solicitation_count` both at 0."
    PRD: "It takes one of `NONE`, `OWNER_MANUAL` or `OPT_OUT` and starts at `NONE`."

    Design: Corner/entities/device_retrieval_returns_stored_row
    """
    owner = fixtures.register_resident(
        api,
        display_name="Owner One",
        email="owner1@example.test",
        home_x_m=0,
        home_y_m=10,
        alert_radius_m=0,
    )
    created = validate_success(
        api.create_device(
            f.device_payload(
                owner["id"],
                label="Porch camera",
                grid_x_m=0,
                grid_y_m=10,
                retention_window_days=45,
            ),
            make_resident_headers(owner["id"]),
        ),
        201,
    )

    stored = validate_success(
        api.get_device(created["id"], make_resident_headers(owner["id"])), 200
    )
    expected = {
        "id": created["id"],
        "owner_resident_id": owner["id"],
        "label": "Porch camera",
        "grid_x_m": 0,
        "grid_y_m": 10,
        "retention_window_days": 45,
        "status": k.DEVICE_STATUS_ACTIVE,
        "auto_decline_requests": False,
        "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
        "solicitations_received_count": 0,
        "pending_solicitation_count": 0,
    }
    assertions.assert_subset(stored, expected)
    assertions.assert_subset(created, expected)
    assertions.assert_mutable_common_fields(stored, version=1)
    assertions.assert_created_equals_updated(stored)
    assertions.assert_instant(stored["created_at"], created["created_at"], "created_at")


def test_device_pages_report_total_count_and_has_more_across_both_pages(
    api: ApiClient, clock: str
) -> None:
    """Two pages of size 2 over three cameras report total_count 3 and has_more true then false.

    PRD: "The pagination block echoed in `meta` carries `limit`, `offset`, `total_count` — the total number of rows matching the filters, not the number returned on this page — and `has_more`, which is true exactly when rows remain beyond the current page."
    PRD: "`offset` controls the starting position: it defaults to 0 and may be no smaller than 0."

    Design: Corner/entities/device_listing_paginates_with_total_count_and_has_more
    """
    owner, _other, owned_ids = _seed_one_owner_three_cameras(api)
    headers = make_resident_headers(owner["id"])

    first_rows, first_meta = validate_paginated(
        api.list_devices(headers, f.page(limit=2, offset=0, owner_resident_id=owner["id"]))
    )
    assert len(first_rows) == 2, f"Expected 2 rows on the first page, got {len(first_rows)}"
    assert first_meta["total_count"] == 3, (
        f"total_count counts the filtered set, not the page: {first_meta!r}"
    )
    assert first_meta["has_more"] is True, f"Rows remain beyond page one: {first_meta!r}"
    assert first_meta["limit"] == 2 and first_meta["offset"] == 0, (
        f"The pagination block echoes the requested limit and offset: {first_meta!r}"
    )

    second_rows, second_meta = validate_paginated(
        api.list_devices(headers, f.page(limit=2, offset=2, owner_resident_id=owner["id"]))
    )
    assert len(second_rows) == 1, (
        f"Expected 1 row on the second page, got {len(second_rows)}"
    )
    assert second_meta["total_count"] == 3, (
        f"total_count is unchanged by paging: {second_meta!r}"
    )
    assert second_meta["has_more"] is False, (
        f"No rows remain beyond page two: {second_meta!r}"
    )
    assert second_meta["limit"] == 2 and second_meta["offset"] == 2, (
        f"The pagination block echoes the requested limit and offset: {second_meta!r}"
    )

    first_ids = [row["id"] for row in first_rows]
    second_ids = [row["id"] for row in second_rows]
    assert not set(first_ids) & set(second_ids), (
        f"The two pages must not overlap: {first_ids} against {second_ids}"
    )
    assert set(first_ids) | set(second_ids) == set(owned_ids), (
        f"The two pages together are the filtered set: {first_ids + second_ids}"
    )
    for row in first_rows + second_rows:
        assert row["owner_resident_id"] == owner["id"], (
            f"A filtered page carries only this owner's cameras: {row!r}"
        )
        assertions.assert_mutable_common_fields(row, version=1)


def test_device_owner_filter_excludes_another_residents_camera(
    api: ApiClient, clock: str
) -> None:
    """The owner filter narrows the counted set, and a second filter narrows it again.

    PRD: "Every filter parameter on every collection is optional and filters are combined conjunctively: supplying two filters returns only rows matching both."
    PRD: "The pagination block echoed in `meta` carries `limit`, `offset`, `total_count` — the total number of rows matching the filters, not the number returned on this page — and `has_more`, which is true exactly when rows remain beyond the current page."

    Design: Corner/entities/device_listing_paginates_with_total_count_and_has_more
    """
    owner, other, owned_ids = _seed_one_owner_three_cameras(api)
    other_device_id = fixtures.list_rows(
        api, "list_devices", owner_resident_id=other["id"]
    )[0]["id"]

    unfiltered_rows, unfiltered_meta = validate_paginated(
        api.list_devices(PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0))
    )
    assert unfiltered_meta["total_count"] == 4, (
        f"Four cameras exist in the portal: {unfiltered_meta!r}"
    )
    assert other_device_id in {row["id"] for row in unfiltered_rows}, (
        "The second resident's camera is visible without a filter"
    )

    owned_rows, owned_meta = validate_paginated(
        api.list_devices(
            PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0, owner_resident_id=owner["id"])
        )
    )
    assert owned_meta["total_count"] == 3, (
        f"The owner filter counts only this owner's three cameras: {owned_meta!r}"
    )
    assert owned_meta["has_more"] is False, f"One page holds all three: {owned_meta!r}"
    assert {row["id"] for row in owned_rows} == set(owned_ids), (
        "The filtered page is exactly this owner's cameras"
    )
    assert other_device_id not in {row["id"] for row in owned_rows}, (
        "Another resident's camera is excluded by the owner filter"
    )

    both_rows, both_meta = validate_paginated(
        api.list_devices(
            PLATFORM_ADMIN_HEADERS,
            f.page(
                limit=10,
                offset=0,
                owner_resident_id=owner["id"],
                status=k.DEVICE_STATUS_ACTIVE,
            ),
        )
    )
    assert both_meta["total_count"] == 3, (
        f"All three of this owner's cameras are ACTIVE: {both_meta!r}"
    )
    assert {row["id"] for row in both_rows} == set(owned_ids)

    none_rows, none_meta = validate_paginated(
        api.list_devices(
            PLATFORM_ADMIN_HEADERS,
            f.page(
                limit=10,
                offset=0,
                owner_resident_id=owner["id"],
                status=k.DEVICE_STATUS_DECOMMISSIONED,
            ),
        )
    )
    assert none_meta["total_count"] == 0, (
        f"Two filters return only rows matching both: {none_meta!r}"
    )
    assert none_rows == [], f"Expected an empty page, got {none_rows!r}"


def test_unknown_resident_id_reports_the_resident_not_found_code(
    api: ApiClient, clock: str
) -> None:
    """A read against a well-formed but unknown resident identifier is a resident-level 404.

    PRD: "Every `{id}` path segment resolves to an existing row, validated **left to right**, with the collection segment deciding which not-found code is raised: `ERR_AGENCY_NOT_FOUND`, `ERR_OFFICER_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_REQUEST_AREA_NOT_FOUND`, `ERR_VIDEO_REQUEST_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_SHARED_CLIP_NOT_FOUND`, `ERR_POST_NOT_FOUND`, `ERR_MODERATION_CASE_NOT_FOUND` or `ERR_TRANSPARENCY_REPORT_NOT_FOUND`, each with HTTP 404."
    PRD: "Every resource in this portal is identified by a server-minted UUID exposed as `id`."

    Design: Corner/entities/resident_get_with_unknown_id_returns_not_found
    """
    real = fixtures.register_resident(
        api,
        display_name="Real Rita",
        email="rita@example.test",
        home_x_m=5,
        home_y_m=5,
        alert_radius_m=0,
    )

    validate_error(
        api.get_resident(_UNKNOWN_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.RESIDENT_NOT_FOUND.value,
        404,
    )

    still_readable = validate_success(
        api.get_resident(real["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert still_readable["id"] == real["id"], (
        "The existing resident is untouched by the failed read"
    )
    assertions.assert_subset(
        still_readable, {"status": k.RESIDENT_STATUS_ACTIVE, "version": 1}
    )
    assertions.assert_mutable_common_fields(still_readable, version=1)


def test_device_creation_without_grid_y_is_refused_and_stores_nothing(
    api: ApiClient, clock: str
) -> None:
    """A camera body missing a required coordinate is a 400 and leaves the collection empty.

    PRD: "The request body is well formed on every write endpoint: every required field present and non-null, every enum value within its declared set, every integer within its declared bounds, every datetime a valid ISO 8601 UTC instant, and a resident `email` that is unique portal-wide — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD: "Registering a camera names its `owner_resident_id`, an owner-supplied `label` of one to eighty characters, and its grid position as `grid_x_m` and `grid_y_m`."

    Design: Corner/entities/device_create_missing_required_grid_y_returns_invalid_request
    """
    owner = fixtures.register_resident(
        api,
        display_name="Req Rae",
        email="rae@example.test",
        home_x_m=0,
        home_y_m=10,
        alert_radius_m=0,
    )
    headers = make_resident_headers(owner["id"])

    validate_error(
        api.create_device(
            {"owner_resident_id": owner["id"], "label": "Half a camera", "grid_x_m": 0},
            headers,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )

    rows, meta = validate_paginated(
        api.list_devices(headers, f.page(limit=10, offset=0, owner_resident_id=owner["id"]))
    )
    assert meta["total_count"] == 0, (
        f"A refused registration creates no camera row: {meta!r}"
    )
    assert rows == [], f"Expected no camera rows, got {rows!r}"

    unchanged = fixtures.read_resident(api, owner["id"])
    assertions.assert_version_unchanged(unchanged, 1)
    assertions.assert_subset(unchanged, {"status": k.RESIDENT_STATUS_ACTIVE})


def test_officer_creation_against_unknown_agency_reports_agency_not_found(
    api: ApiClient, clock: str
) -> None:
    """A body-supplied agency identifier that names no row is a 404, and no officer is enrolled.

    PRD: "Every foreign key supplied in the request body resolves to an existing row — `agency_id`, `owner_resident_id`, `author_resident_id`, `parent_post_id`, `request_area_id` and `resident_post_id` — raising the matching not-found code from the list above with HTTP 404."
    PRD: "This applies to officer creation, camera registration, canvass-area creation, video-request creation, post creation, moderation-case creation and transparency-report compilation."

    Design: Corner/entities/officer_create_with_unknown_agency_returns_not_found
    """
    agency = fixtures.onboarded_agency(
        api, name="Riverbend Police Department", jurisdiction_code="RB-001", min_device_threshold=3
    )

    validate_error(
        api.create_officer(
            f.officer_payload(
                _UNKNOWN_UUID,
                badge_number="B-999",
                full_name="Ghost Officer",
                duty_role=k.DUTY_ROLE_REQUESTER,
            ),
            PLATFORM_ADMIN_HEADERS,
        ),
        ApiErrorId.AGENCY_NOT_FOUND.value,
        404,
    )

    rows, meta = validate_paginated(
        api.list_officers(PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0, agency_id=agency["id"]))
    )
    assert meta["total_count"] == 0, f"A refused enrolment creates no officer row: {meta!r}"
    assert rows == [], f"Expected no officer rows, got {rows!r}"

    all_rows, all_meta = validate_paginated(
        api.list_officers(PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0))
    )
    assert all_meta["total_count"] == 0, (
        f"No officer exists anywhere in the portal: {all_meta!r}"
    )
    assert all_rows == []

    unchanged = fixtures.read_agency(api, agency["id"])
    assertions.assert_version_unchanged(unchanged, agency["version"])
    assertions.assert_subset(unchanged, {"status": k.AGENCY_STATUS_ONBOARDED})


def test_post_category_outside_the_declared_set_is_refused(api: ApiClient, clock: str) -> None:
    """A category the contract does not declare is a 400, while a declared one publishes.

    PRD: "A resident publishing a post supplies their own `author_resident_id` — which must equal the acting `X-User-ID` after identity translation, or the write is refused with `ERR_IDENTITY_MISMATCH` — a `body` of between 1 and 2000 characters, a `category` drawn from `SAFETY_REPORT`, `LOST_PET`, `SUSPICIOUS_ACTIVITY` and `GENERAL`, and the incident position as `post_x_m` and `post_y_m`, each a whole metre between −1000000 and 1000000 on the municipal planning grid."
    PRD: "The request body is well formed on every write endpoint: every required field present and non-null, every enum value within its declared set, every integer within its declared bounds, every datetime a valid ISO 8601 UTC instant, and a resident `email` that is unique portal-wide — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD: "A score below 0.49 means the post is created in `PUBLISHED` with a null `auto_flag_reason` and the alert fan-out runs immediately."

    Design: Corner/entities/resident_post_invalid_enum_category_rejected
    """
    author = fixtures.register_resident(
        api,
        display_name="Poster Pat",
        email="pat@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    headers = make_resident_headers(author["id"])

    validate_error(
        api.create_post(
            f.post_payload(
                author["id"],
                body="Gossip about the neighbours.",
                category="GOSSIP",
                post_x_m=0,
                post_y_m=0,
            ),
            headers,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )
    assert fixtures.list_rows(api, "list_posts", author_resident_id=author["id"]) == [], (
        "A refused publication creates no post row"
    )

    accepted = validate_success(
        api.create_post(
            f.post_payload(
                author["id"],
                body="A legitimate safety report about a broken street light.",
                category=k.CATEGORY_SAFETY_REPORT,
                post_x_m=0,
                post_y_m=0,
                hostile_tone_count=1,
            ),
            headers,
        ),
        201,
    )
    assertions.assert_subset(
        accepted,
        {
            "author_resident_id": author["id"],
            "body": "A legitimate safety report about a broken street light.",
            "category": k.CATEGORY_SAFETY_REPORT,
            "post_x_m": 0,
            "post_y_m": 0,
            "state": k.POST_PUBLISHED,
            "hostile_tone_count": 1,
            "protected_class_term_count": 0,
            "unverified_assertion_count": 0,
            "location_profiling_count": 0,
            "alert_fanout_cap": k.DEFAULT_ALERT_FANOUT_CAP,
            "flag_count": 0,
            "revision_count": 0,
            "flagged_by_resident_ids": [],
        },
    )
    assertions.assert_nulls(accepted, "auto_flag_reason", "parent_post_id")
    assertions.assert_score(accepted["discrimination_score"], "0.09")
    assertions.assert_zero_counters(
        accepted, "alert_candidate_count", "alert_fanout_count", "alert_suppressed_count"
    )
    assertions.assert_fanout_conservation(accepted, k.DEFAULT_ALERT_FANOUT_CAP)
    assertions.assert_mutable_common_fields(accepted, version=1)
    assertions.assert_created_equals_updated(accepted)


def test_post_classifier_signal_above_fifty_is_refused(api: ApiClient, clock: str) -> None:
    """A classifier signal outside its declared zero-to-fifty bound is a 400 and stores nothing.

    PRD: "Optionally they may supply `parent_post_id`, the identifier of the post this one replies to, which is a self-reference into the feed and defaults to null for a top-level post; an `alert_fanout_cap` between 0 and 500, defaulting to 50; and the four classifier signals `protected_class_term_count`, `unverified_assertion_count`, `location_profiling_count` and `hostile_tone_count`, each an integer between 0 and 50 and each defaulting to 0."
    PRD: "The request body is well formed on every write endpoint: every required field present and non-null, every enum value within its declared set, every integer within its declared bounds, every datetime a valid ISO 8601 UTC instant, and a resident `email` that is unique portal-wide — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/resident_post_invalid_enum_category_rejected
    """
    author = fixtures.register_resident(
        api,
        display_name="Poster Pat",
        email="pat@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    headers = make_resident_headers(author["id"])

    validate_error(
        api.create_post(
            f.post_payload(
                author["id"],
                body="Too many signals.",
                category=k.CATEGORY_SAFETY_REPORT,
                post_x_m=0,
                post_y_m=0,
                hostile_tone_count=k.MAX_SIGNAL_COUNT + 1,
            ),
            headers,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )

    rows, meta = validate_paginated(
        api.list_posts(headers, f.page(limit=10, offset=0, author_resident_id=author["id"]))
    )
    assert meta["total_count"] == 0, f"A refused publication creates no post row: {meta!r}"
    assert rows == [], f"Expected no post rows, got {rows!r}"

    unchanged = fixtures.read_resident(api, author["id"])
    assertions.assert_version_unchanged(unchanged, 1)
    assertions.assert_subset(unchanged, {"post_privilege_state": k.PRIVILEGE_UNRESTRICTED})


def test_data_control_receipt_carries_only_its_declared_record_fields(
    api: ApiClient, clock: str
) -> None:
    """The receipt of an exercised data control records the act and nothing versionable.

    PRD: "Account-level data controls are the resident's ultimate lever, and each exercise of one produces an immutable receipt naming the `action_type` exercised, an optional free-text `reason`, the `applied_at` instant read from the logical clock, and four counts of what it touched: `affected_device_count`, `affected_solicitation_count`, `affected_clip_count` and `affected_request_count`."
    PRD: "A `NotificationDispatch` and a `DataControlAction` each expose only `id` and `created_at`: they have no `updated_at` and no `version`, because nothing in the system ever mutates them once written."
    PRD: "Level one sets `data_sharing_opt_out` to true on the resident."

    Design: Corner/entities/data_control_action_row_is_immutable
    """
    resident = fixtures.register_resident(
        api, display_name="Control Cass", email="cass@example.test", home_x_m=0, home_y_m=10
    )
    device = fixtures.register_device(
        api, resident["id"], label="Porch camera", grid_x_m=0, grid_y_m=10
    )
    headers = make_resident_headers(resident["id"])

    receipt = validate_success(
        api.exercise_data_control(
            resident["id"],
            f.data_control_payload(k.ACTION_OPT_OUT, reason="Stepping back from requests."),
            headers,
        ),
        201,
    )

    assertions.assert_receipt_common_fields(receipt)
    assertions.assert_subset(
        receipt,
        {
            "action_type": k.ACTION_OPT_OUT,
            "reason": "Stepping back from requests.",
            "affected_device_count": 1,
        },
    )
    assertions.assert_zero_counters(
        receipt, "affected_solicitation_count", "affected_clip_count", "affected_request_count"
    )
    assertions.assert_instant(receipt["applied_at"], clock, "applied_at")

    after = fixtures.read_resident(api, resident["id"])
    assertions.assert_subset(after, {"data_sharing_opt_out": True, "status": k.RESIDENT_STATUS_ACTIVE})
    assertions.assert_version_advanced(after, resident["version"])

    camera = fixtures.read_device(api, device["id"])
    assertions.assert_subset(
        camera,
        {
            "auto_decline_requests": True,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_OPT_OUT,
        },
    )

    rows, meta = validate_paginated(
        api.list_data_control_actions(resident["id"], headers, f.page(limit=10, offset=0))
    )
    assert meta["total_count"] == 1, f"Exactly one control was exercised: {meta!r}"
    assert rows[0]["id"] == receipt["id"], (
        f"The listed receipt is the one just written: {rows[0]!r} vs {receipt!r}"
    )


def test_second_data_control_appends_a_row_and_leaves_the_first_untouched(
    api: ApiClient, clock: str
) -> None:
    """Opting back in writes a second receipt oldest-last; the opt-out receipt never changes.

    PRD: "It sets `data_sharing_opt_out` back to false, and clears `auto_decline_requests` on exactly those cameras whose `auto_decline_source` is `OPT_OUT`, resetting their `auto_decline_source` to `NONE`."
    PRD: "Every data control advances the resident's `version` by 1, and the receipt itself is append-only: it carries `id` and `created_at` and nothing else from the common property set."
    PRD: "Unless a specific collection documents a different ordering, list results are sorted by `created_at` ascending."

    Design: Corner/entities/data_control_action_row_is_immutable
    """
    resident = fixtures.register_resident(
        api, display_name="Control Cass", email="cass@example.test", home_x_m=0, home_y_m=10
    )
    device = fixtures.register_device(
        api, resident["id"], label="Porch camera", grid_x_m=0, grid_y_m=10
    )
    headers = make_resident_headers(resident["id"])

    first = validate_success(
        api.exercise_data_control(
            resident["id"],
            f.data_control_payload(k.ACTION_OPT_OUT, reason="Stepping back from requests."),
            headers,
        ),
        201,
    )

    fixtures.set_clock(api, _LATER_CLOCK)

    second = validate_success(
        api.exercise_data_control(
            resident["id"],
            f.data_control_payload(k.ACTION_OPT_IN, reason="Happy to help again."),
            headers,
        ),
        201,
    )
    assertions.assert_receipt_common_fields(second)
    assert second["id"] != first["id"], "Each exercise mints its own receipt"
    assertions.assert_subset(
        second,
        {
            "action_type": k.ACTION_OPT_IN,
            "reason": "Happy to help again.",
            "affected_device_count": 1,
        },
    )
    assertions.assert_zero_counters(
        second, "affected_solicitation_count", "affected_clip_count", "affected_request_count"
    )
    assertions.assert_instant(second["applied_at"], _LATER_CLOCK, "applied_at")

    rows, meta = validate_paginated(
        api.list_data_control_actions(resident["id"], headers, f.page(limit=10, offset=0))
    )
    assert meta["total_count"] == 2, f"Two controls were exercised: {meta!r}"
    assert [row["id"] for row in rows] == [first["id"], second["id"]], (
        f"Receipts are listed oldest first: {rows!r}"
    )

    listed_first = rows[0]
    assertions.assert_receipt_common_fields(listed_first)
    assertions.assert_subset(
        listed_first,
        {
            "action_type": k.ACTION_OPT_OUT,
            "reason": "Stepping back from requests.",
            "affected_device_count": 1,
        },
    )
    assertions.assert_instant(listed_first["applied_at"], clock, "applied_at")
    assertions.assert_instant(listed_first["created_at"], first["created_at"], "created_at")

    after = fixtures.read_resident(api, resident["id"])
    assertions.assert_subset(after, {"data_sharing_opt_out": False, "status": k.RESIDENT_STATUS_ACTIVE})
    assertions.assert_version_advanced(after, resident["version"], by=2)

    camera = fixtures.read_device(api, device["id"])
    assertions.assert_subset(
        camera,
        {
            "auto_decline_requests": False,
            "auto_decline_source": k.AUTO_DECLINE_SOURCE_NONE,
        },
    )
