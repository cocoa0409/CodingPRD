"""Submit-filing guard chain, deficiency cure cycle, entry lock semantics,
and fiscal tolerance boundaries (PRD §3.1, §3.2, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    add_adjustment,
    add_entry,
    add_rate_base_item,
    add_regulatory_asset,
    create_case,
    create_regulatory_asset_payload,
    create_rate_base_item_payload,
    create_test_year_entry_payload,
    get_adjustment,
    get_case,
    get_entry,
    lock_entry,
    setup_draft_case,
    setup_filed_case,
    submit_and_lock_entry,
    submit_entry,
    validate_error,
    validate_success,
    verify_adjustment,
    RB2,
    TEST_USERS,
    make_utility_filer_headers,
)

UF = TEST_USERS["utility_filer_alice"]
STAFF = TEST_USERS["commission_staff"]
ALICE = make_utility_filer_headers("uf_alice")
BOB = make_utility_filer_headers("uf_bob")


# ─── Difficulty: non_linear_state_machine / rate_case_deficiency_cure_cycle ──

def test_deficiency_cure_cycle_revisits_filed(api):
    """PRD §3.4: "With `outcome` equal to `DEFICIENT` the case moves back to
    `DEFICIENT`, and a non-empty `deficiency_notes` must be supplied — otherwise
    `ERR_DEFICIENCY_NOTES_REQUIRED`."
    PRD §3.3: "The filing gate is the submit-filing transition, available to
    `UtilityFiler` while the case is in `DRAFT` or `DEFICIENT`."

    Design: Difficulty/non_linear_state_machine/rate_case_deficiency_cure_cycle
    """
    s = setup_filed_case()
    st1 = validate_success(api.deficiency_review(
        s.case["id"], {"outcome": "DEFICIENT",
                       "deficiency_notes": "Cost of service study incomplete"},
        STAFF), 200)
    assert st1["status"] == "DEFICIENT", "cycle edge FILED -> DEFICIENT taken"
    st2 = validate_success(api.submit_filing(s.case["id"], UF), 200)
    assert st2["status"] == "FILED", "DEFICIENT -> FILED re-ran the full guard chain"
    st3 = validate_success(api.deficiency_review(
        s.case["id"], {"outcome": "ACCEPTED"}, STAFF), 200)
    assert st3["status"] == "ACCEPTED"


def test_deficiency_cycle_keeps_accepted_adjustment_stable(api):
    """PRD §3.3: "On success, every `VERIFIED` adjustment of the case moves to
    `ACCEPTED` (the acceptance cascade), and the case moves to `FILED`."

    Design: Difficulty/non_linear_state_machine/rate_case_deficiency_cure_cycle
    """
    s = setup_filed_case()
    assert get_adjustment(s.a1["id"])["status"] == "ACCEPTED"
    validate_success(api.deficiency_review(
        s.case["id"], {"outcome": "DEFICIENT", "deficiency_notes": "Incomplete"}, STAFF), 200)
    validate_success(api.submit_filing(s.case["id"], UF), 200)
    a1 = get_adjustment(s.a1["id"])
    assert a1["status"] == "ACCEPTED", (
        "the cascade is idempotent on already-ACCEPTED rows, not re-applied destructively"
    )
    assert a1["amount_cents"] == 50000000


# ─── Difficulty: priority_pair / state_guard_beats_fiscal_rr_mismatch ────────

def _setup_unlocked_entry_mismatched_case():
    """E1 SUBMITTED (not LOCKED), RB1 SUBMITTED; proposed RR 1,897,500,000 while
    the computed as-filed figure is 180,000,000 (COS 0 + return on 2.4e9)."""
    case = create_case()
    e1 = add_entry(case["id"], "900", "O_AND_M", 1000000000)
    submit_entry(e1["id"])
    rb1 = add_rate_base_item(case["id"])
    return case, e1, rb1


def test_state_guard_beats_fiscal_rr_mismatch(api):
    """PRD §3.3: "Its guards are evaluated in a pinned order. Case-level guards
    come first, in this order: (1) at least one TestYearEntry exists for the case
    — otherwise `ERR_NO_TEST_YEAR_ENTRIES`; (2) every TestYearEntry of the case is
    `LOCKED` — otherwise `ERR_ENTRIES_NOT_LOCKED`" and "Fiscal guards follow, also
    in pinned order".

    Design: Difficulty/priority_pair_validation_conflict/state_guard_beats_fiscal_rr_mismatch
    """
    case, _e1, _rb1 = _setup_unlocked_entry_mismatched_case()
    res = api.submit_filing(case["id"], UF)
    validate_error(res, ApiErrorId.ERR_ENTRIES_NOT_LOCKED, expected_status=409)
    assert get_case(case["id"])["status"] == "DRAFT", "case unchanged by the rejection"


def test_fiscal_mismatch_reached_once_state_guards_pass(api):
    """PRD §3.3: "Fiscal guards follow, also in pinned order: (1) the computed
    as-filed revenue requirement must be strictly greater than zero — otherwise
    `ERR_NONPOSITIVE_REVENUE_REQUIREMENT`; (2) the absolute difference between
    the case's `proposed_revenue_requirement_cents` and the computed as-filed
    revenue requirement must be at most 100 cents — otherwise `ERR_RR_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/state_guard_beats_fiscal_rr_mismatch
    """
    case, e1, _rb1 = _setup_unlocked_entry_mismatched_case()
    lock_entry(e1["id"])
    res = api.submit_filing(case["id"], UF)
    validate_error(res, ApiErrorId.ERR_RR_MISMATCH, expected_status=422)
    assert get_case(case["id"])["status"] == "DRAFT"


# ─── Difficulty: cross_entity_state_dependency / entry_lock ──────────────────

def _setup_submitted_entry_with_verified_adjustment():
    case = create_case()
    e1 = add_entry(case["id"], "900", "O_AND_M", 1000000000)
    submit_entry(e1["id"])
    a1 = add_adjustment(case["id"], e1["id"], 50000000, proposer_headers=ALICE)
    verify_adjustment(a1["id"], BOB)
    return case, e1, a1


def test_entry_lock_blocked_by_disputed_adjustment(api):
    """PRD §3.1: "Locking is blocked by any `DISPUTED` adjustment targeting the
    entry — `ERR_UNRESOLVED_ENTRY_ADJUSTMENTS` — but `PROPOSED` adjustments do
    not block entry lock (they block the case-level filing instead)."

    Design: Difficulty/cross_entity_state_dependency/entry_lock_blocked_by_disputed_adjustment
    """
    case, e1, a1 = _setup_submitted_entry_with_verified_adjustment()
    validate_success(api.dispute_adjustment(a1["id"], STAFF), 200)
    res = api.lock_entry(e1["id"], UF)
    validate_error(res, ApiErrorId.ERR_UNRESOLVED_ENTRY_ADJUSTMENTS, expected_status=409)
    assert get_entry(e1["id"])["status"] == "SUBMITTED", "entry unchanged while blocked"


def test_entry_lock_cleared_after_disputed_adjustment_withdrawn(api):
    """PRD §3.2: "a `UtilityFiler` withdraws a `PROPOSED` or `DISPUTED`
    adjustment, requiring `X-User-ID` equal to `proposed_by_user_id` (otherwise
    `ERR_FORBIDDEN_OWNERSHIP`); the adjustment moves to `WITHDRAWN` and is
    excluded from the entry total."
    PRD §3.2: "The entry's adjusted amount is the booked amount plus the sum of
    `amount_cents` over all adjustments of that entry whose status is `PROPOSED`,
    `VERIFIED`, `DISPUTED`, or `ACCEPTED`; `WITHDRAWN` and `REJECTED` adjustments
    are excluded."

    Design: Difficulty/cross_entity_state_dependency/entry_lock_blocked_by_disputed_adjustment
    """
    case, e1, a1 = _setup_submitted_entry_with_verified_adjustment()
    validate_success(api.dispute_adjustment(a1["id"], STAFF), 200)
    validate_error(api.lock_entry(e1["id"], UF),
                   ApiErrorId.ERR_UNRESOLVED_ENTRY_ADJUSTMENTS, expected_status=409)
    validate_success(api.withdraw_adjustment(a1["id"], ALICE), 200)
    locked = validate_success(api.lock_entry(e1["id"], UF), 200)
    assert locked["status"] == "LOCKED", "guard cleared by the other entity's transition"
    assert get_entry(e1["id"])["adjusted_amount_cents"] == 1000000000, (
        "WITHDRAWN amount no longer counted"
    )


# ─── Corner: state_machines / filing_guards_cluster ──────────────────────────

def test_filing_guards_cluster(api):
    """PRD §3.3: "Case-level guards come first, in this order: (1) at least one
    TestYearEntry exists for the case — otherwise `ERR_NO_TEST_YEAR_ENTRIES`;
    (2) every TestYearEntry of the case is `LOCKED` — otherwise
    `ERR_ENTRIES_NOT_LOCKED`; (3) zero adjustments of the case are in `PROPOSED`
    or `DISPUTED` — otherwise `ERR_UNRESOLVED_ADJUSTMENTS`; (4) at least one
    RateBaseItem of the case is in `SUBMITTED` or `AUDITED` — otherwise
    `ERR_NO_RATE_BASE_ITEMS`."
    PRD §3.3: "Wrong item state is `ERR_INVALID_ITEM_STATE`; wrong case state is
    `ERR_INVALID_CASE_STATE`."

    Design: Corner/state_machines/filing_guards_cluster
    """
    case = create_case(proposed_revenue_requirement_cents=1067500000)
    res1 = api.submit_filing(case["id"], UF)
    validate_error(res1, ApiErrorId.ERR_NO_TEST_YEAR_ENTRIES, expected_status=409)
    e1 = add_entry(case["id"], "900", "O_AND_M", 1000000000)
    submit_and_lock_entry(e1["id"])
    res2 = api.submit_filing(case["id"], UF)
    validate_error(res2, ApiErrorId.ERR_NO_RATE_BASE_ITEMS, expected_status=409)
    rb1 = add_rate_base_item(case["id"], submit=False,
                             label="Generation plant (kept DRAFT)")
    add_rate_base_item(case["id"], **RB2)
    filed = validate_success(api.submit_filing(case["id"], UF), 200)
    assert filed["status"] == "FILED", (
        "computed as-filed RR == 1,000,000,000 + round(900,000,000*0.075) "
        "== 1,067,500,000 == proposed, tolerance satisfied exactly"
    )
    res3 = api.audit_rate_base_item(rb1["id"], {"outcome": "AUDIT_PASS"}, STAFF)
    validate_error(res3, ApiErrorId.ERR_INVALID_ITEM_STATE, expected_status=409)


def test_deficiency_review_requires_notes(api):
    """PRD §3.4: "With `outcome` equal to `DEFICIENT` the case moves back to
    `DEFICIENT`, and a non-empty `deficiency_notes` must be supplied — otherwise
    `ERR_DEFICIENCY_NOTES_REQUIRED`."

    Design: Corner/state_machines/deficiency_review_requires_notes
    """
    s = setup_filed_case()
    res = api.deficiency_review(s.case["id"], {"outcome": "DEFICIENT"}, STAFF)
    validate_error(res, ApiErrorId.ERR_DEFICIENCY_NOTES_REQUIRED, expected_status=400)
    assert get_case(s.case["id"])["status"] == "FILED", "case unchanged"


def test_unresolved_proposed_adjustment_blocks_filing(api):
    """PRD §3.1: "`PROPOSED` adjustments do not block entry lock (they block the
    case-level filing instead)."
    PRD §3.3: "(3) zero adjustments of the case are in `PROPOSED` or `DISPUTED`
    — otherwise `ERR_UNRESOLVED_ADJUSTMENTS`"

    Design: Corner/validations/unresolved_proposed_adjustment_blocks_filing
    """
    case = create_case(proposed_revenue_requirement_cents=1230000000)
    e1 = add_entry(case["id"], "900", "O_AND_M", 1000000000)
    submit_entry(e1["id"])
    a2 = add_adjustment(case["id"], e1["id"], 50000000, proposer_headers=ALICE)
    locked = validate_success(api.lock_entry(e1["id"], UF), 200)
    assert locked["status"] == "LOCKED", "PROPOSED does not block entry lock"
    assert locked["adjusted_amount_cents"] == 1050000000, "PROPOSED counts in the total"
    add_rate_base_item(case["id"])
    res = api.submit_filing(case["id"], UF)
    validate_error(res, ApiErrorId.ERR_UNRESOLVED_ADJUSTMENTS, expected_status=409)
    validate_success(api.withdraw_adjustment(a2["id"], ALICE), 200)
    assert get_entry(e1["id"])["adjusted_amount_cents"] == 1000000000
    res2 = api.submit_filing(case["id"], UF)
    validate_error(res2, ApiErrorId.ERR_RR_MISMATCH, expected_status=422)
    assert get_case(case["id"])["status"] == "DRAFT"


def test_child_create_after_filing_rejected(api):
    """PRD §3.1: "While the case is in `DRAFT` or `DEFICIENT`, the utility
    assembles the test-year record."
    PRD §3.3: "Each RateBaseItem is created while the case is in `DRAFT` or
    `DEFICIENT`"
    PRD §3.6: "The asset is created (while the case is in `DRAFT` or
    `DEFICIENT`)"
    PRD §3.1: "the wrong case state yields `ERR_INVALID_CASE_STATE`"

    Design: Corner/state_machines/child_create_after_filing_rejected
    """
    s = setup_filed_case()
    res1 = api.create_test_year_entry(
        create_test_year_entry_payload(s.case["id"], account_code="903",
                                       booked_amount_cents=5), UF)
    validate_error(res1, ApiErrorId.ERR_INVALID_CASE_STATE, expected_status=409)
    res2 = api.create_rate_base_item(
        create_rate_base_item_payload(s.case["id"], label="Late plant",
                                      plant_in_service_cents=1,
                                      accumulated_depreciation_cents=0,
                                      working_capital_cents=0,
                                      accumulated_deferred_taxes_cents=0), UF)
    validate_error(res2, ApiErrorId.ERR_INVALID_CASE_STATE, expected_status=409)
    res3 = api.create_regulatory_asset(
        create_regulatory_asset_payload(s.case["id"], asset_name="Late deferral",
                                        principal_cents=1000,
                                        incurrence_start="2024-01-01T00:00:00Z",
                                        incurrence_end="2024-06-30T00:00:00Z",
                                        amortization_months=2), UF)
    validate_error(res3, ApiErrorId.ERR_INVALID_CASE_STATE, expected_status=409)


def test_locked_entry_is_terminal_rejected(api):
    """PRD §3.1: "`LOCKED` is terminal for an entry." and "All three transitions
    require the owning case in `DRAFT` or `DEFICIENT`; the wrong entry state
    yields `ERR_INVALID_ENTRY_STATE`, the wrong case state yields
    `ERR_INVALID_CASE_STATE`."

    Design: Corner/state_machines/locked_entry_is_terminal_rejected
    """
    case = create_case()
    e1 = add_entry(case["id"])
    submit_and_lock_entry(e1["id"])
    res1 = api.lock_entry(e1["id"], UF)
    validate_error(res1, ApiErrorId.ERR_INVALID_ENTRY_STATE, expected_status=409)
    res2 = api.reopen_entry(e1["id"], UF)
    validate_error(res2, ApiErrorId.ERR_INVALID_ENTRY_STATE, expected_status=409)
    assert get_entry(e1["id"])["status"] == "LOCKED"


def test_rr_mismatch_tolerance_boundary(api):
    """PRD §3.3: "(2) the absolute difference between the case's
    `proposed_revenue_requirement_cents` and the computed as-filed revenue
    requirement must be at most 100 cents — otherwise `ERR_RR_MISMATCH`." and
    "(1) the computed as-filed revenue requirement must be strictly greater than
    zero — otherwise `ERR_NONPOSITIVE_REVENUE_REQUIREMENT`"

    Design: Corner/validations/rr_mismatch_tolerance_boundary
    """
    def minimal_case(case_number, proposed, booked=1000000000, plant=3000000000,
                     acc_dep=500000000, wc=100000000, adt=200000000):
        case = create_case(case_number=case_number,
                           proposed_revenue_requirement_cents=proposed)
        e = add_entry(case["id"], "900", "O_AND_M", booked)
        submit_and_lock_entry(e["id"])
        add_rate_base_item(case["id"], plant_in_service_cents=plant,
                           accumulated_depreciation_cents=acc_dep,
                           working_capital_cents=wc,
                           accumulated_deferred_taxes_cents=adt)
        return case

    case_a = minimal_case("UR-2026-A", 1180000100)
    case_b = minimal_case("UR-2026-B", 1180000101)
    case_c = minimal_case("UR-2026-C", 0, booked=0, plant=500000000,
                          acc_dep=500000000, wc=0, adt=0)

    res_a = api.submit_filing(case_a["id"], UF)
    filed_a = validate_success(res_a, 200)
    assert filed_a["status"] == "FILED", (
        "|1,180,000,100 - 1,180,000,000| == 100 <= 100, inclusive boundary"
    )
    res_b = api.submit_filing(case_b["id"], UF)
    validate_error(res_b, ApiErrorId.ERR_RR_MISMATCH, expected_status=422)
    res_c = api.submit_filing(case_c["id"], UF)
    validate_error(res_c, ApiErrorId.ERR_NONPOSITIVE_REVENUE_REQUIREMENT,
                   expected_status=422)
