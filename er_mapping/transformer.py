from er_mapping.transformer_utils import (
    AttributeHelper,
    DependencyResolver,
    ERDIndexer,
    ERDValidator,
)


class ERTransformer:

    def __init__(self, erd_json):
        self.erd = erd_json
        self.entities = {e["name"]: e for e in self.erd.get("entities", [])}
        self.tables = {}
        self.foreign_keys = []
        self.identifying_map = ERDIndexer.build_identifying_index(self.erd, self.entities)

    def get_entity_pk_names(self, entity_name):
        if entity_name in self.tables:
            return [
                a["name"]
                for a in self.tables[entity_name]["attributes"]
                if a["is_pk"]
            ]
        return []

    def transform(self):
        ERDValidator.validate(self.entities, self.identifying_map)
        processing_order = DependencyResolver.get_processing_order(self.entities, self.identifying_map)

        for e_name in processing_order:
            self._process_single_entity(e_name)

        self._process_non_identifying_relationships()
        return self.tables, self.foreign_keys

    def _process_single_entity(self, e_name):
        entity = self.entities[e_name]
        simple_attrs, multivalued_attrs = AttributeHelper.flatten_attributes(entity.get("attributes", []))

        if entity.get("isWeak", False): self._build_weak_entity_table(e_name, simple_attrs)
        else: self._build_strong_entity_table(e_name, simple_attrs)

        self._process_multivalued_attributes(e_name, multivalued_attrs)

    def _build_strong_entity_table(self, e_name, simple_attrs):
        table_attrs = [
            {
                "name": attr["name"],
                "is_pk": attr.get("isPrimaryKey", False),
                "is_fk": False,     # FKs will come from relationships
            }
            for attr in simple_attrs
        ]
        self.tables[e_name] = {"attributes": table_attrs}

    def _build_weak_entity_table(self, e_name, simple_attrs):
        table_attrs = []
        parent_names = self.identifying_map.get(e_name, [])
        # Primary Key
        for p_name in parent_names:
            parent_pks = self.get_entity_pk_names(p_name)  # since we are building with topological order, it's guaranteed that parents are already found in table
            for pk in parent_pks:
                fk_col = (
                    f"{p_name}_{pk}"
                    if pk in [a["name"] for a in simple_attrs]
                    else pk
                )
                table_attrs.append(
                    {"name": fk_col, "is_pk": True, "is_fk": True}
                )
                self.foreign_keys.append((e_name, fk_col, p_name, pk))

        # Partial Keys and regular attributes
        for attr in simple_attrs:
            is_part_key = attr.get("isPartialKey", False) or attr.get(
                "isPrimaryKey", False
            )
            table_attrs.append(
                {"name": attr["name"], "is_pk": is_part_key, "is_fk": False}
            )

        self.tables[e_name] = {"attributes": table_attrs}

    def _process_multivalued_attributes(self, e_name, multivalued_attrs):
        for mv in multivalued_attrs:
            attr_base_name = mv.get("parent_attr", mv["name"])
            mv_table_name = f"{e_name}_{attr_base_name}"

            if mv_table_name not in self.tables:
                parent_pks = self.get_entity_pk_names(e_name)
                mv_attrs = []
                for pk in parent_pks:
                    mv_attrs.append(
                        {"name": f"{e_name}_{pk}", "is_pk": True, "is_fk": True}
                    )
                    self.foreign_keys.append(
                        (mv_table_name, f"{e_name}_{pk}", e_name, pk)
                    )
                self.tables[mv_table_name] = {"attributes": mv_attrs}

            self.tables[mv_table_name]["attributes"].append(
                {"name": mv["name"], "is_pk": True, "is_fk": False}
            )

    def _process_non_identifying_relationships(self):
        non_identifying = [
            r
            for r in self.erd.get("relationships", [])
            if not r.get("isIdentifying", False)
        ]
        for rel in non_identifying:
            self._map_relationship(rel)

    def _map_relationship(self, rel):
        entities = rel.get("entities", [])
        rel_name = rel.get("name")
        rel_attrs, _ = AttributeHelper.flatten_attributes(rel.get("attributes", []))

        # If more than one side is 'N'/'M', or if degree > 2, build a junction table
        n_or_m_count = sum(1 for e in entities if e.get("cardinality") in ["N", "M"])

        if n_or_m_count >= 2 or len(entities) > 2:
            junction_attrs = []

            # Pull PKs from all participating entities
            for ent in entities:
                e_name = ent["eName"]
                pks = self.get_entity_pk_names(e_name)
                for pk in pks:
                    fk_col = f"{e_name}_{pk}"
                    junction_attrs.append({"name": fk_col, "is_pk": True, "is_fk": True})
                    self.foreign_keys.append((rel_name, fk_col, e_name, pk))

            # Add relationship descriptive attributes
            for attr in rel_attrs:
                junction_attrs.append({"name": attr["name"],"is_pk": bool(attr.get("isPrimaryKey", False)), "is_fk": False})

            self.tables[rel_name] = {"attributes": junction_attrs}

        # 1:N Relationship -> Foreign Key on N-side
        elif n_or_m_count == 1:
            one_side = next(e for e in entities if e.get("cardinality") == "1")
            n_side = next(e for e in entities if e.get("cardinality") in ["N", "M"])

            one_name, n_name = one_side["eName"], n_side["eName"]
            one_pks = self.get_entity_pk_names(one_name)

            # Append parent PKs as FKs on the N-side table
            for pk in one_pks:
                fk_col = f"{one_name}_{pk}" if pk in [a["name"] for a in self.tables[n_name]["attributes"]] else pk
                self.tables[n_name]["attributes"].append({"name": fk_col, "is_pk": False, "is_fk": True})
                self.foreign_keys.append((n_name, fk_col, one_name, pk))

            # Append relationship descriptive attributes to the N-side table
            for attr in rel_attrs:
                self.tables[n_name]["attributes"].append({"name": attr["name"], "is_pk": bool(attr.get("isPrimaryKey", False)), "is_fk": False})

        # 1:1 Relationship -> Foreign Key on Total Participation side
        elif n_or_m_count == 0:
            # Prefer side with total participation, default to second entity
            target_side = next((e for e in entities if e.get("participation") == "total"), entities[1])
            source_side = next(e for e in entities if e["eName"] != target_side["eName"])

            target_name, source_name = target_side["eName"], source_side["eName"]
            source_pks = self.get_entity_pk_names(source_name)

            for pk in source_pks:
                fk_col = f"{source_name}_{pk}" if pk in [a["name"] for a in
                                                         self.tables[target_name]["attributes"]] else pk
                self.tables[target_name]["attributes"].append({"name": fk_col, "is_pk": False, "is_fk": True})
                self.foreign_keys.append((target_name, fk_col, source_name, pk))

            for attr in rel_attrs:
                self.tables[target_name]["attributes"].append({"name": attr["name"], "is_pk": bool(attr.get("isPrimaryKey", False)), "is_fk": False})