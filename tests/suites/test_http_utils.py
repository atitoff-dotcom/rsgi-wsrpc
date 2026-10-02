# -*- coding: utf-8 -*-
import pytest
from rsgi_wsrpc.core.http import extract_header, extract_query_params


class DummyScope:
    def __init__(self, headers=None, query_string=""):
        self.headers = headers
        self.query_string = query_string


def test_extract_header_from_dict():
    scope = {"headers": {"user-agent": "Googlebot/2.1", "content-type": "application/json"}}
    assert extract_header(scope, "User-Agent") == "Googlebot/2.1"
    assert extract_header(scope, "CONTENT-TYPE") == "application/json"
    assert extract_header(scope, "X-Non-Existent") is None
    assert extract_header(scope, "X-Non-Existent", "default_val") == "default_val"


def test_extract_header_from_tuples():
    scope = DummyScope(headers=[
        (b"user-agent", b"TelegramBot"),
        ("x-custom-key", "secret123"),
    ])
    assert extract_header(scope, "User-Agent") == "TelegramBot"
    assert extract_header(scope, "X-Custom-Key") == "secret123"
    assert extract_header(scope, "host") is None


def test_extract_header_granian_mock():
    class MockHeaders:
        def __init__(self, mapping):
            self._map = {k.lower(): v for k, v in mapping.items()}

        def get(self, key):
            if not isinstance(key, str):
                raise TypeError("'bytes' object is not an instance of 'str' while processing 'key'")
            return self._map.get(key.lower())

    scope = DummyScope(headers=MockHeaders({"Host": "example.com", "Authorization": "Bearer token123"}))
    assert extract_header(scope, "host") == "example.com"
    assert extract_header(scope, "authorization") == "Bearer token123"
    # Заголовок отсутствует: не должен вызывать TypeError из-за fallback на bytes
    assert extract_header(scope, "cookie") is None
    assert extract_header(scope, "cookie", "default_val") == "default_val"


def test_extract_header_dict_with_byte_keys():
    scope = {"headers": {b"user-agent": b"Curl/7.68.0", b"x-auth": "secret123"}}
    assert extract_header(scope, "User-Agent") == "Curl/7.68.0"
    assert extract_header(scope, "X-Auth") == "secret123"
    assert extract_header(scope, "missing") is None
    assert extract_header(scope, "missing", "fallback") == "fallback"



def test_extract_query_params():
    scope = DummyScope(query_string="a=1&b=hello&c=foo%20bar")
    params = extract_query_params(scope)
    assert params == {"a": "1", "b": "hello", "c": "foo bar"}

    scope_bytes = DummyScope(query_string=b"tag=python&page=2")
    params_bytes = extract_query_params(scope_bytes)
    assert params_bytes == {"tag": "python", "page": "2"}

    scope_dict = {"query_string": "search=test"}
    assert extract_query_params(scope_dict) == {"search": "test"}

    scope_empty = DummyScope(query_string="")
    assert extract_query_params(scope_empty) == {}
