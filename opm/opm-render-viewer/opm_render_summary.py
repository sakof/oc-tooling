#!/usr/bin/env python3
"""
opm_render_summary.py

Lit la sortie JSON d'un `opm render <image-or-index>` (format FBC, un objet
JSON par ligne - JSONL - ou un tableau JSON classique) et affiche une synthèse
par package : canaux disponibles, et pour chaque canal la liste des versions
d'opérateur présentes, avec la tête de canal (head) mise en évidence.

Usage:
    opm render registry.local/redhat/redhat-operator-index:v4.16 > catalog.json
    python3 opm_render_summary.py catalog.json

    # ou directement en pipe :
    opm render registry.local/redhat/redhat-operator-index:v4.16 | python3 opm_render_summary.py

Options:
    --package NAME   Filtrer sur un seul package (ex: --package amq-streams)
    --json           Sortie au format JSON au lieu du texte formaté
"""

import sys
import json
import argparse
import re
from collections import defaultdict


def load_objects(fp):
    """Charge les objets FBC, que la sortie soit un tableau JSON ou du JSONL."""
    content = fp.read()
    content = content.strip()
    if not content:
        return []

    # Tentative 1 : un unique tableau JSON
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError:
        pass

    # Tentative 2 : JSON Lines (un objet JSON par ligne, format natif d'opm render)
    objects = []
    decoder = json.JSONDecoder()
    idx = 0
    length = len(content)
    while idx < length:
        # sauter les espaces/retours à la ligne
        while idx < length and content[idx] in " \t\r\n":
            idx += 1
        if idx >= length:
            break
        obj, end = decoder.raw_decode(content, idx)
        objects.append(obj)
        idx = end
    return objects


def extract_version(bundle):
    """Extrait la version d'un bundle : d'abord via les properties olm.package,
    sinon en repliant sur le nom du CSV (ex: mon-operateur.v1.2.3 -> 1.2.3)."""
    for prop in bundle.get("properties", []) or []:
        if prop.get("type") == "olm.package":
            value = prop.get("value", {})
            if "version" in value:
                return value["version"]

    name = bundle.get("name", "")
    match = re.search(r"\.v(\d+\.\d+\.\d+(?:[-+][\w.]+)?)$", name)
    if match:
        return match.group(1)
    return None


def build_catalog(objects):
    packages = defaultdict(lambda: {
        "defaultChannel": None,
        "channels": defaultdict(list),  # channel_name -> [entry_name, ...]
    })
    bundle_versions = {}  # bundle_name -> version

    for obj in objects:
        schema = obj.get("schema")

        if schema == "olm.package":
            pkg = obj.get("name")
            packages[pkg]["defaultChannel"] = obj.get("defaultChannel")

        elif schema == "olm.channel":
            pkg = obj.get("package")
            channel_name = obj.get("name")
            entries = obj.get("entries", []) or []
            for entry in entries:
                packages[pkg]["channels"][channel_name].append({
                    "name": entry.get("name"),
                    "replaces": entry.get("replaces"),
                    "skipRange": entry.get("skipRange"),
                })

        elif schema == "olm.bundle":
            pkg = obj.get("package")
            name = obj.get("name")
            version = extract_version(obj)
            bundle_versions[name] = version
            # s'assurer que le package existe même sans olm.package séparé
            _ = packages[pkg]

    return packages, bundle_versions


def find_channel_head(entries):
    """La tête de canal est l'entrée qui n'est référencée par aucun 'replaces'
    d'une autre entrée du même canal."""
    replaced = {e["replaces"] for e in entries if e.get("replaces")}
    heads = [e["name"] for e in entries if e["name"] not in replaced]
    return heads[0] if len(heads) == 1 else (heads[0] if heads else None)


def print_text_summary(packages, bundle_versions, only_package=None):
    for pkg_name in sorted(packages):
        if only_package and pkg_name != only_package:
            continue
        pkg = packages[pkg_name]
        print(f"\n=== Package: {pkg_name} ===")
        if pkg["defaultChannel"]:
            print(f"  Canal par défaut : {pkg['defaultChannel']}")

        if not pkg["channels"]:
            print("  (aucun canal trouvé)")
            continue

        for channel_name in sorted(pkg["channels"]):
            entries = pkg["channels"][channel_name]
            head = find_channel_head(entries)
            is_default = " (default)" if channel_name == pkg["defaultChannel"] else ""
            print(f"  - Canal: {channel_name}{is_default}")

            # trier les versions si possible pour un affichage lisible
            def sort_key(e):
                v = bundle_versions.get(e["name"])
                return v or e["name"]

            for entry in sorted(entries, key=sort_key):
                version = bundle_versions.get(entry["name"], "?")
                head_marker = "  <- head" if entry["name"] == head else ""
                print(f"      {entry['name']} (v{version}){head_marker}")


def print_json_summary(packages, bundle_versions, only_package=None):
    output = {}
    for pkg_name, pkg in packages.items():
        if only_package and pkg_name != only_package:
            continue
        output[pkg_name] = {
            "defaultChannel": pkg["defaultChannel"],
            "channels": {}
        }
        for channel_name, entries in pkg["channels"].items():
            head = find_channel_head(entries)
            output[pkg_name]["channels"][channel_name] = {
                "head": head,
                "versions": [
                    {
                        "name": e["name"],
                        "version": bundle_versions.get(e["name"]),
                        "replaces": e.get("replaces"),
                        "skipRange": e.get("skipRange"),
                    }
                    for e in entries
                ]
            }
    print(json.dumps(output, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", type=argparse.FileType("r"), default=sys.stdin,
                         help="Fichier JSON issu de 'opm render' (par défaut: stdin)")
    parser.add_argument("--package", help="Filtrer sur un seul package")
    parser.add_argument("--json", action="store_true", help="Sortie au format JSON")
    args = parser.parse_args()

    objects = load_objects(args.file)
    if not objects:
        print("Aucun objet FBC trouvé dans l'entrée fournie.", file=sys.stderr)
        sys.exit(1)

    packages, bundle_versions = build_catalog(objects)

    if args.json:
        print_json_summary(packages, bundle_versions, only_package=args.package)
    else:
        print_text_summary(packages, bundle_versions, only_package=args.package)


if __name__ == "__main__":
    main()
