"""Award lifecycle: acceptance, disbursement schedules and releases, renewal,
decline, expiry, and the completion bubble-up — PRD §2.5, §3.7, §3.8.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_award,
    advance_clock,
    assert_pool_ledger_consistent,
    create_college_institution,
    create_renewal,
    create_renewal_decision_payload,
    decide_renewal,
    create_renewal_verification_payload,
    decline_award,
    find_award,
    get_agreement,
    get_award,
    get_cycle,
    list_award_disbursements,
    list_award_renewals,
    list_notifications,
    make_college_admin_headers,
    make_student_headers,
    release_disbursement,
    setup_accepted_awards,
    setup_awards_completed,
    setup_enrolled_awards,
    setup_matching_run,
    setup_renewal_submitted,
    validate_error,
    validate_error_is_one_of,
)

PA = TEST_USERS["program_admin_headers"]

_COLLEGE_3X2 = {  # 83335/year, 3 years, 2 terms/year -> 250005 over 6 terms
    "award_amount_cents": 83335,
    "renewable_years_total": 3,
    "terms_per_year": 2,
    "pool_total_cents": 1000000,
    "max_awards": 5,
}
_COLLEGE_2X2 = {  # 100000/year, 2 years, 2 terms/year -> 200000 over 4 terms
    "award_amount_cents": 100000,
    "renewable_years_total": 2,
    "terms_per_year": 2,
    "pool_total_cents": 1000000,
    "max_awards": 5,
}
_COLLEGE_2X1 = {  # 100000/year, 2 years, 1 term/year -> 200000 over 2 terms
    "award_amount_cents": 100000,
    "renewable_years_total": 2,
    "terms_per_year": 1,
    "pool_total_cents": 500000,
    "max_awards": 5,
}


def test_disbursement_amounts_final_term_absorbs_remainder(api):
    """PRD §3.8: "Each non-final term's `amount_cents` is the award's
    `amount_cents` divided by `terms_total`, rounded half up; the final term
    absorbs the remainder, taking the award's `amount_cents` minus the sum of
    all prior terms. This rounding order is pinned — round each non-final term
    first, then let the final term absorb the remainder; rounding every term
    would let the schedule drift from the award total".
    
    Design: Difficulty/combinatorial_formula/disbursement_per_term_rounding_remainder_absorption
    """
    ctx = setup_accepted_awards(
        student_specs=[{"first_choice_college": True}],
        college_overrides=_COLLEGE_3X2,
    )
    award = ctx["award"]
    assert award["category"] == "COLLEGE_SPONSORED"
    assert award["amount_cents"] == 250005  # 83335 * 3
    assert award["terms_total"] == 6  # 3 * 2
    assert award["renewable_years_total"] == 3
    terms = ctx["disbursements"][award["id"]]
    assert [t["term_index"] for t in terms] == [1, 2, 3, 4, 5, 6]
    amounts = [t["amount_cents"] for t in terms]
    # round_half_up(250005 / 6) = 41668 for terms 1-5; term 6 takes the rest.
    assert amounts == [41668, 41668, 41668, 41668, 41668, 41665]
    assert sum(amounts) == award["amount_cents"] == 250005


def test_disbursement_schedule_dates_and_year_held_split(api):
    """PRD §3.8: "Numbering terms 1 through `terms_total`, with T0 the
    logical-clock date at acceptance: term i takes a `scheduled_date` of T0
    plus (i − 1) times 180 days", and "Year-1 terms are created `SCHEDULED` —
    payable once due — while terms of year 2 and beyond are created `HELD`
    pending that year's renewal".
    
    Design: Difficulty/combinatorial_formula/disbursement_per_term_rounding_remainder_absorption
    """
    ctx = setup_accepted_awards(
        student_specs=[{"first_choice_college": True}],
        college_overrides=_COLLEGE_3X2,
    )
    terms = ctx["disbursements"][ctx["award"]["id"]]
    # Acceptance happens at the logical-clock start 2026-09-01 (PRD §2.5).
    expected_dates = [
        "2026-09-01", "2027-02-28", "2027-08-27",
        "2028-02-23", "2028-08-21", "2029-02-17",
    ]
    assert [t["scheduled_date"][:10] for t in terms] == expected_dates
    assert [t["academic_year_index"] for t in terms] == [1, 1, 2, 2, 3, 3]
    assert [t["status"] for t in terms] == [
        "SCHEDULED", "SCHEDULED", "HELD", "HELD", "HELD", "HELD",
    ]
    assert all(t["released_logical_at"] is None for t in terms)


def test_award_dimensions_renewed_while_partially_disbursed(api):
    """PRD §3.8: "Approval moves the verification `SUBMITTED` → `APPROVED` and
    cascades into the award: the recipient moves `ENROLLED` → `RENEWED` ...
    years_renewed` grows by 1, and that year's `HELD` disbursements flip
    `HELD` → `SCHEDULED`", while the funding dimension only advances "on to
    `FULLY_DISBURSED` when the last non-`CANCELLED` term releases".
    
    Design: Difficulty/non_linear_state_machine/award_parallel_dimensions_independent
    """
    ctx = setup_enrolled_awards(  # accepted + term 1 released
        student_specs=[{"first_choice_college": True}],
        college_overrides=_COLLEGE_2X2,
    )
    award = ctx["award"]
    assert award["recipient_status"] == "ENROLLED"
    assert award["funding_status"] == "PARTIALLY_DISBURSED"
    terms = ctx["disbursements"][award["id"]]
    advance_clock("2027-02-28T00:00:00Z")
    release_disbursement(terms[1]["id"])  # 2 of 4 -> still PARTIALLY_DISBURSED

    renewal = create_renewal(award["id"], ctx["college"]["id"], reported_gpa=3.4)
    decided = decide_renewal(renewal["id"], "APPROVE")
    assert decided["status"] == "APPROVED"

    mid = get_award(award["id"])
    assert mid["recipient_status"] == "RENEWED"  # dimensions independent ...
    assert mid["funding_status"] == "PARTIALLY_DISBURSED"  # ... of each other
    assert mid["years_renewed"] == 1
    after = {t["id"]: t for t in list_award_disbursements(award["id"])}
    assert after[terms[2]["id"]]["status"] == "SCHEDULED"
    assert after[terms[3]["id"]]["status"] == "SCHEDULED"
    assert [after[t["id"]]["amount_cents"] for t in terms] == [50000] * 4


def test_award_fully_disbursed_completes_and_bubbles_cycle(api):
    """PRD §3.8: "reaching `FULLY_DISBURSED` flips a recipient in `ACCEPTED`,
    `ENROLLED`, or `RENEWED` to `COMPLETED`", and "when the cycle's
    `matching_run` is true, no award of the cycle remains in `OFFERED`,
    `ACCEPTED`, `ENROLLED`, or `RENEWED`, and no disbursement of the cycle's
    awards remains `SCHEDULED` or `HELD`, the cycle moves `FINALISTS_SELECTED`
    → `AWARDS_COMPLETED`".
    
    Design: Difficulty/non_linear_state_machine/award_parallel_dimensions_independent
    """
    ctx = setup_enrolled_awards(
        student_specs=[{"first_choice_college": True}],
        college_overrides=_COLLEGE_2X2,
    )
    award = ctx["award"]
    terms = ctx["disbursements"][award["id"]]
    advance_clock("2027-02-28T00:00:00Z")
    release_disbursement(terms[1]["id"])
    renewal = create_renewal(award["id"], ctx["college"]["id"], reported_gpa=3.4)
    decide_renewal(renewal["id"], "APPROVE")
    advance_clock("2027-08-27T00:00:00Z")
    release_disbursement(terms[2]["id"])
    advance_clock("2028-02-23T00:00:00Z")
    release_disbursement(terms[3]["id"])

    final = get_award(award["id"])
    assert final["funding_status"] == "FULLY_DISBURSED"
    assert final["recipient_status"] == "COMPLETED"
    assert get_cycle(ctx["cycle"]["id"])["status"] == "AWARDS_COMPLETED"


def test_disbursement_release_gates_rejected(api):
    """PRD §3.8: "Releasing a disbursement is a `ProgramAdmin` action with three
    preconditions: the disbursement must be `SCHEDULED` — a `HELD` one is
    rejected `ERR_DISBURSEMENT_HELD` (HTTP 409) and a terminal one (`RELEASED`
    or `CANCELLED`) is `ERR_INVALID_STATE`; the logical clock must be at or
    past its `scheduled_date`, else `ERR_DISBURSEMENT_NOT_DUE` (HTTP 422)".
    
    Design: Corner/validations/disbursement_release_gates_rejected
    """
    ctx = setup_accepted_awards(
        student_specs=[{"first_choice_college": True}],
        college_overrides=_COLLEGE_2X2,
    )
    award = ctx["award"]
    terms = ctx["disbursements"][award["id"]]
    # Term 1 is due at the acceptance date (the default clock): inclusive gate.
    first = release_disbursement(terms[0]["id"])
    assert first["status"] == "RELEASED"

    resp_notdue = api.release_disbursement(terms[1]["id"], PA)  # due 2027-02-28
    validate_error(resp_notdue, ApiErrorId.ERR_DISBURSEMENT_NOT_DUE)
    advance_clock("2027-08-27T00:00:00Z")  # term 3 now due but still HELD
    resp_held = api.release_disbursement(terms[2]["id"], PA)
    validate_error(resp_held, ApiErrorId.ERR_DISBURSEMENT_HELD)

    after = {t["id"]: t for t in list_award_disbursements(award["id"])}
    assert after[terms[1]["id"]]["status"] == "SCHEDULED"
    assert after[terms[2]["id"]]["status"] == "HELD"
    mid = get_award(award["id"])
    assert mid["recipient_status"] == "ENROLLED"
    assert mid["funding_status"] == "PARTIALLY_DISBURSED"


def test_renewal_gpa_boundary_conditional(api):
    """PRD §3.8: "A `decision` of `APPROVE` requires `reported_enrollment` of
    `FULL_TIME` and a `reported_gpa` of at least 2.5; anything short is
    `ERR_RENEWAL_CRITERIA_UNMET` (HTTP 422)."
    
    Design: Corner/validations/renewal_gpa_boundary_conditional
    """
    ctx = setup_enrolled_awards(
        student_specs=[{"first_choice_college": True}, {"first_choice_college": True}],
        college_overrides=_COLLEGE_2X1,
    )
    college_id = ctx["college"]["id"]
    aw_a = find_award(ctx["students"][0]["id"], ctx["cycle"]["id"])
    aw_b = find_award(ctx["students"][1]["id"], ctx["cycle"]["id"])
    rv_a = create_renewal(aw_a["id"], college_id, reported_gpa=2.4)
    rv_b = create_renewal(aw_b["id"], college_id, reported_gpa=2.5)

    resp = api.decide_renewal_verification(
        rv_a["id"], create_renewal_decision_payload("APPROVE"), PA
    )
    validate_error(resp, ApiErrorId.ERR_RENEWAL_CRITERIA_UNMET)  # 2.4 < 2.5
    renewals_a = list_award_renewals(aw_a["id"])
    assert len(renewals_a) == 1 and renewals_a[0]["status"] == "SUBMITTED"
    mid_a = get_award(aw_a["id"])
    assert mid_a["recipient_status"] == "ENROLLED"
    assert mid_a["years_renewed"] == 0
    terms_a = list_award_disbursements(aw_a["id"])
    assert terms_a[1]["status"] == "HELD"

    decided_b = decide_renewal(rv_b["id"], "APPROVE")  # 2.5 exactly: inclusive
    assert decided_b["status"] == "APPROVED"
    mid_b = get_award(aw_b["id"])
    assert mid_b["recipient_status"] == "RENEWED"
    assert mid_b["years_renewed"] == 1
    terms_b = list_award_disbursements(aw_b["id"])
    assert terms_b[1]["status"] == "SCHEDULED"


def test_duplicate_renewal_same_year_rejected(api):
    """PRD §3.8: "exactly one verification may exist per academic year — the
    submitted `academic_year_index` must lie between 2 and the award's
    `renewable_years_total` and must be the immediately next unverified year,
    else `ERR_RENEWAL_ALREADY_EXISTS` (HTTP 409)".
    
    Design: Corner/errors/duplicate_renewal_same_year_rejected
    """
    ctx = setup_renewal_submitted(
        student_specs=[{"first_choice_college": True}],
        college_overrides=_COLLEGE_2X1,
        renewal_overrides={"reported_gpa": 3.1},
    )
    award = ctx["award"]
    resp = api.create_renewal_verification(
        award["id"],
        create_renewal_verification_payload(
            academic_year_index=2, reported_enrollment="FULL_TIME", reported_gpa=3.9
        ),
        make_college_admin_headers(ctx["college"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RENEWAL_ALREADY_EXISTS)
    renewals = list_award_renewals(award["id"])
    assert len(renewals) == 1
    assert renewals[0]["status"] == "SUBMITTED"
    assert renewals[0]["reported_gpa"] == 3.1


def test_renewal_on_single_payment_rejected(api):
    """PRD §3.8: "Renewability requires the award's `renewable_years_total` to be
    at least 2, else `ERR_NOT_RENEWABLE` (HTTP 409)", and "on a national or
    corporate award, whose `college_id` is null, any `CollegeAdmin` passes
    this ownership check and hits the renewability gate instead".
    
    Design: Corner/errors/renewal_on_single_payment_rejected
    """
    ctx = setup_matching_run(cycle_overrides={"national_award_slots": 1})
    award = ctx["award"]
    accept_award(award["id"], ctx["student"]["id"])
    college = create_college_institution()  # identity anchor for the caller
    resp = api.create_renewal_verification(
        award["id"],
        create_renewal_verification_payload(
            academic_year_index=2, reported_enrollment="FULL_TIME", reported_gpa=3.5
        ),
        make_college_admin_headers(college["id"]),
    )
    # PRD §2.8 lists ERR_NOT_RENEWABLE and the recipient-state ERR_INVALID_STATE
    # in the same priority-6 category without an intra-category order, and a
    # single-payment award never rests in ENROLLED (its only release completes
    # it) — so either member of the pair is the deterministic surface.
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_NOT_RENEWABLE, ApiErrorId.ERR_INVALID_STATE]
    )
    assert list_award_renewals(award["id"]) == []


def test_decline_already_declined_rejected(api):
    """PRD §3.8: "accepting or declining an award in any other recipient state
    (already accepted, already declined, expired-swept, or lapsed) is
    `ERR_AWARD_NOT_OFFERED` (HTTP 409)".
    
    Design: Corner/state_machines/decline_already_declined_rejected
    """
    ctx = setup_matching_run(cycle_overrides={"national_award_slots": 1})
    award = ctx["award"]
    student_id = ctx["student"]["id"]
    decline_award(award["id"], student_id)

    resp1 = api.decline_award(award["id"], make_student_headers(student_id))
    validate_error(resp1, ApiErrorId.ERR_AWARD_NOT_OFFERED)
    resp2 = api.accept_award(award["id"], make_student_headers(student_id))
    validate_error(resp2, ApiErrorId.ERR_AWARD_NOT_OFFERED)

    after = get_award(award["id"])
    assert after["recipient_status"] == "DECLINED"
    assert after["funding_status"] == "RELEASED_BACK"
    notes = list_notifications(student_id)
    assert len(notes) == 4
    assert [n["status"] for n in notes] == [
        "EMBARGOED", "EMBARGOED", "SUPERSEDED", "SUPERSEDED",
    ]


def test_completed_cycle_rejects_reopen(api):
    """PRD §3.1: "Opening entries moves `SETUP` → `ENTRY_OPEN`; attempted from
    any other posture it is `ERR_INVALID_STATE`." PRD §3.8: "when the cycle's
    `matching_run` is true, no award of the cycle remains in `OFFERED`,
    `ACCEPTED`, `ENROLLED`, or `RENEWED`, and no disbursement of the cycle's
    awards remains `SCHEDULED` or `HELD`, the cycle moves `FINALISTS_SELECTED`
    → `AWARDS_COMPLETED`".
    
    Design: Corner/state_machines/completed_cycle_rejects_reopen
    """
    ctx = setup_awards_completed()  # one national award, fully disbursed
    assert ctx["cycle"]["status"] == "AWARDS_COMPLETED"
    award = get_award(ctx["award"]["id"])
    assert award["recipient_status"] == "COMPLETED"
    assert award["funding_status"] == "FULLY_DISBURSED"
    resp = api.open_entries(ctx["cycle"]["id"], PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_offer_expiry_sweep_promotes_waitlist(api):
    """PRD §3.8: "expiry is the clock sweep's, firing when the logical clock
    advances past `acceptance_deadline` while the award is still `OFFERED`",
    and PRD §2.5: a successful advance "sweeps every still-`OFFERED` award
    whose `acceptance_deadline` has passed to `EXPIRED` (running the full
    release cascade of §3.8)" and returns "the `expired_offer_ids` of the
    offers swept by that advance".
    
    Design: Corner/cross_cutting_layers/offer_expiry_sweep_promotes_waitlist
    """
    ctx = setup_matching_run(
        student_specs=[
            {"confirming_selection_index": 212},  # F1 SI 224
            {"confirming_selection_index": 208},  # F2 SI 222
        ],
        cycle_overrides={"national_award_slots": 1},
    )
    f1, f2 = ctx["students"]
    aw1 = find_award(f1["id"], ctx["cycle"]["id"])
    assert aw1["acceptance_deadline"] == "2026-10-01T00:00:00Z"  # offered + 30d

    at_boundary = advance_clock("2026-10-01T00:00:00Z")
    assert at_boundary["expired_offer_ids"] == []  # sweep fires only past it
    after = advance_clock("2026-10-02T00:00:00Z")
    assert aw1["id"] in after["expired_offer_ids"]

    expired = get_award(aw1["id"])
    assert expired["recipient_status"] == "EXPIRED"
    assert expired["funding_status"] == "RELEASED_BACK"
    promoted = find_award(f2["id"], ctx["cycle"]["id"])
    assert promoted["recipient_status"] == "OFFERED"
    assert promoted["category"] == "NATIONAL_SINGLE"
    assert promoted["acceptance_deadline"] == "2026-11-01T00:00:00Z"  # new window

    f1_notes = list_notifications(f1["id"])
    assert [n["status"] for n in f1_notes] == [
        "EMBARGOED", "EMBARGOED", "SUPERSEDED", "SUPERSEDED",
    ]
    f2_notes = list_notifications(f2["id"])
    assert [n["sequence_number"] for n in f2_notes] == [1, 2, 3, 4]
    offer_note = [n for n in f2_notes if n["notice_type"] == "AWARD_OFFER"][0]
    assert offer_note["status"] == "EMBARGOED"


def test_pool_ledger_reconciles_across_offer_accept_release(api):
    """PRD §3.6: "pool_available_reserved_cents` is `pool_total_cents` minus
    `pool_committed_cents` minus `pool_paid_cents`"; PRD §3.8: a release
    "moves money in the funding pool's ledger — `pool_committed_cents` down by
    the term's `amount_cents`, `pool_paid_cents` up by the same amount", and
    the bubble-up flips "every `ACTIVE` or `EXHAUSTED` `SponsorAgreement` of
    the cycle ... to CLOSED".
    
    Design: Corner/cross_cutting_layers/sponsor_pool_ledger_reconciles_across_offer_accept_release
    """
    ctx = setup_matching_run(
        student_specs=[{"parent_sponsor": True}],
        agreement_overrides={"pool_total_cents": 500000},
    )
    agreement_id = ctx["agreement"]["id"]
    pre = get_agreement(agreement_id)
    assert pre["pool_committed_cents"] == 250000  # reservation at offer time
    assert pre["pool_paid_cents"] == 0
    assert_pool_ledger_consistent(pre)

    award = ctx["award"]
    accept_award(award["id"], ctx["student"]["id"])
    mid = get_agreement(agreement_id)
    assert mid["pool_committed_cents"] == 250000  # accept moves no money
    assert mid["pool_paid_cents"] == 0

    term = list_award_disbursements(award["id"])[0]  # single 250000 term, due now
    release_disbursement(term["id"])
    post = get_agreement(agreement_id)
    assert post["pool_committed_cents"] == 0  # committed -> paid, no drift
    assert post["pool_paid_cents"] == 250000
    assert_pool_ledger_consistent(post)
    assert post["status"] == "CLOSED"
    assert get_cycle(ctx["cycle"]["id"])["status"] == "AWARDS_COMPLETED"
