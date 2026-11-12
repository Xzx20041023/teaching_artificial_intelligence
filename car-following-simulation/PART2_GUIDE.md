# Part II: longitudinal control exploration

This extension connects an optional language-model policy to the supplied
single-lane car-following simulation. Only vehicle 20 is controlled by the
experimental policy; all other vehicles use IDM. The upstream simulation loop,
road, bottleneck and kinematics are retained.

**Evidence includes offline suites and a separately recorded real Zhipu pilot.**
The offline rule is a deterministic controller used to validate the integration;
its performance is not evidence about any language model. The HTTP transport is
tested with an in-memory response; the separate Zhipu pilot also exercises the
real service. See `PART2_ZHIPU_RESULTS.md` for model evidence and its limits.

## Setup (Windows PowerShell, Python 3.11+)

Run from the repository root. Only the simulation dependencies are needed:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r car-following-simulation/requirements.txt
$env:MPLCONFIGDIR = "$PWD/car-following-simulation/.mplconfig"
```

No CNN/RNN training, PyTorch installation, model download or API key is needed.

## Reproduce the original baseline

```powershell
python car-following-simulation/main.py --experiment 1 --time-max 500 --output car-following-simulation/results/idm-original.png --no-show
```

`--no-show` now chooses the Agg backend before loading pyplot, allowing headless
execution without Tcl/Tk. Interactive mode retains the normal backend.

## Run matched offline comparisons

```powershell
python car-following-simulation/run_part2.py --policy offline --seeds 1 2 3
python car-following-simulation/run_part2.py --policy failure --seeds 1 --output car-following-simulation/part2-failure
```

The offline suite compares IDM, a rule queried once per simulation second, and
the same rule plus a per-step IDM guard. The fault-injection run intentionally
raises a timeout at every decision and should reproduce the IDM baseline through
fresh fallback actions. Local computation latency is NOT LLM latency.

Useful variations (write each to a new output directory):

```powershell
python car-following-simulation/run_part2.py --experiment 2 --seeds 1 2 3 --output car-following-simulation/part2-random
python car-following-simulation/run_part2.py --decision-interval 2 --seeds 1 2 3 --output car-following-simulation/part2-interval2
```

## Real-model run

The adapter expects an OpenAI-compatible chat-completions service. This can be a
local server or a provider. Set the URL to the API prefix, including `/v1` where
your service requires it. Do not include `/chat/completions` in the base URL.

```powershell
$env:LLM_BASE_URL = 'http://localhost:8000/v1'
$env:LLM_MODEL = 'your-served-model-name'
# For a provider requiring authentication, set LLM_API_KEY locally.
python car-following-simulation/run_part2.py --policy api --allow-api --max-calls 50 --timeout 20 --seeds 1 --output car-following-simulation/part2-live
```

This command makes real network requests only when `--allow-api` is present.
No paid calls are enabled by default. Keys are read from environment variables
and are not written to result files. Public services require HTTPS. Redirects
are disabled to avoid sending credentials to a different host. There are no
automatic retries. The call cap applies per experimental run (one guarded run
per seed); after it is exhausted, the vehicle falls back to IDM. A capped run
must be reported as a mixed controller with its actual failure/fallback rate.
The separate Zhipu pilot tests one real service. Other providers remain unverified.

The simulation blocks while a request completes. Simulation-time scheduling is
not real-time execution; record wall-clock latency separately. A 20 s timeout
cannot establish feasibility for a 1 s real-time control deadline.

## Design and logs

- `llm_policy.py`: prompt, strict finite numeric JSON parsing, offline/fault
  providers, bounded HTTP adapter, JSONL decision log.
- `vehicle_llm.py`: decision scheduling, held actions, clipping, fresh IDM
  fallback and optional guard checked at each 0.1 s step.
- `part2_simulator.py`: precomputed arrivals and bottleneck traits; independent
  noise generator per vehicle. A SHA-256 fingerprint verifies matched inputs.
- `run_part2.py`: trajectories, control trace, metrics and figures.

At a decision, input includes speed, front speed, bumper gap, closing speed,
position, road desired speed and holding interval. A successful response supplies
one acceleration in m/s2. The numerical bound is [-8, 1.5]. An invalid response,
network error, timeout or exhausted budget selects a fresh IDM action every step
until a valid decision arrives. Replies and decision-start actions are logged in
`decisions.jsonl`; the actual held/guarded action at EVERY step is in `control.csv`.

The guard restricts an action to be no greater than IDM when gap < 2 + 1.5v or
closing TTC < 4 s. It is a heuristic, not a proof of collision avoidance. Physical
clipping alone also does not guarantee safety. No position correction hides
overlaps: count them and inspect trajectories. Stop interpreting an overlapping
run as a physically valid traffic trajectory.

Scheduled demand and per-vehicle traits match between controllers. Actual
admission can differ when the entrance is blocked, which is an outcome, not a
different demand schedule. The original baseline uses its original RNG; the
matched suite uses separate RNGs and should not be treated as numerically
identical to the original main.py baseline.

## Reading the metrics

- `min_gap_m`: minimum sampled bumper gap across all active leader/follower pairs.
- `overlapping_pairs`: distinct original leader/follower pairs with gap < 0.
  `overlap_samples` counts samples, not separate crashes. The model has no crash
  response, so subsequent outcomes after overlap need caution.
- `completed` and `unfinished`: exits and admitted vehicles still on the road.
  Mean travel time includes completed vehicles only and can have selection bias.
- Target speed/gap/acceleration plots and acceleration/jerk RMS: compare behavior
  and smoothness under consistent units and sampling. Jerk excludes initialization.
- `guard_steps`, `fallback_steps`, decision failures and latencies: disclose how
  much of the trajectory was supplied by the experimental policy vs. IDM.

The conventional guard shares IDM with the baseline, so guard improvements cannot
be credited to the experimental policy. A single controlled vehicle cannot
establish network-wide benefits, and three seeds are exploratory evidence only.

## Tests

```powershell
Push-Location car-following-simulation
python -m unittest -v test_simulation.py test_part2.py
Pop-Location
```

These check upstream invariants, malformed/nonfinite replies, scheduling,
clipping, fallback equivalence, guard behavior, HTTP payload and budget using a
mock transport, and reproducibility. No external model is contacted.

Verify stored summaries, input fingerprints, target traces, decision counts and
execution-source snapshots (line-ending differences are accepted):

```powershell
python car-following-simulation/verify_part2_artifacts.py
```

## Submission boundary

Use `PART2_REPORT.md` as a technical draft, verify its results against the JSON/CSV
and add your own observations. The assignment explicitly reserves personal
reflection and conclusions for the student: those sections are left unwritten.
Do not present the offline rule or mock-transport test as a working LLM result.

## Reproduce the Zhipu pilot

Zhipu's [official model documentation](https://docs.bigmodel.cn/cn/guide/models/free/glm-4-flash-250414)
lists `glm-4-flash-250414` as free. Check current conditions before rerunning.
Set `LLM_API_KEY` locally to a standard-model API key; do not commit it.

```powershell
$env:LLM_BASE_URL = 'https://open.bigmodel.cn/api/paas/v4'
$env:LLM_MODEL = 'glm-4-flash-250414'
$env:LLM_JSON_MODE = '1'
python car-following-simulation/run_part2.py --policy api --allow-api --max-calls 180 --timeout 30 --min-request-interval 1 --decision-interval 2 --seeds 1 --output car-following-simulation/part2-zhipu
```

Prompt-only output included Markdown code fences and failed strict parsing.
JSON mode resolves the observed format problem. Decision metadata preserves the
response ID, actual model, finish reason and token usage. The minimum request
interval affects wall-clock pacing, not simulation time. Coding-plan API keys
and endpoints differ from standard-model access; see the official API guide.
