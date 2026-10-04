"""The scale price file revisits PENDING and ACTIVE across its rotation."""

from test_helpers import (
    ApiErrorId,
    api_client,
    platform_admin_headers,
    scale_operator_headers,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    validate_error,
    validate_success,
)


def _setup_two_price_files():
    set_clock("2026-09-02T03:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0, with_price_file=False)
    # PRD §3.6 permits supersession only for an overlapping interval that is a
    # re-price (effective_from strictly later, effective_to identical) or an
    # abutting one, so the successor is shaped as a re-price.
    old = setup_price_file(
        master.s, file_label="PF-OLD",
        effective_from="2026-09-02T00:00:00Z", effective_to="2026-09-10T00:00:00Z",
        item_price_count=4, activate=False,
    )
    new = setup_price_file(
        master.s, file_label="PF-NEW",
        effective_from="2026-09-02T06:00:00Z", effective_to="2026-09-10T00:00:00Z",
        item_price_count=6, activate=False,
    )
    return master, old, new


def test_a_price_file_re_enters_active_through_the_superseded_rotation():
    """PRD §3.6: "Reactivating a `SUPERSEDED` file also returns it through
    `PENDING` and then immediately into `ACTIVE` via the ordinary activation
    edge: this is permitted only when the currently ACTIVE file is expired
    relative to the logical clock and the returning file's effective interval
    contains the clock."
    PRD §3.6: "A superseded file re-enters rotation through `PENDING`, never by
    reverting the superseded row in place."

    Design: Difficulty/non_linear_state_machine/scale_price_file_supersede_and_reactivate_cycle
    """
    master, old, new = _setup_two_price_files()

    first = validate_success(api_client.activate_price_file(old["id"], scale_operator_headers()))
    assert first["status"] == "ACTIVE", "the first activation enters ACTIVE"

    second = validate_success(api_client.activate_price_file(new["id"], scale_operator_headers()))
    assert second["status"] == "ACTIVE"

    old_after_supersede = validate_success(api_client.get_price_file(old["id"], platform_admin_headers()))
    assert old_after_supersede["status"] == "SUPERSEDED"

    # The clock sits inside the returning file's interval but outside the
    # incumbent's, which is the precondition PRD §3.6 states for reactivation.
    set_clock("2026-09-02T03:00:00Z")
    returned = validate_success(
        api_client.reactivate_price_file(old["id"], scale_operator_headers())
    )
    assert returned["status"] == "ACTIVE", (
        "the superseded file re-enters ACTIVE a second time through the rotation"
    )
    new_after = validate_success(api_client.get_price_file(new["id"], platform_admin_headers()))
    assert new_after["status"] == "SUPERSEDED", (
        "reactivation supersedes the incumbent exactly as a fresh activation would"
    )


def test_retraction_returns_the_file_to_the_pending_state_it_already_held():
    """PRD §3.6: "Withdrawing an `ACTIVE` file returns it to `PENDING` rather than
    to a dead end, and it is guarded twice."

    Design: Difficulty/non_linear_state_machine/scale_price_file_supersede_and_reactivate_cycle
    """
    master, old, new = _setup_two_price_files()
    validate_success(api_client.activate_price_file(old["id"], scale_operator_headers()))
    validate_success(api_client.activate_price_file(new["id"], scale_operator_headers()))
    set_clock("2026-09-02T03:00:00Z")
    validate_success(api_client.reactivate_price_file(old["id"], scale_operator_headers()))

    retracted = validate_success(api_client.retract_price_file(old["id"], scale_operator_headers()))
    assert retracted["status"] == "PENDING", (
        "a withdrawn rotation returns to PENDING, the state the file held before its first activation"
    )
    # PRD 3.6: with no candidate file the label-generating calls, and the
    # resolution read itself, report ERR_PRICE_FILE_STALE.
    resolve_response = api_client.get_active_price_file(master.s, platform_admin_headers())
    validate_error(resolve_response, ApiErrorId.ERR_PRICE_FILE_STALE)
    report = validate_success(api_client.get_posture_report(master.s, platform_admin_headers()))
    assert report["posture_reason"] == "NO_ACTIVE_PRICE_FILE", (
        "an empty candidate set drives the store's posture reason to NO_ACTIVE_PRICE_FILE"
    )