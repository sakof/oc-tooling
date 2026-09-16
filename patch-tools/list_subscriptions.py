#!/usr/bin/env python3
"""
list_subscriptions.py

Extrait, pour chaque Subscription OLM (operators.coreos.com/v1alpha1) présente
sur un cluster OpenShift, les informations suivantes :
    - Namespace
    - Nom de l'opérateur (nom de la Subscription)
    - Package (spec.name, le nom réel du package OLM)
    - Channel (avec gestion du cas où il n'est pas défini)
    - Mode de validation d'upgrade (spec.installPlanApproval : Automatic/Manual)
    - Version de l'opérateur installé (extraite de status.installedCSV)

Prérequis :
    - La CLI `oc` doit être installée et disponible dans le PATH.
    - L'utilisateur doit être connecté au cluster (oc login ...) avec les
      droits de lecture sur les Subscriptions (au minimum sur les namespaces
      concernés, idéalement cluster-admin ou un rôle avec accès cluster-wide).

Utilisation :
    python3 list_subscriptions.py                     # affiche un tableau dans le terminal
    python3 list_subscriptions.py --namespace openshift-operators
    python3 list_subscriptions.py --csv subscriptions.csv
    python3 list_subscriptions.py --json subscriptions.json
"""

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from typing import List, Optional


CHANNEL_NON_DEFINI = "Non défini"
VERSION_NON_DISPONIBLE = "Non disponible"


@dataclass
class SubscriptionInfo:
    namespace: str
    operateur: str          # nom de la ressource Subscription
    package: str             # spec.name (nom réel du package OLM)
    channel: str
    mode_approbation: str    # Automatic / Manual
    version_installee: str
    installed_csv: str       # nom complet du CSV installé (référence brute)


def verifier_oc_disponible() -> None:
    """Vérifie que la CLI oc est présente dans le PATH."""
    if shutil.which("oc") is None:
        print(
            "Erreur : la commande 'oc' est introuvable dans le PATH. "
            "Installez la CLI OpenShift et assurez-vous d'être connecté au cluster.",
            file=sys.stderr,
        )
        sys.exit(1)


def recuperer_subscriptions(namespace: Optional[str] = None) -> dict:
    """
    Récupère les Subscriptions via `oc get subscriptions -o json`.
    Si namespace est None, récupère sur tous les namespaces (-A).
    """
    cmd = ["oc", "get", "subscriptions.operators.coreos.com", "-o", "json"]
    if namespace:
        cmd.extend(["-n", namespace])
    else:
        cmd.append("-A")

    try:
        resultat = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=60
        )
    except subprocess.CalledProcessError as e:
        print(f"Erreur lors de l'appel à 'oc' :\n{e.stderr}", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("Erreur : délai d'attente dépassé lors de l'appel à 'oc'.", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(resultat.stdout)
    except json.JSONDecodeError:
        print("Erreur : impossible de parser la sortie JSON de 'oc'.", file=sys.stderr)
        sys.exit(1)


def extraire_version(installed_csv: str) -> str:
    """
    Extrait la version depuis un nom de CSV installé, du type :
        'amq-streams-cluster-operator.v2.5.0' -> '2.5.0'
    Si le format ne correspond pas, retourne le CSV brut ou une valeur par défaut.
    """
    if not installed_csv:
        return VERSION_NON_DISPONIBLE

    # Cherche le dernier segment commençant par 'v' suivi de chiffres/points
    match = re.search(r"\.v(\d[\w.\-+]*)$", installed_csv)
    if match:
        return match.group(1)

    return installed_csv  # fallback : on retourne le nom complet si le pattern ne matche pas


def parser_subscription(item: dict) -> SubscriptionInfo:
    """Transforme un objet Subscription (dict JSON) en SubscriptionInfo."""
    metadata = item.get("metadata", {})
    spec = item.get("spec", {})
    status = item.get("status", {})

    namespace = metadata.get("namespace", "")
    operateur = metadata.get("name", "")
    package = spec.get("name", "")

    # Gestion du cas où le channel n'est pas défini dans la Subscription
    channel = spec.get("channel") or CHANNEL_NON_DEFINI

    # Mode de validation d'upgrade : Automatic ou Manual (Automatic par défaut si absent)
    mode_approbation = spec.get("installPlanApproval") or "Automatic (défaut)"

    installed_csv = status.get("installedCSV", "")
    version_installee = extraire_version(installed_csv)

    return SubscriptionInfo(
        namespace=namespace,
        operateur=operateur,
        package=package,
        channel=channel,
        mode_approbation=mode_approbation,
        version_installee=version_installee,
        installed_csv=installed_csv or VERSION_NON_DISPONIBLE,
    )


def afficher_tableau(subscriptions: List[SubscriptionInfo]) -> None:
    """Affiche les résultats sous forme de tableau texte aligné dans le terminal."""
    if not subscriptions:
        print("Aucune subscription trouvée.")
        return

    en_tetes = ["NAMESPACE", "OPERATEUR", "PACKAGE", "CHANNEL", "MODE APPROBATION", "VERSION INSTALLEE"]
    lignes = [
        [
            s.namespace,
            s.operateur,
            s.package,
            s.channel,
            s.mode_approbation,
            s.version_installee,
        ]
        for s in subscriptions
    ]

    largeurs = [
        max(len(str(en_tetes[i])), max((len(str(l[i])) for l in lignes), default=0))
        for i in range(len(en_tetes))
    ]

    def formater_ligne(colonnes):
        return "  ".join(str(c).ljust(largeurs[i]) for i, c in enumerate(colonnes))

    print(formater_ligne(en_tetes))
    print("  ".join("-" * l for l in largeurs))
    for ligne in lignes:
        print(formater_ligne(ligne))

    print(f"\nTotal : {len(subscriptions)} subscription(s)")


def exporter_csv(subscriptions: List[SubscriptionInfo], chemin: str) -> None:
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["Namespace", "Operateur", "Package", "Channel", "Mode approbation", "Version installee", "CSV installe"]
        )
        for s in subscriptions:
            writer.writerow(
                [s.namespace, s.operateur, s.package, s.channel, s.mode_approbation, s.version_installee, s.installed_csv]
            )
    print(f"Export CSV généré : {chemin}")


def exporter_json(subscriptions: List[SubscriptionInfo], chemin: str) -> None:
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump([asdict(s) for s in subscriptions], f, ensure_ascii=False, indent=2)
    print(f"Export JSON généré : {chemin}")


def main():
    parser = argparse.ArgumentParser(
        description="Extrait les informations des Subscriptions OLM sur un cluster OpenShift."
    )
    parser.add_argument(
        "-n", "--namespace",
        help="Limiter la recherche à un namespace précis (par défaut : tous les namespaces).",
        default=None,
    )
    parser.add_argument("--csv", help="Chemin du fichier CSV à générer (optionnel).", default=None)
    parser.add_argument("--json", help="Chemin du fichier JSON à générer (optionnel).", default=None)
    args = parser.parse_args()

    verifier_oc_disponible()
    data = recuperer_subscriptions(args.namespace)

    items = data.get("items", [])
    subscriptions = [parser_subscription(item) for item in items]

    # Tri par namespace puis par nom d'opérateur pour une lecture plus claire
    subscriptions.sort(key=lambda s: (s.namespace, s.operateur))

    afficher_tableau(subscriptions)

    if args.csv:
        exporter_csv(subscriptions, args.csv)
    if args.json:
        exporter_json(subscriptions, args.json)


if __name__ == "__main__":
    main()
