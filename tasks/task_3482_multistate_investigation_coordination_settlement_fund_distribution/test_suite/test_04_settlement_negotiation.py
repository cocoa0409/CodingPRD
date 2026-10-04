"""Settlement negotiation: the counter-revise cycle, its investigation phase
bounce, the round cap, optimistic concurrency on the settlement version, and
provisional recomputation on revise.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    advance_investigation,
    advance_payload,
    agree_terms,
    counter_settlement,
    counter_settlement_payload,
    get_investigation,
    get_settlement,
    revise_settlement,
    setup_proposed_world,
    validate_error,
    TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
COUNSEL = TEST_USERS["defendant_counsel_headers"]


def test_settlement_counter_cycle_returns_to_proposed():
    """PRD section 3.3: "A successful counter moves `PROPOSED` → `COUNTERED`,
    increments `negotiation_round` by 1, records the supplied
    `counter_total_cents` when one is provided alongside the optional
    free-text `note`, increments the settlement's `version` by 1."
    PRD section 3.3: "A successful revise moves `COUNTERED` → `PROPOSED`,
    increments `version` by 1, and automatically returns the investigation
    from `DISCOVERY` to `NEGOTIATION`."

    Design: Difficulty/non_linear_state_machine/settlement_counter_cycle_returns_to_proposed
    """
    world = setup_proposed_world()
    settlement = world["settlement"]
    v0 = settlement["version"]
    countered = counter_settlement(settlement, counter_total_cents=90000000)
    assert countered["term_status"] == "COUNTERED"
    assert countered["negotiation_round"] == 1
    assert countered["counter_total_cents"] == 90000000
    assert countered["version"] == v0 + 1
    revised = revise_settlement(countered, world["offices"]["CA"])
    assert revised["term_status"] == "PROPOSED", "the cycle returns to PROPOSED"
    assert revised["negotiation_round"] == 1, "revise does not consume a round"
    assert revised["version"] == v0 + 2


def test_investigation_negotiation_discovery_bounce():
    """PRD section 3.3: "because a counter reopens factual disputes —
    automatically bounces an investigation sitting in `NEGOTIATION` back to
    `DISCOVERY`."
    PRD section 3.3: "A successful revise ... automatically returns the
    investigation from `DISCOVERY` to `NEGOTIATION` — this automatic return
    deliberately skips the accepted-response gate, since the bounce originated
    from this settlement's own counter rather than from a loss of discovery
    coverage."

    Design: Difficulty/non_linear_state_machine/investigation_negotiation_discovery_bounce
    """
    world = setup_proposed_world()
    inv_id = world["investigation"]["id"]
    assert world["investigation"]["phase"] == "NEGOTIATION"
    countered = counter_settlement(world["settlement"], counter_total_cents=90000000)
    assert get_investigation(inv_id)["phase"] == "DISCOVERY", (
        "the counter bounces the investigation back to DISCOVERY"
    )
    revise_settlement(countered, world["offices"]["CA"])
    assert get_investigation(inv_id)["phase"] == "NEGOTIATION", (
        "the revise returns the investigation to NEGOTIATION automatically"
    )


def test_counter_round_cap_exhausted_returns_negotiation_exhausted():
    """PRD section 3.3: "is bounded by the negotiation cap: the counter is
    rejected with `ERR_NEGOTIATION_EXHAUSTED` (HTTP 422) when applying it
    would push `negotiation_round` beyond 4 — rounds 1 through 4 are allowed,
    a fifth is not."

    Design: Corner/state_machines/counter_round_cap_exhausted_returns_negotiation_exhausted
    """
    world = setup_proposed_world()
    settlement = world["settlement"]
    lead_office = world["offices"]["CA"]
    for _ in range(4):
        settlement = counter_settlement(settlement)
        settlement = revise_settlement(settlement, lead_office)
    fresh = get_settlement(settlement["id"])
    assert fresh["negotiation_round"] == 4
    resp = api_client.counter_settlement(
        fresh["id"], counter_settlement_payload(fresh["version"]), COUNSEL,
    )
    validate_error(resp, ApiErrorId.ERR_NEGOTIATION_EXHAUSTED)
    after = get_settlement(fresh["id"])
    assert after["term_status"] == "PROPOSED"
    assert after["negotiation_round"] == 4


def test_settlement_counter_stale_version_returns_412():
    """PRD section 2.5: "Countering a settlement and revising a settlement
    each require the request body to carry `expected_settlement_version`,
    holding the caller's last observed `version` of the target settlement; if
    the settlement's current `version` has advanced past that value — because
    a counter or revise has already landed since the caller last read it — the
    write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/settlement_counter_stale_version_returns_412
    """
    world = setup_proposed_world()
    settlement = world["settlement"]
    v0 = settlement["version"]
    countered = counter_settlement(settlement, counter_total_cents=90000000)
    revise_settlement(countered, world["offices"]["CA"])
    resp = api_client.counter_settlement(
        settlement["id"], counter_settlement_payload(v0), COUNSEL,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = get_settlement(settlement["id"])
    assert after["term_status"] == "PROPOSED"
    assert after["negotiation_round"] == 1
    assert after["version"] == v0 + 2


def test_revise_with_new_total_recomputes_provisional():
    """PRD section 2.7: "The provisional variant runs when a settlement is
    proposed, and again when a revise supplies a new total."
    PRD section 3.3: "When the revise supplies `revised_total_cents`, the
    settlement's `monetary_total_cents` is updated and the provisional
    allocation variant is recomputed against the new total."
    PRD section 3.3: "the lead-state cost pool is the smaller of 25000000
    cents and the base multiplied by 500 basis points out of 10000, rounded
    half up to a whole cent."

    Design: Corner/calculations/revise_with_new_total_recomputes_provisional
    """
    world = setup_proposed_world(office_codes=("CA", "TX", "NY"))
    countered = counter_settlement(world["settlement"], counter_total_cents=90000000)
    revised = revise_settlement(
        countered, world["offices"]["CA"], revised_total_cents=120000000,
    )
    assert revised["monetary_total_cents"] == 120000000
    # base 110,000,000; lead pool min(25,000,000, 5% of base) = 5,500,000;
    # provisional distributable 110,000,000 - 5,500,000.
    assert revised["provisional_distributable_cents"] == 104500000
    # populations CA 100 / TX 300 / NY 400 over total 800 -> 1250/3750/5000 bps
    # (the design index's 1000/3000/4000 figures belong to the canonical
    # 4-office world with FL 200 in the denominator; this setup has 3 offices).
    assert revised["provisional_weight_bps_by_state"] == {
        "CA": 1250, "TX": 3750, "NY": 5000,
    }, "provisional weights still normalize over the ACTIVE participations"


def test_defendant_cannot_open_sign_on():
    """PRD section 4: the open-sign-on endpoint is authorized for
    CommitteeChair only.
    PRD section 2.1: "A request whose role is not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD section 3.4: "Opening stamps `sign_on_opened_at` with the current
    logical time and fixes `sign_on_deadline` exactly 45 days later."

    Design: Corner/rbac/defendant_cannot_open_sign_on
    """
    world = setup_proposed_world()
    settlement = agree_terms(world["settlement"]["id"])
    advance_investigation(world["investigation"]["id"], "SETTLEMENT_PENDING")
    resp = api_client.open_sign_on(settlement["id"], COUNSEL)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = get_settlement(settlement["id"])
    assert after["term_status"] == "TERMS_AGREED"
    assert after["sign_on_opened_at"] is None
    assert after["sign_on_deadline"] is None


def test_execute_from_proposed_returns_invalid_state():
    """PRD section 3.4: "Execution is the moment of truth, performed by the
    `CommitteeChair` on a settlement in `SIGN_ON_OPEN` while the investigation
    is in `SETTLEMENT_PENDING`."
    PRD section 2.8: "the target resource's own state machine must admit the
    trigger (`ERR_INVALID_STATE`, ...)."

    Design: Corner/state_machines/execute_from_proposed_returns_invalid_state
    """
    world = setup_proposed_world()
    resp = api_client.execute_settlement(world["settlement"]["id"], CHAIR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_settlement(world["settlement"]["id"])["term_status"] == "PROPOSED"
