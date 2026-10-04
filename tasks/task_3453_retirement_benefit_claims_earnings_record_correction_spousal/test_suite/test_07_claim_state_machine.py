"""Benefit-claim state machine: initial states, invalid transitions, terminal
lockdown, denial-reopen, and the 60-day reopen window."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_overpayment_case,
    create_payee_case,
    create_relationship,
    create_worker,
    create_worker_with_awi_record,
    file_claim,
    file_correction,
    make_claimant_headers,
    make_claims_specialist_headers,
    make_senior_adjudicator_headers,
    set_clock,
    setup_entitled_retirement,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestInitialStates:
    def test_initial_states_on_create(self, api):
        """PRD §3.4: "Two filing guards apply before the claim enters `FILED`".
        PRD §3.2: "The request enters `PENDING_REVIEW` with its `statute_deadline`
        computed immediately".
        PRD §3.3: "The assertion enters `ASSERTED`, and the system begins tracking
        `marriage_months`".
        PRD §3.8: "the case enters `NOTIFIED`, its notice date stamped at creation".
        PRD §3.9: "the case enters `INVESTIGATING` with `created_by` stamped".

        Design: Corner/state_machines/initial_states_on_create
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Initial Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        assert claim["status"] == "FILED"
        entitled = approve_claim(claim["id"])
        assert entitled["status"] == "ENTITLED"

        worker2 = create_worker(full_name="Initial Worker Two")
        claim2 = file_claim(worker2["id"], "RETIREMENT", "2026-06")
        assert claim2["status"] == "FILED"

        correction = file_correction(worker["id"], 2023, 1_900_000, "OTHER")
        assert correction["status"] == "PENDING_REVIEW"

        spouse = create_worker(full_name="Init Spouse")
        rel = create_relationship(worker["id"], spouse["id"], "CURRENT_SPOUSE", "2000-01-01")
        assert rel["status"] == "ASSERTED"

        case = create_overpayment_case(entitled["id"], 1_000, "2026-06", "2026-06",
                                       reason="SYSTEM_ERROR")
        assert case["status"] == "NOTIFIED"

        payee = create_payee_case(entitled["id"], creator_id="spec-2",
                                  payee_name="Init Payee",
                                  determination_basis="physician letter")
        assert payee["status"] == "INVESTIGATING"
        assert payee["created_by"] == "spec-2"


class TestInvalidTransitions:
    def test_claim_approve_twice_returns_invalid_state(self, api):
        """PRD §3.4: "Approval — `FILED → ENTITLED`, by a `ClaimsSpecialist`".
        PRD §2.9: "**State-machine legality**: the target entity is in a
        from-state of the invoked transition, and terminal entities reject all
        further actions — otherwise `ERR_INVALID_STATE` (409), or
        `ERR_CLAIM_ALREADY_TERMINAL` (409) when the target claim is
        `WITHDRAWN` or `TERMINATED`."

        Design: Corner/state_machines/claim_approve_twice_returns_invalid_state
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")
        assert entitled["monthly_benefit_cents"] == 8750

        resp = api.approve_claim(entitled["id"], CS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        unchanged = validate_success(api.get_claim(entitled["id"], CS))
        assert unchanged["status"] == "ENTITLED"
        assert unchanged["monthly_benefit_cents"] == 8750

    def test_claim_resume_when_entitled_returns_invalid_state(self, api):
        """PRD §3.6: "Resumption — `SUSPENDED → ENTITLED` — happens two ways: the
        claimant (or a specialist) asks, or the monthly batch auto-resumes the
        claim when the claimant's `age_months` at the run month reaches 840."
        PRD §2.9: "**State-machine legality**: the target entity is in a
        from-state of the invoked transition, and terminal entities reject all
        further actions — otherwise `ERR_INVALID_STATE` (409), or
        `ERR_CLAIM_ALREADY_TERMINAL` (409) when the target claim is
        `WITHDRAWN` or `TERMINATED`."

        Design: Corner/state_machines/claim_resume_when_entitled_returns_invalid_state
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")

        resp = api.resume_claim(entitled["id"], make_claimant_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        unchanged = validate_success(api.get_claim(entitled["id"], CS))
        assert unchanged["status"] == "ENTITLED"
        assert unchanged["drc_months"] == 0

    def test_claim_terminal_lockdown_after_withdraw_returns_409(self, api):
        """PRD §3.4: "Once a claim reaches `WITHDRAWN` or `TERMINATED`, every
        further action on it is rejected with `ERR_CLAIM_ALREADY_TERMINAL` (409)
        rather than the generic state error."

        Design: Corner/state_machines/claim_terminal_lockdown_after_withdraw_returns_409
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")
        withdrawn = validate_success(
            api.withdraw_claim(entitled["id"], 0, make_claimant_headers(worker["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.suspend_claim(
            withdrawn["id"], entitled["version"], make_claimant_headers(worker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL, 409)

        unchanged = validate_success(api.get_claim(entitled["id"], CS))
        assert unchanged["status"] == "WITHDRAWN"


class TestDenialReopen:
    def test_claim_denial_reopen_cycle_restores_filed(self, api):
        """PRD §3.4: "A denied claim may be reopened by a `SeniorAdjudicator`
        within sixty days of `decided_at` (`ERR_REOPEN_WINDOW_EXPIRED`, 422) and
        never by the operator who denied it (`ERR_SAME_ADJUDICATOR`, 409);
        reopening returns the claim to `FILED`, clears the denial fields, and
        records the adjudicator's `reopen_reason`."

        Design: Corner/state_machines/claim_denial_reopen_cycle_restores_filed
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Reopen Worker")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")

        denied = validate_success(
            api.deny_claim(claim["id"], "insufficient proof of age",
                           make_claims_specialist_headers("spec-1"))
        )
        assert denied["status"] == "DENIED"
        assert denied["decided_by"] == "spec-1"

        reopened = validate_success(
            api.reopen_claim(claim["id"], "birth certificate produced",
                             make_senior_adjudicator_headers("sen-2"))
        )
        assert reopened["status"] == "FILED"
        assert reopened["denial_reason"] is None
        assert reopened["decided_by"] is None
        assert reopened["decided_at"] is None

        entitled = approve_claim(claim["id"])
        assert entitled["status"] == "ENTITLED"
        assert entitled["monthly_benefit_cents"] == 8750

    def test_claim_reopen_after_60_days_rejected(self, api):
        """PRD §3.4: "A denied claim may be reopened by a `SeniorAdjudicator`
        within sixty days of `decided_at` (`ERR_REOPEN_WINDOW_EXPIRED`, 422) and
        never by the operator who denied it (`ERR_SAME_ADJUDICATOR`, 409)".

        Design: Corner/validations/claim_reopen_after_60_days_rejected
        """
        worker = create_worker(full_name="Late Reopen")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        validate_success(
            api.deny_claim(claim["id"], "not insured", make_claims_specialist_headers("spec-1"))
        )

        set_clock("2026-11-15T00:00:00Z")  # 75 days after the 2026-09-01 decision
        resp = api.reopen_claim(
            claim["id"], "new evidence", make_senior_adjudicator_headers("sen-2")
        )
        validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED, 422)

        unchanged = validate_success(api.get_claim(claim["id"], CS))
        assert unchanged["status"] == "DENIED"
