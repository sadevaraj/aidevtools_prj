"""The runtime launcher honors the host-provided listening port."""

from types import SimpleNamespace
from unittest.mock import patch

from app import server


def test_server_binds_to_configured_render_port() -> None:
    with (
        patch.object(server, "settings", SimpleNamespace(port=10000)),
        patch.object(server.uvicorn, "run") as run,
    ):
        server.main()

    run.assert_called_once_with(server.app, host="0.0.0.0", port=10000)
