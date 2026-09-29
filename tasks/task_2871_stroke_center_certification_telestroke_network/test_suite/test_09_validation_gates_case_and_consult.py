"""Validation gates on the case, the checklist, the consult and the transfer.

Every test here turns on the ordered ladder of PRD 2.11: the two header gates
and the role gate, consult ownership, request shape and pagination bounds, the
checklist gates that surround a determination, the window recomputation applied
at administration, the transfer mode and destination guards, and the network
rules that police an agreement, a proxy credential grant and the concurrent
consult ceiling.
"""
import uuid

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import PAGINATION, REQUIRED_INCLUSION_ITEM_CODES
from test_helpers.test_users import COORD, ED, TRANSFER, make_neurologist_headers


def _unique_region():
    """An `ems_region_code` no other test in the session shares, for list filters."""
    return f"R-{uuid.uuid4().hex[:8].upper()}"


def _headers_without_user_id(role):
    """Well-formed headers with `X-User-ID` omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def _documented_checklist_case(door_at, *, relative=0, absolute=0, item_codes=None):
    """A CONSULT_IN_PROGRESS case whose checklist is documented but not determined."""
    context = fx.setup_network(clock=door_at)
    built = fx.setup_case_with_completed_consult(context, door_at)
    checklist = fx.setup_documented_checklist(
        built["case"]["id"],
        item_codes=item_codes,
        relative_contraindications=relative,
        absolute_contraindications=absolute,
    )
    return context, built["case"], checklist


def _three_centers_in_one_region():
    """Three facilities sharing one `ems_region_code`, so a filtered page is exact."""
    region = _unique_region()
    centers = []
    for minute in range(3):
        fx.set_clock(fx.shift("2026-09-01T08:00:00Z", minutes=minute))
        centers.append(fx.register_center(ems_region_code=region))
    return region, centers


def _list_centers_in_region(region, params):
    query = {"ems_region_code": region}
    query.update(params)
    return api_client.list_stroke_centers(COORD, query)


def _determine_response(checklist_id, neurologist_id, *, at=None, override_justification=None):
    """The raw determination response, so a refusal can be inspected."""
    if at is not None:
        fx.set_clock(at)
    payload = f.determine_payload()
    if override_justification is not None:
        payload["override_justification"] = override_justification
    return api_client.determine_checklist(
        checklist_id,
        headers=make_neurologist_headers(neurologist_id),
        payload=payload,
    )


def _determine(checklist_id, neurologist_id, *, at=None, override_justification=None):
    """Attest a checklist as the assigned neurologist and return the updated row."""
    return validate_success(
        _determine_response(
            checklist_id, neurologist_id,
            at=at, override_justification=override_justification,
        )
    )


def _eligible_case(
    context,
    door_at,
    *,
    dti_minutes=20,
    determine_at=None,
    relative=0,
    absolute=0,
    override_justification=None,
    lkw_precision="EXACT",
    last_known_well_at=None,
):
    """A case at ELIGIBILITY_DETERMINED with a documented, determined checklist."""
    built = fx.setup_case_with_completed_consult(
        context, door_at,
        lkw_precision=lkw_precision, last_known_well_at=last_known_well_at,
    )
    case_id = built["case"]["id"]
    imaging_at = fx.shift(door_at, minutes=dti_minutes)
    fx.complete_imaging(case_id, at=imaging_at)
    checklist = fx.setup_documented_checklist(
        case_id, relative_contraindications=relative, absolute_contraindications=absolute
    )
    checklist = _determine(
        checklist["id"], context["neurologist"]["id"],
        at=determine_at or imaging_at,
        override_justification=override_justification,
    )
    return {"case": fx.read_case(case_id), "checklist": checklist, "consult": built["consult"]}


def test_writes_missing_the_user_id_header_are_unauthenticated_before_anything_else():
    """Two writes, one of them also carrying a bad enum, both stop at the header gate.

    PRD 2.1: "If either header is missing or empty, or if `X-User-Role` carries a value outside the six role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.11: "the response is determined by the highest-precedence rule violated, not by the order in which an implementation happens to run its checks"

    Design: Corner/validations/every_write_missing_the_x_user_id_header_is_unauthenticated
    """
    fx.set_clock("2026-09-01T08:00:00Z")
    region = _unique_region()
    center = fx.register_center(ems_region_code=region)

    first = validate_error(
        api_client.register_stroke_center(
            f.register_center_payload(ems_region_code=region),
            _headers_without_user_id("ProgramCoordinator"),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    second = validate_error(
        api_client.activate_code_stroke(
            f.code_stroke_payload(
                center["id"], "2026-09-01T08:00:00Z",
                last_known_well_at="2026-09-01T07:40:00Z",
                arrival_mode="AMBULANCE",
            ),
            _headers_without_user_id("EdPhysician"),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )

    assert first["error_id"] == second["error_id"], (
        "both refusals carry the same identifier, got "
        f"{first['error_id']} and {second['error_id']}"
    )
    assert second["error_id"] != ApiErrorId.ERR_INVALID_ENUM_VALUE.value, (
        "the undeclared arrival_mode is never reached because the header rule outranks the "
        f"enum rule, got {second['error_id']}"
    )

    centers, center_meta = validate_paginated(
        _list_centers_in_region(region, {"limit": 10, "offset": 0})
    )
    assert center_meta["total_count"] == 1, (
        "only the authenticated registration exists in this region, got "
        f"{center_meta['total_count']}"
    )
    assert [row["id"] for row in centers] == [center["id"]]

    cases, case_meta = validate_paginated(
        api_client.list_code_strokes(COORD, {"center_id": center["id"], "limit": 10, "offset": 0})
    )
    assert case_meta["total_count"] == 0, (
        f"the unauthenticated activation created no case, got {case_meta['total_count']}"
    )
    assert cases == []


def test_an_undeclared_role_is_unauthenticated_while_a_real_wrong_role_is_forbidden():
    """The same body three ways: an invented role, a declared but unauthorised role, then the owner.

    PRD 2.1: "If either header is missing or empty, or if `X-User-Role` carries a value outside the six role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.1: "When the headers are well formed but the named role is not authorised for the endpoint being called, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/validations/an_undeclared_role_name_is_unauthenticated_while_a_declared_wrong_role_is_forbidden
    """
    door_at = "2026-09-01T08:00:00Z"
    fx.set_clock(door_at)
    center = fx.register_center()
    payload = f.code_stroke_payload(
        center["id"], door_at, last_known_well_at="2026-09-01T07:40:00Z"
    )

    invented = api_client.activate_code_stroke(
        payload, {"X-User-ID": "ed-physician-001", "X-User-Role": "StrokeChampion"}
    )
    unrecognised = validate_error(invented, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert invented.status_code == 401, (
        f"an undeclared role name is an authentication failure, got {invented.status_code}"
    )

    wrong_role = api_client.activate_code_stroke(
        payload, {"X-User-ID": "quality-abstractor-001", "X-User-Role": "QualityAbstractor"}
    )
    forbidden = validate_error(wrong_role, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert wrong_role.status_code == 403, (
        f"a real role that is not authorised here is a 403, got {wrong_role.status_code}"
    )
    assert unrecognised["error_id"] != forbidden["error_id"], (
        "the two refusals differ in identifier as well as status, got "
        f"{unrecognised['error_id']} twice"
    )

    _, meta = validate_paginated(
        api_client.list_code_strokes(COORD, {"center_id": center["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, (
        f"neither refusal created a case, got {meta['total_count']}"
    )

    created = validate_success(api_client.activate_code_stroke(payload, ED), 201)
    assert created["status"] == "ACTIVATED", (
        f"the identical body from an EdPhysician is accepted, got {created['status']}"
    )
    assert created["center_id"] == center["id"]


def test_a_peer_neurologist_cannot_accept_decline_or_determine_someone_elses_consult():
    """Three ownership-gated calls from the unassigned neurologist, all 403, then the assignee succeeds.

    PRD 2.1: "A `Neurologist` who is not the assignee is rejected with `ERR_NOT_CONSULT_OWNER` (HTTP 403)"
    PRD 3.5: "The caller must be the neurologist assigned to a consult on this case whose `status` is `IN_SESSION` or `COMPLETED` and whose `valid_video_session_count` is 1 or more; anyone else gets `ERR_NOT_CONSULT_OWNER`."

    Design: Corner/validations/a_second_neurologist_cannot_accept_a_consult_assigned_to_a_peer
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(
        clock=door_at, neurologists=[{"roster_rank": 10}, {"roster_rank": 20}]
    )
    assignee, intruder = context["neurologists"]
    case = fx.activate_case(context["spoke"]["id"], door_at)
    fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    consult = fx.request_consult(
        case["id"], context["agreement"]["id"], at="2026-09-01T08:15:00Z"
    )
    assert consult["assigned_neurologist_id"] == assignee["id"], (
        "the roster_rank 10 neurologist is selected, got "
        f"{consult['assigned_neurologist_id']}"
    )
    checklist = fx.create_checklist(case["id"])
    intruder_headers = make_neurologist_headers(intruder["id"])

    fx.set_clock("2026-09-01T08:16:00Z")
    refused_accept = validate_error(
        api_client.accept_consult(consult["id"], intruder_headers),
        ApiErrorId.ERR_NOT_CONSULT_OWNER.value, 403,
    )
    refused_decline = validate_error(
        api_client.decline_consult(
            consult["id"], f.decline_consult_payload(), intruder_headers
        ),
        ApiErrorId.ERR_NOT_CONSULT_OWNER.value, 403,
    )
    refused_determine = validate_error(
        api_client.determine_checklist(
            checklist["id"], headers=intruder_headers, payload=f.determine_payload()
        ),
        ApiErrorId.ERR_NOT_CONSULT_OWNER.value, 403,
    )
    for refusal in (refused_accept, refused_decline, refused_determine):
        assert refusal["error_id"] == ApiErrorId.ERR_NOT_CONSULT_OWNER.value, (
            f"ownership is checked before state or documentation, got {refusal['error_id']}"
        )
    assert refused_determine["error_id"] != ApiErrorId.ERR_CHECKLIST_INCOMPLETE.value, (
        "the empty checklist is never inspected because ownership outranks it"
    )

    untouched = fx.read_consult(consult["id"])
    assert untouched["status"] == "ASSIGNED", (
        f"the intruder's calls left the consult assigned, got {untouched['status']}"
    )
    assert untouched["assigned_neurologist_id"] == assignee["id"]
    assert untouched["decline_count"] == 0, (
        f"the intruder's decline did not count, got {untouched['decline_count']}"
    )

    accepted = fx.accept_consult(consult["id"], assignee["id"], at="2026-09-01T08:17:00Z")
    assert accepted["status"] == "IN_SESSION", (
        f"the rightful assignee opens the session, got {accepted['status']}"
    )
    assert a.instants_equal(accepted["accepted_at"], "2026-09-01T08:17:00Z"), (
        f"accepted_at is stamped from the logical clock, got {accepted['accepted_at']}"
    )


def test_pagination_outside_the_declared_bounds_is_rejected_on_a_list_endpoint():
    """A zero limit, a limit of 101 and a negative offset are all the same refusal.

    PRD 2.3: "A `limit` or `offset` outside those bounds, or one that is not an integer, is rejected with `ERR_INVALID_PAGINATION` (HTTP 422)."
    PRD 2.3: "it defaults to 10 when omitted, and an explicitly supplied value must be an integer no smaller than 1 and no larger than 100"

    Design: Corner/validations/list_endpoints_reject_out_of_range_pagination_and_admit_the_bounds
    """
    region, centers = _three_centers_in_one_region()
    assert len(centers) == 3

    below = validate_error(
        _list_centers_in_region(region, {"limit": 0, "offset": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value, 422,
    )
    above = validate_error(
        _list_centers_in_region(region, {"limit": 101, "offset": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value, 422,
    )
    negative = validate_error(
        _list_centers_in_region(region, {"limit": 10, "offset": -1}),
        ApiErrorId.ERR_INVALID_PAGINATION.value, 422,
    )

    assert below["error_id"] == above["error_id"] == negative["error_id"], (
        "one identifier covers a limit below the floor, a limit above the ceiling and a "
        f"negative offset, got {below['error_id']}, {above['error_id']}, {negative['error_id']}"
    )
    assert PAGINATION["MIN_LIMIT"] == 1 and PAGINATION["MAX_LIMIT"] == 100, (
        "the refused values sit exactly one step outside the declared range, got "
        f"{PAGINATION['MIN_LIMIT']} and {PAGINATION['MAX_LIMIT']}"
    )


def test_pagination_admits_both_ends_of_the_declared_limit_range():
    """A limit of exactly 1 and a limit of exactly 100 are both inside the range.

    PRD 2.3: "it defaults to 10 when omitted, and an explicitly supplied value must be an integer no smaller than 1 and no larger than 100"
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope"

    Design: Corner/validations/list_endpoints_reject_out_of_range_pagination_and_admit_the_bounds
    """
    region, centers = _three_centers_in_one_region()

    page, meta = validate_paginated(
        _list_centers_in_region(region, {"limit": PAGINATION["MIN_LIMIT"], "offset": 0})
    )
    assert len(page) == 1, f"a limit of 1 returns exactly one record, got {len(page)}"
    assert meta["limit"] == 1
    assert meta["total_count"] == 3, (
        f"total_count counts the whole filtered set, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, (
        f"two records remain beyond the first page, got {meta['has_more']}"
    )
    assert page[0]["id"] == centers[0]["id"], (
        f"the earliest created_at leads the page, got {page[0]['id']}"
    )

    full, full_meta = validate_paginated(
        _list_centers_in_region(region, {"limit": PAGINATION["MAX_LIMIT"], "offset": 0})
    )
    assert len(full) == 3, f"a limit of 100 is admitted and returns all three, got {len(full)}"
    assert full_meta["limit"] == 100
    assert full_meta["total_count"] == 3
    assert full_meta["has_more"] is False, (
        f"nothing remains beyond a page of 100, got {full_meta['has_more']}"
    )
    assert full[0]["id"] == centers[0]["id"], (
        f"both admitted limits open on the same record, got {full[0]['id']}"
    )
    assert [row["id"] for row in full] == [row["id"] for row in centers], (
        "the page is ordered by created_at ascending, got "
        f"{[row['id'] for row in full]}"
    )


def test_an_unknown_body_field_is_rejected_rather_than_silently_dropped():
    """A server-assigned field supplied by the caller fails the request-shape rule.

    PRD 2.11: "The body must contain every required input field of the endpoint with the declared JSON type, must not contain unknown fields"
    PRD 3.1: "Everything else about a new facility is server-assigned: `certification_status` begins at `PROVISIONAL`, both `ct_scanner_ready` and `video_cart_ready` begin true"

    Design: Corner/validations/an_unknown_field_in_the_body_is_rejected_rather_than_ignored
    """
    fx.set_clock("2026-09-01T08:00:00Z")
    region = _unique_region()

    refused = validate_error(
        api_client.register_stroke_center(
            f.register_center_payload(
                ems_region_code=region, certification_status="CERTIFIED"
            ),
            COORD,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value, 422,
    )
    assert refused["error_id"] == ApiErrorId.ERR_INVALID_REQUEST.value

    _, meta = validate_paginated(_list_centers_in_region(region, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, (
        "the unknown key was not merely dropped: nothing was created, got "
        f"{meta['total_count']}"
    )

    accepted = validate_success(
        api_client.register_stroke_center(
            f.register_center_payload(ems_region_code=region), COORD
        ),
        201,
    )
    assert accepted["certification_status"] == "PROVISIONAL", (
        "the same body without the extra key is accepted and the status is server-assigned, got "
        f"{accepted['certification_status']}"
    )
    assert accepted["ems_region_code"] == region


def test_determination_is_refused_until_the_fourth_inclusion_item_is_confirmed():
    """Three items leave the attested variant unrun; the fourth unblocks the identical call.

    PRD 3.5: "`confirmed_inclusion_item_count` must equal 4, otherwise `ERR_CHECKLIST_INCOMPLETE` — and this check runs before the score is computed at all, since a score over incomplete documentation is meaningless."
    PRD 3.2: "sets `status` to `ACTIVATED`, sets `disposition` to `PENDING`, sets `deviation_count` to 0, and classifies the case's `thrombolytic_window_class` immediately"

    Design: Corner/validations/determination_is_blocked_until_all_four_inclusion_items_are_documented
    """
    door_at = "2026-09-01T08:00:00Z"
    context, case, checklist = _documented_checklist_case(
        door_at, item_codes=REQUIRED_INCLUSION_ITEM_CODES[:3]
    )
    neurologist_id = context["neurologist"]["id"]

    assert checklist["confirmed_inclusion_item_count"] == 3, (
        f"three of the four required items are documented, got {checklist['confirmed_inclusion_item_count']}"
    )
    assert checklist["screening_eligibility_score"] == 45.00, (
        "15.0 for each of three items is 45.00 under the screening variant, got "
        f"{checklist['screening_eligibility_score']}"
    )

    refused = validate_error(
        _determine_response(checklist["id"], neurologist_id, at="2026-09-01T08:25:00Z"),
        ApiErrorId.ERR_CHECKLIST_INCOMPLETE.value, 422,
    )
    assert refused["error_id"] == ApiErrorId.ERR_CHECKLIST_INCOMPLETE.value

    blocked = fx.read_checklist(checklist["id"])
    assert blocked["attested_eligibility_score"] is None, (
        "the attested variant never ran, so nothing was scored, got "
        f"{blocked['attested_eligibility_score']}"
    )
    assert blocked["determination_status"] == "PENDING", (
        f"the verdict dimension has not moved, got {blocked['determination_status']}"
    )
    assert blocked["documentation_status"] == "IN_PROGRESS", (
        f"three items leave the documentation dimension in progress, got {blocked['documentation_status']}"
    )
    assert blocked["determined_at"] is None
    assert blocked["screening_eligibility_score"] == 45.00, (
        "the refusal leaves the screening figure exactly as documentation left it, got "
        f"{blocked['screening_eligibility_score']}"
    )

    stalled = fx.read_case(case["id"])
    assert stalled["status"] == "CONSULT_IN_PROGRESS", (
        f"the case did not advance out of the consult, got {stalled['status']}"
    )
    assert stalled["thrombolytic_window_class"] == "WITHIN_3H", (
        "the class classified at activation survives the refused determination, got "
        f"{stalled['thrombolytic_window_class']}"
    )

    fx.confirm_item(checklist["id"], REQUIRED_INCLUSION_ITEM_CODES[3])
    determined = _determine(checklist["id"], neurologist_id, at="2026-09-01T08:26:00Z")

    assert determined["confirmed_inclusion_item_count"] == 4
    assert determined["attested_eligibility_score"] == 66.00, (
        "60.00 with no window penalty plus the 6.0 board credit is 66.00, got "
        f"{determined['attested_eligibility_score']}"
    )
    assert determined["determination_status"] == "ELIGIBLE", (
        f"the identical call now succeeds, got {determined['determination_status']}"
    )
    assert fx.read_case(case["id"])["status"] == "ELIGIBILITY_DETERMINED"


def test_a_relative_contraindication_makes_the_override_justification_mandatory():
    """One relative contraindication: the determination is refused without a justification and lands the override verdict with one.

    PRD 3.5: "`override_justification` is required if and only if `relative_contraindication_count` is greater than 0: omitting it with relative contraindications present and supplying it with none are both `ERR_OVERRIDE_JUSTIFICATION_REQUIRED`."
    PRD 3.5: "otherwise if `relative_contraindication_count` is 1 or more, the attested score is 40.0 or higher and an `override_justification` was supplied, the verdict is `ELIGIBLE_WITH_RELATIVE_OVERRIDE`"

    Design: Corner/validations/override_justification_is_required_exactly_when_a_relative_contraindication_exists
    """
    door_at = "2026-09-01T08:00:00Z"
    context, case, checklist = _documented_checklist_case(door_at, relative=1)
    neurologist_id = context["neurologist"]["id"]
    assert checklist["relative_contraindication_count"] == 1
    assert checklist["screening_eligibility_score"] == 48.00, (
        f"15.0*4 minus 12.0 is 48.00, got {checklist['screening_eligibility_score']}"
    )

    refused = validate_error(
        _determine_response(checklist["id"], neurologist_id, at="2026-09-01T09:30:00Z"),
        ApiErrorId.ERR_OVERRIDE_JUSTIFICATION_REQUIRED.value, 422,
    )
    assert refused["error_id"] == ApiErrorId.ERR_OVERRIDE_JUSTIFICATION_REQUIRED.value

    untouched = fx.read_checklist(checklist["id"])
    assert untouched["determination_status"] == "PENDING", (
        f"the refused determination wrote no verdict, got {untouched['determination_status']}"
    )
    assert untouched["determined_at"] is None, (
        f"determined_at stays null after the refusal, got {untouched['determined_at']}"
    )
    assert untouched["attested_eligibility_score"] is None
    assert fx.read_case(case["id"])["status"] == "CONSULT_IN_PROGRESS", (
        "the refused determination did not advance the case"
    )

    justification = "large vessel syndrome outweighs the elevated INR; hematology agrees"
    determined = _determine(
        checklist["id"], neurologist_id,
        at="2026-09-01T09:31:00Z", override_justification=justification,
    )
    assert determined["determination_status"] == "ELIGIBLE_WITH_RELATIVE_OVERRIDE", (
        "an attested 54.00 at or above 40.0 with a justification takes the override verdict, got "
        f"{determined['determination_status']}"
    )
    assert determined["attested_eligibility_score"] == 54.00, (
        "48.00 with no window penalty plus the 6.0 board credit is 54.00, got "
        f"{determined['attested_eligibility_score']}"
    )
    assert determined["override_justification"] == justification, (
        f"the stored justification echoes the request, got {determined['override_justification']}"
    )
    assert determined["overridden_by_neurologist_id"] == neurologist_id, (
        f"the acting neurologist is recorded, got {determined['overridden_by_neurologist_id']}"
    )


def test_an_override_justification_with_no_relative_contraindication_is_refused():
    """The reverse direction of the biconditional: supplying the justification unasked is equally invalid.

    PRD 3.5: "`override_justification` is required if and only if `relative_contraindication_count` is greater than 0: omitting it with relative contraindications present and supplying it with none are both `ERR_OVERRIDE_JUSTIFICATION_REQUIRED`."
    PRD 3.5: "Both variants clamp the result into the range 0 through 100 and then round to two decimals half up, per §2.6."

    Design: Corner/validations/override_justification_is_required_exactly_when_a_relative_contraindication_exists
    """
    door_at = "2026-09-01T08:00:00Z"
    context, case, checklist = _documented_checklist_case(door_at)
    neurologist_id = context["neurologist"]["id"]
    assert checklist["relative_contraindication_count"] == 0
    assert checklist["absolute_contraindication_count"] == 0
    assert checklist["screening_eligibility_score"] == 60.00, (
        f"four items and nothing against them screen at 60.00, got {checklist['screening_eligibility_score']}"
    )

    refused = validate_error(
        _determine_response(
            checklist["id"], neurologist_id, at="2026-09-01T09:30:00Z",
            override_justification="clinician judgement favours treatment",
        ),
        ApiErrorId.ERR_OVERRIDE_JUSTIFICATION_REQUIRED.value, 422,
    )
    assert refused["error_id"] == ApiErrorId.ERR_OVERRIDE_JUSTIFICATION_REQUIRED.value, (
        "an unnecessary justification trips the same identifier as a missing one, got "
        f"{refused['error_id']}"
    )

    untouched = fx.read_checklist(checklist["id"])
    assert untouched["determination_status"] == "PENDING"
    assert untouched["override_justification"] is None, (
        f"the refused body was not stored, got {untouched['override_justification']}"
    )
    assert untouched["determined_at"] is None
    assert fx.read_case(case["id"])["status"] == "CONSULT_IN_PROGRESS"

    determined = _determine(checklist["id"], neurologist_id, at="2026-09-01T09:31:00Z")
    assert determined["determination_status"] == "ELIGIBLE", (
        f"the same call without the justification succeeds, got {determined['determination_status']}"
    )
    assert determined["attested_eligibility_score"] == 66.00, (
        "60.00 with no window penalty plus the 6.0 board credit is 66.00, got "
        f"{determined['attested_eligibility_score']}"
    )
    assert determined["override_justification"] is None, (
        f"no justification was supplied or invented, got {determined['override_justification']}"
    )
    assert determined["overridden_by_neurologist_id"] is None, (
        "nothing was overridden, so no neurologist is recorded there, got "
        f"{determined['overridden_by_neurologist_id']}"
    )


def test_a_bare_absolute_contraindication_is_refused_before_any_mutation():
    """Nothing is appended, no counter moves and no deviation is opened by the refusal.

    PRD 3.5: "An `ABSOLUTE` entry must carry non-empty `documented_evidence` — a `RELATIVE` one need not — and a bare `ABSOLUTE` entry is rejected with `ERR_CONTRAINDICATION_EVIDENCE_REQUIRED` **before any mutation happens**: nothing is appended, no count moves, and in particular no `MISSING_CONTRAINDICATION_DOC` deviation is created."

    Design: Corner/validations/an_absolute_contraindication_without_documented_evidence_is_rejected
    """
    door_at = "2026-09-01T08:00:00Z"
    _, case, checklist = _documented_checklist_case(door_at)
    assert checklist["screening_eligibility_score"] == 60.00

    fx.set_clock("2026-09-01T08:25:00Z")
    refused = validate_error(
        api_client.document_contraindication(
            checklist["id"],
            f.contraindication_payload("CI_RECENT_INTRACRANIAL_SURGERY", "ABSOLUTE"),
            ED,
        ),
        ApiErrorId.ERR_CONTRAINDICATION_EVIDENCE_REQUIRED.value, 422,
    )
    assert refused["error_id"] == ApiErrorId.ERR_CONTRAINDICATION_EVIDENCE_REQUIRED.value

    clean = fx.read_checklist(checklist["id"])
    assert clean["absolute_contraindication_count"] == 0, (
        f"no count moved, got {clean['absolute_contraindication_count']}"
    )
    assert clean["relative_contraindication_count"] == 0
    assert clean["contraindications"] == [], (
        f"nothing was appended to the array, got {clean['contraindications']}"
    )
    assert clean["screening_eligibility_score"] == 60.00, (
        f"the screening figure is untouched, got {clean['screening_eligibility_score']}"
    )

    assert fx.list_case_deviations(case["id"]) == [], (
        "a rejected contraindication opens no MISSING_CONTRAINDICATION_DOC deviation, got "
        f"{fx.list_case_deviations(case['id'])}"
    )
    assert fx.read_case(case["id"])["deviation_count"] == 0, (
        f"the case carries no deviation, got {fx.read_case(case['id'])['deviation_count']}"
    )


def test_the_evidence_requirement_follows_the_severity_of_the_entry():
    """A bare RELATIVE entry is accepted while the same ABSOLUTE code needs its evidence.

    PRD 3.5: "An `ABSOLUTE` entry must carry non-empty `documented_evidence` — a `RELATIVE` one need not — and a bare `ABSOLUTE` entry is rejected with `ERR_CONTRAINDICATION_EVIDENCE_REQUIRED` **before any mutation happens**: nothing is appended, no count moves, and in particular no `MISSING_CONTRAINDICATION_DOC` deviation is created."
    PRD 3.5: "15.0 points for each confirmed inclusion item, minus 12.0 for each relative contraindication, minus 100.0 for each absolute contraindication"

    Design: Corner/validations/an_absolute_contraindication_without_documented_evidence_is_rejected
    """
    door_at = "2026-09-01T08:00:00Z"
    _, case, checklist = _documented_checklist_case(door_at)

    fx.set_clock("2026-09-01T08:25:00Z")
    with_relative = validate_success(
        api_client.document_contraindication(
            checklist["id"], f.contraindication_payload("CI_INR_ELEVATED", "RELATIVE"), ED
        ),
        201,
    )
    assert with_relative["relative_contraindication_count"] == 1, (
        "a RELATIVE entry with no evidence is accepted, got "
        f"{with_relative['relative_contraindication_count']}"
    )
    assert with_relative["screening_eligibility_score"] == 48.00, (
        f"60.00 minus 12.0 is 48.00, got {with_relative['screening_eligibility_score']}"
    )

    with_absolute = validate_success(
        api_client.document_contraindication(
            checklist["id"],
            f.contraindication_payload(
                "CI_RECENT_INTRACRANIAL_SURGERY", "ABSOLUTE",
                "operative note dated 2026-08-29 in the transferred chart",
            ),
            ED,
        ),
        201,
    )
    assert with_absolute["absolute_contraindication_count"] == 1, (
        "the same ABSOLUTE code with evidence is accepted, got "
        f"{with_absolute['absolute_contraindication_count']}"
    )
    assert with_absolute["screening_eligibility_score"] == 0.00, (
        "a raw 60.0 - 12.0 - 100.0 clamps up to 0.00 rather than going negative, got "
        f"{with_absolute['screening_eligibility_score']}"
    )
    a.assert_two_decimal_places(
        with_absolute["screening_eligibility_score"], "screening_eligibility_score"
    )
    assert len(with_absolute["contraindications"]) == 2, (
        f"both accepted entries are on the row, got {len(with_absolute['contraindications'])}"
    )
    assert fx.list_case_deviations(case["id"]) == [], (
        "documenting contraindications properly raises no deviation"
    )


def test_administering_a_case_that_never_reached_a_determination_is_refused():
    """A live case whose consult recommended thrombolysis still has no declared administration transition.

    PRD 3.6: "The case must be at `ELIGIBILITY_DETERMINED`. Then, in the precedence of §2.11:"
    PRD 2.11: "The same code covers a case action attempted from a status for which no transition is declared."

    Design: Corner/validations/administering_without_any_checklist_determination_is_refused
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    built = fx.setup_case_with_completed_consult(context, door_at)
    case_id = built["case"]["id"]
    fx.complete_imaging(case_id, at="2026-09-01T08:10:00Z")
    alive = fx.read_case(case_id)
    assert alive["status"] == "CONSULT_IN_PROGRESS", (
        f"the case is alive and mid-consult, got {alive['status']}"
    )
    assert built["consult"]["recommendation"] == "THROMBOLYSIS", (
        "the consult recommended the drug, which is exactly what must not be enough, got "
        f"{built['consult']['recommendation']}"
    )

    fx.set_clock("2026-09-01T08:30:00Z")
    response = api_client.administer_thrombolytic(
        case_id, f.administer_thrombolytic_payload(), ED
    )
    error = validate_error(response, ApiErrorId.ERR_CASE_NOT_ACTIVE.value, 409)
    assert response.status_code == 409, (
        "the case exists and is active, so this is a state failure rather than a 404 or a 422, got "
        f"{response.status_code}"
    )
    assert error["error_id"] == ApiErrorId.ERR_CASE_NOT_ACTIVE.value

    after = fx.read_case(case_id)
    assert after["status"] == "CONSULT_IN_PROGRESS", (
        f"the refused administration left the status alone, got {after['status']}"
    )
    assert after["needle_at"] is None, f"needle_at stays null, got {after['needle_at']}"
    assert after["door_to_needle_minutes"] is None
    assert after["thrombolytic_agent"] is None
    assert after["version"] == alive["version"], (
        f"a refused write does not bump the case version, got {after['version']}"
    )

    _, meta = validate_paginated(
        api_client.list_checklists(COORD, {"case_id": case_id, "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, (
        f"the endpoint does not lazily create a checklist, got {meta['total_count']}"
    )


def test_the_absolute_contraindication_outranks_the_determination_verdict_on_administer():
    """Both guards are armed by one call and the clinical safety rule is the one reported.

    PRD 3.6: "The checklist's `absolute_contraindication_count` must be 0, otherwise `ERR_ABSOLUTE_CONTRAINDICATION`."
    PRD 2.11: "This is the highest-precedence clinical safety rule, and it deliberately sits below rule 13"

    Design: Corner/validations/an_absolute_contraindication_blocks_administration_ahead_of_the_determination_check
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    built = fx.setup_case_with_completed_consult(context, door_at)
    case_id = built["case"]["id"]
    fx.complete_imaging(case_id, at="2026-09-01T08:10:00Z")
    checklist = fx.setup_documented_checklist(case_id, absolute_contraindications=1)
    assert checklist["screening_eligibility_score"] == 0.00, (
        "a raw 60.0 - 100.0 clamps up to 0.00, got "
        f"{checklist['screening_eligibility_score']}"
    )

    determined = _determine(
        checklist["id"], context["neurologist"]["id"], at="2026-09-01T08:25:00Z"
    )
    assert determined["absolute_contraindication_count"] == 1
    assert determined["attested_eligibility_score"] == 0.00, (
        "the attested variant clamps to 0.00 as well, got "
        f"{determined['attested_eligibility_score']}"
    )
    assert determined["determination_status"] == "INELIGIBLE", (
        "the absolute count forces the verdict regardless of the score, got "
        f"{determined['determination_status']}"
    )
    before = fx.read_case(case_id)
    assert before["status"] == "ELIGIBILITY_DETERMINED"
    assert before["disposition"] == "NO_TREATMENT", (
        f"an ineligible verdict sends the case down the no-treatment branch, got {before['disposition']}"
    )

    response = api_client.administer_thrombolytic(
        case_id, f.administer_thrombolytic_payload(), ED
    )
    error = validate_error(response, ApiErrorId.ERR_ABSOLUTE_CONTRAINDICATION.value, 422)
    assert response.status_code == 422, (
        "the two candidate rules differ in status as well as identifier, got "
        f"{response.status_code}"
    )
    assert error["error_id"] != ApiErrorId.ERR_ELIGIBILITY_NOT_DETERMINED.value, (
        "the INELIGIBLE verdict is not what gets reported, got "
        f"{error['error_id']}"
    )

    after = fx.read_case(case_id)
    assert after["status"] == "ELIGIBILITY_DETERMINED", (
        f"the case is unchanged, got {after['status']}"
    )
    assert after["needle_at"] is None, f"needle_at stays null, got {after['needle_at']}"
    assert after["version"] == before["version"], (
        f"the refused write bumped nothing, got version {after['version']}"
    )


def test_two_hundred_seventy_one_minutes_of_window_refuses_the_drug_hours_after_an_eligible_verdict():
    """The classifier is re-run at administration, and one minute past the outer bound is a hard stop.

    PRD 3.6: "the drug is refused with `ERR_THROMBOLYTIC_WINDOW_EXPIRED` when that fresh classification is `OUT_OF_WINDOW` — even if the determination minutes earlier said `ELIGIBLE`, because the window is a property of the passing clock and not of the paperwork."
    PRD 3.2: "Exactly 180 is `WITHIN_3H`, exactly 181 is `WITHIN_4_5H`, exactly 270 is still `WITHIN_4_5H`, and exactly 271 is `OUT_OF_WINDOW`."

    Design: Corner/validations/the_window_is_recomputed_at_administration_and_flips_at_two_hundred_seventy_one_minutes
    """
    door_at = "2026-09-01T08:00:00Z"
    context = fx.setup_network(clock=door_at)
    built = _eligible_case(
        context, door_at,
        dti_minutes=20, determine_at="2026-09-01T08:20:00Z",
        last_known_well_at="2026-09-01T07:40:00Z",
    )
    case_id = built["case"]["id"]
    assert built["checklist"]["determination_status"] == "ELIGIBLE", (
        f"the case was eligible when it was attested, got {built['checklist']['determination_status']}"
    )
    assert built["checklist"]["attested_eligibility_score"] == 66.00
    assert built["case"]["thrombolytic_window_class"] == "WITHIN_3H", (
        "forty minutes past last known well is well inside three hours, got "
        f"{built['case']['thrombolytic_window_class']}"
    )

    fx.set_clock("2026-09-01T12:11:00Z")
    response = api_client.administer_thrombolytic(
        case_id, f.administer_thrombolytic_payload(), ED
    )
    error = validate_error(
        response, ApiErrorId.ERR_THROMBOLYTIC_WINDOW_EXPIRED.value, 422
    )
    assert error["error_id"] == ApiErrorId.ERR_THROMBOLYTIC_WINDOW_EXPIRED.value, (
        "271 whole minutes from 07:40 is past the outer bound, got "
        f"{error['error_id']}"
    )

    after = fx.read_case(case_id)
    assert after["status"] == "ELIGIBILITY_DETERMINED", (
        f"the refusal left the case where it was, got {after['status']}"
    )
    assert after["needle_at"] is None, f"no drug was given, got {after['needle_at']}"
    assert after["thrombolytic_agent"] is None
    assert after["door_to_needle_minutes"] is None
    assert after["disposition"] == "PENDING", (
        f"the case did not take the treated branch, got {after['disposition']}"
    )

    checklist = fx.read_checklist(built["checklist"]["id"])
    assert checklist["determination_status"] == "ELIGIBLE", (
        "the determination is not retroactively rewritten by the expiry, got "
        f"{checklist['determination_status']}"
    )
    assert checklist["attested_eligibility_score"] == 66.00, (
        f"the attested figure stands as attested, got {checklist['attested_eligibility_score']}"
    )


def test_exactly_two_hundred_seventy_minutes_of_window_still_admits_the_drug():
    """One minute earlier on the same clock is inside the extended window and is treated.

    PRD 3.2: "Exactly 180 is `WITHIN_3H`, exactly 181 is `WITHIN_4_5H`, exactly 270 is still `WITHIN_4_5H`, and exactly 271 is `OUT_OF_WINDOW`."
    PRD 3.6: "When `door_to_needle_minutes` exceeds 60 a system-detected `ProtocolDeviation` of type `DTN_EXCEEDED` and severity `MAJOR` is opened on the case with `deviation_count` raised by 1"

    Design: Corner/validations/the_window_is_recomputed_at_administration_and_flips_at_two_hundred_seventy_one_minutes
    """
    door_at = "2026-09-01T09:00:00Z"
    context = fx.setup_network(clock=door_at)
    built = _eligible_case(
        context, door_at,
        dti_minutes=20, determine_at="2026-09-01T09:20:00Z",
        last_known_well_at="2026-09-01T07:41:00Z",
    )
    case_id = built["case"]["id"]
    assert built["checklist"]["determination_status"] == "ELIGIBLE"
    assert built["case"]["thrombolytic_window_class"] == "WITHIN_3H", (
        "99 minutes past last known well is inside three hours, got "
        f"{built['case']['thrombolytic_window_class']}"
    )

    treated = fx.administer(case_id, at="2026-09-01T12:11:00Z")

    assert treated["thrombolytic_window_class"] == "WITHIN_4_5H", (
        "exactly 270 minutes is still the extended window, got "
        f"{treated['thrombolytic_window_class']}"
    )
    assert treated["status"] == "THROMBOLYSIS_ADMINISTERED", (
        f"the drug went in, got {treated['status']}"
    )
    assert treated["disposition"] == "TREATED_LOCAL"
    assert a.instants_equal(treated["needle_at"], "2026-09-01T12:11:00Z"), (
        f"needle_at is stamped from the logical clock, got {treated['needle_at']}"
    )
    assert treated["door_to_needle_minutes"] == 191, (
        f"09:00 to 12:11 is 191 whole minutes, got {treated['door_to_needle_minutes']}"
    )
    assert treated["lkw_to_needle_minutes"] == 270, (
        f"07:41 to 12:11 is exactly 270 whole minutes, got {treated['lkw_to_needle_minutes']}"
    )
    assert treated["thrombolytic_agent"] == "ALTEPLASE"
    a.assert_case_clock_intervals(treated)

    deviations = fx.list_case_deviations(case_id)
    assert len(deviations) == 1, (
        f"a 191-minute needle opens exactly one deviation, got {len(deviations)}"
    )
    a.assert_system_detected_deviation(deviations[0], "DTN_EXCEEDED", "MAJOR")
    assert treated["deviation_count"] == 1, (
        f"the case counts that deviation, got {treated['deviation_count']}"
    )


def test_all_three_last_known_well_clauses_report_the_same_refusal():
    """Omitting the instant, supplying it under a wake-up precision and dating it after the door all fail alike.

    PRD 3.2: "When the precision is `EXACT` or `ESTIMATED`, `last_known_well_at` is required; when the precision is `UNKNOWN_WAKE_UP` — the wake-up stroke whose onset nobody witnessed — `last_known_well_at` must be omitted and remains null."
    PRD 3.2: "a supplied `last_known_well_at` must never be later than `door_at`: a patient cannot have been last known well after they arrived. Any of those three violations is rejected with `ERR_LKW_REQUIRED`."

    Design: Corner/validations/last_known_well_presence_is_dictated_by_the_precision_and_never_follows_the_door
    """
    door_at = "2026-09-01T08:00:00Z"
    fx.set_clock(door_at)
    center = fx.register_center()

    exact_without = validate_error(
        api_client.activate_code_stroke(
            f.code_stroke_payload(center["id"], door_at, lkw_precision="EXACT"), ED
        ),
        ApiErrorId.ERR_LKW_REQUIRED.value, 422,
    )
    estimated_without = validate_error(
        api_client.activate_code_stroke(
            f.code_stroke_payload(center["id"], door_at, lkw_precision="ESTIMATED"), ED
        ),
        ApiErrorId.ERR_LKW_REQUIRED.value, 422,
    )
    wake_up_with = validate_error(
        api_client.activate_code_stroke(
            f.code_stroke_payload(
                center["id"], door_at,
                lkw_precision="UNKNOWN_WAKE_UP",
                last_known_well_at="2026-09-01T07:40:00Z",
            ),
            ED,
        ),
        ApiErrorId.ERR_LKW_REQUIRED.value, 422,
    )
    one_minute_late = validate_error(
        api_client.activate_code_stroke(
            f.code_stroke_payload(
                center["id"], door_at,
                lkw_precision="EXACT",
                last_known_well_at="2026-09-01T08:01:00Z",
            ),
            ED,
        ),
        ApiErrorId.ERR_LKW_REQUIRED.value, 422,
    )

    identifiers = {
        exact_without["error_id"], estimated_without["error_id"],
        wake_up_with["error_id"], one_minute_late["error_id"],
    }
    assert identifiers == {ApiErrorId.ERR_LKW_REQUIRED.value}, (
        f"one identifier guards all three clauses in both directions, got {identifiers}"
    )

    _, meta = validate_paginated(
        api_client.list_code_strokes(COORD, {"center_id": center["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0, (
        f"none of the four refusals created a case, got {meta['total_count']}"
    )
    assert fx.read_center(center["id"])["open_case_count"] == 0, (
        "no refusal cascaded an open-case increment onto the facility, got "
        f"{fx.read_center(center['id'])['open_case_count']}"
    )


def test_last_known_well_equal_to_the_door_and_an_omitted_wake_up_instant_are_both_admitted():
    """The inclusive edge of the comparison and the omission the wake-up precision demands.

    PRD 3.2: "a supplied `last_known_well_at` must never be later than `door_at`: a patient cannot have been last known well after they arrived. Any of those three violations is rejected with `ERR_LKW_REQUIRED`."
    PRD 3.2: "If that is 120 minutes or fewer, `thrombolytic_window_class` is `EXTENDED_UNKNOWN`; if it is more than 120 minutes, the class is `OUT_OF_WINDOW`."

    Design: Corner/validations/last_known_well_presence_is_dictated_by_the_precision_and_never_follows_the_door
    """
    door_at = "2026-09-01T08:00:00Z"
    fx.set_clock(door_at)
    center = fx.register_center()

    on_the_door = validate_success(
        api_client.activate_code_stroke(
            f.code_stroke_payload(
                center["id"], door_at,
                lkw_precision="EXACT", last_known_well_at=door_at,
            ),
            ED,
        ),
        201,
    )
    assert a.instants_equal(on_the_door["last_known_well_at"], door_at), (
        "an instant equal to door_at is accepted, so the comparison is strict on later than, got "
        f"{on_the_door['last_known_well_at']}"
    )
    assert on_the_door["thrombolytic_window_class"] == "WITHIN_3H", (
        "zero elapsed minutes classifies inside three hours, got "
        f"{on_the_door['thrombolytic_window_class']}"
    )

    wake_up = validate_success(
        api_client.activate_code_stroke(
            f.code_stroke_payload(
                center["id"], door_at, lkw_precision="UNKNOWN_WAKE_UP"
            ),
            ED,
        ),
        201,
    )
    assert wake_up["last_known_well_at"] is None, (
        f"the wake-up case keeps a null instant, got {wake_up['last_known_well_at']}"
    )
    assert wake_up["lkw_precision"] == "UNKNOWN_WAKE_UP"
    assert wake_up["thrombolytic_window_class"] == "EXTENDED_UNKNOWN", (
        "a wake-up case is classified on door elapsed time instead, got "
        f"{wake_up['thrombolytic_window_class']}"
    )

    _, meta = validate_paginated(
        api_client.list_code_strokes(COORD, {"center_id": center["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2, (
        f"exactly the two admitted activations exist, got {meta['total_count']}"
    )
    assert fx.read_center(center["id"])["open_case_count"] == 2, (
        "each admitted activation cascaded one open case onto the facility, got "
        f"{fx.read_center(center['id'])['open_case_count']}"
    )


def test_the_transfer_mode_must_agree_with_whether_the_needle_was_given():
    """A lysed case cannot travel unlysed and an untreated one cannot travel as a drip, and swapping the modes fixes both.

    PRD 3.7: "`DRIP_AND_SHIP` means lysis was started locally and requires the case's `needle_at` to be set, while `TRANSFER_ONLY` means the patient is shipped unlysed and requires `needle_at` to be null. Getting this backwards is `ERR_TRANSFER_MODE_MISMATCH`."
    PRD 3.7: "The proposal is created with `origin_center_id` copied from the case's `center_id`, a `status` of `PROPOSED`"

    Design: Corner/validations/transfer_mode_must_match_whether_the_needle_was_already_given
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    destination = fx.register_thrombectomy_center()
    treated = _eligible_case(
        context, "2026-09-01T08:00:00Z",
        dti_minutes=10, determine_at="2026-09-01T08:20:00Z",
    )
    treated_id = treated["case"]["id"]
    lysed = fx.administer(treated_id, at="2026-09-01T08:45:00Z")
    assert lysed["needle_at"] is not None, "the treated case carries a needle instant"

    untreated = _eligible_case(
        context, "2026-09-01T09:00:00Z",
        dti_minutes=10, determine_at="2026-09-01T09:20:00Z",
    )
    untreated_id = untreated["case"]["id"]
    assert untreated["case"]["needle_at"] is None, (
        f"the untreated case has no needle instant, got {untreated['case']['needle_at']}"
    )

    fx.set_clock("2026-09-01T09:40:00Z")
    lysed_as_dry = validate_error(
        api_client.propose_transfer(
            f.transfer_payload(treated_id, destination["id"], "TRANSFER_ONLY", 30), TRANSFER
        ),
        ApiErrorId.ERR_TRANSFER_MODE_MISMATCH.value, 422,
    )
    dry_as_drip = validate_error(
        api_client.propose_transfer(
            f.transfer_payload(untreated_id, destination["id"], "DRIP_AND_SHIP", 30), TRANSFER
        ),
        ApiErrorId.ERR_TRANSFER_MODE_MISMATCH.value, 422,
    )
    assert lysed_as_dry["error_id"] == dry_as_drip["error_id"], (
        "the biconditional fails with one identifier in both directions, got "
        f"{lysed_as_dry['error_id']} and {dry_as_drip['error_id']}"
    )

    drip = validate_success(
        api_client.propose_transfer(
            f.transfer_payload(treated_id, destination["id"], "DRIP_AND_SHIP", 30), TRANSFER
        ),
        201,
    )
    assert drip["mode"] == "DRIP_AND_SHIP", (
        f"the exchanged mode is accepted for the lysed case, got {drip['mode']}"
    )
    assert drip["status"] == "PROPOSED", (
        f"an accepted proposal starts in the declared initial state, got {drip['status']}"
    )
    assert drip["origin_center_id"] == context["spoke"]["id"], (
        f"the origin is copied from the case, got {drip['origin_center_id']}"
    )

    dry = validate_success(
        api_client.propose_transfer(
            f.transfer_payload(untreated_id, destination["id"], "TRANSFER_ONLY", 30), TRANSFER
        ),
        201,
    )
    assert dry["mode"] == "TRANSFER_ONLY", (
        f"the exchanged mode is accepted for the untreated case, got {dry['mode']}"
    )

    _, meta = validate_paginated(
        api_client.list_transfers(
            COORD, {"destination_center_id": destination["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2, (
        f"neither rejected proposal left a row behind, got {meta['total_count']}"
    )
    assert fx.read_case(treated_id)["disposition"] == "DRIP_AND_SHIP", (
        f"the lysed case takes the drip-and-ship branch, got {fx.read_case(treated_id)['disposition']}"
    )
    assert fx.read_case(untreated_id)["disposition"] == "TRANSFER_ONLY", (
        f"the untreated case takes the transfer-only branch, got {fx.read_case(untreated_id)['disposition']}"
    )


def test_a_non_thrombectomy_destination_is_reported_even_when_it_is_the_origin_itself():
    """The hub and the case's own spoke give the same capability refusal, never the self-referral one.

    PRD 3.7: "The destination must have `facility_type` `THROMBECTOMY_CAPABLE` (`ERR_DESTINATION_NOT_THROMBECTOMY_CAPABLE`), must not be the origin facility itself (`ERR_SELF_REFERRAL_TRANSFER`)"
    PRD 2.11: "the response is determined by the highest-precedence rule violated, not by the order in which an implementation happens to run its checks"

    Design: Corner/validations/a_destination_that_is_not_thrombectomy_capable_is_refused_ahead_of_the_self_referral_check
    """
    context = fx.setup_network(clock="2026-09-01T08:00:00Z")
    spoke_id = context["spoke"]["id"]
    hub_id = context["hub"]["id"]
    built = _eligible_case(
        context, "2026-09-01T08:00:00Z",
        dti_minutes=10, determine_at="2026-09-01T08:20:00Z",
    )
    case_id = built["case"]["id"]

    fx.set_clock("2026-09-01T09:10:00Z")
    to_hub = validate_error(
        api_client.propose_transfer(
            f.transfer_payload(case_id, hub_id, "TRANSFER_ONLY", 30), TRANSFER
        ),
        ApiErrorId.ERR_DESTINATION_NOT_THROMBECTOMY_CAPABLE.value, 422,
    )
    to_itself = validate_error(
        api_client.propose_transfer(
            f.transfer_payload(case_id, spoke_id, "TRANSFER_ONLY", 30), TRANSFER
        ),
        ApiErrorId.ERR_DESTINATION_NOT_THROMBECTOMY_CAPABLE.value, 422,
    )
    assert to_hub["error_id"] == to_itself["error_id"], (
        "a HUB_PRIMARY destination and the case's own SPOKE are refused identically, got "
        f"{to_hub['error_id']} and {to_itself['error_id']}"
    )
    assert to_itself["error_id"] != ApiErrorId.ERR_SELF_REFERRAL_TRANSFER.value, (
        "the capability rule outranks the self-referral rule, got "
        f"{to_itself['error_id']}"
    )

    stalled = fx.read_case(case_id)
    assert stalled["status"] == "ELIGIBILITY_DETERMINED", (
        f"neither refusal moved the case, got {stalled['status']}"
    )
    assert stalled["disposition"] == "PENDING", (
        f"neither refusal chose a branch, got {stalled['disposition']}"
    )

    destination = fx.register_thrombectomy_center()
    proposal = validate_success(
        api_client.propose_transfer(
            f.transfer_payload(case_id, destination["id"], "TRANSFER_ONLY", 30), TRANSFER
        ),
        201,
    )
    assert proposal["origin_center_id"] == spoke_id, (
        "the origin is echoed from the case rather than from the request, got "
        f"{proposal['origin_center_id']}"
    )
    assert proposal["destination_center_id"] == destination["id"]
    assert proposal["status"] == "PROPOSED"
    assert fx.read_case(case_id)["status"] == "TRANSFER_INITIATED", (
        f"only the genuine proposal moved the case, got {fx.read_case(case_id)['status']}"
    )


def test_a_case_already_sitting_at_the_thrombectomy_centre_is_refused_as_a_self_referral():
    """With the capability rule satisfied, the self-referral rule surfaces on its own.

    PRD 3.7: "The destination must have `facility_type` `THROMBECTOMY_CAPABLE` (`ERR_DESTINATION_NOT_THROMBECTOMY_CAPABLE`), must not be the origin facility itself (`ERR_SELF_REFERRAL_TRANSFER`)"
    PRD 3.7: "The proposal is created with `origin_center_id` copied from the case's `center_id`, a `status` of `PROPOSED`"

    Design: Corner/validations/a_destination_that_is_not_thrombectomy_capable_is_refused_ahead_of_the_self_referral_check
    """
    context = fx.setup_network(
        clock="2026-09-01T08:00:00Z", spoke_facility_type="THROMBECTOMY_CAPABLE"
    )
    origin = fx.read_center(context["spoke"]["id"])
    assert origin["facility_type"] == "THROMBECTOMY_CAPABLE", (
        f"the case is opened at a thrombectomy-capable facility, got {origin['facility_type']}"
    )
    built = _eligible_case(
        context, "2026-09-01T08:00:00Z",
        dti_minutes=10, determine_at="2026-09-01T08:20:00Z",
    )
    case_id = built["case"]["id"]

    fx.set_clock("2026-09-01T09:10:00Z")
    refused = validate_error(
        api_client.propose_transfer(
            f.transfer_payload(case_id, origin["id"], "TRANSFER_ONLY", 30), TRANSFER
        ),
        ApiErrorId.ERR_SELF_REFERRAL_TRANSFER.value, 409,
    )
    assert refused["error_id"] != ApiErrorId.ERR_DESTINATION_NOT_THROMBECTOMY_CAPABLE.value, (
        "the capability rule is satisfied here, so the self-referral rule is the one left, got "
        f"{refused['error_id']}"
    )

    stalled = fx.read_case(case_id)
    assert stalled["status"] == "ELIGIBILITY_DETERMINED", (
        f"the refused proposal left the case alone, got {stalled['status']}"
    )
    _, meta = validate_paginated(
        api_client.list_transfers(
            COORD, {"destination_center_id": origin["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused proposal left no row behind, got {meta['total_count']}"
    )

    elsewhere = fx.register_thrombectomy_center()
    proposal = validate_success(
        api_client.propose_transfer(
            f.transfer_payload(case_id, elsewhere["id"], "TRANSFER_ONLY", 30), TRANSFER
        ),
        201,
    )
    assert proposal["origin_center_id"] == origin["id"], (
        f"the origin is the case's own facility, got {proposal['origin_center_id']}"
    )
    assert proposal["status"] == "PROPOSED", (
        f"a different thrombectomy centre is a legitimate destination, got {proposal['status']}"
    )


def test_an_inverted_or_self_paired_agreement_is_refused_with_one_identifier():
    """The identical pair, the inverted pair and a thrombectomy hub all fail the same clause.

    PRD 3.1: "The hub and the spoke must be different facilities and the hub must genuinely be a facility whose `facility_type` is `HUB_PRIMARY`; either violation returns `ERR_SPOKE_AGREEMENT_SELF_PAIR`."
    PRD 3.1: "A newly created agreement lands in `DRAFT` with an empty `proxy_credentials` array, an `active_consult_count` of 0 and a null `suspension_reason`."

    Design: Corner/validations/an_agreement_needs_two_distinct_centers_and_a_hub_primary_hub
    """
    fx.set_clock("2026-09-01T08:00:00Z")
    hub = fx.register_hub()
    spoke = fx.register_center()
    thrombectomy = fx.register_thrombectomy_center()

    same_twice = validate_error(
        api_client.create_spoke_agreement(
            f.spoke_agreement_payload(hub["id"], hub["id"]), COORD
        ),
        ApiErrorId.ERR_SPOKE_AGREEMENT_SELF_PAIR.value, 409,
    )
    inverted = validate_error(
        api_client.create_spoke_agreement(
            f.spoke_agreement_payload(spoke["id"], hub["id"]), COORD
        ),
        ApiErrorId.ERR_SPOKE_AGREEMENT_SELF_PAIR.value, 409,
    )
    wrong_hub_type = validate_error(
        api_client.create_spoke_agreement(
            f.spoke_agreement_payload(thrombectomy["id"], spoke["id"]), COORD
        ),
        ApiErrorId.ERR_SPOKE_AGREEMENT_SELF_PAIR.value, 409,
    )
    identifiers = {
        same_twice["error_id"], inverted["error_id"], wrong_hub_type["error_id"]
    }
    assert identifiers == {ApiErrorId.ERR_SPOKE_AGREEMENT_SELF_PAIR.value}, (
        "two distinct centres are not enough when the hub is not a hub, got "
        f"{identifiers}"
    )

    created = validate_success(
        api_client.create_spoke_agreement(
            f.spoke_agreement_payload(hub["id"], spoke["id"]), COORD
        ),
        201,
    )
    assert created["status"] == "DRAFT", (
        f"a new agreement lands in DRAFT, got {created['status']}"
    )
    assert created["proxy_credentials"] == [], (
        f"it starts with no grants, got {created['proxy_credentials']}"
    )
    assert created["active_consult_count"] == 0
    assert created["suspension_reason"] is None

    _, meta = validate_paginated(
        api_client.list_spoke_agreements(
            COORD, {"hub_center_id": hub["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the well-formed pair was created, got {meta['total_count']}"
    )


def test_a_proxy_grant_needs_a_hub_homed_neurologist_and_is_unique_per_scope():
    """A neurologist homed at another hub is refused, and the uniqueness clause is scoped to the pair.

    PRD 3.1: "the named neurologist's `home_center_id` must equal the agreement's `hub_center_id`, and there may be at most one grant per combination of `neurologist_id` and `privilege_scope` while an existing grant for that combination is still `GRANTED`. Either violation returns `ERR_PROXY_CREDENTIAL_INVALID`."
    PRD 3.1: "a `status` of `GRANTED`, and a `granted_at` set to the logical clock"

    Design: Corner/validations/credentialing_by_proxy_is_limited_to_hub_neurologists_and_one_grant_per_scope
    """
    granted_at = "2026-09-01T08:00:00Z"
    fx.set_clock(granted_at)
    hub = fx.register_hub()
    other_hub = fx.register_hub()
    spoke = fx.register_center()
    agreement = fx.create_agreement(hub["id"], spoke["id"])
    insider = fx.register_neurologist(hub["id"])
    outsider = fx.register_neurologist(other_hub["id"])
    assert outsider["home_center_id"] != agreement["hub_center_id"], (
        "the outsider is employed by a different hub, got "
        f"{outsider['home_center_id']}"
    )

    refused = validate_error(
        api_client.grant_proxy_credential(
            agreement["id"], f.proxy_credential_payload(outsider["id"]), COORD
        ),
        ApiErrorId.ERR_PROXY_CREDENTIAL_INVALID.value, 422,
    )
    assert refused["error_id"] == ApiErrorId.ERR_PROXY_CREDENTIAL_INVALID.value
    assert fx.read_agreement(agreement["id"])["proxy_credentials"] == [], (
        "the refused grant appended nothing, got "
        f"{fx.read_agreement(agreement['id'])['proxy_credentials']}"
    )

    first = validate_success(
        api_client.grant_proxy_credential(
            agreement["id"], f.proxy_credential_payload(insider["id"]), COORD
        ),
        201,
    )
    assert len(first["proxy_credentials"]) == 1, (
        f"the hub-homed neurologist is granted, got {len(first['proxy_credentials'])}"
    )
    grant = first["proxy_credentials"][0]
    assert grant["neurologist_id"] == insider["id"]
    assert grant["privilege_scope"] == "CONSULT_AND_THROMBOLYSIS"
    assert grant["status"] == "GRANTED", (
        f"a new grant starts GRANTED, got {grant['status']}"
    )
    assert a.instants_equal(grant["granted_at"], granted_at), (
        f"granted_at comes from the logical clock, got {grant['granted_at']}"
    )

    duplicate = validate_error(
        api_client.grant_proxy_credential(
            agreement["id"], f.proxy_credential_payload(insider["id"]), COORD
        ),
        ApiErrorId.ERR_PROXY_CREDENTIAL_INVALID.value, 422,
    )
    assert duplicate["error_id"] == ApiErrorId.ERR_PROXY_CREDENTIAL_INVALID.value, (
        f"the same pair may not be granted twice, got {duplicate['error_id']}"
    )

    second_scope = validate_success(
        api_client.grant_proxy_credential(
            agreement["id"],
            f.proxy_credential_payload(insider["id"], privilege_scope="CONSULT_ONLY"),
            COORD,
        ),
        201,
    )
    assert len(second_scope["proxy_credentials"]) == 2, (
        "uniqueness is per neurologist and scope, not per neurologist, got "
        f"{len(second_scope['proxy_credentials'])}"
    )
    scopes = sorted(g["privilege_scope"] for g in second_scope["proxy_credentials"])
    assert scopes == ["CONSULT_AND_THROMBOLYSIS", "CONSULT_ONLY"], (
        f"both scopes are held at once, got {scopes}"
    )
    assert len(fx.read_agreement(agreement["id"])["proxy_credentials"]) == 2, (
        "the rejected duplicate appended nothing on re-read"
    )


def test_a_consult_requested_before_the_agreement_takes_effect_is_refused():
    """An ACTIVE agreement is not yet an agreement in effect, and the lower bound is inclusive.

    PRD 3.3: "A request made before the agreement's `effective_from` has arrived is rejected earlier and differently, with `ERR_AGREEMENT_WINDOW_CLOSED`."
    PRD 3.3: "The winner is written to `assigned_neurologist_id`, `assigned_at` is stamped from the logical clock, the consult's `status` becomes `ASSIGNED`"

    Design: Corner/validations/a_consult_cannot_be_requested_before_the_agreement_takes_effect
    """
    effective_from = "2026-09-02T00:00:00Z"
    context = fx.setup_network(clock="2026-09-01T08:00:00Z", effective_from=effective_from)
    agreement = context["agreement"]
    assert agreement["status"] == "ACTIVE", (
        f"the agreement was activated, got {agreement['status']}"
    )
    assert a.instants_equal(agreement["effective_from"], effective_from), (
        f"its coverage window opens tomorrow, got {agreement['effective_from']}"
    )
    case = fx.activate_case(context["spoke"]["id"], "2026-09-01T08:00:00Z")

    early = validate_error(
        api_client.request_consult(
            f.consult_request_payload(case["id"], agreement["id"], case["version"]), ED
        ),
        ApiErrorId.ERR_AGREEMENT_WINDOW_CLOSED.value, 409,
    )
    assert early["error_id"] != ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, (
        "the status check is satisfied, so only the temporal clause can refuse, got "
        f"{early['error_id']}"
    )

    unchanged = fx.read_agreement(agreement["id"])
    assert unchanged["status"] == "ACTIVE", (
        f"the refusal did not disturb the agreement, got {unchanged['status']}"
    )
    assert unchanged["active_consult_count"] == 0, (
        f"the refusal reserved no capacity, got {unchanged['active_consult_count']}"
    )
    assert fx.read_case(case["id"])["status"] == "ACTIVATED", (
        f"the case did not move into a consult, got {fx.read_case(case['id'])['status']}"
    )

    consult = fx.request_consult(case["id"], agreement["id"], at=effective_from)

    assert consult["status"] == "ASSIGNED", (
        f"at exactly effective_from the identical request routes, got {consult['status']}"
    )
    assert consult["assigned_neurologist_id"] == context["neurologist"]["id"], (
        f"the only candidate takes it, got {consult['assigned_neurologist_id']}"
    )
    assert a.instants_equal(consult["assigned_at"], effective_from), (
        f"assigned_at is stamped from the logical clock, got {consult['assigned_at']}"
    )
    assert fx.read_agreement(agreement["id"])["active_consult_count"] == 1, (
        "the accepted request is the one that consumes capacity, got "
        f"{fx.read_agreement(agreement['id'])['active_consult_count']}"
    )


def test_the_fourth_live_consult_is_refused_until_an_abort_releases_one():
    """The ceiling counts only live consults, so aborting a case lets the refused request through.

    PRD 3.3: "the count of consults already on it whose `status` is `REQUESTED`, `ASSIGNED` or `IN_SESSION` must be strictly fewer than its `max_concurrent_consults`, otherwise `ERR_AGREEMENT_CONSULT_CAPACITY`"
    PRD 3.8: "First, every consult on the case in `REQUESTED`, `ASSIGNED` or `IN_SESSION` is cancelled and every transfer decision in `PROPOSED` or `ACCEPTED` is cancelled."

    Design: Corner/validations/the_fourth_live_consult_on_a_three_consult_agreement_is_refused_until_one_is_cancelled
    """
    context = fx.setup_network(
        clock="2026-09-01T08:00:00Z",
        max_concurrent_consults=3,
        neurologists=[{"roster_rank": 10}, {"roster_rank": 20}],
    )
    agreement_id = context["agreement"]["id"]
    cases = [fx.activate_case(context["spoke"]["id"], "2026-09-01T08:00:00Z") for _ in range(4)]
    for case in cases:
        fx.complete_imaging(case["id"], at="2026-09-01T08:10:00Z")
    live = [
        fx.request_consult(case["id"], agreement_id, at="2026-09-01T08:15:00Z")
        for case in cases[:3]
    ]
    for consult in live:
        assert consult["status"] == "ASSIGNED", (
            f"each of the three is individually valid, got {consult['status']}"
        )
    assert fx.read_agreement(agreement_id)["active_consult_count"] == 3, (
        "the agreement sits exactly at its ceiling, got "
        f"{fx.read_agreement(agreement_id)['active_consult_count']}"
    )

    fourth_case = cases[3]
    fx.set_clock("2026-09-01T08:20:00Z")
    refused = validate_error(
        api_client.request_consult(
            f.consult_request_payload(
                fourth_case["id"], agreement_id, fx.read_case(fourth_case["id"])["version"]
            ),
            ED,
        ),
        ApiErrorId.ERR_AGREEMENT_CONSULT_CAPACITY.value, 409,
    )
    assert refused["error_id"] == ApiErrorId.ERR_AGREEMENT_CONSULT_CAPACITY.value
    assert fx.read_agreement(agreement_id)["active_consult_count"] == 3, (
        "the refusal did not increment the counter, got "
        f"{fx.read_agreement(agreement_id)['active_consult_count']}"
    )
    _, meta = validate_paginated(
        api_client.list_consults(
            COORD, {"case_id": fourth_case["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0, (
        f"no consult row was created for the fourth case, got {meta['total_count']}"
    )

    fx.abort_case(cases[0]["id"], at="2026-09-01T08:21:00Z")
    released = fx.read_consult(live[0]["id"])
    assert released["status"] == "CANCELLED", (
        f"the abort cancelled the consult it carried, got {released['status']}"
    )
    assert fx.read_agreement(agreement_id)["active_consult_count"] == 2, (
        "a CANCELLED consult leaves the live pool, got "
        f"{fx.read_agreement(agreement_id)['active_consult_count']}"
    )

    admitted = fx.request_consult(fourth_case["id"], agreement_id, at="2026-09-01T08:22:00Z")
    assert admitted["status"] == "ASSIGNED", (
        f"the previously refused request now routes, got {admitted['status']}"
    )
    assert admitted["assigned_neurologist_id"] is not None
    assert fx.read_agreement(agreement_id)["active_consult_count"] == 3, (
        "the ceiling is reached again, got "
        f"{fx.read_agreement(agreement_id)['active_consult_count']}"
    )
