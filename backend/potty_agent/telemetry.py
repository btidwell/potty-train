"""OpenTelemetry setup for Strands agent traces."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_READY = False


def configure_telemetry() -> None:
    """Enable Strands OTEL export once per execution environment."""
    global _READY
    if _READY:
        return
    try:
        from strands.telemetry import StrandsTelemetry

        telemetry = StrandsTelemetry()
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if endpoint:
            telemetry.setup_otlp_exporter()
            logger.info("Agent OTEL OTLP exporter enabled.")
        else:
            # Without a collector, still emit spans to CloudWatch Logs so a
            # cold start shows that tracing is wired.
            telemetry.setup_console_exporter()
            logger.info("Agent OTEL console exporter enabled.")
        _READY = True
    except Exception:
        logger.exception("Could not configure agent OpenTelemetry.")
