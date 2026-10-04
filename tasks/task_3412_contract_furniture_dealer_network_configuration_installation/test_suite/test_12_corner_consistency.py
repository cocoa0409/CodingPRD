"""Immediate-consistency corner: a dealer PATCH is visible to the very next
request, and a rejected submit leaves the order untouched (PRD §3.1, §2.5,
§3.5)."""

from test_helpers import (
    ApiErrorId,
    create_and_lock_configuration,
    create_order,
    make_dealer_headers,
    make_module_entry,
    make_submit_payload,
    setup_dealer_world,
    update_dealer,
    validate_error,
    validate_success,
)


def test_capability_patch_visible_on_immediate_retry(api):
    """PRD §3.1: "`service_capability_level`, `territory_codes`,
    `showroom_compliant`, and `status` may all change" — the mutation is
    visible in the PATCH response and to the immediately following request.
    The failed submit never mutated the order (§2.5: `version` "increments by
    1 on every mutation"), so the retry carries the same
    `expected_order_version` and now passes the capability gate of §3.5.

    Design: Corner/consistency_model/consistency_immediate_read_after_write
    """
    ctx = setup_dealer_world(
        api, capability=2, family_specs=(("SYS-7500", "SYSTEMS", 42),)
    )
    dealer_id = ctx["dealer"]["id"]
    spec = create_and_lock_configuration(
        api, dealer_id, modules=[make_module_entry("WORKSTATION_6X6", "A", 1)]
    )
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], dealer_id
    )

    resp = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(dealer_id),
    )
    validate_error(resp, ApiErrorId.ERR_CAPABILITY_INSUFFICIENT)

    patched = update_dealer(api, dealer_id, service_capability_level=5)
    assert patched["service_capability_level"] == 5

    retry = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(dealer_id),
    )
    submitted = validate_success(retry, 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] == order["version"] + 1
