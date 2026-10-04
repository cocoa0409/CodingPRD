"""Enrollment deferral cycle and the financial-hold re-registration gate."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, setup_registered_enrollment,
    create_aid_package, set_clock,
)

REGISTRAR = TEST_USERS["registrar_headers"]
FAO1 = TEST_USERS["fao1_headers"]


class TestEnrollmentDeferCycleGatedByFinancialHold:
    def _setup_deferred_with_packaged_aid(self):
        ctx = setup_registered_enrollment(intensity="FULL_TIME",
                                          tuition_cents=500000)
        create_aid_package(ctx["enrollment"]["id"], 0, FAO1)  # stays PACKAGED
        return ctx

    def test_registered_to_deferred_succeeds(self):
        """PRD §3.9: "A `RegistrarAdmin` defers a `REGISTERED` or `ACTIVE`
        enrollment by naming `to_state` `DEFERRED`, moving it `REGISTERED` →
        `DEFERRED` or `ACTIVE` → `DEFERRED` with a `version` bump."

        Design: Difficulty/non_linear_state_machine/enrollment_defer_cycle_gated_by_financial_hold
        """
        ctx = self._setup_deferred_with_packaged_aid()
        resp = api_client.defer_enrollment(
            ctx["enrollment"]["id"], "DEFERRED", REGISTRAR)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "DEFERRED", (
            f"REGISTERED -> DEFERRED is the first leg of the cycle; got "
            f"{data['status']}")

    def test_deferred_to_registered_blocked_by_financial_hold(self):
        """PRD §3.9: "Coming back is the re-registration cycle: naming
        `to_state` `REGISTERED` on a `DEFERRED` enrollment passes two gates
        in order — the term must be `ENROLLMENT_OPEN`, otherwise
        `ERR_TERM_NOT_OPEN`, and the enrollment's `financial_hold` must be
        false, otherwise `ERR_FINANCIAL_HOLD`. The `financial_hold` flag is
        computed, not stored: it is true exactly when the enrollment's latest
        financial aid package is still in `PACKAGED` and the current logical
        date is later than the term's `census_date` — a student whose aid was
        never certified past the census snapshot cannot quietly re-register."

        Design: Difficulty/non_linear_state_machine/enrollment_defer_cycle_gated_by_financial_hold
        """
        ctx = self._setup_deferred_with_packaged_aid()
        validate_success(api_client.defer_enrollment(
            ctx["enrollment"]["id"], "DEFERRED", REGISTRAR),
            expected_status=200)
        # Move past the census date (2026-10-19) while the package is still
        # PACKAGED; the term is still ENROLLMENT_OPEN, so only the hold bites.
        set_clock("2026-10-20T00:00:00Z")
        enrollment = get_success_data(
            api_client.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
        assert enrollment["financial_hold"] is True, (
            "PACKAGED package past census_date must raise financial_hold")
        resp = api_client.defer_enrollment(
            ctx["enrollment"]["id"], "REGISTERED", REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_FINANCIAL_HOLD)
