"""Cross-entity gates on three different entity pairs (PRD §3.4, §3.8, §3.9).

Queue A — rule ``cross_entity_state_dependency``: the write targets one entity
but admissibility is decided by a state field of another. A layer submission
turns on the *market's* ``security_status``, a remittance settlement turns on the
*program's* ``documentation_status``, and a claim notification turns on the
*layer's* status. Each pair is probed on both sides of the flip.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    TEST_USERS,
    acknowledge_disclosure,
    api_client,
    approve_transaction,
    assert_instant_equals,
    assert_is_null,
    assert_money_equals,
    assert_status,
    bind_program,
    book_transaction,
    create_claim_advocacy_payload,
    create_market_submission_payload,
    file_document,
    list_rows,
    read_layer,
    read_market_submission,
    read_program,
    read_reinsurer,
    read_transaction,
    refresh,
    send_submission,
    set_market_security,
    settle_cedent_receipt,
    settle_transaction,
    setup_bound_program,
    setup_firm_ordered_layer,
    setup_program_in_market,
    submit_to_market,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["placement_lead_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]

# Instance 1 — the (Layer, Reinsurer) pair. India Re is the market whose posture
# moves; Juliet Re only proves the layer itself can take submissions.
INDIA_AND_JULIET_SPECS = [
    {
        "name": "India Re",
        "security_rating": "A",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 40.0000,
        "lead_authorised": False,
    },
    {
        "name": "Juliet Re",
        "security_rating": "AA",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 60.0000,
        "lead_authorised": True,
    },
]

# Instances 2 and 3 — Echo Re writes the whole canonical catastrophe layer, whose
# frozen gross premium is 97,125,000. At 2.5000% brokerage the single bound line
# yields brokerage 2,428,125 and net remittance 94,696,875.
ECHO_MARKET_SPECS = [
    {
        "name": "Echo Re",
        "security_rating": "AA",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    }
]
CAT_GROSS_PREMIUM_MINOR = 97_125_000
CAT_BROKERAGE_MINOR = 2_428_125
CAT_NET_REMITTANCE_MINOR = 94_696_875

# The claim the two cover-gate tests notify: inside the half-open treaty period
# and piercing the 2,000,000,000 attachment by 600,000,000.
EARLY_CLAIM = {
    "claim_reference": "CL-2026-EARLY-001",
    "event_date": "2026-06-01T00:00:00.000Z",
    "gross_claim_minor": 2_600_000_000,
}
EARLY_CLAIM_CEDED_MINOR = 600_000_000


def _layer_in_market_with_juliet_served():
    """A CATASTROPHE layer carried OPEN -> IN_MARKET by Juliet Re's submission."""
    ctx = setup_program_in_market(
        market_specs=INDIA_AND_JULIET_SPECS,
        program_overrides={"program_name": "Northwind Property CAT 2026"},
        submission_overrides={"package_label": "NW-CAT-2026-EDP"},
    )
    ctx["juliet_submission"] = send_submission(ctx, market_index=1)
    return refresh(ctx)


def _slip_only_program_with_an_approved_remittance():
    """A funded BOUND program at SLIP_ISSUED carrying one APPROVED remittance."""
    ctx = setup_bound_program(
        market_specs=ECHO_MARKET_SPECS,
        program_overrides={"program_name": "Northwind Property CAT 2026"},
        submission_overrides={"package_label": "NW-CAT-2026-EDP"},
    )
    ctx["documents"] = [file_document(ctx["program"]["id"], "SLIP", "NW-CAT-2026-SLIP")]
    ctx["receipt"] = settle_cedent_receipt(ctx["program"]["id"], CAT_GROSS_PREMIUM_MINOR)
    remittance = book_transaction(
        ctx["program"]["id"],
        "REINSURER_REMITTANCE",
        CAT_NET_REMITTANCE_MINOR,
        signing_line_id=ctx["signing_lines"][0]["id"],
    )
    approve_transaction(remittance["id"])
    ctx["remittance"] = read_transaction(remittance["id"])
    return refresh(ctx)


def test_a_suspended_market_cannot_receive_a_submission_on_a_layer_already_in_market():
    """India Re is suspended between go-to-market and the submission, so the send fails.

    PRD: "The target market's `security_status` must not be `SUSPENDED`, else
    `ERR_MARKET_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/layer_cannot_be_submitted_to_a_market_whose_security_status_is_suspended
    """
    ctx = _layer_in_market_with_juliet_served()
    india = ctx["reinsurers"][0]

    suspended = set_market_security(
        india["id"], "SUSPENDED", "regulatory intervention in domicile"
    )
    assert_status(suspended, "security_status", "SUSPENDED")

    response = api_client.create_market_submission(
        ctx["layer"]["id"],
        create_market_submission_payload(
            india["id"], response_deadline=CLOCK["RESPONSE_DEADLINE"]
        ),
        LEAD,
    )

    validate_error(response, ApiErrorId.ERR_MARKET_SUSPENDED.value)

    assert_status(read_reinsurer(india["id"]), "security_status", "SUSPENDED")
    assert_status(read_layer(ctx["layer"]["id"]), "status", "IN_MARKET")
    assert_status(read_market_submission(ctx["juliet_submission"]["id"]), "status", "SENT")

    rows = list_rows(api_client.list_reinsurer_market_submissions(india["id"], LEAD))
    assert rows == [], f"India Re must hold no market submission at all, got {rows!r}"


def test_a_restricted_market_still_receives_the_very_same_submission():
    """The gate keys on SUSPENDED alone, so a RESTRICTED India Re is served.

    PRD: "The three postures differ in what they permit: an `APPROVED` market may
    both lead and follow, a `RESTRICTED` market may follow but never lead, and a
    `SUSPENDED` market may not receive submissions at all and triggers the
    security cascade described in §3.5."

    Design: Difficulty/cross_entity_state_dependency/layer_cannot_be_submitted_to_a_market_whose_security_status_is_suspended
    """
    ctx = _layer_in_market_with_juliet_served()
    india = ctx["reinsurers"][0]

    restricted = set_market_security(
        india["id"], "RESTRICTED", "watchlist pending rating review"
    )
    assert_status(restricted, "security_status", "RESTRICTED")

    market_submission = submit_to_market(
        ctx["layer"]["id"], india["id"], response_deadline=CLOCK["RESPONSE_DEADLINE"]
    )

    assert_status(market_submission, "status", "SENT")
    assert market_submission["reinsurer_id"] == india["id"], (
        "the submission must address India Re, got "
        f"{market_submission['reinsurer_id']!r}"
    )
    assert_instant_equals(
        market_submission["response_deadline"],
        CLOCK["RESPONSE_DEADLINE"],
        "response_deadline",
    )
    assert_status(read_layer(ctx["layer"]["id"]), "status", "IN_MARKET")
    assert_status(read_market_submission(ctx["juliet_submission"]["id"]), "status", "SENT")

    rows = list_rows(api_client.list_reinsurer_market_submissions(india["id"], LEAD))
    assert len(rows) == 1, f"India Re must hold exactly one submission, got {len(rows)}"
    assert rows[0]["id"] == market_submission["id"], (
        f"the listed submission must be the one just sent, got {rows[0]['id']!r}"
    )


def test_approved_remittance_cannot_settle_while_the_program_only_has_a_slip():
    """The money is on hand and the movement is APPROVED, but the program lacks agreed wording.

    PRD: "For the two premium out-payment types, `REINSURER_REMITTANCE` and
    `REINSTATEMENT_PREMIUM`, the program's `documentation_status` must be
    `WORDING_AGREED` or `EXECUTED`, else `ERR_DOCUMENTATION_NOT_AGREED` — this is
    the contract-certainty gate of §3.7 expressed as a payment control."

    Design: Difficulty/cross_entity_state_dependency/remittance_cannot_settle_while_the_owning_program_documentation_is_only_slip_issued
    """
    ctx = _slip_only_program_with_an_approved_remittance()
    remittance = ctx["remittance"]

    funded = read_program(ctx["program"]["id"])
    assert_money_equals(
        funded["fiduciary_holding_minor"],
        CAT_GROSS_PREMIUM_MINOR,
        "fiduciary_holding_minor before the attempt",
    )
    assert_status(funded, "documentation_status", "SLIP_ISSUED")
    assert_status(remittance, "status", "APPROVED")

    response = api_client.settle_fiduciary_transaction(remittance["id"], ACCOUNTANT)

    validate_error(response, ApiErrorId.ERR_DOCUMENTATION_NOT_AGREED.value)

    blocked = read_transaction(remittance["id"])
    assert_status(blocked, "status", "APPROVED")
    assert_is_null(blocked, "value_date")
    assert_money_equals(
        blocked["amount_minor"], CAT_NET_REMITTANCE_MINOR, "remittance amount_minor"
    )

    program = read_program(ctx["program"]["id"])
    assert_status(program, "documentation_status", "SLIP_ISSUED")
    assert_money_equals(
        program["fiduciary_holding_minor"],
        CAT_GROSS_PREMIUM_MINOR,
        "fiduciary_holding_minor after the refusal",
    )
    assert_money_equals(
        program["net_remittance_minor"], CAT_NET_REMITTANCE_MINOR, "net_remittance_minor"
    )
    assert_money_equals(
        program["brokerage_earned_minor"], CAT_BROKERAGE_MINOR, "brokerage_earned_minor"
    )


def test_the_same_remittance_settles_once_the_program_reaches_wording_agreed():
    """Filing the wording draft and the agreed wording opens the gate for the same movement.

    PRD: "For the two premium out-payment types, `REINSURER_REMITTANCE` and
    `REINSTATEMENT_PREMIUM`, the program's `documentation_status` must be
    `WORDING_AGREED` or `EXECUTED`, else `ERR_DOCUMENTATION_NOT_AGREED` — this is
    the contract-certainty gate of §3.7 expressed as a payment control."

    Design: Difficulty/cross_entity_state_dependency/remittance_cannot_settle_while_the_owning_program_documentation_is_only_slip_issued
    """
    ctx = _slip_only_program_with_an_approved_remittance()
    remittance = ctx["remittance"]

    file_document(ctx["program"]["id"], "WORDING_DRAFT", "NW-CAT-2026-WORDING")
    file_document(ctx["program"]["id"], "AGREED_WORDING", "NW-CAT-2026-WORDING")

    agreed = read_program(ctx["program"]["id"])
    assert_status(agreed, "documentation_status", "WORDING_AGREED")
    assert_money_equals(
        agreed["fiduciary_holding_minor"],
        CAT_GROSS_PREMIUM_MINOR,
        "fiduciary_holding_minor before settlement",
    )

    settled = settle_transaction(remittance["id"])

    assert_status(settled, "status", "SETTLED")
    assert_instant_equals(settled["value_date"], CLOCK["PLACEMENT_START"], "value_date")
    assert_money_equals(
        settled["amount_minor"], CAT_NET_REMITTANCE_MINOR, "settled amount_minor"
    )

    program = read_program(ctx["program"]["id"])
    assert_money_equals(
        program["fiduciary_holding_minor"],
        CAT_BROKERAGE_MINOR,
        "fiduciary_holding_minor after the remittance leaves",
    )
    assert_status(program, "documentation_status", "WORDING_AGREED")
    assert_money_equals(
        program["net_remittance_minor"], CAT_NET_REMITTANCE_MINOR, "net_remittance_minor"
    )


def test_claim_cannot_be_notified_against_a_layer_that_is_only_fully_placed():
    """Echo Re wrote the whole line, but the unacknowledged disclosure left the layer unbound.

    PRD: "The layer must be `BOUND`, else `ERR_LAYER_NOT_BOUND` — an unbound layer
    has no contract to claim under."

    Design: Difficulty/cross_entity_state_dependency/claim_cannot_be_notified_against_a_layer_that_is_only_fully_placed
    """
    ctx = setup_firm_ordered_layer(
        market_specs=ECHO_MARKET_SPECS,
        program_overrides={"program_name": "Northwind Property CAT 2026"},
        submission_overrides={"package_label": "NW-CAT-2026-EDP"},
    )

    placed = read_layer(ctx["layer"]["id"])
    assert_status(placed, "status", "FULLY_PLACED")
    assert_money_equals(placed["limit_eroded_minor"], 0, "limit_eroded_minor")

    response = api_client.create_claim_advocacy(
        ctx["layer"]["id"], create_claim_advocacy_payload(**EARLY_CLAIM), LEAD
    )

    validate_error(response, ApiErrorId.ERR_LAYER_NOT_BOUND.value)

    layer = read_layer(ctx["layer"]["id"])
    assert_status(layer, "status", "FULLY_PLACED")
    assert_money_equals(layer["limit_eroded_minor"], 0, "limit_eroded_minor after the refusal")

    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "FIRM_ORDER")
    assert program["disclosure_acknowledged"] is False, (
        "the disclosure was never acknowledged, so disclosure_acknowledged must be false, got "
        f"{program['disclosure_acknowledged']!r}"
    )

    rows = list_rows(api_client.list_layer_claim_advocacies(ctx["layer"]["id"], LEAD))
    assert rows == [], f"no advocacy may have been created, got {rows!r}"


def test_the_same_claim_is_admitted_once_the_disclosure_is_acknowledged_and_the_program_bound():
    """Acknowledging the disclosure and binding turns the layer BOUND, so cover exists.

    PRD: "The layer must be `BOUND`, else `ERR_LAYER_NOT_BOUND` — an unbound layer
    has no contract to claim under."

    Design: Difficulty/cross_entity_state_dependency/claim_cannot_be_notified_against_a_layer_that_is_only_fully_placed
    """
    ctx = setup_firm_ordered_layer(
        market_specs=ECHO_MARKET_SPECS,
        program_overrides={"program_name": "Northwind Property CAT 2026"},
        submission_overrides={"package_label": "NW-CAT-2026-EDP"},
    )

    acknowledge_disclosure(
        ctx["program"]["id"], ctx["cedent"]["id"], ctx["program"]["brokerage_pct"]
    )
    bound_program = bind_program(ctx["program"]["id"])
    assert_status(bound_program, "placement_status", "BOUND")
    assert bound_program["disclosure_acknowledged"] is True, (
        "the cedent acknowledged the disclosure, so disclosure_acknowledged must be true, got "
        f"{bound_program['disclosure_acknowledged']!r}"
    )
    assert_status(read_layer(ctx["layer"]["id"]), "status", "BOUND")

    response = api_client.create_claim_advocacy(
        ctx["layer"]["id"], create_claim_advocacy_payload(**EARLY_CLAIM), LEAD
    )

    advocacy = validate_success(response, 201)
    assert_status(advocacy, "status", "NOTIFIED")
    assert advocacy["claim_reference"] == EARLY_CLAIM["claim_reference"], (
        f"claim_reference must be preserved, got {advocacy['claim_reference']!r}"
    )
    assert_instant_equals(advocacy["event_date"], EARLY_CLAIM["event_date"], "event_date")
    assert_money_equals(
        advocacy["ceded_claim_minor"], EARLY_CLAIM_CEDED_MINOR, "ceded_claim_minor"
    )

    rows = list_rows(api_client.list_layer_claim_advocacies(ctx["layer"]["id"], LEAD))
    assert len(rows) == 1, f"exactly one advocacy must exist, got {len(rows)}"
