"""Keep personal event details out of GitHub's workflow logs."""

import json
from pathlib import Path
import subprocess
import sys


def main():
    result = subprocess.run([sys.executable, "-m", "unified_schedule.sync", "--non-interactive"],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        output = result.stdout + result.stderr
        if "session has expired" in output or "Manual login" in output or "manual login" in output:
            message = "Session Workforce à renouveler sur votre PC, puis remplacez WORKFORCE_STATE_JSON."
        elif "Google Calendar API returned HTTP" in output:
            message = "Erreur Google Calendar : vérifiez les quotas et l'autorisation Google."
        else:
            message = "Actualisation échouée. Vérifiez les secrets et sessions ; lancez la commande locale pour un diagnostic détaillé."
        print(f"::error::{message}")
        return 1
    report = json.loads(Path("data/google-sync.json").read_text(encoding="utf-8"))
    print(f"Synchronisation terminée : {report['applied_counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
