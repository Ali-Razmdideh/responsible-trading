import json
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture()
def u001_trades():
    data = json.loads((FIXTURES / "trades_small.json").read_text())
    return [t for t in data["trades"] if t["user_id"] == "u_001"]


@pytest.fixture()
def u002_trades():
    data = json.loads((FIXTURES / "trades_small.json").read_text())
    return [t for t in data["trades"] if t["user_id"] == "u_002"]


@pytest.fixture()
def calendar():
    return json.loads((FIXTURES / "calendar_small.json").read_text())


@pytest.fixture()
def all_trades():
    data = json.loads((FIXTURES / "trades_small.json").read_text())
    return data["trades"]
