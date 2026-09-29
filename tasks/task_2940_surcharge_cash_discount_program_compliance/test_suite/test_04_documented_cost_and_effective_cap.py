"""The two frozen numbers on a cost document, the three-way minimum that becomes a
program's cap, and which rate rule a capture ends up selecting."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    apply_law_change,
    assert_instant_equals,
    capture_sale,
    cost_documentation_payload,
    file_rate_rule,
    list_items,
    list_total,
    read_merchant,
    read_program,
    read_terminal,
    read_transaction,
    set_clock,
    setup_active_surcharge_program,
    setup_draft_program,
    setup_enforcing_surcharge_estate,
    setup_enforcing_terminal,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    CLOCK_DEC_31,
    CLOCK_OCT_01,
    TS_AUG_31,
)
from test_helpers.fixtures import ADMIN, OFFICER_ONE
from test_helpers.test_users import make_terminal_agent_headers

WINDOW_END_SEP_30 = "2026-09-30T00:00:00Z"


def test_the_mean_ticket_rounds_half_up_and_is_frozen_onto_the_new_document(api):
    """PRD §3.2: "It then takes the arithmetic mean of those sales' `base_amount_cents`, rounds it half up to a whole number of cents, and stores the result as `average_ticket_cents` on the new document."
    PRD §3.2: "The per-item component is `per_item_fee_cents` divided by `average_ticket_cents`, multiplied by 100, and rounded half up to four decimal places."
    PRD §3.2: "A sale captured tomorrow does not retroactively change a document filed today; only a *new* document, filed later, picks up the newer average ticket."

    Design: Corner/calculations/average_ticket_mean_rounds_half_up_and_freezes_the_documented_cost
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    merchant_id = ctx["merchant"]["id"]
    doc_a_id = ctx["cost_documentation"]["id"]
    capture_sale(
        ctx["terminal"]["id"],
        ctx["program"]["id"],
        base_amount_cents=1234,
        requested_surcharge_cents=27,
    )
    capture_sale(
        ctx["terminal"]["id"],
        ctx["program"]["id"],
        base_amount_cents=5677,
        requested_surcharge_cents=124,
    )

    doc_c = validate_success(
        api_client.create_cost_documentation(
            merchant_id,
            cost_documentation_payload(
                read_merchant(merchant_id)["version"],
                "docA",
                evidence_uri="s3://acq/az/2026-08.pdf",
            ),
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert doc_c["average_ticket_cents"] == 3456
    assert doc_c["documented_cost_pct"] == pytest.approx(2.2794, abs=0.00001)

    frozen = validate_success(api_client.get_cost_documentation(doc_a_id, ADMIN))
    assert frozen["average_ticket_cents"] == 5000
    assert frozen["documented_cost_pct"] == pytest.approx(2.19, abs=0.00001)

    merchant = read_merchant(merchant_id)
    assert merchant["gross_surcharge_collected_cents"] == 151
    assert merchant["active_cost_documentation_id"] == doc_c["id"]


def test_the_ticket_average_ignores_the_surcharge_the_sale_collected(api):
    """PRD §3.2: "Only `base_amount_cents` participates: surcharge and cash-discount amounts are deliberately excluded so that the ticket average cannot feed back into the very surcharge it helps to cap."
    PRD §3.2: "The server collects every `Transaction` captured by a terminal belonging to this merchant whose `occurred_at` is at or before the current logical clock — every captured sale qualifies regardless of which of the three outcomes it carries, there is no lower time bound, and each sale is counted once."

    Design: Corner/calculations/average_ticket_counts_base_amount_only_ignoring_the_surcharge
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    merchant_id = ctx["merchant"]["id"]
    sale = capture_sale(
        ctx["terminal"]["id"],
        ctx["program"]["id"],
        base_amount_cents=10000,
        requested_surcharge_cents=219,
    )

    document = validate_success(
        api_client.create_cost_documentation(
            merchant_id,
            cost_documentation_payload(
                read_merchant(merchant_id)["version"],
                "docA",
                evidence_uri="s3://acq/az/2026-08b.pdf",
            ),
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert document["average_ticket_cents"] == 10000
    assert document["documented_cost_pct"] == pytest.approx(2.09, abs=0.00001)

    reread = read_transaction(sale["id"])
    assert reread["base_amount_cents"] == 10000
    assert reread["surcharge_amount_cents"] == 219
    assert reread["total_amount_cents"] == 10219


def test_a_merchant_with_no_captured_sales_falls_back_to_the_default_ticket(api):
    """PRD §3.2: "If the merchant has captured no transactions at all, `average_ticket_cents` is instead the default average ticket of 5000 cents — fifty dollars — which is a fallback, never an error."
    PRD §3.2: "`documented_cost_pct` is then `base_mdr_pct` plus `assessment_pct` plus that per-item component, with the sum rounded half up to four decimal places."

    Design: Corner/calculations/default_average_ticket_constant_applies_when_no_transaction_exists
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    merchant_id = ctx["merchant"]["id"]
    assert read_terminal(ctx["terminal"]["id"])["state"] == "ENFORCING"

    document = validate_success(
        api_client.create_cost_documentation(
            merchant_id,
            cost_documentation_payload(
                read_merchant(merchant_id)["version"],
                "docA",
                evidence_uri="s3://acq/az/2026-08c.pdf",
            ),
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert document["average_ticket_cents"] == 5000
    assert document["documented_cost_pct"] == pytest.approx(2.19, abs=0.00001)

    assert (
        list_total(
            api_client.list_transactions(ADMIN, params={"program_id": ctx["program"]["id"]})
        )
        == 0
    )
    assert read_merchant(merchant_id)["gross_surcharge_collected_cents"] == 0


def test_the_texas_statutory_ceiling_binds_below_the_documented_cost(api):
    """PRD §3.3: "For a `SURCHARGE` program it is the smallest of three numbers: the frozen `documented_cost_pct` of the pinned cost documentation, the jurisdiction's statutory `surcharge_cap_pct`, and the network ceiling of 3.0 percent."
    PRD §3.4: "A `rate_pct` at most `effective_cap_pct` is admitted, with equality passing; a `rate_pct` strictly greater than `effective_cap_pct` is rejected with `ERR_SURCHARGE_CAP_EXCEEDED`."

    Design: Corner/calculations/state_cap_binds_the_effective_surcharge_cap_in_texas
    """
    ctx = setup_draft_program(jurisdiction_profile="TX", with_rate_rule=False)
    program_id = ctx["program"]["id"]
    assert ctx["cost_documentation"]["documented_cost_pct"] == pytest.approx(2.19, abs=0.00001)
    assert ctx["program"]["effective_cap_pct"] == pytest.approx(2.0, abs=0.00001)

    over = api_client.create_rate_rule(
        program_id,
        {
            "brand": "VISA",
            "product_tier": "ALL",
            "rate_pct": 2.19,
            "effective_from": CLOCK_AUG_01,
            "effective_to": CLOCK_DEC_31,
            "expected_program_version": ctx["program"]["version"],
        },
        OFFICER_ONE,
    )
    validate_error(over, ApiErrorId.ERR_SURCHARGE_CAP_EXCEEDED)

    at_the_cap = validate_success(
        api_client.create_rate_rule(
            program_id,
            {
                "brand": "VISA",
                "product_tier": "ALL",
                "rate_pct": 2.0,
                "effective_from": CLOCK_AUG_01,
                "effective_to": CLOCK_DEC_31,
                "expected_program_version": ctx["program"]["version"],
            },
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert at_the_cap["rate_pct"] == pytest.approx(2.0, abs=0.00001)
    assert at_the_cap["product_tier"] == "ALL"
    assert (
        list_total(api_client.list_rate_rules(ADMIN, params={"program_id": program_id})) == 1
    )


def test_a_cash_discount_program_takes_its_cap_from_the_ten_percent_ceiling(api):
    """PRD §3.3: "For a `CASH_DISCOUNT` program the cap is simply the cash-discount ceiling of 10.0 percent."
    PRD §3.3: "The cap is inclusive: a rate rule whose rate exactly equals the cap is admissible."
    PRD §3.4: "Finally, the rate itself must sit under the program's cap."

    Design: Corner/calculations/cash_discount_program_cap_uses_the_ten_percent_constant
    """
    ctx = setup_draft_program(program_type="CASH_DISCOUNT", with_rate_rule=False)
    program_id = ctx["program"]["id"]
    assert ctx["program"]["program_type"] == "CASH_DISCOUNT"
    assert ctx["program"]["effective_cap_pct"] == pytest.approx(10.0, abs=0.00001)
    assert ctx["cost_documentation"]["documented_cost_pct"] == pytest.approx(2.19, abs=0.00001)

    admitted = validate_success(
        api_client.create_rate_rule(
            program_id,
            {
                "brand": "VISA",
                "product_tier": "ALL",
                "rate_pct": 9.5,
                "effective_from": CLOCK_AUG_01,
                "effective_to": CLOCK_DEC_31,
                "expected_program_version": ctx["program"]["version"],
            },
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert admitted["rate_pct"] == pytest.approx(9.5, abs=0.00001)

    response = api_client.create_rate_rule(
        program_id,
        {
            "brand": "MASTERCARD",
            "product_tier": "ALL",
            "rate_pct": 10.5,
            "effective_from": CLOCK_AUG_01,
            "effective_to": CLOCK_DEC_31,
            "expected_program_version": read_program(program_id)["version"],
        },
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_SURCHARGE_CAP_EXCEEDED)
    assert (
        list_total(api_client.list_rate_rules(ADMIN, params={"program_id": program_id})) == 1
    )


def test_re_permission_propagates_the_new_statutory_cap_into_the_program(api):
    """PRD §3.1: "Every program of that jurisdiction whose `status` is `DISABLED` and whose `disable_reason` is exactly `JURISDICTION_PROHIBITION` moves to `SUSPENDED` with `disable_reason` reset to `OPERATOR_SUSPENSION`, and its `effective_cap_pct` is recomputed against the jurisdiction's new `surcharge_cap_pct`."
    PRD §3.1: "Applying a law change increments `law_change_count` by exactly 1, sets `last_law_change_at` to the current logical clock, and bumps the jurisdiction's `version`."
    PRD §3.1: "First, every `SurchargeProgram` whose `jurisdiction_id` is the changed jurisdiction, whose `program_type` is `SURCHARGE`, and whose `status` is neither `DISABLED` nor `WITHDRAWN` moves to `DISABLED` with `disable_reason` set to `JURISDICTION_PROHIBITION` — that is, programs in `DRAFT`, `PENDING_REGISTRATION`, `ACTIVE`, `SUSPENDED`, and `REMEDIATION` are all swept."

    Design: Corner/calculations/law_change_repermitting_surcharging_recomputes_the_effective_cap
    """
    ctx = setup_active_surcharge_program()
    program_id = ctx["program"]["id"]
    jurisdiction_id = ctx["jurisdiction"]["id"]
    assert ctx["program"]["effective_cap_pct"] == pytest.approx(2.19, abs=0.00001)
    rule_id = ctx["rate_rule"]["id"]

    apply_law_change(jurisdiction_id, False, surcharge_cap_pct=None)
    before = read_program(program_id)
    assert before["status"] == "DISABLED"
    assert before["disable_reason"] == "JURISDICTION_PROHIBITION"
    assert before["effective_cap_pct"] == pytest.approx(2.19, abs=0.00001)

    changed = apply_law_change(
        jurisdiction_id, True, surcharge_cap_pct=1.0, cash_discount_permitted=True
    )
    assert changed["surcharge_permitted"] is True
    assert changed["surcharge_cap_pct"] == pytest.approx(1.0, abs=0.00001)
    assert changed["law_change_count"] == 2
    assert_instant_equals(changed["last_law_change_at"], TS_AUG_31, "last_law_change_at")

    after = read_program(program_id)
    assert after["status"] == "SUSPENDED"
    assert after["disable_reason"] == "OPERATOR_SUSPENSION"
    assert after["effective_cap_pct"] == pytest.approx(1.0, abs=0.00001)

    rules = list_items(api_client.list_rate_rules(ADMIN, params={"program_id": program_id}))
    assert len(rules) == 1
    assert rules[0]["id"] == rule_id
    assert rules[0]["rate_pct"] == pytest.approx(2.19, abs=0.00001)


def test_each_credit_tier_selects_its_own_rate_rule(api):
    """PRD §3.9: "Among the candidates, a rule whose `product_tier` exactly equals the capture's tier ranks strictly above a rule whose `product_tier` is `ALL`, so a specific tier rate always beats a catch-all."
    PRD §3.3: "`PRODUCT_LEVEL` means the merchant prices named credit product tiers separately and every rate rule must name a specific tier rather than `ALL`."
    PRD §3.9: "On a `SURCHARGE` program with `card_funding` of `CREDIT`: `surcharge_amount_cents` is `base_amount_cents` multiplied by the applied rate, divided by 100, rounded half up to a whole cent; `cash_discount_amount_cents` is 0; `cash_price_cents` equals `base_amount_cents`; `total_amount_cents` is `base_amount_cents` plus `surcharge_amount_cents`; and `outcome` is `APPROVED_WITH_SURCHARGE`."

    Design: Corner/calculations/product_tier_specific_rate_rules_are_selected_by_tier
    """
    ctx = setup_active_surcharge_program(
        consistency_scope="PRODUCT_LEVEL", product_tier="CONSUMER_CREDIT", rate_pct=1.5
    )
    program_id = ctx["program"]["id"]
    merchant_id = ctx["merchant"]["id"]
    file_rate_rule(
        program_id,
        brand="VISA",
        product_tier="REWARDS_CREDIT",
        rate_pct=2.19,
        effective_from=CLOCK_AUG_01,
        effective_to=CLOCK_DEC_31,
    )
    terminal = setup_enforcing_terminal(merchant_id, program_id, "TRM-AZ-0001")
    agent = make_terminal_agent_headers(terminal["id"])

    consumer = validate_success(
        api_client.create_transaction(
            {
                "terminal_id": terminal["id"],
                "program_id": program_id,
                "card_brand": "VISA",
                "card_funding": "CREDIT",
                "product_tier": "CONSUMER_CREDIT",
                "base_amount_cents": 10000,
                "requested_surcharge_cents": 150,
                "receipt_line_present": True,
            },
            agent,
        ),
        expected_status=201,
    )
    assert consumer["applied_rate_pct"] == pytest.approx(1.5, abs=0.00001)
    assert consumer["surcharge_amount_cents"] == 150
    assert consumer["total_amount_cents"] == 10150
    assert consumer["outcome"] == "APPROVED_WITH_SURCHARGE"

    rewards = validate_success(
        api_client.create_transaction(
            {
                "terminal_id": terminal["id"],
                "program_id": program_id,
                "card_brand": "VISA",
                "card_funding": "CREDIT",
                "product_tier": "REWARDS_CREDIT",
                "base_amount_cents": 10000,
                "requested_surcharge_cents": 219,
                "receipt_line_present": True,
            },
            agent,
        ),
        expected_status=201,
    )
    assert rewards["applied_rate_pct"] == pytest.approx(2.19, abs=0.00001)
    assert rewards["surcharge_amount_cents"] == 219
    assert rewards["total_amount_cents"] == 10219

    assert read_merchant(merchant_id)["gross_surcharge_collected_cents"] == 369


def test_a_credit_sale_past_the_rules_inclusive_end_finds_no_candidate(api):
    """PRD §3.9: "Otherwise — for a `SURCHARGE` program with `CREDIT` funding, and for every `CASH_DISCOUNT` capture regardless of funding — candidate rules are gathered from the program's rate table: rules whose `program_id` is the capture's program, whose `brand` equals the capture's `card_brand`, whose closed effectivity interval contains the logical clock (that is, `effective_from` at or before the clock and `effective_to` at or after the clock, both ends inclusive), and whose `product_tier` either equals the capture's `product_tier` or is `ALL`."
    PRD §3.9: "If no candidate survives, the capture is rejected with `ERR_NO_RATE_RULE_IN_EFFECT`."

    Design: Corner/calculations/no_rate_rule_in_effect_rejects_a_credit_sale_after_the_window_closes
    """
    ctx = setup_enforcing_surcharge_estate(
        serial_prefix="TRM-AZ-", effective_to=WINDOW_END_SEP_30
    )
    program_id = ctx["program"]["id"]
    terminal_id = ctx["terminal"]["id"]
    set_clock(CLOCK_OCT_01)

    response = api_client.create_transaction(
        {
            "terminal_id": terminal_id,
            "program_id": program_id,
            "card_brand": "VISA",
            "card_funding": "CREDIT",
            "product_tier": "CONSUMER_CREDIT",
            "base_amount_cents": 10000,
            "requested_surcharge_cents": 219,
            "receipt_line_present": True,
        },
        make_terminal_agent_headers(terminal_id),
    )
    validate_error(response, ApiErrorId.ERR_NO_RATE_RULE_IN_EFFECT)

    assert read_program(program_id)["status"] == "ACTIVE"
    assert read_terminal(terminal_id)["state"] == "ENFORCING"
    assert (
        list_total(api_client.list_transactions(ADMIN, params={"program_id": program_id})) == 0
    )
    assert read_merchant(ctx["merchant"]["id"])["gross_surcharge_collected_cents"] == 0
