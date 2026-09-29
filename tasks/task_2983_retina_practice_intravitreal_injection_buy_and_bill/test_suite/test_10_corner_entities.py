"""
Entity-surface breadth: creation, retrieval, listing, defaults, computed fields,
system fields, type constraints, immutability and parent integrity.
"""

from prd_bench_local_runner.testing import is_valid_uuid, validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_envelope_shape,
    assert_error_envelope,
    assert_immutable_entity_fields,
    assert_instant_equals,
    assert_system_fields,
    assert_vial_counters,
    list_ids,
    validate_list,
)
from test_helpers import factories as f
from test_helpers.test_users import specialist_headers

UNKNOWN_LOT_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_PATIENT_ID = "22222222-2222-4222-8222-222222222222"


def test_receipt_seeds_five_in_stock_vials_and_one_version(breadth, tech):
    """
    Booking a lot of five vials answers with `vials_on_hand` 5, every other
    counter 0, and five `IN_STOCK` vial rows behind it.

    The PRD makes receipt the only moment vials exist: "Receipt is the only moment
    vials come into existence: exactly `vials_received` vial rows are created, all
    in `IN_STOCK` ... Immediately after receipt `vials_on_hand` equals
    `vials_received` and every other vial counter on the lot is 0. A lot begins in
    `AVAILABLE` with `quarantine_reason` null, `carrying_cost_accrued_cents` at 0,
    `last_swept_at` null, and `related_endophthalmitis_count` at 0."  The row's own
    `version` "starts at 1 when the row is created".

    Design: Corner/entities/corner_create_drug_lot_returns_seeded_counters_and_version_one
    """
    drug = breadth.drug_ref

    response = breadth.api.create_drug_lot(
        f.lot_payload(
            drug_id=drug["id"],
            lot_number="RX-9001",
            expiration_date="2027-06-30T00:00:00Z",
            received_date="2026-07-01T00:00:00Z",
            unit_acquisition_cost_cents=132000,
            vials_received=5,
        ),
        tech,
    )
    lot = validate_success(response, 201)

    assert lot["status"] == "AVAILABLE"
    assert lot["version"] == 1
    assert lot["quarantine_reason"] is None
    assert lot["carrying_cost_accrued_cents"] == 0
    assert lot["last_swept_at"] is None
    assert lot["related_endophthalmitis_count"] == 0
    assert_vial_counters(
        lot,
        vials_on_hand=5,
        vials_reserved=0,
        vials_administered=0,
        vials_quarantined=0,
        vials_returned=0,
        vials_expired=0,
    )

    rows, meta = validate_list(
        breadth.api.list_vials(tech, f.page_params(drug_lot_id=lot["id"], limit=100))
    )
    assert meta["total_count"] == 5
    assert {row["status"] for row in rows} == {"IN_STOCK"}
    assert all(row["reserved_for_encounter_id"] is None for row in rows)


def test_reading_a_lot_back_echoes_every_stored_field_in_an_object_envelope(breadth, tech):
    """
    The single-resource read returns the stored row inside the object envelope.

    The PRD fixes the envelope for a single read: "The `response_type` is either
    \"object\" for a single resource or \"array\" for a list of resources", with
    "`api_request_id` ... a server-generated unique identifier for the request that
    starts with `req_`" and "`api_request_timestamp` ... a server-generated ISO 8601
    UTC timestamp with three fractional digits" in `meta`.  The stored figures are
    the ones supplied at receipt: the tech books "the manufacturer's `lot_number`
    ... the `expiration_date` and `received_date` instants, the
    `unit_acquisition_cost_cents` the practice paid for one vial from this lot".

    Design: Corner/entities/corner_get_drug_lot_by_id_returns_the_stored_row
    """
    lot = breadth.lot_ref

    response = breadth.api.get_drug_lot(lot["id"], tech)
    echoed = validate_success(response, 200)

    assert_envelope_shape(response, "object")
    assert echoed["lot_number"] == "RX-9001"
    assert echoed["unit_acquisition_cost_cents"] == 132000
    assert_instant_equals(echoed["expiration_date"], "2027-06-30T00:00:00Z", "expiration_date")
    assert_instant_equals(echoed["received_date"], "2026-07-01T00:00:00Z", "received_date")
    assert echoed["id"] == lot["id"]


def test_lot_listing_pages_the_filtered_collection_and_reports_what_remains(breadth, tech):
    """
    Three lots of one product paged two at a time report the full match count on
    both pages and flip `has_more` on the last one, in `created_at` order.

    The PRD defines the four fields: "`limit` and `offset` echo the effective values
    used for the page, `total_count` reports how many rows matched the filter across
    all pages, and `has_more` is true when rows remain beyond the current page", and
    fixes the order: "List results are ordered by `created_at` ascending unless the
    narrative for a specific listing says otherwise."  Since every resource carries
    "`created_at`, an ISO 8601 UTC timestamp with three fractional digits recording
    when the row was first written" against the logical clock, the three lots are
    booked at three distinct instants so their order is the order they were received.
    Lots "may be listed filtered on `drug_id` and `status`".

    Design: Corner/entities/corner_list_drug_lots_filtered_by_drug_with_limit_and_offset
    """
    drug = breadth.drug_ref
    first = breadth.lot_ref

    breadth.set_clock("2026-08-01T01:00:00Z")
    second = breadth.lot(
        drug_id=drug["id"],
        lot_number="RX-9002",
        expiration_date="2027-07-31T00:00:00Z",
        received_date="2026-07-05T00:00:00Z",
        unit_acquisition_cost_cents=131000,
        vials_received=2,
    )
    breadth.set_clock("2026-08-01T02:00:00Z")
    third = breadth.lot(
        drug_id=drug["id"],
        lot_number="RX-9003",
        expiration_date="2027-08-31T00:00:00Z",
        received_date="2026-07-09T00:00:00Z",
        unit_acquisition_cost_cents=130000,
        vials_received=1,
    )

    page_one, meta_one = validate_list(
        breadth.api.list_drug_lots(tech, f.page_params(limit=2, offset=0, drug_id=drug["id"]))
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert list_ids(page_one) == [first["id"], second["id"]]

    page_two, meta_two = validate_list(
        breadth.api.list_drug_lots(tech, f.page_params(limit=2, offset=2, drug_id=drug["id"]))
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2
    assert list_ids(page_two) == [third["id"]]


def test_an_unknown_lot_identifier_is_a_typed_404_not_an_empty_body(breadth, tech):
    """
    A syntactically valid but unknown lot id answers with the lot's own 404 inside
    the error envelope, and disturbs nothing.

    The PRD assigns each path identifier its own failure: "Every identifier in the
    URL path resolves to an existing row, validated left to right — otherwise the 404
    belonging to the entity that failed to resolve, drawn from ...
    `ERR_LOT_NOT_FOUND` ..."  The error body is fixed too: "The `error_id` is a
    unique, machine-readable string that identifies the specific error" and "The
    `message` provides a human-readable explanation of what went wrong", carried
    under "`response_type`" of `"error"`.

    Design: Corner/entities/corner_get_drug_lot_with_unknown_id_not_found
    """
    lot = breadth.lot_ref

    response = breadth.api.get_drug_lot(UNKNOWN_LOT_ID, tech)
    validate_error(response, ApiErrorId.ERR_LOT_NOT_FOUND, 404)
    body = assert_error_envelope(response)
    assert body["message"].strip()

    assert breadth.read_lot(lot["id"])["vials_on_hand"] == 5


def test_a_lot_missing_its_lot_number_creates_neither_lot_nor_vials(breadth, tech):
    """
    Omitting a required field is rejected at the payload gate and leaves the
    collections empty.

    The PRD lists `lot_number` among the fields receipt requires — the tech supplies
    "the `drug_id` of the product, the manufacturer's `lot_number` (3 to 24
    characters, unique within that drug ...), the `expiration_date` and
    `received_date` instants, the `unit_acquisition_cost_cents` ... and
    `vials_received`" — and the payload gate is stated as step 5: "The request body
    and query string carry every required field, each with the declared type, a
    recognised enum member, a value inside its numeric range ... — otherwise
    `ERR_INVALID_REQUEST` (400)."  Nothing is created because "Receipt is the only
    moment vials come into existence".

    Design: Corner/entities/corner_missing_required_lot_number_returns_invalid_request
    """
    drug = breadth.drug_ref

    response = breadth.api.create_drug_lot(
        {
            "drug_id": drug["id"],
            "expiration_date": "2027-06-30T00:00:00Z",
            "received_date": "2026-07-01T00:00:00Z",
            "unit_acquisition_cost_cents": 132000,
            "vials_received": 5,
        },
        tech,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, lot_meta = validate_list(
        breadth.api.list_drug_lots(tech, f.page_params(drug_id=drug["id"]))
    )
    assert lot_meta["total_count"] == 0

    _, vial_meta = validate_list(breadth.api.list_vials(tech, f.page_params()))
    assert vial_meta["total_count"] == 0


def test_a_payer_registered_with_only_its_three_required_fields_takes_the_declared_defaults(
    breadth, admin
):
    """
    The three optional payer attributes come back as their declared defaults rather
    than as nulls, alongside the system-managed status.

    The PRD names each default: "Three further attributes are optional at
    registration and carry defaults: `pa_required` defaults to true and expresses the
    payer's house rule on prior authorization; `biosimilar_preference` defaults to
    `NONE` and may instead be `PREFERRED` or `MANDATORY`; and `appeal_window_days`
    defaults to 60 and must fall between 1 and 365 inclusive ... A payer's `status`
    is system-managed and begins `ACTIVE`, the alternative value being `INACTIVE`."
    The derived flag follows the contract family: it is "false when `payer_type` is
    `COMMERCIAL`".

    Design: Corner/entities/corner_payer_defaults_applied_when_optional_inputs_omitted
    """
    response = breadth.api.create_payer(
        f.payer_payload(
            name="Bare Minimum Health", payer_type="COMMERCIAL", coinsurance_rate=0.15
        ),
        admin,
    )
    payer = validate_success(response, 201)

    assert payer["pa_required"] is True
    assert payer["biosimilar_preference"] == "NONE"
    assert payer["appeal_window_days"] == 60
    assert payer["status"] == "ACTIVE"
    assert payer["federal_program"] is False
    assert payer["version"] == 1


def test_federal_program_is_derived_from_the_payer_type_alone(breadth, admin):
    """
    A Part B carrier is flagged federal and a commercial carrier is not, from the
    same request shape.

    The PRD forbids the client from setting it: "One payer attribute is never
    supplied by the client. `federal_program` is derived from the contract family: it
    is true when `payer_type` is `MEDICARE_PART_B`, `MEDICARE_ADVANTAGE` or
    `MEDICAID`, and false when `payer_type` is `COMMERCIAL`. That single boolean is
    what later blocks a manufacturer copay card from being applied to a federally
    funded patient, and because it is derived rather than declared, the practice
    cannot accidentally opt a Medicare patient into an ineligible assistance
    program."

    Design: Corner/entities/corner_payer_federal_program_is_computed_from_payer_type
    """
    federal = validate_success(
        breadth.api.create_payer(
            f.payer_payload(
                name="Sentinel Part B", payer_type="MEDICARE_PART_B", coinsurance_rate=0.2
            ),
            admin,
        ),
        201,
    )
    commercial = validate_success(
        breadth.api.create_payer(
            f.payer_payload(
                name="Sentinel Commercial", payer_type="COMMERCIAL", coinsurance_rate=0.2
            ),
            admin,
        ),
        201,
    )

    assert federal["federal_program"] is True
    assert federal["payer_type"] == "MEDICARE_PART_B"
    assert commercial["federal_program"] is False
    assert commercial["payer_type"] == "COMMERCIAL"


def test_a_lots_identity_and_audit_fields_are_minted_by_the_server(breadth, tech):
    """
    The identifier is a server-minted UUID and both audit timestamps read the
    logical clock the row was written against.

    The PRD makes all four server property: "Every resource the API mints carries an
    `id`, which is a server-minted UUID with no type prefix and no client influence —
    a client-supplied `id` in a request body is never honoured. Every resource also
    carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits
    recording when the row was first written", and `version` "starts at 1 when the
    row is created".  Time is the logical clock: "Rather than reading wall-clock
    time, every temporal rule in this system reads a server-held logical clock."

    Design: Corner/entities/corner_lot_system_fields_are_server_minted
    """
    drug = breadth.drug_ref

    lot = validate_success(
        breadth.api.create_drug_lot(
            f.lot_payload(
                drug_id=drug["id"],
                lot_number="RX-9010",
                expiration_date="2027-06-30T00:00:00Z",
                received_date="2026-07-01T00:00:00Z",
                unit_acquisition_cost_cents=132000,
                vials_received=5,
            ),
            tech,
        ),
        201,
    )

    assert_system_fields(lot)
    assert lot["version"] == 1
    assert_instant_equals(lot["created_at"], breadth.CLOCK, "created_at")
    assert_instant_equals(lot["updated_at"], breadth.CLOCK, "updated_at")
    assert is_valid_uuid(lot["id"])


def test_an_eye_outside_the_two_declared_members_is_rejected_before_any_plan_exists(
    breadth,
):
    """
    A plan naming a third eye value is refused as a malformed request and no plan
    row appears.

    The eye is a two-member enum: the specialist records "the `eye` — `OD` for the
    right eye or `OS` for the left", and a plan is opened "for one patient and one
    eye, naming the `patient_id`, the `drug_id` of the planned product before any
    biosimilar substitution, and the `eye`".  An unrecognised member fails the
    payload gate, which requires "a recognised enum member ... — otherwise
    `ERR_INVALID_REQUEST` (400)".

    Design: Corner/entities/corner_invalid_enum_eye_on_plan_create_returns_invalid_request
    """
    breadth.pol_np_ref
    patient = breadth.pt_np
    clinician = breadth.cl1

    response = breadth.api.create_treatment_plan(
        f.plan_payload(
            patient_id=patient["id"],
            drug_id=breadth.drug_ref["id"],
            eye="OU",
            loading_doses_required=3,
        ),
        specialist_headers(clinician["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_list(
        breadth.api.list_treatment_plans(
            specialist_headers(clinician["id"]), f.page_params(patient_id=patient["id"])
        )
    )
    assert meta["total_count"] == 0


def test_an_imaging_study_carries_no_mutability_fields_and_stamps_its_own_reader(breadth):
    """
    The stored study reads back unchanged, carries neither `version` nor
    `updated_at`, and names the acting specialist as its interpreter.

    The PRD carves out the one exception: "An `ImagingStudy` is the one exception. An
    OCT reading is an immutable clinical observation: once written it is never
    edited, and consequently an `ImagingStudy` row carries only `id` and
    `created_at`. It has no `updated_at` field and no `version` field, and neither key
    appears in its response payload."  The reader is stamped, not nominated: "The
    acting specialist's own identifier is stamped onto the study as
    `interpreted_by_clinician_id`; a client may not nominate the interpreter."  The
    verdict is `ACTIVE` here because fluid is present — "or intraretinal fluid is
    present ... any one of those four conditions suffices".

    Design: Corner/entities/corner_imaging_study_is_immutable_and_carries_no_version
    """
    clinician = breadth.cl1
    study = breadth.img_np

    assert study["disease_activity"] == "ACTIVE"
    assert_immutable_entity_fields(study)

    response = breadth.api.get_imaging_study(study["id"], specialist_headers(clinician["id"]))
    echoed = validate_success(response, 200)

    assert echoed["central_subfield_thickness_um"] == 420
    assert echoed["interpreted_by_clinician_id"] == clinician["id"]
    assert_immutable_entity_fields(echoed)


def test_a_plan_naming_an_unknown_patient_reports_the_patients_own_404(breadth):
    """
    An unresolvable `patient_id` in the body is a typed 404 rather than a malformed
    request, and creates nothing.

    The PRD checks body foreign keys after the payload itself: "Every foreign key
    supplied in the request body resolves to an existing row, validated in the order
    the fields are listed for that endpoint in §4's companion narrative — otherwise
    the same catalogue of 404s", which includes `ERR_PATIENT_NOT_FOUND`.  The plan's
    parent is that patient: a specialist "opens a plan for one patient and one eye,
    naming the `patient_id`".

    Design: Corner/entities/corner_plan_create_with_unknown_patient_returns_patient_not_found
    """
    breadth.pol_np_ref
    breadth.pt_np
    clinician = breadth.cl1

    response = breadth.api.create_treatment_plan(
        f.plan_payload(
            patient_id=UNKNOWN_PATIENT_ID,
            drug_id=breadth.drug_ref["id"],
            eye="OD",
            loading_doses_required=3,
        ),
        specialist_headers(clinician["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND, 404)

    _, meta = validate_list(
        breadth.api.list_treatment_plans(specialist_headers(clinician["id"]), f.page_params())
    )
    assert meta["total_count"] == 0
