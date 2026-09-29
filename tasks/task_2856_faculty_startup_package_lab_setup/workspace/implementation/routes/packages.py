"""StartupPackage negotiation, the tranche schedule and the package reads.

PRD 3.2 (drafting), 3.3 (the three signatures and the counteroffer loop),
3.4 (activation and the rollups) and 3.9 (rollover, close-out, recommitment).
"""

from flask import Blueprint

import authz
import cascades
import derive
import envelope
import ledger
import lookups
import money
import serialize
import store
import validate
from errors import fail

bp = Blueprint("packages", __name__)

PACKAGE_KINDS = ("INITIAL", "RETENTION_COUNTEROFFER")
NEGOTIATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "DEAN_REVIEW",
    "COUNTERED",
    "APPROVED",
    "ACTIVE",
    "CLOSED_OUT",
    "SUPERSEDED",
)
SPEND_STATUSES = ("NOT_YET_AVAILABLE", "SPENDING", "FROZEN", "SETTLED")
CARRYFORWARD_POLICIES = ("NONE", "CAPPED", "FULL")

OFFICE_ROLES = (authz.ROLE_DEAN_OFFICE, authz.ROLE_DEAN, authz.ROLE_DEPARTMENT_CHAIR)
READ_ROLES = OFFICE_ROLES + (authz.ROLE_FACULTY,)


def _predecessor_unspent_cents(predecessor):
    """PRD 3.9: the SCHEDULED / OPEN available balances of the predecessor."""
    total = 0
    for tranche in ledger.tranches_of_package(predecessor["id"]):
        if tranche["status"] in ("SCHEDULED", "OPEN"):
            total += ledger.available_balance(tranche)
    return total


@bp.post("/startup-packages")
def create_package():
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    payload = validate.body()
    faculty_id = validate.identifier(payload, "faculty_id")
    kind = validate.enum(payload, "package_kind", PACKAGE_KINDS)
    superseded_id = validate.identifier(payload, "superseded_package_id", required=False)
    dean_unit_id = validate.identifier(payload, "dean_unit_id")
    dept_pct = validate.percent(payload, "dept_share_pct")
    college_pct = validate.percent(payload, "college_share_pct")
    dean_pct = validate.percent(payload, "dean_share_pct")
    total = validate.cents(payload, "proposed_total_cents", positive=True)
    deadline = validate.calendar_date(payload, "spend_deadline_on")
    if kind == "RETENTION_COUNTEROFFER" and superseded_id is None:
        fail(
            "ERR_VALIDATION",
            "a RETENTION_COUNTEROFFER must name superseded_package_id",
        )
    if kind == "INITIAL" and superseded_id is not None:
        fail(
            "ERR_VALIDATION",
            "an INITIAL package must leave superseded_package_id null",
        )
    if dept_pct + college_pct + dean_pct != 100:
        fail(
            "ERR_SHARE_PCT_SUM_INVALID",
            "the three cost-share percentages must sum to exactly 100",
        )
    lookups.get_unit_typed(dean_unit_id, "DEAN_OFFICE", "dean_unit_id")
    record_faculty = lookups.get_faculty(faculty_id)
    predecessor = None
    if superseded_id is not None:
        predecessor = lookups.get_package(superseded_id)
        if (
            predecessor["negotiation_status"] != "ACTIVE"
            or predecessor["faculty_id"] != record_faculty["id"]
            or record_faculty["appointment_status"] != "DEPARTURE_NOTICE"
            or record_faculty["departure_intent"] != "OUTSIDE_OFFER"
        ):
            fail(
                "ERR_PREDECESSOR_NOT_ELIGIBLE",
                "the superseded package is not eligible for a retention counteroffer",
            )
        floor = _predecessor_unspent_cents(predecessor) + money.MIN_NEW_MONEY_CENTS
        if total < floor:
            fail(
                "ERR_RECOMMITMENT_BELOW_FLOOR",
                "proposed_total_cents must be at least %d cents" % floor,
            )
    department = store.db.funding_units.get(record_faculty["funding_unit_id"])
    if department is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the faculty member's department no longer exists")
    record = {
        "id": store.new_id(),
        "faculty_id": record_faculty["id"],
        "package_kind": kind,
        "superseded_package_id": superseded_id,
        "department_unit_id": department["id"],
        "college_unit_id": department["parent_unit_id"],
        "dean_unit_id": dean_unit_id,
        "dept_share_pct": dept_pct,
        "college_share_pct": college_pct,
        "dean_share_pct": dean_pct,
        "proposed_total_cents": total,
        "spend_deadline_on": deadline.isoformat(),
        "negotiation_status": "DRAFT",
        "spend_status": "NOT_YET_AVAILABLE",
        "negotiation_round": 1,
        "counter_total_cents": None,
        "proposed_by_user_id": None,
        "endorsed_by_user_id": None,
        "approved_by_user_id": None,
        "settlement_variant": None,
        "recaptured_unspent_cents": 0,
        "transferred_balance_cents": 0,
        "college_holdback_cents": 0,
        "activated_on": None,
        "closed_out_on": None,
    }
    store.stamp_new(record)
    store.db.packages[record["id"]] = record
    if predecessor is not None:
        record_faculty["retention_round"] = (
            derive.retention_round(record_faculty["id"]) + 1
        )
        store.touch(record_faculty)
    return envelope.created(serialize.package(record))


@bp.post("/startup-packages/<package_id>/tranches")
def create_tranche(package_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    payload = validate.body()
    category = validate.enum(payload, "category", ledger.TRANCHE_CATEGORIES)
    fiscal_year = validate.integer(
        payload, "fiscal_year", minimum=2020, maximum=2100
    )
    amount = validate.cents(payload, "amount_cents", positive=True)
    available_on = validate.instant(payload, "available_on")
    expires_on = validate.instant(payload, "expires_on")
    policy = validate.enum(payload, "carryforward_policy", CARRYFORWARD_POLICIES)
    cap_pct = validate.percent(payload, "carryforward_cap_pct", required=False)
    validate.strictly_before(
        available_on, expires_on, "expires_on must be strictly after available_on"
    )
    if policy == "CAPPED" and cap_pct is None:
        fail(
            "ERR_VALIDATION",
            "carryforward_cap_pct is required when carryforward_policy is CAPPED",
        )
    if policy != "CAPPED" and cap_pct is not None:
        fail(
            "ERR_VALIDATION",
            "carryforward_cap_pct is only accepted when carryforward_policy is CAPPED",
        )
    package = lookups.get_package(package_id)
    if package["negotiation_status"] != "DRAFT":
        fail(
            "ERR_PACKAGE_STATE_INVALID",
            "tranches may only be scheduled while the package is in DRAFT",
        )
    record = {
        "id": store.new_id(),
        "package_id": package["id"],
        "category": category,
        "fiscal_year": fiscal_year,
        "amount_cents": amount,
        "available_on": store.iso(available_on),
        "expires_on": store.iso(expires_on),
        "carryforward_policy": policy,
        "carryforward_cap_pct": cap_pct if policy == "CAPPED" else 0,
        "status": "SCHEDULED",
        "opened_on": None,
    }
    store.stamp_new(record)
    store.db.tranches[record["id"]] = record
    # Every tranche create re-derives the owning package's rollups (PRD 3.2).
    store.touch(package)
    return envelope.created(serialize.tranche(record))


@bp.delete("/startup-packages/<package_id>/tranches/<tranche_id>")
def delete_tranche(package_id, tranche_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    package = lookups.get_package(package_id)
    tranche = lookups.get_tranche(tranche_id, package["id"])
    if package["negotiation_status"] != "DRAFT":
        fail(
            "ERR_PACKAGE_STATE_INVALID",
            "a tranche may only be withdrawn while the package is in DRAFT",
        )
    if tranche["status"] != "SCHEDULED":
        fail(
            "ERR_SPEND_ITEM_STATE_INVALID",
            "only a SCHEDULED tranche may be withdrawn",
        )
    del store.db.tranches[tranche["id"]]
    store.touch(package)
    return envelope.no_content()


@bp.post("/startup-packages/<package_id>/submit")
def submit_package(package_id):
    act = authz.actor((authz.ROLE_DEAN_OFFICE,))
    package = lookups.get_package(package_id)
    if package["negotiation_status"] != "DRAFT":
        fail("ERR_PACKAGE_STATE_INVALID", "only a DRAFT package may be submitted")
    tranches = ledger.tranches_of_package(package["id"])
    if not tranches:
        fail("ERR_NO_TRANCHES_DEFINED", "the package has no commitment tranche")
    scheduled_total = sum(int(t["amount_cents"]) for t in tranches)
    if scheduled_total != int(package["proposed_total_cents"]):
        fail(
            "ERR_TRANCHE_SUM_MISMATCH",
            "the tranche amounts must sum to proposed_total_cents exactly",
        )
    package["negotiation_status"] = "SUBMITTED"
    package["proposed_by_user_id"] = act.user_id
    store.touch(package)
    return envelope.object_response(serialize.package(package))


@bp.post("/startup-packages/<package_id>/endorse")
def endorse_package(package_id):
    act = authz.actor((authz.ROLE_DEPARTMENT_CHAIR,))
    package = lookups.get_package(package_id)
    authz.unit_scope_on_package(act, package)
    authz.segregation(act, package["proposed_by_user_id"])
    if package["negotiation_status"] != "SUBMITTED":
        fail("ERR_PACKAGE_STATE_INVALID", "only a SUBMITTED package may be endorsed")
    package["negotiation_status"] = "DEAN_REVIEW"
    package["endorsed_by_user_id"] = act.user_id
    store.touch(package)
    return envelope.object_response(serialize.package(package))


@bp.post("/startup-packages/<package_id>/counter")
def counter_package(package_id):
    act = authz.actor((authz.ROLE_DEAN,))
    payload = validate.body()
    counter_total = validate.cents(payload, "counter_total_cents")
    package = lookups.get_package(package_id)
    authz.unit_scope_on_package(act, package)
    if package["negotiation_status"] != "DEAN_REVIEW":
        fail(
            "ERR_PACKAGE_STATE_INVALID",
            "only a package in DEAN_REVIEW may be countered",
        )
    package["negotiation_status"] = "COUNTERED"
    package["counter_total_cents"] = counter_total
    # A counter voids the endorsement (PRD 3.3).
    package["endorsed_by_user_id"] = None
    store.touch(package)
    return envelope.object_response(serialize.package(package))


@bp.post("/startup-packages/<package_id>/revise")
def revise_package(package_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    payload = validate.body()
    revised_total = validate.cents(payload, "revised_total_cents", positive=True)
    package = lookups.get_package(package_id)
    if package["negotiation_status"] != "COUNTERED":
        fail(
            "ERR_PACKAGE_STATE_INVALID",
            "only a COUNTERED package may be revised",
        )
    package["negotiation_status"] = "DRAFT"
    package["proposed_total_cents"] = revised_total
    package["negotiation_round"] = int(package["negotiation_round"]) + 1
    package["proposed_by_user_id"] = None
    store.touch(package)
    return envelope.object_response(serialize.package(package))


@bp.post("/startup-packages/<package_id>/approve")
def approve_package(package_id):
    act = authz.actor((authz.ROLE_DEAN,))
    package = lookups.get_package(package_id)
    authz.unit_scope_on_package(act, package)
    authz.segregation(
        act, package["proposed_by_user_id"], package["endorsed_by_user_id"]
    )
    if package["negotiation_status"] != "DEAN_REVIEW":
        fail(
            "ERR_PACKAGE_STATE_INVALID",
            "only a package in DEAN_REVIEW may be approved",
        )
    committed = ledger.package_rollup(package)["total_committed_cents"]
    shares = ledger.package_split(package, committed)
    units = ledger.funder_units(package)
    for slot, unit in zip(("dept", "college", "dean"), units):
        if unit is None:
            continue
        if ledger.unit_amounts(unit)["available_pool_cents"] < shares[slot]:
            fail(
                "ERR_UNIT_POOL_EXCEEDED",
                "funding unit %s cannot reserve %d cents" % (unit["id"], shares[slot]),
            )
    package["negotiation_status"] = "APPROVED"
    package["approved_by_user_id"] = act.user_id
    store.touch(package)
    # The reservation lands on the three funder pools (PRD 2.8, 3.3).
    for unit in units:
        if unit is not None:
            store.touch(unit)
    return envelope.object_response(serialize.package(package))


@bp.post("/startup-packages/<package_id>/activate")
def activate_package(package_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    package = lookups.get_package(package_id)
    if package["negotiation_status"] != "APPROVED":
        fail(
            "ERR_PACKAGE_STATE_INVALID",
            "only an APPROVED package may be activated",
        )
    record_faculty = store.db.faculty.get(package["faculty_id"])
    if record_faculty is None:
        fail("ERR_FACULTY_NOT_FOUND", "the package's faculty member no longer exists")
    if package["package_kind"] == "RETENTION_COUNTEROFFER":
        required_status = "DEPARTURE_NOTICE"
    else:
        required_status = "ACTIVE"
    if record_faculty["appointment_status"] != required_status:
        fail(
            "ERR_FACULTY_NOT_ACTIVE",
            "activation requires the faculty member to be in %s" % required_status,
        )
    predecessor = None
    if package["superseded_package_id"] is not None:
        predecessor = store.db.packages.get(package["superseded_package_id"])
    if predecessor is not None:
        blocked = any(
            t["status"] == "OBLIGATED"
            for t in ledger.tranches_of_package(predecessor["id"])
        )
        if not blocked:
            blocked = ledger.package_rollup(predecessor)["total_encumbered_cents"] != 0
        if blocked:
            fail(
                "ERR_PREDECESSOR_HAS_OPEN_ENCUMBRANCES",
                "the superseded package still holds open encumbrances",
            )
    package["negotiation_status"] = "ACTIVE"
    package["spend_status"] = "SPENDING"
    package["activated_on"] = ledger.clock_iso()
    store.touch(package)
    cascades.open_in_window_tranches(package)
    if predecessor is not None:
        cascades.recommitment_cascade(package, predecessor, record_faculty)
    return envelope.object_response(serialize.package(package))


@bp.post("/startup-packages/<package_id>/year-end-rollover")
def rollover_package(package_id):
    act = authz.actor((authz.ROLE_DEAN_OFFICE, authz.ROLE_DEAN))
    payload = validate.body()
    fiscal_year = validate.integer(
        payload, "fiscal_year", minimum=2020, maximum=2100
    )
    package = lookups.get_package(package_id)
    authz.unit_scope_on_package(act, package)
    if package["negotiation_status"] != "ACTIVE":
        fail(
            "ERR_PACKAGE_STATE_INVALID",
            "only an ACTIVE package may run a year-end rollover",
        )
    boundary = "%04d-07-01T00:00:00.000Z" % fiscal_year
    if ledger.clock_iso() < boundary:
        fail(
            "ERR_ROLLOVER_FISCAL_YEAR_NOT_ELAPSED",
            "fiscal year %d has not closed yet" % fiscal_year,
        )
    for tranche in ledger.tranches_of_package(package["id"]):
        if int(tranche["fiscal_year"]) != fiscal_year:
            continue
        if tranche["status"] in ("CARRIED_FORWARD", "EXPIRED"):
            fail(
                "ERR_ROLLOVER_ALREADY_RUN",
                "the rollover for fiscal year %d has already run" % fiscal_year,
            )
    cascades.year_end_rollover(package, fiscal_year)
    return envelope.object_response(serialize.package(package))


@bp.post("/startup-packages/<package_id>/close-out")
def close_out_package(package_id):
    authz.actor((authz.ROLE_DEAN,))
    package = lookups.get_package(package_id)
    if package["negotiation_status"] != "ACTIVE":
        fail("ERR_PACKAGE_STATE_INVALID", "only an ACTIVE package may be closed out")
    tranches = ledger.tranches_of_package(package["id"])
    open_encumbrance = ledger.package_rollup(package)["total_encumbered_cents"] != 0
    if not open_encumbrance:
        open_encumbrance = any(t["status"] == "OBLIGATED" for t in tranches)
    if open_encumbrance:
        fail(
            "ERR_OPEN_ENCUMBRANCES_BLOCK_CLOSEOUT",
            "the package still holds open encumbrances",
        )
    cascades.close_out(package)
    return envelope.object_response(serialize.package(package))


APPOINTMENT_TYPES = ("LAB_MANAGER", "POSTDOC", "GRAD_RA", "TECHNICIAN")
APPOINTMENT_STATUSES = ("PROPOSED", "ACTIVE", "ENDED", "CANCELLED")


@bp.get("/startup-packages")
def list_packages():
    authz.actor(OFFICE_ROLES)
    limit, offset = validate.pagination()
    faculty_filter = validate.filter_value("faculty_id")
    superseded_filter = validate.filter_value("superseded_package_id")
    department_filter = validate.filter_value("department_unit_id")
    college_filter = validate.filter_value("college_unit_id")
    dean_filter = validate.filter_value("dean_unit_id")
    negotiation_filter = validate.filter_value(
        "negotiation_status", NEGOTIATION_STATUSES
    )
    spend_filter = validate.filter_value("spend_status", SPEND_STATUSES)
    records = store.by_created(list(store.db.packages.values()))
    if faculty_filter is not None:
        records = [p for p in records if p["faculty_id"] == faculty_filter]
    if superseded_filter is not None:
        records = [
            p for p in records if p["superseded_package_id"] == superseded_filter
        ]
    if department_filter is not None:
        records = [p for p in records if p["department_unit_id"] == department_filter]
    if college_filter is not None:
        records = [p for p in records if p["college_unit_id"] == college_filter]
    if dean_filter is not None:
        records = [p for p in records if p["dean_unit_id"] == dean_filter]
    if negotiation_filter is not None:
        records = [
            p for p in records if p["negotiation_status"] == negotiation_filter
        ]
    if spend_filter is not None:
        records = [p for p in records if p["spend_status"] == spend_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.package(p) for p in page], limit, offset, total
    )


@bp.get("/startup-packages/<package_id>")
def read_package(package_id):
    act = authz.actor(READ_ROLES)
    package = lookups.get_package(package_id)
    authz.faculty_scope(act, package["faculty_id"])
    return envelope.object_response(serialize.package(package))


@bp.get("/startup-packages/<package_id>/tranches")
def list_package_tranches(package_id):
    act = authz.actor(READ_ROLES)
    limit, offset = validate.pagination()
    category_filter = validate.filter_value("category", ledger.TRANCHE_CATEGORIES)
    year_filter = validate.filter_int("fiscal_year")
    status_filter = validate.filter_value("status", ledger.TRANCHE_STATUSES)
    package = lookups.get_package(package_id)
    authz.faculty_scope(act, package["faculty_id"])
    records = ledger.tranches_of_package(package["id"])
    if category_filter is not None:
        records = [t for t in records if t["category"] == category_filter]
    if year_filter is not None:
        records = [t for t in records if int(t["fiscal_year"]) == year_filter]
    if status_filter is not None:
        records = [t for t in records if t["status"] == status_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.tranche(t) for t in page], limit, offset, total
    )


@bp.get("/startup-packages/<package_id>/staff-appointments")
def list_package_appointments(package_id):
    act = authz.actor(READ_ROLES)
    limit, offset = validate.pagination()
    status_filter = validate.filter_value("status", APPOINTMENT_STATUSES)
    type_filter = validate.filter_value("appointment_type", APPOINTMENT_TYPES)
    package = lookups.get_package(package_id)
    authz.faculty_scope(act, package["faculty_id"])
    records = cascades.appointments_of_package(package["id"])
    if status_filter is not None:
        records = [a for a in records if a["status"] == status_filter]
    if type_filter is not None:
        records = [a for a in records if a["appointment_type"] == type_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.staff_appointment(a) for a in page], limit, offset, total
    )


@bp.get("/startup-packages/<package_id>/spend-transactions")
def list_package_transactions(package_id):
    act = authz.actor(READ_ROLES)
    limit, offset = validate.pagination()
    kind_filter = validate.filter_value("kind", ledger.KINDS)
    source_filter = validate.filter_value("source_kind", ledger.SOURCE_KINDS)
    package = lookups.get_package(package_id)
    authz.faculty_scope(act, package["faculty_id"])
    records = ledger.rows_for_package(package["id"])
    if kind_filter is not None:
        records = [r for r in records if r["kind"] == kind_filter]
    if source_filter is not None:
        records = [r for r in records if r["source_kind"] == source_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.spend_transaction(r) for r in page], limit, offset, total
    )


@bp.get("/startup-packages/<package_id>/spend-summary")
def read_spend_summary(package_id):
    act = authz.actor(READ_ROLES)
    package = lookups.get_package(package_id)
    authz.faculty_scope(act, package["faculty_id"])
    return envelope.object_response(serialize.spend_summary(package))


@bp.get("/commitment-tranches/<tranche_id>")
def read_tranche(tranche_id):
    act = authz.actor(READ_ROLES)
    tranche = lookups.get_tranche(tranche_id)
    package = store.db.packages.get(tranche["package_id"])
    if package is not None:
        authz.faculty_scope(act, package["faculty_id"])
    return envelope.object_response(serialize.tranche(tranche))


@bp.get("/commitment-tranches/<tranche_id>/spend-transactions")
def list_tranche_transactions(tranche_id):
    act = authz.actor(READ_ROLES)
    limit, offset = validate.pagination()
    kind_filter = validate.filter_value("kind", ledger.KINDS)
    tranche = lookups.get_tranche(tranche_id)
    package = store.db.packages.get(tranche["package_id"])
    if package is not None:
        authz.faculty_scope(act, package["faculty_id"])
    records = ledger.rows_for_tranche(tranche["id"])
    if kind_filter is not None:
        records = [r for r in records if r["kind"] == kind_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.spend_transaction(r) for r in page], limit, offset, total
    )
