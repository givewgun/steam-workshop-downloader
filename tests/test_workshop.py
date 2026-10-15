import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workshop', ROOT / 'workshop.py')
workshop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workshop)


class WorkshopTests(unittest.TestCase):
    def test_sources_accept_ids_urls_and_reject_command_injection(self):
        self.assertEqual(workshop.parse_sources('123, https://steamcommunity.com/sharedfiles/filedetails/?id=456&searchtext=a;123'), ['123', '456', '123'])
        for value in ['123\nquit', 'https://evil.example/?id=123', '0', '-1', '123abc']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                workshop.parse_sources(value)

    def test_legacy_json_and_text_lists(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'mods.json'
            path.write_text(json.dumps({'appId': '255710', 'mods': [{'id': '123'}, {'url': 'https://steamcommunity.com/sharedfiles/filedetails/?id=456'}]}))
            self.assertEqual(workshop.read_list(path), (['123', '456'], '255710'))
            path = Path(folder) / 'mods.txt'
            path.write_text('# my list\n123\n\n456,789\n')
            self.assertEqual(workshop.read_list(path), (['123', '456', '789'], None))

    def test_nested_collections_preserve_order_and_deduplicate_cycles(self):
        collections = {'100': ['200', '300', '200'], '300': ['400', '100']}
        def api(method, ids):
            if method == 'GetCollectionDetails':
                return [{'publishedfileid': i, 'result': 1 if i in collections else 9,
                         'children': [{'publishedfileid': c, 'sortorder': n} for n, c in enumerate(collections.get(i, []))]} for i in ids]
            return [{'publishedfileid': i, 'result': 1, 'consumer_app_id': 1158310, 'title': 'Mod ' + i} for i in ids]
        plan = workshop.resolve(['100', '400'], '1158310', api, recursive=True)
        self.assertEqual([m['id'] for m in plan['mods']], ['200', '400'])
        self.assertEqual(plan['appId'], '1158310')
        direct = workshop.resolve(['100'], '1158310', api)
        self.assertEqual([m['id'] for m in direct['mods']], ['200'])
        self.assertEqual(direct['linkedCollections'], ['300'])
        explicit = workshop.resolve(['100', '300'], '1158310', api)
        self.assertEqual([m['id'] for m in explicit['mods']], ['200', '400'])

    def test_wrong_game_and_inaccessible_items_fail_before_download(self):
        def api(method, ids):
            if method == 'GetCollectionDetails':
                return [{'publishedfileid': i, 'result': 9} for i in ids]
            return [{'publishedfileid': i, 'result': 1, 'consumer_app_id': 255710, 'title': 'A mod'} for i in ids]
        with self.assertRaisesRegex(ValueError, '255710'):
            workshop.resolve(['200'], '1158310', api)
        self.assertEqual(workshop.resolve(['200'], None, api)['appId'], '255710')
        with self.assertRaises(ValueError):
            workshop.resolve(['200'], None, lambda method, ids: [])

    def test_existing_files_need_fresh_success_and_nonempty_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            item = root / 'steamapps/workshop/content/1158310/200'
            item.mkdir(parents=True)
            (item / 'mod.txt').write_text('payload')
            plan = {'appId': '1158310', 'mods': [{'id': '200', 'name': 'Mod', 'url': ''}, {'id': '300', 'name': 'Empty', 'url': ''}]}
            rows = workshop.verify(plan, root, "Success. Downloaded item 300 to x\nERROR! Download item 200 failed (Failure).")
            self.assertEqual([r['Status'] for r in rows], ['Files present; download not verified', 'Not downloaded'])
            rows = workshop.verify(plan, root, 'Success. Downloaded item 200 to x\n')
            self.assertEqual(rows[0]['Status'], 'Verified downloaded')
            rows = workshop.verify(plan, root, 'Success. Downloaded item 200 to x\nERROR! Download item 200 failed (Failure).')
            self.assertNotEqual(rows[0]['Status'], 'Verified downloaded')

    def test_unavailable_collection_member_is_recorded_when_skipping(self):
        def api(method, ids):
            if method == 'GetCollectionDetails':
                return [{'publishedfileid': i, 'result': 9} for i in ids]
            return [{'publishedfileid': '200', 'result': 1, 'consumer_app_id': 1158310, 'title': 'One'},
                    {'publishedfileid': '300', 'result': 9}]
        plan = workshop.resolve(['200', '300'], '1158310', api, skip_unavailable=True)
        self.assertEqual([m['id'] for m in plan['mods']], ['200'])
        self.assertEqual(plan['unavailable'][0]['id'], '300')
        rows = workshop.verify(plan, Path('unused'), '')
        self.assertEqual(rows[-1]['Status'], 'Unavailable')

    def test_prepare_writes_only_selected_app_commands_without_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            plan = {'appId': '1158310', 'mods': [{'id': '200', 'name': 'One', 'url': ''}]}
            run = workshop.prepare(plan, Path(folder))
            commands = (run / 'workshop-downloads.txt').read_text()
            self.assertIn('workshop_download_item 1158310 200 validate', commands)
            self.assertNotIn('login', commands)
            self.assertEqual(json.loads((run / 'manifest.json').read_text())['mods'][0]['id'], '200')

    def test_download_exit_code_and_report_depend_on_item_success(self):
        # Replace only the external Steam executable with a real child process.
        real_popen = subprocess.Popen
        for success in (True, False):
            with self.subTest(success=success), tempfile.TemporaryDirectory(prefix='workshop test ') as folder:
                root = Path(folder)
                executable = root / 'steamcmd.exe'
                executable.touch()
                item = root / 'steamapps/workshop/content/1158310/200'
                item.mkdir(parents=True)
                (item / 'mod.txt').write_text('payload')
                plan = {'appId': '1158310', 'mods': [{'id': '200', 'name': 'One', 'url': ''}]}
                run = workshop.prepare(plan, root / 'reports')
                message = 'Success. Downloaded item 200 to x' if success else 'ERROR! Download item 200 failed (Failure).'
                def launch(args, **kwargs):
                    return real_popen([sys.executable, '-c', f'print({message!r})'], **kwargs)
                with patch.object(workshop.subprocess, 'Popen', side_effect=launch):
                    result = workshop.download(plan, executable, 'anonymous', run)
                self.assertEqual(result, 0 if success else 1)
                summary = json.loads((run / 'summary.json').read_text())
                self.assertEqual(summary['verified'], 1 if success else 0)
                self.assertEqual(summary['steamExitCode'], 0)
                self.assertFalse((root / '.workshop-downloader.lock').exists())
                self.assertTrue((run / 'download-report.csv').is_file())


if __name__ == '__main__':
    unittest.main()
