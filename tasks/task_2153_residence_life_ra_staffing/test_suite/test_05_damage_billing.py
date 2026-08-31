"""Room condition, damage assessment and the bursar's ledger."""
from test_helpers import (
    ApiErrorId,
    assert_damage_charge,
    assert_settlement_arithmetic,
    assert_timestamp_equals,
    create_room,
    create_ra,
    create_room_inspection_payload,
    damage_line,
    read_damage_charge,
    read_room,
    read_room_inspection,
    read_student,
    room_version,
    schedule_inspection,
    set_clock,
    setup_billed_damage_charge,
    setup_certified_ra_with_rooms,
    setup_hall_with_rooms,
    setup_pending_damage_charge,
    create_student,
    create_floor,
    place_student,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDualVariantDamageAssessment:
    def test_billing_computes_the_depreciated_subtotal_beside_the_list_figure(
        self, api, bursar_headers
    ):
        """PRD §3.6: "The catalogue is fixed in whole cents: a `WALL` line is 7,500
        cents each, a `DOOR` 22,000, a `CARPET` 18,000, a `FURNITURE` item 13,500 and a
        `WINDOW` 26,000."
        PRD §3.6: "The `depreciation_rate` is six one-hundredths for each such year,
        capped at one half — so a room eight years past renovation depreciates at
        forty-eight hundredths, and a room nine or more years past renovation is held at
        fifty hundredths."
        PRD §3.6: "**The rounding order is pinned:** each damage line is separately
        multiplied by its catalogue price and quantity, reduced by the depreciation
        rate, and rounded half-up to whole cents; only then are the rounded lines summed
        into `assessed_subtotal_cents`."

        Design: Difficulty/dual_variant_calc/damage_provisional_list_vs_final_depreciated_subtotal
        """
        base = setup_pending_damage_charge()
        charge = base["charge"]
        assert charge["provisional_subtotal_cents"] == 37000, (
            "two WALL lines at 7,500 plus one DOOR at 22,000 list at 37,000 cents"
        )

        billed = validate_success(
            api.bill_damage_charge(
                charge["id"], {"note": "term-end assessment"}, bursar_headers
            )
        )

        assert_damage_charge(billed)
        assert billed["depreciation_rate"] == 0.30, (
            "a room five years past its 2021 renovation depreciates at 0.30, got "
            f"{billed['depreciation_rate']}"
        )
        assert billed["assessed_subtotal_cents"] == 25900, (
            "10,500 for the WALL line plus 15,400 for the DOOR line"
        )
        assert billed["provisional_subtotal_cents"] == 37000, (
            "the list figure is never rewritten by billing"
        )
        assert billed["assessed_subtotal_cents"] != billed["provisional_subtotal_cents"]

    def test_billing_moves_the_charge_to_billed_and_the_inspection_still_points_at_it(
        self, api, bursar_headers
    ):
        """PRD §3.6: "A `BursarOfficer` bills a `PENDING` charge, optionally attaching
        a `note`, and the charge moves to `BILLED`."
        PRD §3.6: "Completion stamps `completed_at`, copies the supplied score onto the
        room's own `condition_score`, and, when `damage_lines` is non-empty,
        synthesizes a damage charge in `PENDING` whose `student_id` is the supplied
        `responsible_student_id`, or the room's sole occupant when none was supplied;
        the new charge's identifier is recorded on the inspection as
        `damage_charge_id`."

        Design: Difficulty/dual_variant_calc/damage_provisional_list_vs_final_depreciated_subtotal
        """
        base = setup_pending_damage_charge()
        assert base["charge"]["status"] == "PENDING"

        billed = validate_success(
            api.bill_damage_charge(
                base["charge"]["id"], {"note": "term-end assessment"}, bursar_headers
            )
        )

        assert billed["status"] == "BILLED"
        assert billed["student_id"] == base["resident"]["id"]
        inspection = read_room_inspection(base["inspection"]["id"])
        assert inspection["damage_charge_id"] == billed["id"]
        assert inspection["status"] == "COMPLETED"
        assert read_room(base["room"]["id"])["condition_score"] == 62


class TestSettlementEvaluationOrder:
    def test_admin_tier_reads_the_gross_and_relief_reads_the_fee_inclusive_total(
        self, api, bursar_headers
    ):
        """PRD §3.6: "Step two selects an administrative rate from that gross figure
        alone: zero for a gross below 5,000 cents, five one-hundredths for a gross from
        5,000 cents up to but not including 20,000 cents, and one tenth for a gross of
        20,000 cents or more."
        PRD §3.6: "Step five computes `hardship_relief_cents`: it is zero when the
        resident's `financial_hardship_flag` is false, and otherwise the smaller of
        5,000 cents and one quarter of the total-before-relief figure, that quarter
        being rounded half-up to whole cents."
        PRD §3.6: "**The administrative tier is chosen from the gross figure and never
        from the total before relief; the relief base is the total before relief and
        never the gross figure.**"

        Design: Difficulty/combinatorial_formula/damage_settlement_admin_tier_then_hardship_relief_evaluation_order
        """
        base = setup_pending_damage_charge(financial_hardship_flag=True)

        billed = validate_success(
            api.bill_damage_charge(
                base["charge"]["id"], {"note": "settlement order probe"}, bursar_headers
            )
        )

        assert billed["admin_fee_cents"] == 2590, (
            "a gross of 25,900 sits in the ten-percent tier, so the fee is 2,590"
        )
        assert billed["hardship_relief_cents"] == 5000, (
            "a quarter of the 28,490 total-before-relief is 7,123, capped at 5,000"
        )
        assert billed["final_amount_cents"] == 23490
        assert_settlement_arithmetic(billed)

    def test_billing_opens_the_appeal_window_and_recomputes_the_resident_balance(
        self, api, bursar_headers
    ):
        """PRD §3.6: "Billing then stamps `billed_at` with the logical clock and sets
        `appeal_deadline_at` to fourteen days after it, and the resident's
        `damage_balance_cents` is recomputed."
        PRD §3.6: "That balance is the sum of `final_amount_cents` over the resident's
        charges whose status is `BILLED` or `APPEALED`; a `PENDING`, `SETTLED`,
        `WAIVED` or `VOID` charge contributes nothing."

        Design: Difficulty/combinatorial_formula/damage_settlement_admin_tier_then_hardship_relief_evaluation_order
        """
        base = setup_pending_damage_charge(financial_hardship_flag=True)
        assert read_student(base["resident"]["id"])["damage_balance_cents"] == 0, (
            "a PENDING charge contributes nothing"
        )

        billed = validate_success(
            api.bill_damage_charge(
                base["charge"]["id"], {"note": "settlement order probe"}, bursar_headers
            )
        )

        assert_timestamp_equals(
            billed["billed_at"], "2026-08-01T00:00:00Z", "billed_at"
        )
        assert_timestamp_equals(
            billed["appeal_deadline_at"], "2026-08-15T00:00:00Z", "appeal_deadline_at"
        )
        assert read_student(base["resident"]["id"])["damage_balance_cents"] == 23490


def test_appeal_adjustment_reruns_the_settlement_and_bars_a_second_appeal(
    api, bursar_headers
):
    """PRD §3.6: "`ADJUST` carries `adjusted_subtotal_cents`, which must be present and
    must fall between zero and the existing `assessed_subtotal_cents` inclusive; the
    adjusted figure replaces `assessed_subtotal_cents`, and `admin_fee_cents`,
    `hardship_relief_cents` and `final_amount_cents` are then recomputed by the same
    six-step settlement from that new subtotal."
    PRD §3.6: "`ADJUST` records `appeal_outcome` as `ADJUSTED` and `UPHOLD` records it
    as `UPHELD`."
    PRD §3.6: "An appeal is permitted only once per charge: a charge whose
    `appeal_outcome` is already `ADJUSTED` or `UPHELD` refuses a second appeal with
    `ERR_APPEAL_ALREADY_RESOLVED`."

    Design: Corner/state_machines/damage_appeal_adjust_recomputes_settlement_and_returns_charge_to_billed
    """
    base = setup_billed_damage_charge(financial_hardship_flag=True)
    charge_id = base["charge"]["id"]
    validate_success(
        api.appeal_damage_charge(
            charge_id,
            {"reason": "the door was already cracked at check-in"},
            base["resident_headers"],
        )
    )

    adjusted = validate_success(
        api.resolve_damage_appeal(
            charge_id,
            {"action": "ADJUST", "adjusted_subtotal_cents": 10000},
            bursar_headers,
        )
    )

    assert adjusted["status"] == "BILLED"
    assert adjusted["appeal_outcome"] == "ADJUSTED"
    assert adjusted["assessed_subtotal_cents"] == 10000
    assert adjusted["admin_fee_cents"] == 500, "10,000 sits in the five-percent tier"
    assert adjusted["hardship_relief_cents"] == 2625, "a quarter of 10,500"
    assert adjusted["final_amount_cents"] == 7875
    assert_settlement_arithmetic(adjusted)
    assert read_student(base["resident"]["id"])["damage_balance_cents"] == 7875

    second_appeal = api.appeal_damage_charge(
        charge_id, {"reason": "still too high"}, base["resident_headers"]
    )
    validate_error(second_appeal, ApiErrorId.ERR_APPEAL_ALREADY_RESOLVED.value, 409)
    assert read_damage_charge(charge_id)["provisional_subtotal_cents"] == 37000, (
        "the list figure is never rewritten by an appeal resolution"
    )


def test_appeal_after_the_deadline_is_refused_but_the_deadline_itself_is_inclusive(
    api, bursar_headers
):
    """PRD §3.6: "The appeal must also arrive at or before `appeal_deadline_at` on the
    logical clock; strictly later is `ERR_APPEAL_WINDOW_CLOSED`."
    PRD §3.6: "The billed resident — and only the billed resident — may appeal,
    supplying a `reason` that is stored as `appeal_reason`."

    Design: Corner/validations/appeal_filed_after_the_deadline_returns_appeal_window_closed
    """
    base = setup_billed_damage_charge(
        damage_lines=[damage_line("WALL", 1)],
        financial_hardship_flag=False,
        condition_score=70,
    )
    charge = base["charge"]
    assert charge["provisional_subtotal_cents"] == 7500
    assert charge["assessed_subtotal_cents"] == 5250
    assert charge["admin_fee_cents"] == 263
    assert charge["hardship_relief_cents"] == 0
    assert charge["final_amount_cents"] == 5513
    assert_timestamp_equals(
        charge["appeal_deadline_at"], "2026-08-15T00:00:00Z", "appeal_deadline_at"
    )

    set_clock("2026-08-15T00:00:01Z")
    too_late = api.appeal_damage_charge(
        charge["id"], {"reason": "one day late"}, base["resident_headers"]
    )
    validate_error(too_late, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, 409)
    assert read_damage_charge(charge["id"])["status"] == "BILLED"

    set_clock("2026-08-15T00:00:00Z")
    on_time = validate_success(
        api.appeal_damage_charge(
            charge["id"],
            {"reason": "filed exactly on the deadline"},
            base["resident_headers"],
        )
    )
    assert on_time["status"] == "APPEALED"
    assert read_student(base["resident"]["id"])["damage_balance_cents"] == 5513, (
        "an APPEALED charge still counts toward the resident's balance"
    )


def test_taking_an_occupied_room_offline_cancels_its_scheduled_inspection(
    api, director_headers
):
    """PRD §3.1: "Going offline from `OCCUPIED` also revokes every approved or
    checked-in break stay for that room and cancels every scheduled inspection of it,
    exactly as the hall-wide cascade does."
    PRD §3.6: "`COMPLETED`, `SUPERSEDED` and `CANCELLED` are all terminal; the
    `CANCELLED` state is written only by the system, when the inspected room goes
    offline."

    Design: Corner/state_machines/taking_a_room_offline_cancels_its_scheduled_inspection
    """
    base = setup_certified_ra_with_rooms(
        room_specs=[{"room_number": "201", "bed_capacity": 2}]
    )
    room = base["rooms"][0]
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))
    place_student(resident["id"], room["id"])
    inspection = schedule_inspection(
        base["ra_headers"],
        room["id"],
        inspection_type="HEALTH_SAFETY",
        scheduled_for="2026-08-10T09:00:00Z",
    )
    assert inspection["status"] == "SCHEDULED"

    offline = validate_success(
        api.set_room_status(
            room["id"],
            {"target_status": "OFFLINE", "reason": "mould remediation"},
            director_headers,
        )
    )

    assert offline["status"] == "OFFLINE"
    cancelled = read_room_inspection(inspection["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["damage_charge_id"] is None
    assert cancelled["completed_at"] is None
    _, meta = validate_paginated(
        api.list_damage_charges(director_headers, params={"inspection_id": inspection["id"]})
    )
    assert meta["total_count"] == 0, "a cancelled inspection produces no charge"
    assert read_room(room["id"])["condition_score"] == 100


def test_scheduling_an_inspection_on_another_floor_reports_a_floor_mismatch(
    api, director_headers
):
    """PRD §3.6: "The room's floor must also be the RA's own `assigned_floor_id`, or
    the request is refused with `ERR_FLOOR_MISMATCH`."
    PRD §3.6: "The inspecting RA is taken from the caller and stored as
    `inspector_ra_id`; the RA must be `ACTIVE`, and an inactive scheduler is refused
    with `ERR_RA_NOT_ACTIVE`."

    Design: Corner/errors/inspecting_a_room_on_another_floor_returns_floor_mismatch
    """
    base = setup_hall_with_rooms(room_specs=[{"room_number": "201", "bed_capacity": 2}])
    own_room = base["rooms"][0]
    other_floor = create_floor(base["building"]["id"], floor_number=3)
    other_room = create_room(other_floor["id"], room_number="301", bed_capacity=2)
    staff = create_ra(floor_id=base["floor"]["id"])

    off_floor = api.create_room_inspection(
        create_room_inspection_payload(
            other_room["id"],
            room_version(other_room["id"]),
            inspection_type="HEALTH_SAFETY",
            scheduled_for="2026-08-10T09:00:00Z",
        ),
        staff["ra_headers"],
    )

    validate_error(off_floor, ApiErrorId.ERR_FLOOR_MISMATCH.value, 422)
    _, meta = validate_paginated(
        api.list_room_inspections(director_headers, params={"room_id": other_room["id"]})
    )
    assert meta["total_count"] == 0

    on_floor = validate_success(
        api.create_room_inspection(
            create_room_inspection_payload(
                own_room["id"],
                room_version(own_room["id"]),
                inspection_type="HEALTH_SAFETY",
                scheduled_for="2026-08-10T09:00:00Z",
            ),
            staff["ra_headers"],
        ),
        201,
    )
    assert on_floor["status"] == "SCHEDULED"
    assert on_floor["inspector_ra_id"] == staff["ra"]["id"]
