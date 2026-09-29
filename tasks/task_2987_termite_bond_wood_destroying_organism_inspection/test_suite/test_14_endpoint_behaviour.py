"""Endpoint behaviour of the clock, the graph listing, the licence-status
channel, bond issuance windows, renewal invoicing and gallon accumulation.
"""

from test_helpers import (
    BOND_ACTIVE,
    BRANCH_MANAGER_ID,
    CLOCK_STARTUP_INSTANT,
    ERR_INVALID_BOND_STATE,
    ERR_INVALID_PLAN_STATE,
    ERR_RENEWAL_ALREADY_PENDING,
    ERR_RENEWAL_WINDOW_NOT_OPEN,
    ERR_STALE_VERSION,
    ERR_UNAUTHORIZED,
    INSPECTION_DRAFT,
    INSPECTION_SUPERSEDED,
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_EXPIRED,
    LICENSE_STATUS_SUSPENDED,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    PLAN_APPROVED,
    PLAN_COMPLETED,
    PURPOSE_INITIAL,
    PURPOSE_REAL_ESTATE,
    PURPOSE_RENEWAL,
    RENEWAL_PENDING,
    application_payload,
    approved_plan,
    assert_instant_equals,
    assert_money,
    assert_page,
    assert_renewal_invoice,
    assert_status,
    assert_version,
    bonded_property,
    clock_payload,
    graphed_inspection,
    license_status_payload,
    make_applicator_headers,
    make_property_owner_headers,
    open_graph,
    property_payload,
    register_inspector,
    register_property_and_inspector,
    set_clock,
    sign_empty_graph,
    validate_error,
    validate_success,
)

BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"


def _four_graphs_on_one_property(api):
    """One structure carrying four graphs of three purposes, one of them signed.

    The four occupations merely touch at their endpoints, which the diary rule
    permits, so the licensee can hold all four without a collision.
    """
    prop, inspector = register_property_and_inspector(api)
    first = open_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_INITIAL,
        scheduled_start_at="2026-08-01T09:00:00Z",
        scheduled_end_at="2026-08-01T11:00:00Z",
    )
    sign_empty_graph(api, first["id"], inspector["id"])
    second = open_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_INITIAL,
        scheduled_start_at="2026-08-01T11:00:00Z",
        scheduled_end_at="2026-08-01T13:00:00Z",
    )
    third = open_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_REAL_ESTATE,
        closing_date="2026-09-20",
        scheduled_start_at="2026-08-01T13:00:00Z",
        scheduled_end_at="2026-08-01T15:00:00Z",
    )
    fourth = open_graph(
        api,
        prop["id"],
        inspector["id"],
        purpose=PURPOSE_RENEWAL,
        supersedes_inspection_id=first["id"],
        scheduled_start_at="2026-08-01T15:00:00Z",
        scheduled_end_at="2026-08-01T17:00:00Z",
    )
    return prop, inspector, first, second, third, fourth


class TestLogicalClock:
    """The clock read is header-exempt; the setter is officer-exclusive."""

    def test_cold_clock_reads_the_declared_startup_instant(self, api):
        """A server that has never been told the time still knows it.

        PRD 2.5: "The clock's mandatory startup value is exactly
        `2026-08-01T00:00:00Z`: before any client moves it, every read of the
        clock returns that instant, and the server must never fall back to real
        wall-clock time."

        Design: Corner/endpoints/logical_clock_starts_at_the_declared_instant_and_moves_only_via_the_setter
        """
        data = validate_success(api.get_clock(MANAGER_HEADERS))
        assert_instant_equals(data["current_utc"], CLOCK_STARTUP_INSTANT)

    def test_branch_manager_may_not_move_the_logical_clock(self, api):
        """The clock is not a shared utility: only compliance may set it.

        PRD 2.5: "A `ComplianceOfficer` may set the clock to any UTC instant by
        supplying `current_utc`" — and PRD 2.6 stage 2 refuses a role the target
        operation does not admit with "`ERR_UNAUTHORIZED` (403)".

        Design: Corner/endpoints/logical_clock_starts_at_the_declared_instant_and_moves_only_via_the_setter
        """
        response = api.set_clock(
            clock_payload("2027-03-04T05:06:07Z"), MANAGER_HEADERS
        )
        validate_error(response, ERR_UNAUTHORIZED)
        after = validate_success(api.get_clock(MANAGER_HEADERS))
        assert_instant_equals(after["current_utc"], CLOCK_STARTUP_INSTANT)

    def test_officer_set_instant_is_visible_to_every_other_role(self, api):
        """One clock serves the whole system, whoever reads it.

        PRD 2.5: "any caller may read the clock's present value without
        supplying authentication headers at all — the clock read is the single
        endpoint exempt from the header requirement."

        Design: Corner/endpoints/logical_clock_starts_at_the_declared_instant_and_moves_only_via_the_setter
        """
        set_clock(api, "2027-03-04T05:06:07Z")
        data = validate_success(api.get_clock(make_property_owner_headers("owner-1")))
        assert_instant_equals(data["current_utc"], "2027-03-04T05:06:07Z")

    def test_row_stamping_reads_the_logical_clock_not_real_time(self, api):
        """A row created after the clock moved carries the moved instant.

        PRD 2.5: "Every instant the server stamps comes from this clock:
        `created_at` and `updated_at`, the `graph_completed_at` of a signed
        graph, the `requested_at` and `issued_at` of a statutory report ..."

        Design: Corner/endpoints/logical_clock_starts_at_the_declared_instant_and_moves_only_via_the_setter
        """
        set_clock(api, "2027-03-04T05:06:07Z")
        created = validate_success(
            api.create_property(
                property_payload(address_line1="411 Cypress Row"), OFFICER_HEADERS
            ),
            201,
        )
        assert_instant_equals(created["created_at"], "2027-03-04T05:06:07Z")


class TestGraphListingFilters:
    """Six equality filters that AND together, over a filtered total_count."""

    def test_property_page_reports_the_filtered_total_and_has_more(self, api):
        """A page of two out of four rows reports the pre-paging total.

        PRD 2.3: "Both values are echoed back in `meta` alongside `total_count`,
        the number of rows matching the request before paging, and `has_more`,
        which is true exactly when rows remain beyond the current page."

        Design: Corner/endpoints/inspection_filters_compose_with_pagination_over_one_property
        """
        prop, _, _, _, _, _ = _four_graphs_on_one_property(api)
        response = api.list_inspections(
            OFFICER_HEADERS, property_id=prop["id"], limit=2, offset=0
        )
        rows, meta = assert_page(
            response, 4, expected_rows=2, expected_has_more=True
        )
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        for row in rows:
            for field in ("id", "created_at", "updated_at", "version"):
                assert field in row, "a graph row must expose %s" % field

    def test_property_purpose_and_status_filters_and_together(self, api):
        """Three filters narrow four graphs to the single unsigned INITIAL one.

        PRD 2.3: "Filters narrow a collection before paging is applied, and
        every filter is an exact-match equality test. ... Graphs may be filtered
        by `property_id`, by `inspector_id`, by `supersedes_inspection_id`, by
        `status` and by `purpose`."

        Design: Corner/endpoints/inspection_filters_compose_with_pagination_over_one_property
        """
        prop, _, _, second, _, _ = _four_graphs_on_one_property(api)
        response = api.list_inspections(
            OFFICER_HEADERS,
            property_id=prop["id"],
            purpose=PURPOSE_INITIAL,
            status=INSPECTION_DRAFT,
            limit=10,
            offset=0,
        )
        rows, meta = assert_page(response, 1, expected_rows=1, expected_has_more=False)
        assert rows[0]["id"] == second["id"]
        assert rows[0]["purpose"] == PURPOSE_INITIAL
        assert_status(rows[0], INSPECTION_DRAFT, "inspection")

    def test_supersedes_inspection_id_is_a_query_dimension(self, api):
        """The self-referential replacement key is filterable in its own right.

        PRD 2.3: "Graphs may be filtered by `property_id`, by `inspector_id`, by
        `supersedes_inspection_id`, by `status` and by `purpose`."

        Design: Corner/endpoints/inspection_filters_compose_with_pagination_over_one_property
        """
        _, _, first, _, _, fourth = _four_graphs_on_one_property(api)
        response = api.list_inspections(
            OFFICER_HEADERS,
            supersedes_inspection_id=first["id"],
            limit=10,
            offset=0,
        )
        rows, _ = assert_page(response, 1, expected_rows=1)
        assert rows[0]["id"] == fourth["id"]
        assert rows[0]["purpose"] == PURPOSE_RENEWAL

    def test_superseded_status_filter_finds_the_retired_graph(self, api):
        """Opening the replacement retired the graph it named, on the spot.

        PRD 3.3: "Supplying `supersedes_inspection_id` retires the prior graph
        immediately ... The first hop moves the named graph to `SUPERSEDED`,
        whether it was `GRAPHED` or still `DRAFT`."

        Design: Corner/endpoints/inspection_filters_compose_with_pagination_over_one_property
        """
        _, inspector, first, _, _, _ = _four_graphs_on_one_property(api)
        response = api.list_inspections(
            OFFICER_HEADERS,
            inspector_id=inspector["id"],
            status=INSPECTION_SUPERSEDED,
            limit=10,
            offset=0,
        )
        rows, _ = assert_page(response, 1, expected_rows=1)
        assert rows[0]["id"] == first["id"]
        assert_status(rows[0], INSPECTION_SUPERSEDED, "inspection")


class TestInspectorRegistryMutationChannel:
    """The licence-status action is the registry's only mutation channel."""

    def test_suspension_changes_status_only(self, api):
        """A suspension moves status and version and touches nothing else.

        PRD 3.2: "`ACTIVE → SUSPENDED` requires the licence to be `ACTIVE` and
        simply sets it `SUSPENDED`. ... All four moves set the new `status` and
        raise the record's `version` by one."

        Design: Corner/endpoints/inspector_registry_fields_change_only_through_the_licence_status_channel
        """
        inspector = register_inspector(api, ce_credits=3)
        suspended = validate_success(
            api.set_license_status(
                inspector["id"],
                license_status_payload(LICENSE_STATUS_SUSPENDED),
                OFFICER_HEADERS,
            )
        )
        assert_status(suspended, LICENSE_STATUS_SUSPENDED, "inspector")
        assert_version(suspended, 2, "inspector")
        for field in (
            "full_name",
            "license_number",
            "license_state",
            "license_categories",
        ):
            assert suspended[field] == inspector[field], (
                "%s must survive a licence-status change" % field
            )

    def test_lifting_a_suspension_ignores_supplied_credits_and_expiry(self, api):
        """The suspension-lift hop declares no expiry or credit side effects.

        PRD 3.2: "`SUSPENDED → ACTIVE` requires the licence to be `SUSPENDED`
        **and** its existing `license_expires_on` to fall on or after the logical
        clock's UTC date — a suspension cannot be lifted on a credential that has
        meanwhile run out."

        Design: Corner/endpoints/inspector_registry_fields_change_only_through_the_licence_status_channel
        """
        inspector = register_inspector(api, ce_credits=3)
        validate_success(
            api.set_license_status(
                inspector["id"],
                license_status_payload(LICENSE_STATUS_SUSPENDED),
                OFFICER_HEADERS,
            )
        )
        lifted = validate_success(
            api.set_license_status(
                inspector["id"],
                license_status_payload(
                    LICENSE_STATUS_ACTIVE,
                    ce_credits=40,
                    license_expires_on="2031-01-01",
                ),
                OFFICER_HEADERS,
            )
        )
        assert_status(lifted, LICENSE_STATUS_ACTIVE, "inspector")
        assert lifted["ce_credits"] == 3, (
            "the suspension-lift hop applies no continuing-education balance"
        )
        assert lifted["license_expires_on"] == inspector["license_expires_on"], (
            "the suspension-lift hop applies no new expiry date"
        )
        assert_version(lifted, 3, "inspector")

    def test_reinstatement_applies_the_supplied_credits_and_expiry(self, api):
        """The expired-to-active hop is the one that writes the two fields.

        PRD 3.2: "On a successful reinstatement the record's
        `license_expires_on` becomes the supplied date and its `ce_credits`
        becomes the supplied balance when one was supplied, remaining unchanged
        otherwise."

        Design: Corner/endpoints/inspector_registry_fields_change_only_through_the_licence_status_channel
        """
        inspector = register_inspector(api, ce_credits=3)
        validate_success(
            api.set_license_status(
                inspector["id"],
                license_status_payload(LICENSE_STATUS_EXPIRED),
                OFFICER_HEADERS,
            )
        )
        reinstated = validate_success(
            api.set_license_status(
                inspector["id"],
                license_status_payload(
                    LICENSE_STATUS_ACTIVE,
                    license_expires_on="2032-06-30",
                    ce_credits=8,
                ),
                OFFICER_HEADERS,
            )
        )
        assert_status(reinstated, LICENSE_STATUS_ACTIVE, "inspector")
        assert reinstated["license_expires_on"] == "2032-06-30"
        assert reinstated["ce_credits"] == 8
        assert_version(reinstated, 3, "inspector")

    def test_four_accepted_hops_raise_the_version_exactly_four_times(self, api):
        """One increment per accepted hop, with the licence number untouched.

        PRD 2.4: "`version`, an integer that starts at 1 when the row is created
        and increases by exactly 1 on every mutation of that row."

        Design: Corner/endpoints/inspector_registry_fields_change_only_through_the_licence_status_channel
        """
        inspector = register_inspector(api, ce_credits=3)
        hops = (
            license_status_payload(LICENSE_STATUS_SUSPENDED),
            license_status_payload(
                LICENSE_STATUS_ACTIVE, ce_credits=40, license_expires_on="2031-01-01"
            ),
            license_status_payload(LICENSE_STATUS_EXPIRED),
            license_status_payload(
                LICENSE_STATUS_ACTIVE, license_expires_on="2032-06-30", ce_credits=8
            ),
        )
        for index, payload in enumerate(hops):
            data = validate_success(
                api.set_license_status(inspector["id"], payload, OFFICER_HEADERS)
            )
            assert_version(data, index + 2, "inspector")
        final = validate_success(api.get_inspector(inspector["id"], MANAGER_HEADERS))
        assert_version(final, 5, "inspector")
        assert final["license_number"] == inspector["license_number"], (
            "no declared operation can rewrite a licence number"
        )


class TestBondIssuanceWindows:
    """Every coverage-calendar date is derived once, from the issuance clock."""

    def test_issuance_freezes_all_four_calendar_dates(self, api):
        """A bond issued on 2026-09-01 lands its whole calendar in one step.

        PRD 3.7: "`issued_on` and `current_term_start` are both the logical
        clock's UTC date at issuance. `current_term_end` is 365 days after
        `current_term_start` and is the inclusive last date of the term.
        `renewal_window_opens_on` is 60 days before `current_term_end`."

        Design: Corner/endpoints/bond_issuance_freezes_every_term_window_at_the_issuance_date
        """
        chain = bonded_property(api, issue_instant=BOND_ISSUE_INSTANT)
        bond = chain["bond"]
        assert bond["issued_on"] == "2026-09-01"
        assert bond["current_term_start"] == "2026-09-01"
        assert bond["current_term_end"] == "2027-09-01"
        assert bond["renewal_window_opens_on"] == "2027-07-03"

    def test_issuance_starts_the_counters_and_watch_flags_at_rest(self, api):
        """Nothing about a fresh bond is yet in flight.

        PRD 3.7: "`lapse_date` starts null, `reinstatement_count` starts at 0,
        and the three watch flags — `retreat_required`, `coverage_watch` and the
        counter `retreat_credit_count` — start false, false and 0 respectively."

        Design: Corner/endpoints/bond_issuance_freezes_every_term_window_at_the_issuance_date
        """
        chain = bonded_property(api, issue_instant=BOND_ISSUE_INSTANT)
        bond = chain["bond"]
        assert_status(bond, BOND_ACTIVE, "bond")
        assert bond["term_index"] == 1
        assert bond["reinstatement_count"] == 0
        assert bond["lapse_date"] is None
        assert bond["issued_by_user_id"] == BRANCH_MANAGER_ID
        assert bond["conducive_waiver_codes"] == []
        assert bond["coverage_watch"] is False
        assert bond["retreat_required"] is False
        assert bond["retreat_credit_count"] == 0

    def test_premature_term_review_cannot_manufacture_a_lapse(self, api):
        """Two weeks into a term, neither review transition is available.

        PRD 3.8: "A review that finds neither deadline passed changes nothing and
        is refused with `ERR_INVALID_BOND_STATE`."

        Design: Corner/endpoints/bond_issuance_freezes_every_term_window_at_the_issuance_date
        """
        chain = bonded_property(api, issue_instant=BOND_ISSUE_INSTANT)
        bond = chain["bond"]
        set_clock(api, "2026-09-15T00:00:00Z")
        validate_error(
            api.term_review(bond["id"], {}, OFFICER_HEADERS), ERR_INVALID_BOND_STATE
        )

    def test_a_refused_review_leaves_the_bond_byte_for_byte_intact(self, api):
        """The refused sweep is a no-op: no window moves and no version rises.

        PRD 3.8: "A review that finds neither deadline passed changes nothing and
        is refused with `ERR_INVALID_BOND_STATE`."

        Design: Corner/endpoints/bond_issuance_freezes_every_term_window_at_the_issuance_date
        """
        chain = bonded_property(api, issue_instant=BOND_ISSUE_INSTANT)
        bond = chain["bond"]
        set_clock(api, "2026-09-15T00:00:00Z")
        validate_error(
            api.term_review(bond["id"], {}, OFFICER_HEADERS), ERR_INVALID_BOND_STATE
        )
        after = validate_success(api.get_bond(bond["id"], OFFICER_HEADERS))
        for field in (
            "issued_on",
            "current_term_start",
            "current_term_end",
            "renewal_window_opens_on",
            "term_index",
        ):
            assert after[field] == bond[field], (
                "a refused review must not move %s" % field
            )
        assert after["lapse_date"] is None
        assert_version(after, bond["version"], "bond")


class TestRenewalCreation:
    """The window bound is an inclusive date test and pricing is provisional."""

    def test_renewal_refused_on_the_last_instant_before_the_window_opens(self, api):
        """23:59:59 on 2027-07-02 is still outside a window opening 2027-07-03.

        PRD 3.8: "the clock's UTC date must be on or after
        `renewal_window_opens_on` — that is, no earlier than 60 days before
        `current_term_end` ... Outside the window the attempt is
        `ERR_RENEWAL_WINDOW_NOT_OPEN`."

        Design: Corner/endpoints/renewal_creation_opens_exactly_on_the_window_date_and_prices_provisionally
        """
        chain = bonded_property(api, issue_instant=BOND_ISSUE_INSTANT)
        set_clock(api, "2027-07-02T23:59:59Z")
        validate_error(
            api.create_renewal(chain["bond"]["id"], {}, MANAGER_HEADERS),
            ERR_RENEWAL_WINDOW_NOT_OPEN,
        )

    def test_renewal_opens_exactly_on_the_window_date(self, api):
        """Midnight on the opening date is inside the window, not outside it.

        PRD 3.8: "Opening an invoice creates a renewal row in status `PENDING`
        that snapshots the bond's `term_index` — the term this invoice closes out
        — and sets `due_on` to the bond's `current_term_end`."

        Design: Corner/endpoints/renewal_creation_opens_exactly_on_the_window_date_and_prices_provisionally
        """
        chain = bonded_property(api, issue_instant=BOND_ISSUE_INSTANT)
        set_clock(api, "2027-07-03T00:00:00Z")
        invoice = validate_success(
            api.create_renewal(chain["bond"]["id"], {}, MANAGER_HEADERS), 201
        )
        assert_status(invoice, RENEWAL_PENDING, "renewal")
        assert invoice["term_index"] == 1
        assert invoice["due_on"] == "2027-09-01"
        assert invoice["inspection_id"] is None
        assert invoice["paid_at"] is None
        # The creation-time value of `amount_paid_usd` is not asserted: PRD 3.8
        # names the field only as one that completion "records ... as the amount
        # tendered" and never states what a PENDING invoice carries, so null and
        # 0.00 are both faithful readings (PRD 3.10 starts a claim's money
        # fields at 0.00). Split per the partial-coverage rule.

    def test_provisional_pricing_forces_the_last_two_components_to_zero(self, api):
        """Only the two determinable components carry money at creation.

        PRD 3.8: "At creation `conducive_surcharge_usd` and `late_fee_usd` are
        both forced to 0.00, because no renewal graph has been attached yet and
        nothing is past due yet. `invoice_total_usd` is the exact sum of the four
        already-rounded components."

        Design: Corner/endpoints/renewal_creation_opens_exactly_on_the_window_date_and_prices_provisionally
        """
        chain = bonded_property(api, issue_instant=BOND_ISSUE_INSTANT)
        assert_money(chain["bond"]["annual_premium_usd"], 241.06)
        set_clock(api, "2027-07-03T00:00:00Z")
        invoice = validate_success(
            api.create_renewal(chain["bond"]["id"], {}, MANAGER_HEADERS), 201
        )
        assert_renewal_invoice(
            invoice,
            base_renewal_fee_usd=83.17,
            inspection_fee_usd=128.10,
            conducive_surcharge_usd=0.00,
            late_fee_usd=0.00,
            invoice_total_usd=211.27,
        )

    def test_a_second_invoice_is_refused_while_one_is_pending(self, api):
        """The open invoice must be settled before another may be raised.

        PRD 3.8: "Only one invoice may be open at a time: a bond with an existing
        renewal in status `PENDING` refuses a second with
        `ERR_RENEWAL_ALREADY_PENDING`."

        Design: Corner/endpoints/renewal_creation_opens_exactly_on_the_window_date_and_prices_provisionally
        """
        chain = bonded_property(api, issue_instant=BOND_ISSUE_INSTANT)
        set_clock(api, "2027-07-03T00:00:00Z")
        validate_success(
            api.create_renewal(chain["bond"]["id"], {}, MANAGER_HEADERS), 201
        )
        validate_error(
            api.create_renewal(chain["bond"]["id"], {}, MANAGER_HEADERS),
            ERR_RENEWAL_ALREADY_PENDING,
        )

    def test_the_pending_invoice_is_readable_by_the_bonded_homeowner(self, api):
        """The homeowner who will pay the invoice may list it.

        PRD 2.3: "The renewal invoices of one bond may be filtered by `status`"
        — and the endpoint table admits ComplianceOfficer, BranchManager and
        PropertyOwner on `GET /bonds/{id}/renewals`.

        Design: Corner/endpoints/renewal_creation_opens_exactly_on_the_window_date_and_prices_provisionally
        """
        chain = bonded_property(api, issue_instant=BOND_ISSUE_INSTANT)
        set_clock(api, "2027-07-03T00:00:00Z")
        invoice = validate_success(
            api.create_renewal(chain["bond"]["id"], {}, MANAGER_HEADERS), 201
        )
        response = api.list_bond_renewals(
            chain["bond"]["id"],
            make_property_owner_headers(chain["property"]["id"]),
            status=RENEWAL_PENDING,
            limit=10,
            offset=0,
        )
        rows, _ = assert_page(response, 1, expected_rows=1, expected_has_more=False)
        assert rows[0]["id"] == invoice["id"]


def _approved_liquid_plan(api):
    """A structure, a signed INITIAL graph and an APPROVED liquid plan on it."""
    prop, inspector = register_property_and_inspector(api)
    graph = graphed_inspection(api, prop["id"], inspector["id"])
    plan = approved_plan(api, prop["id"], graph["id"], inspector["id"])
    return prop, inspector, graph, plan


class TestApplicationsAccumulateGallons:
    """The volume target is a floor, and each discharge bumps the plan version."""

    def test_the_first_discharge_accumulates_and_leaves_the_plan_approved(self, api):
        """95 of 190 gallons moves the running total but not the status.

        PRD 3.6: "The plan's `gallons_applied_total` — the running sum of
        `gallons_applied` over the plan's records — is increased by the gallons
        just discharged, and the plan's `version` rises by one."

        Design: Corner/endpoints/applications_accumulate_gallons_until_the_plan_may_be_completed
        """
        _, inspector, _, plan = _approved_liquid_plan(api)
        assert_money(plan["target_gallons"], 190.00)
        validate_success(
            api.create_application(
                plan["id"],
                application_payload(plan["version"], gallons_applied=95.00),
                make_applicator_headers(inspector["id"]),
            ),
            201,
        )
        after = validate_success(api.get_treatment_plan(plan["id"], MANAGER_HEADERS))
        assert_money(after["gallons_applied_total"], 95.00)
        assert_status(after, PLAN_APPROVED, "treatment plan")

    def test_completion_below_the_volume_target_is_refused(self, api):
        """Half the trench gallons is not a closeable liquid plan.

        PRD 3.6: "A `LIQUID_BARRIER` plan may only be completed once
        `gallons_applied_total` has reached at least `target_gallons` — the volume
        target is a floor, and exceeding it is fine."

        Design: Corner/endpoints/applications_accumulate_gallons_until_the_plan_may_be_completed
        """
        _, inspector, _, plan = _approved_liquid_plan(api)
        validate_success(
            api.create_application(
                plan["id"],
                application_payload(plan["version"], gallons_applied=95.00),
                make_applicator_headers(inspector["id"]),
            ),
            201,
        )
        validate_error(
            api.complete_treatment_plan(
                plan["id"], {}, make_applicator_headers(inspector["id"])
            ),
            ERR_INVALID_PLAN_STATE,
        )

    def test_a_second_discharge_needs_the_refreshed_plan_version(self, api):
        """The stale expectation is refused; the refreshed one is accepted.

        PRD 2.7: "If that value does not equal the plan's current `version`, the
        application is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/applications_accumulate_gallons_until_the_plan_may_be_completed
        """
        _, inspector, _, plan = _approved_liquid_plan(api)
        stale_version = plan["version"]
        validate_success(
            api.create_application(
                plan["id"],
                application_payload(stale_version, gallons_applied=95.00),
                make_applicator_headers(inspector["id"]),
            ),
            201,
        )
        validate_error(
            api.create_application(
                plan["id"],
                application_payload(stale_version, gallons_applied=95.00),
                make_applicator_headers(inspector["id"]),
            ),
            ERR_STALE_VERSION,
        )
        refreshed = validate_success(
            api.get_treatment_plan(plan["id"], MANAGER_HEADERS)
        )
        assert refreshed["version"] != stale_version
        validate_success(
            api.create_application(
                plan["id"],
                application_payload(refreshed["version"], gallons_applied=95.00),
                make_applicator_headers(inspector["id"]),
            ),
            201,
        )

    def test_reaching_the_target_exactly_unlocks_completion(self, api):
        """Two 95-gallon visits reach 190.00 and the plan closes out.

        PRD 3.6: "Completion stamps `completed_at` with the clock instant, and
        for a `BAIT_STATION` plan it also installs the hardware."

        Design: Corner/endpoints/applications_accumulate_gallons_until_the_plan_may_be_completed
        """
        _, inspector, _, plan = _approved_liquid_plan(api)
        version = plan["version"]
        for _ in range(2):
            validate_success(
                api.create_application(
                    plan["id"],
                    application_payload(version, gallons_applied=95.00),
                    make_applicator_headers(inspector["id"]),
                ),
                201,
            )
            version += 1
        completed = validate_success(
            api.complete_treatment_plan(
                plan["id"], {}, make_applicator_headers(inspector["id"])
            )
        )
        assert_status(completed, PLAN_COMPLETED, "treatment plan")
        assert_money(completed["gallons_applied_total"], 190.00)
        assert_instant_equals(completed["completed_at"], CLOCK_STARTUP_INSTANT)

    def test_the_pesticide_records_carry_a_retention_date_and_no_version(self, api):
        """Two immutable Florida records, each retained for four 365-day years.

        PRD 2.10: "Alabama, Georgia and Texas each require 2 years of retention,
        California requires 3, and Florida requires 4; the retention deadline is
        always computed as that year count multiplied by 365 days added to the
        date on which the chemical was applied."

        Design: Corner/endpoints/applications_accumulate_gallons_until_the_plan_may_be_completed
        """
        _, inspector, _, plan = _approved_liquid_plan(api)
        version = plan["version"]
        for _ in range(2):
            validate_success(
                api.create_application(
                    plan["id"],
                    application_payload(version, gallons_applied=95.00),
                    make_applicator_headers(inspector["id"]),
                ),
                201,
            )
            version += 1
        response = api.list_applications(plan["id"], OFFICER_HEADERS, limit=10, offset=0)
        rows, _ = assert_page(response, 2, expected_rows=2, expected_has_more=False)
        for row in rows:
            assert row["retention_until"] == "2030-07-31"
            assert "version" not in row, "a pesticide record carries no version"
            assert "updated_at" not in row, "a pesticide record carries no updated_at"

    def test_a_liquid_plan_installs_no_bait_stations_on_completion(self, api):
        """The station target is zero for every method but BAIT_STATION.

        PRD 3.5: "The station target, `target_station_count`, is the number of
        bait stations to install and is 0 for any method other than
        `BAIT_STATION`."

        Design: Corner/endpoints/applications_accumulate_gallons_until_the_plan_may_be_completed
        """
        _, inspector, _, plan = _approved_liquid_plan(api)
        assert plan["target_station_count"] == 0
        version = plan["version"]
        for _ in range(2):
            validate_success(
                api.create_application(
                    plan["id"],
                    application_payload(version, gallons_applied=95.00),
                    make_applicator_headers(inspector["id"]),
                ),
                201,
            )
            version += 1
        validate_success(
            api.complete_treatment_plan(
                plan["id"], {}, make_applicator_headers(inspector["id"])
            )
        )
        response = api.list_bait_stations(
            plan["id"], OFFICER_HEADERS, limit=10, offset=0
        )
        assert_page(response, 0, expected_rows=0, expected_has_more=False)
