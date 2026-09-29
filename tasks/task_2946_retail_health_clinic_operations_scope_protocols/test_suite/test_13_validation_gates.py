"""Validation gates: which refusal a request earns when it breaks several rules."""
from test_helpers import (
    BILLING_COVERAGE_VERIFIED,
    BILLING_SELF_PAY_ACCEPTED,
    BILLING_SELF_PAY_QUOTED,
    BILLING_UNBILLED,
    CLINIC_CLOSED,
    COMPLAINT_SPORTS_PHYSICAL,
    COVERAGE_UNKNOWN,
    COVERAGE_UNVERIFIED,
    NON_EXISTENT_UUID,
    OUTCOME_SCOPE_DEVIATION,
    PRESCRIPTION_CANCELLED,
    PRESCRIPTION_DRAFT,
    PRESCRIPTION_ROUTED,
    QUEUE_CALLED,
    QUEUE_KIND_APPOINTMENT,
    REVIEW_ESCALATED,
    REVIEW_PENDING,
    THERAPY_ANTIBIOTIC_MACROLIDE,
    VISIT_TREATED,
    ApiErrorId,
    accept_quote,
    add_walk_in,
    appointment_payload,
    call_next,
    checkout,
    closed_insured_visit,
    create_insured_patient,
    create_patient,
    create_physician,
    create_protocol,
    create_state_rule,
    eligibility_payload,
    error_id,
    make_admin_headers,
    make_patient_headers,
    make_physician_headers,
    prescription_payload,
    quote_self_pay,
    read_chart_review,
    read_clinic,
    read_clinician,
    read_patient,
    read_prescription,
    read_queue_entry,
    read_visit,
    run_sampling,
    staffed_clinic,
    treated_visit,
    validate_error,
    validate_paginated,
    validate_success,
    verify_active_coverage,
    visit_payload,
    walk_in_payload,
)

NORMAL_VITALS = {"temp_c": 37.0, "heart_rate_bpm": 76, "spo2_pct": 99}


# ---------------------------------------------------------------------------
# corner_checkout_before_eligibility_check_returns_quote_required
# ---------------------------------------------------------------------------

def _treated_visit_with_no_eligibility_recorded(api):
    """Quinn Quote is seen and treated, but the money dimension never moved."""
    env = staffed_clinic(api, protocol={"requires_cosign": False})
    patient = create_patient(api, env["front_desk"], full_name="Quinn Quote",
                             date_of_birth="1983-08-23")
    env["patient"] = patient
    env["bundle"] = treated_visit(api, env, patient["id"], vitals=NORMAL_VITALS)
    env["visit_id"] = env["bundle"]["visit_id"]
    return env


def test_a_freshly_opened_visit_starts_unbilled_with_every_price_still_null(api):
    """The fiscal dimension is untouched by the clinical work that follows.

    PRD: "A patient who clears the gate gets a visit created with `clinical_status` of
    `SCREENING` and `billing_status` of `UNBILLED`, its priced amounts —
    `quoted_price_cents`, `final_price_cents`, `patient_responsibility_cents`,
    `payer_responsibility_cents`, `copay_cents` and `coinsurance_pct` — all still null,
    its `coverage_status` at `UNVERIFIED`, its `self_pay` flag false, its
    `referral_required` flag false, and its `services_rendered` empty."

    Design: Corner/validations/corner_checkout_before_eligibility_check_returns_quote_required
    """
    env = _treated_visit_with_no_eligibility_recorded(api)

    opened = env["bundle"]["visit"]

    assert opened["billing_status"] == BILLING_UNBILLED
    assert opened["coverage_status"] == COVERAGE_UNVERIFIED
    assert opened["quoted_price_cents"] is None
    assert opened["final_price_cents"] is None
    assert opened["self_pay"] is False


def test_checkout_before_any_eligibility_check_is_refused_for_a_missing_quote(api):
    """The clinical work is finished, so only the unrecorded quote can refuse it.

    PRD: "The billing dimension must have settled at `COVERAGE_VERIFIED` or
    `SELF_PAY_ACCEPTED`: a visit still `UNBILLED` has had no eligibility check recorded
    and is refused with `ERR_QUOTE_REQUIRED`, while a visit still `SELF_PAY_QUOTED` has
    an unaccepted offer outstanding and is refused with `ERR_PAYMENT_METHOD_REQUIRED`
    (HTTP 402)."

    Design: Corner/validations/corner_checkout_before_eligibility_check_returns_quote_required
    """
    env = _treated_visit_with_no_eligibility_recorded(api)

    response = api.checkout(env["visit_id"], env["clinician_headers"],
                            services_rendered=[])

    validate_error(response, ApiErrorId.ERR_QUOTE_REQUIRED, 409)
    assert error_id(response) != "ERR_PAYMENT_METHOD_REQUIRED"


def test_the_refused_checkout_leaves_the_visit_treated_and_unpriced(api):
    """Nothing on either dimension moved and the patient owes nothing.

    PRD: "A patient's `outstanding_balance_cents` is the sum of
    `patient_responsibility_cents` across that patient's visits whose `billing_status`
    is `INVOICED`, and it is recomputed from scratch on every billing transition that
    touches the patient."

    Design: Corner/validations/corner_checkout_before_eligibility_check_returns_quote_required
    """
    env = _treated_visit_with_no_eligibility_recorded(api)

    api.checkout(env["visit_id"], env["clinician_headers"], services_rendered=[])

    visit = read_visit(api, env["visit_id"])
    assert visit["clinical_status"] == VISIT_TREATED
    assert visit["billing_status"] == BILLING_UNBILLED
    assert visit["final_price_cents"] is None
    assert visit["quoted_price_cents"] is None
    assert read_patient(api, env["patient"]["id"])["outstanding_balance_cents"] == 0


# ---------------------------------------------------------------------------
# corner_self_pay_quote_must_be_matched_then_accepted_before_checkout
# ---------------------------------------------------------------------------

def _self_pay_quoted_visit_at_the_list_price(api):
    """Pat SelfPay has no payer, so an UNKNOWN eligibility answer quotes 9900."""
    env = staffed_clinic(api, protocol={"requires_cosign": False})
    patient = create_patient(api, env["front_desk"], full_name="Pat SelfPay",
                             date_of_birth="1984-09-24")
    env["patient"] = patient
    env["bundle"] = treated_visit(api, env, patient["id"],
                                  vitals={"temp_c": 37.2, "heart_rate_bpm": 80,
                                          "spo2_pct": 98})
    env["visit_id"] = env["bundle"]["visit_id"]
    env["quoted"] = validate_success(api.eligibility_check(
        env["visit_id"], eligibility_payload(COVERAGE_UNKNOWN), env["front_desk"]))
    env["patient_headers"] = make_patient_headers(patient["id"])
    return env


def test_an_unknown_coverage_answer_quotes_the_undiscounted_self_pay_price(api):
    """A 9900 subtotal sits below the first tier ceiling, so no discount applies.

    PRD: "Second, choose the tier from that subtotal: a subtotal below 10000 cents earns
    no discount, a subtotal from 10000 cents up to but not including 20000 cents earns
    10 percent, and a subtotal of 20000 cents or more earns 15 percent."

    Design: Corner/validations/corner_self_pay_quote_must_be_matched_then_accepted_before_checkout
    """
    env = _self_pay_quoted_visit_at_the_list_price(api)

    quoted = env["quoted"]

    assert quoted["billing_status"] == BILLING_SELF_PAY_QUOTED
    assert quoted["self_pay"] is True
    assert quoted["quoted_price_cents"] == 9900
    assert quoted["copay_cents"] is None
    assert quoted["coinsurance_pct"] is None


def test_checkout_on_a_merely_quoted_self_pay_visit_needs_a_payment_method(api):
    """The offer is outstanding, so the fiscal gate answers 402 rather than 409.

    PRD: "A self-pay visit must have an accepted quote before services are priced at
    checkout; a visit still in `SELF_PAY_QUOTED` is refused with
    `ERR_PAYMENT_METHOD_REQUIRED` (402)."

    Design: Corner/validations/corner_self_pay_quote_must_be_matched_then_accepted_before_checkout
    """
    env = _self_pay_quoted_visit_at_the_list_price(api)

    response = api.checkout(env["visit_id"], env["clinician_headers"],
                            services_rendered=[])

    validate_error(response, ApiErrorId.ERR_PAYMENT_METHOD_REQUIRED, 402)
    assert error_id(response) != "ERR_QUOTE_REQUIRED"
    assert read_visit(api, env["visit_id"])["billing_status"] == BILLING_SELF_PAY_QUOTED


def test_acknowledging_a_price_the_clinic_never_quoted_is_refused(api):
    """9800 is not 9900, so the acceptance does not bind the patient.

    PRD: "Acceptance carries `acknowledged_price_cents`, which must equal the visit's
    stored `quoted_price_cents` exactly; any other figure means the patient is
    acknowledging a price the clinic did not quote, and the acceptance is refused with
    `ERR_QUOTE_MISMATCH`."

    Design: Corner/validations/corner_self_pay_quote_must_be_matched_then_accepted_before_checkout
    """
    env = _self_pay_quoted_visit_at_the_list_price(api)

    response = api.accept_self_pay(env["visit_id"], 9800, env["patient_headers"])

    validate_error(response, ApiErrorId.ERR_QUOTE_MISMATCH, 422)
    assert read_visit(api, env["visit_id"])["billing_status"] == BILLING_SELF_PAY_QUOTED


def test_accepting_the_exact_quote_prices_the_whole_visit_to_the_patient(api):
    """With the offer accepted the checkout lands 9900 on the patient and 0 on a payer.

    PRD: "For a self-pay visit the total allowed amount is run through the self-pay
    discount of §3.5 — subtotal first, tier from the subtotal, one rounded aggregate
    discount, then subtraction — and the discounted figure becomes `final_price_cents`,
    with `patient_responsibility_cents` equal to it and `payer_responsibility_cents` set
    to 0, since no payer is involved."

    Design: Corner/validations/corner_self_pay_quote_must_be_matched_then_accepted_before_checkout
    """
    env = _self_pay_quoted_visit_at_the_list_price(api)
    accepted = accept_quote(api, env["visit_id"], 9900,
                            headers=env["patient_headers"])

    closed = checkout(api, env, env["visit_id"], services_rendered=[])

    assert accepted["billing_status"] == BILLING_SELF_PAY_ACCEPTED
    assert closed["final_price_cents"] == 9900
    assert closed["patient_responsibility_cents"] == 9900
    assert closed["payer_responsibility_cents"] == 0
    assert read_patient(api, env["patient"]["id"])["outstanding_balance_cents"] == 9900


# ---------------------------------------------------------------------------
# corner_body_shape_error_precedes_unknown_foreign_key
# ---------------------------------------------------------------------------

def _reference_data_and_one_patient_but_no_clinic(api):
    """Vic Validation is registered; the clinic id the probes carry belongs to nobody."""
    env = {"admin": make_admin_headers()}
    env["state_rule"] = create_state_rule(api)
    env["protocol"] = create_protocol(api)
    env["patient"] = create_patient(api, full_name="Vic Validation",
                                    date_of_birth="1985-10-25")
    return env


def test_an_invalid_kind_enum_outranks_the_unknown_clinic_reference(api):
    """Both rules are broken by one body; the shape rung is the earlier one.

    PRD: "Unknown body fields are rejected, required fields must be present, types and
    enum members must be valid, integers declared non-negative must be non-negative,
    `limit` must lie between 1 and 100 inclusive and `offset` must be 0 or greater. Any
    breach is `ERR_VALIDATION` (400)."

    Design: Corner/validations/corner_body_shape_error_precedes_unknown_foreign_key
    """
    env = _reference_data_and_one_patient_but_no_clinic(api)
    payload = walk_in_payload(NON_EXISTENT_UUID, env["patient"]["id"],
                              kind="DRIVE_THROUGH")

    response = api.create_queue_entry(payload, env["admin"])

    validate_error(response, ApiErrorId.ERR_VALIDATION, 400)
    assert error_id(response) != "ERR_CLINIC_NOT_FOUND"


def test_a_legal_enum_lets_the_request_reach_the_body_reference_check(api):
    """With `kind` repaired the same unknown clinic id is finally reported as missing.

    PRD: "Every foreign reference carried in a request body must resolve to an existing
    row, checked in the order the fields are declared for that endpoint, and the refusal
    is the matching 404 from the same list."

    Design: Corner/validations/corner_body_shape_error_precedes_unknown_foreign_key
    """
    env = _reference_data_and_one_patient_but_no_clinic(api)
    payload = walk_in_payload(NON_EXISTENT_UUID, env["patient"]["id"])

    response = api.create_queue_entry(payload, env["admin"])

    validate_error(response, ApiErrorId.ERR_CLINIC_NOT_FOUND, 404)
    assert error_id(response) != "ERR_VALIDATION"


def test_neither_refused_intake_leaves_a_queue_entry_behind(api):
    """An ordered refusal is still a refusal: the patient has no entry at all.

    PRD: "The ladder is evaluated top to bottom, and evaluation stops at the first
    failure."

    Design: Corner/validations/corner_body_shape_error_precedes_unknown_foreign_key
    """
    env = _reference_data_and_one_patient_but_no_clinic(api)
    api.create_queue_entry(
        walk_in_payload(NON_EXISTENT_UUID, env["patient"]["id"], kind="DRIVE_THROUGH"),
        env["admin"])
    api.create_queue_entry(
        walk_in_payload(NON_EXISTENT_UUID, env["patient"]["id"]), env["admin"])

    rows, meta = validate_paginated(
        api.list_queue_entries(env["admin"], params={"patient_id": env["patient"]["id"]}))

    assert rows == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# corner_closed_clinic_refuses_appointment_intake_as_well_as_walk_ins
# ---------------------------------------------------------------------------

def _clinic_that_was_never_staffed(api):
    """Reference data, a site with no assignment at all, and one waiting patient."""
    env = staffed_clinic(api, staff=False)
    env["patient"] = create_patient(api, env["front_desk"], full_name="Cleo Closed",
                                    date_of_birth="1986-11-26")
    return env


def test_a_site_with_no_staffing_assignment_sits_closed_and_empty(api):
    """The posture is derived from a zero on-duty count, not chosen by a client.

    PRD: "The site's operational readings are all server-derived and start at rest:
    `on_duty_clinician_count` at 0, `open_status` at `CLOSED`, `waiting_count` at 0,
    `posted_wait_minutes` at 0, and `last_realized_wait_minutes` null, since no patient
    has yet been called and there is therefore no realized wait to report."

    Design: Corner/validations/corner_closed_clinic_refuses_appointment_intake_as_well_as_walk_ins
    """
    env = _clinic_that_was_never_staffed(api)

    clinic = read_clinic(api, env["clinic_id"])

    assert clinic["on_duty_clinician_count"] == 0
    assert clinic["open_status"] == CLINIC_CLOSED
    assert clinic["waiting_count"] == 0
    assert clinic["last_realized_wait_minutes"] is None


def test_a_closed_clinic_refuses_appointment_booking_with_the_closure_error(api):
    """The booking path that survives LIMITED does not survive CLOSED.

    PRD: "The clinic's `open_status` must permit the operation: a `CLOSED` clinic refuses
    every intake, call and visit with `ERR_CLINIC_CLOSED` (409), and a `LIMITED` clinic
    refuses walk-in intake with `ERR_WALK_IN_SUSPENDED` (409) while still admitting
    appointment arrivals."

    Design: Corner/validations/corner_closed_clinic_refuses_appointment_intake_as_well_as_walk_ins
    """
    env = _clinic_that_was_never_staffed(api)
    payload = appointment_payload(env["clinic_id"], env["patient"]["id"],
                                  "2026-08-01T09:00:00Z")

    response = api.create_queue_entry(payload, env["front_desk"])

    validate_error(response, ApiErrorId.ERR_CLINIC_CLOSED, 409)
    assert error_id(response) != "ERR_WALK_IN_SUSPENDED"
    assert payload["kind"] == QUEUE_KIND_APPOINTMENT


def test_a_closed_clinic_refuses_walk_in_intake_with_the_same_closure_error(api):
    """Closure is the stricter posture, so the walk-in suspension never surfaces.

    PRD: "The clinic must be fully `OPEN`: a `LIMITED` clinic — one that has some
    clinician on duty but fewer than its floor — refuses walk-ins with
    `ERR_WALK_IN_SUSPENDED`, and a `CLOSED` clinic refuses them with
    `ERR_CLINIC_CLOSED`."

    Design: Corner/validations/corner_closed_clinic_refuses_appointment_intake_as_well_as_walk_ins
    """
    env = _clinic_that_was_never_staffed(api)

    response = api.create_queue_entry(
        walk_in_payload(env["clinic_id"], env["patient"]["id"]), env["front_desk"])

    validate_error(response, ApiErrorId.ERR_CLINIC_CLOSED, 409)
    assert error_id(response) != "ERR_WALK_IN_SUSPENDED"
    rows, meta = validate_paginated(
        api.list_queue_entries(env["admin"], params={"clinic_id": env["clinic_id"]}))
    assert rows == []
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# corner_charge_void_before_invoicing_returns_charge_not_voidable
# ---------------------------------------------------------------------------

def _verified_but_never_invoiced_visit(api):
    """Van Void's insured visit is TREATED and COVERAGE_VERIFIED, never checked out."""
    env = staffed_clinic(api, protocol={"requires_cosign": False})
    patient = create_insured_patient(
        api, env["front_desk"], full_name="Van Void", date_of_birth="1987-12-27",
        payer_name="BlueCo", member_id="M-1111", pcp_consent_on_file=False)
    env["patient"] = patient
    env["bundle"] = treated_visit(api, env, patient["id"],
                                  vitals={"temp_c": 37.1, "heart_rate_bpm": 78,
                                          "spo2_pct": 98})
    env["visit_id"] = env["bundle"]["visit_id"]
    env["verified"] = verify_active_coverage(api, env, env["visit_id"],
                                             copay_cents=2500, coinsurance_pct=12.5)
    return env


def test_an_active_eligibility_answer_only_verifies_coverage_and_quotes(api):
    """Verification is not invoicing: the money dimension stops at an estimate.

    PRD: "Its `coverage_status` becomes `ACTIVE`, its `self_pay` flag is set false, the
    reported `copay_cents` and `coinsurance_pct` are stored on the visit, and
    `quoted_price_cents` is written with an **insured estimate**."

    Design: Corner/validations/corner_charge_void_before_invoicing_returns_charge_not_voidable
    """
    env = _verified_but_never_invoiced_visit(api)

    verified = env["verified"]

    assert verified["billing_status"] == BILLING_COVERAGE_VERIFIED
    assert verified["self_pay"] is False
    assert verified["quoted_price_cents"] == 3425
    assert verified["final_price_cents"] is None


def test_voiding_a_charge_that_was_never_raised_is_refused(api):
    """The compensation cannot run before the invoice it is meant to compensate.

    PRD: "The visit's `billing_status` must be `INVOICED`, else
    `ERR_CHARGE_NOT_VOIDABLE`."

    Design: Corner/validations/corner_charge_void_before_invoicing_returns_charge_not_voidable
    """
    env = _verified_but_never_invoiced_visit(api)

    response = api.charge_void(env["visit_id"], "Voided too early", env["admin"])

    validate_error(response, ApiErrorId.ERR_CHARGE_NOT_VOIDABLE, 409)
    assert error_id(response) != "ERR_VISIT_INVALID_STATE"


def test_the_refused_void_leaves_the_verified_visit_exactly_as_it_was(api):
    """Both dimensions hold their place and no money was ever attributed.

    PRD: "Only an invoiced visit may be voided, else `ERR_CHARGE_NOT_VOIDABLE` (409)."

    Design: Corner/validations/corner_charge_void_before_invoicing_returns_charge_not_voidable
    """
    env = _verified_but_never_invoiced_visit(api)

    api.charge_void(env["visit_id"], "Voided too early", env["admin"])

    visit = read_visit(api, env["visit_id"])
    assert visit["billing_status"] == BILLING_COVERAGE_VERIFIED
    assert visit["clinical_status"] == VISIT_TREATED
    assert visit["final_price_cents"] is None
    assert read_patient(api, env["patient"]["id"])["outstanding_balance_cents"] == 0


# ---------------------------------------------------------------------------
# corner_outstanding_balance_ceiling_blocks_the_next_self_pay_visit
# ---------------------------------------------------------------------------

def _patient_over_the_ceiling_with_a_second_entry_already_called(api):
    """Bea Balance owes 51000 from one closed self-pay visit and has been called again."""
    env = staffed_clinic(api, protocol={"complaint_code": COMPLAINT_SPORTS_PHYSICAL,
                                        "base_price_cents": 60000,
                                        "min_age_months": 24,
                                        "max_heart_rate_bpm": 130,
                                        "red_flag_codes": ("ANAPHYLAXIS",),
                                        "requires_cosign": False})
    patient = create_patient(api, env["front_desk"], full_name="Bea Balance",
                             date_of_birth="1977-07-17")
    env["patient"] = patient
    first = treated_visit(api, env, patient["id"],
                          complaint_code=COMPLAINT_SPORTS_PHYSICAL,
                          vitals={"temp_c": 37.0, "heart_rate_bpm": 82,
                                  "spo2_pct": 98})
    env["first_visit_id"] = first["visit_id"]
    env["quoted"] = quote_self_pay(api, env, first["visit_id"])
    accept_quote(api, first["visit_id"], 51000, headers=env["front_desk"])
    env["closed"] = checkout(api, env, first["visit_id"], services_rendered=[])
    env["second_entry"] = add_walk_in(api, env, patient["id"],
                                      complaint_code=COMPLAINT_SPORTS_PHYSICAL)
    env["called_again"] = call_next(api, env)
    return env


def test_a_sixty_thousand_cent_base_quotes_the_fifteen_percent_self_pay_tier(api):
    """60000 sits in the top tier, so the single aggregate discount is 9000.

    PRD: "Second, choose the tier from that subtotal: a subtotal below 10000 cents earns
    no discount, a subtotal from 10000 cents up to but not including 20000 cents earns
    10 percent, and a subtotal of 20000 cents or more earns 15 percent."

    Design: Corner/validations/corner_outstanding_balance_ceiling_blocks_the_next_self_pay_visit
    """
    env = _patient_over_the_ceiling_with_a_second_entry_already_called(api)

    assert env["quoted"]["quoted_price_cents"] == 51000
    assert env["quoted"]["billing_status"] == BILLING_SELF_PAY_QUOTED


def test_the_invoiced_self_pay_visit_carries_the_patient_past_the_ceiling(api):
    """51000 is strictly greater than the 50000-cent global ceiling.

    PRD: "A patient whose `outstanding_balance_cents` is strictly greater than 50000
    cents — five hundred dollars — may not open a further visit that would be priced on
    the self-pay path, and the attempt is refused with `ERR_OUTSTANDING_BALANCE_BLOCK`
    (HTTP 402)."

    Design: Corner/validations/corner_outstanding_balance_ceiling_blocks_the_next_self_pay_visit
    """
    env = _patient_over_the_ceiling_with_a_second_entry_already_called(api)

    assert env["closed"]["patient_responsibility_cents"] == 51000
    assert env["closed"]["final_price_cents"] == 51000
    balance = read_patient(api, env["patient"]["id"])["outstanding_balance_cents"]
    assert balance == 51000
    assert balance > 50000


def test_the_next_visit_for_that_patient_is_refused_at_the_fiscal_door(api):
    """The gate fires at visit-open time, after the entry has already been called.

    PRD: "When the patient has no `payer_name` on file — the condition that will force
    this visit onto the self-pay path — and their `outstanding_balance_cents` is strictly
    greater than 50000, the visit is refused with `ERR_OUTSTANDING_BALANCE_BLOCK`."

    Design: Corner/validations/corner_outstanding_balance_ceiling_blocks_the_next_self_pay_visit
    """
    env = _patient_over_the_ceiling_with_a_second_entry_already_called(api)
    assert env["called_again"]["id"] == env["second_entry"]["id"]

    response = api.create_visit(visit_payload(env["second_entry"]["id"]),
                                env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_OUTSTANDING_BALANCE_BLOCK, 402)
    assert error_id(response) != "ERR_QUEUE_ENTRY_NOT_CALLABLE"


def test_the_refused_visit_does_not_consume_the_called_queue_entry(api):
    """No visit was opened, so the entry never advanced to SERVED.

    PRD: "The visit copies its `clinic_id`, its `patient_id` and its `complaint_code`
    from the entry it consumes, and the consumed entry advances `CALLED → SERVED` in the
    same request."

    Design: Corner/validations/corner_outstanding_balance_ceiling_blocks_the_next_self_pay_visit
    """
    env = _patient_over_the_ceiling_with_a_second_entry_already_called(api)
    api.create_visit(visit_payload(env["second_entry"]["id"]), env["clinician_headers"])

    entry = read_queue_entry(api, env["second_entry"]["id"])
    rows, meta = validate_paginated(
        api.list_visits(env["admin"], params={"patient_id": env["patient"]["id"]}))

    assert entry["status"] == QUEUE_CALLED
    assert meta["total_count"] == 1
    assert rows[0]["id"] == env["first_visit_id"]


# ---------------------------------------------------------------------------
# corner_scope_deviation_needs_a_disinterested_reviewer_then_holds_the_clinician
# ---------------------------------------------------------------------------

def _pending_review_whose_reviewer_also_cosigned_it(api):
    """NP Wren's cosigned, closed chart is sampled back to the very cosigner."""
    env = staffed_clinic(api, protocol={"requires_cosign": True},
                         physician={"full_name": "Dr Supervisor Fifty Five"},
                         clinician={"full_name": "NP Wren"})
    env["other_physician"] = create_physician(api, env["admin"],
                                              full_name="Dr Disinterested",
                                              licensed_state_codes=("CA",),
                                              max_supervised_clinicians=3)
    env["other_physician_headers"] = make_physician_headers(
        env["other_physician"]["id"])
    held = create_insured_patient(api, env["front_desk"], full_name="Hank Held",
                                  date_of_birth="1978-08-18", payer_name="BlueCo",
                                  member_id="M-2222", pcp_consent_on_file=False)
    env["bundle"] = closed_insured_visit(api, env, held["id"], cosign=True,
                                         services_rendered=[],
                                         vitals={"temp_c": 37.3, "heart_rate_bpm": 84,
                                                 "spo2_pct": 97})
    env["run"] = run_sampling(api, env["clinic_id"], "2026-08-01T00:00:00Z",
                              "2026-08-02T00:00:00Z")
    env["review_id"] = env["run"]["chart_review_ids"][0]
    nina = create_insured_patient(api, env["front_desk"], full_name="Nina Next",
                                  date_of_birth="1979-09-19", payer_name="BlueCo",
                                  member_id="M-2223", pcp_consent_on_file=False)
    env["next_patient"] = nina
    env["next_entry"] = add_walk_in(api, env, nina["id"])
    call_next(api, env)
    return env


def test_the_physician_who_cosigned_the_chart_may_not_attest_its_review(api):
    """He is the review's own reviewer, so only segregation of duties can stop him.

    PRD: "Both are also subject to segregation of duties: the physician who cosigned the
    assessment under review may not attest the review of that same assessment, and the
    attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/corner_scope_deviation_needs_a_disinterested_reviewer_then_holds_the_clinician
    """
    env = _pending_review_whose_reviewer_also_cosigned_it(api)
    review = read_chart_review(api, env["review_id"])
    assert review["reviewer_physician_id"] == env["physician_id"]

    response = api.attest_chart_review(env["review_id"], OUTCOME_SCOPE_DEVIATION,
                                       env["physician_headers"],
                                       attestation_note="Treated outside protocol")

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    assert error_id(response) != "ERR_FORBIDDEN_OWNERSHIP"


def test_the_refused_attestation_leaves_the_review_pending_and_nobody_on_hold(api):
    """A blocked escalation must not half-apply: no outcome, no scope hold.

    PRD: "Its `changes_requested_count` starts at 0 and its `outcome` starts null."

    Design: Corner/validations/corner_scope_deviation_needs_a_disinterested_reviewer_then_holds_the_clinician
    """
    env = _pending_review_whose_reviewer_also_cosigned_it(api)

    api.attest_chart_review(env["review_id"], OUTCOME_SCOPE_DEVIATION,
                            env["physician_headers"],
                            attestation_note="Treated outside protocol")

    review = read_chart_review(api, env["review_id"])
    assert review["status"] == REVIEW_PENDING
    assert review["outcome"] is None
    assert read_clinician(api, env["clinician_id"])["scope_hold"] is False


def test_reassignment_finds_a_disinterested_physician_who_can_escalate(api):
    """The remedy is a new reviewer, and his deviation lands the hold on the clinician.

    PRD: "`SCOPE_DEVIATION` moves the review `PENDING → ESCALATED`, records that outcome,
    and sets the reviewed visit's clinician's `scope_hold` to true — a consequential
    flag, because a clinician on hold may no longer be staffed onto a site, may no longer
    open a visit, may no longer create or submit an assessment, may no longer prescribe,
    and is removed from the candidate pool for float coverage."

    Design: Corner/validations/corner_scope_deviation_needs_a_disinterested_reviewer_then_holds_the_clinician
    """
    env = _pending_review_whose_reviewer_also_cosigned_it(api)

    reassigned = validate_success(
        api.reassign_chart_review(env["review_id"], env["admin"]))
    escalated = validate_success(api.attest_chart_review(
        env["review_id"], OUTCOME_SCOPE_DEVIATION, env["other_physician_headers"],
        attestation_note="Treated outside protocol"))

    assert reassigned["reviewer_physician_id"] == env["other_physician"]["id"]
    assert reassigned["status"] == REVIEW_PENDING
    assert escalated["status"] == REVIEW_ESCALATED
    assert escalated["outcome"] == OUTCOME_SCOPE_DEVIATION
    assert read_clinician(api, env["clinician_id"])["scope_hold"] is True


def test_the_scope_hold_then_blocks_that_clinicians_next_visit(api):
    """The queue entry is perfectly callable; the hold on its clinician is what refuses.

    PRD: "The acting clinician's `scope_hold` flag must be clear before they may be
    staffed onto a site, open a visit, assess, or prescribe, else
    `ERR_SCOPE_HOLD_ACTIVE` (422)."

    Design: Corner/validations/corner_scope_deviation_needs_a_disinterested_reviewer_then_holds_the_clinician
    """
    env = _pending_review_whose_reviewer_also_cosigned_it(api)
    validate_success(api.reassign_chart_review(env["review_id"], env["admin"]))
    validate_success(api.attest_chart_review(
        env["review_id"], OUTCOME_SCOPE_DEVIATION, env["other_physician_headers"],
        attestation_note="Treated outside protocol"))

    response = api.create_visit(visit_payload(env["next_entry"]["id"]),
                                env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_SCOPE_HOLD_ACTIVE, 422)
    assert read_queue_entry(api, env["next_entry"]["id"])["status"] == QUEUE_CALLED
    _, meta = validate_paginated(
        api.list_visits(env["admin"], params={"clinic_id": env["clinic_id"]}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# corner_superseding_prescription_passes_the_duplicate_therapy_gate
# ---------------------------------------------------------------------------

def _patient_already_holding_a_routed_macrolide(api):
    """Dora Duplicate's treated visit carries one ROUTED macrolide, so the class is locked."""
    env = staffed_clinic(api, protocol={"requires_cosign": False})
    patient = create_patient(api, env["front_desk"], full_name="Dora Duplicate",
                             date_of_birth="1980-10-20")
    env["patient"] = patient
    env["bundle"] = treated_visit(api, env, patient["id"],
                                  vitals={"temp_c": 37.2, "heart_rate_bpm": 82,
                                          "spo2_pct": 98})
    env["visit_id"] = env["bundle"]["visit_id"]
    treated = read_visit(api, env["visit_id"], env["clinician_headers"])
    env["first_rx"] = validate_success(api.create_prescription(
        prescription_payload(env["visit_id"], treated["version"],
                             drug_name="Azithromycin 250mg",
                             therapy_class=THERAPY_ANTIBIOTIC_MACROLIDE,
                             days_supply=5),
        env["clinician_headers"]), 201)
    env["first_routed"] = validate_success(
        api.route_prescription(env["first_rx"]["id"], env["clinician_headers"]))
    env["visit_version"] = read_visit(api, env["visit_id"],
                                      env["clinician_headers"])["version"]
    return env


def _superseding_draft(api, env):
    """The replacement macrolide, naming the predecessor it will cancel."""
    return api.create_prescription(
        prescription_payload(env["visit_id"], env["visit_version"],
                             drug_name="Clarithromycin 500mg",
                             therapy_class=THERAPY_ANTIBIOTIC_MACROLIDE,
                             days_supply=7,
                             supersedes_prescription_id=env["first_rx"]["id"]),
        env["clinician_headers"])


def test_routing_the_first_macrolide_takes_the_patients_therapy_lock(api):
    """The lock is taken at the pharmacy handoff, not at draft time.

    PRD: "On success the prescription advances `DRAFT → ROUTED`, its `routed_at` is
    stamped with the logical clock, and the patient's `active_therapy_classes` gains this
    `therapy_class` with `active_therapy_class_count` recomputed as the length of that
    set."

    Design: Corner/validations/corner_superseding_prescription_passes_the_duplicate_therapy_gate
    """
    env = _patient_already_holding_a_routed_macrolide(api)

    assert env["first_routed"]["status"] == PRESCRIPTION_ROUTED
    assert env["first_routed"]["routed_at"] is not None
    patient = read_patient(api, env["patient"]["id"])
    assert patient["active_therapy_classes"] == [THERAPY_ANTIBIOTIC_MACROLIDE]
    assert patient["active_therapy_class_count"] == 1


def test_a_second_macrolide_draft_naming_no_predecessor_is_refused(api):
    """The patient already holds that class, and nothing was named as superseded.

    PRD: "And the patient may not be given a second live therapy in a class they already
    hold: if `therapy_class` already appears in the patient's `active_therapy_classes`,
    the draft is refused with `ERR_DUPLICATE_THERAPY` — unless the request names, through
    `supersedes_prescription_id`, the very prescription holding that class, in which case
    the check ignores the class held by the named predecessor."

    Design: Corner/validations/corner_superseding_prescription_passes_the_duplicate_therapy_gate
    """
    env = _patient_already_holding_a_routed_macrolide(api)

    response = api.create_prescription(
        prescription_payload(env["visit_id"], env["visit_version"],
                             drug_name="Clarithromycin 500mg",
                             therapy_class=THERAPY_ANTIBIOTIC_MACROLIDE,
                             days_supply=7),
        env["clinician_headers"])

    validate_error(response, ApiErrorId.ERR_DUPLICATE_THERAPY, 422)
    assert error_id(response) != "ERR_STALE_VISIT_VERSION"


def test_naming_the_predecessor_lets_the_superseding_draft_through(api):
    """The escape hatch ignores the class held by the prescription being replaced.

    PRD: "A fresh draft has `status` of `DRAFT` and a null `routed_at`."

    Design: Corner/validations/corner_superseding_prescription_passes_the_duplicate_therapy_gate
    """
    env = _patient_already_holding_a_routed_macrolide(api)

    draft = validate_success(_superseding_draft(api, env), 201)

    assert draft["status"] == PRESCRIPTION_DRAFT
    assert draft["routed_at"] is None
    assert draft["supersedes_prescription_id"] == env["first_rx"]["id"]


def test_routing_the_successor_cancels_its_predecessor_and_keeps_one_lock(api):
    """Supersession never leaves the patient holding two locks in one class.

    PRD: "When the request named a predecessor, the ordering is pinned: the named
    prescription transitions `ROUTED → CANCELLED` first, and only afterwards is the
    patient's lock set recomputed, so the supersession never leaves the patient briefly
    holding two locks in one class."

    Design: Corner/validations/corner_superseding_prescription_passes_the_duplicate_therapy_gate
    """
    env = _patient_already_holding_a_routed_macrolide(api)
    draft = validate_success(_superseding_draft(api, env), 201)

    routed = validate_success(
        api.route_prescription(draft["id"], env["clinician_headers"]))

    assert routed["status"] == PRESCRIPTION_ROUTED
    assert read_prescription(api, env["first_rx"]["id"])["status"] == \
        PRESCRIPTION_CANCELLED
    patient = read_patient(api, env["patient"]["id"])
    assert patient["active_therapy_classes"] == [THERAPY_ANTIBIOTIC_MACROLIDE]
    assert patient["active_therapy_class_count"] == 1
