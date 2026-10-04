"""Settlement windows, funds-transfer lines, and net position tests."""
from test_helpers import (
    ApiErrorId,
    create_active_member,
    create_draft_line,
    create_open_window,
    create_settlement_window,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_member_headers

SO = TEST_USERS["settlement_operator_headers"]


def _two_members(api):
    m1 = create_active_member(legal_name="B1", member_kind="BOTH", region="NA")
    m2 = create_active_member(legal_name="B2", member_kind="BOTH", region="NA")
    return m1, m2


class TestWindowCardinality:
    def test_settlement_single_open_window_cardinality(self, api):
        """PRD §3.9: "Opening a window requires the logical clock to have
        reached `opens_at` and — critically — requires that no other window is
        currently `OPEN`: the network operates strictly one open window at a
        time, and an attempt to open a second is rejected with
        `ERR_WINDOW_NOT_OPEN`."

        Design: Difficulty/resource_temporal_overlap/settlement_single_open_window_cardinality
        """
        w1 = create_open_window(window_date="2026-09-01",
                                opens_at="2026-08-31T23:00:00Z",
                                closes_at="2026-09-02T00:00:00Z")
        # W2's interval lies entirely in the future and does not overlap W1.
        w2 = create_settlement_window(window_date="2026-09-05",
                                      opens_at="2026-09-05T00:00:00Z",
                                      closes_at="2026-09-06T00:00:00Z")
        res = api.open_settlement_window(w2["id"], SO)
        validate_error(res, ApiErrorId.ERR_WINDOW_NOT_OPEN)
        assert get_success_data(
            api.get_settlement_window(w2["id"], SO))["status"] == "SCHEDULED"
        assert get_success_data(
            api.get_settlement_window(w1["id"], SO))["status"] == "OPEN"

    def test_second_window_opens_after_first_reconciled(self, api):
        """PRD §3.9: "the network operates strictly one open window at a
        time".
        PRD §3.9: "Reconciliation moves it from `OPEN` to `RECONCILED`".

        Design: Difficulty/resource_temporal_overlap/settlement_single_open_window_cardinality
        """
        w1 = create_open_window(window_date="2026-09-01",
                                opens_at="2026-08-31T23:00:00Z",
                                closes_at="2026-09-02T00:00:00Z")
        validate_success(api.reconcile_settlement_window(w1["id"], SO))
        w2 = create_settlement_window(window_date="2026-09-05",
                                      opens_at="2026-09-05T00:00:00Z",
                                      closes_at="2026-09-06T00:00:00Z")
        set_clock("2026-09-05T00:00:00Z")
        data = validate_success(api.open_settlement_window(w2["id"], SO))
        assert data["status"] == "OPEN"


class TestReconciliation:
    def test_settlement_reconcile_blocked_by_single_draft_line(self, api):
        """PRD §3.9: "Reconciliation moves it from `OPEN` to `RECONCILED` and
        is blocked while any line in the window remains in `DRAFT` — such an
        attempt is rejected with `ERR_DRAFT_LINES_REMAIN`; only windows whose
        lines are all `COMMITTED` or `REVERSED` reconcile."

        Design: Difficulty/boundary_precision_check/settlement_reconcile_blocked_by_single_draft_line
        """
        m1, m2 = _two_members(api)
        window = create_open_window()
        line = create_draft_line(window["id"], m1["id"], m2["id"], 1000)

        res = api.reconcile_settlement_window(window["id"], SO)
        validate_error(res, ApiErrorId.ERR_DRAFT_LINES_REMAIN)
        assert get_success_data(
            api.get_settlement_window(window["id"], SO))["status"] == "OPEN"

    def test_reconcile_succeeds_once_draft_line_committed(self, api):
        """PRD §3.9: "only windows whose lines are all `COMMITTED` or
        `REVERSED` reconcile."
        PRD §3.9: "the window's `total_settled_cents` increases by the same".

        Design: Difficulty/boundary_precision_check/settlement_reconcile_blocked_by_single_draft_line
        """
        m1, m2 = _two_members(api)
        window = create_open_window()
        line = create_draft_line(window["id"], m1["id"], m2["id"], 1000)
        validate_error(api.reconcile_settlement_window(window["id"], SO),
                       ApiErrorId.ERR_DRAFT_LINES_REMAIN)

        validate_success(api.commit_settlement_line(line["id"], SO))
        data = validate_success(api.reconcile_settlement_window(window["id"],
                                                                SO))
        assert data["status"] == "RECONCILED"
        assert data["total_settled_cents"] == 1000


class TestCommitTimingAndFiscal:
    def test_commit_outside_window_time_rejected(self, api):
        """PRD §3.9: "Committing a line requires the line to be `DRAFT`, the
        window to be `OPEN` — otherwise `ERR_WINDOW_NOT_OPEN` — and the
        current logical time to fall at or after `opens_at` and strictly
        before `closes_at`; a commit outside the window's bounds is rejected
        with `ERR_WINDOW_EXPIRED`."

        Design: Corner/endpoints/commit_outside_window_time_rejected
        """
        m1, m2 = _two_members(api)
        window = create_open_window()
        line = create_draft_line(window["id"], m1["id"], m2["id"], 100)
        set_clock("2026-09-03T00:00:00Z")
        res = api.commit_settlement_line(line["id"], SO)
        validate_error(res, ApiErrorId.ERR_WINDOW_EXPIRED)
        current = get_success_data(api.get_settlement_line(line["id"], SO))
        assert current["status"] == "DRAFT"

    def test_settlement_fiscal_self_transfer_rejected(self, api):
        """PRD §3.9: "Fiscal rules are enforced at both drafting and commit:
        the amount must be strictly positive, payer and receiver must differ,
        and both members must be `ACTIVE`; any violation is rejected with
        `ERR_SETTLEMENT_INVALID`."

        Design: Corner/validations/settlement_fiscal_self_transfer_rejected
        """
        m1 = create_active_member(legal_name="B", member_kind="BOTH",
                                  region="NA")
        window = create_settlement_window()
        res = api.create_settlement_line(
            {"window_id": window["id"], "from_member_id": m1["id"],
             "to_member_id": m1["id"], "amount_cents": 100, "currency": "USD",
             "reference": "x"}, SO)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_INVALID)


class TestPositions:
    def test_settlement_positions_sum_to_zero(self, api):
        """PRD §3.9: "For each member with lines in the window, the net
        position in cents is the sum of `amount_cents` over `COMMITTED` lines
        where the member is the receiver, minus the sum over `COMMITTED` lines
        where the member is the payer; `DRAFT` and `REVERSED` lines are
        excluded in all cases. The positions are returned sorted by net amount
        ascending — largest debtor first — with ties broken by the member's
        `created_at` ascending, alongside a `total_check_cents` that must
        equal exactly zero".

        Design: Corner/calculations/settlement_positions_sum_to_zero
        """
        m1 = create_active_member(legal_name="B1")
        m2 = create_active_member(legal_name="B2")
        m3 = create_active_member(legal_name="B3")
        window = create_open_window()
        l1 = create_draft_line(window["id"], m1["id"], m2["id"], 5000,
                               reference="r1")
        validate_success(api.commit_settlement_line(l1["id"], SO))
        l2 = create_draft_line(window["id"], m3["id"], m1["id"], 2000,
                               reference="r2")
        validate_success(api.commit_settlement_line(l2["id"], SO))

        data = validate_success(api.get_window_positions(window["id"], SO))
        positions = data["positions"]
        # M1: +2000 (receives from M3) - 5000 (pays M2) = -3000
        # M2: +5000
        # M3: -2000
        nets = {p["member_id"]: p["net_cents"] for p in positions}
        assert nets[m1["id"]] == -3000
        assert nets[m2["id"]] == 5000
        assert nets[m3["id"]] == -2000
        assert [p["net_cents"] for p in positions] == [-3000, -2000, 5000], \
            "positions must be sorted by net ascending, largest debtor first"
        assert data["total_check_cents"] == 0


class TestCommitReverseConservation:
    def _setup_committed_line(self, api, amount=5000):
        m1, m2 = _two_members(api)
        window = create_open_window()
        line = create_draft_line(window["id"], m1["id"], m2["id"], amount)
        validate_success(api.commit_settlement_line(line["id"], SO))
        return m1, m2, window, line

    def test_settlement_commit_immediately_visible_in_balances(self, api):
        """PRD §3.9: "On commit, `committed_at` is stamped with the logical
        time, the line moves to `COMMITTED`, and three balances move together:
        the payer's `settled_balance_cents` decreases by `amount_cents`, the
        receiver's increases by the same, and the window's
        `total_settled_cents` increases by the same".

        Design: Corner/consistency_model/settlement_commit_immediately_visible_in_balances
        """
        m1, m2 = _two_members(api)
        window = create_open_window()
        line = create_draft_line(window["id"], m1["id"], m2["id"], 7000)
        data = validate_success(api.commit_settlement_line(line["id"], SO))
        assert data["status"] == "COMMITTED"
        assert get_success_data(
            api.get_member(m1["id"], SO))["settled_balance_cents"] == -7000
        assert get_success_data(
            api.get_member(m2["id"], SO))["settled_balance_cents"] == 7000

    def test_commit_then_reverse_restores_all_balances(self, api):
        """PRD §3.9: "Reversal is the mirror image, available on a `COMMITTED`
        line while its window is still `OPEN`: the payer is credited back, the
        receiver debited back, the window total decreased, and the line moves
        to the terminal `REVERSED` state, with the same three version
        increments."

        Design: Difficulty/compensating_invariant/settlement_commit_reverse_conserves_positions
        """
        m1, m2, window, line = self._setup_committed_line(api, 5000)
        # Mid-check: commit effects are visible before the compensating act.
        assert get_success_data(
            api.get_member(m1["id"], SO))["settled_balance_cents"] == -5000
        assert get_success_data(
            api.get_settlement_window(window["id"], SO)
        )["total_settled_cents"] == 5000

        data = validate_success(api.reverse_settlement_line(line["id"], SO))
        assert data["status"] == "REVERSED"
        assert get_success_data(
            api.get_member(m1["id"], SO))["settled_balance_cents"] == 0
        assert get_success_data(
            api.get_member(m2["id"], SO))["settled_balance_cents"] == 0
        assert get_success_data(
            api.get_settlement_window(window["id"], SO)
        )["total_settled_cents"] == 0

    def test_positions_total_check_zero_after_reversal(self, api):
        """PRD §3.9: "a `total_check_cents` that must equal exactly zero, the
        per-window invariant that the sum of all members' net positions is
        zero."
        PRD §3.9: "`DRAFT` and `REVERSED` lines are excluded in all cases."

        Design: Difficulty/compensating_invariant/settlement_commit_reverse_conserves_positions
        """
        m1, m2, window, line = self._setup_committed_line(api, 5000)
        validate_success(api.reverse_settlement_line(line["id"], SO))
        data = validate_success(api.get_window_positions(window["id"], SO))
        assert data["total_check_cents"] == 0
