"""Derived-field recomputation and the cascades of PRD 3.2, 3.4, 3.5 and 3.9.

Every derived money and unit field is recomputed from its defining input set
rather than adjusted incrementally, exactly as the specification demands; that
is what makes validate-then-unwind land back on the pre-validation figures.
"""

import clock
import db
import util
from middleware import touch
from services import calc

FULL_REVERSAL_REASONS = ("UNWOUND_DEAL", "BACK_DATED_SALE", "DUPLICATE_CLAIM")
PARTIAL_REASONS = ("OBJECTIVE_REVISED", "REPRICING_ADJUSTMENT")
CHARGEBACK_REASONS = FULL_REVERSAL_REASONS + PARTIAL_REASONS


# --------------------------------------------------------------------------
# Recomputation of derived fields
# --------------------------------------------------------------------------

def recompute_program(program, bump=True):
    """Refresh every derived money and unit field of one program (PRD 3.7, 3.9)."""
    claims = calc.committed_claim_set(program["id"])

    committed = sum(c["approved_amount_cents"] for c in claims)
    for claim in calc.program_claims(program["id"]):
        for chargeback in calc.claim_chargebacks(claim["id"]):
            if chargeback["status"] == "WRITTEN_OFF":
                committed += chargeback["amount_cents"]
    program["committed_cents"] = committed

    program["paid_cents"] = sum(
        c["approved_amount_cents"]
        for c in calc.program_claims(program["id"])
        if c["payment_status"] == "PAID"
    )

    claimed_units, per_unit = calc.per_unit_spend(program["id"])
    program["claimed_units"] = claimed_units
    program["per_unit_spend_cents"] = per_unit

    program["accrued_budget_cents"] = calc.accrued_budget_cents(program["id"])
    program["residual_impact_bps"] = calc.residual_impact_bps(program)

    if bump:
        touch(program)
    return program


def recompute_dealer(dealer, bump=True):
    """Dealer paid_cents and open_chargeback_cents (PRD 3.7, 3.9)."""
    if dealer is None:
        return None
    dealer_claims = [c for c in db.claims.values() if c["dealer_id"] == dealer["id"]]
    dealer["paid_cents"] = sum(
        c["approved_amount_cents"] for c in dealer_claims if c["payment_status"] == "PAID"
    )
    open_chargebacks = 0
    for claim in dealer_claims:
        for chargeback in calc.claim_chargebacks(claim["id"]):
            if chargeback["status"] == "PENDING":
                open_chargebacks += chargeback["amount_cents"]
    dealer["open_chargeback_cents"] = open_chargebacks
    if bump:
        touch(dealer)
    return dealer


def recompute_batch(batch, bump=True):
    """claim_count and total_cents over the batch's SCHEDULED or PAID claims."""
    if batch is None:
        return None
    attached = [
        c
        for c in db.claims.values()
        if c["payment_batch_id"] == batch["id"]
        and c["payment_status"] in ("SCHEDULED", "PAID")
    ]
    batch["claim_count"] = len(attached)
    batch["total_cents"] = sum(c["approved_amount_cents"] for c in attached)
    if bump:
        touch(batch)
    return batch


def recompute_objective(objective, bump=True):
    """achieved_units, attainment_bps, tier_attained and payout_cents (PRD 3.7)."""
    program = db.programs[objective["program_id"]]
    objective["achieved_units"] = calc.objective_achieved_units(objective)
    attainment_bps, tier_attained, payout = calc.stair_step_payout(objective, program)
    objective["attainment_bps"] = attainment_bps
    objective["tier_attained"] = tier_attained
    objective["payout_cents"] = payout
    if bump:
        touch(objective)
    return objective


def credited_objectives(delivery):
    """The objectives whose progress this delivery moves (PRD 3.5)."""
    result = []
    for objective in db.ordered(list(db.objectives.values())):
        if objective["dealer_id"] != delivery["dealer_id"]:
            continue
        if objective["status"] not in ("PROPOSED", "PROTESTED", "REVISED", "FINAL"):
            continue
        program = db.programs.get(objective["program_id"])
        if program is None or not calc.program_admits(program, delivery):
            continue
        result.append(objective)
    return result


# --------------------------------------------------------------------------
# Chargebacks and the accrual reversal row
# --------------------------------------------------------------------------

def append_reversal_row(program, chargeback):
    """Exactly one REVERSAL ledger row per chargeback (PRD 3.9)."""
    row = {
        "program_id": program["id"],
        "period_month": util.month_key_of(clock.now()),
        "accrual_method": program["accrual_method"],
        "entry_type": "REVERSAL",
        "unit_basis": 0,
        "accrued_cents": 0,
        "reversal_cents": chargeback["amount_cents"],
        "source_reference": chargeback["id"],
    }
    return db.insert(db.budget_accruals, "budget_accrual", row)


def create_chargeback(claim, reason, amount_cents, created_by_user_id=None):
    """Create a chargeback plus its reversal row. Returns None when amount <= 0."""
    if amount_cents <= 0:
        return None
    chargeback = db.insert(
        db.chargebacks,
        "chargeback",
        {
            "claim_id": claim["id"],
            "reason": reason,
            "amount_cents": amount_cents,
            "status": "PENDING",
            "created_by_user_id": created_by_user_id,
            "recovered_at": None,
        },
    )
    program = db.programs[claim["program_id"]]
    append_reversal_row(program, chargeback)
    return chargeback


def reverse_claim_payment(claim):
    """Full reversal: the claim leaves the committed set and its batch."""
    former_batch_id = claim["payment_batch_id"]
    claim["payment_status"] = "CHARGED_BACK"
    claim["payment_batch_id"] = None
    touch(claim)
    if former_batch_id is not None:
        recompute_batch(db.payment_batches.get(former_batch_id))


# --------------------------------------------------------------------------
# Unwind cascade (PRD 3.9) - four links
# --------------------------------------------------------------------------

def unwind_cascade(delivery):
    programs_touched = []
    dealers_touched = []

    for claim in calc.delivery_claims(delivery["id"]):
        if claim["payment_status"] not in ("SCHEDULED", "PAID"):
            continue
        # Link two: one chargeback per charged-back claim, full recovery.
        create_chargeback(claim, "UNWOUND_DEAL", claim["approved_amount_cents"])
        # Link one: the claim leaves the committed set and its batch.
        reverse_claim_payment(claim)
        if claim["program_id"] not in programs_touched:
            programs_touched.append(claim["program_id"])
        if claim["dealer_id"] not in dealers_touched:
            dealers_touched.append(claim["dealer_id"])

    # Links three and four: every derived ledger field is recomputed.
    for program_id in programs_touched:
        recompute_program(db.programs[program_id])
    if delivery["dealer_id"] not in dealers_touched:
        dealers_touched.append(delivery["dealer_id"])
    for dealer_id in dealers_touched:
        recompute_dealer(db.dealers.get(dealer_id))

    for objective in credited_objectives(delivery):
        recompute_objective(objective)


# --------------------------------------------------------------------------
# Supersession cascade (PRD 3.2) - three links
# --------------------------------------------------------------------------

def supersede_cascade(program):
    program["status"] = "SUPERSEDED"
    for claim in calc.program_claims(program["id"]):
        if claim["validation_status"] != "SUBMITTED":
            continue
        claim["validation_status"] = "REJECTED"
        claim["approved_amount_cents"] = 0
        claim["rejection_error_id"] = "ERR_PROGRAM_NOT_ACTIVE"
        touch(claim)
    recompute_program(program)


# --------------------------------------------------------------------------
# Closure cascade (PRD 3.2)
# --------------------------------------------------------------------------

def close_cascade(program):
    for objective in calc.program_objectives(program["id"]):
        if objective["status"] not in ("PROPOSED", "PROTESTED", "REVISED"):
            continue
        objective["status"] = "VOID"
        objective["payout_cents"] = 0
        touch(objective)
        for protest in calc.objective_protests(objective["id"]):
            if protest["status"] != "OPEN":
                continue
            protest["status"] = "DENIED"
            protest["resolved_units"] = None
            touch(protest)


# --------------------------------------------------------------------------
# Upheld protest cascade (PRD 3.4) - four links
# --------------------------------------------------------------------------

def stair_step_claim_of(objective):
    """The stair-step bonus claim an upheld protest recovers against."""
    candidates = [
        c
        for c in db.ordered(list(db.claims.values()))
        if c["program_id"] == objective["program_id"]
        and c["dealer_id"] == objective["dealer_id"]
        and c["claim_type"] == "STAIR_STEP_BONUS"
    ]
    paid = [c for c in candidates if c["payment_status"] == "PAID"]
    if paid:
        return paid[-1]
    live = [
        c
        for c in candidates
        if c["validation_status"] != "REJECTED" and c["payment_status"] != "CHARGED_BACK"
    ]
    return live[-1] if live else None


def uphold_cascade(objective, protest):
    dealer = db.dealers[objective["dealer_id"]]
    program = db.programs[objective["program_id"]]

    # Link one: the dealer's figure replaces the volume basis.
    objective["basis_units"] = protest["claimed_basis_units"]
    objective["objective_units"] = calc.objective_units_from_basis(
        objective["basis_units"], dealer["market_opportunity_bps"], objective["stretch_bps"]
    )
    protest["resolved_units"] = objective["objective_units"]

    # Link two: the denominator moved, so the tier arithmetic reruns.
    recompute_objective(objective, bump=False)

    # Link three: partial recovery of an overpayment, only when overpaid.
    if objective["paid_payout_cents"] > objective["payout_cents"]:
        amount = objective["paid_payout_cents"] - objective["payout_cents"]
        claim = stair_step_claim_of(objective)
        if claim is not None:
            create_chargeback(claim, "OBJECTIVE_REVISED", amount)
            claim["approved_amount_cents"] = objective["payout_cents"]
            touch(claim)
            objective["paid_payout_cents"] = objective["payout_cents"]
            # Link four: the reduced amount reworks the program's books.
            recompute_program(program)
            recompute_dealer(dealer)


# --------------------------------------------------------------------------
# Retroactive repricing pass (PRD 3.9)
# --------------------------------------------------------------------------

def apply_retroactive_repricing(program, month_start, effective_at):
    """Re-evaluate the month. Returns (affected_claim_count, net_adjustment_cents)."""
    targets = []
    for claim in calc.program_claims(program["id"]):
        if claim["claim_type"] != "UNIT_INCENTIVE":
            continue
        if claim["validation_status"] != "VALIDATED":
            continue
        if claim["payment_status"] not in ("UNPAID", "SCHEDULED"):
            continue
        delivery = db.deliveries.get(claim["delivery_id"])
        if delivery is None:
            continue
        if not (month_start <= delivery["sale_date"] < effective_at):
            continue
        targets.append((delivery["sale_date"], claim["created_at"], claim["_seq"], claim))
    targets.sort(key=lambda row: (row[0], row[1], row[2]))

    affected_claim_count = 0
    net_adjustment_cents = 0
    batches_touched = []
    dealers_touched = []

    for _, _, _, claim in targets:
        new_amount, _ = calc.claim_payable(claim, force_repriced=True)
        delta = new_amount - claim["approved_amount_cents"]
        if delta == 0:
            continue
        affected_claim_count += 1
        net_adjustment_cents += delta

        batch = db.payment_batches.get(claim["payment_batch_id"])
        if batch is None or batch["status"] == "OPEN":
            claim["approved_amount_cents"] = new_amount
            claim["rate_basis"] = "REPRICED_CURRENT"
            touch(claim)
            if batch is not None and batch["id"] not in batches_touched:
                batches_touched.append(batch["id"])
        elif delta < 0:
            # Locked money: the amount stands and the shortfall is recovered.
            create_chargeback(claim, "REPRICING_ADJUSTMENT", -delta)
            if claim["dealer_id"] not in dealers_touched:
                dealers_touched.append(claim["dealer_id"])

    for batch_id in batches_touched:
        recompute_batch(db.payment_batches[batch_id])
    for dealer_id in dealers_touched:
        recompute_dealer(db.dealers.get(dealer_id))
    recompute_program(program, bump=False)
    return affected_claim_count, net_adjustment_cents
