"""Dependent-claim conflict tests: analyst resolution with the single-credit
invariant, the clock-sweep default resolution, and the third-claim
exclusivity gate.

PRD section 3.6 (with the sweep of section 2.4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    DEPENDENT_CREDIT_CENTS,
    create_dependent_payload,
    create_return_payload,
    create_taxpayer,
    get_conflict,
    get_return,
    list_claims,
    make_taxpayer_headers,
    resolve_conflict,
    set_clock,
    setup_dependent_conflict,
    validate_error,
)

ANALYST = TEST_USERS["fraud_analyst_headers"]


def test_analyst_resolution_second_filer_wins_claim(api):
    """PRD section 3.6: "An analyst decision — a `FraudAnalyst` resolving an
    `OPEN` conflict with a payload `winner` naming the first or second filer
    — requires the conflict to still be `OPEN` (a resolved conflict rejects
    further action with `ERR_CONFLICT_ALREADY_RESOLVED`, HTTP 409), records
    the payload winner as the `resolution` (`FIRST_FILER` or `SECOND_FILER`)
    with `resolved_reason` `ANALYST_DECISION`."
    PRD section 3.6: "Under analyst decision and default resolution, the
    winner's claim moves from `CONTESTED` to `SUSTAINED` and the loser's
    claim moves to `DISALLOWED`".

    Design: Difficulty/compensating_invariant/conflict_resolution_conserves_single_credit
    """
    world = setup_dependent_conflict(
        claim_a_cents=300000, claim_b_cents=100000,
        clock_iso="2027-02-01T00:00:00Z",
    )
    conflict = world["conflict"]

    resolved = resolve_conflict(conflict["id"], winner="SECOND_FILER")
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "SECOND_FILER"
    assert resolved["resolved_reason"] == "ANALYST_DECISION"

    claim_a = list_claims(world["return_a"]["id"])[0]
    claim_b = list_claims(world["return_b"]["id"])[0]
    assert claim_a["status"] == "DISALLOWED"
    assert claim_b["status"] == "SUSTAINED"


def test_loser_absorbs_single_credit_adjustment(api):
    """PRD section 3.6: "the adjustment amount is the lesser of 200000 cents
    (the dependent credit at stake) and the losing return's
    `claimed_refund_cents`; that amount is subtracted from
    `claimed_refund_cents` — the minimum guarantees the floor of 0 is never
    breached — and the same signed amount is subtracted from the return's
    `adjustment_cents`, which accumulates negative adjustments."
    PRD section 3.4: "Every claim's `credit_cents` is fixed at 200000 cents —
    the dependent credit at stake".

    Design: Difficulty/compensating_invariant/conflict_resolution_conserves_single_credit
    """
    world = setup_dependent_conflict(
        claim_a_cents=300000, claim_b_cents=100000,
        clock_iso="2027-02-01T00:00:00Z",
    )
    resolve_conflict(world["conflict"]["id"], winner="SECOND_FILER")

    loser = get_return(world["return_a"]["id"])
    assert loser["claimed_refund_cents"] == 100000
    assert loser["adjustment_cents"] == -DEPENDENT_CREDIT_CENTS

    winner = get_return(world["return_b"]["id"])
    assert winner["claimed_refund_cents"] == 100000
    assert winner["adjustment_cents"] == 0

    # Conserved quantity: exactly one SUSTAINED claim, worth exactly one
    # DEPENDENT_CREDIT_CENTS, for this (dependent_tin, tax_year).
    claims = list_claims(world["return_a"]["id"]) + list_claims(world["return_b"]["id"])
    sustained = [c for c in claims if c["status"] == "SUSTAINED"]
    assert len(sustained) == 1
    assert sustained[0]["credit_cents"] == DEPENDENT_CREDIT_CENTS


def test_conflict_clock_sweep_default_first_filer(api):
    """PRD section 2.4: "First, every `OPEN` dependent conflict whose
    `evidence_window_ends_at` is earlier than the new clock time is
    auto-resolved by the evidence rule described in §3.6."
    PRD section 3.6: "A default resolution fires from the clock sweep of
    §2.4 when the clock advances past `evidence_window_ends_at` while the
    conflict is still `OPEN`: the `resolution` becomes `SECOND_FILER` exactly
    when `evidence_b_submitted` is true and `evidence_a_submitted` is false,
    and `FIRST_FILER` in every other evidence combination, with
    `resolved_reason` `DEFAULT_NO_EVIDENCE`."
    PRD section 3.6: "the adjustment amount is the lesser of 200000 cents
    (the dependent credit at stake) and the losing return's
    `claimed_refund_cents`; that amount is subtracted from
    `claimed_refund_cents` — the minimum guarantees the floor of 0 is never
    breached".

    Design: Corner/state_machines/conflict_clock_sweep_default_first_filer
    """
    world = setup_dependent_conflict(
        claim_a_cents=300000, claim_b_cents=150000,
        clock_iso="2027-02-01T00:00:00Z",
    )
    conflict = world["conflict"]

    # No evidence from either side; the window ends 2027-03-03T00:00:00Z.
    set_clock("2027-03-04T00:00:00Z")

    swept = get_conflict(conflict["id"])
    assert swept["status"] == "RESOLVED"
    assert swept["resolution"] == "FIRST_FILER"
    assert swept["resolved_reason"] == "DEFAULT_NO_EVIDENCE"

    loser = get_return(world["return_b"]["id"])
    # delta = min(200000, 150000) == 150000: floored at a 0-cent claim.
    assert loser["claimed_refund_cents"] == 0
    assert loser["adjustment_cents"] == -150000

    claim_a = list_claims(world["return_a"]["id"])[0]
    assert claim_a["status"] == "SUSTAINED"


def test_third_claim_on_contested_dependent_rejected(api):
    """PRD section 3.4: "If that dependent TIN and tax year already sit
    inside an `OPEN` conflict, the filing is refused outright with
    `ERR_DEPENDENT_CONFLICT_OPEN` (HTTP 409)."

    Design: Corner/validations/third_claim_on_contested_dependent_rejected
    """
    world = setup_dependent_conflict(clock_iso="2027-02-01T00:00:00Z")
    assert world["conflict"]["status"] == "OPEN"

    third = create_taxpayer()
    resp = api.file_tax_return(
        create_return_payload(
            third["id"], claimed_refund_cents=50000, bank_product="NONE",
            dependents=[
                create_dependent_payload(world["dependent_tin"], "SIBLING")
            ],
        ),
        make_taxpayer_headers(third["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEPENDENT_CONFLICT_OPEN)
