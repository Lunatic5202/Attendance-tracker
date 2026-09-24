"""Background daily sync tasks (Excel push + encrypted backup).

Runs once per day at ``MS_SYNC_TIME`` (UTC, default 23:30) plus a single
startup pass shortly after boot so the workbook is always fresh after a
redeploy. Both can be individually disabled via ``MS_EXCEL_ENABLED`` /
``MS_BACKUP_ENABLED``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time as dtime, timedelta, timezone

from backend import backup_sync, excel_sync, onedrive

log = logging.getLogger("scheduler")


def ms_sync_time() -> dtime:
    spec = os.getenv("MS_SYNC_TIME", "23:30")
    try:
        hour, minute = (int(part) for part in str(spec).split(":", 1))
        return dtime(hour % 24, minute % 60)
    except ValueError:
        return dtime(23, 30)


def excel_enabled() -> bool:
    return os.getenv("MS_EXCEL_ENABLED", "1") != "0"


def backup_enabled() -> bool:
    return os.getenv("MS_BACKUP_ENABLED", "1") != "0"


def _seconds_until_next(target: dtime) -> float:
    now = datetime.now(timezone.utc)
    next_fire = datetime.combine(now.date(), target, tzinfo=timezone.utc)
    if next_fire <= now:
        next_fire += timedelta(days=1)
    return (next_fire - now).total_seconds()


def _run_tasks() -> None:
    """Run both sync tasks once (blocking; invoked from a thread)."""
    results = {"excel": None, "backup": None}
    if excel_enabled():
        try:
            excel_sync.sync_to_excel()
        except Exception as exc:
            log.exception("Excel sync failed")
            results["excel"] = str(exc)
        else:
            results["excel"] = "ok"
    if backup_enabled():
        try:
            backup_sync.run_backup()
        except Exception as exc:
            log.exception("Backup sync failed")
            results["backup"] = str(exc)
        else:
            results["backup"] = "ok"
    log.info("Daily Microsoft sync finished: %s", results)


async def _daily_loop() -> None:
    while True:
        wait = _seconds_until_next(ms_sync_time())
        await asyncio.sleep(wait)
        try:
            await asyncio.to_thread(_run_tasks)
        except Exception:  # pragma: no cover - defensive
            log.exception("Daily Microsoft sync crashed")


async def _startup_pass() -> None:
    await asyncio.sleep(15)
    try:
        await asyncio.to_thread(_run_tasks)
    except Exception:  # pragma: no cover - defensive
        log.exception("Startup Microsoft sync crashed")


def spawn() -> None:
    """Start the scheduler if Microsoft Graph is configured. No-op otherwise."""
    if not onedrive.configured():
        log.info("Microsoft OneDrive sync disabled (MS_* env vars not set).")
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("Scheduler not started (no running event loop).")
        return
    loop.create_task(_daily_loop())
    loop.create_task(_startup_pass())
    log.info("Microsoft OneDrive scheduler started (daily at %s UTC).", ms_sync_time())