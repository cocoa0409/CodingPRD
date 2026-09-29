"""Arithmetic edges: ranking keys, capped projections, waterfalls and truncation."""
from test_helpers import (
    ASSESSMENT_REFERRAL_REQUIRED,
    ASSESSMENT_TREATMENT_AUTHORIZED,
    ASSIGNMENT_ACTIVE,
    ASSIGNMENT_CANCELLED,
    BILLING_INVOICED,
    CLINIC_CLOSED,
    CLINIC_OPEN,
    CLOCK_START,
    COMPLAINT_EAR_PAIN,
    COMPLAINT_FLU_LIKE,
    COMPLAINT_RASH,
    DESTINATION_FAX,
    DESTINATION_PATIENT_PORTAL,
    QUEUE_CALLED,
    QUEUE_SCHEDULED,
    QUEUE_WAITING,
    REASON_FEVER_THRESHOLD,
    REASON_RED_FLAG,
    REFERRAL_EMERGENCY_DEPARTMENT,
    REFERRAL_URGENT_CARE,
    REVIEW_PENDING,
    ROLE_KIND_FLOAT,
    SAMPLED_RANDOM_SAMPLE,
    SERVICE_RAPID_STREP_TEST,
    SUMMARY_QUEUED,
    VISIT_CLOSED,
    VISIT_REFERRED,
    VISIT_TREATED,
    ApiErrorId,
    add_appointment,
    add_walk_in,
    assert_instant_equal,
    assert_money_conserved,
    call_next,
    checkout,
    closed_insured_visit,
    create_clinic,
    create_clinician,
    create_insured_patient,
    create_patient,
    create_protocol,
    float_coverage_payload,
    read_clinic,
    read_clinician,
    read_patient,
    read_physician,
    read_queue_entry,
    read_visit,
    run_sampling,
    screening_visit,
    staffed_clinic,
    start_assessment,
    submit_assessment,
    treated_visit,
    validate_error,
    validate_paginated,
    validate_success,
    verify_active_coverage,
    visit_payload,
)

SAMPLING_WINDOW_START = "2026-08-01T00:00:00Z"
SAMPLING_WINDOW_END = "2026-08-02T00:00:00Z"
REVIEW_DUE_AT = "2026-08-04T00:00:00Z"
SHIFT_ENDS_AT = "2026-08-01T23:00:00Z"


# ---------------------------------------------------------------------------
# corner_call_next_ranks_by_priority_score_before_arrival_order
# ---------------------------------------------------------------------------

def _adult_then_geriatric_walk_in(api):
    """A 439-month adult queues first, a 919-month geriatric patient queues second."""
    env = staffed_clinic(api, protocol={"acuity_tier": 2})
    adult = create_patient(api, env["front_desk"], full_name="Adam Adult",
                           date_of_birth="1990-01-01")
    geriatric = create_patient(api, env["front_desk"], full_name="Gina Geriatric",
                               date_of_birth="1950-01-01")
    env["adult"] = adult
    env["geriatric"] = geriatric
    env["adult_entry"] = add_walk_in(api, env, adult["id"])
    env["geriatric_entry"] = add_walk_in(api, env, geriatric["id"])
    return env


def test_the_geriatric_walk_in_scores_sixty_points_above_the_adult(api):
    """Identical tier-2 complaints score 200 and 260 because of the age bump alone.

    PRD: "**Vulnerable age** contributes a flat 60 points when the patient's age in
    whole months, computed against the logical clock as described in §3.4, is below 24
    months — under two years old — or is 780 months or more, meaning 65 years and older;
    otherwise 0."

    Design: Corner/calculations/corner_call_next_ranks_by_priority_score_before_arrival_order
    """
    env = _adult_then_geriatric_walk_in(api)

    assert env["adult_entry"]["priority_score"] == 200
    assert env["geriatric_entry"]["priority_score"] == 260
    assert env["adult_entry"]["acuity_tier"] == env["geriatric_entry"]["acuity_tier"] == 2


def test_the_higher_scoring_second_arrival_is_called_before_the_earlier_one(api):
    """Descending priority is the first ranking key, so arrival order only breaks ties.

    PRD: "Candidates are ranked by descending `priority_score`, then by ascending
    `arrived_at`, then by ascending `created_at`, and the first entry after that ranking
    is the winner; the entry's `id` never participates in the ordering."

    Design: Corner/calculations/corner_call_next_ranks_by_priority_score_before_arrival_order
    """
    env = _adult_then_geriatric_walk_in(api)

    first = call_next(api, env)
    second = call_next(api, env)

    assert first["id"] == env["geriatric_entry"]["id"]
    assert first["patient_id"] == env["geriatric"]["id"]
    assert second["patient_id"] == env["adult"]["id"]


def test_the_winning_call_stamps_the_clock_and_measures_a_zero_realized_wait(api):
    """Arrival and call happen at the same logical instant, so the wait floors to 0.

    PRD: "The winning entry's `called_at` is stamped with the logical clock, and its
    `realized_wait_minutes` is measured as the whole minutes elapsed from `arrived_at`
    to `called_at`, discarding any partial minute."

    Design: Corner/calculations/corner_call_next_ranks_by_priority_score_before_arrival_order
    """
    env = _adult_then_geriatric_walk_in(api)

    call_next(api, env)

    entry = read_queue_entry(api, env["geriatric_entry"]["id"])
    assert entry["status"] == QUEUE_CALLED
    assert_instant_equal(entry["called_at"], CLOCK_START)
    assert entry["realized_wait_minutes"] == 0


# ---------------------------------------------------------------------------
# corner_call_next_excludes_scheduled_appointments_and_returns_queue_empty
# ---------------------------------------------------------------------------

def _one_booked_appointment_nobody_arrived_for(api):
    """An OPEN clinic whose only entry is a 09:00 booking, with the clock at 00:00."""
    env = staffed_clinic(api)
    patient = create_patient(api, env["front_desk"], full_name="Sam Scheduled",
                             date_of_birth="1988-08-18")
    env["patient"] = patient
    env["entry"] = add_appointment(api, env, patient["id"], "2026-08-01T09:00:00Z")
    return env


def test_call_next_refuses_when_the_only_entry_is_a_booked_appointment(api):
    """A SCHEDULED booking is not in the candidate set, so the queue reads as empty.

    PRD: "Selection considers only that clinic's entries in `WAITING` status —
    `SCHEDULED`, `CALLED`, `SERVED`, `ABANDONED` and `DEFERRED_CLOSURE` entries are all
    excluded — and each candidate's `priority_score` is recomputed at evaluation time so
    that accrued waiting is honoured."

    Design: Corner/calculations/corner_call_next_excludes_scheduled_appointments_and_returns_queue_empty
    """
    env = _one_booked_appointment_nobody_arrived_for(api)

    response = api.call_next(env["clinic_id"], env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_QUEUE_EMPTY, 409)


def test_the_refused_call_leaves_the_booking_scheduled_and_uncalled(api):
    """Nothing was consumed, so the entry keeps its booked status and a null call stamp.

    PRD: "When the clinic has no `WAITING` entry at all, the call is refused with
    `ERR_QUEUE_EMPTY`."

    Design: Corner/calculations/corner_call_next_excludes_scheduled_appointments_and_returns_queue_empty
    """
    env = _one_booked_appointment_nobody_arrived_for(api)

    api.call_next(env["clinic_id"], env["clinician_headers"])

    entry = read_queue_entry(api, env["entry"]["id"])
    assert entry["status"] == QUEUE_SCHEDULED
    assert entry["called_at"] is None


def test_a_booking_outside_the_next_hour_adds_nothing_to_the_posted_wait(api):
    """09:00 lies outside the half-open [00:00, 01:00) lookahead, so the posted wait is 0.

    PRD: "To it is added 10 minutes for each appointment at the clinic that is still
    `SCHEDULED` and whose `scheduled_at` falls inside the next hour, counted on a
    half-open basis from the current logical clock up to but not including one hour
    later."

    Design: Corner/calculations/corner_call_next_excludes_scheduled_appointments_and_returns_queue_empty
    """
    env = _one_booked_appointment_nobody_arrived_for(api)

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["open_status"] == CLINIC_OPEN
    assert clinic["waiting_count"] == 0
    assert clinic["posted_wait_minutes"] == 0


# ---------------------------------------------------------------------------
# corner_posted_wait_projection_is_capped_at_one_hundred_twenty_minutes
# ---------------------------------------------------------------------------

def _seven_walk_ins_against_one_clinician(api):
    """Capacity 8, one clinician on duty, seven uncalled walk-ins in the room."""
    env = staffed_clinic(api, clinic={"walk_in_queue_capacity": 8})
    env["entries"] = []
    for index in range(7):
        patient = create_patient(api, env["front_desk"],
                                 full_name=f"Cap {index + 1}",
                                 date_of_birth=f"1991-0{index + 1}-11")
        env["entries"].append(add_walk_in(api, env, patient["id"]))
    return env


def test_seven_waiting_against_one_clinician_posts_the_capped_one_hundred_twenty(api):
    """ceil(7/1) * 20 projects 140 minutes, and the cap lands last to clamp it to 120.

    PRD: "The rounding-up happens before the multiplication and the cap is applied last:
    for a clinic with three patients waiting, two clinicians on duty and one appointment
    in the coming hour, the projection is two patients per clinician, forty minutes of
    visits, plus ten minutes of appointment blending, for a posted figure of 50 minutes."

    Design: Corner/calculations/corner_posted_wait_projection_is_capped_at_one_hundred_twenty_minutes
    """
    env = _seven_walk_ins_against_one_clinician(api)

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["waiting_count"] == 7
    assert clinic["on_duty_clinician_count"] == 1
    assert clinic["posted_wait_minutes"] == 120
    assert clinic["open_status"] == CLINIC_OPEN


def test_the_seventh_walk_in_is_still_admitted_into_the_waiting_room(api):
    """Six waiting walk-ins are below the capacity of 8, so the seventh joins WAITING.

    PRD: "Inside the same request the entry advances `SCHEDULED → WAITING`, its
    `arrived_at` is stamped with the logical clock, its `priority_score` is computed, the
    clinic's `waiting_count` rises by 1 and `posted_wait_minutes` is recomputed from the
    new depth."

    Design: Corner/calculations/corner_posted_wait_projection_is_capped_at_one_hundred_twenty_minutes
    """
    env = _seven_walk_ins_against_one_clinician(api)

    seventh = read_queue_entry(api, env["entries"][6]["id"])

    assert seventh["status"] == QUEUE_WAITING
    assert_instant_equal(seventh["arrived_at"], CLOCK_START)


def test_a_capped_projection_still_reports_no_realized_wait_at_all(api):
    """The projection is forward-looking, so an uncalled queue has measured nothing yet.

    PRD: "Until the first patient at a site is ever called, both the entry-level
    `realized_wait_minutes` and the clinic-level `last_realized_wait_minutes` remain
    null."

    Design: Corner/calculations/corner_posted_wait_projection_is_capped_at_one_hundred_twenty_minutes
    """
    env = _seven_walk_ins_against_one_clinician(api)

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["last_realized_wait_minutes"] is None
    assert read_queue_entry(api, env["entries"][0]["id"])["realized_wait_minutes"] is None


# ---------------------------------------------------------------------------
# corner_summary_destination_waterfall_takes_fax_then_portal_then_nothing
# ---------------------------------------------------------------------------

def _three_closed_visits_down_the_destination_waterfall(api):
    """Fay has a fax-only PCP, Portia has no address, Nora never gave consent."""
    env = staffed_clinic(api)
    env["fay"] = create_insured_patient(
        api, env["front_desk"], full_name="Fay Fax", date_of_birth="1970-10-10",
        payer_name="BlueCo", member_id="M-7001", pcp_name="Dr Fax PCP",
        pcp_direct_address="fax:+14155550001", pcp_accepts_electronic_summary=False,
        pcp_consent_on_file=True)
    env["fay_bundle"] = closed_insured_visit(api, env, env["fay"]["id"])
    env["portia"] = create_insured_patient(
        api, env["front_desk"], full_name="Portia Portal",
        date_of_birth="1971-11-11", payer_name="BlueCo", member_id="M-7002",
        pcp_name="Dr Portal PCP", pcp_consent_on_file=True)
    env["portia_bundle"] = closed_insured_visit(api, env, env["portia"]["id"])
    env["nora"] = create_insured_patient(
        api, env["front_desk"], full_name="Nora NoConsent",
        date_of_birth="1972-12-12", payer_name="BlueCo", member_id="M-7003",
        pcp_name="Dr No PCP", pcp_direct_address="pcp2@direct.example",
        pcp_accepts_electronic_summary=True, pcp_consent_on_file=False)
    env["nora_bundle"] = closed_insured_visit(api, env, env["nora"]["id"])
    return env


def _summaries_for(api, env, visit_id):
    rows, meta = validate_paginated(
        api.list_visit_summaries(env["admin"], params={"visit_id": visit_id}))
    return rows, meta


def test_an_address_without_electronic_acceptance_routes_the_summary_to_fax(api):
    """The middle branch of the waterfall keeps the address and calls the route FAX.

    PRD: "When an address exists but electronic delivery is not accepted,
    `destination_kind` is `FAX` and `destination_address` is again that address — a fax
    number in this case."

    Design: Corner/calculations/corner_summary_destination_waterfall_takes_fax_then_portal_then_nothing
    """
    env = _three_closed_visits_down_the_destination_waterfall(api)

    rows, meta = _summaries_for(api, env, env["fay_bundle"]["visit_id"])

    assert meta["total_count"] == 1
    assert rows[0]["destination_kind"] == DESTINATION_FAX
    assert rows[0]["destination_address"] == "fax:+14155550001"


def test_a_patient_with_no_address_at_all_routes_to_the_patient_portal(api):
    """The last branch has nowhere to send to, so the address field stays null.

    PRD: "When no address exists at all, `destination_kind` is `PATIENT_PORTAL` and
    `destination_address` is null."

    Design: Corner/calculations/corner_summary_destination_waterfall_takes_fax_then_portal_then_nothing
    """
    env = _three_closed_visits_down_the_destination_waterfall(api)

    rows, meta = _summaries_for(api, env, env["portia_bundle"]["visit_id"])

    assert meta["total_count"] == 1
    assert rows[0]["destination_kind"] == DESTINATION_PATIENT_PORTAL
    assert rows[0]["destination_address"] is None


def test_a_patient_without_consent_generates_no_summary_row_at_all(api):
    """The consent gate suppresses creation entirely rather than minting a blocked row.

    PRD: "A patient without consent on file generates no summary at all, and there is
    nothing to transmit later."

    Design: Corner/calculations/corner_summary_destination_waterfall_takes_fax_then_portal_then_nothing
    """
    env = _three_closed_visits_down_the_destination_waterfall(api)

    rows, meta = _summaries_for(api, env, env["nora_bundle"]["visit_id"])

    assert meta["total_count"] == 0
    assert rows == []
    assert read_visit(api, env["nora_bundle"]["visit_id"])["billing_status"] == \
        BILLING_INVOICED


def test_a_summary_minted_by_a_treated_closure_is_queued_without_a_referral(api):
    """Both consenting patients closed from TREATED, so neither summary carries one.

    PRD: "And when — and only when — the patient's `pcp_consent_on_file` is true, a visit
    summary is created in `QUEUED` status for delivery to their primary care provider,
    with `includes_referral` set true if the visit closed from `REFERRED` and false if it
    closed from `TREATED`."

    Design: Corner/calculations/corner_summary_destination_waterfall_takes_fax_then_portal_then_nothing
    """
    env = _three_closed_visits_down_the_destination_waterfall(api)

    fay_rows, _ = _summaries_for(api, env, env["fay_bundle"]["visit_id"])
    portia_rows, _ = _summaries_for(api, env, env["portia_bundle"]["visit_id"])

    for row in (fay_rows[0], portia_rows[0]):
        assert row["status"] == SUMMARY_QUEUED
        assert row["includes_referral"] is False


# ---------------------------------------------------------------------------
# corner_referral_comparison_operators_are_asymmetric_at_the_ceilings
# ---------------------------------------------------------------------------

def _two_assessments_submitted_at_the_vital_ceilings(api):
    """Ed sits exactly on the HR and SpO2 bounds; Flo sits exactly on the temp ceiling."""
    env = staffed_clinic(api, protocol={"max_temp_c": 39.5, "max_heart_rate_bpm": 120,
                                        "min_spo2_pct": 92})
    ed = create_patient(api, env["front_desk"], full_name="Ed Edge",
                        date_of_birth="1985-05-05")
    env["ed_bundle"] = screening_visit(api, env, ed["id"])
    ed_assessment = start_assessment(api, env, env["ed_bundle"]["visit_id"],
                                     temp_c=39.4, heart_rate_bpm=120, spo2_pct=92,
                                     red_flag_codes=[])
    env["ed_submitted"] = submit_assessment(api, env, ed_assessment["id"])

    flo = create_patient(api, env["front_desk"], full_name="Flo Fever",
                         date_of_birth="1986-06-06")
    env["flo_bundle"] = screening_visit(api, env, flo["id"])
    flo_assessment = start_assessment(api, env, env["flo_bundle"]["visit_id"],
                                      temp_c=39.5, heart_rate_bpm=118, spo2_pct=92,
                                      red_flag_codes=[])
    env["flo_submitted"] = submit_assessment(api, env, flo_assessment["id"])
    return env


def test_a_heart_rate_and_saturation_exactly_at_their_bounds_do_not_refer(api):
    """120 is not strictly above 120 and 92 is not strictly below 92, so nothing fires.

    PRD: "When no trigger fires, both fields stay null and the assessment advances
    `DRAFT → TREATMENT_AUTHORIZED` instead."

    Design: Corner/calculations/corner_referral_comparison_operators_are_asymmetric_at_the_ceilings
    """
    env = _two_assessments_submitted_at_the_vital_ceilings(api)

    assert env["ed_submitted"]["status"] == ASSESSMENT_TREATMENT_AUTHORIZED
    assert env["ed_submitted"]["referral_reason_code"] is None
    assert env["ed_submitted"]["referral_destination"] is None


def test_the_unreferred_visit_takes_the_treatment_branch(api):
    """Ed's encounter reaches TREATED with the referral flag left down.

    PRD: "On the treatment branch, the linked visit advances `IN_ASSESSMENT → TREATED`,
    its `referral_required` flag is set false, no prescription cascade fires at all, and
    prescribing becomes legal for the first time."

    Design: Corner/calculations/corner_referral_comparison_operators_are_asymmetric_at_the_ceilings
    """
    env = _two_assessments_submitted_at_the_vital_ceilings(api)

    visit = read_visit(api, env["ed_bundle"]["visit_id"])

    assert visit["clinical_status"] == VISIT_TREATED
    assert visit["referral_required"] is False


def test_a_temperature_exactly_at_the_ceiling_refers_to_urgent_care(api):
    """The temperature comparison is the inclusive one, so 39.5 against 39.5 fires.

    PRD: "A **fever threshold** fires when `temp_c` is at or above the protocol's
    `max_temp_c`, and it directs to an urgent care."

    Design: Corner/calculations/corner_referral_comparison_operators_are_asymmetric_at_the_ceilings
    """
    env = _two_assessments_submitted_at_the_vital_ceilings(api)

    assert env["flo_submitted"]["status"] == ASSESSMENT_REFERRAL_REQUIRED
    assert env["flo_submitted"]["referral_reason_code"] == REASON_FEVER_THRESHOLD
    assert env["flo_submitted"]["referral_destination"] == REFERRAL_URGENT_CARE


def test_the_referred_visit_takes_the_escalation_branch(api):
    """Flo's encounter reaches REFERRED with the referral flag raised.

    PRD: "On the referral branch, the linked visit advances `IN_ASSESSMENT → REFERRED`
    and its `referral_required` flag is set true; then every prescription on that visit
    whose status is `DRAFT` or `ROUTED` is cancelled; then, for each prescription that was
    cancelled, the patient's `active_therapy_classes` and `active_therapy_class_count` are
    recomputed."

    Design: Corner/calculations/corner_referral_comparison_operators_are_asymmetric_at_the_ceilings
    """
    env = _two_assessments_submitted_at_the_vital_ceilings(api)

    visit = read_visit(api, env["flo_bundle"]["visit_id"])

    assert visit["clinical_status"] == VISIT_REFERRED
    assert visit["referral_required"] is True


# ---------------------------------------------------------------------------
# corner_referral_precedence_picks_red_flag_over_hypoxia
# ---------------------------------------------------------------------------

def _an_assessment_with_all_four_triggers_firing(api):
    """STRIDOR, SpO2 88, temp 39.6 and heart rate 130 all fire on one submission."""
    env = staffed_clinic(api, protocol={"red_flag_codes": ["STRIDOR"],
                                        "max_temp_c": 39.5,
                                        "max_heart_rate_bpm": 120,
                                        "min_spo2_pct": 92})
    ray = create_patient(api, env["front_desk"], full_name="Ray RedFlag",
                         date_of_birth="1980-01-20")
    env["bundle"] = screening_visit(api, env, ray["id"])
    assessment = start_assessment(api, env, env["bundle"]["visit_id"], temp_c=39.6,
                                  heart_rate_bpm=130, spo2_pct=88,
                                  red_flag_codes=["STRIDOR"])
    env["assessment_id"] = assessment["id"]
    env["submitted"] = submit_assessment(api, env, assessment["id"])
    return env


def test_a_red_flag_outranks_a_hypoxic_saturation_in_the_recorded_reason(api):
    """Four triggers fire and the first in the fixed order wins, so it is RED_FLAG.

    PRD: "When at least one trigger fires, the winner is chosen by **positional
    precedence, not by destination severity**: red flag outranks hypoxia, hypoxia
    outranks fever threshold, and fever threshold outranks tachycardia."

    Design: Corner/calculations/corner_referral_precedence_picks_red_flag_over_hypoxia
    """
    env = _an_assessment_with_all_four_triggers_firing(api)

    assert env["submitted"]["status"] == ASSESSMENT_REFERRAL_REQUIRED
    assert env["submitted"]["referral_reason_code"] == REASON_RED_FLAG


def test_the_red_flag_trigger_directs_the_patient_to_an_emergency_department(api):
    """The intersection with the protocol's codes is non-empty, so the route is the ED.

    PRD: "A **red flag** fires when the intersection between the assessment's
    `red_flag_codes` and the protocol's `red_flag_codes` is non-empty, and it directs the
    patient to an emergency department."

    Design: Corner/calculations/corner_referral_precedence_picks_red_flag_over_hypoxia
    """
    env = _an_assessment_with_all_four_triggers_firing(api)

    assert env["submitted"]["referral_destination"] == REFERRAL_EMERGENCY_DEPARTMENT


def test_the_precedence_winner_still_escalates_the_linked_visit(api):
    """Whichever trigger wins, the visit itself moves to REFERRED with the flag raised.

    PRD: "On the referral branch, the linked visit advances `IN_ASSESSMENT → REFERRED`
    and its `referral_required` flag is set true; then every prescription on that visit
    whose status is `DRAFT` or `ROUTED` is cancelled; then, for each prescription that was
    cancelled, the patient's `active_therapy_classes` and `active_therapy_class_count` are
    recomputed."

    Design: Corner/calculations/corner_referral_precedence_picks_red_flag_over_hypoxia
    """
    env = _an_assessment_with_all_four_triggers_firing(api)

    visit = read_visit(api, env["bundle"]["visit_id"])

    assert visit["clinical_status"] == VISIT_REFERRED
    assert visit["referral_required"] is True


def test_an_uncosigned_referral_records_no_cosigning_physician(api):
    """Only a cosignature writes that field, and nobody has signed this referral.

    PRD: "A successful cosignature moves the assessment to `COSIGNED`, records the acting
    physician in `cosigned_by_physician_id` and stamps `cosigned_at` with the logical
    clock."

    Design: Corner/calculations/corner_referral_precedence_picks_red_flag_over_hypoxia
    """
    env = _an_assessment_with_all_four_triggers_firing(api)

    assert env["submitted"]["cosigned_by_physician_id"] is None
    assert env["submitted"]["cosigned_at"] is None


# ---------------------------------------------------------------------------
# corner_referred_visit_checkout_uses_referral_truncated_variant
# ---------------------------------------------------------------------------

def _referred_insured_visit_checked_out_with_an_add_on(api):
    """Tina is referred on a 39.7 temperature, then checked out claiming a strep test."""
    env = staffed_clinic(api, protocol={"base_price_cents": 9900, "max_temp_c": 39.5})
    tina = create_insured_patient(
        api, env["front_desk"], full_name="Tina Truncated",
        date_of_birth="1982-02-22", payer_name="BlueCo", member_id="M-8008",
        pcp_consent_on_file=False)
    env["tina"] = tina
    env["bundle"] = treated_visit(api, env, tina["id"],
                                  vitals={"temp_c": 39.7, "heart_rate_bpm": 96,
                                          "spo2_pct": 97})
    env["quoted"] = verify_active_coverage(api, env, env["bundle"]["visit_id"],
                                           copay_cents=2500, coinsurance_pct=12.5)
    env["closed"] = checkout(api, env, env["bundle"]["visit_id"],
                             services_rendered=[SERVICE_RAPID_STREP_TEST])
    return env


def test_the_insured_estimate_at_eligibility_time_still_prices_the_full_base(api):
    """Eligibility runs before any truncation, so the quote is the ordinary 3425.

    PRD: "Concretely, subtract `copay_cents` from the protocol's `base_price_cents`, apply
    `coinsurance_pct` to that remainder, round the product to whole cents half up, and add
    the copay back."

    Design: Corner/calculations/corner_referred_visit_checkout_uses_referral_truncated_variant
    """
    env = _referred_insured_visit_checked_out_with_an_add_on(api)

    assert env["bundle"]["assessment"]["status"] == ASSESSMENT_REFERRAL_REQUIRED
    assert env["quoted"]["quoted_price_cents"] == 3425


def test_a_referred_checkout_drops_the_add_on_line_and_halves_the_base(api):
    """The submitted strep test never reaches the bill and 9900 halves to 4950.

    PRD: "A referred visit is priced differently: every add-on line is dropped and the
    base line alone is billed at half the protocol's `base_price_cents`, with that halved
    figure rounded to whole cents half up."

    Design: Corner/calculations/corner_referred_visit_checkout_uses_referral_truncated_variant
    """
    env = _referred_insured_visit_checked_out_with_an_add_on(api)

    assert env["closed"]["final_price_cents"] == 4950
    assert env["closed"]["final_price_cents"] != 13400


def test_the_truncated_visit_splits_3119_to_the_patient_and_1831_to_the_payer(api):
    """A 2500 copay plus round_half_up(4950 * 0.125) is 3119, leaving the payer 1831.

    PRD: "Had the same visit ended in referral instead, the add-on lines would have
    vanished and the base line would have halved to 4950, making the patient responsible
    for 3119 and the payer for 1831 — the same clinical inputs the treated variant prices
    at 16200."

    Design: Corner/calculations/corner_referred_visit_checkout_uses_referral_truncated_variant
    """
    env = _referred_insured_visit_checked_out_with_an_add_on(api)

    assert env["closed"]["patient_responsibility_cents"] == 3119
    assert env["closed"]["payer_responsibility_cents"] == 1831
    assert_money_conserved(env["closed"])


def test_the_referred_checkout_closes_invoices_and_moves_the_balance(api):
    """REFERRED closes without a cosignature and the 3119 lands on the patient's balance.

    PRD: "The `clinical_status` moves `TREATED → CLOSED` or `REFERRED → CLOSED`; the
    `billing_status` moves `COVERAGE_VERIFIED → INVOICED` or `SELF_PAY_ACCEPTED →
    INVOICED` in the same request; the patient's `outstanding_balance_cents` is recomputed
    from scratch across their invoiced visits; the visit's `version` is incremented."

    Design: Corner/calculations/corner_referred_visit_checkout_uses_referral_truncated_variant
    """
    env = _referred_insured_visit_checked_out_with_an_add_on(api)

    assert env["closed"]["clinical_status"] == VISIT_CLOSED
    assert env["closed"]["billing_status"] == BILLING_INVOICED
    assert read_patient(api, env["tina"]["id"])["outstanding_balance_cents"] == 3119


# ---------------------------------------------------------------------------
# corner_visit_age_above_protocol_max_returns_out_of_protocol_scope
# ---------------------------------------------------------------------------

def _an_adult_called_against_a_paediatric_only_protocol(api):
    """Owen is 559 months old and the EAR_PAIN protocol stops at 216."""
    env = staffed_clinic(api, protocol={"complaint_code": COMPLAINT_EAR_PAIN,
                                       "min_age_months": 24,
                                       "max_age_months": 216,
                                       "base_price_cents": 8800,
                                       "acuity_tier": 1,
                                       "red_flag_codes": ["MASTOID_SWELLING"],
                                       "max_heart_rate_bpm": 150})
    owen = create_patient(api, env["front_desk"], full_name="Owen Overage",
                          date_of_birth="1979-12-15")
    env["owen"] = owen
    entry = add_walk_in(api, env, owen["id"], complaint_code=COMPLAINT_EAR_PAIN)
    env["entry_id"] = entry["id"]
    env["called"] = call_next(api, env)
    return env


def test_an_age_above_the_protocol_ceiling_is_out_of_scope_for_retail_care(api):
    """559 whole months against a 216-month ceiling is refused with 422.

    PRD: "An age below the floor or above the ceiling is out of scope for retail care and
    the visit is refused with `ERR_OUT_OF_PROTOCOL_SCOPE`."

    Design: Corner/calculations/corner_visit_age_above_protocol_max_returns_out_of_protocol_scope
    """
    env = _an_adult_called_against_a_paediatric_only_protocol(api)

    response = api.create_visit(visit_payload(env["entry_id"]),
                                env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_OUT_OF_PROTOCOL_SCOPE, 422)


def test_the_age_scope_rung_is_reached_only_after_the_entry_has_been_called(api):
    """The call itself succeeds and picks Owen's entry; the age check comes later.

    PRD: "The patient's age in whole months must fall inside the effective band described
    in §3.4, else `ERR_OUT_OF_PROTOCOL_SCOPE` (422). This rung guards visit creation."

    Design: Corner/calculations/corner_visit_age_above_protocol_max_returns_out_of_protocol_scope
    """
    env = _an_adult_called_against_a_paediatric_only_protocol(api)

    assert env["called"]["id"] == env["entry_id"]
    assert env["called"]["status"] == QUEUE_CALLED


def test_the_refused_visit_does_not_consume_the_called_entry(api):
    """Consumption to SERVED is part of a successful opening, so CALLED survives.

    PRD: "The visit copies its `clinic_id`, its `patient_id` and its `complaint_code` from
    the entry it consumes, and the consumed entry advances `CALLED → SERVED` in the same
    request."

    Design: Corner/calculations/corner_visit_age_above_protocol_max_returns_out_of_protocol_scope
    """
    env = _an_adult_called_against_a_paediatric_only_protocol(api)

    api.create_visit(visit_payload(env["entry_id"]), env["clinician_headers"])

    assert read_queue_entry(api, env["entry_id"])["status"] == QUEUE_CALLED


def test_the_out_of_scope_patient_ends_up_with_no_visit_row_at_all(api):
    """Nothing was written, so the patient's visit collection stays empty.

    PRD: "An age below the floor or above the ceiling is out of scope for retail care and
    the visit is refused with `ERR_OUT_OF_PROTOCOL_SCOPE`."

    Design: Corner/calculations/corner_visit_age_above_protocol_max_returns_out_of_protocol_scope
    """
    env = _an_adult_called_against_a_paediatric_only_protocol(api)

    api.create_visit(visit_payload(env["entry_id"]), env["clinician_headers"])

    rows, meta = validate_paginated(
        api.list_visits(env["admin"], params={"patient_id": env["owen"]["id"]}))
    assert rows == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# corner_chart_review_sampling_ceils_target_and_ranks_pool_by_acuity
# ---------------------------------------------------------------------------

def _three_closed_charts_of_mixed_acuity_then_a_sampling_run(api):
    """RASH (acuity 1), FLU_LIKE (acuity 3) and RASH again, closed in that order."""
    env = staffed_clinic(api, protocol={"complaint_code": COMPLAINT_RASH,
                                       "acuity_tier": 1,
                                       "base_price_cents": 9000,
                                       "min_age_months": 24,
                                       "max_heart_rate_bpm": 140,
                                       "red_flag_codes": ["SADDLE_ANESTHESIA"]})
    create_protocol(api, env["admin"], complaint_code=COMPLAINT_FLU_LIKE,
                    acuity_tier=3, base_price_cents=11000, min_age_months=24,
                    max_heart_rate_bpm=130, red_flag_codes=["MASTOID_SWELLING"])
    plan = [("Sample One", "1981-01-05", "M-9001", COMPLAINT_RASH,
             {"temp_c": 37.0, "heart_rate_bpm": 74, "spo2_pct": 98}),
            ("Sample Two", "1981-02-05", "M-9002", COMPLAINT_FLU_LIKE,
             {"temp_c": 37.4, "heart_rate_bpm": 88, "spo2_pct": 96}),
            ("Sample Three", "1981-03-05", "M-9003", COMPLAINT_RASH,
             {"temp_c": 37.1, "heart_rate_bpm": 72, "spo2_pct": 99})]
    env["visit_ids"] = []
    for full_name, dob, member_id, complaint_code, vitals in plan:
        patient = create_insured_patient(
            api, env["front_desk"], full_name=full_name, date_of_birth=dob,
            payer_name="BlueCo", member_id=member_id, pcp_consent_on_file=False)
        bundle = closed_insured_visit(api, env, patient["id"], services_rendered=[],
                                     complaint_code=complaint_code, vitals=vitals,
                                     copay_cents=2000, coinsurance_pct=10)
        env["visit_ids"].append(bundle["visit_id"])
    env["run"] = run_sampling(api, env["clinic_id"], SAMPLING_WINDOW_START,
                              SAMPLING_WINDOW_END, headers=env["physician_headers"])
    return env


def _reviews_of(api, env, visit_id):
    return validate_paginated(
        api.list_chart_reviews(env["admin"], params={"visit_id": visit_id}))


def test_three_eligible_charts_at_forty_percent_round_the_target_up_to_two(api):
    """1.2 charts is not 1 chart: the target is ceiled, so two reviews are minted.

    PRD: "The size of the run comes from the state rule: multiply the number of eligible
    visits by `chart_review_sample_pct`, divide by 100, and round the result **up** to a
    whole number to obtain the target total."

    Design: Corner/calculations/corner_chart_review_sampling_ceils_target_and_ranks_pool_by_acuity
    """
    env = _three_closed_charts_of_mixed_acuity_then_a_sampling_run(api)

    assert env["run"]["sampled_count"] == 2
    assert len(env["run"]["chart_review_ids"]) == 2


def test_with_no_mandatory_chart_the_whole_target_is_filled_by_chance(api):
    """No referral and no controlled script, so both picks are random ones.

    PRD: "Subtract the mandatory count from that target to obtain how many random charts
    to add, and floor that remainder at 0 — a state whose mandatory charts already exceed
    its target percentage adds no random ones and never produces a negative count."

    Design: Corner/calculations/corner_chart_review_sampling_ceils_target_and_ranks_pool_by_acuity
    """
    env = _three_closed_charts_of_mixed_acuity_then_a_sampling_run(api)

    assert env["run"]["mandatory_count"] == 0
    assert env["run"]["random_count"] == 2


def test_the_random_pool_takes_the_high_acuity_chart_then_the_earlier_tie(api):
    """Acuity 3 leads, the two acuity-1 charts tie, and the earlier one wins the seat.

    PRD: "The random pool is the eligible population minus the mandatory charts, ranked by
    the `acuity_tier` of each visit's governing protocol in descending order and then by
    ascending `created_at`, and the run takes the first entries of that ranking up to the
    random count."

    Design: Corner/calculations/corner_chart_review_sampling_ceils_target_and_ranks_pool_by_acuity
    """
    env = _three_closed_charts_of_mixed_acuity_then_a_sampling_run(api)
    first, second, third = env["visit_ids"]

    assert _reviews_of(api, env, second)[1]["total_count"] == 1
    assert _reviews_of(api, env, first)[1]["total_count"] == 1
    assert _reviews_of(api, env, third)[1]["total_count"] == 0


def test_each_minted_review_is_pending_with_a_deadline_seventy_two_hours_out(api):
    """A fresh review names the supervising physician and is due 72 hours after the run.

    PRD: "Every chart the run selects becomes a review in `PENDING` status recording the
    `visit_id` sampled, the `assessment_id` under review, a `reviewer_physician_id` taken
    from the treating clinician's `supervising_physician_id`, the `sampled_reason`
    established above, and a `due_at` computed as the logical clock at the moment of
    sampling plus the state rule's `review_deadline_hours`."

    Design: Corner/calculations/corner_chart_review_sampling_ceils_target_and_ranks_pool_by_acuity
    """
    env = _three_closed_charts_of_mixed_acuity_then_a_sampling_run(api)
    rows, _ = _reviews_of(api, env, env["visit_ids"][1])

    review = rows[0]
    assert review["status"] == REVIEW_PENDING
    assert review["sampled_reason"] == SAMPLED_RANDOM_SAMPLE
    assert review["reviewer_physician_id"] == env["physician_id"]
    assert review["assessment_id"] is not None
    assert_instant_equal(review["due_at"], REVIEW_DUE_AT)


# ---------------------------------------------------------------------------
# corner_float_coverage_selection_prefers_the_home_site_clinician
# ---------------------------------------------------------------------------

def _a_closed_site_with_a_home_float_and_an_away_float(api):
    """Two idle float-eligible candidates: one homed here, one at the neighbour store."""
    env = staffed_clinic(api, with_protocol=False,
                         physician={"full_name": "Dr Quill"},
                         clinician={"full_name": "NP Primary Quill"})
    neighbour = create_clinic(api, env["admin"], name="CA Store 49 Neighbour")
    env["home_float"] = create_clinician(api, env["clinic_id"], env["physician_id"],
                                        env["admin"], full_name="NP Home Float",
                                        float_eligible=True)
    env["away_float"] = create_clinician(api, neighbour["id"], env["physician_id"],
                                        env["admin"], full_name="NP Away Float",
                                        float_eligible=True)
    env["primary_before"] = env["assignment"]
    env["cancelled"] = validate_success(api.cancel_staffing_assignment(
        env["assignment_id"], env["admin"], cancel_reason="Called out sick"))
    env["clinic_before"] = read_clinic(api, env["clinic_id"])
    return env


def _cover_the_cancelled_shift(api, env):
    payload = float_coverage_payload(
        env["assignment_id"], env["clinic_before"]["version"],
        pinned_supervising_physician_id=env["physician_id"])
    return validate_success(
        api.create_float_coverage(env["clinic_id"], payload, env["admin"]), 201)


def test_cancelling_the_only_active_shift_shuts_the_covered_site(api):
    """The ACTIVE primary goes to CANCELLED and the headcount of 0 closes the clinic.

    PRD: "Hop two re-derives `open_status` from the new count, moving `OPEN → LIMITED`
    when the count is above 0 but below `min_clinicians_required`, and `OPEN → CLOSED`
    or `LIMITED → CLOSED` when it reaches 0."

    Design: Corner/calculations/corner_float_coverage_selection_prefers_the_home_site_clinician
    """
    env = _a_closed_site_with_a_home_float_and_an_away_float(api)

    assert env["primary_before"]["status"] == ASSIGNMENT_ACTIVE
    assert env["cancelled"]["status"] == ASSIGNMENT_CANCELLED
    assert env["clinic_before"]["open_status"] == CLINIC_CLOSED
    assert env["clinic_before"]["on_duty_clinician_count"] == 0


def test_the_home_site_float_is_chosen_over_the_equally_idle_neighbour(api):
    """Both candidates hold zero assignments, so the home-site key decides it.

    PRD: "Surviving candidates are ranked with the clinician's home site first — those
    whose `home_clinic_id` equals the clinic being covered rank ahead of everyone else —
    then by ascending `active_assignment_count`, then by ascending `created_at`; the first
    candidate after that ranking wins, and the clinician's `id` never participates in the
    ordering."

    Design: Corner/calculations/corner_float_coverage_selection_prefers_the_home_site_clinician
    """
    env = _a_closed_site_with_a_home_float_and_an_away_float(api)

    coverage = _cover_the_cancelled_shift(api, env)

    assert coverage["clinician_id"] == env["home_float"]["id"]
    assert coverage["clinician_id"] != env["away_float"]["id"]


def test_the_covering_shift_spans_exactly_the_interval_it_replaces(api):
    """A FLOAT row inherits the cancelled shift's window and points back at it.

    PRD: "The winner receives a new assignment with `role_kind` of `FLOAT` spanning
    exactly the covered shift's interval, pointing back at the covered row through
    `covers_assignment_id`."

    Design: Corner/calculations/corner_float_coverage_selection_prefers_the_home_site_clinician
    """
    env = _a_closed_site_with_a_home_float_and_an_away_float(api)

    coverage = _cover_the_cancelled_shift(api, env)

    assert coverage["role_kind"] == ROLE_KIND_FLOAT
    assert coverage["covers_assignment_id"] == env["assignment_id"]
    assert_instant_equal(coverage["starts_at"], CLOCK_START)
    assert_instant_equal(coverage["ends_at"], SHIFT_ENDS_AT)


def test_the_covering_shift_activates_at_once_and_reopens_the_clinic(api):
    """The clock already sits inside the inherited window, so cover is immediate.

    PRD: "That new row is subject to the same double-booking, licensure and
    supervision-capacity rules as a hand-scheduled one, and it activates immediately when
    the logical clock already sits inside the interval — raising `on_duty_clinician_count`,
    possibly moving the posture `LIMITED → OPEN` or `CLOSED → LIMITED` or `CLOSED → OPEN`,
    and recomputing both the physician's `current_supervised_count` and the clinician's
    `active_assignment_count`."

    Design: Corner/calculations/corner_float_coverage_selection_prefers_the_home_site_clinician
    """
    env = _a_closed_site_with_a_home_float_and_an_away_float(api)

    coverage = _cover_the_cancelled_shift(api, env)

    assert coverage["status"] == ASSIGNMENT_ACTIVE
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["open_status"] == CLINIC_OPEN
    assert clinic["on_duty_clinician_count"] == 1
    assert read_clinician(api, env["home_float"]["id"])["active_assignment_count"] == 1
    assert read_clinician(api, env["away_float"]["id"])["active_assignment_count"] == 0
    assert read_physician(api, env["physician_id"])["current_supervised_count"] == 1
