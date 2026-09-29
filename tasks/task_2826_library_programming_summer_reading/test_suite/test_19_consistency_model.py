"""Writes are immediately consistent: the response body is already the final state.

The confirmation of a program is the widest write in the service — it stores the
draw lines, moves stock, commits money and publishes the room's seats.  This case
asserts that the write's own response already carries every one of those values,
and that the reads which follow add nothing the write had not already published.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.assertions import (
    assert_common_fields,
    assert_lot_state,
    assert_materials_conservation,
    assert_object_envelope,
    assert_program_status,
    assert_supply_draw_lines,
)
from test_helpers.fixtures import LibraryWorld


class TestConfirmPublishesTheWholeCascadeInItsOwnResponse:
    """No second write, and no waiting: the next read repeats the write's own figures."""

    def test_the_confirm_body_already_carries_the_draw_the_money_and_the_seats(
        self, world: LibraryWorld
    ) -> None:
        """The lot side of the cascade is visible in the very next request.

        "An accepted confirmation stores `supply_draw_lines`, moves each drawn lot's
        units from `quantity_available` to `quantity_reserved` (re-deriving
        `quantity_available` and setting the lot's `status` to `DEPLETED` when it
        reaches 0), stores `materials_committed_cents` and
        `materials_available_cents`, sets `confirmed_room_capacity` to the
        `effective_capacity_seats` of the `CONFIRMED` reservation" and "increments the
        program's `version` by 1, and answers 200 OK with the program."

        Design: Corner/consistency_model/confirm_response_already_reflects_the_whole_draw_cascade
        """
        branch = world.branch()
        room = world.room(branch["id"], capacity_seats=60)
        lot = world.supply_lot(
            branch["id"],
            sku="CRAFT-KIT",
            unit_cost_cents=250,
            quantity_procured=100,
            reuse_pool=False,
        )
        program = world.program(branch["id"])
        reservation = world.hold(program["id"], room["id"])
        world.confirm_reservation(reservation["id"])
        world.schedule(program["id"])
        version_before = world.program_version(program["id"])

        confirm_response = world.api.confirm_program(program["id"], world.manager)
        assert_object_envelope(confirm_response)
        written = get_success_data(confirm_response, 200)

        assert_program_status(written, operational_status="CONFIRMED")
        assert written["materials_committed_cents"] == 2750
        assert written["confirmed_room_capacity"] == 60
        assert_supply_draw_lines(
            written,
            [
                {
                    "lot_id": lot["id"],
                    "units": 10,
                    "unit_cost_cents": 250,
                    "surcharge_cents": 0,
                    "line_total_cents": 2500,
                }
            ],
        )
        assert_materials_conservation(written)
        assert_common_fields(written, expected_version=version_before + 1)

        read_response = world.api.get_program(program["id"], world.manager)
        assert_object_envelope(read_response)
        read_back = get_success_data(read_response, 200)
        assert read_back["materials_committed_cents"] == written[
            "materials_committed_cents"
        ]
        assert read_back["materials_available_cents"] == written[
            "materials_available_cents"
        ]
        assert read_back["confirmed_room_capacity"] == written[
            "confirmed_room_capacity"
        ]
        assert read_back["supply_draw_lines"] == written["supply_draw_lines"]
        assert read_back["version"] == written["version"]

        lot_response = world.api.get_inventory_lot(lot["id"], world.manager)
        assert_object_envelope(lot_response)
        read_lot = get_success_data(lot_response, 200)
        assert_lot_state(read_lot, available=90, reserved=10, issued=0)
        assert read_lot["status"] == "ACTIVE"
