"""What each entity's own contract promises on the way in and on the way out:
which fields a create echoes back, which the server owns outright, which
defaults it fills, which values it refuses, and which parents it insists on.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    UNKNOWN_UUID,
    ApiErrors,
    add_product,
    add_shelf,
    assert_append_only_identity,
    assert_calendar_date,
    assert_clinic_posture,
    assert_error,
    assert_identity_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_object_envelope,
    build_practice,
    create_clinic,
    create_patient,
    create_physician,
    create_supplier,
    insurance_coordinator_headers,
    inventory_manager_headers,
    practice_admin_headers,
    set_clock,
)
from test_helpers import factories as f


def test_creating_a_clinic_answers_with_every_declared_field(api):
    """A site registered with all six inputs comes back carrying those inputs, the
    two derived posture fields at their opening values, and the four identity
    fields.

    PRD: "A newly registered site opens with a `dispensing_status` of `ACTIVE` and
    a `stockout_par_level_count` of 0; both of those are derived and neither is
    ever supplied by a client."

    Design: Corner/entities/corner_clinic_creation_returns_every_declared_field
    """
    response = api.create_clinic(
        f.clinic_payload(dispensing_specialties=["SPINE", "HAND"]), practice_admin_headers()
    )

    clinic = validate_success(response, 201)
    assert_object_envelope(response)
    assert clinic["name"] == "North Ortho"
    assert clinic["state_code"] == "OH"
    assert clinic["accreditation_body"] == "ABC"
    assert clinic["accreditation_expires_on"] == "2027-06-30"
    assert clinic["ioas_supervision_level"] == "DIRECT"
    assert clinic["dispensing_specialties"] == ["SPINE", "HAND"]
    assert_clinic_posture(clinic, dispensing_status="ACTIVE", stockout_par_level_count=0)
    assert_identity_fields(clinic, expected_version=1)


def test_reading_a_supplier_returns_what_registration_stored(api):
    """A supplier read back reports the promise it was registered with and the two
    derived reputation figures at their opening values.

    PRD: "A new supplier opens with a derived `turnaround_score` of 100 and an
    `accepted_fab_order_count` of 0."

    Design: Corner/entities/corner_supplier_retrieval_returns_stored_representation
    """
    supplier = create_supplier(api, promised_turnaround_days=12, accreditation_body="BOC")

    response = api.get_supplier(supplier["id"], inventory_manager_headers())

    stored = validate_success(response, 200)
    assert stored["name"] == "Bracewell Ortho"
    assert stored["accreditation_body"] == "BOC"
    assert stored["promised_turnaround_days"] == 12
    assert stored["turnaround_score"] == 100
    assert stored["accepted_fab_order_count"] == 0


def test_the_shelf_list_filters_by_posture_and_paginates_over_that_filtered_set(api):
    """With two empty shelves and one stocked shelf, a posture-filtered list counts
    only the two, pages through them one at a time, and never shows the stocked
    shelf; an unfiltered call sees all three.

    PRD: "Both are reflected back in the `meta` object of the response alongside
    `total_count`, the number of rows matching the filter before paging is applied,
    and `has_more`, a boolean that is true when rows remain beyond the current
    page."

    Design: Corner/entities/corner_par_level_listing_filters_and_paginates
    """
    practice = build_practice(api, with_shelf=False)
    collar = add_product(practice, f.cervical_collar_product_payload(practice.supplier_id))
    splint = add_product(practice, f.wrist_splint_product_payload(practice.supplier_id))
    empty_one = add_shelf(practice, practice.product_id)
    empty_two = add_shelf(practice, collar["id"])
    stocked = add_shelf(practice, splint["id"], received_qty=10)
    assert stocked["stock_posture"] == "OK"

    query = {"clinic_id": practice.clinic_id, "stock_posture": "STOCKOUT"}
    first_page = api.list_par_levels(
        inventory_manager_headers(), dict(query, limit=1, offset=0)
    )
    second_page = api.list_par_levels(
        inventory_manager_headers(), dict(query, limit=1, offset=1)
    )
    everything = api.list_par_levels(
        inventory_manager_headers(), {"clinic_id": practice.clinic_id}
    )

    first_rows, _ = assert_list_meta(
        first_page, expected_total=2, expected_limit=1, expected_offset=0, expected_has_more=True
    )
    second_rows, _ = assert_list_meta(
        second_page, expected_total=2, expected_offset=1, expected_has_more=False
    )
    all_rows, _ = assert_list_meta(everything, expected_total=3, expected_has_more=False)
    assert len(first_rows) == 1 and len(second_rows) == 1 and len(all_rows) == 3
    paged_ids = {first_rows[0]["id"], second_rows[0]["id"]}
    assert paged_ids == {empty_one["id"], empty_two["id"]}
    assert stocked["id"] not in paged_ids


def test_reading_a_catalog_item_that_was_never_created_is_a_not_found(api):
    """A well-formed identifier that names no catalog row answers with the
    catalog's own not-found identifier rather than an empty success.

    PRD: "A supplier's catalog can be listed and narrowed by `category`, and a
    single product read directly; an unresolvable `product_id` yields
    `ERR_PRODUCT_NOT_FOUND`."

    Design: Corner/entities/corner_unknown_product_id_returns_not_found
    """
    response = api.get_product(UNKNOWN_UUID, inventory_manager_headers())

    assert_error(response, ApiErrors.PRODUCT_NOT_FOUND, 404)


def test_opening_a_shelf_without_a_par_minimum_is_refused(api):
    """The par minimum has no default, so a shelf request that omits it is refused
    and no shelf is opened.

    PRD: "An `InventoryManager` establishes a **par level** — the practice's term
    for one product's shelf at one clinic — by naming a `clinic_id` and a
    `product_id` together with a `par_min_qty` of at least 1 unit, the minimum
    on-shelf availability the site must maintain, and a `par_max_qty`, the maximum
    stocking level."

    Design: Corner/entities/corner_par_level_creation_missing_par_min_qty_rejected
    """
    practice = build_practice(api, with_shelf=False)

    response = api.create_par_level(
        {"clinic_id": practice.clinic_id, "product_id": practice.product_id, "par_max_qty": 20},
        inventory_manager_headers(),
    )

    assert_error(response, ApiErrors.INVALID_REQUEST, 400)
    assert_list_meta(
        api.list_par_levels(inventory_manager_headers(), {"clinic_id": practice.clinic_id}),
        expected_total=0,
    )


def test_a_supplier_registered_without_its_flags_gets_all_three_as_false(api):
    """Leaving the three supplier booleans out of the registration yields false for
    each of them, not null and not true.

    PRD: "Three booleans may be supplied at onboarding and all three default to
    false: `dmepos_standards_attested`, recording attestation to the DMEPOS
    supplier standards required for in-office dispensing; `custom_fab_capable`,
    recording that the supplier can accept custom-fabricated device orders; and
    `quality_hold`, recording that the practice has placed the supplier on quality
    hold."

    Design: Corner/entities/corner_supplier_flag_defaults_applied_when_omitted
    """
    payload = f.without(
        f.supplier_payload(promised_turnaround_days=15, accreditation_body="ACHC"),
        "dmepos_standards_attested",
        "custom_fab_capable",
        "quality_hold",
    )

    supplier = validate_success(api.create_supplier(payload, practice_admin_headers()), 201)

    assert supplier["dmepos_standards_attested"] is False
    assert supplier["custom_fab_capable"] is False
    assert supplier["quality_hold"] is False
    assert supplier["turnaround_score"] == 100
    assert supplier["promised_turnaround_days"] == 15


def test_an_encounter_without_a_service_date_takes_the_logical_clock_s_date(api):
    """With the clock moved forward, an encounter created without a service date is
    stamped with the clock's calendar date, so the default is read from the clock
    and not from wall time.

    PRD: "It also carries a `quantity` of at least 1 and at most 20 units, and an
    optional `service_date`; when `service_date` is omitted it defaults to the
    logical clock's calendar date at the moment of creation."

    Design: Corner/entities/corner_encounter_service_date_defaults_to_clock_date
    """
    practice = build_practice(api, with_shelf=False)
    previous = set_clock(api, "2026-08-05T00:00:00Z")
    assert_instant_equals(previous["previous_utc"], "2026-08-01T00:00:00Z")

    encounter = practice.open_encounter()

    assert_calendar_date(encounter["service_date"], "service_date")
    assert encounter["service_date"] == "2026-08-05"
    assert encounter["clinical_status"] == "DRAFT"
    assert encounter["financial_status"] == "UNVERIFIED"
    assert encounter["compliance_hold"] is False
    assert encounter["hold_reason"] is None


def test_the_shelf_quantities_are_server_owned_and_only_a_receipt_moves_them(api):
    """A shelf request that also supplies the quantity and posture fields is
    created empty regardless, and only a stock receipt raises those figures.

    PRD: "Its `on_hand_qty` — the physical units actually on the shelf — is 0, its
    `reserved_qty` — the units committed to encounters that have reserved but not
    yet taken delivery — is 0, its derived `available_qty` is 0, and its
    `lifetime_received_qty`, the cumulative count of units ever received into this
    shelf across its whole history, is 0."

    Design: Corner/entities/corner_par_level_computed_quantities_are_server_owned_input_ignored
    """
    practice = build_practice(api, with_shelf=False)

    shelf = validate_success(
        api.create_par_level(
            f.par_level_payload(
                practice.clinic_id,
                practice.product_id,
                on_hand_qty=99,
                available_qty=99,
                stock_posture="OK",
                lifetime_received_qty=99,
            ),
            inventory_manager_headers(),
        ),
        201,
    )
    assert shelf["on_hand_qty"] == 0
    assert shelf["available_qty"] == 0
    assert shelf["lifetime_received_qty"] == 0
    assert shelf["stock_posture"] == "STOCKOUT"
    assert shelf["par_min_qty"] == 4
    assert shelf["par_max_qty"] == 20

    received = validate_success(
        api.receive_stock(shelf["id"], f.stock_receipt_payload(6), inventory_manager_headers()),
        201,
    )
    assert received["on_hand_qty"] == 6
    assert received["available_qty"] == 6
    assert received["stock_posture"] == "OK"


def test_an_encounter_s_identity_and_lifecycle_fields_are_minted_by_the_server(api):
    """A create body that also carries an identifier, a version and four lifecycle
    fields is ignored on every one of them: the row opens fresh, and nothing exists
    at the identifier the caller tried to claim.

    PRD: "`version` starts at 1 when the resource is created and increases by
    exactly 1 on every mutation of that resource, including mutations that only
    touch derived fields."

    Design: Corner/entities/corner_encounter_system_fields_are_server_minted_input_ignored
    """
    practice = build_practice(api, with_shelf=False)
    claimed_id = "00000000-0000-4000-8000-0000000000aa"

    encounter = validate_success(
        api.create_encounter(
            f.encounter_payload(
                practice.clinic_id,
                practice.patient_id,
                practice.product_id,
                practice.ordering_physician_id,
                1,
                id=claimed_id,
                version=47,
                clinical_status="DELIVERED",
                mn_signed_at="2026-07-01T00:00:00Z",
                compliance_hold=True,
                delivered_at="2026-07-02T00:00:00Z",
            ),
            practice_admin_headers(),
        ),
        201,
    )

    assert encounter["id"] != claimed_id
    assert encounter["version"] == 1
    assert encounter["clinical_status"] == "DRAFT"
    assert encounter["mn_signed_at"] is None
    assert encounter["delivered_at"] is None
    assert encounter["compliance_hold"] is False
    assert_error(
        api.get_encounter(claimed_id, practice_admin_headers()),
        ApiErrors.ENCOUNTER_NOT_FOUND,
        404,
    )


def test_a_patient_with_a_payer_type_outside_the_declared_set_is_refused(api):
    """A payer type that is not one of the four declared values is refused and no
    patient is created.

    PRD: "A `Patient` carries a `full_name` of 1 to 120 non-blank characters, a
    `dob` date of birth, a `payer_type` drawn from `MEDICARE`, `MEDICAID`,
    `COMMERCIAL` and `SELF_PAY`, an optional `member_id` payer member identifier
    that defaults to null and is expected to be null for self-pay patients, and an
    optional `medicare_beneficiary` boolean defaulting to false."

    Design: Corner/entities/corner_patient_invalid_payer_type_enum_rejected
    """
    clinic = create_clinic(api)

    response = api.create_patient(
        clinic["id"],
        f.patient_payload(payer_type="TRICARE"),
        insurance_coordinator_headers(),
    )

    assert_error(response, ApiErrors.INVALID_REQUEST, 400)
    assert_list_meta(
        api.list_patients(clinic["id"], practice_admin_headers()), expected_total=0
    )


def test_re_verifying_coverage_appends_a_second_row_and_leaves_the_first_intact(api):
    """A second verification is a new numbered row, not an edit: the first row keeps
    its own figures, neither row carries a version, and both appear in the list.

    PRD: "The server assigns `verification_seq`, a 1-based sequence within the
    encounter equal to the previous maximum plus 1, stamps `verified_at` from the
    logical clock, and derives `expires_at` as `verified_at` plus `valid_for_days`
    whole days."

    Design: Corner/entities/corner_coverage_verification_is_immutable_and_append_only
    """
    practice = build_practice(api, with_shelf=False)
    encounter_id = practice.attested_encounter()

    # The declared origins of a verification are `UNVERIFIED` and `NON_COVERED`,
    # so the correcting second row is written over a first row that said no.
    first = practice.verify_coverage(
        encounter_id, covered=False, deductible_remaining_cents=5000, coinsurance_pct=0.2, valid_for_days=30
    )
    second = practice.verify_coverage(
        encounter_id, covered=True, deductible_remaining_cents=0, coinsurance_pct=0.5, valid_for_days=60
    )

    assert first["verification_seq"] == 1
    assert second["verification_seq"] == 2
    assert first["covered"] is False
    assert second["covered"] is True
    assert first["deductible_remaining_cents"] == 5000
    assert second["deductible_remaining_cents"] == 0
    assert_instant_equals(first["expires_at"], "2026-08-31T00:00:00Z", "expires_at")
    assert_append_only_identity(first)
    assert_append_only_identity(second)

    rows, _ = assert_list_meta(
        api.list_coverage_verifications(encounter_id, insurance_coordinator_headers()),
        expected_total=2,
    )
    assert {row["id"] for row in rows} == {first["id"], second["id"]}
    for row in rows:
        assert "version" not in row


def test_a_fitter_cannot_be_hired_into_a_clinic_that_does_not_exist(api):
    """A fitter is always a fitter of some clinic, so an unresolvable clinic in the
    path is refused and leaves the real clinic's roster empty.

    PRD: "Path parameters are resolved strictly left to right, and the first
    identifier that names no existing row determines the response."

    Design: Corner/entities/corner_fitter_creation_under_unknown_clinic_rejected
    """
    clinic = create_clinic(api)

    response = api.create_fitter(
        "00000000-0000-4000-8000-0000000000c9", f.fitter_payload(), practice_admin_headers()
    )

    assert_error(response, ApiErrors.CLINIC_NOT_FOUND, 404)
    assert_list_meta(
        api.list_fitters(clinic["id"], practice_admin_headers()), expected_total=0
    )


def test_an_encounter_cannot_borrow_a_patient_from_another_clinic(api):
    """A patient on one site's roster cannot be attached to an encounter opened at
    another site: the patient exists, so this is a scoping refusal and not a
    not-found.

    PRD: "The named patient's `clinic_id` must equal the encounter's `clinic_id`;
    the named ordering physician's `clinic_id` must equal it too; and the ordering
    physician's `specialty` must equal the product's `specialty`, because a spine
    surgeon does not order a foot-and-ankle orthosis under this practice's rules."

    Design: Corner/entities/corner_encounter_across_two_clinics_rejected
    """
    practice = build_practice(api, with_shelf=False)
    other_clinic = create_clinic(api, name="South Ortho")
    create_physician(api, other_clinic["id"], full_name="Vic Hale", specialty="SPINE")
    other_patient = create_patient(api, other_clinic["id"], full_name="Joel Pike")

    response = api.create_encounter(
        f.encounter_payload(
            practice.clinic_id,
            other_patient["id"],
            practice.product_id,
            practice.ordering_physician_id,
            1,
        ),
        practice_admin_headers(),
    )

    assert_error(response, ApiErrors.CLINIC_SCOPE_MISMATCH, 403)
    assert_list_meta(
        api.list_encounters(practice_admin_headers(), {"clinic_id": practice.clinic_id}),
        expected_total=0,
    )
