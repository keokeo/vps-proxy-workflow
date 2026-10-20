import base64
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, unquote, urlsplit

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'build_reality_clients.py'
spec=importlib.util.spec_from_file_location('reality_clients',SCRIPT)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ClientArtifacts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='reality-offline-')
        self.root=Path(self.tmp.name).resolve()
        self.material={
            'server':'203.0.113.10','port':443,
            'uuid':'cf590485-027a-4fd6-b1fc-dc30a840e8f9',
            'public_key':base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip('='),
            'short_id':'aabbccdd11223344','servername':'www.example.com',
        }
        self.input=self.root/'metadata.json'
        self.out=self.root/'clients'
        self.write_material()
    def tearDown(self): self.tmp.cleanup()
    def write_material(self): self.input.write_text(json.dumps(self.material)); self.input.chmod(0o600)
    def run_cli(self,*extras):
        return subprocess.run([sys.executable,str(SCRIPT),'--material',str(self.input),'--out',str(self.out),*extras],text=True,capture_output=True)
    def assert_ok(self,result): self.assertEqual(result.returncode,0,result.stderr)
    def test_profile_and_uri_round_trip(self):
        self.assert_ok(result:=self.run_cli('--name','测试 / REALITY','--local-port','17890','--test-port','17891'))
        main=json.loads((self.out/'clash-verge-reality.yaml').read_text())
        isolated=json.loads((self.out/'mihomo-reality-test.yaml').read_text())
        uri=urlsplit((self.out/'shadowrocket-reality.txt').read_text().strip())
        query=parse_qs(uri.query)
        node=main['proxies'][0]
        self.assertEqual(uri.scheme,'vless'); self.assertEqual(uri.hostname,self.material['server']); self.assertEqual(uri.port,self.material['port'])
        self.assertEqual(uri.username,self.material['uuid']); self.assertEqual(unquote(uri.fragment),node['name'])
        for field,param in [('servername','sni'),('flow','flow')]: self.assertEqual(node[field],query[param][0])
        self.assertEqual(node['reality-opts']['public-key'],query['pbk'][0]);self.assertEqual(node['reality-opts']['short-id'],query['sid'][0])
        self.assertEqual(query['security'],['reality']);self.assertEqual(query['encryption'],['none']);self.assertEqual(query['type'],['tcp']);self.assertEqual(query['fp'],['chrome'])
        self.assertEqual(node['flow'],'xtls-rprx-vision');self.assertEqual(node['packet-encoding'],'xudp');self.assertTrue(node['udp']);self.assertTrue(node['tls']);self.assertFalse(node['skip-cert-verify'])
        self.assertEqual(main['proxy-groups'],[{'name':'PROXY','type':'select','proxies':[node['name']]}]);self.assertEqual(main['rules'],['MATCH,PROXY']);self.assertNotIn('DIRECT',json.dumps(main))
        self.assertFalse(main['allow-lan']);self.assertFalse(main['ipv6']);self.assertFalse(main['dns']['ipv6']);self.assertTrue(main['dns']['respect-rules']);self.assertEqual(main['bind-address'],'127.0.0.1')
        self.assertEqual(main['mixed-port'],17890);self.assertEqual(isolated.pop('mixed-port'),17891);main.pop('mixed-port');self.assertEqual(main,isolated)
        for secret in [self.material['uuid'],self.material['public_key'],self.material['short_id']]: self.assertNotIn(secret,result.stdout+result.stderr)
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode),0o700)
        for output in self.out.iterdir():self.assertEqual(stat.S_IMODE(output.stat().st_mode),0o600)
    def test_ipv6_uri_and_dns_normalization(self):
        self.material['server']='2001:db8::1';self.material['servername']='WWW.EXAMPLE.COM';self.write_material()
        self.assert_ok(self.run_cli());value=(self.out/'shadowrocket-reality.txt').read_text();self.assertIn('@[2001:db8::1]:443?',value);self.assertEqual(urlsplit(value.strip()).hostname,'2001:db8::1');self.assertIn('sni=www.example.com',value)
    def test_no_overwrite_and_explicit_overwrite(self):
        self.assert_ok(self.run_cli());before={p.name:p.read_bytes() for p in self.out.iterdir()}
        self.material['servername']='new.example.com';self.write_material()
        self.assertNotEqual(self.run_cli().returncode,0);self.assertEqual(before,{p.name:p.read_bytes() for p in self.out.iterdir()})
        self.assert_ok(self.run_cli('--overwrite'));self.assertNotEqual(before['clash-verge-reality.yaml'],(self.out/'clash-verge-reality.yaml').read_bytes())
    def test_existing_partial_output_prevents_any_publish(self):
        self.out.mkdir();(self.out/'shadowrocket-reality.txt').write_text('existing')
        self.assertNotEqual(self.run_cli().returncode,0);self.assertEqual([p.name for p in self.out.iterdir()],['shadowrocket-reality.txt'])
    def test_verified_macos_tmp_alias_is_accepted(self):
        if sys.platform != 'darwin' or not Path('/tmp').is_symlink():
            self.skipTest('macOS system /tmp alias is not present')
        with tempfile.TemporaryDirectory(prefix='reality-macos-alias-', dir='/private/tmp') as temporary:
            actual_root = Path(temporary).resolve()
            self.input = Path('/tmp') / actual_root.name / 'metadata.json'
            self.out = Path('/tmp') / actual_root.name / 'clients'
            self.write_material()
            self.assert_ok(self.run_cli())
            self.assertEqual(module.checked_path(str(self.input)), actual_root / 'metadata.json')
            self.assertTrue((actual_root / 'clients' / 'clash-verge-reality.yaml').exists())
    def test_verified_macos_var_alias_is_accepted(self):
        if sys.platform != 'darwin' or not Path('/var').is_symlink():
            self.skipTest('macOS system /var alias is not present')
        self.assertEqual(module.checked_path('/var/tmp'),Path('/private/var/tmp'))
    def test_symlink_input_rejected(self):
        real=self.root/'real.json';self.input.rename(real);self.input.symlink_to(real)
        self.assertNotEqual(self.run_cli().returncode,0);self.assertFalse(self.out.exists())
    def test_symlink_directory_rejected(self):
        real=self.root/'real';real.mkdir();self.out.symlink_to(real,target_is_directory=True)
        self.assertNotEqual(self.run_cli('--overwrite').returncode,0);self.assertEqual(list(real.iterdir()),[])
    def test_symlink_parent_rejected(self):
        real=self.root/'real';real.mkdir();alias=self.root/'alias';alias.symlink_to(real,target_is_directory=True);self.out=alias/'clients'
        self.assertNotEqual(self.run_cli('--overwrite').returncode,0);self.assertEqual(list(real.iterdir()),[])
    def test_symlink_target_rejected_even_with_overwrite(self):
        self.out.mkdir();victim=self.root/'victim';victim.write_text('preserve');(self.out/'shadowrocket-reality.txt').symlink_to(victim)
        self.assertNotEqual(self.run_cli('--overwrite').returncode,0);self.assertEqual(victim.read_text(),'preserve');self.assertFalse((self.out/'clash-verge-reality.yaml').exists())
    def test_credential_material_rejected_without_leak(self):
        for key in ['private_key','password','server_credentials','unrecognized']:
            with self.subTest(key=key):
                self.material[key]='SENSITIVE_DO_NOT_PRINT';self.write_material();r=self.run_cli();self.assertNotEqual(r.returncode,0);self.assertNotIn('SENSITIVE_DO_NOT_PRINT',r.stdout+r.stderr);self.assertFalse(self.out.exists());del self.material[key]
    def test_invalid_metadata_rejected(self):
        invalid={
            'server':['user@host','https://example.com','[2001:db8::1]','2001:db8::1%eth0','999.1.2.3','bad..domain',''],
            'port':[0,65536,True,'443'],
            'uuid':['not-a-uuid','cf590485027a4fd6b1fcdc30a840e8f9'],
            'public_key':['','a'*42,'a'*44,'A'*42+'B'],
            'short_id':['a','aa'*9,'xz',''],
            'servername':['203.0.113.1','https://www.example.com','bad name'],
            'flow':['','unsupported'],
        }
        for field,values in invalid.items():
            for value in values:
                with self.subTest(field=field,value=value):
                    source=dict(self.material);source[field]=value
                    with self.assertRaises(module.BuildError):module.validate_material(source)
    def test_port_name_conflicts_rejected(self):
        for flags in [('--local-port','17893'),('--name','PROXY'),('--name','bad\nname'),('--test-port','0')]:
            with self.subTest(flags=flags):self.assertNotEqual(self.run_cli(*flags).returncode,0);self.assertFalse(self.out.exists())
    def test_unrelated_output_directory_is_not_modified(self):
        self.out.mkdir(mode=0o755);(self.out/'keep.txt').write_text('preserve');before=stat.S_IMODE(self.out.stat().st_mode)
        self.assertNotEqual(self.run_cli('--overwrite').returncode,0);self.assertEqual((self.out/'keep.txt').read_text(),'preserve');self.assertEqual(stat.S_IMODE(self.out.stat().st_mode),before)
    def test_missing_qr_dependency_does_not_publish(self):
        try:import qrcode
        except ImportError:pass
        else:self.skipTest('qrcode is installed; covered by PNG smoke test')
        result=self.run_cli('--qr');self.assertNotEqual(result.returncode,0);self.assertFalse(self.out.exists());self.assertIn('already installed qrcode',result.stderr)
    def test_optional_qr_has_png_signature_and_protected_mode(self):
        try:import qrcode
        except ImportError:self.skipTest('Optional qrcode is not installed')
        self.assert_ok(self.run_cli('--qr'));file=self.out/'shadowrocket-reality-qr.png';self.assertTrue(file.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'));self.assertEqual(stat.S_IMODE(file.stat().st_mode),0o600)

if __name__=='__main__':unittest.main(verbosity=2)
