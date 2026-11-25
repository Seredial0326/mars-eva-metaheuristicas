"""
Per-iteration trace of a solver run. A solver receives a Tracer as `trace=`, calls
`trace.start()` on entry, `trace(**fields)` once per iteration and `trace.flush()` before
returning. Each row gets `t_s`, the seconds since start().
"""
import csv
import time


class Tracer:
    """Collects one row per offered call; with every=k keeps row 0, every k-th and the last.

    Meant for one solver run: start() resets only the clock, not the rows.
    """

    def __init__(self, every=1):
        self.every = max(1, int(every))
        self.rows = []
        self._t0 = None
        self._count = 0                                     # calls offered through __call__
        self._pending = None                                # last row offered but not kept

    def start(self):
        """Reset the clock origin: t_s is measured from this call."""
        self._t0 = time.perf_counter()

    def __call__(self, **fields):
        if self._t0 is None:
            self._t0 = time.perf_counter()
        row = {**fields, "t_s": time.perf_counter() - self._t0}
        if self._count % self.every == 0:
            self.rows.append(row)
            self._pending = None
        else:
            self._pending = row
        self._count += 1

    def flush(self):
        """Keep the last row offered even when every > 1 (idempotent)."""
        if self._pending is not None:
            self.rows.append(self._pending)
            self._pending = None

    def extend(self, rows):
        """Append rows that already carry t_s (e.g. from a subprocess); all are kept."""
        self.rows.extend(dict(r) for r in rows)

    def to_csv(self, path, extra=None):
        """Write the rows to `path`, with the columns of `extra` first on every row."""
        extra = extra or {}
        names = list(extra)
        for row in self.rows:
            names += [k for k in row if k not in names]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=names)
            writer.writeheader()
            for row in self.rows:
                writer.writerow({**extra, **row})
