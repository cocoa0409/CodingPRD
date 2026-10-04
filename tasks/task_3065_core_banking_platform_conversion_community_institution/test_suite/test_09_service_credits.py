"""Vendor service credit claims: computation, cap, eligibility, segregation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_fc_headers,
    setup_live_project, setup_live_project_with_defect,
    setup_live_project_with_open_claim, create_defect, resolve_defect_at,
    set_clock,
)

PM = TEST_USERS["pm_headers"]
OPS = TEST_USERS["ops_headers"]
VTL = TEST_USERS["vtl_headers"]
FC = TEST_USERS["fc_headers"]


class TestCreditComputation:
    def test_monthly_cap_binds_on_aggregate(self, api):
        """PRD §3.12: "First, per defect and preserving the `defect_ids` order,
        the breach hours are the seconds from the defect's `sla_deadline` to
        its `resolved_at`, divided into hours and rounded **up** to the next
        whole hour — these populate `breach_hours` positionally."
        PRD §3.12: "Fourth, the raw credit is the uncovered hours times 25,000
        cents per hour (that is, 250 dollars per hour), and the final
        `credit_cents` is that raw amount capped at 200,000 cents (2,000
        dollars) for the month — the cap applies to the aggregated monthly
        claim, not per defect."

        Design: Corner/calculations/service_credit_cap_binds_on_aggregate_month
        """
        ctx = setup_live_project()
        pid = ctx["project"]["id"]
        set_clock("2026-09-21T00:00:00Z")
        da = create_defect(pid, title="A", severity="SEV1")
        db = create_defect(pid, title="B", severity="SEV1")
        resolve_defect_at(da["id"], "2026-09-22T06:00:00Z")
        resolve_defect_at(db["id"], "2026-09-23T02:00:00Z")
        claim = get_success_data(
            api.create_service_credit(
                {"project_id": pid, "month": "2026-09",
                 "defect_ids": [da["id"], db["id"]]},
                FC,
            ),
            201,
        )
        # A: sla 2026-09-22T00:00Z resolved +6h; B: +26h. (6+26-4)*25000 raw
        # = 700000, capped at the 200000 monthly cap.
        assert claim["breach_hours"] == [6, 26]
        assert claim["credit_cents"] == 200000

    def test_defect_reopen_disputes_open_claim(self, api):
        """PRD §3.11: "A `ProjectManager` may reopen a resolved defect
        (`RESOLVED → REOPENED`), which increments `reopened_count`, clears
        `resolved_at` to null, forces `credit_eligible` false, and — critically
        — disputes money in flight: every `OPEN` service credit claim of the
        project whose `defect_ids` reference this defect transitions to
        `DISPUTED` with the dispute note \"auto: defect reopened\"."

        Design: Difficulty/transitive_cascade/defect_reopen_cascades_service_credit_dispute
        """
        ctx = setup_live_project_with_open_claim()
        assert ctx["defect"]["credit_eligible"] is True
        assert ctx["claim"]["breach_hours"] == [48]
        assert ctx["claim"]["credit_cents"] == 200000
        get_success_data(api.reopen_defect(ctx["defect"]["id"], PM))
        claim = get_success_data(api.get_service_credit(ctx["claim"]["id"], FC))
        assert claim["claim_status"] == "DISPUTED"
        assert claim["dispute_note"] == "auto: defect reopened"

    def test_auto_dispute_note_and_claim_status_after_reopen(self, api):
        """PRD §3.11: "every `OPEN` service credit claim of the project whose
        `defect_ids` reference this defect transitions to `DISPUTED` with the
        dispute note \"auto: defect reopened\"."

        Design: Difficulty/transitive_cascade/defect_reopen_cascades_service_credit_dispute
        """
        ctx = setup_live_project_with_open_claim(
            defect_clock="2026-09-21T00:00:00Z",
            resolve_clock="2026-09-23T00:00:00Z",  # breach 24h: (24-4)*25000 = 500000 -> capped
        )
        assert ctx["claim"]["credit_cents"] == 200000
        get_success_data(api.reopen_defect(ctx["defect"]["id"], PM))
        claim = get_success_data(api.get_service_credit(ctx["claim"]["id"], FC))
        assert claim["claim_status"] == "DISPUTED"
        assert claim["dispute_note"] == "auto: defect reopened"


class TestCreditInvariantAcrossReopen:
    def test_credit_conserved_across_reopen_and_reresolve(self, api):
        """PRD §3.12: "A disputed claim returns to `OPEN` (`DISPUTED → OPEN`)
        only when every listed defect is again `RESOLVED` and
        `credit_eligible`, and the return recomputes `credit_cents` under the
        four-step rule."
        PRD §3.11: "The SLA deadline never moves: resolving a `REOPENED` defect
        recomputes `credit_eligible` against the original deadline."

        Design: Difficulty/compensating_invariant/defect_reopen_reresolve_conserves_credit_on_claim_reopen
        """
        ctx = setup_live_project_with_open_claim(
            defect_clock="2026-09-21T00:00:00Z",
            resolve_clock="2026-09-24T00:00:00Z",
        )
        defect = ctx["defect"]
        claim = ctx["claim"]
        assert claim["credit_cents"] == 200000
        resolved_1 = defect["resolved_at"]
        get_success_data(api.reopen_defect(defect["id"], PM))
        # Clock is still held at 2026-09-24T00:00:00Z, so the re-resolution
        # stamps the same resolved_at.
        resolved2 = get_success_data(api.resolve_defect(defect["id"], VTL))
        assert resolved2["resolved_at"] == resolved_1
        assert resolved2["credit_eligible"] is True
        reopened_claim = get_success_data(api.reopen_service_credit(claim["id"], FC))
        assert reopened_claim["claim_status"] == "OPEN"
        assert reopened_claim["credit_cents"] == 200000

    def test_claim_reopen_recomputes_identical_credit(self, api):
        """PRD §3.12: "the return recomputes `credit_cents` under the four-step
        rule."
        PRD §3.12: "Fourth, the raw credit is the uncovered hours times 25,000
        cents per hour (that is, 250 dollars per hour), and the final
        `credit_cents` is that raw amount capped at 200,000 cents (2,000
        dollars) for the month"

        Design: Difficulty/compensating_invariant/defect_reopen_reresolve_conserves_credit_on_claim_reopen
        """
        ctx = setup_live_project_with_open_claim(
            defect_clock="2026-09-21T00:00:00Z",
            resolve_clock="2026-09-22T05:30:00Z",  # breach 5.5h -> ceil 6h -> (6-4)*25000 = 50000
        )
        defect = ctx["defect"]
        claim = ctx["claim"]
        assert claim["credit_cents"] == 50000
        get_success_data(api.reopen_defect(defect["id"], PM))
        get_success_data(api.resolve_defect(defect["id"], VTL))
        reopened_claim = get_success_data(api.reopen_service_credit(claim["id"], FC))
        assert reopened_claim["claim_status"] == "OPEN"
        assert reopened_claim["credit_cents"] == 50000


class TestCreditEligibility:
    def test_ineligible_defect_and_wrong_month_rejected(self, api):
        """PRD §3.12: "Every referenced defect must currently be
        `credit_eligible`, must have its `sla_deadline` fall in the claim's
        `month`, and must not already appear in another `OPEN` claim of the
        project; additionally there may be only one `OPEN` claim per project
        per month. Eligibility failures are rejected with
        `ERR_CREDIT_INELIGIBLE` (HTTP 422)"

        Design: Corner/validations/service_credit_ineligible_defect_returns_credit_ineligible
        """
        ctx = setup_live_project_with_defect(severity="SEV3")
        pid = ctx["project"]["id"]
        # SEV3 opened 2026-09-21 -> sla +168h = 2026-09-28T00:00Z; resolved
        # 2026-09-22 within the SLA -> not credit eligible.
        defect = resolve_defect_at(ctx["defect"]["id"], "2026-09-22T00:00:00Z")
        assert defect["credit_eligible"] is False
        resp = api.create_service_credit(
            {"project_id": pid, "month": "2026-09", "defect_ids": [defect["id"]]},
            FC,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_INELIGIBLE)
        resp2 = api.create_service_credit(
            {"project_id": pid, "month": "2026-10", "defect_ids": [defect["id"]]},
            FC,
        )
        validate_error(resp2, ApiErrorId.ERR_CREDIT_INELIGIBLE)


class TestApproverPayerSegregation:
    def test_approver_cannot_pay(self, api):
        """PRD §3.12: "Payment (`APPROVED → PAID`, terminal) re-checks that
        every listed defect is still `RESOLVED`, and must not be performed by
        the same `X-User-ID` recorded in `approved_by` — the approver-payer
        split is the second segregation-of-duties pair."

        Design: Corner/rbac/segregation_approver_cannot_pay
        """
        ctx = setup_live_project_with_open_claim()
        claim = ctx["claim"]
        get_success_data(
            api.approve_service_credit(claim["id"], make_fc_headers("fc-carol"))
        )
        resp = api.pay_service_credit(claim["id"], make_fc_headers("fc-carol"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        paid = get_success_data(
            api.pay_service_credit(claim["id"], make_fc_headers("fc-dave"))
        )
        assert paid["claim_status"] == "PAID"
