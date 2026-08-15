"""Compliance filings: true-up reconciliation, de-minimis threshold, remand and
supersede chains, docket close, and OCC on filing creation (PRD §2.8, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_version_incremented,
    create_compliance_filing_payload,
    create_filing,
    get_case,
    get_filing,
    setup_compliance_both_classes,
    setup_compliance_res_only,
    submit_compliance_filing,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

UF = TEST_USERS["utility_filer_alice"]
STAFF = TEST_USERS["commission_staff"]
ALJ = TEST_USERS["alj"]

ACTUALS_OVER = [
    {"class_code": "RESIDENTIAL", "actual_revenue_cents": 1210000000},
    {"class_code": "COMMERCIAL", "actual_revenue_cents": 660000000},
]
ACTUALS_AT_THRESHOLD = [
    {"class_code": "RESIDENTIAL", "actual_revenue_cents": 1200000000},
    {"class_code": "COMMERCIAL", "actual_revenue_cents": 659250000},
]
ACTUALS_ONE_OVER = [
    {"class_code": "RESIDENTIAL", "actual_revenue_cents": 1200000000},
    {"class_code": "COMMERCIAL", "actual_revenue_cents": 659250001},
]
ACTUALS_EXACT_RES = [{"class_code": "RESIDENTIAL", "actual_revenue_cents": 1850000000}]


# ─── Difficulty: combinatorial_formula / true_up evaluation order ────────────

def test_true_up_delta_and_action_refund(api):
    """PRD §3.8: "First, `actual_total` is the sum of `actual_revenue_cents`
    across `actual_revenue_by_class`. Second, `true_up_delta_cents` is
    `actual_total` minus the case's `authorized_revenue_requirement_cents`; a
    positive delta is over-collection (a refund owed to customers), a negative
    delta is under-collection (a surcharge owed to the utility)." and "otherwise
    `REFUND` when the delta is positive and `SURCHARGE` when it is negative."

    Design: Difficulty/combinatorial_formula/true_up_evaluation_order_breaks_circularity
    """
    s = setup_compliance_both_classes()
    f1 = create_filing(s.case["id"], ACTUALS_OVER)
    submitted = validate_success(api.submit_compliance_filing(f1["id"], UF), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["actual_total_revenue_cents"] == 1870000000
    assert submitted["true_up_delta_cents"] == 20000000, (
        "over-collection vs authorized 1,850,000,000"
    )
    # threshold = max(100000, round(1,850,000,000*0.005)) = 9,250,000; 20,000,000
    # is strictly greater, so the trigger fires.
    assert submitted["true_up_action"] == "REFUND"


def test_true_up_class_lines_rounding_and_residual(api):
    """PRD §3.8: "Fifth, per-class true-up lines are computed even when the
    action is `NONE`, for transparency: each line is the round-half-away-from-zero
    of the delta times that class's `actual_revenue_cents` divided by
    `actual_total`, and the residual — the delta minus the sum of lines — is
    assigned to the class with the largest `actual_revenue_cents`, ties broken by
    `class_code` ascending. These lines are stored as `class_true_up_lines`, an
    array of objects each with `class_code` and `line_cents`."

    Design: Difficulty/combinatorial_formula/true_up_evaluation_order_breaks_circularity
    """
    s = setup_compliance_both_classes()
    f1 = create_filing(s.case["id"], ACTUALS_OVER)
    submitted = validate_success(api.submit_compliance_filing(f1["id"], UF), 200)
    lines = {l["class_code"]: l["line_cents"] for l in submitted["class_true_up_lines"]}
    assert lines == {"RESIDENTIAL": 12941176, "COMMERCIAL": 7058824}, (
        "round_half_away_from_zero(20,000,000 * share); residual 20,000,000 - "
        "20,000,000 == 0"
    )
    assert sum(lines.values()) == submitted["true_up_delta_cents"]


# ─── Difficulty: boundary_precision / true_up de-minimis ─────────────────────

def test_true_up_exact_threshold_is_none(api):
    """PRD §3.8: "Third, the de-minimis threshold is the larger of 100000 cents
    and the round-half-up of the authorized revenue requirement times 0.005.
    Fourth, `true_up_action` is `NONE` when the absolute value of the delta is
    less than or equal to the threshold — a delta exactly equal to the threshold
    is `NONE`, since the trigger is strictly-greater"

    Design: Difficulty/boundary_precision_check/true_up_de_minimis_exact_threshold
    """
    s = setup_compliance_both_classes()
    f1 = create_filing(s.case["id"], ACTUALS_AT_THRESHOLD)
    submitted = validate_success(api.submit_compliance_filing(f1["id"], UF), 200)
    assert submitted["actual_total_revenue_cents"] == 1859250000
    assert submitted["true_up_delta_cents"] == 9250000, (
        "== threshold max(100,000, round(1,850,000,000*0.005))"
    )
    assert submitted["true_up_action"] == "NONE", (
        "strictly-greater trigger does not fire at exact equality"
    )
    assert submitted["status"] == "SUBMITTED"


def test_true_up_one_cent_over_threshold_is_refund(api):
    """PRD §3.8: "a delta exactly equal to the threshold is `NONE`, since the
    trigger is strictly-greater — otherwise `REFUND` when the delta is positive
    and `SURCHARGE` when it is negative."

    Design: Difficulty/boundary_precision_check/true_up_de_minimis_exact_threshold
    """
    s = setup_compliance_both_classes()
    f1 = create_filing(s.case["id"], ACTUALS_ONE_OVER)
    submitted = validate_success(api.submit_compliance_filing(f1["id"], UF), 200)
    assert submitted["true_up_delta_cents"] == 9250001
    assert submitted["true_up_action"] == "REFUND", "one cent over the threshold flips it"


# ─── Corner: remand / supersede / state guards ───────────────────────────────

def test_remand_review_requires_notes_and_supersede_chain(api):
    """PRD §3.8: "`REMAND` moves it to `REMANDED` and requires a non-empty
    `remand_notes` — otherwise `ERR_REMAND_NOTES_REQUIRED`." and "The new filing
    supersedes the case's existing filing in `DRAFT` or `REMANDED` (the superseded
    filing moves to `SUPERSEDED` and the new filing's `supersedes_filing_id` is
    set to the superseded filing's `id`; null for the case's first filing)"

    Design: Corner/state_machines/remand_review_requires_notes_and_supersede_chain
    """
    s = setup_compliance_res_only()
    f1 = create_filing(s.case["id"], ACTUALS_EXACT_RES)
    submit_compliance_filing(f1["id"])
    res = api.review_compliance_filing(f1["id"], {"outcome": "REMAND"}, STAFF)
    validate_error(res, ApiErrorId.ERR_REMAND_NOTES_REQUIRED, expected_status=400)
    assert get_filing(f1["id"])["status"] == "SUBMITTED"
    remanded = validate_success(api.review_compliance_filing(
        f1["id"], {"outcome": "REMAND",
                   "remand_notes": "Actual revenue lacks billing-determinant support"},
        STAFF), 200)
    assert remanded["status"] == "REMANDED"
    f1_after = get_filing(f1["id"])
    assert f1_after["true_up_action"] == "NONE"
    assert f1_after["true_up_delta_cents"] == 0, "computed at submit, frozen"
    f2 = create_filing(s.case["id"], ACTUALS_EXACT_RES, period_label="RATE_YEAR_1_REV")
    assert f2["status"] == "DRAFT"
    assert f2["supersedes_filing_id"] == f1["id"]
    assert get_filing(f1["id"])["status"] == "SUPERSEDED"


def test_filing_submit_twice_and_double_review_rejected(api):
    """PRD §3.8: "Submitting a `DRAFT` filing (case must be in
    `COMPLIANCE_MONITORING`, otherwise `ERR_INVALID_CASE_STATE`; filing not in
    `DRAFT` is `ERR_INVALID_FILING_STATE`) freezes the true-up computation." and
    "`ACCEPT` moves it to `ACCEPTED`" and "`ACCEPTED` and `SUPERSEDED` are
    terminal."

    Design: Corner/state_machines/filing_submit_twice_and_double_review_rejected
    """
    s = setup_compliance_res_only()
    f1 = create_filing(s.case["id"], ACTUALS_EXACT_RES)
    submit_compliance_filing(f1["id"])
    res1 = api.submit_compliance_filing(f1["id"], UF)
    validate_error(res1, ApiErrorId.ERR_INVALID_FILING_STATE, expected_status=409)
    accepted = validate_success(api.review_compliance_filing(
        f1["id"], {"outcome": "ACCEPT"}, STAFF), 200)
    assert accepted["status"] == "ACCEPTED"
    res2 = api.review_compliance_filing(f1["id"], {"outcome": "ACCEPT"}, STAFF)
    validate_error(res2, ApiErrorId.ERR_INVALID_FILING_STATE, expected_status=409)


def test_close_requires_accepted_filing(api):
    """PRD §3.8: "The ALJ closes the docket from `COMPLIANCE_MONITORING` once at
    least one ComplianceFiling of the case is `ACCEPTED` — otherwise
    `ERR_NO_ACCEPTED_FILING` — moving the case to `CLOSED`, its terminal state."

    Design: Corner/state_machines/close_requires_accepted_filing
    """
    s = setup_compliance_res_only()
    res = api.close_case(s.case["id"], ALJ)
    validate_error(res, ApiErrorId.ERR_NO_ACCEPTED_FILING, expected_status=409)
    f1 = create_filing(s.case["id"], ACTUALS_EXACT_RES)
    submit_compliance_filing(f1["id"])
    validate_success(api.review_compliance_filing(f1["id"], {"outcome": "ACCEPT"}, STAFF), 200)
    closed = validate_success(api.close_case(s.case["id"], ALJ), 200)
    assert closed["status"] == "CLOSED"


def test_submitted_filing_blocks_new_filing(api):
    """PRD §3.8: "an existing filing in `SUBMITTED` or `ACCEPTED` blocks the new
    filing with `ERR_FILING_NOT_SUPERSEDABLE`."

    Design: Corner/validations/submitted_filing_blocks_new_filing
    """
    s = setup_compliance_res_only()
    f1 = create_filing(s.case["id"], ACTUALS_EXACT_RES)
    submit_compliance_filing(f1["id"])
    version = get_case(s.case["id"])["version"]
    res = api.create_compliance_filing(
        create_compliance_filing_payload(
            s.case["id"], version, period_label="RATE_YEAR_1_REV",
            actual_revenue_by_class=ACTUALS_EXACT_RES), UF)
    validate_error(res, ApiErrorId.ERR_FILING_NOT_SUPERSEDABLE, expected_status=409)
    assert get_filing(f1["id"])["status"] == "SUBMITTED", "unchanged"


def test_incomplete_class_revenue_rejected(api):
    """PRD §3.8: "`actual_revenue_by_class` (an array of per-class actuals, each
    with `class_code` and `actual_revenue_cents`, covering every CustomerClass of
    the case exactly once — otherwise `ERR_INCOMPLETE_CLASS_REVENUE`)"

    Design: Corner/validations/incomplete_class_revenue_rejected
    """
    s = setup_compliance_res_only()
    version = get_case(s.case["id"])["version"]
    res = api.create_compliance_filing(
        create_compliance_filing_payload(
            s.case["id"], version,
            actual_revenue_by_class=[
                {"class_code": "PHANTOM_CLASS", "actual_revenue_cents": 1850000000},
            ]), UF)
    validate_error(res, ApiErrorId.ERR_INCOMPLETE_CLASS_REVENUE, expected_status=422)
    data, meta = validate_paginated(api.list_compliance_filings(
        UF, params={"rate_case_id": s.case["id"]}))
    assert meta["total_count"] == 0, "no filing persisted"


def test_occ_stale_version_compliance_filing_rejected(api):
    """PRD §2.8: "Two create-with-supersede endpoints take a non-optional
    `expected_rate_case_version` input field that carries the client's last
    observed `version` of the parent RateCase: settlement-round creation and
    compliance-filing creation. If `expected_rate_case_version` does not equal
    the case's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)"
    PRD §3.8: "The new filing supersedes the case's existing filing in `DRAFT` or
    `REMANDED` (the superseded filing moves to `SUPERSEDED` and the new filing's
    `supersedes_filing_id` is set to the superseded filing's `id`; null for the
    case's first filing)"

    Design: Corner/complexity_layers/occ_stale_version_compliance_filing_rejected
    """
    s = setup_compliance_res_only()
    v2 = get_case(s.case["id"])["version"]
    f1 = validate_success(api.create_compliance_filing(
        create_compliance_filing_payload(s.case["id"], v2,
                                         actual_revenue_by_class=ACTUALS_EXACT_RES),
        UF), 201)
    assert f1["status"] == "DRAFT"
    assert f1.get("supersedes_filing_id") is None, "null for the case's first filing"
    res = api.create_compliance_filing(
        create_compliance_filing_payload(
            s.case["id"], v2, period_label="RATE_YEAR_1_REV",
            actual_revenue_by_class=ACTUALS_EXACT_RES), UF)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    v3 = get_case(s.case["id"])["version"]
    assert_version_incremented(v3, v2)
    f2 = validate_success(api.create_compliance_filing(
        create_compliance_filing_payload(
            s.case["id"], v3, period_label="RATE_YEAR_1_REV",
            actual_revenue_by_class=ACTUALS_EXACT_RES), UF), 201)
    assert f2["supersedes_filing_id"] == f1["id"]
    assert get_filing(f1["id"])["status"] == "SUPERSEDED"
