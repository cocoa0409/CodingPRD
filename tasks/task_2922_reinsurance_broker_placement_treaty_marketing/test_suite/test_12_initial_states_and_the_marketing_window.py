"""Declared initial states and the opening of the marketing window (PRD §3.1–§3.9).

Queue B — corner section ``state_machines``: every machine of the placement
chain is observed at the state it is declared to enter at, and the
``SUBMISSION_READY`` → ``IN_MARKET`` hop is separated from the layer hop it does
not perform.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_is_null,
    assert_money_equals,
    assert_pct_equals,
    assert_score_equals,
    assert_status,
    assert_version_incremented,
    book_transaction,
    create_disclosure,
    create_exposure_submission,
    create_layer,
    go_to_market,
    notify_claim,
    raise_dispute,
    read_cedent,
    read_layer,
    read_program,
    read_submission,
    review_claim,
    send_submission,
    set_clock,
    setup_bound_program,
    setup_draft_program,
    setup_firm_ordered_layer,
    setup_program_in_market,
    setup_quoted_layer,
    setup_submission_ready_program,
    signoff,
    submit_for_review,
    suspend_cedent,
    validate_error,
    validate_paginated,
)

# The opaque broker identities the chains act with (PRD §2.1).
LEAD_HEADERS = TEST_USERS["placement_lead_headers"]
LEAD_USER_ID = TEST_USERS["placement_lead_headers"]["X-User-ID"]
ACTUARY_USER_ID = TEST_USERS["actuary_headers"]["X-User-ID"]
ACCOUNTANT_USER_ID = TEST_USERS["accountant_headers"]["X-User-ID"]

# The post-binding chains park the clock two months after inception and notify a
# 2,400,000,000 ground-up loss on the canonical 1B xs 2B catastrophe layer, so
# the cession is 400,000,000 and 100,000,000 of it can be disputed (PRD §3.9).
POST_BIND_CLOCK = "2026-03-01T00:00:00.000Z"
CLAIM_EVENT_DATE = "2026-02-20T00:00:00.000Z"
CLAIM_OVERRIDES = {
    "claim_reference": "NW-CAT-CLM-001",
    "event_date": CLAIM_EVENT_DATE,
    "gross_claim_minor": 2_400_000_000,
}
RECEIPT_MINOR = 100_000_000
DISPUTED_MINOR = 100_000_000

# The second exposure package: 10 flags in 1000 records and a 95.0000% loss
# history score 40*0.99 + 25 + 23.75 + 10 = 98.35 (PRD §3.2).
PACKAGE_A_OVERRIDES = {"package_label": "NW-CAT-2026-EDP-A"}
PACKAGE_B_OVERRIDES = {
    "package_label": "NW-CAT-2026-EDP-B",
    "data_quality_flags_count": 10,
    "cat_model_version": "RMS-23.2",
    "loss_history_completeness_pct": 95.0000,
}


def _bound_program_at_the_post_bind_clock():
    """The BOUND prologue, with the clock moved on to 2026-03-01 (PRD §3.6)."""
    ctx = setup_bound_program()
    set_clock(POST_BIND_CLOCK)
    return ctx


def _program_with_two_packages_and_the_first_signed_off():
    """Two packages both sent to review while DRAFT, then package A signed off."""
    ctx = setup_draft_program(
        with_layer=False, submission_overrides=PACKAGE_A_OVERRIDES
    )
    ctx["submission_b"] = create_exposure_submission(
        ctx["program"]["id"], ctx["cedent"]["id"], **PACKAGE_B_OVERRIDES
    )
    submit_for_review(ctx["submission"]["id"])
    submit_for_review(ctx["submission_b"]["id"])
    ctx["submission"] = signoff(
        ctx["submission"]["id"], review_note="Package A accepted"
    )
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx


def test_a_new_program_opens_in_draft_on_placement_and_not_started_on_documentation():
    """A freshly opened placement file enters both of its state machines at the head.

    PRD: "A newly opened file starts with `placement_status` at `DRAFT` and
    `documentation_status` at `NOT_STARTED`."

    Design: Corner/state_machines/placement_chain_entities_each_start_in_their_declared_initial_state
    """
    ctx = setup_draft_program()

    program = ctx["program"]
    assert_status(program, "placement_status", "DRAFT")
    assert_status(program, "documentation_status", "NOT_STARTED")

    read_back = read_program(program["id"])
    assert_status(read_back, "placement_status", "DRAFT")
    assert_status(read_back, "documentation_status", "NOT_STARTED")


def test_a_new_exposure_package_opens_in_draft_with_an_empty_signoff_trail():
    """The exposure package enters at DRAFT and carries no actuarial trail yet.

    PRD: "The package is created in status `DRAFT`, its `program_id` is taken
    from the program it is created under, and its `actuary_signoff_user_id`,
    `signed_off_at` and `review_note` all start null."

    Design: Corner/state_machines/placement_chain_entities_each_start_in_their_declared_initial_state
    """
    ctx = setup_draft_program()

    submission = ctx["submission"]
    assert_status(submission, "status", "DRAFT")
    assert submission["program_id"] == ctx["program"]["id"], (
        "the package's program_id is taken from the program it was created under"
    )
    assert_is_null(submission, "actuary_signoff_user_id")
    assert_is_null(submission, "signed_off_at")
    assert_is_null(submission, "review_note")

    read_back = read_submission(submission["id"])
    assert_status(read_back, "status", "DRAFT")
    assert_is_null(read_back, "actuary_signoff_user_id")


def test_a_new_layer_opens_in_open_with_zeroed_totals_and_null_commission_fields():
    """A layer enters at OPEN with every placement and commission figure still empty.

    PRD: "A new layer opens with status `OPEN`, with `written_line_total_pct`
    and `signed_line_total_pct` at `0.0000`, with `limit_eroded_minor`,
    `reinstatements_used` and `incurred_ceded_minor` at 0, and with
    `loss_ratio_pct`, `provisional_ceding_commission_minor`,
    `final_ceding_commission_minor` and `ceding_commission_delta_minor` all
    null."

    Design: Corner/state_machines/placement_chain_entities_each_start_in_their_declared_initial_state
    """
    ctx = setup_draft_program()

    layer = ctx["layer"]
    assert_status(layer, "status", "OPEN")
    assert_pct_equals(layer["written_line_total_pct"], 0.0000, "written_line_total_pct")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")
    assert_money_equals(layer["limit_eroded_minor"], 0, "limit_eroded_minor")
    assert layer["reinstatements_used"] == 0, "reinstatements_used starts at 0"
    assert_money_equals(layer["incurred_ceded_minor"], 0, "incurred_ceded_minor")
    for null_field in (
        "loss_ratio_pct",
        "provisional_ceding_commission_minor",
        "final_ceding_commission_minor",
        "ceding_commission_delta_minor",
    ):
        assert_is_null(layer, null_field)

    read_back = read_layer(layer["id"])
    assert_status(read_back, "status", "OPEN")
    assert_pct_equals(read_back["written_line_total_pct"], 0.0000, "written_line_total_pct")


def test_a_new_market_submission_opens_in_sent_stamped_with_the_logical_clock():
    """Releasing a layer to a market creates a SENT submission stamped at the clock.

    PRD: "A market submission is created in status `SENT`, with `layer_id` taken
    from the layer it was created under, `sent_at` stamped with the current
    logical-clock instant and `submitted_by_user_id` recording the releasing
    broker's `X-User-ID`."

    Design: Corner/state_machines/placement_chain_entities_each_start_in_their_declared_initial_state
    """
    ctx = setup_program_in_market()

    market_submission = send_submission(ctx)

    assert_status(market_submission, "status", "SENT")
    assert market_submission["layer_id"] == ctx["layer"]["id"], (
        "layer_id is taken from the layer the submission was created under"
    )
    assert_instant_equals(
        market_submission["sent_at"], CLOCK["PLACEMENT_START"], "sent_at"
    )
    assert market_submission["submitted_by_user_id"] == LEAD_USER_ID, (
        "submitted_by_user_id records the releasing broker's X-User-ID"
    )


def test_a_new_quote_opens_in_quoted_at_negotiation_round_zero():
    """The market's first answer enters at QUOTED with the negotiation counter untouched.

    PRD: "A successful quote is created in status `QUOTED` with
    `negotiation_round` at 0, `last_counter_note` null and `accepted_line_pct`
    null."

    Design: Corner/state_machines/placement_chain_entities_each_start_in_their_declared_initial_state
    """
    ctx = setup_quoted_layer()

    quote = ctx["quotes"][0]
    assert_status(quote, "status", "QUOTED")
    assert quote["negotiation_round"] == 0, (
        f"negotiation_round starts at 0, got {quote['negotiation_round']!r}"
    )
    assert_is_null(quote, "last_counter_note")
    assert_is_null(quote, "accepted_line_pct")
    assert quote["market_submission_id"] == ctx["market_submissions"][0]["id"], (
        "market_submission_id records the submission the quote answers"
    )
    assert quote["layer_id"] == ctx["layer"]["id"], "layer_id is copied from the submission"
    assert quote["reinsurer_id"] == ctx["reinsurers"][0]["id"], (
        "reinsurer_id is copied from the submission"
    )


def test_a_firm_ordered_signing_line_opens_provisional_with_a_null_signed_line():
    """The firm order's first hop enters the line at PROVISIONAL, unsigned.

    PRD: "The first hop creates a signing line whose `layer_id`, `quote_id` and
    `reinsurer_id` identify the layer, the quote and the market, whose
    `written_line_pct` is copied from the `accepted_line_pct` just accepted and
    is **never mutated again**, whose `signed_line_pct` is null, and whose status
    is `PROVISIONAL`."

    Design: Corner/state_machines/placement_chain_entities_each_start_in_their_declared_initial_state
    """
    ctx = setup_firm_ordered_layer()

    signing_line = ctx["signing_lines"][0]
    assert_status(signing_line, "status", "PROVISIONAL")
    assert_is_null(signing_line, "signed_line_pct")
    assert_pct_equals(signing_line["written_line_pct"], 100.0000, "written_line_pct")
    assert signing_line["layer_id"] == ctx["layer"]["id"], "layer_id identifies the layer"
    assert signing_line["quote_id"] == ctx["quotes"][0]["id"], "quote_id identifies the quote"
    assert signing_line["reinsurer_id"] == ctx["reinsurers"][0]["id"], (
        "reinsurer_id identifies the market"
    )


def test_a_new_brokerage_disclosure_opens_in_draft_with_no_decision_trail():
    """The compensation disclosure is drafted at DRAFT with nothing decided yet.

    PRD: "The disclosure records its `program_id`, starts in `DRAFT`, and leaves
    `disclosed_by_user_id`, `acknowledged_by_user_id` and `decision_note` null."

    Design: Corner/state_machines/placement_chain_entities_each_start_in_their_declared_initial_state
    """
    ctx = setup_firm_ordered_layer()

    disclosure = create_disclosure(ctx["program"]["id"])

    assert_status(disclosure, "status", "DRAFT")
    assert disclosure["program_id"] == ctx["program"]["id"], (
        "the disclosure records the program it was drafted against"
    )
    assert_is_null(disclosure, "disclosed_by_user_id")
    assert_is_null(disclosure, "acknowledged_by_user_id")
    assert_is_null(disclosure, "decision_note")


def test_a_booked_fiduciary_movement_opens_pending_and_moves_no_money():
    """A 100,000,000 cedent receipt is booked at PENDING with an empty approval trail.

    PRD: "A booked movement records `created_by_user_id` as the booking
    accountant's identity, starts in `PENDING`, leaves `approved_by_user_id`,
    `value_date`, `hold_reason` and `reverses_transaction_id` null, and
    increments the program's `version`."

    Design: Corner/state_machines/post_bind_entities_each_start_in_their_declared_initial_state
    """
    ctx = _bound_program_at_the_post_bind_clock()
    before = read_program(ctx["program"]["id"])

    transaction = book_transaction(
        ctx["program"]["id"],
        "CEDENT_RECEIPT",
        RECEIPT_MINOR,
        expected_program_version=before["version"],
    )

    assert_status(transaction, "status", "PENDING")
    assert transaction["created_by_user_id"] == ACCOUNTANT_USER_ID, (
        "created_by_user_id records the booking accountant's identity"
    )
    for null_field in (
        "approved_by_user_id",
        "value_date",
        "hold_reason",
        "reverses_transaction_id",
    ):
        assert_is_null(transaction, null_field)
    assert_money_equals(transaction["amount_minor"], RECEIPT_MINOR, "amount_minor")

    after = read_program(ctx["program"]["id"])
    assert_version_incremented(after["version"], before["version"])
    assert_money_equals(after["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")


def test_a_notified_claim_opens_in_notified_with_nothing_collected_or_disputed():
    """A loss notified on the bound layer enters at NOTIFIED with every counter at zero.

    PRD: "A new file starts in `NOTIFIED`, with `disputed_minor`,
    `collected_minor` and `arbitration_cost_minor` at 0, `advocacy_route` null
    and `reinstatement_triggered` false, and answers 201."

    Design: Corner/state_machines/post_bind_entities_each_start_in_their_declared_initial_state
    """
    ctx = _bound_program_at_the_post_bind_clock()

    advocacy = notify_claim(ctx["layer"]["id"], ctx["cedent"]["id"], **CLAIM_OVERRIDES)

    assert_status(advocacy, "status", "NOTIFIED")
    assert_money_equals(advocacy["disputed_minor"], 0, "disputed_minor")
    assert_money_equals(advocacy["collected_minor"], 0, "collected_minor")
    assert_money_equals(advocacy["arbitration_cost_minor"], 0, "arbitration_cost_minor")
    assert_is_null(advocacy, "advocacy_route")
    assert advocacy["reinstatement_triggered"] is False, (
        "reinstatement_triggered starts false on a newly notified file"
    )


def test_a_raised_cession_dispute_opens_with_nothing_settled():
    """The market's objection enters at RAISED with no concession recorded.

    PRD: "A dispute starts in `RAISED` with `settled_minor` 0 and
    `resolution_note` null, and answers 201."

    Design: Corner/state_machines/post_bind_entities_each_start_in_their_declared_initial_state
    """
    ctx = _bound_program_at_the_post_bind_clock()
    advocacy = notify_claim(ctx["layer"]["id"], ctx["cedent"]["id"], **CLAIM_OVERRIDES)
    review_claim(advocacy["id"])

    dispute = raise_dispute(
        advocacy["id"],
        ctx["reinsurers"][0]["id"],
        ctx["signing_lines"][0]["id"],
        DISPUTED_MINOR,
        dispute_reason="WORDING_AMBIGUITY",
    )

    assert_status(dispute, "status", "RAISED")
    assert_money_equals(dispute["settled_minor"], 0, "settled_minor")
    assert_is_null(dispute, "resolution_note")
    assert dispute["claim_advocacy_id"] == advocacy["id"], (
        "the dispute records the advocacy file it was raised against"
    )
    assert dispute["signing_line_id"] == ctx["signing_lines"][0]["id"], (
        "the dispute records the objecting market's own line"
    )


def test_go_to_market_advances_the_program_and_bumps_its_version():
    """The only trigger for SUBMISSION_READY → IN_MARKET moves the program and nothing else.

    PRD: "Once the actuary has opened the marketing window, the placing broker
    releases the program to market, advancing `placement_status` from
    `SUBMISSION_READY` to `IN_MARKET`."

    Design: Corner/state_machines/go_to_market_moves_the_program_and_leaves_the_layer_untouched_until_a_submission
    """
    ctx = setup_submission_ready_program()
    before = read_program(ctx["program"]["id"])
    assert_status(before, "placement_status", "SUBMISSION_READY")

    after = go_to_market(ctx["program"]["id"])

    assert_status(after, "placement_status", "IN_MARKET")
    assert after["version"] == before["version"] + 1, (
        f"go-to-market increments the version once: {before['version']} → {after['version']}"
    )
    assert_status(after, "documentation_status", "NOT_STARTED")
    assert_status(
        read_program(ctx["program"]["id"]), "documentation_status", "NOT_STARTED"
    )


def test_the_first_market_submission_is_what_carries_the_layer_out_of_open():
    """The layer stays OPEN through go-to-market and only the first submission moves it.

    PRD: "The **first** submission on a layer also carries the layer from `OPEN`
    to `IN_MARKET`, which is the moment `quoted_gross_premium_minor` is frozen,
    and increments the layer's `version`."

    Design: Corner/state_machines/go_to_market_moves_the_program_and_leaves_the_layer_untouched_until_a_submission
    """
    ctx = setup_submission_ready_program()

    go_to_market(ctx["program"]["id"])
    after_release = read_layer(ctx["layer"]["id"])
    assert_status(after_release, "status", "OPEN")

    send_submission(ctx)

    after_submission = read_layer(ctx["layer"]["id"])
    assert_status(after_submission, "status", "IN_MARKET")
    assert after_submission["version"] == after_release["version"] + 1, (
        "the first submission increments the layer's version once: "
        f"{after_release['version']} → {after_submission['version']}"
    )


def test_go_to_market_without_an_open_layer_is_refused():
    """A SUBMISSION_READY program with no layer at all cannot be released to market.

    PRD: "At least one layer of the program must still be `OPEN`, and the
    program's `documentation_status` must still be `NOT_STARTED` — you cannot
    re-market a program whose slip has already been issued; either failure, like
    an attempt from any placement state other than `SUBMISSION_READY`, is
    `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/state_machines/go_to_market_without_an_open_layer_or_with_a_suspended_cedent_is_refused
    """
    ctx = setup_submission_ready_program(with_layer=False)

    response = api_client.go_to_market(ctx["program"]["id"], LEAD_HEADERS)

    validate_error(response, ApiErrorId.ERR_PROGRAM_STATE_INVALID.value)
    assert_status(
        read_program(ctx["program"]["id"]), "placement_status", "SUBMISSION_READY"
    )


def test_go_to_market_with_a_suspended_cedent_is_refused_on_the_cedent_posture_rule():
    """Once the cedent is suspended the same release fails on posture, not on state.

    PRD: "The owning cedent's `status` must be `ACTIVE`; a suspended cedent
    blocks the release with `ERR_CEDENT_SUSPENDED`."

    Design: Corner/state_machines/go_to_market_without_an_open_layer_or_with_a_suspended_cedent_is_refused
    """
    ctx = setup_submission_ready_program(with_layer=False)
    layer = create_layer(ctx["program"]["id"])

    suspended = suspend_cedent(ctx["cedent"]["id"], reason="Regulatory review")
    assert_status(suspended, "status", "SUSPENDED")
    assert read_cedent(ctx["cedent"]["id"])["suspension_reason"] == "Regulatory review", (
        "the suspension_reason is recorded alongside the status"
    )

    response = api_client.go_to_market(ctx["program"]["id"], LEAD_HEADERS)

    validate_error(response, ApiErrorId.ERR_CEDENT_SUSPENDED.value)
    assert_status(
        read_program(ctx["program"]["id"]), "placement_status", "SUBMISSION_READY"
    )
    assert_status(read_layer(layer["id"]), "status", "OPEN")
    rows, _meta = validate_paginated(
        api_client.list_layer_market_submissions(layer["id"], LEAD_HEADERS)
    )
    assert len(rows) == 0, f"no market submission was created, got {len(rows)} rows"


def test_signing_off_a_second_package_supersedes_the_first_one():
    """Package B's sign-off retires package A into the terminal SUPERSEDED state.

    PRD: "Every **other** exposure package of the same program that was itself in
    `SIGNED_OFF` becomes `SUPERSEDED`, which is that entity's terminal state —
    only one signed-off package can be the live one."

    Design: Corner/state_machines/signing_off_a_second_package_supersedes_the_first_and_leaves_the_program_state_alone
    """
    ctx = _program_with_two_packages_and_the_first_signed_off()
    assert_status(ctx["submission"], "status", "SIGNED_OFF")

    package_b = signoff(
        ctx["submission_b"]["id"], review_note="Package B supersedes A"
    )

    assert_status(package_b, "status", "SIGNED_OFF")
    assert package_b["actuary_signoff_user_id"] == ACTUARY_USER_ID, (
        "signing off stamps the acting actuary's X-User-ID"
    )
    assert_instant_equals(
        package_b["signed_off_at"], CLOCK["PLACEMENT_START"], "signed_off_at"
    )
    assert package_b["review_note"] == "Package B supersedes A", (
        "the supplied review_note is recorded on the package just signed off"
    )

    package_a = read_submission(ctx["submission"]["id"])
    assert_status(package_a, "status", "SUPERSEDED")
    assert package_a["review_note"] == "Package A accepted", (
        "superseding package A does not disturb the note its own sign-off recorded"
    )


def test_the_second_signoff_leaves_the_program_state_and_version_alone():
    """The bubble-up cannot re-fire from SUBMISSION_READY, so nothing on the program moves.

    PRD: "And the program's `placement_status` bubbles up from `DRAFT` to
    `SUBMISSION_READY`, with the program's `version` incremented."

    Design: Corner/state_machines/signing_off_a_second_package_supersedes_the_first_and_leaves_the_program_state_alone
    """
    ctx = _program_with_two_packages_and_the_first_signed_off()
    midpoint = ctx["program"]
    assert_status(midpoint, "placement_status", "SUBMISSION_READY")

    signoff(ctx["submission_b"]["id"], review_note="Package B supersedes A")

    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "SUBMISSION_READY")
    assert program["version"] == midpoint["version"], (
        "the second sign-off transitions nothing on the program, so its version "
        f"stays at {midpoint['version']}, got {program['version']}"
    )


def test_the_second_package_scores_ninety_eight_point_three_five():
    """Ten flagged records in a thousand and a 95.0000% loss history score 98.35.

    PRD: "The four weighted components are added together and the resulting raw
    total is rounded half up to two decimal places to give
    `completeness_score`."

    Design: Corner/state_machines/signing_off_a_second_package_supersedes_the_first_and_leaves_the_program_state_alone
    """
    ctx = _program_with_two_packages_and_the_first_signed_off()

    package_b = signoff(
        ctx["submission_b"]["id"], review_note="Package B supersedes A"
    )

    assert_score_equals(package_b["completeness_score"], 98.35, "completeness_score")
    assert_score_equals(
        read_submission(ctx["submission_b"]["id"])["completeness_score"],
        98.35,
        "completeness_score",
    )
    assert_score_equals(
        read_submission(ctx["submission"]["id"])["completeness_score"],
        96.70,
        "package A completeness_score",
    )
