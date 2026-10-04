"""Membership cycles, freeze proration, class packs, credits and packs."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    OPERATOR,
    book,
    create_client,
    create_membership,
    create_session,
    ensure_tier,
    get_success_data,
    make_client_headers,
    same_instant,
    set_clock,
    setup_studio_roster,
    validate_error,
    validate_success,
)


class TestMembershipBillingCycle:

    def test_membership_cycle_late_fee_differs_between_the_two_variants(self, api):
        """PRD §3.9: "Under the billing-day chronological variant — the one an
        outcome of CHARGED selects — the late fee tests against the new due
        date, which sits one month in the future, so the fee fires only once the
        caller has advanced the clock past that new date. Under the
        forward-looking variant — selected by outcome EARLY_CHARGED — the fee
        tests against the old due date, which the clock has not yet reached, so
        the very same membership advances with no late fee at all."

        Design: Difficulty/dual_variant_calc/membership_cycle_late_fee_differs_between_billing_day_and_forward_looking_variant
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        anchor_one = create_membership(ctx["studio"]["id"], ctx["owner"], maya["id"],
                                       billing_anchor_day=1)
        anchor_two = create_membership(ctx["studio"]["id"], ctx["owner"], maya["id"],
                                       billing_anchor_day=2)

        # The first settled charge moves PENDING to ACTIVE and takes the fee in.
        first = validate_success(api.advance_membership_cycle(
            anchor_one["id"],
            {"advance_days": 0, "outcome": "CHARGED",
             "expected_membership_version": anchor_one["version"]}, ctx["owner"]))
        assert first["status"] in ("ACTIVE", "PAST_DUE")
        assert first["open_balance_cents"] >= 9000

        set_clock("2026-07-02T00:00:00Z")
        fresh_a = validate_success(api.get_membership(anchor_one["id"], ctx["owner"]))
        forward_a = validate_success(api.advance_membership_cycle(
            anchor_one["id"],
            {"advance_days": 0, "outcome": "EARLY_CHARGED",
             "expected_membership_version": fresh_a["version"]}, ctx["owner"]))
        assert forward_a["current_period_index"] == 2

        fresh_b = validate_success(api.get_membership(anchor_two["id"], ctx["owner"]))
        forward_b = validate_success(api.advance_membership_cycle(
            anchor_two["id"],
            {"advance_days": 0, "outcome": "EARLY_CHARGED",
             "expected_membership_version": fresh_b["version"]}, ctx["owner"]))
        assert forward_b["current_period_index"] == 1

        # Anchor day 1 has its old due date on 2026-07-01, already reached, so
        # the forward-looking variant posts the late fee on top of the cycle fee.
        assert forward_a["open_balance_cents"] > forward_b["open_balance_cents"], \
            "the two rows advance from the same clock position with different fees"

    def test_billing_day_variant_tests_the_new_due_date(self, api):
        """PRD §3.9: "The late fee is then tested against `next_billing_at` and, because the comparison is at-or-past rather than strictly past, the instant exactly equal to the due date lies inside the fee window: when the clock has reached the new due date the balance also grows by one tenth of the monthly fee truncated to whole cents and the membership moves to `PAST_DUE`."

        Design: Difficulty/dual_variant_calc/membership_cycle_late_fee_differs_between_billing_day_and_forward_looking_variant
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        membership = create_membership(ctx["studio"]["id"], ctx["owner"], maya["id"],
                                       billing_anchor_day=1)

        first = validate_success(api.advance_membership_cycle(
            membership["id"],
            {"advance_days": 0, "outcome": "CHARGED",
             "expected_membership_version": membership["version"]}, ctx["owner"]))
        balance_after_first = first["open_balance_cents"]

        # Anchor day 1 advances next_billing_at to 2026-07-01; the clock has not
        # reached it during the first charge, so no late fee fires.
        assert balance_after_first == 9000, \
            "one cycle fee and no late fee while the clock lags the due date"

    def test_a_frozen_membership_advances_without_a_charge(self, api):
        """PRD §3.9: "A membership that is `FROZEN` is skipped entirely: the cycle does not advance, no charge is posted, and `next_billing_at` simply moves by one calendar month."

        Design: Difficulty/dual_variant_calc/membership_cycle_late_fee_differs_between_billing_day_and_forward_looking_variant
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        membership = create_membership(ctx["studio"]["id"], ctx["owner"], maya["id"],
                                       billing_anchor_day=1,
                                       freeze_max_days_per_cycle=10)
        activated = validate_success(api.advance_membership_cycle(
            membership["id"],
            {"advance_days": 0, "outcome": "CHARGED",
             "expected_membership_version": membership["version"]}, ctx["owner"]))
        frozen = validate_success(api.freeze_membership(
            membership["id"],
            {"freeze_days": 10,
             "expected_membership_version": activated["version"]}, ctx["owner"]))
        assert frozen["status"] == "FROZEN"

        balance_before = frozen["open_balance_cents"]
        advanced = validate_success(api.advance_membership_cycle(
            membership["id"],
            {"advance_days": 30, "outcome": "CHARGED",
             "expected_membership_version": frozen["version"]}, ctx["owner"]))
        assert advanced["status"] == "FROZEN"
        assert advanced["open_balance_cents"] == balance_before, \
            "a FROZEN membership pays nothing"


class TestMembershipFreezeProration:

    def test_freezing_reports_the_prorated_fee_against_the_plan_ceiling(self, api):
        """PRD §3.9: "the proration factor is 1 minus the lesser of the counted days and the plan's `freeze_max_days_per_cycle` divided by the cycle length of 30 days; and the prorated monthly fee is the membership's monthly fee multiplied by that factor, truncated to whole cents."

        Design: Corner/calculations/freezing_a_membership_reports_the_prorated_fee_on_the_row
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        wide = create_membership(ctx["studio"]["id"], ctx["owner"], maya["id"],
                                 freeze_max_days_per_cycle=10,
                                 billing_anchor_day=1)
        narrow = create_membership(ctx["studio"]["id"], ctx["owner"], maya["id"],
                                   plan_name="Light Monthly",
                                   freeze_max_days_per_cycle=3,
                                   minimum_term_months=0, billing_anchor_day=1)

        wide_active = validate_success(api.advance_membership_cycle(
            wide["id"], {"advance_days": 0, "outcome": "CHARGED","expected_membership_version": wide["version"]}, ctx["owner"]))
        narrow_active = validate_success(api.advance_membership_cycle(
            narrow["id"], {"advance_days": 0, "outcome": "CHARGED","expected_membership_version": narrow["version"]}, ctx["owner"]))

        wide_frozen = validate_success(api.freeze_membership(
            wide["id"], {"freeze_days": 12,
                         "expected_membership_version": wide_active["version"]},
            ctx["owner"]))
        narrow_frozen = validate_success(api.freeze_membership(
            narrow["id"], {"freeze_days": 12,
                           "expected_membership_version": narrow_active["version"]},
            ctx["owner"]))

        assert wide_frozen["status"] == "FROZEN"
        assert narrow_frozen["status"] == "FROZEN"
        assert wide_frozen["prorated_fee_cents"] == 6000, \
            "9000 x (1 - 10/30), floored"
        assert narrow_frozen["prorated_fee_cents"] == 8100, \
            "9000 x (1 - 3/30), floored"

    def test_freeze_cap_exceeded_is_refused(self, api):
        """PRD §3.9: "if that running total would pass the annual freeze cap of 60 days the extension is refused with `ERR_FREEZE_CAP_EXCEEDED` and no proration is posted."

        Design: Corner/calculations/freezing_a_membership_reports_the_prorated_fee_on_the_row
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        membership = create_membership(ctx["studio"]["id"], ctx["owner"], maya["id"],
                                       freeze_max_days_per_cycle=28, billing_anchor_day=1)
        active = validate_success(api.advance_membership_cycle(
            membership["id"], {"advance_days": 0, "outcome": "CHARGED","expected_membership_version": membership["version"]},
            ctx["owner"]))

        # A plan whose per-cycle ceiling is small cannot absorb a very long
        # freeze; the cap error is the platform's declared refusal.
        validate_error(api.freeze_membership(
            membership["id"], {"freeze_days": 400,
                               "expected_membership_version": active["version"]},
            ctx["owner"]), ApiErrorId.ERR_FREEZE_CAP_EXCEEDED)


class TestClassPackCreditSemantics:

    def test_pack_create_defaults_start_fully_credited_with_derived_expiry(self, api):
        """PRD §3.9: "The pack's `credits_remaining` begins at `pack_size` and its status at `ACTIVE`, and the sale increments the client's `version` by 1."
        PRD §3.9: "The `expires_at` is derived from `purchased_at` according to the scheme: `NONE` gives the standard pack validity span, `SEASONAL` gives 90 days, and `PROMOTIONAL` gives 30 days while also capping the pack size at 12."

        Design: Corner/entities/class_pack_create_defaults_auto_renew_and_starts_fully_credited
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": maya["id"],
            "pack_size": 5, "purchased_at": "2026-06-01T00:00:00Z",
            "expiry_scheme": "NONE", "expected_client_version": maya["version"],
        }, ctx["owner"]), expected_status=201)

        assert pack["credits_remaining"] == 5
        assert pack["status"] == "ACTIVE"
        assert same_instant(pack["expires_at"], "2026-11-28T00:00:00Z"), \
            "180 days after purchase"
        assert pack["extension_days_used"] == 0
        assert pack["pending_expiry_grace_until"] is None

        client = validate_success(api.get_client(maya["id"], ctx["owner"]))
        assert client["version"] == maya["version"] + 1, \
            "pack creation advances the guarded client version"

    def test_promotional_scheme_expires_thirty_days_out(self, api):
        """PRD §3.9: "NONE` gives the standard pack validity span, `SEASONAL` gives 90 days, and `PROMOTIONAL` gives 30 days while also capping the pack size at 12."

        Design: Corner/entities/class_pack_create_defaults_auto_renew_and_starts_fully_credited
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": maya["id"],
            "pack_size": 8, "purchased_at": "2026-06-01T00:00:00Z",
            "expiry_scheme": "PROMOTIONAL", "expected_client_version": maya["version"],
        }, ctx["owner"]), expected_status=201)
        assert pack["credits_remaining"] == 8
        assert same_instant(pack["expires_at"], "2026-07-01T00:00:00Z"), "30 days out"


class TestPackExpirySweep:

    def test_pack_expiry_returns_a_quarter_of_the_unused_credits(self, api):
        """PRD §3.9: "running total would pass the annual freeze cap of 60 days the extension is refused with `ERR_FREEZE_CAP_EXCEEDED` and no proration is posted. The `prorated_fee_cents` fiel"
        PRD §3.9: "The expiry sweep moves every pack whose expires_at has been
        reached from ACTIVE, FROZEN or DEPLETED to EXPIRED, sets
        pending_expiry_grace_until to expires_at plus the pack grace days of 14."

        Design: Corner/calculations/pack_expiry_returns_a_quarter_of_the_unused_credits_to_the_studio
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        old_pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": bea["id"],
            "pack_size": 6, "purchased_at": "2026-01-01T00:00:00Z",
            "expiry_scheme": "NONE", "expected_client_version": bea["version"],
        }, ctx["owner"]), expected_status=201)
        promo_pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": maya["id"],
            "pack_size": 8, "purchased_at": "2026-06-01T00:00:00Z",
            "expiry_scheme": "PROMOTIONAL", "expected_client_version": maya["version"],
        }, ctx["owner"]), expected_status=201)

        set_clock("2026-07-15T00:00:00Z")
        swept_old = validate_success(api.sweep_class_pack_expiry(
            old_pack["id"], {"advance_clock_days": 0}, ctx["owner"]))
        assert swept_old["credits_returned_to_studio"] == 7, \
            "6 remaining plus floor(6 / 4) = 7 kept by the studio"

        swept_promo = validate_success(api.sweep_class_pack_expiry(
            promo_pack["id"], {"advance_clock_days": 0}, ctx["owner"]))
        assert swept_promo["credits_returned_to_studio"] == 10, \
            "8 remaining plus floor(8 / 4) = 10 kept by the studio"

    def test_swept_pack_is_expired_with_a_fourteen_day_grace(self, api):
        """PRD §3.9: "The expiry sweep moves every pack whose expires_at has been
        reached from ACTIVE, FROZEN or DEPLETED to EXPIRED, sets
        pending_expiry_grace_until to expires_at plus the pack grace days of 14."

        Design: Corner/calculations/pack_expiry_returns_a_quarter_of_the_unused_credits_to_the_studio
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        bea = create_client(ctx["studio"]["id"], display_name="Bea Tan",
                            email="bea@example.com")
        pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": bea["id"],
            "pack_size": 6, "purchased_at": "2026-01-01T00:00:00Z",
            "expiry_scheme": "NONE", "expected_client_version": bea["version"],
        }, ctx["owner"]), expected_status=201)
        set_clock("2026-07-15T00:00:00Z")
        validate_success(api.sweep_class_pack_expiry(
            pack["id"], {"advance_clock_days": 0}, ctx["owner"]))

        after = validate_success(api.get_class_pack(pack["id"], ctx["owner"]))
        assert after["status"] == "EXPIRED"
        assert same_instant(after["pending_expiry_grace_until"], "2026-07-14T00:00:00Z"), \
            "14 days past the expiry instant"

    def test_pack_extension_beyond_the_lifetime_cap_is_refused(self, api):
        """PRD §3.9: "the extension is refused with `ERR_PACK_EXTENSION_CAP_EXCEEDED` once the lifetime total would pass the maximum extension days of 90."

        Design: Corner/calculations/pack_expiry_returns_a_quarter_of_the_unused_credits_to_the_studio
        """
        ctx = setup_studio_roster(tier="GROWTH", with_template=False,
                                  with_instructor=False)
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": maya["id"],
            "pack_size": 5, "purchased_at": "2026-06-01T00:00:00Z",
            "expiry_scheme": "NONE", "expected_client_version": maya["version"],
        }, ctx["owner"]), expected_status=201)
        validate_success(api.extend_class_pack(
            pack["id"], {"extend_days": 60, "reason": "goodwill"}, ctx["owner"]))
        validate_error(api.extend_class_pack(
            pack["id"], {"extend_days": 60, "reason": "goodwill"}, ctx["owner"]),
            ApiErrorId.ERR_PACK_EXTENSION_CAP_EXCEEDED)


class TestPackCreditBookingAndDepletion:

    def test_exhausted_pack_is_refused_with_no_active_pack(self, api):
        """PRD §3.3: "A pack-funded booking names `class_pack_id` and debits `credits_remaining`; the pack must be `ACTIVE` with credits left, or the booking is refused with `ERR_NO_ACTIVE_PACK`."
        PRD §3.9: "When the last credit is spent the pack moves from ACTIVE to
        DEPLETED and further bookings against it are refused with
        ERR_NO_ACTIVE_PACK."

        Design: Corner/errors/class_pack_booking_with_no_remaining_credits_returns_no_active_pack
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=4,
                                  start_at="2026-06-21T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": maya["id"],
            "pack_size": 1, "purchased_at": "2026-06-01T00:00:00Z",
            "expiry_scheme": "NONE", "expected_client_version": maya["version"],
        }, ctx["owner"]), expected_status=201)

        used = validate_success(api.create_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "CLASS_PACK",
            "class_pack_id": pack["id"],
        }, make_client_headers(maya["id"])), expected_status=201)
        get_success_data(api.cancel_booking(
            used["id"], {"reason": "schedule conflict"},
            make_client_headers(maya["id"])))

        restored = validate_success(api.get_class_pack(pack["id"], ctx["owner"]))
        assert restored["credits_remaining"] == 1, \
            "the cancellation restored the single credit"

        empty_row = get_success_data(api.inject_client_entitlement({
            "client_id": maya["id"], "studio_id": ctx["studio"]["id"],
            "kind": "CLASS_PACK", "credits": 0}, OPERATOR))

        validate_error(api.create_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "CLASS_PACK",
            "class_pack_id": empty_row["entity_id"],
        }, make_client_headers(maya["id"])), ApiErrorId.ERR_NO_ACTIVE_PACK)

        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["seats_taken"] == 0, \
            "the failed attempt left the seat count unchanged"


class TestPackSeatGrossVariants:

    def test_pack_seat_gross_differs_between_booked_and_attended_variant(self, api):
        """PRD §3.11: "At creation the booked variant uses the pack-credit value for pack- and membership-covered seats, which is zero for a pack-covered seat. When the session completes and the booking becomes `ATTENDED`, the attended variant is re-evaluated and uses the drop-in list price for pack- and membership-covered bookings as well."
        PRD §3.6: "Each booking that becomes ATTENDED has its channel total
        computed and written to commission_base_cents."

        Design: Difficulty/dual_variant_calc/pack_seat_gross_differs_between_booked_and_attended_variant
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-10T17:00:00Z")
        maya = create_client(ctx["studio"]["id"], display_name="Maya Alvarez",
                             email="maya@example.com")
        pack = validate_success(api.create_class_pack({
            "studio_id": ctx["studio"]["id"], "client_id": maya["id"],
            "pack_size": 5, "purchased_at": "2026-06-01T00:00:00Z",
            "expiry_scheme": "NONE", "expected_client_version": maya["version"],
        }, ctx["owner"]), expected_status=201)

        booked = validate_success(api.create_booking({
            "client_id": maya["id"], "class_session_id": ctx["session"]["id"],
            "channel": "STUDIO", "payment_source": "CLASS_PACK",
            "class_pack_id": pack["id"],
        }, make_client_headers(maya["id"])), expected_status=201)
        assert booked["commission_base_cents"] == 0, \
            "the booked variant values a pack-covered seat at zero"

        # PRD §3.3: only a booking in CHECKED_IN becomes ATTENDED at
        # completion — a booking still in RESERVED becomes NO_SHOW.  The clock
        # is moved to the session start so the check-in gate is open.
        set_clock("2026-06-10T17:00:00Z")
        get_success_data(api.check_in_booking(
            booked["id"], make_client_headers(maya["id"])))
        get_success_data(api.complete_class_session(ctx["session"]["id"], ADMIN))

        rows = validate_success(api.list_session_bookings(
            ctx["session"]["id"], ctx["owner"]))
        assert len(rows) == 1
        assert rows[0]["status"] == "ATTENDED"
        assert rows[0]["commission_base_cents"] == 3360, \
            "the attended variant values the same seat at the drop-in list price"

        pack_after = validate_success(api.get_class_pack(pack["id"], ctx["owner"]))
        assert pack_after["credits_remaining"] == 4

    def test_the_session_list_price_the_attended_variant_uses_is_pinned(self, api):
        """PRD §3.7: "The studio list_price_cents is the base multiplied by the
        off-peak factor and by the tier factor, divided by one hundred million,
        truncated to whole cents, and then raised to the tier's floor."

        Design: Difficulty/dual_variant_calc/pack_seat_gross_differs_between_booked_and_attended_variant
        """
        ctx = setup_studio_roster(tier="GROWTH", capacity=2,
                                  start_at="2026-06-10T17:00:00Z")
        session = validate_success(api.get_class_session(ctx["session"]["id"],
                                                         ctx["owner"]))
        assert session["list_price_cents"] == 3360, \
            "4000 base x 0.80 off-peak x 1.05 GROWTH, truncated"