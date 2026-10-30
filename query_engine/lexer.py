import re
from collections import namedtuple


class QueryError(Exception):
    def __init__(self, message, pos=None):
        super().__init__(message)
        self.message, self.pos = message, pos


Token = namedtuple("Token", "kind value pos")

KEYWORDS = {
    "SELECT", "PROJECT", "AGGREGATE", "JOIN", "LEFT", "RIGHT",
    "UNION", "INTERSECT", "MINUS", "DIFFERENCE", "AND", "OR", "NOT", "AS",
}

SYMBOLS = {    "σ": ["SELECT"], "π": ["PROJECT"],"γ": ["AGGREGATE"], "⋈": ["JOIN"], "⟕": ["LEFT", "JOIN"], "⟖": ["RIGHT", "JOIN"],
    "∪": ["UNION"], "∩": ["INTERSECT"], "−": ["MINUS"], "∧": ["AND"], "∨": ["OR"], "¬": ["NOT"],}

PUNCT = {"(": "LPAREN", ")": "RPAREN", "[": "LBRACK", "]": "RBRACK",
    ",": "COMMA",  ";": "SEMI", "*": "STAR"}


CMP_SYMBOLS = {"≥": ">=", "≤": "<=", "≠": "!="}
OPS_MAP = {"<>": "!=", "==": "="}
IDENT_RE = re.compile(r"[^\W\d]\w*(?:\.\w+)*")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def tokenize(text):
    tokens, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in SYMBOLS:
            tokens.extend(Token("KW", kw, i) for kw in SYMBOLS[ch])
            i += 1
            continue
        if ch in CMP_SYMBOLS:
            tokens.append(Token("OP", CMP_SYMBOLS[ch], i))
            i += 1
            continue
        if ch in PUNCT:
            tokens.append(Token(PUNCT[ch], ch, i))
            i += 1
            continue
        two = text[i:i + 2]
        if two in (">=", "<=", "!=", "<>", "=="):
            tokens.append(Token("OP", OPS_MAP.get(two, two), i))
            i += 2
            continue
        if ch in "=<>":
            tokens.append(Token("OP", ch, i))
            i += 1
            continue
        if ch in "'\"":
            end = text.find(ch, i + 1)
            if end == -1:
                raise QueryError("Unterminated string", i)
            tokens.append(Token("STRING", text[i + 1:end], i))
            i = end + 1
            continue
        negative = ch == "-" and i + 1 < n and text[i + 1].isdigit() and tokens and tokens[-1].kind == "OP"
        if ch.isdigit() or negative:
            m = NUMBER_RE.match(text, i)
            raw = m.group()
            tokens.append(Token("NUMBER", float(raw) if "." in raw else int(raw), i))
            i = m.end()
            continue
        m = IDENT_RE.match(text, i)
        if m:
            word = m.group()
            is_kw = word.upper() in KEYWORDS
            tokens.append(Token("KW" if is_kw else "IDENT", word.upper() if is_kw else word, i))
            i = m.end()
            continue
        hint = " (use MINUS for set difference)" if ch == "-" else ""
        raise QueryError(f"Unexpected character '{ch}'{hint}", i)
    tokens.append(Token("EOF", None, n))
    return tokens