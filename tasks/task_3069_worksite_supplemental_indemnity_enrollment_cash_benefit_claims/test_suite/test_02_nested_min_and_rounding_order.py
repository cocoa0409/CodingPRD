"""Nested-minimum payable selection and round-per-line-then-sum payroll aggregation."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import make_group_admin_headers


def _lifetime_gate_scenario(client):
    """One policy with 90000 of a 100000 lifetime already paid, plus a documented
    claim under review asking for 2 occurrences x 30000."""
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="ICU_DAY",
                benefit_amount_cents=30000,
                max_occurrences_per_year=10,
                lifetime_max_cents=100000,
            )
        ],
        schedule_overrides={"monthly_premium_cents": 4000},
    )
    prior = fixtures.submit_claim(
        client, base.policy["id"], "ICU_DAY",
        service_date="2026-09-05T00:00:00Z", diagnosis_code="J96.00",
        claimed_occurrences=3,
    )
    fixtures.pay_claim_full_cycle(client, prior["id"])

    claim = fixtures.submit_claim(
        client, base.policy["id"], "ICU_DAY",
        service_date="2026-09-20T00:00:00Z", diagnosis_code="J96.00",
        claimed_occurrences=2,
    )
    reviewed = fixtures.review_claim(client, claim["id"])
    document = fixtures.attach_document(client, claim["id"], doc_type="DIAGNOSIS_PROOF")
    fixtures.accept_document(client, document["id"])
    return base, reviewed


def _three_line_cycle(client):
    """HALF_MONTH group with three issued 3333-premium policies and one finalized
    September cycle."""
    base = fixtures.setup_open_campaign(
        client,
        group_overrides={"proration_convention": "HALF_MONTH"},
        schedule_overrides={"monthly_premium_cents": 3333},
        benefit_items=[
            benefit_item_payload(
                event_code="SCREENING",
                benefit_amount_cents=5000,
                max_occurrences_per_year=4,
                lifetime_max_cents=500000,
            )
        ],
    )
    for _ in range(3):
        employee = fixtures.create_employee(client, base.group["id"])
        policy = fixtures.apply_policy(
            client, base.campaign["id"], employee["id"], base.series["id"],
            base.counselor,
        )
        fixtures.issue_policy(client, policy["id"], base.counselor)
    cycle = fixtures.create_payroll_cycle(client, base.group["id"])
    fixtures.finalize_payroll_cycle(client, cycle["id"])
    return cycle


def test_approval_alone_posts_nothing_to_the_ledger(client):
    """An approved-but-unpaid claim leaves the paid counters exactly where they were.

    "Only `PAID` claims feed the counters — approved-but-unpaid claims are
    invisible to both variants."

    Design: Difficulty/combinatorial_formula/claim_payable_three_input_nested_min_cap_selection
    """
    base, reviewed = _lifetime_gate_scenario(client)
    fixtures.adjudicate_claim(client, reviewed["id"], "APPROVE")

    policy = fixtures.read_policy(client, base.policy["id"])
    assert policy["lifetime_paid_cents"] == 90000, (
        "approval does not post; only pay posts; got %r"
        % policy.get("lifetime_paid_cents")
    )
    assert policy["paid_occurrences_by_year"]["2026"]["ICU_DAY"] == 3

    fixtures.pay_claim(client, reviewed["id"])
    policy = fixtures.read_policy(client, base.policy["id"])
    assert policy["lifetime_paid_cents"] == 100000
    assert policy["paid_occurrences_by_year"]["2026"]["ICU_DAY"] == 5


def test_cycle_total_rounds_each_line_before_summing(client):
    """Three half-month lines of 3334 each sum to 10002, not 9999.

    "Payroll deduction proration is the one place where rounding occurs, and its
    order of operations is pinned: each deduction line's `amount_cents` is rounded
    half-up to whole cents at line level first, and only then are line amounts
    summed into the cycle's `total_posted_cents`. The system never sums unrounded
    values and rounds once at the end."

    Design: Difficulty/combinatorial_formula/payroll_cycle_total_rounds_per_line_then_sums
    """
    cycle = _three_line_cycle(client)

    lines = validate_success(
        client.list_cycle_deduction_lines(cycle["id"], make_group_admin_headers()), 200
    )
    assert len(lines) == 3, "expected one line per billable policy; got %d" % len(lines)
    for line in lines:
        assert line["amount_cents"] == 3334, (
            "round_half_up(3333/2)*2 = 1667*2 = 3334; got %r" % line.get("amount_cents")
        )
        assert line["status"] == "POSTED"

    reloaded = validate_success(
        client.get_payroll_cycle(cycle["id"], make_group_admin_headers()), 200
    )
    assert reloaded["status"] == "FINALIZED"
    assert reloaded["total_posted_cents"] == 10002, (
        "3 * 3334 = 10002; a sum-then-round implementation would report 9999; got %r"
        % reloaded.get("total_posted_cents")
    )


def test_each_line_is_individually_rounded_to_whole_cents(client):
    """Every synthesized line of the 3333-premium cycle carries the same 3334.

    "Under `HALF_MONTH`, each half-month bucket is rounded first: half the premium
    is rounded half-up to whole cents per bucket, then multiplied by the number of
    buckets — two buckets when the coverage spans the full period, one when it
    spans a positive partial period, and zero when there is no coverage."

    Design: Difficulty/combinatorial_formula/payroll_cycle_total_rounds_per_line_then_sums
    """
    cycle = _three_line_cycle(client)

    lines = validate_success(
        client.list_cycle_deduction_lines(cycle["id"], make_group_admin_headers()), 200
    )
    amounts = sorted(line["amount_cents"] for line in lines)
    assert amounts == [3334, 3334, 3334]
    for line in lines:
        assert line["coverage_days"] == 30
        assert line["tax_treatment"] == "POST_TAX"
