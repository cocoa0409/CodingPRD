"""Writing responses that are already complete, with nothing left to settle later.

Checkout answers with every derived amount and both settled dimensions, and a
clock advance answers with every identifier the advance touched — so a client
never has to issue a second request to learn what its first one did.
"""
from test_helpers import (
    ASSIGNMENT_ACTIVE,
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_SCHEDULED,
    BILLING_COVERAGE_VERIFIED,
    BILLING_INVOICED,
    CLINIC_OPEN,
    CREDENTIAL_PA,
    DESTINATION_DIRECT_MESSAGE,
    QUEUE_ABANDONED,
    QUEUE_WAITING,
    SERVICE_EKG,
    SERVICE_INJECTION_ADMIN,
    SUMMARY_QUEUED,
    VISIT_CLOSED,
    add_walk_in,
    assert_instant_equal,
    assert_money_conserved,
    checkout,
    create_assignment,
    create_clinician,
    create_insured_patient,
    read_assignment,
    read_clinic,
    read_patient,
    read_queue_entry,
    read_visit,
    set_clock,
    staffed_clinic,
    treated_visit,
    validate_paginated,
    verify_active_coverage,
)

CHECKOUT_SERVICES = [SERVICE_INJECTION_ADMIN, SERVICE_EKG]

# 9900 base + 4200 injection administration + 6500 electrocardiogram.
FINAL_PRICE_CENTS = 20600
# Per-line 7.5 percent shares 743 + 315 + 488 = 1546, plus the 1500 copay.
PATIENT_SHARE_CENTS = 3046
PAYER_SHARE_CENTS = 17554
# 1500 copay plus 7.5 percent of the 8400 the base exceeds the copay by.
INSURED_QUOTE_CENTS = 2130


def _an_insured_checkout_with_two_add_on_services(api):
    """Cleo Consent is treated, verified at 1500/7.5, then checked out with two lines."""
    env = staffed_clinic(api, clinic={"name": "CA Store 82"},
                         protocol={"requires_cosign": False},
                         physician={"full_name": "Dr Willow"},
                         clinician={"full_name": "NP Willow"})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Cleo Consent",
        date_of_birth="1968-08-28", payer_name="BlueCo", member_id="M-8282",
        pcp_name="Dr Primary", pcp_direct_address="cleo.pcp@direct.example.org",
        pcp_accepts_electronic_summary=True, pcp_consent_on_file=True)
    env["patient"] = patient
    env["balance_before"] = read_patient(api, patient["id"])["outstanding_balance_cents"]
    bundle = treated_visit(api, env, patient["id"],
                           vitals={"temp_c": 37.3, "heart_rate_bpm": 84,
                                   "spo2_pct": 98})
    env["visit_id"] = bundle["visit_id"]
    env["verified"] = verify_active_coverage(api, env, bundle["visit_id"],
                                             copay_cents=1500, coinsurance_pct=7.5)
    env["checked_out"] = checkout(api, env, bundle["visit_id"],
                                  services_rendered=CHECKOUT_SERVICES)
    return env


def test_the_checkout_response_carries_the_allowed_amount_and_both_shares(api):
    """20600 splits into 3046 for the patient and 17554 for the payer, in one answer.

    PRD: "For an insured visit, the patient's share is built **line by line**:
    `coinsurance_pct` is applied to each line price, each line's result is rounded to
    whole cents half up on its own, those rounded shares are added together,
    `copay_cents` is added on top, and the outcome is finally capped so that it never
    exceeds the total allowed amount."

    Design: Corner/consistency_model/corner_checkout_response_already_carries_every_derived_amount
    """
    env = _an_insured_checkout_with_two_add_on_services(api)

    visit = env["checked_out"]

    assert visit["final_price_cents"] == FINAL_PRICE_CENTS
    assert visit["patient_responsibility_cents"] == PATIENT_SHARE_CENTS
    assert visit["payer_responsibility_cents"] == PAYER_SHARE_CENTS
    assert visit["services_rendered"] == CHECKOUT_SERVICES
    assert_money_conserved(visit)


def test_the_checkout_response_already_shows_both_dimensions_settled(api):
    """CLOSED and INVOICED arrive together in the writing response, not on a re-read.

    PRD: "The `clinical_status` moves `TREATED → CLOSED` or `REFERRED → CLOSED`; the
    `billing_status` moves `COVERAGE_VERIFIED → INVOICED` or
    `SELF_PAY_ACCEPTED → INVOICED` in the same request; the patient's
    `outstanding_balance_cents` is recomputed from scratch across their invoiced
    visits; the visit's `version` is incremented."

    Design: Corner/consistency_model/corner_checkout_response_already_carries_every_derived_amount
    """
    env = _an_insured_checkout_with_two_add_on_services(api)

    visit = env["checked_out"]

    assert env["verified"]["billing_status"] == BILLING_COVERAGE_VERIFIED
    assert env["verified"]["self_pay"] is False
    assert visit["clinical_status"] == VISIT_CLOSED
    assert visit["billing_status"] == BILLING_INVOICED


def test_rereading_the_visit_repeats_every_amount_and_keeps_the_original_quote(api):
    """No denormalised field lags: the re-read matches, and the up-front quote survives.

    PRD: "Concretely, subtract `copay_cents` from the protocol's `base_price_cents`,
    apply `coinsurance_pct` to that remainder, round the product to whole cents half
    up, and add the copay back."

    Design: Corner/consistency_model/corner_checkout_response_already_carries_every_derived_amount
    """
    env = _an_insured_checkout_with_two_add_on_services(api)

    reread = read_visit(api, env["visit_id"])

    assert env["verified"]["quoted_price_cents"] == INSURED_QUOTE_CENTS
    assert env["checked_out"]["quoted_price_cents"] == INSURED_QUOTE_CENTS
    assert reread["quoted_price_cents"] == INSURED_QUOTE_CENTS
    assert reread["final_price_cents"] == env["checked_out"]["final_price_cents"]
    assert reread["patient_responsibility_cents"] == PATIENT_SHARE_CENTS
    assert reread["payer_responsibility_cents"] == PAYER_SHARE_CENTS


def test_the_patient_aggregate_and_the_queued_summary_settle_on_the_first_read(api):
    """A balance of 0 becomes 3046 and the routed summary is already discoverable.

    PRD: "A patient's `outstanding_balance_cents` is the sum of
    `patient_responsibility_cents` across that patient's visits whose `billing_status`
    is `INVOICED`, and it is recomputed from scratch on every billing transition that
    touches the patient."

    Design: Corner/consistency_model/corner_checkout_response_already_carries_every_derived_amount
    """
    env = _an_insured_checkout_with_two_add_on_services(api)

    patient = read_patient(api, env["patient"]["id"])
    rows, meta = validate_paginated(api.list_visit_summaries(
        env["admin"], params={"visit_id": env["visit_id"]}))

    assert env["balance_before"] == 0
    assert patient["outstanding_balance_cents"] == PATIENT_SHARE_CENTS
    assert meta["total_count"] == 1
    summary = rows[0]
    assert summary["destination_kind"] == DESTINATION_DIRECT_MESSAGE
    assert summary["destination_address"] == "cleo.pcp@direct.example.org"
    assert summary["status"] == SUMMARY_QUEUED
    assert summary["attempt_count"] == 0
    assert summary["includes_referral"] is False


# ---------------------------------------------------------------------------
# The clock advance summary names every row it touched
# ---------------------------------------------------------------------------

HANDOVER_INSTANT = "2026-08-01T02:05:00Z"


def _a_site_handing_over_between_two_shifts(api):
    """NP A works [00:00, 01:00), NP B is booked [02:00, 04:00), Ned waits from 00:00."""
    env = staffed_clinic(api, clinic={"name": "CA Store 83"},
                         physician={"full_name": "Dr Yarrow"},
                         clinician={"full_name": "NP Yarrow A"},
                         assignment={"starts_at": "2026-08-01T00:00:00Z",
                                     "ends_at": "2026-08-01T01:00:00Z"})
    env["shift_a"] = env["assignment"]
    env["clinician_b"] = create_clinician(
        api, env["clinic_id"], env["physician_id"], env["admin"],
        full_name="NP Yarrow B", credential=CREDENTIAL_PA)
    env["shift_b"] = create_assignment(
        api, env["clinic_id"], env["clinician_b"]["id"], env["admin"],
        starts_at="2026-08-01T02:00:00Z", ends_at="2026-08-01T04:00:00Z",
        pinned_supervising_physician_id=env["physician_id"])
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Ned Neglected",
        date_of_birth="1967-07-27", payer_name="BlueCo", member_id="M-8383")
    env["patient"] = patient
    env["entry"] = add_walk_in(api, env, patient["id"])
    return env


def test_the_handover_begins_with_one_active_shift_and_one_booked_for_later(api):
    """The 00:00 shift activates on creation while the 02:00 shift is merely scheduled.

    PRD: "It advances `SCHEDULED → ACTIVE` the moment the logical clock sits inside its
    interval — either because the clock was already there when the assignment was
    created, in which case the activation happens inside the same request, or because a
    later clock move crossed `starts_at`."

    Design: Corner/consistency_model/corner_clock_response_names_every_row_the_advance_touched
    """
    env = _a_site_handing_over_between_two_shifts(api)

    assert env["shift_a"]["status"] == ASSIGNMENT_ACTIVE
    assert env["shift_b"]["status"] == ASSIGNMENT_SCHEDULED
    assert env["entry"]["status"] == QUEUE_WAITING
    assert_instant_equal(env["entry"]["arrived_at"], "2026-08-01T00:00:00Z")


def test_the_clock_response_enumerates_the_assignments_it_completed_and_activated(api):
    """One advance to 02:05 reports the finished shift, the started shift and the site.

    PRD: "The response to a clock move reports what it did, listing `current_utc`
    alongside `activated_assignment_ids`, `completed_assignment_ids`,
    `abandoned_queue_entry_ids` and `affected_clinic_ids`."

    Design: Corner/consistency_model/corner_clock_response_names_every_row_the_advance_touched
    """
    env = _a_site_handing_over_between_two_shifts(api)

    advance = set_clock(api, HANDOVER_INSTANT, env["admin"])

    assert_instant_equal(advance["current_utc"], HANDOVER_INSTANT)
    assert advance["completed_assignment_ids"] == [env["shift_a"]["id"]]
    assert advance["activated_assignment_ids"] == [env["shift_b"]["id"]]
    assert advance["affected_clinic_ids"] == [env["clinic_id"]]


def test_the_clock_response_names_the_walk_in_it_abandoned(api):
    """125 minutes of waiting crosses the two-hour threshold, so the entry is abandoned.

    PRD: "When the logical clock advances to 120 minutes or more past an entry's
    `arrived_at` while that entry is still `WAITING` and no one has called it, the entry
    moves `WAITING → ABANDONED`, the clinic's `waiting_count` falls by 1, and
    `posted_wait_minutes` is recomputed."

    Design: Corner/consistency_model/corner_clock_response_names_every_row_the_advance_touched
    """
    env = _a_site_handing_over_between_two_shifts(api)

    advance = set_clock(api, HANDOVER_INSTANT, env["admin"])

    assert advance["abandoned_queue_entry_ids"] == [env["entry"]["id"]]
    assert read_queue_entry(api, env["entry"]["id"])["status"] == QUEUE_ABANDONED


def test_the_handover_keeps_the_site_open_and_clears_the_posted_wait(api):
    """Completion and activation are both applied before the posture is re-derived.

    PRD: "An administrator-only, test-driving capability sets the clock to a supplied
    `current_utc` instant, and moving the clock is itself an operational event: staffing
    assignments whose start instant has arrived activate, active assignments whose end
    instant has passed complete, waiting queue entries that have waited longer than two
    hours are abandoned, and every clinic touched by those changes has its posture
    re-derived along with the queue and visit cascades that posture change implies."

    Design: Corner/consistency_model/corner_clock_response_names_every_row_the_advance_touched
    """
    env = _a_site_handing_over_between_two_shifts(api)

    set_clock(api, HANDOVER_INSTANT, env["admin"])

    assert read_assignment(api, env["shift_a"]["id"])["status"] == ASSIGNMENT_COMPLETED
    assert read_assignment(api, env["shift_b"]["id"])["status"] == ASSIGNMENT_ACTIVE
    clinic = read_clinic(api, env["clinic_id"])
    assert clinic["on_duty_clinician_count"] == 1
    assert clinic["open_status"] == CLINIC_OPEN
    assert clinic["waiting_count"] == 0
    assert clinic["posted_wait_minutes"] == 0
