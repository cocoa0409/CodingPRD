"""Referential joins on two endpoints, the not-found family, and authorization.

The two endpoint cases are the platform's referential joins: the valuation that
must find both a unit and a guide before it can compute anything, and the
refurbishment start that accepts one particular valuation of one particular unit
in one particular status. The error and role cases probe the top of the §2.7
ladder — authentication before shape, role authorization before existence, and
ownership before the state machine.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_instant_equals,
    assert_recovery_case,
    assert_valuation,
    assert_valuation_breakdown,
    factories,
    fixtures,
    headers_without_user_id,
    is_iso8601_timestamp,
    make_community_operator_headers,
    make_credit_analyst_headers,
    validate_error,
    validate_paginated,
    validate_success,
    LOAN_APPROVER_USER_ID,
    RECOVERY_CERTIFIER_USER_ID,
    VALUATION_CERTIFIER_USER_ID,
)

# The instant the logical clock reads before any PlatformAdmin has moved it.
UNMOVED_CLOCK = "2026-08-01T00:00:00Z"
FORWARD_CLOCK = "2026-09-01T00:00:00Z"
VALUATION_YEAR = 2026

DANA = {
    "full_name": "Dana Whitfield",
    "credit_score": 705,
    "monthly_income_cents": 520000,
    "state_code": "GA",
}
PIERED = {"installation_type": "PIER_AND_ANCHOR", "wind_zone": 2}

# ─── The 1440 sqft 2018 MULTI_WIDE on its owner's own parcel ───
# Eight years of age at 350 bps a year leaves 7200 of 10000 basis points of
# guide value: 1440 sqft x 4500 cents x 11500 bps x 7200 bps.
BOOK_BASE_CENTS = 5365440
PRIVATE_LAND_LOCATION_CENTS = 482890
PIER_INSTALLATION_CENTS = 250000
PRIVATE_LAND_CERTIFIED_CENTS = 6098330

# ─── The same shell on a signed community lot, valued for liquidation ───
AGREED_LOCATION_CENTS = 160963
FORCED_SALE_DISCOUNT_CENTS = 1215809
LIQUIDATION_CERTIFIED_CENTS = 4310594

# ─── The chattel loan that ends up in possession ───
PRINCIPAL_CENTS = 4600000
REQUESTED_TERM_MONTHS = 240
DWELLING_COVERAGE_CENTS = 4700000
FIRST_DUE_DATE = "2026-09-01T00:00:00Z"
ASSESSMENT_CLOCK = "2026-11-01T00:00:00Z"
POSSESSION_CLOCK = "2026-11-11T00:00:00Z"
NOTICE_REFERENCE = "RTC-2026-11-0007"

# ─── The loan the certifier is barred from approving ───
SMALL_PRINCIPAL_CENTS = 1500000

# ─── Two parks, one impostor ───
PINE_RIDGE = {
    "name": "Pine Ridge MHC",
    "state_code": "GA",
    "lot_count": 180,
    "monthly_lot_rent_cents": 52000,
    "sales_commission_bps": 150,
}
CEDAR_GLEN = {
    "name": "Cedar Glen MHC",
    "state_code": "GA",
    "lot_count": 96,
    "monthly_lot_rent_cents": 47500,
}

INCOMPLETE_BORROWER = {"full_name": "Dana Whitfield", "credit_score": 705}


def _guide_and_piered_parcel_unit(api):
    """One in-force guide and one piered MULTI_WIDE on land its obligor owns."""
    return fixtures.setup_private_land_collateral(
        api,
        borrower_overrides=DANA,
        unit_overrides=PIERED,
        record_documents=False,
    )


def _case_at_possession(api):
    """The chattel loan defaulted onto the repossession arm and seized on the
    day the ten-day right-to-cure expires."""
    return fixtures.setup_case_at_possession(
        api,
        possession_clock=POSSESSION_CLOCK,
        notice_reference=NOTICE_REFERENCE,
        assessment_clock=ASSESSMENT_CLOCK,
        principal_cents=PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
        dwelling_coverage_cents=DWELLING_COVERAGE_CENTS,
        first_due_date=FIRST_DUE_DATE,
    )


def test_a_valuation_resolves_its_unit_and_its_guide_independently(api):
    """PRD §2.6: "Each identifier has its own not-found code, all of them HTTP 404:
    `ERR_BORROWER_NOT_FOUND` for `borrower_id` or `land_owner_borrower_id`,
    `ERR_COMMUNITY_NOT_FOUND` for `community_id`, `ERR_GUIDE_NOT_FOUND` for
    `guide_id`, `ERR_UNIT_NOT_FOUND` for `unit_id`, `ERR_VALUATION_NOT_FOUND` for
    `valuation_id`, `origination_valuation_id` or `recovery_valuation_id`,
    `ERR_LOAN_NOT_FOUND` for `loan_id`, `refinanced_from_loan_id` or
    `resale_loan_id`, `ERR_FILING_NOT_FOUND` for `filing_id`,
    `ERR_POLICY_NOT_FOUND` for `policy_id`, `ERR_PAYMENT_NOT_FOUND` for
    `payment_id`, and `ERR_RECOVERY_CASE_NOT_FOUND` for `case_id`."
    PRD §2.6: "Body foreign keys are resolved after path parameters, on the seven
    endpoints that accept them: unit registration, valuation creation, loan
    application, lien-filing submission, insurance-policy creation, refurbishment
    start, and sale finalization."
    PRD §3.3: "A `CreditAnalyst` or a `RecoveryManager` values a unit by naming the
    unit as `unit_id`, the guide edition as `guide_id`, the algorithm to run as
    `variant`, and the unit's last observed version as `expected_unit_version`."
    PRD §3.3: "The platform stamps `valuation_year` with the calendar year of the
    logical clock at the moment of creation, which fixes the age used for
    depreciation for the life of this valuation. Age in years is `valuation_year`
    minus the unit's `model_year`, floored at zero so that a unit newer than the
    current year never ages negatively. Depreciation in basis points is that age in
    years multiplied by the guide's `annual_depreciation_bps`, but capped: the
    depreciation may never exceed 7000 basis points, which is ten thousand basis
    points less a 3000-basis-point residual floor, so at least thirty percent of
    guide value always survives no matter how old the unit is."
    PRD §3.3: "The width multiplier is the guide's `multi_wide_multiplier_bps` when
    the unit's `width_class` is `MULTI_WIDE` and its `single_wide_multiplier_bps`
    otherwise. The platform then computes `book_base_cents` as the unit's
    `square_feet` multiplied by the guide's `base_value_per_sqft_cents`, multiplied by
    the width multiplier in basis points divided by ten thousand, multiplied by the
    surviving fraction of value — ten thousand basis points less the depreciation in
    basis points, divided by ten thousand."
    PRD §3.3: "When the unit's `placement_type` is `PRIVATE_LAND`, the key is
    `PRIVATE_LAND`."
    PRD §3.3: "The `location_adjustment_cents` figure is `book_base_cents` multiplied
    by the location rate for `location_key` divided by ten thousand, rounded half up
    — a credit of 300 basis points for `COMMUNITY_WITH_AGREEMENT`, a charge of 700
    basis points for `COMMUNITY_WITHOUT_AGREEMENT`, and a credit of 900 basis points
    for `PRIVATE_LAND`. Both of these are signed quantities: a charge is stored as a
    negative number of cents. The `installation_adjustment_cents` figure is not
    proportional at all — on the `ORIGINATION` variant it is a flat 850,000 cents for
    a unit on a `PERMANENT_FOUNDATION` and a flat 250,000 cents for a unit on
    `PIER_AND_ANCHOR`, and on the `RECOVERY_LIQUIDATION` variant it is dropped
    entirely and recorded as zero. The adjusted subtotal is `book_base_cents` plus
    all three adjustments."
    PRD §3.3: "On the `ORIGINATION` variant, both liquidation deductions are recorded
    as zero — `forced_sale_discount_cents` is 0 and `detach_and_move_cost_cents` is 0
    — and `certified_value_cents` is the adjusted subtotal exactly as computed."
    PRD §3.3: "It increments the unit's own `version`, so a client that creates two
    valuations back to back must re-read the unit between them."
    PRD §3.3: "Valuations can be listed and filtered by `unit_id`, `guide_id`,
    `variant` and `status`, and read individually with their full adjustment
    breakdown, which is how an auditor reconstructs how a number was reached."

    Design: Corner/endpoints/valuation_create_links_a_unit_and_a_guide_and_both_must_exist
    """
    scenario = _guide_and_piered_parcel_unit(api)
    unit, guide = scenario["unit"], scenario["guide"]

    validate_error(
        api.create_valuation(
            factories.valuation_payload(
                NON_EXISTENT_UUID, guide["id"], unit["version"]
            ),
            fixtures.ANALYST,
        ),
        ApiErrorId.ERR_UNIT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_valuation(
            factories.valuation_payload(
                unit["id"], NON_EXISTENT_UUID, unit["version"]
            ),
            fixtures.ANALYST,
        ),
        ApiErrorId.ERR_GUIDE_NOT_FOUND.value,
        404,
    )

    valuation = validate_success(
        api.create_valuation(
            factories.valuation_payload(unit["id"], guide["id"], unit["version"]),
            fixtures.ANALYST,
        ),
        201,
    )

    assert_valuation(valuation)
    assert valuation["unit_id"] == unit["id"]
    assert valuation["guide_id"] == guide["id"], (
        "both foreign keys are recorded on the row that the join produced"
    )
    assert valuation["valuation_year"] == VALUATION_YEAR
    assert valuation["location_key"] == "PRIVATE_LAND"
    assert_valuation_breakdown(
        valuation,
        book_base_cents=BOOK_BASE_CENTS,
        condition_adjustment_cents=0,
        location_adjustment_cents=PRIVATE_LAND_LOCATION_CENTS,
        installation_adjustment_cents=PIER_INSTALLATION_CENTS,
        forced_sale_discount_cents=0,
        detach_and_move_cost_cents=0,
        certified_value_cents=PRIVATE_LAND_CERTIFIED_CENTS,
    )

    assert fixtures.read_unit(api, unit["id"])["version"] == 2, (
        "only the create that resolved both references bumped the unit"
    )

    by_unit, unit_meta = validate_paginated(
        api.list_valuations(fixtures.ANALYST, {"unit_id": unit["id"]})
    )
    assert unit_meta["total_count"] == 1
    assert by_unit[0]["id"] == valuation["id"]
    _, guide_meta = validate_paginated(
        api.list_valuations(fixtures.ANALYST, {"guide_id": guide["id"]})
    )
    assert guide_meta["total_count"] == 1, (
        "the two refused creates persisted no row against either reference"
    )


def test_refurbishment_opens_only_on_a_certified_liquidation_of_this_unit(api):
    """PRD §3.9: "A successful possession moves the case to `POSSESSION_OBTAINED` and
    stamps `possession_date` with the logical clock."
    PRD §3.9: "Refurbishment begins by attaching a liquidation figure. The
    `RecoveryManager` names a `recovery_valuation_id`, which must reference a
    valuation that is `CERTIFIED`, is of variant `RECOVERY_LIQUIDATION`, and was
    computed on this same unit; anything else is refused with
    `ERR_VALUATION_VARIANT_MISMATCH` (HTTP 422). Attaching it moves the case from
    `POSSESSION_OBTAINED` to `REFURBISHING`."
    PRD §3.9: "The platform appends an object carrying `category`, `cost_cents`,
    `cost_class` and `recorded_at` to the case's append-only
    `refurbishment_line_items` list."
    PRD §3.9: "A case with no capitalized line at all reports
    `refurbishment_cost_cents` as 0."
    PRD §3.9: "Recovery cases can be listed and filtered by `loan_id`, by
    `recovery_valuation_id`, by `resale_loan_id`, by `path` and by `status`, and read
    individually with their refurbishment lines and settlement figures."
    PRD §3.3: "It moves any earlier `CERTIFIED` valuation of the same unit and the
    same variant to `SUPERSEDED` — which is precisely why the stale-version guard of
    §2.9 exists on this write, and why `ERR_STALE_UNIT_VERSION` is returned when
    `expected_unit_version` does not match. It increments the unit's own `version`, so
    a client that creates two valuations back to back must re-read the unit between
    them. And it leaves the new valuation in `status` `DRAFT`, with
    `certified_by_user_id` and `certified_at` both null."
    PRD §3.3: "A draft valuation is a working figure; only a certified one may be
    cited by a loan or a recovery case. Certification is performed by a
    `CreditAnalyst` or a `RecoveryManager` and freezes the row: `status` moves to
    `CERTIFIED`, `certified_by_user_id` is stamped with the acting `X-User-ID`, and
    `certified_at` is stamped with the logical clock."
    PRD §3.3: "The platform stamps `valuation_year` with the calendar year of the
    logical clock at the moment of creation, which fixes the age used for
    depreciation for the life of this valuation. Age in years is `valuation_year`
    minus the unit's `model_year`, floored at zero so that a unit newer than the
    current year never ages negatively. Depreciation in basis points is that age in
    years multiplied by the guide's `annual_depreciation_bps`, but capped: the
    depreciation may never exceed 7000 basis points, which is ten thousand basis
    points less a 3000-basis-point residual floor, so at least thirty percent of
    guide value always survives no matter how old the unit is."
    PRD §3.3: "The width multiplier is the guide's `multi_wide_multiplier_bps` when
    the unit's `width_class` is `MULTI_WIDE` and its `single_wide_multiplier_bps`
    otherwise. The platform then computes `book_base_cents` as the unit's
    `square_feet` multiplied by the guide's `base_value_per_sqft_cents`, multiplied by
    the width multiplier in basis points divided by ten thousand, multiplied by the
    surviving fraction of value — ten thousand basis points less the depreciation in
    basis points, divided by ten thousand."
    PRD §3.3: "Otherwise the unit sits on a community lot, and the key is
    `COMMUNITY_WITH_AGREEMENT` when that community's `operator_agreement_status` is
    `EXECUTED` and `COMMUNITY_WITHOUT_AGREEMENT` in every other case — including
    `PENDING` and `TERMINATED`, neither of which grants the lender anything."
    PRD §3.3: "The `location_adjustment_cents` figure is `book_base_cents` multiplied
    by the location rate for `location_key` divided by ten thousand, rounded half up
    — a credit of 300 basis points for `COMMUNITY_WITH_AGREEMENT`, a charge of 700
    basis points for `COMMUNITY_WITHOUT_AGREEMENT`, and a credit of 900 basis points
    for `PRIVATE_LAND`. Both of these are signed quantities: a charge is stored as a
    negative number of cents. The `installation_adjustment_cents` figure is not
    proportional at all — on the `ORIGINATION` variant it is a flat 850,000 cents for
    a unit on a `PERMANENT_FOUNDATION` and a flat 250,000 cents for a unit on
    `PIER_AND_ANCHOR`, and on the `RECOVERY_LIQUIDATION` variant it is dropped
    entirely and recorded as zero. The adjusted subtotal is `book_base_cents` plus
    all three adjustments."
    PRD §3.3: "The `forced_sale_discount_cents` figure is the adjusted subtotal
    multiplied by 2200 basis points divided by ten thousand, rounded half up — the
    haircut a forced sale takes. The `detach_and_move_cost_cents` figure is a flat
    675,000 cents when, and only when, `location_key` is `COMMUNITY_WITHOUT_AGREEMENT`;
    on private land, or in a community whose operator agreement is executed, it is
    zero, because in those cases the unit can be sold where it stands rather than
    detached and hauled away. Then `certified_value_cents` is the adjusted subtotal
    less the forced-sale discount less the detach-and-move cost, floored at zero so
    that a badly depreciated unit reports a value of 0 rather than a negative one."
    PRD §4: "Every other operation modifies a resource that already exists and
    returns `200 OK`, including the clock setter, the operator-agreement driver,
    land-document recording, classification conversion, valuation certification,
    every origination and servicing transition, filing agency responses and
    re-tenders, and every recovery-case action."

    Design: Corner/endpoints/begin_refurbishment_only_accepts_a_certified_recovery_liquidation_valuation
    """
    scenario = _case_at_possession(api)
    case_id = scenario["case"]["id"]
    origination = scenario["valuation"]
    assert scenario["case"]["status"] == "POSSESSION_OBTAINED"
    assert origination["variant"] == "ORIGINATION"
    assert origination["status"] == "CERTIFIED"

    liquidation = fixtures.create_valuation(
        api,
        scenario["unit"]["id"],
        scenario["guide"]["id"],
        fixtures.read_unit(api, scenario["unit"]["id"])["version"],
        "RECOVERY_LIQUIDATION",
        fixtures.RECOVERY,
    )
    assert liquidation["status"] == "DRAFT", (
        "a freshly created valuation is a working figure, not a citable one"
    )

    validate_error(
        api.begin_refurbishment(
            case_id, {"recovery_valuation_id": origination["id"]}, fixtures.RECOVERY
        ),
        ApiErrorId.ERR_VALUATION_VARIANT_MISMATCH.value,
        422,
    )
    validate_error(
        api.begin_refurbishment(
            case_id, {"recovery_valuation_id": liquidation["id"]}, fixtures.RECOVERY
        ),
        ApiErrorId.ERR_VALUATION_VARIANT_MISMATCH.value,
        422,
    )
    held = fixtures.read_case(api, case_id)
    assert held["status"] == "POSSESSION_OBTAINED", (
        "the right variant in the wrong status is refused as flatly as the wrong "
        "variant in the right status"
    )

    certified = fixtures.certify_valuation(
        api, liquidation["id"], RECOVERY_CERTIFIER_USER_ID, "RecoveryManager"
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == RECOVERY_CERTIFIER_USER_ID
    assert certified["location_key"] == "COMMUNITY_WITH_AGREEMENT"
    assert_valuation_breakdown(
        certified,
        book_base_cents=BOOK_BASE_CENTS,
        condition_adjustment_cents=0,
        location_adjustment_cents=AGREED_LOCATION_CENTS,
        installation_adjustment_cents=0,
        forced_sale_discount_cents=FORCED_SALE_DISCOUNT_CENTS,
        detach_and_move_cost_cents=0,
        certified_value_cents=LIQUIDATION_CERTIFIED_CENTS,
    )

    case = validate_success(
        api.begin_refurbishment(
            case_id, {"recovery_valuation_id": liquidation["id"]}, fixtures.RECOVERY
        ),
        200,
    )
    assert_recovery_case(case)
    assert case["status"] == "REFURBISHING"
    assert case["refurbishment_cost_cents"] == 0
    assert case["refurbishment_line_items"] == [], (
        "the list is append-only and nothing has been appended yet"
    )

    attached, attached_meta = validate_paginated(
        api.list_recovery_cases(
            fixtures.RECOVERY, {"recovery_valuation_id": liquidation["id"]}
        )
    )
    assert attached_meta["total_count"] == 1
    assert attached[0]["id"] == case_id

    assert fixtures.read_valuation(api, origination["id"])["status"] == "CERTIFIED", (
        "a valuation of a different variant never supersedes the origination figure"
    )


def test_each_entity_family_answers_an_unknown_id_with_its_own_not_found(api):
    """PRD §2.6: "Identifiers reach the server in two ways: as a path parameter naming
    the resource being acted on, and as a foreign key inside a request body. Both are
    resolved before any business rule runs, and path parameters are resolved first,
    left to right, so that the first identifier in the path that does not resolve
    determines the error returned."
    PRD §2.6: "Each identifier has its own not-found code, all of them HTTP 404:
    `ERR_BORROWER_NOT_FOUND` for `borrower_id` or `land_owner_borrower_id`,
    `ERR_COMMUNITY_NOT_FOUND` for `community_id`, `ERR_GUIDE_NOT_FOUND` for
    `guide_id`, `ERR_UNIT_NOT_FOUND` for `unit_id`, `ERR_VALUATION_NOT_FOUND` for
    `valuation_id`, `origination_valuation_id` or `recovery_valuation_id`,
    `ERR_LOAN_NOT_FOUND` for `loan_id`, `refinanced_from_loan_id` or
    `resale_loan_id`, `ERR_FILING_NOT_FOUND` for `filing_id`,
    `ERR_POLICY_NOT_FOUND` for `policy_id`, `ERR_PAYMENT_NOT_FOUND` for
    `payment_id`, and `ERR_RECOVERY_CASE_NOT_FOUND` for `case_id`."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` counts every item matching the
    filters rather than the items on the current page."
    PRD §4: "All read endpoints return `200 OK`."

    Design: Corner/errors/unknown_path_ids_return_the_matching_not_found_error
    """
    families = (
        (api.get_community, ApiErrorId.ERR_COMMUNITY_NOT_FOUND),
        (api.get_valuation, ApiErrorId.ERR_VALUATION_NOT_FOUND),
        (api.get_lien_filing, ApiErrorId.ERR_FILING_NOT_FOUND),
        (api.get_insurance_policy, ApiErrorId.ERR_POLICY_NOT_FOUND),
        (api.get_payment, ApiErrorId.ERR_PAYMENT_NOT_FOUND),
        (api.get_recovery_case, ApiErrorId.ERR_RECOVERY_CASE_NOT_FOUND),
    )

    seen = set()
    for read_one, error_id in families:
        response = read_one(NON_EXISTENT_UUID, fixtures.ADMIN)
        validate_error(response, error_id.value, 404)
        envelope = response.json()
        assert set(envelope["meta"]) == {"api_request_id", "api_request_timestamp"}
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(envelope["meta"]["api_request_timestamp"])
        seen.add(envelope["data"]["error_id"])

    assert len(seen) == len(families), (
        "one identifier, six families, six distinct codes — not a single generic 404"
    )

    for list_all in (
        api.list_valuations,
        api.list_lien_filings,
        api.list_insurance_policies,
        api.list_payments,
        api.list_recovery_cases,
    ):
        rows, meta = validate_paginated(list_all(fixtures.ADMIN))
        assert rows == []
        assert meta["total_count"] == 0, "an empty collection is not a not-found"


def test_the_identity_header_is_demanded_before_the_body_is_read(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the caller, and `X-User-Role`, naming the capacity in which the caller
    acts. If either header is absent, or if `X-User-Role` is not one of the seven role
    names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."
    PRD §2.7: "Requests are validated in a fixed order and the first failure wins; no
    later check may mask an earlier one."
    PRD §2.7: "First come the three authorization checks: header presence and role
    validity (`ERR_UNAUTHENTICATED`), then role authorization for the endpoint
    (`ERR_ROLE_NOT_PERMITTED`), then resource ownership for the two identity-backed
    roles (`ERR_NOT_RESOURCE_OWNER`)."
    PRD §2.7: "Next come the two existence layers of §2.6 — path identifiers, then
    body foreign keys — followed by request-shape validation: every required body
    field present, every enum value a declared member of its enumeration, every
    amount named with a `_cents` or `_bps` suffix an integer inside its declared
    range, every date field a parseable ISO 8601 UTC instant, and pagination within
    bounds. Any of those failures is `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD §2.6: "Each identifier has its own not-found code, all of them HTTP 404:
    `ERR_BORROWER_NOT_FOUND` for `borrower_id` or `land_owner_borrower_id`,
    `ERR_COMMUNITY_NOT_FOUND` for `community_id`, `ERR_GUIDE_NOT_FOUND` for
    `guide_id`, `ERR_UNIT_NOT_FOUND` for `unit_id`, `ERR_VALUATION_NOT_FOUND` for
    `valuation_id`, `origination_valuation_id` or `recovery_valuation_id`,
    `ERR_LOAN_NOT_FOUND` for `loan_id`, `refinanced_from_loan_id` or
    `resale_loan_id`, `ERR_FILING_NOT_FOUND` for `filing_id`,
    `ERR_POLICY_NOT_FOUND` for `policy_id`, `ERR_PAYMENT_NOT_FOUND` for
    `payment_id`, and `ERR_RECOVERY_CASE_NOT_FOUND` for `case_id`."
    PRD §3.1: "An obligor is registered with a `full_name`, a `credit_score` between
    300 and 850 inclusive, a `monthly_income_cents` figure of zero or more
    representing verified monthly income, and a two-letter `state_code` for the
    obligor's residence."

    Design: Corner/errors/calls_without_an_x_user_id_header_are_unauthenticated
    """
    anonymous = headers_without_user_id("PlatformAdmin")

    validate_error(
        api.create_borrower(dict(INCOMPLETE_BORROWER), anonymous),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.get_borrower(NON_EXISTENT_UUID, anonymous),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    validate_error(
        api.create_borrower(dict(INCOMPLETE_BORROWER), fixtures.ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    whole = validate_success(
        api.create_borrower(factories.borrower_payload(**DANA), fixtures.ADMIN), 201
    )
    assert whole["monthly_income_cents"] == DANA["monthly_income_cents"], (
        "the two missing fields were never reached until the header was present"
    )
    assert whole["state_code"] == DANA["state_code"]


def test_holding_one_role_is_no_licence_to_run_another_roles_operation(api):
    """PRD §2.1: "If both headers are well formed but the named role is not among the
    roles authorized for the endpoint being called — see the authorization column of
    the endpoint table in §4 — the request is rejected with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."
    PRD §2.1: "A `PlatformAdmin` is operations staff. It owns reference data (guide
    editions, borrower registration, community registration), the logical clock, and
    the inbound channel through which a recording office reports the outcome of a
    filing. It also proposes and terminates community operator agreements, and shares
    unit registration with a `ClosingAgent`."
    PRD §2.7: "First come the three authorization checks: header presence and role
    validity (`ERR_UNAUTHENTICATED`), then role authorization for the endpoint
    (`ERR_ROLE_NOT_PERMITTED`), then resource ownership for the two identity-backed
    roles (`ERR_NOT_RESOURCE_OWNER`)."
    PRD §2.4: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`, and the server must not fall back to real time in that
    state."
    PRD §2.4: "A `PlatformAdmin` moves the clock by supplying a `current_utc` instant.
    The clock may only move forward or stay where it is; a request that would move it
    backwards is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). Setting the clock
    mutates no entity — it only changes what subsequent reads of the clock return,
    which is echoed back as `current_utc`."

    Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation
    """
    validate_error(
        api.create_borrower(factories.borrower_payload(**DANA), fixtures.ANALYST),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.create_book_value_guide(
            factories.book_value_guide_payload(), fixtures.CLOSER
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )
    validate_error(
        api.set_clock(FORWARD_CLOCK, fixtures.SERVICER),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    # Re-setting the clock to the instant it reads before anyone has moved it is a
    # legal no-op; had the Servicer's request landed, this would be a regression.
    echoed = validate_success(api.set_clock(UNMOVED_CLOCK, fixtures.ADMIN), 200)
    assert_instant_equals(echoed["current_utc"], UNMOVED_CLOCK, "current_utc")

    borrower = validate_success(
        api.create_borrower(factories.borrower_payload(**DANA), fixtures.ADMIN), 201
    )
    assert borrower["full_name"] == DANA["full_name"], (
        "the identical body is refused or accepted purely on the role that sends it"
    )


def test_the_analyst_who_certified_the_collateral_cannot_approve_the_loan(api):
    """PRD §2.11: "One control in this platform exists purely to keep two judgments in
    separate hands. The operator identity that certifies the origination valuation for
    a loan may never be the operator identity that credit-approves the loan secured by
    it, even though both actions belong to the `CreditAnalyst` role. The certifier's
    `X-User-ID` is durably recorded as `certified_by_user_id` on the valuation at
    certification, and the approver's `X-User-ID` is recorded as `approved_by_user_id`
    on the loan at approval. If the two would be equal, approval is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD §3.4: "Submitting the application for underwriting is the pricing act: it
    advances `underwriting_state` from `DRAFT` to `UNDERWRITING` and, in doing so,
    computes and stores `ltv_bps`, `apr_bps` and `term_months`, all three of which are
    null until this succeeds."
    PRD §3.4: "Credit approval, also a `CreditAnalyst` action, advances the loan from
    `UNDERWRITING` to `APPROVED` and enforces three gates in order. The
    segregation-of-duties control of §2.11 fires first: the acting `X-User-ID` must
    differ from the `certified_by_user_id` of the loan's origination valuation, or the
    approval is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.4: "A successful approval stamps `approved_by_user_id` with the acting
    `X-User-ID` and increments the loan's `version`."
    PRD §3.3: "Certification is performed by a `CreditAnalyst` or a `RecoveryManager`
    and freezes the row: `status` moves to `CERTIFIED`, `certified_by_user_id` is
    stamped with the acting `X-User-ID`, and `certified_at` is stamped with the
    logical clock."

    Design: Corner/rbac/the_certifier_of_the_valuation_cannot_approve_the_loan_it_secures
    """
    scenario = _guide_and_piered_parcel_unit(api)
    certifier = make_credit_analyst_headers(VALUATION_CERTIFIER_USER_ID)

    valuation = fixtures.create_certified_valuation(
        api,
        scenario["unit"]["id"],
        scenario["guide"]["id"],
        certifier_user_id=VALUATION_CERTIFIER_USER_ID,
    )
    assert valuation["certified_by_user_id"] == VALUATION_CERTIFIER_USER_ID

    loan = fixtures.open_loan(
        api,
        scenario["borrower"]["id"],
        scenario["unit"]["id"],
        valuation["id"],
        principal_cents=SMALL_PRINCIPAL_CENTS,
        requested_term_months=REQUESTED_TERM_MONTHS,
    )
    priced = validate_success(api.submit_underwriting(loan["id"], certifier), 200)
    assert priced["underwriting_state"] == "UNDERWRITING", (
        "pricing carries no duty split, so the certifier may submit its own file"
    )

    validate_error(
        api.approve_loan(loan["id"], certifier),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        409,
    )
    held = fixtures.read_loan(api, loan["id"])
    assert held["underwriting_state"] == "UNDERWRITING", (
        "the caller does hold CreditAnalyst; the refusal is on identity, not on role"
    )
    assert held["version"] == priced["version"], "no approval, no version bump"

    approved = validate_success(
        api.approve_loan(loan["id"], make_credit_analyst_headers(LOAN_APPROVER_USER_ID)),
        200,
    )
    assert approved["underwriting_state"] == "APPROVED"
    assert approved["approved_by_user_id"] == LOAN_APPROVER_USER_ID
    assert approved["approved_by_user_id"] != valuation["certified_by_user_id"]


def test_an_operator_may_execute_only_its_own_parks_agreement(api):
    """PRD §2.1: "Ownership violations are rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP
    403). The check applies to the operator-agreement endpoint, to lot-rent reporting,
    and to every read endpoint: a `CommunityOperator` acting on a community other than
    the one its `X-User-ID` names, or a `Borrower` reading a loan, unit, policy,
    payment or recovery case that does not belong to it, is refused."
    PRD §3.1: "A newly registered community starts with `operator_agreement_status` at
    `NONE`, `lender_access_rights` false, and `agreement_executed_at` null."
    PRD §3.1: "A `PlatformAdmin` proposes an agreement with the `action` value
    `PROPOSE`, which is available from `NONE` and also from `TERMINATED` — a lapsed
    relationship can be re-proposed — and moves the community to `PENDING`. From
    `PENDING`, the `action` value `EXECUTE` moves the community to `EXECUTED`, and this
    is the one write in the system reserved to the `CommunityOperator` role: the acting
    `X-User-ID` must equal the community's own `id`. Execution sets
    `lender_access_rights` to true and stamps `agreement_executed_at` with the logical
    clock, and it also raises the location adjustment applied to future valuations of
    units in that community, as described in §3.3."
    PRD §2.4: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00Z`, and the server must not fall back to real time in that
    state."
    PRD §4: "Every other operation modifies a resource that already exists and returns
    `200 OK`, including the clock setter, the operator-agreement driver, land-document
    recording, classification conversion, valuation certification, every origination
    and servicing transition, filing agency responses and re-tenders, and every
    recovery-case action."

    Design: Corner/rbac/community_operator_cannot_execute_another_parks_agreement
    """
    pine = fixtures.register_community(api, **PINE_RIDGE)
    cedar = fixtures.register_community(api, **CEDAR_GLEN)
    assert pine["operator_agreement_status"] == "NONE"

    fixtures.propose_agreement(api, pine["id"])
    proposed = fixtures.propose_agreement(api, cedar["id"])
    assert proposed["operator_agreement_status"] == "PENDING"
    assert proposed["lender_access_rights"] is False

    validate_error(
        api.operator_agreement(
            cedar["id"], "EXECUTE", make_community_operator_headers(pine["id"])
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
        403,
    )
    held = fixtures.read_community(api, cedar["id"])
    assert held["operator_agreement_status"] == "PENDING", (
        "the neighbouring operator holds the right role and still moves nothing"
    )
    assert held["lender_access_rights"] is False

    executed = validate_success(
        api.operator_agreement(
            cedar["id"], "EXECUTE", make_community_operator_headers(cedar["id"])
        ),
        200,
    )
    assert executed["operator_agreement_status"] == "EXECUTED"
    assert executed["lender_access_rights"] is True
    assert_instant_equals(
        executed["agreement_executed_at"], UNMOVED_CLOCK, "agreement_executed_at"
    )

    untouched = fixtures.read_community(api, pine["id"])
    assert untouched["operator_agreement_status"] == "PENDING", (
        "acting on one park never advances another"
    )
    assert untouched["lender_access_rights"] is False
