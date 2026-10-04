"""API client: one method per endpoint the scoring platform exposes."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Bureau registry ──────────────────────────────
    def create_bureau(self, payload, headers):
        return self._request("POST", "/bureaus", payload, headers)

    def get_bureau(self, bureau_id, headers):
        return self._request("GET", f"/bureaus/{bureau_id}", headers=headers)

    def list_bureaus(self, headers, params=None):
        return self._request("GET", "/bureaus", headers=headers, params=params)

    # ─── Score model versions ─────────────────────────
    def create_score_model(self, payload, headers):
        return self._request("POST", "/score-models", payload, headers)

    def get_score_model(self, model_id, headers):
        return self._request("GET", f"/score-models/{model_id}", headers=headers)

    def list_score_models(self, headers, params=None):
        return self._request("GET", "/score-models", headers=headers, params=params)

    def create_variant(self, model_id, payload, headers):
        return self._request("POST", f"/score-models/{model_id}/variants", payload, headers)

    def release_model(self, model_id, expected_model_version, headers):
        return self._request("POST", f"/score-models/{model_id}/release",
                             {"expected_model_version": expected_model_version}, headers)

    def deprecate_model(self, model_id, expected_model_version, headers):
        return self._request("POST", f"/score-models/{model_id}/deprecate",
                             {"expected_model_version": expected_model_version}, headers)

    def reopen_model(self, model_id, expected_model_version, headers):
        return self._request("POST", f"/score-models/{model_id}/reopen",
                             {"expected_model_version": expected_model_version}, headers)

    def retire_model(self, model_id, expected_model_version, headers):
        return self._request("POST", f"/score-models/{model_id}/retire",
                             {"expected_model_version": expected_model_version}, headers)

    # ─── Score variants ───────────────────────────────
    def get_variant(self, variant_id, headers):
        return self._request("GET", f"/score-variants/{variant_id}", headers=headers)

    def list_variants(self, headers, params=None):
        return self._request("GET", "/score-variants", headers=headers, params=params)

    def release_variant(self, variant_id, headers):
        return self._request("POST", f"/score-variants/{variant_id}/release", {}, headers)

    def recall_variant(self, variant_id, headers):
        return self._request("POST", f"/score-variants/{variant_id}/recall", {}, headers)

    # ─── Consumers ────────────────────────────────────
    def create_consumer(self, payload, headers):
        return self._request("POST", "/consumers", payload, headers)

    def get_consumer(self, consumer_id, headers):
        return self._request("GET", f"/consumers/{consumer_id}", headers=headers)

    def list_consumers(self, headers, params=None):
        return self._request("GET", "/consumers", headers=headers, params=params)

    # ─── Archive samples ──────────────────────────────
    def create_archive_sample(self, payload, headers):
        return self._request("POST", "/archive-samples", payload, headers)

    def get_archive_sample(self, sample_id, headers):
        return self._request("GET", f"/archive-samples/{sample_id}", headers=headers)

    def list_archive_samples(self, headers, params=None):
        return self._request("GET", "/archive-samples", headers=headers, params=params)

    # ─── Validation studies ───────────────────────────
    def create_validation_study(self, payload, headers):
        return self._request("POST", "/validation-studies", payload, headers)

    def get_validation_study(self, study_id, headers):
        return self._request("GET", f"/validation-studies/{study_id}", headers=headers)

    def list_validation_studies(self, headers, params=None):
        return self._request("GET", "/validation-studies", headers=headers, params=params)

    def run_validation_study(self, study_id, expected_study_version, headers):
        return self._request("POST", f"/validation-studies/{study_id}/run",
                             {"expected_study_version": expected_study_version}, headers)

    def acknowledge_validation_study(self, study_id, finalized_by, evidence_ref,
                                     expected_study_version, headers):
        return self._request("POST", f"/validation-studies/{study_id}/acknowledge",
                             {"finalized_by": finalized_by,
                              "evidence_ref": evidence_ref,
                              "expected_study_version": expected_study_version}, headers)

    def revert_validation_study(self, study_id, expected_study_version, headers):
        return self._request("POST", f"/validation-studies/{study_id}/revert",
                             {"expected_study_version": expected_study_version}, headers)

    def compensate_validation_study(self, study_id, expected_study_version, headers):
        return self._request("POST", f"/validation-studies/{study_id}/compensate",
                             {"expected_study_version": expected_study_version}, headers)

    # ─── Reference sets ───────────────────────────────
    def create_reference_set(self, payload, headers):
        return self._request("POST", "/reference-sets", payload, headers)

    def get_reference_set(self, reference_set_id, headers):
        return self._request("GET", f"/reference-sets/{reference_set_id}", headers=headers)

    def list_reference_sets(self, headers, params=None):
        return self._request("GET", "/reference-sets", headers=headers, params=params)

    def attach_reason_code(self, reference_set_id, reason_code_id,
                           expected_reference_set_version, headers):
        return self._request("POST", f"/reference-sets/{reference_set_id}/attach-reason-code",
                             {"reason_code_id": reason_code_id,
                              "expected_reference_set_version": expected_reference_set_version},
                             headers)

    def detach_reason_code(self, reference_set_id, expected_reference_set_version, headers):
        return self._request("POST", f"/reference-sets/{reference_set_id}/detach-reason-code",
                             {"expected_reference_set_version": expected_reference_set_version},
                             headers)

    def reconcile_reference_set(self, reference_set_id, expected_reference_set_version, headers):
        return self._request("POST", f"/reference-sets/{reference_set_id}/reconcile",
                             {"expected_reference_set_version": expected_reference_set_version},
                             headers)

    # ─── Score postings ───────────────────────────────
    def create_score_result(self, payload, headers):
        return self._request("POST", "/score-results", payload, headers)

    def get_score_result(self, score_result_id, headers):
        return self._request("GET", f"/score-results/{score_result_id}", headers=headers)

    def list_score_results(self, headers, params=None):
        return self._request("GET", "/score-results", headers=headers, params=params)

    def bureau_discrepancies(self, score_result_id, headers):
        return self._request("GET", f"/score-results/{score_result_id}/bureau-discrepancies",
                             headers=headers)

    def void_score_result(self, score_result_id, expected_license_version, headers):
        return self._request("POST", f"/score-results/{score_result_id}/void",
                             {"expected_license_version": expected_license_version}, headers)

    # ─── Reason-code catalogue ────────────────────────
    def create_reason_code(self, payload, headers):
        return self._request("POST", "/reason-codes", payload, headers)

    def get_reason_code(self, reason_code_id, headers):
        return self._request("GET", f"/reason-codes/{reason_code_id}", headers=headers)

    def list_reason_codes(self, headers, params=None):
        return self._request("GET", "/reason-codes", headers=headers, params=params)

    def archive_reason_code(self, reason_code_id, headers):
        return self._request("POST", f"/reason-codes/{reason_code_id}/archive", {}, headers)

    def restore_reason_code(self, reason_code_id, headers):
        return self._request("POST", f"/reason-codes/{reason_code_id}/restore", {}, headers)

    # ─── Licences ─────────────────────────────────────
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def activate_license(self, license_id, expected_license_version, headers):
        return self._request("POST", f"/licenses/{license_id}/activate",
                             {"expected_license_version": expected_license_version}, headers)

    def suspend_license(self, license_id, expected_license_version, headers):
        return self._request("POST", f"/licenses/{license_id}/suspend",
                             {"expected_license_version": expected_license_version}, headers)

    def reactivate_license(self, license_id, expected_license_version, headers):
        return self._request("POST", f"/licenses/{license_id}/reactivate",
                             {"expected_license_version": expected_license_version}, headers)

    def terminate_license(self, license_id, expected_license_version, headers):
        return self._request("POST", f"/licenses/{license_id}/terminate",
                             {"expected_license_version": expected_license_version}, headers)

    def fee_quote(self, license_id, prospective_count, headers):
        return self._request("POST", f"/licenses/{license_id}/fee-quotes",
                             {"prospective_count": prospective_count}, headers)

    # ─── Fee ledger ───────────────────────────────────
    def get_fee_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/fee-ledger-entries/{entry_id}", headers=headers)

    def list_fee_ledger_entries(self, headers, params=None):
        return self._request("GET", "/fee-ledger-entries", headers=headers, params=params)

    # ─── Regulatory documentation ─────────────────────
    def create_model_documentation(self, payload, headers):
        return self._request("POST", "/model-documentation", payload, headers)

    def get_model_documentation(self, documentation_id, headers):
        return self._request("GET", f"/model-documentation/{documentation_id}", headers=headers)

    def list_model_documentation(self, headers, params=None):
        return self._request("GET", "/model-documentation", headers=headers, params=params)

    def file_model_documentation(self, documentation_id, expected_documentation_version, headers):
        return self._request("POST", f"/model-documentation/{documentation_id}/file",
                             {"expected_documentation_version": expected_documentation_version},
                             headers)

    # ─── Migration events ─────────────────────────────
    def create_migration_event(self, payload, headers):
        return self._request("POST", "/migration-events", payload, headers)

    def get_migration_event(self, migration_event_id, headers):
        return self._request("GET", f"/migration-events/{migration_event_id}", headers=headers)

    def list_migration_events(self, headers, params=None):
        return self._request("GET", "/migration-events", headers=headers, params=params)

    def void_migration_event(self, migration_event_id, headers):
        return self._request("POST", f"/migration-events/{migration_event_id}/void", {}, headers)

    # ─── Discovery slots ──────────────────────────────
    def create_discovery_request(self, tag, headers):
        return self._request("POST", "/score-discovery-requests", {"tag": tag}, headers)

    def get_discovery_request(self, discovery_request_id, headers):
        return self._request("GET", f"/score-discovery-requests/{discovery_request_id}",
                             headers=headers)

    def list_discovery_requests(self, headers, params=None):
        return self._request("GET", "/score-discovery-requests", headers=headers, params=params)

    # ─── Logical clock ────────────────────────────────
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def advance_to_month(self, month, headers):
        return self._request("POST", "/_clock/advance_to_month", {"month": month}, headers)


api_client = ApiClient()