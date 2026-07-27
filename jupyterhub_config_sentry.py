"""Sentry error reporting for the hub (GlitchTip compatible).

Enabled when SENTRY_DSN is set (via hub.extraEnv); otherwise a no-op.
GlitchTip implements the Sentry protocol, so a GlitchTip DSN works
unchanged.

Other standard SDK environment variables are honoured too, most usefully
SENTRY_ENVIRONMENT (e.g. ``rctest``) and SENTRY_RELEASE.
"""

import logging
import os

log = logging.getLogger("nectar.sentry")

if os.environ.get("SENTRY_DSN"):
    import sentry_sdk
    from sentry_sdk.integrations.tornado import TornadoIntegration

    sentry_sdk.init(
        integrations=[TornadoIntegration()],
        # error reporting only: GlitchTip has limited tracing support
        traces_sample_rate=0.0,
        # hub handles auth; keep user PII out of events
        send_default_pii=False,
    )
    log.info("Sentry error reporting enabled")
else:
    log.info("Sentry error reporting disabled: SENTRY_DSN not set")
