# Created by: Raymond Reeves Engineering Tech 4 2026
from __future__ import annotations

import logging
import sys

import structlog

from app.settings.config import Settings


def configure_logging(settings: Settings) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    renderer = (
        structlog.dev.ConsoleRenderer(colors=True)
        if settings.environment == "development"
        else structlog.processors.JSONRenderer()
    )

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        stream=sys.stdout,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

# Fully-commented edition notes:
# - File path: backend/app/settings/logging.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.