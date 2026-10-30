from query_engine.lexer import QueryError
from query_engine.parser import parse
from relational_algebra.relational_algebra_utils import Utils


def find(scope, name):
    """Exact match, else a unique case-insensitive match."""
    if name in scope:
        return scope[name]
    hits = {v for k, v in scope.items() if k.lower() == name.lower()}
    return hits.pop() if len(hits) == 1 else None


def table_scope(t):
    """Every spelling that may refer to a column of t: col, Table.col and inherited qualifiers."""
    scope = {c: c for c in t.columns}
    scope.update({f"{t.name}.{c}": c for c in t.columns})
    scope.update({q: c for q, c in getattr(t, "qualified", {}).items() if c in t.columns})
    return scope


def column_of(t, name, pos):
    col = find(table_scope(t), name)
    if col is None:
        raise QueryError(f"Unknown column '{name}'. Available: {', '.join(t.columns)}", pos)
    return col


def single_resolver(t):
    def resolve(name, pos):
        col = column_of(t, name, pos)
        return lambda row: row.get(col)

    return resolve


def join_resolver(left, right):
    """Getters over a (left_row, right_row) pair. Bare names shared by both tables are ambiguous."""
    ls, rs = table_scope(left), table_scope(right)
    clash = set(left.columns) & set(right.columns)
    _, mapping, _ = Utils.prep_join(left, right, join_key=[], allow_empty=True)
    renamed = {m: o for o, m in mapping.items()}  # e.g. Department_Name -> Name (right side)

    def resolve(name, pos):
        if name in clash:
            raise QueryError(f"Column '{name}' exists in both tables; write {left.name}.{name} "
                             f"or {right.name}.{name}", pos)
        col = find(ls, name)
        if col is not None:
            return lambda ctx: ctx[0].get(col)
        col = find(rs, name)
        if col is None:
            col = renamed.get(name)
        if col is None:
            raise QueryError(f"Unknown column '{name}'. Available: "
                             f"{', '.join(left.columns + right.columns)}", pos)
        return lambda ctx: ctx[1].get(col)

    return resolve


def join_qualified(l, r, res, natural):
    """Remember 'Table.col' spellings for the joined result so later steps can still use them."""
    _, mapping, _ = Utils.prep_join(l, r, None if natural else [], allow_empty=not natural)
    q = {f"{l.name}.{c}": c for c in l.columns}
    q.update(getattr(l, "qualified", {}))
    for o in r.columns:
        q[f"{r.name}.{o}"] = mapping.get(o, o)
    for qn, col in getattr(r, "qualified", {}).items():
        if col in r.columns:
            q[qn] = mapping.get(col, col)
    return {k: v for k, v in q.items() if v in res.columns}


# ---------------------------------------------------------------- conditions
def compile_cond(node, resolve):
    kind = node[0]
    if kind in ("and", "or"):
        fs = [compile_cond(n, resolve) for n in node[1]]
        combine = all if kind == "and" else any
        return lambda ctx: combine(f(ctx) for f in fs)
    if kind == "not":
        f = compile_cond(node[1], resolve)
        return lambda ctx: not f(ctx)
    _, op, left, right, _pos = node
    gl, gr = _operand(left, resolve), _operand(right, resolve)
    return lambda ctx: Utils.compare(gl(ctx), op, gr(ctx))


def _operand(node, resolve):
    if node[0] == "lit":
        value = node[1]
        return lambda ctx: value
    return resolve(node[1], node[2])


def cond_text(node, top=True):
    kind = node[0]
    if kind == "cmp":
        return f"{_operand_text(node[2])} {node[1]} {_operand_text(node[3])}"
    if kind == "not":
        return f"¬({cond_text(node[1])})"
    text = (" ∧ " if kind == "and" else " ∨ ").join(cond_text(n, False) for n in node[1])
    return text if top else f"({text})"


def _operand_text(node):
    if node[0] == "col":
        return node[1]
    return f"'{node[1]}'" if isinstance(node[1], str) else str(node[1])


def keep(res, src):
    """Unary operators don't change which relation a column came from."""
    res.name = src.name
    res.qualified = getattr(src, "qualified", {})
    return res


# ---------------------------------------------------------------- executor
class Executor:
    def __init__(self, tables):
        self.tables = tables

    def run(self, text):
        return self.eval(parse(text))

    def eval(self, node):
        try:
            return getattr(self, "_" + type(node).__name__.lower())(node)
        except ValueError as e:  # errors raised by Table methods
            raise QueryError(str(e), getattr(node, "pos", None)) from None

    def _tableref(self, n):
        t = self.tables.get(n.name)
        if t is None:
            hits = [k for k in self.tables if k.lower() == n.name.lower()]
            t = self.tables[hits[0]] if len(hits) == 1 else None
        if t is None:
            raise QueryError(f"Unknown table '{n.name}'. Available: {', '.join(self.tables)}", n.pos)
        return t

    def _select(self, n):
        t = self.eval(n.child)
        f = compile_cond(n.cond, single_resolver(t))
        return keep(t.select_where(f, cond_text(n.cond)), t)

    def _project(self, n):
        t = self.eval(n.child)
        cols = [column_of(t, name, pos) for name, pos in n.attrs]
        if len(set(cols)) != len(cols):
            raise QueryError("Duplicate column in PROJECT list", n.pos)
        return keep(t.project(cols), t)

    def _aggregate(self, n):
        t = self.eval(n.child)
        groups = [column_of(t, name, pos) for name, pos in n.groups]
        specs = [(fn, "*" if col == "*" else column_of(t, col, pos), alias) for fn, col, alias, pos in n.specs]
        return t.aggregate_multi(groups, specs)

    def _join(self, n):
        l, r = self.eval(n.left), self.eval(n.right)
        if n.cond is None:  # natural: match on all common columns
            res = {
                "inner": lambda: l.natural_join(r),
                "left": lambda: l.left_outer_join(r, None),
                "right": lambda: l.right_outer_join(r, None),
            }[n.kind]()
        else:
            if l.name == r.name:
                raise QueryError(f"Both sides are called '{l.name}'. Use distinct table aliases.", n.pos)
            f = compile_cond(n.cond, join_resolver(l, r))
            res = l.join_where(r, lambda a, b: f((a, b)), n.kind, cond_text(n.cond))

        res.qualified = join_qualified(l, r, res, natural=n.cond is None)
        return res

    def _setop(self, n):
        l, r = self.eval(n.left), self.eval(n.right)
        return {"UNION": l.union, "INTERSECT": l.intersect,
                "MINUS": l.difference, "DIFFERENCE": l.difference}[n.op](r)