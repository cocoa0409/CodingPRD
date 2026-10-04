"""Route blueprints, one module per resource group."""

from routes import (
    activities,
    admissions,
    arcade_credits,
    attractions,
    cabanas,
    day_passes,
    group_bookings,
    group_members,
    lifeguard_shifts,
    resorts,
    reservations,
    room_types,
    testing,
    water_quality,
    wristbands,
)

ALL_BLUEPRINTS = (
    resorts.bp,
    room_types.bp,
    reservations.bp,
    day_passes.bp,
    wristbands.bp,
    attractions.bp,
    lifeguard_shifts.bp,
    water_quality.bp,
    admissions.bp,
    cabanas.bp,
    group_bookings.bp,
    group_members.bp,
    activities.bp,
    arcade_credits.bp,
    testing.bp,
)


def register(app):
    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)