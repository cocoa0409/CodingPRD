"""Difficulty coverage (queue A): the digitization priority's demand-weighted
canonical formula — per-input min() caps and the conditional DECLASSIFIED
bonus — against the age-weighted alternative reading."""

import test_helpers as th


def _accession_described_collection(api, agency, schedule, cutoff, units=20):
    transfer = th.create_validated_transfer(
        agency, schedule, unit_count=units, records_cutoff_date=cutoff,
        linear_feet=5.0,
    )
    collection = th.read_collection(th.accession_transfer(transfer)["collection_id"])
    collection = th.begin_processing(collection)
    return th.describe_collection(collection)


def _two_age_collections():
    """Collection A cutoff 1996-03-15 (age 30) and B cutoff 2001-03-15 (age
    25) under one schedule; zero demand counters on both."""
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(
        agency, schedule_number="SCH-DOJ-010", title="Program Subject Files"
    )
    return agency, schedule


def test_digitization_priority_weighting_divergence(api):
    """PRD §3.4: "It awards 2 points per whole year of records age, counting
    at most 50 years; plus 3 points per fulfilled pull request against the
    collection, counting at most 20 pulls; plus 5 points per FOIA release the
    collection has had, counting at most 10 releases; plus 1 point per 50
    fulfilled reproduction pages, where the page count is capped at 500 before
    being divided by 50 and rounded down; plus a bonus of 25 points when the
    collection's `declass_outcome` is `DECLASSIFIED`."
    PRD §3.4: "The digitization queue itself is a computed read. It lists
    exactly the collections whose `digitization_status` is `QUEUED`, ordered by
    `digitization_priority` descending, then by `records_cutoff_date` ascending
    so that older records come first on a tie, then by `created_at` ascending
    as the final tie-break — a collection's `id` is never used for ordering."

    Design: Difficulty/dual_variant_calc/digitization_priority_weighting_divergence
    """
    agency, schedule = _two_age_collections()
    col_a = _accession_described_collection(api, agency, schedule,
                                            "1996-03-15T00:00:00Z")
    col_b = _accession_described_collection(api, agency, schedule,
                                            "2001-03-15T00:00:00Z")

    enqueued_a = th.enqueue_digitization(col_a)
    enqueued_b = th.enqueue_digitization(col_b)
    # Canonical demand-weighted reading: 2 * min(age, 50) with zero demand.
    assert enqueued_a["digitization_priority"] == 60
    assert enqueued_a["digitization_priority"] != 150  # age-weighted reading
    assert enqueued_b["digitization_priority"] == 50
    assert enqueued_b["digitization_priority"] != 125

    data, _ = th.validate_paginated(
        api.get_digitization_queue(
            headers=th.TEST_USERS["processing_archivist_headers"]
        )
    )
    assert [row["id"] for row in data] == [col_a["id"], col_b["id"]]


def test_digitization_priority_weighting_snapshot_persisted(api):
    """PRD §3.4: "Enqueueing moves the digitization dimension to `QUEUED` and
    stamps `digitization_priority` with a snapshot of the demand-weighted
    priority score."
    PRD §3.4: "All inputs come from the collection's own fields —
    `records_cutoff_date` for age, the demand counters `pull_count_total`,
    `repro_pages_fulfilled`, and `foia_release_count`, and `declass_outcome` —
    evaluated against the logical clock."

    Design: Difficulty/dual_variant_calc/digitization_priority_weighting_divergence
    """
    agency, schedule = _two_age_collections()
    col_a = _accession_described_collection(api, agency, schedule,
                                            "1996-03-15T00:00:00Z")
    col_b = _accession_described_collection(api, agency, schedule,
                                            "2001-03-15T00:00:00Z")
    th.enqueue_digitization(col_a)
    th.enqueue_digitization(col_b)

    # The snapshot is stored on the collection row, not just the queue read.
    stored_a = th.read_collection(col_a["id"])
    stored_b = th.read_collection(col_b["id"])
    assert stored_a["digitization_status"] == "QUEUED"
    assert stored_a["digitization_priority"] == 60
    assert stored_a["digitization_priority"] == th.expected_digitization_priority(
        th.STARTUP_CLOCK_UTC, "1996-03-15T00:00:00Z"
    )
    assert stored_b["digitization_priority"] == 50

    _, meta = th.validate_paginated(
        api.get_digitization_queue(
            headers=th.TEST_USERS["processing_archivist_headers"]
        )
    )
    assert meta["total_count"] == 2


def test_digitization_priority_caps_and_conditional_bonus(api):
    """PRD §3.4: "It awards 2 points per whole year of records age, counting
    at most 50 years; plus 3 points per fulfilled pull request against the
    collection, counting at most 20 pulls; plus 5 points per FOIA release the
    collection has had, counting at most 10 releases; plus 1 point per 50
    fulfilled reproduction pages, where the page count is capped at 500 before
    being divided by 50 and rounded down; plus a bonus of 25 points when the
    collection's `declass_outcome` is `DECLASSIFIED`."
    PRD §3.5: "A `DECLASSIFIED` outcome clears the collection's
    `classification_level` to `NONE` and stamps `declass_outcome` as
    `DECLASSIFIED`."

    Design: Difficulty/combinatorial_formula/digitization_priority_caps_and_conditional_bonus
    """
    th.set_clock()
    agency = th.create_agency()

    # X: SECRET, cutoff 1956-03-15 (age 70 at the startup clock), declassified
    # by a completed SYSTEMATIC review, then described.
    schedule_x = th.create_approved_schedule(
        agency, schedule_number="SCH-DOJ-011", title="Intelligence Reports",
        classification_default="SECRET",
    )
    transfer_x = th.create_validated_transfer(
        agency, schedule_x, transfer_method="ELECTRONIC", unit_count=40,
        records_cutoff_date="1956-03-15T00:00:00Z",
    )
    collection_x = th.read_collection(
        th.accession_transfer(transfer_x)["collection_id"]
    )
    review = th.create_open_systematic_review(collection_x)
    review = th.begin_review(review)
    completed = th.complete_review(review, "DECLASSIFY")
    assert completed["outcome"] == "DECLASSIFIED"

    collection_x = th.read_collection(collection_x["id"])
    assert collection_x["classification_level"] == "NONE"
    assert collection_x["declass_outcome"] == "DECLASSIFIED"
    assert collection_x["restriction_posture"] == "PUBLIC"
    collection_x = th.begin_processing(collection_x)
    collection_x = th.describe_collection(collection_x)

    # Y: NONE, same 1956-03-15 cutoff, never declassified.
    schedule_y = th.create_approved_schedule(
        agency, schedule_number="SCH-DOJ-012", title="Open Administrative Files",
        classification_default="NONE",
    )
    collection_y = _accession_described_collection(
        api, agency, schedule_y, "1956-03-15T00:00:00Z", units=10
    )

    enqueued_x = th.enqueue_digitization(collection_x)
    enqueued_y = th.enqueue_digitization(collection_y)
    # Age term is capped: 2 * min(70, 50) = 100, not 140; only X gets the
    # conditional +25 DECLASSIFIED bonus.
    assert enqueued_x["digitization_priority"] == 125
    assert enqueued_x["digitization_priority"] != 165  # uncapped-age reading
    assert enqueued_y["digitization_priority"] == 100

    data, _ = th.validate_paginated(
        api.get_digitization_queue(
            headers=th.TEST_USERS["processing_archivist_headers"]
        )
    )
    assert [row["id"] for row in data] == [collection_x["id"], collection_y["id"]]


def test_digitization_priority_age_cap_binds_at_fifty(api):
    """PRD §3.4: "It awards 2 points per whole year of records age, counting
    at most 50 years"
    PRD §2.9: "Age in years is computed from the logical clock and a
    `records_cutoff_date` as follows: take the clock's year minus the cutoff's
    year, then subtract one if the clock's month-and-day has not yet reached
    the cutoff's month-and-day — that is, the anniversary of the cutoff must
    already have occurred in the clock's year for the year to count."

    Design: Difficulty/combinatorial_formula/digitization_priority_caps_and_conditional_bonus
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(
        agency, schedule_number="SCH-DOJ-013", title="Aged Series"
    )
    # Ages at the startup clock: 51 (Z), exactly 50 (V), 49 (W).  The 50-year
    # cap makes Z and V score identically despite Z being a year older.
    col_z = _accession_described_collection(api, agency, schedule,
                                            "1975-03-15T00:00:00Z", units=10)
    col_v = _accession_described_collection(api, agency, schedule,
                                            "1976-03-15T00:00:00Z", units=10)
    col_w = _accession_described_collection(api, agency, schedule,
                                            "1977-03-15T00:00:00Z", units=10)

    enqueued_z = th.enqueue_digitization(col_z)
    enqueued_v = th.enqueue_digitization(col_v)
    enqueued_w = th.enqueue_digitization(col_w)
    assert enqueued_z["digitization_priority"] == 100  # min(51, 50) * 2
    assert enqueued_v["digitization_priority"] == 100  # min(50, 50) * 2
    assert enqueued_w["digitization_priority"] == 98   # min(49, 50) * 2

    data, _ = th.validate_paginated(
        api.get_digitization_queue(
            headers=th.TEST_USERS["processing_archivist_headers"]
        )
    )
    # Tied scores fall to records_cutoff_date ascending: older records first.
    assert [row["id"] for row in data] == [col_z["id"], col_v["id"], col_w["id"]]
