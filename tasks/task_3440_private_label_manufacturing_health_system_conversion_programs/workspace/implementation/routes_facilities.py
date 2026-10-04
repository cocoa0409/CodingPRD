"""Facility endpoints (PRD 3.3)."""
from flask import Blueprint

import db
import helpers as H

bp = Blueprint('facilities', __name__)

FACILITY_TYPES = ('ACUTE_CARE', 'SURGERY_CENTER', 'CLINIC', 'LONG_TERM_CARE')


@bp.post('/supply/facilities')
def create_facility():
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    b = H.get_body()
    name = H.v_str(H.required(b, 'name'), 'name')
    health_system_name = H.v_str(H.required(b, 'health_system_name'), 'health_system_name')
    facility_type = H.v_enum(H.required(b, 'facility_type'), 'facility_type', FACILITY_TYPES)
    ship_to_address = H.v_str(H.required(b, 'ship_to_address'), 'ship_to_address')
    fac = H.base_resource()
    fac.update({
        'name': name,
        'health_system_name': health_system_name,
        'facility_type': facility_type,
        'ship_to_address': ship_to_address,
    })
    db.STORES['facilities'][fac['id']] = fac
    return H.success(fac, 201)
