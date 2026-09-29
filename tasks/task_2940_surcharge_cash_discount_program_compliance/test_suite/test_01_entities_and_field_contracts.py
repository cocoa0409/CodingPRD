"""Field-level contracts: what a create body may set, what the server derives, and
what a read of each entity has to show."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_cost_documentation,
    assert_jurisdiction,
    assert_merchant,
    assert_terminal,
    assert_transaction,
    assert_instant_equals,
    cost_documentation_payload,
    create_jurisdiction,
    create_merchant,
    file_cost_documentation,
    is_valid_uuid,
    jurisdiction_payload,
    list_items,
    list_page,
    list_total,
    merchant_payload,
    program_payload,
    provision_terminal,
    rate_rule_payload,
    read_merchant,
    read_transaction,
    set_clock,
    setup_draft_program,
    setup_surcharged_sale,
    terminal_payload,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    CLOCK_DEC_31,
    TS_AUG_01,
    TS_AUG_31,
    UNMINTED_UUID,
)
from test_helpers.fixtures import ADMIN, OFFICER_ONE, OFFICER_TWO
from test_helpers.test_users import make_merchant_operator_headers


def test_jurisdiction_registration_echoes_every_declared_flag(api):
    """PRD §3.1: "A `PlatformAdmin` registers each state the platform operates in by supplying its `state_code` — exactly two uppercase letters — together with the seven law-variance flags that describe what that state permits and demands."
    PRD §3.1: "A freshly registered jurisdiction begins with `law_change_count` at 0 and `last_law_change_at` null."
    PRD §2.4: "Every resource this service persists is addressed by an `id`, which is a server-minted UUID carrying no type prefix and no embedded semantics."

    Design: Corner/entities/jurisdiction_creation_persists_all_declared_fields
    """
    set_clock(CLOCK_AUG_01)

    response = api_client.create_jurisdiction(jurisdiction_payload("MA"), ADMIN)
    data = validate_success(response, 201)

    assert_jurisdiction(data)
    assert data["state_code"] == "MA"
    assert data["surcharge_permitted"] is True
    assert data["surcharge_cap_pct"] == pytest.approx(3.5, abs=0.0001)
    assert data["cash_discount_permitted"] is False
    assert data["price_posting_required"] is False
    assert data["disclosure_signage_required"] is False
    assert data["receipt_line_item_required"] is False
    assert data["ag_enforcement_posture"] == "PERMISSIVE"
    assert data["law_change_count"] == 0
    assert data["last_law_change_at"] is None
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert_instant_equals(data["created_at"], TS_AUG_01, "created_at")


def test_jurisdiction_read_returns_the_stored_texas_row(api):
    """PRD §3.1: "`surcharge_cap_pct` carries the statutory ceiling as a percentage: it must be greater than 0 and at most 100 with up to four decimal places, it must be supplied and non-null whenever `surcharge_permitted` is true, and it must be null whenever `surcharge_permitted` is false."
    PRD §4: "| GET | `/jurisdictions/{id}` | Read one jurisdiction's law profile. | All six roles |"

    Design: Corner/entities/jurisdiction_retrieval_by_id_returns_stored_row
    """
    set_clock(CLOCK_AUG_01)
    created = create_jurisdiction("TX")

    data = validate_success(api_client.get_jurisdiction(created["id"], OFFICER_ONE))

    assert_jurisdiction(data)
    assert data["id"] == created["id"]
    assert data["state_code"] == "TX"
    assert data["surcharge_cap_pct"] == pytest.approx(2.0, abs=0.0001)
    assert data["ag_enforcement_posture"] == "PERMISSIVE"
    assert data["version"] == 1
    assert data["law_change_count"] == 0


def test_jurisdiction_listing_reports_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter defaults to 10, accepts a minimum of 1 and a maximum of 100, and the `offset` parameter defaults to 0 with a minimum of 0."
    PRD §2.3: "List responses carry `response_type` of `"array"`, and their `meta` object includes `limit` and `offset` as applied, `total_count` giving the number of rows matching the filter before pagination, and `has_more` which is true exactly when rows remain beyond the returned page."
    PRD §3.1: "The jurisdiction collection may be filtered by `state_code` and by `surcharge_permitted`."

    Design: Corner/entities/jurisdiction_listing_paginates_with_total_count_and_has_more
    """
    set_clock(CLOCK_AUG_01)
    create_jurisdiction("AZ")
    create_jurisdiction("NY")
    create_jurisdiction("TX")

    first_page, first_meta = list_page(
        api_client.list_jurisdictions(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    second_page, second_meta = list_page(
        api_client.list_jurisdictions(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    filtered, filtered_meta = list_page(
        api_client.list_jurisdictions(ADMIN, params={"state_code": "NY"})
    )
    assert filtered_meta["total_count"] == 1
    assert filtered[0]["state_code"] == "NY"


def test_reading_an_unminted_merchant_id_is_a_not_found_error(api):
    """PRD §2.6: "Identifiers in a request path are resolved left to right, and the first one that does not resolve determines the rejection."
    PRD §2.6: "Each entity has its own not-found code: `ERR_JURISDICTION_NOT_FOUND`, `ERR_MERCHANT_NOT_FOUND`, `ERR_COST_DOCUMENTATION_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`, `ERR_ARTIFACT_NOT_FOUND`, `ERR_TERMINAL_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, and `ERR_REFUND_NOT_FOUND`, each carrying HTTP 404."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/merchant_retrieval_with_unknown_id_returns_not_found
    """
    set_clock(CLOCK_AUG_01)

    response = api_client.get_merchant(UNMINTED_UUID, ADMIN)
    error = validate_error(response, ApiErrorId.ERR_MERCHANT_NOT_FOUND, 404)

    assert error["error_id"] == "ERR_MERCHANT_NOT_FOUND"
    body = response.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]


def test_merchant_creation_without_an_mcc_is_a_shape_defect(api):
    """PRD §3.2: "A `PlatformAdmin` onboards a merchant into a jurisdiction by supplying the governing `jurisdiction_id`, the merchant's `legal_name` — between 1 and 200 characters — and its four-digit `mcc`."
    PRD §2.9: "**Request shape** — required fields present, enum members recognised, numbers inside their declared ranges, ISO 8601 instants parseable, `base_amount_cents` at least 1, `refund_amount_cents` at least 1, `requested_surcharge_cents` at least 0, a disclosure artifact's `expires_at` strictly after its `effective_from`, a rate rule's `effective_to` strictly after its `effective_from`, and `product_tier` equal to `NOT_APPLICABLE` exactly when `card_funding` is not `CREDIT`: `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/merchant_creation_missing_required_mcc_rejected
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")

    response = api_client.create_merchant(
        {"jurisdiction_id": jurisdiction["id"], "legal_name": "Sonoran Supply Co"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    assert list_total(api_client.list_merchants(ADMIN)) == 0


def test_provisioned_terminal_defaults_to_an_unbound_state(api):
    """PRD §3.8: "A provisioned terminal begins in state `PROVISIONED` with `program_id` null, `debit_exclusion_enabled` false, `bin_table_version` null, `quarantine_reason` of `NONE`, and `last_configured_at` null."
    PRD §3.8: "A `MerchantOperator` provisions a terminal under its own merchant by supplying only the manufacturer's `serial_number`, between 1 and 40 characters."

    Design: Corner/entities/terminal_creation_defaults_state_provisioned_and_null_program
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    merchant = create_merchant(jurisdiction["id"])

    response = api_client.create_terminal(
        merchant["id"],
        terminal_payload("TRM-AZ-0001"),
        make_merchant_operator_headers(merchant["id"]),
    )
    data = validate_success(response, 201)

    assert_terminal(data)
    assert data["state"] == "PROVISIONED"
    assert data["program_id"] is None
    assert data["bin_table_version"] is None
    assert data["last_configured_at"] is None
    assert data["debit_exclusion_enabled"] is False
    assert data["quarantine_reason"] == "NONE"
    assert data["merchant_id"] == merchant["id"]
    assert data["serial_number"] == "TRM-AZ-0001"
    assert data["version"] == 1
    assert read_merchant(merchant["id"])["enforcing_terminal_count"] == 0


def test_new_merchant_starts_with_an_empty_surcharge_ledger(api):
    """PRD §3.2: "A new merchant starts with `gross_surcharge_collected_cents`, `net_surcharge_collected_cents`, and `enforcing_terminal_count` all at 0, and with `active_cost_documentation_id` null."

    Design: Corner/entities/merchant_creation_defaults_ledger_counters_to_zero
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")

    response = api_client.create_merchant(merchant_payload(jurisdiction["id"]), ADMIN)
    data = validate_success(response, 201)

    assert_merchant(data)
    assert data["gross_surcharge_collected_cents"] == 0
    assert data["net_surcharge_collected_cents"] == 0
    assert data["enforcing_terminal_count"] == 0
    assert data["active_cost_documentation_id"] is None
    assert data["jurisdiction_id"] == jurisdiction["id"]
    assert data["version"] == 1


def test_cost_documentation_freezes_the_default_ticket_and_documented_cost(api):
    """PRD §3.2: "If the merchant has captured no transactions at all, `average_ticket_cents` is instead the default average ticket of 5000 cents — fifty dollars — which is a fallback, never an error."
    PRD §3.2: "The per-item component is `per_item_fee_cents` divided by `average_ticket_cents`, multiplied by 100, and rounded half up to four decimal places."
    PRD §3.2: "`documented_cost_pct` is then `base_mdr_pct` plus `assessment_pct` plus that per-item component, with the sum rounded half up to four decimal places."
    PRD §3.2: "The merchant's existing document in state `ACTIVE`, if there is one, moves to `SUPERSEDED` with `superseded_at` stamped from the logical clock and its own `version` bumped; the merchant's `active_cost_documentation_id` is repointed at the new document; and the merchant's `version` is bumped by 1."

    Design: Corner/entities/cost_documentation_computed_fields_average_ticket_and_documented_cost
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    merchant = create_merchant(jurisdiction["id"])

    response = api_client.create_cost_documentation(
        merchant["id"],
        cost_documentation_payload(merchant["version"], "docA"),
        OFFICER_ONE,
    )
    data = validate_success(response, 201)

    assert_cost_documentation(data)
    assert data["average_ticket_cents"] == 5000
    assert data["documented_cost_pct"] == pytest.approx(2.19, abs=0.0001)
    assert data["state"] == "ACTIVE"
    assert data["superseded_at"] is None
    assert read_merchant(merchant["id"])["active_cost_documentation_id"] == data["id"]


def test_cost_documentation_ignores_client_supplied_system_fields(api):
    """PRD §3.2: "The server stamps `attested_by_user_id` with the filing officer's `X-User-ID` and `effective_from` with the logical clock, and the row is created in state `ACTIVE` with `superseded_at` null."
    PRD §2.4: "Clients never supply an `id`; a client-supplied identifier in a create body is ignored."

    Design: Corner/entities/cost_documentation_system_fields_input_ignored
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    merchant = create_merchant(jurisdiction["id"])

    payload = cost_documentation_payload(merchant["version"], "docA")
    payload["state"] = "SUPERSEDED"
    payload["effective_from"] = "2020-01-01T00:00:00Z"
    payload["attested_by_user_id"] = "officer-9"

    data = validate_success(
        api_client.create_cost_documentation(merchant["id"], payload, OFFICER_TWO), 201
    )

    assert_cost_documentation(data)
    assert data["state"] == "ACTIVE"
    assert_instant_equals(data["effective_from"], TS_AUG_01, "effective_from")
    assert data["attested_by_user_id"] == "officer-2"
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1


def test_jurisdiction_cap_above_one_hundred_is_rejected(api):
    """PRD §2.9: "Checks are evaluated in the following fixed order, and the first failing check determines both the `error_id` and the HTTP status."
    PRD §2.9: "**Jurisdiction cap coherence** — a jurisdiction whose `surcharge_permitted` is true carries a non-null `surcharge_cap_pct`, and one whose `surcharge_permitted` is false carries `surcharge_cap_pct` null: `ERR_JURISDICTION_CAP_REQUIRED`, 422. Applies to jurisdiction registration and to law changes."
    PRD §3.1: "`surcharge_cap_pct` carries the statutory ceiling as a percentage: it must be greater than 0 and at most 100 with up to four decimal places, it must be supplied and non-null whenever `surcharge_permitted` is true, and it must be null whenever `surcharge_permitted` is false."

    Design: Corner/entities/jurisdiction_cap_out_of_range_rejected
    """
    set_clock(CLOCK_AUG_01)

    response = api_client.create_jurisdiction(
        jurisdiction_payload("AZ", surcharge_cap_pct=150.0), ADMIN
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert error["error_id"] != "ERR_JURISDICTION_CAP_REQUIRED"

    assert list_total(api_client.list_jurisdictions(ADMIN)) == 0


def test_rate_rule_naming_an_unknown_brand_is_rejected(api):
    """PRD §3.4: "Each rule names the `brand` it prices — one of `VISA`, `MASTERCARD`, `DISCOVER`, or `AMEX` — the `product_tier` it applies to, the `rate_pct` to apply, and a closed effectivity interval running from `effective_from` through `effective_to` inclusive."
    PRD §2.9: "**Request shape** — required fields present, enum members recognised, numbers inside their declared ranges, ISO 8601 instants parseable, `base_amount_cents` at least 1, `refund_amount_cents` at least 1, `requested_surcharge_cents` at least 0, a disclosure artifact's `expires_at` strictly after its `effective_from`, a rate rule's `effective_to` strictly after its `effective_from`, and `product_tier` equal to `NOT_APPLICABLE` exactly when `card_funding` is not `CREDIT`: `ERR_INVALID_REQUEST`, 400."

    Design: Corner/entities/brand_rate_rule_unknown_brand_enum_rejected
    """
    ctx = setup_draft_program(with_rate_rule=False)
    program = ctx["program"]

    response = api_client.create_rate_rule(
        program["id"],
        rate_rule_payload(
            program["version"],
            brand="UNIONPAY",
            product_tier="ALL",
            rate_pct=2.0,
            effective_from=CLOCK_AUG_01,
            effective_to=CLOCK_DEC_31,
        ),
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    assert (
        list_total(api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program["id"]}))
        == 0
    )


def test_provisioning_under_an_unminted_merchant_is_a_not_found_error(api):
    """PRD §2.9: "**Path existence** — every identifier in the path resolves, left to right: the 404 family of §2.6. Applies to every operation with a path identifier."
    PRD §2.9: "**Merchant ownership** — a `MerchantOperator`'s `X-User-ID` equals the target's merchant: `ERR_MERCHANT_OWNERSHIP_REQUIRED`, 403. Applies to exactly four operations: provisioning a terminal under a merchant, configuring a terminal, driving a terminal's state action, and drafting a disclosure artifact for a program (where the comparison is against that program's `merchant_id`)."
    PRD §2.9: "Later checks are not evaluated once an earlier one has failed."

    Design: Corner/entities/terminal_creation_under_unknown_merchant_not_found
    """
    set_clock(CLOCK_AUG_01)

    response = api_client.create_terminal(
        UNMINTED_UUID,
        terminal_payload("TRM-GHOST-0001"),
        make_merchant_operator_headers(UNMINTED_UUID),
    )
    error = validate_error(response, ApiErrorId.ERR_MERCHANT_NOT_FOUND, 404)
    assert error["error_id"] != "ERR_MERCHANT_OWNERSHIP_REQUIRED"

    assert list_total(api_client.list_terminals(ADMIN)) == 0


def test_program_cannot_pin_another_merchants_cost_documentation(api):
    """PRD §3.3: "The pinned document must belong to the same merchant, on pain of `ERR_COST_DOCUMENTATION_MERCHANT_MISMATCH`, and must be in state `ACTIVE` at the moment of pinning."
    PRD §2.9: "**Cost-documentation ownership** — the pinned document's `merchant_id` equals the program's `merchant_id`: `ERR_COST_DOCUMENTATION_MERCHANT_MISMATCH`, 422. Applies to program creation and the program partial update."

    Design: Corner/entities/program_creation_with_other_merchants_cost_documentation_rejected
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    merchant_a = create_merchant(jurisdiction["id"], legal_name="Merchant A LLC", mcc="5734")
    merchant_b = create_merchant(jurisdiction["id"], legal_name="Merchant B LLC", mcc="5999")
    file_cost_documentation(merchant_a["id"], merchant_a["version"], "docA")
    documentation_b = file_cost_documentation(merchant_b["id"], merchant_b["version"], "docA")

    response = api_client.create_program(
        program_payload(
            merchant_a["id"],
            jurisdiction["id"],
            documentation_b["id"],
            "SURCHARGE",
            "BRAND_LEVEL",
        ),
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_COST_DOCUMENTATION_MERCHANT_MISMATCH, 422)

    assert (
        list_total(
            api_client.list_programs(OFFICER_ONE, params={"merchant_id": merchant_a["id"]})
        )
        == 0
    )


def test_program_cannot_name_a_jurisdiction_its_merchant_does_not_operate_in(api):
    """PRD §3.3: "The supplied `jurisdiction_id` must equal the merchant's own `jurisdiction_id`; a program cannot be governed by a state its merchant does not operate in, and a mismatch is rejected with `ERR_JURISDICTION_SCOPE_MISMATCH`."
    PRD §2.9: "**Jurisdiction scope agreement** — the program's `jurisdiction_id` equals its merchant's `jurisdiction_id`: `ERR_JURISDICTION_SCOPE_MISMATCH`, 422. Applies to program creation."

    Design: Corner/entities/program_creation_with_foreign_jurisdiction_rejected
    """
    set_clock(CLOCK_AUG_01)
    arizona = create_jurisdiction("AZ")
    texas = create_jurisdiction("TX")
    merchant = create_merchant(arizona["id"])
    documentation = file_cost_documentation(merchant["id"], merchant["version"], "docA")

    response = api_client.create_program(
        program_payload(
            merchant["id"], texas["id"], documentation["id"], "SURCHARGE", "BRAND_LEVEL"
        ),
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_JURISDICTION_SCOPE_MISMATCH, 422)

    assert (
        list_total(api_client.list_programs(OFFICER_ONE, params={"merchant_id": merchant["id"]}))
        == 0
    )


def test_captured_sale_carries_neither_version_nor_updated_at(api):
    """PRD §2.4: "`Transaction` is the single exception. A captured sale is an immutable event, not a mutable resource: a `Transaction` carries `id` and `created_at` only, and both `updated_at` and `version` are absent from its representation entirely."
    PRD §2.4: "A `Transaction`'s derived `refunded_surcharge_cents` is recomputed at read time from the refunds that reference it rather than being treated as a versioned mutation of the sale."

    Design: Corner/entities/transaction_is_immutable_and_carries_no_version_field
    """
    ctx = setup_surcharged_sale(
        serial_prefix="TRM-AZ-2", base_amount_cents=10000, requested_surcharge_cents=219
    )

    data = read_transaction(ctx["transaction"]["id"])

    assert_transaction(data)
    assert data["id"] == ctx["transaction"]["id"]
    assert "version" not in data
    assert "updated_at" not in data
    assert_instant_equals(data["occurred_at"], TS_AUG_31, "occurred_at")
    assert data["surcharge_amount_cents"] == 219
    assert data["total_amount_cents"] == 10219
    assert data["refunded_surcharge_cents"] == 0
