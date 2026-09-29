"""The seven-role authority matrix and the fiduciary duty split (PRD §2.1, §2.8, §2.10).

Queue B — section ``rbac``: every role's own exclusive operations succeed for it and
for nobody else, the auth band answers before the existence band, shared operations
stay inside the calling entity's own rows, and no identity may approve the fiduciary
movement it booked itself.
"""
from test_helpers import (
    ACCOUNTANT,
    ACCOUNTANT_2,
    ACTUARY,
    ADMIN,
    CLOCK,
    COMPLIANCE,
    LEAD,
    LEAD_2,
    NON_EXISTENT_UUID,
    OMIT,
    UNUSED_UUID,
    UNUSED_UUID_ALT,
    ApiErrorId,
    api_client,
    approve_transaction,
    assert_is_null,
    assert_money_equals,
    assert_pct_equals,
    assert_score_equals,
    assert_status,
    bind_program,
    book_transaction,
    collect,
    counter_payload,
    counter_quote,
    create_cedent,
    create_claim_advocacy_payload,
    create_disclosure,
    create_exposure_submission,
    create_fiduciary_transaction_payload,
    create_layer,
    create_program,
    create_program_payload,
    create_quote_payload,
    create_reinsurer,
    decide_disclosure,
    decline_payload,
    disclose,
    disclosure_decision_payload,
    file_document,
    firm_order,
    generate_renewal_report,
    go_to_market,
    headers_missing_both,
    headers_without_user_id,
    make_cedent_underwriter_headers,
    make_headers,
    make_reinsurer_underwriter_headers,
    notify_claim,
    quote_on,
    raise_dispute,
    read_advocacy,
    read_dispute,
    read_layer,
    read_program,
    read_reinsurer,
    read_submission,
    read_transaction,
    requote,
    resolve_dispute,
    reverse_transaction,
    review_claim,
    revise_exposure_submission_payload,
    set_advocacy_route,
    set_clock,
    set_market_security,
    settle_transaction,
    sign_off_exposure,
    signoff,
    signoff_payload,
    submit_for_review,
    submit_to_market,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_claim,
)

# The single lead market of every chain in this file, sized at 5,000,000,000 so a
# 100.0000 line on a 1,000,000,000 layer never exhausts its capacity.
LEAD_MARKET_SPEC = {
    "name": "Alpha Re",
    "security_rating": "AA",
    "capacity_limit_minor": 5_000_000_000,
    "max_line_pct": 100.0000,
    "lead_authorised": True,
}
PROGRAM = {"program_name": "Northwind Property CAT 2026"}

# The package the actuary must reject: 200 of 1000 records flagged, two years of
# history, 40.0000% loss history and no report, scoring 40*0.8 + 25*0.4 + 25*0.4 =
# 52.00, which is under the 70.00 sign-off floor.
WEAK_PACKAGE = {
    "package_label": "NW-CAT-2026-EDP",
    "exposure_records_count": 1000,
    "data_quality_flags_count": 200,
    "historical_years_supplied": 2,
    "cat_model_version": "RMS-23.1",
    "loss_history_completeness_pct": 40.0000,
    "actuarial_report_attached": False,
}
# The cedent's resupply, which lifts the merged package to 40*0.98 + 25 + 22.5 + 10.
REVISION = {
    "data_quality_flags_count": 20,
    "historical_years_supplied": 5,
    "loss_history_completeness_pct": 90.0000,
    "actuarial_report_attached": True,
}

# The negotiation: the market indicates at 9.0000, the broker counters, the market
# requotes at 8.0000 and the broker firm-orders the whole line.
NEGOTIATED_QUOTE = {
    "offered_line_pct": 100.0000,
    "quoted_rate_pct": 9.0000,
    "ceding_commission_pct": 0.0000,
    "reinstatements_offered": 1,
    "sublimit_minor": 0,
    "expires_at": "2026-03-01T00:00:00.000Z",
    "is_lead": True,
}
REQUOTE = dict(NEGOTIATED_QUOTE, quoted_rate_pct=8.0000)
DISCLOSURE_TERMS = {
    "brokerage_pct": 2.5000,
    "contingent_commission_pct": 0.0000,
    "market_service_fee_minor": 0,
}

# The exposure package Southbank's cedent files, and the program it hangs on.
SOUTHBANK_PACKAGE = {
    "package_label": "SB-EDP-1",
    "exposure_records_count": 500,
    "data_quality_flags_count": 10,
    "historical_years_supplied": 5,
    "cat_model_version": "N/A",
    "loss_history_completeness_pct": 95.0000,
    "actuarial_report_attached": True,
}
SOUTHBANK_PROGRAM = {
    "program_name": "Southbank Casualty XL 2026",
    "line_of_business": "CASUALTY",
    "estimated_premium_income_minor": 800_000_000,
    "brokerage_pct": OMIT,
}
# A well-formed program payload whose only interesting property is who sends it.
FOREIGN_PROGRAM_ATTEMPT = {
    "line_of_business": "CASUALTY",
    "underwriting_year": 2026,
    "inception_date": "2027-06-01T00:00:00.000Z",
    "expiry_date": "2028-06-01T00:00:00.000Z",
    "estimated_premium_income_minor": 100_000_000,
    "brokerage_pct": OMIT,
}


def _revise(submission_id: str, cedent_id: str, **fields):
    """The cedent's exclusive revise verb, which has no composite fixture."""
    return validate_success(
        api_client.revise_exposure_submission(
            submission_id,
            revise_exposure_submission_payload(**fields),
            make_cedent_underwriter_headers(cedent_id),
        )
    )


def _notify_as_broker(layer_id: str, **overrides):
    """The broker's half of the shared claim-notification door (PRD §3.9)."""
    return validate_success(
        api_client.create_claim_advocacy(
            layer_id, create_claim_advocacy_payload(**overrides), LEAD
        ),
        201,
    )


def _in_market_placement():
    """Registry -> program -> signed-off package -> layer -> IN_MARKET."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    alpha = create_reinsurer(**LEAD_MARKET_SPEC)
    program = create_program(cedent["id"], **PROGRAM)
    submission = create_exposure_submission(program["id"], cedent["id"])
    layer = create_layer(program["id"])
    sign_off_exposure(submission["id"])
    program = go_to_market(program["id"])
    return {
        "cedent": cedent,
        "alpha": alpha,
        "program": program,
        "submission": submission,
        "layer": layer,
    }


def _bound_placement():
    """The IN_MARKET chain plus an acknowledged disclosure, a lead line and bind."""
    ctx = _in_market_placement()
    disclosure = create_disclosure(ctx["program"]["id"], **DISCLOSURE_TERMS)
    disclose(disclosure["id"])
    decide_disclosure(disclosure["id"], ctx["cedent"]["id"], "ACKNOWLEDGE")
    market_submission = submit_to_market(ctx["layer"]["id"], ctx["alpha"]["id"])
    quote = quote_on(market_submission["id"], ctx["alpha"]["id"], **NEGOTIATED_QUOTE)
    counter_quote(quote["id"], "Rate needs to come to 8.0")
    requote(quote["id"], ctx["alpha"]["id"], **REQUOTE)
    signing_line = firm_order(quote["id"], 100.0000, layer_id=ctx["layer"]["id"])
    ctx["program"] = bind_program(ctx["program"]["id"])
    ctx.update(
        {
            "disclosure": disclosure,
            "market_submission": market_submission,
            "quote": quote,
            "signing_line": signing_line,
        }
    )
    return ctx


def _bound_placement_with_wording():
    """A bound placement whose wording is agreed, so outflows may settle."""
    ctx = _bound_placement()
    ctx["documents"] = [
        file_document(ctx["program"]["id"], "SLIP", "NMA-SLIP-2026-001"),
        file_document(ctx["program"]["id"], "WORDING_DRAFT", "NMA-WD-2026-001"),
        file_document(ctx["program"]["id"], "AGREED_WORDING", "NMA-AW-2026-001"),
    ]
    return ctx


def _southbank_draft():
    """One cedent, one market, one DRAFT program carrying one DRAFT package."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent(
        name="Southbank Insurance", domicile_code="GBLON", financial_rating="A"
    )
    alpha = create_reinsurer(**LEAD_MARKET_SPEC)
    program = create_program(cedent["id"], **SOUTHBANK_PROGRAM)
    submission = create_exposure_submission(
        program["id"], cedent["id"], **SOUTHBANK_PACKAGE
    )
    return {
        "cedent": cedent,
        "alpha": alpha,
        "program": program,
        "submission": submission,
        "version": program["version"],
    }


def _assert_nothing_mutated(ctx):
    """Every refusal in this file is total: the DRAFT file is exactly as it was."""
    rows, meta = validate_paginated(
        api_client.list_programs(LEAD, {"cedent_id": ctx["cedent"]["id"]})
    )
    assert len(rows) == 1, f"expected exactly one program, got {len(rows)}"
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert rows[0]["id"] == ctx["program"]["id"], "the listed program is the only program"

    program = read_program(ctx["program"]["id"])
    assert program["version"] == ctx["version"], (
        f"expected version {ctx['version']}, got {program['version']}"
    )
    assert_status(program, "placement_status", "DRAFT")

    submission = read_submission(ctx["submission"]["id"])
    assert_status(submission, "status", "DRAFT")
    assert submission["historical_years_supplied"] == 5, (
        "the refused revision must not have overwritten historical_years_supplied"
    )


def test_the_actuarys_signoff_and_no_broker_action_opens_the_marketing_window():
    """Admin seeds the registry, the actuary rejects then signs off, the broker markets.

    PRD: "That bubble-up is the crucial ordering fact of the whole placement: it is
    the actuary's sign-off, not any broker action, that opens the marketing window."

    Design: Corner/rbac/each_of_the_seven_roles_exercises_its_own_exclusive_operations
    """
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    alpha = create_reinsurer(**LEAD_MARKET_SPEC)
    assert_status(cedent, "status", "ACTIVE")
    assert_status(alpha, "security_status", "APPROVED")

    program = create_program(cedent["id"], **PROGRAM)
    assert_status(program, "placement_status", "DRAFT")

    submission = create_exposure_submission(program["id"], cedent["id"], **WEAK_PACKAGE)
    reviewed = submit_for_review(submission["id"])
    assert_score_equals(reviewed["completeness_score"], 52.00, "weak completeness_score")

    rejected = signoff(
        submission["id"],
        "REJECTED",
        review_note="Loss history and cat modelling both short",
    )
    assert_status(rejected, "status", "REJECTED")
    assert_status(read_program(program["id"]), "placement_status", "DRAFT")

    revised = _revise(submission["id"], cedent["id"], **REVISION)
    assert_status(revised, "status", "DRAFT")
    assert_score_equals(revised["completeness_score"], 96.70, "revised completeness_score")

    submit_for_review(submission["id"])
    signed = signoff(submission["id"])
    assert_status(signed, "status", "SIGNED_OFF")
    assert signed["actuary_signoff_user_id"] == "act-1", (
        "sign-off stamps the acting actuary's identity"
    )
    assert_status(read_program(program["id"]), "placement_status", "SUBMISSION_READY")

    layer = create_layer(program["id"])
    in_market = go_to_market(program["id"])
    assert_status(in_market, "placement_status", "IN_MARKET")
    assert_status(read_layer(layer["id"]), "status", "OPEN")


def test_the_accountant_releases_the_compensation_disclosure_and_the_cedent_acknowledges_it():
    """acct-1 drafts and discloses; only the owning cedent can acknowledge and unblock bind.

    PRD: "`ACKNOWLEDGE` moves the disclosure to `ACKNOWLEDGED`, which is terminal, and
    sets the program's `disclosure_acknowledged` flag to true — the flag that unblocks
    binding."

    Design: Corner/rbac/each_of_the_seven_roles_exercises_its_own_exclusive_operations
    """
    ctx = _in_market_placement()

    disclosure = create_disclosure(ctx["program"]["id"], **DISCLOSURE_TERMS)
    assert_status(disclosure, "status", "DRAFT")
    assert_is_null(disclosure, "disclosed_by_user_id")

    disclosed = disclose(disclosure["id"])
    assert_status(disclosed, "status", "DISCLOSED")
    assert disclosed["disclosed_by_user_id"] == "acct-1", (
        "release stamps the acting accountant's identity"
    )
    assert read_program(ctx["program"]["id"])["disclosure_acknowledged"] is False

    acknowledged = decide_disclosure(
        disclosure["id"],
        ctx["cedent"]["id"],
        "ACKNOWLEDGE",
        decision_note="Compensation understood",
    )
    assert_status(acknowledged, "status", "ACKNOWLEDGED")
    assert acknowledged["acknowledged_by_user_id"] == ctx["cedent"]["id"], (
        "the acknowledgement is stamped with the deciding cedent's own id"
    )
    assert read_program(ctx["program"]["id"])["disclosure_acknowledged"] is True


def test_the_broker_counters_and_the_market_requotes_before_the_broker_binds_the_file():
    """Counter is the broker's verb, requote the market's, and only the broker binds.

    PRD: "The market answers a counter by requoting, which is permitted only from
    `COUNTERED` and only by the market that owns the quote."

    Design: Corner/rbac/each_of_the_seven_roles_exercises_its_own_exclusive_operations
    """
    ctx = _in_market_placement()
    disclosure = create_disclosure(ctx["program"]["id"], **DISCLOSURE_TERMS)
    disclose(disclosure["id"])
    decide_disclosure(disclosure["id"], ctx["cedent"]["id"], "ACKNOWLEDGE")

    market_submission = submit_to_market(ctx["layer"]["id"], ctx["alpha"]["id"])
    assert market_submission["submitted_by_user_id"] == "lead-1", (
        "the placing broker owns the submission out to the market"
    )

    quote = quote_on(market_submission["id"], ctx["alpha"]["id"], **NEGOTIATED_QUOTE)
    assert_status(quote, "status", "QUOTED")

    countered = counter_quote(quote["id"], "Rate needs to come to 8.0")
    assert_status(countered, "status", "COUNTERED")
    assert countered["negotiation_round"] == 1, (
        f"the counter opens round 1, got {countered['negotiation_round']}"
    )

    requoted = requote(quote["id"], ctx["alpha"]["id"], **REQUOTE)
    assert_status(requoted, "status", "REQUOTED")
    assert_pct_equals(requoted["quoted_rate_pct"], 8.0000, "requoted_rate_pct")

    signing_line = firm_order(quote["id"], 100.0000, layer_id=ctx["layer"]["id"])
    assert_pct_equals(signing_line["written_line_pct"], 100.0000, "written_line_pct")

    program = bind_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "BOUND")
    assert_money_equals(
        program["gross_written_premium_minor"], 97_125_000, "gross_written_premium_minor"
    )
    assert_money_equals(program["net_remittance_minor"], 94_696_875, "net_remittance_minor")

    file_document(ctx["program"]["id"], "SLIP", "NMA-SLIP-2026-001")
    file_document(ctx["program"]["id"], "WORDING_DRAFT", "NMA-WD-2026-001")
    agreed = file_document(ctx["program"]["id"], "AGREED_WORDING", "NMA-AW-2026-001")
    assert_status(agreed, "document_type", "AGREED_WORDING")


def test_the_actuary_generates_renewal_analytics_and_compliance_moves_security_posture():
    """act-1 reports on the bound file at 9.7125 rate on line; compliance restricts Alpha.

    PRD: "A `BrokerActuary` generates a renewal report against a program that is
    `BOUND` or `SETTLED`, else `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/rbac/each_of_the_seven_roles_exercises_its_own_exclusive_operations
    """
    ctx = _bound_placement()

    report = generate_renewal_report(ctx["program"]["id"])
    assert report["generated_by_user_id"] == "act-1", (
        "the report is stamped with the generating actuary's identity"
    )
    assert_pct_equals(report["current_rate_on_line_pct"], 9.7125, "current_rate_on_line_pct")
    assert_pct_equals(report["prior_rate_on_line_pct"], 0.0000, "prior_rate_on_line_pct")
    assert_score_equals(
        report["placement_efficiency_pct"], 100.00, "placement_efficiency_pct"
    )
    assert_score_equals(report["market_condition_index"], 0.00, "market_condition_index")

    restricted = set_market_security(
        ctx["alpha"]["id"], "RESTRICTED", "Rating watch negative"
    )
    assert_status(restricted, "security_status", "RESTRICTED")
    assert_status(read_reinsurer(ctx["alpha"]["id"]), "security_status", "RESTRICTED")


def test_the_accountant_books_and_settles_while_compliance_approves_and_reverses():
    """One receipt and one remittance walk the four acts; only compliance reverses.

    PRD: "The intermediary holds client money, so the fiduciary chain is split into
    four distinct acts performed by distinct authorities: an accountant **books** a
    movement, a second identity **approves** it, an accountant **settles** it, and
    only a compliance officer may **reverse** a settled movement."

    Design: Corner/rbac/each_of_the_seven_roles_exercises_its_own_exclusive_operations
    """
    ctx = _bound_placement_with_wording()
    program_id = ctx["program"]["id"]

    receipt = book_transaction(program_id, "CEDENT_RECEIPT", 97_125_000)
    assert receipt["created_by_user_id"] == "acct-1", "the accountant books the movement"
    assert_status(receipt, "status", "PENDING")

    approved = approve_transaction(receipt["id"])
    assert_status(approved, "status", "APPROVED")
    assert approved["approved_by_user_id"] == "compl-1", (
        "a second identity — the compliance officer — approves the booking"
    )
    assert_status(settle_transaction(receipt["id"]), "status", "SETTLED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        97_125_000,
        "fiduciary_holding_minor after the receipt settles",
    )

    remittance = book_transaction(
        program_id,
        "REINSURER_REMITTANCE",
        94_696_875,
        signing_line_id=ctx["signing_line"]["id"],
    )
    approve_transaction(remittance["id"])
    assert_status(settle_transaction(remittance["id"]), "status", "SETTLED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        2_428_125,
        "fiduciary_holding_minor after the remittance settles",
    )

    compensating = reverse_transaction(remittance["id"])
    assert_status(compensating, "status", "SETTLED")
    assert_status(compensating, "txn_type", "REMITTANCE_REVERSAL")
    assert compensating["reverses_transaction_id"] == remittance["id"], (
        "the compensating row points back at the movement it reverses"
    )
    assert_money_equals(compensating["amount_minor"], 94_696_875, "reversal amount_minor")
    assert_status(read_transaction(remittance["id"]), "status", "REVERSED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        97_125_000,
        "the reversal restores the balance exactly",
    )


def test_the_cedent_notifies_and_withdraws_while_the_broker_reviews_routes_and_resolves():
    """Two claim files split the advocacy verbs between cedent, broker, market and accountant.

    PRD: "The placing broker takes it under review, which requires the file to be
    `NOTIFIED` and the layer to still be `BOUND` and moves it to `UNDER_REVIEW`; or the
    cedent withdraws it, which requires the file to be `NOTIFIED` and the withdrawing
    `CedentUnderwriter` to be the program's own cedent, and moves it to `WITHDRAWN`, a
    terminal state that leaves the layer's erosion and reinstatements untouched because
    notification never touched them in the first place."

    Design: Corner/rbac/each_of_the_seven_roles_exercises_its_own_exclusive_operations
    """
    ctx = _bound_placement()
    layer_id, line_id = ctx["layer"]["id"], ctx["signing_line"]["id"]

    withdrawn_file = notify_claim(
        layer_id,
        ctx["cedent"]["id"],
        claim_reference="NW-2026-0001",
        event_date="2026-06-01T00:00:00.000Z",
        gross_claim_minor=2_300_000_000,
    )
    assert_money_equals(withdrawn_file["ceded_claim_minor"], 300_000_000, "ceded_claim_minor")
    assert_status(
        withdraw_claim(withdrawn_file["id"], ctx["cedent"]["id"]), "status", "WITHDRAWN"
    )

    live_file = _notify_as_broker(
        layer_id,
        claim_reference="NW-2026-0002",
        event_date="2026-07-01T00:00:00.000Z",
        gross_claim_minor=2_200_000_000,
    )
    assert_money_equals(live_file["ceded_claim_minor"], 200_000_000, "ceded_claim_minor")
    assert_status(review_claim(live_file["id"]), "status", "UNDER_REVIEW")

    collection = collect(live_file["id"], line_id, 50_000_000)
    assert_status(collection, "txn_type", "CLAIM_COLLECTION")
    assert_status(collection, "status", "PENDING")

    dispute = raise_dispute(
        live_file["id"],
        ctx["alpha"]["id"],
        line_id,
        30_000_000,
        dispute_reason="AGGREGATION_DISAGREEMENT",
    )
    assert_money_equals(dispute["disputed_minor"], 30_000_000, "disputed_minor")
    assert_status(dispute, "status", "RAISED")

    assert_status(set_advocacy_route(live_file["id"], "NEGOTIATION"), "status", "ADVOCACY_NEGOTIATION")
    resolve_dispute(
        dispute["id"], "WITHDRAWN", 30_000_000, resolution_note="Market conceded aggregation"
    )
    assert_status(read_dispute(dispute["id"]), "status", "WITHDRAWN")

    resolved_file = read_advocacy(live_file["id"])
    assert_status(resolved_file, "status", "RESOLVED")
    assert_money_equals(resolved_file["collectible_minor"], 200_000_000, "collectible_minor")


def test_a_blank_identity_is_absent_while_an_unrecognised_identity_is_merely_unknown():
    """Priority 1 answers for a blank or missing header; priority 2 for ghost-9.

    PRD: "The `X-User-ID` header must be present and non-blank, else
    `ERR_MISSING_USER_ID`; it must then resolve to a known actor, else
    `ERR_UNKNOWN_USER`."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation_and_the_auth_band_answers_first
    """
    ctx = _southbank_draft()
    program_id = ctx["program"]["id"]

    validate_error(
        api_client.get_program(program_id, headers_without_user_id("BrokerPlacementLead")),
        ApiErrorId.ERR_MISSING_USER_ID.value,
        401,
    )
    validate_error(
        api_client.get_program(program_id, headers_missing_both()),
        ApiErrorId.ERR_MISSING_USER_ID.value,
        401,
    )
    validate_error(
        api_client.get_program(program_id, make_headers("ghost-9", "BrokerPlacementLead")),
        ApiErrorId.ERR_UNKNOWN_USER.value,
        401,
    )

    readable = validate_success(api_client.get_program(program_id, LEAD))
    assert readable["id"] == program_id, "the same read succeeds for a recognised identity"


def test_the_role_check_answers_before_the_row_is_ever_looked_up():
    """Three unauthorised verbs aimed at ids that do not exist all report priority 3.

    PRD: "Checks are evaluated in ascending priority, and **the first violated rule
    decides the response** — later violations are never reported."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation_and_the_auth_band_answers_first
    """
    ctx = _southbank_draft()

    validate_error(
        api_client.create_program(
            create_program_payload(
                NON_EXISTENT_UUID, program_name="Ghost Cedent Program", **FOREIGN_PROGRAM_ATTEMPT
            ),
            ACTUARY,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.reverse_fiduciary_transaction(UNUSED_UUID, ACCOUNTANT),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.counter_quote(
            UNUSED_UUID_ALT,
            counter_payload("Sharpen the rate"),
            make_reinsurer_underwriter_headers(ctx["alpha"]["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )


def test_opening_a_file_signing_it_off_revising_it_and_the_clock_each_admit_one_role_only():
    """The actuary and the admin cannot open a file, the broker cannot sign off, and nothing moves.

    PRD: "The caller's role must appear in the called endpoint's role list, else
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation_and_the_auth_band_answers_first
    """
    ctx = _southbank_draft()
    cedent_id, submission_id = ctx["cedent"]["id"], ctx["submission"]["id"]

    for headers, name in ((ACTUARY, "Actuary's Program"), (ADMIN, "Admin's Program")):
        validate_error(
            api_client.create_program(
                create_program_payload(cedent_id, program_name=name, **FOREIGN_PROGRAM_ATTEMPT),
                headers,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

    validate_error(
        api_client.signoff_exposure_submission(submission_id, signoff_payload("SIGNED_OFF"), LEAD),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.revise_exposure_submission(
            submission_id, revise_exposure_submission_payload(historical_years_supplied=1), ACTUARY
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.set_clock("2026-02-01T00:00:00.000Z", LEAD),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    _assert_nothing_mutated(ctx)


def test_only_an_accountant_may_originate_a_fiduciary_movement():
    """The placing broker and the approving compliance officer are both refused the booking.

    PRD: "The intermediary holds client money, so the fiduciary chain is split into
    four distinct acts performed by distinct authorities: an accountant **books** a
    movement, a second identity **approves** it, an accountant **settles** it, and
    only a compliance officer may **reverse** a settled movement."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation_and_the_auth_band_answers_first
    """
    ctx = _southbank_draft()
    program_id = ctx["program"]["id"]
    payload = create_fiduciary_transaction_payload("CEDENT_RECEIPT", 1_000_000, ctx["version"])

    for headers in (LEAD, COMPLIANCE):
        validate_error(
            api_client.create_fiduciary_transaction(program_id, payload, headers),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

    ledger, meta = validate_paginated(
        api_client.list_program_fiduciary_transactions(program_id, ACCOUNTANT)
    )
    assert ledger == [], f"no movement was booked, got {ledger}"
    assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"
    _assert_nothing_mutated(ctx)


def test_the_fiduciary_ledger_is_closed_to_the_actuary_and_to_the_cedent():
    """Reads are gated by the same band as writes, and the ledger excludes act-1 by name.

    PRD: "It has no placement, binding or money authority, and — uniquely among the
    broker-side roles — it may not read the fiduciary ledger."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation_and_the_auth_band_answers_first
    """
    ctx = _southbank_draft()
    program_id = ctx["program"]["id"]

    validate_error(
        api_client.list_fiduciary_transactions(ACTUARY, {"program_id": program_id}),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.list_program_fiduciary_transactions(
            program_id, make_cedent_underwriter_headers(ctx["cedent"]["id"])
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    for headers in (ACCOUNTANT, COMPLIANCE):
        rows, meta = validate_paginated(api_client.list_fiduciary_transactions(headers))
        assert rows == [], f"the empty ledger reads cleanly for an admitted role, got {rows}"
        assert meta["total_count"] == 0, f"expected total_count 0, got {meta['total_count']}"


def test_the_two_counterparties_cannot_drive_the_placement_or_browse_each_others_registry():
    """The cedent cannot market its own program and neither counterparty browses the other.

    PRD: "The role model is one of **segregation of duties**: placement authority,
    actuarial sign-off, money movement and independent control are held by four
    different broker-side roles, and the two market-facing counterparties are external
    parties who may only touch their own resources."

    Design: Corner/rbac/no_role_reaches_another_roles_exclusive_operation_and_the_auth_band_answers_first
    """
    ctx = _southbank_draft()
    cedent_headers = make_cedent_underwriter_headers(ctx["cedent"]["id"])
    market_headers = make_reinsurer_underwriter_headers(ctx["alpha"]["id"])

    validate_error(
        api_client.go_to_market(ctx["program"]["id"], cedent_headers),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api_client.list_cedents(market_headers), ApiErrorId.ERR_UNAUTHORIZED.value, 403
    )
    validate_error(
        api_client.list_reinsurers(cedent_headers), ApiErrorId.ERR_UNAUTHORIZED.value, 403
    )

    _assert_nothing_mutated(ctx)


# The three extra packages of the shared-authorship probe differ only in their label
# and in who files them: 40 flags of 1000 records, five years, 80.0000% loss history.
SHARED_PACKAGE = {
    "exposure_records_count": 1000,
    "data_quality_flags_count": 40,
    "historical_years_supplied": 5,
    "cat_model_version": "RMS-23.1",
    "loss_history_completeness_pct": 80.0000,
    "actuarial_report_attached": False,
}
BRAVO_MARKET_SPEC = {
    "name": "Bravo Re",
    "security_rating": "A",
    "capacity_limit_minor": 5_000_000_000,
    "max_line_pct": 100.0000,
    "lead_authorised": True,
}
UNINVITED_QUOTE = {
    "offered_line_pct": 50.0000,
    "quoted_rate_pct": 8.5000,
    "ceding_commission_pct": 0.0000,
    "reinstatements_offered": 1,
    "sublimit_minor": 0,
    "expires_at": "2026-03-01T00:00:00.000Z",
    "is_lead": False,
}
INVITED_QUOTE = dict(NEGOTIATED_QUOTE, quoted_rate_pct=8.0000)


def _two_cedents_one_invited_market():
    """ced1 owns an IN_MARKET program addressed to Alpha only; Bravo and ced2 are outsiders."""
    set_clock(CLOCK["PLACEMENT_START"])
    ced1 = create_cedent(name="Cedent One Mutual", domicile_code="USNYC")
    ced2 = create_cedent(name="Cedent Two Mutual", domicile_code="USCHI")
    alpha = create_reinsurer(**LEAD_MARKET_SPEC)
    bravo = create_reinsurer(**BRAVO_MARKET_SPEC)
    program = create_program(ced1["id"], program_name="Cedent One Property CAT 2026")
    signed_package = create_exposure_submission(
        program["id"], ced1["id"], package_label="C1-EDP-A"
    )
    sign_off_exposure(signed_package["id"])
    layer = create_layer(program["id"], layer_label="C1 CAT 1B xs 2B")
    go_to_market(program["id"])
    market_submission = submit_to_market(layer["id"], alpha["id"])
    disclosure = create_disclosure(program["id"], **DISCLOSURE_TERMS)
    disclose(disclosure["id"])
    return {
        "ced1": ced1,
        "ced2": ced2,
        "alpha": alpha,
        "bravo": bravo,
        "program": program,
        "signed_package": signed_package,
        "layer": layer,
        "market_submission": market_submission,
        "disclosure": disclosure,
    }


def test_either_broker_identity_or_the_cedent_itself_may_assemble_an_exposure_package():
    """lead-1, lead-2 and the cedent each file a DRAFT package on the same program.

    PRD: "Either the placing broker or the ceding insurer itself may assemble an
    exposure package on a program, supplying a `package_label` of 1 to 80 characters,
    an `exposure_records_count` that is an integer of at least zero, a
    `data_quality_flags_count` recording how many of those records the data-quality
    scrub flagged — which must be at least zero and no greater than
    `exposure_records_count` — a `historical_years_supplied` between 0 and 20
    inclusive, a `cat_model_version` string of 1 to 40 characters naming the
    catastrophe model version used for the exposure run, and a
    `loss_history_completeness_pct` between 0 and 100 inclusive with up to four
    decimals, being the actuary's assessment of how complete the loss history is."

    Design: Corner/rbac/shared_operations_admit_both_owners_while_identity_binding_confines_them_to_their_own_rows
    """
    ctx = _two_cedents_one_invited_market()
    program_id = ctx["program"]["id"]
    assert_score_equals(
        ctx["signed_package"]["completeness_score"], 96.70, "signed completeness_score"
    )

    by_lead = create_exposure_submission(
        program_id, headers=LEAD, package_label="C1-EDP-B-by-broker", **SHARED_PACKAGE
    )
    by_second_lead = create_exposure_submission(
        program_id, headers=LEAD_2, package_label="C1-EDP-C-by-second-broker", **SHARED_PACKAGE
    )
    by_cedent = create_exposure_submission(
        program_id, ctx["ced1"]["id"], package_label="C1-EDP-D-by-cedent", **SHARED_PACKAGE
    )

    for package in (by_lead, by_second_lead, by_cedent):
        assert_status(package, "status", "DRAFT")
    filed_ids = {by_lead["id"], by_second_lead["id"], by_cedent["id"]}
    assert len(filed_ids) == 3, f"three separate packages were filed, got {filed_ids}"
    assert ctx["signed_package"]["id"] not in filed_ids, "none of them touched the signed row"

    rows, meta = validate_paginated(
        api_client.list_program_exposure_submissions(program_id, LEAD)
    )
    assert len(rows) == 4, f"expected four packages on the program, got {len(rows)}"
    assert meta["total_count"] == 4, f"expected total_count 4, got {meta['total_count']}"
    assert rows[0]["id"] == ctx["signed_package"]["id"], (
        "the listing runs created_at ascending, so the first package is the signed one"
    )


def test_six_roles_read_the_program_while_the_quoting_market_may_not():
    """Every broker-side role and the owning cedent read the file; Alpha is refused.

    PRD: "The caller's role must appear in the called endpoint's role list, else
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/shared_operations_admit_both_owners_while_identity_binding_confines_them_to_their_own_rows
    """
    ctx = _two_cedents_one_invited_market()
    program_id = ctx["program"]["id"]

    admitted = (
        ADMIN,
        LEAD,
        ACTUARY,
        ACCOUNTANT,
        COMPLIANCE,
        make_cedent_underwriter_headers(ctx["ced1"]["id"]),
    )
    for headers in admitted:
        program = validate_success(api_client.get_program(program_id, headers))
        assert program["id"] == program_id, "every admitted role reads the same program row"

    validate_error(
        api_client.get_program(
            program_id, make_reinsurer_underwriter_headers(ctx["alpha"]["id"])
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )


def test_a_cedent_authorised_for_the_verb_still_cannot_reach_another_cedents_rows():
    """ced2 is refused on ced1's package and on ced1's disclosure; ced1's own call lands.

    PRD: "And if an entity-backed caller is authorised for the endpoint but reaches for
    a resource belonging to a different instance of its backing entity, the request
    fails with `ERR_FOREIGN_RESOURCE` (HTTP 403)."

    Design: Corner/rbac/shared_operations_admit_both_owners_while_identity_binding_confines_them_to_their_own_rows
    """
    ctx = _two_cedents_one_invited_market()
    foreign_headers = make_cedent_underwriter_headers(ctx["ced2"]["id"])
    package = create_exposure_submission(
        ctx["program"]["id"],
        ctx["ced1"]["id"],
        package_label="C1-EDP-D-by-cedent",
        **SHARED_PACKAGE,
    )

    validate_error(
        api_client.revise_exposure_submission(
            package["id"],
            revise_exposure_submission_payload(historical_years_supplied=1),
            foreign_headers,
        ),
        ApiErrorId.ERR_FOREIGN_RESOURCE.value,
        403,
    )
    validate_error(
        api_client.decide_brokerage_disclosure(
            ctx["disclosure"]["id"],
            disclosure_decision_payload("ACKNOWLEDGE", decision_note="Not my program"),
            foreign_headers,
        ),
        ApiErrorId.ERR_FOREIGN_RESOURCE.value,
        403,
    )

    acknowledged = decide_disclosure(
        ctx["disclosure"]["id"],
        ctx["ced1"]["id"],
        "ACKNOWLEDGE",
        decision_note="Compensation understood",
    )
    assert_status(acknowledged, "status", "ACKNOWLEDGED")
    assert acknowledged["acknowledged_by_user_id"] == ctx["ced1"]["id"], (
        "only the owning cedent's identity is ever stamped on the acknowledgement"
    )
    assert read_submission(package["id"])["historical_years_supplied"] == 5, (
        "the refused revision left the foreign package byte-identical"
    )


def test_an_uninvited_market_is_turned_away_on_ownership_before_any_placement_rule():
    """Bravo cannot quote, requote or decline on the submission addressed to Alpha.

    PRD: "The acting market's `X-User-ID` must equal the submission's `reinsurer_id`,
    else `ERR_FOREIGN_RESOURCE`."

    Design: Corner/rbac/shared_operations_admit_both_owners_while_identity_binding_confines_them_to_their_own_rows
    """
    ctx = _two_cedents_one_invited_market()
    bravo_headers = make_reinsurer_underwriter_headers(ctx["bravo"]["id"])
    market_submission_id = ctx["market_submission"]["id"]

    validate_error(
        api_client.create_quote(
            market_submission_id, create_quote_payload(**UNINVITED_QUOTE), bravo_headers
        ),
        ApiErrorId.ERR_FOREIGN_RESOURCE.value,
        403,
    )

    quote = quote_on(market_submission_id, ctx["alpha"]["id"], **INVITED_QUOTE)
    assert_status(quote, "status", "QUOTED")

    validate_error(
        api_client.requote(
            quote["id"],
            create_quote_payload(**dict(INVITED_QUOTE, quoted_rate_pct=7.0000)),
            bravo_headers,
        ),
        ApiErrorId.ERR_FOREIGN_RESOURCE.value,
        403,
    )
    validate_error(
        api_client.decline_quote(
            quote["id"], decline_payload(decline_reason="Not our risk"), bravo_headers
        ),
        ApiErrorId.ERR_FOREIGN_RESOURCE.value,
        403,
    )

    declined = validate_success(
        api_client.decline_quote(
            quote["id"],
            decline_payload(decline_reason="Capacity redeployed"),
            make_reinsurer_underwriter_headers(ctx["alpha"]["id"]),
        )
    )
    assert_status(declined, "status", "DECLINED")


# The fiduciary duty-separation chain needs no placement at all: a program and two
# receipts are enough to exercise who may originate, approve and settle a movement.
FOURFOLD_PROGRAM = {
    "program_name": "Fourfold Property CAT 2026",
    "line_of_business": "PROPERTY",
    "underwriting_year": 2026,
    "estimated_premium_income_minor": 500_000_000,
    "brokerage_pct": 2.5000,
}
FIRST_RECEIPT_MINOR = 50_000_000
SECOND_RECEIPT_MINOR = 20_000_000


def _fourfold_booking():
    """A program of Fourfold Mutual carrying one PENDING 50,000,000 receipt booked by acct-1."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent(name="Fourfold Mutual", domicile_code="USNYC")
    program = create_program(cedent["id"], **FOURFOLD_PROGRAM)
    receipt = book_transaction(program["id"], "CEDENT_RECEIPT", FIRST_RECEIPT_MINOR)
    assert receipt["created_by_user_id"] == "acct-1", (
        "the booking identity is stamped from the caller, got "
        f"{receipt['created_by_user_id']!r}"
    )
    assert_status(receipt, "status", "PENDING")
    return {"cedent": cedent, "program": program, "receipt": receipt}


def test_the_accountant_that_booked_a_movement_cannot_approve_its_own_booking():
    """acct-1 books and is refused its own approval, leaving the row untouched.

    PRD: "A `BrokerAccountant` may approve only a movement whose
    `created_by_user_id` differs from the approving `X-User-ID`; approving its own
    booking is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

    Design: Corner/rbac/the_identity_that_books_a_fiduciary_movement_can_never_approve_it
    """
    ctx = _fourfold_booking()
    receipt_id = ctx["receipt"]["id"]

    validate_error(
        api_client.approve_fiduciary_transaction(receipt_id, ACCOUNTANT),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        422,
    )

    unchanged = read_transaction(receipt_id)
    assert_status(unchanged, "status", "PENDING")
    assert_is_null(unchanged, "approved_by_user_id")
    assert_money_equals(unchanged["amount_minor"], FIRST_RECEIPT_MINOR, "amount_minor")
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        0,
        "fiduciary_holding_minor after the refused approval",
    )


def test_a_compliance_officer_supplies_the_independent_approval_the_booker_could_not():
    """The same movement acct-1 could not approve is approved by compl-1.

    PRD: "A `PENDING` movement is approved by a `ComplianceOfficer` or a
    `BrokerAccountant`; anything other than `PENDING` is
    `ERR_TRANSACTION_STATE_INVALID`."

    Design: Corner/rbac/the_identity_that_books_a_fiduciary_movement_can_never_approve_it
    """
    ctx = _fourfold_booking()
    receipt_id = ctx["receipt"]["id"]

    validate_error(
        api_client.approve_fiduciary_transaction(receipt_id, ACCOUNTANT),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        422,
    )

    approved = approve_transaction(receipt_id, COMPLIANCE)
    assert_status(approved, "status", "APPROVED")
    assert approved["approved_by_user_id"] == "compl-1", (
        f"expected compl-1 to own the approval, got {approved['approved_by_user_id']!r}"
    )
    assert approved["created_by_user_id"] == "acct-1", (
        "approval never rewrites the booking identity"
    )
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        0,
        "an APPROVED movement is still invisible to the balance",
    )


def test_the_state_band_answers_before_the_duty_band_once_the_movement_has_moved_on():
    """After compl-1 approves, acct-1's second attempt is a state error, not a duty error.

    PRD: "Checks are evaluated in ascending priority, and **the first violated rule
    decides the response** — later violations are never reported."

    Design: Corner/rbac/the_identity_that_books_a_fiduciary_movement_can_never_approve_it
    """
    ctx = _fourfold_booking()
    receipt_id = ctx["receipt"]["id"]
    approve_transaction(receipt_id, COMPLIANCE)

    validate_error(
        api_client.approve_fiduciary_transaction(receipt_id, ACCOUNTANT),
        ApiErrorId.ERR_TRANSACTION_STATE_INVALID.value,
        409,
    )

    still_approved = read_transaction(receipt_id)
    assert_status(still_approved, "status", "APPROVED")
    assert still_approved["approved_by_user_id"] == "compl-1", (
        "the refused re-approval left compl-1's stamp in place"
    )


def test_two_accountants_cover_each_other_and_settlement_is_where_the_money_moves():
    """acct-2 approves acct-1's second receipt, and the two settlements sum to 70,000,000.

    PRD: "This is why the accounting role holds more than one identity: two
    accountants can cover each other, but neither can self-approve."

    Design: Corner/rbac/the_identity_that_books_a_fiduciary_movement_can_never_approve_it
    """
    ctx = _fourfold_booking()
    program_id = ctx["program"]["id"]
    first_id = ctx["receipt"]["id"]

    approve_transaction(first_id, COMPLIANCE)
    first_settled = settle_transaction(first_id, ACCOUNTANT)
    assert_status(first_settled, "status", "SETTLED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        FIRST_RECEIPT_MINOR,
        "fiduciary_holding_minor after the first settlement",
    )

    second = book_transaction(program_id, "CEDENT_RECEIPT", SECOND_RECEIPT_MINOR)
    assert second["created_by_user_id"] == "acct-1", "acct-1 books the second receipt too"
    validate_error(
        api_client.approve_fiduciary_transaction(second["id"], ACCOUNTANT),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        422,
    )

    peer_approved = approve_transaction(second["id"], ACCOUNTANT_2)
    assert_status(peer_approved, "status", "APPROVED")
    assert peer_approved["approved_by_user_id"] == "acct-2", (
        f"expected acct-2 to cover the booking, got {peer_approved['approved_by_user_id']!r}"
    )

    second_settled = settle_transaction(second["id"], ACCOUNTANT)
    assert_status(second_settled, "status", "SETTLED")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        FIRST_RECEIPT_MINOR + SECOND_RECEIPT_MINOR,
        "fiduciary_holding_minor after both settlements",
    )

    rows, meta = validate_paginated(
        api_client.list_program_fiduciary_transactions(
            program_id, COMPLIANCE, {"status": "SETTLED"}
        )
    )
    assert len(rows) == 2, f"expected both settled movements, got {len(rows)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert rows[0]["id"] == first_id, (
        "the ledger runs created_at ascending, so the first receipt leads"
    )
