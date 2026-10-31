"""Start the server.

  python run.py

HTTPS: set SSL_CERTFILE and SSL_KEYFILE in .env (strongly recommended; see README).
"""
import os

import uvicorn

if __name__ == "__main__":
    from app import config  # noqa: F401  (loads .env)

    cert, key = os.environ.get("SSL_CERTFILE"), os.environ.get("SSL_KEYFILE")
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8443" if cert else "8000")),
        ssl_certfile=cert or None,
        ssl_keyfile=key or None,
        proxy_headers=os.environ.get("TRUST_PROXY", "false").lower() == "true",
        server_header=False,
        date_header=False,
        log_level="info",
        workers=1,
    )
