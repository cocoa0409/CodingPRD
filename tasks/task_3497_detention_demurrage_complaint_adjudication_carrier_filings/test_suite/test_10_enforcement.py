"""Enforcement proceedings: determination gates, the pinned civil-penalty
formula, compliance-score adjustment, and the suspension cascade through
tariffs, invoices, and disputes."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    determine_proceeding,
    issue_invoice,
    make_carrier_rep_headers,
    mark_paid,
    open_dispute,
    open_proceeding,
    set_logical_clock,
    setup_published_tariff,
    setup_standard_billing,
    setup_suspended_carrier_with_pending_dispute,
    validate_error,
    validate_paginated,
    validate_success,
)

DOCKET = TEST_USERS["docket_headers"]


def _carrier(carrier_id):
    return api_client.get_carrier(carrier_id, DOCKET).json()["data"]


class TestDeterminationGate:
    def test_enforcement_determine_twice_returns_not_notice_issued(self):
        """PRD §3.9: "Determination belongs to an `AdministrativeLawJudge` and
        only while the proceeding stands in `NOTICE_ISSUED` — otherwise
        `ERR_PROCEEDING_NOT_NOTICE_ISSUED` (HTTP 409)." and "A no-violation
        determination moves the proceeding to `DISMISSED` with no penalty and no
        score consequence; `penalty_cents` and `score_delta` remain unset."

        Design: Corner/state_machines/enforcement_determine_twice_returns_not_notice_issued
        """
        env = setup_published_tariff()
        cid = env["carrier"]["id"]
        proceeding = open_proceeding(cid, basis="TARIFF_VIOLATION")
        dismissed = determine_proceeding(proceeding["id"], "NO_VIOLATION")
        assert dismissed["proceeding_status"] == "DISMISSED"

        resp = api_client.determine_proceeding(proceeding["id"], {
            "determination": "VIOLATION_FOUND", "violation_count": 9,
            "willful": True}, TEST_USERS["alj_headers"])
        validate_error(resp, ApiErrorId.ERR_PROCEEDING_NOT_NOTICE_ISSUED)

        after = api_client.get_proceeding(proceeding["id"], DOCKET).json()["data"]
        assert after["proceeding_status"] == "DISMISSED"
        assert after.get("penalty_cents") is None
        assert after.get("score_delta") is None
        assert _carrier(cid)["compliance_score"] == 1000


class TestCivilPenaltyFormula:
    def _penalty_probe(self):
        env = setup_published_tariff(carrier_name="Penalty Probe Lines")
        cid = env["carrier"]["id"]
        p1 = open_proceeding(cid, basis="TARIFF_VIOLATION")
        d1 = determine_proceeding(p1["id"], "VIOLATION_FOUND",
                                  violation_count=5, willful=False)
        p2 = open_proceeding(cid, basis="TARIFF_VIOLATION")
        d2 = determine_proceeding(p2["id"], "VIOLATION_FOUND",
                                  violation_count=30, willful=True)
        return env, d1, d2

    def test_civil_penalty_stacks_willful_repeat_and_cap_inputs(self):
        """PRD §3.9: "The civil penalty then assembles in a pinned evaluation
        order. The base is `violation_count` times 1,000,000 cents per violation;
        a willful violation doubles the base; a repeat offender multiplies the
        running figure by three-halves in exact integer arithmetic — multiply by
        three, then divide by two; and the result is capped at 100,000,000 cents
        per proceeding."
        PRD §3.9: "At the determination instant the server fixes
        `repeat_offender`: it is true exactly when another proceeding against the
        same carrier already stands in `DETERMINED` with a violation found".

        Design: Difficulty/combinatorial_formula/civil_penalty_stacks_willful_repeat_and_cap_inputs
        """
        _env, d1, d2 = self._penalty_probe()
        assert d1["penalty_cents"] == 5_000_000, "5 x 1000000, no multipliers"
        assert d1["repeat_offender"] is False, "first determination"
        assert d2["penalty_cents"] == 90_000_000, (
            "30 x 1000000 x 2 willful x 1.5 repeat, under the 100000000 cap")
        assert d2["repeat_offender"] is True
        assert d2["score_delta"] == -250, "non-UNREASONABLE_PRACTICE: min(50x30, 250)"

    def test_civil_penalty_accumulates_on_carrier_and_suspends_below_600(self):
        """PRD §3.9: "On the carrier, `cumulative_civil_penalties_cents` grows by
        the penalty and `compliance_score` absorbs the `score_delta` without ever
        falling below zero; if the deduction leaves the score below 600, the full
        suspension cascade of §2.10 fires."

        Design: Difficulty/combinatorial_formula/civil_penalty_stacks_willful_repeat_and_cap_inputs
        """
        env, _d1, _d2 = self._penalty_probe()
        carrier = _carrier(env["carrier"]["id"])
        assert carrier["cumulative_civil_penalties_cents"] == 95_000_000
        assert carrier["compliance_score"] == 500, "1000 - 250 - 250"
        assert carrier["status"] == "SUSPENDED", "500 < 600"

    def test_carrier_derived_totals_reconcile_after_two_determinations(self):
        """PRD §3.1: "the penalties figure is a running total, summing
        `penalty_cents` across every enforcement proceeding against the carrier
        that has reached a `DETERMINED` outcome."
        PRD §3.9: "any other basis costs 50 points per violation, capped at 250
        points".

        Design: Corner/complexity_layers/carrier_derived_totals_reconcile_after_two_determinations
        """
        env = setup_published_tariff()
        cid = env["carrier"]["id"]
        p1 = open_proceeding(cid, basis="TARIFF_VIOLATION")
        d1 = determine_proceeding(p1["id"], "VIOLATION_FOUND",
                                  violation_count=1, willful=False)
        p2 = open_proceeding(cid, basis="AGREEMENT_VIOLATION")
        d2 = determine_proceeding(p2["id"], "VIOLATION_FOUND",
                                  violation_count=1, willful=False)
        assert d1["penalty_cents"] == 1_000_000
        assert d1["repeat_offender"] is False
        assert d2["penalty_cents"] == 1_500_000, "repeat offender: x1.5"
        assert d2["repeat_offender"] is True

        carrier = _carrier(cid)
        assert carrier["cumulative_civil_penalties_cents"] == 2_500_000, (
            "equals the sum of the two proceedings' penalty_cents")
        assert carrier["compliance_score"] == 900, "1000 - 50 - 50"
        assert carrier["status"] == "ACTIVE", "900 >= 600"


class TestSuspensionThreshold:
    def test_compliance_score_exactly_600_does_not_suspend(self):
        """PRD §2.10: "the moment a deduction leaves it below 600, the carrier's
        `status` becomes `SUSPENDED` automatically — no operator action is
        required — and suspension is a terminal condition within the platform."
        PRD §3.9: "an `UNREASONABLE_PRACTICE` finding costs 100 points per
        violation, capped at 500 points for the proceeding".

        Design: Corner/calculations/compliance_score_exactly_600_does_not_suspend
        """
        env = setup_standard_billing()
        dispute = open_dispute(env["invoice"]["id"], env["shipper"]["id"],
                               dispute_reason="OTHER")
        proceeding = open_proceeding(env["carrier"]["id"],
                                     basis="UNREASONABLE_PRACTICE")
        determined = determine_proceeding(proceeding["id"], "VIOLATION_FOUND",
                                          violation_count=4, willful=False)
        assert determined["score_delta"] == -400
        assert determined["penalty_cents"] == 4_000_000

        carrier = _carrier(env["carrier"]["id"])
        assert carrier["compliance_score"] == 600
        assert carrier["status"] == "ACTIVE", "600 is not below 600"
        inv = api_client.get_invoice(env["invoice"]["id"], DOCKET).json()["data"]
        assert inv["invoice_status"] == "DISPUTED", "no cascade fired"
        rows, _meta = validate_paginated(api_client.list_disputes(
            env["invoice"]["id"], DOCKET))
        assert rows[0]["id"] == dispute["id"]
        assert rows[0]["resolution"] == "PENDING"


class TestEnforcementCascade:
    def test_enforcement_determination_suspends_carrier_and_tariff(self):
        """PRD §2.10: "the carrier then transitions from `ACTIVE` to `SUSPENDED`;
        every tariff publication of that carrier standing in `PUBLISHED` moves to
        `SUSPENDED`".
        PRD §3.9: "an `UNREASONABLE_PRACTICE` finding costs 100 points per
        violation, capped at 500 points for the proceeding".

        Design: Difficulty/transitive_cascade/enforcement_determination_suspends_carrier_tariff_invoice_dispute_chain
        """
        env = setup_suspended_carrier_with_pending_dispute()
        carrier = _carrier(env["carrier"]["id"])
        assert carrier["compliance_score"] == 500, "1000 - min(100 x 5, 500)"
        assert carrier["status"] == "SUSPENDED"
        assert carrier["cumulative_civil_penalties_cents"] == 5_000_000

        rows, _meta = validate_paginated(api_client.list_tariffs(
            env["carrier"]["id"], DOCKET))
        assert rows[0]["id"] == env["tariff"]["id"]
        assert rows[0]["publication_status"] == "SUSPENDED", "cascade link 2"

    def test_enforcement_cascade_voids_invoice_and_waives_dispute(self):
        """PRD §2.10: "every invoice of that carrier in `ISSUED` or `DISPUTED`
        status whose `charge_basis` is `TARIFF` and whose governing tariff has
        just been suspended moves to `VOIDED`; and every dispute still `PENDING`
        on a just-voided invoice is resolved as `UPHELD_WAIVED` with
        `resolved_amount_cents` set to zero and its `response_was_late` flag left
        untouched."

        Design: Difficulty/transitive_cascade/enforcement_determination_suspends_carrier_tariff_invoice_dispute_chain
        """
        env = setup_suspended_carrier_with_pending_dispute()
        inv = api_client.get_invoice(env["invoice"]["id"], DOCKET).json()["data"]
        assert inv["invoice_status"] == "VOIDED", "cascade link 3"

        rows, _meta = validate_paginated(api_client.list_disputes(
            env["invoice"]["id"], DOCKET))
        assert rows[0]["id"] == env["dispute"]["id"]
        assert rows[0]["resolution"] == "UPHELD_WAIVED", "cascade link 4"
        assert rows[0]["resolved_amount_cents"] == 0
        assert rows[0]["response_was_late"] is False, (
            "the cascade leaves response_was_late untouched")

        proc = api_client.get_proceeding(
            env["proceeding"]["id"], DOCKET).json()["data"]
        assert proc["proceeding_status"] == "DETERMINED"
        assert proc["score_delta"] == -500

    def test_enforcement_cascade_voids_only_non_terminal_invoices(self):
        """PRD §2.10: "every invoice of that carrier in `ISSUED` or `DISPUTED`
        status whose `charge_basis` is `TARIFF` and whose governing tariff has
        just been suspended moves to `VOIDED`" — a `PAID` invoice is not in the
        cascade's domain.

        Design: Corner/state_machines/enforcement_cascade_voids_only_non_terminal_invoices
        """
        env = setup_standard_billing()
        cid = env["carrier"]["id"]
        sid = env["shipper"]["id"]
        inv_b = issue_invoice(cid, sid, tariff_id=env["tariff"]["id"],
                              invoice_number="INV-COR-3",
                              container_number="MSKU9000003")
        mark_paid(env["invoice"]["id"], sid)
        d_b = open_dispute(inv_b["id"], sid, dispute_reason="MISSING_ELEMENTS")

        proceeding = open_proceeding(cid, basis="UNREASONABLE_PRACTICE")
        determine_proceeding(proceeding["id"], "VIOLATION_FOUND",
                             violation_count=5, willful=False)

        inv_a = api_client.get_invoice(env["invoice"]["id"], DOCKET).json()["data"]
        assert inv_a["invoice_status"] == "PAID", (
            "terminal invoices are untouched by the cascade")
        inv_b_now = api_client.get_invoice(inv_b["id"], DOCKET).json()["data"]
        assert inv_b_now["invoice_status"] == "VOIDED"
        rows, _meta = validate_paginated(api_client.list_disputes(inv_b["id"], DOCKET))
        assert rows[0]["id"] == d_b["id"]
        assert rows[0]["resolution"] == "UPHELD_WAIVED"
        assert rows[0]["resolved_amount_cents"] == 0


class TestSuspendedCarrierGate:
    def _dual_failure_env(self):
        """Carrier with a published tariff, suspended by an
        UNREASONABLE_PRACTICE determination (5 violations -> score 500);
        clock advanced to 2026-10-20 so an invoice dated 2026-09-06 is also
        more than 30 days stale."""
        env = setup_published_tariff(carrier_name="Dual Failure Lines")
        proceeding = open_proceeding(env["carrier"]["id"],
                                     basis="UNREASONABLE_PRACTICE")
        determine_proceeding(proceeding["id"], "VIOLATION_FOUND",
                             violation_count=5, willful=False)
        set_logical_clock("2026-10-20T00:00:00Z")
        return env

    def _late_invoice_attempt(self, env):
        return api_client.create_invoice(env["carrier"]["id"], {
            "invoice_number": "INV-DUAL-1", "charge_basis": "TARIFF",
            "tariff_id": env["tariff"]["id"],
            "billed_party_shipper_id": env["shipper"]["id"],
            "container_number": "MSKU4000004", "port_code": "USLGB",
            "availability_date": "2026-09-03T00:00:00Z",
            "return_date": "2026-09-06T00:00:00Z",
            "last_accrual_date": "2026-09-06T00:00:00Z"},
            make_carrier_rep_headers(env["carrier"]["id"]))

    def test_suspended_carrier_beats_late_invoice_issuance(self):
        """PRD §2.7: the ladder's "7. The carrier's operational standing for
        operational filings (`ERR_CARRIER_NOT_ACTIVE`)." precedes the from-state
        and "9. Temporal windows" rungs, and "evaluation stops at the first
        failure".
        PRD §3.5: "The invoicing carrier itself must be `ACTIVE` (otherwise
        `ERR_CARRIER_NOT_ACTIVE`)".

        Design: Difficulty/priority_pair_validation_conflict/suspended_carrier_beats_late_invoice_issuance
        """
        env = self._dual_failure_env()
        resp = self._late_invoice_attempt(env)
        # The tariff is cascade-SUSPENDED and last_accrual is 44 days stale;
        # the carrier-standing rung still wins.
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_ACTIVE)

    def test_suspended_carrier_rejection_stores_no_invoice(self):
        """PRD §2.10: "A suspended carrier is barred from the operational
        filings: it cannot issue invoices, file service contracts, or publish
        tariffs."

        Design: Difficulty/priority_pair_validation_conflict/suspended_carrier_beats_late_invoice_issuance
        """
        env = self._dual_failure_env()
        resp = self._late_invoice_attempt(env)
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_ACTIVE)
        rows, meta = validate_paginated(api_client.list_invoices(
            DOCKET, params={"carrier_id": env["carrier"]["id"]}))
        assert meta["total_count"] == 0
        assert rows == []
