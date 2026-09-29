"""The membership book: categories, households, the waitlist queue and
memberships with their invoices, payments and write-offs.

PRD §3.2, §3.3 and §3.4.
"""
from flask import Blueprint, request

import clock
import constants as C
import engine as E
import validation as V
from auth import guard, require_owner
from envelope import created, ok, ok_list
from errors import fail
from money import D, round_half_up
from store import DB, serialize, serialize_many

bp = Blueprint("book", __name__)

CATEGORY_READ_ROLES = (
    "MembershipChair",
    "Treasurer",
    "BoardPresident",
    "PoolManager",
    "Member",
)
HOUSEHOLD_READ_ROLES = (
    "MembershipChair",
    "Treasurer",
    "BoardPresident",
    "PoolManager",
    "Member",
)
HOUSEHOLD_LIST_ROLES = ("MembershipChair", "Treasurer", "BoardPresident", "PoolManager")
WAITLIST_ROLES = ("MembershipChair", "BoardPresident", "Member")
MEMBERSHIP_READ_ROLES = (
    "MembershipChair",
    "Treasurer",
    "BoardPresident",
    "PoolManager",
    "SwimTeamCoach",
    "Member",
)

# ------------------------------------------------------------- categories §3.2
CATEGORY_SPECS = [
    V.f("code", "enum", enum=C.CATEGORY_CODE),
    V.f("label", "string"),
    V.f("bond_cents", "int", minimum=0),
    V.f("initiation_fee_cents", "int", minimum=0),
    V.f("seasonal_dues_cents", "int", minimum=0),
    V.f("guest_pass_allotment", "int", minimum=0),
    V.f("max_household_size", "int", minimum=1),
    V.f("volunteer_credits_required", "int", minimum=0),
    V.f("waitlist_required", "bool", required=False, default=False),
    V.f("proration_allowed", "bool", required=False, default=True),
    V.f("party_privileges", "bool", required=False, default=True),
]


@bp.route("/membership-categories", methods=["POST"])
def create_category():
    guard(("MembershipChair",))
    body = V.body_of(request)
    values = V.validate(body, CATEGORY_SPECS)
    for existing in DB.all("membership_categories"):
        if existing["code"] == values["code"]:
            fail("ERR_VALIDATION", "Category code %s already exists." % values["code"])
    category = DB.insert("membership_categories", dict(values))
    return created(serialize(category))


@bp.route("/membership-categories/<category_id>", methods=["GET"])
def read_category(category_id):
    guard(CATEGORY_READ_ROLES)
    return ok(serialize(E.need("membership_categories", category_id)))


@bp.route("/membership-categories", methods=["GET"])
def list_categories():
    guard(CATEGORY_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("membership_categories"),
        request,
        string_fields=("code",),
        bool_fields=("waitlist_required",),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# -------------------------------------------------------------- households §3.2
HOUSEHOLD_SPECS = [
    V.f("primary_contact_name", "string"),
    V.f("address_line", "string"),
    V.f("residency", "enum", enum=C.RESIDENCY),
    V.f("member_count", "int", required=False, default=1, minimum=1),
    V.f("transferred_from_household_id", "string", required=False),
    V.f("prior_member", "bool", required=False, default=False),
]


@bp.route("/households", methods=["POST"])
def create_household():
    guard(("MembershipChair",))
    body = V.body_of(request)
    values = V.validate(body, HOUSEHOLD_SPECS)

    source = None
    if values["transferred_from_household_id"]:
        source = E.need("households", values["transferred_from_household_id"])

    fields = {
        "primary_contact_name": values["primary_contact_name"],
        "address_line": values["address_line"],
        "residency": values["residency"],
        "member_count": values["member_count"],
        "transferred_from_household_id": values["transferred_from_household_id"],
        "bond_status": "NONE",
        "bond_paid_cents": 0,
        "prior_member": bool(values["prior_member"]),
        "standing": "GOOD_STANDING",
        "conduct_points": 0,
        "guest_pass_allotment_granted": 0,
        "guest_passes_consumed": 0,
        "guest_pass_balance": 0,
        "guest_fee_owed_cents": 0,
        "party_charges_owed_cents": 0,
        "account_credit_cents": 0,
    }
    if source is not None:
        fields["bond_status"] = "TRANSFERRED"
        fields["bond_paid_cents"] = source["bond_paid_cents"]
        fields["prior_member"] = True
    household = DB.insert("households", fields)
    return created(serialize(household))


STANDING_SPECS = [
    V.f("to_standing", "enum", enum=C.HOUSEHOLD_STANDING),
    V.f("reason", "string"),
]


@bp.route("/households/<household_id>/standing-transitions", methods=["POST"])
def household_standing(household_id):
    guard(("BoardPresident",))
    body = V.body_of(request)
    values = V.validate(body, STANDING_SPECS)
    household = E.need("households", household_id)
    target = values["to_standing"]

    if household["standing"] == "EXPELLED":
        fail("ERR_ALREADY_TERMINAL", "An expelled household has no path back.")
    if C.STANDING_RANK[target] >= C.STANDING_RANK[household["standing"]]:
        fail(
            "ERR_INVALID_TRANSITION",
            "This operation only softens a standing; %s does not soften %s."
            % (target, household["standing"]),
        )
    if target == "GOOD_STANDING":
        for case in E.rows_where("conduct_cases", household_id=household["id"]):
            if case["status"] in ("REPORTED", "UNDER_REVIEW", "APPEALED"):
                fail(
                    "ERR_INVALID_TRANSITION",
                    "A household with a live conduct case may not be cleared.",
                )

    household["standing"] = target
    DB.touch(household)
    for membership in E.memberships_of_household(household["id"]):
        if membership["access_status"] == "SUSPENDED":
            membership["access_status"] = "ACTIVE"
            DB.touch(membership)
    return ok(serialize(household))


HOUSEHOLD_PAYMENT_SPECS = [
    V.f("amount_cents", "int", minimum=0),
    V.f("allocation", "enum", enum=C.HOUSEHOLD_PAYMENT_ALLOCATION),
]


@bp.route("/households/<household_id>/payments", methods=["POST"])
def household_payment(household_id):
    caller = guard(("Treasurer", "Member"))
    require_owner(caller, household_id)
    body = V.body_of(request)
    values = V.validate(body, HOUSEHOLD_PAYMENT_SPECS)
    household = E.need("households", household_id)
    amount = values["amount_cents"]
    allocation = values["allocation"]

    if allocation == "GUEST_FEES":
        if amount > household["guest_fee_owed_cents"]:
            fail("ERR_PAYMENT_EXCEEDS_BALANCE", "The payment exceeds the guest fees owed.")
        household["guest_fee_owed_cents"] -= amount
    elif allocation == "PARTY_CHARGES":
        if amount > household["party_charges_owed_cents"]:
            fail(
                "ERR_PAYMENT_EXCEEDS_BALANCE",
                "The payment exceeds the party charges owed.",
            )
        household["party_charges_owed_cents"] -= amount
    else:
        category = E.latest_category_of_household(household)
        bond_cents = category["bond_cents"] if category else 0
        ceiling = bond_cents - household["bond_paid_cents"]
        if ceiling < 0:
            ceiling = 0
        if amount > ceiling:
            fail("ERR_PAYMENT_EXCEEDS_BALANCE", "The payment exceeds the bond still owed.")
        household["bond_paid_cents"] += amount
        if household["bond_status"] in ("NONE", "INSTALLMENTS"):
            if category is not None and household["bond_paid_cents"] >= bond_cents:
                household["bond_status"] = "PAID"
    DB.touch(household)
    return ok(serialize(household))


@bp.route("/households/<household_id>", methods=["GET"])
def read_household(household_id):
    caller = guard(HOUSEHOLD_READ_ROLES)
    require_owner(caller, household_id)
    return ok(serialize(E.need("households", household_id)))


@bp.route("/households", methods=["GET"])
def list_households():
    guard(HOUSEHOLD_LIST_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("households"),
        request,
        string_fields=(
            "standing",
            "residency",
            "bond_status",
            "transferred_from_household_id",
        ),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# ---------------------------------------------------------- the queue §3.2
WAITLIST_SPECS = [
    V.f("household_id", "string"),
    V.f("membership_category_id", "string"),
    V.f("priority_tier", "enum", required=False, default="STANDARD",
        enum=C.PRIORITY_TIER),
]


@bp.route("/waitlist-entries", methods=["POST"])
def create_waitlist_entry():
    caller = guard(("MembershipChair", "Member"))
    body = V.body_of(request)
    values = V.validate(body, WAITLIST_SPECS)
    require_owner(caller, values["household_id"])
    category = E.need("membership_categories", values["membership_category_id"])
    household = E.need("households", values["household_id"])

    if household["standing"] in ("SUSPENDED", "EXPELLED"):
        fail("ERR_HOUSEHOLD_SUSPENDED", "A suspended household may not join the queue.")
    for entry in E.rows_where(
        "waitlist_entries",
        household_id=household["id"],
        membership_category_id=category["id"],
    ):
        if entry["status"] in ("WAITING", "OFFERED", "ACCEPTED"):
            fail(
                "ERR_DUPLICATE_WAITLIST_ENTRY",
                "The household already holds a live entry for this category.",
            )
    if household["member_count"] > category["max_household_size"]:
        fail(
            "ERR_HOUSEHOLD_SIZE_EXCEEDED",
            "The household exceeds the category's household-size cap.",
        )

    tier = values["priority_tier"]
    entry = DB.insert(
        "waitlist_entries",
        {
            "household_id": household["id"],
            "membership_category_id": category["id"],
            "priority_tier": tier,
            "priority_tier_rank": C.PRIORITY_TIER_RANK[tier],
            "status": "WAITING",
            "deferral_count": 0,
            "offered_at": None,
            "offer_expires_at": None,
            "requeued_at": None,
            "queue_key_at": None,
        },
    )
    entry["queue_key_at"] = entry["created_at"]
    return created(serialize(entry))


NEXT_OFFER_SPECS = [V.f("membership_category_id", "string")]


@bp.route("/waitlist-entries/next-offer", methods=["POST"])
def next_offer():
    guard(("MembershipChair",))
    body = V.body_of(request)
    values = V.validate(body, NEXT_OFFER_SPECS)
    category = E.need("membership_categories", values["membership_category_id"])
    winner = E.select_offer_candidate(category["id"])
    if winner is None:
        fail("ERR_WAITLIST_EMPTY", "No eligible entry is waiting in this category.")
    E.make_offer(winner)
    return ok(serialize(winner))


RESPOND_SPECS = [
    V.f("decision", "enum", enum=C.WAITLIST_DECISION),
    V.f("requeue", "bool", required=False, default=False),
]
WAITLIST_TERMINAL = ("ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN")


@bp.route("/waitlist-entries/<entry_id>/respond", methods=["POST"])
def respond_waitlist(entry_id):
    caller = guard(("Member", "MembershipChair"))
    known = DB.get("waitlist_entries", entry_id)
    if known is not None:
        require_owner(caller, known["household_id"])
    body = V.body_of(request)
    values = V.validate(body, RESPOND_SPECS)
    entry = E.need("waitlist_entries", entry_id)
    decision = values["decision"]

    if entry["status"] in WAITLIST_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This waitlist entry is already resolved.")

    # PRD §2.9 band 11 orders "the waitlist offer is live (ERR_OFFER_EXPIRED,
    # 409); the deferral budget is not exhausted (ERR_MAX_DEFERRALS_REACHED,
    # 409)". Those two codes can only both be in play on a requeueing decline, so
    # the offer-live check guards every response that acts on a live offer, not
    # just the acceptance, and it is evaluated ahead of the deferral budget.
    if decision in ("ACCEPT", "DECLINE") and entry["status"] == "OFFERED":
        expires = clock.parse_instant(entry["offer_expires_at"]) if entry["offer_expires_at"] else None
        if expires is not None and clock.now() > expires:
            fail("ERR_OFFER_EXPIRED", "The offer window has passed.")

    if decision == "ACCEPT":
        if entry["status"] != "OFFERED":
            fail("ERR_INVALID_TRANSITION", "Only an offered entry may be accepted.")
        entry["status"] = "ACCEPTED"
    elif decision == "DECLINE":
        if entry["status"] != "OFFERED":
            fail("ERR_INVALID_TRANSITION", "Only an offered entry may be declined.")
        if values["requeue"]:
            if entry["deferral_count"] >= C.MAX_DEFERRALS:
                fail("ERR_MAX_DEFERRALS_REACHED", "The deferral budget is exhausted.")
            stamp = clock.now_iso()
            entry["status"] = "WAITING"
            entry["deferral_count"] += 1
            entry["requeued_at"] = stamp
            entry["queue_key_at"] = stamp
            entry["offered_at"] = None
            entry["offer_expires_at"] = None
        else:
            entry["status"] = "DECLINED"
    else:
        if entry["status"] != "WAITING":
            fail("ERR_INVALID_TRANSITION", "Only a waiting entry may be withdrawn.")
        entry["status"] = "WITHDRAWN"

    DB.touch(entry)
    return ok(serialize(entry))


@bp.route("/waitlist-entries/<entry_id>", methods=["GET"])
def read_waitlist_entry(entry_id):
    caller = guard(WAITLIST_ROLES)
    known = DB.get("waitlist_entries", entry_id)
    if known is not None:
        require_owner(caller, known["household_id"])
    return ok(serialize(E.need("waitlist_entries", entry_id)))


@bp.route("/waitlist-entries", methods=["GET"])
def list_waitlist_entries():
    guard(WAITLIST_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("waitlist_entries"),
        request,
        string_fields=(
            "household_id",
            "membership_category_id",
            "status",
            "priority_tier",
        ),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# ------------------------------------------------------- memberships §3.3/§3.4
MEMBERSHIP_SPECS = [
    V.f("household_id", "string"),
    V.f("membership_category_id", "string"),
    V.f("season_id", "string"),
    V.f("join_date", "date"),
    V.f("bond_payment_plan", "enum", required=False, enum=C.BOND_PAYMENT_PLAN),
]


@bp.route("/memberships", methods=["POST"])
def create_membership():
    guard(("MembershipChair",))
    body = V.body_of(request)
    values = V.validate(body, MEMBERSHIP_SPECS)
    season = E.need("seasons", values["season_id"])
    category = E.need("membership_categories", values["membership_category_id"])
    household = E.need("households", values["household_id"])

    if season["status"] != "OPEN":
        fail("ERR_SEASON_NOT_OPEN", "The season is not open for business.")
    if household["standing"] in ("SUSPENDED", "EXPELLED"):
        fail("ERR_HOUSEHOLD_SUSPENDED", "A suspended household may not buy a membership.")

    join_date = clock.parse_date(values["join_date"])
    open_date = clock.parse_date(season["open_date"])
    close_date = clock.parse_date(season["close_date"])
    if join_date < open_date or join_date > close_date:
        fail("ERR_OUTSIDE_SEASON_WINDOW", "join_date falls outside the season window.")

    for existing in E.memberships_of_household(household["id"]):
        if existing["season_id"] != season["id"]:
            continue
        if existing["access_status"] not in ("LAPSED", "TERMINATED"):
            fail(
                "ERR_DUPLICATE_MEMBERSHIP",
                "The household already holds a membership for this season.",
            )
    if household["member_count"] > category["max_household_size"]:
        fail(
            "ERR_HOUSEHOLD_SIZE_EXCEEDED",
            "The household exceeds the category's household-size cap.",
        )

    if category["waitlist_required"]:
        accepted = [
            entry
            for entry in E.rows_where("waitlist_entries", household_id=household["id"])
            if entry["status"] == "ACCEPTED"
        ]
        if not accepted:
            fail(
                "ERR_WAITLIST_OFFER_REQUIRED",
                "This category is purchasable only against an accepted waitlist entry.",
            )
        if not any(e["membership_category_id"] == category["id"] for e in accepted):
            fail(
                "ERR_CATEGORY_MISMATCH",
                "The accepted waitlist entry names a different category.",
            )

    initiation = 0 if household["prior_member"] else category["initiation_fee_cents"]
    membership = DB.insert(
        "memberships",
        {
            "household_id": household["id"],
            "membership_category_id": category["id"],
            "season_id": season["id"],
            "join_date": values["join_date"],
            "bond_payment_plan": values["bond_payment_plan"],
            "dues_status": "UNBILLED",
            "access_status": "PENDING",
            "assessed_dues_cents": E.assess_dues(category, season, join_date),
            "initiation_fee_cents": initiation,
            "bond_installment_cents": 0,
            "swim_team_fee_cents": 0,
            "late_penalty_cents": 0,
            "invoice_total_cents": 0,
            "amount_paid_cents": 0,
            "balance_due_cents": 0,
            "invoiced_at": None,
            "volunteer_credits_required": 0,
            "volunteer_credits_earned": 0,
            "volunteer_buyout_cents": 0,
        },
    )

    household["guest_pass_allotment_granted"] += category["guest_pass_allotment"]
    household["guest_pass_balance"] += category["guest_pass_allotment"]
    household["prior_member"] = True
    if values["bond_payment_plan"] == "INSTALLMENTS" and household["bond_status"] == "NONE":
        household["bond_status"] = "INSTALLMENTS"
    DB.touch(household)
    return created(serialize(membership))


@bp.route("/memberships/<membership_id>/invoice", methods=["POST"])
def invoice_membership(membership_id):
    guard(("Treasurer",))
    membership = E.need("memberships", membership_id)
    season = E.season_of_membership(membership)
    category = E.category_of_membership(membership)

    if season is not None and season["status"] not in ("PLANNED", "OPEN"):
        fail("ERR_SEASON_NOT_OPEN", "A closed season cannot be invoiced against.")
    if membership["dues_status"] == "WRITTEN_OFF":
        fail("ERR_ALREADY_TERMINAL", "A written-off membership cannot be invoiced.")
    if membership["dues_status"] != "UNBILLED":
        fail("ERR_INVALID_TRANSITION", "The invoice is cut exactly once, from UNBILLED.")

    plan = membership["bond_payment_plan"]
    bond_cents = category["bond_cents"] if category else 0
    if plan == "FULL":
        bond_line = bond_cents
    elif plan == "INSTALLMENTS":
        bond_line = round_half_up(D(bond_cents) * C.BOND_INSTALLMENT_RATE)
    else:
        bond_line = 0
    membership["bond_installment_cents"] = bond_line
    E.recompute_swim_fee(membership)

    base = (
        membership["assessed_dues_cents"]
        + membership["initiation_fee_cents"]
        + bond_line
        + membership["swim_team_fee_cents"]
    )
    penalty = 0
    due_date = clock.parse_date(season["dues_due_date"]) if season else None
    if due_date is not None and clock.today() > due_date:
        penalty = round_half_up(D(base) * C.LATE_PENALTY_RATE)
    membership["late_penalty_cents"] = penalty
    membership["invoice_total_cents"] = base + penalty
    membership["balance_due_cents"] = (
        membership["invoice_total_cents"]
        + membership["volunteer_buyout_cents"]
        - membership["amount_paid_cents"]
    )
    if membership["balance_due_cents"] < 0:
        membership["balance_due_cents"] = 0
    membership["dues_status"] = "INVOICED"
    membership["invoiced_at"] = clock.now_iso()

    household = E.household_of_membership(membership)
    if (
        membership["access_status"] == "PENDING"
        and household is not None
        and household["standing"] == "GOOD_STANDING"
    ):
        membership["access_status"] = "ACTIVE"
    if household is not None and plan == "INSTALLMENTS" and household["bond_status"] == "NONE":
        household["bond_status"] = "INSTALLMENTS"
        DB.touch(household)
    DB.touch(membership)
    return ok(serialize(membership))


MEMBERSHIP_PAYMENT_SPECS = [
    V.f("amount_cents", "int", minimum=0),
    V.f("allocation", "enum", required=False, default="DUES",
        enum=C.MEMBERSHIP_PAYMENT_ALLOCATION),
]


@bp.route("/memberships/<membership_id>/payments", methods=["POST"])
def membership_payment(membership_id):
    caller = guard(("Treasurer", "Member"))
    known = DB.get("memberships", membership_id)
    if known is not None:
        require_owner(caller, known["household_id"])
    body = V.body_of(request)
    values = V.validate(body, MEMBERSHIP_PAYMENT_SPECS)
    membership = E.need("memberships", membership_id)

    if membership["dues_status"] == "WRITTEN_OFF":
        fail("ERR_ALREADY_TERMINAL", "A written-off membership takes no further payment.")
    if membership["dues_status"] not in ("INVOICED", "DELINQUENT"):
        fail("ERR_INVALID_TRANSITION", "Payments are accepted only once invoiced.")

    amount = values["amount_cents"]
    if amount > membership["balance_due_cents"]:
        fail("ERR_PAYMENT_EXCEEDS_BALANCE", "The payment exceeds the balance due.")

    household = E.household_of_membership(membership)
    category = E.category_of_membership(membership)
    if values["allocation"] == "BOND" and household is not None:
        household["bond_paid_cents"] += amount
        if household["bond_status"] in ("NONE", "INSTALLMENTS"):
            if category is not None and household["bond_paid_cents"] >= category["bond_cents"]:
                household["bond_status"] = "PAID"
        DB.touch(household)

    membership["amount_paid_cents"] += amount
    membership["balance_due_cents"] -= amount
    if membership["balance_due_cents"] < 0:
        membership["balance_due_cents"] = 0
    if membership["balance_due_cents"] == 0:
        E.settle_to_paid(membership)
    DB.touch(membership)
    return ok(serialize(membership))


WRITE_OFF_SPECS = [V.f("reason", "string")]


@bp.route("/memberships/<membership_id>/write-off", methods=["POST"])
def write_off_membership(membership_id):
    guard(("Treasurer",))
    body = V.body_of(request)
    V.validate(body, WRITE_OFF_SPECS)
    membership = E.need("memberships", membership_id)

    if membership["dues_status"] == "WRITTEN_OFF":
        fail("ERR_ALREADY_TERMINAL", "The balance is already written off.")
    if membership["dues_status"] != "DELINQUENT":
        fail("ERR_INVALID_TRANSITION", "Only a delinquent balance may be written off.")

    membership["balance_due_cents"] = 0
    membership["dues_status"] = "WRITTEN_OFF"
    if membership["access_status"] == "ACTIVE":
        membership["access_status"] = "SUSPENDED"
        DB.touch(membership)
        E.membership_suspension_effects(membership)
    DB.touch(membership)
    return ok(serialize(membership))


@bp.route("/memberships/<membership_id>", methods=["GET"])
def read_membership(membership_id):
    caller = guard(MEMBERSHIP_READ_ROLES)
    known = DB.get("memberships", membership_id)
    if known is not None:
        require_owner(caller, known["household_id"])
    return ok(serialize(E.need("memberships", membership_id)))


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    guard(MEMBERSHIP_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("memberships"),
        request,
        string_fields=(
            "household_id",
            "membership_category_id",
            "season_id",
            "dues_status",
            "access_status",
        ),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)
