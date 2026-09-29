"""Stored shapes: creation, retrieval, listing, defaults and computed fields.

Every resource declares which of its fields the client supplies, which the server
defaults, and which it computes. These tests read those declarations back off the
wire — the initial ledgers, the omitted optional flags, the fields that stay null
until a later transition fills them, and the pagination envelope.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    BATCH_STATUS_STAGED,
    CLEARANCE_PENDING,
    DEAL_STATUS_ABANDONED,
    DEAL_STATUS_SOURCING,
    DEFAULT_CLOCK_INSTANT,
    DEFAULT_LIMIT,
    DISPOSITION_ESCROWED,
    DISPOSITION_UNASSIGNED,
    EMPLOYMENT_PROSPECTIVE,
    LIABILITY_EQUIPMENT_LEASE,
    LIABILITY_UNPAID_PTO,
    NPI_A,
    OFFER_STATUS_DRAFT,
    PHYSICIAN_NAME_A,
    POSTURE_AT_RISK,
    POSTURE_BLOCKED,
    RETENTION_YEARS_DEFAULT,
    ROLE_CODE_MA,
    SPECIALTY_PRIMARY_CARE,
    STRUCTURE_ASSET,
    TASK_IT_DATA_MIGRATION,
    TASK_STATUS_OPEN,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    advance_deal_status,
    closed_deal,
    create_acquisition,
    create_batch,
    create_cardiology_acquisition,
    create_liability,
    create_offer,
    create_report,
    create_task,
    read_acquisition,
    reset_clock,
    set_clock,
    set_disposition,
)

ESCROW_TOTAL_CENTS = 10_000_000
POOL_TOTAL_CENTS = 3_000_000
TRAILING_COLLECTIONS_CENTS = 500_000_000
MALPRACTICE_PREMIUM_CENTS = 4_800_000
HEADCOUNT = 5
TARGET_CLOSE_ON = "2026-11-01"
ZERO_COVERAGE_PCT = 0.00

BATCH_RECORD_COUNT = 20_000
BATCH_LAST_ENCOUNTER_ON = "2026-07-15"
BATCH_PURGE_ELIGIBLE_ON = "2036-07-15"

# An MA on 3,600,000 cents harmonises to 3,778,615 and is lifted to the floor.
MA_UPLIFT_CENTS = 144_000
MA_PTO_CENTS = 34_615
MA_FLOOR_CENTS = 4_200_000
MA_BONUS_CENTS = 210_000

LEASE_EXPOSURE_CENTS = 2_500_000
PTO_EXPOSURE_CENTS = 400_000
ESCROW_AVAILABLE_AFTER_LEASE_CENTS = 7_500_000

# One reportable month for the standard base-plus-incentive plan. 700 work RVUs
# in August earn 1,666,667 of pro-rated base plus 3,150,000 of incentive against
# 2,483,333 already paid on the projection, and the 8,400 annualised volume
# re-benchmarks the plan to 57,800,000 of total cash compensation.
REPORTING_CLOCK_INSTANT = "2026-09-05T00:00:00Z"
REPORT_PERIOD_START = "2026-08-01"
REPORT_PERIOD_END = "2026-08-31"
REPORT_ACTUAL_WRVU = 700
REPORT_COLLECTIONS_CENTS = 41_000_000
TRUE_UP_CENTS = 2_333_334
PERCENTILE_AFTER = 95.45


def test_opening_a_deal_returns_201_with_both_ledgers_fully_available(api: ApiClient):
    """The create response is the stored row, with both money ledgers uncommitted.

    PRD: "A newly opened acquisition sits in `deal_status` `SOURCING` with
    `compliance_clearance` `PENDING` and `readiness_posture` `BLOCKED`, carries
    `hr_staffing_coverage_pct` of 0.00, and has `tail_premium_cents` not yet
    computed."

    Design: Corner/entities/acquisition_creation_returns_201_with_ledgers_initialised
    """
    reset_clock(api)

    response = api.create_acquisition(f.acquisition_payload(), DEAL_LEAD)

    acquisition = validate_success(response, 201)
    assert response.json()["response_type"] == "object"
    assert is_valid_uuid(acquisition["id"])
    a.assert_status(acquisition, DEAL_STATUS_SOURCING, "deal_status")
    assert acquisition["compliance_clearance"] == CLEARANCE_PENDING
    assert acquisition["readiness_posture"] == POSTURE_BLOCKED
    a.assert_retention_pool(acquisition, POOL_TOTAL_CENTS, 0, POOL_TOTAL_CENTS)
    a.assert_escrow(acquisition, ESCROW_TOTAL_CENTS, 0, ESCROW_TOTAL_CENTS)
    a.assert_percentage_equals(
        acquisition["hr_staffing_coverage_pct"], ZERO_COVERAGE_PCT, "hr_staffing_coverage_pct"
    )
    a.assert_common_fields(acquisition, expected_version=1)
    a.assert_fields_null(acquisition, "closed_at", "abandoned_reason")


def test_reading_the_deal_back_echoes_every_stored_input(api: ApiClient):
    """Nothing is dropped and nothing is re-derived differently on the read path.

    PRD: "Each carries an `id` that is a server-minted UUID with no type prefix and
    no client-supplied component; a `created_at` and an `updated_at`, both ISO 8601
    UTC instants with exactly three fractional digits; and a `version`, a plain
    integer that starts at 1 when the row is inserted and increases by exactly 1 on
    every mutation of that row."

    Design: Corner/entities/acquisition_retrieval_returns_the_stored_entity
    """
    reset_clock(api)
    created = create_acquisition(api)

    fetched = validate_success(api.get_acquisition(created["id"], COMPLIANCE_OFFICER))

    assert fetched["id"] == created["id"]
    assert fetched["target_practice_name"] == "Lakeside Family Medicine"
    assert fetched["specialty"] == SPECIALTY_PRIMARY_CARE
    assert fetched["structure"] == STRUCTURE_ASSET
    a.assert_money_equals(
        fetched["annual_malpractice_premium_cents"],
        MALPRACTICE_PREMIUM_CENTS,
        "annual_malpractice_premium_cents",
    )
    a.assert_money_equals(
        fetched["trailing_annual_collections_cents"],
        TRAILING_COLLECTIONS_CENTS,
        "trailing_annual_collections_cents",
    )
    assert fetched["target_close_on"] == TARGET_CLOSE_ON
    assert fetched["required_staff_headcount"] == HEADCOUNT
    a.assert_instant_equals(fetched["created_at"], DEFAULT_CLOCK_INSTANT, "created_at")
    a.assert_instant_equals(fetched["updated_at"], DEFAULT_CLOCK_INSTANT, "updated_at")


def test_the_deal_listing_paginates_and_filters_on_the_workflow_status(api: ApiClient):
    """Two pages over three rows, with total_count counted before pagination.

    PRD: "Every list response populates all four pagination fields in `meta`:
    `limit` and `offset` echo the effective values actually applied, `total_count`
    reports the number of rows matching the filter before pagination is applied,
    and `has_more` is true exactly when the sum of `offset` and the number of rows
    returned in this page is less than `total_count`."

    Design: Corner/entities/acquisition_listing_is_paginated_with_total_count_and_has_more
    """
    reset_clock(api)
    first = create_acquisition(api)
    second = create_cardiology_acquisition(api)
    third = create_acquisition(api, target_practice_name="Riverbend Orthopedics")
    advance_deal_status(
        api,
        second["id"],
        DEAL_STATUS_ABANDONED,
        abandoned_reason="Seller withdrew from the letter of intent.",
    )

    response = api.list_acquisitions({"limit": 2, "offset": 0}, DEAL_LEAD)

    page_one, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(page_one) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_acquisitions({"limit": 2, "offset": 2}, DEAL_LEAD)
    )
    assert len(page_two) == 1
    assert meta_two["has_more"] is False

    sourcing = a.assert_total_count(
        api.list_acquisitions({"deal_status": DEAL_STATUS_SOURCING}, DEAL_LEAD), 2
    )
    a.assert_contains_id(sourcing, first["id"])
    a.assert_contains_id(sourcing, third["id"])
    a.assert_excludes_id(sourcing, second["id"])

    abandoned = a.assert_total_count(
        api.list_acquisitions({"deal_status": DEAL_STATUS_ABANDONED}, DEAL_LEAD), 1
    )
    a.assert_contains_id(abandoned, second["id"])

    _, default_meta = validate_paginated(api.list_acquisitions({}, DEAL_LEAD))
    assert default_meta["total_count"] == 3
    assert default_meta["limit"] == DEFAULT_LIMIT


def test_an_unknown_deal_identifier_is_a_404_not_an_empty_body(api: ApiClient):
    """A well-formed identifier that resolves to nothing is an error, not a blank.

    PRD: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/acquisition_get_with_unknown_id_returns_not_found
    """
    reset_clock(api)

    response = api.get_acquisition(NON_EXISTENT_UUID, DEAL_LEAD)

    error = validate_error(response, ApiErrorId.RESOURCE_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"
    assert error["error_id"] == ApiErrorId.RESOURCE_NOT_FOUND
    assert error["message"]


def test_the_escrow_total_is_required_and_is_never_defaulted_to_zero(api: ApiClient):
    """Omitting a mandatory ledger total is a schema violation, not a zero.

    PRD: "Finally, the two ledger totals are authorised: `retention_pool_total_cents`
    for staff retention bonuses and `escrow_total_cents` for the indemnity escrow,
    each of which may be zero but never negative."

    Design: Corner/entities/acquisition_missing_required_escrow_total_rejected
    """
    reset_clock(api)
    payload = f.acquisition_payload()
    del payload["escrow_total_cents"]

    validate_error(api.create_acquisition(payload, DEAL_LEAD), ApiErrorId.INVALID_REQUEST, 400)

    for omitted in ("retention_pool_total_cents", "target_close_on", "required_staff_headcount"):
        variant = f.acquisition_payload()
        del variant[omitted]
        validate_error(
            api.create_acquisition(variant, DEAL_LEAD), ApiErrorId.INVALID_REQUEST, 400
        )

    a.assert_total_count(api.list_acquisitions({}, DEAL_LEAD), 0)


def test_the_tail_coverage_months_input_defaults_to_zero_not_null(api: ApiClient):
    """A declared default is stored as its value; the derived tail is still unpriced.

    PRD: "The buyer states how many months of prior-acts coverage it intends to
    purchase in `tail_coverage_months`, an integer from 0 through 120 inclusive that
    defaults to 0 when omitted."

    Design: Corner/entities/acquisition_tail_coverage_months_defaults_to_zero
    """
    reset_clock(api)

    defaulted = create_acquisition(api)
    assert defaulted["tail_coverage_months"] == 0
    assert defaulted["tail_coverage_months"] is not None
    a.assert_fields_null(defaulted, "tail_premium_cents")

    supplied = create_acquisition(
        api, target_practice_name="Riverbend Orthopedics", tail_coverage_months=60
    )
    assert supplied["tail_coverage_months"] == 60


def test_board_certification_defaults_to_false_and_keeps_the_filter_total(api: ApiClient):
    """The omitted flag stores false, so the boolean filter still matches the row.

    PRD: "Board certification is recorded in `board_certified`, which defaults to
    false when the field is omitted."

    Design: Corner/entities/physician_board_certified_defaults_to_false
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    payload = f.physician_payload(acquisition["id"], npi=NPI_A, full_name=PHYSICIAN_NAME_A)
    payload.pop("board_certified", None)

    physician = validate_success(api.create_physician(payload, DEAL_LEAD), 201)

    assert physician["board_certified"] is False
    assert physician["employment_status"] == EMPLOYMENT_PROSPECTIVE
    rows = a.assert_total_count(
        api.list_physicians(
            {"acquisition_id": acquisition["id"], "board_certified": False}, DEAL_LEAD
        ),
        1,
    )
    a.assert_contains_id(rows, physician["id"])


def test_a_checklist_line_is_blocking_by_default_and_derives_its_domain(api: ApiClient):
    """The default drags the posture off BLOCKED, and the domain is not an input.

    PRD: "Either an `IntegrationManager` or a `DealLead` adds one, naming the
    `acquisition_id`, the `task_code`, and the `due_on` date by which the line must
    be complete, and optionally setting `is_blocking`, which defaults to true."

    Design: Corner/entities/readiness_task_is_blocking_defaults_to_true
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    assert acquisition["readiness_posture"] == POSTURE_BLOCKED

    task = create_task(
        api, acquisition["id"], task_code=TASK_IT_DATA_MIGRATION, due_on="2026-10-15"
    )

    assert task["is_blocking"] is True
    assert task["domain"] == "IT"
    a.assert_status(task, TASK_STATUS_OPEN)
    assert read_acquisition(api, acquisition["id"])["readiness_posture"] == POSTURE_AT_RISK
    a.assert_total_count(
        api.list_readiness_tasks(
            {"acquisition_id": acquisition["id"], "is_blocking": True}, INTEGRATION_MANAGER
        ),
        1,
    )


def test_the_consideration_fields_stay_null_until_the_board_prices_the_deal(api: ApiClient):
    """Computed money fields are null, not zero, before the transition that fills them.

    PRD: "Its five consideration fields — `purchase_price_cents`,
    `integration_reserve_cents`, `gross_consideration_cents`, `synergy_credit_bps`,
    `synergy_credit_cents`, and `net_consideration_cents` — are all null until the
    board reviews the deal, and `closed_at` and `abandoned_reason` are likewise
    null."

    Design: Corner/entities/acquisition_consideration_fields_are_null_until_board_review
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    fetched = validate_success(api.get_acquisition(acquisition["id"], DEAL_LEAD))

    a.assert_consideration_all_null(fetched)
    a.assert_fields_null(fetched, "tail_premium_cents")
    assert fetched["tail_coverage_required"] is False


def test_the_retention_fields_are_settled_the_moment_the_batch_is_staged(api: ApiClient):
    """Statutory retention and the conserved remainder are both creation-time work.

    PRD: "`legacy_purge_eligible_on` is then `last_encounter_on` plus
    `retention_years` calendar years, preserving month and day-of-month, with 29
    February mapping to 28 February in a non-leap target year."

    Design: Corner/entities/ehr_batch_retention_fields_computed_on_create
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    batch = create_batch(
        api,
        acquisition["id"],
        batch_label="CHARTS-A",
        record_count=BATCH_RECORD_COUNT,
        last_encounter_on=BATCH_LAST_ENCOUNTER_ON,
    )

    assert batch["retention_years"] == RETENTION_YEARS_DEFAULT
    assert batch["legacy_purge_eligible_on"] == BATCH_PURGE_ELIGIBLE_ON
    assert batch["validated_count"] == 0
    assert batch["defect_count"] == 0
    assert batch["unprocessed_count"] == BATCH_RECORD_COUNT
    assert batch["match_rate_bps"] == 0
    assert batch["retry_count"] == 0
    a.assert_status(batch, BATCH_STATUS_STAGED)


def test_a_performance_report_carries_no_version_and_no_updated_at(api: ApiClient):
    """The one entity outside the common property set, and it reads identically forever.

    PRD: "A performance report is append-only and immutable once written: it carries
    only `id` and `created_at`. It has no `updated_at` and no `version` field at all,
    and neither key appears in its representation."

    Design: Corner/entities/performance_report_is_immutable_and_carries_no_version_field
    """
    reset_clock(api)
    deal = closed_deal(api)
    a.assert_instant_equals(deal["acquisition"]["closed_at"], DEFAULT_CLOCK_INSTANT, "closed_at")
    set_clock(api, REPORTING_CLOCK_INSTANT)

    report = create_report(
        api,
        deal["acquisition"]["id"],
        deal["physician"]["id"],
        deal["plan"]["id"],
        period_start_on=REPORT_PERIOD_START,
        period_end_on=REPORT_PERIOD_END,
        actual_wrvu=REPORT_ACTUAL_WRVU,
        actual_collections_cents=REPORT_COLLECTIONS_CENTS,
    )

    a.assert_report_common_fields(report)
    assert "version" not in report
    assert "updated_at" not in report
    a.assert_money_equals(report["true_up_applied_cents"], TRUE_UP_CENTS, "true_up_applied_cents")
    a.assert_percentage_equals(
        report["benchmark_percentile_after"], PERCENTILE_AFTER, "benchmark_percentile_after"
    )

    reread = validate_success(api.get_performance_report(report["id"], INTEGRATION_MANAGER))
    assert reread == report


def test_an_unrecognised_specialty_is_refused_rather_than_stored(api: ApiClient):
    """Enumerations that key a lookup table are validated at the schema rank.

    PRD: "The creation payload names the target with `target_practice_name` and
    records the practice's dominant `specialty`, which must be one of
    `PRIMARY_CARE`, `CARDIOLOGY`, `ORTHOPEDICS`, or `ONCOLOGY` — this single choice
    later selects both the compensation survey benchmark table and the malpractice
    tail rate."

    Design: Corner/entities/acquisition_invalid_specialty_enum_rejected
    """
    reset_clock(api)

    for payload in (
        f.acquisition_payload(target_practice_name="Lakeside Dermatology", specialty="DERMATOLOGY"),
        f.acquisition_payload(annual_malpractice_premium_cents=-1),
        f.acquisition_payload(target_close_on="2026-13-01"),
        f.acquisition_payload(structure="JOINT_VENTURE"),
    ):
        validate_error(api.create_acquisition(payload, DEAL_LEAD), ApiErrorId.INVALID_REQUEST, 400)

    a.assert_total_count(api.list_acquisitions({}, DEAL_LEAD), 0)


def test_an_inverted_coverage_term_is_refused_before_the_overlap_check(api: ApiClient):
    """A term ending before it begins is a schema violation, not an overlap.

    PRD: "The term runs from `effective_on` through `terminates_on`, both calendar
    dates, with `terminates_on` on or after `effective_on`."

    Design: Corner/entities/payer_contract_terminates_before_effective_rejected
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    rejected = api.create_payer_contract(
        f.payer_contract_payload(
            acquisition["id"], effective_on="2027-10-31", terminates_on="2026-11-01"
        ),
        INTEGRATION_MANAGER,
    )

    validate_error(rejected, ApiErrorId.INVALID_REQUEST, 400)
    a.assert_total_count(
        api.list_payer_contracts({"acquisition_id": acquisition["id"]}, INTEGRATION_MANAGER), 0
    )


def test_naming_an_unstored_parent_in_the_body_is_a_404(api: ApiClient):
    """The flat topology validates the foreign key in the body, not in the path.

    PRD: "The payload carries the `acquisition_id` of the deal being joined, the
    provider's `npi`, their `full_name`, their own `specialty` from the same
    four-value enumeration, and their `state_license_expires_on`."

    Design: Corner/entities/physician_with_unknown_acquisition_id_returns_not_found
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    validate_error(
        api.create_physician(f.physician_payload(NON_EXISTENT_UUID), DEAL_LEAD),
        ApiErrorId.RESOURCE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_readiness_task(f.readiness_task_payload(NON_EXISTENT_UUID), INTEGRATION_MANAGER),
        ApiErrorId.RESOURCE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_liability_item(f.liability_item_payload(NON_EXISTENT_UUID), DEAL_LEAD),
        ApiErrorId.RESOURCE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_ehr_migration_batch(
            f.ehr_migration_batch_payload(NON_EXISTENT_UUID), INTEGRATION_MANAGER
        ),
        ApiErrorId.RESOURCE_NOT_FOUND,
        404,
    )

    a.assert_total_count(
        api.list_physicians({"acquisition_id": acquisition["id"]}, DEAL_LEAD), 0
    )


def test_a_drafted_offer_already_carries_every_derived_wage_figure(api: ApiClient):
    """The wage arithmetic runs at creation while the pool stays untouched.

    PRD: "A drafted offer lands in `DRAFT`, with `extended_on` and `accepted_on`
    both null, and the retention pool is untouched — a draft reserves nothing."

    Design: Corner/entities/staff_offer_computed_wage_fields_present_on_create
    """
    reset_clock(api)
    acquisition = create_acquisition(api)

    offer = create_offer(
        api,
        acquisition["id"],
        staff_member_name="Ruth Alvarez",
        role_code=ROLE_CODE_MA,
        legacy_annual_wage_cents=3_600_000,
        legacy_pto_hours=40,
        credited_service_months=30,
        offer_expires_on="2026-09-15",
    )

    a.assert_money_equals(
        offer["uplift_component_cents"], MA_UPLIFT_CENTS, "uplift_component_cents"
    )
    a.assert_money_equals(offer["pto_component_cents"], MA_PTO_CENTS, "pto_component_cents")
    assert offer["wage_floor_applied"] is True
    a.assert_money_equals(
        offer["offered_annual_wage_cents"], MA_FLOOR_CENTS, "offered_annual_wage_cents"
    )
    a.assert_money_equals(offer["retention_bonus_cents"], MA_BONUS_CENTS, "retention_bonus_cents")
    a.assert_status(offer, OFFER_STATUS_DRAFT)
    a.assert_fields_null(offer, "extended_on", "accepted_on")

    ledger = read_acquisition(api, acquisition["id"])
    a.assert_retention_pool(ledger, POOL_TOTAL_CENTS, 0, POOL_TOTAL_CENTS)
    a.assert_percentage_equals(
        ledger["hr_staffing_coverage_pct"], ZERO_COVERAGE_PCT, "hr_staffing_coverage_pct"
    )


def test_the_liability_filter_and_the_escrow_ledger_agree_on_one_row_set(api: ApiClient):
    """Filtering by disposition selects exactly the rows the escrow aggregate sums.

    PRD: "`UNASSIGNED → ESCROWED` and `ASSUMED → ESCROWED` behave identically to one
    another: each requires that `estimated_amount_cents` does not exceed the
    acquisition's `escrow_available_cents`, failing with `ERR_ESCROW_INSUFFICIENT`
    otherwise, and each sets the item's `escrowed_amount_cents` to
    `estimated_amount_cents`, adds that amount to `escrow_committed_cents`, and
    subtracts it from `escrow_available_cents`."

    Design: Corner/entities/liability_item_listing_filters_by_disposition
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    lease = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_EQUIPMENT_LEASE,
        description="Two imaging leases running to 2029.",
        estimated_amount_cents=LEASE_EXPOSURE_CENTS,
    )
    pto = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_UNPAID_PTO,
        description="Accrued but untaken staff PTO at close.",
        estimated_amount_cents=PTO_EXPOSURE_CENTS,
    )
    set_disposition(api, lease["id"], DISPOSITION_ESCROWED)

    response = api.list_liability_items(
        {"acquisition_id": acquisition["id"], "disposition": DISPOSITION_ESCROWED},
        COMPLIANCE_OFFICER,
    )

    rows, meta = validate_paginated(response)
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    a.assert_contains_id(rows, lease["id"])
    a.assert_money_equals(
        rows[0]["escrowed_amount_cents"], LEASE_EXPOSURE_CENTS, "escrowed_amount_cents"
    )

    untouched = validate_success(api.get_liability_item(pto["id"], COMPLIANCE_OFFICER))
    assert untouched["disposition"] == DISPOSITION_UNASSIGNED
    a.assert_money_equals(untouched["escrowed_amount_cents"], 0, "escrowed_amount_cents")

    ledger = read_acquisition(api, acquisition["id"])
    a.assert_escrow(
        ledger, ESCROW_TOTAL_CENTS, LEASE_EXPOSURE_CENTS, ESCROW_AVAILABLE_AFTER_LEASE_CENTS
    )
    a.assert_total_count(
        api.list_liability_items({"acquisition_id": acquisition["id"]}, COMPLIANCE_OFFICER), 2
    )
