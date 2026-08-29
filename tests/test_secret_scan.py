import importlib.util
from pathlib import Path


def test_repo_has_no_secrets_or_personal_data():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("check_secrets", root / "scripts" / "check_secrets.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    problems = module.scan(root)
    assert problems == [], "\n".join(problems)
