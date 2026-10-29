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
    assert 'os.getenv("WEB_BIND_HOST") or "0.0.0.0"' in src and "middlewares=[_lan_only]" in src
