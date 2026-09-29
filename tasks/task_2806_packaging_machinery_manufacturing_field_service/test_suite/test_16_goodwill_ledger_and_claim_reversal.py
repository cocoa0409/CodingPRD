"""The goodwill pot: what a claim spends, where the band edges sit, and undoing it.

Money is the propagating quantity here — an approval walks from the claim to the
contract's pot to its derived posture and on into the service diary, and a void must
walk every step of that back.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    SERVICE_MANAGER,
    api_client,
    book_visit,
    read_claim,
    read_contract,
    read_model,
    read_visit,
    setup_accepted_machine,
    setup_active_contract,
    setup_claim_ready_for_adjudication,
    setup_reference_data,
)

TERM = {"start_date": "2026-08-01", "end_date": "2027-07-31", "pm_visits_included": 2}
MORNING_SLOT = {
    "start_ts": "2026-08-10T08:00:00.000Z",
    "end_ts": "2026-08-10T12:00:00.000Z",
}


def _covered_claim(tier, pot_cents, with_visit=True, failure_summary=None, line_label=None):
    """A single-line, fully reviewed 400,000-cent claim on a funded contract, with an
    optional preventive visit already on the books."""
    env = setup_accepted_machine(setup_reference_data(line={}, engineer={}))
    env = setup_active_contract(
        env,
        contract_overrides=dict(TERM, tier=tier, goodwill_budget_initial_cents=pot_cents),
    )
    if with_visit:
        env = book_visit(env, visit_type="PM", **MORNING_SLOT)
    return setup_claim_ready_for_adjudication(
        env,
        lines=[
            {
                "line_label": line_label or "Turret cam rebuild",
                "amount_cents": 400_000,
                "defect_attribution_pct": 100.00,
            }
        ],
        claim_overrides={
            "failure_summary": failure_summary or "Cam follower failure on the filling turret"
        },
    )


def test_the_goodwill_charge_is_clamped_to_whatever_is_left_in_the_pot():
    """A GOLD contract absorbs the whole 400,000-cent OEM share, but the pot only holds
    300,000, so the charge is clamped and the balance stops at exactly zero.

    PRD: "The clamp is what keeps the pot from going negative: it can be driven to
    exactly 0 and no further."

    Design: Difficulty/transitive_cascade/claim_adjudication_cascade_exhausts_goodwill_and_holds_visit
    """
    env = _covered_claim("GOLD", 300_000)

    data = validate_success(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], "APPROVE", SERVICE_MANAGER)
    )

    assert data["status"] == "ADJUDICATED"
    assert data["cause"] == "MACHINE_DEFECT"
    assert data["oem_share_cents"] == 400_000
    assert data["customer_share_cents"] == 0
    assert data["goodwill_charged_cents"] == 300_000
    contract = read_contract(env["contract"]["id"])
    assert contract["goodwill_budget_cents"] == 0
    assert contract["coverage_posture"] == "BUDGET_EXHAUSTED"


def test_draining_the_pot_puts_the_booked_visit_on_a_billable_hold():
    """The approval reaches a third entity the request never named: the appointment is
    kept but the customer now pays for it.

    PRD: "Hop three re-derives `coverage_posture` from the new balance, and if the
    posture has just become `BUDGET_EXHAUSTED` in this request, every visit on that
    contract still sitting in `SCHEDULED` is moved to `BILLABLE_HOLD` with its
    `billable` flag set to true — the OEM keeps the appointment but the customer now
    pays for it."

    Design: Difficulty/transitive_cascade/claim_adjudication_cascade_exhausts_goodwill_and_holds_visit
    """
    env = _covered_claim("GOLD", 300_000)
    assert env["visit"]["status"] == "SCHEDULED"
    assert env["visit"]["billable"] is False

    validate_success(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], "APPROVE", SERVICE_MANAGER)
    )

    visit = read_visit(env["visit"]["id"])
    assert visit["status"] == "BILLABLE_HOLD"
    assert visit["billable"] is True
    assert read_model(env["model"]["id"])["open_defect_review_count"] == 1


def test_exactly_fifty_thousand_cents_left_in_the_pot_reads_as_restricted():
    """A SILVER contract absorbs three quarters of the 400,000-cent share, charging
    300,000 against a 350,000-cent pot and landing on the inclusive upper edge of the
    restricted band.

    PRD: "The restricted band is inclusive at its upper edge: exactly 50,000 cents
    remaining is `RESTRICTED`, while 50,001 cents is `OPEN`."

    Design: Difficulty/boundary_precision_check/goodwill_remainder_exactly_at_restrict_threshold_sets_restricted
    """
    env = _covered_claim(
        "SILVER",
        350_000,
        with_visit=False,
        failure_summary="Nozzle block cracked during production",
        line_label="Nozzle block replacement",
    )

    data = validate_success(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], "APPROVE", SERVICE_MANAGER)
    )

    assert data["status"] == "ADJUDICATED"
    assert data["cause"] == "MACHINE_DEFECT"
    assert data["oem_share_cents"] == 400_000
    assert data["goodwill_charged_cents"] == 300_000
    contract = read_contract(env["contract"]["id"])
    assert contract["goodwill_budget_cents"] == 50_000
    assert contract["coverage_posture"] == "RESTRICTED"


def test_one_cent_more_in_the_pot_keeps_the_contract_open():
    """Funding the identical contract with a single extra cent leaves 50,001 after the
    identical charge, which is one cent clear of the restricted band.

    PRD: "It reads `BUDGET_EXHAUSTED` when `goodwill_budget_cents` is exactly 0,
    `RESTRICTED` when the remaining pot is above 0 but no more than 50,000 cents — that
    is, five hundred dollars or less still available — and `OPEN` otherwise."

    Design: Difficulty/boundary_precision_check/goodwill_remainder_exactly_at_restrict_threshold_sets_restricted
    """
    env = _covered_claim(
        "SILVER",
        350_001,
        with_visit=False,
        failure_summary="Nozzle block cracked during production",
        line_label="Nozzle block replacement",
    )

    data = validate_success(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], "APPROVE", SERVICE_MANAGER)
    )

    assert data["goodwill_charged_cents"] == 300_000
    contract = read_contract(env["contract"]["id"])
    assert contract["goodwill_budget_cents"] == 50_001
    assert contract["coverage_posture"] == "OPEN"


def test_voiding_the_claim_restores_the_pot_to_its_full_opening_balance():
    """The ledger identity is what is being conserved: with no adjudicated claim left on
    the contract the pot must read exactly its initial funding again, while the cost
    record itself survives.

    PRD: "Hop two debits the contract, reducing `goodwill_budget_cents` by
    `goodwill_charged_cents`, which must leave the pot equal to
    `goodwill_budget_initial_cents` less the sum of `goodwill_charged_cents` over all
    `ADJUDICATED` claims on that contract."

    Design: Difficulty/compensating_invariant/claim_void_restores_goodwill_budget_and_releases_billable_hold
    """
    env = _covered_claim(
        "GOLD",
        300_000,
        failure_summary="filling valve seat fractured after 300 hours",
        line_label="valve seat assembly",
    )
    validate_success(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], "APPROVE", SERVICE_MANAGER)
    )
    assert read_contract(env["contract"]["id"])["goodwill_budget_cents"] == 0

    data = validate_success(api_client.void_warranty_claim(env["claim"]["id"], SERVICE_MANAGER))

    assert data["status"] == "VOID"
    assert data["goodwill_charged_cents"] == 0
    assert data["oem_share_cents"] == 0
    assert data["customer_share_cents"] == 0
    assert data["claimed_cost_cents"] == 400_000
    contract = read_contract(env["contract"]["id"])
    assert contract["goodwill_budget_cents"] == 300_000
    assert contract["goodwill_budget_cents"] == contract["goodwill_budget_initial_cents"]
    assert contract["coverage_posture"] == "OPEN"
    rows, meta = validate_paginated(
        api_client.list_warranty_claim_lines(
            SERVICE_MANAGER, params={"warranty_claim_id": env["claim"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["amount_cents"] == 400_000


def test_the_void_also_releases_the_billable_hold_and_withdraws_the_defect_review():
    """A partial reversal would leave the customer paying for a visit and the model
    carrying a defect tally, so the reversal has to reach both of those third parties.

    PRD: "The claim moves to `VOID`; the contract's `goodwill_budget_cents` is credited
    by exactly the claim's `goodwill_charged_cents`; that `goodwill_charged_cents` is
    then reset to 0 along with the claim's `oem_share_cents` and `customer_share_cents`;
    the contract's `coverage_posture` is re-derived, and any visit sitting in
    `BILLABLE_HOLD` on a contract whose posture has left `BUDGET_EXHAUSTED` for `OPEN` or
    `RESTRICTED` returns to `SCHEDULED` with its `billable` flag recomputed under the
    billability rules of §3.8; and the `open_defect_review_count` on the model behind the
    machine is decremented by 1, because the defect review is withdrawn along with the
    claim."

    Design: Difficulty/compensating_invariant/claim_void_restores_goodwill_budget_and_releases_billable_hold
    """
    env = _covered_claim(
        "GOLD",
        300_000,
        failure_summary="filling valve seat fractured after 300 hours",
        line_label="valve seat assembly",
    )
    validate_success(
        api_client.adjudicate_warranty_claim(env["claim"]["id"], "APPROVE", SERVICE_MANAGER)
    )
    held = read_visit(env["visit"]["id"])
    assert held["status"] == "BILLABLE_HOLD"
    assert held["billable"] is True
    assert read_model(env["model"]["id"])["open_defect_review_count"] == 1

    validate_success(api_client.void_warranty_claim(env["claim"]["id"], SERVICE_MANAGER))

    released = read_visit(env["visit"]["id"])
    assert released["status"] == "SCHEDULED"
    assert released["billable"] is False
    assert read_model(env["model"]["id"])["open_defect_review_count"] == 0
    assert read_claim(env["claim"]["id"])["status"] == "VOID"
