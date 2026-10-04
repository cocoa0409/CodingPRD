"""Financing plans: annuity constant, OCC, live-plan uniqueness, and the
delinquency/cure cycle driven by production-day closes.

Covers PRD §3.2 (financing lifecycle, interest-first payments, delinquency),
§2.7 (OCC on agreement version), and §2.9 (account standing).
Instances:
Difficulty/non_linear_state_machine/financing_delinquency_cure_cycle_via_close,
Difficulty/transitive_cascade/production_close_delinquency_standing_cascade,
Corner/calculations/weekly_payment_annuity_constant_pinned,
Corner/errors/second_plan_with_live_plan_rejected,
Corner/cross_cutting_complexity_layers/occ_plan_create_stale_then_fresh_supersedes.
"""
from test_helpers import (
    FINANCED_AMOUNT_CENTS,
    FINANCING_WEEKLY_PAYMENT_CENTS,
    ApiErrorId,
    TEST_USERS,
    api_client,
    claim_item,
    close_production_day,
    create_bakery,
    create_distributor,
    create_draft_agreement,
    create_financing_plan,
    create_financing_plan_payload,
    create_listed_territory,
    create_production_day,
    create_stale_claim,
    disburse_financing_plan,
    financing_payment_payload,
    find_financing_plan,
    get_agreement,
    get_distributor,
    list_financing_plans,
    list_stale_claims,
    make_distributor_headers,
    order_line,
    reset_clock_to_default,
    set_clock,
    setup_active_financed_agreement,
    setup_delivered_order,
    validate_error,
    validate_success,
)

_CREDIT = TEST_USERS["credit_analyst_headers"]


def _draft_financed_agreement():
    """DRAFT financed agreement (financed 52000) with one DRAFT plan."""
    reset_clock_to_default()
    bakery = create_bakery()
    territory = create_listed_territory()
    distributor = create_distributor()
    agreement = create_draft_agreement(
        territory["id"],
        distributor["id"],
        bakery["id"],
        financed_amount_cents=FINANCED_AMOUNT_CENTS,
    )
    plan = create_financing_plan(agreement, principal_cents=FINANCED_AMOUNT_CENTS)
    return bakery, territory, distributor, agreement, plan


def test_close_flags_delinquent_plan_and_watch_standing(api):
    """PRD §3.2: "The scheduled amount due is the lesser of the weeks elapsed
    and `term_weeks`, multiplied by `weekly_payment_cents`. The plan is
    delinquent when `total_paid_cents` is strictly less than the scheduled due
    minus one weekly payment; that subtraction builds one weekly payment of
    grace into the test."
    PRD §2.9: "otherwise it is `WATCH` whenever any of the distributor's
    financing plans is `DELINQUENT`; otherwise it is `GOOD`."

    Design: Difficulty/non_linear_state_machine/financing_delinquency_cure_cycle_via_close
    """
    ctx = setup_active_financed_agreement()
    day = create_production_day(ctx["bakery"]["id"], "2026-09-16")
    set_clock("2026-09-16T08:00:00Z")
    close_production_day(day["id"])
    plan = find_financing_plan(ctx["agreement"]["id"], ctx["plan"]["id"])
    assert plan["status"] == "DELINQUENT", (
        "disbursed 2026-09-01, closed 2026-09-16: 2 weeks elapsed, scheduled "
        "10510, paid 0 < 10510 - 5255 grace"
    )
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["account_standing"] == "WATCH"


def test_payment_cures_delinquency_at_next_close(api):
    """PRD §3.2: "Each payment applies interest-first: the interest portion is
    the outstanding principal multiplied by the weekly rate, rounded half-up to
    whole cents, and a payment smaller than that interest portion is rejected
    with `ERR_PAYMENT_BELOW_INTEREST`. Otherwise the principal portion is the
    lesser of the amount remaining after interest and the outstanding
    principal..."
    PRD §3.2: "a passing result cures `DELINQUENT → ACTIVE`, or keeps an active
    plan active. Either recomputation refreshes the distributor's
    `account_standing` and advances the distributor's `version`."

    Design: Difficulty/non_linear_state_machine/financing_delinquency_cure_cycle_via_close
    """
    ctx = setup_active_financed_agreement()
    day = create_production_day(ctx["bakery"]["id"], "2026-09-16")
    set_clock("2026-09-16T08:00:00Z")
    close_production_day(day["id"])
    plan = find_financing_plan(ctx["agreement"]["id"], ctx["plan"]["id"])
    assert plan["status"] == "DELINQUENT"

    resp = api_client.record_financing_payment(
        plan["id"],
        financing_payment_payload(10510),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    paid_plan = validate_success(resp)
    # interest-first: interest round_half_up(52000 * 0.10/52) == 100,
    # principal 10510 - 100 == 10410.
    assert paid_plan["outstanding_principal_cents"] == 41590
    assert paid_plan["total_paid_cents"] == 10510

    day2 = create_production_day(ctx["bakery"]["id"], "2026-09-17")
    set_clock("2026-09-17T08:00:00Z")
    close_production_day(day2["id"])
    plan = find_financing_plan(ctx["agreement"]["id"], ctx["plan"]["id"])
    assert plan["status"] == "ACTIVE", (
        "paid 10510 >= scheduled 10510 - grace 5255 cures the delinquency"
    )
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["account_standing"] == "GOOD"


def _setup_close_cascade_context():
    """Financed agreement disbursed 2026-08-28 with no payments; WHT-24 x5
    delivered 2026-09-01; a SUBMITTED stale claim filed 2026-09-06; an open
    production day for 2026-09-16 with the clock at 2026-09-16."""
    ctx = setup_active_financed_agreement(clock="2026-08-28T00:00:00Z")
    setup_delivered_order(ctx, "2026-09-01", [order_line("WHT-24", 5)])
    set_clock("2026-09-06T09:00:00Z")
    claim = create_stale_claim(
        ctx["distributor"],
        [claim_item("WHT-24", "2026-09-01", 1, "2026-09-06")],
    )
    day_close = create_production_day(ctx["bakery"]["id"], "2026-09-16")
    set_clock("2026-09-16T08:00:00Z")
    return ctx, claim, day_close


def test_close_cascades_delinquency_to_standing(api):
    """PRD §3.3: "The close is a system-wide checkpoint rather than a
    bookkeeping formality: it runs the financing delinquency and cure
    evaluation of §3.2 across every `ACTIVE` or `DELINQUENT` plan, and it
    auto-expires unanswered stale claims as described in §3.6."
    PRD §3.2: "A delinquent result moves the plan `ACTIVE → DELINQUENT`, or
    keeps a delinquent plan delinquent..."

    Design: Difficulty/transitive_cascade/production_close_delinquency_standing_cascade
    """
    ctx, _claim, day_close = _setup_close_cascade_context()
    closed = close_production_day(day_close["id"])
    assert closed["status"] == "CLOSED"
    plan = find_financing_plan(ctx["agreement"]["id"], ctx["plan"]["id"])
    assert plan["status"] == "DELINQUENT", (
        "disbursed 2026-08-28, closed 2026-09-16: 19 days -> 2 weeks elapsed, "
        "scheduled 10510, paid 0 < 10510 - 5255 grace"
    )
    distributor = get_distributor(ctx["distributor"]["id"])
    assert distributor["account_standing"] == "WATCH", (
        "standing recomputed because the plan became DELINQUENT"
    )


def test_close_auto_expires_stale_claim(api):
    """PRD §3.6: "Claims also die of old age: when a production day closes,
    every claim still sitting in `SUBMITTED` or `NEEDS_INFO` that was created
    more than three days before the close date is denied automatically with
    `denial_reason` `AUTO_EXPIRED`."

    Design: Difficulty/transitive_cascade/production_close_delinquency_standing_cascade
    """
    ctx, claim, day_close = _setup_close_cascade_context()
    close_production_day(day_close["id"])
    current = [
        c for c in list_stale_claims(ctx["distributor"]["id"])
        if c["id"] == claim["id"]
    ][0]
    assert current["status"] == "DENIED"
    assert current["denial_reason"] == "AUTO_EXPIRED", (
        "claim created 2026-09-06, close date 2026-09-16: 10 days > 3"
    )


def test_weekly_payment_annuity_constant_pinned(api):
    """PRD §3.2: "first divide `annual_interest_rate` by 52 to obtain the
    weekly rate; then form the discount factor by adding one to the weekly
    rate, raising that sum to the power of negative `term_weeks`, and
    subtracting the result from one; the weekly payment is `principal_cents`
    multiplied by the weekly rate and divided by that discount factor, rounded
    half-up to whole cents."
    PRD §3.2: "Disbursement stamps `disburse_date` with the current logical
    date, seeds `outstanding_principal_cents` equal to `principal_cents`, and
    computes the level-annuity `weekly_payment_cents`..."

    Design: Corner/calculations/weekly_payment_annuity_constant_pinned
    """
    ctx = setup_active_financed_agreement()
    plan = find_financing_plan(ctx["agreement"]["id"], ctx["plan"]["id"])
    assert plan["weekly_payment_cents"] == FINANCING_WEEKLY_PAYMENT_CENTS == 5255
    assert plan["disburse_date"] == "2026-09-01"
    assert plan["outstanding_principal_cents"] == FINANCED_AMOUNT_CENTS == 52000
    assert plan["status"] == "ACTIVE"
    assert plan["total_paid_cents"] == 0


def test_second_plan_with_live_plan_rejected(api):
    """PRD §3.2: "Only one live plan may exist: creation is rejected with
    `ERR_FINANCING_PLAN_EXISTS` when the agreement already holds a plan in any
    status other than `DRAFT` or `SUPERSEDED`."

    Design: Corner/errors/second_plan_with_live_plan_rejected
    """
    _, _, _, agreement, plan = _draft_financed_agreement()
    disburse_financing_plan(plan["id"])
    agreement_now = get_agreement(agreement["id"])
    assert agreement_now["version"] == 2, "create 1, plan creation 2"
    resp = api_client.create_financing_plan(
        agreement["id"],
        create_financing_plan_payload(agreement_now["version"]),
        _CREDIT,
    )
    validate_error(resp, ApiErrorId.ERR_FINANCING_PLAN_EXISTS)
    plans = list_financing_plans(agreement["id"])
    assert len(plans) == 1
    assert plans[0]["status"] == "ACTIVE"
    assert get_agreement(agreement["id"])["version"] == 2, (
        "the rejected creation did not advance the agreement version"
    )


def test_occ_plan_create_stale_then_fresh_supersedes(api):
    """PRD §2.7: "A successful plan creation legitimately supersedes any prior
    draft plan and advances the agreement's `version` by one, so a creation
    carrying a value that no longer equals the agreement's current `version` is
    acting on a superseded view of the agreement and is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "When a prior plan is still in `DRAFT`, the new plan supersedes
    it — the older plan moves `DRAFT → SUPERSEDED` — and the agreement's
    `version` advances by one."

    Design: Corner/cross_cutting_complexity_layers/occ_plan_create_stale_then_fresh_supersedes
    """
    _, _, _, agreement, plan1 = _draft_financed_agreement()
    stale_version = agreement["version"]
    assert stale_version == 1

    resp = api_client.create_financing_plan(
        agreement["id"],
        create_financing_plan_payload(stale_version),
        _CREDIT,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = get_agreement(agreement["id"])["version"]
    assert fresh_version == 2
    resp2 = api_client.create_financing_plan(
        agreement["id"],
        create_financing_plan_payload(
            fresh_version,
            financier_type="EXTERNAL_LENDER",
            lender_name="RouteCapital Finance",
        ),
        _CREDIT,
    )
    plan2 = validate_success(resp2, 201)
    assert plan2["financier_type"] == "EXTERNAL_LENDER"
    assert plan2["lender_name"] == "RouteCapital Finance"

    plan1_now = find_financing_plan(agreement["id"], plan1["id"])
    assert plan1_now["status"] == "SUPERSEDED"
    assert get_agreement(agreement["id"])["version"] == 3, (
        "create 1, plan1 create 2, plan2 create 3; the 412 attempt bumped "
        "nothing"
    )
