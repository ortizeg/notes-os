"""Async-harness smoke test — proves pytest-asyncio + Textual run_test() work end-to-end.

This test is intentionally minimal: it defines a trivial inline Textual App
and drives it via ``app.run_test()`` inside an ``async def`` body.  If this
test passes, the async harness is wired correctly and every other screen test
in this package can rely on the same mechanism.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Label


class _MinimalApp(App[None]):
    """Trivial inline app used only by the smoke test below."""

    def compose(self) -> ComposeResult:
        """Yield a single label so the app has at least one widget.

        Yields:
            A single :class:`~textual.widgets.Label` widget.
        """
        yield Label("smoke-test")


async def test_async_harness_smoke() -> None:
    """Textual run_test() context manager enters and exits without error.

    Verifies that:
    - pytest-asyncio is installed and ``asyncio_mode = "auto"`` is active so
      this ``async def`` body executes under pytest.
    - Textual's ``App.run_test()`` async context manager can be entered and
      exited without raising.
    - The app reaches a running state while the context is active.
    """
    app = _MinimalApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.is_running
