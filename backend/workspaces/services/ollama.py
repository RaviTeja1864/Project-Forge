import http.client
import json
from urllib.parse import urlsplit

from django.conf import settings


class OllamaError(Exception):
    status_code = 503
    public_message = "The local model service is unavailable."


class OllamaOfflineError(OllamaError):
    public_message = "The local model service is offline or unreachable."


class OllamaTimeoutError(OllamaError):
    status_code = 504
    public_message = "The local model request timed out. Try again."


class OllamaProtocolError(OllamaError):
    status_code = 502
    public_message = "The local model returned an invalid response."


class OllamaRequestTooLargeError(OllamaError):
    status_code = 413
    public_message = "The project context is too large for the local model. Reduce the source or artifact size and try again."


class OllamaConfigurationError(OllamaError):
    public_message = "The local model service configuration is invalid."


class OllamaModelMissingError(OllamaError):
    status_code = 503
    public_message = "The configured local model is not available."


def _endpoint():
    raw = settings.OLLAMA_BASE_URL
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise OllamaConfigurationError from error
    allowed_hosts = {
        host.strip("[]").casefold() for host in settings.OLLAMA_ALLOWED_HOSTS
    }
    if (
        parsed.scheme not in ("http", "https")
        or not hostname
        or hostname.casefold() not in allowed_hosts
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise OllamaConfigurationError
    if port is not None and not 1 <= port <= 65535:
        raise OllamaConfigurationError
    if any(character in parsed.path for character in "\r\n\t"):
        raise OllamaConfigurationError
    if not settings.OLLAMA_MODEL or len(settings.OLLAMA_MODEL) > 120:
        raise OllamaConfigurationError
    if not 0 < settings.OLLAMA_CONNECT_TIMEOUT <= 30:
        raise OllamaConfigurationError
    if not 0 < settings.OLLAMA_GENERATION_TIMEOUT <= 600:
        raise OllamaConfigurationError
    if not 1 <= settings.OLLAMA_MAX_OUTPUT_TOKENS <= 4096:
        raise OllamaConfigurationError
    path = parsed.path.rstrip("/")
    return parsed, hostname, port or (443 if parsed.scheme == "https" else 80), path


def _request_json(method, endpoint_path, *, payload=None, timeout=None, max_bytes=1_000_000):
    parsed, hostname, port, prefix = _endpoint()
    connection_type = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = None
    try:
        connection = connection_type(
            hostname,
            port,
            timeout=settings.OLLAMA_CONNECT_TIMEOUT,
        )
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, f"{prefix}{endpoint_path}", body=body, headers=headers)
        if connection.sock is not None and timeout is not None:
            connection.sock.settimeout(timeout)
        response = connection.getresponse()
        raw = response.read(max_bytes + 1)
        if response.status == 404:
            raise OllamaModelMissingError
        if len(raw) > max_bytes or response.status < 200 or response.status >= 300:
            raise OllamaProtocolError
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OllamaProtocolError from error
        if not isinstance(value, dict):
            raise OllamaProtocolError
        return value
    except TimeoutError as error:
        raise OllamaTimeoutError from error
    except OllamaError:
        raise
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise OllamaOfflineError from error
    finally:
        if connection is not None:
            connection.close()


def model_status():
    try:
        value = _request_json(
            "GET",
            "/api/tags",
            timeout=settings.OLLAMA_CONNECT_TIMEOUT,
            max_bytes=256_000,
        )
    except OllamaModelMissingError:
        return {
            "available": False,
            "model": settings.OLLAMA_MODEL,
            "state": "model_missing",
        }
    models = value.get("models")
    if not isinstance(models, list):
        raise OllamaProtocolError
    available_models = [
        item.get("name")
        for item in models
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    configured = settings.OLLAMA_MODEL
    available = configured in available_models or (
        configured.endswith(":latest")
        and any(name.split(":", 1)[0] == configured.split(":", 1)[0] for name in available_models)
    )
    return {
        "available": available,
        "model": configured,
        "state": "available" if available else "model_missing",
    }


def generate_json(prompt, *, max_output_tokens=None):
    if not isinstance(prompt, str) or not prompt.strip():
        raise OllamaProtocolError
    if len(prompt) > 60_000:
        raise OllamaRequestTooLargeError
    token_limit = max_output_tokens or settings.OLLAMA_MAX_OUTPUT_TOKENS
    if not 1 <= token_limit <= settings.OLLAMA_MAX_OUTPUT_TOKENS:
        raise OllamaConfigurationError
    payload = {
        "model": settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"num_predict": token_limit},
    }
    value = _request_json(
        "POST",
        "/api/generate",
        payload=payload,
        timeout=settings.OLLAMA_GENERATION_TIMEOUT,
    )
    response = value.get("response")
    if not isinstance(response, str) or not response.strip() or len(response) > 100_000:
        raise OllamaProtocolError
    try:
        result = json.loads(response)
    except json.JSONDecodeError as error:
        raise OllamaProtocolError from error
    if not isinstance(result, dict):
        raise OllamaProtocolError
    return result
