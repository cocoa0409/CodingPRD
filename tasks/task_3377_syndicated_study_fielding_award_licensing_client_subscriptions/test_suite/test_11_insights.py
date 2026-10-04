"""Client insights: own-brand diagnostics, competitive benchmarking, and the
year-over-year comparability rule (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_active_subscription,
    make_client_user_headers,
    register_client,
    setup_published_study,
    setup_scored_study,
    validate_error,
    validate_success,
)

_ONE_BRAND = [{"name": "BrandA", "responses": [{"token": "rt-1", "qual": 9, "feat": 8}]}]


def _factor_map(factor_scores):
    """Normalize the per-factor breakdown to {code: integer_score} (PRD §2.7,
    §3.4 pin the values on the 100-1000 band)."""
    if isinstance(factor_scores, dict):
        return dict(factor_scores)
    out = {}
    for entry in factor_scores:
        code = entry.get("factor_code", entry.get("code"))
        score = entry.get("score", entry.get("factor_score"))
        out[code] = score
    return out


def _published_ctx_with_subscription(tier="DIAGNOSTIC"):
    ctx = setup_published_study(min_sample=1, brands=_ONE_BRAND)
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    create_active_subscription(client["id"], ctx["study"]["id"], tier=tier)
    return ctx, client


def test_diagnostics_returns_own_brand_breakdown(api):
    """PRD §3.8: "A `ClientUser` reads its own-brand deep diagnostic on a study:
    the gate first requires the study to be `PUBLISHED` ... The diagnostic returns
    the `study_id`, the client's `brand_id`, the brand's `eligible` flag,
    `accepted_n`, `final_index`, `rank_position`, `significance_group`, and the
    per-factor `factor_scores` breakdown."
    PRD §2.7: "per-brand factor scores landing on the 100–1000 band by
    construction (a mean item score of 1–10 multiplied by 100)"

    Design: Corner/endpoints/diagnostics_returns_own_brand_breakdown
    """
    ctx, client = _published_ctx_with_subscription(tier="DIAGNOSTIC")
    sid = ctx["study"]["id"]
    data = validate_success(api.get_diagnostics(sid, make_client_user_headers(client["id"])))
    assert data["study_id"] == sid
    assert data["brand_id"] == ctx["brands"]["BrandA"]["id"], (
        "the diagnostic is scoped by the caller's Client.brand_id, not a request parameter"
    )
    assert data["eligible"] is True
    assert data["accepted_n"] == 1
    assert data["final_index"] == 860, f"0.6*900 + 0.4*800, got {data['final_index']}"
    assert data["rank_position"] == 1 and data["significance_group"] == 1
    assert _factor_map(data["factor_scores"]) == {"QUAL": 900, "FEAT": 800}


def _two_cycle_ctx(current_change_class="FULL_COMPARABLE"):
    """Prior cycle PUBLISHED with BrandA final 800; current PUBLISHED with 860."""
    prior = setup_published_study(
        min_sample=1, study_code="VDS-2025", cycle_year=2025,
        embargo_lift_at="2025-10-15T00:00:00Z", publish_at="2026-09-01T00:00:00Z",
        brands=[{"name": "BrandA", "responses": [{"token": "rt-1", "qual": 8, "feat": 8}]}],
    )
    brand_id = prior["brands"]["BrandA"]["id"]
    current = setup_published_study(
        min_sample=1, study_code="VDS-2026", cycle_year=2026,
        embargo_lift_at="2026-10-15T00:00:00Z", prior_study_id=prior["study"]["id"],
        publish_at="2026-10-15T00:00:00Z", change_class=current_change_class,
        brands=[{"name": "BrandA", "brand_id": brand_id,
                 "responses": [{"token": "rt-9", "qual": 9, "feat": 8}]}],
    )
    client = register_client(brand_id=brand_id)
    create_active_subscription(client["id"], current["study"]["id"], tier="BENCHMARK")
    return prior, current, client


def test_benchmarking_returns_yoy_delta_when_comparable(api):
    """PRD §3.8: "Year-over-year comparability follows the pinned methodology's
    declared change class: the delta is comparable only when the study's
    `prior_study_id` is set, the prior cycle's study is `PUBLISHED`, the active
    methodology's `change_class` is not `BREAK` — `FULL_COMPARABLE` and `ADJUSTED`
    both permit the comparison while `BREAK` suppresses it — and both cycles hold
    a `final_index` for the client's brand. When comparable, `yoy_comparable` is
    true and `yoy_delta` is the current cycle's `final_index` minus the prior
    cycle's; otherwise `yoy_comparable` is false and `yoy_delta` is null."
    PRD §3.8: "Benchmarking returns the `study_id`, the active methodology's
    `change_class`, the `rankings` array of all eligible brands' standings, and
    the year-over-year verdict for the client's own brand."

    Design: Corner/calculations/benchmarking_returns_yoy_delta_when_comparable
    """
    _, current, client = _two_cycle_ctx(current_change_class="FULL_COMPARABLE")
    data = validate_success(
        api.get_benchmarking(current["study"]["id"], make_client_user_headers(client["id"]))
    )
    assert data["yoy_comparable"] is True
    assert data["change_class"] == "FULL_COMPARABLE"
    assert data["yoy_delta"] == 60, f"860 - 800, got {data['yoy_delta']}"
    assert isinstance(data["rankings"], list) and len(data["rankings"]) == 1, (
        f"exactly one eligible brand in the current cycle, got {len(data['rankings'])}"
    )


def test_benchmarking_suppresses_yoy_on_methodology_break(api):
    """PRD §3.8: "the active methodology's `change_class` is not `BREAK` —
    `FULL_COMPARABLE` and `ADJUSTED` both permit the comparison while `BREAK`
    suppresses it — ... otherwise `yoy_comparable` is false and `yoy_delta` is
    null."

    Design: Corner/calculations/benchmarking_suppresses_yoy_on_methodology_break
    """
    _, current, client = _two_cycle_ctx(current_change_class="BREAK")
    data = validate_success(
        api.get_benchmarking(current["study"]["id"], make_client_user_headers(client["id"]))
    )
    assert data["yoy_comparable"] is False, "BREAK suppresses the comparison despite both final scores"
    assert data["yoy_delta"] is None
    assert data["change_class"] == "BREAK"
    assert isinstance(data["rankings"], list) and len(data["rankings"]) == 1, (
        "the break suppresses YoY only, not current-cycle benchmarking"
    )


def test_benchmarking_requires_benchmark_tier(api):
    """PRD §3.8: "The benchmarking read layers competitive context on top of the
    same gates, and additionally requires the subscription's `tier` to be
    `BENCHMARK` — a `DIAGNOSTIC`-tier subscriber is turned away with
    `ERR_TIER_INSUFFICIENT` (HTTP 403)."

    Design: Corner/errors/benchmarking_requires_benchmark_tier
    """
    ctx, client = _published_ctx_with_subscription(tier="DIAGNOSTIC")
    resp = api.get_benchmarking(ctx["study"]["id"], make_client_user_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_TIER_INSUFFICIENT)


def test_insights_require_active_subscription(api):
    """PRD §3.8: "then requires an `ACTIVE` subscription for the caller's
    `client_id` and that `study_id` whose window contains the logical clock
    (otherwise `ERR_SUBSCRIPTION_REQUIRED`, HTTP 403)"

    Design: Corner/errors/insights_require_active_subscription
    """
    ctx = setup_published_study(min_sample=1, brands=_ONE_BRAND)
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    # No subscription at all for (client, study).
    resp = api.get_diagnostics(ctx["study"]["id"], make_client_user_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_REQUIRED)


def test_insights_require_published_study(api):
    """PRD §3.8: "the gate first requires the study to be `PUBLISHED` (otherwise
    `ERR_RESULTS_NOT_PUBLISHED`, HTTP 403), then requires an `ACTIVE` subscription
    for the caller's `client_id` and that `study_id` whose window contains the
    logical clock (otherwise `ERR_SUBSCRIPTION_REQUIRED`, HTTP 403)"

    Design: Corner/errors/insights_require_published_study
    """
    ctx = setup_scored_study(min_sample=1, brands=_ONE_BRAND)  # SCORED, never published
    client = register_client(brand_id=ctx["brands"]["BrandA"]["id"])
    create_active_subscription(client["id"], ctx["study"]["id"], tier="DIAGNOSTIC")
    resp = api.get_diagnostics(ctx["study"]["id"], make_client_user_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_RESULTS_NOT_PUBLISHED)
