"""The error surface at its widest, and one triage read back three ways.

The first three scenarios probe the parts of the contract that are the same everywhere:
the not-found catalogue, the two checks that precede every other check, and the three
409 identifiers that report a state a transition is not declared from. The last one asks
whether a computed response agrees with the rows it just wrote.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import (
    build_user_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_HEADERS: dict = {}
UNKNOWN_ROLE_HEADERS = build_user_headers("test-billing-clerk-1", "BillingClerk")
CODER_HEADERS = TEST_USERS["coder_headers"]
FACILITY_CODE = "VAC-901"
ACCESS_PLACED_ON = "2026-03-01"
NECESSITY_STATEMENT = "flow decline documented on this access"


def test_01_twelve_absent_identifiers_report_twelve_distinct_not_found_codes(api):
    """Every collection owns its own 404 identifier, and none of them is a 422.

    The PRD states: "Each entity has its own not-found identifier, and the correct one is
    always the one belonging to the *segment that failed*: `ERR_FACILITY_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_ACCESS_NOT_FOUND`, `ERR_READING_NOT_FOUND`,
    `ERR_REFERRAL_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`,
    `ERR_PROCEDURE_NOT_FOUND`, `ERR_DEVICE_LOT_NOT_FOUND`, `ERR_DEVICE_USAGE_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND` and `ERR_INFECTION_EVENT_NOT_FOUND`."

    Each identifier is well-formed and simply names nothing, so the resolution rung is the
    only one that can fire: the PRD orders it as "**Path existence.** Every identifier in
    the path resolves, left to right, otherwise the segment's own not-found identifier."

    Every one of the twelve replies is also checked against the shape the PRD declares for
    a refusal, since "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."

    Design: Corner/errors/unknown_ids_across_every_collection_return_their_own_not_found_code
    """
    reads = (
        (api.get_dialysis_facility, "ERR_FACILITY_NOT_FOUND"),
        (api.get_patient, "ERR_PATIENT_NOT_FOUND"),
        (api.get_vascular_access, "ERR_ACCESS_NOT_FOUND"),
        (api.get_surveillance_reading, "ERR_READING_NOT_FOUND"),
        (api.get_referral, "ERR_REFERRAL_NOT_FOUND"),
        (api.get_procedure_room, "ERR_ROOM_NOT_FOUND"),
        (api.get_clinician, "ERR_CLINICIAN_NOT_FOUND"),
        (api.get_procedure, "ERR_PROCEDURE_NOT_FOUND"),
        (api.get_device_lot, "ERR_DEVICE_LOT_NOT_FOUND"),
        (api.get_device_usage, "ERR_DEVICE_USAGE_NOT_FOUND"),
        (api.get_conversion_plan, "ERR_PLAN_NOT_FOUND"),
        (api.get_infection_event, "ERR_INFECTION_EVENT_NOT_FOUND"),
    )
    seen = []
    for read, error_id in reads:
        response = read(NON_EXISTENT_UUID, fx.ADMIN)
        validate_error(response, error_id, 404)
        envelope = response.json()
        assert envelope["response_type"] == "error", error_id
        assert envelope["meta"]["api_request_id"], error_id
        assertions.assert_instant(
            envelope["meta"]["api_request_timestamp"], "api_request_timestamp"
        )
        seen.append(envelope["data"]["error_id"])

    assert seen == [error_id for _read, error_id in reads]
    assert len(set(seen)) == 12


def test_02_a_missing_header_and_an_unknown_role_are_refused_before_anything_else(api):
    """Two ways to fail authentication, neither of which reaches the row or the body.

    The PRD states: "A request that omits either header, or that supplies an `X-User-Role`
    value outside those six, is rejected with `ERR_UNAUTHENTICATED` (401)."

    The identifier in the path resolves to nothing and the body of the third request is
    missing a required field, yet neither the 404 nor the `ERR_INVALID_REQUEST` (422) that
    would otherwise follow is what comes back, because the PRD pins the sequence: "These
    two checks run before anything else, in that order."

    Design: Corner/errors/missing_auth_header_returns_unauthenticated_before_every_other_check
    """
    headerless_read = api.get_dialysis_facility(NON_EXISTENT_UUID, NO_HEADERS)
    validate_error(headerless_read, "ERR_UNAUTHENTICATED", 401)

    unknown_role_read = api.get_dialysis_facility(
        NON_EXISTENT_UUID, UNKNOWN_ROLE_HEADERS
    )
    validate_error(unknown_role_read, "ERR_UNAUTHENTICATED", 401)
    assert unknown_role_read.json()["data"]["error_id"] != "ERR_UNAUTHORIZED"

    headerless_write = api.create_patient(
        {
            "full_name": "Nobody At All",
            "dialysis_facility_id": NON_EXISTENT_UUID,
            "dialysis_modality": "IN_CENTER_HD",
            "payer_program": "BUNDLED_ESRD",
        },
        NO_HEADERS,
    )
    validate_error(headerless_write, "ERR_UNAUTHENTICATED", 401)
    assert headerless_write.json()["data"]["error_id"] != "ERR_INVALID_REQUEST"


def test_03_a_recognised_role_outside_the_operation_s_list_is_refused_and_writes_nothing(api):
    """The coder is authenticated beyond doubt and still may not register a facility.

    The PRD states: "A request whose role is recognized but does not appear in the
    authorized-role list of the operation being called is rejected with
    `ERR_UNAUTHORIZED` (403)."

    The refusal left no row behind, which the identical payload proves by succeeding under
    the one role the PRD authorises: "it alone may set the logical clock, run the expiry
    sweep, register facilities, clinicians, procedure rooms and device lots". Had the
    refused request created anything, the second attempt would have collided with
    `ERR_DUPLICATE_FACILITY_CODE`.

    Design: Corner/errors/missing_auth_header_returns_unauthenticated_before_every_other_check
    """
    payload = {"name": "Northgate Dialysis Partners", "facility_code": FACILITY_CODE}

    refused = api.create_dialysis_facility(payload, CODER_HEADERS)
    validate_error(refused, "ERR_UNAUTHORIZED", 403)

    accepted = validate_success(api.create_dialysis_facility(payload, fx.ADMIN), 201)
    assertions.assert_dialysis_facility(accepted)
    assert accepted["facility_code"] == FACILITY_CODE
    assert accepted["version"] == 1
    assert accepted["last_scored_at"] is None


def test_04_three_state_conflicts_on_one_scheduled_case_each_report_their_own_identifier(api):
    """A freshly booked case and an untouched lot refuse four transitions with three codes.

    The PRD groups them on one rung: "**Declared state.** The target row is in a state from
    which the requested transition is declared." Each of the three identifiers below is
    drawn from that rung, and each request satisfies every rung above it — the acting
    principal is in every case the one the operation reserves itself to.

    Discharge is refused because the PRD states it "requires `clinical_status` of
    `RECOVERY` (otherwise `ERR_PROCEDURE_NOT_IN_RECOVERY`)", and the assigned nurse is the
    one asking, so the assignment check cannot be what fired.

    Attestation is refused because "The procedure's `coding_status` must be `CODED`", and
    the primary operator is the one asking. Code filing is refused on the other half of the
    same identifier: "The procedure's `clinical_status` must already be `DISCHARGED` or
    `ABORTED` and its `coding_status` must be `UNCODED` or `CODED`, otherwise the request is
    refused with `ERR_CODING_STATE_INVALID`."

    And the lot refuses its release because the PRD states "**Release** requires the lot's
    `status` to be `QUARANTINED`", adding that "releasing one that is not `QUARANTINED`, is
    refused with `ERR_DEVICE_LOT_STATE_INVALID`."

    Design: Corner/errors/the_three_state_conflict_errors_are_each_reachable
    """
    bundle = fx.seed_scheduled_case(api, sedation_level="MODERATE")
    lot = fx.seed_lot(api, "BALLOON", received_quantity=6)
    assert bundle["procedure"]["clinical_status"] == "SCHEDULED"
    assert bundle["procedure"]["coding_status"] == "UNCODED"
    assert bundle["procedure"]["sedation_rn_id"] == bundle["nurse_id"]
    assert lot["status"] == "AVAILABLE"

    too_early_to_discharge = api.discharge_procedure(
        bundle["procedure_id"], bundle["nurse_headers"]
    )
    validate_error(too_early_to_discharge, "ERR_PROCEDURE_NOT_IN_RECOVERY", 409)

    nothing_to_attest = api.attest_procedure(
        bundle["procedure_id"],
        {
            "medical_necessity_statement": NECESSITY_STATEMENT,
            "supporting_reading_id": bundle["reading_id"],
        },
        bundle["operator_headers"],
    )
    validate_error(nothing_to_attest, "ERR_CODING_STATE_INVALID", 409)

    too_early_to_code = api.create_procedure_code(
        bundle["procedure_id"],
        {
            "hcpcs_code": "36902",
            "code_family": "ANGIOPLASTY",
            "base_allowed_cents": 180000,
            "rank": 1,
        },
        bundle["coder_headers"],
    )
    validate_error(too_early_to_code, "ERR_CODING_STATE_INVALID", 409)
    assert bundle["coder_id"] != bundle["operator_id"]
    assert bundle["coder_id"] != bundle["nurse_id"]

    nothing_to_release = api.release_device_lot(lot["id"], fx.ADMIN)
    validate_error(nothing_to_release, "ERR_DEVICE_LOT_STATE_INVALID", 409)

    unmoved = fx.read_procedure(api, bundle["procedure_id"])
    assertions.assert_procedure(unmoved)
    assert unmoved["clinical_status"] == "SCHEDULED"
    assert unmoved["coding_status"] == "UNCODED"
    assert unmoved["version"] == bundle["procedure"]["version"]
    assert unmoved["allowed_amount_cents"] == 0
    assert unmoved["attested_by_id"] is None
    assert unmoved["supporting_reading_id"] is None
    assert unmoved["discharged_at"] is None

    codes, code_meta = validate_paginated(
        api.list_procedure_codes(bundle["procedure_id"], fx.ADMIN)
    )
    assert codes == []
    assert code_meta["total_count"] == 0

    still_available = fx.read_lot(api, lot["id"])
    assert still_available["status"] == "AVAILABLE"
    assert still_available["quarantine_reason"] is None
    assert still_available["version"] == lot["version"]


def test_05_the_triage_response_and_the_reads_that_follow_it_agree_field_by_field(api):
    """One request computes a score, a variant, an urgency, an access move and nine facility
    fields, and every one of them is already visible to the next read.

    The trend arithmetic is fixed by the PRD: "The system computes a flow-decline percentage
    as the previous reading's `access_flow_ml_min` minus the latest reading's
    `access_flow_ml_min`, divided by the previous reading's `access_flow_ml_min`, then
    multiplied by 100" and "Trend points are that percentage multiplied by a weight of 1.2,
    rounded half up to a whole number, floored at 0 so an improving access earns nothing,
    and then capped at 40." A fall from 1000 to 700 is 30 percent, so 36 points.

    The latest reading is 700, and the PRD adds "An absolute-level component is added on
    top: 25 points if the latest reading's `access_flow_ml_min` is below 600 millilitres per
    minute, otherwise 12 points if it is below 800, otherwise none." The pressure and
    recirculation earn nothing, and the single missed treatment earns six, because "the
    missed-treatment burden contributes six points per missed treatment, capped at 18
    points". The total is 54, which the PRD bands: "`SAME_DAY` when `triage_score` is 70 or
    above, otherwise `NEXT_DAY` when it is 45 or above, otherwise `ROUTINE`."

    Both side effects are already committed when the response is read back: the access,
    because "that access is moved `IN_USE → DYSFUNCTIONAL`", and the facility, because
    scoring "runs on exactly five occasions: when a referral is submitted, when a referral
    is triaged, when a referral is declined, when a referral's missed-treatment count is
    updated, and when a case is discharged."

    Design: Corner/consistency_model/triage_response_and_immediate_reads_agree_within_the_same_request
    """
    center = fx.seed_center(api)
    access = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVG",
        laterality="LEFT",
        site="FOREARM",
        placed_on=ACCESS_PLACED_ON,
    )
    fx.seed_reading_pair(
        api,
        access["id"],
        center["facility_id"],
        1000,
        700,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
    )
    submitted = fx.seed_referral(
        api,
        access["id"],
        center["facility_id"],
        suspected_problem="STENOSIS",
        clinical_narrative="steady flow decline with one treatment already missed",
        missed_treatment_count=1,
    )
    assert submitted["status"] == "SUBMITTED"

    triaged = validate_success(api.triage_referral(submitted["id"], fx.COORDINATOR))
    assertions.assert_referral(triaged)
    assert triaged["status"] == "TRIAGED"
    assert triaged["triage_variant"] == "TREND_BASED"
    assert triaged["triage_score"] == 54
    assert triaged["urgency"] == "NEXT_DAY"
    assertions.assert_instant_equals(
        triaged["triaged_at"], fx.CLOCK_STARTUP_UTC, "triaged_at"
    )

    read_back = fx.read_referral(api, submitted["id"])
    assert read_back["status"] == triaged["status"]
    assert read_back["triage_variant"] == triaged["triage_variant"]
    assert read_back["triage_score"] == triaged["triage_score"]
    assert read_back["urgency"] == triaged["urgency"]
    assert read_back["version"] == triaged["version"]
    assert read_back["missed_treatment_count"] == 1
    assertions.assert_instant_equals(
        read_back["triaged_at"], triaged["triaged_at"], "triaged_at"
    )

    dysfunctional = fx.read_access(api, access["id"])
    assert dysfunctional["status"] == "DYSFUNCTIONAL"
    assert dysfunctional["version"] == access["version"] + 1

    facility = fx.read_facility(api, center["facility_id"])
    assertions.assert_dialysis_facility(facility)
    assert facility["referral_volume_window"] == 1
    assert facility["raw_missed_count_window"] == 1
    assert facility["grace_credit_window"] == 0
    assert facility["adjusted_missed_count_window"] == 1
    assert facility["same_day_honored_window"] == 0
    assert facility["partnership_score"] == 96
    assert facility["partnership_tier"] == "GOLD"
    assert facility["contract_status"] == "ACTIVE"
    assertions.assert_instant_equals(
        facility["last_scored_at"], fx.CLOCK_STARTUP_UTC, "last_scored_at"
    )
