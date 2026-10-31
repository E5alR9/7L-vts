# -*- coding: utf-8 -*-
"""後台網站開給同網路的裝置（老爸 2026-10-29）：只收本機、家裡網路、Tailscale，外面的擋掉。"""
import asyncio

import services.web_dashboard as w


def test_only_home_network_tailscale_and_this_pc_get_in():
    for ok in ("127.0.0.1", "::1", "192.168.1.50", "10.0.0.5", "172.20.1.1", "100.116.25.75", "::ffff:192.168.0.3"):
        assert w.is_lan_peer(ok), ok
    for bad in ("8.8.8.8", "1.1.1.1", "::ffff:1.2.3.4", "", "not-an-ip"):
        assert not w.is_lan_peer(bad), bad


def test_middleware_refuses_outside_addresses():
    class Req:
        def __init__(self, remote):
            self.remote = remote

    async def handler(request):
        return "ok"

    assert asyncio.run(w._lan_only(Req("192.168.1.50"), handler)) == "ok"
    try:
        asyncio.run(w._lan_only(Req("8.8.8.8"), handler))
        raise AssertionError("外面的位址應該被擋")
    except w.web.HTTPForbidden:
        pass


def test_binds_all_interfaces_by_default():
    src = open(w.__file__, encoding="utf-8").read()
    assert 'os.getenv("WEB_BIND_HOST") or "0.0.0.0"' in src and "middlewares=[_lan_only, _same_site_only]" in src


def test_other_websites_cannot_drive_the_dashboard_through_the_browser():
    """別的網站借老爸的瀏覽器打後台（CSRF、DNS rebinding）要擋；自己的網址、curl 這類不帶 Origin 的照收（2026-10-31 Fable 審查）。"""
    class Req:
        def __init__(self, host, origin=None):
            self.host, self.method, self.path = host, "POST", "/api/shutdown"
            self.headers = {} if origin is None else {"Origin": origin}

    async def handler(request):
        return "ok"

    for host, origin in [("127.0.0.1:7860", None), ("localhost:7860", "http://localhost:7860"),
                         ("192.168.1.50:7860", "http://192.168.1.50:7860"), ("100.116.25.75:7860", "http://100.116.25.75:7860"),
                         ("desktop:7860", "http://desktop:7860"), ("desktop.tail1234.ts.net:7860", "http://desktop.tail1234.ts.net:7860"),
                         ("[::1]:7860", None)]:
        assert asyncio.run(w._same_site_only(Req(host, origin), handler)) == "ok", (host, origin)
    for host, origin in [("127.0.0.1:7860", "https://evil.example.com"), ("evil.example.com:7860", None),
                         ("localhost:7860", "null"), ("rebind.attacker.net:7860", "http://rebind.attacker.net:7860")]:
        try:
            asyncio.run(w._same_site_only(Req(host, origin), handler))
            raise AssertionError(("應該被擋", host, origin))
        except w.web.HTTPForbidden:
            pass
