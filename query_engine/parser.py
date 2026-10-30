from dataclasses import dataclass
from query_engine.lexer import tokenize, QueryError


@dataclass
class TableRef:
    name: str
    pos: int


@dataclass
class Select:
    cond: tuple
    child: object
    pos: int


@dataclass
class Project:
    attrs: list
    child: object
    pos: int


@dataclass
class Aggregate:
    groups: list
    specs: list
    child: object
    pos: int


@dataclass
class Join:
    kind: str  # inner | left | right
    cond: object
    left: object
    right: object
    pos: int


@dataclass
class SetOp:
    op: str  # UNION | INTERSECT | MINUS | DIFFERENCE
    left: object
    right: object
    pos: int


AGG_FUNCS = {"SUM", "AVG", "COUNT", "MAX", "MIN"}
BIN_KWS = ("JOIN", "LEFT", "RIGHT")


def describe(tok):
    return "the end of the query" if tok.kind == "EOF" else f"'{tok.value}'"


class Parser:
    def __init__(self, text):
        self.toks = tokenize(text)
        self.i = 0

    # ---- helpers
    @property
    def cur(self):
        return self.toks[self.i]

    def advance(self):
        tok = self.cur
        if tok.kind != "EOF":
            self.i += 1
        return tok

    def peek_kw(self, *names):
        return self.cur.kind == "KW" and self.cur.value in names

    def expect(self, kind, label):
        if self.cur.kind != kind:
            raise QueryError(f"Expected {label} but found {describe(self.cur)}", self.cur.pos)
        return self.advance()

    def expect_kw(self, name):
        if not self.peek_kw(name):
            raise QueryError(f"Expected {name} but found {describe(self.cur)}", self.cur.pos)
        return self.advance()

    # ---- grammar
    def parse(self):
        node = self.set_expr()
        if self.cur.kind != "EOF":
            raise QueryError(f"Unexpected {describe(self.cur)}", self.cur.pos)
        return node

    def set_expr(self):  # lowest precedence, left associative
        left = self.bin_expr()
        while self.peek_kw("UNION", "INTERSECT", "MINUS", "DIFFERENCE"):
            t = self.advance()
            left = SetOp(t.value, left, self.bin_expr(), t.pos)
        return left

    def bin_expr(self):  # joins: left associative
        left = self.primary()
        while self.peek_kw(*BIN_KWS):
            t = self.advance()
            if t.value in ("LEFT", "RIGHT"):
                self.expect_kw("JOIN")
                kind = t.value.lower()
            else:
                kind = "inner"

            cond = None
            if self.cur.kind == "LBRACK":
                self.advance()
                # Equi-join column list check: JOIN[col1, col2] vs JOIN[TableA.col = TableB.col]
                if self.cur.kind == "IDENT" and self.toks[self.i + 1].kind in ("COMMA", "RBRACK"):
                    cols = self.name_list()
                    cond = ("and", [("cmp", "=", ("col", c, p), ("col", c, p), p) for c, p in cols])
                else:
                    cond = self.cond()
                self.expect("RBRACK", "']'")
            left = Join(kind, cond, left, self.primary(), t.pos)
        return left

    def primary(self):
        t = self.cur
        if t.kind == "KW" and t.value in ("SELECT", "PROJECT", "AGGREGATE"):
            self.advance()
            self.expect("LBRACK", "'['")
            if t.value == "SELECT":
                arg = self.cond()
            elif t.value == "PROJECT":
                arg = self.name_list()
            else:
                arg = self.agg_spec()
            self.expect("RBRACK", "']'")
            self.expect("LPAREN", "'(' before the operand")
            child = self.set_expr()
            self.expect("RPAREN", "')'")
            if t.value == "SELECT":
                return Select(arg, child, t.pos)
            if t.value == "PROJECT":
                return Project(arg, child, t.pos)
            return Aggregate(arg[0], arg[1], child, t.pos)
        if t.kind == "LPAREN":
            self.advance()
            node = self.set_expr()
            self.expect("RPAREN", "')'")
            return node
        if t.kind == "IDENT":
            self.advance()
            return TableRef(t.value, t.pos)
        raise QueryError(f"Expected a table name, an operator or '(' but found {describe(t)}", t.pos)

    def name_list(self):
        names = []
        while True:
            t = self.expect("IDENT", "a column name")
            names.append((t.value, t.pos))
            if self.cur.kind != "COMMA":
                return names
            self.advance()

    def agg_spec(self):
        """[SUM(Salary), COUNT(*) AS n]  or  [DeptID, City; SUM(Salary) AS Total]"""
        j, has_semi = self.i, False
        while self.toks[j].kind not in ("RBRACK", "EOF"):
            has_semi = has_semi or self.toks[j].kind == "SEMI"
            j += 1
        groups = []
        if has_semi:
            groups = self.name_list()
            self.expect("SEMI", "';' after the grouping columns")
        specs = []
        while True:
            f = self.expect("IDENT", "an aggregate function (SUM, AVG, COUNT, MAX, MIN)")
            if f.value.upper() not in AGG_FUNCS:
                raise QueryError(f"Unknown aggregate function '{f.value}'", f.pos)
            self.expect("LPAREN", "'('")
            if self.cur.kind == "STAR":
                self.advance()
                col = "*"
            else:
                col = self.expect("IDENT", "a column name or *").value
            self.expect("RPAREN", "')'")
            alias = None
            if self.peek_kw("AS"):
                self.advance()
                alias = self.expect("IDENT", "an alias").value
            specs.append((f.value.upper(), col, alias, f.pos))
            if self.cur.kind != "COMMA":
                return groups, specs
            self.advance()

    # ---- conditions: OR < AND < NOT < comparison / parentheses
    def cond(self):
        parts = [self.and_cond()]
        while self.peek_kw("OR"):
            self.advance()
            parts.append(self.and_cond())
        return parts[0] if len(parts) == 1 else ("or", parts)

    def and_cond(self):
        parts = [self.not_cond()]
        while self.peek_kw("AND"):
            self.advance()
            parts.append(self.not_cond())
        return parts[0] if len(parts) == 1 else ("and", parts)

    def not_cond(self):
        if self.peek_kw("NOT"):
            self.advance()
            return ("not", self.not_cond())
        if self.cur.kind == "LPAREN":
            self.advance()
            c = self.cond()
            self.expect("RPAREN", "')'")
            return c
        left = self.operand()
        op = self.expect("OP", "a comparison operator (=, !=, <, >, <=, >=)")
        return ("cmp", op.value, left, self.operand(), op.pos)

    def operand(self):
        t = self.cur
        if t.kind == "IDENT":
            self.advance()
            return ("col", t.value, t.pos)
        if t.kind in ("NUMBER", "STRING"):
            self.advance()
            return ("lit", t.value)
        raise QueryError(f"Expected a column name, number or 'text' but found {describe(t)}", t.pos)


def parse(text):
    return Parser(text).parse()