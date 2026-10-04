"""Territories: reverse lookup, the three-territory cap, and assignment guards
(PRD §3.2, §4)."""
from test_helpers import (
    ApiErrorId,
    assign_territory,
    create_active_licensee,
    create_licensee,
    create_territory,
    get_territory,
    validate_error,
    validate_paginated,
)


class TestLicenseeTerritoryLookup:
    def test_licensee_reverse_territory_lookup(self, api, platform_admin_headers):
        """PRD §4: GET /api/licensees/{id}/territories — "List territories assigned to
        a licensee; query params `limit`, `offset`".
        PRD §3.2: "On success `assigned_licensee_id` is set and `assigned_at` is
        stamped."

        Design: Corner/endpoints/licensee_reverse_territory_lookup
        """
        licensee = create_active_licensee()
        territory = create_territory(region_code="T-SEA", population_tier="METRO")
        before, meta_before = validate_paginated(
            api.list_licensee_territories(licensee["id"], platform_admin_headers)
        )
        assert before == [] and meta_before["total_count"] == 0

        assign_territory(territory["id"], licensee["id"])

        after, meta_after = validate_paginated(
            api.list_licensee_territories(licensee["id"], platform_admin_headers)
        )
        assert meta_after["total_count"] == 1
        assert len(after) == 1
        assert after[0]["region_code"] == "T-SEA"
        assert after[0]["status"] == "ASSIGNED"
        assert after[0]["assigned_at"] is not None


class TestTerritoryAssignmentGuards:
    def test_fourth_territory_assignment_rejected(self, api, platform_admin_headers):
        """PRD §3.2: "must currently hold fewer than the `MAX_TERRITORIES_PER_LICENSEE`
        cap of 3 `ASSIGNED` territories — an assignment that would give the licensee a
        fourth is rejected with `ERR_MAX_TERRITORIES_EXCEEDED`"

        Design: Corner/errors/fourth_territory_assignment_rejected
        """
        licensee = create_active_licensee()
        t_sea = create_territory(region_code="T-SEA", population_tier="METRO")
        t_pdx = create_territory(region_code="T-PDX", population_tier="SUBURBAN")
        t_boi = create_territory(region_code="T-BOI", population_tier="RURAL")
        t_spo = create_territory(region_code="T-SPO", population_tier="RURAL")
        for t in (t_sea, t_pdx, t_boi):
            assign_territory(t["id"], licensee["id"])
        resp = api.transition_territory(
            t_spo["id"],
            {"to_state": "ASSIGNED", "licensee_id": licensee["id"]},
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MAX_TERRITORIES_EXCEEDED.value)
        assert get_territory(t_spo["id"])["status"] == "OPEN"

    def test_territory_assign_to_applicant_licensee_rejected(self, api, platform_admin_headers):
        """PRD §3.2: "Assignment is a transition with `to_state` `ASSIGNED` plus a
        `licensee_id`: the target licensee must be `ACTIVE` (otherwise
        `ERR_LICENSEE_NOT_ACTIVE`)"

        Design: Corner/errors/territory_assign_to_applicant_licensee_rejected
        """
        licensee = create_licensee()  # stays APPLICANT
        territory = create_territory(region_code="T-SEA", population_tier="METRO")
        resp = api.transition_territory(
            territory["id"],
            {"to_state": "ASSIGNED", "licensee_id": licensee["id"]},
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LICENSEE_NOT_ACTIVE.value)
        assert get_territory(territory["id"])["status"] == "OPEN"

    def test_territory_double_assign_rejected(self, api, platform_admin_headers):
        """PRD §3.2: "and the territory itself must be `OPEN` (otherwise
        `ERR_REGION_ALREADY_ASSIGNED`)."
        PRD §3.2: "`OPEN → ASSIGNED → OPEN` is a deliberate cycle: territories are
        re-assignable after revocation."

        Design: Corner/errors/territory_double_assign_rejected
        """
        summit = create_active_licensee()
        prairie = create_active_licensee(business_name="Prairie Furniture Co")
        territory = create_territory(region_code="T-SEA", population_tier="METRO")
        assign_territory(territory["id"], summit["id"])
        resp = api.transition_territory(
            territory["id"],
            {"to_state": "ASSIGNED", "licensee_id": prairie["id"]},
            platform_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REGION_ALREADY_ASSIGNED.value)
        assert get_territory(territory["id"])["assigned_licensee_id"] == summit["id"]
