import math
from relational_algebra.relational_algebra_utils import Utils

class Table:
    def __init__(self, name: str, columns: list[str], data: list[dict], expr: str = None):
        self.name = name
        self.columns = columns
        self.data = data
        self.expr = expr or name

    def select_where(self, predicate, text: str) -> "Table":
        rows = [dict(r) for r in self.data if predicate(r)]
        return Table(f"σ_{self.name}", list(self.columns), rows, expr=f"σ[{text}]({self.expr})")

    def select(self, column: str, operator: str, value) -> "Table":
        if column not in self.columns:
            raise ValueError(f"Column '{column}' missing in '{self.name}'.")
        Utils.check_operator(operator)
        return self.select_where(
            lambda r: Utils.compare(r.get(column), operator, value),
            text=f"{column} {operator} {value}"
        )

    def project(self, attributes: list[str]) -> "Table":
        missing = set(attributes) - set(self.columns)
        if missing:
            raise ValueError(f"Attributes {missing} missing in '{self.name}'.")
        seen, data = set(), []
        for r in self.data:
            tup = tuple(r.get(a) for a in attributes)
            if tup not in seen:
                seen.add(tup)
                data.append(dict(zip(attributes, tup)))
        return Table(f"π_{self.name}", list(attributes), data, expr=f"π[{', '.join(attributes)}]({self.expr})")


    def join_where(self, other: "Table", predicate, kind: str, text: str) -> "Table":
        symbols = {"inner": "⋈", "left": "⟕", "right": "⟖"}
        sym = symbols[kind]
        label = f"{self.name} {sym} {other.name}"
        expr = f"({self.expr} {sym}[{text}] {other.expr})"

        _, mapping, cols = Utils.prep_join(self, other, join_key=[], allow_empty=True)

        def merge(l, r):
            row = {c: (l.get(c) if l is not None else None) for c in self.columns}
            row.update({m: (r.get(o) if r is not None else None) for o, m in mapping.items()})
            return row

        joined, matched_right = [], set()
        for l in self.data:
            hit = False
            for i, r in enumerate(other.data):
                if predicate(l, r):
                    joined.append(merge(l, r))
                    matched_right.add(i)
                    hit = True
            if not hit and kind == "left":
                joined.append(merge(l, None))

        if kind == "right":
            for i, r in enumerate(other.data):
                if i not in matched_right:
                    joined.append(merge(None, r))

        return Table(label, cols, joined, expr=expr)

    def _equi_join(self, other: "Table", join_key, keep_left: bool = False, keep_right: bool = False, symbol: str = "⋈", natural: bool = False) -> "Table":
        keys, mapping, cols = Utils.prep_join(self, other, join_key)
        idx = {}
        for i, r in enumerate(other.data):
            k = Utils.row_key(r, keys)
            if None not in k:
                idx.setdefault(k, []).append(i)

        joined, matched_right = [], set()
        for r1 in self.data:
            k = Utils.row_key(r1, keys)
            hits = idx.get(k, []) if None not in k else []
            left_part = {c: r1.get(c) for c in self.columns}
            if hits:
                for i in hits:
                    matched_right.add(i)
                    joined.append({**left_part, **{m: other.data[i].get(o) for o, m in mapping.items()}})
            elif keep_left:
                joined.append({**left_part, **{m: None for m in mapping.values()}})

        if keep_right:
            for i, r2 in enumerate(other.data):
                if i not in matched_right:
                    base = {**{c: None for c in self.columns}, **{k: r2.get(k) for k in keys}}
                    joined.append({**base, **{m: r2.get(o) for o, m in mapping.items()}})

        lbl_keys = "" if natural else f"[{', '.join(keys)}]"
        return Table(f"{self.name} {symbol} {other.name}", cols, joined, expr=f"({self.expr} {symbol}{lbl_keys} {other.expr})")

    def join(self, other: "Table", join_key) -> "Table":
        return self._equi_join(other, join_key, keep_left=False, keep_right=False, symbol="⋈")

    def natural_join(self, other: "Table") -> "Table":
        return self._equi_join(other, None, keep_left=False, keep_right=False, symbol="⋈", natural=True)

    def left_outer_join(self, other: "Table", join_key) -> "Table":
        return self._equi_join(other, join_key, keep_left=True, keep_right=False, symbol="⟕")

    def right_outer_join(self, other: "Table", join_key) -> "Table":
        return self._equi_join(other, join_key, keep_left=False, keep_right=True, symbol="⟖")

    def join_theta(self, other: "Table", left_col: str, operator: str, right_col: str) -> "Table":
        if left_col not in self.columns or right_col not in other.columns:
            raise ValueError("Join columns missing in respective tables.")
        Utils.check_operator(operator)
        return self.join_where(
            other,
            predicate=lambda l, r: Utils.compare(l.get(left_col), operator, r.get(right_col)),
            kind="inner",
            text=f"{left_col} {operator} {right_col}"
        )

    def _set_op(self, other: "Table", op_type: str, symbol: str) -> "Table":
        if sorted(self.columns) != sorted(other.columns):
            raise ValueError("Tables not union-compatible.")

        s2 = {Utils.row_key(r, self.columns) for r in other.data}
        seen, data = set(), []
        candidate_rows = self.data + (other.data if op_type == "union" else [])

        for r in candidate_rows:
            key = Utils.row_key(r, self.columns)
            if key not in seen:
                if op_type == "union" or (op_type == "intersect" and key in s2) or (op_type == "diff" and key not in s2):
                    seen.add(key)
                    data.append({c: r.get(c) for c in self.columns})

        return Table(f"{self.name} {symbol} {other.name}", list(self.columns), data, expr=f"({self.expr} {symbol} {other.expr})")

    def union(self, other: "Table") -> "Table":
        return self._set_op(other, "union", "∪")

    def intersect(self, other: "Table") -> "Table":
        return self._set_op(other, "intersect", "∩")

    def difference(self, other: "Table") -> "Table":
        return self._set_op(other, "diff", "-")

    def aggregate_multi(self, group_cols: list, specs: list) -> "Table":
        for g in group_cols:
            if g not in self.columns:
                raise ValueError(f"Group column '{g}' missing.")
        names = []
        for fn, col, alias in specs:
            if fn not in ("SUM", "AVG", "COUNT", "MAX", "MIN"):
                raise ValueError(f"Invalid function '{fn}'.")
            if col == "*":
                if fn != "COUNT":
                    raise ValueError("Only COUNT can be used with *.")
            elif col not in self.columns:
                raise ValueError(f"Target '{col}' missing.")
            names.append(alias or f"{fn}({col})")
        out_cols = list(group_cols) + names
        if len(set(out_cols)) != len(out_cols):
            raise ValueError("Duplicate output column names; use AS to rename them.")

        def num(v, col):
            if Utils.is_number(v):
                return v
            if isinstance(v, str) and (n := Utils.parse_number(v)) is not None:
                return n
            raise ValueError(f"Non-numeric value {v!r} in '{col}'.")

        groups = {}
        for r in self.data:
            groups.setdefault(tuple(r.get(g) for g in group_cols), []).append(r)
        if not group_cols and not groups:
            groups[()] = []

        rows = []
        for key, rs in groups.items():
            row = dict(zip(group_cols, key))
            for (fn, col, _), name in zip(specs, names):
                if col == "*":
                    val = len(rs)
                else:
                    vals = [r.get(col) for r in rs if r.get(col) is not None]
                    if fn == "COUNT":
                        val = len(vals)
                    elif not vals:
                        val = None
                    elif fn in ("SUM", "AVG"):
                        nums = [num(v, col) for v in vals]
                        val = sum(nums) if fn == "SUM" else sum(nums) / len(nums)
                    else:
                        val = max(vals) if fn == "MAX" else min(vals)
                row[name] = round(val, 2) if isinstance(val, float) else val
            rows.append(row)

        spec_txt = ", ".join(f"{fn}({col})" + (f" AS {a}" if a else "") for fn, col, a in specs)
        group_txt = ", ".join(group_cols) + "; " if group_cols else ""
        return Table(f"γ_{self.name}", out_cols, rows, expr=f"γ[{group_txt}{spec_txt}]({self.expr})")

    def aggregate(self, func: str, target_col: str, group_by_col: str = None) -> "Table":
        group_cols = [group_by_col] if group_by_col else []
        specs = [(func.upper(), target_col, None)]
        return self.aggregate_multi(group_cols, specs)