"""Centers, donors, schedules: creation, defaults, identity, RBAC, envelope."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_center,
    make_center_with_schedule,
    make_donor,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_center_payload,
    create_donor_payload,
    create_schedule_payload,
)


# ---------------------------------------------------------------------------
# Corner/entities
# ---------------------------------------------------------------------------

def test_center_create_success_defaults_and_system_fields(api):
    """PRD §2.10: "The center's `status` begins at `OPERATIONAL`."
    PRD §2.4: the logical clock's "default instant is `2026-09-01T00:00:00Z`
    before any client sets it" and every entity timestamp "is stamped from
    the logical clock, not from the host's clock."
    PRD §2.5: "A system-managed integer that starts at 1
    and increments on every mutation of the resource, including mutations
    that originate in side effects rather than in a direct client write" (the `version` field).

    Design: Corner/entities/center_create_success_defaults_and_system_fields
    """
    set_clock("2026-09-01T09:00:00Z")
    resp = api.create_center(create_center_payload(), TEST_USERS["admin_headers"])
    data = validate_success(resp, 201)
    assert data["status"] == "OPERATIONAL"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["created_at"] == "2026-09-01T09:00:00.000Z"
    assert data["updated_at"] == "2026-09-01T09:00:00.000Z"


def test_get_nonexistent_center_returns_not_found(api):
    """PRD §2.8: "the system resolves each identifier in left-to-right order,
    returning `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
    correspond to an existing resource."

    Design: Corner/entities/get_nonexistent_center_returns_not_found
    """
    resp = api.get_center(
        "00000000-0000-0000-0000-000000000000", TEST_USERS["admin_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_donor_create_missing_required_field_returns_400(api):
    """PRD §2.9 item 22: "Required-field presence, types, enum membership,
    string-length floors, numeric ranges → `ERR_INVALID_REQUEST`."
    PRD §3.2: "A `Recorder` registers a donor by presenting
    `external_donor_ref`, `legal_first_name`, `legal_last_name`,
    `date_of_birth` (an ISO 8601 date in `YYYY-MM-DD` form), the most
    recently measured `weight_kg` in kilograms to one decimal place, and
    `home_center_id`."

    Design: Corner/entities/donor_create_missing_required_field_returns_400
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    payload = create_donor_payload(center["id"])
    del payload["external_donor_ref"]
    resp = api.register_donor(payload, TEST_USERS["recorder_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    data, meta = validate_paginated(
        api.list_donors(TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 0, "no Donor row may be created"


def test_duplicate_external_donor_ref_across_centers_rejected(api):
    """PRD §3.2: "A registration attempt carrying an `external_donor_ref`
    that is already on file — regardless of which center originally
    registered it — is rejected with `ERR_DUPLICATE_DONOR` (HTTP 409)."

    Design: Corner/entities/duplicate_external_donor_ref_across_centers_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    c1 = make_center(center_code="CSL-DAL-014")
    c2 = make_center(
        center_code="CSL-FTW-002",
        legal_name="CSL Plasma Fort Worth 002",
        screening_lanes=1,
        donor_floor_beds=1,
        observation_chairs=1,
    )
    make_donor(c1)
    resp = api.register_donor(
        create_donor_payload(c2["id"]), TEST_USERS["recorder_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DONOR, 409)


def test_underage_donor_registration_rejected(api):
    """PRD §3.2: "A donor must be at least 18 years old at registration; a
    `date_of_birth` that violates this is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/underage_donor_registration_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    resp = api.register_donor(
        create_donor_payload(
            center["id"], external_donor_ref="DL-TX-000009",
            legal_first_name="Kid", legal_last_name="Young",
            date_of_birth="2010-01-01",
        ),
        TEST_USERS["recorder_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_schedule_create_defaults_promo_fields(api):
    """PRD §3.1: "When omitted, `promo_code` defaults to null and both
    `promo_bonus_cents` and `promo_qualifying_donation_count` default to 0; a
    qualifying count of 0 disables the promo entirely."

    Design: Corner/entities/schedule_create_defaults_promo_fields
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    resp = api.create_schedule(
        center["id"],
        create_schedule_payload(center["version"]),
        TEST_USERS["admin_headers"],
    )
    data = validate_success(resp, 201)
    assert data["promo_code"] is None
    assert data["promo_bonus_cents"] == 0
    assert data["promo_qualifying_donation_count"] == 0
    assert data["schedule_status"] == "ACTIVE"
    assert data["version"] == 1


def test_donor_list_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    response envelope."

    Design: Corner/entities/donor_list_pagination_envelope
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    make_donor(center)
    make_donor(
        center,
        external_donor_ref="DL-TX-000002",
        legal_first_name="John",
        legal_last_name="Roe",
        date_of_birth="1985-05-05",
        weight_kg=80.0,
    )
    data1, meta1 = validate_paginated(
        api.list_donors(TEST_USERS["admin_headers"], params={"limit": 1, "offset": 0})
    )
    assert len(data1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0
    data2, meta2 = validate_paginated(
        api.list_donors(TEST_USERS["admin_headers"], params={"limit": 1, "offset": 1})
    )
    assert len(data2) == 1
    assert meta2["has_more"] is False
    assert data1[0]["id"] != data2[0]["id"], "pages must carry disjoint donors"


# ---------------------------------------------------------------------------
# Corner/errors: envelope shape
# ---------------------------------------------------------------------------

def test_response_envelope_success_and_error_shape(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format" with meta.api_request_id,
    response_type and data; and "All error API responses (4xx status codes)
    follow this standard envelope format" carrying data.error_id and
    data.message.

    Design: Corner/errors/response_envelope_success_and_error_shape
    """
    set_clock("2026-09-01T09:00:00Z")
    resp = api.create_center(create_center_payload(), TEST_USERS["admin_headers"])
    body = resp.json()
    assert resp.status_code == 201
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert isinstance(body["data"], dict)

    err_resp = api.get_center(
        "00000000-0000-0000-0000-000000000000", TEST_USERS["admin_headers"]
    )
    err_body = err_resp.json()
    assert err_resp.status_code == 404
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"].strip()


# ---------------------------------------------------------------------------
# Corner/validations: auth, not-found, RBAC ordering
# ---------------------------------------------------------------------------

def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Failure to provide valid headers produces an
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    resp = api_client.list_centers(headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


def test_auth_priority_beats_not_found(api):
    """PRD §2.9: "the server evaluates them in the following fixed priority
    order and reports the **first** rule that fails", where item 2 is "Role
    authorization for the operation → `ERR_INSUFFICIENT_PERMISSIONS`." and
    item 3 is "Left-to-right resolution of path-template identifiers →
    `ERR_NOT_FOUND`."

    Design: Corner/validations/auth_priority_beats_not_found
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    resp = api.decommission_center(
        "00000000-0000-0000-0000-000000000000",
        {"expected_center_version": center["version"]},
        TEST_USERS["phlebotomist_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_not_found_body_fk_screening_reference(api):
    """PRD §2.8: "a body-supplied reference (such as the `screening_visit_id`
    on a donation visit) that fails to resolve produces `ERR_NOT_FOUND`
    (HTTP 404) before any business-rule evaluation proceeds."

    Design: Corner/validations/not_found_body_fk_screening_reference
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    resp = api.schedule_donation(
        donor["id"],
        {
            "center_id": center["id"],
            "screening_visit_id": "00000000-0000-0000-0000-000000000000",
            "scheduled_for": "2026-09-02T10:00:00Z",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


# ---------------------------------------------------------------------------
# Corner/rbac
# ---------------------------------------------------------------------------

def test_medical_screener_cannot_post_sub_record(api):
    """PRD §4 lists POST `/screening-visits/{visitId}/sub-records` with
    Recorder as its only authorized role, so a MedicalScreener posting a
    sub-record acts outside the caller's designated role.
    PRD §2.1: "An attempt to perform an action outside of the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/medical_screener_cannot_post_sub_record
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = get_success_data(
        api.schedule_screening(
            donor["id"],
            {"center_id": center["id"], "scheduled_for": "2026-09-01T08:00:00Z"},
            TEST_USERS["recorder_headers"],
        )
    )
    resp = api.record_sub_record(
        visit["id"],
        {"record_type": "IDENTITY", "payload": {"document_number": "TXDL-883491"}},
        TEST_USERS["screener_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_recorder_cannot_clear_screening(api):
    """PRD §4 lists POST `/screening-visits/{visitId}/clear` with
    MedicalScreener as its only authorized role, so a Recorder attempting
    clearance acts outside the caller's designated role.
    PRD §2.1: "An attempt to perform an action outside of the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/recorder_cannot_clear_screening
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    visit = get_success_data(
        api.schedule_screening(
            donor["id"],
            {"center_id": center["id"], "scheduled_for": "2026-09-01T08:00:00Z"},
            TEST_USERS["recorder_headers"],
        )
    )
    resp = api.clear_screening(visit["id"], TEST_USERS["recorder_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_phlebotomist_cannot_file_deferral(api):
    """PRD §4 lists POST `/donors/{donorId}/deferrals` with ComplianceOfficer
    as its only authorized role, so a Phlebotomist filing a deferral acts
    outside the caller's designated role.
    PRD §2.1: "An attempt to perform an action outside of the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/phlebotomist_cannot_file_deferral
    """
    set_clock("2026-09-01T09:00:00Z")
    center = make_center()
    donor = make_donor(center)
    resp = api.file_deferral(
        donor["id"],
        {
            "reason_code": "MEDICAL_HOLD",
            "deferral_type": "TEMPORARY",
            "deferral_ends_on": "2026-09-20T00:00:00Z",
        },
        TEST_USERS["phlebotomist_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


def test_compliance_officer_cannot_create_center(api):
    """PRD §4 lists POST `/plasma-centers` with PlatformAdmin as its only
    authorized role, so a ComplianceOfficer creating a center acts outside
    the caller's designated role.
    PRD §2.1: "An attempt to perform an action outside of the caller's
    designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_create_center
    """
    set_clock("2026-09-01T09:00:00Z")
    resp = api.create_center(
        create_center_payload(), TEST_USERS["compliance_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
