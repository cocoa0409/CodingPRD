"""API client: one method per endpoint defined in the PRD (§4).

All domain paths are mounted under the ``/evote`` prefix. The single
exception is the logical-clock control ``POST /_clock/set_current_utc``,
which lives OUTSIDE the ``/evote`` mount (PRD §2.4 / §4) and is therefore
called at the server root, unprefixed.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Platform logical clock (UNPREFIXED — PRD §2.4) -------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---------------- VotingSystem ----------------
    def create_voting_system(self, payload, headers):
        return self._request("POST", "/evote/voting-systems", payload, headers)

    def get_voting_system(self, system_id, headers):
        return self._request("GET", f"/evote/voting-systems/{system_id}", headers=headers)

    def transition_voting_system(self, system_id, payload, headers):
        return self._request(
            "POST", f"/evote/voting-systems/{system_id}/transitions", payload, headers
        )

    # ---------------- TestLaboratory ----------------
    def create_test_laboratory(self, payload, headers):
        return self._request("POST", "/evote/test-laboratories", payload, headers)

    def get_test_laboratory(self, lab_id, headers):
        return self._request("GET", f"/evote/test-laboratories/{lab_id}", headers=headers)

    def transition_test_laboratory(self, lab_id, payload, headers):
        return self._request(
            "POST", f"/evote/test-laboratories/{lab_id}/transitions", payload, headers
        )

    # ---------------- CertificationCampaign ----------------
    def create_certification_campaign(self, payload, headers):
        return self._request("POST", "/evote/certification-campaigns", payload, headers)

    def list_certification_campaigns(self, headers, params=None):
        return self._request(
            "GET", "/evote/certification-campaigns", headers=headers, params=params
        )

    def get_certification_campaign(self, campaign_id, headers):
        return self._request(
            "GET", f"/evote/certification-campaigns/{campaign_id}", headers=headers
        )

    def transition_certification_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST",
            f"/evote/certification-campaigns/{campaign_id}/transitions",
            payload,
            headers,
        )

    # ---------------- Certificate ----------------
    def list_certificates(self, headers, params=None):
        return self._request("GET", "/evote/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/evote/certificates/{certificate_id}", headers=headers)

    def transition_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/evote/certificates/{certificate_id}/transitions", payload, headers
        )

    # ---------------- Jurisdiction ----------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/evote/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/evote/jurisdictions/{jurisdiction_id}", headers=headers)

    def create_budget_adjustment(self, jurisdiction_id, payload, headers):
        return self._request(
            "POST",
            f"/evote/jurisdictions/{jurisdiction_id}/budget-adjustments",
            payload,
            headers,
        )

    # ---------------- ElectionOfficial ----------------
    def create_official(self, jurisdiction_id, payload, headers):
        return self._request(
            "POST", f"/evote/jurisdictions/{jurisdiction_id}/officials", payload, headers
        )

    def list_officials(self, headers, params=None):
        return self._request("GET", "/evote/officials", headers=headers, params=params)

    def get_official(self, official_id, headers):
        return self._request("GET", f"/evote/officials/{official_id}", headers=headers)

    def transition_official(self, official_id, payload, headers):
        return self._request(
            "POST", f"/evote/officials/{official_id}/transitions", payload, headers
        )

    def list_official_la_tests(self, official_id, headers, params=None):
        return self._request(
            "GET", f"/evote/officials/{official_id}/la-tests", headers=headers, params=params
        )

    def list_official_custody_transfers(self, official_id, headers, params=None):
        return self._request(
            "GET",
            f"/evote/officials/{official_id}/custody-transfers",
            headers=headers,
            params=params,
        )

    # ---------------- Procurement / AcceptanceTest ----------------
    def create_procurement(self, payload, headers):
        return self._request("POST", "/evote/procurements", payload, headers)

    def list_procurements(self, headers, params=None):
        return self._request("GET", "/evote/procurements", headers=headers, params=params)

    def get_procurement(self, procurement_id, headers):
        return self._request("GET", f"/evote/procurements/{procurement_id}", headers=headers)

    def transition_procurement(self, procurement_id, payload, headers):
        return self._request(
            "POST", f"/evote/procurements/{procurement_id}/transitions", payload, headers
        )

    def create_acceptance_test(self, procurement_id, payload, headers):
        return self._request(
            "POST",
            f"/evote/procurements/{procurement_id}/acceptance-tests",
            payload,
            headers,
        )

    def list_acceptance_tests(self, procurement_id, headers, params=None):
        return self._request(
            "GET",
            f"/evote/procurements/{procurement_id}/acceptance-tests",
            headers=headers,
            params=params,
        )

    # ---------------- ElectionDefinition ----------------
    def create_election_definition(self, payload, headers):
        return self._request("POST", "/evote/election-definitions", payload, headers)

    def list_election_definitions(self, headers, params=None):
        return self._request("GET", "/evote/election-definitions", headers=headers, params=params)

    def get_election_definition(self, definition_id, headers):
        return self._request(
            "GET", f"/evote/election-definitions/{definition_id}", headers=headers
        )

    def put_layout(self, definition_id, payload, headers):
        return self._request(
            "PUT", f"/evote/election-definitions/{definition_id}/layout", payload, headers
        )

    def transition_election_definition(self, definition_id, payload, headers):
        return self._request(
            "POST",
            f"/evote/election-definitions/{definition_id}/transitions",
            payload,
            headers,
        )

    def get_readiness(self, definition_id, headers):
        return self._request(
            "GET", f"/evote/election-definitions/{definition_id}/readiness", headers=headers
        )

    def get_print_estimate(self, definition_id, headers, params=None):
        return self._request(
            "GET",
            f"/evote/election-definitions/{definition_id}/print-estimate",
            headers=headers,
            params=params,
        )

    # ---------------- LogicAccuracyTest ----------------
    def create_la_test(self, definition_id, payload, headers):
        return self._request(
            "POST", f"/evote/election-definitions/{definition_id}/la-tests", payload, headers
        )

    def list_la_tests(self, definition_id, headers, params=None):
        return self._request(
            "GET",
            f"/evote/election-definitions/{definition_id}/la-tests",
            headers=headers,
            params=params,
        )

    def transition_la_test(self, la_test_id, payload, headers):
        return self._request(
            "POST", f"/evote/logic-accuracy-tests/{la_test_id}/transitions", payload, headers
        )

    # ---------------- EquipmentUnit ----------------
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/evote/equipment-units", payload, headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/evote/equipment-units", headers=headers, params=params)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"/evote/equipment-units/{unit_id}", headers=headers)

    def transition_equipment_unit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/evote/equipment-units/{unit_id}/transitions", payload, headers
        )

    def record_usage(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/evote/equipment-units/{unit_id}/record-usage", payload, headers
        )

    def create_custody_transfer(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/evote/equipment-units/{unit_id}/custody-transfers", payload, headers
        )

    def list_custody_transfers(self, unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/evote/equipment-units/{unit_id}/custody-transfers",
            headers=headers,
            params=params,
        )

    def list_unit_work_orders(self, unit_id, headers, params=None):
        return self._request(
            "GET",
            f"/evote/equipment-units/{unit_id}/maintenance-work-orders",
            headers=headers,
            params=params,
        )

    # ---------------- MaintenanceWorkOrder ----------------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/evote/maintenance-work-orders", payload, headers)

    def transition_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"/evote/maintenance-work-orders/{work_order_id}/transitions",
            payload,
            headers,
        )

    # ---------------- SoftwareModification ----------------
    def create_software_modification(self, payload, headers):
        return self._request("POST", "/evote/software-modifications", payload, headers)

    def list_software_modifications(self, system_id, headers, params=None):
        return self._request(
            "GET",
            f"/evote/voting-systems/{system_id}/software-modifications",
            headers=headers,
            params=params,
        )

    def transition_software_modification(self, modification_id, payload, headers):
        return self._request(
            "POST",
            f"/evote/software-modifications/{modification_id}/transitions",
            payload,
            headers,
        )

    # ---------------- PostElectionAudit ----------------
    def create_post_election_audit(self, payload, headers):
        return self._request("POST", "/evote/post-election-audits", payload, headers)

    def list_post_election_audits(self, definition_id, headers, params=None):
        return self._request(
            "GET",
            f"/evote/election-definitions/{definition_id}/post-election-audits",
            headers=headers,
            params=params,
        )

    def transition_post_election_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/evote/post-election-audits/{audit_id}/transitions", payload, headers
        )

    def publish_post_election_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/evote/post-election-audits/{audit_id}/publish", {}, headers
        )

    # ---------------- Public transparency ----------------
    def get_public_documentation(self, system_id, headers):
        return self._request(
            "GET", f"/evote/public/voting-systems/{system_id}/documentation", headers=headers
        )


api_client = ApiClient()
