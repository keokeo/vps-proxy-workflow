import argparse
import contextlib
import importlib.util
import io
import json
import pathlib
import statistics
import subprocess
import tempfile
import time
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'benchmark_targets.py'
spec = importlib.util.spec_from_file_location('benchmark_targets', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class BenchmarkTests(unittest.TestCase):
    def test_domains_are_dns_only(self):
        self.assertEqual(module.valid_domain('WWW.Example.COM.'), 'www.example.com')
        for invalid in ['example.com;touch /tmp/oops', '$(whoami).com', '-a.example', 'https://example.com', 'a..com', 'example.com..', 'example.com:443', '192.0.2.1', 'localhost', 'éxample.com', 'a'*64+'.com']:
            with self.subTest(invalid=invalid), self.assertRaises(argparse.ArgumentTypeError):
                module.valid_domain(invalid)

    def test_partial_success_does_not_win_ranking(self):
        reliable = {'domain':'reliable.example', 'summary': module.summarize([
            {'status':'ok','elapsed_ms':30}, {'status':'ok','elapsed_ms':32}, {'status':'ok','elapsed_ms':34}])}
        partial = {'domain':'partial.example', 'summary':module.summarize([
            {'status':'ok','elapsed_ms':2}, {'status':'timeout','elapsed_ms':1000}, {'status':'error','elapsed_ms':3}])}
        self.assertEqual(module.rank_results([partial,reliable]), ['reliable.example','partial.example'])
        self.assertEqual(partial['summary'], {'success_count':1,'failure_count':2,'timeout_count':1,'median_ms':2,'min_ms':2,'max_ms':2})
        empty = module.summarize([{'status':'timeout','elapsed_ms':1000}])
        self.assertIsNone(empty['median_ms'])

    def fake_probe(self, code, output, compatibility=False):
        calls=[]
        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, code, stdout=output, stderr='')
        ticks=iter([1000000, 42000000])
        result = module.probe('example.com',1,'openssl','timeout',compatibility,runner=runner,clock=lambda:next(ticks))
        self.assertNotIn('timeout', calls[0][1])
        self.assertNotIn('shell', calls[0][1])
        self.assertEqual(result['elapsed_ms'],41)
        return result,calls[0][0]

    def test_tls13_h2_and_hostname_verification(self):
        result,command=self.fake_probe(0,'New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384\nALPN protocol: h2\nVerify return code: 0 (ok)\n',True)
        self.assertTrue(result['checks_passed'])
        self.assertEqual(command[-6:],['-tls1_3','-alpn','h2','-verify_hostname','example.com','-verify_return_error'])

    def test_tls_success_without_http2_stays_incompatible(self):
        result,_=self.fake_probe(0,'New, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384\nNo ALPN negotiated\nVerify return code: 0 (ok)\n',True)
        self.assertEqual(result['status'],'ok')
        self.assertTrue(result['tls_1_3'])
        self.assertTrue(result['certificate_and_hostname_verified'])
        self.assertFalse(result['http2'])
        self.assertFalse(result['checks_passed'])

    def test_timeouts_and_handshake_errors_are_distinct(self):
        for code in [124,137]:
            result,_=self.fake_probe(code,'')
            self.assertEqual(result['status'],'timeout')
            self.assertEqual(result['exit_code'],code)
        result,_=self.fake_probe(1,'verify error:num=62:hostname mismatch',True)
        self.assertEqual(result['status'],'error')
        self.assertIn('hostname verification failed',result['error'])
        self.assertFalse(result['checks_passed'])
        result,_=self.fake_probe(0,'CONNECTED only')
        self.assertEqual(result['status'],'error')
        result,_=self.fake_probe(127,'')
        self.assertEqual(result['status'],'tool_error')

    def test_timeouts_and_round_limits_are_finite(self):
        for invalid in ['nan','inf','0','61','-1']:
            with self.subTest(invalid=invalid),self.assertRaises(argparse.ArgumentTypeError):
                module.positive_timeout(invalid)
        for invalid in ['0','21','1.5']:
            with self.subTest(invalid=invalid),self.assertRaises(argparse.ArgumentTypeError):
                module.round_count(invalid)

    def test_real_local_process_timing_and_cli_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=pathlib.Path(temporary)
            wrapper=root/'timeout'
            wrapper.write_text('#!/bin/sh\nshift\nshift\nshift\nexec "$@"\n')
            executable=root/'openssl'
            executable.write_text('#!/bin/sh\nsleep 0.03\ncase "$*" in\n  *-verify_hostname*) printf "New, TLSv1.3, Cipher is TEST\\nALPN protocol: h2\\nVerify return code: 0 (ok)\\n" ;;\n  *) printf "CONNECTION ESTABLISHED\\nProtocol version: TLSv1.3\\n" ;;\nesac\n')
            wrapper.chmod(0o700)
            executable.chmod(0o700)
            baseline=[]
            measured=[]
            for _ in range(5):
                started=time.monotonic_ns()
                subprocess.run([str(executable)],input='',capture_output=True,text=True,check=True)
                baseline.append((time.monotonic_ns()-started)/1_000_000)
                measured.append(module.probe('offline.example',1,str(executable),str(wrapper))['elapsed_ms'])
            difference=statistics.median(measured)-statistics.median(baseline)
            self.assertLess(difference,15, 'short probes were inflated by polling: {}'.format(difference))
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                result=module.main(['--domains','offline.example','offline.example','--rounds','2','--openssl-bin',str(executable),'--timeout-bin',str(wrapper)])
            self.assertEqual(result,0)
            data=json.loads(output.getvalue())
            self.assertEqual(len(data['results']),2)
            self.assertEqual(len(data['ranking']),2)
            for item in data['results']:
                self.assertEqual(item['summary']['success_count'],2)
                self.assertTrue(item['compatibility']['checks_passed'])
            print('local 30 ms sleep probe: direct median {:.3f} ms; helper median {:.3f} ms'.format(statistics.median(baseline),statistics.median(measured)))

if __name__=='__main__':
    unittest.main(verbosity=2)
