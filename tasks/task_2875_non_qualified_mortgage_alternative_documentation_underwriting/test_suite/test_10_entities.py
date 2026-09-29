"""Entity surface: field echo, conditional shape, defaults, computed fields,
system fields, domains, immutability and foreign-key resolution order.
"""

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_BORROWER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LOAN_FILE_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_VALUE_OUT_OF_RANGE,
)
from test_helpers.constants import SEASONING_MATRIX
from test_helpers.test_users import (
    ADMIN,
    LOAN_OFFICER,
    SECURITIZATION_ANALYST,
    UNDERWRITER,
    underwriter,
)

INVESTOR = "INV-ALPHA"
MISSING_UUID = "00000000-0000-4000-8000-0000000000aa"
OTHER_MISSING_UUID = "00000000-0000-4000-8000-0000000000bb"


def _dscr_program_payload(**overrides):
    payload = {
        "program_code": "DSCR", "name": "Investor DSCR", "min_dscr": 1.1000,
        "max_ltv_pct": 85.00, "min_fico": 660, "min_reserves_months": 6,
        "min_residual_income_cents": 0,
        "second_valuation_ltv_threshold_pct": 90.00,
        "second_valuation_loan_amount_threshold_cents": 150000000,
        "atr_exempt_flag": True, "seasoning_matrix": dict(SEASONING_MATRIX),
    }
    payload.update(overrides)
    return payload


def _dscr_loan_payload(borrower_id, program_id, **overrides):
    payload = {
        "borrower_id": borrower_id, "program_id": program_id,
        "investor_code": INVESTOR, "loan_amount_cents": 60000000,
        "purchase_price_cents": 80000000, "property_value_cents": 80000000,
        "occupancy": "INVESTMENT", "purpose": "PURCHASE", "lien_position": "FIRST",
        "note_rate_pct": 8.750, "apor_pct": 6.100, "term_months": 360,
        "amortization_type": "INTEREST_ONLY", "monthly_taxes_cents": 60000,
        "monthly_insurance_cents": 20000, "gross_market_rent_cents": 620000,
        "lease_rent_cents": 640000,
    }
    payload.update(overrides)
    return payload


def _minimal_borrower_payload(legal_name="Ida Novak", **overrides):
    """A borrower carrying only the fields the PRD does not default."""
    payload = {"legal_name": legal_name, "fico_score": 700,
               "monthly_debt_obligations_cents": 0,
               "verified_liquid_assets_cents": 5000000, "age_years": 50}
    payload.update(overrides)
    return payload


def test_program_creation_echoes_every_declared_field_including_the_matrix(api):
    """A create carrying all program inputs echoes them, matrix keys included.

    PRD 3.1: "`seasoning_matrix` is an object whose keys are exactly `FORECLOSURE`,
    `SHORT_SALE`, `DEED_IN_LIEU`, `BK_CH7`, `BK_CH13`, `MODIFICATION` and
    `MORTGAGE_LATE_60`, all seven required, each mapping to a non-negative whole number
    of months."

    Design: Corner/entities/corner_program_creation_echoes_every_declared_field
    """
    payload = {
        "program_code": "BANK_STATEMENT_12MO", "name": "12-Month Bank Statement",
        "statement_period_months": 12, "default_expense_factor_pct": 50.00,
        "min_expense_factor_pct": 25.00, "max_ltv_pct": 80.00, "min_fico": 660,
        "min_reserves_months": 6, "max_dti_pct": 50.00,
        "min_residual_income_cents": 250000,
        "second_valuation_ltv_threshold_pct": 85.00,
        "second_valuation_loan_amount_threshold_cents": 150000000,
        "atr_exempt_flag": False, "seasoning_matrix": dict(SEASONING_MATRIX),
    }

    created = validate_success(api.create_program(payload, ADMIN), 201)

    A.assert_created_row(created)
    A.assert_fields(created, {"program_code": "BANK_STATEMENT_12MO",
                              "statement_period_months": 12,
                              "min_residual_income_cents": 250000,
                              "second_valuation_loan_amount_threshold_cents": 150000000,
                              "atr_exempt_flag": False})
    A.assert_pct_2dp(created["default_expense_factor_pct"], "50.00",
                     "default_expense_factor_pct")
    A.assert_pct_2dp(created["min_expense_factor_pct"], "25.00",
                     "min_expense_factor_pct")
    A.assert_fields(created["seasoning_matrix"], {"BK_CH7": 24,
                                                  "MORTGAGE_LATE_60": 12,
                                                  "FORECLOSURE": 36})
    assert set(created["seasoning_matrix"]) == set(SEASONING_MATRIX)


def test_program_shape_fields_are_conditionally_required_by_program_code(api):
    """A bank-statement program needs its period; a DSCR program forbids max_dti_pct.

    PRD 3.1: "`max_dti_pct` is the debt-to-income ceiling: it is required for every
    program except `DSCR` and must be omitted for `DSCR`, which has no borrower income
    to divide by."
    PRD 2.8: "`ERR_INVALID_REQUEST` — on every POST endpoint: a non-optional input field
    is missing, a value has the wrong type, an enum value is not a declared member, or
    the body carries a field the endpoint does not declare."

    Design: Corner/entities/corner_program_conditional_field_matrix_by_program_code
    """
    missing_period = api.create_program(
        {"program_code": "BANK_STATEMENT_12MO", "name": "Missing Period",
         "default_expense_factor_pct": 50.00, "min_expense_factor_pct": 25.00,
         "max_ltv_pct": 80.00, "min_fico": 660, "min_reserves_months": 6,
         "max_dti_pct": 50.00, "min_residual_income_cents": 250000,
         "second_valuation_ltv_threshold_pct": 85.00,
         "second_valuation_loan_amount_threshold_cents": 150000000,
         "seasoning_matrix": dict(SEASONING_MATRIX)},
        ADMIN)
    validate_error(missing_period, ERR_INVALID_REQUEST)

    forbidden_dti = api.create_program(
        _dscr_program_payload(name="Investor DSCR With Forbidden DTI",
                              max_dti_pct=50.00),
        ADMIN)
    validate_error(forbidden_dti, ERR_INVALID_REQUEST)


def _profit_and_loss_draft_file(api):
    program = fx.create_program(
        api, "PROFIT_AND_LOSS", name="CPA P&L 12-Month", statement_period_months=12,
        default_expense_factor_pct=50.00, min_expense_factor_pct=25.00,
        max_ltv_pct=80.00, min_fico=660, min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    borrower = fx.create_borrower(
        api, legal_name="Dana Reyes", fico_score=700, self_employed_flag=True,
        entity_ownership_pct=None, monthly_debt_obligations_cents=400000,
        verified_liquid_assets_cents=4000000, age_years=45)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, purchase_price_cents=75000000,
        property_value_cents=75000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=8.750, apor_pct=6.100,
        term_months=360, amortization_type="FULLY_AMORTIZING",
        monthly_taxes_cents=78000, monthly_insurance_cents=22000)
    return loan_file


def test_loan_file_read_returns_stored_inputs_and_create_time_computations(api):
    """A DRAFT file already carries its payment, its LTV and its reserves.

    PRD 3.3: "A file opens with `status` `DRAFT`, `doc_type` null, `pool_id` null and
    `assigned_underwriter_id` null." "`documented_reserves_months` is the borrower's
    `verified_liquid_assets_cents` divided by `pitia_monthly_cents`, rounded half up to
    two decimals" and "`dti_pct` is null whenever `qualifying_income_monthly_cents` is 0".

    Design: Corner/entities/corner_loan_file_retrieval_returns_stored_and_computed_fields
    """
    loan_file = _profit_and_loss_draft_file(api)

    row = validate_success(api.get_loan_file(loan_file["id"], UNDERWRITER))

    A.assert_money(row["loan_amount_cents"], 60000000, "loan_amount_cents")
    A.assert_pct_3dp(row["note_rate_pct"], "8.750", "note_rate_pct")
    A.assert_money(row["pitia_monthly_cents"], 572020, "pitia_monthly_cents")
    A.assert_pct_2dp(row["ltv_pct"], "80.00", "ltv_pct")
    A.assert_decimal_equals(row["documented_reserves_months"], "6.99", 2,
                            "documented_reserves_months")
    A.assert_is_null(row, "dti_pct", "doc_type", "pool_id",
                     "assigned_underwriter_id", "dscr_ratio", "rate_spread_pct",
                     "governing_credit_event_id")
    A.assert_fields(row, {"status": "DRAFT",
                          "points_and_fees_test_result": "NOT_TESTED",
                          "atr_documentation_status": "INCOMPLETE",
                          "safe_harbor_class": "NOT_EVALUATED",
                          "securitization_eligible": False,
                          "version": 1})


def test_loan_file_listing_carries_the_pagination_envelope_and_honours_the_filter(api):
    """No pagination input means limit 10 and offset 0; the status filter narrows.

    PRD 2.3: "`limit` controls page size: it defaults to 10" and "`offset` controls the
    starting position: it defaults to 0". "List responses populate `limit`, `offset`,
    `total_count` and `has_more` in `meta`, where `total_count` is the number of records
    matching the filter before pagination is applied and `has_more` is true when records
    remain beyond the current page."

    Design: Corner/entities/corner_loan_file_listing_pagination_envelope_and_filter
    """
    program = validate_success(api.create_program(_dscr_program_payload(), ADMIN), 201)
    borrower = validate_success(
        api.create_borrower(_minimal_borrower_payload(), LOAN_OFFICER), 201)
    first = validate_success(api.create_loan_file(
        _dscr_loan_payload(borrower["id"], program["id"]), LOAN_OFFICER), 201)
    second = validate_success(api.create_loan_file(
        _dscr_loan_payload(borrower["id"], program["id"], loan_amount_cents=40000000,
                           purchase_price_cents=55000000,
                           property_value_cents=55000000, note_rate_pct=9.250,
                           monthly_insurance_cents=18000, monthly_hoa_cents=15000,
                           gross_market_rent_cents=420000, lease_rent_cents=480000),
        LOAN_OFFICER), 201)

    default_page = api.list_loan_files(SECURITIZATION_ANALYST)
    rows = validate_success(default_page)
    A.assert_meta_pagination(default_page.json()["meta"], 10, 0, 2, False)
    assert len(rows) == 2
    A.assert_created_at_ascending(rows)
    A.assert_ids_equal(rows, [first["id"], second["id"]])

    one_row = api.list_loan_files(SECURITIZATION_ANALYST, {"limit": 1, "offset": 0})
    page = validate_success(one_row)
    A.assert_meta_pagination(one_row.json()["meta"], 1, 0, 2, True)
    assert len(page) == 1

    filtered = api.list_loan_files(SECURITIZATION_ANALYST, {"status": "UNDERWRITING"})
    empty = validate_success(filtered)
    A.assert_meta_pagination(filtered.json()["meta"], 10, 0, 0, False)
    assert empty == []


def test_a_well_formed_uuid_naming_no_loan_file_is_a_not_found(api):
    """The existence band answers with the resource's own code, not an empty 200.

    PRD 2.8: "Existence of every referenced resource, on every endpoint that has a path
    parameter or a foreign-key input." "The applicable code is the one naming the missing
    resource — `ERR_PROGRAM_NOT_FOUND`, `ERR_OVERLAY_NOT_FOUND`, `ERR_BORROWER_NOT_FOUND`,
    `ERR_LOAN_FILE_NOT_FOUND`".

    Design: Corner/entities/corner_unknown_loan_file_id_returns_loan_file_not_found
    """
    validate_error(api.get_loan_file(NON_EXISTENT_UUID, UNDERWRITER),
                   ERR_LOAN_FILE_NOT_FOUND)
    validate_error(api.get_loan_file(MISSING_UUID, UNDERWRITER),
                   ERR_LOAN_FILE_NOT_FOUND)


def test_omitting_the_required_property_value_persists_no_loan_file(api):
    """`property_value_cents` is not optional, and the rejection leaves no row.

    PRD 3.3: "`property_value_cents`, the estimated value at application, greater than
    zero". PRD 2.8: "`ERR_INVALID_REQUEST` — on every POST endpoint: a non-optional input
    field is missing".

    Design: Corner/entities/corner_loan_file_creation_missing_required_property_value
    """
    program = validate_success(api.create_program(_dscr_program_payload(), ADMIN), 201)
    borrower = validate_success(
        api.create_borrower(_minimal_borrower_payload(), LOAN_OFFICER), 201)
    payload = _dscr_loan_payload(borrower["id"], program["id"])
    payload.pop("property_value_cents")
    payload.pop("purchase_price_cents")

    validate_error(api.create_loan_file(payload, LOAN_OFFICER), ERR_INVALID_REQUEST)

    listing = api.list_loan_files(LOAN_OFFICER)
    assert validate_success(listing) == []
    A.assert_meta_pagination(listing.json()["meta"], 10, 0, 0, False)


def test_omitted_optional_flags_take_their_declared_defaults(api):
    """False, 100.00, true and three falses — never null.

    PRD 3.2: "`self_employed_flag` which defaults to false, `entity_ownership_pct` which
    defaults to 100.00" and "`documented_flag`, which defaults to true".
    PRD 3.6: "Three flags qualify the charge, all defaulting to false:
    `paid_to_affiliate_flag` marks a charge retained by an affiliate of the creditor,
    `prepaid_finance_charge_flag` marks a prepaid finance charge financed into the note,
    and `bona_fide_discount_flag` marks discount points as bona fide."

    Design: Corner/entities/corner_omitted_optional_flags_take_declared_defaults
    """
    program = validate_success(api.create_program(_dscr_program_payload(), ADMIN), 201)
    borrower = validate_success(
        api.create_borrower(_minimal_borrower_payload(), LOAN_OFFICER), 201)
    loan_file = validate_success(api.create_loan_file(
        _dscr_loan_payload(borrower["id"], program["id"]), LOAN_OFFICER), 201)
    validate_success(api.create_credit_event(
        {"borrower_id": borrower["id"], "event_type": "BK_CH7",
         "completion_date": "2024-01-01T00:00:00Z"}, LOAN_OFFICER), 201)
    validate_success(api.create_fee_item(
        {"loan_file_id": loan_file["id"], "fee_code": "F-ORIG",
         "fee_category": "ORIGINATION_POINTS", "amount_cents": 600000},
        LOAN_OFFICER), 201)

    stored = validate_success(api.get_borrower(borrower["id"], LOAN_OFFICER))
    A.assert_fields(stored, {"self_employed_flag": False, "credit_event_count": 1})
    A.assert_pct_2dp(stored["entity_ownership_pct"], "100.00", "entity_ownership_pct")

    events_response = api.list_credit_events(borrower["id"], LOAN_OFFICER)
    events = validate_success(events_response)
    A.assert_meta_pagination(events_response.json()["meta"], 10, 0, 1, False)
    A.assert_fields(events[0], {"documented_flag": True})

    fees_response = api.list_fee_items(loan_file["id"], LOAN_OFFICER)
    fees = validate_success(fees_response)
    A.assert_meta_pagination(fees_response.json()["meta"], 10, 0, 1, False)
    A.assert_fields(fees[0], {"paid_to_affiliate_flag": False,
                              "prepaid_finance_charge_flag": False,
                              "bona_fide_discount_flag": False,
                              "status": "ACTIVE",
                              "inclusion_in_test": "INCLUDED"})


def test_the_client_may_not_supply_the_computed_credit_event_count(api):
    """`credit_event_count` is server-maintained, and the input form rejects it.

    PRD 3.2: "The borrower row also exposes `credit_event_count`, a computed tally of the
    derogatory events recorded against them, which starts at zero and is recomputed on
    every credit-event creation."
    PRD 2.8: "or the body carries a field the endpoint does not declare."

    Design: Corner/entities/corner_computed_field_credit_event_count_input_ignored
    """
    borrower = validate_success(
        api.create_borrower(_minimal_borrower_payload(), LOAN_OFFICER), 201)
    A.assert_fields(borrower, {"credit_event_count": 0})

    rejected = api.create_borrower(
        _minimal_borrower_payload("Client Supplied Count", credit_event_count=5),
        LOAN_OFFICER)
    validate_error(rejected, ERR_INVALID_REQUEST)

    validate_success(api.create_credit_event(
        {"borrower_id": borrower["id"], "event_type": "BK_CH13",
         "completion_date": "2025-01-01T00:00:00Z"}, LOAN_OFFICER), 201)

    A.assert_fields(validate_success(api.get_borrower(borrower["id"], LOAN_OFFICER)),
                    {"credit_event_count": 1})


def test_identity_and_version_are_minted_by_the_server_not_the_client(api):
    """`version` is exactly 1 on create, and a supplied `version` is an unknown field.

    PRD 2.4: "Every resource carries an `id` that is a server-minted UUID with no type
    prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC instant with three
    fractional digits." "an integer `version` that starts at 1 and increments by one each
    time the resource is mutated."
    PRD 2.7: "No other endpoint takes a version field. Requests that supply one where it
    is not called for are handled by the request-shape rule as unknown fields."

    Design: Corner/entities/corner_system_fields_on_program_create_input_ignored
    """
    response = api.create_program(
        {"program_code": "ASSET_DEPLETION", "name": "Asset Depletion 84",
         "depletion_horizon_months": 84, "max_ltv_pct": 80.00, "min_fico": 660,
         "min_reserves_months": 6, "max_dti_pct": 60.00,
         "min_residual_income_cents": 250000,
         "second_valuation_ltv_threshold_pct": 85.00,
         "second_valuation_loan_amount_threshold_cents": 150000000,
         "atr_exempt_flag": False, "seasoning_matrix": dict(SEASONING_MATRIX)},
        ADMIN)
    created = validate_success(response, 201)
    A.assert_created_row(created)
    assert is_valid_uuid(created["id"]), f"id is not a bare UUID: {created['id']!r}"
    assert is_iso8601_timestamp(created["created_at"])
    assert is_iso8601_timestamp(created["updated_at"])
    A.assert_instant_equals(created["updated_at"], created["created_at"], "updated_at")
    envelope = response.json()
    assert envelope["meta"]["api_request_id"]
    assert envelope["meta"]["api_request_timestamp"]

    supplied_version = api.create_program(
        {"program_code": "BANK_STATEMENT_24MO", "name": "Client Supplied Version",
         "statement_period_months": 24, "default_expense_factor_pct": 50.00,
         "min_expense_factor_pct": 25.00, "max_ltv_pct": 80.00, "min_fico": 660,
         "min_reserves_months": 6, "max_dti_pct": 50.00,
         "min_residual_income_cents": 250000,
         "second_valuation_ltv_threshold_pct": 85.00,
         "second_valuation_loan_amount_threshold_cents": 150000000,
         "seasoning_matrix": dict(SEASONING_MATRIX), "version": 7},
        ADMIN)
    validate_error(supplied_version, ERR_INVALID_REQUEST)
    assert supplied_version.json()["meta"]["api_request_id"]


def test_a_non_member_enum_fails_shape_while_a_bad_number_fails_the_domain(api):
    """Two different bands: request shape at 400, numeric domain at 422.

    PRD 3.1: "`min_fico` is the representative-credit-score floor between 300 and 850,
    checked inclusively." "`fico_score` must be between 300 and 850 inclusive".
    PRD 3.2: "`age_years`, a whole number between 18 and 120".
    PRD 2.8: "an enum value is not a declared member" is `ERR_INVALID_REQUEST`, and
    "`ERR_VALUE_OUT_OF_RANGE` — on `POST /borrowers`".

    Design: Corner/entities/corner_type_constraints_enum_member_and_numeric_domain
    """
    bad_enum = api.create_program(
        {"program_code": "BANK_STATEMENT_18MO", "name": "Not An Enum Member",
         "statement_period_months": 18, "default_expense_factor_pct": 50.00,
         "min_expense_factor_pct": 25.00, "max_ltv_pct": 80.00, "min_fico": 660,
         "min_reserves_months": 6, "max_dti_pct": 50.00,
         "min_residual_income_cents": 250000,
         "second_valuation_ltv_threshold_pct": 85.00,
         "second_valuation_loan_amount_threshold_cents": 150000000,
         "seasoning_matrix": dict(SEASONING_MATRIX)},
        ADMIN)
    validate_error(bad_enum, ERR_INVALID_REQUEST)

    validate_error(api.create_borrower(
        _minimal_borrower_payload("Out Of Range Fico", fico_score=900), LOAN_OFFICER),
        ERR_VALUE_OUT_OF_RANGE)
    validate_error(api.create_borrower(
        _minimal_borrower_payload("Out Of Range Age", age_years=15), LOAN_OFFICER),
        ERR_VALUE_OUT_OF_RANGE)


def test_a_credit_event_carries_no_version_and_no_updated_at(api):
    """The one write-once entity in the platform, readable and filterable.

    PRD 2.4: "Credit events are the single exception. A credit event is an immutable
    historical record: it carries only `id` and `created_at`, has neither an `updated_at`
    timestamp nor a `version` counter, and has no update endpoint of any kind."
    PRD 3.2: "the borrower's event list can be read back, including the undocumented
    ones, optionally filtered by `event_type`."

    Design: Corner/entities/corner_credit_event_is_immutable_and_carries_no_version
    """
    borrower = validate_success(
        api.create_borrower(_minimal_borrower_payload(), LOAN_OFFICER), 201)
    event = validate_success(api.create_credit_event(
        {"borrower_id": borrower["id"], "event_type": "SHORT_SALE",
         "completion_date": "2024-06-15T00:00:00Z", "documented_flag": True},
        LOAN_OFFICER), 201)
    A.assert_created_row(event, write_once=True)
    assert "version" not in event, f"credit event carries a version: {event!r}"
    assert "updated_at" not in event, f"credit event carries updated_at: {event!r}"

    rows = validate_success(api.list_credit_events(borrower["id"], UNDERWRITER,
                                                   {"event_type": "SHORT_SALE"}))
    assert len(rows) == 1
    A.assert_ids_equal(rows, [event["id"]])
    A.assert_instant_equals(rows[0]["completion_date"], "2024-06-15T00:00:00Z",
                            "completion_date")
    assert "version" not in rows[0] and "updated_at" not in rows[0]


def test_a_credit_event_naming_no_borrower_is_a_borrower_not_found(api):
    """The parent must exist before the child may be written.

    PRD 3.2: "Prior derogatory history is recorded one event at a time by a `LoanOfficer`
    or an `Underwriter`, in a payload naming the `borrower_id`".
    PRD 2.8: "The applicable code is the one naming the missing resource" and
    "`ERR_BORROWER_NOT_FOUND`".

    Design: Corner/entities/corner_credit_event_requires_existing_parent_borrower
    """
    borrower = validate_success(
        api.create_borrower(_minimal_borrower_payload(), LOAN_OFFICER), 201)

    orphan = api.create_credit_event(
        {"borrower_id": "00000000-0000-4000-8000-0000000000cc",
         "event_type": "BK_CH7", "completion_date": "2024-01-01T00:00:00Z"},
        UNDERWRITER)
    validate_error(orphan, ERR_BORROWER_NOT_FOUND)

    accepted = api.create_credit_event(
        {"borrower_id": borrower["id"], "event_type": "BK_CH7",
         "completion_date": "2024-01-01T00:00:00Z"}, UNDERWRITER)
    validate_success(accepted, 201)

    listing = api.list_credit_events(borrower["id"], LOAN_OFFICER)
    assert len(validate_success(listing)) == 1
    A.assert_meta_pagination(listing.json()["meta"], 10, 0, 1, False)


def test_body_foreign_keys_resolve_in_the_order_the_endpoint_lists_them(api):
    """Both keys unknown reports the borrower, never the program.

    PRD 2.8: "References are resolved strictly left to right: path segments first, parent
    before child, and then request-body foreign keys in the order the fields are listed
    for that endpoint."
    PRD 3.3: "A `LoanOfficer` opens a loan file in `DRAFT` by naming the `borrower_id` and
    the `program_id` the file will be underwritten to".

    Design: Corner/entities/corner_flat_topology_foreign_keys_validated_left_to_right
    """
    program = validate_success(api.create_program(_dscr_program_payload(), ADMIN), 201)
    borrower = validate_success(
        api.create_borrower(_minimal_borrower_payload(), LOAN_OFFICER), 201)

    both_unknown = api.create_loan_file(
        _dscr_loan_payload(OTHER_MISSING_UUID, MISSING_UUID), LOAN_OFFICER)
    validate_error(both_unknown, ERR_BORROWER_NOT_FOUND)

    program_unknown = api.create_loan_file(
        _dscr_loan_payload(borrower["id"], MISSING_UUID), LOAN_OFFICER)
    validate_error(program_unknown, ERR_PROGRAM_NOT_FOUND)

    assert validate_success(api.list_loan_files(LOAN_OFFICER)) == []
