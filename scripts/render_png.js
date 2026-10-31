// Render images for the LinkedIn post from the built night site (out/site_live), with no network beyond the CDNs.
//   node scripts/render_png.js [siteDir] [outDir]
// Writes: flows_2022_2026.png (national flow chart, 2022 to 2026 only), seats_2026.png (the seat bars),
// and flows_<area>_2022_2026.png for each area id given in AREAS below.
const http = require('http'), fs = require('fs'), path = require('path');
const { chromium } = require('playwright');

const site = path.resolve(process.argv[2] || path.join(__dirname, '../out/site_live'));
const out = path.resolve(process.argv[3] || path.join(__dirname, '../out/live/png'));
const AREAS = ['national', 'sector:haredi', 'sector:arab', 'sector:general', '5000', '3000', '4000', '9000'];
fs.mkdirSync(out, { recursive: true });

const types = { '.html': 'text/html; charset=utf-8', '.json': 'application/json', '.js': 'text/javascript' };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/page.html';
  const f = path.join(site, p);
  if (p === '/page.html') {
    // the published page gets its document skeleton from the host; add one here
    const body = fs.readFileSync(path.join(site, 'index.html'), 'utf8');
    res.writeHead(200, { 'content-type': types['.html'] });
    return res.end('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>body{margin:0}</style></head><body>' + body + '</body></html>');
  }
  if (!f.startsWith(site) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(res);
});

(async () => {
  await new Promise(r => server.listen(0, r));
  const base = `http://localhost:${server.address().port}/`;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 1100 }, deviceScaleFactor: 2, colorScheme: 'light' });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  // the seat bars sit in a collapsible card on the night page; open it for the picture
  await page.evaluate(() => { const d = document.getElementById('seats-box'); if (d) d.open = true; });
  await page.waitForTimeout(300);
  await (await page.$('#seats-box, section.seats')).screenshot({ path: path.join(out, 'seats_2026.png') });
  // two columns only: 2022 and 2026; no "stayed" filter, so the chart reads as the whole electorate
  for (const id of AREAS) {
    const ok = await page.evaluate(async id => {
      VIEWS.full = ['25-26']; state.view = 'full'; state.area = id;
      document.getElementById('th').value = 2;
      await load();
      return !!(state.data && state.data.pairs['25-26']);
    }, id);
    if (!ok) { console.log('skip (no 2026 data):', id); continue; }
    await page.waitForTimeout(500);
    const name = id === 'national' ? 'flows_2022_2026.png' : `flows_${id.replace(':', '-')}_2022_2026.png`;
    // poster layout: hide the controls and notes, title the card for a feed
    await page.evaluate(() => {
      for (const sel of ['.bar', '#ses-ctl', '.card .note', '#insights', '#status']) document.querySelectorAll(sel).forEach(e => e.hidden = true);
      const d = state.data;
      document.getElementById('area-name').textContent = (d.kind === 'national' ? 'כל הארץ' : d.name) + ': לאן עברו הקולות מ-2022 ל-2026';
      document.getElementById('area-meta').textContent = 'הערכה לפי תוצאות הקלפיות. עובי הרצועה הוא מספר הקולות.';
    });
    const card = await page.$('section.card[aria-label="תרשים נדידת קולות"]');
    await card.screenshot({ path: path.join(out, name) });
    await page.evaluate(() => document.querySelectorAll('[hidden]').forEach(e => { if (!['live-banner','ses-ctl','status','tip','insights'].includes(e.id)) e.hidden = false; }));
    console.log('wrote', name);
  }
  if (errors.length) console.log('page errors:', errors);
  await browser.close();
  server.close();
})();
