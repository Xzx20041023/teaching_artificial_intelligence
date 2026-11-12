"""Matched exogenous inputs; reuse the upstream five-stage simulation loop."""
import hashlib
import json
import random
from simulator import Simulator
from vehicle_idm import IDMVehicle
from vehicle_llm import LLMVehicle

class Part2Simulator(Simulator):
    def __init__(self, config, *, policy=None, target_id=20,
                 decision_interval=1.0, guarded=True, logger=None):
        super().__init__(config)
        self.policy, self.target_id = policy, target_id
        self.interval, self.guarded, self.logger = decision_interval, guarded, logger
        rng = random.Random(config.seed)
        self.schedule = []
        t = 0.0
        while t < config.time_max:
            self.schedule.append(t)
            t += config.vehicle_min_interval
            if config.vehicle_extra_interval > 0:
                t += rng.expovariate(1.0 / config.vehicle_extra_interval)
        self.traits = [random.Random(config.seed * 1000003 + i).random()
                       < config.bottleneck_influence_rate
                       for i in range(1, len(self.schedule) + 1)]
        self.scenario_hash = hashlib.sha256(json.dumps([self.schedule, self.traits]).encode()).hexdigest()

    def _generate_vehicle(self, current_time):
        index = len(self.vehicles)
        if index >= len(self.schedule) or current_time + 1e-12 < self.schedule[index]:
            return
        active = [v for v in self.vehicles if v.active]
        leader = active[-1] if active else None
        c = self.config
        if leader is not None:
            entry_gap = c.vehicle_length + c.idm_minimum_spacing + c.initial_speed * c.idm_time_headway
            if leader.position < entry_gap:
                return
        vehicle_id = index + 1
        if self.policy is not None and vehicle_id == self.target_id:
            vehicle = LLMVehicle(c, vehicle_id, leader, policy=self.policy,
                decision_interval=self.interval, guarded=self.guarded, logger=self.logger)
        else:
            vehicle = IDMVehicle(c, vehicle_id, leader)
        vehicle.influenced_by_bottleneck = self.traits[index]
        vehicle.rng = random.Random(c.seed * 1000033 + vehicle_id)
        vehicle.record_state(current_time)
        self.vehicles.append(vehicle)
