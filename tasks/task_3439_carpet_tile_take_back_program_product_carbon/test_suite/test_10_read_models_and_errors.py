"""Read models and the error catalogue (PRD §2.2, §2.3, §2.10): filtered
lists with exact scoping and pagination meta, empty-list behavior, and the
per-resource 404 vocabulary in the standard error envelope.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_batch_payload,
    create_claim,
    create_collection,
    create_installed_site,
    create_order,
    create_report,
    create_takeback,
    lay_zone,
    set_clock,
    setup_collection_with_batch,
    validate_created,
    validate_error,
    validate_paginated,
)

TEST_ADMIN = TEST_USERS["admin_headers"]


def test_batches_list_filters_by_collection_and_paginates(api, specifier_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, with a minimum accepted value of 1 and a
    maximum accepted value of 100. The `offset` parameter sets the number of
    items skipped before the page begins and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.2: "Batches can be listed with optional `collection_id` and
    `status` filters."

    Design: Corner/entities/batches_list_filters_by_collection_and_paginates
    """
    set_clock()
    col_a = create_collection(
        name="Alpha", pattern_code="ALP", lifecycle_boundary="CRADLE_TO_GATE",
        claim_intent="NONE",
    )
    col_b = create_collection(
        name="Beta", pattern_code="BET", lifecycle_boundary="CRADLE_TO_GATE",
        claim_intent="NONE",
    )
    ids_a = []
    for i, (code, date, m2, de) in enumerate(
        [
            ("DL-A1", "2026-09-05T00:00:00Z", 10, 0.1),
            ("DL-A2", "2026-09-06T00:00:00Z", 20, 0.2),
            ("DL-A3", "2026-09-07T00:00:00Z", 30, 0.3),
        ]
    ):
        data = validate_created(
            api.create_batch(
                col_a["id"],
                create_batch_payload(
                    dye_lot_code=code, production_date=date,
                    produced_m2=m2, delta_e=de,
                ),
                TEST_ADMIN,
            )
        )
        ids_a.append(data["id"])
    b1 = validate_created(
        api.create_batch(
            col_b["id"],
            create_batch_payload(
                dye_lot_code="DL-B1", production_date="2026-09-08T00:00:00Z",
                produced_m2=40, delta_e=0.4,
            ),
            TEST_ADMIN,
        )
    )

    resp = api.list_batches(
        specifier_headers, params={"collection_id": col_a["id"], "limit": 2, "offset": 0}
    )
    assert resp.json()["response_type"] == "array"
    page0, meta0 = validate_paginated(resp)
    assert len(page0) == 2
    assert meta0["total_count"] == 3
    assert meta0["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_batches(
            specifier_headers,
            params={"collection_id": col_a["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    # Both pages together cover exactly collection A's three batches.
    assert {row["id"] for row in page0 + page2} == set(ids_a)

    # The filter excludes the other collection's batch; defaults apply.
    rows_b, meta_b = validate_paginated(
        api.list_batches(specifier_headers, params={"collection_id": col_b["id"]})
    )
    assert [row["id"] for row in rows_b] == [b1["id"]]
    assert meta_b["total_count"] == 1
    assert meta_b["limit"] == 10
    assert meta_b["offset"] == 0


def test_zone_get_with_unknown_id_returns_404(api, admin_headers):
    """PRD §2.10: "The existence vocabulary is per-resource:
    `ERR_COLLECTION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_TAKEBACK_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_TARGET_NOT_FOUND`, and `ERR_PACKAGE_NOT_FOUND`, each an HTTP 404."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/zone_get_with_unknown_id_returns_404
    """
    set_clock()
    resp = api.get_zone(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_ZONE_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)


def test_filtered_lists_return_scoped_rows_and_empty_states(api, admin_headers):
    """PRD §3.3: "Zones can be listed with optional `site_id`, `batch_id`, and
    `status` filters."
    PRD §3.4: "Orders can be listed with optional `site_id`, `zone_id`,
    `matched_batch_id`, and `status` filters."
    PRD §3.5: "requests can be listed with optional `site_id`,
    `collection_id`, and `status` filters."
    PRD §3.6: "Reports can be listed with optional `collection_id` and
    `status` filters."
    PRD §3.7: "Claims can be listed with optional `collection_id`,
    `report_id`, `manufacturing_target_id`, and `status` filters."
    PRD §3.8: "Packages can be listed with optional `architect_firm`,
    `collection_id`, `report_id`, `claim_id`, and `status` filters."

    Design: Corner/endpoints/filtered_lists_return_scoped_rows_and_empty_states
    """
    set_clock()
    built = setup_collection_with_batch()
    col_id = built["collection"]["id"]
    site = create_installed_site()
    z1 = lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=10)
    ord1 = create_order(site, z1, reason="WEAR", new_zone_code="Z-1R")
    tb1 = create_takeback(site, col_id)
    rep1 = create_report(col_id)
    cl1 = create_claim(col_id, rep1["id"])

    rows, _ = validate_paginated(
        api.list_zones(admin_headers, params={"batch_id": built["batch"]["id"]})
    )
    assert [row["id"] for row in rows] == [z1["id"]]

    rows, _ = validate_paginated(
        api.list_replacement_orders(admin_headers, params={"zone_id": z1["id"]})
    )
    assert [row["id"] for row in rows] == [ord1["id"]]

    rows, _ = validate_paginated(
        api.list_takeback_requests(
            admin_headers, params={"site_id": site["id"], "status": "REQUESTED"}
        )
    )
    assert [row["id"] for row in rows] == [tb1["id"]]

    # A filter matching nothing is an empty page, not an error.
    rows, meta = validate_paginated(
        api.list_takeback_requests(
            admin_headers, params={"site_id": site["id"], "status": "CREDITED"}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False

    rows, _ = validate_paginated(
        api.list_pcf_reports(
            admin_headers, params={"collection_id": col_id, "status": "DRAFT"}
        )
    )
    assert [row["id"] for row in rows] == [rep1["id"]]

    rows, _ = validate_paginated(
        api.list_carbon_claims(admin_headers, params={"report_id": rep1["id"]})
    )
    assert [row["id"] for row in rows] == [cl1["id"]]

    resp = api.list_spec_packages(
        admin_headers, params={"architect_firm": "NO-SUCH-FIRM"}
    )
    assert resp.json()["response_type"] == "array"
    rows, meta = validate_paginated(resp)
    assert rows == []
    assert meta["total_count"] == 0


def test_not_found_catalog_sweeps_every_resource(api, admin_headers):
    """PRD §2.10: "The existence vocabulary is per-resource:
    `ERR_COLLECTION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_TAKEBACK_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_TARGET_NOT_FOUND`, and `ERR_PACKAGE_NOT_FOUND`, each an HTTP 404."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/not_found_catalog_sweeps_every_resource
    """
    set_clock()
    cases = [
        (api.get_collection, ApiErrorId.ERR_COLLECTION_NOT_FOUND),
        (api.get_batch, ApiErrorId.ERR_BATCH_NOT_FOUND),
        (api.get_feedstock_lot, ApiErrorId.ERR_LOT_NOT_FOUND),
        (api.get_site, ApiErrorId.ERR_SITE_NOT_FOUND),
        (api.get_zone, ApiErrorId.ERR_ZONE_NOT_FOUND),
        (api.get_replacement_order, ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_takeback_request, ApiErrorId.ERR_TAKEBACK_NOT_FOUND),
        (api.get_pcf_report, ApiErrorId.ERR_REPORT_NOT_FOUND),
        (api.get_carbon_claim, ApiErrorId.ERR_CLAIM_NOT_FOUND),
        (api.get_manufacturing_target, ApiErrorId.ERR_TARGET_NOT_FOUND),
        (api.get_spec_package, ApiErrorId.ERR_PACKAGE_NOT_FOUND),
    ]
    for getter, error_id in cases:
        resp = getter(NON_EXISTENT_UUID, admin_headers)
        data = validate_error(resp, error_id)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert data["message"].strip()
