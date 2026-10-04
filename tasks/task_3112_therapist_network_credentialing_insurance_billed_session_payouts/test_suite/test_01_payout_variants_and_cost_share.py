"""Dual-variant calculations: the two-variant cost-share estimator and the two
payout-line inclusion filters."""
from test_helpers import (
    CLOCK_DELIVERY,
    CLOCK_ONBOARD,
    add_signed_note,
    adjudicate,
    api_client,
    assert_claim,
    assert_payout_batch,
    assert_payout_line,
    assert_payout_line_invariants,
    attach_billable_clinician,
    complete_session,
    get_batch_lines,
    get_session,
    make_completed_session,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    open_and_lock_batch,
    set_clock,
    submit_claim,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]


def _divergence_setup() -> dict:
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(
        payer["id"], full_name="Dana Reyes", weekly_caseload_target=8
    )
    clinician = attached["clinician"]
    patient = make_verified_patient(
        payer["id"],
        full_name="Priya Anand",
        member_id="MBR-4410",
        deductible_cents=100_000,
        coinsurance_rate=0.20,
        oop_max_cents=200_000,
        verification={
            "deductible_remaining_cents": 5_000,
            "coinsurance_rate": 0.20,
            "copay_cents": 2_500,
            "oop_remaining_cents": 200_000,
        },
    )
    session = make_scheduled_session(
        clinician["id"], patient["id"],
        "2026-06-16T14:00:00Z", "2026-06-16T15:00:00Z",
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock(CLOCK_DELIVERY)
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])
    return {"payer": payer, "clinician": clinician, "patient": patient,
            "session": session, "claim": claim}


def test_provisional_quote_keeps_the_snapshot_deductible_while_the_final_responsibility_uses_the_live_basis():
    """PRD §3.3: "The provisional quote used at booking — and recomputed whenever
    a cancelled session is moved to a new interval — reads all four of its
    parameters from the snapshot in force at that moment: the remaining
    deductible, the out-of-pocket room, the coinsurance rate and the copay all
    come from that same `BenefitVerification` row, and this variant always
    carries the copay offset."
    PRD §3.3: "Its remaining deductible is the patient's `deductible_cents`
    reduced by the sum of `patient_resp_cents` across that patient's claims in
    `PAID` status during the current plan year, taken in ascending `submitted_on`
    order and floored at zero; its out-of-pocket room is the patient's
    `oop_max_cents` less the live `oop_met_cents`, floored at zero."

    Design: Difficulty/dual_variant_calc/cost_share_provisional_quote_diverges_from_final_adjudication
    """
    scenario = _divergence_setup()
    session_id = scenario["session"]["id"]
    claim_id = scenario["claim"]["id"]

    adjudicated = validate_success(
        api_client.adjudicate_claim(claim_id, {"outcome": "PAID"}, OPS)
    )
    assert_claim(adjudicated)

    session = get_session(session_id)
    assert session["quoted_cost_share_cents"] == 8_400, (
        "the provisional quote is 5000 + 1400 + 2500 less the 500 offset, "
        f"got {session['quoted_cost_share_cents']}"
    )
    assert adjudicated["billed_cents"] == 15_000
    assert adjudicated["allowed_cents"] == 12_000, "allowed is billed times 0.80"
    assert adjudicated["patient_resp_cents"] == 14_500, (
        "the final variant reads the live deductible basis, so the whole allowed "
        f"amount falls on the patient, got {adjudicated['patient_resp_cents']}"
    )
    assert adjudicated["payer_paid_cents"] == 0
    assert adjudicated["patient_resp_cents"] - session["quoted_cost_share_cents"] == 6_100
    assert session["quoted_cost_share_cents"] == 8_400, (
        "the provisional quote is never rewritten by adjudication"
    )


def test_final_adjudicated_responsibility_skips_the_copay_offset_entirely():
    """PRD §3.3: "Its coinsurance rate and copay come from the newest verified
    snapshot, and this variant never carries the copay offset — the 500-cent
    step is skipped entirely."
    PRD §3.3: "Three independent differences therefore separate the two figures:
    the deductible basis, the out-of-pocket-room basis, and the presence or
    absence of the offset."

    Design: Difficulty/dual_variant_calc/cost_share_provisional_quote_diverges_from_final_adjudication
    """
    scenario = _divergence_setup()
    claim_id = scenario["claim"]["id"]
    session_id = scenario["session"]["id"]

    claim = validate_success(api_client.adjudicate_claim(claim_id, {"outcome": "PAID"}, OPS))

    # The offset-free raw figure is 0 + 0 + 14500; had the offset applied it
    # would have been 14000 and the two variants would not separate here.
    assert claim["patient_resp_cents"] == 14_500
    assert claim["allowed_cents"] == 12_000
    assert claim["payer_paid_cents"] == max(
        0, claim["allowed_cents"] - claim["patient_resp_cents"]
    )
    assert claim["claim_status"] == "PAID"
    assert get_session(session_id)["quoted_cost_share_cents"] == 8_400
    assert get_session(session_id)["billing_state"] == "PAYER_PAID"


def test_scheduled_basis_line_counts_denied_sessions_while_cash_basis_line_excludes_them():
    """PRD §3.6: "those clinicians earn on every `COMPLETED` session in the
    window that has a signed note, regardless of whether the payer has paid
    anything, so `gross_cents` counts unpaid and denied sessions and the denials
    are picked up later as clawback adjustments."
    PRD §3.6: "those clinicians earn only on sessions whose newest claim reads
    `PAID`, so `gross_cents` is strictly lower whenever any session in the window
    is unpaid or denied, and `adjustment_cents` carries no denial clawbacks at
    all because denied sessions were never included."

    Design: Difficulty/dual_variant_calc/payout_line_scheduled_basis_exceeds_cash_basis_for_identical_sessions
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(
        payer["id"],
        full_name="Zara Whitfield",
        weekly_caseload_target=8,
        availability_blocks=[
            {"weekday": 2, "start_minute": 480, "end_minute": 1080},
            {"weekday": 3, "start_minute": 480, "end_minute": 1080},
        ],
    )
    clinician = attached["clinician"]
    pat_a = make_verified_patient(payer["id"], full_name="Priya Anand", member_id="MBR-4410")
    pat_b = make_verified_patient(
        payer["id"], full_name="Marcus Cole", member_id="MBR-5182",
        verification={"deductible_remaining_cents": 40_000},
    )
    set_clock(CLOCK_DELIVERY)
    s_a = make_completed_session(clinician["id"], pat_a["id"], "2026-06-02T14:00:00Z", "2026-06-02T15:00:00Z")
    s_b = make_completed_session(clinician["id"], pat_b["id"], "2026-06-03T14:00:00Z", "2026-06-03T15:00:00Z")
    s_c = make_completed_session(clinician["id"], pat_a["id"], "2026-06-16T14:00:00Z", "2026-06-16T15:00:00Z")
    s_d = make_completed_session(clinician["id"], pat_b["id"], "2026-06-17T14:00:00Z", "2026-06-17T15:00:00Z")

    for session, outcome, code in (
        (s_a, "PAID", None),
        (s_b, "DENIED", "NOT_COVERED"),
        (s_c, "PAID", None),
        (s_d, "DENIED", "NOT_COVERED"),
    ):
        claim_id = submit_claim(session["id"])["id"]
        if code:
            adjudicate(claim_id, outcome, code)
        else:
            adjudicate(claim_id, outcome)

    b1 = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY")
    set_clock("2026-06-22T00:00:00Z")
    b2 = open_and_lock_batch("2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", "SEMIMONTHLY")
    b1_lines = get_batch_lines(b1["id"])
    b2_lines = get_batch_lines(b2["id"])

    assert_payout_batch(b1)
    assert b1["total_gross_cents"] == 30_000, "the scheduled basis counts both completed sessions"
    assert b1["total_adjustment_cents"] == 0
    assert b1["total_net_cents"] == 30_000
    assert b1["line_count"] == 1
    assert b2["total_gross_cents"] == 15_000, "the cash basis counts only the paid session"
    assert b2["total_adjustment_cents"] == 0
    assert b2["total_net_cents"] == 15_000
    assert b2["line_count"] == 1
    assert b1_lines[0]["basis"] == "SCHEDULED"
    assert b2_lines[0]["basis"] == "CASH_BASIS"
    assert b2_lines[0]["gross_cents"] == b1_lines[0]["gross_cents"] - 15_000, (
        "the 15000-cent divergence comes solely from the inclusion filter"
    )


def test_cash_basis_line_earns_only_on_sessions_whose_newest_claim_is_paid():
    """PRD §3.6: "A clinician is paid on the scheduled basis when the batch's
    `schedule` is `WEEKLY` or `BIWEEKLY` and the clinician does not carry
    `cash_basis_opt_in`".
    PRD §3.6: "A clinician is paid on the cash basis when they carry
    `cash_basis_opt_in` set to true or when the batch's `schedule` is
    `SEMICONTHLY`; those clinicians earn only on sessions whose newest claim reads
    `PAID`, so `gross_cents` is strictly lower whenever any session in the window
    is unpaid or denied, and `adjustment_cents` carries no denial clawbacks at all
    because denied sessions were never included."
    PRD §3.6: "Both variants read the same window and resolve rates identically,
    so the divergence is caused solely by the inclusion filter."

    Design: Difficulty/dual_variant_calc/payout_line_scheduled_basis_exceeds_cash_basis_for_identical_sessions
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(
        payer["id"],
        full_name="Zara Whitfield",
        availability_blocks=[
            {"weekday": 2, "start_minute": 480, "end_minute": 1080},
            {"weekday": 3, "start_minute": 480, "end_minute": 1080},
        ],
    )
    clinician = attached["clinician"]
    pat_a = make_verified_patient(payer["id"], full_name="Priya Anand", member_id="MBR-4410")
    pat_b = make_verified_patient(
        payer["id"], full_name="Marcus Cole", member_id="MBR-5182",
        verification={"deductible_remaining_cents": 40_000},
    )
    set_clock(CLOCK_DELIVERY)
    s_a = make_completed_session(clinician["id"], pat_a["id"], "2026-06-02T14:00:00Z", "2026-06-02T15:00:00Z")
    s_b = make_completed_session(clinician["id"], pat_b["id"], "2026-06-03T14:00:00Z", "2026-06-03T15:00:00Z")
    claim_a = submit_claim(s_a["id"])["id"]
    claim_b = submit_claim(s_b["id"])["id"]
    adjudicate(claim_a, "PAID")
    adjudicate(claim_b, "DENIED", "NOT_COVERED")

    # The very same two-session window, twice: WEEKLY earns on both, SEMIMONTHLY
    # earns only on the paid one.
    weekly = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY")
    weekly_lines = get_batch_lines(weekly["id"])
    assert weekly["total_net_cents"] == 30_000
    assert set(weekly_lines[0]["session_ids"]) == {s_a["id"], s_b["id"]}, (
        "the scheduled basis includes the session behind the DENIED claim"
    )
    assert weekly_lines[0]["adjustment_cents"] == 0, (
        "the denial was never assigned to a payout line, so no clawback exists"
    )
    assert_payout_line(weekly_lines[0])
    assert_payout_line_invariants(weekly_lines[0])

    semimonthly = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "SEMIMONTHLY")
    assert semimonthly["status"] == "LOCKED"
    semimonthly_lines = get_batch_lines(semimonthly["id"])
    assert semimonthly["total_net_cents"] == 15_000, (
        "the cash basis keeps only the session whose newest claim reads PAID"
    )
    assert semimonthly["line_count"] == 1
    assert set(semimonthly_lines[0]["session_ids"]) == {s_a["id"]}, (
        "the denied session is filtered out of the cash-basis line entirely"
    )