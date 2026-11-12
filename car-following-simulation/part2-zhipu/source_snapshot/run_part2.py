"""Reproducible Part II experiment runner (offline by default)."""
import argparse
import csv
import json
import math
import hashlib
import platform
import sys
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config import Config
from plotting import plot_time_space_diagram
from llm_policy import ChatPolicy, DecisionLog, FailurePolicy, OfflinePolicy, SYSTEM_PROMPT
from part2_simulator import Part2Simulator


def export_run(sim, directory, label):
    directory.mkdir(parents=True, exist_ok=True)
    target = next((v for v in sim.vehicles if v.id == sim.target_id), None)
    if target is None:
        raise ValueError("Target vehicle was not admitted; increase duration or reduce target-id")
    maps = {v.id: {round(r["t"], 8): r for r in v.history} for v in sim.vehicles}
    min_gap, overlap_pairs, overlaps = math.inf, set(), 0
    with (directory / "trajectories.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["vehicle_id", "t", "position", "speed", "acceleration", "gap"])
        writer.writeheader()
        for v in sim.vehicles:
            for r in v.history:
                leader = maps.get(v.vehicle_front.id, {}) if v.vehicle_front else {}
                front = leader.get(round(r["t"], 8))
                # A leader at the exit is removed from the road.
                gap = front["position"] - r["position"] - v.vehicle_length if front and front["position"] < sim.config.road_length else None
                if gap is not None:
                    min_gap = min(min_gap, gap)
                    if gap < -1e-9:
                        overlaps += 1
                        overlap_pairs.add((v.vehicle_front.id, v.id))
                writer.writerow(dict(vehicle_id=v.id, **r, gap=gap))
    history = target.history
    times = np.array([r["t"] for r in history])
    speeds = np.array([r["speed"] for r in history])
    accels = np.array([r["acceleration"] for r in history])
    leader = maps.get(target.vehicle_front.id, {}) if target.vehicle_front else {}
    gaps = [leader.get(round(r["t"], 8)) for r in history]
    gaps = np.array([g["position"] - r["position"] - target.vehicle_length
                     if g and g["position"] < sim.config.road_length else np.nan
                     for r, g in zip(history, gaps)])
    with (directory / "target.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["t", "position", "speed", "acceleration", "gap"])
        writer.writeheader()
        for record, gap in zip(history, gaps):
            writer.writerow(dict(record, gap=float(gap) if np.isfinite(gap) else None))
    fig, axs = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for ax, data, ylabel in zip(axs, [speeds, accels, gaps], ["Speed (m/s)", "Acceleration (m/s2)", "Gap (m)"]):
        ax.plot(times, data, linewidth=1)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=.25)
    axs[-1].set_xlabel("Simulation time (s)")
    fig.suptitle(f"{label} | vehicle {target.id}")
    fig.tight_layout()
    fig.savefig(directory / "target.png", dpi=140)
    plt.close(fig)
    fig, ax = plot_time_space_diagram(sim, sim.config, show=False)
    ax.set_title(label)
    fig.savefig(directory / "time-space.png", dpi=140, bbox_inches="tight")
    completed = [v for v in sim.vehicles if not v.active]
    result = {
        "label": label, "seed": sim.config.seed, "experiment": sim.config.experiment,
        "scenario_sha256": sim.scenario_hash, "time_max_s": sim.config.time_max,
        "time_step_s": sim.config.time_step, "decision_interval_s": sim.interval,
        "target_id": sim.target_id, "admitted": len(sim.vehicles),
        "completed": len(completed), "unfinished": len(sim.vehicles) - len(completed),
        "min_gap_m": min_gap if math.isfinite(min_gap) else None,
        "overlapping_pairs": len(overlap_pairs), "overlap_samples": overlaps,
        "mean_completed_travel_time_s": float(np.mean([v.history[-1]["t"] - v.history[0]["t"] for v in completed])) if completed else None,
        "target_completed": not target.active,
        "target_travel_or_observed_time_s": float(times[-1] - times[0]),
        "target_min_gap_m": float(np.nanmin(gaps)) if np.any(np.isfinite(gaps)) else None,
        "target_acceleration_rms_mps2": float(np.sqrt(np.mean(accels[1:] ** 2))),
        "target_jerk_rms_mps3": float(np.sqrt(np.mean((np.diff(accels[1:]) / sim.config.time_step) ** 2))) if len(accels) > 2 else None,
        "policy_stats": getattr(target, "stats", {}),
        "actual_api_requests": getattr(getattr(target, "policy", None), "calls", 0),
    }
    (directory / "metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    if hasattr(target, "events"):
        with (directory / "control.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["t", "requested", "applied", "fallback", "guarded", "gap"])
            writer.writeheader()
            writer.writerows(target.events)
    return result, times, speeds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=["offline", "failure", "api"], default="offline")
    parser.add_argument("--experiment", type=int, choices=[1, 2, 3, 4], default=1)
    parser.add_argument("--time-max", type=float, default=500)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--target-id", type=int, default=20)
    parser.add_argument("--decision-interval", type=float, default=1.0)
    parser.add_argument("--max-calls", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--min-request-interval", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "part2-results")
    parser.add_argument("--allow-api", action="store_true", help="Explicitly enable network calls; may incur provider charges")
    args = parser.parse_args()
    if args.target_id < 1 or not math.isfinite(args.time_max) or args.time_max <= 0:
        parser.error("target-id and finite time-max must be positive")
    if not math.isfinite(args.decision_interval) or args.decision_interval < 0.1:
        parser.error("decision-interval must be finite and >= 0.1 seconds")
    if args.policy == "api" and not args.allow_api:
        parser.error("API disabled: pass --allow-api only when ready to make real calls")
    # Validate configuration once, before running any simulations.
    if args.policy == "api":
        ChatPolicy(args.timeout, args.max_calls, args.min_request_interval)
    results = []
    args.output.mkdir(parents=True, exist_ok=True)
    source_dir = Path(__file__).parent
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in source_dir.glob("*.py")}
    snapshot = args.output / "source_snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    for filename in sources:
        (snapshot / filename).write_bytes((source_dir / filename).read_bytes())
    metadata = {"argv": sys.argv[1:], "python": platform.python_version(),
                "numpy": np.__version__, "matplotlib": matplotlib.__version__,
                "sources_sha256": sources,
                "evidence": "actual-model-api" if args.policy == "api" else "offline-NOT-LLM",
                "api_base_url": os.environ.get("LLM_BASE_URL") if args.policy == "api" else None,
                "api_model": os.environ.get("LLM_MODEL") if args.policy == "api" else None,
                "json_mode": os.environ.get("LLM_JSON_MODE", "0") == "1",
                "parameters": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}}
    (args.output / "run-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (args.output / "prompt.txt").write_text(SYSTEM_PROMPT, encoding="utf-8")
    modes = ["idm", "unguarded", "guarded"] if args.policy != "api" else ["idm", "guarded"]
    for seed in args.seeds:
        fig, ax = plt.subplots(figsize=(10, 4))
        for mode in modes:
            config = Config(seed=seed, experiment=args.experiment, time_max=args.time_max)
            directory = args.output / f"seed-{seed}" / mode
            logger = DecisionLog(directory / "decisions.jsonl")
            policy = None if mode == "idm" else {"offline": OfflinePolicy,
                "failure": FailurePolicy, "api": lambda: ChatPolicy(args.timeout, args.max_calls, args.min_request_interval)}[args.policy]()
            label = "IDM baseline" if mode == "idm" else f"{policy.name} | {mode}"
            sim = Part2Simulator(config, policy=policy, target_id=args.target_id,
                decision_interval=args.decision_interval, guarded=mode == "guarded", logger=logger)
            sim.run(verbose=False)
            result, times, speeds = export_run(sim, directory, label)
            results.append(result)
            ax.plot(times, speeds, label=label, linewidth=1)
            print(json.dumps(result, allow_nan=False))
        ax.set(xlabel="Simulation time (s)", ylabel="Target speed (m/s)", title=f"Matched scenario comparison | seed {seed}")
        ax.legend(fontsize=8)
        ax.grid(alpha=.25)
        fig.tight_layout()
        fig.savefig(args.output / f"comparison-seed-{seed}.png", dpi=150)
        plt.close(fig)
    (args.output / "summary.json").write_text(json.dumps(results, indent=2, allow_nan=False), encoding="utf-8")
    columns = ["seed", "label", "admitted", "completed", "unfinished", "min_gap_m", "overlapping_pairs", "target_min_gap_m", "target_acceleration_rms_mps2", "target_jerk_rms_mps3"]
    with (args.output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

if __name__ == "__main__":
    main()
