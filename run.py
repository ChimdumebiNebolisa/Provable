from __future__ import annotations

import os

from provable import create_app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("PROVABLE_HOST", "127.0.0.1")
    port = int(os.getenv("PROVABLE_PORT", "5000"))
    debug = os.getenv("PROVABLE_DEBUG", "1") == "1"
    app.run(host=host, port=port, debug=debug)
