"""Compensating invariants: conserved ledgers returning to a prior value.

Covers the program's order-reconciliation balance and its credentialed-trainer
headcount.
"""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    get_program,
    create_patient_order_payload,
    create_credentialed_trainer_payload,
    setup_program_and_facility,
    setup_program_facility_department,
    get_staff,
    RECONCILER,
    CONVERSION,
    DIRECTOR,
    TRAINING,
    ANALYST,
)


# ===========================================================================
# r9_reconcile_backfill_pair_preserves_order_balance
# ===========================================================================

def test_reconciling_a_converted_order_credits_the_program_balance_by_one(api, director_headers, conversion_headers, reconciler_headers):
    """PRD §3.7: "The straightforward path applies when `paper_backfill_count` is
    0: reconciliation moves the order to `RECONCILED`, publishes the final
    charge, credits the program's `order_reconciliation_balance` by one."
    PRD §2.14: "The program's `order_reconciliation_balance` counts converted EHR
    orders reconciled minus paper order slips backfilled."

    Design: Difficulty/compensating_invariant/r9_reconcile_backfill_pair_preserves_order_balance
    """
    prog, fac = setup_program_and_facility()
    before = get_program(prog["id"], director_headers)
    assert before["order_reconciliation_balance"] == 0

    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-7001", order_type="LAB",
            encounter_utc="2026-08-29T00:00:00Z", legacy_charge_cents=10000,
        ),
        conversion_headers,
    ))
    reconciled = validate_success(api.reconcile_order(order["id"], reconciler_headers), 200)
    assert reconciled["clinical_state"] == "RECONCILED"

    after = get_program(prog["id"], director_headers)
    assert after["order_reconciliation_balance"] == 1, "a forward reconcile credits one unit"


def test_a_compensating_paper_backfill_returns_the_balance_to_its_start(api, director_headers, conversion_headers, reconciler_headers):
    """PRD §2.14: "A reconcile paired with a matching paper backfill must
    therefore leave the balance exactly where it started — the compensating slip
    gives back precisely the unit the reconciliation took."
    PRD §3.7: "Backfilling the paper slip — an `OrderReconciler` action — moves
    the order to `RECONCILED`, increments `paper_backfill_count` by one, and
    debits the program's `order_reconciliation_balance` by one."

    The matched pair leaves the balance exactly where it began.

    Design: Difficulty/compensating_invariant/r9_reconcile_backfill_pair_preserves_order_balance
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-7001", order_type="LAB",
            encounter_utc="2026-08-29T00:00:00Z", legacy_charge_cents=10000,
        ),
        conversion_headers,
    ))
    get_success_data(api.reconcile_order(order["id"], reconciler_headers))
    assert get_program(prog["id"], director_headers)["order_reconciliation_balance"] == 1

    backfilled = validate_success(api.backfill_paper_order(order["id"], reconciler_headers), 200)
    assert backfilled["paper_backfill_count"] == 1
    assert backfilled["clinical_state"] == "RECONCILED"

    after = get_program(prog["id"], director_headers)
    assert after["order_reconciliation_balance"] == 0, (
        "the compensating slip gives back exactly the unit the reconcile took"
    )


# ===========================================================================
# r9_trainer_certify_revoke_pair_preserves_net_trainer_count
# ===========================================================================

def test_certifying_two_trainer_records_raises_the_net_trainer_count(api, director_headers):
    """PRD §2.14: "The program's `net_trainer_count` counts credentialed-trainer
    rows currently in `CERTIFIED` status."
    PRD §3.4: "Certifying requires the observation floor of §2.13 and stamps
    `certified_utc` with the logical clock and `expires_utc` with the clock plus
    365 days."

    Design: Difficulty/compensating_invariant/r9_trainer_certify_revoke_pair_preserves_net_trainer_count
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        {
            "full_name": "Twin Certified", "staff_type": "NURSE",
            "primary_facility_id": fac["id"], "department_id": dept["id"],
            "hired_on": "2026-01-10T00:00:00Z",
        },
        TRAINING,
    ))
    trainer_a = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            staff["version"], application_code="CLN", certification_level="STANDARD",
            observation_hours=8,
        ),
        TRAINING,
    ))
    get_success_data(api_client.certify_trainer(trainer_a["id"], TRAINING))

    refreshed = get_staff(staff["id"])
    trainer_b = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            refreshed["version"], application_code="CLN-ADV", certification_level="ADVANCED",
            observation_hours=8,
        ),
        TRAINING,
    ))
    get_success_data(api_client.certify_trainer(trainer_b["id"], TRAINING))

    assert get_program(prog["id"], director_headers)["net_trainer_count"] == 2


def test_the_certify_revoke_pair_returns_the_headcount_to_zero(api, director_headers):
    """PRD §2.14: "certifying a trainer raises it and revoking that trainer lowers
    it by the same unit, so a certify/revoke pair restores the pre-pair value."
    PRD §3.4: "Revoking may be done from `CERTIFIED` and moves the record to the
    terminal `REVOKED`, refreshing the program's `net_trainer_count`."

    Design: Difficulty/compensating_invariant/r9_trainer_certify_revoke_pair_preserves_net_trainer_count
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        {
            "full_name": "Twin Certified", "staff_type": "NURSE",
            "primary_facility_id": fac["id"], "department_id": dept["id"],
            "hired_on": "2026-01-10T00:00:00Z",
        },
        TRAINING,
    ))
    trainer_a = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            staff["version"], application_code="CLN", certification_level="STANDARD",
            observation_hours=8,
        ),
        TRAINING,
    ))
    get_success_data(api_client.certify_trainer(trainer_a["id"], TRAINING))
    refreshed = get_staff(staff["id"])
    trainer_b = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            refreshed["version"], application_code="CLN-ADV", certification_level="ADVANCED",
            observation_hours=8,
        ),
        TRAINING,
    ))
    get_success_data(api_client.certify_trainer(trainer_b["id"], TRAINING))

    revoked_a = validate_success(api_client.revoke_trainer(trainer_a["id"], TRAINING), 200)
    revoked_b = validate_success(api_client.revoke_trainer(trainer_b["id"], TRAINING), 200)
    assert revoked_a["status"] == "REVOKED"
    assert revoked_b["status"] == "REVOKED"

    assert get_program(prog["id"], director_headers)["net_trainer_count"] == 0, (
        "two certifications minus two compensating revocations nets to the starting value"
    )