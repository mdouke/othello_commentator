from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
LOG_DIR = ROOT_DIR / "logs"
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
SUMMARY_DIR = ARTIFACTS_DIR / "summary"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
