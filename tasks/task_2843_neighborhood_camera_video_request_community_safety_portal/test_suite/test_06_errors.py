"""Refusals: which error identifier the portal reports, and that it changes nothing.

A single request can violate several rules at once, and the contract fixes which
violation is reported. Every test here drives one refusal, asserts the exact
error identifier and HTTP status the contract names for it, and then re-reads the
row that was refused to prove that the refusal moved no state, no counter and no
``version``.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    MODERATOR_ID,
    MODERATOR_SECOND_HEADERS,
    MODERATOR_SECOND_ID,
    PLATFORM_ADMIN_HEADERS,
    PLATFORM_ADMIN_ID,
    PLATFORM_ADMIN_SECOND_HEADERS,
    PLATFORM_ADMIN_SECOND_ID,
    headers_with_empty_user_id,
    headers_with_undeclared_role,
    headers_without_role,
    make_officer_headers,
    make_resident_headers,
)

# Nine syntactically valid identifiers that name no row in any family, one per
# collection under test, so the nine refusals cannot be confused with each other.
_ABSENT_OFFICER = "00000000-0000-4000-8000-000000000001"
_ABSENT_DEVICE = "00000000-0000-4000-8000-000000000002"
_ABSENT_AREA = "00000000-0000-4000-8000-000000000003"
_ABSENT_REQUEST = "00000000-0000-4000-8000-000000000004"
_ABSENT_SOLICITATION = "00000000-0000-4000-8000-000000000005"
_ABSENT_CLIP = "00000000-0000-4000-8000-000000000006"
_ABSENT_POST = "00000000-0000-4000-8000-000000000007"
_ABSENT_CASE = "00000000-0000-4000-8000-000000000008"
_ABSENT_REPORT = "00000000-0000-4000-8000-000000000009"
_ABSENT_RESIDENT = "00000000-0000-4000-8000-000000000099"


def test_each_family_reports_its_own_not_found_code(api: ApiClient, clock: str) -> None:
    """Nine reads of nine absent identifiers report nine distinct 404 codes.

    PRD: "Every `{id}` path segment resolves to an existing row, validated **left to right**, with the collection segment deciding which not-found code is raised: `ERR_AGENCY_NOT_FOUND`, `ERR_OFFICER_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_REQUEST_AREA_NOT_FOUND`, `ERR_VIDEO_REQUEST_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_SHARED_CLIP_NOT_FOUND`, `ERR_POST_NOT_FOUND`, `ERR_MODERATION_CASE_NOT_FOUND` or `ERR_TRANSPARENCY_REPORT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/unknown_ids_across_every_family_return_the_matching_not_found
    """
    attempts = [
        (api.get_officer(_ABSENT_OFFICER, PLATFORM_ADMIN_HEADERS), ApiErrorId.OFFICER_NOT_FOUND),
        (api.get_device(_ABSENT_DEVICE, PLATFORM_ADMIN_HEADERS), ApiErrorId.DEVICE_NOT_FOUND),
        (
            api.get_request_area(_ABSENT_AREA, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.REQUEST_AREA_NOT_FOUND,
        ),
        (
            api.get_video_request(_ABSENT_REQUEST, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.VIDEO_REQUEST_NOT_FOUND,
        ),
        (
            api.get_solicitation(_ABSENT_SOLICITATION, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.SOLICITATION_NOT_FOUND,
        ),
        (
            api.get_shared_clip(_ABSENT_CLIP, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.SHARED_CLIP_NOT_FOUND,
        ),
        (api.get_post(_ABSENT_POST, PLATFORM_ADMIN_HEADERS), ApiErrorId.POST_NOT_FOUND),
        (
            api.get_moderation_case(_ABSENT_CASE, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.MODERATION_CASE_NOT_FOUND,
        ),
        (
            api.get_report(_ABSENT_REPORT, PLATFORM_ADMIN_HEADERS),
            ApiErrorId.TRANSPARENCY_REPORT_NOT_FOUND,
        ),
    ]

    observed = []
    for response, expected in attempts:
        observed.append(validate_error(response, expected.value, 404)["error_id"])

    assert len(set(observed)) == len(observed), (
        f"Each collection must raise its own not-found code, got {observed}"
    )


def test_unusable_role_header_reports_unauthenticated(api: ApiClient, clock: str) -> None:
    """A missing role header and an unrecognised role name are both 401, and write nothing.

    PRD: "When `X-User-Role` is missing, or carries a value that is not one of the six recognised role names, or when `X-User-ID` is missing or empty for any role other than `Anonymous`, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_or_empty_auth_headers_return_unauthenticated
    """
    resident = fixtures.register_resident(
        api, display_name="R1", email="r1@example.test", home_x_m=0, home_y_m=10, alert_radius_m=0
    )

    missing_role = api.create_device(
        f.device_payload(resident["id"], label="No role header", grid_x_m=0, grid_y_m=10),
        headers_without_role(resident["id"]),
    )
    validate_error(missing_role, ApiErrorId.UNAUTHENTICATED.value, 401)

    undeclared_role = api.create_device(
        f.device_payload(resident["id"], label="Unknown role", grid_x_m=0, grid_y_m=11),
        headers_with_undeclared_role(resident["id"]),
    )
    validate_error(undeclared_role, ApiErrorId.UNAUTHENTICATED.value, 401)

    rows, meta = validate_paginated(
        api.list_devices(
            PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0, owner_resident_id=resident["id"])
        )
    )
    assert meta["total_count"] == 0, "A refused registration must not create a camera"
    assert rows == []


def test_empty_user_id_outranks_an_unknown_body_foreign_key(api: ApiClient, clock: str) -> None:
    """An empty X-User-ID is 401 even though the body names a resident that does not exist.

    PRD: "When `X-User-Role` is missing, or carries a value that is not one of the six recognised role names, or when `X-User-ID` is missing or empty for any role other than `Anonymous`, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD: "Rules are evaluated strictly in the order below, the first violated rule decides the response, and no later rule is evaluated once one has fired."

    Design: Corner/errors/missing_or_empty_auth_headers_return_unauthenticated
    """
    response = api.create_device(
        f.device_payload(_ABSENT_RESIDENT, label="Empty user id", grid_x_m=0, grid_y_m=12),
        headers_with_empty_user_id(k.ROLE_RESIDENT),
    )
    validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)

    rows, meta = validate_paginated(
        api.list_devices(PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0))
    )
    assert meta["total_count"] == 0, "A refused registration must not create a camera"
    assert rows == []


def test_audit_review_of_an_unflagged_request_reports_audit_not_pending(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """Neither audit trigger fires, so an auditor's review is refused and nothing moves.

    PRD: "When neither condition holds, the compliance dimension stops at `JUSTIFICATION_LOGGED` and no audit is ever required."
    PRD: "It is only accepted while `compliance_state` is `AUDIT_FLAGGED` — otherwise `ERR_AUDIT_NOT_PENDING` — and the acting officer must belong to the same agency as the request, must hold a `duty_role` of `AUDITOR` or `DUAL_ROLE`, and must not be the request's `submitting_officer_id`."

    Design: Corner/errors/audit_review_before_the_request_is_flagged_returns_audit_not_pending
    """
    area = fixtures.read_area(api, canvass["area"]["id"])
    assert area["radius_m"] == 500
    assert area["eligible_device_count"] == 3, (
        "Three eligible cameras is not strictly greater than four, so no audit is required"
    )

    before = fixtures.read_request(api, canvass["request_id"])
    assertions.assert_subset(
        before,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
        },
    )
    assertions.assert_nulls(before, "auditor_officer_id", "audit_note")

    auditor = fixtures.add_auditor(api, canvass["agency_id"])

    response = api.review_audit(
        canvass["request_id"],
        f.audit_review_payload(decision=k.AUDIT_DECISION_CLEAR, audit_note="Nothing to see here."),
        make_officer_headers(auditor["id"]),
    )
    validate_error(response, ApiErrorId.AUDIT_NOT_PENDING.value, 409)

    after = fixtures.read_request(api, canvass["request_id"])
    assertions.assert_subset(
        after,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
        },
    )
    assertions.assert_nulls(after, "auditor_officer_id", "audit_note")
    assertions.assert_version_unchanged(after, before["version"])

    assert fixtures.read_officer(api, auditor["id"])["audits_completed_count"] == 0, (
        "A refused review must not credit the auditor with an audit"
    )


def _seed_deactivated_resident(api: ApiClient) -> Dict[str, Any]:
    """One resident owning one camera, who has just closed their own account."""
    household = fixtures.seed_resident_with_device(
        api,
        display_name="R1",
        email="r1@example.test",
        x=0,
        y=10,
        alert_radius_m=0,
        label="Front door",
    )
    receipt = fixtures.exercise_data_control(
        api,
        household["resident_id"],
        k.ACTION_DEACTIVATE_ACCOUNT,
        reason="Leaving the neighbourhood.",
    )
    household["receipt"] = receipt
    return household


def test_every_write_by_a_deactivated_account_reports_resident_deactivated(
    api: ApiClient, clock: str
) -> None:
    """Registering a camera, patching alert settings and a second control are all refused.

    PRD: "The resident moves `ACTIVE → DEACTIVATED`, `data_sharing_opt_out` is set to true, every camera of theirs is set to `DECOMMISSIONED`, every solicitation still in `SOLICITED` is driven to `DECLINED` with `decline_reason` `ACCOUNT_DEACTIVATED`, and every clip still in `RETAINED` is moved to `PURGE_PENDING` rather than purged outright."
    PRD: "A deactivated resident may still read their own data but may not write anything — every write attempt is refused with `ERR_RESIDENT_DEACTIVATED`."

    Design: Corner/errors/deactivated_account_write_returns_resident_deactivated
    """
    household = _seed_deactivated_resident(api)
    resident_id = household["resident_id"]
    headers = make_resident_headers(resident_id)

    assert household["receipt"]["affected_device_count"] == 1
    assert (
        fixtures.read_device(api, household["device_id"])["status"]
        == k.DEVICE_STATUS_DECOMMISSIONED
    )
    before = fixtures.read_resident(api, resident_id)
    assertions.assert_subset(
        before, {"status": k.RESIDENT_STATUS_DEACTIVATED, "data_sharing_opt_out": True}
    )

    registration = api.create_device(
        f.device_payload(resident_id, label="Another camera", grid_x_m=0, grid_y_m=99),
        headers,
    )
    validate_error(registration, ApiErrorId.RESIDENT_DEACTIVATED.value, 409)

    settings = api.update_alert_settings(
        resident_id, f.alert_settings_payload(alert_radius_m=500), headers
    )
    validate_error(settings, ApiErrorId.RESIDENT_DEACTIVATED.value, 409)

    second_control = api.exercise_data_control(
        resident_id,
        f.data_control_payload(k.ACTION_OPT_IN, reason="Changed my mind."),
        headers,
    )
    validate_error(second_control, ApiErrorId.RESIDENT_DEACTIVATED.value, 409)

    after = fixtures.read_resident(api, resident_id)
    assertions.assert_subset(
        after,
        {
            "status": k.RESIDENT_STATUS_DEACTIVATED,
            "data_sharing_opt_out": True,
            "alert_radius_m": before["alert_radius_m"],
        },
    )
    assertions.assert_version_unchanged(after, before["version"])

    rows, meta = validate_paginated(
        api.list_devices(PLATFORM_ADMIN_HEADERS, f.page(limit=10, offset=0, owner_resident_id=resident_id))
    )
    assert meta["total_count"] == 1, "The refused registration created no second camera"
    assert [row["id"] for row in rows] == [household["device_id"]]


def test_a_deactivated_account_still_reads_its_own_row_and_its_one_receipt(
    api: ApiClient, clock: str
) -> None:
    """The closed account reads back with 200 and exactly one data-control receipt.

    PRD: "A deactivated resident may still read their own data but may not write anything — every write attempt is refused with `ERR_RESIDENT_DEACTIVATED`."

    Design: Corner/errors/deactivated_account_write_returns_resident_deactivated
    """
    household = _seed_deactivated_resident(api)
    resident_id = household["resident_id"]
    headers = make_resident_headers(resident_id)

    refused = api.exercise_data_control(
        resident_id,
        f.data_control_payload(k.ACTION_OPT_IN, reason="Changed my mind."),
        headers,
    )
    validate_error(refused, ApiErrorId.RESIDENT_DEACTIVATED.value, 409)

    own_row = validate_success(api.get_resident(resident_id, headers))
    assertions.assert_subset(
        own_row, {"status": k.RESIDENT_STATUS_DEACTIVATED, "data_sharing_opt_out": True}
    )

    receipts = fixtures.list_data_control_actions(api, resident_id)
    assert [row["id"] for row in receipts] == [household["receipt"]["id"]], (
        "The refused control must leave no receipt behind"
    )
    assertions.assert_receipt_common_fields(receipts[0])


def _agency_allowed_one_request(api: ApiClient, positions: Any) -> Dict[str, Any]:
    """An onboarded agency whose lifetime allotment is a single request.

    Its concurrency ceiling stays at three, so the two submission quotas can
    never be confused with one another, and one resident with one camera is
    seeded at each grid point given.
    """
    world = fixtures.seed_agency_with_officer(
        api, min_device_threshold=3, max_open_requests=3, period_request_quota=1
    )
    world["households"] = fixtures.seed_residents_with_devices(api, positions)
    return world


def test_creating_a_request_against_a_draft_area_reports_area_not_locked(
    api: ApiClient, clock: str
) -> None:
    """A draft area has no frozen roster, so the request cannot be opened against it.

    PRD: "The area must be in `LOCKED`; an area still in `DRAFT` has neither a frozen roster nor an `effective_min_devices`, so the creation is refused with `ERR_AREA_NOT_LOCKED`, and the owning agency must be `ONBOARDED`."

    Design: Corner/errors/request_creation_and_submit_gates_each_return_their_own_error
    """
    world = _agency_allowed_one_request(api, ((0, 10), (0, 20)))
    area = fixtures.create_area(
        api, world["agency_id"], world["officer_id"], area_label="Area 1"
    )
    assertions.assert_subset(
        area,
        {
            "status": k.AREA_STATUS_DRAFT,
            "eligible_device_count": 0,
            "derived_request_count": 0,
            "version": 1,
        },
    )
    assertions.assert_nulls(area, "effective_min_devices", "locked_at", "invalidated_reason")

    response = api.create_video_request(
        f.video_request_payload(area["id"], area["version"], case_number="CASE-2001"),
        world["officer_headers"],
    )
    validate_error(response, ApiErrorId.AREA_NOT_LOCKED.value, 409)

    after = fixtures.read_area(api, area["id"])
    assertions.assert_subset(
        after, {"status": k.AREA_STATUS_DRAFT, "derived_request_count": 0}
    )
    assertions.assert_nulls(after, "effective_min_devices", "locked_at")
    assertions.assert_version_unchanged(after, area["version"])
    assert fixtures.list_rows(api, "list_video_requests") == [], (
        "A refused creation must leave no request row behind"
    )


def test_submitting_below_the_frozen_device_floor_reports_min_device_threshold_not_met(
    api: ApiClient, clock: str
) -> None:
    """Two eligible cameras against a floor of three dispatches nothing at all.

    PRD: "Then the area's frozen `eligible_device_count` must be greater than or equal to its frozen `effective_min_devices`; below that minimum the canvass would identify individual households rather than survey a neighbourhood, so **no solicitation is dispatched at all** and the answer is `ERR_MIN_DEVICE_THRESHOLD_NOT_MET`."

    Design: Corner/errors/request_creation_and_submit_gates_each_return_their_own_error
    """
    world = _agency_allowed_one_request(api, ((0, 10), (0, 20)))
    area = fixtures.seed_locked_area(
        api, world["agency_id"], world["officer_id"], area_label="Area 1"
    )
    assertions.assert_subset(
        area,
        {
            "status": k.AREA_STATUS_LOCKED,
            "eligible_device_count": 2,
            "effective_min_devices": 3,
        },
    )

    request = fixtures.create_video_request(
        api, area, world["officer_id"], case_number="CASE-2002"
    )
    fixtures.log_justification(api, request["id"], world["officer_id"])
    before = fixtures.read_request(api, request["id"])
    assertions.assert_subset(
        before,
        {
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
        },
    )

    response = api.submit_video_request(request["id"], world["officer_headers"])
    validate_error(response, ApiErrorId.MIN_DEVICE_THRESHOLD_NOT_MET.value, 409)

    after = fixtures.read_request(api, request["id"])
    assertions.assert_subset(
        after,
        {
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "solicitation_count": 0,
            "pending_count": 0,
            "shared_count": 0,
            "declined_count": 0,
            "expired_count": 0,
            "withdrawn_count": 0,
            "shared_clip_count": 0,
            "provisional_share_rate_bps": 0,
        },
    )
    assertions.assert_nulls(after, "submitted_at", "expires_at")
    assertions.assert_version_unchanged(after, before["version"])

    assert fixtures.list_solicitations(api, video_request_id=request["id"]) == [], (
        "The refusal dispatches no solicitation at all"
    )
    agency = fixtures.read_agency(api, world["agency_id"])
    assertions.assert_subset(agency, {"open_request_count": 0, "requests_submitted_count": 0})
    assert fixtures.read_officer(api, world["officer_id"])["requests_submitted_count"] == 0


def test_a_second_lifetime_submission_reports_the_period_quota_not_the_open_quota(
    api: ApiClient, clock: str
) -> None:
    """One request is open against a ceiling of three, so the lifetime gate is the one that fires.

    PRD: "The agency's two quotas are checked **last**, after every state precondition and every other business rule, so a quota breach can never mask a consent, window or threshold failure."
    PRD: "The second gate is the lifetime allotment: when `requests_submitted_count` has reached `period_request_quota` the submission is refused with `ERR_AGENCY_PERIOD_QUOTA_EXCEEDED`."

    Design: Corner/errors/request_creation_and_submit_gates_each_return_their_own_error
    """
    world = _agency_allowed_one_request(api, ((0, 10), (0, 20), (0, 30)))
    first = fixtures.seed_submitted_request(
        api,
        world["agency_id"],
        world["officer_id"],
        case_number="CASE-2003",
        area_overrides={
            "area_label": "Area 2",
            "window_start_utc": "2026-08-05T00:00:00Z",
            "window_end_utc": "2026-08-05T06:00:00Z",
        },
    )
    assertions.assert_subset(
        first["area"], {"eligible_device_count": 3, "effective_min_devices": 3}
    )
    assertions.assert_subset(
        first["request"],
        {"lifecycle_state": k.LIFECYCLE_SOLICITING, "solicitation_count": 3, "pending_count": 3},
    )
    agency_before = fixtures.read_agency(api, world["agency_id"])
    assertions.assert_subset(
        agency_before,
        {
            "max_open_requests": 3,
            "period_request_quota": 1,
            "open_request_count": 1,
            "requests_submitted_count": 1,
        },
    )

    second = fixtures.seed_justified_request(
        api,
        world["agency_id"],
        world["officer_id"],
        case_number="CASE-2004",
        area_overrides={
            "area_label": "Area 3",
            "window_start_utc": "2026-08-02T00:00:00Z",
            "window_end_utc": "2026-08-02T06:00:00Z",
        },
    )
    before = fixtures.read_request(api, second["request_id"])

    response = api.submit_video_request(second["request_id"], world["officer_headers"])
    refusal = validate_error(response, ApiErrorId.AGENCY_PERIOD_QUOTA_EXCEEDED.value, 409)
    assert refusal["error_id"] != ApiErrorId.AGENCY_OPEN_REQUEST_QUOTA_EXCEEDED.value, (
        "One open request against a ceiling of three clears the concurrency gate, "
        "so only the lifetime gate can fire"
    )

    after = fixtures.read_request(api, second["request_id"])
    assertions.assert_subset(
        after,
        {
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "solicitation_count": 0,
            "pending_count": 0,
            "provisional_share_rate_bps": 0,
        },
    )
    assertions.assert_nulls(after, "submitted_at", "expires_at")
    assertions.assert_version_unchanged(after, before["version"])
    assert fixtures.list_solicitations(api, video_request_id=second["request_id"]) == []

    agency_after = fixtures.read_agency(api, world["agency_id"])
    assertions.assert_subset(
        agency_after, {"open_request_count": 1, "requests_submitted_count": 1}
    )
    assertions.assert_version_unchanged(agency_after, agency_before["version"])


# Exactly 72 hours after the standard submission at 2026-08-12T00:00:00Z.
_RESPONSE_DEADLINE = "2026-08-15T00:00:00Z"


def test_footage_starting_before_the_justified_window_reports_clip_outside_request_window(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """A segment reaching back an hour before the window is refused with 422 and creates no clip.

    PRD: "An officer may only receive footage from the window they justified, so a segment that starts before the window or runs past its end is refused with `ERR_CLIP_OUTSIDE_REQUEST_WINDOW` (HTTP 422)."

    Design: Corner/errors/share_and_decline_gates_each_return_their_own_error
    """
    device = canvass["devices"][0]
    owner = canvass["households"][0]
    solicitation = fixtures.solicitation_for_device(api, canvass["request_id"], device["id"])
    assertions.assert_instant(
        solicitation["respond_deadline_utc"], _RESPONSE_DEADLINE, "respond_deadline_utc"
    )
    assert solicitation["status"] == k.SOLICITATION_SOLICITED

    response = api.share_footage(
        solicitation["id"],
        f.share_payload(recorded_start_utc="2026-08-07T23:00:00Z", duration_seconds=1800),
        owner["headers"],
    )
    validate_error(response, ApiErrorId.CLIP_OUTSIDE_REQUEST_WINDOW.value, 422)

    after = fixtures.read_solicitation(api, solicitation["id"])
    assertions.assert_subset(
        after, {"status": k.SOLICITATION_SOLICITED, "clip_count": 0}
    )
    assertions.assert_nulls(after, "responded_at", "decline_reason")
    assertions.assert_version_unchanged(after, solicitation["version"])

    request = fixtures.read_request(api, canvass["request_id"])
    assertions.assert_subset(
        request,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "pending_count": 3,
            "shared_count": 0,
            "shared_clip_count": 0,
        },
    )
    assert fixtures.list_clips_for_device(api, device["id"]) == [], (
        "A refused share must create no clip"
    )
    assert fixtures.read_device(api, device["id"])["pending_solicitation_count"] == 1


def test_sharing_at_the_deadline_instant_reports_solicitation_deadline_passed(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """The deadline is exclusive, so the clock standing exactly on it is already too late.

    PRD: "`lifecycle_state` moves `DRAFT → SOLICITING`, `submitted_at` is stamped from the logical clock, and `expires_at` is set to exactly 72 hours after `submitted_at` — three days is the whole window a camera owner gets to answer."
    PRD: "And the logical clock must be strictly before the solicitation's `respond_deadline_utc` — at or after that instant the owner may no longer answer even if the sweep has not yet marked the solicitation `EXPIRED`, and the answer is `ERR_SOLICITATION_DEADLINE_PASSED`."

    Design: Corner/errors/share_and_decline_gates_each_return_their_own_error
    """
    device = canvass["devices"][0]
    owner = canvass["households"][0]
    solicitation = fixtures.solicitation_for_device(api, canvass["request_id"], device["id"])
    assertions.assert_instant(
        canvass["request"]["expires_at"], _RESPONSE_DEADLINE, "expires_at"
    )
    assertions.assert_instant(
        solicitation["respond_deadline_utc"], _RESPONSE_DEADLINE, "respond_deadline_utc"
    )

    fixtures.set_clock(api, _RESPONSE_DEADLINE)

    response = api.share_footage(
        solicitation["id"],
        f.share_payload(recorded_start_utc="2026-08-08T01:00:00Z", duration_seconds=1800),
        owner["headers"],
    )
    validate_error(response, ApiErrorId.SOLICITATION_DEADLINE_PASSED.value, 409)

    after = fixtures.read_solicitation(api, solicitation["id"])
    assertions.assert_subset(
        after, {"status": k.SOLICITATION_SOLICITED, "clip_count": 0}
    )
    assertions.assert_nulls(after, "responded_at", "decline_reason")
    assertions.assert_version_unchanged(after, solicitation["version"])

    request = fixtures.read_request(api, canvass["request_id"])
    assertions.assert_subset(
        request,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "pending_count": 3,
            "expired_count": 0,
            "shared_clip_count": 0,
        },
    )
    assert fixtures.list_clips_for_device(api, device["id"]) == []


def test_declining_after_withdrawal_reports_request_not_soliciting(
    api: ApiClient, canvass: Dict[str, Any]
) -> None:
    """With the deadline also passed, the earlier lifecycle rule is the one reported.

    PRD: "Declining is the recorded refusal, and it is a strictly narrower operation than sharing: it is accepted only while the solicitation is in `SOLICITED`, only from the solicitation's own `resident_id`, only while the owning request is `SOLICITING`, and only strictly before `respond_deadline_utc`."
    PRD: "Rules are evaluated strictly in the order below, the first violated rule decides the response, and no later rule is evaluated once one has fired."

    Design: Corner/errors/share_and_decline_gates_each_return_their_own_error
    """
    device = canvass["devices"][1]
    owner = canvass["households"][1]
    solicitation = fixtures.solicitation_for_device(api, canvass["request_id"], device["id"])

    fixtures.set_clock(api, _RESPONSE_DEADLINE)
    withdrawn = fixtures.withdraw_request(
        api,
        canvass["request_id"],
        canvass["officer_headers"],
        reason="Canvass abandoned after the response window closed.",
    )
    assertions.assert_subset(
        withdrawn,
        {
            "lifecycle_state": k.LIFECYCLE_WITHDRAWN,
            "withdraw_reason": k.WITHDRAW_REASON_OFFICER,
            "withdrawn_count": 3,
            "pending_count": 0,
        },
    )
    before = fixtures.read_solicitation(api, solicitation["id"])
    assert before["status"] == k.SOLICITATION_WITHDRAWN

    response = api.decline_solicitation(
        solicitation["id"], f.decline_payload(k.DECLINE_OWNER_DECLINE), owner["headers"]
    )
    refusal = validate_error(response, ApiErrorId.REQUEST_NOT_SOLICITING.value, 409)
    assert refusal["error_id"] != ApiErrorId.SOLICITATION_DEADLINE_PASSED.value, (
        "The lifecycle rule sits above the deadline rule in the ordering"
    )
    assert refusal["error_id"] != ApiErrorId.SOLICITATION_ALREADY_RESOLVED.value, (
        "The lifecycle rule sits above the solicitation-status rule in the ordering"
    )

    after = fixtures.read_solicitation(api, solicitation["id"])
    assertions.assert_subset(after, {"status": k.SOLICITATION_WITHDRAWN, "clip_count": 0})
    assertions.assert_nulls(after, "decline_reason")
    assertions.assert_version_unchanged(after, before["version"])

    request = fixtures.read_request(api, canvass["request_id"])
    assertions.assert_subset(
        request,
        {
            "lifecycle_state": k.LIFECYCLE_WITHDRAWN,
            "withdrawn_count": 3,
            "declined_count": 0,
            "pending_count": 0,
        },
    )
    assertions.assert_version_unchanged(request, withdrawn["version"])


def _post_under_review(api: ApiClient) -> Dict[str, Any]:
    """One author, three neighbours, and a post two of them have already flagged.

    Every account sets an alert radius of zero, so nothing here turns on the
    notification fan-out. Opening the case takes the post out of the feed.
    """
    author = fixtures.register_resident(
        api,
        display_name="Author A",
        email="authora@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
    )
    neighbours = [
        fixtures.register_resident(
            api,
            display_name=f"N{index}",
            email=f"n{index}@example.test",
            home_x_m=10 * index,
            home_y_m=0,
            alert_radius_m=0,
        )
        for index in (1, 2, 3)
    ]
    seeded = fixtures.seed_post_under_review(
        api,
        author["id"],
        [neighbours[0]["id"], neighbours[1]["id"]],
        body="Someone left a bicycle unlocked by the mailboxes overnight.",
    )
    seeded["author"] = author
    seeded["neighbours"] = neighbours
    return seeded


def test_flagging_a_post_that_has_left_the_feed_reports_post_not_published(
    api: ApiClient, clock: str
) -> None:
    """A third neighbour's flag arrives after the case opened, and is not counted.

    PRD: "A post must be in `PUBLISHED` to be flagged, or the attempt is refused with `ERR_POST_NOT_PUBLISHED`."
    PRD: "Each accepted flag increments `flag_count` by 1, appends the flagger, and advances the post's `version` by 1."

    Design: Corner/errors/moderation_gates_each_return_their_own_error
    """
    seeded = _post_under_review(api)
    before = seeded["post"]
    assertions.assert_subset(
        before, {"state": k.POST_UNDER_REVIEW, "flag_count": 2, "revision_count": 0}
    )
    assert seeded["case"]["state"] == k.CASE_OPEN

    response = api.flag_post(
        seeded["post_id"],
        f.flag_payload(flag_reason="Third resident piling on."),
        make_resident_headers(seeded["neighbours"][2]["id"]),
    )
    validate_error(response, ApiErrorId.POST_NOT_PUBLISHED.value, 409)

    after = fixtures.read_post(api, seeded["post_id"])
    assertions.assert_subset(after, {"state": k.POST_UNDER_REVIEW, "flag_count": 2})
    assert after["flagged_by_resident_ids"] == before["flagged_by_resident_ids"], (
        "A refused flag must not append the flagger"
    )
    assert seeded["neighbours"][2]["id"] not in after["flagged_by_resident_ids"]
    assertions.assert_version_unchanged(after, before["version"])

    case = fixtures.read_case(api, seeded["case_id"])
    assertions.assert_subset(case, {"state": k.CASE_OPEN})
    assertions.assert_version_unchanged(case, seeded["case"]["version"])


def test_deciding_a_decided_case_reports_case_already_decided(
    api: ApiClient, clock: str
) -> None:
    """The uphold is terminal for the case even though it puts the post back in the feed.

    PRD: "Deciding a case requires the case to be `OPEN` — a `DECIDED` or `SUPERSEDED` case is terminal and is refused with `ERR_CASE_ALREADY_DECIDED` — and requires the post to be in `UNDER_REVIEW`."
    PRD: "On acceptance the case moves `OPEN → DECIDED` with `decided_by_user_id` set to the acting caller, `decided_at` stamped from the logical clock, and its `version` advanced by 1."

    Design: Corner/errors/moderation_gates_each_return_their_own_error
    """
    seeded = _post_under_review(api)

    decided = fixtures.decide_case(
        api,
        seeded["case_id"],
        MODERATOR_SECOND_HEADERS,
        decision=k.DECISION_UPHELD_PUBLISH,
        decision_note="Report is accurate and carries no discriminatory content.",
    )
    assertions.assert_subset(
        decided,
        {
            "state": k.CASE_DECIDED,
            "decision": k.DECISION_UPHELD_PUBLISH,
            "decided_by_user_id": MODERATOR_SECOND_ID,
            "opened_by_user_id": MODERATOR_ID,
            "decision_note": "Report is accurate and carries no discriminatory content.",
        },
    )
    assertions.assert_instant(decided["decided_at"], clock, "decided_at")

    response = api.decide_moderation_case(
        seeded["case_id"],
        f.decide_case_payload(
            decision=k.DECISION_REMOVE_INACCURATE, decision_note="Changed my mind after the fact."
        ),
        MODERATOR_SECOND_HEADERS,
    )
    validate_error(response, ApiErrorId.CASE_ALREADY_DECIDED.value, 409)

    case = fixtures.read_case(api, seeded["case_id"])
    assertions.assert_subset(
        case,
        {
            "state": k.CASE_DECIDED,
            "decision": k.DECISION_UPHELD_PUBLISH,
            "decision_note": "Report is accurate and carries no discriminatory content.",
            "decided_by_user_id": MODERATOR_SECOND_ID,
        },
    )
    assertions.assert_version_unchanged(case, decided["version"])

    post = fixtures.read_post(api, seeded["post_id"])
    assertions.assert_subset(post, {"state": k.POST_PUBLISHED, "flag_count": 2})
    assertions.assert_nulls(post, "auto_flag_reason")

    author = fixtures.read_resident(api, seeded["author"]["id"])
    assertions.assert_subset(
        author,
        {
            "accuracy_strike_count": 0,
            "discrimination_strike_count": 0,
            "total_strike_score": 0,
            "post_privilege_state": k.PRIVILEGE_UNRESTRICTED,
        },
    )


def test_certifying_a_certified_report_reports_report_already_certified(
    api: ApiClient, clock: str
) -> None:
    """Certification is one-way, and the refused repeat rewrites none of its stamps.

    PRD: "A report that is already `CERTIFIED` is terminal and any further attempt is refused with `ERR_REPORT_ALREADY_CERTIFIED`."
    PRD: "It then sets `variant` to `CERTIFIED`, repoints `published_share_rate_bps` at `certified_share_rate_bps`, records the `certification_note`, stamps `certified_at` from the logical clock and `certified_by_user_id` from the acting caller, and advances the report's `version` by 1."
    PRD: "In both branches a denominator of zero yields 0, a documented outcome and not an error."

    Design: Corner/errors/certifying_a_report_twice_returns_report_already_certified
    """
    agency = fixtures.onboarded_agency(api, min_device_threshold=3)
    report = fixtures.compile_report(
        api,
        agency,
        period_start_utc="2026-08-01T00:00:00Z",
        period_end_utc="2026-08-12T00:00:00Z",
    )
    assertions.assert_subset(
        report,
        {
            "variant": k.REPORT_PROVISIONAL,
            "compiled_by_user_id": PLATFORM_ADMIN_ID,
            "requests_submitted_count": 0,
            "solicitations_dispatched_count": 0,
            "version": 1,
        },
    )
    assertions.assert_bps(report["provisional_share_rate_bps"], 0, "provisional_share_rate_bps")
    assertions.assert_bps(report["certified_share_rate_bps"], 0, "certified_share_rate_bps")
    assertions.assert_bps(report["published_share_rate_bps"], 0, "published_share_rate_bps")
    assertions.assert_nulls(report, "certified_at", "certified_by_user_id", "certification_note")

    certified = fixtures.certify_report(
        api,
        report["id"],
        PLATFORM_ADMIN_SECOND_HEADERS,
        certification_note="Figures reconciled against the dispatch log.",
    )
    assertions.assert_subset(
        certified,
        {
            "variant": k.REPORT_CERTIFIED,
            "certified_by_user_id": PLATFORM_ADMIN_SECOND_ID,
            "certification_note": "Figures reconciled against the dispatch log.",
            "version": 2,
        },
    )
    assertions.assert_bps(certified["published_share_rate_bps"], 0, "published_share_rate_bps")
    assertions.assert_instant(certified["certified_at"], clock, "certified_at")

    response = api.certify_report(
        report["id"],
        f.certify_payload(certification_note="Second attempt."),
        PLATFORM_ADMIN_SECOND_HEADERS,
    )
    validate_error(response, ApiErrorId.REPORT_ALREADY_CERTIFIED.value, 409)

    after = fixtures.read_report(api, report["id"])
    assertions.assert_subset(
        after,
        {
            "variant": k.REPORT_CERTIFIED,
            "certification_note": "Figures reconciled against the dispatch log.",
            "certified_by_user_id": PLATFORM_ADMIN_SECOND_ID,
        },
    )
    assertions.assert_instant(after["certified_at"], certified["certified_at"], "certified_at")
    assertions.assert_version_unchanged(after, certified["version"])


def _clip_on_legal_hold(api: ApiClient) -> Dict[str, Any]:
    """A canvass dense enough to require an audit, escalated, with one clip shared.

    Five eligible cameras is strictly more than four, so the justification flags
    the request for audit; the auditor escalates it, and the footage shared
    afterwards is therefore created under legal hold.
    """
    world = fixtures.seed_standard_canvass(
        api, positions=((0, 10), (0, 20), (0, 30), (0, 40), (0, 50))
    )
    assertions.assert_subset(
        world["area"], {"eligible_device_count": 5, "effective_min_devices": 3, "radius_m": 500}
    )
    assert world["request"]["compliance_state"] == k.COMPLIANCE_AUDIT_FLAGGED

    auditor = fixtures.add_auditor(api, world["agency_id"])
    escalated = fixtures.escalate_audit(
        api,
        world["request_id"],
        auditor["id"],
        audit_note="Justification does not match the case number on file; escalating for review.",
    )
    assert escalated["compliance_state"] == k.COMPLIANCE_AUDIT_ESCALATED

    owner = world["households"][0]
    solicitation = fixtures.solicitation_for_device(
        api, world["request_id"], world["devices"][0]["id"]
    )
    clip = fixtures.share_footage(
        api,
        solicitation["id"],
        owner["resident_id"],
        recorded_start_utc="2026-08-08T01:00:00Z",
        duration_seconds=1800,
    )
    assertions.assert_subset(
        clip,
        {
            "status": k.CLIP_LEGAL_HOLD,
            "retention_variant": k.RETENTION_CASE_ANCHORED,
            "duration_seconds": 1800,
            "owner_resident_id": owner["resident_id"],
        },
    )
    world["auditor"] = auditor
    world["request"] = escalated
    world["owner"] = owner
    world["solicitation_id"] = solicitation["id"]
    world["clip"] = clip
    return world


def test_an_owners_revocation_of_a_held_clip_reports_clip_under_legal_hold(
    api: ApiClient, clock: str
) -> None:
    """Footage preserved by an escalation survives the owner asking for its deletion.

    PRD: "When the owning request's `compliance_state` reads `AUDIT_ESCALATED` at the moment of sharing, the clip is `CASE_ANCHORED`: its `retention_expires_at` is the **later** of the agency candidate and the portal candidate, the device candidate is **ignored entirely**, and the clip's initial `status` is `LEGAL_HOLD`."
    PRD: "From `LEGAL_HOLD`, a purge is accepted **only** with `LEGAL_RELEASE` and **only** from a `PlatformAdmin`: an owner's revocation and the sweep's retention expiry are both refused with `ERR_CLIP_UNDER_LEGAL_HOLD`, as is any attempt by a role other than `PlatformAdmin`."

    Design: Corner/errors/legal_hold_clip_resists_owner_purge_and_purge_history
    """
    world = _clip_on_legal_hold(api)
    clip = world["clip"]
    owner = world["owner"]

    response = api.purge_clip(
        clip["id"], f.purge_payload(k.PURGE_OWNER_REVOCATION), owner["headers"]
    )
    validate_error(response, ApiErrorId.CLIP_UNDER_LEGAL_HOLD.value, 409)

    after = fixtures.read_clip(api, clip["id"])
    assertions.assert_subset(
        after,
        {"status": k.CLIP_LEGAL_HOLD, "retention_variant": k.RETENTION_CASE_ANCHORED},
    )
    assertions.assert_nulls(after, "purged_at", "purge_reason")
    assertions.assert_version_unchanged(after, clip["version"])

    solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    assert solicitation["status"] == k.SOLICITATION_SHARED, (
        "A refused purge revokes nothing"
    )
    resident = fixtures.read_resident(api, owner["resident_id"])
    assertions.assert_footage_ledger(resident, lifetime=1800, retained=1800, purged=0)


def test_erasure_controls_over_held_footage_report_data_control_blocked_by_hold(
    api: ApiClient, clock: str
) -> None:
    """Neither purging history nor closing the account can erase evidence under hold.

    PRD: "If any clip of theirs sits in `LEGAL_HOLD`, both `PURGE_HISTORY` and `DEACTIVATE_ACCOUNT` are rejected with `ERR_DATA_CONTROL_BLOCKED_BY_HOLD`, because evidence preserved under an audit escalation cannot be erased by an account-level control."

    Design: Corner/errors/legal_hold_clip_resists_owner_purge_and_purge_history
    """
    world = _clip_on_legal_hold(api)
    owner = world["owner"]
    before = fixtures.read_resident(api, owner["resident_id"])

    purge_history = api.exercise_data_control(
        owner["resident_id"],
        f.data_control_payload(k.ACTION_PURGE_HISTORY, reason="Erase everything I ever shared."),
        owner["headers"],
    )
    validate_error(purge_history, ApiErrorId.DATA_CONTROL_BLOCKED_BY_HOLD.value, 409)

    deactivate = api.exercise_data_control(
        owner["resident_id"],
        f.data_control_payload(k.ACTION_DEACTIVATE_ACCOUNT, reason="Then close my account."),
        owner["headers"],
    )
    validate_error(deactivate, ApiErrorId.DATA_CONTROL_BLOCKED_BY_HOLD.value, 409)

    assert fixtures.list_data_control_actions(api, owner["resident_id"]) == [], (
        "A refused control leaves no receipt behind"
    )
    after = fixtures.read_resident(api, owner["resident_id"])
    assertions.assert_subset(
        after, {"status": k.RESIDENT_STATUS_ACTIVE, "data_sharing_opt_out": False}
    )
    assertions.assert_version_unchanged(after, before["version"])
    assertions.assert_footage_ledger(after, lifetime=1800, retained=1800, purged=0)

    clip = fixtures.read_clip(api, world["clip"]["id"])
    assertions.assert_subset(clip, {"status": k.CLIP_LEGAL_HOLD})
    assertions.assert_version_unchanged(clip, world["clip"]["version"])


def test_a_released_clip_cannot_be_purged_a_second_time(
    api: ApiClient, clock: str
) -> None:
    """The platform's legal release succeeds once, leaves consent intact, and is terminal.

    PRD: "A `LEGAL_RELEASE` purge likewise leaves the solicitation in `SHARED`."
    PRD: "A clip already in `PURGED` cannot be purged again and the attempt is refused with `ERR_CLIP_ALREADY_PURGED`."

    Design: Corner/errors/legal_hold_clip_resists_owner_purge_and_purge_history
    """
    world = _clip_on_legal_hold(api)
    clip = world["clip"]
    owner = world["owner"]

    released = fixtures.purge_clip(
        api, clip["id"], PLATFORM_ADMIN_HEADERS, purge_reason=k.PURGE_LEGAL_RELEASE
    )
    assertions.assert_subset(
        released, {"status": k.CLIP_PURGED, "purge_reason": k.PURGE_LEGAL_RELEASE}
    )
    assertions.assert_instant(released["purged_at"], clock, "purged_at")

    solicitation = fixtures.read_solicitation(api, world["solicitation_id"])
    assert solicitation["status"] == k.SOLICITATION_SHARED, (
        "A legal release is not an owner revocation, so consent stands"
    )
    resident = fixtures.read_resident(api, owner["resident_id"])
    assertions.assert_footage_ledger(resident, lifetime=1800, retained=0, purged=1800)

    response = api.purge_clip(
        clip["id"], f.purge_payload(k.PURGE_LEGAL_RELEASE), PLATFORM_ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.CLIP_ALREADY_PURGED.value, 409)

    after = fixtures.read_clip(api, clip["id"])
    assertions.assert_subset(
        after, {"status": k.CLIP_PURGED, "purge_reason": k.PURGE_LEGAL_RELEASE}
    )
    assertions.assert_instant(after["purged_at"], released["purged_at"], "purged_at")
    assertions.assert_version_unchanged(after, released["version"])
    assertions.assert_footage_ledger(
        fixtures.read_resident(api, owner["resident_id"]),
        lifetime=1800,
        retained=0,
        purged=1800,
    )
