"""Keep personal event details out of GitHub's workflow logs."""

import json
import re
from pathlib import Path
import subprocess
import sys


def safe_failure_context(output):
    """Use fixed stage names and source-code literals, never raw child output."""
    import ast

    stages = {
        "1/5": "ADE", "2/5": "Workforce", "3/5": "SQLite",
        "4/5": "Conflits", "5/5": "Google Calendar",
    }
    reached = re.findall(r"^([1-5]/5)\b", output, re.MULTILINE)
    stage = stages[reached[-1]] if reached else "Démarrage"
    # Only complete, literal exception messages from our own code are safe to
    # publish. Formatted strings can contain event names, IDs, or credentials.
    messages = set()
    root = Path(__file__).resolve().parents[1] / "src" / "unified_schedule"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            if node.exc.args and isinstance(node.exc.args[0], ast.Constant):
                value = node.exc.args[0].value
                if isinstance(value, str) and f"Error: {value}" in output:
                    messages.add(value)
    return f"Étape : {stage}. " + " ".join(sorted(messages))


def main():
    result = subprocess.run([sys.executable, "-m", "unified_schedule.sync", "--non-interactive"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        output = result.stdout + result.stderr
        if "Existing ID is cancelled or moved" in output:
            message = "Un identifiant appartient à un événement déplacé/annulé. Vérifiez GOOGLE_ADE_CALENDAR_ID (EILCO) et GOOGLE_WORKFORCE_CALENDAR_ID (Domino's) dans Repository secrets ; n'utilisez pas l'ancien agenda."
        elif "Existing ID cannot be safely matched" in output:
            message = "L'événement existant ne peut pas être reconnu avec certitude. Aucun doublon créé ; vérification manuelle nécessaire."
        elif any(marker in output for marker in (
            "session has expired", "Manual login", "manual login", "No usable session.",
            "Login needs verification or corrected credentials.",
            "Workforce requires a fresh login",
        )):
            message = "Session Workforce à renouveler sur votre PC, puis remplacez WORKFORCE_STATE_JSON."
        elif "Google authorization or token refresh failed" in output:
            message = "Autorisation Google expirée ou renouvellement impossible. Lancez authorize --write --login sur votre PC, puis remplacez GOOGLE_WRITE_TOKEN_JSON."
        elif "ADE download timed out" in output or "ADE download failed" in output:
            message = "Téléchargement ADE impossible (connexion ou délai dépassé). Réessayez ; si l'erreur persiste, vérifiez ADE_ICS_URL."
        elif "ADE returned HTTP" in output:
            match = re.search(r"ADE returned HTTP (\d{3}); expected 200\.", output)
            status = match.group(1) if match else "inconnu"
            message = f"Erreur ADE HTTP {status}. Vérifiez la disponibilité du service et ADE_ICS_URL."
        elif "ADE did not return an ICS calendar" in output:
            message = "ADE a renvoyé une page au lieu du calendrier ICS. Vérifiez ADE_ICS_URL et l'accès à l'export."
        elif "Configured calendar ID is not in your accessible calendar list." in output:
            message = "Un agenda configuré est inaccessible. Vérifiez les identifiants GOOGLE_*_CALENDAR_ID et le compte Google autorisé."
        elif "browser or schedule request failed" in output:
            message = "Impossible de lire Workforce. Vérifiez la connexion, la session et l'installation Chromium."
        elif "Google Calendar API returned HTTP" in output:
            match = re.search(r"Google Calendar API returned HTTP (\d{3}) \(([A-Za-z]+)\)\.", output)
            reasons = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded",
                       "forbidden", "forbiddenForNonOrganizer", "insufficientPermissions",
                       "accessNotConfigured", "duplicate", "backendError", "unknown"}
            reason = match.group(2) if match and match.group(2) in reasons else "unknown"
            status = match.group(1) if match else "inconnu"
            message = f"Erreur Google Calendar HTTP {status} ({reason}). "
            if reason in {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded"}:
                message += "Limite Google atteinte : attendez avant de relancer."
            elif status == "404":
                message += "Vérifiez les deux identifiants d'agenda dans GitHub Secrets et le compte Google autorisé."
            elif status == "409":
                message += "Identifiant déjà présent : ne supprimez rien ; une vérification des marqueurs est nécessaire."
            elif status == "401" or reason == "insufficientPermissions":
                message += "Renouvelez l'autorisation d'écriture et remplacez GOOGLE_WRITE_TOKEN_JSON."
            else:
                message += "Vérifiez les permissions Google et l'accès aux agendas."
        else:
            message = "Actualisation échouée. Vérifiez les secrets et sessions ; lancez la commande locale pour un diagnostic détaillé."
        context = safe_failure_context(output)
        print(f"::error::{message} {context}")
        return 1
    report = json.loads(Path("data/google-sync.json").read_text(encoding="utf-8"))
    print(f"Synchronisation terminée : {report['applied_counts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
