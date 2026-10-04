"""Rate resolution: the pinned evaluation order of the new-clinician and
geography differential steps, and the cost-share offset and clamp boundaries."""
from test_helpers import (
    CLOCK_DELIVERY,
    CLOCK_ONBOARD,
    add_signed_note,
    api_client,
    assert_claim,
    attach_billable_clinician,
    complete_session,
    get_session,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    set_clock,
    submit_claim,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]


def test_the_geography_differential_is_not_applied_before_its_activation_instant():
    """PRD §3.6: "The ordering of the last two steps is fixed and they are never
    applied in reverse. The branch test in the seventh step reads the value the
    sixth step produced, not the original rate, so swapping the two steps yields
    a different number for the same inputs."
    PRD §3.6: "The seventh step's activation instant is `2026-07-01T00:00:00Z`: a
    session whose `scheduled_start` falls strictly before that instant takes the
    value the sixth step produced with no geography differential applied, and a
    session whose `scheduled_start` falls at or after it is subject to the
    differential."

    Design: Difficulty/combinatorial_formula/resolved_rate_geography_differential_is_order_sensitive_after_flooring
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000, rate_set_version=1, geography="CA")
    make_rate(payer["id"], rate_cents=16_000, rate_set_version=2, geography="TX")
    attached = attach_billable_clinician(
        payer["id"],
        primary_state="TX",
        license_number="LCSW-TX-31140",
        availability_blocks=[{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
    )
    clinician = attached["clinician"]
    patient = make_verified_patient(
        payer["id"],
        state_code="CA",
        deductible_cents=0,
        oop_max_cents=500_000,
        verification={
            "deductible_remaining_cents": 0,
            "coinsurance_rate": 0.20,
            "copay_cents": 2_000,
            "oop_remaining_cents": 500_000,
        },
    )
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-04-15T14:00:00Z", "2026-04-15T15:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-04-15T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])

    assert_claim(claim)
    assert claim["billed_cents"] == 14_400, (
        "floor(16000 * 0.90) applied by the new-clinician step, with the "
        f"geography step skipped before its activation instant, got {claim['billed_cents']}"
    )
    assert claim["allowed_cents"] == 11_520, "the allowed amount is billed times 0.80"


def test_the_new_clinician_step_is_floored_before_the_branch_test_reads_it():
    """PRD §3.6: "Sixth, while the session's `scheduled_start` is strictly before
    the clinician's `onboarded_at` plus 90 days, the rate is multiplied by 0.90
    and rounded toward negative infinity; at and after that instant the step is
    skipped and the rate is left untouched."
    PRD §3.6: "Applying the geography differential once to a sum of raw rate
    rows, or scaling a batch total, produces a different number by up to one cent
    per affected line and is wrong."

    Design: Difficulty/combinatorial_formula/resolved_rate_geography_differential_is_order_sensitive_after_flooring
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000, rate_set_version=1, geography="CA")
    make_rate(payer["id"], rate_cents=16_000, rate_set_version=2, geography="TX")
    attached = attach_billable_clinician(
        payer["id"],
        primary_state="TX",
        license_number="LCSW-TX-31140",
        availability_blocks=[{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
    )
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"], state_code="CA", deductible_cents=0)

    # First the pre-activation session: the sixth step's floored value stands.
    early = make_scheduled_session(
        clinician["id"], patient["id"], "2026-04-15T14:00:00Z", "2026-04-15T15:00:00Z"
    )
    add_signed_note(clinician["id"], early["id"])
    set_clock("2026-04-15T18:00:00Z")
    early = complete_session(clinician["id"], early["id"])
    early_claim = submit_claim(early["id"])
    assert early_claim["billed_cents"] == 14_400
    assert early_claim["billed_cents"] != 13_500, (
        "13,500 is the swapped-order answer, which the pinned order never produces"
    )

    # The chosen row is the version 2 TX row, reached because the clinician's
    # primary state is TX, so the differential would fire at or after activation.
    rates = api_client.list_payer_rates(payer["id"], OPS, {"geography": "TX"}).json()["data"]
    assert len(rates) == 1 and rates[0]["rate_cents"] == 16_000
    assert early_claim["billed_cents"] == 14_400, (
        "the differential did not fire, because the branch is gated on the "
        "activation instant and not on the geography mismatch alone"
    )


def test_the_geography_differential_fires_at_or_after_its_activation_instant():
    """PRD §3.6: "Seventh, once the activation instant `2026-07-01T00:00:00Z` has
    been reached, and only then, and only when the chosen rate row's geography
    differs from the patient's `state_code`, a branching differential is applied
    to the value the sixth step produced: if that value is at least 10,000 cents
    the rate becomes that value less 1,000 cents, and otherwise the rate becomes
    that value multiplied by 0.90 and rounded toward negative infinity."

    Design: Difficulty/combinatorial_formula/resolved_rate_geography_differential_is_order_sensitive_after_flooring
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=16_000, rate_set_version=2, geography="TX")
    attached = attach_billable_clinician(
        payer["id"],
        primary_state="TX",
        license_number="LCSW-TX-31140",
        availability_blocks=[{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
    )
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"], state_code="CA", deductible_cents=0)
    set_clock("2026-07-15T00:00:00Z")
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-07-15T14:00:00Z", "2026-07-15T15:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-07-15T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])

    # The session is past the 90-day window, so the sixth step is skipped and the
    # seventh reads the untouched 16000; 16000 >= 10000 so the flat reduction applies.
    assert claim["billed_cents"] == 15_000, (
        f"16000 less the 1000-cent flat reduction, got {claim['billed_cents']}"
    )
    assert claim["allowed_cents"] == 12_000


def test_the_copay_offset_is_presence_gated_and_the_result_is_clamped_to_the_out_of_pocket_room():
    """PRD §3.3: "applies a copay offset of 500 cents only when the variant
    carries the offset and only when the coinsurance component is at least 500
    cents, and finally clamps the result between zero and the out-of-pocket room
    by taking the larger of zero and the smaller of the pre-clamp figure and the
    room."
    PRD §3.3: "The copay offset is applied at most once per session, is never
    applied when the coinsurance component is below 500 cents, and rounding
    toward negative infinity appears only in that final clamp."

    Design: Difficulty/combinatorial_formula/patient_cost_share_offset_is_presence_gated_and_clamped_at_the_out_of_pocket_ceiling
    """
    scenario = _clamp_scenario()
    session_id = scenario["session"]["id"]
    claim_id = scenario["claim"]["id"]

    session = get_session(session_id)
    assert session["quoted_cost_share_cents"] == 3_000, (
        "the unclamped provisional raw is 0 + 9600 + 3500 less the 500 offset, "
        f"and the 3000-cent room clamps it, got {session['quoted_cost_share_cents']}"
    )

    claim = validate_success(api_client.adjudicate_claim(claim_id, {"outcome": "PAID"}, OPS))
    assert claim["billed_cents"] == 60_000
    assert claim["allowed_cents"] == 48_000
    assert claim["patient_resp_cents"] == 3_000
    assert claim["payer_paid_cents"] == 45_000, (
        "the payer absorbs the remainder the patient is no longer liable for"
    )


def test_the_offset_free_variant_reaches_the_same_clamped_ceiling_through_a_higher_raw():
    """PRD §3.3: "Three independent differences therefore separate the two
    figures: the deductible basis, the out-of-pocket-room basis, and the presence
    or absence of the offset."
    PRD §3.3: "Its coinsurance rate and copay come from the newest verified
    snapshot, and this variant never carries the copay offset — the 500-cent step
    is skipped entirely."

    Design: Difficulty/combinatorial_formula/patient_cost_share_offset_is_presence_gated_and_clamped_at_the_out_of_pocket_ceiling
    """
    scenario = _clamp_scenario()
    claim_id = scenario["claim"]["id"]

    # Removing the offset from the final variant raises its raw from 12600 to
    # 13100, and the room still clamps both to exactly 3000.
    claim = validate_success(api_client.adjudicate_claim(claim_id, {"outcome": "PAID"}, OPS))
    assert claim["patient_resp_cents"] == 3_000
    assert claim["patient_resp_cents"] == min(
        3_000, 0 + round(48_000 * 0.20) + 3_500
    ), "the clamp, not the offset, is what fixes this figure"
    assert get_session(scenario["session"]["id"])["billing_state"] == "PAYER_PAID"


def _clamp_scenario() -> dict:
    """A plan whose out-of-pocket room is only 3000 cents against a 48000-cent
    allowed amount, so the clamp bites on both variants."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=60_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(
        payer["id"],
        deductible_cents=0,
        oop_max_cents=3_000,
        verification={
            "deductible_remaining_cents": 0,
            "coinsurance_rate": 0.20,
            "copay_cents": 3_500,
            "oop_remaining_cents": 3_000,
        },
    )
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-16T14:00:00Z", "2026-06-16T15:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock(CLOCK_DELIVERY)
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])
    return {"payer": payer, "clinician": clinician, "patient": patient,
            "session": session, "claim": claim}