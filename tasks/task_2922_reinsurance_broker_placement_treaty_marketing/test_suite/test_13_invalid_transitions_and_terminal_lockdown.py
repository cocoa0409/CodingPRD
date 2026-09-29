"""Invalid placement transitions, terminal lockdown and scoped cascades (PRD §2.8, §3.1–§3.6).

Queue B — corner section ``state_machines``: each trigger is fired from a state
that does not declare it, so the own-state rule at priority 21 answers before
every later gate, and the cascades that do fire are shown to stop at their
declared scope.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_quote,
    api_client,
    assert_is_null,
    assert_pct_equals,
    assert_score_equals,
    assert_status,
    assert_version_incremented,
    bind_program,
    create_disclosure,
    create_xol_layer_payload,
    decide_disclosure,
    decline_payload,
    disclose,
    read_disclosure,
    read_layer,
    read_market_submission,
    read_program,
    read_quote,
    read_signing_line,
    read_submission,
    revise_exposure_submission_payload,
    send_submission,
    setup_draft_program,
    setup_firm_ordered_layer,
    setup_program_in_market,
    submit_for_review,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_program,
    withdraw_program_payload,
)

LEAD_HEADERS = TEST_USERS["placement_lead_headers"]
ACCOUNTANT_HEADERS = TEST_USERS["accountant_headers"]

# Two markets on one layer: Alpha leads at 60.0000 and Bravo follows at 50.0000,
# so a decline by one of them can be shown not to touch the other (PRD §3.4).
DECLINE_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "security_rating": "AA",
        "max_line_pct": 100.0000,
        "lead_authorised": True,
        "capacity_limit_minor": 1_000_000_000,
    },
    {
        "name": "Bravo Re",
        "security_rating": "A",
        "max_line_pct": 100.0000,
        "lead_authorised": False,
        "capacity_limit_minor": 1_000_000_000,
    },
]

# The disclosure the cedent first rejects: the program's own 2.5000% brokerage
# plus a contingent commission and a market service fee (PRD §3.6).
DISCLOSURE_OVERRIDES = {
    "brokerage_pct": 2.5000,
    "contingent_commission_pct": 0.5000,
    "market_service_fee_minor": 250_000,
}
WITHDRAWAL_REASON = "Cedent restructured the tower"


def _program_in_market_with_one_submission_out():
    """The IN_MARKET prologue with one submission sent, so the layer is IN_MARKET."""
    ctx = setup_program_in_market()
    ctx["market_submission"] = send_submission(ctx)
    return ctx


def _withdrawn_program():
    """An IN_MARKET program with one submission out, then withdrawn."""
    ctx = _program_in_market_with_one_submission_out()
    ctx["program"] = withdraw_program(ctx["program"]["id"], reason=WITHDRAWAL_REASON)
    return ctx


def _package_in_actuary_review():
    """A DRAFT program whose only exposure package has been sent to the actuary."""
    ctx = setup_draft_program(with_layer=False)
    ctx["submission"] = submit_for_review(ctx["submission"]["id"])
    return ctx


def _layer_quoted_by_two_markets():
    """One CATASTROPHE layer quoted by Alpha at 60.0000 as lead and Bravo at 50.0000."""
    ctx = setup_program_in_market(market_specs=DECLINE_MARKET_SPECS)
    send_submission(ctx, market_index=0)
    add_quote(ctx, market_index=0, offered_line_pct=60.0000, is_lead=True)
    send_submission(ctx, market_index=1)
    add_quote(
        ctx,
        market_index=1,
        offered_line_pct=50.0000,
        quoted_rate_pct=8.5000,
        is_lead=False,
    )
    return ctx


def _firm_ordered_program_with_a_disclosed_disclosure():
    """A FIRM_ORDER program whose compensation disclosure has been released."""
    ctx = setup_firm_ordered_layer()
    disclosure = create_disclosure(ctx["program"]["id"], **DISCLOSURE_OVERRIDES)
    ctx["disclosure"] = disclose(disclosure["id"])
    return ctx


def _firm_ordered_program_with_a_rejected_disclosure():
    """The same program after the cedent has rejected the disclosed terms."""
    ctx = _firm_ordered_program_with_a_disclosed_disclosure()
    ctx["disclosure"] = decide_disclosure(
        ctx["disclosure"]["id"],
        ctx["cedent"]["id"],
        "REJECT",
        decision_note="Contingent commission unacceptable",
    )
    return ctx


def test_binding_an_in_market_program_reports_the_state_error_not_the_disclosure_error():
    """Bind from IN_MARKET answers on the priority-21 state rule, never on priority 41.

    PRD: "Checks are evaluated in ascending priority, and **the first violated
    rule decides the response** — later violations are never reported."

    Design: Corner/state_machines/bind_before_firm_order_and_settle_before_bind_are_invalid_transitions
    """
    ctx = _program_in_market_with_one_submission_out()
    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "IN_MARKET")
    assert program["disclosure_acknowledged"] is False, (
        "no disclosure was ever acknowledged, so the priority-41 gate is also violated"
    )

    response = api_client.bind_program(ctx["program"]["id"], LEAD_HEADERS)

    validate_error(response, ApiErrorId.ERR_PROGRAM_STATE_INVALID.value)
    after = read_program(ctx["program"]["id"])
    assert_status(after, "placement_status", "IN_MARKET")
    assert after["disclosure_acknowledged"] is False, (
        "the refusal changed nothing on the program"
    )
    layer = read_layer(ctx["layer"]["id"])
    assert_status(layer, "status", "IN_MARKET")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")


def test_settling_an_in_market_program_is_an_invalid_transition():
    """The accounting close is refused three states early, on the program's own status.

    PRD: "The program's `placement_status` must be `BOUND`, its
    `documentation_status` must be `WORDING_AGREED` or `EXECUTED` — a placement
    whose wording was never agreed cannot be closed — else
    `ERR_DOCUMENTATION_NOT_AGREED`, and no fiduciary movement of the program may
    remain in `PENDING`, `APPROVED` or `HELD`, else
    `ERR_PROGRAM_HAS_OPEN_TRANSACTIONS`."

    Design: Corner/state_machines/bind_before_firm_order_and_settle_before_bind_are_invalid_transitions
    """
    ctx = _program_in_market_with_one_submission_out()
    before = read_program(ctx["program"]["id"])
    assert_status(before, "placement_status", "IN_MARKET")

    response = api_client.settle_program(ctx["program"]["id"], ACCOUNTANT_HEADERS)

    validate_error(response, ApiErrorId.ERR_PROGRAM_STATE_INVALID.value)
    after = read_program(ctx["program"]["id"])
    assert_status(after, "placement_status", "IN_MARKET")
    assert_status(after, "documentation_status", "NOT_STARTED")
    assert after["version"] == before["version"], (
        "a refused settlement must not touch the program"
    )
    layer = read_layer(ctx["layer"]["id"])
    assert_status(layer, "status", "IN_MARKET")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")


def test_withdrawing_from_in_market_lapses_the_layer_and_closes_the_submission():
    """Abandoning a marketed file unwinds the paper it put out before it terminates.

    PRD: "Withdrawal from `IN_MARKET` or from `FIRM_ORDER` runs an identical,
    larger cascade: every layer of the program whose status is not `BOUND`
    becomes `LAPSED`; every signing line on those layers in `PROVISIONAL` or
    `SIGNED` becomes `RELEASED` with `release_reason` set to
    `PROGRAM_WITHDRAWN`; every quote on those layers in `QUOTED`, `COUNTERED`,
    `REQUOTED` or `FIRM_ORDER` becomes `LAPSED`; every market submission on
    those layers in `SENT` or `QUOTED` becomes `CLOSED`;
    `committed_capacity_minor` is recomputed for every market whose lines were
    handed back; and only then does `placement_status` become `WITHDRAWN` with
    the program's `version` incremented."

    Design: Corner/state_machines/a_withdrawn_program_is_locked_against_every_further_trigger
    """
    ctx = _program_in_market_with_one_submission_out()
    before = read_program(ctx["program"]["id"])

    program = withdraw_program(ctx["program"]["id"], reason=WITHDRAWAL_REASON)

    assert_status(program, "placement_status", "WITHDRAWN")
    assert program["withdrawal_reason"] == WITHDRAWAL_REASON, (
        "the supplied reason is captured verbatim as withdrawal_reason"
    )
    assert_version_incremented(program["version"], before["version"])
    assert_status(read_layer(ctx["layer"]["id"]), "status", "LAPSED")
    assert_status(
        read_market_submission(ctx["market_submission"]["id"]), "status", "CLOSED"
    )

    rows, _meta = validate_paginated(
        api_client.list_program_layers(ctx["program"]["id"], LEAD_HEADERS)
    )
    assert len(rows) == 1, (
        f"the cascade lapses the one layer in place, it does not add or remove rows: {rows}"
    )


def test_a_second_withdrawal_is_refused_and_does_not_overwrite_the_reason():
    """WITHDRAWN is terminal, so the original abandonment reason survives untouched.

    PRD: "The placing broker may withdraw a placement from `DRAFT`,
    `SUBMISSION_READY`, `IN_MARKET` or `FIRM_ORDER`, supplying a `reason` that is
    captured as `withdrawal_reason`; from any other placement state the attempt
    is `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/state_machines/a_withdrawn_program_is_locked_against_every_further_trigger
    """
    ctx = _withdrawn_program()
    withdrawn_version = ctx["program"]["version"]

    response = api_client.withdraw_program(
        ctx["program"]["id"],
        withdraw_program_payload(reason="Second thoughts about the restructure"),
        LEAD_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_PROGRAM_STATE_INVALID.value)
    after = read_program(ctx["program"]["id"])
    assert_status(after, "placement_status", "WITHDRAWN")
    assert after["withdrawal_reason"] == WITHDRAWAL_REASON, (
        "the refused second withdrawal must not overwrite the recorded reason"
    )
    assert after["version"] == withdrawn_version, (
        "a refused trigger leaves the terminal program at the version withdrawal left it"
    )


def test_every_further_placement_trigger_on_a_withdrawn_program_is_refused():
    """Go-to-market, bind, sweep and restructure all die on the priority-21 gate.

    PRD: "Each entity's own status must admit the requested action: the program's
    `placement_status` (priority 21, `ERR_PROGRAM_STATE_INVALID`), the program's
    `documentation_status` against the filed `document_type` (priority 22,
    `ERR_DOCUMENT_SEQUENCE_INVALID`), the exposure submission's status (priority
    23, `ERR_SUBMISSION_STATE_INVALID`), the layer's status (priority 24,
    `ERR_LAYER_STATE_INVALID`), the market submission's status (priority 25,
    `ERR_MARKET_SUBMISSION_CLOSED`), the quote's status (priority 26,
    `ERR_QUOTE_STATE_INVALID`), the signing line's status (priority 27,
    `ERR_SIGNING_LINE_STATE_INVALID`), the disclosure's status (priority 28,
    `ERR_DISCLOSURE_STATE_INVALID`), the fiduciary transaction's status (priority
    29, `ERR_TRANSACTION_STATE_INVALID`), the advocacy's status (priority 30,
    `ERR_ADVOCACY_STATE_INVALID`) and the dispute's status (priority 31,
    `ERR_DISPUTE_STATE_INVALID`)."

    Design: Corner/state_machines/a_withdrawn_program_is_locked_against_every_further_trigger
    """
    ctx = _withdrawn_program()
    program_id = ctx["program"]["id"]
    withdrawn_version = ctx["program"]["version"]

    validate_error(
        api_client.go_to_market(program_id, LEAD_HEADERS),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID.value,
    )
    validate_error(
        api_client.bind_program(program_id, LEAD_HEADERS),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID.value,
    )
    validate_error(
        api_client.market_sweep(program_id, LEAD_HEADERS),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID.value,
    )
    validate_error(
        api_client.create_layer(
            program_id,
            create_xol_layer_payload(
                layer_label="XOL 500M xs 1B",
                attachment_minor=1_000_000_000,
                limit_minor=500_000_000,
            ),
            LEAD_HEADERS,
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID.value,
    )

    after = read_program(program_id)
    assert_status(after, "placement_status", "WITHDRAWN")
    assert after["version"] == withdrawn_version, (
        "four refused triggers in a row leave the terminal program byte-for-byte alone"
    )
    rows, _meta = validate_paginated(
        api_client.list_program_layers(program_id, LEAD_HEADERS)
    )
    assert len(rows) == 1, f"the refused restructure added no layer row: {rows}"
    assert_status(rows[0], "status", "LAPSED")


def test_submitting_the_same_exposure_package_for_review_twice_is_refused():
    """The second hand-off finds the package already with the actuary, not in DRAFT.

    PRD: "The placing broker sends a package to the broker actuary, moving it
    from `DRAFT` to `ACTUARY_REVIEW` and recomputing the score in passing; this
    requires the package to be in `DRAFT`, else `ERR_SUBMISSION_STATE_INVALID`,
    and requires the owning program's `placement_status` still to be `DRAFT`,
    else `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/state_machines/submitting_the_same_exposure_package_for_review_twice_is_refused
    """
    ctx = _package_in_actuary_review()
    submitted = ctx["submission"]
    assert_status(submitted, "status", "ACTUARY_REVIEW")
    assert_score_equals(submitted["completeness_score"], 96.70, "completeness_score")

    response = api_client.submit_exposure_for_review(submitted["id"], LEAD_HEADERS)

    validate_error(response, ApiErrorId.ERR_SUBMISSION_STATE_INVALID.value)
    after = read_submission(submitted["id"])
    assert_status(after, "status", "ACTUARY_REVIEW")
    assert_score_equals(after["completeness_score"], 96.70, "completeness_score")
    assert after["version"] == submitted["version"], (
        "the refused re-submission must not re-score or re-version the package"
    )
    assert_is_null(after, "actuary_signoff_user_id")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "DRAFT")


def test_revising_a_package_under_actuary_review_is_refused():
    """Only a REJECTED package may be resupplied, so a package in review is frozen.

    PRD: "A revision attempted from any status other than `REJECTED` is
    `ERR_SUBMISSION_STATE_INVALID`, and a revision attempted by a
    `CedentUnderwriter` whose `X-User-ID` is not the owning program's `cedent_id`
    is `ERR_FOREIGN_RESOURCE`."

    Design: Corner/state_machines/submitting_the_same_exposure_package_for_review_twice_is_refused
    """
    ctx = _package_in_actuary_review()
    submitted = ctx["submission"]

    response = api_client.revise_exposure_submission(
        submitted["id"],
        revise_exposure_submission_payload(loss_history_completeness_pct=99.0000),
        ctx["cedent_headers"],
    )

    validate_error(response, ApiErrorId.ERR_SUBMISSION_STATE_INVALID.value)
    after = read_submission(submitted["id"])
    assert_status(after, "status", "ACTUARY_REVIEW")
    assert_pct_equals(
        after["loss_history_completeness_pct"], 90.0000, "loss_history_completeness_pct"
    )
    assert_score_equals(after["completeness_score"], 96.70, "completeness_score")
    assert after["version"] == submitted["version"], (
        "a refused revision overwrites no field and bumps no version"
    )


def test_declining_a_quote_closes_its_own_market_submission_and_no_other():
    """Alpha walking away from the layer leaves Bravo's quote and submission live.

    PRD: "Declining is permitted from `QUOTED`, `COUNTERED` or `REQUOTED`, by the
    owning market only, with an optional `decline_reason`; the quote's status
    becomes `DECLINED` and the parent market submission's status becomes
    `DECLINED` as well, whether it was sitting in `SENT` or in `QUOTED`."

    Design: Corner/state_machines/declining_a_quote_closes_its_own_market_submission_and_no_other
    """
    ctx = _layer_quoted_by_two_markets()
    alpha_submission, bravo_submission = ctx["market_submissions"]
    alpha_quote, bravo_quote = ctx["quotes"]

    response = api_client.decline_quote(
        alpha_quote["id"],
        decline_payload(decline_reason="Rate inadequate for the peril mix"),
        ctx["market_headers"][0],
    )

    declined = validate_success(response)
    assert_status(declined, "status", "DECLINED")
    # The PRD names `decline_reason` only as an optional input to the decline and
    # never as a response-visible attribute of the quote — unlike `counter_note`,
    # which it explicitly says "is stored as `last_counter_note`" — so no
    # assertion is made about it being echoed back.
    assert_status(read_market_submission(alpha_submission["id"]), "status", "DECLINED")

    assert_status(read_quote(bravo_quote["id"]), "status", "QUOTED")
    assert_status(read_market_submission(bravo_submission["id"]), "status", "QUOTED")


def test_the_decline_leaves_the_layer_and_the_program_where_the_marketing_put_them():
    """No signing line ever existed, so the layer's derived total stays 0.0000.

    PRD: "Third, a **compound status is always re-derived, never assumed**: a
    layer's status is a function of the signing lines currently on it, so after
    any line is created or released the totals are recomputed first and the
    status follows from the recomputed totals."

    Design: Corner/state_machines/declining_a_quote_closes_its_own_market_submission_and_no_other
    """
    ctx = _layer_quoted_by_two_markets()
    alpha_quote = ctx["quotes"][0]

    validate_success(
        api_client.decline_quote(
            alpha_quote["id"],
            decline_payload(decline_reason="Rate inadequate for the peril mix"),
            ctx["market_headers"][0],
        )
    )

    layer = read_layer(ctx["layer"]["id"])
    assert_status(layer, "status", "IN_MARKET")
    assert_pct_equals(layer["written_line_total_pct"], 0.0000, "written_line_total_pct")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "IN_MARKET")


def test_rejecting_the_disclosure_leaves_the_program_flag_false():
    """The cedent refuses the contingent commission, so nothing is acknowledged.

    PRD: "`REJECT` moves it to `REJECTED` and leaves `disclosure_acknowledged`
    false, because no disclosure of the program is acknowledged."

    Design: Corner/state_machines/acknowledging_the_disclosure_syncs_the_flag_onto_the_parent_program
    """
    ctx = _firm_ordered_program_with_a_disclosed_disclosure()
    disclosed = ctx["disclosure"]
    assert_status(disclosed, "status", "DISCLOSED")
    program_before = read_program(ctx["program"]["id"])

    rejected = decide_disclosure(
        disclosed["id"],
        ctx["cedent"]["id"],
        "REJECT",
        decision_note="Contingent commission unacceptable",
    )

    assert_status(rejected, "status", "REJECTED")
    assert rejected["decision_note"] == "Contingent commission unacceptable", (
        "the decision note is recorded on either outcome"
    )
    assert rejected["acknowledged_by_user_id"] == ctx["cedent"]["id"], (
        "the deciding cedent underwriter is stamped even on a rejection"
    )
    assert_version_incremented(rejected["version"], disclosed["version"])

    program = read_program(ctx["program"]["id"])
    assert program["disclosure_acknowledged"] is False, (
        "a rejected disclosure must not flip the program flag"
    )
    assert_version_incremented(program["version"], program_before["version"])
    assert_status(program, "placement_status", "FIRM_ORDER")


def test_binding_with_a_rejected_disclosure_is_refused():
    """A FIRM_ORDER program whose cedent said no is still blocked from binding.

    PRD: "Binding requires the program's `placement_status` to be `FIRM_ORDER`,
    requires `disclosure_acknowledged` to be true — else
    `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` — and requires every layer of the program
    whose status is not `LAPSED` to be either `FULLY_PLACED` or `SIGNED_DOWN`,
    else `ERR_LAYER_STATE_INVALID`."

    Design: Corner/state_machines/acknowledging_the_disclosure_syncs_the_flag_onto_the_parent_program
    """
    ctx = _firm_ordered_program_with_a_rejected_disclosure()
    layer_before = read_layer(ctx["layer"]["id"])
    assert_status(layer_before, "status", "FULLY_PLACED")

    response = api_client.bind_program(ctx["program"]["id"], LEAD_HEADERS)

    validate_error(response, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED.value)
    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "FIRM_ORDER")
    assert program["disclosure_acknowledged"] is False, (
        "the refused bind leaves the flag exactly as the rejection left it"
    )
    assert_status(read_layer(ctx["layer"]["id"]), "status", "FULLY_PLACED")
    assert_status(read_signing_line(ctx["signing_line"]["id"]), "status", "PROVISIONAL")


def test_re_disclosing_after_a_rejection_clears_the_prior_decision():
    """REJECTED is not terminal: the same disclosure goes back out to the cedent clean.

    PRD: "`REJECTED` is deliberately **not** terminal: the accountant can correct
    the terms and release the same disclosure again, which takes it from
    `REJECTED` back to `DISCLOSED`, clearing `acknowledged_by_user_id` and
    `decision_note` back to null and re-checking the `brokerage_pct` match and
    the program state."

    Design: Corner/state_machines/acknowledging_the_disclosure_syncs_the_flag_onto_the_parent_program
    """
    ctx = _firm_ordered_program_with_a_rejected_disclosure()
    rejected = ctx["disclosure"]

    re_disclosed = disclose(rejected["id"])

    assert_status(re_disclosed, "status", "DISCLOSED")
    assert_is_null(re_disclosed, "acknowledged_by_user_id")
    assert_is_null(re_disclosed, "decision_note")
    assert re_disclosed["disclosed_by_user_id"] == ACCOUNTANT_HEADERS["X-User-ID"], (
        "the releasing accountant is stamped again on the re-release"
    )
    assert_version_incremented(re_disclosed["version"], rejected["version"])
    assert read_program(ctx["program"]["id"])["disclosure_acknowledged"] is False, (
        "a re-released disclosure is not yet acknowledged"
    )


def test_acknowledging_the_disclosure_syncs_the_flag_onto_the_parent_program():
    """The cedent's acknowledgement is what flips the program's binding gate.

    PRD: "`ACKNOWLEDGE` moves the disclosure to `ACKNOWLEDGED`, which is
    terminal, and sets the program's `disclosure_acknowledged` flag to true — the
    flag that unblocks binding."

    Design: Corner/state_machines/acknowledging_the_disclosure_syncs_the_flag_onto_the_parent_program
    """
    ctx = _firm_ordered_program_with_a_rejected_disclosure()
    re_disclosed = disclose(ctx["disclosure"]["id"])
    program_before = read_program(ctx["program"]["id"])

    acknowledged = decide_disclosure(re_disclosed["id"], ctx["cedent"]["id"], "ACKNOWLEDGE")

    assert_status(acknowledged, "status", "ACKNOWLEDGED")
    assert acknowledged["acknowledged_by_user_id"] == ctx["cedent"]["id"], (
        "the acknowledging cedent underwriter is stamped on the disclosure"
    )
    assert_version_incremented(acknowledged["version"], re_disclosed["version"])

    program = read_program(ctx["program"]["id"])
    assert program["disclosure_acknowledged"] is True, (
        "the acknowledgement syncs the flag onto the parent program"
    )
    assert_version_incremented(program["version"], program_before["version"])
    assert_status(program, "placement_status", "FIRM_ORDER")
    assert_status(read_disclosure(re_disclosed["id"]), "status", "ACKNOWLEDGED")


def test_binding_after_the_acknowledgement_converts_the_layer_and_its_line():
    """With the flag true the same bind call now carries the whole file to BOUND.

    PRD: "On those layers, each `PROVISIONAL` line — a line on a layer that was
    never signed down, therefore written at exactly the line it was firm-ordered
    at — has its `signed_line_pct` set equal to its `written_line_pct` and then
    becomes `BOUND`; each already-`SIGNED` line simply becomes `BOUND`."

    Design: Corner/state_machines/acknowledging_the_disclosure_syncs_the_flag_onto_the_parent_program
    """
    ctx = _firm_ordered_program_with_a_rejected_disclosure()
    re_disclosed = disclose(ctx["disclosure"]["id"])
    decide_disclosure(re_disclosed["id"], ctx["cedent"]["id"], "ACKNOWLEDGE")

    program = bind_program(ctx["program"]["id"])

    assert_status(program, "placement_status", "BOUND")
    assert program["disclosure_acknowledged"] is True, (
        "binding does not disturb the acknowledgement that unblocked it"
    )
    assert_status(read_layer(ctx["layer"]["id"]), "status", "BOUND")

    line = read_signing_line(ctx["signing_line"]["id"])
    assert_status(line, "status", "BOUND")
    assert_pct_equals(line["signed_line_pct"], 100.0000, "signed_line_pct")
    assert_pct_equals(line["written_line_pct"], 100.0000, "written_line_pct")
    assert_pct_equals(
        read_layer(ctx["layer"]["id"])["signed_line_total_pct"],
        100.0000,
        "signed_line_total_pct",
    )
