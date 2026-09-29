"""Cross-cutting behaviour of the Playground Equipment Manufacturing API:
optimistic concurrency on two different parents, full reconciliation of the
five derived money fields on a project, and the immediacy of every derived and
cascaded value.

Each test builds its own world from `test_helpers.fixtures`; the server is
relaunched with an empty database and the logical clock at 2026-08-01T00:00:00Z
before every test.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_paginated_list,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["design_consultant_headers"]
CLIENT = TEST_USERS["client_representative_headers"]


def _preschool_post_model_payload():
    """A PRESCHOOL_2_5 ground-level post at 10750 cents, default colour first."""
    return f.post_model_payload(
        sku="POST-STD-120",
        category="POST",
        age_group="PRESCHOOL_2_5",
        deck_height_cm=0,
        use_zone_footprint_cm=60,
        color_options=["FOREST_GREEN", "CRIMSON"],
        unit_price_cents=10750,
        hardware_bag_count=4,
        warranty_years=10,
        parts_support_until_year=2040,
        accessible_transfer_ready=False,
    )


def _preschool_project_payload(client_name):
    """A SANDY_LOAM preschool site with a 500000 cent budget and no route rule."""
    return dict(
        client_name=client_name,
        site_length_cm=3000,
        site_width_cm=2000,
        site_soil_type="SANDY_LOAM",
        budget_cents=500000,
        fundraising_deadline="2026-12-31",
        required_age_groups=["PRESCHOOL_2_5"],
        accessible_route_required=False,
    )


def _setup_preschool_post_design(client_name):
    """Standard ACTIVE, one certified PRESCHOOL_2_5 post, and a project sitting
    in RENDERED with one VALIDATED placement of quantity 3 and one ISSUED
    rendering. A FIRM quote over this design prices at 84000 cents.
    """
    fx.set_clock("2026-08-01T09:00:00Z")
    standard = fx.create_active_standard(
        code="ASTM_F1487",
        edition_year=2024,
        effective_from="2024-01-01",
        min_use_zone_clearance_cm=183,
        max_fall_height_cm_toddler=122,
        max_fall_height_cm_preschool=152,
        max_fall_height_cm_school_age=244,
        requires_accessible_route=False,
    )
    model = fx.create_certified_model(_preschool_post_model_payload())
    project = fx.create_project_in_consultation(**_preschool_project_payload(client_name))
    area = fx.create_play_area(
        project["id"],
        age_group="PRESCHOOL_2_5",
        axis_origin_cm=0,
        axis_length_cm=1200,
        surfacing_material="ENGINEERED_WOOD_FIBER",
        surfacing_depth_cm=30,
    )
    placement = fx.create_validated_placement(
        area["id"],
        model["id"],
        color_choice="FOREST_GREEN",
        x_start_cm=200,
        quantity=3,
    )
    rendering = fx.issue_rendering(project["id"], standard["id"])
    return {
        "standard": standard,
        "model": model,
        "project": project,
        "area": area,
        "placement": placement,
        "rendering": rendering,
    }


def _setup_preschool_deck_area(client_name):
    """Standard ACTIVE, one certified PRESCHOOL_2_5 deck 122 cm high, and a
    CONSULTATION project holding one still-empty PRESCHOOL_2_5 area 0..1200 at
    ENGINEERED_WOOD_FIBER depth 30.
    """
    fx.set_clock("2026-08-01T09:00:00Z")
    standard = fx.create_active_standard(
        code="ASTM_F1487",
        edition_year=2024,
        effective_from="2024-01-01",
        min_use_zone_clearance_cm=183,
        max_fall_height_cm_toddler=122,
        max_fall_height_cm_preschool=152,
        max_fall_height_cm_school_age=244,
        requires_accessible_route=False,
    )
    model = fx.create_certified_model(
        f.deck_model_payload(
            sku="DECK-122-SQ",
            category="DECK",
            age_group="PRESCHOOL_2_5",
            deck_height_cm=122,
            use_zone_footprint_cm=183,
            color_options=["FOREST_GREEN", "CRIMSON"],
            unit_price_cents=89500,
            hardware_bag_count=6,
            warranty_years=15,
            parts_support_until_year=2045,
            accessible_transfer_ready=False,
        )
    )
    project = fx.create_project_in_consultation(**_preschool_project_payload(client_name))
    area = fx.create_play_area(
        project["id"],
        age_group="PRESCHOOL_2_5",
        axis_origin_cm=0,
        axis_length_cm=1200,
        surfacing_material="ENGINEERED_WOOD_FIBER",
        surfacing_depth_cm=30,
    )
    return {
        "standard": standard,
        "model": model,
        "project": project,
        "area": area,
    }


def test_quote_create_refuses_a_project_version_observed_before_the_vote_batch():
    """A project version read before a vote batch is stale for the quote create
    that follows it, and the rejected create writes nothing.

    PRD: "If that value does not equal the project's current `version`, the
    request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/quote_create_occ_rejects_a_project_version_observed_before_the_vote_batch
    """
    scenario = _setup_preschool_post_design("Concurrency Green Park")
    project_id = scenario["project"]["id"]
    rendering_id = scenario["rendering"]["id"]

    before_votes = fx.get_project(project_id)
    assert before_votes["design_status"] == "RENDERED", (
        f"expected RENDERED before the vote batch, got {before_votes['design_status']}"
    )
    version_stale = before_votes["version"]

    tally = fx.record_votes(rendering_id, 15, 10)
    assert tally["community_approval_pct"] == 60.0, (
        f"expected 60.0 approval from 15 yes of 25 votes, got "
        f"{tally['community_approval_pct']}"
    )

    stale_body = f.quote_payload(
        project_id,
        rendering_id,
        version_stale,
        variant="FIRM",
        valid_until="2026-12-31",
    )
    rejected = api_client.create_quote(stale_body, CONSULTANT)
    assert rejected.status_code == 412, (
        f"expected 412 for a project version invalidated by the vote batch, got "
        f"{rejected.status_code}: {rejected.text}"
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)

    quotes, _ = assert_paginated_list(
        api_client.list_quotes(CONSULTANT, {"project_id": project_id}), 0
    )
    assert quotes == [], f"the rejected create must write no quote, found {quotes}"

    version_fresh = fx.project_version(project_id)
    assert version_fresh == version_stale + 1, (
        f"the vote batch must bump the project by exactly one: expected "
        f"{version_stale + 1}, got {version_fresh}"
    )

    fresh_body = f.quote_payload(
        project_id,
        rendering_id,
        version_fresh,
        variant="FIRM",
        valid_until="2026-12-31",
    )
    quote = validate_success(api_client.create_quote(fresh_body, CONSULTANT), 201)
    assert quote["subtotal_cents"] == 32250, (
        f"expected subtotal 32250 for three posts at 10750, got {quote['subtotal_cents']}"
    )
    assert quote["freight_cents"] == 51750, (
        f"expected freight 51750, got {quote['freight_cents']}"
    )
    assert quote["discount_cents"] == 0, (
        f"expected no discount, got {quote['discount_cents']}"
    )
    assert quote["total_cents"] == 84000, (
        f"expected total 84000, got {quote['total_cents']}"
    )
    assert quote["status"] == "ISSUED", f"expected ISSUED, got {quote['status']}"
    assert quote["version"] == 1, (
        f"a freshly issued quote must be at version 1, got {quote['version']}"
    )

    version_after_quote = fx.project_version(project_id)
    assert version_after_quote == version_fresh + 1, (
        f"the accepted create must itself bump the project: expected "
        f"{version_fresh + 1}, got {version_after_quote}"
    )


def test_job_reschedule_refuses_an_installer_version_observed_before_a_second_booking():
    """The reschedule guard reads the installer's version, not the job's, so a
    second booking for the same installer invalidates a version observed after
    the first one.

    PRD: "If that value does not equal the installer's current `version`, the
    request is rejected with `ERR_STALE_INSTALLER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/job_reschedule_occ_rejects_an_installer_version_observed_before_a_second_booking
    """
    scenario = _setup_preschool_post_design("Reschedule Ridge Park")
    project_id = scenario["project"]["id"]
    rendering_id = scenario["rendering"]["id"]

    fx.record_votes(rendering_id, 15, 10)
    fx.close_review(rendering_id)
    fx.certify_compliance(project_id)
    quote = fx.issue_quote(
        project_id, rendering_id, variant="FIRM", valid_until="2026-12-31"
    )
    assert quote["total_cents"] == 84000, (
        f"expected a firm quote of 84000, got {quote['total_cents']}"
    )
    fx.accept_quote(quote["id"])
    fx.create_collected_pledge(project_id, 84000)
    order = fx.create_order(quote["id"])

    installer = fx.create_installer(
        company_name="Highline Rigging Crews",
        certification_level="MASTER",
        certified_categories=["POST", "DECK"],
        crew_capacity_per_day=6,
        certification_expires_on="2030-12-31",
        region_code="TX",
    )
    job1 = fx.book_job(
        order["id"],
        installer["id"],
        scheduled_start_date="2026-08-06",
        scheduled_end_date="2026-08-08",
        crew_size=4,
    )
    assert job1["booked_crew_days"] == 12, (
        f"expected 12 booked crew days for crew 4 over three inclusive days, got "
        f"{job1['booked_crew_days']}"
    )
    a.assert_booked_crew_days(job1)
    job1_version = job1["version"]

    after_job1 = fx.get_installer(installer["id"])
    assert after_job1["committed_crew_days"] == 12, (
        f"expected 12 committed crew days after one booking, got "
        f"{after_job1['committed_crew_days']}"
    )
    installer_version_stale = after_job1["version"]

    job2 = fx.book_job(
        order["id"],
        installer["id"],
        scheduled_start_date="2026-08-20",
        scheduled_end_date="2026-08-21",
        crew_size=2,
    )
    assert job2["booked_crew_days"] == 4, (
        f"expected 4 booked crew days for crew 2 over two inclusive days, got "
        f"{job2['booked_crew_days']}"
    )

    after_job2 = fx.get_installer(installer["id"])
    assert after_job2["committed_crew_days"] == 16, (
        f"expected 16 committed crew days across both bookings, got "
        f"{after_job2['committed_crew_days']}"
    )
    installer_version_fresh = after_job2["version"]
    assert installer_version_fresh == installer_version_stale + 1, (
        f"the second booking must bump the installer by exactly one: expected "
        f"{installer_version_stale + 1}, got {installer_version_fresh}"
    )

    rejected = api_client.reschedule_job(
        job1["id"],
        f.reschedule_payload(
            installer_version_stale, "2026-08-10", "2026-08-12", crew_size=5
        ),
        CONSULTANT,
    )
    assert rejected.status_code == 412, (
        f"expected 412 for an installer version invalidated by the second "
        f"booking, got {rejected.status_code}: {rejected.text}"
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_INSTALLER_VERSION.value)

    job1_after_412 = fx.get_job(job1["id"])
    assert job1_after_412["scheduled_start_date"] == "2026-08-06", (
        f"the rejected reschedule must leave the window intact, got "
        f"{job1_after_412['scheduled_start_date']}"
    )
    assert job1_after_412["scheduled_end_date"] == "2026-08-08", (
        f"expected the original end date, got {job1_after_412['scheduled_end_date']}"
    )
    assert job1_after_412["booked_crew_days"] == 12, (
        f"expected 12 booked crew days still, got {job1_after_412['booked_crew_days']}"
    )
    assert job1_after_412["version"] == job1_version, (
        f"a failed write must not bump the job: expected {job1_version}, got "
        f"{job1_after_412['version']}"
    )
    assert job1_after_412["status"] == "SCHEDULED", (
        f"expected SCHEDULED, got {job1_after_412['status']}"
    )

    installer_after_412 = fx.get_installer(installer["id"])
    assert installer_after_412["committed_crew_days"] == 16, (
        f"expected the committed total to stay at 16, got "
        f"{installer_after_412['committed_crew_days']}"
    )
    assert installer_after_412["version"] == installer_version_fresh, (
        f"a failed write must not bump the installer: expected "
        f"{installer_version_fresh}, got {installer_after_412['version']}"
    )

    moved = fx.reschedule_job(
        job1["id"], "2026-08-10", "2026-08-12", installer_version_fresh, crew_size=5
    )
    assert moved["scheduled_start_date"] == "2026-08-10", (
        f"expected the window to move to 2026-08-10, got "
        f"{moved['scheduled_start_date']}"
    )
    assert moved["scheduled_end_date"] == "2026-08-12", (
        f"expected the window to end 2026-08-12, got {moved['scheduled_end_date']}"
    )
    assert moved["booked_crew_days"] == 15, (
        f"expected 15 booked crew days for crew 5 over three inclusive days, got "
        f"{moved['booked_crew_days']}"
    )
    a.assert_booked_crew_days(moved)
    assert moved["status"] == "SCHEDULED", (
        f"a reschedule is not a state transition, got {moved['status']}"
    )

    installer_final = fx.get_installer(installer["id"])
    assert installer_final["committed_crew_days"] == 19, (
        f"expected 19 committed crew days (15 rescheduled + 4 for the second "
        f"job), got {installer_final['committed_crew_days']}"
    )
    assert installer_final["version"] == installer_version_fresh + 1, (
        f"the accepted reschedule must bump the installer once: expected "
        f"{installer_version_fresh + 1}, got {installer_final['version']}"
    )


def test_funds_and_allocation_buckets_reconcile_across_two_collects_and_a_refund():
    """The five derived money fields are recomputed from the collected pledges
    at every step, so refunding the second pledge restores the exact picture the
    first collection produced.

    PRD: "The invariant that must hold after every collection and every refund
    is that the four buckets sum to exactly `funds_collected_cents` — no cent is
    created and none is lost."

    Design: Corner/cross_cutting_complexity_layers/project_funds_and_allocation_buckets_reconcile_across_two_collects_and_a_partial_refund
    """
    scenario = _setup_preschool_post_design("Ledger Meadow Park")
    project_id = scenario["project"]["id"]

    quote = fx.issue_quote(
        project_id,
        scenario["rendering"]["id"],
        variant="FIRM",
        valid_until="2026-12-31",
    )
    assert quote["subtotal_cents"] == 32250, (
        f"expected subtotal 32250, got {quote['subtotal_cents']}"
    )
    assert quote["freight_cents"] == 51750, (
        f"expected freight 51750, got {quote['freight_cents']}"
    )

    pledge1 = fx.create_pledge(project_id, amount_cents=60000, pledged_at="2026-08-01")
    pledge2 = fx.create_pledge(project_id, amount_cents=30000, pledged_at="2026-08-01")
    assert pledge1["status"] == "PLEDGED", (
        f"expected a new pledge to be PLEDGED, got {pledge1['status']}"
    )

    point1 = fx.get_project(project_id)
    assert point1["funds_collected_cents"] == 0, (
        f"a pledge that has not been collected contributes nothing, got "
        f"{point1['funds_collected_cents']}"
    )
    assert point1["alloc_permit_freight_cents"] == 0
    assert point1["alloc_surfacing_cents"] == 0
    assert point1["alloc_structure_cents"] == 0
    assert point1["alloc_contingency_cents"] == 0
    a.assert_allocation_invariant(point1)
    version_before = point1["version"]

    collected1 = fx.collect_pledge(pledge1["id"])
    assert collected1["status"] == "COLLECTED", (
        f"expected COLLECTED, got {collected1['status']}"
    )

    point2 = fx.get_project(project_id)
    assert point2["funds_collected_cents"] == 60000, (
        f"expected 60000 collected, got {point2['funds_collected_cents']}"
    )
    assert point2["alloc_permit_freight_cents"] == 51750, (
        f"the first target takes the whole freight of 51750, got "
        f"{point2['alloc_permit_freight_cents']}"
    )
    assert point2["alloc_surfacing_cents"] == 6450, (
        f"the second target is twenty percent of 32250, got "
        f"{point2['alloc_surfacing_cents']}"
    )
    assert point2["alloc_structure_cents"] == 1800, (
        f"expected the 1800 cents left over, got {point2['alloc_structure_cents']}"
    )
    assert point2["alloc_contingency_cents"] == 0, (
        f"nothing survives the first three targets yet, got "
        f"{point2['alloc_contingency_cents']}"
    )
    a.assert_allocation_invariant(point2)
    assert point2["version"] == version_before + 1, (
        f"the collection must bump the project once: expected "
        f"{version_before + 1}, got {point2['version']}"
    )

    collected2 = fx.collect_pledge(pledge2["id"])
    assert collected2["status"] == "COLLECTED", (
        f"expected COLLECTED, got {collected2['status']}"
    )

    point3 = fx.get_project(project_id)
    assert point3["funds_collected_cents"] == 90000, (
        f"expected 90000 collected, got {point3['funds_collected_cents']}"
    )
    assert point3["alloc_permit_freight_cents"] == 51750
    assert point3["alloc_surfacing_cents"] == 6450
    assert point3["alloc_structure_cents"] == 25800, (
        f"the structure target of 25800 is now fully funded, got "
        f"{point3['alloc_structure_cents']}"
    )
    assert point3["alloc_contingency_cents"] == 6000, (
        f"contingency absorbs the 6000 beyond the 84000 total, got "
        f"{point3['alloc_contingency_cents']}"
    )
    a.assert_allocation_invariant(point3)
    assert point3["version"] == version_before + 2, (
        f"the second collection must bump the project once more: expected "
        f"{version_before + 2}, got {point3['version']}"
    )

    refunded = fx.refund_pledge(pledge2["id"])
    assert refunded["status"] == "REFUNDED", (
        f"expected REFUNDED, got {refunded['status']}"
    )

    point4 = fx.get_project(project_id)
    assert point4["funds_collected_cents"] == 60000, (
        f"expected the collected total back at 60000, got "
        f"{point4['funds_collected_cents']}"
    )
    assert point4["alloc_permit_freight_cents"] == 51750, (
        f"expected the freight bucket restored to 51750, got "
        f"{point4['alloc_permit_freight_cents']}"
    )
    assert point4["alloc_surfacing_cents"] == 6450, (
        f"expected the surfacing bucket restored to 6450, got "
        f"{point4['alloc_surfacing_cents']}"
    )
    assert point4["alloc_structure_cents"] == 1800, (
        f"a total recompute must drain structure back to 1800, got "
        f"{point4['alloc_structure_cents']}"
    )
    assert point4["alloc_contingency_cents"] == 0, (
        f"a total recompute must drain contingency back to 0, got "
        f"{point4['alloc_contingency_cents']}"
    )
    a.assert_allocation_invariant(point4)
    assert point4["version"] == version_before + 3, (
        f"the refund of a collected pledge must bump the project once: expected "
        f"{version_before + 3}, got {point4['version']}"
    )

    survivor = validate_success(api_client.get_pledge(pledge1["id"], CLIENT))
    assert survivor["status"] == "COLLECTED", (
        f"the refund touches one pledge row only, got {survivor['status']}"
    )


def test_a_placement_create_carries_its_use_zone_and_the_area_already_agrees():
    """The create response already carries the derived use-zone interval, and the
    very next read of the parent area already shows both numbers recomputed from
    a placement that is still DRAFT.

    PRD: "For the placement being written, `use_zone_start_cm` is the anchor
    coordinate `x_start_cm` less the model's `use_zone_footprint_cm`." "Both
    numbers are recomputed on every placement creation, every validation, every
    removal and every retrofit under the area."

    Design: Corner/consistency_model/every_derived_and_cascaded_value_is_visible_in_the_same_response_that_causes_it
    """
    scenario = _setup_preschool_deck_area("Immediate View Park")
    area = scenario["area"]
    assert area["critical_fall_height_cm"] == 0, (
        f"an area with no placements has no fall height, got "
        f"{area['critical_fall_height_cm']}"
    )
    assert area["required_surfacing_depth_cm"] == 15, (
        f"an empty area still reads the floor of 15, got "
        f"{area['required_surfacing_depth_cm']}"
    )
    assert area["version"] == 1, (
        f"a freshly created area is at version 1, got {area['version']}"
    )

    created = validate_success(
        api_client.create_placement(
            area["id"],
            f.placement_payload(
                scenario["model"]["id"],
                color_choice="FOREST_GREEN",
                x_start_cm=400,
                quantity=1,
            ),
            CONSULTANT,
        ),
        201,
    )
    assert created["status"] == "DRAFT", (
        f"a placement is born DRAFT, got {created['status']}"
    )
    assert created["use_zone_start_cm"] == 217, (
        f"expected 400 less the 183 footprint, got {created['use_zone_start_cm']}"
    )
    assert created["use_zone_end_cm"] == 583, (
        f"expected 400 plus the 183 footprint with no slide run-out, got "
        f"{created['use_zone_end_cm']}"
    )
    a.assert_use_zone(created, scenario["model"])

    read_back = fx.get_play_area(area["id"])
    assert read_back["critical_fall_height_cm"] == 122, (
        f"the DRAFT placement already counts towards the fall height, got "
        f"{read_back['critical_fall_height_cm']}"
    )
    assert read_back["required_surfacing_depth_cm"] == 23, (
        f"expected the engineered wood fibre depth of 23 for a 122 cm fall with "
        f"no uplift, got {read_back['required_surfacing_depth_cm']}"
    )
    assert read_back["status"] == "PLANNED", (
        f"creating a placement does not zone the area, got {read_back['status']}"
    )
    assert read_back["version"] == 2, (
        f"the recompute happened inside the create request, so the area is at "
        f"version 2, got {read_back['version']}"
    )


def test_validation_zones_the_area_and_leaves_both_derived_numbers_unchanged():
    """The validate response already reports VALIDATED at its new version, and
    the next read of the area already reports ZONED with exactly the numbers the
    DRAFT placement had produced.

    PRD: "A successful validation sets the placement's `status` to `VALIDATED`,
    promotes the owning area from `PLANNED` to `ZONED` if it was still
    `PLANNED`, recomputes the area's `critical_fall_height_cm` and
    `required_surfacing_depth_cm`, and increments both the placement's and the
    area's `version` by one."

    Design: Corner/consistency_model/every_derived_and_cascaded_value_is_visible_in_the_same_response_that_causes_it
    """
    scenario = _setup_preschool_deck_area("Immediate View Park")
    area = scenario["area"]
    placement = fx.create_placement(
        area["id"],
        scenario["model"]["id"],
        color_choice="FOREST_GREEN",
        x_start_cm=400,
        quantity=1,
    )

    draft_area = fx.get_play_area(area["id"])
    assert draft_area["status"] == "PLANNED", (
        f"expected PLANNED before validation, got {draft_area['status']}"
    )
    depth_from_draft = draft_area["required_surfacing_depth_cm"]
    height_from_draft = draft_area["critical_fall_height_cm"]

    validated = validate_success(
        api_client.validate_placement(placement["id"], CONSULTANT)
    )
    assert validated["status"] == "VALIDATED", (
        f"expected VALIDATED, got {validated['status']}"
    )
    assert validated["version"] == 2, (
        f"validation bumps the placement to version 2, got {validated['version']}"
    )

    zoned = fx.get_play_area(area["id"])
    assert zoned["status"] == "ZONED", (
        f"the first VALIDATED placement zones the area, got {zoned['status']}"
    )
    assert zoned["version"] == 3, (
        f"the area is bumped by both the create and the validation, so it reads "
        f"version 3, got {zoned['version']}"
    )
    assert zoned["critical_fall_height_cm"] == 122, (
        f"expected 122, got {zoned['critical_fall_height_cm']}"
    )
    assert zoned["required_surfacing_depth_cm"] == 23, (
        f"expected 23, got {zoned['required_surfacing_depth_cm']}"
    )
    assert zoned["critical_fall_height_cm"] == height_from_draft, (
        f"the derivation reads the same input set before and after validation: "
        f"{height_from_draft} became {zoned['critical_fall_height_cm']}"
    )
    assert zoned["required_surfacing_depth_cm"] == depth_from_draft, (
        f"the derivation reads the same input set before and after validation: "
        f"{depth_from_draft} became {zoned['required_surfacing_depth_cm']}"
    )


def test_close_review_returns_the_cascaded_project_and_the_hops_are_already_done():
    """Closing a review below threshold answers with the fully cascaded project,
    and the rendering it withdrew and the quote it expired are already in their
    new states on the immediately following reads.

    PRD: "the rendering's `status` becomes `WITHDRAWN`, the project's
    `design_status` becomes `REVISION_REQUESTED` and its `revision_rounds`
    counter is incremented by one, and every `Quote` of the project still in
    `ISSUED` status is moved to `EXPIRED`." "the operation's response body is
    the project rather than the rendering"

    Design: Corner/consistency_model/every_derived_and_cascaded_value_is_visible_in_the_same_response_that_causes_it
    """
    scenario = _setup_preschool_deck_area("Immediate View Park")
    project_id = scenario["project"]["id"]
    fx.create_validated_placement(
        scenario["area"]["id"],
        scenario["model"]["id"],
        color_choice="FOREST_GREEN",
        x_start_cm=400,
        quantity=1,
    )

    rendering = fx.issue_rendering(project_id, scenario["standard"]["id"])
    assert rendering["round_number"] == 1, (
        f"the project's first rendering is round 1, got {rendering['round_number']}"
    )
    assert rendering["status"] == "ISSUED", (
        f"expected ISSUED, got {rendering['status']}"
    )

    quote = validate_success(
        api_client.create_quote(
            f.quote_payload(
                project_id,
                rendering["id"],
                fx.project_version(project_id),
                variant="FIRM",
                valid_until="2026-12-31",
            ),
            CONSULTANT,
        ),
        201,
    )
    assert quote["total_cents"] == 138750, (
        f"expected 89500 of structure plus 49250 of freight, got "
        f"{quote['total_cents']}"
    )
    assert quote["status"] == "ISSUED", f"expected ISSUED, got {quote['status']}"

    tally = fx.record_votes(rendering["id"], 10, 15)
    assert tally["community_approval_pct"] == 40.0, (
        f"expected 40.0 approval from 10 yes of 25 votes, got "
        f"{tally['community_approval_pct']}"
    )

    closed = validate_success(api_client.close_review(rendering["id"], CONSULTANT))
    assert closed["id"] == project_id, (
        f"the close-review body is the project, got the row {closed['id']}"
    )
    assert closed["design_status"] == "REVISION_REQUESTED", (
        f"expected REVISION_REQUESTED in the causing response, got "
        f"{closed['design_status']}"
    )
    assert closed["revision_rounds"] == 1, (
        f"expected the revision counter at 1 in the causing response, got "
        f"{closed['revision_rounds']}"
    )

    rendering_after = fx.get_rendering(rendering["id"])
    assert rendering_after["status"] == "WITHDRAWN", (
        f"the withdrawal is already visible, got {rendering_after['status']}"
    )
    quote_after = fx.get_quote(quote["id"])
    assert quote_after["status"] == "EXPIRED", (
        f"the expiry is already visible, got {quote_after['status']}"
    )
    project_after = fx.get_project(project_id)
    assert project_after["design_status"] == closed["design_status"], (
        f"the follow-up read must agree with the causing response: "
        f"{closed['design_status']} became {project_after['design_status']}"
    )
    assert project_after["revision_rounds"] == closed["revision_rounds"], (
        f"the follow-up read must agree with the causing response: "
        f"{closed['revision_rounds']} became {project_after['revision_rounds']}"
    )
