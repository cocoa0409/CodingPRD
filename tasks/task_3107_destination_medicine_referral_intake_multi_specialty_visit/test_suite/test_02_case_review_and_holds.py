"""Case review, segregation of duties, OCC on holds, and booking validations."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_patient_payload,
    create_referral_payload,
    create_slot_payload,
    create_specialty_service_payload,
    get_case_version,
    get_success_data,
    hold_slot,
    register_and_verify_record,
    register_record,
    set_clock,
    setup_approved_case,
    setup_card_neur_services,
    setup_case_with_holds,
    setup_cleared_case,
    setup_referral_in_review,
    validate_error,
    validate_success,
)


def test_case_creation_requires_referral_in_review(api):
    """PRD §3.3: "Opening a case against a referral that is not `IN_REVIEW`
    fails with `ERR_REFERRAL_NOT_IN_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/case_creation_depends_on_referral_in_review
    """
    set_clock()
    card, neur = setup_card_neur_services()
    ic = TEST_USERS["intake_coordinator_headers"]
    referral = get_success_data(api.create_referral(create_referral_payload(), ic))
    # One record received but never verified/submitted: referral is RECORDS_PENDING.
    register_record(referral["id"], ic_headers=ic)

    resp = api.create_visit_case(
        {
            "referral_id": referral["id"],
            "case_type": "DESTINATION",
            "care_team_specialty_ids": [card["id"], neur["id"]],
        },
        ic,
    )
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_IN_REVIEW)
    rows = get_success_data(
        api.list_visit_cases(ic, params={"referral_id": referral["id"]})
    )
    assert rows == []


def test_case_creation_after_submit_review_succeeds(api):
    """PRD §3.3: "With a referral `IN_REVIEW`, an `IntakeCoordinator` opens a
    visit case by naming the `referral_id`, the `case_type`, and the
    `care_team_specialty_ids`."

    Design: Difficulty/cross_entity_state_dependency/case_creation_depends_on_referral_in_review
    """
    set_clock()
    card, neur = setup_card_neur_services()
    referral, _rec = setup_referral_in_review()
    ic = TEST_USERS["intake_coordinator_headers"]
    resp = api.create_visit_case(
        {
            "referral_id": referral["id"],
            "case_type": "DESTINATION",
            "care_team_specialty_ids": [card["id"], neur["id"]],
        },
        ic,
    )
    case = validate_success(resp, 201)
    assert case["status"] == "INTAKE"
    assert case["assigned_coordinator_id"] == ic["X-User-ID"]


def test_self_review_rejected_with_segregation_of_duties(api):
    """PRD §3.3: "Three guards fire on every review, in this order: the case
    must currently be `INTAKE` (`ERR_INVALID_STATE` otherwise), its referral
    must still be `IN_REVIEW` (`ERR_REFERRAL_NOT_IN_REVIEW`), and the reviewer
    must not be the case's `assigned_coordinator_id`
    (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Difficulty/priority_pair_validation_conflict/segregation_safety_beats_referential_care_team_on_review
    """
    set_clock()
    card, neur = setup_card_neur_services()
    referral, _rec = setup_referral_in_review()
    ic = TEST_USERS["intake_coordinator_headers"]
    case = get_success_data(
        api.create_visit_case(
            {
                "referral_id": referral["id"],
                "case_type": "DESTINATION",
                "care_team_specialty_ids": [card["id"], neur["id"]],
            },
            ic,
        )
    )
    # Review submitted by the coordinator who created the case.
    reviewer_headers = {
        "X-User-ID": ic["X-User-ID"],
        "X-User-Role": "CaseReviewer",
        "Content-Type": "application/json",
    }
    resp = api.create_case_review(
        case["id"], {"outcome": "APPROVE", "notes": "self-review attempt"},
        reviewer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_single_specialty_destination_care_team_rejected(api):
    """PRD §3.3: "A care team that references unknown services, or whose size
    violates the case-type rule, is rejected with `ERR_INVALID_CARE_TEAM`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_safety_beats_referential_care_team_on_review
    """
    set_clock()
    card, _neur = setup_card_neur_services()
    referral, _rec = setup_referral_in_review()
    ic = TEST_USERS["intake_coordinator_headers"]
    resp = api.create_visit_case(
        {
            "referral_id": referral["id"],
            "case_type": "DESTINATION",
            "care_team_specialty_ids": [card["id"]],
        },
        ic,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_CARE_TEAM)


def test_slot_confirm_state_beats_financial_clearance(api):
    """PRD §2.8: "A failure earlier in this sequence masks all later failures
    for that request."
    PRD §3.4: "Confirming a held slot is a separate coordinator action: it
    requires the slot to be `HELD` (`ERR_INVALID_STATE` otherwise) and the
    owning case's clearance to be `CLEARED` or `WAIVED`
    (`ERR_FINANCIAL_CLEARANCE_REQUIRED` — HTTP 402 — otherwise)."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_fiscal_on_slot_confirm
    """
    set_clock()
    card, _neur = setup_card_neur_services()
    slot = get_success_data(
        api.create_slot(
            card["id"], create_slot_payload(), TEST_USERS["platform_admin_headers"]
        )
    )
    ctx = setup_approved_case(services=[card, _neur])
    # clearance still PENDING, slot never held -> state error must surface.
    assert ctx["clearance"]["status"] == "PENDING"
    resp = api.confirm_slot(slot["id"], TEST_USERS["intake_coordinator_headers"])
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] != ApiErrorId.ERR_FINANCIAL_CLEARANCE_REQUIRED


def test_slot_confirm_on_held_slot_with_pending_clearance_is_fiscal_error(api):
    """PRD §3.4: "Confirming a held slot is a separate coordinator action: it
    requires the slot to be `HELD` (`ERR_INVALID_STATE` otherwise) and the
    owning case's clearance to be `CLEARED` or `WAIVED`
    (`ERR_FINANCIAL_CLEARANCE_REQUIRED` — HTTP 402 — otherwise)."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_fiscal_on_slot_confirm
    """
    set_clock()
    # Cleared case so the hold succeeds; then reopen -> PENDING; confirm fails
    # with the fiscal rule because the slot is genuinely HELD.
    ctx = setup_case_with_holds([{"start_min": 540, "end_min": 600}])
    slot_id = ctx["slots"][0]["id"]
    resp = api.reopen_clearance(
        ctx["case"]["id"], TEST_USERS["financial_counselor_headers"]
    )
    validate_success(resp, 200)
    resp = api.confirm_slot(slot_id, TEST_USERS["intake_coordinator_headers"])
    validate_error(resp, ApiErrorId.ERR_FINANCIAL_CLEARANCE_REQUIRED)


def test_stale_version_on_slot_hold_rejected(api):
    """PRD §2.7: "If that value does not match the case's current `version` —
    for example because another coordinator has just placed or released a hold
    on the same case, each of which legitimately advances the case's `version`
    — the hold is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_slot_hold
    """
    set_clock()
    ctx = setup_cleared_case()
    card = ctx["services"][0]
    case_id = ctx["case"]["id"]
    v0 = get_case_version(case_id)
    slot1 = get_success_data(
        api.create_slot(
            card["id"],
            create_slot_payload(start_min=540, end_min=600),
            TEST_USERS["platform_admin_headers"],
        )
    )
    slot2 = get_success_data(
        api.create_slot(
            card["id"],
            create_slot_payload(start_min=600, end_min=660),
            TEST_USERS["platform_admin_headers"],
        )
    )
    hold_slot(case_id, slot1["id"], v0, visit_type="CONSULT", sequencing_priority=1)
    # v0 is now stale: the first hold bumped the case version.
    resp = api.create_slot_hold(
        case_id,
        {
            "appointment_slot_id": slot2["id"],
            "visit_type": "IMAGING",
            "listed_price_cents": 200000,
            "sequencing_priority": 2,
            "expected_case_version": v0,
        },
        TEST_USERS["intake_coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    slot2_after = get_success_data(
        api.get_slot(slot2["id"], TEST_USERS["intake_coordinator_headers"])
    )
    assert slot2_after["status"] == "OPEN"


def test_current_version_on_slot_hold_succeeds(api):
    """PRD §2.7: "Exactly one write operation in the system is guarded by
    optimistic concurrency control: placing a slot hold on a visit case. The
    request must carry a non-optional `expected_case_version` field containing
    the `version` of the `VisitCase` the client last observed."

    Design: Corner/cross_cutting_layers/occ_current_version_on_slot_hold_succeeds
    """
    set_clock()
    ctx = setup_cleared_case()
    card = ctx["services"][0]
    case_id = ctx["case"]["id"]
    slot1 = get_success_data(
        api.create_slot(
            card["id"],
            create_slot_payload(start_min=540, end_min=600),
            TEST_USERS["platform_admin_headers"],
        )
    )
    slot2 = get_success_data(
        api.create_slot(
            card["id"],
            create_slot_payload(start_min=600, end_min=660),
            TEST_USERS["platform_admin_headers"],
        )
    )
    v0 = get_case_version(case_id)
    hold_slot(case_id, slot1["id"], v0, visit_type="CONSULT", sequencing_priority=1)
    v1 = get_case_version(case_id)
    assert v1 == v0 + 1
    resp = api.create_slot_hold(
        case_id,
        {
            "appointment_slot_id": slot2["id"],
            "visit_type": "IMAGING",
            "listed_price_cents": 200000,
            "sequencing_priority": 2,
            "expected_case_version": v1,
        },
        TEST_USERS["intake_coordinator_headers"],
    )
    visit = validate_success(resp, 201)
    assert visit["status"] == "PENDING"
    slot2_after = get_success_data(
        api.get_slot(slot2["id"], TEST_USERS["intake_coordinator_headers"])
    )
    assert slot2_after["status"] == "HELD"


def test_case_version_increments_on_review_approval(api):
    """PRD §2.5: "The `version` field is an integer that increments on every
    mutation to the resource, including mutations caused by cascading side
    effects initiated elsewhere."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
    """
    set_clock()
    card, neur = setup_card_neur_services()
    referral, _rec = setup_referral_in_review()
    ic = TEST_USERS["intake_coordinator_headers"]
    case = get_success_data(
        api.create_visit_case(
            {
                "referral_id": referral["id"],
                "case_type": "DESTINATION",
                "care_team_specialty_ids": [card["id"], neur["id"]],
            },
            ic,
        )
    )
    assert case["version"] == 1
    resp = api.create_case_review(
        case["id"],
        {"outcome": "APPROVE", "notes": "ok"},
        TEST_USERS["case_reviewer_headers"],
    )
    validate_success(resp, 201)
    after = get_success_data(api.get_visit_case(case["id"], ic))
    assert after["version"] == 2


def test_imaging_visit_on_non_imaging_service_rejected(api):
    """PRD §3.4: "And when the requested `visit_type` is `IMAGING`, the slot's
    service must have `supports_imaging` true, or the hold fails with
    `ERR_IMAGING_NOT_SUPPORTED`; `CONSULT`, `LAB_TEST`, and `PROCEDURE` visit
    types carry no such flag requirement."

    Design: Corner/validations/imaging_visit_on_non_imaging_service_rejected
    """
    set_clock()
    ctx = setup_cleared_case()
    neur = ctx["services"][1]  # supports_imaging False
    slot = get_success_data(
        api.create_slot(
            neur["id"], create_slot_payload(), TEST_USERS["platform_admin_headers"]
        )
    )
    case_id = ctx["case"]["id"]
    resp = api.create_slot_hold(
        case_id,
        {
            "appointment_slot_id": slot["id"],
            "visit_type": "IMAGING",
            "listed_price_cents": 100000,
            "sequencing_priority": 1,
            "expected_case_version": get_case_version(case_id),
        },
        TEST_USERS["intake_coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_IMAGING_NOT_SUPPORTED)
    slot_after = get_success_data(
        api.get_slot(slot["id"], TEST_USERS["intake_coordinator_headers"])
    )
    assert slot_after["status"] == "OPEN"


def test_slot_outside_service_window_rejected(api):
    """PRD §3.1: "Slot creation is rejected with `ERR_OUTSIDE_SERVICE_WINDOW`
    when the interval falls outside the service's window or when the
    `slot_date` is in the past relative to the logical clock."

    Design: Corner/validations/slot_outside_service_window_rejected
    """
    set_clock()
    svc = get_success_data(
        api.create_specialty_service(
            create_specialty_service_payload(code="CARD", name="Cardiology"),
            TEST_USERS["platform_admin_headers"],
        )
    )
    resp = api.create_slot(
        svc["id"],
        create_slot_payload(start_min=1030, end_min=1090),
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_SERVICE_WINDOW)


def test_slot_hold_on_non_open_slot_rejected(api):
    """PRD §3.4: "The target slot must be `OPEN` — holding anything else yields
    `ERR_SLOT_NOT_OPEN`."

    Design: Corner/endpoints/slot_hold_on_non_open_slot_rejected
    """
    set_clock()
    ctx = setup_case_with_holds([{"start_min": 540, "end_min": 600}])
    held_slot = ctx["slots"][0]
    card, neur = ctx["services"]

    # Second case, also cleared, attempts to hold the same slot.
    ic_b = TEST_USERS["intake_coordinator_b_headers"]
    referral_b = get_success_data(
        api.create_referral(
            create_referral_payload(
                patient=create_patient_payload(full_name="Gail Second",
                                               residence_state="IA")
            ),
            ic_b,
        )
    )
    register_and_verify_record(referral_b["id"], ic_headers=ic_b)
    get_success_data(api.submit_review(referral_b["id"], ic_b))
    case_b = get_success_data(
        api.create_visit_case(
            {
                "referral_id": referral_b["id"],
                "case_type": "DESTINATION",
                "care_team_specialty_ids": [card["id"], neur["id"]],
            },
            ic_b,
        )
    )
    get_success_data(
        api.create_case_review(
            case_b["id"], {"outcome": "APPROVE", "notes": "ok"},
            TEST_USERS["case_reviewer_headers"],
        )
    )
    get_success_data(
        api.create_billing_transaction(
            case_b["id"], {"txn_type": "DEPOSIT", "amount_cents": 60000},
            TEST_USERS["financial_counselor_headers"],
        )
    )
    case_b_v = get_case_version(case_b["id"])
    resp = api.create_slot_hold(
        case_b["id"],
        {
            "appointment_slot_id": held_slot["id"],
            "visit_type": "CONSULT",
            "listed_price_cents": 100000,
            "sequencing_priority": 1,
            "expected_case_version": case_b_v,
        },
        ic_b,
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_NOT_OPEN)


def test_hold_before_clearance_rejected(api):
    """PRD §3.4: "Booking opens only after money clears. The first slot hold
    placed against a case in `FINANCIAL_CLEARED` flips the case into
    `SCHEDULING` and bumps the case's `version`; attempting to hold a slot
    before clearance — while the case is still `INTAKE` or
    `AWAITING_FINANCIAL` — is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_fiscal_on_slot_confirm
    """
    set_clock()
    ctx = setup_approved_case()
    card = ctx["services"][0]
    slot = get_success_data(
        api.create_slot(
            card["id"], create_slot_payload(), TEST_USERS["platform_admin_headers"]
        )
    )
    case_id = ctx["case"]["id"]
    resp = api.create_slot_hold(
        case_id,
        {
            "appointment_slot_id": slot["id"],
            "visit_type": "CONSULT",
            "listed_price_cents": 100000,
            "sequencing_priority": 1,
            "expected_case_version": get_case_version(case_id),
        },
        TEST_USERS["intake_coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
