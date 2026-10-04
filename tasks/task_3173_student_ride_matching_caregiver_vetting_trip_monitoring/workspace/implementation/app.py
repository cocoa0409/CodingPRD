"""Entry point.

The store and the logical clock both start in their pristine, empty default
state; nothing here (and nothing anywhere else) seeds, preloads or registers an
entity. Every resource a caller observes was created through a declared
endpoint during the current process lifetime, so a fresh `bash start.sh` boot
wipes every byte of state.
"""

import os

import clock
from app_factory import create_app

# Pristine boot: logical clock at the fixed default instant, empty store.
clock.reset_clock()

app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)