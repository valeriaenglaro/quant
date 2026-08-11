// E2E browser verification for the QuantSuite terminal (run with: node e2e_test.js)
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium/chrome-linux/chrome' }).catch(() => chromium.launch());
  const pg = await b.newPage({ viewport: { width: 1660, height: 1150 } });
  const errs = [];
  pg.on('pageerror', e => errs.push('PAGEERROR: ' + e.message));
  await pg.goto('http://localhost:8002/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await pg.waitForTimeout(1400);

  // 1 · defaults check
  const defs = await pg.evaluate(() => ({
    solveFor: document.getElementById('solveFor').value,
    barrier: document.getElementById('barrierType').value,
    cpnType: document.getElementById('couponType').value,
    cpnFreq: document.getElementById('couponFreq').value,
    acFreq: document.getElementById('acFreq').value,
    putStrike: document.getElementById('putStrike').value,
    cpnBar: document.getElementById('couponBarrier').value,
    underlying: document.getElementById('underlying').value,
  }));
  console.log('DEFAULTS:', JSON.stringify(defs));

  // 2 · block order: schedCard before rt-cols?
  const order = await pg.evaluate(() => {
    const s = document.getElementById('schedCard');
    const r = document.querySelector('.rt-cols');
    return !!(s && r && (s.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING));
  });
  console.log('CALENDAR BEFORE JSON/SPREAD:', order);

  // 3 · payoff chart interactive (legend exists, zoom changes view)
  const payoff = await pg.evaluate(() => {
    const cv = document.getElementById('payoff');
    return { hasChart: !!(cv && cv._qsi), legend: !!document.querySelector('.qsi-legend'), v: cv && cv._qsi ? cv._qsi.v.slice() : null };
  });
  console.log('PAYOFF CHART:', JSON.stringify(payoff));
  if (payoff.hasChart) {
    const box = await pg.locator('#payoff').boundingBox();
    await pg.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await pg.mouse.wheel(0, -240);      // zoom in
    await pg.waitForTimeout(200);
    const v2 = await pg.evaluate(() => document.getElementById('payoff')._qsi.v.slice());
    console.log('ZOOM CHANGED VIEW:', JSON.stringify(payoff.v) !== JSON.stringify(v2), JSON.stringify(v2));
    // pan
    await pg.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await pg.mouse.down(); await pg.mouse.move(box.x + box.width / 2 + 90, box.y + box.height / 2 + 30, { steps: 4 }); await pg.mouse.up();
    const v3 = await pg.evaluate(() => document.getElementById('payoff')._qsi.v.slice());
    console.log('PAN CHANGED VIEW:', JSON.stringify(v2) !== JSON.stringify(v3));
    await pg.dblclick('#payoff');
    const v4 = await pg.evaluate(() => document.getElementById('payoff')._qsi.v.slice());
    console.log('DBLCLICK RESET:', JSON.stringify(v4) === JSON.stringify(payoff.v));
    // drag legend
    const lg = await pg.locator('.qsi-legend').first().boundingBox();
    await pg.mouse.move(lg.x + 40, lg.y + 8);
    await pg.mouse.down(); await pg.mouse.move(lg.x + 140, lg.y + 60, { steps: 4 }); await pg.mouse.up();
    const lg2 = await pg.locator('.qsi-legend').first().boundingBox();
    console.log('LEGEND DRAGGED:', Math.abs(lg2.x - lg.x) > 50);
    // recolour via swatch
    await pg.evaluate(() => {
      const sw = document.querySelector('.qsi-legend .qsi-sw');
      sw.value = '#ff00aa'; sw.dispatchEvent(new Event('input'));
    });
    const col = await pg.evaluate(() => document.getElementById('payoff')._qsi.o.series[0].color);
    console.log('COLOR PICKED:', col);
  }

  // 4 · price on BOTH engines
  await pg.click('#calcBtn');
  await pg.waitForFunction(() => !document.getElementById('calcBtn').disabled, { timeout: 240000 });
  const res = await pg.evaluate(() => ({
    val: document.getElementById('resVal').textContent,
    sub: document.getElementById('resSub').textContent,
    match: (document.getElementById('benchMatch') || {}).textContent,
  }));
  console.log('CALC:', JSON.stringify(res));
  await pg.screenshot({ path: '/tmp/v2_pricing.png' });

  // 5 · risk suite on ngn/k (default 'both' -> k)
  await pg.click('.vs-btn[data-page="pageRisk"]');
  await pg.waitForTimeout(700);
  await pg.click('#rkRunBtn');
  await pg.waitForFunction(() => /Done —|Error/.test((document.getElementById('rkStatus') || {}).textContent || ''), { timeout: 300000 });
  const rk = await pg.evaluate(() => ({
    status: document.getElementById('rkStatus').textContent,
    greeks: document.getElementById('rkGreeks').innerText.split('\n').slice(0, 10).join(' | '),
    varTiles: document.getElementById('rkVar').innerText.replace(/\n/g, ' | '),
    chart: !!(document.getElementById('rkChartCv') && document.getElementById('rkChartCv')._qsi),
  }));
  console.log('RISK:', JSON.stringify(rk, null, 1));
  await pg.screenshot({ path: '/tmp/v2_risk.png' });

  console.log('PAGEERRORS:', errs.slice(0, 8));
  await b.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
