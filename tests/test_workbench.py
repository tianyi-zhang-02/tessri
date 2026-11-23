"""Real repository/source capture, refresh boundaries and the loopback handoff protocol."""
import contextlib
import copy
import http.client
import io
import json
import os
from pathlib import Path
import re
import threading
from unittest import mock

from helpers import TempRepo, git, write_tree
from tessri import config, integration, reviewview, workbench
from tessri.cli import main


class WorkbenchTest(TempRepo):
    def setUp(self):
        super().setUp()
        git(self.root, 'init', '-q', '-b', 'main')
        write_tree(self.root, {'app.py':'from util import value\n', 'outside.py':'from util import value\n', 'util.py':'value = 1\n', '.gitignore':'__pycache__/\n'})
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'baseline')
        git(self.root, 'checkout', '-qb', 'change')
        (self.root/'util.py').unlink()
        (self.root/'app.py').write_text('value = 1\n', encoding='utf-8', newline='')

    def session(self):
        return workbench.Session(self.root, config.load(self.root), 'main')

    def test_real_source_contains_unchanged_importer_and_deleted_base_without_writes(self):
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.glob('*.py')}
        session=self.session()
        self.assertEqual(session.data['sources']['outside.py']['current']['text'], 'from util import value\n')
        self.assertEqual(session.data['sources']['util.py']['base']['text'], 'value = 1\n')
        self.assertIsNone(session.data['sources']['util.py']['current']['text'])
        finding=next(f for f in session.data['brief']['consequences']['findings'] if f['kind']=='dangling-import')
        self.assertEqual(session.data['related'][finding['id']], ['outside.py','util.py'])
        self.assertFalse(session.stale())
        self.assertEqual(before,{p.relative_to(self.root):p.read_bytes() for p in self.root.glob('*.py')})

    def test_source_preserves_line_endings_in_working_tree_and_base(self):
        texts = {'lf.py': 'value = "café"\n', 'crlf.py': 'value = "café"\r\n',
                 'cr.py': 'value = "café"\r'}
        for name, text in texts.items():
            (self.root/name).write_bytes(text.encode('utf-8'))
        git(self.root, '-c', 'core.autocrlf=false', 'add', '--', *texts)
        git(self.root, 'commit', '-qm', 'source line endings')
        for name, text in texts.items():
            with self.subTest(path=name):
                self.assertEqual(workbench.source(self.root, name), {'text': text, 'reason': None})
                self.assertEqual(workbench.source(self.root, name, 'HEAD'), {'text': text, 'reason': None})
                self.assertEqual((self.root/name).read_bytes(), text.encode('utf-8'))

    def test_content_change_with_preserved_size_and_mtime_is_stale_and_refresh_replaces_source(self):
        session=self.session()
        path=self.root/'app.py';stat=path.stat()
        path.write_text('value = 2\n', encoding='utf-8', newline='')
        os.utime(path, ns=(stat.st_atime_ns,stat.st_mtime_ns))
        self.assertTrue(session.stale())
        self.assertEqual(session.data['sources']['app.py']['current']['text'], 'value = 1\n')
        session.refresh()
        self.assertFalse(session.stale())
        self.assertEqual(session.data['sources']['app.py']['current']['text'], 'value = 2\n')

    def test_similarly_named_deleted_modules_do_not_cross_wire_finding_context(self):
        result=copy.deepcopy(self.session().data['brief'])
        result['check']['dangling_imports'].append({'deleted':'til.py','importers':['another.py']})
        data=workbench.assemble(self.root,result)
        self.assertEqual(data['related']['dangling-import:util.py'],['outside.py','util.py'])

    def test_snapshot_round_trips_hostile_repository_text_without_script_breakout(self):
        data=copy.deepcopy(self.session().data)
        attack='</script><img src="https://invalid.test" onerror="alert(1)">'
        data['brief']['repo']['name']=attack
        data['sources']['app.py']['current']['text']=attack
        text=reviewview.render(data)
        self.assertNotIn(attack,text)
        raw=re.search(r'<script id="review-data" type="application/json">(.*?)</script>',text,re.S).group(1)
        self.assertEqual(json.loads(raw)['sources']['app.py']['current']['text'],attack)
        self.assertEqual(text.count('<script'),2)

    def test_source_rejects_traversal_binary_large_and_symlink(self):
        self.assertIsNone(workbench.source(self.root,'../outside')['text'])
        (self.root/'binary').write_bytes(b'abc\0def')
        self.assertIn('Binary',workbench.source(self.root,'binary')['reason'])
        (self.root/'large').write_bytes(b'x'*(workbench.MAX_SOURCE_BYTES+1))
        self.assertIn('exceeds',workbench.source(self.root,'large')['reason'])
        try:
            (self.root/'link').symlink_to(self.root/'app.py')
        except OSError:
            return  # Windows without symlink permission: other boundaries still run.
        self.assertIn('Symlink',workbench.source(self.root,'link')['reason'])

    def test_checkout_root_is_canonicalized_before_source_containment_checks(self):
        noncanonical=self.root/'..'/self.root.name
        self.assertEqual(workbench.source(noncanonical,'app.py')['text'],'value = 1\n')

    def test_agent_export_is_one_shot_and_contains_real_source(self):
        target=Path(self._tmp.name)/'handoff.html'
        with mock.patch('tessri.workbench.serve') as serve, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['review','--repo',str(self.root),'--since','main','--out',str(target)]),0)
        serve.assert_not_called()
        text=target.read_text()
        self.assertIn('from util import value',text)
        self.assertIn('"live": false',text)

    def test_loopback_api_requires_capability_host_and_refresh_header(self):
        session=self.session()
        server=workbench.make_server(session)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def close():
            server.shutdown();thread.join(timeout=5);server.server_close()
        self.addCleanup(close)
        def request(path,method='GET',headers=None):
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
            try:
                conn.request(method,path,headers=headers or {})
                response=conn.getresponse();return response.status,response.read().decode(),dict(response.getheaders())
            finally:
                conn.close()
        prefix='/'+session.token+'/'
        self.assertEqual(request('/')[0],404)
        self.assertEqual(request(prefix,headers={'Host':'foreign.test'})[0],404)
        status,body,headers=request(prefix)
        self.assertEqual(status,200)
        self.assertIn('review-data',body)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(request(prefix+'../app.py')[0],404)
        self.assertEqual(json.loads(request(prefix+'status')[1]),{'stale':False})
        (self.root/'app.py').write_text('value = 3\n', encoding='utf-8', newline='')
        self.assertTrue(json.loads(request(prefix+'status')[1])['stale'])
        self.assertEqual(request(prefix+'refresh','POST')[0],403)
        self.assertEqual(request(prefix+'refresh','POST',{'X-Tessri-Review':session.token,'Origin':'https://foreign.test'})[0],403)
        result=request(prefix+'refresh','POST',{'X-Tessri-Review':session.token})
        self.assertEqual(result[0],200)
        self.assertEqual(json.loads(result[1])['sources']['app.py']['current']['text'],'value = 3\n')
        self.assertFalse(json.loads(request(prefix+'status')[1])['stale'])

    def test_all_three_agent_instructions_explain_the_same_nonblocking_handoff(self):
        result=integration.run(self.root,'install',['codex','claude','copilot','copilot-cli','mcp'])
        self.assertTrue(result['applied'])
        for profile in ('codex','claude','copilot'):
            text=(self.root/integration.PROFILES[profile].path).read_text()
            self.assertIn('tessri review --since <base> --out',text)
            self.assertIn('does not',text)
        cfg=json.loads((self.root/'.tessri/copilot-mcp.json').read_text())
        self.assertEqual(cfg['mcpServers']['tessri']['args'],['mcp'])
        self.assertEqual(cfg['mcpServers']['tessri']['tools'],['*'])
        integration.run(self.root,'remove',['copilot-cli'])
        self.assertFalse((self.root/'.tessri/copilot-mcp.json').exists())
