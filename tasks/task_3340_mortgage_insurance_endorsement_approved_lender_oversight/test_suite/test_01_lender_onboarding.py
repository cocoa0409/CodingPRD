"""Lender onboarding: creation, retrieval, validation, and the review cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    advance_lender,
    approve_lender_action,
    create_lender,
    decide_filing,
    get_lender,
    is_iso8601_timestamp,
    is_valid_uuid,
    lender_action,
    lender_version,
    setup_approved_lender,
    submit_filing,
    validate_error,
    validate_success,
)
from test_helpers import api_client
from test_helpers.test_users import (
    make_admin_headers,
    make_approver_headers,
    make_lender_officer_headers,
    make_reviewer_headers,
)


# ---------------------------------------------------------------------------
# Creation and retrieval
# ---------------------------------------------------------------------------
def test_lender_creation_lands_in_desk_review_with_defaults(api):
    """PRD §3.1: "The new `Lender` lands in `DESK_REVIEW` with `endorsed_volume_cents`
    at 0 and its `required_net_worth_cents` immediately computed per the variant rule
    below."

    Design: Corner/entities/lender_creation_lands_in_desk_review_with_defaults
    """
    response = api_client.create_lender(
        {
            "legal_name": "Acme Mortgage Co",
            "institution_type": "MORTGAGEE_SUPERVISED",
            "home_state": "VA",
            "qc_plan_on_file": True,
        },
        make_admin_headers(),
    )
    data = validate_success(response, expected_status=201)
    assert data["status"] == "DESK_REVIEW"
    assert data["endorsed_volume_cents"] == 0
    assert isinstance(data["version"], int)
    assert is_valid_uuid(data["id"])


def test_lender_get_returns_stored_input_fields(api):
    """PRD §3.1: "A `PlatformAdmin` onboards a lender application by supplying the
    applicant's `legal_name`, its `institution_type` — one of `MORTGAGEE_SUPERVISED`,
    `MORTGAGEE_NONSUPERVISED`, or `MORTGAGEE_INVESTING` — its two-letter `home_state`,
    and the `qc_plan_on_file` attestation flag recording whether a quality control plan
    was presented at application."

    Design: Corner/entities/lender_get_returns_stored_input_fields
    """
    lender = create_lender(
        legal_name="Blue Ridge Mortgage",
        institution_type="MORTGAGEE_NONSUPERVISED",
        home_state="NC",
        qc_plan_on_file=False,
    )
    response = api_client.get_lender(lender["id"], make_admin_headers())
    data = validate_success(response)
    assert data["legal_name"] == "Blue Ridge Mortgage"
    assert data["institution_type"] == "MORTGAGEE_NONSUPERVISED"
    assert data["home_state"] == "NC"
    assert data["qc_plan_on_file"] is False


def test_lender_get_unknown_id_returns_not_found(api):
    """PRD §2.7: "Existence: every id in the path and body references an existing
    resource (`ERR_NOT_FOUND`)."

    Design: Corner/entities/lender_get_unknown_id_returns_not_found
    """
    response = api_client.get_lender(UNKNOWN_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_lender_creation_missing_legal_name_rejected(api):
    """PRD §2.7: "Payload shape: required fields present, enums valid, amounts positive,
    `start_date` not after `end_date`, `deficiency_codes` non-empty on a flag-deficient
    decision (`ERR_VALIDATION`)."

    Design: Corner/entities/lender_creation_missing_legal_name_rejected
    """
    response = api_client.create_lender(
        {
            "institution_type": "MORTGAGEE_SUPERVISED",
            "home_state": "VA",
            "qc_plan_on_file": True,
        },
        make_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_lender_creation_invalid_institution_type_enum_rejected(api):
    """PRD §2.7: "Payload shape: required fields present, enums valid, amounts positive,
    `start_date` not after `end_date`, `deficiency_codes` non-empty on a flag-deficient
    decision (`ERR_VALIDATION`)."

    Design: Corner/entities/lender_creation_invalid_institution_type_enum_rejected
    """
    response = api_client.create_lender(
        {
            "legal_name": "Bad Enum Bank",
            "institution_type": "BANK",
            "home_state": "VA",
            "qc_plan_on_file": True,
        },
        make_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_lender_system_fields_server_minted(api):
    """PRD §2.4: "Every entity in the platform carries the common resource properties:
    `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC
    timestamp with three fractional digits; `updated_at`, refreshed on every mutation
    in the same format; and `version`, an integer that starts at its initial value and
    increments by 1 on every mutation of that entity."

    Design: Corner/entities/lender_system_fields_server_minted
    """
    response = api_client.create_lender(
        {
            "legal_name": "Sys Fields Co",
            "institution_type": "MORTGAGEE_INVESTING",
            "home_state": "MD",
            "qc_plan_on_file": True,
        },
        make_admin_headers(),
    )
    data = validate_success(response, expected_status=201)
    assert is_valid_uuid(data["id"])
    assert isinstance(data["version"], int)
    # NOTE: an assertion that created_at/updated_at equal the logical-clock startup
    # default was removed — PRD §2.4 names only endorsement_date, default_date,
    # closed_at, and evaluated_at as logical-clock-stamped, and describes
    # created_at/updated_at purely by format, so the clock source is not uniquely
    # derivable. Format-level checks remain:
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


# ---------------------------------------------------------------------------
# Review cycle transitions
# ---------------------------------------------------------------------------
def test_lender_advance_to_field_review_records_advancer(api):
    """PRD §3.1: "an `FhaReviewer` may advance an application sitting in `DESK_REVIEW`
    to `FIELD_REVIEW`, which records the reviewer's identifier in `advanced_by_user_id`"
    PRD §3.1: "Every status change increments the lender's `version` by 1."

    Design: Corner/state_machines/lender_advance_to_field_review_records_advancer
    """
    lender = create_lender(legal_name="Advance Co")
    created_version = lender["version"]
    response = api_client.lender_status_change(
        lender["id"],
        {"action": "ADVANCE_TO_FIELD_REVIEW"},
        make_reviewer_headers("rev-1"),
    )
    data = validate_success(response)
    assert data["status"] == "FIELD_REVIEW"
    assert data["advanced_by_user_id"] == "rev-1"
    assert data["version"] == created_version + 1


def test_lender_return_from_desk_review(api):
    """PRD §3.1: "or return an application sitting in either `DESK_REVIEW` or
    `FIELD_REVIEW` to `RETURNED`."

    Design: Corner/state_machines/lender_return_from_desk_review
    """
    lender = create_lender(legal_name="Return Co")
    response = api_client.lender_status_change(
        lender["id"], {"action": "RETURN"}, make_reviewer_headers("rev-1")
    )
    data = validate_success(response)
    assert data["status"] == "RETURNED"


def test_lender_resubmit_cycle_returns_to_desk_review(api):
    """PRD §3.1: "A returned application may be resubmitted by the owning
    `LenderOfficer`, which moves it from `RETURNED` back to `DESK_REVIEW`; the
    resubmission cycle `RETURNED` → `DESK_REVIEW` → `FIELD_REVIEW` may repeat any
    number of times."

    Design: Corner/state_machines/lender_resubmit_cycle_returns_to_desk_review
    """
    lender = create_lender(legal_name="Cycle Co")
    lender_action(lender["id"], "RETURN", make_reviewer_headers("rev-1"))
    response = api_client.lender_status_change(
        lender["id"], {"action": "RESUBMIT"}, make_lender_officer_headers(lender["id"])
    )
    data = validate_success(response)
    assert data["status"] == "DESK_REVIEW"


def test_lender_advance_from_field_review_rejected(api):
    """PRD §3.1: "Requesting an advance against an application that is no longer in
    `DESK_REVIEW` is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/lender_advance_from_field_review_rejected
    """
    lender = create_lender(legal_name="Bad Advance Co")
    advance_lender(lender["id"], reviewer="rev-1")
    response = api_client.lender_status_change(
        lender["id"],
        {"action": "ADVANCE_TO_FIELD_REVIEW"},
        make_reviewer_headers("rev-2"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_lender_resubmit_from_desk_review_rejected(api):
    """PRD §3.1: "A returned application may be resubmitted by the owning
    `LenderOfficer`, which moves it from `RETURNED` back to `DESK_REVIEW`"
    PRD §2.7: "State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/lender_resubmit_from_desk_review_rejected
    """
    lender = create_lender(legal_name="Bad Resubmit Co")
    response = api_client.lender_status_change(
        lender["id"], {"action": "RESUBMIT"}, make_lender_officer_headers(lender["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_lender_approve_from_desk_review_rejected(api):
    """PRD §3.1: "An `FhaApprover` approves an application in `FIELD_REVIEW` only when
    five conditions hold."
    PRD §2.7: "State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/lender_approve_from_desk_review_rejected
    """
    lender = create_lender(legal_name="Bad Approve Co")
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("app-1")
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_lender_return_twice_rejected(api):
    """PRD §3.1: "or return an application sitting in either `DESK_REVIEW` or
    `FIELD_REVIEW` to `RETURNED`."
    PRD §2.7: "State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/lender_return_twice_rejected
    """
    lender = create_lender(legal_name="Twice Co")
    lender_action(lender["id"], "RETURN", make_reviewer_headers("rev-1"))
    response = api_client.lender_status_change(
        lender["id"], {"action": "RETURN"}, make_reviewer_headers("rev-1")
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Suspension, reinstatement, termination
# ---------------------------------------------------------------------------
def test_lender_terminate_from_approved_with_no_cases(api):
    """PRD §3.6: "An `FhaApprover` terminates a lender from either `APPROVED` or
    `SUSPENDED`, but only when no loan case of the lender sits in a non-terminal state"

    Design: Corner/state_machines/lender_terminate_from_approved_with_no_cases
    """
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Terminate Co"}, advancer="rev-1", approver="app-1"
    )
    response = api_client.lender_status_change(
        lender["id"], {"action": "TERMINATE"}, make_approver_headers("app-1")
    )
    data = validate_success(response)
    assert data["status"] == "TERMINATED"


def test_lender_terminated_is_terminal_lockdown(api):
    """PRD §3.6: "`TERMINATED` is the lender's terminal state."
    PRD §2.7: "State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/lender_terminated_is_terminal_lockdown
    """
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Locked Co"}, advancer="rev-1", approver="app-1"
    )
    lender_action(lender["id"], "TERMINATE", make_approver_headers("app-1"))
    response = api_client.lender_status_change(
        lender["id"], {"action": "SUSPEND"}, make_approver_headers("app-1")
    )
    validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_lender_suspend_reinstate_round_trip(api):
    """PRD §3.6: "An `FhaApprover` moves a lender from `APPROVED` to `SUSPENDED`"
    PRD §3.6: "Reinstating reverses the same cascade: the lender moves from `SUSPENDED`
    back to `APPROVED`"
    PRD §3.1: "Every status change increments the lender's `version` by 1."

    Design: Corner/state_machines/lender_suspend_reinstate_round_trip
    """
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Suspend Co"}, advancer="rev-1", approver="app-1"
    )
    approved_version = lender["version"]
    response = api_client.lender_status_change(
        lender["id"], {"action": "SUSPEND"}, make_approver_headers("app-1")
    )
    assert validate_success(response)["status"] == "SUSPENDED"
    response = api_client.lender_status_change(
        lender["id"], {"action": "REINSTATE"}, make_approver_headers("app-1")
    )
    data = validate_success(response)
    assert data["status"] == "APPROVED"
    assert data["version"] == approved_version + 2


def test_error_lender_has_active_cases(api):
    """PRD §3.6: "A termination attempt with any such case outstanding is rejected with
    `ERR_LENDER_HAS_ACTIVE_CASES`."

    Design: Corner/errors/error_lender_has_active_cases
    """
    from test_helpers import create_case

    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Active Co"}, advancer="rev-1", approver="app-1"
    )
    create_case(lender["id"], borrower_reference="ACT-1")
    response = api_client.lender_status_change(
        lender["id"], {"action": "TERMINATE"}, make_approver_headers("app-1")
    )
    validate_error(response, ApiErrorId.ERR_LENDER_HAS_ACTIVE_CASES)
    assert get_lender(lender["id"])["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Segregation of duties at approval
# ---------------------------------------------------------------------------
def test_error_segregation_of_duties(api):
    """PRD §3.1: "First, the approver's identity must differ from the
    `advanced_by_user_id` recorded when the application was advanced — the same person
    who moved the file forward may not approve it — or the approval is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/error_segregation_of_duties
    """
    lender = create_lender(legal_name="SoD Co")
    filing = submit_filing(lender["id"])
    decide_filing(filing["id"], lender["id"], "ACCEPT", reviewer="rev-2")
    advance_lender(lender["id"], reviewer="rev-1")
    # The approver carries the same operator id recorded as advanced_by_user_id.
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("rev-1")
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_lender(lender["id"])["status"] == "FIELD_REVIEW"


def _latest_filing_id(lender_id: str) -> str:
    filings = validate_success(
        api_client.list_financial_filings(lender_id, make_admin_headers())
    )
    return filings[-1]["id"] if isinstance(filings, list) else filings["id"]


# ---------------------------------------------------------------------------
# Difficulty: net worth variant divergence
# ---------------------------------------------------------------------------
def _file_and_advance(lender_id: str, **filing_overrides):
    filing = submit_filing(lender_id, **filing_overrides)
    decide_filing(filing["id"], lender_id, "ACCEPT", reviewer="rev-alpha")
    advance_lender(lender_id, reviewer="rev-alpha")


def test_small_lender_variant_approves_below_standard_floor(api):
    """PRD §3.1: "A lender whose `institution_type` is `MORTGAGEE_NONSUPERVISED` and
    whose `endorsed_volume_cents` is below 5,000,000,000 cents is a `SMALL_LENDER`, and
    its `required_net_worth_cents` is a flat 50,000,000 cents regardless of volume."
    PRD §3.1: "Third, that filing's `adjusted_net_worth_cents` must be at least the
    lender's `required_net_worth_cents` (`ERR_NET_WORTH_DEFICIENT`)."

    Design: Difficulty/dual_variant_calc/net_worth_floor_diverges_by_variant_for_identical_financials
    """
    lender = create_lender(
        legal_name="Independent Mortgage Bankers",
        institution_type="MORTGAGEE_NONSUPERVISED",
    )
    _file_and_advance(
        lender["id"],
        total_assets_cents=95_000_000,
        total_liabilities_cents=20_000_000,
        liquid_assets_cents=11_000_000,
    )
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("appr-beta")
    )
    data = validate_success(response)
    # Net worth 75,000,000 clears the 50,000,000 SMALL_LENDER floor.
    assert data["status"] == "APPROVED"
    lender = get_lender(lender["id"])
    assert lender["net_worth_variant"] == "SMALL_LENDER"
    assert lender["required_net_worth_cents"] == 50_000_000


def test_standard_variant_rejects_identical_financials(api):
    """PRD §3.1: "Every other lender is `STANDARD`, and its requirement is the greater
    of 100,000,000 cents and one percent of its `endorsed_volume_cents` rounded half-up
    to whole cents — so two non-supervised lenders with identical financials can face
    different floors once one crosses the volume cap."
    PRD §3.1: "Third, that filing's `adjusted_net_worth_cents` must be at least the
    lender's `required_net_worth_cents` (`ERR_NET_WORTH_DEFICIENT`)."

    Design: Difficulty/dual_variant_calc/net_worth_floor_diverges_by_variant_for_identical_financials
    """
    lender = create_lender(
        legal_name="Supervised Bank Mortgage Co",
        institution_type="MORTGAGEE_SUPERVISED",
    )
    _file_and_advance(
        lender["id"],
        total_assets_cents=95_000_000,
        total_liabilities_cents=20_000_000,
        liquid_assets_cents=11_000_000,
    )
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("appr-beta")
    )
    # The identical 75,000,000 net worth fails the 100,000,000 STANDARD floor.
    validate_error(response, ApiErrorId.ERR_NET_WORTH_DEFICIENT)
    lender = get_lender(lender["id"])
    assert lender["status"] == "FIELD_REVIEW"
    assert lender["net_worth_variant"] == "STANDARD"
    assert lender["required_net_worth_cents"] == 100_000_000


# ---------------------------------------------------------------------------
# Difficulty: boundary precision at the approval floors
# ---------------------------------------------------------------------------
def _setup_lender_at_exact_floors(api):
    """SUPERVISED lender with adjusted net worth exactly 100,000,000 and liquidity
    product exactly 100,000,000."""
    lender = create_lender(legal_name="Exact Floor Co")
    filing = submit_filing(
        lender["id"],
        total_assets_cents=120_000_000,
        total_liabilities_cents=20_000_000,
        liquid_assets_cents=20_000_000,
    )
    decide_filing(filing["id"], lender["id"], "ACCEPT", reviewer="rev-alpha")
    advance_lender(lender["id"], reviewer="rev-alpha")
    return lender, filing


def test_net_worth_exactly_at_floor_passes_approval(api):
    """PRD §3.1: "Third, that filing's `adjusted_net_worth_cents` must be at least the
    lender's `required_net_worth_cents` (`ERR_NET_WORTH_DEFICIENT`). Fourth, the
    filing's `liquid_assets_cents` multiplied by five must be at least
    `required_net_worth_cents` — a twenty-percent liquidity test
    (`ERR_LIQUIDITY_DEFICIENT`)."

    Design: Difficulty/boundary_precision_check/net_worth_exactly_at_floor_passes_approval
    """
    lender, _filing = _setup_lender_at_exact_floors(api)
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("appr-beta")
    )
    data = validate_success(response)
    # Equality passes both floors: "at least" is >=, not >.
    assert data["status"] == "APPROVED"
    lender = get_lender(lender["id"])
    assert lender["required_net_worth_cents"] == 100_000_000


def test_net_worth_floor_boundary_filing_arithmetic(api):
    """PRD §3.1: "The system derives `adjusted_net_worth_cents` as total assets minus
    total liabilities."
    PRD §3.1: "Every other lender is `STANDARD`, and its requirement is the greater of
    100,000,000 cents and one percent of its `endorsed_volume_cents` rounded half-up
    to whole cents"

    Design: Difficulty/boundary_precision_check/net_worth_exactly_at_floor_passes_approval
    """
    lender, filing = _setup_lender_at_exact_floors(api)
    assert filing["adjusted_net_worth_cents"] == 100_000_000
    assert lender["net_worth_variant"] == "STANDARD"
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("appr-beta")
    )
    assert validate_success(response)["status"] == "APPROVED"


# ---------------------------------------------------------------------------
# Difficulty: priority pair — state beats fiscal
# ---------------------------------------------------------------------------
def _setup_returned_lender_with_deficient_filing():
    """Lender in RETURNED whose accepted filing is below the STANDARD floor:
    both a state violation (APPROVE not permitted from RETURNED) and a fiscal
    violation (net worth 40,000,000 < 100,000,000) are present."""
    lender = create_lender(legal_name="Priority Co")
    filing = submit_filing(
        lender["id"],
        total_assets_cents=60_000_000,
        total_liabilities_cents=20_000_000,
        liquid_assets_cents=9_000_000,
    )
    decide_filing(filing["id"], lender["id"], "ACCEPT", reviewer="rev-alpha")
    advance_lender(lender["id"], reviewer="rev-alpha")
    lender_action(lender["id"], "RETURN", make_reviewer_headers("rev-alpha"), note="incomplete")
    return lender


def test_approve_state_error_beats_fiscal_error(api):
    """PRD §2.7: "When a request violates more than one rule, the platform reports the
    violation whose category ranks earliest in the following priority order, so a
    caller always sees the most fundamental problem first:"
    PRD §2.7: "7. State legality: the target resource is in a state that permits the
    transition (`ERR_INVALID_STATE`, `ERR_CASE_BLOCKED`, `ERR_ALREADY_TERMINAL`)."
    PRD §2.7: "12. Financial sufficiency (`ERR_NET_WORTH_DEFICIENT`,
    `ERR_LIQUIDITY_DEFICIENT`, `ERR_QC_PLAN_MISSING`,
    `ERR_MIP_CANCELLATION_INELIGIBLE`)."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_error_beats_fiscal_error
    """
    lender = _setup_returned_lender_with_deficient_filing()
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("appr-beta")
    )
    # State legality (priority 7) is reported, not the net-worth floor (priority 12).
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_lender(lender["id"])["status"] == "RETURNED"


def test_approve_fiscal_error_surfaces_from_approvable_state(api):
    """PRD §3.1: "Third, that filing's `adjusted_net_worth_cents` must be at least the
    lender's `required_net_worth_cents` (`ERR_NET_WORTH_DEFICIENT`)."

    The isolated fiscal leg of the priority pair: once the state violation is cured
    (RETURNED -> DESK_REVIEW -> FIELD_REVIEW), the identical financials surface the
    fiscal error.

    Design: Difficulty/priority_pair_validation_conflict/approve_state_error_beats_fiscal_error
    """
    lender = _setup_returned_lender_with_deficient_filing()
    lender_action(
        lender["id"], "RESUBMIT", make_lender_officer_headers(lender["id"])
    )
    advance_lender(lender["id"], reviewer="rev-alpha")
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("appr-beta")
    )
    validate_error(response, ApiErrorId.ERR_NET_WORTH_DEFICIENT)


# ---------------------------------------------------------------------------
# Difficulty: lender return/resubmission cycle
# ---------------------------------------------------------------------------
def test_lender_return_resubmission_cycle_states(api):
    """PRD §3.1: "A returned application may be resubmitted by the owning
    `LenderOfficer`, which moves it from `RETURNED` back to `DESK_REVIEW`; the
    resubmission cycle `RETURNED` → `DESK_REVIEW` → `FIELD_REVIEW` may repeat any
    number of times."

    Design: Difficulty/non_linear_state_machine/lender_return_resubmission_cycle
    """
    lender = create_lender(legal_name="Cycle Lender Co")
    advance_lender(lender["id"], reviewer="rev-alpha")
    returned = lender_action(
        lender["id"], "RETURN", make_reviewer_headers("rev-alpha"), note="missing exhibits"
    )
    assert returned["status"] == "RETURNED"
    resubmitted = lender_action(
        lender["id"], "RESUBMIT", make_lender_officer_headers(lender["id"])
    )
    assert resubmitted["status"] == "DESK_REVIEW"


def test_lender_return_resubmission_cycle_reaches_approval(api):
    """PRD §3.1: "the resubmission cycle `RETURNED` → `DESK_REVIEW` → `FIELD_REVIEW`
    may repeat any number of times."
    PRD §3.1: "On approval the approver's identifier is recorded in
    `approved_by_user_id`, the net worth requirement and variant are recomputed, and
    the lender's `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/lender_return_resubmission_cycle
    """
    lender = create_lender(legal_name="Cycle Approve Co")
    filing = submit_filing(lender["id"], fiscal_year_end="2026-06-30")
    decide_filing(filing["id"], lender["id"], "ACCEPT", reviewer="rev-alpha")
    advance_lender(lender["id"], reviewer="rev-alpha")
    lender_action(lender["id"], "RETURN", make_reviewer_headers("rev-alpha"), note="missing exhibits")
    lender_action(lender["id"], "RESUBMIT", make_lender_officer_headers(lender["id"]))
    advance_lender(lender["id"], reviewer="rev-alpha")
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("appr-beta")
    )
    data = validate_success(response)
    assert data["status"] == "APPROVED"
    assert data["approved_by_user_id"] == "appr-beta"
# ---------------------------------------------------------------------------
# Fiscal gates at approval
# ---------------------------------------------------------------------------
def test_qc_plan_missing_at_approval(api):
    """PRD §3.1: "Fifth, `qc_plan_on_file` must be true (`ERR_QC_PLAN_MISSING`)."

    Design: Corner/validations/qc_plan_missing_at_approval
    """
    lender = create_lender(legal_name="No QC Co", qc_plan_on_file=False)
    filing = submit_filing(lender["id"])
    decide_filing(filing["id"], lender["id"], "ACCEPT")
    advance_lender(lender["id"], reviewer="rev-1")
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("app-1")
    )
    validate_error(response, ApiErrorId.ERR_QC_PLAN_MISSING)
    assert get_lender(lender["id"])["status"] == "FIELD_REVIEW"


def test_net_worth_deficient_at_approval(api):
    """PRD §3.1: "Third, that filing's `adjusted_net_worth_cents` must be at least the
    lender's `required_net_worth_cents` (`ERR_NET_WORTH_DEFICIENT`)."

    Design: Corner/validations/net_worth_deficient_at_approval
    """
    # Adjusted net worth 80,000,000 < the 100,000,000 STANDARD floor.
    lender = create_lender(legal_name="Thin Co")
    filing = submit_filing(
        lender["id"],
        total_assets_cents=50_000_000_000,
        total_liabilities_cents=49_920_000_000,
    )
    decide_filing(filing["id"], lender["id"], "ACCEPT")
    advance_lender(lender["id"], reviewer="rev-1")
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("app-1")
    )
    validate_error(response, ApiErrorId.ERR_NET_WORTH_DEFICIENT)


def test_liquidity_deficient_at_approval(api):
    """PRD §3.1: "Fourth, the filing's `liquid_assets_cents` multiplied by five must be
    at least `required_net_worth_cents` — a twenty-percent liquidity test
    (`ERR_LIQUIDITY_DEFICIENT`)."

    Design: Corner/validations/liquidity_deficient_at_approval
    """
    # Net worth 100,000,000 passes the floor; 15,000,000 * 5 = 75,000,000 fails.
    lender = create_lender(legal_name="Illiquid Co")
    filing = submit_filing(
        lender["id"],
        total_assets_cents=50_000_000_000,
        total_liabilities_cents=49_900_000_000,
        liquid_assets_cents=15_000_000,
    )
    decide_filing(filing["id"], lender["id"], "ACCEPT")
    advance_lender(lender["id"], reviewer="rev-1")
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("app-1")
    )
    validate_error(response, ApiErrorId.ERR_LIQUIDITY_DEFICIENT)


def test_filing_stale_at_approval(api):
    """PRD §3.1: "Second, the lender's `last_accepted_filing_id` must reference an
    accepted audited filing whose `fiscal_year_end` falls within the 15 months before
    the current logical date; otherwise the approval fails with `ERR_FILING_STALE`."

    Design: Corner/validations/filing_stale_at_approval
    """
    # FYE 2024-12-31 is more than 15 months before the 2026-09-01 logical date.
    lender = create_lender(legal_name="Stale Filing Co")
    filing = submit_filing(lender["id"], fiscal_year_end="2024-12-31")
    decide_filing(filing["id"], lender["id"], "ACCEPT")
    advance_lender(lender["id"], reviewer="rev-1")
    response = api_client.lender_status_change(
        lender["id"], {"action": "APPROVE"}, make_approver_headers("app-1")
    )
    validate_error(response, ApiErrorId.ERR_FILING_STALE)


def test_resubmit_by_non_owner_forbidden(api):
    """PRD §3.1: "Resubmission by anyone other than the lender that owns the
    application is rejected with `ERR_FORBIDDEN_OWNERSHIP`."
    PRD §2.1: "When `X-User-Role` is `LenderOfficer` or `ServicerOfficer`, `X-User-ID`
    is the `id` of the acting `Lender`; ownership checks on any resource that
    references a lender — directly, or through a loan case's `lender_id`, or through
    the parent chain of filings, appraisals, escrows, reviews, and claims — compare
    that lender id to `X-User-ID`, and a mismatch is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/validations/resubmit_by_non_owner_forbidden
    """
    lender = create_lender(legal_name="Owned Co")
    lender_action(lender["id"], "RETURN", make_reviewer_headers("rev-1"))
    response = api_client.lender_status_change(
        lender["id"], {"action": "RESUBMIT"}, make_lender_officer_headers(UNKNOWN_UUID)
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_required_net_worth_standard_variant_hits_floor_at_zero_volume(api):
    """PRD §3.1: "Every other lender is `STANDARD`, and its requirement is the greater
    of 100,000,000 cents and one percent of its `endorsed_volume_cents` rounded half-up
    to whole cents"

    Design: Corner/calculations/required_net_worth_standard_variant_hits_floor_at_zero_volume
    """
    # A SUPERVISED lender with zero endorsed volume: max(100,000,000, 0) binds the
    # floor, not the one-percent volume rate.
    lender = setup_approved_lender(
        lender_overrides={"legal_name": "Floor Co"}, advancer="rev-1", approver="app-1"
    )
    assert lender["status"] == "APPROVED"
    assert lender["net_worth_variant"] == "STANDARD"
    assert lender["required_net_worth_cents"] == 100_000_000

