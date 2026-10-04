"""Breadth probes over list pagination, the response envelope, and the
public transparency read."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_jurisdiction_payload,
    create_procurement,
    file_findings,
    open_audit,
    publish_audit,
    set_clock,
    setup_election_definition,
    setup_procurement,
    transition_audit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
PUBLIC = TEST_USERS["public_requester_headers"]


def test_procurements_list_paginates_with_total_count(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
    the number of items skipped and defaults to 0. Unless otherwise
    specified, list endpoints return resources sorted by `created_at` in
    ascending order. The `meta` object of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §4: "| GET | `/evote/procurements` | List procurements; optional
    filters `jurisdiction_id`, `voting_system_id`, `certificate_id`, `status`
    | All roles |"

    Design: Corner/endpoints/procurements_list_paginates_with_total_count
    """
    base = setup_procurement("PLACED")
    off1 = base["officials"][0]["id"]
    jur_id = base["jurisdiction"]["id"]
    create_procurement(
        jur_id, base["system"]["id"], base["certificate"]["id"],
        acting_official_id=off1, quantity=5, unit_price_cents=1_000_000,
    )
    create_procurement(
        jur_id, base["system"]["id"], base["certificate"]["id"],
        acting_official_id=off1, quantity=2, unit_price_cents=500_000,
    )

    page1, meta1 = validate_paginated(
        api.list_procurements(AUDITOR, params={"jurisdiction_id": jur_id,
                                               "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3, "total_count counts the filtered set, not the page"
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_procurements(AUDITOR, params={"jurisdiction_id": jur_id,
                                               "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_success_envelope_shape_on_create(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`." and "The
    `response_type` is either "object" for a single resource or "array" for a
    list of resources."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
    unique, machine-readable string that identifies the specific error."

    Design: Corner/endpoints/success_envelope_shape_on_create
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_jurisdiction(
        create_jurisdiction_payload(
            name="Envelope County", state_code="CA", budget_total_cents=1000
        ),
        ADMIN,
    )
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict) and body["data"]["id"] == data["id"]

    resp = api.get_jurisdiction(NON_EXISTENT_UUID, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert body["data"]["message"]


def test_public_documentation_reflects_published_audits(api):
    """PRD §3.10: "From either terminal state, the `Auditor` publishes the
    report: `report_public` becomes true and `published_at` is stamped from
    the logical clock."
    PRD §3.10: "Publication is what admits an audit into the public
    documentation read, which any role — including `PublicRequester` — may
    call with no ownership checks: for a named system it returns `system_id`,
    `model_name`, `software_baseline_version`, `hardware_class`, the system's
    `system_status`, the `active_certificate_count`, the `campaign_count`,
    and the `public_audit_count` of published audit reports for that system."

    Design: Corner/endpoints/public_documentation_reflects_published_audits
    """
    base = setup_election_definition("CANVASSING")  # clock now at election day 08:00Z
    audit = open_audit(base["definition"]["id"], audit_type="RISK_LIMITING")
    file_findings(audit["id"], 0, 1, 0)
    transition_audit(audit["id"], "CLOSED_CONFIRMED")

    doc = validate_success(
        api.get_public_documentation(base["system"]["id"], PUBLIC)
    )
    assert doc["public_audit_count"] == 0, "unpublished audits are not counted"
    assert doc["system_status"] == "FIELDED"
    assert doc["active_certificate_count"] == 1
    assert doc["campaign_count"] == 1

    published = publish_audit(audit["id"])
    assert published["report_public"] is True
    assert published["published_at"].startswith("2026-11-03T08:00:00")

    doc = validate_success(
        api.get_public_documentation(base["system"]["id"], PUBLIC)
    )
    assert doc["public_audit_count"] == 1
