"""Optimistic concurrency control on the three guarded writes: claim suspend,
overpayment waiver request, and worker pension update."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_overpayment_case,
    create_worker,
    create_worker_with_awi_record,
    file_claim,
    get_claim,
    get_overpayment_case,
    get_worker,
    make_claimant_headers,
    set_clock,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestSuspendOcc:
    def test_occ_suspend_with_stale_version_after_recompute_returns_412(self, api):
        """PRD §2.7: "Suspending a claim (`POST /ssa/claims/{id}/suspend`)
        requires `expected_claim_version` matching the claim's current
        `version`. A claimant whose view of the claim predates a recomputation
        side effect — say, a correction approval or pension update that changed
        `monthly_benefit_cents` — holds a stale view at the moment of the
        suspension decision, and the write is rejected rather than allowed to
        overwrite what the client never observed."
        PRD §3.1: "The write recomputes the worker's own `ENTITLED` or
        `SUSPENDED` claims — because the windfall elimination provision depends
        on the pension — and every auxiliary claim where this worker is the
        claimant, because the government pension offset depends on it."

        The pension PATCH bumps the claim's version from 2 to 3 (WEP
        recomputation: monthly 12,510 -> 5,560 at the FRA factor 1.0); the stale
        suspend is rejected, the fresh one succeeds.

        Design: Corner/cross_cutting_layers/occ_suspend_with_stale_version_after_recompute_returns_412
        """
        worker = create_worker_with_awi_record(2021, 2023, full_name="Occ Suspend")
        claim = file_claim(worker["id"], "RETIREMENT", "2031-06")
        set_clock("2031-06-15T00:00:00Z")
        entitled = approve_claim(claim["id"])
        assert entitled["version"] == 2

        patched = validate_success(
            api.patch_worker(
                worker["id"],
                {
                    "noncovered_pension_monthly_cents": 60_000,
                    "noncovered_pension_start_month": "2030-01",
                    "expected_worker_version": worker["version"],
                },
                CS,
            )
        )
        assert patched["version"] == worker["version"] + 1

        recomputed = get_claim(claim["id"])
        assert recomputed["monthly_benefit_cents"] == 5_560, (
            "WEP recomputation at FRA: PIA 5,560 with factor 1.0"
        )
        assert recomputed["version"] == entitled["version"] + 1

        set_clock("2031-08-01T00:00:00Z")
        stale = api.suspend_claim(
            claim["id"], entitled["version"], make_claimant_headers(worker["id"])
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        suspended = validate_success(
            api.suspend_claim(
                claim["id"], recomputed["version"], make_claimant_headers(worker["id"])
            )
        )
        assert suspended["status"] == "SUSPENDED"


class TestWaiverOcc:
    def test_occ_waiver_with_stale_version_returns_412(self, api):
        """PRD §2.7: "Requesting an overpayment waiver (`POST
        /ssa/overpayment-cases/{id}/request-waiver`) requires
        `expected_overpayment_version` matching the case's current `version`. A
        withholding batch may have advanced `recovered_cents` since the claimant
        last read the case, leaving the waiver decision resting on a stale
        remaining balance."

        Design: Corner/cross_cutting_layers/occ_waiver_with_stale_version_returns_412
        """
        worker = create_worker(full_name="Occ Waiver")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")
        case = create_overpayment_case(claim["id"], 8_000, "2026-06", "2026-06",
                                       reason="SYSTEM_ERROR")

        stale = api.request_waiver(
            case["id"], case["version"] - 1, "stale view",
            make_claimant_headers(worker["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        fresh = validate_success(
            api.request_waiver(
                case["id"], case["version"], "without fault",
                make_claimant_headers(worker["id"]),
            )
        )
        assert fresh["status"] == "WAIVER_REVIEW"
        assert fresh["waiver_grounds"] == "without fault"


class TestPensionPatchOcc:
    def test_occ_worker_pension_patch_with_stale_version_returns_412(self, api):
        """PRD §2.7: "Updating a worker's non-covered pension (`PATCH
        /ssa/workers/{id}`) requires `expected_worker_version` matching the
        worker's current `version`. Another writer — a death report, or an
        earlier pension update that triggered recomputation — may have advanced
        the worker since the client last observed it."

        The first PATCH (expected version 1) succeeds and bumps the worker to
        version 2; the second, still carrying 1, is rejected.

        Design: Corner/cross_cutting_layers/occ_worker_pension_patch_with_stale_version_returns_412
        """
        worker = create_worker(full_name="Occ Patch")

        first = validate_success(
            api.patch_worker(
                worker["id"],
                {
                    "noncovered_pension_monthly_cents": 40_000,
                    "noncovered_pension_start_month": "2025-01",
                    "expected_worker_version": worker["version"],
                },
                CS,
            )
        )
        assert first["version"] == worker["version"] + 1
        assert first["noncovered_pension_monthly_cents"] == 40_000

        stale = api.patch_worker(
            worker["id"],
            {
                "noncovered_pension_monthly_cents": 45_000,
                "noncovered_pension_start_month": "2025-01",
                "expected_worker_version": worker["version"],
            },
            CS,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        unchanged = get_worker(worker["id"])
        assert unchanged["noncovered_pension_monthly_cents"] == 40_000
        assert unchanged["version"] == first["version"]
