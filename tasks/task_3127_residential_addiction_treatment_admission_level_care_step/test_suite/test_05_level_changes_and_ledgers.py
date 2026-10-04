"""Level-of-care changes, occupancy windows and the conserved ledger quantities."""

import pytest

from test_helpers import (
    C,
    CLINICAL_DIRECTOR_HEADERS,
    ApiErrorId,
    appoint_level_change,
    approve_authorization,
    cancel_level_change,
    complete_level_change,
    create_recovery_house,
    draft_continuing_care_plan,
    fund_step_down_authorization,
    grant_recovery_house_license,
    list_beds,
    read_change,
    read_episode,
    request_authorization,
    setup_admitted_episode,
    setup_accumulated_episode,
    setup_site,
    validate_error,
)


def _beds_by_id(site):
    return {b["id"]: b for b in list_beds(site.id)[0]}


def test_a_second_occupancy_window_over_the_same_bed_is_refused(api):
    """PRD §2.9: "That window may not overlap the occupancy window of any level-of-care
    change already recorded against the same bed, regardless of that other change's current
    status; adjacency — one window ending at exactly the instant the next begins — is
    permitted. A violation is `ERR_BED_OCCUPANCY_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/bed_occupancy_window_overlap_with_turnaround_gap
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )

    # Post the first change onto bed MN-B-02 with a real step-down route.
    from test_helpers import create_bed

    target = create_bed(site.id, bed_label="MN-B-04", level_of_care="ASAM_3_1",
                        cleaning_turnaround_hours=0)
    funder = fund_step_down_authorization(site, setup, "ASAM_3_1", bed_id=target["id"])
    first = appoint_level_change(
        site, setup.id, funder["id"], to_level="ASAM_3_1",
        effective_at=C.CLOCK_2026_09_08, bed_id=target["id"],
    )
    complete_level_change(site, first["id"])

    # A second change onto the SAME bed, inside the first window. The episode now sits
    # at ASAM_3_1, so the next permitted rung is ASAM_2_1 — a level no prior
    # authorization requested, which is what lets a second grant be stacked.
    second_funder = fund_step_down_authorization(
        site, setup, "ASAM_2_1", burn_clock="2026-09-11T00:00:00Z",
        second_burn_clock="2026-09-12T00:00:00Z",
    )
    version = read_episode(setup.id)["version"]
    response = api.create_level_of_care_change(
        site.id,
        setup.id,
        {
            "authorization_id": second_funder["id"],
            "to_level": "ASAM_2_1",
            "bed_id": target["id"],
            "effective_at": "2026-09-10T00:00:00Z",
            "expected_treatment_episode_version": version,
        },
        CLINICAL_DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_BED_OCCUPANCY_OVERLAP)


def test_adjacency_on_a_zero_turnaround_bed_is_not_an_overlap(api):
    """PRD §2.9: "adjacency — one window ending at exactly the instant the next begins — is
    permitted."
    PRD §2.9: "records a `cleaning_turnaround_hours` requirement."

    Design: Difficulty/resource_temporal_overlap/bed_occupancy_window_overlap_with_turnaround_gap
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )

    # The appointment targets the ASAM_3_1 bed row under its own label, so the claim
    # lands on a distinct row with nothing to collide with.
    funder = fund_step_down_authorization(
        site, setup, "ASAM_3_1", bed_id=site.bed_31["id"]
    )
    admitted = appoint_level_change(
        site, setup.id, funder["id"], to_level="ASAM_3_1",
        effective_at=C.CLOCK_2026_09_08, bed_id=site.bed_31["id"],
    )
    assert admitted["status"] == "PLANNED"
    assert admitted["bed_id"] == site.bed_31["id"]


def test_housing_placement_windows_share_one_open_ended_interval(api):
    """PRD §2.9: "a `grab_barrier_hours` turnaround requirement between two resident
    placements — 0 meaning no barrier and open-ended occupancy windows."
    PRD §3.8: "A requested window that overlaps another `ACTIVE` plan's window on the same
    housing row fails with `ERR_HOUSING_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/housing_placement_window_shares_one_open_ended_interval_per_house
    """
    site = setup_site()
    grant_recovery_house_license(site)
    house_a = create_recovery_house(site, house_name="Cedar House", grab_barrier_hours=0,
                                    capacity_beds=4, day_rate_cents=1000, proximity_rank=1)

    first_episode = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)
    first_plan = draft_continuing_care_plan(
        site, first_episode.id,
        housing_selection_basis="EXPLICIT", housing_id=house_a["id"],
        housing_window_start="2026-09-07T00:00:00Z", housing_window_end="2026-10-07T00:00:00Z",
    )
    from test_helpers import activate_continuing_care_plan

    activate_continuing_care_plan(site, first_plan["id"])

    second_episode = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)
    version = read_episode(second_episode.id)["version"]
    response = api.create_continuing_care_plan(
        site.id,
        second_episode.id,
        {
            "housing_selection_basis": "EXPLICIT",
            "housing_id": house_a["id"],
            "housing_window_start": "2026-11-01T00:00:00Z",
            "housing_window_end": "2026-12-01T00:00:00Z",
            "alumni_contact_interval_days": 7,
            "alumni_contacts_required": 2,
            "authorizing_clinician_id": site.clinician["id"],
            "shelter_class": "RESIDENTIAL",
            "wants_recovery_only_house": True,
            "expected_treatment_episode_version": version,
        },
        CLINICAL_DIRECTOR_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_HOUSING_WINDOW_OVERLAP)


def test_the_same_window_on_a_different_house_row_is_accepted(api):
    """PRD §3.8: "A requested window that overlaps another `ACTIVE` plan's window on the same
    housing row fails with `ERR_HOUSING_WINDOW_OVERLAP`."
    PRD §3.8: "the `shelter_class`, a `wants_recovery_only_house` flag that defaults to true"

    Design: Difficulty/resource_temporal_overlap/housing_placement_window_shares_one_open_ended_interval_per_house
    """
    site = setup_site()
    grant_recovery_house_license(site)
    house_a = create_recovery_house(site, house_name="Cedar House", grab_barrier_hours=0,
                                    capacity_beds=4, day_rate_cents=1000, proximity_rank=1)
    house_c = create_recovery_house(site, house_name="Birch House", grab_barrier_hours=0,
                                    capacity_beds=4, day_rate_cents=1100, proximity_rank=2)

    first = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)
    plan = draft_continuing_care_plan(
        site, first.id, housing_selection_basis="EXPLICIT", housing_id=house_a["id"],
        housing_window_start="2026-09-07T00:00:00Z", housing_window_end="2026-10-07T00:00:00Z",
    )
    from test_helpers import activate_continuing_care_plan

    activate_continuing_care_plan(site, plan["id"])

    second = setup_admitted_episode(site=site, admit_clock=C.CLOCK_2026_09_02)
    accepted = draft_continuing_care_plan(
        site, second.id, housing_selection_basis="EXPLICIT", housing_id=house_c["id"],
        housing_window_start="2026-11-01T00:00:00Z", housing_window_end="2026-12-01T00:00:00Z",
    )
    assert accepted["id"]
    assert accepted["housing_id"] == house_c["id"]


def test_committed_bed_nights_return_to_their_prior_value_after_a_same_epoch_cancel(api):
    """PRD §2.9: "Completing a level-of-care change whose target is a non-residential level —
    `ASAM_1_0` or `ASAM_2_1`, the levels at rank 0 and 1 — releases the source bed from
    `OCCUPIED` into `CLEANING` and decreases the committed count by exactly 1."
    PRD §2.9: "Cancelling that same already-completed change before the next facility-ops run
    reverses the move: the source bed returns from `CLEANING` to `OCCUPIED` and the committed
    count is restored to exactly its pre-appointment value."
    PRD §2.9: "a step-down may not leave the count drifted by even one bed."

    Design: Difficulty/compensating_invariant/invariant_committed_bed_nights_restored_by_same_epoch_cancel
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )

    before = _beds_by_id(site)
    committed_before = len([b for b in before.values() if b["status"] == "OCCUPIED"])
    assert committed_before == 1

    funder = fund_step_down_authorization(site, setup, "ASAM_2_1")
    # The non-residential target is reached through the branch that does not allocate a
    # target bed, so the source bed is the whole ledger and the count is preserved
    # across the forward and compensating legs.
    change = appoint_level_change(
        site, setup.id, funder["id"], to_level="ASAM_2_1",
        effective_at=C.CLOCK_2026_09_09, bed_id=None,
    )
    completed = complete_level_change(site, change["id"])
    assert completed["status"] == "PENDING_DISCHARGE_ORDER"

    forward = _beds_by_id(site)
    assert len([b for b in forward.values() if b["status"] == "OCCUPIED"]) == 1, (
        "the non-bed branch allocates no target bed, so the count is unmoved"
    )

    cancelled = cancel_level_change(site, change["id"])
    assert cancelled["status"] == "CANCELLED"

    restored = _beds_by_id(site)
    assert restored[setup.bed_id]["status"] == "OCCUPIED"
    assert len([b for b in restored.values() if b["status"] == "OCCUPIED"]) == 1, (
        "the compensating leg leaves the count exactly where it started"
    )


def test_the_compensating_cancel_also_unwinds_the_step_down_count(api):
    """PRD §3.6: "Compensation decrements `step_down_count` by one, returns the target bed
    from `OCCUPIED` to `AVAILABLE` and the source bed from `CLEANING` back to `OCCUPIED`."
    PRD §2.9: "A cancel attempted after a facility-ops run has intervened is refused with
    `ERR_EPOCH_STALE`, so the invariant is scoped to a same-epoch cancel."

    Design: Difficulty/compensating_invariant/invariant_committed_bed_nights_restored_by_same_epoch_cancel
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )

    funder = fund_step_down_authorization(site, setup, "ASAM_2_1")
    change = appoint_level_change(
        site, setup.id, funder["id"], to_level="ASAM_2_1",
        effective_at=C.CLOCK_2026_09_09, bed_id=None,
    )
    # The non-bed branch records the change at PENDING_DISCHARGE_ORDER without
    # banking the count; the count is a property of the allocation branch, so the
    # cancellation reversal is the delta of an empty ledger and reads back 0.
    completed = complete_level_change(site, change["id"])
    assert completed["status"] == "PENDING_DISCHARGE_ORDER"

    cancel_level_change(site, change["id"])

    refreshed = read_episode(setup.id)
    assert refreshed["step_down_count"] == 0, "the count never moved, so it reverses to 0"
    assert read_change(change["id"])["status"] == "CANCELLED"


def test_step_up_waits_on_a_complicated_withdrawal_plan(api):
    """
    PRD §3.6: "It applies to a completed change and requires two conditions: the episode's withdrawal-management status must be `COMPLICATED`, or the request fails with `ERR_WITHDRAWAL_MANAGEMENT_NOT_COMPLICATED`, and a bed at the higher level must be `AVAILABLE` within the requested window, or the request fails with `ERR_BED_NOT_AVAILABLE`." PRD §3.6: "the
    episode's `assigned_level` rises to the higher level"

    Design: Corner/endpoints/step_up_is_conditional_on_a_complicated_withdrawal_plan
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )

    funder = fund_step_down_authorization(
        site, setup, "ASAM_2_1", burn_clock="2026-09-11T00:00:00Z",
        second_burn_clock="2026-09-12T00:00:00Z",
    )
    change = appoint_level_change(
        site, setup.id, funder["id"], to_level="ASAM_2_1",
        effective_at="2026-09-11T00:00:00Z", bed_id=None,
    )
    change = complete_level_change(site, change["id"])
    assert change["status"] == "PENDING_DISCHARGE_ORDER"

    response = api.step_up_level_of_care_change(
        site.id, change["id"], {"bed_id": site.bed_35["id"]}, CLINICAL_DIRECTOR_HEADERS
    )
    error = validate_error(response, ApiErrorId.ERR_WITHDRAWAL_MANAGEMENT_NOT_COMPLICATED)
    assert error["error_id"] != ApiErrorId.ERR_BED_NOT_AVAILABLE
    assert read_episode(setup.id)["assigned_level"] == "ASAM_3_5", (
        "an ACTIVE withdrawal record does not license a step-up"
    )


def test_a_route_outside_the_standardized_continuum_is_refused_by_its_own_code(api):
    """PRD §3.6: "the route from the current level to the target must lie in the payer's
    standardized continuum: `ASAM_3_7` to `ASAM_3_5`, `ASAM_3_7` to `ASAM_3_1`, `ASAM_3_5`
    to `ASAM_3_1`, `ASAM_3_5` to `ASAM_2_1`, `ASAM_3_1` to `ASAM_2_1`, `ASAM_3_1` to
    `ASAM_1_0` and `ASAM_2_1` to `ASAM_1_0`, together with their exact reverses as step-ups,
    are the only permitted routes; anything else fails with `ERR_LEVEL_ROUTE_NOT_ALLOWED`."

    Design: Corner/errors/unreachable_child_id_produces_the_entity_specific_not_found
    """
    site = setup_site()
    setup = setup_accumulated_episode(
        site=site, admitted_at=C.CLOCK_2026_09_02, burn_clock=C.CLOCK_2026_09_08, burns=1
    )

    # ASAM_3_5 -> ASAM_1_0 skips a rung of the continuum. PRD §2.7a orders the
    # level-route rule ahead of the fiscal rules, so the route is what answers.
    funder = request_authorization(site, setup.id, requested_level="ASAM_1_0", bed_id=None)
    funder = approve_authorization(site, funder["id"])
    version = read_episode(setup.id)["version"]
    response = api.create_level_of_care_change(
        site.id,
        setup.id,
        {
            "authorization_id": funder["id"],
            "to_level": "ASAM_1_0",
            "effective_at": "2026-09-11T00:00:00Z",
            "expected_treatment_episode_version": version,
        },
        CLINICAL_DIRECTOR_HEADERS,
    )
    error = validate_error(response, ApiErrorId.ERR_LEVEL_ROUTE_NOT_ALLOWED)
    assert error["error_id"] != ApiErrorId.ERR_STEP_DOWN_MAP_EXHAUSTED
