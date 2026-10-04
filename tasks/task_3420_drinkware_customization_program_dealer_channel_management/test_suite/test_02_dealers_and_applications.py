"""Dealer registration, listing, and the authorization fork-join (PRD 3.1)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    boot_clock,
    create_dealer,
    create_dealer_application_payload,
    create_open_application,
    decide_application,
    get_application,
    get_dealer,
    make_channel_manager_headers,
    record_inspection,
    schedule_inspection,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_documents,
    assert_dealer,
    assert_dealer_application,
    TEST_USERS,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_CM = TEST_USERS["channel_manager_headers"]


def test_dealer_create_defaults_applied_and_system_fields_ignored(api):
    """A dealer created with only the documented input fields starts PENDING
    with the PRD defaults; system-managed fields are server-owned.

    (Only PRD-declared input fields are sent: PRD section 2.5 defines id,
    created_at, updated_at, and version as system-managed, and PRD section 2.7
    does not mandate a verdict on undeclared extra fields, so none are sent.)

    PRD section 3.1: "the `tier` may be given as `STANDARD` or `PREMIER` and
    defaults to `STANDARD`, and the wholesale `credit_limit_cents` ceiling
    defaults to 500000 cents when omitted. A freshly registered dealer starts
    in `PENDING` status with `storefront_verified` false and a
    `brand_presentation_score` of 0, and it stays `PENDING` until an
    authorization application is approved."
    PRD section 2.2: "Unless otherwise noted, operations that create or modify
    a resource will return the created or updated resource object in the data
    field."

    Design: Corner/entities/dealer_create_with_status_input_ignored_and_defaults_applied
    """
    boot_clock()
    resp = api.create_dealer(
        {
            "legal_name": "Standard Dealer Co",
            "storefront_address": "10 Main St",
            "region_code": "TX-CT",
            "sell_through_pct": 50,
            "tenure_years": 5,
        },
        _ADMIN,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert "api_request_id" in body["meta"] and "api_request_timestamp" in body["meta"]

    data = validate_success(resp, 201)
    assert_dealer(data)
    assert data["status"] == "PENDING"
    assert data["tier"] == "STANDARD"
    assert data["credit_limit_cents"] == 500000
    assert data["storefront_verified"] is False
    assert data["brand_presentation_score"] == 0
    assert data["infraction_points"] == 0


def test_dealers_list_paginates_with_total_count_and_has_more(api):
    """limit/offset slice the dealer collection while total_count spans the
    whole filtered set.

    PRD section 2.3: "The `limit` parameter caps the number of items returned;
    it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items and defaults to 0."
    PRD section 2.3: "List responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/dealers_list_paginates_with_total_count_and_has_more
    """
    boot_clock()
    for i in (1, 2, 3):
        create_dealer(legal_name=f"Page {i}", tenure_years=i)

    page1, meta1 = validate_paginated(
        api.list_dealers(_CM, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3 and meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_dealers(_CM, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False

    all_rows, meta3 = validate_paginated(api.list_dealers(_CM))
    assert len(all_rows) == 3 and meta3["total_count"] == 3


def test_immediate_read_after_write_consistency(api):
    """The create response and the immediately following GET agree; a read is
    not a mutation, so version does not move between them.

    PRD section 2.5: "`version` (integer): starts low and increments by 1 on
    every mutation of the resource, including mutations caused by cascading
    side effects from operations on other resources."
    PRD section 2.5: "`updated_at` (string): an ISO 8601 UTC timestamp
    refreshed on every mutation."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    boot_clock()
    created = create_dealer(legal_name="Standard Dealer Co")
    read = get_dealer(created["id"])
    assert_dealer(read)
    assert read["legal_name"] == "Standard Dealer Co" == created["legal_name"]
    assert read["version"] == created["version"], \
        "a read performs no mutation, so the version must not advance"
    assert read["created_at"] and read["created_at"] == read["updated_at"], \
        "on a fresh entity created_at and updated_at stamp the same event"


def test_second_open_application_returns_409(api):
    """At most one open application per dealer.

    PRD section 3.1: "At most one application per dealer may be open — in
    `SUBMITTED` or `VETTING` — at a time; opening a second is rejected with
    `ERR_APPLICATION_ALREADY_OPEN`."

    Design: Corner/validations/second_open_application_returns_409
    """
    boot_clock()
    pair = create_open_application()
    dealer_id = pair["dealer"]["id"]

    resp = api.create_dealer_application(
        create_dealer_application_payload(
            dealer_id, storefront_sqft=900, document_refs=["doc-2nd"]),
        make_channel_manager_headers("cm-admin"),
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_ALREADY_OPEN)

    data, meta = validate_paginated(
        api.list_dealer_applications(_CM, params={"dealer_id": dealer_id}))
    assert len(data) == 1 and meta["total_count"] == 1


def test_dealer_application_fork_join_gate(api):
    """The decide join refuses APPROVE until both legs pass, in either leg
    order; the successful decide cascades the dealer to AUTHORIZED exactly
    once.

    PRD section 3.1: "The two legs advance independently; either may start
    first, and the decision is the join."
    PRD section 3.1: "An approval is refused until the join is satisfied: it
    requires `inspection_status` `PASSED` and `docs_status` `VERIFIED`, and
    attempting it earlier is rejected with `ERR_APPLICATION_INCOMPLETE`."
    PRD section 3.1: "When all of this holds, the application lands in
    `APPROVED` and the dealer cascades from `PENDING` to `AUTHORIZED`:
    `storefront_verified` becomes true, the application's
    `brand_presentation_score` is copied onto the dealer, and the dealer's
    `version` increments."

    Design: Difficulty/non_linear_state_machine/dealer_application_fork_join_gate
    """
    boot_clock()
    pair = create_open_application(
        dealer_overrides={"legal_name": "Fork Join Traders"})
    dealer, app = pair["dealer"], pair["application"]
    v_at_create = dealer["version"]

    # Join with both legs missing.
    resp1 = api.decide_application(
        app["id"], {"decision": "APPROVE", "decision_reason": "too early"},
        make_channel_manager_headers("cm-1"))
    validate_error(resp1, ApiErrorId.ERR_APPLICATION_INCOMPLETE)

    # Docs leg first: still refused — the inspection leg is missing.
    verify_documents(app["id"], reviewer_id="cm-docs")
    resp2 = api.decide_application(
        app["id"],
        {"decision": "APPROVE", "decision_reason": "docs done, inspection missing"},
        make_channel_manager_headers("cm-1"))
    validate_error(resp2, ApiErrorId.ERR_APPLICATION_INCOMPLETE)

    # Inspection leg completes; the join now passes.
    schedule_inspection(app["id"], inspector_id="fi-2")
    set_clock("2026-09-02T11:00:00Z")
    record_inspection(app["id"], inspector_id="fi-2",
                      outcome="PASSED", brand_presentation_score=85)
    decided = decide_application(app["id"], decider_id="cm-1", decision="APPROVE")
    assert_dealer_application(decided)
    assert decided["status"] == "APPROVED"
    assert decided["inspection_status"] == "PASSED"
    assert decided["docs_status"] == "VERIFIED"
    assert decided["brand_presentation_score"] == 85

    dealer_after = get_dealer(dealer["id"])
    assert dealer_after["status"] == "AUTHORIZED"
    assert dealer_after["storefront_verified"] is True
    assert dealer_after["brand_presentation_score"] == 85
    assert dealer_after["version"] == v_at_create + 1, \
        "exactly one cascade mutation on the dealer, not one per decide attempt"


def test_decide_sod_violation_same_docs_reviewer(api):
    """The ChannelManager who verified the documents cannot also decide; a
    different ChannelManager decides the same application successfully.

    PRD section 3.1: "Segregation of duties is enforced at the join: the
    deciding `X-User-ID` must differ from both `inspection_recorded_by` and
    `docs_reviewed_by`, otherwise the decision is rejected with
    `ERR_SOD_VIOLATION`."

    Design: Corner/validations/decide_sod_violation_same_docs_reviewer
    """
    boot_clock()
    pair = create_open_application()
    dealer, app = pair["dealer"], pair["application"]
    schedule_inspection(app["id"], inspector_id="fi-1")
    set_clock("2026-09-02T11:00:00Z")
    record_inspection(app["id"], inspector_id="fi-1",
                      outcome="PASSED", brand_presentation_score=85)
    verify_documents(app["id"], reviewer_id="cm-sod")

    resp = api.decide_application(
        app["id"], {"decision": "APPROVE", "decision_reason": "self-review"},
        make_channel_manager_headers("cm-sod"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
    assert get_application(app["id"])["status"] == "VETTING", \
        "the rejected decide leaves the application mid-join"

    decided = decide_application(app["id"], decider_id="cm-1", decision="APPROVE")
    assert decided["status"] == "APPROVED"
    assert get_dealer(dealer["id"])["status"] == "AUTHORIZED"


def test_approve_without_storefront_returns_storefront_required(api):
    """Strong legs cannot waive the physical-storefront requirement.

    PRD section 3.1: "Beyond the join, approval demands that
    `has_physical_storefront` be true — authorization is impossible without a
    brick-and-mortar location, failing with `ERR_STOREFRONT_REQUIRED`"

    Design: Corner/validations/approve_without_storefront_returns_storefront_required
    """
    boot_clock()
    pair = create_open_application(
        has_physical_storefront=False, storefront_sqft=1)
    dealer, app = pair["dealer"], pair["application"]
    schedule_inspection(app["id"], inspector_id="fi-1")
    set_clock("2026-09-02T11:00:00Z")
    record_inspection(app["id"], inspector_id="fi-1",
                      outcome="PASSED", brand_presentation_score=95)
    verify_documents(app["id"], reviewer_id="cm-docs")

    resp = api.decide_application(
        app["id"], {"decision": "APPROVE", "decision_reason": "online-only applicant"},
        make_channel_manager_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_STOREFRONT_REQUIRED)
    assert get_application(app["id"])["status"] == "VETTING"
    assert get_dealer(dealer["id"])["status"] == "PENDING"


def test_approve_with_brand_score_69_returns_below_threshold(api):
    """The brand-presentation bar is at least 70; a PASSED inspection scoring
    69 still fails the join.

    PRD section 3.1: "and that the recorded `brand_presentation_score` be at
    least 70, failing with `ERR_BRAND_STANDARD_BELOW_THRESHOLD`."

    Design: Corner/validations/approve_with_brand_score_69_returns_below_threshold
    """
    boot_clock()
    pair = create_open_application()
    dealer, app = pair["dealer"], pair["application"]
    schedule_inspection(app["id"], inspector_id="fi-1")
    set_clock("2026-09-02T11:00:00Z")
    record_inspection(app["id"], inspector_id="fi-1",
                      outcome="PASSED", brand_presentation_score=69)
    verify_documents(app["id"], reviewer_id="cm-docs")

    resp = api.decide_application(
        app["id"], {"decision": "APPROVE", "decision_reason": "close enough?"},
        make_channel_manager_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_BRAND_STANDARD_BELOW_THRESHOLD)
    dealer_after = get_dealer(dealer["id"])
    assert dealer_after["status"] == "PENDING"
    assert dealer_after["brand_presentation_score"] == 0, "no partial cascade"
