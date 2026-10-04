"""Validation-rule corners: authentication, authorization, segregation of
duties, jurisdiction, objection window, supersede chain, and cell ranges
(PRD §2.1, §2.7, §3.3)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_cell_payload,
    create_filing_payload,
    get_success_data,
    make_admin_headers,
    make_actuary_headers,
    make_department,
    make_filed_filing,
    make_reviewed_filing,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    make_regulator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request arriving without a recognized `X-User-Role`, or
    without `X-User-ID`, is treated as an anonymous call and fails the first
    validation check with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_insurers(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_regulator_cannot_create_filings_unauthorized(api):
    """PRD §2.1: "A caller whose role is recognized but not permitted for the
    requested endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: "POST `/bureau/filings` | Create a loss cost filing (resubmission
    when superseding) | BureauAdmin".

    Design: Corner/validations/regulator_cannot_create_filings_unauthorized
    """
    dept = make_department()
    resp = api.create_filing(
        create_filing_payload(filing_code="LC-TX-CP-120", state_code="TX",
                              effective_date="2027-01-01T00:00:00Z"),
        make_regulator_headers(dept["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    rows, meta = validate_paginated(api.list_filings(ADMIN))
    assert rows == []


def test_segregation_of_duties_same_user_submit_and_complete_rejected(api):
    """PRD §3.3: "That recorded identity is the fulcrum of the bureau's
    segregation of duties: a `BureauActuary` completes the review, and the
    completing actuary's `X-User-ID` must differ from the administrator
    identity recorded at submit time. If they match, the completion is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."
    PRD §2.7: "**Segregation of duties** on review completion (see §3.3) —
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_same_user_submit_and_complete_rejected
    """
    filing = get_success_data(api.create_filing(
        create_filing_payload(effective_date="2027-01-01T00:00:00Z"), ADMIN
    ))
    api.create_cell(filing["id"], create_cell_payload(), ADMIN)
    admin_headers = make_admin_headers("admin-77")
    actuary_same_person = make_actuary_headers("admin-77")
    validate_success(api.submit_filing_review(filing["id"], admin_headers))
    resp = api.complete_filing_review(filing["id"], actuary_same_person)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    after = validate_success(api.get_filing(filing["id"], ADMIN))
    assert after["filing_status"] == "IN_ACTUARIAL_REVIEW"
    assert after["indicated_change_pct"] is None


def test_jurisdiction_mismatch_objection_rejected(api):
    """PRD §3.3: "jurisdiction first — the analyst's department `state_code`
    must equal the filing's `state_code`, else `ERR_JURISDICTION_MISMATCH` —
    then the window".
    PRD §2.7: "**Regulator jurisdiction** on objections —
    `ERR_JURISDICTION_MISMATCH`."

    Design: Corner/validations/jurisdiction_mismatch_objection_rejected
    """
    _dept_tx = make_department(state_code="TX")
    dept_ca = make_department(state_code="CA", objection_window_days=45,
                              max_lcm_deviation_pct=15)
    filing, _d = make_filed_filing(
        filing_overrides={"state_code": "TX", "effective_date": "2027-01-01T00:00:00Z"},
    )
    resp = api.raise_objection(
        filing["id"],
        {"department_id": dept_ca["id"], "objection_code": "R-CA",
         "objection_text": "Wrong state analyst"},
        make_regulator_headers(dept_ca["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_MISMATCH)
    after = validate_success(api.get_filing(filing["id"], ADMIN))
    assert after["filing_status"] == "FILED"
    rows, _meta = validate_paginated(api.list_filing_objections(filing["id"], ADMIN))
    assert rows == []


def test_objection_after_window_closed_rejected(api):
    """PRD §3.3: "the window — the logical clock must be no later than
    `filed_at` plus the department's `objection_window_days`, else
    `ERR_OBJECTION_WINDOW_CLOSED`."
    PRD §2.7: "**Objection window** temporal check —
    `ERR_OBJECTION_WINDOW_CLOSED`."

    Design: Corner/validations/objection_after_window_closed_rejected
    """
    filing, dept = make_filed_filing(
        filing_overrides={"effective_date": "2026-11-01T00:00:00Z"},
    )  # filed_at = 2026-09-01, window 30 days
    set_clock("2026-10-02T00:00:00Z")  # filed_at + 31 days
    resp = api.raise_objection(
        filing["id"],
        {"department_id": dept["id"], "objection_code": "R-LATE",
         "objection_text": "Too late"},
        make_regulator_headers(dept["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OBJECTION_WINDOW_CLOSED)
    after = validate_success(api.get_filing(filing["id"], ADMIN))
    assert after["filing_status"] == "FILED"


def test_resubmission_against_non_objected_filing_breaks_chain(api):
    """PRD §3.3: "the supersede chain check requires the named filing to
    currently be `OBJECTED` — otherwise `ERR_SUPERSEDE_CHAIN_BROKEN` — and the
    OCC rule of §2.8 applies via `expected_superseded_version`."
    PRD §2.7: "**Supersede chain integrity** — `ERR_SUPERSEDE_CHAIN_BROKEN`
    (HTTP 422)."

    Design: Corner/validations/resubmission_against_non_objected_filing_breaks_chain
    """
    filing, _dept = make_filed_filing(
        filing_overrides={"effective_date": "2027-01-01T00:00:00Z"},
    )  # FILED, not OBJECTED
    resp = api.create_filing(
        create_filing_payload(
            trend_selection="EXPONENTIAL_LEAST_SQUARES",
            effective_date="2027-03-01T00:00:00Z",
            supersedes_filing_id=filing["id"],
            expected_superseded_version=filing["version"],
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_SUPERSEDE_CHAIN_BROKEN)
    after = validate_success(api.get_filing(filing["id"], ADMIN))
    assert after["filing_status"] == "FILED"
    rows, meta = validate_paginated(
        api.list_filings(ADMIN, params={"filing_status": "DRAFT"})
    )
    assert rows == []


def test_cell_create_with_zero_earned_premium_rejected(api):
    """PRD §3.3: "Each cell names a `class_code` within the filing's line of
    business and carries the on-level `earned_premium_cents` for the
    experience period (strictly greater than 0), the developed
    `incurred_loss_cents` (zero or more), a `weight_pct` credibility weight in
    whole percent from 1 to 100, and the `current_loss_cost_cents` currently
    effective for that state, line, and class (strictly greater than 0)."
    PRD §3.3: "Out-of-range cell values are rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/cell_create_with_zero_earned_premium_rejected
    """
    filing = get_success_data(api.create_filing(
        create_filing_payload(effective_date="2027-01-01T00:00:00Z"), ADMIN
    ))
    resp = api.create_cell(
        filing["id"],
        create_cell_payload(earned_premium_cents=0),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api.list_cells(filing["id"], ADMIN))
    assert rows == []
