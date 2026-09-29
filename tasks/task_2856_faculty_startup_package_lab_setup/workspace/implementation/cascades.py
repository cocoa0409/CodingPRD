"""Server-initiated transitions: the cascades of PRD 2.12, 3.6, 3.7, 3.8, 3.9.

Consistency is immediate; every dependent resource that changes gets its own
updated_at refresh and version increment inside the same request.
"""

from datetime import date, timedelta

import derive
import ledger
import money
import store

CATEGORY_ORDER = ("EQUIPMENT", "PERSONNEL", "RENOVATION", "DISCRETIONARY")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def packages_of_faculty(faculty_id, negotiation_status=None):
    packages = [p for p in store.db.packages.values() if p["faculty_id"] == faculty_id]
    if negotiation_status is not None:
        packages = [p for p in packages if p["negotiation_status"] == negotiation_status]
    return store.by_created(packages)


def orders_of_package(package_id, statuses=None):
    orders = [o for o in store.db.equipment_orders.values() if o["package_id"] == package_id]
    if statuses is not None:
        orders = [o for o in orders if o["status"] in statuses]
    return store.by_created(orders)


def appointments_of_package(package_id, statuses=None):
    items = [
        a for a in store.db.staff_appointments.values() if a["package_id"] == package_id
    ]
    if statuses is not None:
        items = [a for a in items if a["status"] in statuses]
    return store.by_created(items)


def projects_of_package(package_id, statuses=None):
    items = [
        p for p in store.db.renovation_projects.values() if p["package_id"] == package_id
    ]
    if statuses is not None:
        items = [p for p in items if p["status"] in statuses]
    return store.by_created(items)


def phases_of_project(project_id):
    phases = [p for p in store.db.renovation_phases.values() if p["project_id"] == project_id]
    return sorted(phases, key=lambda p: (int(p["sequence_no"]), p["created_at"], p["_seq"]))


def open_in_window_tranches(package):
    """Advance every SCHEDULED tranche whose window contains the clock to OPEN."""
    moment = ledger.clock_iso()
    for tranche in ledger.tranches_of_package(package["id"]):
        if tranche["status"] != "SCHEDULED":
            continue
        if ledger.in_window(tranche, moment):
            tranche["status"] = "OPEN"
            tranche["opened_on"] = moment
            store.touch(tranche)


def refresh_space_status(space):
    """A room whose allocated share falls to 0 returns to AVAILABLE."""
    if space["status"] != "ASSIGNED":
        return
    if derive.allocated_share_pct(space) == 0:
        space["status"] = "AVAILABLE"
        store.touch(space)


def promote_in_window_proposals(space):
    """Substantial completion promotes in-window PROPOSED assignments to ACTIVE."""
    moment = ledger.clock_iso()
    for assignment in derive.assignments_of_space(space["id"]):
        if assignment["status"] != "PROPOSED":
            continue
        if derive.window_contains(assignment, moment):
            assignment["status"] = "ACTIVE"
            store.touch(assignment)


# ---------------------------------------------------------------------------
# Item-level settlement shared by the endpoints and the cascades
# ---------------------------------------------------------------------------


def cancel_order(order, package):
    """One RELEASE row per open ENCUMBRANCE row, copying its stored split."""
    if package is not None:
        ledger.settle_source(
            package,
            ledger.SOURCE_EQUIPMENT_ORDER,
            order["id"],
            0,
            "equipment order cancelled",
        )
    order["status"] = "CANCELLED"
    store.touch(order)
    return order


def install_order(order, package, space):
    """Disburse the order's open encumbrances and raise the room's loads."""
    open_rows = ledger.open_encumbrances(
        package["id"], ledger.SOURCE_EQUIPMENT_ORDER, order["id"]
    )
    total_open = sum(ledger.open_amount(r) for r in open_rows)
    ledger.settle_source(
        package,
        ledger.SOURCE_EQUIPMENT_ORDER,
        order["id"],
        total_open,
        "equipment installed",
    )
    order["status"] = "INSTALLED"
    order["installed_on"] = ledger.clock_iso()
    order["utility_block_reason"] = None
    store.touch(order)
    # installed_power_kw / installed_fume_hoods are derived from this room's
    # INSTALLED orders, so the room's own version bumps here too.
    store.touch(space)
    return order


def months_served(appointment, effective_end):
    start = date.fromisoformat(appointment["start_date"])
    served = derive.month_span(start, effective_end)
    if served < 0:
        served = 0
    committed = int(appointment["committed_months"])
    return min(served, committed)


def end_appointment(appointment, package, effective_end):
    """Disburse the served months, release the remainder (PRD 3.8)."""
    monthly = derive.monthly_charge_cents(appointment)
    served = months_served(appointment, effective_end)
    disbursed = monthly * served
    total = derive.encumbrance_total_cents(appointment)
    if disbursed > total:
        disbursed = total
    ledger.settle_source(
        package,
        ledger.SOURCE_STAFF_APPOINTMENT,
        appointment["id"],
        disbursed,
        "appointment ended",
    )
    appointment["status"] = "ENDED"
    appointment["ended_on"] = ledger.clock_iso()
    store.touch(appointment)
    return appointment


def release_project_encumbrance(project, package):
    ledger.settle_source(
        package,
        ledger.SOURCE_RENOVATION_PROJECT,
        project["id"],
        0,
        "renovation encumbrance released at separation",
    )


# ---------------------------------------------------------------------------
# The freeze cascade (PRD 3.9)
# ---------------------------------------------------------------------------


def freeze_cascade(faculty):
    for package in packages_of_faculty(faculty["id"], "ACTIVE"):
        if package["spend_status"] == "SPENDING":
            package["spend_status"] = "FROZEN"
            store.touch(package)
        for appointment in appointments_of_package(package["id"], ("PROPOSED",)):
            appointment["status"] = "CANCELLED"
            appointment["ended_on"] = ledger.clock_iso()
            store.touch(appointment)
        for order in orders_of_package(package["id"], ("REQUESTED",)):
            order["status"] = "CANCELLED"
            store.touch(order)


# ---------------------------------------------------------------------------
# Fiscal year-end rollover (PRD 3.9, six pinned steps)
# ---------------------------------------------------------------------------


def rollover_subjects(package, fiscal_year):
    return [
        t
        for t in ledger.tranches_of_package(package["id"])
        if int(t["fiscal_year"]) == int(fiscal_year)
        and t["status"] in ("SCHEDULED", "OPEN", "OBLIGATED")
    ]


def carry_eligible_cents(tranche, eligible):
    if not eligible:
        return 0
    policy = tranche["carryforward_policy"]
    available = ledger.available_balance(tranche)
    if policy == "FULL":
        return max(available, 0)
    if policy == "CAPPED":
        cap_pct = int(tranche["carryforward_cap_pct"] or 0)
        # The cap is a percentage of the ORIGINAL amount_cents.
        ceiling = money.pct_of_cents(int(tranche["amount_cents"]), cap_pct)
        return max(min(available, ceiling), 0)
    return 0


def carryforward_destination(package, category, fiscal_year):
    candidates = [
        t
        for t in ledger.tranches_of_package(package["id"])
        if t["category"] == category and int(t["fiscal_year"]) == int(fiscal_year) + 1
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t["expires_on"], t["created_at"], t["_seq"]))
    return candidates[0]


def year_end_rollover(package, fiscal_year):
    # Step 1: read the eligibility ratio from the pre-rollover ledger.
    ratio = ledger.package_rollup(package)["spend_down_ratio"]
    eligible = ratio >= money.MIN_SPENDDOWN_RATIO_FOR_CARRYFORWARD
    # Step 2: select the subjects.
    subjects = rollover_subjects(package, fiscal_year)
    obligated_subjects = set()
    # Step 3: obligate what still carries open commitments.
    for tranche in subjects:
        if ledger.encumbered_balance(tranche) > 0:
            tranche["status"] = "OBLIGATED"
            obligated_subjects.add(tranche["id"])
            store.touch(tranche)
    for tranche in subjects:
        # Step 4: compute the carry-eligible amount.
        carry = carry_eligible_cents(tranche, eligible)
        # Step 5: find the destination and move the money.
        destination = None
        if carry > 0:
            destination = carryforward_destination(
                package, tranche["category"], fiscal_year
            )
            if destination is None:
                carry = 0
        if carry > 0:
            ledger.write_row(
                package,
                tranche,
                ledger.KIND_CARRYFORWARD_OUT,
                carry,
                ledger.SOURCE_ROLLOVER,
                None,
                "carried forward out of FY%s" % fiscal_year,
            )
            ledger.write_row(
                package,
                destination,
                ledger.KIND_CARRYFORWARD_IN,
                carry,
                ledger.SOURCE_ROLLOVER,
                None,
                "carried forward into FY%s" % (int(fiscal_year) + 1),
            )
        # Step 6: expire the residue and label the subject.
        leftover = ledger.available_balance(tranche)
        if leftover > 0:
            ledger.write_row(
                package,
                tranche,
                ledger.KIND_EXPIRY,
                leftover,
                ledger.SOURCE_ROLLOVER,
                None,
                "unspent balance expired at FY%s year end" % fiscal_year,
            )
        if tranche["id"] in obligated_subjects:
            continue
        tranche["status"] = "CARRIED_FORWARD" if carry > 0 else "EXPIRED"
        store.touch(tranche)
    # The rollover also opens next-year tranches that are now inside window.
    open_in_window_tranches(package)
    store.touch(package)
    return package


# ---------------------------------------------------------------------------
# Close-out (PRD 3.9)
# ---------------------------------------------------------------------------


def close_out(package):
    for tranche in ledger.tranches_of_package(package["id"]):
        if tranche["status"] not in ("SCHEDULED", "OPEN", "OBLIGATED", "CARRIED_FORWARD"):
            continue
        residual = ledger.available_balance(tranche)
        if residual <= 0:
            continue
        ledger.write_row(
            package,
            tranche,
            ledger.KIND_EXPIRY,
            residual,
            ledger.SOURCE_SETTLEMENT,
            None,
            "residual balance expired at close-out",
        )
        tranche["status"] = "EXPIRED"
        store.touch(tranche)
    package["negotiation_status"] = "CLOSED_OUT"
    package["spend_status"] = "SETTLED"
    package["closed_out_on"] = ledger.clock_iso()
    store.touch(package)
    return package


# ---------------------------------------------------------------------------
# The recommitment cascade (PRD 3.9)
# ---------------------------------------------------------------------------


def successor_destination(package, category):
    candidates = [
        t for t in ledger.tranches_of_package(package["id"]) if t["category"] == category
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda t: (t["expires_on"], int(t["fiscal_year"]), t["created_at"], t["_seq"])
    )
    return candidates[0]


def recommitment_cascade(successor, predecessor, faculty):
    for category in CATEGORY_ORDER:
        subjects = [
            t
            for t in ledger.tranches_of_package(predecessor["id"])
            if t["category"] == category
            and t["status"] in ("SCHEDULED", "OPEN", "CARRIED_FORWARD")
        ]
        moved = 0
        for tranche in subjects:
            amount = ledger.available_balance(tranche)
            if amount > 0:
                ledger.write_row(
                    predecessor,
                    tranche,
                    ledger.KIND_RECAPTURE,
                    amount,
                    ledger.SOURCE_SETTLEMENT,
                    None,
                    "unspent balance recaptured by retention counteroffer",
                )
                moved += amount
            tranche["status"] = "RECAPTURED"
            store.touch(tranche)
        if moved > 0:
            destination = successor_destination(successor, category)
            if destination is not None:
                ledger.write_row(
                    successor,
                    destination,
                    ledger.KIND_CARRYFORWARD_IN,
                    moved,
                    ledger.SOURCE_SETTLEMENT,
                    None,
                    "balance recommitted from superseded package",
                )
    predecessor["spend_status"] = "SETTLED"
    predecessor["negotiation_status"] = "SUPERSEDED"
    store.touch(predecessor)
    faculty["appointment_status"] = "ACTIVE"
    faculty["departure_intent"] = None
    faculty["departure_effective_on"] = None
    faculty["target_funding_unit_id"] = None
    faculty["retention_round"] = derive.retention_round(faculty["id"])
    store.touch(faculty)


# ---------------------------------------------------------------------------
# Separation: the terminal settlement (PRD 3.9)
# ---------------------------------------------------------------------------


def _settle_package_at_separation(package, intent, target_unit_id):
    subjects = [
        t
        for t in ledger.tranches_of_package(package["id"])
        if t["status"] in ("SCHEDULED", "OPEN")
    ]
    unspent = 0
    for tranche in subjects:
        amount = ledger.available_balance(tranche)
        if amount > 0:
            ledger.write_row(
                package,
                tranche,
                ledger.KIND_RECAPTURE,
                amount,
                ledger.SOURCE_SETTLEMENT,
                None,
                "unspent balance recaptured at separation",
            )
            unspent += amount
        tranche["status"] = "RECAPTURED"
        store.touch(tranche)
    if intent == "INTERNAL_TRANSFER" and target_unit_id is not None:
        holdback = money.pct_of_cents(unspent, money.COLLEGE_HOLDBACK_PCT)
        package["settlement_variant"] = "INTERNAL_TRANSFER"
        package["college_holdback_cents"] = holdback
        package["transferred_balance_cents"] = unspent - holdback
        package["recaptured_unspent_cents"] = holdback
        target = store.db.funding_units.get(target_unit_id)
        if target is not None and package["transferred_balance_cents"] > 0:
            target["cost_share_pool_cents"] = int(
                target["cost_share_pool_cents"]
            ) + package["transferred_balance_cents"]
            store.touch(target)
    else:
        package["settlement_variant"] = "DEPARTURE_RECAPTURE"
        package["recaptured_unspent_cents"] = unspent
        package["transferred_balance_cents"] = 0
        package["college_holdback_cents"] = 0
    store.touch(package)
    return unspent


DISPOSITION_BY_INTENT = {
    "DEPARTURE": "RETAINED_BY_UNIT",
    "INTERNAL_TRANSFER": "TRANSFERRED_WITH_FACULTY",
    "OUTSIDE_OFFER": "SURPLUSED",
}


def separation_cascade(faculty):
    intent = faculty["departure_intent"]
    target_unit_id = faculty["target_funding_unit_id"]
    moment = ledger.clock_iso()
    effective_end = date.fromisoformat(moment[:10])
    cancelled_project_spaces = set()

    for package in packages_of_faculty(faculty["id"], "ACTIVE"):
        for appointment in appointments_of_package(package["id"], ("ACTIVE",)):
            end_appointment(appointment, package, effective_end)
        for order in orders_of_package(
            package["id"], ("ORDERED", "DELIVERED", "UTILITY_BLOCKED")
        ):
            cancel_order(order, package)
        for project in projects_of_package(package["id"], ("SCOPING", "BID")):
            project["status"] = "CANCELLED"
            store.touch(project)
            cancelled_project_spaces.add(project["space_id"])
        for project in projects_of_package(package["id"], ("AWARDED", "IN_PROGRESS")):
            release_project_encumbrance(project, package)
        _settle_package_at_separation(package, intent, target_unit_id)
        disposition = DISPOSITION_BY_INTENT.get(intent)
        for order in orders_of_package(package["id"], ("INSTALLED",)):
            order["transfer_disposition"] = disposition
            store.touch(order)
        package["negotiation_status"] = "CLOSED_OUT"
        package["closed_out_on"] = moment
        package["spend_status"] = "SETTLED"
        store.touch(package)

    # The faculty member's own axis.
    if intent == "INTERNAL_TRANSFER":
        faculty["appointment_status"] = "TRANSFERRED_INTERNAL"
        if target_unit_id is not None:
            faculty["funding_unit_id"] = target_unit_id
    else:
        faculty["appointment_status"] = "DEPARTED"
    faculty["separated_on"] = moment
    store.touch(faculty)

    # Space is released as part of the same request.
    held_by_room = {}
    for assignment in derive.assignments_of_faculty(faculty["id"]):
        if assignment["status"] not in ("ACTIVE", "PROPOSED"):
            continue
        held_by_room[assignment["space_id"]] = held_by_room.get(
            assignment["space_id"], 0
        ) + int(assignment["share_pct"])
        if assignment["status"] == "ACTIVE":
            assignment["status"] = "RELEASED"
            assignment["released_on"] = moment
            assignment["effective_to"] = moment
        else:
            assignment["status"] = "WITHDRAWN"
        store.touch(assignment)
    for space_id, held in held_by_room.items():
        space = store.db.lab_spaces.get(space_id)
        if space is None:
            continue
        if held >= 100 and space_id in cancelled_project_spaces:
            space["status"] = "DECOMMISSIONED"
            store.touch(space)
            for other in derive.assignments_of_space(space_id):
                if other["status"] in ("PROPOSED", "ACTIVE"):
                    other["status"] = "WITHDRAWN"
                    store.touch(other)
        else:
            refresh_space_status(space)
    return faculty
