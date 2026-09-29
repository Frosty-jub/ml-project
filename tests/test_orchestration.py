"""Failure paths must fail tasks and restore aliases, never silently promote."""
import unittest
from unittest.mock import Mock, patch
from src.demand_forecasting import orchestration as flow


class OrchestrationTests(unittest.TestCase):
    def test_failed_gate_raises(self):
        with self.assertRaises(ValueError):
            flow.require_pass({"passed": False})

    def test_release_restores_aliases_when_promotion_fails(self):
        client = Mock()
        before = {"production": "2", "champion": "2", "previous": "1"}
        with patch.object(flow, "load_state", return_value={"version": "3", "aliases_before": before}), \
             patch.object(flow, "context", return_value=(client, "forecast")), \
             patch.object(flow.registry, "alias_version", return_value=before), \
             patch.object(flow.registry, "promote", side_effect=ValueError("gate failed")), \
             patch.object(flow, "save_state") as save:
            with self.assertRaisesRegex(ValueError, "gate failed"):
                flow.release()
        client.set_registered_model_alias.assert_any_call("forecast", "production", "2")
        self.assertFalse(save.call_args.args[0]["released"])

    def test_concurrent_alias_change_blocks_promotion(self):
        with patch.object(flow, "load_state", return_value={"version": "3", "aliases_before": {}}), \
             patch.object(flow, "context", return_value=(Mock(), "forecast")), \
             patch.object(flow.registry, "alias_version", return_value={"production": "4"}), \
             patch.object(flow.registry, "promote") as promote:
            with self.assertRaisesRegex(ValueError, "Aliases changed"):
                flow.release()
            promote.assert_not_called()

    def test_first_release_cleanup_removes_new_aliases(self):
        client = Mock()
        with patch.object(flow.registry, "alias_version", return_value={"production": "1", "champion": "1"}):
            flow.restore_aliases(client, "forecast", {})
        client.delete_registered_model_alias.assert_any_call("forecast", "production")
        client.delete_registered_model_alias.assert_any_call("forecast", "champion")

    def test_candidate_serving_gate_failure_raises(self):
        from contextlib import nullcontext
        with patch.object(flow, "temporary_server", return_value=nullcontext("http://candidate")), \
             patch.object(flow.registry, "benchmark_version", return_value={"gate": {"passed": False}}):
            with self.assertRaises(ValueError):
                flow.benchmark("3")

    def test_live_benchmark_failure_restores_previous_production(self):
        import io
        client = Mock()
        before = {"production": "2", "champion": "2"}
        with patch.object(flow, "load_state", return_value={"version": "3", "aliases_before": before}), \
             patch.object(flow, "context", return_value=(client, "forecast")), \
             patch.object(flow.registry, "alias_version", side_effect=[before, {"production": "3", "champion": "3", "previous": "2"}]), \
             patch.object(flow.registry, "promote"), \
             patch.object(flow.urllib.request, "urlopen", return_value=io.BytesIO(b'{"version":"3"}')), \
             patch.object(flow.registry, "benchmark_version", return_value={"gate": {"passed": False}}), \
             patch.object(flow, "save_state") as save:
            with self.assertRaises(ValueError):
                flow.release()
        client.set_registered_model_alias.assert_any_call("forecast", "production", "2")
        client.delete_registered_model_alias.assert_called_once_with("forecast", "previous")
        self.assertFalse(save.call_args.args[0]["released"])

    def test_live_benchmark_success_records_release(self):
        import io
        client = Mock()
        with patch.object(flow, "load_state", return_value={"version": "3", "aliases_before": {}}), \
             patch.object(flow, "context", return_value=(client, "forecast")), \
             patch.object(flow.registry, "alias_version", return_value={}), \
             patch.object(flow.registry, "promote"), \
             patch.object(flow.urllib.request, "urlopen", return_value=io.BytesIO(b'{"version":"3"}')), \
             patch.object(flow.registry, "benchmark_version", return_value={"gate": {"passed": True}}), \
             patch.object(flow, "save_state") as save:
            flow.release()
        self.assertTrue(save.call_args.args[0]["released"])
        client.set_registered_model_alias.assert_not_called()
