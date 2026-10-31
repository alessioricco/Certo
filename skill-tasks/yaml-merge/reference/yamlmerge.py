"""Merge YAML settings files."""

import sys

import yaml


def merge(*docs):
    result = {}
    for doc in docs:
        for key, value in doc.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = merge(result[key], value)
            elif isinstance(value, dict):
                result[key] = merge(value)
            else:
                result[key] = value
    return result


def load_and_merge(paths):
    docs = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        if doc is None:
            doc = {}
        if not isinstance(doc, dict):
            raise ValueError(f"{path}: the top level is not a mapping")
        docs.append(doc)
    return merge(*docs)


def main(argv):
    if not argv:
        print("usage: python yamlmerge.py FILE...", file=sys.stderr)
        return 2
    try:
        result = load_and_merge(argv)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        print(f"yamlmerge: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(yaml.safe_dump(result, sort_keys=True, default_flow_style=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
