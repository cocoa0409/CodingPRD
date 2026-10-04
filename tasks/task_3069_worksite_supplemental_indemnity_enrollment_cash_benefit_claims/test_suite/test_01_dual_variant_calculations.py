"""The two payable variants and the two proration variants diverge in pinned ways."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import assert_payroll_cycle
from test_helpers.factories import benefit_item_payload
from test_helpers.test_users import make_group_admin_headers


def _payroll_pair(client):
    """One DAILY group and one HALF_MONTH group, each with one issued policy against
    a 9999-cent-premium series, each with a finalized September cycle."""
    series_bundle = fixtures.create_active_series(
        client,
        schedule_overrides={
            "monthly_premium_cents": 9999,
            "wellness_benefit_cents": 1000,
        },
        benefit_items=[
            benefit_item_payload(
                event_code="WELLNESS_SCREEN",
                benefit_amount_cents=100,
                max_occurrences_per_year=12,
                lifetime_max_cents=100000,
            )
        ],
    )
    groups = {}
    for key, convention in (("daily", "DAILY"), ("half", "HALF_MONTH")):
        # One counselor per campaign: identical default windows would otherwise
        # double-book a single counselor under the closed-interval rule.
        counselor = fixtures.create_counselor(client)
        group = fixtures.create_active_group(client, proration_convention=convention)
        campaign = fixtures.create_campaign(client, group["id"], counselor)
        fixtures.open_campaign(client, campaign["id"], counselor)
        employee = fixtures.create_employee(client, group["id"])
        policy = fixtures.apply_policy(
            client, campaign["id"], employee["id"],
            series_bundle.series["id"], counselor,
        )
        fixtures.issue_policy(client, policy["id"], counselor)
        cycle = fixtures.create_payroll_cycle(client, group["id"])
        fixtures.finalize_payroll_cycle(client, cycle["id"])
        groups[key] = cycle["id"]
    return groups


def test_final_payable_drops_below_provisional_when_a_competing_claim_pays_first(client):
    """The final adjudication re-reads counters that a competing payment moved.

    "The final variant re-evaluates the identical formula at the adjudication
    instant; if paid counters advanced since review — another claim paid in
    between — the final amount can be lower than the provisional one, and only
    the final value, stored in `payable_amount_cents`, ever posts to the ledger."

    Design: Difficulty/dual_variant_calc/claim_payable_provisional_vs_final_diverge_when_counters_advance
    """
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="HOSP_CONFINEMENT",
                benefit_amount_cents=20000,
                max_occurrences_per_year=2,
                lifetime_max_cents=1000000,
            )
        ],
    )
    claim_a = fixtures.submit_claim(
        client, base.policy["id"], "HOSP_CONFINEMENT",
        service_date="2026-09-10T00:00:00Z", diagnosis_code="S82.001A",
        claimed_occurrences=1,
    )
    fixtures.review_claim(client, claim_a["id"])
    fixtures.approve_claim_with_document(client, claim_a["id"])

    claim_b = fixtures.submit_claim(
        client, base.policy["id"], "HOSP_CONFINEMENT",
        service_date="2026-09-11T00:00:00Z", diagnosis_code="S82.001A",
        claimed_occurrences=2,
    )
    reviewed_b = fixtures.review_claim(client, claim_b["id"])
    assert reviewed_b["provisional_payable_cents"] == 40000, (
        "provisional computed before claim A pays: min(2, 2-0)*20000 = 40000; got %r"
        % reviewed_b.get("provisional_payable_cents")
    )

    # Document claim B while it is UNDER_REVIEW, then pay claim A in between.
    document_b = fixtures.attach_document(client, claim_b["id"], doc_type="DIAGNOSIS_PROOF")
    fixtures.accept_document(client, document_b["id"])
    fixtures.pay_claim(client, claim_a["id"])

    final_b = fixtures.adjudicate_claim(client, claim_b["id"], "APPROVE")
    assert final_b["provisional_payable_cents"] == 40000
    assert final_b["adjudicated_occurrences"] == 1, (
        "final credits min(2, 2-1) = 1 occurrence; got %r"
        % final_b.get("adjudicated_occurrences")
    )
    assert final_b["payable_amount_cents"] == 20000, (
        "final = min(1*20000, 1000000-20000) = 20000; got %r"
        % final_b.get("payable_amount_cents")
    )
    assert final_b["payable_amount_cents"] < final_b["provisional_payable_cents"]


def test_only_the_final_amount_posts_to_the_policy_ledger(client):
    """A claim approved at 20000 after a 40000 provisional posts exactly 20000.

    "The occurrences credited are the smaller of `claimed_occurrences` and the
    remaining occurrences; the uncapped amount is the per-occurrence benefit times
    the credited occurrences; and the payable amount is the smaller of that
    uncapped amount and the remaining lifetime. Only `PAID` claims feed the
    counters — approved-but-unpaid claims are invisible to both variants."

    Design: Difficulty/dual_variant_calc/claim_payable_provisional_vs_final_diverge_when_counters_advance
    """
    base = fixtures.setup_active_policy(
        client,
        benefit_items=[
            benefit_item_payload(
                event_code="HOSP_CONFINEMENT",
                benefit_amount_cents=20000,
                max_occurrences_per_year=2,
                lifetime_max_cents=1000000,
            )
        ],
    )
    claim_a = fixtures.submit_claim(
        client, base.policy["id"], "HOSP_CONFINEMENT",
        service_date="2026-09-10T00:00:00Z", diagnosis_code="S82.001A",
        claimed_occurrences=1,
    )
    fixtures.review_claim(client, claim_a["id"])
    fixtures.approve_claim_with_document(client, claim_a["id"])

    claim_b = fixtures.submit_claim(
        client, base.policy["id"], "HOSP_CONFINEMENT",
        service_date="2026-09-11T00:00:00Z", diagnosis_code="S82.001A",
        claimed_occurrences=2,
    )
    fixtures.review_claim(client, claim_b["id"])
    document_b = fixtures.attach_document(client, claim_b["id"], doc_type="DIAGNOSIS_PROOF")
    fixtures.accept_document(client, document_b["id"])
    fixtures.pay_claim(client, claim_a["id"])
    fixtures.adjudicate_claim(client, claim_b["id"], "APPROVE")

    # Approval does not post: the ledger shows only claim A's 20000 until B is paid.
    policy_mid = fixtures.read_policy(client, base.policy["id"])
    assert policy_mid["lifetime_paid_cents"] == 20000
    assert policy_mid["paid_occurrences_by_year"]["2026"]["HOSP_CONFINEMENT"] == 1

    fixtures.pay_claim(client, claim_b["id"])
    policy_final = fixtures.read_policy(client, base.policy["id"])
    assert policy_final["lifetime_paid_cents"] == 40000, (
        "ledger = 20000 (A) + 20000 (B's final, not its 40000 provisional); got %r"
        % policy_final.get("lifetime_paid_cents")
    )
    assert policy_final["paid_occurrences_by_year"]["2026"]["HOSP_CONFINEMENT"] == 2


def test_daily_and_half_month_conventions_diverge_on_an_odd_premium(client):
    """The same full-month bill lands on 9999 or 10000 purely from rounding order.

    "Because billability is all-or-nothing, both variants charge the full-period
    amount for a billable policy and zero otherwise; the variants diverge on the
    rounding itself — for a premium of 9999 cents, the daily convention yields 9999
    for a full period while the half-month convention rounds 4999.5 up to 5000 per
    bucket and yields 10000."

    Design: Difficulty/dual_variant_calc/deduction_proration_daily_vs_half_month_rounding_diverge
    """
    cycles = _payroll_pair(client)

    daily_lines = validate_success(
        client.list_cycle_deduction_lines(cycles["daily"], make_group_admin_headers()), 200
    )
    half_lines = validate_success(
        client.list_cycle_deduction_lines(cycles["half"], make_group_admin_headers()), 200
    )
    assert len(daily_lines) == 1 and len(half_lines) == 1

    daily_line = daily_lines[0]
    half_line = half_lines[0]
    assert daily_line["amount_cents"] == 9999, (
        "DAILY full period: round_half_up(9999 * 30 / 30) = 9999; got %r"
        % daily_line.get("amount_cents")
    )
    assert daily_line["coverage_days"] == 30
    assert half_line["amount_cents"] == 10000, (
        "HALF_MONTH full period: round_half_up(9999/2)*2 = 5000*2 = 10000; got %r"
        % half_line.get("amount_cents")
    )
    assert half_line["coverage_days"] == 30


def test_cycle_totals_follow_the_rounded_line_amounts(client):
    """Each cycle total is the sum of its lines' rounded amounts, nothing else.

    "Following §2.8, every line is rounded before any summing, and the cycle's
    `total_posted_cents` is the sum of `amount_cents` over its `POSTED` lines."

    Design: Difficulty/dual_variant_calc/deduction_proration_daily_vs_half_month_rounding_diverge
    """
    cycles = _payroll_pair(client)

    daily_cycle = validate_success(
        client.get_payroll_cycle(cycles["daily"], make_group_admin_headers()), 200
    )
    half_cycle = validate_success(
        client.get_payroll_cycle(cycles["half"], make_group_admin_headers()), 200
    )
    assert_payroll_cycle(daily_cycle)
    assert_payroll_cycle(half_cycle)
    assert daily_cycle["total_posted_cents"] == 9999
    assert half_cycle["total_posted_cents"] == 10000
    assert daily_cycle["status"] == "FINALIZED"
    assert half_cycle["status"] == "FINALIZED"
