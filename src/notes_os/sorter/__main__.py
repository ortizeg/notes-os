"""Thin manual runner for the NotesOS PARA sorter.

Allows running the sorter directly via::

    python -m notes_os.sorter

This is a LOCAL DEVELOPMENT / MANUAL USE entry point only.  It is NOT the
``notes`` console-script entry point — that is reserved for the Phase 6
Textual TUI (``notes_os.app:main``).  Do NOT add a ``[project.scripts]``
entry for this module.

Usage::

    python -m notes_os.sorter                 # uses ~/.notes-os/config.toml
    python -m notes_os.sorter --config /path  # explicit config path (future)

"""

from __future__ import annotations

import logging
import sys

from notes_os.config import load_config
from notes_os.sorter.controller import build_default_controller


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Load config, build the production controller, and run the sort loop.

    Exits with code 1 on any fatal error so shell scripts can detect failure.

    Returns:
        None.
    """
    try:
        config = load_config()
        controller = build_default_controller(config)
        controller.run()
    except KeyboardInterrupt:
        logger.info("Sort session cancelled by user.")
        sys.exit(0)
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
