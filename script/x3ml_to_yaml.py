"""One-time migration of 3M/X3ML mappings and generator policies to the YAML rule format.

Usage:
    x3ml_to_yaml.py <mapping.x3ml> <generator-policy.xml> <output.yaml> [--default-prefix lynx]

The YAML file is self-contained (namespaces, generators, and rules), so the 3M
tool and its Java engine are no longer needed to produce RDF.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml
from lxml import etree

BUILTIN_GENERATORS = {
    "UUID": {"kind": "uuid"},
    "URIorUUID": {"kind": "uri_or_uuid"},
}
LABEL_GENERATORS = {"Literal", "prefLabel"}
DROPPED_NAMESPACE_PREFIXES = {"", "rdf", "rdfs", "owl", "xsd"}
DEFAULT_NAMESPACE = "http://www.lynx.com/resource/"


class MigrationError(ValueError):
    pass


def text(element: etree._Element, path: str) -> str:
    value = element.findtext(path)
    return (value or "").strip()


def convert_namespaces(root: etree._Element) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    for namespace in root.iter("namespace"):
        prefix, uri = namespace.get("prefix", ""), namespace.get("uri", "")
        if prefix in DROPPED_NAMESPACE_PREFIXES or not uri:
            continue
        if namespaces.setdefault(prefix, uri) != uri:
            raise MigrationError(f"Namespace prefix {prefix!r} is bound to two different URIs.")
    return namespaces


def convert_policy(policy_path: Path) -> dict[str, dict[str, Any]]:
    generators: dict[str, dict[str, Any]] = {}
    for generator in etree.parse(str(policy_path)).getroot().findall("generator"):
        name = generator.get("name")
        if generator.find("pattern") is not None:
            definition: dict[str, Any] = {"pattern": text(generator, "pattern")}
            if generator.get("prefix"):
                definition["prefix"] = generator.get("prefix")
            if generator.get("uuid") == "yes":
                definition["uuid"] = True
            generators[name] = definition
        elif generator.find("custom") is not None:
            custom_class = generator.find("custom").get("generatorClass", "")
            if custom_class.endswith("URIorUUID"):
                generators[name] = {"kind": "uri_or_uuid"}
            else:
                generators[name] = {"kind": "unsupported", "class": custom_class}
    return generators


def convert_condition(element: etree._Element) -> dict[str, Any]:
    children = [child for child in element if isinstance(child.tag, str)]
    if len(children) != 1:
        raise MigrationError(f"Unsupported <{element.tag}> condition with {len(children)} children.")
    child = children[0]
    if child.tag == "if":
        return convert_condition(child)
    if child.tag == "exists":
        return {"exists": (child.text or "").strip()}
    if child.tag == "equals":
        return {"equals": [(child.text or "").strip(), child.get("value", "")]}
    if child.tag == "not":
        return {"not": convert_condition(child)}
    if child.tag in {"and", "or"}:
        return {child.tag: [convert_condition(operand) for operand in child if isinstance(operand.tag, str)]}
    raise MigrationError(f"Unsupported condition <{child.tag}>.")


def convert_args(generator: etree._Element) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for arg in generator.findall("arg"):
        value = (arg.text or "").strip()
        args[arg.get("name")] = {"const": value} if arg.get("type") == "constant" else value
    return args


def convert_entity(entity: etree._Element, used_generators: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"types": [type_.text.strip() for type_ in entity.findall("type")]}

    instance_generator = entity.find("instance_generator")
    if instance_generator is not None:
        name = instance_generator.get("name")
        used_generators.add(name)
        uri: dict[str, Any] = {"generator": name}
        args = convert_args(instance_generator)
        if args:
            uri["args"] = args
        result["uri"] = uri

    label_generator = entity.find("label_generator")
    if label_generator is not None:
        if label_generator.get("name") not in LABEL_GENERATORS:
            raise MigrationError(f"Unsupported label generator {label_generator.get('name')!r}.")
        args = convert_args(label_generator)
        result["label"] = args["text"]

    additional = [
        {
            "predicate": text(extra, "relationship"),
            "entity": convert_entity(extra.find("entity"), used_generators),
        }
        for extra in entity.findall("additional")
    ]
    if additional:
        result["additional"] = additional
    return result


def convert_target_node(target_node: etree._Element, used_generators: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    condition = target_node.find("if")
    if condition is not None:
        result["when"] = convert_condition(condition)
    result["entity"] = convert_entity(target_node.find("entity"), used_generators)
    return result


def convert_link(link: etree._Element, used_generators: set[str]) -> dict[str, Any]:
    target_relation = link.find("path/target_relation")
    path_condition = target_relation.find("if")
    steps = [child for child in target_relation if isinstance(child.tag, str) and child.tag != "if"]
    expected_tags = ["relationship", "entity"] * ((len(steps) - 1) // 2) + ["relationship"]
    if [step.tag for step in steps] != expected_tags:
        raise MigrationError("target_relation must alternate relationship and entity, ending with a relationship.")

    result: dict[str, Any] = {"range": text(link, "range/source_node")}
    through = [
        {
            "predicate": (steps[index].text or "").strip(),
            "entity": convert_entity(steps[index + 1], used_generators),
        }
        for index in range(0, len(steps) - 1, 2)
    ]
    if through:
        result["through"] = through
    result["predicate"] = (steps[-1].text or "").strip()
    target = convert_target_node(link.find("range/target_node"), used_generators)
    if path_condition is not None:
        conditions = [convert_condition(path_condition)]
        if "when" in target and target["when"] not in conditions:
            conditions.append(target["when"])
        target["when"] = conditions[0] if len(conditions) == 1 else {"and": conditions}
        target = {"when": target.pop("when"), **target}
    result.update(target)
    return result


def convert(x3ml_path: Path, policy_path: Path, default_prefix: str, source: str = "main") -> dict[str, Any]:
    root = etree.parse(str(x3ml_path)).getroot()
    policy = convert_policy(policy_path)
    used_generators: set[str] = set()

    rules = []
    for mapping in root.iter("mapping"):
        rule: dict[str, Any] = {"domain": text(mapping, "domain/source_node")}
        rule.update(convert_target_node(mapping.find("domain/target_node"), used_generators))
        links = [convert_link(link, used_generators) for link in mapping.findall("link")]
        if links:
            rule["links"] = links
        rules.append(rule)

    generators: dict[str, Any] = {}
    for name in sorted(used_generators):
        if name in policy:
            generators[name] = policy[name]
        elif name in BUILTIN_GENERATORS:
            generators[name] = BUILTIN_GENERATORS[name]
        else:
            print(f"warning: generator {name!r} is not defined in {policy_path.name}", file=sys.stderr)
            generators[name] = {"kind": "undefined"}

    namespaces = convert_namespaces(root)
    namespaces.setdefault(default_prefix, DEFAULT_NAMESPACE)
    return {
        "name": text(root, "info/title"),
        "source": source,
        "default_prefix": default_prefix,
        "namespaces": namespaces,
        "generators": generators,
        "rules": rules,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("x3ml", type=Path)
    parser.add_argument("policy", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--default-prefix", default="lynx", help="Namespace prefix used for UUID URIs.")
    parser.add_argument(
        "--source",
        choices=("main", "relations", "entities"),
        default="main",
        help="Export the mapping applies to in the pipeline.",
    )
    args = parser.parse_args()

    try:
        document = convert(args.x3ml, args.policy, args.default_prefix, args.source)
    except (OSError, etree.XMLSyntaxError, MigrationError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
