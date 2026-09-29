"""The fiscal checks that close out a capture, and the headroom, uniqueness, scope and
state rules that govern remediation refunds."""

from test_helpers import (
    ApiErrorId,
    api_client,
    capture_sale,
    create_jurisdiction,
    create_merchant,
    create_program,
    create_refund,
    decide_registration,
    effectuate_registration,
    file_cost_documentation,
    file_rate_rule,
    issue_refund,
    list_items,
    list_total,
    read_complaint_case,
    read_merchant,
    read_refund,
    read_terminal,
    read_transaction,
    refund_payload,
    remediation_action_payload,
    set_clock,
    setup_active_surcharge_program,
    setup_case_with_accepted_plan,
    setup_configured_terminal,
    setup_enforcing_surcharge_estate,
    setup_enforcing_terminal,
    setup_refundable_sale,
    submit_registration,
    transaction_payload,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01, CLOCK_AUG_31
from test_helpers.fixtures import ADMIN, AUDITOR, OFFICER_ONE, OFFICER_TWO, activate_program
from test_helpers.test_users import make_terminal_agent_headers


def test_a_surcharged_sale_without_the_receipt_line_is_refused(api):
    """PRD §3.9: "If the jurisdiction's `receipt_line_item_required` is true and the computed `surcharge_amount_cents` is greater than 0, then `receipt_line_present` must be true; a surcharged sale whose receipt carried no separate line is rejected with `ERR_RECEIPT_LINE_ITEM_REQUIRED`."
    PRD §3.1: "`receipt_line_item_required` says whether the surcharge must be printed as its own line on the receipt."

    Design: Corner/validations/credit_sale_without_the_receipt_line_rejected
    """
    ctx = setup_enforcing_surcharge_estate(
        jurisdiction_profile="NY", serial_prefix="TRM-NY-"
    )
    assert ctx["jurisdiction"]["receipt_line_item_required"] is True
    terminal_id = ctx["terminal"]["id"]

    response = api_client.create_transaction(
        transaction_payload(
            terminal_id,
            ctx["program"]["id"],
            base_amount_cents=5000,
            requested_surcharge_cents=110,
            receipt_line_present=False,
        ),
        make_terminal_agent_headers(terminal_id),
    )
    validate_error(response, ApiErrorId.ERR_RECEIPT_LINE_ITEM_REQUIRED)

    assert (
        list_total(api_client.list_transactions(ADMIN, params={"terminal_id": terminal_id}))
        == 0
    )
    assert read_merchant(ctx["merchant"]["id"])["gross_surcharge_collected_cents"] == 0


def test_a_terminal_that_computed_one_cent_less_is_refused(api):
    """PRD §3.9: "And the terminal's own arithmetic must agree with the server's: `requested_surcharge_cents` must equal the computed `surcharge_amount_cents`, and any disagreement is rejected with `ERR_SURCHARGE_AMOUNT_MISMATCH` — a terminal running a stale rate table is a compliance incident, not a rounding nuisance."
    PRD §3.9: "On success the sale is persisted with `occurred_at` stamped from the logical clock and `refunded_surcharge_cents` at 0, and the merchant's surcharge ledger moves."

    Design: Corner/validations/transaction_with_a_mismatched_requested_surcharge_rejected
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    program_id = ctx["program"]["id"]
    terminal_id = ctx["terminal"]["id"]

    response = api_client.create_transaction(
        transaction_payload(
            terminal_id,
            program_id,
            base_amount_cents=5000,
            requested_surcharge_cents=109,
        ),
        make_terminal_agent_headers(terminal_id),
    )
    validate_error(response, ApiErrorId.ERR_SURCHARGE_AMOUNT_MISMATCH)

    assert (
        list_total(api_client.list_transactions(ADMIN, params={"program_id": program_id})) == 0
    )
    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 0
    assert merchant["net_surcharge_collected_cents"] == 0


def test_a_merely_configured_terminal_cannot_book_a_sale(api):
    """PRD §3.9: "The capturing terminal must be in state `ENFORCING`; a sale from a `PROVISIONED`, `CONFIGURED`, `QUARANTINED`, or `DISABLED` terminal is rejected with `ERR_INVALID_TERMINAL_STATE`."
    PRD §3.9: "The terminal's stored `program_id` must equal the body's `program_id`, else `ERR_TERMINAL_PROGRAM_MISMATCH` — a terminal cannot book against a program it is not configured for, even if that program is perfectly healthy."

    Design: Corner/validations/transaction_from_a_configured_terminal_rejected
    """
    ctx = setup_active_surcharge_program(jurisdiction_profile="AZ")
    program_id = ctx["program"]["id"]
    terminal = setup_configured_terminal(ctx["merchant"]["id"], program_id, "TRM-AZ-0001")
    assert terminal["program_id"] == program_id

    response = api_client.create_transaction(
        transaction_payload(terminal["id"], program_id),
        make_terminal_agent_headers(terminal["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TERMINAL_STATE)

    assert read_terminal(terminal["id"])["state"] == "CONFIGURED"
    assert (
        list_total(
            api_client.list_transactions(ADMIN, params={"terminal_id": terminal["id"]})
        )
        == 0
    )


def test_a_refund_one_cent_past_the_remainder_is_refused(api):
    """PRD §3.11: "The amount must be at least 1 cent and at most the sale's `surcharge_amount_cents` less its current `refunded_surcharge_cents` — the unrefunded remainder — and an amount beyond that remainder is rejected with `ERR_REFUND_AMOUNT_EXCEEDS_SURCHARGE`."
    PRD §3.11: "Creation moves no ledger field whatsoever: a pending refund is an intention, not a payment."

    Design: Corner/validations/refund_above_the_remaining_surcharge_rejected
    """
    ctx = setup_refundable_sale()
    case_id = ctx["complaint_case"]["id"]
    transaction_id = ctx["transaction"]["id"]
    assert ctx["transaction"]["surcharge_amount_cents"] == 219

    response = api_client.create_refund(
        case_id, refund_payload(transaction_id, 220), OFFICER_ONE
    )
    validate_error(response, ApiErrorId.ERR_REFUND_AMOUNT_EXCEEDS_SURCHARGE)

    assert (
        list_total(api_client.list_refunds(ADMIN, params={"complaint_case_id": case_id})) == 0
    )
    sale = read_transaction(transaction_id)
    assert sale["surcharge_amount_cents"] == 219
    assert sale["refunded_surcharge_cents"] == 0


def test_a_refund_for_the_whole_remainder_is_created_pending(api):
    """PRD §3.11: "A created refund begins in state `PENDING`, with the creating officer's `X-User-ID` recorded as `created_by_user_id` and with `issued_by_user_id`, `issued_at`, and `voided_at` all null."
    PRD §3.11: "A case's `refund_total_cents` is always the sum of `refund_amount_cents` over that case's refunds in state `ISSUED` — pending and voided refunds are excluded — and a sale's `refunded_surcharge_cents` is likewise the sum over the `ISSUED` refunds referencing it."

    Design: Corner/validations/refund_equal_to_the_remaining_surcharge_is_accepted
    """
    ctx = setup_refundable_sale()
    case_id = ctx["complaint_case"]["id"]
    transaction_id = ctx["transaction"]["id"]

    refund = validate_success(
        api_client.create_refund(case_id, refund_payload(transaction_id, 219), OFFICER_ONE),
        expected_status=201,
    )
    assert refund["state"] == "PENDING"
    assert refund["refund_amount_cents"] == 219
    assert refund["created_by_user_id"] == "officer-1"
    assert refund["issued_by_user_id"] is None
    assert refund["issued_at"] is None
    assert refund["voided_at"] is None
    assert refund["version"] == 1

    assert read_transaction(transaction_id)["refunded_surcharge_cents"] == 0
    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 219
    assert merchant["net_surcharge_collected_cents"] == 219
    assert read_complaint_case(case_id)["refund_total_cents"] == 0


def test_a_second_live_refund_for_the_same_sale_is_refused(api):
    """PRD §3.11: "At most one refund that is not `VOIDED` may exist for a given pairing of case and sale; a second live refund for the same pairing is rejected with `ERR_REFUND_DUPLICATE_TRANSACTION`, while a previously voided one does not block a fresh attempt."

    Design: Corner/validations/second_refund_for_the_same_transaction_rejected
    """
    ctx = setup_refundable_sale()
    case_id = ctx["complaint_case"]["id"]
    transaction_id = ctx["transaction"]["id"]
    first = create_refund(case_id, transaction_id, 100)
    assert first["state"] == "PENDING"

    response = api_client.create_refund(
        case_id, refund_payload(transaction_id, 50), OFFICER_ONE
    )
    validate_error(response, ApiErrorId.ERR_REFUND_DUPLICATE_TRANSACTION)

    refunds = list_items(api_client.list_refunds(ADMIN, params={"complaint_case_id": case_id}))
    assert len(refunds) == 1
    assert refunds[0]["id"] == first["id"]
    assert refunds[0]["refund_amount_cents"] == 100


def test_issuing_the_same_refund_twice_is_refused(api):
    """PRD §3.11: "The owning case's `remediation_state` must still be `PLAN_ACCEPTED`, else `ERR_INVALID_COMPLAINT_STATE`, and issuing a refund that is not `PENDING` is rejected with `ERR_INVALID_REFUND_STATE`."
    PRD §3.11: "On success the server stamps `issued_at` from the logical clock and `issued_by_user_id` from the acting `X-User-ID`, decreases the merchant's `net_surcharge_collected_cents` by `refund_amount_cents` while leaving `gross_surcharge_collected_cents` completely unchanged, increases the sale's `refunded_surcharge_cents` by the same amount, recomputes the case's `refund_total_cents`, and bumps both the merchant's `version` and the refund's `version` by 1."

    Design: Corner/validations/issuing_an_already_issued_refund_rejected
    """
    ctx = setup_refundable_sale()
    transaction_id = ctx["transaction"]["id"]
    refund = create_refund(ctx["complaint_case"]["id"], transaction_id, 219)
    issued = issue_refund(refund["id"])
    assert issued["state"] == "ISSUED"

    response = api_client.issue_refund(refund["id"], OFFICER_TWO)
    validate_error(response, ApiErrorId.ERR_INVALID_REFUND_STATE)

    after = read_refund(refund["id"])
    assert after["state"] == "ISSUED"
    assert after["issued_by_user_id"] == "officer-2"
    assert after["version"] == 2

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 219
    assert merchant["net_surcharge_collected_cents"] == 0
    assert read_transaction(transaction_id)["refunded_surcharge_cents"] == 219


def test_a_case_with_money_still_owed_cannot_be_closed(api):
    """PRD §3.10: "**`CLOSE`** is available to the same two roles under the same channel rule and requires `remediation_state` of `PLAN_ACCEPTED`; it additionally requires that no refund of the case is still in state `PENDING`, else the close is rejected with `ERR_REMEDIATION_REFUNDS_PENDING`."
    PRD §3.10: "`investigation_state` is untouched and stays `SUBSTANTIATED`."

    Design: Corner/validations/case_closure_with_a_pending_refund_rejected
    """
    ctx = setup_refundable_sale()
    case_id = ctx["complaint_case"]["id"]
    refund = create_refund(case_id, ctx["transaction"]["id"], 219)

    response = api_client.complaint_remediation_action(
        case_id, remediation_action_payload("CLOSE"), AUDITOR
    )
    validate_error(response, ApiErrorId.ERR_REMEDIATION_REFUNDS_PENDING)

    case = read_complaint_case(case_id)
    assert case["remediation_state"] == "PLAN_ACCEPTED"
    assert case["investigation_state"] == "SUBSTANTIATED"
    assert case["refund_total_cents"] == 0
    assert read_refund(refund["id"])["state"] == "PENDING"


def test_a_refund_cannot_reach_across_to_another_merchants_sale(api):
    """PRD §3.11: "The named sale must have been captured by a terminal of the merchant that owns the case's program; a refund reaching across merchants is rejected with `ERR_REFUND_TRANSACTION_SCOPE_MISMATCH`."
    PRD §3.9: "The merchant's `net_surcharge_collected_cents` is that gross figure less the total of the merchant's refunds in state `ISSUED`, so it increases by the same amount here."

    Design: Corner/validations/refund_citing_another_merchants_transaction_rejected
    """
    set_clock(CLOCK_AUG_01)
    jurisdiction = create_jurisdiction("AZ")
    estates = []
    for label in ("A", "B"):
        merchant = create_merchant(jurisdiction["id"], legal_name=f"Sonoran Supply {label}")
        documentation = file_cost_documentation(merchant["id"])
        program = create_program(
            merchant["id"], jurisdiction["id"], documentation["id"], "SURCHARGE", "BRAND_LEVEL"
        )
        file_rate_rule(program["id"], program["version"])
        registration = submit_registration(program["id"], "VISA", f"VS-2940-{label}-0001")
        decide_registration(registration["id"], "ACKNOWLEDGE")
        estates.append({"merchant": merchant, "program": program, "registration": registration})

    set_clock(CLOCK_AUG_31)
    for index, estate in enumerate(estates):
        effectuate_registration(estate["registration"]["id"])
        estate["program"] = activate_program(estate["program"]["id"])
        assert estate["program"]["status"] == "ACTIVE"
        terminal = setup_enforcing_terminal(
            estate["merchant"]["id"], estate["program"]["id"], f"TRM-AZ-{index + 1:04d}"
        )
        estate["transaction"] = capture_sale(terminal["id"], estate["program"]["id"])

    case = setup_case_with_accepted_plan(estates[0]["program"]["id"], "CARDHOLDER")
    response = api_client.create_refund(
        case["id"], refund_payload(estates[1]["transaction"]["id"], 100), OFFICER_ONE
    )
    validate_error(response, ApiErrorId.ERR_REFUND_TRANSACTION_SCOPE_MISMATCH)

    assert (
        list_total(api_client.list_refunds(ADMIN, params={"complaint_case_id": case["id"]}))
        == 0
    )
    assert read_transaction(estates[1]["transaction"]["id"])["refunded_surcharge_cents"] == 0
    assert read_merchant(estates[1]["merchant"]["id"])["net_surcharge_collected_cents"] == 219
