"""Heat claims: the DELIVERED gate, the repeatable MORE_INFO review cycle,
settlement branch precision, the aggregate claimed-units cap, the
auto-approve rejection ban, and filing-side role segregation.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_DELIVER_TIME,
    HeatClaimStatus,
    ShipmentStatus,
    TEST_USERS,
    api_client,
    compute_heat_claim_credit,
    create_heat_claim_payload,
    create_planned_shipment,
    decide_claim,
    deliver_shipment,
    get_heat_claim,
    get_retailer_account,
    get_shipment,
    make_retailer_headers,
    provide_claim_info,
    setup_allocated_program,
    setup_delivered_shipment,
    setup_heat_claim_under_review,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# The non-linear review cycle: UNDER_REVIEW -> MORE_INFO -> UNDER_REVIEW
# ---------------------------------------------------------------------------

def test_heat_claim_more_info_cycle_is_repeatable(api):
    """PRD §3.8: "`REQUEST_MORE_INFO` moves the claim to `MORE_INFO`, from
    which the owning retailer supplies fresh evidence through a provide-info
    step carrying a new `evidence_note`; that step replaces the claim's
    `evidence_note`, returns the claim to `UNDER_REVIEW`, and is repeatable —
    the review cycle `UNDER_REVIEW` to `MORE_INFO` and back may run as many
    times as needed."

    Design: Difficulty/non_linear_state_machine/heat_claim_more_info_review_cycle
    """
    world = setup_heat_claim_under_review(
        claimed_units=4, commitment_units=10, ship_units=10, temp_controlled=True,
    )
    claim = world["claim"]
    retailer = world["retailer"]
    assert claim["status"] == HeatClaimStatus.UNDER_REVIEW.value
    assert claim["version"] == 1  # born FILED, auto-advanced in the same request

    first = decide_claim(claim["id"], "REQUEST_MORE_INFO")
    assert first["status"] == HeatClaimStatus.MORE_INFO.value

    back = provide_claim_info(claim["id"], retailer, "added carrier temperature log")
    assert back["status"] == HeatClaimStatus.UNDER_REVIEW.value
    assert back["evidence_note"] == "added carrier temperature log"

    # The cycle is not one-shot: a second loop also succeeds.
    second = decide_claim(claim["id"], "REQUEST_MORE_INFO")
    assert second["status"] == HeatClaimStatus.MORE_INFO.value
    back2 = provide_claim_info(claim["id"], retailer, "second packet: warehouse receipt photos")
    assert back2["status"] == HeatClaimStatus.UNDER_REVIEW.value


def test_heat_claim_cycle_then_approve_settles_temp_controlled_branch(api):
    """PRD §3.8: "if the shipment was `temp_controlled`, the payout is 100%
    (a fraction of 1.00) — the house carried the cold chain and owns the
    failure" and "Every decide and provide-info increments the claim's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/heat_claim_more_info_review_cycle
    """
    world = setup_heat_claim_under_review(
        claimed_units=4, commitment_units=10, ship_units=10, temp_controlled=True,
    )
    claim = world["claim"]
    retailer = world["retailer"]
    assert claim["auto_approve"] is False

    decide_claim(claim["id"], "REQUEST_MORE_INFO")
    provide_claim_info(claim["id"], retailer, "added carrier temperature log")
    decide_claim(claim["id"], "REQUEST_MORE_INFO")
    provide_claim_info(claim["id"], retailer, "second packet: warehouse receipt photos")

    approved = decide_claim(claim["id"], "APPROVE")
    assert approved["status"] == HeatClaimStatus.APPROVED.value
    # 4 x 499 x 1.00 = 1996 on the temp_controlled branch.
    assert approved["credit_cents"] == 1996
    assert approved["credit_cents"] == compute_heat_claim_credit(4, 499, 1.00)
    # v1 at create, +2 per cycle hop pair (4 hops), +1 for the approval.
    assert approved["version"] == 6
    assert get_retailer_account(retailer["id"])["credit_balance_cents"] == 1996


# ---------------------------------------------------------------------------
# Cross-entity gate: claims only against DELIVERED shipments
# ---------------------------------------------------------------------------

def test_heat_claim_on_planned_shipment_rejected(api):
    """PRD §3.8: "A `Retailer` files a `HeatClaim` against a shipment that has
    been `DELIVERED` — filing against a shipment in any other status is
    rejected with `ERR_INVALID_STATE`".

    Design: Difficulty/cross_entity_state_dependency/heat_claim_requires_shipment_delivered
    """
    world = setup_allocated_program(
        commitment_specs=[{"tier": "GOLD", "units": 10, "use_default_retailer": True}],
        produced_units=10,
    )
    shipment = create_planned_shipment(world["commitment"], world["warehouse"], units=5)
    assert shipment["status"] == ShipmentStatus.PLANNED.value

    resp = api_client.create_heat_claim(
        create_heat_claim_payload(
            shipment_id=shipment["id"], claimed_units=2, reason="BLOOM",
            evidence_note="whitened surface on arrival",
        ),
        make_retailer_headers(world["retailer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_heat_claim_after_deliver_lands_under_review(api):
    """PRD §3.8: "A claim is born `FILED` and immediately advanced to
    `UNDER_REVIEW` by the system within the same request, so the persisted
    claim reads `UNDER_REVIEW` at `version` 1." PRD §3.6: "a `PLANNED`
    shipment becomes `DELIVERED`, `delivered_on` is set from the logical
    clock".

    Design: Difficulty/cross_entity_state_dependency/heat_claim_requires_shipment_delivered
    """
    world = setup_allocated_program(
        commitment_specs=[{"tier": "GOLD", "units": 10, "use_default_retailer": True}],
        produced_units=10,
    )
    shipment = create_planned_shipment(world["commitment"], world["warehouse"], units=5)
    delivered = deliver_shipment(shipment)
    assert delivered["status"] == ShipmentStatus.DELIVERED.value
    assert delivered["delivered_on"] == CLOCK_DELIVER_TIME

    resp = api_client.create_heat_claim(
        create_heat_claim_payload(
            shipment_id=shipment["id"], claimed_units=2, reason="BLOOM",
            evidence_note="whitened surface on arrival",
        ),
        make_retailer_headers(world["retailer"]["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == HeatClaimStatus.UNDER_REVIEW.value
    assert data["version"] == 1


# ---------------------------------------------------------------------------
# Settlement branches and claim guards
# ---------------------------------------------------------------------------

def test_heat_claim_declined_temp_control_settles_at_half_credit(api):
    """PRD §3.8: "otherwise, if the retailer explicitly declined temp control
    (`temp_control_declined_by_retailer`), the payout is 50% (0.50) — the risk
    was shared" and "rounded half-up to whole cents" (PRD §2.6: "round
    half-up means a fraction of exactly one half rounds away from zero").

    Design: Corner/calculations/heat_claim_declined_temp_control_settles_at_half_credit
    """
    world = setup_heat_claim_under_review(
        claimed_units=7, commitment_units=10, ship_units=7,
        temp_controlled=False, temp_control_declined=True,
    )
    claim = world["claim"]
    # Declined by the retailer: the auto-approve branch does not apply.
    assert claim["auto_approve"] is False

    approved = decide_claim(claim["id"], "APPROVE")
    assert approved["status"] == HeatClaimStatus.APPROVED.value
    # 7 x 499 x 0.50 = 1746.5 -> 1747 round half-up (not 1746, not 3493).
    assert approved["credit_cents"] == 1747
    assert approved["credit_cents"] == compute_heat_claim_credit(7, 499, 0.50)
    assert get_retailer_account(world["retailer"]["id"])["credit_balance_cents"] == 1747


def test_claim_units_capped_by_shipment_in_aggregate(api):
    """PRD §3.8: "The `claimed_units` must be at least 1, and the sum of
    `claimed_units` over all of the shipment's claims that are not `REJECTED`
    must not exceed the shipment's `units`, or the filing is rejected with
    `ERR_CLAIM_EXCEEDS_SHIPMENT` (HTTP 422)."

    Design: Corner/validations/claim_units_capped_by_shipment_in_aggregate
    """
    world = setup_delivered_shipment(
        commitment_units=10, ship_units=5, temp_controlled=True,
    )
    shipment = world["shipment"]
    headers = make_retailer_headers(world["retailer"]["id"])

    over = api_client.create_heat_claim(
        create_heat_claim_payload(shipment_id=shipment["id"], claimed_units=6),
        headers,
    )
    validate_error(over, ApiErrorId.ERR_CLAIM_EXCEEDS_SHIPMENT)

    exact = api_client.create_heat_claim(
        create_heat_claim_payload(
            shipment_id=shipment["id"], claimed_units=5,
            evidence_note="full-shipment claim",
        ),
        headers,
    )
    exact_data = validate_success(exact, 201)  # 5 == shipment.units passes
    assert exact_data["status"] == HeatClaimStatus.UNDER_REVIEW.value

    aggregate = api_client.create_heat_claim(
        create_heat_claim_payload(
            shipment_id=shipment["id"], claimed_units=1, reason="BLOOM",
            evidence_note="one more unit found",
        ),
        headers,
    )
    # 5 + 1 > 5 in aggregate: a per-claim check would miss this one.
    validate_error(aggregate, ApiErrorId.ERR_CLAIM_EXCEEDS_SHIPMENT)

    rows, _meta = validate_paginated(api_client.list_heat_claims(
        ADMIN, params={"shipment_id": shipment["id"]},
    ))
    assert len(rows) == 1


def test_auto_approve_claim_cannot_be_rejected(api):
    """PRD §3.8: "a claim whose `auto_approve` condition holds may not be
    rejected at all, and the attempt is refused with
    `ERR_CLAIM_AUTO_APPROVED` (HTTP 422), because a summer shipment of
    heat-sensitive product sent without refrigeration was a known house
    risk." Auto-approve holds when "the product is heat-sensitive
    (`requires_temp_control`), the shipment was not `temp_controlled`, the
    retailer did not decline temp control, and the shipment's `ship_on` falls
    in a summer month — June, July, or August (months 6, 7, and 8)."

    Design: Corner/validations/auto_approve_claim_cannot_be_rejected
    """
    world = setup_heat_claim_under_review(
        claimed_units=7, commitment_units=10, ship_units=7,
        temp_controlled=False, temp_control_declined=False,
    )
    claim = world["claim"]
    # ship_on 2027-08-02 is month 8 (summer); temp-required product; not
    # temp-controlled; not declined.
    assert claim["auto_approve"] is True

    rejected = api_client.decide_heat_claim(
        claim["id"], {"decision": "REJECT"}, ADJUSTER,
    )
    validate_error(rejected, ApiErrorId.ERR_CLAIM_AUTO_APPROVED)
    assert get_heat_claim(claim["id"])["status"] == HeatClaimStatus.UNDER_REVIEW.value

    # The only way out of UNDER_REVIEW here is APPROVE at the 1.00 branch.
    approved = decide_claim(claim["id"], "APPROVE")
    assert approved["status"] == HeatClaimStatus.APPROVED.value
    assert approved["credit_cents"] == 3493  # 7 x 499 x 1.00
    assert get_retailer_account(world["retailer"]["id"])["credit_balance_cents"] == 3493


def test_claims_adjuster_cannot_file_heat_claim_returns_unauthorized(api):
    """PRD §2.1: "`ClaimsAdjuster` — decides heat claims and never files
    them, keeping claim adjudication segregated from claim filing." PRD §2.8:
    "2. **Authorization** — the declared role is listed among the endpoint's
    authorized roles (`ERR_UNAUTHORIZED`)" runs before "3. **Path
    existence**".

    Design: Corner/rbac/claims_adjuster_cannot_file_heat_claim_returns_unauthorized
    """
    resp = api_client.create_heat_claim(
        create_heat_claim_payload(
            shipment_id="00000000-0000-4000-8000-000000000000",
            claimed_units=1, evidence_note="adjuster trying to file",
        ),
        ADJUSTER,
    )
    # Role denial (priority 2) precedes the not-found check (priority 3).
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
