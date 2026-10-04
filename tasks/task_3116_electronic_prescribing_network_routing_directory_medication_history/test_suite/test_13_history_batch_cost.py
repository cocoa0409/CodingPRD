"""Medication history aggregation: deduplication and the batch query fee's per-record cap.

The batch partitions its live certified-source records by dedupe key, ranks each partition,
and charges a base fee plus a per-record term that saturates once the source count reaches the
cap.
"""
import datetime

from test_helpers import (
    set_clock,
    setup_certified_pharmacy,
    create_patient,
    grant_consent,
    add_history_record,
    open_history_batch,
    aggregate_batch,
    reload_batch,
    reload_history_record,
    reload_patient,
    batch_cost_cents,
    RECORD_FEE_CAP,
)


def _history_scenario(record_specs):
    """A CERTIFIED pharmacy with a MED_HISTORY endpoint, a patient holding an ACTIVE
    MEDICATION_HISTORY consent of 365 days, and the supplied history records."""
    set_clock()
    pharmacy, _ = setup_certified_pharmacy(
        endpoint_specs=[{"service_set": "MED_HISTORY", "endpoint_role": "RECEIVER",
                         "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
                         "message_standard": "NCPDP_SCRIPT_2022011"}]
    )
    patient = create_patient(full_name="Perla Vance")
    grant_consent(patient["id"], scope="MEDICATION_HISTORY", duration_days=365)
    records = [add_history_record(patient["id"], pharmacy["id"], **spec) for spec in record_specs]
    batch = open_history_batch(patient["id"], pharmacy["id"])
    return pharmacy, patient, records, batch


def _distinct_key_records(count):
    """`count` live pharmacy-fill records, each with a distinct dedupe key because no two
    share a fill date."""
    base = datetime.date(2026, 6, 1)
    specs = []
    for offset in range(count):
        fill = (base + datetime.timedelta(days=offset)).isoformat() + "T00:00:00Z"
        specs.append({"drug_ndc": "00093314905", "fill_date": fill,
                      "days_supply": 30, "quantity": 60})
    return specs


def test_settlement_dedupes_on_quantity_within_a_shared_key(api):
    """PRD §3.8: "The batch then stamps `record_count` as the number of partitions that
    survived, `superseded_count` as the number of input rows minus the number of partitions,
    and `source_record_count` as the number of input rows."
    PRD §3.8: "Settlement also forces the patient aggregate and advances a payer's deductible.
    The patient's `history_record_count` is recomputed over records whose `retracted_at` is
    null"

    Design: Difficulty/boundary_precision_check/medication_history_batch_cost_cap_boundary_at_forty_records
    """
    pharmacy, patient, records, batch = _history_scenario([
        {"drug_ndc": "00093314905", "fill_date": "2026-06-01T00:00:00Z",
         "days_supply": 30, "quantity": 60},
        {"drug_ndc": "00093314905", "fill_date": "2026-06-01T00:00:00Z",
         "days_supply": 30, "quantity": 30},
        {"source_type": "PAYER_CLAIM", "drug_ndc": "00093314906",
         "fill_date": "2026-07-01T00:00:00Z", "days_supply": 90, "quantity": 90},
    ])
    rec_a, rec_b, rec_c = records

    settled = aggregate_batch(batch["id"])
    assert settled["source_record_count"] == 3
    assert settled["record_count"] == 2
    assert settled["superseded_count"] == 1

    # The larger quantity wins the shared key, so the 60-unit row survives and 30 is dropped.
    assert reload_history_record(rec_a["id"])["is_superseded"] is False
    assert reload_history_record(rec_b["id"])["is_superseded"] is True
    # A distinct dedupe key always wins its own partition.
    assert reload_history_record(rec_c["id"])["is_superseded"] is False

    assert reload_patient(patient["id"])["history_record_count"] == 3


def test_batch_cost_before_and_at_the_per_record_cap(api):
    """PRD §3.8: "The batch's own cost is computed under the medication-history fee schedule
    as a base charge of 25 cents plus 10 cents for each source record, where the per-record
    term counts at most 40 records."
    PRD §3.8: "a batch of 40, 41, or 500 source records all cost exactly 425 cents because the
    per-record term saturates at 400."

    Design: Difficulty/boundary_precision_check/medication_history_batch_cost_cap_boundary_at_forty_records
    """
    pharmacy, patient, records, batch = _history_scenario(_distinct_key_records(39))

    assert batch_cost_cents(RECORD_FEE_CAP - 1) == 415
    assert batch_cost_cents(RECORD_FEE_CAP) == 425
    assert batch_cost_cents(RECORD_FEE_CAP + 1) == 425

    settled = aggregate_batch(batch["id"])
    assert settled["source_record_count"] == RECORD_FEE_CAP - 1
    assert settled["batch_cost_cents"] == 415
    assert settled["subscription_generation"] == 1

    # One more live record pushes the source count onto the cap, and the re-run re-prices the
    # batch in place.
    add_history_record(patient["id"], pharmacy["id"], **{
        "drug_ndc": "00093314905",
        "fill_date": (datetime.date(2026, 6, 1) + datetime.timedelta(days=39)).isoformat()
        + "T00:00:00Z",
        "days_supply": 30, "quantity": 60,
    })
    re_run = aggregate_batch(batch["id"])
    assert re_run["source_record_count"] == RECORD_FEE_CAP
    assert re_run["batch_cost_cents"] == 425
    assert re_run["batch_cost_cents"] == batch_cost_cents(RECORD_FEE_CAP)
    assert re_run["subscription_generation"] == 2
    assert reload_batch(batch["id"])["batch_cost_cents"] == 425