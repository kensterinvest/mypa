# MyPA migrations

Hand-rolled, ordered SQL migrations. Simpler than Alembic for a
single-user, single-writer SQLCipher database. If/when the schema starts
moving fast enough to make hand-rolling painful, adopt Alembic.

## File naming

`00N_short_description.sql` — three-digit zero-padded sequence, then a
short `snake_case` name. The lexical order of filenames IS the
application order.

## What each file contains

Pure SQL (one statement per logical change, semicolon-terminated).
Wrap any potentially-failing block in `BEGIN; ... COMMIT;` to keep the
DB consistent if mid-migration interruption happens.

## How they get applied

`scripts/apply_migrations.py` walks `migrations/*.sql` in order, skips
any whose filename is recorded in `schema_versions`, applies the rest
in a single transaction, then records the filename. Idempotent — safe
to run on every deploy.

## What's in 001_init.sql

The initial schema (items, reminders, indexes, schema_versions table
itself). This was bootstrapped via `Base.metadata.create_all()` for
the very first deploy and is recorded here so subsequent installs
have a single source of truth.

## Adding a column

1. Write `00N_add_column_<name>.sql` with `ALTER TABLE items ADD COLUMN ...`.
2. Update `mypa/models.py` to add the corresponding Mapped attribute.
3. Run `python scripts/apply_migrations.py` (which `setup.sh` and CI also call).
4. The next service restart picks up the new column.

## Anti-patterns to avoid

- **DON'T** rely on `Base.metadata.create_all()` after the initial deploy
  — it's a no-op for existing tables, so column additions go silent.
- **DON'T** rename or delete migration files after they've been applied
  to production.
- **DON'T** edit a previously-applied migration; write a new one instead.
- **DON'T** add a migration that requires data backfill without a
  separate one-shot data-migration script run by hand.
