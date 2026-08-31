"""Building the group, its member entities and its state footprint."""

from test_helpers import (
    UNKNOWN_UUIDS,
    ApiErrorId,
    TEST_USERS,
    assert_activity_record,
    assert_common_fields,
    assert_millisecond_timestamp,
    assert_state_registration,
    assert_taxpayer_group,
    create_group,
    create_legal_entity,
    create_registration,
    is_valid_uuid,
    set_clock,
    setup_bare_registration,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["tax_manager_headers"]
SA = TEST_USERS["state_analyst_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_new_group_seeds_its_own_compliance_fields(api):
    """PRD 3.1: "A newly created group starts with `open_registration_obligations` at 0 and `compliance_posture` at `COMPLIANT`, and its `nowhere_sales_pool` — described in Section 3.4 — starts at 0."
    PRD 3.1: "An optional `fiscal_year_end_month` records the calendar month in which the group's tax year ends; it must be between 1 and 12 inclusive and defaults to 12."
    PRD 2.4: "Most resources additionally carry an `updated_at` timestamp, in the same ISO 8601 UTC format with three fractional digits, and a `version`, which is an integer that starts at 1 when the resource is created and increases by exactly 1 on each mutation of that resource."

    Design: Corner/entities/create_taxpayer_group_returns_seeded_derived_fields
    """
    set_clock()
    response = api.create_group(
        {
            "name": "Fresh Group",
            "base_state_code": "DE",
            "everywhere_sales": 1000000,
            "everywhere_property": 400000,
            "everywhere_payroll": 200000,
        },
        TM,
    )
    group = validate_success(response, 201)
    assert_taxpayer_group(group)

    assert group["compliance_posture"] == "COMPLIANT", (
        f"A brand new group must start COMPLIANT, got {group['compliance_posture']}"
    )
    assert group["open_registration_obligations"] == 0, (
        "A brand new group must start with zero open registration obligations"
    )
    assert group["nowhere_sales_pool"] == 0, (
        "A brand new group must start with a zero nowhere sales pool"
    )
    assert group["version"] == 1, "A newly created resource starts at version 1"
    assert group["fiscal_year_end_month"] == 12, (
        "fiscal_year_end_month defaults to 12 when omitted"
    )


def test_registration_defaults_fill_in_the_state_regime(api):
    """PRD 3.1: "Optional configuration fills in the rest of the state's regime: `economic_nexus_sales_threshold` (defaulting to 500,000) and `economic_nexus_employee_days_threshold` (defaulting to 15) set the two nexus tripwires; `due_month` (1 to 12, defaulting to 4) and `due_day` (1 to 28, defaulting to 15) set the original return due date; `extension_months` (0 to 12, defaulting to 6) sets how far a granted extension moves it; `estimated_installment_count` (1 to 4, defaulting to 4) says how many estimated installments the state requires; `safe_harbor_basis` selects the estimated-payment variant from `PRIOR_YEAR_100`, `PRIOR_YEAR_110` and `CURRENT_YEAR_90`, defaulting to `PRIOR_YEAR_100`; `prior_year_tax` and `current_year_estimated_tax` (both defaulting to 0) supply the two safe-harbor bases; and `state_permits_early_revocation`, defaulting to false, records whether the state tolerates revoking an election inside its binding period."
    PRD 3.1: "A fresh registration begins with `nexus_status` at `NONE`, `registration_status` at `NOT_REQUIRED`, a null `state_account_number`, a null `registered_on_date`, `calendar_rolled_through_year` at 0, and both money pools — `total_payments_received` and `unapplied_payment_balance` — at 0."

    Design: Corner/entities/registration_defaults_applied_when_optional_fields_omitted
    """
    set_clock()
    group = create_group(name="Defaults Group")

    response = api.create_registration(
        group["id"],
        {
            "state_code": "OR",
            "factor_formula": "SINGLE_SALES_FACTOR",
            "tax_rate": 0.066,
            "throwback_rule": "NONE",
            "service_sourcing_rule": "MARKET_BASED",
        },
        TM,
    )
    registration = validate_success(response, 201)
    assert_state_registration(registration)

    assert registration["due_month"] == 4 and registration["due_day"] == 15
    assert registration["extension_months"] == 6
    assert registration["estimated_installment_count"] == 4
    assert registration["safe_harbor_basis"] == "PRIOR_YEAR_100"
    assert registration["prior_year_tax"] == 0
    assert registration["current_year_estimated_tax"] == 0
    assert registration["economic_nexus_sales_threshold"] == 500000
    assert registration["economic_nexus_employee_days_threshold"] == 15
    assert registration["nexus_status"] == "NONE"
    assert registration["registration_status"] == "NOT_REQUIRED"
    assert registration["state_permits_early_revocation"] is False
    assert registration["calendar_rolled_through_year"] == 0
    assert registration["total_payments_received"] == 0
    assert registration["unapplied_payment_balance"] == 0


def test_return_due_date_derives_from_the_state_filing_calendar(api):
    """PRD 3.4: "Its `original_due_date` is computed as midnight UTC on the registration's `due_month` and `due_day` in the year following the return's `tax_year`; a 2025 return on a registration configured for the fifteenth of the fourth month is therefore due at midnight UTC on 15 April 2026."
    PRD 3.4: "A newly opened return begins at `preparation_status` `DRAFT` and `payment_status` `UNPAID`, with `apportionment_variant` null and every derived money field at 0: `apportionment_percentage`, `modification_total`, `state_taxable_income`, `tax_before_credits`, `credits_applied_total`, `estimated_credits_applied`, `assessment_added_total`, `balance_due` and `amendment_count`."

    Design: Corner/entities/filing_original_due_date_computed_from_registration_calendar
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "Calendar Group"},
        registration_overrides={"due_month": 3, "due_day": 1, "extension_months": 6},
    )

    response = api.create_filing(
        ctx["registration_id"],
        {"tax_year": 2026, "filing_basis": "COMBINED_UNITARY",
         "federal_taxable_income": 1000000},
        SA,
    )
    filing = validate_success(response, 201)

    assert filing["original_due_date"].startswith("2027-03-01T00:00:00"), (
        "A 2026 return on a March-1 calendar is due midnight UTC 2027-03-01, "
        f"got {filing['original_due_date']}"
    )
    assert filing["extended_due_date"] is None
    assert filing["preparation_status"] == "DRAFT"
    assert filing["payment_status"] == "UNPAID"
    assert filing["apportionment_percentage"] == 0
    assert filing["balance_due"] == 0


def test_server_mints_identity_and_leaves_system_fields_null(api):
    """PRD 2.4: "Every resource the API returns carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with three fractional digits."
    PRD 2.4: "Most resources additionally carry an `updated_at` timestamp, in the same ISO 8601 UTC format with three fractional digits, and a `version`, which is an integer that starts at 1 when the resource is created and increases by exactly 1 on each mutation of that resource."
    PRD 3.1: "A fresh registration begins with `nexus_status` at `NONE`, `registration_status` at `NOT_REQUIRED`, a null `state_account_number`, a null `registered_on_date`, `calendar_rolled_through_year` at 0, and both money pools — `total_payments_received` and `unapplied_payment_balance` — at 0."

    Design: Corner/entities/system_fields_are_server_minted_on_every_entity
    """
    set_clock()
    group = create_group(name="System Fields Group")

    response = api.create_registration(
        group["id"],
        {"state_code": "CA", "factor_formula": "DOUBLE_WEIGHTED_SALES",
         "tax_rate": 0.0884, "throwback_rule": "THROWBACK",
         "service_sourcing_rule": "MARKET_BASED"},
        TM,
    )
    registration = validate_success(response, 201)

    assert is_valid_uuid(registration["id"]), (
        f"id must be a bare 8-4-4-4-12 UUID with no type prefix, got {registration['id']!r}"
    )
    assert_millisecond_timestamp(registration["created_at"], "created_at")
    assert_millisecond_timestamp(registration["updated_at"], "updated_at")
    assert registration["version"] == 1
    assert registration["state_account_number"] is None
    assert registration["registered_on_date"] is None


def test_reading_an_unknown_return_reports_the_filing_not_found_code(api):
    """PRD 2.7: "Each entity has its own not-found code: `ERR_GROUP_NOT_FOUND` for a taxpayer group, `ERR_LEGAL_ENTITY_NOT_FOUND` for a member entity, `ERR_REGISTRATION_NOT_FOUND` for a state registration, `ERR_ACTIVITY_RECORD_NOT_FOUND` for an activity record, `ERR_ELECTION_NOT_FOUND` for a filing election, `ERR_FILING_NOT_FOUND` for a state return, `ERR_CREDIT_CLAIM_NOT_FOUND` for a credit claim, `ERR_PAYMENT_NOT_FOUND` for an estimated payment, `ERR_EXTENSION_NOT_FOUND` for an extension request, `ERR_NOTICE_NOT_FOUND` for a notice, and `ERR_VDA_NOT_FOUND` for a voluntary disclosure agreement. All eleven return HTTP 404."

    Design: Corner/entities/get_filing_with_unknown_id_returns_not_found
    """
    set_clock()

    response = api.get_filing(UNKNOWN_UUIDS["filing"], AUD)

    error = validate_error(response, ApiErrorId.ERR_FILING_NOT_FOUND.value)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"
    assert error["message"].strip(), "The error envelope must carry a message"


def test_registration_missing_a_required_field_is_rejected(api):
    """PRD 3.1: "Opening one requires the `state_code` (again exactly two uppercase letters), the `factor_formula` that names the state's weighting scheme (`EQUAL_WEIGHTED_THREE`, `DOUBLE_WEIGHTED_SALES` or `SINGLE_SALES_FACTOR`), the `tax_rate` applied to state taxable income (a fraction between 0 and 1 inclusive), the `throwback_rule` governing origin sales whose purchaser is not taxable in the destination state (`THROWBACK`, `THROWOUT` or `NONE`), and the `service_sourcing_rule` (`MARKET_BASED` or `COST_OF_PERFORMANCE`)."
    PRD 2.11: "5. Payload shape on every write — required fields present, enum members recognized, numeric ranges honored (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_registration_missing_required_field_returns_invalid_request
    """
    set_clock()
    group = create_group(name="Missing Field Group")

    response = api.create_registration(
        group["id"],
        {"state_code": "WA", "factor_formula": "SINGLE_SALES_FACTOR",
         "tax_rate": 0.01, "service_sourcing_rule": "MARKET_BASED"},
        TM,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    listing, meta = validate_paginated(
        api.list_group_registrations(group["id"], TM, {"limit": 10, "offset": 0})
    )
    assert listing == [], "A rejected registration create must persist nothing"
    assert meta["total_count"] == 0


def test_registration_with_an_unknown_factor_formula_is_rejected(api):
    """PRD 2.4: "Every enumeration value in this system — every state name, every category, every doctrine selector — is an exact uppercase string, and is compared literally. A payload carrying a value outside an enumeration's declared members is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_registration_invalid_enum_returns_invalid_request
    """
    set_clock()
    group = create_group(name="Enum Group")

    response = api.create_registration(
        group["id"],
        {"state_code": "WA", "factor_formula": "TRIPLE_WEIGHTED_SALES",
         "tax_rate": 0.01, "throwback_rule": "NONE",
         "service_sourcing_rule": "MARKET_BASED"},
        TM,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    listing, _ = validate_paginated(
        api.list_group_registrations(group["id"], TM, {"limit": 10, "offset": 0})
    )
    assert listing == [], "A rejected registration create must persist nothing"


def test_activity_record_carries_neither_updated_at_nor_version(api):
    """PRD 2.4: "`ActivityRecord` is the single exception. An activity record is immutable once written: it is never updated, never re-versioned, and consequently carries **only** `id` and `created_at`. Neither `updated_at` nor `version` appears on an `ActivityRecord` at all."

    Design: Corner/entities/activity_record_is_immutable_and_carries_no_version
    """
    ctx = setup_bare_registration(
        group_overrides={"name": "Immutable Group"}, include_member=True,
    )

    response = api.create_activity_record(
        ctx["registration_id"],
        {"legal_entity_id": ctx["le_a_id"], "tax_year": 2026,
         "destination_sales": 250000},
        SA,
    )
    record = validate_success(response, 201)
    assert_activity_record(record)

    assert "version" not in record, "ActivityRecord must expose no version field"
    assert "updated_at" not in record, "ActivityRecord must expose no updated_at field"

    reread = validate_success(api.get_activity_record(record["id"], AUD))
    assert reread["destination_sales"] == 250000
    assert "version" not in reread and "updated_at" not in reread


def test_member_entity_under_an_unknown_group_reports_group_not_found(api):
    """PRD 2.11: "3. Path identifier resolution, left to right (the eleven 404 codes of Section 2.7)."
    PRD 2.7: "Resource identifiers embedded in a URL path are resolved strictly **left to right**, and the first identifier that fails to resolve determines the error."

    Design: Corner/entities/legal_entity_creation_under_unknown_group_returns_not_found
    """
    set_clock()

    response = api.create_legal_entity(
        UNKNOWN_UUIDS["group"],
        {"name": "Orphan Co", "incorporation_state_code": "DE"},
        TM,
    )

    validate_error(response, ApiErrorId.ERR_GROUP_NOT_FOUND.value)
    assert response.status_code == 404


def test_activity_for_a_member_of_another_group_is_rejected(api):
    """PRD 3.1: "A record's `legal_entity_id` must name a member of the very same group that owns the registration in the path, or the write is rejected with `ERR_ENTITY_NOT_IN_GROUP`; and its `tax_year` must be no earlier than 2000, or the write is rejected with `ERR_ACTIVITY_YEAR_MISMATCH`."

    Design: Corner/entities/activity_record_for_entity_of_another_group_rejected
    """
    set_clock()
    group_one = create_group(name="Group One")
    create_legal_entity(group_one["id"], name="Member One")
    registration = create_registration(group_one["id"])

    group_two = create_group(
        name="Group Two", base_state_code="NV", everywhere_sales=500000,
        everywhere_property=100000, everywhere_payroll=80000,
    )
    foreign_member = create_legal_entity(
        group_two["id"], name="Member Two", incorporation_state_code="NV",
    )

    response = api.create_activity_record(
        registration["id"],
        {"legal_entity_id": foreign_member["id"], "tax_year": 2026,
         "destination_sales": 100000},
        SA,
    )

    validate_error(response, ApiErrorId.ERR_ENTITY_NOT_IN_GROUP.value)
    listing, _ = validate_paginated(
        api.list_activity_records(
            AUD, {"registration_id": registration["id"], "limit": 10, "offset": 0}
        )
    )
    assert listing == [], "A rejected activity write must persist nothing"


def test_group_listing_reports_the_pagination_envelope(api):
    """PRD 2.3: "`limit` controls page size: it defaults to 10, its minimum accepted value is 1, and its maximum accepted value is 100."
    PRD 2.3: "For list responses the `meta` object carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of records matching the filter before pagination is applied and `has_more` is true when `offset` plus the number of returned records is less than `total_count`."

    Design: Corner/entities/list_groups_returns_pagination_envelope
    """
    set_clock()
    create_group(name="Alpha Group")
    create_group(name="Beta Group", base_state_code="NV", everywhere_sales=1,
                 everywhere_property=1, everywhere_payroll=1)
    create_group(name="Gamma Group", base_state_code="TX", everywhere_sales=2,
                 everywhere_property=2, everywhere_payroll=2)

    response = api.list_groups(AUD, {"limit": 2, "offset": 0})
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(rows) == 2, f"Expected 2 rows on the first page, got {len(rows)}"
    for row in rows:
        assert_common_fields(row, "TaxpayerGroup")
