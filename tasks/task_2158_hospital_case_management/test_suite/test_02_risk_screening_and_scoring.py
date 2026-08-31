"""Risk screening: the weighted composite score, its two variants, the derived
barriers it raises, and the readmission-intervention bundle it drives."""
from test_helpers import (
    CASE_MANAGER,
    ApiErrorId,
    assert_screening,
    document_choice_payload,
    mark_episode_ready,
    move_barrier,
    open_barrier,
    place_offer,
    read_barriers,
    read_episode,
    record_bundle,
    setup_broadcast_referral,
    setup_screened_episode,
    validate_error,
    validate_success,
)

LAKESIDE = {
    "name": "Lakeside Choice", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}
NO_PCP_PATIENT = {
    "mrn": "MRN-1001", "full_name": "Ada Lin", "date_of_birth": "1948-03-12",
    "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": False,
}


def _placed_snf_episode_with_three_barriers():
    """Episode whose ADMISSION screening scores 50 / HIGH (raising one
    PHYSICIAN_ORDER barrier), plus two manually recorded barriers, and whose SNF
    referral has been driven to PLACED."""
    env = setup_broadcast_referral(
        payer=dict(LAKESIDE),
        patient=dict(NO_PCP_PATIENT),
        referral={
            "requested_level_of_care": "SNF", "projected_stay_days": 30,
            "needed_by": "2026-08-20T00:00:00Z",
        },
    )
    episode_id = env["episode"]["id"]
    open_barrier(episode_id, barrier_code="TRANSPORT", severity="MEDIUM",
                 delay_reason_code="AWAITING_TRANSPORT")
    open_barrier(episode_id, barrier_code="DME_DELIVERY", severity="LOW",
                 delay_reason_code="AWAITING_DME")
    env["offer"] = place_offer(
        env["referral"]["id"], env["provider_a"]["id"], env["referral_version"],
        daily_rate_cents=32808,
    )
    return env


def test_admission_variant_scores_the_screening_without_any_adjustment(api):
    """PRD §3.2: "The score itself is a weighted integer tally with no rounding anywhere.
    The base begins with prior-admission history: the smaller of
    `prior_admissions_snapshot` and a cap of four admissions, multiplied by eight points
    each — so a patient with seven prior admissions contributes the same 32 points as one
    with four. To that are added three deficit terms, each computed as ten minus the
    corresponding score so that a lower clinical score contributes more risk: the
    functional deficit weighted at three points per unit, the cognitive deficit at two
    points per unit, and the social-support deficit at two points per unit. Six further
    points are added when `lives_alone_snapshot` is true. Five further points are added
    when `has_pcp_snapshot` is false. And seven polypharmacy points are added when
    `medication_count` is at least ten — exactly ten qualifies."
    PRD §3.2: "Under `ADMISSION_VARIANT` — which applies when `screening_type` is
    `ADMISSION`, that is, a screening submitted while the case is still at admission or
    freshly screened — the adjustment is exactly zero: neither barrier history nor
    placement credit exists yet, so neither is consulted."
    PRD §3.2: "The base and the adjustment are summed and then clamped into the range 0
    through 100 inclusive, and the clamp is applied last, after the adjustment. The
    resulting `composite_risk_score` maps to a `risk_band` by threshold: 70 or above is
    `VERY_HIGH`, otherwise 50 or above is `HIGH`, otherwise 30 or above is `MODERATE`,
    and anything below 30 is `LOW`. The episode adopts the submitting screening's figures
    into `current_risk_score`, `current_risk_band`, and `risk_variant_applied`."

    Design: Difficulty/dual_variant_calc/risk_score_admission_variant_versus_predischarge_variant
    """
    env = setup_screened_episode(payer=dict(LAKESIDE), patient=dict(NO_PCP_PATIENT))
    screening = env["screening"]

    assert_screening(screening)
    assert screening["composite_risk_score"] == 50, (
        "16 prior-admission points + 6 functional + 4 cognitive + 12 social + 5 no-PCP "
        f"+ 7 polypharmacy == 50, got {screening['composite_risk_score']}"
    )
    assert screening["risk_band"] == "HIGH"
    assert screening["variant_applied"] == "ADMISSION_VARIANT"

    episode = read_episode(env["episode"]["id"])
    assert episode["current_risk_score"] == 50
    assert episode["current_risk_band"] == "HIGH"
    assert episode["risk_variant_applied"] == "ADMISSION_VARIANT"


def test_predischarge_variant_reprices_the_same_screening_at_mark_ready(api):
    """PRD §3.2: "Under `PREDISCHARGE_VARIANT` — which applies when `screening_type` is
    `RESCREEN`, and again as a side effect of the mark-ready declaration — the adjustment
    adds three points for each barrier in the episode's accumulated history, counting at
    most five barriers, so at most fifteen points; and it subtracts a twelve-point
    placement credit when the episode has a referral in `PLACED` status whose
    `requested_level_of_care` is `SNF`, `IRF`, or `LTACH`."
    PRD §3.2: "The barrier history term reads `barriers_ever_opened_count`, which counts
    every barrier row ever created on the episode in any status, waived ones included, and
    does not double-count a barrier that was reopened."
    PRD §3.8: "Once they have, the episode records `discharge_disposition` from the body,
    sets `marked_ready_by_user_id` to the acting `X-User-ID` and `marked_ready_at` to the
    logical clock instant, and then rescores: `current_risk_score` and `current_risk_band`
    are recomputed with the predischarge variant of the risk model described in §3.2,
    drawing on the episode's most recent `SUBMITTED` screening, and `risk_variant_applied`
    becomes `PREDISCHARGE_VARIANT`."

    Design: Difficulty/dual_variant_calc/risk_score_admission_variant_versus_predischarge_variant
    """
    env = _placed_snf_episode_with_three_barriers()
    episode_id = env["episode"]["id"]

    validate_success(
        api.document_choice(
            env["referral"]["id"],
            document_choice_payload(env["offer"]["id"], choice_basis="PATIENT_PREFERENCE"),
            CASE_MANAGER,
        )
    )
    for barrier in read_barriers(episode_id):
        move_barrier(barrier["id"], "RESOLVED")
    record_bundle(episode_id, pcp_followup_booked=True, med_reconciliation_completed=True)

    episode = mark_episode_ready(episode_id, "SNF")

    assert episode["case_status"] == "READY_FOR_DISCHARGE"
    assert episode["barriers_ever_opened_count"] == 3, (
        "one screening-derived barrier plus two manually recorded ones, all statuses "
        f"counted, got {episode['barriers_ever_opened_count']}"
    )
    assert episode["risk_variant_applied"] == "PREDISCHARGE_VARIANT"
    assert episode["current_risk_score"] == 47, (
        "the same 50-point base plus 9 points of barrier history less the 12-point SNF "
        f"placement credit == 47, got {episode['current_risk_score']}"
    )
    assert episode["current_risk_band"] == "MODERATE"


def test_nine_medications_stay_below_the_polypharmacy_threshold(api):
    """PRD §3.2: "And seven polypharmacy points are added when `medication_count` is at
    least ten — exactly ten qualifies."
    PRD §3.2: "The base and the adjustment are summed and then clamped into the range 0
    through 100 inclusive, and the clamp is applied last, after the adjustment. The
    resulting `composite_risk_score` maps to a `risk_band` by threshold: 70 or above is
    `VERY_HIGH`, otherwise 50 or above is `HIGH`, otherwise 30 or above is `MODERATE`,
    and anything below 30 is `LOW`. The episode adopts the submitting screening's figures
    into `current_risk_score`, `current_risk_band`, and `risk_variant_applied`."
    PRD §3.3: "The first rule fires when the freshly computed `risk_band` is `HIGH` or
    `VERY_HIGH` **and** `has_pcp_snapshot` is false; it creates a barrier with
    `barrier_code` of `PHYSICIAN_ORDER`, `severity` of `MEDIUM`, and `delay_reason_code`
    of `AWAITING_PHYSICIAN`."

    Design: Difficulty/boundary_precision_check/polypharmacy_threshold_at_exactly_ten_medications
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-6001", "full_name": "Lea Marchetti", "date_of_birth": "1950-10-10",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": False,
        },
        screening={
            "screening_type": "ADMISSION", "functional_score": 8, "cognitive_score": 8,
            "social_support_score": 4, "medication_count": 9,
        },
    )

    assert env["screening"]["composite_risk_score"] == 43, (
        "nine medications earn no polypharmacy points, so the base stops at 43, got "
        f"{env['screening']['composite_risk_score']}"
    )
    assert env["screening"]["risk_band"] == "MODERATE"

    barriers = read_barriers(env["episode"]["id"])
    assert barriers == [], (
        "a MODERATE band never triggers the physician-order derivation rule, got "
        f"{[b['barrier_code'] for b in barriers]}"
    )
    episode = read_episode(env["episode"]["id"])
    assert episode["barrier_posture"] == "CLEAR"
    assert episode["readmission_bundle_complete"] is False, (
        "a MODERATE band still requires pcp_followup_booked"
    )


def test_exactly_ten_medications_cross_the_polypharmacy_threshold(api):
    """PRD §3.2: "And seven polypharmacy points are added when `medication_count` is at
    least ten — exactly ten qualifies."
    PRD §3.3: "The first rule fires when the freshly computed `risk_band` is `HIGH` or
    `VERY_HIGH` **and** `has_pcp_snapshot` is false; it creates a barrier with
    `barrier_code` of `PHYSICIAN_ORDER`, `severity` of `MEDIUM`, and `delay_reason_code`
    of `AWAITING_PHYSICIAN`."
    PRD §3.3: "Both derived barriers carry `origin` of `SCREENING_AUTO`, `clock_start_at`
    at the logical clock instant, and the literal string `system` as `opened_by_user_id`."

    Design: Difficulty/boundary_precision_check/polypharmacy_threshold_at_exactly_ten_medications
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-6002", "full_name": "Moe Vasquez", "date_of_birth": "1950-10-10",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": False,
        },
        screening={
            "screening_type": "ADMISSION", "functional_score": 8, "cognitive_score": 8,
            "social_support_score": 4, "medication_count": 10,
        },
    )

    assert env["screening"]["composite_risk_score"] == 50, (
        "the tenth medication adds exactly the seven polypharmacy points, 43 -> 50, got "
        f"{env['screening']['composite_risk_score']}"
    )
    assert env["screening"]["risk_band"] == "HIGH"

    barriers = read_barriers(env["episode"]["id"])
    assert len(barriers) == 1, (
        f"the HIGH band with no PCP raises exactly one barrier, got {len(barriers)}"
    )
    derived = barriers[0]
    assert derived["barrier_code"] == "PHYSICIAN_ORDER"
    assert derived["severity"] == "MEDIUM"
    assert derived["delay_reason_code"] == "AWAITING_PHYSICIAN"
    assert derived["origin"] == "SCREENING_AUTO"
    assert derived["opened_by_user_id"] == "system"
    assert read_episode(env["episode"]["id"])["barrier_posture"] == "ACTIVE"


def test_resubmitting_a_submitted_screening_is_refused(api):
    """PRD §3.2: "Submission requires the screening to be in `DRAFT` — anything else is
    `ERR_INVALID_SCREENING_STATE` — and requires the owning episode's `case_status` to be
    one of `ADMITTED`, `SCREENED`, or `PLANNING`."
    PRD §3.3: "The second rule fires when `lives_alone_snapshot` is true **and**
    `functional_score` is 5 or below; it creates a barrier with `barrier_code` of
    `HOUSING`, `severity` of `HIGH`, and `delay_reason_code` of `AWAITING_FAMILY`."
    PRD §3.2: "Submission of an admission screening also advances the episode: when
    `case_status` is `ADMITTED` and the submitted screening belongs to that episode and
    carries `screening_type` of `ADMISSION`, `case_status` moves `ADMITTED → SCREENED`."

    Design: Corner/state_machines/screening_submitted_twice_returns_invalid_screening_state
    """
    env = setup_screened_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200},
        patient={
            "mrn": "MRN-C203", "full_name": "Eli Farr", "date_of_birth": "1945-05-05",
            "prior_admissions_180d": 2, "lives_alone": True, "has_pcp": True,
        },
        screening={
            "screening_type": "ADMISSION", "functional_score": 4, "cognitive_score": 8,
            "social_support_score": 4, "medication_count": 10,
        },
    )

    response = api.submit_screening(env["screening"]["id"], CASE_MANAGER)

    validate_error(response, ApiErrorId.ERR_INVALID_SCREENING_STATE, 409)
    assert env["screening"]["composite_risk_score"] == 63
    assert env["screening"]["risk_band"] == "HIGH"

    barriers = read_barriers(env["episode"]["id"])
    assert len(barriers) == 1, (
        "the has_pcp patient skips the physician-order rule and the refused resubmit "
        f"adds nothing, got {[b['barrier_code'] for b in barriers]}"
    )
    assert barriers[0]["barrier_code"] == "HOUSING"
    assert barriers[0]["severity"] == "HIGH"
    assert barriers[0]["delay_reason_code"] == "AWAITING_FAMILY"
    assert barriers[0]["origin"] == "SCREENING_AUTO"
    assert read_episode(env["episode"]["id"])["case_status"] == "SCREENED"


def test_very_high_band_requires_all_four_readmission_interventions(api):
    """PRD §3.8: "The required set is keyed on `current_risk_band` at the moment of
    evaluation. A `LOW` band requires nothing at all, and because the required set is
    empty it is vacuously satisfied, so `readmission_bundle_complete` reads true. A
    `MODERATE` band requires `pcp_followup_booked`. A `HIGH` band requires
    `pcp_followup_booked` and `med_reconciliation_completed`. A `VERY_HIGH` band requires
    all four: `pcp_followup_booked`, `med_reconciliation_completed`, `tcm_call_scheduled`,
    and `home_monitoring_enrolled`. `readmission_bundle_complete` is true exactly when
    every flag in the required set is true, and it is re-derived on every read or write of
    the episode."
    PRD §3.8: "Fourth, `readmission_bundle_complete` must be true, evaluated against the
    `current_risk_band` **in effect before** this transition's predischarge rescore, or the
    refusal is `ERR_READMISSION_BUNDLE_INCOMPLETE` (HTTP 422)."

    Design: Corner/calculations/readmission_bundle_requirement_scales_with_risk_band
    """
    env = setup_screened_episode(
        payer={"name": "Lakeside Choice", "coinsurance_pct": 0.200, "snf_auth_required": False},
        patient={
            "mrn": "MRN-C305", "full_name": "Pen Quintero", "date_of_birth": "1938-05-05",
            "prior_admissions_180d": 4, "lives_alone": True, "has_pcp": False,
        },
        screening={
            "screening_type": "ADMISSION", "functional_score": 2, "cognitive_score": 2,
            "social_support_score": 2, "medication_count": 12,
        },
    )
    episode_id = env["episode"]["id"]

    assert env["screening"]["composite_risk_score"] == 100, (
        "a raw 106 is clamped into 0..100, got "
        f"{env['screening']['composite_risk_score']}"
    )
    assert env["screening"]["risk_band"] == "VERY_HIGH"

    barriers = read_barriers(episode_id)
    assert len(barriers) == 2
    assert barriers[0]["barrier_code"] == "PHYSICIAN_ORDER"
    assert barriers[1]["barrier_code"] == "HOUSING"
    for barrier in barriers:
        move_barrier(barrier["id"], "RESOLVED")

    partial = record_bundle(
        episode_id, pcp_followup_booked=True, med_reconciliation_completed=True
    )
    assert partial["readmission_bundle_complete"] is False

    blocked = api.mark_ready(episode_id, {"discharge_disposition": "HOME_SELF_CARE"}, CASE_MANAGER)
    validate_error(blocked, ApiErrorId.ERR_READMISSION_BUNDLE_INCOMPLETE, 422)

    full = record_bundle(episode_id, tcm_call_scheduled=True, home_monitoring_enrolled=True)
    assert full["readmission_bundle_complete"] is True

    ready = validate_success(
        api.mark_ready(episode_id, {"discharge_disposition": "HOME_SELF_CARE"}, CASE_MANAGER)
    )
    assert ready["case_status"] == "READY_FOR_DISCHARGE"
