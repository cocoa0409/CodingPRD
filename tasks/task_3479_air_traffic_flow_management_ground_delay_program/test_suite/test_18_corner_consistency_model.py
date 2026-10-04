"""Corner queue: the immediate consistency model — a mutation is visible in
its own response and in the very next read."""

from test_helpers import (
    assert_instant,
    at,
    get_flight,
    setup_active_gdp,
    substitution_payload,
    validate_success,
)


class TestImmediateConsistencyAfterSubstitution:
    def test_swap_visible_in_response_and_next_read(self, api):
        """PRD §2.10: "The consistency model is immediate: every mutation a
        request triggers, including the cascades it fires into other entities,
        is visible in that same request's response and to every subsequent
        read."

        Design: Corner/consistency_model/immediate_consistency_after_substitution
        """
        world = setup_active_gdp(
            api, carrier_names=("Alpha Air",),
            flight_specs=((0, "AAL1", "13:05"), (0, "AAL2", "13:20")),
        )
        f1, f2 = world["flights"]
        resp = api.create_substitution(
            world["tmi"]["id"],
            substitution_payload(f1["id"], f2["id"]),
            world["operator_headers"][0],
        )
        transaction = validate_success(resp, 201)
        assert_instant(transaction["to_slot_time"], at("13:10"), "swap result in response")

        read_back = get_flight(api, f1["id"])
        assert_instant(
            read_back["controlled_arrival"], at("13:10"),
            "the immediately following read reflects the swapped CTA",
        )
