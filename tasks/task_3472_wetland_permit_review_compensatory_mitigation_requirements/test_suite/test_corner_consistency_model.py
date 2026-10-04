"""Corner queue — consistency model (PRD §2.2, §3.7).

Every issuance side effect is visible in the same request cycle: the
decision response itself shows ISSUED, and the immediately following reads
return the new permit, its five DUE reports, and the ACTIVE plan.
"""
from test_helpers import (
    FIRST_PERMIT_NUMBER,
    ReportStatus,
    get_permit_for_application,
    render_decision,
    setup_application_decision_pending,
    setup_secured_bank_credits_plan,
    validate_paginated,
    validate_success,
)


def test_corner_immediate_consistency_on_issue(api, reviewer_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.7: "An `ISSUE` outcome moves the application to `ISSUED` and
    creates the `Permit`."
    PRD §3.7: "Issuance also activates the mitigation: the application's
    `CREDITS_SECURED` plan transitions to `ACTIVE`, and when the application
    has such a plan, exactly five monitoring reports are generated for the
    new permit and plan — `period_index` running 1 through 5, each report's
    `due_date` set at the permit's `issue_date` plus 365 days times its
    period index, each opening in `DUE`."

    The render-decision response shows ISSUED; the very next GETs already
    return the permit (WP-0001), five DUE reports, and the ACTIVE plan — no
    eventual-consistency lag anywhere.

    Design: Corner/consistency_model/corner_immediate_consistency_on_issue
    """
    ctx = setup_application_decision_pending()
    ctx = setup_secured_bank_credits_plan(ctx)
    app, plan = ctx["app"], ctx["plan"]

    app = render_decision(app, "ISSUE")
    assert app["status"] == "ISSUED", "the decision response itself shows ISSUED"

    permit = get_permit_for_application(app, reviewer_headers)
    assert permit["permit_number"] == FIRST_PERMIT_NUMBER, (
        "the first issued permit is already readable as WP-0001"
    )

    data, meta = validate_paginated(
        api.list_monitoring_reports(
            reviewer_headers, params={"permit_id": permit["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 5
    assert data[0]["status"] == ReportStatus.DUE.value

    plan_after = validate_success(api.get_mitigation_plan(plan["id"], reviewer_headers))
    assert plan_after["status"] == "ACTIVE", (
        "the secured plan is ACTIVE in the same request cycle"
    )
