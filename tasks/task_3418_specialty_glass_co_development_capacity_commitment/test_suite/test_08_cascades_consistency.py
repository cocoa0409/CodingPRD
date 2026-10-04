"""Cross-entity cascades and the immediate-consistency discipline.

Covers the four-hop composition-retire cascade (PRD section 3.3), the
program-termination cascade (PRD section 3.2), the confirmed-infringement
cascade onto licenses and usage reports (PRD section 3.1), the
same-request reconciliation of denormalized fields, and the conserved campaign
supply invariant across an allocate/release pair (PRD section 3.6).
"""

from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_campaign_supply_conservation,
    create_usage_report,
    factories,
    fulfill_allocation,
    get_commitment_version,
    ip_review,
    release_allocation,
    set_clock,
    setup_approved_marketing_license,
    setup_running_supply_chain,
    setup_supply_chain,
    setup_supply_chain_with_allocation,
    shift_iso,
    validate_created,
    validate_success,
    get_success_data,
)

MANAGER = TEST_USERS["program_manager_headers"]
PLANNER = TEST_USERS["capacity_planner_headers"]
LEGAL = TEST_USERS["legal_counsel_headers"]


def _parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_composition_retire_cascade_reaches_breach_watch_and_demotion():
    """PRD section 3.3: "Hop one: every `SCHEDULED` campaign over this
    composition is `CANCELLED` ... Hop two: every `RESERVED` allocation held by
    those cancelled campaigns transitions to `RELEASED`, and each affected
    campaign's `unallocated_units` is increased by the released units. Hop
    three: ... if it has fallen below 1.0 (CONST.SUPPLY_COVERAGE_MIN) the
    commitment moves from `SECURED` to `BREACH_WATCH` with a `breach_deadline`
    set to the current logical clock plus 90 days (CONST.BREACH_GRACE_DAYS).
    Hop four: ... its device maker's `standing_tier` is demoted one step, per
    the demotion ladder in section 3.1."

    Design: Difficulty/transitive_cascade/composition_retire_cascade_reaches_breach_watch_and_demotion
    """
    chain = setup_supply_chain_with_allocation(
        alloc_units=5000, standing_tier="STRATEGIC"
    )
    set_clock("2028-03-01T00:00:00Z")
    retired = validate_success(
        api_client.retire_composition(chain.composition["id"], headers=MANAGER)
    )
    assert retired["status"] == "RETIRED"

    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], MANAGER))
    assert campaign["status"] == "CANCELLED"
    assert campaign["unallocated_units"] == 6200  # 1200 + 5000 restored
    allocation = get_success_data(api_client.get_allocation(chain.allocation["id"], MANAGER))
    assert allocation["status"] == "RELEASED"

    commitment = get_success_data(api_client.get_commitment(chain.commitment["id"], MANAGER))
    assert commitment["status"] == "BREACH_WATCH"  # coverage fell to 0
    expected_deadline = shift_iso("2028-03-01T00:00:00Z", days=90)
    assert _parse(commitment["breach_deadline"]) == _parse(expected_deadline)

    maker = get_success_data(api_client.get_device_maker(chain.maker["id"], MANAGER))
    assert maker["standing_tier"] == "STANDARD"  # STRATEGIC demoted one step


def test_program_terminate_releases_commitments_and_cancels_campaigns():
    """PRD section 3.2: "Hop one releases every commitment of the program in
    `PROPOSED`, `SIGNED`, `COUNTERSIGNED`, `SECURED`, or `BREACH_WATCH`: each
    such commitment moves to `RELEASED`, its `prepayment_refunded_cents` is
    increased by its `prepayment_remaining_cents`, and its
    `prepayment_remaining_cents` is then set to zero. The same hop cancels
    every `SCHEDULED` campaign over the program's compositions. Hop two
    releases every `RESERVED` allocation held by those cancelled campaigns."

    Design: Corner/state_machines/program_terminate_releases_commitments_and_cancels_campaigns
    """
    chain = setup_supply_chain_with_allocation(alloc_units=5000)
    resp = api_client.terminate_program(
        chain.program["id"], MANAGER, {"reason": "strategic pivot"}
    )
    validate_success(resp)

    commitment = get_success_data(api_client.get_commitment(chain.commitment["id"], MANAGER))
    assert commitment["status"] == "RELEASED"
    assert commitment["prepayment_refunded_cents"] == 2500000
    assert commitment["prepayment_remaining_cents"] == 0

    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], MANAGER))
    assert campaign["status"] == "CANCELLED"
    assert campaign["unallocated_units"] == 6200
    allocation = get_success_data(api_client.get_allocation(chain.allocation["id"], MANAGER))
    assert allocation["status"] == "RELEASED"


def test_ip_confirmation_cascade_suspends_license_and_holds_report():
    """PRD section 3.1: "Hop one: every License whose `device_maker_id` is
    this maker and whose `license_status` is `ACTIVE` transitions to
    `SUSPENDED`, with `suspension_reason` set to `IP_REVIEW`. Hop two: for each
    license suspended in hop one, every UsageReport of that license still in
    `SUBMITTED` transitions to `HELD`."

    Design: Difficulty/transitive_cascade/ip_confirmation_cascade_suspends_license_and_holds_report
    """
    chain = setup_approved_marketing_license()
    report = create_usage_report(chain.license, chain.maker)  # SUBMITTED
    ip_review(chain.maker, "UNDER_REVIEW")
    validate_success(
        api_client.ip_review_device_maker(
            chain.maker["id"], factories.ip_review_payload("CONFIRMED_INFRINGEMENT"), LEGAL
        )
    )

    license_ = get_success_data(api_client.get_license(chain.license["id"], LEGAL))
    assert license_["license_status"] == "SUSPENDED"
    assert license_["suspension_reason"] == "IP_REVIEW"
    report = get_success_data(api_client.get_usage_report(report["id"], LEGAL))
    assert report["status"] == "HELD"
    maker = get_success_data(api_client.get_device_maker(chain.maker["id"], LEGAL))
    assert maker["ip_review_status"] == "CONFIRMED_INFRINGEMENT"


def test_derived_fields_reconcile_immediately_on_allocate_and_fulfill():
    """PRD section 3.4: "`supply_coverage`: the sum of `units` over its
    allocations in `RESERVED` or `FULFILLED`, divided by `committed_units`,
    stored at four decimal places rounded half up". PRD section 3.6:
    "fulfillment adds the allocation's `units` into the commitment's
    `fulfilled_units` and recomputes `supply_coverage`". Allocating 2000 of
    5000 committed gives coverage 0.4 and leaves 4200 unallocated; fulfilling
    the same allocation moves the units into fulfilled_units while coverage
    stays 0.4.

    Design: Corner/cross_cutting_layers/derived_fields_reconcile_immediately_on_allocate_and_fulfill
    """
    chain = setup_running_supply_chain()
    allocation = validate_created(
        api_client.create_allocation(
            factories.create_allocation_payload(
                chain.commitment["id"],
                chain.campaign["id"],
                expected_commitment_version=get_commitment_version(chain.commitment["id"]),
                units=2000,
            ),
            PLANNER,
        )
    )
    commitment = get_success_data(api_client.get_commitment(chain.commitment["id"], PLANNER))
    assert commitment["supply_coverage"] == pytest.approx(0.4)  # 2000 / 5000
    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["unallocated_units"] == 4200  # 6200 - 2000

    fulfill_allocation(allocation)
    commitment = get_success_data(api_client.get_commitment(chain.commitment["id"], PLANNER))
    assert commitment["fulfilled_units"] == 2000
    assert commitment["supply_coverage"] == pytest.approx(0.4)


def test_immediate_visibility_without_checkpoint():
    """PRD section 3.6: "A successful creation decrements the campaign's
    `unallocated_units` by the allocated `units`" — the very next read shows
    the mutation; no operations checkpoint intervenes (PRD section 2.4 gates
    only time-driven transitions behind the sweep).

    Design: Corner/consistency_model/immediate_visibility_without_checkpoint
    """
    chain = setup_supply_chain()
    validate_created(
        api_client.create_allocation(
            factories.create_allocation_payload(
                chain.commitment["id"],
                chain.campaign["id"],
                expected_commitment_version=get_commitment_version(chain.commitment["id"]),
                units=1000,
            ),
            PLANNER,
        )
    )
    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["unallocated_units"] == 5200  # 6200 - 1000


def test_campaign_headroom_conserved_under_allocate_release():
    """PRD section 3.5: "The campaign's `expected_good_units` is
    `planned_units` multiplied by that provisional rate, floored to a whole
    unit, and fixed at creation — it is the allocatable supply pool, and the
    campaign's `unallocated_units` starts equal to it." PRD section 3.6:
    "Releasing it moves the allocation from `RESERVED` to `RELEASED` ...
    restoring the allocation's `units` to the campaign's `unallocated_units`".
    The forward/compensating pair leaves the conserved supply quantity
    unchanged at every step.

    Design: Difficulty/compensating_invariant/campaign_headroom_conserved_under_allocate_release
    """
    chain = setup_supply_chain()
    assert chain.campaign["expected_good_units"] == 6200
    assert chain.campaign["unallocated_units"] == 6200

    allocation = validate_created(
        api_client.create_allocation(
            factories.create_allocation_payload(
                chain.commitment["id"],
                chain.campaign["id"],
                expected_commitment_version=get_commitment_version(chain.commitment["id"]),
                units=5000,
            ),
            PLANNER,
        )
    )
    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["unallocated_units"] == 1200
    assert_campaign_supply_conservation(campaign, [allocation])

    released = validate_success(api_client.release_allocation(allocation["id"], headers=PLANNER))
    assert released["status"] == "RELEASED"
    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["unallocated_units"] == 6200
    assert_campaign_supply_conservation(campaign, [released])
