"""Award matching waterfall, pool ledgers, and sponsor agreements —
PRD §3.6, §3.7.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_pool_ledger_consistent,
    close_entries,
    create_corporate_sponsor,
    create_cycle,
    create_sponsor_agreement,
    find_award,
    get_agreement,
    get_cycle,
    list_cycle_awards,
    open_entries,
    publish_finalists,
    run_award_matching,
    run_semifinalist_selection,
    setup_matching_run,
    validate_error,
)

PA = TEST_USERS["program_admin_headers"]


def test_agreement_employee_children_only_defaults_true(api):
    """PRD §3.6: "employee_children_only` (default true) restricts eligibility to
    students whose `parent_sponsor_id` equals the agreement's `sponsor_id`",
    and "A new agreement is `ACTIVE`, its `supersedes_agreement_id` is null".
    
    Design: Corner/entities/agreement_employee_children_only_defaults_true
    """
    cycle = create_cycle(name="CYC-C7")
    sponsor = create_corporate_sponsor(legal_name="Acme Corp", sponsor_code="ACME")
    agreement = create_sponsor_agreement(sponsor["id"], cycle["id"])
    assert agreement["employee_children_only"] is True
    assert agreement["status"] == "ACTIVE"
    assert agreement["supersedes_agreement_id"] is None


def test_selector_tie_break_confirming_score_decides(api):
    """PRD §3.7: "Within every bucket the selector ranks candidates identically:
    `selection_index_snapshot` (the entry's `selection_index`, snapshotted
    onto the award at matching time) descending, then
    `confirming_selection_index` descending, then `submitted_at` ascending —
    never by `id`."
    
    Design: Corner/calculations/selector_tie_break_confirming_score_decides
    """
    ctx = setup_matching_run(
        student_specs=[
            {"full_name": "F Hi", "parent_sponsor": True, "scores": (37, 37, 36),
             "confirming_selection_index": 215},
            {"full_name": "F Lo", "parent_sponsor": True, "scores": (37, 37, 36),
             "confirming_selection_index": 210},
        ],
        agreement_overrides={"pool_total_cents": 250000},  # capacity exactly 1
    )
    assert ctx["matching_result"]["corporate_granted"] == 1
    awards = list_cycle_awards(ctx["cycle"]["id"])
    assert len(awards) == 1
    winner = awards[0]
    # Both finalists tie at SI 220; confirming 215 beats 210.
    assert winner["student_id"] == ctx["students"][0]["id"]
    assert winner["selection_index_snapshot"] == 220
    assert winner["category"] == "CORPORATE_SPONSORED"
    assert find_award(ctx["students"][1]["id"], ctx["cycle"]["id"]) is None


def test_denied_application_excluded_from_matching(api):
    """PRD §3.7: "Candidates are the cycle's `FINALIST_CONFIRMED` applications
    with no existing award; one award per finalist per cycle is a hard rule."
    
    Design: Corner/calculations/denied_application_excluded_from_matching
    """
    ctx = setup_matching_run(
        student_specs=[{"apply": "confirm"}, {"apply": "deny"}],
        cycle_overrides={"national_award_slots": 5},
    )
    assert ctx["matching_result"]["national_granted"] == 1
    assert ctx["matching_result"]["awards_created"] == 1
    assert find_award(ctx["students"][1]["id"], ctx["cycle"]["id"]) is None


def test_matching_rerun_rejected(api):
    """PRD §3.7: the waterfall runs "exactly once per cycle, only in
    `FINALISTS_SELECTED` posture (any other posture is
    `ERR_CYCLE_POSTURE_INVALID`), with a repeat attempt rejected as
    `ERR_MATCHING_ALREADY_RUN`", and "a bucket with no eligible candidates is
    skipped silently, without error".
    
    Design: Corner/errors/matching_rerun_rejected
    """
    cycle = create_cycle(name="CYC-E1", national_award_slots=2)
    open_entries(cycle["id"])
    close_entries(cycle["id"])
    run_semifinalist_selection(cycle["id"])
    publish_finalists(cycle["id"])
    first = run_award_matching(cycle["id"])
    assert first["awards_created"] == 0  # empty candidate set is not an error

    resp = api.run_award_matching(cycle["id"], PA)
    validate_error(resp, ApiErrorId.ERR_MATCHING_ALREADY_RUN)
    assert get_cycle(cycle["id"])["matching_run"] is True
    assert list_cycle_awards(cycle["id"]) == []


def _setup_single_offer_pool(pool_total_cents, max_awards):
    return setup_matching_run(
        student_specs=[{"parent_sponsor": True}],
        agreement_overrides={
            "award_amount_cents": 250000,
            "max_awards": max_awards,
            "pool_total_cents": pool_total_cents,
        },
    )


def test_pool_reserved_vs_cash_ledger_fields(api):
    """PRD §3.6: "The reservation ledger `pool_committed_cents` sums, over the
    pool's awards in a live recipient state (`OFFERED`, `ACCEPTED`,
    `ENROLLED`, or `RENEWED`), each award's `amount_cents` minus that award's
    already-`RELEASED` disbursement amounts. The cash ledger `pool_paid_cents`
    sums all `RELEASED` disbursement amounts the pool has funded." PRD §3.7:
    "Every grant debits its pool at offer time: `pool_committed_cents` grows
    by the award's `amount_cents` — a reservation, not yet a payment."
    
    Design: Difficulty/dual_variant_calc/sponsor_pool_reserved_vs_cash_availability
    """
    ctx = _setup_single_offer_pool(pool_total_cents=500000, max_awards=2)
    assert ctx["matching_result"]["corporate_granted"] == 1
    award = find_award(ctx["student"]["id"], ctx["cycle"]["id"])
    assert award["recipient_status"] == "OFFERED"
    assert award["funding_status"] == "PLEDGED"
    assert award["amount_cents"] == 250000
    assert award["category"] == "CORPORATE_SPONSORED"
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["pool_committed_cents"] == 250000
    assert agreement["pool_paid_cents"] == 0
    assert_pool_ledger_consistent(agreement)


def test_pool_reserved_vs_cash_diverge_while_offer_outstanding(api):
    """PRD §3.6: "pool_available_reserved_cents` is `pool_total_cents` minus
    `pool_committed_cents` minus `pool_paid_cents`, and
    `pool_available_cash_cents` is `pool_total_cents` minus `pool_paid_cents`.
    Every gate in the system — matching capacity, exhaustion evaluation,
    promotion capacity — uses the reservation variant only; the cash variant
    is reported for reconciliation and must never gate anything."
    
    Design: Difficulty/dual_variant_calc/sponsor_pool_reserved_vs_cash_availability
    """
    ctx = _setup_single_offer_pool(pool_total_cents=500000, max_awards=2)
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["pool_available_reserved_cents"] == 250000  # 500k - 250k - 0
    assert agreement["pool_available_cash_cents"] == 500000  # 500k - 0
    delta = (
        agreement["pool_available_cash_cents"]
        - agreement["pool_available_reserved_cents"]
    )
    assert delta == 250000, "the delta is exactly the outstanding OFFERED commitment"


def test_pool_exact_equality_grants_award(api):
    """PRD §3.7: "Each agreement grants at most the smaller of its remaining
    award headroom (`max_awards` minus awards already granted under it) and
    its remaining capacity in award units (`pool_available_reserved_cents`
    divided by `award_amount_cents`, rounded down)".
    
    Design: Difficulty/boundary_precision_check/pool_exact_equality_grants_and_exhausts
    """
    ctx = _setup_single_offer_pool(pool_total_cents=250000, max_awards=5)
    # floor(250000 / 250000) == 1: exact equality suffices to grant.
    assert ctx["matching_result"]["corporate_granted"] == 1
    assert ctx["matching_result"]["awards_created"] == 1
    award = find_award(ctx["student"]["id"], ctx["cycle"]["id"])
    assert award["amount_cents"] == 250000
    assert award["terms_total"] == 1
    assert award["renewable_years_total"] == 1
    assert award["category"] == "CORPORATE_SPONSORED"


def test_pool_exact_equality_leaves_zero_and_exhausts(api):
    """PRD §3.6: "A sponsor agreement flips `ACTIVE` → `EXHAUSTED` after any
    award creation or pool release touching it whenever its
    `pool_available_reserved_cents` falls below its `award_amount_cents` or
    its granted award count reaches `max_awards`".
    
    Design: Difficulty/boundary_precision_check/pool_exact_equality_grants_and_exhausts
    """
    ctx = _setup_single_offer_pool(pool_total_cents=250000, max_awards=5)
    agreement = get_agreement(ctx["agreement"]["id"])
    assert agreement["pool_available_reserved_cents"] == 0
    assert agreement["status"] == "EXHAUSTED"  # floor(0 / 250000) == 0 capacity
    assert_pool_ledger_consistent(agreement)
