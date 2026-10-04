"""Legal-entity governance and fund transfers: the direction matrix, pinned
fiscal check order, segregation of duties, caps, and balance conservation."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    set_clock, get_legal_entity, create_legal_entity_of_kind,
    request_transfer, approve_transfer_ok, setup_membership_and_foundation,
    create_household_with_term, make_governance_officer_headers,
    make_finance_controller_headers, create_fund_transfer_payload,
    assert_balance_conservation,
)

GOV = TEST_USERS["governance_officer_headers"]
FIN = TEST_USERS["finance_controller_headers"]


class TestSafetyPairBeatsFiscalBalance:
    def _setup_prohibited_underfunded_transfer(self):
        set_clock()
        foundation = create_legal_entity_of_kind(
            "FOUNDATION", 100, "Charitable Foundation")
        lobby = create_legal_entity_of_kind(
            "LOBBY_ARM", 5_000_000, "Advocacy Lobby Arm")
        transfer = request_transfer(
            foundation["id"], lobby["id"], 1_000_000, purpose="lobbying grant")
        return foundation, lobby, transfer

    def test_prohibited_pair_error_wins_over_balance_error(self, api):
        """PRD §2.8: "A request that would fail several rungs is rejected
        with the error from the earliest rung it fails." PRD §3.6: "Whether a
        direction is permitted at all is decided by a fixed governance
        matrix, and any pair not listed is prohibited with
        `ERR_PROHIBITED_ENTITY_PAIR` (HTTP 422)." PRD §3.6: "Everything else
        is prohibited: `FOUNDATION` → `LOBBY_ARM` (foundation money never
        funds lobbying), any transfer where the lobbying arm is the sender
        (the lobbying arm never sends), and any self-transfer from an entity
        to itself."

        Design: Difficulty/priority_pair_validation_conflict/safety_pair_beats_fiscal_balance
        """
        _fdn, _lob, transfer = self._setup_prohibited_underfunded_transfer()
        resp = api.decide_fund_transfer(transfer["id"], {"decision": "APPROVE"}, FIN)
        error = validate_error(resp, ApiErrorId.ERR_PROHIBITED_ENTITY_PAIR)
        assert resp.status_code == 422
        assert error["error_id"] == "ERR_PROHIBITED_ENTITY_PAIR"

    def test_rejected_pair_leaves_transfer_pending_and_balances_untouched(self, api):
        """PRD §3.6: "After creation, an entity's `balance_cents` is mutated
        only by executed fund transfers — there is no other balance-write
        path." PRD §3.6: "the request is created in `PENDING_APPROVAL` with
        `requested_by_user_id` recorded from the caller's `X-User-ID`."

        Design: Difficulty/priority_pair_validation_conflict/safety_pair_beats_fiscal_balance
        """
        fdn, lob, transfer = self._setup_prohibited_underfunded_transfer()
        resp = api.decide_fund_transfer(transfer["id"], {"decision": "APPROVE"}, FIN)
        validate_error(resp, ApiErrorId.ERR_PROHIBITED_ENTITY_PAIR)
        assert get_legal_entity(fdn["id"])["balance_cents"] == 100
        assert get_legal_entity(lob["id"])["balance_cents"] == 5_000_000
        rows, _meta = validate_paginated(
            api.list_entity_fund_transfers(fdn["id"], GOV))
        tx = next(r for r in rows if r["id"] == transfer["id"])
        assert tx["status"] == "PENDING_APPROVAL"


class TestFundTransferBalanceConservation:
    def _setup_at_cap_transfer(self):
        mo, fdn = setup_membership_and_foundation()
        # Per-transfer cap: round_down(0.05 * 200,000,000) = 10,000,000 —
        # exactly at the cap, admitted by the inclusive comparison.
        transfer = request_transfer(
            fdn["id"], mo["id"], 10_000_000,
            purpose="annual grant to membership org")
        return mo, fdn, transfer

    def test_execution_moves_balances_and_conserves_sum(self, api):
        """PRD §3.6: "An approved transfer lands in `EXECUTED`: the source
        entity's `balance_cents` decreases by `amount_cents`, the
        destination's increases by the same amount — balance conservation is
        the standing invariant — and the transfer records
        `from_balance_after_cents`, `to_balance_after_cents`,
        `decided_by_user_id`, and `executed_at` stamped from the logical
        clock". PRD §3.6: "an amount exactly at the cap passes, and anything
        above is `ERR_PER_TRANSFER_CAP_EXCEEDED` (HTTP 422)."

        Design: Difficulty/compensating_invariant/fund_transfer_balance_conservation
        """
        set_clock()
        mo, fdn, transfer = self._setup_at_cap_transfer()
        resp = api.decide_fund_transfer(transfer["id"], {"decision": "APPROVE"}, FIN)
        executed = validate_success(resp)
        assert executed["status"] == "EXECUTED"
        assert executed["from_balance_after_cents"] == 190_000_000
        assert executed["to_balance_after_cents"] == 110_000_000
        assert_balance_conservation(200_000_000, 100_000_000,
                                    executed["from_balance_after_cents"],
                                    executed["to_balance_after_cents"])

    def test_executed_balances_visible_on_entities_with_version_bump(self, api):
        """PRD §2.5: "Mutation cascades count as mutations of every resource
        they touch." PRD §2.5: "`version` (integer): a system-managed integer
        that increments by one on every mutation of the resource."

        Design: Difficulty/compensating_invariant/fund_transfer_balance_conservation
        """
        set_clock()
        mo, fdn, transfer = self._setup_at_cap_transfer()
        assert mo["version"] == 1
        assert fdn["version"] == 1
        approve_transfer_ok(transfer["id"])
        fdn_after = get_legal_entity(fdn["id"])
        mo_after = get_legal_entity(mo["id"])
        assert fdn_after["balance_cents"] == 190_000_000
        assert mo_after["balance_cents"] == 110_000_000
        assert fdn_after["version"] == 2
        assert mo_after["version"] == 2


class TestSegregationOfDuties:
    def test_self_approval_forbidden(self, api):
        """PRD §3.6: "Segregation of duties is enforced per transfer: the
        decider's `X-User-ID` must differ from the transfer's
        `requested_by_user_id`, on rejection with `ERR_SELF_APPROVAL`
        (HTTP 403), and this check guards both decisions — an officer may
        neither approve nor reject their own request."

        Design: Corner/validations/self_approval_forbidden
        """
        set_clock()
        mo, fdn = setup_membership_and_foundation()
        transfer = request_transfer(fdn["id"], mo["id"], 1_000_000,
                                    purpose="program grant", requester_id="gov-1")
        # A FinanceController carrying the requester's X-User-ID.
        resp = api.decide_fund_transfer(
            transfer["id"], {"decision": "APPROVE"},
            make_finance_controller_headers("gov-1"))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL)
        rows, _meta = validate_paginated(
            api.list_entity_fund_transfers(fdn["id"], GOV))
        tx = next(r for r in rows if r["id"] == transfer["id"])
        assert tx["status"] == "PENDING_APPROVAL"
        assert get_legal_entity(fdn["id"])["balance_cents"] == 200_000_000
        assert get_legal_entity(mo["id"])["balance_cents"] == 100_000_000

    def test_finance_controller_cannot_request_transfer(self, api):
        """PRD §2.10: "a `FinanceController` decides them but can never
        request one". PRD §2.1: "a caller whose role is not entitled to the
        endpoint or the requested action is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/finance_controller_cannot_request_transfer
        """
        set_clock()
        mo, fdn = setup_membership_and_foundation()
        payload = create_fund_transfer_payload(
            fdn["id"], mo["id"], amount_cents=1000, purpose="self-dealing probe")
        resp = api.create_fund_transfer(payload, FIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        rows, meta = validate_paginated(
            api.list_entity_fund_transfers(fdn["id"], GOV))
        assert len(rows) == 0
        assert meta["total_count"] == 0

    def test_approve_rejected_transfer_rejected(self, api):
        """PRD §3.6: "The segregation check runs before the transfer's state
        is examined; a decision attempted on a transfer no longer in
        `PENDING_APPROVAL` is rejected with `ERR_TRANSFER_STATE` (HTTP 409)."
        PRD §3.6: "Both outcomes are terminal."

        Design: Corner/state_machines/approve_rejected_transfer_rejected
        """
        set_clock()
        mo, fdn = setup_membership_and_foundation()
        transfer = request_transfer(fdn["id"], mo["id"], 5_000_000,
                                    purpose="grant request")
        rejected = validate_success(api.decide_fund_transfer(
            transfer["id"], {"decision": "REJECT"}, FIN))
        assert rejected["status"] == "REJECTED"

        resp = api.decide_fund_transfer(transfer["id"], {"decision": "APPROVE"}, FIN)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_STATE)
        assert get_legal_entity(fdn["id"])["balance_cents"] == 200_000_000
        assert get_legal_entity(mo["id"])["balance_cents"] == 100_000_000


class TestLobbyingAnnualCap:
    def test_lobbying_annual_cap_boundary(self, api):
        """PRD §3.6: "For `MEMBERSHIP_ORG` → `LOBBY_ARM`, the annual cap is
        measured against dues revenue: net dues year-to-date are the sum of
        `paid_cents` minus `refunded_cents` across all membership terms — of
        any status, with refunds netting out — whose `purchased_at` falls in
        the clock's calendar year, and the sum of this calendar year's
        `EXECUTED` membership-to-lobby transfers plus the requested amount
        may not exceed 20% of that figure, truncated down, on pain of
        `ERR_ANNUAL_CAP_EXCEEDED`."

        Design: Corner/calculations/lobbying_annual_cap_boundary
        """
        set_clock()
        # Two 5-year purchases in calendar 2026: net dues YTD = 12,800.
        create_household_with_term(
            state_code="MO", term_years=5, primary_full_name="Pam Poe",
            primary_date_of_birth="1966-06-06")
        create_household_with_term(
            state_code="MO", term_years=5, primary_full_name="Rex Rudd",
            primary_date_of_birth="1964-04-04")
        mo = create_legal_entity_of_kind("MEMBERSHIP_ORG", 100_000_000,
                                         "Membership Organization")
        lob = create_legal_entity_of_kind("LOBBY_ARM", 5_000_000,
                                          "Advocacy Lobby Arm")

        # round_down(0.20 * 12,800) = 2,560: exactly at the cap, executes.
        tx_a = request_transfer(mo["id"], lob["id"], 2560,
                                purpose="Q3 advocacy funding")
        executed = approve_transfer_ok(tx_a["id"])
        assert executed["status"] == "EXECUTED"
        assert executed["from_balance_after_cents"] == 99_997_440
        assert executed["to_balance_after_cents"] == 5_002_560

        tx_b = request_transfer(mo["id"], lob["id"], 1, purpose="one more cent")
        resp = api.decide_fund_transfer(tx_b["id"], {"decision": "APPROVE"}, FIN)
        validate_error(resp, ApiErrorId.ERR_ANNUAL_CAP_EXCEEDED)
        rows, _meta = validate_paginated(
            api.list_entity_fund_transfers(mo["id"], GOV))
        tx_b_row = next(r for r in rows if r["id"] == tx_b["id"])
        assert tx_b_row["status"] == "PENDING_APPROVAL"
