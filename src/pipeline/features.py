from __future__ import annotations

import datetime


def _parse_ts(ts: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _seconds_between(a: str, b: str) -> float:
    return (_parse_ts(b) - _parse_ts(a)).total_seconds()


def compute_features(
    trades: list[dict[str, object]],
    calendar: list[dict[str, object]],
) -> dict[str, object]:
    """Pure, deterministic feature computation. Sorts trades by open_ts internally."""
    trades = sorted(trades, key=lambda t: str(t["open_ts"]))
    n = len(trades)
    if n == 0:
        return _empty_features()

    high_impact_ts = [
        _parse_ts(str(e["datetime_utc"])) for e in calendar if e.get("impact") == "high"
    ]

    stakes = [float(t["stake_usd"]) for t in trades]  # type: ignore[arg-type]
    payouts = [float(t["payout_usd"]) for t in trades]  # type: ignore[arg-type]
    results = [str(t["result"]) for t in trades]

    sum_stake = round(sum(stakes), 6)
    sum_payout = round(sum(payouts), 6)
    average_stake = round(sum_stake / n, 6)
    total_net_pnl = round(sum_payout - sum_stake, 6)

    n_wins = results.count("win")
    n_losses = results.count("loss")
    win_rate = round(n_wins / n, 6)

    min_open = _parse_ts(str(trades[0]["open_ts"]))
    max_close = _parse_ts(str(trades[-1]["close_ts"]))
    span_seconds = round(max((max_close - min_open).total_seconds(), 1.0), 3)

    post_loss_ratios: list[float] = []
    for i in range(1, n):
        if results[i - 1] == "loss" and stakes[i - 1] > 0:
            post_loss_ratios.append(stakes[i] / stakes[i - 1])

    n_post_loss_pairs = len(post_loss_ratios)
    sum_ratios = round(sum(post_loss_ratios), 6) if post_loss_ratios else 0.0
    stake_escalation_ratio = (
        round(sum_ratios / n_post_loss_pairs, 6) if n_post_loss_pairs else 0.0
    )

    n_news_adjacent = 0
    for t in trades:
        open_dt = _parse_ts(str(t["open_ts"]))
        for news_dt in high_impact_ts:
            if abs((open_dt - news_dt).total_seconds()) <= 300:
                n_news_adjacent += 1
                break
    pct_news_adjacent = round(n_news_adjacent / n, 6)

    revenge_intervals: list[float] = []
    for i in range(1, n):
        if results[i - 1] == "loss":
            gap = _seconds_between(
                str(trades[i - 1]["close_ts"]), str(trades[i]["open_ts"])
            )
            revenge_intervals.append(gap)
    n_revenge_pairs = len(revenge_intervals)
    revenge_interval_avg = (
        round(sum(revenge_intervals) / n_revenge_pairs, 6) if n_revenge_pairs else 0.0
    )

    longest_streak = 0
    current_streak = 0
    for r in results:
        if r == "loss":
            current_streak += 1
            longest_streak = max(longest_streak, current_streak)
        else:
            current_streak = 0

    sessions: dict[str, list[dict[str, object]]] = {}
    for t in trades:
        sid = str(t["session_id"])
        sessions.setdefault(sid, []).append(t)

    session_durations: list[float] = []
    for session_trades in sessions.values():
        open_times = [_parse_ts(str(t["open_ts"])) for t in session_trades]
        close_times = [_parse_ts(str(t["close_ts"])) for t in session_trades]
        dur = (max(close_times) - min(open_times)).total_seconds()
        session_durations.append(round(dur, 6))

    avg_session_duration = round(sum(session_durations) / len(session_durations), 6)

    # "Active" time excludes long inter-session gaps so trades_per_minute
    # reflects intensity within trading sessions, not wall-clock span.
    active_seconds = round(max(sum(session_durations), 1.0), 3)
    trades_per_minute = round(n / (active_seconds / 60.0), 6)

    return {
        "total_trades": n,
        "average_stake": average_stake,
        "stake_escalation_ratio_after_losses": stake_escalation_ratio,
        "trades_per_minute": trades_per_minute,
        "pct_trades_within_5min_of_high_impact_news": pct_news_adjacent,
        "win_rate": win_rate,
        "revenge_interval_seconds_avg": revenge_interval_avg,
        "longest_losing_streak": longest_streak,
        "total_net_pnl_usd": total_net_pnl,
        "average_session_duration_seconds": avg_session_duration,
        # flat audit fields
        "n_wins": n_wins,
        "n_losses": n_losses,
        "sum_stake_usd": sum_stake,
        "sum_payout_usd": sum_payout,
        "active_seconds": active_seconds,
        "span_seconds": span_seconds,
        "n_post_loss_pairs": n_post_loss_pairs,
        "sum_escalation_ratios": sum_ratios,
        "n_news_adjacent": n_news_adjacent,
        "n_high_impact_events": len(high_impact_ts),
        "n_loss_to_next_pairs": n_revenge_pairs,
        "n_sessions": len(sessions),
        "session_durations": session_durations,
    }


def _empty_features() -> dict[str, object]:
    return {
        "total_trades": 0,
        "average_stake": 0.0,
        "stake_escalation_ratio_after_losses": 0.0,
        "trades_per_minute": 0.0,
        "pct_trades_within_5min_of_high_impact_news": 0.0,
        "win_rate": 0.0,
        "revenge_interval_seconds_avg": 0.0,
        "longest_losing_streak": 0,
        "total_net_pnl_usd": 0.0,
        "average_session_duration_seconds": 0.0,
        "n_wins": 0,
        "n_losses": 0,
        "sum_stake_usd": 0.0,
        "sum_payout_usd": 0.0,
        "active_seconds": 0.0,
        "span_seconds": 0.0,
        "n_post_loss_pairs": 0,
        "sum_escalation_ratios": 0.0,
        "n_news_adjacent": 0,
        "n_high_impact_events": 0,
        "n_loss_to_next_pairs": 0,
        "n_sessions": 0,
        "session_durations": [],
    }
