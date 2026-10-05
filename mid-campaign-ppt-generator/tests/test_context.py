import base64
import json

import pytest

from agent_server_context import (
    bind_request_headers,
    current_invocation_data,
    require_agent_file_context,
    reset_request_headers,
)


def test_current_invocation_data_valid():
    raw = base64.b64encode(json.dumps({"agent_id": "a", "thread_id": "t"}).encode()).decode()
    token = bind_request_headers({"X-Tool-Invocation-Context": raw})
    try:
        assert current_invocation_data() == {"agent_id": "a", "thread_id": "t"}
    finally:
        reset_request_headers(token)


def test_current_invocation_data_missing_and_malformed():
    token = bind_request_headers({})
    try:
        assert current_invocation_data() == {}
    finally:
        reset_request_headers(token)
    token = bind_request_headers({"X-Tool-Invocation-Context": "not-base64"})
    try:
        assert current_invocation_data() == {}
    finally:
        reset_request_headers(token)


def test_require_agent_file_context_missing_fields():
    token = bind_request_headers({})
    try:
        with pytest.raises(RuntimeError, match="Missing required platform context fields"):
            require_agent_file_context()
    finally:
        reset_request_headers(token)
