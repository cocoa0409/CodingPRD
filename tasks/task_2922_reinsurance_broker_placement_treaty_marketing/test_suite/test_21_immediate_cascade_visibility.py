"""Immediate consistency across a whole placement (PRD §2.9, §3.2–§3.8).

Queue B — section ``consistency_model``: every derived field and every cascaded
status is already correct in the body of the response that caused it, and the
first read afterwards returns the same values with no second write, including the
hops whose cascade lands on an entity that is not the response's output entity.
"""
from test_helpers import (
    acknowledge_disclosure,
    approve_transaction,
    assert_capacity_invariants,
    assert_is_null,
    assert_money_equals,
    assert_pct_equals,
    assert_placement_money_invariants,
    assert_score_equals,
    assert_status,
    bind_program,
    book_transaction,
    create_disclosure,
    create_layer,
    decide_disclosure,
    disclose,
    file_document,
    firm_order,
    go_to_market,
    read_cedent,
    read_disclosure,
    read_layer,
    read_program,
    read_quote,
    read_reinsurer,
    read_signing_line,
    read_submission,
    setup_bound_program,
    setup_draft_program,
    setup_firm_ordered_layer,
    setup_program_in_market,
    setup_quoted_layer,
    setup_submission_ready_program,
    settle_transaction,
    signoff,
    submit_for_review,
    submit_to_market,
)

# The Immediate Mutual placement: one cedent, one market big enough to take the
# whole 1,000,000,000 layer, and the canonical CAT layer whose frozen technical
# premium is 97,125,000 minor units.
IM_CEDENT = {"name": "Immediate Mutual", "domicile_code": "USNYC", "financial_rating": "A"}
IM_MARKET_SPEC = {
    "name": "Alpha Re",
    "security_rating": "AA",
    "capacity_limit_minor": 5_000_000_000,
    "max_line_pct": 100.0000,
    "lead_authorised": True,
}
IM_PROGRAM = {
    "program_name": "Immediate Property CAT 2026",
    "line_of_business": "PROPERTY",
    "underwriting_year": 2026,
    "estimated_premium_income_minor": 2_000_000_000,
    "brokerage_pct": 2.5000,
}
IM_PACKAGE = {"package_label": "IM-EDP-1"}
IM_LAYER = {"layer_label": "IM CAT 1B xs 2B"}
IM_QUOTE = {
    "offered_line_pct": 100.0000,
    "quoted_rate_pct": 8.0000,
    "ceding_commission_pct": 0.0000,
    "reinstatements_offered": 1,
    "sublimit_minor": 0,
    "expires_at": "2026-03-01T00:00:00.000Z",
    "is_lead": True,
}
IM_DISCLOSURE = {
    "brokerage_pct": 2.5000,
    "contingent_commission_pct": 0.0000,
    "market_service_fee_minor": 0,
}

# Every pinned figure of the chain: the package scores 96.70, the layer prices at
# 97,125,000, and a 2.5000% brokerage on a single 100% line splits that premium
# into 2,428,125 of brokerage and 94,696,875 of net remittance with no residue.
PACKAGE_SCORE = 96.70
LAYER_LIMIT_MINOR = 1_000_000_000
MARKET_CAPACITY_MINOR = 5_000_000_000
PREMIUM_MINOR = 97_125_000
BROKERAGE_MINOR = 2_428_125
NET_REMITTANCE_MINOR = 94_696_875
MONEY_FIELDS = (
    "gross_written_premium_minor",
    "brokerage_earned_minor",
    "net_remittance_minor",
    "rounding_residue_minor",
)


def _chain_kwargs(**extra):
    """The Immediate Mutual parameters, freshly copied for one chain builder call."""
    kwargs = {
        "cedent_overrides": dict(IM_CEDENT),
        "market_specs": [dict(IM_MARKET_SPEC)],
        "program_overrides": dict(IM_PROGRAM),
        "submission_overrides": dict(IM_PACKAGE),
        "layer_overrides": dict(IM_LAYER),
    }
    kwargs.update(extra)
    return kwargs


def test_the_completeness_score_is_already_final_in_the_response_that_computed_it():
    """96.70 is in the create body, in the first read, and again after submit-for-review.

    PRD: "A `completeness_score` is computed on creation, recomputed whenever the
    cedent revises the package, and recomputed again when the package is submitted
    for review, so the score an actuary sees is always current."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_draft_program(**_chain_kwargs(with_layer=False))
    created = ctx["submission"]

    assert_score_equals(created["completeness_score"], PACKAGE_SCORE, "score in the write")
    assert_status(created, "status", "DRAFT")

    first_read = read_submission(created["id"])
    assert_score_equals(
        first_read["completeness_score"], PACKAGE_SCORE, "score on the first read"
    )

    reviewed = submit_for_review(created["id"])
    assert_status(reviewed, "status", "ACTUARY_REVIEW")
    assert_score_equals(
        reviewed["completeness_score"], PACKAGE_SCORE, "score in the review response"
    )
    assert_score_equals(
        read_submission(created["id"])["completeness_score"],
        PACKAGE_SCORE,
        "score after the review",
    )


def test_the_signoff_bubbles_up_onto_the_program_before_the_very_next_read():
    """The signoff body says SIGNED_OFF and the program is already SUBMISSION_READY.

    PRD: "And the program's `placement_status` bubbles up from `DRAFT` to
    `SUBMISSION_READY`, with the program's `version` incremented."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_draft_program(**_chain_kwargs())
    program_id = ctx["program"]["id"]
    submit_for_review(ctx["submission"]["id"])
    before = read_program(program_id)
    assert_status(before, "placement_status", "DRAFT")

    signed = signoff(ctx["submission"]["id"])
    assert_status(signed, "status", "SIGNED_OFF")

    after = read_program(program_id)
    assert_status(after, "placement_status", "SUBMISSION_READY")
    assert after["version"] == before["version"] + 1, (
        f"expected the program version to move {before['version']} -> "
        f"{before['version'] + 1}, got {after['version']}"
    )


def test_the_technical_premium_is_derived_inside_the_layer_create_response():
    """97,125,000 is in the create body and unchanged on the immediate re-read.

    PRD: "It is computed when the layer is created, recomputed on every restructure
    while the layer is still `OPEN`, and then **frozen for ever** the moment the
    layer goes to market."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_submission_ready_program(**_chain_kwargs(with_layer=False))

    layer = create_layer(ctx["program"]["id"], **IM_LAYER)

    assert_money_equals(
        layer["quoted_gross_premium_minor"], PREMIUM_MINOR, "premium in the write"
    )
    assert_status(layer, "status", "OPEN")

    first_read = read_layer(layer["id"])
    assert_money_equals(
        first_read["quoted_gross_premium_minor"], PREMIUM_MINOR, "premium on the first read"
    )
    assert first_read["version"] == layer["version"], (
        "reading the layer must not itself write anything"
    )


def test_the_release_to_market_carries_the_new_placement_status_in_its_own_response():
    """go-to-market answers with IN_MARKET already set and the version already moved.

    PRD: "Once the actuary has opened the marketing window, the placing broker
    releases the program to market, advancing `placement_status` from
    `SUBMISSION_READY` to `IN_MARKET`."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_submission_ready_program(**_chain_kwargs())
    program_id = ctx["program"]["id"]
    before = read_program(program_id)
    assert_status(before, "placement_status", "SUBMISSION_READY")

    released = go_to_market(program_id)

    assert_status(released, "placement_status", "IN_MARKET")
    assert released["version"] == before["version"] + 1, (
        f"expected version {before['version'] + 1} in the go-to-market body, "
        f"got {released['version']}"
    )
    after = read_program(program_id)
    assert_status(after, "placement_status", "IN_MARKET")
    assert after["version"] == released["version"], (
        "the read must agree with the body of the write that caused the change"
    )
    assert_status(read_layer(ctx["layer"]["id"]), "status", "OPEN")


def test_the_first_market_submission_has_already_moved_the_layer_when_it_answers():
    """The submission answers SENT while the layer is already IN_MARKET one version on.

    PRD: "The **first** submission on a layer also carries the layer from `OPEN` to
    `IN_MARKET`, which is the moment `quoted_gross_premium_minor` is frozen, and
    increments the layer's `version`."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_program_in_market(**_chain_kwargs())
    layer_before = read_layer(ctx["layer"]["id"])
    assert_status(layer_before, "status", "OPEN")

    market_submission = submit_to_market(layer_before["id"], ctx["reinsurer"]["id"])

    assert_status(market_submission, "status", "SENT")
    assert market_submission["layer_id"] == layer_before["id"], (
        "the submission answers with the layer it was sent on"
    )
    layer_after = read_layer(layer_before["id"])
    assert_status(layer_after, "status", "IN_MARKET")
    assert layer_after["version"] == layer_before["version"] + 1, (
        f"expected the layer version to move {layer_before['version']} -> "
        f"{layer_before['version'] + 1}, got {layer_after['version']}"
    )
    assert_money_equals(
        layer_after["quoted_gross_premium_minor"],
        PREMIUM_MINOR,
        "the premium frozen by the first submission",
    )


def test_the_acknowledgement_flips_the_flag_on_a_different_entity_in_the_same_cycle():
    """The decision body says ACKNOWLEDGED and the program flag is already true.

    PRD: "`ACKNOWLEDGE` moves the disclosure to `ACKNOWLEDGED`, which is terminal,
    and sets the program's `disclosure_acknowledged` flag to true — the flag that
    unblocks binding."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_quoted_layer(quote_overrides=dict(IM_QUOTE), **_chain_kwargs())
    program_id = ctx["program"]["id"]
    disclosure = create_disclosure(program_id, **IM_DISCLOSURE)
    disclose(disclosure["id"])
    assert read_program(program_id)["disclosure_acknowledged"] is False, (
        "the flag stays false until the cedent acknowledges"
    )

    decided = decide_disclosure(
        disclosure["id"], ctx["cedent"]["id"], "ACKNOWLEDGE", decision_note="Understood"
    )

    assert_status(decided, "status", "ACKNOWLEDGED")
    assert read_program(program_id)["disclosure_acknowledged"] is True, (
        "the flag on the program is already true on the immediately following read"
    )
    assert_status(read_disclosure(disclosure["id"]), "status", "ACKNOWLEDGED")


def test_the_firm_order_answers_with_the_signing_line_it_has_already_created():
    """The firm-order body is a PROVISIONAL line written at 100.0000 with no signed line.

    PRD: "The first hop creates a signing line whose `layer_id`, `quote_id` and
    `reinsurer_id` identify the layer, the quote and the market, whose
    `written_line_pct` is copied from the `accepted_line_pct` just accepted and is
    **never mutated again**, whose `signed_line_pct` is null, and whose status is
    `PROVISIONAL`."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_quoted_layer(quote_overrides=dict(IM_QUOTE), **_chain_kwargs())
    layer_id = ctx["layer"]["id"]
    quote_id = ctx["quote"]["id"]

    signing_line = firm_order(quote_id, 100.0000, layer_id=layer_id)

    assert signing_line["layer_id"] == layer_id, "the line identifies its layer"
    assert signing_line["quote_id"] == quote_id, "the line identifies its quote"
    assert signing_line["reinsurer_id"] == ctx["reinsurer"]["id"], (
        "the line identifies the market that wrote it"
    )
    assert_pct_equals(signing_line["written_line_pct"], 100.0000, "written_line_pct")
    assert_is_null(signing_line, "signed_line_pct")
    assert_status(signing_line, "status", "PROVISIONAL")

    first_read = read_signing_line(signing_line["id"])
    assert_pct_equals(first_read["written_line_pct"], 100.0000, "written_line_pct on read")
    assert_is_null(first_read, "signed_line_pct")
    assert_status(first_read, "status", "PROVISIONAL")
    assert_status(read_quote(quote_id), "status", "FIRM_ORDER")


def test_the_layer_the_firm_order_did_not_return_is_already_fully_placed():
    """The written total and the compound layer status are correct on the first read.

    PRD: "The second hop recomputes the layer's `written_line_total_pct` — the sum
    of `written_line_pct` over the layer's lines in `PROVISIONAL`, `SIGNED` or
    `BOUND` — and lets the layer's compound status follow from the recomputed total:
    a total greater than `0.0000` but less than `100.0000` leaves the layer
    `PARTIALLY_PLACED`, a total of exactly `100.0000` makes it `FULLY_PLACED`, and a
    total greater than `100.0000` makes it `OVERSUBSCRIBED`."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_quoted_layer(quote_overrides=dict(IM_QUOTE), **_chain_kwargs())
    layer_before = read_layer(ctx["layer"]["id"])
    assert_status(layer_before, "status", "IN_MARKET")
    assert_pct_equals(layer_before["written_line_total_pct"], 0.0000, "written total before")

    firm_order(ctx["quote"]["id"], 100.0000, layer_id=layer_before["id"])

    layer_after = read_layer(layer_before["id"])
    assert_pct_equals(
        layer_after["written_line_total_pct"], 100.0000, "written_line_total_pct"
    )
    assert_status(layer_after, "status", "FULLY_PLACED")
    assert layer_after["version"] == layer_before["version"] + 1, (
        f"expected the layer version to move {layer_before['version']} -> "
        f"{layer_before['version'] + 1}, got {layer_after['version']}"
    )
    assert_money_equals(
        layer_after["quoted_gross_premium_minor"],
        PREMIUM_MINOR,
        "the frozen premium is untouched by the placement cascade",
    )


def test_the_program_two_levels_up_is_already_in_firm_order():
    """Filling the only layer advances the grandparent program in the same request.

    PRD: "The third hop looks up at the program: when every layer of the program
    whose status is not `LAPSED` is either `FULLY_PLACED` or `OVERSUBSCRIBED`, the
    program's `placement_status` advances from `IN_MARKET` to `FIRM_ORDER` and its
    `version` increments."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_quoted_layer(quote_overrides=dict(IM_QUOTE), **_chain_kwargs())
    program_before = read_program(ctx["program"]["id"])
    assert_status(program_before, "placement_status", "IN_MARKET")

    firm_order(ctx["quote"]["id"], 100.0000, layer_id=ctx["layer"]["id"])

    program_after = read_program(program_before["id"])
    assert_status(program_after, "placement_status", "FIRM_ORDER")
    assert program_after["version"] == program_before["version"] + 1, (
        f"expected the program version to move {program_before['version']} -> "
        f"{program_before['version'] + 1}, got {program_after['version']}"
    )


def test_the_markets_capacity_is_refreshed_by_the_line_that_reserved_it():
    """Alpha's committed and available capacity both move on the firm order itself.

    PRD: "A market's `committed_capacity_minor` is that sum and its
    `available_capacity_minor` is its `capacity_limit_minor` less that sum; both are
    refreshed whenever any of its lines is created, signed down or released."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_quoted_layer(quote_overrides=dict(IM_QUOTE), **_chain_kwargs())
    market_before = read_reinsurer(ctx["reinsurer"]["id"])
    assert_money_equals(market_before["committed_capacity_minor"], 0, "committed before")
    assert_money_equals(
        market_before["available_capacity_minor"], MARKET_CAPACITY_MINOR, "available before"
    )

    firm_order(ctx["quote"]["id"], 100.0000, layer_id=ctx["layer"]["id"])

    market_after = read_reinsurer(market_before["id"])
    assert_money_equals(
        market_after["committed_capacity_minor"],
        LAYER_LIMIT_MINOR,
        "committed_capacity_minor",
    )
    assert_money_equals(
        market_after["available_capacity_minor"],
        MARKET_CAPACITY_MINOR - LAYER_LIMIT_MINOR,
        "available_capacity_minor",
    )
    assert_capacity_invariants(market_after)


def test_the_bind_response_already_carries_all_four_money_fields_and_the_read_agrees():
    """97,125,000 splits into 2,428,125 and 94,696,875 with no residue, twice over.

    PRD: "First, cascades are **immediate and complete within the request**: by the
    time a response is returned, every derived field, every dependent status and
    every aggregate named in the cascade has been brought up to date, and a
    subsequent read never sees a half-applied cascade."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_firm_ordered_layer(**_chain_kwargs())
    program_id = ctx["program"]["id"]
    acknowledge_disclosure(program_id, ctx["cedent"]["id"], 2.5000)

    bound = bind_program(program_id)

    assert_status(bound, "placement_status", "BOUND")
    assert_money_equals(
        bound["gross_written_premium_minor"], PREMIUM_MINOR, "gross_written_premium_minor"
    )
    assert_money_equals(
        bound["brokerage_earned_minor"], BROKERAGE_MINOR, "brokerage_earned_minor"
    )
    assert_money_equals(
        bound["net_remittance_minor"], NET_REMITTANCE_MINOR, "net_remittance_minor"
    )
    assert_money_equals(bound["rounding_residue_minor"], 0, "rounding_residue_minor")
    assert_placement_money_invariants(bound)

    first_read = read_program(program_id)
    for field in MONEY_FIELDS:
        assert_money_equals(first_read[field], int(bound[field]), f"{field} on the re-read")
    assert_status(first_read, "placement_status", "BOUND")
    assert first_read["version"] == bound["version"], (
        "nothing converges after the fact, so the version does not move on a read"
    )


def test_binding_has_already_bound_the_layer_it_did_not_return():
    """The bind answers with the program while the layer is already BOUND one version on.

    PRD: "Every layer that is `FULLY_PLACED` or `SIGNED_DOWN` becomes `BOUND` and
    increments its `version`."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_firm_ordered_layer(**_chain_kwargs())
    layer_before = read_layer(ctx["layer"]["id"])
    assert_status(layer_before, "status", "FULLY_PLACED")
    acknowledge_disclosure(ctx["program"]["id"], ctx["cedent"]["id"], 2.5000)

    bound = bind_program(ctx["program"]["id"])
    assert_status(bound, "placement_status", "BOUND")

    layer_after = read_layer(layer_before["id"])
    assert_status(layer_after, "status", "BOUND")
    assert layer_after["version"] == layer_before["version"] + 1, (
        f"expected the layer version to move {layer_before['version']} -> "
        f"{layer_before['version'] + 1}, got {layer_after['version']}"
    )


def test_the_grandchild_signing_line_is_signed_at_its_written_line_and_bound():
    """The provisional line is already BOUND at signed_line_pct 100.0000, as is its quote.

    PRD: "On those layers, each `PROVISIONAL` line — a line on a layer that was never
    signed down, therefore written at exactly the line it was firm-ordered at — has
    its `signed_line_pct` set equal to its `written_line_pct` and then becomes
    `BOUND`; each already-`SIGNED` line simply becomes `BOUND`."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_firm_ordered_layer(**_chain_kwargs())
    line_before = read_signing_line(ctx["signing_lines"][0]["id"])
    assert_status(line_before, "status", "PROVISIONAL")
    assert_is_null(line_before, "signed_line_pct")
    acknowledge_disclosure(ctx["program"]["id"], ctx["cedent"]["id"], 2.5000)

    bind_program(ctx["program"]["id"])

    line_after = read_signing_line(line_before["id"])
    assert_status(line_after, "status", "BOUND")
    assert_pct_equals(line_after["signed_line_pct"], 100.0000, "signed_line_pct")
    assert_pct_equals(
        line_after["written_line_pct"], 100.0000, "written_line_pct is never mutated"
    )
    assert_money_equals(
        line_after["committed_capacity_minor"],
        LAYER_LIMIT_MINOR,
        "committed_capacity_minor",
    )
    assert_status(read_quote(ctx["quotes"][0]["id"]), "status", "BOUND")


def test_the_slip_advances_the_documentation_dimension_and_leaves_the_placement_alone():
    """Filing the slip is SLIP_ISSUED on the next read while placement stays BOUND.

    PRD: "A `SLIP` takes the program from `NOT_STARTED` to `SLIP_ISSUED` and requires
    the program's `placement_status` to be `FIRM_ORDER` or `BOUND` — the slip is the
    record of a placement that actually exists."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_bound_program(**_chain_kwargs())
    program_id = ctx["program"]["id"]
    assert_status(read_program(program_id), "documentation_status", "NOT_STARTED")

    document = file_document(program_id, "SLIP", "IM-SLIP-1")

    assert_status(document, "document_type", "SLIP")
    assert document["program_id"] == program_id, "the slip is filed on this program"

    after = read_program(program_id)
    assert_status(after, "documentation_status", "SLIP_ISSUED")
    assert_status(after, "placement_status", "BOUND")


def test_booking_and_approving_are_visible_at_once_while_the_balance_holds_at_zero():
    """Immediate consistency is not eagerness: the receipt is PENDING and nothing moved.

    PRD: "Movements in `PENDING`, `APPROVED` or `HELD` are invisible to the balance:
    booking, approving and holding a movement never move money."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_bound_program(**_chain_kwargs())
    program_id = ctx["program"]["id"]

    receipt = book_transaction(program_id, "CEDENT_RECEIPT", PREMIUM_MINOR)

    assert_status(receipt, "status", "PENDING")
    assert_money_equals(receipt["amount_minor"], PREMIUM_MINOR, "amount_minor")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        0,
        "fiduciary_holding_minor after booking",
    )

    approved = approve_transaction(receipt["id"])
    assert_status(approved, "status", "APPROVED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        0,
        "fiduciary_holding_minor after approval",
    )


def test_settlement_moves_the_program_balance_inside_its_own_request():
    """The settle body says SETTLED and the program balance is already 97,125,000.

    PRD: "A `BrokerAccountant` settles an `APPROVED` movement, and settlement is
    where the balance actually changes."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_bound_program(**_chain_kwargs())
    program_id = ctx["program"]["id"]
    receipt = book_transaction(program_id, "CEDENT_RECEIPT", PREMIUM_MINOR)
    approve_transaction(receipt["id"])

    settled = settle_transaction(receipt["id"])

    assert_status(settled, "status", "SETTLED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        PREMIUM_MINOR,
        "fiduciary_holding_minor after settlement",
    )


def test_the_cedents_roll_up_is_readable_in_the_same_request_cycle_as_the_settlement():
    """The settled receipt lands on the cedent's settled_receipts_minor immediately.

    PRD: "`settled_receipts_minor` is the sum of `amount_minor` over the cedent's
    movements whose `txn_type` is `CEDENT_RECEIPT` and whose status is `SETTLED` —
    money genuinely received."

    Design: Corner/consistency_model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    ctx = setup_bound_program(**_chain_kwargs())
    cedent_id = ctx["cedent"]["id"]
    receipt = book_transaction(ctx["program"]["id"], "CEDENT_RECEIPT", PREMIUM_MINOR)
    approve_transaction(receipt["id"])
    assert_money_equals(
        read_cedent(cedent_id)["settled_receipts_minor"],
        0,
        "settled_receipts_minor before settlement",
    )

    settle_transaction(receipt["id"])

    assert_money_equals(
        read_cedent(cedent_id)["settled_receipts_minor"],
        PREMIUM_MINOR,
        "settled_receipts_minor",
    )
