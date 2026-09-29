"""Compensating writes that must leave stored counters and ledgers matching a recount."""

from __future__ import annotations

from test_helpers import (
    AUTH_STATUS_APPROVED,
    AUTH_STATUS_REVOKED,
    CASE_STATUS_RESCHEDULED,
    CASE_STATUS_SCHEDULED,
    COMPLEXITY_COMPLEX,
    COVERAGE_COVERED,
    COVERAGE_NOT_REQUIRED,
    FEE_STATUS_ASSESSED,
    FEE_STATUS_REVERSED,
    LOANER_STATUS_DELIVERED_LATE,
    LOANER_STATUS_DELIVERED_ON_TIME,
    POSTURE_COMPLIANT,
    READINESS_NOT_APPLICABLE,
    approved_authorization,
    approved_product,
    assert_instant_equals,
    assert_integer_field,
    assert_money_cents,
    assert_total_count,
    authorization_revoke_payload,
    create_case,
    create_facility,
    create_vendor,
    credentialed_rep,
    find_by_id,
    list_rows_and_meta,
    read_authorization,
    read_case,
    read_loaner_set,
    read_vendor,
    read_vendor_rep,
    receive_loaner_set,
    register_loaner_set,
    reschedule_payload,
    COMPLIANCE_ADMIN,
    OR_COORDINATOR,
    REVOKED_REASON_MANUAL,
    REVOKED_REASON_NONE,
    validate_success,
)


class TestRevocationConservesAuthorizationCounters:
    """One manual revocation hands back exactly the slot its approval consumed."""

    @staticmethod
    def _setup(api):
        """Two consecutive shoulder cases, both covered by the same credentialed rep."""
        facility = create_facility(
            api, "IV-17", name="Inverness Valley Hospital",
            spd_turnaround_hours=6, spd_bay_count=2,
        )
        vendor = create_vendor(api, "INVAR", legal_name="Invariant Surgical Supply Co")
        rep = credentialed_rep(
            api,
            vendor["id"],
            "Ken Sato",
            issued_at_utc="2026-07-01T00:00:00Z",
            expires_at_utc="2027-07-01T00:00:00Z",
        )
        assert rep["credential_posture"] == POSTURE_COMPLIANT
        case_one = create_case(
            api,
            facility["id"],
            "CASE-11001",
            "2026-09-05T08:00:00Z",
            "2026-09-05T10:00:00Z",
            procedure_name="Shoulder Scope Day One",
        )
        case_two = create_case(
            api,
            facility["id"],
            "CASE-11002",
            "2026-09-06T08:00:00Z",
            "2026-09-06T10:00:00Z",
            procedure_name="Shoulder Scope Day Two",
        )
        auth_one = approved_authorization(api, case_one["id"], rep["id"])
        auth_two = approved_authorization(api, case_two["id"], rep["id"])
        return vendor, rep, case_one, case_two, auth_one, auth_two

    @staticmethod
    def _revoke(api, auth_id):
        """Withdraw one approved authorization, letting the reason default on the server."""
        return validate_success(
            api.revoke_authorization(
                auth_id, authorization_revoke_payload(), OR_COORDINATOR
            ),
            200,
        )

    def test_revocation_hands_back_the_slot_it_consumed(self, api):
        """Withdrawing the first day's badge undoes all three increments its approval made.

        "Revocation requires the authorization to be `APPROVED`, moves it
        `APPROVED → REVOKED`, leaves `decided_at_utc` as the approval left it,
        decrements the vendor's `authorizations_used_epoch`, the
        representative's `open_authorization_count` and the case's
        `approved_rep_count` — each floored at zero — increments the case's
        `revoked_authorization_count`".

        Design: Difficulty/compensating_invariant/revocation_conserves_authorization_counters_against_recount
        """
        vendor, rep, case_one, _case_two, auth_one, auth_two = self._setup(api)

        before = read_vendor(api, vendor["id"])
        assert_integer_field(before, "authorizations_used_epoch", 2)

        self._revoke(api, auth_one["id"])

        withdrawn = read_authorization(api, auth_one["id"])
        assert withdrawn["status"] == AUTH_STATUS_REVOKED
        assert withdrawn["revoked_reason"] == REVOKED_REASON_MANUAL

        surviving = read_authorization(api, auth_two["id"])
        assert surviving["status"] == AUTH_STATUS_APPROVED
        assert surviving["revoked_reason"] == REVOKED_REASON_NONE
        assert_integer_field(surviving, "epoch_number", 0)

        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "authorizations_used_epoch", 1)
        assert_integer_field(stored_vendor, "last_sweep_epoch", 0)
        assert_integer_field(stored_vendor, "adjudicated_compliance_score", 100)

        stored_rep = read_vendor_rep(api, rep["id"])
        assert_integer_field(stored_rep, "open_authorization_count", 1)

        first_day = read_case(api, case_one["id"])
        assert_integer_field(first_day, "approved_rep_count", 0)
        assert_integer_field(first_day, "revoked_authorization_count", 1)

    def test_used_epoch_counter_equals_a_recount_of_the_approved_rows(self, api):
        """The vendor's used-authorization figure equals the rows still approved this epoch.

        "Revocation decrements the counter, so a revoked authorization hands its
        slot back." The counter is therefore recountable from the live roster:
        "Authorization listings may be narrowed by `surgical_case_id`, by
        `vendor_rep_id` and by `status`", and "The server stamps `epoch_number`
        with the vendor's current `last_sweep_epoch`, which scopes this row to
        the quota epoch it consumes."

        Design: Difficulty/compensating_invariant/revocation_conserves_authorization_counters_against_recount
        """
        vendor, rep, _case_one, _case_two, auth_one, auth_two = self._setup(api)

        self._revoke(api, auth_one["id"])

        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "authorizations_used_epoch", 1)

        approved_rows, approved_meta = list_rows_and_meta(
            api.list_authorizations(
                COMPLIANCE_ADMIN,
                {"vendor_rep_id": rep["id"], "status": AUTH_STATUS_APPROVED},
            )
        )
        assert_total_count(approved_meta, 1)
        assert approved_meta["total_count"] == stored_vendor["authorizations_used_epoch"], (
            "the stored used-authorization counter should equal a recount of the "
            "representative's rows that are still approved"
        )

        recounted = find_by_id(approved_rows, auth_two["id"])
        assert_integer_field(recounted, "epoch_number", stored_vendor["last_sweep_epoch"])

        every_row, every_meta = list_rows_and_meta(
            api.list_authorizations(COMPLIANCE_ADMIN, {"vendor_rep_id": rep["id"]})
        )
        assert_total_count(every_meta, 2)
        assert len(every_row) == 2, "both authorizations remain on file as history"
        assert every_meta["total_count"] != stored_vendor["authorizations_used_epoch"], (
            "counting every historical row would overstate the epoch's consumption"
        )

    def test_the_second_day_case_does_not_drift_when_the_first_is_withdrawn(self, api):
        """Withdrawing day one leaves day two covered and recountable in its own right.

        "If the case does not require an implant and there are no approved
        authorizations, the posture is `NOT_REQUIRED`", whereas on a case that
        still holds cover and has never lost any, "Otherwise the posture is
        `COVERED`."

        Design: Difficulty/compensating_invariant/revocation_conserves_authorization_counters_against_recount
        """
        _vendor, _rep, case_one, case_two, auth_one, auth_two = self._setup(api)

        self._revoke(api, auth_one["id"])

        first_day = read_case(api, case_one["id"])
        assert first_day["vendor_coverage_status"] == COVERAGE_NOT_REQUIRED
        assert_integer_field(first_day, "approved_rep_count", 0)
        assert_integer_field(first_day, "revoked_authorization_count", 1)

        second_day = read_case(api, case_two["id"])
        assert second_day["vendor_coverage_status"] == COVERAGE_COVERED
        assert_integer_field(second_day, "approved_rep_count", 1)
        assert_integer_field(second_day, "revoked_authorization_count", 0)

        rows, meta = list_rows_and_meta(
            api.list_authorizations(
                COMPLIANCE_ADMIN,
                {"surgical_case_id": case_two["id"], "status": AUTH_STATUS_APPROVED},
            )
        )
        assert_total_count(meta, 1)
        assert meta["total_count"] == second_day["approved_rep_count"], (
            "the second day's approved-rep counter should equal a recount of its "
            "own approved authorizations"
        )
        find_by_id(rows, auth_two["id"])


class TestFeeReversalConservesVendorLedger:
    """A reschedule reverses one of two identical late fees and the ledger re-sums."""

    @staticmethod
    def _setup(api):
        """Two identical nine-tray sets, each 37 minutes late for 1125 cents."""
        facility = create_facility(
            api, "LG-18", name="Ledgerport Surgical Hospital",
            spd_turnaround_hours=8, spd_bay_count=3,
        )
        vendor = create_vendor(api, "LEDGR", legal_name="Ledger Medical Instruments Ltd")
        _pir, product = approved_product(
            api,
            vendor["id"],
            facility["id"],
            "UR-500",
            150000,
            is_implant=False,
            product_name="Universal Retractor Frame",
            manufacturer="Ledger Medical",
        )
        case_one = create_case(
            api,
            facility["id"],
            "CASE-11101",
            "2026-09-12T14:00:00Z",
            "2026-09-12T18:00:00Z",
            procedure_name="Open Reduction Day One",
        )
        set_one = register_loaner_set(
            api, vendor["id"], case_one["id"], product["id"], 9, COMPLEXITY_COMPLEX
        )
        case_two = create_case(
            api,
            facility["id"],
            "CASE-11102",
            "2026-09-13T14:00:00Z",
            "2026-09-13T18:00:00Z",
            procedure_name="Open Reduction Day Two",
        )
        set_two = register_loaner_set(
            api, vendor["id"], case_two["id"], product["id"], 9, COMPLEXITY_COMPLEX
        )

        received_one = receive_loaner_set(api, set_one["id"], "2026-09-11T23:37:00Z")
        assert received_one["status"] == LOANER_STATUS_DELIVERED_LATE
        assert received_one["fee_status"] == FEE_STATUS_ASSESSED
        received_two = receive_loaner_set(api, set_two["id"], "2026-09-12T23:37:00Z")
        assert received_two["status"] == LOANER_STATUS_DELIVERED_LATE
        assert received_two["fee_status"] == FEE_STATUS_ASSESSED

        loaded = read_vendor(api, vendor["id"])
        assert_money_cents(loaded, "late_fee_balance_cents", 2250)
        return vendor, product, case_one, case_two, set_one, set_two

    @staticmethod
    def _move_day_one_later(api, case_id):
        """Push the first case four hours later, which relieves its tray set of lateness."""
        return validate_success(
            api.reschedule_surgical_case(
                case_id,
                reschedule_payload("2026-09-12T18:00:00Z", "2026-09-12T22:00:00Z"),
                OR_COORDINATOR,
            ),
            200,
        )

    def test_reschedule_reverses_one_fee_and_debits_the_ledger_by_exactly_that_amount(self, api):
        """The moved case's fee is reversed while its historical amount stands on the row.

        "if `fee_status` was `ASSESSED` it becomes `REVERSED` and the vendor's
        `late_fee_balance_cents` is debited by that set's
        `assessed_late_fee_cents` — the amount itself being retained as the
        historical assessment".

        Design: Difficulty/compensating_invariant/fee_reversal_conserves_vendor_ledger_against_resum
        """
        vendor, _product, case_one, _case_two, set_one, _set_two = self._setup(api)

        self._move_day_one_later(api, case_one["id"])

        moved = read_case(api, case_one["id"])
        assert moved["status"] == CASE_STATUS_RESCHEDULED
        assert_integer_field(moved, "reschedule_count", 1)
        assert_instant_equals(
            moved["original_scheduled_start_utc"],
            "2026-09-12T14:00:00Z",
            "original_scheduled_start_utc",
        )
        assert moved["implant_readiness_status"] == READINESS_NOT_APPLICABLE

        relieved = read_loaner_set(api, set_one["id"])
        assert_instant_equals(
            relieved["required_delivery_deadline_utc"],
            "2026-09-12T03:00:00Z",
            "required_delivery_deadline_utc",
        )
        assert_instant_equals(
            relieved["pinned_deadline_utc"],
            "2026-09-11T23:00:00Z",
            "pinned_deadline_utc",
        )
        assert_integer_field(relieved, "late_minutes_current_basis", 0)
        assert_integer_field(relieved, "late_minutes_pinned_basis", 37)
        assert relieved["status"] == LOANER_STATUS_DELIVERED_ON_TIME
        assert relieved["fee_status"] == FEE_STATUS_REVERSED
        assert_money_cents(relieved, "assessed_late_fee_cents", 1125)

        stored_vendor = read_vendor(api, vendor["id"])
        assert_money_cents(stored_vendor, "late_fee_balance_cents", 1125)

    def test_late_fee_balance_equals_a_resum_over_the_sets_still_assessed(self, api):
        """The ledger matches the sum over assessed rows, not the sum over every row.

        "only sets whose `fee_status` is `ASSESSED` contribute to the vendor's
        `late_fee_balance_cents`, which is defined as the sum of
        `assessed_late_fee_cents` over that vendor's sets in that state."

        Design: Difficulty/compensating_invariant/fee_reversal_conserves_vendor_ledger_against_resum
        """
        vendor, product, case_one, _case_two, _set_one, set_two = self._setup(api)

        self._move_day_one_later(api, case_one["id"])

        every_row, every_meta = list_rows_and_meta(
            api.list_loaner_sets(COMPLIANCE_ADMIN, {"approved_product_id": product["id"]})
        )
        assert_total_count(every_meta, 2)

        resum = sum(
            row["assessed_late_fee_cents"]
            for row in every_row
            if row["fee_status"] == FEE_STATUS_ASSESSED
        )
        naive_resum = sum(row["assessed_late_fee_cents"] for row in every_row)
        assert resum == 1125, "one of the two identical fees survives the reversal"
        assert naive_resum == 2250, (
            "both rows still carry their historical assessment, so summing every "
            "row would overstate the ledger"
        )

        stored_vendor = read_vendor(api, vendor["id"])
        assert_money_cents(stored_vendor, "late_fee_balance_cents", resum)
        assert stored_vendor["late_fee_balance_cents"] != naive_resum, (
            "the ledger counts only the rows whose fee is still assessed"
        )

        assessed_rows, assessed_meta = list_rows_and_meta(
            api.list_loaner_sets(
                COMPLIANCE_ADMIN,
                {"approved_product_id": product["id"], "fee_status": FEE_STATUS_ASSESSED},
            )
        )
        assert_total_count(assessed_meta, 1)
        assert_money_cents(
            find_by_id(assessed_rows, set_two["id"]), "assessed_late_fee_cents", 1125
        )

    def test_the_second_days_set_and_the_late_delivery_penalty_do_not_drift(self, api):
        """Only the untouched set still counts as a late delivery against the score.

        "The late-delivery penalty is five points for each of that vendor's
        loaner sets whose `status` is `DELIVERED_LATE` or `REJECTED_LATE` **and**
        whose `fee_status` is not `REVERSED`."

        Design: Difficulty/compensating_invariant/fee_reversal_conserves_vendor_ledger_against_resum
        """
        vendor, _product, case_one, case_two, _set_one, set_two = self._setup(api)

        self._move_day_one_later(api, case_one["id"])

        untouched = read_loaner_set(api, set_two["id"])
        assert untouched["status"] == LOANER_STATUS_DELIVERED_LATE
        assert untouched["fee_status"] == FEE_STATUS_ASSESSED
        assert_money_cents(untouched, "assessed_late_fee_cents", 1125)
        assert_integer_field(untouched, "late_minutes_current_basis", 37)
        assert_integer_field(untouched, "late_minutes_pinned_basis", 37)
        assert_instant_equals(
            untouched["required_delivery_deadline_utc"],
            "2026-09-12T23:00:00Z",
            "required_delivery_deadline_utc",
        )

        second_day = read_case(api, case_two["id"])
        assert second_day["status"] == CASE_STATUS_SCHEDULED
        assert_integer_field(second_day, "reschedule_count", 0)
        assert second_day["implant_readiness_status"] == READINESS_NOT_APPLICABLE

        stored_vendor = read_vendor(api, vendor["id"])
        assert_integer_field(stored_vendor, "adjudicated_compliance_score", 95)
        assert_money_cents(stored_vendor, "late_fee_balance_cents", 1125)
