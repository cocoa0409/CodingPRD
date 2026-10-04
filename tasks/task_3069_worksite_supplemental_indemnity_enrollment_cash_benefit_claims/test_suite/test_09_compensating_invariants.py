"""Compensating invariants: pay/void restores the claim ledger, reverse restores
the payroll cycle total."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import (
    make_carrier_admin_headers,
    make_claims_adjuster_headers,
    make_group_admin_headers,
)


def _approved_burn_claim(client):
    """An approved 2-occurrence BURN claim (payable 16000) on an issued policy."""
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="BURN",
                benefit_amount_cents=8000,
                max_occurrences_per_year=3,
                lifetime_max_cents=500000,
            )
        ],
    )
    claim = fixtures.submit_claim(
        client, base.policy["id"], "BURN",
        service_date="2026-09-04T00:00:00Z", diagnosis_code="T22.001A",
        claimed_occurrences=2,
    )
    fixtures.review_claim(client, claim["id"])
    fixtures.approve_claim_with_document(client, claim["id"])
    return base, claim


def test_voiding_a_paid_claim_restores_the_ledger_exactly(client):
    """Pay adds 16000 and two occurrences; voiding the paid claim removes both.

    "Two invariants are maintained at all times: `lifetime_paid_cents` always
    equals the sum over the policy's non-voided paid claims, and each yearly
    occurrence counter always equals the occurrences credited by those same
    claims. Paying a claim increments both; voiding a paid claim decrements both
    by exactly the amount and occurrences that claim contributed."

    Design: Difficulty/compensating_invariant/claim_pay_then_void_restores_policy_lifetime_paid
    """
    base, claim = _approved_burn_claim(client)

    fixtures.pay_claim(client, claim["id"])
    paid_policy = fixtures.read_policy(client, base.policy["id"])
    assert paid_policy["lifetime_paid_cents"] == 16000
    assert paid_policy["paid_occurrences_by_year"]["2026"]["BURN"] == 2

    voided = validate_success(
        client.void_claim(claim["id"], make_claims_adjuster_headers()), 200
    )
    assert voided["status"] == "VOIDED"

    restored = fixtures.read_policy(client, base.policy["id"])
    assert restored["lifetime_paid_cents"] == 0, (
        "the compensating reversal restores zero; got %r"
        % restored.get("lifetime_paid_cents")
    )
    assert restored["paid_occurrences_by_year"].get("2026", {}).get("BURN", 0) == 0


def test_ledger_counters_track_only_non_voided_paid_claims(client):
    """After the pay/void pair, the counters equal the sum over non-voided PAID rows.

    "`lifetime_paid_cents` is the sum of `payable_amount_cents` over the policy's
    claims whose status is `PAID` — and only those: claims that are approved but
    not yet paid do not consume capacity, and voided claims are compensated back
    out. `paid_occurrences_by_year` is a map from calendar year to event code to
    the number of occurrences paid, again over `PAID` claims only."

    Design: Difficulty/compensating_invariant/claim_pay_then_void_restores_policy_lifetime_paid
    """
    base, claim = _approved_burn_claim(client)
    policy = fixtures.read_policy(client, base.policy["id"])
    assert policy["lifetime_paid_cents"] == 0, "the ledger starts at zero"
    assert policy["paid_occurrences_by_year"].get("2026", {}).get("BURN", 0) == 0

    fixtures.pay_claim(client, claim["id"])
    mid = fixtures.read_policy(client, base.policy["id"])
    assert mid["lifetime_paid_cents"] == 16000

    fixtures.void_claim(client, claim["id"])
    final = fixtures.read_policy(client, base.policy["id"])
    assert final["lifetime_paid_cents"] == 0
    assert final["paid_occurrences_by_year"].get("2026", {}).get("BURN", 0) == 0


def _finalized_two_line_cycle(client):
    """A DAILY group with two issued 3000-premium policies and a FINALIZED
    September cycle (two lines, total 6000)."""
    base = fixtures.setup_open_campaign(
        client,
        group_overrides={"proration_convention": "DAILY"},
        schedule_overrides={"monthly_premium_cents": 3000},
        benefit_items=[
            benefit_item_payload(
                event_code="W",
                benefit_amount_cents=100,
                max_occurrences_per_year=12,
                lifetime_max_cents=100000,
            )
        ],
    )
    for _ in range(2):
        employee = fixtures.create_employee(client, base.group["id"])
        policy = fixtures.apply_policy(
            client, base.campaign["id"], employee["id"], base.series["id"],
            base.counselor,
        )
        fixtures.issue_policy(client, policy["id"], base.counselor)
    cycle = fixtures.create_payroll_cycle(client, base.group["id"])
    fixtures.finalize_payroll_cycle(client, cycle["id"])
    lines = validate_success(
        client.list_cycle_deduction_lines(cycle["id"], make_group_admin_headers()), 200
    )
    return base, cycle, lines


def test_reversing_a_line_compensates_the_cycle_total(client):
    """Reversal subtracts exactly the line's amount from the cycle total.

    "Reversal compensates the cycle: the line's `amount_cents` is subtracted from
    `total_posted_cents`, keeping the invariant that the cycle total always equals
    the sum over its posted lines."

    Design: Difficulty/compensating_invariant/deduction_line_reverse_restores_cycle_total
    """
    base, cycle, lines = _finalized_two_line_cycle(client)
    assert len(lines) == 2
    before = validate_success(
        client.get_payroll_cycle(cycle["id"], make_group_admin_headers()), 200
    )
    assert before["total_posted_cents"] == 6000

    reversed_line = validate_success(
        client.reverse_deduction_line(lines[0]["id"], make_group_admin_headers()), 200
    )
    assert reversed_line["status"] == "REVERSED"

    after = validate_success(
        client.get_payroll_cycle(cycle["id"], make_group_admin_headers()), 200
    )
    assert after["total_posted_cents"] == 3000


def test_lines_become_immutable_once_the_cycle_is_reconciled(client):
    """After FINALIZED the reverse path closes; RECONCILED lines cannot reverse.

    "Lines can be disputed after finalization: a `GroupAdmin` reverses a line
    (`POSTED` → `REVERSED`), which is permitted only while the cycle is
    `FINALIZED` — once reconciled or closed, lines are immutable and the attempt
    fails with `ERR_CYCLE_NOT_REVERSIBLE`."

    Design: Difficulty/compensating_invariant/deduction_line_reverse_restores_cycle_total
    """
    base, cycle, lines = _finalized_two_line_cycle(client)
    validate_success(
        client.reverse_deduction_line(lines[0]["id"], make_group_admin_headers()), 200
    )
    validate_success(
        client.reconcile_payroll_cycle(cycle["id"], make_carrier_admin_headers()), 200
    )

    response = client.reverse_deduction_line(lines[0]["id"], make_group_admin_headers())

    validate_error(response, api_errors.ERR_CYCLE_NOT_REVERSIBLE, 409)
