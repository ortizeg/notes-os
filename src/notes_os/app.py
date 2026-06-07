"""NotesOS application entry point.

The full Textual ``App`` subclass with screens and widgets arrives in Phase 6.
This module provides the ``main()`` console entry point and a placeholder
``NotesOSApp`` class so the ``notes`` command resolves and runs cleanly from
day one, and so tests can import and instantiate the class without error.
"""

from __future__ import annotations

import importlib.metadata
import logging


logger = logging.getLogger(__name__)


class NotesOSApp:
    """Placeholder for the NotesOS Textual application.

    The Textual ``App`` subclass, HomeScreen, SortScreen, and all widgets
    are implemented in Phase 6.  This placeholder exists so:

    - ``notes_os.app`` is always importable.
    - The ``notes`` entry point can start, log a banner, and exit cleanly.
    - Unit tests can instantiate the class without pulling in Textual.

    Args:
        None — no constructor arguments in Phase 1.
    """

    def run(self) -> None:
        """Log a startup banner.

        In Phase 6 this method will launch the Textual TUI event loop.
        For now it simply logs that the TUI is not yet available.
        """
        logger.info("NotesOSApp.run() — full TUI launches in Phase 6.")


def main() -> None:
    """Entry point for the ``notes`` console command.

    Configures basic logging, resolves the package version via
    ``importlib.metadata`` (falls back to ``"0.0.0+unknown"`` when the
    package is not installed or the VCS tag is absent), logs a banner,
    and returns.  The Textual app launch is wired in Phase 6.

    Returns:
        None
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        version = importlib.metadata.version("para-notes-sorter")
    except importlib.metadata.PackageNotFoundError:
        version = "0.0.0+unknown"

    logger.info("NotesOS %s — TUI arrives in Phase 6.", version)
