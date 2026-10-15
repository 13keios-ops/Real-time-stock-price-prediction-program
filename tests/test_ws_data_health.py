from datetime import datetime,timedelta
import unittest
import importlib.util


class DataHealthTests(unittest.TestCase):
    def setUp(self):
        from app.brokers import kis_quote_ws
        self.assertTrue(hasattr(kis_quote_ws,'KisWebSocketDataHealth'),'Per-channel liveness missing')
        self.cls=kis_quote_ws.KisWebSocketDataHealth
        self.now=datetime.fromisoformat('2026-10-16T09:00:00+09:00')
        self.health=self.cls(('H0STCNT0','H0STASP0'))

    def test_book_and_heartbeat_cannot_hide_trade_silence(self):
        self.health.observe('H0STCNT0',self.now)
        self.health.observe('H0STASP0',self.now)
        self.now+=timedelta(seconds=61)
        with self.assertRaisesRegex(Exception,'H0STCNT0'):
            self.health.observe('H0STASP0',self.now)

    def test_control_frames_do_not_reset_freshness(self):
        self.health.observe(None,self.now)
        with self.assertRaisesRegex(Exception,'data silence'):
            self.health.observe(None,self.now+timedelta(seconds=61))

    def test_warmup_and_closing_auction_do_not_trigger_trade_storm(self):
        self.health.observe(None,self.now.replace(hour=8))
        self.health.observe(None,self.now.replace(hour=8,minute=59))
        self.health.observe('H0STASP0',self.now)
        self.health.observe(None,self.now.replace(hour=15,minute=20))

    def test_listener_reconnects_when_pingpong_masks_missing_data(self):
        import asyncio
        import json
        from unittest.mock import AsyncMock,patch
        from tests.test_kis_ws_reconnect_metrics import KisWebSocketReconnectRetryTests
        client=KisWebSocketReconnectRetryTests()._client()
        class Connection:
            def __init__(self,frames):self.frames=iter(frames)
            async def __aenter__(self):return self
            async def __aexit__(self,*args):return False
            async def send(self,message):pass
            async def pong(self,message):pass
            async def recv(self):return next(self.frames)
        ping=json.dumps({'header':{'tr_id':'PINGPONG'}})
        frame='0|H0STCNT0|001|005930^090000^70000'
        connections=iter([Connection([ping,ping]),Connection([frame])])
        class Transport:
            @staticmethod
            def connect(*args,**kwargs):return next(connections)
        snapshots=[]
        async def collect():
            return [f async for f in client.listen(['005930'],include_orderbook=False,
                max_frames=1,max_reconnects=1,metrics_callback=snapshots.append)]
        with patch.object(type(client),'issue_approval_key',return_value='fixture'), \
                patch('app.brokers.kis_quote_ws.websockets',Transport), \
                patch('app.brokers.kis_quote_ws.asyncio.sleep',new_callable=AsyncMock), \
                patch('app.brokers.kis_quote_ws._now_local',side_effect=[self.now,self.now+timedelta(seconds=61),self.now+timedelta(seconds=62)]):
            self.assertEqual(asyncio.run(collect()),[frame])
        failures=[s for s in snapshots if s.state=='disconnected']
        self.assertEqual(len(failures),1)
