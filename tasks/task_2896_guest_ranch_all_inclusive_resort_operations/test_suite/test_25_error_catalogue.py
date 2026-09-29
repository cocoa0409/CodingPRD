"""Error catalogue: the authentication layer, the mount eligibility filter and
the seat gate that fires while a slot sits on hold."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import assertions
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import party_member, reservation_payload
from test_helpers.fixtures import (
    assign_guide,
    build_activity_slot,
    build_active_guide,
    build_booking,
    build_cabin,
    build_guest,
    build_horse,
    build_open_season,
    build_ready_rider,
    build_season,
    confirm_booking,
    open_slot,
    pay_deposit,
    set_clock_to,
    sign_guest_waiver,
    take_seat,
)
from test_helpers.test_users import (
    EMPTY_ROLE_HEADER,
    EMPTY_USER_ID_HEADER,
    HORSE_PROGRAM_DIRECTOR,
    MISSING_BOTH_HEADERS,
    MISSING_ROLE_HEADER,
    MISSING_USER_ID_HEADER,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
    make_headers,
)


class TestAuthenticationLayer:
    """Identification runs ahead of every business rule."""

    def test_request_missing_auth_headers_is_rejected_before_any_business_rule(self, client):
        """A well-formed read of a real season is refused on its headers alone, whether they are absent or blank.

        PRD: "If either header is absent, empty, or contains only whitespace, the request is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

        Design: Corner/errors/request_missing_auth_headers_is_rejected_before_any_business_rule
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_season(client)

        no_role = client.get_season(season["id"], MISSING_ROLE_HEADER)
        error = validate_error(
            no_role, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value, 401
        )
        assert error["message"].strip() != ""

        envelope = no_role.json()
        assert envelope["response_type"] == "error"
        assert isinstance(envelope["meta"]["api_request_id"], str)
        assert envelope["meta"]["api_request_id"] != ""

        for headers in (
            MISSING_USER_ID_HEADER,
            MISSING_BOTH_HEADERS,
            EMPTY_ROLE_HEADER,
            EMPTY_USER_ID_HEADER,
        ):
            validate_error(
                client.get_season(season["id"], headers),
                ApiErrorId.ERR_MISSING_AUTH_HEADERS.value,
                401,
            )

        # The season plainly exists, so none of the refusals above can be a
        # disguised not-found.
        readable = validate_success(client.get_season(season["id"], RANCH_MANAGER))
        assert readable["id"] == season["id"]

    @pytest.mark.parametrize("role_value", ["Wrangler", "ranchmanager", "TrailBossEmeritus"])
    def test_unrecognised_role_header_value_is_rejected_as_unknown_role(self, client, role_value):
        """A role string outside the six declared names fails identification rather than authorisation.

        PRD: "If `X-User-Role` carries a value that is not one of the six role names below, the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401)."

        Design: Corner/errors/unrecognised_role_header_value_is_rejected_as_unknown_role
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_season(client)

        error = validate_error(
            client.get_season(season["id"], make_headers("test-unknown-1", role_value)),
            ApiErrorId.ERR_UNKNOWN_ROLE.value,
            401,
        )
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value


class TestMountEligibility:
    """The auto-assign selector reports an empty eligible set as its own failure."""

    def test_auto_assign_with_no_eligible_horse_returns_no_eligible_mount(self, client):
        """The only animal in the herd is too light for the rider, so the draw fails and the seat keeps waiting.

        PRD: "When the eligible set is empty the request is refused with `ERR_NO_ELIGIBLE_MOUNT`."

        Design: Corner/errors/auto_assign_with_no_eligible_horse_returns_no_eligible_mount
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_open_season(client)
        cabin = build_cabin(client)
        ann = build_ready_rider(
            client, "Ann Adult", "1985-04-02", 165, ability="INTERMEDIATE"
        )

        booking = build_booking(
            client, season["id"], cabin["id"], [party_member(ann["id"])]
        )
        assert booking["deposit_required_cents"] == 143850
        pay_deposit(client, booking["id"])
        confirm_booking(client, booking["id"])

        pony = build_horse(client, name="Pony", weight_limit_lb=120)
        assert pony["horse_status"] == "IN_SERVICE"

        slot = build_activity_slot(client, season["id"])
        seat = take_seat(client, slot["id"], booking["id"], ann["id"])
        assert seat["mount_status"] == "PENDING"

        validate_error(
            client.auto_assign_mount(seat["id"], HORSE_PROGRAM_DIRECTOR),
            ApiErrorId.ERR_NO_ELIGIBLE_MOUNT.value,
            422,
        )

        seat_after = validate_success(
            client.get_reservation(seat["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assert seat_after["mount_status"] == "PENDING"
        assert seat_after["assigned_horse_id"] is None

        pony_after = validate_success(
            client.get_horse(pony["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assertions.assert_horse_load(pony_after, scheduled_load_hours=0.0)
        assert pony_after["version"] == pony["version"]

        comet = build_horse(client, name="Comet", weight_limit_lb=240)
        picked = validate_success(
            client.auto_assign_mount(seat["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assert picked["assigned_horse_id"] == comet["id"]
        assert picked["mount_status"] == "ASSIGNED"


class TestSeatGateOnAHeldSlot:
    """A slot that fell to HOLD sells no further seats until the defect clears."""

    def test_seat_request_on_a_held_slot_returns_slot_on_hold(self, client):
        """Releasing the only guide holds the slot, the next seat is refused, and a fresh guide reopens the door.

        PRD: "While a slot sits on `HOLD` no new seat may be created on it, and the cycle `OPEN → HOLD → OPEN` may repeat any number of times over the slot's life."

        Design: Corner/errors/seat_request_on_a_held_slot_returns_slot_on_hold
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_open_season(client)
        cabin = build_cabin(client)

        ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
        ben = build_guest(client, "Ben Adult", "1983-07-11", 190)
        sign_guest_waiver(client, ann["id"])
        sign_guest_waiver(client, ben["id"])

        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(ann["id"]), party_member(ben["id"])],
        )
        pay_deposit(client, booking["id"])
        confirm_booking(client, booking["id"])

        lead_guide = build_active_guide(
            client, season["id"], full_name="Gus Guide", housing_bunk_number=3
        )
        spare_guide = build_active_guide(
            client, season["id"], full_name="Hal Wrangler", housing_bunk_number=4
        )

        slot = build_activity_slot(
            client,
            season["id"],
            activity_type="HIKE",
            starts_at="2026-10-13T15:00:00Z",
            ends_at="2026-10-13T17:00:00Z",
            terrain_grade="ROLLING",
            min_ability_rank="UNASSESSED",
            capacity=4,
            rider_surcharge_cents=0,
            mount_required=False,
        )
        take_seat(client, slot["id"], booking["id"], ann["id"])
        assignment = assign_guide(client, slot["id"], lead_guide["id"])
        opened = open_slot(client, slot["id"])
        assert opened["slot_status"] == "OPEN"

        released = validate_success(
            client.release_guide_assignment(
                assignment["id"], "guide reassigned to the river crossing", RANCH_MANAGER
            )
        )
        assert released["assignment_status"] == "RELEASED"

        held = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assert held["slot_status"] == "HOLD"
        assert held["hold_reason"] == "UNDERSTAFFED"
        assertions.assert_readiness_posture(held, "UNDERSTAFFED")

        validate_error(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], ben["id"], held["version"]),
                RESERVATIONS_AGENT,
            ),
            ApiErrorId.ERR_SLOT_ON_HOLD.value,
            409,
        )

        assign_guide(client, slot["id"], spare_guide["id"])
        reopened = open_slot(client, slot["id"])
        assert reopened["slot_status"] == "OPEN"

        fresh = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        second_seat = validate_success(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], ben["id"], fresh["version"]),
                RESERVATIONS_AGENT,
            ),
            201,
        )
        assert second_seat["reservation_status"] == "CONFIRMED"

        final = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assertions.assert_slot_counters(final, confirmed_rider_count=2)
