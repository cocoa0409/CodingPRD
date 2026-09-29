"""Dispatch: candidate selection, visit windows, the response SLA and settlement."""

from flask import Blueprint

import config
import derive
import serializers
import timeutil
from errors import ApiError
from response import object_response, paginate
from routes.claims import lookup_claim
from routes.contractors import lookup_contractor
from services import calc, cascades
from store import create_record, ordered, store, touch
from validation import Field, current_user_id, filter_enum, filter_value, parse_body, require_path_uuid, require_role

bp = Blueprint("dispatches", __name__)

READ_ROLES = (
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_CUSTOMER_SERVICE_REP,
    config.ROLE_CLAIMS_ADJUSTER,
    config.ROLE_NETWORK_CONTRACTOR,
    config.ROLE_REGULATORY_AFFAIRS,
    config.ROLE_OPERATIONS_ADMIN,
)

CREATE_SPEC = {
    "window_start": Field("instant", required=True),
    "expected_claim_version": Field("integer", required=True),
    "contractor_id": Field("uuid"),
    "supersedes_dispatch_id": Field("uuid"),
}

EVENT_SPEC = {
    "event_type": Field("enum", required=True, enum=config.DISPATCH_EVENT_TYPES),
    "labor_cents": Field("integer", minimum=0),
    "materials_cents": Field("integer", minimum=0),
    "permit_fee_cents": Field("integer", minimum=0),
    "restoration_cents": Field("integer", minimum=0),
    "restoration_scope": Field("enum", enum=config.RESTORATION_SCOPES),
    "permit_number": Field("string", min_len=1, max_len=60),
    "note": Field("string", max_len=1000),
}


def lookup_dispatch(dispatch_id):
    dispatch = store.dispatches.get(dispatch_id)
    if dispatch is None:
        raise ApiError("ERR_DISPATCH_NOT_FOUND", "No dispatch with id %s" % dispatch_id)
    return dispatch


def _open_count(contractor, ignore_dispatch_id=None):
    """Open slots held by a contractor, discounting a dispatch leaving the board."""
    count = 0
    for dispatch in store.dispatches.values():
        if dispatch["contractor_id"] != contractor["id"]:
            continue
        if ignore_dispatch_id is not None and dispatch["id"] == ignore_dispatch_id:
            continue
        if dispatch["status"] in config.OPEN_DISPATCH_STATUSES:
            count += 1
    return count


def _license_expired(contractor):
    """A licence expiring today is already unusable."""
    expires = timeutil.parse_date(contractor["license_expires_on"])
    return expires is None or expires <= store.today()


def _window_conflict(contractor, window_start, window_end, ignore_dispatch_id=None):
    """True when the candidate window collides with a booked one plus its buffer."""
    for existing in ordered(store.dispatches, lambda d: d["contractor_id"] == contractor["id"]):
        if ignore_dispatch_id is not None and existing["id"] == ignore_dispatch_id:
            continue
        if existing["status"] not in config.OPEN_DISPATCH_STATUSES:
            continue
        existing_start = timeutil.parse_instant(existing["window_start"])
        existing_end = timeutil.parse_instant(existing["window_end"])
        if existing_start is None or existing_end is None:
            continue
        if calc.windows_conflict(window_start, window_end, existing_start, existing_end):
            return True
    return False


def _eligible(contractor, claim, product, premises, ignore_dispatch_id=None):
    """The automatic selector's filter: every condition must hold, none is relaxed."""
    if contractor["status"] != "ACTIVE":
        return False
    if _license_expired(contractor):
        return False
    if claim["line_type"] not in contractor["line_types_certified"]:
        return False
    if premises is None or contractor["state_code"] != premises["state_code"]:
        return False
    if _open_count(contractor, ignore_dispatch_id) >= contractor["max_open_dispatches"]:
        return False
    if product is not None and product.get("permit_covered") and not contractor.get("permit_pull_authorized"):
        return False
    return True


def _select_contractor(claim, product, premises, ignore_dispatch_id=None):
    """Highest score wins; ties fall to the cheaper rate then the earlier record."""
    candidates = []
    for contractor in ordered(store.contractors):
        if _eligible(contractor, claim, product, premises, ignore_dispatch_id):
            candidates.append((contractor, calc.selection_score(contractor, claim["urgency"])))
    if not candidates:
        raise ApiError(
            "ERR_NO_ELIGIBLE_CONTRACTOR", "No contractor in the network satisfies every dispatch condition"
        )
    ranked = sorted(
        candidates,
        key=lambda pair: (-pair[1], pair[0]["hourly_rate_cents"], pair[0]["created_at"], pair[0]["_seq"]),
    )
    return ranked[0][0], ranked[0][1]


@bp.post("/claims/<claim_id>/dispatches")
def create_dispatch(claim_id):
    current_user_id()
    require_role(config.ROLE_OPERATIONS_ADMIN)
    require_path_uuid(claim_id)
    body = parse_body(CREATE_SPEC)

    claim = lookup_claim(claim_id)
    named_contractor = lookup_contractor(body["contractor_id"]) if body["contractor_id"] else None
    superseded = lookup_dispatch(body["supersedes_dispatch_id"]) if body["supersedes_dispatch_id"] else None

    if body["expected_claim_version"] != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION", "The claim has changed since it was read")

    # Tier 10: the nominated dispatch first, then the claim's own state.
    if superseded is not None:
        if superseded["claim_id"] != claim["id"] or superseded["status"] not in config.SUPERSEDABLE_DISPATCH_STATUSES:
            raise ApiError("ERR_INVALID_DISPATCH_STATE", "The nominated dispatch cannot be superseded")
        if claim["status"] not in ("APPROVED", "DISPATCHED"):
            raise ApiError("ERR_INVALID_CLAIM_STATE", "Only an APPROVED or DISPATCHED claim may be re-dispatched")
    elif claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only an APPROVED claim may be dispatched")

    enrollment = derive.enrollment_of_claim(claim)
    product = derive.product_of_claim(claim)
    premises = derive.premises_of_enrollment(enrollment) if enrollment is not None else None
    ignore_id = superseded["id"] if superseded is not None else None

    window_start = body["window_start"]
    window_end = calc.visit_window_end(window_start, claim["line_type"])

    if named_contractor is not None:
        selection_mode = "MANUAL"
        contractor = named_contractor
        # Every eligibility condition is enforced individually, in ladder order.
        if contractor["status"] != "ACTIVE":
            raise ApiError("ERR_CONTRACTOR_NOT_ACTIVE", "The named contractor is %s" % contractor["status"])
        if _license_expired(contractor):
            raise ApiError("ERR_CONTRACTOR_LICENSE_EXPIRED", "The named contractor's licence has expired")
        if product is not None and product.get("permit_covered") and not contractor.get("permit_pull_authorized"):
            raise ApiError("ERR_PERMIT_REQUIRED", "The named contractor may not pull municipal permits")
        if claim["line_type"] not in contractor["line_types_certified"]:
            raise ApiError("ERR_CONTRACTOR_NOT_CERTIFIED", "The named contractor is not certified for this line")
        if _window_conflict(contractor, window_start, window_end, ignore_id):
            raise ApiError("ERR_CONTRACTOR_WINDOW_CONFLICT", "The visit window collides with an existing booking")
        if _open_count(contractor, ignore_id) >= contractor["max_open_dispatches"]:
            raise ApiError("ERR_CONTRACTOR_CAPACITY_EXCEEDED", "The named contractor's book is full")
        score = calc.selection_score(contractor, claim["urgency"])
    else:
        selection_mode = "AUTOMATIC"
        contractor, score = _select_contractor(claim, product, premises, ignore_id)
        if _window_conflict(contractor, window_start, window_end, ignore_id):
            raise ApiError("ERR_CONTRACTOR_WINDOW_CONFLICT", "The visit window collides with an existing booking")

    # Tier 16: the occurrence pool is the last thing that can refuse the request.
    if derive.occurrence_pool_cents(claim) <= 0:
        raise ApiError("ERR_PER_OCCURRENCE_CAP_EXHAUSTED", "The occurrence allowance is fully consumed")

    estimated = calc.estimated_benefit_cents(
        derive.benefit_pool_cents(claim), claim["line_type"], contractor["hourly_rate_cents"]
    )

    # The response deadline is set once per claim and inherited from then on.
    if not claim.get("sla_deadline_at"):
        reported = timeutil.parse_instant(claim["reported_at"])
        deadline = timeutil.add_hours(reported, config.SLA_HOURS[claim["urgency"]])
        claim["sla_deadline_at"] = timeutil.render_instant(deadline)

    record = create_record(
        store.dispatches,
        {
            "claim_id": claim["id"],
            "contractor_id": contractor["id"],
            "supersedes_dispatch_id": superseded["id"] if superseded is not None else None,
            "selection_mode": selection_mode,
            "selection_score": score,
            "assigned_at": store.now_iso(),
            "window_start": timeutil.render_instant(window_start),
            "window_end": timeutil.render_instant(window_end),
            "sla_deadline_at": claim["sla_deadline_at"],
            "status": "ASSIGNED",
            "responded_at": None,
            "response_minutes": None,
            "estimated_benefit_cents": estimated,
            "labor_cents": None,
            "materials_cents": None,
            "permit_fee_cents": None,
            "permit_number": None,
            "restoration_cents": None,
            "restoration_scope": None,
            "invoice_total_cents": None,
            "benefit_paid_cents": None,
            "customer_responsibility_cents": None,
            "cancellation_reason": None,
        },
    )

    # The outgoing dispatch leaves the board, releasing its slot and reservation.
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        superseded["cancellation_reason"] = "SUPERSEDED_BY_REDISPATCH"
        touch(superseded)
        touch(store.contractors[superseded["contractor_id"]])

    claim["status"] = "DISPATCHED"
    touch(claim)
    touch(contractor)
    return object_response(serializers.dispatch(record), 201)


@bp.get("/dispatches")
def list_dispatches():
    current_user_id()
    require_role(*READ_ROLES)
    claim_id = filter_value("claim_id")
    contractor_id = filter_value("contractor_id")
    supersedes_id = filter_value("supersedes_dispatch_id")
    status = filter_enum("status", config.DISPATCH_STATUSES)

    def matches(dispatch):
        if claim_id is not None and dispatch["claim_id"] != claim_id:
            return False
        if contractor_id is not None and dispatch["contractor_id"] != contractor_id:
            return False
        if supersedes_id is not None and dispatch["supersedes_dispatch_id"] != supersedes_id:
            return False
        if status is not None and dispatch["status"] != status:
            return False
        return True

    return paginate(ordered(store.dispatches, matches), serializers.dispatch)


@bp.get("/dispatches/<dispatch_id>")
def get_dispatch(dispatch_id):
    current_user_id()
    require_role(*READ_ROLES)
    require_path_uuid(dispatch_id)
    return object_response(serializers.dispatch(lookup_dispatch(dispatch_id)))


@bp.post("/dispatches/<dispatch_id>/events")
def post_dispatch_event(dispatch_id):
    user_id = current_user_id()
    require_role(config.ROLE_NETWORK_CONTRACTOR)
    require_path_uuid(dispatch_id)
    body = parse_body(EVENT_SPEC)
    dispatch = lookup_dispatch(dispatch_id)

    if user_id != dispatch["contractor_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the assigned contractor may post field events")

    event_type = body["event_type"]
    if event_type == "ACCEPT":
        _accept(dispatch)
    elif event_type == "ARRIVE":
        _arrive(dispatch)
    else:
        _complete(dispatch, body)
    return object_response(serializers.dispatch(dispatch))


def _accept(dispatch):
    if dispatch["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_DISPATCH_STATE", "Only an ASSIGNED dispatch may be accepted")
    responded_at = store.now()
    assigned_at = timeutil.parse_instant(dispatch["assigned_at"])
    dispatch["status"] = "ACCEPTED"
    dispatch["responded_at"] = timeutil.render_instant(responded_at)
    dispatch["response_minutes"] = calc.response_minutes(assigned_at, responded_at)
    touch(dispatch)


def _arrive(dispatch):
    if dispatch["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_DISPATCH_STATE", "Only an ACCEPTED dispatch may report arrival")
    dispatch["status"] = "ON_SITE"
    touch(dispatch)


def _complete(dispatch, body):
    if dispatch["status"] not in ("ACCEPTED", "ON_SITE"):
        raise ApiError("ERR_INVALID_DISPATCH_STATE", "Only an ACCEPTED or ON_SITE dispatch may be completed")

    labor = body["labor_cents"] or 0
    materials = body["materials_cents"] or 0
    permit_fee = body["permit_fee_cents"] or 0
    restoration = body["restoration_cents"] or 0
    restoration_scope = body["restoration_scope"] or "NONE"
    permit_number = body["permit_number"]

    if permit_fee > 0 and not permit_number:
        raise ApiError("ERR_PERMIT_REQUIRED", "A permit fee may only be reimbursed against a permit number")

    claim = derive.claim_of_dispatch(dispatch)
    enrollment = derive.enrollment_of_claim(claim)
    product = derive.product_of_claim(claim)
    if product is not None and config.RESTORATION_SCOPE_RANK[restoration_scope] > config.RESTORATION_SCOPE_RANK[
        product["restoration_covered_scope"]
    ]:
        raise ApiError("ERR_RESTORATION_SCOPE_NOT_COVERED", "The performed restoration exceeds the filed scope")

    # The pool is read before the reservation is released: the used figure is
    # defined by posted charges alone, never by an outstanding estimate.
    settlement = calc.settle_invoice(
        product,
        derive.benefit_pool_cents(claim),
        labor,
        materials,
        permit_fee,
        restoration,
        restoration_scope,
    )

    dispatch["labor_cents"] = labor
    dispatch["materials_cents"] = materials
    dispatch["permit_fee_cents"] = permit_fee
    dispatch["permit_number"] = permit_number
    dispatch["restoration_cents"] = restoration
    dispatch["restoration_scope"] = restoration_scope
    dispatch["invoice_total_cents"] = settlement["invoice_total_cents"]
    dispatch["benefit_paid_cents"] = settlement["benefit_paid_cents"]
    dispatch["customer_responsibility_cents"] = settlement["customer_responsibility_cents"]
    # Moving to COMPLETED both frees the contractor's slot and releases the
    # reservation, because both are live views over the open dispatch set.
    dispatch["status"] = "COMPLETED"
    touch(dispatch)
    touch(store.contractors[dispatch["contractor_id"]])

    if settlement["benefit_paid_cents"] > 0:
        cascades.post_ledger(
            enrollment,
            "BENEFIT_CHARGE",
            settlement["benefit_paid_cents"],
            store.today(),
            claim_id=claim["id"],
        )

    # DISPATCHED -> WORK_COMPLETE -> PAID, the middle state transient by design.
    claim["status"] = "WORK_COMPLETE"
    claim["status"] = "PAID"
    touch(claim)
    cascades.refresh_cap_status(enrollment)
