"""Product catalog + regulatory registration lifecycle (PRD 3.1)."""
from flask import Blueprint

import db
import helpers as H
import services
from errors import ApiError, ERR_DUPLICATE_SKU, ERR_INVALID_STATE, not_found

bp = Blueprint('products', __name__)

BRAND_TYPES = ('BRANDED', 'PRIVATE_LABEL')
CATEGORIES = ('SURGICAL_INSTRUMENTS', 'WOUND_CARE', 'EXAM_GLOVES',
              'STERILIZATION_SUPPLIES', 'UROLOGICAL', 'RESPIRATORY')
DEVICE_CLASSES = ('CLASS_I', 'CLASS_II', 'CLASS_III')
AVAILABILITY = ('ACTIVE', 'DISCONTINUED')


@bp.post('/supply/products')
def create_product():
    _, role = H.auth()
    H.require_roles(role, ('SupplyChainAdmin',))
    b = H.get_body()
    sku = H.v_str(H.required(b, 'sku'), 'sku')
    name = H.v_str(H.required(b, 'name'), 'name')
    brand_type = H.v_enum(H.required(b, 'brand_type'), 'brand_type', BRAND_TYPES)
    category = H.v_enum(H.required(b, 'category'), 'category', CATEGORIES)
    sterile = H.v_bool(H.required(b, 'sterile'), 'sterile')
    device_class = H.v_enum(H.required(b, 'device_class'), 'device_class', DEVICE_CLASSES)
    units_per_case = H.v_int(H.required(b, 'units_per_case'), 'units_per_case', minimum=1)
    each_price_cents = H.v_int(H.required(b, 'each_price_cents'), 'each_price_cents', minimum=0)
    availability = H.v_enum(b.get('availability', 'ACTIVE'), 'availability', AVAILABILITY)
    order_multiple = H.v_int(b.get('order_multiple', 1), 'order_multiple', minimum=1)
    lum_eligible = H.v_bool(b.get('lum_eligible', False), 'lum_eligible')
    # Priority 8: sku is globally unique
    for p in db.STORES['products'].values():
        if p['sku'] == sku:
            raise ApiError(ERR_DUPLICATE_SKU, 409, 'sku already exists')
    prod = H.base_resource()
    prod.update({
        'sku': sku,
        'name': name,
        'brand_type': brand_type,
        'category': category,
        'sterile': sterile,
        'device_class': device_class,
        'registration_status': 'UNREGISTERED',
        'availability': availability,
        'units_per_case': units_per_case,
        'each_price_cents': each_price_cents,
        'order_multiple': order_multiple,
        'lum_eligible': lum_eligible,
    })
    db.STORES['products'][prod['id']] = prod
    return H.success(prod, 201)


@bp.post('/supply/products/<pid>/registration-events')
def registration_event(pid):
    _, role = H.auth()
    H.require_roles(role, ('RegulatorySpecialist',))
    b = H.get_body()
    event = H.v_enum(H.required(b, 'event'), 'event', ('SUBMIT', 'APPROVE', 'REJECT'))
    prod = db.STORES['products'].get(pid)
    if prod is None:
        not_found('product')
    cur = prod['registration_status']
    if event == 'SUBMIT':
        if cur not in ('UNREGISTERED', 'REJECTED'):
            raise ApiError(ERR_INVALID_STATE, 409,
                           'SUBMIT is not valid from registration_status {}'.format(cur))
        prod['registration_status'] = 'SUBMITTED'
    elif event == 'APPROVE':
        if cur != 'SUBMITTED':
            raise ApiError(ERR_INVALID_STATE, 409,
                           'APPROVE is not valid from registration_status {}'.format(cur))
        prod['registration_status'] = 'REGISTERED'
    else:  # REJECT
        if cur != 'SUBMITTED':
            raise ApiError(ERR_INVALID_STATE, 409,
                           'REJECT is not valid from registration_status {}'.format(cur))
        prod['registration_status'] = 'REJECTED'
    services.touch(prod)
    return H.success(prod, 200)
