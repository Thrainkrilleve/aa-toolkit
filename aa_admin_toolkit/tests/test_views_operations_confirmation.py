import importlib
import sys
import types
import unittest


class _FakeMessagesModule(types.ModuleType):
    def error(self, request, message):
        request._messages.append(("error", str(message)))

    def success(self, request, message):
        request._messages.append(("success", str(message)))


class _FakePostData(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def getlist(self, key):
        value = super().get(key, [])
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [value]


class _FakeRequest:
    def __init__(self, post_data):
        self.method = "POST"
        self.POST = _FakePostData(post_data)
        self.path = "/admin-toolkit/operations/"
        self.user = types.SimpleNamespace(is_authenticated=True, is_superuser=False)
        self._messages = []


class _FakeCommandLogRecord:
    def __init__(self, log_id=1, **kwargs):
        self.id = log_id
        self.command_name = kwargs.get("command_name", "")
        self.action_type = kwargs.get("action_type", "")
        self.target = kwargs.get("target", "")
        self.executed_by = kwargs.get("executed_by")
        self.status = kwargs.get("status", "")
        self.exit_code = kwargs.get("exit_code")
        self.started_at = kwargs.get("started_at")
        self.finished_at = kwargs.get("finished_at")
        self.output = kwargs.get("output", "")
        self.normalized_command = kwargs.get("normalized_command", "")

    def save(self):
        return None


class _FakeCommandLogManager:
    def __init__(self):
        self.created = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return _FakeCommandLogRecord(log_id=len(self.created), **kwargs)


class _FakeTask:
    def __init__(self):
        self.calls = []

    def delay(self, *args):
        self.calls.append(args)


class OperationsConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake_messages = _FakeMessagesModule("django.contrib.messages")
        cls.fake_log_manager = _FakeCommandLogManager()
        cls.fake_task = _FakeTask()
        real_actions_module = sys.modules.get("aa_admin_toolkit.actions")

        # Minimal django stubs required by aa_admin_toolkit.views imports.
        django_module = types.ModuleType("django")
        shortcuts_module = types.ModuleType("django.shortcuts")
        shortcuts_module.redirect = lambda target: {"redirect": target}
        shortcuts_module.render = lambda request, template, context: {"template": template, "context": context}
        shortcuts_module.get_object_or_404 = lambda model, **kwargs: types.SimpleNamespace(id=kwargs.get("id", 1))

        auth_decorators_module = types.ModuleType("django.contrib.auth.decorators")
        auth_decorators_module.user_passes_test = lambda _check: (lambda fn: fn)

        auth_models_module = types.ModuleType("django.contrib.auth.models")
        auth_models_module.User = type("User", (), {"objects": types.SimpleNamespace(count=lambda: 0)})

        utils_module = types.ModuleType("django.utils")
        timezone_module = types.ModuleType("django.utils.timezone")
        timezone_module.now = lambda: None
        utils_module.timezone = timezone_module

        http_module = types.ModuleType("django.http")
        http_module.JsonResponse = lambda data: data

        db_module = types.ModuleType("django.db")
        db_module.connection = types.SimpleNamespace()

        contrib_module = types.ModuleType("django.contrib")
        contrib_module.messages = cls.fake_messages
        auth_module = types.ModuleType("django.contrib.auth")
        auth_module.decorators = auth_decorators_module
        auth_module.models = auth_models_module

        django_module.shortcuts = shortcuts_module
        django_module.contrib = contrib_module
        django_module.utils = utils_module
        django_module.http = http_module
        django_module.db = db_module

        # App module stubs used by views.
        models_module = types.ModuleType("aa_admin_toolkit.models")
        models_module.CommandLog = type("CommandLog", (), {"objects": cls.fake_log_manager})

        tasks_module = types.ModuleType("aa_admin_toolkit.tasks")
        tasks_module.run_action_task = cls.fake_task

        actions_module = types.ModuleType("aa_admin_toolkit.actions")
        supported = {
            "docker_full_restart",
            "pip_install",
            "pip_upgrade",
            "pip_uninstall",
            "docker_status",
            "maintenance_enable",
            "maintenance_disable",
            "file_save",
            "file_revert",
        }
        actions_module.user_can_view = lambda user: True
        actions_module.user_can_execute = lambda user: True
        actions_module.docker_enabled = lambda: True
        actions_module.allowed_docker_services = lambda: ["web"]
        actions_module.allowed_editor_files = lambda: ["requirements.txt"]
        actions_module.read_editor_file = lambda _name: ""
        actions_module.save_editor_file = lambda _name, _content: {"backup_path": "x"}
        actions_module.revert_editor_file = lambda _name: {"backup_path": "x"}
        actions_module.editor_backup_exists = lambda _name: False
        actions_module.docker_service_snapshot = lambda: []
        actions_module.maintenance_mode_enabled = lambda: False
        actions_module.enable_maintenance_mode = lambda: {"path": "x"}
        actions_module.disable_maintenance_mode = lambda: {"path": "x"}
        actions_module.is_supported_action = lambda action_key: action_key in supported
        actions_module.allowed_manage_commands = lambda: []
        cls.webhook_calls = []
        actions_module.send_audit_webhook = lambda **kwargs: cls.webhook_calls.append(kwargs)

        eve_module = types.ModuleType("allianceauth.eveonline.models")
        eve_module.EveCharacter = type("EveCharacter", (), {"objects": types.SimpleNamespace(count=lambda: 0)})

        sys.modules["django"] = django_module
        sys.modules["django.shortcuts"] = shortcuts_module
        sys.modules["django.contrib"] = contrib_module
        sys.modules["django.contrib.messages"] = cls.fake_messages
        sys.modules["django.contrib.auth"] = auth_module
        sys.modules["django.contrib.auth.decorators"] = auth_decorators_module
        sys.modules["django.contrib.auth.models"] = auth_models_module
        sys.modules["django.utils"] = utils_module
        sys.modules["django.utils.timezone"] = timezone_module
        sys.modules["django.http"] = http_module
        sys.modules["django.db"] = db_module
        sys.modules["aa_admin_toolkit.models"] = models_module
        sys.modules["aa_admin_toolkit.tasks"] = tasks_module
        sys.modules["aa_admin_toolkit.actions"] = actions_module
        sys.modules["allianceauth.eveonline.models"] = eve_module

        if "aa_admin_toolkit.views" in sys.modules:
            del sys.modules["aa_admin_toolkit.views"]
        cls.views = importlib.import_module("aa_admin_toolkit.views")

        if real_actions_module is not None:
            sys.modules["aa_admin_toolkit.actions"] = real_actions_module

    def setUp(self):
        self.fake_messages = self.__class__.fake_messages
        self.fake_log_manager = self.__class__.fake_log_manager
        self.fake_task = self.__class__.fake_task
        self.webhook_calls = self.__class__.webhook_calls
        self.fake_log_manager.created.clear()
        self.fake_task.calls.clear()
        self.webhook_calls.clear()

    def test_full_restart_requires_checkbox(self):
        request = _FakeRequest({"action": "docker_full_restart", "confirm_full_restart_phrase": "RESTART STACK"})
        response = self.views.operations(request)

        self.assertEqual(response.get("redirect"), "aa_admin_toolkit:operations")
        self.assertTrue(any("explicit confirmation" in msg for level, msg in request._messages if level == "error"))
        self.assertEqual(self.fake_task.calls, [])

    def test_full_restart_requires_phrase(self):
        request = _FakeRequest({"action": "docker_full_restart", "confirm_full_restart": "1", "confirm_full_restart_phrase": "wrong"})
        response = self.views.operations(request)

        self.assertEqual(response.get("redirect"), "aa_admin_toolkit:operations")
        self.assertTrue(any("RESTART STACK" in msg for level, msg in request._messages if level == "error"))
        self.assertEqual(self.fake_task.calls, [])

    def test_package_full_recreate_requires_extra_checkbox(self):
        request = _FakeRequest({
            "action": "pip_upgrade",
            "package": "requests",
            "confirm_package_change": "1",
            "followup": "full_stack_recreate",
            "confirm_followup_recreate_phrase": "RECREATE STACK",
        })
        response = self.views.operations(request)

        self.assertEqual(response.get("redirect"), "aa_admin_toolkit:operations")
        self.assertTrue(any("additional confirmation" in msg for level, msg in request._messages if level == "error"))
        self.assertEqual(self.fake_task.calls, [])

    def test_package_full_recreate_requires_phrase(self):
        request = _FakeRequest({
            "action": "pip_install",
            "package": "requests",
            "confirm_package_change": "1",
            "followup": "full_stack_recreate",
            "confirm_followup_recreate": "1",
            "confirm_followup_recreate_phrase": "wrong",
        })
        response = self.views.operations(request)

        self.assertEqual(response.get("redirect"), "aa_admin_toolkit:operations")
        self.assertTrue(any("RECREATE STACK" in msg for level, msg in request._messages if level == "error"))
        self.assertEqual(self.fake_task.calls, [])

    def test_valid_confirmations_dispatch_background_task(self):
        request = _FakeRequest({
            "action": "pip_uninstall",
            "package": "requests",
            "confirm_package_change": "1",
            "followup": "full_stack_recreate",
            "confirm_followup_recreate": "1",
            "confirm_followup_recreate_phrase": "RECREATE STACK",
        })
        response = self.views.operations(request)

        self.assertEqual(response.get("redirect"), "aa_admin_toolkit:operations")
        self.assertEqual(len(self.fake_log_manager.created), 1)
        self.assertEqual(len(self.fake_task.calls), 1)
        self.assertEqual(self.fake_task.calls[0][1], "pip_uninstall")

    def test_maintenance_toggle_sends_audit_webhook(self):
        request = _FakeRequest({"action": "maintenance_enable"})

        response = self.views.operations(request)

        self.assertEqual(response.get("redirect"), "aa_admin_toolkit:operations")
        self.assertEqual(len(self.fake_log_manager.created), 1)
        self.assertEqual(len(self.webhook_calls), 1)
        self.assertEqual(self.webhook_calls[0]["action_type"], "maintenance_enable")
        self.assertEqual(self.webhook_calls[0]["status"], "SUCCESS")
        self.assertEqual(self.webhook_calls[0]["target"], "-")

    def test_file_save_sends_audit_webhook(self):
        request = _FakeRequest({
            "action": "file_save",
            "file": "requirements.txt",
            "content": "django>=4.2",
        })

        response = self.views.operations(request)

        self.assertEqual(response.get("redirect"), "/admin-toolkit/operations/?file=requirements.txt")
        self.assertEqual(len(self.fake_log_manager.created), 1)
        self.assertEqual(len(self.webhook_calls), 1)
        self.assertEqual(self.webhook_calls[0]["action_type"], "file_save")
        self.assertEqual(self.webhook_calls[0]["status"], "SUCCESS")
        self.assertEqual(self.webhook_calls[0]["target"], "requirements.txt")

    def test_view_only_users_cannot_execute_actions(self):
        self.views.user_can_execute = lambda user: False
        request = _FakeRequest({"action": "docker_status"})

        response = self.views.operations(request)

        self.assertEqual(response.get("redirect"), "aa_admin_toolkit:operations")
        self.assertTrue(any("not execute actions" in msg for level, msg in request._messages if level == "error"))
        self.assertEqual(self.fake_task.calls, [])
        self.assertEqual(len(self.fake_log_manager.created), 0)


if __name__ == "__main__":
    unittest.main()
