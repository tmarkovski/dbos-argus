"""`workflow` channel — pushes the same payload shape as `GET /api/workflows/{id}`.

Params: `{id: string}` — required.

There's no cheap cursor here: the snapshot itself is the family walk + steps
+ events. Computing a "did anything in this family change?" probe would do
almost the same work. We just re-snapshot every tick; per-page subscribers
are few (one client per detail page).
"""

from __future__ import annotations

from typing import Any

from ..channel import KeyedChannel


class WorkflowChannel(KeyedChannel):
    name = "workflow"

    def validate_params(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        if not params or not isinstance(params.get("id"), str) or not params["id"].strip():
            raise ValueError("workflow channel requires params.id (non-empty string)")
        return {"id": params["id"]}

    async def snapshot(self, params: dict[str, Any] | None) -> Any:
        # Lazy import to break the realtime → main → realtime cycle.
        from ...main import fetch_workflow_detail

        workflow_id = (params or {}).get("id")
        result = await fetch_workflow_detail(str(workflow_id))
        if result is None:
            # Surface "not found" as an empty snapshot so the client can render
            # an empty state. The frontend already has to handle this for
            # first-paint races.
            return None
        return result.model_dump(mode="json")
