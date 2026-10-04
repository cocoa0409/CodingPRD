"""Optimistic concurrency, RBAC denials, segregation of duties and malformed bodies."""
from test_helpers import (
    ANY,
    ApiErrorId,
    broker_version,
    get_broker,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CM,
    create_and_approve_broker,
    open_qc_review,
    price_quote,
    publish_rate_sheet,
    record_decision,
    set_clock,
    setup_full_scenario,
    setup_funded_loan,
    setup_loan_in_state,
    underwrite_loan,
)
from test_helpers.test_users import (
    NAMED_QC_ANALYST_ID,
    NAMED_UNDERWRITER_ID,
    TEST_USERS,
    anonymous_headers,
    make_broker_headers,
    make_channel_manager_headers,
    make_compliance_officer_headers,
    make_qc_analyst_headers,
    make_underwriter_headers,
)

STANDARD_TABLE = [
    {"dim": "credit", "bucket": "760-plus", "adjust_pct": -0.125},
    {"dim": "ltv", "bucket": "up-to-60", "adjust_pct": 0.000},
    {"dim": "occupancy", "bucket": "PRIMARY_RESIDENCE", "adjust_pct": 0.000},
    {"dim": "product", "bucket": "CONVENTIONAL", "adjust_pct": 0.000},
]


def test_stale_broker_version_on_underwrite_is_rejected_with_412(api):
    """PRD §2.7: "the request must carry `expected_broker_version` matching the target
    `Broker`'s current `version`. If the broker's version has advanced since the client last
    read it, the write is refused with `ERR_STALE_VERSION` and a `412 Precondition Failed`
    status."
    PRD §2.7: "`Broker.version` legitimately advances on every licence revocation"

    Design: Difficulty/cross_entity_state_dependency/loan_underwriting_requires_broker_approved_and_not_blocked
    """
    scenario = setup_loan_in_state("UNDERWRITING", state_code="CA")
    b = scenario["broker_id"]
    stale_version = broker_version(b)

    set_clock("2026-10-05T00:00:00Z")
    validate_success(
        api_client.revoke_license(b, scenario["license"]["id"], make_compliance_officer_headers())
    )
    set_clock("2026-09-01T00:00:00Z")

    live_version = broker_version(b)
    assert live_version != stale_version

    response = api_client.underwrite_loan(
        scenario["loan_id"], {"expected_broker_version": stale_version}, make_underwriter_headers()
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_a_fresh_broker_version_lets_the_underwrite_through(api):
    """PRD §2.7: "Three write operations are guarded against stale reads, and each names the
    version field it expects in the request body rather than its own resource version."
    PRD §3.7: "the call must carry `expected_broker_version`"

    Design: Difficulty/cross_entity_state_dependency/loan_underwriting_requires_broker_approved_and_not_blocked
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]

    accepted = underwrite_loan(scenario["loan_id"], broker_version(b))
    assert accepted["status"] == "UNDERWRITING"
    assert accepted["underwriting_due_at"] is not None


def test_advanced_broker_version_still_answers_412_on_underwrite(api):
    """PRD §2.7: "If the broker's version has advanced since the client last read it, the write
    is refused with `ERR_STALE_VERSION` and a `412 Precondition Failed` status."
    PRD §2.11: "then the version-freshness guards, then the state preconditions of the target
    resource"

    Design: Corner/cross_cutting_complexity_layers/stale_broker_version_on_underwrite_is_rejected_with_412
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]
    stale_version = broker_version(b)

    # Registering an exclusivity policy recomputes exclusivity_status and bumps the
    # broker's version (PRD §3.4) without touching the loan's own status.
    validate_success(
        api_client.create_exclusivity_policy(
            {
                "broker_id": b,
                "competitor_identifier": "COMP-OMEGA",
                "competitor_name": "Omega Home Lending",
                "effective_from": "2026-09-01T00:00:00Z",
                "effective_to": "2026-12-01T00:00:00Z",
                "status": "ACTIVE",
                "restriction_scope": "LOAN_SUBMISSION",
            },
            make_channel_manager_headers(),
        ),
        expected_status=201,
    )

    broker = get_broker(b)
    assert broker["version"] != stale_version
    assert broker["status"] == "APPROVED"

    response = api_client.underwrite_loan(
        scenario["loan_id"], {"expected_broker_version": stale_version}, make_underwriter_headers()
    )
    # The version guard precedes the target's state precondition (PRD §2.11), so a
    # stale pin is refused on freshness alone and the loan is never advanced.
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert validate_success(api_client.get_loan_submission(scenario["loan_id"], ANY))["status"] == "SUBMITTED"


def test_underwriter_cannot_resolve_a_turn_time_escalation(api):
    """PRD §2.1: "A caller whose role is not permitted for the endpoint being invoked is refused
    with `ERR_INSUFFICIENT_PERMISSIONS` and a `403 Forbidden` status."
    PRD §2.1: "`Underwriter` owns the underwriting and closing decision surface on submitted
    loans"

    Design: Corner/rbac/underwriter_cannot_resolve_turn_time_escalations
    """
    scenario = setup_loan_in_state("UNDERWRITING")
    loan_id = scenario["loan_id"]
    set_clock("2026-09-20T00:00:00Z")
    escalations = validate_success(api_client.list_loan_escalations(loan_id, ANY))
    assert len(escalations) == 1

    response = api_client.resolve_escalation(
        escalations[0]["id"],
        {"resolution_note": "underwriter attempting to resolve"},
        make_underwriter_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    still = validate_success(api_client.list_loan_escalations(loan_id, ANY))
    assert still[0]["status"] == "OPEN"


def test_analyst_cannot_underwrite_and_manager_cannot_review_quality(api):
    """PRD §2.1: "`Underwriter` owns the underwriting and closing decision surface on submitted
    loans and may not price, elect compensation, or review quality."
    PRD §2.1: "`QualityControlAnalyst` performs post-funding file review, defect resolution and
    repurchase exercise, and must not also be the loan's underwriter."

    Design: Corner/rbac/analyst_cannot_underwrite_and_channel_manager_cannot_review_quality
    """
    scenario = setup_full_scenario()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]

    analyst_attempt = api_client.underwrite_loan(
        loan_id, {"expected_broker_version": broker_version(b)},
        make_qc_analyst_headers(NAMED_QC_ANALYST_ID),
    )
    validate_error(analyst_attempt, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    manager_attempt = api_client.create_quality_control_review(
        {"loan_submission_id": loan_id, "defect_type": "NON_DEFECT",
         "severity": "MINOR", "remediation_status": "NONE"},
        make_channel_manager_headers(),
    )
    validate_error(manager_attempt, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)

    assert validate_success(api_client.get_loan_submission(loan_id, ANY))["status"] == "SUBMITTED"
    reviews, meta = validate_paginated(
        api_client.list_loan_quality_control_reviews(loan_id, ANY)
    )
    assert reviews == [] and meta["total_count"] == 0


def test_segregation_of_duties_blocks_self_review_of_the_underwriter(api):
    """PRD §2.1: "the reviewer of a loan's post-funding quality review must not be the
    underwriter named on that loan's most recent final `UnderwritingDecision`. A violation of
    that rule is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` and a `403 Forbidden` status."

    Design: Corner/rbac/segregation_of_duties_blocks_self_review_of_own_decision
    """
    scenario = setup_funded_loan()
    loan_id = scenario["loan_id"]

    self_review = api_client.create_quality_control_review(
        {"loan_submission_id": loan_id, "defect_type": "NON_DEFECT",
         "severity": "MINOR", "remediation_status": "NONE"},
        make_qc_analyst_headers(NAMED_UNDERWRITER_ID),
    )
    validate_error(self_review, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION, expected_status=403)

    review = validate_success(
        api_client.create_quality_control_review(
            {"loan_submission_id": loan_id, "defect_type": "NON_DEFECT",
             "severity": "MINOR", "remediation_status": "NONE"},
            make_qc_analyst_headers(NAMED_QC_ANALYST_ID),
        ),
        expected_status=201,
    )
    assert review["outcome"] == "CLEAR"

    rows, meta = validate_paginated(api_client.list_loan_quality_control_reviews(loan_id, ANY))
    assert len(rows) == 1 and meta["total_count"] == 1


def test_read_endpoints_admit_any_role_with_no_ownership_filter(api):
    """PRD §2.1: "`Any` designates any authenticated caller and appears only on read endpoints,
    which apply no ownership filter."
    PRD §2.1: "If either header is absent, or if `X-User-Role` names a role that the system does
    not declare, the request is refused with `ERR_MISSING_USER_CONTEXT` and a `400 Bad Request`
    status."

    Design: Corner/rbac/any_role_can_read_but_no_role_can_read_without_context
    """
    scenario = setup_full_scenario()
    b = scenario["broker_id"]
    from test_helpers.fixtures import create_submitted_broker

    second = create_submitted_broker(
        legal_name="Second Readonly Brokers LLC", nmls_id="NMLS-3325936", home_state="NV",
        volume_expectation_cents=50_000_000,
    )

    foreign, meta = validate_paginated(
        api_client.list_loan_submissions(TEST_USERS["any_headers"], {"broker_id": second["id"]})
    )
    assert foreign == [] and meta["total_count"] == 0

    own, meta_own = validate_paginated(
        api_client.list_loan_submissions(TEST_USERS["any_headers"], {"broker_id": b})
    )
    assert len(own) == 1 and meta_own["total_count"] == 1

    headerless = api_client.list_loan_submissions(anonymous_headers())
    validate_error(headerless, ApiErrorId.ERR_MISSING_USER_CONTEXT, expected_status=400)


def test_quality_review_list_pages_and_filters_together(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in the
    `meta` object of the envelope."
    PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10, has a
    minimum of 1, and has a maximum of 100."

    Design: Corner/cross_cutting_complexity_layers/pagination_with_filtering_and_has_more_on_quality_reviews
    """
    scenario = setup_funded_loan()
    loan_id = scenario["loan_id"]
    b = scenario["broker_id"]
    open_qc_review(loan_id, "NON_DEFECT", "MINOR", "NONE", reviewer_id=NAMED_QC_ANALYST_ID)

    filtered, meta_filtered = validate_paginated(
        api_client.list_broker_quality_control_reviews(b, ANY, {"outcome": "CLEAR", "limit": 1, "offset": 0})
    )
    assert len(filtered) == 1
    assert meta_filtered["total_count"] == 1
    assert meta_filtered["has_more"] is False

    unfiltered, meta_unfiltered = validate_paginated(
        api_client.list_broker_quality_control_reviews(b, ANY, {"limit": 1, "offset": 0})
    )
    assert len(unfiltered) == 1
    assert meta_unfiltered["total_count"] == 1
    assert meta_unfiltered["has_more"] is False

    defaulted, meta_default = validate_paginated(
        api_client.list_broker_quality_control_reviews(b, ANY)
    )
    assert len(defaulted) == 1
    assert meta_default["limit"] == 10

    assert filtered[0]["outcome"] == "CLEAR"
    assert filtered[0]["remediation_status"] == "NONE"


def test_out_of_enum_occupancy_type_answers_invalid_request(api):
    """PRD §2.11: "a defect review created with `remediation_status` `OPEN`, an unknown enum
    member and a missing required field all travel through `ERR_INVALID_REQUEST`."
    PRD §3.5: "`occupancy_type` of `PRIMARY_RESIDENCE`, `SECOND_HOME` or `INVESTMENT`"

    Design: Corner/validations/malformed_body_enum_outranks_every_business_check
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=STANDARD_TABLE)

    response = api_client.create_pricing_quote(
        sheet["id"],
        {
            "representative_fico": 780, "ltv_ratio": 0.5500,
            "occupancy_type": "VACATION_HOME", "loan_amount_cents": 40_000_000,
            "lock_period_days": 30, "loan_purpose": "PURCHASE",
            "expected_rate_sheet_version": sheet["version"],
        },
        make_broker_headers(broker["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    quotes, meta = validate_paginated(api_client.list_sheet_pricing_quotes(sheet["id"], ANY))
    assert quotes == [] and meta["total_count"] == 0
    assert validate_success(api_client.get_rate_sheet(sheet["id"], ANY))["status"] == "PUBLISHED"