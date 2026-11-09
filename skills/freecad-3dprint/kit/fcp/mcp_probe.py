"""Probe the FreeCAD MCP RPC server. Stdlib only: no FreeCAD, no numpy.

Run with any Python 3:  python fcp/mcp_probe.py
Prints the probe result as JSON, so the setup guide can show the agent and the
user the same evidence.

The probe is informational. It never blocks a build, a check or the gate; a
machine with no MCP server is a fully supported configuration.
"""
import json
import socket
import xmlrpc.client

PROTOCOL_VERSION = 1
ENDPOINT = "127.0.0.1:9875"
TIMEOUT = 2.0


class _TimeoutTransport(xmlrpc.client.Transport):
    """xmlrpc's Transport has no timeout parameter; this one does.

    Without it the probe would inherit the OS connect timeout and the "2 s"
    promise would be false.
    """

    def __init__(self, timeout=TIMEOUT):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        # get_host_info returns the URL-ish host ("http://127.0.0.1:9875/RPC2"), and
        # Transport passes that straight to HTTPConnection(chost), which misparses
        # it and times out instead of refusing. Parse it, then hand the socket a
        # real timeout: HTTPConnection connects on .request(), so passing it after
        # construction is too late.
        import http.client
        from urllib.parse import urlsplit
        if self._connection and host == self._connection[0]:
            return self._connection[1]
        parts = urlsplit(host if "//" in host else "//" + host)
        netloc = parts.netloc or parts.path
        chost, self._extra_headers, _x509 = self.get_host_info(netloc)
        # get_host_info again may return the whole thing; take the bare authority
        bare = urlsplit(chost).netloc or chost
        self._connection = host, http.client.HTTPConnection(bare, timeout=self._timeout)
        return self._connection[1]


def _result(endpoint, available=False, protocol=None, addon=None, reason="unreachable"):
    return {"available": available, "endpoint": endpoint,
            "protocol_version": protocol, "addon_version": addon, "reason": reason}


def probe(endpoint=ENDPOINT, timeout=TIMEOUT, server_factory=None):
    """Ask the MCP server whether it is there. Never raises."""
    uri = "http://%s/RPC2" % endpoint
    if server_factory is None:
        def server_factory(u, **kw):
            return xmlrpc.client.ServerProxy(u, allow_none=True,
                                             transport=_TimeoutTransport(timeout))

    try:
        server = server_factory(uri)
        server.ping()
    except ConnectionRefusedError:
        return _result(endpoint, reason="connection refused")
    except socket.timeout:
        return _result(endpoint, reason="timed out")
    except xmlrpc.client.ProtocolError as exc:
        return _result(endpoint, reason="not an XML-RPC server: %s" % exc)
    except xmlrpc.client.Fault as exc:
        return _result(endpoint, reason="not an XML-RPC server: fault %s" % exc)
    except OSError as exc:
        if isinstance(exc, ConnectionRefusedError):
            return _result(endpoint, reason="connection refused")
        return _result(endpoint, reason="unreachable: %s" % exc)
    except Exception as exc:  # noqa: BLE001 - the probe reports, it never propagates
        return _result(endpoint, reason="unreachable: %s" % exc)

    try:
        status = server.get_rpc_status() or {}
    except Exception as exc:  # noqa: BLE001 - ping answered; a status failure is still a result
        return _result(endpoint, available=True, reason="ok, but no version: %s" % exc)

    protocol = status.get("protocol_version")
    addon = status.get("addon_version")
    if protocol is not None and protocol != PROTOCOL_VERSION:
        return _result(endpoint, protocol=protocol, addon=addon,
                       reason="wrong protocol version: server %s, probe %s"
                              % (protocol, PROTOCOL_VERSION))
    return _result(endpoint, available=True, protocol=protocol, addon=addon, reason="ok")


def main():
    print(json.dumps(probe(), indent=2))


from cli import run  # noqa: E402

run(main, module_name=__name__)
