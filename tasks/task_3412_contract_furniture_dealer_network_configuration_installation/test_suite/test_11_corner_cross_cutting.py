"""Cross-cutting optimistic-concurrency corners: the stale lock and the
version ladder across an order's lifecycle (PRD §2.5)."""

from test_helpers import (
    ApiErrorId,
    acknowledge_order,
    cancel_order,
    create_configuration,
    create_order,
    create_product_family,
    create_dealer,
    lock_configuration,
    make_dealer_headers,
    make_lock_payload,
    make_submit_payload,
    revise_configuration,
    setup_locked_world,
    submit_order,
    validate_error,
    validate_success,
)


def test_occ_stale_spec_lock_returns_412(api):
    """PRD §2.5: "locking a configuration requires
    `expected_configuration_version` holding the client's last observed
    `version` of the configuration spec. If the supplied value does not match
    the entity's current `version` — because a dealer-suspension cascade, a
    prior submission, a revision, or any other mutation has advanced the
    version since the client last read the resource — the write is rejected
    with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_layers/layer_occ_stale_spec_lock_returns_412
    """
    create_product_family(api, category="SEATING", base_lead_time_days=28)
    dealer = create_dealer(api)
    headers = make_dealer_headers(dealer["id"])

    spec = create_configuration(api, dealer["id"], name="Chairs")
    assert spec["version"] == 1
    locked = lock_configuration(api, spec, dealer["id"])
    assert locked["version"] == 2
    revised = revise_configuration(api, locked, dealer["id"])
    assert revised["version"] == 3
    assert revised["status"] == "DRAFT"

    # The pre-lock version is now stale even though the spec is legitimately
    # DRAFT again: OCC fires before any state consideration.
    resp = api.lock_configuration(
        spec["id"], make_lock_payload(spec["version"]), headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    resp = api.lock_configuration(
        spec["id"], make_lock_payload(revised["version"]), headers
    )
    relocked = validate_success(resp, 200)
    assert relocked["status"] == "LOCKED"
    assert relocked["version"] == 4


def test_version_ladder_on_order_lifecycle(api):
    """PRD §2.5: "`version`, an integer that increments by 1 on every
    mutation of the resource" — create 1, submit 2, acknowledge 3, cancel 4.

    Design: Corner/cross_cutting_layers/layer_version_ladder_on_order_lifecycle
    """
    ctx = setup_locked_world(api)
    dealer_id = ctx["dealer"]["id"]

    order = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"], dealer_id
    )
    assert order["version"] == 1
    submitted = submit_order(api, order, dealer_id)
    assert submitted["version"] == 2
    acknowledged = acknowledge_order(api, order["id"])
    assert acknowledged["version"] == 3
    cancelled = cancel_order(
        api, order["id"], make_dealer_headers(dealer_id), reason="done"
    )
    assert cancelled["version"] == 4
    assert cancelled["status"] == "CANCELLED"
