"""Restore private configuration without putting secret values in shell code."""

import json
import os
from pathlib import Path
import sys


def main():
    for name in ("ADE_ICS_URL", "GOOGLE_CALENDAR_ID", "WORKFORCE_STATE_JSON", "GOOGLE_WRITE_TOKEN_JSON"):
        if not os.getenv(name, "").strip():
            print(f"::error::Secret GitHub manquant : {name}")
            return 1
    try:
        state = json.loads(os.environ["WORKFORCE_STATE_JSON"])
        token = json.loads(os.environ["GOOGLE_WRITE_TOKEN_JSON"])
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list) or not isinstance(state.get("origins"), list):
            raise ValueError()
        if not isinstance(token, dict) or not token.get("refresh_token"):
            raise ValueError()
        for path, document in ((Path("playwright/.auth/workforce.json"), state),
                               (Path("secrets/google-write-token.json"), token)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding="utf-8")
            path.chmod(0o600)
    except (ValueError, TypeError, OSError):
        print("::error::Configuration privée invalide ou impossible à écrire. Vérifiez les deux secrets JSON.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
