"""Domain graph helpers: lookups, denormalized rollups, exposure policy.

The rollup recomputations deliberately touch only computed fields — they never
bump `version`, because `version` tracks explicit client-visible transitions
used for optimistic concurrency control (PRD §2.6, §2.8).
"""
from . import clock, computations
from .computations import (
    AGREEMENT_REINSTATEMENT_THRESHOLD_CENTS,
    AGREEMENT_SUSPENSION_THRESHOLD_CENTS,
    ACQUISITION_COST_PER_ACCOUNT_CENTS,
    BALANCE_CAP_MULTIPLE,
    BALANCE_UNIT_CENTS,
    round_half_up,
)
from .store import find, store


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_partner(partner_id):
    return store.partners.get(partner_id)


def get_agreement(agreement_id):
    return store.agreements.get(agreement_id)


def get_program(program_id):
    return store.programs.get(program_id)


def get_account(account_id):
    return store.accounts.get(account_id)


def get_program_of_account(account):
    return store.programs.get(account.get("program_id"))


def get_agreement_of_program(program):
    return store.agreements.get(program.get("agreement_id"))


def get_program_of_plan(plan):
    return store.programs.get(plan.get("program_id"))


def get_transaction(transaction_id):
    return store.transactions.get(transaction_id)


def get_partner_of_account(account):
    program = get_program_of_account(account)
    if not program:
        return None
    return store.partners.get(program.get("partner_id"))


def accounts_of_program(program_id):
    return [a for a in store.accounts.values() if a.get("program_id") == program_id]


def programs_of_agreement(agreement_id):
    return [p for p in store.programs.values() if p.get("agreement_id") == agreement_id]


def programs_of_partner(partner_id):
    return [p for p in store.programs.values() if p.get("partner_id") == partner_id]


def plans_of_program(program_id):
    return [p for p in store.promo_plans.values() if p.get("program_id") == program_id]


def plans_of_account(account_id):
    return [p for p in store.promo_plans.values() if p.get("account_id") == account_id]


def plans_of_transaction(transaction_id):
    return [p for p in store.promo_plans.values() if p.get("transaction_id") == transaction_id]


def balances_of_account(account_id):
    return [b for b in store.scheduled_balances.values() if b.get("account_id") == account_id]


def days_since_last_payment(account):
    """Whole logical days since the account's scheduled payment due date.

    The account's servicing clock starts when its payment is scheduled
    (PRD §3.6: "days since the account's last payment").
    """
    due = store.payment_due.get(account["id"])
    if not due:
        return 0
    try:
        due_at = clock.parse(due)
    except ValueError:
        return 0
    elapsed = clock.days_between(due_at, clock.now())
    return elapsed if elapsed > 0 else 0


# ---------------------------------------------------------------------------
# Rollups
# ---------------------------------------------------------------------------

def recompute_account_balance(account):
    """Account.outstanding_balance_cents is the sum of its principal slices."""
    total = sum(b.get("principal_balance_cents", 0) for b in balances_of_account(account["id"]))
    account["outstanding_balance_cents"] = total
    return total


def _batch_contribution(batch, revenue_share_rate, average_balance_cents):
    multiplier = 1 + revenue_share_rate * min(
        average_balance_cents / BALANCE_UNIT_CENTS, float(BALANCE_CAP_MULTIPLE)
    )
    net = batch.get("gross_subsidy_cents", 0) - batch.get("retailer_liability_cents", 0)
    return round_half_up(net * multiplier, 0)


def compute_program_profitability(program):
    """Full recomputation over every settled batch of the program (PRD §3.6)."""
    program_id = program["id"]
    agreement = get_agreement_of_program(program) or {}
    revenue_share_rate = float(agreement.get("revenue_share_rate", 0.0))
    accounts = accounts_of_program(program_id)
    account_count = len(accounts)
    average_balance_cents = sum(a.get("outstanding_balance_cents", 0) for a in accounts)
    settled = [b for b in store.settlement_batches.values()
               if b.get("agreement_id") == agreement.get("id")
               and b.get("batch_status") == "SETTLED"]
    total = 0
    for batch in settled:
        total += _batch_contribution(batch, revenue_share_rate, average_balance_cents)
    total -= account_count * ACQUISITION_COST_PER_ACCOUNT_CENTS
    return int(round_half_up(total, 0))


def recompute_program_rollups(program):
    """Recompute every denormalized program figure (PRD §3.2)."""
    program_id = program["id"]
    accounts = accounts_of_program(program_id)
    program["outstanding_receivable_cents"] = sum(
        a.get("outstanding_balance_cents", 0)
        for a in accounts if a.get("account_status") != "CHARGED_OFF"
    )
    program["free_look_exposure_cents"] = sum(
        p.get("subsidy_at_risk_cents", 0)
        for p in plans_of_program(program_id) if p.get("plan_status") == "ACTIVE"
    )
    program["program_profitability_cents"] = compute_program_profitability(program)
    _refresh_partner_exposure(program.get("partner_id"))
    return program


def _refresh_partner_exposure(partner_id):
    partner = store.partners.get(partner_id)
    if not partner:
        return
    partner["partner_portfolio_exposure_cents"] = sum(
        p.get("free_look_exposure_cents", 0) for p in programs_of_partner(partner_id)
    )


def refresh_program(program):
    """Recompute a program's rollups, its partner's exposure, and the
    governing agreement's automatic exposure safeguard."""
    if program is None:
        return
    recompute_program_rollups(program)
    _apply_agreement_exposure_policy(program.get("agreement_id"))


def refresh_plan_exposure(plan):
    """Recompute the owning program after a plan's risk figure changed."""
    program = store.programs.get(plan.get("program_id"))
    refresh_program(program)


def _apply_agreement_exposure_policy(agreement_id):
    """Automatic agreement suspension / reinstatement by exposure rollup.

    Aggregate >= 5,000,000,000 suspends an ACTIVE agreement; strictly below
    4,000,000,000 restores a SUSPENDED one. Both bump the agreement version
    (PRD §3.1).
    """
    agreement = store.agreements.get(agreement_id)
    if not agreement:
        return
    aggregate = sum(p.get("free_look_exposure_cents", 0) for p in programs_of_agreement(agreement_id))
    status = agreement.get("agreement_status")
    if status == "ACTIVE" and aggregate >= AGREEMENT_SUSPENSION_THRESHOLD_CENTS:
        agreement["agreement_status"] = "SUSPENDED"
        agreement["version"] = agreement.get("version", 1) + 1
        agreement["updated_at"] = clock.now_iso()
    elif status == "SUSPENDED" and aggregate < AGREEMENT_REINSTATEMENT_THRESHOLD_CENTS:
        agreement["agreement_status"] = "ACTIVE"
        agreement["version"] = agreement.get("version", 1) + 1
        agreement["updated_at"] = clock.now_iso()


# ---------------------------------------------------------------------------
# Promotional subsidy (PRD §3.4, §3.7)
# ---------------------------------------------------------------------------

def compute_subsidy_at_risk(plan, agreement) -> int:
    """Live partner-funded exposure for a plan."""
    if plan.get("promo_start_at") >= plan.get("promo_expires_at"):
        return 0
    if plan.get("promo_principal_cents", 0) < agreement.get("minimum_charge_cents", 0):
        return 0
    if not plan.get("qualifying_flag"):
        return 0
    gross = computations.projected_interest(
        plan["promo_principal_cents"], plan["promo_term_months"]
    )
    return computations.money(gross * computations.dec(agreement.get("promo_subsidy_rate", 0.0)))


def is_plan_expired(plan) -> bool:
    """The clock has reached the plan's expiry instant (PRD §3.4)."""
    try:
        return clock.now() >= clock.parse(plan["promo_expires_at"])
    except (KeyError, ValueError):
        return False


def expire_plan(plan) -> bool:
    """ACTIVE -> EXPIRED with a zero risk figure (PRD §3.4)."""
    if plan.get("plan_status") != "ACTIVE":
        return False
    plan["plan_status"] = "EXPIRED"
    plan["subsidy_at_risk_cents"] = 0
    return True


def expire_plans_on_account(account):
    """Charge-off hop 2: every plan on the account expires with zero exposure."""
    changed = False
    for plan in plans_of_account(account["id"]):
        if expire_plan(plan):
            changed = True
    return changed


def zero_plans_on_transaction(transaction_id):
    """Dispute hop 2: a disputed purchase's plans drop to zero exposure."""
    for plan in plans_of_transaction(transaction_id):
        plan["subsidy_at_risk_cents"] = 0


def restore_plans_on_transaction(transaction_id):
    """Merchant resolution hop 1: recompute each plan's exposure."""
    for plan in plans_of_transaction(transaction_id):
        if plan.get("plan_status") != "ACTIVE":
            continue
        agreement = get_agreement_of_program(get_program_of_plan(plan)) or {}
        plan["subsidy_at_risk_cents"] = compute_subsidy_at_risk(plan, agreement)