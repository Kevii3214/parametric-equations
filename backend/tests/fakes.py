"""Small in-memory stand-in for the Supabase client, shared by the agent tests."""

from itertools import count
from types import SimpleNamespace
from uuid import UUID

from postgrest.exceptions import APIError


class FakeSupabase:
    def __init__(self, **tables):
        self.tables = {name: [dict(r) for r in rows] for name, rows in tables.items()}
        self.ids = count(1)
        self.fail_tables: set[str] = set()
        self.strict_uuid = (
            False  # like Postgres: an id that is not a UUID is an error, not "no rows"
        )
        self.missing_columns: dict[
            str, set[str]
        ] = {}  # table -> columns the database does not have yet

    def table(self, name):
        return _Query(self, name)

    def rows(self, name):
        return self.tables.setdefault(name, [])


class _Query:
    def __init__(self, db, table):
        self.db, self.name = db, table
        self.action, self.payload, self.filters = "select", None, []

    def insert(self, row):
        self.action, self.payload = "insert", row
        return self

    def update(self, values):
        self.action, self.payload = "update", values
        return self

    def select(self, *_):
        self.action = "select"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.name in self.db.fail_tables:
            raise RuntimeError(f"{self.name} is unavailable")
        self._check_ids()
        rows = self.db.rows(self.name)
        matching = [r for r in rows if all(r.get(c) == v for c, v in self.filters)]
        if self.action == "insert":
            missing = self.db.missing_columns.get(self.name, set()) & set(self.payload)
            if missing:
                raise RuntimeError(f"Could not find the {min(missing)!r} column of {self.name!r}")
            row = {"id": next(self.db.ids), **self.payload}
            rows.append(row)
            return SimpleNamespace(data=[row])
        if self.action == "update":
            for row in matching:
                row.update(self.payload)
            return SimpleNamespace(data=matching)
        return SimpleNamespace(data=matching)

    def _check_ids(self):
        if not self.db.strict_uuid:
            return
        for column, value in self.filters:
            if column in ("id", "incident_id"):
                try:
                    UUID(str(value))
                except ValueError:
                    raise APIError(
                        {
                            "message": f'invalid input syntax for type uuid: "{value}"',
                            "code": "22P02",
                        }
                    ) from None
