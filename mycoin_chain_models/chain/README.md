# MyCoin `chain` app - database models (phase 1)

Models only: no API, no migrations (none were created or run).

## Install
1. Copy the `chain/` folder next to your other apps (rename it if the label `chain` clashes; string references such as
   `"chain.Block"` and the `chain.` imports in `tests/` then need the same rename).
2. Add `"chain"` (or `"chain.apps.ChainConfig"`) to `INSTALLED_APPS`. Database must be PostgreSQL.
3. Run `python manage.py test chain`. The test database is built straight from the models, so tests work
   even though no migration files exist yet. Run `makemigrations` only when you give the go-ahead.

## Layout
- `infrastructure/models/` - `base.py`, `network.py`, `wallets.py`, `ledger.py`, `staking.py` (ORM layer)
- `models.py` - re-exports the models so Django can discover them
- `tests/` - constraint and validation tests (`factories.py` builds valid sample rows)

Django 4.2+ is supported (`check()` in `base.py` picks `check=` vs `condition=` automatically).
