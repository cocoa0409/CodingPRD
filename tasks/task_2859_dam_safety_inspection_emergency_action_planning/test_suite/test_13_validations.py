"""Validation breadth: each admission rule refused once and then satisfied once."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assert_acre_feet, assert_cents, assert_cfs, assert_instant
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSESSMENT_CERTIFIED,
    ASSESSMENT_DRAFT,
    CLOCK_ORIGIN,
    DELINQUENCY_CURRENT,
    DELINQUENCY_DELINQUENT,
    DRAWDOWN_COORDINATED,
    DRAWDOWN_REQUESTED,
    EAP_APPROVED,
    EAP_DRAFT,
    EAP_SUBMITTED,
    ENTRY_CIVIL_PENALTY,
    ENTRY_PAYMENT_RECEIVED,
    EVENT_MONITORING,
    EXERCISE_ACCEPTED,
    EXERCISE_FUNCTIONAL,
    HAZARD_HIGH,
    HAZARD_LOW,
    HAZARD_SIGNIFICANT,
    HAZARD_UNCLASSIFIED,
    INSPECTION_SCHEDULED,
    LICENSE_ACTIVE,
    PERMIT_ISSUED,
    PERMIT_TYPE_REPAIR,
    PERMIT_UNDER_ENGINEERING_REVIEW,
    REG_REGISTERED,
    REVIEW_APPROVE,
)
from test_helpers.test_users import make_engineer_headers, make_owner_headers


# ---------------------------------------------------------------------------
# Rung 25: nothing is scheduled against an unclassified dam
# ---------------------------------------------------------------------------
@pytest.fixture()
def drafted_only(program, base):
    """An UNCLASSIFIED dam whose only consequence assessment is still DRAFT."""
    return program.create_assessment(f.assessment_a1(base.dam_id), base.engineer_a_id)


def test_scheduling_is_refused_while_the_class_is_still_unpublished(
    api, program, base, drafted_only
):
    """A filed but uncertified assessment leaves the dam unschedulable.

    PRD 3.3: "A dam that has never been classified cannot be scheduled at all, which surfaces as `ERR_DAM_UNCLASSIFIED`; the nominated engineer's licence must be active and their certification must cover the dam's hazard class."

    Design: Corner/validations/inspection_scheduling_rejected_until_the_dam_is_classified
    """
    assert drafted_only["status"] == ASSESSMENT_DRAFT
    assert program.get_dam(base.dam_id)["hazard_class"] == HAZARD_UNCLASSIFIED

    response = api.create_inspection(
        f.inspection_payload(base.dam_id, base.engineer_a_id), program.admin
    )
    validate_error(response, ApiErrorId.ERR_DAM_UNCLASSIFIED.value, 422)

    _rows, meta = validate_paginated(
        api.list_inspections(program.admin, {"dam_id": base.dam_id})
    )
    assert meta["total_count"] == 0
    assert program.get_engineer(base.engineer_a_id)["open_inspection_count"] == 0


def test_the_identical_request_is_scheduled_once_the_class_is_published(
    program, base, drafted_only
):
    """Certifying the pending assessment is all the request was waiting for.

    PRD 3.3: "A new inspection lands in `SCHEDULED` with `performed_at`, `condition_rating` and `narrative` all null, `deficiency_count` and `return_count` at 0, and `accepted_by_user_id` and `accepted_at` null; the engineer's `open_inspection_count` rises by one."

    Design: Corner/validations/inspection_scheduling_rejected_until_the_dam_is_classified
    """
    program.certify_assessment(drafted_only["id"], base.engineer_a_id)
    assert program.get_dam(base.dam_id)["hazard_class"] == HAZARD_SIGNIFICANT

    scheduled = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    assert scheduled["status"] == INSPECTION_SCHEDULED
    assert scheduled["engineer_id"] == base.engineer_a_id
    assert scheduled["performed_at"] is None
    assert scheduled["condition_rating"] is None
    assert scheduled["narrative"] is None
    assert scheduled["deficiency_count"] == 0
    assert scheduled["return_count"] == 0
    assert scheduled["accepted_by_user_id"] is None
    assert scheduled["accepted_at"] is None

    assert program.get_engineer(base.engineer_a_id)["open_inspection_count"] == 1


# ---------------------------------------------------------------------------
# Rung 31: the notification-contact minimum is inclusive
# ---------------------------------------------------------------------------
@pytest.fixture()
def short_contact_plan(program, base):
    """A DRAFT plan on a SIGNIFICANT dam listing only three notification contacts."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    return program.draft_plan(
        base.dam_id, base.owner_id, notification_contact_count=3
    )


def test_three_contacts_are_one_short_of_the_significant_minimum(
    api, program, base, short_contact_plan
):
    """A shortfall of one contact refuses the submission and consumes no transition.

    PRD 3.5: "First, `notification_contact_count` must be at least the hazard-class minimum from §2.8 — 8 contacts at `HIGH`, 4 at `SIGNIFICANT`, 1 at `LOW` or `UNCLASSIFIED`, inclusive — and a shortfall is `ERR_INSUFFICIENT_NOTIFICATION_CONTACTS`."

    Design: Corner/validations/eap_submit_rejected_below_the_contact_minimum_then_passes_at_exactly_four
    """
    response = api.submit_eap(
        short_contact_plan["id"], None, make_owner_headers(base.owner_id)
    )
    validate_error(
        response, ApiErrorId.ERR_INSUFFICIENT_NOTIFICATION_CONTACTS.value, 422
    )

    stored = program.get_plan(short_contact_plan["id"])
    assert stored["status"] == EAP_DRAFT
    assert stored["notification_contact_count"] == 3
    assert program.get_dam(base.dam_id)["latest_eap_status"] == EAP_DRAFT


def test_a_submit_time_override_to_exactly_four_contacts_is_admitted(
    program, base, short_contact_plan
):
    """The submitted override is written before the minimum is measured.

    PRD 3.5: "Submission accepts optional `inundation_map_ref`, `notification_flowchart_ref`, `notification_contact_count` and `drawdown_procedure_ref` values, and any that are supplied **overwrite the stored values before the two admission checks below are evaluated** — which is precisely how an owner recovers a plan that a reclassification pushed into `REVISION_REQUIRED`, by resubmitting it with a refreshed map reference."

    Design: Corner/validations/eap_submit_rejected_below_the_contact_minimum_then_passes_at_exactly_four
    """
    submitted = program.submit_plan(
        short_contact_plan["id"], base.owner_id, {"notification_contact_count": 4}
    )
    assert submitted["status"] == EAP_SUBMITTED
    assert submitted["notification_contact_count"] == 4

    dam = program.get_dam(base.dam_id)
    assert dam["eap_required"] is True
    assert dam["latest_eap_status"] == EAP_SUBMITTED


# ---------------------------------------------------------------------------
# Rung 32: the plan's map must match the dam's certified assessment
# ---------------------------------------------------------------------------
@pytest.fixture()
def stale_map_plan(program, base):
    """A DRAFT plan quoting a retired inundation map on a SIGNIFICANT dam."""
    certified = program.classify_significant(base.dam_id, base.engineer_a_id)
    plan = program.draft_plan(
        base.dam_id,
        base.owner_id,
        inundation_map_ref="IM-2014-OLD",
        notification_contact_count=4,
    )
    return {"certified": certified, "plan": plan}


def test_a_retired_map_reference_blocks_the_submission(
    api, program, base, stale_map_plan
):
    """The comparison is against the dam's certified assessment, not the plan itself.

    PRD 3.5: "Second, when the dam's `eap_required` flag is true, the plan's `inundation_map_ref` must equal the `inundation_map_ref` of the dam's certified consequence assessment; a mismatch is `ERR_INUNDATION_MAP_STALE`, and a dam that does not require a plan is exempt from this check entirely."

    Design: Corner/validations/eap_submit_rejected_against_a_superseded_inundation_map
    """
    plan_id = stale_map_plan["plan"]["id"]
    response = api.submit_eap(plan_id, None, make_owner_headers(base.owner_id))
    validate_error(response, ApiErrorId.ERR_INUNDATION_MAP_STALE.value, 422)

    stored = program.get_plan(plan_id)
    assert stored["status"] == EAP_DRAFT
    assert stored["inundation_map_ref"] == "IM-2014-OLD"


def test_refreshing_the_map_reference_at_submission_clears_the_check(
    program, base, stale_map_plan
):
    """Quoting the certified map at submission admits the very same plan.

    PRD 3.5: "Submission accepts optional `inundation_map_ref`, `notification_flowchart_ref`, `notification_contact_count` and `drawdown_procedure_ref` values, and any that are supplied **overwrite the stored values before the two admission checks below are evaluated** — which is precisely how an owner recovers a plan that a reclassification pushed into `REVISION_REQUIRED`, by resubmitting it with a refreshed map reference."

    Design: Corner/validations/eap_submit_rejected_against_a_superseded_inundation_map
    """
    submitted = program.submit_plan(
        stale_map_plan["plan"]["id"],
        base.owner_id,
        {"inundation_map_ref": "IM-2019-A"},
    )
    assert submitted["status"] == EAP_SUBMITTED
    assert submitted["inundation_map_ref"] == "IM-2019-A"

    # Neither call touched the certification the map was compared against.
    certified = program.assessments_for(base.dam_id)[0]
    assert certified["id"] == stale_map_plan["certified"]["id"]
    assert certified["status"] == ASSESSMENT_CERTIFIED
    assert certified["inundation_map_ref"] == "IM-2019-A"


# ---------------------------------------------------------------------------
# Rung 23: a high-hazard decision waits for an approved plan
# ---------------------------------------------------------------------------
@pytest.fixture()
def high_hazard_permit(program, base):
    """A paid, assigned REPAIR permit on a HIGH dam whose plan is only SUBMITTED."""
    program.classify(base.dam_id, base.engineer_a_id, f.assessment_a4)
    plan = program.draft_plan(
        base.dam_id,
        base.owner_id,
        inundation_map_ref="IM-2026-D",
        notification_contact_count=8,
    )
    program.submit_plan(plan["id"], base.owner_id)
    permit = program.apply_permit(
        base.dam_id,
        base.owner_id,
        permit_type=PERMIT_TYPE_REPAIR,
        scope_description="Toe drain replacement and filter rebuild.",
        estimated_project_cost_cents=8_000_000,
    )
    program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_PAYMENT_RECEIVED,
        amount_cents=-150_000,
        memo="Review fee settled in full before the decision.",
    )
    program.assign_permit_review(permit["id"], base.engineer_b_id)
    return {"plan": plan, "permit": permit}


def test_the_decision_is_refused_while_the_plan_sits_in_submitted(
    api, program, base, high_hazard_permit
):
    """Fees paid and a reviewer assigned, and still the plan gate holds the decision.

    PRD 2.5: "**Approved plan required for high-hazard operations** — when the dam's hazard class is `HIGH`, its latest plan status must be `APPROVED`; otherwise `ERR_EAP_NOT_APPROVED` (422)."

    Design: Corner/validations/high_hazard_permit_decision_rejected_until_the_plan_is_approved
    """
    permit_id = high_hazard_permit["permit"]["id"]
    assert_cents(high_hazard_permit["permit"]["total_fee_cents"], 150000, "total_fee_cents")
    assert program.get_owner(base.owner_id)["delinquency_status"] == DELINQUENCY_CURRENT
    assert program.get_dam(base.dam_id)["hazard_class"] == HAZARD_HIGH

    response = api.decide_permit(
        permit_id,
        f.permit_decision_payload(findings="Engineering package adequate."),
        make_engineer_headers(base.engineer_b_id),
    )
    validate_error(response, ApiErrorId.ERR_EAP_NOT_APPROVED.value, 422)

    stored = program.get_permit(permit_id)
    assert stored["status"] == PERMIT_UNDER_ENGINEERING_REVIEW
    assert stored["issued_at"] is None
    assert stored["decision_findings"] is None


def test_approving_the_plan_admits_the_very_same_decision(
    program, base, high_hazard_permit
):
    """The gate reads the dam's latest plan status, so approval unblocks issuance.

    PRD 3.6: "`ISSUE` moves the permit `UNDER_ENGINEERING_REVIEW → ISSUED`, which is terminal, stamps `issued_at` with the logical clock and stores the supplied findings in `decision_findings` and any `conditions`."

    Design: Corner/validations/high_hazard_permit_decision_rejected_until_the_plan_is_approved
    """
    program.review_plan(
        high_hazard_permit["plan"]["id"],
        base.engineer_a_id,
        decision=REVIEW_APPROVE,
        findings="Inundation mapping and flowchart accepted.",
    )
    assert program.get_dam(base.dam_id)["latest_eap_status"] == EAP_APPROVED

    issued = program.decide_permit(
        high_hazard_permit["permit"]["id"],
        base.engineer_b_id,
        findings="Engineering package adequate.",
    )
    assert issued["status"] == PERMIT_ISSUED
    assert_instant(issued["issued_at"], CLOCK_ORIGIN, "issued_at")
    assert issued["decision_findings"] == "Engineering package adequate."
    assert issued["review_engineer_id"] == base.engineer_b_id


def test_issuing_a_repair_permit_leaves_the_regulatory_posture_alone(
    program, base, high_hazard_permit
):
    """Only a removal authorisation moves the dam on the regulatory dimension.

    PRD 3.6: "When the `permit_type` is `REMOVAL`, issuance also moves the dam `REGISTERED → REMOVAL_PERMITTED` on the regulatory dimension and increments the dam's `version` by 1 — the state has authorised the structure's removal, and from that point no new consequence assessment or construction permit may be filed against it."

    Design: Corner/validations/high_hazard_permit_decision_rejected_until_the_plan_is_approved
    """
    program.review_plan(
        high_hazard_permit["plan"]["id"], base.engineer_a_id, decision=REVIEW_APPROVE
    )
    issued = program.decide_permit(
        high_hazard_permit["permit"]["id"],
        base.engineer_b_id,
        findings="Engineering package adequate.",
    )
    assert issued["permit_type"] == PERMIT_TYPE_REPAIR
    assert program.get_dam(base.dam_id)["regulatory_status"] == REG_REGISTERED


# ---------------------------------------------------------------------------
# Rung 29: the reservoir cannot lend more storage than it holds
# ---------------------------------------------------------------------------
@pytest.fixture()
def tiny_reservoir(program, base):
    """A 100 acre-foot reservoir on the 1200-cfs reach with two REQUESTED releases."""
    dam = program.create_dam(
        base.owner_id,
        base.reach_id,
        name="Pothole Basin Dam",
        nid_code="ST00155",
        height_ft=34,
        gross_storage_acre_ft=100,
        crest_elevation_ft=980.0,
        normal_pool_elevation_ft=976.0,
        year_completed=1977,
    )
    program.classify_significant(
        dam["id"], base.engineer_a_id, inundation_map_ref="IM-2019-E"
    )
    event = program.declare_event(
        dam["id"],
        declared_at=CLOCK_ORIGIN,
        trigger_description="Cell of intense rainfall over the small catchment.",
        declared_inflow_cfs=700,
    )
    big = program.request_drawdown(
        dam["id"],
        event["id"],
        requested_release_cfs=400,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )
    small = program.request_drawdown(
        dam["id"],
        event["id"],
        requested_release_cfs=200,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
    )
    return {"dam": dam, "big": big, "small": small}


def test_both_requests_price_their_volume_off_the_same_six_hour_window(tiny_reservoir):
    """The rate is what separates the two orders; the window is identical.

    PRD 3.7: "The window's duration is measured in hours, fractional hours allowed, as `window_end` less `window_start`; that number of hours is multiplied by `requested_release_cfs` and by the conversion factor 0.0826446 acre-feet per cubic-foot-per-second-hour, and the product is rounded half up to three decimal places."

    Design: Corner/validations/drawdown_coordination_rejected_when_planned_release_exceeds_available_storage
    """
    assert_acre_feet(
        tiny_reservoir["big"]["planned_release_acre_ft"], 198.347, "planned_release_acre_ft"
    )
    assert_acre_feet(
        tiny_reservoir["small"]["planned_release_acre_ft"], 99.174, "planned_release_acre_ft"
    )
    assert tiny_reservoir["big"]["status"] == DRAWDOWN_REQUESTED
    assert tiny_reservoir["small"]["status"] == DRAWDOWN_REQUESTED


def test_the_channel_could_carry_the_release_but_the_reservoir_cannot_fund_it(
    api, program, base, tiny_reservoir
):
    """198.347 acre-feet against 100 available is refused on storage, not capacity.

    PRD 3.7: "The **storage check** then requires the order's `planned_release_acre_ft` to be at or below the dam's `available_conservation_storage_acre_ft`, equality allowed, with a shortfall rejected as `ERR_INSUFFICIENT_STORAGE`."

    Design: Corner/validations/drawdown_coordination_rejected_when_planned_release_exceeds_available_storage
    """
    opening_version = program.reach_version(base.reach_id)
    response = api.coordinate_drawdown(
        tiny_reservoir["big"]["id"],
        f.coordinate_payload(opening_version),
        program.admin,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_STORAGE.value, 409)

    refused = program.get_drawdown(tiny_reservoir["big"]["id"])
    assert refused["status"] == DRAWDOWN_REQUESTED
    assert refused["coordinated_at"] is None

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 0.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 0
    assert reach["version"] == opening_version


def test_the_smaller_release_fits_with_less_than_an_acre_foot_to_spare(
    program, base, tiny_reservoir
):
    """99.174 acre-feet leaves 0.826 behind, and that is enough to coordinate.

    PRD 3.7: "On success the order moves `REQUESTED → COORDINATED`, `coordinated_at` is stamped with the clock, and both shared quantities are committed in the same request: the reach's `committed_release_cfs` rises by the order's requested rate and its `active_drawdown_count` by one, incrementing the reach's `version` by 1; and the dam's `committed_drawdown_acre_ft` rises by the order's planned volume with `available_conservation_storage_acre_ft` recomputed, incrementing the dam's `version` by 1."

    Design: Corner/validations/drawdown_coordination_rejected_when_planned_release_exceeds_available_storage
    """
    coordinated = program.coordinate_drawdown(
        tiny_reservoir["small"]["id"], reach_id=base.reach_id
    )
    assert coordinated["status"] == DRAWDOWN_COORDINATED
    assert_instant(coordinated["coordinated_at"], CLOCK_ORIGIN, "coordinated_at")

    dam = program.get_dam(tiny_reservoir["dam"]["id"])
    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 99.174, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        0.826,
        "available_conservation_storage_acre_ft",
    )

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 200.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 1


# ---------------------------------------------------------------------------
# Rungs 38 and 39: two uniqueness keys on two different entities
# ---------------------------------------------------------------------------
def test_the_inventory_code_is_unique_across_the_whole_program(api, program, base):
    """Reusing a registered NID code is refused even for the same owner and reach.

    PRD 2.5: "**Inventory code uniqueness** — a dam's `nid_code` is unique program-wide, independent of owner; otherwise `ERR_DUPLICATE_NID_CODE` (409)."

    Design: Corner/validations/duplicate_nid_code_and_duplicate_license_number_are_rejected
    """
    clash = f.dam_payload(
        base.owner_id,
        base.reach_id,
        name="Copycat Dam",
        nid_code="ST00123",
        height_ft=41,
        gross_storage_acre_ft=300,
        crest_elevation_ft=900.0,
        normal_pool_elevation_ft=896.0,
        year_completed=1981,
        registered_at="2020-06-01T00:00:00Z",
    )
    validate_error(
        api.create_dam(clash, program.admin),
        ApiErrorId.ERR_DUPLICATE_NID_CODE.value,
        409,
    )

    accepted = program.create_dam(
        base.owner_id,
        base.reach_id,
        name="Copycat Dam",
        nid_code="ST00124",
        height_ft=41,
        gross_storage_acre_ft=300,
        crest_elevation_ft=900.0,
        normal_pool_elevation_ft=896.0,
        year_completed=1981,
        registered_at="2020-06-01T00:00:00Z",
    )
    assert accepted["nid_code"] == "ST00124"
    assert accepted["hazard_class"] == HAZARD_UNCLASSIFIED
    assert accepted["regulatory_status"] == REG_REGISTERED

    _rows, meta = validate_paginated(api.list_dams(program.admin))
    assert meta["total_count"] == 2


def test_one_professional_licence_registers_exactly_one_engineer(api, program, base):
    """A different name and expiry cannot smuggle a second row onto the same licence.

    PRD 2.5: "**Licence number uniqueness** — an engineer's `license_number` is unique across all engineers; otherwise `ERR_DUPLICATE_LICENSE_NUMBER` (409)."

    Design: Corner/validations/duplicate_nid_code_and_duplicate_license_number_are_rejected
    """
    clash = f.engineer_payload(
        full_name="Sam Okoye",
        license_number=base.engineer_a["license_number"],
        license_expires_at="2030-06-30T00:00:00Z",
        certified_hazard_classes=[HAZARD_LOW],
    )
    validate_error(
        api.create_engineer(clash, program.admin),
        ApiErrorId.ERR_DUPLICATE_LICENSE_NUMBER.value,
        409,
    )

    accepted = program.create_engineer(
        full_name="Sam Okoye",
        license_number="PE-44121",
        license_expires_at="2030-06-30T00:00:00Z",
        certified_hazard_classes=[HAZARD_LOW],
    )
    assert accepted["license_number"] == "PE-44121"
    assert accepted["license_status"] == LICENSE_ACTIVE

    _rows, meta = validate_paginated(api.list_engineers(program.admin))
    assert meta["total_count"] == 3


# ---------------------------------------------------------------------------
# Rung 42: the clock never runs backwards, but it may stand still
# ---------------------------------------------------------------------------
@pytest.fixture()
def advanced_clock(program):
    """An owner minted at the origin, then the clock pushed forward four days."""
    owner = program.create_owner()
    program.set_clock("2026-08-05T13:00:00Z")
    return owner


def test_a_one_second_rewind_is_refused_and_the_clock_holds_its_value(
    api, program, advanced_clock
):
    """The next created row proves the rejected rewind never took effect.

    PRD 2.4: "The clock is strictly monotonic: a requested value earlier than the current clock is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), while setting it to exactly its current value succeeds as a no-op."

    Design: Corner/validations/clock_rewind_rejected_but_resetting_to_the_same_instant_succeeds
    """
    assert advanced_clock["fee_balance_cents"] == 0
    validate_error(
        api.set_clock(f.clock_payload("2026-08-05T12:59:59Z"), program.admin),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
        422,
    )

    minted = program.create_engineer(
        full_name="Dana Whitlock",
        license_number="PE-44190",
        license_expires_at="2029-12-31T00:00:00Z",
    )
    assert_instant(minted["created_at"], "2026-08-05T13:00:00Z", "created_at")


def test_resetting_the_clock_to_its_own_value_is_an_accepted_no_op(
    program, advanced_clock
):
    """Standing still is legal, and it disturbs nothing already recorded.

    PRD 2.4: "Advancing the clock does not itself mutate any row: an engineer's `license_status` and a dam's `inspection_overdue` are re-derived on the next read, and the enforcement consequences of elapsed time are applied only by the compliance sweep described in §3.9."

    Design: Corner/validations/clock_rewind_rejected_but_resetting_to_the_same_instant_succeeds
    """
    program.set_clock("2026-08-05T13:00:00Z")

    stored = program.get_owner(advanced_clock["id"])
    assert_instant(stored["created_at"], CLOCK_ORIGIN, "created_at")
    assert stored["delinquency_status"] == DELINQUENCY_CURRENT

    later = program.create_engineer(
        full_name="Ines Whitlock",
        license_number="PE-44191",
        license_expires_at="2029-12-31T00:00:00Z",
    )
    assert_instant(later["created_at"], "2026-08-05T13:00:00Z", "created_at")


# ---------------------------------------------------------------------------
# Rung 41: the order and its event must name the same dam
# ---------------------------------------------------------------------------
@pytest.fixture()
def two_dams_one_event(program, base):
    """Two SIGNIFICANT dams on one reach, with a MONITORING event on the first."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    dam_b = program.create_dam(
        base.owner_id,
        base.reach_id,
        name="Sandy Bench Dam",
        nid_code="ST00167",
        height_ft=52,
        gross_storage_acre_ft=1200,
        crest_elevation_ft=1120.0,
        normal_pool_elevation_ft=1116.0,
        year_completed=1971,
    )
    program.classify_significant(
        dam_b["id"], base.engineer_a_id, inundation_map_ref="IM-2019-F"
    )
    event = program.declare_event(
        base.dam_id,
        declared_at=CLOCK_ORIGIN,
        trigger_description="Warm rain on a saturated basin.",
        declared_inflow_cfs=800,
    )
    return {"dam_b": dam_b, "event": event}


def test_borrowing_another_dams_event_is_a_mismatch_not_a_missing_row(
    api, program, two_dams_one_event
):
    """Both references resolve, so the only defect left is their disagreement.

    PRD 3.7: "The event must not be stood down, the dam must be operable and must not be `UNCLASSIFIED`, a `HIGH`-hazard dam must have an `APPROVED` plan on record or the request fails with `ERR_EAP_NOT_APPROVED`, and the named event must belong to the same dam as the order — a mismatch is `ERR_EVENT_DAM_MISMATCH`."

    Design: Corner/validations/drawdown_order_rejected_when_the_event_belongs_to_another_dam
    """
    dam_b_id = two_dams_one_event["dam_b"]["id"]
    response = api.create_drawdown_order(
        f.drawdown_payload(
            dam_b_id,
            two_dams_one_event["event"]["id"],
            requested_release_cfs=300,
            window_start="2026-08-02T00:00:00Z",
            window_end="2026-08-02T06:00:00Z",
        ),
        program.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_EVENT_DAM_MISMATCH.value, 422)

    _rows, meta = validate_paginated(
        api.list_drawdown_orders(program.admin, {"dam_id": dam_b_id})
    )
    assert meta["total_count"] == 0


def test_the_matching_pair_lands_in_requested_with_nothing_committed(
    api, program, base, two_dams_one_event
):
    """Naming the event's own dam is accepted and reserves no capacity yet.

    PRD 3.7: "The order lands in `REQUESTED` with `coordinated_at`, `activated_at`, `completed_at`, `cancelled_at`, `cancel_reason` and `actual_release_acre_ft` all null, and **nothing is committed yet**."

    Design: Corner/validations/drawdown_order_rejected_when_the_event_belongs_to_another_dam
    """
    event = two_dams_one_event["event"]
    order = validate_success(
        api.create_drawdown_order(
            f.drawdown_payload(
                base.dam_id,
                event["id"],
                requested_release_cfs=300,
                window_start="2026-08-02T00:00:00Z",
                window_end="2026-08-02T06:00:00Z",
            ),
            program.coordinator,
        ),
        201,
    )
    assert order["status"] == DRAWDOWN_REQUESTED
    assert_acre_feet(order["planned_release_acre_ft"], 148.760, "planned_release_acre_ft")
    assert order["coordinated_at"] is None
    assert order["activated_at"] is None
    assert order["completed_at"] is None
    assert order["cancelled_at"] is None
    assert order["cancel_reason"] is None
    assert order["actual_release_acre_ft"] is None

    reach = program.get_reach(base.reach_id)
    assert_cfs(reach["committed_release_cfs"], 0.000, "committed_release_cfs")
    assert reach["active_drawdown_count"] == 0

    stored_event = program.get_event(event["id"])
    assert stored_event["status"] == EVENT_MONITORING
    assert stored_event["dam_id"] == base.dam_id


# ---------------------------------------------------------------------------
# Rung 34: an exercise may be logged at the clock but not past it
# ---------------------------------------------------------------------------
@pytest.fixture()
def drill_ready_plan(program, base):
    """An APPROVED plan on a SIGNIFICANT dam, ready to accept an exercise log."""
    program.classify_significant(base.dam_id, base.engineer_a_id)
    return program.approved_plan(base.dam_id, base.owner_id, base.engineer_b_id)


def test_a_drill_dated_one_second_ahead_of_the_clock_is_refused(
    api, program, base, drill_ready_plan
):
    """The future-date rule bites at one second past the clock and records nothing.

    PRD 3.5: "Exercises are logged after the fact, so `conducted_at` must be at or before the current logical clock, equality permitted, with a later instant rejected as `ERR_EXERCISE_DATE_IN_FUTURE`."

    Design: Corner/validations/exercise_rejected_when_conducted_after_the_clock_but_accepted_exactly_at_it
    """
    plan_id = drill_ready_plan["id"]
    response = api.create_exercise(
        plan_id,
        f.exercise_payload(
            exercise_type=EXERCISE_FUNCTIONAL,
            conducted_at="2026-08-01T00:00:01Z",
            participant_count=6,
            notification_test_passed=True,
        ),
        make_owner_headers(base.owner_id),
    )
    validate_error(response, ApiErrorId.ERR_EXERCISE_DATE_IN_FUTURE.value, 422)

    _rows, meta = validate_paginated(api.list_exercises(plan_id, program.admin))
    assert meta["total_count"] == 0
    stored = program.get_plan(plan_id)
    assert stored["accepted_exercise_count"] == 0
    assert stored["exercise_current"] is False


def test_a_drill_dated_exactly_at_the_clock_is_accepted_and_makes_the_plan_current(
    program, base, drill_ready_plan
):
    """Equality with the clock is permitted, and it satisfies the currency window too.

    PRD 3.5: "The plan is current exactly when at least one exercise on the dam's `APPROVED` plan is graded `ACCEPTED` and its `conducted_at` is **strictly later** than the clock less 365 days and at or before the clock — the lower bound is exclusive, so an exercise conducted exactly 365 days ago no longer counts, while the upper bound is inclusive."

    Design: Corner/validations/exercise_rejected_when_conducted_after_the_clock_but_accepted_exactly_at_it
    """
    logged = program.log_exercise(
        drill_ready_plan["id"],
        make_owner_headers(base.owner_id),
        exercise_type=EXERCISE_FUNCTIONAL,
        conducted_at=CLOCK_ORIGIN,
        participant_count=6,
        notification_test_passed=True,
    )
    assert logged["outcome"] == EXERCISE_ACCEPTED
    assert logged["deficiency_reason"] is None

    stored = program.get_plan(drill_ready_plan["id"])
    assert stored["accepted_exercise_count"] == 1
    assert_instant(
        stored["last_accepted_exercise_at"], CLOCK_ORIGIN, "last_accepted_exercise_at"
    )
    assert stored["exercise_current"] is True


# ---------------------------------------------------------------------------
# Rungs 3 and 40: the ledger's sign rule and the zero-amount rule are distinct
# ---------------------------------------------------------------------------
def test_both_directions_of_the_sign_rule_are_enforced(api, program, base):
    """A positive payment and a negative penalty are each refused as sign mismatches.

    PRD 3.8: "An entry whose `amount_cents` sign disagrees with its `entry_type` is rejected with `ERR_LEDGER_SIGN_MISMATCH`, and an `amount_cents` of exactly 0 is never accepted at all — it is caught as a malformed request."

    Design: Corner/validations/fee_adjustment_rejected_for_sign_mismatch_and_zero_amount_returns_invalid_request
    """
    wrong_way = api.create_fee_adjustment(
        base.owner_id,
        f.fee_adjustment_payload(
            entry_type=ENTRY_PAYMENT_RECEIVED, amount_cents=5000, memo="Wrong sign"
        ),
        program.admin,
    )
    validate_error(wrong_way, ApiErrorId.ERR_LEDGER_SIGN_MISMATCH.value, 422)

    other_way = api.create_fee_adjustment(
        base.owner_id,
        f.fee_adjustment_payload(
            entry_type=ENTRY_CIVIL_PENALTY,
            amount_cents=-5000,
            memo="Wrong sign the other way",
        ),
        program.admin,
    )
    validate_error(other_way, ApiErrorId.ERR_LEDGER_SIGN_MISMATCH.value, 422)

    _rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 0
    assert_cents(program.get_owner(base.owner_id)["fee_balance_cents"], 0, "fee_balance_cents")


def test_a_zero_amount_is_caught_as_a_malformed_request_not_a_sign_mismatch(
    api, program, base
):
    """The amount is judged for shape before it is judged for sign.

    PRD 2.5: "This layer catches a non-positive `height_ft`, a negative `population_at_risk`, a `requested_release_cfs` that is zero or negative, an `amount_cents` of exactly zero, and any unknown enum member."

    Design: Corner/validations/fee_adjustment_rejected_for_sign_mismatch_and_zero_amount_returns_invalid_request
    """
    response = api.create_fee_adjustment(
        base.owner_id,
        f.fee_adjustment_payload(
            entry_type=ENTRY_PAYMENT_RECEIVED, amount_cents=0, memo="Nothing at all"
        ),
        program.admin,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 0


def test_a_correctly_signed_penalty_posts_and_crosses_the_delinquency_threshold(
    program, base
):
    """Thirty thousand cents owed is above the inclusive threshold, so the owner is delinquent.

    PRD 3.8: "`delinquency_status` is a pure function of the replayed balance and is recomputed on every posting: it reads `DELINQUENT` when `fee_balance_cents` is at or above 25,000 cents — two hundred and fifty dollars, and the threshold is inclusive, so a balance of exactly 25,000 cents is delinquent — and `CURRENT` otherwise."

    Design: Corner/validations/fee_adjustment_rejected_for_sign_mismatch_and_zero_amount_returns_invalid_request
    """
    posted = program.post_ledger_entry(
        base.owner_id,
        entry_type=ENTRY_CIVIL_PENALTY,
        amount_cents=30_000,
        memo="Correctly signed penalty",
    )
    assert posted["sequence_no"] == 1
    assert_cents(posted["balance_after_cents"], 30000, "balance_after_cents")

    owner = program.get_owner(base.owner_id)
    assert_cents(owner["fee_balance_cents"], 30000, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_DELINQUENT

    _rows, meta = program.ledger(base.owner_id)
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Rung 21: certification is measured against the dam's current class
# ---------------------------------------------------------------------------
@pytest.fixture()
def high_dam_and_low_engineer(program, base):
    """A HIGH dam plus a third engineer whose certification stops at LOW."""
    certified = program.classify(base.dam_id, base.engineer_a_id, f.assessment_a4)
    low_only = program.create_engineer(
        full_name="Marta Boone",
        license_number="PE-61055",
        license_expires_at="2029-12-31T00:00:00Z",
        certified_hazard_classes=[HAZARD_LOW],
    )
    return {"certified": certified, "low_only": low_only}


def test_a_low_only_engineer_cannot_be_sent_to_a_high_hazard_dam(
    api, program, base, high_dam_and_low_engineer
):
    """The check reads the dam's published class, so the visit is never reserved.

    PRD 2.5: "**Engineer hazard certification** — the dam's hazard class is among the engineer's certified classes; otherwise `ERR_ENGINEER_NOT_CERTIFIED` (422)."

    Design: Corner/validations/inspection_rejected_for_an_engineer_not_certified_for_the_hazard_class
    """
    low_only_id = high_dam_and_low_engineer["low_only"]["id"]
    assert program.get_dam(base.dam_id)["hazard_class"] == HAZARD_HIGH

    response = api.create_inspection(
        f.inspection_payload(base.dam_id, low_only_id), program.admin
    )
    validate_error(response, ApiErrorId.ERR_ENGINEER_NOT_CERTIFIED.value, 422)

    _rows, meta = validate_paginated(
        api.list_inspections(program.admin, {"engineer_id": low_only_id})
    )
    assert meta["total_count"] == 0
    assert program.get_engineer(low_only_id)["open_inspection_count"] == 0


def test_the_fully_certified_engineer_takes_the_same_window(
    program, base, high_dam_and_low_engineer
):
    """Only the nominated engineer changed, and that is enough for the visit to stand.

    PRD 3.3: "A dam that has never been classified cannot be scheduled at all, which surfaces as `ERR_DAM_UNCLASSIFIED`; the nominated engineer's licence must be active and their certification must cover the dam's hazard class."

    Design: Corner/validations/inspection_rejected_for_an_engineer_not_certified_for_the_hazard_class
    """
    scheduled = program.schedule_inspection(base.dam_id, base.engineer_a_id)
    assert scheduled["status"] == INSPECTION_SCHEDULED
    assert scheduled["engineer_id"] == base.engineer_a_id

    # The same LOW-holding rule let the dam be certified while it was unclassified.
    assert high_dam_and_low_engineer["certified"]["status"] == ASSESSMENT_CERTIFIED
    assert program.get_engineer(base.engineer_a_id)["open_inspection_count"] == 1
