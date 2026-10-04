"""Transitive cascades: agreement termination and audit finding issuance."""
from test_helpers import (
    TEST_USERS,
    create_audit,
    create_finalized_sales_report,
    create_order,
    setup_active_chain,
    validate_success,
)

CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
AUD = TEST_USERS["auditor_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


class TestAgreementTerminateCascade:
    def test_terminate_cascades_vehicle_list_order(self, api):
        """PRD §3.9: "Termination sets posture to SUSPENDED per the derivation
        rule, and cascades broadly: every vehicle under the agreement moves to
        EXPIRED; every teaming arrangement moves to TERMINATED; every ACTIVE
        price list moves to SUPERSEDED; and every order still in billing
        status UNBILLED with compliance status DRAFT, SCREENING, or CLEARED is
        moved to compliance CANCELLED, with each cancellation recomputing its
        vehicle's prc_accumulator_cents."

        Design: Difficulty/transitive_cascade/agreement_terminate_four_hop_cascade
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        order = create_order(vehicle["id"], price_list["id"])
        resp = api.terminate_agreement(agreement["id"], CO)
        agreement = validate_success(resp)
        assert agreement["status"] == "TERMINATED"
        vehicle = validate_success(api.get_vehicle(vehicle["id"], CM))
        assert vehicle["status"] == "EXPIRED"
        price_list = validate_success(api.get_price_list(price_list["id"], CM))
        assert price_list["status"] == "SUPERSEDED"
        order = validate_success(api.get_order(order["id"], OPS))
        assert order["compliance_status"] == "CANCELLED"

    def test_terminated_agreement_posture_suspended(self, api):
        """PRD §2.6: "The derivation is: if the agreement's status is
        TERMINATED, posture is SUSPENDED; otherwise, if status is SUSPENDED,
        posture is SUSPENDED; otherwise, if dispute_credit_cents is strictly
        less than -100000 (that is, net debt has crossed $1,000.00), posture
        is ON_HOLD; otherwise posture is GOOD_STANDING."

        Design: Difficulty/transitive_cascade/agreement_terminate_four_hop_cascade
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        create_order(vehicle["id"], price_list["id"])
        api.terminate_agreement(agreement["id"], CO)
        agreement = validate_success(api.get_agreement(agreement["id"], CM))
        assert agreement["status"] == "TERMINATED"
        assert agreement["posture"] == "SUSPENDED"

    def test_cleared_unbilled_order_cancelled_by_terminate(self, api):
        """PRD §3.9: "every order still in billing status UNBILLED with
        compliance status DRAFT, SCREENING, or CLEARED is moved to compliance
        CANCELLED, with each cancellation recomputing its vehicle's
        prc_accumulator_cents."

        Design: Difficulty/transitive_cascade/agreement_terminate_four_hop_cascade
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        order = create_order(vehicle["id"], price_list["id"])
        order = validate_success(api.submit_order(order["id"], OPS))
        assert order["compliance_status"] == "CLEARED"
        api.terminate_agreement(agreement["id"], CO)
        order = validate_success(api.get_order(order["id"], OPS))
        assert order["compliance_status"] == "CANCELLED"
        price_list = validate_success(api.get_price_list(price_list["id"], CM))
        assert price_list["status"] == "SUPERSEDED"


class TestAuditFindingCascade:
    def test_material_finding_suspends_agreement_and_vehicles(self, api):
        """PRD §3.9: "A successful finding moves the audit to FINDING_ISSUED
        and cascades: the agreement's status moves from ACTIVE to SUSPENDED,
        with all the downstream vehicle and teaming suspensions that implies."
        PRD §3.9: "Suspension of the agreement by a ComplianceOfficer
        cascades: every AUTHORIZED vehicle under the agreement moves to
        SUSPENDED, and every APPROVED teaming arrangement moves to SUSPENDED."

        Design: Difficulty/transitive_cascade/audit_finding_two_hop_cascade
        """
        _, agreement, vehicle, _ = setup_active_chain()
        # Variance: disclosed (no finalized reports) = 0; attestation 500000
        # -> variance 500000 > 250000 materiality.
        audit = create_audit(agreement["id"], mfc_attestation_cents=500000)
        resp = api.issue_finding(audit["id"], AUD)
        audit = validate_success(resp)
        assert audit["status"] == "FINDING_ISSUED"
        agreement = validate_success(api.get_agreement(agreement["id"], CM))
        assert agreement["status"] == "SUSPENDED"
        vehicle = validate_success(api.get_vehicle(vehicle["id"], CM))
        assert vehicle["status"] == "SUSPENDED"

    def test_finding_sets_agreement_posture_suspended(self, api):
        """PRD §2.6: "otherwise, if status is SUSPENDED, posture is SUSPENDED;
        otherwise, if dispute_credit_cents is strictly less than -100000 (that
        is, net debt has crossed $1,000.00), posture is ON_HOLD; otherwise
        posture is GOOD_STANDING."
        PRD §2.6: "Posture is recomputed on every mutation chain that touches
        the ledger or the agreement status — dispute raise, dispute resolve,
        suspend, reinstate, terminate, and audit-finding issuance."

        Design: Difficulty/transitive_cascade/audit_finding_two_hop_cascade
        """
        _, agreement, vehicle, _ = setup_active_chain()
        create_finalized_sales_report(agreement["id"], period_label="2026-08")
        audit = create_audit(agreement["id"], mfc_attestation_cents=500000)
        api.issue_finding(audit["id"], AUD)
        agreement = validate_success(api.get_agreement(agreement["id"], CM))
        assert agreement["posture"] == "SUSPENDED"
        vehicle = validate_success(api.get_vehicle(vehicle["id"], CM))
        assert vehicle["status"] == "SUSPENDED"
