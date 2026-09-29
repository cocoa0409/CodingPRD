"""
The failure surface: which check answers first, and which status each id carries.

The first scenario drives five refusals at the top two priorities to show that a
malformed payload behind absent credentials is never even inspected. The second
draws one refusal from each of the six statuses the service uses, against a single
prepared case, so a mapping mistake shows up as a status mismatch rather than as a
plausible-looking wrong identifier.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_START, MISSING_UUID
from test_helpers.test_users import (
    CASE_WORKER_HEADERS,
    FINANCE_OFFICER_HEADERS,
    NO_AUTH_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SUPERVISING_ATTORNEY_HEADERS,
    headers_with_empty_user_id,
    make_headers,
)

#: The one payload the credential tests keep constant while the headers vary.
_GOOD_PARTICIPANT: Dict[str, Any] = {
    "role_type": "CUSTODIAL_PARTY",
    "full_name": "Perpetua Odongo",
    "ssn_last4": "6247",
    "residence_state_code": "MN",
}


def test_01_absent_credentials_answer_before_the_payload_is_ever_read():
    """
    A two-digit `ssn_last4` behind missing headers still answers 401, never 422.

    Every request to this API — without exception, including reads — must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role.

    If either header is absent or present but empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401).

    Authentication and identity come first, in this internal order: header presence (`ERR_MISSING_AUTH_HEADERS`), role recognition (`ERR_INVALID_ROLE`), role authorisation for the endpoint (`ERR_UNAUTHORIZED`), then party ownership for `CustodialParty` and `NoncustodialParty` callers (`ERR_NOT_CASE_PARTY`), then employer ownership for `EmployerAgent` callers (`ERR_NOT_IWO_EMPLOYER`).

    Design: Corner/errors/auth_header_errors_preempt_payload_and_state_checks
    """
    fx.set_clock(CLOCK_START)

    validate_error(
        api_client.create_participant(dict(_GOOD_PARTICIPANT), NO_AUTH_HEADERS),
        ApiErrorId.MISSING_AUTH_HEADERS,
        401,
    )

    # The payload carries a two-digit ssn_last4 and a state code outside the set,
    # yet the credential check answers before the schema is looked at.
    malformed = dict(_GOOD_PARTICIPANT)
    malformed["ssn_last4"] = "12"
    malformed["residence_state_code"] = "ZZ"
    validate_error(
        api_client.create_participant(malformed, NO_AUTH_HEADERS),
        ApiErrorId.MISSING_AUTH_HEADERS,
        401,
    )

    # An empty X-User-ID counts as absent even though the role header is good.
    validate_error(
        api_client.create_participant(
            dict(_GOOD_PARTICIPANT), headers_with_empty_user_id("CaseWorker")
        ),
        ApiErrorId.MISSING_AUTH_HEADERS,
        401,
    )

    _rows, meta = validate_paginated(api_client.list_participants(CASE_WORKER_HEADERS))
    assert meta["total_count"] == 0


def test_02_an_unrecognised_role_name_is_a_different_refusal_from_a_missing_one():
    """
    `CountyAttorney` and the lowercased `caseworker` are both simply unknown roles.

    If `X-User-Role` carries a string that is not one of the eight roles enumerated below, the rejection is `ERR_INVALID_ROLE` (HTTP 401).

    The eight roles are `CaseWorker`, `SupervisingAttorney`, `FinanceOfficer`, `EmployerAgent`, `CustodialParty`, `NoncustodialParty`, `InterstateLiaison` and `ProgramAdmin`.

    Design: Corner/errors/auth_header_errors_preempt_payload_and_state_checks
    """
    fx.set_clock(CLOCK_START)

    validate_error(
        api_client.create_participant(
            dict(_GOOD_PARTICIPANT), make_headers("user-attorney-009", "CountyAttorney")
        ),
        ApiErrorId.INVALID_ROLE,
        401,
    )

    # Role names match exactly, so a lowercased real role is an unknown role.
    validate_error(
        api_client.create_participant(
            dict(_GOOD_PARTICIPANT), make_headers("user-caseworker-001", "caseworker")
        ),
        ApiErrorId.INVALID_ROLE,
        401,
    )

    # The identical payload succeeds the moment the headers are right.
    created = validate_success(
        api_client.create_participant(dict(_GOOD_PARTICIPANT), CASE_WORKER_HEADERS), 201
    )
    assert created["role_type"] == "CUSTODIAL_PARTY"
    assert created["id"]

    _rows, meta = validate_paginated(api_client.list_participants(CASE_WORKER_HEADERS))
    # Four refused requests wrote nothing; only the credentialled one landed.
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# One refusal from each declared status, against one prepared case
# ---------------------------------------------------------------------------


def _entered_order_whose_version_has_already_moved() -> Dict[str, Any]:
    """
    An entered 75,000-cent order, a Minnesota employer, and the order version as
    it read *before* a charge posting silently advanced it.
    """
    scenario = fx.case_with_entered_order(
        clock=CLOCK_START,
        cp_overrides={
            "full_name": "Wilhelmina Osei",
            "ssn_last4": "6248",
            "monthly_gross_income_cents": 200000,
        },
        ncp_overrides={
            "full_name": "Kwabena Osei",
            "ssn_last4": "6249",
            "monthly_gross_income_cents": 300000,
            "supports_second_family": False,
            "has_valid_drivers_license": True,
        },
        case_overrides={"child_count": 2, "tanf_assistance": False, "good_cause_claim": False},
        order_overrides={
            "origin_state_code": "MN",
            "effective_date": "2026-08-01",
            "medical_support_monthly_cents": 0,
        },
    )
    scenario.employer = fx.create_employer(
        legal_name="Osei Freight Lines",
        fein="41-0000114",
        state_code="MN",
        pay_frequency="MONTHLY",
        remittance_fee_cents=0,
    )
    stale_version = fx.read_order(scenario.order_id)["version"]
    charge = fx.post_charge(
        scenario.order_id,
        charge_type="CURRENT_SUPPORT",
        period_start_date="2026-08-01",
        period_end_date="2026-09-01",
        due_date="2026-08-15",
        amount_cents=75000,
    )
    scenario.charges = [charge]
    return {"scenario": scenario, "stale_version": stale_version}


def test_03_the_two_identity_statuses_and_the_not_found_status_answer_as_declared():
    """
    An unknown role reads 401, an unauthorised one 403, and a resolvable path 404.

    If the role is well formed but that role is not among the roles authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

    Path variables are resolved strictly left to right, and the first segment that fails to resolve determines the error. `{participant_id}` must resolve to a `Participant` or the answer is `ERR_PARTICIPANT_NOT_FOUND`; `{case_id}` to a `SupportCase` or `ERR_CASE_NOT_FOUND`; `{paternity_action_id}` to a `PaternityAction` or `ERR_PATERNITY_ACTION_NOT_FOUND`; `{order_id}` to a `SupportOrder` or `ERR_ORDER_NOT_FOUND`; `{employer_id}` to an `Employer` or `ERR_EMPLOYER_NOT_FOUND`; `{iwo_id}` to an `IncomeWithholdingOrder` or `ERR_IWO_NOT_FOUND`; `{charge_id}` to an `ObligationCharge` or `ERR_CHARGE_NOT_FOUND`; `{payment_id}` to a `PaymentTransaction` or `ERR_PAYMENT_NOT_FOUND`; `{modification_review_id}` to a `ModificationReview` or `ERR_REVIEW_NOT_FOUND`; `{enforcement_action_id}` to an `EnforcementAction` or `ERR_ENFORCEMENT_ACTION_NOT_FOUND`; `{interstate_referral_id}` to an `InterstateReferral` or `ERR_REFERRAL_NOT_FOUND`; and `{compromise_offer_id}` to a `CompromiseOffer` or `ERR_OFFER_NOT_FOUND`.

    Design: Corner/errors/one_error_per_declared_status_maps_to_its_declared_code
    """
    built = _entered_order_whose_version_has_already_moved()
    scenario = built["scenario"]

    # An unknown role on a read the caller would otherwise have been allowed.
    validate_error(
        api_client.get_case(scenario.case_id, make_headers("user-auditor-001", "Auditor")),
        ApiErrorId.INVALID_ROLE,
        401,
    )

    # Closure is SupervisingAttorney-exclusive: authenticated but not authorised.
    validate_error(
        api_client.close_case(
            scenario.case_id, f.closure_payload("CP_REQUEST"), FINANCE_OFFICER_HEADERS
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    # A well-formed identifier that matches no row.
    validate_error(
        api_client.get_charge(MISSING_UUID, FINANCE_OFFICER_HEADERS),
        ApiErrorId.CHARGE_NOT_FOUND,
        404,
    )


def test_04_a_concurrency_failure_is_a_412_and_never_degrades_to_a_422():
    """
    The stale version was correct when it was read, so the answer is 412, not 422.

    If that value does not equal the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` and HTTP 412.

    It adds its `amount_cents` to the case's `total_charged_principal_cents` and advances the order's `next_accrual_due_date` by one month, and it increases both the case's and the order's `version` by 1.

    Next comes payload schema validation (`ERR_VALIDATION`): required fields present, enum values inside their declared sets, integer money values non-negative, `child_count` between 1 and 6 inclusive, `installment_count` between 3 and 36 inclusive, `genetic_probability_pct` between 0 and 100 inclusive, and ISO dates well formed.

    The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.

    Design: Corner/errors/one_error_per_declared_status_maps_to_its_declared_code
    """
    built = _entered_order_whose_version_has_already_moved()
    scenario = built["scenario"]
    stale_version = built["stale_version"]

    assert scenario.order["monthly_obligation_cents"] == 75000
    fresh_version = fx.read_order(scenario.order_id)["version"]
    assert fresh_version == stale_version + 1

    # The order is already ENTERED, so entry has no available origin state.
    validate_error(
        api_client.enter_order(scenario.order_id, f.entry_payload(), SUPERVISING_ATTORNEY_HEADERS),
        ApiErrorId.INVALID_ORDER_STATUS,
        409,
    )

    stale = api_client.issue_withholding_order(
        scenario.order_id,
        f.withholding_order_payload(
            scenario.employer_id, stale_version, reported_disposable_income_cents=150000
        ),
        CASE_WORKER_HEADERS,
    )
    validate_error(stale, ApiErrorId.STALE_ORDER_VERSION, 412)

    invalid = api_client.create_case(
        f.case_payload(scenario.cp_id, scenario.ncp_id, child_count=7),
        CASE_WORKER_HEADERS,
    )
    validate_error(invalid, ApiErrorId.VALIDATION, 422)

    # The failure envelope carries an identifier and a message, and nothing else.
    body = invalid.json()
    assert body["response_type"] == "error"
    assert sorted(body["data"].keys()) == ["error_id", "message"]
    assert sorted(body["meta"].keys()) == ["api_request_id", "api_request_timestamp"]
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]

    # Neither the 412 nor the 422 persisted anything.
    _iwos, iwo_meta = validate_paginated(
        api_client.list_withholding_orders(
            CASE_WORKER_HEADERS, params={"order_id": scenario.order_id}
        )
    )
    assert iwo_meta["total_count"] == 0
    _cases, case_meta = validate_paginated(api_client.list_cases(CASE_WORKER_HEADERS))
    assert case_meta["total_count"] == 1
