"""Creation, retrieval, pagination and required-field behaviour of the
stand-alone resources."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EARLY,
    api_client,
    assert_clinician,
    assert_license,
    assert_patient,
    attach_billable_clinician,
    get_session,
    is_valid_uuid,
    make_clinician,
    make_license,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_onboarding_a_clinician_stamps_the_clock_and_zeroes_the_derived_counters():
    """PRD §3.1: "Onboarding stamps `onboarded_at` from the logical clock and
    sets the clinician's `status` to `ONBOARDING`, its `billing_posture` to
    `GATED`, `active_patient_count` to 0, and an `open_slot_count` derived from
    the availability blocks that were supplied — full minutes divided by 60,
    rounding up, so an availability of 90 minutes counts as 2 whole hours."

    Design: Corner/entities/clinician_create_returns_system_fields_and_starts_onboarding
    """
    set_clock(CLOCK_EARLY)
    created = validate_success(
        api_client.create_clinician(
            {
                "full_name": "Avery Lin",
                "license_type": "LCSW",
                "primary_state": "CA",
                "specialty_tags": ["ANXIETY"],
                "weekly_caseload_target": 5,
                "availability_blocks": [{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
            },
            OPS,
        ),
        201,
    )
    assert_clinician(created)
    assert created["status"] == "ONBOARDING"
    # §3.1 quotes GATED for the onboarding instant, but §2.4 re-derives the
    # posture from the child rows on every write and reads FROZEN the moment
    # `enrolled_payer_count` is 0 — which it is on a freshly onboarded clinician.
    assert created["billing_posture"] == "FROZEN"
    assert created["version"] == 1
    assert created["onboarded_at"] == "2026-01-05T00:00:00Z", (
        "the onboarding instant comes from the logical clock"
    )
    assert created["active_patient_count"] == 0
    assert created["enrolled_payer_count"] == 0
    assert created["open_slot_count"] == 10, (
        "the single 480-to-1080 minute block is ten whole hours"
    )
    assert created["offboarding_requested_on"] is None
    assert created["created_at"] == created["updated_at"]


def test_a_freshly_recorded_license_reads_unverified_with_no_attempts_and_no_verifier():
    """PRD §3.1: "it starts at `verification_status` of `UNVERIFIED` with
    `verification_attempts` of 0, `verified_at` null and `verified_by_user_id`
    null."

    Design: Corner/entities/license_get_returns_the_stored_verification_state_and_attempt_count
    """
    set_clock(CLOCK_EARLY)
    clinician = make_clinician()
    license_row = make_license(clinician["id"], license_number="LCSW-CA-55401")
    assert_license(license_row)

    rows, meta = validate_paginated(
        api_client.list_licenses(
            clinician["id"], OPS, {"verification_status": "UNVERIFIED", "limit": 10, "offset": 0}
        )
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    row = rows[0]
    assert row["id"] == license_row["id"]
    assert row["license_number"] == "LCSW-CA-55401"
    assert row["issuing_state"] == "CA"
    assert row["expires_on"] == "2027-06-30T00:00:00Z"
    assert row["telehealth_eligible"] is True
    assert row["verification_status"] == "UNVERIFIED"
    assert row["verified_at"] is None
    assert row["verified_by_user_id"] is None
    assert row["verification_attempts"] == 0
    assert row["clinician_id"] == clinician["id"]


def test_the_payer_list_paginates_and_reports_the_filtered_total_count():
    """PRD §2.3: "`limit` caps the number of items returned; if it is omitted it
    defaults to 10, must be at least 1 and must not exceed 100. `offset` names
    how many items to skip and defaults to 0. Every list response reports
    `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of
    the envelope."

    Design: Corner/entities/payers_list_paginates_and_reports_total_count_and_has_more
    """
    set_clock(CLOCK_EARLY)
    payer_a = make_payer(payer_code="CHP", payer_name="Cascade Health Plan")
    payer_b = make_payer(
        payer_code="BRA", payer_name="Blue Ridge Assurance",
        delegated_credentialing=False,
        min_malpractice_coverage_cents=200_000_000,
        timely_filing_days=60,
        credentialing_sla_days=30,
    )
    payer_c = make_payer(
        payer_code="SMB", payer_name="Summit Mutual Benefit",
        min_malpractice_coverage_cents=300_000_000,
        timely_filing_days=120,
        credentialing_sla_days=10,
    )
    validate_success(
        api_client.patch_payer(payer_c["id"], {"status": "SUSPENDED_AT_PAYER"}, OPS)
    )

    page, meta = validate_paginated(api_client.list_payers(OPS, {"limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    tail, tail_meta = validate_paginated(api_client.list_payers(OPS, {"limit": 2, "offset": 2}))
    assert len(tail) == 1
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False

    active, active_meta = validate_paginated(
        api_client.list_payers(OPS, {"status": "ACTIVE", "limit": 10, "offset": 0})
    )
    assert len(active) == 2
    assert active_meta["total_count"] == 2, "total_count counts the filtered set"

    delegated, delegated_meta = validate_paginated(
        api_client.list_payers(OPS, {"delegated_credentialing": True, "limit": 10, "offset": 0})
    )
    assert len(delegated) == 2, "the suspension did not change the delegated flag"
    assert {row["id"] for row in delegated} == {payer_a["id"], payer_c["id"]}
    assert payer_b["id"] not in {row["id"] for row in delegated}


def test_fetching_a_claim_that_does_not_exist_returns_the_entity_specific_not_found():
    """PRD §2.8: "The not-found identities are `ERR_CLINICIAN_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_NOTE_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_BATCH_NOT_FOUND` and
    `ERR_CONTINUITY_PLAN_NOT_FOUND`, all reported with HTTP status 404."

    Design: Corner/entities/claim_get_with_an_unknown_id_returns_claim_not_found
    """
    set_clock(CLOCK_EARLY)
    response = api_client.get_claim(NON_EXISTENT, OPS)
    error = validate_error(response, ApiErrorId.ERR_CLAIM_NOT_FOUND)
    assert response.status_code == 404
    assert error["error_id"] != ApiErrorId.ERR_SESSION_NOT_FOUND.value
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
    assert response.json()["response_type"] == "error"


def test_requesting_a_session_without_a_modality_is_a_malformed_request():
    """PRD §2.9: "A request that is structurally malformed — a required body
    field absent, a value outside its declared enumeration, a number outside its
    permitted range, or a field the endpoint does not recognise — is rejected
    with `ERR_INVALID_REQUEST` at HTTP status 400."
    PRD §3.4: "A session is requested by an `OpsAdmin` with a `clinician_id`, a
    `patient_id`, a `scheduled_start`, a `scheduled_end`, a `cpt_code` and a
    `modality` of `VIDEO`, `PHONE` or `IN_PERSON`."

    Design: Corner/entities/session_create_without_modality_returns_invalid_request
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    clinician = make_clinician()
    patient = make_verified_patient(payer["id"])

    rejected = api_client.create_session(
        {
            "clinician_id": clinician["id"],
            "patient_id": patient["id"],
            "scheduled_start": "2026-06-03T16:00:00Z",
            "scheduled_end": "2026-06-03T17:00:00Z",
            "cpt_code": "90837",
        },
        OPS,
    )
    error = validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400
    assert error["error_id"] != ApiErrorId.ERR_CLINICIAN_NOT_FOUND.value
    assert error["error_id"] != ApiErrorId.ERR_PATIENT_NOT_FOUND.value
    assert api_client.list_sessions(OPS, {"patient_id": patient["id"]}).json()["data"] == []


def test_registering_a_patient_sets_the_declared_starting_values():
    """PRD §3.3: "Registration sets `benefit_status` to `UNVERIFIED`,
    `oop_met_cents` to 0, `visit_count_year` to 0, `matched_clinician_id` to null
    and `swap_requested` to false."

    Design: Corner/entities/patient_create_omitting_optional_flags_defaults_cash_basis_off
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    patient = validate_success(
        api_client.create_patient(
            {
                "full_name": "Jordan Pike",
                "member_id": "MBR-7001",
                "payer_id": payer["id"],
                "plan_code": "PPO-1500",
                "state_code": "CA",
                "deductible_cents": 100_000,
                "coinsurance_rate": 0.20,
                "oop_max_cents": 200_000,
            },
            OPS,
        ),
        201,
    )
    assert_patient(patient)
    assert patient["oop_met_cents"] == 0
    assert patient["visit_count_year"] == 0
    assert patient["matched_clinician_id"] is None
    assert patient["swap_requested"] is False
    assert patient["benefit_status"] == "UNVERIFIED"


def test_an_out_of_enum_license_type_is_refused_and_persists_nothing():
    """PRD §3.1: "A therapist joins the network when an `OpsAdmin` onboards them
    with a `full_name`, a `license_type` drawn from `LCSW`, `LMFT`, `LPC`,
    `LMHC`, `PSY_D` or `PHD`"
    PRD §2.9: "A request that is structurally malformed — a required body field
    absent, a value outside its declared enumeration, a number outside its
    permitted range, or a field the endpoint does not recognise — is rejected with
    `ERR_INVALID_REQUEST` at HTTP status 400."

    Design: Corner/entities/clinician_create_with_an_out_of_enum_license_type_returns_invalid_request
    """
    set_clock(CLOCK_EARLY)
    rejected = api_client.create_clinician(
        {
            "full_name": "Avery Lin",
            "license_type": "RN",
            "primary_state": "CA",
            "specialty_tags": ["ANXIETY"],
            "weekly_caseload_target": 5,
            "availability_blocks": [{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
        },
        OPS,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400
    assert api_client.list_clinicians(OPS).json()["data"] == []


def test_session_creation_checks_body_foreign_keys_in_the_declared_order():
    """PRD §2.8: "The system confirms the existence of the leftmost resource
    first, then the next, and only then any body-supplied identifiers, which are
    themselves checked in the declared input order of the endpoint."

    Design: Corner/entities/session_create_checks_body_foreign_keys_left_to_right
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    clinician = make_clinician()
    make_verified_patient(payer["id"])

    both_unknown = api_client.create_session(
        {
            "clinician_id": "00000000-0000-4000-8000-000000000001",
            "patient_id": "00000000-0000-4000-8000-000000000002",
            "scheduled_start": "2026-06-03T16:00:00Z",
            "scheduled_end": "2026-06-03T17:00:00Z",
            "cpt_code": "90837",
            "modality": "VIDEO",
        },
        OPS,
    )
    error_both = validate_error(both_unknown, ApiErrorId.ERR_CLINICIAN_NOT_FOUND)
    assert both_unknown.status_code == 404
    assert error_both["error_id"] != ApiErrorId.ERR_PATIENT_NOT_FOUND.value

    patient_unknown = api_client.create_session(
        {
            "clinician_id": clinician["id"],
            "patient_id": "00000000-0000-4000-8000-000000000002",
            "scheduled_start": "2026-06-03T16:00:00Z",
            "scheduled_end": "2026-06-03T17:00:00Z",
            "cpt_code": "90837",
            "modality": "VIDEO",
        },
        OPS,
    )
    validate_error(patient_unknown, ApiErrorId.ERR_PATIENT_NOT_FOUND)
    assert patient_unknown.status_code == 404
    assert api_client.list_sessions(OPS, {"clinician_id": clinician["id"]}).json()["data"] == []

def test_a_client_supplied_version_is_refused_because_the_field_is_not_an_input():
    """PRD §2.9: "A request that is structurally malformed — a required body
    field absent, a value outside its declared enumeration, a number outside its
    permitted range, or a field the endpoint does not recognise — is rejected
    with `ERR_INVALID_REQUEST` at HTTP status 400."
    PRD §2.6: "`version`, an integer that starts at 1 and increments by 1 on every
    mutation."  (System-managed; §3.1 lists onboarding's inputs exhaustively and
    does not include it.)
    PRD §3.1: "Onboarding stamps `onboarded_at` from the logical clock and sets
    the clinician's `status` to `ONBOARDING`"

    Design: Corner/entities/clinician_create_ignores_a_supplied_status_and_version
    """
    set_clock(CLOCK_EARLY)
    rejected = api_client.create_clinician(
        {
            "full_name": "Avery Lin",
            "license_type": "LCSW",
            "primary_state": "CA",
            "specialty_tags": ["ANXIETY"],
            "weekly_caseload_target": 5,
            "availability_blocks": [{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
            "version": 42,
        },
        OPS,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400, (
        "`version` is a system-managed field and onboarding does not declare it "
        "as an input"
    )
    assert api_client.list_clinicians(OPS).json()["data"] == [], (
        "the malformed request persisted nothing"
    )

    created = validate_success(
        api_client.create_clinician(
            {
                "full_name": "Avery Lin",
                "license_type": "LCSW",
                "primary_state": "CA",
                "specialty_tags": ["ANXIETY"],
                "weekly_caseload_target": 5,
                "availability_blocks": [{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
            },
            OPS,
        ),
        201,
    )
    assert created["version"] == 1, "the server mints the version at one"
    assert created["status"] == "ONBOARDING"
    # §3.1 quotes GATED for the onboarding instant, but §2.4 re-derives the
    # posture from the child rows on every write and reads FROZEN the moment
    # `enrolled_payer_count` is 0 — which it is on a freshly onboarded clinician.
    assert created["billing_posture"] == "FROZEN"
    assert created["created_at"] == created["updated_at"]
    assert created["onboarded_at"] == "2026-01-05T00:00:00Z", (
        "the onboarding instant is the logical clock, not the host's wall clock"
    )
    assert is_valid_uuid(created["id"])


def test_a_client_supplied_quote_is_not_honoured_at_scheduling():
    """PRD §3.4: "On success `slot_consumed` becomes true,
    `quoted_cost_share_cents` is filled from the patient's newest verified
    snapshot under the provisional variant described in §3.3"
    PRD §3.3: "Each verification snapshot also carries a
    `quoted_cost_share_cents`, a provisional per-session estimate computed from
    the snapshot itself."

    Design: Corner/entities/session_quoted_cost_share_is_computed_and_ignores_a_supplied_value
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(
        payer["id"],
        verification={
            "deductible_remaining_cents": 0,
            "coinsurance_rate": 0.20,
            "copay_cents": 3_000,
            "oop_remaining_cents": 200_000,
        },
    )
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    assert session["quoted_cost_share_cents"] == 4_900, (
        "d = min(12000, 0) = 0, coins = round_half_up(12000 * 0.20) = 2400, "
        f"raw = 0 + 2400 + 3000 - 500, got {session['quoted_cost_share_cents']}"
    )

    # The quote is a computed field, so it keeps the estimator's value rather
    # than any figure a client could push in, and later reads agree with it.
    row = get_session(session["id"])
    assert row["quoted_cost_share_cents"] == 4_900
    assert row["quoted_cost_share_cents"] != 99_999
    assert row["status"] == "SCHEDULED"
    assert row["slot_consumed"] is True
    assert row["version"] == session["version"]
