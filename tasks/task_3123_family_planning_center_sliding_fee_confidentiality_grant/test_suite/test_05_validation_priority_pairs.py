"""Depth tests: validation-pipeline priority conflict pairs."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_tx_clinic, setup_completed_encounter, setup_patient_with_assessment,
    create_catalog_entry, create_patient, create_assessment,
    create_privacy_hold_payload,
    build_user_headers,
    TEST_USERS, FPL_INCOME_H1_PCT_265, ENC_START, ENC_END,
)

ADMIN = TEST_USERS["grant_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
PRIVACY = TEST_USERS["privacy_officer_headers"]


def _setup_completed_encounter_under_all_hold(api):
    """Completed encounter on a patient then placed under an ALL-scope hold.

    Returns (clinic, patient, encounter).
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    ctx = setup_completed_encounter(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
    )
    validate_success(
        api_client.create_privacy_hold(
            ctx["patient"]["id"],
            create_privacy_hold_payload(
                hold_start="2026-09-01T00:00:00Z",
                hold_end="2026-12-01T00:00:00Z",
                scope="ALL",
                authorized_staff_ids=["staff-allowed"],
            ),
            PRIVACY,
        ),
        201,
    )
    return clinic, ctx["patient"], ctx["encounter"]


def test_hold_gate_beats_state_error_on_patient_scoped_request(api):
    """PRD §2.10: "the privacy-hold gate (priority 4.5) runs **before** state
    checks on patient-scoped requests: a state-invalid action against a held
    patient returns `ERR_PRIVACY_HOLD_BLOCKS_ACCESS`, never the state error."

    Cancelling an already-COMPLETED encounter of a held patient as a
    non-authorized staff id returns 403 ERR_PRIVACY_HOLD_BLOCKS_ACCESS, not
    the 409 state error, and the encounter is untouched.

    Design: Difficulty/priority_pair_validation_conflict/privacy_hold_blocks_access_beats_state_error
    """
    _clinic, _patient, enc = _setup_completed_encounter_under_all_hold(api)
    blocked_headers = build_user_headers("staff-blocked", "FrontDeskStaff")
    res = api_client.cancel_encounter(enc["id"], blocked_headers)
    validate_error(res, "ERR_PRIVACY_HOLD_BLOCKS_ACCESS", expected_status=403)
    assert res.json()["data"]["error_id"] != "ERR_INVALID_STATE"


def test_hold_gate_leaves_no_side_effects_when_it_fires(api):
    """PRD §2.10: "a state-invalid action against a held patient returns
    `ERR_PRIVACY_HOLD_BLOCKS_ACCESS`, never the state error."
    PRD §3.11: "The privacy-hold management endpoints themselves — creating,
    listing, reading, and releasing holds — are never blocked by a hold".

    The blocked cancel changes nothing (the encounter remains COMPLETED);
    reading the encounter through an authorized staff id succeeds, confirming
    the hold — not deletion — caused the rejection.

    Design: Difficulty/priority_pair_validation_conflict/privacy_hold_blocks_access_beats_state_error
    """
    _clinic, _patient, enc = _setup_completed_encounter_under_all_hold(api)
    blocked_headers = build_user_headers("staff-blocked", "FrontDeskStaff")
    res = api_client.cancel_encounter(enc["id"], blocked_headers)
    validate_error(res, "ERR_PRIVACY_HOLD_BLOCKS_ACCESS", expected_status=403)

    allowed_headers = build_user_headers("staff-allowed", "FrontDeskStaff")
    enc_after = validate_success(api_client.get_encounter(enc["id"],
                                                          allowed_headers))
    assert enc_after["clinical_status"] == "COMPLETED", (
        "no side effects fired behind the hold gate"
    )


def test_out_of_scope_service_beats_telehealth_license_gap(api):
    """PRD §2.10: "an encounter creation that is simultaneously out-of-scope
    and license-gapped returns `ERR_SERVICE_OUT_OF_SCOPE` (priority 7) before
    `ERR_TELEHEALTH_LICENSE_GAP` (priority 8)."

    A TELEHEALTH request for an out-of-scope service, by a provider licensed
    only in TX for a patient in NM, returns ERR_SERVICE_OUT_OF_SCOPE — the
    referential check runs before the licensure safety check.

    Design: Difficulty/priority_pair_validation_conflict/out_of_scope_service_beats_telehealth_license_gap
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    aff = clinic["affiliate"]
    create_catalog_entry(
        aff["id"], service_code="SURGICAL_REFERRAL", in_scope=False,
        telehealth_eligible=False, full_fee_cents=100000,
    )
    patient, _asm = setup_patient_with_assessment(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
    )
    res = api_client.create_encounter(
        patient["id"],
        {
            "service_code": "SURGICAL_REFERRAL",
            "provider_id": clinic["provider"]["id"],
            "channel": "TELEHEALTH",
            "patient_location_state": "NM",
            "scheduled_start": ENC_START,
            "scheduled_end": ENC_END,
        },
        FRONT_DESK,
    )
    validate_error(res, "ERR_SERVICE_OUT_OF_SCOPE", expected_status=422)
    assert res.json()["data"]["error_id"] != "ERR_TELEHEALTH_LICENSE_GAP"


def test_scope_priority_leaves_no_encounter_behind(api):
    """PRD §2.10: "an encounter creation that is simultaneously out-of-scope
    and license-gapped returns `ERR_SERVICE_OUT_OF_SCOPE` (priority 7) before
    `ERR_TELEHEALTH_LICENSE_GAP` (priority 8)."
    PRD §3.4: "A `service_code` that is missing from the catalog, present but
    with `in_scope` false, or present but `SUSPENDED` ... rejects the
    encounter with `ERR_SERVICE_OUT_OF_SCOPE` (HTTP 422); in those cases a
    `ReferralOrder` is the correct artifact, not an encounter."

    The rejected double-violation creation persists no encounter at all.

    Design: Difficulty/priority_pair_validation_conflict/out_of_scope_service_beats_telehealth_license_gap
    """
    clinic = setup_tx_clinic(full_fee_cents=20000)
    aff = clinic["affiliate"]
    create_catalog_entry(
        aff["id"], service_code="SURGICAL_REFERRAL", in_scope=False,
        telehealth_eligible=False, full_fee_cents=100000,
    )
    patient, _asm = setup_patient_with_assessment(
        clinic, income_cents=FPL_INCOME_H1_PCT_265,
    )
    res = api_client.create_encounter(
        patient["id"],
        {
            "service_code": "SURGICAL_REFERRAL",
            "provider_id": clinic["provider"]["id"],
            "channel": "TELEHEALTH",
            "patient_location_state": "NM",
            "scheduled_start": ENC_START,
            "scheduled_end": ENC_END,
        },
        FRONT_DESK,
    )
    validate_error(res, "ERR_SERVICE_OUT_OF_SCOPE", expected_status=422)
    rows, meta = validate_paginated(
        api_client.list_patient_encounters(patient["id"], FRONT_DESK)
    )
    assert len(rows) == 0, "no encounter persisted from the rejected create"
    assert meta["total_count"] == 0
