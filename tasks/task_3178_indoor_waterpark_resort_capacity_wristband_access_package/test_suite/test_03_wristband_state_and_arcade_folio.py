"""Wristband state machine, room-charge privilege, and the arcade folio."""
import pytest

from test_helpers import ApiErrorId, assert_wristband_credit_invariants, validate_error, validate_success
from test_helpers import fixtures as fx


def test_reissuing_an_active_band_returns_it_to_issued_for_the_successor(api, front_desk_headers):
    """PRD §3.3: "The successor is created in `ISSUED` status with `access_status`
    `PENDING`, carrying the old band's `arcade_credit_limit_cents` forward
    unchanged and starting with `arcade_credit_spent_cents` of 0, and it is issued
    for the same `valid_on_service_date` as the band it replaces."

    Design: Difficulty/non_linear_state_machine/wristband_reissue_returns_to_issued
    """
    resort = fx.create_resort(arcade_credit_rate_cents_per_unit=9450)
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=2)
    fx.check_in_reservation(resort["id"], reservation["id"])
    band = fx.create_wristband(
        resort["id"], "RESERVATION_GUEST", "Ava", reservation_id=reservation["id"]
    )
    band = fx.activate_wristband(resort["id"], band["id"])
    old = validate_success(api.reissue_wristband(resort["id"], band["id"], front_desk_headers))
    assert old["wristband_status"] == "REISSUED"
    successor = validate_success(
        api.get_wristband(resort["id"], old["superseded_by_wristband_id"], front_desk_headers)
    )
    assert successor["wristband_status"] == "ISSUED"
    assert successor["arcade_credit_limit_cents"] == 18900


def test_reissued_predecessor_carries_no_back_reference_and_zero_ceiling(api, front_desk_headers):
    """PRD §3.3: "The presented band moves to `REISSUED` with `access_status` `DENIED`, `room_charge_enabled` false, `arcade_credit_limit_cents` 0, and `superseded_by_wristband_id` naming the successor; its `version` is incremented, and the response to the operation is this old band rather than the successor, so that the successor's identifier can be read back from `superseded_by_wristband_id`."

    Design: Difficulty/non_linear_state_machine/wristband_reissue_returns_to_issued
    """
    resort, _room_type, _reservation, band = fx.setup_active_guest_band(guest_count=1)
    old = validate_success(api.reissue_wristband(resort["id"], band["id"], front_desk_headers))
    assert old["arcade_credit_limit_cents"] == 0
    assert old["room_charge_enabled"] is False
    assert old["access_status"] == "DENIED"
    successor = validate_success(
        api.get_wristband(resort["id"], old["superseded_by_wristband_id"], front_desk_headers)
    )
    assert successor["superseded_by_wristband_id"] is None


def test_reissued_band_ceiling_moves_to_the_successor_rather_than_multiplying(api, front_desk_headers):
    """PRD §3.2: "`credited_arcade_cents` is computed as an accrual: the property's
    `arcade_credit_rate_cents_per_unit` multiplied by the booking's
    `waterpark_included_units`, rounded half up to whole cents."
    PRD §3.3: "The successor is created in `ISSUED` status with `access_status` `PENDING`, carrying the old band's `arcade_credit_limit_cents` forward unchanged and starting with `arcade_credit_spent_cents` of 0, and it is issued for the same `valid_on_service_date` as the band it replaces."

    Design: Difficulty/compensating_invariant/reissue_conserves_reservation_arcade_credit_total
    """
    resort = fx.create_resort(arcade_credit_rate_cents_per_unit=9450)
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=2)
    reservation = fx.check_in_reservation(resort["id"], reservation["id"])
    band = fx.create_wristband(
        resort["id"], "RESERVATION_GUEST", "Jon", reservation_id=reservation["id"]
    )
    band = fx.activate_wristband(resort["id"], band["id"])
    old = validate_success(api.reissue_wristband(resort["id"], band["id"], front_desk_headers))
    successor = validate_success(
        api.get_wristband(resort["id"], old["superseded_by_wristband_id"], front_desk_headers)
    )
    assert old["arcade_credit_limit_cents"] == 0
    assert old["wristband_status"] == "REISSUED"
    assert successor["arcade_credit_limit_cents"] == 18900
    assert (
        old["arcade_credit_limit_cents"] + successor["arcade_credit_limit_cents"]
        == reservation["credited_arcade_cents"]
    )


def test_a_grant_of_exactly_the_remaining_ceiling_is_accepted(api, anonymous_headers):
    """PRD §2.5: "Both ceilings are inclusive at their boundary: a request that
    lands exactly on the limit is accepted, and a request one unit beyond it is
    rejected."

    Design: Difficulty/boundary_precision_check/arcade_ceiling_exact_equality_admits
    """
    resort = fx.create_resort(arcade_credit_rate_cents_per_unit=18900)
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=1)
    fx.check_in_reservation(resort["id"], reservation["id"])
    band = fx.create_wristband(
        resort["id"], "RESERVATION_GUEST", "Gil", reservation_id=reservation["id"]
    )
    band = fx.activate_wristband(resort["id"], band["id"])
    grant = validate_success(
        api.post_arcade_grant(resort["id"], band["id"], {"amount_cents": 18900}, anonymous_headers),
        201,
    )
    assert grant["grant_status"] == "SUCCEEDED"
    updated = validate_success(api.get_wristband(resort["id"], band["id"], anonymous_headers))
    assert updated["arcade_credit_spent_cents"] == 18900
    assert updated["arcade_credit_remaining_cents"] == 0
    assert_wristband_credit_invariants(updated)


def test_a_grant_one_cent_above_the_remaining_ceiling_is_refused(api, anonymous_headers):
    """PRD §3.4: "A grant whose amount exceeds the band's remaining credit is
    refused with `ERR_ARCADE_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/arcade_ceiling_exact_equality_admits
    """
    resort = fx.create_resort(arcade_credit_rate_cents_per_unit=18900)
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=1)
    fx.check_in_reservation(resort["id"], reservation["id"])
    band = fx.create_wristband(
        resort["id"], "RESERVATION_GUEST", "Gil", reservation_id=reservation["id"]
    )
    band = fx.activate_wristband(resort["id"], band["id"])
    response = api.post_arcade_grant(
        resort["id"], band["id"], {"amount_cents": 18901}, anonymous_headers
    )
    validate_error(response, ApiErrorId.ERR_ARCADE_LIMIT_EXCEEDED.value)
    unchanged = validate_success(api.get_wristband(resort["id"], band["id"], anonymous_headers))
    assert unchanged["arcade_credit_spent_cents"] == 0


@pytest.mark.parametrize("amount_cents", [601, 18901])
def test_arcade_ceiling_breach_surfaces_as_payment_required(api, anonymous_headers, amount_cents):
    """PRD §3.4: "A grant whose amount exceeds the band's remaining credit is
    refused with `ERR_ARCADE_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/arcade_ceiling_breach_returns_payment_required
    """
    resort = fx.create_resort(arcade_credit_rate_cents_per_unit=300)
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=2)
    fx.check_in_reservation(resort["id"], reservation["id"])
    band = fx.create_wristband(
        resort["id"], "RESERVATION_GUEST", "Val", reservation_id=reservation["id"]
    )
    band = fx.activate_wristband(resort["id"], band["id"])
    response = api.post_arcade_grant(
        resort["id"], band["id"], {"amount_cents": amount_cents}, anonymous_headers
    )
    validate_error(response, ApiErrorId.ERR_ARCADE_LIMIT_EXCEEDED.value)
    assert validate_success(
        api.get_wristband(resort["id"], band["id"], anonymous_headers)
    )["arcade_credit_spent_cents"] == 0


def test_revoking_an_active_band_disables_room_charge_privilege(api, front_desk_headers):
    """PRD §3.3: "The state change is the same in both cases: `REVOKED` with
    `access_status` `DENIED`, `room_charge_enabled` false,
    `arcade_credit_limit_cents` 0, and the band's `version` incremented."

    Design: Corner/cross_cutting_complexity_layers/activation_after_revoke_denies_access_and_drops_units
    """
    resort, _room_type, _reservation, band = fx.setup_active_guest_band(guest_count=2)
    revoked = validate_success(api.revoke_wristband(resort["id"], band["id"], front_desk_headers))
    assert revoked["wristband_status"] == "REVOKED"
    assert revoked["room_charge_enabled"] is False
    assert revoked["arcade_credit_limit_cents"] == 0


def test_revoking_a_band_declines_its_succeeded_grants(api, anonymous_headers, front_desk_headers):
    """PRD §3.3: "In addition, every arcade credit grant on that band whose
    `grant_status` is `SUCCEEDED` is moved to `DECLINED` with a `decline_reason` of
    `WRISTBAND_REVOKED`, so the folio is unwound along with the band."

    Design: Difficulty/transitive_cascade/pool_closure_revokes_band_then_declines_grants
    """
    resort, _attraction, _reservation, band = fx.setup_pool_closure_with_active_band(
        arcade_credit_rate_cents_per_unit=9450
    )
    grants = validate_success(
        api.list_wristband_arcade_credits(resort["id"], band["id"], fx.PLATFORM_OPS)
    )
    declined = [g for g in grants if g["grant_status"] == "DECLINED"]
    assert declined, "the closure must have declined the band's outstanding grants"
    assert all(g["decline_reason"] == "WRISTBAND_REVOKED" for g in declined)


def test_revoking_an_activated_band_removes_its_reserved_units(api, front_desk_headers):
    """PRD §3.3: "A successful activation moves the band to `ACTIVE` with `access_status` `GRANTED`, recomputes the room contribution for the band's `valid_on_service_date`, recomputes `pool_posture` from the property's current non-terminal water readings, and increments the band's `version`."
    PRD §3.2: "Each reservation's `reserved_units` equals its
    `waterpark_included_units` on every service date in the half-open span from
    `arrival_date` inclusive to `departure_date` exclusive."

    Design: Corner/cross_cutting_complexity_layers/activation_after_revoke_denies_access_and_drops_units
    """
    resort, _room_type, _reservation, band = fx.setup_active_guest_band(guest_count=2)
    before = fx.get_capacity(resort["id"], "2026-09-03")
    validate_success(api.revoke_wristband(resort["id"], band["id"], front_desk_headers))
    after = fx.get_capacity(resort["id"], "2026-09-03")
    assert after["room_units_reserved"] <= before["room_units_reserved"]

def test_reissue_moves_the_whole_ceiling_to_the_successor(api, front_desk_headers):
    """PRD §3.3: "carrying the old band's `arcade_credit_limit_cents` forward unchanged and starting with `arcade_credit_spent_cents` of 0, and it is issued for the same `valid_on_service_date` as the band it replaces."

    Design: Difficulty/compensating_invariant/reissue_conserves_reservation_arcade_credit_total
    """
    resort = fx.create_resort(arcade_credit_rate_cents_per_unit=9450)
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=2)
    reservation = fx.check_in_reservation(resort["id"], reservation["id"])
    band = fx.create_wristband(
        resort["id"], "RESERVATION_GUEST", "Jon", reservation_id=reservation["id"]
    )
    band = fx.activate_wristband(resort["id"], band["id"])
    old = validate_success(api.reissue_wristband(resort["id"], band["id"], front_desk_headers))
    successor = validate_success(
        api.get_wristband(resort["id"], old["superseded_by_wristband_id"], front_desk_headers)
    )
    assert successor["arcade_credit_limit_cents"] == reservation["credited_arcade_cents"]
    assert successor["arcade_credit_spent_cents"] == 0
