"""W3C WebDriver / Appium UIAutomator2 driver abstraction (mock & live Appium modes)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from sut.mobile_bridge import DeterministicMobileBridge


@dataclass(frozen=True)
class Locator:
    """Appium locator tuple (`accessibility id`, `id`, `xpath`)."""

    using: str
    value: str


class MobileDriverBackend(Protocol):
    """Protocol implemented by both deterministic mock bridge and live Appium HTTP backend."""

    def create_session(self, capabilities: dict[str, Any]) -> str: ...
    def delete_session(self, session_id: str) -> None: ...
    def find_element(self, session_id: str, using: str, value: str) -> str: ...
    def click(self, session_id: str, element_id: str) -> None: ...
    def send_keys(self, session_id: str, element_id: str, text: str) -> None: ...
    def get_text(self, session_id: str, element_id: str) -> str: ...
    def is_displayed(self, session_id: str, element_id: str) -> bool: ...
    def page_source(self, session_id: str) -> str: ...


class MockAppiumBackend:
    """In-process deterministic backend routed to DeterministicMobileBridge."""

    def __init__(self, bridge: DeterministicMobileBridge) -> None:
        self._bridge = bridge

    def create_session(self, capabilities: dict[str, Any]) -> str:
        res = self._bridge.create_session(capabilities)
        return str(res["sessionId"])

    def delete_session(self, session_id: str) -> None:
        self._bridge.delete_session(session_id)

    def find_element(self, session_id: str, using: str, value: str) -> str:
        return self._bridge.find_element(session_id, using, value)

    def click(self, session_id: str, element_id: str) -> None:
        self._bridge.click(session_id, element_id)

    def send_keys(self, session_id: str, element_id: str, text: str) -> None:
        self._bridge.send_keys(session_id, element_id, text)

    def get_text(self, session_id: str, element_id: str) -> str:
        return self._bridge.get_element_text(session_id, element_id)

    def is_displayed(self, session_id: str, element_id: str) -> bool:
        return self._bridge.is_element_displayed(session_id, element_id)

    def page_source(self, session_id: str) -> str:
        return self._bridge.get_page_source(session_id)


class HttpAppiumBackend:
    """Live Appium 2.x W3C WebDriver HTTP REST backend for real Android emulators/devices."""

    def __init__(self, server_url: str) -> None:
        self._client = httpx.Client(base_url=server_url, timeout=30.0)

    def create_session(self, capabilities: dict[str, Any]) -> str:
        resp = self._client.post(
            "/session",
            json={"capabilities": {"alwaysMatch": capabilities}},
        )
        resp.raise_for_status()
        value = resp.json()["value"]
        return str(value["sessionId"])

    def delete_session(self, session_id: str) -> None:
        self._client.delete(f"/session/{session_id}")

    def find_element(self, session_id: str, using: str, value: str) -> str:
        resp = self._client.post(
            f"/session/{session_id}/element",
            json={"using": using, "value": value},
        )
        if resp.status_code == 404:
            raise LookupError(f"Element not found: {using}={value}")
        resp.raise_for_status()
        elem_obj = resp.json()["value"]
        return str(next(iter(elem_obj.values())))

    def click(self, session_id: str, element_id: str) -> None:
        resp = self._client.post(f"/session/{session_id}/element/{element_id}/click", json={})
        resp.raise_for_status()

    def send_keys(self, session_id: str, element_id: str, text: str) -> None:
        resp = self._client.post(
            f"/session/{session_id}/element/{element_id}/value",
            json={"text": text, "value": list(text)},
        )
        resp.raise_for_status()

    def get_text(self, session_id: str, element_id: str) -> str:
        resp = self._client.get(f"/session/{session_id}/element/{element_id}/text")
        resp.raise_for_status()
        return str(resp.json()["value"])

    def is_displayed(self, session_id: str, element_id: str) -> bool:
        resp = self._client.get(f"/session/{session_id}/element/{element_id}/displayed")
        resp.raise_for_status()
        return bool(resp.json()["value"])

    def page_source(self, session_id: str) -> str:
        resp = self._client.get(f"/session/{session_id}/source")
        resp.raise_for_status()
        return str(resp.json()["value"])


class MobileElement:
    """Object-oriented element wrapper used by Page Objects."""

    def __init__(self, backend: MobileDriverBackend, session_id: str, element_id: str) -> None:
        self._backend = backend
        self._session_id = session_id
        self._element_id = element_id

    def click(self) -> None:
        self._backend.click(self._session_id, self._element_id)

    def send_keys(self, text: str) -> None:
        self._backend.send_keys(self._session_id, self._element_id, text)

    @property
    def text(self) -> str:
        return self._backend.get_text(self._session_id, self._element_id)

    def is_displayed(self) -> bool:
        return self._backend.is_displayed(self._session_id, self._element_id)


class MobileDriver:
    """High-level Appium UIAutomator2 driver with explicit wait helpers."""

    def __init__(self, backend: MobileDriverBackend, capabilities: dict[str, Any]) -> None:
        self._backend = backend
        self.session_id = self._backend.create_session(capabilities)

    def find_element(self, locator: Locator) -> MobileElement:
        element_id = self._backend.find_element(self.session_id, locator.using, locator.value)
        return MobileElement(self._backend, self.session_id, element_id)

    def wait_for_element(
        self, locator: Locator, *, timeout_seconds: float = 3.0, poll_interval: float = 0.05
    ) -> MobileElement:
        deadline = time.monotonic() + timeout_seconds
        last_err: Exception | None = None
        while time.monotonic() <= deadline:
            try:
                elem = self.find_element(locator)
                if elem.is_displayed():
                    return elem
            except LookupError as exc:
                last_err = exc
            time.sleep(poll_interval)
        raise TimeoutError(
            f"Timed out waiting for locator ({locator.using}={locator.value!r}): {last_err}"
        )

    @property
    def page_source(self) -> str:
        return self._backend.page_source(self.session_id)

    def quit(self) -> None:
        self._backend.delete_session(self.session_id)
