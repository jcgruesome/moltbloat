#!/usr/bin/env python3
"""Caching-aware dollar cost of ecosystem token overhead.

Ecosystem overhead (CLAUDE.md, rules, skill listings, MCP tool defs) is
static within a session, so Anthropic's prompt cache holds it after turn 1.
Pricing every message at the full uncached rate, as token-budget used to,
overstates steady-state cost. Three tiers on one base per-1M rate: uncached
(no multiplier, the honest ceiling), turn 1 / cache write (~1.25x, paid once
per 5-min cache window), turn 2+ / cache read (~0.1x, paid on every later
turn reusing the cache). Pure API-level prompt-caching economics on input
tokens; unrelated to context-window auto-compaction.

Usage: python3 cache-cost.py --tokens N --rate R --write-mult M --read-mult M
                              [--messages-per-day N] [--session-messages N] [--json]
       python3 cache-cost.py --tokens N --model MODEL_ID [--write-mult M] [...]

--model reads the input rate and that model's own cache-read rate from
`costs.models` in moltbloat config (cache reads are not 0.1x on every
model: Opus 5.5 is 0.05x, Fable 5.1 0.025x). --write-mult defaults to
`costs.cache_write_multiplier`.
Output: markdown, or one JSON object with --json. Fails fast on total_tokens <= 0.
"""
import argparse
import importlib.util
import json
import os
import sys

DEFAULT_MESSAGES_PER_DAY = 200
DEFAULT_SESSION_MESSAGES = 10


def scan(total_tokens, rate_per_1m, cache_write_multiplier, cache_read_multiplier,
          messages_per_day=DEFAULT_MESSAGES_PER_DAY, session_messages=DEFAULT_SESSION_MESSAGES):
    """Compute uncached, turn-1, cached-turn, blended, daily, monthly cost.

    Returns a dict of dollar amounts, unrounded; callers format.
    """
    if total_tokens <= 0:
        raise ValueError("total_tokens must be positive")
    if rate_per_1m < 0 or cache_write_multiplier < 0 or cache_read_multiplier < 0:
        raise ValueError("rate and multipliers must be non-negative")
    if messages_per_day <= 0:
        raise ValueError("messages_per_day must be positive")
    if session_messages <= 0:
        raise ValueError("session_messages must be positive")

    base_cost = (total_tokens / 1_000_000) * rate_per_1m
    turn1_cost = base_cost * cache_write_multiplier
    cached_turn_cost = base_cost * cache_read_multiplier

    # First message in a session pays the cache write; later messages in the
    # same session reuse the cache and pay the read rate instead.
    session_blended_cost = (
        turn1_cost + max(session_messages - 1, 0) * cached_turn_cost
    ) / session_messages
    daily_cost = turn1_cost + max(messages_per_day - 1, 0) * cached_turn_cost

    return {
        "total_tokens": total_tokens,
        "rate_per_1m": rate_per_1m,
        "cache_write_multiplier": cache_write_multiplier,
        "cache_read_multiplier": cache_read_multiplier,
        "uncached_cost": base_cost,
        "turn1_cost": turn1_cost,
        "cached_turn_cost": cached_turn_cost,
        "session_messages": session_messages,
        "session_blended_cost": session_blended_cost,
        "messages_per_day": messages_per_day,
        "daily_cost": daily_cost,
        "monthly_cost": daily_cost * 30,
    }


def render_markdown(r):
    return "\n".join([
        "# Cache-Aware Cost", "",
        f"Ecosystem overhead: {r['total_tokens']:,} tokens at ${r['rate_per_1m']:.2f}/1M base rate.",
        "",
        "| Scenario | Cost |",
        "|---|---|",
        f"| Uncached (ceiling, caching off) | ${r['uncached_cost']:.4f} |",
        f"| Turn 1 of a session (cache write) | ${r['turn1_cost']:.4f} |",
        f"| Turn 2+ of a session (cache read) | ${r['cached_turn_cost']:.4f} |",
        f"| Blended average over a {r['session_messages']}-message session | ${r['session_blended_cost']:.4f} |",
        f"| Per day ({r['messages_per_day']} messages) | ${r['daily_cost']:.2f} |",
        f"| Per month | ${r['monthly_cost']:.2f} |",
    ])


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--tokens", type=int, required=True)
    p.add_argument("--model")
    p.add_argument("--rate", type=float)
    p.add_argument("--write-mult", type=float)
    p.add_argument("--read-mult", type=float)
    p.add_argument("--messages-per-day", type=int, default=DEFAULT_MESSAGES_PER_DAY)
    p.add_argument("--session-messages", type=int, default=DEFAULT_SESSION_MESSAGES)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv[1:])

    if args.model:
        spec = importlib.util.spec_from_file_location(
            "init_config", os.path.join(os.path.dirname(os.path.abspath(__file__)), "init-config.py"))
        ic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ic)
        config = ic.load_config()
        rates = ic.model_rates(args.model, config)
        if rates is None:
            sys.stderr.write(f"error: no rate for model {args.model} in costs.models\n")
            return 2
        if args.rate is not None or args.read_mult is not None:
            sys.stderr.write("error: --model sets the rate and read multiplier; do not pass --rate or --read-mult\n")
            return 2
        args.rate = rates[0]
        args.read_mult = rates[1] / rates[0]
        if args.write_mult is None:
            args.write_mult = config["costs"]["cache_write_multiplier"]
    missing = [n for n in ("rate", "write_mult", "read_mult") if getattr(args, n) is None]
    if missing:
        sys.stderr.write("error: pass --model, or all of --rate --write-mult --read-mult\n")
        return 2

    try:
        result = scan(
            args.tokens, args.rate, args.write_mult, args.read_mult,
            messages_per_day=args.messages_per_day, session_messages=args.session_messages,
        )
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1

    print(json.dumps(result, indent=2) if args.json else render_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
