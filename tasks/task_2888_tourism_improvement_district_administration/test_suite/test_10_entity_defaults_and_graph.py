"""Stored shapes: declared defaults, server-resolved fields and the entity graph.

These tests read entities back rather than driving workflows.  They pin the
values the specification says a creation call must apply when the client supplies
nothing, the fields the server resolves on its own, the 404 an unresolved
reference produces, and the way a junction row is reachable from both of the
parents it joins.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ASSESSMENT_STATEMENT_NOT_FOUND,
    ERR_BUSINESS_OUTSIDE_BOUNDARY,
    ERR_DISTRICT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_REMITTANCE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_pagination_meta,
    assert_ratio_four_dp,
    ids_of,
)
from test_helpers.test_users import ADMIN, DMO_LIAISON, operator_headers

UNKNOWN_ID = "00000000-0000-4000-8000-00000000dead"
UNKNOWN_DISTRICT_ID = "00000000-0000-4000-8000-0000000000d0"


def test_a_district_proposed_with_a_name_alone_lands_on_every_declared_default(api):
    """Supplying only `name` leaves the server to apply the eight documented
    optional defaults and the documented initial state.

    PRD 3.1: "`assessment_method` chooses which branch of the assessment
    calculation the district's statements will run and takes one of
    PCT_OF_ROOM_REVENUE, PER_OCCUPIED_ROOM_NIGHT or TIERED_BY_CLASSIFICATION,
    defaulting to PCT_OF_ROOM_REVENUE. ... it must be a non-empty subset of
    ZONE_CORE and ZONE_PERIMETER, must not repeat a code, and defaults to both
    zones. ... `formation_threshold_pct` ... defaults to 0.6000;
    `renewal_threshold_pct` ... defaults to 0.6500; and
    `renewal_headcount_threshold_pct` is an additional headcount minimum that
    binds only on renewal drives, defaulting to 0.5000. `term_years` ... defaults
    to 5 ... `current_fiscal_year` ... defaults to 2027".

    Design: Corner/entities/district_creation_applies_every_declared_default
    """
    fx.pin_clock_to_origin(api)

    district = validate_success(
        api.create_district(
            {"name": "Default Bay Tourism Improvement District"}, headers=ADMIN
        ),
        expected_status=201,
    )
    assert_fields(
        district,
        assessment_method="PCT_OF_ROOM_REVENUE",
        included_zones=["ZONE_CORE", "ZONE_PERIMETER"],
        term_years=5,
        current_fiscal_year=2027,
        status="PROPOSED",
        transparency_standing="COMPLIANT",
        dmo_agreement_status="NONE",
        collected_to_date_cents=0,
        delinquent_charges_cents=0,
        assessable_basis_cents=0,
        assessable_business_count=0,
        version=1,
    )
    assert_ratio_four_dp(district["formation_threshold_pct"], 0.6000, "formation_threshold_pct")
    assert_ratio_four_dp(district["renewal_threshold_pct"], 0.6500, "renewal_threshold_pct")
    assert_ratio_four_dp(
        district["renewal_headcount_threshold_pct"], 0.5000, "renewal_headcount_threshold_pct"
    )
    assert_null_fields(district, "dmo_name", "formed_on", "expiration_date")


def test_property_creation_resolves_its_own_status_and_rolls_up_the_district(api):
    """The four roll properties are each created with the six required inputs and
    no optional ones, so the server resolves their status and standing itself and
    the district's two aggregates land on the sum and the count of the roll.

    PRD 3.1: "Creation also initialises `delinquency_strike_count` to 0 and
    `compliance_standing` to GOOD, then recomputes the district's assessable
    aggregates and re-scores every open petition drive of the district."

    Design: Corner/entities/lodging_business_creation_defaults_and_rolls_up_the_district_totals
    """
    ctx = fx.district_with_roll(api)

    cottages = validate_success(api.get_lodging_business(ctx.b4_id, headers=ADMIN))
    assert_fields(
        cottages,
        legal_name="Cove Cottages",
        status="ASSESSABLE",
        exempt_status="NONE",
        remittance_frequency="MONTHLY",
        delinquency_strike_count=0,
        compliance_standing="GOOD",
        version=1,
    )

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, assessable_basis_cents=100000000, assessable_business_count=4)


def test_a_single_district_read_is_served_with_no_headers_at_all(api):
    """The single-district read is one of the ten published public operations, so a
    request carrying neither header returns the stored row rather than a 401.

    PRD 2.1: "Ten read operations are published for the general public and are
    served with no headers at all, because publication is the point of them: the
    district list, a single district, a district's financial summary, a district's
    petition drives, a district's annual work plans, a district's transparency
    records, a single petition drive, a single annual work plan, a single
    marketing program, and a single transparency record. On those ten the header
    requirement is waived entirely and ERR_UNAUTHENTICATED cannot arise."

    Design: Corner/entities/public_district_retrieval_returns_the_stored_row_with_no_headers
    """
    ctx = fx.district_with_roll(api)

    response = api.get_district(ctx.d_id)
    assert response.status_code == 200, (
        "a header-free public read returned %s: %s" % (response.status_code, response.text)
    )
    district = validate_success(response)
    assert_fields(
        district,
        name="Harbor Bay Tourism Improvement District",
        assessment_method="PCT_OF_ROOM_REVENUE",
        included_zones=["ZONE_CORE", "ZONE_PERIMETER"],
        term_years=1,
        status="PROPOSED",
    )
    assert_ratio_four_dp(district["formation_threshold_pct"], 0.6000, "formation_threshold_pct")

    envelope = response.json()
    assert envelope["response_type"] == "object", (
        "response_type was %r" % envelope["response_type"]
    )
    assert "api_request_id" in envelope["meta"], "meta lacked api_request_id"
    assert "api_request_timestamp" in envelope["meta"], "meta lacked api_request_timestamp"


def test_the_roll_listing_paginates_and_filters_before_it_paginates(api):
    """Two pages of two properties cover the four-property roll, and a zone filter
    narrows total_count while leaving the default limit of 10 in place.

    PRD 2.3: "The `limit` parameter caps the number of records returned; it
    defaults to 10 when omitted ... Filter parameters offered by individual list
    operations — for example `status`, `filing_status`, `payment_status`,
    `boundary_zone`, `drive_type`, `record_type`, `dispute_type`, `channel`,
    `fiscal_year` and `lodging_business_id` — narrow the result set before
    pagination is applied, so `total_count` always reflects the filtered set
    rather than the whole collection."

    Design: Corner/entities/lodging_business_listing_paginates_with_total_count_and_has_more
    """
    ctx = fx.district_with_roll(api)

    page1, meta1 = validate_paginated(
        api.list_district_lodging_businesses(ctx.d_id, headers=ADMIN, params={"limit": 2, "offset": 0})
    )
    assert_pagination_meta(meta1, limit=2, offset=0, total_count=4, has_more=True)
    assert ids_of(page1) == [ctx.b1_id, ctx.b2_id], "page 1 held %s" % ids_of(page1)

    page2, meta2 = validate_paginated(
        api.list_district_lodging_businesses(ctx.d_id, headers=ADMIN, params={"limit": 2, "offset": 2})
    )
    assert_pagination_meta(meta2, limit=2, offset=2, total_count=4, has_more=False)
    assert ids_of(page2) == [ctx.b3_id, ctx.b4_id], "page 2 held %s" % ids_of(page2)

    perimeter, meta3 = validate_paginated(
        api.list_district_lodging_businesses(
            ctx.d_id, headers=ADMIN, params={"boundary_zone": "ZONE_PERIMETER"}
        )
    )
    assert_pagination_meta(meta3, limit=10, offset=0, total_count=2, has_more=False)
    assert ids_of(perimeter) == [ctx.b3_id, ctx.b4_id], "the filtered page held %s" % ids_of(
        perimeter
    )


def test_an_unknown_statement_id_answers_with_its_own_not_found_code(api):
    """A well-formed identifier naming no stored statement produces the statement's
    own 404 rather than an empty 200 or the generic shape error.

    PRD 2.8: "Existence — path identifiers are resolved left to right, and then
    body foreign keys in the order the fields are declared for that operation; the
    first unresolved reference decides which 404 is returned, from
    ERR_DISTRICT_NOT_FOUND, ERR_LODGING_BUSINESS_NOT_FOUND,
    ERR_PETITION_DRIVE_NOT_FOUND, ERR_PETITION_SIGNATURE_NOT_FOUND,
    ERR_ASSESSMENT_PERIOD_NOT_FOUND, ERR_ASSESSMENT_STATEMENT_NOT_FOUND,
    ERR_REMITTANCE_NOT_FOUND, ERR_WORK_PLAN_NOT_FOUND,
    ERR_MARKETING_PROGRAM_NOT_FOUND, ERR_ROOM_NIGHT_CLAIM_NOT_FOUND,
    ERR_TRANSPARENCY_RECORD_NOT_FOUND and ERR_DISPUTE_NOT_FOUND."

    Design: Corner/entities/unknown_assessment_statement_id_returns_not_found
    """
    fx.district_with_roll(api)

    response = api.get_assessment_statement(UNKNOWN_ID, headers=ADMIN)
    validate_error(response, ERR_ASSESSMENT_STATEMENT_NOT_FOUND, expected_status=404)
    assert response.json()["response_type"] == "error", (
        "response_type was %r" % response.json()["response_type"]
    )


def test_a_filing_that_omits_the_revenue_field_leaves_the_statement_untouched(api):
    """Both reported figures are required inputs, so a filing naming only the room
    nights is refused on shape and the statement is not half-filed.

    PRD 3.3: "An operator files its period figures by supplying
    `reported_room_nights` and `reported_gross_room_revenue_cents`, each an
    integer that may not be negative."

    Design: Corner/entities/assessment_filing_missing_the_revenue_field_is_rejected
    """
    ctx = fx.active_district(api)
    fx.open_period(api, ctx)
    fx.generate_statements(api, ctx)
    fx.index_statements(api, ctx)

    response = api.file_statement(
        ctx.st1_id, {"reported_room_nights": 2000}, headers=operator_headers(ctx.b1_id)
    )
    validate_error(response, ERR_INVALID_REQUEST, expected_status=400)

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(
        statement,
        filing_status="NOT_FILED",
        provisional_assessment_cents=0,
        effective_assessment_cents=0,
        version=1,
    )
    assert_null_fields(statement, "reported_room_nights", "reported_gross_room_revenue_cents")


def test_a_signature_takes_its_weight_from_the_signers_roll_row(api):
    """The request names only the signing property, yet the stored signature
    carries that property's prior-year revenue and the drive's numerator moves by
    exactly that figure.

    PRD 3.2: "The new signature stores its `petition_drive_id`, stamps `signed_at`
    from the logical clock, and — critically — captures
    `weight_basis_revenue_cents` as a snapshot of the signer's
    `prior_year_gross_room_revenue_cents` at the moment of signing, which is never
    re-read afterwards."

    Design: Corner/entities/petition_signature_weight_basis_is_computed_from_the_signer_roll_row
    """
    ctx = fx.district_with_roll(api)
    fx.open_formation_drive(api, ctx)

    fx.sign(api, ctx, "b3_id")
    signature = validate_success(api.get_petition_signature(ctx.sig_b3, headers=ADMIN))
    assert_fields(
        signature,
        weight_basis_revenue_cents=15000000,
        status="VALID",
        disqualification_reason="NONE",
        petition_drive_id=ctx.pd_id,
        lodging_business_id=ctx.b3_id,
    )
    assert_instant_equals(signature["signed_at"], "2026-08-01T00:00:00Z", "signed_at")

    drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(drive, signed_basis_cents=15000000, valid_signature_count=1)
    assert_ratio_four_dp(drive["weighted_support_pct"], 0.1500, "weighted_support_pct")


def test_a_dispute_copies_the_billed_property_and_grants_nothing_yet(api):
    """The dispute payload never names a property, and the amount asked for is
    recorded as claimed rather than granted.

    PRD 3.5: "The dispute is created with `status` SUBMITTED, `filed_on` stamped
    from the logical clock, `granted_adjustment_cents` 0, `appeal_count` 0, and
    `resolved_by_user_id` and `resolution_note` null. Its `lodging_business_id` is
    copied from the referenced statement and is never supplied by the client, so a
    dispute can never be attributed to a property other than the one billed."

    Design: Corner/entities/dispute_creation_stamps_its_system_fields_and_copies_the_business_id
    """
    ctx = fx.statements_filed(api)

    dispute = validate_success(
        api.create_dispute(
            f.dispute_payload(
                ctx.st1_id,
                dispute_type="CALCULATION_ERROR",
                claimed_adjustment_cents=82450,
                dispute_note="resort fee should not sit in the revenue basis",
            ),
            headers=operator_headers(ctx.b1_id),
        ),
        expected_status=201,
    )
    assert_fields(
        dispute,
        lodging_business_id=ctx.b1_id,
        assessment_statement_id=ctx.st1_id,
        status="SUBMITTED",
        claimed_adjustment_cents=82450,
        granted_adjustment_cents=0,
        appeal_count=0,
        version=1,
    )
    assert_instant_equals(dispute["filed_on"], "2026-08-01T00:00:00Z", "filed_on")
    assert_null_fields(dispute, "resolved_by_user_id", "resolution_note")

    statement = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(statement, effective_assessment_cents=824500)


def test_four_shape_violations_on_three_endpoints_all_answer_at_the_shape_rung(api):
    """An undeclared enum member, a repeated zone code, a negative cent amount and
    an interval whose start equals its end are each refused on shape, and nothing
    is stored.

    PRD 2.8: "Request shape — every non-optional input field is present; every
    enum-typed field carries a declared member; every cent-valued field is an
    integer that is not negative; every date or instant field parses as ISO 8601;
    every interval field has its start strictly before its end. Any failure here is
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/creation_endpoints_reject_undeclared_enums_negative_cents_and_inverted_intervals
    """
    fx.pin_clock_to_origin(api)
    ctx = fx.create_district(api)

    bad_requests = (
        api.create_district(
            {"name": "Bad Method District", "assessment_method": "FLAT_FEE_PER_ROOM"},
            headers=ADMIN,
        ),
        api.create_district(
            {"name": "Duplicate Zone District", "included_zones": ["ZONE_CORE", "ZONE_CORE"]},
            headers=ADMIN,
        ),
        api.create_lodging_business(
            f.lodging_business_payload(
                ctx.d_id,
                legal_name="Negative Revenue Inn",
                classification="LIMITED_SERVICE",
                room_count=10,
                prior_year_gross_room_revenue_cents=-1,
                operator_contact_email="ops@negative.example",
            ),
            headers=ADMIN,
        ),
        api.create_assessment_period(
            f.assessment_period_payload(
                ctx.d_id,
                period_label="FY2027-BAD",
                period_start="2026-11-01T00:00:00Z",
                period_end="2026-11-01T00:00:00Z",
                due_date="2026-11-15T00:00:00Z",
            ),
            headers=ADMIN,
        ),
    )
    for response in bad_requests:
        validate_error(response, ERR_INVALID_REQUEST, expected_status=400)

    districts, _ = validate_paginated(api.list_districts(params={"limit": 100}))
    names = [row["name"] for row in districts]
    assert "Bad Method District" not in names, "the undeclared-enum district was stored"
    assert "Duplicate Zone District" not in names, "the repeated-zone district was stored"

    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(district, assessable_business_count=0, assessable_basis_cents=0)

    _, meta = validate_paginated(
        api.list_district_assessment_periods(ctx.d_id, headers=ADMIN)
    )
    assert meta["total_count"] == 0, "a period was stored from the inverted interval"


def test_a_property_named_against_an_unknown_district_is_not_stored_as_an_orphan(api):
    """`district_id` is a body foreign key, so an id no district holds answers with
    the district's own 404 before any boundary or roll logic runs.

    PRD 2.8: "Existence — path identifiers are resolved left to right, and then
    body foreign keys in the order the fields are declared for that operation ...
    This applies to every operation carrying a path identifier or a body foreign
    key."

    Design: Corner/entities/lodging_business_under_an_unknown_district_returns_not_found
    """
    fx.pin_clock_to_origin(api)

    response = api.create_lodging_business(
        f.lodging_business_payload(
            UNKNOWN_DISTRICT_ID,
            legal_name="Orphan Lodge",
            room_count=50,
            prior_year_gross_room_revenue_cents=1000000,
            operator_contact_email="ops@orphan.example",
        ),
        headers=ADMIN,
    )
    validate_error(response, ERR_DISTRICT_NOT_FOUND, expected_status=404)

    _, meta = validate_paginated(api.list_districts(params={"limit": 100}))
    assert meta["total_count"] == 0, "a district exists although none was created"


def test_a_remittance_of_another_statement_is_not_reversible_through_this_one(api):
    """The payment exists but belongs to a sibling statement, so the reversal
    addressed through the first statement is a 404 and the sibling's buckets are
    left whole.

    PRD 2.8: "A supplied `remittance_id` that exists but belongs to a different
    statement than the one in the path is treated as not found and yields
    ERR_REMITTANCE_NOT_FOUND."

    Design: Corner/entities/reversal_naming_another_statements_remittance_returns_not_found
    """
    ctx = fx.statements_filed(api)
    remittance = fx.remit(api, ctx, "st2_id", "b2_id", 300000, method="ACH", key="rem_st2")

    response = api.reverse_remittance(
        ctx.st1_id,
        f.remittance_reversal_payload(remittance["id"], "posted against the wrong statement"),
        headers=ADMIN,
    )
    validate_error(response, ERR_REMITTANCE_NOT_FOUND, expected_status=404)

    untouched = validate_success(api.get_remittance(remittance["id"], headers=ADMIN))
    assert_fields(untouched, status="APPLIED")
    assert_null_fields(untouched, "reversed_on")

    st2 = validate_success(api.get_assessment_statement(ctx.st2_id, headers=ADMIN))
    assert_fields(st2, principal_paid_cents=300000, total_due_cents=40000)
    st1 = validate_success(api.get_assessment_statement(ctx.st1_id, headers=ADMIN))
    assert_fields(st1, principal_paid_cents=0, total_due_cents=824500)
    assert_fields(validate_success(api.get_district(ctx.d_id)), collected_to_date_cents=300000)


def test_a_signer_belonging_to_another_district_never_enters_this_drive(api):
    """The foreign signer is ASSESSABLE and sits in a zone the target district
    includes, yet it belongs to a different district, which is enough on its own to
    refuse the signature.

    PRD 3.2: "The signer must belong to the same district as the drive, must have a
    `boundary_zone` that is a member of the district's `included_zones`, and must
    have `status` ASSESSABLE; a failure of any of those three is
    ERR_BUSINESS_OUTSIDE_BOUNDARY."

    Design: Corner/entities/signature_from_a_business_of_another_district_is_rejected
    """
    ctx = fx.district_with_roll(api)
    fx.open_formation_drive(api, ctx)

    other = fx.create_district(api, name="Cliffside Tourism Improvement District", term_years=5)
    fx.add_business(
        api,
        other,
        f.lodging_business_payload(
            other.d_id,
            legal_name="Cliffside Arms Hotel",
            room_count=80,
            prior_year_gross_room_revenue_cents=30000000,
            operator_contact_email="ops@cliffsidearms.example",
        ),
        "b9_id",
    )

    response = api.sign_petition(ctx.pd_id, f.signature_payload(other.b9_id), headers=ADMIN)
    validate_error(response, ERR_BUSINESS_OUTSIDE_BOUNDARY, expected_status=409)

    foreigner = validate_success(api.get_lodging_business(other.b9_id, headers=ADMIN))
    assert_fields(foreigner, status="ASSESSABLE", boundary_zone="ZONE_CORE")

    drive = validate_success(api.get_petition_drive(ctx.pd_id))
    assert_fields(
        drive,
        valid_signature_count=0,
        signed_basis_cents=0,
        assessable_basis_snapshot_cents=100000000,
    )


def test_a_room_night_claim_reads_back_from_the_program_and_from_the_property(api):
    """The claim joins a program to a property, so both parents list it under the
    same id, and the program-side list filtered to a different property is empty.

    PRD 3.8: "Claims are readable per program — filterable by `status` and
    `lodging_business_id` — per property, and individually."

    Design: Corner/entities/room_night_claims_join_program_and_property_and_read_back_from_both_sides
    """
    ctx = fx.running_program(api)
    fx.set_clock(api, "2026-09-25T00:00:00Z")

    claim = validate_success(
        api.create_room_night_claim(
            ctx.mp_id,
            f.room_night_claim_payload(
                ctx.b3_id,
                stay_start="2026-09-10T00:00:00Z",
                stay_end="2026-09-12T00:00:00Z",
                room_nights=100,
            ),
            headers=DMO_LIAISON,
        ),
        expected_status=201,
    )
    assert_fields(
        claim,
        marketing_program_id=ctx.mp_id,
        lodging_business_id=ctx.b3_id,
        status="SUBMITTED",
        rejection_reason="NONE",
    )
    assert_null_fields(claim, "verified_room_nights", "verified_by_user_id")

    program_side, program_meta = validate_paginated(
        api.list_program_room_night_claims(ctx.mp_id, headers=DMO_LIAISON)
    )
    assert ids_of(program_side) == [claim["id"]], "program side held %s" % ids_of(program_side)
    assert program_meta["total_count"] == 1, "program-side total_count was %s" % program_meta[
        "total_count"
    ]

    business_side, business_meta = validate_paginated(
        api.list_business_room_night_claims(ctx.b3_id, headers=DMO_LIAISON)
    )
    assert ids_of(business_side) == [claim["id"]], "property side held %s" % ids_of(business_side)
    assert business_meta["total_count"] == 1, "property-side total_count was %s" % business_meta[
        "total_count"
    ]

    _, filtered_meta = validate_paginated(
        api.list_program_room_night_claims(
            ctx.mp_id, headers=DMO_LIAISON, params={"lodging_business_id": ctx.b2_id}
        )
    )
    assert filtered_meta["total_count"] == 0, (
        "the claim surfaced under a property that never made it"
    )
