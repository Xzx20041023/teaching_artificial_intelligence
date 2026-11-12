"""Offline contract, transport and simulation regression checks; no paid calls."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from config import Config
from llm_policy import ChatPolicy, FailurePolicy, OfflinePolicy, parse_acceleration
from part2_simulator import Part2Simulator
from vehicle_idm import IDMVehicle
from vehicle_llm import LLMVehicle

class ConstantPolicy:
    name = "test-only-NOT-LLM"
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0
    def decide(self, observation):
        self.calls += 1
        return self.reply

class PolicyTests(unittest.TestCase):
    def test_bad_json_values_are_rejected(self):
        for raw in ['{}', 'text', '{"acceleration": true}', '{"acceleration": "1"}',
                    '{"acceleration": NaN}', '{"acceleration": Infinity}', '[]']:
            with self.subTest(raw=raw), self.assertRaises((ValueError, KeyError, TypeError)):
                parse_acceleration(raw)

    def test_output_is_clipped_and_decisions_are_scheduled(self):
        policy = ConstantPolicy('{"acceleration": 100}')
        vehicle = LLMVehicle(Config(), 1, policy=policy, guarded=False)
        for step in range(20):
            vehicle.record_state(step * .1)
            vehicle.update_acceleration()
            vehicle.update_motion()
        self.assertEqual(policy.calls, 2)
        self.assertLessEqual(vehicle.acceleration, 1.5 + 1e-9)
        self.assertEqual(vehicle.stats["clipped_decisions"], 2)

    def test_invalid_reply_falls_back_to_fresh_idm(self):
        policy = ConstantPolicy('invalid')
        config = Config()
        vehicle = LLMVehicle(config, 1, policy=policy)
        baseline = IDMVehicle(config, 1)
        vehicle.speed = baseline.speed = 20
        baseline.update_acceleration()
        vehicle.update_acceleration()
        self.assertAlmostEqual(vehicle.acceleration, baseline.acceleration)
        self.assertEqual(vehicle.stats["failures"], 1)

    def test_guard_overrides_unsafe_held_action(self):
        config = Config()
        leader = IDMVehicle(config, 1)
        leader.position, leader.speed = 15, 0
        follower = LLMVehicle(config, 2, leader,
                              policy=ConstantPolicy('{"acceleration": 1.5}'))
        follower.speed = 20
        follower.update_acceleration()
        self.assertLess(follower.acceleration, 0)
        self.assertEqual(follower.stats["guard_steps"], 1)

    def test_http_contract_and_call_budget_without_network(self):
        environ = {"LLM_BASE_URL": "http://localhost:8000/v1", "LLM_MODEL": "test-model", "LLM_API_KEY": "test-placeholder"}
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": '{"acceleration": -1.0}'}}]}).encode()
        with patch.dict(os.environ, dict(environ, LLM_JSON_MODE="1")), patch("urllib.request.build_opener", return_value=opener):
            policy = ChatPolicy(timeout=3, max_calls=1)
            self.assertEqual(parse_acceleration(policy.decide({"speed": 20})), -1)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "http://localhost:8000/v1/chat/completions")
            self.assertEqual(json.loads(request.data)["model"], "test-model")
            self.assertEqual(json.loads(request.data)["response_format"], {"type": "json_object"})
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 3)
            with self.assertRaisesRegex(RuntimeError, "budget"):
                policy.decide({})
            self.assertIsNone(policy.last_response)
            self.assertEqual(opener.open.call_count, 1)

    def test_remote_plain_http_is_rejected(self):
        with patch.dict(os.environ, {"LLM_BASE_URL": "http://example.com/v1", "LLM_MODEL": "test"}):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                ChatPolicy()

    def test_network_failure_does_not_reuse_a_stale_action(self):
        class FailSecond(ConstantPolicy):
            def decide(self, observation):
                if self.calls:
                    raise TimeoutError()
                return super().decide(observation)
        vehicle = LLMVehicle(Config(), 1, policy=FailSecond('{"acceleration": 1.5}'), guarded=False)
        vehicle.update_acceleration()
        self.assertEqual(vehicle.held_acceleration, 1.5)
        vehicle.record_state(1.0)
        vehicle.update_acceleration()
        self.assertIsNone(vehicle.held_acceleration)
        self.assertEqual(vehicle.acceleration, 0.0)

    def test_matching_inputs_reproducibility_and_failure_fallback(self):
        def run(policy):
            sim = Part2Simulator(Config(seed=7, experiment=2, time_max=40),
                                 target_id=3, policy=policy)
            sim.run(verbose=False)
            return sim
        baseline, failed, repeat = run(None), run(FailurePolicy()), run(None)
        signature = lambda s: [(v.id, v.position, v.speed, len(v.history)) for v in s.vehicles]
        self.assertEqual(baseline.scenario_hash, failed.scenario_hash)
        self.assertEqual(signature(baseline), signature(repeat))
        self.assertEqual(signature(baseline), signature(failed))
        self.assertGreater(failed.vehicles[2].stats["failures"], 0)

if __name__ == "__main__":
    unittest.main()
