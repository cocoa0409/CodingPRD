"""Per-entity birth state, reads, listing, shape rules and FK integrity.

These are the §1.1/§1.5 entity-level guarantees: the full set of fields a fresh
row carries, the filtered-and-paginated collection surface, the entity-scoped
not-found catalogue of PRD §2.11, and the three shape refusals of PRD §2.7
(unknown key, missing required input, non-member enum value).
"""

from test_helpers import (
    CAPACITY_CEILING,
    DEFAULT_LOGICAL_CLOCK,
    NON_EXISTENT_ID,
    admin_headers,
    applicant_creation_headers,
    assert_capacity_slots,
    assert_checklist_item,
    assert_created_at_ascending,
    assert_instant,
    assert_point_ledger,
    assert_score,
    factories as f,
    fixtures as fx,
    intake_headers,
    make_applicant_headers,
    make_inspector_headers,
    supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ALL_AGE_GROUPS = ["INFANT", "TODDLER", "PRESCHOOL", "SCHOOL_AGE"]


def _create_provider_raw(api, **overrides):
    """POST /licensing/providers with the one identity envelope it accepts: the
    ``Applicant`` role and no ``X-User-ID``."""
    return api.create_provider(
        f.provider_payload(**overrides), headers=applicant_creation_headers()
    )


class TestProviderBirthStateAndReads:
    """§3.2: "The new record starts with `application_status` at `DRAFT` and
    `license_status` at `NONE`"."""

    def test_creation_returns_every_declared_provider_field(self, api):
        """A CENTER application created with the five required inputs answers 201
        with the derived ceiling of 120 and every counter at 0.

        PRD §3.2: "From the programme class the service derives
        `capacity_ceiling`, the statutory maximum: 120 children for a `CENTER`,
        40 for a `GROUP_HOME`, 12 for a `FAMILY_HOME`. ... The new record starts
        with `application_status` at `DRAFT` and `license_status` at `NONE`; with
        `licensed_capacity`, `suspended_capacity`, `open_violation_points`,
        `resolved_violation_points`, `lifetime_violation_points`,
        `critical_open_count`, `critical_violation_count_24mo`,
        `substantiated_complaint_count_24mo`, `inconclusive_complaint_count_24mo`,
        `risk_score`, `current_ladder_step` and `probation_cycle_count` all at 0;
        with `risk_tier` at `LOW`; with `clearance_complete` false; and with
        `license_number`, `licensed_at`, `provisional_started_at` and
        `decision_reason` all null."

        Design: Corner/entities/entity_creation_provider_returns_all_declared_fields
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = validate_success(
            _create_provider_raw(
                api,
                legal_name="Bright Start Center",
                county_code="CTY-01",
                site_address="12 Elm St",
                program_type="CENTER",
                requested_capacity=20,
            ),
            201,
        )

        assert provider["legal_name"] == "Bright Start Center"
        assert provider["site_address"] == "12 Elm St"
        assert provider["county_code"] == "CTY-01"
        assert provider["program_type"] == "CENTER"
        assert provider["requested_capacity"] == 20
        assert provider["capacity_ceiling"] == CAPACITY_CEILING["CENTER"] == 120
        assert provider["application_status"] == "DRAFT"
        assert provider["license_status"] == "NONE"
        assert_capacity_slots(provider, 0, 0)
        assert provider["license_number"] is None
        assert provider["licensed_at"] is None
        assert provider["provisional_started_at"] is None
        assert provider["decision_reason"] is None
        assert_point_ledger(provider, 0, 0, 0)
        assert provider["critical_open_count"] == 0
        assert provider["critical_violation_count_24mo"] == 0
        assert provider["substantiated_complaint_count_24mo"] == 0
        assert provider["inconclusive_complaint_count_24mo"] == 0
        assert_score(provider["risk_score"], 0.00, "risk_score")
        assert provider["risk_tier"] == "LOW"
        assert provider["current_ladder_step"] == 0
        assert provider["probation_cycle_count"] == 0
        assert provider["clearance_complete"] is False
        assert provider["version"] == 1
        assert_instant(provider["created_at"], DEFAULT_LOGICAL_CLOCK, "created_at")
        assert_instant(provider["updated_at"], DEFAULT_LOGICAL_CLOCK, "updated_at")

    def test_single_resource_read_returns_the_stored_row_to_its_owner(self, api):
        """The applicant reads its own GROUP_HOME record back with the ceiling of
        40 that the programme class derived one call earlier.

        PRD §3.2: "40 for a `GROUP_HOME`"; §2.5: "`version`, an integer that
        starts at 1 on creation and increments by exactly 1 on each mutation of
        the row."

        Design: Corner/entities/entity_retrieval_provider_by_id_returns_stored_row
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        created = validate_success(
            _create_provider_raw(
                api,
                legal_name="Maple House",
                site_address="9 Maple Rd",
                program_type="GROUP_HOME",
                requested_capacity=12,
            ),
            201,
        )

        stored = validate_success(
            api.get_provider(created["id"], headers=make_applicant_headers(created["id"]))
        )
        assert stored["id"] == created["id"]
        assert stored["legal_name"] == "Maple House"
        assert stored["program_type"] == "GROUP_HOME"
        assert stored["capacity_ceiling"] == CAPACITY_CEILING["GROUP_HOME"] == 40
        assert stored["requested_capacity"] == 12
        assert stored["licensed_capacity"] == 0
        assert stored["version"] == 1

    def test_listing_filters_by_county_and_pages_one_row_at_a_time(self, api):
        """Two CTY-01 rows and one CTY-02 row: `county_code=CTY-01&limit=1` yields
        the older row with `total_count` 2 and `has_more` true, and `offset=1`
        yields the younger with `has_more` false.

        PRD §2.3: "List results are ordered by `created_at` ascending ... The
        `meta` object of a list response carries `limit`, `offset`, `total_count`
        and `has_more`, where `total_count` counts every row matching the
        request's filters before the page window is applied and `has_more` states
        whether any row remains beyond the current window."

        Design: Corner/entities/entity_listing_providers_filtered_and_paginated
        """
        # The three rows are created one minute apart because `created_at`
        # ascending is only a total order when the stamps differ.
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        alpha = validate_success(
            _create_provider_raw(api, legal_name="Alpha Care", site_address="1 A St"), 201
        )
        fx.set_clock(api, "2026-08-01T00:01:00Z")
        beta = validate_success(
            _create_provider_raw(api, legal_name="Beta Care", site_address="2 B St"), 201
        )
        fx.set_clock(api, "2026-08-01T00:02:00Z")
        gamma = validate_success(
            _create_provider_raw(
                api, legal_name="Gamma Care", site_address="3 C St", county_code="CTY-02"
            ),
            201,
        )

        first, meta_first = validate_paginated(
            api.list_providers(headers=admin_headers(), county_code="CTY-01", limit=1, offset=0)
        )
        assert [row["id"] for row in first] == [alpha["id"]]
        assert meta_first["total_count"] == 2
        assert meta_first["limit"] == 1
        assert meta_first["offset"] == 0
        assert meta_first["has_more"] is True

        second, meta_second = validate_paginated(
            api.list_providers(headers=admin_headers(), county_code="CTY-01", limit=1, offset=1)
        )
        assert [row["id"] for row in second] == [beta["id"]]
        assert meta_second["total_count"] == 2
        assert meta_second["offset"] == 1
        assert meta_second["has_more"] is False

        every_row, _meta = validate_paginated(api.list_providers(headers=admin_headers()))
        assert_created_at_ascending(every_row)
        assert gamma["id"] not in [row["id"] for row in first + second], (
            "the county_code filter excludes the CTY-02 row from both pages"
        )


class TestNotFoundAndShapeRefusals:
    """§2.11: "the first segment that does not resolve produces that entity's own
    not-found error with HTTP 404"."""

    def test_every_single_resource_get_has_its_own_not_found_error(self, api):
        """Fourteen reads of the same unknown id answer with fourteen distinct
        entity-scoped 404s and never a generic not-found.

        PRD §2.11: "The identifiers appearing in paths are `provider_id`,
        `inspector_id`, `staff_member_id`, `background_check_id`, `roster_id`,
        `inspection_id`, `violation_id`, `complaint_id`, `cap_id`, `action_id`,
        `amendment_id`, `report_id`, `posting_id` and `checklist_item_id`, and
        their respective failures are `ERR_PROVIDER_NOT_FOUND`,
        `ERR_INSPECTOR_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`,
        `ERR_BACKGROUND_CHECK_NOT_FOUND`, `ERR_ROSTER_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`,
        `ERR_COMPLAINT_NOT_FOUND`, `ERR_CAP_NOT_FOUND`,
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`,
        `ERR_INCIDENT_REPORT_NOT_FOUND`, `ERR_POSTING_NOT_FOUND` and
        `ERR_CHECKLIST_ITEM_NOT_FOUND`."

        Design: Corner/entities/entity_not_found_unknown_path_ids_return_entity_scoped_404
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        hdrs = admin_headers()
        reads = [
            (api.get_provider, "ERR_PROVIDER_NOT_FOUND"),
            (api.get_inspector, "ERR_INSPECTOR_NOT_FOUND"),
            (api.get_checklist_item, "ERR_CHECKLIST_ITEM_NOT_FOUND"),
            (api.get_staff_member, "ERR_STAFF_MEMBER_NOT_FOUND"),
            (api.get_background_check, "ERR_BACKGROUND_CHECK_NOT_FOUND"),
            (api.get_roster, "ERR_ROSTER_NOT_FOUND"),
            (api.get_inspection, "ERR_INSPECTION_NOT_FOUND"),
            (api.get_violation, "ERR_VIOLATION_NOT_FOUND"),
            (api.get_complaint, "ERR_COMPLAINT_NOT_FOUND"),
            (api.get_cap, "ERR_CAP_NOT_FOUND"),
            (api.get_enforcement_action, "ERR_ENFORCEMENT_ACTION_NOT_FOUND"),
            (api.get_amendment, "ERR_AMENDMENT_NOT_FOUND"),
            (api.get_incident_report, "ERR_INCIDENT_REPORT_NOT_FOUND"),
            (api.get_posting, "ERR_POSTING_NOT_FOUND"),
        ]
        for read, expected_error in reads:
            validate_error(read(NON_EXISTENT_ID, headers=hdrs), expected_error, 404)

    def test_missing_required_input_and_unknown_key_are_both_invalid_request(self, api):
        """An omitted `program_type`, an omitted `qualified_age_groups` and an
        undeclared `nickname` are all ERR_INVALID_REQUEST 400, and none of the
        three leaves a row behind.

        PRD §2.7: "Next comes request shape: the body must contain no unknown keys
        and every non-optional input field must be present and of its declared
        scalar type (otherwise `ERR_INVALID_REQUEST`, HTTP 400)"

        Design: Corner/entities/entity_required_fields_omitted_input_invalid_request
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = validate_success(
            _create_provider_raw(api, legal_name="Bright Start Center"), 201
        )
        prov_headers = make_applicant_headers(provider["id"])

        validate_error(
            api.create_provider(
                {
                    "legal_name": "No Program Type",
                    "county_code": "CTY-01",
                    "site_address": "5 D St",
                    "requested_capacity": 20,
                },
                headers=applicant_creation_headers(),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_staff_member(
                {
                    "provider_id": provider["id"],
                    "full_name": "Dana Reed",
                    "member_type": "DIRECTOR",
                    "date_of_birth": "1985-04-02",
                },
                headers=prov_headers,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_staff_member(
                {
                    "provider_id": provider["id"],
                    "full_name": "Dana Reed",
                    "member_type": "DIRECTOR",
                    "date_of_birth": "1985-04-02",
                    "qualified_age_groups": ["INFANT"],
                    "nickname": "Dee",
                },
                headers=prov_headers,
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        _rows, meta = validate_paginated(api.list_providers(headers=admin_headers()))
        assert meta["total_count"] == 1, "the refused create persisted no second provider"
        _staff, staff_meta = validate_paginated(
            api.list_staff_members(headers=admin_headers(), provider_id=provider["id"])
        )
        assert staff_meta["total_count"] == 0

    def test_omitted_optionals_take_their_declared_defaults(self, api):
        """Four defaults land in one chain — `max_daily_visits` 3,
        `infant_sensitive` false, the roster counts at 0 and `duration_minutes`
        120 — and the visit window ends exactly 120 minutes after its start.

        PRD §3.1: "an optional `infant_sensitive` flag that defaults to false when
        omitted"; "an optional `max_daily_visits` ceiling between 1 and 8 that
        defaults to 3 when omitted. A new inspector starts with `status` equal to
        `ACTIVE`"; §3.4: "an optional `duration_minutes` between 30 and 480 that
        defaults to 120 ... The service derives `visit_window_end` as the start
        instant plus the duration in minutes, creates the record in `SCHEDULED`
        with `started_at`, `submitted_at`, `finalized_at`, `age_groups_observed`,
        `outcome`, `preliminary_compliance_score`, `final_compliance_score` and
        `raw_deduction_points` all null"

        Design: Corner/entities/entity_defaults_omitted_optionals_take_declared_defaults
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        item = validate_success(
            api.create_checklist_item(
                {
                    "code": "FA-401",
                    "title": "Indoor play area free of hazards",
                    "category": "FACILITY",
                    "default_severity": "MODERATE",
                    "age_groups_applicable": ALL_AGE_GROUPS,
                },
                headers=admin_headers(),
            ),
            201,
        )
        assert item["infant_sensitive"] is False

        inspector = validate_success(
            api.create_inspector(
                {
                    "full_name": "Ivy Cole",
                    "county_code": "CTY-01",
                    "certified_age_groups": ["INFANT", "PRESCHOOL"],
                },
                headers=admin_headers(),
            ),
            201,
        )
        assert inspector["max_daily_visits"] == 3
        assert inspector["status"] == "ACTIVE"
        assert inspector["scheduled_visit_count"] == 0

        provider = validate_success(
            _create_provider_raw(api, requested_capacity=20), 201
        )
        roster = validate_success(
            api.create_roster(
                {
                    "provider_id": provider["id"],
                    "age_group": "INFANT",
                    "requested_group_size": 8,
                },
                headers=make_applicant_headers(provider["id"]),
            ),
            201,
        )
        assert roster["enrolled_count"] == 0
        assert roster["staff_assigned_count"] == 0
        assert roster["lead_staff_member_id"] is None
        assert roster["approved_group_size"] == 0
        assert roster["required_staff_count"] == 0
        assert roster["ratio_compliant"] is True
        assert roster["group_size_compliant"] is True
        assert roster["supervision_compliant"] is True, (
            "§3.2: a room 'is supervision-compliant when no children are "
            "enrolled', whatever its lead"
        )

        inspection = validate_success(
            api.create_inspection(
                {
                    "provider_id": provider["id"],
                    "inspector_id": inspector["id"],
                    "inspection_type": "ANNUAL",
                    "scheduled_for": "2026-08-05T09:00:00Z",
                    "target_age_groups": ["INFANT", "PRESCHOOL"],
                },
                headers=supervisor_headers(),
            ),
            201,
        )
        assert inspection["duration_minutes"] == 120
        assert_instant(
            inspection["visit_window_end"], "2026-08-05T11:00:00Z", "visit_window_end"
        )
        assert inspection["status"] == "SCHEDULED"
        assert inspection["complaint_id"] is None
        assert inspection["age_groups_observed"] is None
        assert inspection["outcome"] is None
        assert inspection["started_at"] is None
        assert inspection["submitted_at"] is None
        assert inspection["finalized_at"] is None
        assert inspection["preliminary_compliance_score"] is None
        assert inspection["final_compliance_score"] is None
        assert inspection["raw_deduction_points"] is None
        assert inspection["violation_count"] == 0
        assert inspection["reopen_count"] == 0
        assert inspection["cap_required"] is False

        after = validate_success(api.get_inspector(inspector["id"], headers=admin_headers()))
        assert after["scheduled_visit_count"] == 1

    def test_a_client_supplied_capacity_ceiling_is_an_unknown_key(self, api):
        """`capacity_ceiling` is derived, so sending it is refused as an unknown
        key while the omitted-body create derives 12 for a FAMILY_HOME.

        PRD §3.2: "From the programme class the service derives
        `capacity_ceiling`, the statutory maximum: ... 12 for a `FAMILY_HOME`."

        Design: Corner/entities/entity_computed_fields_capacity_ceiling_client_value_rejected
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        validate_error(
            api.create_provider(
                {
                    "legal_name": "Ceiling Hack",
                    "county_code": "CTY-01",
                    "site_address": "7 E St",
                    "program_type": "FAMILY_HOME",
                    "requested_capacity": 10,
                    "capacity_ceiling": 99,
                },
                headers=applicant_creation_headers(),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        provider = validate_success(
            _create_provider_raw(
                api,
                legal_name="Willow Family Home",
                site_address="7 E St",
                program_type="FAMILY_HOME",
                requested_capacity=10,
            ),
            201,
        )
        assert provider["capacity_ceiling"] == CAPACITY_CEILING["FAMILY_HOME"] == 12
        assert provider["requested_capacity"] == 10
        assert provider["licensed_capacity"] == 0


class TestSystemFieldsTypesAndReferences:
    """§2.5: "Every resource carries a server-minted `id` — a UUID with no type
    prefix — and a `created_at` timestamp: an ISO 8601 UTC instant with three
    fractional digits, taken from the logical clock at creation"."""

    def test_timestamps_and_versions_are_stamped_from_the_logical_clock(self, api):
        """`created_at` freezes at the creation instant while the cascade of a
        later staff write moves the provider's `updated_at` a day forward and
        lifts its `version` from 1 to 2.

        PRD §3.2: "A newly attached person starts with `clearance_status` at
        `PENDING`, `supervision_eligible` false and `barred_offense_tier` at
        `NONE`, and attaching them immediately recomputes the provider's
        `clearance_complete` — adding an uncleared person to a fully cleared
        provider flips that flag to false — and increments the provider's
        `version`."

        Design: Corner/entities/entity_system_fields_timestamps_and_version_are_server_stamped
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = validate_success(
            _create_provider_raw(api, legal_name="Bright Start Center"), 201
        )
        assert provider["version"] == 1

        fx.set_clock(api, "2026-08-02T00:00:00Z")
        director = validate_success(
            api.create_staff_member(
                f.staff_member_payload(
                    provider["id"],
                    qualified_age_groups=["INFANT", "TODDLER", "PRESCHOOL"],
                    role_title="Director",
                ),
                headers=make_applicant_headers(provider["id"]),
            ),
            201,
        )
        assert_instant(director["created_at"], "2026-08-02T00:00:00Z", "created_at")
        assert director["version"] == 1
        assert director["clearance_status"] == "PENDING"
        assert director["supervision_eligible"] is False
        assert director["barred_offense_tier"] == "NONE"
        assert director["id"] != provider["id"], "ids are independently minted"

        reread = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert_instant(reread["created_at"], DEFAULT_LOGICAL_CLOCK, "created_at")
        assert_instant(reread["updated_at"], "2026-08-02T00:00:00Z", "updated_at")
        assert reread["version"] == 2

    def test_a_value_outside_a_declared_enum_is_422_not_400(self, api):
        """A bogus `program_type`, a bogus `allegation_category` and the reserved
        `AGENCY_INCIDENT` channel are all ERR_INVALID_ENUM_VALUE 422.

        PRD §3.7: "`AGENCY_INCIDENT` is reserved for the system's own use, so a
        client that names that channel is refused with `ERR_INVALID_ENUM_VALUE`
        (HTTP 422) even though it is a member of the declared set."

        Design: Corner/entities/entity_type_constraints_invalid_enum_member_rejected
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = validate_success(
            _create_provider_raw(api, legal_name="Bright Start Center"), 201
        )

        validate_error(
            api.create_provider(
                f.provider_payload(
                    legal_name="Odd Program",
                    site_address="8 F St",
                    program_type="PRESCHOOL_CENTER",
                    requested_capacity=20,
                ),
                headers=applicant_creation_headers(),
            ),
            "ERR_INVALID_ENUM_VALUE",
            422,
        )
        validate_error(
            api.create_complaint(
                f.complaint_payload(
                    provider["id"],
                    allegation_category="GOSSIP",
                    narrative="Unclear report.",
                ),
                headers=intake_headers(),
            ),
            "ERR_INVALID_ENUM_VALUE",
            422,
        )
        validate_error(
            api.create_complaint(
                f.complaint_payload(
                    provider["id"],
                    intake_channel="AGENCY_INCIDENT",
                    narrative="Client tries to forge an agency-generated intake.",
                ),
                headers=intake_headers(),
            ),
            "ERR_INVALID_ENUM_VALUE",
            422,
        )

        _complaints, complaint_meta = validate_paginated(
            api.list_complaints(headers=admin_headers(), provider_id=provider["id"])
        )
        assert complaint_meta["total_count"] == 0
        _providers, provider_meta = validate_paginated(
            api.list_providers(headers=admin_headers())
        )
        assert provider_meta["total_count"] == 1

    def test_a_checklist_item_carries_no_revision_counter_and_no_duplicate_code(
        self, api
    ):
        """The catalog row reads back without `version` or `updated_at`, and a
        second SU-101 is refused as an invalid request.

        PRD §2.5: "a `ChecklistItem` is immutable configuration, has no update or
        delete capability, and carries only `id` and `created_at` — it has neither
        `updated_at` nor `version`, and callers must not expect either field on
        it."  §3.1: "a `code` that must match the pattern of two uppercase
        letters, a hyphen and three digits (for example `SU-101`) and that must be
        unique across the whole catalog — a duplicate is refused with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/entity_immutability_checklist_item_has_no_version_and_no_write_endpoint
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        created = validate_success(
            api.create_checklist_item(
                {
                    "code": "SU-101",
                    "title": "Direct supervision of children",
                    "category": "SUPERVISION",
                    "default_severity": "CRITICAL",
                    "age_groups_applicable": ALL_AGE_GROUPS,
                    "infant_sensitive": True,
                },
                headers=admin_headers(),
            ),
            201,
        )
        inspector = fx.register_inspector(api)

        read_back = validate_success(
            api.get_checklist_item(
                created["id"], headers=make_inspector_headers(inspector["id"])
            )
        )
        assert read_back["code"] == "SU-101"
        assert read_back["default_severity"] == "CRITICAL"
        assert read_back["infant_sensitive"] is True
        assert_checklist_item(read_back)

        validate_error(
            api.create_checklist_item(
                {
                    "code": "SU-101",
                    "title": "Duplicate code attempt",
                    "category": "SUPERVISION",
                    "default_severity": "SERIOUS",
                    "age_groups_applicable": ["INFANT"],
                    "infant_sensitive": False,
                },
                headers=admin_headers(),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        _rows, meta = validate_paginated(
            api.list_checklist_items(headers=admin_headers(), code="SU-101")
        )
        assert meta["total_count"] == 1

    def test_an_unresolvable_body_fk_reports_the_referenced_entity_not_found(self, api):
        """A `provider_id` naming no row is ERR_PROVIDER_NOT_FOUND, and the
        accepted sibling call is reachable through the filtered collection.

        PRD §2.11: "The same catalogue answers unresolvable foreign keys supplied
        in a request body, resolved in the order the endpoint declares its inputs.
        A `provider_id` that matches no provider is `ERR_PROVIDER_NOT_FOUND`"

        Design: Corner/entities/entity_parent_relationships_staff_provider_id_must_resolve_not_found
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = validate_success(
            _create_provider_raw(api, legal_name="Bright Start Center"), 201
        )

        validate_error(
            api.create_staff_member(
                f.staff_member_payload(
                    NON_EXISTENT_ID,
                    full_name="Ghost Staff",
                    member_type="ASSISTANT",
                    date_of_birth="1990-01-01",
                    qualified_age_groups=["PRESCHOOL"],
                ),
                headers=admin_headers(),
            ),
            "ERR_PROVIDER_NOT_FOUND",
            404,
        )

        director = validate_success(
            api.create_staff_member(
                f.staff_member_payload(provider["id"], role_title="Director"),
                headers=make_applicant_headers(provider["id"]),
            ),
            201,
        )
        assert director["provider_id"] == provider["id"]

        rows, meta = validate_paginated(
            api.list_staff_members(headers=admin_headers(), provider_id=provider["id"])
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [director["id"]]

    def test_the_complaint_inspection_pairing_rule_fires_three_ways(self, api):
        """A COMPLAINT visit without a complaint, one naming another provider's
        complaint, and an ANNUAL visit carrying a complaint are each 400 — only
        the matched pair is scheduled.

        PRD §3.4: "a `complaint_id` that is **required exactly when** the type is
        `COMPLAINT` and **forbidden otherwise**; a complaint reference supplied on
        any other type, or omitted on a complaint visit, or naming a complaint
        whose `provider_id` differs from the inspection's, is
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/entity_foreign_key_integrity_complaint_inspection_pairing_rejected
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        inspector = fx.register_inspector(
            api, certified_age_groups=["INFANT", "PRESCHOOL"]
        )
        provider_a = validate_success(
            _create_provider_raw(api, legal_name="Provider A", site_address="1 A St"), 201
        )
        provider_b = validate_success(
            _create_provider_raw(api, legal_name="Provider B", site_address="2 B St"), 201
        )
        complaint_b = validate_success(
            api.create_complaint(
                f.complaint_payload(
                    provider_b["id"],
                    allegation_category="RECORDS",
                    narrative="Attendance records incomplete.",
                ),
                headers=intake_headers(),
            ),
            201,
        )

        def _schedule(provider_id, inspection_type, complaint_id=None):
            payload = {
                "provider_id": provider_id,
                "inspector_id": inspector["id"],
                "inspection_type": inspection_type,
                "scheduled_for": "2026-08-05T09:00:00Z",
                "target_age_groups": ["PRESCHOOL"],
            }
            if complaint_id is not None:
                payload["complaint_id"] = complaint_id
            return api.create_inspection(payload, headers=supervisor_headers())

        validate_error(
            _schedule(provider_a["id"], "COMPLAINT"), "ERR_INVALID_REQUEST", 400
        )
        validate_error(
            _schedule(provider_a["id"], "COMPLAINT", complaint_b["id"]),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            _schedule(provider_b["id"], "ANNUAL", complaint_b["id"]),
            "ERR_INVALID_REQUEST",
            400,
        )

        accepted = validate_success(
            _schedule(provider_b["id"], "COMPLAINT", complaint_b["id"]), 201
        )
        assert accepted["complaint_id"] == complaint_b["id"]
        assert accepted["provider_id"] == provider_b["id"]

        after = validate_success(api.get_inspector(inspector["id"], headers=admin_headers()))
        assert after["scheduled_visit_count"] == 1, (
            "only the accepted call occupied a window"
        )
