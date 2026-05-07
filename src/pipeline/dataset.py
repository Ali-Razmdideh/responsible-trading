from __future__ import annotations

import datetime
import random
import re
from typing import Any

MIN_USERS = 8
MIN_TRADES = 800
DEFAULT_SEED = 42

# Restrict user_id / trade_id / session_id to safe characters — these flow
# directly into filesystem paths (features/{user_id}.json etc.) and JSONL logs.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.match(value):
        raise ValueError(f"Invalid {field}: {value!r}")
    return value

INSTRUMENTS = [
    "Volatility 75 Index",
    "Volatility 25 Index",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "Crash 1000 Index",
    "Boom 500 Index",
]

# Persona definitions: (name, stake_start, double_on_loss, quick_revenge, news_trade)
PERSONAS = [
    ("martingale", 5.0, True, True, False),
    ("scalper", 10.0, False, True, False),
    ("news_chaser", 20.0, False, False, True),
    ("anti_martingale", 10.0, False, False, False),
    ("normal", 15.0, False, False, False),
]


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_session_id(user_idx: int, session_idx: int) -> str:
    return f"s_synth_{user_idx:03d}_{session_idx:03d}"


def _generate_user_trades(
    rng: random.Random,
    user_id: str,
    user_idx: int,
    persona: tuple[str, float, bool, bool, bool],
    n_trades: int,
    base_dt: datetime.datetime,
    high_impact_events: list[datetime.datetime],
) -> list[dict[str, Any]]:
    _name, stake_start, double_on_loss, quick_revenge, news_trade = persona
    trades: list[dict[str, Any]] = []
    trade_counter = 0
    session_idx = 0
    dt = base_dt + datetime.timedelta(hours=rng.randint(0, 4))
    stake = stake_start
    session_id = _make_session_id(user_idx, session_idx)
    session_trade_count = 0
    max_session_trades = rng.randint(10, 30)

    while len(trades) < n_trades:
        trade_counter += 1
        trade_id = f"t_synth_{user_id[2:]}_{trade_counter:04d}"

        if news_trade and high_impact_events:
            event_dt = rng.choice(high_impact_events)
            open_dt = event_dt + datetime.timedelta(seconds=rng.randint(-240, 240))
        else:
            interval = rng.randint(5, 120) if not quick_revenge else rng.randint(5, 25)
            open_dt = dt + datetime.timedelta(seconds=interval)

        duration = rng.randint(20, 90)
        close_dt = open_dt + datetime.timedelta(seconds=duration)

        result = "win" if rng.random() < 0.45 else "loss"
        payout = round(stake * 1.9, 2) if result == "win" else 0.0

        trades.append(
            {
                "user_id": user_id,
                "trade_id": trade_id,
                "open_ts": _iso(open_dt),
                "close_ts": _iso(close_dt),
                "instrument": rng.choice(INSTRUMENTS),
                "direction": rng.choice(["rise", "fall"]),
                "stake_usd": round(stake, 2),
                "payout_usd": payout,
                "result": result,
                "session_id": session_id,
            }
        )

        dt = close_dt

        if double_on_loss and result == "loss":
            stake = min(stake * 2, 500.0)
        elif result == "win":
            stake = stake_start
        else:
            stake = max(stake_start, stake * 0.9)

        session_trade_count += 1
        if session_trade_count >= max_session_trades:
            session_idx += 1
            session_id = _make_session_id(user_idx, session_idx)
            session_trade_count = 0
            max_session_trades = rng.randint(10, 30)
            dt += datetime.timedelta(hours=rng.randint(1, 6))

    return trades


def extend_to_minimum(
    existing_trades: list[dict[str, Any]],
    economic_calendar: list[dict[str, Any]],
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """
    Extend trades to meet MIN_USERS and MIN_TRADES.

    Preserves all existing trades verbatim. Uses a fixed seed so repeated
    calls on the same input produce identical output.
    """
    rng = random.Random(seed)

    existing_users = sorted({t["user_id"] for t in existing_trades})
    n_existing_users = len(existing_users)
    n_synth_users_needed = max(0, MIN_USERS - n_existing_users)

    high_impact_events = [
        datetime.datetime.fromisoformat(e["datetime_utc"].replace("Z", "+00:00"))
        for e in economic_calendar
        if e.get("impact") == "high"
    ]

    # Determine date range from existing trades
    if existing_trades:
        dates = [
            datetime.datetime.fromisoformat(t["open_ts"].replace("Z", "+00:00"))
            for t in existing_trades
        ]
        base_dt = min(dates).replace(tzinfo=None)
    else:
        base_dt = datetime.datetime(2025, 8, 1, 8, 0, 0)

    high_impact_naive = [e.replace(tzinfo=None) for e in high_impact_events]

    synthetic: list[dict[str, Any]] = []
    for i in range(n_synth_users_needed):
        user_id = f"u_synth_{i + 1:03d}"
        persona = PERSONAS[i % len(PERSONAS)]
        user_base_dt = base_dt + datetime.timedelta(days=rng.randint(0, 5))
        user_trades = _generate_user_trades(
            rng,
            user_id=user_id,
            user_idx=i,
            persona=persona,
            n_trades=rng.randint(80, 120),
            base_dt=user_base_dt,
            high_impact_events=high_impact_naive,
        )
        synthetic.extend(user_trades)

    all_trades = existing_trades + synthetic

    # If still below MIN_TRADES, pad the last synthetic user
    while len(all_trades) < MIN_TRADES:
        last_user_id = f"u_synth_{n_synth_users_needed:03d}"
        persona = PERSONAS[n_synth_users_needed % len(PERSONAS)]
        extra = _generate_user_trades(
            rng,
            user_id=last_user_id,
            user_idx=n_synth_users_needed,
            persona=persona,
            n_trades=MIN_TRADES - len(all_trades) + 10,
            base_dt=base_dt + datetime.timedelta(days=10),
            high_impact_events=high_impact_naive,
        )
        all_trades.extend(extra)

    return all_trades


def validate_and_extend(
    raw_trades: dict[str, Any],
    economic_calendar: list[dict[str, Any]],
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """
    Validate schema, extend if needed, and return the full trade list.
    """
    trades: list[dict[str, Any]] = raw_trades.get("trades", [])
    for t in trades:
        for field in (
            "user_id",
            "trade_id",
            "open_ts",
            "close_ts",
            "instrument",
            "direction",
            "stake_usd",
            "payout_usd",
            "result",
            "session_id",
        ):
            if field not in t:
                raise ValueError(f"Trade missing field '{field}': {t}")
        _safe_id(t["user_id"], "user_id")
        _safe_id(t["trade_id"], "trade_id")
        _safe_id(t["session_id"], "session_id")

    n_users = len({t["user_id"] for t in trades})
    n_trades = len(trades)

    if n_users < MIN_USERS or n_trades < MIN_TRADES:
        trades = extend_to_minimum(trades, economic_calendar, seed=seed)

    return trades
