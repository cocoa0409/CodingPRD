"""The complete error catalogue (PRD 5) and the global rejection ladder (PRD 2.11)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = HTTP_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, "The request was rejected."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# PRD 5 -- Error Code Catalogue: every error id with its HTTP status.
# --------------------------------------------------------------------------

HTTP_STATUS = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_PLAN_PROVIDER_NOT_FOUND": 404,
    "ERR_PLAN_DOCUMENT_NOT_FOUND": 404,
    "ERR_SERVICE_PROVIDER_NOT_FOUND": 404,
    "ERR_FIDUCIARY_ALLOCATION_NOT_FOUND": 404,
    "ERR_ADOPTING_EMPLOYER_NOT_FOUND": 404,
    "ERR_DESIGN_ELECTION_NOT_FOUND": 404,
    "ERR_PAYROLL_BATCH_NOT_FOUND": 404,
    "ERR_REMITTANCE_DEPOSIT_NOT_FOUND": 404,
    "ERR_COMPLIANCE_TEST_NOT_FOUND": 404,
    "ERR_PLAN_FILING_NOT_FOUND": 404,
    "ERR_EXIT_TRANSFER_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_STALE_EMPLOYER_VERSION": 412,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_PROVIDER_NOT_PENDING": 409,
    "ERR_PLAN_ALREADY_ACTIVE": 409,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_ALLOCATION_ALREADY_ACKNOWLEDGED": 409,
    "ERR_ELECTION_INVALID_STATE": 409,
    "ERR_EMPLOYER_INVALID_STATE": 409,
    "ERR_BATCH_INVALID_STATE": 409,
    "ERR_DEPOSIT_INVALID_STATE": 409,
    "ERR_DEPOSIT_NOT_REVERSIBLE": 409,
    "ERR_CORRECTION_INVALID_STATE": 409,
    "ERR_TEST_INVALID_STATE": 409,
    "ERR_FILING_INVALID_STATE": 409,
    "ERR_AUDIT_NOT_REQUIRED": 409,
    "ERR_TRANSFER_INVALID_STATE": 409,
    "ERR_FIDELITY_BOND_BELOW_FLOOR": 422,
    "ERR_PROVIDER_NOT_REGISTERED": 409,
    "ERR_NAMED_FIDUCIARY_NOT_ACKNOWLEDGED": 409,
    "ERR_TRUSTEE_NOT_ACKNOWLEDGED": 409,
    "ERR_PLAN_COMPLIANCE_FROZEN": 409,
    "ERR_PLAN_LEVEL_TEST_OUTSTANDING": 409,
    "ERR_AUDIT_OPINION_UNACCEPTABLE": 409,
    "ERR_NOT_AN_AUDITOR_FIRM": 409,
    "ERR_AUDITOR_NOT_INDEPENDENT": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_EMPLOYER_ELECTIONS_INCOMPLETE": 409,
    "ERR_TEST_SCOPE_MISMATCH": 422,
    "ERR_EMPLOYER_PLAN_MISMATCH": 409,
    "ERR_NOT_PLAN_RECORDKEEPER": 409,
    "ERR_INVALID_AFFILIATION": 422,
    "ERR_NO_BILLABLE_SERVICE_PROVIDER": 409,
    "ERR_INVALID_PAY_PERIOD": 422,
    "ERR_PAY_PERIOD_OVERLAP": 409,
    "ERR_WITHHOLDING_DATE_OUT_OF_PERIOD": 422,
    "ERR_DEPOSIT_DATE_OUT_OF_RANGE": 422,
    "ERR_INVALID_RECOVERY_DATE": 422,
    "ERR_INVALID_ALLOCATION_WINDOW": 422,
    "ERR_ALLOCATION_WINDOW_OVERLAP": 409,
    "ERR_INVALID_BLACKOUT_WINDOW": 422,
    "ERR_BLACKOUT_WINDOW_CONFLICT": 409,
    "ERR_ELECTION_WINDOW_CLOSED": 409,
    "ERR_BLACKOUT_NOT_ENDED": 409,
    "ERR_INVALID_DISCLOSURE_PERIOD": 422,
    "ERR_DUPLICATE_PROVIDER_EIN": 409,
    "ERR_DUPLICATE_PLAN_NUMBER": 409,
    "ERR_DUPLICATE_EMPLOYER_EIN": 409,
    "ERR_DUPLICATE_PAYROLL_REFERENCE": 409,
    "ERR_DUPLICATE_FILING_YEAR": 409,
    "ERR_DUPLICATE_COMPLIANCE_TEST": 409,
    "ERR_TIER_FIELDS_MISMATCH": 422,
    "ERR_TIER_LIMITS_OUT_OF_ORDER": 422,
    "ERR_SIGNATORY_REQUIRED": 422,
    "ERR_ELIGIBILITY_MORE_RESTRICTIVE": 409,
    "ERR_VESTING_MORE_RESTRICTIVE": 409,
    "ERR_CENSUS_INCONSISTENT": 422,
    "ERR_NO_APPROVED_ELECTION": 409,
    "ERR_MATCH_MISMATCH": 409,
    "ERR_DEPOSIT_AMOUNT_MISMATCH": 409,
    "ERR_OPEN_LATE_DEPOSIT_CORRECTION": 409,
    "ERR_UNREMITTED_CONTRIBUTIONS": 409,
    "ERR_FIDELITY_BOND_INSUFFICIENT": 409,
    "ERR_FORM_5330_REFERENCE_REQUIRED": 422,
    "ERR_FILING_ALREADY_SUBMITTED": 409,
}

# The catalogue above is exactly the 80 identifiers of PRD 5. The two entries
# below are outside it: the PRD declares no not-found error for a FeeDisclosure
# and no transport-level fallbacks, so these exist purely so that an
# unresolvable disclosure id, an unrouted path and a wrong HTTP method still
# come back inside the standard envelope instead of as a bare Werkzeug page.
CATALOGUE_SIZE = len(HTTP_STATUS)
HTTP_STATUS["ERR_FEE_DISCLOSURE_NOT_FOUND"] = 404
HTTP_STATUS["ERR_NOT_FOUND"] = 404
HTTP_STATUS["ERR_METHOD_NOT_ALLOWED"] = 405

# --------------------------------------------------------------------------
# PRD 2.11 -- the global rejection precedence ladder, priorities 1..71.
# The ordering is observable; when a request violates more than one rule the
# violation with the lowest priority number is the one reported.
# --------------------------------------------------------------------------

LADDER = [
    "ERR_MISSING_AUTH_HEADERS",              # 1
    "ERR_UNKNOWN_ROLE",                      # 2
    "ERR_UNAUTHORIZED",                      # 3
    "ERR_NOT_RESOURCE_OWNER",                # 4
    "__PATH_EXISTENCE__",                    # 5
    "__BODY_FK_EXISTENCE__",                 # 6
    "ERR_VALIDATION",                        # 7
    "ERR_STALE_EMPLOYER_VERSION",            # 8
    "ERR_STALE_PLAN_VERSION",                # 9
    "ERR_PROVIDER_NOT_PENDING",              # 10
    "ERR_PLAN_ALREADY_ACTIVE",               # 11
    "ERR_PLAN_NOT_ACTIVE",                   # 12
    "ERR_ALLOCATION_ALREADY_ACKNOWLEDGED",   # 13
    "ERR_ELECTION_INVALID_STATE",            # 14
    "ERR_EMPLOYER_INVALID_STATE",            # 15
    "ERR_BATCH_INVALID_STATE",               # 16
    "ERR_DEPOSIT_INVALID_STATE",             # 17
    "ERR_DEPOSIT_NOT_REVERSIBLE",            # 18
    "ERR_CORRECTION_INVALID_STATE",          # 19
    "ERR_TEST_INVALID_STATE",                # 20
    "ERR_FILING_INVALID_STATE",              # 21
    "ERR_AUDIT_NOT_REQUIRED",                # 22
    "ERR_TRANSFER_INVALID_STATE",            # 23
    "ERR_FIDELITY_BOND_BELOW_FLOOR",         # 24
    "ERR_PROVIDER_NOT_REGISTERED",           # 25
    "ERR_NAMED_FIDUCIARY_NOT_ACKNOWLEDGED",  # 26
    "ERR_TRUSTEE_NOT_ACKNOWLEDGED",          # 27
    "ERR_PLAN_COMPLIANCE_FROZEN",            # 28
    "ERR_PLAN_LEVEL_TEST_OUTSTANDING",       # 29
    "ERR_AUDIT_OPINION_UNACCEPTABLE",        # 30
    "ERR_NOT_AN_AUDITOR_FIRM",               # 31
    "ERR_AUDITOR_NOT_INDEPENDENT",           # 32
    "ERR_SEGREGATION_OF_DUTIES",             # 33
    "ERR_EMPLOYER_ELECTIONS_INCOMPLETE",     # 34
    "ERR_TEST_SCOPE_MISMATCH",               # 35
    "ERR_EMPLOYER_PLAN_MISMATCH",            # 36
    "ERR_NOT_PLAN_RECORDKEEPER",             # 37
    "ERR_INVALID_AFFILIATION",               # 38
    "ERR_NO_BILLABLE_SERVICE_PROVIDER",      # 39
    "ERR_INVALID_PAY_PERIOD",                # 40
    "ERR_PAY_PERIOD_OVERLAP",                # 41
    "ERR_WITHHOLDING_DATE_OUT_OF_PERIOD",    # 42
    "ERR_DEPOSIT_DATE_OUT_OF_RANGE",         # 43
    "ERR_INVALID_RECOVERY_DATE",             # 44
    "ERR_INVALID_ALLOCATION_WINDOW",         # 45
    "ERR_ALLOCATION_WINDOW_OVERLAP",         # 46
    "ERR_INVALID_BLACKOUT_WINDOW",           # 47
    "ERR_BLACKOUT_WINDOW_CONFLICT",          # 48
    "ERR_ELECTION_WINDOW_CLOSED",            # 49
    "ERR_BLACKOUT_NOT_ENDED",                # 50
    "ERR_INVALID_DISCLOSURE_PERIOD",         # 51
    "ERR_DUPLICATE_PROVIDER_EIN",            # 52
    "ERR_DUPLICATE_PLAN_NUMBER",             # 53
    "ERR_DUPLICATE_EMPLOYER_EIN",            # 54
    "ERR_DUPLICATE_PAYROLL_REFERENCE",       # 55
    "ERR_DUPLICATE_FILING_YEAR",             # 56
    "ERR_DUPLICATE_COMPLIANCE_TEST",         # 57
    "ERR_TIER_FIELDS_MISMATCH",              # 58
    "ERR_TIER_LIMITS_OUT_OF_ORDER",          # 59
    "ERR_SIGNATORY_REQUIRED",                # 60
    "ERR_ELIGIBILITY_MORE_RESTRICTIVE",      # 61
    "ERR_VESTING_MORE_RESTRICTIVE",          # 62
    "ERR_CENSUS_INCONSISTENT",               # 63
    "ERR_NO_APPROVED_ELECTION",              # 64
    "ERR_MATCH_MISMATCH",                    # 65
    "ERR_DEPOSIT_AMOUNT_MISMATCH",           # 66
    "ERR_OPEN_LATE_DEPOSIT_CORRECTION",      # 67
    "ERR_UNREMITTED_CONTRIBUTIONS",          # 68
    "ERR_FIDELITY_BOND_INSUFFICIENT",        # 69
    "ERR_FORM_5330_REFERENCE_REQUIRED",      # 70
    "ERR_FILING_ALREADY_SUBMITTED",          # 71
]

PRIORITY = {name: i + 1 for i, name in enumerate(LADDER)}

# Path-identifier and body-foreign-key not-found errors both live at
# priorities 5 and 6 respectively (PRD 2.8).
NOT_FOUND_ERRORS = (
    "ERR_PLAN_PROVIDER_NOT_FOUND",
    "ERR_PLAN_DOCUMENT_NOT_FOUND",
    "ERR_SERVICE_PROVIDER_NOT_FOUND",
    "ERR_FIDUCIARY_ALLOCATION_NOT_FOUND",
    "ERR_ADOPTING_EMPLOYER_NOT_FOUND",
    "ERR_DESIGN_ELECTION_NOT_FOUND",
    "ERR_PAYROLL_BATCH_NOT_FOUND",
    "ERR_REMITTANCE_DEPOSIT_NOT_FOUND",
    "ERR_COMPLIANCE_TEST_NOT_FOUND",
    "ERR_PLAN_FILING_NOT_FOUND",
    "ERR_EXIT_TRANSFER_NOT_FOUND",
)

DEFAULT_MESSAGE = {
    "ERR_MISSING_AUTH_HEADERS": "Both X-User-ID and X-User-Role are required.",
    "ERR_UNKNOWN_ROLE": "X-User-Role is not one of the five declared roles.",
    "ERR_UNAUTHORIZED": "This role is not authorised for the requested operation.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the addressed resource.",
    "ERR_VALIDATION": "The request body or query string is malformed.",
}

for _eid in HTTP_STATUS:
    DEFAULT_MESSAGE.setdefault(
        _eid, _eid.replace("ERR_", "").replace("_", " ").capitalize() + "."
    )
