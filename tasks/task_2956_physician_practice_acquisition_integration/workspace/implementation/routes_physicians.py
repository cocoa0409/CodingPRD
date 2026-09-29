"""POST /physicians (PRD section 3.1)."""

import clock
import enums
import services
import store
import validate
from errors import ApiError


def create_physician():
    validate.gate(enums.ROLES_DEAL_LEAD)
    body = validate.json_body()
    acquisition_id = validate.req_id(body, "acquisition_id")
    npi = validate.req_str(body, "npi")
    if len(npi) != 10 or not npi.isdigit():
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'npi' must be exactly ten decimal digits.")
    full_name = validate.req_str(body, "full_name")
    specialty = validate.req_enum(body, "specialty", enums.SPECIALTIES)
    board_certified = validate.opt_bool(body, "board_certified", False)
    license_expires_on = validate.req_date(body, "state_license_expires_on")

    # Rank 5: body reference existence.
    acquisition = store.require("acquisitions", acquisition_id)

    # Rank 7: the NPI is unique across every physician in the system.
    for peer in store.all_rows("physicians"):
        if peer["npi"] == npi:
            raise ApiError("ERR_DUPLICATE_NPI",
                           "NPI '%s' is already registered." % npi)

    # Rank 15: the compliance-clearance freeze.
    services.check_freeze(acquisition)

    row = {
        "acquisition_id": acquisition_id,
        "npi": npi,
        "full_name": full_name,
        "specialty": specialty,
        "board_certified": board_certified,
        "state_license_expires_on": clock.format_date(license_expires_on),
        "employment_status": "PROSPECTIVE",
    }
    store.insert("physicians", row)
    return services.respond_created(row)


def register(app):
    app.add_url_rule("/physicians", "create_physician", create_physician,
                     methods=["POST"])
