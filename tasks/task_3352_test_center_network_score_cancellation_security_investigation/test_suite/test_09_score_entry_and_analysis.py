"""Score entry gating, provisional/equated rounding order, mean-includes-self."""
from test_helpers import (
    ApiErrorId,
    RAWS_PROVISIONAL_120,
    RAWS_PROVISIONAL_97,
    check_in_admit,
    get_score_record,
    lock_session,
    register_new_examinee,
    setup_administered_session,
    setup_analyzed_session,
    setup_bookable_session,
    validate_error,
    validate_success,
)
from test_helpers import create_score_entry_payload


def test_score_entry_before_administered_rejected(api, score_analyst_headers):
    """PRD §3.5: "Score entry is valid only while the session is
    `ADMINISTERED` (else `ERR_SESSION_NOT_ADMINISTERED`) and only for a
    registration whose `attendance_status` is `ADMITTED`"

    Design: Corner/validations/score_entry_before_administered_rejected
    """
    ctx = setup_bookable_session(name="Center SE", total_seats=5, with_proctor=True)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex SE", id_document_number="PSE1"
    )
    lock_session(session_id, ctx["manager"]["id"])
    check_in_admit(registration["id"], examinee, ctx["proctor"]["id"])
    # The session is LOCKED, not ADMINISTERED.
    resp = api.create_score_entry(
        registration["id"],
        create_score_entry_payload([10, 10, 10], 30),
        score_analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_ADMINISTERED)
    scores = validate_success(
        api.get_registration_score(registration["id"], score_analyst_headers), 200
    )
    assert scores == [], "no ScoreRecord created by the rejected entry"


def test_provisional_rounding_per_section_then_sum(api):
    """PRD §3.5: "The rounding order is pinned: summing the weighted raws
    first and rounding once is a rejected variant, and the difference is real
    — raws of 33, 21, and 40 yield per-section integers of 40, 17, and 40 for
    a provisional of 97, whereas the rejected sum-first order would round 96.4
    to 96."

    Design: Difficulty/combinatorial_formula/rounding_order_per_section_then_sum
    """
    ctx = setup_administered_session(
        [{"section_raws": RAWS_PROVISIONAL_97, "prior_best_scaled_score": 80}],
        name="Center RB", total_seats=5,
    )
    record = ctx["score_records"][0]
    assert record["provisional_scaled_score"] == 97, (
        "round_half_up(39.6)+round_half_up(16.8)+round_half_up(40.0) = 40+17+40"
    )
    assert record["provisional_scaled_score"] != 96, (
        "sum-then-round is the rejected variant (round_half_up(96.4))"
    )


def test_provisional_raw_total_is_plain_sum(api):
    """PRD §3.5: "The `raw_total` is the plain sum of the three section raws.
    The `provisional_scaled_score` applies per-section weights — 1.2 to the
    first section, 0.8 to the second, 1.0 to the third — by multiplying each
    raw by its weight, rounding each product half-up to an integer first, and
    only then summing the three integers."
    PRD §3.5: "it both creates the `ScoreRecord` — born `PENDING_ANALYSIS`
    with `scaled_score` still null and `released_report_count` at zero — and
    completes the attendance dimension, moving the registration from
    `ADMITTED` to `COMPLETED`."

    Design: Difficulty/combinatorial_formula/rounding_order_per_section_then_sum
    """
    ctx = setup_administered_session(
        [{"section_raws": RAWS_PROVISIONAL_97, "prior_best_scaled_score": 80}],
        name="Center RB2", total_seats=5,
    )
    record = ctx["score_records"][0]
    assert record["raw_total"] == 94, "33 + 21 + 40"
    assert record["provisional_scaled_score"] == 97
    assert record["status"] == "PENDING_ANALYSIS"
    assert record["scaled_score"] is None
    assert record["released_report_count"] == 0


def _two_record_analysis(name):
    """Raws [33,21,40] (raw_total 94) and [40,40,40] (raw_total 120), both
    admitted and score-entered, then the analysis run.

    Session mean raw = round_half_up((94+120)/2, 2) = 107.00, and the mean
    includes the record being scored.
    """
    specs = [
        {"section_raws": RAWS_PROVISIONAL_97, "prior_best_scaled_score": 80,
         "id_document_number": "PEA1"},
        {"section_raws": RAWS_PROVISIONAL_120, "prior_best_scaled_score": 100,
         "id_document_number": "NEB1", "id_document_type": "NATIONAL_ID",
         "id_document_expiry": "2028-01-01"},
    ]
    return setup_analyzed_session(specs, name=name, total_seats=10)


def test_equated_mean_includes_self(api):
    """PRD §3.5: "Second, the session mean raw is computed as the sum of all
    those raw totals divided by the number of records — the mean includes the
    record being scored — rounded half-up to 2 decimal places."
    PRD §3.5: "The provisional and equated variants genuinely diverge — a
    record with raw total 94 in a session whose mean raw is 107.00 finishes at
    91 rather than its provisional 97."

    Design: Difficulty/combinatorial_formula/equated_mean_includes_self_order
    """
    ctx = _two_record_analysis("Center EQ")
    record_a = get_score_record(ctx["score_records"][0]["id"])
    assert record_a["scaled_score"] == 91, (
        "97 + floor(0.5*(94-107.00)+0.5) = 97 + floor(-6.0)"
    )
    assert record_a["scaled_score"] != 85, (
        "a self-excluded mean (120.00) would give 97 + floor(-12.5+0.5) = 85"
    )


def test_equated_mean_applies_to_every_record(api):
    """PRD §3.5: "Third, each record's `scaled_score` is its provisional score
    plus the equating adjustment, where the adjustment is half of the
    difference between the record's own raw total and the session mean raw,
    rounded half-up with half-up defined as the floor of the value plus one
    half, so negative halves round toward zero: an adjustment of minus six and
    a half lands on minus six."

    Design: Difficulty/combinatorial_formula/equated_mean_includes_self_order
    """
    ctx = _two_record_analysis("Center EQ2")
    record_b = get_score_record(ctx["score_records"][1]["id"])
    assert record_b["provisional_scaled_score"] == 120
    assert record_b["scaled_score"] == 127, (
        "120 + floor(0.5*(120-107.00)+0.5) = 120 + 7"
    )
    record_a = get_score_record(ctx["score_records"][0]["id"])
    assert record_a["scaled_score"] == 91
