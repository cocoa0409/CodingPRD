"""License fee variants, license term boundaries, and ops-run sweeps."""
from test_helpers import (
    ADMIN,
    ET,
    RM,
    api_client,
    get_success_data,
    record_calibration,
    set_clock,
    setup_base,
    setup_dealer,
    setup_equipment,
    setup_license,
    setup_onboarded_dealer,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


def _setup_onboarding_dealer_with_active_license():
    """Region + system + ONBOARDING dealer + unit + license activated by a
    PASS calibration (PRD section 3.3). No line / no stock order needed."""
    ctx = setup_base(with_line=False)
    dealer = setup_dealer(ctx["region"]["id"], branding_compliant=True)
    get_success_data(api_client.begin_onboarding(dealer["id"], RM))
    equip = setup_equipment(dealer["id"], ctx["system"]["id"])
    lic = setup_license(dealer["id"], ctx["system"]["id"])
    record_calibration(equip["id"], "PASS")
    ctx["dealer"] = get_success_data(api_client.get_dealer(dealer["id"], RM))
    ctx["equipment"] = equip
    ctx["license"] = lic
    return ctx


class TestLicenseFeeVariants:
    def test_renew_active_charges_full_annual_fee(self, api):
        """PRD section 3.3: "Renewing an `ACTIVE` license charges the full
        annual fee regardless of how many days remain — even with 364 days
        left — setting `fee_basis` to `FULL`, `fee_charged_cents` to the
        system's `annual_license_fee_cents`, and `expires_on` to 365 days
        from now."

        Design: Difficulty/dual_variant_calc/license_fee_full_vs_prorated_variants
        """
        ctx = _setup_onboarding_dealer_with_active_license()
        resp = api.renew_license(ctx["license"]["id"], RM)
        data = validate_success(resp)
        assert data["fee_basis"] == "FULL"
        assert data["fee_charged_cents"] == 2_500_000

    def test_renew_expired_charges_prorated_zero(self, api):
        """PRD section 3.3: "Renewing an `EXPIRED` license revives it on
        prorated terms: `fee_basis` becomes `PRORATED` and the fee is the
        annual fee multiplied by the number of whole days remaining until the
        old `expires_on`, divided by 365, rounded half-up to integer cents —
        computed against the expiry in force before the renewal resets it;
        because the license has already expired, that day count is floored at
        zero and the fee is 0."
        PRD section 2.7: "An active color license whose `expires_on` has been
        reached — the current logical time is at or after `expires_on` —
        transitions to `EXPIRED` on any read of that license or on an ops-run
        sweep."

        Design: Difficulty/dual_variant_calc/license_fee_full_vs_prorated_variants
        """
        ctx = _setup_onboarding_dealer_with_active_license()
        lic_id = ctx["license"]["id"]
        # First renew from ACTIVE (full fee), then let the renewed term lapse.
        first = validate_success(api.renew_license(lic_id, RM))
        assert first["fee_basis"] == "FULL"
        assert first["fee_charged_cents"] == 2_500_000
        # Renewed expiry is 2027-09-01; advance past it and read to flip EXPIRED.
        set_clock("2027-10-01T00:00:00Z")
        expired = validate_success(api.get_license(lic_id, RM))
        assert expired["status"] == "EXPIRED"
        second = validate_success(api.renew_license(lic_id, RM))
        assert second["fee_basis"] == "PRORATED"
        assert second["fee_charged_cents"] == 0
        # The two renewal charges for the same license diverge by the full fee.
        assert first["fee_charged_cents"] - second["fee_charged_cents"] == 2_500_000


class TestLicenseTermAdjacency:
    def test_license_expires_at_exact_expiry_instant(self, api):
        """PRD section 2.7: "An active color license whose `expires_on` has
        been reached — the current logical time is at or after `expires_on` —
        transitions to `EXPIRED` on any read of that license or on an ops-run
        sweep."

        Design: Difficulty/resource_temporal_overlap/license_term_adjacency_no_overlap
        """
        ctx = _setup_onboarding_dealer_with_active_license()
        # License activated at 2026-09-01 -> expires_on 2027-09-01.
        set_clock("2027-09-01T00:00:00Z")
        at_boundary = validate_success(api.get_license(ctx["license"]["id"], RM))
        assert at_boundary["status"] == "EXPIRED"

    def test_renew_at_adjacency_charges_zero_and_starts_fresh_term(self, api):
        """PRD section 3.3: "Renewing an `EXPIRED` license revives it on
        prorated terms: `fee_basis` becomes `PRORATED` and the fee is the
        annual fee multiplied by the number of whole days remaining until the
        old `expires_on`, divided by 365, rounded half-up to integer cents ...
        because the license has already expired, that day count is floored at
        zero and the fee is 0. In both variants `expires_on` resets to 365
        days from the renewal instant and the license returns to `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/license_term_adjacency_no_overlap
        """
        ctx = _setup_onboarding_dealer_with_active_license()
        set_clock("2027-09-01T00:00:00Z")
        renewed = validate_success(api.renew_license(ctx["license"]["id"], RM))
        assert renewed["status"] == "ACTIVE"
        assert renewed["fee_basis"] == "PRORATED"
        assert renewed["fee_charged_cents"] == 0
        # 365 days from 2027-09-01 is 2028-08-31 (the term spans the
        # 2028-02-29 leap day).
        assert renewed["expires_on"].startswith("2028-08-31")


class TestOpsRunSweeps:
    def test_ops_run_marks_overdue_equipment_and_expired_license(self, api):
        """PRD section 2.7: "A `PlatformAdmin` may invoke an ops-run
        checkpoint that performs all three sweeps eagerly: it marks every
        `CALIBRATED` unit past its `calibration_due_on` as
        `CALIBRATION_OVERDUE`, moves every `ACTIVE` license at or past
        `expires_on` to `EXPIRED`, and clears `rematch_pending` on formulas
        whose formulation change has no `PENDING` rematch tasks left. The
        sweep response reports `equipment_marked_overdue`, `licenses_expired`,
        and `rematch_flags_cleared` counts."

        Design: Corner/endpoints/ops_run_sweeps_overdue_equipment_and_expired_license
        """
        ctx = _setup_onboarding_dealer_with_active_license()
        set_clock("2027-10-01T00:00:00Z")
        summary = validate_success(api.ops_run(ADMIN))
        # The unit is 10 months past its 90-day calibration due date, so the
        # equipment sweep fires. Per PRD section 3.3 the overdue sweep
        # cascades the license ACTIVE -> SUSPENDED; whether the §2.7 expiry
        # sweep also reports such a license as expired is unspecified, so
        # only the equipment count is asserted.
        assert summary["equipment_marked_overdue"] == 1
        equip = validate_success(api.get_equipment(ctx["equipment"]["id"], ET))
        assert equip["status"] == "CALIBRATION_OVERDUE"
        lic = validate_success(api.get_license(ctx["license"]["id"], RM))
        assert lic["status"] in ("SUSPENDED", "EXPIRED")

    def test_ops_run_suspends_license_when_unit_becomes_overdue(self, api):
        """PRD section 2.7: "The license-suspension cascade triggered by
        newly overdue equipment (§3.3) applies during the sweep exactly as it
        does on lazy reads."
        PRD section 3.3: "whenever a `FAIL` calibration or an overdue sweep
        leaves no `CALIBRATED` unit for the license's colorant system at that
        dealer, the license cascades from `ACTIVE` to `SUSPENDED`".

        Design: Corner/endpoints/ops_run_sweeps_overdue_equipment_and_expired_license
        """
        ctx = _setup_onboarding_dealer_with_active_license()
        # Advance past calibration_due_on (2026-11-30) but before license
        # expiry (2027-09-01) so only the equipment sweep fires.
        set_clock("2026-12-01T00:00:00Z")
        summary = validate_success(api.ops_run(ADMIN))
        assert summary["equipment_marked_overdue"] == 1
        assert summary["licenses_expired"] == 0
        equip = validate_success(api.get_equipment(ctx["equipment"]["id"], ET))
        assert equip["status"] == "CALIBRATION_OVERDUE"
        lic = validate_success(api.get_license(ctx["license"]["id"], RM))
        assert lic["status"] == "SUSPENDED"
