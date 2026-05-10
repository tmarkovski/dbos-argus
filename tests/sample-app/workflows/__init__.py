"""Workflow definitions for the Argus demo sample app.

Submodules each cover one use case so the dashboard shows distinct workflow
trees side-by-side. `DBOS(...)` MUST be constructed before importing this
package — the @DBOS.step / @DBOS.workflow decorators reference the global
DBOS singleton at definition time.
"""

from __future__ import annotations

from .billing import run_billing_cycle
from .campaigns import deliver_message, send_campaign
from .common import audit, log_event
from .fulfillment import fulfill_order
from .onboarding import onboard_user
from .reports import generate_daily_report
from .returns import process_return

__all__ = [
    "audit",
    "deliver_message",
    "fulfill_order",
    "generate_daily_report",
    "log_event",
    "onboard_user",
    "process_return",
    "run_billing_cycle",
    "send_campaign",
]
