"""Endpoint corners: the list envelope's pagination defaults and the audit
event an export leaves behind."""

from test_helpers import (
    account_with_contract,
    create_grant,
    create_ready_report,
    get_success_data,
    ingest_category_households,
    validate_paginated,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]


def test_list_pagination_envelope_defaults(api):
    """A list response without pagination parameters reports limit 10, offset 0, and both meta counts.

    PRD: "The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0."
    PRD: "List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    Design: Corner/endpoints/list_pagination_envelope_defaults
    """
    world = account_with_contract(api, name="Pager Co")
    create_grant(
        api, world["account"]["id"], valid_from="2026-09-01T00:00:00Z", valid_until="2026-10-01T00:00:00Z"
    )
    create_grant(
        api, world["account"]["id"], valid_from="2026-10-01T00:00:00Z", valid_until="2026-11-01T00:00:00Z"
    )
    rows, meta = validate_paginated(api.list_account_grants(world["account"]["id"], ADMIN))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2


def test_audit_event_written_on_export(api):
    """Exporting a READY report delivers it and records exactly one REPORT_EXPORTED event.

    PRD: "A successful export moves the report to `DELIVERED` and writes a `REPORT_EXPORTED` audit event naming the report as its subject."
    PRD: "Generation also stamps the report's `redistribution_class`: `CATEGORY` reports are `SHAREABLE_AGGREGATE`, `BRAND_OWN` reports are `INTERNAL_ONLY`, and `COMPETITOR_BLIND` reports are `MODELED_DERIVED`."
    Design: Corner/endpoints/audit_event_written_on_export
    """
    world = account_with_contract(api, name="Audit Co", scope_category="SNACKS", scope_brands=["ACME"])
    ingest_category_households(api, 20, "e")
    report = create_ready_report(api, world["contract"]["id"], world["analyst_headers"])
    exported = get_success_data(api.export_report(report["id"], world["analyst_headers"]))
    assert exported["status"] == "DELIVERED"
    assert exported["redistribution_class"] == "SHAREABLE_AGGREGATE"
    events, meta = validate_paginated(
        api.list_audit_events(ADMIN, params={"subject_id": report["id"]})
    )
    assert meta["total_count"] == 1
    event = events[0]
    assert event["event_type"] == "REPORT_EXPORTED"
    assert event["actor_role"] == "SupplierAnalyst"
    assert event["subject_id"] == report["id"]
