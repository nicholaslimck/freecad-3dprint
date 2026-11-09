import os
import socket
import sys
import xmlrpc.client

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "freecad-3dprint", "kit", "fcp"))
os.environ.setdefault("FCP_NO_MAIN", "1")

import mcp_probe  # noqa: E402


class _Fake:
    def __init__(self, status=None, ping_exc=None, status_exc=None):
        self._status, self._ping_exc, self._status_exc = status, ping_exc, status_exc

    def ping(self):
        if self._ping_exc:
            raise self._ping_exc
        return True

    def get_rpc_status(self):
        if self._status_exc:
            raise self._status_exc
        return self._status


STATUS = {"success": True, "addon_version": "0.1.30", "protocol_version": 1}


def test_available_reports_versions():
    got = mcp_probe.probe(server_factory=lambda *a, **k: _Fake(STATUS))
    assert got["available"] is True and got["reason"] == "ok"
    assert got["addon_version"] == "0.1.30" and got["protocol_version"] == 1
    assert got["endpoint"] == "127.0.0.1:9875"


def test_connection_refused_is_named():
    exc = ConnectionRefusedError(10061, "actively refused")
    got = mcp_probe.probe(server_factory=lambda *a, **k: _Fake(STATUS, ping_exc=exc))
    assert got["available"] is False and got["reason"] == "connection refused"
    assert got["addon_version"] is None and got["protocol_version"] is None


def test_wrong_protocol_is_not_available_but_reports_the_version():
    got = mcp_probe.probe(server_factory=lambda *a, **k: _Fake(dict(STATUS, protocol_version=7)))
    assert got["available"] is False
    assert got["reason"].startswith("wrong protocol version")
    assert "7" in got["reason"] and got["protocol_version"] == 7


def test_timeout_is_named():
    got = mcp_probe.probe(server_factory=lambda *a, **k: _Fake(STATUS, ping_exc=socket.timeout()))
    assert got["reason"] == "timed out"


def test_plain_http_server_says_so_not_refused(monkeypatch):
    """A web page or another service on the port must not read as 'FreeCAD is off'."""
    got = mcp_probe.probe(server_factory=lambda *a, **k: _Fake(
        STATUS, ping_exc=xmlrpc.client.ProtocolError("http://x", 415, "Unsupported", {})))
    assert got["reason"].startswith("not an XML-RPC server")


def test_probe_imports_no_freecad():
    src = open(mcp_probe.__file__, encoding="utf-8").read()
    assert "import FreeCAD" not in src and "import Part" not in src and "analysis" not in src


def test_probe_on_a_real_closed_port_does_not_raise():
    """The transport path is not covered by the fakes: a closed port must be a result."""
    import time
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    t0 = time.time()
    got = mcp_probe.probe(endpoint="127.0.0.1:%d" % port, timeout=1.0)
    elapsed = time.time() - t0
    assert got["available"] is False
    assert got["protocol_version"] is None and got["addon_version"] is None
    # this machine hangs rather than refusing on closed localhost ports, so the
    # reason may be either; what matters is that it returns within the timeout
    assert got["reason"] in ("connection refused", "timed out"), got["reason"]
    assert elapsed < 5.0, "probe did not honour its timeout: %.1fs" % elapsed


def test_probe_against_a_plain_http_server_says_not_xmlrpc():
    """A real HTTP server on the port must not read as 'FreeCAD is off'."""
    import http.server
    import threading
    srv = http.server.HTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        got = mcp_probe.probe(endpoint="127.0.0.1:%d" % port, timeout=2.0)
    finally:
        srv.shutdown()
    assert got["available"] is False
    assert got["reason"].startswith(("not an XML-RPC server", "timed out")), got["reason"]
