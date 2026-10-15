import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from backend.workspaces.services.ollama import (
    OllamaConfigurationError,
    OllamaOfflineError,
    OllamaProtocolError,
    OllamaRequestTooLargeError,
    OllamaTimeoutError,
    _endpoint,
    _request_json,
    generate_json,
    model_status,
)


class OllamaClientTests(SimpleTestCase):
    @override_settings(
        OLLAMA_BASE_URL="http://username@localhost:11434",
        OLLAMA_ALLOWED_HOSTS=("localhost",),
    )
    def test_endpoint_rejects_userinfo(self):
        with self.assertRaises(OllamaConfigurationError):
            _endpoint()

    @override_settings(
        OLLAMA_BASE_URL="http://localhost:11434/prefix",
        OLLAMA_ALLOWED_HOSTS=("localhost", "127.0.0.1", "::1"),
    )
    def test_endpoint_only_allows_explicit_hosts_and_safe_url_parts(self):
        endpoint, host, port, prefix = _endpoint()
        self.assertEqual((endpoint.scheme, host, port, prefix), ("http", "localhost", 11434, "/prefix"))

    @override_settings(
        OLLAMA_BASE_URL="http://metadata.internal/latest",
        OLLAMA_ALLOWED_HOSTS=("localhost", "127.0.0.1", "::1"),
    )
    def test_endpoint_rejects_untrusted_hosts(self):
        with self.assertRaises(OllamaConfigurationError):
            _endpoint()

    @override_settings(
        OLLAMA_BASE_URL="http://user:password@localhost:11434",
        OLLAMA_ALLOWED_HOSTS=("localhost",),
    )
    def test_endpoint_rejects_credentials(self):
        with self.assertRaises(OllamaConfigurationError):
            _endpoint()

    @patch("backend.workspaces.services.ollama.http.client.HTTPConnection")
    @override_settings(OLLAMA_BASE_URL="http://localhost:11434", OLLAMA_ALLOWED_HOSTS=("localhost",))
    def test_request_uses_fixed_path_timeouts_and_bounded_json(self, connection_class):
        connection = connection_class.return_value
        connection.sock = Mock()
        response = Mock(status=200)
        response.read.return_value = json.dumps({"models": []}).encode()
        connection.getresponse.return_value = response
        result = _request_json("GET", "/api/tags", timeout=3)
        self.assertEqual(result, {"models": []})
        connection_class.assert_called_once_with("localhost", 11434, timeout=3.0)
        connection.request.assert_called_once_with(
            "GET", "/api/tags", body=None, headers={"Accept": "application/json"}
        )
        connection.sock.settimeout.assert_called_once_with(3)

    @patch("backend.workspaces.services.ollama.http.client.HTTPConnection")
    @override_settings(OLLAMA_BASE_URL="http://localhost:11434", OLLAMA_ALLOWED_HOSTS=("localhost",))
    def test_request_translates_timeout_and_rejects_redirects(self, connection_class):
        connection = connection_class.return_value
        connection.request.side_effect = TimeoutError("private socket details")
        with self.assertRaises(OllamaTimeoutError) as timeout_error:
            _request_json("GET", "/api/tags")
        self.assertNotIn("private socket details", str(timeout_error.exception))

        connection.request.side_effect = None
        connection.getresponse.return_value = Mock(status=302, read=Mock(return_value=b""))
        with self.assertRaises(OllamaProtocolError):
            _request_json("GET", "/api/tags")

    @override_settings(
        OLLAMA_BASE_URL="http://localhost:11434",
        OLLAMA_ALLOWED_HOSTS=("localhost",),
        OLLAMA_MODEL="qwen3:4b",
        OLLAMA_MAX_OUTPUT_TOKENS=512,
        OLLAMA_GENERATION_TIMEOUT=45,
    )
    @patch("backend.workspaces.services.ollama._request_json")
    def test_generation_is_bounded_json_and_validates_model_result(self, request_json):
        request_json.return_value = {
            "response": '{"problem_summary": "Evidence-based summary"}'
        }
        result = generate_json("Use only supplied evidence.", max_output_tokens=128)
        self.assertEqual(result, {"problem_summary": "Evidence-based summary"})
        args, kwargs = request_json.call_args
        self.assertEqual(args[:2], ("POST", "/api/generate"))
        self.assertEqual(kwargs["timeout"], 45)
        self.assertEqual(kwargs["payload"]["model"], "qwen3:4b")
        self.assertEqual(kwargs["payload"]["stream"], False)
        self.assertEqual(kwargs["payload"]["format"], "json")
        self.assertEqual(kwargs["payload"]["think"], False)
        self.assertEqual(kwargs["payload"]["options"]["num_predict"], 128)

    @override_settings(
        OLLAMA_BASE_URL="http://localhost:11434",
        OLLAMA_ALLOWED_HOSTS=("localhost",),
        OLLAMA_MODEL="qwen3:4b",
        OLLAMA_MAX_OUTPUT_TOKENS=512,
    )
    @patch("backend.workspaces.services.ollama._request_json")
    def test_generation_rejects_malformed_model_output(self, request_json):
        request_json.return_value = {"response": "not-json"}
        with self.assertRaises(OllamaProtocolError):
            generate_json("Return JSON")
        with self.assertRaises(OllamaProtocolError):
            generate_json(" ")
        with self.assertRaises(OllamaConfigurationError):
            generate_json("Return JSON", max_output_tokens=600)
        with self.assertRaises(OllamaRequestTooLargeError):
            generate_json("x" * 60_001)

    @override_settings(
        OLLAMA_BASE_URL="http://localhost:11434",
        OLLAMA_ALLOWED_HOSTS=("localhost",),
        OLLAMA_MODEL="qwen3:4b",
    )
    @patch("backend.workspaces.services.ollama._request_json")
    def test_model_status_reports_presence_without_internal_details(self, request_json):
        request_json.return_value = {"models": [{"name": "qwen3:4b"}]}
        self.assertEqual(
            model_status(),
            {"available": True, "model": "qwen3:4b", "state": "available"},
        )
        request_json.return_value = {"models": [{"name": "other:latest"}]}
        self.assertEqual(
            model_status(),
            {"available": False, "model": "qwen3:4b", "state": "model_missing"},
        )

    def test_error_classes_have_safe_public_messages(self):
        for error_type in (
            OllamaOfflineError,
            OllamaTimeoutError,
            OllamaProtocolError,
            OllamaRequestTooLargeError,
            OllamaConfigurationError,
        ):
            with self.subTest(error=error_type.__name__):
                self.assertNotIn("localhost", error_type.public_message)
                self.assertNotIn("password", error_type.public_message)
