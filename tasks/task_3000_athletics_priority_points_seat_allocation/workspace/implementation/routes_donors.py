"""The donor book, gifts and season-ticket tenure (PRD sections 3.1, 3.2)."""
from decimal import Decimal

from flask import Blueprint

import auth
import clock
import derive
import envelope
import enums
import num
import serial
import validation as v
from errors import err, invalid, invalid_state
from store import DB, by_created_at, check_version, get_body_ref, get_path, new_row, touch

bp = Blueprint("donors", __name__)

ZERO = Decimal("0.00")


def _email_taken(email, skip_id=None):
    for row in DB.donors.values():
        if row["id"] != skip_id and row["email"].lower() == email.lower():
            return True
    return False


_SORT_FIELDS = {
    "created_at": lambda r: (r["created_at"], r["_seq"]),
    "full_name": lambda r: r["full_name"],
    "email": lambda r: r["email"],
    "certified_points": lambda r: num.dec(r["certified_points"]),
    "provisional_points": lambda r: num.dec(r["provisional_points"]),
    "cumulative_giving_cents": lambda r: int(r["cumulative_giving_cents"]),
    "consecutive_giving_years": lambda r: int(r["consecutive_giving_years"]),
    "season_ticket_seasons_purchased": lambda r: int(r["season_ticket_seasons_purchased"]),
    "rank_position": lambda r: (r["rank_position"] is None, r["rank_position"] or 0),
    "donor_status": lambda r: r["donor_status"],
    "updated_at": lambda r: (r["updated_at"], r["_seq"]),
}


def _sorted_donors(rows):
    """Default order is created_at ASC; `sort` may name another stored field."""
    raw = v.q_str("sort")
    if raw is None:
        return by_created_at(rows)
    spec = raw.strip()
    descending = False
    if spec.startswith("-"):
        descending = True
        spec = spec[1:]
    for separator in (":", " ", ","):
        if separator in spec:
            spec, _, direction = spec.partition(separator)
            if direction.strip().lower() in ("desc", "descending"):
                descending = True
            break
    spec = spec.strip()
    if spec.endswith("_desc"):
        descending = True
        spec = spec[: -len("_desc")]
    elif spec.endswith("_asc"):
        spec = spec[: -len("_asc")]
    key = _SORT_FIELDS.get(spec)
    if key is None:
        return by_created_at(rows)
    ordered = sorted(by_created_at(rows), key=key, reverse=descending)
    return ordered


@bp.get("/athletics/donors")
def list_donors():
    auth.require(auth.STAFF_ONLY)
    donor_status = v.q_enum("donor_status", enums.DONOR_STATUSES)
    alumni_status = v.q_enum("alumni_status", enums.ALUMNI_STATUSES)
    entity_type = v.q_enum("entity_type", enums.ENTITY_TYPES)
    partner_id = v.q_str("household_partner_donor_id")
    min_points = v.q_num("min_certified_points")
    rows = list(DB.donors.values())
    if donor_status is not None:
        rows = [r for r in rows if r["donor_status"] == donor_status]
    if alumni_status is not None:
        rows = [r for r in rows if r["alumni_status"] == alumni_status]
    if entity_type is not None:
        rows = [r for r in rows if r["entity_type"] == entity_type]
    if partner_id is not None:
        rows = [r for r in rows if r["household_partner_donor_id"] == partner_id]
    if min_points is not None:
        rows = [r for r in rows if num.dec(r["certified_points"]) >= min_points]
    return envelope.paginated(_sorted_donors(rows), serial.donor)


@bp.get("/athletics/donors/<donor_id>")
def get_donor(donor_id):
    auth.require(auth.STAFF_AND_DONOR)
    return envelope.ok(serial.donor(get_path("donor", donor_id)))


@bp.post("/athletics/donors")
def create_donor():
    auth.require(auth.OFFICE)
    body = v.body_dict()
    full_name = v.str_field(body, "full_name", min_len=1, max_len=120)
    email = v.str_field(body, "email", min_len=1, max_len=None)
    if "@" not in email:
        raise invalid("'email' must contain an at-sign")
    alumni_status = v.enum_field(body, "alumni_status", enums.ALUMNI_STATUSES)
    entity_type = v.enum_field(body, "entity_type", enums.ENTITY_TYPES)
    first_year = v.year_field(body, "season_ticket_first_cycle_year", required=False)
    if _email_taken(email):
        raise invalid("'email' is already registered to another donor")
    row = new_row(
        full_name=full_name,
        email=email,
        alumni_status=alumni_status,
        entity_type=entity_type,
        donor_status="ACTIVE",
        status_effective_date=clock.now(),
        household_partner_donor_id=None,
        season_ticket_first_cycle_year=first_year,
        season_ticket_seasons_purchased=0,
        cumulative_giving_cents=0,
        consecutive_giving_years=0,
        provisional_points=ZERO,
        certified_base_points=ZERO,
        certified_points=ZERO,
        transferred_points_in=ZERO,
        transferred_points_out=ZERO,
        dispute_adjustment_points=ZERO,
        rank_position=None,
        pending_request_count=0,
    )
    row["_season_years"] = []
    DB.donors[row["id"]] = row
    return envelope.created(serial.donor(row))


@bp.post("/athletics/donors/<donor_id>/status-change")
def change_donor_status(donor_id):
    auth.require(auth.OFFICE)
    donor = get_path("donor", donor_id)
    body = v.body_dict()
    new_status = v.enum_field(body, "new_status", enums.DONOR_STATUSES)
    effective_date = v.instant_field(body, "effective_date")
    v.str_field(body, "reason", min_len=1, max_len=None)
    expected = v.version_field(body, "expected_donor_version")
    check_version(donor, expected, "donor")
    current = donor["donor_status"]
    if (current, new_status) not in enums.DONOR_TRANSITIONS:
        raise invalid_state(
            "donor_status '%s' does not admit a move to '%s'" % (current, new_status))
    if new_status == "LAPSED" and effective_date > clock.now():
        raise invalid_state("'effective_date' may not be later than the current instant")
    if new_status == "DISSOLVED_ENTITY" and donor["entity_type"] not in (
            "CORPORATION", "FOUNDATION"):
        raise invalid_state(
            "only a CORPORATION or FOUNDATION donor may be dissolved")
    donor["donor_status"] = new_status
    donor["status_effective_date"] = effective_date
    touch(donor)
    return envelope.ok(serial.donor(donor))


@bp.post("/athletics/donors/<donor_id>/household-link")
def link_household(donor_id):
    auth.require(auth.OFFICE)
    donor = get_path("donor", donor_id)
    body = v.body_dict()
    partner_id = v.id_field(body, "partner_donor_id")
    expected = v.version_field(body, "expected_donor_version")
    partner = get_body_ref("donor", partner_id)
    check_version(donor, expected, "donor")
    if partner["id"] == donor["id"]:
        raise err("ERR_HOUSEHOLD_LINK_INVALID",
                  "a donor may not be linked to themselves")
    if donor["entity_type"] != "JOINT_HOUSEHOLD" or partner["entity_type"] != "JOINT_HOUSEHOLD":
        raise err("ERR_HOUSEHOLD_LINK_INVALID",
                  "both donors must carry entity_type JOINT_HOUSEHOLD")
    existing = donor["household_partner_donor_id"]
    if existing is not None and existing != partner["id"]:
        raise err("ERR_HOUSEHOLD_LINK_INVALID",
                  "this donor is already linked to a different partner")
    partner_existing = partner["household_partner_donor_id"]
    if partner_existing is not None and partner_existing != donor["id"]:
        raise err("ERR_HOUSEHOLD_LINK_INVALID",
                  "the partner is already linked to a different donor")
    donor["household_partner_donor_id"] = partner["id"]
    partner["household_partner_donor_id"] = donor["id"]
    touch(donor)
    touch(partner)
    return envelope.ok(serial.donor(donor))


# ---------------------------------------------------------------------------
# Gifts (PRD section 3.2)
# ---------------------------------------------------------------------------
@bp.get("/athletics/donors/<donor_id>/gifts")
def list_donor_gifts(donor_id):
    auth.require(auth.STAFF_AND_DONOR)
    donor = get_path("donor", donor_id)
    gift_status = v.q_enum("gift_status", enums.GIFT_STATUSES)
    cycle_year = v.q_int("cycle_year")
    designation = v.q_enum("designation", enums.DESIGNATIONS)
    rows = [g for g in DB.gifts.values() if g["donor_id"] == donor["id"]]
    if gift_status is not None:
        rows = [g for g in rows if g["gift_status"] == gift_status]
    if cycle_year is not None:
        rows = [g for g in rows if int(g["cycle_year"]) == cycle_year]
    if designation is not None:
        rows = [g for g in rows if g["designation"] == designation]
    return envelope.paginated(by_created_at(rows), serial.gift)


@bp.post("/athletics/donors/<donor_id>/gifts")
def create_gift(donor_id):
    auth.require(auth.OFFICE)
    donor = get_path("donor", donor_id)
    body = v.body_dict()
    gift_date = v.instant_field(body, "gift_date")
    amount_cents = v.int_field(body, "amount_cents", minimum=1)
    designation = v.enum_field(body, "designation", enums.DESIGNATIONS)
    gift_status = v.enum_field(body, "gift_status", enums.GIFT_STATUSES,
                               required=False, default="PLEDGED")
    cycle_year = clock.utc_year(gift_date)
    if cycle_year < 1900 or cycle_year > 2100:
        raise invalid("'gift_date' must fall in a calendar year between 1900 and 2100")
    settled = None if gift_status == "PLEDGED" else clock.now()
    row = new_row(
        donor_id=donor["id"],
        gift_date=gift_date,
        cycle_year=cycle_year,
        amount_cents=amount_cents,
        designation=designation,
        gift_status=gift_status,
        counts_toward_points=designation in ("ATHLETICS_ANNUAL", "CAPITAL"),
        settled_at=settled,
    )
    DB.gifts[row["id"]] = row
    if gift_status == "RECEIVED":
        donor["cumulative_giving_cents"] = int(donor["cumulative_giving_cents"]) + amount_cents
        touch(donor)
    return envelope.created(serial.gift(row))


@bp.post("/athletics/gifts/<gift_id>/settle")
def settle_gift(gift_id):
    auth.require(auth.OFFICE)
    gift = get_path("gift", gift_id)
    body = v.body_dict()
    new_status = v.enum_field(body, "new_status", enums.GIFT_SETTLE_STATUSES)
    current = gift["gift_status"]
    if new_status == "RECEIVED" and current != "PLEDGED":
        raise invalid_state("only a PLEDGED gift may be settled as RECEIVED")
    if new_status == "REFUNDED" and current not in ("PLEDGED", "RECEIVED"):
        raise invalid_state("only a PLEDGED or RECEIVED gift may be refunded")
    donor = DB.donors.get(gift["donor_id"])
    gift["gift_status"] = new_status
    gift["settled_at"] = clock.now()
    if new_status == "RECEIVED":
        gift["counts_toward_points"] = gift["designation"] in ("ATHLETICS_ANNUAL", "CAPITAL")
        if donor is not None:
            donor["cumulative_giving_cents"] = (
                int(donor["cumulative_giving_cents"]) + int(gift["amount_cents"]))
            touch(donor)
    else:
        gift["counts_toward_points"] = False
        if current == "RECEIVED" and donor is not None:
            donor["cumulative_giving_cents"] = (
                int(donor["cumulative_giving_cents"]) - int(gift["amount_cents"]))
            touch(donor)
    touch(gift)
    return envelope.ok(serial.gift(gift))


@bp.post("/athletics/donors/<donor_id>/season-ticket-renewals")
def record_season_ticket_renewal(donor_id):
    auth.require(auth.OFFICE)
    donor = get_path("donor", donor_id)
    body = v.body_dict()
    cycle_year = v.year_field(body, "cycle_year")
    recorded = donor.setdefault("_season_years", [])
    if cycle_year not in recorded:
        recorded.append(cycle_year)
        donor["season_ticket_seasons_purchased"] = len(recorded)
        if donor["season_ticket_first_cycle_year"] is None:
            donor["season_ticket_first_cycle_year"] = cycle_year
        touch(donor)
    return envelope.ok(serial.donor(donor))


@bp.get("/athletics/donors/<donor_id>/point-transfers")
def list_donor_transfers(donor_id):
    auth.require(auth.NO_ANALYST)
    donor = get_path("donor", donor_id)
    status = v.q_enum("status", enums.TRANSFER_STATUSES)
    basis = v.q_enum("basis", enums.TRANSFER_BASES)
    rows = [t for t in DB.transfers.values()
            if t["source_donor_id"] == donor["id"]
            or t["recipient_donor_id"] == donor["id"]]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if basis is not None:
        rows = [t for t in rows if t["basis"] == basis]
    return envelope.paginated(by_created_at(rows), serial.transfer)
