"""Paths for the separate Squirrel checkout and its Traveler installation."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAVELER_ROOT = Path(os.environ.get(
    "SQUIRRELS_TRAVELER_ROOT", str(REPO_ROOT.parent / "Traveler")
)).expanduser().resolve()
OUTPUT_ROOT = Path(os.environ.get(
    "SQUIRRELS_OUTPUT_ROOT", str(REPO_ROOT / "runtime")
)).expanduser().resolve()
ENGINE_ROOT = TRAVELER_ROOT / "_tools" / "rpgcobo-tool"


def validate_traveler():
    required = (
        ENGINE_ROOT / "rpgcobo.exe",
        ENGINE_ROOT / "project" / "data" / "setting.json",
        ENGINE_ROOT / "project" / "plugin" / "rokugan" / "RokuganChase.sk",
        ENGINE_ROOT / "project" / "plugin" / "rokugan" / "RokuganMarkerData.sk",
        ENGINE_ROOT / "project" / "plugin" / "rokugan" / "RokuganJournalData.sk",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(
            "Traveler installation is incomplete. Set SQUIRRELS_TRAVELER_ROOT to a compatible "
            "Traveler checkout. Missing:\n" + "\n".join(missing)
        )
