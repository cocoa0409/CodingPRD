"""Non-linear lifecycles on three entities: the quote cycle, the program's two
dimensions and the advocacy fork/join (PRD §3.4, §3.1, §3.6, §3.7, §3.9).

Queue A — rule ``non_linear_state_machine``: the Quote machine is cyclic and
only the monotone round counter stops it; the Program carries two orthogonal
state dimensions that never drag each other along; and the ClaimAdvocacy forks
into arbitration on a child entity's event and rejoins at ``RESOLVED``.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    TEST_USERS,
    acknowledge_disclosure,
    api_client,
    assert_instant_equals,
    assert_money_equals,
    assert_pct_equals,
    assert_status,
    bind_program,
    collect,
    counter_payload,
    counter_quote,
    create_collection_payload,
    file_document,
    read_advocacy,
    read_dispute,
    read_layer,
    read_program,
    read_quote,
    read_signing_line,
    read_transaction,
    requote,
    resolve_dispute,
    set_advocacy_route,
    set_clock,
    setup_disputed_claim,
    setup_firm_ordered_layer,
    setup_quoted_layer,
    validate_error,
)

# The single lead-authorised market every chain in this file places with. Its
# capacity of 1,000,000,000 is exactly one full line on the canonical CAT layer.
ECHO_MARKET_SPECS = [
    {
        "name": "Echo Re",
        "security_rating": "AA",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    }
]
CAT_PROGRAM_OVERRIDES = {"program_name": "Northwind Property CAT 2026"}
CAT_SUBMISSION_OVERRIDES = {"package_label": "NW-CAT-2026-EDP"}
# The canonical CAT layer prices at 97,125,000 and is frozen there at market.
CAT_GROSS_PREMIUM_MINOR = 97_125_000

# The opening quote of the negotiation chain: a wide 9.0000 rate on line that the
# broker walks down over three counters.
OPENING_QUOTE_OVERRIDES = {
    "offered_line_pct": 100.0000,
    "quoted_rate_pct": 9.0000,
    "ceding_commission_pct": 0.0000,
    "reinstatements_offered": 1,
    "sublimit_minor": 0,
    "expires_at": CLOCK["QUOTE_EXPIRY"],
    "is_lead": True,
}
# Every requote carries the same terms and only sharpens the rate.
REQUOTE_TERMS = {
    "offered_line_pct": 100.0000,
    "ceding_commission_pct": 0.0000,
    "reinstatements_offered": 1,
    "sublimit_minor": 0,
    "expires_at": CLOCK["QUOTE_EXPIRY"],
    "is_lead": True,
}
COUNTER_NOTES = [
    "rate too high, come back at 8.5",
    "still wide of the mark",
    "final push to 8.0",
]
REQUOTED_RATES = [8.7000, 8.4000, 8.0000]
FOURTH_COUNTER_NOTE = "one more squeeze"

# The program whose two dimensions are driven apart: the slip is filed on
# 2026-01-20T12:00:00.000Z, nineteen and a half days after inception.
SLIP_FILING_INSTANT = "2026-01-20T12:00:00.000Z"
SLIP_DAYS_FROM_INCEPTION = 19
CONTRACT_CERTAINTY_DEADLINE = "2026-01-31T00:00:00.000Z"

# The advocacy chain: a 2,600,000,000 ground-up loss on a layer attaching at
# 2,000,000,000 cedes exactly 600,000,000, of which 100,000,000 is disputed.
CLAIM_OVERRIDES = {
    "claim_reference": "CL-2026-CAT-001",
    "event_date": "2026-06-01T00:00:00.000Z",
    "gross_claim_minor": 2_600_000_000,
}
DISPUTED_MINOR = 100_000_000
CEDED_CLAIM_MINOR = 600_000_000
COLLECTIBLE_WHILE_DISPUTED_MINOR = 500_000_000
# 1.5% of the 600,000,000 cession, rounded half up.
ARBITRATION_COST_MINOR = 9_000_000

LEAD = TEST_USERS["placement_lead_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


def _quoted_cat_layer():
    """One CAT layer in market with a single lead quote from Echo Re at 9.0000."""
    return setup_quoted_layer(
        quote_overrides=dict(OPENING_QUOTE_OVERRIDES),
        market_specs=ECHO_MARKET_SPECS,
        program_overrides=dict(CAT_PROGRAM_OVERRIDES),
        submission_overrides=dict(CAT_SUBMISSION_OVERRIDES),
    )


def _walk_three_negotiation_rounds(ctx):
    """counter -> requote three times, returning the round counter after each counter."""
    quote_id = ctx["quotes"][0]["id"]
    reinsurer_id = ctx["reinsurers"][0]["id"]
    rounds = []
    for note, rate in zip(COUNTER_NOTES, REQUOTED_RATES):
        countered = counter_quote(quote_id, note)
        rounds.append(countered)
        requote(quote_id, reinsurer_id, quoted_rate_pct=rate, **REQUOTE_TERMS)
    return rounds


def _firm_ordered_program_with_disclosure_acknowledged():
    """A single 100.0000 line fills the CAT layer, and the cedent acknowledges brokerage."""
    ctx = setup_firm_ordered_layer(
        market_specs=ECHO_MARKET_SPECS,
        program_overrides=dict(CAT_PROGRAM_OVERRIDES),
        submission_overrides=dict(CAT_SUBMISSION_OVERRIDES),
    )
    ctx["disclosure"] = acknowledge_disclosure(
        ctx["program"]["id"], ctx["cedent"]["id"], 2.5000
    )
    return ctx


def _disputed_advocacy_on_a_bound_cat_layer():
    """A BOUND CAT layer with a 600,000,000 cession and one RAISED 100,000,000 dispute."""
    return setup_disputed_claim(
        disputed_minor=DISPUTED_MINOR,
        claim_overrides=dict(CLAIM_OVERRIDES),
        dispute_overrides={"dispute_reason": "WORDING_AMBIGUITY"},
        market_specs=ECHO_MARKET_SPECS,
        program_overrides=dict(CAT_PROGRAM_OVERRIDES),
        submission_overrides=dict(CAT_SUBMISSION_OVERRIDES),
    )


def test_each_broker_counter_advances_the_quote_negotiation_round_by_one():
    """Three counters read 1, 2 and 3 on a quote that keeps cycling back to COUNTERED.

    PRD: "The placing broker counters a quote that is in `QUOTED` or `REQUOTED`,
    supplying a `counter_note`; the quote's `negotiation_round` increases by one,
    the note is stored as `last_counter_note`, and the status becomes
    `COUNTERED`."

    Design: Difficulty/non_linear_state_machine/quote_counter_requote_cycle_rejects_the_fourth_broker_counter
    """
    ctx = _quoted_cat_layer()
    assert ctx["quotes"][0]["negotiation_round"] == 0, (
        "a fresh quote opens with negotiation_round 0"
    )

    rounds = _walk_three_negotiation_rounds(ctx)

    assert rounds[0]["negotiation_round"] == 1, (
        f"first counter must read round 1, got {rounds[0]['negotiation_round']!r}"
    )
    assert rounds[1]["negotiation_round"] == 2, (
        f"second counter must read round 2, got {rounds[1]['negotiation_round']!r}"
    )
    assert rounds[2]["negotiation_round"] == 3, (
        f"third counter must read round 3, got {rounds[2]['negotiation_round']!r}"
    )
    for index, countered in enumerate(rounds):
        assert_status(countered, "status", "COUNTERED")
        assert countered["last_counter_note"] == COUNTER_NOTES[index], (
            f"counter {index + 1} must store its own note as last_counter_note"
        )


def test_a_requote_re_enters_the_cycle_without_advancing_the_round_counter():
    """Each requote returns the quote to REQUOTED at the sharpened rate, round untouched.

    PRD: "A requote overwrites `offered_line_pct`, `quoted_rate_pct`,
    `ceding_commission_pct`, `reinstatements_offered`, `sublimit_minor`,
    `additional_exclusions` and `expires_at` with the values supplied, leaves
    `negotiation_round` **unchanged** — only the broker's counter advances the
    round counter — and moves the status to `REQUOTED`."

    Design: Difficulty/non_linear_state_machine/quote_counter_requote_cycle_rejects_the_fourth_broker_counter
    """
    ctx = _quoted_cat_layer()
    quote_id = ctx["quotes"][0]["id"]
    reinsurer_id = ctx["reinsurers"][0]["id"]

    for expected_round, (note, rate) in enumerate(
        zip(COUNTER_NOTES, REQUOTED_RATES), start=1
    ):
        countered = counter_quote(quote_id, note)
        assert countered["negotiation_round"] == expected_round, (
            f"counter must read round {expected_round}"
        )
        requoted = requote(quote_id, reinsurer_id, quoted_rate_pct=rate, **REQUOTE_TERMS)
        assert_status(requoted, "status", "REQUOTED")
        assert requoted["negotiation_round"] == expected_round, (
            "a requote leaves negotiation_round exactly where the counter left it, "
            f"expected {expected_round}, got {requoted['negotiation_round']!r}"
        )
        assert_pct_equals(requoted["quoted_rate_pct"], rate, "requoted quoted_rate_pct")


def test_the_fourth_broker_counter_is_refused_once_three_rounds_are_exhausted():
    """After three counters the cycle terminates: a fourth counter is refused.

    PRD: "The quote's `negotiation_round` must be **less than three** before a
    further counter is accepted, so at most three counters are ever possible on
    one quote and a fourth attempt is refused with
    `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`."

    Design: Difficulty/non_linear_state_machine/quote_counter_requote_cycle_rejects_the_fourth_broker_counter
    """
    ctx = _quoted_cat_layer()
    _walk_three_negotiation_rounds(ctx)

    response = api_client.counter_quote(
        ctx["quotes"][0]["id"], counter_payload(FOURTH_COUNTER_NOTE), LEAD
    )

    validate_error(response, ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value)


def test_the_refused_fourth_counter_leaves_the_quote_as_the_last_requote_left_it():
    """The rejected counter changes nothing: still REQUOTED at 8.0000 on round 3.

    PRD: "The cycle from `COUNTERED` to `REQUOTED` and back to `COUNTERED` may
    therefore run until the round cap bites."

    Design: Difficulty/non_linear_state_machine/quote_counter_requote_cycle_rejects_the_fourth_broker_counter
    """
    ctx = _quoted_cat_layer()
    quote_id = ctx["quotes"][0]["id"]
    _walk_three_negotiation_rounds(ctx)

    validate_error(
        api_client.counter_quote(quote_id, counter_payload(FOURTH_COUNTER_NOTE), LEAD),
        ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED.value,
    )

    quote = read_quote(quote_id)
    assert_status(quote, "status", "REQUOTED")
    assert quote["negotiation_round"] == 3, (
        f"the rejected counter must not advance the round, got {quote['negotiation_round']!r}"
    )
    assert_pct_equals(quote["quoted_rate_pct"], 8.0000, "quoted_rate_pct")
    assert quote["last_counter_note"] == COUNTER_NOTES[2], (
        "last_counter_note must still hold the third accepted counter's note, got "
        f"{quote['last_counter_note']!r}"
    )


def test_filing_the_slip_advances_documentation_without_touching_placement():
    """A slip filed on a FIRM_ORDER program moves documentation only.

    PRD: "A `SLIP` takes the program from `NOT_STARTED` to `SLIP_ISSUED` and
    requires the program's `placement_status` to be `FIRM_ORDER` or `BOUND` — the
    slip is the record of a placement that actually exists."

    Design: Difficulty/non_linear_state_machine/program_documentation_dimension_advances_independently_of_placement_dimension
    """
    ctx = _firm_ordered_program_with_disclosure_acknowledged()
    before = read_program(ctx["program"]["id"])
    assert_status(before, "placement_status", "FIRM_ORDER")
    assert_status(before, "documentation_status", "NOT_STARTED")
    set_clock(SLIP_FILING_INSTANT)

    file_document(ctx["program"]["id"], "SLIP", "NW-CAT-2026-SLIP")

    after = read_program(ctx["program"]["id"])
    assert_status(after, "documentation_status", "SLIP_ISSUED")
    assert_status(after, "placement_status", "FIRM_ORDER")


def test_binding_advances_placement_without_dragging_documentation_along():
    """Binding a slip-issued program leaves documentation_status at SLIP_ISSUED.

    PRD: "Neither dimension constrains the other except where a rule explicitly
    says so."

    Design: Difficulty/non_linear_state_machine/program_documentation_dimension_advances_independently_of_placement_dimension
    """
    ctx = _firm_ordered_program_with_disclosure_acknowledged()
    set_clock(SLIP_FILING_INSTANT)
    file_document(ctx["program"]["id"], "SLIP", "NW-CAT-2026-SLIP")

    bound = bind_program(ctx["program"]["id"])

    assert_status(bound, "placement_status", "BOUND")
    assert_status(bound, "documentation_status", "SLIP_ISSUED")

    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "BOUND")
    assert_status(program, "documentation_status", "SLIP_ISSUED")
    assert_money_equals(
        program["gross_written_premium_minor"],
        CAT_GROSS_PREMIUM_MINOR,
        "gross_written_premium_minor",
    )


def test_the_slip_records_nineteen_whole_days_from_inception():
    """A slip filed at noon on day nineteen and a half floors to 19 days.

    PRD: "The system records the document's `program_id`, stamps `issued_at` with
    the current logical clock, records `filed_by_user_id` as the filing broker's
    identity, and computes `days_from_inception` as the whole number of days
    between the program's `inception_date` and `issued_at`: the elapsed seconds
    divided by eighty-six thousand four hundred, floored, which is negative when
    the document was filed before inception."

    Design: Difficulty/non_linear_state_machine/program_documentation_dimension_advances_independently_of_placement_dimension
    """
    ctx = _firm_ordered_program_with_disclosure_acknowledged()
    set_clock(SLIP_FILING_INSTANT)

    document = file_document(ctx["program"]["id"], "SLIP", "NW-CAT-2026-SLIP")

    assert_status(document, "document_type", "SLIP")
    assert document["days_from_inception"] == SLIP_DAYS_FROM_INCEPTION, (
        "a slip issued at 2026-01-20T12:00:00.000Z against a 2026-01-01 inception is "
        f"19 whole days from inception, got {document['days_from_inception']!r}"
    )
    assert_instant_equals(document["issued_at"], SLIP_FILING_INSTANT, "issued_at")


def test_the_contract_certainty_deadline_is_fixed_thirty_days_after_inception():
    """The 2026-01-01 inception fixes the certainty deadline at 2026-01-31.

    PRD: "At creation the program's `contract_certainty_deadline` is materialised
    as the `inception_date` advanced by thirty days, and `disclosure_acknowledged`
    is false."

    Design: Difficulty/non_linear_state_machine/program_documentation_dimension_advances_independently_of_placement_dimension
    """
    ctx = _firm_ordered_program_with_disclosure_acknowledged()

    program = read_program(ctx["program"]["id"])

    assert_instant_equals(
        program["contract_certainty_deadline"],
        CONTRACT_CERTAINTY_DEADLINE,
        "contract_certainty_deadline",
    )
    assert_instant_equals(program["inception_date"], CLOCK["INCEPTION"], "inception_date")


def test_binding_carries_the_layer_the_quote_and_the_line_to_bound():
    """The placement dimension's move to BOUND converts the whole placement below it.

    PRD: "Every quote on those layers still in `FIRM_ORDER` becomes `BOUND`."

    Design: Difficulty/non_linear_state_machine/program_documentation_dimension_advances_independently_of_placement_dimension
    """
    ctx = _firm_ordered_program_with_disclosure_acknowledged()
    set_clock(SLIP_FILING_INSTANT)
    file_document(ctx["program"]["id"], "SLIP", "NW-CAT-2026-SLIP")

    bind_program(ctx["program"]["id"])

    assert_status(read_layer(ctx["layer"]["id"]), "status", "BOUND")
    assert_status(read_quote(ctx["quotes"][0]["id"]), "status", "BOUND")
    assert_status(read_signing_line(ctx["signing_lines"][0]["id"]), "status", "BOUND")


def test_choosing_arbitration_forks_the_advocacy_and_accrues_the_arbitration_cost():
    """The 600,000,000 cession forks to ADVOCACY_ARBITRATION at a 9,000,000 cost.

    PRD: "Separately, `arbitration_cost_minor` is the `ceded_claim_minor`
    multiplied by one and a half per cent, rounded half up to whole minor units,
    when the `advocacy_route` is `ARBITRATION`, and 0 otherwise."

    Design: Difficulty/non_linear_state_machine/advocacy_forks_into_arbitration_freezing_collections_until_the_dispute_join
    """
    ctx = _disputed_advocacy_on_a_bound_cat_layer()
    assert_money_equals(
        ctx["advocacy"]["ceded_claim_minor"], CEDED_CLAIM_MINOR, "ceded_claim_minor"
    )
    assert_status(ctx["advocacy"], "status", "DISPUTED")
    assert_money_equals(
        ctx["advocacy"]["collectible_minor"],
        COLLECTIBLE_WHILE_DISPUTED_MINOR,
        "collectible_minor while the dispute is RAISED",
    )

    forked = set_advocacy_route(ctx["advocacy"]["id"], "ARBITRATION")

    assert_status(forked, "status", "ADVOCACY_ARBITRATION")
    assert_status(forked, "advocacy_route", "ARBITRATION")
    assert_money_equals(
        forked["arbitration_cost_minor"], ARBITRATION_COST_MINOR, "arbitration_cost_minor"
    )
    assert_money_equals(
        read_advocacy(ctx["advocacy"]["id"])["arbitration_cost_minor"],
        ARBITRATION_COST_MINOR,
        "arbitration_cost_minor read back",
    )


def test_the_arbitration_branch_freezes_collections_until_the_branch_joins():
    """A 500,000,000 collection is refused while the file sits in arbitration.

    PRD: "`ARBITRATION` sets `advocacy_route` to `ARBITRATION`, accrues
    `arbitration_cost_minor` as described above, moves the file to
    `ADVOCACY_ARBITRATION`, and **freezes collections**: no collection may be
    booked against a file sitting in `ADVOCACY_ARBITRATION`, and the attempt is
    `ERR_COLLECTION_BLOCKED_BY_ARBITRATION` until the branch joins."

    Design: Difficulty/non_linear_state_machine/advocacy_forks_into_arbitration_freezing_collections_until_the_dispute_join
    """
    ctx = _disputed_advocacy_on_a_bound_cat_layer()
    set_advocacy_route(ctx["advocacy"]["id"], "ARBITRATION")

    response = api_client.create_collection(
        ctx["advocacy"]["id"],
        create_collection_payload(
            ctx["signing_lines"][0]["id"], COLLECTIBLE_WHILE_DISPUTED_MINOR
        ),
        ACCOUNTANT,
    )

    validate_error(response, ApiErrorId.ERR_COLLECTION_BLOCKED_BY_ARBITRATION.value)
    advocacy = read_advocacy(ctx["advocacy"]["id"])
    assert_status(advocacy, "status", "ADVOCACY_ARBITRATION")
    assert_money_equals(advocacy["collected_minor"], 0, "collected_minor")


def test_withdrawing_the_last_raised_dispute_joins_the_branch_back_at_resolved():
    """Resolving the only dispute as WITHDRAWN rejoins the fork at RESOLVED.

    PRD: "When, after a resolution, **no** dispute of the file remains in
    `RAISED`, the file cascades from whichever branch it is on —
    `ADVOCACY_NEGOTIATION` or `ADVOCACY_ARBITRATION`, identically for both — to
    `RESOLVED`, recomputing `disputed_minor` and `collectible_minor` and
    refreshing the layer's `incurred_ceded_minor`."

    Design: Difficulty/non_linear_state_machine/advocacy_forks_into_arbitration_freezing_collections_until_the_dispute_join
    """
    ctx = _disputed_advocacy_on_a_bound_cat_layer()
    set_advocacy_route(ctx["advocacy"]["id"], "ARBITRATION")

    resolve_dispute(
        ctx["dispute"]["id"],
        "WITHDRAWN",
        DISPUTED_MINOR,
        resolution_note="market conceded the wording point",
    )

    assert_status(read_dispute(ctx["dispute"]["id"]), "status", "WITHDRAWN")
    advocacy = read_advocacy(ctx["advocacy"]["id"])
    assert_status(advocacy, "status", "RESOLVED")
    assert_money_equals(advocacy["disputed_minor"], 0, "disputed_minor")
    assert_money_equals(
        advocacy["collectible_minor"], CEDED_CLAIM_MINOR, "collectible_minor after the join"
    )


def test_a_withdrawn_dispute_contributes_nothing_to_the_disputed_total():
    """The 100,000,000 the market conceded in full drops out of disputed_minor.

    PRD: "Each dispute contributes according to its own status: a dispute still
    `RAISED` contributes its full `disputed_minor`; a dispute `UPHELD`, meaning
    the market's objection succeeded, also contributes its full `disputed_minor`;
    a dispute `SETTLED_PARTIAL` contributes its `disputed_minor` less the
    `settled_minor` the market conceded; and a `WITHDRAWN` dispute contributes
    nothing at all, because the market conceded in full."

    Design: Difficulty/non_linear_state_machine/advocacy_forks_into_arbitration_freezing_collections_until_the_dispute_join
    """
    ctx = _disputed_advocacy_on_a_bound_cat_layer()
    set_advocacy_route(ctx["advocacy"]["id"], "ARBITRATION")
    assert_money_equals(
        read_advocacy(ctx["advocacy"]["id"])["disputed_minor"],
        DISPUTED_MINOR,
        "disputed_minor while the dispute is RAISED",
    )

    resolve_dispute(
        ctx["dispute"]["id"],
        "WITHDRAWN",
        DISPUTED_MINOR,
        resolution_note="market conceded the wording point",
    )

    dispute = read_dispute(ctx["dispute"]["id"])
    assert_status(dispute, "status", "WITHDRAWN")
    assert_money_equals(dispute["settled_minor"], DISPUTED_MINOR, "settled_minor")
    advocacy = read_advocacy(ctx["advocacy"]["id"])
    assert_money_equals(advocacy["disputed_minor"], 0, "disputed_minor")
    assert_money_equals(advocacy["collectible_minor"], CEDED_CLAIM_MINOR, "collectible_minor")


def test_the_collection_booked_after_the_join_closes_the_file_at_collected():
    """A 600,000,000 collection is admitted once the branch has joined and closes the file.

    PRD: "When the recomputed `collected_minor` reaches or exceeds
    `collectible_minor`, the file becomes `COLLECTED`, which is terminal, and this
    is reachable both from `RESOLVED` and directly from `UNDER_REVIEW` when no
    dispute was ever raised on the file."

    Design: Difficulty/non_linear_state_machine/advocacy_forks_into_arbitration_freezing_collections_until_the_dispute_join
    """
    ctx = _disputed_advocacy_on_a_bound_cat_layer()
    set_advocacy_route(ctx["advocacy"]["id"], "ARBITRATION")
    resolve_dispute(
        ctx["dispute"]["id"],
        "WITHDRAWN",
        DISPUTED_MINOR,
        resolution_note="market conceded the wording point",
    )

    collection = collect(
        ctx["advocacy"]["id"], ctx["signing_lines"][0]["id"], CEDED_CLAIM_MINOR
    )

    advocacy = read_advocacy(ctx["advocacy"]["id"])
    assert_money_equals(advocacy["collected_minor"], CEDED_CLAIM_MINOR, "collected_minor")
    assert_status(advocacy, "status", "COLLECTED")
    assert_money_equals(
        advocacy["arbitration_cost_minor"],
        ARBITRATION_COST_MINOR,
        "arbitration_cost_minor survives the join and the collection",
    )
    assert collection["id"], "the collection answers with the fiduciary movement it created"


def test_the_collection_is_materialised_as_a_pending_claim_collection_movement():
    """The booked collection is a PENDING CLAIM_COLLECTION on the advocacy's program.

    PRD: "The collection is materialised as a `CLAIM_COLLECTION` fiduciary
    movement on the advocacy's program in status `PENDING`, linked to the same
    signing line, and that movement is the 201 response body."

    Design: Difficulty/non_linear_state_machine/advocacy_forks_into_arbitration_freezing_collections_until_the_dispute_join
    """
    ctx = _disputed_advocacy_on_a_bound_cat_layer()
    set_advocacy_route(ctx["advocacy"]["id"], "ARBITRATION")
    resolve_dispute(
        ctx["dispute"]["id"],
        "WITHDRAWN",
        DISPUTED_MINOR,
        resolution_note="market conceded the wording point",
    )

    collection = collect(
        ctx["advocacy"]["id"], ctx["signing_lines"][0]["id"], CEDED_CLAIM_MINOR
    )

    assert_status(collection, "txn_type", "CLAIM_COLLECTION")
    assert_status(collection, "status", "PENDING")
    assert_money_equals(collection["amount_minor"], CEDED_CLAIM_MINOR, "amount_minor")
    assert collection["signing_line_id"] == ctx["signing_lines"][0]["id"], (
        "the movement is linked to the same signing line the collection named"
    )
    assert collection["program_id"] == ctx["program"]["id"], (
        "the movement is booked on the advocacy's program"
    )

    stored = read_transaction(collection["id"])
    assert_status(stored, "txn_type", "CLAIM_COLLECTION")
    assert_status(stored, "status", "PENDING")
