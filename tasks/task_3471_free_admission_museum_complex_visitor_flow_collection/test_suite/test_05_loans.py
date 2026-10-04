"""Collection loans: premium computation (provisional vs final, pinned
rounding), the cyclic negotiation state machine, half-open window overlap,
term gates, condition-report gating and supersession, conservation holds, and
optimistic concurrency (PRD §3.4, §3.5, §2.6)."""

from test_helpers import (
    PREMIUM_ROUNDING_DECLARED,
    PREMIUM_ROUNDING_PINNED_CENTS,
    PREMIUM_ROUNDING_WRONG_CENTS,
    PREMIUM_WORKED_DECLARED,
    PREMIUM_WORKED_FINAL_CENTS,
    PREMIUM_WORKED_PROVISIONAL_CENTS,
    ApiErrorId,
    accept_loan,
    activate_loan,
    counter_loan,
    create_agreed_loan,
    create_closed_loan,
    create_object,
    create_proposed_loan,
    decide_condition_report,
    expected_final_premium_cents,
    file_condition_report,
    get_object,
    make_borrower_rep_headers,
    make_loans_officer_headers,
    make_registrar_headers,
    reset_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_loan_premium_provisional_vs_final_diverge(api):
    """PRD §3.4: "During negotiation, staff may quote a provisional premium: a flat 0.8 percent of `declared_value_cents`, with no tiering and no courier surcharge. The provisional figure is a documented estimate and is never persisted."
    PRD §3.4: "For contrast, a declared value of 250,000,000 cents with a courier quotes provisionally at 2,000,000 cents but locks at 1,260,000 cents under the final tiered computation."

    Design: Difficulty/dual_variant_calc/loan_premium_provisional_vs_final_diverge
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0001", title="Etruscan Krater", declared_value_cents=300000000
    )
    loan = create_proposed_loan(
        obj["id"], borrower_institution="Kunstmuseum Basel",
        loan_start_date="2026-10-01", loan_end_date="2027-01-01",
        declared_value_cents=PREMIUM_WORKED_DECLARED,
        coverage_type="INSURANCE", courier_required=True,
    )
    agreed = accept_loan(loan, as_borrower=True)
    assert agreed["status"] == "AGREED"
    # FINAL: tiered base 600000 + 525000 = 1125000, surcharge round(1125000 * 0.12) = 135000.
    assert agreed["premium_cents"] == PREMIUM_WORKED_FINAL_CENTS == 1260000
    assert agreed["premium_cents"] != PREMIUM_WORKED_PROVISIONAL_CENTS, (
        "the flat 0.8% provisional quote is never persisted"
    )


def test_loan_premium_rounding_order_pinned(api):
    """PRD §3.4: "The pinned order matters: for a declared value of 1,000,075 cents with a courier, the pinned computation yields 6,720 cents, while summing the unrounded parts and rounding once at the end yields 6,721 — and is wrong."

    Design: Difficulty/combinatorial_formula/loan_premium_rounding_order_pinned
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0002", title="Moche Stirrup Vessel",
        declared_value_cents=PREMIUM_ROUNDING_DECLARED,
    )
    loan = create_proposed_loan(
        obj["id"], borrower_institution="Field Museum",
        loan_start_date="2026-10-01", loan_end_date="2027-01-01",
        declared_value_cents=PREMIUM_ROUNDING_DECLARED,
        coverage_type="INSURANCE", courier_required=True,
    )
    agreed = accept_loan(loan, as_borrower=True)
    # base = round_half_up(6000.45) = 6000; surcharge = round_half_up(6000 * 0.12) = 720.
    assert agreed["premium_cents"] == PREMIUM_ROUNDING_PINNED_CENTS == 6720
    assert agreed["premium_cents"] != PREMIUM_ROUNDING_WRONG_CENTS, (
        "the sum-then-round reading is wrong"
    )
    assert agreed["premium_cents"] == expected_final_premium_cents(
        PREMIUM_ROUNDING_DECLARED, "INSURANCE", True
    )


def test_loan_counter_rounds_cycle(api):
    """PRD §3.4: "Negotiation proceeds in counter-rounds. The `BorrowerRep` counters a `PROPOSED` agreement, moving it to `COUNTERED`; the `LoansOfficer` counters a `COUNTERED` agreement, moving it back to `PROPOSED` — the lender's counter of the borrower's counter."
    PRD §3.4: "On a successful counter, whichever of the term fields — `loan_start_date`, `loan_end_date`, `declared_value_cents`, `coverage_type`, `courier_required` — are provided replace the current terms, `negotiated_round` increments by 1, and the agreement's `version` increments by 1."
    PRD §3.4: "Acceptance is symmetric: the `BorrowerRep` accepts from `PROPOSED`, and the `LoansOfficer` accepts from `COUNTERED`."

    Design: Difficulty/non_linear_state_machine/loan_counter_rounds_cycle
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0003", title="Hope Diamond Study Model", declared_value_cents=120000000
    )
    loan = create_proposed_loan(
        obj["id"], borrower_institution="Getty Museum",
        loan_start_date="2026-10-01", loan_end_date="2027-03-01",
        declared_value_cents=120000000, coverage_type="INSURANCE", courier_required=True,
    )
    loan = counter_loan(loan, as_borrower=True, declared_value_cents=120000000)  # -> COUNTERED, v2
    loan = counter_loan(loan, as_borrower=False, loan_end_date="2027-03-01")     # -> PROPOSED, v3
    loan = counter_loan(loan, as_borrower=True)                                  # -> COUNTERED, v4
    agreed = accept_loan(loan, as_borrower=False)  # lender accepts from COUNTERED
    assert agreed["status"] == "AGREED"
    assert agreed["negotiated_round"] == 4, "1 at creation plus 3 counters"
    assert agreed["version"] == 5, "create + 3 counters + accept"
    # base = 600000 + 20000000 * 0.0035 = 670000; surcharge = round(670000 * 0.12) = 80400.
    assert agreed["premium_cents"] == expected_final_premium_cents(120000000, "INSURANCE", True) == 750400


def test_object_loan_loop_returns_to_in_collection(api):
    """PRD §3.5: "The object's next state reads off that accepted return report: when `damage_noted` is false the object returns to `IN_COLLECTION`, and when `damage_noted` is true it moves to `UNDER_CONSERVATION`."
    PRD §3.4: "The object must be `IN_COLLECTION`, else `ERR_OBJECT_NOT_IN_COLLECTION`."

    Design: Difficulty/non_linear_state_machine/object_loan_loop_returns_to_in_collection
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0004", title="Lansdowne Portrait", declared_value_cents=50000000
    )
    built = create_closed_loan(
        obj["id"], damage_noted=False, borrower_institution="Metropolitan Museum",
        loan_start_date="2026-10-01", loan_end_date="2026-12-01",
        declared_value_cents=50000000, coverage_type="INSURANCE", courier_required=False,
    )
    loan1 = built["loan"]
    assert loan1["status"] == "CLOSED"
    # Flat tier-1 only: round(50000000 * 0.006) = 300000, no courier surcharge.
    assert loan1["premium_cents"] == expected_final_premium_cents(50000000, "INSURANCE", False) == 300000
    assert built["object"]["status"] == "IN_COLLECTION", (
        "the OUT_ON_LOAN -> IN_COLLECTION loop completed on a clean return"
    )
    # The loop is re-enterable: a second negotiation opens cleanly.
    loan2 = create_proposed_loan(
        obj["id"], borrower_institution="Art Institute of Chicago",
        loan_start_date="2027-01-05", loan_end_date="2027-03-01",
        declared_value_cents=52000000, coverage_type="INSURANCE", courier_required=False,
    )
    assert loan2["status"] == "PROPOSED"


def test_loan_windows_half_open_adjacency(api):
    """PRD §3.4: "Second, window overlap: the half-open window must not overlap any other `AGREED` or `ACTIVE` loan of the same object, where overlap means this loan starts before the other ends and the other starts before this loan ends; adjacency — one loan starting exactly when another ends — is not overlap, so back-to-back loans are allowed. A conflict is rejected with `ERR_LOAN_PERIOD_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/loan_windows_half_open_adjacency
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0007", title="Wright Flyer Fabric", declared_value_cents=50000000
    )
    create_agreed_loan(
        obj["id"], borrower_institution="Science Museum London",
        loan_start_date="2026-10-01", loan_end_date="2026-12-01",
        declared_value_cents=50000000, coverage_type="INSURANCE", courier_required=False,
    )
    loan_b = create_proposed_loan(
        obj["id"], borrower_institution="Deutsches Museum",
        loan_start_date="2026-11-15", loan_end_date="2027-01-15",
        declared_value_cents=50000000, coverage_type="INSURANCE", courier_required=False,
    )
    loan_c = create_proposed_loan(
        obj["id"], borrower_institution="National Air and Space Annex",
        loan_start_date="2026-12-01", loan_end_date="2027-02-01",
        declared_value_cents=50000000, coverage_type="INSURANCE", courier_required=False,
    )
    # [2026-11-15, 2027-01-15) intersects A's [2026-10-01, 2026-12-01).
    resp_b = api.accept_loan_agreement(
        loan_b["id"], loan_b["version"], headers=make_borrower_rep_headers()
    )
    validate_error(resp_b, ApiErrorId.ERR_LOAN_PERIOD_CONFLICT)
    after_b = validate_success(
        api.get_loan_agreement(loan_b["id"], headers=make_loans_officer_headers())
    )
    assert after_b["status"] == "PROPOSED", "a rejected accept leaves the negotiation open"
    # [2026-12-01, 2027-02-01) starts exactly at A's end: adjacency is not overlap.
    agreed_c = accept_loan(loan_c, as_borrower=True)
    assert agreed_c["status"] == "AGREED"
    assert agreed_c["premium_cents"] == expected_final_premium_cents(50000000, "INSURANCE", False)


def test_indemnity_and_courier_term_gates(api):
    """PRD §3.4: "First, terms validation: an agreement whose declared value is at least 100,000,000 cents requires a courier, so acceptance with `courier_required` false at or above that threshold fails with `ERR_COURIER_REQUIRED`; an `INDEMNITY` agreement requires a declared value of at least 500,000,000 cents, failing otherwise with `ERR_INDEMNITY_MINIMUM_NOT_MET`, and always requires a courier, failing otherwise with `ERR_INDEMNITY_REQUIRES_COURIER`"
    PRD §3.4: "Under `INDEMNITY` coverage the premium is always 0."

    Design: Corner/calculations/indemnity_and_courier_term_gates
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0012", title="Treaty of Canandaigua", declared_value_cents=600000000
    )
    window = {"loan_start_date": "2026-10-01", "loan_end_date": "2027-01-01"}
    l1 = create_proposed_loan(obj["id"], borrower_institution="Borrower One",
                              declared_value_cents=400000000, coverage_type="INDEMNITY",
                              courier_required=True, **window)
    l2 = create_proposed_loan(obj["id"], borrower_institution="Borrower Two",
                              declared_value_cents=600000000, coverage_type="INDEMNITY",
                              courier_required=False, **window)
    l4 = create_proposed_loan(obj["id"], borrower_institution="Borrower Four",
                              declared_value_cents=150000000, coverage_type="INSURANCE",
                              courier_required=False, **window)
    l3 = create_proposed_loan(obj["id"], borrower_institution="Borrower Three",
                              declared_value_cents=600000000, coverage_type="INDEMNITY",
                              courier_required=True, **window)
    # 400,000,000 < the 500,000,000 indemnity minimum.
    resp1 = api.accept_loan_agreement(l1["id"], l1["version"], headers=make_borrower_rep_headers())
    validate_error(resp1, ApiErrorId.ERR_INDEMNITY_MINIMUM_NOT_MET)
    # L2 violates both the general courier minimum and the indemnity courier
    # mandate; the PRD does not pin which of the two term errors is reported.
    validate_error_is_one_of(
        resp2 := api.accept_loan_agreement(l2["id"], l2["version"], headers=make_borrower_rep_headers()),
        [ApiErrorId.ERR_INDEMNITY_REQUIRES_COURIER, ApiErrorId.ERR_COURIER_REQUIRED],
    )
    # L4 is evaluated while no AGREED/ACTIVE loan exists, so the courier term
    # gate is the only gate that can fire (150,000,000 >= 100,000,000).
    resp4 = api.accept_loan_agreement(l4["id"], l4["version"], headers=make_borrower_rep_headers())
    validate_error(resp4, ApiErrorId.ERR_COURIER_REQUIRED)
    # The compliant INDEMNITY loan accepts; federal indemnity prices at 0.
    agreed3 = accept_loan(l3, as_borrower=True)
    assert agreed3["status"] == "AGREED"
    assert agreed3["premium_cents"] == 0
    for rejected in (l1, l2, l4):
        after = validate_success(
            api.get_loan_agreement(rejected["id"], headers=make_loans_officer_headers())
        )
        assert after["status"] == "PROPOSED", "a rejected accept leaves the loan PROPOSED"


def test_loan_activate_requires_accepted_outbound_report(api):
    """PRD §3.5: "Shipment requires paperwork. Moving an agreement `AGREED` to `ACTIVE` — the `LoansOfficer` shipping the object — requires an `OUTBOUND` report for the loan standing in `ACCEPTED`, else `ERR_CONDITION_REPORT_REQUIRED`, and requires the object still `IN_COLLECTION`, else `ERR_OBJECT_NOT_IN_COLLECTION`. Activation flips the object to `OUT_ON_LOAN` and bumps the loan's `version`."

    Design: Difficulty/cross_entity_state_dependency/loan_activate_requires_accepted_outbound_report
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0006", title="Star-Spangled Banner Fragment",
        declared_value_cents=50000000,
    )
    loan = create_agreed_loan(
        obj["id"], borrower_institution="Museum of American History Partners",
        loan_start_date="2026-10-01", loan_end_date="2026-12-01",
        declared_value_cents=50000000, coverage_type="INSURANCE", courier_required=False,
    )
    report = file_condition_report(
        loan["id"], report_kind="OUTBOUND",
        condition_summary="Textile stable under low light.", damage_noted=False,
    )
    # Merely SUBMITTED does not unblock shipment.
    resp = api.activate_loan_agreement(loan["id"], headers=make_loans_officer_headers())
    validate_error(resp, ApiErrorId.ERR_CONDITION_REPORT_REQUIRED)
    decide_condition_report(report["id"], "ACCEPTED")
    active = activate_loan(loan["id"])
    assert active["status"] == "ACTIVE"
    assert get_object(obj["id"])["status"] == "OUT_ON_LOAN"


def test_condition_report_supersede_on_refiling(api):
    """PRD §3.5: "Filing a fresh report of the same kind for the same loan supersedes any earlier report of that kind still standing in `DISPUTED`: the earlier report moves to `SUPERSEDED`, so only one live dispute per kind exists at a time."
    PRD §3.5: "Acceptance and dispute are terminal-or-supersedable states: `ACCEPTED`, `SUPERSEDED`, and `CANCELLED` are terminal, while `DISPUTED` awaits a superseding re-filing."

    Design: Corner/state_machines/condition_report_supersede_on_refiling
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0010", title="Apollo Suit Glove", declared_value_cents=50000000
    )
    loan = create_agreed_loan(
        obj["id"], borrower_institution="Kennedy Space Center",
        loan_start_date="2026-10-01", loan_end_date="2026-12-01",
        declared_value_cents=50000000, coverage_type="INSURANCE", courier_required=False,
    )
    r1 = file_condition_report(
        loan["id"], report_kind="OUTBOUND",
        condition_summary="Possible seam wear.", damage_noted=True, as_borrower=True,
    )
    decide_condition_report(r1["id"], "DISPUTED")
    r2 = file_condition_report(
        loan["id"], report_kind="OUTBOUND",
        condition_summary="Re-inspection: seam intact.", damage_noted=False,
    )
    # The supersede is written by the create, not by any decide.
    r1_after = validate_success(
        api.get_condition_report(r1["id"], headers=make_loans_officer_headers())
    )
    assert r1_after["status"] == "SUPERSEDED"
    resp_r1 = api.decide_condition_report(
        r1["id"], "ACCEPTED", headers=make_loans_officer_headers()
    )
    validate_error(resp_r1, ApiErrorId.ERR_INVALID_STATE)
    r2_decided = decide_condition_report(r2["id"], "ACCEPTED")
    assert r2_decided["status"] == "ACCEPTED"


def test_object_under_conservation_blocks_loans_until_released(api):
    """PRD §3.5: "An object under conservation blocks new loans and blocks research approvals until a `Registrar` performs the release action, moving it `UNDER_CONSERVATION` back to `IN_COLLECTION`."
    PRD §3.4: "The object must be `IN_COLLECTION`, else `ERR_OBJECT_NOT_IN_COLLECTION`."

    Design: Corner/state_machines/object_under_conservation_blocks_loans_until_released
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0011", title="Greensboro Lunch Counter Stool",
        declared_value_cents=50000000,
    )
    built = create_closed_loan(
        obj["id"], damage_noted=True, borrower_institution="DuSable Museum",
        loan_start_date="2026-10-01", loan_end_date="2026-12-01",
        declared_value_cents=50000000, coverage_type="INSURANCE", courier_required=False,
    )
    assert built["object"]["status"] == "UNDER_CONSERVATION", (
        "an accepted RETURN report with damage_noted true routes to conservation"
    )
    loan_payload = {
        "borrower_institution": "Another Museum",
        "loan_start_date": "2027-01-05", "loan_end_date": "2027-03-01",
        "declared_value_cents": 50000000, "coverage_type": "INSURANCE", "courier_required": False,
    }
    resp = api.create_loan_agreement(
        obj["id"], loan_payload, headers=make_loans_officer_headers()
    )
    validate_error(resp, ApiErrorId.ERR_OBJECT_NOT_IN_COLLECTION)
    released = validate_success(
        api.release_conservation(obj["id"], headers=make_registrar_headers())
    )
    assert released["status"] == "IN_COLLECTION"
    loan2 = create_proposed_loan(obj["id"], **loan_payload)
    assert loan2["status"] == "PROPOSED"


def test_loan_counter_stale_version_rejected(api):
    """PRD §2.6: "Countering a loan agreement — whether by the `BorrowerRep` or the `LoansOfficer` — requires the request to carry `expected_loan_version`, holding the `version` of the loan agreement the writer last observed. If the loan's current `version` has advanced beyond that value (the canonical case: the lender's counter legitimately supersedes the borrower's view, and a second counter carrying the pre-counter version is stale), the request is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412)."

    Design: Corner/validations/loan_counter_stale_version_rejected
    """
    reset_clock()
    obj = create_object(
        accession_number="2026.0021", title="OCC Loan Object", declared_value_cents=50000000
    )
    loan = create_proposed_loan(
        obj["id"], borrower_institution="OCC Borrower",
        loan_start_date="2026-10-01", loan_end_date="2026-12-01",
        declared_value_cents=50000000, coverage_type="INSURANCE", courier_required=False,
    )
    assert loan["version"] == 1
    loan = counter_loan(loan, as_borrower=True, declared_value_cents=51000000)  # -> COUNTERED, v2
    assert loan["version"] == 2
    # The lender's counter carries the pre-counter version: stale.
    resp = api.counter_loan_agreement(
        loan["id"],
        {"expected_loan_version": 1, "declared_value_cents": 52000000},
        headers=make_loans_officer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LOAN_VERSION)
    after = validate_success(
        api.get_loan_agreement(loan["id"], headers=make_loans_officer_headers())
    )
    assert after["declared_value_cents"] == 51000000, "the losing counter changed nothing"
    assert after["negotiated_round"] == 2
    assert after["status"] == "COUNTERED"
