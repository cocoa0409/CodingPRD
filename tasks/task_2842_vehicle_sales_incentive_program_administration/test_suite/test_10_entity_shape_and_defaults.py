"""Entity shape, server-minted identity, declared defaults and computed fields.

Every test in this module starts against an empty database and a logical clock
sitting at its startup default, and builds each precondition from scratch.
"""
import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, make_dealer_headers
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import AUG_01, DEFAULT_LIMIT, DEFAULT_OFFSET

# A syntactically valid UUID that matches no persisted row.
UNKNOWN_PROGRAM_ID = "11111111-2222-4333-8444-555555555555"
UNKNOWN_DEALER_ID = "99999999-8888-4777-8666-555555555555"


def test_dealer_creation_returns_envelope_with_server_minted_identity_and_defaults():
    """Registering a dealer answers 201 with the standard envelope, a bare UUID
    id, version 1 and both money counters at their declared defaults.

    PRD: "A newly registered dealer has `status` `ACTIVE`, `paid_cents` of 0 and
    `open_chargeback_cents` of 0."
    PRD: "Every persisted resource carries an `id` that is a server-minted UUID.
    Identifiers carry no type prefix and no embedded semantics; a program id and
    a claim id are distinguishable only by which collection they belong to."
    PRD: "Most resources additionally carry `updated_at`, refreshed to the
    current logical clock reading on every mutation, and `version`, an integer
    that starts at 1 when the resource is created and increments by exactly 1 on
    every mutation of that resource."

    Design: Corner/entities/dealer_creation_returns_envelope_with_server_minted_identity_and_defaults
    """
    fx.set_clock(AUG_01)

    payload = {
        "dealer_code": "CRN-D-001",
        "name": "Cornerstone Auto",
        "region_code": "WEST",
        "historical_volume_units": 10,
        "market_opportunity_bps": 1500,
    }
    response = api_client.create_dealer(payload, fx.CONTROLLER)

    body = response.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}, (
        f"the success envelope carries exactly meta, response_type and data: {sorted(body)}"
    )
    assert body["response_type"] == "object", body["response_type"]
    assert body["meta"].get("api_request_id", "").startswith("req_"), body["meta"]
    assert is_iso8601_timestamp(body["meta"].get("api_request_timestamp", "")), body["meta"]

    dealer = validate_success(response, 201)
    a.assert_dealer_shape(dealer)

    # A bare 36-character UUID with no type prefix such as 'dlr_'.
    assert is_valid_uuid(dealer["id"]), dealer["id"]
    assert len(dealer["id"]) == 36, dealer["id"]
    assert "_" not in dealer["id"], f"id carries a type prefix: {dealer['id']!r}"

    a.assert_version(dealer, 1)
    assert dealer["created_at"] == "2026-08-01T00:00:00.000Z", dealer["created_at"]
    assert dealer["updated_at"] == "2026-08-01T00:00:00.000Z", dealer["updated_at"]

    a.assert_status(dealer, "ACTIVE")
    a.assert_dealer_money(dealer, paid_cents=0, open_chargeback_cents=0)

    assert dealer["dealer_code"] == "CRN-D-001"
    assert dealer["name"] == "Cornerstone Auto"
    assert dealer["region_code"] == "WEST"
    a.assert_int_field(dealer, "historical_volume_units", 10)
    a.assert_bps(dealer, "market_opportunity_bps", 1500)


def test_program_retrieval_returns_every_stored_and_computed_field():
    """Reading back a freshly created CUSTOMER_CASH program returns DRAFT,
    version 1, the type-conditional levers at 0 and every ledger field at 0.

    PRD: "On creation the program's `status` is `DRAFT`, its `version` is 1, and
    every derived money and unit field is initialized to 0: `committed_cents`,
    `paid_cents`, `accrued_budget_cents`, `claimed_units`, `per_unit_spend_cents`
    and `residual_impact_bps`."
    PRD: "Three levers are consulted only by particular incentive types, and each
    defaults to 0 when the designer omits it."
    PRD: "The audit fields `submitted_by_user_id` and `approved_by_user_id` both
    begin as null."
    PRD: "`stack_cap_cents` defaults to 0 and expresses a program-level ceiling,
    in cents, on the total stacked incentive of any single delivery that consumes
    this program, where the value 0 means this program imposes no ceiling of its
    own. And `supersedes_program_id` may name an earlier program this one
    replaces; it defaults to null, and when it is supplied the referenced program
    must exist."

    Design: Corner/entities/program_retrieval_returns_every_stored_and_computed_field
    """
    fx.set_clock(AUG_01)

    created = fx.create_draft_program(
        {
            "program_code": "CRN-P-001",
            "name": "Corner Retrieval Cash",
            "incentive_type": "CUSTOMER_CASH",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 111000,
            "budget_cents": 12000000,
            "stack_group": "CRN",
            "priority_rank": 201,
            "accrual_method": "UNIT_BASED",
        }
    )

    program = validate_success(api_client.get_program(created["id"], fx.DESIGNER))
    a.assert_program_shape(program)

    assert program["program_code"] == "CRN-P-001"
    a.assert_status(program, "DRAFT")
    a.assert_money(program, "per_unit_amount_cents", 111000)
    a.assert_version(program, 1)

    # The type-conditional levers default rather than erroring on CUSTOMER_CASH.
    a.assert_bps(program, "apr_buydown_bps", 0)
    a.assert_bps(program, "residual_support_bps", 0)
    a.assert_money(program, "stack_cap_cents", 0)

    a.assert_money(program, "committed_cents", 0)
    a.assert_money(program, "paid_cents", 0)
    a.assert_money(program, "accrued_budget_cents", 0)
    a.assert_int_field(program, "claimed_units", 0)
    a.assert_money(program, "per_unit_spend_cents", 0)
    a.assert_bps(program, "residual_impact_bps", 0)

    a.assert_null_fields(
        program,
        ["submitted_by_user_id", "approved_by_user_id", "supersedes_program_id"],
    )


def test_program_listing_paginates_and_filters_by_status_and_incentive_type():
    """limit/offset advance the window over three programs while total_count
    tracks the filtered population for the status and incentive_type filters.

    PRD: "For list responses the `meta` object carries `limit` and `offset` as
    they were resolved for the request, `total_count` as the number of records
    matching the filters before pagination is applied, and `has_more` as a
    boolean that is true when records remain beyond the current page."
    PRD: "`limit` controls the page size: it defaults to 10 when omitted, its
    minimum accepted value is 1 and its maximum accepted value is 100. `offset`
    controls how many records are skipped before the page begins: it defaults to
    0 and its minimum accepted value is 0."
    PRD: "Programs themselves can be listed with filters on `status`, on
    `incentive_type` and on `supersedes_program_id`, which is how a controller
    finds the successor chain behind a superseded program."

    Design: Corner/entities/program_listing_paginates_and_filters_by_status_and_incentive_type
    """
    fx.set_clock(AUG_01)

    p1 = fx.create_draft_program(
        {
            "program_code": "CRN-L-1",
            "name": "List One",
            "incentive_type": "CUSTOMER_CASH",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 100000,
            "budget_cents": 12000000,
            "stack_group": "CRNL",
            "priority_rank": 211,
            "accrual_method": "UNIT_BASED",
        }
    )
    fx.add_eligibility_rule(
        p1["id"],
        model_code="MX5",
        region_code="WEST",
        build_date_from="2026-05-01T00:00:00.000Z",
        build_date_to="2026-07-31T00:00:00.000Z",
        allowed_deal_types=["CASH"],
    )
    fx.submit_program(p1["id"])

    fx.create_draft_program(
        {
            "program_code": "CRN-L-2",
            "name": "List Two",
            "incentive_type": "CUSTOMER_CASH",
            "effective_from": "2026-09-01T00:00:00.000Z",
            "effective_to": "2026-10-01T00:00:00.000Z",
            "per_unit_amount_cents": 100000,
            "budget_cents": 12000000,
            "stack_group": "CRNL",
            "priority_rank": 212,
            "accrual_method": "UNIT_BASED",
        }
    )
    fx.create_draft_program(
        {
            "program_code": "CRN-L-3",
            "name": "List Three",
            "incentive_type": "LEASE_SUPPORT",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 100000,
            "residual_support_bps": 300,
            "budget_cents": 12000000,
            "stack_group": "CRNL",
            "priority_rank": 213,
            "accrual_method": "UNIT_BASED",
        }
    )

    page1_response = api_client.list_programs(fx.DESIGNER, params={"limit": 2, "offset": 0})
    assert page1_response.json()["response_type"] == "array"
    page1, meta1 = validate_paginated(page1_response)
    assert meta1["total_count"] == 3, meta1
    assert meta1["has_more"] is True, meta1
    assert meta1["limit"] == 2 and meta1["offset"] == 0, meta1
    a.assert_list_length(page1, 2, "page-1 programs")

    page2, meta2 = validate_paginated(
        api_client.list_programs(fx.DESIGNER, params={"limit": 2, "offset": 2})
    )
    assert meta2["total_count"] == 3, meta2
    assert meta2["has_more"] is False, meta2
    a.assert_list_length(page2, 1, "page-2 programs")

    # The offset advances the window rather than repeating it.
    assert page1[0]["program_code"] != page2[0]["program_code"], (
        f"offset 2 repeated the first row: {page1[0]['program_code']}"
    )

    lease_rows, lease_meta = validate_paginated(
        api_client.list_programs(fx.DESIGNER, params={"incentive_type": "LEASE_SUPPORT"})
    )
    assert lease_meta["total_count"] == 1, lease_meta
    a.assert_list_length(lease_rows, 1, "LEASE_SUPPORT programs")
    assert lease_rows[0]["program_code"] == "CRN-L-3", lease_rows[0]

    pending_rows, pending_meta = validate_paginated(
        api_client.list_programs(fx.DESIGNER, params={"status": "PENDING_APPROVAL"})
    )
    assert pending_meta["total_count"] == 1, pending_meta
    a.assert_list_length(pending_rows, 1, "PENDING_APPROVAL programs")
    assert pending_rows[0]["program_code"] == "CRN-L-1", pending_rows[0]

    # Omitting limit and offset entirely falls back to the declared defaults.
    default_rows, default_meta = validate_paginated(api_client.list_programs(fx.DESIGNER))
    assert default_meta["limit"] == DEFAULT_LIMIT, default_meta
    assert default_meta["offset"] == DEFAULT_OFFSET, default_meta
    assert default_meta["total_count"] == 3, default_meta
    assert len(default_rows) <= DEFAULT_LIMIT, len(default_rows)
    a.assert_list_length(default_rows, 3, "unpaginated programs")


def test_unknown_program_id_returns_program_not_found():
    """A well-formed UUID matching no program answers 404 ERR_PROGRAM_NOT_FOUND
    through the error envelope, on the program read and on its sub-resource list.

    PRD: "**Path existence** — every resource named in the URL path exists,
    resolved strictly left to right: the program before its eligibility rule, the
    objective before its protest, the batch before the claims it is asked to
    schedule."
    PRD: "A missing resource yields the not-found code of the segment that failed
    — `ERR_PROGRAM_NOT_FOUND`, `ERR_OBJECTIVE_NOT_FOUND`, `ERR_PROTEST_NOT_FOUND`,
    `ERR_DEALER_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND` or `ERR_BATCH_NOT_FOUND` — all HTTP 404."
    PRD: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."

    Design: Corner/entities/unknown_program_id_returns_program_not_found
    """
    fx.set_clock(AUG_01)

    response = api_client.get_program(UNKNOWN_PROGRAM_ID, fx.DESIGNER)
    error = validate_error(response, "ERR_PROGRAM_NOT_FOUND")
    assert error["message"].strip(), error

    body = response.json()
    assert body["response_type"] == "error", body["response_type"]
    # The error payload holds only error_id and message: no partial program.
    assert set(body["data"].keys()) == {"error_id", "message"}, sorted(body["data"])
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        sorted(body["meta"])
    )

    # The sub-resource list on the same unknown id is a 404 too, not an empty page.
    sub_response = api_client.list_eligibility_rules(UNKNOWN_PROGRAM_ID, fx.DESIGNER)
    validate_error(sub_response, "ERR_PROGRAM_NOT_FOUND")


def test_delivery_create_missing_required_vin_returns_400():
    """Omitting vin is a payload-shape breach: 400 ERR_INVALID_REQUEST, nothing
    persisted, and the very same payload carrying a vin is accepted.

    PRD: "Each delivery carries a `vin` of exactly 17 characters that is globally
    unique across every retail delivery ever recorded — including deliveries that
    were later rejected and deliveries that were later unwound, so a dealer cannot
    recycle a VIN after a deal falls apart."
    PRD: "**Payload shape** — on every creating or acting endpoint: all required
    fields present, every enum value a declared member, every integer inside its
    declared range, every instant a parseable ISO 8601 UTC value with three
    fractional digits, `effective_to` strictly greater than `effective_from`,
    `build_date_to` greater than or equal to `build_date_from`, `period_end`
    greater than or equal to `period_start`, `scheduled_pay_date` greater than or
    equal to `period_end`, `cap_amount_cents` non-null exactly when `mode` is
    `CAPPED_TOTAL` and null in every other mode, and `tier_schedule` strictly
    ascending in both `tier_index` and `threshold_bps`. Any breach yields
    `ERR_INVALID_REQUEST` (400)."
    PRD: "Checks are evaluated in the following order, and the first failure
    short-circuits the request; no side effect of any kind is applied to any
    entity once a check fails."

    Design: Corner/entities/delivery_create_missing_required_vin_returns_400
    """
    fx.set_clock("2026-08-10T00:00:00.000Z")

    dealer = fx.register_dealer(
        dealer_code="CRN-D-002",
        name="Required Fields Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    dealer_headers = make_dealer_headers(dealer["id"])

    without_vin = {
        "dealer_id": dealer["id"],
        "model_code": "MX5",
        "trim_code": "BASE",
        "build_date": "2026-06-01T00:00:00.000Z",
        "msrp_cents": 3100000,
        "sale_date": "2026-08-09T00:00:00.000Z",
        "customer_region_code": "WEST",
        "deal_type": "CASH",
    }
    validate_error(
        api_client.create_delivery(without_vin, dealer_headers), "ERR_INVALID_REQUEST"
    )

    # The refused create persisted nothing.
    rows, meta = validate_paginated(
        api_client.list_deliveries(fx.VALIDATOR, params={"dealer_id": dealer["id"]})
    )
    a.assert_list_length(rows, 0, "deliveries of this dealer")
    assert meta["total_count"] == 0, meta

    # vin was the only missing element: the same call with one succeeds.
    with_vin = dict(without_vin, vin=f.unique_vin())
    delivery = validate_success(
        api_client.create_delivery(with_vin, dealer_headers), 201
    )
    a.assert_delivery_shape(delivery)
    assert len(delivery["vin"]) == 17, delivery["vin"]


def test_eligibility_rule_defaults_apply_when_optional_inputs_are_omitted():
    """A footprint row created from the four required inputs materialises four
    different default shapes and takes its program_id from the path.

    PRD: "`trim_code` is optional and defaults to null, and a null trim admits
    every trim of that model."
    PRD: "`min_msrp_cents` defaults to 0 and is an inclusive sticker-price floor
    in cents where 0 means no floor; `max_msrp_cents` defaults to null and is an
    inclusive ceiling where null means no ceiling."
    PRD: "`allowed_deal_types` is an array of members drawn from `CASH`,
    `FINANCE` and `LEASE` and defaults to all three."
    PRD: "Each row is append-only configuration owned by the program named in the
    path, which is what the row's `program_id` records, and it describes one
    admissible slice of the automaker's line-up."

    Design: Corner/entities/eligibility_rule_defaults_apply_when_optional_inputs_are_omitted
    """
    fx.set_clock(AUG_01)

    program = fx.create_draft_program(
        {
            "program_code": "CRN-P-DEF",
            "name": "Defaults Program",
            "incentive_type": "CUSTOMER_CASH",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 90000,
            "budget_cents": 12000000,
            "stack_group": "CRND",
            "priority_rank": 221,
            "accrual_method": "UNIT_BASED",
        }
    )

    rule = validate_success(
        api_client.create_eligibility_rule(
            program["id"],
            {
                "model_code": "MX5",
                "region_code": "WEST",
                "build_date_from": "2026-05-01T00:00:00.000Z",
                "build_date_to": "2026-07-31T00:00:00.000Z",
            },
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_eligibility_rule_shape(rule)

    a.assert_null_fields(rule, ["trim_code", "max_msrp_cents"])
    a.assert_money(rule, "min_msrp_cents", 0)
    assert sorted(rule["allowed_deal_types"]) == ["CASH", "FINANCE", "LEASE"], (
        rule["allowed_deal_types"]
    )

    # program_id comes from the path, never from the body.
    assert rule["program_id"] == program["id"], rule["program_id"]


def test_delivery_computed_and_system_fields_input_ignored():
    """A create payload smuggling status, reported_at, reporting_lag_days and
    back_dated_flag is answered with the recomputed and system-stamped values.

    PRD: "At the moment the delivery is recorded, the server stamps `reported_at`
    from the logical clock — never from real wall-clock time — sets `status` to
    `REPORTED`, and runs the **back-dated sale detector** immediately."
    PRD: "`reporting_lag_days` is the whole number of days between the sale and
    the report: the elapsed seconds from `sale_date` to `reported_at` divided by
    86400 seconds and floored toward negative infinity."
    PRD: "`back_dated_flag` is set to true when either of two conditions holds:
    `reporting_lag_days` is **strictly greater** than ten days, or `sale_date` is
    strictly later than `reported_at`."

    Design: Corner/entities/delivery_computed_and_system_fields_input_ignored
    """
    fx.set_clock("2026-08-25T00:00:00.000Z")

    dealer = fx.register_dealer(
        dealer_code="CRN-D-003",
        name="Computed Fields Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )

    payload = {
        "dealer_id": dealer["id"],
        "vin": f.unique_vin(),
        "model_code": "MX5",
        "trim_code": "BASE",
        "build_date": "2026-06-01T00:00:00.000Z",
        "msrp_cents": 3100000,
        "sale_date": "2026-08-01T00:00:00.000Z",
        "customer_region_code": "WEST",
        "deal_type": "CASH",
        # Server-owned fields the dealer is not the author of.
        "status": "VALIDATED",
        "reported_at": "2026-08-02T00:00:00.000Z",
        "reporting_lag_days": 0,
        "back_dated_flag": False,
    }
    delivery = validate_success(
        api_client.create_delivery(payload, make_dealer_headers(dealer["id"])), 201
    )
    a.assert_delivery_shape(delivery)

    # Only POST /incentives/deliveries/{id}/validate can move the status.
    a.assert_status(delivery, "REPORTED")
    assert delivery["reported_at"] == "2026-08-25T00:00:00.000Z", delivery["reported_at"]
    a.assert_int_field(delivery, "reporting_lag_days", 24)
    assert delivery["back_dated_flag"] is True, delivery["back_dated_flag"]

    a.assert_null_fields(delivery, ["validated_by_user_id", "unwound_at"])
    a.assert_version(delivery, 1)

    # No echo of the smuggled instant survives anywhere in the response.
    assert "2026-08-02T00:00:00.000Z" not in [
        value for value in delivery.values() if isinstance(value, str)
    ], delivery


def test_claim_system_fields_start_at_their_declared_defaults():
    """A freshly submitted claim carries the two starting state dimensions, the
    derived claim_type, the frozen per-unit snapshot and the copied dealer_id.

    PRD: "The claim's two independent state dimensions begin at
    `validation_status` `SUBMITTED` and `payment_status` `UNPAID`, its
    `payment_batch_id` is null, its `rejection_error_id`,
    `adjudicated_by_user_id` and `paid_at` are all null, and the claimed
    program's `version` increments by 1."
    PRD: "`snapshot_per_unit_cents` freezes the program's `per_unit_amount_cents`
    exactly as it stands at submission, which is what protects an
    already-submitted claim from a later prospective repricing."
    PRD: "`claim_type` is derived from the program's `incentive_type`: it is
    `UNIT_INCENTIVE` when the program's type is `CUSTOMER_CASH`,
    `FINANCE_SUBVENTION` or `LEASE_SUPPORT`, and `STAIR_STEP_BONUS` when the type
    is `DEALER_STAIR_STEP`."
    PRD: "`dealer_id` is copied from the delivery at creation and is never
    re-derived afterwards, even if the delivery is later touched."

    Design: Corner/entities/claim_system_fields_start_at_their_declared_defaults
    """
    fx.set_clock(AUG_01)

    dealer = fx.register_dealer(
        dealer_code="CRN-D-004",
        name="System Fields Motors",
        region_code="WEST",
        historical_volume_units=4,
        market_opportunity_bps=0,
    )
    program = fx.create_active_program(
        payload={
            "program_code": "CRN-P-SYS",
            "name": "System Fields Cash",
            "incentive_type": "CUSTOMER_CASH",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 118000,
            "budget_cents": 12000000,
            "stack_group": "CRNS",
            "priority_rank": 231,
            "accrual_method": "UNIT_BASED",
        }
    )

    fx.set_clock("2026-08-08T00:00:00.000Z")
    delivery = fx.report_delivery(
        dealer["id"],
        sale_date="2026-08-07T00:00:00.000Z",
        msrp_cents=3100000,
    )
    fx.validate_delivery(delivery["id"])

    claim = validate_success(
        api_client.create_claim(
            f.create_claim_payload(
                delivery["id"],
                program["id"],
                999999,
                fx.program_version(program["id"]),
            ),
            make_dealer_headers(dealer["id"]),
        ),
        201,
    )
    a.assert_claim_shape(claim)

    # The two independent dimensions both start at their declared defaults.
    a.assert_claim_dimensions(claim, "SUBMITTED", "UNPAID")
    assert claim["claim_type"] == "UNIT_INCENTIVE", claim["claim_type"]
    a.assert_money(claim, "snapshot_per_unit_cents", 118000)

    # The dealer's ask is recorded verbatim.
    a.assert_money(claim, "claimed_amount_cents", 999999)

    a.assert_null_fields(
        claim,
        ["payment_batch_id", "adjudicated_by_user_id", "rejection_error_id", "paid_at"],
    )
    a.assert_version(claim, 1)

    assert claim["dealer_id"] == dealer["id"], claim["dealer_id"]
    assert claim["delivery_id"] == delivery["id"], claim["delivery_id"]
    assert claim["program_id"] == program["id"], claim["program_id"]


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param(
            {
                "program_code": "CRN-P-BAD1",
                "name": "Bad Enum",
                "incentive_type": "TRADE_IN_BONUS",
            },
            id="out_of_enum_incentive_type",
        ),
        pytest.param(
            {
                "program_code": "CRN-P-BAD2",
                "name": "Bad Amount",
                "per_unit_amount_cents": -1,
            },
            id="negative_per_unit_amount_cents",
        ),
        pytest.param(
            {
                "program_code": "CRN-P-BAD3",
                "name": "Bad Type",
                "budget_cents": "twelve million",
            },
            id="non_integer_budget_cents",
        ),
    ],
)
def test_program_invalid_incentive_type_enum_returns_400(overrides):
    """An out-of-enum incentive_type, a negative per-unit amount and a
    non-integer budget all collapse to ERR_INVALID_REQUEST with nothing written.

    PRD: "The creation payload names the program with a `program_code` of 1 to 32
    characters and a human-readable `name`, and it declares exactly one
    `incentive_type` chosen from `CUSTOMER_CASH`, `FINANCE_SUBVENTION`,
    `LEASE_SUPPORT` and `DEALER_STAIR_STEP` — the lever this program pulls."
    PRD: "`per_unit_amount_cents` carries the cash value in cents the program
    pays for each eligible retail delivery, and must be zero or greater; for a
    stair-step program the same field is the base per-unit bonus that sits
    underneath the tier schedule."
    PRD: "**Payload shape** — on every creating or acting endpoint: all required
    fields present, every enum value a declared member, every integer inside its
    declared range, every instant a parseable ISO 8601 UTC value with three
    fractional digits, `effective_to` strictly greater than `effective_from`,
    `build_date_to` greater than or equal to `build_date_from`, `period_end`
    greater than or equal to `period_start`, `scheduled_pay_date` greater than or
    equal to `period_end`, `cap_amount_cents` non-null exactly when `mode` is
    `CAPPED_TOTAL` and null in every other mode, and `tier_schedule` strictly
    ascending in both `tier_index` and `threshold_bps`. Any breach yields
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/program_invalid_incentive_type_enum_returns_400
    """
    fx.set_clock(AUG_01)

    payload = {
        "program_code": "CRN-P-BAD",
        "name": "Bad Program",
        "incentive_type": "CUSTOMER_CASH",
        "effective_from": "2026-08-01T00:00:00.000Z",
        "effective_to": "2026-09-01T00:00:00.000Z",
        "per_unit_amount_cents": 100000,
        "budget_cents": 12000000,
        "stack_group": "CRNB",
        "priority_rank": 241,
    }
    payload.update(overrides)

    validate_error(
        api_client.create_program(payload, fx.DESIGNER), "ERR_INVALID_REQUEST"
    )

    # The refused create consumed no program_code.
    rows, meta = validate_paginated(api_client.list_programs(fx.DESIGNER))
    assert meta["total_count"] == 0, meta
    a.assert_list_length(rows, 0, "programs")


def test_eligibility_rule_is_immutable_with_no_version_and_no_mutating_endpoint():
    """A footprint row and a stacking edge answer with id and created_at only —
    no version, no updated_at — and stay readable through the parent's listing.

    PRD: "An eligibility footprint row and a stackability edge are append-only
    configuration: they are written once while their program is still a draft and
    are never mutated afterwards."
    PRD: "Both therefore carry only `id` and `created_at` — they have no
    `updated_at` field and no `version` field at all."
    PRD: "`cap_amount_cents` carries the combined ceiling in cents for the pair
    and is required exactly when `mode` is `CAPPED_TOTAL`; in the other two modes
    it must be null."

    Design: Corner/entities/eligibility_rule_is_immutable_with_no_version_and_no_mutating_endpoint
    """
    fx.set_clock(AUG_01)

    p1 = fx.create_draft_program(
        {
            "program_code": "CRN-P-IMM1",
            "name": "Immutable One",
            "incentive_type": "CUSTOMER_CASH",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 100000,
            "budget_cents": 12000000,
            "stack_group": "CRNI",
            "priority_rank": 251,
            "accrual_method": "UNIT_BASED",
        }
    )
    p2 = fx.create_draft_program(
        {
            "program_code": "CRN-P-IMM2",
            "name": "Immutable Two",
            "incentive_type": "LEASE_SUPPORT",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 100000,
            "residual_support_bps": 250,
            "budget_cents": 12000000,
            "stack_group": "CRNI",
            "priority_rank": 252,
            "accrual_method": "UNIT_BASED",
        }
    )

    rule = validate_success(
        api_client.create_eligibility_rule(
            p1["id"],
            {
                "model_code": "MX5",
                "region_code": "WEST",
                "build_date_from": "2026-05-01T00:00:00.000Z",
                "build_date_to": "2026-07-31T00:00:00.000Z",
                "allowed_deal_types": ["CASH"],
            },
            fx.DESIGNER,
        ),
        201,
    )
    edge = validate_success(
        api_client.create_stackability_constraint(
            p1["id"], {"program_b_id": p2["id"], "mode": "ALLOWED"}, fx.DESIGNER
        ),
        201,
    )

    # Neither configuration child carries a version key nor an updated_at key.
    a.assert_eligibility_rule_shape(rule)
    a.assert_stack_constraint_shape(edge)
    assert is_valid_uuid(rule["id"]) and len(rule["id"]) == 36, rule["id"]
    assert is_valid_uuid(edge["id"]) and len(edge["id"]) == 36, edge["id"]
    assert rule["created_at"] == "2026-08-01T00:00:00.000Z", rule["created_at"]
    assert edge["created_at"] == "2026-08-01T00:00:00.000Z", edge["created_at"]
    a.assert_null_fields(edge, ["cap_amount_cents"])

    # The immutable row is still readable through its parent's sub-resource list.
    listed, meta = validate_paginated(
        api_client.list_eligibility_rules(p1["id"], fx.DESIGNER)
    )
    a.assert_list_length(listed, 1, "eligibility rules of the program")
    assert listed[0]["id"] == rule["id"], listed[0]
    assert meta["total_count"] == 1, meta


def test_objective_create_with_unknown_dealer_returns_not_found():
    """The objective's body foreign key is resolved after the path parent, so a
    dangling dealer_id under a live ACTIVE program is 404 ERR_DEALER_NOT_FOUND.

    PRD: "**Body foreign keys** — every foreign key carried in the request body
    resolves to an existing row: the `delivery_id` and `program_id` of a claim,
    the `dealer_id` of an objective, the `program_b_id` of a stackability edge,
    every id inside `claim_ids`, and a program's `supersedes_program_id`. A
    dangling reference yields the matching 404 code (`ERR_DELIVERY_NOT_FOUND`,
    `ERR_PROGRAM_NOT_FOUND`, `ERR_DEALER_NOT_FOUND` or `ERR_CLAIM_NOT_FOUND`)."
    PRD: "The payload carries the `dealer_id` of the dealer the objective binds,
    plus an optional `stretch_bps` — an extra stretch in basis points laid on top
    of the dealer's market opportunity, capped at 10000 basis points and
    defaulting to 0."

    Design: Corner/entities/objective_create_with_unknown_dealer_returns_not_found
    """
    fx.set_clock(AUG_01)

    program = fx.create_active_program(
        payload={
            "program_code": "CRN-P-FK",
            "name": "FK Parent Stair",
            "incentive_type": "DEALER_STAIR_STEP",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 0,
            "budget_cents": 12000000,
            "stack_group": "CRNF",
            "priority_rank": 261,
            "tier_schedule": [
                {"tier_index": 1, "threshold_bps": 8000, "per_unit_bonus_cents": 40000}
            ],
            "tier_bonus_mode": "MARGINAL",
        },
        rules=[
            {
                "model_code": "TRK9",
                "region_code": "NORTH",
                "build_date_from": "2026-05-01T00:00:00.000Z",
                "build_date_to": "2026-07-31T00:00:00.000Z",
                "allowed_deal_types": ["CASH"],
            }
        ],
    )
    a.assert_status(program, "ACTIVE")

    # A well-formed UUID that resolves to nothing is a 404, not a 400.
    validate_error(
        api_client.create_objective(
            program["id"],
            {"dealer_id": UNKNOWN_DEALER_ID, "stretch_bps": 0},
            fx.FSM,
        ),
        "ERR_DEALER_NOT_FOUND",
    )

    # The orphan child was never created.
    rows, meta = validate_paginated(
        api_client.list_program_objectives(program["id"], fx.FSM)
    )
    a.assert_list_length(rows, 0, "objectives of the program")
    assert meta["total_count"] == 0, meta


def test_stackability_edge_is_undirected_and_visible_from_both_programs():
    """One CAPPED_TOTAL edge created from A is the single row listed by both A and
    B, and both the reverse duplicate and the self-edge are refused.

    PRD: "The edge is undirected — at most one row may ever join a given
    unordered pair, and the listing of a program's edges returns every edge
    touching it in either direction."
    PRD: "Declaring an edge whose `program_b_id` equals the path program, or
    declaring a second edge over a pair that an edge already joins, is refused
    with `ERR_INVALID_STACK_EDGE`."
    PRD: "A designer declares an edge between the program named in the path,
    recorded on the edge as `program_a_id`, and another program named in the
    payload as `program_b_id`."

    Design: Corner/entities/stackability_edge_is_undirected_and_visible_from_both_programs
    """
    fx.set_clock(AUG_01)

    g1 = fx.create_draft_program(
        {
            "program_code": "CRN-G-1",
            "name": "Graph One",
            "incentive_type": "CUSTOMER_CASH",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 100000,
            "budget_cents": 12000000,
            "stack_group": "CRNG",
            "priority_rank": 271,
            "accrual_method": "UNIT_BASED",
        }
    )
    g2 = fx.create_draft_program(
        {
            "program_code": "CRN-G-2",
            "name": "Graph Two",
            "incentive_type": "FINANCE_SUBVENTION",
            "effective_from": "2026-08-01T00:00:00.000Z",
            "effective_to": "2026-09-01T00:00:00.000Z",
            "per_unit_amount_cents": 0,
            "apr_buydown_bps": 250,
            "budget_cents": 12000000,
            "stack_group": "CRNG",
            "priority_rank": 272,
            "accrual_method": "UNIT_BASED",
        }
    )

    edge = validate_success(
        api_client.create_stackability_constraint(
            g1["id"],
            {"program_b_id": g2["id"], "mode": "CAPPED_TOTAL", "cap_amount_cents": 500000},
            fx.DESIGNER,
        ),
        201,
    )
    a.assert_stack_constraint_shape(edge)
    assert edge["program_a_id"] == g1["id"], edge["program_a_id"]
    assert edge["program_b_id"] == g2["id"], edge["program_b_id"]
    assert edge["mode"] == "CAPPED_TOTAL", edge["mode"]
    a.assert_money(edge, "cap_amount_cents", 500000)

    # The same single row is seen from either end of the unordered pair.
    from_a, meta_a = validate_paginated(
        api_client.list_stackability_constraints(g1["id"], fx.DESIGNER)
    )
    a.assert_list_length(from_a, 1, "edges touching G1")
    assert from_a[0]["mode"] == "CAPPED_TOTAL", from_a[0]
    assert meta_a["total_count"] == 1, meta_a

    from_b, meta_b = validate_paginated(
        api_client.list_stackability_constraints(g2["id"], fx.DESIGNER)
    )
    a.assert_list_length(from_b, 1, "edges touching G2")
    assert from_b[0]["mode"] == "CAPPED_TOTAL", from_b[0]
    assert from_b[0]["program_a_id"] == g1["id"], from_b[0]
    assert from_b[0]["id"] == edge["id"], from_b[0]
    assert meta_b["total_count"] == 1, meta_b

    # The reverse insertion over the same unordered pair is refused.
    validate_error(
        api_client.create_stackability_constraint(
            g2["id"], {"program_b_id": g1["id"], "mode": "FORBIDDEN"}, fx.DESIGNER
        ),
        "ERR_INVALID_STACK_EDGE",
    )

    # program_b_id must differ from the path program: no self-loops.
    validate_error(
        api_client.create_stackability_constraint(
            g1["id"], {"program_b_id": g1["id"], "mode": "ALLOWED"}, fx.DESIGNER
        ),
        "ERR_INVALID_STACK_EDGE",
    )

    after, _ = validate_paginated(
        api_client.list_stackability_constraints(g1["id"], fx.DESIGNER)
    )
    a.assert_list_length(after, 1, "edges touching G1 after both refusals")
    assert after[0]["mode"] == "CAPPED_TOTAL", after[0]
