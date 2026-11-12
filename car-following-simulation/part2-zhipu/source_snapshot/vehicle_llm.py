"""Scheduled policy decisions, fresh IDM fallback and optional per-step guard."""
import time
from vehicle_idm import IDMVehicle
from llm_policy import PolicyUnavailable, parse_acceleration

class LLMVehicle(IDMVehicle):
    def __init__(self, config, vehicle_id, vehicle_front=None, *, policy=None,
                 decision_interval=1.0, guarded=True, logger=None):
        super().__init__(config, vehicle_id, vehicle_front)
        if policy is None or decision_interval < self.time_step:
            raise ValueError("Provide a policy and interval >= time_step")
        self.policy, self.interval, self.guarded = policy, decision_interval, guarded
        self.logger = logger
        self.sim_time, self.next_decision = 0.0, 0.0
        self.held_acceleration = None
        self.stats = dict(decisions=0, failures=0, fallback_steps=0,
                          guard_steps=0, clipped_decisions=0, latency_s=0.0)
        self.events = []

    def record_state(self, current_time):
        self.sim_time = current_time
        super().record_state(current_time)

    def get_observation(self):
        leader = self.vehicle_front
        valid = leader is not None and leader.active
        return {
            "vehicle_id": self.id, "time": self.sim_time,
            "position": self.position, "speed": self.speed,
            "acceleration": self.acceleration,
            "current_speed_limit": self.current_speed_limit,
            "gap": leader.position - self.position - self.vehicle_length if valid else None,
            "relative_speed": self.speed - leader.speed if valid else None,
            "front_speed": leader.speed if valid else None,
            "decision_interval": self.interval,
        }

    def update_acceleration(self):
        observation = self.get_observation()
        super().update_acceleration()
        idm_acceleration = self.acceleration
        decision = None
        if self.sim_time + 1e-9 >= self.next_decision:
            self.next_decision = self.sim_time + self.interval
            self.stats["decisions"] += 1
            start = time.perf_counter()
            decision = {"observation": observation, "provider": self.policy.name,
                        "raw_reply": None, "requested_acceleration": None, "error": None}
            try:
                raw = self.policy.decide(observation)
                decision["raw_reply"] = raw
                requested = parse_acceleration(raw)
                self.held_acceleration = max(-self.maximum_deceleration,
                    min(self.maximum_acceleration, requested))
                decision["requested_acceleration"] = requested
                self.stats["clipped_decisions"] += requested != self.held_acceleration
            except Exception as exc:
                self.held_acceleration = None
                self.stats["failures"] += 1
                decision["error"] = type(exc).__name__
                if isinstance(exc, PolicyUnavailable):
                    decision["error_code"] = str(exc)
            decision["latency_s"] = time.perf_counter() - start
            decision["response_metadata"] = getattr(self.policy, "last_response", None)
            self.stats["latency_s"] += decision["latency_s"]

        fallback = self.held_acceleration is None
        acceleration = idm_acceleration if fallback else self.held_acceleration
        guarded = False
        gap = observation["gap"]
        if self.guarded and gap is not None:
            closing = max(0.0, observation["relative_speed"])
            if gap < 2.0 + 1.5 * self.speed or (closing > 0 and gap / closing < 4.0):
                safe_action = min(acceleration, idm_acceleration)
                guarded = safe_action < acceleration - 1e-9
                acceleration = safe_action
        self.acceleration = acceleration
        self.stats["fallback_steps"] += fallback
        self.stats["guard_steps"] += guarded
        self.events.append({"t": self.sim_time, "requested": self.held_acceleration,
                            "applied": acceleration, "fallback": fallback,
                            "guarded": guarded, "gap": gap})
        if decision is not None and self.logger:
            decision.update(held_acceleration=self.held_acceleration,
                applied_acceleration=acceleration, fallback=fallback, guarded=guarded)
            self.logger.write(decision)
