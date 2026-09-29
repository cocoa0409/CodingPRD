"""State-machine transitions: initial states, inadmissible repeats, terminal
states, the production fork and join, and the cancellation cascades.
"""

from test_helpers import (
    CONSULTANT_USER_ID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    validate_error,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["manufacturer_admin_headers"]
CONSULTANT = TEST_USERS["design_consultant_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _setup_ordered_project_with_scheduled_job(
    pledge_amount_cents=400000, installer_overrides=None
):
    """An ORDERED project funded by one collected pledge, with one ACTIVE
    installer holding a SCHEDULED job over 2026-08-06 .. 2026-08-08 at crew
    size 4, so the job books 12 crew-days.
    """
    scenario = fx.setup_ordered_project(pledge_amount_cents=pledge_amount_cents)
    installer = fx.create_installer(**(installer_overrides or {}))
    job = fx.book_job(
        scenario["order"]["id"],
        installer["id"],
        scheduled_start_date="2026-08-06",
        scheduled_end_date="2026-08-08",
        crew_size=4,
    )
    scenario["installer"] = fx.get_installer(installer["id"])
    scenario["job"] = job
    return scenario


def test_project_is_created_in_draft_with_every_counter_at_zero():
    """A newly opened project starts in DRAFT with all counters at zero.

    PRD: "The created project starts with `design_status` `DRAFT` and `compliance_status` `NOT_ASSESSED`, and it stores the acting consultant's `X-User-ID` in `consultant_user_id`"

    PRD: "Its counters start at zero: `revision_rounds` is 0, `funds_collected_cents` is 0, and all four allocation buckets — `alloc_permit_freight_cents`, `alloc_surfacing_cents`, `alloc_structure_cents` and `alloc_contingency_cents` — are 0."

    PRD: "Its `installed_on` is null and stays null until the day the installation passes inspection."

    Design: Corner/state_machines/project_initial_state_is_draft_until_consultation_starts
    """
    fx.create_active_standard()

    project = a.assert_object_envelope(
        api_client.create_project(
            f.project_payload(client_name="Rowan Commons"), CONSULTANT
        ),
        201,
    )

    a.assert_project(project)
    assert project["design_status"] == "DRAFT", (
        f"expected DRAFT, got {project['design_status']!r}"
    )
    assert project["compliance_status"] == "NOT_ASSESSED", (
        f"expected NOT_ASSESSED, got {project['compliance_status']!r}"
    )
    assert project["consultant_user_id"] == CONSULTANT_USER_ID, (
        f"expected the acting consultant {CONSULTANT_USER_ID!r}, got "
        f"{project['consultant_user_id']!r}"
    )
    assert project["revision_rounds"] == 0, (
        f"expected revision_rounds 0, got {project['revision_rounds']}"
    )
    assert project["funds_collected_cents"] == 0, (
        f"expected funds_collected_cents 0, got {project['funds_collected_cents']}"
    )
    for bucket in (
        "alloc_permit_freight_cents",
        "alloc_surfacing_cents",
        "alloc_structure_cents",
        "alloc_contingency_cents",
    ):
        assert project[bucket] == 0, f"expected {bucket} 0, got {project[bucket]}"
    assert project["installed_on"] is None, (
        f"expected a null installed_on, got {project['installed_on']!r}"
    )
    a.assert_common_fields(project, expected_version=1)


def test_design_content_becomes_editable_only_after_start_consultation():
    """A DRAFT project refuses design content; consultation opens the window.

    PRD: "Creating a play area, creating a placement, validating a placement and removing a placement are all permitted only while the owning project's `design_status` is `CONSULTATION` or `REVISION_REQUESTED`; in any other status they are refused with `ERR_PROJECT_NOT_EDITABLE`."

    PRD: "On success `design_status` becomes `CONSULTATION` and the project's `version` is incremented by one."

    Design: Corner/state_machines/project_initial_state_is_draft_until_consultation_starts
    """
    fx.create_active_standard()
    project = fx.create_project(client_name="Rowan Commons")

    refused = api_client.create_play_area(
        project["id"], f.play_area_payload(), CONSULTANT
    )
    validate_error(refused, ApiErrorId.ERR_PROJECT_NOT_EDITABLE.value, 409)

    opened = a.assert_object_envelope(
        api_client.start_consultation(project["id"], CONSULTANT)
    )
    assert opened["design_status"] == "CONSULTATION", (
        f"expected CONSULTATION, got {opened['design_status']!r}"
    )
    assert opened["version"] == 2, (
        f"starting the consultation bumps the project to version 2, got "
        f"{opened['version']}"
    )

    area = a.assert_object_envelope(
        api_client.create_play_area(project["id"], f.play_area_payload(), CONSULTANT),
        201,
    )
    assert area["status"] == "PLANNED", (
        f"the area created inside the window is PLANNED, got {area['status']!r}"
    )


def test_activating_a_second_edition_while_one_is_already_active_is_refused():
    """The registry admits at most one ACTIVE edition at any instant.

    PRD: "activating a genuine `DRAFT` while some other edition already sits in `ACTIVE` is rejected with `ERR_ACTIVE_STANDARD_EXISTS` — the registry admits at most one `ACTIVE` edition at any instant"

    Design: Corner/state_machines/standard_activate_blocked_while_another_edition_is_active
    """
    active = fx.create_active_standard()
    successor = fx.setup_draft_successor(
        effective_from="2026-01-01",
        min_use_zone_clearance_cm=213,
        requires_accessible_route=True,
    )

    response = api_client.activate_standard(successor["id"], OFFICER)

    validate_error(response, ApiErrorId.ERR_ACTIVE_STANDARD_EXISTS.value, 409)
    refused = a.assert_object_envelope(
        api_client.get_standard(successor["id"], OFFICER)
    )
    assert refused["status"] == "DRAFT", (
        f"the refused edition stays DRAFT, got {refused['status']!r}"
    )
    assert refused["version"] == 1, (
        f"a refused activation mutates nothing, got version {refused['version']}"
    )
    incumbent = a.assert_object_envelope(api_client.get_standard(active["id"], OFFICER))
    assert incumbent["status"] == "ACTIVE", (
        f"the incumbent stays ACTIVE, got {incumbent['status']!r}"
    )
    assert incumbent["superseded_by_standard_id"] is None, (
        f"the incumbent was not retired, got "
        f"{incumbent['superseded_by_standard_id']!r}"
    )
    a.assert_paginated_list(
        api_client.list_standards(OFFICER, params={"status": "ACTIVE"}),
        expected_total=1,
    )


def test_activating_an_already_active_edition_is_refused():
    """Activation is admissible only from DRAFT, so a repeat call fails.

    PRD: "Activating an edition whose status is anything other than `DRAFT` is rejected with `ERR_STANDARD_NOT_DRAFT`"

    PRD: "A successful activation sets `status` to `ACTIVE` and bumps the edition's `version` by one."

    Design: Corner/state_machines/standard_activate_twice_second_call_returns_standard_not_draft
    """
    standard = fx.create_active_standard()
    assert standard["version"] == 2, (
        f"the first activation bumps the edition to version 2, got "
        f"{standard['version']}"
    )

    response = api_client.activate_standard(standard["id"], OFFICER)

    validate_error(response, ApiErrorId.ERR_STANDARD_NOT_DRAFT.value, 409)
    after = a.assert_object_envelope(api_client.get_standard(standard["id"], OFFICER))
    assert after["status"] == "ACTIVE", (
        f"the edition stays ACTIVE, got {after['status']!r}"
    )
    assert after["version"] == 2, (
        f"the refused repeat leaves version at 2, got {after['version']}"
    )


def test_a_superseded_edition_accepts_neither_activation_nor_supersession():
    """SUPERSEDED is terminal: both triggers are refused from it.

    PRD: "Activating an edition whose status is anything other than `DRAFT` is rejected with `ERR_STANDARD_NOT_DRAFT`"

    PRD: "The edition being retired must itself be `ACTIVE`, or the request fails with `ERR_STANDARD_NOT_ACTIVE`"

    Design: Corner/state_machines/superseded_standard_is_terminal_for_activate_and_supersede
    """
    retired = fx.create_active_standard()
    successor = fx.setup_draft_successor(effective_from="2026-01-01")
    spare = fx.setup_draft_successor(edition_year=2030, effective_from="2026-02-01")
    fx.supersede_standard(retired["id"], successor["id"])

    reactivation = api_client.activate_standard(retired["id"], OFFICER)
    validate_error(reactivation, ApiErrorId.ERR_STANDARD_NOT_DRAFT.value, 409)

    resupersession = api_client.supersede_standard(
        retired["id"], f.supersede_payload(spare["id"]), OFFICER
    )
    validate_error(resupersession, ApiErrorId.ERR_STANDARD_NOT_ACTIVE.value, 409)

    after = a.assert_object_envelope(api_client.get_standard(retired["id"], OFFICER))
    assert after["status"] == "SUPERSEDED", (
        f"the retired edition stays SUPERSEDED, got {after['status']!r}"
    )
    assert after["superseded_by_standard_id"] == successor["id"], (
        f"expected the recorded successor {successor['id']}, got "
        f"{after['superseded_by_standard_id']}"
    )
    promoted = a.assert_object_envelope(
        api_client.get_standard(successor["id"], OFFICER)
    )
    assert promoted["status"] == "ACTIVE", (
        f"the successor holds ACTIVE, got {promoted['status']!r}"
    )
    untouched = a.assert_object_envelope(api_client.get_standard(spare["id"], OFFICER))
    assert untouched["status"] == "DRAFT", (
        f"the nominated spare stays DRAFT, got {untouched['status']!r}"
    )
    assert untouched["version"] == 1, (
        f"the refused nomination mutates nothing, got version {untouched['version']}"
    )


def test_validating_an_already_validated_placement_is_refused():
    """Validation is admissible only from DRAFT, so the second call fails.

    PRD: "The placement itself must be in `DRAFT`; validating one that is already `VALIDATED`, or one that has been demoted to `NEEDS_RECERTIFICATION`, is refused with `ERR_PLACEMENT_INVALID_STATE`."

    PRD: "`PLANNED` becomes `ZONED` automatically the moment the area's first placement reaches `VALIDATED`"

    Design: Corner/state_machines/placement_validate_twice_second_call_returns_placement_invalid_state
    """
    scenario = fx.setup_project_with_toddler_area()
    area_id = scenario["area"]["id"]
    placement = fx.create_validated_placement(
        area_id,
        scenario["post"]["id"],
        color_choice="FOREST_GREEN",
        x_start_cm=200,
        quantity=3,
    )
    zoned_area = fx.get_play_area(area_id)

    response = api_client.validate_placement(placement["id"], CONSULTANT)

    validate_error(response, ApiErrorId.ERR_PLACEMENT_INVALID_STATE.value, 409)
    after = a.assert_object_envelope(
        api_client.get_placement(placement["id"], CONSULTANT)
    )
    assert after["status"] == "VALIDATED", (
        f"the placement stays VALIDATED, got {after['status']!r}"
    )
    assert after["version"] == placement["version"], (
        f"the refused repeat mutates nothing, expected version "
        f"{placement['version']}, got {after['version']}"
    )
    area = a.assert_object_envelope(api_client.get_play_area(area_id, CONSULTANT))
    assert area["status"] == "ZONED", (
        f"the area stays ZONED after its first validation, got {area['status']!r}"
    )
    assert area["critical_fall_height_cm"] == 0, (
        f"a ground-level component contributes no fall height, got "
        f"{area['critical_fall_height_cm']}"
    )
    a.assert_required_surfacing_depth(area, "CLAY")
    a.assert_required_surfacing_depth(area, "CLAY", expected=15)
    assert area["version"] == zoned_area["version"], (
        f"the refused repeat does not bump the area again, expected version "
        f"{zoned_area['version']}, got {area['version']}"
    )


def test_close_review_from_a_rendered_project_is_refused_on_project_state():
    """A review cannot be closed before the project reaches community review.

    PRD: "The rendering must still be `ISSUED` (otherwise `ERR_RENDERING_NOT_ISSUED`) and the project must be in `COMMUNITY_REVIEW`."

    PRD: "A trigger fired from a state that declares no such transition — including firing the same trigger twice — is rejected here with that entity's state error"

    PRD: "Renderings are returned with HTTP 201 and their vote tallies start at zero: `yes_votes` 0, `no_votes` 0 and `community_approval_pct` 0.0."

    Design: Corner/state_machines/close_review_and_restart_consultation_rejected_from_wrong_project_state
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Thistle Green"}
    )
    fx.create_placement(
        scenario["area"]["id"],
        scenario["post"]["id"],
        color_choice="FOREST_GREEN",
        x_start_cm=200,
        quantity=3,
    )
    rendering = fx.issue_rendering(
        scenario["project"]["id"], scenario["standard"]["id"]
    )

    response = api_client.close_review(rendering["id"], CONSULTANT)

    validate_error(response, ApiErrorId.ERR_PROJECT_INVALID_STATE.value, 409)
    after = a.assert_object_envelope(
        api_client.get_rendering(rendering["id"], CONSULTANT)
    )
    assert after["status"] == "ISSUED", (
        f"the rendering stays ISSUED, got {after['status']!r}"
    )
    assert after["round_number"] == 1, (
        f"expected the first round, got {after['round_number']}"
    )
    assert after["yes_votes"] == 0, f"expected yes_votes 0, got {after['yes_votes']}"
    assert after["no_votes"] == 0, f"expected no_votes 0, got {after['no_votes']}"
    assert after["community_approval_pct"] == 0.0, (
        f"expected community_approval_pct 0.0, got {after['community_approval_pct']}"
    )
    project = a.assert_object_envelope(
        api_client.get_project(scenario["project"]["id"], CONSULTANT)
    )
    assert project["design_status"] == "RENDERED", (
        f"the project stays RENDERED, got {project['design_status']!r}"
    )
    assert project["revision_rounds"] == 0, (
        f"no revision round was opened, got {project['revision_rounds']}"
    )


def test_start_consultation_from_a_rendered_project_is_refused():
    """The consultation trigger is admissible from DRAFT only.

    PRD: "Firing the same trigger a second time, or firing it from any status other than `DRAFT`, is rejected with `ERR_PROJECT_INVALID_STATE`."

    Design: Corner/state_machines/close_review_and_restart_consultation_rejected_from_wrong_project_state
    """
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Thistle Green"}
    )
    fx.create_placement(
        scenario["area"]["id"],
        scenario["post"]["id"],
        color_choice="FOREST_GREEN",
        x_start_cm=200,
        quantity=3,
    )
    fx.issue_rendering(scenario["project"]["id"], scenario["standard"]["id"])
    rendered = fx.get_project(scenario["project"]["id"])
    assert rendered["design_status"] == "RENDERED", (
        f"the setup must leave the project RENDERED, got {rendered['design_status']!r}"
    )

    response = api_client.start_consultation(scenario["project"]["id"], CONSULTANT)

    validate_error(response, ApiErrorId.ERR_PROJECT_INVALID_STATE.value, 409)
    after = a.assert_object_envelope(
        api_client.get_project(scenario["project"]["id"], CONSULTANT)
    )
    assert after["design_status"] == "RENDERED", (
        f"the project stays RENDERED, got {after['design_status']!r}"
    )
    assert after["revision_rounds"] == 0, (
        f"no revision round was opened, got {after['revision_rounds']}"
    )
    assert after["version"] == rendered["version"], (
        f"the refused trigger mutates nothing, expected version "
        f"{rendered['version']}, got {after['version']}"
    )


def test_prep_dimensions_are_not_writable_before_the_production_fork():
    """A CREATED order refuses prep advances until production starts.

    PRD: "On success a `ManufacturingOrder` is created with HTTP 201 in `production_status` `CREATED`, `kitting_status` `PENDING` and `bagging_status` `PENDING`, with `kit_line_count`, `hardware_bag_total` and `instruction_package_revision` all at 0."

    PRD: "only once the order is `IN_PRODUCTION` do the two prep dimensions become writable, and advancing either of them while `production_status` is anything else is refused with `ERR_ORDER_NOT_IN_PRODUCTION`"

    Design: Corner/state_machines/order_prep_dimensions_fork_at_in_production_and_join_at_ready_to_ship
    """
    scenario = fx.setup_ordered_project()
    order = scenario["order"]

    a.assert_order(order)
    assert order["production_status"] == "CREATED", (
        f"expected CREATED, got {order['production_status']!r}"
    )
    assert order["kitting_status"] == "PENDING", (
        f"expected kitting_status PENDING, got {order['kitting_status']!r}"
    )
    assert order["bagging_status"] == "PENDING", (
        f"expected bagging_status PENDING, got {order['bagging_status']!r}"
    )
    for field in ("kit_line_count", "hardware_bag_total", "instruction_package_revision"):
        assert order[field] == 0, f"expected {field} 0 on creation, got {order[field]}"

    refused = api_client.advance_kitting(
        order["id"], f.kitting_payload("DONE"), ADMIN
    )

    validate_error(refused, ApiErrorId.ERR_ORDER_NOT_IN_PRODUCTION.value, 409)
    unchanged = fx.get_order(order["id"])
    assert unchanged["kitting_status"] == "PENDING", (
        f"the refused advance leaves kitting PENDING, got {unchanged['kitting_status']!r}"
    )
    assert unchanged["version"] == order["version"], (
        f"the refused advance mutates nothing, expected version "
        f"{order['version']}, got {unchanged['version']}"
    )

    forked = fx.start_production(order["id"])
    assert forked["production_status"] == "IN_PRODUCTION", (
        f"expected IN_PRODUCTION, got {forked['production_status']!r}"
    )
    assert forked["kitting_status"] == "PENDING", (
        f"the fork does not advance kitting, got {forked['kitting_status']!r}"
    )
    assert forked["bagging_status"] == "PENDING", (
        f"the fork does not advance bagging, got {forked['bagging_status']!r}"
    )
    assert forked["version"] > order["version"], (
        f"starting production bumps the order past version {order['version']}, got "
        f"{forked['version']}"
    )


def test_prep_branches_touch_disjoint_fields_and_join_at_ready_to_ship():
    """Each prep branch writes only its own derived field; the second joins.

    PRD: "Reaching `DONE` writes exactly one derived field and no other: `kit_line_count` becomes the count of distinct placement lines the backing quote priced."

    PRD: "the moment the second of `kitting_status` and `bagging_status` reaches `DONE`, and only then, the order's `production_status` moves `IN_PRODUCTION → READY_TO_SHIP` and `instruction_package_revision` is set to the backing rendering's `round_number`"

    PRD: "Shipping then moves the order `READY_TO_SHIP → SHIPPED`, dispatching the kit together with its instruction package, and increments `version` by one."

    Design: Corner/state_machines/order_prep_dimensions_fork_at_in_production_and_join_at_ready_to_ship
    """
    scenario = fx.setup_order_in_production()
    order_id = scenario["order"]["id"]
    versions = [scenario["order"]["version"]]

    kitted = fx.advance_kitting(order_id, "DONE")
    versions.append(kitted["version"])
    assert kitted["kitting_status"] == "DONE", (
        f"expected kitting_status DONE, got {kitted['kitting_status']!r}"
    )
    assert kitted["kit_line_count"] == 3, (
        f"expected the three priced placement lines, got {kitted['kit_line_count']}"
    )
    assert kitted["production_status"] == "IN_PRODUCTION", (
        f"one branch alone does not join, got {kitted['production_status']!r}"
    )
    assert kitted["bagging_status"] == "PENDING", (
        f"kitting must not touch bagging, got {kitted['bagging_status']!r}"
    )
    assert kitted["hardware_bag_total"] == 0, (
        f"kitting must not write hardware_bag_total, got {kitted['hardware_bag_total']}"
    )
    assert kitted["instruction_package_revision"] == 0, (
        f"the instruction package is written only by the join, got "
        f"{kitted['instruction_package_revision']}"
    )

    bagged = fx.advance_bagging(order_id, "DONE")
    versions.append(bagged["version"])
    assert bagged["bagging_status"] == "DONE", (
        f"expected bagging_status DONE, got {bagged['bagging_status']!r}"
    )
    assert bagged["hardware_bag_total"] == 16, (
        f"expected hardware_bag_total 16, got {bagged['hardware_bag_total']}"
    )
    assert bagged["kit_line_count"] == 3, (
        f"bagging must not rewrite kit_line_count, got {bagged['kit_line_count']}"
    )
    assert bagged["production_status"] == "READY_TO_SHIP", (
        f"the second branch joins to READY_TO_SHIP, got {bagged['production_status']!r}"
    )
    assert bagged["instruction_package_revision"] == 1, (
        f"expected the backing rendering's round number 1, got "
        f"{bagged['instruction_package_revision']}"
    )

    shipped = fx.ship_order(order_id)
    versions.append(shipped["version"])
    assert shipped["production_status"] == "SHIPPED", (
        f"expected SHIPPED, got {shipped['production_status']!r}"
    )
    assert all(
        earlier < later for earlier, later in zip(versions, versions[1:])
    ), f"every accepted call must bump the order's version, got {versions}"


def test_cancelling_an_ordered_project_cascades_across_the_chain():
    """Cancellation cancels the order and its job, refunds the pledge and
    recomputes both the crew-day ledger and the allocation buckets.

    PRD: "Hop one: the project's `ManufacturingOrder`, if it has one and its `production_status` is `CREATED` or `IN_PRODUCTION`, moves to `CANCELLED`. Hop two: because that order is cancelled, every `InstallationJob` of the order whose `status` is `SCHEDULED` or `IN_PROGRESS` moves to `CANCELLED`. Hop three: because those jobs are cancelled, each affected installer has its `committed_crew_days` recomputed."

    PRD: "Alongside the hops, every `FundraisingPledge` of the project whose `status` is `PLEDGED` or `COLLECTED` moves to `REFUNDED`, after which `funds_collected_cents` and all four allocation buckets are recomputed and therefore all become 0; and every `Quote` of the project still in `ISSUED` moves to `EXPIRED`."

    PRD: "When no such quote exists, all three targeted buckets are zero and `alloc_contingency_cents` absorbs the entire collected amount."

    The pledge is collected before any quote is issued, and the waterfall is
    "recomputed in full on every collection and every refund" — not on quote
    issuance — so at collection time the project had no `ISSUED` or `ACCEPTED`
    quote and contingency legitimately holds the whole 400000 cents.

    PRD: "every play area of the project is driven `ZONED → LOCKED`"

    Design: Corner/state_machines/project_cancel_cascades_to_order_jobs_pledges_and_quotes
    """
    scenario = _setup_ordered_project_with_scheduled_job()
    project_id = scenario["project"]["id"]
    job = scenario["job"]

    assert scenario["installer"]["committed_crew_days"] == 12, (
        f"expected 12 committed crew-days before the cancellation, got "
        f"{scenario['installer']['committed_crew_days']}"
    )
    assert job["booked_crew_days"] == 12, (
        f"expected 12 booked crew-days, got {job['booked_crew_days']}"
    )
    a.assert_booked_crew_days(job)
    assert job["status"] == "SCHEDULED", (
        f"expected a SCHEDULED job, got {job['status']!r}"
    )
    funded = fx.get_project(project_id)
    assert funded["funds_collected_cents"] == 400000, (
        f"expected 400000 cents collected, got {funded['funds_collected_cents']}"
    )
    assert funded["alloc_permit_freight_cents"] == 0, (
        f"no quote existed at collection time, so the first target is zero, got "
        f"{funded['alloc_permit_freight_cents']}"
    )
    assert funded["alloc_surfacing_cents"] == 0, (
        f"no quote existed at collection time, so the second target is zero, got "
        f"{funded['alloc_surfacing_cents']}"
    )
    assert funded["alloc_structure_cents"] == 0, (
        f"no quote existed at collection time, so the third target is zero, got "
        f"{funded['alloc_structure_cents']}"
    )
    assert funded["alloc_contingency_cents"] == 400000, (
        f"contingency absorbs the entire collected amount, got "
        f"{funded['alloc_contingency_cents']}"
    )
    a.assert_allocation_invariant(funded)

    cancelled = a.assert_object_envelope(
        api_client.cancel_project(project_id, CONSULTANT)
    )

    assert cancelled["design_status"] == "CANCELLED", (
        f"expected CANCELLED, got {cancelled['design_status']!r}"
    )
    order_after = fx.get_order(scenario["order"]["id"])
    assert order_after["production_status"] == "CANCELLED", (
        f"hop one must cancel the order, got {order_after['production_status']!r}"
    )
    job_after = fx.get_job(job["id"])
    assert job_after["status"] == "CANCELLED", (
        f"hop two must cancel the job, got {job_after['status']!r}"
    )
    installer_after = fx.get_installer(scenario["installer"]["id"])
    assert installer_after["committed_crew_days"] == 0, (
        f"hop three must recompute the ledger to 0, got "
        f"{installer_after['committed_crew_days']}"
    )
    pledge_after = a.assert_object_envelope(
        api_client.get_pledge(scenario["pledge"]["id"], CONSULTANT)
    )
    assert pledge_after["status"] == "REFUNDED", (
        f"the collected pledge must be refunded, got {pledge_after['status']!r}"
    )
    assert cancelled["funds_collected_cents"] == 0, (
        f"expected funds_collected_cents 0, got {cancelled['funds_collected_cents']}"
    )
    for bucket in (
        "alloc_permit_freight_cents",
        "alloc_surfacing_cents",
        "alloc_structure_cents",
        "alloc_contingency_cents",
    ):
        assert cancelled[bucket] == 0, (
            f"expected {bucket} 0 after the refund, got {cancelled[bucket]}"
        )
    a.assert_allocation_invariant(cancelled)
    quote_after = a.assert_object_envelope(
        api_client.get_quote(scenario["quote"]["id"], CONSULTANT)
    )
    assert quote_after["status"] == "ACCEPTED", (
        f"an accepted quote is not expired by the cancellation, got "
        f"{quote_after['status']!r}"
    )
    area_after = fx.get_play_area(scenario["area"]["id"])
    assert area_after["status"] == "LOCKED", (
        f"the area stays LOCKED, got {area_after['status']!r}"
    )


def test_installer_revocation_cancels_open_bookings_and_is_terminal():
    """An administrative suspension keeps bookings; revocation cancels them and
    admits no return to ACTIVE.

    PRD: "it only blocks the creation of new jobs and blocks a `SCHEDULED` job from being started"

    PRD: "Revocation moves the installer to `REVOKED` from either `ACTIVE` or `SUSPENDED`, cancels every job of that installer whose `status` is `SCHEDULED` or `IN_PROGRESS`, and then recomputes `committed_crew_days`"

    PRD: "A status change that no transition declares — attempting to move a `REVOKED` installer back to `ACTIVE`, for instance — is refused with `ERR_INSTALLER_INVALID_STATE`."

    Design: Corner/state_machines/installer_revocation_cancels_open_bookings_and_is_terminal
    """
    scenario = _setup_ordered_project_with_scheduled_job(
        installer_overrides={
            "company_name": "Southline Installers",
            "region_code": "SL",
        }
    )
    installer_id = scenario["installer"]["id"]
    job_id = scenario["job"]["id"]

    suspended = fx.set_installer_status(installer_id, "SUSPENDED")
    assert suspended["status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {suspended['status']!r}"
    )
    assert suspended["committed_crew_days"] == 12, (
        f"an administrative suspension keeps the booking, got "
        f"{suspended['committed_crew_days']}"
    )
    assert fx.get_job(job_id)["status"] == "SCHEDULED", (
        f"the job stays SCHEDULED, got {fx.get_job(job_id)['status']!r}"
    )

    revoked = fx.set_installer_status(installer_id, "REVOKED")
    assert revoked["status"] == "REVOKED", (
        f"expected REVOKED, got {revoked['status']!r}"
    )
    assert revoked["committed_crew_days"] == 0, (
        f"revocation recomputes the ledger to 0, got {revoked['committed_crew_days']}"
    )
    assert fx.get_job(job_id)["status"] == "CANCELLED", (
        f"revocation cancels the open booking, got {fx.get_job(job_id)['status']!r}"
    )

    reinstatement = api_client.set_installer_status(
        installer_id, f.installer_status_payload("ACTIVE"), ADMIN
    )

    validate_error(reinstatement, ApiErrorId.ERR_INSTALLER_INVALID_STATE.value, 409)
    after = fx.get_installer(installer_id)
    assert after["status"] == "REVOKED", (
        f"REVOKED is terminal, got {after['status']!r}"
    )
    assert after["committed_crew_days"] == 0, (
        f"the refused reinstatement changes nothing, got "
        f"{after['committed_crew_days']}"
    )
    assert fx.get_job(job_id)["status"] == "CANCELLED", (
        f"the cancelled job is not resurrected, got {fx.get_job(job_id)['status']!r}"
    )
    assert fx.get_project(scenario["project"]["id"])["design_status"] == "ORDERED", (
        "the installer's membership axis never moves the project's design axis"
    )
