"""Error catalogue and API exception type.

Every error id and HTTP status here is transcribed from the scaffold's error
catalogue (SCAFFOLD.yaml §1.6) and PRD §5. Nothing is invented and no status
is guessed.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        status, default_message = ERRORS.get(error_id, (500, "Unexpected error."))
        self.message = message or default_message
        self.http_status = http_status if http_status is not None else status


# error_id -> (http_status, default human message)
ERRORS = {
    # --- auth / context -----------------------------------------------------
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": (
        400, "X-User-ID and X-User-Role headers are required and must be non-empty."),
    "ERR_AGENT_NOT_PERMITTED": (403, "The acting role is not permitted for this operation."),
    "ERR_REGION_SCOPE_VIOLATION": (403, "A region-scoped role may only act on accounts in its own region."),
    "ERR_OWNERSHIP_MISMATCH": (403, "The acting identity does not own the resource it acts on."),
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": (
        403, "The approver must differ from the hospital account owner."),
    "ERR_BULK_SCOPE_VIOLATION": (403, "A bulk request named a system outside the acting account scope."),

    # --- not found ----------------------------------------------------------
    "ERR_ACCOUNT_NOT_FOUND": (404, "Path accountId does not resolve."),
    "ERR_AGREEMENT_NOT_FOUND": (404, "Path agreementId does not resolve."),
    "ERR_SYSTEM_NOT_FOUND": (404, "Path systemId does not resolve."),
    "ERR_READINESS_REVIEW_NOT_FOUND": (404, "Path reviewId does not resolve on the readiness collection."),
    "ERR_CASE_NOT_FOUND": (404, "Path caseId does not resolve."),
    "ERR_TRAINING_RECORD_NOT_FOUND": (404, "Path recordId does not resolve."),
    "ERR_EVIDENCE_NOT_FOUND": (404, "Path evidenceId does not resolve."),
    "ERR_CONTRACT_NOT_FOUND": (404, "Path contractId does not resolve."),
    "ERR_INCIDENT_NOT_FOUND": (404, "Path incidentId does not resolve."),
    "ERR_EXPANSION_REVIEW_NOT_FOUND": (404, "Path reviewId does not resolve on the expansion-review collection."),
    "ERR_TRANSFER_NOT_FOUND": (404, "Path transactionId does not resolve."),
    "ERR_LEDGER_NOT_FOUND": (404, "Path ledgerId does not resolve."),
    "ERR_CONFIGURATION_NOT_FOUND": (404, "Path configId does not resolve."),
    "ERR_DEPLOYMENT_NOT_FOUND": (404, "Path deploymentId does not resolve."),
    "ERR_PROCTOR_CASE_NOT_FOUND": (404, "Path proctorCaseId does not resolve."),
    "ERR_LOANER_DISPATCH_NOT_FOUND": (404, "Path dispatchId does not resolve."),
    "ERR_SOFTWARE_RELEASE_NOT_FOUND": (404, "Path releaseId does not resolve."),

    # --- generic request ----------------------------------------------------
    "ERR_INVALID_REQUEST": (400, "A required body field is missing, unparseable or of the wrong JSON type."),

    # --- account state ------------------------------------------------------
    "ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE": (409, "Account transition attempted from an ineligible status."),
    "ERR_ACCOUNT_NOT_CLOSABLE": (409, "Close attempted from a status other than ACTIVE or DORMANT."),
    "ERR_ACCOUNT_POSTURE_GATE": (409, "The account posture gate is not ACTIVE."),
    "ERR_READINESS_REVIEW_REQUIRED": (409, "Account activation attempted with no readiness review on file."),
    "ERR_TRAINING_PATH_UNINITIALIZED": (409, "Account activation attempted with no training record on file."),
    "ERR_NO_PLACEMENT_AGREEMENT": (409, "READINESS to CONTRACTED attempted with no agreement row on file."),
    "ERR_NO_ACTIVE_AGREEMENT": (409, "CONTRACTED to ACTIVE attempted with no ACTIVE agreement."),
    "ERR_ACTIVE_AGREEMENT_EXISTS": (409, "Account close attempted while an agreement is ACTIVE or SUSPENDED."),

    # --- readiness ----------------------------------------------------------
    "ERR_READINESS_REVIEW_NOT_PENDING": (409, "The readiness review is not in PENDING_REVIEW."),
    "ERR_READINESS_REVIEW_NOT_REJECTED": (409, "Return-to-review attempted on a review not in REJECTED."),
    "ERR_READINESS_REVIEW_NOT_PASSED": (409, "The referenced readiness review is not PASSED."),
    "ERR_ROOM_REQUIREMENTS_UNMET": (422, "A room dimension or throw radius falls below the configuration minimum."),
    "ERR_CONDITIONAL_CLEARANCE_REQUIRES_REVIEW": (422, "A PASSED verdict requires zero conditional clearances."),
    "ERR_POWER_CIRCUIT_MISSING": (422, "The configuration requires a dedicated power circuit the site lacks."),
    "ERR_NETWORK_INTEGRATION_MISSING": (422, "The configuration requires a dark fiber run the site lacks."),
    "ERR_REMEDIATION_NOTE_REQUIRED": (422, "A readiness rejection requires a non-empty remediation note."),
    "ERR_DUPLICATE_SITE_CODE": (409, "site_code is already used within this hospital account."),

    # --- agreements ---------------------------------------------------------
    "ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE": (409, "Agreement transition attempted from an ineligible status."),
    "ERR_AGREEMENT_NOT_TERMINABLE": (409, "Termination attempted on an agreement not ACTIVE or SUSPENDED."),
    "ERR_AGREEMENT_NOT_SUSPENDABLE": (409, "Suspension attempted while compliance_status is not NON_COMPLIANT."),
    "ERR_AGREEMENT_TERMS_INCOMPLETE": (422, "The commercial term required by the arrangement type is absent."),
    "ERR_ACCEPTANCE_WINDOW_EXPIRED": (409, "Acceptance attempted at or after acceptance_expires_utc."),
    "ERR_PLACEMENT_CAP_EXCEEDED": (402, "Submitting would exceed the account placement cap."),
    "ERR_DUPLICATE_SERIAL_NUMBER": (409, "The synthesized system serial number is already used."),

    # --- systems ------------------------------------------------------------
    "ERR_SYSTEM_STATUS_INVALID": (409, "System transition attempted from an ineligible service_status."),
    "ERR_SYSTEM_HAS_OPEN_CASES": (409, "Decommission attempted while a non-terminal case remains."),
    "ERR_SYSTEM_SITE_NOT_READY": (409, "Install attempted while the readiness review is not PASSED."),
    "ERR_COMMITMENT_CYCLE_NOT_STARTED": (409, "Install attempted while the commitment interval is not live."),
    "ERR_SERVICE_ACTION_UNRESOLVED": (409, "Restore-service attempted while a non-RESOLVED incident remains."),
    "ERR_NO_CREDENTIALED_SURGEON": (409, "The account has no CREDENTIALED surgeon training record."),
    "ERR_SERVICE_CONTRACT_REQUIRED": (409, "An ACTIVE in-window service contract is required."),

    # --- contracts / incidents / loaners ------------------------------------
    "ERR_SERVICE_CONTRACT_NOT_ACTIVE": (409, "The service contract is not ACTIVE."),
    "ERR_CONTRACT_TEMPORALLY_INVALID": (422, "Contract start precedes installation, or end is not after start."),
    "ERR_CONTRACT_TIER_UNRECOGNIZED": (422, "coverage_tier does not map into the response-time ladder."),
    "ERR_LOANER_WINDOW_CONFLICT": (409, "The loaner dispatch window overlaps a non-terminal dispatch on the unit."),
    "ERR_INVALID_WINDOW": (400, "The declared window end is not strictly later than its start."),

    # --- training / credentialing -------------------------------------------
    "ERR_TRAINING_STATUS_INVALID": (409, "Training transition attempted from an ineligible training_status."),
    "ERR_SIMULATION_MODULES_INCOMPLETE": (422, "Fewer than 3 simulation modules have been completed."),
    "ERR_PROCTORING_REQUIREMENT_MISSING": (422, "begin-proctoring requires required_proctored_cases >= 1."),
    "ERR_PROCTORING_CASES_INCOMPLETE": (422, "Proctored cases have not reached required_proctored_cases."),
    "ERR_CREDENTIALING_EVIDENCE_REQUIRED": (422, "No VALID or EXPIRING_SOON evidence exists on the record."),
    "ERR_RECERTIFICATION_NOT_DUE": (409, "The credential is unexpired and no evidence is REVOKED."),
    "ERR_EVIDENCE_NOT_RENEWABLE": (409, "The evidence status forbids this operation."),
    "ERR_EVIDENCE_WINDOW_INVALID": (422, "The evidence window is out of order or issued in the future."),
    "ERR_DUPLICATE_SURGEON_NPI": (409, "surgeon_npi is already used within this hospital account."),
    "ERR_SURGEON_NOT_CREDENTIALED": (409, "The named training record is not credential-valid."),

    # --- cases --------------------------------------------------------------
    "ERR_CASE_SCHEDULE_CONFLICT": (409, "Case occupancy overlaps a sibling case on the same system."),
    "ERR_INSTRUMENT_LIVES_EXHAUSTED": (409, "The requested instrument load remains above zero after clamping."),
    "ERR_REFERENTIAL_INTEGRITY_VIOLATION": (409, "A referenced parent row is missing, terminal or foreign."),

    # --- software -----------------------------------------------------------
    "ERR_RELEASE_DOWNGRADE": (409, "The release index is not strictly above the system's installed index."),
    "ERR_RELEASE_CONFIGURATION_MISMATCH": (409, "The release targets a different system configuration."),
    "ERR_DEPLOYMENT_WINDOW_INVALID": (422, "The deployment window starts before the deployment creation instant."),

    # --- IDN pool -----------------------------------------------------------
    "ERR_TRANSFER_WINDOW_CONFLICT": (409, "The transfer window overlaps a non-reversed window beyond grace."),
    "ERR_INSUFFICIENT_UTILISATION_CREDIT": (402, "The source account lacks remaining credit units."),
    "ERR_IDN_POOL_SATURATED": (402, "Aggregate utilisation has reached the IDN pool ceiling."),

    # --- concurrency --------------------------------------------------------
    "ERR_STALE_VERSION": (412, "expected_<parent>_version differs from the parent's current version."),
}

# HTTP statuses that the scaffold's endpoint table assigns to each mutating
# operation are read from `endpoints[].code`; the error catalogue above is the
# single source of truth for failures.