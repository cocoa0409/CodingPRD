"""Which role may act, which identity may act, and the two duty separations that
compare the acting identity against the row it is trying to move.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_baseline_period,
    assert_coaching_alert,
    assert_consignment,
    assert_consignment_line,
    assert_corporate_rollup,
    assert_hauler,
    assert_reduction_target,
    assert_shift,
    assert_waste_entry,
    factories,
    fixtures,
    get_success_data,
    make_corporate_lead_headers,
    make_hauler_operator_headers,
    make_kitchen_staff_headers,
    make_platform_admin_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_NOON = "2026-08-01T12:00:00Z"
CAPTURED_AT = "2026-08-01T10:00:00Z"
LATER_CAPTURED_AT = "2026-08-01T10:10:00Z"
PICKUP_WINDOW = {
    "pickup_window_start": "2026-08-02T09:00:00Z",
    "pickup_window_end": "2026-08-02T11:00:00Z",
}


class TestFloorRolesShareCaptureAndAcknowledgement:
    """The two floor roles hold the capture write and the acknowledgement write together."""

    def test_both_floor_roles_capture_and_each_row_keeps_its_own_capturing_identity(self, api):
        """A cook and a supervisor each post a loss, and each row remembers who posted it.

        PRD Coverage: "Capturing a loss is the platform's highest-volume operation and is available to both `KitchenStaff` and `ShiftLead`." "`captured_by_user_id` records the capturing operator's `X-User-ID`, which is the comparison target of the void duty separation." "The owning service period recomputes `shift_waste_grams`, the sum of `weight_grams` over its captures whose status is `RECORDED` or `FLAGGED`"

        Design: Corner/rbac/kitchen_staff_and_shift_lead_both_capture_and_both_acknowledge
        """
        fixtures.set_clock(CLOCK_NOON)
        world = fixtures.site_with_open_shift()
        station_id = world["station"]["id"]
        shift_id = world["shift"]["id"]
        food_type_id = world["food_type"]["id"]

        cook_payload = factories.create_waste_entry_payload(
            station_id, shift_id, food_type_id, weight_grams=900, loss_reason="TRIM",
            captured_at=CAPTURED_AT,
        )
        cook_entry = validate_success(
            api.create_waste_entry(cook_payload, make_kitchen_staff_headers("ks-1")), 201
        )
        assert_waste_entry(cook_entry)
        assert cook_entry["status"] == "RECORDED"
        assert cook_entry["captured_by_user_id"] == "ks-1"

        lead_payload = factories.create_waste_entry_payload(
            station_id, shift_id, food_type_id, weight_grams=700, loss_reason="SPOILAGE",
            captured_at=LATER_CAPTURED_AT,
        )
        lead_entry = validate_success(
            api.create_waste_entry(lead_payload, make_shift_lead_headers("sl-1")), 201
        )
        assert_waste_entry(lead_entry)
        assert lead_entry["status"] == "RECORDED"
        assert lead_entry["captured_by_user_id"] == "sl-1"

        shift = fixtures.read_shift(shift_id)
        assert_shift(shift)
        assert shift["shift_waste_grams"] == 1600, "both identities feed the same period"

    def test_both_floor_roles_acknowledge_a_coaching_alert(self, api):
        """A cook acknowledges one alert and a supervisor the other; each stamps its own identity.

        PRD Coverage: "Acknowledgement is the cook's action and is open to `KitchenStaff` and `ShiftLead` alike; it advances `OPEN → ACKNOWLEDGED`, stamps `acknowledged_by_user_id` with the acting `X-User-ID`, and increments the alert's `version` by 1."

        Design: Corner/rbac/kitchen_staff_and_shift_lead_both_capture_and_both_acknowledge
        """
        fixtures.set_clock(CLOCK_NOON)
        world = fixtures.site_with_open_shift()
        fixtures.capture_entry(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            weight_grams=6000,
            loss_reason="OVERPRODUCTION",
            captured_at=CAPTURED_AT,
        )

        alerts, meta = validate_paginated(
            api.list_alerts(make_platform_admin_headers(), shift_id=world["shift"]["id"])
        )
        assert meta["total_count"] == 2, "the intensity breach and the overproduction spike both fired"
        for alert in alerts:
            assert_coaching_alert(alert)
            assert alert["status"] == "OPEN"

        by_cook = validate_success(
            api.acknowledge_alert(alerts[0]["id"], make_kitchen_staff_headers("ks-1")), 200
        )
        assert by_cook["status"] == "ACKNOWLEDGED"
        assert by_cook["acknowledged_by_user_id"] == "ks-1"
        assert by_cook["version"] == alerts[0]["version"] + 1

        by_lead = validate_success(
            api.acknowledge_alert(alerts[1]["id"], make_shift_lead_headers("sl-1")), 200
        )
        assert by_lead["status"] == "ACKNOWLEDGED"
        assert by_lead["acknowledged_by_user_id"] == "sl-1"
        assert by_lead["version"] == alerts[1]["version"] + 1


# The writes a cook may never issue on a capture it recorded, or on its period.
SUPERVISOR_ONLY_WRITES = [
    (
        "flag",
        lambda api, headers, entry_id, shift_id, version: api.flag_waste_entry(
            entry_id, factories.flag_payload(flag_reason="Weight looks implausible"), headers
        ),
    ),
    (
        "void",
        lambda api, headers, entry_id, shift_id, version: api.void_waste_entry(
            entry_id, factories.void_payload(void_reason="mis-keyed"), headers
        ),
    ),
    (
        "correction",
        lambda api, headers, entry_id, shift_id, version: api.correct_waste_entry(
            entry_id,
            factories.correction_payload(
                version, correction_note="reweighed", weight_grams=800
            ),
            headers,
        ),
    ),
    (
        "close_shift",
        lambda api, headers, entry_id, shift_id, version: api.close_shift(shift_id, headers),
    ),
]


class TestCurationBelongsToTheSupervisor:
    """A cook may create the capture row but may not curate it afterwards."""

    @staticmethod
    def _capture_by_a_cook():
        fixtures.set_clock(CLOCK_NOON)
        world = fixtures.site_with_open_shift()
        world["entry"] = fixtures.capture_entry(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            weight_grams=900,
            captured_at=CAPTURED_AT,
        )
        return world

    @pytest.mark.parametrize(
        "label,issue_write",
        SUPERVISOR_ONLY_WRITES,
        ids=[label for label, _ in SUPERVISOR_ONLY_WRITES],
    )
    def test_kitchen_staff_is_refused_on_the_supervisors_writes(self, api, label, issue_write):
        """Flag, void, correction and closure are all refused for a cook, and the row never moves.

        PRD Coverage: "The four curation operations on a capture belong exclusively to `ShiftLead`." "Closing a service period is the accounting event of the kitchen day, and it belongs exclusively to `ShiftLead` — not to the site manager, not to the platform administrator." "When both headers are present and well-formed but the caller's role is not among the roles the target endpoint admits, the request fails with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/kitchen_staff_cannot_perform_the_shift_leads_curation_writes
        """
        world = self._capture_by_a_cook()
        entry = world["entry"]

        response = issue_write(
            api, make_kitchen_staff_headers("ks-1"), entry["id"], world["shift"]["id"],
            entry["version"],
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED.value)

        unchanged = fixtures.read_entry(entry["id"])
        assert unchanged["status"] == "RECORDED"
        assert unchanged["weight_grams"] == 900
        assert unchanged["version"] == entry["version"]

        shift = fixtures.read_shift(world["shift"]["id"])
        assert shift["status"] == "OPEN"

    def test_the_role_refusal_precedes_the_correction_version_comparison(self, api):
        """A cook's correction carrying a stale version is still a role refusal, not a stale-version one.

        PRD Coverage: "2. Role admission for the target endpoint — `ERR_UNAUTHORIZED`." "10. Optimistic-concurrency token match — `ERR_STALE_ENTRY_VERSION` or `ERR_STALE_SITE_VERSION`." "`KitchenStaff` are line and prep cooks at a station terminal: they capture losses and acknowledge coaching alerts, and they may read every resource except the hauler-scoped ones."

        Design: Corner/rbac/kitchen_staff_cannot_perform_the_shift_leads_curation_writes
        """
        world = self._capture_by_a_cook()
        entry = world["entry"]

        stale_payload = factories.correction_payload(
            entry["version"] + 99, correction_note="reweighed", weight_grams=800
        )
        validate_error(
            api.correct_waste_entry(entry["id"], stale_payload, make_kitchen_staff_headers("ks-1")),
            ApiErrorId.UNAUTHORIZED.value,
        )

        unchanged = fixtures.read_entry(entry["id"])
        assert unchanged["status"] == "RECORDED"
        assert unchanged["version"] == entry["version"]
        assert unchanged["corrects_entry_id"] is None


# The two ways a submitted baseline can leave review, both held by the corporate side.
REVIEW_DECISIONS = [
    ("certify", lambda api, baseline_id, headers: api.certify_baseline_period(baseline_id, headers)),
    (
        "reject",
        lambda api, baseline_id, headers: api.reject_baseline_period(
            baseline_id, factories.reject_baseline_payload(rejection_note="self-serve"), headers
        ),
    ),
]


class TestBaselineReviewIsACorporateDecision:
    """A site opens and submits its own baseline but may not sign it off."""

    @staticmethod
    def _submitted_baseline():
        fixtures.set_clock(CLOCK_NOON)
        world = fixtures.site_with_one_capture(
            entry_overrides={"weight_grams": 1000, "captured_at": CAPTURED_AT}
        )
        world["shift"] = fixtures.close_shift(world["shift"]["id"])
        world["baseline"] = fixtures.open_baseline(world["site"]["id"])
        world["baseline"] = fixtures.submit_baseline(world["site"]["id"], world["baseline"]["id"])
        return world

    @pytest.mark.parametrize(
        "label,issue_decision",
        REVIEW_DECISIONS,
        ids=[label for label, _ in REVIEW_DECISIONS],
    )
    def test_the_site_cannot_decide_the_baseline_it_submitted(self, api, label, issue_decision):
        """Neither review outcome is open to the site itself, and the period stays in review.

        PRD Coverage: "Corporate review, exercised by a `CorporateSustainabilityLead`, has two outcomes." "`SiteSustainabilityManager` owns exactly one site and runs its baselines, diversion logistics, data-quality scans and weigh-ticket review, always restricted to rows carrying their own `site_id`." "When both headers are present and well-formed but the caller's role is not among the roles the target endpoint admits, the request fails with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/site_manager_cannot_certify_or_reject_the_baseline_it_submitted
        """
        world = self._submitted_baseline()
        site_id = world["site"]["id"]
        baseline = world["baseline"]

        response = issue_decision(
            api, baseline["id"], make_site_sustainability_manager_headers(site_id)
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED.value)

        unchanged = fixtures.read_baseline(baseline["id"])
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["version"] == baseline["version"]
        assert unchanged["certified_at"] is None
        assert unchanged["rejection_count"] == 0

    def test_a_corporate_identity_certifies_the_very_same_period(self, api):
        """The certification the site was refused succeeds for the corporate reviewer.

        PRD Coverage: "`CorporateSustainabilityLead` certifies and rejects baselines, creates and activates reduction targets, approves haulers, and prepares and publishes rollups." "`CERTIFIED` is the only status a reduction target may bind to."

        Design: Corner/rbac/site_manager_cannot_certify_or_reject_the_baseline_it_submitted
        """
        world = self._submitted_baseline()
        baseline = world["baseline"]

        certified = get_success_data(
            api.certify_baseline_period(baseline["id"], make_corporate_lead_headers("csl-1"))
        )
        assert_baseline_period(certified)
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_at"] is not None
        assert certified["version"] == baseline["version"] + 1


class TestTheCorporateSideCannotRunTheSiteFloor:
    """Authority runs both ways: the reviewer cannot do the reviewed site's own work."""

    @staticmethod
    def _site_and_pending_hauler():
        fixtures.set_clock(CLOCK_NOON)
        site = fixtures.create_site()
        hauler = fixtures.create_hauler()
        return site, hauler

    def test_the_corporate_lead_is_refused_on_baselines_logistics_and_scans(self, api):
        """Opening a baseline, opening a consignment and running a scan are all site-side writes.

        PRD Coverage: "`SiteSustainabilityManager` owns exactly one site and runs its baselines, diversion logistics, data-quality scans and weigh-ticket review, always restricted to rows carrying their own `site_id`." "A data-quality scan is requested by the owning `SiteSustainabilityManager` or by a `PlatformAdmin` for one `site_id` and one `scan_date`, and it materialises findings as durable rows." "When both headers are present and well-formed but the caller's role is not among the roles the target endpoint admits, the request fails with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/corporate_lead_cannot_open_a_baseline_or_run_site_logistics
        """
        site, hauler = self._site_and_pending_hauler()
        fixtures.approve_hauler(hauler["id"])
        corporate = make_corporate_lead_headers("csl-1")

        validate_error(
            api.create_baseline_period(factories.create_baseline_period_payload(site["id"]), corporate),
            ApiErrorId.UNAUTHORIZED.value,
        )
        validate_error(
            api.create_consignment(
                factories.create_consignment_payload(site["id"], hauler["id"], **PICKUP_WINDOW), corporate
            ),
            ApiErrorId.UNAUTHORIZED.value,
        )
        validate_error(
            api.create_data_quality_scan(
                factories.create_data_quality_scan_payload(site["id"], "2026-08-01"), corporate
            ),
            ApiErrorId.UNAUTHORIZED.value,
        )

        site_headers = make_site_sustainability_manager_headers(site["id"])
        _, baseline_meta = validate_paginated(api.list_baseline_periods(site_headers, site_id=site["id"]))
        assert baseline_meta["total_count"] == 0
        _, consignment_meta = validate_paginated(api.list_consignments(site_headers, site_id=site["id"]))
        assert consignment_meta["total_count"] == 0
        _, finding_meta = validate_paginated(api.list_findings(site_headers, site_id=site["id"]))
        assert finding_meta["total_count"] == 0

    def test_the_same_corporate_identity_still_approves_the_hauler(self, api):
        """The refusals are endpoint-scoped, not an identity problem: the approval it does own succeeds.

        PRD Coverage: "Approval belongs to `CorporateSustainabilityLead`, advances `PENDING → APPROVED`, is refused with `ERR_INVALID_HAULER_STATE` when the hauler is already approved, makes every consignment already staged against that hauler dispatchable, and increments the hauler's `version` by 1."

        Design: Corner/rbac/corporate_lead_cannot_open_a_baseline_or_run_site_logistics
        """
        _, hauler = self._site_and_pending_hauler()
        assert hauler["status"] == "PENDING"

        approved = get_success_data(api.approve_hauler(hauler["id"], make_corporate_lead_headers("csl-1")))
        assert_hauler(approved)
        assert approved["status"] == "APPROVED"
        assert approved["version"] == hauler["version"] + 1


# The operational writes the catalog owner is deliberately kept out of.
OPERATIONAL_WRITES_CLOSED_TO_THE_ADMIN = [
    (
        "capture",
        lambda api, headers, world: api.create_waste_entry(
            factories.create_waste_entry_payload(
                world["station"]["id"], world["shift"]["id"], world["food_type"]["id"],
                weight_grams=500, loss_reason="SPOILAGE", captured_at="2026-08-01T11:00:00Z",
            ),
            headers,
        ),
    ),
    (
        "void",
        lambda api, headers, world: api.void_waste_entry(
            world["entry"]["id"], factories.void_payload(void_reason="admin override"), headers
        ),
    ),
    ("close_shift", lambda api, headers, world: api.close_shift(world["shift"]["id"], headers)),
    (
        "rollup",
        lambda api, headers, world: api.create_rollup(
            factories.create_rollup_payload([world["site"]["id"]], period_end="2026-08-01"), headers
        ),
    ),
]


class TestTheCatalogOwnerHoldsNoOperationalAuthority:
    """The role that creates every dependency cannot record, void, close or report."""

    @staticmethod
    def _catalog_built_by_the_admin():
        fixtures.set_clock(CLOCK_NOON)
        world = fixtures.site_with_one_capture(
            entry_overrides={"weight_grams": 900, "captured_at": CAPTURED_AT}
        )
        return world

    @pytest.mark.parametrize(
        "label,issue_write",
        OPERATIONAL_WRITES_CLOSED_TO_THE_ADMIN,
        ids=[label for label, _ in OPERATIONAL_WRITES_CLOSED_TO_THE_ADMIN],
    )
    def test_the_platform_admin_is_refused_on_every_operational_write(self, api, label, issue_write):
        """Capture, void, closure and rollup preparation are all refused, and the period is untouched.

        PRD Coverage: "`PlatformAdmin` maintains the shared catalog — sites, food types, recipes, haulers and stations — and deliberately holds no operational authority over captures, service-period closure, baselines, targets, settlements or rollups, so administrative rights cannot be used to route around either duty separation." "When both headers are present and well-formed but the caller's role is not among the roles the target endpoint admits, the request fails with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/platform_admin_cannot_capture_void_or_close_despite_owning_the_catalog
        """
        world = self._catalog_built_by_the_admin()

        validate_error(
            issue_write(api, make_platform_admin_headers("pa-1"), world),
            ApiErrorId.UNAUTHORIZED.value,
        )

        shift = fixtures.read_shift(world["shift"]["id"])
        assert shift["status"] == "OPEN"
        assert shift["shift_waste_grams"] == 900
        entry = fixtures.read_entry(world["entry"]["id"])
        assert entry["status"] == "RECORDED"
        assert entry["version"] == world["entry"]["version"]

    def test_the_same_admin_identity_owns_the_catalog_the_floor_depends_on(self, api):
        """Site, station and food type all answer 201 for the very identity refused above.

        PRD Coverage: "No role is a superset of another." "`PlatformAdmin` maintains the shared catalog — sites, food types, recipes, haulers and stations — and deliberately holds no operational authority over captures, service-period closure, baselines, targets, settlements or rollups, so administrative rights cannot be used to route around either duty separation."

        Design: Corner/rbac/platform_admin_cannot_capture_void_or_close_despite_owning_the_catalog
        """
        fixtures.set_clock(CLOCK_NOON)
        admin = make_platform_admin_headers("pa-1")

        site = validate_success(api.create_site(factories.create_site_payload(), admin), 201)
        station = validate_success(
            api.create_tracking_station(factories.create_tracking_station_payload(site["id"]), admin), 201
        )
        food_type = validate_success(
            api.create_food_type(factories.create_food_type_payload(), admin), 201
        )

        assert site["id"] and station["site_id"] == site["id"] and food_type["id"]


# Kitchen-side reads the external collector is kept out of.
KITCHEN_SIDE_READS = [
    ("shift", lambda api, headers, world: api.get_shift(world["shift"]["id"], headers)),
    ("waste_entry", lambda api, headers, world: api.get_waste_entry(world["entry"]["id"], headers)),
    ("coaching_alerts", lambda api, headers, world: api.list_alerts(headers)),
    ("corporate_rollups", lambda api, headers, world: api.list_rollups(headers)),
]


class TestTheHaulerReadSurfaceStopsAtTheLoadingDock:
    """The external role's boundary is drawn on reads, not only on writes."""

    @staticmethod
    def _kitchen_and_a_consignment():
        fixtures.set_clock(CLOCK_NOON)
        return fixtures.site_with_draft_consignment(
            entry_overrides={"weight_grams": 900, "captured_at": CAPTURED_AT},
            consignment_overrides=dict(PICKUP_WINDOW),
        )

    @pytest.mark.parametrize(
        "label,issue_read",
        KITCHEN_SIDE_READS,
        ids=[label for label, _ in KITCHEN_SIDE_READS],
    )
    def test_the_hauler_operator_is_refused_on_the_kitchen_side_reads(self, api, label, issue_read):
        """Service periods, captures, alerts and rollups are all closed to the collector.

        PRD Coverage: "`HaulerOperator` files weigh tickets for consignments assigned to their hauler and may mark a staged consignment dispatched at pickup; they cannot read waste captures, service periods, baselines, targets, alerts, findings or rollups, and they may never accept or dispute their own ticket." "When both headers are present and well-formed but the caller's role is not among the roles the target endpoint admits, the request fails with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/hauler_operator_cannot_read_the_kitchen_side_of_the_data
        """
        world = self._kitchen_and_a_consignment()

        validate_error(
            issue_read(api, make_hauler_operator_headers(world["hauler"]["id"]), world),
            ApiErrorId.UNAUTHORIZED.value,
        )

    def test_the_capture_refusal_is_about_the_role_and_not_a_missing_row(self, api):
        """The capture the collector cannot read is demonstrably present for a permitted reader.

        PRD Coverage: "2. Role admission for the target endpoint — `ERR_UNAUTHORIZED`." "6. Existence of every identifier appearing in the URL path — the owning entity's not-found error."

        Design: Corner/rbac/hauler_operator_cannot_read_the_kitchen_side_of_the_data
        """
        world = self._kitchen_and_a_consignment()

        validate_error(
            api.get_waste_entry(world["entry"]["id"], make_hauler_operator_headers(world["hauler"]["id"])),
            ApiErrorId.UNAUTHORIZED.value,
        )

        present = fixtures.read_entry(world["entry"]["id"])
        assert_waste_entry(present)
        assert present["weight_grams"] == 900

    def test_the_same_identity_reads_its_own_hauler_and_consignment(self, api):
        """The collector's own two rows answer 200 for the identity refused on the kitchen side.

        PRD Coverage: "`HaulerOperator` files weigh tickets for consignments assigned to their hauler and may mark a staged consignment dispatched at pickup; they cannot read waste captures, service periods, baselines, targets, alerts, findings or rollups, and they may never accept or dispute their own ticket." "When `X-User-Role` is `HaulerOperator`, `X-User-ID` is the `id` of the acting `Hauler`; ownership checks on any consignment or weigh ticket compare its `hauler_id` to `X-User-ID`, and a mismatch is rejected with `ERR_HAULER_SCOPE_VIOLATION`."

        Design: Corner/rbac/hauler_operator_cannot_read_the_kitchen_side_of_the_data
        """
        world = self._kitchen_and_a_consignment()
        hauler_headers = make_hauler_operator_headers(world["hauler"]["id"])

        consignment = validate_success(
            api.get_consignment(world["consignment"]["id"], hauler_headers), 200
        )
        assert_consignment(consignment)
        assert consignment["hauler_id"] == world["hauler"]["id"]

        hauler = validate_success(api.get_hauler(world["hauler"]["id"], hauler_headers), 200)
        assert_hauler(hauler)


# Every role that is not the catalog owner, keyed by how its identity is formed.
NON_CATALOG_ROLES = [
    ("site_manager", lambda site_id: make_site_sustainability_manager_headers(site_id)),
    ("shift_lead", lambda site_id: make_shift_lead_headers("sl-1")),
    ("kitchen_staff", lambda site_id: make_kitchen_staff_headers("ks-1")),
    ("corporate_lead", lambda site_id: make_corporate_lead_headers("csl-1")),
]


class TestTheSharedCatalogHasASingleWriter:
    """Sites, food types, recipes and haulers are written by one role and no other."""

    def test_the_platform_admin_writes_all_four_catalog_resources(self, api):
        """One identity opens a site, a food type, a hauler and a recipe in a single pass.

        PRD Coverage: "`PlatformAdmin` maintains the shared catalog — sites, food types, recipes, haulers and stations — and deliberately holds no operational authority over captures, service-period closure, baselines, targets, settlements or rollups, so administrative rights cannot be used to route around either duty separation."

        Design: Corner/rbac/platform_admin_alone_writes_the_shared_catalog
        """
        fixtures.set_clock(CLOCK_NOON)
        admin = make_platform_admin_headers("pa-1")

        validate_success(api.create_site(factories.create_site_payload(), admin), 201)
        validate_success(api.create_food_type(factories.create_food_type_payload(), admin), 201)
        hauler = validate_success(api.create_hauler(factories.create_hauler_payload(), admin), 201)
        assert hauler["status"] == "PENDING"
        recipe = validate_success(api.create_recipe(factories.create_recipe_payload(), admin), 201)
        assert recipe["status"] == "DRAFT"

    @pytest.mark.parametrize(
        "label,build_headers",
        NON_CATALOG_ROLES,
        ids=[label for label, _ in NON_CATALOG_ROLES],
    )
    def test_no_other_role_may_open_a_site(self, api, label, build_headers):
        """A site creation is refused for every role but the catalog owner, and none is recorded.

        PRD Coverage: "No role is a superset of another." "When both headers are present and well-formed but the caller's role is not among the roles the target endpoint admits, the request fails with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/platform_admin_alone_writes_the_shared_catalog
        """
        fixtures.set_clock(CLOCK_NOON)
        existing = fixtures.create_site()

        validate_error(
            api.create_site(
                factories.create_site_payload(name="Pier Kitchen", site_code="PK-02"),
                build_headers(existing["id"]),
            ),
            ApiErrorId.UNAUTHORIZED.value,
        )

        _, meta = validate_paginated(api.list_sites(make_platform_admin_headers()))
        assert meta["total_count"] == 1, "only the catalog owner's site exists"

    def test_the_corporate_lead_may_approve_a_hauler_but_never_register_one(self, api):
        """Registration is refused for the reviewer; the very same identity then approves the row.

        PRD Coverage: "`CorporateSustainabilityLead` certifies and rejects baselines, creates and activates reduction targets, approves haulers, and prepares and publishes rollups." "Approval belongs to `CorporateSustainabilityLead`, advances `PENDING → APPROVED`, is refused with `ERR_INVALID_HAULER_STATE` when the hauler is already approved, makes every consignment already staged against that hauler dispatchable, and increments the hauler's `version` by 1."

        Design: Corner/rbac/platform_admin_alone_writes_the_shared_catalog
        """
        fixtures.set_clock(CLOCK_NOON)

        validate_error(
            api.create_hauler(factories.create_hauler_payload(), make_corporate_lead_headers("csl-1")),
            ApiErrorId.UNAUTHORIZED.value,
        )
        _, meta = validate_paginated(api.list_haulers(make_platform_admin_headers()))
        assert meta["total_count"] == 0

        registered = fixtures.create_hauler()
        approved = validate_success(
            api.approve_hauler(registered["id"], make_corporate_lead_headers("csl-1")), 200
        )
        assert approved["status"] == "APPROVED"


class TestCorporateWritesSitBehindOneRole:
    """Target proposal, hauler approval and rollup preparation are corporate-only writes."""

    @staticmethod
    def _certified_baseline_and_pending_hauler():
        fixtures.set_clock(CLOCK_NOON)
        world = fixtures.certified_baseline(
            entry_overrides={"weight_grams": 1000, "captured_at": CAPTURED_AT}
        )
        world["hauler"] = fixtures.create_hauler()
        world["site"] = fixtures.read_site(world["site"]["id"])
        return world

    def test_the_corporate_lead_proposes_a_target_approves_a_hauler_and_prepares_a_rollup(self, api):
        """All three writes land, and the new target opens in the proposal state.

        PRD Coverage: "`CorporateSustainabilityLead` certifies and rejects baselines, creates and activates reduction targets, approves haulers, and prepares and publishes rollups." "The new target itself opens in status `PROPOSED` with `activated_at` and `resolved_at` null, `performance_waste_grams` and `performance_meals_served` at 0, and `attainment_state` at `BEHIND`." "The rollup's `status` begins at `DRAFT`, which may only ever hold `DRAFT` or `PUBLISHED`, `prepared_by_user_id` is stamped with the acting `X-User-ID` — the value that segregation of duties will later be measured against — and `published_by_user_id`, `published_at` and `published_metrics` are all null."

        Design: Corner/rbac/corporate_lead_alone_writes_certification_targets_and_rollups
        """
        world = self._certified_baseline_and_pending_hauler()
        corporate = make_corporate_lead_headers("csl-1")

        target = validate_success(
            api.create_reduction_target(
                factories.create_reduction_target_payload(
                    world["site"]["id"], world["baseline"]["id"], world["site"]["version"],
                    basis="INTENSITY",
                ),
                corporate,
            ),
            201,
        )
        assert_reduction_target(target)
        assert target["status"] == "PROPOSED"
        assert target["attainment_state"] == "BEHIND"
        assert target["activated_at"] is None

        approved = validate_success(api.approve_hauler(world["hauler"]["id"], corporate), 200)
        assert approved["status"] == "APPROVED"

        rollup = validate_success(
            api.create_rollup(
                factories.create_rollup_payload([world["site"]["id"]], period_end="2026-08-01"), corporate
            ),
            201,
        )
        assert_corporate_rollup(rollup)
        assert rollup["status"] == "DRAFT"
        assert rollup["prepared_by_user_id"] == "csl-1"

    @pytest.mark.parametrize("role", ["site_manager", "platform_admin"])
    def test_neither_the_site_nor_the_admin_may_issue_a_corporate_write(self, api, role):
        """The three corporate bodies are refused for the site itself and for the catalog owner.

        PRD Coverage: "When both headers are present and well-formed but the caller's role is not among the roles the target endpoint admits, the request fails with `ERR_UNAUTHORIZED`." "`PlatformAdmin` maintains the shared catalog — sites, food types, recipes, haulers and stations — and deliberately holds no operational authority over captures, service-period closure, baselines, targets, settlements or rollups, so administrative rights cannot be used to route around either duty separation."

        Design: Corner/rbac/corporate_lead_alone_writes_certification_targets_and_rollups
        """
        world = self._certified_baseline_and_pending_hauler()
        site = world["site"]
        headers = (
            make_site_sustainability_manager_headers(site["id"])
            if role == "site_manager"
            else make_platform_admin_headers("pa-1")
        )

        validate_error(
            api.create_reduction_target(
                factories.create_reduction_target_payload(
                    site["id"], world["baseline"]["id"], site["version"], basis="INTENSITY"
                ),
                headers,
            ),
            ApiErrorId.UNAUTHORIZED.value,
        )
        validate_error(api.approve_hauler(world["hauler"]["id"], headers), ApiErrorId.UNAUTHORIZED.value)
        validate_error(
            api.create_rollup(
                factories.create_rollup_payload([site["id"]], period_end="2026-08-01"), headers
            ),
            ApiErrorId.UNAUTHORIZED.value,
        )

        _, target_meta = validate_paginated(
            api.list_reduction_targets(make_corporate_lead_headers("csl-1"), site_id=site["id"])
        )
        assert target_meta["total_count"] == 0
        _, rollup_meta = validate_paginated(api.list_rollups(make_corporate_lead_headers("csl-1")))
        assert rollup_meta["total_count"] == 0
        assert fixtures.read_hauler(world["hauler"]["id"])["status"] == "PENDING"

    def test_the_role_refusal_precedes_the_site_version_comparison(self, api):
        """A target proposal carrying a stale site token is still refused on the role, not the token.

        PRD Coverage: "2. Role admission for the target endpoint — `ERR_UNAUTHORIZED`." "10. Optimistic-concurrency token match — `ERR_STALE_ENTRY_VERSION` or `ERR_STALE_SITE_VERSION`."

        Design: Corner/rbac/corporate_lead_alone_writes_certification_targets_and_rollups
        """
        world = self._certified_baseline_and_pending_hauler()
        site = world["site"]

        stale_payload = factories.create_reduction_target_payload(
            site["id"], world["baseline"]["id"], site["version"] + 99, basis="INTENSITY"
        )
        validate_error(
            api.create_reduction_target(
                stale_payload, make_site_sustainability_manager_headers(site["id"])
            ),
            ApiErrorId.UNAUTHORIZED.value,
        )

        assert fixtures.read_site(site["id"])["version"] == site["version"]


class TestAllocationLinesArePeerWork:
    """Either the site manager or a supervisor may route grams, including each other's lines."""

    @staticmethod
    def _consignment_with_the_managers_line():
        fixtures.set_clock(CLOCK_NOON)
        world = fixtures.site_with_draft_consignment(
            entry_overrides={"weight_grams": 1000, "captured_at": CAPTURED_AT},
            consignment_overrides=dict(PICKUP_WINDOW),
        )
        world["second_entry"] = fixtures.capture_entry(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            weight_grams=800,
            loss_reason="SPOILAGE",
            captured_at=LATER_CAPTURED_AT,
        )
        world["manager_line"] = fixtures.add_line(
            world["site"]["id"], world["consignment"]["id"], world["entry"]["id"], 400
        )
        return world

    def test_a_supervisor_routes_grams_beside_the_managers_line(self, api):
        """The supervisor's line is accepted and records the supervisor's own identity.

        PRD Coverage: "**Allocation lines** attach captured grams to a consignment and may be created by either the owning `SiteSustainabilityManager` or a `ShiftLead`." "The platform stamps `created_by_user_id` with the acting `X-User-ID`."

        Design: Corner/rbac/site_manager_and_shift_lead_are_peers_on_consignment_lines
        """
        world = self._consignment_with_the_managers_line()
        assert world["manager_line"]["created_by_user_id"] == world["site"]["id"]

        line = validate_success(
            api.create_consignment_line(
                factories.create_consignment_line_payload(
                    world["consignment"]["id"], world["second_entry"]["id"], 300
                ),
                make_shift_lead_headers("sl-1"),
            ),
            201,
        )
        assert_consignment_line(line)
        assert line["created_by_user_id"] == "sl-1"
        assert line["allocated_weight_grams"] == 300

        consignment = fixtures.read_consignment(world["consignment"]["id"])
        assert consignment["line_count"] == 2
        assert consignment["staged_weight_grams"] == 700

    def test_a_supervisor_may_delete_the_line_the_manager_created(self, api):
        """The creating identity is recorded for audit but is never compared against the deleter.

        PRD Coverage: "Deleting a line — permitted only while the consignment is `DRAFT`, and available to the same two roles — restores the capture's unrouted grams exactly, so the identity that a capture's `weight_grams` equals its routed plus its unrouted grams holds continuously and with zero drift." "For the consignment, `staged_weight_grams` becomes the sum of `allocated_weight_grams` over its lines and `line_count` becomes the number of lines attached."

        Design: Corner/rbac/site_manager_and_shift_lead_are_peers_on_consignment_lines
        """
        world = self._consignment_with_the_managers_line()
        validate_success(
            api.create_consignment_line(
                factories.create_consignment_line_payload(
                    world["consignment"]["id"], world["second_entry"]["id"], 300
                ),
                make_shift_lead_headers("sl-1"),
            ),
            201,
        )

        validate_success(
            api.delete_consignment_line(world["manager_line"]["id"], make_shift_lead_headers("sl-1")), 200
        )

        consignment = fixtures.read_consignment(world["consignment"]["id"])
        assert consignment["staged_weight_grams"] == 300
        assert consignment["line_count"] == 1

        restored = fixtures.read_entry(world["entry"]["id"])
        assert restored["routed_weight_grams"] == 0
        assert restored["unrouted_weight_grams"] == 1000
        assert_waste_entry(restored)


class TestTheVoidDutySeparation:
    """A supervisor holds the void permission but not over the row they recorded."""

    @staticmethod
    def _capture_recorded_by_the_supervisor():
        fixtures.set_clock(CLOCK_NOON)
        world = fixtures.site_with_open_shift()
        world["entry"] = fixtures.capture_entry(
            world["station"]["id"],
            world["shift"]["id"],
            world["food_type"]["id"],
            as_kitchen_staff=False,
            user_id="sl-1",
            weight_grams=1000,
            captured_at=CAPTURED_AT,
        )
        return world

    def test_the_recording_supervisor_cannot_void_their_own_capture(self, api):
        """The refusal is on the identity, not the role, and the capture keeps its state.

        PRD Coverage: "A `ShiftLead` may not void a capture whose `captured_by_user_id` equals their own `X-User-ID`; a different `ShiftLead` identity must perform the void." "`captured_by_user_id` records the capturing operator's `X-User-ID`, which is the comparison target of the void duty separation."

        Design: Corner/rbac/a_shift_lead_cannot_void_the_capture_they_recorded_themselves
        """
        world = self._capture_recorded_by_the_supervisor()
        entry = world["entry"]
        assert entry["captured_by_user_id"] == "sl-1"

        validate_error(
            api.void_waste_entry(
                entry["id"],
                factories.void_payload(void_reason="double counted the tray"),
                make_shift_lead_headers("sl-1"),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        unchanged = fixtures.read_entry(entry["id"])
        assert unchanged["status"] == "RECORDED"
        assert unchanged["version"] == entry["version"]
        assert fixtures.read_shift(world["shift"]["id"])["shift_waste_grams"] == 1000

    def test_a_second_supervisor_identity_voids_the_same_capture(self, api):
        """The refused call left no trace, so the second identity's void is the row's only write.

        PRD Coverage: "The acting `ShiftLead`'s `X-User-ID` must differ from the capture's `captured_by_user_id`; a lead attempting to erase their own capture is refused with `ERR_SEGREGATION_OF_DUTIES`." "In the first hop the capture's status becomes `VOIDED`, `void_reason` is stored, and the entry leaves every `RECORDED`-or-`FLAGGED` aggregation set."

        Design: Corner/rbac/a_shift_lead_cannot_void_the_capture_they_recorded_themselves
        """
        world = self._capture_recorded_by_the_supervisor()
        entry = world["entry"]

        validate_error(
            api.void_waste_entry(
                entry["id"],
                factories.void_payload(void_reason="double counted the tray"),
                make_shift_lead_headers("sl-1"),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        voided = validate_success(
            api.void_waste_entry(
                entry["id"],
                factories.void_payload(void_reason="double counted the tray"),
                make_shift_lead_headers("sl-2"),
            ),
            200,
        )
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "double counted the tray"
        assert voided["version"] == entry["version"] + 1, "only the successful void wrote to the row"

        assert fixtures.read_shift(world["shift"]["id"])["shift_waste_grams"] == 0


class TestThePublicationDutySeparation:
    """The lead who assembles the company report may not be the lead who signs it."""

    @staticmethod
    def _draft_rollup_prepared_by_the_first_lead():
        fixtures.set_clock(CLOCK_NOON)
        world = fixtures.closed_shift_with_capture(
            entry_overrides={"weight_grams": 1000, "captured_at": CAPTURED_AT}
        )
        world["rollup"] = fixtures.prepare_rollup(
            [world["site"]["id"]], user_id="csl-1", period_end="2026-08-01"
        )
        return world

    def test_the_preparing_lead_cannot_publish_their_own_rollup(self, api):
        """The report stays in draft when its own author tries to sign it off.

        PRD Coverage: "A `CorporateSustainabilityLead` may not publish a rollup whose `prepared_by_user_id` equals their own `X-User-ID`; a second `CorporateSustainabilityLead` identity must publish it." "The acting `X-User-ID` must differ from `prepared_by_user_id`, refused otherwise with `ERR_SEGREGATION_OF_DUTIES` — the lead who assembled a report may never be the lead who signs it off, however senior."

        Design: Corner/rbac/a_corporate_lead_cannot_publish_the_rollup_they_prepared
        """
        world = self._draft_rollup_prepared_by_the_first_lead()
        rollup = world["rollup"]
        assert rollup["prepared_by_user_id"] == "csl-1"

        validate_error(
            api.publish_rollup(rollup["id"], make_corporate_lead_headers("csl-1")),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        unchanged = fixtures.read_rollup(rollup["id"])
        assert unchanged["status"] == "DRAFT"
        assert unchanged["version"] == rollup["version"]
        assert unchanged["published_by_user_id"] is None
        assert unchanged["published_at"] is None
        assert unchanged["published_metrics"] is None

    def test_a_second_corporate_identity_signs_the_report_off(self, api):
        """Both identities end up recorded on the row: one prepared it, the other published it.

        PRD Coverage: "A `CorporateSustainabilityLead` may not publish a rollup whose `prepared_by_user_id` equals their own `X-User-ID`; a second `CorporateSustainabilityLead` identity must publish it." "`published_by_user_id` is stamped with the acting `X-User-ID`, `published_at` with the current logical clock, `status` advances `DRAFT → PUBLISHED`, and `version` is incremented by 1."

        Design: Corner/rbac/a_corporate_lead_cannot_publish_the_rollup_they_prepared
        """
        world = self._draft_rollup_prepared_by_the_first_lead()
        rollup = world["rollup"]

        validate_error(
            api.publish_rollup(rollup["id"], make_corporate_lead_headers("csl-1")),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        published = validate_success(
            api.publish_rollup(rollup["id"], make_corporate_lead_headers("csl-2")), 200
        )
        assert_corporate_rollup(published)
        assert published["status"] == "PUBLISHED"
        assert published["published_by_user_id"] == "csl-2"
        assert published["prepared_by_user_id"] == "csl-1"
        assert published["version"] == rollup["version"] + 1
