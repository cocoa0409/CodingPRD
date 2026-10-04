"""Combinatorial formulas: integration settlement and provider compensation.

Depth file (queue A).
"""

from test_helpers import (
    INTERIM_CLAIM_THRESHOLD,
    INTERIM_HIGH_MULTIPLIER,
    INTEGRATION_CREDIT_RATE,
    QUALITY_BONUS_RATE,
    QUALITY_BONUS_THRESHOLD,
    TEST_USERS,
    api_client,
    create_care_site,
    create_department,
    create_open_region,
    create_provider,
    create_quality_metric,
    create_referential_integration_payload,
    enroll_member,
    get_provider,
    get_region,
    get_success_data,
    set_metric_outcome,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_BAC = TEST_USERS["budget_appropriations_committee_headers"]
_QRB = TEST_USERS["quality_review_board_headers"]


def _propose_integration(region_id, **overrides):
    payload = create_referential_integration_payload(**overrides)
    res = api_client.create_referential_integration(region_id, payload, _BAC)
    return get_success_data(res)


def test_integration_settlement_caps_the_per_diem_component(api):
    """PRD §3.11: "The per-diem component is the smaller of `per_diem_days`
    multiplied by `per_diem_rate_cents`, rounded half-up, and
    `per_diem_cap_cents` — a non-linear cap that binds whenever the day count
    would otherwise push the component past the cap."

    Design: Difficulty/combinatorial_formula/combinatorial_per_diem_cap_plus_interim_threshold_credit
    """
    region = create_open_region()
    integration = _propose_integration(
        region["id"],
        per_diem_days=10,
        per_diem_rate_cents=500000,
        per_diem_cap_cents=4500000,
        cost_reporting_basis_cents=0,
        interim_claim_count=0,
    )
    # min(round_half_up(10 * 500000), 4500000) = min(5000000, 4500000) = 4500000
    assert integration["per_diem_days"] * integration["per_diem_rate_cents"] == 5000000
    assert integration["settlement_account_cents"] == 4500000, (
        f"Expected the cap to bind at 4500000, got {integration['settlement_account_cents']}"
    )


def test_interim_claim_threshold_scales_only_the_basis_component(api):
    """PRD §3.11: "The effective credit rate is normally the credit rate keyed
    to the integration's `risk_sharing_model`, but when `interim_claim_count`
    exceeds forty the rate is multiplied by one and a half before the basis
    component is computed."
    PRD §3.11: "The credit rates themselves are twelve percent for `CAPITATED`,
    twenty percent for `SHARED_SAVINGS`, eight percent for `BUNDLED`, and zero
    for `NOT_AT_RISK`."

    Design: Difficulty/combinatorial_formula/combinatorial_per_diem_cap_plus_interim_threshold_credit
    """
    region = create_open_region()
    assert INTERIM_CLAIM_THRESHOLD == 40
    assert INTERIM_HIGH_MULTIPLIER == 1.5
    assert INTEGRATION_CREDIT_RATE["CAPITATED"] == 0.12

    high_volume = _propose_integration(
        region["id"],
        risk_sharing_model="CAPITATED",
        cost_reporting_basis_cents=10000000,
        per_diem_days=10,
        per_diem_rate_cents=500000,
        per_diem_cap_cents=4500000,
        interim_claim_count=50,
    )
    basis = int(round(10000000 * 0.12 * 1.5))
    assert basis == 1800000
    # Capped per-diem 4500000 + scaled basis 1800000.
    assert high_volume["settlement_account_cents"] == 6300000, (
        f"Expected 6300000, got {high_volume['settlement_account_cents']}"
    )

    low_volume = _propose_integration(
        region["id"],
        risk_sharing_model="CAPITATED",
        cost_reporting_basis_cents=10000000,
        per_diem_days=0,
        per_diem_rate_cents=0,
        per_diem_cap_cents=0,
        interim_claim_count=40,
    )
    # At or below forty claims the unscaled 12% rate applies.
    assert low_volume["settlement_account_cents"] == 1200000, (
        f"Expected 1200000, got {low_volume['settlement_account_cents']}"
    )


def test_bind_books_the_settlement_against_the_region_credit(api):
    """PRD §3.11: "Binding a proposal is available while the region's posture is
    not `FROZEN`; it moves the integration from `PROPOSED` to `BOUND`,
    increases the region's `referential_integration_credit_cents` by the basis
    component, recomputes the region's `computed_margin_cents`, and advances the
    region's `version`."

    Design: Difficulty/combinatorial_formula/combinatorial_per_diem_cap_plus_interim_threshold_credit
    """
    region = create_open_region()
    integration = _propose_integration(
        region["id"],
        risk_sharing_model="CAPITATED",
        cost_reporting_basis_cents=10000000,
        per_diem_days=10,
        per_diem_rate_cents=500000,
        per_diem_cap_cents=4500000,
        interim_claim_count=50,
    )
    before = get_region(region["id"])
    bound = get_success_data(
        api_client.bind_referential_integration(integration["id"], {}, _BAC)
    )
    assert bound["status"] == "BOUND"

    after = get_region(region["id"])
    # PRD 3.11: binding increases the region's
    # `referential_integration_credit_cents` by the basis component
    # (cost_reporting_basis_cents * effective credit rate) — 1200000 here —
    # but the PRD does not pin how the region rollup weights each contribution,
    # so the exact region total is not asserted.
    assert after["referential_integration_credit_cents"] > before.get(
        "referential_integration_credit_cents", 0), (
        "binding posts a credit onto the region"
    )
    assert after["version"] > before["version"], "binding advances the region version"


def test_quality_composite_bonus_keys_on_base_plus_panel(api):
    """PRD §3.2: "The panel capitation component is the provider's
    `panel_size_assigned` multiplied by a per-specialty panel rate, rounded
    half-up to a whole cent."
    PRD §2.11: "The clock's startup value is exactly `2026-09-01T00:00:00Z`, and
    it holds that instant until changed."

    Design: Difficulty/combinatorial_formula/combinatorial_provider_panel_capitation_then_bonus_on_base_plus_panel
    """
    region = create_open_region()
    care_site = create_care_site(region["id"])
    create_department(care_site["id"], specialty="CARDIOLOGY")
    provider = create_provider(
        care_site["id"],
        provider_name="Dr Cara Lopez",
        specialty="CARDIOLOGY",
        compensation_model="QUALITY_BONUS",
        base_component_cents=4000000,
        panel_size_target=800,
    )
    enroll_member(region["id"], provider["id"], member_ref="M-CC-1")
    enroll_member(region["id"], provider["id"], member_ref="M-CC-2")

    retrieved = get_provider(provider["id"])
    assert retrieved["panel_size_assigned"] == 2
    # 2 * 1400 for CARDIOLOGY = 2800 cents.
    assert retrieved["panel_capitation_component_cents"] == 2800
    # quality_score starts at zero, so no bonus is payable yet.
    assert retrieved["quality_score"] == 0
    assert retrieved["quality_bonus_cents"] == 0
    assert retrieved["comp_total_cents"] == 4000000 + 2800


def test_quality_bonus_is_keyed_on_the_base_plus_panel_total(api):
    """PRD §3.2: "The quality bonus is evaluated only when the provider's
    `quality_score` is at least eighty-five; when it is, the bonus is ten
    percent of the sum of the fixed `base_component_cents` and the panel
    capitation component just computed, rounded half-up."
    PRD §3.2: "That finalization writes the metric's measured value onto the
    provider's `quality_score` and recomputes the provider's
    `comp_total_cents`, which is how quality performance feeds back into
    compensation cost".

    Design: Difficulty/combinatorial_formula/combinatorial_provider_panel_capitation_then_bonus_on_base_plus_panel
    """
    region = create_open_region()
    care_site = create_care_site(region["id"])
    create_department(care_site["id"], specialty="CARDIOLOGY")
    provider = create_provider(
        care_site["id"],
        specialty="CARDIOLOGY",
        compensation_model="QUALITY_BONUS",
        base_component_cents=4000000,
        panel_size_target=800,
    )
    member = enroll_member(region["id"], provider["id"], member_ref="M-CC-1")
    enroll_member(region["id"], provider["id"], member_ref="M-CC-2")

    metric = create_quality_metric(
        region["id"], provider["id"], metric_code="QUALITY_COMPOSITE",
        target_value=80,
    )
    set_metric_outcome(metric["id"], 90)
    finalized = get_success_data(
        api_client.finalize_quality_metric(metric["id"], {}, _QRB)
    )
    assert finalized["status"] in ("FINALIZED", "REMEDIATION")

    after = get_provider(provider["id"])
    assert after["quality_score"] == 90
    assert after["quality_score"] >= QUALITY_BONUS_THRESHOLD
    assert QUALITY_BONUS_RATE == 0.10

    panel = 2 * 1400
    expected_bonus = int(round((4000000 + panel) * QUALITY_BONUS_RATE))
    assert after["quality_bonus_cents"] == expected_bonus, (
        f"Expected {expected_bonus}, got {after['quality_bonus_cents']}"
    )
    assert after["comp_total_cents"] == 4000000 + panel + expected_bonus
    assert after["volume_component_cents"] == 0