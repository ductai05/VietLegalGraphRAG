"""VM lifecycle manager for Neo4j VPS auto-start/stop.

This module manages the lifecycle of a cloud VM running Neo4j.  It
starts the VM on the first incoming request, keeps it alive while the
backend is receiving traffic, and automatically stops it after a
configurable idle timeout (default 10 minutes).

The design is provider-agnostic: concrete adapters implement the
``VMProviderBase`` interface for each cloud (GCP, AWS, Vultr, …).
A ``none`` provider is included for local development where the VM is
assumed to be always running.

Thread safety
-------------
``VMManager`` is designed for a single-process async backend (uvicorn).
An ``asyncio.Lock`` serialises state transitions so concurrent ``/health``
polls do not trigger duplicate start commands.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

logger = logging.getLogger("vm_manager")


# ---------------------------------------------------------------------------
# VM status enum
# ---------------------------------------------------------------------------

class VMStatus(str, Enum):
    """Possible states of the managed Neo4j VM."""
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class VMProviderBase(ABC):
    """Abstract interface that each cloud adapter must implement."""

    @abstractmethod
    async def start_vm(self) -> None:
        """Issue a start command to the cloud API."""

    @abstractmethod
    async def stop_vm(self) -> None:
        """Issue a stop command to the cloud API."""

    @abstractmethod
    async def get_status(self) -> VMStatus:
        """Query the cloud API for current VM status."""


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------

class NoneVMProvider(VMProviderBase):
    """No-op provider for local development.

    Assumes Neo4j is always running on localhost or managed externally.
    """

    async def start_vm(self) -> None:
        logger.debug("NoneVMProvider.start_vm: no-op")

    async def stop_vm(self) -> None:
        logger.debug("NoneVMProvider.stop_vm: no-op")

    async def get_status(self) -> VMStatus:
        return VMStatus.READY


class GCPVMProvider(VMProviderBase):
    """Google Cloud Compute Engine adapter.

    Requires ``google-cloud-compute`` package and a service account with
    ``compute.instances.start`` / ``compute.instances.stop`` permissions.

    Environment variables (or constructor args):
        VM_PROJECT   – GCP project ID
        VM_ZONE      – e.g. ``asia-southeast1-b``
        VM_INSTANCE  – instance name
    """

    def __init__(
        self,
        project: str | None = None,
        zone: str | None = None,
        instance: str | None = None,
    ) -> None:
        self.project = project or os.getenv("VM_PROJECT", "")
        self.zone = zone or os.getenv("VM_ZONE", "")
        self.instance = instance or os.getenv("VM_INSTANCE_ID", "")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from google.cloud import compute_v1  # type: ignore[import-untyped]
                self._client = compute_v1.InstancesClient()
            except ImportError:
                raise RuntimeError(
                    "google-cloud-compute is required for GCP VM management. "
                    "Install it with: pip install google-cloud-compute"
                )
        return self._client

    async def start_vm(self) -> None:
        client = self._get_client()
        logger.info("GCP: Starting VM %s/%s/%s", self.project, self.zone, self.instance)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: client.start(
                project=self.project,
                zone=self.zone,
                instance=self.instance,
            ),
        )

    async def stop_vm(self) -> None:
        client = self._get_client()
        logger.info("GCP: Stopping VM %s/%s/%s", self.project, self.zone, self.instance)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: client.stop(
                project=self.project,
                zone=self.zone,
                instance=self.instance,
            ),
        )

    async def get_status(self) -> VMStatus:
        client = self._get_client()
        loop = asyncio.get_event_loop()
        instance = await loop.run_in_executor(
            None,
            lambda: client.get(
                project=self.project,
                zone=self.zone,
                instance=self.instance,
            ),
        )
        status_map = {
            "RUNNING": VMStatus.READY,
            "STAGING": VMStatus.STARTING,
            "PROVISIONING": VMStatus.STARTING,
            "STOPPING": VMStatus.STOPPING,
            "TERMINATED": VMStatus.STOPPED,
            "STOPPED": VMStatus.STOPPED,
            "SUSPENDED": VMStatus.STOPPED,
        }
        return status_map.get(instance.status, VMStatus.UNKNOWN)


class AWSVMProvider(VMProviderBase):
    """Amazon EC2 adapter.

    Requires ``boto3`` and appropriate IAM credentials.

    Environment variables (or constructor args):
        VM_INSTANCE_ID  – EC2 instance ID (e.g. ``i-0abc123``)
        VM_ZONE         – AWS region (e.g. ``ap-southeast-1``)
    """

    def __init__(
        self,
        instance_id: str | None = None,
        region: str | None = None,
    ) -> None:
        self.instance_id = instance_id or os.getenv("VM_INSTANCE_ID", "")
        self.region = region or os.getenv("VM_ZONE", "")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3  # type: ignore[import-untyped]
                self._client = boto3.client("ec2", region_name=self.region)
            except ImportError:
                raise RuntimeError(
                    "boto3 is required for AWS VM management. "
                    "Install it with: pip install boto3"
                )
        return self._client

    async def start_vm(self) -> None:
        client = self._get_client()
        logger.info("AWS: Starting instance %s in %s", self.instance_id, self.region)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: client.start_instances(InstanceIds=[self.instance_id]),
        )

    async def stop_vm(self) -> None:
        client = self._get_client()
        logger.info("AWS: Stopping instance %s in %s", self.instance_id, self.region)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: client.stop_instances(InstanceIds=[self.instance_id]),
        )

    async def get_status(self) -> VMStatus:
        client = self._get_client()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.describe_instances(InstanceIds=[self.instance_id]),
        )
        state = (
            response["Reservations"][0]["Instances"][0]["State"]["Name"]
            if response.get("Reservations")
            else "unknown"
        )
        status_map = {
            "running": VMStatus.READY,
            "pending": VMStatus.STARTING,
            "stopping": VMStatus.STOPPING,
            "stopped": VMStatus.STOPPED,
            "shutting-down": VMStatus.STOPPING,
            "terminated": VMStatus.STOPPED,
        }
        return status_map.get(state, VMStatus.UNKNOWN)


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[VMProviderBase]] = {
    "none": NoneVMProvider,
    "gcp": GCPVMProvider,
    "aws": AWSVMProvider,
}


def create_provider(provider_name: str) -> VMProviderBase:
    """Instantiate a VM provider by name."""
    cls = _PROVIDERS.get(provider_name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown VM provider '{provider_name}'. "
            f"Available: {', '.join(_PROVIDERS)}"
        )
    return cls()


# ---------------------------------------------------------------------------
# VM Manager (orchestrator)
# ---------------------------------------------------------------------------

class VMManager:
    """Orchestrates Neo4j VM start/stop with idle-timeout watchdog.

    Usage in FastAPI::

        vm_manager = VMManager(provider="gcp", idle_timeout=600)

        @app.on_event("startup")
        async def startup():
            await vm_manager.start_watchdog()

        @app.on_event("shutdown")
        async def shutdown():
            await vm_manager.shutdown()

        @app.middleware("http")
        async def activity_tracker(request, call_next):
            vm_manager.touch()
            return await call_next(request)
    """

    def __init__(
        self,
        provider: str = "none",
        idle_timeout: int = 600,
        neo4j_boot_timeout: int = 120,
    ) -> None:
        self._provider = create_provider(provider)
        self._idle_timeout = idle_timeout
        self._neo4j_boot_timeout = neo4j_boot_timeout
        self._last_activity: float = time.monotonic()
        self._status = VMStatus.UNKNOWN
        self._lock = asyncio.Lock()
        self._watchdog_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()

    @property
    def status(self) -> VMStatus:
        return self._status

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_activity

    @property
    def idle_timeout(self) -> int:
        return self._idle_timeout

    def touch(self) -> None:
        """Record activity — resets the idle countdown."""
        self._last_activity = time.monotonic()

    # -- Lifecycle ----------------------------------------------------------

    async def ensure_running(self) -> VMStatus:
        """Ensure the VM is started.  Returns current status.

        If the VM is stopped, issues a start command and begins polling
        for readiness.  Concurrent calls are serialised by the lock.
        """
        self.touch()

        async with self._lock:
            if self._status == VMStatus.READY:
                return VMStatus.READY

            if self._status in (VMStatus.STOPPED, VMStatus.UNKNOWN):
                logger.info("VM is %s — requesting start", self._status.value)
                self._status = VMStatus.STARTING
                try:
                    await self._provider.start_vm()
                except Exception:
                    logger.exception("Failed to start VM")
                    self._status = VMStatus.STOPPED
                    return VMStatus.STOPPED

            # Poll provider until READY or timeout
            if self._status == VMStatus.STARTING:
                deadline = time.monotonic() + self._neo4j_boot_timeout
                while time.monotonic() < deadline:
                    try:
                        remote = await self._provider.get_status()
                        if remote == VMStatus.READY:
                            self._status = VMStatus.READY
                            logger.info("VM is now READY")
                            return VMStatus.READY
                    except Exception:
                        logger.warning("Error polling VM status", exc_info=True)
                    await asyncio.sleep(5)

                logger.warning(
                    "VM did not reach READY within %ds — status is %s",
                    self._neo4j_boot_timeout,
                    self._status.value,
                )

        return self._status

    async def stop(self) -> None:
        """Gracefully stop the VM."""
        async with self._lock:
            if self._status in (VMStatus.STOPPED, VMStatus.STOPPING):
                return
            logger.info("Stopping VM (idle for %.0fs)", self.idle_seconds)
            self._status = VMStatus.STOPPING
            try:
                await self._provider.stop_vm()
                self._status = VMStatus.STOPPED
                logger.info("VM stopped successfully")
            except Exception:
                logger.exception("Failed to stop VM")
                self._status = VMStatus.UNKNOWN

    # -- Watchdog -----------------------------------------------------------

    async def start_watchdog(self) -> None:
        """Launch the idle-timeout watchdog as a background task."""
        self._shutdown_event.clear()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info(
            "VM watchdog started (idle timeout: %ds, provider: %s)",
            self._idle_timeout,
            type(self._provider).__name__,
        )

    async def shutdown(self) -> None:
        """Cancel the watchdog and optionally stop the VM."""
        self._shutdown_event.set()
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
        logger.info("VM watchdog shut down")

    async def _watchdog_loop(self) -> None:
        """Background loop that stops the VM after idle timeout."""
        while not self._shutdown_event.is_set():
            await asyncio.sleep(30)  # Check every 30 seconds
            if self._status != VMStatus.READY:
                continue
            if self.idle_seconds >= self._idle_timeout:
                logger.info(
                    "Idle timeout reached (%.0fs >= %ds) — stopping VM",
                    self.idle_seconds,
                    self._idle_timeout,
                )
                await self.stop()

    # -- Health info --------------------------------------------------------

    def health_dict(self) -> dict[str, Any]:
        """Return a dict suitable for the /health endpoint."""
        return {
            "neo4j_vm": self._status.value,
            "idle_seconds": round(self.idle_seconds),
            "idle_timeout": self._idle_timeout,
            "provider": type(self._provider).__name__,
        }
