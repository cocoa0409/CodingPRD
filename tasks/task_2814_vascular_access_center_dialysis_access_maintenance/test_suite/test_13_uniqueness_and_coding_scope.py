"""Scoped keys: five uniqueness scopes, one rank scope and one medical-necessity scope.

Every guard here is about the boundary of a key rather than the value of a field, so each
scenario pairs a rejected duplicate with an accepted near-duplicate that differs only in
the dimension the scope does not cover.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

LOT_NUMBER = "CL-35"
FIRST_LOT_EXPIRES_ON = "2027-06-30"
SECOND_LOT_EXPIRES_ON = "2027-09-30"
ACCESS_PLACED_ON = "2026-03-01"
SIBLING_PLACED_ON = "2026-03-10"
IN_WINDOW_READING_AT = "2026-07-25T08:00:00Z"
STALE_READING_AT = "2026-06-20T08:00:00Z"
SIBLING_READING_AT = "2026-07-26T08:00:00Z"
NECESSITY_STATEMENT = "flow decline documented on this access"


def _one_of_each_uniquely_keyed_row(api):
    """A facility, a patient, a clinician, a room and a balloon lot, each freshly created."""
    facility = fx.seed_facility(api)
    patient = fx.seed_patient(api, facility["id"])
    clinician = fx.seed_interventionalist(api)
    room = fx.seed_room(api)
    lot = fx.seed_lot(
        api,
        "BALLOON",
        catalog_code="BAL-6X40",
        lot_number=LOT_NUMBER,
        expires_on=FIRST_LOT_EXPIRES_ON,
        received_quantity=4,
        unit_cost_cents=22000,
    )
    assertions.assert_dialysis_facility(facility)
    assertions.assert_patient(patient)
    assertions.assert_clinician(clinician)
    assertions.assert_procedure_room(room)
    assertions.assert_device_lot(lot)
    assert lot["lot_number"] == LOT_NUMBER
    return facility, patient, clinician, room, lot


def test_01_each_of_the_four_scalar_scopes_reports_its_own_identifier(api):
    """Four duplicates, four different error identifiers, no partial rows behind them.

    The PRD states: "**Scalar uniqueness** of `facility_code`, `mrn`, `npi`, `room_code`
    and the `device_type`-plus-`lot_number` pair, otherwise
    `ERR_DUPLICATE_FACILITY_CODE`, `ERR_DUPLICATE_MRN`, `ERR_DUPLICATE_NPI`,
    `ERR_DUPLICATE_ROOM_CODE` or `ERR_DUPLICATE_LOT_NUMBER` (all 409). These five apply
    respectively to facility registration, patient registration, clinician registration,
    room registration and device-lot receipt."

    Each duplicate request differs from the row it collides with in every field except the
    key, so a scope that keyed on anything wider would accept them all: the clinician
    duplicate carries a different `clinician_role` and the room duplicate a different
    `room_type`, and the PRD still refuses both.

    Design: Corner/validations/scalar_uniqueness_duplicates_are_rejected_across_five_collections
    """
    facility, patient, clinician, room, _lot = _one_of_each_uniquely_keyed_row(api)

    validate_error(
        api.create_dialysis_facility(
            {"name": "Different Name Same Code", "facility_code": facility["facility_code"]},
            fx.ADMIN,
        ),
        "ERR_DUPLICATE_FACILITY_CODE",
        409,
    )
    validate_error(
        api.create_patient(
            {
                "mrn": patient["mrn"],
                "full_name": "Different Patient",
                "dialysis_facility_id": facility["id"],
                "dialysis_modality": "HOME_HD",
                "payer_program": "BUNDLED_ESRD",
            },
            fx.ADMIN,
        ),
        "ERR_DUPLICATE_MRN",
        409,
    )
    validate_error(
        api.create_clinician(
            {
                "full_name": "Dr Other Person",
                "clinician_role": "SEDATION_RN",
                "npi": clinician["npi"],
                "moderate_sedation_credentialed": True,
                "credential_expires_on": "2027-05-31",
            },
            fx.ADMIN,
        ),
        "ERR_DUPLICATE_NPI",
        409,
    )
    validate_error(
        api.create_procedure_room(
            {"room_code": room["room_code"], "room_type": "PROCEDURE_ROOM"}, fx.ADMIN
        ),
        "ERR_DUPLICATE_ROOM_CODE",
        409,
    )

    assert fx.read_facility(api, facility["id"])["version"] == facility["version"]
    assert fx.read_patient(api, patient["id"])["version"] == patient["version"]
    assert validate_success(api.get_clinician(clinician["id"], fx.ADMIN))["clinician_role"] == (
        "INTERVENTIONALIST"
    )
    assert validate_success(api.get_procedure_room(room["id"], fx.ADMIN))["room_type"] == (
        "ANGIO_SUITE"
    )

    patients, meta = validate_paginated(api.list_facility_patients(facility["id"], fx.ADMIN))
    assert meta["total_count"] == 1
    assert [row["id"] for row in patients] == [patient["id"]]


def test_02_the_lot_number_scope_is_composite_so_a_sheath_may_reuse_it(api):
    """The same lot number is a collision under one device type and a new row under another.

    The PRD states: "The `lot_number` need only be unique *within* a device type — the same
    lot number under a different `device_type` is accepted, while a repeat of the same pair
    is refused with `ERR_DUPLICATE_LOT_NUMBER`."

    The accepted sheath is a full row in its own right, which the PRD pins: "On receipt,
    `quantity_on_hand` is initialised to `received_quantity`, `quantity_reserved` is 0,
    `status` is `AVAILABLE` and `quarantine_reason` is null."

    Design: Corner/validations/scalar_uniqueness_duplicates_are_rejected_across_five_collections
    """
    _facility, _patient, _clinician, _room, lot = _one_of_each_uniquely_keyed_row(api)

    validate_error(
        api.create_device_lot(
            {
                "device_type": "BALLOON",
                "catalog_code": "BAL-8X40",
                "lot_number": LOT_NUMBER,
                "expires_on": SECOND_LOT_EXPIRES_ON,
                "received_quantity": 9,
                "unit_cost_cents": 23000,
            },
            fx.ADMIN,
        ),
        "ERR_DUPLICATE_LOT_NUMBER",
        409,
    )

    sheath = validate_success(
        api.create_device_lot(
            {
                "device_type": "SHEATH",
                "catalog_code": "SHT-7F",
                "lot_number": LOT_NUMBER,
                "expires_on": SECOND_LOT_EXPIRES_ON,
                "received_quantity": 9,
                "unit_cost_cents": 9000,
            },
            fx.ADMIN,
        ),
        201,
    )
    assertions.assert_device_lot(sheath)
    assert sheath["device_type"] == "SHEATH"
    assert sheath["lot_number"] == LOT_NUMBER
    assert sheath["quantity_on_hand"] == 9
    assert sheath["quantity_reserved"] == 0
    assert sheath["status"] == "AVAILABLE"
    assert sheath["quarantine_reason"] is None
    assert sheath["version"] == 1

    survivor = fx.read_lot(api, lot["id"])
    assert survivor["received_quantity"] == 4
    assert survivor["expires_on"] == FIRST_LOT_EXPIRES_ON
    assert survivor["version"] == lot["version"]

    lots, meta = validate_paginated(api.list_device_lots(fx.ADMIN))
    assert meta["total_count"] == 2
    assert {row["id"] for row in lots} == {lot["id"], sheath["id"]}


def test_03_a_repeated_rank_is_refused_and_the_money_keeps_the_first_line_s_total(api):
    """Rank uniqueness is scoped to the one procedure and is checked before the money moves.

    The PRD states: "the rank must be unique among that procedure's existing lines, and a
    repeat is refused with `ERR_DUPLICATE_CODE_RANK`."

    The first line was accepted on an aborted case because the PRD states "The procedure's
    `clinical_status` must already be `DISCHARGED` or `ABORTED` and its `coding_status` must
    be `UNCODED` or `CODED`", and it set the money by the position rule: "100 percent for
    the first line, 50 percent for the second, and 25 percent for the third and every line
    after it".

    Because the duplicate line is never created, the recomputation the PRD attaches to
    "Every accepted line" never runs, so the total stays exactly where one line at 100
    percent put it.

    Design: Corner/validations/duplicate_code_rank_within_a_procedure_is_rejected
    """
    bundle = fx.seed_aborted_case(api)
    assert bundle["procedure"]["clinical_status"] == "ABORTED"

    first = fx.file_code_line(
        api,
        bundle,
        hcpcs_code="36902",
        code_family="ANGIOPLASTY",
        base_allowed_cents=180000,
        rank=1,
    )
    assertions.assert_procedure_code(first)
    assert first["is_bundled"] is False
    assert first["reduction_factor_pct"] == 100
    assert first["allowed_cents"] == 180000

    coded = fx.read_procedure(api, bundle["procedure_id"])
    assert coded["coding_status"] == "CODED"
    assert coded["allowed_amount_cents"] == 180000
    assert coded["reimbursement_variant"] == "FEE_FOR_SERVICE"

    refused = api.create_procedure_code(
        bundle["procedure_id"],
        {
            "hcpcs_code": "36903",
            "code_family": "IMAGING",
            "base_allowed_cents": 40000,
            "rank": 1,
        },
        bundle["coder_headers"],
    )
    validate_error(refused, "ERR_DUPLICATE_CODE_RANK", 409)

    codes, meta = validate_paginated(
        api.list_procedure_codes(bundle["procedure_id"], fx.ADMIN)
    )
    assert meta["total_count"] == 1
    assert [code["id"] for code in codes] == [first["id"]]
    assert codes[0]["hcpcs_code"] == "36902"

    unchanged = fx.read_procedure(api, bundle["procedure_id"])
    assert unchanged["coding_status"] == "CODED"
    assert unchanged["allowed_amount_cents"] == 180000
    assert unchanged["version"] == coded["version"]
    assertions.assert_money_ledger(unchanged)


def _an_aborted_coded_case_with_three_candidate_readings(api):
    """One coded case on access A, and three readings only one of which may support it.

    Access A carries an in-window reading on 2026-07-25 and a stale one on 2026-06-20;
    the sibling access B carries a reading of its own on 2026-07-26. The case is booked to
    begin at 13:00 on 2026-08-01, so its thirty-day lookback opens on 2026-07-02.
    """
    center = fx.seed_center(api)
    access_a = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVG",
        laterality="LEFT",
        site="FOREARM",
        placed_on=ACCESS_PLACED_ON,
    )
    access_b = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVF",
        laterality="RIGHT",
        site="UPPER_ARM",
        placed_on=SIBLING_PLACED_ON,
    )
    supporting = fx.seed_reading(
        api,
        access_a["id"],
        center["facility_id"],
        reading_at=IN_WINDOW_READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="ROUTINE",
    )
    stale = fx.seed_reading(
        api,
        access_a["id"],
        center["facility_id"],
        reading_at=STALE_READING_AT,
        access_flow_ml_min=950,
        venous_pressure_mmhg=95,
        recirculation_pct=1.0,
        kind="ROUTINE",
    )
    sibling = fx.seed_reading(
        api,
        access_b["id"],
        center["facility_id"],
        reading_at=SIBLING_READING_AT,
        access_flow_ml_min=880,
        venous_pressure_mmhg=105,
        recirculation_pct=3.0,
        kind="ROUTINE",
    )

    referral = fx.triage(
        api,
        fx.seed_referral(
            api,
            access_a["id"],
            center["facility_id"],
            suspected_problem="STENOSIS",
            clinical_narrative="rising pressures on the graft, necessity to be documented",
            missed_treatment_count=0,
        )["id"],
    )
    assert referral["triage_variant"] == "ABSOLUTE_BASED"
    assert referral["triage_score"] == 0

    procedure = fx.book_case(
        api,
        referral["id"],
        center["room_id"],
        center["operator_id"],
        referral["version"],
    )
    bundle = dict(center)
    bundle["procedure_id"] = procedure["id"]
    bundle["access_id"] = access_a["id"]
    bundle["referral_id"] = referral["id"]

    fx.set_clock(api, fx.CASE_START_CLOCK)
    fx.start_case(api, bundle)
    bundle["procedure"] = fx.abort(api, bundle)
    assert bundle["procedure"]["clinical_status"] == "ABORTED"

    fx.file_code_line(
        api,
        bundle,
        hcpcs_code="36902",
        code_family="ANGIOPLASTY",
        base_allowed_cents=180000,
        rank=1,
    )
    assert fx.read_procedure(api, procedure["id"])["coding_status"] == "CODED"
    return bundle, supporting, stale, sibling


def test_04_a_sibling_reading_and_a_stale_own_reading_fail_with_the_same_identifier(api):
    """Two different ways to miss the support window, one error identifier, nothing written.

    The PRD states: "The cited reading must sit on the procedure's own `access_id` and its
    `reading_at` must fall inside the closed thirty-day lookback window ending at the
    procedure's `scheduled_start` — that is, at or after thirty days before
    `scheduled_start` and at or before `scheduled_start`."

    It also states: "A reading on a different access, a reading after the case was
    scheduled to begin, or a reading older than the window is refused with
    `ERR_MEDICAL_NECESSITY_UNSUPPORTED`."

    The sibling reading is only six days old and the stale one is on the right access, so
    each attempt fails on exactly one of the two scopes; between them they show that both
    scopes are enforced.

    Design: Corner/validations/attestation_citing_a_reading_on_another_access_is_rejected
    """
    bundle, _supporting, stale, sibling = _an_aborted_coded_case_with_three_candidate_readings(api)

    wrong_access = api.attest_procedure(
        bundle["procedure_id"],
        {
            "medical_necessity_statement": "citing the sibling access",
            "supporting_reading_id": sibling["id"],
        },
        bundle["operator_headers"],
    )
    validate_error(wrong_access, "ERR_MEDICAL_NECESSITY_UNSUPPORTED", 422)

    too_old = api.attest_procedure(
        bundle["procedure_id"],
        {
            "medical_necessity_statement": "citing a stale reading",
            "supporting_reading_id": stale["id"],
        },
        bundle["operator_headers"],
    )
    validate_error(too_old, "ERR_MEDICAL_NECESSITY_UNSUPPORTED", 422)

    unchanged = fx.read_procedure(api, bundle["procedure_id"])
    assert unchanged["coding_status"] == "CODED"
    assert unchanged["attested_by_id"] is None
    assert unchanged["supporting_reading_id"] is None
    assert unchanged["medical_necessity_statement"] is None
    assert unchanged["allowed_amount_cents"] == 180000


def test_05_the_in_window_own_access_reading_carries_the_attestation(api):
    """The third citation differs from the first two only in which reading it names.

    The PRD states: "It records the `medical_necessity_statement` narrative and a
    `supporting_reading_id`, sets `attested_by_id` to the acting `X-User-ID`, and moves
    `CODED → ATTESTED`."

    The reading it cites was taken on 2026-07-25, seven days after the lookback opened, and
    sits on the procedure's own access; the PRD adds that "A reading taken exactly thirty
    days before, or exactly at, `scheduled_start` qualifies."

    Design: Corner/validations/attestation_citing_a_reading_on_another_access_is_rejected
    """
    bundle, supporting, stale, sibling = _an_aborted_coded_case_with_three_candidate_readings(api)
    validate_error(
        api.attest_procedure(
            bundle["procedure_id"],
            {
                "medical_necessity_statement": "citing the sibling access",
                "supporting_reading_id": sibling["id"],
            },
            bundle["operator_headers"],
        ),
        "ERR_MEDICAL_NECESSITY_UNSUPPORTED",
        422,
    )
    validate_error(
        api.attest_procedure(
            bundle["procedure_id"],
            {
                "medical_necessity_statement": "citing a stale reading",
                "supporting_reading_id": stale["id"],
            },
            bundle["operator_headers"],
        ),
        "ERR_MEDICAL_NECESSITY_UNSUPPORTED",
        422,
    )

    attested = validate_success(
        api.attest_procedure(
            bundle["procedure_id"],
            {
                "medical_necessity_statement": NECESSITY_STATEMENT,
                "supporting_reading_id": supporting["id"],
            },
            bundle["operator_headers"],
        )
    )
    assertions.assert_procedure(attested)
    assert attested["coding_status"] == "ATTESTED"
    assert attested["attested_by_id"] == bundle["operator_id"]
    assert attested["supporting_reading_id"] == supporting["id"]
    assert attested["medical_necessity_statement"] == NECESSITY_STATEMENT
    assert attested["clinical_status"] == "ABORTED"
    assert attested["allowed_amount_cents"] == 180000
