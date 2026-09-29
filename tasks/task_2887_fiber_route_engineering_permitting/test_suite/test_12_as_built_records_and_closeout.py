"""Closing the network records.

The as-built filing is the last artifact a route produces, and two rules decide
whether it can be signed: the length variance against the drawing must sit inside
five percent, and the engineer who sealed that drawing may not be the engineer who
swears the field matched it. Both rules are asymmetric — they guard the accepting
branch only — and acceptance is the route's terminal hop.
"""

from test_helpers import USER_IDS, fixtures as fx, validate_error, validate_success
from test_helpers.factories import certify_payload, create_as_built_record_payload

_INLAND_SPUR = {
    "name": "Inland Spur",
    "topology_objective": "SPUR",
    "target_in_service_date": "2027-06-01",
    "budget_authorized_cents": 250000000,
}


def _construction_ready_inland_spur(submitter=None, stamper=None):
    """A CONSTRUCTION_READY 400-foot route with revision 1 stamped by a second engineer."""

    fx.set_clock("2026-08-10T00:00:00Z")
    built = fx.construction_ready_route(
        route_overrides=dict(_INLAND_SPUR), submitter=submitter, stamper=stamper
    )
    return {
        "route_id": built["route"]["id"],
        "segment_id": built["segments"][0]["id"],
        "design": built["design"],
        "route": built["route"],
    }


def _filed_as_built(as_built_length_feet, **overrides):
    """One SUBMITTED as-built on a construction-ready route, at the given field length."""

    built = _construction_ready_inland_spur()
    assert built["route"]["design_total_length_feet"] == 400
    built["as_built"] = fx.create_as_built(
        built["route_id"],
        design_revision=1,
        as_built_length_feet=as_built_length_feet,
        splice_point_count_field_verified=1,
        records_system_reference="OSP-2026-0418",
        **overrides,
    )
    return built


def test_a_variance_of_exactly_five_hundred_basis_points_may_still_be_certified(
    api, engineer_third_headers
):
    """420 field feet against 400 designed feet is 500 basis points, and 500 passes.

    PRD: "A variance of exactly 500 basis points is acceptable and passes; strictly
    above 500 is refused with `ERR_AS_BUILT_VARIANCE_EXCEEDED`."

    Design: Corner/calculations/as_built_variance_at_exactly_500_basis_points_is_accepted
    """
    built = _filed_as_built(420)
    record = built["as_built"]
    assert record["length_variance_bp"] == 500
    assert record["status"] == "SUBMITTED"

    accepted = validate_success(
        api.certify_as_built_record(
            record["id"],
            certify_payload(
                "ACCEPTED", certification_note="20 feet of extra slack at the vault"
            ),
            headers=engineer_third_headers,
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["certified_by_user_id"] == USER_IDS["route_engineer_third"]

    route = fx.read_route(built["route_id"])
    assert route["status"] == "RECORDS_UPDATED"
    assert route["design_total_length_feet"] == 400, (
        "the designed total is the drawing's figure and the as-built never overwrites it"
    )


def test_one_more_foot_puts_the_variance_past_the_cap_but_rejection_still_lands(
    api, engineer_third_headers
):
    """421 feet scores 525 basis points, so ACCEPTED is refused and REJECTED is not.

    PRD: "**Rejection** moves the record `SUBMITTED → REJECTED`, which is equally
    terminal, and applies no variance check at all — an engineer may reject a filing
    whose numbers are perfectly within tolerance for reasons the numbers do not
    capture."

    Design: Corner/validations/as_built_certify_with_variance_above_the_cap_returns_variance_exceeded
    """
    built = _filed_as_built(421)
    record = built["as_built"]
    assert record["length_variance_bp"] == 525

    refused = api.certify_as_built_record(
        record["id"],
        certify_payload("ACCEPTED", certification_note="field length 421"),
        headers=engineer_third_headers,
    )
    validate_error(refused, "ERR_AS_BUILT_VARIANCE_EXCEEDED", 422)

    still_open = fx.read_as_built(record["id"])
    assert still_open["status"] == "SUBMITTED"
    assert still_open["certified_by_user_id"] is None
    assert fx.read_route(built["route_id"])["status"] == "CONSTRUCTION_READY"

    rejected = validate_success(
        api.certify_as_built_record(
            record["id"],
            certify_payload("REJECTED", certification_note="resurvey the slack loops"),
            headers=engineer_third_headers,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert fx.read_route(built["route_id"])["status"] == "CONSTRUCTION_READY", (
        "a rejected filing leaves the route open rather than closing it"
    )


def test_filing_against_a_revision_that_was_never_stamped_is_refused(
    api, surveyor_headers, engineer_headers
):
    """Revision 1 is stamped and revision 2 is a draft, so citing 2 is a 422.

    PRD: "It also requires that a design package on that route with `revision` equal
    to the supplied `design_revision` actually be at `STAMPED` — filing against a
    revision number that never existed, or against one whose stamp was voided by a
    permit denial or superseded by a later revision, is refused with
    `ERR_DESIGN_NOT_STAMPED`."

    Design: Corner/validations/as_built_create_for_an_unstamped_revision_returns_design_not_stamped
    """
    built = _construction_ready_inland_spur()
    stamped = built["design"]
    assert stamped["revision"] == 1
    assert stamped["status"] == "STAMPED"

    draft = fx.create_design(
        built["route_id"], headers=engineer_headers, fiber_count_allocated=288, express_fiber_count=48
    )
    assert draft["revision"] == 2
    assert draft["status"] == "DRAFT"

    refused = api.create_as_built_record(
        create_as_built_record_payload(
            built["route_id"],
            design_revision=2,
            as_built_length_feet=400,
            splice_point_count_field_verified=1,
            records_system_reference="OSP-2026-0418",
        ),
        headers=surveyor_headers,
    )
    validate_error(refused, "ERR_DESIGN_NOT_STAMPED", 422)

    rows = validate_success(
        api.list_route_as_built_records(built["route_id"], headers=surveyor_headers)
    )
    assert rows == []
    assert fx.read_route(built["route_id"])["status"] == "CONSTRUCTION_READY"

    accepted_revision = validate_success(
        api.create_as_built_record(
            create_as_built_record_payload(
                built["route_id"],
                design_revision=1,
                as_built_length_feet=400,
                splice_point_count_field_verified=1,
                records_system_reference="OSP-2026-0419",
            ),
            headers=surveyor_headers,
        ),
        201,
    )
    assert accepted_revision["design_revision"] == 1, (
        "the revision number, not the route status, is what the gate objects to"
    )


def test_a_certified_record_is_terminal_and_a_second_decision_is_refused(
    api, engineer_third_headers, engineer_fourth_headers
):
    """ACCEPTED admits no reversal, and the first certifier stays on the row.

    PRD: "Certification requires the record at `SUBMITTED`; a second decision on an
    already-decided record is `ERR_INVALID_AS_BUILT_STATE`, since both outcomes are
    terminal."

    Design: Corner/state_machines/as_built_certify_from_accepted_returns_invalid_as_built_state
    """
    built = _filed_as_built(400)
    record = built["as_built"]
    assert record["length_variance_bp"] == 0
    assert record["submitted_by_user_id"] == USER_IDS["field_surveyor"]

    validate_success(
        api.certify_as_built_record(
            record["id"],
            certify_payload("ACCEPTED", certification_note="records updated"),
            headers=engineer_third_headers,
        )
    )

    second = api.certify_as_built_record(
        record["id"],
        certify_payload("REJECTED", certification_note="changed my mind"),
        headers=engineer_fourth_headers,
    )
    validate_error(second, "ERR_INVALID_AS_BUILT_STATE", 409)

    unchanged = fx.read_as_built(record["id"])
    assert unchanged["status"] == "ACCEPTED"
    assert unchanged["certified_by_user_id"] == USER_IDS["route_engineer_third"]
    assert unchanged["length_variance_bp"] == 0
    assert fx.read_route(built["route_id"])["status"] == "RECORDS_UPDATED"


def test_the_engineer_who_stamped_the_drawing_cannot_certify_the_as_built(
    api, engineer_alt_headers, engineer_third_headers
):
    """The duty bar reaches across entities from the stamp to the certification.

    PRD: "Both outcomes are guarded by the **second segregation-of-duties rule**,
    and it fires identically on each: the certifying engineer's `X-User-ID` must
    differ from the `stamped_by_user_id` of the design package on this route whose
    `revision` equals the record's `design_revision`."

    Design: Corner/rbac/as_built_certify_by_the_stamping_engineer_returns_segregation_of_duties
    """
    built = _filed_as_built(400)
    record = built["as_built"]
    assert built["design"]["stamped_by_user_id"] == USER_IDS["route_engineer_second"]
    assert record["submitted_by_user_id"] == USER_IDS["field_surveyor"]
    assert record["length_variance_bp"] == 0

    self_certified = api.certify_as_built_record(
        record["id"],
        certify_payload("ACCEPTED", certification_note="stamper self-certifying"),
        headers=engineer_alt_headers,
    )
    validate_error(self_certified, "ERR_SEGREGATION_OF_DUTIES", 403)

    untouched = fx.read_as_built(record["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["certified_by_user_id"] is None
    assert fx.read_route(built["route_id"])["status"] == "CONSTRUCTION_READY"

    accepted = validate_success(
        api.certify_as_built_record(
            record["id"],
            certify_payload("ACCEPTED", certification_note="records updated"),
            headers=engineer_third_headers,
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["certified_by_user_id"] == USER_IDS["route_engineer_third"]
    assert fx.read_route(built["route_id"])["status"] == "RECORDS_UPDATED"
