from __future__ import annotations

import asyncio
import json
import logging
import typing

import aiohttp

from lava import errors, events, models

log = logging.getLogger(__name__)


class Lavalink:
    def __init__(self) -> None:
        self._is_ssl: bool | None = None
        self._host: str | None = None
        self._port: int | str | None = None

        self._session: aiohttp.ClientSession | None = None
        self._websocket: aiohttp.client._WSRequestContextManager | None = None

        self.event_listeners: dict[
            typing.Type[events.Event], list[events.EventsCallbackT]
        ] = {}

    @property
    def is_ssl(self) -> bool:
        if self._is_ssl is None:
            raise RuntimeError("Lavalink.connect() was not called.")

        return self._is_ssl

    @property
    def host(self) -> str:
        if self._host is None:
            raise RuntimeError("Lavalink.connect() was not called.")

        return self._host

    @property
    def port(self) -> int | str:
        if self._port is None:
            raise RuntimeError("Lavalink.connect() was not called.")

        return self._port

    @property
    def session(self) -> aiohttp.ClientSession:
        if not self._session:
            raise RuntimeError("Lavalink.connect() was not called.")

        return self._session

    @property
    def websocket(self) -> aiohttp.client._WSRequestContextManager:
        if not self._websocket:
            raise RuntimeError("Lavalink.connect() was not called.")

        return self._websocket

    async def close(self) -> None:
        await self.session.close()
        self.websocket.close()

    async def connect(
        self,
        host: str,
        port: int | str,
        password: str,
        bot_id: int,
        resume_key: str | None = None,
        is_ssl: bool = False,
    ) -> None:
        self._is_ssl = is_ssl
        self._host = host
        self._port = port

        headers = {
            "Authorization": password,
            "User-Id": str(bot_id),
            "Client-Name": "lava.py/0.0.0",
        }
        if resume_key:
            headers["Resume-Key"] = resume_key

        self._session = aiohttp.ClientSession(headers=headers)
        self._websocket = self._session.ws_connect(
            f"{'wss' if is_ssl else 'ws'}://{host}:{port}/v3/websocket"
        )

        asyncio.create_task(self._start_listening())

    async def _start_listening(self) -> None:
        async with self.websocket as ws:
            async for msg in ws:
                data: dict = json.loads(msg.data)

                if data["op"] == "ready":
                    self.dispatch(events.ReadyEvent.from_payload(data))

                elif data["op"] == "playerUpdate":
                    self.dispatch(events.PlayerUpdateEvent.from_payload(data))

                elif data["op"] == "stats":
                    self.dispatch(events.StatsEvent.from_payload(data))

                elif data["op"] == "event":
                    if data["type"] == "TrackStartEvent":
                        self.dispatch(events.TrackStartEvent.from_payload(data))
                    elif data["type"] == "TrackEndEvent":
                        self.dispatch(events.TrackEndEvent.from_payload(data))
                    elif data["type"] == "TrackExceptionEvent":
                        self.dispatch(events.TrackExceptionEvent.from_payload(data))
                    elif data["type"] == "TrackStuckEvent":
                        self.dispatch(events.TrackStuckEvent.from_payload(data))
                    elif data["type"] == "WebSocketClosedEvent":
                        self.dispatch(events.WebSocketClosedEvent.from_payload(data))

    def dispatch(self, event: events.Event) -> None:
        if listeners := self.event_listeners.get(type(event)):
            for listener in listeners:
                asyncio.create_task(listener(event))  # type: ignore[arg-type]

    def listen(
        self, event_type: typing.Type[events.EventT]
    ) -> typing.Callable[[events.EventsCallbackT], None]:
        def decorator(
            callback: events.EventsCallbackT,
        ) -> None:
            if event_type in self.event_listeners:
                self.event_listeners[event_type].append(callback)
            else:
                self.event_listeners[event_type] = [callback]

        return decorator

    ## REST API METHODS

    async def get(self, path: str) -> typing.Any:
        async with self.session.get(
            f"{'http' if self.is_ssl else 'https'}://{self.host}:{self.port}/v3/{path}&trace=true"
        ) as res:
            data = await res.json()

            if not res.ok:
                raise errors.LavalinkError.from_payload(
                    data
                ) from res.raise_for_status()

            return data

    async def get_players(self, session_id: str) -> list[models.Player]:
        return [
            models.Player.from_payload(p) for p in
            await self.get(f"sessions/{session_id}/players")
        ]