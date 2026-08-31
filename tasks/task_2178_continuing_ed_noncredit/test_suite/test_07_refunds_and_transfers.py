"""Unwinding a registration: refund valuation, transfer settlement and program revenue."""

from test_helpers import (
    ADMIN,
    COURSE_EXT_050,
    REGISTRAR,
    ApiErrorId,
    add_paid_registration,
    decide_request,
    make_learner_headers,
    new_learner,
    open_refund_request,
    read_offering,
    read_registration,
    read_request,
    register_learner,
    reset_clock,
    set_clock,
    setup_open_offering,
    setup_single_seat_offering_with_waitlist,
    setup_transfer_scene,
    validate_error,
    validate_paginated,
    validate_success,
)


def _paid_seat_at(clock: str, tuition_cents: int = 60000, session_count: int = 10):
    """One ENROLLED x PAID learner on an OPEN section, with the clock parked at `clock`."""
    scene = setup_open_offering(
        offering_overrides={"tuition_cents": tuition_cents, "session_count": session_count}
    )
    seat = add_paid_registration(scene["offering_id"], learner_index=0)
    set_clock(clock)
    scene["seat"] = seat
    return scene


class TestRefundBasisVariants:
    """The two refund bases value the very same registration differently."""

    def test_policy_schedule_values_one_day_of_notice_at_fifty_percent(self, api):
        """PRD 3.9: "The valuation itself starts from a **refundable base** that
        deliberately excludes the fee: the registration's `amount_paid_cents` less its
        `processing_fee_cents`."
        PRD 3.9: "Under the default `POLICY_SCHEDULE` basis, the refundable base is
        multiplied by a percentage read off the notice period alone, with attendance
        ignored entirely: 100 percent when `days_before_start` is 14 or more, 75 percent
        when it is 7 or more but under 14, 50 percent when it is 1 or more but under 7,
        and 0 percent otherwise — which includes the day the section starts and every
        day after."
        PRD 3.9: "`days_before_start` is the number of whole days between the logical
        clock and the source section's `start_date`, obtained by dividing the interval
        by 86,400 seconds and taking the floor; it may be negative when the section has
        already begun."

        Design: Difficulty/dual_variant_calc/refund_policy_schedule_vs_pro_rata_diverge_on_one_registration
        """
        reset_clock()
        scene = _paid_seat_at("2026-09-14T00:00:00Z")
        registration = read_registration(scene["seat"]["registration_id"])
        assert registration["total_due_cents"] == 62400
        assert registration["processing_fee_cents"] == 2400

        data = validate_success(
            api.create_refund_transfer_request(
                {
                    "registration_id": scene["seat"]["registration_id"],
                    "request_type": "REFUND",
                    "refund_basis": "POLICY_SCHEDULE",
                },
                make_learner_headers(scene["seat"]["learner_id"]),
            ),
            201,
        )
        assert data["days_before_start"] == 1
        assert data["computed_refund_cents"] == 30000, (
            f"50 percent of the 60000-cent refundable base is 30000, got "
            f"{data['computed_refund_cents']}"
        )
        assert data["status"] == "SUBMITTED"

    def test_pro_rata_override_at_approval_values_the_same_seat_at_ninety_percent(self, api):
        """PRD 3.9: "Under the `PRO_RATA_ATTENDANCE` basis, the notice period is
        ignored entirely and the unused portion of the course is valued instead: the
        unused ratio is `total_sessions` less `sessions_attended`, divided by
        `total_sessions`; the effective percentage is the smaller of that ratio and a
        pro-rata ceiling of 90 percent; and the refundable base is multiplied by it."
        PRD 3.9: "The two bases genuinely diverge on identical inputs — a registration
        one day before the section starts with no sessions attended is valued at 50
        percent of the refundable base under the policy schedule and at 90 percent of it
        under pro-rata attendance."
        PRD 3.9: "The refund arm moves the request `SUBMITTED → REFUND_APPROVED` and
        re-values `computed_refund_cents` from scratch under the effective
        `refund_basis`, using the **current** logical clock and the **current**
        `sessions_attended` rather than the values captured at creation — so a request
        approved a week after it was opened is worth less under the policy schedule than
        it was on the day it was filed."

        Design: Difficulty/dual_variant_calc/refund_policy_schedule_vs_pro_rata_diverge_on_one_registration
        """
        reset_clock()
        scene = _paid_seat_at("2026-09-14T00:00:00Z")
        request = open_refund_request(
            scene["seat"]["registration_id"],
            learner_id=scene["seat"]["learner_id"],
            request_type="REFUND",
            refund_basis="POLICY_SCHEDULE",
        )
        assert request["computed_refund_cents"] == 30000

        data = validate_success(
            api.decide_refund_transfer_request(
                request["id"],
                {"decision": "APPROVE", "refund_basis": "PRO_RATA_ATTENDANCE"},
                REGISTRAR,
            )
        )
        assert data["status"] == "REFUND_APPROVED"
        assert data["computed_refund_cents"] == 54000, (
            f"90 percent of the 60000-cent refundable base is 54000, got "
            f"{data['computed_refund_cents']}"
        )
        assert data["computed_refund_cents"] != 30000


class TestProgramRevenueRoundingOrder:
    """Overhead is rounded per line and only then summed."""

    def test_two_identical_lines_round_per_line_before_summing(self, api):
        """PRD 3.6: "For each line, take its gross as `amount_paid_cents` less
        `amount_refunded_cents`; compute institutional overhead as that gross multiplied
        by an overhead rate of 18.5 percent, **rounded half up to whole cents at this
        point, per line**; then subtract that overhead and a flat platform fee of 250
        cents per registration from the gross to obtain the line's net."
        PRD 3.6: "`net_program_revenue_cents` is the plain integer sum of those per-line
        nets, with no further rounding applied to the total. Summing gross across lines
        and applying the overhead rate once at the end is forbidden and produces a
        different number whenever a per-line overhead lands on a fractional cent."

        Design: Difficulty/combinatorial_formula/net_program_revenue_rounds_per_line_before_summing
        """
        reset_clock()
        scene = setup_open_offering(
            offering_overrides={"min_enrollment": 2, "tuition_cents": 59904}
        )
        add_paid_registration(scene["offering_id"], learner_index=0)
        add_paid_registration(scene["offering_id"], learner_index=1)

        offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
        assert offering["net_program_revenue_cents"] == 101048, (
            f"two lines of 62300 each net 50524 after per-line rounding, got "
            f"{offering['net_program_revenue_cents']}"
        )
        assert offering["net_program_revenue_cents"] != 101049
        assert offering["paid_enrollment_count"] == 2

    def test_the_pinned_price_feeding_the_revenue_lines(self, api):
        """PRD 3.5: "Step six multiplies the subtotal by the selected rate and rounds
        half up to whole cents to produce a raw fee."
        PRD 3.5: "Step eight sets `total_due_cents` to the subtotal plus
        `processing_fee_cents`."
        PRD 3.6: "For each line, take its gross as `amount_paid_cents` less
        `amount_refunded_cents`; compute institutional overhead as that gross multiplied
        by an overhead rate of 18.5 percent, **rounded half up to whole cents at this
        point, per line**; then subtract that overhead and a flat platform fee of 250
        cents per registration from the gross to obtain the line's net."

        Design: Difficulty/combinatorial_formula/net_program_revenue_rounds_per_line_before_summing
        """
        reset_clock()
        scene = setup_open_offering(
            offering_overrides={"min_enrollment": 2, "tuition_cents": 59904}
        )
        first = add_paid_registration(scene["offering_id"], learner_index=0)
        registration = read_registration(first["registration_id"])
        assert registration["processing_fee_cents"] == 2396
        assert registration["total_due_cents"] == 62300

        offering = read_offering(scene["offering_id"])
        assert offering["net_program_revenue_cents"] == 50524, (
            f"a single 62300 line nets 62300 - 11526 - 250, got "
            f"{offering['net_program_revenue_cents']}"
        )


class TestRequestForkIntoTransferArm:
    """A TRANSFER request approves into its own arm, never into the refund arm."""

    def test_approving_a_transfer_lands_in_transfer_approved(self, api):
        """PRD 3.9: "The transfer arm moves the request `SUBMITTED →
        TRANSFER_APPROVED` and validates the destination instead of the money."
        PRD 3.9: "Creation records two derived values. `days_before_start` is the number
        of whole days between the logical clock and the source section's `start_date`,
        obtained by dividing the interval by 86,400 seconds and taking the floor; it may
        be negative when the section has already begun. `computed_refund_cents` is
        filled with a provisional valuation, and the request enters `status` `SUBMITTED`
        with `settled_at` null."

        Design: Difficulty/non_linear_state_machine/refund_transfer_request_forks_into_transfer_arm_not_refund_arm
        """
        reset_clock()
        scene = setup_transfer_scene(destination_tuition_cents=50000)
        created = validate_success(
            api.create_refund_transfer_request(
                {
                    "registration_id": scene["registration_id"],
                    "request_type": "TRANSFER",
                    "target_offering_id": scene["dest_id"],
                },
                make_learner_headers(scene["learner_id"]),
            ),
            201,
        )
        assert created["status"] == "SUBMITTED"
        assert created["settled_at"] is None

        decided = validate_success(
            api.decide_refund_transfer_request(
                created["id"], {"decision": "APPROVE"}, REGISTRAR
            )
        )
        assert decided["status"] == "TRANSFER_APPROVED"
        assert decided["status"] != "REFUND_APPROVED"
        assert decided["request_type"] == "TRANSFER"

    def test_the_transfer_arm_moves_no_money_and_no_seat_at_decision_time(self, api):
        """PRD 3.9: "The transfer arm moves the request `SUBMITTED →
        TRANSFER_APPROVED` and validates the destination instead of the money."
        PRD 3.9: "Settlement, also a `Registrar` action, executes the approved arm and
        moves the request to `SETTLED`, stamping `settled_at` with the current
        logical-clock instant."

        Design: Difficulty/non_linear_state_machine/refund_transfer_request_forks_into_transfer_arm_not_refund_arm
        """
        reset_clock()
        scene = setup_transfer_scene(destination_tuition_cents=50000)
        request = open_refund_request(
            scene["registration_id"],
            learner_id=scene["learner_id"],
            request_type="TRANSFER",
            target_offering_id=scene["dest_id"],
        )
        decided = decide_request(request["id"], "APPROVE")
        assert decided["computed_refund_cents"] == 0, (
            "the transfer arm leaves the cash residual at 0 until settlement"
        )
        source = read_registration(scene["registration_id"])
        assert source["enrollment_status"] == "ENROLLED"
        assert source["transferred_to_registration_id"] is None


class TestRefundWindowOutranksTransferTarget:
    """A request that breaks the window rule and the target rule reports the window."""

    def test_closed_window_reports_refund_window_closed(self, api):
        """PRD 2.8: "When a request would fail more than one rule, exactly one error is
        returned, and which one is fully determined: rules are evaluated in ascending
        priority order and the **first** rule that fails determines the response."
        PRD 3.9: "Requests are opened against a registration whose `enrollment_status`
        is `ENROLLED`, and they may be opened only while the logical clock is strictly
        earlier than the source section's `end_date`; once teaching has ended, no refund
        or transfer may be opened and the attempt is refused with
        `ERR_REFUND_WINDOW_CLOSED` (HTTP 422)."
        PRD 3.9: "For a transfer, the destination is vetted for compatibility at this
        moment as well as again at adjudication: it must not be the source
        registration's own `offering_id`, must be `OPEN` or `WAITLIST_ONLY`, must sit on
        a course whose `status` is `ACTIVE`, and must sit on a course whose `ceu_units`
        equals the source course's `ceu_units`, or the request is refused with
        `ERR_TRANSFER_TARGET_INCOMPATIBLE`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_refund_window_closed_wins_over_referential_transfer_target
        """
        reset_clock()
        scene = setup_transfer_scene(
            destination_tuition_cents=25000,
            destination_course_spec=COURSE_EXT_050,
            destination_overrides={
                "session_count": 4,
                "term_code": "2027SP",
                "start_date": "2027-02-01T00:00:00Z",
                "end_date": "2027-03-01T00:00:00Z",
                "census_at": "2027-01-20T00:00:00Z",
            },
        )
        set_clock("2026-11-20T00:00:00Z")

        error = validate_error(
            api.create_refund_transfer_request(
                {
                    "registration_id": scene["registration_id"],
                    "request_type": "TRANSFER",
                    "target_offering_id": scene["dest_id"],
                },
                make_learner_headers(scene["learner_id"]),
            ),
            ApiErrorId.ERR_REFUND_WINDOW_CLOSED,
            422,
        )
        assert error["error_id"] != "ERR_TRANSFER_TARGET_INCOMPATIBLE"

    def test_the_rejected_request_is_never_persisted(self, api):
        """PRD 3.9: "Requests are opened against a registration whose
        `enrollment_status` is `ENROLLED`, and they may be opened only while the logical
        clock is strictly earlier than the source section's `end_date`; once teaching
        has ended, no refund or transfer may be opened and the attempt is refused with
        `ERR_REFUND_WINDOW_CLOSED` (HTTP 422)."
        PRD 2.3: "Refund and transfer requests may be filtered by `registration_id`,
        `target_offering_id`, `status` and `request_type`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_refund_window_closed_wins_over_referential_transfer_target
        """
        reset_clock()
        scene = setup_transfer_scene(
            destination_tuition_cents=25000,
            destination_course_spec=COURSE_EXT_050,
            destination_overrides={
                "session_count": 4,
                "term_code": "2027SP",
                "start_date": "2027-02-01T00:00:00Z",
                "end_date": "2027-03-01T00:00:00Z",
                "census_at": "2027-01-20T00:00:00Z",
            },
        )
        set_clock("2026-11-20T00:00:00Z")
        api.create_refund_transfer_request(
            {
                "registration_id": scene["registration_id"],
                "request_type": "TRANSFER",
                "target_offering_id": scene["dest_id"],
            },
            make_learner_headers(scene["learner_id"]),
        )
        _, meta = validate_paginated(
            api.list_refund_transfer_requests(
                REGISTRAR, params={"registration_id": scene["registration_id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_registration(scene["registration_id"])["enrollment_status"] == "ENROLLED"


def test_settled_refund_promotes_the_waitlist_head_by_created_at(api):
    """PRD 3.5: "Whenever a seat is released on a section — by a settled refund, by a
    settled transfer, or by the cancellation cascade — the system **first** attempts a
    promotion: among that section's registrations whose `enrollment_status` is
    `WAITLISTED` and whose `payment_status` is `PAID` or `VOUCHER_COMMITTED`, the one
    with the smallest `created_at` moves `WAITLISTED → ENROLLED`, has its `enrolled_at`
    stamped with the current logical-clock instant, and causes the section's
    `waitlist_count` to decrease by 1 while `confirmed_enrollment_count` and
    `paid_enrollment_count` each increase by 1."
    PRD 3.9: "On the money axis, a registration that was `PAID` moves `PAID →
    REFUNDED` when `computed_refund_cents` equals `amount_paid_cents` and `PAID →
    PARTIALLY_REFUNDED` when the refund is above zero but strictly below
    `amount_paid_cents`; a registration still sitting at `VOUCHER_COMMITTED` because the
    section has not yet cleared census moves `VOUCHER_COMMITTED → REFUNDED` with
    `amount_refunded_cents` set to `amount_paid_cents`, its voucher moving
    `amount_paid_cents` out of `committed_cents` and back into `remaining_cents`, its
    voucher `status` re-derived, and its sponsor account moving the same amount out of
    `committed_cents` and back into `unallocated_voucher_cents`."

    Design: Corner/state_machines/settled_refund_promotes_waitlist_head_by_created_at
    """
    reset_clock()
    scene = setup_single_seat_offering_with_waitlist(waitlisted=1)
    seated = scene["seated"]
    waiting = scene["waiting"][0]
    set_clock("2026-09-14T00:00:00Z")

    request = open_refund_request(
        seated["registration_id"],
        learner_id=seated["learner_id"],
        request_type="REFUND",
        refund_basis="POLICY_SCHEDULE",
    )
    approved = decide_request(request["id"], "APPROVE")
    assert approved["computed_refund_cents"] == 30000

    settled = validate_success(
        api.settle_refund_transfer_request(request["id"], REGISTRAR)
    )
    assert settled["status"] == "SETTLED"

    source = read_registration(seated["registration_id"])
    assert source["enrollment_status"] == "WITHDRAWN"
    assert source["payment_status"] == "PARTIALLY_REFUNDED"
    assert source["amount_refunded_cents"] == 30000

    promoted = read_registration(waiting["registration_id"])
    assert promoted["enrollment_status"] == "ENROLLED"

    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["waitlist_count"] == 0
    assert offering["confirmed_enrollment_count"] == 1
    assert offering["status"] == "WAITLIST_ONLY"


def test_settled_refund_with_empty_waitlist_reverts_section_to_open(api):
    """PRD 3.5: "Only when no such registration exists does the section fall back from
    `WAITLIST_ONLY → OPEN`, incrementing its `version` by 1. That fallback closes the
    cycle between the open and waitlist-only postures, which a section may traverse any
    number of times."
    PRD 3.9: "The source section's `confirmed_enrollment_count` and
    `paid_enrollment_count` each decrease by 1, the seat-release rule of §3.5 runs —
    waitlist promotion first, and only failing that the fall back from `WAITLIST_ONLY →
    OPEN` — and the section's `net_program_revenue_cents` is recomputed."

    Design: Corner/state_machines/settled_refund_with_empty_waitlist_reverts_offering_to_open
    """
    reset_clock()
    scene = setup_single_seat_offering_with_waitlist(waitlisted=0)
    assert scene["offering"]["status"] == "WAITLIST_ONLY"
    seated = scene["seated"]
    set_clock("2026-09-14T00:00:00Z")

    request = open_refund_request(
        seated["registration_id"],
        learner_id=seated["learner_id"],
        request_type="REFUND",
        refund_basis="POLICY_SCHEDULE",
    )
    decide_request(request["id"], "APPROVE")
    validate_success(api.settle_refund_transfer_request(request["id"], REGISTRAR))

    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["status"] == "OPEN"
    assert offering["confirmed_enrollment_count"] == 0
    assert offering["waitlist_count"] == 0
    assert offering["net_program_revenue_cents"] == 0
    assert read_registration(seated["registration_id"])["enrollment_status"] == "WITHDRAWN"


def test_program_revenue_excludes_unpaid_and_withdrawn_lines(api):
    """PRD 3.6: "Take the registrations on the section whose `payment_status` is `PAID`
    or `PARTIALLY_REFUNDED` **and** whose `enrollment_status` is `ENROLLED`, `COMPLETED`
    or `NO_SHOW`; registrations that are `UNPAID`, `VOUCHER_COMMITTED` or `REFUNDED` on
    the money axis, or `PENDING`, `WAITLISTED`, `WITHDRAWN` or `TRANSFERRED_OUT` on the
    seat axis, are excluded entirely."
    PRD 3.6: "The figure is recomputed whenever a registration is paid, whenever the
    census decision is taken, whenever a section is closed out, and whenever a refund or
    transfer request is settled."

    Design: Corner/calculations/net_program_revenue_excludes_unpaid_and_withdrawn_lines
    """
    reset_clock()
    scene = setup_open_offering()
    kept = add_paid_registration(scene["offering_id"], learner_index=0)
    unpaid_learner = new_learner(email="ben@x.com", full_name="Ben Osei")
    unpaid = register_learner(scene["offering_id"], unpaid_learner["id"], as_registrar=True)
    refunded = add_paid_registration(scene["offering_id"], learner_index=2)

    set_clock("2026-09-14T00:00:00Z")
    request = open_refund_request(
        refunded["registration_id"], request_type="REFUND", refund_basis="POLICY_SCHEDULE"
    )
    decide_request(request["id"], "APPROVE")
    validate_success(api.settle_refund_transfer_request(request["id"], REGISTRAR))

    offering = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert offering["net_program_revenue_cents"] == 50606, (
        f"only the one surviving ENROLLED x PAID line counts, got "
        f"{offering['net_program_revenue_cents']}"
    )
    assert offering["confirmed_enrollment_count"] == 1
    assert read_registration(unpaid["id"])["payment_status"] == "UNPAID"
    withdrawn = read_registration(refunded["registration_id"])
    assert withdrawn["enrollment_status"] == "WITHDRAWN"
    assert withdrawn["payment_status"] == "PARTIALLY_REFUNDED"
    assert withdrawn["amount_refunded_cents"] == 30000
    assert read_registration(kept["registration_id"])["enrollment_status"] == "ENROLLED"


def test_transfer_credit_short_of_destination_price_returns_402(api):
    """PRD 3.9: "The carried credit must also stretch: the registration's
    `amount_paid_cents` less a flat transfer fee of 2,500 cents must be at least the
    `total_due_cents` that the pricing resolution of §3.5 produces for this learner on
    the destination section, or the approval is refused with
    `ERR_TRANSFER_CREDIT_INSUFFICIENT` (HTTP 402)."

    Design: Corner/validations/transfer_credit_insufficient_on_decide_returns_402
    """
    reset_clock()
    scene = setup_transfer_scene(destination_tuition_cents=70000)
    request = open_refund_request(
        scene["registration_id"],
        learner_id=scene["learner_id"],
        request_type="TRANSFER",
        target_offering_id=scene["dest_id"],
    )

    validate_error(
        api.decide_refund_transfer_request(
            request["id"], {"decision": "APPROVE"}, REGISTRAR
        ),
        ApiErrorId.ERR_TRANSFER_CREDIT_INSUFFICIENT,
        402,
    )
    assert read_request(request["id"])["status"] == "SUBMITTED"
    source = read_registration(scene["registration_id"])
    assert source["enrollment_status"] == "ENROLLED"
    assert source["transferred_to_registration_id"] is None
    _, meta = validate_paginated(
        api.list_registrations(REGISTRAR, params={"offering_id": scene["dest_id"]})
    )
    assert meta["total_count"] == 0


def test_transfer_settle_mints_destination_registration_and_returns_the_residual(api):
    """PRD 3.9: "A brand-new registration is then minted on the destination section for
    the same learner and priced fresh by the eight-step resolution of §3.5 using the
    learner's **current** `loyalty_tier` — not the tier that priced the source
    registration — so a learner who has completed a course in the meantime transfers at
    their improved rate."
    PRD 3.9: "The new registration's `amount_paid_cents` is set to its own
    `total_due_cents`, its `payment_status` is set directly to `PAID`, and seat
    resolution runs on the destination section exactly as it does after an ordinary
    payment."
    PRD 3.9: "The source registration then has its `transferred_to_registration_id` set
    to the new registration's `id`, moves `ENROLLED → TRANSFERRED_OUT` on the seat axis
    and to `REFUNDED` on the money axis, and receives a cash residual: the source
    `amount_paid_cents` less the 2,500-cent transfer fee, less the new registration's
    `total_due_cents`."

    Design: Corner/endpoints/transfer_settle_mints_destination_registration_and_refunds_residual
    """
    reset_clock()
    scene = setup_transfer_scene(destination_tuition_cents=50000)
    request = open_refund_request(
        scene["registration_id"],
        learner_id=scene["learner_id"],
        request_type="TRANSFER",
        target_offering_id=scene["dest_id"],
    )
    decide_request(request["id"], "APPROVE")

    settled = validate_success(
        api.settle_refund_transfer_request(request["id"], REGISTRAR)
    )
    assert settled["status"] == "SETTLED"
    assert settled["computed_refund_cents"] == 7900, (
        f"62400 less the 2500 transfer fee less the 52000 destination price is 7900, "
        f"got {settled['computed_refund_cents']}"
    )

    rows, meta = validate_paginated(
        api.list_registrations(REGISTRAR, params={"offering_id": scene["dest_id"]})
    )
    assert meta["total_count"] == 1
    minted = rows[0]
    assert minted["total_due_cents"] == 52000
    assert minted["payment_status"] == "PAID"
    assert minted["enrollment_status"] == "ENROLLED"

    source = read_registration(scene["registration_id"])
    assert source["enrollment_status"] == "TRANSFERRED_OUT"
    assert source["payment_status"] == "REFUNDED"
    assert source["amount_refunded_cents"] == 7900
    assert source["transferred_to_registration_id"] == minted["id"]

    assert read_offering(scene["source_id"])["confirmed_enrollment_count"] == 0
    assert read_offering(scene["dest_id"])["confirmed_enrollment_count"] == 1


def test_transfer_to_a_different_ceu_course_is_incompatible(api):
    """PRD 3.9: "For a transfer, the destination is vetted for compatibility at this
    moment as well as again at adjudication: it must not be the source registration's
    own `offering_id`, must be `OPEN` or `WAITLIST_ONLY`, must sit on a course whose
    `status` is `ACTIVE`, and must sit on a course whose `ceu_units` equals the source
    course's `ceu_units`, or the request is refused with
    `ERR_TRANSFER_TARGET_INCOMPATIBLE`."

    Design: Corner/errors/transfer_to_offering_with_different_ceu_units_returns_incompatible
    """
    reset_clock()
    scene = setup_transfer_scene(
        destination_tuition_cents=25000,
        destination_course_spec=COURSE_EXT_050,
        destination_overrides={
            "session_count": 4,
            "term_code": "2027SP",
            "start_date": "2027-02-01T00:00:00Z",
            "end_date": "2027-03-01T00:00:00Z",
            "census_at": "2027-01-20T00:00:00Z",
        },
    )
    validate_error(
        api.create_refund_transfer_request(
            {
                "registration_id": scene["registration_id"],
                "request_type": "TRANSFER",
                "target_offering_id": scene["dest_id"],
            },
            make_learner_headers(scene["learner_id"]),
        ),
        ApiErrorId.ERR_TRANSFER_TARGET_INCOMPATIBLE,
        422,
    )
    _, meta = validate_paginated(
        api.list_refund_transfer_requests(
            REGISTRAR, params={"registration_id": scene["registration_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_registration(scene["registration_id"])["enrollment_status"] == "ENROLLED"
