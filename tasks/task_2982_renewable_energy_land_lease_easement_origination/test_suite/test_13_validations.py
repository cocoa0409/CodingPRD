"""Business-gate claims: waiver limits, uniqueness pairs, gate order and running totals."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_DUPLICATE_INVOICE_PERIOD,
    ERR_PARCEL_APN_DUPLICATE,
    ERR_PARCEL_NOT_FOUND,
    ERR_PROHIBITED_ZONING,
    ERR_SECURITY_OVERPOSTED,
    ERR_WAIVER_LIMIT_REACHED,
)
from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_null,
    assert_page_meta,
    assert_score_equals,
    assert_status,
)
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.factories import invoice_payload, option_payload, parcel_payload
from test_helpers.fixtures import (
    accept_option,
    client,
    draft_option,
    execute_option,
    exercise_option,
    lease_version,
    parcels_page,
    post_security,
    raise_curative,
    raise_invoice,
    read_curative,
    read_invoice,
    read_landowner,
    read_lease,
    read_parcel,
    register_landowner,
    register_parcel,
    record_memo,
    send_option,
    submit_memo,
    void_invoice,
    waive_curative,
)
from test_helpers.test_users import (
    LAND_AGENT,
    PAYMENT_ADMIN,
    TITLE_COUNSEL,
    TITLE_COUNSEL_2,
)

SANDHILL = {
    "legal_name": "Sandhill Prairie LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "ops@sandhill.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CLEAN_COUNTY = "48451"

CLEAN_INPUTS = {
    "county_fips": CLEAN_COUNTY,
    "gross_acres": 200.00,
    "interconnection_distance_km": 3.50,
    "resource_capacity_factor": 0.38,
    "slope_pct": 4.0,
    "title_condition_grade": "B",
    "zoning_code": "AG2",
}


def _owner_and_tract(apn: str = "R-9001-001", **overrides):
    """One owner and one clean two-hundred-acre tract in an unregulated county."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    inputs = dict(CLEAN_INPUTS)
    inputs.update(overrides)
    parcel = register_parcel(landowner_id, apn=apn, **inputs)
    return landowner_id, parcel


def _parcel_with_one_waiver_already_spent():
    """A blocking defect already accepted on the record, and its successor released."""
    landowner_id, parcel = _owner_and_tract()
    first = raise_curative(
        parcel["id"],
        TITLE_COUNSEL,
        item_type="MINERAL_SEVERANCE",
        severity="BLOCKING",
        curative_cost_cents=250000,
    )
    second = raise_curative(
        parcel["id"],
        TITLE_COUNSEL,
        item_type="MORTGAGE_SUBORDINATION",
        severity="BLOCKING",
        curative_cost_cents=180000,
        blocks_item_id=first["id"],
    )
    waive_curative(
        first["id"],
        TITLE_COUNSEL_2,
        waiver_note="Mineral owner non-development letter accepted by counsel",
    )
    assert_status(read_curative(second["id"]), "OPEN", "item B")
    assert read_parcel(parcel["id"])["waived_blocking_count"] == 1
    return landowner_id, parcel["id"], second["id"]


def test_the_second_waiver_on_one_parcel_is_refused_at_the_limit():
    """
    Every earlier gate passes — the item is open, its predecessor is resolved, and
    counsel is not the raiser — so the only thing that can refuse this request is the
    one-waiver-per-parcel ceiling, and the item is left exactly as it was.

    PRD: "One further constraint applies only to waivers of `BLOCKING` items: at most
    one blocking defect per parcel may be waived rather than cured, so the waiver is
    admitted only while the parcel's `waived_blocking_count` is still below 1, and the
    second attempt is refused with `ERR_WAIVER_LIMIT_REACHED` (422)."

    Design: Corner/validations/waive_second_blocking_defect_rejects_at_the_waiver_limit
    """
    _landowner_id, _parcel_id, second_id = _parcel_with_one_waiver_already_spent()

    response = client().waive_curative_item(
        second_id,
        {"waiver_note": "Lender declined to subordinate; accepting the risk"},
        TITLE_COUNSEL_2,
    )

    validate_error(response, ERR_WAIVER_LIMIT_REACHED, 422)
    item = read_curative(second_id)
    assert_status(item, "OPEN", "item B")
    assert_null(item["cleared_at"], "cleared_at")
    assert_null(item["cleared_by_user_id"], "cleared_by_user_id")


def test_the_refused_waiver_moves_neither_counter_on_the_parcel():
    """
    A rejected waiver must not increment the waiver count, must not resolve the
    still-open blocking defect, and must not capitalise the cost it never accepted.

    PRD: "Three counters on the parcel are maintained by the title workflow of §3.4
    rather than by screening: `blocking_curative_open_count`, the number of `BLOCKING`
    items still in `BLOCKED` or `OPEN`; `waived_blocking_count`, the number of
    `BLOCKING` items that reached `WAIVED`; and `curative_cost_cents`, the sum of
    `curative_cost_cents` over the items on this parcel that reached `CLEARED`."

    Design: Corner/validations/waive_second_blocking_defect_rejects_at_the_waiver_limit
    """
    _landowner_id, parcel_id, second_id = _parcel_with_one_waiver_already_spent()

    response = client().waive_curative_item(
        second_id,
        {"waiver_note": "Lender declined to subordinate; accepting the risk"},
        TITLE_COUNSEL_2,
    )
    validate_error(response, ERR_WAIVER_LIMIT_REACHED, 422)

    parcel = read_parcel(parcel_id)
    assert parcel["waived_blocking_count"] == 1, parcel["waived_blocking_count"]
    assert parcel["blocking_curative_open_count"] == 1, (
        parcel["blocking_curative_open_count"]
    )
    assert_cents_equals(parcel["curative_cost_cents"], 0, "curative_cost_cents")
    assert_status(parcel, "SCREENING", "parcel")


def test_a_prohibited_zoning_designation_is_refused_as_a_business_gate():
    """
    The designation is a perfectly well-formed twelve-character-or-less string, so
    the shape gate has nothing to say: it is the business gate that refuses it, with
    422 rather than 400, and no parcel is screened or stored.

    PRD: "And a parcel whose `zoning_code` is one of the two prohibited designations,
    `RES1` or `CONS1`, can never be optioned and is refused outright with
    `ERR_PROHIBITED_ZONING` (422)."

    Design: Corner/validations/prohibited_zoning_code_rejects_parcel_registration
    """
    landowner_id = register_landowner(**SANDHILL)["id"]

    payload = parcel_payload(landowner_id, apn="R-9004-001", **CLEAN_INPUTS)
    payload["zoning_code"] = "RES1"
    response = client().create_parcel(payload, LAND_AGENT)

    validate_error(response, ERR_PROHIBITED_ZONING, 422)
    _rows, meta = parcels_page(LAND_AGENT, landowner_id=landowner_id)
    assert_page_meta(meta, total_count=0)
    assert_status(read_landowner(landowner_id), "PROSPECT", "landowner")


def test_the_same_assessor_number_in_the_same_county_is_refused():
    """
    The second registration claims a pair already on the books. It is refused with a
    conflict, and — the point of the gate — the first parcel's derived acreage and
    score are not overwritten by the second body's very different inputs.

    PRD: "The pair of `apn` and `county_fips` must be unique across the portfolio; a
    second parcel claiming the same pair is refused with `ERR_PARCEL_APN_DUPLICATE`
    (409)."

    Design: Corner/validations/duplicate_apn_within_the_same_county_rejects_the_second_parcel
    """
    landowner_id, first = _owner_and_tract(apn="R-7000-001")

    response = client().create_parcel(
        parcel_payload(
            landowner_id,
            apn="R-7000-001",
            county_fips=CLEAN_COUNTY,
            gross_acres=90.00,
            interconnection_distance_km=1.00,
            resource_capacity_factor=0.30,
            slope_pct=12.0,
            title_condition_grade="D",
            zoning_code="AG2",
        ),
        LAND_AGENT,
    )

    validate_error(response, ERR_PARCEL_APN_DUPLICATE, 409)
    _rows, meta = parcels_page(LAND_AGENT, landowner_id=landowner_id)
    assert_page_meta(meta, total_count=1)
    kept = read_parcel(first["id"])
    assert_acres_equals(kept["gross_acres"], 200.00, "gross_acres")
    assert_acres_equals(kept["buildable_acres"], 200.00, "buildable_acres")
    assert_score_equals(kept["screening_score"], 82.15, "screening_score")


def test_the_same_assessor_number_in_another_county_is_accepted():
    """
    The satisfying side of the same composite key: only one of the two components
    matches, so the second tract is registered and screened on its own inputs, and
    the county filter separates them.

    PRD: "The pair of `apn` and `county_fips` must be unique across the portfolio; a
    second parcel claiming the same pair is refused with `ERR_PARCEL_APN_DUPLICATE`
    (409)."

    Design: Corner/validations/same_apn_in_a_different_county_passes_the_uniqueness_gate
    """
    landowner_id, _first = _owner_and_tract(apn="R-7000-001")

    response = client().create_parcel(
        parcel_payload(
            landowner_id,
            apn="R-7000-001",
            county_fips="48029",
            gross_acres=120.00,
            interconnection_distance_km=3.50,
            resource_capacity_factor=0.38,
            slope_pct=4.0,
            title_condition_grade="B",
            zoning_code="AG2",
        ),
        LAND_AGENT,
    )

    second = validate_success(response, 201)
    assert second["county_fips"] == "48029", second["county_fips"]
    assert_acres_equals(second["buildable_acres"], 120.00, "buildable_acres")
    assert_score_equals(second["screening_score"], 82.15, "screening_score")
    assert_status(second, "QUALIFIED", "parcel")
    _rows, owner_meta = parcels_page(LAND_AGENT, landowner_id=landowner_id)
    assert_page_meta(owner_meta, total_count=2)
    _rows, county_meta = parcels_page(LAND_AGENT, county_fips=CLEAN_COUNTY)
    assert_page_meta(county_meta, total_count=1)


def test_the_unknown_parcel_outranks_the_undeclared_enum_member_beside_it():
    """
    One body breaks two rules at once: it names a parcel that does not exist and it
    names a rent structure that is not a declared member. Existence is checked before
    request shape, so the answer is the four-oh-four.

    PRD: "The ladder runs authentication, then authorisation, then existence, then
    request shape, then optimistic concurrency, then instrument expiry, then generic
    state admissibility, then title and security compliance, then deal-structure
    constraints, then temporal conflicts, and finally money."

    Design: Corner/validations/parcel_not_found_outranks_the_invalid_enum_on_option_create
    """
    landowner = register_landowner(**SANDHILL)
    payload = option_payload(
        UNKNOWN_UUID,
        landowner["id"],
        landowner["version"],
        rent_structure_type="PROFIT_SHARE",
        base_rent_per_acre_cents=120000,
    )

    response = client().create_option_agreement(payload, LAND_AGENT)

    validate_error(response, ERR_PARCEL_NOT_FOUND, 404)
    _rows, meta = validate_paginated(
        client().list_option_agreements(LAND_AGENT, {"landowner_id": landowner["id"]})
    )
    assert_page_meta(meta, total_count=0)


def _exercised_lease_on_two_hundred_acres():
    """A lease originated over two hundred as-built acres, security unposted."""
    landowner_id, parcel = _owner_and_tract()
    option = draft_option(
        parcel["id"],
        landowner_id,
        option_term_days=365,
        option_fee_per_acre_cents=2500,
        extension_count_allowed=1,
        extension_fee_per_acre_cents=3000,
        rent_structure_type="PER_ACRE",
        base_rent_per_acre_cents=120000,
        royalty_rate_bps=0,
        escalator_pct_bps=200,
        escalator_mode="SIMPLE",
    )
    send_option(option["id"])
    accept_option(option["id"], landowner_id)
    execute_option(option["id"])
    lease = exercise_option(option["id"], "NOE-2026-0001")
    assert_acres_equals(
        lease["acre_basis_at_exercise"], 200.00, "acre_basis_at_exercise"
    )
    assert_cents_equals(
        lease["total_security_required_cents"], 10450000, "total_security_required_cents"
    )
    return landowner_id, parcel["id"], option["id"], lease


def test_an_instalment_that_would_overshoot_the_requirement_is_refused():
    """
    Five thousand dollars is far below the requirement on its own, but the gate reads
    the running total: added to what is already posted it would overshoot by fifty
    thousand cents, so it is refused and the posted balance does not move.

    PRD: "Over-posting is refused: if `security_posted_cents` plus the supplied
    `amount_cents` would exceed `total_security_required_cents`, the posting fails with
    `ERR_SECURITY_OVERPOSTED` (422)."

    Design: Corner/validations/post_security_above_the_requirement_rejects_as_overposted
    """
    _landowner_id, _parcel_id, _option_id, lease = _exercised_lease_on_two_hundred_acres()
    post_security(lease["id"], 10000000)

    response = client().post_security(lease["id"], {"amount_cents": 500000}, PAYMENT_ADMIN)

    validate_error(response, ERR_SECURITY_OVERPOSTED, 422)
    after = read_lease(lease["id"])
    assert_cents_equals(
        after["security_posted_cents"], 10000000, "security_posted_cents"
    )
    assert_cents_equals(
        after["total_security_required_cents"], 10450000, "total_security_required_cents"
    )


def test_the_instalment_that_lands_exactly_on_the_requirement_is_accepted():
    """
    The gate refuses only what would exceed the requirement, so the four-hundred-and
    -fifty-thousand-cent balance owed is admitted and brings the posting exactly level
    with what was required.

    PRD: "Because over-posting is impossible, "fully posted" and "exactly posted"
    coincide."

    Design: Corner/validations/post_security_above_the_requirement_rejects_as_overposted
    """
    _landowner_id, _parcel_id, _option_id, lease = _exercised_lease_on_two_hundred_acres()
    post_security(lease["id"], 10000000)
    refused = client().post_security(lease["id"], {"amount_cents": 500000}, PAYMENT_ADMIN)
    validate_error(refused, ERR_SECURITY_OVERPOSTED, 422)

    post_security(lease["id"], 450000)

    assert_cents_equals(
        read_lease(lease["id"])["security_posted_cents"],
        10450000,
        "security_posted_cents",
    )


def _recorded_lease_with_one_draft_invoice():
    """A recorded lease already carrying a draft invoice for its first year."""
    _landowner_id, _parcel_id, _option_id, lease = _exercised_lease_on_two_hundred_acres()
    post_security(lease["id"], 10450000)
    submit_memo(lease["id"])
    recorded = record_memo(lease["id"], "2026-0091001")
    assert recorded["recording_status"] == "RECORDED", recorded["recording_status"]
    invoice = raise_invoice(lease["id"], period_year=1, production_mwh=0)
    return lease["id"], invoice


def test_a_still_draft_invoice_already_occupies_its_period_year():
    """
    The period is taken by an invoice that has not even been issued yet, and the
    second attempt quotes a freshly read lease version so the concurrency gate cannot
    be the one answering: the duplicate-period conflict is.

    PRD: "`period_year` is 1-based and must be an integer from 1 to 35, matching the
    lease's thirty-five-year term; a `period_year` outside that range, or one for which
    the lease already carries an invoice in `DRAFT`, `ISSUED` or `PAID`, is refused with
    `ERR_DUPLICATE_INVOICE_PERIOD` (409)."

    Design: Corner/validations/duplicate_invoice_period_rejects_a_second_draft_for_the_same_year
    """
    lease_id, first = _recorded_lease_with_one_draft_invoice()

    response = client().create_rent_invoice(
        lease_id, invoice_payload(lease_version(lease_id), 1, 0), PAYMENT_ADMIN
    )

    validate_error(response, ERR_DUPLICATE_INVOICE_PERIOD, 409)
    kept = read_invoice(first["id"])
    assert_status(kept, "DRAFT", "invoice")
    assert kept["rent_variant"] == "FINAL_AS_BUILT", kept["rent_variant"]
    assert_acres_equals(kept["acre_basis"], 200.00, "acre_basis")
    assert_cents_equals(kept["gross_rent_cents"], 24000000, "gross_rent_cents")
    _rows, meta = validate_paginated(
        client().list_rent_invoices(PAYMENT_ADMIN, {"lease_agreement_id": lease_id})
    )
    assert_page_meta(meta, total_count=1)


def test_voiding_the_first_invoice_frees_its_period_year_again():
    """
    Occupancy is a property of the live statuses only, so the void-and-replace path
    reopens the year: the same create that was just refused now succeeds.

    PRD: "A voided invoice frees its `period_year`, so a period first billed
    provisionally can be re-billed as a final as-built figure once the memorandum has
    been recorded — that is the intended use of the void-and-replace path."

    Design: Corner/validations/duplicate_invoice_period_rejects_a_second_draft_for_the_same_year
    """
    lease_id, first = _recorded_lease_with_one_draft_invoice()
    refused = client().create_rent_invoice(
        lease_id, invoice_payload(lease_version(lease_id), 1, 0), PAYMENT_ADMIN
    )
    validate_error(refused, ERR_DUPLICATE_INVOICE_PERIOD, 409)

    void_invoice(first["id"], void_reason="Re-billing the first year as built")

    response = client().create_rent_invoice(
        lease_id, invoice_payload(lease_version(lease_id), 1, 0), PAYMENT_ADMIN
    )
    replacement = validate_success(response, 201)
    assert_status(replacement, "DRAFT", "replacement invoice")
    assert replacement["period_year"] == 1, replacement["period_year"]
    assert_cents_equals(replacement["gross_rent_cents"], 24000000, "gross_rent_cents")
    assert_status(read_invoice(first["id"]), "VOID", "voided invoice")
