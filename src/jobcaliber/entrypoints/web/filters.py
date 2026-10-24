"""The `/jobs` query string, turned into typed rows and SQL filters.

Pure logic on the query params: no FastAPI, no templates, no SQL. A `Column` says what can be
filtered and which widget it needs; a `Row` is what the user set; a `Filter` is the part that
reaches the store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlencode

from jobcaliber.bootstrap import AppContext
from jobcaliber.core.formatting import local_time
from jobcaliber.infrastructure.database import APPLICATION_STATES, Filter

DECISIONS = ("pass", "review", "drop")
DEFAULT_DECISIONS = ("pass", "review")
OPTIONAL_COLUMNS = ("salary", "last_seen", "run", "status")
SORTS = ("score_total", "confidence", "decision", "title", "company", "source",
         "first_seen_at", "last_seen_at", "run_started_at")
FILTER_OPS = {"number": ("lt", "le", "eq", "ge", "gt"), "text": ("contains",),
              "enum": ("is", "is_not"), "date": ("ge", "lt")}
OP_LABELS = {"lt": "<", "le": "≤", "eq": "=", "ge": "≥", "gt": ">",
             "contains": "contains", "is": "is", "is_not": "is not"}
STATUS_OPTIONS = ("none", *APPLICATION_STATES)

@dataclass(frozen=True)
class Column:
    """A filterable table column: its kind decides the widget, its group the sub-box."""

    key: str
    group: str
    kind: str
    label: str
    options: tuple[str, ...] = ()
    option_labels: dict[str, str] = field(default_factory=dict)

    @property
    def ops(self) -> tuple[str, ...]:
        return FILTER_OPS[self.kind]


@dataclass(frozen=True)
class Row:
    """The current state of one column's filter: an empty value means "no filter"."""

    column: Column
    op: str
    value: float | str | tuple[str, ...] | None = None

    @property
    def shown(self) -> str:
        if isinstance(self.value, tuple):
            return ",".join(self.value)
        if isinstance(self.value, float):
            return f"{self.value:g}"
        return self.value or ""

def default_filters() -> dict:
    return {
        "decisions": list(DEFAULT_DECISIONS), "filters": [], "rows": [], "groups": [],
        "exclude_missing": False,
        "columns": set(), "selectable_columns": [], "criterion_columns": [],
        "sort": "score_total", "dir": "desc", "limit": 50, "offset": 0,
    }


def _float(raw: str | None, low: float, high: float) -> float | None:
    try:
        return max(low, min(high, float(raw)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int(raw: str | None, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(raw)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

def _column(key: str, group: str, kind: str, options: tuple[str, ...] = (),
            labels: dict[str, str] | None = None) -> Column:
    return Column(key=key, group=group, kind=kind, label=key.replace("crit:", ""),
                  options=options, option_labels=labels or {})

def filter_columns(ctx: AppContext) -> list[Column]:
    """Every filterable column, in the order the panel shows them."""
    runs = ctx.store.runs(50)
    columns = [
        _column("score", "Score & decision", "number"),
        _column("decision", "Score & decision", "enum", DECISIONS),
        _column("title", "Job", "text"),
        _column("company", "Job", "text"),
        _column("board", "Job", "enum", tuple(ctx.config.scraping.boards)),
        _column("location", "Job", "text"),
        # read from the config: a criterion added today is filterable before the first run
        *[_column(f"crit:{name}", "Criteria",
                  "number" if spec.question.type == "score" else "enum",
                  tuple(spec.question.options) if spec.question.type == "choice" else ())
          for name, spec in ctx.config.criteria.items()],
        _column("status", "Status & dates", "enum", STATUS_OPTIONS),
        _column("run", "Status & dates", "enum", tuple(str(run["id"]) for run in runs),
                {str(run["id"]): f"{local_time(run['started_at'], ctx.tz)} · {run['status']}"
                                 f" · {run['new']} new" for run in runs}),
        _column("last_seen", "Status & dates", "date"),
    ]
    return columns


def read_filter_rows(params, columns: list[Column], decisions: list[str]
                     ) -> tuple[list[Row], list[Filter]]:
    """One row per column: `op__<column>` / `val__<column>` hold what the user set."""
    rows: list[Row] = []
    filters: list[Filter] = []
    for column in columns:
        ops = FILTER_OPS[column.kind]
        op = params.get(f"op__{column.key}")
        op = op if op in ops else ops[0]
        raw = (params.get(f"val__{column.key}") or "").strip()
        if column.key == "decision":
            value: object = tuple(decisions)
        elif column.kind == "enum":
            value = tuple(v for v in params.getlist(f"val__{column.key}") if v in column.options)
        elif column.kind == "number":
            value = _float(raw, -1_000_000.0, 1_000_000.0) if raw else None
        else:
            value = raw[:80] or None
        rows.append(Row(column=column, op=op, value=value))
        if column.key == "decision":
            continue           # already applied through `decisions`
        if isinstance(value, tuple):
            if value:
                filters.append(Filter(column=column.key, op=op, value=value))
        elif value is not None:
            filters.append(Filter(column=column.key, op=op, value=value))
    return rows, filters


def grouped_rows(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    groups: dict[str, list[Row]] = {}
    for row in rows:
        groups.setdefault(row.column.group, []).append(row)
    return list(groups.items())


def parse_filters(params, ctx: AppContext) -> dict:
    """Validate every query parameter: nothing from the URL reaches SQL unchecked."""
    decisions: list[str] = []
    for raw in params.getlist("decisions"):
        decisions.extend(d for d in raw.split(",") if d in DECISIONS)
    if not decisions:
        decisions = list(DECISIONS)
    rows, filters = read_filter_rows(params, filter_columns(ctx), decisions)

    known = list(ctx.config.criteria)
    selectable = [*known, *OPTIONAL_COLUMNS]
    chosen = [c for raw in params.getlist("cols") for c in raw.split(",") if c in selectable]
    visible = set(chosen) if params.getlist("cols") else set(known)

    sort = params.get("sort") or "score_total"
    if not (sort in SORTS or (sort.startswith("crit:") and sort[5:] in known)):
        sort = "score_total"
    return {
        "decisions": decisions,
        "filters": filters,
        "rows": rows,
        "groups": grouped_rows(rows),
        "exclude_missing": params.get("exclude_missing") in ("1", "true", "on"),
        "sort": sort, "dir": "asc" if params.get("dir") == "asc" else "desc",
        "columns": visible, "selectable_columns": selectable,
        "criterion_columns": [c for c in known if c in visible],
        "limit": _int(params.get("limit"), 50, 10, 200), "offset": _int(params.get("offset"), 0, 0, 100000),
    }


def jobs_url(filters: dict, **overrides) -> str:
    merged = {**filters, **overrides}
    pairs = [("decisions", ",".join(merged["decisions"]))]
    if merged.get("exclude_missing"):
        pairs.append(("exclude_missing", "1"))
    for row in merged.get("rows", ()):
        shown = row.shown
        if not shown:
            continue
        if row.column.kind in ("number", "date"):
            pairs.append((f"op__{row.column.key}", row.op))
        if isinstance(row.value, tuple):
            pairs.extend((f"val__{row.column.key}", item) for item in row.value)
        else:
            pairs.append((f"val__{row.column.key}", shown))
    pairs += [("cols", ",".join(sorted(merged["columns"]))), ("sort", merged["sort"]),
              ("dir", merged["dir"]), ("limit", str(merged["limit"])),
              ("offset", str(merged["offset"]))]
    return "/jobs?" + urlencode([(k, v) for k, v in pairs if v != ""], doseq=True)

def detail_url(filters: dict, job_id: int) -> str:
    """The detail page carries the current query string, so "back" returns to the same list."""
    _, _, query = jobs_url(filters).partition("?")
    return f"/jobs/{job_id}?{query}" if query else f"/jobs/{job_id}"
