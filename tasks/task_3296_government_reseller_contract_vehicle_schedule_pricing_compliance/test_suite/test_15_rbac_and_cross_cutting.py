"""Corner coverage: RBAC denials and cross-cutting complexity (OCC, cascades)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_agreement,
    create_approved_teaming,
    create_audit,
    create_price_modification_payload,
    setup_active_chain,
    validate_error,
    validate_success,
)

CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
AUD = TEST_USERS["auditor_headers"]
INT = TEST_USERS["integrator_headers"]


class TestRbacDenials:
    def test_integrator_cannot_activate_price_list(self, api):
        """PRD §2.1: "ComplianceOfficer — compliance reviewer; suspends,
        reinstates, and terminates agreements; suspends, reinstates, and
        expires vehicles; activates and rejects price lists; approves and
        rejects price modifications; approves, suspends, and reinstates
        teaming arrangements; resolves disputes; closes audits; and may also
        raise disputes."
        PRD §2.1: "When the supplied role is not a declared role, or when the
        role is declared but is not permitted on the endpoint per the RBAC
        matrix, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/integrator_cannot_activate_price_list
        """
        from test_helpers import create_submitted_price_list

        _, _, vehicle, _ = setup_active_chain()
        price_list = create_submitted_price_list(vehicle["id"])
        resp = api.activate_price_list(price_list["id"], INT)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_auditor_cannot_close_audit(self, api):
        """PRD §3.9: "The auditor cannot also reinstate the agreement or close
        the finding — closure is performed by a ComplianceOfficer."
        PRD §2.1: "Auditor — external auditor; opens compliance audits and
        issues findings (exclusive); cannot close own findings (segregation of
        duties)."

        Design: Corner/rbac/auditor_cannot_close_own_finding_sod
        """
        _, agreement, _, _ = setup_active_chain()
        audit = create_audit(agreement["id"], mfc_attestation_cents=500000)
        resp = api.issue_finding(audit["id"], AUD)
        validate_success(resp)
        resp = api.close_audit(audit["id"], AUD)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestOccStalePriceListVersion:
    def test_stale_expected_version_rejected_412(self, api):
        """PRD §2.8: "Creating a price modification requires
        expected_price_list_version matching the target PriceList's current
        version. A mismatch is rejected with ERR_STALE_PRICE_LIST_VERSION
        (HTTP 412). This captures the case where another writer has just
        approved a different modification (which bumps the list's version) and
        the current writer's view of the list is therefore stale."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_price_list_version_412
        """
        _, _, _, price_list = setup_active_chain()
        pl = validate_success(api.get_price_list(price_list["id"], CM))
        stale_version = pl["version"]
        resp = api.create_price_modification(
            create_price_modification_payload(
                price_list["id"], stale_version, new_offered_price_cents=9000,
            ),
            CM,
        )
        mod1 = validate_success(resp, expected_status=201)
        # Approving bumps the list's version, so the earlier observation is stale.
        validate_success(api.approve_price_modification(mod1["id"], CO))
        resp = api.create_price_modification(
            create_price_modification_payload(
                price_list["id"], stale_version, new_offered_price_cents=8000,
            ),
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PRICE_LIST_VERSION)


class TestAgreementSuspendReinstateCascade:
    def test_suspend_cascades_and_reinstate_restores(self, api):
        """PRD §3.9: "Suspension of the agreement by a ComplianceOfficer
        cascades: every AUTHORIZED vehicle under the agreement moves to
        SUSPENDED, and every APPROVED teaming arrangement moves to SUSPENDED."
        PRD §3.9: "on reinstatement, posture is recomputed via the standard
        derivation, and any vehicle whose earlier suspension came from the
        cascade — flagged as cascade-induced — returns to AUTHORIZED."

        Design: Corner/cross_cutting_complexity_layers/cascading_suspend_reinstates_vehicles
        """
        _, agreement, vehicle, _ = setup_active_chain()
        teaming = create_approved_teaming(
            agreement["id"], vehicle["id"],
            integrator_name="Int Y", small_business=True,
        )
        resp = api.suspend_agreement(agreement["id"], CO)
        agreement = validate_success(resp)
        assert agreement["status"] == "SUSPENDED"
        vehicle = validate_success(api.get_vehicle(vehicle["id"], CM))
        assert vehicle["status"] == "SUSPENDED"
        teaming = validate_success(api.get_teaming(teaming["id"], CM))
        assert teaming["status"] == "SUSPENDED"
        resp = api.reinstate_agreement(agreement["id"], CO)
        agreement = validate_success(resp)
        assert agreement["status"] == "ACTIVE"
        vehicle = validate_success(api.get_vehicle(vehicle["id"], CM))
        assert vehicle["status"] == "AUTHORIZED"
