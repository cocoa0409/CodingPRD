"""Discharge readiness and the discharge itself: the five mark-ready preconditions,
the discharge cascade, and the length-of-stay report."""
from test_helpers import (
    CASE_MANAGER,
    PLATFORM_ADMIN,
    SECOND_DISCHARGE_COORDINATOR,
    ApiErrorId,
    assert_throughput_report,
    confirm_order,
    create_dme_order,
    document_choice_payload,
    mark_episode_ready,
    open_episode,
    read_episode,
    read_logistics_order,
    read_referral,
    record_bundle,
    seed_dme_supplier,
    seed_patient,
    seed_payer,
    set_logical_clock,
    setup_choice_pending_referral,
    setup_screened_episode,
    validate_error,
    validate_success,
)

LAKESIDE = {
    "name": "Lakeside Choice", "coinsurance_pct": 0.200,
    "snf_auth_required": False, "hh_auth_required": False, "auth_expiry_days": 30,
}


def _ready_to_mark_snf_episode(mrn):
    """A PLANNING episode with a complete MODERATE bundle, no barriers, and a SNF
    referral that is still only CHOICE_PENDING."""
    env = setup_choice_pending_referral(
        payer=dict(LAKESIDE),
        patient={
            "mrn": mrn, "full_name": "Ovi Delacroix", "date_of_birth": "1946-07-07",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
        referral={"requested_level_of_care": "SNF", "projected_stay_days": 14,
                  "needed_by": "2026-08-20T00:00:00Z"},
        offer={"daily_rate_cents": 30000},
    )
    env["episode"] = record_bundle(env["episode"]["id"], pcp_followup_booked=True)
    return env


def test_a_post_acute_disposition_without_a_placed_referral_is_refused(api):
    """PRD §3.8: "Fifth, when the chosen disposition is `SNF`, `IRF`, `LTACH`, or
    `HOME_WITH_HH`, the episode must have at least one referral in `PLACED` status, or the
    refusal is `ERR_PLACEMENT_NOT_CONFIRMED` (HTTP 422); the three remaining dispositions
    carry no placement requirement."
    PRD §3.8: "The ordering of that fourth check deserves emphasis, because the transition
    itself changes the band. Bundle completeness is judged on the **pre-transition** band,
    and the predischarge rescore happens strictly after every precondition has passed."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_blocked_until_referral_reaches_placed
    """
    env = _ready_to_mark_snf_episode("MRN-7001")

    response = api.mark_ready(
        env["episode"]["id"], {"discharge_disposition": "SNF"}, CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_PLACEMENT_NOT_CONFIRMED, 422)
    episode = read_episode(env["episode"]["id"])
    assert episode["case_status"] == "PLANNING"
    assert episode["marked_ready_by_user_id"] is None
    assert episode["risk_variant_applied"] == "ADMISSION_VARIANT", (
        "the predischarge rescore never ran because a precondition failed"
    )
    assert read_referral(env["referral"]["id"])["status"] == "CHOICE_PENDING"


def test_documenting_the_choice_unlocks_the_post_acute_mark_ready(api):
    """PRD §3.8: "Fifth, when the chosen disposition is `SNF`, `IRF`, `LTACH`, or
    `HOME_WITH_HH`, the episode must have at least one referral in `PLACED` status, or the
    refusal is `ERR_PLACEMENT_NOT_CONFIRMED` (HTTP 422); the three remaining dispositions
    carry no placement requirement."
    PRD §3.5: "The referral moves `CHOICE_PENDING → PLACED`, recording
    `chosen_bed_offer_id`, `choice_basis` and `patient_choice_attested`, and its `version`
    advances by one."
    PRD §3.8: "Once they have, the episode records `discharge_disposition` from the body,
    sets `marked_ready_by_user_id` to the acting `X-User-ID` and `marked_ready_at` to the
    logical clock instant, and then rescores: `current_risk_score` and `current_risk_band`
    are recomputed with the predischarge variant of the risk model described in §3.2,
    drawing on the episode's most recent `SUBMITTED` screening, and `risk_variant_applied`
    becomes `PREDISCHARGE_VARIANT`."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_blocked_until_referral_reaches_placed
    """
    env = _ready_to_mark_snf_episode("MRN-7002")
    blocked = api.mark_ready(
        env["episode"]["id"], {"discharge_disposition": "SNF"}, CASE_MANAGER
    )
    validate_error(blocked, ApiErrorId.ERR_PLACEMENT_NOT_CONFIRMED, 422)

    placed = validate_success(
        api.document_choice(
            env["referral"]["id"],
            document_choice_payload(env["offer"]["id"], choice_basis="CLINICAL_MATCH"),
            CASE_MANAGER,
        )
    )
    assert placed["status"] == "PLACED"

    episode = validate_success(
        api.mark_ready(env["episode"]["id"], {"discharge_disposition": "SNF"}, CASE_MANAGER)
    )

    assert episode["case_status"] == "READY_FOR_DISCHARGE"
    assert episode["discharge_disposition"] == "SNF"
    assert episode["marked_ready_by_user_id"] == "cm-alpha"
    assert episode["marked_ready_at"] == "2026-08-01T00:00:00.000Z"
    assert episode["risk_variant_applied"] == "PREDISCHARGE_VARIANT"


def test_a_brand_new_episode_is_admitted_and_clear_and_cannot_be_marked_ready(api):
    """PRD §3.2: "A new episode starts with `case_status` of `ADMITTED`, `barrier_posture`
    of `CLEAR`, `assigned_case_manager_id` set to the creating operator's `X-User-ID`,
    `current_risk_score` of 0, `current_risk_band` of `LOW`, `risk_variant_applied` of
    `ADMISSION_VARIANT`, `logistics_committed_cents` and `authorized_days_total` both at
    zero, `discharge_disposition` null, and all four intervention flags false."
    PRD §3.8: "First, the episode's `case_status` must be `PLANNING`; anything else is
    `ERR_INVALID_EPISODE_STATE`."

    Design: Corner/state_machines/episode_initial_state_is_admitted_with_clear_posture
    """
    payer = seed_payer(**{"name": "Lakeside Choice", "coinsurance_pct": 0.200})
    patient = seed_patient(
        payer["id"], mrn="MRN-C202", full_name="Dot Emeka", date_of_birth="1947-04-04",
        prior_admissions_180d=2, lives_alone=False, has_pcp=True,
    )
    episode = open_episode(patient["id"])
    assert episode["case_status"] == "ADMITTED"
    assert episode["barrier_posture"] == "CLEAR"

    response = api.mark_ready(
        episode["id"], {"discharge_disposition": "HOME_SELF_CARE"}, CASE_MANAGER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_EPISODE_STATE, 409)
    after = read_episode(episode["id"])
    assert after["case_status"] == "ADMITTED"
    assert after["barrier_posture"] == "CLEAR"
    assert after["marked_ready_by_user_id"] is None


def test_discharge_completes_confirmed_orders_and_finalises_the_stay(api):
    """PRD §3.8: "A successful discharge moves `case_status` to the terminal `DISCHARGED`
    and sets `discharged_at` to the logical clock instant. Every `CONFIRMED` logistics
    order becomes `COMPLETED`, with `logistics_committed_cents` unchanged."
    PRD §3.9: "**Step three** computes `los_hours`: the elapsed time from `admitted_at` to
    `discharged_at` when the episode has been discharged, or to the logical clock now when
    it has not, measured in whole minutes, divided by 60 and rounded half up to one decimal
    place."
    PRD §2.10: "`Episode.logistics_committed_cents` is the sum of `cost_cents` across that
    episode's logistics orders in `CONFIRMED` or `COMPLETED` status; confirming an order
    credits it, cancelling a confirmed order debits it by the same amount, and completing a
    confirmed order leaves it untouched because completion stays inside the committed set."

    Design: Corner/state_machines/episode_discharge_cascades_to_orders_offers_and_finalises_metrics
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-C207", "full_name": "Ines Jung", "date_of_birth": "1943-09-09",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    supplier = seed_dme_supplier()
    record_bundle(env["episode"]["id"], pcp_followup_booked=True)
    order = create_dme_order(
        env["episode"]["id"], supplier["id"], item_code="HOSPITAL_BED",
        window_start="2026-08-02T09:00:00Z", window_end="2026-08-02T12:00:00Z",
    )
    confirm_order(order["id"])
    mark_episode_ready(env["episode"]["id"], "HOME_SELF_CARE")
    set_logical_clock("2026-08-08T00:00:00Z")

    discharged = validate_success(
        api.discharge_episode(env["episode"]["id"], SECOND_DISCHARGE_COORDINATOR)
    )

    assert discharged["case_status"] == "DISCHARGED"
    assert discharged["discharged_at"] == "2026-08-08T00:00:00.000Z"
    completed = read_logistics_order(order["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["cost_cents"] == 45000
    episode = read_episode(env["episode"]["id"])
    assert episode["logistics_committed_cents"] == 45000, (
        "a completed order stays inside the committed set"
    )
    assert episode["los_hours"] == 168.0
    assert episode["avoidable_delay_hours"] == 0.0
    assert episode["adjusted_los_hours"] == 168.0
    assert episode["risk_variant_applied"] == "PREDISCHARGE_VARIANT"


def test_discharge_is_refused_while_an_order_is_still_only_requested(api):
    """PRD §3.8: "And no logistics order on the episode may still be sitting in
    `REQUESTED`, or the refusal is `ERR_LOGISTICS_NOT_CONFIRMED` (HTTP 422): every
    arrangement must be either confirmed or cancelled before the patient leaves."
    PRD §3.7: "For a `DME_DELIVERY` order the cost is a flat published rate keyed on
    `item_code`: a hospital bed costs 45000 cents, an oxygen concentrator 32000 cents, a
    wheelchair 21000 cents, a walker 8000 cents, and a CPAP unit 27000 cents."
    PRD §3.8: "A successful discharge moves `case_status` to the terminal `DISCHARGED` and
    sets `discharged_at` to the logical clock instant. Every `CONFIRMED` logistics order
    becomes `COMPLETED`, with `logistics_committed_cents` unchanged."

    Design: Corner/errors/discharge_with_requested_order_returns_logistics_not_confirmed
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-E103", "full_name": "Dov Bassey", "date_of_birth": "1946-04-04",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    supplier = seed_dme_supplier()
    record_bundle(env["episode"]["id"], pcp_followup_booked=True)
    order = create_dme_order(
        env["episode"]["id"], supplier["id"], item_code="WHEELCHAIR",
        window_start="2026-08-02T09:00:00Z", window_end="2026-08-02T12:00:00Z",
    )
    mark_episode_ready(env["episode"]["id"], "HOME_SELF_CARE")

    refused = api.discharge_episode(env["episode"]["id"], SECOND_DISCHARGE_COORDINATOR)

    validate_error(refused, ApiErrorId.ERR_LOGISTICS_NOT_CONFIRMED, 422)
    assert read_episode(env["episode"]["id"])["case_status"] == "READY_FOR_DISCHARGE"
    assert order["cost_cents"] == 21000

    confirm_order(order["id"], SECOND_DISCHARGE_COORDINATOR)
    assert read_episode(env["episode"]["id"])["logistics_committed_cents"] == 21000

    discharged = validate_success(
        api.discharge_episode(env["episode"]["id"], SECOND_DISCHARGE_COORDINATOR)
    )
    assert discharged["case_status"] == "DISCHARGED"
    assert read_logistics_order(order["id"])["status"] == "COMPLETED"


def test_the_throughput_report_agrees_with_the_episode_it_reports_on(api):
    """PRD §3.9: "Throughput figures are recomputed as a side effect of the mark-ready
    declaration and again at discharge, and they are also available on demand as a
    per-episode report exposing `los_hours`, `avoidable_delay_hours`, `adjusted_los_hours`,
    `expected_los_hours`, `observed_expected_ratio`, `throughput_grade`,
    `current_risk_score`, `current_risk_band`, and `barriers_ever_opened_count`."
    PRD §3.9: "**Step five** computes `expected_los_hours` as `drg_gmlos_days` multiplied by
    24 to convert days into hours and then multiplied by an acuity multiplier keyed on the
    band from step one — 0.90 for `LOW`, 1.00 for `MODERATE`, 1.15 for `HIGH`, and 1.30 for
    `VERY_HIGH` — with the product rounded half up to one decimal place. **Step six**
    computes `observed_expected_ratio` as `adjusted_los_hours` divided by
    `expected_los_hours`, rounded half up to three decimal places."
    PRD §3.9: "Otherwise a ratio of 1.250 or below is `ABOVE_TARGET`."

    Design: Corner/endpoints/throughput_computed_read_agrees_with_stored_episode_fields
    """
    env = setup_screened_episode(
        payer=dict(LAKESIDE),
        patient={
            "mrn": "MRN-E001", "full_name": "Ada Yates", "date_of_birth": "1950-01-01",
            "prior_admissions_180d": 2, "lives_alone": False, "has_pcp": True,
        },
    )
    set_logical_clock("2026-08-06T00:00:00Z")

    report = validate_success(api.get_throughput(env["episode"]["id"], PLATFORM_ADMIN))
    episode = validate_success(api.get_episode(env["episode"]["id"], PLATFORM_ADMIN))

    assert_throughput_report(report)
    assert report["los_hours"] == 120.0
    assert report["avoidable_delay_hours"] == 0.0
    assert report["adjusted_los_hours"] == 120.0
    assert report["expected_los_hours"] == 108.0
    assert report["observed_expected_ratio"] == 1.111
    assert report["throughput_grade"] == "ABOVE_TARGET"
    assert report["current_risk_score"] == 45
    assert report["current_risk_band"] == "MODERATE"
    assert report["barriers_ever_opened_count"] == 0

    for field in (
        "los_hours", "avoidable_delay_hours", "adjusted_los_hours", "expected_los_hours",
        "observed_expected_ratio", "throughput_grade",
    ):
        assert report[field] == episode[field], (
            f"the report derives nothing of its own: {field} reads {report[field]} on the "
            f"report and {episode[field]} on the episode"
        )
