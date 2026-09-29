"""Three ways identity narrows a request: the attester, the facility and the FK slot.

None of the refusals below is about the role header. Two are about which principal is
acting and one is about which clinician a body names, and each is paired with the request
that differs from it in exactly that one respect.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import (
    make_facility_coordinator_headers,
    make_interventionalist_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ACCESS_PLACED_ON = "2026-03-01"
OWN_READING_AT = "2026-07-25T08:00:00Z"
INTRUDER_READING_AT = "2026-07-27T08:00:00Z"
PEER_STATEMENT = "peer attests on behalf of the operator"
OPERATOR_STATEMENT = "flow decline documented on 2026-07-25"


def test_01_attestation_by_a_peer_interventionalist_reports_its_own_identifier(api):
    """The same identity mismatch that the room steps call one thing, attestation calls another.

    The PRD states: "The acting user must be exactly the procedure's `primary_operator_id`;
    any other interventionalist — including one who was not on the case at all — is refused
    with `ERR_ATTESTATION_NOT_OPERATOR`, which is a distinct identifier from the assignment
    check applied to the room operations, so the two never compete for the same request."

    It puts the same point the other way round in the precedence list: "Attestation is
    deliberately *not* one of them; its operator-identity check lives at rung 14 and reports
    a different identifier, so the two never compete for the same request."

    The accepted attestation is filed on an aborted case, which the PRD explicitly permits:
    "A discharged case may sit `UNCODED` indefinitely, and an aborted case may still be
    coded, attested and billed."

    Design: Corner/rbac/attestation_by_a_non_operating_interventionalist_is_rejected
    """
    bundle = fx.seed_aborted_case(api)
    fx.file_code_line(
        api,
        bundle,
        hcpcs_code="36902",
        code_family="ANGIOPLASTY",
        base_allowed_cents=180000,
        rank=1,
    )
    coded = fx.read_procedure(api, bundle["procedure_id"])
    assert coded["clinical_status"] == "ABORTED"
    assert coded["coding_status"] == "CODED"

    peer = fx.seed_interventionalist(api)
    peer_headers = make_interventionalist_headers(peer["id"])
    assert peer["id"] != bundle["operator_id"]

    peer_attest = api.attest_procedure(
        bundle["procedure_id"],
        {
            "medical_necessity_statement": PEER_STATEMENT,
            "supporting_reading_id": bundle["reading_id"],
        },
        peer_headers,
    )
    validate_error(peer_attest, "ERR_ATTESTATION_NOT_OPERATOR", 403)
    assert peer_attest.json()["data"]["error_id"] != "ERR_NOT_ASSIGNED_CLINICIAN"

    unattested = fx.read_procedure(api, bundle["procedure_id"])
    assert unattested["coding_status"] == "CODED"
    assert unattested["attested_by_id"] is None
    assert unattested["supporting_reading_id"] is None
    assert unattested["medical_necessity_statement"] is None
    assert unattested["version"] == coded["version"]

    attested = validate_success(
        api.attest_procedure(
            bundle["procedure_id"],
            {
                "medical_necessity_statement": OPERATOR_STATEMENT,
                "supporting_reading_id": bundle["reading_id"],
            },
            bundle["operator_headers"],
        )
    )
    assertions.assert_procedure(attested)
    assert attested["coding_status"] == "ATTESTED"
    assert attested["attested_by_id"] == bundle["operator_id"]
    assert attested["supporting_reading_id"] == bundle["reading_id"]
    assert attested["medical_necessity_statement"] == OPERATOR_STATEMENT
    assert attested["clinical_status"] == "ABORTED"


def _one_referral_owned_by_facility_a_and_a_second_facility(api):
    """Facility A holds the patient, the access, the reading and the referral; B holds nothing."""
    center = fx.seed_center(api)
    intruder = fx.seed_facility(api)
    access = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVG",
        laterality="LEFT",
        site="FOREARM",
        placed_on=ACCESS_PLACED_ON,
    )
    fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        reading_at=OWN_READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="ROUTINE",
    )
    referral = fx.seed_referral(
        api,
        access["id"],
        center["facility_id"],
        suspected_problem="STENOSIS",
        clinical_narrative="the referral belongs to one facility and one only",
        missed_treatment_count=0,
    )
    assert intruder["id"] != center["facility_id"]
    return center, intruder, access, referral


def test_02_a_second_facility_is_out_of_scope_on_every_row_that_names_the_first(api):
    """The rows all exist; the caller simply does not speak for the facility they name.

    The PRD states: "When `X-User-Role` is `FacilityCoordinator`, `X-User-ID` must equal the
    facility identified by the request: the `referring_facility_id` supplied in a referral
    body, the `reported_by_facility_id` supplied in a surveillance-reading body, the
    `referring_facility_id` of the referral named in the path for resubmission and
    missed-treatment updates, or the facility `id` in the path of a facility read. A
    mismatch is rejected with `ERR_FACILITY_SCOPE_VIOLATION` (403)."

    Each refusal is a 403 rather than a 404, because the scope rung sits below path
    resolution: the PRD orders "**Facility scope.** The `FacilityCoordinator` ownership rule
    of §2.1, otherwise `ERR_FACILITY_SCOPE_VIOLATION`" after path existence, so the rows
    resolved before the scope was judged.

    Design: Corner/rbac/facility_coordinator_cannot_reach_another_facilitys_rows
    """
    center, intruder, access, referral = _one_referral_owned_by_facility_a_and_a_second_facility(api)
    intruder_headers = make_facility_coordinator_headers(intruder["id"])

    validate_error(
        api.get_referral(referral["id"], intruder_headers),
        "ERR_FACILITY_SCOPE_VIOLATION",
        403,
    )
    validate_error(
        api.get_dialysis_facility(center["facility_id"], intruder_headers),
        "ERR_FACILITY_SCOPE_VIOLATION",
        403,
    )
    validate_error(
        api.create_surveillance_reading(
            {
                "access_id": access["id"],
                "reported_by_facility_id": center["facility_id"],
                "reading_at": INTRUDER_READING_AT,
                "access_flow_ml_min": 880,
                "venous_pressure_mmhg": 105,
                "recirculation_pct": 3.0,
                "kind": "ROUTINE",
            },
            intruder_headers,
        ),
        "ERR_FACILITY_SCOPE_VIOLATION",
        403,
    )

    own = validate_success(
        api.get_referral(referral["id"], center["facility_headers"])
    )
    assertions.assert_referral(own)
    assert own["referring_facility_id"] == center["facility_id"]
    assert own["version"] == referral["version"]

    readings, reading_meta = validate_paginated(
        api.list_access_surveillance_readings(access["id"], fx.ADMIN)
    )
    assert reading_meta["total_count"] == 1
    assert [row["reading_at"][:10] for row in readings] == [OWN_READING_AT[:10]]

    referrals, referral_meta = validate_paginated(
        api.list_referrals(fx.ADMIN, {"referring_facility_id": center["facility_id"]})
    )
    assert referral_meta["total_count"] == 1
    assert [row["id"] for row in referrals] == [referral["id"]]


def test_03_each_clinician_slot_is_type_checked_before_the_credential_is_examined(api):
    """A coder in the operator slot and an operator in the nurse slot fail the same way.

    The PRD states: "The named primary operator must be a clinician whose `clinician_role`
    is `INTERVENTIONALIST`, and the named sedation nurse must be one whose `clinician_role`
    is `SEDATION_RN`; either mismatch is refused with `ERR_CLINICIAN_ROLE_MISMATCH`."

    The second booking would also have failed the credential test — the interventionalist it
    names in the nurse slot was registered without a credential, and the PRD says
    `moderate_sedation_credentialed` "defaults to `false` when omitted" — yet the identifier
    that comes back is the role-fit one, because the PRD puts role fit at rung 7 —
    "**Clinician role fit and case assignment.**" — and the credential test three rungs
    lower: "**Moderate-sedation credentialing**, otherwise `ERR_SEDATION_CREDENTIAL_INVALID`
    (422)."

    Neither refusal consumed the referral's version, which the accepted third booking proves
    by declaring the same value both refused calls declared.

    Design: Corner/rbac/naming_a_coder_as_the_primary_operator_is_rejected
    """
    center = fx.seed_center(api)
    triaged = fx.seed_triaged_referral(api, center)
    referral = triaged["referral"]
    assert referral["urgency"] == "ROUTINE"
    assert center["operator"]["moderate_sedation_credentialed"] is False
    assert center["nurse"]["moderate_sedation_credentialed"] is True

    def booking(**overrides):
        payload = {
            "referral_id": referral["id"],
            "room_id": center["room_id"],
            "primary_operator_id": center["operator_id"],
            "procedure_type": "ANGIOPLASTY",
            "sedation_level": "NONE",
            "scheduled_start": fx.DEFAULT_SLOT_START,
            "scheduled_end": fx.DEFAULT_SLOT_END,
            "expected_referral_version": referral["version"],
        }
        payload.update(overrides)
        return api.create_procedure(payload, fx.COORDINATOR)

    coder_as_operator = booking(primary_operator_id=center["coder_id"])
    validate_error(coder_as_operator, "ERR_CLINICIAN_ROLE_MISMATCH", 422)

    operator_as_nurse = booking(
        sedation_level="MODERATE", sedation_rn_id=center["operator_id"]
    )
    validate_error(operator_as_nurse, "ERR_CLINICIAN_ROLE_MISMATCH", 422)
    assert operator_as_nurse.json()["data"]["error_id"] != "ERR_SEDATION_CREDENTIAL_INVALID"

    unconsumed = fx.read_referral(api, referral["id"])
    assert unconsumed["status"] == "TRIAGED"
    assert unconsumed["version"] == referral["version"]

    booked = validate_success(
        booking(sedation_level="MODERATE", sedation_rn_id=center["nurse_id"]), 201
    )
    assertions.assert_procedure(booked)
    assert booked["clinical_status"] == "SCHEDULED"
    assert booked["sedation_level"] == "MODERATE"
    assert booked["sedation_rn_id"] == center["nurse_id"]
    assert booked["primary_operator_id"] == center["operator_id"]

    scheduled = fx.read_referral(api, referral["id"])
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["version"] == referral["version"] + 1
