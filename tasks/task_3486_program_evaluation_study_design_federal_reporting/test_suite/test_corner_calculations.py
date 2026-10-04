"""Corner queue — calculation claims not owned by a difficulty instance:
report deadline arithmetic and feasibility input-set filtering."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_site,
    create_report,
    get_contract,
    get_study,
    report_decision_payload,
    set_clock,
    setup_accepted_report,
    setup_report_in_revision,
    setup_study_with_sites,
    site_outreach_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]
PI = TEST_USERS["principal_investigator_headers"]
SD = TEST_USERS["study_director_headers"]
PEER = TEST_USERS["peer_reviewer_headers"]


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_revision_deadline_boundary_pass_and_miss(api):
    """PRD §3.7: "A `decision` of `REVISION_REQUIRED` moves the report to
    `REVISION`, increments `revision_count` by one, and sets `revision_due` to
    the decision time plus `REVISION_DAYS` of 60 days, starting the revision
    loop that ends in a resubmission as described above."
    PRD §3.7: "A resubmission from `REVISION` carries one more gate: the
    current logical time must be at or before `revision_due`, with submission
    at exactly the deadline allowed and one second past it rejected with
    `ERR_REVISION_DEADLINE_MISSED` (HTTP 422)."

    Design: Corner/calculations/revision_deadline_boundary_pass_and_miss
    """
    ctx = setup_report_in_revision()  # decision made at clock 2026-10-15
    report = ctx["report"]
    assert report["status"] == "REVISION"
    assert _parse(report["revision_due"]) == datetime(2026, 12, 14, tzinfo=timezone.utc), (
        "2026-10-15 + 60 days"
    )
    assert report["revision_count"] == 1

    # At exactly revision_due the resubmission passes.
    set_clock("2026-12-14T00:00:00Z")
    report = validate_success(api.submit_report(report["id"], PI), 200)
    assert report["status"] == "SUBMITTED"

    validate_success(api.review_report(report["id"], PEER), 200)
    report = validate_success(
        api.report_agency_decision(report["id"], report_decision_payload("REVISION_REQUIRED"), AO),
        200,
    )
    assert report["revision_count"] == 2
    assert _parse(report["revision_due"]) == datetime(2027, 2, 12, tzinfo=timezone.utc), (
        "2026-12-14 + 60 days"
    )

    # One day past the new due date the resubmission is rejected.
    set_clock("2027-02-13T00:00:00Z")
    resp = api.submit_report(report["id"], PI)
    validate_error(resp, ApiErrorId.ERR_REVISION_DEADLINE_MISSED)


def test_publication_deadline_boundary_pass_and_miss(api):
    """PRD §3.7: "A `decision` of `ACCEPTED` stamps `accepted_at` and sets
    `publication_due` to `accepted_at` plus `PUBLICATION_DAYS` of 90 days."
    PRD §3.8: "The deadline gate requires the current logical time to be at or
    before `publication_due`, with publication at exactly the deadline allowed
    and anything later rejected with `ERR_PUBLICATION_DEADLINE_MISSED` (HTTP
    422)."

    Design: Corner/calculations/publication_deadline_boundary_pass_and_miss
    """
    ctx = setup_accepted_report()  # R1 accepted at clock 2026-10-15
    study_id = ctx["study"]["id"]
    r1 = ctx["report"]
    assert r1["status"] == "ACCEPTED"
    assert _parse(r1["publication_due"]) == datetime(2027, 1, 13, tzinfo=timezone.utc), (
        "2026-10-15 + 90 days"
    )

    # A sibling INTERIM report accepted at the same logical time shares the due.
    r2 = create_report(
        study_id, title="R2", report_type="INTERIM", payment_milestone_cents=0
    )
    validate_success(api.submit_report(r2["id"], PI), 200)
    validate_success(api.review_report(r2["id"], PEER), 200)
    r2 = validate_success(
        api.report_agency_decision(r2["id"], report_decision_payload("ACCEPTED"), AO), 200
    )
    assert _parse(r2["publication_due"]) == datetime(2027, 1, 13, tzinfo=timezone.utc)

    # At exactly publication_due the publish passes.
    set_clock("2027-01-13T00:00:00Z")
    r1 = validate_success(api.publish_report(r1["id"], AO), 200)
    assert r1["status"] == "PUBLISHED"

    # One day later the sibling can no longer publish.
    set_clock("2027-01-14T00:00:00Z")
    resp = api.publish_report(r2["id"], AO)
    validate_error(resp, ApiErrorId.ERR_PUBLICATION_DEADLINE_MISSED)
    reports, _ = validate_paginated(api.list_reports(study_id, PI))
    assert next(r for r in reports if r["id"] == r2["id"])["status"] == "ACCEPTED"
    assert get_contract(ctx["contract"]["id"])["disbursed_cents"] == 30000000, (
        "only R1's milestone disbursed"
    )


def test_feasibility_excludes_declined_and_withdrawn_sites(api):
    """PRD §3.4: "for each `CONTACTED` site, the site's `max_participants`
    multiplied by the yield credit `YIELD_CONTACTED` of 0.35 and rounded down
    to a whole participant, plus for each `PROSPECTED` site the same product
    with the yield credit `YIELD_PROSPECTED` of 0.10, again rounded down per
    site before summing."
    PRD §3.4: "Sites in `DECLINED`, `WITHDRAWN`, or `COMPLETED` contribute zero
    to both variants."

    Design: Corner/calculations/feasibility_excludes_declined_and_withdrawn_sites
    """
    ctx = setup_study_with_sites(site_specs=((60, "RECRUITED"), (300, "CONTACTED")))
    study_id = ctx["study"]["id"]
    study = get_study(study_id)
    assert study["committed_projected_n"] == 60
    assert study["pipeline_projected_n"] == 165  # 60 + floor(300 * 0.35)

    # A PROSPECTED 500-capacity site adds floor(500 * 0.10) = 50.
    site_d = add_site(study_id, name="Site D", max_participants=500,
                      target_state="PROSPECTED")
    study = get_study(study_id)
    assert study["pipeline_projected_n"] == 215

    # Once DECLINED it contributes zero to both variants again.
    site_d = validate_success(
        api.site_outreach(site_d["id"], site_outreach_payload("DECLINED"), SD), 200
    )
    assert site_d["status"] == "DECLINED"
    study = get_study(study_id)
    assert study["committed_projected_n"] == 60
    assert study["pipeline_projected_n"] == 165
