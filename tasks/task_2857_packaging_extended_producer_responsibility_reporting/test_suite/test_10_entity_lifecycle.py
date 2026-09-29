"""Entity creation, retrieval, listing, shape validation and version discipline.

These tests exercise the declared defaults of a freshly created row, the read-back
of stored reference data, the pagination envelope and its filters, the twelve
type-specific not-found codes, the shape rejections that precede every business
rule, and the rule that every write advances the row's version by exactly one.
"""

from test_helpers import (
    ApiErrorId,
    ComponentStatus,
    ExemptionStatus,
    NON_EXISTENT_UUID,
    ObligatedPartyRole,
    ObligationBasis,
    ProducerStatus,
    REGULATOR_HEADERS,
    SkuStatus,
    assert_common_fields,
    assert_instant_equals,
    assert_producer,
    assert_registration,
    assert_reporting_period,
    assert_sku,
    assert_state_program,
    assert_weight,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    make_pro_administrator_headers,
    make_producer_compliance_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import CompliancePosture


def _total_count(response):
    """The filtered row count reported by a list endpoint."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


# ---------------------------------------------------------------------------
# Creation: the server supplies every field the client did not
# ---------------------------------------------------------------------------
def test_a_new_producer_answers_with_every_declared_default(api):
    """The create response carries the whole default set in one body.

    Nothing in the request mentions a status, a classification, a tonnage, a
    staleness flag or a balance, yet all five come back filled in, and the row is
    at version one with its two timestamps still equal.

    Design: Corner/entities/producer_create_returns_declared_defaults_and_system_fields
    """
    assert _total_count(api.list_producers(REGULATOR_HEADERS, {"limit": 10, "offset": 0})) == 0

    producer = validate_success(
        api.create_producer(
            f.producer_payload(
                legal_name="Northlake Beverages LLC",
                brand_owner_flag=True,
                importer_of_record_flag=False,
                domestic_licensor_flag=False,
                annual_gross_revenue_usd=5000000,
                contact_email="compliance@northlake.example",
            ),
            REGULATOR_HEADERS,
        ),
        201,
    )

    assert is_valid_uuid(producer["id"])
    assert_producer(
        producer,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        parent_producer_id=None,
        status=ProducerStatus.DRAFT,
        obligated_party_role=ObligatedPartyRole.UNDETERMINED,
        determination_stale=False,
        assessed_fee_balance_cents=0,
        version=1,
    )
    assert_weight(producer["annual_packaging_weight_kg"], 0.000, "annual_packaging_weight_kg")
    assert_instant_equals(producer["updated_at"], producer["created_at"], "updated_at")


# ---------------------------------------------------------------------------
# Retrieval: reference data reads back exactly as it was stored
# ---------------------------------------------------------------------------
def test_reference_data_reads_back_field_for_field_for_any_role(api):
    """A program and its period return the stored values to an unrelated officer.

    Reference data is shared rather than producer-scoped, so an officer that owns
    nothing here may read both rows, and the empty exemption array and the
    three-decimal tonnage threshold survive the round trip unchanged.

    Design: Corner/entities/state_program_and_reporting_period_retrieval_returns_stored_data
    """
    program = fx.make_state_program(
        api,
        state_code="CA",
        obligation_basis=ObligationBasis.ENTITY_LEVEL,
        small_producer_revenue_threshold_usd=1000000,
        small_producer_tonnage_threshold_kg=1.000,
        exempt_product_categories=[],
        verification_required_threshold_kg=3000,
    )
    period = fx.make_reporting_period(
        api,
        program["id"],
        period_label="CA-2026-H1",
        data_start="2026-07-01",
        data_end="2027-01-01",
        submission_open="2026-07-01T00:00:00Z",
        submission_deadline="2026-12-31T23:59:59Z",
        correction_window_days=30,
    )
    outsider = make_producer_compliance_officer_headers(NON_EXISTENT_UUID)

    read_program = validate_success(api.get_state_program(program["id"], outsider))
    read_period = validate_success(api.get_reporting_period(period["id"], outsider))

    assert_state_program(
        read_program,
        state_code="CA",
        obligation_basis=ObligationBasis.ENTITY_LEVEL,
        eco_mod_policy="BONUS_MALUS",
        fee_rounding_order="PER_LINE_THEN_SUM",
        small_producer_revenue_threshold_usd=1000000,
        exempt_product_categories=[],
    )
    assert_weight(
        read_program["small_producer_tonnage_threshold_kg"],
        1.000,
        "small_producer_tonnage_threshold_kg",
    )
    assert_weight(
        read_program["verification_required_threshold_kg"],
        3000,
        "verification_required_threshold_kg",
    )
    assert_reporting_period(
        read_period,
        state_program_id=program["id"],
        period_label="CA-2026-H1",
        data_start="2026-07-01",
        data_end="2027-01-01",
        correction_window_days=30,
    )


# ---------------------------------------------------------------------------
# Listing: the pagination envelope and the declared producer filters
# ---------------------------------------------------------------------------
def _three_draft_producers(api):
    """A brand owner, a second brand owner and the second one's affiliate."""
    first = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    second = fx.make_producer(
        api,
        legal_name="Harborline Foods Inc",
        annual_gross_revenue_usd=2000000,
        contact_email="epr@harborline.example",
    )
    third = fx.make_producer(
        api,
        legal_name="Harborline Snacks Sub",
        parent_producer_id=second["id"],
        brand_owner_flag=False,
        importer_of_record_flag=True,
        annual_gross_revenue_usd=400000,
        contact_email="sub@harborline.example",
    )
    return first, second, third


def test_the_producer_list_pages_and_narrows_by_its_declared_filters(api):
    """Three stored rows are walked in two pages and then filtered three ways.

    The first window returns two of the three rows and reports that more remain,
    the second returns the last row and reports that none do; the status filter
    matches all three, the classification filter matches none because no
    determination has run, and the parent filter isolates the affiliate.

    Design: Corner/entities/producer_list_pagination_envelope_and_filters
    """
    _first, second, third = _three_draft_producers(api)

    page_one, meta_one = validate_paginated(
        api.list_producers(REGULATOR_HEADERS, {"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2 and meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_producers(REGULATOR_HEADERS, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    outsider_admin = make_pro_administrator_headers(NON_EXISTENT_UUID)
    assert (
        _total_count(
            api.list_producers(outsider_admin, {"status": ProducerStatus.DRAFT, "limit": 10, "offset": 0})
        )
        == 3
    )

    branded, branded_meta = validate_paginated(
        api.list_producers(
            REGULATOR_HEADERS,
            {"obligated_party_role": ObligatedPartyRole.BRAND_OWNER, "limit": 10, "offset": 0},
        )
    )
    assert branded == [] and branded_meta["total_count"] == 0

    affiliates, affiliate_meta = validate_paginated(
        api.list_producers(
            REGULATOR_HEADERS, {"parent_producer_id": second["id"], "limit": 10, "offset": 0}
        )
    )
    assert affiliate_meta["total_count"] == 1
    assert affiliates[0]["id"] == third["id"]


# ---------------------------------------------------------------------------
# Defaults: the exemption verdict is not pre-computed at creation
# ---------------------------------------------------------------------------
def test_a_draft_registration_carries_no_exemption_verdict_yet(api):
    """Opening a registration leaves every verdict field at its undetermined default.

    The exemption analysis runs at submission, so the fresh row reports an
    undetermined exemption on no basis, four zeroed rollups and no submission
    instant, and the producer it names is left exactly as the determination left it.

    Design: Corner/entities/registration_and_report_defaults_before_any_determination
    """
    program = fx.make_state_program(
        api,
        state_code="CA",
        obligation_basis=ObligationBasis.ENTITY_LEVEL,
        small_producer_revenue_threshold_usd=1000000,
        small_producer_tonnage_threshold_kg=1.000,
    )
    built = fx.determined_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    producer = built["producer"]

    registration = validate_success(
        api.create_registration(
            f.registration_payload(producer["id"], program["id"]), fx.officer(producer)
        ),
        201,
    )

    assert_registration(
        registration,
        status="DRAFT",
        submitted_at=None,
        suspension_reason=None,
        exemption_status=ExemptionStatus.UNDETERMINED,
        exemption_basis_applied="NONE",
        assessed_group_revenue_usd=0,
        compliance_posture=CompliancePosture.UNDETERMINED,
        version=1,
    )
    assert_weight(registration["assessed_group_weight_kg"], 0.000, "assessed_group_weight_kg")
    assert_weight(registration["reported_weight_kg_ytd"], 0.000, "reported_weight_kg_ytd")

    unchanged = validate_success(api.get_producer(producer["id"], fx.officer(producer)))
    assert_producer(
        unchanged,
        status=ProducerStatus.OBLIGATION_DETERMINED,
        obligated_party_role=ObligatedPartyRole.BRAND_OWNER,
    )
    assert_weight(unchanged["annual_packaging_weight_kg"], 5.500, "annual_packaging_weight_kg")


# ---------------------------------------------------------------------------
# Computed fields: a create body cannot smuggle a derived or system value
# ---------------------------------------------------------------------------
def test_a_create_body_cannot_smuggle_derived_or_system_values(api):
    """Only the five declared inputs of a unit are honoured at creation.

    The body also carries a component list, a unit weight, a status, a revision
    count, an identifier and a version, yet the row comes back in draft with no
    components and no weight; the first genuine component append is what moves the
    weight to fifty grams, and a draft unit contributes nothing to its producer.

    Design: Corner/entities/sku_create_computed_and_system_fields_input_ignored
    """
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    headers = fx.officer(producer)

    sku = validate_success(
        api.create_sku(
            f.sku_payload(
                producer["id"],
                name="Sparkling Water 750ml",
                product_category="BEVERAGE",
                units_sold_annual_estimate=110,
                components=[
                    f.component_payload(material_type="GLASS", unit_weight_grams=999.00)
                ],
                unit_packaging_weight_grams=999.00,
                status=SkuStatus.ACTIVE,
                revision_count=7,
                id="11111111-1111-1111-1111-111111111111",
                version=42,
            ),
            headers,
        ),
        201,
    )

    assert sku["id"] != "11111111-1111-1111-1111-111111111111"
    assert_sku(
        sku,
        status=SkuStatus.DRAFT,
        components=[],
        unit_packaging_weight_grams=0.00,
        revision_count=0,
        version=1,
    )

    with_component = validate_success(
        api.add_sku_component(
            sku["id"],
            f.component_payload(material_type="GLASS", unit_weight_grams=50.00),
            headers,
        )
    )

    assert_sku(with_component, version=2, unit_packaging_weight_grams=50.00)
    assert len(with_component["components"]) == 1
    assert with_component["components"][0]["component_seq"] == 1
    assert with_component["components"][0]["status"] == ComponentStatus.ACTIVE

    still_untouched = validate_success(api.get_producer(producer["id"], headers))
    assert_producer(still_untouched, version=1)
    assert_weight(
        still_untouched["annual_packaging_weight_kg"], 0.000, "annual_packaging_weight_kg"
    )


# ---------------------------------------------------------------------------
# Not found: each read answers with its own entity's code
# ---------------------------------------------------------------------------
def test_every_entity_read_names_its_own_not_found_code(api):
    """Twelve reads of an absent identifier give twelve distinct codes.

    The identifier is a well-formed but unused value, so no read may fall back on
    a generic shape rejection or borrow a neighbouring entity's code, and every
    body carries only the machine-readable code and its message.

    Design: Corner/entities/entity_path_ids_that_do_not_exist_return_entity_specific_not_found
    """
    reads = (
        (api.get_producer, ApiErrorId.PRODUCER_NOT_FOUND),
        (api.get_sku, ApiErrorId.SKU_NOT_FOUND),
        (api.get_state_program, ApiErrorId.STATE_PROGRAM_NOT_FOUND),
        (api.get_reporting_period, ApiErrorId.REPORTING_PERIOD_NOT_FOUND),
        (api.get_pro, ApiErrorId.PRO_NOT_FOUND),
        (api.get_fee_schedule, ApiErrorId.FEE_SCHEDULE_NOT_FOUND),
        (api.get_registration, ApiErrorId.REGISTRATION_NOT_FOUND),
        (api.get_membership, ApiErrorId.MEMBERSHIP_NOT_FOUND),
        (api.get_report, ApiErrorId.REPORT_NOT_FOUND),
        (api.get_report_line, ApiErrorId.REPORT_LINE_NOT_FOUND),
        (api.get_engagement, ApiErrorId.ENGAGEMENT_NOT_FOUND),
        (api.get_invoice, ApiErrorId.INVOICE_NOT_FOUND),
    )

    for read, expected in reads:
        error = validate_error(read(NON_EXISTENT_UUID, REGULATOR_HEADERS), expected, 404)
        assert error["error_id"] == expected.value
        assert isinstance(error["message"], str) and error["message"]
        assert set(error) == {"error_id", "message"}


# ---------------------------------------------------------------------------
# Required fields: a shape rejection persists nothing
# ---------------------------------------------------------------------------
def test_a_missing_required_input_field_is_rejected_and_stores_nothing(api):
    """Four creates each omit one field that carries no default.

    A producer without its legal name, a program without its obligation basis, a
    unit without its product category and a schedule without its membership fee are
    all refused before any existence or state check, and each collection still holds
    exactly what it held before.

    Design: Corner/entities/create_bodies_missing_required_fields_return_invalid_request
    """
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    pro = fx.make_pro(api, name="Circular Stewardship Alliance", contact_email="ops@csa.example")
    program = fx.make_state_program(api, state_code="CA")

    no_name = f.producer_payload(contact_email="nolegalname@northlake.example")
    del no_name["legal_name"]
    no_basis = f.state_program_payload(state_code="OR")
    del no_basis["obligation_basis"]
    no_category = f.sku_payload(producer["id"], name="Cereal 500g", units_sold_annual_estimate=100)
    del no_category["product_category"]
    no_fee = f.fee_schedule_payload(pro["id"], program["id"])
    del no_fee["membership_fee_cents"]

    validate_error(
        api.create_producer(no_name, REGULATOR_HEADERS), ApiErrorId.INVALID_REQUEST, 400
    )
    validate_error(
        api.create_state_program(no_basis, REGULATOR_HEADERS), ApiErrorId.INVALID_REQUEST, 400
    )
    validate_error(
        api.create_sku(no_category, fx.officer(producer)), ApiErrorId.INVALID_REQUEST, 400
    )
    validate_error(
        api.create_fee_schedule(no_fee, fx.admin(pro)), ApiErrorId.INVALID_REQUEST, 400
    )

    assert _total_count(api.list_producers(REGULATOR_HEADERS, {"limit": 100, "offset": 0})) == 1
    assert (
        _total_count(api.list_state_programs(REGULATOR_HEADERS, {"limit": 100, "offset": 0})) == 1
    )
    assert (
        _total_count(
            api.list_skus(REGULATOR_HEADERS, {"producer_id": producer["id"], "limit": 100, "offset": 0})
        )
        == 0
    )
    assert (
        _total_count(
            api.list_fee_schedules(REGULATOR_HEADERS, {"pro_id": pro["id"], "limit": 100, "offset": 0})
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Type constraints: enums, ranges and the pagination window
# ---------------------------------------------------------------------------
def test_out_of_range_enums_numbers_and_pagination_windows_are_all_shape_failures(api):
    """Five malformed requests all answer with the single shape-failure code.

    A category outside its enumeration, a negative unit estimate, an administrative
    bracket above two thousand basis points, a page size above one hundred and a
    negative offset are one and the same class of failure, and neither malformed
    unit is stored.

    Design: Corner/entities/out_of_range_enums_numbers_and_pagination_return_invalid_enum_rejection
    """
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    pro = fx.make_pro(api, name="Circular Stewardship Alliance", contact_email="ops@csa.example")
    program = fx.make_state_program(api, state_code="CA")
    headers = fx.officer(producer)

    validate_error(
        api.create_sku(
            f.sku_payload(producer["id"], name="Mystery Item", product_category="PET_TOYS"),
            headers,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_sku(
            f.sku_payload(
                producer["id"],
                name="Negative Units",
                product_category="FOOD_DRY",
                units_sold_annual_estimate=-1,
            ),
            headers,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_fee_schedule(
            f.fee_schedule_payload(pro["id"], program["id"], admin_fee_bps_high=2001),
            fx.admin(pro),
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.list_producers(REGULATOR_HEADERS, {"limit": 101, "offset": 0}),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.list_producers(REGULATOR_HEADERS, {"limit": 10, "offset": -1}),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    assert (
        _total_count(
            api.list_skus(headers, {"producer_id": producer["id"], "limit": 10, "offset": 0})
        )
        == 0
    )


# ---------------------------------------------------------------------------
# Parent relationships: no append may orphan its child
# ---------------------------------------------------------------------------
def test_an_append_against_an_absent_parent_names_the_parent(api):
    """The three append-style sub-resources all refuse an unknown parent.

    A component, a reporting period and a report line each address their parent
    through the path, so the path identifier is resolved before anything in the
    body — the line append reports the missing report rather than the missing unit
    its body names — and no child row survives.

    Design: Corner/entities/sub_resource_appends_require_an_existing_parent_not_found
    """
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    headers = fx.officer(producer)

    validate_error(
        api.add_sku_component(
            NON_EXISTENT_UUID,
            f.component_payload(material_type="GLASS", unit_weight_grams=50.00),
            headers,
        ),
        ApiErrorId.SKU_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_reporting_period(
            NON_EXISTENT_UUID,
            f.reporting_period_payload(period_label="XX-2026-H1"),
            REGULATOR_HEADERS,
        ),
        ApiErrorId.STATE_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api.add_report_line(
            NON_EXISTENT_UUID, f.report_line_payload(NON_EXISTENT_UUID, 110), headers
        ),
        ApiErrorId.REPORT_NOT_FOUND,
        404,
    )

    assert _total_count(api.list_report_lines(REGULATOR_HEADERS, {"limit": 10, "offset": 0})) == 0


# ---------------------------------------------------------------------------
# Body foreign keys: resolved in the order the endpoint declares them
# ---------------------------------------------------------------------------
def test_the_first_declared_body_reference_is_the_one_reported(api):
    """Four creates with unresolvable references each name their first field.

    A unit names its producer, a registration its program once the producer
    resolves, a report its registration ahead of its period, and an invoice its
    report ahead of its membership; nothing is stored in any of the four
    collections.

    Design: Corner/entities/body_foreign_keys_are_validated_in_declared_input_order_not_found
    """
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    pro = fx.make_pro(api, name="Circular Stewardship Alliance", contact_email="ops@csa.example")
    headers = fx.officer(producer)

    validate_error(
        api.create_sku(
            f.sku_payload(NON_EXISTENT_UUID, name="Orphan SKU", product_category="FOOD_DRY"),
            make_producer_compliance_officer_headers(NON_EXISTENT_UUID),
        ),
        ApiErrorId.PRODUCER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_registration(
            f.registration_payload(producer["id"], NON_EXISTENT_UUID), headers
        ),
        ApiErrorId.STATE_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_report(f.report_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), headers),
        ApiErrorId.REGISTRATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_invoice(
            f.invoice_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), fx.admin(pro)
        ),
        ApiErrorId.REPORT_NOT_FOUND,
        404,
    )

    for lister in (api.list_skus, api.list_registrations, api.list_reports, api.list_invoices):
        assert _total_count(lister(REGULATOR_HEADERS, {"limit": 10, "offset": 0})) == 0


# ---------------------------------------------------------------------------
# Immutability: nothing here is frozen, so every write moves the version
# ---------------------------------------------------------------------------
def test_activation_and_determination_each_advance_the_versions_by_one(api):
    """The unit walks one to three and its producer walks one to three as well.

    Activation is the unit's third write and the producer's second, because the
    activation also refreshes the producer's tonnage; the determination is the
    producer's third. The staleness flag stays down throughout, because the
    producer was still in draft when its material data moved.

    Design: Corner/entities/every_entity_carries_a_version_that_increments_on_each_write
    """
    producer = fx.make_producer(
        api,
        legal_name="Northlake Beverages LLC",
        annual_gross_revenue_usd=5000000,
        contact_email="compliance@northlake.example",
    )
    headers = fx.officer(producer)
    assert_common_fields(producer, expected_version=1)

    sku = validate_success(
        api.create_sku(
            f.sku_payload(
                producer["id"], name="Sparkling Water 750ml", units_sold_annual_estimate=110
            ),
            headers,
        ),
        201,
    )
    assert_common_fields(sku, expected_version=1)
    appended = validate_success(
        api.add_sku_component(
            sku["id"],
            f.component_payload(material_type="GLASS", unit_weight_grams=50.00),
            headers,
        )
    )
    assert_common_fields(appended, expected_version=2)

    activated = validate_success(api.activate_sku(sku["id"], None, headers))

    assert_sku(activated, status=SkuStatus.ACTIVE, version=3)
    after_activate = validate_success(api.get_producer(producer["id"], headers))
    assert_producer(
        after_activate, version=2, determination_stale=False, status=ProducerStatus.DRAFT
    )
    assert_weight(
        after_activate["annual_packaging_weight_kg"], 5.500, "annual_packaging_weight_kg"
    )

    determined = validate_success(api.determine_obligation(producer["id"], None, REGULATOR_HEADERS))

    assert_producer(
        determined,
        version=3,
        status=ProducerStatus.OBLIGATION_DETERMINED,
        obligated_party_role=ObligatedPartyRole.BRAND_OWNER,
        determination_stale=False,
    )
