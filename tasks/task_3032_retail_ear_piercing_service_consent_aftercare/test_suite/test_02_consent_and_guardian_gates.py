"""Consent verification, the guardian gate and the window it opens."""
from test_helpers import (
    E,
    api_client,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    INTAKE,
    READER,
    create_consent,
    create_jurisdiction,
    create_minor_customer,
    set_clock,
)


def test_identification_mismatch_blocks_consent_verification(api):
    """PRD §3.2: "It requires that the consent is `PENDING`, that `guardian_verification_status`
    is `VERIFIED` or that the `consent_type` is `SELF`, and that the presented
    `identification_type` equals the derived `required_identification_type`; a mismatch is
    refused with `ERR_IDENTIFICATION_TYPE_MISMATCH` and HTTP 422."

    Design: Corner/validations/identification_mismatch_rejected_on_consent_verify
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    customer = create_minor_customer()
    consent = create_consent(
        customer["id"],
        jurisdiction["id"],
        consent_type="GUARDIAN_PRESENT",
        identification_type="GOVERNMENT_PHOTO_ID",
    )
    # A guardian-present instrument demands a birth certificate, not a photo id.
    assert consent["required_identification_type"] == "BIRTH_CERTIFICATE"
    get_success_data(
        api_client.record_guardian_verification(consent["id"], {"outcome": "VERIFIED"}, INTAKE)
    )

    res = api.verify_consent(consent["id"], INTAKE)
    validate_error(res, E.IDENTIFICATION_TYPE_MISMATCH, expected_status=422)

    still_pending = get_success_data(api.get_consent(consent["id"], READER))
    assert still_pending["consent_status"] == "PENDING"


def test_consent_activates_and_stamps_the_thirty_day_validity_window(api):
    """PRD §3.2: "It requires that the consent is `PENDING`, that `guardian_verification_status`
    is `VERIFIED` or that the `consent_type` is `SELF`, and that the presented
    `identification_type` equals the derived `required_identification_type`".
    PRD §3.2: "On success `consent_status` becomes `ACTIVE` and `expires_at` is set to
    `signed_at` plus the consent validity window of 30 days (`CONSENT_VALIDITY_DAYS`)."

    Design: Corner/validations/consent_verify_succeeds_when_every_gate_passes
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    customer = create_minor_customer()
    consent = create_consent(
        customer["id"],
        jurisdiction["id"],
        consent_type="GUARDIAN_PRESENT",
        identification_type="BIRTH_CERTIFICATE",
        signed_at="2026-08-30T00:00:00Z",
    )
    get_success_data(
        api_client.record_guardian_verification(consent["id"], {"outcome": "VERIFIED"}, INTAKE)
    )

    activated = validate_success(api.verify_consent(consent["id"], INTAKE), 200)
    assert activated["consent_status"] == "ACTIVE"
    assert activated["expires_at"] == "2026-09-29T00:00:00Z"
    assert activated["guardian_verification_status"] == "VERIFIED"


def test_guardian_gate_is_reported_ahead_of_the_identification_gate(api):
    """PRD §3.2: "When `consent_type` is `GUARDIAN_PRESENT` or `GUARDIAN_NOTARIZED`,
    `guardian_verification_status` must be `VERIFIED` before the consent can become `ACTIVE`".
    PRD §3.2: "This gate outranks the identification gate, so a consent that fails both
    reports the guardian error."

    Design: Corner/validations/guardian_gate_precedes_identification_gate
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    customer = create_minor_customer()
    consent = create_consent(
        customer["id"],
        jurisdiction["id"],
        consent_type="GUARDIAN_PRESENT",
        identification_type="GOVERNMENT_PHOTO_ID",
    )
    # The guardian was never verified and the identification type does not match
    # the derived requirement: both gates fail at once.
    assert consent["guardian_verification_status"] == "PENDING_VERIFICATION"

    res = api.verify_consent(consent["id"], INTAKE)
    validate_error(res, E.GUARDIAN_VERIFICATION_REQUIRED, expected_status=422)


def test_notarized_consent_is_refused_where_guardian_presence_is_mandated(api):
    """PRD §3.2: "and additionally, when the jurisdiction's `requires_guardian_presence` is true,
    a `GUARDIAN_NOTARIZED` consent is rejected outright because notarization cannot substitute
    for an attending guardian."

    Design: Corner/validations/notarized_consent_rejected_where_guardian_presence_mandated
    """
    set_clock()
    jurisdiction = validate_success(
        api_client.create_jurisdiction(
            {
                "state_code": "TX",
                "min_age_self_consent": 18,
                "min_age_with_guardian": 6,
                "min_age_absolute": 6,
                "permitted_sites": ["LOBE", "UPPER_LOBE"],
                "requires_guardian_presence": True,
                "record_retention_years": 7,
                "consent_form_version": "TX-2026",
                "sterilization_protocol_code": "AUTOCLAVE-B",
            },
            COMPLIANCE,
        ),
        201,
    )
    customer = create_minor_customer()
    consent = create_consent(
        customer["id"],
        jurisdiction["id"],
        consent_type="GUARDIAN_NOTARIZED",
        identification_type="BIRTH_CERTIFICATE",
    )
    get_success_data(
        api_client.record_guardian_verification(consent["id"], {"outcome": "VERIFIED"}, INTAKE)
    )

    res = api.verify_consent(consent["id"], INTAKE)
    validate_error(res, E.GUARDIAN_VERIFICATION_REQUIRED, expected_status=422)

    unchanged = get_success_data(api.get_consent(consent["id"], READER))
    assert unchanged["consent_status"] == "PENDING"