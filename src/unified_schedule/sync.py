"""Refresh both sources, import them, report conflicts, and synchronize Google."""

import argparse
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def run_step(label, module, arguments):
    print(f"\n{label}", flush=True)
    result = subprocess.run([sys.executable, "-m", module, *arguments], check=False)
    if result.returncode:
        print(f"Arrêt : {label}. Les étapes suivantes n'ont pas été exécutées.", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Actualiser ADE et Workforce puis synchroniser Google Calendar.")
    parser.add_argument("--weeks", type=int, default=4, help="Nombre maximal de semaines Workforce (défaut : 4).")
    parser.add_argument("--non-interactive", action="store_true", help="Ne pas demander de connexion manuelle Workforce.")
    parser.add_argument("--preview", action="store_true", help="Prévisualiser Google sans modifier ses événements.")
    args = parser.parse_args()
    if args.weeks < 1:
        parser.error("--weeks doit être positif")
    data = Path("data")
    data.mkdir(parents=True, exist_ok=True)
    try:
        # Both new exports must succeed before importing. Never fall back to an
        # old export if the other source fails to refresh.
        with TemporaryDirectory(prefix="sync-", dir=data) as directory:
            ade = Path(directory) / "ade.json"
            workforce = Path(directory) / "workforce.json"
            workforce_args = ["--weeks", str(args.weeks), "--output", str(workforce)]
            if args.non_interactive:
                workforce_args.append("--non-interactive")
            steps = [
                ("1/5 — Récupération ADE", "unified_schedule", ["--output", str(ade)]),
                ("2/5 — Récupération Workforce", "unified_schedule.workforce", workforce_args),
                ("3/5 — Import SQLite", "unified_schedule.calendar", ["import", "--ade", str(ade), "--workforce", str(workforce)]),
            ]
            for step in steps:
                if not run_step(*step):
                    return 1
            ade.replace(data / "ade.json")
            ade.with_suffix(".ics").replace(data / "ade.ics")
            workforce.replace(data / "workforce.json")
        if not run_step("4/5 — Détection des conflits", "unified_schedule.calendar",
                        ["conflicts", "--output", str(data / "conflicts.json")]):
            return 1
        google_command = "preview" if args.preview else "sync"
        if not run_step("5/5 — Google Calendar", "unified_schedule.google_calendar", [google_command]):
            return 1
        print("\nActualisation terminée." + (" Google n'a pas été modifié." if args.preview else ""))
        return 0
    except OSError:
        print("Erreur : impossible d'exécuter une commande ou d'enregistrer les exports locaux.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Actualisation interrompue. Certaines étapes peuvent déjà être terminées.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
