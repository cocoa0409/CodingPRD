"""Corner design — section: endpoints."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_campaign,
    create_product,
    set_clock,
    setup_operating_store,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    activate_agreement,
    add_assortment_item,
    create_draft_agreement,
    create_licensee,
    create_store,
    create_venue,
)
from test_helpers.test_users import make_licensee_manager_headers


def test_delete_assortment_item_soft_deletes():
    """PRD §3.4: "Items are removed by soft-delete: the `active` flag flips to
    false while the row remains queryable, and the deletion is refused while
    the store is `OPERATING` — a running kiosk may not shed assortment
    mid-service."

    Design: Corner/endpoints/delete_assortment_item_soft_deletes
    """
    set_clock()
    licensee = create_licensee()
    venue = create_venue()
    agreement = activate_agreement(create_draft_agreement(licensee["id"], venue["id"]))
    store = create_store(agreement["id"], licensee["id"],
                         store_code="ST1", equipment_footprint_units=40)
    product = create_product()
    assortment = add_assortment_item(store["id"], licensee["id"], product["id"],
                                     par_level=10)
    lic_headers = make_licensee_manager_headers(licensee["id"])
    resp = api_client.delete_assortment_item(assortment["id"], lic_headers)
    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"
    refreshed = validate_success(api_client.get_assortment_item(assortment["id"], lic_headers))
    assert refreshed["active"] is False


def test_fk_reverse_reachability_agreement_stores():
    """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/fk_reverse_reachability_agreement_stores
    """
    set_clock()
    licensee = create_licensee()
    venue = create_venue()
    agreement = activate_agreement(create_draft_agreement(licensee["id"], venue["id"]))
    s1 = create_store(agreement["id"], licensee["id"],
                      store_code="ST1", equipment_footprint_units=20)
    s2 = create_store(agreement["id"], licensee["id"],
                      store_code="ST2", equipment_footprint_units=20)
    rows, meta = validate_paginated(api_client.list_agreement_stores(agreement["id"], ADMIN))
    assert meta["total_count"] == 2
    assert all(row["agreement_id"] == agreement["id"] for row in rows)
    assert {row["id"] for row in rows} == {s1["id"], s2["id"]}


def test_campaign_activate_before_window_rejected():
    """PRD §3.9: "Activation moves `PLANNED → ACTIVE` and is gated three ways:
    the logical clock's date must fall within the window (else
    `ERR_CAMPAIGN_WINDOW_NOT_OPEN`), the store must be `OPERATING` (else
    `ERR_STORE_NOT_OPERATING`), and the store's posture must not be `PROBATION`
    (else `ERR_STORE_POSTURE_PROBATION`)."

    Design: Corner/endpoints/campaign_activate_before_window_rejected
    """
    set_clock()  # 2026-09-01
    bundle = setup_operating_store()
    campaign = create_campaign(
        bundle["store"]["id"], start_date="2026-10-01", end_date="2026-10-10")
    resp = api_client.activate_promotion_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_NOT_OPEN.value)
    campaign = validate_success(api_client.get_promotion_campaign(campaign["id"], ADMIN))
    assert campaign["status"] == "PLANNED"


def test_campaign_full_lifecycle_reconcile():
    """PRD §3.9: "An `ACTIVE` campaign may be ended by the brand, moving it to
    `ENDED`, and an `ENDED` campaign is reconciled — its `reconciled` flag set
    true as it moves to `RECONCILED` — as the terminal bookkeeping step."

    Design: Corner/endpoints/campaign_full_lifecycle_reconcile
    """
    set_clock()  # 2026-09-01
    bundle = setup_operating_store()
    campaign = create_campaign(
        bundle["store"]["id"], start_date="2026-09-01", end_date="2026-09-30")
    activated = validate_success(api_client.activate_promotion_campaign(campaign["id"], ADMIN))
    assert activated["status"] == "ACTIVE"
    ended = validate_success(api_client.end_promotion_campaign(campaign["id"], ADMIN))
    assert ended["status"] == "ENDED"
    reconciled = validate_success(api_client.reconcile_promotion_campaign(campaign["id"], ADMIN))
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["reconciled"] is True
