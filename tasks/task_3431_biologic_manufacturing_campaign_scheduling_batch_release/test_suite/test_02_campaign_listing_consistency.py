"""Campaign listing pagination/filtering and immediate read-after-write consistency."""
from test_helpers import (
    validate_success, validate_paginated,
    setup_master_data, setup_campaign, create_campaign_entity,
)


def test_campaigns_list_paginates_with_total_count_and_has_more(api, platform_admin_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0."
    PRD §2.3: "Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.2: "Campaigns are browsable through a listing that accepts optional `site_id`, `train_id`, `product_id`, `demand_type`, and `status` filters"

    Design: Corner/entities/campaigns_list_paginates_with_total_count_and_has_more
    """
    env = setup_master_data()
    train_id = env["train"]["id"]
    prod_id = env["product"]["id"]
    create_campaign_entity(train_id, prod_id, demand_type="COMMERCIAL",
                           planned_start_utc="2026-10-01T00:00:00Z",
                           planned_end_utc="2026-10-05T00:00:00Z",
                           upstream_hours=8, downstream_hours=24)
    create_campaign_entity(train_id, prod_id, demand_type="COMMERCIAL",
                           planned_start_utc="2026-10-05T06:00:00Z",
                           planned_end_utc="2026-10-10T00:00:00Z",
                           upstream_hours=8, downstream_hours=24)
    camp_c = create_campaign_entity(train_id, prod_id, demand_type="CLINICAL",
                                    planned_start_utc="2026-10-20T00:00:00Z",
                                    planned_end_utc="2026-10-25T00:00:00Z",
                                    upstream_hours=8, downstream_hours=24)

    page1, meta1 = validate_paginated(
        api.list_campaigns(platform_admin_headers,
                           params={"train_id": train_id, "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_campaigns(platform_admin_headers,
                           params={"train_id": train_id, "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False

    clinical, _meta3 = validate_paginated(
        api.list_campaigns(platform_admin_headers,
                           params={"train_id": train_id, "demand_type": "CLINICAL"}))
    assert len(clinical) == 1 and clinical[0]["id"] == camp_c["id"]

    _all_rows, meta_default = validate_paginated(api.list_campaigns(platform_admin_headers))
    assert meta_default["limit"] == 10 and meta_default["offset"] == 0


def test_mutation_visible_in_same_response_and_next_read(api, platform_admin_headers,
                                                         process_engineer_headers):
    """PRD §3.2: "Every successful campaign advance — allocation, de-allocation, seed start, production start — increments the campaign's `version` by one."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/mutation_visible_in_same_response_and_next_read
    """
    env = setup_campaign()
    camp_id = env["campaign"]["id"]
    resp = api.advance_campaign(camp_id, "ALLOCATED", process_engineer_headers)
    data = validate_success(resp)
    assert data["status"] == "ALLOCATED" and data["version"] == 2
    reread = validate_success(api.get_campaign(camp_id, platform_admin_headers))
    assert reread["status"] == "ALLOCATED" and reread["version"] == 2
