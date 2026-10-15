"""Steam Workshop downloader. Python 3.10+, standard library only."""
import argparse
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError
import uuid

ROOT = Path(__file__).resolve().parent
API = 'https://api.steampowered.com/ISteamRemoteStorage/{}/v1/'


def numeric(value):
    value = str(value)
    if not re.fullmatch(r'[1-9][0-9]{0,19}', value):
        raise ValueError(f'Expected a positive numeric Steam ID, got {value!r}')
    return value


def parse_sources(value):
    ids = []
    for token in re.split(r'[\s,;]+', str(value).strip()):
        if not token:
            continue
        if token.startswith('https://') or token.startswith('http://'):
            url = urlparse(token)
            if (url.hostname != 'steamcommunity.com' or url.username or url.password
                    or url.path.rstrip('/') not in ('/sharedfiles/filedetails', '/workshop/filedetails')):
                raise ValueError(f'Expected a Steam Workshop item or collection URL: {token!r}')
            values = parse_qs(url.query).get('id', [])
            if len(values) != 1:
                raise ValueError(f'Workshop URL needs exactly one id: {token!r}')
            token = values[0]
        ids.append(numeric(token))
    if not ids:
        raise ValueError('No Workshop IDs or URLs supplied.')
    return ids


def read_list(path):
    path = Path(path)
    content = path.read_text(encoding='utf-8-sig')
    app_id = None
    if path.suffix.lower() == '.json':
        data = json.loads(content)
        if isinstance(data, dict):
            app_id = numeric(data['appId']) if data.get('appId') else None
            entries = data.get('mods', data.get('items', []))
        else:
            entries = data
        if not isinstance(entries, list):
            raise ValueError('JSON must contain an array, or an object with a mods/items array.')
        values = []
        for entry in entries:
            if isinstance(entry, dict):
                entry = entry.get('id', entry.get('url', ''))
            values.extend(parse_sources(entry))
    else:
        values = []
        for line in content.splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                values.extend(parse_sources(line))
    if not values:
        raise ValueError(f'List is empty: {path}')
    return values, app_id


def steam_api(method, ids):
    count = 'collectioncount' if method == 'GetCollectionDetails' else 'itemcount'
    body = {count: str(len(ids))}
    body.update({f'publishedfileids[{i}]': item for i, item in enumerate(ids)})
    request = Request(API.format(method), data=urlencode(body).encode(),
                      headers={'User-Agent': 'SteamWorkshopDownloader/1.0'})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)['response']
            key = 'collectiondetails' if method == 'GetCollectionDetails' else 'publishedfiledetails'
            return payload.get(key, [])
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def resolve(sources, app_id=None, api=steam_api, skip_unavailable=False, recursive=False):
    """Expand actual collection children; item dependency links are not collections."""
    selected = numeric(app_id) if app_id else None
    cache, visited, leaves = {}, set(), []
    linked = []

    def prefetch(ids):
        missing = list(dict.fromkeys(i for i in ids if i not in cache))
        for offset in range(0, len(missing), 100):
            batch = missing[offset:offset + 100]
            details = {str(d['publishedfileid']): d for d in api('GetCollectionDetails', batch)}
            for item in batch:
                if item not in details:
                    raise ValueError(f'Steam returned no collection classification for {item}.')
                cache[item] = details[item]

    def visit(item, depth=0):
        if item in visited:
            return
        if depth > 50:
            raise ValueError('Collection nesting exceeds 50 levels.')
        visited.add(item)
        detail = cache[item]
        if detail.get('result') == 1:
            if depth > 0 and not recursive and item not in sources:
                linked.append(item)
                return
            children = [numeric(c['publishedfileid']) for c in
                        sorted(detail.get('children', []), key=lambda c: int(c.get('sortorder', 0)))]
            if not children:
                raise ValueError(f'Collection {item} is empty or inaccessible.')
            prefetch(children)
            for child in children:
                visit(child, depth + 1)
        else:
            leaves.append(item)

    sources = [numeric(i) for i in sources]
    prefetch(sources)
    for item in sources:
        visit(item)
    mods, unavailable = [], []
    for offset in range(0, len(leaves), 100):
        batch = leaves[offset:offset + 100]
        details = {str(d['publishedfileid']): d for d in api('GetPublishedFileDetails', batch)}
        for item in batch:
            detail = details.get(item, {})
            if detail.get('result') != 1:
                if skip_unavailable and detail:
                    unavailable.append({'id': item, 'result': detail.get('result')})
                    continue
                raise ValueError(f'Workshop item {item} is unavailable (Steam result {detail.get("result", "missing")}).')
            actual = numeric(detail.get('consumer_app_id', 0))
            if selected is None:
                selected = actual
            if actual != selected:
                raise ValueError(f'Item {item} belongs to App ID {actual}, not selected App ID {selected}.')
            mods.append({'id': item, 'name': detail.get('title', item),
                         'url': f'https://steamcommunity.com/sharedfiles/filedetails/?id={item}'})
    if not mods:
        raise ValueError('No downloadable items resolved.')
    return {'appId': selected, 'sources': sources, 'unavailable': unavailable, 'linkedCollections': linked,
            'resolvedAt': datetime.now(timezone.utc).isoformat(), 'mods': mods}


def prepare(plan, output):
    run = Path(output) / numeric(plan['appId']) / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
    run.mkdir(parents=True)
    (run / 'manifest.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
    app = numeric(plan['appId'])
    commands = ['@ShutdownOnFailedCommand 0', '@NoPromptForPassword 0', 'app_info_update 1']
    commands += [f'workshop_download_item {app} {numeric(m["id"])} validate' for m in plan['mods']]
    commands += ['quit']
    (run / 'workshop-downloads.txt').write_text('\n'.join(commands) + '\n', encoding='ascii')
    return run


def verify(plan, steam_root, output):
    outcomes = {}
    for match in re.finditer(r'Success\. Downloaded item (\d+)\b|ERROR! Download item (\d+) failed([^\r\n]*)', output):
        if match[1]:
            outcomes[match[1]] = 'OK'
        else:
            outcomes[match[2]] = 'Failed' + match[3].strip()
    rows = []
    for mod in plan['mods']:
        path = Path(steam_root) / 'steamapps/workshop/content' / plan['appId'] / mod['id']
        files = [p for p in path.rglob('*') if p.is_file()] if path.is_dir() else []
        size = sum(p.stat().st_size for p in files)
        result = outcomes.get(mod['id'], 'Not attempted or no result')
        status = ('Verified downloaded' if result == 'OK' and size > 0 else
                  'Files present; download not verified' if size > 0 else 'Not downloaded')
        rows.append({'Id': mod['id'], 'Name': mod['name'], 'Status': status,
                     'SteamResult': result, 'Files': len(files), 'Bytes': size,
                     'Path': str(path), 'Url': mod['url']})
    for item in plan.get('unavailable', []):
        rows.append({'Id': item['id'], 'Name': '(unavailable)', 'Status': 'Unavailable',
                     'SteamResult': f'Metadata result {item["result"]}', 'Files': 0, 'Bytes': 0,
                     'Path': '', 'Url': f'https://steamcommunity.com/sharedfiles/filedetails/?id={item["id"]}'})
    return rows


def download(plan, steamcmd, user, run, timeout=0):
    steamcmd = Path(steamcmd).resolve()
    if not steamcmd.is_file():
        raise ValueError(f'SteamCMD not found: {steamcmd}. Install SteamCMD or pass --steamcmd PATH.')
    if not re.fullmatch(r'[A-Za-z0-9_]+', user):
        raise ValueError('Steam username must contain only letters, digits, or underscores.')
    lock = steamcmd.parent / '.workshop-downloader.lock'
    try:
        handle = lock.open('x')
    except FileExistsError:
        raise ValueError(f'Another download may be using SteamCMD. If none is running, remove {lock}.')
    output, interrupted, expired = [], False, threading.Event()
    process, timer = None, None
    try:
        handle.write(str(run))
        handle.close()
        # No shell and no password argument. SteamCMD reads credentials from inherited stdin.
        process = subprocess.Popen([str(steamcmd), '+login', user, '+runscript', str((run / 'workshop-downloads.txt').resolve())],
                                   cwd=steamcmd.parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace', bufsize=1)
        if timeout:
            def kill():
                expired.set()
                process.kill()
            timer = threading.Timer(timeout, kill)
            timer.daemon = True
            timer.start()
        try:
            # Prompts may have no newline. Display each character immediately
            # so password / Steam Guard prompts remain usable interactively.
            while True:
                character = process.stdout.read(1)
                if not character:
                    break
                output.append(character)
                print(character, end='', flush=True)
            process.wait()
        except KeyboardInterrupt:
            interrupted = True
            process.terminate()
            process.wait()
    finally:
        if timer:
            timer.cancel()
        if process and process.poll() is None:
            process.kill()
            process.wait()
        if process and process.stdout:
            process.stdout.close()
        handle.close()
        lock.unlink(missing_ok=True)
    transcript = ''.join(output)
    (run / 'steamcmd.log').write_text(transcript, encoding='utf-8')
    rows = verify(plan, steamcmd.parent, transcript)
    with (run / 'download-report.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    good = sum(r['Status'] == 'Verified downloaded' for r in rows)
    summary = {'appId': plan['appId'], 'total': len(rows), 'verified': good,
               'steamExitCode': process.returncode, 'timedOut': expired.is_set(), 'interrupted': interrupted}
    (run / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f'\nVerified downloads: {good} / {len(rows)}. SteamCMD exit code: {process.returncode}')
    print(f'Report: {run / "download-report.csv"}')
    return 0 if good == len(rows) and process.returncode == 0 and not expired.is_set() and not interrupted else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='*', help='Workshop IDs or item/collection URLs; comma-separated values also accepted')
    parser.add_argument('--app-id', help='Steam game App ID; inferred from items when omitted')
    parser.add_argument('--list', action='append', default=[], dest='lists', help='Text or JSON list file; repeatable')
    parser.add_argument('--steam-user', default='anonymous', help='Steam account name; credentials entered only in SteamCMD')
    parser.add_argument('--steamcmd', type=Path, default=ROOT / 'steamcmd.exe')
    parser.add_argument('--output', type=Path, default=ROOT / 'runs')
    parser.add_argument('--prepare-only', action='store_true', help='Resolve and write manifest/commands without downloading')
    parser.add_argument('--skip-unavailable', action='store_true', help='Record inaccessible entries and continue with available items')
    parser.add_argument('--recursive-collections', action='store_true', help='Also expand linked/nested collections (may be alternative mod sets)')
    parser.add_argument('--timeout-seconds', type=int, default=0, help='Stop SteamCMD after this many seconds; 0 disables timeout')
    args = parser.parse_args(argv)
    try:
        if args.timeout_seconds < 0:
            raise ValueError('--timeout-seconds cannot be negative.')
        ids, app = [], numeric(args.app_id) if args.app_id else None
        for source in args.sources:
            ids.extend(parse_sources(source))
        for path in args.lists:
            entries, list_app = read_list(path)
            if app and list_app and app != list_app:
                raise ValueError(f'List App ID {list_app} conflicts with selected App ID {app}.')
            app = app or list_app
            ids.extend(entries)
        if not ids:
            raise ValueError('Supply a Workshop ID/URL or --list FILE. Run with --help for arguments.')
        plan = resolve(ids, app, skip_unavailable=args.skip_unavailable, recursive=args.recursive_collections)
        run = prepare(plan, args.output.resolve())
        print(f'Resolved {len(plan["mods"])} items for App ID {plan["appId"]}. Run folder: {run}', flush=True)
        for item in plan['unavailable']:
            print(f'Unavailable item {item["id"]}: Steam metadata result {item["result"]}', flush=True)
        if plan['linkedCollections']:
            print('Linked collections excluded; use --recursive-collections to include: ' + ', '.join(plan['linkedCollections']), flush=True)
        if args.prepare_only:
            return 0
        return download(plan, args.steamcmd, args.steam_user, run, args.timeout_seconds)
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
