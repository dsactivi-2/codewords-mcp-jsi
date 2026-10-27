"""Real MySQL integration tests; no CodeWords/CRM connections or production credentials.

The runtime module starts external infrastructure on import. Load its actual AST
functions without the registration decorators; only the DB transport and URL
fetch boundary are replaced. SQL and transaction logic execute in real MySQL.
"""
import ast
import asyncio
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = os.environ.get('JOBSTEP_MYSQL_CONTAINER', '')


class ToolError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def mysql(sql, database='jobstep_test'):
    proc = subprocess.run(
        ['docker', 'exec', '-i', CONTAINER, 'mysql', '--batch', '--raw', '--skip-column-names', '-u', 'root', database],
        input=sql, text=True, capture_output=True,
    )
    if proc.returncode:
        raise ToolError(proc.stderr.strip())
    return proc.stdout


def query(sql):
    # mysql --xml preserves column names and NULL without a driver dependency.
    import xml.etree.ElementTree as ET
    proc = subprocess.run(
        ['docker', 'exec', '-i', CONTAINER, 'mysql', '--xml', '-u', 'root', 'jobstep_test'],
        input=sql, text=True, capture_output=True,
    )
    if proc.returncode:
        raise ToolError(proc.stderr.strip())
    if not proc.stdout.strip():
        return []
    # CALL may return multiple resultsets; accept the data resultsets, not OK packets.
    document = '<results>' + proc.stdout.replace('<?xml version="1.0"?>', '') + '</results>'
    rows = []
    for row in ET.fromstring(document).iter('row'):
        value = {}
        for field in row:
            text = field.text
            value[field.attrib['name']] = None if text is None else (int(text) if text.lstrip('-').isdigit() else text)
        rows.append(value)
    return rows


def load_tools(db, gate):
    tree = ast.parse((ROOT / 'jobstep_mcp.py').read_text())
    wanted = {'_esc', '_num', '_limit', '_kandidat_oder_fehler', '_dokumenttyp',
              '_intake_result', 'unterlagen_soll', 'kandidat_dokumente', 'unterlage_anlegen',
              '_p', '_spec'}
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            node.decorator_list = []
            node.returns = None
            for arg in node.args.args + node.args.kwonlyargs:
                arg.annotation = None
            body.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id in {'DOC_STATUS', 'TOOL_SPECS', 'SERVICE_VERSION', 'MAX_ROWS', 'HARD_LIMIT'} for t in targets):
                body.append(node)
    env = {'db': db, 'datei_pruefen': gate, 'McpError': ToolError, 'asyncio': asyncio,
           'Any': object, 'logger': SimpleNamespace(info=lambda *a, **kw: None)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), str(ROOT / 'jobstep_mcp.py'), 'exec'), env)
    return SimpleNamespace(**env)


@unittest.skipUnless(CONTAINER, 'Set JOBSTEP_MYSQL_CONTAINER to an isolated disposable MySQL container')
class IntakeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        if not CONTAINER.startswith('codex-jobstep-intake-test-'):
            raise RuntimeError('Refusing a non-test container')
        info = json.loads(subprocess.check_output(['docker', 'inspect', CONTAINER], text=True))[0]
        if info['HostConfig']['NetworkMode'] != 'none' or any(m['Type'] == 'bind' for m in info.get('Mounts', [])):
            raise RuntimeError('Test container must have no network or host bind mounts')

    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 10
        mysql('DROP DATABASE IF EXISTS jobstep_test; CREATE DATABASE jobstep_test;', database='mysql')
        mysql((ROOT / 'tests/fixtures/schema.sql').read_text())
        migration = ROOT / 'migrations/001_document_replacement.sql'
        if migration.exists():
            mysql(migration.read_text())
        self.gate_ok = True
        self.timeout_after_commit = False
        async def db(sql):
            result = await asyncio.to_thread(query, sql)
            if sql.startswith('CALL ') and self.timeout_after_commit:
                self.timeout_after_commit = False
                raise ToolError('synthetic timeout after commit')
            return result
        async def gate(url):
            return {'success': True, 'erreichbar': self.gate_ok, 'http_status': 200 if self.gate_ok else 404}
        self.tools = load_tools(db, gate)

    def old(self, status=24, candidate=100, order=30, requirement=10):
        mysql(f"INSERT INTO idk_pp_documents (doc_file_name,doc_candidate_id,doc_nalog_id,doc_nrd_id,doc_status) VALUES ('https://files.example/old.pdf',{candidate},{order},{requirement},{status});")
        did = query('SELECT MAX(doc_id) id FROM idk_pp_documents')[0]['id']
        mysql(f"INSERT INTO idk_pp_documents_status_logs (dsl_doc_id,dsl_doc_status,dsl_comment) VALUES ({did},{status},'Human: original history');")
        return did

    async def intake(self, **kw):
        args = dict(kandidat_id=100, nalog_id=30, doc_type_id=20, datei_url='https://files.example/new.pdf')
        args.update(kw)
        return await self.tools.unterlage_anlegen(**args)

    def counts(self):
        return tuple(query('SELECT COUNT(*) n FROM ' + table)[0]['n'] for table in
                     ['idk_pp_documents', 'idk_documents', 'idk_pp_documents_status_logs'])

    async def test_summary_uses_new_pass_not_max_status(self):
        self.old(24)
        mysql("INSERT INTO idk_pp_documents (doc_file_name,doc_candidate_id,doc_nalog_id,doc_nrd_id,doc_status) VALUES ('https://files.example/new.pdf',100,30,10,3);")
        result = await self.tools.unterlagen_soll(100, 30)
        passport = next(x for x in result['unterlagen'] if x['doc_type_id'] == 20)
        self.assertEqual(passport['status'], 3)
        self.assertFalse(passport['fehlt'])

    async def test_rejected_pass_is_missing_until_replaced(self):
        self.old(24)
        passport = next(x for x in (await self.tools.unterlagen_soll(100, 30))['unterlagen'] if x['doc_type_id'] == 20)
        self.assertTrue(passport['fehlt'])

    async def test_replacement_keeps_history_and_links_both_directions(self):
        old = self.old(24)
        result = await self.intake(ersetzt_doc_id=old)
        new = result['doc_id']
        self.assertNotEqual(new, old)
        self.assertEqual(result['ersetzt_doc_id'], old)
        passport = next(x for x in (await self.tools.unterlagen_soll(100, 30))['unterlagen'] if x['doc_type_id'] == 20)
        self.assertEqual((passport['doc_id'], passport['status'], passport['pruefung_offen']), (new, 3, True))
        docs = (await self.tools.kandidat_dokumente(100))['unterlagen_verfahren']
        by_id = {d['doc_id']: d for d in docs}
        self.assertEqual(by_id[old]['ersetzt_durch_doc_id'], new)
        self.assertEqual(by_id[old]['doc_status'], 24)
        self.assertEqual(by_id[new]['ersetzt_doc_id'], old)
        self.assertEqual(query(f'SELECT dsl_comment FROM idk_pp_documents_status_logs WHERE dsl_doc_id={old}'), [{'dsl_comment': 'Human: original history'}])

    async def test_defective_pass_can_be_replaced(self):
        old = self.old(21)
        self.assertEqual((await self.intake(ersetzt_doc_id=old))['ersetzt_doc_id'], old)

    async def test_identical_retry_creates_no_duplicate(self):
        old = self.old()
        first = await self.intake(ersetzt_doc_id=old)
        second = await self.intake(ersetzt_doc_id=old)
        self.assertEqual(first['doc_id'], second['doc_id'])
        self.assertTrue(second['wiederverwendet'])
        self.assertEqual(self.counts(), (2, 1, 2))

    async def test_timeout_after_commit_can_be_retried_safely(self):
        old = self.old()
        self.timeout_after_commit = True
        with self.assertRaisesRegex(ToolError, 'timeout'):
            await self.intake(ersetzt_doc_id=old)
        result = await self.intake(ersetzt_doc_id=old)
        self.assertTrue(result['wiederverwendet'])
        self.assertEqual(self.counts(), (2, 1, 2))

    async def test_concurrent_identical_uploads_have_one_result(self):
        old = self.old()
        a, b = await asyncio.gather(self.intake(ersetzt_doc_id=old), self.intake(ersetzt_doc_id=old))
        self.assertEqual(a['doc_id'], b['doc_id'])
        self.assertEqual(self.counts(), (2, 1, 2))

    async def test_concurrent_different_files_do_not_both_win(self):
        old = self.old()
        outcomes = await asyncio.gather(self.intake(ersetzt_doc_id=old), self.intake(ersetzt_doc_id=old, datei_url='https://files.example/other.pdf'), return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in outcomes), 1)
        self.assertEqual(self.counts(), (2, 1, 2))

    async def test_normal_intake_retry_is_idempotent(self):
        a, b = await asyncio.gather(self.intake(), self.intake())
        self.assertEqual(a['doc_id'], b['doc_id'])
        self.assertEqual(self.counts(), (1, 1, 1))

    async def test_blocking_statuses_and_pending_review_stop_intake(self):
        for status in [3, 6, 9, 12, 15, 18, 27, 99]:
            with self.subTest(status=status):
                mysql('DELETE FROM idk_pp_documents_status_logs; DELETE FROM idk_pp_documents;')
                self.old(status)
                with self.assertRaises(ToolError):
                    await self.intake()
                self.assertEqual(self.counts(), (1, 0, 1))

    async def test_blocker_older_than_first_page_still_blocks(self):
        self.old(18)
        for _ in range(45):
            self.old(24)
        old = query('SELECT MAX(doc_id) id FROM idk_pp_documents')[0]['id']
        with self.assertRaises(ToolError):
            await self.intake(ersetzt_doc_id=old)
        self.assertEqual(self.counts(), (46, 0, 46))

    async def test_wrong_predecessor_candidate_order_or_type_rejected(self):
        for candidate, order, requirement in [(101,30,10),(100,31,12),(100,30,11)]:
            with self.subTest(candidate=candidate, order=order, requirement=requirement):
                mysql('DELETE FROM idk_pp_documents_status_logs; DELETE FROM idk_pp_documents;')
                old = self.old(24,candidate,order,requirement)
                with self.assertRaises(ToolError):
                    await self.intake(ersetzt_doc_id=old)
                self.assertEqual(self.counts(), (1,0,1))

    async def test_replacement_must_be_explicit(self):
        self.old(24)
        with self.assertRaises(ToolError):
            await self.intake()
        self.assertEqual(self.counts(), (1,0,1))

    async def test_unreachable_file_never_written(self):
        self.gate_ok = False
        with self.assertRaises(ToolError):
            await self.intake()
        self.assertEqual(self.counts(), (0,0,0))

    async def test_non_upload_start_status_is_rejected(self):
        with self.assertRaises(ToolError):
            await self.intake(doc_status=6)
        self.assertEqual(self.counts(), (0,0,0))

    async def test_wrong_requirement_is_rejected(self):
        with self.assertRaises(ToolError):
            await self.intake(nrd_id=11)
        self.assertEqual(self.counts(), (0,0,0))

    async def test_failure_in_history_rolls_back_document_and_file(self):
        mysql("CREATE TRIGGER synthetic_history_failure BEFORE INSERT ON idk_pp_documents_status_logs FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='synthetic history failure';")
        with self.assertRaises(ToolError):
            await self.intake()
        self.assertEqual(self.counts(), (0,0,0))

    async def test_replacement_chain_shows_latest_only(self):
        old = self.old(24)
        middle = (await self.intake(ersetzt_doc_id=old))['doc_id']
        mysql(f'UPDATE idk_pp_documents SET doc_status=21 WHERE doc_id={middle};')
        last = (await self.intake(ersetzt_doc_id=middle, datei_url='https://files.example/newest.pdf'))['doc_id']
        passport = next(x for x in (await self.tools.unterlagen_soll(100,30))['unterlagen'] if x['doc_type_id']==20)
        self.assertEqual((passport['doc_id'],passport['status']), (last,3))
        with self.assertRaises(ToolError):
            await self.intake(ersetzt_doc_id=old, datei_url='https://files.example/stale.pdf')
        self.assertEqual(self.counts(), (3,2,3))

    async def test_response_and_file_icon_remain_compatible(self):
        result = await self.intake()
        self.assertEqual((result['status'], result['unterlagentyp']), ('Hochgeladen', 'Putovnica'))
        self.assertEqual(query('SELECT document_icon FROM idk_documents'), [{'document_icon': 'pdf'}])

    async def test_comment_and_url_are_data_under_no_backslash_escapes(self):
        async def db(sql):
            return await asyncio.to_thread(query, "SET SESSION sql_mode='STRICT_TRANS_TABLES,NO_BACKSLASH_ESCAPES';" + sql)
        async def gate(url):
            return {'erreichbar': True}
        self.tools = load_tools(db, gate)
        comment = "O'Brien; -- / * synthetic comment"
        url = "https://files.example/O'Brien.pdf?value=;--"
        result = await self.intake(datei_url=url, kommentar=comment)
        self.assertGreater(result['doc_id'], 0)
        self.assertEqual(query('SELECT document_desc, document_file FROM idk_documents'), [{'document_desc':comment,'document_file':url}])

    async def test_non_required_document_remains_typed(self):
        mysql('DELETE FROM idk_pp_nalog_required_documents WHERE nrd_id=10;')
        first = await self.intake()
        docs = (await self.tools.kandidat_dokumente(100))['unterlagen_verfahren']
        self.assertEqual(docs[0]['doc_type_id'], 20)
        self.assertEqual((await self.intake())['doc_id'], first['doc_id'])

    async def test_unmapped_legacy_document_fails_closed(self):
        self.old(24,requirement='NULL')
        with self.assertRaises(ToolError):
            await self.intake()
        self.assertEqual(self.counts(), (1,0,1))

    async def test_other_candidate_or_order_does_not_block(self):
        self.old(18,candidate=101,order=31,requirement=12)
        self.assertGreater((await self.intake())['doc_id'], 0)

    async def test_replay_does_not_reset_human_review_status(self):
        first = await self.intake()
        mysql(f"UPDATE idk_pp_documents SET doc_status=6 WHERE doc_id={first['doc_id']};")
        second = await self.intake()
        self.assertEqual(second['status_id'], 6)
        self.assertEqual(self.counts(), (1,1,1))

    async def test_missing_migration_fails_before_writes(self):
        mysql('DROP PROCEDURE jobstep_document_intake_v1;')
        with self.assertRaises(ToolError):
            await self.intake()
        self.assertEqual(self.counts(), (0,0,0))

    async def test_registered_mcp_file_checker_is_callable_via_fn(self):
        async def gate(url):
            return {'erreichbar': True}
        self.tools.unterlage_anlegen.__globals__['datei_pruefen'] = SimpleNamespace(fn=gate)
        self.assertGreater((await self.intake())['doc_id'], 0)

    async def test_multiple_requirements_need_explicit_position(self):
        mysql('INSERT INTO idk_pp_nalog_required_documents VALUES(13,20,30,1);')
        with self.assertRaises(ToolError):
            await self.intake()
        self.assertGreater((await self.intake(nrd_id=10))['doc_id'], 0)

    async def test_multiple_legacy_rejections_require_clarification(self):
        self.old(24)
        old = self.old(21)
        with self.assertRaises(ToolError):
            await self.intake(ersetzt_doc_id=old)
        self.assertEqual(self.counts(), (2,0,2))

    async def test_replacement_cannot_switch_requirement(self):
        old = self.old(24)
        mysql('INSERT INTO idk_pp_nalog_required_documents VALUES(13,20,30,1);')
        with self.assertRaises(ToolError):
            await self.intake(ersetzt_doc_id=old,nrd_id=13)
        self.assertEqual(self.counts(), (1,0,1))

    async def test_parallel_status_change_cannot_rewrite_replaced_pass(self):
        old = self.old(24)
        mysql("DELIMITER $$\nCREATE TRIGGER synthetic_intake_pause BEFORE INSERT ON idk_pp_documents FOR EACH ROW BEGIN IF NEW.doc_replaces_id IS NOT NULL THEN DO SLEEP(1); END IF; END$$\nDELIMITER ;\n")
        replacement = asyncio.create_task(self.intake(ersetzt_doc_id=old))
        for _ in range(100):
            paused = await asyncio.to_thread(query, "SELECT COUNT(*) n FROM information_schema.processlist WHERE STATE='User sleep' AND DB='jobstep_test';")
            if paused[0]['n']:
                break
            await asyncio.sleep(0.02)
        else:
            replacement.cancel()
            self.fail('Synthetic pause was not reached')
        async def change_status():
            return await asyncio.to_thread(mysql, f'UPDATE idk_pp_documents SET doc_status=9 WHERE doc_id={old};')
        update = asyncio.create_task(change_status())
        result, status_result = await asyncio.gather(replacement, update, return_exceptions=True)
        self.assertIsInstance(result, dict)
        self.assertIsInstance(status_result, ToolError)
        self.assertEqual(query(f'SELECT doc_status FROM idk_pp_documents WHERE doc_id={old}'), [{'doc_status':24}])
        self.assertEqual(self.counts(), (2,1,2))

    async def test_replaced_pass_file_is_immutable(self):
        old = self.old(24)
        await self.intake(ersetzt_doc_id=old)
        with self.assertRaises(ToolError):
            mysql(f"UPDATE idk_pp_documents SET doc_file_name='https://files.example/mutated.pdf' WHERE doc_id={old};")
        self.assertEqual(query(f'SELECT doc_file_name FROM idk_pp_documents WHERE doc_id={old}'), [{'doc_file_name':'https://files.example/old.pdf'}])

    async def test_status_change_that_wins_first_blocks_replacement(self):
        old = self.old(24)
        status_change = asyncio.create_task(asyncio.to_thread(mysql,
            f'START TRANSACTION; UPDATE idk_pp_documents SET doc_status=9 WHERE doc_id={old}; DO SLEEP(1); COMMIT;'))
        for _ in range(100):
            paused = await asyncio.to_thread(query, "SELECT COUNT(*) n FROM information_schema.processlist WHERE STATE='User sleep' AND DB='jobstep_test';")
            if paused[0]['n']:
                break
            await asyncio.sleep(0.02)
        else:
            await status_change
            self.fail('Synthetic status-change pause was not reached')
        with self.assertRaises(ToolError):
            await self.intake(ersetzt_doc_id=old)
        await status_change
        self.assertEqual(self.counts(), (1,0,1))
        self.assertEqual(query(f'SELECT doc_status FROM idk_pp_documents WHERE doc_id={old}'), [{'doc_status':9}])


class ResultShapeTests(unittest.TestCase):
    def test_nested_call_rows_are_recognized(self):
        tools = load_tools(None,None)
        row = {'intake_version':1,'doc_id':42}
        self.assertEqual(tools._intake_result([[row], {'affectedRows':0}]), row)

    def test_ok_packets_or_ambiguous_rows_are_not_success(self):
        tools = load_tools(None,None)
        for result in [[],[{'affectedRows':1}],[[{'intake_version':1,'doc_id':1},{'intake_version':1,'doc_id':2}]]]:
            with self.subTest(result=result):
                with self.assertRaises(ToolError):
                    tools._intake_result(result)


if __name__ == '__main__':
    unittest.main()
