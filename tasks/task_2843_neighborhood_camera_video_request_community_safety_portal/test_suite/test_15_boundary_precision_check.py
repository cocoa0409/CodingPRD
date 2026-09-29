"""Boundary arithmetic at the exact inclusive bound, and one unit either side.

Two metrics are exercised here. The first is the closed eligibility disc a
canvass area freezes at lock time: a camera whose integer squared distance to
the centre is exactly the radius squared is on the roster, while a camera one
metre further out is not, and the difference decides whether the canvass may
leave draft at all. The second is the character count of a written
justification, compared against the minimum the owning agency configured for
itself rather than against any portal-wide literal.

Every scenario pins the logical clock first, and every optimistic-concurrency
version is quoted from a read taken immediately before the guarded write.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
)

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_officer_headers

# The rim probe: a 500 m disc at the origin admits squared distances up to and
# including 250000. (300, 400) sits exactly on that bound; (300, 401) is one
# metre beyond it at 250801.
RIM_RADIUS_M = 500
RIM_BOUND_SQ = RIM_RADIUS_M * RIM_RADIUS_M
NEAR_POSITION: Tuple[int, int] = (0, 10)
SECOND_POSITION: Tuple[int, int] = (0, 20)
ON_RIM_POSITION: Tuple[int, int] = (300, 400)
OUTSIDE_RIM_POSITION: Tuple[int, int] = (300, 401)
NEAR_SQ = 100
SECOND_SQ = 400
OUTSIDE_SQ = 250801


def _seed_rim_probe(
    api: ApiClient, positions: List[Tuple[int, int]], *, case_number: str
) -> Dict[str, Any]:
    """One agency, one requester, one household per position, one justified request.

    The area is a 500 m disc at the origin over the standard six-hour footage
    window, locked after every camera exists so the roster is frozen over the
    whole probe set.
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = fixtures.seed_agency_with_officer(
        api,
        duty_role=k.DUTY_ROLE_REQUESTER,
        min_device_threshold=3,
        justification_min_chars=80,
    )
    households = fixtures.seed_residents_with_devices(api, positions)

    area = fixtures.create_area(
        api,
        world["agency_id"],
        world["officer_id"],
        center_x_m=0,
        center_y_m=0,
        radius_m=RIM_RADIUS_M,
        window_start_utc=fixtures.FOOTAGE_WINDOW_START,
        window_end_utc=fixtures.FOOTAGE_WINDOW_END,
        area_label="Rim probe",
    )
    locked = fixtures.lock_area(api, area["id"], world["officer_id"])

    observed_area = fixtures.read_area(api, locked["id"])
    request = fixtures.create_video_request(
        api, observed_area, world["officer_id"], case_number=case_number
    )
    request = fixtures.log_justification(
        api,
        request["id"],
        world["officer_id"],
        justification_text=f.JUSTIFICATION_150,
    )

    world["households"] = households
    world["device_ids"] = [household["device_id"] for household in households]
    world["area"] = locked
    world["area_id"] = locked["id"]
    world["request"] = request
    world["request_id"] = request["id"]
    return world


def _solicitation_page(
    api: ApiClient, officer_id: str, **filters: Any
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """One page of solicitations plus the pagination block it echoed."""
    response = api.list_solicitations(
        make_officer_headers(officer_id), f.page(limit=100, offset=0, **filters)
    )
    return validate_paginated(response)


def test_camera_exactly_on_the_disc_perimeter_joins_the_frozen_roster(
    api: ApiClient,
) -> None:
    """A camera at squared distance 250000 is eligible inside a 500 m disc.

    PRD: "And geometrically, the squared grid distance from the camera's position to the area centre is less than or equal to `radius_m` multiplied by itself — the disc is closed, so a camera exactly on the perimeter is in."
    PRD: "The number of cameras on this frozen roster is written to `eligible_device_count`, and their position in this ordering is the `dispatch_rank` each will carry when the request is actually sent."

    Design: Difficulty/boundary_precision_check/eligible_device_disc_boundary_inclusive_at_exact_radius_squared
    """
    world = _seed_rim_probe(
        api,
        [NEAR_POSITION, SECOND_POSITION, ON_RIM_POSITION, OUTSIDE_RIM_POSITION],
        case_number="CASE-RIM",
    )
    near_device, second_device, rim_device, outside_device = world["device_ids"]

    area = world["area"]
    assert area["status"] == k.AREA_STATUS_LOCKED, (
        f"Locking must move the area to LOCKED, got {area['status']!r}"
    )
    assert area["eligible_device_count"] == 3, (
        "The camera at squared distance 250000 sits exactly on the closed bound of "
        f"250000 and must count, so the roster is 3 cameras, got "
        f"{area['eligible_device_count']}"
    )
    assert area["effective_min_devices"] == 3, (
        "A 500 m disc over a six-hour window adds no bump to a base of 3, and the "
        f"global floor is also 3, got {area['effective_min_devices']}"
    )

    submitted = fixtures.submit_request(api, world["request_id"], world["officer_id"])
    assert submitted["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assert submitted["solicitation_count"] == 3, (
        "One solicitation per roster camera, so the boundary camera is asked and "
        f"the camera one metre outside is not, got {submitted['solicitation_count']}"
    )
    assertions.assert_solicitation_buckets(submitted, 3, 0, 0, 0, 0)

    rows, meta = _solicitation_page(
        api, world["officer_id"], video_request_id=world["request_id"]
    )
    assert meta["total_count"] == 3, (
        f"Expected three dispatched solicitations, got {meta['total_count']}"
    )
    assertions.assert_field_sequence(rows, "dispatch_rank", [1, 2, 3])
    assertions.assert_field_sequence(
        rows, "distance_sq_m2", [NEAR_SQ, SECOND_SQ, RIM_BOUND_SQ]
    )
    assertions.assert_field_sequence(
        rows, "device_id", [near_device, second_device, rim_device]
    )

    rim_solicitation = rows[2]
    assert rim_solicitation["distance_sq_m2"] == RIM_BOUND_SQ, (
        "The boundary camera's squared distance is the exact integer 250000, got "
        f"{rim_solicitation['distance_sq_m2']}"
    )
    assert rim_solicitation["status"] == k.SOLICITATION_SOLICITED
    assert rim_solicitation["dispatch_rank"] == 3

    outside_rows, outside_meta = _solicitation_page(
        api, world["officer_id"], device_id=outside_device
    )
    assert outside_meta["total_count"] == 0, (
        f"The camera at squared distance {OUTSIDE_SQ} is outside the closed disc "
        f"and is never solicited, got {outside_meta['total_count']} solicitations"
    )
    assert outside_rows == []

    rim_row = fixtures.read_device(api, rim_device)
    assertions.assert_subset(
        rim_row,
        {"solicitations_received_count": 1, "pending_solicitation_count": 1},
    )
    outside_row = fixtures.read_device(api, outside_device)
    assertions.assert_subset(
        outside_row,
        {"solicitations_received_count": 0, "pending_solicitation_count": 0},
    )

    final_area = fixtures.read_area(api, world["area_id"])
    assertions.assert_subset(
        final_area,
        {
            "status": k.AREA_STATUS_LOCKED,
            "eligible_device_count": 3,
            "effective_min_devices": 3,
            "derived_request_count": 1,
        },
    )


def test_camera_one_metre_beyond_the_perimeter_is_left_off_the_roster(
    api: ApiClient,
) -> None:
    """A camera at squared distance 250801 is excluded, so the canvass fails its floor.

    PRD: "And geometrically, the squared grid distance from the camera's position to the area centre is less than or equal to `radius_m` multiplied by itself — the disc is closed, so a camera exactly on the perimeter is in."
    PRD: "The frozen roster still clears the area's minimum-device threshold — otherwise `ERR_MIN_DEVICE_THRESHOLD_NOT_MET` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/eligible_device_disc_boundary_inclusive_at_exact_radius_squared
    """
    world = _seed_rim_probe(
        api,
        [NEAR_POSITION, SECOND_POSITION, OUTSIDE_RIM_POSITION],
        case_number="CASE-OUTSIDE",
    )
    near_device, second_device, outside_device = world["device_ids"]

    area = world["area"]
    assert area["eligible_device_count"] == 2, (
        f"The camera at squared distance {OUTSIDE_SQ} lies one metre beyond the "
        f"closed bound of {RIM_BOUND_SQ} and must not count, got "
        f"{area['eligible_device_count']}"
    )
    assert area["effective_min_devices"] == 3, (
        f"The device floor is 3, got {area['effective_min_devices']}"
    )

    justified = world["request"]
    assert justified["compliance_state"] == k.COMPLIANCE_JUSTIFICATION_LOGGED
    version_before = justified["version"]

    response = api.submit_video_request(
        world["request_id"], make_officer_headers(world["officer_id"])
    )
    validate_error(response, ApiErrorId.MIN_DEVICE_THRESHOLD_NOT_MET.value, 409)

    refused = fixtures.read_request(api, world["request_id"])
    assertions.assert_version_unchanged(refused, version_before)
    assertions.assert_subset(
        refused,
        {
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "solicitation_count": 0,
            "shared_clip_count": 0,
            "provisional_share_rate_bps": 0,
        },
    )
    assertions.assert_nulls(refused, "submitted_at", "expires_at")
    assertions.assert_solicitation_buckets(refused, 0, 0, 0, 0, 0)

    rows, meta = _solicitation_page(
        api, world["officer_id"], video_request_id=world["request_id"]
    )
    assert meta["total_count"] == 0, (
        "Below the device floor no solicitation is dispatched at all, got "
        f"{meta['total_count']}"
    )
    assert rows == []

    for device_id in (near_device, second_device, outside_device):
        device = fixtures.read_device(api, device_id)
        assertions.assert_subset(
            device,
            {"solicitations_received_count": 0, "pending_solicitation_count": 0},
        )

    agency = fixtures.read_agency(api, world["agency_id"])
    assertions.assert_subset(
        agency, {"open_request_count": 0, "requests_submitted_count": 0}
    )


def test_perimeter_camera_is_what_carries_the_roster_over_the_device_floor(
    api: ApiClient,
) -> None:
    """Three cameras, the farthest exactly on the rim, clear the floor of 3 and dispatch.

    PRD: "And geometrically, the squared grid distance from the camera's position to the area centre is less than or equal to `radius_m` multiplied by itself — the disc is closed, so a camera exactly on the perimeter is in."
    PRD: "For every camera solicited, `solicitations_received_count` and `pending_solicitation_count` are each incremented by 1."

    Design: Difficulty/boundary_precision_check/eligible_device_disc_boundary_inclusive_at_exact_radius_squared
    """
    world = _seed_rim_probe(
        api,
        [NEAR_POSITION, SECOND_POSITION, ON_RIM_POSITION],
        case_number="CASE-EXACT",
    )
    near_device, second_device, rim_device = world["device_ids"]

    assert world["area"]["eligible_device_count"] == 3, (
        "The rim camera at squared distance 250000 is the third eligible camera, "
        f"got {world['area']['eligible_device_count']}"
    )
    assert world["area"]["effective_min_devices"] == 3

    submitted = fixtures.submit_request(api, world["request_id"], world["officer_id"])
    assertions.assert_subset(
        submitted,
        {
            "lifecycle_state": k.LIFECYCLE_SOLICITING,
            "solicitation_count": 3,
            "pending_count": 3,
        },
    )
    assertions.assert_solicitation_buckets(submitted, 3, 0, 0, 0, 0)

    rows, meta = _solicitation_page(
        api, world["officer_id"], video_request_id=world["request_id"]
    )
    assert meta["total_count"] == 3
    assertions.assert_field_sequence(
        rows, "distance_sq_m2", [NEAR_SQ, SECOND_SQ, RIM_BOUND_SQ]
    )
    assertions.assert_field_sequence(
        rows, "device_id", [near_device, second_device, rim_device]
    )

    for device_id in (near_device, second_device, rim_device):
        device = fixtures.read_device(api, device_id)
        assertions.assert_subset(
            device,
            {"solicitations_received_count": 1, "pending_solicitation_count": 1},
        )

    agency = fixtures.read_agency(api, world["agency_id"])
    assertions.assert_subset(
        agency, {"open_request_count": 1, "requests_submitted_count": 1}
    )
    officer = fixtures.read_officer(api, world["officer_id"])
    assert officer["requests_submitted_count"] == 1, (
        "The submitting officer's own counter advances by 1, got "
        f"{officer['requests_submitted_count']}"
    )


def _seed_draft_request(
    api: ApiClient,
    *,
    justification_min_chars: int,
    name: str,
    jurisdiction_code: str,
    badge_number: str,
    full_name: str,
    centre_m: int,
    case_number: str,
) -> Dict[str, Any]:
    """An onboarded agency configured with this minimum, and one draft request.

    No camera exists anywhere near the area, so the frozen roster is empty and
    the request sits in `JUSTIFICATION_PENDING` with nothing but the length rule
    left to satisfy.
    """
    world = fixtures.seed_agency_with_officer(
        api,
        duty_role=k.DUTY_ROLE_REQUESTER,
        badge_number=badge_number,
        full_name=full_name,
        name=name,
        jurisdiction_code=jurisdiction_code,
        min_device_threshold=3,
        justification_min_chars=justification_min_chars,
    )
    area = fixtures.create_area(
        api,
        world["agency_id"],
        world["officer_id"],
        center_x_m=centre_m,
        center_y_m=centre_m,
        radius_m=RIM_RADIUS_M,
        window_start_utc=fixtures.FOOTAGE_WINDOW_START,
        window_end_utc=fixtures.FOOTAGE_WINDOW_END,
        area_label=f"{name} area",
    )
    locked = fixtures.lock_area(api, area["id"], world["officer_id"])

    observed_area = fixtures.read_area(api, locked["id"])
    request = fixtures.create_video_request(
        api, observed_area, world["officer_id"], case_number=case_number
    )

    world["area"] = locked
    world["request"] = request
    world["request_id"] = request["id"]
    return world


def _seed_alpha(api: ApiClient) -> Dict[str, Any]:
    """The agency that requires 80 characters of written justification."""
    return _seed_draft_request(
        api,
        justification_min_chars=80,
        name="Alpha County Sheriff",
        jurisdiction_code="AL-001",
        badge_number="A-100",
        full_name="Officer Alpha",
        centre_m=0,
        case_number="CASE-A",
    )


def _seed_beta(api: ApiClient) -> Dict[str, Any]:
    """The agency that requires 200 characters of written justification."""
    return _seed_draft_request(
        api,
        justification_min_chars=200,
        name="Beta Township Police",
        jurisdiction_code="BE-001",
        badge_number="B-100",
        full_name="Officer Beta",
        centre_m=9000,
        case_number="CASE-B",
    )


def test_justification_of_exactly_the_configured_minimum_length_is_logged(
    api: ApiClient,
) -> None:
    """80 characters clears an agency minimum of 80, so the bound is inclusive.

    PRD: "The text is measured **after trimming surrounding whitespace** and must be at least as long, in characters, as the owning agency's `justification_min_chars`; `statutory_basis` must be a non-empty string."
    PRD: "On success both fields are stored, `justification_logged_at` is stamped from the logical clock, and the compliance dimension moves `JUSTIFICATION_PENDING → JUSTIFICATION_LOGGED`."

    Design: Difficulty/boundary_precision_check/justification_length_boundary_at_configured_minimum_chars
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = _seed_alpha(api)
    assert len(f.JUSTIFICATION_80) == 80, "This text must be exactly 80 characters long"

    agency = fixtures.read_agency(api, world["agency_id"])
    assert agency["justification_min_chars"] == 80, (
        f"The agency configured 80, got {agency['justification_min_chars']}"
    )
    assert world["request"]["compliance_state"] == k.COMPLIANCE_JUSTIFICATION_PENDING
    version_before = world["request"]["version"]

    logged = fixtures.log_justification(
        api,
        world["request_id"],
        world["officer_id"],
        justification_text=f.JUSTIFICATION_80,
    )
    assertions.assert_version_advanced(logged, version_before)
    assertions.assert_subset(
        logged,
        {
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "justification_text": f.JUSTIFICATION_80,
            "statutory_basis": f.STATUTORY_BASIS,
        },
    )
    assertions.assert_instant(
        logged["justification_logged_at"],
        fixtures.SCENARIO_CLOCK,
        "justification_logged_at",
    )
    assertions.assert_nulls(logged, "auditor_officer_id", "audit_note", "submitted_at")

    final = fixtures.read_request(api, world["request_id"])
    assertions.assert_subset(
        final,
        {
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "justification_text": f.JUSTIFICATION_80,
        },
    )


def test_justification_one_character_short_of_the_configured_minimum_is_refused(
    api: ApiClient,
) -> None:
    """79 characters falls short of an agency minimum of 80 and is refused 422.

    PRD: "The text is measured **after trimming surrounding whitespace** and must be at least as long, in characters, as the owning agency's `justification_min_chars`; `statutory_basis` must be a non-empty string."
    PRD: "Failing either is `ERR_JUSTIFICATION_TOO_SHORT` (HTTP 422) — a request may not be logged against a token justification."

    Design: Difficulty/boundary_precision_check/justification_length_boundary_at_configured_minimum_chars
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = _seed_alpha(api)
    assert len(f.JUSTIFICATION_79) == 79, "This text must be exactly 79 characters long"

    version_before = world["request"]["version"]
    response = api.log_justification(
        world["request_id"],
        f.justification_payload(justification_text=f.JUSTIFICATION_79),
        make_officer_headers(world["officer_id"]),
    )
    validate_error(response, ApiErrorId.JUSTIFICATION_TOO_SHORT.value, 422)

    refused = fixtures.read_request(api, world["request_id"])
    assertions.assert_version_unchanged(refused, version_before)
    assertions.assert_subset(
        refused,
        {
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_PENDING,
            "lifecycle_state": k.LIFECYCLE_DRAFT,
        },
    )
    assertions.assert_nulls(
        refused, "justification_text", "statutory_basis", "justification_logged_at"
    )


def test_justification_of_exactly_a_higher_configured_minimum_is_logged(
    api: ApiClient,
) -> None:
    """200 characters clears an agency minimum of 200, inclusive at that value too.

    PRD: "The text is measured **after trimming surrounding whitespace** and must be at least as long, in characters, as the owning agency's `justification_min_chars`; `statutory_basis` must be a non-empty string."
    PRD: "On success both fields are stored, `justification_logged_at` is stamped from the logical clock, and the compliance dimension moves `JUSTIFICATION_PENDING → JUSTIFICATION_LOGGED`."

    Design: Difficulty/boundary_precision_check/justification_length_boundary_at_configured_minimum_chars
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = _seed_beta(api)
    assert len(f.JUSTIFICATION_200) == 200, (
        "This text must be exactly 200 characters long"
    )

    agency = fixtures.read_agency(api, world["agency_id"])
    assert agency["justification_min_chars"] == 200, (
        f"The agency configured 200, got {agency['justification_min_chars']}"
    )
    version_before = world["request"]["version"]

    logged = fixtures.log_justification(
        api,
        world["request_id"],
        world["officer_id"],
        justification_text=f.JUSTIFICATION_200,
    )
    assertions.assert_version_advanced(logged, version_before)
    assertions.assert_subset(
        logged,
        {
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "justification_text": f.JUSTIFICATION_200,
            "statutory_basis": f.STATUTORY_BASIS,
        },
    )
    assertions.assert_instant(
        logged["justification_logged_at"],
        fixtures.SCENARIO_CLOCK,
        "justification_logged_at",
    )

    final = fixtures.read_request(api, world["request_id"])
    assert final["compliance_state"] == k.COMPLIANCE_JUSTIFICATION_LOGGED


def test_the_minimum_length_is_read_from_the_owning_agency_row(
    api: ApiClient,
) -> None:
    """One 150-character text is refused by the agency requiring 200 and logged by the one requiring 80.

    PRD: "The text is measured **after trimming surrounding whitespace** and must be at least as long, in characters, as the owning agency's `justification_min_chars`; `statutory_basis` must be a non-empty string."
    PRD: "The written justification meets the agency's minimum length and cites a statutory basis — otherwise `ERR_JUSTIFICATION_TOO_SHORT` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/justification_length_boundary_at_configured_minimum_chars
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    alpha = _seed_alpha(api)
    beta = _seed_beta(api)
    assert len(f.JUSTIFICATION_150) == 150, (
        "This text must be exactly 150 characters long"
    )

    beta_version_before = beta["request"]["version"]
    response = api.log_justification(
        beta["request_id"],
        f.justification_payload(justification_text=f.JUSTIFICATION_150),
        make_officer_headers(beta["officer_id"]),
    )
    validate_error(response, ApiErrorId.JUSTIFICATION_TOO_SHORT.value, 422)

    beta_refused = fixtures.read_request(api, beta["request_id"])
    assertions.assert_version_unchanged(beta_refused, beta_version_before)
    assertions.assert_subset(
        beta_refused,
        {
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_PENDING,
            "lifecycle_state": k.LIFECYCLE_DRAFT,
        },
    )
    assertions.assert_nulls(
        beta_refused, "justification_text", "statutory_basis", "justification_logged_at"
    )

    alpha_logged = fixtures.log_justification(
        api,
        alpha["request_id"],
        alpha["officer_id"],
        justification_text=f.JUSTIFICATION_150,
    )
    assertions.assert_subset(
        alpha_logged,
        {
            "compliance_state": k.COMPLIANCE_JUSTIFICATION_LOGGED,
            "lifecycle_state": k.LIFECYCLE_DRAFT,
            "justification_text": f.JUSTIFICATION_150,
        },
    )

    assert fixtures.read_agency(api, alpha["agency_id"])["justification_min_chars"] == 80
    assert fixtures.read_agency(api, beta["agency_id"])["justification_min_chars"] == 200
