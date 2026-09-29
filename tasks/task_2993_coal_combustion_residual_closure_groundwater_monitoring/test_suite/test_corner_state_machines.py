"""Breadth probes over the declared state machines.

Initial states, both edges out of one endpoint, precondition gates, terminal
lockdown, the recount a child transition pushes into its parent, and the
bubble-up that closes a parent when a child fills it exactly.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    AGREEMENT_STATUS_ACTIVE,
    AGREEMENT_STATUS_COMPLETED,
    AGREEMENT_STATUS_DRAFT,
    CAP_NOT_APPLICABLE,
    CLOSURE_STATE_ACTIVE,
    CLOSURE_STATE_CLOSURE_PLANNED,
    DOC_SHA256_ALT,
    DOC_URI_ALT,
    EVENT_STATUS_DRAFT,
    EVENT_STATUS_REJECTED,
    EVENT_TYPE_DETECTION,
    EXTENSION_STATUS_REQUESTED,
    FREQUENCY_SEMIANNUAL,
    JUSTIFICATION_PERMANENT_CESSATION,
    METHOD_CLOSURE_IN_PLACE,
    PHASE_DETECTION,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_ENGINEERING_CERTIFIED,
    POSTING_ANNUAL_GW_REPORT,
    POSTING_STATUS_POSTED,
    POSTING_STATUS_WITHDRAWN,
    POSTURE_WATCH,
    REJECTION_NO_RESULTS,
    SHIPMENT_STATUS_SHIPPED,
    STABILITY_ADEQUATE,
    TIMELINESS_PENDING,
    WELL_ROLE_BACKGROUND,
    WELL_STATUS_CERTIFIED,
    WELL_STATUS_DECOMMISSIONED,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, REGULATOR_HEADERS, UTILITY_ADMIN_HEADERS

FIRST_WITHDRAWAL_REASON = "Superseded by a corrected annual groundwater monitoring report"
SECOND_WITHDRAWAL_REASON = "Duplicate withdrawal attempt against a terminal posting"


def test_an_empty_round_is_rejected_and_a_reopen_restores_it_to_draft(api):
    """One endpoint, two edges out of DRAFT, and a schedule that never advances.

    PRD: If the round holds no results at all, or if any of its results references a decommissioned well, the round moves `DRAFT → REJECTED` instead, and `rejection_reason` records which it was: `NO_RESULTS` when the round was empty
    PRD: A rejection leaves the program's `last_validated_event_id` and `next_sampling_due_date` exactly as they were — a rejected round never advances the schedule
    PRD: Reopening it moves `REJECTED → DRAFT` and clears both `rejection_reason` and `validated_on` back to null
    Design: Corner/state_machines/zero_result_event_validate_flips_to_rejection_then_reopen_restores_draft
    """
    world = fixtures.seed_unit(api, "IMP-0113")
    fixtures.install_standard_network(api, world["unit_id"], world["hydro_headers"])
    fixtures.configure_program(api, world["program_id"], world["hydro_headers"])
    fixtures.certify_network(api, world["program_id"], world["hydro_headers"], "2025-01-05")
    event = fixtures.open_round(
        api,
        world["program_id"],
        world["hydro_headers"],
        "DET-EMPTY",
        "2026-06-15",
        EVENT_TYPE_DETECTION,
    )

    rejected = validate_success(
        api.validate_sampling_event(
            event["id"], factories.validate_event_payload("2026-06-16"), world["hydro_headers"]
        )
    )
    assert rejected["status"] == EVENT_STATUS_REJECTED
    assert rejected["rejection_reason"] == REJECTION_NO_RESULTS

    program = fixtures.read_program(api, world["program_id"])
    assert program["last_validated_event_id"] is None
    assert program["next_sampling_due_date"] is None

    reopened = validate_success(
        api.reopen_sampling_event(event["id"], None, world["hydro_headers"])
    )
    assert reopened["status"] == EVENT_STATUS_DRAFT
    assert reopened["rejection_reason"] is None
    assert reopened["validated_on"] is None

    after_reopen = fixtures.read_program(api, world["program_id"])
    assert after_reopen["last_validated_event_id"] is None


def test_engineering_certification_waits_for_an_adequate_governing_verdict(api):
    """The precondition starts at UNASSESSED, so the first identical call is refused.

    PRD: It is admitted only when the unit's `governing_stability_verdict` is `ADEQUATE` — both `UNASSESSED` and `DEFICIENT` fail, with `ERR_STABILITY_NOT_ADEQUATE` (HTTP 422)
    Design: Corner/state_machines/engineering_certification_before_any_stability_assessment_is_refused
    """
    world = fixtures.seed_unit(api, "IMP-0114")
    plan = fixtures.draft_plan(api, world, "CP-0114")
    signature = factories.engineering_certification_payload("2026-08-01")

    refused = api.certify_plan_engineering(plan["id"], signature, world["geotech_headers"])
    validate_error(refused, ApiErrorId.STABILITY_NOT_ADEQUATE.value)

    unsigned = validate_success(api.get_closure_plan(plan["id"], UTILITY_ADMIN_HEADERS))
    assert unsigned["status"] == PLAN_STATUS_DRAFT
    assert unsigned["engineering_certified_by"] is None

    fixtures.file_stability(api, world, "2026-07-15")
    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["governing_stability_verdict"] == STABILITY_ADEQUATE

    certified = validate_success(
        api.certify_plan_engineering(plan["id"], signature, world["geotech_headers"])
    )
    assert certified["status"] == PLAN_STATUS_ENGINEERING_CERTIFIED
    assert certified["engineering_certified_by"] == world["geotech_id"]
    a.assert_date(certified["engineering_certified_on"], "2026-08-01", "engineering_certified_on")
    assert certified["recommended_method"] == METHOD_CLOSURE_IN_PLACE


def test_plan_approval_advances_the_unit_and_opens_the_posting_obligation(api):
    """Three declared side effects, all of them in the approving request.

    PRD: On success the unit advances `CLOSURE_PLANNED → CLOSING`
    PRD: an obligation that is still pending but whose due date has not yet passed — a due date on or after the current date — only reaches `WATCH`
    Design: Corner/state_machines/plan_approval_moves_the_unit_and_opens_the_closure_plan_posting_obligation
    """
    world = fixtures.seed_unit(api, "IMP-0115")
    fixtures.file_stability(api, world, "2026-07-15")
    plan = fixtures.draft_plan(api, world, "CP-0115")
    fixtures.certify_plan_both_halves(api, world, plan["id"], "2026-08-01")

    approved = validate_success(
        api.approve_closure_plan(
            plan["id"], factories.approve_plan_payload("2026-08-01", "PERMIT-2026-A"), REGULATOR_HEADERS
        )
    )
    assert approved["status"] == PLAN_STATUS_APPROVED
    a.assert_date(approved["approved_on"], "2026-08-01", "approved_on")
    assert approved["permit_reference"] == "PERMIT-2026-A"

    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["closure_state"] == CLOSURE_STATE_CLOSURE_PLANNED
    a.assert_date(
        unit["closure_plan_posting_due_date"], "2026-09-30", "closure_plan_posting_due_date"
    )
    a.assert_string_list(unit["overdue_posting_types"], [], "overdue_posting_types")
    assert unit["compliance_posture"] == POSTURE_WATCH
    assert unit["closure_timeliness"] == TIMELINESS_PENDING


def test_the_closure_endpoints_are_refused_while_the_unit_is_still_active(api):
    """Two transitions declared out of later states, attempted from the first one.

    PRD: The unit must be in `CLOSING`, else `ERR_INVALID_UNIT_STATE` (HTTP 409).
    PRD: The unit must be in `POST_CLOSURE_CARE`, else `ERR_INVALID_UNIT_STATE`
    Design: Corner/state_machines/complete_closure_on_an_active_unit_is_rejected
    """
    world = fixtures.seed_unit(api, "IMP-0116")

    completion = api.complete_closure(
        world["unit_id"], factories.complete_closure_payload("2026-08-01"), world["geotech_headers"]
    )
    validate_error(completion, ApiErrorId.INVALID_UNIT_STATE.value)

    care = api.certify_care_complete(world["unit_id"], None, world["geotech_headers"])
    validate_error(care, ApiErrorId.INVALID_UNIT_STATE.value)

    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["closure_state"] == CLOSURE_STATE_ACTIVE
    assert unit["cap_integrity_state"] == CAP_NOT_APPLICABLE
    assert unit["closure_completed_on"] is None
    assert unit["post_closure_care_start_on"] is None
    assert unit["post_closure_care_end_date"] is None
    assert unit["closure_timeliness"] == TIMELINESS_PENDING


def test_every_new_row_lands_in_its_declared_initial_state(api):
    """Five machines, one probe each, all read straight out of their creating call.

    PRD: A unit's `closure_state` machine is `ACTIVE -> CLOSURE_PLANNED -> CLOSING -> POST_CLOSURE_CARE -> CARE_COMPLETE`, and a unit is created in `ACTIVE`.
    PRD: A well is created in `CERTIFIED`
    PRD: An agreement's status machine is `DRAFT -> QUALIFIED -> ACTIVE -> COMPLETED`, with a `DISQUALIFIED` and a `SUSPENDED` branch; it is created in `DRAFT`
    PRD: A request is created in `REQUESTED`
    PRD: A posting is created in `POSTED`
    Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states
    """
    world = fixtures.seed_unit(api, "IMP-0117")
    unit = world["unit"]
    well = fixtures.install_well(
        api, world["unit_id"], world["hydro_headers"], "BG-01", WELL_ROLE_BACKGROUND
    )
    agreement = fixtures.draft_agreement(
        api, world, "AGR-0117", commitment_start_on="2026-01-01", commitment_end_on="2026-12-31"
    )
    request = fixtures.request_extension(
        api,
        world,
        24,
        justification_category=JUSTIFICATION_PERMANENT_CESSATION,
        narrative="The station has permanently ceased burning coal and the impoundment is dewatering",
    )
    posting = fixtures.post_document(
        api,
        world,
        POSTING_ANNUAL_GW_REPORT,
        "2026-07-01",
        document_uri=DOC_URI_ALT,
        document_sha256=DOC_SHA256_ALT,
    )

    assert unit["closure_state"] == CLOSURE_STATE_ACTIVE
    assert unit["cap_integrity_state"] == CAP_NOT_APPLICABLE
    assert well["well_status"] == WELL_STATUS_CERTIFIED
    assert agreement["status"] == AGREEMENT_STATUS_DRAFT
    assert agreement["shipped_tons_total"] == 0
    assert agreement["qualified_by"] is None
    assert request["status"] == EXTENSION_STATUS_REQUESTED
    assert request["granted_months"] == 0
    assert request["decided_on"] is None
    assert posting["status"] == POSTING_STATUS_POSTED
    for label, row in (
        ("unit", unit),
        ("well", well),
        ("agreement", agreement),
        ("extension_request", request),
        ("public_posting", posting),
    ):
        a.assert_versioned(row, 1, label)

    program = fixtures.read_program(api, world["program_id"])
    assert program["phase"] == PHASE_DETECTION
    assert program["network_certified"] is False
    assert program["sampling_frequency"] == FREQUENCY_SEMIANNUAL


def test_a_withdrawn_posting_cannot_be_withdrawn_a_second_time(api):
    """WITHDRAWN is terminal, and the refusal preserves the first withdrawal exactly.

    PRD: Withdrawing a posting that is already `WITHDRAWN` is `ERR_INVALID_POSTING_STATE` (HTTP 409).
    Design: Corner/state_machines/a_withdrawn_posting_cannot_be_withdrawn_again
    """
    world = fixtures.seed_unit(api, "IMP-0118")
    posting = fixtures.post_document(api, world, POSTING_ANNUAL_GW_REPORT, "2026-07-01")

    withdrawn = validate_success(
        api.withdraw_public_posting(
            posting["id"],
            factories.withdraw_posting_payload("2026-07-20", FIRST_WITHDRAWAL_REASON),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    assert withdrawn["status"] == POSTING_STATUS_WITHDRAWN
    a.assert_date(withdrawn["withdrawn_on"], "2026-07-20", "withdrawn_on")

    second = api.withdraw_public_posting(
        posting["id"],
        factories.withdraw_posting_payload("2026-07-25", SECOND_WITHDRAWAL_REASON),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(second, ApiErrorId.INVALID_POSTING_STATE.value)

    final = validate_success(api.get_public_posting(posting["id"], UTILITY_ADMIN_HEADERS))
    assert final["status"] == POSTING_STATUS_WITHDRAWN
    a.assert_date(final["withdrawn_on"], "2026-07-20", "withdrawn_on")
    assert final["withdrawal_reason"] == FIRST_WITHDRAWAL_REASON
    assert final["satisfied_obligation"] is False
    assert final["days_late"] == 0


def test_decommissioning_a_well_re_derives_the_counts_and_then_guards_the_floors(api):
    """The child transition pushes a recount into the parent, which then blocks it.

    PRD: `background_well_count` is the number of wells of this unit whose `well_role` is `BACKGROUND` and whose `well_status` is `CERTIFIED`
    PRD: If the program's network is certified, the server first re-derives what the counts would become without this well: decommissioning it must not drop the unit below 1 certified background well - else `ERR_NO_BACKGROUND_WELL` (HTTP 422) - nor below 3 certified downgradient wells - else `ERR_INSUFFICIENT_DOWNGRADIENT_WELLS` (HTTP 422).
    Design: Corner/state_machines/decommissioning_a_background_well_re_derives_the_program_well_counts
    """
    world = fixtures.seed_unit(api, "IMP-0119")
    wells = fixtures.install_standard_network(
        api, world["unit_id"], world["hydro_headers"], ("BG-01", "BG-02")
    )
    fixtures.configure_program(api, world["program_id"], world["hydro_headers"])
    fixtures.certify_network(api, world["program_id"], world["hydro_headers"], "2025-01-05")

    before = fixtures.read_program(api, world["program_id"])
    assert before["background_well_count"] == 2
    assert before["downgradient_well_count"] == 3

    retired = validate_success(
        api.decommission_well(
            wells["BG-01"]["id"],
            factories.decommission_payload("2026-07-01"),
            world["hydro_headers"],
        )
    )
    assert retired["well_status"] == WELL_STATUS_DECOMMISSIONED
    a.assert_date(retired["decommissioned_on"], "2026-07-01", "decommissioned_on")

    recounted = fixtures.read_program(api, world["program_id"])
    assert recounted["background_well_count"] == 1
    assert recounted["downgradient_well_count"] == 3

    last_background = api.decommission_well(
        wells["BG-02"]["id"], factories.decommission_payload("2026-07-02"), world["hydro_headers"]
    )
    validate_error(last_background, ApiErrorId.NO_BACKGROUND_WELL.value)
    assert (
        validate_success(api.get_well(wells["BG-02"]["id"], UTILITY_ADMIN_HEADERS))["well_status"]
        == WELL_STATUS_CERTIFIED
    )

    third_downgradient = api.decommission_well(
        wells["DG-01"]["id"], factories.decommission_payload("2026-07-02"), world["hydro_headers"]
    )
    validate_error(third_downgradient, ApiErrorId.INSUFFICIENT_DOWNGRADIENT_WELLS.value)
    assert (
        validate_success(api.get_well(wells["DG-01"]["id"], UTILITY_ADMIN_HEADERS))["well_status"]
        == WELL_STATUS_CERTIFIED
    )

    final = fixtures.read_program(api, world["program_id"])
    assert final["network_certified"] is True
    assert final["background_well_count"] == 1
    assert final["downgradient_well_count"] == 3


def test_the_load_that_fills_the_commitment_completes_the_agreement(api):
    """20,000 then 10,000 tons against a 30,000-ton commitment, and then a refusal.

    PRD: after which, if the agreement's recomputed `shipped_tons_total` has reached or passed its `committed_tons`, the agreement moves `ACTIVE` -> `COMPLETED`
    PRD: The agreement must be `ACTIVE`, else `ERR_INVALID_AGREEMENT_STATE` (HTTP 409).
    Design: Corner/state_machines/a_shipment_that_fills_the_commitment_bubbles_the_agreement_to_completed
    """
    world = fixtures.seed_unit(api, "IMP-0120")
    fixtures.seed_active_agreement(
        api,
        world,
        "AGR-0120",
        committed_tons=30000,
        commitment_start_on="2026-01-01",
        commitment_end_on="2026-12-31",
    )

    first = fixtures.ship_load(api, world, "SHP-0120-A", 20000, "2026-07-01")
    assert first["status"] == SHIPMENT_STATUS_SHIPPED
    partial = validate_success(api.get_reuse_agreement(world["agreement_id"], UTILITY_ADMIN_HEADERS))
    assert partial["status"] == AGREEMENT_STATUS_ACTIVE
    assert partial["shipped_tons_total"] == 20000
    assert fixtures.read_unit(api, world["unit_id"])["ash_in_place_tons"] == 460000

    second = fixtures.ship_load(api, world, "SHP-0120-B", 10000, "2026-07-02")
    assert second["status"] == SHIPMENT_STATUS_SHIPPED
    filled = validate_success(api.get_reuse_agreement(world["agreement_id"], UTILITY_ADMIN_HEADERS))
    assert filled["status"] == AGREEMENT_STATUS_COMPLETED
    assert filled["shipped_tons_total"] == 30000
    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["ash_in_place_tons"] == 450000
    assert unit["ash_mass_balance_ok"] is True

    overflow = api.create_reuse_shipment(
        factories.shipment_payload(
            world["agreement_id"],
            "SHP-0120-C",
            1,
            fixtures.unit_version(api, world["unit_id"]),
            "2026-07-03",
        ),
        UTILITY_ADMIN_HEADERS,
    )
    validate_error(overflow, ApiErrorId.INVALID_AGREEMENT_STATE.value)
    assert fixtures.read_unit(api, world["unit_id"])["ash_in_place_tons"] == 450000
