"""Where each state machine opens, which moves it accepts, which side effects
one accepted move must apply all at once, and how it refuses a replay.
"""

from test_helpers import (
    ApiErrors,
    assert_clinic_posture,
    assert_compliance_hold,
    assert_encounter_states,
    assert_error,
    assert_instant_equals,
    assert_list_meta,
    assert_money_fields,
    assert_responsibility,
    assert_shelf,
    attest_standards,
    build_practice,
    encounter_version,
    error_id_of,
    insurance_coordinator_headers,
    inventory_manager_headers,
    read_clinic,
    read_encounter,
    read_fab_order,
    read_shelf,
    read_supplier,
)
from test_helpers import factories as f

NOT_COVERED = {"covered": False}
HALF_COINSURANCE = {"covered": True, "deductible_remaining_cents": 0, "coinsurance_pct": 0.5}


def _custom_fab_practice(api):
    """A practice whose catalog item is custom fabricated, with the encounter
    documented and no shelf involved at all."""
    practice = build_practice(
        api, product_factory=f.custom_afo_product_payload, with_shelf=False
    )
    encounter_id = practice.documented_encounter()
    return practice, encounter_id


def test_a_freshly_placed_fabrication_order_opens_submitted_with_its_promise_snapshot(api):
    """The order opens in its initial state with no rework rounds, the supplier's
    promise copied onto it, a promised date ten whole days out, and every score
    still unwritten.

    PRD: "On success a `CustomFabOrder` is created against its parent
    `encounter_id` with `status` `SUBMITTED` and `submitted_at` stamped from the
    logical clock, and two supplier values are snapshotted onto it:
    `promised_turnaround_days_snapshot`, copied from the supplier's
    `promised_turnaround_days`, and `promised_delivery_on`, derived as the calendar
    date of `submitted_at` advanced by that many whole days."

    Design: Corner/state_machines/corner_custom_fab_order_initial_state_is_submitted
    """
    practice, encounter_id = _custom_fab_practice(api)
    assert read_encounter(api, encounter_id)["clinical_status"] == "DOCUMENTED"

    order = practice.place_fab_order(encounter_id)

    assert order["status"] == "SUBMITTED"
    assert order["version"] == 1
    assert order["adjustment_rounds"] == 0
    assert_instant_equals(order["submitted_at"], "2026-08-01T00:00:00Z", "submitted_at")
    assert order["promised_turnaround_days_snapshot"] == 10
    assert order["promised_delivery_on"] == "2026-08-11"
    assert order["first_delivered_at"] is None
    assert order["projected_turnaround_score"] is None
    assert_encounter_states(
        read_encounter(api, encounter_id),
        clinical_status="AWAITING_DEVICE",
        financial_status="UNVERIFIED",
    )
    supplier = read_supplier(api, practice.supplier_id)
    assert supplier["accepted_fab_order_count"] == 0
    assert supplier["turnaround_score"] == 100


def test_signing_the_notice_with_the_first_option_puts_the_encounter_on_the_cash_path(api):
    """Signing an outstanding notice with the bill-the-payer option moves the notice
    to signed and the money dimension onto the cash path, while the clinical
    dimension does not move at all.

    PRD: "With `OPTION_1` or `OPTION_2` the financial dimension advances
    `ABN_ISSUED → SELF_PAY` and the encounter is now dispensable on the cash path."

    Design: Corner/state_machines/corner_abn_option_one_signature_advances_encounter_to_self_pay
    """
    practice = build_practice(api, with_shelf=False)
    encounter_id = practice.open_encounter()["id"]
    practice.sign_note(encounter_id)
    verification = practice.verify_coverage(encounter_id, **NOT_COVERED)
    assert verification["covered"] is False
    assert_encounter_states(read_encounter(api, encounter_id), financial_status="NON_COVERED")
    assert encounter_version(api, encounter_id) == 3

    notice = practice.issue_abn(encounter_id)
    assert notice["notice_seq"] == 1
    assert notice["status"] == "ISSUED"
    assert_money_fields(
        notice,
        unit_net_price_cents=11765,
        estimated_subtotal_cents=11765,
        dispensing_fee_cents=2500,
        estimated_cost_cents=14265,
    )

    signed = practice.sign_abn(notice["id"], option="OPTION_1", signed_by="PATIENT")

    assert signed["status"] == "SIGNED"
    assert signed["option_selected"] == "OPTION_1"
    assert signed["signed_by"] == "PATIENT"
    assert_instant_equals(signed["patient_signed_at"], "2026-08-01T00:00:00Z", "patient_signed_at")
    assert signed["version"] == 2
    assert_encounter_states(
        read_encounter(api, encounter_id),
        clinical_status="DOCUMENTED",
        financial_status="SELF_PAY",
    )


def _authorization_under_review(api, quantity=1, requested_units=1):
    """A covered encounter for a product that needs authorization, with the request
    already submitted and awaiting a decision."""
    practice = build_practice(api, product={"requires_prior_auth": True})
    encounter_id = practice.documented_encounter(quantity=quantity)
    verification = practice.verify_coverage(encounter_id, **HALF_COINSURANCE)
    assert verification["same_or_similar_conflict"] is False
    assert verification["prior_delivered_encounter_id"] is None
    request = practice.request_prior_auth(encounter_id, requested_units=requested_units)
    return practice, encounter_id, request


def test_a_pended_decision_is_reopened_by_an_appeal_that_clears_the_decision_stamp(api):
    """A pended decision leaves the money dimension exactly where it was and only
    stamps the decision instant; the appeal then reopens the request, counts a round
    and unstamps that instant.

    PRD: "It returns `status` to `SUBMITTED`, increases `appeal_round` by 1, clears
    `decision_at` back to null, and returns the encounter dimension to
    `AUTH_PENDING` — from `PENDED` that is a no-op on the encounter, and from
    `DENIED` it is the move `AUTH_DENIED → AUTH_PENDING`."

    Design: Corner/state_machines/corner_pended_prior_auth_appeal_increments_round_and_reopens
    """
    practice, encounter_id, request = _authorization_under_review(api)

    assert request["status"] == "SUBMITTED"
    assert request["appeal_round"] == 0
    assert request["version"] == 1
    assert_encounter_states(read_encounter(api, encounter_id), financial_status="AUTH_PENDING")

    pended = practice.decide_prior_auth(
        request["id"],
        decision="PENDED",
        approved_units=None,
        auth_number=None,
        valid_for_days=None,
    )
    assert pended["status"] == "PENDED"
    assert_instant_equals(pended["decision_at"], "2026-08-01T00:00:00Z", "decision_at")
    assert pended["version"] == 2

    appealed = practice.appeal_prior_auth(
        request["id"], appeal_note="additional gait documentation submitted"
    )

    assert appealed["status"] == "SUBMITTED"
    assert appealed["appeal_round"] == 1
    assert appealed["decision_at"] is None
    assert appealed["version"] == 3
    assert appealed["approved_units"] is None
    assert appealed["auth_number"] is None
    assert_encounter_states(read_encounter(api, encounter_id), financial_status="AUTH_PENDING")


def test_dispensing_out_of_the_documented_state_is_diagnosed_clinically(api):
    """A dispense that skips both the reservation and the fitting is refused on the
    clinical dimension even though the money dimension is also in the wrong place,
    and the encounter is left untouched.

    PRD: "The fourth band is state, in the order `ERR_INVALID_CLINICAL_STATE`,
    `ERR_INVALID_FINANCIAL_STATE`, `ERR_INVALID_PRIOR_AUTH_STATE`,
    `ERR_INVALID_ABN_STATE`, `ERR_INVALID_FAB_ORDER_STATE`,
    `ERR_INVALID_RETURN_STATE` — so an encounter in the wrong clinical state is
    always diagnosed as such even when its financial state is also wrong."

    Design: Corner/state_machines/corner_dispense_from_documented_encounter_rejected
    """
    practice = build_practice(api)
    encounter_id = practice.documented_encounter()
    assert_encounter_states(
        read_encounter(api, encounter_id),
        clinical_status="DOCUMENTED",
        financial_status="UNVERIFIED",
    )

    response = api.dispense(encounter_id, f.dispense_payload(), practice.fitter_headers)

    assert_error(response, ApiErrors.INVALID_CLINICAL_STATE, 409)
    assert error_id_of(response) != ApiErrors.INVALID_FINANCIAL_STATE
    assert error_id_of(response) != ApiErrors.COVERAGE_VERIFICATION_MISSING
    encounter = read_encounter(api, encounter_id)
    assert encounter["clinical_status"] == "DOCUMENTED"
    assert encounter["delivered_at"] is None
    assert encounter["version"] == 2


def test_a_second_decision_on_an_approved_request_is_refused_and_overwrites_nothing(api):
    """Replaying an approval on an already-decided request is refused, and the
    approved units, the authorization number, the expiry and the version all stand
    exactly as the first decision left them.

    PRD: "A decision is only accepted while the request's `status` is `SUBMITTED` or
    `PENDED`; otherwise it is refused with `ERR_INVALID_PRIOR_AUTH_STATE` and HTTP
    409."

    Design: Corner/state_machines/corner_second_prior_auth_decision_after_approval_rejected
    """
    practice, encounter_id, request = _authorization_under_review(
        api, quantity=2, requested_units=2
    )

    approved = practice.decide_prior_auth(
        request["id"],
        decision="APPROVED",
        approved_units=2,
        auth_number="AUTH-77001",
        valid_for_days=30,
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_units"] == 2
    assert approved["auth_number"] == "AUTH-77001"
    assert_instant_equals(approved["decision_at"], "2026-08-01T00:00:00Z", "decision_at")
    assert_instant_equals(approved["expires_at"], "2026-08-31T00:00:00Z", "expires_at")
    assert approved["version"] == 2

    response = api.decide_prior_auth(
        request["id"],
        f.prior_auth_decision_payload(
            decision="APPROVED", approved_units=1, auth_number="AUTH-99002", valid_for_days=90
        ),
        insurance_coordinator_headers(),
    )

    assert_error(response, ApiErrors.INVALID_PRIOR_AUTH_STATE, 409)
    rows, _ = assert_list_meta(
        api.list_prior_auth_requests(encounter_id, insurance_coordinator_headers()),
        expected_total=1,
    )
    unchanged = rows[0]
    assert unchanged["approved_units"] == 2
    assert unchanged["auth_number"] == "AUTH-77001"
    assert_instant_equals(unchanged["expires_at"], "2026-08-31T00:00:00Z", "expires_at")
    assert unchanged["version"] == 2
    assert_encounter_states(read_encounter(api, encounter_id), financial_status="AUTH_APPROVED")


def test_refusing_the_device_on_the_notice_voids_the_encounter_and_frees_the_shelf(api):
    """One refusal signature applies four effects at once: the notice is signed, the
    clinical dimension jumps to voided, the money dimension is written off with both
    figures at zero, and the held unit goes back to being available without the
    physical shelf moving.

    PRD: "With `OPTION_3` the financial dimension advances `ABN_ISSUED →
    WRITTEN_OFF`, and the clinical dimension cascades to `VOIDED` from wherever it
    stood — `DRAFT → VOIDED`, `DOCUMENTED → VOIDED` or `RESERVED → VOIDED` — with
    both `patient_responsibility_cents` and `billable_amount_cents` set to 0 and the
    encounter's `version` advanced by 1."

    Design: Corner/state_machines/corner_abn_option_three_signature_voids_encounter_and_releases_reservation
    """
    practice = build_practice(api, received_qty=6)
    assert_shelf(practice.par_level, on_hand_qty=6, stock_posture="OK", version=2)
    encounter_id = practice.open_encounter()["id"]
    practice.sign_note(encounter_id)
    practice.verify_coverage(encounter_id, **NOT_COVERED)
    practice.reserve(encounter_id)
    assert_encounter_states(
        read_encounter(api, encounter_id),
        clinical_status="RESERVED",
        financial_status="NON_COVERED",
    )
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=6,
        reserved_qty=1,
        available_qty=5,
        stock_posture="OK",
        version=3,
    )

    notice = practice.issue_abn(encounter_id)
    assert notice["status"] == "ISSUED"
    assert notice["estimated_cost_cents"] == 14265

    signed = practice.sign_abn(notice["id"], option="OPTION_3")

    assert signed["status"] == "SIGNED"
    assert signed["option_selected"] == "OPTION_3"
    voided = read_encounter(api, encounter_id)
    assert_encounter_states(voided, clinical_status="VOIDED", financial_status="WRITTEN_OFF")
    assert_responsibility(voided, patient_responsibility_cents=0, billable_amount_cents=0)
    assert_shelf(
        read_shelf(api, practice.par_level_id),
        on_hand_qty=6,
        reserved_qty=0,
        available_qty=6,
        stock_posture="OK",
        version=4,
    )
    assert_clinic_posture(
        read_clinic(api, practice.clinic_id),
        dispensing_status="ACTIVE",
        stockout_par_level_count=0,
    )


def test_cancelling_a_held_fabrication_order_walks_the_encounter_back(api):
    """A quality hold parks the order and holds the encounter; cancelling the order
    then reverses both, and because only accepted orders count, the supplier's
    reputation is untouched throughout.

    PRD: "`CANCEL` moves `SUPPLIER_HOLD → CANCELLED`, abandoning an order stuck
    behind a supplier's quality problem; it also reverts the waiting encounter's
    clinical dimension `AWAITING_DEVICE → DOCUMENTED` and clears its
    `compliance_hold`, so the fitter can re-route the encounter to a different
    supplier, and it advances both the order's and the encounter's `version` by 1."

    Design: Corner/state_machines/corner_supplier_hold_cancellation_restores_encounter_to_documented
    """
    practice, encounter_id = _custom_fab_practice(api)
    order = practice.place_fab_order(encounter_id)
    assert order["status"] == "SUBMITTED"

    held_supplier = attest_standards(api, practice.supplier_id, attested=True, quality_hold=True)
    assert held_supplier["quality_hold"] is True
    assert read_fab_order(api, order["id"])["status"] == "SUPPLIER_HOLD"
    held_encounter = read_encounter(api, encounter_id)
    assert_compliance_hold(held_encounter, True, "SUPPLIER_QUALITY_HOLD")
    assert held_encounter["clinical_status"] == "AWAITING_DEVICE"

    cancelled = practice.fitting_check(
        order["id"], "CANCEL", note="supplier on quality hold; patient re-routed"
    )

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["accepted_at"] is None
    assert cancelled["final_turnaround_score"] is None
    restored = read_encounter(api, encounter_id)
    assert restored["clinical_status"] == "DOCUMENTED"
    assert_compliance_hold(restored, False, None)
    supplier = read_supplier(api, practice.supplier_id)
    assert supplier["turnaround_score"] == 100
    assert supplier["accepted_fab_order_count"] == 0


def test_a_returned_encounter_refuses_every_replay_with_its_own_diagnosis(api):
    """Once the device is back on the shelf, four replays each get the diagnosis
    that belongs to them — a second inspection, a second return request, a fresh
    note and a second dispense — and none of them moves the frozen money.

    PRD: "Second, on a return request the clinical-state check is evaluated only
    when the encounter has no return yet, so a second return request against an
    encounter that already has one is diagnosed as `ERR_RETURN_ALREADY_EXISTS`
    rather than as an invalid clinical state, even though the post-return clinical
    states are not declared origins of the return transition."

    Design: Corner/state_machines/corner_returned_encounter_and_inspected_return_are_locked_down_rejected
    """
    practice = build_practice(
        api, received_qty=6, fitter={"privilege_scope": "OFF_SHELF_ONLY"}
    )
    encounter_id = practice.reserved_encounter(coverage=HALF_COINSURANCE)
    fitting = practice.fit(
        encounter_id, start_at="2026-08-01T09:00:00Z", end_at="2026-08-01T09:45:00Z"
    )
    assert fitting["fitting_minutes"] == 45
    delivered = practice.dispense(encounter_id)
    assert_responsibility(
        delivered,
        patient_responsibility_cents=10300,
        billable_amount_cents=10300,
        responsibility_variant="INSURANCE_ASSIGNED",
    )
    product_return = practice.open_return(encounter_id, reason="POOR_FIT")
    assert product_return["status"] == "REQUESTED"
    assert product_return["quantity_returned"] == 1
    assert product_return["days_since_delivery"] == 0
    inspected = practice.inspect_return(product_return["id"], condition="SELLABLE")
    assert inspected["status"] == "RESTOCKED"
    assert_money_fields(inspected, refund_cents=9348, restock_fee_cents=952)

    assert_error(
        api.inspect_return(
            product_return["id"], f.inspection_payload("DAMAGED"), inventory_manager_headers()
        ),
        ApiErrors.INVALID_RETURN_STATE,
        409,
    )
    assert_error(
        api.create_return(encounter_id, f.return_payload("DEFECT"), practice.fitter_headers),
        ApiErrors.RETURN_ALREADY_EXISTS,
        409,
    )
    assert_error(
        api.sign_medical_necessity_note(
            encounter_id,
            f.medical_necessity_note_payload(mn_diagnosis_code="M54.51"),
            practice.ordering_physician_headers,
        ),
        ApiErrors.INVALID_CLINICAL_STATE,
        409,
    )
    dispense_again = api.dispense(encounter_id, f.dispense_payload(), practice.fitter_headers)
    assert_error(dispense_again, ApiErrors.INVALID_CLINICAL_STATE, 409)
    assert error_id_of(dispense_again) != ApiErrors.INVALID_FINANCIAL_STATE

    frozen_return = api.list_returns(encounter_id, inventory_manager_headers())
    rows, _ = assert_list_meta(frozen_return, expected_total=1)
    assert rows[0]["condition"] == "SELLABLE"
    assert rows[0]["refund_cents"] == 9348
    assert rows[0]["status"] == "RESTOCKED"
    frozen_encounter = read_encounter(api, encounter_id)
    assert_encounter_states(
        frozen_encounter, clinical_status="RETURNED", financial_status="REFUNDED"
    )
    assert_responsibility(
        frozen_encounter, patient_responsibility_cents=10300, billable_amount_cents=0
    )
    assert_shelf(read_shelf(api, practice.par_level_id), on_hand_qty=6, stock_posture="OK")
