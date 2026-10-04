"""Content pipeline: capture format constraint, batch dispatch gates, render-time
calculation, the cyclic QC retry loop, and batch counters."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    capture_asset,
    create_active_campaign,
    create_active_production,
    create_production,
    create_render_batch_payload,
    get_success_data,
    render_asset_to_qc,
    set_clock,
    setup_active_production_with_approved_asset,
    validate_error,
    validate_success,
)

PD = TEST_USERS["production_director_headers"]
CP = TEST_USERS["content_producer_headers"]
SM = TEST_USERS["sponsorship_manager_headers"]


class TestCaptureFormatConstraint:

    def test_haptic_production_requires_wrap16k_format(self, api):
        """PRD: "The capture format is constrained by the parent production's
        haptic capability: when the production's `is_haptic_capable` is `true`,
        the asset must be captured in `WRAP_16K`. Submitting a `WRAP_8K` asset
        under a haptic-capable production is rejected with `ERR_FORMAT_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/haptic_production_requires_wrap16k_format
        """
        prod = create_production(title="HF", production_type="ORIGINAL", base_price_cents=10000, is_haptic_capable=True)
        resp = api.create_asset(
            {
                "production_id": prod["id"],
                "title": "HFA",
                "capture_format": "WRAP_8K",
                "storage_gb": 100,
                "render_hours_base": 2,
            },
            CP,
        )
        validate_error(resp, ApiErrorId.ERR_FORMAT_MISMATCH)

    def test_haptic_production_accepts_wrap16k_format(self, api):
        """PRD: "The capture format is constrained by the parent production's
        haptic capability: when the production's `is_haptic_capable` is `true`,
        the asset must be captured in `WRAP_16K`."
        PRD: "Newly captured assets land in `CAPTURED` status with
        `render_cost_cents` equal to 0; the render cost is only computed when
        the asset passes quality control."

        Design: Corner/validations/haptic_production_requires_wrap16k_format
        """
        prod = create_production(title="HF2", production_type="ORIGINAL", base_price_cents=10000, is_haptic_capable=True)
        data = validate_success(
            api.create_asset(
                {
                    "production_id": prod["id"],
                    "title": "HFB",
                    "capture_format": "WRAP_16K",
                    "storage_gb": 100,
                    "render_hours_base": 2,
                },
                CP,
            ),
            expected_status=201,
        )
        assert data["status"] == "CAPTURED"
        assert data["render_cost_cents"] == 0


class TestBatchDispatchGates:

    def test_dispatch_empty_batch_rejected(self, api):
        """PRD: "Dispatching a batch (`OPEN → RENDERING`) is gated by three
        checks. First, the batch must have at least one submitted asset. Second,
        no other batch may currently be in `RENDERING` or `SETTLING` — the
        render wall can only host one batch at a time. Either violation is
        rejected with `ERR_BATCH_BUSY` (HTTP 409)."

        Design: Corner/validations/batch_dispatch_empty_rejected
        """
        batch = validate_success(
            api.create_render_batch({"dispatch_mode": "STANDARD", "asset_ids": []}, CP),
            expected_status=201,
        )
        resp = api.dispatch_render_batch(batch["id"], CP)
        validate_error(resp, ApiErrorId.ERR_BATCH_BUSY)

    def test_dispatch_while_another_batch_rendering_rejected(self, api):
        """PRD: "Second, no other batch may currently be in `RENDERING` or
        `SETTLING` — the render wall can only host one batch at a time. Either
        violation is rejected with `ERR_BATCH_BUSY` (HTTP 409)."

        Design: Corner/validations/batch_dispatch_empty_rejected
        """
        prod = create_active_production(title="BB", base_price_cents=10000)
        a1 = capture_asset(prod["id"], title="BB1")
        a2 = capture_asset(prod["id"], title="BB2")
        b1 = validate_success(api.create_render_batch(create_render_batch_payload([a1["id"]]), CP), expected_status=201)
        validate_success(api.dispatch_render_batch(b1["id"], CP))
        b2 = validate_success(api.create_render_batch(create_render_batch_payload([a2["id"]]), CP), expected_status=201)
        resp = api.dispatch_render_batch(b2["id"], CP)
        validate_error(resp, ApiErrorId.ERR_BATCH_BUSY)
        after = validate_success(api.get_render_batch(b2["id"], CP))
        assert after["status"] == "OPEN", "the second batch must remain OPEN after the rejected dispatch"


class TestRenderTimeCalculation:

    def test_render_time_sums_base_rush_and_premium_sponsor_adjust(self, api):
        """PRD: "The render duration is the sum of three terms: a fixed 90
        minutes of base render time, plus 45 minutes of peak rush overhead for
        each asset in the batch when the batch's `dispatch_mode` is `RUSH` (zero
        when `STANDARD`), plus 30 minutes for each `ACTIVE` campaign whose
        sponsor's `brand_tier` is `PREMIUM` and whose flight window covers the
        dispatch instant."
        PRD: "The `batch_cost_cents` is the total render minutes multiplied by
        1000 cents per render minute."

        Design: Corner/calculations/render_time_sums_base_rush_and_premium_sponsor_adjust
        """
        create_active_campaign(brand_tier="PREMIUM")
        prod = create_active_production(title="RP2", base_price_cents=10000)
        a1 = capture_asset(prod["id"], title="R1", render_hours_base=2)
        a2 = capture_asset(prod["id"], title="R2", render_hours_base=3)
        batch = validate_success(
            api.create_render_batch({"dispatch_mode": "RUSH", "asset_ids": [a1["id"], a2["id"]]}, CP),
            expected_status=201,
        )
        data = validate_success(api.dispatch_render_batch(batch["id"], CP))
        # 90 base + 2 x 45 rush + 1 x 30 premium sponsor = 210
        assert data["render_minutes"] == 210
        assert data["batch_cost_cents"] == 210000

    def test_render_time_standard_without_premium_sponsor_is_base_only(self, api):
        """PRD: "The render duration is the sum of three terms: a fixed 90
        minutes of base render time, plus 45 minutes of peak rush overhead for
        each asset in the batch when the batch's `dispatch_mode` is `RUSH` (zero
        when `STANDARD`), plus 30 minutes for each `ACTIVE` campaign whose
        sponsor's `brand_tier` is `PREMIUM` and whose flight window covers the
        dispatch instant."

        Design: Corner/calculations/render_time_sums_base_rush_and_premium_sponsor_adjust
        """
        prod = create_active_production(title="STD", base_price_cents=10000)
        asset = capture_asset(prod["id"], title="S1", render_hours_base=2)
        batch = validate_success(
            api.create_render_batch({"dispatch_mode": "STANDARD", "asset_ids": [asset["id"]]}, CP),
            expected_status=201,
        )
        data = validate_success(api.dispatch_render_batch(batch["id"], CP))
        # 90 base + 0 rush (STANDARD) + 0 premium campaigns = 90
        assert data["render_minutes"] == 90
        assert data["batch_cost_cents"] == 90000


class TestAssetQCRetryCycle:

    def test_qc_fail_then_retry_then_second_pass_approve(self, api):
        """PRD: "A failed asset may be retried: the retry action returns it from
        `QC_FAILED` to `CAPTURED`, but only while the asset's parent production
        is `DRAFT` or `ACTIVE`."
        PRD: "Failing (`QC → QC_FAILED`) increments the batch's
        `failed_asset_count` by 1 and likewise decrements `submitted_asset_count`
        by 1."

        Design: Difficulty/non_linear_state_machine/asset_qc_retry_cycle
        """
        prod = create_active_production(title="AP", base_price_cents=10000)
        asset = capture_asset(prod["id"], title="AA", render_hours_base=2)
        asset_qc, batch1 = render_asset_to_qc(asset["id"])
        assert asset_qc["status"] == "QC"

        validate_success(api.qc_fail_asset(asset["id"], CP))
        batch1_after = validate_success(api.get_render_batch(batch1["id"], CP))
        assert batch1_after["failed_asset_count"] == 1
        assert batch1_after["submitted_asset_count"] == 0

        retry_data = validate_success(api.retry_asset(asset["id"], CP))
        assert retry_data["status"] == "CAPTURED", "retry must return the asset to CAPTURED (cycle re-entry)"

        asset_qc2, batch2 = render_asset_to_qc(asset["id"], settle_clock="2026-09-01T06:00:00Z")
        assert asset_qc2["status"] == "QC"
        approved = validate_success(api.qc_approve_asset(asset["id"], CP))
        assert approved["status"] == "APPROVED"

    def test_retry_loop_restores_render_cost_on_final_approve(self, api):
        """PRD: "Approval (`QC → APPROVED`) assigns the asset's
        `render_cost_cents` as the asset's own `render_hours_base` multiplied by
        360000 cents per hour, divided by 60 to convert to the per-minute rate,
        then rounded half-up to 2 decimal places; the parent batch's
        `submitted_asset_count` decrements by 1."

        Design: Difficulty/non_linear_state_machine/asset_qc_retry_cycle
        """
        prod = create_active_production(title="AP2", base_price_cents=10000)
        asset = capture_asset(prod["id"], title="AB", render_hours_base=2)
        render_asset_to_qc(asset["id"])
        validate_success(api.qc_fail_asset(asset["id"], CP))
        validate_success(api.retry_asset(asset["id"], CP))
        render_asset_to_qc(asset["id"], settle_clock="2026-09-01T06:00:00Z")
        approved = validate_success(api.qc_approve_asset(asset["id"], CP))
        # round_half_up(2 x 360000 / 60, 2) = 12000
        assert approved["render_cost_cents"] == pytest.approx(12000, abs=0.005)


class TestAssetQCStateGuards:

    def test_qc_approve_rejected_when_asset_not_in_qc(self, api):
        """PRD: "Attempting either QC action on an asset that is not in `QC` —
        for example, because its batch has not yet settled — is rejected with
        `ERR_ASSET_NOT_IN_QC` (HTTP 409)."

        Design: Corner/state_machines/qc_approve_rejected_when_asset_not_in_qc
        """
        prod = create_production(title="QP2", production_type="ORIGINAL", base_price_cents=5000)
        asset = capture_asset(prod["id"], title="QA2", render_hours_base=2)
        assert asset["status"] == "CAPTURED"
        resp = api.qc_approve_asset(asset["id"], CP)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_IN_QC)

    def test_qc_fail_rejected_when_asset_not_in_qc(self, api):
        """PRD: "Attempting either QC action on an asset that is not in `QC` —
        for example, because its batch has not yet settled — is rejected with
        `ERR_ASSET_NOT_IN_QC` (HTTP 409)."

        Design: Corner/state_machines/qc_approve_rejected_when_asset_not_in_qc
        """
        prod = create_production(title="QP3", production_type="ORIGINAL", base_price_cents=5000)
        asset = capture_asset(prod["id"], title="QA3", render_hours_base=2)
        resp = api.qc_fail_asset(asset["id"], CP)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_IN_QC)


class TestAssetArchive:

    def test_archive_rejected_from_captured(self, api):
        """PRD: "An approved asset may be archived (`APPROVED → ARCHIVED`);
        archiving is unconditional."
        PRD §5: "| `ERR_INVALID_STATE` | 409 |"

        Design: Corner/state_machines/asset_archive_only_from_approved
        """
        prod = create_production(title="AR", production_type="ORIGINAL", base_price_cents=5000)
        asset = capture_asset(prod["id"], title="ARA", render_hours_base=2)
        resp = api.archive_asset(asset["id"], CP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_archive_succeeds_from_approved(self, api):
        """PRD: "An approved asset may be archived (`APPROVED → ARCHIVED`);
        archiving is unconditional."

        Design: Corner/state_machines/asset_archive_only_from_approved
        """
        prod, asset = setup_active_production_with_approved_asset(title="AR2", base_price_cents=10000)
        assert asset["status"] == "APPROVED"
        data = validate_success(api.archive_asset(asset["id"], CP))
        assert data["status"] == "ARCHIVED"
