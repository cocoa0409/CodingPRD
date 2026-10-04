"""Scheduled personal property, appraisal-document currency and the aggregate cap."""
from test_helpers import (
    add_approved_appraisal,
    api_client,
    assert_appraisal_document,
    create_agency,
    create_appraisal_document,
    create_enrollment,
    create_property,
    create_underwritable_setup,
    create_zone,
    file_document_and_schedule,
    get_success_data,
    reload_property,
    reset_clock,
    run_posture_eval,
    setup_property_with_scheduled_item,
    setup_underwritable_property,
    submit_enrollment,
    validate_error,
    validate_success,
)


def test_scheduled_aggregate_at_the_cap_is_accepted(api, underwriter_headers):
    """PRD 3.2: "the sum of `declared_value_cents` across the property's items already
    in status `APPROVED` or `ATTACHED`, counted together with the item under approval,
    must not exceed 60 percent of the property's `total_insured_value_cents`; a breach
    is refused with `ERR_SCHEDULED_VALUE_CAP`."

    Design: Difficulty/boundary_precision_check/scheduled_aggregate_cap_exactly_at_boundary_is_accepted
    """
    # With nothing approved yet and a single item under approval, the item's own
    # declared value is the whole aggregate and the property's total insured
    # value is the dwelling alone, so the inclusive bound is exactly
    # 0.60 x 200000000 = 120000000.
    zone, agency, prop = create_underwritable_setup(zone_code="ZCAP",
                                                    agency_code="AGCAP")
    assert prop["total_insured_value_cents"] == 200_000_000

    _doc, at_cap = file_document_and_schedule(
        prop["id"], item_type="FINE_ART", declared_value_cents=120_000_000,
        appraised_value_cents=150_000_000)
    approved = validate_success(
        api_client.approve_scheduled_item(at_cap["id"], underwriter_headers), 200)
    assert approved["status"] == "APPROVED"
    assert approved["attached_value_cents"] == 120_000_000
    after = reload_property(prop["id"])
    assert after["scheduled_valuation_cents"] == 120_000_000
    assert after["total_insured_value_cents"] == 320_000_000

    # The bound moves with the accepted value: the total is now 320000000, so
    # the inclusive bound on the aggregate is 0.60 x 320000000 = 192000000, and
    # 120000000 is already occupied.  A 72000000 item lands exactly on the line;
    # one cent more is a breach.
    _doc1, at_line = file_document_and_schedule(
        prop["id"], item_type="COLLECTION", declared_value_cents=72_000_000,
        appraised_value_cents=90_000_000)
    hit = validate_success(
        api_client.approve_scheduled_item(at_line["id"], underwriter_headers), 200)
    assert hit["status"] == "APPROVED"
    assert reload_property(prop["id"])["scheduled_valuation_cents"] == 192_000_000

    # The bound moves with the accepted value: approving the second item raises
    # the property's total insured value to 320000000 + 72000000 = 392000000, so
    # the inclusive bound on the aggregate is 0.60 x 392000000 = 235200000.  With
    # 192000000 already occupied, 43200000 lands exactly on the line; one cent
    # more is a breach.
    _doc2, over = file_document_and_schedule(
        prop["id"], item_type="JEWELRY", declared_value_cents=43_200_001,
        appraised_value_cents=60_000_000)
    res = api_client.approve_scheduled_item(over["id"], underwriter_headers)
    validate_error(res, "ERR_SCHEDULED_VALUE_CAP", expected_status=422)


def test_property_read_reports_the_scheduled_component(api, underwriter_headers):
    """PRD 3.1: "The `scheduled_valuation_cents` component is the sum of
    `attached_value_cents` over the property's scheduled items in status `APPROVED`
    or `ATTACHED`."
    PRD 3.1: "`total_insured_value_cents` is the dwelling component plus the contents
    component plus the scheduled component. Loss-of-use coverage is never part of this
    sum, and never participates in any concentration or exposure measurement."

    Design: Corner/entities/property_get_returns_derived_posture_and_valuation_totals
    """
    zone, agency, prop, item = setup_property_with_scheduled_item(
        item_type="COLLECTION", declared_value_cents=50_000_000,
        dwelling_cost_cents=200_000_000)
    read = validate_success(
        api_client.get_property(prop["id"], underwriter_headers), 200)
    assert read["dwelling_replacement_cost_cents"] == 200_000_000
    assert read["scheduled_valuation_cents"] == 50_000_000
    assert read["total_insured_value_cents"] == 250_000_000
    assert read["mitigation_band"] == "UNVERIFIED"
    assert read["base_posture"] == "UNDERWRITABLE"
    # PRD 2.9: the WUI referral branch fires only when the bound zone's
    # exposure_band is ELEVATED, so an EXTREME / WITHIN_WUI zone whose cleared
    # mitigation and defense window are both absent still writes.
    assert read["posture"] == "WRITE_ELIGIBLE"


def test_appraisal_document_is_an_append_only_record(api, underwriter_headers):
    """PRD 2.6: "an `AppraisalDocument` and a `ManagedRiskEvent` are created with `id`
    and `created_at` only, and therefore expose neither `updated_at` nor `version`;
    nothing in the specification keys a mutation or a concurrency check on either of
    them."

    Design: Corner/entities/appraisal_document_and_managed_risk_event_are_immutable_records
    """
    prop = setup_underwritable_property(zone_code="ZDOC", agency_code="AGDOC")
    doc = create_appraisal_document(prop["id"], item_class="JEWELRY",
                                    appraisal_date="2026-08-20T00:00:00Z",
                                    appraised_value_cents=60_000_000)
    assert_appraisal_document(doc)
    assert "updated_at" not in doc
    assert "version" not in doc
    assert doc["currency_months"] == 0
    assert doc["currency_status"] == "CURRENT"

    # A second document is a new row; the first is untouched.
    create_appraisal_document(prop["id"], item_class="JEWELRY",
                              appraisal_date="2026-08-20T00:00:00Z",
                              appraised_value_cents=70_000_000)
    listing = get_success_data(api_client.list_appraisal_documents(
        prop["id"], underwriter_headers))
    assert len(listing) == 2


def test_expired_appraisal_document_blocks_item_approval(api, underwriter_headers):
    """PRD 3.2: "Its `currency_status` must be `CURRENT` or `AGING` — an `EXPIRED`
    document, or one whose `appraised_value_cents` falls below the item's
    `declared_value_cents`, is refused with `ERR_APPRAISAL_CURRENCY_EXPIRED`."

    Design: Corner/validations/expired_appraisal_document_blocks_scheduled_item_approval
    """
    prop = setup_underwritable_property(zone_code="ZEXP", agency_code="AGEXP")
    doc, item = file_document_and_schedule(
        prop["id"], item_type="JEWELRY", declared_value_cents=50_000_000,
        appraised_value_cents=60_000_000, appraisal_date="2024-09-15T00:00:00Z")

    # Currency is derived at read time, so the untouched document decays with the clock.
    reset_clock("2026-10-01T00:00:00Z")
    res = api_client.approve_scheduled_item(item["id"], underwriter_headers)
    validate_error(res, "ERR_APPRAISAL_CURRENCY_EXPIRED", expected_status=422)

    pending = get_success_data(api_client.list_scheduled_items(
        prop["id"], underwriter_headers, params={"status": "PENDING"}))
    assert any(row["id"] == item["id"] for row in pending)


def test_scheduled_approval_recomputes_both_property_aggregates(api, underwriter_headers):
    """PRD 3.2: "Approval recomputes the item's `appraisal_currency_months` from the
    clock and then recomputes both `scheduled_valuation_cents` and
    `total_insured_value_cents` on the property."

    Design: Corner/entities/property_get_returns_derived_posture_and_valuation_totals
    """
    prop = setup_underwritable_property(zone_code="ZAGG", agency_code="AGAGG")
    assert reload_property(prop["id"])["total_insured_value_cents"] == 200_000_000

    _doc, item = file_document_and_schedule(
        prop["id"], item_type="WINE", declared_value_cents=40_000_000,
        appraised_value_cents=50_000_000)
    approved = validate_success(
        api_client.approve_scheduled_item(item["id"], underwriter_headers), 200)
    assert approved["attached_value_cents"] == 40_000_000

    after = reload_property(prop["id"])
    assert after["scheduled_valuation_cents"] == 40_000_000
    assert after["total_insured_value_cents"] == 240_000_000


def test_document_class_mismatch_is_refused(api, underwriter_headers):
    """PRD 3.2: "Its `item_class` must match the item's `item_type`."
    PRD 3.2: "A document that belongs to another property or mismatches the item class
    is refused with `ERR_APPRAISAL_DOC_MISMATCH`."

    Design: Corner/entities/appraisal_document_and_managed_risk_event_are_immutable_records
    """
    prop = setup_underwritable_property(zone_code="ZMIS", agency_code="AGMIS")
    _doc, item = file_document_and_schedule(
        prop["id"], item_type="JEWELRY", declared_value_cents=50_000_000,
        appraised_value_cents=60_000_000, item_class="WINE")

    res = api_client.approve_scheduled_item(item["id"], underwriter_headers)
    validate_error(res, "ERR_APPRAISAL_DOC_MISMATCH", expected_status=422)

def test_an_approved_item_stays_out_of_the_totals_until_the_bind(
        api, underwriter_headers):
    """PRD 3.2: "The item is born in `PENDING` with `attached_value_cents` at 0, and
    contributes nothing until it is approved."
    PRD 3.2: "when the property's enrollment reaches `ATTACHED`, every approved
    scheduled item of that property transitions to `ATTACHED` automatically, and
    `attached_value_cents` becomes the item's `declared_value_cents`"

    Design: Difficulty/cross_entity_state_dependency/scheduled_item_attachment_is_gated_on_the_property_enrollment
    """
    zone = create_zone(zone_code="ZO1G", wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code="AG14G")
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"], dwelling_cost_cents=200_000_000)
    run_posture_eval(prop["id"])
    # The zone is ELEVATED/OUTSIDE_WUI so the WUI referral branch does not fire
    # (PRD §2.9) and the enrollment can be submitted and approved outright.
    prop = reload_property(prop["id"])
    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=300_000_000)
    submit_enrollment(enroll["id"], agency["id"])
    _doc, item = file_document_and_schedule(
        prop["id"], item_type="JEWELRY", declared_value_cents=50_000_000,
        appraised_value_cents=60_000_000)
    approved = validate_success(
        api_client.approve_scheduled_item(item["id"], underwriter_headers), 200)
    assert approved["status"] == "APPROVED"
    assert approved["attached_value_cents"] == 50_000_000

    # The item contributes to the property totals while merely APPROVED.
    assert reload_property(prop["id"])["scheduled_valuation_cents"] == 50_000_000

    prop = reload_property(prop["id"])
    binding = validate_success(
        api_client.approve_enrollment(enroll["id"], underwriter_headers), 200)
    validate_success(api_client.attach_enrollment(
        binding["id"], reload_property(prop["id"])["version"], underwriter_headers), 200)

    # The bind carries the item across: it is now ATTACHED.
    rows = get_success_data(api_client.list_scheduled_items(
        prop["id"], underwriter_headers, params={"status": "ATTACHED"}))
    assert len(rows) == 1
    assert rows[0]["attached_value_cents"] == 50_000_000


def test_an_item_one_cent_over_the_aggregate_cap_is_refused(
        api, underwriter_headers, platform_admin_headers):
    """PRD 3.2: "the sum of `declared_value_cents` across the property's items already
    in status `APPROVED` or `ATTACHED`, counted together with the item under approval,
    must not exceed 60 percent of the property's `total_insured_value_cents`; a breach
    is refused with `ERR_SCHEDULED_VALUE_CAP`."

    Design: Difficulty/boundary_precision_check/scheduled_aggregate_cap_exactly_at_boundary_is_accepted
    """
    zone, agency, prop = create_underwritable_setup(zone_code="ZCAP2",
                                                    agency_code="AGCAP2")
    # With one 50000000 item approved first, the total insured value becomes
    # 250000000 and the inclusive bound on the aggregate is exactly 150000000.
    _doc0, seed = file_document_and_schedule(
        prop["id"], item_type="COLLECTION", declared_value_cents=50_000_000,
        appraised_value_cents=60_000_000)
    validate_success(api_client.approve_scheduled_item(seed["id"], underwriter_headers), 200)
    assert reload_property(prop["id"])["total_insured_value_cents"] == 250_000_000

    # 50000000 + 100000000 lands exactly on the 150000000 line; one cent more
    # drives the aggregate past it.
    _doc1, at_line = file_document_and_schedule(
        prop["id"], item_type="FINE_ART", declared_value_cents=100_000_000,
        appraised_value_cents=150_000_000)
    accepted = validate_success(
        api_client.approve_scheduled_item(at_line["id"], underwriter_headers), 200)
    assert accepted["status"] == "APPROVED"
    assert reload_property(prop["id"])["scheduled_valuation_cents"] == 150_000_000

    # Approving the second item lifts the property's total insured value to
    # 250000000 + 100000000 = 350000000, so the inclusive bound on the aggregate
    # is 0.60 x 350000000 = 210000000.  With 150000000 occupied, 60000000 lands
    # exactly on the line and one cent more drives the aggregate past it.
    _doc2, over = file_document_and_schedule(
        prop["id"], item_type="WINE", declared_value_cents=60_000_001,
        appraised_value_cents=90_000_000)
    res = api_client.approve_scheduled_item(over["id"], underwriter_headers)
    validate_error(res, "ERR_SCHEDULED_VALUE_CAP", expected_status=422)
