"""Endpoint surface, the four-oh-four families and the role/identity barriers.

Three groups of corner cases live here: the endpoints whose whole point is what they
must NOT touch (the two-field patch, the entity-less clock, the read that mutates
nothing), the two not-found families and their place in the precedence ladder, and
the role matrix plus the two segregation-of-duties comparisons.
"""
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_client import api_client, instants_equal
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import REQUIRED_HANDOFF_PACKET_ITEMS
from test_helpers.test_users import (
    ABSTRACTOR,
    ATTESTER,
    CERTIFICATION_REVIEWER_ALT_USER_ID,
    CERTIFICATION_REVIEWER_USER_ID,
    COORD,
    ED,
    ED_PHYSICIAN_USER_ID,
    PROGRAM_COORDINATOR_USER_ID,
    QUALITY_ABSTRACTOR_USER_ID,
    QUALITY_ATTESTER_USER_ID,
    REVIEWER,
    REVIEWER_ALT,
    TRANSFER,
    make_ed_physician_headers,
    make_neurologist_headers,
    make_program_coordinator_headers,
    make_quality_abstractor_headers,
)

# A syntactically valid UUID that never names a row in any collection.
GHOST = "11111111-1111-4111-8111-111111111111"

# The report period every certification scenario below uses.
PERIOD_START = "2026-09-01T00:00:00Z"
PERIOD_END = "2026-10-01T00:00:00Z"


def _determine(checklist_id, neurologist_id):
    """Determine a checklist through the client's keyword contract.

    `api_client.determine_checklist` declares `(checklist_id, headers, payload)`, so
    the headers must be passed by keyword; the shared fixture passes them
    positionally into the payload slot, which is why this file calls the client.
    """
    return validate_success(
        api_client.determine_checklist(
            checklist_id, headers=make_neurologist_headers(neurologist_id), payload={}
        )
    )


def _decide_report(report_id, headers):
    """Decide a report through the client's keyword contract, as above."""
    return api_client.decide_certification_report(
        report_id, headers=headers, payload=f.decide_report_payload()
    )


def _determined_case(context, door_at, *, absolute=0, dti_minutes=20):
    """A case at the spoke carried to ELIGIBILITY_DETERMINED through a real consult.

    With `absolute=1` the documented contraindication forces an INELIGIBLE
    determination and a `NO_TREATMENT` disposition, which is the only state a case
    that never travelled may be closed from.
    """
    built = fx.setup_case_with_completed_consult(context, door_at)
    case_id = built["case"]["id"]
    fx.complete_imaging(case_id, at=fx.shift(door_at, minutes=dti_minutes))
    checklist = fx.setup_documented_checklist(case_id, absolute_contraindications=absolute)
    determined = _determine(checklist["id"], context["neurologist"]["id"])
    return {
        "case": fx.read_case(case_id),
        "checklist": determined,
        "consult": built["consult"],
    }


def _closed_ineligible_case(context, door_at, *, measure="STK_DTN_60"):
    """An INELIGIBLE case closed with one FINALIZED abstraction attached to nothing."""
    built = _determined_case(context, door_at, absolute=1)
    case_id = built["case"]["id"]
    abstraction = fx.create_abstraction(case_id, measure)
    fx.close_case(case_id, at=fx.shift(door_at, minutes=55))
    built["abstraction"] = fx.finalize_abstraction(abstraction["id"])
    built["case"] = fx.read_case(case_id)
    return built


def _submitted_empty_denominator_report(*, submit_headers=None):
    """Two excluded abstractions over two closed cases: every rate 0.00, composite 0.00."""
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    first = _closed_ineligible_case(context, "2026-09-02T08:00:00Z")
    second = _closed_ineligible_case(context, "2026-09-03T08:00:00Z")
    center = fx.read_center(context["spoke"]["id"])
    report = fx.create_report(
        center["id"], PERIOD_START, PERIOD_END, at="2026-09-05T09:00:00Z"
    )
    submitted = fx.submit_report(
        report["id"], at="2026-09-05T09:00:00Z", headers=submit_headers
    )
    return {
        "context": context,
        "center": center,
        "cases": [first, second],
        "report": submitted,
    }


def test_patching_a_center_edits_two_fields_and_refuses_every_other_key():
    """Partial updates leave the omitted field alone, bump version, and refuse the rest.

    PRD 3.1: "A facility's `name` and `ems_region_code` may later be revised by the same coordinator role; nothing else about the registration is editable, and the revision increments the facility's `version`"
    PRD 2.11: "Every `id` appearing in a URL path must reference an existing record of the addressed collection, returning that collection's own not-found code"

    Design: Corner/endpoints/patching_a_center_touches_only_the_two_editable_fields
    """
    fx.set_clock("2026-09-01T08:00:00Z")
    center = fx.register_center(
        name="Riverside Community Spoke", facility_type="SPOKE",
        state_code="CA", ems_region_code="CA-R1",
    )
    assert center["version"] == 1, f"a fresh registration starts at 1, got {center['version']}"

    renamed = validate_success(
        api_client.update_stroke_center(
            center["id"], {"name": "Riverside Regional Spoke"}, COORD
        )
    )
    assert renamed["name"] == "Riverside Regional Spoke", (
        f"the name-only patch renames the facility, got {renamed['name']}"
    )
    assert renamed["ems_region_code"] == "CA-R1", (
        f"the omitted region is left alone, got {renamed['ems_region_code']}"
    )
    assert renamed["version"] == center["version"] + 1, (
        f"a partial update is still a version-bearing write, got {renamed['version']}"
    )
    assert renamed["facility_type"] == center["facility_type"] == "SPOKE", (
        f"no other field moved, got {renamed['facility_type']}"
    )
    assert renamed["certification_status"] == "PROVISIONAL", (
        f"the patch does not touch certification, got {renamed['certification_status']}"
    )

    reregioned = validate_success(
        api_client.update_stroke_center(center["id"], {"ems_region_code": "CA-R4"}, COORD)
    )
    assert reregioned["name"] == "Riverside Regional Spoke", (
        f"the region-only patch keeps the new name, got {reregioned['name']}"
    )
    assert reregioned["ems_region_code"] == "CA-R4", (
        f"the region is the field that moved, got {reregioned['ems_region_code']}"
    )
    assert reregioned["version"] == renamed["version"] + 1, (
        f"the second patch increments again, got {reregioned['version']}"
    )

    validate_error(
        api_client.update_stroke_center(center["id"], {"facility_type": "HUB_PRIMARY"}, COORD),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api_client.update_stroke_center(
            center["id"], {"certification_status": "CERTIFIED"}, COORD
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    after = fx.read_center(center["id"])
    assert after["name"] == "Riverside Regional Spoke", (
        f"the refusals wrote no name, got {after['name']}"
    )
    assert after["ems_region_code"] == "CA-R4", (
        f"the refusals wrote no region, got {after['ems_region_code']}"
    )
    assert after["facility_type"] == "SPOKE", (
        f"the refused facility_type never landed, got {after['facility_type']}"
    )
    assert after["certification_status"] == "PROVISIONAL", (
        f"the refused certification_status never landed, got {after['certification_status']}"
    )
    assert after["version"] == reregioned["version"], (
        f"a refused patch is not a write, got {after['version']}"
    )

    validate_error(
        api_client.get_stroke_center(GHOST, COORD),
        ApiErrorId.ERR_CENTER_NOT_FOUND.value,
        404,
    )


def test_the_logical_clock_stamps_every_system_field_and_returns_no_entity():
    """An input instant may precede the clock; a system instant is the clock exactly.

    PRD 2.4: "it is the one endpoint outside the `/stroke-network` mount, exposed at `POST /_clock/set_current_utc`, it returns HTTP 200, and it mutates no entity"
    PRD 2.5: "are always the logical clock as it stands at the moment the write is applied"

    Design: Corner/endpoints/the_logical_clock_endpoint_supplies_every_system_timestamp
    """
    clock_body = validate_success(api_client.set_clock("2026-09-01T08:00:00Z", COORD), 200)
    assert not isinstance(clock_body, dict) or "id" not in clock_body, (
        f"the clock call returns no addressable entity, got {clock_body}"
    )

    center = fx.register_center(
        name="Riverside Community Spoke", facility_type="SPOKE",
        state_code="CA", ems_region_code="CA-R1",
    )
    assert instants_equal(center["created_at"], "2026-09-01T08:00:00Z"), (
        f"creation stamps come from the clock, got {center['created_at']}"
    )
    assert instants_equal(center["updated_at"], center["created_at"]), (
        f"a record never touched since creation has equal stamps, got {center['updated_at']}"
    )

    case = validate_success(
        api_client.activate_code_stroke(
            f.code_stroke_payload(
                center["id"], "2026-09-01T07:30:00Z",
                last_known_well_at="2026-09-01T07:10:00Z",
            ),
            ED,
        ),
        201,
    )
    assert instants_equal(case["created_at"], "2026-09-01T08:00:00Z"), (
        f"the case is created at the clock, got {case['created_at']}"
    )
    assert instants_equal(case["door_at"], "2026-09-01T07:30:00Z"), (
        f"an input instant may sit half an hour before the clock, got {case['door_at']}"
    )
    assert instants_equal(case["activation_at"], "2026-09-01T08:00:00Z"), (
        f"activation_at is a system field and follows the clock, got {case['activation_at']}"
    )

    validate_success(api_client.set_clock("2026-09-01T09:00:00Z", ED), 200)
    imaged = validate_success(
        api_client.complete_imaging(case["id"], f.imaging_complete_payload(), ED)
    )
    assert instants_equal(imaged["imaging_at"], "2026-09-01T09:00:00Z"), (
        f"imaging_at is the clock at the moment of the write, got {imaged['imaging_at']}"
    )
    assert instants_equal(imaged["updated_at"], "2026-09-01T09:00:00Z"), (
        f"the write refreshes updated_at from the clock, got {imaged['updated_at']}"
    )
    assert imaged["door_to_imaging_minutes"] == 90, (
        "07:30 to 09:00 spans an input instant and a clock instant, got "
        f"{imaged['door_to_imaging_minutes']}"
    )

    validate_success(api_client.set_clock("2026-09-01T10:00:00Z", ABSTRACTOR), 200)
    reread = fx.read_case(case["id"])
    assert instants_equal(reread["imaging_at"], imaged["imaging_at"]), (
        f"advancing the clock rewrites nothing already stamped, got {reread['imaging_at']}"
    )
    assert reread["door_to_imaging_minutes"] == 90, (
        f"the derived interval is frozen too, got {reread['door_to_imaging_minutes']}"
    )


def test_granting_a_proxy_credential_needs_both_sides_and_unblocks_the_selector():
    """The junction row is what moves a consult from escalation to assignment.

    PRD 3.3: "A newly created consult is stamped with `requested_at` from the logical clock, a `status` of `REQUESTED`, a null `assigned_neurologist_id`, a `decline_count` of 0, a `routing_attempt_count` of 1"
    PRD 3.3: "The consult's `status` becomes `ESCALATED_UNFILLED`, `assigned_neurologist_id` stays null, `routing_attempt_count` is still incremented"
    PRD 3.1: "The grant is appended to the agreement's `proxy_credentials` array as an object carrying that `neurologist_id`, that `privilege_scope`, that `expires_at`, a `status` of `GRANTED`, and a `granted_at` set to the logical clock"
    PRD 2.12: "every action path carries exactly one identifier, and that identifier is resolved before any body field is inspected"

    Design: Corner/endpoints/granting_a_proxy_credential_requires_both_sides_to_exist_and_makes_the_neurologist_routable
    """
    context = fx.setup_network(
        clock="2026-09-01T08:00:00Z", neurologists=[{"grant_credential": False}]
    )
    agreement_id = context["agreement"]["id"]
    neurologist_id = context["neurologist"]["id"]
    assert context["agreement"]["proxy_credentials"] == [], (
        f"no credential has been granted yet, got {context['agreement']['proxy_credentials']}"
    )

    first_case = fx.activate_case(context["spoke"]["id"], "2026-09-01T09:00:00Z")
    unfilled = fx.request_consult(first_case["id"], agreement_id)
    assert unfilled["status"] == "ESCALATED_UNFILLED", (
        f"clause 5 of the selector finds no grant, got {unfilled['status']}"
    )
    assert unfilled["assigned_neurologist_id"] is None, (
        f"an escalated consult carries no assignee, got {unfilled['assigned_neurologist_id']}"
    )
    assert unfilled["routing_attempt_count"] == 1, (
        "the pass that found nobody is still counted, got "
        f"{unfilled['routing_attempt_count']}"
    )

    validate_error(
        api_client.grant_proxy_credential(
            GHOST, f.proxy_credential_payload(neurologist_id), COORD
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.grant_proxy_credential(
            agreement_id, f.proxy_credential_payload(GHOST), COORD
        ),
        ApiErrorId.ERR_NEUROLOGIST_NOT_FOUND.value,
        404,
    )

    granted = validate_success(
        api_client.grant_proxy_credential(
            agreement_id, f.proxy_credential_payload(neurologist_id), COORD
        ),
        201,
    )
    credentials = granted["proxy_credentials"]
    assert len(credentials) == 1, (
        f"exactly one grant is appended, got {len(credentials)}"
    )
    assert credentials[0]["neurologist_id"] == neurologist_id, (
        f"the grant names the neurologist, got {credentials[0]['neurologist_id']}"
    )
    assert credentials[0]["privilege_scope"] == "CONSULT_AND_THROMBOLYSIS", (
        f"the requested scope is recorded, got {credentials[0]['privilege_scope']}"
    )
    assert credentials[0]["status"] == "GRANTED", (
        f"a new grant is GRANTED, got {credentials[0]['status']}"
    )

    second_case = fx.activate_case(context["spoke"]["id"], "2026-09-01T09:14:00Z")
    assigned = fx.request_consult(second_case["id"], agreement_id)
    assert assigned["status"] == "ASSIGNED", (
        f"the identical request now finds a candidate, got {assigned['status']}"
    )
    assert assigned["assigned_neurologist_id"] == neurologist_id, (
        f"and the candidate is the credentialed neurologist, got "
        f"{assigned['assigned_neurologist_id']}"
    )


def test_reading_a_center_derives_its_counts_without_writing_to_it():
    """Two GETs by two roles are identical; only the abort moves the count and the version.

    PRD 2.8: "A facility's `open_case_count` is the number of `CodeStrokeCase` records whose `center_id` names that facility and whose `status` is anything other than `CLOSED` or `ABORTED`"
    PRD 2.5: "a monotonically increasing counter that begins at 1 on creation and increments by exactly 1 on every mutation of that record"

    Design: Corner/endpoints/reading_a_center_returns_its_derived_operational_fields_without_mutating_it
    """
    fx.set_clock("2026-09-01T08:00:00Z")
    center = fx.register_center(
        name="Riverside Community Spoke", facility_type="SPOKE",
        state_code="CA", ems_region_code="CA-R1",
    )
    first_case = fx.activate_case(center["id"], "2026-09-01T08:00:00Z")
    fx.activate_case(center["id"], "2026-09-01T08:00:00Z")

    read_one = validate_success(api_client.get_stroke_center(center["id"], COORD))
    assert read_one["open_case_count"] == 2, (
        f"both live cases are counted, got {read_one['open_case_count']}"
    )
    assert read_one["equipment_readiness_posture"] == "READY", (
        f"both readiness flags began true, got {read_one['equipment_readiness_posture']}"
    )
    assert read_one["ems_routing_posture"] == "ROUTINE", (
        "two open cases sit below the inclusive threshold of three, got "
        f"{read_one['ems_routing_posture']}"
    )
    assert read_one["public_dtn_compliance_pct"] is None, (
        f"no report has been published, got {read_one['public_dtn_compliance_pct']}"
    )

    read_two = validate_success(api_client.get_stroke_center(center["id"], TRANSFER))
    assert read_two["version"] == read_one["version"], (
        f"reading never bumps the version, got {read_two['version']}"
    )
    assert instants_equal(read_two["updated_at"], read_one["updated_at"]), (
        f"reading never refreshes updated_at, got {read_two['updated_at']}"
    )
    assert read_two["open_case_count"] == 2, (
        f"the second reader sees the same derived count, got {read_two['open_case_count']}"
    )

    fx.abort_case(first_case["id"], at="2026-09-01T08:30:00Z")

    read_three = validate_success(api_client.get_stroke_center(center["id"], ABSTRACTOR))
    assert read_three["open_case_count"] == 1, (
        f"the aborted case leaves the count, got {read_three['open_case_count']}"
    )
    assert read_three["ems_routing_posture"] == "ROUTINE", (
        f"one open case is still routine, got {read_three['ems_routing_posture']}"
    )
    assert read_three["version"] != read_one["version"], (
        "the version moved because of the abort cascade, not because of the reads, got "
        f"{read_three['version']}"
    )


def test_a_composite_of_zero_is_denied_returned_and_unpublishable_but_resubmittable():
    """The low branch of decide: DENIED, RETURNED, the escalation hops, and a fresh submit.

    PRD 3.9: "The `decision` follows the score — `CERTIFIED` at 85.00 or above, `CONDITIONAL` from 70.00 up to but not including 85.00, and `DENIED` below 70.00"
    PRD 3.9: "A `CERTIFIED` or `CONDITIONAL` decision moves the report's `status` to `ACCEPTED`; a `DENIED` one moves it to `RETURNED`, from where it can be resubmitted."
    PRD 3.9: "whatever the submission produced is what the decision judges, even if abstractions or deviations have moved since"
    PRD 3.9: "First, the facility's `consecutive_denied_report_count` rises by 1 and its `certification_status` moves to `SUSPENDED`"
    PRD 3.9: "Second, and caused by the first, the facility's `ems_routing_posture` becomes `BYPASS`."
    PRD 3.9: "takes no request body and requires an `ACCEPTED` report whose `decision` is `CERTIFIED` or `CONDITIONAL`"

    Design: Corner/endpoints/a_report_below_the_conditional_floor_is_returned_and_denied_and_cannot_be_published
    """
    scenario = _submitted_empty_denominator_report()
    submitted = scenario["report"]
    center_before = scenario["center"]

    assert submitted["status"] == "SUBMITTED", (
        f"the report is submitted before it is judged, got {submitted['status']}"
    )
    assert submitted["rate_variant"] == "CERTIFIED", (
        f"submission switches the variant, got {submitted['rate_variant']}"
    )
    assert submitted["included_abstraction_count"] == 2, (
        f"both finalised abstractions attach, got {submitted['included_abstraction_count']}"
    )
    assert submitted["dtn_60_compliance_pct"] == 0.00, (
        "both rows carry an absolute-contraindication exclusion so the certified "
        f"denominator is empty, got {submitted['dtn_60_compliance_pct']}"
    )
    assert submitted["composite_certification_score"] == 0.00, (
        "an empty base with no penalty and no volume credit scores zero, got "
        f"{submitted['composite_certification_score']}"
    )

    fx.set_clock("2026-09-05T10:00:00Z")
    decided = validate_success(
        _decide_report(submitted["id"], REVIEWER)
    )
    assert decided["status"] == "RETURNED", (
        f"a denial returns the report rather than accepting it, got {decided['status']}"
    )
    assert decided["decision"] == "DENIED", (
        f"0.00 is strictly below the conditional floor of 70.00, got {decided['decision']}"
    )
    assert decided["decided_by_user_id"] == CERTIFICATION_REVIEWER_USER_ID, (
        f"the deciding identity is recorded, got {decided['decided_by_user_id']}"
    )
    assert instants_equal(decided["decided_at"], "2026-09-05T10:00:00Z"), (
        f"decided_at is stamped from the logical clock, got {decided['decided_at']}"
    )
    assert decided["composite_certification_score"] == 0.00, (
        "decide re-reads the stored composite and never recomputes it, got "
        f"{decided['composite_certification_score']}"
    )

    center_after = fx.read_center(center_before["id"])
    assert center_after["consecutive_denied_report_count"] == (
        center_before["consecutive_denied_report_count"] + 1
    ), (
        "the denial counter advances by exactly one, got "
        f"{center_after['consecutive_denied_report_count']}"
    )
    assert center_after["certification_status"] == "SUSPENDED", (
        "the first denial hop moves the facility to SUSPENDED, got "
        f"{center_after['certification_status']}"
    )
    assert center_after["ems_routing_posture"] == "BYPASS", (
        "the second hop is caused by the first, got "
        f"{center_after['ems_routing_posture']}"
    )

    validate_error(
        api_client.publish_certification_report(submitted["id"], headers=COORD),
        ApiErrorId.ERR_INVALID_REPORT_STATE.value,
        409,
    )

    resubmitted = fx.submit_report(submitted["id"], at="2026-09-05T11:00:00Z")
    assert resubmitted["status"] == "SUBMITTED", (
        f"a RETURNED report is re-submittable, got {resubmitted['status']}"
    )
    assert instants_equal(resubmitted["submitted_at"], "2026-09-05T11:00:00Z"), (
        f"the resubmission re-stamps submitted_at, got {resubmitted['submitted_at']}"
    )


def _three_consults_on_two_neurologists():
    """Three cases, one consult each: the first IN_SESSION, the other two ASSIGNED."""
    context = fx.setup_network(
        clock="2026-09-01T08:00:00Z",
        neurologists=[
            {"roster_rank": 10, "concurrent_consult_limit": 1},
            {"roster_rank": 20, "concurrent_consult_limit": 2},
        ],
    )
    cases = []
    consults = []
    for door_at in ("2026-09-01T08:00:00Z", "2026-09-01T08:05:00Z", "2026-09-01T08:10:00Z"):
        case = fx.activate_case(context["spoke"]["id"], door_at)
        fx.complete_imaging(case["id"], at=door_at)
        consults.append(fx.request_consult(case["id"], context["agreement"]["id"], at=door_at))
        cases.append(case)
    fx.accept_consult(
        consults[0]["id"], context["neurologists"][0]["id"], at="2026-09-01T08:16:00Z"
    )
    return {"context": context, "cases": cases, "consults": consults}


def test_consult_filters_compose_and_total_count_describes_the_filtered_set():
    """Every count on the page is the filtered count, and two filters intersect.

    PRD 2.3: "`total_count` is the size of the full filtered result set before the page window is applied and `has_more` indicates whether records remain beyond the current window"
    PRD 2.3: "Filter parameters offered by a list endpoint combine conjunctively — a request that supplies two filters returns only records matching both."
    PRD 2.3: "Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending."

    Design: Corner/endpoints/consult_list_filters_compose_with_pagination_and_total_count_follows_the_filter
    """
    scenario = _three_consults_on_two_neurologists()
    context = scenario["context"]
    consults = scenario["consults"]
    second_neurologist = context["neurologists"][1]["id"]

    rows, meta = validate_paginated(
        api_client.list_consults(
            COORD, {"agreement_id": context["agreement"]["id"], "limit": 10, "offset": 0}
        )
    )
    assert len(rows) == 3, f"all three consults sit on the one agreement, got {len(rows)}"
    assert meta["total_count"] == 3, f"the filtered count is three, got {meta['total_count']}"
    assert meta["has_more"] is False, "a window of ten holds all three rows"
    assert rows[0]["id"] == consults[0]["id"], (
        f"ordering is by created_at ascending, got {rows[0]['id']}"
    )

    rows, meta = validate_paginated(
        api_client.list_consults(COORD, {"status": "ASSIGNED", "limit": 10, "offset": 0})
    )
    assert len(rows) == 2, f"one consult was accepted and left ASSIGNED, got {len(rows)}"
    assert meta["total_count"] == 2, (
        f"the status filter narrows the count too, got {meta['total_count']}"
    )
    assert meta["has_more"] is False
    assert rows[0]["status"] == "ASSIGNED", (
        f"the filter really selected on status, got {rows[0]['status']}"
    )

    rows, meta = validate_paginated(
        api_client.list_consults(COORD, {"status": "ASSIGNED", "limit": 1, "offset": 0})
    )
    assert len(rows) == 1, f"the window is one row wide, got {len(rows)}"
    assert meta["total_count"] == 2, (
        "total_count is the filtered set before the window, not the page size, got "
        f"{meta['total_count']}"
    )
    assert meta["has_more"] is True, (
        "one row of two filtered rows leaves more behind, got "
        f"{meta['has_more']}"
    )
    assert rows[0]["id"] == consults[1]["id"], (
        f"the first assigned row is the second consult, got {rows[0]['id']}"
    )

    rows, meta = validate_paginated(
        api_client.list_consults(COORD, {"status": "ASSIGNED", "limit": 1, "offset": 1})
    )
    assert rows[0]["id"] == consults[2]["id"], (
        f"ordering is stable across pages, got {rows[0]['id']}"
    )
    assert meta["total_count"] == 2, (
        f"the count does not move with the offset, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "the second page exhausts the filtered set"

    rows, meta = validate_paginated(
        api_client.list_consults(
            COORD,
            {
                "status": "ASSIGNED",
                "assigned_neurologist_id": second_neurologist,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 2, (
        "both assigned consults belong to the second neurologist, got "
        f"{meta['total_count']}"
    )
    assert all(row["assigned_neurologist_id"] == second_neurologist for row in rows), (
        f"the two filters intersect, got {[row['assigned_neurologist_id'] for row in rows]}"
    )

    rows, meta = validate_paginated(
        api_client.list_consults(
            COORD, {"case_id": scenario["cases"][0]["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, (
        f"one consult sits on the first case, got {meta['total_count']}"
    )
    assert rows[0]["status"] == "IN_SESSION", (
        f"that consult was accepted, got {rows[0]['status']}"
    )

    rows, meta = validate_paginated(
        api_client.list_consults(COORD, {"status": "COMPLETED", "limit": 10, "offset": 0})
    )
    assert rows == [], f"no consult has completed yet, got {rows}"
    assert meta["total_count"] == 0, (
        f"a filter that matches nothing counts nothing, got {meta['total_count']}"
    )
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_consults(
            COORD, {"assigned_neurologist_id": GHOST, "limit": 10, "offset": 0}
        )
    )
    assert rows == [], f"an unknown filter value matches nothing, got {rows}"
    assert meta["total_count"] == 0, (
        "an unknown filter value is an empty page rather than a not-found error, got "
        f"{meta['total_count']}"
    )


def test_declining_a_transfer_touches_no_destination_and_survives_a_later_abort():
    """Decline is the one transfer action with no cascade, and the abort skips the row.

    PRD 3.7: "records a `decline_reason` and unwinds the case to the node it came from — back to `THROMBOLYSIS_ADMINISTERED` with `disposition` restored to `TREATED_LOCAL` for a drip-and-ship proposal, or back to `ELIGIBILITY_DETERMINED` with `disposition` restored to `PENDING` for a transfer-only one"
    PRD 3.7: "No `open_case_count` moves on a decline, because a proposed transfer was never counted."
    PRD 3.8: "every consult on the case in `REQUESTED`, `ASSIGNED` or `IN_SESSION` is cancelled and every transfer decision in `PROPOSED` or `ACCEPTED` is cancelled"
    PRD 3.8: "the origin facility's `open_case_count` drops by 1 — exactly compensating the increment the activation made"

    Design: Corner/endpoints/declining_a_transfer_never_touches_the_destination_and_survives_a_later_abort
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    destination = fx.register_thrombectomy_center()
    built = _determined_case(context, "2026-09-01T08:00:00Z")
    case_id = built["case"]["id"]
    assert built["checklist"]["determination_status"] == "ELIGIBLE", (
        f"four items and no contraindications attest eligible, got "
        f"{built['checklist']['determination_status']}"
    )

    transfer = fx.propose_transfer(
        case_id, destination["id"], mode="TRANSFER_ONLY",
        transport_eta_minutes=30, at="2026-09-01T09:00:00Z",
    )
    assert transfer["status"] == "PROPOSED"

    before = fx.read_center(destination["id"])
    assert before["open_case_count"] == 0, (
        f"a proposal is not counted at the destination, got {before['open_case_count']}"
    )
    assert before["ems_routing_posture"] == "ROUTINE"

    declined = fx.decline_transfer(transfer["id"], at="2026-09-01T09:20:00Z")
    assert declined["status"] == "DECLINED", (
        f"the proposal is declined, got {declined['status']}"
    )
    assert declined["decline_reason"], (
        f"the reason is recorded on the row, got {declined['decline_reason']}"
    )
    assert declined["accepted_at"] is None, (
        f"a declined transfer was never accepted, got {declined['accepted_at']}"
    )

    after = fx.read_center(destination["id"])
    assert after["open_case_count"] == before["open_case_count"] == 0, (
        f"the decline decremented nothing, got {after['open_case_count']}"
    )
    assert after["ems_routing_posture"] == before["ems_routing_posture"] == "ROUTINE", (
        f"no posture was re-derived, got {after['ems_routing_posture']}"
    )
    assert after["version"] == before["version"], (
        f"the destination was not written to at all, got {after['version']}"
    )

    unwound = fx.read_case(case_id)
    assert unwound["status"] == "ELIGIBILITY_DETERMINED", (
        "a declined transfer-only proposal unwinds the case to the node it came from, got "
        f"{unwound['status']}"
    )
    assert unwound["disposition"] == "PENDING", (
        f"the disposition is restored so another destination may be tried, got "
        f"{unwound['disposition']}"
    )

    fx.abort_case(case_id, at="2026-09-01T09:40:00Z")
    still_declined = fx.read_transfer(transfer["id"])
    assert still_declined["status"] == "DECLINED", (
        "the cancellation cascade covers only PROPOSED and ACCEPTED decisions, got "
        f"{still_declined['status']}"
    )
    assert fx.read_center(destination["id"])["open_case_count"] == 0, (
        "the destination never carried this patient, got "
        f"{fx.read_center(destination['id'])['open_case_count']}"
    )
    assert fx.read_center(context["spoke"]["id"])["open_case_count"] == 0, (
        "the abort released the origin's own count, got "
        f"{fx.read_center(context['spoke']['id'])['open_case_count']}"
    )


# The ten declared 404 identifiers; nothing outside this set may ever be returned.
NOT_FOUND_FAMILY = {
    ApiErrorId.ERR_CENTER_NOT_FOUND.value,
    ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
    ApiErrorId.ERR_NEUROLOGIST_NOT_FOUND.value,
    ApiErrorId.ERR_CASE_NOT_FOUND.value,
    ApiErrorId.ERR_CONSULT_NOT_FOUND.value,
    ApiErrorId.ERR_CHECKLIST_NOT_FOUND.value,
    ApiErrorId.ERR_TRANSFER_NOT_FOUND.value,
    ApiErrorId.ERR_DEVIATION_NOT_FOUND.value,
    ApiErrorId.ERR_ABSTRACTION_NOT_FOUND.value,
    ApiErrorId.ERR_REPORT_NOT_FOUND.value,
}


def test_every_path_identifier_answers_with_its_own_collections_not_found_code():
    """Sixteen well-formed ids that name nothing, ten distinct identifiers, no generic 404.

    PRD 2.11: "Every `id` appearing in a URL path must reference an existing record of the addressed collection, returning that collection's own not-found code"
    PRD 2.12: "Because collections are flat, every action path carries exactly one identifier, and that identifier is resolved before any body field is inspected"

    Design: Corner/errors/each_collection_answers_a_path_id_that_names_nothing_with_its_own_not_found_error
    """
    fx.set_clock("2026-09-01T08:00:00Z")
    probes = [
        ("GET stroke-centers", lambda: api_client.get_stroke_center(GHOST, COORD),
         ApiErrorId.ERR_CENTER_NOT_FOUND),
        ("GET spoke-agreements", lambda: api_client.get_spoke_agreement(GHOST, COORD),
         ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        ("GET neurologists", lambda: api_client.get_neurologist(GHOST, COORD),
         ApiErrorId.ERR_NEUROLOGIST_NOT_FOUND),
        ("GET code-strokes", lambda: api_client.get_code_stroke(GHOST, ED),
         ApiErrorId.ERR_CASE_NOT_FOUND),
        ("GET consults", lambda: api_client.get_consult(GHOST, ED),
         ApiErrorId.ERR_CONSULT_NOT_FOUND),
        ("GET checklists", lambda: api_client.get_checklist(GHOST, ED),
         ApiErrorId.ERR_CHECKLIST_NOT_FOUND),
        ("GET transfer-decisions", lambda: api_client.get_transfer(GHOST, TRANSFER),
         ApiErrorId.ERR_TRANSFER_NOT_FOUND),
        ("GET deviations", lambda: api_client.get_deviation(GHOST, COORD),
         ApiErrorId.ERR_DEVIATION_NOT_FOUND),
        ("GET abstractions", lambda: api_client.get_abstraction(GHOST, ABSTRACTOR),
         ApiErrorId.ERR_ABSTRACTION_NOT_FOUND),
        ("GET certification-reports",
         lambda: api_client.get_certification_report(GHOST, COORD),
         ApiErrorId.ERR_REPORT_NOT_FOUND),
        ("POST readiness-attestations",
         lambda: api_client.record_readiness_attestation(
             GHOST, f.readiness_attestation_payload(), COORD
         ),
         ApiErrorId.ERR_CENTER_NOT_FOUND),
        ("POST spoke-agreements activate",
         lambda: api_client.activate_spoke_agreement(GHOST, headers=COORD),
         ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        ("POST code-strokes imaging-complete",
         lambda: api_client.complete_imaging(GHOST, f.imaging_complete_payload(), ED),
         ApiErrorId.ERR_CASE_NOT_FOUND),
        ("POST checklists inclusion-items",
         lambda: api_client.confirm_inclusion_item(
             GHOST, f.inclusion_item_payload("INC_NIHSS_RECORDED"), ED
         ),
         ApiErrorId.ERR_CHECKLIST_NOT_FOUND),
        ("POST transfer-decisions complete-handoff",
         lambda: api_client.complete_handoff(
             GHOST, f.handoff_payload(list(REQUIRED_HANDOFF_PACKET_ITEMS)), TRANSFER
         ),
         ApiErrorId.ERR_TRANSFER_NOT_FOUND),
        ("POST certification-reports submit",
         lambda: api_client.submit_certification_report(GHOST, headers=COORD),
         ApiErrorId.ERR_REPORT_NOT_FOUND),
    ]

    observed = set()
    for label, call, expected in probes:
        response = call()
        assert response.status_code == 404, (
            f"{label} on an id that names nothing must be 404, got {response.status_code}"
        )
        error = validate_error(response, expected.value, 404)
        observed.add(error["error_id"])

    assert observed <= NOT_FOUND_FAMILY, (
        f"only the ten declared not-found identifiers may appear, got {sorted(observed)}"
    )
    assert len(observed) == 10, (
        f"all ten collections are exercised distinctly, got {sorted(observed)}"
    )


def test_a_dangling_body_reference_names_the_collection_it_points_at():
    """Fourteen bad foreign keys: every one is a 404 against the target, never the host.

    PRD 2.11: "Every foreign-key field in a request body must reference an existing record of the target entity, returning that entity's not-found code from the same list, and checked in the order the fields are declared in the endpoint's input list"
    PRD 2.12: "Where a path identifier and a body foreign key are both present, the path identifier is resolved first, then the body references in the order the endpoint declares them."

    Design: Corner/errors/a_body_reference_is_reported_against_the_collection_it_names_not_the_endpoint_it_sits_on
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    hub_id = context["hub"]["id"]
    spoke_id = context["spoke"]["id"]
    agreement_id = context["agreement"]["id"]
    neurologist_id = context["neurologist"]["id"]
    destination = fx.register_thrombectomy_center()

    case = fx.activate_case(spoke_id, "2026-09-01T08:00:00Z")
    case = fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    center_version = fx.read_center(spoke_id)["version"]

    probes = [
        ("code-strokes center_id",
         lambda: api_client.activate_code_stroke(
             f.code_stroke_payload(GHOST, "2026-09-01T08:20:00Z"), ED
         ),
         ApiErrorId.ERR_CENTER_NOT_FOUND),
        ("spoke-agreements hub_center_id",
         lambda: api_client.create_spoke_agreement(
             f.spoke_agreement_payload(GHOST, spoke_id), COORD
         ),
         ApiErrorId.ERR_CENTER_NOT_FOUND),
        ("spoke-agreements spoke_center_id",
         lambda: api_client.create_spoke_agreement(
             f.spoke_agreement_payload(hub_id, GHOST), COORD
         ),
         ApiErrorId.ERR_CENTER_NOT_FOUND),
        ("neurologists home_center_id",
         lambda: api_client.register_neurologist(f.neurologist_payload(GHOST), COORD),
         ApiErrorId.ERR_CENTER_NOT_FOUND),
        ("proxy-credentials neurologist_id",
         lambda: api_client.grant_proxy_credential(
             agreement_id, f.proxy_credential_payload(GHOST), COORD
         ),
         ApiErrorId.ERR_NEUROLOGIST_NOT_FOUND),
        ("proxy-credentials agreement path",
         lambda: api_client.grant_proxy_credential(
             GHOST, f.proxy_credential_payload(neurologist_id), COORD
         ),
         ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        ("consults agreement_id",
         lambda: api_client.request_consult(
             f.consult_request_payload(case["id"], GHOST, case["version"]), ED
         ),
         ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        ("consults case_id",
         lambda: api_client.request_consult(
             f.consult_request_payload(GHOST, agreement_id, case["version"]), ED
         ),
         ApiErrorId.ERR_CASE_NOT_FOUND),
        ("checklists case_id",
         lambda: api_client.create_checklist(f.checklist_payload(GHOST), ED),
         ApiErrorId.ERR_CASE_NOT_FOUND),
        ("abstractions case_id",
         lambda: api_client.create_abstraction(f.abstraction_payload(GHOST), ABSTRACTOR),
         ApiErrorId.ERR_CASE_NOT_FOUND),
        ("deviations case_id",
         lambda: api_client.create_deviation(
             f.deviation_payload(GHOST, "DTN_EXCEEDED", "MINOR", "clock overrun on nothing"),
             ABSTRACTOR,
         ),
         ApiErrorId.ERR_CASE_NOT_FOUND),
        ("transfer-decisions case_id",
         lambda: api_client.propose_transfer(
             f.transfer_payload(GHOST, destination["id"], transport_eta_minutes=30), TRANSFER
         ),
         ApiErrorId.ERR_CASE_NOT_FOUND),
        ("transfer-decisions destination_center_id",
         lambda: api_client.propose_transfer(
             f.transfer_payload(case["id"], GHOST, transport_eta_minutes=30), TRANSFER
         ),
         ApiErrorId.ERR_CENTER_NOT_FOUND),
        ("certification-reports center_id",
         lambda: api_client.create_certification_report(
             f.certification_report_payload(GHOST, PERIOD_START, PERIOD_END, center_version),
             COORD,
         ),
         ApiErrorId.ERR_CENTER_NOT_FOUND),
    ]

    observed = set()
    for label, call, expected in probes:
        response = call()
        assert response.status_code == 404, (
            f"{label} is a dangling reference, never a 422 or a 409, got "
            f"{response.status_code}"
        )
        error = validate_error(response, expected.value, 404)
        observed.add(error["error_id"])

    host_collections = {
        ApiErrorId.ERR_CONSULT_NOT_FOUND.value,
        ApiErrorId.ERR_CHECKLIST_NOT_FOUND.value,
        ApiErrorId.ERR_ABSTRACTION_NOT_FOUND.value,
        ApiErrorId.ERR_DEVIATION_NOT_FOUND.value,
        ApiErrorId.ERR_TRANSFER_NOT_FOUND.value,
        ApiErrorId.ERR_REPORT_NOT_FOUND.value,
    }
    assert observed & host_collections == set(), (
        f"no call may report the endpoint's own collection, got {sorted(observed)}"
    )

    _, meta = validate_paginated(
        api_client.list_consults(COORD, {"agreement_id": agreement_id, "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, (
        f"not one of the refused writes created anything, got {meta['total_count']}"
    )


def test_the_not_found_family_sits_below_the_shape_checks_and_above_the_state_checks():
    """One ladder, walked from both sides of the not-found rungs.

    PRD 2.11: "When a single request violates more than one rule, the response is determined by the highest-precedence rule violated, not by the order in which an implementation happens to run its checks."
    PRD 2.11: "The body must contain every required input field of the endpoint with the declared JSON type, must not contain unknown fields"
    PRD 2.11: "Every enum-typed input field must carry one of that field's declared values"
    PRD 2.11: "`expected_case_version` must equal the referenced case's current `version`"
    PRD 2.12: "a request naming a non-existent record is rejected with that collection's not-found code regardless of what else the body gets wrong"

    Design: Corner/errors/the_not_found_family_sits_between_the_shape_checks_above_it_and_the_state_checks_below_it
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    agreement_id = context["agreement"]["id"]
    neurologist_id = context["neurologist"]["id"]
    case = fx.activate_case(context["spoke"]["id"], "2026-09-01T08:00:00Z")
    case = fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    current_version = case["version"]
    stale_version = current_version - 1
    assert stale_version >= 1, (
        f"the imaging write left a version to be stale against, got {current_version}"
    )

    validate_error(
        api_client.suspend_stroke_center(GHOST, f.suspend_center_payload(), COORD),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    validate_error(
        api_client.create_checklist(
            {"case_id": GHOST, "documentation_status": "DOCUMENTED"}, ED
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        api_client.propose_transfer(
            f.transfer_payload(GHOST, GHOST, mode="AIR_AMBULANCE", transport_eta_minutes=30),
            TRANSFER,
        ),
        ApiErrorId.ERR_INVALID_ENUM_VALUE.value,
        422,
    )
    validate_error(
        api_client.request_consult(
            f.consult_request_payload(case["id"], GHOST, stale_version), ED
        ),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.request_consult(
            f.consult_request_payload(case["id"], agreement_id, stale_version), ED
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION.value,
        412,
    )
    validate_error(
        api_client.accept_consult(GHOST, make_neurologist_headers(neurologist_id)),
        ApiErrorId.ERR_CONSULT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.activate_spoke_agreement(GHOST, headers=COORD),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.activate_spoke_agreement(agreement_id, headers=COORD),
        ApiErrorId.ERR_INVALID_AGREEMENT_STATE.value,
        409,
    )

    accepted = validate_success(
        api_client.request_consult(
            f.consult_request_payload(case["id"], agreement_id, current_version), ED
        ),
        201,
    )
    assert accepted["status"] == "ASSIGNED", (
        "the request that violates no rung at all succeeds, got "
        f"{accepted['status']}"
    )
    assert accepted["assigned_neurologist_id"] == neurologist_id, (
        f"and routes to the credentialed neurologist, got "
        f"{accepted['assigned_neurologist_id']}"
    )


def test_every_role_is_refused_every_other_roles_exclusive_operation():
    """Ten exclusive operations, ten role refusals, and nothing written on the way through.

    PRD 2.1: "When the headers are well formed but the named role is not authorised for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.11: "The caller's role must appear in the endpoint's authorised-role list"

    Design: Corner/rbac/every_role_is_refused_every_other_roles_exclusive_operation
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    spoke_id = context["spoke"]["id"]
    agreement_id = context["agreement"]["id"]
    neurologist_headers = make_neurologist_headers(context["neurologist"]["id"])
    destination = fx.register_thrombectomy_center()

    case = fx.activate_case(spoke_id, "2026-09-01T08:00:00Z")
    case = fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    checklist = fx.create_checklist(case["id"])
    report = fx.create_report(spoke_id, PERIOD_START, PERIOD_END)

    refusals = [
        ("EdPhysician registering a facility",
         lambda: api_client.register_stroke_center(f.register_center_payload(), ED)),
        ("Neurologist activating a code stroke",
         lambda: api_client.activate_code_stroke(
             f.code_stroke_payload(spoke_id, "2026-09-01T08:20:00Z"), neurologist_headers
         )),
        ("TransferCoordinator determining a checklist",
         lambda: api_client.determine_checklist(
             checklist["id"], headers=TRANSFER, payload={}
         )),
        ("QualityAbstractor proposing a transfer",
         lambda: api_client.propose_transfer(
             f.transfer_payload(case["id"], destination["id"], transport_eta_minutes=30),
             ABSTRACTOR,
         )),
        ("ProgramCoordinator creating an abstraction",
         lambda: api_client.create_abstraction(f.abstraction_payload(case["id"]), COORD)),
        ("CertificationReviewer requesting a consult",
         lambda: api_client.request_consult(
             f.consult_request_payload(case["id"], agreement_id, case["version"]), REVIEWER
         )),
        ("ProgramCoordinator deciding a report",
         lambda: _decide_report(report["id"], COORD)),
        ("CertificationReviewer submitting a report",
         lambda: api_client.submit_certification_report(report["id"], headers=REVIEWER)),
        ("ProgramCoordinator suspending a facility",
         lambda: api_client.suspend_stroke_center(spoke_id, f.suspend_center_payload(), COORD)),
        ("EdPhysician retracting an abstraction that is really a checklist",
         lambda: api_client.retract_abstraction(
             checklist["id"], f.retract_abstraction_payload(), ED
         )),
    ]

    for label, call in refusals:
        response = call()
        assert response.status_code == 403, (
            f"{label} is a role decision, got HTTP {response.status_code}"
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    unchanged = fx.read_report(report["id"])
    assert unchanged["status"] == "DRAFT", (
        "the reviewer's refused submit left the legal DRAFT transition untaken, got "
        f"{unchanged['status']}"
    )
    assert unchanged["decision"] == "PENDING", (
        f"the coordinator's refused decide wrote nothing, got {unchanged['decision']}"
    )
    assert fx.read_center(spoke_id)["certification_status"] == "PROVISIONAL", (
        "the coordinator's refused suspension wrote nothing, got "
        f"{fx.read_center(spoke_id)['certification_status']}"
    )
    _, meta = validate_paginated(
        api_client.list_abstractions(
            ABSTRACTOR, {"case_id": case["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        f"the coordinator's refused abstraction was never created, got {meta['total_count']}"
    )


def test_the_five_shared_operations_admit_exactly_their_two_declared_roles():
    """Each shared endpoint is driven from both of its sides and refused from a third.

    PRD 2.1: "When the headers are well formed but the named role is not authorised for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 3.1: "Suspension runs the other way and is available to both a `ProgramCoordinator` and a `CertificationReviewer`."
    PRD 3.1: "Availability is a small state machine on `on_call_state` with exactly four declared moves, and either the neurologist themselves or a `ProgramCoordinator` may drive it."
    PRD 3.8: "`opened_by_user_id` from the caller's identity header, `review_round` 0 and `debrief_completed` false"
    PRD 3.8: "records a `debrief_summary` and sets `debrief_completed` true, and it is the only thing that ever writes those two fields"

    Design: Corner/rbac/the_five_shared_operations_admit_exactly_their_two_declared_roles
    """
    context = fx.setup_network(clock="2026-09-02T06:00:00Z")
    neurologist_id = context["neurologist"]["id"]
    first = _determined_case(context, "2026-09-02T08:00:00Z", absolute=1)
    second = _determined_case(context, "2026-09-02T10:00:00Z", absolute=1)
    case_a = first["case"]["id"]
    case_b = second["case"]["id"]
    assert first["checklist"]["determination_status"] == "INELIGIBLE", (
        "an absolute contraindication makes the case closeable, got "
        f"{first['checklist']['determination_status']}"
    )

    abstractor_deviation = fx.create_deviation(
        case_a,
        deviation_type="MISSING_CONTRAINDICATION_DOC",
        severity="MINOR",
        narrative="the absolute contraindication was written up late",
        headers=ABSTRACTOR,
    )
    physician_deviation = fx.create_deviation(
        case_b,
        deviation_type="LKW_WINDOW_VIOLATION",
        severity="SENTINEL",
        narrative="the onset window was read from the wrong chart",
        headers=ED,
    )
    assert abstractor_deviation["opened_by_user_id"] == QUALITY_ABSTRACTOR_USER_ID, (
        "the abstractor's identity header is recorded verbatim, got "
        f"{abstractor_deviation['opened_by_user_id']}"
    )
    assert physician_deviation["opened_by_user_id"] == ED_PHYSICIAN_USER_ID, (
        "and so is the physician's on the very same endpoint, got "
        f"{physician_deviation['opened_by_user_id']}"
    )
    assert abstractor_deviation["source"] == "MANUAL"
    assert physician_deviation["source"] == "MANUAL"

    closed_by_physician = fx.close_case(case_a, at="2026-09-02T10:30:00Z", headers=ED)
    closed_by_abstractor = fx.close_case(case_b, at="2026-09-02T10:35:00Z", headers=ABSTRACTOR)
    assert closed_by_physician["status"] == "CLOSED", (
        f"the physician may close, got {closed_by_physician['status']}"
    )
    assert closed_by_abstractor["status"] == "CLOSED", (
        f"and so may the abstractor, got {closed_by_abstractor['status']}"
    )
    assert closed_by_physician["disposition"] == "NO_TREATMENT"
    assert closed_by_abstractor["disposition"] == "NO_TREATMENT"

    validate_error(
        api_client.close_code_stroke(case_a, headers=TRANSFER),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )

    fx.set_clock("2026-09-02T11:00:00Z", headers=REVIEWER)
    physician_debrief = fx.debrief_deviation(abstractor_deviation["id"], headers=ED)
    abstractor_debrief = fx.debrief_deviation(physician_deviation["id"], headers=ABSTRACTOR)
    assert physician_debrief["debrief_completed"] is True, (
        "the physician debriefs the abstractor's deviation, got "
        f"{physician_debrief['debrief_completed']}"
    )
    assert abstractor_debrief["debrief_completed"] is True, (
        "and the abstractor debriefs the physician's, got "
        f"{abstractor_debrief['debrief_completed']}"
    )
    assert physician_debrief["debrief_summary"], "the debrief writes the summary it was given"

    stood_down = fx.set_on_call(
        neurologist_id, "OFF_DUTY", headers=make_neurologist_headers(neurologist_id)
    )
    assert stood_down["on_call_state"] == "OFF_DUTY", (
        f"the neurologist may stand himself down, got {stood_down['on_call_state']}"
    )
    recalled = fx.set_on_call(neurologist_id, "ON_CALL", headers=COORD)
    assert recalled["on_call_state"] == "ON_CALL", (
        f"and the coordinator may recall him, got {recalled['on_call_state']}"
    )
    validate_error(
        api_client.set_on_call_state(
            neurologist_id, f.on_call_state_payload("OFF_DUTY"), ABSTRACTOR
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    assert fx.read_neurologist(neurologist_id)["on_call_state"] == "ON_CALL", (
        "the refused move wrote nothing"
    )

    second_spoke = fx.register_spoke()
    second_agreement = fx.activate_agreement(
        fx.create_agreement(context["hub"]["id"], second_spoke["id"])["id"]
    )
    by_reviewer = validate_success(
        api_client.suspend_spoke_agreement(
            context["agreement"]["id"], f.suspend_agreement_payload(), REVIEWER
        )
    )
    by_coordinator = validate_success(
        api_client.suspend_spoke_agreement(
            second_agreement["id"], f.suspend_agreement_payload(), COORD
        )
    )
    assert by_reviewer["status"] == "SUSPENDED", (
        f"the reviewer may suspend an agreement, got {by_reviewer['status']}"
    )
    assert by_coordinator["status"] == "SUSPENDED", (
        f"and so may the coordinator, got {by_coordinator['status']}"
    )
    assert by_reviewer["active_consult_count"] == 0, (
        "the settled consults leave nothing to cancel, got "
        f"{by_reviewer['active_consult_count']}"
    )


def test_a_report_cannot_be_decided_by_the_identity_that_submitted_it():
    """The barrier compares two opaque ids, is inert when it fires, and yields to state.

    PRD 2.10: "A certification report's deciding `X-User-ID` must differ from the `submitted_by_user_id` recorded on that report at its most recent submission."
    PRD 2.10: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 2.11: "The addressed record must be in a state from which the requested transition is declared, otherwise the per-entity invalid-state code applies"

    Design: Corner/rbac/a_report_cannot_be_decided_by_the_user_who_submitted_it
    """
    scenario = _submitted_empty_denominator_report(
        submit_headers=make_program_coordinator_headers(CERTIFICATION_REVIEWER_USER_ID)
    )
    report = scenario["report"]
    report_id = report["id"]
    assert report["status"] == "SUBMITTED", (
        f"the coordinator role submitted the report, got {report['status']}"
    )
    assert report["submitted_by_user_id"] == CERTIFICATION_REVIEWER_USER_ID, (
        "the submitter's opaque id is recorded verbatim, whatever role carried it, got "
        f"{report['submitted_by_user_id']}"
    )

    refused = _decide_report(report_id, REVIEWER)
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    untouched = fx.read_report(report_id)
    assert untouched["status"] == "SUBMITTED", (
        f"the refused decision is completely inert, got {untouched['status']}"
    )
    assert untouched["decision"] == "PENDING", (
        f"no decision was recorded, got {untouched['decision']}"
    )
    assert untouched["decided_by_user_id"] is None, (
        f"and no decider either, got {untouched['decided_by_user_id']}"
    )
    assert untouched["decided_at"] is None, (
        f"nor a decision instant, got {untouched['decided_at']}"
    )
    assert fx.read_center(scenario["center"]["id"])["certification_status"] == "PROVISIONAL", (
        "the facility is untouched while the barrier holds"
    )

    decided = validate_success(_decide_report(report_id, REVIEWER_ALT))
    assert decided["decided_by_user_id"] == CERTIFICATION_REVIEWER_ALT_USER_ID, (
        "a second reviewer with a different id passes the barrier, got "
        f"{decided['decided_by_user_id']}"
    )
    assert decided["decision"] == "DENIED", (
        f"the zero composite is a denial, got {decided['decision']}"
    )
    assert decided["status"] == "RETURNED", (
        f"and a denial returns the report, got {decided['status']}"
    )
    assert decided["decided_at"] == "2026-09-05T09:00:00Z", (
        f"the decision is stamped from the logical clock, got {decided['decided_at']}"
    )

    again = _decide_report(report_id, REVIEWER)
    validate_error(again, ApiErrorId.ERR_INVALID_REPORT_STATE.value, 409)
    assert fx.read_report(report_id)["decided_by_user_id"] == CERTIFICATION_REVIEWER_ALT_USER_ID, (
        "the state check above the barrier answers first and changes nothing"
    )


def test_an_abstraction_cannot_be_attested_by_the_identity_that_abstracted_it():
    """Two drafts with two different abstractors, each refusing exactly its own author.

    PRD 2.10: "A quality measure abstraction's attesting `X-User-ID` must differ from the `abstracted_by_user_id` recorded when the abstraction was created."
    PRD 3.9: "`abstracted_by_user_id` from the caller's identity header, and a null `attested_by_user_id`, `attestation_note` and `retraction_reason`"
    PRD 2.11: "The addressed record must be in a state from which the requested transition is declared, otherwise the per-entity invalid-state code applies"

    Design: Corner/rbac/an_abstraction_cannot_be_attested_by_the_user_who_abstracted_it
    """
    context = fx.setup_network(clock="2026-09-02T06:00:00Z")
    built = _determined_case(context, "2026-09-02T08:00:00Z", absolute=1)
    case_id = built["case"]["id"]

    by_abstractor = fx.create_abstraction(case_id, "STK_DTN_60")
    by_coordinator = validate_success(
        api_client.create_abstraction(
            f.abstraction_payload(case_id, "STK_4_THROMBOLYTIC_THERAPY"),
            make_quality_abstractor_headers(PROGRAM_COORDINATOR_USER_ID),
        ),
        201,
    )
    assert by_abstractor["abstracted_by_user_id"] == QUALITY_ABSTRACTOR_USER_ID
    assert by_coordinator["abstracted_by_user_id"] == PROGRAM_COORDINATOR_USER_ID, (
        "the abstractor role is opaque, so any operator id may hold it, got "
        f"{by_coordinator['abstracted_by_user_id']}"
    )
    assert by_abstractor["attested_by_user_id"] is None
    assert by_coordinator["attestation_note"] is None

    closed = fx.close_case(case_id, at="2026-09-02T09:00:00Z", headers=ED)
    assert closed["status"] == "CLOSED", f"attestation waits for closure, got {closed['status']}"

    self_attest = api_client.finalize_abstraction(
        by_abstractor["id"], f.finalize_abstraction_payload(), ABSTRACTOR
    )
    validate_error(self_attest, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    still_draft = fx.read_abstraction(by_abstractor["id"])
    assert still_draft["status"] == "DRAFT", (
        f"the refused attestation is inert, got {still_draft['status']}"
    )
    assert still_draft["attested_by_user_id"] is None, (
        f"and records no attester, got {still_draft['attested_by_user_id']}"
    )
    assert still_draft["attestation_note"] is None, (
        f"nor the note it was offered, got {still_draft['attestation_note']}"
    )

    attested = validate_success(
        api_client.finalize_abstraction(
            by_abstractor["id"], f.finalize_abstraction_payload(), ATTESTER
        )
    )
    assert attested["status"] == "FINALIZED", (
        f"a second abstractor identity passes the barrier, got {attested['status']}"
    )
    assert attested["attested_by_user_id"] == QUALITY_ATTESTER_USER_ID, (
        f"and is recorded as the attester, got {attested['attested_by_user_id']}"
    )

    validate_error(
        api_client.finalize_abstraction(
            by_abstractor["id"], f.finalize_abstraction_payload(), ATTESTER
        ),
        ApiErrorId.ERR_INVALID_ABSTRACTION_STATE.value,
        409,
    )
    validate_error(
        api_client.finalize_abstraction(
            by_abstractor["id"], f.finalize_abstraction_payload(), ABSTRACTOR
        ),
        ApiErrorId.ERR_INVALID_ABSTRACTION_STATE.value,
        409,
    )

    validate_error(
        api_client.finalize_abstraction(
            by_coordinator["id"],
            f.finalize_abstraction_payload(),
            make_quality_abstractor_headers(PROGRAM_COORDINATOR_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )
    second_attested = validate_success(
        api_client.finalize_abstraction(
            by_coordinator["id"], f.finalize_abstraction_payload(), ABSTRACTOR
        )
    )
    assert second_attested["status"] == "FINALIZED", (
        "the identity that was barred on the first row is free on the second, got "
        f"{second_attested['status']}"
    )
    assert second_attested["attested_by_user_id"] == QUALITY_ABSTRACTOR_USER_ID, (
        f"got {second_attested['attested_by_user_id']}"
    )


def test_the_five_opaque_roles_bind_no_user_id_so_only_the_role_header_authorises():
    """Never-seen and cross-borrowed operator ids are accepted; only the role decides.

    PRD 2.1: "When `X-User-Role` is `EdPhysician`, `TransferCoordinator`, `QualityAbstractor`, `ProgramCoordinator`, or `CertificationReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity."
    PRD 2.1: "but it never compares that identifier to any entity's `id`"
    PRD 2.1: "When the headers are well formed but the named role is not authorised for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.4: "A capability available to all six roles sets the clock to a supplied `current_utc` instant"
    PRD 2.9: "The posture is `READY` when both flags are true, `DEGRADED` when exactly one is true, and `OFFLINE` when neither is true."

    Design: Corner/rbac/the_five_opaque_roles_never_bind_a_user_id_so_only_the_role_header_authorises
    """
    stranger = "pc-zoe-never-seen-by-this-server"
    context = fx.setup_network(clock="2026-09-02T06:00:00Z")
    spoke_id = context["spoke"]["id"]

    by_physician = fx.activate_case(spoke_id, "2026-09-02T07:00:00Z", headers=ED)
    assert by_physician["activated_by_user_id"] == ED_PHYSICIAN_USER_ID, (
        f"the identity header is recorded verbatim, got {by_physician['activated_by_user_id']}"
    )

    from_stranger = validate_success(
        api_client.register_stroke_center(
            f.register_center_payload(), make_program_coordinator_headers(stranger)
        ),
        201,
    )
    assert from_stranger["certification_status"] == "PROVISIONAL", (
        "an operator id the server has never seen still registers a facility, got "
        f"{from_stranger['certification_status']}"
    )
    assert from_stranger["equipment_readiness_posture"] == "READY"
    assert from_stranger["ems_routing_posture"] == "ROUTINE"

    from_borrowed_id = validate_success(
        api_client.register_stroke_center(
            f.register_center_payload(),
            make_program_coordinator_headers(ED_PHYSICIAN_USER_ID),
        ),
        201,
    )
    assert from_borrowed_id["id"] != from_stranger["id"], (
        "the physician's own id under the coordinator role registers a second facility"
    )

    by_borrowed_coordinator = fx.activate_case(
        spoke_id,
        "2026-09-02T07:30:00Z",
        headers=make_ed_physician_headers(PROGRAM_COORDINATOR_USER_ID),
    )
    assert by_borrowed_coordinator["activated_by_user_id"] == PROGRAM_COORDINATOR_USER_ID, (
        "whatever id the authorised role carries is what gets audited, got "
        f"{by_borrowed_coordinator['activated_by_user_id']}"
    )

    fx.set_clock("2026-09-02T08:00:00Z", headers=TRANSFER)
    degraded = validate_success(
        api_client.record_readiness_attestation(
            from_stranger["id"],
            f.readiness_attestation_payload("VIDEO_CART", "FAIL"),
            make_program_coordinator_headers(QUALITY_ABSTRACTOR_USER_ID),
        )
    )
    assert degraded["video_cart_ready"] is False, (
        f"the attestation from a borrowed id still lands, got {degraded['video_cart_ready']}"
    )
    assert degraded["ct_scanner_ready"] is True
    assert degraded["equipment_readiness_posture"] == "DEGRADED", (
        f"exactly one flag false is degraded, got {degraded['equipment_readiness_posture']}"
    )
    assert degraded["ems_routing_posture"] == "DIVERT_ADVISORY", (
        f"and a degraded facility advises diversion, got {degraded['ems_routing_posture']}"
    )
    assert instants_equal(degraded["updated_at"], "2026-09-02T08:00:00Z"), (
        "stamped from the clock the coordinator-free role moved, got "
        f"{degraded['updated_at']}"
    )

    validate_error(
        api_client.register_stroke_center(
            f.register_center_payload(), make_ed_physician_headers(stranger)
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value,
        403,
    )
    _, meta = validate_paginated(
        api_client.list_stroke_centers(ABSTRACTOR, {"limit": 20, "offset": 0})
    )
    assert meta["total_count"] == 4, (
        "the hub, the spoke and the two registered by borrowed ids, and nothing from the "
        f"refused call, got {meta['total_count']}"
    )
