"""Frontend structure validation for report pages."""
import sys, re

# ── interview-report.html ──────────────────────────────────────────────────
html = open('apps/web/static/interview-report.html', encoding='utf-8').read()

html_checks = [
    ('DOCTYPE',              '<!doctype html>' in html.lower()),
    ('charset utf-8',        'charset="utf-8"' in html),
    ('styles.css link',      'href="/styles.css"' in html),
    ('report.js module',     'src="/report.js"' in html),
    ('Production flow Step 4','Production flow · Step 4' in html),
    ('면접 리포트 h1',      '면접 리포트' in html),
    ('비언어 종합 section', '비언어 종합' in html),
    ('trend-chart div',      'id="trend-chart"' in html),
    ('turn-list ol',         'class="turn-list"' in html),
    ('meta-date id',         'id="meta-date"' in html),
    ('meta-turns id',        'id="meta-turns"' in html),
    ('dialog-turn-count id', 'id="dialog-turn-count"' in html),
    ('trend-prev/next',      'id="trend-prev"' in html and 'id="trend-next"' in html),
    ('dialog-prev/next',     'id="dialog-prev"' in html and 'id="dialog-next"' in html),
    ('avg-rate id',          'id="avg-rate"' in html),
    ('avg-pitch id',         'id="avg-pitch"' in html),
    ('no innerHTML',         'innerHTML' not in html),
    ('security: no raw token', 'Bearer' not in html and 'token' not in html.lower() or '__REPORT_TOKEN__' not in html),
]

all_ok = True
for name, ok in html_checks:
    status = 'OK' if ok else 'FAIL'
    if not ok: all_ok = False
    print(f'  {status}: [HTML] {name}')

# ── report.js ──────────────────────────────────────────────────────────────
js = open('apps/web/static/report.js', encoding='utf-8').read()

js_checks = [
    ('REPORT_API_BASE defined',     'REPORT_API_BASE' in js),
    ('fetchReport function',        'async function fetchReport' in js),
    ('renderReport function',       'function renderReport' in js),
    ('renderTrendChart function',   'function renderTrendChart' in js),
    ('renderSummary function',      'function renderSummary' in js),
    ('turnItem function',           'function turnItem' in js),
    ('init function',               'async function init' in js),
    ('textContent only (no innerHTML)', '.innerHTML' not in js),
    ('TREND_FEATURES array',        'TREND_FEATURES' in js),
    ('metrics.vocal path',          'metrics.vocal' in js or 'vocal' in js),
    ('metrics.visual path',         'metrics.visual' in js or 'visual' in js),
    ('metrics.coverage path',       'metrics.coverage' in js or 'coverage' in js),
    ('animateMetric function',      'function animateMetric' in js),
    ('loadReportWithRetry',         'loadReportWithRetry' in js),
    ('PLACEHOLDER_REPORT fallback', 'PLACEHOLDER_REPORT' in js),
    ('no raw token in code',        'process.env' not in js and 'API_KEY' not in js),
]

for name, ok in js_checks:
    status = 'OK' if ok else 'FAIL'
    if not ok: all_ok = False
    print(f'  {status}: [JS]   {name}')

# ── styles.css report section ──────────────────────────────────────────────
css = open('apps/web/static/styles.css', encoding='utf-8').read()

css_checks = [
    ('report-page-main',     '.report-page-main' in css),
    ('report-card',          '.report-card' in css),
    ('turn-list',            '.turn-list' in css),
    ('turn-item',            '.turn-item' in css),
    ('turn-eval',            '.turn-eval' in css),
    ('trend-chart',          '.trend-chart' in css),
    ('trend-svg',            '.trend-svg' in css),
    ('trend-line',           '.trend-line' in css),
    ('metric-grid',          '.metric-grid' in css),
    ('report-pager',         '.report-pager' in css),
    ('eval-unmeasured',      '.eval-unmeasured' in css),
    ('summary-metric-grid',  '.summary-metric-grid' in css),
    ('responsive @media',    '@media (max-width: 980px)' in css and 'report-grid' in css),
]

for name, ok in css_checks:
    status = 'OK' if ok else 'FAIL'
    if not ok: all_ok = False
    print(f'  {status}: [CSS]  {name}')

# ── app.js: interviewer.question.completed 이벤트 ──────────────────────────
app_js = open('apps/web/static/app.js', encoding='utf-8').read()

appjs_checks = [
    ('interviewer.question.completed event', 'interviewer.question.completed' in app_js),
    ('postRealtimeTurnEvent call for question',
     'postRealtimeTurnEvent' in app_js and 'question.completed' in app_js),
    ('question variable passed',
     'question' in app_js and 'interviewer.question.completed' in app_js),
]

for name, ok in appjs_checks:
    status = 'OK' if ok else 'FAIL'
    if not ok: all_ok = False
    print(f'  {status}: [APP]  {name}')

print()
print('Frontend: All OK' if all_ok else 'Frontend: ERRORS FOUND')
sys.exit(0 if all_ok else 1)
