"""PollingScheduler — APScheduler integration for the Parcel API poll cycle.

Implements :class:`~app.application.services.interfaces.AbstractSchedulerState`
so the application layer can query scheduler health without importing APScheduler.

Responsibilities:
- Register the poll job with ``IntervalTrigger`` (jitter, max_instances=1)
- Execute a cold-start poll on startup (POLL-REQ-003)
- Provide ``is_running()`` and ``get_next_poll_at()`` for health reporting
- Gracefully shut down on application exit (POLL-REQ-002)

Session management: a fresh ``AsyncSession`` is created **per poll cycle**.
Repositories are instantiated inside ``_run_poll_cycle`` so each cycle has
its own transaction scope.  The polling use case never crosses session
boundaries between cycles.

ARCH-INFRASTRUCTURE §8
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.application.services.interfaces import (
    AbstractParcelAPIClient,
    AbstractSchedulerState,
)
from app.application.use_cases.polling.poll_and_sync import PollAndSyncUseCase
from app.infrastructure.database.engine import async_session_factory
from app.infrastructure.database.repositories.sqlalchemy_delivery_repository import (
    SQLAlchemyDeliveryRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_poll_log_repository import (
    SQLAlchemyPollLogRepository,
)

logger = logging.getLogger(__name__)

_JOB_ID = "poll_and_sync"


class PollingScheduler(AbstractSchedulerState):
    """APScheduler wrapper that manages the Parcel API poll cycle.

    Args:
        parcel_client:      Shared ``AbstractParcelAPIClient`` instance.
        interval_minutes:   Poll interval in minutes (default 15, min 5).
        jitter_seconds:     Max random jitter added to each interval (±N seconds).
    """

    def __init__(
        self,
        parcel_client: AbstractParcelAPIClient,
        interval_minutes: int = 15,
        jitter_seconds: int = 30,
    ) -> None:
        self._parcel_client = parcel_client
        self._interval_minutes = interval_minutes
        self._jitter_seconds = jitter_seconds
        self._scheduler = AsyncIOScheduler()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start APScheduler and register the poll job.

        The cold-start poll is dispatched as a non-blocking ``asyncio.Task``
        so HTTP serving can begin immediately (POLL-REQ-003, POLL-REQ-001).
        The interval timer starts AFTER the cold-start poll completes, which
        satisfies POLL-REQ-004.
        """
        self._scheduler.add_job(
            func=self._run_poll_cycle,
            trigger=IntervalTrigger(
                minutes=self._interval_minutes,
                jitter=self._jitter_seconds,
            ),
            id=_JOB_ID,
            name="Parcel API Poll Cycle",
            max_instances=1,       # dropped (not queued) if previous is running
            coalesce=True,         # collapse multiple misfired triggers into one
            misfire_grace_time=60, # if missed within 60 s, run immediately
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            "Polling scheduler started: interval=%dm jitter=±%ds",
            self._interval_minutes,
            self._jitter_seconds,
        )

        # Cold-start poll — fire immediately, do not block startup (POLL-REQ-003)
        asyncio.create_task(
            self._run_poll_cycle(),
            name="poll_and_sync_cold_start",
        )

    def shutdown(self) -> None:
        """Gracefully shut down the scheduler (POLL-REQ-002).

        ``wait=True`` allows any in-progress poll cycle to complete before
        the process exits, up to APScheduler's internal grace period.
        """
        if self._scheduler.running:
            logger.info("Polling scheduler shutting down (wait=True)...")
            self._scheduler.shutdown(wait=True)
            logger.info("Polling scheduler stopped.")

    # ------------------------------------------------------------------
    # AbstractSchedulerState interface
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        """Return ``True`` if the scheduler is running and the job is registered."""
        return self._scheduler.running and (
            self._scheduler.get_job(_JOB_ID) is not None
        )

    def get_next_poll_at(self) -> Optional[datetime]:
        """Return the UTC datetime of the next scheduled poll, or ``None``.

        Returns ``None`` if the scheduler is not running or the job has no
        next fire time (API-REQ-018).
        """
        if not self._scheduler.running:
            return None
        job = self._scheduler.get_job(_JOB_ID)
        if job is None or job.next_run_time is None:
            return None
        return job.next_run_time

    # ------------------------------------------------------------------
    # Poll cycle execution
    # ------------------------------------------------------------------

    async def _run_poll_cycle(self) -> None:
        """Execute one complete poll-and-sync cycle within a fresh session.

        Creates a new ``AsyncSession`` per cycle so each poll has its own
        transaction scope.  The ``PollAndSyncUseCase`` is instantiated fresh
        inside the session context — it never persists state between cycles.

        Transaction note: ``async_session_factory()`` used as a context
        manager calls ``session.close()`` on exit, NOT ``session.commit()``.
        We call ``await session.commit()`` explicitly after ``execute()``
        returns.  ``PollAndSyncUseCase.execute()`` never raises — all errors
        are caught internally and reflected in the ``PollLog`` record.

        The outer ``try/except`` is a last-resort guard for unexpected
        infrastructure failures (e.g. DB unavailable before the poll log
        can even be written).
        """
        try:
            async with async_session_factory() as session:
                delivery_repo = SQLAlchemyDeliveryRepository(session)
                poll_log_repo = SQLAlchemyPollLogRepository(session)
                use_case = PollAndSyncUseCase(
                    delivery_repo=delivery_repo,
                    poll_log_repo=poll_log_repo,
                    parcel_client=self._parcel_client,
                )
                await use_case.execute()
                # Commit all changes (deliveries, events, status history, poll log).
                # execute() never raises, so this line is always reached.
                await session.commit()
        except Exception:
            # Should be unreachable under normal conditions — PollAndSyncUseCase
            # never raises.  Logged here as a diagnostic safety net.
            logger.exception("Unhandled error in poll cycle job wrapper")
