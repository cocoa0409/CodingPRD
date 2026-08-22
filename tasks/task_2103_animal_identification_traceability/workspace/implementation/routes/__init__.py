from routes.animals import bp as animals_bp
from routes.awards import bp as awards_bp
from routes.clock import bp as clock_bp
from routes.holds import bp as holds_bp
from routes.lots import bp as lots_bp
from routes.movements import bp as movements_bp
from routes.premises import bp as premises_bp
from routes.producers import bp as producers_bp
from routes.recon import bp as recon_bp
from routes.suppliers import bp as suppliers_bp
from routes.tags import bp as tags_bp
from routes.traces import bp as traces_bp

ALL_BLUEPRINTS = [
    producers_bp,
    premises_bp,
    suppliers_bp,
    lots_bp,
    tags_bp,
    animals_bp,
    movements_bp,
    traces_bp,
    holds_bp,
    recon_bp,
    awards_bp,
    clock_bp,
]
