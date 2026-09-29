"""Registry writes: proponents, species, critical habitat, banks, the clock."""
from flask import Blueprint

import auth
import calc
import cascades
import envelope
import resolve
import serialize
import shape
import store
import util
from errors import ApiError

bp = Blueprint("registry", __name__)

AGENCY = ("WildlifeAgency",)
ANY_ROLE = ("Proponent", "WildlifeAgency", "Auditor")


@bp.route("/proponents", methods=["POST"])
def register_proponent():
    # Self-registration is exempt from the header-presence check altogether.
    auth.authenticate(("Anonymous",), presence_exempt=True)
    body = shape.Body()
    org_name = body.string("org_name", 1, 160)
    contact_email = body.email("contact_email", 5, 160)
    is_federal_agency = body.boolean("is_federal_agency", required=False,
                                     default=False)
    body.close()

    row = store.new_row(
        org_name=org_name,
        contact_email=contact_email,
        is_federal_agency=is_federal_agency,
        compliance_standing_score=util.q2(100),
        compliance_variant_applied="LIFETIME",
        open_reinitiation_count=0,
    )
    store.insert("proponents", row)
    return envelope.created(serialize.proponent(row))


@bp.route("/species", methods=["POST"])
def register_species():
    auth.authenticate(AGENCY)
    body = shape.Body()
    scientific_name = body.string("scientific_name", 1, 120)
    common_name = body.string("common_name", 1, 120)
    listing_status = body.enum("listing_status", calc.LISTING_STATUSES)
    take_authorization_unit = body.enum("take_authorization_unit",
                                        calc.TAKE_UNITS)
    take_density_per_acre = body.quantity("take_density_per_acre")
    recovery_unit_population = body.integer("recovery_unit_population", lo=1)
    start_month = body.integer("survey_season_start_month", lo=1, hi=12)
    end_month = body.integer("survey_season_end_month", lo=1, hi=12)
    body.close()

    for existing in store.values("species"):
        if existing["scientific_name"] == scientific_name:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "scientific_name is already present in the register.",
            )

    row = store.new_row(
        scientific_name=scientific_name,
        common_name=common_name,
        listing_status=listing_status,
        critical_habitat_designated=False,
        take_authorization_unit=take_authorization_unit,
        take_density_per_acre=take_density_per_acre,
        recovery_unit_population=recovery_unit_population,
        survey_season_start_month=start_month,
        survey_season_end_month=end_month,
        listing_change_count=0,
        last_listing_change_at=None,
    )
    store.insert("species", row)
    return envelope.created(serialize.species(row))


@bp.route("/species/<sid>/critical-habitat-units", methods=["POST"])
def designate_habitat_unit(sid):
    auth.authenticate(AGENCY)
    species = resolve.species(sid)
    body = shape.Body()
    unit_code = body.string("unit_code", 3, 24)
    acres = body.quantity("acres", positive=True)
    county_code = body.digits("county_code", 5)
    designation_status = body.enum("designation_status",
                                   calc.DESIGNATION_STATUSES)
    elements = body.str_array("primary_constituent_elements", 1, 8, 1, 80)
    body.close()

    for existing in store.values("habitat_units"):
        if existing["species_id"] == sid and existing["unit_code"] == unit_code:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "unit_code is already used by this species.",
            )

    row = store.new_row(
        species_id=sid,
        unit_code=unit_code,
        acres=acres,
        county_code=county_code,
        designation_status=designation_status,
        primary_constituent_elements=elements,
    )
    store.insert("habitat_units", row)

    designated = any(
        unit["species_id"] == sid and unit["designation_status"] == "FINAL"
        for unit in store.values("habitat_units")
    )
    species["critical_habitat_designated"] = designated
    store.touch(species)
    return envelope.created(serialize.habitat_unit(row))


@bp.route("/species/<sid>/listing-change", methods=["POST"])
def record_listing_change(sid):
    auth.authenticate(AGENCY)
    species = resolve.species(sid)
    body = shape.Body()
    new_status = body.enum("new_listing_status", calc.LISTING_STATUSES)
    body.string("rationale", 1)
    body.close()

    old_rank = calc.LISTING_RANK[species["listing_status"]]
    new_rank = calc.LISTING_RANK[new_status]

    species["listing_status"] = new_status
    species["listing_change_count"] = species["listing_change_count"] + 1
    species["last_listing_change_at"] = store.now()
    store.touch(species)

    # Only raising the rank starts the uplisting cascade.
    if new_rank > old_rank:
        cascades.uplisting_cascade(species)

    return envelope.obj(serialize.species(species))


@bp.route("/conservation-banks", methods=["POST"])
def establish_bank():
    auth.authenticate(AGENCY)
    # Rung 6: the body foreign key resolves before the body is shape-checked.
    covered_species_id = shape.peek_str("covered_species_id")
    species = None
    if covered_species_id is not None:
        species = resolve.species(covered_species_id)

    body = shape.Body()
    bank_name = body.string("bank_name", 1, 160)
    body.ident("covered_species_id")
    counties = body.str_array("service_area_county_codes", 1, 12, width=5)
    credit_price_cents = body.money("credit_price_cents", positive=True)
    credits_total_minted = body.quantity("credits_total_minted", positive=True)
    body.close()

    if species is None:
        species = resolve.species(covered_species_id)

    # Rung 13: only a listed species carries sellable credits.
    if species["listing_status"] not in ("ENDANGERED", "THREATENED"):
        raise ApiError("ERR_SPECIES_NOT_LISTED")

    row = store.new_row(
        bank_name=bank_name,
        covered_species_id=species["id"],
        service_area_county_codes=counties,
        credit_price_cents=credit_price_cents,
        credits_total_minted=credits_total_minted,
        credits_available=credits_total_minted,
        credits_reserved=util.q2(0),
        credits_transferred=util.q2(0),
    )
    store.insert("banks", row)
    return envelope.created(serialize.bank(row))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = auth.authenticate(ANY_ROLE)
    auth.require_identity(caller)
    body = shape.Body()
    moment = body.instant("to_iso8601")
    body.close()

    store.set_clock(moment)
    cascades.expire_permits()
    return envelope.obj({})
