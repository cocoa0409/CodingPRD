"""Corner queue — entities: creation defaults, computed territory/tier
assignment, creation-time rejections, and listing/404 surface (PRD §3.1,
§2.2, §2.3, §2.6)."""

from test_helpers import (
    CLOCK_START_ISO,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_bureau,
    assert_business,
    assert_complaint,
    create_bureau,
    create_bureau_payload,
    create_business,
    create_business_payload,
    create_consumer,
    file_and_forward_complaint,
    file_complaint,
    parse_iso,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def test_bureau_create_applies_defaults_and_returns_envelope(api):
    """PRD §3.1: "A `BureauAdmin` creates a bureau with a display `name`, a
    set of `territory_state_codes` (the two-letter US state codes the bureau
    serves), and an optional `local_dues_fee_cents` — a flat bureau-local fee
    added to accreditation dues, defaulting to 0 when omitted and never
    negative (`ERR_INVALID_REQUEST`)."
    PRD §2.4: "At startup, before any clock operation has been issued, the
    logical clock reads exactly 2026-09-01T00:00:00Z, and it never falls back
    to the host's wall clock."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."

    Design: Corner/entities/bureau_create_applies_defaults_and_returns_envelope
    """
    # No clock call: the pinned startup default stamps created_at.
    resp = api.create_bureau(
        create_bureau_payload(name="Heartland Bureau",
                              territory_state_codes=["IA", "NE"],
                              local_dues_fee_cents=None),  # omit -> default 0
        ADMIN)
    data = validate_success(resp, 201)
    assert_bureau(data)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert data["local_dues_fee_cents"] == 0
    assert data["dues_collected_cents"] == 0
    assert data["ops_day_index"] == 0
    assert parse_iso(data["created_at"]) == parse_iso(CLOCK_START_ISO)


def test_business_create_computes_territory_and_size_tier(api):
    """PRD §3.1: "First, `bureau_id` is assigned to the unique bureau whose
    `territory_state_codes` contains the business's home state; because state
    codes never overlap between bureaus there is at most one candidate and no
    ranking or tie-break is needed, and when no bureau covers the state the
    creation is rejected with `ERR_TERRITORY_UNCOVERED` (HTTP 422)."
    PRD §3.1: "Second, `size_tier` is computed from headcount: `MICRO` for 1
    to 4 employees, `SMALL` for 5 to 19 employees, `MEDIUM` for 20 to 99
    employees, and `LARGE` for 100 or more employees."
    PRD §3.1: "A newly created business carries `accreditation_status`
    `NOT_ACCREDITED` and `advertising_compliance_status` `CLEAR`."

    Design: Corner/entities/business_create_computes_territory_and_size_tier
    """
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Prairie Bureau",
                           territory_state_codes=["KS", "MO"],
                           local_dues_fee_cents=0)
    resp = api.create_business(
        create_business_payload(legal_name="Kansas Plains LLC",
                                home_state_code="KS", employee_count=50,
                                founded_on="2020-01-01T00:00:00Z"), ADMIN)
    data = validate_success(resp, 201)
    assert_business(data)
    assert data["bureau_id"] == bureau["id"]
    assert data["size_tier"] == "MEDIUM"  # 50 employees is within 20-99
    assert data["accreditation_status"] == "NOT_ACCREDITED"
    assert data["advertising_compliance_status"] == "CLEAR"
    for counter in ("complaints_received_36m", "complaints_unanswered_36m",
                    "complaints_unresolved_36m", "complaints_open_count",
                    "complaints_closed_count", "published_scam_count_12m"):
        assert data[counter] == 0, counter
    assert data["current_published_score"] is None
    assert data["current_published_grade"] is None


def test_business_create_with_uncovered_state_returns_territory_uncovered(
        api):
    """PRD §3.1: "when no bureau covers the state the creation is rejected
    with `ERR_TERRITORY_UNCOVERED` (HTTP 422)."

    Design: Corner/entities/business_create_with_uncovered_state_returns_territory_uncovered
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    resp = api.create_business(
        create_business_payload(legal_name="Texas Outsider LLC",
                                home_state_code="TX", employee_count=5,
                                founded_on="2020-01-01T00:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_TERRITORY_UNCOVERED)
    rows, meta = validate_paginated(api.list_businesses(
        ADMIN, params={"home_state_code": "TX"}))
    assert rows == [] and meta["total_count"] == 0, \
        "no business row may persist after a rejected creation"


def test_bureau_create_with_duplicate_state_returns_state_already_assigned(
        api):
    """PRD §3.1: "Territories are exclusive across the whole system: each
    state code may appear in at most one bureau, and creating a bureau that
    claims a state code already assigned elsewhere is rejected with
    `ERR_STATE_ALREADY_ASSIGNED`."

    Design: Corner/entities/bureau_create_with_duplicate_state_returns_state_already_assigned
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    resp = api.create_bureau(
        create_bureau_payload(name="Overlapping Bureau",
                              territory_state_codes=["NE", "SD"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STATE_ALREADY_ASSIGNED)
    # The rejected bureau claimed nothing: SD remains uncovered.
    resp = api.create_business(
        create_business_payload(legal_name="Dakota LLC", home_state_code="SD",
                                employee_count=5,
                                founded_on="2020-01-01T00:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_TERRITORY_UNCOVERED)


def test_consumer_create_rejects_duplicate_email(api):
    """PRD §3.1: "Email addresses are unique across consumers; registering a
    duplicate is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/consumer_create_rejects_duplicate_email
    """
    set_clock(CLOCK_START_ISO)
    create_consumer(full_name="Pat Consumer", email="pat@example.com",
                    home_state_code="IA")
    resp = api.create_consumer(
        {"full_name": "Patrick Consumer", "email": "pat@example.com",
         "home_state_code": "NE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_business_create_rejects_zero_employee_count(api):
    """PRD §3.1: "A `BureauAdmin` onboards a business by supplying its
    `legal_name`, its `home_state_code` (the principal place of business), its
    `employee_count` (at least 1; anything smaller is rejected with
    `ERR_INVALID_REQUEST`), and its `founded_on` founding date in ISO 8601 —
    the founding date later drives both accreditation eligibility and the
    business-age rating factor."

    Design: Corner/entities/business_create_rejects_zero_employee_count
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    resp = api.create_business(
        create_business_payload(legal_name="No Employees LLC",
                                home_state_code="IA", employee_count=0,
                                founded_on="2020-01-01T00:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api.list_businesses(ADMIN))
    assert rows == [] and meta["total_count"] == 0


def test_business_create_extra_status_fields_input_ignored(api):
    """PRD §3.1: "A newly created business carries `accreditation_status`
    `NOT_ACCREDITED` and `advertising_compliance_status` `CLEAR`."
    PRD §2.5: "`version` (integer): a system-managed integer that increments
    by 1 on every mutation of the resource. Clients never write `version`
    directly"

    Design: Corner/entities/business_create_extra_status_fields_input_ignored
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    payload = create_business_payload(legal_name="Eager Beaver LLC",
                                      home_state_code="IA", employee_count=3,
                                      founded_on="2020-01-01T00:00:00Z")
    payload["accreditation_status"] = "ACCREDITED"  # system-managed: ignored
    payload["version"] = 99  # never client-writable: ignored
    resp = api.create_business(payload, ADMIN)
    data = validate_success(resp, 201)
    assert_business(data)
    assert data["accreditation_status"] == "NOT_ACCREDITED"
    assert data["advertising_compliance_status"] == "CLEAR"
    assert data["version"] != 99, \
        "the client-supplied version must be overridden by the server"


def test_complaints_list_paginates_and_filters(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and is bounded above
    at 100. The `offset` parameter skips that many items from the start of the
    result set and defaults to 0."
    PRD §3.4: "Complaints can be listed with `business_id`, `consumer_id`, or
    `status` filters"

    Design: Corner/entities/complaints_list_paginates_and_filters
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    c1 = file_and_forward_complaint(consumer, business, category="SERVICE",
                                    description="p1")
    file_complaint(consumer, business, category="BILLING", description="p2")
    file_complaint(consumer, business, category="DELIVERY", description="p3")
    assert c1["status"] == "FORWARDED"

    resp = api.list_complaints(ADMIN, params={"business_id": business["id"],
                                              "limit": 2, "offset": 0})
    page1, meta = validate_paginated(resp)
    assert len(page1) == 2
    assert (meta["total_count"], meta["has_more"]) == (3, True)
    assert (meta["limit"], meta["offset"]) == (2, 0)
    assert resp.json()["response_type"] == "array"
    for row in page1:
        assert_complaint(row)

    page2, meta = validate_paginated(api.list_complaints(
        ADMIN, params={"business_id": business["id"], "limit": 2,
                       "offset": 2}))
    assert len(page2) == 1
    assert (meta["total_count"], meta["has_more"]) == (3, False)

    received, _ = validate_paginated(api.list_complaints(
        ADMIN, params={"business_id": business["id"], "status": "RECEIVED"}))
    assert len(received) == 2
    forwarded, _ = validate_paginated(api.list_complaints(
        ADMIN, params={"business_id": business["id"], "status": "FORWARDED"}))
    assert len(forwarded) == 1

    _rows, meta = validate_paginated(api.list_complaints(ADMIN))
    assert (meta["limit"], meta["offset"]) == (10, 0), \
        "omitted parameters fall back to the pinned defaults"
    assert meta["total_count"] == 3


def test_complaint_get_with_unknown_id_returns_404_envelope(api):
    """PRD §2.6: "Each missing resource yields its own not-found error:
    `ERR_BUREAU_NOT_FOUND`, `ERR_BUSINESS_NOT_FOUND`,
    `ERR_CONSUMER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
    `ERR_MEDIATION_NOT_FOUND`, `ERR_ARBITRATION_NOT_FOUND`,
    `ERR_SNAPSHOT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_AD_REVIEW_NOT_FOUND`, or `ERR_SCAM_REPORT_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/complaint_get_with_unknown_id_returns_404_envelope
    """
    resp = api.get_complaint(NON_EXISTENT_UUID, ADMIN)
    error = validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_FOUND)
    assert error["message"], "the error envelope carries a message"
