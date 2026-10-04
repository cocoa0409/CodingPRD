"""Calculation results: rate selection, the telehealth gate, the floored
differential, the allowed ratio, the post-payment clawback and the enrollment
window derivation."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EARLY,
    add_signed_note,
    api_client,
    attach_billable_clinician,
    complete_session,
    get_batch_lines,
    get_clinician,
    get_session,
    make_enrollment,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    open_and_lock_batch,
    set_clock,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]


def test_the_higher_rate_set_version_wins_on_overlapping_windows():
    """PRD §3.6: "Second, the winner is the candidate with the highest
    `rate_set_version`; when two candidates share the highest version, the winner
    is the one with the largest `created_at`"

    Design: Corner/calculations/resolved_rate_selects_the_highest_rate_set_version_on_overlapping_windows
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000, rate_set_version=1)
    make_rate(
        payer["id"], rate_cents=18_000, rate_set_version=2,
        effective_from="2026-06-01T00:00:00Z",
    )
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])

    rates, meta = validate_paginated(
        api_client.list_payer_rates(payer["id"], OPS, {"license_type": "LCSW", "geography": "CA"})
    )
    assert len(rates) == 2 and meta["total_count"] == 2
    assert claim["billed_cents"] == 18_000, (
        "the version 2 row wins outright rather than averaging to 16500"
    )


def test_a_rate_row_whose_end_instant_equals_the_session_start_is_out_of_the_candidate_set():
    """PRD §3.6: "and whose window covers the session's `scheduled_start` under
    the half-open rule — `effective_from` at or before the start, and
    `effective_to` null or strictly after the start."
    PRD §3.2: "The validity window is half-open — `effective_from` inclusive,
    `effective_to` exclusive — and an open-ended row has `effective_to` null."

    Design: Corner/calculations/resolved_rate_ignores_a_rate_row_whose_end_instant_has_already_passed
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(
        payer["id"], rate_cents=15_000, rate_set_version=1,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-03T16:00:00Z",
    )
    make_rate(
        payer["id"], rate_cents=16_000, rate_set_version=2,
        effective_from="2026-06-03T16:00:00Z",
    )
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(
        payer["id"],
        verification={
            "deductible_remaining_cents": 0,
            "coinsurance_rate": 0.20,
            "copay_cents": 3_000,
            "oop_remaining_cents": 200_000,
        },
    )
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )

    # The version 1 window closes exactly where the session opens, so it drops
    # out; the version 2 row's inclusive start admits it. The quote follows from
    # the version 2 rate: round_half_up(16000 * 0.80) = 12800, then
    # 0 + round_half_up(12800 * 0.20) + 3000 - 500 == 5060.
    assert session["quoted_cost_share_cents"] == 5_060


def test_the_telehealth_gate_collapses_the_rate_to_zero_on_a_video_session():
    """PRD §3.6: "Fifth, when the session's modality is `VIDEO` and the
    clinician's license for eligible practice does not permit telehealth into the
    primary state, the rate is zero and the following two steps are skipped
    entirely."
    PRD §3.3: "The estimator shares one body across both of its variants: it
    takes the allowed amount `S` for the session — zero when no rate row
    resolved"

    Design: Corner/calculations/resolved_rate_is_zero_when_the_license_cannot_telehealth_into_the_patient_state
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(
        payer["id"], license_overrides={"telehealth_eligible": False}
    )
    clinician = attached["clinician"]
    patient = make_verified_patient(
        payer["id"],
        verification={
            "deductible_remaining_cents": 0,
            "coinsurance_rate": 0.20,
            "copay_cents": 3_000,
            "oop_remaining_cents": 200_000,
        },
    )
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    assert session["quoted_cost_share_cents"] == 3_000, (
        "with the allowed amount at zero the raw is the copay alone, and the "
        "500-cent offset is suppressed because the coinsurance component is "
        f"below 500 cents, got {session['quoted_cost_share_cents']}"
    )

    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])
    assert claim["billed_cents"] == 0, (
        "the pinned non-eligible constant, not the 15000-cent contract rate"
    )
    assert claim["allowed_cents"] == 0


def test_the_new_clinician_differential_floors_an_odd_contract_rate():
    """PRD §2.5: "The new-clinician and geography differentials in rate
    resolution, and the payer-paid clamp, round toward negative infinity."
    PRD §3.6: "Sixth, while the session's `scheduled_start` is strictly before
    the clinician's `onboarded_at` plus 90 days, the rate is multiplied by 0.90
    and rounded toward negative infinity"

    Design: Corner/calculations/resolved_rate_floors_the_new_clinician_differential_on_an_odd_contract_rate
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=16_999)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(
        payer["id"],
        verification={
            "deductible_remaining_cents": 0,
            "coinsurance_rate": 0.20,
            "copay_cents": 3_000,
            "oop_remaining_cents": 200_000,
        },
    )
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-02-04T16:00:00Z", "2026-02-04T17:00:00Z"
    )

    # floor(16999 * 0.90) == 15299, and the quote is built from the allowed
    # amount: round_half_up(15299 * 0.80) == 12239, then
    # 0 + round_half_up(12239 * 0.20) + 3000 - 500 == 4948.
    assert session["quoted_cost_share_cents"] == 4_948


def test_the_provisional_quote_and_the_final_responsibility_coexist_on_their_own_entities():
    """PRD §3.3: "The final adjudicated variant applies at adjudication and reads
    its bases from live accumulators instead."
    PRD §3.3: "A patient with no snapshot reading `VERIFIED` cannot reach the
    estimator at all, because both booking and adjudication gate on exactly that."

    Design: Corner/calculations/cost_share_variant_selection_is_driven_by_the_endpoint_that_triggers_it
    """
    scenario = _variant_scenario()
    claim_id = scenario["claim"]["id"]
    session_id = scenario["session"]["id"]

    before = get_session(session_id)["quoted_cost_share_cents"]
    assert before == 4_900, "the booking snapshot basis produced this figure"

    claim = validate_success(api_client.adjudicate_claim(claim_id, {"outcome": "PAID"}, OPS))
    assert claim["patient_resp_cents"] == 15_000, (
        "the final variant reads the patient's full 100000-cent deductible"
    )
    assert get_session(session_id)["quoted_cost_share_cents"] == before, (
        "the session's provisional quote is preserved rather than overwritten"
    )
    assert claim["allowed_cents"] == 12_000
    assert claim["payer_paid_cents"] == 0


def test_the_allowed_ratio_is_applied_to_the_billed_amount_not_to_the_raw_rate_row():
    """PRD §3.5: "The claim's `allowed_cents` is that billed amount multiplied by
    0.80 and rounded half up."
    PRD §3.5: "The ratio and the differentials mean the allowed amount cannot be
    recomputed from the rate row's `rate_cents` directly; it is derived from the
    billed amount that the differentials actually produced."

    Design: Corner/calculations/payout_line_applies_the_eighty_percent_ratio_to_the_billed_amount
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000, rate_set_version=1)
    make_rate(
        payer["id"], rate_cents=18_000, rate_set_version=2,
        effective_from="2026-06-01T00:00:00Z",
    )
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])

    assert claim["billed_cents"] == 18_000
    assert claim["allowed_cents"] == 14_400
    assert claim["allowed_cents"] != 12_000, (
        "12,000 would come from applying the ratio to the version 1 rate"
    )
    assert claim["claim_status"] == "SUBMITTED"
    assert claim["submitted_on"] == "2026-06-03T18:00:00Z"
    assert get_session(session["id"])["billing_state"] == "CLAIM_SUBMITTED"
    assert get_session(session["id"])["claim_id"] == claim["id"]


def test_a_denial_landing_after_payment_is_reconciled_on_a_later_batch_with_an_unfloored_net():
    """PRD §3.6: "Against a session on a `PAID` line, the adjustment is likewise
    the negative of the resolved session rate but the net is allowed to go
    negative with no floor, and that negative value is meant to be seen."
    PRD §3.6: "Lines in `PAID` contribute their `net_cents`; lines in `PENDING`
    contribute zero; lines in `CLAWED_BACK` contribute their `adjustment_cents`,
    which is to say the negative reversal rather than the original gross."

    Design: Corner/calculations/payout_line_records_a_post_payment_denial_as_a_clawback_on_a_later_batch
    """
    scenario = _denied_after_payment_scenario()
    claim_id = scenario["claim"]["id"]

    denied = validate_success(
        api_client.adjudicate_claim(
            claim_id, {"outcome": "DENIED", "denial_code": "MISSING_DOCUMENTATION"}, OPS
        )
    )
    assert denied["claim_status"] == "DENIED"
    assert denied["denial_code"] == "MISSING_DOCUMENTATION"

    set_clock("2026-06-22T00:00:00Z")
    b2 = open_and_lock_batch("2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", "WEEKLY")
    assert b2["total_adjustment_cents"] == -15_000
    assert b2["total_net_cents"] == -15_000, (
        "the negative net is not floored, because the floor applies only to PENDING lines"
    )
    b1 = validate_success(api_client.get_payout_batch(scenario["batch"]["id"], OPS))
    assert b1["total_net_cents"] == 15_000, (
        "batch one's totals were frozen as a snapshot at lock time"
    )


def test_an_open_ended_enrollment_window_reports_nothing_while_a_bounded_one_reports_whole_days():
    """PRD §3.2: "The derived `effective_window_days` is the whole number of days
    between the two instants while `effective_to` is set, and null while the
    enrollment is open-ended."
    PRD §3.2: "A zero-length or inverted window is refused at 422 with
    `ERR_ENROLLMENT_WINDOW_INVALID`: the window is half-open, so a window that
    closes exactly where it opens is invalid rather than empty"

    Design: Corner/calculations/enrollment_effective_window_days_is_null_when_the_window_is_open_ended
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]

    open_row = make_enrollment(
        clinician["id"], payer["id"], effective_from="2026-01-01T00:00:00Z"
    )
    open_row = validate_success(api_client.activate_payer_enrollment(open_row["id"], OPS))
    assert open_row["status"] == "EFFECTIVE"
    assert open_row["effective_window_days"] is None
    assert open_row["rate_set_version_pinned"] == 1

    bounded = make_enrollment(
        clinician["id"], payer["id"], effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-07-01T00:00:00Z",
    )
    bounded = validate_success(api_client.activate_payer_enrollment(bounded["id"], OPS))
    assert bounded["effective_window_days"] == 181

    zero = api_client.create_payer_enrollment(
        {
            "clinician_id": clinician["id"],
            "payer_id": payer["id"],
            "delegated": False,
            "effective_from": "2026-03-01T00:00:00Z",
            "effective_to": "2026-03-01T00:00:00Z",
        },
        OPS,
    )
    validate_error(zero, ApiErrorId.ERR_ENROLLMENT_WINDOW_INVALID)
    assert zero.status_code == 422
    assert get_clinician(clinician["id"])["enrolled_payer_count"] == 3, (
        "the attachment fixture's own EFFECTIVE enrollment plus the open-ended "
        "and bounded rows; the refused zero-length window adds nothing"
    )


def _variant_scenario() -> dict:
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(
        payer["id"],
        verification={
            "deductible_remaining_cents": 0,
            "coinsurance_rate": 0.20,
            "copay_cents": 3_000,
            "oop_remaining_cents": 200_000,
        },
    )
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])
    return {"payer": payer, "clinician": clinician, "patient": patient,
            "session": session, "claim": claim}


def _denied_after_payment_scenario() -> dict:
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])
    validate_success(api_client.adjudicate_claim(claim["id"], {"outcome": "PAID"}, OPS))

    set_clock("2026-06-09T00:00:00Z")
    batch = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY")
    batch = validate_success(api_client.pay_payout_batch(batch["id"], OPS))
    lines = get_batch_lines(batch["id"])
    assert lines[0]["line_status"] == "PAID"
    assert lines[0]["gross_cents"] == 15_000 and lines[0]["adjustment_cents"] == 0
    return {"payer": payer, "clinician": clinician, "patient": patient,
            "session": session, "claim": claim, "batch": batch}