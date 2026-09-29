"""Pinned arithmetic order: the per-tray rounding step and the sweep's quota walk."""

from __future__ import annotations

from test_helpers import (
    BASE_QUOTA,
    COMPLEXITY_COMPLEX,
    FEE_STATUS_ASSESSED,
    INCIDENT_TYPE_GIFT_POLICY_VIOLATION,
    INCIDENT_TYPE_UNBADGED_ACCESS,
    LOANER_STATUS_DELIVERED_LATE,
    OUTCOME_SUBSTANTIATED,
    SEVERITY_CRITICAL,
    SEVERITY_MAJOR,
    STATUS_IN_GOOD_STANDING,
    STATUS_PROBATION,
    TIER_PLATINUM,
    TIER_PROBATION,
    ACCESS_STATUS_CREDENTIALED,
    POSTURE_COMPLIANT,
    COMPLIANCE_ADMIN,
    OR_COORDINATOR,
    adjudicate_incident,
    approved_authorization,
    approved_product,
    assert_instant_equals,
    assert_integer_field,
    assert_money_cents,
    compliance_score,
    compliance_status,
    create_case,
    create_facility,
    create_vendor,
    create_vendor_rep,
    credential_rep,
    late_fee_cents,
    loaner_deadline,
    next_quota,
    per_tray_late_charge_cents,
    read_loaner_set,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    report_incident,
    run_sweep,
    scorecard_tier,
    utilization_ratio,
)


class TestLateFeeRoundsPerTrayBeforeMultiplying:
    """Nine trays of complex instruments, thirty-seven minutes past the dock deadline."""

    @staticmethod
    def _setup(api):
        """A nine-tray COMPLEX set staged for a non-implant case at an eight-hour site."""
        facility = create_facility(
            api,
            "NW-04",
            name="Northwood Regional Hospital",
            spd_turnaround_hours=8,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "TRAUMX", legal_name="Traumax Instruments GmbH")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "DF-410",
            120000,
            is_implant=False,
            product_name="Distal Femur Plating Set",
            manufacturer="Traumax",
        )
        case = create_case(
            api,
            facility["id"],
            "CASE-9301",
            "2026-09-10T14:00:00Z",
            "2026-09-10T18:00:00Z",
            procedure_name="Distal Femur ORIF",
            implant_required=False,
        )
        loaner = register_loaner_set(
            api, vendor["id"], case["id"], product["id"], 9, COMPLEXITY_COMPLEX
        )
        return vendor, case, loaner

    def test_per_tray_charge_is_rounded_before_the_tray_count_multiplies_it(self, api):
        """Thirty-seven late minutes on nine complex trays assess 1125 cents, not 1124.

        "The per-tray late charge is rounded half up to a whole number of cents
        *before* it is multiplied by the tray count, never after." Rounding the
        per-tray figure of 124.875 cents up to 125 and then multiplying by nine
        trays gives 1125 cents; multiplying first and rounding the 1123.875-cent
        product would give 1124, so the two orders are told apart by one cent.

        Design: Difficulty/combinatorial_formula/late_fee_rounds_per_tray_before_multiplying_by_tray_count
        """
        _vendor, _case, loaner = self._setup(api)

        received = receive_loaner_set(api, loaner["id"], "2026-09-09T23:37:00Z")

        # Eight turnaround hours plus six for COMPLEX plus one tray surcharge for
        # nine trays lands the dock deadline fifteen hours before the knife.
        expected_deadline = loaner_deadline(
            "2026-09-10T14:00:00Z", 8, COMPLEXITY_COMPLEX, 9, False
        )
        assert_instant_equals(
            received["required_delivery_deadline_utc"],
            expected_deadline,
            "required_delivery_deadline_utc",
        )
        assert_instant_equals(
            received["required_delivery_deadline_utc"],
            "2026-09-09T23:00:00Z",
            "required_delivery_deadline_utc",
        )
        assert_instant_equals(
            received["pinned_deadline_utc"],
            "2026-09-09T23:00:00Z",
            "pinned_deadline_utc",
        )
        assert_integer_field(received, "late_minutes_current_basis", 37)
        assert_integer_field(received, "late_minutes_pinned_basis", 37)

        assert per_tray_late_charge_cents(37, COMPLEXITY_COMPLEX) == 125, (
            "the per-tray charge should round half up to a whole 125 cents"
        )
        assert_money_cents(
            received,
            "assessed_late_fee_cents",
            late_fee_cents(37, 9, COMPLEXITY_COMPLEX),
        )
        assert_money_cents(received, "assessed_late_fee_cents", 1125)
        assert received["assessed_late_fee_cents"] != 1124, (
            "multiplying the trays in before the rounding step is the wrong order"
        )

        stored = read_loaner_set(api, loaner["id"])
        assert_money_cents(stored, "assessed_late_fee_cents", 1125)

    def test_late_branch_and_the_vendor_ledger_carry_the_assessed_amount(self, api):
        """The tray set lands in DELIVERED_LATE and its fee reaches the vendor's balance.

        "When `late_minutes_current_basis` is greater than zero and at most 120 —
        the two-hour hard-reject grace — the set moves `EXPECTED →
        DELIVERED_LATE`, the late fee below is assessed, that fee is added to the
        vendor's `late_fee_balance_cents`, and both vendor compliance-score
        variants and the case's `implant_readiness_status` are recomputed."

        Design: Difficulty/combinatorial_formula/late_fee_rounds_per_tray_before_multiplying_by_tray_count
        """
        vendor, _case, loaner = self._setup(api)

        received = receive_loaner_set(api, loaner["id"], "2026-09-09T23:37:00Z")
        assert received["status"] == LOANER_STATUS_DELIVERED_LATE
        assert received["fee_status"] == FEE_STATUS_ASSESSED

        # "only sets whose fee_status is ASSESSED contribute to the vendor's
        # late_fee_balance_cents", so the single assessed set is the whole ledger.
        stored_vendor = read_vendor(api, vendor["id"])
        assert_money_cents(stored_vendor, "late_fee_balance_cents", 1125)

        # One late delivery that has not been reversed deducts five points from
        # the base of 100 in both score variants.
        assert_integer_field(
            stored_vendor,
            "adjudicated_compliance_score",
            compliance_score(late_delivery_count=1),
        )
        assert_integer_field(stored_vendor, "adjudicated_compliance_score", 95)
        assert_integer_field(stored_vendor, "provisional_compliance_score", 95)


class TestSweepTakesTheRatioBeforeResettingTheCounter:
    """Five approvals against a quota of four, then the scheduled reckoning."""

    @staticmethod
    def _setup(api):
        """One representative approved onto five consecutive days, carrying two findings."""
        facility = create_facility(
            api,
            "NG-03",
            name="Northgate Ambulatory Surgery",
            spd_turnaround_hours=6,
            spd_bay_count=2,
        )
        vendor = create_vendor(api, "CDLX", legal_name="Cardiolux Devices SA")
        rep = create_vendor_rep(api, vendor["id"], "Ira Vance")
        credential_rep(
            api,
            rep["id"],
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
        )

        # Five single-day theatre slots, so the five badge windows of 07:00 to
        # 10:30 never overlap and the double-booking test never fires.
        cases = []
        for day in range(1, 6):
            cases.append(
                create_case(
                    api,
                    facility["id"],
                    f"CASE-920{day}",
                    f"2026-09-0{day}T08:00:00Z",
                    f"2026-09-0{day}T10:00:00Z",
                    procedure_name=f"Pacemaker Generator Change {day}",
                )
            )
        for case in cases:
            approved_authorization(api, case["id"], rep["id"])

        critical = report_incident(
            api,
            cases[0]["id"],
            rep["id"],
            INCIDENT_TYPE_GIFT_POLICY_VIOLATION,
            SEVERITY_CRITICAL,
            headers=OR_COORDINATOR,
            narrative="Rep breached the sterile field during lead placement.",
        )
        adjudicate_incident(api, critical["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN)
        major = report_incident(
            api,
            cases[1]["id"],
            rep["id"],
            INCIDENT_TYPE_UNBADGED_ACCESS,
            SEVERITY_MAJOR,
            headers=OR_COORDINATOR,
            narrative="Badge reused after check-out.",
        )
        adjudicate_incident(api, major["id"], OUTCOME_SUBSTANTIATED, COMPLIANCE_ADMIN)
        return vendor, rep

    def test_ordinary_credentialing_work_leaves_the_quota_and_the_tier_alone(self, api):
        """Before the sweep the vendor reads 72 points on five used slots of a quota of four.

        "This is the **only** place in the system where `scorecard_tier`,
        `access_quota_in_effect`, `authorizations_used_epoch` and
        `compliance_status` may change; no ordinary endpoint may write them." The
        twenty-point critical finding and the eight-point major one are already
        deducted, while the over-utilization penalty is still held back because
        the ratio is refreshed only inside the rescoring phase.

        Design: Difficulty/combinatorial_formula/sweep_quota_tier_reset_pinned_evaluation_order
        """
        vendor, rep = self._setup(api)

        before = read_vendor(api, vendor["id"])
        assert_integer_field(
            before,
            "adjudicated_compliance_score",
            compliance_score(incident_weights=(20, 8)),
        )
        assert_integer_field(before, "adjudicated_compliance_score", 72)
        assert_integer_field(before, "provisional_compliance_score", 72)

        # Six approvals is the hard cap at a quota of four, so the fifth slot is
        # admitted and the counter legitimately sits above the nominal quota.
        assert_integer_field(before, "authorizations_used_epoch", 5)
        assert_integer_field(before, "access_quota_in_effect", BASE_QUOTA)
        assert before["scorecard_tier"] == TIER_PLATINUM
        assert before["compliance_status"] == STATUS_IN_GOOD_STANDING
        assert_integer_field(before, "last_sweep_epoch", 0)

        # Neither finding is unapproved product use, so the representative stands.
        stored_rep = read_vendor_rep(api, rep["id"])
        assert stored_rep["access_status"] == ACCESS_STATUS_CREDENTIALED
        assert stored_rep["credential_posture"] == POSTURE_COMPLIANT

    def test_sweep_rescores_on_the_pre_sweep_quota_and_drops_the_vendor_to_probation(
        self, api
    ):
        """The pre-sweep quota of four turns five used slots into a 1.25 ratio and 60 points.

        "First, take `quota_in_effect` as the vendor's `access_quota_in_effect`
        **as read before this sweep** — the pre-sweep value, never the value step
        six is about to write." Five over four is 1.25, strictly above one, so the
        twelve-point overage penalty applies on top of the twenty-eight points of
        substantiated findings, landing the vendor on 60 points, `TIER_PROBATION`
        and a shrunken allowance of one authorization.

        Design: Difficulty/combinatorial_formula/sweep_quota_tier_reset_pinned_evaluation_order
        """
        vendor, _rep = self._setup(api)

        run_sweep(api)

        after = read_vendor(api, vendor["id"])
        expected_ratio = utilization_ratio(5, BASE_QUOTA)
        assert expected_ratio == 1.25, "five slots against a quota of four is 1.25"
        expected_score = compliance_score(
            incident_weights=(20, 8), over_utilized=expected_ratio > 1
        )
        assert_integer_field(after, "adjudicated_compliance_score", expected_score)
        assert_integer_field(after, "adjudicated_compliance_score", 60)
        assert_integer_field(after, "provisional_compliance_score", 60)

        assert after["scorecard_tier"] == scorecard_tier(60)
        assert after["scorecard_tier"] == TIER_PROBATION
        assert after["compliance_status"] == compliance_status(60)
        assert after["compliance_status"] == STATUS_PROBATION

        # Forty per cent of the pre-sweep quota of four floors to one.
        assert_integer_field(
            after, "access_quota_in_effect", next_quota(BASE_QUOTA, TIER_PROBATION)
        )
        assert_integer_field(after, "access_quota_in_effect", 1)

        assert after["adjudicated_compliance_score"] != 72, (
            "reading the quota after step six would leave the overage penalty off"
        )
        assert after["scorecard_tier"] != "TIER_STANDARD", (
            "a 72-point vendor would have held its tier instead of dropping"
        )

    def test_epoch_counter_resets_only_after_the_ratio_has_been_taken_from_it(self, api):
        """The counter reads zero while the score it fed still carries the overage penalty.

        "Seventh, and only now, reset `authorizations_used_epoch` to 0: the epoch
        reset happens **after** the ratio in step two has already been taken from
        it, so resetting earlier would make every ratio zero." A zeroed counter
        beside a 60-point score is only jointly reachable in that order, and the
        fresh epoch stamp re-scopes the counter to the epoch just opened.

        Design: Difficulty/combinatorial_formula/sweep_quota_tier_reset_pinned_evaluation_order
        """
        vendor, _rep = self._setup(api)

        sweep = run_sweep(api)

        assert_integer_field(sweep, "epoch_number", 1)
        assert_integer_field(sweep, "previous_epoch_number", 0)
        # "Every vendor row is rescored on every sweep ... and
        # vendors_rescored_count therefore always equals the total number of vendors."
        assert_integer_field(sweep, "vendors_rescored_count", 1)
        # Nothing else was due at this instant: the credentials run to 2027 and
        # the representative's posture never fell to LAPSED.
        assert_integer_field(sweep, "credentials_expired_count", 0)
        assert_integer_field(sweep, "credentials_warned_count", 0)
        assert_integer_field(sweep, "reps_suspended_count", 0)
        assert_integer_field(sweep, "authorizations_revoked_count", 0)

        after = read_vendor(api, vendor["id"])
        assert_integer_field(after, "authorizations_used_epoch", 0)
        assert_integer_field(after, "last_sweep_epoch", 1)
        assert_integer_field(after, "adjudicated_compliance_score", 60)
        assert after["adjudicated_compliance_score"] == 100 - 20 - 8 - 12, (
            "the twelve-point overage penalty proves the ratio predated the reset"
        )
