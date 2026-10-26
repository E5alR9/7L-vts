# -*- coding: utf-8 -*-
"""人聲分離前先等她講完應答（2026-10-26：分離和語音合成搶同一張顯卡，分離中合成一句要 24～51 秒）。"""
import asyncio
import time

import core.stage_state as stage
import services.auto_cover_pipeline as acp


def test_waits_while_talking_then_goes():
    async def go():
        stage.set_ai_state("TALKING", "測試")

        async def finish():
            await asyncio.sleep(0.3)
            stage.set_ai_state("IDLE", "測試")
        asyncio.ensure_future(finish())
        return await acp._let_her_finish_talking(max_wait=5.0)
    waited = asyncio.run(go())
    assert 0.25 <= waited < 2.0


def test_does_not_wait_while_singing_or_idle():
    for state in ("SINGING", "IDLE"):
        stage.set_ai_state(state, "測試")
        t0 = time.time()
        assert asyncio.run(acp._let_her_finish_talking(max_wait=5.0)) < 0.1 and time.time() - t0 < 0.5
    stage.set_ai_state("IDLE", "測試")


def test_gives_up_after_max_wait():
    stage.set_ai_state("TALKING", "測試")
    try:
        assert 0.3 <= asyncio.run(acp._let_her_finish_talking(max_wait=0.3)) < 1.5
    finally:
        stage.set_ai_state("IDLE", "測試")


def test_waits_for_queued_speech_too():
    """應答講完、主腦的回覆還在排隊：也要等（2026-10-26 實機：沒等的那句拖了 84 秒）。"""
    pending = {"n": 1}
    stage.register_speech_pending_probe(lambda: pending["n"] > 0)
    try:
        async def go():
            async def drain():
                await asyncio.sleep(0.3)
                pending["n"] = 0
                stage.notify_change()
            asyncio.ensure_future(drain())
            return await acp._let_her_finish_talking(max_wait=5.0)
        assert 0.25 <= asyncio.run(go()) < 2.0
    finally:
        stage.register_speech_pending_probe(None)
