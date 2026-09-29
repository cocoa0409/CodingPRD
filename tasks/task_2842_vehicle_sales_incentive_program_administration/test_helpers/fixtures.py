"""Composite setup helpers.

The server is restarted before every test, so every precondition is rebuilt
from scratch through the public API. Each helper below returns the entity the
setup step produced, so a test can read the ids and version counters it needs
without repeating the chain.

Two rules are threaded through every helper here:
  * a `Dealer` call is always made with `make_dealer_headers(dealer_id)`, since
    a dealer's `X-User-ID` is the id of the acting Dealer row;
  * an optimistically guarded write always re-reads the parent's current
    `version` first, so the guard carries a fresh value.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .test_users import TEST_USERS, make_dealer_headers

DESIGNER = TEST_USERS["program_designer_headers"]
CONTROLLER = TEST_USERS["incentive_controller_headers"]
FSM = TEST_USERS["field_sales_manager_headers"]
# The validating auditor and the adjudicating auditor must be different
# principals, so the two roles below are deliberately distinct identities.
VALIDATOR = TEST_USERS["claims_auditor_headers"]
ADJUDICATOR = TEST_USERS["claims_auditor_2_headers"]


# --- The logical clock -------------------------------------------------------


def set_clock(instant: str) -> str:
    """Move the server's logical clock and return the resulting current_utc."""
    data = get_success_data(
        api_client.set_clock(f.set_clock_payload(instant), CONTROLLER)
    )
    return data["current_utc"]


# --- Readers -----------------------------------------------------------------


def read_program(program_id: str, headers: dict = DESIGNER) -> dict:
    return get_success_data(api_client.get_program(program_id, headers))


def read_dealer(dealer_id: str, headers: dict = CONTROLLER) -> dict:
    return get_success_data(api_client.get_dealer(dealer_id, headers))


def read_objective(objective_id: str, headers: dict = FSM) -> dict:
    return get_success_data(api_client.get_objective(objective_id, headers))


def read_delivery(delivery_id: str, headers: dict = VALIDATOR) -> dict:
    return get_success_data(api_client.get_delivery(delivery_id, headers))


def read_claim(claim_id: str, headers: dict = ADJUDICATOR) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers))


def read_batch(batch_id: str, headers: dict = CONTROLLER) -> dict:
    return get_success_data(api_client.get_payment_batch(batch_id, headers))


def program_version(program_id: str) -> int:
    """The program's current version, for the expected_program_version guard."""
    return read_program(program_id)["version"]


def objective_version(objective_id: str) -> int:
    """The objective's current version, for the expected_objective_version guard."""
    return read_objective(objective_id)["version"]


# --- Dealers -----------------------------------------------------------------


def register_dealer(**overrides) -> dict:
    """Register a dealer, ACTIVE with both money counters at zero."""
    return get_success_data(
        api_client.create_dealer(f.create_dealer_payload(**overrides), CONTROLLER)
    )


def set_dealer_status(dealer_id: str, status: str, **overrides) -> dict:
    return get_success_data(
        api_client.set_dealer_status(
            dealer_id, f.set_dealer_status_payload(status, **overrides), CONTROLLER
        )
    )


# --- Programs ----------------------------------------------------------------


def create_draft_program(payload: dict = None, **overrides) -> dict:
    """A DRAFT program with no eligibility footprint row yet."""
    body = payload if payload is not None else f.create_program_payload(**overrides)
    return get_success_data(api_client.create_program(body, DESIGNER))


def add_eligibility_rule(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_eligibility_rule(
            program_id, f.create_eligibility_rule_payload(**overrides), DESIGNER
        )
    )


def add_stack_edge(program_a_id: str, program_b_id: str, mode: str = "ALLOWED",
                   **overrides) -> dict:
    return get_success_data(
        api_client.create_stackability_constraint(
            program_a_id,
            f.create_stackability_constraint_payload(program_b_id, mode, **overrides),
            DESIGNER,
        )
    )


def create_draft_program_with_rules(payload: dict = None, rules=None,
                                    **overrides) -> dict:
    """A DRAFT program carrying at least one eligibility footprint row, which is
    the minimum a submission requires. Returns the re-read program."""
    program = create_draft_program(payload, **overrides)
    for rule in rules if rules is not None else [{}]:
        add_eligibility_rule(program["id"], **rule)
    return read_program(program["id"])


def submit_program(program_id: str, headers: dict = DESIGNER, **payload) -> dict:
    return get_success_data(
        api_client.submit_program(program_id, headers, payload or None)
    )


def approve_program(program_id: str, headers: dict = CONTROLLER, **payload) -> dict:
    return get_success_data(
        api_client.approve_program(program_id, headers, payload or None)
    )


def create_pending_program(payload: dict = None, rules=None, **overrides) -> dict:
    """A program in PENDING_APPROVAL, submitted by the shared designer id."""
    program = create_draft_program_with_rules(payload, rules, **overrides)
    return submit_program(program["id"])


def create_active_program(payload: dict = None, rules=None, **overrides) -> dict:
    """A program driven all the way to ACTIVE: created, given one footprint row,
    submitted by the designer and approved by a different principal."""
    program = create_pending_program(payload, rules, **overrides)
    return approve_program(program["id"])


def close_program(program_id: str, **payload) -> dict:
    return get_success_data(
        api_client.close_program(program_id, CONTROLLER, payload or None)
    )


def revise_program(program_id: str, **payload) -> dict:
    return get_success_data(
        api_client.revise_program(program_id, DESIGNER, payload or None)
    )


def apply_repricing(program_id: str, mode: str, new_per_unit_amount_cents: int,
                    expected_program_version: int = None) -> dict:
    """Apply a repricing, re-reading the program's version unless the caller
    pins one deliberately."""
    version = (
        program_version(program_id)
        if expected_program_version is None
        else expected_program_version
    )
    return get_success_data(
        api_client.create_repricing(
            program_id,
            f.create_repricing_payload(mode, new_per_unit_amount_cents, version),
            DESIGNER,
        )
    )


def run_accrual(program_id: str, period_month: str = "2026-08") -> dict:
    return get_success_data(
        api_client.run_accrual(program_id, f.run_accrual_payload(period_month), CONTROLLER)
    )


def read_spend_summary(program_id: str, headers: dict = CONTROLLER) -> dict:
    return get_success_data(api_client.get_spend_summary(program_id, headers))


# --- Objectives and protests -------------------------------------------------


def assign_objective(program_id: str, dealer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_objective(
            program_id, f.create_objective_payload(dealer_id, **overrides), FSM
        )
    )


def file_protest(objective_id: str, dealer_id: str, claimed_basis_units: int,
                 **overrides) -> dict:
    """The dealer files against its own objective, so the call carries that
    dealer's own headers."""
    return get_success_data(
        api_client.create_protest(
            objective_id,
            f.create_protest_payload(claimed_basis_units, **overrides),
            make_dealer_headers(dealer_id),
        )
    )


def resolve_protest(objective_id: str, protest_id: str, resolution: str,
                    expected_objective_version: int = None, headers: dict = FSM) -> dict:
    """Resolve a protest, re-reading the parent objective's version unless the
    caller pins one deliberately."""
    version = (
        objective_version(objective_id)
        if expected_objective_version is None
        else expected_objective_version
    )
    return get_success_data(
        api_client.resolve_protest(
            objective_id,
            protest_id,
            f.resolve_protest_payload(resolution, version),
            headers,
        )
    )


def finalize_objective(objective_id: str, headers: dict = FSM) -> dict:
    return get_success_data(api_client.finalize_objective(objective_id, headers))


def list_protests(objective_id: str, headers: dict = FSM, params: dict = None):
    return get_success_data(api_client.list_protests(objective_id, headers, params))


# --- Retail deliveries -------------------------------------------------------


def report_delivery(dealer_id: str, **overrides) -> dict:
    """The dealer reports for itself, so X-User-ID is the dealer's own id."""
    return get_success_data(
        api_client.create_delivery(
            f.create_delivery_payload(dealer_id, **overrides),
            make_dealer_headers(dealer_id),
        )
    )


def report_finance_delivery(dealer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_delivery(
            f.create_finance_delivery_payload(dealer_id, **overrides),
            make_dealer_headers(dealer_id),
        )
    )


def report_lease_delivery(dealer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_delivery(
            f.create_lease_delivery_payload(dealer_id, **overrides),
            make_dealer_headers(dealer_id),
        )
    )


def validate_delivery(delivery_id: str, headers: dict = VALIDATOR) -> dict:
    return get_success_data(api_client.validate_delivery(delivery_id, headers))


def reject_delivery(delivery_id: str, headers: dict = VALIDATOR, **overrides) -> dict:
    return get_success_data(
        api_client.reject_delivery(
            delivery_id, f.reject_delivery_payload(**overrides), headers
        )
    )


def unwind_delivery(delivery_id: str, headers: dict = VALIDATOR, **overrides) -> dict:
    return get_success_data(
        api_client.unwind_delivery(
            delivery_id, f.unwind_delivery_payload(**overrides), headers
        )
    )


def report_and_validate_delivery(dealer_id: str, **overrides) -> dict:
    """Report a delivery and have the anchor auditor vouch for it, which is the
    minimum state a claim can be built on."""
    delivery = report_delivery(dealer_id, **overrides)
    return validate_delivery(delivery["id"])


def read_eligible_programs(delivery_id: str, headers: dict = VALIDATOR) -> dict:
    return get_success_data(api_client.get_eligible_programs(delivery_id, headers))


# --- Claims ------------------------------------------------------------------


def submit_claim(dealer_id: str, delivery_id: str, program_id: str,
                 claimed_amount_cents: int, expected_program_version: int = None,
                 headers: dict = None, **overrides) -> dict:
    """Submit a claim, re-reading the program's version for the guard unless the
    caller pins one deliberately."""
    version = (
        program_version(program_id)
        if expected_program_version is None
        else expected_program_version
    )
    return get_success_data(
        api_client.create_claim(
            f.create_claim_payload(
                delivery_id, program_id, claimed_amount_cents, version, **overrides
            ),
            headers if headers is not None else make_dealer_headers(dealer_id),
        )
    )


def adjudicate_claim(claim_id: str, decision: str = "APPROVE",
                     headers: dict = ADJUDICATOR, **overrides) -> dict:
    """Adjudicate with an auditor identity distinct from the validating auditor,
    which is what the segregation-of-duties rule demands."""
    return get_success_data(
        api_client.adjudicate_claim(
            claim_id, f.adjudicate_payload(decision, **overrides), headers
        )
    )


def submit_and_approve_claim(dealer_id: str, delivery_id: str, program_id: str,
                             claimed_amount_cents: int) -> dict:
    claim = submit_claim(dealer_id, delivery_id, program_id, claimed_amount_cents)
    return adjudicate_claim(claim["id"])


def raise_chargeback(claim_id: str, reason: str, headers: dict = ADJUDICATOR) -> dict:
    return get_success_data(
        api_client.create_chargeback(
            claim_id, f.create_chargeback_payload(reason), headers
        )
    )


def recover_chargeback(chargeback_id: str) -> dict:
    return get_success_data(api_client.recover_chargeback(chargeback_id, CONTROLLER))


def write_off_chargeback(chargeback_id: str, **payload) -> dict:
    return get_success_data(
        api_client.write_off_chargeback(chargeback_id, CONTROLLER, payload or None)
    )


def list_chargebacks(claim_id: str, headers: dict = CONTROLLER, params: dict = None):
    return get_success_data(api_client.list_chargebacks(claim_id, headers, params))


# --- Payment batches ---------------------------------------------------------


def open_batch(**overrides) -> dict:
    return get_success_data(
        api_client.create_payment_batch(
            f.create_payment_batch_payload(**overrides), CONTROLLER
        )
    )


def schedule_claims(batch_id: str, claim_ids) -> dict:
    return get_success_data(
        api_client.schedule_claims(
            batch_id, f.schedule_claims_payload(claim_ids), CONTROLLER
        )
    )


def lock_batch(batch_id: str) -> dict:
    return get_success_data(api_client.lock_batch(batch_id, CONTROLLER))


def disburse_batch(batch_id: str, at: str = None) -> dict:
    """Disburse a locked batch, first moving the clock to the batch's
    scheduled_pay_date unless the caller names another instant."""
    batch = read_batch(batch_id)
    set_clock(at if at is not None else batch["scheduled_pay_date"])
    return get_success_data(api_client.disburse_batch(batch_id, CONTROLLER))


def cancel_batch(batch_id: str, **payload) -> dict:
    return get_success_data(
        api_client.cancel_batch(batch_id, CONTROLLER, payload or None)
    )


def pay_claims(claim_ids, at: str = None, **batch_overrides) -> dict:
    """Open a batch, attach the claims, lock it and disburse it. Returns the
    disbursed batch."""
    batch = open_batch(**batch_overrides)
    schedule_claims(batch["id"], claim_ids)
    lock_batch(batch["id"])
    return disburse_batch(batch["id"], at)


# --- Higher-tier composites --------------------------------------------------


def setup_active_program_and_dealer(program_overrides: dict = None,
                                   dealer_overrides: dict = None,
                                   rules=None) -> dict:
    """An ACTIVE program plus an ACTIVE dealer in the same region — the state
    every claim chain starts from."""
    program = create_active_program(
        rules=rules, **(program_overrides or {})
    )
    dealer = register_dealer(**(dealer_overrides or {}))
    return {"program": program, "dealer": dealer}


def setup_validated_delivery(program_overrides: dict = None,
                             dealer_overrides: dict = None,
                             delivery_overrides: dict = None,
                             rules=None) -> dict:
    """An ACTIVE program, an ACTIVE dealer and one VALIDATED delivery of that
    dealer that the program's footprint admits."""
    base = setup_active_program_and_dealer(program_overrides, dealer_overrides, rules)
    delivery = report_and_validate_delivery(
        base["dealer"]["id"], **(delivery_overrides or {})
    )
    return {
        "program": read_program(base["program"]["id"]),
        "dealer": read_dealer(base["dealer"]["id"]),
        "delivery": delivery,
    }


def setup_approved_claim(claimed_amount_cents: int = None,
                         program_overrides: dict = None,
                         dealer_overrides: dict = None,
                         delivery_overrides: dict = None,
                         rules=None) -> dict:
    """Carry the chain one step further: the delivery's claim is submitted and
    approved, so the program's committed ledger has moved."""
    base = setup_validated_delivery(
        program_overrides, dealer_overrides, delivery_overrides, rules
    )
    amount = (
        base["program"]["per_unit_amount_cents"]
        if claimed_amount_cents is None
        else claimed_amount_cents
    )
    claim = submit_and_approve_claim(
        base["dealer"]["id"], base["delivery"]["id"], base["program"]["id"], amount
    )
    base["claim"] = claim
    base["program"] = read_program(base["program"]["id"])
    return base


def setup_paid_claim(claimed_amount_cents: int = None,
                     program_overrides: dict = None,
                     dealer_overrides: dict = None,
                     delivery_overrides: dict = None,
                     batch_overrides: dict = None,
                     rules=None) -> dict:
    """The full money chain: an approved claim scheduled into a regional batch,
    locked and disbursed, so the claim is PAID and both paid ledgers have moved."""
    base = setup_approved_claim(
        claimed_amount_cents, program_overrides, dealer_overrides,
        delivery_overrides, rules,
    )
    overrides = dict(batch_overrides or {})
    overrides.setdefault("region_code", base["dealer"]["region_code"])
    batch = pay_claims([base["claim"]["id"]], **overrides)
    base["batch"] = batch
    base["claim"] = read_claim(base["claim"]["id"])
    base["program"] = read_program(base["program"]["id"])
    base["dealer"] = read_dealer(base["dealer"]["id"])
    return base


def setup_scheduled_claim(claimed_amount_cents: int = None,
                          program_overrides: dict = None,
                          dealer_overrides: dict = None,
                          delivery_overrides: dict = None,
                          batch_overrides: dict = None,
                          rules=None, lock: bool = False) -> dict:
    """An approved claim attached to an OPEN batch, optionally locked, which is
    the state a retroactive repricing has to reason about."""
    base = setup_approved_claim(
        claimed_amount_cents, program_overrides, dealer_overrides,
        delivery_overrides, rules,
    )
    overrides = dict(batch_overrides or {})
    overrides.setdefault("region_code", base["dealer"]["region_code"])
    batch = open_batch(**overrides)
    schedule_claims(batch["id"], [base["claim"]["id"]])
    if lock:
        lock_batch(batch["id"])
    base["batch"] = read_batch(batch["id"])
    base["claim"] = read_claim(base["claim"]["id"])
    return base


def setup_stair_step_objective(historical_volume_units: int = 4,
                               market_opportunity_bps: int = 0,
                               tier_schedule=None,
                               tier_bonus_mode: str = "MARGINAL",
                               validated_units: int = 0,
                               program_overrides: dict = None,
                               rules=None) -> dict:
    """An ACTIVE DEALER_STAIR_STEP program with one objective assigned to a
    dealer, and `validated_units` VALIDATED deliveries credited to it."""
    payload = f.create_stair_step_program_payload(**(program_overrides or {}))
    if tier_schedule is not None:
        payload["tier_schedule"] = tier_schedule
    payload["tier_bonus_mode"] = tier_bonus_mode
    program = create_active_program(payload=payload, rules=rules)
    dealer = register_dealer(
        historical_volume_units=historical_volume_units,
        market_opportunity_bps=market_opportunity_bps,
    )
    objective = assign_objective(program["id"], dealer["id"])
    deliveries = []
    for _ in range(validated_units):
        deliveries.append(report_and_validate_delivery(dealer["id"]))
    return {
        "program": read_program(program["id"]),
        "dealer": read_dealer(dealer["id"]),
        "objective": read_objective(objective["id"]),
        "deliveries": deliveries,
    }
