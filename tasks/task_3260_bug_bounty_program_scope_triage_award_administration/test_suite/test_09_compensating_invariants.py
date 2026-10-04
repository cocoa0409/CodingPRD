"""Difficulty tests: compensating invariants — pool conservation and conduct reversal."""
from test_helpers import assert_pool_ledger_conserved, get_success_data, validate_success
from test_helpers.fixtures import (
    PLATFORM_ADMIN,
    PROGRAM_ADMIN,
    TRIAGER,
    approve_award,
    create_award,
    create_validated_report,
    get_program,
    get_researcher,
    register_researcher,
    set_clock,
    setup_active_program,
    submit_tax_document,
    verify_tax_document,
)


def test_pool_conservation_across_approve_void_pay(api):
    """PRD §2.6: "Each program maintains a three-part pool ledger.
    `bounty_pool_cents` is the total budget declared by the customer.
    `bounty_reserved_cents` is the sum of `amount_cents` across all awards of that
    program in `APPROVED` or `BLOCKED` status — funds committed but not yet
    disbursed. `bounty_paid_cents` is the sum of the gross `amount_cents` across
    awards in `PAID` status. The derived `available_pool_cents` is the pool minus
    reserved minus paid, and it bounds both award computation and award
    approval."

    Design: Difficulty/compensating_invariant/award_approve_pay_void_pool_conservation
    """
    program, asset = setup_active_program(bounty_pool_cents=5_000_000)
    researcher = register_researcher()
    submit_tax_document(researcher, document_type="W9")
    verify_tax_document(researcher)  # VERIFIED + US -> 0% withholding
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    award1 = create_award(report["id"], "BOUNTY")
    # CRITICAL/CRITICAL raw 2000000 + first-report bonus 200000 = 2200000
    assert award1["amount_cents"] == 2_200_000
    approve_award(award1["id"])
    after_approve = get_program(program["id"])
    assert after_approve["bounty_reserved_cents"] == 2_200_000
    assert after_approve["available_pool_cents"] == 2_800_000
    assert_pool_ledger_conserved(after_approve)
    # Void releases the reservation (compensation)
    get_success_data(api.void_award(award1["id"], PROGRAM_ADMIN))
    after_void = get_program(program["id"])
    assert after_void["bounty_reserved_cents"] == 0
    assert after_void["bounty_paid_cents"] == 0
    assert_pool_ledger_conserved(after_void)
    # A subsequent approve+pay of a 10000 BONUS settles with zero drift
    award2 = create_award(report["id"], "BONUS", amount_cents=10_000)
    approve_award(award2["id"])
    get_success_data(api.pay_award(award2["id"], PLATFORM_ADMIN))
    final = get_program(program["id"])
    assert final["bounty_reserved_cents"] == 0
    assert final["bounty_paid_cents"] == 10_000
    assert final["total_withheld_cents"] == 0
    assert final["available_pool_cents"] == 4_990_000
    assert_pool_ledger_conserved(final)


def test_pool_ledger_counter_semantics(api):
    """PRD §3.9: "On approval the award's `amount_cents` is added to the
    program's `bounty_reserved_cents`, `approved_at` is stamped, and
    `available_pool_cents` is recomputed."
    PRD §3.9: "Voiding an `APPROVED` award releases its reservation: the amount
    is subtracted from `bounty_reserved_cents` as compensation."

    Design: Difficulty/compensating_invariant/award_approve_pay_void_pool_conservation
    """
    program, asset = setup_active_program(bounty_pool_cents=5_000_000)
    researcher = register_researcher()
    submit_tax_document(researcher, document_type="W9")
    verify_tax_document(researcher)
    report = create_validated_report(
        program, asset, researcher, impact=9, exploitability=8, affected_scope=5,
        vulnerability_class="RCE")
    award1 = create_award(report["id"], "BOUNTY")
    approve_award(award1["id"])
    get_success_data(api.void_award(award1["id"], PROGRAM_ADMIN))
    award2 = create_award(report["id"], "BONUS", amount_cents=10_000)
    approve_award(award2["id"])
    get_success_data(api.pay_award(award2["id"], PLATFORM_ADMIN))
    final = get_program(program["id"])
    assert final["bounty_reserved_cents"] == 0
    assert final["bounty_paid_cents"] == 10_000
    assert final["available_pool_cents"] == 4_990_000


def test_conduct_reverse_last_restores_reputation_and_standing(api):
    """PRD §3.3: "`REVERSE_LAST` sets `reversed` to true on the latest unreversed
    log entry, undoes its delta exactly, and recomputes standing: a suspended
    researcher whose unreversed strike count drops below 2 — with no unreversed
    ban — returns to `ACTIVE` with `suspension_ends_at` cleared to null."
    PRD §3.3: "A `STRIKE` increments `strike_count` and applies −50; when the
    strike brings the unreversed strike count to exactly 2 the researcher is
    suspended"

    Design: Difficulty/compensating_invariant/conduct_reverse_restores_reputation_invariant
    """
    set_clock("2026-09-01T00:00:00Z")
    researcher = register_researcher()
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "one"}, TRIAGER))
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "two"}, TRIAGER))
    suspended = get_researcher(researcher["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["strike_count"] == 2
    assert suspended["reputation_lifetime"] == 0
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "REVERSE_LAST", "reason": "appeal upheld"},
        PROGRAM_ADMIN))
    after_first = get_researcher(researcher["id"])
    assert after_first["strike_count"] == 1
    assert after_first["status"] == "ACTIVE"  # below the 2-strike threshold
    assert after_first["reputation_lifetime"] == 50


def test_conduct_reverse_last_twice_restores_zero_drift(api):
    """PRD §3.3: "`REVERSE_LAST` sets `reversed` to true on the latest unreversed
    log entry, undoes its delta exactly, and recomputes standing: a suspended
    researcher whose unreversed strike count drops below 2 — with no unreversed
    ban — returns to `ACTIVE` with `suspension_ends_at` cleared to null."
    PRD §3.3: "`reputation_lifetime` is 100 plus the sum of all unreversed
    deltas, floored at zero"

    Design: Difficulty/compensating_invariant/conduct_reverse_restores_reputation_invariant
    """
    set_clock("2026-09-01T00:00:00Z")
    researcher = register_researcher()
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "one"}, TRIAGER))
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "STRIKE", "reason": "two"}, TRIAGER))
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "REVERSE_LAST", "reason": "appeal upheld"},
        PROGRAM_ADMIN))
    get_success_data(api.conduct_action(
        researcher["id"], {"action": "REVERSE_LAST", "reason": "second appeal upheld"},
        PROGRAM_ADMIN))
    restored = get_researcher(researcher["id"])
    assert restored["reputation_lifetime"] == 100
    assert restored["strike_count"] == 0
    assert restored["status"] == "ACTIVE"
    assert restored["suspension_ends_at"] is None
