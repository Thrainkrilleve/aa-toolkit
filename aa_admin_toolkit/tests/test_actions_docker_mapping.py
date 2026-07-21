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


class _FakeGroupsFilterResult:
    def exists(self):
        return False


class _FakeGroups:
    def filter(self, **_kwargs):
        return _FakeGroupsFilterResult()


class _FakeUser:
    def __init__(self, *, username="admin", is_authenticated=True, is_superuser=False, character_id=None, character_name=None):
        self.username = username
        self.is_authenticated = is_authenticated
        self.is_superuser = is_superuser
        self.groups = _FakeGroups()
        self.character_ownerships = types.SimpleNamespace(
            select_related=lambda *_args, **_kwargs: types.SimpleNamespace(
                all=lambda: [
                    types.SimpleNamespace(
                        character=types.SimpleNamespace(
                            character_id=character_id,
                            character_name=character_name,
                        )
                    )
                ] if character_id is not None or character_name is not None else []
            )
        )
        self.profile = types.SimpleNamespace(
            main_character=types.SimpleNamespace(character_id=character_id, character_name=character_name)
            if character_id is not None or character_name is not None
            else None
        )

    def has_perm(self, _permission):
        return False


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

    @patch("aa_admin_toolkit.actions.compose_project_directory", return_value="/tmp")
    @patch("aa_admin_toolkit.actions.compose_base_command", return_value=["docker", "compose"])
    @patch("aa_admin_toolkit.actions.allowed_docker_services", return_value=["web"])
    @patch("aa_admin_toolkit.actions.docker_enabled", return_value=False)
    def test_snapshot_still_collects_when_actions_are_disabled(self, _docker_enabled, _allowed_services, _compose_cmd, _compose_dir):
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
                "Name": "myproj-web-1",
                "CPUPerc": "2.5%",
                "MemPerc": "4.0%",
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
        self.assertEqual(snapshot[0]["cpu"], "2.5%")
        self.assertEqual(snapshot[0]["memory"], "4.0%")

    @patch("aa_admin_toolkit.actions.setting", side_effect=lambda name, default: ["requirements.txt"] if name == "AA_ADMIN_TOOLKIT_ALLOWED_EDITABLE_FILES" else default)
    def test_allowed_editor_files_always_includes_local_py(self, _setting):
        files = actions.allowed_editor_files()

        self.assertIn("requirements.txt", files)
        self.assertIn("local.py", files)

    @patch("aa_admin_toolkit.actions.allow_view_non_superusers", return_value=False)
    def test_superuser_has_no_implicit_view_access(self, _allow_view_non_superusers):
        user = _FakeUser(is_superuser=True)

        self.assertFalse(actions.user_can_view(user))

    @patch("aa_admin_toolkit.actions.allow_execute_non_superusers", return_value=False)
    def test_superuser_has_no_implicit_execute_access(self, _allow_execute_non_superusers):
        user = _FakeUser(is_superuser=True)

        self.assertFalse(actions.user_can_execute(user))

    @patch("aa_admin_toolkit.actions.allow_view_non_superusers", return_value=False)
    @patch("aa_admin_toolkit.actions.allowed_view_eve_character_names", return_value={"Pilot Example"})
    @patch("aa_admin_toolkit.actions.allowed_view_eve_character_ids", return_value=set())
    @patch("aa_admin_toolkit.actions.allowed_view_groups", return_value=set())
    @patch("aa_admin_toolkit.actions.allowed_view_permissions", return_value=set())
    @patch("aa_admin_toolkit.actions.allowed_view_users", return_value=set())
    def test_eve_character_allowlist_grants_view_access_without_toggle(
        self,
        _allowed_view_users,
        _allowed_view_permissions,
        _allowed_view_groups,
        _allowed_view_eve_ids,
        _allowed_view_eve_names,
        _allow_view_non_superusers,
    ):
        user = _FakeUser(username="pilot", character_name="Pilot Example")

        self.assertTrue(actions.user_can_view(user))


if __name__ == "__main__":
    unittest.main()
