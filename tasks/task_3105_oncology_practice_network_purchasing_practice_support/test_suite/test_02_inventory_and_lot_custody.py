"""Lot custody, expiry, and the FIFO draw order."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error_is_one_of,
    ApiErrorId, get_success_data, set_clock, create_network, create_practice,
    create_product, create_provider, create_published_protocol,
    create_activated_contract, create_approved_agreement, receive_new_lot,
    adopt_pathways, get_practice, make_practice_admin_headers,
    create_treatment_payload, create_administer_payload, DEFAULT_CLOCK,
)


def test_lot_release_of_an_expired_lot_is_refused(api, network_admin_headers):
    """PRD §3.6: "Releasing a quarantined lot returns it to `AVAILABLE`,
    requires the lot to be `QUARANTINED` — failing with `ERR_LOT_NOT_QUARANTINED`
    — and is refused with `ERR_LOT_EXPIRED` when `expires_at` is at or before the
    logical clock, so a lot cannot be released back into circulation already dead."

    Design: Corner/state_machines/lot_release_of_an_expired_lot_is_refused
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"])
    practice = get_practice(practice["id"])

    product = create_product(network["id"])
    _, lot = receive_new_lot(practice["id"], product["id"], 100,
                             expires_at="2026-09-15T00:00:00Z")
    practice_headers = make_practice_admin_headers(practice["id"])

    quarantined = validate_success(
        api.quarantine_lot(lot["id"], practice_headers), 200)
    assert quarantined["status"] == "QUARANTINED"

    set_clock("2026-09-20T00:00:00Z")
    res = api.release_lot(lot["id"], practice_headers)
    validate_error_is_one_of(res, [ApiErrorId.ERR_LOT_EXPIRED])
    assert res.status_code == 409

    current = validate_success(api.get_inventory_lot(lot["id"], network_admin_headers), 200)
    assert current["status"] == "QUARANTINED"


def test_treatment_administer_from_voided_returns_not_scheduled(api, network_admin_headers):
    """PRD §3.9: "A `NetworkAdmin` may void an `ADMINISTERED` treatment, but only
    while its claim is in `DRAFT` or `DENIED` and no appeal has been filed,
    failing with `ERR_TREATMENT_HAS_SUBMITTED_CLAIM`; the treatment becomes
    `VOIDED`".
    PRD §3.7: "The treatment begins `SCHEDULED`."

    Design: Corner/state_machines/treatment_administer_from_voided_returns_not_scheduled
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"])
    practice = get_practice(practice["id"])
    product = create_product(network["id"], unit_type="VIAL")
    provider = create_provider(practice["id"])
    protocol = create_published_protocol(network["id"])
    adopt_pathways(practice["id"])
    receive_new_lot(practice["id"], product["id"], 200)
    practice = get_practice(practice["id"])

    practice_headers = make_practice_admin_headers(practice["id"])
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(practice["id"], provider["id"], product["id"],
                                     protocol["id"], patient_reference="PT-VOID-1",
                                     administered_units=100, vial_yield_units=100),
            practice_headers),
        201)
    assert treatment["status"] == "SCHEDULED"

    # A SCHEDULED treatment has not been administered, so the void must be refused.
    res = api.void_treatment(treatment["id"], network_admin_headers)
    assert res.status_code == 409, res.text
    validate_error_is_one_of(
        res, [ApiErrorId.ERR_TREATMENT_NOT_ADMINISTERED, ApiErrorId.ERR_INVALID_STATE])

    current = validate_success(
        api.get_patient_treatment(treatment["id"], network_admin_headers), 200)
    assert current["status"] == "SCHEDULED"


def test_fifo_tie_break_uses_created_at_not_id(api, network_admin_headers):
    """PRD §3.7: "The order is fixed by two keys and never uses an identifier:
    lots are sorted by `expires_at` ascending and, where two lots share an
    expiration instant, by `created_at` ascending."
    PRD §3.7: "Walking that order, the platform takes from each lot the smaller
    of the remaining need and that lot's `quantity_remaining`, emitting one
    consumption row per lot drawn".

    Design: Corner/calculations/fifo_tie_break_uses_created_at_not_id
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"])
    practice = get_practice(practice["id"])
    product = create_product(network["id"], unit_type="MG")
    provider = create_provider(practice["id"])
    protocol = create_published_protocol(network["id"])
    adopt_pathways(practice["id"])

    shared_expiry = "2027-01-01T00:00:00Z"
    set_clock("2026-09-03T00:00:00Z")
    _, lot_a = receive_new_lot(practice["id"], product["id"], 100,
                               expires_at=shared_expiry, lot_number="L-TIE-A")
    set_clock("2026-09-06T00:00:00Z")
    _, lot_b = receive_new_lot(practice["id"], product["id"], 100,
                               expires_at=shared_expiry, lot_number="L-TIE-B")

    set_clock("2026-09-10T00:00:00Z")
    practice = get_practice(practice["id"])
    practice_headers = make_practice_admin_headers(practice["id"])
    treatment = validate_success(
        api.create_treatment(
            create_treatment_payload(practice["id"], provider["id"], product["id"],
                                     protocol["id"], patient_reference="PT-FIFO-1",
                                     administered_units=150, dose_count=1,
                                     vial_yield_units=1, administered_at="2026-09-10T00:00:00Z"),
            practice_headers),
        201)
    version = get_practice(practice["id"])["version"]
    validate_success(
        api.administer_treatment(treatment["id"], create_administer_payload(version),
                                 practice_headers),
        200)

    consumptions = get_success_data(
        api.list_treatment_consumptions(treatment["id"], network_admin_headers))
    assert len(consumptions) == 2, "one consumption row per lot drawn"
    first = next(c for c in consumptions if c["consumption_sequence"] == 1)
    assert first["inventory_lot_id"] == lot_a["id"], (
        "the earlier-created lot must be drawn first when expiry instants tie")

    lot_a_after = validate_success(
        api.get_inventory_lot(lot_a["id"], network_admin_headers), 200)
    lot_b_after = validate_success(
        api.get_inventory_lot(lot_b["id"], network_admin_headers), 200)
    assert lot_a_after["quantity_remaining"] == 0
    assert lot_a_after["status"] == "DEPLETED"
    assert lot_b_after["quantity_remaining"] == 50