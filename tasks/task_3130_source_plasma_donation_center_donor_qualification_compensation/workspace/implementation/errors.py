"""Error class and error ID constants (from SCAFFOLD.yaml error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_missing_headers():
    return ApiError(
        "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
        "X-User-ID or X-User-Role header missing or malformed",
        400,
    )


def err_permissions():
    return ApiError(
        "ERR_INSUFFICIENT_PERMISSIONS",
        "Role not authorized for this operation",
        403,
    )


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_stale_version():
    return ApiError(
        "ERR_STALE_VERSION",
        "expected version does not match the current version",
        412,
    )


def err_invalid_state(msg="Invalid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_center_not_operational():
    return ApiError(
        "ERR_CENTER_NOT_OPERATIONAL",
        "Center is INSPECTION_HOLD or DECOMMISSIONED; operation requires OPERATIONAL",
        409,
    )


def err_center_not_on_hold():
    return ApiError(
        "ERR_CENTER_NOT_ON_HOLD",
        "Clear-hold requires center.status == INSPECTION_HOLD",
        409,
    )


def err_center_has_active_visits():
    return ApiError(
        "ERR_CENTER_HAS_ACTIVE_VISITS",
        "Decommission requires zero in-flight screening or donation visits at this center",
        409,
    )


def err_donor_not_eligible():
    return ApiError(
        "ERR_DONOR_NOT_ELIGIBLE",
        "Donor status blocks the operation",
        409,
    )


def err_donor_not_deferrable():
    return ApiError(
        "ERR_DONOR_NOT_DEFERRABLE",
        "Donor is already deferred and cannot be re-deferred",
        409,
    )


def err_donor_deferred():
    return ApiError(
        "ERR_DONOR_DEFERRED",
        "An ACTIVE DeferralRegistryEntry exists for this donor at check-in",
        409,
    )


def err_donor_not_qualified():
    return ApiError(
        "ERR_DONOR_NOT_QUALIFIED",
        "Donor status is not QUALIFIED",
        409,
    )


def err_donor_underweight():
    return ApiError(
        "ERR_DONOR_UNDERWEIGHT",
        "Physical exam records weight_kg below 50.0",
        422,
    )


def err_active_deferral_exists():
    return ApiError(
        "ERR_ACTIVE_DEFERRAL_EXISTS",
        "An ACTIVE DeferralRegistryEntry already exists for this donor",
        409,
    )


def err_duplicate_donor():
    return ApiError(
        "ERR_DUPLICATE_DONOR",
        "external_donor_ref already registered",
        409,
    )


def err_segregation_of_duties():
    return ApiError(
        "ERR_SEGREGATION_OF_DUTIES",
        "MedicalScreener clearing the visit recorded at least one of its sub-records",
        403,
    )


def err_incomplete_screening():
    return ApiError(
        "ERR_INCOMPLETE_SCREENING",
        "Fewer than four sub-records present at clearance",
        409,
    )


def err_screening_not_passable():
    return ApiError(
        "ERR_SCREENING_NOT_PASSABLE",
        "At least one sub-record has outcome FAIL at clearance",
        409,
    )


def err_screening_not_cleared():
    return ApiError(
        "ERR_SCREENING_NOT_CLEARED",
        "Referenced ScreeningVisit is not CLEARED or is already consumed",
        409,
    )


def err_screening_center_mismatch():
    return ApiError(
        "ERR_SCREENING_CENTER_MISMATCH",
        "ScreeningVisit.center_id does not match the donation center_id",
        409,
    )


def err_duplicate_sub_record():
    return ApiError(
        "ERR_DUPLICATE_SUB_RECORD",
        "A ScreeningSubRecord of this record_type already exists for this visit",
        409,
    )


def err_visit_not_in_progress():
    return ApiError(
        "ERR_VISIT_NOT_IN_PROGRESS",
        "Visit must be IN_PROGRESS for this operation",
        409,
    )


def err_visit_not_scheduled():
    return ApiError(
        "ERR_VISIT_NOT_SCHEDULED",
        "DonationVisit must be SCHEDULED for check-in",
        409,
    )


def err_visit_not_observable():
    return ApiError(
        "ERR_VISIT_NOT_OBSERVABLE",
        "DonationVisit must be OBSERVATION for discharge",
        409,
    )


def err_visit_not_abortable():
    return ApiError(
        "ERR_VISIT_NOT_ABORTABLE",
        "DonationVisit must be IN_PROGRESS or OBSERVATION for adverse-reaction abort",
        409,
    )


def err_frequency_limit():
    return ApiError(
        "ERR_FREQUENCY_LIMIT_EXCEEDED",
        "Donor has reached the rolling-window donation limit",
        409,
    )


def err_inter_donation_gap():
    return ApiError(
        "ERR_INTER_DONATION_GAP_VIOLATION",
        "Less than 48 hours since the donor's most recent completed donation",
        409,
    )


def err_no_bed_available():
    return ApiError(
        "ERR_NO_BED_AVAILABLE",
        "All donor-floor beds occupied at check-in",
        409,
    )


def err_no_observation_chair():
    return ApiError(
        "ERR_NO_OBSERVATION_CHAIR",
        "All observation chairs occupied at complete-collection",
        409,
    )


def err_observation_too_early():
    return ApiError(
        "ERR_OBSERVATION_TOO_EARLY",
        "Fewer than 15 minutes elapsed since entering OBSERVATION",
        409,
    )


def err_invalid_actual_volume():
    return ApiError(
        "ERR_INVALID_ACTUAL_VOLUME",
        "actual_volume_ml must be greater than 0 and at most programmed_volume_ml",
        422,
    )


def err_no_active_comp_schedule():
    return ApiError(
        "ERR_NO_ACTIVE_COMP_SCHEDULE",
        "No ACTIVE CompensationSchedule covers the check-in instant",
        409,
    )


def err_schedule_not_active():
    return ApiError(
        "ERR_SCHEDULE_NOT_ACTIVE",
        "Schedule must be ACTIVE for retire",
        409,
    )


def err_unit_not_quarantined():
    return ApiError(
        "ERR_UNIT_NOT_QUARANTINED",
        "DonationUnit must be QUARANTINED for manual release",
        409,
    )


def err_lookback_open():
    return ApiError(
        "ERR_LOOKBACK_OPEN",
        "An OPEN or UNITS_QUARANTINED LookBackCase exists for this donor",
        409,
    )


def err_lookback_not_ready():
    return ApiError(
        "ERR_LOOKBACK_NOT_READY",
        "LookBackCase must be UNITS_QUARANTINED for resolve",
        409,
    )
