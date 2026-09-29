"""Claim boundaries, the dispute overlay and the fiduciary ceilings (PRD §3.8, §3.9).

Queue B — section ``validations``: the half-open event-date window and the
layer-scoped claim reference, the cession and line-layer bounds on disputes, the
link requirement that flips with the transaction type, and the two money ceilings
that reject one minor unit over and admit exact equality.
"""
from test_helpers import (
    ACCOUNTANT,
    COMPLIANCE,
    LEAD,
    ApiErrorId,
    acknowledge_disclosure,
    add_layer,
    agree_wording,
    api_client,
    approve_transaction,
    assert_instant_equals,
    assert_is_null,
    assert_money_equals,
    assert_status,
    bind_program,
    book_approve_settle,
    book_transaction,
    create_cession_dispute_payload,
    create_claim_advocacy_payload,
    create_exposure_submission,
    create_fiduciary_transaction_payload,
    create_program,
    create_xol_layer,
    current_program_version,
    firm_order,
    go_to_market,
    list_rows,
    notify_claim,
    place_line,
    quote_on,
    raise_dispute,
    read_advocacy,
    read_dispute,
    read_layer,
    read_program,
    read_signing_line,
    read_transaction,
    refresh,
    resolve_dispute,
    resolve_dispute_payload,
    review_claim,
    set_clock,
    settle_program,
    settle_transaction,
    setup_bound_program,
    setup_draft_program,
    sign_off_exposure,
    submit_to_market,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------
# A two-layer bound program (PRD §3.3, §3.6)
# --------------------------------------------------------------------------
# One market big enough to write both layers whole: 100% of two 1,000,000,000
# limits is 2,000,000,000 against a 5,000,000,000 capacity.
SOLE_BIG_MARKET = [
    {
        "name": "Alpha Re",
        "max_line_pct": 100.0000,
        "lead_authorised": True,
        "capacity_limit_minor": 5_000_000_000,
    }
]
# The lower catastrophe layer: 1,000,000,000 excess of 1,000,000,000, so a
# 2,100,000,000 event pierces it by 1,100,000,000 and is capped at one limit.
LOWER_CAT_LAYER = {
    "layer_label": "PROP CAT 1B xs 1B",
    "attachment_minor": 1_000_000_000,
    "limit_minor": 1_000_000_000,
    "base_rate_pct": 6.0000,
    "subject_premium_base_minor": 1_250_000_000,
    "expected_loss_cost_minor": 40_000_000,
}
# The treaty period is [2026-01-01, 2027-01-01) and the clock is parked mid-term.
MID_TERM_CLOCK = "2026-06-01T00:00:00.000Z"
INCEPTION_INSTANT = "2026-01-01T00:00:00.000Z"
LAST_COVERED_INSTANT = "2026-12-31T23:59:59.999Z"
INSTANT_BEFORE_INCEPTION = "2025-12-31T23:59:59.999Z"
EXPIRY_INSTANT = "2027-01-01T00:00:00.000Z"


def _two_bound_cat_layers():
    """One program, two CAT layers, both written 100% by Alpha and both BOUND."""
    ctx = setup_draft_program(market_specs=SOLE_BIG_MARKET)
    add_layer(ctx, "CAT", **LOWER_CAT_LAYER)
    sign_off_exposure(ctx["submission"]["id"])
    go_to_market(ctx["program"]["id"])
    place_line(ctx, market_index=0, layer_index=0, accepted_line_pct=100.0000, is_lead=True)
    place_line(ctx, market_index=0, layer_index=1, accepted_line_pct=100.0000, is_lead=True)
    acknowledge_disclosure(ctx["program"]["id"], ctx["cedent"]["id"])
    bind_program(ctx["program"]["id"])
    set_clock(MID_TERM_CLOCK)
    refresh(ctx)
    ctx["layer_a"], ctx["layer_b"] = ctx["layers"][0], ctx["layers"][1]
    ctx["line_a"], ctx["line_b"] = ctx["signing_lines"][0], ctx["signing_lines"][1]
    return ctx


def test_an_event_on_the_expiry_instant_falls_outside_the_treaty_period():
    """2027-01-01T00:00:00.000Z is the excluded end of the half-open period.

    PRD: "The `event_date` must fall inside the half-open treaty period: an event
    exactly at the program's `inception_date` is covered, an event exactly at
    `expiry_date` is not, and anything outside is `ERR_EVENT_DATE_OUT_OF_PERIOD`."

    Design: Corner/validations/event_date_boundaries_are_half_open_and_claim_reference_is_layer_scoped
    """
    ctx = _two_bound_cat_layers()
    assert_status(ctx["layer_a"], "status", "BOUND")

    response = api_client.create_claim_advocacy(
        ctx["layer_a"]["id"],
        create_claim_advocacy_payload(
            claim_reference="NW-CLM-0001",
            event_date=EXPIRY_INSTANT,
            gross_claim_minor=2_300_000_000,
        ),
        ctx["cedent_headers"],
    )
    validate_error(response, ApiErrorId.ERR_EVENT_DATE_OUT_OF_PERIOD.value)

    rows = list_rows(api_client.list_layer_claim_advocacies(ctx["layer_a"]["id"], LEAD))
    assert len(rows) == 0, f"the refused notification files nothing, got {len(rows)}"


def test_an_event_one_millisecond_before_inception_falls_outside_the_treaty_period():
    """2025-12-31T23:59:59.999Z is the last instant the treaty does not cover.

    PRD: "The `event_date` must fall inside the half-open treaty period: an event
    exactly at the program's `inception_date` is covered, an event exactly at
    `expiry_date` is not, and anything outside is `ERR_EVENT_DATE_OUT_OF_PERIOD`."

    Design: Corner/validations/event_date_boundaries_are_half_open_and_claim_reference_is_layer_scoped
    """
    ctx = _two_bound_cat_layers()

    response = api_client.create_claim_advocacy(
        ctx["layer_a"]["id"],
        create_claim_advocacy_payload(
            claim_reference="NW-CLM-0001",
            event_date=INSTANT_BEFORE_INCEPTION,
            gross_claim_minor=2_300_000_000,
        ),
        ctx["cedent_headers"],
    )
    validate_error(response, ApiErrorId.ERR_EVENT_DATE_OUT_OF_PERIOD.value)

    rows = list_rows(api_client.list_layer_claim_advocacies(ctx["layer_a"]["id"], LEAD))
    assert len(rows) == 0, f"the refused notification files nothing, got {len(rows)}"


def test_an_event_exactly_on_the_inception_instant_is_covered():
    """2026-01-01T00:00:00.000Z is the included end, and 2,300,000,000 cedes 300,000,000.

    PRD: "The `ceded_claim_minor` is then the minimum of the subject amount, the
    per-event cap, the layer's `limit_minor` and the aggregate available amount."

    Design: Corner/validations/event_date_boundaries_are_half_open_and_claim_reference_is_layer_scoped
    """
    ctx = _two_bound_cat_layers()

    response = api_client.create_claim_advocacy(
        ctx["layer_a"]["id"],
        create_claim_advocacy_payload(
            claim_reference="NW-CLM-0001",
            event_date=INCEPTION_INSTANT,
            gross_claim_minor=2_300_000_000,
        ),
        ctx["cedent_headers"],
    )
    advocacy = validate_success(response, 201)
    assert_status(advocacy, "status", "NOTIFIED")
    assert_instant_equals(advocacy["event_date"], INCEPTION_INSTANT, "event_date")
    assert_money_equals(advocacy["ceded_claim_minor"], 300_000_000, "ceded_claim_minor")
    assert_money_equals(advocacy["disputed_minor"], 0, "disputed_minor")
    assert_money_equals(advocacy["collected_minor"], 0, "collected_minor")


def test_a_claim_reference_is_unique_per_layer_and_not_per_program():
    """NW-CLM-0001 is refused a second time on layer A and accepted once on layer B.

    PRD: "The `claim_reference` must be unique among the advocacies of the same
    layer, else `ERR_DUPLICATE_CLAIM_REFERENCE`; the same reference may
    legitimately appear on a different layer of the same program, because each
    layer's file is its own."

    Design: Corner/validations/event_date_boundaries_are_half_open_and_claim_reference_is_layer_scoped
    """
    ctx = _two_bound_cat_layers()
    notify_claim(
        ctx["layer_a"]["id"],
        ctx["cedent"]["id"],
        claim_reference="NW-CLM-0001",
        event_date=INCEPTION_INSTANT,
        gross_claim_minor=2_300_000_000,
    )

    duplicate = api_client.create_claim_advocacy(
        ctx["layer_a"]["id"],
        create_claim_advocacy_payload(
            claim_reference="NW-CLM-0001",
            event_date="2026-07-01T00:00:00.000Z",
            gross_claim_minor=2_100_000_000,
        ),
        ctx["cedent_headers"],
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CLAIM_REFERENCE.value)

    on_layer_b = notify_claim(
        ctx["layer_b"]["id"],
        ctx["cedent"]["id"],
        claim_reference="NW-CLM-0001",
        event_date=LAST_COVERED_INSTANT,
        gross_claim_minor=2_100_000_000,
    )
    assert_status(on_layer_b, "status", "NOTIFIED")
    assert_money_equals(
        on_layer_b["ceded_claim_minor"], 1_000_000_000, "layer B ceded_claim_minor"
    )
    assert len(list_rows(api_client.list_layer_claim_advocacies(ctx["layer_a"]["id"], LEAD))) == 1
    assert len(list_rows(api_client.list_layer_claim_advocacies(ctx["layer_b"]["id"], LEAD))) == 1


def test_a_second_reference_on_the_same_layer_opens_its_own_file():
    """NW-CLM-0002 cedes its own 100,000,000 and layer A then carries two files.

    PRD: "A new file starts in `NOTIFIED`, with `disputed_minor`,
    `collected_minor` and `arbitration_cost_minor` at 0, `advocacy_route` null and
    `reinstatement_triggered` false, and answers 201."

    Design: Corner/validations/event_date_boundaries_are_half_open_and_claim_reference_is_layer_scoped
    """
    ctx = _two_bound_cat_layers()
    notify_claim(
        ctx["layer_a"]["id"],
        ctx["cedent"]["id"],
        claim_reference="NW-CLM-0001",
        event_date=INCEPTION_INSTANT,
        gross_claim_minor=2_300_000_000,
    )

    second = notify_claim(
        ctx["layer_a"]["id"],
        ctx["cedent"]["id"],
        claim_reference="NW-CLM-0002",
        event_date=LAST_COVERED_INSTANT,
        gross_claim_minor=2_100_000_000,
    )
    assert_status(second, "status", "NOTIFIED")
    assert_money_equals(second["ceded_claim_minor"], 100_000_000, "ceded_claim_minor")
    assert_money_equals(second["arbitration_cost_minor"], 0, "arbitration_cost_minor")
    assert_is_null(second, "advocacy_route")
    assert second["reinstatement_triggered"] is False, "notification never erodes the layer"

    rows = list_rows(api_client.list_layer_claim_advocacies(ctx["layer_a"]["id"], LEAD))
    assert len(rows) == 2, f"layer A carries both files, got {len(rows)}"
    layer_a = read_layer(ctx["layer_a"]["id"])
    assert_money_equals(layer_a["limit_eroded_minor"], 0, "limit_eroded_minor")


# --------------------------------------------------------------------------
# The dispute overlay: bounded by the cession, tied to the layer (PRD §3.9)
# --------------------------------------------------------------------------
# A 2,300,000,000 event on the upper layer cedes exactly 300,000,000, which is
# the ceiling every dispute on the file is measured against.
DISPUTE_EVENT = {
    "claim_reference": "NW-CLM-0001",
    "event_date": "2026-05-01T00:00:00.000Z",
    "gross_claim_minor": 2_300_000_000,
}


def _reviewed_advocacy_on_the_upper_layer():
    """A 300,000,000 cession on layer A, taken under review by the broker."""
    ctx = _two_bound_cat_layers()
    advocacy = notify_claim(ctx["layer_a"]["id"], ctx["cedent"]["id"], **DISPUTE_EVENT)
    assert_money_equals(advocacy["ceded_claim_minor"], 300_000_000, "ceded_claim_minor")
    ctx["advocacy"] = review_claim(advocacy["id"])
    assert_status(ctx["advocacy"], "status", "UNDER_REVIEW")
    return ctx


def test_a_dispute_must_cite_a_line_sitting_on_the_advocacys_own_layer():
    """Alpha's line on layer B cannot be used to dispute a layer A cession.

    PRD: "A market raises a dispute against a file, supplying the
    `signing_line_id` of its own line — which must belong to the advocacy's layer,
    else `ERR_LINE_LAYER_MISMATCH` — a positive integer `disputed_minor` and a
    `dispute_reason` drawn from `EXCLUSION_APPLIES`, `LATE_NOTIFICATION`,
    `AGGREGATION_DISAGREEMENT` and `WORDING_AMBIGUITY`."

    Design: Corner/validations/dispute_amounts_are_bounded_by_the_cession_and_the_line_must_be_on_the_advocacy_layer
    """
    ctx = _reviewed_advocacy_on_the_upper_layer()

    response = api_client.create_cession_dispute(
        ctx["advocacy"]["id"],
        create_cession_dispute_payload(ctx["line_b"]["id"], 200_000_000),
        ctx["market_headers"][0],
    )
    validate_error(response, ApiErrorId.ERR_LINE_LAYER_MISMATCH.value)

    advocacy = read_advocacy(ctx["advocacy"]["id"])
    assert_status(advocacy, "status", "UNDER_REVIEW")
    assert_money_equals(advocacy["disputed_minor"], 0, "disputed_minor")


def test_a_single_dispute_above_the_cession_is_refused():
    """350,000,000 contested against a 300,000,000 cession is more than was ever ceded.

    PRD: "The sum of `disputed_minor` across the file's disputes that are
    `RAISED`, `UPHELD` or `SETTLED_PARTIAL` may not exceed the file's
    `ceded_claim_minor` — the markets cannot collectively dispute more than was
    ever ceded to them — else `ERR_DISPUTE_EXCEEDS_CESSION`."

    Design: Corner/validations/dispute_amounts_are_bounded_by_the_cession_and_the_line_must_be_on_the_advocacy_layer
    """
    ctx = _reviewed_advocacy_on_the_upper_layer()

    response = api_client.create_cession_dispute(
        ctx["advocacy"]["id"],
        create_cession_dispute_payload(ctx["line_a"]["id"], 350_000_000),
        ctx["market_headers"][0],
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_EXCEEDS_CESSION.value)

    advocacy = read_advocacy(ctx["advocacy"]["id"])
    assert_status(advocacy, "status", "UNDER_REVIEW")
    assert_money_equals(advocacy["disputed_minor"], 0, "disputed_minor")
    assert_money_equals(advocacy["collectible_minor"], 300_000_000, "collectible_minor")


def test_the_first_admitted_dispute_cascades_the_file_to_disputed():
    """200,000,000 contested leaves 100,000,000 collectible and moves the file off review.

    PRD: "Creating the **first** dispute on a file cascades the file from
    `UNDER_REVIEW` to `DISPUTED` and recomputes `disputed_minor` and
    `collectible_minor`; a second and subsequent dispute recomputes those figures
    without moving the file, which is already `DISPUTED`."

    Design: Corner/validations/dispute_amounts_are_bounded_by_the_cession_and_the_line_must_be_on_the_advocacy_layer
    """
    ctx = _reviewed_advocacy_on_the_upper_layer()

    dispute = raise_dispute(
        ctx["advocacy"]["id"], ctx["reinsurers"][0]["id"], ctx["line_a"]["id"], 200_000_000
    )
    assert_status(dispute, "status", "RAISED")
    assert_money_equals(dispute["disputed_minor"], 200_000_000, "dispute disputed_minor")
    assert_money_equals(dispute["settled_minor"], 0, "settled_minor")
    assert_is_null(dispute, "resolution_note")

    advocacy = read_advocacy(ctx["advocacy"]["id"])
    assert_status(advocacy, "status", "DISPUTED")
    assert_money_equals(advocacy["disputed_minor"], 200_000_000, "disputed_minor")
    assert_money_equals(advocacy["collectible_minor"], 100_000_000, "collectible_minor")


def test_the_cession_ceiling_binds_the_sum_of_the_files_disputes():
    """With 200,000,000 already contested, 150,000,000 more is refused and 100,000,000 is not.

    PRD: "The sum of `disputed_minor` across the file's disputes that are
    `RAISED`, `UPHELD` or `SETTLED_PARTIAL` may not exceed the file's
    `ceded_claim_minor` — the markets cannot collectively dispute more than was
    ever ceded to them — else `ERR_DISPUTE_EXCEEDS_CESSION`."

    Design: Corner/validations/dispute_amounts_are_bounded_by_the_cession_and_the_line_must_be_on_the_advocacy_layer
    """
    ctx = _reviewed_advocacy_on_the_upper_layer()
    raise_dispute(
        ctx["advocacy"]["id"], ctx["reinsurers"][0]["id"], ctx["line_a"]["id"], 200_000_000
    )

    over = api_client.create_cession_dispute(
        ctx["advocacy"]["id"],
        create_cession_dispute_payload(ctx["line_a"]["id"], 150_000_000),
        ctx["market_headers"][0],
    )
    validate_error(over, ApiErrorId.ERR_DISPUTE_EXCEEDS_CESSION.value)
    assert_money_equals(
        read_advocacy(ctx["advocacy"]["id"])["disputed_minor"], 200_000_000, "disputed_minor"
    )

    exact = raise_dispute(
        ctx["advocacy"]["id"], ctx["reinsurers"][0]["id"], ctx["line_a"]["id"], 100_000_000
    )
    assert_status(exact, "status", "RAISED")

    advocacy = read_advocacy(ctx["advocacy"]["id"])
    assert_status(advocacy, "status", "DISPUTED")
    assert_money_equals(advocacy["disputed_minor"], 300_000_000, "disputed_minor")
    assert_money_equals(advocacy["collectible_minor"], 0, "collectible_minor")


def test_the_settled_amount_must_match_the_resolution_chosen():
    """SETTLED_PARTIAL at the full 200,000,000 and UPHELD at 1 are both refused; UPHELD at 0 lands.

    PRD: "The dispute must be `RAISED`, else `ERR_DISPUTE_STATE_INVALID`, and the
    amount supplied must match the resolution chosen: `UPHELD` requires
    `settled_minor` to be exactly 0, since the market conceded nothing;
    `WITHDRAWN` requires it to equal the dispute's `disputed_minor` exactly, since
    the market conceded everything; and `SETTLED_PARTIAL` requires it to lie
    strictly between 0 and `disputed_minor`, since a partial settlement that
    concedes nothing or everything is one of the other two outcomes."

    Design: Corner/validations/dispute_amounts_are_bounded_by_the_cession_and_the_line_must_be_on_the_advocacy_layer
    """
    ctx = _reviewed_advocacy_on_the_upper_layer()
    dispute = raise_dispute(
        ctx["advocacy"]["id"], ctx["reinsurers"][0]["id"], ctx["line_a"]["id"], 200_000_000
    )

    whole = api_client.resolve_cession_dispute(
        dispute["id"], resolve_dispute_payload("SETTLED_PARTIAL", 200_000_000), LEAD
    )
    validate_error(whole, ApiErrorId.ERR_RESOLUTION_AMOUNT_INVALID.value)

    upheld_with_a_penny = api_client.resolve_cession_dispute(
        dispute["id"], resolve_dispute_payload("UPHELD", 1), LEAD
    )
    validate_error(upheld_with_a_penny, ApiErrorId.ERR_RESOLUTION_AMOUNT_INVALID.value)
    assert_status(read_dispute(dispute["id"]), "status", "RAISED")

    resolved = resolve_dispute(dispute["id"], "UPHELD", 0)
    assert_status(resolved, "status", "UPHELD")
    assert_money_equals(resolved["settled_minor"], 0, "settled_minor")


def test_a_resolved_dispute_is_closed_and_a_withdrawn_one_leaves_the_overlay():
    """The UPHELD 200,000,000 keeps contributing while the WITHDRAWN 100,000,000 contributes nothing.

    PRD: "Each dispute contributes according to its own status: a dispute still
    `RAISED` contributes its full `disputed_minor`; a dispute `UPHELD`, meaning
    the market's objection succeeded, also contributes its full `disputed_minor`;
    a dispute `SETTLED_PARTIAL` contributes its `disputed_minor` less the
    `settled_minor` the market conceded; and a `WITHDRAWN` dispute contributes
    nothing at all, because the market conceded in full."

    Design: Corner/validations/dispute_amounts_are_bounded_by_the_cession_and_the_line_must_be_on_the_advocacy_layer
    """
    ctx = _reviewed_advocacy_on_the_upper_layer()
    first = raise_dispute(
        ctx["advocacy"]["id"], ctx["reinsurers"][0]["id"], ctx["line_a"]["id"], 200_000_000
    )
    second = raise_dispute(
        ctx["advocacy"]["id"], ctx["reinsurers"][0]["id"], ctx["line_a"]["id"], 100_000_000
    )
    resolve_dispute(first["id"], "UPHELD", 0)

    again = api_client.resolve_cession_dispute(
        first["id"], resolve_dispute_payload("WITHDRAWN", 200_000_000), LEAD
    )
    validate_error(again, ApiErrorId.ERR_DISPUTE_STATE_INVALID.value)
    assert_status(read_dispute(first["id"]), "status", "UPHELD")

    withdrawn = resolve_dispute(second["id"], "WITHDRAWN", 100_000_000)
    assert_status(withdrawn, "status", "WITHDRAWN")
    assert_money_equals(withdrawn["settled_minor"], 100_000_000, "settled_minor")

    advocacy = read_advocacy(ctx["advocacy"]["id"])
    assert_money_equals(advocacy["disputed_minor"], 200_000_000, "disputed_minor")
    assert_money_equals(advocacy["collectible_minor"], 100_000_000, "collectible_minor")


# --------------------------------------------------------------------------
# Fiduciary bookings: the link flips with the type (PRD §3.8)
# --------------------------------------------------------------------------
ALPHA_AND_BRAVO = [
    {
        "name": "Alpha Re",
        "max_line_pct": 100.0000,
        "lead_authorised": True,
        "capacity_limit_minor": 1_000_000_000,
    },
    {
        "name": "Bravo Re",
        "max_line_pct": 100.0000,
        "lead_authorised": False,
        "capacity_limit_minor": 1_000_000_000,
    },
]
# A second program on the same cedent in a different class of business, so no
# treaty period overlaps: it exists only to own a line that is foreign to P1.
FOREIGN_CASUALTY_LAYER = {
    "layer_label": "CAS XL 500M xs 500M",
    "attachment_minor": 500_000_000,
    "limit_minor": 500_000_000,
    "base_rate_pct": 5.0000,
    "subject_premium_base_minor": 800_000_000,
    "expected_loss_cost_minor": 20_000_000,
}
# The canonical CAT layer's frozen premium and the net remittance left after the
# program's 2.5000% brokerage: 97,125,000 - 2,428,125.
CAT_GROSS_PREMIUM_MINOR = 97_125_000
NET_REMITTANCE_MINOR = 94_696_875


def _bound_property_program_and_a_foreign_casualty_line():
    """P1 BOUND with Alpha's whole line; P2 IN_MARKET carrying a PROVISIONAL Bravo line."""
    ctx = setup_bound_program(market_specs=ALPHA_AND_BRAVO)
    bravo = ctx["reinsurers"][1]

    foreign_program = create_program(
        ctx["cedent"]["id"],
        program_name="Northwind Casualty 2026",
        line_of_business="CASUALTY",
    )
    foreign_submission = create_exposure_submission(
        foreign_program["id"], ctx["cedent"]["id"], package_label="NW-CAS-2026-EDP"
    )
    foreign_layer = create_xol_layer(foreign_program["id"], **FOREIGN_CASUALTY_LAYER)
    sign_off_exposure(foreign_submission["id"])
    go_to_market(foreign_program["id"])
    foreign_ms = submit_to_market(foreign_layer["id"], bravo["id"])
    foreign_quote = quote_on(
        foreign_ms["id"], bravo["id"], offered_line_pct=50.0000, is_lead=False
    )
    ctx["foreign_program"] = foreign_program
    ctx["foreign_line"] = firm_order(
        foreign_quote["id"], 50.0000, layer_id=foreign_layer["id"]
    )
    set_clock(MID_TERM_CLOCK)
    return refresh(ctx)


def test_the_signing_line_link_is_forbidden_on_inflows_and_required_on_remittances():
    """A linked receipt, an unlinked remittance and a hand-booked reversal are all refused.

    PRD: "Supplying it when it is forbidden, or omitting it when it is required, is
    `ERR_TRANSACTION_TYPE_LINK_INVALID`; so is booking a `REMITTANCE_REVERSAL`
    through this endpoint at all, because reversal rows are only ever created by
    the system."

    Design: Corner/validations/fiduciary_link_requirement_flips_with_txn_type_and_the_line_must_be_on_the_same_program
    """
    ctx = _bound_property_program_and_a_foreign_casualty_line()
    program_version = current_program_version(ctx["program"]["id"])

    linked_receipt = create_fiduciary_transaction_payload(
        "CEDENT_RECEIPT", CAT_GROSS_PREMIUM_MINOR, program_version
    )
    linked_receipt["signing_line_id"] = ctx["signing_lines"][0]["id"]
    validate_error(
        api_client.create_fiduciary_transaction(
            ctx["program"]["id"], linked_receipt, ACCOUNTANT
        ),
        ApiErrorId.ERR_TRANSACTION_TYPE_LINK_INVALID.value,
    )

    validate_error(
        api_client.create_fiduciary_transaction(
            ctx["program"]["id"],
            create_fiduciary_transaction_payload(
                "REINSURER_REMITTANCE", NET_REMITTANCE_MINOR, program_version
            ),
            ACCOUNTANT,
        ),
        ApiErrorId.ERR_TRANSACTION_TYPE_LINK_INVALID.value,
    )

    validate_error(
        api_client.create_fiduciary_transaction(
            ctx["program"]["id"],
            create_fiduciary_transaction_payload(
                "REMITTANCE_REVERSAL", CAT_GROSS_PREMIUM_MINOR, program_version
            ),
            ACCOUNTANT,
        ),
        ApiErrorId.ERR_TRANSACTION_TYPE_LINK_INVALID.value,
    )

    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        0,
        "fiduciary_holding_minor",
    )


def test_a_remittance_may_not_cite_a_line_from_another_programs_layer():
    """Bravo's casualty line is a real line, but it does not sit on this program.

    PRD: "When a link is supplied, the referenced line must sit on a layer
    belonging to this program, else `ERR_LINE_LAYER_MISMATCH`."

    Design: Corner/validations/fiduciary_link_requirement_flips_with_txn_type_and_the_line_must_be_on_the_same_program
    """
    ctx = _bound_property_program_and_a_foreign_casualty_line()
    program_version = current_program_version(ctx["program"]["id"])

    payload = create_fiduciary_transaction_payload(
        "REINSURER_REMITTANCE", NET_REMITTANCE_MINOR, program_version
    )
    payload["signing_line_id"] = ctx["foreign_line"]["id"]

    response = api_client.create_fiduciary_transaction(
        ctx["program"]["id"], payload, ACCOUNTANT
    )
    validate_error(response, ApiErrorId.ERR_LINE_LAYER_MISMATCH.value)

    assert_status(read_signing_line(ctx["foreign_line"]["id"]), "status", "PROVISIONAL")
    rows = list_rows(
        api_client.list_program_fiduciary_transactions(ctx["program"]["id"], ACCOUNTANT)
    )
    assert len(rows) == 0, f"no refused booking may appear on the ledger, got {len(rows)}"


def test_the_refused_bookings_leave_the_program_version_reusable():
    """None of the refusals mutated the program, so the same OCC token books the receipt.

    PRD: "A booked movement records `created_by_user_id` as the booking
    accountant's identity, starts in `PENDING`, leaves `approved_by_user_id`,
    `value_date`, `hold_reason` and `reverses_transaction_id` null, and increments
    the program's `version`."

    Design: Corner/validations/fiduciary_link_requirement_flips_with_txn_type_and_the_line_must_be_on_the_same_program
    """
    ctx = _bound_property_program_and_a_foreign_casualty_line()
    program_version = current_program_version(ctx["program"]["id"])

    validate_error(
        api_client.create_fiduciary_transaction(
            ctx["program"]["id"],
            create_fiduciary_transaction_payload(
                "REINSURER_REMITTANCE", NET_REMITTANCE_MINOR, program_version
            ),
            ACCOUNTANT,
        ),
        ApiErrorId.ERR_TRANSACTION_TYPE_LINK_INVALID.value,
    )
    assert current_program_version(ctx["program"]["id"]) == program_version, (
        "a refused booking must not increment the program version"
    )

    accepted = api_client.create_fiduciary_transaction(
        ctx["program"]["id"],
        create_fiduciary_transaction_payload(
            "CEDENT_RECEIPT", CAT_GROSS_PREMIUM_MINOR, program_version
        ),
        ACCOUNTANT,
    )
    transaction = validate_success(accepted, 201)
    assert_status(transaction, "status", "PENDING")
    assert transaction["created_by_user_id"] == ACCOUNTANT["X-User-ID"], (
        f"expected the booking accountant, got {transaction['created_by_user_id']}"
    )
    assert_is_null(transaction, "signing_line_id")
    assert_is_null(transaction, "approved_by_user_id")
    assert_is_null(transaction, "value_date")
    assert_is_null(transaction, "hold_reason")
    assert_is_null(transaction, "reverses_transaction_id")
    assert current_program_version(ctx["program"]["id"]) == program_version + 1, (
        "the accepted booking increments the program version by exactly one"
    )


def test_a_pending_movement_cannot_be_settled_and_cannot_be_approved_twice():
    """Settlement is refused before approval, and approval is refused after it.

    PRD: "A `PENDING` movement is approved by a `ComplianceOfficer` or a
    `BrokerAccountant`; anything other than `PENDING` is
    `ERR_TRANSACTION_STATE_INVALID`."

    Design: Corner/validations/fiduciary_link_requirement_flips_with_txn_type_and_the_line_must_be_on_the_same_program
    """
    ctx = _bound_property_program_and_a_foreign_casualty_line()
    transaction = book_transaction(
        ctx["program"]["id"], "CEDENT_RECEIPT", CAT_GROSS_PREMIUM_MINOR
    )

    early_settlement = api_client.settle_fiduciary_transaction(transaction["id"], ACCOUNTANT)
    validate_error(early_settlement, ApiErrorId.ERR_TRANSACTION_STATE_INVALID.value)
    assert_status(read_transaction(transaction["id"]), "status", "PENDING")

    approved = approve_transaction(transaction["id"])
    assert_status(approved, "status", "APPROVED")
    assert approved["approved_by_user_id"] == COMPLIANCE["X-User-ID"], (
        f"expected the compliance officer, got {approved['approved_by_user_id']}"
    )

    second_approval = api_client.approve_fiduciary_transaction(transaction["id"], COMPLIANCE)
    validate_error(second_approval, ApiErrorId.ERR_TRANSACTION_STATE_INVALID.value)
    assert_status(read_transaction(transaction["id"]), "status", "APPROVED")
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        0,
        "approval moves no money",
    )


def test_an_approved_movement_cannot_be_reversed_before_it_settles():
    """Reversal reaches only SETTLED outflows, so the APPROVED receipt is untouchable.

    PRD: "Only a `ComplianceOfficer` may reverse a movement, and only a `SETTLED`
    one whose `txn_type` is one of the four outflow types — inflows are never
    reversed through this route — else `ERR_TRANSACTION_STATE_INVALID`."

    Design: Corner/validations/fiduciary_link_requirement_flips_with_txn_type_and_the_line_must_be_on_the_same_program
    """
    ctx = _bound_property_program_and_a_foreign_casualty_line()
    transaction = book_transaction(
        ctx["program"]["id"], "CEDENT_RECEIPT", CAT_GROSS_PREMIUM_MINOR
    )
    approve_transaction(transaction["id"])

    response = api_client.reverse_fiduciary_transaction(transaction["id"], COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_TRANSACTION_STATE_INVALID.value)

    after = read_transaction(transaction["id"])
    assert_status(after, "status", "APPROVED")
    assert_is_null(after, "value_date")
    rows = list_rows(
        api_client.list_program_fiduciary_transactions(ctx["program"]["id"], ACCOUNTANT)
    )
    assert len(rows) == 1, f"a refused reversal appends nothing, got {len(rows)}"


def test_settlement_stamps_the_value_date_and_is_refused_a_second_time():
    """The receipt settles at the parked clock, moves the balance, and then closes.

    PRD: "Settlement stamps `value_date` with the current logical clock, moves the
    status to `SETTLED`, and recomputes the balance and the two cedent aggregates."

    Design: Corner/validations/fiduciary_link_requirement_flips_with_txn_type_and_the_line_must_be_on_the_same_program
    """
    ctx = _bound_property_program_and_a_foreign_casualty_line()
    transaction = book_transaction(
        ctx["program"]["id"], "CEDENT_RECEIPT", CAT_GROSS_PREMIUM_MINOR
    )
    approve_transaction(transaction["id"])

    settled = settle_transaction(transaction["id"])
    assert_status(settled, "status", "SETTLED")
    assert_instant_equals(settled["value_date"], MID_TERM_CLOCK, "value_date")
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        CAT_GROSS_PREMIUM_MINOR,
        "fiduciary_holding_minor",
    )

    again = api_client.settle_fiduciary_transaction(transaction["id"], ACCOUNTANT)
    validate_error(again, ApiErrorId.ERR_TRANSACTION_STATE_INVALID.value)

    assert_status(read_transaction(transaction["id"]), "status", "SETTLED")
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        CAT_GROSS_PREMIUM_MINOR,
        "the refused second settlement moves no money",
    )


# --------------------------------------------------------------------------
# The two money ceilings on the way out (PRD §3.8, §3.9)
# --------------------------------------------------------------------------
# The account is funded 50,000,000 first and topped up by 10,000,000, so the
# 60,000,000 remittance is refused once and then settles at exact equality.
FIRST_RECEIPT_MINOR = 50_000_000
TOP_UP_RECEIPT_MINOR = 10_000_000
OUTFLOW_MINOR = 60_000_000


def _bound_program_with_agreed_wording_and_an_empty_account():
    """A BOUND program whose wording is agreed and whose fiduciary account is untouched."""
    ctx = setup_bound_program()
    ctx["documents"] = agree_wording(ctx["program"]["id"])
    return refresh(ctx)


def _approved_outflow(ctx):
    """A 60,000,000 remittance to Alpha's line, booked and approved but not settled."""
    transaction = book_transaction(
        ctx["program"]["id"],
        "REINSURER_REMITTANCE",
        OUTFLOW_MINOR,
        signing_line_id=ctx["signing_lines"][0]["id"],
    )
    assert_status(transaction, "status", "PENDING")
    return approve_transaction(transaction["id"])


def test_an_outflow_one_step_above_the_balance_is_refused_and_stays_approved():
    """60,000,000 against a 50,000,000 holding may not overdraw the fiduciary account.

    PRD: "For every outflow type, `amount_minor` must be no greater than the
    program's current `fiduciary_holding_minor`, since a fiduciary account may
    never be overdrawn; equality is allowed, and one minor unit more is
    `ERR_INSUFFICIENT_FIDUCIARY_BALANCE`."

    Design: Corner/validations/fiduciary_outflow_and_program_settlement_ceilings_reject_then_admit_exact_equality
    """
    ctx = _bound_program_with_agreed_wording_and_an_empty_account()
    assert_money_equals(
        ctx["program"]["fiduciary_holding_minor"], 0, "the account opens empty"
    )
    book_approve_settle(ctx["program"]["id"], "CEDENT_RECEIPT", FIRST_RECEIPT_MINOR)
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        FIRST_RECEIPT_MINOR,
        "fiduciary_holding_minor",
    )
    outflow = _approved_outflow(ctx)
    assert_status(outflow, "status", "APPROVED")

    response = api_client.settle_fiduciary_transaction(outflow["id"], ACCOUNTANT)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_FIDUCIARY_BALANCE.value)

    after = read_transaction(outflow["id"])
    assert_status(after, "status", "APPROVED")
    assert_is_null(after, "value_date")
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        FIRST_RECEIPT_MINOR,
        "the refused settlement moves no money",
    )


def test_an_approved_movement_blocks_the_accounting_close():
    """The stranded remittance keeps the placement year open at 409.

    PRD: "The program's `placement_status` must be `BOUND`, its
    `documentation_status` must be `WORDING_AGREED` or `EXECUTED` — a placement
    whose wording was never agreed cannot be closed — else
    `ERR_DOCUMENTATION_NOT_AGREED`, and no fiduciary movement of the program may
    remain in `PENDING`, `APPROVED` or `HELD`, else
    `ERR_PROGRAM_HAS_OPEN_TRANSACTIONS`."

    Design: Corner/validations/fiduciary_outflow_and_program_settlement_ceilings_reject_then_admit_exact_equality
    """
    ctx = _bound_program_with_agreed_wording_and_an_empty_account()
    book_approve_settle(ctx["program"]["id"], "CEDENT_RECEIPT", FIRST_RECEIPT_MINOR)
    outflow = _approved_outflow(ctx)
    validate_error(
        api_client.settle_fiduciary_transaction(outflow["id"], ACCOUNTANT),
        ApiErrorId.ERR_INSUFFICIENT_FIDUCIARY_BALANCE.value,
    )

    response = api_client.settle_program(ctx["program"]["id"], ACCOUNTANT)
    validate_error(response, ApiErrorId.ERR_PROGRAM_HAS_OPEN_TRANSACTIONS.value)

    program = read_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "BOUND")
    assert_status(program, "documentation_status", "WORDING_AGREED")


def test_topping_the_account_up_to_exact_equality_admits_the_outflow():
    """A 10,000,000 top-up lifts the holding to exactly 60,000,000 and the remittance settles.

    PRD: "For every outflow type, `amount_minor` must be no greater than the
    program's current `fiduciary_holding_minor`, since a fiduciary account may
    never be overdrawn; equality is allowed, and one minor unit more is
    `ERR_INSUFFICIENT_FIDUCIARY_BALANCE`."

    Design: Corner/validations/fiduciary_outflow_and_program_settlement_ceilings_reject_then_admit_exact_equality
    """
    ctx = _bound_program_with_agreed_wording_and_an_empty_account()
    book_approve_settle(ctx["program"]["id"], "CEDENT_RECEIPT", FIRST_RECEIPT_MINOR)
    outflow = _approved_outflow(ctx)
    validate_error(
        api_client.settle_fiduciary_transaction(outflow["id"], ACCOUNTANT),
        ApiErrorId.ERR_INSUFFICIENT_FIDUCIARY_BALANCE.value,
    )

    book_approve_settle(ctx["program"]["id"], "CEDENT_RECEIPT", TOP_UP_RECEIPT_MINOR)
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        OUTFLOW_MINOR,
        "fiduciary_holding_minor",
    )

    settled = settle_transaction(outflow["id"])
    assert_status(settled, "status", "SETTLED")
    assert_money_equals(settled["amount_minor"], OUTFLOW_MINOR, "amount_minor")
    assert_money_equals(
        read_program(ctx["program"]["id"])["fiduciary_holding_minor"],
        0,
        "the account is drained to exactly zero",
    )


def test_a_ledger_with_nothing_open_closes_the_placement_year():
    """With every movement settled the accountant closes the year and the program is SETTLED.

    PRD: "The program's `placement_status` becomes `SETTLED`, which is terminal,
    and its `version` increments."

    Design: Corner/validations/fiduciary_outflow_and_program_settlement_ceilings_reject_then_admit_exact_equality
    """
    ctx = _bound_program_with_agreed_wording_and_an_empty_account()
    book_approve_settle(ctx["program"]["id"], "CEDENT_RECEIPT", FIRST_RECEIPT_MINOR)
    outflow = _approved_outflow(ctx)
    validate_error(
        api_client.settle_fiduciary_transaction(outflow["id"], ACCOUNTANT),
        ApiErrorId.ERR_INSUFFICIENT_FIDUCIARY_BALANCE.value,
    )
    book_approve_settle(ctx["program"]["id"], "CEDENT_RECEIPT", TOP_UP_RECEIPT_MINOR)
    settle_transaction(outflow["id"])
    before = read_program(ctx["program"]["id"])

    program = settle_program(ctx["program"]["id"])
    assert_status(program, "placement_status", "SETTLED")
    assert program["version"] > before["version"], (
        f"the close increments the version, {before['version']} -> {program['version']}"
    )
    assert_money_equals(program["fiduciary_holding_minor"], 0, "fiduciary_holding_minor")

    rows = list_rows(
        api_client.list_program_fiduciary_transactions(ctx["program"]["id"], ACCOUNTANT)
    )
    assert len(rows) == 3, f"three movements make up the closed ledger, got {len(rows)}"
    for row in rows:
        assert_status(row, "status", "SETTLED")
