"""PQR lifecycle and WPS approval gates: state checks, segregation of duties,
welding-code agreement, and the inclusive thickness envelope."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_pqr,
    approve_wps,
    create_and_approve_pqr,
    create_pqr,
    create_shop,
    create_wps,
    get_success_data,
    make_qc_manager_headers,
    validate_error,
    validate_success,
)

QC_MANAGER = TEST_USERS["qc_manager_headers"]


class TestPqrLifecycle:
    def test_pqr_approve_from_approved_returns_invalid_state(self, api):
        """PRD §3.1: "Approving it — again a `QCManager` action — requires
        that it still be `DRAFT` (otherwise `ERR_PQR_NOT_DRAFT`) and that its
        thickness window be well formed, meaning the maximum is strictly
        greater than the minimum (otherwise `ERR_INVALID_THICKNESS_RANGE`)."

        Design: Corner/state_machines/pqr_approve_from_approved_returns_invalid_state
        """
        shop = create_shop(shop_name="PQR State Shop")
        pqr = create_and_approve_pqr(shop["id"], pqr_number="PQR-Q1")
        assert pqr["status"] == "APPROVED"

        resp = api.approve_pqr(shop["id"], pqr["id"], QC_MANAGER)
        validate_error(resp, ApiErrorId.ERR_PQR_NOT_DRAFT)

    def test_pqr_terminal_rejected_lockdown(self, api):
        """PRD §3.1: "A `QCManager` may instead reject a `DRAFT` PQR, moving
        it to `REJECTED` and incrementing its `version`. Both `APPROVED` and
        `REJECTED` are terminal for the PQR."
        PRD §3.1: "Approving it — again a `QCManager` action — requires that
        it still be `DRAFT` (otherwise `ERR_PQR_NOT_DRAFT`)"

        Design: Corner/state_machines/pqr_terminal_rejected_lockdown
        """
        shop = create_shop(shop_name="PQR Reject Shop")
        pqr = create_pqr(shop["id"], pqr_number="PQR-Q2")

        rejected = validate_success(
            api.reject_pqr(shop["id"], pqr["id"], QC_MANAGER), 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["version"] == pqr["version"] + 1

        resp = api.approve_pqr(shop["id"], pqr["id"], QC_MANAGER)
        validate_error(resp, ApiErrorId.ERR_PQR_NOT_DRAFT)

    def test_pqr_thickness_range_validation(self, api):
        """PRD §3.1: "Approving it — again a `QCManager` action — requires
        that it still be `DRAFT` (otherwise `ERR_PQR_NOT_DRAFT`) and that its
        thickness window be well formed, meaning the maximum is strictly
        greater than the minimum (otherwise `ERR_INVALID_THICKNESS_RANGE`)."

        Design: Corner/entities/pqr_thickness_range_validation
        """
        shop = create_shop(shop_name="PQR Range Shop")
        pqr = create_pqr(shop["id"], pqr_number="PQR-BAD",
                         thickness_range_min_mm=25.0,
                         thickness_range_max_mm=3.0)

        resp = api.approve_pqr(shop["id"], pqr["id"], QC_MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_THICKNESS_RANGE)


class TestWpsApprovalGates:
    def test_wps_approve_with_unapproved_pqr_returns_error(self, api):
        """PRD §3.1: "Then the lifecycle gates: the revision itself must be
        `DRAFT` (`ERR_WPS_NOT_DRAFT`), and the referenced PQR must be
        `APPROVED` at that moment (`ERR_PQR_NOT_APPROVED`)."

        Design: Corner/state_machines/wps_approve_with_unapproved_pqr_returns_error
        """
        shop = create_shop(shop_name="WPS Gate Shop")
        pqr = create_pqr(shop["id"], pqr_number="PQR-Q7")  # stays DRAFT
        wps = create_wps(shop["id"], pqr["id"], wps_number="WPS-Q7")

        resp = api.approve_wps(
            shop["id"], wps["id"],
            {"expected_wps_version": wps["version"]},
            QC_MANAGER)
        validate_error(resp, ApiErrorId.ERR_PQR_NOT_APPROVED)

    def test_wps_approve_process_mismatch_returns_error(self, api):
        """PRD §3.1: "Then welding-code agreement: the WPS `process` must
        equal the PQR `process` (`ERR_WPS_PQR_PROCESS_MISMATCH`) and the WPS
        `base_metal_spec` must equal the PQR `base_metal_spec`
        (`ERR_WPS_PQR_MATERIAL_MISMATCH`)."

        Design: Corner/state_machines/wps_approve_process_mismatch_returns_error
        """
        shop = create_shop(shop_name="WPS Process Shop")
        pqr = create_and_approve_pqr(shop["id"], pqr_number="PQR-Q8",
                                     process="SMAW")
        wps = create_wps(shop["id"], pqr["id"], wps_number="WPS-Q8",
                         process="GMAW")

        resp = api.approve_wps(
            shop["id"], wps["id"],
            {"expected_wps_version": wps["version"]},
            QC_MANAGER)
        validate_error(resp, ApiErrorId.ERR_WPS_PQR_PROCESS_MISMATCH)


class TestWpsThicknessEnvelope:
    """The WPS envelope must sit inside the PQR envelope with inclusive
    boundaries (PRD §3.1)."""

    def test_wps_envelope_exact_match_approves(self, api):
        """PRD §3.1: "Then the thickness envelope, evaluated with inclusive
        boundaries: the WPS `thickness_min_mm` must be at least the PQR
        `thickness_range_min_mm`, and the WPS `thickness_max_mm` must be at
        most the PQR `thickness_range_max_mm` — a WPS envelope that exactly
        matches the PQR envelope passes, and any protrusion is rejected with
        `ERR_WPS_THICKNESS_OUTSIDE_PQR`."

        Design: Difficulty/combinatorial_formula/wps_thickness_envelope_3input_conditional
        """
        shop = create_shop(shop_name="Envelope Exact Shop")
        pqr = create_and_approve_pqr(shop["id"], pqr_number="PQR-3",
                                     thickness_range_min_mm=3.00,
                                     thickness_range_max_mm=25.00)
        wps = create_wps(shop["id"], pqr["id"], wps_number="WPS-3A",
                         thickness_min_mm=3.00, thickness_max_mm=25.00)

        approved = approve_wps(shop["id"], wps["id"])
        assert approved["status"] == "APPROVED", (
            "An envelope exactly matching the PQR envelope passes")

    def test_wps_envelope_max_protrusion_rejected(self, api):
        """PRD §3.1: "Then the thickness envelope, evaluated with inclusive
        boundaries: the WPS `thickness_min_mm` must be at least the PQR
        `thickness_range_min_mm`, and the WPS `thickness_max_mm` must be at
        most the PQR `thickness_range_max_mm` — a WPS envelope that exactly
        matches the PQR envelope passes, and any protrusion is rejected with
        `ERR_WPS_THICKNESS_OUTSIDE_PQR`."

        Design: Difficulty/combinatorial_formula/wps_thickness_envelope_3input_conditional
        """
        shop = create_shop(shop_name="Envelope Max Shop")
        pqr = create_and_approve_pqr(shop["id"], pqr_number="PQR-3",
                                     thickness_range_min_mm=3.00,
                                     thickness_range_max_mm=25.00)
        wps = create_wps(shop["id"], pqr["id"], wps_number="WPS-3B",
                         thickness_min_mm=3.00, thickness_max_mm=25.01)

        resp = api.approve_wps(
            shop["id"], wps["id"],
            {"expected_wps_version": wps["version"]},
            QC_MANAGER)
        validate_error(resp, ApiErrorId.ERR_WPS_THICKNESS_OUTSIDE_PQR)

    def test_wps_envelope_min_protrusion_rejected(self, api):
        """PRD §3.1: "Then the thickness envelope, evaluated with inclusive
        boundaries: the WPS `thickness_min_mm` must be at least the PQR
        `thickness_range_min_mm`, and the WPS `thickness_max_mm` must be at
        most the PQR `thickness_range_max_mm` — a WPS envelope that exactly
        matches the PQR envelope passes, and any protrusion is rejected with
        `ERR_WPS_THICKNESS_OUTSIDE_PQR`."

        Design: Difficulty/combinatorial_formula/wps_thickness_envelope_3input_conditional
        """
        shop = create_shop(shop_name="Envelope Min Shop")
        pqr = create_and_approve_pqr(shop["id"], pqr_number="PQR-3",
                                     thickness_range_min_mm=3.00,
                                     thickness_range_max_mm=25.00)
        wps = create_wps(shop["id"], pqr["id"], wps_number="WPS-3C",
                         thickness_min_mm=2.99, thickness_max_mm=25.00)

        resp = api.approve_wps(
            shop["id"], wps["id"],
            {"expected_wps_version": wps["version"]},
            QC_MANAGER)
        validate_error(resp, ApiErrorId.ERR_WPS_THICKNESS_OUTSIDE_PQR)


class TestWpsApproveValidationOrder:
    """WPS approval evaluates the lifecycle gate before segregation of duties
    (PRD §3.1 fixed order; PRD §2.8 precedence)."""

    def _approved_pqr_and_wps(self, api, reviewer_id):
        shop = create_shop(shop_name="Order Shop")
        pqr = create_pqr(shop["id"], pqr_number="PQR-9")
        approve_pqr(shop["id"], pqr["id"], reviewer_id)
        wps = create_wps(shop["id"], pqr["id"], wps_number="WPS-9")
        return shop, pqr, wps

    def test_state_gate_precedes_segregation_on_approve(self, api):
        """PRD §3.1: "Then the lifecycle gates: the revision itself must be
        `DRAFT` (`ERR_WPS_NOT_DRAFT`), and the referenced PQR must be
        `APPROVED` at that moment (`ERR_PQR_NOT_APPROVED`). Then segregation
        of duties: the approving `X-User-ID` must differ from the
        `reviewed_by_user_id` recorded on the supporting PQR — the same
        person may not review a qualification record and approve the
        procedure built on it (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."
        PRD §2.8: "Only after state checks pass do business rules run, in
        this order: segregation-of-duties and welding-code safety checks
        (WPS/PQR process and material agreement, the thickness envelope,
        welder continuity, consumable-lot usability)"

        The WPS is already APPROVED and the caller is the PQR reviewer; the
        state gate fires first, so the error is ERR_WPS_NOT_DRAFT.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_wps_approve
        """
        shop, _, wps = self._approved_pqr_and_wps(api, reviewer_id="qc-U1")
        # First approval by a different QCManager — segregation satisfied.
        approve_wps(shop["id"], wps["id"], approver_id="qc-U2")

        # Re-approve attempt by the PQR reviewer, carrying the CURRENT
        # version so only the state and segregation gates could fire.
        fresh = get_success_data(api.get_wps(shop["id"], wps["id"],
                                             TEST_USERS["shop_admin_headers"]))
        resp = api.approve_wps(
            shop["id"], wps["id"],
            {"expected_wps_version": fresh["version"]},
            make_qc_manager_headers("qc-U1"))
        validate_error(resp, ApiErrorId.ERR_WPS_NOT_DRAFT)

    def test_segregation_fires_when_state_passes(self, api):
        """PRD §3.1: "Then segregation of duties: the approving `X-User-ID`
        must differ from the `reviewed_by_user_id` recorded on the supporting
        PQR — the same person may not review a qualification record and
        approve the procedure built on it (`ERR_SEGREGATION_OF_DUTIES`,
        HTTP 403)."

        The WPS is still DRAFT and the caller equals the PQR reviewer, so
        evaluation reaches the segregation rule and rejects with
        ERR_SEGREGATION_OF_DUTIES.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_wps_approve
        """
        shop, _, wps = self._approved_pqr_and_wps(api, reviewer_id="qc-U1")

        resp = api.approve_wps(
            shop["id"], wps["id"],
            {"expected_wps_version": wps["version"]},
            make_qc_manager_headers("qc-U1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
