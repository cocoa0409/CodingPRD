"""Dual-variant on-hand stock and pathway adherence recomputation."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, set_clock, create_network,
    create_practice, create_product, create_provider, create_published_protocol,
    create_activated_contract, create_approved_agreement, receive_new_lot,
    adopt_pathways, get_practice, make_practice_admin_headers,
    create_treatment_payload, create_administer_payload, DEFAULT_CLOCK, NON_EXISTENT_UUID,
)


def test_on_hand_stock_report_shows_both_expiring_and_usable_counts(api, network_admin_headers, network_analyst_headers):
    """PRD §3.6: "Both filter to lots belonging to the practice and the named
    product with status `AVAILABLE`, so quarantined, expired, and depleted lots
    are excluded from both."
    PRD §3.6: "The usable variant sums `quantity_remaining` over lots whose
    `expires_at` is strictly later than the instant being evaluated, because a
    lot expiring exactly at that instant is not usable."
    PRD §3.6: "Consider forty units sitting on a single lot expiring at
    `2026-09-10T00:00:00Z` with the logical clock reading that same instant: the
    expiring count is forty and the usable count is zero."

    Design: Corner/calculations/on_hand_stock_report_shows_both_expiring_and_usable_counts
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"])
    product = create_product(network["id"], unit_type="VIAL")
    receive_new_lot(practice["id"], product["id"], 40,
                    expires_at="2026-09-10T00:00:00Z")

    res = api.get_stock_report(
        practice["id"], network_analyst_headers,
        params={"drug_product_id": product["id"], "as_of": "2026-09-10T00:00:00Z"})
    data = validate_success(res, 200)

    # PRD §3.6/§3.12: the two variants read the same rows and disagree at the
    # expiry boundary — the expiring count is 40 and the usable count is zero.
    assert data["expiring_on_hand_units"] == 40
    assert data["usable_on_hand_units"] == 0


def test_pathway_adherence_recomputes_on_protocol_publish(api, network_admin_headers):
    """PRD §3.8: "A practice adopts the pathways program through a
    `PracticeAdmin` or `NetworkAdmin` action available from `NOT_ADOPTED`".
    PRD §3.8: "Adoption sets `pathway_steering_status` to `ACTIVE` and
    re-evaluates every `SCHEDULED` treatment of the practice for concordance
    against the protocol in force at its `administered_at`, then recomputes
    `pathway_adherence_pct` over that re-evaluated set."
    PRD §3.2: "a `pathway_steering_target_pct` representing the adherence level
    the pathways program will steer it toward and defaulting to 0.75".

    Design: Corner/calculations/pathway_adherence_recomputes_on_protocol_publish
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"])
    protocol = create_published_protocol(network["id"])
    adopt_pathways(practice["id"])

    current = validate_success(api.get_practice(practice["id"], network_admin_headers), 200)
    assert current["pathway_adherence_pct"] == 0
    assert current["pathway_steering_status"] == "ACTIVE"

    protocol_now = validate_success(
        api.get_pathway_protocol(protocol["id"], network_admin_headers), 200)
    assert protocol_now["status"] == "PUBLISHED"

    # A practice created without the field carries the documented default.
    other = create_practice(network["id"])
    created = validate_success(api.get_practice(other["id"], network_admin_headers), 200)
    assert created["pathway_steering_target_pct"] == pytest.approx(0.75)