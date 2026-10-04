"""Program setup: organizations, competitions, applications, member registration.

Covers creation-time declared/system fields, computed application figures, and
list pagination over applications (PRD §2.3, §2.5, §3.1, §3.2, §3.4).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_application,
    assert_award,
    assert_competition,
    assert_member,
    assert_organization,
    assert_slot,
    create_competition_payload,
    create_draft_application,
    create_org,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_grantee_staff_headers,
    match_line,
    register_member,
    register_member_payload,
    set_clock,
    setup_awarded_program,
    setup_org_competition,
    slot_request,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOrganizationCreation:
    def test_organization_created_active_with_system_fields(self, api, officer_headers):
        """A new organization starts ACTIVE at version 1 with system-minted
        id/created_at/updated_at inside the standard object envelope.

        PRD §3.1: "A new organization starts `ACTIVE`."
        PRD §2.5: "`version` (integer): a system-managed integer starting at 1 that increments on every mutation."

        Design: Corner/entities/organization_create_returns_declared_fields_and_starts_active
        """
        set_clock()
        resp = api.create_organization(
            {
                "legal_name": "River City Service Corps",
                "ein": "12-3456789",
                "org_type": "NONPROFIT",
            },
            officer_headers,
        )
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        org = validate_success(resp, 201)
        assert_organization(org)
        assert org["status"] == "ACTIVE"
        assert org["version"] == 1
        assert is_valid_uuid(org["id"])
        assert is_iso8601_timestamp(org["created_at"])
        assert is_iso8601_timestamp(org["updated_at"])

    def test_competition_created_open_and_window_round_trips(self, api, officer_headers):
        """A competition is born OPEN and the application window is stored.

        PRD §3.1: "A competition is born `OPEN`, and submissions are accepted at or after `application_open_at` and at or before `application_close_at` — both bounds inclusive."

        Design: Corner/entities/competition_create_starts_open_and_window_is_stored
        """
        set_clock()
        resp = api.create_competition(create_competition_payload(), officer_headers)
        comp = validate_success(resp, 201)
        assert_competition(comp)
        assert comp["status"] == "OPEN"
        assert comp["application_open_at"].startswith("2026-09-01T00:00:00")
        assert comp["application_close_at"].startswith("2026-10-01T00:00:00")
        assert comp["fiscal_year"] == 2026


class TestApplicationCreation:
    def test_missing_slot_requests_is_invalid_request(self, api, officer_headers):
        """Omitting the required slot_requests array is a request-shape 400.

        PRD §3.2: "a `slot_requests` array describing the positions sought — each entry pairing a `term_category` from the term table with a `count` of at least 1"
        PRD §2.10: "request shape (`ERR_INVALID_REQUEST` — missing required fields, unknown enum values, range violations)"

        Design: Corner/entities/application_create_missing_slot_requests_returns_invalid_request
        """
        base = setup_org_competition()
        staff = make_grantee_staff_headers(base["org_id"])
        resp = api.create_application(
            base["comp_id"],
            {
                "organization_id": base["org_id"],
                "federal_share_requested_cents": 4000000,
                "match_lines": [match_line("CASH", 1000000)],
            },
            staff,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(
            api.list_applications(officer_headers, params={"organization_id": base["org_id"]})
        )
        assert rows == [] and meta["total_count"] == 0

    def test_create_computes_msy_and_cost_fields(self, api, officer_headers):
        """A DRAFT application for 2 FULL_TIME slots derives total_term_minutes
        204000, msy_requested 2.0, allowable match 1000000 (CASH at full value).

        PRD §3.2: "Creation computes and stores five derived figures."
        PRD §3.2: "The `total_term_minutes` aggregates the slot requests against the term table, and `msy_requested` expresses that total in member-service years to 3 decimal places."
        PRD §3.2: "Both fields remain null until their respective events set them."

        Design: Corner/entities/application_create_computes_msy_and_cost_fields
        """
        base = setup_org_competition()
        resp = api.create_application(
            base["comp_id"],
            {
                "organization_id": base["org_id"],
                "federal_share_requested_cents": 4000000,
                "slot_requests": [slot_request("FULL_TIME", 2)],
                "match_lines": [match_line("CASH", 1000000)],
            },
            make_grantee_staff_headers(base["org_id"]),
        )
        app = validate_success(resp, 201)
        assert_application(app)
        assert app["status"] == "DRAFT"
        assert app["version"] == 1
        assert app["total_term_minutes"] == 204000
        assert app["msy_requested"] == pytest.approx(2.0, abs=0.0005)
        assert app["allowable_match_commitment_cents"] == 1000000
        assert app["cost_per_msy_federal_cents"] == pytest.approx(2000000.0, abs=0.005)
        assert app["clarification_question"] is None
        assert app["clarification_response"] is None

    def test_applications_list_paginates_and_filters(self, api, officer_headers):
        """limit/offset page the collection and the status filter narrows it;
        meta always carries the four pagination fields.

        PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response always carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/applications_list_paginates_and_filters
        """
        base = setup_org_competition()
        create_draft_application(base["comp_id"], base["org_id"])
        create_draft_application(
            base["comp_id"],
            base["org_id"],
            federal_share_requested_cents=2300000,
            slot_requests=[slot_request("FULL_TIME", 1)],
            match_lines=[match_line("CASH", 560000)],
        )
        create_draft_application(
            base["comp_id"],
            base["org_id"],
            federal_share_requested_cents=1150000,
            slot_requests=[slot_request("HALF_TIME", 1)],
            match_lines=[match_line("CASH", 276000)],
        )
        page1, meta1 = validate_paginated(
            api.list_applications(
                officer_headers,
                params={"organization_id": base["org_id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3 and meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_applications(
                officer_headers,
                params={"organization_id": base["org_id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3 and meta2["has_more"] is False
        drafts, meta3 = validate_paginated(
            api.list_applications(officer_headers, params={"status": "DRAFT"})
        )
        assert len(drafts) == 3 and meta3["total_count"] == 3
        unfiltered, meta4 = validate_paginated(api.list_applications(officer_headers))
        assert len(unfiltered) == 3 and meta4["limit"] == 10


class TestAwardCreation:
    def test_award_round_trips_ledger_and_competition_finalizes(self, api, officer_headers):
        """Awarding the competition's only application mints the GrantAward
        ACTIVE at version 1 with computed cost-per-MSY and one OPEN slot per
        requested unit, and bubbles the competition to AWARDS_FINALIZED.

        PRD §3.2: "a new GrantAward is created `ACTIVE` at `version` 1, linked back through `application_id`, copying the application's `organization_id`, `competition_id`, and `total_term_minutes`, carrying the `federal_share_awarded_cents`, a freshly computed `cost_per_msy_awarded_cents` (half-up, 2 decimal places), and `allowable_match_cents` starting at 0"
        PRD §3.2: "one PositionSlot is minted per requested slot unit — `awarded_slot_count` in total, the sum of the `slot_requests` counts — numbered by `slot_index` from 1 upward in `slot_requests` array order, each `OPEN` with `fill_count` 0"
        PRD §3.1: "Its final transition, `CLOSED` → `AWARDS_FINALIZED`, is fired by the system itself the moment no application of that competition remains in `DRAFT`, `UNDER_REVIEW`, or `CLARIFICATION_REQUESTED` — that is, when every application has been awarded or rejected."

        Design: Corner/entities/award_get_returns_stored_ledger_and_competition_finalizes
        """
        program = setup_awarded_program()
        award = validate_success(
            api.get_award(program["award_id"], officer_headers), 200
        )
        assert_award(award)
        assert award["federal_share_awarded_cents"] == 4000000
        assert award["allowable_match_cents"] == 0
        assert award["awarded_slot_count"] == 2
        assert award["total_term_minutes"] == 204000
        assert award["cost_per_msy_awarded_cents"] == pytest.approx(2000000.0, abs=0.005)
        assert award["status"] == "ACTIVE"
        assert award["version"] == 1
        assert award["application_id"] == program["app_id"]
        comp = validate_success(api.get_competition(program["comp_id"], officer_headers))
        assert comp["status"] == "AWARDS_FINALIZED"
        slots, meta = validate_paginated(
            api.list_slots(program["award_id"], officer_headers)
        )
        assert meta["total_count"] == 2
        by_index = {s["slot_index"]: s for s in slots}
        assert sorted(by_index) == [1, 2]
        for slot in by_index.values():
            assert_slot(slot)
            assert slot["status"] == "OPEN"
            assert slot["term_category"] == "FULL_TIME"
            assert slot["fill_count"] == 0


class TestMemberRegistration:
    def test_register_ignores_client_supplied_status(self, api, officer_headers, anonymous_headers):
        """A smuggled status field cannot preempt the system-managed initial
        state: the member still starts ACTIVE with a zero release count.

        PRD §3.4: "A new member is `ACTIVE` with a `for_cause_release_count` of 0."

        Design: Corner/entities/member_register_client_status_input_ignored
        """
        set_clock()
        member = register_member_payload(status="DEBARRED")
        resp = api.register_member(member, anonymous_headers)
        created = validate_success(resp, 201)
        assert_member(created)
        assert created["status"] == "ACTIVE"
        assert created["for_cause_release_count"] == 0
        assert created["version"] == 1
        fetched = validate_success(api.get_member(created["id"], officer_headers))
        assert fetched["status"] == "ACTIVE"
