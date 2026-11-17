"""Parser tests on a stored response: run with `pytest pipelines/` (no network)."""
from pathlib import Path

from sourcebound.contracts import Contract

import importlib.util

# loaded by path: several pipelines have a pipeline.py, so the bare name is ambiguous
_spec = importlib.util.spec_from_file_location(f"{Path(__file__).parent.name}_pipeline", Path(__file__).parent / "pipeline.py")
_pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pipeline)
parse = _pipeline.parse

HERE = Path(__file__).parent
CONTRACT = Contract.load(HERE.parents[1] / "contracts" / "market" / "ecb_fx_daily.yaml")


def test_parse_fixture_matches_contract():
    df = parse((HERE / "fixtures" / "exr_sample.csv").read_bytes(), "sha-test")
    assert CONTRACT.validate(df) == []
    assert set(df["currency"]) == {"USD", "GBP", "CHF"}
    assert df["rate"].min() > 0


def test_parse_drops_missing_observations():
    body = (HERE / "fixtures" / "exr_sample.csv").read_bytes()
    lines = body.decode().splitlines()
    head, first = lines[0], lines[1].split(",")
    first[7] = "NaN"
    df = parse(("\n".join([head, ",".join(first)]) + "\n").encode(), "x")
    assert df.height == 0
