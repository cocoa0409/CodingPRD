"""Reference-data and collateral registration: what the caller supplies and what
the platform seeds.

Three registrations (obligor, community, unit) are read back field by field, the
immutable guide edition is checked for the two audit fields it is *not* allowed
to carry, the unit listing is walked page by page, and four malformed or
unresolvable writes are refused without leaving a row behind.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_book_value_guide,
    assert_borrower,
    assert_community,
    assert_instant_equals,
    assert_manufactured_unit,
    factories,
    fixtures,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

PRINCIPAL_CENTS = 4600000
REQUESTED_TERM_MONTHS = 240

DANA = {
    "full_name": "Dana Whitfield",
    "credit_score": 705,
    "monthly_income_cents": 520000,
    "state_code": "GA",
}

PINE_RIDGE = {
    "name": "Pine Ridge MHC",
    "state_code": "GA",
    "lot_count": 180,
    "monthly_lot_rent_cents": 52000,
    "sales_commission_bps": 150,
}
CYPRESS_LANDING = {
    "name": "Cypress Landing MHC",
    "state_code": "GA",
    "lot_count": 96,
    "monthly_lot_rent_cents": 48000,
    "sales_commission_bps": 200,
}

# The one registration that leaves the single optional input out entirely.
RIVERBEND = {
    "name": "Riverbend Estates",
    "state_code": "GA",
    "lot_count": 64,
    "monthly_lot_rent_cents": 45000,
}

HUD_LABEL = "ALB0412345"
LOT_NUMBER = "A-14"
PLACEMENT_START_DATE = "2026-08-01T00:00:00Z"
UNIT_INPUTS = {
    "hud_label_number": HUD_LABEL,
    "manufacturer": "Clayton",
    "model_year": 2018,
    "width_class": "MULTI_WIDE",
    "square_feet": 1440,
    "condition_grade": "GOOD",
    "installation_type": "PIER_AND_ANCHOR",
    "wind_zone": 2,
    "lot_number": LOT_NUMBER,
    "placement_start_date": PLACEMENT_START_DATE,
}

# Three lots in the first park and one in the second.
FIRST_PARK_LOTS = ("A-01", "A-02", "A-03")
OTHER_PARK_LOT = "B-01"
PAGE_LIMIT = 2

GUIDE_EDITION = "NADA-2026-SPRING"
CORRECTED_EDITION = "NADA-2026-SPRING-R2"
GUIDE_EFFECTIVE_DATE = "2026-01-01T00:00:00Z"
BASE_VALUE_PER_SQFT_CENTS = 4500
ANNUAL_DEPRECIATION_BPS = 350


def _community_with_three_units_and_a_neighbouring_park(api):
    """Three units on distinct lots of one park, one unit in a second park."""
    first = fixtures.register_community(api, **PINE_RIDGE)
    second = fixtures.register_community(api, **CYPRESS_LANDING)
    inside = [
        fixtures.register_community_unit(api, first["id"], lot_number=lot)
        for lot in FIRST_PARK_LOTS
    ]
    outside = fixtures.register_community_unit(
        api, second["id"], lot_number=OTHER_PARK_LOT
    )
    return {
        "first": first,
        "second": second,
        "inside": inside,
        "outside": outside,
    }


def _certified_collateral_without_an_obligor(api):
    """A community unit carrying a CERTIFIED ORIGINATION valuation and nothing else."""
    guide = fixtures.publish_guide(api)
    community = fixtures.register_community(api, **PINE_RIDGE)
    unit = fixtures.register_community_unit(api, community["id"])
    valuation = fixtures.create_certified_valuation(
        api, unit["id"], guide["id"], "ORIGINATION"
    )
    return {
        "guide": guide,
        "community": community,
        "unit": unit,
        "valuation": valuation,
    }


def test_borrower_registration_echoes_its_inputs_and_seeds_every_system_field(api):
    """PRD §3.1: "An obligor is registered with a `full_name`, a `credit_score`
    between 300 and 850 inclusive, a `monthly_income_cents` figure of zero or more
    representing verified monthly income, and a two-letter `state_code` for the
    obligor's residence."
    PRD §3.1: "Three fields are managed by the platform rather than supplied. A
    borrower's `status` begins at `ACTIVE` and is the credit-standing gate for new
    originations; the only other value it takes is `SUSPENDED`. A borrower's
    `total_outstanding_principal_cents` begins at 0 and is at all times the sum of
    `principal_balance_cents` across that borrower's loans whose servicing standing
    is `CURRENT`, `DELINQUENT`, `DEFAULT` or `RECOVERY` — loans that have reached
    `PAID_OFF` or `CHARGED_OFF` are excluded from the total entirely. A borrower's
    `units_under_recovery_hold_count` also begins at 0 and is the number of
    *distinct* units that both secure a loan of this borrower and currently carry a
    recovery hold; because one borrower may hold two loans on the same unit, the
    count is over distinct units, not over loans."
    PRD §2.5: "Every resource carries a server-minted `id` formatted as a UUID with
    no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant
    with three fractional digits."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    Design: Corner/entities/create_borrower_applies_system_defaults_and_common_fields
    """
    response = api.create_borrower(factories.borrower_payload(**DANA), fixtures.ADMIN)

    borrower = validate_success(response, 201)
    assert_borrower(borrower)
    assert borrower["full_name"] == DANA["full_name"]
    assert borrower["credit_score"] == DANA["credit_score"]
    assert borrower["monthly_income_cents"] == DANA["monthly_income_cents"]
    assert borrower["state_code"] == DANA["state_code"]
    assert borrower["status"] == "ACTIVE"
    assert borrower["total_outstanding_principal_cents"] == 0
    assert borrower["units_under_recovery_hold_count"] == 0
    assert borrower["version"] == 1

    envelope = response.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(envelope["meta"]["api_request_timestamp"])

    assert fixtures.read_borrower(api, borrower["id"])["version"] == 1, (
        "a read is not a mutation, so the version stays where registration left it"
    )


def test_reading_a_new_unit_returns_its_inputs_and_the_four_declared_seeds(api):
    """PRD §3.2: "Its physical description consists of a `hud_label_number` (the HUD
    certification label, which must be globally unique across all units), a
    `manufacturer`, a `model_year` that drives both depreciation and remaining useful
    life, a `width_class` of either `SINGLE_WIDE` or `MULTI_WIDE`, a `square_feet`
    figure greater than zero giving heated floor area, a `condition_grade` of
    `EXCELLENT`, `GOOD`, `FAIR` or `POOR`, an `installation_type` of either
    `PIER_AND_ANCHOR` or `PERMANENT_FOUNDATION`, and a `wind_zone` of 1, 2 or 3
    identifying the HUD wind zone of the site."
    PRD §3.2: "A community placement requires a non-null `community_id`, a
    `lot_number` labelling the lot the unit occupies, and a `placement_start_date`
    opening the occupancy interval, and it requires `land_owner_borrower_id` to be
    null."
    PRD §3.2: "Any other combination — community fields on private land, or land
    fields on a community lot — is rejected with `ERR_PLACEMENT_FIELDS_INCONSISTENT`
    (HTTP 422)."
    PRD §3.2: "Every newly registered unit starts with `classification` at
    `PERSONAL_PROPERTY`, `title_status` at `ACTIVE_TITLE`, `recovery_hold` false, and
    both land-document flags — `deed_recorded` and `affixation_affidavit_recorded` —
    false."

    Design: Corner/entities/get_unit_returns_stored_inputs_and_system_defaults
    """
    community = fixtures.register_community(api, **PINE_RIDGE)
    created = fixtures.register_community_unit(api, community["id"], **UNIT_INPUTS)

    unit = validate_success(api.get_unit(created["id"], fixtures.SERVICER))

    assert_manufactured_unit(unit)
    assert unit["hud_label_number"] == HUD_LABEL
    assert unit["manufacturer"] == "Clayton"
    assert unit["model_year"] == 2018
    assert unit["width_class"] == "MULTI_WIDE"
    assert unit["square_feet"] == 1440
    assert unit["condition_grade"] == "GOOD"
    assert unit["installation_type"] == "PIER_AND_ANCHOR"
    assert unit["wind_zone"] == 2

    assert unit["placement_type"] == "COMMUNITY"
    assert unit["community_id"] == community["id"]
    assert unit["lot_number"] == LOT_NUMBER
    assert_instant_equals(
        unit["placement_start_date"],
        PLACEMENT_START_DATE,
        "ManufacturedUnit.placement_start_date",
    )
    assert unit["placement_end_date"] is None, "occupancy is open-ended"
    assert unit["land_owner_borrower_id"] is None
    assert unit["land_parcel_apn"] is None, "a land field on a community lot"
    assert unit["land_county"] is None, "a land field on a community lot"

    assert unit["classification"] == "PERSONAL_PROPERTY"
    assert unit["title_status"] == "ACTIVE_TITLE"
    assert unit["recovery_hold"] is False
    assert unit["deed_recorded"] is False
    assert unit["affixation_affidavit_recorded"] is False
    assert unit["version"] == 1


def test_the_community_filter_narrows_the_total_count_and_drives_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10 when omitted, may not be smaller than 1, and may not be larger than 100.
    The `offset` parameter is the number of matching items to skip before the page
    begins; it defaults to 0 and may not be negative."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every item matching the
    filters rather than the items on the current page."
    PRD §3.2: "Units can be listed and filtered by `community_id`, by
    `land_owner_borrower_id`, by `classification` and by `placement_type`, which is
    how a `CommunityOperator` finds the collateral in its own park and how a recovery
    desk finds every unit of a given classification."

    Design: Corner/entities/list_units_by_community_paginates_with_total_count_and_has_more
    """
    scenario = _community_with_three_units_and_a_neighbouring_park(api)
    community_id = scenario["first"]["id"]
    inside_ids = {unit["id"] for unit in scenario["inside"]}

    first_page, first_meta = validate_paginated(
        api.list_units(
            fixtures.ADMIN,
            {"community_id": community_id, "limit": PAGE_LIMIT, "offset": 0},
        )
    )
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == PAGE_LIMIT
    assert first_meta["offset"] == 0
    assert len(first_page) == PAGE_LIMIT

    second_page, second_meta = validate_paginated(
        api.list_units(
            fixtures.ADMIN,
            {"community_id": community_id, "limit": PAGE_LIMIT, "offset": 2},
        )
    )
    assert second_meta["total_count"] == 3, (
        "total_count counts every matching unit, not the one on this page"
    )
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2
    assert len(second_page) == 1

    paged_ids = {row["id"] for row in first_page} | {row["id"] for row in second_page}
    assert paged_ids == inside_ids
    assert scenario["outside"]["id"] not in paged_ids, (
        "the other park's unit is outside the filter"
    )


def test_a_well_formed_uuid_naming_no_loan_returns_the_loan_not_found_envelope(api):
    """PRD §2.6: "Each identifier has its own not-found code, all of them HTTP 404:
    `ERR_BORROWER_NOT_FOUND` for `borrower_id` or `land_owner_borrower_id`,
    `ERR_COMMUNITY_NOT_FOUND` for `community_id`, `ERR_GUIDE_NOT_FOUND` for
    `guide_id`, `ERR_UNIT_NOT_FOUND` for `unit_id`, `ERR_VALUATION_NOT_FOUND` for
    `valuation_id`, `origination_valuation_id` or `recovery_valuation_id`,
    `ERR_LOAN_NOT_FOUND` for `loan_id`, `refinanced_from_loan_id` or
    `resale_loan_id`, `ERR_FILING_NOT_FOUND` for `filing_id`,
    `ERR_POLICY_NOT_FOUND` for `policy_id`, `ERR_PAYMENT_NOT_FOUND` for
    `payment_id`, and `ERR_RECOVERY_CASE_NOT_FOUND` for `case_id`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/entities/get_loan_with_unknown_uuid_returns_loan_not_found
    """
    response = api.get_loan(NON_EXISTENT_UUID, fixtures.SERVICER)

    validate_error(response, ApiErrorId.ERR_LOAN_NOT_FOUND.value, 404)

    envelope = response.json()
    assert envelope["response_type"] == "error", "not an empty 200 body"
    assert envelope["data"]["error_id"] == ApiErrorId.ERR_LOAN_NOT_FOUND.value
    assert isinstance(envelope["data"]["message"], str)
    assert envelope["data"]["message"]
    assert "id" not in envelope["data"], "an error body carries no entity fields"
    assert "principal_cents" not in envelope["data"]
    assert set(envelope["meta"]) == {"api_request_id", "api_request_timestamp"}


def test_a_unit_registration_omitting_square_feet_is_refused_and_stores_nothing(api):
    """PRD §2.7: "Next come the two existence layers of §2.6 — path identifiers, then
    body foreign keys — followed by request-shape validation: every required body
    field present, every enum value a declared member of its enumeration, every
    amount named with a `_cents` or `_bps` suffix an integer inside its declared
    range, every date field a parseable ISO 8601 UTC instant, and pagination within
    bounds. Any of those failures is `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §3.2: "Its physical description consists of a `hud_label_number` (the HUD
    certification label, which must be globally unique across all units), a
    `manufacturer`, a `model_year` that drives both depreciation and remaining useful
    life, a `width_class` of either `SINGLE_WIDE` or `MULTI_WIDE`, a `square_feet`
    figure greater than zero giving heated floor area, a `condition_grade` of
    `EXCELLENT`, `GOOD`, `FAIR` or `POOR`, an `installation_type` of either
    `PIER_AND_ANCHOR` or `PERMANENT_FOUNDATION`, and a `wind_zone` of 1, 2 or 3
    identifying the HUD wind zone of the site."

    Design: Corner/entities/create_unit_missing_required_square_feet_returns_invalid_request
    """
    community = fixtures.register_community(api, **PINE_RIDGE)
    payload = factories.community_unit_payload(community["id"])
    payload.pop("square_feet")
    assert "square_feet" not in payload

    validate_error(
        api.create_unit(payload, fixtures.CLOSER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    _, meta = validate_paginated(
        api.list_units(fixtures.CLOSER, {"community_id": community["id"]})
    )
    assert meta["total_count"] == 0, "the shape failure left no unit row behind"


def test_a_community_registered_without_a_commission_stores_zero_not_null(api):
    """PRD §3.1: "A land-lease community is registered with a `name`, a two-letter
    `state_code`, a `lot_count` greater than zero, a `monthly_lot_rent_cents` figure
    of zero or more giving the posted monthly lot rent, and an optional
    `sales_commission_bps` between 0 and 500 inclusive — the referral commission the
    operator charges the lender when a remarketed unit is sold in-community. When
    `sales_commission_bps` is omitted it is 0. A newly registered community starts
    with `operator_agreement_status` at `NONE`, `lender_access_rights` false, and
    `agreement_executed_at` null."
    PRD §2.5: "Most resources also carry `updated_at`, an ISO 8601 UTC instant
    refreshed on every mutation of the resource, and `version`, an integer that starts
    at 1 and increments by exactly one on every mutation."

    Design: Corner/entities/create_community_omitting_sales_commission_bps_applies_zero_default
    """
    assert "sales_commission_bps" not in RIVERBEND

    community = validate_success(api.create_community(RIVERBEND, fixtures.ADMIN), 201)

    assert_community(community)
    assert community["name"] == RIVERBEND["name"]
    assert community["lot_count"] == RIVERBEND["lot_count"]
    assert community["monthly_lot_rent_cents"] == RIVERBEND["monthly_lot_rent_cents"]
    assert community["sales_commission_bps"] == 0, (
        "the omitted commission is stored as an integer zero, not as null"
    )
    assert community["sales_commission_bps"] is not None
    assert community["operator_agreement_status"] == "NONE"
    assert community["lender_access_rights"] is False
    assert community["agreement_executed_at"] is None
    assert community["version"] == 1


def test_a_published_guide_edition_carries_neither_version_nor_updated_at(api):
    """PRD §2.5: "Two resources are exceptions and carry only `id` and `created_at` —
    they have no `updated_at` and no `version` field at all, because nothing in the
    system ever mutates them in place. A `BookValueGuide` is a published edition and
    is immutable once created."
    PRD §3.1: "A guide edition is never edited after publication; a corrected guide
    is a new edition."

    Design: Corner/entities/book_value_guide_carries_no_version_field_and_no_mutation_endpoint
    """
    published = fixtures.publish_guide(
        api,
        guide_edition=GUIDE_EDITION,
        effective_date=GUIDE_EFFECTIVE_DATE,
        base_value_per_sqft_cents=BASE_VALUE_PER_SQFT_CENTS,
        annual_depreciation_bps=ANNUAL_DEPRECIATION_BPS,
    )

    guide = validate_success(api.get_book_value_guide(published["id"], fixtures.ANALYST))

    assert_book_value_guide(guide)
    assert "version" not in guide
    assert "updated_at" not in guide
    assert guide["guide_edition"] == GUIDE_EDITION
    assert guide["base_value_per_sqft_cents"] == BASE_VALUE_PER_SQFT_CENTS
    assert guide["annual_depreciation_bps"] == ANNUAL_DEPRECIATION_BPS
    assert_instant_equals(
        guide["effective_date"],
        GUIDE_EFFECTIVE_DATE,
        "BookValueGuide.effective_date",
    )

    corrected = fixtures.publish_guide(
        api,
        guide_edition=CORRECTED_EDITION,
        effective_date=GUIDE_EFFECTIVE_DATE,
        base_value_per_sqft_cents=BASE_VALUE_PER_SQFT_CENTS + 100,
        annual_depreciation_bps=ANNUAL_DEPRECIATION_BPS,
    )
    assert corrected["id"] != published["id"], (
        "a correction is a second edition, never an edit of the first"
    )

    unchanged = validate_success(
        api.get_book_value_guide(published["id"], fixtures.ANALYST)
    )
    assert unchanged["base_value_per_sqft_cents"] == BASE_VALUE_PER_SQFT_CENTS
    assert unchanged["guide_edition"] == GUIDE_EDITION
    assert "version" not in unchanged


def test_an_unresolvable_borrower_id_is_caught_before_any_valuation_rule(api):
    """PRD §2.6: "Body foreign keys are resolved after path parameters, on the seven
    endpoints that accept them: unit registration, valuation creation, loan
    application, lien-filing submission, insurance-policy creation, refurbishment
    start, and sale finalization."
    PRD §2.6: "Each identifier has its own not-found code, all of them HTTP 404:
    `ERR_BORROWER_NOT_FOUND` for `borrower_id` or `land_owner_borrower_id`,
    `ERR_COMMUNITY_NOT_FOUND` for `community_id`, `ERR_GUIDE_NOT_FOUND` for
    `guide_id`, `ERR_UNIT_NOT_FOUND` for `unit_id`, `ERR_VALUATION_NOT_FOUND` for
    `valuation_id`, `origination_valuation_id` or `recovery_valuation_id`,
    `ERR_LOAN_NOT_FOUND` for `loan_id`, `refinanced_from_loan_id` or
    `resale_loan_id`, `ERR_FILING_NOT_FOUND` for `filing_id`,
    `ERR_POLICY_NOT_FOUND` for `policy_id`, `ERR_PAYMENT_NOT_FOUND` for
    `payment_id`, and `ERR_RECOVERY_CASE_NOT_FOUND` for `case_id`."

    Design: Corner/entities/create_loan_with_unknown_borrower_id_returns_borrower_not_found
    """
    scenario = _certified_collateral_without_an_obligor(api)
    unit_id = scenario["unit"]["id"]
    assert scenario["valuation"]["status"] == "CERTIFIED"

    validate_error(
        api.create_loan(
            factories.loan_payload(
                NON_EXISTENT_UUID,
                unit_id,
                scenario["valuation"]["id"],
                PRINCIPAL_CENTS,
                REQUESTED_TERM_MONTHS,
            ),
            fixtures.ANALYST,
        ),
        ApiErrorId.ERR_BORROWER_NOT_FOUND.value,
        404,
    )

    _, meta = validate_paginated(
        api.list_loans(fixtures.ANALYST, {"unit_id": unit_id})
    )
    assert meta["total_count"] == 0, "no application was opened"

    valuation = fixtures.read_valuation(api, scenario["valuation"]["id"])
    assert valuation["status"] == "CERTIFIED", (
        "the rejected application never reached the valuation rules"
    )
    assert valuation["version"] == scenario["valuation"]["version"]


def test_a_width_class_outside_the_declared_pair_is_refused(api):
    """PRD §3.2: "Its physical description consists of a `hud_label_number` (the HUD
    certification label, which must be globally unique across all units), a
    `manufacturer`, a `model_year` that drives both depreciation and remaining useful
    life, a `width_class` of either `SINGLE_WIDE` or `MULTI_WIDE`, a `square_feet`
    figure greater than zero giving heated floor area, a `condition_grade` of
    `EXCELLENT`, `GOOD`, `FAIR` or `POOR`, an `installation_type` of either
    `PIER_AND_ANCHOR` or `PERMANENT_FOUNDATION`, and a `wind_zone` of 1, 2 or 3
    identifying the HUD wind zone of the site."
    PRD §2.7: "Next come the two existence layers of §2.6 — path identifiers, then
    body foreign keys — followed by request-shape validation: every required body
    field present, every enum value a declared member of its enumeration, every
    amount named with a `_cents` or `_bps` suffix an integer inside its declared
    range, every date field a parseable ISO 8601 UTC instant, and pagination within
    bounds. Any of those failures is `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_unit_with_undeclared_width_class_returns_invalid_request
    """
    community = fixtures.register_community(api, **PINE_RIDGE)
    payload = factories.community_unit_payload(
        community["id"], width_class="TRIPLE_WIDE", square_feet=2100, lot_number="A-15"
    )

    validate_error(
        api.create_unit(payload, fixtures.CLOSER),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    rows, meta = validate_paginated(
        api.list_units(fixtures.CLOSER, {"community_id": community["id"]})
    )
    assert meta["total_count"] == 0, (
        "the undeclared enum member was refused rather than silently narrowed to "
        "the single-wide multiplier"
    )
    assert rows == []
