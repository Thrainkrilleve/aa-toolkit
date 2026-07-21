import json
import importlib
import importlib.util
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

for module_name in [
    "aa_admin_toolkit.actions",
    "celery",
    "django",
    "django.conf",
    "django.core",
    "django.core.management",
]:
    sys.modules.pop(module_name, None)

# Provide lightweight stubs so this unit test can run without full Django/Celery deps.
if "celery" not in sys.modules:
    celery_module = types.ModuleType("celery")
    celery_module.current_app = types.SimpleNamespace(send_task=lambda *_args, **_kwargs: None)
    sys.modules["celery"] = celery_module

if "django" not in sys.modules:
    django_module = types.ModuleType("django")
    conf_module = types.ModuleType("django.conf")
    conf_module.settings = types.SimpleNamespace(BASE_DIR=".")
    core_module = types.ModuleType("django.core")
    mgmt_module = types.ModuleType("django.core.management")
    mgmt_module.call_command = lambda *args, **kwargs: None
    core_module.management = mgmt_module
    django_module.conf = conf_module
    django_module.core = core_module
    sys.modules["django"] = django_module
    sys.modules["django.conf"] = conf_module
    sys.modules["django.core"] = core_module
    sys.modules["django.core.management"] = mgmt_module

module_path = Path(__file__).resolve().parents[1] / "actions.py"
spec = importlib.util.spec_from_file_location("aa_admin_toolkit.actions", module_path)
assert spec is not None and spec.loader is not None
actions = importlib.util.module_from_spec(spec)
sys.modules["aa_admin_toolkit.actions"] = actions
spec.loader.exec_module(actions)


class DockerServiceSnapshotMappingTests(unittest.TestCase):
    def _cp(self, argv: list[str], stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=argv, returncode=returncode, stdout=stdout, stderr="")

    @patch("aa_admin_toolkit.actions.compose_project_directory", return_value="/tmp")
    @patch("aa_admin_toolkit.actions.compose_base_command", return_value=["docker", "compose"])
    @patch("aa_admin_toolkit.actions.allowed_docker_services", return_value=["web"])
    @patch("aa_admin_toolkit.actions.docker_enabled", return_value=True)
    def test_snapshot_matches_stats_by_container_id(self, _docker_enabled, _allowed_services, _compose_cmd, _compose_dir):
        ps_payload = json.dumps([
            {
                "Service": "web",
                "State": "running",
                "Health": "healthy",
                "ID": "abcdef1234567890",
                "Name": "myproj-web-1",
            }
        ])
        stats_payload = json.dumps(
            {
                "ID": "abcdef123456",
                "Name": "renamed_container",
                "CPUPerc": "1.2%",
                "MemPerc": "3.4%",
            }
        )

        with patch("aa_admin_toolkit.actions._run_subprocess") as run_subprocess:
            run_subprocess.side_effect = [
                self._cp(["docker", "compose", "ps", "--format", "json"], ps_payload),
                self._cp(["docker", "compose", "stats", "--no-stream", "--format", "json"], stats_payload),
            ]
            snapshot = actions.docker_service_snapshot()

        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["service"], "web")
        self.assertEqual(snapshot[0]["cpu"], "1.2%")
        self.assertEqual(snapshot[0]["memory"], "3.4%")

    @patch("aa_admin_toolkit.actions.compose_project_directory", return_value="/tmp")
    @patch("aa_admin_toolkit.actions.compose_base_command", return_value=["docker", "compose"])
    @patch("aa_admin_toolkit.actions.allowed_docker_services", return_value=["web"])
    @patch("aa_admin_toolkit.actions.docker_enabled", return_value=True)
    def test_snapshot_falls_back_to_container_name_match(self, _docker_enabled, _allowed_services, _compose_cmd, _compose_dir):
        ps_payload = json.dumps([
            {
                "Service": "web",
                "State": "running",
                "Health": "healthy",
                "ID": "",
                "Name": "myproj-web-1",
            }
        ])
        stats_payload = json.dumps(
            {
                "Name": "myproj-web-1",
                "CPUPerc": "5.0%",
                "MemPerc": "10.0%",
            }
        )

        with patch("aa_admin_toolkit.actions._run_subprocess") as run_subprocess:
            run_subprocess.side_effect = [
                self._cp(["docker", "compose", "ps", "--format", "json"], ps_payload),
                self._cp(["docker", "compose", "stats", "--no-stream", "--format", "json"], stats_payload),
            ]
            snapshot = actions.docker_service_snapshot()

        self.assertEqual(snapshot[0]["cpu"], "5.0%")
        self.assertEqual(snapshot[0]["memory"], "10.0%")

    @patch("aa_admin_toolkit.actions.compose_project_directory", return_value="/tmp")
    @patch("aa_admin_toolkit.actions.compose_base_command", return_value=["docker", "compose"])
    @patch("aa_admin_toolkit.actions.allowed_docker_services", return_value=["web"])
    @patch("aa_admin_toolkit.actions.docker_enabled", return_value=True)
    def test_snapshot_falls_back_to_service_match(self, _docker_enabled, _allowed_services, _compose_cmd, _compose_dir):
        ps_payload = json.dumps([
            {
                "Service": "web",
                "State": "running",
                "Health": "healthy",
                "ID": "",
                "Name": "myproj-web-1",
            }
        ])
        stats_payload = json.dumps(
            {
                "Service": "web",
                "Name": "other-name",
                "CPUPerc": "8.5%",
                "MemPerc": "18.0%",
            }
        )

        with patch("aa_admin_toolkit.actions._run_subprocess") as run_subprocess:
            run_subprocess.side_effect = [
                self._cp(["docker", "compose", "ps", "--format", "json"], ps_payload),
                self._cp(["docker", "compose", "stats", "--no-stream", "--format", "json"], stats_payload),
            ]
            snapshot = actions.docker_service_snapshot()

        self.assertEqual(snapshot[0]["cpu"], "8.5%")
        self.assertEqual(snapshot[0]["memory"], "18.0%")

    @patch("aa_admin_toolkit.actions.compose_project_directory", return_value="/tmp")
    @patch("aa_admin_toolkit.actions.compose_base_command", return_value=["docker", "compose"])
    @patch("aa_admin_toolkit.actions.allowed_docker_services", return_value=["web"])
    @patch("aa_admin_toolkit.actions.docker_enabled", return_value=True)
    def test_snapshot_keeps_service_with_missing_stats(self, _docker_enabled, _allowed_services, _compose_cmd, _compose_dir):
        ps_payload = json.dumps([
            {
                "Service": "web",
                "State": "running",
                "Health": "healthy",
                "ID": "abcdef1234567890",
                "Name": "myproj-web-1",
            }
        ])

        with patch("aa_admin_toolkit.actions._run_subprocess") as run_subprocess:
            run_subprocess.side_effect = [
                self._cp(["docker", "compose", "ps", "--format", "json"], ps_payload),
                self._cp(["docker", "compose", "stats", "--no-stream", "--format", "json"], ""),
            ]
            snapshot = actions.docker_service_snapshot()

        self.assertEqual(snapshot[0]["cpu"], "-")
        self.assertEqual(snapshot[0]["memory"], "-")


if __name__ == "__main__":
    unittest.main()
