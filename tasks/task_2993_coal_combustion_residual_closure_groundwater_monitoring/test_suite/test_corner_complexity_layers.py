"""Breadth probes over the declared complexity layers.

Three of them are the platform's three optimistic-concurrency guards, each on a
different endpoint with a different parent row; the fourth is the inclusive
boundary of the lateness counter.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    AGREEMENT_STATUS_ACTIVE,
    DOC_SHA256_ALT,
    DOC_URI_ALT,
    EVENT_STATUS_DRAFT,
    POSTING_CLOSURE_PLAN,
    POSTING_STABILITY_ASSESSMENT,
    POSTURE_COMPLIANT,
    POSTURE_FROZEN,
    SHIPMENT_STATUS_RETURNED,
    SHIPMENT_STATUS_SHIPPED,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, UTILITY_ADMIN_HEADERS

COMMITMENT_WINDOW = {"commitment_start_on": "2026-07-01", "commitment_end_on": "2026-12-31"}
RETURN_REASON = "Load rejected at the ready-mix plant for excess moisture"


def read_agreement(api, agreement_id):
    return validate_success(api.get_reuse_agreement(agreement_id, UTILITY_ADMIN_HEADERS))


def shipment_count(api, agreement_id):
    _, meta = validate_paginated(
        api.list_reuse_shipments(UTILITY_ADMIN_HEADERS, {"agreement_id": agreement_id})
    )
    return meta["total_count"]


def test_a_second_shipment_must_quote_the_version_the_first_one_produced(api):
    """Replaying the pre-shipment version moves no tonnage; re-reading fixes it.

    PRD: **Creating a reuse shipment** requires a non-optional `expected_unit_version` field in the request body, carrying the client's last observed `version` of the owning `DisposalUnit` — the unit that the shipment's agreement draws its ash from. If that value does not equal the unit's current `version`, the request is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412).
    Design: Corner/complexity_layers/shipment_creation_rejects_a_stale_expected_unit_version
    """
    world = fixtures.seed_unit(api, "IMP-0150")
    agreement = fixtures.seed_active_agreement(
        api, world, "RA-0150", "2026-08-01", **COMMITMENT_WINDOW
    )
    first_version = fixtures.unit_version(api, world["unit_id"])

    validate_success(
        api.create_reuse_shipment(
            factories.shipment_payload(
                agreement["id"], "SH-0150-A", 10000, first_version, "2026-08-01"
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )
    moved = fixtures.read_unit(api, world["unit_id"])
    assert moved["ash_in_place_tons"] == 470000
    assert moved["version"] == first_version + 1

    stale_body = factories.shipment_payload(
        agreement["id"], "SH-0150-B", 10000, first_version, "2026-08-01"
    )
    validate_error(
        api.create_reuse_shipment(stale_body, UTILITY_ADMIN_HEADERS),
        ApiErrorId.STALE_UNIT_VERSION.value,
    )

    assert shipment_count(api, agreement["id"]) == 1
    held = fixtures.read_unit(api, world["unit_id"])
    assert held["ash_in_place_tons"] == 470000
    assert held["version"] == first_version + 1
    assert read_agreement(api, agreement["id"])["shipped_tons_total"] == 10000

    second_version = fixtures.unit_version(api, world["unit_id"])
    assert second_version == first_version + 1

    accepted = validate_success(
        api.create_reuse_shipment(
            factories.shipment_payload(
                agreement["id"], "SH-0150-B", 10000, second_version, "2026-08-01"
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )

    assert accepted["status"] == SHIPMENT_STATUS_SHIPPED
    after = fixtures.read_unit(api, world["unit_id"])
    assert after["ash_in_place_tons"] == 460000
    assert after["version"] == second_version + 1
    reread = read_agreement(api, agreement["id"])
    assert reread["shipped_tons_total"] == 20000
    assert reread["status"] == AGREEMENT_STATUS_ACTIVE


def test_a_return_must_quote_the_version_the_later_shipment_produced(api):
    """The compensating write is guarded by the same field as the forward write.

    PRD: **Returning a reuse shipment** likewise requires `expected_unit_version` matching the owning unit's current `version`, and is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412) on a mismatch.
    Design: Corner/complexity_layers/shipment_return_rejects_a_stale_expected_unit_version
    """
    world = fixtures.seed_unit(api, "IMP-0151")
    agreement = fixtures.seed_active_agreement(
        api, world, "RA-0151", "2026-08-01", **COMMITMENT_WINDOW
    )
    first_version = fixtures.unit_version(api, world["unit_id"])
    first_load = validate_success(
        api.create_reuse_shipment(
            factories.shipment_payload(
                agreement["id"], "SH-0151-A", 10000, first_version, "2026-08-01"
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )
    second_version = fixtures.unit_version(api, world["unit_id"])
    validate_success(
        api.create_reuse_shipment(
            factories.shipment_payload(
                agreement["id"], "SH-0151-B", 10000, second_version, "2026-08-01"
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )
    seeded = fixtures.read_unit(api, world["unit_id"])
    assert seeded["ash_in_place_tons"] == 460000
    assert read_agreement(api, agreement["id"])["shipped_tons_total"] == 20000
    assert seeded["ash_mass_balance_ok"] is True

    stale_body = factories.return_shipment_payload(second_version, "2026-08-03", RETURN_REASON)
    validate_error(
        api.return_reuse_shipment(first_load["id"], stale_body, UTILITY_ADMIN_HEADERS),
        ApiErrorId.STALE_UNIT_VERSION.value,
    )

    untouched = validate_success(api.get_reuse_shipment(first_load["id"], UTILITY_ADMIN_HEADERS))
    assert untouched["status"] == SHIPMENT_STATUS_SHIPPED
    assert untouched["returned_on"] is None
    held = fixtures.read_unit(api, world["unit_id"])
    assert held["ash_in_place_tons"] == 460000
    assert read_agreement(api, agreement["id"])["shipped_tons_total"] == 20000

    third_version = fixtures.unit_version(api, world["unit_id"])
    assert third_version == second_version + 1

    returned = validate_success(
        api.return_reuse_shipment(
            first_load["id"],
            factories.return_shipment_payload(third_version, "2026-08-03", RETURN_REASON),
            UTILITY_ADMIN_HEADERS,
        )
    )

    assert returned["status"] == SHIPMENT_STATUS_RETURNED
    after = fixtures.read_unit(api, world["unit_id"])
    assert after["ash_in_place_tons"] == 470000
    assert after["version"] == third_version + 1
    assert after["ash_mass_balance_ok"] is True
    assert read_agreement(api, agreement["id"])["shipped_tons_total"] == 10000


def test_a_second_append_must_quote_the_version_the_first_result_produced(api):
    """The one guard whose parent is the round, on a call the round's own state would accept.

    PRD: **Appending an analytical result** requires a non-optional `expected_sampling_event_version` field carrying the client's last observed `version` of the parent `SamplingEvent`. A mismatch with the event's current `version` is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412). Appends to a round are legitimately repeatable — a round carries one result per well and parameter combination — so the event's own state will happily accept a second append; the version check is what forces the client to observe the round's current result set before adding to it.
    Design: Corner/complexity_layers/result_append_rejects_a_stale_expected_sampling_event_version
    """
    world = fixtures.seed_certified_network(api, "IMP-0152")
    hydro = world["hydro_headers"]
    background_well = world["wells"]["BG-01"]["id"]
    compliance_well = world["wells"]["DG-01"]["id"]
    event = fixtures.open_round(api, world["program_id"], hydro, "SE-0152", "2026-08-01")
    first_version = event["version"]

    validate_success(
        api.create_analytical_result(
            factories.result_payload(event["id"], background_well, 0.5000, first_version), hydro
        ),
        201,
    )
    seeded = fixtures.read_round(api, event["id"], hydro)
    assert seeded["result_count"] == 1
    assert seeded["version"] == first_version + 1
    assert seeded["status"] == EVENT_STATUS_DRAFT

    stale_body = factories.result_payload(event["id"], compliance_well, 0.9000, first_version)
    validate_error(
        api.create_analytical_result(stale_body, hydro), ApiErrorId.STALE_EVENT_VERSION.value
    )

    held = fixtures.read_round(api, event["id"], hydro)
    assert held["result_count"] == 1
    assert held["version"] == first_version + 1
    _, orphans = validate_paginated(
        api.list_analytical_results(UTILITY_ADMIN_HEADERS, {"well_id": compliance_well})
    )
    assert orphans["total_count"] == 0

    second_version = held["version"]
    appended = validate_success(
        api.create_analytical_result(
            factories.result_payload(event["id"], compliance_well, 0.9000, second_version), hydro
        ),
        201,
    )

    a.assert_four_dp(appended["effective_value"], 0.9000, "effective_value")
    after = fixtures.read_round(api, event["id"], hydro)
    assert after["result_count"] == 2
    assert after["version"] == second_version + 1
    assert after["status"] == EVENT_STATUS_DRAFT


def test_lateness_starts_the_day_after_the_obligation_date_and_not_on_it(api):
    """A document filed on the due date is 0 days late; one filed a day after its own is 1.

    PRD: `days_late` is `posted_on` minus the obligation date in whole calendar days, floored at 0, and is 0 whenever there is no obligation date or the posting is not `POSTED`; a posting that lands on the due date itself is 0 days late, not 1.
    PRD: `late_posting_count` counts the unit's `POSTED` postings whose `days_late` exceeds 0.
    Design: Corner/complexity_layers/posting_lateness_is_counted_only_strictly_after_the_obligation_date
    """
    world = fixtures.seed_unit(api, "IMP-0153")
    fixtures.file_stability(api, world, "2026-07-15")
    plan = fixtures.draft_plan(api, world, "CP-0153")
    fixtures.certify_plan_both_halves(api, world, plan["id"], "2026-08-01")

    before = fixtures.read_unit(api, world["unit_id"])
    a.assert_date(
        before["stability_posting_due_date"], "2026-08-14", "stability_posting_due_date"
    )
    assert before["late_posting_count"] == 0

    fixtures.set_clock(api, "2026-08-14T00:00:00Z")
    on_time = fixtures.post_document(api, world, POSTING_STABILITY_ASSESSMENT, "2026-08-14")

    assert on_time["days_late"] == 0
    assert on_time["satisfied_obligation"] is True
    punctual = fixtures.read_unit(api, world["unit_id"])
    assert punctual["late_posting_count"] == 0
    assert punctual["overdue_posting_types"] == []
    assert punctual["compliance_posture"] == POSTURE_COMPLIANT

    fixtures.approve_plan(api, plan["id"], "2026-08-14", "PERMIT-2026-F")
    planned = fixtures.read_unit(api, world["unit_id"])
    a.assert_date(
        planned["closure_plan_posting_due_date"], "2026-10-13", "closure_plan_posting_due_date"
    )

    fixtures.set_clock(api, "2026-10-14T00:00:00Z")
    overdue = validate_success(
        api.get_compliance_summary(world["unit_id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert overdue["compliance_posture"] == POSTURE_FROZEN
    assert overdue["overdue_posting_types"] == [POSTING_CLOSURE_PLAN]
    assert overdue["late_posting_count"] == 0

    late = fixtures.post_document(
        api,
        world,
        POSTING_CLOSURE_PLAN,
        "2026-10-14",
        document_uri=DOC_URI_ALT,
        document_sha256=DOC_SHA256_ALT,
    )

    assert late["days_late"] == 1
    assert late["satisfied_obligation"] is True
    recovered = fixtures.read_unit(api, world["unit_id"])
    assert recovered["late_posting_count"] == 1
    assert recovered["overdue_posting_types"] == []
    assert recovered["compliance_posture"] == POSTURE_COMPLIANT
