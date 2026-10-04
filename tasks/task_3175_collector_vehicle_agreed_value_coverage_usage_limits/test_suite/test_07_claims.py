"""Claims: dual-variant payouts, reopen cycle, total-loss cascade, gating."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_certified_shop,
    create_claim_payload,
    create_guide_tool_valuation,
    create_member,
    create_published_guide,
    create_policy_for,
    add_listed_driver,
    get_policy,
    get_vehicle,
    make_adjuster_headers,
    make_member_headers,
    propose_and_approve,
    setup_active_policy,
    setup_approved_guide_valuation,
    setup_claim_under_investigation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
ADJ1 = TEST_USERS["adjuster_headers"]
ADJ2 = TEST_USERS["adjuster2_headers"]
ADJ3 = TEST_USERS["adjuster3_headers"]


def test_claim_payout_repair_variant(api):
    """PRD §3.9: "Under the repair variant the `payout_cents` is the estimate
    capped at the coverage limit: the smaller of `estimate_cents` and
    `coverage_limit_cents`."

    Design: Difficulty/dual_variant_calc/claim_payout_repair_vs_total_loss_divergence
    """
    ctx = setup_claim_under_investigation(estimate_cents=120_000)
    claim = ctx["claim"]
    validate_success(api.authorize_repair(claim["id"], ADJ1))
    settled = validate_success(api.settle_claim(claim["id"], ADJ1))
    # min(120000, coverage 3000000) == 120000
    assert settled["payout_cents"] == 120_000, (
        f"Repair payout must be min(estimate, coverage) == 120000, got "
        f"{settled['payout_cents']}"
    )
    assert settled["status"] == "PAID"


def test_claim_payout_total_loss_variant_diverges(api):
    """PRD §3.9: "Under the total-loss variant the payout is the policy's
    full `agreed_value_cents` — no deductible, no depreciation — less the
    salvage value when the owner retains the salvage, satisfying the
    invariant that payout plus retained salvage equals the agreed value
    exactly."
    PRD §3.9: "the two variants produce different payouts for identical claim
    input data."

    Design: Difficulty/dual_variant_calc/claim_payout_repair_vs_total_loss_divergence
    """
    ctx = setup_claim_under_investigation(estimate_cents=120_000)
    claim = ctx["claim"]
    # Repair-settle, then reopen, then take the total-loss branch.
    validate_success(api.authorize_repair(claim["id"], ADJ1))
    repair_settled = validate_success(api.settle_claim(claim["id"], ADJ1))
    assert repair_settled["payout_cents"] == 120_000
    validate_success(api.reopen_claim(claim["id"], ctx["member_headers"]))
    validate_success(
        api.declare_total_loss(claim["id"], {"salvage_retained": False}, ADJ2)
    )
    total_settled = validate_success(api.settle_claim(claim["id"], ADJ3))
    assert total_settled["payout_cents"] == 3_000_000, (
        f"Total loss pays the full agreed value 3000000, got "
        f"{total_settled['payout_cents']}"
    )
    assert total_settled["payout_cents"] != repair_settled["payout_cents"]


def test_claim_reopen_cycle_loop(api):
    """PRD §3.9: "A repair settlement, by contrast, is not final — the member
    may reopen a paid repair claim when supplemental damage surfaces, which
    requires the claim's variant to be `REPAIR` (reopening a total loss is
    rejected with `ERR_INVALID_STATE`) and the policy to be `ACTIVE`;
    reopening returns the claim to `UNDER_INVESTIGATION`, resets the variant
    to `NONE`, clears the payout, and allows a fresh estimate."

    Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_loop
    """
    ctx = setup_claim_under_investigation(estimate_cents=120_000)
    claim = ctx["claim"]
    validate_success(api.authorize_repair(claim["id"], ADJ1))
    validate_success(api.settle_claim(claim["id"], ADJ1))
    reopened = validate_success(api.reopen_claim(claim["id"], ctx["member_headers"]))
    assert reopened["status"] == "UNDER_INVESTIGATION", (
        "Reopen cycles PAID -> UNDER_INVESTIGATION"
    )
    assert reopened["settlement_variant"] == "NONE"


def test_claim_reopen_cycle_resettles_with_new_estimate(api):
    """PRD §3.9: "reopening returns the claim to `UNDER_INVESTIGATION`,
    resets the variant to `NONE`, clears the payout, and allows a fresh
    estimate."
    PRD §3.9: "Under the repair variant the `payout_cents` is the estimate
    capped at the coverage limit: the smaller of `estimate_cents` and
    `coverage_limit_cents`."

    Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_loop
    """
    ctx = setup_claim_under_investigation(estimate_cents=120_000)
    claim = ctx["claim"]
    validate_success(api.authorize_repair(claim["id"], ADJ1))
    validate_success(api.settle_claim(claim["id"], ADJ1))
    validate_success(api.reopen_claim(claim["id"], ctx["member_headers"]))
    validate_success(api.submit_estimate(claim["id"], {"estimate_cents": 150_000}, ADJ1))
    validate_success(api.authorize_repair(claim["id"], ADJ1))
    settled2 = validate_success(api.settle_claim(claim["id"], ADJ1))
    assert settled2["payout_cents"] == 150_000, (
        f"Second settlement after reopen must pay the new estimate 150000, "
        f"got {settled2['payout_cents']}"
    )


def test_total_loss_settle_cascade_depth2(api):
    """PRD §3.9: "A total-loss settlement cascades: the policy moves to
    `CANCELLED` and the vehicle moves `INSURED` → `RETIRED`."

    Design: Difficulty/transitive_cascade/total_loss_settle_cascade_depth2
    """
    ctx = setup_claim_under_investigation(loss_type="THEFT")
    claim = ctx["claim"]
    validate_success(
        api.declare_total_loss(claim["id"], {"salvage_retained": False}, ADJ1)
    )
    settled = validate_success(api.settle_claim(claim["id"], ADJ2))
    assert settled["status"] == "PAID"
    assert settled["payout_cents"] == 3_000_000
    policy = get_policy(ctx["policy"]["id"])
    assert policy["status"] == "CANCELLED", (
        f"Total-loss settlement must cancel the policy, got {policy['status']}"
    )
    vehicle = get_vehicle(ctx["vehicle"]["id"])
    assert vehicle["status"] == "RETIRED", (
        f"Total-loss settlement must retire the vehicle, got {vehicle['status']}"
    )


def test_total_loss_settle_payout_no_salvage(api):
    """PRD §3.9: "Under the total-loss variant the payout is the policy's
    full `agreed_value_cents` — no deductible, no depreciation — less the
    salvage value when the owner retains the salvage, satisfying the
    invariant that payout plus retained salvage equals the agreed value
    exactly."

    Design: Difficulty/transitive_cascade/total_loss_settle_cascade_depth2
    """
    ctx = setup_claim_under_investigation(loss_type="THEFT")
    claim = ctx["claim"]
    validate_success(
        api.declare_total_loss(claim["id"], {"salvage_retained": False}, ADJ1)
    )
    settled = validate_success(api.settle_claim(claim["id"], ADJ2))
    # agreed 3000000, no salvage retained -> payout == agreed value
    assert settled["payout_cents"] == ctx["policy"]["agreed_value_cents"] == 3_000_000


def test_total_loss_gated_on_valuation_staleness(api):
    """PRD §3.9: "The total-loss path requires the policy's pinned valuation
    to be approved and not stale (`ERR_VALUATION_STALE`)".
    PRD §3.4: "Publication triggers a three-level cascade. The prior guide in
    `PUBLISHED` becomes `SUPERSEDED`. Every valuation created by the
    guide-tool method that was pinned to that superseded guide and still in
    `APPROVED` status becomes `STALE`."

    Design: Difficulty/cross_entity_state_dependency/total_loss_gated_on_valuation_staleness
    """
    ctx = setup_claim_under_investigation(loss_type="FIRE")
    claim = ctx["claim"]
    # Publish a second guide: supersedes the first, staling the pinned
    # GUIDE_TOOL valuation.
    create_published_guide(base_value_cents=3_100_000)
    resp = api.declare_total_loss(claim["id"], {"salvage_retained": False}, ADJ1)
    validate_error(resp, ApiErrorId.ERR_VALUATION_STALE)


def test_total_loss_gated_on_valuation_staleness_after_clock_advance(api):
    """PRD §3.5: "It becomes `STALE` — its `is_stale` flag true — when its
    pinned guide is superseded or when its `approved_at` lies more than 365
    days before the logical clock."
    PRD §3.9: "The total-loss path requires the policy's pinned valuation to
    be approved and not stale (`ERR_VALUATION_STALE`)."

    Design: Difficulty/cross_entity_state_dependency/total_loss_gated_on_valuation_staleness
    """
    ctx = setup_claim_under_investigation(loss_type="FIRE")
    claim = ctx["claim"]
    # Advance the logical clock beyond approved_at + 365 days.
    validate_success(
        api.set_clock({"to_iso8601": "2027-10-01T00:00:00Z"}, ADMIN)
    )
    resp = api.declare_total_loss(claim["id"], {"salvage_retained": False}, ADJ1)
    validate_error(resp, ApiErrorId.ERR_VALUATION_STALE)


def test_claim_reopen_after_total_loss_rejected(api):
    """PRD §3.9: "reopening a total loss is rejected with
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/claim_reopen_after_total_loss_rejected
    """
    ctx = setup_claim_under_investigation(loss_type="THEFT")
    claim = ctx["claim"]
    validate_success(
        api.declare_total_loss(claim["id"], {"salvage_retained": False}, ADJ1)
    )
    validate_success(api.settle_claim(claim["id"], ADJ2))
    resp = api.reopen_claim(claim["id"], ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_error_referenced_not_found_on_assign_shop(api):
    """PRD §3.9: "From there a `ClaimsAdjuster` assigns a specialty repair
    shop by reference — a dangling `repair_shop_id` is rejected with
    `ERR_REFERENCED_NOT_FOUND`".

    Design: Corner/errors/error_referenced_not_found_on_assign_shop
    """
    ctx = setup_active_policy()
    claim = validate_success(
        api.open_claim(
            ctx["policy"]["id"], create_claim_payload(), ctx["member_headers"]
        ),
        expected_status=201,
    )
    resp = api.assign_shop(claim["id"], {"repair_shop_id": NON_EXISTENT_UUID}, ADJ1)
    validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND)


def test_claim_incident_out_of_period_rejected(api):
    """PRD §3.9: "The member opens a claim on an active policy by supplying
    the `incident_date` — which must fall inside the coverage window, failing
    which the report is rejected with `ERR_INCIDENT_OUT_OF_PERIOD`".

    Design: Corner/validations/claim_incident_out_of_period_rejected
    """
    ctx = setup_active_policy()
    resp = api.open_claim(
        ctx["policy"]["id"],
        create_claim_payload(incident_date="2026-06-01T00:00:00Z"),
        ctx["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INCIDENT_OUT_OF_PERIOD)
