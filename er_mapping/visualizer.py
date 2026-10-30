from graphviz import Digraph


class RelationalSchemaVisualizer:
    PALETTE = [
        "#C00000",  # Crimson Red
        "#0070C0",  # Royal Blue
        "#008000",  # Forest Green
        "#7030A0",  # Purple
        "#ED7D31",  # Burnt Orange
        "#008080",  # Teal
        "#C55A11",  # Bronze
        "#70AD47",  # Olive
        "#4472C4",  # Steel Blue
    ]

    def __init__(self, tables, foreign_keys):
        self.tables = tables
        self.foreign_keys = foreign_keys
        self._table_colors = self._assign_table_colors()

    def _assign_table_colors(self):
        table_colors = {}
        for i, table_name in enumerate(self.tables.keys()):
            table_colors[table_name] = self.PALETTE[i % len(self.PALETTE)]
        return table_colors

    def render(
        self, output_path="schema_diagram", fmt="png"
    ) -> str:
        dot = Digraph(name="Relational_Schema", format=fmt)
        dot.attr(
            dpi="300",  # High resolution for crisp text
            rankdir="TB",  # Top-to-Bottom flow
            splines="curved",  # Smooth curved lines that route around nodes naturally
            nodesep="0.8",  # Spacing between side-by-side nodes
            ranksep="1.2",  # Vertical gap between levels
        )
        dot.attr("node", fontname="Arial", fontsize="10", shape="none")

        for table_name, table_info in self.tables.items():
            attr_cells = []
            for attr in table_info["attributes"]:
                name = attr["name"]
                is_pk, is_fk = attr["is_pk"], attr["is_fk"]

                if is_pk and is_fk:
                    label = f"<u><b>{name}</b></u> (PK, FK)"
                elif is_pk:
                    label = f"<u><b>{name}</b></u> (PK)"
                elif is_fk:
                    label = f"{name} (FK)"
                else:
                    label = name

                bg = "#D9E1F2" if is_pk else "#FFFFFF"
                attr_cells.append(
                    f'<td align="center" bgcolor="{bg}" port="{name}">{label}</td>'
                )

            table_cols = max(len(attr_cells), 1)
            table_label = f"""<
            <table border="1" cellborder="1" cellspacing="0" cellpadding="6">
                <tr>
                    <td bgcolor="#1F4E78" colspan="{table_cols}">
                        <font color="white"><b>{table_name}</b></font>
                    </td>
                </tr>
                <tr>
                    {"".join(attr_cells)}
                </tr>
            </table>
            >"""

            dot.node(table_name, label=table_label)

        # Curved Edges
        for from_t, from_c, to_t, to_c in self.foreign_keys:
            source = f"{from_t}:{from_c}"
            target = f"{to_t}:{to_c}"
            edge_color = self._table_colors.get(from_t, "#000000")

            dot.edge(
                source,
                target,
                color=edge_color,
                penwidth="1.8",
                arrowhead="vee",
            )

        output_filename = dot.render(filename=output_path, cleanup=True)
        print(f"Diagram rendered successfully at: {output_filename}")
        return output_filename