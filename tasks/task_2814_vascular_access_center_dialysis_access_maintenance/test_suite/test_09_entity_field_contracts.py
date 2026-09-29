"""What a freshly created row looks like, and what a malformed request leaves behind.

Every scenario here reads the create response of one collection and then reads a
second row back to prove the write either landed whole or did not land at all: seeded
defaults, computed fields the client cannot set, closed enumerations, immutable
records with no version, the two not-found rungs and the list envelope.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import NON_EXISTENT_UUID
from test_helpers import validate_error, validate_paginated, validate_success


def test_01_a_new_facility_is_seeded_at_full_trust_with_an_unscored_window(api):
    """Registration writes the posture, the five window aggregates and nothing else.

    The PRD states: "A newly registered facility starts from a position of full
    trust: its `contract_status` is `ACTIVE`, its `partnership_tier` is `SILVER`, its
    `partnership_score` is 100, every window aggregate — `referral_volume_window`,
    `raw_missed_count_window`, `grace_credit_window`, `adjusted_missed_count_window`
    and `same_day_honored_window` — is 0, its `last_scored_at` is null because no
    scoring evaluation has yet run, and its `version` is 1."

    The tier is `SILVER` rather than `GOLD`, which is what makes the first scoring
    evaluation forgive one tenth of the in-window referral volume and not one fifth.

    It also states: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/facility_creation_seeds_the_partnership_posture_and_the_success_envelope
    """
    fx.reset_clock(api)

    response = api.create_dialysis_facility(
        {"name": "Corner Dialysis One", "facility_code": "C-01"}, fx.ADMIN
    )
    facility = validate_success(response, 201)

    envelope = response.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"].startswith("req_")
    assertions.assert_instant(
        envelope["meta"]["api_request_timestamp"], "meta.api_request_timestamp"
    )

    assertions.assert_dialysis_facility(facility)
    assert facility["name"] == "Corner Dialysis One"
    assert facility["facility_code"] == "C-01"
    assert facility["contract_status"] == "ACTIVE"
    assert facility["partnership_tier"] == "SILVER"
    assert facility["partnership_score"] == 100
    assert facility["referral_volume_window"] == 0
    assert facility["raw_missed_count_window"] == 0
    assert facility["grace_credit_window"] == 0
    assert facility["adjusted_missed_count_window"] == 0
    assert facility["same_day_honored_window"] == 0
    assert facility["last_scored_at"] is None
    assert facility["version"] == 1


def test_02_a_patient_without_an_mrn_is_refused_and_leaves_no_row(api):
    """The medical record number is required input, so the whole write is discarded.

    The PRD states: "**Body shape.** Every required field present, every enum value
    inside its declared member set, every integer inside its declared domain, dates
    well-formed `YYYY-MM-DD`, datetimes well-formed ISO 8601 UTC, and `scheduled_end`
    strictly after `scheduled_start` — otherwise `ERR_INVALID_REQUEST` (422)."

    It also states: "Patients are registered by a `CenterAdmin` or an
    `AccessCoordinator` with a medical record number `mrn` that must be unique across
    all patients (`ERR_DUPLICATE_MRN` on a repeat), a `full_name`, the
    `dialysis_facility_id` of their home facility, a `dialysis_modality` and a
    `payer_program`."

    Every other declared field is present and valid, so the omission is the only
    thing the refusal can be reporting, and the facility's patient list stays empty.

    Design: Corner/entities/patient_create_without_mrn_returns_invalid_request
    """
    facility = fx.seed_facility(api, name="Corner Dialysis Two")

    refused = api.create_patient(
        {
            "full_name": "No Mrn",
            "dialysis_facility_id": facility["id"],
            "dialysis_modality": "IN_CENTER_HD",
            "payer_program": "FEE_FOR_SERVICE",
        },
        fx.ADMIN,
    )
    validate_error(refused, "ERR_INVALID_REQUEST", 422)

    _patients, meta = validate_paginated(api.list_facility_patients(facility["id"], fx.ADMIN))
    assert meta["total_count"] == 0

    settled = fx.read_facility(api, facility["id"])
    assert settled["version"] == facility["version"]


def test_03_a_received_lot_seeds_its_stock_from_the_received_quantity_alone(api):
    """The client supplies one stock number; the other three are seeded from it.

    The PRD states: "On receipt, `quantity_on_hand` is initialised to
    `received_quantity`, `quantity_reserved` is 0, `status` is `AVAILABLE` and
    `quarantine_reason` is null."

    It also states: "`received_quantity` is never mutated again; it is the anchor of
    the conservation invariant of §2.11."

    So the lot opens with a headroom equal to its whole received quantity, and every
    catalogue field crosses back exactly as submitted, the unit cost as integer cents.

    Design: Corner/entities/device_lot_creation_defaults_on_hand_to_received_and_reserved_to_zero
    """
    fx.reset_clock(api)

    lot = validate_success(
        api.create_device_lot(
            {
                "device_type": "STENT",
                "catalog_code": "STN-8X60",
                "lot_number": "CL-03",
                "expires_on": "2027-03-31",
                "received_quantity": 6,
                "unit_cost_cents": 145000,
            },
            fx.ADMIN,
        ),
        201,
    )

    assertions.assert_device_lot(lot)
    assert lot["received_quantity"] == 6
    assert lot["quantity_on_hand"] == 6
    assert lot["quantity_reserved"] == 0
    assert lot["status"] == "AVAILABLE"
    assert lot["quarantine_reason"] is None
    assert lot["device_type"] == "STENT"
    assert lot["catalog_code"] == "STN-8X60"
    assert lot["lot_number"] == "CL-03"
    assert lot["expires_on"] == "2027-03-31"
    assert lot["unit_cost_cents"] == 145000
    assert lot["version"] == 1
    assertions.assert_lot_headroom(lot, 6)


def test_04_the_patient_access_count_is_computed_and_a_submitted_value_is_discarded(api):
    """A client-supplied access_count is neither honoured nor fatal; it is simply ignored.

    The PRD states: "A new patient's `access_count` is 0 and their `version` is 1."

    It also states: "Recording it increases the owning patient's `access_count` by
    one; `access_count` counts the patient's accesses whose `status` is `PLANNED`,
    `PLACED`, `MATURING`, `IN_USE` or `DYSFUNCTIONAL`, so an access that later reaches
    `ABANDONED` decrements it again."

    The same body carries a `payer_program` the endpoint does declare, and that value
    is honoured, so the two fields separate declared input from computed output. The
    PRD states of the payer program: "That last field is quietly one of the most
    consequential values in the system: it selects which reimbursement variant every
    claim on this patient's cases will be paid under."

    Design: Corner/entities/patient_access_count_is_computed_and_client_input_ignored
    """
    facility = fx.seed_facility(api, name="Corner Dialysis Four")

    patient = validate_success(
        api.create_patient(
            {
                "mrn": "MC-04",
                "full_name": "Ada Kern",
                "dialysis_facility_id": facility["id"],
                "dialysis_modality": "IN_CENTER_HD",
                "payer_program": "BUNDLED_ESRD",
                "access_count": 9,
            },
            fx.ADMIN,
        ),
        201,
    )
    assertions.assert_patient(patient)
    assert patient["access_count"] == 0
    assert patient["payer_program"] == "BUNDLED_ESRD"
    assert patient["mrn"] == "MC-04"
    assert patient["version"] == 1

    access = fx.seed_access(
        api, patient["id"], access_type="AVF", laterality="LEFT", site="FOREARM",
        placed_on="2026-06-01",
    )
    assert access["status"] == "PLANNED"

    counted = fx.read_patient(api, patient["id"])
    assert counted["access_count"] == 1
    assert counted["payer_program"] == "BUNDLED_ESRD"


def test_05_an_unspecified_room_takes_all_three_declared_capacity_defaults(api):
    """Thirty minutes of turnover, six cases a day, three bays -- none of them supplied.

    The PRD states: "Three capacity parameters have defaults: `turnover_buffer_min`,
    the number of minutes of room turnover appended to every booking for overlap
    arithmetic, defaults to 30; `daily_case_cap`, the maximum number of non-cancelled
    cases per calendar day in this room before surge, defaults to 6; and
    `recovery_bay_count`, the number of moderate-sedation recovery bays attached to
    the room, defaults to 3."

    It also states: "Only an `ANGIO_SUITE` earns the same-day surge allowance
    described in §3.5; a plain `PROCEDURE_ROOM` never does."

    These are the exact values the booking gates read when the client omits them, so
    the defaults are load-bearing rather than cosmetic.

    Design: Corner/entities/procedure_room_optional_capacities_take_their_declared_defaults
    """
    fx.reset_clock(api)

    room = validate_success(
        api.create_procedure_room(
            {"room_code": "CR-05", "room_type": "PROCEDURE_ROOM"}, fx.ADMIN
        ),
        201,
    )

    assertions.assert_procedure_room(room)
    assert room["turnover_buffer_min"] == 30
    assert room["daily_case_cap"] == 6
    assert room["recovery_bay_count"] == 3
    assert room["room_type"] == "PROCEDURE_ROOM"
    assert room["room_code"] == "CR-05"
    assert room["version"] == 1


def test_06_a_suspected_problem_outside_the_closed_set_is_refused_before_scoring(api):
    """A plausible clinical word that is not an enum member never reaches the facility.

    The PRD states: "A `Referral` has a `suspected_problem` of `STENOSIS`,
    `THROMBOSIS`, `CATHETER_DYSFUNCTION` or `MATURATION_FAILURE`".

    It also states: "Submitting a referral immediately rescores the referring
    facility, which can itself drop the facility's contract posture and fire the whole
    posture chain within the same request."

    That second sentence is what makes the facility read decisive: a body-shape
    refusal must run before the rescoring, so `last_scored_at` is still null and the
    facility's version has not moved since registration.

    Design: Corner/entities/referral_with_unknown_suspected_problem_enum_returns_invalid_request
    """
    facility = fx.seed_facility(api, name="Corner Dialysis Six")
    patient = fx.seed_patient(api, facility["id"], mrn="MC-06", full_name="Bram Oyelaran")
    access = fx.seed_access(api, patient["id"], placed_on="2026-06-01")

    refused = api.create_referral(
        {
            "access_id": access["id"],
            "referring_facility_id": facility["id"],
            "suspected_problem": "ANEURYSM",
            "clinical_narrative": "unsupported problem code",
            "missed_treatment_count": 0,
        },
        fx.make_facility_coordinator_headers(facility["id"]),
    )
    validate_error(refused, "ERR_INVALID_REQUEST", 422)

    _referrals, meta = validate_paginated(
        api.list_referrals(fx.ADMIN, {"access_id": access["id"]})
    )
    assert meta["total_count"] == 0

    unscored = fx.read_facility(api, facility["id"])
    assert unscored["last_scored_at"] is None
    assert unscored["referral_volume_window"] == 0
    assert unscored["partnership_score"] == 100
    assert unscored["version"] == facility["version"]


OBSERVED_FIRST_AT = "2026-08-01T14:10:00Z"
OBSERVED_SECOND_AT = "2026-08-01T14:25:00Z"


def test_07_a_charted_observation_is_append_only_and_carries_no_version(api):
    """The recovery chart is a legal record: two rows, no version, no way back.

    The PRD states: "Two resource kinds are deliberately immutable and therefore carry
    only `id` and `created_at` — for these, both `updated_at` and `version` are absent
    from the response body entirely."

    It also states: "Observations are immutable legal records: the response carries
    `id` and `created_at` and no `version`, and no operation edits or deletes one."

    Charting is not itself a transition — the PRD reserves the recovery exit for the
    discharge criteria — so the case is still `RECOVERY` after both rows are written,
    and the list comes back in the declared order: "recovery-observation lists are
    ordered by `observed_at` ascending then `created_at` ascending".

    Design: Corner/entities/recovery_observation_is_immutable_with_no_version_field
    """
    bundle = fx.seed_case_in_recovery(api)

    first = validate_success(
        api.create_recovery_observation(
            bundle["procedure_id"],
            {"observed_at": OBSERVED_FIRST_AT, "aldrete_score": 8, "on_room_air": False},
            bundle["nurse_headers"],
        ),
        201,
    )
    second = validate_success(
        api.create_recovery_observation(
            bundle["procedure_id"],
            {"observed_at": OBSERVED_SECOND_AT, "aldrete_score": 9, "on_room_air": True},
            bundle["nurse_headers"],
        ),
        201,
    )

    for observation in (first, second):
        assertions.assert_recovery_observation(observation)
        assertions.assert_field_absent(observation, "version")
        assertions.assert_field_absent(observation, "updated_at")
        assert observation["procedure_id"] == bundle["procedure_id"]

    observations, meta = validate_paginated(
        api.list_recovery_observations(
            bundle["procedure_id"], bundle["nurse_headers"], {"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert [observation["id"] for observation in observations] == [first["id"], second["id"]]
    assert [observation["aldrete_score"] for observation in observations] == [8, 9]
    assert [observation["on_room_air"] for observation in observations] == [False, True]

    assert fx.read_procedure(api, bundle["procedure_id"])["clinical_status"] == "RECOVERY"


def test_08_an_unknown_procedure_path_id_reports_the_procedure_not_found_code(api):
    """The 404 belongs to the collection in the path, not to a generic catch-all.

    The PRD states: "Identifiers embedded in a request path are resolved strictly left
    to right, and the first identifier that does not resolve to a live row decides the
    response with a 404."

    It also states: "Each entity has its own not-found identifier, and the correct one
    is always the one belonging to the *segment that failed*".

    The database is deliberately non-empty — a facility exists — so the miss is a real
    lookup failure on a well-formed identifier rather than an empty-store artefact,
    and the procedure list confirms no hidden row was passed over.

    Design: Corner/entities/get_procedure_with_unknown_id_returns_not_found
    """
    fx.seed_facility(api, name="Corner Dialysis Eight")

    missing = api.get_procedure(NON_EXISTENT_UUID, fx.ADMIN)
    validate_error(missing, "ERR_PROCEDURE_NOT_FOUND", 404)

    _procedures, meta = validate_paginated(api.list_procedures(fx.ADMIN))
    assert meta["total_count"] == 0


def test_09_an_unknown_access_in_a_reading_body_reports_the_access_not_found_code(api):
    """A body foreign key that names no row is a 404 on the referenced collection.

    The PRD states: "Foreign keys supplied in a request *body* are resolved by the
    same catalogue of errors, but they are checked after body-shape validation, and
    among themselves they are checked in the order the operation declares its input
    fields."

    It also names the identifier for this key: "`ERR_ACCESS_NOT_FOUND` (for
    `access_id`, `predecessor_access_id`, `from_access_id` and `target_access_id`)".

    Every scalar in the body is inside its declared domain — flow and pressure are at
    least 0 and recirculation falls between 0.0 and 100.0 inclusive — so body shape
    cannot be what fires, and the acting facility coordinator names its own facility,
    so the scope rule cannot be either.

    Design: Corner/entities/surveillance_reading_for_an_unknown_access_returns_not_found
    """
    facility = fx.seed_facility(api, name="Corner Dialysis Nine")

    missing = api.create_surveillance_reading(
        {
            "access_id": NON_EXISTENT_UUID,
            "reported_by_facility_id": facility["id"],
            "reading_at": "2026-07-25T08:00:00Z",
            "access_flow_ml_min": 700,
            "venous_pressure_mmhg": 150,
            "recirculation_pct": 11.0,
            "kind": "URGENT",
        },
        fx.make_facility_coordinator_headers(facility["id"]),
    )
    validate_error(missing, "ERR_ACCESS_NOT_FOUND", 404)

    _readings, meta = validate_paginated(
        api.list_facility_surveillance_readings(facility["id"], fx.ADMIN)
    )
    assert meta["total_count"] == 0


def _four_referrals_across_two_accesses(api):
    """Three referrals on access A then one on access B, created in that order."""
    facility = fx.seed_facility(api, name="Corner Dialysis Ten")
    patient = fx.seed_patient(api, facility["id"], mrn="MC-10", full_name="Dov Marchetti")
    access_a = fx.seed_access(
        api, patient["id"], access_type="AVG", laterality="LEFT", site="FOREARM",
        placed_on="2026-04-01",
    )
    access_b = fx.seed_access(
        api, patient["id"], access_type="AVG", laterality="RIGHT", site="UPPER_ARM",
        placed_on="2026-04-02",
    )
    facility_headers = fx.make_facility_coordinator_headers(facility["id"])
    narratives = [
        (access_a, "STENOSIS", "page one first"),
        (access_a, "THROMBOSIS", "page one second"),
        (access_a, "STENOSIS", "page two first"),
        (access_b, "STENOSIS", "other access"),
    ]
    referrals = [
        fx.seed_referral(
            api,
            access["id"],
            facility["id"],
            facility_headers,
            suspected_problem=problem,
            clinical_narrative=narrative,
            missed_treatment_count=0,
        )
        for access, problem, narrative in narratives
    ]
    return facility, access_a, access_b, referrals


def test_10_the_referral_list_windows_the_page_while_total_count_counts_the_match(api):
    """Two pages of two, then one filtered read of three, over the same four rows.

    The PRD states: "Both are echoed in the response `meta` alongside `total_count`
    (the number of items matching the filter before the window is applied) and
    `has_more` (true when items remain beyond the current window)."

    It also states: "Unless a specific list states otherwise, resources are returned
    sorted by their creation timestamp `created_at` in ascending order."

    The filter is declared for this list — the PRD states "the referral list filters on
    `access_id`, `referring_facility_id`, `status` and `urgency`" — and narrowing to
    access A drops the total from 4 to 3, which is what proves `total_count` counts the
    filtered set rather than the page or the table.

    Design: Corner/entities/referral_listing_paginates_with_total_count_and_filters_by_access
    """
    _facility, access_a, _access_b, referrals = _four_referrals_across_two_accesses(api)
    identifiers = [referral["id"] for referral in referrals]

    response = api.list_referrals(fx.ADMIN, {"limit": 2, "offset": 0})
    first_page, first_meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert [referral["id"] for referral in first_page] == identifiers[:2]
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 4
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_referrals(fx.ADMIN, {"limit": 2, "offset": 2})
    )
    assert [referral["id"] for referral in second_page] == identifiers[2:]
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 4
    assert second_meta["has_more"] is False

    filtered, filtered_meta = validate_paginated(
        api.list_referrals(fx.ADMIN, {"access_id": access_a["id"], "limit": 10, "offset": 0})
    )
    assert filtered_meta["total_count"] == 3
    assert filtered_meta["has_more"] is False
    assert [referral["id"] for referral in filtered] == identifiers[:3]

    for referral in first_page + second_page:
        assertions.assert_referral(referral)
        assert referral["status"] == "SUBMITTED"
        assert referral["triage_score"] is None
        assert referral["triage_variant"] is None
        assert referral["urgency"] is None
        assert referral["hold_reason"] is None
        assert referral["triaged_at"] is None
