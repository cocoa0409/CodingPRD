"""Media tests: provisional vs settled MER, pinned per-line rounding order,
decision-band enforcement, parallel state dimensions (PRD §3.4, §3.5, §3.9).
"""
import pytest

from test_helpers import (
    MEDIA,
    ApiErrorId,
    api_client,
    air_media_test_payload,
    challenge_claim_study,
    create_media_test,
    decide_media_test,
    get_variant,
    order_line,
    run_review,
    set_clock,
    setup_airing_media,
    setup_decided_scale_media,
    setup_retail_live_fulfilled,
    setup_season_with_category,
    setup_substantiated_study,
    setup_tooled_variant,
    validate_error,
    validate_ok,
)

BAND_LINES = [order_line(3335), order_line(3335), order_line(3334)]


def _airing_variant(category_id: str, spend: int = 1000, gross: int = 1500) -> tuple:
    """TOOLED variant + SUBSTANTIATED claim + media test AIRING (PRD §3.5)."""
    bundle = setup_tooled_variant(category_id)
    setup_substantiated_study(bundle["variant"]["id"])
    media = setup_airing_media(
        bundle["variant"]["id"], media_spend_cents=spend, projected_gross_cents=gross
    )
    return bundle, media


def test_media_mer_provisional_and_settled_diverge_for_identical_spend(api):
    """PRD §3.5: "For identical spend the provisional and settled ratios
    therefore diverge by design: the provisional variant is an estimate from
    projected gross, the settled variant is a realized measure from actual
    order lines."

    Design: Difficulty/dual_variant_calc/media_mer_provisional_vs_settled_diverge
    """
    base = setup_season_with_category()
    bundle, media = _airing_variant(base["category"]["id"], spend=1000, gross=1500)
    assert media["provisional_mer"] == pytest.approx(1.5, abs=1e-9)
    decided = decide_media_test(media["id"], "SCALE", BAND_LINES)
    assert decided["settled_mer"] == pytest.approx(8.504, abs=1e-9)
    assert decided["provisional_mer"] != decided["settled_mer"]
    assert decided["status"] == "DECIDED_SCALE"


def test_scale_decision_binds_to_settled_not_provisional_ratio(api):
    """PRD §3.5: "`SCALE` requires the settled ratio to be at least 2.0 —
    inclusive, so a settled ratio of exactly 2.0000 scales — while `KILL`
    requires it to be below 2.0. A decision contradicting the band is rejected
    with `ERR_DECISION_BAND_MISMATCH`."

    The provisional ratio here is 1.5 (below the band) while the settled ratio
    is 8.504 (inside it); SCALE is accepted, so the band binds to the settled
    variant.

    Design: Difficulty/dual_variant_calc/media_mer_provisional_vs_settled_diverge
    """
    base = setup_season_with_category()
    bundle, media = _airing_variant(base["category"]["id"], spend=1000, gross=1500)
    assert media["provisional_mer"] == pytest.approx(1.5, abs=1e-9)
    decided = decide_media_test(media["id"], "SCALE", BAND_LINES)
    assert decided["settled_mer"] == pytest.approx(8.504, abs=1e-9)
    assert decided["status"] == "DECIDED_SCALE"


def test_settled_mer_rounds_commission_per_order_line(api):
    """PRD §3.5: "For each order line, the net revenue — `revenue_cents` minus
    `cancels_cents` minus `returns_cents` — is multiplied by 0.85, which is one
    minus the 0.15 agency commission rate, and that per-line
    commission-adjusted amount is rounded half-up to whole cents. The per-line
    results are then summed, the sum is divided by `media_spend_cents`, and
    only this final ratio is rounded half-up to 4 decimal places."

    Design: Difficulty/combinatorial_formula/media_settled_mer_per_line_rounding_order_pinned
    """
    base = setup_season_with_category()
    bundle, media = _airing_variant(base["category"]["id"], spend=2000, gross=3000)
    decided = decide_media_test(media["id"], "SCALE", BAND_LINES)
    # Per-line: 2835 + 2835 + 2834 = 8504; 8504 / 2000 = 4.252.
    assert decided["settled_mer"] == pytest.approx(4.252, abs=1e-9)
    # Rejected whole-sum order: round(10004 * 0.85) = 8503; 8503 / 2000 = 4.2515.
    assert decided["settled_mer"] != pytest.approx(4.2515, abs=1e-9)


def test_settled_mer_per_line_order_provisional_remains_projection(api):
    """PRD §3.5: "On airing, the server stamps `aired_at` from the logical
    clock and computes `provisional_mer` as `projected_gross_cents` divided by
    `media_spend_cents`, rounded half-up to 4 decimal places — a
    forward-looking estimate that nets out nothing: no cancels, no returns,
    and no agency commission."

    Design: Difficulty/combinatorial_formula/media_settled_mer_per_line_rounding_order_pinned
    """
    base = setup_season_with_category()
    bundle, media = _airing_variant(base["category"]["id"], spend=2000, gross=3000)
    assert media["provisional_mer"] == pytest.approx(1.5, abs=1e-9)
    assert media["aired_at"] is not None
    decided = decide_media_test(media["id"], "SCALE", BAND_LINES)
    assert decided["settled_mer"] == pytest.approx(4.252, abs=1e-9)
    assert decided["status"] == "DECIDED_SCALE"
    assert decided["decided_at"] is not None


def test_decision_band_rejects_kill_when_settled_mer_high(api):
    """PRD §3.5: "`SCALE` requires the settled ratio to be at least 2.0 —
    inclusive, so a settled ratio of exactly 2.0000 scales — while `KILL`
    requires it to be below 2.0. A decision contradicting the band is rejected
    with `ERR_DECISION_BAND_MISMATCH`."

    Design: Corner/calculations/decision_band_rejects_kill_when_settled_mer_high
    """
    base = setup_season_with_category()
    bundle, media = _airing_variant(base["category"]["id"], spend=1000, gross=1500)
    resp = api_client.decide_media_test(
        media["id"], {"decision": "KILL", "order_lines": BAND_LINES}, MEDIA
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_BAND_MISMATCH)
    tests = validate_ok(
        api_client.list_variant_media_tests(bundle["variant"]["id"], MEDIA)
    )
    assert tests[0]["status"] == "AIRING"
    decided = decide_media_test(media["id"], "SCALE", BAND_LINES)
    assert decided["status"] == "DECIDED_SCALE"


def test_scale_decision_below_band_rejected(api):
    """PRD §3.5: "`SCALE` requires the settled ratio to be at least 2.0 —
    inclusive, so a settled ratio of exactly 2.0000 scales — while `KILL`
    requires it to be below 2.0. A decision contradicting the band is rejected
    with `ERR_DECISION_BAND_MISMATCH`."

    Design: Corner/calculations/scale_decision_below_band_rejected
    """
    base = setup_season_with_category()
    bundle, media = _airing_variant(base["category"]["id"], spend=1000, gross=1500)
    low_lines = [order_line(1765)]  # round(1765 * 0.85) = 1500; 1500/1000 = 1.5
    resp = api_client.decide_media_test(
        media["id"], {"decision": "SCALE", "order_lines": low_lines}, MEDIA
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_BAND_MISMATCH)
    killed = decide_media_test(media["id"], "KILL", low_lines)
    assert killed["status"] == "KILLED"
    assert killed["settled_mer"] == pytest.approx(1.5, abs=1e-9)


def test_media_air_from_decided_scale_rejected(api):
    """PRD §2.10: "the target resource must be in a state from which the
    requested transition exists ... with all other undefined transitions
    rejected as `ERR_INVALID_STATE`."

    Design: Corner/state_machines/media_air_from_decided_scale_rejected
    """
    base = setup_season_with_category()
    bundle = setup_tooled_variant(base["category"]["id"])
    setup_substantiated_study(bundle["variant"]["id"])
    media = setup_decided_scale_media(bundle["variant"]["id"])
    resp = api_client.air_media_test(media["id"], air_media_test_payload(2000), MEDIA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_media_airing_autokill_after_decision_window(api):
    """PRD §3.5: "A test still `AIRING` more than 28 days after `aired_at`
    without a decision is killed automatically at the run-review."

    Design: Corner/state_machines/media_airing_autokill_after_decision_window
    """
    base = setup_season_with_category()
    bundle, media = _airing_variant(base["category"]["id"])  # aired 2026-09-10
    set_clock("2026-10-09T00:00:00Z")  # 29 days later
    run_review(base["season"]["id"])
    tests = validate_ok(
        api_client.list_variant_media_tests(bundle["variant"]["id"], MEDIA)
    )
    assert tests[0]["status"] == "KILLED"


def test_challenged_claim_does_not_move_retail_live_lifecycle(api):
    """PRD §3.4: "The claim-clearance dimension evolves independently of the
    variant's lifecycle — a `RETAIL_LIVE` variant can perfectly well be
    `CHALLENGED` — and clearance alone gates whether a media test may air, as
    §3.5 describes."

    Design: Difficulty/non_linear_state_machine/model_variant_parallel_dimensions_evolve_independently
    """
    bundle = setup_retail_live_fulfilled()
    challenge_claim_study(bundle["study"]["id"], "Competitor ITC complaint")
    variant = get_variant(bundle["variant"]["id"])
    assert variant["lifecycle"] == "RETAIL_LIVE"
    assert variant["claim_clearance"] == "CHALLENGED"


def test_challenged_clearance_alone_blocks_new_media_air(api):
    """PRD §3.5: "the variant's `claim_clearance` must be `SUBSTANTIATED`, else
    `ERR_CLAIM_NOT_SUBSTANTIATED`" and PRD §3.5: "A `MediaBuyer` creates a
    MediaTest for a variant whose `lifecycle` is `TOOLED`, `DR_TESTING`, or
    `RETAIL_LIVE` — any other state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/model_variant_parallel_dimensions_evolve_independently
    """
    bundle = setup_retail_live_fulfilled()
    challenge_claim_study(bundle["study"]["id"], "Competitor ITC complaint")
    media2 = create_media_test(
        bundle["variant"]["id"], "Post-launch flight", 800
    )
    assert media2["status"] == "EDITING"
    resp = api_client.air_media_test(
        media2["id"], air_media_test_payload(2000), MEDIA
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SUBSTANTIATED)
