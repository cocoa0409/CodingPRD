"""Compensating pairs: releasing a provider and releasing an IEP seat.

Two of this system's figures are defined as recomputations over a current set
rather than as running totals, and the PRD turns that into an exactness
requirement. Releasing a provider from a service line must restore that
provider's minute ledger and capacity posture to precisely the values it held
before the line was staffed (PRD §2.9, PRD §3.8), and a community site's
reserved IEP seat count must return to precisely its earlier value once a family
refuses the plan that reserved the seat, leaving the seat re-reservable exactly
once (PRD §3.9).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fields_absent,
    assert_ledger_restored,
    assert_provider_minute_ledger,
    assert_service_line,
    assert_subset,
    minute_ledger,
)
from test_helpers.constants import (
    expected_assigned_minutes,
    expected_travel_overhead,
)
from test_helpers.test_users import TEST_USERS, make_parent_headers

COORDINATOR = TEST_USERS["coordinator_headers"]
PLACEMENT = TEST_USERS["placement_headers"]

FIRST_LINE_MINUTES = 150
SECOND_LINE_MINUTES = 140
MINUTE_CEILING = 400


# --------------------------------------------------------------- local setup helpers
def _two_line_plan_staffed_across_two_sites(api):
    """One provider staffed to two DIRECT lines delivered at two distinct sites.

    The first line is delivered at the plan's own community site and the second at
    a partner site, so the provider's travel overhead carries the per-location
    supplement of PRD §3.8 as well as its percentage tier.
    """
    home_site = fx.register_site(api)
    partner_site = fx.register_site(api)
    context = fx.setup_draft_plan(
        api, setting="COMMUNITY_PRESCHOOL", community_site_id=home_site["id"]
    )
    plan_id = context["plan"]["id"]
    first_line = fx.add_line(
        api,
        plan_id,
        discipline="SLP",
        weekly_minutes=FIRST_LINE_MINUTES,
        delivery_model="DIRECT",
    )
    second_line = fx.add_line(
        api,
        plan_id,
        discipline="SLP",
        weekly_minutes=SECOND_LINE_MINUTES,
        delivery_model="DIRECT",
    )
    provider = fx.register_provider(
        api, discipline="SLP", max_weekly_service_minutes=MINUTE_CEILING
    )
    fx.staff_line(api, first_line["id"], provider["id"], delivery_site_id=home_site["id"])

    # The ledger to which the second staffing must later be undone.
    before = fx.read_provider(api, provider["id"])
    assert_provider_minute_ledger(
        before,
        FIRST_LINE_MINUTES,
        expected_travel_overhead(FIRST_LINE_MINUTES, 1),
        expected_assigned_minutes(FIRST_LINE_MINUTES, 1),
        "OPEN",
    )

    second_line = fx.staff_line(
        api, second_line["id"], provider["id"], delivery_site_id=partner_site["id"]
    )
    context.update(
        {
            "home_site": home_site,
            "partner_site": partner_site,
            "first_line": first_line,
            "second_line": second_line,
            "provider": provider,
            "before": before,
        }
    )
    return context


def _two_draft_plans_competing_for_one_iep_seat(api):
    """Two DRAFT community-preschool plans naming a site with a single IEP seat.

    Each plan carries its own STAFFED line and its own provider, so the only rule
    left to separate them at submission is the site's seat count.
    """
    site = fx.register_site(api, iep_seat_capacity=1)
    first_provider = fx.register_provider(
        api, discipline="SLP", max_weekly_service_minutes=MINUTE_CEILING
    )
    second_provider = fx.register_provider(
        api, discipline="SLP", max_weekly_service_minutes=MINUTE_CEILING
    )
    first = fx.setup_staffed_draft_plan(
        api,
        setting="COMMUNITY_PRESCHOOL",
        community_site_id=site["id"],
        discipline="SLP",
        weekly_minutes=FIRST_LINE_MINUTES,
        delivery_model="DIRECT",
        provider=first_provider,
    )
    second = fx.setup_staffed_draft_plan(
        api,
        setting="COMMUNITY_PRESCHOOL",
        community_site_id=site["id"],
        discipline="SLP",
        weekly_minutes=FIRST_LINE_MINUTES,
        delivery_model="DIRECT",
        provider=second_provider,
    )
    assert fx.read_site(api, site["id"])["reserved_iep_seat_count"] == 0, (
        "a plan still at DRAFT holds no seat"
    )
    return {
        "site": site,
        "first": first,
        "second": second,
        "first_provider": first_provider,
        "second_provider": second_provider,
    }


# =====================================================================================
# Unstaffing restores the released provider's exact pre-staffing ledger
# =====================================================================================
def test_unstaffing_restores_the_providers_exact_minute_figures_and_posture(api):
    """Releasing the second line returns every figure to its pre-staffing value.

    PRD §2.9: "The consequence, and the requirement, is that releasing a provider from
    a line restores that provider's minute figures and capacity posture to exactly the
    values they held before the line was staffed, with no residue."

    PRD §3.8 pins the arithmetic being undone: "The tier is never re-chosen after the
    travel minutes have been added: a provider with 290 direct minutes across two
    distinct locations draws the 5 percent tier from 290, giving 14.5 plus 15, which is
    29.5, rounded up to 30, for an assigned total of 320 — and not the 335 that would
    follow from re-reading the tier against 320.", and the posture: "The ratio is
    compared as an exact decimal and never pre-rounded, so a provider at 320 assigned
    minutes against a 400-minute ceiling sits exactly on eight tenths and is
    `NEAR_CAPACITY`."

    PRD §3.8 on the release itself: "It moves the line to `UNSTAFFED`, clears both
    `provider_id` and `delivery_site_id`, recomputes the released provider's three
    minute figures and re-derives that provider's `service_capacity_posture`, and
    increments both the provider's `version` and the line's `version`."

    Design: Difficulty/compensating_invariant/unstaffing_restores_the_providers_exact_pre_staffing_minute_and_travel_figures
    """
    context = _two_line_plan_staffed_across_two_sites(api)
    provider_id = context["provider"]["id"]
    second_line = context["second_line"]
    before = context["before"]

    loaded = fx.read_provider(api, provider_id)
    assert_provider_minute_ledger(loaded, 290, 30, 320, "NEAR_CAPACITY")
    assert fx.read_caseload(api, provider_id)["distinct_site_count"] == 2

    released = validate_success(
        api.unstaff_service_line(
            second_line["id"], f.unstaffing_payload("Provider reassigned"), PLACEMENT
        ),
        200,
    )
    assert_service_line(released, expected_version=second_line["version"] + 1)
    assert released["status"] == "UNSTAFFED"
    assert_fields_absent(released, "provider_id", "delivery_site_id")

    after = fx.read_provider(api, provider_id)
    assert_ledger_restored(minute_ledger(before), minute_ledger(after))
    assert_provider_minute_ledger(
        after,
        FIRST_LINE_MINUTES,
        expected_travel_overhead(FIRST_LINE_MINUTES, 1),
        expected_assigned_minutes(FIRST_LINE_MINUTES, 1),
        "OPEN",
    )
    assert after["version"] == loaded["version"] + 1, (
        "the release increments the provider's version exactly once"
    )
    caseload = fx.read_caseload(api, provider_id)
    assert_subset(
        caseload,
        {
            "provider_id": provider_id,
            "direct_weekly_service_minutes": FIRST_LINE_MINUTES,
            "distinct_site_count": 1,
            "travel_overhead_minutes": expected_travel_overhead(FIRST_LINE_MINUTES, 1),
            "assigned_weekly_service_minutes": expected_assigned_minutes(FIRST_LINE_MINUTES, 1),
            "service_capacity_posture": "OPEN",
            "max_weekly_service_minutes": MINUTE_CEILING,
        },
    )


def test_unstaffing_leaves_the_parent_plans_committed_total_alone(api):
    """The plan total is deliberately not part of what unstaffing gives back.

    PRD §3.8: "The parent plan's `assigned_weekly_minutes` is deliberately **unchanged**
    by unstaffing, because an `UNSTAFFED` line is still a commitment the plan has made
    and still counts toward the plan total."

    PRD §2.9: "The consequence, and the requirement, is that releasing a provider from a
    line restores that provider's minute figures and capacity posture to exactly the
    values they held before the line was staffed, with no residue."

    Design: Difficulty/compensating_invariant/unstaffing_restores_the_providers_exact_pre_staffing_minute_and_travel_figures
    """
    context = _two_line_plan_staffed_across_two_sites(api)
    plan_id = context["plan"]["id"]
    committed = FIRST_LINE_MINUTES + SECOND_LINE_MINUTES

    staffed_plan = fx.read_plan(api, plan_id)
    assert_subset(
        staffed_plan, {"status": "DRAFT", "assigned_weekly_minutes": committed}
    )

    fx.unstaff_line(api, context["second_line"]["id"], unstaff_reason="Provider reassigned")

    after_plan = fx.read_plan(api, plan_id)
    assert_subset(after_plan, {"status": "DRAFT", "assigned_weekly_minutes": committed})
    assert fx.read_provider(api, context["provider"]["id"])[
        "direct_weekly_service_minutes"
    ] == FIRST_LINE_MINUTES, (
        "the released line stops contributing to the provider even though the plan keeps it"
    )

    rows, meta = validate_paginated(
        api.list_service_lines(PLACEMENT, {"service_plan_id": plan_id})
    )
    assert meta["total_count"] == 2, f"both lines survive the release: {rows}"
    statuses = sorted(row["status"] for row in rows)
    assert statuses == ["STAFFED", "UNSTAFFED"], statuses


def test_restaffing_the_released_line_reproduces_the_same_loaded_ledger(api):
    """The release-and-restaff loop is exactly reversible in both directions.

    PRD §3.8: "Releasing a provider is the sanctioned reverse move, and the pair
    `STAFFED → UNSTAFFED → STAFFED` is a legitimate re-assignment loop that a line may
    travel repeatedly."

    PRD §3.8: "`travel_overhead_minutes` is then the direct total multiplied by the
    chosen percentage, plus 15 minutes for each location beyond the first, with that
    **whole** expression rounded up once to the next multiple of five — the percentage
    part and the per-location part are never rounded separately."

    Design: Difficulty/compensating_invariant/unstaffing_restores_the_providers_exact_pre_staffing_minute_and_travel_figures
    """
    context = _two_line_plan_staffed_across_two_sites(api)
    provider_id = context["provider"]["id"]
    partner_site_id = context["partner_site"]["id"]
    loaded = minute_ledger(fx.read_provider(api, provider_id))

    fx.unstaff_line(api, context["second_line"]["id"])
    assert_ledger_restored(
        minute_ledger(context["before"]), minute_ledger(fx.read_provider(api, provider_id))
    )

    restaffed = fx.staff_line(
        api,
        context["second_line"]["id"],
        provider_id,
        delivery_site_id=partner_site_id,
    )
    assert_subset(
        restaffed,
        {
            "status": "STAFFED",
            "provider_id": provider_id,
            "delivery_site_id": partner_site_id,
        },
    )
    reloaded = fx.read_provider(api, provider_id)
    assert_ledger_restored(loaded, minute_ledger(reloaded))
    assert_provider_minute_ledger(
        reloaded,
        FIRST_LINE_MINUTES + SECOND_LINE_MINUTES,
        expected_travel_overhead(FIRST_LINE_MINUTES + SECOND_LINE_MINUTES, 2),
        expected_assigned_minutes(FIRST_LINE_MINUTES + SECOND_LINE_MINUTES, 2),
        "NEAR_CAPACITY",
    )
    assert fx.read_caseload(api, provider_id)["distinct_site_count"] == 2


# =====================================================================================
# The reserved IEP seat count is conserved across reservation, refusal and re-reservation
# =====================================================================================
def test_only_the_first_plan_submitted_takes_the_sites_single_iep_seat(api):
    """Two DRAFT plans may both name the site; submission is what consumes the seat.

    PRD §3.9: "Only the community-preschool branch reserves a seat: on a successful
    submission the named site's `reserved_iep_seat_count` increases by exactly one.",
    and "`reserved_iep_seat_count` is, by definition, the number of service plans naming
    that site whose `status` is `PENDING_PARENT_CONSENT` or `ACTIVE`; a plan still at
    `DRAFT` holds no seat".

    PRD §3.9: "A submission naming a site whose `reserved_iep_seat_count` has already
    reached its `iep_seat_capacity` is refused with `ERR_IEP_SEAT_CAPACITY_EXCEEDED`.
    Because reservation begins at submission rather than at drafting, two draft plans can
    both name a site with a single free seat and coexist quite legitimately — and only
    the first of them to be submitted for consent succeeds."

    PRD §3.9: "On a successful submission the child's derived `status` is recomputed and
    deliberately stays `IN_EVALUATION`: a plan the family has not yet consented to is
    not yet a service."

    Design: Difficulty/compensating_invariant/iep_seat_count_is_conserved_across_reservation_refusal_and_re_reservation
    """
    context = _two_draft_plans_competing_for_one_iep_seat(api)
    site_id = context["site"]["id"]
    first_plan = context["first"]["plan"]
    second_plan = context["second"]["plan"]

    record = fx.submit_plan(api, first_plan["id"])
    assert_subset(
        record,
        {
            "kind": "SERVICE_CONSENT",
            "decision": "PENDING",
            "service_plan_id": first_plan["id"],
        },
    )
    assert fx.read_plan(api, first_plan["id"])["status"] == "PENDING_PARENT_CONSENT"
    assert fx.read_site(api, site_id)["reserved_iep_seat_count"] == 1
    assert fx.read_child(api, context["first"]["child"]["id"])["status"] == "IN_EVALUATION"

    response = api.submit_plan_for_consent(
        second_plan["id"], f.consent_submission_payload(), PLACEMENT
    )
    validate_error(response, ApiErrorId.ERR_IEP_SEAT_CAPACITY_EXCEEDED.value)

    refused_plan = fx.read_plan(api, second_plan["id"])
    assert_subset(
        refused_plan, {"status": "DRAFT", "version": second_plan["version"]}
    )
    assert fx.read_site(api, site_id)["reserved_iep_seat_count"] == 1, (
        "the refused submission consumes nothing"
    )
    rows, meta = validate_paginated(
        api.list_consent_records(COORDINATOR, {"service_plan_id": second_plan["id"]})
    )
    assert meta["total_count"] == 0, f"no service-consent record for the refused plan: {rows}"


def test_a_refused_service_consent_releases_the_seat_and_the_providers_minutes(api):
    """The four-step unwind returns the seat count to exactly its pre-submission value.

    PRD §3.9: "`REFUSED` on a service-consent record moves the plan
    `PENDING_PARENT_CONSENT → DECLINED` and unwinds the commitment in four steps: every
    service line of the plan standing at `PROPOSED`, `STAFFED` or `UNSTAFFED` moves to
    `DISCONTINUED`; for each line that left `STAFFED`, its provider's
    `direct_weekly_service_minutes`, `travel_overhead_minutes` and
    `assigned_weekly_service_minutes` are recomputed; each affected provider's
    `service_capacity_posture` is then re-derived from the new assigned total; and, on
    the community-preschool branch only, the named site's `reserved_iep_seat_count`
    decreases by one. The child's derived `status` becomes `SERVICES_DECLINED`, and the
    plan's `version` increments."

    PRD §2.9: "Two quantities in this system are conserved: a community site's
    `reserved_iep_seat_count` and a provider's assigned weekly minutes."

    Design: Difficulty/compensating_invariant/iep_seat_count_is_conserved_across_reservation_refusal_and_re_reservation
    """
    context = _two_draft_plans_competing_for_one_iep_seat(api)
    site_id = context["site"]["id"]
    first_plan = context["first"]["plan"]
    child_id = context["first"]["child"]["id"]
    provider_id = context["first_provider"]["id"]

    fx.submit_plan(api, first_plan["id"])
    submitted = fx.read_plan(api, first_plan["id"])
    assert fx.read_site(api, site_id)["reserved_iep_seat_count"] == 1
    assert_provider_minute_ledger(
        fx.read_provider(api, provider_id),
        FIRST_LINE_MINUTES,
        expected_travel_overhead(FIRST_LINE_MINUTES, 1),
        expected_assigned_minutes(FIRST_LINE_MINUTES, 1),
        "OPEN",
    )

    record = fx.consent_record_for_plan(api, first_plan["id"])
    refused = fx.decide_consent(
        api, record["id"], "REFUSED", headers=make_parent_headers(child_id)
    )
    assert refused["decision"] == "REFUSED"

    declined = fx.read_plan(api, first_plan["id"])
    assert_subset(declined, {"status": "DECLINED", "version": submitted["version"] + 1})
    assert fx.read_line(api, context["first"]["line"]["id"])["status"] == "DISCONTINUED"
    assert_provider_minute_ledger(fx.read_provider(api, provider_id), 0, 0, 0, "OPEN")
    assert fx.read_site(api, site_id)["reserved_iep_seat_count"] == 0, (
        "the seat count returns to exactly the value it held before submission"
    )
    assert fx.read_child(api, child_id)["status"] == "SERVICES_DECLINED"


def test_the_released_iep_seat_can_be_re_reserved_exactly_once(api):
    """After the refusal the previously locked-out plan may take the freed seat.

    PRD §3.9: "`reserved_iep_seat_count` is, by definition, the number of service plans
    naming that site whose `status` is `PENDING_PARENT_CONSENT` or `ACTIVE`; a plan still
    at `DRAFT` holds no seat, and a plan that has reached `DECLINED`, `SUPERSEDED`,
    `EXITED_TO_KINDERGARTEN` or `CLOSED_NOT_ELIGIBLE` has released its seat."

    PRD §3.9: "The submission creates a second `ConsentRecord`, this one with `kind` of
    `SERVICE_CONSENT`, `decision` at `PENDING`, `requested_at` from the logical clock,
    `service_plan_id` set to this plan, and `referral_id` set to the referral behind the
    plan's evaluation case. The plan moves `DRAFT → PENDING_PARENT_CONSENT`", and "A
    submission naming a site whose `reserved_iep_seat_count` has already reached its
    `iep_seat_capacity` is refused with `ERR_IEP_SEAT_CAPACITY_EXCEEDED`."

    Design: Difficulty/compensating_invariant/iep_seat_count_is_conserved_across_reservation_refusal_and_re_reservation
    """
    context = _two_draft_plans_competing_for_one_iep_seat(api)
    site_id = context["site"]["id"]
    first_plan = context["first"]["plan"]
    second_plan = context["second"]["plan"]

    fx.submit_plan(api, first_plan["id"])
    validate_error(
        api.submit_plan_for_consent(
            second_plan["id"], f.consent_submission_payload(), PLACEMENT
        ),
        ApiErrorId.ERR_IEP_SEAT_CAPACITY_EXCEEDED.value,
    )

    record = fx.consent_record_for_plan(api, first_plan["id"])
    fx.decide_consent(
        api,
        record["id"],
        "REFUSED",
        headers=make_parent_headers(context["first"]["child"]["id"]),
    )
    assert fx.read_site(api, site_id)["reserved_iep_seat_count"] == 0

    second_record = validate_success(
        api.submit_plan_for_consent(
            second_plan["id"], f.consent_submission_payload(), PLACEMENT
        ),
        201,
    )
    assert_subset(
        second_record,
        {
            "kind": "SERVICE_CONSENT",
            "decision": "PENDING",
            "service_plan_id": second_plan["id"],
            "referral_id": context["second"]["referral"]["id"],
            "version": 1,
        },
    )
    assert fx.read_plan(api, second_plan["id"])["status"] == "PENDING_PARENT_CONSENT"
    assert fx.read_site(api, site_id)["reserved_iep_seat_count"] == 1, (
        "the freed seat is re-reservable, and only once"
    )
    assert fx.read_child(api, context["second"]["child"]["id"])["status"] == "IN_EVALUATION"
    assert fx.read_plan(api, first_plan["id"])["status"] == "DECLINED"
