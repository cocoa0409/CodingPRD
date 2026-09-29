"""Two quoting paths off one protocol, and two wait numbers off one clinic."""
from test_helpers import (
    BILLING_COVERAGE_VERIFIED,
    BILLING_SELF_PAY_QUOTED,
    COMPLAINT_SORE_THROAT,
    COVERAGE_ACTIVE,
    COVERAGE_INACTIVE,
    CLINIC_OPEN,
    QUEUE_CALLED,
    add_appointment,
    add_walk_in,
    call_next,
    create_insured_patient,
    create_patient,
    quote_self_pay,
    read_clinic,
    read_queue_entry,
    read_visit,
    screening_visit,
    set_clock,
    staffed_clinic,
    verify_active_coverage,
)


def _two_patients_in_screening(api):
    """One insured and one uninsured patient, each with a visit open in SCREENING."""
    env = staffed_clinic(api, protocol={"requires_cosign": True,
                                        "red_flag_codes": ["STRIDOR", "DROOLING"]})
    insured = create_insured_patient(
        api, env["front_desk"], full_name="Ada Insured", date_of_birth="1990-05-10",
        payer_name="Aetna", member_id="M-1001", pcp_name="Dr Pace",
        pcp_direct_address="pace@direct.example",
        pcp_accepts_electronic_summary=True, pcp_consent_on_file=True)
    cash = create_patient(api, env["front_desk"], full_name="Ben Cash",
                          date_of_birth="1988-03-02", pcp_consent_on_file=False)
    env["insured_patient"] = insured
    env["cash_patient"] = cash
    env["insured"] = screening_visit(api, env, insured["id"])
    env["cash"] = screening_visit(api, env, cash["id"])
    return env


def test_active_coverage_quotes_the_copay_plus_the_coinsurance_remainder(api):
    """A 9900 base with a 2500 copay at 12.5 percent quotes 3425 cents.

    PRD: "Concretely, subtract `copay_cents` from the protocol's `base_price_cents`,
    apply `coinsurance_pct` to that remainder, round the product to whole cents half
    up, and add the copay back."

    Design: Difficulty/dual_variant_calc/visit_quote_insured_estimate_vs_self_pay_transparent
    """
    env = _two_patients_in_screening(api)

    visit = verify_active_coverage(api, env, env["insured"]["visit_id"],
                                  copay_cents=2500, coinsurance_pct=12.5)

    assert visit["quoted_price_cents"] == 3425
    assert visit["billing_status"] == BILLING_COVERAGE_VERIFIED
    assert visit["self_pay"] is False
    assert visit["coverage_status"] == COVERAGE_ACTIVE
    assert visit["copay_cents"] == 2500
    assert visit["coinsurance_pct"] == 12.5


def test_inactive_coverage_quotes_the_transparent_self_pay_list_price(api):
    """The same 9900 protocol quotes 9900 with no payer parameters at all.

    PRD: "The submitted value is stored in `coverage_status`, `self_pay` is set true,
    and both `copay_cents` and `coinsurance_pct` are set null — no payer participates,
    so no payer parameters apply."

    Design: Difficulty/dual_variant_calc/visit_quote_insured_estimate_vs_self_pay_transparent
    """
    env = _two_patients_in_screening(api)

    visit = quote_self_pay(api, env, env["cash"]["visit_id"])

    assert visit["quoted_price_cents"] == 9900
    assert visit["billing_status"] == BILLING_SELF_PAY_QUOTED
    assert visit["self_pay"] is True
    assert visit["coverage_status"] == COVERAGE_INACTIVE
    assert visit["copay_cents"] is None
    assert visit["coinsurance_pct"] is None


def test_one_protocol_quotes_materially_different_numbers_to_the_two_payers(api):
    """3425 against 9900 on identical protocol data, read back from both rows.

    PRD: "The same protocol therefore quotes a materially different number to an
    insured patient than to a self-pay one, which is the point of quoting both
    transparently."

    Design: Difficulty/dual_variant_calc/visit_quote_insured_estimate_vs_self_pay_transparent
    """
    env = _two_patients_in_screening(api)

    verify_active_coverage(api, env, env["insured"]["visit_id"], copay_cents=2500,
                          coinsurance_pct=12.5)
    quote_self_pay(api, env, env["cash"]["visit_id"])

    insured_visit = read_visit(api, env["insured"]["visit_id"])
    cash_visit = read_visit(api, env["cash"]["visit_id"])
    assert insured_visit["protocol_id"] == cash_visit["protocol_id"]
    assert insured_visit["quoted_price_cents"] == 3425
    assert cash_visit["quoted_price_cents"] == 9900
    assert cash_visit["quoted_price_cents"] - insured_visit["quoted_price_cents"] == 6475


def _three_waiting_and_one_upcoming_appointment(api):
    """Two clinicians on duty at 08:00, one 08:30 appointment, three walk-ins."""
    env = staffed_clinic(
        api, clock="2026-08-01T08:00:00Z", clinician_count=2,
        protocol={"requires_cosign": True},
        assignment={"starts_at": "2026-08-01T08:00:00Z",
                    "ends_at": "2026-08-01T18:00:00Z"})
    appointment_patient = create_patient(api, env["front_desk"],
                                        full_name="Appt Patient",
                                        date_of_birth="1975-01-01")
    add_appointment(api, env, appointment_patient["id"], "2026-08-01T08:30:00Z",
                    complaint_code=COMPLAINT_SORE_THROAT)
    env["walk_ins"] = []
    for index, birth in enumerate(("1980-01-01", "1981-01-01", "1982-01-01")):
        patient = create_patient(api, env["front_desk"],
                                 full_name=f"Walk {index + 1}", date_of_birth=birth)
        env["walk_ins"].append(add_walk_in(api, env, patient["id"]))
    return env


def test_posted_wait_blends_rounded_up_queue_depth_with_upcoming_appointments(api):
    """Three waiting, two on duty and one appointment inside the hour post 50 minutes.

    PRD: "The rounding-up happens before the multiplication and the cap is applied
    last: for a clinic with three patients waiting, two clinicians on duty and one
    appointment in the coming hour, the projection is two patients per clinician,
    forty minutes of visits, plus ten minutes of appointment blending, for a posted
    figure of 50 minutes."

    Design: Difficulty/dual_variant_calc/wait_time_posted_projection_vs_realized_actual
    """
    env = _three_waiting_and_one_upcoming_appointment(api)

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["waiting_count"] == 3
    assert clinic["on_duty_clinician_count"] == 2
    assert clinic["open_status"] == CLINIC_OPEN
    assert clinic["posted_wait_minutes"] == 50
    assert clinic["last_realized_wait_minutes"] is None


def test_call_next_measures_the_realized_wait_from_the_entry_clock_stamps(api):
    """The first walk-in wins the tie and records a realized wait of 25 minutes.

    PRD: "The winning entry's `called_at` is stamped with the logical clock, and its
    `realized_wait_minutes` is measured as the whole minutes elapsed from `arrived_at`
    to `called_at`, discarding any partial minute."

    Design: Difficulty/dual_variant_calc/wait_time_posted_projection_vs_realized_actual
    """
    env = _three_waiting_and_one_upcoming_appointment(api)
    set_clock(api, "2026-08-01T08:25:00Z", env["admin"])

    called = call_next(api, env)

    assert called["id"] == env["walk_ins"][0]["id"]
    assert called["realized_wait_minutes"] == 25
    assert called["status"] == QUEUE_CALLED
    entry = read_queue_entry(api, env["walk_ins"][0]["id"])
    assert entry["realized_wait_minutes"] == 25
    assert entry["status"] == QUEUE_CALLED


def test_the_projection_and_the_measurement_report_different_numbers(api):
    """After the call the clinic posts 30 minutes while the entry realized 25.

    PRD: "This measurement is deliberately unlike the posted projection: it reads only
    the two clock stamps on that single entry and ignores staffing, queue depth and
    upcoming appointments entirely, so the same clinic state will generally produce a
    different number from each."

    Design: Difficulty/dual_variant_calc/wait_time_posted_projection_vs_realized_actual
    """
    env = _three_waiting_and_one_upcoming_appointment(api)
    set_clock(api, "2026-08-01T08:25:00Z", env["admin"])

    call_next(api, env)

    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["last_realized_wait_minutes"] == 25
    assert clinic["waiting_count"] == 2
    assert clinic["posted_wait_minutes"] == 30
    assert clinic["posted_wait_minutes"] != clinic["last_realized_wait_minutes"]
