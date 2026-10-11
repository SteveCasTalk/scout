"""`scout sandbox-routing` against a simulated adb. Synthetic; no device settings are changed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scout_mobile import sandbox_routing as routing


class FakeAdb:
    def __init__(self,proxy='null',reverse=()):
        self.proxy=proxy;self.reverse=set(reverse);self.calls=[]

    def __call__(self,command,**_kwargs):
        args=command[1:]
        self.calls.append(args)
        out=''
        if args==['devices']:out='List of devices attached\nSERIAL1\tdevice\n'
        else:
            args=args[2:]  # drop -s SERIAL
            if args[:4]==['shell','settings','get','global']:out=self.proxy
            elif args[:4]==['shell','settings','put','global']:self.proxy=args[5]
            elif args==['reverse','--list']:out=''.join(f'UsbFfs tcp:{p} tcp:{p}\n' for p in sorted(self.reverse))
            elif args[:2]==['reverse','--remove']:self.reverse.discard(int(args[2].split(':')[1]))
            elif args[0]=='reverse':self.reverse.add(int(args[1].split(':')[1]))
            else:raise AssertionError(args)
        return subprocess.CompletedProcess(command,0,out,'')


class SandboxRoutingTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        for item in (patch.object(routing,'STATE_DIR',Path(folder.name)),patch.dict(os.environ,{'SCOUT_SANDBOX_PORT':'8899'})):
            item.start();self.addCleanup(item.stop)

    def run_with(self,adb,action,*args):
        with patch('scout_mobile.sandbox_routing.subprocess.run',side_effect=adb):
            return getattr(routing,action)('SERIAL1',*args)

    def test_up_then_down_restores_the_original_proxy_and_only_its_tunnels(self):
        adb=FakeAdb(proxy='corp.proxy:3128',reverse={5037})
        result=self.run_with(adb,'up',[8898])
        self.assertTrue(result['sandbox_routing_active'])
        self.assertEqual(adb.proxy,'127.0.0.1:8899')
        self.assertEqual(adb.reverse,{5037,8898,8899})
        self.run_with(adb,'down')
        self.assertEqual(adb.proxy,'corp.proxy:3128')
        self.assertEqual(adb.reverse,{5037})  # a tunnel Scout did not create is kept

    def test_repeated_up_keeps_the_pre_scout_proxy(self):
        adb=FakeAdb(proxy='null')
        self.run_with(adb,'up',[])
        self.run_with(adb,'up',[8898])
        self.run_with(adb,'down')
        self.assertEqual(adb.proxy,':0')
        self.assertEqual(adb.reverse,set())

    def test_down_without_a_record_clears_a_leftover_loopback_proxy(self):
        adb=FakeAdb(proxy='127.0.0.1:8899',reverse={8899})
        self.run_with(adb,'down')
        self.assertEqual((adb.proxy,adb.reverse),(':0',set()))

    def test_unknown_device_and_bad_ports_are_refused_before_changing_anything(self):
        adb=FakeAdb()
        with self.assertRaises(routing.RoutingError),patch('scout_mobile.sandbox_routing.subprocess.run',side_effect=adb):
            routing.up('OTHER',[])
        with self.assertRaises(routing.RoutingError):self.run_with(adb,'up',[80])
        self.assertEqual(adb.proxy,'null')
        self.assertFalse(any(call[2:4]==['shell','settings'] and call[4]=='put' for call in adb.calls if len(call)>4))


if __name__=='__main__':unittest.main()
