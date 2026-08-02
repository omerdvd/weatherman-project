#!/usr/bin/env python3
"""Merge newly-introduced config.example.yaml keys into config.yaml.

Invoked by update.sh - not meant to be run standalone, though it works fine
that way too. Two modes:

  --list   Print each new key (dot-notation path) and its default value,
            one per line. Exit 0 if any were found, 1 if none.
  --apply  Same, but also writes the new keys into --config, preserving
           existing comments/formatting/ordering via ruamel.yaml's
           round-trip mode. Only ever adds missing keys - never touches
           or removes an existing one.

Given an old and a new config.example.yaml (from two different releases)
and the user's current config.yaml, finds keys present in the new example
but absent from both the old example and the user's config, then reports or
applies just the ones still missing from the user's config.
"""

import argparse
import sys

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap


def load_plain(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def find_new_keys(old_tree, new_tree, prefix=()):
    """Keys present in new_tree but not in old_tree, recursively. Returns a
    list of (path_tuple, default_value); a path stops descending once it
    hits a key that's entirely new (the whole subtree becomes the default)."""
    new_keys = []
    if isinstance(new_tree, dict):
        old_tree = old_tree if isinstance(old_tree, dict) else {}
        for key, value in new_tree.items():
            path = prefix + (key,)
            if key not in old_tree:
                new_keys.append((path, value))
            else:
                new_keys.extend(find_new_keys(old_tree[key], value, path))
    return new_keys


def missing_from_config(user_config, candidate_keys):
    missing = []
    for path, default in candidate_keys:
        node = user_config
        found_parent = True
        for part in path[:-1]:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                found_parent = False
                break
        if found_parent and isinstance(node, dict) and path[-1] in node:
            continue
        missing.append((path, default))
    return missing


def format_path(path):
    return ".".join(str(part) for part in path)


def apply_missing(user_config, missing):
    for path, default in missing:
        node = user_config
        for part in path[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = CommentedMap()
            node = node[part]
        node[path[-1]] = default


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-example", required=True, help="Path to the previous version's config.example.yaml")
    parser.add_argument("--new-example", required=True, help="Path to the new version's config.example.yaml")
    parser.add_argument("--config", required=True, help="Path to the user's config.yaml")
    parser.add_argument("--apply", action="store_true", help="Write the new keys into --config instead of just listing them")
    args = parser.parse_args()

    old_tree = load_plain(args.old_example)
    new_tree = load_plain(args.new_example)
    candidate_keys = find_new_keys(old_tree, new_tree)

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.indent(mapping=2, sequence=2, offset=0)
    with open(args.config) as f:
        user_config = yaml_rt.load(f) or CommentedMap()

    missing = missing_from_config(user_config, candidate_keys)

    if not missing:
        sys.exit(1)

    for path, default in missing:
        print(f"{format_path(path)}: {default!r}")

    if args.apply:
        apply_missing(user_config, missing)
        with open(args.config, "w") as f:
            yaml_rt.dump(user_config, f)

    sys.exit(0)


if __name__ == "__main__":
    main()
