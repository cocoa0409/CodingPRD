"""Corner coverage — validations: authentication, state practice, license
field completeness, the one-requeue bound, site state match at confirm,
referral bundle at completion, and OCC staleness."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    confirm_agreement,
    create_agreement,
    create_event,
    create_event_payload,
    create_event_site_locked,
    create_vetted_site,
    create_volunteer,
    get_success_data,
    setup_event_with_open_encounter,
    setup_event_with_queued_ticket,
    submit_agreement,
    validate_error,
    validate_paginated,
    validate_success,
    verify_volunteer,
)

CO = TEST_USERS["credentialing_officer_headers"]
ED = TEST_USERS["event_director_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
QM = TEST_USERS["queue_marshal_headers"]
SL = TEST_USERS["station_lead_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request that arrives without these headers, or with a
    malformed or unrecognized role value, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    response = api.create_event(
        create_event_payload(event_code="RAM-AUTH", name="No Auth"), headers={}
    )
    validate_error(response, "ERR_UNAUTHENTICATED")


def test_state_practice_forbidden_out_of_state_license(api):
    """PRD §3.3: "either the volunteer's `license_state_code` must equal the
    event's `host_state_code` or the volunteer's discipline must be `GENERAL`,
    otherwise `ERR_STATE_PRACTICE_FORBIDDEN`."

    Design: Corner/validations/state_practice_forbidden_out_of_state_license
    """
    event = create_event_site_locked(
        event_overrides={
            "host_state_code": "VA",
            "service_date": "2027-06-12",
            "doors_open_utc": "2027-06-12T10:00:00Z",
            "total_patient_capacity": 10,
        },
        site_overrides={"state_code": "VA"},
    )
    volunteer = create_volunteer(
        discipline="DENTAL",
        license_state_code="NC",
        license_expiry_date="2028-01-01",
    )
    verify_volunteer(volunteer["id"], event["id"])
    event_now = validate_success(api.get_event(event["id"], ED))
    response = api.authorize_volunteer(
        volunteer["id"],
        {
            "clinic_event_id": event["id"],
            "expected_event_version": event_now["version"],
        },
        VC,
    )
    validate_error(response, "ERR_STATE_PRACTICE_FORBIDDEN")

    volunteer_now = validate_success(api.get_volunteer(volunteer["id"], VC))
    assert volunteer_now["status"] == "VERIFIED"


def test_clinical_volunteer_missing_license_fields_rejected(api):
    """PRD §3.3: "If the volunteer's discipline is not `GENERAL` and any of
    `license_number`, `license_state_code`, or `license_expiry_date` is empty,
    the request fails with `ERR_LICENSE_FIELDS_REQUIRED`."

    Design: Corner/validations/clinical_volunteer_missing_license_fields_rejected
    """
    event = create_event(
        event_code="RAM-LF",
        service_date="2027-06-19",
        doors_open_utc="2027-06-19T10:00:00Z",
        total_patient_capacity=10,
    )
    volunteer = create_volunteer(
        discipline="DENTAL",
        license_number="",
        license_state_code="",
        license_expiry_date="",
    )
    response = api.request_verification(
        volunteer["id"],
        {"clinic_event_id": event["id"], "reviewer_notes": "no license"},
        VC,
    )
    validate_error(response, "ERR_LICENSE_FIELDS_REQUIRED")

    volunteer_now = validate_success(api.get_volunteer(volunteer["id"], VC))
    assert volunteer_now["status"] == "REGISTERED"


def test_second_requeue_rejected(api):
    """PRD §3.6: "The marshal can requeue a `CALLED` ticket back to `QUEUED`,
    but at most once per ticket — a second requeue attempt is rejected with
    `ERR_REQUEUE_EXHAUSTED`."

    Design: Corner/validations/second_requeue_rejected
    """
    ctx = setup_event_with_queued_ticket()
    get_success_data(api.call_ticket(ctx["id"], ctx["ticket_id"], QM))
    get_success_data(api.requeue_ticket(ctx["id"], ctx["ticket_id"], QM))
    get_success_data(api.call_ticket(ctx["id"], ctx["ticket_id"], QM))

    response = api.requeue_ticket(ctx["id"], ctx["ticket_id"], QM)
    validate_error(response, "ERR_REQUEUE_EXHAUSTED")

    tickets, _ = validate_paginated(api.list_event_tickets(ctx["id"], QM))
    assert tickets[0]["status"] == "CALLED"


def test_site_state_mismatch_on_confirm(api):
    """PRD §3.2: "the site's `state_code` must equal the event's
    `host_state_code` (otherwise `ERR_SITE_STATE_MISMATCH`)".

    Design: Corner/validations/site_state_mismatch_on_confirm
    """
    site = create_vetted_site(
        site_type="ARENA",
        state_code="KY",
        square_footage=30000,
        has_loading_dock=True,
        sterilization_capable=True,
    )
    event = create_event(
        event_code="RAM-SS",
        host_state_code="TN",
        service_date="2027-07-03",
        doors_open_utc="2027-07-03T10:00:00Z",
        total_patient_capacity=10,
    )
    agreement = create_agreement(
        {"id": event["id"], "version": event["version"]},
        site["id"],
        liability_cap_cents=9_000_000,
    )
    submit_agreement(event["id"], agreement["id"])

    response = api.confirm_agreement(event["id"], agreement["id"], ED)
    validate_error(response, "ERR_SITE_STATE_MISMATCH")

    agreements, _ = validate_paginated(api.list_event_agreements(event["id"], LC))
    assert agreements[0]["status"] == "NEGOTIATING"
    event_now = validate_success(api.get_event(event["id"], ED))
    assert event_now["posture"] == "PLANNING"


def test_encounter_complete_requires_referral_when_followup(api):
    """PRD §3.6: "When the encounter's `requires_followup` is true, the
    completion request must bundle at least one referral — submitted via the
    `referrals` collection in the request — otherwise
    `ERR_REFERRAL_REQUIRED`."

    Design: Corner/validations/encounter_complete_requires_referral_when_followup
    """
    ctx = setup_event_with_open_encounter(requires_followup=True)
    response = api.complete_encounter(ctx["id"], ctx["encounter_id"], {}, SL)
    validate_error(response, "ERR_REFERRAL_REQUIRED")

    encounters, _ = validate_paginated(api.list_event_encounters(ctx["id"], SL))
    assert encounters[0]["status"] == "OPEN"


def test_stale_version_occ_rejected_412(api):
    """PRD §2.7: "if the event's current `version` has advanced past that
    value — because another agreement was confirmed, another volunteer was
    suspended, a posture recompute fired, or any other mutation occurred —
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_version_occ_rejected_412
    """
    site = create_vetted_site(
        site_type="ARENA",
        state_code="TN",
        square_footage=30000,
        has_loading_dock=True,
        sterilization_capable=True,
    )
    event = create_event(
        event_code="RAM-OCC",
        service_date="2027-07-17",
        doors_open_utc="2027-07-17T10:00:00Z",
        total_patient_capacity=10,
    )
    first = create_agreement(
        {"id": event["id"], "version": event["version"]},
        site["id"],
        host_org_name="A",
        liability_cap_cents=1_000_000,
    )
    # The first create bumped the event version, so replaying the observed
    # version is now stale.
    response = api.create_site_agreement(
        event["id"],
        {
            "site_id": site["id"],
            "host_org_name": "B",
            "liability_cap_cents": 1_000_000,
            "insurance_certificate_ref": "COCC2",
            "expected_event_version": event["version"],
        },
        LC,
    )
    validate_error(response, "ERR_STALE_VERSION")
