"""AI writing assessment: scoring blend, bands, suppression gate (PRD §3.6)."""
from test_helpers import (
    get_assessment,
    process,
    setup_basic_scenario,
    submit,
    words,
)


def test_ai_assessment_point_vs_conservative_diverge(api):
    """PRD §3.6: "The blend is a weighted sum: half of `ai_burstiness` plus three
    tenths of `ai_perplexity` plus one fifth of `ai_stylometry`; the **point
    estimate** `ai_score_bps` is ten thousand times that blend, rounded half up.
    The spread between the largest and smallest of the three signals determines
    `confidence_band`: a spread of at most 0.15 is `HIGH`, otherwise at most
    0.30 is `MEDIUM`, otherwise `LOW`. The **conservative bound**
    `conservative_score_bps` subtracts a band-dependent margin from the point
    estimate — 500 basis points for `HIGH`, 1500 for `MEDIUM`, 2500 for `LOW` —
    floored at zero."

    Design: Difficulty/dual_variant_calc/ai_assessment_point_vs_conservative_diverge
    """
    inst, integ, instr, student, asg = setup_basic_scenario("EU")
    sub = submit(
        asg["id"], student["id"], words(250),
        ai_burstiness=0.62, ai_perplexity=0.74, ai_stylometry=0.50,
    )
    process(sub["id"], instr["id"])
    a = get_assessment(sub["id"], instr["id"])
    assert a["assessment_state"] == "COMPLETE"
    # 0.62*0.5 + 0.74*0.3 + 0.50*0.2 = 0.632 -> 6320 bps
    assert a["ai_score_bps"] == 6320
    # spread = 0.74 - 0.50 = 0.24 -> 0.15 < 0.24 <= 0.30 -> MEDIUM
    assert a["confidence_band"] == "MEDIUM"
    # conservative = 6320 - 1500 = 4820
    assert a["conservative_score_bps"] == 4820
    assert a["conservative_score_bps"] != a["ai_score_bps"]


def test_ai_assessment_point_estimate_component_values(api):
    """PRD §3.6: "when the institution's `ai_detection_enabled` is false, or the
    submission's `word_count` is below 250, it lands in `SUPPRESSED` — a
    terminal state — with `ai_score_bps`, `confidence_band`, and
    `conservative_score_bps` all null. Otherwise, provided all three signal
    fields `ai_burstiness`, `ai_perplexity`, and `ai_stylometry` are present on
    the submission, the assessment moves to `COMPLETE` and is scored."

    Design: Difficulty/dual_variant_calc/ai_assessment_point_vs_conservative_diverge
    """
    inst, integ, instr, student, asg = setup_basic_scenario("EU")
    sub = submit(
        asg["id"], student["id"], words(250),
        ai_burstiness=0.62, ai_perplexity=0.74, ai_stylometry=0.50,
    )
    process(sub["id"], instr["id"])
    a = get_assessment(sub["id"], instr["id"])
    # word_count == 250 meets the minimum; ai_detection_enabled defaults true.
    assert a["assessment_state"] == "COMPLETE"
    assert a["ai_score_bps"] is not None
    assert a["confidence_band"] is not None
    assert a["conservative_score_bps"] is not None


def test_ai_confidence_band_high_boundary(api):
    """PRD §3.6: "a spread of at most 0.15 is `HIGH`, otherwise at most 0.30 is
    `MEDIUM`, otherwise `LOW`."

    Design: Corner/calculations/ai_confidence_band_high_boundary
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "US", assignment_overrides={"max_submissions_per_student": 5}
    )
    sub_a = submit(
        asg["id"], student["id"], words(250),
        ai_burstiness=0.50, ai_perplexity=0.55, ai_stylometry=0.65,
    )
    sub_b = submit(
        asg["id"], student["id"], words(250),
        ai_burstiness=0.10, ai_perplexity=0.20, ai_stylometry=0.41,
    )
    process(sub_a["id"], instr["id"])
    process(sub_b["id"], instr["id"])

    a = get_assessment(sub_a["id"], instr["id"])
    # spread 0.65 - 0.50 == 0.15 <= 0.15 -> HIGH
    assert a["confidence_band"] == "HIGH"
    # 0.50*0.5 + 0.55*0.3 + 0.65*0.2 = 0.545 -> 5450
    assert a["ai_score_bps"] == 5450
    assert a["conservative_score_bps"] == 5450 - 500

    b = get_assessment(sub_b["id"], instr["id"])
    # spread 0.41 - 0.10 == 0.31 > 0.30 -> LOW
    assert b["confidence_band"] == "LOW"
    # 0.10*0.5 + 0.20*0.3 + 0.41*0.2 = 0.192 -> 1920
    assert b["ai_score_bps"] == 1920
    # floored at zero: max(0, 1920 - 2500) == 0
    assert b["conservative_score_bps"] == 0


def test_ai_assessment_suppressed_when_policy_disabled(api):
    """PRD §3.6: "when the institution's `ai_detection_enabled` is false, or the
    submission's `word_count` is below 250, it lands in `SUPPRESSED` — a
    terminal state — with `ai_score_bps`, `confidence_band`, and
    `conservative_score_bps` all null."

    Design: Corner/calculations/ai_assessment_suppressed_when_policy_disabled
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        "EU", inst_overrides={"ai_detection_enabled": False}
    )
    sub = submit(
        asg["id"], student["id"], words(300),
        ai_burstiness=0.9, ai_perplexity=0.9, ai_stylometry=0.9,
    )
    process(sub["id"], instr["id"])
    a = get_assessment(sub["id"], instr["id"])
    assert a["assessment_state"] == "SUPPRESSED", (
        "the institution policy flag dominates even with 300 words and full signals"
    )
    assert a["ai_score_bps"] is None
    assert a["confidence_band"] is None
    assert a["conservative_score_bps"] is None
