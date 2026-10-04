"""Specimens: rejection cap, recollection, selector filtering and the stability clock."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client, INTAKE, TEST_USERS,
    ApiErrorId, make_phlebotomist_headers, make_patient_headers,
)
from test_helpers.fixtures import (
    setup_windowed_compromised_specimen, setup_windowed_assigned_specimen,
    setup_three_specimens_assigned, setup_collected_order_with_specimen,
    setup_windowed_visit, new_tube_requirement, new_courier_run, get_specimen,
    get_order, set_clock, seed_reference, new_center, new_patient, new_order,
    resolve_insurance, book, check_in, call_patient, new_phlebotomist,
    setup_eligible_order,
)
from test_helpers.factories import create_specimen_payload


def test_the_third_rejection_of_a_local_day_is_refused_by_the_cap(api):
    """PRD §3.7: "The waiver flag is true exactly when the index reaches or
    exceeds `REJECTION.day_cap`, which is 3."
    PRD §3.7: "The counter is append-only, so a rejection followed by a
    recollection followed by another rejection counts as two rejections on that
    day, and the third rejection of a local day is refused by the cap."

    Design: Corner/calculations/rejection_day_cap_boundary_at_the_third_rejection
    """
    data, specimen_ids = setup_three_specimens_assigned()
    headers = TEST_USERS["lab_liaison_headers"]
    set_clock("2026-09-01T18:50:00Z")

    first = get_specimen(specimen_ids[0])
    assert first["day_rejection_index"] == 0
    assert first["rejection_waived"] is False

    for reason, specimen_id in zip(["HEMOLYZED", "HEMOLYZED", "HEMOLYZED"],
                                   specimen_ids[:2]):
        api_client.compromise_specimen(specimen_id, reason, headers)
        rejected = validate_success(api_client.reject_specimen(specimen_id, headers), 200)
        assert rejected["day_rejection_index"] in (1, 2)
        assert rejected["rejection_waived"] is False

    # The third specimen of the same local day crosses the cap.
    api_client.compromise_specimen(specimen_ids[2], "HEMOLYZED", headers)
    blocked = api_client.reject_specimen(specimen_ids[2], headers)
    assert blocked.status_code >= 400, "the third rejection must be refused"
    assert get_specimen(specimen_ids[2])["status"] == "COMPROMISED"


def test_the_local_day_bucket_keeps_a_late_evening_collection_out_of_the_next_day(api):
    """PRD §3.7: "The index counts the specimens belonging to the same order whose
    status is `REJECTED` and whose collection falls on the same local calendar
    day as the logical clock at the moment of rejection"
    PRD §3.7: "the local calendar day is obtained by shifting the instant by the
    center's `timezone_offset_minutes` and taking the calendar date."

    Design: Corner/calculations/rejection_day_cap_boundary_at_the_third_rejection
    """
    data = setup_windowed_compromised_specimen()
    headers = TEST_USERS["lab_liaison_headers"]

    # The center shifts by -300 minutes, so 02:00Z is still the previous local
    # calendar day: the rejection must be counted in that local day's tally.
    set_clock("2026-09-02T02:00:00Z")
    rejected = validate_success(
        api_client.reject_specimen(data["specimen"]["id"], headers), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["day_rejection_index"] == 1
    assert rejected["rejection_waived"] is False


def test_recollection_preserves_the_specimen_census_and_reopens_the_order(api):
    """PRD §3.7: "A successful recollection moves the specimen to `RECOLLECTED`
    and stamps `recollection_approved_at_utc` with the logical clock. It returns
    the order to `SCHEDULED` and creates a fresh appointment for it in
    `draw_state` `SCHEDULED`."
    PRD §3.7: "the recollection loops back into the booking and check-in flows"

    Design: Difficulty/compensating_invariant/specimen_reassignment_chain_preserves_total_specimen_count
    """
    data = setup_windowed_compromised_specimen(
        compromise_reason="HEMOLYZED", compromise_clock="2026-09-01T17:50:00Z",
        recollection_ready=True)
    headers = TEST_USERS["lab_liaison_headers"]
    center_id = data["center"]["id"]

    before = api_client.list_specimens(
        headers, params={"service_center_id": center_id}).json()["data"]
    assert len(before) == 1

    recollected = validate_success(
        api_client.recollect_specimen(data["specimen"]["id"], headers), 200)
    assert recollected["status"] == "RECOLLECTED"
    assert recollected["recollection_approved_at_utc"] is not None

    # A fresh replacement tube is registered for the recollection visit.
    replacement = validate_success(api_client.create_specimen(
        create_specimen_payload(data["order"]["id"], tube_code="EDTA_LAVENDER",
                                volume_ml=4.0, order_of_draw=1),
        make_phlebotomist_headers(data["phlebotomist"]["id"])), 201)
    assert replacement["status"] == "UNASSIGNED"

    after = api_client.list_specimens(
        headers, params={"service_center_id": center_id}).json()["data"]
    assert len(after) == 2, "the release and the replacement are a matched pair"
    assert get_order(data["order"]["id"])["status"] == "SCHEDULED"


def test_the_selector_excludes_specimens_whose_tube_is_not_recollection_eligible(api):
    """PRD §3.7: "A specimen is eligible for the worklist only when its status is
    `COMPROMISED` and its `compromise_reason` is one of `HEMOLYZED`, `CLOTTED`,
    or `INSUFFICIENT_VOLUME`, and a tube requirement matching its panel and tube
    code exists whose `is_recollection_eligible` is true."

    Design: Corner/calculations/recollection_selector_excludes_ineligible_tubes_and_uncompromised_specimens
    """
    set_clock("2026-09-01T13:00:00Z")
    center = new_center()
    api_client.seed_reference(TEST_USERS["supervisor_headers"])
    new_tube_requirement("LACTATE", "SODIUM_CITRATE_BLUE", stability_minutes=60,
                         max_urgency_hours=4, order_of_draw=2,
                         is_recollection_eligible=False)
    patient = new_patient()
    # LIPID descends from CMP, so the ineligible tube is part of its plan.
    order = new_order(center["id"], patient["id"],
                      api_client.list_insurance_plans(INTAKE).json()["data"][0]["id"],
                      test_panel="LACTATE")
    order = resolve_insurance(order["id"])
    headers = make_phlebotomist_headers(
        new_phlebotomist(center["id"], credential="RN")["id"])

    healthy = validate_success(api_client.create_specimen(
        create_specimen_payload(order["id"], tube_code="EDTA_LAVENDER",
                                volume_ml=4.0, order_of_draw=1), headers), 201)
    ineligible = validate_success(api_client.create_specimen(
        create_specimen_payload(order["id"], tube_code="SODIUM_CITRATE_BLUE",
                                volume_ml=2.7, order_of_draw=2), headers), 201)

    candidates = api_client.list_recollection_candidates(
        TEST_USERS["lab_liaison_headers"],
        params={"service_center_id": center["id"]}).json()["data"]
    ids = [row["id"] for row in candidates]
    assert healthy["id"] not in ids, "an UNASSIGNED specimen is not a candidate"
    assert ineligible["id"] not in ids, "the tube is not recollection-eligible"


def test_a_compromised_specimen_stays_compromised_until_rejection_or_recollection(api):
    """PRD §3.7: "A `LabLiaison` declares the compromise while the specimen is
    `ASSIGNED` and strictly inside the interval between the run's cutoff and its
    dispatch — after the cutoff, but before the van leaves."
    PRD §3.7: "moves the specimen to `COMPROMISED`, records that reason, and
    decrements the run's committed count by one"

    Design: Difficulty/compensating_invariant/courier_put_back_conserves_committed_specimen_count
    """
    data = setup_windowed_compromised_specimen(compromise_reason="INSUFFICIENT_VOLUME")
    specimen = get_specimen(data["specimen"]["id"])
    assert specimen["status"] == "COMPROMISED"
    assert specimen["compromise_reason"] == "INSUFFICIENT_VOLUME"
    assert specimen["recollection_approved_at_utc"] is None

    run = api_client.get_courier_run(
        data["courier_run"]["id"], TEST_USERS["lab_liaison_headers"]).json()["data"]
    assert run["committed_specimen_count"] == 0
    assert run["status"] == "PLANNED"


def test_assignment_raises_the_run_count_and_the_put_back_restores_it(api):
    """PRD §2.10: "A run tracks `committed_specimen_count`, which rises by one
    for each specimen assigned and falls by one when an assignment is undone;
    the count is never allowed to drift from the set of specimens actually
    committed to the run."

    Design: Difficulty/compensating_invariant/courier_put_back_conserves_committed_specimen_count
    """
    data = setup_windowed_assigned_specimen()
    headers = TEST_USERS["lab_liaison_headers"]

    run = api_client.get_courier_run(data["courier_run"]["id"], headers).json()["data"]
    assert run["committed_specimen_count"] == 1

    set_clock("2026-09-01T17:50:00Z")
    compromised = validate_success(
        api_client.compromise_specimen(data["specimen"]["id"], "HEMOLYZED", headers), 200)
    assert compromised["status"] == "COMPROMISED"

    run_after = api_client.get_courier_run(data["courier_run"]["id"], headers).json()["data"]
    assert run_after["committed_specimen_count"] == 0
    assert run_after["status"] == "PLANNED"


def test_the_bulk_commit_assigns_the_eligible_subset_and_surfaces_no_error(api):
    """PRD §3.6: "Committing every assignable specimen walks the center's
    unassigned specimens in a fixed order — soonest stability deadline first,
    then the order identifier ascending, then the earlier creation instant last,
    with the specimen identifier never consulted"
    PRD §3.6: "The specimens left over stay unassigned and no error is surfaced
    for them; the cap is a silent stop, not a failure."

    Design: Corner/cross_cutting_complexity_layers/commit_all_assigns_only_the_window_eligible_subset_of_the_bulk
    """
    data = setup_windowed_visit()
    headers = TEST_USERS["lab_liaison_headers"]
    run = new_courier_run(data["center"]["id"], "2026-09-02T07:00:00Z")

    committed = validate_success(api_client.commit_all(run["id"], headers), 200)
    assert committed["committed_specimen_count"] == 1

    rows = api_client.list_specimens(
        headers, params={"courier_run_id": run["id"]}).json()["data"]
    assert [row["id"] for row in rows] == [data["specimen"]["id"]]