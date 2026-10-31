// Share images for the headline cards: the card's text over the chart of its pair, with the card's flows lit.
//   node scripts/render_share.js [siteDir]   ->  <siteDir>/share/<headline id>.png
// The page offers each image from the card's "תמונה" button.
const http = require('http'), fs = require('fs'), path = require('path');
const { chromium } = require('playwright');

const site = path.resolve(process.argv[2] || path.join(__dirname, '../out/site'));
const out = path.join(site, 'share');
fs.mkdirSync(out, { recursive: true });
const types = { '.html': 'text/html; charset=utf-8', '.json': 'application/json', '.png': 'image/png' };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') {
    const body = fs.readFileSync(path.join(site, 'index.html'), 'utf8');
    res.writeHead(200, { 'content-type': types['.html'] });
    return res.end('<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0}</style></head><body>' + body + '</body></html>');
  }
  const f = path.join(site, p);
  if (!f.startsWith(site) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(res);
});

(async () => {
  await new Promise(r => server.listen(0, r));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1.5, colorScheme: 'light' });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  // the CDN is sometimes slow to go quiet
  await page.goto(`http://localhost:${server.address().port}/`, { waitUntil: 'networkidle', timeout: 90000 });
  await page.waitForTimeout(800);
  const hs = JSON.parse(fs.readFileSync(path.join(site, 'headlines.json'), 'utf8')).filter(h => h.id && h.pair);
  for (const h of hs) {
    await page.evaluate(async h => {
      // only this pair, wide enough to read, flows lit
      VIEWS.poster = [h.pair]; state.view = 'poster'; state.area = h.area; $('area').value = h.area;
      $('th').value = 7; $('nv').checked = true; $('stay').checked = true;
      await load();
      const [a, z] = h.pair.split('-').map(Number), want = new Set(h.links.map(l => l.join('|')));
      const hit = d => d.a === a && d.b === z && want.has(d.sn + '|' + d.tn);
      while (+$('th').value > 0 && svg.selectAll('path.lk').filter(hit).size() < want.size) { $('th').value = +$('th').value - 1; draw(); }
      svg.classed('dim', true); svg.selectAll('path.lk').classed('on', hit);
      // an area with cards of its own (headlines_by_area.json) would replace the national card being drawn
      if (!document.getElementById('h-' + h.id) && typeof BYAREA !== 'undefined') { const keep = BYAREA; BYAREA = {}; areaHeadlines(); BYAREA = keep; }
      const card = document.getElementById('h-' + h.id);
      const p = document.createElement('div'); p.id = 'poster';
      p.style.cssText = 'position:absolute;top:0;left:0;width:1200px;background:#fff;box-shadow:0 0 0 8px #fff;color:#15202b;direction:rtl;padding:36px 44px 24px;box-sizing:border-box;display:grid;gap:10px;font-family:var(--body);z-index:9';
      const c = card.cloneNode(true); c.querySelector('.foot').remove(); c.querySelector('input.link')?.remove();
      c.style.cssText = 'border:0;padding:0;background:none';
      c.querySelector('.big').style.fontSize = '64px'; c.querySelector('h3').style.fontSize = '34px';
      c.querySelectorAll('p').forEach(x => { x.style.fontSize = '20px'; x.style.maxWidth = '70ch'; });
      const ch = $('chart').cloneNode(true); ch.removeAttribute('id'); ch.style.cssText = 'width:100%;height:auto;direction:ltr';
      const f = document.createElement('div');
      f.style.cssText = 'display:flex;justify-content:space-between;font-size:15px;color:#7a8592;border-top:1px solid #dde2e8;padding-top:8px';
      f.innerHTML = `<span>נדידת הקולות בישראל · ${h.area_name}</span><span>הערכה לפי תוצאות הקלפיות</span>`;
      p.append(c, ch, f); document.body.appendChild(p);
    }, h);
    // the chart's rules are written for #chart, so the clone takes its computed look
    await page.evaluate(() => {
      const src = [...document.querySelectorAll('#chart *')], dst = [...document.querySelectorAll('#poster svg *')];
      const props = ['fill', 'stroke', 'stroke-opacity', 'stroke-width', 'opacity', 'font-size', 'font-weight', 'font-family', 'paint-order', 'stroke-linejoin', 'display'];
      dst.forEach((el, i) => { const cs = getComputedStyle(src[i]); for (const k of props) el.style.setProperty(k, cs.getPropertyValue(k)); });
    });
    await (await page.$('#poster')).screenshot({ path: path.join(out, h.id + '.png') });
    await page.evaluate(() => document.getElementById('poster').remove());
    console.log('wrote share/' + h.id + '.png');
  }
  if (errors.length) console.log('page errors:', errors);
  await browser.close();
  server.close();
})();
