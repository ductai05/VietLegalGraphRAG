"""VM lifecycle manager for Neo4j VPS auto-start/stop (Archived).

This module is kept for historical reference and is not used in the
active DigitalOcean Droplet deployment.
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


class VMStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    UNKNOWN = "unknown"


class VMProviderBase(ABC):
    @abstractmethod
    async def start_vm(self) -> None: ...
    @abstractmethod
    async def stop_vm(self) -> None: ...
    @abstractmethod
    async def get_status(self) -> VMStatus: ...


class NoneVMProvider(VMProviderBase):
    async def start_vm(self) -> None: pass
    async def stop_vm(self) -> None: pass
    async def get_status(self) -> VMStatus: return VMStatus.READY


class GCPVMProvider(VMProviderBase):
    def __init__(self, project: str | None = None, zone: str | None = None, instance: str | None = None) -> None:
        self.project = project or os.getenv("VM_PROJECT", "")
        self.zone = zone or os.getenv("VM_ZONE", "")
        self.instance = instance or os.getenv("VM_INSTANCE_ID", "")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import compute_v1
            self._client = compute_v1.InstancesClient()
        return self._client

    async def start_vm(self) -> None:
        client = self._get_client()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: client.start(project=self.project, zone=self.zone, instance=self.instance))

    async def stop_vm(self) -> None:
        client = self._get_client()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: client.stop(project=self.project, zone=self.zone, instance=self.instance))

    async def get_status(self) -> VMStatus:
        client = self._get_client()
        loop = asyncio.get_event_loop()
        instance = await loop.run_in_executor(None, lambda: client.get(project=self.project, zone=self.zone, instance=self.instance))
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
    def __init__(self, instance_id: str | None = None, region: str | None = None) -> None:
        self.instance_id = instance_id or os.getenv("VM_INSTANCE_ID", "")
        self.region = region or os.getenv("VM_ZONE", "")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3
            self._client = boto3.client("ec2", region_name=self.region)
        return self._client

    async def start_vm(self) -> None:
        client = self._get_client()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: client.start_instances(InstanceIds=[self.instance_id]))

    async def stop_vm(self) -> None:
        client = self._get_client()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: client.stop_instances(InstanceIds=[self.instance_id]))

    async def get_status(self) -> VMStatus:
        client = self._get_client()
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: client.describe_instances(InstanceIds=[self.instance_id]))
        state = response["Reservations"][0]["Instances"][0]["State"]["Name"] if response.get("Reservations") else "unknown"
        status_map = {
            "running": VMStatus.READY,
            "pending": VMStatus.STARTING,
            "stopping": VMStatus.STOPPING,
            "stopped": VMStatus.STOPPED,
            "shutting-down": VMStatus.STOPPING,
            "terminated": VMStatus.STOPPED,
        }
        return status_map.get(state, VMStatus.UNKNOWN)


class VMManager:
    def __init__(self, provider: str = "none", idle_timeout: int = 600) -> None:
        if provider == "gcp":
            self._provider = GCPVMProvider()
        elif provider == "aws":
            self._provider = AWSVMProvider()
        else:
            self._provider = NoneVMProvider()
        self._idle_timeout = idle_timeout
        self._last_activity = time.monotonic()
        self._status = VMStatus.UNKNOWN

    def touch(self) -> None:
        self._last_activity = time.monotonic()

    async def ensure_running(self) -> VMStatus:
        return await self._provider.get_status()

    async def start_watchdog(self) -> None: pass
    async def shutdown(self) -> None: pass
    def health_dict(self) -> dict:
        return {
            "neo4j_vm": "ready",
            "idle_seconds": 0,
            "idle_timeout": self._idle_timeout,
            "provider": type(self._provider).__name__,
        }
