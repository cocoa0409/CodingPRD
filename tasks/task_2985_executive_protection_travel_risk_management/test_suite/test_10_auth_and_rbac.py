"""The two outer rings of the ladder: who is calling, and what that role may do."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u


def test_an_unidentifiable_caller_never_reaches_the_endpoints_role_list(api, dep):
    """Empty, absent and undeclared headers are 401; a real wrong role is 403.

    PRD §2.1: "If either header is absent, present but empty, or if `X-User-Role` carries a string that is not one of the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_or_undeclared_auth_headers_are_rejected_before_the_role_check
    """
    vendor = fx.register_vendor(
        api,
        dep,
        vendor_name="Lisbon Ground",
        vendor_type=c.VENDOR_GROUND_SECURITY,
        country_code=c.COUNTRY_PT,
        max_concurrent_engagements=2,
        sla_response_minutes=30,
        hourly_rate_cents=10_000,
        retainer_cents=50_000,
    )
    payload = f.vendor_suspend_payload("licence review")

    unauthenticated = (
        u.headers_with_empty_role(dep.dir_id),
        u.headers_with_empty_user_id(c.ROLE_SECURITY_DIRECTOR),
        u.headers_without_role(dep.dir_id),
        u.headers_without_user_id(c.ROLE_SECURITY_DIRECTOR),
        u.make_headers(dep.dir_id, c.UNDECLARED_ROLE),
    )
    for headers in unauthenticated:
        response = api.suspend_vendor(vendor["id"], payload, headers)
        validate_error(response, e.ERR_UNAUTHENTICATED, 401)
        a.assert_error_meta_shape(response)

    validate_error(
        api.suspend_vendor(vendor["id"], payload, dep.analyst),
        e.ERR_UNAUTHORIZED_ROLE,
        403,
    )

    stored = fx.read_vendor(api, dep, vendor["id"])
    assert stored["activation_status"] == c.VENDOR_AVAILABLE
    assert stored["suspension_reason"] is None
    assert stored["version"] == 1, "not one of the six rejected calls touched the vendor"


def test_the_pagination_window_is_inclusive_at_one_and_at_one_hundred(api, dep):
    """Zero, 101 and -1 are refused; 1 and 100 are both inside the window.

    PRD §2.3: "A `limit` that is not an integer, or an integer below 1 or above 100, and an `offset` that is not an integer or is negative, are rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/pagination_arguments_outside_their_declared_bounds_are_rejected
    """
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        response = api.list_trips_raw(dep.mgr, params)
        validate_error(response, e.ERR_INVALID_PAGINATION, 400)
        a.assert_error_meta_shape(response)

    smallest_page, smallest_meta = validate_paginated(
        api.list_trips_raw(dep.mgr, {"limit": 1, "offset": 0})
    )
    assert smallest_page == []
    assert smallest_meta["limit"] == 1
    assert smallest_meta["offset"] == 0
    assert smallest_meta["total_count"] == 0
    assert smallest_meta["has_more"] is False

    largest_page, largest_meta = validate_paginated(
        api.list_trips_raw(dep.mgr, {"limit": 100})
    )
    assert largest_page == []
    assert largest_meta["limit"] == 100
    assert largest_meta["total_count"] == 0
    assert largest_meta["has_more"] is False


def test_every_remaining_not_found_identifier_is_reachable(api, dep):
    """Eight referential 404s, each raised from the cheapest endpoint that names it.

    PRD §2.6: "The remaining existence failures — `ERR_STAFF_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_TRIP_LEG_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND` and `ERR_INCIDENT_NOT_FOUND` — all carry HTTP 404 and are raised whichever way the missing row was named, by path segment or by a foreign-key field in the body."

    Design: Corner/errors/every_remaining_not_found_error_id_is_reachable_from_its_own_endpoint
    """
    validate_error(
        api.get_security_staff(c.MISSING_STAFF_ID, dep.ops),
        e.ERR_STAFF_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_executive(c.MISSING_EXECUTIVE_ID, dep.mgr),
        e.ERR_EXECUTIVE_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_risk_assessment(c.MISSING_ASSESSMENT_ID, dep.analyst),
        e.ERR_ASSESSMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.update_destination_rating(
            c.COUNTRY_UNRATED,
            f.destination_rating_patch_payload(crime_index=40.0),
            dep.analyst,
        ),
        e.ERR_DESTINATION_RATING_NOT_FOUND,
        404,
    )
    validate_error(
        api.verify_insurance_policy(
            c.MISSING_POLICY_ID,
            f.policy_verify_payload(verification_note="no such policy"),
            dep.officer,
        ),
        e.ERR_POLICY_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_detail_assignment(c.MISSING_ASSIGNMENT_ID, dep.mgr),
        e.ERR_ASSIGNMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_vendor_engagement(c.MISSING_ENGAGEMENT_ID, dep.mgr),
        e.ERR_ENGAGEMENT_NOT_FOUND,
        404,
    )
    triage = api.triage_incident(
        c.MISSING_INCIDENT_ID, f.triage_payload(c.TRACK_SHELTER_IN_PLACE), dep.mgr
    )
    validate_error(triage, e.ERR_INCIDENT_NOT_FOUND, 404)
    a.assert_error_meta_shape(triage)

    _rows, meta = validate_paginated(api.list_vendor_engagements(dep.mgr))
    assert meta["total_count"] == 0, "the refused triage created no engagement"


def test_each_role_carries_out_its_own_exclusive_operations(api, dep):
    """One walk in which all six roles do the work only they are allowed to do.

    PRD §2.1: "Once the headers are accepted, the named role is checked against the set of roles authorised for the target endpoint in §4; a role that is not on that list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/every_role_performs_its_own_exclusive_operations
    """
    # The operator's two exclusive acts already stand behind this fixture: the
    # clock write and the very first staff rows.
    assert fx.read_staff(api, dep, dep.analyst_id)["full_name"] == "Ana Analyst"
    executive = fx.register_executive(api, dep, full_name="Eve Exec")
    assert executive["created_at"] == c.CLOCK_EPOCH_RENDERED

    survey = fx.complete_residential_survey(api, dep, executive["id"])
    assert survey["residential_survey_status"] == c.SURVEY_COMPLETE
    signal = fx.add_exposure_signal(
        api,
        dep,
        executive["id"],
        c.SIGNAL_MEDIA_MENTION,
        3,
        "2026-07-25T00:00:00Z",
    )
    a.assert_append_only_fields(signal)
    rating = fx.publish_rating(api, dep)
    a.assert_decimal_value(
        rating["composite_destination_score"], 9.80, "composite_destination_score"
    )
    assert rating["rating_band"] == c.BAND_LOW

    assessment = fx.draft_assessment(api, dep, executive["id"])
    submitted = fx.submit_assessment(api, dep, assessment["id"])
    assert submitted["status"] == c.ASSESSMENT_SUBMITTED
    approved = fx.review_assessment(
        api, dep, assessment["id"], c.REVIEW_APPROVE, "cleared"
    )
    assert approved["status"] == c.ASSESSMENT_APPROVED
    assert fx.read_executive(api, dep, executive["id"])["threat_level"] == c.THREAT_LOW

    policy = fx.create_policy(api, dep, executive["id"], headers=dep.mgr)
    assert policy["status"] == c.POLICY_UNVERIFIED
    verified = fx.verify_policy(api, dep, policy["id"])
    assert verified["status"] == c.POLICY_VERIFIED
    assert verified["verified_at"] is not None

    trip = fx.create_trip(
        api,
        dep,
        executive["id"],
        approved["id"],
        insurance_policy_id=policy["id"],
    )
    a.assert_trip_states(trip, c.APPROVAL_DRAFT, c.READINESS_NOT_READY)
    leg = fx.add_leg(
        api,
        dep,
        trip["id"],
        arrive_at=c.TRIP_DEPART_AT,
        depart_at=c.TRIP_RETURN_AT,
    )
    assert leg["leg_risk_band"] == c.BAND_LOW

    vendor = fx.register_vendor(
        api,
        dep,
        vendor_name="Lisbon Ground",
        vendor_type=c.VENDOR_GROUND_SECURITY,
        country_code=c.COUNTRY_PT,
    )
    suspended = fx.suspend_vendor(api, dep, vendor["id"], "licence review")
    assert suspended["activation_status"] == c.VENDOR_SUSPENDED_STATUS
    assert suspended["suspension_reason"] == "licence review"

    disclosure = validate_success(
        api.get_perquisite_disclosure(
            executive["id"], u.make_executive_headers(executive["id"])
        )
    )
    assert disclosure["closed_trip_count"] == 0, (
        "the protectee may read their own position before any trip closes"
    )


def test_no_role_can_borrow_another_roles_exclusive_operation(api, dep):
    """Six denials, each from a caller whose only defect is the role header.

    PRD §2.1: "Once the headers are accepted, the named role is checked against the set of roles authorised for the target endpoint in §4; a role that is not on that list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/roles_cannot_perform_other_roles_exclusive_operations
    """
    fx.publish_rating(api, dep)
    executive = fx.register_executive(api, dep)
    fx.complete_residential_survey(api, dep, executive["id"])
    policy = fx.create_policy(api, dep, executive["id"])
    assessment = fx.draft_assessment(api, dep, executive["id"])
    fx.submit_assessment(api, dep, assessment["id"])
    vendor = fx.register_vendor(api, dep)

    validate_error(
        api.create_trip(
            f.trip_payload(executive["id"], dep.analyst_id, assessment["id"]),
            dep.analyst,
        ),
        e.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    validate_error(
        api.suspend_vendor(
            vendor["id"],
            f.vendor_suspend_payload("manager tries to suspend"),
            dep.mgr,
        ),
        e.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    validate_error(
        api.verify_insurance_policy(
            policy["id"],
            f.policy_verify_payload(verification_note="director tries to verify"),
            dep.dir,
        ),
        e.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    validate_error(
        api.review_risk_assessment(
            assessment["id"],
            f.assessment_review_payload(c.REVIEW_APPROVE, review_notes="manager tries"),
            dep.mgr,
        ),
        e.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    validate_error(
        api.create_destination_rating(
            f.destination_rating_payload(country_code=c.COUNTRY_ES), dep.mgr
        ),
        e.ERR_UNAUTHORIZED_ROLE,
        403,
    )
    validate_error(
        api.set_clock(f.clock_payload("2026-08-02T00:00:00Z"), dep.dir),
        e.ERR_UNAUTHORIZED_ROLE,
        403,
    )

    _trips, trip_meta = validate_paginated(api.list_trips(dep.mgr))
    assert trip_meta["total_count"] == 0, "the analyst's create left no trip behind"
    stored_vendor = fx.read_vendor(api, dep, vendor["id"])
    assert stored_vendor["activation_status"] == c.VENDOR_AVAILABLE
    assert stored_vendor["version"] == 1
    policies, _meta = validate_paginated(
        api.list_executive_insurance_policies(executive["id"], dep.officer)
    )
    assert len(policies) == 1
    assert policies[0]["status"] == c.POLICY_UNVERIFIED
    assert policies[0]["verified_at"] is None
    stored_assessment = validate_success(
        api.get_risk_assessment(assessment["id"], dep.analyst)
    )
    assert stored_assessment["status"] == c.ASSESSMENT_SUBMITTED
    validate_error(
        api.update_destination_rating(
            c.COUNTRY_ES,
            f.destination_rating_patch_payload(crime_index=12.0),
            dep.analyst,
        ),
        e.ERR_DESTINATION_RATING_NOT_FOUND,
        404,
    )
    later = fx.register_executive(api, dep, full_name="Tim Timely")
    assert later["created_at"] == c.CLOCK_EPOCH_RENDERED, (
        "the most senior staff role could not move the clock"
    )


def test_a_shared_operation_accepts_every_role_that_declares_it(api, dep):
    """Four operations are declared by two roles each, and both callers succeed.

    PRD §2.1: "`ComplianceOfficer` and `SecurityDirector` callers may read any protectee's perquisite-disclosure position."

    Design: Corner/rbac/shared_operations_succeed_for_each_role_that_declares_them
    """
    by_director = fx.register_staff(
        api, "Ana Second", c.STAFF_ROLE_ANALYST, 9_000, headers=dep.dir
    )
    a.assert_staff_hours(by_director, committed=0, released=0)
    a.assert_common_fields(by_director, expected_version=1)

    exec_a = validate_success(
        api.create_executive(
            f.executive_payload(
                full_name="Eve Exec",
                tier=c.TIER_3,
                base_country_code=c.COUNTRY_US,
                annual_security_budget_cents=100_000_000,
            ),
            dep.mgr,
        ),
        201,
    )
    exec_b = validate_success(
        api.create_executive(
            f.executive_payload(
                full_name="Ivan Insider",
                tier=c.TIER_2,
                role_title="CFO",
                base_country_code=c.COUNTRY_US,
                annual_security_budget_cents=60_000_000,
            ),
            dep.dir,
        ),
        201,
    )
    a.assert_budget_ledger(exec_a, committed=0, spent=0, remaining=100_000_000)
    a.assert_budget_ledger(exec_b, committed=0, spent=0, remaining=60_000_000)

    policy_by_manager = validate_success(
        api.create_insurance_policy(
            f.insurance_policy_payload(
                exec_a["id"],
                policy_type=c.POLICY_KIDNAP_RANSOM,
                coverage_cents=50_000_000,
            ),
            dep.mgr,
        ),
        201,
    )
    policy_by_officer = validate_success(
        api.create_insurance_policy(
            f.insurance_policy_payload(
                exec_b["id"],
                policy_type=c.POLICY_TRAVEL_ACCIDENT,
                coverage_cents=30_000_000,
            ),
            dep.officer,
        ),
        201,
    )
    for policy in (policy_by_manager, policy_by_officer):
        assert policy["status"] == c.POLICY_UNVERIFIED, (
            "creating a policy is shared, verifying it is not"
        )

    vendor_by_manager = validate_success(
        api.create_vendor(
            f.vendor_payload(
                vendor_name="Lisbon Ground",
                vendor_type=c.VENDOR_GROUND_SECURITY,
                country_code=c.COUNTRY_PT,
            ),
            dep.mgr,
        ),
        201,
    )
    vendor_by_director = validate_success(
        api.create_vendor(
            f.vendor_payload(
                vendor_name="Madrid Ground",
                vendor_type=c.VENDOR_GROUND_SECURITY,
                country_code=c.COUNTRY_ES,
                max_concurrent_engagements=1,
                sla_response_minutes=20,
                hourly_rate_cents=9_000,
                retainer_cents=40_000,
            ),
            dep.dir,
        ),
        201,
    )
    for vendor in (vendor_by_manager, vendor_by_director):
        assert vendor["activation_status"] == c.VENDOR_AVAILABLE
        a.assert_vendor_hours(vendor, 0)

    officer_read = validate_success(
        api.get_perquisite_disclosure(exec_a["id"], dep.officer)
    )
    director_read = validate_success(
        api.get_perquisite_disclosure(exec_a["id"], dep.dir)
    )
    assert officer_read["closed_trip_count"] == 0
    assert director_read["closed_trip_count"] == 0
    assert officer_read == director_read, (
        "neither caller owns this protectee, and both may still read the position"
    )


def test_the_author_cannot_review_and_the_trip_creator_cannot_decide(api, dep):
    """Two identity checks against persisted foreign keys, not against the role.

    PRD §2.9: "The staff member who authored a risk assessment may not review it: on the assessment review action, `X-User-ID` must differ from the assessment's `authored_by_staff_id`. The staff member who created a trip may not decide it: on the trip decision action, `X-User-ID` must differ from the trip's `created_by_staff_id`. A violation of either is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/rbac/the_author_cannot_review_and_the_trip_creator_cannot_decide
    """
    fx.publish_rating(api, dep)
    executive = fx.register_executive(api, dep)
    fx.complete_residential_survey(api, dep, executive["id"])
    policy = fx.create_verified_policy(api, dep, executive["id"])
    assessment = fx.draft_assessment(api, dep, executive["id"])
    submitted = fx.submit_assessment(api, dep, assessment["id"])
    assert submitted["authored_by_staff_id"] == dep.analyst_id

    validate_error(
        api.review_risk_assessment(
            assessment["id"],
            f.assessment_review_payload(
                c.REVIEW_APPROVE, review_notes="self-review attempt"
            ),
            u.make_security_director_headers(dep.analyst_id),
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    unchanged = validate_success(
        api.get_risk_assessment(assessment["id"], dep.analyst)
    )
    assert unchanged["status"] == c.ASSESSMENT_SUBMITTED
    assert unchanged["revision_round"] == submitted["revision_round"]
    assert unchanged["approved_by_staff_id"] is None

    approved = fx.review_assessment(
        api, dep, assessment["id"], c.REVIEW_APPROVE, "cleared by a second pair of eyes"
    )
    assert approved["status"] == c.ASSESSMENT_APPROVED
    assert approved["approved_by_staff_id"] == dep.dir_id

    trip = fx.create_trip(
        api,
        dep,
        executive["id"],
        approved["id"],
        insurance_policy_id=policy["id"],
    )
    assert trip["created_by_staff_id"] == dep.mgr_id
    leg = fx.add_leg(
        api, dep, trip["id"], arrive_at=c.TRIP_DEPART_AT, depart_at=c.TRIP_RETURN_AT
    )
    fx.record_advance(api, dep, leg["id"], c.ITEM_ROUTE_SURVEY)
    fx.submit_trip(api, dep, trip["id"])
    fx.ack_briefing(api, executive["id"], trip["id"])

    validate_error(
        api.decide_trip(
            trip["id"],
            f.trip_decision_payload(c.DECISION_APPROVE),
            u.make_security_director_headers(dep.mgr_id),
        ),
        e.ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    a.assert_trip_states(
        fx.read_trip(api, dep, trip["id"]), c.APPROVAL_PENDING_REVIEW
    )

    decided = fx.decide_trip(api, dep, trip["id"], c.DECISION_APPROVE)
    a.assert_trip_states(decided, c.APPROVAL_APPROVED)


def test_an_executive_cannot_read_or_act_on_another_protectees_records(api):
    """Ownership is compared against the path id and against the trip's own protectee.

    PRD §2.1: "An `Executive` caller who addresses a protectee or a trip that is not their own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/an_executive_cannot_read_or_act_on_another_protectees_records
    """
    w = fx.trip_world(api)
    dep = w.dep
    fx.submit_trip(api, dep, w.trip_id)
    intruder = fx.register_executive(api, dep, full_name="Ivan Insider")
    intruder_headers = u.make_executive_headers(intruder["id"])
    # The owner's row has legitimately advanced since registration (survey,
    # assessment approval, submission commitment); pin the version as it stands
    # immediately before the intruder's refused writes.
    version_before = fx.read_executive(api, dep, w.exec_id)["version"]

    validate_error(
        api.get_executive(w.exec_id, intruder_headers), e.ERR_NOT_RESOURCE_OWNER, 403
    )
    validate_error(
        api.patch_executive_consent(
            w.exec_id,
            f.consent_payload(consent_scope=c.CONSENT_TRIP_ONLY),
            intruder_headers,
        ),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api.get_perquisite_disclosure(w.exec_id, intruder_headers),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api.acknowledge_briefing(w.trip_id, intruder_headers),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api.create_check_in(
            w.trip_id,
            f.check_in_payload(
                kind=c.CHECK_IN_AD_HOC,
                location_country_code=c.COUNTRY_PT,
                note="not my trip",
            ),
            intruder_headers,
        ),
        e.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    owner_row = fx.read_executive(api, dep, w.exec_id)
    assert owner_row["consent_scope"] == c.CONSENT_NONE
    assert owner_row["version"] == version_before, (
        "a refused consent revision must not mutate the protectee's row"
    )
    blocked_trip = fx.read_trip(api, dep, w.trip_id)
    assert blocked_trip["briefing_ack_at"] is None
    _rows, meta = validate_paginated(api.list_check_ins(w.trip_id, dep.mgr))
    assert meta["total_count"] == 0, "the refused check-in persisted no row"

    own_read = validate_success(api.get_executive(w.exec_id, w.exec_headers))
    assert own_read["consent_scope"] == c.CONSENT_NONE
    own_ack = validate_success(api.acknowledge_briefing(w.trip_id, w.exec_headers))
    assert own_ack["briefing_ack_at"] == c.CLOCK_EPOCH_RENDERED
    a.assert_trip_states(own_ack, c.APPROVAL_PENDING_REVIEW)
