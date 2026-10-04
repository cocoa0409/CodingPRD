"""Travel authorization, itinerary lock, fatigue withdrawal, closure workflow."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_specialty_service_payload,
    get_case,
    get_case_itinerary,
    get_success_data,
    issue_estimate_letter,
    set_clock,
    setup_approved_case,
    setup_case_with_holds,
    setup_fatigue_case,
    setup_ready_to_travel_case,
    setup_referral_in_review,
    setup_scheduled_case,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
CR = TEST_USERS["case_reviewer_headers"]
FC = TEST_USERS["financial_counselor_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


def _verify(api, referral_id, record_id):
    resp = api.verify_medical_record(referral_id, record_id, CR)
    return resp


def test_withdraw_after_scheduled_rejected(api):
    """PRD §3.7: "A coordinator may withdraw a case manually at any point
    before the schedule locks: withdrawal is permitted from `INTAKE`,
    `AWAITING_FINANCIAL`, `FINANCIAL_CLEARED`, or `SCHEDULING`; attempting it
    from `SCHEDULED` or any later state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/withdraw_after_scheduled_rejected
    """
    set_clock()
    ctx = setup_scheduled_case()
    case_id = ctx["case"]["id"]
    assert ctx["case"]["status"] == "SCHEDULED"
    resp = api.withdraw_case(case_id, IC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_case(case_id)["status"] == "SCHEDULED"


def test_lock_before_ready_to_travel_rejected(api):
    """PRD §3.7: "Only then may the itinerary be locked: locking requires the
    itinerary `CONFIRMED` and the case `READY_TO_TRAVEL`, moves the itinerary
    to terminal `LOCKED`, and renders all subsequent rescheduling attempts
    against it rejectable with `ERR_INVALID_STATE` — a locked itinerary is
    immutable."

    Design: Difficulty/non_linear_state_machine/itinerary_draft_confirmed_locked_with_cancel_branch
    """
    set_clock()
    ctx = setup_scheduled_case()
    itinerary_id = ctx["itinerary"]["id"]
    assert get_case(ctx["case"]["id"])["status"] == "SCHEDULED"
    resp = api.lock_itinerary(itinerary_id, IC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    itinerary = get_success_data(api.get_itinerary(itinerary_id, IC))
    assert itinerary["status"] == "CONFIRMED"


def test_lock_after_ready_to_travel_succeeds(api):
    """PRD §3.7: "Only then may the itinerary be locked: locking requires the
    itinerary `CONFIRMED` and the case `READY_TO_TRAVEL`, moves the itinerary
    to terminal `LOCKED`, and renders all subsequent rescheduling attempts
    against it rejectable with `ERR_INVALID_STATE` — a locked itinerary is
    immutable."

    Design: Difficulty/non_linear_state_machine/itinerary_draft_confirmed_locked_with_cancel_branch
    """
    set_clock()
    ctx = setup_ready_to_travel_case()
    itinerary_id = ctx["itinerary"]["id"]
    assert ctx["case"]["status"] == "READY_TO_TRAVEL"
    resp = api.lock_itinerary(itinerary_id, IC)
    data = validate_success(resp, 200)
    assert data["status"] == "LOCKED"


def _international_scheduled_case(api, with_interpreter_requested=False):
    """International DESTINATION case, fully scheduled, with a fresh letter."""
    services = []
    for code in ("ONC", "ORTH", "GAST", "ENDO"):
        services.append(get_success_data(api.create_specialty_service(
            create_specialty_service_payload(
                code=code, name=code, destination_daily_capacity=4,
                supports_imaging=True, supports_remote_products=True,
            ),
            ADMIN,
        )))
    ctx = setup_scheduled_case(
        hold_specs=[
            {"slot_date": "2026-09-11", "start_min": 540, "end_min": 600,
             "visit_type": "CONSULT", "listed_price_cents": 200000,
             "sequencing_priority": 1},
            {"slot_date": "2026-09-11", "start_min": 600, "end_min": 660,
             "visit_type": "IMAGING", "listed_price_cents": 200000,
             "sequencing_priority": 2},
        ],
        team_size=4,
        services=services,
        patient_overrides={
            "full_name": "Ingrid International",
            "residence_country": "DE",
            "residence_state": None,
            "preferred_language": "de",
        },
        deposit_cents=216000,
    )
    issue_estimate_letter(ctx["case"]["id"])
    if with_interpreter_requested:
        log = get_success_data(
            api.create_logistics(
                ctx["case"]["id"],
                {"arrangement_type": "INTERPRETER",
                 "details": "de-EN consecutive", "companion_count": 1},
                LC,
            )
        )
        ctx["interpreter"] = log
    return ctx


def test_authorize_travel_blocked_by_unbooked_interpreter(api):
    """PRD §3.7: "The coordinator's authorization requires the case in
    `SCHEDULED` and the itinerary in `CONFIRMED` (`ERR_INVALID_STATE` for
    either mismatch); an `ISSUED` estimate letter that is not stale —
    `ERR_STALE_ESTIMATE_LETTER` when no letter is issued or the outstanding
    one was overtaken by an itinerary revision; and, whenever the patient's
    `requires_interpreter` flag is true, every interpreter arrangement the
    case needs must already be `BOOKED`, else `ERR_INTERPRETER_NOT_BOOKED`."

    Design: Difficulty/cross_entity_state_dependency/authorize_travel_depends_on_logistics_and_letter_state
    """
    set_clock()
    ctx = _international_scheduled_case(api, with_interpreter_requested=True)
    case_id = ctx["case"]["id"]
    resp = api.authorize_travel(case_id, IC)
    validate_error(resp, ApiErrorId.ERR_INTERPRETER_NOT_BOOKED)
    assert get_case(case_id)["status"] == "SCHEDULED"


def test_authorize_travel_succeeds_with_booked_interpreter(api):
    """PRD §3.7: "Success moves the case `SCHEDULED → READY_TO_TRAVEL`."

    Design: Difficulty/cross_entity_state_dependency/authorize_travel_depends_on_logistics_and_letter_state
    """
    set_clock()
    ctx = _international_scheduled_case(api, with_interpreter_requested=True)
    case_id = ctx["case"]["id"]
    log_id = ctx["interpreter"]["id"]
    resp = api.confirm_logistics(case_id, log_id, LC)
    validate_success(resp, 200)
    resp = api.authorize_travel(case_id, IC)
    data = validate_success(resp, 200)
    assert data["status"] == "READY_TO_TRAVEL"


def test_stale_estimate_letter_blocks_authorize_travel(api):
    """PRD §3.7: "an `ISSUED` estimate letter that is not stale —
    `ERR_STALE_ESTIMATE_LETTER` when no letter is issued or the outstanding
    one was overtaken by an itinerary revision; and, whenever the patient's
    `requires_interpreter` flag is true, every interpreter arrangement the
    case needs must already be `BOOKED`, else `ERR_INTERPRETER_NOT_BOOKED`."

    Design: Corner/validations/stale_estimate_letter_blocks_authorize_travel
    """
    set_clock()
    ctx = setup_scheduled_case()
    case_id = ctx["case"]["id"]
    issue_estimate_letter(case_id)
    # Cancel a confirmed visit: itinerary revision bumps, staling the letter.
    resp = api.cancel_visit(ctx["visits"][0]["id"], IC)
    validate_success(resp, 200)
    resp = api.authorize_travel(case_id, IC)
    validate_error(resp, ApiErrorId.ERR_STALE_ESTIMATE_LETTER)


def test_fatigue_five_verifies_auto_withdraw_at_ten(api):
    """PRD §3.3: "After any increment lands, the system re-checks the
    withdrawal threshold: if `fatigue_score` has reached at least 10 — the
    boundary is inclusive, so exactly 10 triggers — and the case is in
    `INTAKE`, `AWAITING_FINANCIAL`, `FINANCIAL_CLEARED`, or `SCHEDULING`, the
    case auto-withdraws with the standard release cascade of §3.7."

    Design: Difficulty/combinatorial_formula/review_fatigue_circular_accumulator_evaluation_order
    """
    set_clock()
    # Record 0 is verified before the case exists (lands on no case, per
    # PRD §3.3 "on every non-terminal visit case under the same referral" at
    # the moment of verification). Post-case verifies of records 1..5 each
    # add 2: 2, 4, 6, 8, then 10 -> auto-withdrawal fires.
    ctx = setup_fatigue_case(num_records=6, verify_first=1)
    case_id = ctx["case"]["id"]
    referral_id = ctx["referral"]["id"]
    for rec in ctx["records"][1:5]:
        resp = _verify(api, referral_id, rec["id"])
        validate_success(resp, 200)
    case = get_case(case_id)
    assert case["fatigue_score"] == 8
    assert case["status"] == "INTAKE"
    # Fifth post-case verify: 8 + 2 = 10 -> auto-withdrawal fires.
    resp = _verify(api, referral_id, ctx["records"][5]["id"])
    validate_success(resp, 200)
    case = get_case(case_id)
    assert case["fatigue_score"] == 10
    assert case["status"] == "WITHDRAWN"


def test_verify_before_case_exists_does_not_count(api):
    """PRD §3.3: "Each time a medical record is verified, `fatigue_score`
    increases by 2 on every non-terminal visit case under the same referral."

    Design: Difficulty/combinatorial_formula/review_fatigue_circular_accumulator_evaluation_order
    """
    set_clock()
    # One record verified BEFORE the case exists -> that increment lands on no
    # case. After case creation the score must still be 0.
    ctx = setup_fatigue_case(num_records=2, verify_first=1)
    case = get_case(ctx["case"]["id"])
    assert case["fatigue_score"] == 0
    assert case["status"] == "INTAKE"
    # Second record verified after the case exists -> score 2.
    resp = _verify(api, ctx["referral"]["id"], ctx["records"][1]["id"])
    validate_success(resp, 200)
    case = get_case(ctx["case"]["id"])
    assert case["fatigue_score"] == 2


def test_fatigue_withdrawal_without_explicit_withdraw_call(api):
    """PRD §3.3: "After any increment lands, the system re-checks the
    withdrawal threshold: if `fatigue_score` has reached at least 10 — the
    boundary is inclusive, so exactly 10 triggers — and the case is in
    `INTAKE`, `AWAITING_FINANCIAL`, `FINANCIAL_CLEARED`, or `SCHEDULING`, the
    case auto-withdraws with the standard release cascade of §3.7. The
    threshold check always runs after the increment, never before."

    Design: Difficulty/transitive_cascade/record_verification_fatigue_withdrawal_cascade
    """
    set_clock()
    ctx = setup_fatigue_case(num_records=6, verify_first=1)
    referral_id = ctx["referral"]["id"]
    for rec in ctx["records"][1:5]:
        resp = _verify(api, referral_id, rec["id"])
        validate_success(resp, 200)
    assert get_case(ctx["case"]["id"])["fatigue_score"] == 8
    resp = _verify(api, referral_id, ctx["records"][5]["id"])
    validate_success(resp, 200)
    case = get_case(ctx["case"]["id"])
    assert case["fatigue_score"] == 10
    assert case["status"] == "WITHDRAWN"


def test_nine_points_does_not_withdraw(api):
    """PRD §3.3: "if `fatigue_score` has reached at least 10 — the boundary is
    inclusive, so exactly 10 triggers — and the case is in `INTAKE`,
    `AWAITING_FINANCIAL`, `FINANCIAL_CLEARED`, or `SCHEDULING`, the case
    auto-withdraws with the standard release cascade of §3.7."

    Design: Difficulty/transitive_cascade/record_verification_fatigue_withdrawal_cascade
    """
    set_clock()
    # Four post-case verifies: 2*4 = 8 < 10; case remains INTAKE.
    ctx = setup_fatigue_case(num_records=5, verify_first=1)
    referral_id = ctx["referral"]["id"]
    for rec in ctx["records"][1:5]:
        resp = _verify(api, referral_id, rec["id"])
        validate_success(resp, 200)
    case = get_case(ctx["case"]["id"])
    assert case["fatigue_score"] == 8
    assert case["status"] == "INTAKE"


def test_case_auto_completes_and_referral_closes_after_communications(api):
    """PRD §3.7: "Visit completion or no-show triggers re-evaluation of case
    auto-completion: when every non-cancelled visit under the itinerary has
    reached `COMPLETED` or `NO_SHOW` and at least one visit stands
    `COMPLETED`, the case moves `READY_TO_TRAVEL → COMPLETED`."
    PRD §3.8: "Closure requires both a `RESULTS_TO_REFERRER` communication and
    a `CONTINUITY_PLAN` communication to exist for the case; the
    missing-results condition is reported as `ERR_RESULTS_NOT_TRANSMITTED` and
    the missing-plan condition as `ERR_CONTINUITY_PLAN_MISSING`. Until both
    exist, the case simply remains `COMPLETED` and the referral remains
    `REVIEWED`; with both in place, the referral moves `REVIEWED` → `CLOSED`,
    terminally."

    Design: Corner/state_machines/case_auto_completes_and_referral_closes_after_communications
    """
    set_clock()
    ctx = setup_ready_to_travel_case()
    case_id = ctx["case"]["id"]
    referral_id = ctx["referral"]["id"]
    itinerary_id = ctx["itinerary"]["id"]
    set_clock("2026-09-10T12:00:00Z")
    visits = get_success_data(api.list_itinerary_visits(itinerary_id, IC))
    for visit in sorted(visits, key=lambda v: v["sequencing_priority"]):
        resp = api.complete_visit(visit["id"], IC)
        validate_success(resp, 200)
    assert get_case(case_id)["status"] == "COMPLETED"
    referral_mid = get_success_data(api.get_referral(referral_id, IC))
    assert referral_mid["status"] == "REVIEWED"

    resp = api.create_communication(
        case_id,
        {"comm_type": "RESULTS_TO_REFERRER", "body": "findings attached"},
        CR,
    )
    validate_success(resp, 201)
    assert get_success_data(api.get_referral(referral_id, IC))["status"] == "REVIEWED"

    resp = api.create_communication(
        case_id,
        {
            "comm_type": "CONTINUITY_PLAN",
            "body": "plan",
            "continuity_plan": {"owner": "LOCAL_PHYSICIAN", "follow_up_weeks": 4},
        },
        CR,
    )
    validate_success(resp, 201)
    assert get_success_data(api.get_referral(referral_id, IC))["status"] == "CLOSED"


def test_complete_out_of_sequencing_order_rejected(api):
    """PRD §3.7: "same-day sequencing must be respected: no other visit on the
    same itinerary and the same `slot_date` with a lower `sequencing_priority`
    may still be `CONFIRMED`, with ties broken by earlier `created_at` first;
    violating the order yields `ERR_SEQUENCING_VIOLATION`."

    Design: Corner/state_machines/complete_out_of_sequencing_order_rejected
    """
    set_clock()
    ctx = setup_scheduled_case()
    itinerary_id = ctx["itinerary"]["id"]
    set_clock("2026-09-10T12:00:00Z")
    visits = get_success_data(api.list_itinerary_visits(itinerary_id, IC))
    by_prio = sorted(visits, key=lambda v: v["sequencing_priority"])
    assert len(by_prio) == 2
    # Completing the priority-2 visit while priority-1 is still CONFIRMED.
    resp = api.complete_visit(by_prio[1]["id"], IC)
    validate_error(resp, ApiErrorId.ERR_SEQUENCING_VIOLATION)
    visit_after = get_success_data(api.get_visit(by_prio[1]["id"], IC))
    assert visit_after["status"] == "CONFIRMED"


def test_complete_before_slot_date_rejected(api):
    """PRD §3.7: "the logical clock's date must be at least the visit's
    `slot_date` — completing early is rejected with `ERR_VISIT_NOT_DUE` — and
    same-day sequencing must be respected: no other visit on the same
    itinerary and the same `slot_date` with a lower `sequencing_priority` may
    still be `CONFIRMED`, with ties broken by earlier `created_at` first;
    violating the order yields `ERR_SEQUENCING_VIOLATION`."

    Design: Corner/state_machines/complete_before_slot_date_rejected
    """
    set_clock()
    ctx = setup_case_with_holds([{"start_min": 540, "end_min": 600}])
    slot = ctx["slots"][0]
    visit_id = ctx["visits"][0]["id"]
    resp = api.confirm_slot(slot["id"], IC)
    validate_success(resp, 200)
    # Clock still 2026-09-01, slot date 2026-09-10.
    resp = api.complete_visit(visit_id, IC)
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_DUE)


def test_second_opinion_case_creation_single_specialty(api):
    """PRD §3.3: "`SECOND_OPINION` and `REMOTE_CONSULT` are the remote
    products for patients who do not travel; each takes exactly one specialty,
    and that specialty must have `supports_remote_products` true, or creation
    fails with `ERR_REMOTE_PRODUCT_UNSUPPORTED`."

    Design: Corner/cross_cutting_layers/second_opinion_case_completes_without_itinerary
    """
    set_clock()
    svc = get_success_data(
        api.create_specialty_service(
            create_specialty_service_payload(code="CARD", name="Cardiology"), ADMIN
        )
    )
    referral, _rec = setup_referral_in_review()
    resp = api.create_visit_case(
        {
            "referral_id": referral["id"],
            "case_type": "SECOND_OPINION",
            "care_team_specialty_ids": [svc["id"]],
        },
        IC,
    )
    case = validate_success(resp, 201)
    assert case["case_type"] == "SECOND_OPINION"
    assert case["status"] == "INTAKE"
    assert len(case["care_team_specialty_ids"]) == 1


def test_remote_product_on_unsupported_service_rejected(api):
    """PRD §3.3: "each takes exactly one specialty, and that specialty must
    have `supports_remote_products` true, or creation fails with
    `ERR_REMOTE_PRODUCT_UNSUPPORTED`."

    Design: Corner/validations/remote_product_on_unsupported_service_rejected
    """
    set_clock()
    svc = get_success_data(
        api.create_specialty_service(
            create_specialty_service_payload(
                code="SURG", name="Surgery", destination_daily_capacity=1,
                supports_imaging=False, supports_remote_products=False,
            ),
            ADMIN,
        )
    )
    referral, _rec = setup_referral_in_review()
    resp = api.create_visit_case(
        {
            "referral_id": referral["id"],
            "case_type": "SECOND_OPINION",
            "care_team_specialty_ids": [svc["id"]],
        },
        IC,
    )
    validate_error(resp, ApiErrorId.ERR_REMOTE_PRODUCT_UNSUPPORTED)


def test_interpreter_arrangement_for_english_patient_rejected(api):
    """PRD §3.8: "An `INTERPRETER` arrangement is only lawful when the patient
    `requires_interpreter` — requesting one otherwise is rejected with
    `ERR_INTERPRETER_NOT_REQUIRED`."

    Design: Corner/validations/interpreter_arrangement_for_english_patient_rejected
    """
    set_clock()
    ctx = setup_approved_case()  # domestic English patient
    resp = api.create_logistics(
        ctx["case"]["id"],
        {"arrangement_type": "INTERPRETER", "details": "unneeded",
         "companion_count": 0},
        LC,
    )
    validate_error(resp, ApiErrorId.ERR_INTERPRETER_NOT_REQUIRED)
