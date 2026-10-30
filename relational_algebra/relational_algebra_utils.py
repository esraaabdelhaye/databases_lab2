import math
import operator as _op


class Utils:
    OPERATORS = {
        "=": _op.eq,
        "==": _op.eq,
        "!=": _op.ne,
        ">": _op.gt,
        "<": _op.lt,
        ">=": _op.ge,
        "<=": _op.le,
    }

    @staticmethod
    def is_number(value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def parse_number(text: str):
        if not isinstance(text, str):
            return text if Utils.is_number(text) else None
        text = text.strip()
        for cast in (int, float):
            try:
                number = cast(text)
            except ValueError:
                continue
            if isinstance(number, float) and not math.isfinite(number):
                return None
            return number
        return None

    @classmethod
    def check_operator(cls, operator: str) -> None:
        if operator not in cls.OPERATORS:
            raise ValueError(f"Unsupported operator '{operator}'.")

    @classmethod
    def match_pair_type(cls, a, b):
        if a is None or b is None:
            return None
        if cls.is_number(a) and isinstance(b, str):
            number = cls.parse_number(b)
            return (a, number) if number is not None else (str(a), b)
        if cls.is_number(b) and isinstance(a, str):
            number = cls.parse_number(a)
            return (number, b) if number is not None else (a, str(b))
        return a, b

    @classmethod
    def compare(cls, a, operator: str, b) -> bool:
        cls.check_operator(operator)
        pair = cls.match_pair_type(a, b)
        if pair is None:
            return False
        try:
            return cls.OPERATORS[operator](*pair)
        except TypeError:
            return False

    @staticmethod
    def norm_key(value):
        if isinstance(value, str):
            number = Utils.parse_number(value)
            return number if number is not None else value
        return value

    @staticmethod
    def row_key(row: dict, columns: list):
        return tuple(Utils.norm_key(row.get(c)) for c in columns)

    @staticmethod
    def copy_table(table, name: str):
        from relational_algebra.relational_algebra import Table
        return Table(
            name,
            list(table.columns),
            [dict(r) for r in table.data],
            expr=name,
        )

    @staticmethod
    def prep_join(left_table, right_table, join_key=None, allow_empty=False):
        if join_key is None:
            keys = [c for c in left_table.columns if c in right_table.columns]
            if not keys:
                raise ValueError(
                    f"No common columns between '{left_table.name}' and '{right_table.name}'."
                )
        else:
            keys = [join_key] if isinstance(join_key, str) else list(join_key or [])
            if not keys and not allow_empty:
                raise ValueError("At least one join column is required.")
            for k in keys:
                if k not in left_table.columns or k not in right_table.columns:
                    raise ValueError(f"Join key '{k}' must exist in both tables.")

        used, mapping = set(left_table.columns), {}
        for c in [col for col in right_table.columns if col not in keys]:
            new = f"{right_table.name}_{c}" if c in used else c
            while new in used:
                new += "_"
            used.add(new)
            mapping[c] = new

        return keys, mapping, left_table.columns + list(mapping.values())