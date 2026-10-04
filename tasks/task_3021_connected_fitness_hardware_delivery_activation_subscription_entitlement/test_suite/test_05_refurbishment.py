"""Refurbishment: certification lineage, pricing, listing asymmetry and resale."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_refurb_batch_payload,
    get_device,
    get_membership,
    set_clock,
    setup_active_membership,
    setup_buying_household,
    setup_refurb_chain,
    setup_refurb_source,
    validate_paginated,
    validate_success,
)

TECH = TEST_USERS["service_technician_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# =========================================================================
# Queue A — Difficulty instances
# =========================================================================

def test_certification_chain_depth_counts_hops_from_the_source_device():
    """PRD §2.10: "Refurbished units are traced through a self-referential link: a
    device records the `certifying_device_id` of the unit that was returned to seed
    it. This lineage is a chain, and its length from a batch's source device is the
    `certification_chain_depth`."
    PRD §3.7: "The batch opens in `INSPECTING` with `inspected_at` stamped from the
    logical clock, and its `certification_chain_depth` is computed immediately from
    the source device's lineage, bounded at 3 hops as described in §2.10."

    Design: Difficulty/combinatorial_formula/certification_chain_depth_is_capped_and_self_loops_are_rejected
    """
    base = setup_refurb_chain(depth=3)
    depths = [batch["certification_chain_depth"] for batch in base["batches"]]
    assert depths == [0, 1, 2]

    minted = get_device(base["devices"][1])
    assert minted["certifying_device_id"] == base["devices"][0]
    assert minted["resale_cycle_count"] == 1


def test_a_chain_that_would_exceed_the_depth_bound_is_refused():
    """PRD §2.10: "The chain is bounded at 3 hops. A certification request that
    would require a deeper chain is refused with `ERR_CERTIFICATION_CHAIN_EXCEEDED`
    (HTTP 409)."

    Design: Difficulty/combinatorial_formula/certification_chain_depth_is_capped_and_self_loops_are_rejected
    """
    base = setup_refurb_chain(depth=4)
    # devices[3] carries depth 3 (at the bound, admissible); the sale over it
    # mints devices[4] with depth 4, whose own lineage exceeds the bound
    deepest = base["devices"][4]
    assert base["batches"][-1]["certification_chain_depth"] == 3

    res = api_client.create_refurb_batch({
        "source_device_id": deepest,
        "certification_grade": "A",
        "performance_resale_enabled": True,
    }, TECH)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_CERTIFICATION_CHAIN_EXCEEDED"


def test_a_batch_prices_the_unit_by_the_certified_grade():
    """PRD §3.7: "The batch moves to `CERTIFIED` and its `resale_price_cents` is set
    as a fraction of the source device's SKU list price: three fifths for grade `A`,
    one half for grade `B`, and two fifths for grade `C`."
    PRD §3.7: "If the grade is `B` or `C`, the batch's `performance_resale_enabled`
    flag is forced to false — a lower-grade unit is never sold as a performance
    model."

    Design: Difficulty/combinatorial_formula/certification_chain_depth_is_capped_and_self_loops_are_rejected
    """
    base = setup_refurb_source(clock_utc="2026-09-05T13:30:00Z")
    d_id = base["device_id"]

    graded = {}
    for grade, supplement in (("A", "TREAD-1001"), ("B", "TREAD-1002"),
                              ("C", "TREAD-1003")):
        batch = validate_success(api_client.create_refurb_batch({
            "source_device_id": d_id,
            "certification_grade": grade,
            "performance_resale_enabled": True,
        }, TECH), 201)
        assert batch["certification_chain_depth"] == 0
        certified = validate_success(
            api_client.certify_refurb_batch(batch["id"], {}, TECH), 200)
        graded[grade] = certified

    assert graded["B"]["resale_price_cents"] < graded["A"]["resale_price_cents"]
    assert graded["C"]["resale_price_cents"] < graded["B"]["resale_price_cents"]
    assert graded["A"]["status"] == "CERTIFIED"
    assert graded["B"]["performance_resale_enabled"] is False
    assert graded["C"]["performance_resale_enabled"] is False


def test_a_listed_batch_sells_into_a_minted_refurbished_unit():
    """PRD §3.7: "The batch moves to `SOLD` and records the minted device in
    `sold_device_id`. The minted device is born `REFURBISHED` in `condition`, carries
    `provenance_source` of `RESALE`, points its `certifying_device_id` back at the
    batch's source device, opens directly in `activation_status` `ACTIVE`, carries a
    `resale_cycle_count` of 1, and is bound to the buying membership."

    Design: Difficulty/combinatorial_formula/certification_chain_depth_is_capped_and_self_loops_are_rejected
    """
    base = setup_refurb_source(clock_utc="2026-09-05T13:30:00Z")
    buyer = setup_buying_household(clock_utc="2026-09-05T13:30:00Z")
    m_id = buyer["membership_id"]
    d_id = base["device_id"]

    batch = validate_success(api_client.create_refurb_batch(
        create_refurb_batch_payload(d_id), TECH), 201)
    validate_success(api_client.certify_refurb_batch(batch["id"], {}, TECH), 200)
    validate_success(api_client.list_refurb_batch_for_resale(batch["id"], {}, ADMIN), 200)
    sold = validate_success(api_client.sell_refurb_batch(
        batch["id"], {"buying_membership_id": m_id}, ADMIN), 200)

    assert sold["status"] == "SOLD"
    minted = get_device(sold["sold_device_id"])
    assert minted["condition"] == "REFURBISHED"
    assert minted["provenance_source"] == "RESALE"
    assert minted["certifying_device_id"] == d_id
    assert minted["activation_status"] == "ACTIVE"
    assert minted["resale_cycle_count"] == 1
    assert minted["membership_id"] == m_id



def test_resale_activation_resets_the_warranty_to_ninety_days():
    """PRD §3.7: "Its `warranty_expires_at` is set exactly 90 days beyond the
    logical clock. This is the resale warranty reset: the refurbished unit receives
    a fresh 90-day window anchored on the sale, and that window replaces rather than
    extends any prior coverage."

    Design: Corner/cross_cutting_layers/resale_device_carries_the_reset_warranty_and_the_refreshed_cycle_count
    """
    base = setup_refurb_source(clock_utc="2026-09-05T13:30:00Z")
    buyer = setup_buying_household(clock_utc="2026-09-05T13:30:00Z")
    m_id = buyer["membership_id"]

    batch = validate_success(api_client.create_refurb_batch(
        create_refurb_batch_payload(base["device_id"]), TECH), 201)
    validate_success(api_client.certify_refurb_batch(batch["id"], {}, TECH), 200)
    validate_success(api_client.list_refurb_batch_for_resale(batch["id"], {}, ADMIN), 200)
    sold = validate_success(api_client.sell_refurb_batch(
        batch["id"], {"buying_membership_id": m_id}, ADMIN), 200)

    minted = get_device(sold["sold_device_id"])
    assert minted["warranty_expires_at"] == "2026-12-04T13:30:00Z"
    linage = get_device(base["device_id"])
    assert linage["warranty_expires_at"] == "2027-09-05T13:30:00Z"
    assert minted["warranty_expires_at"] != "2027-12-04T13:30:00Z"


# =========================================================================
# Queue B — Corner instances
# =========================================================================

def test_a_sold_batch_refuses_a_second_sale():
    """PRD §3.7: "A batch that has reached `SOLD` is terminal, and a second sale
    attempt against it is refused with `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/sold_refurb_batch_rejects_a_second_sell
    """
    base = setup_refurb_source(clock_utc="2026-09-05T13:30:00Z")
    buyer = setup_buying_household(clock_utc="2026-09-05T13:30:00Z")
    m_id = buyer["membership_id"]

    batch = validate_success(api_client.create_refurb_batch(
        create_refurb_batch_payload(base["device_id"]), TECH), 201)
    validate_success(api_client.certify_refurb_batch(batch["id"], {}, TECH), 200)
    validate_success(api_client.list_refurb_batch_for_resale(batch["id"], {}, ADMIN), 200)
    sold = validate_success(api_client.sell_refurb_batch(
        batch["id"], {"buying_membership_id": m_id}, ADMIN), 200)
    sold_device_id = sold["sold_device_id"]

    res = api_client.sell_refurb_batch(
        batch["id"], {"buying_membership_id": m_id}, ADMIN)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_ALREADY_TERMINAL"

    after = validate_success(api_client.get_refurb_batch(batch["id"], TECH), 200)
    assert after["status"] == "SOLD"
    assert after["sold_device_id"] == sold_device_id

    rows, meta = validate_paginated(
        api_client.list_device_refurb_batches(base["device_id"], TECH))
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_device_refurb_batches_sold(sold_device_id, TECH))
    assert meta["total_count"] == 1


def test_a_new_sale_device_cannot_take_the_resale_warranty_reset():
    """PRD §3.7: "The same 90-day reset and the same `resale_cycle_count` of 1 apply
    when a technician explicitly applies a resale warranty to an already-live
    resale-provenance device; that action requires `provenance_source` to be
    `RESALE`, and a device that originated as a new sale is refused with
    `ERR_WARRANTY_RESET_NOT_ELIGIBLE` (HTTP 409)."

    Design: Corner/errors/warranty_reset_on_a_new_sale_device_returns_not_eligible
    """
    base = setup_active_membership(clock_utc="2026-09-05T13:30:00Z")
    d_id = base["device_id"]
    before = get_device(d_id)
    assert before["provenance_source"] == "NEW_SALE"
    assert before["warranty_expires_at"] == "2027-09-05T13:30:00Z"

    res = api_client.warranty_reset(d_id, {}, TECH)

    assert res.status_code == 409, res.text
    assert res.json()["data"]["error_id"] == "ERR_WARRANTY_RESET_NOT_ELIGIBLE"

    after = get_device(d_id)
    assert after["warranty_expires_at"] == "2027-09-05T13:30:00Z"
    assert after["resale_cycle_count"] == 0


def test_the_resale_warranty_reset_succeeds_on_a_resale_provenance_device():
    """PRD §3.7: "The same 90-day reset and the same `resale_cycle_count` of 1 apply
    when a technician explicitly applies a resale warranty to an already-live
    resale-provenance device."

    Design: Corner/errors/warranty_reset_on_a_new_sale_device_returns_not_eligible
    """
    base = setup_refurb_source(clock_utc="2026-09-05T13:30:00Z")
    buyer = setup_buying_household(clock_utc="2026-09-05T13:30:00Z")
    m_id = buyer["membership_id"]

    batch = validate_success(api_client.create_refurb_batch(
        create_refurb_batch_payload(base["device_id"]), TECH), 201)
    validate_success(api_client.certify_refurb_batch(batch["id"], {}, TECH), 200)
    validate_success(api_client.list_refurb_batch_for_resale(batch["id"], {}, ADMIN), 200)
    sold = validate_success(api_client.sell_refurb_batch(
        batch["id"], {"buying_membership_id": m_id}, ADMIN), 200)

    reset = validate_success(api_client.warranty_reset(sold["sold_device_id"], {}, TECH), 200)
    assert reset["provenance_source"] == "RESALE"
    assert reset["resale_cycle_count"] == 1
    assert reset["warranty_expires_at"] == "2026-12-04T13:30:00Z"



def test_the_minted_lineage_reports_a_fresh_cycle_counter():
    """PRD §3.7: "carries a `resale_cycle_count` of 1, and is bound to the buying
    membership."
    PRD §3.2: "a `NEW_SALE` warranty is always measured from `delivered_at`, not from
    the moment the order was placed."

    Design: Corner/cross_cutting_layers/resale_device_carries_the_reset_warranty_and_the_refreshed_cycle_count
    """
    base = setup_refurb_source(clock_utc="2026-09-05T13:30:00Z")
    buyer = setup_buying_household(clock_utc="2026-09-05T13:30:00Z")
    m_id = buyer["membership_id"]
    lineage = get_device(base["device_id"])
    assert lineage["resale_cycle_count"] == 0
    assert lineage["warranty_expires_at"] == "2027-09-05T13:30:00Z"

    batch = validate_success(api_client.create_refurb_batch(
        create_refurb_batch_payload(base["device_id"]), TECH), 201)
    validate_success(api_client.certify_refurb_batch(batch["id"], {}, TECH), 200)
    validate_success(api_client.list_refurb_batch_for_resale(batch["id"], {}, ADMIN), 200)
    sold = validate_success(api_client.sell_refurb_batch(
        batch["id"], {"buying_membership_id": m_id}, ADMIN), 200)

    minted = get_device(sold["sold_device_id"])
    assert minted["resale_cycle_count"] == 1
    assert minted["condition"] == "REFURBISHED"
    assert minted["warranty_expires_at"] == "2026-12-04T13:30:00Z"
    assert minted["warranty_expires_at"] != lineage["warranty_expires_at"]
    assert get_membership(m_id)["id"] == minted["membership_id"]


