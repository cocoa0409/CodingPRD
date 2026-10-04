"""Discharge, the deferred release cycle, continuing care and alumni follow-up."""

import pytest

from test_helpers import (
    C,
    CLINICAL_DIRECTOR_HEADERS,
    ApiErrorId,
    activate_continuing_care_plan,
    complete_treatment,
    create_recovery_house,
    discharge_episode,
    draft_continuing_care_plan,
    file_ad_hoc_contact,
    grant_recovery_house_license,
    list_beds,
    list_episode_changes,
    list_episode_contacts,
    read_change,
    read_episode,
    record_alumni_outcome,
    run_ops,
    set_clock,
    setup_curriculum_episode,
    setup_site,
    validate_error,
)


def _complete_at(site, setup, clock=C.CLOCK_2026_09_07):
    set_clock(clock)
    complete_treatment(site, setup.id)
    setup.refresh()
    return setup


def test_a_discharge_without_an_active_plan_defers_the_release_onto_a_change_row(api):
    """
    PRD §3.7: "When a `COMPLETED` episode is discharged with no `ACTIVE` continuing-care plan,
    the call is refused with `ERR_CONTINUING_CARE_PLAN_REQUIRED` and the episode performs no
    mutation at all." PRD §3.7: "Instead, the release is deferred: a level-of-care change row is
    recorded at status `AWAITING_DISCHARGE`, with its `bed_id` set to the episode's current bed,
    its `from_level` set to the episode's `assigned_level` and its `to_level` set to the first
    entry of the payer's step-down coverage map below that level, and its `retry_available_at`
    set to the logical now plus 24 hours."

    Design: Difficulty/non_linear_state_machine/level_change_ledger_release_reocupy_cycle
    """
    site = setup_site()
    setup = _complete_at(site, setup_curriculum_episode(
        site=site, attended_sessions=14, clock="2026-09-02T00:00:00Z"
    ))

    response = api.discharge_episode(site.id, setup.id, {}, CLINICAL_DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_CONTINUING_CARE_PLAN_REQUIRED)
    assert read_episode(setup.id)["clinical_status"] == "COMPLETED", (
        "the refused call performs no episode mutation"
    )

    changes, _ = list_episode_changes(site.id, setup.id)
    deferred = [c for c in changes if c["status"] == "AWAITING_DISCHARGE"]
    assert len(deferred) == 1
    row = deferred[0]
    assert row["bed_id"] == setup.bed_id
    assert row["from_level"] == "ASAM_3_5"
    assert row["to_level"] == "ASAM_3_1", "the first entry of the payer's coverage map below the level"
    assert row["retry_available_at"] == C.CLOCK_2026_09_08_ISO, "the logical now plus 24 hours"


def test_the_deferred_change_cycles_its_bed_without_ever_completing(api):
    """
    PRD §3.7: "That row then cycles through the ops run: at the run where its
    `retry_available_at` has arrived it holds its bed in `CLEANING` for the run instant, and on
    the following run the bed returns to `AVAILABLE` and `retry_available_at` advances by a
    further 24 hours, so the row keeps cycling without ever completing while the continuing-care
    gap persists." PRD §3.5: "A change sitting at `AWAITING_DISCHARGE` whose bed is still
    `CLEANING` returns that bed to `AVAILABLE` and advances the change's `retry_available_at` by
    24 hours, leaving the row in `AWAITING_DISCHARGE` so that the next run may hold the bed
    again."

    Design: Difficulty/non_linear_state_machine/level_change_ledger_release_reocupy_cycle
    """
    site = setup_site()
    setup = _complete_at(site, setup_curriculum_episode(
        site=site, attended_sessions=14, clock="2026-09-02T00:00:00Z"
    ))
    api.discharge_episode(site.id, setup.id, {}, CLINICAL_DIRECTOR_HEADERS)

    changes, _ = list_episode_changes(site.id, setup.id)
    row = [c for c in changes if c["status"] == "AWAITING_DISCHARGE"][0]
    bed_id = row["bed_id"]

    set_clock("2026-09-08T00:00:00Z")
    run_ops(site.id)
    beds = {b["id"]: b for b in list_beds(site.id)[0]}
    assert beds[bed_id]["status"] == "CLEANING", "stage seven holds the bed for the run instant"

    set_clock("2026-09-09T00:00:00Z")
    run_ops(site.id)
    beds = {b["id"]: b for b in list_beds(site.id)[0]}
    assert beds[bed_id]["status"] == "AVAILABLE", "the next run releases it again"

    row = read_change(row["id"])
    assert row["status"] == "AWAITING_DISCHARGE", "it never completes while the gap persists"
    assert row["retry_available_at"] == "2026-09-10T00:00:00.000Z", "advanced by a further 24 hours"


def test_a_second_discharge_of_a_discharged_episode_is_refused(api):
    """PRD §3.7: "The episode moves to `DISCHARGED`, which is terminal"
    PRD §3.7: "an episode in any other state is refused with `ERR_EPISODE_NOT_COMPLETED`, and
    one already `DISCHARGED` is refused with `ERR_ALREADY_DISCHARGED`."
    PRD §3.8: "Alumni contacts are created at discharge, not at admission."

    Design: Corner/state_machines/episode_discharge_from_already_discharged_returns_already_discharged
    """
    site = setup_site()
    grant_recovery_house_license(site)
    create_recovery_house(site, capacity_beds=4)
    setup = _complete_at(site, setup_curriculum_episode(
        site=site, attended_sessions=14, clock="2026-09-02T00:00:00Z"
    ))
    plan = draft_continuing_care_plan(site, setup.id)
    activate_continuing_care_plan(site, plan["id"])

    discharged = discharge_episode(site, setup.id)
    assert discharged["clinical_status"] == "DISCHARGED"
    first_contacts, _ = list_episode_contacts(site.id, setup.id)
    assert len(first_contacts) == 2

    response = api.discharge_episode(site.id, setup.id, {}, CLINICAL_DIRECTOR_HEADERS)
    validate_error(response, ApiErrorId.ERR_ALREADY_DISCHARGED)

    assert read_episode(setup.id)["clinical_status"] == "DISCHARGED"
    second_contacts, _ = list_episode_contacts(site.id, setup.id)
    assert len(second_contacts) == 2, "the rejected call materialized no further contacts"


def test_a_second_outcome_on_a_filed_contact_is_refused(api):
    """PRD §3.8: "Recording against a contact that is not `PENDING` is refused with
    `ERR_CONTACT_NOT_PENDING`."
    PRD §3.8: "Recording stamps `record_filed_at`."

    Design: Corner/state_machines/alumni_contact_second_outcome_returns_contact_not_pending
    """
    site = setup_site()
    setup = setup_curriculum_episode(site=site, attended_sessions=14, clock="2026-09-02T00:00:00Z")
    contact = file_ad_hoc_contact(site, setup.id, "2026-10-01T00:00:00Z", 1)

    filed = record_alumni_outcome(site, contact["id"], outcome="REACHED")
    assert filed["outcome"] == "REACHED"

    from test_helpers import ALUMNI_COORDINATOR_HEADERS

    response = api.record_alumni_outcome(
        site.id, contact["id"], {"outcome": "DECLINED"}, ALUMNI_COORDINATOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_CONTACT_NOT_PENDING)

    rows, _ = list_episode_contacts(site.id, setup.id)
    stored = [r for r in rows if r["id"] == contact["id"]][0]
    assert stored["outcome"] == "REACHED", "the first outcome stands"
    assert stored["record_filed_at"] == filed["record_filed_at"]


def test_a_pending_contact_times_out_on_the_next_epoch(api):
    """PRD §3.5: "Stage six times out alumni contacts: a contact still `PENDING` whose
    `scheduled_for` instant is at or before the logical now becomes `NO_CONTACT`."
    PRD §3.8: "contacts that were never answered are moved to `NO_CONTACT` by the ops cycle
    when their `scheduled_for` instant passes."

    Design: Corner/cross_cutting_complexity_layers/deferred_alumni_contact_times_out_on_the_next_epoch
    """
    site = setup_site()
    setup = setup_curriculum_episode(site=site, attended_sessions=14, clock="2026-09-02T00:00:00Z")
    first = file_ad_hoc_contact(site, setup.id, C.CLOCK_2026_09_15, 1)
    second = file_ad_hoc_contact(site, setup.id, "2026-09-22T00:00:00Z", 2)

    set_clock(C.CLOCK_2026_09_15)
    run_ops(site.id)

    rows, _ = list_episode_contacts(site.id, setup.id)
    by_id = {r["id"]: r for r in rows}
    assert by_id[first["id"]]["outcome"] == "NO_CONTACT", (
        "a contact whose scheduled_for is exactly the logical now has passed"
    )
    assert by_id[second["id"]]["outcome"] == "PENDING", "one week later is still pending"

    filtered, _ = list_episode_contacts(site.id, setup.id, outcome="NO_CONTACT")
    assert len(filtered) == 1
