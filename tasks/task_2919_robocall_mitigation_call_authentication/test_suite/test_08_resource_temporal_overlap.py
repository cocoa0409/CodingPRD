"""Interval semantics on two shared resources with opposite bound rules."""

from test_helpers import (
    ComplianceWorld,
    assert_decimal_2,
    assert_decimal_4,
    assert_equals,
    assert_instant,
    assert_provider_counters,
    expect_created,
    expect_error,
)
from test_helpers.api_errors import (
    ERR_NUMBER_INTERVAL_OVERLAP,
    ERR_OBSERVATION_WINDOW_OVERLAP,
)
from test_helpers.constants import NUMBER_1
from test_helpers.factories import (
    number_assignment_payload,
    traffic_observation_payload,
)


def _build_number_timeline(world: ComplianceWorld):
    """One number occupied by customer A from the first to the tenth of August."""
    provider = world.register_provider()
    customer_a = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
    )
    customer_b = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level="BUSINESS_REGISTRY_VERIFIED"
    )
    first = world.assign_number(
        provider["id"],
        customer_a["id"],
        NUMBER_1,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-08-10T00:00:00Z",
    )
    return provider["id"], customer_a["id"], customer_b["id"], first


def _handoff(world: ComplianceWorld, provider_id: str, customer_id: str, **interval):
    return world.client.create_number_assignment(
        number_assignment_payload(provider_id, customer_id, NUMBER_1, **interval),
        world.provider_admin(provider_id),
    )


class TestNumberAssignmentHalfOpenIntervals:
    """Adjacency accepted, genuine overlap refused."""

    def test_an_assignment_starting_where_the_last_ended_is_accepted(self, world):
        """The handoff at the shared instant lands ACTIVE beside the first row.

        PRD: "Because the interval excludes its upper bound, **adjacency is legal**: an assignment starting at exactly the instant a previous assignment ended does not collide, and back-to-back handoffs of the same number between two customers of the same provider are therefore expressible."

        Design: Difficulty/resource_temporal_overlap/number_assignment_half_open_adjacency_allowed_overlap_rejected
        """
        provider_id, _customer_a, customer_b, first = _build_number_timeline(world)

        adjacent = expect_created(
            _handoff(
                world,
                provider_id,
                customer_b,
                ownership_evidence="PORTED_IN",
                effective_from="2026-08-10T00:00:00Z",
                effective_to="2026-08-20T00:00:00Z",
            )
        )

        assert_equals(adjacent, "status", "ACTIVE")
        assert_instant(adjacent, "effective_from", "2026-08-10T00:00:00Z")
        assert_equals(world.read_assignment(first["id"]), "status", "ACTIVE")
        assert_provider_counters(
            world.read_provider(provider_id), active_assigned_number_count=2
        )

    def test_an_open_ended_assignment_starting_inside_a_live_one_is_refused(self, world):
        """A start one second inside the neighbour's interval collides, 409.

        PRD: "A new assignment may not overlap any existing non-`REVOKED` assignment of the same `telephone_number` under the same provider; an overlap is refused with `ERR_NUMBER_INTERVAL_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/number_assignment_half_open_adjacency_allowed_overlap_rejected
        """
        provider_id, customer_a, customer_b, first = _build_number_timeline(world)
        expect_created(
            _handoff(
                world,
                provider_id,
                customer_b,
                ownership_evidence="PORTED_IN",
                effective_from="2026-08-10T00:00:00Z",
                effective_to="2026-08-20T00:00:00Z",
            )
        )

        expect_error(
            _handoff(
                world,
                provider_id,
                customer_a,
                ownership_evidence="DIRECT_ALLOCATION",
                effective_from="2026-08-19T23:59:59Z",
            ),
            ERR_NUMBER_INTERVAL_OVERLAP,
        )

        assert_equals(world.read_assignment(first["id"]), "status", "ACTIVE")
        assert_provider_counters(
            world.read_provider(provider_id), active_assigned_number_count=2
        )


def _build_monitoring_timeline(world: ComplianceWorld):
    """A customer with one closed monitoring window ending on the second of July."""
    provider = world.register_provider()
    customer = world.verified_enabled_customer(
        provider["id"], kyc_evidence_level="CONTRACT_ONLY"
    )
    first = world.record_observation(
        provider["id"],
        customer["id"],
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-07-02T00:00:00Z",
        total_call_count=1000,
        short_duration_call_count=500,
        unanswered_call_count=500,
        complaint_count=0,
    )
    return provider["id"], customer["id"], first


def _record_second_window(
    world: ComplianceWorld, provider_id: str, customer_id: str, window_start: str
):
    return world.client.create_traffic_observation(
        traffic_observation_payload(
            provider_id,
            customer_id,
            window_start=window_start,
            window_end="2026-07-03T00:00:00Z",
            total_call_count=1000,
            short_duration_call_count=100,
            unanswered_call_count=100,
            complaint_count=0,
        ),
        world.provider_admin(provider_id),
    )


class TestObservationClosedWindows:
    """Both bounds inclusive, so touching endpoints already collide."""

    def test_a_window_starting_at_the_previous_end_instant_collides(self, world):
        """The touching window is refused 409 and the stored subscore is untouched.

        PRD: "A new window may not overlap any existing window of the same customer, and because both bounds are inclusive, merely *touching* a neighbour's endpoint is already a collision: a window starting at exactly the instant an earlier window ended is refused with `ERR_OBSERVATION_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/observation_closed_window_touching_endpoint_collides
        """
        provider_id, customer_id, first = _build_monitoring_timeline(world)

        expect_error(
            _record_second_window(
                world, provider_id, customer_id, "2026-07-02T00:00:00Z"
            ),
            ERR_OBSERVATION_WINDOW_OVERLAP,
        )

        assert_decimal_2(world.read_observation(first["id"]), "window_subscore", 0.40)
        assert_equals(world.read_customer(customer_id), "observation_count", 1)

    def test_shifting_the_start_one_second_accepts_and_renormalises_the_index(
        self, world
    ):
        """Two windows renormalise to 0.2000 rather than the unweighted 0.1600.

        PRD: "The index is the sum of each weight multiplied by its window's `window_subscore`, divided by the sum of the weights used, rounded half up to four decimal places."

        Design: Difficulty/resource_temporal_overlap/observation_closed_window_touching_endpoint_collides
        """
        provider_id, customer_id, _first = _build_monitoring_timeline(world)
        expect_error(
            _record_second_window(
                world, provider_id, customer_id, "2026-07-02T00:00:00Z"
            ),
            ERR_OBSERVATION_WINDOW_OVERLAP,
        )

        shifted = expect_created(
            _record_second_window(
                world, provider_id, customer_id, "2026-07-02T00:00:01Z"
            )
        )

        assert_decimal_2(shifted, "window_subscore", 0.08)
        assert_decimal_4(shifted, "resulting_risk_index", 0.2000)

        customer = world.read_customer(customer_id)
        assert_decimal_4(customer, "traffic_risk_index", 0.2000)
        assert customer["traffic_risk_index"] != 0.1600, (
            "the index must renormalise over the weights actually used, not sum "
            "the unused ones away"
        )
        assert_equals(customer, "risk_tier", "LOW")
