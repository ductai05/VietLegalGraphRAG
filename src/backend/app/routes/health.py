from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    """Health endpoint polled by the frontend.

    When ``VM_PROVIDER`` is configured (not ``none``), this endpoint
    triggers a VM start on the first call and returns the current VM
    status so the frontend can show a loading indicator.
    """
    vm_manager = getattr(request.app.state, "vm_manager", None)

    if vm_manager is None:
        # VMManager not initialised — local dev / legacy mode
        return {
            "status": "degraded",
            "elasticsearch": "not_checked",
            "neo4j": "not_checked",
            "neo4j_vm": "none",
            "llm": "mock",
        }

    # Touch the idle timer (every /health poll counts as activity)
    vm_manager.touch()

    vm_health = vm_manager.health_dict()
    vm_status = vm_health["neo4j_vm"]

    # Auto-trigger VM start when frontend first polls
    if vm_status == "stopped" or vm_status == "unknown":
        # Fire-and-forget: do NOT await the full boot here.
        # The frontend will keep polling until status is "ready".
        import asyncio

        asyncio.ensure_future(vm_manager.ensure_running())
        vm_status = "starting"

    overall = "ok" if vm_status == "ready" else "degraded"

    return {
        "status": overall,
        "elasticsearch": "not_checked",
        "neo4j": vm_status,
        "neo4j_vm": vm_status,
        "idle_seconds": vm_health["idle_seconds"],
        "idle_timeout": vm_health["idle_timeout"],
        "vm_provider": vm_health["provider"],
        "llm": "mock",
    }
