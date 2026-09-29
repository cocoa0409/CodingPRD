"""Which error surfaces when one request breaks two rules, and what happens exactly
at the cap boundary and the empty-set boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    capture_sale,
    create_program,
    get_success_data,
    program_status_action,
    read_merchant,
    read_program,
    read_terminal,
    setup_draft_program,
    setup_enforcing_surcharge_estate,
    setup_program_with_effective_registration,
    validate_error,
    list_total,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01, CLOCK_DEC_31, TS_AUG_31
from test_helpers.fixtures import ADMIN, OFFICER_ONE, activate_program


def test_withdrawn_program_reports_its_state_rather_than_the_excessive_rate(api):
    """PRD §2.9: "Checks are evaluated in the following fixed order, and the first failing check determines both the `error_id` and the HTTP status. Later checks are not evaluated once an earlier one has failed."
    PRD §2.9: "**Declared transition available from the current state** — `ERR_INVALID_PROGRAM_STATE`, `ERR_INVALID_REGISTRATION_STATE`, `ERR_INVALID_ARTIFACT_STATE`, `ERR_INVALID_TERMINAL_STATE`, `ERR_INVALID_COMPLAINT_STATE`, or `ERR_INVALID_REFUND_STATE`, all 409. Applies to every state-changing operation."
    PRD §2.9: "**Rate under the cap** — `ERR_SURCHARGE_CAP_EXCEEDED`, 422. Applies to rate-rule filing."

    Design: Difficulty/priority_pair_validation_conflict/rate_rule_state_check_beats_cap_check_on_withdrawn_program
    """
    ctx = setup_draft_program(with_rate_rule=False)
    program_id = ctx["program"]["id"]
    withdrawn = program_status_action(
        program_id, "WITHDRAW", reason="merchant abandoned the programme"
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["effective_cap_pct"] == pytest.approx(2.19, abs=0.0001)

    response = api_client.create_rate_rule(
        program_id,
        {
            "brand": "VISA",
            "product_tier": "ALL",
            "rate_pct": 9.0,
            "effective_from": CLOCK_AUG_01,
            "effective_to": CLOCK_DEC_31,
            "expected_program_version": withdrawn["version"],
        },
        OFFICER_ONE,
    )
    body = validate_error(response, ApiErrorId.ERR_INVALID_PROGRAM_STATE)
    assert body["error_id"] != ApiErrorId.ERR_SURCHARGE_CAP_EXCEEDED


def test_the_rejected_filing_on_a_withdrawn_program_leaves_the_rate_table_empty(api):
    """PRD §3.4: "Filing carries the `expected_program_version` guard of §2.7 and is refused on a program whose pinned documentation has been superseded, with `ERR_COST_DOCUMENTATION_STALE`, or on a program that has been withdrawn, with `ERR_INVALID_PROGRAM_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/rate_rule_state_check_beats_cap_check_on_withdrawn_program
    """
    ctx = setup_draft_program(with_rate_rule=False)
    program_id = ctx["program"]["id"]
    withdrawn = program_status_action(
        program_id, "WITHDRAW", reason="merchant abandoned the programme"
    )

    api_client.create_rate_rule(
        program_id,
        {
            "brand": "VISA",
            "product_tier": "ALL",
            "rate_pct": 9.0,
            "effective_from": CLOCK_AUG_01,
            "effective_to": CLOCK_DEC_31,
            "expected_program_version": withdrawn["version"],
        },
        OFFICER_ONE,
    )

    assert (
        list_total(api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program_id}))
        == 0
    )
    program = read_program(program_id)
    assert program["status"] == "WITHDRAWN"
    assert program["effective_cap_pct"] == pytest.approx(2.19, abs=0.0001)


def test_debit_surcharge_is_reported_ahead_of_the_wrong_program_binding(api):
    """PRD §2.9: "**Credit-only surcharging at the terminal** — `requested_surcharge_cents` is 0 whenever `card_funding` is `DEBIT` or `PREPAID`: `ERR_DEBIT_SURCHARGE_FORBIDDEN`, 422. Applies to sale capture."
    PRD §2.9: "**Terminal-program agreement** — the terminal's `program_id` equals the body `program_id`: `ERR_TERMINAL_PROGRAM_MISMATCH`, 422. Applies to sale capture and to terminal configuration."

    Design: Difficulty/priority_pair_validation_conflict/transaction_debit_safety_beats_terminal_program_mismatch
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=1, serial_prefix="T-AZ-")
    other_program = create_program(
        ctx["merchant"]["id"],
        ctx["jurisdiction"]["id"],
        ctx["cost_documentation"]["id"],
        "SURCHARGE",
        "PRODUCT_LEVEL",
    )
    assert other_program["status"] == "DRAFT"

    response = api_client.create_transaction(
        {
            "terminal_id": ctx["terminal"]["id"],
            "program_id": other_program["id"],
            "card_brand": "VISA",
            "card_funding": "DEBIT",
            "product_tier": "NOT_APPLICABLE",
            "base_amount_cents": 10000,
            "requested_surcharge_cents": 500,
            "receipt_line_present": True,
        },
        {"X-User-ID": ctx["terminal"]["id"], "X-User-Role": "TerminalAgent"},
    )
    body = validate_error(response, ApiErrorId.ERR_DEBIT_SURCHARGE_FORBIDDEN)
    assert body["error_id"] != ApiErrorId.ERR_TERMINAL_PROGRAM_MISMATCH


def test_a_rejected_capture_moves_neither_the_ledger_nor_the_terminal(api):
    """PRD §2.9: "Second, because the credit-only check at step 18 precedes the rate-selection check at step 34, a terminal that reports a positive surcharge on a debit card is told that debit surcharging is forbidden rather than being told no rate rule was found."

    Design: Difficulty/priority_pair_validation_conflict/transaction_debit_safety_beats_terminal_program_mismatch
    """
    ctx = setup_enforcing_surcharge_estate(terminal_count=1, serial_prefix="T-AZ-")
    other_program = create_program(
        ctx["merchant"]["id"],
        ctx["jurisdiction"]["id"],
        ctx["cost_documentation"]["id"],
        "SURCHARGE",
        "PRODUCT_LEVEL",
    )

    api_client.create_transaction(
        {
            "terminal_id": ctx["terminal"]["id"],
            "program_id": other_program["id"],
            "card_brand": "VISA",
            "card_funding": "DEBIT",
            "product_tier": "NOT_APPLICABLE",
            "base_amount_cents": 10000,
            "requested_surcharge_cents": 500,
            "receipt_line_present": True,
        },
        {"X-User-ID": ctx["terminal"]["id"], "X-User-Role": "TerminalAgent"},
    )

    assert (
        list_total(
            api_client.list_transactions(ADMIN, params={"terminal_id": ctx["terminal"]["id"]})
        )
        == 0
    )
    assert read_merchant(ctx["merchant"]["id"])["gross_surcharge_collected_cents"] == 0
    assert read_terminal(ctx["terminal"]["id"])["state"] == "ENFORCING"


def test_a_rate_exactly_at_the_network_ceiling_is_admitted(api):
    """PRD §3.3: "Whichever of the three is smallest binds — a merchant whose documented cost is 2.19 percent is capped at 2.19 even in a state that permits four, while a merchant whose documented cost is 3.05 percent is capped at 3.0 by the network ceiling."
    PRD §3.3: "The cap is inclusive: a rate rule whose rate exactly equals the cap is admissible."

    Design: Difficulty/boundary_precision_check/rate_at_network_ceiling_passes_and_one_ten_thousandth_over_fails
    """
    ctx = setup_draft_program(doc_profile="docB", with_rate_rule=False)
    assert ctx["cost_documentation"]["documented_cost_pct"] == pytest.approx(3.05, abs=0.00001)
    assert ctx["program"]["effective_cap_pct"] == pytest.approx(3.0, abs=0.00001)

    created = validate_success(
        api_client.create_rate_rule(
            ctx["program"]["id"],
            {
                "brand": "VISA",
                "product_tier": "ALL",
                "rate_pct": 3.0,
                "effective_from": CLOCK_AUG_01,
                "effective_to": CLOCK_DEC_31,
                "expected_program_version": ctx["program"]["version"],
            },
            OFFICER_ONE,
        ),
        expected_status=201,
    )
    assert created["rate_pct"] == pytest.approx(3.0, abs=0.00001)


def test_one_ten_thousandth_above_the_ceiling_is_refused(api):
    """PRD §3.4: "A `rate_pct` at most `effective_cap_pct` is admitted, with equality passing; a `rate_pct` strictly greater than `effective_cap_pct` is rejected with `ERR_SURCHARGE_CAP_EXCEEDED`."
    PRD §3.3: "Because all three inputs already carry four decimal places, taking the minimum introduces no further rounding."

    Design: Difficulty/boundary_precision_check/rate_at_network_ceiling_passes_and_one_ten_thousandth_over_fails
    """
    ctx = setup_draft_program(doc_profile="docB", with_rate_rule=False)
    program_id = ctx["program"]["id"]
    validate_success(
        api_client.create_rate_rule(
            program_id,
            {
                "brand": "VISA",
                "product_tier": "ALL",
                "rate_pct": 3.0,
                "effective_from": CLOCK_AUG_01,
                "effective_to": CLOCK_DEC_31,
                "expected_program_version": ctx["program"]["version"],
            },
            OFFICER_ONE,
        ),
        expected_status=201,
    )

    program = read_program(program_id)
    response = api_client.create_rate_rule(
        program_id,
        {
            "brand": "MASTERCARD",
            "product_tier": "ALL",
            "rate_pct": 3.0001,
            "effective_from": CLOCK_AUG_01,
            "effective_to": CLOCK_DEC_31,
            "expected_program_version": program["version"],
        },
        OFFICER_ONE,
    )
    validate_error(response, ApiErrorId.ERR_SURCHARGE_CAP_EXCEEDED)

    assert (
        list_total(api_client.list_rate_rules(OFFICER_ONE, params={"program_id": program_id}))
        == 1
    )
    assert (
        list_total(
            api_client.list_rate_rules(
                OFFICER_ONE, params={"program_id": program_id, "brand": "MASTERCARD"}
            )
        )
        == 0
    )


def test_a_program_with_three_requirements_and_no_artifacts_cannot_activate(api):
    """PRD §3.6: "A program with no attested artifacts at all and a non-empty required set yields false, and activation in that condition fails with `ERR_DISCLOSURE_INCOMPLETE`."
    PRD §3.6: "For a `SURCHARGE` program: if the jurisdiction's `disclosure_signage_required` is true, both `ENTRY_SIGNAGE` and `POS_SIGNAGE` are required; if its `receipt_line_item_required` is true, `RECEIPT_TEMPLATE` is required as well."

    Design: Difficulty/boundary_precision_check/empty_required_artifact_set_activates_while_zero_attested_fails
    """
    ctx = setup_program_with_effective_registration(
        jurisdiction_profile="NY", legal_name="Hudson Goods Inc", mcc="5999"
    )
    program_id = ctx["program"]["id"]
    assert (
        list_total(
            api_client.list_disclosure_artifacts(ADMIN, params={"program_id": program_id})
        )
        == 0
    )

    response = api_client.activate_program(program_id, OFFICER_ONE)
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_INCOMPLETE)

    program = read_program(program_id)
    assert program["status"] == "PENDING_REGISTRATION"
    assert program["disclosure_ready"] is False
    assert program["activated_at"] is None


def test_an_empty_required_set_makes_readiness_vacuously_true(api):
    """PRD §3.6: "An empty required set — the case of a jurisdiction with every disclosure flag false — yields true vacuously."
    PRD §3.7: "`activated_at` is stamped from the logical clock and `activated_by_user_id` from the acting `X-User-ID`; `disable_reason` is set to `NONE`; `effective_cap_pct` is recomputed through the arm of the cap calculation matching the program's `program_type`; `disclosure_ready` is recomputed; and the program's `version` is bumped by 1."

    Design: Difficulty/boundary_precision_check/empty_required_artifact_set_activates_while_zero_attested_fails
    """
    ctx = setup_program_with_effective_registration(jurisdiction_profile="AZ")
    program_id = ctx["program"]["id"]
    assert (
        list_total(
            api_client.list_disclosure_artifacts(ADMIN, params={"program_id": program_id})
        )
        == 0
    )

    activated = activate_program(program_id)
    assert activated["status"] == "ACTIVE"
    assert activated["disclosure_ready"] is True
    assert activated["disable_reason"] == "NONE"
    assert activated["activated_at"] == TS_AUG_31
    assert activated["activated_by_user_id"] == "officer-1"
