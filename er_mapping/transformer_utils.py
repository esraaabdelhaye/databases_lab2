from collections import defaultdict, deque


class ERDIndexer:
    @staticmethod
    def build_identifying_index(erd, entities):
        identifying_map = defaultdict(list)

        for rel in erd.get("relationships", []):
            if not rel.get("isIdentifying", False):
                continue

            rel_entities = rel.get("entities", [])
            weak_participants = [
                e["eName"]
                for e in rel_entities
                if entities.get(e["eName"], {}).get("isWeak", False)
            ]

            # Determine target weak entity
            if len(weak_participants) == 1:
                target_weak = weak_participants[0]
            elif len(weak_participants) > 1:
                explicit_targets = [
                    e["eName"]
                    for e in rel_entities
                    if e.get("identifiedByThis", False)
                ]
                if len(explicit_targets) != 1:
                    raise ValueError(
                        f"Identifying relationship '{rel.get('name')}' involves multiple weak entities "
                        f"({weak_participants}), but exactly one must have 'identifiedByThis': true."
                    )
                target_weak = explicit_targets[0]
            else:
                continue

            # Record provider/owner parents for this weak entity
            parents = [
                e["eName"] for e in rel_entities if e["eName"] != target_weak
            ]
            identifying_map[target_weak].extend(parents)

        return dict(identifying_map)


class ERDValidator:
    @staticmethod
    def validate(entities, identifying_map):
        for e_name, entity in entities.items():
            if entity.get("isWeak", False):
                # weak entity MUST be indexed with at least one owner/parent
                if e_name not in identifying_map or not identifying_map[e_name]:
                    raise ValueError(
                        f"Invalid ERD Schema: Weak entity '{e_name}' has no identifying relationship! "
                        f"A weak entity must be identified by at least one owner entity."
                    )


class DependencyResolver: # topological sort
    @staticmethod
    def get_processing_order(entities, identifying_map):
        in_degree = {e_name: 0 for e_name in entities}
        graph = defaultdict(list)

        for weak_target, parents in identifying_map.items():
            for parent in parents:
                graph[parent].append(weak_target)
                in_degree[weak_target] += 1

        queue = deque([e_name for e_name, degree in in_degree.items() if degree == 0])  # queue all entities with indegree = 0 (strong entities)
        ordered_entities = []

        while queue:
            curr = queue.popleft()
            ordered_entities.append(curr)

            for neighbor in graph[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(ordered_entities) != len(entities):
            raise ValueError(
                "Cyclic or unresolvable dependency detected among identifying relationships!"
            )

        return ordered_entities


class AttributeHelper:
    @staticmethod
    def flatten_attributes(attrs):
        simple_attrs = []
        multivalued_attrs = []

        for attr in attrs:
            is_mv = attr.get("isMultiValued", False)
            is_pk = attr.get("isPrimaryKey", False)
            is_partial = attr.get("isPartialKey", False)

            if "composite" in attr:
                for sub_field in attr["composite"]:
                    if is_mv:
                        multivalued_attrs.append(
                            {
                                "name": sub_field,
                                "parent_attr": attr["name"],
                                "isMultiValued": True,
                            }
                        )
                    else:
                        simple_attrs.append(
                            {
                                "name": sub_field,
                                "isPrimaryKey": is_pk,
                                "isPartialKey": is_partial,
                            }
                        )
            elif is_mv: multivalued_attrs.append(attr)
            else: simple_attrs.append(attr)

        return simple_attrs, multivalued_attrs


