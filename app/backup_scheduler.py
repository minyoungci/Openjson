from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.backup_crypto import BACKUP_ENCRYPTION_KEY_ENV
from scripts.backup_sqlite import backup_sqlite


DEFAULT_BACKUP_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_BACKUP_RETENTION_COUNT = 7


@dataclass(frozen=True)
class BackupSchedulerConfig:
    enabled: bool
    db_path: str
    output_dir: str
    interval_seconds: int
    retention_count: int | None
    encrypt: bool
    encryption_key_configured: bool


BackupRunner = Callable[..., dict[str, Any]]
SleepRunner = Callable[[int], Awaitable[None]]
EventLogger = Callable[[dict[str, Any]], None]


def _json_log(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), flush=True)


def backup_scheduler_config_from_env(
    *,
    db_path: str,
    env: dict[str, str] | os._Environ[str] = os.environ,
) -> BackupSchedulerConfig:
    output_dir = env.get("OPENJSON_BACKUP_OUTPUT_DIR") or str(Path(db_path).resolve().parent / "backups")
    return BackupSchedulerConfig(
        enabled=_env_flag(env.get("OPENJSON_BACKUP_SCHEDULER_ENABLED")),
        db_path=db_path,
        output_dir=output_dir,
        interval_seconds=_positive_int(
            env.get("OPENJSON_BACKUP_INTERVAL_SECONDS"),
            default=DEFAULT_BACKUP_INTERVAL_SECONDS,
        ),
        retention_count=_optional_positive_int(
            env.get("OPENJSON_BACKUP_RETENTION_COUNT"),
            default=DEFAULT_BACKUP_RETENTION_COUNT,
        ),
        encrypt=_env_flag(env.get("OPENJSON_BACKUP_ENCRYPT")),
        encryption_key_configured=bool((env.get(BACKUP_ENCRYPTION_KEY_ENV) or "").strip()),
    )


class BackupScheduler:
    def __init__(
        self,
        config: BackupSchedulerConfig,
        *,
        backup_runner: BackupRunner = backup_sqlite,
        sleep_runner: SleepRunner = asyncio.sleep,
        event_logger: EventLogger = _json_log,
    ) -> None:
        self.config = config
        self._backup_runner = backup_runner
        self._sleep_runner = sleep_runner
        self._event_logger = event_logger
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self.config.enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_once(self) -> dict[str, Any]:
        self._log(
            "started",
            {
                "output_dir": self.config.output_dir,
                "interval_seconds": self.config.interval_seconds,
                "retention_count": self.config.retention_count,
                "encrypt": self.config.encrypt,
                "encryption_key_configured": self.config.encryption_key_configured,
            },
        )
        result = await asyncio.to_thread(
            self._backup_runner,
            self.config.db_path,
            self.config.output_dir,
            retention_count=self.config.retention_count,
            encrypt=self.config.encrypt,
        )
        self._log(
            "completed",
            {
                "status": result.get("status"),
                "integrity_status": _nested_get(result, "integrity", "status"),
                "backup_path": result.get("backup_path"),
                "manifest_path": result.get("manifest_path"),
                "encrypted": _nested_get(result, "encryption", "enabled"),
            },
        )
        return result

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log("failed", {"error": str(exc), "error_type": type(exc).__name__})
            await self._sleep_runner(self.config.interval_seconds)

    def _log(self, status: str, details: dict[str, Any]) -> None:
        self._event_logger(
            {
                "event": "sqlite_backup_scheduler",
                "status": status,
                "details": details,
            }
        )


def _nested_get(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _env_flag(raw: str | None) -> bool:
    return bool(raw and raw.strip().lower() in {"1", "true", "yes", "on"})


def _positive_int(raw: str | None, *, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)


def _optional_positive_int(raw: str | None, *, default: int | None) -> int | None:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)
