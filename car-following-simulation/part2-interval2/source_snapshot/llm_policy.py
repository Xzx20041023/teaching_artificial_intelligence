"""Provider-neutral chat-completions interface. Offline rules are NOT an LLM."""
import json
import math
import os
import urllib.request
import urllib.parse
import urllib.error

SYSTEM_PROMPT = """You control longitudinal acceleration of one simulated vehicle.
Units: distance m, speed m/s, acceleration m/s^2, time s.
relative_speed = ego speed minus leader speed; positive means closing.
null gap/front_speed means no active leader. current_speed_limit is desired road speed.
Choose acceleration for decision_interval seconds. Aim for collision avoidance,
smooth following and progress toward desired speed. Output ONLY a JSON object:
{"acceleration": number}. Range: -8.0 to 1.5 m/s^2. Do not output prose."""

def parse_acceleration(raw):
    value = json.loads(raw)["acceleration"]
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("acceleration must be a JSON number")
    if not math.isfinite(value):
        raise ValueError("acceleration must be finite")
    return float(value)

class PolicyUnavailable(RuntimeError):
    """Contains only a safe diagnostic code, never credentials or server bodies."""

class OfflinePolicy:
    """Simple delayed car-following rule for plumbing experiments, NOT an LLM."""
    name = "offline-rule-NOT-LLM"

    def decide(self, observation):
        value = 0.5 * (observation["current_speed_limit"] - observation["speed"])
        if observation["gap"] is not None:
            target_gap = 2.0 + observation["speed"] * 1.2
            value = min(value, 0.15 * (observation["gap"] - target_gap)
                        - 0.7 * observation["relative_speed"])
        return json.dumps({"acceleration": max(-8.0, min(1.5, value))})

class FailurePolicy:
    name = "fault-injection-NOT-LLM"

    def decide(self, observation):
        raise TimeoutError("deliberately injected timeout")

class ChatPolicy:
    """OpenAI-compatible /chat/completions; no provider SDK required."""
    def __init__(self, timeout=20.0, max_calls=50):
        self.base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        self.model = os.environ.get("LLM_MODEL", "")
        self.key = os.environ.get("LLM_API_KEY", "")
        if not self.base or not self.model:
            raise ValueError("Set LLM_BASE_URL and LLM_MODEL before --policy api")
        parsed = urllib.parse.urlparse(self.base)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Base URL must not contain credentials/query/fragment")
        if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
            raise ValueError("Use HTTPS, or HTTP for a localhost model")
        if not math.isfinite(timeout) or timeout <= 0 or max_calls < 1:
            raise ValueError("timeout and max_calls must be positive")
        self.timeout, self.max_calls, self.calls = timeout, max_calls, 0
        self.name = "api:" + self.model

    def decide(self, observation):
        if self.calls >= self.max_calls:
            raise PolicyUnavailable("budget exhausted")
        self.calls += 1
        body = {"model": self.model, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(observation, allow_nan=False)}]}
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        req = urllib.request.Request(self.base + "/chat/completions",
            data=json.dumps(body).encode(), headers=headers)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(req, timeout=self.timeout) as response:
                result = json.load(response)
            return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            raise PolicyUnavailable(f"http_{exc.code}") from None
        except urllib.error.URLError:
            raise PolicyUnavailable("network_error") from None

class DecisionLog:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def write(self, record):
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
