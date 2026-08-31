"""Damage at the gate: the liability waterfall, the chargeback it raises, and the
adjudication that settles or reverses it."""


from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    find_chargeback,
    make_approver_headers,
    make_customer_headers,
    make_inspector_headers,
    open_assessment,
    read_agreement,
    read_agreement_unit,
    read_branch,
    read_chargeback,
    read_customer,
    read_damage_assessment,
    read_trailer,
    setup_agreement_active,
    setup_approved_chargeback,
    setup_draft_assessment,
    setup_pending_chargeback,
    setup_reference_data,
    setup_returned_unit,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]

_MAJOR_CLAIM = [{"severity": "MAJOR", "quantity": 5, "unit_cost_cents": 437500,
                 "description": "collision damage to five bays"}]
_TWENTY_FIVE_POINT_ITEMS = [
    {"severity": "MODERATE", "quantity": 2, "unit_cost_cents": 30000,
     "description": "roof panel"},
    {"severity": "MINOR", "quantity": 3, "unit_cost_cents": 10000,
     "description": "scuff"},
]


def test_the_insured_slice_is_capped_at_the_pinned_policy_limit(api):
    """PRD §3.8: "The `insured_portion_cents` is then the assessed amount less the
    deductible, floored at zero so a small claim inside the deductible yields
    nothing from the carrier, and then capped at the applicable limit."
    PRD §3.8: "The `customer_liable_cents` is the assessed amount less the insured
    portion, and `admin_fee_cents` is eight percent of that customer-liable figure,
    rounded half-up to whole cents."

    Design: Corner/calculations/damage_insured_portion_capped_at_certificate_limit
    """
    scn = setup_pending_chargeback(line_items=_MAJOR_CLAIM)

    assessment = scn["assessment"]
    assert assessment["assessed_amount_cents"] == 3_500_000
    assert assessment["insured_portion_cents"] == 3_000_000, (
        "the carrier stops at its limit, not at the 3350000 above the deductible"
    )
    assert assessment["customer_liable_cents"] == 500_000
    assert assessment["admin_fee_cents"] == 40_000
    assert assessment["damage_points"] == 75

    assert scn["chargeback_amount"] == 540_000
    assert read_trailer(scn["trailer_id"])["service_status"] == "OOS_DAMAGE"


def test_a_revoked_certificate_collapses_the_applicable_limit_to_zero(api):
    """PRD §3.8: "The applicable limit is the `physical_damage_limit_cents` of the
    certificate pinned in the owning contract's `insurance_certificate_id`, but
    only when such a certificate exists and its `status` is `ACTIVE` at the moment
    of submission; when the contract pinned no certificate, or when the pinned
    certificate is no longer `ACTIVE`, the applicable limit is 0 and the lessee
    carries the entire assessed amount."

    Design: Corner/calculations/damage_with_revoked_certificate_leaves_customer_liable_for_full_assessment
    """
    scn = setup_returned_unit()
    pinned = read_agreement(scn["agreement_id"])["insurance_certificate_id"]
    revoked = validate_success(
        api.revoke_insurance_certificate(
            pinned, {"reason": "carrier cancelled the policy for non-payment"}, ADMIN
        )
    )
    assert revoked["status"] == "REVOKED"

    assessment = open_assessment(scn, line_items=_MAJOR_CLAIM)
    submitted = submit_assessment(assessment["id"])

    assert submitted["assessed_amount_cents"] == 3_500_000
    assert submitted["insured_portion_cents"] == 0
    assert submitted["customer_liable_cents"] == 3_500_000
    assert submitted["admin_fee_cents"] == 280_000

    chargeback = find_chargeback(assessment["id"])
    assert chargeback["amount_cents"] == 3_780_000
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 3_780_000


def test_a_re_inspection_voids_the_predecessors_chargeback_and_its_points(api):
    """PRD §3.8: "Finally, when the submission carried a `supersedes_assessment_id`,
    the superseded predecessor moves `SUBMITTED → SUPERSEDED`, its own chargeback
    moves `PENDING → VOIDED` or `DISPUTED → VOIDED` depending on where it stood,
    the lessee's `outstanding_chargeback_cents` drops by that voided chargeback's
    `amount_cents`, and the trailer's live damage-point sum is re-derived so that
    the predecessor's points drop out of it."

    Design: Corner/state_machines/superseding_assessment_voids_prior_chargeback_and_rolls_back_points
    """
    scn = setup_pending_chargeback()
    assert scn["chargeback_amount"] == 108000

    replacement = open_assessment(
        scn,
        line_items=[{"severity": "MINOR", "quantity": 3, "unit_cost_cents": 25000,
                     "description": "re-inspection: floor gouges only"}],
        inspector_user_id="insp-2",
        supersedes_assessment_id=scn["assessment_id"],
    )
    submitted = submit_assessment(replacement["id"], inspector_user_id="insp-2")
    assert submitted["damage_points"] == 9

    assert read_damage_assessment(scn["assessment_id"])["status"] == "SUPERSEDED"
    assert read_chargeback(scn["chargeback_id"])["status"] == "VOIDED"
    assert read_damage_assessment(replacement["id"])["status"] == "SUBMITTED"
    assert read_damage_assessment(replacement["id"])["supersedes_assessment_id"] == \
        scn["assessment_id"]

    successor = find_chargeback(replacement["id"])
    assert successor["amount_cents"] == 81000
    assert successor["status"] == "PENDING"

    assert read_trailer(scn["trailer_id"])["damage_points"] == 9
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 81000


def test_opening_an_assessment_with_a_stale_unit_version_is_rejected(api):
    """PRD §2.7: "Opening a damage assessment against a returned contract unit line
    requires `expected_agreement_unit_version` in the request body, carrying the
    client's last observed `version` of the target `AgreementUnit`."
    PRD §3.8: "The new assessment is written in status `DRAFT`, with `trailer_id`
    copied from the assessed line, with `agreement_unit_id` recording the line it
    stands on, and with `assessor_user_id` stamped from the authoring inspector's
    `X-User-ID`; the assessed line's own `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_unit_version_on_damage_assessment_create_conflicts
    """
    scn = setup_draft_assessment()
    stale_version = scn["unit_version"]

    response = api.create_damage_assessment(
        scn["unit_id"],
        {"line_items": [{"severity": "MINOR", "quantity": 1, "unit_cost_cents": 5000,
                         "description": "second inspector, stale view"}],
         "expected_agreement_unit_version": stale_version},
        make_inspector_headers("insp-2"),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    fresh_version = read_agreement_unit(scn["unit_id"])["version"]
    assert fresh_version == stale_version + 1

    second = validate_success(
        api.create_damage_assessment(
            scn["unit_id"],
            {"line_items": [{"severity": "MINOR", "quantity": 1,
                             "unit_cost_cents": 5000,
                             "description": "second inspector, fresh view"}],
             "expected_agreement_unit_version": fresh_version},
            make_inspector_headers("insp-2"),
        ),
        201,
    )
    assert second["status"] == "DRAFT"
    assert second["assessor_user_id"] == "insp-2"

    rows, _ = validate_paginated(
        api.list_damage_assessments(ADMIN, params={"agreement_unit_id": scn["unit_id"]})
    )
    assert len(rows) == 2


def test_an_assessment_cannot_be_submitted_while_the_unit_is_still_out(api):
    """PRD §3.8: "The contract unit line being assessed must have a `status` of
    `RETURNED` or `SETTLED`, since a unit still on the road cannot be inspected at
    the gate, and any other line status is rejected with `ERR_UNIT_NOT_RETURNED`."

    Design: Corner/errors/submit_assessment_on_a_unit_still_out_reports_unit_not_returned
    """
    scn = setup_agreement_active()
    unit = read_agreement_unit(scn["unit_id"])
    assert unit["status"] == "OUT"

    assessment = open_assessment(
        scn,
        line_items=[{"severity": "MINOR", "quantity": 1, "unit_cost_cents": 5000,
                     "description": "roadside note"}],
        unit_version=unit["version"],
    )

    response = api.submit_damage_assessment(
        assessment["id"], make_inspector_headers("insp-1")
    )
    validate_error(response, ApiErrorId.ERR_UNIT_NOT_RETURNED.value)

    assert read_damage_assessment(assessment["id"])["status"] == "DRAFT"
    rows, _ = validate_paginated(
        api.list_chargebacks(ADMIN, params={"damage_assessment_id": assessment["id"]})
    )
    assert rows == []
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 0


def test_submitting_the_same_assessment_twice_is_rejected(api):
    """PRD §3.8: "The assessment must be in `DRAFT`, and any other status is
    rejected with `ERR_ASSESSMENT_NOT_DRAFT`."
    PRD §3.8: "Submission then raises a **chargeback** in status `PENDING` whose
    `amount_cents` is the `customer_liable_cents` plus the `admin_fee_cents`,
    frozen at creation and never recomputed thereafter."

    Design: Corner/errors/submit_assessment_twice_reports_assessment_not_draft
    """
    scn = setup_pending_chargeback()

    response = api.submit_damage_assessment(
        scn["assessment_id"], make_inspector_headers("insp-1")
    )
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_NOT_DRAFT.value)

    assert read_damage_assessment(scn["assessment_id"])["status"] == "SUBMITTED"
    rows, _ = validate_paginated(
        api.list_chargebacks(ADMIN,
                             params={"damage_assessment_id": scn["assessment_id"]})
    )
    assert len(rows) == 1, "a rejected re-submission mints no second chargeback"
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 108000


def test_superseding_a_predecessor_that_is_still_draft_is_rejected(api):
    """PRD §3.8: "And when `supersedes_assessment_id` is set, the assessment it
    names must itself be in status `SUBMITTED`; naming an assessment in any other
    status is rejected with `ERR_ASSESSMENT_SUPERSEDED`."

    Design: Corner/errors/submit_assessment_superseding_a_draft_predecessor_reports_assessment_superseded
    """
    scn = setup_draft_assessment()

    replacement = open_assessment(
        scn,
        line_items=[{"severity": "MINOR", "quantity": 1, "unit_cost_cents": 5000,
                     "description": "re-inspection"}],
        inspector_user_id="insp-2",
        supersedes_assessment_id=scn["assessment_id"],
    )

    response = api.submit_damage_assessment(
        replacement["id"], make_inspector_headers("insp-2")
    )
    validate_error(response, ApiErrorId.ERR_ASSESSMENT_SUPERSEDED.value)

    assert read_damage_assessment(scn["assessment_id"])["status"] == "DRAFT"
    assert read_damage_assessment(replacement["id"])["status"] == "DRAFT"
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 0


def test_approving_a_disputed_chargeback_is_rejected(api):
    """PRD §3.8: "Approving a chargeback is a `ChargebackApprover` action that
    moves it `PENDING → APPROVED`; a chargeback in any other status is rejected
    with `ERR_CHARGEBACK_NOT_PENDING`, and an approver whose `X-User-ID` equals the
    `assessor_user_id` of the assessment behind it is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/approve_a_disputed_chargeback_reports_not_pending
    """
    scn = setup_pending_chargeback()
    validate_success(
        api.dispute_chargeback(
            scn["chargeback_id"], {"dispute_reason": "pre-existing damage"},
            make_customer_headers(scn["customer_id"]),
        )
    )

    response = api.approve_chargeback(scn["chargeback_id"], make_approver_headers("appr-1"))
    validate_error(response, ApiErrorId.ERR_CHARGEBACK_NOT_PENDING.value)

    stored = read_chargeback(scn["chargeback_id"])
    assert stored["status"] == "DISPUTED"
    assert stored.get("approver_user_id") is None


def test_reopening_a_chargeback_that_is_already_pending_is_rejected(api):
    """PRD §3.8: "A `ChargebackApprover` may push a disputed item back into the
    queue, moving it `DISPUTED → PENDING` and clearing `dispute_reason`, after
    which it is approvable or waivable again; a chargeback whose status is not
    `DISPUTED` is rejected with `ERR_CHARGEBACK_NOT_DISPUTED`, and the `version`
    increments by 1."

    Design: Corner/errors/reopen_a_pending_chargeback_reports_not_disputed
    """
    scn = setup_pending_chargeback()

    response = api.reopen_chargeback(scn["chargeback_id"], make_approver_headers("appr-1"))
    validate_error(response, ApiErrorId.ERR_CHARGEBACK_NOT_DISPUTED.value)

    assert read_chargeback(scn["chargeback_id"])["status"] == "PENDING"


def test_paying_a_chargeback_that_is_not_approved_is_rejected(api):
    """PRD §3.8: "A `FleetAdmin` records payment against an approved chargeback,
    moving it `APPROVED → SETTLED`; a chargeback in any other status is rejected
    with `ERR_CHARGEBACK_NOT_APPROVED`."
    PRD §3.8: "Settlement records `paid_amount_cents` — null on any chargeback that
    has not been paid — drops the lessee's `outstanding_chargeback_cents` by the
    chargeback's `amount_cents`, and increments its `version` by 1."

    Design: Corner/errors/record_payment_on_a_pending_chargeback_reports_not_approved
    """
    scn = setup_pending_chargeback()

    response = api.record_chargeback_payment(
        scn["chargeback_id"], {"paid_amount_cents": 108000}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_CHARGEBACK_NOT_APPROVED.value)

    stored = read_chargeback(scn["chargeback_id"])
    assert stored["status"] == "PENDING"
    assert stored.get("paid_amount_cents") is None
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 108000


def test_waiving_an_approved_chargeback_is_rejected(api):
    """PRD §3.8: "A `ChargebackApprover` may waive from either `PENDING` or
    `DISPUTED`; a chargeback already in `APPROVED`, `WAIVED`, `SETTLED` or `VOIDED`
    is rejected with `ERR_CHARGEBACK_TERMINAL`, and the same segregation-of-duties
    comparison applies, rejecting with `ERR_SEGREGATION_OF_DUTIES` when the
    approver's `X-User-ID` equals the assessment's `assessor_user_id`."

    Design: Corner/errors/waive_an_approved_chargeback_reports_chargeback_terminal
    """
    scn = setup_approved_chargeback()

    response = api.waive_chargeback(
        scn["chargeback_id"], {"waiver_reason": "goodwill"},
        make_approver_headers("appr-2"),
    )
    validate_error(response, ApiErrorId.ERR_CHARGEBACK_TERMINAL.value)

    assert read_chargeback(scn["chargeback_id"])["status"] == "APPROVED"
    assert read_damage_assessment(scn["assessment_id"])["status"] == "APPROVED"
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 108000


def test_full_payment_settles_the_chargeback_and_clears_the_balance(api):
    """PRD §3.8: "Payment must be in full: the supplied `paid_amount_cents` must
    equal the chargeback's `amount_cents` exactly, and any other figure — short or
    over — is rejected with `ERR_INVALID_REQUEST`."
    PRD §3.8: "Settlement records `paid_amount_cents` — null on any chargeback that
    has not been paid — drops the lessee's `outstanding_chargeback_cents` by the
    chargeback's `amount_cents`, and increments its `version` by 1."

    Design: Corner/endpoints/record_payment_settles_approved_chargeback_and_clears_balance
    """
    scn = setup_approved_chargeback()
    assert scn["chargeback_amount"] == 108000

    chargeback = validate_success(
        api.record_chargeback_payment(
            scn["chargeback_id"], {"paid_amount_cents": 108000}, ADMIN
        )
    )
    assert chargeback["status"] == "SETTLED"
    assert chargeback["paid_amount_cents"] == 108000

    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 0
    assert read_damage_assessment(scn["assessment_id"])["status"] == "APPROVED"
    assert read_trailer(scn["trailer_id"])["damage_points"] == 16, (
        "an approved assessment keeps its points counted against the unit"
    )


def test_a_chargeback_can_cycle_pending_disputed_pending_before_approval(api):
    """PRD §3.8: "The lessee may dispute a chargeback, moving it `PENDING →
    DISPUTED` and recording the supplied `dispute_reason`."
    PRD §3.8: "A `ChargebackApprover` may push a disputed item back into the queue,
    moving it `DISPUTED → PENDING` and clearing `dispute_reason`, after which it is
    approvable or waivable again; a chargeback whose status is not `DISPUTED` is
    rejected with `ERR_CHARGEBACK_NOT_DISPUTED`, and the `version` increments by 1."
    PRD §3.8: "This `PENDING → DISPUTED → PENDING` cycle may repeat."

    Design: Difficulty/non_linear_state_machine/chargeback_cycles_pending_disputed_pending_before_approval
    """
    scn = setup_pending_chargeback()
    assert scn["chargeback_amount"] == 108000

    disputed = validate_success(
        api.dispute_chargeback(
            scn["chargeback_id"],
            {"dispute_reason": "gate photos disagree with the shop write-up"},
            make_customer_headers(scn["customer_id"]),
        )
    )
    assert disputed["status"] == "DISPUTED"

    reopened = validate_success(
        api.reopen_chargeback(scn["chargeback_id"], make_approver_headers("appr-1"))
    )
    assert reopened["status"] == "PENDING"

    approved = validate_success(
        api.approve_chargeback(scn["chargeback_id"], make_approver_headers("appr-1"))
    )
    assert approved["status"] == "APPROVED"
    assert approved["version"] == 4, (
        "creation, dispute, reopen and approval are four writes of the same row"
    )


def test_the_reopen_and_approve_cycle_leaves_the_money_where_it_stood(api):
    """PRD §3.8: "Approval records `approver_user_id` — which is null for as long
    as a chargeback sits in `PENDING` or `DISPUTED`, and is written only by an
    approval or a waiver — moves the linked assessment `SUBMITTED → APPROVED`,
    leaves the amount counted in `outstanding_chargeback_cents`, leaves the
    assessment's damage points counted against the trailer, and increments the
    chargeback's `version` by 1."
    PRD §3.8: "Disputing changes no money: the amount stays counted in
    `outstanding_chargeback_cents`."

    Design: Difficulty/non_linear_state_machine/chargeback_cycles_pending_disputed_pending_before_approval
    """
    scn = setup_pending_chargeback()

    validate_success(
        api.dispute_chargeback(
            scn["chargeback_id"],
            {"dispute_reason": "gate photos disagree with the shop write-up"},
            make_customer_headers(scn["customer_id"]),
        )
    )
    validate_success(
        api.reopen_chargeback(scn["chargeback_id"], make_approver_headers("appr-1"))
    )
    validate_success(
        api.approve_chargeback(scn["chargeback_id"], make_approver_headers("appr-1"))
    )

    stored = read_chargeback(scn["chargeback_id"])
    assert stored.get("dispute_reason") is None, "reopening cleared the dispute reason"
    assert stored["approver_user_id"] == "appr-1"
    assert read_damage_assessment(scn["assessment_id"])["status"] == "APPROVED"
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 108000


def _approved_move_standing_on_a_unit_about_to_go_out_of_service():
    """A returned idle unit with an approved repositioning move already booked on
    it, and a draft assessment worth exactly the damage ceiling."""
    from test_helpers import add_east_branch, request_relocation, approve_relocation
    ctx = setup_reference_data()
    add_east_branch(ctx)
    scn = setup_returned_unit(ctx=ctx)

    order = request_relocation(scn, destination_branch_id=scn["east_branch_id"])
    scn["order"] = order
    scn["order_id"] = order["id"]
    scn["order_estimate"] = order["estimated_cost_cents"]
    approve_relocation(scn)

    assessment = open_assessment(scn, line_items=_TWENTY_FIVE_POINT_ITEMS)
    scn["assessment"] = assessment
    scn["assessment_id"] = assessment["id"]
    return scn


def test_submitting_an_assessment_prices_the_damage_and_raises_the_chargeback(api):
    """PRD §3.8: "First the gross value: for each line item the server multiplies
    the item's `quantity` by its `unit_cost_cents` by the severity multiplier —
    1.00 for `MINOR`, 1.25 for `MODERATE`, 1.60 for `MAJOR` — and rounds that
    per-item product half-up to whole cents; `assessed_amount_cents` is the sum of
    those rounded per-item figures."
    PRD §3.8: "Submission then raises a **chargeback** in status `PENDING` whose
    `amount_cents` is the `customer_liable_cents` plus the `admin_fee_cents`,
    frozen at creation and never recomputed thereafter."

    Design: Difficulty/transitive_cascade/assessment_submit_cascade_depth4_cancels_approved_relocation
    """
    scn = _approved_move_standing_on_a_unit_about_to_go_out_of_service()
    assert scn["order_estimate"] == 118700

    submitted = submit_assessment(scn["assessment_id"])
    assert submitted["damage_points"] == 25
    assert submitted["customer_liable_cents"] == 105000
    assert submitted["admin_fee_cents"] == 8400

    chargeback = find_chargeback(scn["assessment_id"])
    assert chargeback["amount_cents"] == 113400
    assert chargeback["status"] == "PENDING"
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 113400


def test_crossing_the_damage_ceiling_cancels_the_approved_repositioning_move(api):
    """PRD §3.8: "Every relocation order standing on that trailer whose status is
    `REQUESTED` or `APPROVED` is cancelled, with `cancel_reason` recorded as
    `TRAILER_OUT_OF_SERVICE`; an order cancelled out of `APPROVED` additionally
    releases the inbound capacity window it was holding at its destination yard,
    while an order cancelled out of `REQUESTED` was never holding one."
    PRD §3.8: "If the sum has reached 25 points the unit moves `SERVICEABLE →
    OOS_DAMAGE`, and two cascades fire from that single move."

    Design: Difficulty/transitive_cascade/assessment_submit_cascade_depth4_cancels_approved_relocation
    """
    scn = _approved_move_standing_on_a_unit_about_to_go_out_of_service()

    submit_assessment(scn["assessment_id"])

    trailer = read_trailer(scn["trailer_id"])
    assert trailer["damage_points"] == 25
    assert trailer["service_status"] == "OOS_DAMAGE"
    assert trailer["availability_status"] == "AVAILABLE", (
        "the commercial dimension is untouched by the shop dimension"
    )

    order = validate_success(api.get_relocation_order(scn["order_id"], ADMIN))
    assert order["status"] == "CANCELLED"
    assert order["cancel_reason"] == "TRAILER_OUT_OF_SERVICE"
    assert order.get("actual_cost_cents") is None

    branch = read_branch(scn["branch_id"])
    assert branch["serviceable_available_count"] == 0
    assert branch["on_hand_count"] == 1


def test_waiving_a_chargeback_returns_the_balance_to_where_it_started(api):
    """PRD §2.10: "Submitting a damage assessment adds exactly the created
    chargeback's `amount_cents` to that balance; waiving that chargeback subtracts
    exactly the same amount and additionally rolls the trailer's damage points back
    by the assessment's own point total."
    PRD §2.10: "After a forward action and its compensating action the balance
    returns to its pre-submission value with zero drift."

    Design: Difficulty/compensating_invariant/chargeback_waive_conserves_customer_outstanding_balance_and_damage_points
    """
    scn = setup_returned_unit()
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 0

    assessment = open_assessment(scn, line_items=_TWENTY_FIVE_POINT_ITEMS)
    submit_assessment(assessment["id"])
    chargeback = find_chargeback(assessment["id"])
    assert chargeback["amount_cents"] == 113400
    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 113400

    waived = validate_success(
        api.waive_chargeback(
            chargeback["id"],
            {"waiver_reason": "pre-existing damage documented at checkout"},
            make_approver_headers("appr-1"),
        )
    )
    assert waived["status"] == "WAIVED"
    assert waived["approver_user_id"] == "appr-1"

    assert read_customer(scn["customer_id"])["outstanding_chargeback_cents"] == 0
    assert read_damage_assessment(assessment["id"])["status"] == "REJECTED"


def test_waiving_a_chargeback_rolls_the_damage_points_back_off_the_unit(api):
    """PRD §3.8: "A waiver records `approver_user_id` and the supplied
    `waiver_reason`, moves the linked assessment `SUBMITTED → REJECTED`, drops the
    lessee's `outstanding_chargeback_cents` by exactly the chargeback's
    `amount_cents`, and re-derives the trailer's live damage points and
    `service_status` — so a unit taken out of service by that assessment moves
    `OOS_DAMAGE → SERVICEABLE` once the remaining points fall below 25 and neither
    an inspection problem nor a maintenance-mileage problem stands in the way."

    Design: Difficulty/compensating_invariant/chargeback_waive_conserves_customer_outstanding_balance_and_damage_points
    """
    scn = setup_returned_unit()
    assert read_trailer(scn["trailer_id"])["damage_points"] == 0

    assessment = open_assessment(scn, line_items=_TWENTY_FIVE_POINT_ITEMS)
    submit_assessment(assessment["id"])
    chargeback = find_chargeback(assessment["id"])

    during = read_trailer(scn["trailer_id"])
    assert during["damage_points"] == 25
    assert during["service_status"] == "OOS_DAMAGE"

    validate_success(
        api.waive_chargeback(
            chargeback["id"],
            {"waiver_reason": "pre-existing damage documented at checkout"},
            make_approver_headers("appr-1"),
        )
    )

    after = read_trailer(scn["trailer_id"])
    assert after["damage_points"] == 0, "exactly the assessment's points come back off"
    assert after["service_status"] == "SERVICEABLE"
