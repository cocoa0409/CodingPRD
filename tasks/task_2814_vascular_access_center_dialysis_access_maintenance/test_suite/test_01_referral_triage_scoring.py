"""Referral intake, the revision loop and triage scoring.

Every scenario here turns on how the triage calculation reads the surveillance
window, on how the revision loop counts its laps, and on the facility posture
that decides whether triage is legal at all.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success

EARLIER_AT = "2026-07-20T08:00:00Z"
LATEST_AT = "2026-07-28T08:00:00Z"


def _declining_access(api, center, access_type="AVG"):
    """An IN_USE access carrying a 1000 -> 700 decline inside the lookback window.

    The latest reading also carries a venous pressure of 160 mmHg and a
    recirculation of 12.0 percent, so the two level components both apply.
    """
    access = fx.seed_access_in_use(api, center["patient_id"], access_type=access_type)
    fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        EARLIER_AT,
        access_flow_ml_min=1000,
        venous_pressure_mmhg=120,
        recirculation_pct=4.0,
        kind="ROUTINE",
    )
    latest = fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        LATEST_AT,
        access_flow_ml_min=700,
        venous_pressure_mmhg=160,
        recirculation_pct=12.0,
        kind="URGENT",
    )
    return access, latest


def _single_reading_access(api, center, access_type="AVG"):
    """An IN_USE access carrying only the later of the two readings above."""
    access = fx.seed_access_in_use(api, center["patient_id"], access_type=access_type)
    latest = fx.seed_reading(
        api,
        access["id"],
        center["facility_id"],
        LATEST_AT,
        access_flow_ml_min=700,
        venous_pressure_mmhg=160,
        recirculation_pct=12.0,
        kind="URGENT",
    )
    return access, latest


def test_01_two_readings_score_trend_based_while_one_reading_scores_absolute_based(api):
    """Identical latest readings land in different urgency bands.

    The PRD states: "The consequence is deliberate and must not be smoothed away:
    two referrals with identical latest-reading values can earn different scores,
    and land in different urgency bands, purely because one facility had submitted
    a second reading inside the window and the other had not."

    Access A carries the 2026-07-20 flow of 1000 and the 2026-07-28 flow of 700, so
    two readings qualify: trend points are (1000 - 700) / 1000 * 100 * 1.2 = 36, the
    latest flow of 700 adds 12, the venous pressure of 160 adds 15, the
    recirculation of 12.0 adds 10 and the single missed treatment adds 6, for 79.
    Access B carries only the 2026-07-28 reading, so there is no trend component and
    the level component doubles to 20, for 51.

    Design: Difficulty/dual_variant_calc/triage_trend_based_vs_absolute_based_on_identical_latest_reading
    """
    center = fx.seed_center(api)
    access_a, _ = _declining_access(api, center)
    access_b, _ = _single_reading_access(api, center)

    referral_a = fx.seed_referral(
        api, access_a["id"], center["facility_id"], missed_treatment_count=1
    )
    referral_b = fx.seed_referral(
        api, access_b["id"], center["facility_id"], missed_treatment_count=1
    )

    triaged_a = validate_success(api.triage_referral(referral_a["id"], fx.COORDINATOR))
    triaged_b = validate_success(api.triage_referral(referral_b["id"], fx.COORDINATOR))

    assert triaged_a["triage_variant"] == "TREND_BASED"
    assert triaged_a["triage_score"] == 79
    assert triaged_a["urgency"] == "SAME_DAY"

    assert triaged_b["triage_variant"] == "ABSOLUTE_BASED"
    assert triaged_b["triage_score"] == 51
    assert triaged_b["urgency"] == "NEXT_DAY"

    # The whole 28-point gap is the variant: both referrals scored against a latest
    # reading of flow 700, venous pressure 160 and recirculation 12.0 with one
    # missed treatment.
    assert triaged_a["triage_score"] - triaged_b["triage_score"] == 28
    assert triaged_a["status"] == "TRIAGED"
    assert triaged_b["status"] == "TRIAGED"


def test_02_mechanical_triage_marks_the_access_dysfunctional_and_rescores_the_facility(api):
    """Both triages fire the mechanical side effect and leave the partner ACTIVE.

    The PRD states: "When the `suspected_problem` is `STENOSIS`, `THROMBOSIS` or
    `CATHETER_DYSFUNCTION` — that is, a mechanical failure rather than a
    `MATURATION_FAILURE` — and the referral's access is currently `IN_USE`, that
    access is moved `IN_USE → DYSFUNCTIONAL`."

    Two referrals of one missed treatment each leave the facility on a raw window
    count of 2 against a volume of 2; the grace credit reads the GOLD tier the
    previous evaluation persisted, floor(2 * 0.20) is 0, and the score is
    100 - 4 * 2 = 92, which keeps the contract ACTIVE.

    Design: Difficulty/dual_variant_calc/triage_trend_based_vs_absolute_based_on_identical_latest_reading
    """
    center = fx.seed_center(api)
    access_a, _ = _declining_access(api, center)
    access_b, _ = _single_reading_access(api, center)

    referral_a = fx.seed_referral(
        api, access_a["id"], center["facility_id"], missed_treatment_count=1
    )
    referral_b = fx.seed_referral(
        api, access_b["id"], center["facility_id"], missed_treatment_count=1
    )
    fx.triage(api, referral_a["id"])
    fx.triage(api, referral_b["id"])

    assert fx.read_access(api, access_a["id"])["status"] == "DYSFUNCTIONAL"
    assert fx.read_access(api, access_b["id"])["status"] == "DYSFUNCTIONAL"

    facility = fx.read_facility(api, center["facility_id"])
    assert facility["referral_volume_window"] == 2
    assert facility["raw_missed_count_window"] == 2
    assert facility["grace_credit_window"] == 0
    assert facility["adjusted_missed_count_window"] == 2
    assert facility["partnership_score"] == 92
    assert facility["partnership_tier"] == "GOLD"
    assert facility["contract_status"] == "ACTIVE"


def test_03_the_revision_loop_counts_its_laps_and_clears_the_prior_triage(api):
    """Two full information round trips, then a triage that scores the revised burden.

    The PRD states: "`info_request_count` is deliberately **not** decremented, which
    is what makes the revision loop countable: a referral that has been round-tripped
    three times still carries a count of 3."

    It also states: "Resubmission overwrites `clinical_narrative` with the new
    narrative and overwrites `missed_treatment_count` when the payload supplies one,
    clears `hold_reason` back to null, and — critically — clears `triage_score`,
    `triage_variant`, `urgency` and `triaged_at` all back to null, because a
    resubmitted referral must be re-triaged from scratch."

    The second resubmission drops the missed count to 0, so the score is
    36 + 12 + 15 + 10 = 73 rather than the 79 the same readings earned with one
    missed treatment.

    Design: Difficulty/non_linear_state_machine/referral_revision_loop_traversed_twice_then_locked_out_after_triage
    """
    center = fx.seed_center(api)
    access, _ = _declining_access(api, center)
    referral = fx.seed_referral(
        api, access["id"], center["facility_id"], missed_treatment_count=1
    )

    held = fx.request_info(
        api, referral["id"], info_request_note="need the last three flow trends"
    )
    assert held["status"] == "INFO_REQUESTED"
    assert held["hold_reason"] == "COORDINATOR_REQUEST"
    assert held["info_request_count"] == 1

    revised = fx.resubmit(
        api,
        referral["id"],
        center["facility_headers"],
        clinical_narrative="revised A",
        missed_treatment_count=3,
    )
    assert revised["status"] == "SUBMITTED"
    assert revised["hold_reason"] is None
    assert revised["clinical_narrative"] == "revised A"
    assert revised["missed_treatment_count"] == 3
    assert revised["info_request_count"] == 1

    held_again = fx.request_info(
        api, referral["id"], info_request_note="missed treatment tally looks wrong"
    )
    assert held_again["info_request_count"] == 2

    revised_again = fx.resubmit(
        api,
        referral["id"],
        center["facility_headers"],
        clinical_narrative="revised B",
        missed_treatment_count=0,
    )
    assert revised_again["status"] == "SUBMITTED"
    assert revised_again["clinical_narrative"] == "revised B"
    assert revised_again["missed_treatment_count"] == 0
    assert revised_again["info_request_count"] == 2
    # A resubmitted referral has no triage outcome left to read.
    assert revised_again["triage_score"] is None
    assert revised_again["triage_variant"] is None
    assert revised_again["urgency"] is None
    assert revised_again["triaged_at"] is None

    triaged = fx.triage(api, referral["id"])
    assert triaged["status"] == "TRIAGED"
    assert triaged["triage_variant"] == "TREND_BASED"
    assert triaged["triage_score"] == 73
    assert triaged["urgency"] == "SAME_DAY"
    assertions.assert_instant_equals(
        triaged["triaged_at"], "2026-08-01T00:00:00Z", "triaged_at"
    )


def test_04_a_triaged_referral_refuses_a_third_information_request(api):
    """The loop is closed once triage succeeds, and the count stays where it stopped.

    The PRD states: "Requesting information on a referral that is not `SUBMITTED`, or
    resubmitting one that is not `INFO_REQUESTED`, is refused with
    `ERR_REFERRAL_STATE_INVALID`."

    The successful lap is also the only lap with side effects: the access moved to
    DYSFUNCTIONAL once, and the triage rescore read the resubmitted missed count of
    0, which returns the facility to a score of 100.

    Design: Difficulty/non_linear_state_machine/referral_revision_loop_traversed_twice_then_locked_out_after_triage
    """
    center = fx.seed_center(api)
    access, _ = _declining_access(api, center)
    referral = fx.seed_referral(
        api, access["id"], center["facility_id"], missed_treatment_count=1
    )

    fx.request_info(api, referral["id"])
    fx.resubmit(
        api,
        referral["id"],
        center["facility_headers"],
        clinical_narrative="revised A",
        missed_treatment_count=3,
    )
    fx.request_info(api, referral["id"])
    fx.resubmit(
        api,
        referral["id"],
        center["facility_headers"],
        clinical_narrative="revised B",
        missed_treatment_count=0,
    )
    fx.triage(api, referral["id"])

    rejected = api.request_referral_info(
        referral["id"],
        {"info_request_note": "third lap attempt"},
        fx.COORDINATOR,
    )
    validate_error(rejected, "ERR_REFERRAL_STATE_INVALID", 409)

    after = fx.read_referral(api, referral["id"])
    assert after["status"] == "TRIAGED"
    assert after["info_request_count"] == 2
    assert after["triage_score"] == 73

    assert fx.read_access(api, access["id"])["status"] == "DYSFUNCTIONAL"

    facility = fx.read_facility(api, center["facility_id"])
    assert facility["raw_missed_count_window"] == 0
    assert facility["partnership_score"] == 100


def test_05_a_suspended_facility_blocks_triage_of_an_innocent_sibling_referral(api):
    """Referral B is faultless, and is refused because of what referral A did to the facility.

    The PRD states: "The referring facility's `contract_status` must be `ACTIVE` or
    `PROBATION`; a `SUSPENDED` facility's referrals cannot be triaged and the attempt
    is refused with `ERR_FACILITY_SUSPENDED`."

    Referral A arrives with fifteen missed treatments, so its own submission scores
    the facility at 100 - 4 * 15 = 40 against the seeded SILVER grace rate of
    floor(1 * 0.10) = 0, suspends it, and holds A itself. Referral B then arrives to a
    facility that is already SUSPENDED, so no posture transition fires and B is never
    held: it stays SUBMITTED with a null hold reason.

    Design: Difficulty/cross_entity_state_dependency/triage_legality_depends_on_the_facility_posture_and_is_restored_by_declining_a_sibling
    """
    center = fx.seed_center(api)
    access, _ = _declining_access(api, center)

    referral_a = fx.seed_referral(
        api, access["id"], center["facility_id"], missed_treatment_count=15
    )
    facility = fx.read_facility(api, center["facility_id"])
    assert facility["partnership_score"] == 40
    assert facility["grace_credit_window"] == 0
    assert facility["adjusted_missed_count_window"] == 15
    assert facility["partnership_tier"] == "WATCH"
    assert facility["contract_status"] == "SUSPENDED"

    held_a = fx.read_referral(api, referral_a["id"])
    assert held_a["status"] == "INFO_REQUESTED"
    assert held_a["hold_reason"] == "FACILITY_POSTURE_HOLD"
    assert held_a["info_request_count"] == 1

    referral_b = fx.seed_referral(
        api, access["id"], center["facility_id"], missed_treatment_count=0
    )
    assert referral_b["status"] == "SUBMITTED"
    assert referral_b["hold_reason"] is None
    unchanged = fx.read_facility(api, center["facility_id"])
    assert unchanged["referral_volume_window"] == 2
    assert unchanged["raw_missed_count_window"] == 15
    assert unchanged["partnership_score"] == 40

    refused = api.triage_referral(referral_b["id"], fx.COORDINATOR)
    validate_error(refused, "ERR_FACILITY_SUSPENDED", 409)

    still_submitted = fx.read_referral(api, referral_b["id"])
    assert still_submitted["status"] == "SUBMITTED"
    assert still_submitted["triage_score"] is None
    assert fx.read_access(api, access["id"])["status"] == "IN_USE"


def test_06_declining_the_offending_referral_restores_the_posture_and_unblocks_triage(api):
    """Declining A lifts the facility back to ACTIVE, and only then can B be triaged.

    The PRD states: "`DECLINED` referrals are excluded from membership, which is the
    mechanism by which declining a referral raises the score."

    It also states: "Upward posture transitions fire **no** cascade whatsoever."
    So the decline does not release referral A, which keeps its posture hold as audit
    history; the same triage call that was refused a moment ago now succeeds and
    scores 36 + 12 + 15 + 10 = 73.

    Design: Difficulty/cross_entity_state_dependency/triage_legality_depends_on_the_facility_posture_and_is_restored_by_declining_a_sibling
    """
    center = fx.seed_center(api)
    access, _ = _declining_access(api, center)
    referral_a = fx.seed_referral(
        api, access["id"], center["facility_id"], missed_treatment_count=15
    )
    referral_b = fx.seed_referral(
        api, access["id"], center["facility_id"], missed_treatment_count=0
    )
    validate_error(
        api.triage_referral(referral_b["id"], fx.COORDINATOR),
        "ERR_FACILITY_SUSPENDED",
        409,
    )

    declined = fx.decline(
        api, referral_a["id"], decline_reason="facility withdrew the request"
    )
    assert declined["status"] == "DECLINED"
    assert declined["decline_reason"] == "facility withdrew the request"
    assert declined["hold_reason"] == "FACILITY_POSTURE_HOLD"

    restored = fx.read_facility(api, center["facility_id"])
    assert restored["referral_volume_window"] == 1
    assert restored["raw_missed_count_window"] == 0
    assert restored["partnership_score"] == 100
    assert restored["partnership_tier"] == "GOLD"
    assert restored["contract_status"] == "ACTIVE"

    triaged = fx.triage(api, referral_b["id"])
    assert triaged["triage_variant"] == "TREND_BASED"
    assert triaged["triage_score"] == 73
    assert triaged["urgency"] == "SAME_DAY"
    assert fx.read_access(api, access["id"])["status"] == "DYSFUNCTIONAL"
