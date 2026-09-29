"""Which of a request's several defects the server chooses to report.

A single request frequently violates more than one rule, and the PRD fixes a
strict total order over the rules rather than leaving the reported error to
chance. These tests aim requests that are broken in two ways at once and pin the
code that comes back: authentication before authorisation, authorisation before
the schema, the schema before path existence, path existence before the state
machine, body references before scope agreement, and optimistic concurrency
before every business rule. The two boundary cases at the far end of the order —
a benchmark percentile landing exactly on the safe harbour and a licence
expiring exactly today — are pinned on the passing side.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import PRECEDENCE_RANK, ApiErrorId
from test_helpers.constants import (
    BENCHMARK_BASIS_TOTAL_CASH_COMP,
    CLEARANCE_CLEARED,
    CLEARANCE_PENDING,
    DEAL_STATUS_CLOSED,
    DEAL_STATUS_DILIGENCE,
    DEAL_STATUS_SOURCING,
    EMPLOYMENT_OFFERED,
    LICENSE_EXPIRY_C,
    MODEL_STRAIGHT_SALARY,
    NPI_C,
    PHYSICIAN_NAME_C,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_SUBMITTED,
    SPECIALTY_CARDIOLOGY,
    STARK_NONE,
    USER_COMPLIANCE_OFFICER_ALT,
)
from test_helpers.fixtures import (
    COMPENSATION_DESIGNER,
    COMPLIANCE_OFFICER,
    COMPLIANCE_OFFICER_ALT,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    VALUATION_ANALYST,
    acquisition_version,
    approve_plan,
    board_review_deal,
    create_acquisition,
    create_cardiology_acquisition,
    create_payer_contract,
    create_physician,
    diligence_deal,
    park_clock_on_date,
    read_acquisition,
    reset_clock,
    set_clearance,
    submit_plan,
)
from test_helpers.test_users import (
    EMPTY_USER_ID_HEADERS,
    NO_USER_ID_HEADERS,
    UNRECOGNISED_ROLE_HEADERS,
    make_practice_physician_headers,
)

# A body that is missing eight required fields and names a specialty the PRD
# does not declare. It is malformed on two counts, so whichever rank reports it
# first is unambiguous.
MALFORMED_ACQUISITION_BODY = {
    "target_practice_name": "Lakeside Family Medicine",
    "specialty": "PODIATRY",
}
UNDECLARED_DEAL_STATUS = "RENEGOTIATING"

# The PRIMARY_CARE total-cash-compensation survey points the plans below sit on.
MEDIAN_TCC_CENTS = 26_500_000
MEDIAN_PERCENTILE = 50.00
SAFE_HARBOUR_TCC_CENTS = 36_000_000
SAFE_HARBOUR_PERCENTILE = 90.00
# 100000 cents above the ninetieth-percentile point is 9 * 100000 / 36000000 of
# the way past it, which is 0.025 of a percentile and rounds half up to 90.03.
ABOVE_HARBOUR_TCC_CENTS = 36_100_000
ABOVE_HARBOUR_PERCENTILE = 90.03

LICENCE_EXPIRES_TODAY = "2026-08-01"
DAY_AFTER_THE_LICENCE_LAPSES = "2026-08-02"


def _salary_plan(
    api: ApiClient, acquisition_id: str, physician_id: str, base_salary_cents: int, **overrides
):
    """A STRAIGHT_SALARY plan that quotes no work-RVU inputs at all.

    The four economic inputs are optional, so a salaried design simply omits the
    three productivity fields rather than sending zeros for them.
    """
    version = acquisition_version(api, acquisition_id, COMPENSATION_DESIGNER)
    payload = f.without(
        f.compensation_plan_payload(
            acquisition_id,
            version,
            physician_id,
            model_type=MODEL_STRAIGHT_SALARY,
            base_salary_cents=base_salary_cents,
            **overrides,
        ),
        "conversion_factor_cents_per_wrvu",
        "threshold_wrvu",
        "projected_annual_wrvu",
    )
    return validate_success(api.create_compensation_plan(payload, COMPENSATION_DESIGNER), 201)


def _request_plan_status(api: ApiClient, plan_id: str, target_status: str, headers):
    return api.set_compensation_plan_status(
        plan_id, f.plan_status_payload(target_status), headers
    )


def _read_plan(api: ApiClient, plan_id: str):
    return validate_success(api.get_compensation_plan(plan_id, COMPENSATION_DESIGNER))


# ---------------------------------------------------------------------------
# Rank 1 over rank 2 — authentication before authorisation
# ---------------------------------------------------------------------------


def test_a_missing_identity_outranks_a_role_the_endpoint_would_refuse(api: ApiClient):
    """A caller with no identity is never told that its role was also wrong.

    PRD: "If either header is absent, is present but holds the empty string, or
    if `X-User-Role` holds a value that is not one of the six recognised roles,
    the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/validations/forbidden_role_call_missing_x_user_returns_unauthenticated
    """
    reset_clock(api)

    rejected = api.create_acquisition(f.acquisition_payload(), NO_USER_ID_HEADERS)

    error = validate_error(rejected, ApiErrorId.UNAUTHENTICATED, 401)
    assert error["error_id"] != ApiErrorId.FORBIDDEN_ROLE
    assert PRECEDENCE_RANK[ApiErrorId.UNAUTHENTICATED] < PRECEDENCE_RANK[ApiErrorId.FORBIDDEN_ROLE]
    a.assert_total_count(api.list_acquisitions({}, DEAL_LEAD), 0)


def test_an_empty_identity_and_an_unknown_role_are_both_unauthenticated(api: ApiClient):
    """Blankness and unrecognised roles fail the same check, ahead of the role gate.

    PRD: "This check runs before anything else about the request is examined."

    Design: Corner/validations/forbidden_role_call_missing_x_user_returns_unauthenticated
    """
    reset_clock(api)

    blank_identity = api.create_acquisition(f.acquisition_payload(), EMPTY_USER_ID_HEADERS)
    unknown_role = api.create_acquisition(f.acquisition_payload(), UNRECOGNISED_ROLE_HEADERS)

    validate_error(blank_identity, ApiErrorId.UNAUTHENTICATED, 401)
    unknown = validate_error(unknown_role, ApiErrorId.UNAUTHENTICATED, 401)
    assert unknown["error_id"] != ApiErrorId.FORBIDDEN_ROLE
    assert EMPTY_USER_ID_HEADERS["X-User-ID"] == ""
    a.assert_total_count(api.list_acquisitions({}, DEAL_LEAD), 0)


# ---------------------------------------------------------------------------
# Rank 2 over rank 3 — the role gate before the body is parsed
# ---------------------------------------------------------------------------


def _physician_identity_on_a_cardiology_deal(api: ApiClient):
    """A real Physician row whose id is the entity-backed PracticePhysician caller."""
    reset_clock(api)
    acquisition = create_cardiology_acquisition(api)
    physician = create_physician(
        api,
        acquisition["id"],
        npi=NPI_C,
        full_name=PHYSICIAN_NAME_C,
        specialty=SPECIALTY_CARDIOLOGY,
        state_license_expires_on=LICENSE_EXPIRY_C,
    )
    return {"acquisition": acquisition, "physician": physician}


def test_a_forbidden_caller_never_learns_that_its_body_was_malformed(api: ApiClient):
    """The role gate answers first, so the two body defects go unmentioned.

    PRD: "If both headers are well formed but the named role is not authorised
    for the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` and HTTP 403; because that gate runs before the request
    body is parsed, a caller in a forbidden role never learns whether its
    payload was well formed."

    Design: Corner/validations/malformed_body_from_wrong_role_returns_forbidden
    """
    world = _physician_identity_on_a_cardiology_deal(api)
    physician_headers = make_practice_physician_headers(world["physician"]["id"])

    rejected = api.create_acquisition(MALFORMED_ACQUISITION_BODY, physician_headers)

    error = validate_error(rejected, ApiErrorId.FORBIDDEN_ROLE, 403)
    assert error["error_id"] != ApiErrorId.INVALID_REQUEST
    assert PRECEDENCE_RANK[ApiErrorId.FORBIDDEN_ROLE] < PRECEDENCE_RANK[ApiErrorId.INVALID_REQUEST]
    rows = a.assert_total_count(api.list_acquisitions({}, DEAL_LEAD), 1)
    a.assert_contains_id(rows, world["acquisition"]["id"])


def test_the_identical_body_from_an_authorised_role_is_a_schema_failure(api: ApiClient):
    """The body really was malformed; only the forbidden caller was spared the detail.

    PRD: "**Schema** — on every endpoint: required fields present, types
    correct, enum values recognised, dates in `YYYY-MM-DD` form, instants in ISO
    8601 UTC form, money and count fields non-negative, `limit` within 1 to 100
    and `offset` non-negative."

    Design: Corner/validations/malformed_body_from_wrong_role_returns_forbidden
    """
    world = _physician_identity_on_a_cardiology_deal(api)
    physician_headers = make_practice_physician_headers(world["physician"]["id"])
    validate_error(
        api.create_acquisition(MALFORMED_ACQUISITION_BODY, physician_headers),
        ApiErrorId.FORBIDDEN_ROLE,
        403,
    )

    as_the_owner = api.create_acquisition(MALFORMED_ACQUISITION_BODY, DEAL_LEAD)

    validate_error(as_the_owner, ApiErrorId.INVALID_REQUEST, 400)
    rows = a.assert_total_count(api.list_acquisitions({}, DEAL_LEAD), 1)
    a.assert_contains_id(rows, world["acquisition"]["id"])
    assert rows[0]["specialty"] == SPECIALTY_CARDIOLOGY
    assert (
        rows[0]["target_practice_name"] != MALFORMED_ACQUISITION_BODY["target_practice_name"]
    )


# ---------------------------------------------------------------------------
# Rank 3 over rank 4 — the schema before the path lookup
# ---------------------------------------------------------------------------


def test_an_unrecognised_target_status_is_rejected_before_the_path_is_resolved(
    api: ApiClient,
):
    """No lookup is attempted for a request the schema has already condemned.

    PRD: "The system evaluates rules in a strict total order and returns the
    error belonging to the first rule violated; no two rules share a rank."

    Design: Corner/validations/unknown_acquisition_with_invalid_enum_returns_invalid_request
    """
    reset_clock(api)

    rejected = api.set_acquisition_status(
        NON_EXISTENT_UUID, {"target_status": UNDECLARED_DEAL_STATUS}, DEAL_LEAD
    )

    error = validate_error(rejected, ApiErrorId.INVALID_REQUEST, 400)
    assert error["error_id"] != ApiErrorId.RESOURCE_NOT_FOUND
    assert (
        PRECEDENCE_RANK[ApiErrorId.INVALID_REQUEST]
        < PRECEDENCE_RANK[ApiErrorId.RESOURCE_NOT_FOUND]
    )


def test_the_same_unknown_path_with_a_declared_status_is_a_not_found(api: ApiClient):
    """Repair the enum and the same request reaches the lookup and fails there.

    PRD: "**Path existence** — every identifier in the URL path resolves, on
    every endpoint that has a path parameter. Otherwise
    `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/validations/unknown_acquisition_with_invalid_enum_returns_invalid_request
    """
    reset_clock(api)
    validate_error(
        api.set_acquisition_status(
            NON_EXISTENT_UUID, {"target_status": UNDECLARED_DEAL_STATUS}, DEAL_LEAD
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )

    with_a_declared_status = api.set_acquisition_status(
        NON_EXISTENT_UUID, f.acquisition_status_payload(DEAL_STATUS_DILIGENCE), DEAL_LEAD
    )

    validate_error(with_a_declared_status, ApiErrorId.RESOURCE_NOT_FOUND, 404)


# ---------------------------------------------------------------------------
# Rank 4 over rank 14 — existence before the state machine
# ---------------------------------------------------------------------------


def test_an_impossible_transition_on_an_unknown_deal_is_a_not_found(api: ApiClient):
    """There is no current state against which to judge the transition.

    PRD: "An identifier that does not resolve to a stored entity of the expected
    type yields `ERR_RESOURCE_NOT_FOUND` with HTTP 404; a single shared code
    covers every entity type, and only the human-readable `message` names which
    entity was not found."

    Design: Corner/validations/unknown_acquisition_with_valid_transition_returns_not_found
    """
    reset_clock(api)
    real = create_acquisition(api)
    a.assert_status(real, DEAL_STATUS_SOURCING, "deal_status")

    rejected = api.set_acquisition_status(
        NON_EXISTENT_UUID, f.acquisition_status_payload(DEAL_STATUS_CLOSED), DEAL_LEAD
    )

    error = validate_error(rejected, ApiErrorId.RESOURCE_NOT_FOUND, 404)
    assert error["error_id"] != ApiErrorId.INVALID_STATE_TRANSITION
    assert (
        PRECEDENCE_RANK[ApiErrorId.RESOURCE_NOT_FOUND]
        < PRECEDENCE_RANK[ApiErrorId.INVALID_STATE_TRANSITION]
    )


def test_the_same_transition_against_the_real_deal_is_an_illegal_transition(api: ApiClient):
    """The transition really is undeclared; the unknown id simply masked it.

    PRD: "**State transition legality** — the requested transition is declared
    for the entity's current state, on every action endpoint. This rank absorbs
    every terminal-state lockdown and every repeat of an already-applied
    transition, and it outranks every business rule below it: an action that is
    both out of sequence and economically impossible reports the sequencing
    failure."

    Design: Corner/validations/unknown_acquisition_with_valid_transition_returns_not_found
    """
    reset_clock(api)
    real = create_acquisition(api)

    rejected = api.set_acquisition_status(
        real["id"], f.acquisition_status_payload(DEAL_STATUS_CLOSED), DEAL_LEAD
    )

    validate_error(rejected, ApiErrorId.INVALID_STATE_TRANSITION, 409)
    a.assert_status(read_acquisition(api, real["id"]), DEAL_STATUS_SOURCING, "deal_status")


def test_one_shared_not_found_code_covers_every_entity_type(api: ApiClient):
    """An unknown acquisition and an unknown plan answer with the identical code.

    PRD: "Path parameters are resolved left to right before the request body is
    inspected."

    Design: Corner/validations/unknown_acquisition_with_valid_transition_returns_not_found
    """
    reset_clock(api)
    create_acquisition(api)

    unknown_acquisition = validate_error(
        api.set_acquisition_status(
            NON_EXISTENT_UUID, f.acquisition_status_payload(DEAL_STATUS_DILIGENCE), DEAL_LEAD
        ),
        ApiErrorId.RESOURCE_NOT_FOUND,
        404,
    )
    unknown_plan = validate_error(
        _request_plan_status(api, NON_EXISTENT_UUID, PLAN_STATUS_SUBMITTED, COMPENSATION_DESIGNER),
        ApiErrorId.RESOURCE_NOT_FOUND,
        404,
    )

    for error in (unknown_acquisition, unknown_plan):
        assert error["error_id"] == ApiErrorId.RESOURCE_NOT_FOUND
        assert "ACQUISITION" not in error["error_id"]
        assert "PLAN" not in error["error_id"]
        assert error["message"].strip() != ""


# ---------------------------------------------------------------------------
# Rank 5 over rank 6 — body references before acquisition scope agreement
# ---------------------------------------------------------------------------


def _two_deals_with_the_contract_and_the_physician_apart(api: ApiClient):
    """Acquisition A holds the payer contract; acquisition B holds the physician."""
    reset_clock(api)
    acquisition_a = create_acquisition(api)
    acquisition_b = create_cardiology_acquisition(api)
    physician_b = create_physician(
        api,
        acquisition_b["id"],
        npi=NPI_C,
        full_name=PHYSICIAN_NAME_C,
        specialty=SPECIALTY_CARDIOLOGY,
        state_license_expires_on=LICENSE_EXPIRY_C,
    )
    contract_a = create_payer_contract(api, acquisition_a["id"])
    return {
        "acquisition_a": acquisition_a,
        "acquisition_b": acquisition_b,
        "physician_b": physician_b,
        "contract_a": contract_a,
    }


def test_an_unknown_body_reference_outranks_the_cross_reference_check(api: ApiClient):
    """The dangling physician id is reported, not the contract's foreign acquisition.

    PRD: "Foreign keys carried in a request body are resolved with the same code,
    `ERR_RESOURCE_NOT_FOUND`, but strictly after path parameters and strictly
    before any cross-reference consistency check. An unknown identifier is
    therefore never reported as a scope mismatch."

    Design: Corner/validations/unknown_physician_with_cross_acquisition_contract_returns_not_found
    """
    world = _two_deals_with_the_contract_and_the_physician_apart(api)

    rejected = api.create_credentialing_package(
        f.credentialing_package_payload(
            world["acquisition_a"]["id"], NON_EXISTENT_UUID, world["contract_a"]["id"]
        ),
        INTEGRATION_MANAGER,
    )

    error = validate_error(rejected, ApiErrorId.RESOURCE_NOT_FOUND, 404)
    assert error["error_id"] != ApiErrorId.ACQUISITION_SCOPE_MISMATCH
    assert (
        PRECEDENCE_RANK[ApiErrorId.RESOURCE_NOT_FOUND]
        < PRECEDENCE_RANK[ApiErrorId.ACQUISITION_SCOPE_MISMATCH]
    )
    a.assert_total_count(
        api.list_credentialing_packages(
            {"acquisition_id": world["acquisition_a"]["id"]}, INTEGRATION_MANAGER
        ),
        0,
    )


def test_a_real_physician_from_the_other_deal_is_a_scope_mismatch(api: ApiClient):
    """Once every reference resolves, the disagreement over the deal surfaces.

    PRD: "**Acquisition scope agreement** — all foreign keys in one request body
    belong to the same acquisition, on `POST /compensation-plans`, `POST
    /credentialing-packages`, and `POST /performance-reports`. Otherwise
    `ERR_ACQUISITION_SCOPE_MISMATCH` (409)."

    Design: Corner/validations/unknown_physician_with_cross_acquisition_contract_returns_not_found
    """
    world = _two_deals_with_the_contract_and_the_physician_apart(api)
    validate_error(
        api.create_credentialing_package(
            f.credentialing_package_payload(
                world["acquisition_a"]["id"], NON_EXISTENT_UUID, world["contract_a"]["id"]
            ),
            INTEGRATION_MANAGER,
        ),
        ApiErrorId.RESOURCE_NOT_FOUND,
        404,
    )

    rejected = api.create_credentialing_package(
        f.credentialing_package_payload(
            world["acquisition_a"]["id"],
            world["physician_b"]["id"],
            world["contract_a"]["id"],
        ),
        INTEGRATION_MANAGER,
    )

    validate_error(rejected, ApiErrorId.ACQUISITION_SCOPE_MISMATCH, 409)
    assert world["physician_b"]["acquisition_id"] == world["acquisition_b"]["id"]
    assert world["contract_a"]["acquisition_id"] == world["acquisition_a"]["id"]
    a.assert_total_count(
        api.list_credentialing_packages(
            {"acquisition_id": world["acquisition_a"]["id"]}, INTEGRATION_MANAGER
        ),
        0,
    )


# ---------------------------------------------------------------------------
# Rank 13 over rank 22 — optimistic concurrency before the business rules
# ---------------------------------------------------------------------------


def _incomplete_income_body(acquisition_id: str, version: int):
    """An INCOME_APPROACH opinion carrying only one of the five inputs it needs."""
    return f.without(
        f.income_fmv_payload(acquisition_id, version),
        "projection_years",
        "ebitda_growth_bps",
        "discount_rate_bps",
        "terminal_growth_bps",
    )


def _deal_whose_version_moved_under_the_analyst(api: ApiClient):
    """The analyst's reading is superseded by an officer's later clearance move.

    The advancing writer has to mutate the acquisition row itself, because that is
    what PRD ties the counter to: "a `version`, a plain integer that starts at 1
    when the row is inserted and increases by exactly 1 on every mutation of that
    row". Registering a child physician inserts a `Physician` row and leaves the
    acquisition untouched, so it moves no version; moving the regulatory dimension
    mutates the acquisition and does. `CLEARED` is chosen over `FLAGGED` so the
    deal is not frozen, leaving the filing to be judged on the ranks under test.
    """
    reset_clock(api)
    deal = diligence_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    stale_version = acquisition_version(api, acquisition_id, VALUATION_ANALYST)
    set_clearance(api, acquisition_id, CLEARANCE_CLEARED)
    deal["stale_version"] = stale_version
    deal["fresh_version"] = acquisition_version(api, acquisition_id, VALUATION_ANALYST)
    return deal


def test_a_stale_reader_is_told_to_re_read_rather_than_handed_a_business_error(
    api: ApiClient,
):
    """The version check fires even though the same body is missing four inputs.

    PRD: "**Optimistic concurrency** — `expected_acquisition_version` equals the
    stored acquisition `version`, on `POST /valuation-opinions` and `POST
    /compensation-plans`. Checked after existence and scope but before any state
    or business rule, so a stale reader is told to re-read rather than being
    handed a business error derived from a version it never observed."

    Design: Corner/validations/stale_version_beats_missing_valuation_input
    """
    deal = _deal_whose_version_moved_under_the_analyst(api)
    acquisition_id = deal["acquisition"]["id"]
    assert deal["fresh_version"] > deal["stale_version"]

    rejected = api.create_valuation_opinion(
        _incomplete_income_body(acquisition_id, deal["stale_version"]), VALUATION_ANALYST
    )

    error = validate_error(rejected, ApiErrorId.STALE_ACQUISITION_VERSION, 412)
    assert error["error_id"] != ApiErrorId.MISSING_VALUATION_INPUT
    assert (
        PRECEDENCE_RANK[ApiErrorId.STALE_ACQUISITION_VERSION]
        < PRECEDENCE_RANK[ApiErrorId.MISSING_VALUATION_INPUT]
    )
    a.assert_total_count(
        api.list_valuation_opinions({"acquisition_id": acquisition_id}, VALUATION_ANALYST), 0
    )


def test_the_same_body_at_the_fresh_version_reports_the_missing_inputs(api: ApiClient):
    """Re-reading the acquisition exposes the defect the version check was hiding.

    PRD: "Beyond compatibility, the method dictates which inputs must be present,
    and a gap is `ERR_MISSING_VALUATION_INPUT`: `INCOME_APPROACH` requires
    `normalized_ebitda_cents`, `projection_years`, `ebitda_growth_bps`,
    `discount_rate_bps`, and `terminal_growth_bps`; `MARKET_APPROACH` requires
    `normalized_ebitda_cents` and `market_multiple_bps`; `NARRATIVE` requires
    `cr_conclusion`, which is either `REASONABLE` or `NOT_REASONABLE`."

    Design: Corner/validations/stale_version_beats_missing_valuation_input
    """
    deal = _deal_whose_version_moved_under_the_analyst(api)
    acquisition_id = deal["acquisition"]["id"]
    validate_error(
        api.create_valuation_opinion(
            _incomplete_income_body(acquisition_id, deal["stale_version"]), VALUATION_ANALYST
        ),
        ApiErrorId.STALE_ACQUISITION_VERSION,
        412,
    )

    resent = api.create_valuation_opinion(
        _incomplete_income_body(acquisition_id, deal["fresh_version"]), VALUATION_ANALYST
    )

    validate_error(resent, ApiErrorId.MISSING_VALUATION_INPUT, 422)
    a.assert_total_count(
        api.list_valuation_opinions({"acquisition_id": acquisition_id}, VALUATION_ANALYST), 0
    )


# ---------------------------------------------------------------------------
# Rank 17 over rank 18 — referral-linked pay before the missing Stark exception
# ---------------------------------------------------------------------------


def _deal_with_a_referral_linked_draft(api: ApiClient):
    """A DRAFT plan that both pays for referrals and names no exception."""
    reset_clock(api)
    deal = diligence_deal(api)
    deal["plan"] = _salary_plan(
        api,
        deal["acquisition"]["id"],
        deal["physician"]["id"],
        MEDIAN_TCC_CENTS,
        includes_referral_credit=True,
        stark_exception=STARK_NONE,
    )
    return deal


def test_referral_linked_pay_outranks_the_missing_stark_exception(api: ApiClient):
    """No exception could have saved the plan, so the referral rule answers first.

    PRD: "`includes_referral_credit` must be false — compensation varying with
    the volume or value of referrals is categorically prohibited, and the
    rejection is `ERR_REFERRAL_LINKED_COMPENSATION`. `stark_exception` must not
    be `NONE`, or the rejection is `ERR_STARK_EXCEPTION_REQUIRED`."

    Design: Corner/validations/referral_credit_beats_missing_stark_exception
    """
    deal = _deal_with_a_referral_linked_draft(api)
    plan = deal["plan"]
    a.assert_status(plan, PLAN_STATUS_DRAFT)
    assert plan["includes_referral_credit"] is True
    assert plan["stark_exception"] == STARK_NONE

    rejected = _request_plan_status(api, plan["id"], PLAN_STATUS_SUBMITTED, COMPENSATION_DESIGNER)

    error = validate_error(rejected, ApiErrorId.REFERRAL_LINKED_COMPENSATION, 422)
    assert error["error_id"] != ApiErrorId.STARK_EXCEPTION_REQUIRED
    assert (
        PRECEDENCE_RANK[ApiErrorId.REFERRAL_LINKED_COMPENSATION]
        < PRECEDENCE_RANK[ApiErrorId.STARK_EXCEPTION_REQUIRED]
    )
    unchanged = _read_plan(api, plan["id"])
    a.assert_status(unchanged, PLAN_STATUS_DRAFT)
    assert unchanged["returned_count"] == 0


def test_a_sibling_that_only_lacks_the_exception_reports_the_lower_ranked_rule(
    api: ApiClient,
):
    """With the referral credit removed, the next rule down becomes visible.

    PRD: "**A referral-prohibition exception is named**, on `POST
    /compensation-plans/{planId}/status` with a target status of `SUBMITTED`.
    Otherwise `ERR_STARK_EXCEPTION_REQUIRED` (422)."

    Design: Corner/validations/referral_credit_beats_missing_stark_exception
    """
    deal = _deal_with_a_referral_linked_draft(api)
    validate_error(
        _request_plan_status(api, deal["plan"]["id"], PLAN_STATUS_SUBMITTED, COMPENSATION_DESIGNER),
        ApiErrorId.REFERRAL_LINKED_COMPENSATION,
        422,
    )

    sibling = _salary_plan(
        api,
        deal["acquisition"]["id"],
        deal["physician"]["id"],
        MEDIAN_TCC_CENTS,
        includes_referral_credit=False,
        stark_exception=STARK_NONE,
    )
    rejected = _request_plan_status(api, sibling["id"], PLAN_STATUS_SUBMITTED, COMPENSATION_DESIGNER)

    validate_error(rejected, ApiErrorId.STARK_EXCEPTION_REQUIRED, 422)
    still_draft = _read_plan(api, sibling["id"])
    a.assert_status(still_draft, PLAN_STATUS_DRAFT)
    assert still_draft["returned_count"] == 0


def test_a_referral_linked_plan_anywhere_on_the_deal_blocks_the_clearance(api: ApiClient):
    """The same rule guards the clearance move, not only the submission.

    PRD: "`PENDING → CLEARED` requires two things of the acquisition's
    compensation plans: none may be in `COMPLIANCE_HOLD`, and none may have
    `includes_referral_credit` true — a referral-linked plan anywhere on the deal
    blocks clearance with `ERR_REFERRAL_LINKED_COMPENSATION`."

    Design: Corner/validations/referral_credit_beats_missing_stark_exception
    """
    deal = _deal_with_a_referral_linked_draft(api)
    acquisition_id = deal["acquisition"]["id"]
    assert deal["acquisition"]["compliance_clearance"] == CLEARANCE_PENDING

    rejected = api.set_compliance_clearance(
        acquisition_id, f.compliance_clearance_payload(CLEARANCE_CLEARED), COMPLIANCE_OFFICER
    )

    validate_error(rejected, ApiErrorId.REFERRAL_LINKED_COMPENSATION, 422)
    frozen = read_acquisition(api, acquisition_id)
    assert frozen["compliance_clearance"] == CLEARANCE_PENDING
    a.assert_status(_read_plan(api, deal["plan"]["id"]), PLAN_STATUS_DRAFT)


# ---------------------------------------------------------------------------
# Rank 19 — the safe harbour is inclusive on the passing side
# ---------------------------------------------------------------------------


def test_a_plan_landing_exactly_on_the_ninetieth_percentile_is_approved(api: ApiClient):
    """Exactly 90.00 is inside the harbour, so no justification is demanded.

    PRD: "The fair market value safe harbour is the ninetieth percentile, and
    exactly 90.00 is **inside** it. Only a `benchmark_percentile` strictly
    greater than 90.00 requires `fmv_justification_on_file` to be true; where the
    percentile is above the safe harbour and no justification is on file, the
    offending operation is rejected with `ERR_COMP_EXCEEDS_FMV_SAFE_HARBOR`."

    Design: Corner/validations/benchmark_percentile_of_exactly_ninety_satisfies_the_safe_harbor
    """
    deal = board_review_deal(api)
    plan = _salary_plan(
        api, deal["acquisition"]["id"], deal["physician"]["id"], SAFE_HARBOUR_TCC_CENTS
    )
    a.assert_percentage_equals(
        plan["benchmark_percentile"], SAFE_HARBOUR_PERCENTILE, "benchmark_percentile"
    )
    assert plan["benchmark_basis"] == BENCHMARK_BASIS_TOTAL_CASH_COMP
    assert plan["fmv_justification_on_file"] is False
    a.assert_status(submit_plan(api, plan["id"]), PLAN_STATUS_SUBMITTED)

    approved = approve_plan(api, plan["id"])

    a.assert_status(approved, PLAN_STATUS_APPROVED)
    assert approved["approved_by_user_id"] == USER_COMPLIANCE_OFFICER_ALT
    assert approved["fmv_justification_on_file"] is False
    physician = validate_success(api.get_physician(deal["physician"]["id"], DEAL_LEAD))
    assert physician["employment_status"] == EMPLOYMENT_OFFERED


def test_a_percentile_three_hundredths_higher_is_refused(api: ApiClient):
    """One thousand dollars more salary crosses the boundary and the rule bites.

    PRD: "**Fair market value safe harbour**, on `POST
    /compensation-plans/{planId}/status` with a target status of `APPROVED` or of
    `EXECUTED`. Otherwise `ERR_COMP_EXCEEDS_FMV_SAFE_HARBOR` (422)."

    Design: Corner/validations/benchmark_percentile_of_exactly_ninety_satisfies_the_safe_harbor
    """
    deal = board_review_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    physician_id = deal["physician"]["id"]
    at_the_harbour = _salary_plan(api, acquisition_id, physician_id, SAFE_HARBOUR_TCC_CENTS)
    above = _salary_plan(api, acquisition_id, physician_id, ABOVE_HARBOUR_TCC_CENTS)
    a.assert_percentage_equals(
        above["benchmark_percentile"], ABOVE_HARBOUR_PERCENTILE, "benchmark_percentile"
    )
    assert above["benchmark_basis"] == BENCHMARK_BASIS_TOTAL_CASH_COMP
    submit_plan(api, at_the_harbour["id"])
    submit_plan(api, above["id"])
    a.assert_status(approve_plan(api, at_the_harbour["id"]), PLAN_STATUS_APPROVED)

    rejected = _request_plan_status(
        api, above["id"], PLAN_STATUS_APPROVED, COMPLIANCE_OFFICER_ALT
    )

    validate_error(rejected, ApiErrorId.COMP_EXCEEDS_FMV_SAFE_HARBOR, 422)
    a.assert_status(_read_plan(api, above["id"]), PLAN_STATUS_SUBMITTED)
    assert above["fmv_justification_on_file"] is False


def test_a_written_justification_is_the_documented_escape(api: ApiClient):
    """The identical salary is approvable once the justification is on file.

    PRD: "`fmv_justification_on_file` states whether a written
    above-ninetieth-percentile fair market value justification exists, and
    defaults to false."

    Design: Corner/validations/benchmark_percentile_of_exactly_ninety_satisfies_the_safe_harbor
    """
    deal = board_review_deal(api)
    acquisition_id = deal["acquisition"]["id"]
    physician_id = deal["physician"]["id"]
    unjustified = _salary_plan(api, acquisition_id, physician_id, ABOVE_HARBOUR_TCC_CENTS)
    submit_plan(api, unjustified["id"])
    validate_error(
        _request_plan_status(api, unjustified["id"], PLAN_STATUS_APPROVED, COMPLIANCE_OFFICER_ALT),
        ApiErrorId.COMP_EXCEEDS_FMV_SAFE_HARBOR,
        422,
    )

    justified = _salary_plan(
        api,
        acquisition_id,
        physician_id,
        ABOVE_HARBOUR_TCC_CENTS,
        fmv_justification_on_file=True,
    )
    a.assert_percentage_equals(
        justified["benchmark_percentile"], ABOVE_HARBOUR_PERCENTILE, "benchmark_percentile"
    )
    submit_plan(api, justified["id"])
    approved = approve_plan(api, justified["id"])

    a.assert_status(approved, PLAN_STATUS_APPROVED)
    assert approved["fmv_justification_on_file"] is True
    assert approved["approved_by_user_id"] == USER_COMPLIANCE_OFFICER_ALT


# ---------------------------------------------------------------------------
# Rank 20 — a licence expiring exactly today is still current
# ---------------------------------------------------------------------------


def _deal_whose_licence_expires_today(api: ApiClient):
    reset_clock(api)
    return diligence_deal(
        api, physician_overrides={"state_license_expires_on": LICENCE_EXPIRES_TODAY}
    )


def test_a_licence_expiring_exactly_today_still_supports_a_submission(api: ApiClient):
    """The test is "not before" the current logical date, so today passes.

    PRD: "And the linked physician's `state_license_expires_on` must not be
    before the current logical date, or the rejection is
    `ERR_PHYSICIAN_LICENSE_EXPIRED`; a licence expiring exactly today is still
    valid."

    Design: Corner/validations/license_expiring_exactly_today_satisfies_the_license_rule
    """
    deal = _deal_whose_licence_expires_today(api)
    assert deal["physician"]["state_license_expires_on"] == LICENCE_EXPIRES_TODAY
    plan = _salary_plan(
        api, deal["acquisition"]["id"], deal["physician"]["id"], MEDIAN_TCC_CENTS
    )

    submitted = submit_plan(api, plan["id"])

    a.assert_status(submitted, PLAN_STATUS_SUBMITTED)
    a.assert_percentage_equals(
        submitted["benchmark_percentile"], MEDIAN_PERCENTILE, "benchmark_percentile"
    )
    assert submitted["benchmark_basis"] == BENCHMARK_BASIS_TOTAL_CASH_COMP


def test_the_licence_rule_is_evaluated_at_transition_time_only(api: ApiClient):
    """One day later a fresh submission fails while the earlier one is untouched.

    PRD: "**Physician licence currency**, on `POST
    /compensation-plans/{planId}/status` with a target status of `SUBMITTED` and
    on `POST /credentialing-packages/{packageId}/status` with a target status of
    `SUBMITTED`. Otherwise `ERR_PHYSICIAN_LICENSE_EXPIRED` (422)."

    Design: Corner/validations/license_expiring_exactly_today_satisfies_the_license_rule
    """
    deal = _deal_whose_licence_expires_today(api)
    acquisition_id = deal["acquisition"]["id"]
    physician_id = deal["physician"]["id"]
    first = _salary_plan(api, acquisition_id, physician_id, MEDIAN_TCC_CENTS)
    submit_plan(api, first["id"])

    park_clock_on_date(api, DAY_AFTER_THE_LICENCE_LAPSES)
    second = _salary_plan(api, acquisition_id, physician_id, MEDIAN_TCC_CENTS)
    rejected = _request_plan_status(api, second["id"], PLAN_STATUS_SUBMITTED, COMPENSATION_DESIGNER)

    validate_error(rejected, ApiErrorId.PHYSICIAN_LICENSE_EXPIRED, 422)
    a.assert_status(_read_plan(api, second["id"]), PLAN_STATUS_DRAFT)
    a.assert_status(_read_plan(api, first["id"]), PLAN_STATUS_SUBMITTED)
