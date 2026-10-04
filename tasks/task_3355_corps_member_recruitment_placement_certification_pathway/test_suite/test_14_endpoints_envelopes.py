"""Read endpoints: the logical clock default, sub-resource lists, error envelopes."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    err,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.fixtures import (
    ADMIN,
    CERTIFICATION_OFFICER,
    PLACEMENT_COORDINATOR,
    get_certification_milestone,
    list_milestones,
    setup_member_scenario,
)


class TestClockDefault:
    def test_fresh_server_reports_the_fixed_startup_instant(self, api):
        """PRD §2.12: "Before any client sets it, the clock reads the fixed startup instant `2026-09-01T00:00:00Z`; it never falls back to the machine's real time, which is what makes deadline behaviour reproducible."

        A milestone due 2026-11-01 therefore reports exactly 61 days
        remaining on a freshly started server.

        Design: Corner/endpoints/clock_default_is_fixed_startup_instant
        """
        scenario = setup_member_scenario()
        milestones = {m["milestone_type"]: m for m in list_milestones(scenario["member_id"])}
        orientation_id = milestones["ORIENTATION"]["id"]

        data = get_certification_milestone(orientation_id)
        assert data["due_date"].startswith("2026-11-01")
        assert data["days_remaining"] == 61, (
            "measured from the fixed default 2026-09-01T00:00:00Z"
        )
        assert data["deadline_status"] == "ON_TRACK"


class TestSubResourceDiscovery:
    def test_school_list_and_member_list_are_both_discoverable(self, api):
        """PRD §2.11: "Paths that nest one resource under another are resolved left to right."
        PRD §3.3: "The new member's identifier is written back onto the application as `created_corps_member_id`, which is how a client finds the member an offer produced and is the field the member list can be filtered by."

        Design: Corner/endpoints/school_subresource_list_and_cascade_child_discovery
        """
        scenario = setup_member_scenario()
        district_id = scenario["district"]["id"]
        school_id = scenario["school"]["id"]
        app_id = scenario["application"]["id"]
        member_id = scenario["member_id"]

        response = api.list_district_schools(district_id, ADMIN)
        assert response.json()["response_type"] == "array"
        schools, _ = validate_paginated(response)
        assert schools[0]["id"] == school_id

        members_response = api.list_corps_members(
            PLACEMENT_COORDINATOR, {"application_id": app_id, "limit": 10, "offset": 0}
        )
        members, meta = validate_paginated(members_response)
        assert len(members) == 1
        assert members[0]["id"] == member_id
        assert meta["total_count"] == 1


class TestMilestoneListOrdering:
    def test_member_schedule_reads_in_the_canonical_type_order(self, api):
        """PRD §3.5: "Milestones synthesized by an acceptance are ordered by `milestone_type` in the fixed sequence `COURSEWORK`, `PRACTICUM`, `ORIENTATION`, `EXAM`, so that every member's schedule reads in the same canonical order"

        Design: Corner/endpoints/milestone_subresource_list_is_ordered
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]

        rows = list_milestones(member_id)
        assert [(m["milestone_type"], m["required_hours"]) for m in rows] == [
            ("COURSEWORK", 60),
            ("PRACTICUM", 120),
            ("ORIENTATION", 60),
            ("EXAM", 0),
        ]

        pathway_rows, _ = validate_paginated(
            api.list_pathway_milestones(scenario["pathway"]["id"], CERTIFICATION_OFFICER)
        )
        assert len(pathway_rows) == 4, (
            "the pathway sub-resource lists every milestone derived from it"
        )


class TestErrorEnvelopeShape:
    def test_failure_body_uses_the_fixed_error_envelope(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.10: "A CertificationMilestone that cannot be resolved is `ERR_MILESTONE_NOT_FOUND` (404), reported on the milestone read, start, complete and verify."

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        response = api.get_certification_milestone(NON_EXISTENT_UUID, CERTIFICATION_OFFICER)
        assert response.status_code == 404
        body = response.json()
        assert body["response_type"] == "error"

        error_data = validate_error(response, err(ApiErrorId.ERR_MILESTONE_NOT_FOUND), 404)
        assert set(error_data.keys()) == {"error_id", "message"}, (
            "data carries exactly error_id and message"
        )
        assert error_data["message"].strip()

        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
