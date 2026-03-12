from __future__ import annotations

from typing import Any

import requests

from .client_store import load_config


class ClientError(RuntimeError):
    pass


class BackendClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        config = load_config()
        self.base_url = (base_url or config["base_url"]).rstrip("/")
        self.api_key = api_key if api_key is not None else config.get("api_key", "")
        self.session = requests.Session()
        self.session.headers.update({"accept": "application/json"})

    def request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = False,
        admin_key: str | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers: dict[str, str] = {}
        if auth:
            if not self.api_key:
                raise ClientError("missing API key; run `spore login --private-key ...`")
            headers["x-api-key"] = self.api_key
        if admin_key:
            headers["x-admin-key"] = admin_key
        response = self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            params=params,
            json=json_body,
            headers=headers,
            timeout=30,
        )
        if response.ok:
            if not response.content:
                return {}
            return response.json()
        try:
            payload = response.json()
        except Exception:
            payload = response.text
        raise ClientError(f"{response.status_code} {payload}")

    def get(self, path: str, *, auth: bool = False, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, auth=auth, params=params)

    def post(
        self,
        path: str,
        *,
        auth: bool = False,
        admin_key: str | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        return self.request("POST", path, auth=auth, admin_key=admin_key, json_body=json_body)

    def patch(
        self,
        path: str,
        *,
        auth: bool = False,
        admin_key: str | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        return self.request("PATCH", path, auth=auth, admin_key=admin_key, json_body=json_body)
