"""Case intake: subject companies, risk tiers, and investigation creation."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH_ISO,
    TEST_USERS,
    api_client,
    assert_investigation,
    assert_subject_company,
    create_investigation,
    create_investigation_payload,
    create_subject_company_payload,
    make_staff_attorney_headers,
    parse_iso,
    reset_clock_to_epoch,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_ATTORNEY = TEST_USERS["staff_attorney_headers"]


def test_subject_company_create_applies_defaults_computed_tier_and_system_fields():
    """PRD section 3.1: "When omitted, `complaint_count_90d` defaults to 0; it
    must always be a non-negative integer." and "anything fewer than 10 is
    `STANDARD`."
    PRD section 2.5: "whose initial reading, before any operator intervention,
    is exactly `2026-09-01T00:00:00Z`".

    Design: Corner/entities/subject_company_create_applies_defaults_computed_tier_and_system_fields
    """
    # Per-test server isolation guarantees no clock call has ever been made.
    resp = api_client.create_subject_company({"legal_name": "Default Widgets LLC"}, _ADMIN)
    data = validate_success(resp, 201)
    assert resp.json()["response_type"] == "object"
    assert_subject_company(data)
    assert data["complaint_count_90d"] == 0, "omitted complaint_count_90d must default to 0"
    assert data["risk_tier"] == "STANDARD"
    assert data["version"] == 1
    assert parse_iso(data["created_at"]) == parse_iso(CLOCK_EPOCH_ISO), (
        f"created_at must be the logical clock startup reading, got {data['created_at']}"
    )
    assert parse_iso(data["updated_at"]) == parse_iso(CLOCK_EPOCH_ISO)


def test_investigation_get_roundtrips_stored_fields():
    """PRD section 3.1: "The investigation is born in `INTAKE` status, and the
    system records the opening attorney's identifier in `opened_by_user_id`."

    Design: Corner/entities/investigation_get_roundtrips_stored_fields
    """
    reset_clock_to_epoch()
    company = validate_success(
        api_client.create_subject_company(
            create_subject_company_payload(), _ADMIN
        ),
        201,
    )
    created = validate_success(
        api_client.create_investigation(
            create_investigation_payload(company["id"]),
            make_staff_attorney_headers("sa-7"),
        ),
        201,
    )
    fetched = validate_success(
        api_client.get_investigation(created["id"], _ATTORNEY), 200
    )
    assert_investigation(fetched)
    assert fetched["origin"] == "REFERRAL"
    assert fetched["summary"] == "Deceptive billing practices"
    assert fetched["subject_company_id"] == company["id"]
    assert fetched["status"] == "INTAKE"
    assert fetched["opened_by_user_id"] == "sa-7"
    assert parse_iso(fetched["created_at"]) == parse_iso(CLOCK_EPOCH_ISO)


def test_investigation_created_starts_in_intake_with_version_1():
    """PRD section 3.1: "The investigation is born in `INTAKE` status, and the
    system records the opening attorney's identifier in `opened_by_user_id`."
    PRD section 2.4: "`version` (integer): a system-managed integer that
    increments with every modification to the resource, including cascaded
    ones."

    Design: Corner/state_machines/investigation_created_starts_in_intake_with_version_1
    """
    reset_clock_to_epoch()
    company = validate_success(
        api_client.create_subject_company(
            create_subject_company_payload(), _ADMIN
        ),
        201,
    )
    data = validate_success(
        api_client.create_investigation(
            create_investigation_payload(
                company["id"], origin="COMPLAINT", summary="Billing complaints cluster"
            ),
            _ATTORNEY,
        ),
        201,
    )
    assert_investigation(data)
    assert data["status"] == "INTAKE"
    assert data["version"] == 1


def test_investigation_intake_to_negotiating_rejected():
    """PRD section 3.1: "From `INTAKE`, the attorney advances the investigation
    to `PRELIMINARY_REVIEW`, thence to `EVIDENCE_GATHERING`, and thence to
    `NEGOTIATING`, each step requested with a `target_state`." and "Any target
    state not legal from the investigation's current state is rejected with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/investigation_intake_to_negotiating_rejected
    """
    reset_clock_to_epoch()
    company = validate_success(
        api_client.create_subject_company(
            create_subject_company_payload(), _ADMIN
        ),
        201,
    )
    investigation = create_investigation(company["id"])
    resp = api_client.transition_investigation(
        investigation["id"], {"target_state": "NEGOTIATING"}, _ATTORNEY
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = validate_success(
        api_client.get_investigation(investigation["id"], _ATTORNEY), 200
    )
    assert after["status"] == "INTAKE"
    assert after["version"] == 1


def test_complaint_velocity_tier_boundaries_at_9_10_49_50():
    """PRD section 3.1: "a company with at least 50 complaints in the window is
    `CRITICAL`; one with at least 10 but fewer than 50 is `ELEVATED`; anything
    fewer than 10 is `STANDARD`. The boundaries are inclusive upward — exactly
    10 complaints is `ELEVATED`, and exactly 50 is `CRITICAL`."
    PRD section 3.1: "an `origin` of `MARKET_MONITORING` is accepted only when
    the subject company's `risk_tier` is `ELEVATED` or `CRITICAL`; against a
    `STANDARD` company the filing is rejected with
    `ERR_MONITORING_THRESHOLD_NOT_MET`."

    Design: Difficulty/boundary_precision_check/complaint_velocity_tier_boundaries_at_9_10_49_50
    """
    reset_clock_to_epoch()
    tiers = {}
    companies = {}
    for count, name in ((9, "Nine Complaints LLC"), (10, "Ten Complaints LLC"),
                        (49, "FortyNine Complaints LLC"), (50, "Fifty Complaints LLC")):
        data = validate_success(
            api_client.create_subject_company(
                {"legal_name": name, "complaint_count_90d": count}, _ADMIN
            ),
            201,
        )
        tiers[count] = data["risk_tier"]
        companies[count] = data["id"]
    assert tiers[9] == "STANDARD"
    assert tiers[10] == "ELEVATED", "exactly 10 complaints must be ELEVATED"
    assert tiers[49] == "ELEVATED"
    assert tiers[50] == "CRITICAL", "exactly 50 complaints must be CRITICAL"

    denied = api_client.create_investigation(
        create_investigation_payload(
            companies[9], origin="MARKET_MONITORING", summary="Monitoring sweep intake"
        ),
        _ATTORNEY,
    )
    validate_error(denied, ApiErrorId.ERR_MONITORING_THRESHOLD_NOT_MET)

    accepted = validate_success(
        api_client.create_investigation(
            create_investigation_payload(
                companies[10], origin="MARKET_MONITORING", summary="Monitoring sweep intake"
            ),
            _ATTORNEY,
        ),
        201,
    )
    assert accepted["status"] == "INTAKE"
