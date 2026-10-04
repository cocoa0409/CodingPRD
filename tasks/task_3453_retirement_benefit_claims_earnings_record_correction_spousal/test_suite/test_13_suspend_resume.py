"""Voluntary suspension and resumption: DRC accrual across the cycle, batch
auto-resumption at age 70, and the suspension age band."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_worker_with_awi_record,
    file_claim,
    get_claim,
    list_recomputation_events,
    make_claimant_headers,
    payment_for_month,
    run_batch_at,
    set_clock,
    setup_entitled_retirement,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


def _setup_suspender(api):
    """Worker with PIA 20,880 (five AWI years 2019-2023), RETIREMENT entitled
    2031-06 at FRA (monthly 20,880), approved at clock 2031-06-15."""
    worker = create_worker_with_awi_record(2019, 2023, full_name="Suspender")
    claim = file_claim(worker["id"], "RETIREMENT", "2031-06")
    set_clock("2031-06-15T00:00:00Z")
    entitled = approve_claim(claim["id"])
    assert entitled["monthly_benefit_cents"] == 20_880
    return worker, entitled


class TestSuspendResumeCycle:
    def test_suspend_resume_accrues_24_drc_months(self, api):
        """PRD §3.6: "`drc_months` becomes the lesser of the whole months between
        `suspended_since` and the current month, and the headroom remaining
        between the claimant's age at suspension and 840 months (floored at
        zero) — credits accrue only for months with no payment and never beyond
        age 70."
        PRD §3.5: "When the claimant is at or past full retirement age, the
        factor is one, increased by one one-hundred-fiftieth for each
        delayed-credit month".

        Suspended 2031-12 (age 810), resumed 2033-12: drc_months = min(24, 30)
        = 24; factor 1 + 24/150 = 1.16; monthly = dime_floor(20,880 * 1.16) =
        24,220.

        Design: Difficulty/non_linear_state_machine/claim_suspend_resume_cycle_accrues_drc
        """
        worker, entitled = _setup_suspender(api)

        set_clock("2031-12-10T00:00:00Z")
        suspended = validate_success(
            api.suspend_claim(entitled["id"], entitled["version"],
                              make_claimant_headers(worker["id"]))
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspended_since"] == "2031-12"

        set_clock("2033-12-10T00:00:00Z")
        resumed = validate_success(
            api.resume_claim(entitled["id"], make_claimant_headers(worker["id"]))
        )
        assert resumed["status"] == "ENTITLED"
        assert resumed["drc_months"] == 24
        assert resumed["monthly_benefit_cents"] == 24_220

    def test_resume_appends_suspension_resume_event(self, api):
        """PRD §3.6: "The monthly benefit is then recomputed with those accrued
        credits per §3.5, a recomputation event with `trigger`
        `SUSPENSION_RESUME` is appended, and `suspended_since` returns to null."
        PRD §3.5: "Whenever an event changes `pia_cents` or
        `monthly_benefit_cents` of an `ENTITLED` or `SUSPENDED` claim — a
        correction approval, a pension update, a resumption from suspension — the
        system appends a recomputation event recording the `trigger`".

        Design: Difficulty/non_linear_state_machine/claim_suspend_resume_cycle_accrues_drc
        """
        worker, entitled = _setup_suspender(api)

        set_clock("2031-12-10T00:00:00Z")
        validate_success(
            api.suspend_claim(entitled["id"], entitled["version"],
                              make_claimant_headers(worker["id"]))
        )
        set_clock("2033-12-10T00:00:00Z")
        resumed = validate_success(
            api.resume_claim(entitled["id"], make_claimant_headers(worker["id"]))
        )
        assert resumed["suspended_since"] is None

        events = list_recomputation_events(entitled["id"])
        assert len(events) == 1
        event = events[0]
        assert event["trigger"] == "SUSPENSION_RESUME"
        assert event["old_monthly_benefit_cents"] == 20_880
        assert event["new_monthly_benefit_cents"] == 24_220
        assert event["retro_delta_cents"] == 0, "no payments during suspension"
        assert event["resolution"] == "NONE"


class TestBatchAutoResume:
    def test_batch_auto_resumes_suspension_at_70(self, api):
        """PRD §3.7: "Second, **auto-resumption**: every `SUSPENDED` claim whose
        claimant has reached 840 months at the run month resumes per §3.6,
        accruing its delayed credits and recomputing."
        PRD §3.7: "Third, **payment generation**: one payment is created per
        `ENTITLED` claim whose `entitlement_month` is on or before the run
        month."

        Suspended 2034-01 (age 835); the 2034-06 run reaches 840: drc_months =
        min(5, 5) = 5; monthly = dime_floor(20,880 * 31/30) = 21,570; the same
        run already pays at the new rate.

        Design: Corner/state_machines/batch_auto_resumes_suspension_at_70
        """
        worker, entitled = _setup_suspender(api)

        set_clock("2034-01-10T00:00:00Z")
        suspended = validate_success(
            api.suspend_claim(entitled["id"], entitled["version"],
                              make_claimant_headers(worker["id"]))
        )
        assert suspended["status"] == "SUSPENDED"

        report = run_batch_at("2034-06-05T00:00:00Z", "2034-06")
        assert report["claims_auto_resumed"] == 1

        claim = get_claim(entitled["id"])
        assert claim["status"] == "ENTITLED"
        assert claim["drc_months"] == 5
        assert claim["monthly_benefit_cents"] == 21_570

        payment = payment_for_month(entitled["id"], "2034-06")
        assert payment is not None
        assert payment["gross_cents"] == 21_570, "auto-resume precedes payment generation"


class TestSuspensionAgeBand:
    def test_suspension_before_fra_rejected(self, api):
        """PRD §3.6: "An entitled claimant may **voluntarily suspend** — `ENTITLED
        → SUSPENDED` — but only within a narrow age band: the claimant's
        `age_months` at the logical clock must be at least their `fra_months` and
        below 840 months, else the attempt is rejected with
        `ERR_SUSPENSION_AGE_INELIGIBLE` (422)."

        Age 748 at clock 2026-10-01 is below FRA 804; the OCC version is fresh,
        so only the age band rejects.

        Design: Corner/validations/suspension_before_fra_rejected
        """
        worker, entitled = setup_entitled_retirement(2021, 2023, "2026-06")

        set_clock("2026-10-01T00:00:00Z")
        resp = api.suspend_claim(
            entitled["id"], entitled["version"], make_claimant_headers(worker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SUSPENSION_AGE_INELIGIBLE, 422)

        unchanged = get_claim(entitled["id"])
        assert unchanged["status"] == "ENTITLED"
        assert unchanged["drc_months"] == 0
