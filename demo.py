"""Interactive live AWS demonstration. Run: python demo.py

Press Enter before each of seven demo functions; type q to finish safely.
Use --auto for an unattended run, or --list to show the steps.
Use --sections metrics,flink,hpa to repeat only the new platform demonstrations.
Artifacts remain in digital-library/.local/demo-report.json and demo-runs/ folders.
Only labeled Kafka fixtures and demo business records are created. Flink/YARN jobs
and audit-owned forwards/load threads are stopped in finally blocks. No infrastructure
is provisioned and HPA targets/min/max are never changed by the test.
"""

import argparse
import base64
from collections import Counter, deque
from contextlib import contextmanager
from datetime import timedelta
import hashlib
from http.client import HTTPConnection, HTTPSConnection, HTTPException
import math
import re
import socket
import subprocess
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

REPOSITORY = Path(__file__).resolve().parent
PROJECT = REPOSITORY / 'digital-library'
CONFIG_ROOT = PROJECT / '.local'
DEMO_STEPS = {
    'api': ('REST APIs and private S3', 'Validate all 23 business endpoints, FIFO holds, loans, returns and cover storage.'),
    'grpc': ('Member gRPC and ZooKeeper', 'Call real gRPC eligibility and check the audited reservation lock path.'),
    'fine': ('Positive overdue fines', 'Use deployed Fine code with isolated SQLite; production loan dates are untouched.'),
    'notifications': ('Automatic email delivery', 'Verify checkout/return and explicit SES simulator delivery, then suppress duplicate IDs.'),
    'metrics': ('Prometheus metrics', 'Check all seven scrape targets, request rates, p95 latency, CPU and HPA metrics.'),
    'flink': ('Kafka and Flink processing', 'Run the jar on existing EMR; check exact window output and a completed checkpoint.'),
    'hpa': ('Autoscaling under sustained load', 'Watch both HPAs scale 1 -> 2 -> 1 under bounded read-only HTTP load; allow several minutes.'),
}
PARSER = argparse.ArgumentParser(description='Press Enter before each live AWS demo. Run from any directory. Uses the existing EKS/EMR deployment; provisions no infrastructure.')
PARSER.add_argument('--sections', default=','.join(DEMO_STEPS), help='Comma-separated demos; notifications requires api earlier in the same run.')
PARSER.add_argument('--auto', action='store_true', help='Run selected demos without Enter prompts.')
PARSER.add_argument('--list', action='store_true', help='List demo steps without contacting AWS or writing reports.')
PARSER.add_argument('--base-url', help='Override .local/deployed-url.txt.')
PARSER.add_argument('--kubeconfig', default=str(CONFIG_ROOT / 'recovery-kubeconfig'))
PARSER.add_argument('--output-dir', type=Path, default=CONFIG_ROOT, help='Directory for demo-report.json and demo-runs/.')
PARSER.add_argument('--profile', default='default')
PARSER.add_argument('--region', default='ap-south-1')
PARSER.add_argument('--load-seconds', type=int, default=240)
PARSER.add_argument('--rps', type=int, default=160, help='Maximum read-only HTTP requests/second per HPA service (40..300).')
PARSER.add_argument('--cooldown-seconds', type=int, default=420)
PREFIX = dict(member='member', catalog='catalog', reservation='reservations', lending='loans', availability='availability', fine='fine', notification='notifications')
BUCKET = 'replace-with-globally-unique-library-cover-bucket'
PROM = None
CLEANING_UP = False


def configure(argv=None):
    global ARGS, SECTIONS, ROOT, KUBE, BASE, RUN, REPORT, ARTIFACTS
    ARGS = PARSER.parse_args(argv)
    SECTIONS = [name.strip() for name in ARGS.sections.split(',')]
    if not set(SECTIONS) <= set(DEMO_STEPS) or len(set(SECTIONS)) != len(SECTIONS):
        PARSER.error('Choose unique section names from: ' + ', '.join(DEMO_STEPS))
    if 'notifications' in SECTIONS and ('api' not in SECTIONS or SECTIONS.index('api') > SECTIONS.index('notifications')):
        PARSER.error('notifications requires api earlier in --sections')
    if not 120 <= ARGS.load_seconds <= 600: PARSER.error('--load-seconds must be 120..600')
    if not 40 <= ARGS.rps <= 300: PARSER.error('--rps must be 40..300')
    if not 180 <= ARGS.cooldown_seconds <= 600: PARSER.error('--cooldown-seconds must be 180..600')
    if ARGS.list:
        for index,name in enumerate(SECTIONS,1):
            title,description = DEMO_STEPS[name]
            print(f'{index}. {title} [{name}]\n   {description}')
        return False
    url_file = CONFIG_ROOT / 'deployed-url.txt'
    BASE = (ARGS.base_url or (url_file.read_text().strip() if url_file.exists() else '')).rstrip('/')
    if urlsplit(BASE).scheme not in {'http','https'} or not urlsplit(BASE).netloc:
        PARSER.error('Provide --base-url or the existing digital-library/.local/deployed-url.txt')
    KUBE = str(Path(ARGS.kubeconfig).resolve())
    ROOT = ARGS.output_dir.resolve()
    RUN = uuid4().hex
    ARTIFACTS = ROOT / 'demo-runs' / RUN
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    REPORT = {'run_id': RUN, 'status':'READY', 'started_at': datetime.now(timezone.utc).isoformat(), 'base_url': BASE, 'requests': [], 'assertions': [], 'inventory': {}, 'operational_findings': [], 'fixtures': {}, 'cleanup_warnings': [], 'sections': {}, 'scope_caveats': ['Flink uses isolated Kafka fixture topics; Lending/Reservation still have no domain Kafka publishers.', 'API updates use Argo CD; historical direct platform applies remain a strict GitOps caveat.', 'Load tests use read-only HTTP health endpoints and do not establish business-endpoint capacity.', 'AWS infrastructure remains running after the demo.']}
    RESERVATIONS.clear()
    ACTIVE_LOANS.clear()
    return True

RESERVATIONS = []
ACTIVE_LOANS = []
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=')

def http(url, method='GET', body=None, expected=200, headers=None, raw=False, service='storage'):
    if not ARGS.auto and not CLEANING_UP:
        try:
            choice = input(f'Press Enter for {method} {urlsplit(url).path}, or q to finish: ').strip().lower()
        except EOFError as error:
            raise DemoStopped('Input ended.') from error
        if choice in {'q','quit','exit'}:
            raise DemoStopped('Presenter finished the demo.')
    headers = dict(headers or {})
    if body is not None and not isinstance(body, bytes):
        body = json.dumps(body).encode()
        headers.setdefault('Content-Type', 'application/json')
    try:
        with urlopen(Request(url, data=body, headers=headers, method=method), timeout=30) as response:
            status, content = response.status, response.read()
    except HTTPError as error:
        status, content = error.code, error.read()
    REPORT['requests'].append(dict(service=service, method=method, path=urlsplit(url).path, expected=expected, actual=status, passed=status == expected))
    try:
        displayed = json.loads(content) if content else None
    except (ValueError, UnicodeDecodeError):
        displayed = content.decode('utf-8', errors='replace')
    print(json.dumps({'method':method,'path':urlsplit(url).path,'status_code':status,'response':displayed},indent=2),flush=True)
    if status != expected:
        raise AssertionError(f'{service} {method} {urlsplit(url).path}: expected {expected}, received {status}')
    return content if raw else json.loads(content) if content else None

def api(service, path, method='GET', body=None, expected=200, raw=False):
    return http(f'{BASE}/api/{PREFIX[service]}{path}', method, body, expected, raw=raw, service=service)

def verify(name, condition):
    REPORT['assertions'].append(dict(name=name, passed=bool(condition)))
    if not condition:
        raise AssertionError(name)
    # Successful assertions are recorded; the terminal shows actual responses.

def create_member(number):
    member = api('member', '/members', 'POST', {'name': f'Audit {number}', 'email': f'success+audit-{RUN}-{number}@simulator.amazonses.com'}, 201)
    UUID(member['member_id'])
    return member

def reserve(book, member):
    result = api('reservation', '/reservations', 'POST', {'book_id': book, 'member_id': member}, 201)
    RESERVATIONS.append(result['reservation_id'])
    return result

def wait_copies(book, count):
    for _ in range(30):
        result = api('catalog', f'/books/{book}/copies')
        if len(result['items']) >= count:
            return result
        time.sleep(1)
    raise AssertionError('DynamoDB copy GSI did not become consistent')


def run_api_suite():
    for service in PREFIX:
        api(service, '/health')
        api(service, '/ready')
        schema = api(service, '/openapi.json')
        REPORT['inventory'][service] = [{'method': method.upper(), 'path': path} for path, operations in schema['paths'].items() for method in operations if method in {'get', 'post', 'patch', 'delete', 'put'}]
        verify(service + ' exposes Prometheus metrics', b'_http_requests_total' in api(service, '/metrics', raw=True))
    verify('all seven HTTP services: health/readiness and live endpoint inventory', True)
    missing = str(uuid4())
    m1, m2 = create_member(1), create_member(2)
    mid1, mid2 = m1['member_id'], m2['member_id']
    REPORT['fixtures'].update(member_id=mid1, second_member_id=mid2)
    verify('member GET returns service-generated UUID and creation timestamp', api('member', f'/members/{mid1}')['created_at'] == m1['created_at'])
    updated = api('member', f'/members/{mid1}', 'PATCH', {'name': 'Audit Updated', 'email': f'success+audit-updated-{RUN}@simulator.amazonses.com'})
    verify('member PATCH changes both name and email', updated['name'] == 'Audit Updated' and updated['email'].startswith('success+audit-updated-'))
    api('member', '/members', 'POST', {'name': 'Duplicate', 'email': updated['email'].upper()}, 409)
    api('member', f'/members/{mid2}', 'PATCH', {'email': updated['email']}, 409)
    page = api('member', '/members?limit=1&offset=0')
    page2 = api('member', '/members?limit=1&offset=1')
    verify('member limit/offset returns different records', len(page['items']) == 1 and page['items'][0]['member_id'] != page2['items'][0]['member_id'])
    for path in [f'/members/{missing}']:
        api('member', path, expected=404)
        api('member', path, 'PATCH', {'name': 'Missing'}, 404)
    api('member', '/members/not-a-uuid', expected=422)
    api('member', '/members?limit=0', expected=422)
    api('member', '/members', 'POST', {'name': ' ', 'email': 'invalid'}, 422)
    api('member', f'/members/{mid1}', 'PATCH', {}, 422)
    api('member', f'/members/{mid1}', 'DELETE', expected=405)
    verify('member validation, missing IDs, email uniqueness and no deletion', True)

    book = api('catalog', '/books', 'POST', {'title': f'Audit {RUN}', 'author': 'API Verification', 'isbn': '9780132350884'}, 201)
    bid = book['book_id']; UUID(bid)
    REPORT['fixtures']['book_id'] = bid
    verify('catalog GET preserves book/ISBN and excludes lending state', api('catalog', f'/books/{bid}')['isbn'] == '9780132350884' and not {'available', 'loan_id', 'available_copies'}.intersection(book))
    copy = api('catalog', f'/books/{bid}/copies', 'POST', expected=201)
    cid = copy['copy_id']; UUID(cid)
    REPORT['fixtures']['copy_id'] = cid
    wait_copies(bid, 1)
    books = api('catalog', '/books?limit=1')
    verify('catalog list pagination returns a continuation key', len(books['items']) == 1 and bool(books['last_evaluated_key']))
    next_page = api('catalog', '/books?' + urlencode({'limit': 1, 'last_evaluated_key': json.dumps(books['last_evaluated_key'])}))
    verify('catalog book pagination advances', next_page['items'][0]['book_id'] != books['items'][0]['book_id'])
    for path in [f'/books/{missing}', f'/books/{missing}/copies']:
        api('catalog', path, expected=404)
    api('catalog', f'/books/{missing}/copies', 'POST', expected=404)
    api('catalog', '/books/not-a-uuid', expected=422)
    api('catalog', '/books?limit=0', expected=422)
    api('catalog', '/books?last_evaluated_key=invalid', expected=422)
    api('catalog', '/books', 'POST', {'title': '', 'author': 'A'}, 422)
    api('catalog', '/books', 'POST', {'title': 'A', 'author': 'A', 'isbn': 'invalid'}, 422)
    api('catalog', f'/books/{bid}/cover-url', expected=404)
    api('catalog', f'/books/{bid}/cover/confirm', 'POST', expected=409)
    api('catalog', f'/books/{bid}/cover/upload-url', 'POST', {'content_type': 'application/pdf'}, 422)
    upload = api('catalog', f'/books/{bid}/cover/upload-url', 'POST', {'content_type': 'image/png'})
    http(upload['upload_url'], 'PUT', PNG, headers=upload['headers'], raw=True)
    confirmed = api('catalog', f'/books/{bid}/cover/confirm', 'POST')
    download = api('catalog', f'/books/{bid}/cover-url')['url']
    verify('private S3 cover upload/confirmation/download', bool(confirmed['cover_key']) and http(download, raw=True) == PNG)
    http(download.split('?', 1)[0], expected=403, raw=True)
    verify('catalog missing books, input validation and unsigned S3 rejection', True)

    availability = f'/books/{bid}/availability'
    verify('availability reports the new copy', api('availability', availability)['available_copy_ids'] == [cid])
    api('availability', f'/books/{missing}/availability', expected=404)
    api('availability', '/books/not-a-uuid/availability', expected=422)
    api('reservation', '/reservations', 'POST', {'member_id': missing, 'book_id': bid}, 404)
    api('reservation', '/reservations', 'POST', {'member_id': mid1, 'book_id': missing}, 404)
    api('reservation', '/reservations', 'POST', {'member_id': 'invalid', 'book_id': bid}, 422)
    r1, r2 = reserve(bid, mid1), reserve(bid, mid2)
    REPORT['fixtures'].update(reservation_id=r1['reservation_id'], waiter_id=r2['reservation_id'])
    verify('reservation FIFO assigns READY then WAITLISTED', r1['status'] == 'READY' and r2['status'] == 'WAITLISTED')
    api('reservation', '/reservations', 'POST', {'member_id': mid1, 'book_id': bid}, 409)
    verify('reservation GET detail and member list', api('reservation', '/reservations/' + r1['reservation_id'])['status'] == 'READY' and api('reservation', '/reservations?' + urlencode({'member_id': mid1, 'limit': 1, 'offset': 0}))['total'] == 1)
    api('reservation', f'/reservations/{missing}', expected=404)
    api('reservation', f'/reservations/{missing}', 'DELETE', expected=404)
    api('reservation', '/reservations/not-a-uuid', expected=422)
    verify('availability accounts for an allocated hold', api('availability', availability)['available_copies'] == 0)

    payload = {'member_id': mid1, 'reservation_id': r1['reservation_id'], 'copy_id': cid}
    wrong = dict(payload, member_id=mid2)
    api('lending', '/loans', 'POST', wrong, 409)
    api('lending', '/loans', 'POST', dict(payload, reservation_id=r2['reservation_id'], member_id=mid2), 409)
    api('lending', '/loans', 'POST', dict(payload, reservation_id=missing), 404)
    api('lending', '/loans', 'POST', {'member_id': 'invalid'}, 422)
    loan = api('lending', '/loans', 'POST', payload, 201)
    lid = loan['loan_id']; ACTIVE_LOANS.append(lid)
    REPORT['fixtures']['loan_id'] = lid
    REPORT['fixtures']['checked_out_at'] = loan['checked_out_at']
    verify('lending GET and list filters', api('lending', f'/loans/{lid}')['status'] == 'ACTIVE' and api('lending', '/loans?' + urlencode({'member_id': mid1, 'book_id': bid, 'active_only': 'true', 'limit': 1, 'offset': 0}))['total'] == 1)
    api('lending', '/loans', 'POST', payload, 409)
    api('lending', f'/loans/{missing}', expected=404)
    api('lending', f'/loans/{missing}/return', 'POST', expected=404)
    api('lending', '/loans/not-a-uuid', expected=422)
    api('lending', '/loans?limit=0', expected=422)
    verify('availability accounts for active lending', api('availability', availability)['loaned_copies'] == 1)
    fine = api('fine', f'/loans/{lid}/fine')
    verify('fine assessment on an active non-overdue loan', fine['fine_amount_cents'] == 0 and fine['overdue_days'] == 0)
    api('fine', f'/loans/{missing}/fine', expected=404)
    api('fine', '/loans/not-a-uuid/fine', expected=422)
    returned = api('lending', f'/loans/{lid}/return', 'POST')
    returned2 = api('lending', f'/loans/{lid}/return', 'POST')
    ACTIVE_LOANS.remove(lid)
    REPORT['fixtures']['returned_at'] = returned['returned_at']
    verify('loan return is idempotent', returned['returned_at'] == returned2['returned_at'] and returned2['status'] == 'RETURNED')
    returned_fine = api('fine', f'/loans/{lid}/fine')
    verify('returned-loan fine uses actual return timestamp', returned_fine['fine_amount_cents'] == 0 and returned_fine['assessed_at'] == returned['returned_at'])
    verify('FIFO waiter promotion after return', api('reservation', '/reservations/' + r2['reservation_id'])['status'] == 'READY')
    api('reservation', '/reservations/' + r2['reservation_id'], 'DELETE')
    api('reservation', '/reservations/' + r2['reservation_id'], 'DELETE')
    verify('reservation cancellation is idempotent and frees copy', api('availability', availability)['available_copies'] == 1)

    event = {'event_type': 'LoanReturned', 'recipient': 'success@simulator.amazonses.com', 'subject': f'Final API audit {RUN}', 'body': 'AWS endpoint audit completed.', 'member_id': mid1, 'occurred_at': datetime.now(timezone.utc).isoformat()}
    receipt = api('notification', '/notifications', 'POST', event, 202)
    REPORT['fixtures']['notification_id'] = receipt['notification_id']
    verify('notification asynchronous intake returns QUEUED and UUID', receipt['status'] == 'QUEUED' and bool(UUID(receipt['notification_id'])))
    api('notification', '/notifications', 'POST', dict(event, recipient='invalid'), 422)
    api('notification', '/notifications', 'POST', dict(event, event_type='Unsupported'), 422)

    pagination_book = api('catalog', '/books', 'POST', {'title': f'Pagination {RUN}', 'author': 'Audit'}, 201)['book_id']
    for _ in range(2): api('catalog', f'/books/{pagination_book}/copies', 'POST', expected=201)
    wait_copies(pagination_book, 2)
    first = api('catalog', f'/books/{pagination_book}/copies?limit=1')
    second = api('catalog', f'/books/{pagination_book}/copies?' + urlencode({'limit': 1, 'last_evaluated_key': json.dumps(first['last_evaluated_key'])}))
    verify('copy GSI pagination advances correctly', first['items'][0]['copy_id'] != second['items'][0]['copy_id'])

    concurrency_book = api('catalog', '/books', 'POST', {'title': f'Concurrency {RUN}', 'author': 'Audit'}, 201)['book_id']
    api('catalog', f'/books/{concurrency_book}/copies', 'POST', expected=201)
    wait_copies(concurrency_book, 1)
    people = [create_member(i)['member_id'] for i in range(10, 15)]
    holds = [reserve(concurrency_book, person) for person in people]
    verify('five sequential reservations: one READY, four WAITLISTED, distinct FIFO positions', sorted(h['queue_position'] for h in holds) == [1,2,3,4,5] and sum(h['status'] == 'READY' for h in holds) == 1)
    for hold in sorted(holds, key=lambda h: h['queue_position']):
        current = api('reservation', '/reservations/' + hold['reservation_id'])
        verify('FIFO promotion position ' + str(hold['queue_position']), current['status'] == 'READY')
        api('reservation', '/reservations/' + hold['reservation_id'], 'DELETE')
    REPORT['fixtures']['concurrency_book_id'] = concurrency_book
    verify('frontend HTML is available', b'<html' in http(BASE + '/', raw=True, service='frontend').lower())


def command(args, *, input_text=None, timeout=60, allowed=(0,)):
    result = subprocess.run([str(arg) for arg in args], input=input_text, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode not in allowed:
        raise RuntimeError(f'{args[0]} {args[1]} exited {result.returncode}: {result.stderr[-3000:]} {result.stdout[-1500:]}')
    return result.stdout


def aws(*args, timeout=60, raw=False):
    output = command(['aws', *args, '--profile', ARGS.profile, '--region', ARGS.region, '--no-cli-pager'], timeout=timeout)
    return output if raw else json.loads(output)


def kube(*args, input_text=None, timeout=60, raw=False, allowed=(0,)):
    # Retry transient transport failures only for read-only inspection commands.
    attempts = 3 if any(operation in args for operation in ('get','logs','top')) else 1
    for attempt in range(attempts):
        try:
            output = command(['kubectl', '--kubeconfig', KUBE, '--request-timeout=20s', *args], input_text=input_text, timeout=timeout, allowed=allowed)
            return output if raw else json.loads(output)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            transient = any(term in str(error).lower() for term in ('timeout','timed out','connection reset','unexpected eof','connection refused'))
            if not transient or attempt + 1 == attempts:
                raise
            REPORT.setdefault('transient_retries', []).append({'tool':'kubectl','attempt':attempt+1,'time':datetime.now(timezone.utc).isoformat()})
            print('Retrying transient kubectl transport failure for read-only inspection', flush=True)
            time.sleep(2)


def snapshot():
    REPORT['finished_at'] = datetime.now(timezone.utc).isoformat()
    REPORT['artifact_directory'] = str(ARTIFACTS)
    content = json.dumps(REPORT, indent=2)
    (ROOT / 'demo-report.json').write_text(content, encoding='utf-8')
    (ARTIFACTS / 'report.json').write_text(content, encoding='utf-8')


def wait_for(description, check, timeout=120, interval=5):
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError('Timed out: ' + description)
        time.sleep(interval)


@contextmanager
def prometheus_forward():
    global PROM
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    log = (ARTIFACTS / 'prometheus-forward.log').open('w', encoding='utf-8')
    process = subprocess.Popen(['kubectl', '--kubeconfig', KUBE, '-n', 'observability', 'port-forward', 'service/library-observability-kube-prometheus', f'{port}:9090', '--address', '127.0.0.1'], stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    PROM = f'http://127.0.0.1:{port}'
    try:
        def ready():
            if process.poll() is not None:
                raise RuntimeError('Prometheus forward exited; see ' + str(log.name))
            try:
                with urlopen(PROM + '/-/ready', timeout=2) as response:
                    return response.status == 200
            except OSError:
                return False
        wait_for('Prometheus local forward', ready, 30, 1)
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
        PROM = None


def prometheus(path, params=None):
    url = PROM + '/api/v1/' + path + (('?' + urlencode(params)) if params else '')
    with urlopen(url, timeout=20) as response:
        payload = json.load(response)
    assert payload['status'] == 'success', payload
    return payload['data']


def prom_query(expression):
    return prometheus('query', {'query': expression})['result']


def run_metrics_suite():
    evidence = REPORT['prometheus'] = {'queries': {}, 'targets': []}
    targets = prometheus('targets')['activeTargets']
    evidence['targets'] = [{'app': target['labels'].get('app'), 'health': target['health'], 'last_scrape': target['lastScrape'], 'last_error': target['lastError'], 'url': target['scrapeUrl']} for target in targets if target['labels'].get('namespace') == 'library']
    verify('Prometheus actually scrapes all seven services successfully', set(PREFIX) <= {target['app'] for target in evidence['targets'] if target['health'] == 'up' and not target['last_error']})
    expressions = {
        'request_counters': 'sum by (app) ({__name__=~".+_http_requests_total",namespace="library"})',
        'request_rate': 'sum by (app) (rate({__name__=~".+_http_requests_total",namespace="library"}[5m]))',
        'latency_histogram': 'sum by (app) ({__name__=~".+_http_request_duration_seconds_count",namespace="library"})',
        'p95_seconds': 'histogram_quantile(0.95, sum by (app,le) (rate({__name__=~".+_http_request_duration_seconds_bucket",namespace="library"}[5m])))',
        'cpu_cores': 'sum(rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m]))',
        'hpa_replicas': 'kube_horizontalpodautoscaler_status_current_replicas{namespace="library"}',
    }
    for name, expression in expressions.items():
        result = prom_query(expression)
        evidence['queries'][name] = {'expression': expression, 'result': result}
        if name in {'request_counters', 'request_rate', 'latency_histogram', 'p95_seconds'}:
            verify('Prometheus ' + name + ' has seven finite service series', set(PREFIX) <= {item['metric'].get('app') for item in result if math.isfinite(float(item['value'][1]))})
        else:
            verify('Prometheus exposes ' + name, bool(result))
    snapshot()


def emr_step(cluster_id, label, script, timeout=240):
    path = ARTIFACTS / (label + '-step.json')
    steps = [{'Type': 'CUSTOM_JAR', 'Name': 'library-audit-' + RUN[:10] + '-' + label, 'ActionOnFailure': 'CONTINUE', 'Jar': 'command-runner.jar', 'Args': ['bash', '-lc', script]}]
    path.write_text(json.dumps(steps), encoding='utf-8')
    step_id = aws('emr', 'add-steps', '--cluster-id', cluster_id, '--steps', 'file://' + str(path))['StepIds'][0]
    REPORT.setdefault('emr_steps', []).append({'label': label, 'id': step_id})
    print(f'EMR {label}: {step_id}', flush=True)
    def terminal():
        status = aws('emr', 'describe-step', '--cluster-id', cluster_id, '--step-id', step_id)['Step']['Status']
        return status if status['State'] in {'COMPLETED', 'FAILED', 'CANCELLED', 'INTERRUPTED'} else None
    status = wait_for('EMR ' + label, terminal, timeout, 5)
    REPORT['emr_steps'][-1]['status'] = status
    assert status['State'] == 'COMPLETED', status
    return step_id


def kafka(*args, input_text=None, timeout=60, allowed=(0,)):
    return kube('-n', 'library', 'exec', '-i', 'kafka-0', '--', '/opt/kafka/bin/' + args[0], *args[1:], input_text=input_text, timeout=timeout, raw=True, allowed=allowed)


def run_flink_suite():
    evidence = REPORT['flink'] = {'scope': 'real Flink on existing EMR/YARN, isolated synthetic Kafka fixtures; not automatic domain publishing', 'results': []}
    clusters = aws('emr', 'list-clusters', '--active')['Clusters']
    cluster = next(item for item in clusters if item['Name'] == 'digital-library-dev-analytics')
    cluster_id = evidence['cluster_id'] = cluster['Id']
    instances = aws('emr', 'list-instances', '--cluster-id', cluster_id)['Instances']
    verify('Flink uses only the existing single m5.xlarge EMR primary', len(instances) == 1 and instances[0]['InstanceType'] == 'm5.xlarge')
    nodes = kube('get', 'nodes', '-o', 'json')['items']
    verify('EKS still uses one t3.xlarge worker', len(nodes) == 1 and nodes[0]['metadata']['labels']['node.kubernetes.io/instance-type'] == 't3.xlarge')
    node_ip = next(address['address'] for address in nodes[0]['status']['addresses'] if address['type'] == 'InternalIP')
    evidence['kafka_bootstrap'] = f'{node_ip}:30094'
    jar = PROJECT / 'services/usage-analytics/target/usage-analytics-1.0.0.jar'
    assert jar.exists(), 'Build analytics first: docker run --rm -v <analytics-directory>:/build -w /build maven:3.9.9-eclipse-temurin-17 mvn -B clean verify'
    evidence['jar_sha256'] = hashlib.sha256(jar.read_bytes()).hexdigest()
    prefix = 'flink/audits/' + RUN
    location = f's3://{BUCKET}/{prefix}'
    evidence['artifact_location'] = location
    aws('s3', 'cp', str(jar), location + '/usage-analytics.jar', raw=True)
    input_topic = evidence['input_topic'] = 'library.audit.' + RUN + '.events'
    results_topic = evidence['results_topic'] = 'library.audit.' + RUN + '.results'
    for topic in (input_topic, results_topic):
        kafka('kafka-topics.sh', '--bootstrap-server', 'kafka:9092', '--create', '--topic', topic, '--partitions', '3', '--replication-factor', '1')
    environment = {'KAFKA_BOOTSTRAP_SERVERS': evidence['kafka_bootstrap'], 'KAFKA_INPUT_TOPIC': input_topic, 'KAFKA_RESULTS_TOPIC': results_topic, 'KAFKA_CONSUMER_GROUP': 'library-audit-' + RUN}
    options = ' '.join('-Dcontainerized.master.env.' + key + '=' + value for key, value in environment.items())
    script = f'''set -eu
for candidate in /usr/lib/jvm/java-17-amazon-corretto*; do
  if [ -x "$candidate/bin/java" ]; then export JAVA_HOME="$candidate"; break; fi
done
export PATH="$JAVA_HOME/bin:$PATH"
work=$(mktemp -d /tmp/library-audit-{RUN[:10]}-XXXX)
aws s3 cp '{location}/usage-analytics.jar' "$work/job.jar" --region {ARGS.region}
set +e
flink run-application -t yarn-application -d -p 1 -Dclassloader.resolve-order=parent-first -Denv.java.home="$JAVA_HOME" -Djobmanager.memory.process.size=768m -Dtaskmanager.memory.process.size=1536m -Dtaskmanager.numberOfTaskSlots=1 -Dyarn.application.name=library-audit-{RUN} -Dyarn.application.tags=library-audit-{RUN} -Dstate.checkpoints.dir='{location}/checkpoints/' {options} -c edu.birla.library.analytics.UsageAnalyticsJob "$work/job.jar" > "$work/submit.log" 2>&1
result=$?
aws s3 cp "$work/submit.log" '{location}/submit.log' --region {ARGS.region}
cat "$work/submit.log"
exit "$result"
'''
    application_id = None
    try:
        emr_step(cluster_id, 'flink-submit', script, 300)
        submit_log = aws('s3', 'cp', location + '/submit.log', '-', raw=True)
        (ARTIFACTS / 'flink-submit.log').write_text(submit_log, encoding='utf-8')
        matches = re.findall(r'application_\d+_\d+', submit_log)
        assert matches, 'Flink submission did not return a YARN application ID'
        application_id = evidence['application_id'] = matches[-1]
        minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        expected = {}
        records = []
        for label, types, members in [('A', ['ReservationCreated','ReservationConflict','LoanCheckedOut','LoanReturned'], ['m1','m2','m1','m1']), ('B', ['ReservationCreated','ReservationCreated'], ['m3','m3'])]:
            book_id = str(uuid4())
            counts = Counter(types)
            expected[book_id] = {'reservation_count': counts['ReservationCreated'], 'conflict_count': counts['ReservationConflict'], 'checkout_count': counts['LoanCheckedOut'], 'return_count': counts['LoanReturned'], 'unique_members': len(set(members)), 'total_events': len(types)}
            for index, (kind, member) in enumerate(zip(types, members)):
                records.append({'book_id': book_id, 'member_id': 'audit-' + RUN + '-' + member, 'event_type': kind, 'occurred_at': (minute + timedelta(seconds=index+1)).isoformat().replace('+00:00','Z')})
        # Round-robin markers advance every partition beyond the fixture window
        # plus its 30-second watermark delay; no wall-clock sleep closes the window.
        for _ in range(6):
            records.append({'book_id': 'audit-watermark-' + RUN, 'member_id': 'marker', 'event_type': 'LoanReturned', 'occurred_at': (minute + timedelta(seconds=150)).isoformat().replace('+00:00','Z')})
        evidence['input_records'] = records
        evidence['expected'] = expected
        kafka('kafka-console-producer.sh', '--bootstrap-server', 'kafka:9092', '--topic', input_topic, '--producer-property', 'partitioner.class=org.apache.kafka.clients.producer.RoundRobinPartitioner', '--producer-property', 'acks=all', input_text='\n'.join(json.dumps(record) for record in records) + '\n')
        print('Flink fixtures published: 6 domain records plus 6 watermark markers', flush=True)
        def results_ready():
            output = kafka('kafka-console-consumer.sh', '--bootstrap-server', 'kafka:9092', '--topic', results_topic, '--from-beginning', '--timeout-ms', '8000', timeout=20, allowed=(0,1))
            evidence['results'] = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
            return set(expected) <= {result['book_id'] for result in evidence['results']}
        wait_for('Flink windowed Kafka output', results_ready, 180, 3)
        for book_id, counts in expected.items():
            result = next(item for item in evidence['results'] if item['book_id'] == book_id)
            verify('Flink exact window counts and distinct members for ' + book_id, all(result.get(key) == value for key, value in counts.items()))
            start = datetime.fromisoformat(result['window_start'].replace('Z','+00:00'))
            end = datetime.fromisoformat(result['window_end'].replace('Z','+00:00'))
            verify('Flink UTC-aligned one-minute event-time window for ' + book_id, start == minute and end - start == timedelta(minutes=1))
        # Query actual YARN/Flink REST state and completed checkpoints from the primary.
        inspect_code = f'''import json,time,urllib.request
def get(url):
    with urllib.request.urlopen(url, timeout=10) as response: return json.load(response)
app=get('http://{instances[0]['PrivateIpAddress']}:8088/ws/v1/cluster/apps/{application_id}')['app']
tracking=app['trackingUrl'].rstrip('/')
overview=get(tracking+'/jobs/overview')
jobs=[job for job in overview['jobs'] if job['state']=='RUNNING']
assert jobs, overview
job_id=jobs[0]['jid']
deadline=time.time()+90
while True:
    checkpoints=get(tracking+'/jobs/'+job_id+'/checkpoints')
    if checkpoints['counts']['completed']>0: break
    assert time.time()<deadline, checkpoints
    time.sleep(3)
print(json.dumps({{'application': app, 'jobs': overview, 'checkpoints': checkpoints}}))
'''
        encoded = base64.b64encode(inspect_code.encode()).decode()
        inspect_script = f'''set -eu
out=$(mktemp)
echo '{encoded}' | base64 -d | python3 - > "$out"
aws s3 cp "$out" '{location}/runtime.json' --region {ARGS.region}
cat "$out"
'''
        emr_step(cluster_id, 'flink-inspect', inspect_script, 180)
        evidence['runtime'] = aws('s3', 'cp', location + '/runtime.json', '-', raw=True)
        evidence['runtime'] = json.loads(evidence['runtime'])
        verify('Flink job RUNNING on YARN with a completed checkpoint', evidence['runtime']['application']['state'] == 'RUNNING' and evidence['runtime']['checkpoints']['counts']['completed'] > 0)
        evidence['consumer_group'] = kafka('kafka-consumer-groups.sh', '--bootstrap-server', 'kafka:9092', '--describe', '--group', environment['KAFKA_CONSUMER_GROUP'])
        evidence['input_offsets'] = kafka('kafka-get-offsets.sh', '--bootstrap-server', 'kafka:9092', '--topic', input_topic)
        evidence['result_offsets'] = kafka('kafka-get-offsets.sh', '--bootstrap-server', 'kafka:9092', '--topic', results_topic)
        snapshot()
    finally:
        # Discover by our unique tag as well, so failed/timed-out submission cannot
        # orphan an application merely because its ID was not yet captured.
        cleanup_code = f'''import json,subprocess,urllib.request
url='http://{instances[0]['PrivateIpAddress']}:8088/ws/v1/cluster/apps?applicationTags=library-audit-{RUN}'
with urllib.request.urlopen(url,timeout=15) as response: apps=json.load(response).get('apps') or {{}}
stopped=[]
for app in apps.get('app',[]):
    if app['name']=='library-audit-{RUN}' and app['state'] not in ['FINISHED','FAILED','KILLED']:
        subprocess.run(['yarn','application','-kill',app['id']],check=True)
        stopped.append(app['id'])
print(json.dumps({{'stopped':stopped}}))
'''
        encoded_cleanup = base64.b64encode(cleanup_code.encode()).decode()
        try:
            cleanup_script = f"echo '{encoded_cleanup}' | base64 -d | python3 -"
            emr_step(cluster_id, 'flink-cleanup', cleanup_script, 120)
            evidence['application_stopped'] = True
        except Exception as error:
            REPORT['cleanup_warnings'].append('Flink cleanup: ' + str(error))
        evidence['retained_fixtures'] = 'Isolated Kafka input/results topics and S3 artifacts/checkpoints retained for demonstration; no business loans modified.'


class ReadOnlyLoad:
    """Rate-capped HTTP load with bounded telemetry and an explicit stop signal."""
    def __init__(self, service):
        self.service = service
        self.rate = min(80, ARGS.rps)
        self.next_request = time.monotonic()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.codes = Counter()
        self.latencies = deque(maxlen=20000)
        self.started = time.monotonic()
        self.pool = ThreadPoolExecutor(max_workers=24, thread_name_prefix='audit-' + service)
        self.futures = [self.pool.submit(self.worker) for _ in range(24)]

    def worker(self):
        parsed = urlsplit(BASE)
        connection_type = HTTPSConnection if parsed.scheme == 'https' else HTTPConnection
        connection = connection_type(parsed.hostname, parsed.port, timeout=5)
        try:
            while not self.stop.is_set():
                with self.lock:
                    scheduled = max(self.next_request, time.monotonic())
                    self.next_request = scheduled + 1 / self.rate
                if self.stop.wait(max(0, scheduled - time.monotonic())):
                    break
                start = time.monotonic()
                try:
                    connection.request('GET', '/api/' + PREFIX[self.service] + '/health')
                    response = connection.getresponse()
                    response.read()
                    code = str(response.status)
                except (OSError, HTTPException):
                    code = 'transport_error'
                    connection.close()
                    connection = connection_type(parsed.hostname, parsed.port, timeout=5)
                with self.lock:
                    self.codes[code] += 1
                    self.latencies.append(time.monotonic() - start)
        finally:
            connection.close()

    def stats(self):
        with self.lock:
            samples = sorted(self.latencies)
            counts = dict(self.codes)
        total = sum(counts.values())
        return {'path': '/api/' + PREFIX[self.service] + '/health', 'requests': total, 'status_counts': counts, 'error_rate': (total - counts.get('200', 0)) / max(1,total), 'achieved_rps': total / max(0.001,time.monotonic()-self.started), 'target_rps': self.rate, 'p95_seconds': samples[min(len(samples)-1, int(len(samples)*0.95))] if samples else None, 'latency_samples_retained': len(samples)}

    def close(self):
        self.stop.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
        for future in self.futures:
            if not future.cancelled():
                future.result()


def scaling_snapshot():
    autoscalers = kube('-n', 'library', 'get', 'hpa', 'catalog', 'reservation', '-o', 'json')['items']
    deployments = kube('-n', 'library', 'get', 'deployment', 'catalog', 'reservation', '-o', 'json')['items']
    return {'time': datetime.now(timezone.utc).isoformat(), 'hpa': {item['metadata']['name']: {'spec': item['spec'], 'status': item.get('status', {})} for item in autoscalers}, 'deployments': {item['metadata']['name']: {'desired': item['spec']['replicas'], 'ready': item.get('status', {}).get('readyReplicas', 0), 'available': item.get('status', {}).get('availableReplicas', 0)} for item in deployments}}


def cpu_utilization(item):
    for metric in item['status'].get('currentMetrics', []):
        if metric.get('resource', {}).get('name') == 'cpu':
            return metric['resource']['current'].get('averageUtilization', 0)
    return 0


def run_hpa_suite():
    names = ('catalog', 'reservation')
    evidence = REPORT['autoscaling'] = {'load_scope': 'rate-capped read-only HTTP /health requests; no CPU injection, target changes or manual scaling', 'history': [], 'cooldown': [], 'load': {}}
    baseline = scaling_snapshot()
    for name in names:
        spec = baseline['hpa'][name]['spec']
        verify(name + ' HPA configured min=1 max=2 and CPU target=60%', spec['minReplicas'] == 1 and spec['maxReplicas'] == 2 and spec['metrics'][0]['resource']['target']['averageUtilization'] == 60)
    def at_minimum():
        sample = scaling_snapshot()
        return sample if all(sample['deployments'][name]['desired'] == 1 and sample['deployments'][name]['ready'] == 1 and sample['hpa'][name]['status'].get('currentReplicas') == 1 for name in names) else None
    baseline = wait_for('both HPAs at baseline one ready replica', at_minimum, ARGS.cooldown_seconds, 10)
    evidence['baseline'] = baseline
    range_start = time.time()
    loads = {}
    start = time.monotonic()
    ready_since = {}
    original_error = None
    try:
        for name in names:
            loads[name] = ReadOnlyLoad(name)
        while time.monotonic() - start < ARGS.load_seconds:
            elapsed = time.monotonic() - start
            if elapsed > 60:
                for load in loads.values():
                    load.rate = ARGS.rps
            for load in loads.values():
                for future in load.futures:
                    if future.done():
                        future.result()  # Report worker failures immediately.
            sample = scaling_snapshot()
            sample['elapsed_seconds'] = round(elapsed, 2)
            sample['load'] = {name: load.stats() for name, load in loads.items()}
            sample['prometheus'] = {
                'http_rps': prom_query('sum by (app) (rate({__name__=~"(catalog|reservation)_http_requests_total",namespace="library",route="/health"}[1m]))'),
                'cpu_cores': prom_query('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="library",container=~"catalog|reservation"}[1m]))'),
                'desired_replicas': prom_query('kube_horizontalpodautoscaler_status_desired_replicas{namespace="library",horizontalpodautoscaler=~"catalog|reservation"}'),
                'scraped_replicas': prom_query('sum by (app) (up{namespace="library",app=~"catalog|reservation"})'),
            }
            application = kube('-n','argocd','get','application','digital-library','-o','json')
            sample['argo'] = {'sync':application['status']['sync']['status'],'health':application['status']['health']['status'],'revision':application['status']['sync']['revision']}
            evidence['history'].append(sample)
            print('HPA load ' + str(round(elapsed)) + 's: ' + '; '.join(f"{name} cpu={cpu_utilization(sample['hpa'][name])}% ready={sample['deployments'][name]['ready']}/desired={sample['deployments'][name]['desired']} requests={sample['load'][name]['requests']}" for name in names), flush=True)
            for name in names:
                ready = sample['deployments'][name]['ready'] >= 2 and sample['deployments'][name]['desired'] == 2 and sample['hpa'][name]['status'].get('desiredReplicas') == 2
                if ready:
                    ready_since.setdefault(name, time.monotonic())
                else:
                    ready_since.pop(name, None)
                stats = sample['load'][name]
                if stats['requests'] > 1000 and stats['error_rate'] > 0.01:
                    raise AssertionError(f'{name} load error rate exceeded 1%: {stats}')
            snapshot()
            # Hold the observed scale-out under sustained load for at least a minute.
            if elapsed >= 150 and all(name in ready_since and time.monotonic() - ready_since[name] >= 60 for name in names):
                break
            time.sleep(10)
        for name in names:
            verify(name + ' exceeded the actual HPA CPU target under HTTP load', any(cpu_utilization(sample['hpa'][name]) > 60 for sample in evidence['history']))
            verify(name + ' automatically scaled from one to two ready replicas under sustained load', name in ready_since and time.monotonic() - ready_since[name] >= 60)
            verify(name + ' extra replica is actually scraped by Prometheus', any(any(row['metric'].get('app') == name and float(row['value'][1]) >= 2 for row in sample['prometheus']['scraped_replicas']) for sample in evidence['history']))
            verify(name + ' load request rate is visible in Prometheus', any(any(row['metric'].get('app') == name and float(row['value'][1]) >= 10 for row in sample['prometheus']['http_rps']) for sample in evidence['history']))
            verify(name + ' HPA desired=2 is visible in Prometheus', any(any(row['metric'].get('horizontalpodautoscaler') == name and float(row['value'][1]) >= 2 for row in sample['prometheus']['desired_replicas']) for sample in evidence['history']))
        verify('Argo CD remains Synced/Healthy while both HPA deployments have two replicas', any(sample['argo']['sync'] == 'Synced' and sample['argo']['health'] == 'Healthy' and all(sample['deployments'][name]['ready'] == 2 and sample['deployments'][name]['desired'] == 2 for name in names) for sample in evidence['history']))
        events = kube('-n', 'library', 'get', 'events', '--field-selector', 'involvedObject.kind=HorizontalPodAutoscaler', '-o', 'json')['items']
        evidence['events'] = [{key: event.get(key) for key in ('reason','message','firstTimestamp','lastTimestamp','count','involvedObject')} for event in events if event.get('involvedObject', {}).get('name') in names]
    except Exception as error:
        original_error = error
    finally:
        for name, load in loads.items():
            try:
                load.close()
            except Exception as error:
                if original_error is None:
                    original_error = error
            evidence['load'][name] = load.stats()
        evidence['load_stopped_at'] = datetime.now(timezone.utc).isoformat()
        print('HTTP load stopped; waiting for HPA-driven scale-down (180s stabilization + metrics/controller delay)', flush=True)
        def cooled_down():
            sample = scaling_snapshot()
            evidence['cooldown'].append(sample)
            snapshot()
            print('HPA cooldown: ' + '; '.join(f"{name} cpu={cpu_utilization(sample['hpa'][name])}% ready={sample['deployments'][name]['ready']}/desired={sample['deployments'][name]['desired']}" for name in names), flush=True)
            return sample if all(sample['deployments'][name]['desired'] == 1 and sample['deployments'][name]['ready'] == 1 for name in names) else None
        try:
            final = wait_for('automatic scale-down to one ready replica', cooled_down, ARGS.cooldown_seconds, 15)
            for name in names:
                verify(name + ' HPA configuration unchanged after load', final['hpa'][name]['spec'] == baseline['hpa'][name]['spec'])
                verify(name + ' returned to one ready replica after load stopped', final['deployments'][name]['ready'] == 1 and final['hpa'][name]['status'].get('desiredReplicas') == 1)
            evidence['final'] = final
        except Exception as error:
            REPORT['cleanup_warnings'].append('HPA cooldown: ' + str(error))
            if original_error is None:
                original_error = error
    if original_error:
        raise original_error
    def prom_cooled_down():
        rows = prom_query('kube_horizontalpodautoscaler_status_desired_replicas{namespace="library",horizontalpodautoscaler=~"catalog|reservation"}')
        evidence['prometheus_final_replicas'] = rows
        return set(names) <= {row['metric'].get('horizontalpodautoscaler') for row in rows if float(row['value'][1]) == 1}
    wait_for('Prometheus sees both HPAs return to one replica', prom_cooled_down, 90, 5)
    verify('Prometheus confirms both HPAs scaled back down', True)
    expression = 'kube_horizontalpodautoscaler_status_desired_replicas{namespace="library",horizontalpodautoscaler=~"catalog|reservation"}'
    evidence['prometheus_replica_history'] = prometheus('query_range', {'query':expression,'start':range_start,'end':time.time(),'step':'15s'})
    snapshot()


def run_grpc_suite():
    member_id = REPORT['fixtures'].get('member_id')
    if member_id is None:
        member_id = api('member', '/members?limit=1&offset=0')['items'][0]['member_id']
    code = '''import grpc,json
with grpc.insecure_channel('member:50051') as channel:
    call=channel.unary_unary('/library.member.v1.MemberEligibility/CheckoutEligibility',request_serializer=lambda value:json.dumps(value).encode(),response_deserializer=lambda value:json.loads(value.decode()))
    print(json.dumps([call({'member_id': MEMBER},timeout=10),call({'member_id': MISSING},timeout=10)]))
'''.replace('MEMBER', repr(member_id)).replace('MISSING', repr(str(uuid4())))
    result = json.loads(kube('-n','library','exec','-i','deployment/lending','--','python','-', input_text=code, raw=True))
    REPORT['grpc'] = result
    verify('real Member gRPC eligibility and missing-member response', result[0]['eligible'] and result[1]['reason_code'] == 'MEMBER_NOT_FOUND')
    book_id = REPORT['fixtures'].get('concurrency_book_id', REPORT['fixtures'].get('book_id'))
    path = '/library/books' + ('/' + book_id if book_id else '')
    code = '''import os,json
from kazoo.client import KazooClient
client=KazooClient(hosts=os.environ['ZOOKEEPER_HOSTS'])
client.start(timeout=10)
try: print(json.dumps({'connected':client.connected,'lock_path_exists':bool(client.exists(PATH))}))
finally: client.stop();client.close()
'''.replace('PATH', repr(path))
    result = json.loads(kube('-n','library','exec','-i','deployment/reservation','--','python','-', input_text=code, raw=True))
    REPORT['zookeeper'] = result
    verify('real ZooKeeper connection and audited lock path', result['connected'] and result['lock_path_exists'])


def run_notifications_suite():
    fixture = REPORT['fixtures']
    ids = {kind: str(uuid5(NAMESPACE_URL, f"digital-library/loans/{fixture['loan_id']}/{kind}")) for kind in ('LoanIssued','LoanReturned')}
    ids['ExplicitIntake'] = fixture['notification_id']
    evidence = REPORT['notifications'] = {'ids': ids}
    since = int(datetime.fromisoformat(REPORT['started_at']).timestamp()*1000) - 5000
    def logs():
        return aws('logs','filter-log-events','--log-group-name','/aws/lambda/digital-library-dev-notification','--start-time',str(since))['events']
    def delivered():
        events = logs()
        evidence['events'] = [event for event in events if any(value in event['message'] for value in ids.values())]
        return all(any(value in event['message'] and 'notification_delivered' in event['message'] for event in events) for value in ids.values())
    wait_for('automatic and explicit SES simulator delivery', delivered, 120, 3)
    verify('checkout, return and explicit intake actually delivered through Lambda/SES', True)
    for kind in ('LoanIssued','LoanReturned'):
        timestamp = fixture['checked_out_at'] if kind == 'LoanIssued' else fixture['returned_at']
        receipt = api('notification','/notifications','POST',{'event_id':ids[kind],'event_type':kind,'recipient':'success@simulator.amazonses.com','member_id':fixture['member_id'],'occurred_at':timestamp,'body':'Stable-ID replay audit'},202)
        verify(kind + ' replay preserves notification ID', receipt['notification_id'] == ids[kind])
    def suppressed():
        events = logs()
        evidence['events'] = [event for event in events if any(value in event['message'] for value in ids.values())]
        return all(any(ids[kind] in event['message'] and 'notification_duplicate' in event['message'] for event in events) for kind in ('LoanIssued','LoanReturned'))
    wait_for('Lambda stable-ID duplicate suppression', suppressed, 120, 3)
    for kind,value in ids.items():
        verify(kind + ' has exactly one observed SES delivery', sum(value in event['message'] and 'notification_delivered' in event['message'] for event in evidence['events']) == 1)
    snapshot()



FINE_FIXTURE_CODE = r'''
"""Run inside the deployed Fine container; use only an isolated temporary DB.

PowerShell from repository root:
  Get-Content digital-library/scripts/verify-overdue-fixture.py -Raw |
    kubectl --kubeconfig digital-library/.local/recovery-kubeconfig -n library exec -i deployment/fine -- python -

This exercises deployed code over loopback HTTP, not the public ingress or RDS.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy import create_engine
import uvicorn

import app.main
from app.main import configured_daily_fine_cents, create_app
from app.models import Base, Loan


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, force=True)
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "scope": "deployed Fine code, isolated SQLite, loopback HTTP; no production DB access",
        "source_sha256": hashlib.sha256(Path(app.main.__file__).read_bytes()).hexdigest(),
        "cases": [],
    }
    rate = configured_daily_fine_cents()
    assert rate > 0, "Positive fine demonstration requires a positive configured rate"
    with TemporaryDirectory(prefix="fine-fixture-") as directory:
        engine = create_engine(f"sqlite:///{directory}/fixture.db", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        due = datetime(2026, 1, 1, tzinfo=timezone.utc)
        cases = [
            ("returned_partial_day", due, due + timedelta(days=2, seconds=1), 3),
            ("active_overdue", datetime.now(timezone.utc) - timedelta(days=2, minutes=1), None, 3),
            ("returned_on_time", due, due, 0),
        ]
        fixtures = []
        with engine.begin() as connection:
            for name, due_at, returned_at, expected_days in cases:
                loan_id = uuid4()
                connection.execute(Loan.__table__.insert().values(
                    loan_id=loan_id, due_at=due_at, returned_at=returned_at,
                ))
                fixtures.append((name, loan_id, expected_days))

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(engine=engine), log_level="error", access_log=False))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError("Isolated fixture HTTP server failed to start")
                time.sleep(0.05)
            for name, loan_id, expected_days in fixtures:
                with urlopen(f"http://127.0.0.1:{port}/loans/{loan_id}/fine", timeout=10) as response:
                    result = json.load(response)
                    assert response.status == 200
                assert result["overdue_days"] == expected_days, result
                assert result["daily_fine_cents"] == rate, result
                assert result["fine_amount_cents"] == expected_days * rate, result
                report["cases"].append({"name": name, "http_status": 200, "response": result, "passed": True})
            try:
                urlopen(f"http://127.0.0.1:{port}/loans/{uuid4()}/fine", timeout=10)
            except HTTPError as error:
                assert error.code == 404
                report["cases"].append({"name": "missing_loan", "http_status": error.code, "passed": True})
            else:
                raise AssertionError("Missing loan must return 404")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()
            engine.dispose()
            assert not thread.is_alive(), "Fixture server did not stop"
    report["temporary_database_removed"] = not Path(directory).exists()
    assert report["temporary_database_removed"]
    report["status"] = "PASS"
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
'''


def run_fine_suite():
    output = kube("-n", "library", "exec", "-i", "deployment/fine", "--", "python", "-", input_text=FINE_FIXTURE_CODE, raw=True)
    report = json.loads(output)
    REPORT["fine_fixture"] = report
    verify("isolated deployed-code positive overdue fine HTTP fixture", report["status"] == "PASS" and len(report["cases"]) == 4 and all(case["passed"] for case in report["cases"]))
    verify("isolated fine fixture temporary database removed", report["temporary_database_removed"])


class DemoStopped(Exception):
    """The presenter chose to finish before starting another demo."""


def wait_for_enter(name, index, total):
    title,description = DEMO_STEPS[name]
    print(f'\n[{index}/{total}] {title}\n{description}', flush=True)
    if ARGS.auto:
        return
    while True:
        try:
            choice = input('Press Enter to run this demo, or q to finish: ').strip().lower()
        except EOFError as error:
            raise DemoStopped('Input ended; no further demos were started.') from error
        if not choice:
            return
        if choice in {'q','quit','exit'}:
            raise DemoStopped('Presenter finished the demo.')
        print('Press Enter without typing to continue, or type q to finish.', flush=True)


def show_results(name):
    keys = {'api':'fixtures','grpc':'grpc','fine':'fine_fixture','notifications':'notifications','metrics':'prometheus','flink':'flink','hpa':'autoscaling'}
    print(json.dumps({name: REPORT.get(keys[name], {})}, indent=2), flush=True)


def main(argv=None):
    global CLEANING_UP
    CLEANING_UP = False
    if not configure(argv):
        return 0
    suites = {'api':run_api_suite,'grpc':run_grpc_suite,'fine':run_fine_suite,'notifications':run_notifications_suite,'metrics':run_metrics_suite,'flink':run_flink_suite,'hpa':run_hpa_suite}
    print('DIGITAL LIBRARY LIVE DEMO ' + RUN, flush=True)
    print('Mode: ' + ('automatic' if ARGS.auto else 'press Enter before each demo; q finishes safely'), flush=True)
    print('Target: ' + BASE, flush=True)
    print('The Flink/HPA demos use existing compute; HPA includes a scale-down wait.', flush=True)
    REPORT['selected_sections'] = SECTIONS
    REPORT['status'] = 'RUNNING'
    snapshot()
    try:
        for index,name in enumerate(SECTIONS,1):
            wait_for_enter(name, index, len(SECTIONS))
            section = REPORT['sections'][name] = {'status':'RUNNING','started_at':datetime.now(timezone.utc).isoformat()}
            assertions_before = len(REPORT['assertions'])
            started = time.monotonic()
            print('Running ' + DEMO_STEPS[name][0] + '...', flush=True)
            snapshot()
            try:
                if name in {'metrics','hpa'}:
                    with prometheus_forward(): suites[name]()
                else:
                    suites[name]()
                section['status'] = 'PASS'
                show_results(name)
            except DemoStopped:
                section['status'] = 'STOPPED'
                raise
            except KeyboardInterrupt:
                section['status'] = 'INTERRUPTED'
                raise
            except Exception as error:
                section['status'] = 'FAIL'
                section['failure'] = str(error)
                (ARTIFACTS / (name + '-failure.txt')).write_text(traceback.format_exc(), encoding='utf-8')
                print('FAIL ' + name + ': ' + str(error)[:1200], flush=True)
            finally:
                section['finished_at'] = datetime.now(timezone.utc).isoformat()
                section['duration_seconds'] = round(time.monotonic() - started, 2)
                section['assertion_count'] = len(REPORT['assertions']) - assertions_before
                print(json.dumps({'demo':name,'completed':section['status']=='PASS','duration_seconds':section['duration_seconds']}),flush=True)
                snapshot()
    except DemoStopped as error:
        REPORT['stopped_early'] = True
        print(str(error), flush=True)
    except KeyboardInterrupt:
        REPORT['interrupted'] = True
        print('\nDemo interrupted; cleaning up demo loans, holds and owned work.', flush=True)
    finally:
        CLEANING_UP = True
        for lid in ACTIVE_LOANS:
            try: api('lending',f'/loans/{lid}/return','POST')
            except Exception as error: REPORT['cleanup_warnings'].append('Loan cleanup: ' + str(error))
        for rid in RESERVATIONS:
            try:
                current = api('reservation',f'/reservations/{rid}')
                if current['status'] != 'CANCELLED': api('reservation',f'/reservations/{rid}','DELETE')
            except Exception as error: REPORT['cleanup_warnings'].append('Hold cleanup: ' + str(error))
        failed = REPORT['cleanup_warnings'] or any(section['status'] in {'FAIL','RUNNING'} for section in REPORT['sections'].values())
        if REPORT.get('interrupted'):
            REPORT['status'] = 'INTERRUPTED'
        elif failed:
            REPORT['status'] = 'FAIL'
        elif REPORT.get('stopped_early'):
            REPORT['status'] = 'STOPPED'
        else:
            REPORT['status'] = 'PASS' if len(REPORT['sections']) == len(SECTIONS) else 'FAIL'
        snapshot()
        load_requests = sum(load['requests'] for load in REPORT.get('autoscaling',{}).get('load',{}).values())
        print(json.dumps({'result':REPORT['status'],'sections':REPORT['sections'],'http_checks':len(REPORT['requests']),'load_requests':load_requests,'assertions':len(REPORT['assertions']),'report':str(ROOT / 'demo-report.json'),'cleanup_warnings':REPORT['cleanup_warnings']},indent=2),flush=True)
    return 130 if REPORT.get('interrupted') else 0 if REPORT['status'] in {'PASS','STOPPED'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
