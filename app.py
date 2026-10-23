"""Vercel entrypoint: exposes the SCA web app as `app`."""

import os

# scripts/vercel_build.sh compiles cparse into sca/bin during the Vercel build.
_CPARSE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sca", "bin", "cparse")
if os.path.exists(_CPARSE):
    os.environ.setdefault("SCA_CPARSE", _CPARSE)

from sca.web.app import create_app

app = create_app()
