"""Endpoint-shaped behaviour: a computed read, a conditional action, a cross-reference
link and a single-field action endpoint.

The ledger summary is recomputed on every read rather than copied from the stored
aggregates, retirement is legal only inside the listed window of the registry axis, a
verification assignment validates both of its body-borne foreign keys independently, and
recording arrival on site moves the visit window without touching the opinion axis.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_QUANTIFICATION_RUN_NOT_FOUND,
    ERR_VERIFICATION_BODY_NOT_FOUND,
)
from test_helpers.assertions import assert_pct, assert_tonnes, assert_visit_day
from test_helpers.constants import (
    EVIDENCE_FARM_RECORD,
    ISSUANCE_ISSUED,
    METHOD_MODEL,
    OPINION_PENDING,
    PAYMENT_ACCRUED,
    PAYMENT_PAID,
    POOL_HEALTHY,
    REGISTRY_RETIRED,
    REGISTRY_UNLISTED,
    RUN_SUBMITTED,
    UNKNOWN_UUIDS,
)
from test_helpers.factories import retirement_payload, verification_payload
from test_helpers.test_users import ADMIN_HEADERS, REGISTRY_HEADERS

LEDGER_KEYS = (
    "grower_id",
    "lifetime_credits_issued",
    "buffer_contributed_credits",
    "accrued_total_cents",
    "paid_total_cents",
    "clawed_back_total_cents",
    "outstanding_clawback_cents",
)


def test_settlement_moves_one_payment_between_two_ledger_buckets(scenario):
    """The reconciliation read counts the single per-credit payment in exactly one bucket, so
    settling it empties the accrued bucket and fills the paid one, and the registry officer
    sees the same figures as the programme administrator.

    PRD §3.9: "the `accrued_total_cents`, `paid_total_cents` and `clawed_back_total_cents`,
    being the sums of `net_amount_cents` over this grower's payments whose `status` is
    `ACCRUED`, `PAID` and `CLAWED_BACK` respectively; and the `outstanding_clawback_cents`
    exactly as stored on the grower. The `paid_total_cents` figure must always equal the
    grower's stored `net_paid_cents`."

    PRD §3.9: "the `buffer_contributed_credits`, being the sum of `buffer_credits` over this
    grower's batches whose `issuance_status` is `ISSUED`, so cancelled batches drop out"

    Design: Corner/endpoints/ledger_summary_reconciles_credit_and_cash_ledgers_after_settlement
    """
    scenario.issued_batch(
        standard_overrides={"telemetry_required": False},
        packet_overrides={"source": EVIDENCE_FARM_RECORD},
    )
    payment = scenario.payments_of_enrollment()[0]
    assert payment["status"] == PAYMENT_ACCRUED
    assert payment["gross_amount_cents"] == 382800
    assert payment["holdback_cents"] == 76560
    assert payment["net_amount_cents"] == 306240

    before = get_success_data(
        scenario.api.get_grower_ledger_summary(scenario.grower_id, ADMIN_HEADERS)
    )
    assert before["grower_id"] == scenario.grower_id
    assert before["lifetime_credits_issued"] == 232
    assert before["buffer_contributed_credits"] == 51
    assert before["accrued_total_cents"] == 306240
    assert before["paid_total_cents"] == 0
    assert before["clawed_back_total_cents"] == 0
    assert before["outstanding_clawback_cents"] == 0

    paid = validate_success(
        scenario.api.pay_grower_payment(payment["id"], None, ADMIN_HEADERS), 200
    )
    assert paid["status"] == PAYMENT_PAID
    assert paid["net_amount_cents"] == 306240

    after = get_success_data(
        scenario.api.get_grower_ledger_summary(scenario.grower_id, ADMIN_HEADERS)
    )
    # One payment, counted once: the two buckets never both hold 306240.
    assert after["accrued_total_cents"] == 0
    assert after["paid_total_cents"] == 306240
    assert after["clawed_back_total_cents"] == 0
    assert after["lifetime_credits_issued"] == 232
    assert after["buffer_contributed_credits"] == 51

    officer = get_success_data(
        scenario.api.get_grower_ledger_summary(scenario.grower_id, REGISTRY_HEADERS)
    )
    assert {k: officer[k] for k in LEDGER_KEYS} == {k: after[k] for k in LEDGER_KEYS}

    grower = scenario.reload_grower()
    assert grower["net_paid_cents"] == after["paid_total_cents"]
    assert grower["lifetime_credits_issued"] == 232


def test_retirement_is_legal_only_inside_the_listed_window(scenario):
    """Retiring an unlisted batch and retiring an already retired batch are the same refusal,
    the one legal call in between stores its beneficiary, and retirement removes the
    outstanding credits from the pool while leaving the buffered credits behind.

    PRD §3.8: "Retiring a batch, permitted only while its `registry_status` is `LISTED` and
    its `issuance_status` is `ISSUED`, stores the supplied `retirement_beneficiary` and moves
    the registry axis `LISTED → RETIRED`, which is terminal."

    PRD §3.8: "Retirement permanently removes the credits from circulation, so the buffer
    pool's `outstanding_issued_credits` decreases by the batch's `issued_credits` and its
    `required_reserve_credits` is re-derived; the batch's own buffer contribution, however,
    stays in the pool permanently."

    Design: Corner/endpoints/batch_retirement_is_conditional_on_the_registry_listing_axis
    """
    scenario.issued_batch(
        standard_overrides={"telemetry_required": False},
        packet_overrides={"source": EVIDENCE_FARM_RECORD},
    )
    batch_id = scenario.batch["id"]
    assert scenario.batch["registry_status"] == REGISTRY_UNLISTED

    validate_error(
        scenario.api.retire_batch(
            batch_id, retirement_payload(retirement_beneficiary="Northwind Airlines"),
            REGISTRY_HEADERS,
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    assert scenario.reload_batch(batch_id)["registry_status"] == REGISTRY_UNLISTED

    before = scenario.buffer_pool()
    assert before["balance_credits"] == 51
    assert before["outstanding_issued_credits"] == 232
    assert before["required_reserve_credits"] == 12

    scenario.list_batch(batch_id, registry_account_ref="REG-ACCT-99")

    retired = validate_success(
        scenario.api.retire_batch(
            batch_id, retirement_payload(retirement_beneficiary="Northwind Airlines"),
            REGISTRY_HEADERS,
        ),
        200,
    )
    assert retired["registry_status"] == REGISTRY_RETIRED
    assert retired["retirement_beneficiary"] == "Northwind Airlines"
    assert retired["issuance_status"] == ISSUANCE_ISSUED

    after = scenario.buffer_pool()
    assert after["outstanding_issued_credits"] == 0
    assert after["required_reserve_credits"] == 0
    # The 51 buffered credits stay in the pool; only the outstanding count moves.
    assert after["balance_credits"] == 51
    assert after["pool_status"] == POOL_HEALTHY

    validate_error(
        scenario.api.retire_batch(
            batch_id, retirement_payload(retirement_beneficiary="Second Beneficiary"),
            REGISTRY_HEADERS,
        ),
        ERR_INVALID_STATE_TRANSITION,
        409,
    )
    terminal = scenario.reload_batch(batch_id)
    assert terminal["registry_status"] == REGISTRY_RETIRED
    assert terminal["retirement_beneficiary"] == "Northwind Airlines"


def test_an_assignment_validates_both_foreign_keys_and_is_reachable_from_each(scenario):
    """An unknown body and an unknown run are refused with their own not-found codes and
    persist nothing, and the valid assignment that follows is discoverable from either side of
    the link it creates.

    PRD §2.10: "Every foreign key supplied in the body resolves → otherwise the corresponding
    not-found code (404). Applies to enrollment creation, quantification-run creation,
    verification creation, reversal-event reporting and field registration."

    PRD §3.6: "A new verification starts with `opinion` of `PENDING`, `resample_count` of 0
    and `material_discrepancy_pct` of 0.00, and both `restated_removals_t` and `findings_note`
    null."

    Design: Corner/endpoints/verification_assignment_links_a_run_and_a_body_and_validates_both_references
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    scenario.create_run(METHOD_MODEL)
    scenario.submit_run()
    scenario.accredit_body()
    window = {"site_visit_start": "2026-07-01", "site_visit_end": "2026-07-03"}

    validate_error(
        scenario.api.create_verification(
            verification_payload(
                scenario.run_id, UNKNOWN_UUIDS["verification_body"], **window
            ),
            ADMIN_HEADERS,
        ),
        ERR_VERIFICATION_BODY_NOT_FOUND,
        404,
    )
    validate_error(
        scenario.api.create_verification(
            verification_payload(
                UNKNOWN_UUIDS["quantification_run"], scenario.body_id, **window
            ),
            ADMIN_HEADERS,
        ),
        ERR_QUANTIFICATION_RUN_NOT_FOUND,
        404,
    )
    _empty, empty_meta = validate_paginated(
        scenario.api.list_verifications(
            {"quantification_run_id": scenario.run_id}, ADMIN_HEADERS
        )
    )
    assert empty_meta["total_count"] == 0

    created = validate_success(
        scenario.api.create_verification(
            verification_payload(scenario.run_id, scenario.body_id, **window),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert created["quantification_run_id"] == scenario.run_id
    assert created["verification_body_id"] == scenario.body_id
    assert created["opinion"] == OPINION_PENDING
    assert created["resample_count"] == 0
    assert_pct(created["material_discrepancy_pct"], 0.00)
    assert created["restated_removals_t"] is None
    assert created["findings_note"] is None

    by_run, run_meta = validate_paginated(
        scenario.api.list_verifications(
            {"quantification_run_id": scenario.run_id}, ADMIN_HEADERS
        )
    )
    assert run_meta["total_count"] == 1
    assert run_meta["has_more"] is False
    assert by_run[0]["id"] == created["id"]

    # The body itself reaches the same row from the other foreign key.
    by_body, body_meta = validate_paginated(
        scenario.api.list_verifications(
            {"verification_body_id": scenario.body_id, "opinion": OPINION_PENDING},
            scenario.verifier_auth,
        )
    )
    assert body_meta["total_count"] == 1
    assert by_body[0]["id"] == created["id"]


def test_recording_arrival_restamps_the_window_start_and_nothing_else(scenario):
    """Arrival on site replaces the booked first visit day with the clock's day, leaves the
    last visit day, the pending opinion and the resample counter alone, and fires no cascade
    into the submitted run underneath.

    PRD §3.6: "A `Verifier` records arrival on site, which resets `site_visit_start` to the
    current logical clock instant and leaves the `opinion` axis untouched at `PENDING`."

    Design: Corner/endpoints/start_visit_moves_only_the_site_visit_window_and_not_the_opinion_axis
    """
    scenario.active_enrollment()
    scenario.passed_packet()
    scenario.create_run(METHOD_MODEL)
    scenario.submit_run()
    scenario.accredit_body()
    booked = scenario.commission_verification(
        site_visit_start="2026-07-01", site_visit_end="2026-07-03"
    )
    assert booked["version"] == 1
    assert_visit_day(booked["site_visit_start"], "2026-07-01")

    scenario.set_clock("2026-07-02T09:00:00Z")

    started = validate_success(
        scenario.api.start_visit(booked["id"], None, scenario.verifier_auth), 200
    )

    assert_visit_day(started["site_visit_start"], "2026-07-02")
    assert_visit_day(started["site_visit_end"], "2026-07-03")
    assert started["opinion"] == OPINION_PENDING
    assert started["resample_count"] == 0
    assert started["version"] == 2

    reread = get_success_data(
        scenario.api.get_verification(booked["id"], ADMIN_HEADERS)
    )
    assert_visit_day(reread["site_visit_start"], "2026-07-02")
    assert reread["opinion"] == OPINION_PENDING

    run = scenario.reload_run()
    assert run["status"] == RUN_SUBMITTED
    assert_tonnes(run["net_removals_t"], 283.360)
