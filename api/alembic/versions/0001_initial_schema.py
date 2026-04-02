"""Initial schema — all five application tables.

Revision ID: 0001
Revises:     —
Create Date: 2025-04-01

Creates all five tables in forward FK-dependency order so that foreign-key
constraints can be enforced immediately:

  1. users           — authentication; no FK references to other tables
  2. poll_logs       — polling audit log; no FK references to other tables
  3. deliveries      — main tracking table; no FK references to other tables
  4. delivery_events — append-only events (FK → deliveries.id)
  5. status_history  — status transitions (FK → deliveries.id, poll_logs.id)

Downgrade drops tables in the exact reverse order so FK constraints are never
violated during rollback.

Notes
-----
* All timestamp columns use ``TIMESTAMP(timezone=True)`` → ``TIMESTAMPTZ``
  in PostgreSQL.  Naive datetimes are never stored (DM-BR-021).
* UUID primary keys use ``UUID(as_uuid=True)`` so SQLAlchemy returns Python
  ``uuid.UUID`` objects rather than strings.
* ``users.id`` uses ``Integer / SERIAL`` (autoincrement) because the table is
  not append-heavy and a sequential PK is conventional for credential records.
* ``token_version`` on ``users`` is GAP-001: absent from ``02-data-model.md``
  but required by the JWT invalidation chain (SEC-REQ-020).
* The ``uq_event_fingerprint`` unique constraint on ``delivery_events`` is the
  deduplication key used by ``INSERT … ON CONFLICT DO NOTHING`` (DM-BR-007).
* ``deliveries.description`` has a Python-side default of ``""`` in the ORM;
  no SQL ``DEFAULT`` is declared here to keep the migration in sync with what
  Alembic autogenerate would produce (``compare_server_default=True``).

Task 6.2 — ARCH-INFRASTRUCTURE §2.3, §9
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────────────
    # 1. users
    #
    #    Single-user system today; schema supports future multi-user expansion
    #    (DM-BR-015).  ``token_version`` is incremented atomically on each
    #    logout, invalidating all outstanding JWTs for that user (GAP-001,
    #    SEC-REQ-020–021).
    # ──────────────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            comment="GAP-001: incremented on logout to invalidate JWTs (SEC-REQ-020)",
        ),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Named unique index matching ORM model's Index("uq_user_username", ...).
    op.create_index("uq_user_username", "users", ["username"], unique=True)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. poll_logs
    #
    #    Append-only audit log.  A record is inserted with outcome='in_progress'
    #    *before* the Parcel API call; it is updated to 'success', 'partial', or
    #    'error' once the cycle completes (DM-BR-018–019).
    # ──────────────────────────────────────────────────────────────────────────
    op.create_table(
        "poll_logs",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deliveries_fetched", sa.Integer(), nullable=True),
        sa.Column("new_deliveries", sa.Integer(), nullable=True),
        sa.Column("status_changes", sa.Integer(), nullable=True),
        sa.Column("new_events", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('in_progress', 'success', 'partial', 'error')",
            name="ck_poll_log_outcome",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_poll_log_started_at", "poll_logs", ["started_at"])
    op.create_index("idx_poll_log_outcome", "poll_logs", ["outcome"])

    # ──────────────────────────────────────────────────────────────────────────
    # 3. deliveries
    #
    #    Business key: (tracking_number, carrier_code) — enforced by
    #    ``uq_delivery_tracking`` (DM-BR-001).
    #
    #    ``last_raw_response`` stores the most recent Parcel API payload as
    #    JSONB for efficient querying; it is NOT a history log (DM-BR-004).
    #
    #    ``timestamp_expected`` index supports the NULLS LAST sort used on the
    #    deliveries list endpoint (API-REQ-012).  The NULLS LAST behaviour is
    #    applied at query time via ``.nullslast()``; the index here is a plain
    #    B-tree index that the planner can use for that query.
    # ──────────────────────────────────────────────────────────────────────────
    op.create_table(
        "deliveries",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("tracking_number", sa.String(255), nullable=False),
        sa.Column("carrier_code", sa.String(50), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("extra_information", sa.String(500), nullable=True),
        sa.Column("parcel_status_code", sa.SmallInteger(), nullable=False),
        sa.Column("semantic_status", sa.String(50), nullable=False),
        sa.Column("date_expected_raw", sa.String(50), nullable=True),
        sa.Column("date_expected_end_raw", sa.String(50), nullable=True),
        sa.Column("timestamp_expected", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("timestamp_expected_end", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_raw_response", JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tracking_number", "carrier_code", name="uq_delivery_tracking"
        ),
    )
    op.create_index("idx_delivery_semantic_status", "deliveries", ["semantic_status"])
    op.create_index(
        "idx_delivery_timestamp_expected", "deliveries", ["timestamp_expected"]
    )
    op.create_index("idx_delivery_last_seen", "deliveries", ["last_seen_at"])
    op.create_index("idx_delivery_updated_at", "deliveries", ["updated_at"])

    # ──────────────────────────────────────────────────────────────────────────
    # 4. delivery_events
    #
    #    Append-only carrier timeline events (DM-BR-006).
    #
    #    ``uq_event_fingerprint`` on (delivery_id, event_description,
    #    event_date_raw) is the deduplication key that makes
    #    ``INSERT … ON CONFLICT DO NOTHING`` safe to call on every poll cycle
    #    without creating duplicate rows (DM-BR-007).
    #
    #    ``event_date_raw`` is stored verbatim — never parsed to a timestamp
    #    because carrier date string formats are non-standard (DM-BR-009).
    # ──────────────────────────────────────────────────────────────────────────
    op.create_table(
        "delivery_events",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_description", sa.Text(), nullable=False),
        sa.Column("event_date_raw", sa.String(50), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("additional_info", sa.Text(), nullable=True),
        sa.Column("sequence_number", sa.SmallInteger(), nullable=False),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["deliveries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "delivery_id",
            "event_description",
            "event_date_raw",
            name="uq_event_fingerprint",
        ),
    )
    # Composite index supports efficient ``ORDER BY sequence_number`` for
    # the delivery detail endpoint (API-REQ-014).
    op.create_index(
        "idx_event_delivery_seq",
        "delivery_events",
        ["delivery_id", "sequence_number"],
    )

    # ──────────────────────────────────────────────────────────────────────────
    # 5. status_history
    #
    #    Immutable once written (DM-BR-012).  ``previous_*`` columns are NULL
    #    only on the *first* StatusHistory entry for a delivery — the one
    #    created when it is first seen by the poller (DM-BR-010).
    #
    #    ``poll_log_id`` is nullable to accommodate records written outside
    #    normal polling (e.g. seed, manual correction).  ON DELETE SET NULL
    #    means a poll_log deletion does not cascade to history rows.
    # ──────────────────────────────────────────────────────────────────────────
    op.create_table(
        "status_history",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("delivery_id", UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status_code", sa.SmallInteger(), nullable=True),
        sa.Column("previous_semantic_status", sa.String(50), nullable=True),
        sa.Column("new_status_code", sa.SmallInteger(), nullable=False),
        sa.Column("new_semantic_status", sa.String(50), nullable=False),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("poll_log_id", UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["deliveries.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["poll_log_id"],
            ["poll_logs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_status_history_delivery",
        "status_history",
        ["delivery_id", "detected_at"],
    )
    op.create_index(
        "idx_status_history_detected_at", "status_history", ["detected_at"]
    )


def downgrade() -> None:
    # Drop in reverse FK-dependency order so constraints are never violated.
    #
    # Indexes on each table are automatically dropped in PostgreSQL when the
    # table is dropped, but are listed here explicitly for documentation
    # clarity and cross-database compatibility.

    # 5. status_history — references deliveries + poll_logs; drop first
    op.drop_index("idx_status_history_detected_at", table_name="status_history")
    op.drop_index("idx_status_history_delivery", table_name="status_history")
    op.drop_table("status_history")

    # 4. delivery_events — references deliveries
    op.drop_index("idx_event_delivery_seq", table_name="delivery_events")
    op.drop_table("delivery_events")

    # 3. deliveries — now no longer referenced by events or history
    op.drop_index("idx_delivery_updated_at", table_name="deliveries")
    op.drop_index("idx_delivery_last_seen", table_name="deliveries")
    op.drop_index("idx_delivery_timestamp_expected", table_name="deliveries")
    op.drop_index("idx_delivery_semantic_status", table_name="deliveries")
    op.drop_table("deliveries")

    # 2. poll_logs — now no longer referenced by status_history
    op.drop_index("idx_poll_log_outcome", table_name="poll_logs")
    op.drop_index("idx_poll_log_started_at", table_name="poll_logs")
    op.drop_table("poll_logs")

    # 1. users — no FK references; drop last
    op.drop_index("uq_user_username", table_name="users")
    op.drop_table("users")
