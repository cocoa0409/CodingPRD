"""Resource creation and listing: envelope, defaults, pagination, required
fields, computed-field write protection, and scoped uniqueness."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_call_payload,
    create_invoice_payload,
    create_service_level_payload,
    validate_error,
    validate_paginated,
    validate_success,
    is_valid_uuid,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import NON_EXISTENT_ID
from test_helpers.fixtures import (
    certify_agent,
    create_agent,
    create_contract,
    create_course,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
SUP = TEST_USERS["supervisor_headers"]
KM = TEST_USERS["knowledge_manager_headers"]
BILL = TEST_USERS["billing_analyst_headers"]


def test_contract_create_returns_defaults_and_envelope():
    """PRD §3.1: "A new contract is born in `DRAFT` with `withheld_cents_cum`
    at 0 and `cure_periods_used` at 0."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.5: "`version`, an integer that increments on every mutation of the
    resource."

    Design: Corner/entities/contract_create_returns_defaults_and_envelope
    """
    resp = api_client.create_contract(
        {
            "agency_name": "State Benefits Agency",
            "measurement_tz": "UTC",
            "cap_absolutes": False,
        },
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["withheld_cents_cum"] == 0
    assert data["cure_periods_used"] == 0
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert data["created_at"] == "2026-09-01T00:00:00.000Z"


def test_service_level_list_paginates_and_filters():
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter states how many items to skip and defaults to 0."
    PRD §3.1: "The service-level collection can be filtered by `contract_id`,
    `program_code`, `metric`, and `status`."

    Design: Corner/entities/service_level_list_paginates_and_filters
    """
    contract = create_contract()
    sl_ids = []
    for metric, target, cap, fee in (
        ("ASA", 30, 1.0, 1000),
        ("ABANDON", 0.05, 0.5, 800),
        ("QA_AVG", 80, 0.5, 1200),
    ):
        payload = create_service_level_payload(
            contract["id"], metric=metric, target=target,
            cap_pct_of_gross=cap, remedy_fee_cents=fee,
        )
        sl = validate_success(api_client.create_service_level(payload, OPS), 201)
        sl_ids.append(sl["id"])

    page1, meta1 = validate_paginated(
        api_client.list_service_levels(
            BILL, params={"contract_id": contract["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api_client.list_service_levels(
            BILL, params={"contract_id": contract["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(
        api_client.list_service_levels(
            BILL, params={"contract_id": contract["id"], "metric": "ASA"}
        )
    )
    assert len(filtered) == 1
    assert filtered[0]["id"] == sl_ids[0]
    assert meta3["total_count"] == 1

    default_page, meta4 = validate_paginated(
        api_client.list_service_levels(BILL, params={"contract_id": contract["id"]})
    )
    assert len(default_page) == 3
    assert meta4["limit"] == 10
    assert meta4["offset"] == 0


def test_queue_create_with_unknown_contract_returns_contract_not_found():
    """PRD §2.6: "existence — path identifiers are validated left to right,
    and body foreign keys are checked in the endpoint's declared input order,
    each miss producing the entity-specific 404 (`ERR_CONTRACT_NOT_FOUND`, ...)".

    Design: Corner/entities/queue_get_unknown_id_returns_not_found
    """
    resp = api_client.create_queue(
        {
            "contract_id": NON_EXISTENT_ID,
            "program_code": "MEDICAID",
            "language_code": "en",
            "queue_type": "GENERAL",
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND)
    rows, meta = validate_paginated(api_client.list_queues(OPS))
    assert len(rows) == 0


def test_call_create_missing_enqueued_at_returns_invalid_request():
    """PRD §3.4: "A **Call** enters the system when a `Supervisor` (or an
    `OpsManager`) registers it with the `contract_id` it arrived under, the
    `program_code` the caller dialed, the caller's `language_code`, an
    optional `required_specialty`, and the `enqueued_at` logical timestamp of
    arrival."
    PRD §2.6: "request shape — required fields present, values well-typed,
    enum values inside their declared sets, referential fields well-formed,
    else `ERR_INVALID_REQUEST` (HTTP 400)".

    Design: Corner/entities/call_create_missing_enqueued_at_returns_invalid_request
    """
    contract = create_contract()
    resp = api_client.create_call(
        {
            "contract_id": contract["id"],
            "program_code": "MEDICAID",
            "language_code": "en",
        },
        SUP,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, _ = validate_paginated(
        api_client.list_calls(SUP, params={"contract_id": contract["id"]})
    )
    assert len(rows) == 0


def test_certification_and_completion_carry_no_version():
    """PRD §2.5: "a Certification and a CourseCompletion carry only `id` and
    `created_at` — both `updated_at` and `version` are absent from them,
    because neither resource is ever mutated after creation".

    Design: Corner/entities/certification_and_completion_carry_no_version
    """
    agent = create_agent()
    course = create_course()
    completion = certify_agent(agent["id"], course["id"])
    assert is_valid_uuid(completion["id"])
    assert completion["agent_id"] == agent["id"]
    assert completion["training_course_id"] == course["id"]
    assert "completed_at" in completion
    assert "version" not in completion, "completion must not carry version"
    assert "updated_at" not in completion, "completion must not carry updated_at"

    certs = api_client.list_certifications(OPS, params={"agent_id": agent["id"]})
    rows, meta = validate_paginated(certs)
    assert len(rows) == 1
    cert = rows[0]
    assert "version" not in cert, "certification must not carry version"
    assert "updated_at" not in cert, "certification must not carry updated_at"
    assert cert["invalidated_at"] is None
    assert cert["valid_until"] == "2027-01-01T00:00:00Z"


def test_call_create_computed_fields_are_ignored_input():
    """PRD §3.4: "A new call is `WAITING` with `route_depth` 0 and no
    `queue_id`, `agent_id`, or `assigned_via` — all three stay null while the
    call waits."

    Design: Corner/entities/call_create_computed_fields_are_ignored_input
    """
    contract = create_contract()
    payload = create_call_payload(contract["id"])
    payload.update({"status": "COMPLETED", "route_depth": 9, "assigned_via": "OVERFLOW"})
    resp = api_client.create_call(payload, SUP)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "WAITING"
    assert data["route_depth"] == 0
    assert data["queue_id"] is None
    assert data["agent_id"] is None
    assert data["assigned_via"] is None
    assert data["version"] == 1


def test_invoice_create_duplicate_period_rejected():
    """PRD §3.9: "The period is unique per contract — a second invoice for the
    same contract and period is rejected with `ERR_INVOICE_PERIOD_DUPLICATE`
    (HTTP 409)."

    Design: Corner/entities/invoice_create_duplicate_period_rejected
    """
    contract_a = create_contract()
    contract_b = create_contract(agency_name="Second Agency", cap_absolutes=True)
    validate_success(
        api_client.create_invoice(create_invoice_payload(contract_a["id"]), BILL), 201
    )
    dup = api_client.create_invoice(create_invoice_payload(contract_a["id"]), BILL)
    validate_error(dup, ApiErrorId.ERR_INVOICE_PERIOD_DUPLICATE)
    ok = api_client.create_invoice(create_invoice_payload(contract_b["id"]), BILL)
    validate_success(ok, expected_status=201)
    rows, meta = validate_paginated(
        api_client.list_invoices(BILL, params={"contract_id": contract_a["id"]})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
