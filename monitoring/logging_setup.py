#!/usr/bin/env python3
"""Monitoring logging entrypoint — re-exports the structured, secret-masking
logger from the safety core so monitoring.* and safety.* share one logger."""
from safety.logging_setup import get_logger, _mask  # noqa: F401
