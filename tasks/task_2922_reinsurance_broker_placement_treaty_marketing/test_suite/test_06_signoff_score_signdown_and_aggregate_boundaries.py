"""Exact-boundary behaviour on the three placement thresholds (PRD §3.2, §3.5, §3.6, §3.9).

Queue A — rule ``boundary_precision_check``: a completeness score landing exactly
on the 70.00 sign-off floor, a written line total landing exactly on
``100.0000`` and an aggregate cover balance landing exactly on zero. Each
threshold is probed twice: once sitting on the boundary and once one unit past
it.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    TEST_USERS,
    assert_instant_equals,
    assert_is_null,
    assert_money_equals,
    assert_pct_equals,
    assert_score_equals,
    assert_status,
    collect,
    create_cedent,
    create_claim_advocacy_payload,
    create_exposure_submission,
    create_program,
    list_rows,
    notify_claim,
    place_lines,
    read_advocacy,
    read_cedent,
    read_layer,
    read_program,
    read_signing_line,
    read_submission,
    refresh,
    review_claim,
    setup_bound_program,
    setup_program_in_market,
    sign_down,
    signoff,
    signoff_payload,
    submit_for_review,
    set_clock,
    validate_error,
    validate_success,
    api_client,
)

LEAD = TEST_USERS["placement_lead_headers"]
ACTUARY = TEST_USERS["actuary_headers"]

# ---------------------------------------------------------------------------
# Instance 1 — the sign-off floor of 70.00
# ---------------------------------------------------------------------------
# Twin exposure packages differing only in ``data_quality_flags_count``. Both
# supply 1,000 records, four years of history and a 56.0000% loss history with no
# actuarial report, so the score is 40 * unflagged/1000 + 25 * 4/5 + 25 * 0.56.
# 100 flags scores 36 + 20 + 14 = 70.00 exactly; 150 flags scores 34 + 20 + 14 = 68.00.
TWIN_PACKAGE_BASE = {
    "exposure_records_count": 1000,
    "historical_years_supplied": 4,
    "cat_model_version": "RMS-23.1",
    "loss_history_completeness_pct": 56.0000,
    "actuarial_report_attached": False,
}
TWIN_PACKAGE_SPECS = (
    ("at_the_floor", "Northwind Property CAT 2026", "PROPERTY", "NW-PROP-2026-EDP", 100),
    ("below_the_floor", "Northwind Marine CAT 2026", "MARINE", "NW-MAR-2026-EDP", 150),
)

# ---------------------------------------------------------------------------
# Instance 2 — the strict 100.0000 oversubscription boundary
# ---------------------------------------------------------------------------
# Alpha Re leads at 60.0000 and Bravo Re follows, against a 1,000,000,000 limit
# and a 1,000,000,000 aggregate each.
BOUNDARY_MARKET_SPECS = [
    {
        "name": "Alpha Re",
        "security_rating": "AA",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 60.0000,
        "lead_authorised": True,
    },
    {
        "name": "Bravo Re",
        "security_rating": "A",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 40.0000,
        "lead_authorised": False,
    },
]
# The same pair, with Bravo Re allowed the single extra basis point that carries
# the written total from exactly 100.0000 to 100.0001.
PAST_BOUNDARY_MARKET_SPECS = [
    dict(BOUNDARY_MARKET_SPECS[0]),
    dict(BOUNDARY_MARKET_SPECS[1], max_line_pct=40.0001),
]

# ---------------------------------------------------------------------------
# Instance 3 — the strict zero boundary on aggregate cover
# ---------------------------------------------------------------------------
# Echo Re writes the whole catastrophe layer: limit 1,000,000,000 attaching at
# 2,000,000,000 with one reinstatement, so the aggregate is 2,000,000,000 and
# the frozen gross premium is 97,125,000.
ECHO_MARKET_SPECS = [
    {
        "name": "Echo Re",
        "security_rating": "AA",
        "capacity_limit_minor": 1_000_000_000,
        "max_line_pct": 100.0000,
        "lead_authorised": True,
    }
]


def _twin_packages_at_the_signoff_floor():
    """One cedent, two DRAFT programs, twin packages scoring 70.00 and 68.00."""
    set_clock(CLOCK["PLACEMENT_START"])
    cedent = create_cedent()
    ctx = {"cedent": cedent}
    for key, program_name, line_of_business, package_label, flags in TWIN_PACKAGE_SPECS:
        program = create_program(
            cedent["id"], program_name=program_name, line_of_business=line_of_business
        )
        submission = create_exposure_submission(
            program["id"],
            cedent["id"],
            package_label=package_label,
            data_quality_flags_count=flags,
            **TWIN_PACKAGE_BASE,
        )
        submit_for_review(submission["id"])
        ctx[key] = {
            "program": program,
            "created": submission,
            "submission": read_submission(submission["id"]),
        }
    return ctx


def _layer_written_to(first_line_pct: float, second_line_pct: float, market_specs):
    """Two markets write the given lines on one PRO_RATA catastrophe layer."""
    ctx = setup_program_in_market(
        market_specs=market_specs,
        program_overrides={
            "program_name": "Northwind Property CAT 2026",
            "signdown_method": "PRO_RATA",
        },
        submission_overrides={"package_label": "NW-CAT-2026-EDP"},
    )
    place_lines(
        ctx,
        [
            {
                "market_index": 0,
                "accepted_line_pct": first_line_pct,
                "offered_line_pct": first_line_pct,
                "is_lead": True,
            },
            {
                "market_index": 1,
                "accepted_line_pct": second_line_pct,
                "offered_line_pct": second_line_pct,
                "is_lead": False,
            },
        ],
    )
    return refresh(ctx)


def _collect_in_full(ctx, claim_reference: str, event_date: str, gross_claim_minor: int,
                     amount_minor: int):
    """Notify, review and collect one cession in full so the file reaches COLLECTED."""
    advocacy = notify_claim(
        ctx["layer"]["id"],
        ctx["cedent"]["id"],
        claim_reference=claim_reference,
        event_date=event_date,
        gross_claim_minor=gross_claim_minor,
    )
    review_claim(advocacy["id"])
    collect(advocacy["id"], ctx["signing_lines"][0]["id"], amount_minor)
    return read_advocacy(advocacy["id"])


def test_completeness_score_of_exactly_seventy_signs_off_and_opens_the_marketing_window():
    """A package scoring exactly 70.00 clears the sign-off floor.

    PRD: "A `decision` of `SIGNED_OFF` requires the package's
    `completeness_score` to be at least 70.00 — a score of exactly 70.00 passes —
    and a lower score is refused with `ERR_SIGNOFF_SCORE_TOO_LOW`."

    Design: Difficulty/boundary_precision_check/completeness_score_exactly_seventy_passes_signoff_while_sixty_eight_rejects
    """
    ctx = _twin_packages_at_the_signoff_floor()
    at_floor, below_floor = ctx["at_the_floor"], ctx["below_the_floor"]

    assert_score_equals(
        at_floor["created"]["completeness_score"], 70.00, "PROPERTY completeness_score"
    )
    assert_score_equals(
        below_floor["created"]["completeness_score"], 68.00, "MARINE completeness_score"
    )

    signed_off = signoff(
        at_floor["submission"]["id"], "SIGNED_OFF", review_note="at the floor but acceptable"
    )

    assert_status(signed_off, "status", "SIGNED_OFF")
    assert signed_off["actuary_signoff_user_id"] == "act-1", (
        "actuary_signoff_user_id must be stamped with the acting actuary's X-User-ID, "
        f"got {signed_off['actuary_signoff_user_id']!r}"
    )
    assert_instant_equals(
        signed_off["signed_off_at"], CLOCK["PLACEMENT_START"], "signed_off_at"
    )
    assert signed_off["review_note"] == "at the floor but acceptable", (
        f"review_note must record the supplied note, got {signed_off['review_note']!r}"
    )
    assert_score_equals(
        signed_off["completeness_score"], 70.00, "signed-off completeness_score"
    )

    assert_status(
        read_program(at_floor["program"]["id"]), "placement_status", "SUBMISSION_READY"
    )
    assert_status(read_program(below_floor["program"]["id"]), "placement_status", "DRAFT")


def test_completeness_score_below_the_floor_is_refused_and_leaves_the_program_in_draft():
    """The twin package scoring 68.00 is refused, so its program never opens.

    PRD: "A `decision` of `SIGNED_OFF` requires the package's
    `completeness_score` to be at least 70.00 — a score of exactly 70.00 passes —
    and a lower score is refused with `ERR_SIGNOFF_SCORE_TOO_LOW`."

    Design: Difficulty/boundary_precision_check/completeness_score_exactly_seventy_passes_signoff_while_sixty_eight_rejects
    """
    ctx = _twin_packages_at_the_signoff_floor()
    at_floor, below_floor = ctx["at_the_floor"], ctx["below_the_floor"]

    assert_score_equals(
        at_floor["created"]["completeness_score"], 70.00, "PROPERTY completeness_score"
    )
    assert_score_equals(
        below_floor["created"]["completeness_score"], 68.00, "MARINE completeness_score"
    )

    response = api_client.signoff_exposure_submission(
        below_floor["submission"]["id"], signoff_payload("SIGNED_OFF"), ACTUARY
    )

    validate_error(response, ApiErrorId.ERR_SIGNOFF_SCORE_TOO_LOW.value)

    refused = read_submission(below_floor["submission"]["id"])
    assert_status(refused, "status", "ACTUARY_REVIEW")
    assert_is_null(refused, "actuary_signoff_user_id")
    assert_is_null(refused, "signed_off_at")
    assert_score_equals(refused["completeness_score"], 68.00, "refused completeness_score")

    assert_status(read_program(below_floor["program"]["id"]), "placement_status", "DRAFT")
    assert_status(read_program(at_floor["program"]["id"]), "placement_status", "DRAFT")


def test_written_line_total_of_exactly_one_hundred_is_fully_placed_and_refuses_sign_down():
    """Lines of 60.0000 and 40.0000 sit on the boundary, so sign-down is refused.

    PRD: "The placing broker signs a layer down; the layer must be
    `OVERSUBSCRIBED`, meaning its `written_line_total_pct` is **strictly** greater
    than `100.0000` — a layer sitting on exactly `100.0000` is `FULLY_PLACED` and
    signing it down is `ERR_LAYER_NOT_OVERSUBSCRIBED` — and the owning program
    must be in `FIRM_ORDER`, else `ERR_PROGRAM_STATE_INVALID`."

    Design: Difficulty/boundary_precision_check/layer_written_total_exactly_one_hundred_cannot_be_signed_down
    """
    ctx = _layer_written_to(60.0000, 40.0000, BOUNDARY_MARKET_SPECS)
    lead_line, follower_line = ctx["signing_lines"][0], ctx["signing_lines"][1]

    placed = read_layer(ctx["layer"]["id"])
    assert_pct_equals(placed["written_line_total_pct"], 100.0000, "written_line_total_pct")
    assert_status(placed, "status", "FULLY_PLACED")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "FIRM_ORDER")

    response = api_client.sign_down_layer(ctx["layer"]["id"], LEAD)

    validate_error(response, ApiErrorId.ERR_LAYER_NOT_OVERSUBSCRIBED.value)

    layer = read_layer(ctx["layer"]["id"])
    assert_pct_equals(layer["written_line_total_pct"], 100.0000, "written_line_total_pct")
    assert_status(layer, "status", "FULLY_PLACED")
    assert_pct_equals(layer["signed_line_total_pct"], 0.0000, "signed_line_total_pct")

    lead = read_signing_line(lead_line["id"])
    follower = read_signing_line(follower_line["id"])
    assert_is_null(lead, "signed_line_pct")
    assert_is_null(follower, "signed_line_pct")
    assert_status(lead, "status", "PROVISIONAL")
    assert_status(follower, "status", "PROVISIONAL")
    assert_money_equals(
        lead["committed_capacity_minor"], 600_000_000, "lead committed_capacity_minor"
    )
    assert_money_equals(
        follower["committed_capacity_minor"], 400_000_000, "follower committed_capacity_minor"
    )

    assert_status(read_program(ctx["program"]["id"]), "placement_status", "FIRM_ORDER")


def test_written_line_total_one_basis_point_past_one_hundred_admits_the_sign_down():
    """The same pair written 60.0000 and 40.0001 is OVERSUBSCRIBED and signs down.

    PRD: "The placing broker signs a layer down; the layer must be
    `OVERSUBSCRIBED`, meaning its `written_line_total_pct` is **strictly** greater
    than `100.0000` — a layer sitting on exactly `100.0000` is `FULLY_PLACED` and
    signing it down is `ERR_LAYER_NOT_OVERSUBSCRIBED` — and the owning program
    must be in `FIRM_ORDER`, else `ERR_PROGRAM_STATE_INVALID`."

    Design: Difficulty/boundary_precision_check/layer_written_total_exactly_one_hundred_cannot_be_signed_down
    """
    ctx = _layer_written_to(60.0000, 40.0001, PAST_BOUNDARY_MARKET_SPECS)
    lead_line, follower_line = ctx["signing_lines"][0], ctx["signing_lines"][1]

    oversubscribed = read_layer(ctx["layer"]["id"])
    assert_pct_equals(
        oversubscribed["written_line_total_pct"], 100.0001, "written_line_total_pct"
    )
    assert_status(oversubscribed, "status", "OVERSUBSCRIBED")
    assert_status(read_program(ctx["program"]["id"]), "placement_status", "FIRM_ORDER")

    layer = sign_down(ctx["layer"]["id"])

    assert_pct_equals(layer["signed_line_total_pct"], 100.0000, "signed_line_total_pct")
    assert_status(layer, "status", "SIGNED_DOWN")

    lead = read_signing_line(lead_line["id"])
    follower = read_signing_line(follower_line["id"])
    assert_pct_equals(lead["signed_line_pct"], 59.9999, "lead signed_line_pct")
    assert_pct_equals(follower["signed_line_pct"], 40.0001, "follower signed_line_pct")
    assert_status(lead, "status", "SIGNED")
    assert_status(follower, "status", "SIGNED")
    assert_money_equals(
        lead["committed_capacity_minor"], 599_999_000, "lead committed_capacity_minor"
    )
    assert_money_equals(
        follower["committed_capacity_minor"], 400_001_000, "follower committed_capacity_minor"
    )


def test_aggregate_available_of_exactly_zero_refuses_the_next_notification():
    """Two collected 1,000,000,000 cessions burn the whole aggregate, so CL-003 is refused.

    PRD: "And the layer must have aggregate cover left, since a layer whose limit
    and reinstatements are fully eroded has nothing left to cede and the
    notification is `ERR_AGGREGATE_LIMIT_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/aggregate_available_exactly_zero_blocks_the_next_cession
    """
    ctx = setup_bound_program(market_specs=ECHO_MARKET_SPECS)

    first = _collect_in_full(
        ctx, "CL-001", "2026-03-01T00:00:00.000Z", 3_200_000_000, 1_000_000_000
    )
    assert_money_equals(first["ceded_claim_minor"], 1_000_000_000, "CL-001 ceded_claim_minor")
    assert_status(first, "status", "COLLECTED")

    second = _collect_in_full(
        ctx, "CL-002", "2026-06-01T00:00:00.000Z", 3_200_000_000, 1_000_000_000
    )
    assert_money_equals(second["ceded_claim_minor"], 1_000_000_000, "CL-002 ceded_claim_minor")
    assert_status(second, "status", "COLLECTED")

    exhausted = read_layer(ctx["layer"]["id"])
    assert_money_equals(exhausted["limit_eroded_minor"], 2_000_000_000, "limit_eroded_minor")
    assert exhausted["reinstatements_used"] == 1, (
        f"reinstatements_used must be 1, got {exhausted['reinstatements_used']!r}"
    )

    response = api_client.create_claim_advocacy(
        ctx["layer"]["id"],
        create_claim_advocacy_payload(
            claim_reference="CL-003",
            event_date="2026-09-01T00:00:00.000Z",
            gross_claim_minor=2_600_000_000,
        ),
        LEAD,
    )

    validate_error(response, ApiErrorId.ERR_AGGREGATE_LIMIT_EXHAUSTED.value)

    rows = list_rows(api_client.list_layer_claim_advocacies(ctx["layer"]["id"], LEAD))
    assert len(rows) == 2, f"CL-003 must never have been created, got {len(rows)} advocacies"

    assert_money_equals(
        read_cedent(ctx["cedent"]["id"])["outstanding_reinstatement_premium_minor"],
        97_125_000,
        "outstanding_reinstatement_premium_minor",
    )


def test_aggregate_available_of_one_minor_unit_still_admits_a_notification_ceding_one():
    """Eroding 1,999,999,999 of the 2,000,000,000 aggregate leaves a cession of exactly 1.

    PRD: "The `ceded_claim_minor` is then the minimum of the subject amount, the
    per-event cap, the layer's `limit_minor` and the aggregate available amount."

    Design: Difficulty/boundary_precision_check/aggregate_available_exactly_zero_blocks_the_next_cession
    """
    ctx = setup_bound_program(market_specs=ECHO_MARKET_SPECS)

    first = _collect_in_full(
        ctx, "CL-001", "2026-03-01T00:00:00.000Z", 3_200_000_000, 1_000_000_000
    )
    assert_money_equals(first["ceded_claim_minor"], 1_000_000_000, "CL-001 ceded_claim_minor")

    second = _collect_in_full(
        ctx, "CL-002", "2026-06-01T00:00:00.000Z", 2_999_999_999, 999_999_999
    )
    assert_money_equals(second["ceded_claim_minor"], 999_999_999, "CL-002 ceded_claim_minor")
    assert_status(second, "status", "COLLECTED")

    nearly_exhausted = read_layer(ctx["layer"]["id"])
    assert_money_equals(
        nearly_exhausted["limit_eroded_minor"], 1_999_999_999, "limit_eroded_minor"
    )
    assert nearly_exhausted["reinstatements_used"] == 1, (
        f"reinstatements_used must be 1, got {nearly_exhausted['reinstatements_used']!r}"
    )

    response = api_client.create_claim_advocacy(
        ctx["layer"]["id"],
        create_claim_advocacy_payload(
            claim_reference="CL-003",
            event_date="2026-09-01T00:00:00.000Z",
            gross_claim_minor=2_600_000_000,
        ),
        LEAD,
    )

    admitted = validate_success(response, 201)
    assert_money_equals(admitted["ceded_claim_minor"], 1, "CL-003 ceded_claim_minor")
    assert_status(admitted, "status", "NOTIFIED")

    rows = list_rows(api_client.list_layer_claim_advocacies(ctx["layer"]["id"], LEAD))
    assert len(rows) == 3, f"CL-003 must have been created, got {len(rows)} advocacies"

    unchanged = read_layer(ctx["layer"]["id"])
    assert_money_equals(
        unchanged["limit_eroded_minor"], 1_999_999_999, "limit_eroded_minor after notification"
    )
