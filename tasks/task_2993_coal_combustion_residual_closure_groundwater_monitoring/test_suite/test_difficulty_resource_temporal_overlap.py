"""Temporal windows read from both sides of the day that separates them."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    AGREEMENT_STATUS_DRAFT,
    AGREEMENT_STATUS_QUALIFIED,
    EVENT_STATUS_DRAFT,
    EVENT_STATUS_VALIDATED,
    EVENT_TYPE_DETECTION,
    FREQUENCY_SEMIANNUAL,
    PARAM_BORON,
)
from test_helpers.test_users import UTILITY_ADMIN_HEADERS

TOUCHING_WINDOW = {"commitment_start_on": "2026-06-30", "commitment_end_on": "2026-12-31"}
DISJOINT_WINDOW = {"commitment_start_on": "2026-07-01", "commitment_end_on": "2026-12-31"}


def case_one_validated_round_on_the_fifteenth_of_june(api):
    """A certified network whose only validated round anchors the pacing rule."""
    world = fixtures.seed_certified_network(
        api, "IMP-0016", ("BG-01", "BG-02", "BG-03", "BG-04")
    )
    world["base_event"] = fixtures.validated_round(
        api,
        world["program_id"],
        world["hydro_headers"],
        "DET-BASE",
        "2026-06-15",
        [(world["wells"]["DG-01"]["id"], 0.5000)],
        EVENT_TYPE_DETECTION,
        PARAM_BORON,
        validated_on="2026-06-16",
    )
    # Both candidate dates below must already be in the past.
    fixtures.set_clock(api, "2026-09-20T00:00:00Z")
    return world


def open_round_on(api, world, event_code, sampled_on):
    return api.create_sampling_event(
        factories.sampling_event_payload(
            world["program_id"], event_code, sampled_on, EVENT_TYPE_DETECTION
        ),
        world["hydro_headers"],
    )


def case_three_agreements_over_a_fifty_thousand_ton_inventory(api):
    """One qualified agreement for 30,000 tons and two 25,000-ton candidates."""
    world = fixtures.seed_unit(api, "IMP-0017", original_ash_in_place_tons=50000)
    first = fixtures.draft_agreement(
        api,
        world,
        "AGR-WIN-A",
        committed_tons=30000,
        commitment_start_on="2026-01-01",
        commitment_end_on="2026-06-30",
    )
    world["first_agreement"] = get_success_data(
        api.qualify_reuse_agreement(
            first["id"], factories.qualify_agreement_payload("2026-08-01"), world["civil_headers"]
        )
    )
    world["first_agreement_id"] = first["id"]
    world["touching_id"] = fixtures.draft_agreement(
        api, world, "AGR-WIN-B", committed_tons=25000, **TOUCHING_WINDOW
    )["id"]
    world["disjoint_id"] = fixtures.draft_agreement(
        api, world, "AGR-WIN-C", committed_tons=25000, **DISJOINT_WINDOW
    )["id"]
    return world


def qualify(api, world, agreement_id):
    return api.qualify_reuse_agreement(
        agreement_id, factories.qualify_agreement_payload("2026-08-01"), world["civil_headers"]
    )


def read_agreement(api, agreement_id):
    return get_success_data(api.get_reuse_agreement(agreement_id, UTILITY_ADMIN_HEADERS))


def test_a_round_eighty_nine_days_after_the_anchor_is_refused(api):
    """Day 89 still falls inside the forbidden window and no round is created.

    PRD: A new round's `sampled_on` must be at least 90 days after the `sampled_on` of the program's latest validated round; exactly 90 days later is accepted, and 89 days later is refused with `ERR_SAMPLE_INTERVAL_TOO_SHORT` (HTTP 422).
    Design: Difficulty/resource_temporal_overlap/sampling_interval_window_is_half_open_at_exactly_ninety_days
    """
    world = case_one_validated_round_on_the_fifteenth_of_june(api)
    assert world["base_event"]["status"] == EVENT_STATUS_VALIDATED
    a.assert_date(world["base_event"]["sampled_on"], "2026-06-15", "sampled_on")

    response = open_round_on(api, world, "DET-D89", "2026-09-12")

    validate_error(response, ApiErrorId.SAMPLE_INTERVAL_TOO_SHORT.value)
    rounds, _ = fixtures.page(
        api.list_sampling_events(UTILITY_ADMIN_HEADERS, {"program_id": world["program_id"]})
    )
    assert [row["event_code"] for row in rounds] == ["DET-BASE"]


def test_a_round_exactly_ninety_days_after_the_anchor_is_accepted(api):
    """One day later the same request is admitted, and the anchor does not move.

    PRD: exactly 90 days later is accepted
    PRD: Among all validated rounds of the program, the one with the latest `sampled_on` - a later `created_at` breaking a tie, and the record identifier never consulted - becomes `last_validated_event_id`.
    Design: Difficulty/resource_temporal_overlap/sampling_interval_window_is_half_open_at_exactly_ninety_days
    """
    world = case_one_validated_round_on_the_fifteenth_of_june(api)

    created = get_success_data(open_round_on(api, world, "DET-D90", "2026-09-13"), 201)

    assert created["status"] == EVENT_STATUS_DRAFT
    a.assert_date(created["sampled_on"], "2026-09-13", "sampled_on")
    program = fixtures.read_program(api, world["program_id"])
    # A draft round has not been validated, so the schedule still reads the base round.
    assert program["last_validated_event_id"] == world["base_event"]["id"]
    assert program["sampling_frequency"] == FREQUENCY_SEMIANNUAL
    a.assert_date(program["next_sampling_due_date"], "2026-12-14", "next_sampling_due_date")


def test_windows_touching_on_one_shared_day_aggregate_past_the_inventory(api):
    """55,000 committed tons against 50,000 in place, only because 30 June is shared.

    PRD: Both windows are closed intervals on both ends, so two agreements that merely touch on a single shared date, one ending on the 30th of June and the next starting on the 30th of June, do overlap and their tonnages are summed.
    PRD: The committed tonnages of those overlapping peers plus the candidate's own `committed_tons` form the aggregate exposure, and if that aggregate strictly exceeds the unit's current `ash_in_place_tons` the qualification is refused with `ERR_REUSE_COMMITMENT_OVERLAP` (HTTP 409).
    Design: Difficulty/resource_temporal_overlap/adjacent_commitment_windows_touching_at_one_endpoint_exceed_the_ash_inventory
    """
    world = case_three_agreements_over_a_fifty_thousand_ton_inventory(api)
    assert fixtures.read_unit(api, world["unit_id"])["ash_in_place_tons"] == 50000
    assert world["first_agreement"]["status"] == AGREEMENT_STATUS_QUALIFIED
    assert world["first_agreement"]["meets_astm_c618_class_f"] is True
    a.assert_two_dp(world["first_agreement"]["qualification_score"], 70.30, "qualification_score")

    response = qualify(api, world, world["touching_id"])

    validate_error(response, ApiErrorId.REUSE_COMMITMENT_OVERLAP.value)
    refused = read_agreement(api, world["touching_id"])
    assert refused["status"] == AGREEMENT_STATUS_DRAFT
    assert refused["qualified_on"] is None
    assert refused["qualified_by"] is None


def test_shifting_the_window_start_by_one_day_makes_the_same_tonnage_qualify(api):
    """Disjoint windows are not peers, so the candidate stands on its own 25,000 tons.

    PRD: The exposure test looks at the unit's *other* agreements whose status is `QUALIFIED` or `ACTIVE` - draft, disqualified, suspended and completed agreements contribute nothing - and keeps those whose commitment window intersects the candidate's.
    Design: Difficulty/resource_temporal_overlap/adjacent_commitment_windows_touching_at_one_endpoint_exceed_the_ash_inventory
    """
    world = case_three_agreements_over_a_fifty_thousand_ton_inventory(api)

    qualified = get_success_data(qualify(api, world, world["disjoint_id"]))

    assert qualified["status"] == AGREEMENT_STATUS_QUALIFIED
    assert qualified["qualified_by"] == world["civil_id"]
    a.assert_two_dp(qualified["qualification_score"], 70.30, "qualification_score")
    # Qualifying the later window leaves the earlier agreement exactly as it was.
    assert read_agreement(api, world["first_agreement_id"])["status"] == AGREEMENT_STATUS_QUALIFIED
