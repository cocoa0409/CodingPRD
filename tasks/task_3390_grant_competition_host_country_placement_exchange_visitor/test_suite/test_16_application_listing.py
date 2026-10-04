"""Application listing: pagination and filters (PRD §2.3)."""
from test_helpers import (
    create_draft_application,
    register_applicant,
    setup_open_cycle,
    validate_paginated,
)


def test_applications_list_paginates_and_filters(api, program_officer_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned: it defaults to 10 when not provided, with a minimum of 1 and a
    maximum of 100. The `offset` parameter sets the number of items skipped
    and defaults to 0."
    PRD §2.3: "Two listings accept additional filters: the application
    listing accepts `cycle_id`, `country_program_id`, `applicant_id`, and
    `status`, and the report listing accepts `report_type`."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."

    Three DRAFT applications in one cycle: page 1 of size 2 has has_more
    true; the tail page has one row and has_more false; the status filter
    narrows rows and total_count.

    Design: Corner/endpoints/applications_list_paginates_and_filters
    """
    base = setup_open_cycle()
    cycle, program = base["cycle"], base["program"]
    for title in ("Alpha", "Beta", "Gamma"):
        applicant = register_applicant()
        create_draft_application(applicant, cycle, program, project_title=title)

    page1, meta1 = validate_paginated(
        api.list_applications(
            program_officer_headers,
            params={"cycle_id": cycle["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_applications(
            program_officer_headers,
            params={"cycle_id": cycle["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page2) == 1, "the tail page carries the remaining row"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    drafts, meta_d = validate_paginated(
        api.list_applications(program_officer_headers, params={"status": "DRAFT"})
    )
    assert len(drafts) == 3 and meta_d["total_count"] == 3

    awarded, meta_a = validate_paginated(
        api.list_applications(program_officer_headers, params={"status": "AWARDED"})
    )
    assert awarded == [] and meta_a["total_count"] == 0

    _, meta_default = validate_paginated(
        api.list_applications(program_officer_headers)
    )
    assert meta_default["limit"] == 10, "the default page size is 10"
    assert meta_default["offset"] == 0, "the default offset is 0"
