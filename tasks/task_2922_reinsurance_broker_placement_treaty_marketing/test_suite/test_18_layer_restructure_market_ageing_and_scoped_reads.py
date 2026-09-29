"""Layer restructuring, market ageing, security posture and the scoped read surfaces.

Queue B — section ``endpoints``: the write endpoints that reshape a layer, age the
market and downgrade a counterparty, and the read endpoints that project money and
partition every child collection by its own parent (PRD §2.3, §3.1, §3.3, §3.4,
§3.5, §3.6, §3.7, §3.8, §3.9, §4).
"""
from test_helpers import (
    ACCOUNTANT,
    ACTUARY,
    CANONICAL_CAT_LAYER,
    CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR,
    CLOCK,
    COMPLIANCE,
    LEAD,
    ApiErrorId,
    acknowledge_disclosure,
    add_layer,
    add_quote,
    api_client,
    approve_transaction,
    assert_append_only_fields,
    assert_capacity_invariants,
    assert_cession_dispute,
    assert_claim_advocacy,
    assert_collectible_invariant,
    assert_contract_document,
    assert_instant_equals,
    assert_layer,
    assert_money_equals,
    assert_pct_equals,
    assert_placement_money_invariants,
    assert_program,
    assert_renewal_report,
    assert_status,
    bind_program,
    book_transaction,
    create_cedent,
    create_program,
    create_quote_payload,
    decline_payload,
    file_document,
    generate_renewal_report,
    go_to_market,
    market_sweep,
    notify_claim,
    place_line,
    place_lines,
    raise_dispute,
    read_advocacy,
    read_cedent,
    read_layer,
    read_market_submission,
    read_program,
    read_quote,
    read_reinsurer,
    read_signing_line,
    refresh,
    review_claim,
    send_submission,
    set_clock,
    set_market_security,
    settle_transaction,
    setup_draft_program,
    setup_program_in_market,
    setup_submission_ready_program,
    sign_off_exposure,
    update_layer_payload,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_program,
    withdraw_program_payload,
)

# Every market in this file is registered with the same generous aggregate so that
# capacity never becomes the binding constraint on a placement these tests build.
MARKET_CAPACITY_MINOR = 5_000_000_000

# The technical premium of CANONICAL_CAT_LAYER once base_rate_pct is restructured
# from 8.0000 to 7.0000: 1,250,000,000 x 7% = 87,500,000, loaded by one
# reinstatement to 91,875,000, then discounted 5% in the 25,000,000 tier.
RESTRUCTURED_CAT_LAYER_GROSS_PREMIUM_MINOR = 87_281_250

# A second layer on the same program, so that the layer collections have two rows
# to order and partition. Quota-share coherence: attachment 0, base rate == cession.
QS_LAYER_OVERRIDES = {
    "layer_label": "PROP QS 25 pct",
    "limit_minor": 400_000_000,
    "cession_pct": 25.0000,
    "base_rate_pct": 25.0000,
    "subject_premium_base_minor": 1_000_000_000,
    "expected_loss_cost_minor": 200_000_000,
    "ceding_commission_pct": 25.0000,
}

# The fully walked placement: 60 + 40 on a 1,000,000,000 CAT layer whose premium is
# 97,125,000, brokered at 2.5000%.
ALPHA_LINE_PCT = 60.0000
BRAVO_LINE_PCT = 40.0000
ALPHA_COMMITTED_MINOR = 600_000_000
ALPHA_AVAILABLE_AFTER_LINE_MINOR = 4_400_000_000
BOUND_BROKERAGE_MINOR = 2_428_125
BOUND_NET_REMITTANCE_MINOR = 94_696_875


def _market_spec(name: str, lead_authorised: bool = False):
    """One market register entry with enough aggregate for every line placed here."""
    return {
        "name": name,
        "security_rating": "AA",
        "capacity_limit_minor": MARKET_CAPACITY_MINOR,
        "max_line_pct": 100.0000,
        "lead_authorised": lead_authorised,
    }


ALPHA_ONLY = [_market_spec("Alpha Re", lead_authorised=True)]
ALPHA_AND_BRAVO = [_market_spec("Alpha Re", lead_authorised=True), _market_spec("Bravo Re")]
FOUR_MARKETS = [
    _market_spec("Alpha Re", lead_authorised=True),
    _market_spec("Bravo Re"),
    _market_spec("Charlie Re"),
    _market_spec("Delta Re"),
]


def _two_layer_draft_program():
    """A DRAFT program cut into the canonical CAT layer and a quota-share layer."""
    ctx = setup_draft_program(market_specs=ALPHA_ONLY)
    add_layer(ctx, "QUOTA_SHARE", **QS_LAYER_OVERRIDES)
    return ctx


def test_layer_creation_and_read_both_echo_the_structure_with_zeroed_placement_counters():
    """A new CAT layer reads back OPEN at 97,125,000 with every counter at zero.

    PRD: "A new layer opens with status `OPEN`, with `written_line_total_pct` and
    `signed_line_total_pct` at `0.0000`, with `limit_eroded_minor`,
    `reinstatements_used` and `incurred_ceded_minor` at 0, and with
    `loss_ratio_pct`, `provisional_ceding_commission_minor`,
    `final_ceding_commission_minor` and `ceding_commission_delta_minor` all null."

    Design: Corner/endpoints/layer_create_read_update_round_trip_and_the_update_window_closing
    """
    ctx = setup_draft_program(market_specs=ALPHA_ONLY)
    created = ctx["layer"]

    assert_layer(created)
    assert_status(created, "status", "OPEN")
    assert created["version"] == 1, "a freshly cut layer is at version 1"

    layer = validate_success(api_client.get_layer(created["id"], ACTUARY))
    assert layer["id"] == created["id"], "the read answers with the layer just created"
    assert layer["program_id"] == ctx["program"]["id"], "layer_id hangs off its program"
    assert layer["layer_label"] == CANONICAL_CAT_LAYER["layer_label"], "the label echoes"
    assert layer["layer_type"] == "CATASTROPHE", "layer_type echoes the structure supplied"
    assert_money_equals(
        layer["attachment_minor"], CANONICAL_CAT_LAYER["attachment_minor"], "attachment_minor"
    )
    assert_money_equals(layer["limit_minor"], CANONICAL_CAT_LAYER["limit_minor"], "limit_minor")
    assert_pct_equals(layer["base_rate_pct"], CANONICAL_CAT_LAYER["base_rate_pct"], "base_rate_pct")
    assert layer["excluded_perils"] == [], "excluded_perils defaults to an empty list"
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR,
        "quoted_gross_premium_minor",
    )
    assert_pct_equals(layer["written_line_total_pct"], 0.0000, "written_line_total_pct")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")
    assert_money_equals(layer["limit_eroded_minor"], 0, "limit_eroded_minor")
    assert layer["reinstatements_used"] == 0, "no reinstatement is used at creation"
    assert_money_equals(layer["incurred_ceded_minor"], 0, "incurred_ceded_minor")
    assert layer["loss_ratio_pct"] is None, "no loss experience exists on a new layer"
    assert layer["provisional_ceding_commission_minor"] is None, (
        "provisional_ceding_commission_minor is only fixed at binding"
    )
    assert layer["final_ceding_commission_minor"] is None, (
        "final_ceding_commission_minor is only fixed at settlement"
    )
    assert layer["ceding_commission_delta_minor"] is None, (
        "ceding_commission_delta_minor stays null until the commission reconciles"
    )


def test_restructuring_an_open_layer_while_the_program_is_draft_recomputes_the_premium():
    """Dropping base_rate_pct to 7.0000 reprices the layer to 87,281,250 at version 2.

    PRD: "A restructure accepts any subset of `layer_label`, `attachment_minor`,
    `limit_minor`, `base_rate_pct`, `subject_premium_base_minor`,
    `expected_loss_cost_minor`, `cession_pct`, `reinstatements_total`,
    `reinstatement_premium_pct`, `sublimit_minor`, `ceding_commission_pct` and
    `excluded_perils`, overwrites exactly what was supplied, recomputes the
    technical premium, and increments the layer's `version`."

    Design: Corner/endpoints/layer_create_read_update_round_trip_and_the_update_window_closing
    """
    ctx = setup_draft_program(market_specs=ALPHA_ONLY)
    assert_status(ctx["program"], "placement_status", "DRAFT")

    layer = validate_success(
        api_client.update_layer(
            ctx["layer"]["id"], update_layer_payload(base_rate_pct=7.0000), LEAD
        )
    )

    assert_pct_equals(layer["base_rate_pct"], 7.0000, "restructured base_rate_pct")
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        RESTRUCTURED_CAT_LAYER_GROSS_PREMIUM_MINOR,
        "recomputed quoted_gross_premium_minor",
    )
    assert layer["version"] == 2, "the restructure increments the layer version to 2"
    assert_status(layer, "status", "OPEN")
    assert_money_equals(
        layer["limit_minor"],
        CANONICAL_CAT_LAYER["limit_minor"],
        "limit_minor was not supplied so it is untouched",
    )
    assert_money_equals(
        read_layer(layer["id"])["quoted_gross_premium_minor"],
        RESTRUCTURED_CAT_LAYER_GROSS_PREMIUM_MINOR,
        "the read-back agrees with the PATCH response",
    )


def test_restructuring_a_label_and_exclusions_in_submission_ready_leaves_the_premium_alone():
    """A label and peril PATCH is legal while the program is SUBMISSION_READY and reprices nothing.

    PRD: "Restructuring is permitted only while the layer is `OPEN` — from any
    other layer status the attempt is `ERR_LAYER_STATE_INVALID` — and only while
    the owning program is `DRAFT` or `SUBMISSION_READY`."

    Design: Corner/endpoints/layer_create_read_update_round_trip_and_the_update_window_closing
    """
    ctx = setup_submission_ready_program(market_specs=ALPHA_ONLY)
    assert_status(ctx["program"], "placement_status", "SUBMISSION_READY")
    assert_status(read_layer(ctx["layer"]["id"]), "status", "OPEN")

    layer = validate_success(
        api_client.update_layer(
            ctx["layer"]["id"],
            update_layer_payload(
                layer_label="PROP CAT 1B xs 2B rev A", excluded_perils=["TERROR", "CYBER"]
            ),
            LEAD,
        )
    )

    assert layer["layer_label"] == "PROP CAT 1B xs 2B rev A", "the new label is stored"
    assert layer["excluded_perils"] == ["TERROR", "CYBER"], "both exclusions are stored"
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR,
        "recomputing from unchanged rating inputs returns the same premium",
    )
    assert layer["version"] == 2, "the restructure still increments the layer version"
    assert_status(layer, "status", "OPEN")


def test_restructuring_after_the_layer_goes_to_market_is_refused_and_the_premium_stays_frozen():
    """The first market submission closes the update window and freezes 97,125,000.

    PRD: "It is computed when the layer is created, recomputed on every restructure
    while the layer is still `OPEN`, and then **frozen for ever** the moment the
    layer goes to market."

    Design: Corner/endpoints/layer_create_read_update_round_trip_and_the_update_window_closing
    """
    ctx = setup_program_in_market(market_specs=ALPHA_ONLY)
    send_submission(ctx)
    assert_status(read_layer(ctx["layer"]["id"]), "status", "IN_MARKET")

    validate_error(
        api_client.update_layer(
            ctx["layer"]["id"], update_layer_payload(base_rate_pct=7.0000), LEAD
        ),
        ApiErrorId.ERR_LAYER_STATE_INVALID.value,
    )

    layer = read_layer(ctx["layer"]["id"])
    assert_status(layer, "status", "IN_MARKET")
    assert_pct_equals(layer["base_rate_pct"], 8.0000, "the refused rate change did not land")
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR,
        "the premium is frozen at the moment the layer went to market",
    )


def test_the_layer_collection_pages_and_orders_identically_from_the_program_and_the_root():
    """Two layers page one at a time from the program and read back in creation order.

    PRD: "Four pagination fields appear in the `meta` object of every list
    response: `limit` and `offset` echo the effective values used, `total_count`
    is the number of rows matching the request's filters **before** `limit` and
    `offset` are applied, and `has_more` is true exactly when the sum of `offset`
    and the number of rows returned in this page is less than `total_count`."

    Design: Corner/endpoints/layer_create_read_update_round_trip_and_the_update_window_closing
    """
    ctx = _two_layer_draft_program()
    cat_layer, qs_layer = ctx["layers"][0], ctx["layers"][1]
    program_id = ctx["program"]["id"]

    first_rows, first_meta = validate_paginated(
        api_client.list_program_layers(program_id, ACTUARY, params={"limit": 1, "offset": 0})
    )
    assert len(first_rows) == 1, "a limit of 1 returns exactly one layer"
    assert first_rows[0]["id"] == cat_layer["id"], "the earliest layer heads the collection"
    assert first_meta["total_count"] == 2, "total_count counts both layers before limit"
    assert first_meta["limit"] == 1, "limit echoes the effective value used"
    assert first_meta["offset"] == 0, "offset echoes the effective value used"
    assert first_meta["has_more"] is True, "0 + 1 is less than 2, so has_more is true"

    second_rows, second_meta = validate_paginated(
        api_client.list_program_layers(program_id, ACTUARY, params={"limit": 1, "offset": 1})
    )
    assert second_rows[0]["id"] == qs_layer["id"], "the second page carries the later layer"
    assert second_meta["has_more"] is False, "1 + 1 is not less than 2, so has_more is false"

    root_rows, root_meta = validate_paginated(api_client.list_layers(ACTUARY))
    assert root_meta["total_count"] == 2, "the flat collection sees the same two layers"
    assert root_meta["limit"] == 10, "an unspecified limit defaults to 10"
    assert root_meta["offset"] == 0, "an unspecified offset defaults to 0"
    assert root_meta["has_more"] is False, "0 + 2 is not less than 2, so has_more is false"
    assert [row["id"] for row in root_rows] == [cat_layer["id"], qs_layer["id"]], (
        "the flat collection agrees row for row with the parent-scoped collection"
    )


# The ageing clock and the four deadlines the sweep is asked to compare against it.
SWEEP_CLOCK = "2026-02-15T00:00:00.000Z"
LATE_DEADLINE = "2026-03-01T00:00:00.000Z"
EARLY_QUOTE_EXPIRY = "2026-02-01T00:00:00.000Z"
LATE_QUOTE_EXPIRY = "2026-03-01T00:00:00.000Z"


def _aged_market_program():
    """One layer out to four markets: a stale quote, a live quote, a declined quote, a bare SENT.

    Alpha's quote expires before the sweep instant, Bravo's after it, Charlie has
    walked away, and Delta's submission is left unanswered with its deadline landing
    exactly on the sweep instant.
    """
    ctx = setup_program_in_market(market_specs=FOUR_MARKETS)
    alpha_submission = send_submission(ctx, market_index=0, response_deadline=LATE_DEADLINE)
    add_quote(
        ctx,
        market_index=0,
        market_submission=alpha_submission,
        is_lead=False,
        expires_at=EARLY_QUOTE_EXPIRY,
    )
    bravo_submission = send_submission(ctx, market_index=1, response_deadline=LATE_DEADLINE)
    add_quote(
        ctx,
        market_index=1,
        market_submission=bravo_submission,
        is_lead=False,
        expires_at=LATE_QUOTE_EXPIRY,
    )
    charlie_submission = send_submission(ctx, market_index=2, response_deadline=LATE_DEADLINE)
    charlie_quote = add_quote(
        ctx,
        market_index=2,
        market_submission=charlie_submission,
        is_lead=False,
        expires_at=LATE_QUOTE_EXPIRY,
    )
    validate_success(
        api_client.decline_quote(
            charlie_quote["id"], decline_payload(), ctx["market_headers"][2]
        )
    )
    send_submission(ctx, market_index=3, response_deadline=SWEEP_CLOCK)
    return ctx


def test_the_market_sweep_ages_only_the_rows_whose_own_deadline_has_passed():
    """At 2026-02-15 only Delta's SENT submission expires and only Alpha's quote lapses.

    PRD: "The sweep expires every market submission on the program's layers that is
    still in `SENT` and whose `response_deadline` is at or before the current
    logical-clock instant, moving it to `EXPIRED`, and it lapses every quote on
    those layers in `QUOTED`, `COUNTERED` or `REQUOTED` whose `expires_at` is at or
    before that instant, moving it to `LAPSED`."

    Design: Corner/endpoints/market_sweep_ages_only_the_rows_whose_own_deadline_passed
    """
    ctx = _aged_market_program()
    alpha_ms, bravo_ms, charlie_ms, delta_ms = ctx["market_submissions"]
    alpha_quote, bravo_quote, charlie_quote = ctx["quotes"]

    set_clock(SWEEP_CLOCK)
    market_sweep(ctx["program"]["id"])

    assert_status(read_market_submission(delta_ms["id"]), "status", "EXPIRED")
    assert_status(read_quote(alpha_quote["id"]), "status", "LAPSED")
    assert_status(read_quote(bravo_quote["id"]), "status", "QUOTED")
    assert_status(read_market_submission(alpha_ms["id"]), "status", "QUOTED")
    assert_status(read_market_submission(bravo_ms["id"]), "status", "QUOTED")
    assert_status(read_market_submission(charlie_ms["id"]), "status", "DECLINED")
    assert_status(read_quote(charlie_quote["id"]), "status", "DECLINED")


def test_the_sweep_moves_no_layer_or_program_status_and_a_second_sweep_changes_nothing():
    """The swept layer stays IN_MARKET at 0.0000 written and re-sweeping is a no-op.

    PRD: "The sweep deliberately changes **no** layer status and **no** program
    status — an unplaced layer stays `IN_MARKET` and the broker must decide what to
    do about it."

    Design: Corner/endpoints/market_sweep_ages_only_the_rows_whose_own_deadline_passed
    """
    ctx = _aged_market_program()
    alpha_quote, bravo_quote, charlie_quote = ctx["quotes"]
    delta_ms = ctx["market_submissions"][3]

    set_clock(SWEEP_CLOCK)
    market_sweep(ctx["program"]["id"])

    layer = read_layer(ctx["layer"]["id"])
    assert_status(layer, "status", "IN_MARKET")
    assert_pct_equals(layer["written_line_total_pct"], 0.0000, "written_line_total_pct")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "IN_MARKET")

    market_sweep(ctx["program"]["id"])

    assert_status(read_market_submission(delta_ms["id"]), "status", "EXPIRED")
    assert_status(read_quote(alpha_quote["id"]), "status", "LAPSED")
    assert_status(read_quote(bravo_quote["id"]), "status", "QUOTED")
    assert_status(read_layer(ctx["layer"]["id"]), "status", "IN_MARKET")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "IN_MARKET")

    rows, meta = validate_paginated(
        api_client.list_quotes(LEAD, params={"layer_id": ctx["layer"]["id"]})
    )
    assert meta["total_count"] == 3, "three markets answered the layer"
    assert [row["id"] for row in rows] == [
        alpha_quote["id"],
        bravo_quote["id"],
        charlie_quote["id"],
    ], "the quotes on the layer come back in ascending created_at order"


def _sixty_forty_placement(alpha_security=None):
    """Alpha writes 60 and Bravo 40 on one CAT layer, filling it to exactly 100."""
    ctx = setup_program_in_market(market_specs=ALPHA_AND_BRAVO)
    if alpha_security is not None:
        set_market_security(ctx["reinsurers"][0]["id"], alpha_security, "Rating on watch")
    place_lines(
        ctx,
        [
            {"market_index": 0, "accepted_line_pct": ALPHA_LINE_PCT},
            {"market_index": 1, "accepted_line_pct": BRAVO_LINE_PCT},
        ],
    )
    return refresh(ctx)


def test_restricting_a_market_leaves_its_capacity_intact_but_refuses_a_lead_quote():
    """A RESTRICTED market keeps lead_authorised true and its whole aggregate, yet cannot lead.

    PRD: "And setting `is_lead` to true requires the quoting market to have
    `lead_authorised` true **and** `security_status` exactly `APPROVED`; a
    `RESTRICTED` market may follow but never lead, and either failure is
    `ERR_LEAD_NOT_AUTHORISED`."

    Design: Corner/endpoints/security_status_action_downgrades_the_market_and_is_not_an_undo_button
    """
    ctx = setup_program_in_market(market_specs=ALPHA_AND_BRAVO)
    set_market_security(ctx["reinsurers"][0]["id"], "RESTRICTED", "Rating on watch")

    alpha = read_reinsurer(ctx["reinsurers"][0]["id"])
    assert_status(alpha, "security_status", "RESTRICTED")
    assert alpha["lead_authorised"] is True, (
        "the downgrade touches the posture, not the market's standing lead permission"
    )
    assert_money_equals(alpha["committed_capacity_minor"], 0, "committed_capacity_minor")
    assert_money_equals(
        alpha["available_capacity_minor"], MARKET_CAPACITY_MINOR, "available_capacity_minor"
    )
    assert_capacity_invariants(alpha)

    submission = send_submission(ctx, market_index=0)
    validate_error(
        api_client.create_quote(
            submission["id"], create_quote_payload(is_lead=True), ctx["market_headers"][0]
        ),
        ApiErrorId.ERR_LEAD_NOT_AUTHORISED.value,
    )
    assert_status(read_market_submission(submission["id"]), "status", "SENT")


def test_a_restricted_market_may_still_follow_and_its_line_fills_the_layer():
    """Alpha writes 60 while RESTRICTED and Bravo's 40 carries the layer to FULLY_PLACED.

    PRD: "Then the quoting market's `security_status` must be either `APPROVED` or
    `RESTRICTED`, since a `SUSPENDED` market cannot be firm-ordered, else
    `ERR_MARKET_SUSPENDED`."

    Design: Corner/endpoints/security_status_action_downgrades_the_market_and_is_not_an_undo_button
    """
    ctx = _sixty_forty_placement("RESTRICTED")

    assert_status(ctx["reinsurers"][0], "security_status", "RESTRICTED")
    alpha_line = read_signing_line(ctx["signing_lines"][0]["id"])
    assert_status(alpha_line, "status", "PROVISIONAL")
    assert_pct_equals(alpha_line["written_line_pct"], ALPHA_LINE_PCT, "written_line_pct")
    assert_pct_equals(alpha_line["effective_line_pct"], ALPHA_LINE_PCT, "effective_line_pct")

    layer = ctx["layers"][0]
    assert_status(layer, "status", "FULLY_PLACED")
    assert_pct_equals(layer["written_line_total_pct"], 100.0000, "written_line_total_pct")
    assert_status(ctx["program"], "placement_status", "FIRM_ORDER")

    assert_money_equals(
        ctx["reinsurers"][0]["committed_capacity_minor"],
        ALPHA_COMMITTED_MINOR,
        "Alpha's committed_capacity_minor",
    )
    assert_money_equals(
        ctx["reinsurers"][0]["available_capacity_minor"],
        ALPHA_AVAILABLE_AFTER_LINE_MINOR,
        "Alpha's available_capacity_minor",
    )


def test_suspending_a_market_releases_its_live_line_and_restoring_approval_is_not_an_undo():
    """Suspension releases Alpha's line for SECURITY_FAILURE and re-approval does not revive it.

    PRD: "Every signing line of the suspended market that is `PROVISIONAL` or
    `SIGNED` and sits on a layer that is not `BOUND` becomes `RELEASED` with
    `release_reason` set to `SECURITY_FAILURE`; that is hop one."

    Design: Corner/endpoints/security_status_action_downgrades_the_market_and_is_not_an_undo_button
    """
    ctx = _sixty_forty_placement()
    alpha_line, bravo_line = ctx["signing_lines"]
    alpha_quote = ctx["quotes"][0]

    set_market_security(ctx["reinsurers"][0]["id"], "SUSPENDED", "Rating downgrade")

    released = read_signing_line(alpha_line["id"])
    assert_status(released, "status", "RELEASED")
    assert released["release_reason"] == "SECURITY_FAILURE", (
        "the release reason names the security cascade that caused it"
    )
    assert_status(read_quote(alpha_quote["id"]), "status", "LAPSED")
    assert_status(read_signing_line(bravo_line["id"]), "status", "PROVISIONAL")

    layer = read_layer(ctx["layers"][0]["id"])
    assert_status(layer, "status", "PARTIALLY_PLACED")
    assert_pct_equals(layer["written_line_total_pct"], BRAVO_LINE_PCT, "written_line_total_pct")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "IN_MARKET")

    alpha = read_reinsurer(ctx["reinsurers"][0]["id"])
    assert_money_equals(alpha["committed_capacity_minor"], 0, "committed_capacity_minor")
    assert_money_equals(
        alpha["available_capacity_minor"],
        MARKET_CAPACITY_MINOR,
        "releasing the line hands the whole aggregate back",
    )

    set_market_security(ctx["reinsurers"][0]["id"], "APPROVED", "Rating restored")

    restored = read_reinsurer(ctx["reinsurers"][0]["id"])
    assert_status(restored, "security_status", "APPROVED")
    assert_money_equals(
        restored["committed_capacity_minor"], 0, "re-approval reserves nothing again"
    )
    assert_status(read_signing_line(alpha_line["id"]), "status", "RELEASED")
    assert_status(read_quote(alpha_quote["id"]), "status", "LAPSED")
    assert_status(read_layer(ctx["layers"][0]["id"]), "status", "PARTIALLY_PLACED")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "IN_MARKET")


def _two_layer_program_in_market():
    """Both layers are cut while the file is DRAFT, then the program is released to market."""
    ctx = setup_draft_program(market_specs=ALPHA_AND_BRAVO)
    add_layer(ctx, "QUOTA_SHARE", **QS_LAYER_OVERRIDES)
    ctx["submission"] = sign_off_exposure(ctx["submission"]["id"])
    ctx["program"] = go_to_market(ctx["program"]["id"])
    return ctx


def test_market_submissions_partition_by_their_layer_and_by_their_market():
    """Three submissions across two layers and two markets answer only under their own parents.

    PRD: "A market submission is created in status `SENT`, with `layer_id` taken
    from the layer it was created under, `sent_at` stamped with the current
    logical-clock instant and `submitted_by_user_id` recording the releasing
    broker's `X-User-ID`."

    Design: Corner/endpoints/parent_scoped_child_collections_never_leak_a_sibling_parents_rows
    """
    ctx = _two_layer_program_in_market()
    cat_layer, qs_layer = ctx["layers"][0], ctx["layers"][1]
    alpha, bravo = ctx["reinsurers"][0], ctx["reinsurers"][1]

    cat_to_alpha = send_submission(ctx, market_index=0, layer_index=0)
    cat_to_bravo = send_submission(ctx, market_index=1, layer_index=0)
    qs_to_alpha = send_submission(ctx, market_index=0, layer_index=1)

    cat_rows, cat_meta = validate_paginated(
        api_client.list_layer_market_submissions(cat_layer["id"], LEAD)
    )
    assert cat_meta["total_count"] == 2, "the CAT layer went to two markets"
    assert [row["id"] for row in cat_rows] == [cat_to_alpha["id"], cat_to_bravo["id"]], (
        "the CAT layer's collection holds only its own submissions"
    )

    qs_rows, qs_meta = validate_paginated(
        api_client.list_layer_market_submissions(qs_layer["id"], LEAD)
    )
    assert qs_meta["total_count"] == 1, "the quota-share layer went to one market"
    assert qs_rows[0]["id"] == qs_to_alpha["id"], "no sibling layer's submission leaks in"
    assert qs_rows[0]["layer_id"] == qs_layer["id"], "layer_id names the layer it was sent under"

    alpha_rows, alpha_meta = validate_paginated(
        api_client.list_reinsurer_market_submissions(alpha["id"], LEAD)
    )
    assert alpha_meta["total_count"] == 2, "Alpha was approached on both layers"
    assert [row["id"] for row in alpha_rows] == [cat_to_alpha["id"], qs_to_alpha["id"]], (
        "the market axis cuts the same three rows the other way"
    )

    bravo_rows, bravo_meta = validate_paginated(
        api_client.list_reinsurer_market_submissions(bravo["id"], LEAD)
    )
    assert bravo_meta["total_count"] == 1, "Bravo was approached on one layer only"
    assert bravo_rows[0]["id"] == cat_to_bravo["id"], "Alpha's submissions stay out of Bravo's list"

    root_rows, root_meta = validate_paginated(api_client.list_market_submissions(LEAD))
    assert root_meta["total_count"] == 3, "the flat collection holds every submission once"
    assert [row["id"] for row in root_rows] == [
        cat_to_alpha["id"],
        cat_to_bravo["id"],
        qs_to_alpha["id"],
    ], "the flat collection is the union of the parent-scoped collections, in creation order"


def test_program_layer_and_signing_line_collections_never_leak_a_sibling_parents_rows():
    """A market that wrote no line and a program with no layers both read back empty.

    PRD: "The first hop creates a signing line whose `layer_id`, `quote_id` and
    `reinsurer_id` identify the layer, the quote and the market, whose
    `written_line_pct` is copied from the `accepted_line_pct` just accepted and is
    **never mutated again**, whose `signed_line_pct` is null, and whose status is
    `PROVISIONAL`."

    Design: Corner/endpoints/parent_scoped_child_collections_never_leak_a_sibling_parents_rows
    """
    ctx = setup_program_in_market(market_specs=ALPHA_AND_BRAVO)
    alpha_line = place_line(ctx, market_index=0, accepted_line_pct=ALPHA_LINE_PCT)
    alpha, bravo = ctx["reinsurers"][0], ctx["reinsurers"][1]

    other_cedent = create_cedent(name="Southgate Insurance")
    other_program = create_program(
        other_cedent["id"], program_name="Southgate Property 2026"
    )

    alpha_rows, alpha_meta = validate_paginated(
        api_client.list_reinsurer_signing_lines(alpha["id"], LEAD)
    )
    assert alpha_meta["total_count"] == 1, "Alpha holds exactly the one line it wrote"
    assert alpha_rows[0]["id"] == alpha_line["id"], "the line under Alpha is Alpha's own"
    assert alpha_rows[0]["reinsurer_id"] == alpha["id"], "reinsurer_id names the writing market"
    assert alpha_rows[0]["layer_id"] == ctx["layer"]["id"], "layer_id names the layer written"

    bravo_rows, bravo_meta = validate_paginated(
        api_client.list_reinsurer_signing_lines(bravo["id"], LEAD)
    )
    assert bravo_rows == [], "a market that never wrote a line answers with no rows"
    assert bravo_meta["total_count"] == 0, "and with a total_count of zero"
    assert bravo_meta["has_more"] is False, "0 + 0 is not less than 0, so has_more is false"

    own_rows, own_meta = validate_paginated(
        api_client.list_cedent_programs(ctx["cedent"]["id"], LEAD)
    )
    assert own_meta["total_count"] == 1, "each cedent sees only its own placement file"
    assert own_rows[0]["id"] == ctx["program"]["id"], "and that file is the one it owns"

    other_rows, other_meta = validate_paginated(
        api_client.list_programs(LEAD, params={"cedent_id": other_cedent["id"]})
    )
    assert other_meta["total_count"] == 1, "the declared cedent_id filter cuts the same way"
    assert other_rows[0]["id"] == other_program["id"], "the second cedent's file is its own"

    layer_rows, layer_meta = validate_paginated(
        api_client.list_program_layers(other_program["id"], LEAD)
    )
    assert layer_rows == [], "a program that was never cut into layers answers with no rows"
    assert layer_meta["total_count"] == 0, "and with a total_count of zero"

    own_layer_rows, own_layer_meta = validate_paginated(
        api_client.list_program_layers(ctx["program"]["id"], LEAD)
    )
    assert own_layer_meta["total_count"] == 1, "the placed program keeps its single layer"
    assert own_layer_rows[0]["id"] == ctx["layer"]["id"], "no sibling program's layer leaks in"


def _bound_sixty_forty():
    """The 60/40 placement carried through an acknowledged disclosure into BOUND."""
    ctx = _sixty_forty_placement()
    program = read_program(ctx["program"]["id"])
    ctx["disclosure"] = acknowledge_disclosure(
        program["id"], ctx["cedent"]["id"], program["brokerage_pct"]
    )
    ctx["program"] = bind_program(program["id"])
    return refresh(ctx)


def test_a_newly_opened_placement_file_reads_its_five_money_aggregates_at_zero():
    """A DRAFT program projects no premium, no brokerage, no remittance and no balance.

    PRD: "Five money aggregates — `gross_written_premium_minor`,
    `brokerage_earned_minor`, `net_remittance_minor`, `rounding_residue_minor` and
    `fiduciary_holding_minor` — all initialise to 0, and `withdrawal_reason` is
    null."

    Design: Corner/endpoints/computed_reads_project_placement_money_and_the_fiduciary_balance_from_children
    """
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    created = create_program(cedent["id"])

    program = validate_success(api_client.get_program(created["id"], ACCOUNTANT))

    assert_program(program)
    assert_status(program, "placement_status", "DRAFT")
    assert_money_equals(program["gross_written_premium_minor"], 0, "gross_written_premium_minor")
    assert_money_equals(program["brokerage_earned_minor"], 0, "brokerage_earned_minor")
    assert_money_equals(program["net_remittance_minor"], 0, "net_remittance_minor")
    assert_money_equals(program["rounding_residue_minor"], 0, "rounding_residue_minor")
    assert_money_equals(program["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")
    assert program["withdrawal_reason"] is None, "nothing has been abandoned yet"
    assert program["disclosure_acknowledged"] is False, "no disclosure has been acknowledged"
    assert_placement_money_invariants(program)


def test_firm_ordering_reserves_the_line_but_computes_none_of_the_placement_money():
    """At FIRM_ORDER the money is still zero and the reserved line carries no signed line.

    PRD: "The money on the program is computed at binding, and the order of
    rounding and summation is pinned because it is observable in the result."

    Design: Corner/endpoints/computed_reads_project_placement_money_and_the_fiduciary_balance_from_children
    """
    ctx = _sixty_forty_placement()
    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "FIRM_ORDER")
    assert_money_equals(program["gross_written_premium_minor"], 0, "gross_written_premium_minor")
    assert_money_equals(program["brokerage_earned_minor"], 0, "brokerage_earned_minor")
    assert_money_equals(program["net_remittance_minor"], 0, "net_remittance_minor")
    assert_money_equals(program["rounding_residue_minor"], 0, "rounding_residue_minor")

    acknowledge_disclosure(program["id"], ctx["cedent"]["id"], program["brokerage_pct"])

    acknowledged = read_program(program["id"])
    assert acknowledged["disclosure_acknowledged"] is True, (
        "acknowledging the disclosure unblocks binding without moving any money"
    )
    assert_money_equals(
        acknowledged["gross_written_premium_minor"], 0, "gross_written_premium_minor"
    )
    assert_money_equals(acknowledged["brokerage_earned_minor"], 0, "brokerage_earned_minor")
    assert_money_equals(acknowledged["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")

    alpha_line = read_signing_line(ctx["signing_lines"][0]["id"])
    assert_status(alpha_line, "status", "PROVISIONAL")
    assert_pct_equals(alpha_line["written_line_pct"], ALPHA_LINE_PCT, "written_line_pct")
    assert alpha_line["signed_line_pct"] is None, (
        "a provisional line has not been allocated a signed line yet"
    )
    assert_pct_equals(alpha_line["effective_line_pct"], ALPHA_LINE_PCT, "effective_line_pct")


def test_binding_projects_the_placement_money_and_the_capacity_from_the_bound_lines():
    """A 60/40 bind reads back 97,125,000 gross, 2,428,125 brokerage and a zero residue.

    PRD: "Its `rounding_residue_minor` is the gross written premium less the sum of
    `brokerage_earned_minor` and `net_remittance_minor`, and it exists precisely so
    that the penny the per-line rounding creates or destroys is visible rather than
    hidden."

    Design: Corner/endpoints/computed_reads_project_placement_money_and_the_fiduciary_balance_from_children
    """
    ctx = _bound_sixty_forty()

    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "BOUND")
    assert_money_equals(
        program["gross_written_premium_minor"],
        CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR,
        "gross_written_premium_minor",
    )
    assert_money_equals(
        program["brokerage_earned_minor"], BOUND_BROKERAGE_MINOR, "brokerage_earned_minor"
    )
    assert_money_equals(
        program["net_remittance_minor"], BOUND_NET_REMITTANCE_MINOR, "net_remittance_minor"
    )
    assert_money_equals(program["rounding_residue_minor"], 0, "rounding_residue_minor")
    assert_placement_money_invariants(program)

    layer = read_layer(ctx["layers"][0]["id"])
    assert_status(layer, "status", "BOUND")
    assert_pct_equals(layer["written_line_total_pct"], 100.0000, "written_line_total_pct")
    assert_pct_equals(layer["signed_line_total_pct"], 100.0000, "signed_line_total_pct")
    assert_money_equals(
        layer["quoted_gross_premium_minor"],
        CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR,
        "binding never moves the technical premium",
    )
    assert layer["provisional_ceding_commission_minor"] is None, (
        "an excess layer carries no ceding commission at binding"
    )

    alpha_line = read_signing_line(ctx["signing_lines"][0]["id"])
    assert_status(alpha_line, "status", "BOUND")
    assert_pct_equals(alpha_line["signed_line_pct"], ALPHA_LINE_PCT, "signed_line_pct")
    assert_money_equals(
        alpha_line["committed_capacity_minor"],
        ALPHA_COMMITTED_MINOR,
        "committed_capacity_minor",
    )

    alpha = read_reinsurer(ctx["reinsurers"][0]["id"])
    assert_money_equals(
        alpha["committed_capacity_minor"], ALPHA_COMMITTED_MINOR, "committed_capacity_minor"
    )
    assert_money_equals(
        alpha["available_capacity_minor"],
        ALPHA_AVAILABLE_AFTER_LINE_MINOR,
        "available_capacity_minor",
    )
    assert_capacity_invariants(alpha)


def test_only_a_settled_movement_moves_the_fiduciary_balance_and_the_cedent_receipts():
    """Booking and approving a 97,125,000 receipt moves nothing; settling it moves everything.

    PRD: "Movements in `PENDING`, `APPROVED` or `HELD` are invisible to the
    balance: booking, approving and holding a movement never move money."

    Design: Corner/endpoints/computed_reads_project_placement_money_and_the_fiduciary_balance_from_children
    """
    ctx = _bound_sixty_forty()
    program_id = ctx["program"]["id"]
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"], 0, "fiduciary_holding_minor"
    )

    receipt = book_transaction(
        program_id, "CEDENT_RECEIPT", CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR
    )
    assert_status(receipt, "status", "PENDING")
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        0,
        "a PENDING movement is invisible to the balance",
    )

    approve_transaction(receipt["id"])
    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        0,
        "an APPROVED movement is invisible to the balance",
    )
    assert_money_equals(
        read_cedent(ctx["cedent"]["id"])["settled_receipts_minor"],
        0,
        "settled_receipts_minor counts only SETTLED receipts",
    )

    settle_transaction(receipt["id"])

    assert_money_equals(
        read_program(program_id)["fiduciary_holding_minor"],
        CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR,
        "settlement is where the balance actually changes",
    )
    assert_money_equals(
        read_cedent(ctx["cedent"]["id"])["settled_receipts_minor"],
        CANONICAL_CAT_LAYER_GROSS_PREMIUM_MINOR,
        "settled_receipts_minor",
    )

    nested_rows, nested_meta = validate_paginated(
        api_client.list_program_fiduciary_transactions(program_id, ACCOUNTANT)
    )
    assert nested_meta["total_count"] == 1, "one movement has been booked on this program"
    assert nested_rows[0]["id"] == receipt["id"], "the ledger row is the receipt just settled"
    assert_status(nested_rows[0], "status", "SETTLED")

    root_rows, root_meta = validate_paginated(
        api_client.list_fiduciary_transactions(ACCOUNTANT, params={"program_id": program_id})
    )
    assert root_meta["total_count"] == 1, "the declared program_id filter cuts the same row"
    assert root_rows[0]["id"] == receipt["id"], "the flat ledger agrees with the nested one"


FIRST_WITHDRAWAL_REASON = "Cedent cancelled the renewal"


def _bare_draft_program():
    """A placement file with no exposure package, no layer and no market activity."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent(name="Southgate Insurance")
    program = create_program(cedent["id"], program_name="Southgate Property 2026")
    return cedent, program


def test_withdrawing_a_draft_program_writes_one_status_and_has_nothing_to_unwind():
    """A bare DRAFT file goes straight to WITHDRAWN with its reason and one version step.

    PRD: "Withdrawal from `DRAFT` or `SUBMISSION_READY` has nothing to unwind and
    simply moves `placement_status` to `WITHDRAWN` and increments the program's
    `version`."

    Design: Corner/endpoints/withdraw_accepts_four_states_and_cascades_only_onto_the_children_that_exist
    """
    _cedent, created = _bare_draft_program()
    assert_status(created, "placement_status", "DRAFT")

    withdrawn = withdraw_program(created["id"], reason=FIRST_WITHDRAWAL_REASON)

    assert_status(withdrawn, "placement_status", "WITHDRAWN")
    assert withdrawn["withdrawal_reason"] == FIRST_WITHDRAWAL_REASON, (
        "the reason supplied is captured as withdrawal_reason"
    )
    assert withdrawn["version"] == created["version"] + 1, (
        "withdrawal increments the program version exactly once"
    )
    assert_status(withdrawn, "documentation_status", "NOT_STARTED")

    program = read_program(created["id"])
    assert_status(program, "placement_status", "WITHDRAWN")
    assert program["withdrawal_reason"] == FIRST_WITHDRAWAL_REASON, "the read-back agrees"


def test_withdrawing_from_in_market_cascades_onto_every_child_that_exists():
    """Two layers lapse, two submissions close, the one quote lapses and capacity comes back.

    PRD: "Withdrawal from `IN_MARKET` or from `FIRM_ORDER` runs an identical, larger
    cascade: every layer of the program whose status is not `BOUND` becomes
    `LAPSED`; every signing line on those layers in `PROVISIONAL` or `SIGNED`
    becomes `RELEASED` with `release_reason` set to `PROGRAM_WITHDRAWN`; every quote
    on those layers in `QUOTED`, `COUNTERED`, `REQUOTED` or `FIRM_ORDER` becomes
    `LAPSED`; every market submission on those layers in `SENT` or `QUOTED` becomes
    `CLOSED`; `committed_capacity_minor` is recomputed for every market whose lines
    were handed back; and only then does `placement_status` become `WITHDRAWN` with
    the program's `version` incremented."

    Design: Corner/endpoints/withdraw_accepts_four_states_and_cascades_only_onto_the_children_that_exist
    """
    ctx = _two_layer_program_in_market()
    cat_layer, qs_layer = ctx["layers"][0], ctx["layers"][1]
    cat_submission = send_submission(ctx, market_index=0, layer_index=0)
    qs_submission = send_submission(ctx, market_index=0, layer_index=1)
    quote = add_quote(ctx, market_index=0, market_submission=cat_submission, is_lead=False)

    withdrawn = withdraw_program(ctx["program"]["id"], reason=FIRST_WITHDRAWAL_REASON)

    assert_status(withdrawn, "placement_status", "WITHDRAWN")
    assert_status(read_layer(cat_layer["id"]), "status", "LAPSED")
    assert_status(read_layer(qs_layer["id"]), "status", "LAPSED")
    assert_status(read_market_submission(cat_submission["id"]), "status", "CLOSED")
    assert_status(read_market_submission(qs_submission["id"]), "status", "CLOSED")
    assert_status(read_quote(quote["id"]), "status", "LAPSED")

    alpha = read_reinsurer(ctx["reinsurers"][0]["id"])
    assert_money_equals(
        alpha["committed_capacity_minor"], 0, "no line was ever written, so nothing was committed"
    )
    assert_money_equals(
        alpha["available_capacity_minor"], MARKET_CAPACITY_MINOR, "available_capacity_minor"
    )

    line_rows, line_meta = validate_paginated(
        api_client.list_signing_lines(LEAD, params={"layer_id": cat_layer["id"]})
    )
    assert line_rows == [], "the cascade had no signing line to hand back"
    assert line_meta["total_count"] == 0, "and the line collection stays empty"


def test_a_second_withdrawal_is_refused_and_the_first_reason_survives():
    """WITHDRAWN is not one of the four admitting states, so the second attempt is refused.

    PRD: "The placing broker may withdraw a placement from `DRAFT`,
    `SUBMISSION_READY`, `IN_MARKET` or `FIRM_ORDER`, supplying a `reason` that is
    captured as `withdrawal_reason`; from any other placement state the attempt is
    `ERR_PROGRAM_STATE_INVALID`."

    Design: Corner/endpoints/withdraw_accepts_four_states_and_cascades_only_onto_the_children_that_exist
    """
    _cedent, created = _bare_draft_program()
    withdraw_program(created["id"], reason=FIRST_WITHDRAWAL_REASON)

    validate_error(
        api_client.withdraw_program(
            created["id"], withdraw_program_payload(reason="Second attempt"), LEAD
        ),
        ApiErrorId.ERR_PROGRAM_STATE_INVALID.value,
    )

    program = read_program(created["id"])
    assert_status(program, "placement_status", "WITHDRAWN")
    assert program["withdrawal_reason"] == FIRST_WITHDRAWAL_REASON, (
        "the refused second withdrawal did not overwrite the reason on file"
    )


# The claim walked through the placement: 2,300,000,000 gross pierces the 2,000,000,000
# attachment by 300,000,000, of which the writing market contests 50,000,000.
WALKED_CLAIM_GROSS_MINOR = 2_300_000_000
WALKED_CEDED_MINOR = 300_000_000
WALKED_DISPUTED_MINOR = 50_000_000
WALKED_COLLECTIBLE_MINOR = 250_000_000

# 100 x 97,125,000 / 1,000,000,000 of bound limit, and 100 signed over 100 written.
WALKED_RATE_ON_LINE_PCT = 9.7125
WALKED_PLACEMENT_EFFICIENCY_PCT = 100.00


def _walked_placement():
    """One placement walked end to end: bound 60/40, documented, reported and disputed."""
    ctx = _bound_sixty_forty()
    program_id = ctx["program"]["id"]
    ctx["documents"] = [
        file_document(program_id, "SLIP", "NM-SLIP-1"),
        file_document(program_id, "WORDING_DRAFT", "NM-WORD-1"),
        file_document(program_id, "AGREED_WORDING", "NM-AGREED-1"),
    ]
    ctx["report"] = generate_renewal_report(program_id)
    advocacy = notify_claim(
        ctx["layers"][0]["id"],
        ctx["cedent"]["id"],
        gross_claim_minor=WALKED_CLAIM_GROSS_MINOR,
    )
    review_claim(advocacy["id"])
    ctx["dispute"] = raise_dispute(
        advocacy["id"],
        ctx["reinsurers"][0]["id"],
        ctx["signing_lines"][0]["id"],
        WALKED_DISPUTED_MINOR,
    )
    ctx["advocacy"] = read_advocacy(advocacy["id"])
    return ctx


def test_the_documentation_trail_reads_in_filing_order_from_the_program_and_from_the_root():
    """Slip, wording draft and agreed wording come back in the order they were filed.

    PRD: "Collections are returned in ascending `created_at` order."

    Design: Corner/endpoints/every_declared_read_surface_answers_from_one_fully_walked_placement
    """
    ctx = _walked_placement()
    slip, draft, agreed = ctx["documents"]

    nested_rows, nested_meta = validate_paginated(
        api_client.list_program_contract_documents(ctx["program"]["id"], COMPLIANCE)
    )
    assert nested_meta["total_count"] == 3, "three documents have been filed on the program"
    assert [row["id"] for row in nested_rows] == [slip["id"], draft["id"], agreed["id"]], (
        "the trail reads slip, then wording draft, then agreed wording"
    )
    assert [row["document_type"] for row in nested_rows] == [
        "SLIP",
        "WORDING_DRAFT",
        "AGREED_WORDING",
    ], "each row carries the type that advanced the documentation chain"

    root_rows, root_meta = validate_paginated(api_client.list_contract_documents(COMPLIANCE))
    assert root_meta["total_count"] == 3, "the flat collection holds the same three documents"
    assert [row["id"] for row in root_rows] == [slip["id"], draft["id"], agreed["id"]], (
        "the flat collection is ordered identically to the program-scoped one"
    )

    assert_status(read_program(ctx["program"]["id"]), "documentation_status", "WORDING_AGREED")


def test_a_single_filed_document_reads_back_as_an_append_only_row():
    """The slip reads back with its wording reference, its filer and no version at all.

    PRD: "A contract document carries only `id` and `created_at` from the common
    properties; it has no `updated_at` and no `version`, because there is nothing
    about it that can ever change."

    Design: Corner/endpoints/every_declared_read_surface_answers_from_one_fully_walked_placement
    """
    ctx = _walked_placement()
    slip = ctx["documents"][0]

    document = validate_success(api_client.get_contract_document(slip["id"], ACCOUNTANT))

    assert_contract_document(document)
    assert_append_only_fields(document)
    assert document["program_id"] == ctx["program"]["id"], "the document hangs off its program"
    assert document["document_type"] == "SLIP", "document_type echoes the filing"
    assert document["wording_reference"] == "NM-SLIP-1", "wording_reference echoes the filing"
    assert document["filed_by_user_id"] == "lead-1", "filed_by_user_id records the filing broker"
    assert_instant_equals(document["issued_at"], CLOCK["PLACEMENT_START"], "issued_at")
    assert document["days_from_inception"] == 0, (
        "the slip was filed at the inception instant itself, so no whole day has elapsed"
    )


def test_the_renewal_report_reads_back_from_three_surfaces_with_its_analytics_frozen():
    """The report answers 9.7125 rate on line at 100.00 efficiency and a 0.00 index.

    PRD: "The report is append-only, carries only `id` and `created_at` from the
    common properties — no `updated_at` and no `version` — records its
    `program_id`, the generating actuary's identity as `generated_by_user_id` and
    the current logical clock as `as_of`, and answers 201."

    Design: Corner/endpoints/every_declared_read_surface_answers_from_one_fully_walked_placement
    """
    ctx = _walked_placement()
    report_id = ctx["report"]["id"]

    nested_rows, nested_meta = validate_paginated(
        api_client.list_program_renewal_reports(ctx["program"]["id"], ACTUARY)
    )
    assert nested_meta["total_count"] == 1, "one report has been generated on this program"
    assert nested_rows[0]["id"] == report_id, "the program-scoped read finds it"

    root_rows, root_meta = validate_paginated(api_client.list_renewal_reports(ACTUARY))
    assert root_meta["total_count"] == 1, "the flat collection finds the same single report"
    assert root_rows[0]["id"] == report_id, "and it is the same row"

    report = validate_success(api_client.get_renewal_report(report_id, ACTUARY))
    assert_renewal_report(report)
    assert_append_only_fields(report)
    assert report["program_id"] == ctx["program"]["id"], "the report hangs off its program"
    assert report["generated_by_user_id"] == "act-1", "the generating actuary is recorded"
    assert_instant_equals(report["as_of"], CLOCK["PLACEMENT_START"], "as_of")
    assert_pct_equals(
        report["current_rate_on_line_pct"], WALKED_RATE_ON_LINE_PCT, "current_rate_on_line_pct"
    )
    assert_pct_equals(report["prior_rate_on_line_pct"], 0.0000, "prior_rate_on_line_pct")
    assert_pct_equals(report["rate_change_pct"], 0.00, "rate_change_pct")
    assert_pct_equals(report["exposure_change_pct"], 0.00, "exposure_change_pct")
    assert_pct_equals(
        report["risk_adjusted_rate_change_pct"], 0.00, "risk_adjusted_rate_change_pct"
    )
    assert_pct_equals(
        report["placement_efficiency_pct"],
        WALKED_PLACEMENT_EFFICIENCY_PCT,
        "placement_efficiency_pct",
    )
    assert_pct_equals(report["market_condition_index"], 0.00, "market_condition_index")


def test_the_package_the_disclosure_and_the_quote_all_answer_from_parent_and_from_root():
    """Each of the three children reads back once under its parent and once at the root.

    PRD: "Every response body follows the envelope defined in §2.2, and every list
    endpoint accepts the `limit` and `offset` parameters defined in §2.3 in addition
    to the filters named in its own description."

    Design: Corner/endpoints/every_declared_read_surface_answers_from_one_fully_walked_placement
    """
    ctx = _walked_placement()
    program_id = ctx["program"]["id"]
    package = ctx["submission"]
    disclosure = ctx["disclosure"]
    market_submission = ctx["market_submissions"][0]
    quote = ctx["quotes"][0]

    package_rows, package_meta = validate_paginated(
        api_client.list_program_exposure_submissions(
            program_id, ACTUARY, params={"limit": 5, "offset": 0}
        )
    )
    assert package_meta["limit"] == 5, "limit echoes the effective value used"
    assert package_meta["offset"] == 0, "offset echoes the effective value used"
    assert package_meta["total_count"] == 1, "one exposure package was assembled"
    assert package_rows[0]["id"] == package["id"], "the program-scoped read finds the package"
    assert_status(package_rows[0], "status", "SIGNED_OFF")
    root_package_rows, _ = validate_paginated(api_client.list_exposure_submissions(ACTUARY))
    assert [row["id"] for row in root_package_rows] == [package["id"]], (
        "the flat package collection agrees with the program-scoped one"
    )

    disclosure_rows, disclosure_meta = validate_paginated(
        api_client.list_program_brokerage_disclosures(
            program_id, ACCOUNTANT, params={"limit": 5, "offset": 0}
        )
    )
    assert disclosure_meta["total_count"] == 1, "one compensation disclosure was drafted"
    assert disclosure_rows[0]["id"] == disclosure["id"], "the program-scoped read finds it"
    assert_status(disclosure_rows[0], "status", "ACKNOWLEDGED")
    root_disclosure_rows, _ = validate_paginated(
        api_client.list_brokerage_disclosures(ACCOUNTANT)
    )
    assert [row["id"] for row in root_disclosure_rows] == [disclosure["id"]], (
        "the flat disclosure collection agrees with the program-scoped one"
    )

    quote_rows, quote_meta = validate_paginated(
        api_client.list_market_submission_quotes(
            market_submission["id"], LEAD, params={"limit": 5, "offset": 0}
        )
    )
    assert quote_meta["total_count"] == 1, "one market answered that submission"
    assert quote_rows[0]["id"] == quote["id"], "the submission-scoped read finds its quote"
    root_quote_rows, root_quote_meta = validate_paginated(
        api_client.list_quotes(LEAD, params={"market_submission_id": market_submission["id"]})
    )
    assert root_quote_meta["total_count"] == 1, "the declared filter cuts the same single quote"
    assert root_quote_rows[0]["id"] == quote["id"], "and it is the same row"
    assert_status(validate_success(api_client.get_quote(quote["id"], LEAD)), "status", "BOUND")


def test_the_advocacy_and_its_dispute_answer_from_every_declared_surface():
    """A 300,000,000 cession contested by 50,000,000 leaves 250,000,000 collectible.

    PRD: "The file's `collectible_minor` is then its `ceded_claim_minor` less
    `disputed_minor`, floored at zero."

    Design: Corner/endpoints/every_declared_read_surface_answers_from_one_fully_walked_placement
    """
    ctx = _walked_placement()
    advocacy, dispute = ctx["advocacy"], ctx["dispute"]

    layer_rows, layer_meta = validate_paginated(
        api_client.list_layer_claim_advocacies(ctx["layers"][0]["id"], LEAD)
    )
    assert layer_meta["total_count"] == 1, "one loss has been notified on the bound layer"
    assert layer_rows[0]["id"] == advocacy["id"], "the layer-scoped read finds the file"

    root_advocacy_rows, root_advocacy_meta = validate_paginated(
        api_client.list_claim_advocacies(LEAD)
    )
    assert root_advocacy_meta["total_count"] == 1, "the flat collection finds the same file"
    assert root_advocacy_rows[0]["id"] == advocacy["id"], "and it is the same row"

    file_read = validate_success(api_client.get_claim_advocacy(advocacy["id"], LEAD))
    assert_claim_advocacy(file_read)
    assert_status(file_read, "status", "DISPUTED")
    assert_money_equals(file_read["ceded_claim_minor"], WALKED_CEDED_MINOR, "ceded_claim_minor")
    assert_money_equals(file_read["disputed_minor"], WALKED_DISPUTED_MINOR, "disputed_minor")
    assert_money_equals(
        file_read["collectible_minor"], WALKED_COLLECTIBLE_MINOR, "collectible_minor"
    )
    assert_money_equals(file_read["collected_minor"], 0, "nothing has been collected yet")
    assert_collectible_invariant(file_read)

    nested_dispute_rows, nested_dispute_meta = validate_paginated(
        api_client.list_advocacy_cession_disputes(advocacy["id"], LEAD)
    )
    assert nested_dispute_meta["total_count"] == 1, "one market has contested the cession"
    assert nested_dispute_rows[0]["id"] == dispute["id"], "the file-scoped read finds the dispute"

    by_file_rows, by_file_meta = validate_paginated(
        api_client.list_cession_disputes(LEAD, params={"claim_advocacy_id": advocacy["id"]})
    )
    assert by_file_meta["total_count"] == 1, "the declared claim_advocacy_id filter finds it"
    assert by_file_rows[0]["id"] == dispute["id"], "and it is the same row"

    by_line_rows, by_line_meta = validate_paginated(
        api_client.list_cession_disputes(
            LEAD, params={"signing_line_id": ctx["signing_lines"][0]["id"]}
        )
    )
    assert by_line_meta["total_count"] == 1, "the declared signing_line_id filter finds it too"
    assert by_line_rows[0]["id"] == dispute["id"], "and it is still the same row"

    dispute_read = validate_success(api_client.get_cession_dispute(dispute["id"], LEAD))
    assert_cession_dispute(dispute_read)
    assert_status(dispute_read, "status", "RAISED")
    assert_money_equals(dispute_read["disputed_minor"], WALKED_DISPUTED_MINOR, "disputed_minor")
    assert_money_equals(dispute_read["settled_minor"], 0, "a raised dispute has settled nothing")
    assert dispute_read["resolution_note"] is None, "no resolution note has been written yet"
