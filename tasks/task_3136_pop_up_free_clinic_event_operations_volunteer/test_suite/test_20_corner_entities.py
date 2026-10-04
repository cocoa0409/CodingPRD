"""Corner coverage — entities: creation defaults, required fields, enum
constraints, uniqueness, append-only shape, not-found, pagination envelope,
and server-owned system fields."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    complete_encounter_with_referral,
    create_event,
    create_event_payload,
    create_site_payload,
    setup_event_with_open_encounter,
    validate_error,
    validate_paginated,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
SL = TEST_USERS["station_lead_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]


def test_clinic_event_creation_applies_defaults(api):
    """PRD §3.2: "A new event starts in `PLANNING` posture with
    `confirmed_site_agreement_id` unset and all computed counters —
    `dental_chair_count`, `vision_lane_count`, `medical_bay_count`,
    `verified_volunteer_count`, `tickets_issued_count`,
    `tickets_served_count`, `unmet_demand_count`,
    `projected_servable_patients`, and `sterilization_cycles_completed` — at
    zero."

    Design: Corner/entities/clinic_event_creation_applies_defaults
    """
    event = validate_success(
        api.create_event(
            create_event_payload(
                event_code="RAM-TN-100",
                name="Corner Event",
                service_date="2027-01-16",
                doors_open_utc="2027-01-16T10:00:00Z",
                total_patient_capacity=10,
            ),
            ED,
        ),
        201,
    )
    assert event["posture"] == "PLANNING"
    assert event["version"] == 1
    assert event["tickets_issued_count"] == 0
    assert event["tickets_served_count"] == 0
    assert event["unmet_demand_count"] == 0

    fetched = validate_success(api.get_event(event["id"], ED))
    assert fetched["posture"] == "PLANNING"
    assert fetched["version"] == 1


def test_clinic_event_missing_required_field_returns_400(api):
    """PRD §3.2: "An `EventDirector` creates a `ClinicEvent` by supplying a
    human-readable unique `event_code` (for example `RAM-2026-APP-01`), a
    display `name`, the two-letter `host_state_code` where the event will
    physically be held, the ISO-8601 calendar `service_date` of the single
    service day, the `doors_open_utc` timestamp at which the patient queue
    opens (typically pre-dawn), and the `total_patient_capacity` — a hard
    ceiling on tickets issuable for the event, which must be at least 1."
    Omitting `total_patient_capacity` fails generic validation with
    `ERR_VALIDATION` (HTTP 400).

    Design: Corner/entities/clinic_event_missing_required_field_returns_400
    """
    payload = create_event_payload(
        event_code="RAM-BAD",
        name="No Capacity",
        service_date="2027-01-16",
        doors_open_utc="2027-01-16T10:00:00Z",
    )
    payload.pop("total_patient_capacity")
    response = api.create_event(payload, ED)
    validate_error(response, "ERR_VALIDATION")


def test_site_invalid_enum_rejected(api):
    """PRD §3.1: "A `LogisticsCoordinator` registers a prospective venue by
    supplying its `site_name`, a `site_type` of `ARENA`, `FAIRGROUND`, or
    `SCHOOL`" — a value outside that set is rejected with `ERR_VALIDATION`.

    Design: Corner/entities/site_invalid_enum_rejected
    """
    response = api.create_site(
        create_site_payload(site_name="Stadium", site_type="STADIUM"), LC
    )
    validate_error(response, "ERR_VALIDATION")


def test_volunteer_duplicate_email_conflict(api):
    """PRD §3.3: "a contact `email` (unique across all volunteers — a
    duplicate registration is rejected with `ERR_DUPLICATE_EMAIL`, HTTP 409)".

    Design: Corner/entities/volunteer_duplicate_email_conflict
    """
    payload = {
        "full_name": "First",
        "email": "dup@example.com",
        "discipline": "GENERAL",
        "license_number": "",
        "license_state_code": "",
        "license_expiry_date": "",
    }
    validate_success(api.create_volunteer(payload, VC), 201)
    second = dict(payload, full_name="Second")
    response = api.create_volunteer(second, VC)
    validate_error(response, "ERR_DUPLICATE_EMAIL")


def test_referral_record_immutable_no_version_field(api):
    """PRD §2.5: "Two resources deliberately deviate from this convention:
    `ReferralRecord` and `UnmetDemandReport` carry only `id` and
    `created_at`. Both `updated_at` and `version` are absent from these two
    resources, because referral records are written once inside an
    encounter-completion bundle and unmet-demand reports are append-only
    snapshots that are never modified after generation."

    Design: Corner/entities/referral_record_immutable_no_version_field
    """
    ctx = setup_event_with_open_encounter(requires_followup=True)
    complete_encounter_with_referral(ctx["id"], ctx["encounter_id"])

    referrals, _ = validate_paginated(
        api.list_encounter_referrals(ctx["id"], ctx["encounter_id"], SL)
    )
    assert len(referrals) == 1
    referral = referrals[0]
    assert referral["referral_type"] == "MEDICAL_FOLLOWUP"
    assert "id" in referral and "created_at" in referral
    assert "version" not in referral
    assert "updated_at" not in referral


def test_get_nonexistent_event_returns_404(api):
    """PRD §2.6: "The first identifier in the path that does not correspond
    to an existing resource yields `ERR_NOT_FOUND` (HTTP 404), and no later
    validation is attempted."

    Design: Corner/entities/get_nonexistent_event_returns_404
    """
    response = api.get_event(NON_EXISTENT_UUID, ED)
    validate_error(response, "ERR_NOT_FOUND")


def test_events_list_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of a list response always carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/events_list_pagination_envelope
    """
    create_event(event_code="RAM-P1", name="Page1")
    create_event(event_code="RAM-P2", name="Page2")

    data, meta = validate_paginated(
        api.list_events(ED, params={"limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_system_fields_ignore_client_input(api):
    """PRD §2.5: "The `id` is a server-minted UUID with no type prefix" and
    "`version` is an integer that starts on creation and increments on every
    mutation" — a client-supplied id or version in the create payload does not
    become the stored value.

    Design: Corner/entities/system_fields_ignore_client_input
    """
    payload = create_event_payload(event_code="RAM-SYS", name="Sys Fields")
    payload["id"] = "11111111-1111-1111-1111-111111111111"
    payload["version"] = 99
    event = validate_success(api.create_event(payload, ED), 201)
    assert event["id"] != "11111111-1111-1111-1111-111111111111"
    assert event["version"] == 1
