"""Premium rating and policy issuance tests."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_member,
    create_policy_for,
    create_published_guide,
    create_guide_tool_valuation,
    propose_and_approve,
    setup_active_policy,
    setup_approved_guide_valuation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_premium_tiered_multipliers_mode_a_core(api):
    """PRD §3.8: "It starts from `coverage_limit_cents` as the base and applies
    three tiers: the portion of the base up to 5,000,000 cents is charged at
    0.9 percent; the portion above that up to 15,000,000 cents at 0.7 percent;
    and any portion beyond 15,000,000 cents at 0.55 percent."
    PRD §3.8: "The tiered base is then multiplied by three factors — the usage
    multiplier (0.85 for `LIMITED`, 1.00 for `REGULAR`, 1.20 for `EXTENDED`),
    the storage multiplier (0.95 for `ENCLOSED_GARAGE`, 1.00 for `CARPORT`)".

    Design: Difficulty/combinatorial_formula/premium_tiered_multipliers_mode_a
    """
    member, m_headers = create_member(full_name="Cara", email="cara@x.com")
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=3_200_000, proposed=4_000_000,
        condition_grade="EXCELLENT",
    )
    resp = api.create_policy(
        {
            "member_id": member["id"],
            "vehicle_id": ctx["vehicle"]["id"],
            "valuation_id": ctx["valuation"]["id"],
            "usage_tier": "REGULAR",
            "period_start": "2026-09-01T00:00:00Z",
            "period_end": "2027-09-01T00:00:00Z",
        },
        UW,
    )
    policy = validate_success(resp, expected_status=201)
    # tier1 = round(4000000 * 0.009) = 36000; core = round(36000 * 1.00 * 0.95 * 1.00) = 34200
    assert policy["coverage_limit_cents"] == 4_000_000
    assert policy["premium_cents"] == 34_200, (
        f"Expected premium 34200, got {policy['premium_cents']}"
    )


def test_premium_tiered_multipliers_mode_a_endorsement_free(api):
    """PRD §3.8: "An endorsement fee of one percent of
    `endorsement_limit_cents`, rounded half-up, is added on top, and the sum
    is `premium_cents`."
    PRD §3.6: "computes its `coverage_limit_cents` as that agreed value plus
    any `endorsement_limit_cents` from an active restoration project (zero
    otherwise)".

    Design: Difficulty/combinatorial_formula/premium_tiered_multipliers_mode_a
    """
    member, m_headers = create_member(full_name="Cara2", email="cara2@x.com")
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=3_200_000, proposed=4_000_000,
        condition_grade="EXCELLENT",
    )
    policy = validate_success(
        api.create_policy(
            {
                "member_id": member["id"],
                "vehicle_id": ctx["vehicle"]["id"],
                "valuation_id": ctx["valuation"]["id"],
                "usage_tier": "REGULAR",
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2027-09-01T00:00:00Z",
            },
            UW,
        ),
        expected_status=201,
    )
    # No restoration project: endorsement is zero, so premium == core only.
    assert policy["endorsement_limit_cents"] == 0
    assert policy["premium_cents"] == 34_200


def test_premium_tier_boundary_straddle(api):
    """PRD §3.8: "It starts from `coverage_limit_cents` as the base and applies
    three tiers: the portion of the base up to 5,000,000 cents is charged at
    0.9 percent; the portion above that up to 15,000,000 cents at 0.7 percent;
    and any portion beyond 15,000,000 cents at 0.55 percent. Each tier's
    charge is rounded half-up to whole cents individually, and the three
    rounded tier charges are then summed into the tiered base."

    Design: Corner/calculations/premium_tier_boundary_straddle
    """
    member, m_headers = create_member(full_name="Cal", email="cal@x.com")
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=6_000_000, proposed=6_000_000,
        condition_grade="GOOD", storage_type="CARPORT",
    )
    policy = validate_success(
        api.create_policy(
            {
                "member_id": member["id"],
                "vehicle_id": ctx["vehicle"]["id"],
                "valuation_id": ctx["valuation"]["id"],
                "usage_tier": "REGULAR",
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2027-09-01T00:00:00Z",
            },
            UW,
        ),
        expected_status=201,
    )
    # tier1 = round(5000000 * 0.009) = 45000; tier2 = round(1000000 * 0.007) = 7000;
    # core = round(52000 * 1.00 * 1.00 * 1.00) = 52000
    assert policy["premium_cents"] == 52_000, (
        f"Straddling tiers 1 and 2 must yield 52000, got {policy['premium_cents']}"
    )


def test_policy_create_pins_valuation_fields(api):
    """PRD §3.6: "At issuance the policy copies `agreed_value_cents` from the
    pinned valuation's final agreed value, computes its `coverage_limit_cents`
    as that agreed value plus any `endorsement_limit_cents` from an active
    restoration project (zero otherwise), and computes `premium_cents` per the
    premium formula in §3.8."
    PRD §3.6: "If the vehicle's documentation is still incomplete, the policy
    lands in `PENDING_DOCUMENTS`; otherwise it lands in `QUOTED`."

    Design: Corner/endpoints/policy_create_pins_valuation_fields
    """
    member, m_headers = create_member(full_name="Pia", email="pia@x.com")
    # Documentation NOT completed -> policy must land in PENDING_DOCUMENTS.
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=3_000_000, proposed=3_000_000,
        document=False,
    )
    policy = validate_success(
        api.create_policy(
            {
                "member_id": member["id"],
                "vehicle_id": ctx["vehicle"]["id"],
                "valuation_id": ctx["valuation"]["id"],
                "usage_tier": "LIMITED",
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2027-09-01T00:00:00Z",
            },
            UW,
        ),
        expected_status=201,
    )
    assert policy["agreed_value_cents"] == 3_000_000
    assert policy["coverage_limit_cents"] == 3_000_000
    # tier1 = round(3000000 * 0.009) = 27000; core = round(27000 * 0.85 * 0.95 * 1.00)
    #       = round(21802.5) = 21803 (round half up)
    assert policy["premium_cents"] == 21_803, (
        f"LIMITED/ENCLOSED/no-club premium must be 21803, got {policy['premium_cents']}"
    )
    assert policy["status"] == "PENDING_DOCUMENTS"


def test_immediate_consistency_mutation_visible_in_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.6: "On success the vehicle transitions `REGISTERED` → `INSURED` — a
    vehicle already `INSURED` via a prior policy stays on its path — the
    premium is recomputed, and the policy's `version` increments."

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
    """
    member, m_headers = create_member(full_name="Yus", email="yus@x.com")
    ctx = setup_approved_guide_valuation(
        (member, m_headers), base_value_cents=3_000_000, proposed=3_000_000,
    )
    policy = validate_success(
        api.create_policy(
            {
                "member_id": member["id"],
                "vehicle_id": ctx["vehicle"]["id"],
                "valuation_id": ctx["valuation"]["id"],
                "usage_tier": "REGULAR",
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2027-09-01T00:00:00Z",
            },
            UW,
        ),
        expected_status=201,
    )
    created_version = policy["version"]
    from test_helpers import add_listed_driver
    add_listed_driver(policy["id"], m_headers)
    resp = api.activate_policy(policy["id"], UW)
    activated = validate_success(resp)
    assert activated["status"] == "ACTIVE"
    # tier1 = round(3000000 * 0.009) = 27000; core = round(27000 * 1.00 * 0.95 * 1.00) = 25650
    assert activated["premium_cents"] == 25_650, (
        f"Activation must recompute the premium in the response, got "
        f"{activated['premium_cents']}"
    )
    assert activated["version"] > created_version
