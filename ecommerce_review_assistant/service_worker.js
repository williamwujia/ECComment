let queue = [];
let collected = [];
let workerTabId = null;
let outcomes = [];
let lastActivityAt = 0;
let authPaused = false;
let hydrated = false;

const WATCHDOG_ALARM = 'ecom-scrape-watchdog';
const STALE_AFTER_MS = 90_000;
const STATE_KEYS = [
  'ecomQueue',
  'ecomCollected',
  'ecomWorkerTabId',
  'ecomOutcomes',
  'ecomLastActivityAt',
  'ecomAuthPaused'
];

async function hydrateState() {
  if (hydrated) return;
  const saved = await chrome.storage.local.get(STATE_KEYS);
  queue = Array.isArray(saved.ecomQueue) ? saved.ecomQueue : [];
  collected = Array.isArray(saved.ecomCollected) ? saved.ecomCollected : [];
  workerTabId = Number.isInteger(saved.ecomWorkerTabId) ? saved.ecomWorkerTabId : null;
  outcomes = Array.isArray(saved.ecomOutcomes) ? saved.ecomOutcomes : [];
  lastActivityAt = Number(saved.ecomLastActivityAt || 0);
  authPaused = Boolean(saved.ecomAuthPaused);
  hydrated = true;
}

async function persistState() {
  await chrome.storage.local.set({
    ecomQueue: queue,
    ecomCollected: collected,
    ecomWorkerTabId: workerTabId,
    ecomOutcomes: outcomes,
    ecomLastActivityAt: lastActivityAt,
    ecomAuthPaused: authPaused
  });
}

function touchActivity() {
  lastActivityAt = Date.now();
  chrome.storage.local.set({ecomLastActivityAt: lastActivityAt});
}

function rowKey(row) {
  return [
    row?.platform,
    row?.product_id,
    row?.platform_content_id,
    row?.user_name_masked,
    row?.review_time,
    row?.review_date,
    row?.sku,
    row?.review_text_raw
  ].join('|');
}

function mergeCollected(rows) {
  const known = new Set(collected.map(rowKey));
  let added = 0;
  for (const row of Array.isArray(rows) ? rows : []) {
    const key = rowKey(row);
    if (!row?.review_text_raw || known.has(key)) continue;
    known.add(key);
    collected.push(row);
    added++;
  }
  return added;
}

function rowsForTarget(url) {
  return collected.filter(row => row.product_url === url);
}

function setStatus(value) {
  chrome.storage.local.set({ecomScrapeStatus: value});
  chrome.action.setBadgeText({text: queue.length ? String(queue.length) : ''});
  chrome.action.setBadgeBackgroundColor({color: authPaused ? '#d97706' : '#1677ff'});
}

function targetIdentity(urlValue) {
  const url = new URL(urlValue);
  const host = url.hostname.toLowerCase();
  if (host === 'item.jd.com') {
    const id = (url.pathname.match(/\/(\d+)\.html$/) || [])[1] || '';
    return id ? {platform: 'jd', productId: id} : null;
  }
  if (
    host === 'item.taobao.com'
    || host === 'detail.tmall.com'
    || host === 'chaoshi.detail.tmall.com'
    || host === 'detail.tmall.hk'
  ) {
    const id = url.searchParams.get('id') || url.searchParams.get('itemId') || '';
    if (!/^\d+$/.test(id)) return null;
    return {platform: host === 'item.taobao.com' ? 'taobao' : 'tmall', productId: id};
  }
  return null;
}

function parseTargets(text) {
  return text.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map((line, index) => {
    const parts = line.split(/[,\t]/).map(value => value.trim());
    const url = parts[0];
    const count = Number(parts[1]);
    let identity;
    try {
      identity = targetIdentity(url);
    } catch (_) {
      identity = null;
    }
    if (!identity) throw new Error(`第 ${index + 1} 行不是受支持的淘宝、天猫或京东商品 URL`);
    if (!Number.isInteger(count) || count <= 0 || count > 2000) {
      throw new Error(`第 ${index + 1} 行数量无效，必须是 1–2000`);
    }
    return {url, count, ...identity};
  });
}

function csvCell(value) {
  return `"${String(value ?? '').replaceAll('"', '""')}"`;
}

function utf8Base64(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = '';
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

async function downloadResults() {
  const columns = [
    'platform',
    'product_id',
    'product_url',
    'product_title',
    'shop_name',
    'platform_content_id',
    'user_name_masked',
    'rating',
    'review_time',
    'review_date',
    'sku',
    'review_text_raw'
  ];
  const lines = [
    columns.join(','),
    ...collected.map(row => columns.map(key => csvCell(row[key])).join(','))
  ];
  const stamp = new Date().toISOString().replaceAll(/[-:TZ.]/g, '').slice(0, 14);
  const csv = '\ufeff' + lines.join('\r\n');
  await chrome.downloads.download({
    url: `data:text/csv;charset=utf-8;base64,${utf8Base64(csv)}`,
    filename: `ecommerce_reviews_${stamp}.csv`,
    saveAs: false
  });
}

async function clearRunState() {
  queue = [];
  collected = [];
  outcomes = [];
  workerTabId = null;
  lastActivityAt = 0;
  authPaused = false;
  await chrome.storage.local.remove(STATE_KEYS);
}

async function runNext() {
  await hydrateState();
  if (!queue.length) {
    if (collected.length) await downloadResults();
    const details = outcomes.map(item =>
      `${item.platform}:${item.productId || item.url}：要求 ${item.requested}，实际 ${item.actual}` +
      (item.failed
        ? `（中途失败：${item.error || '未知原因'}；已保存现有结果）`
        : item.actual < item.requested ? '（评论已到底，未达标）' : '')
    ).join('\n');
    const total = collected.length;
    await clearRunState();
    setStatus(
      `任务完成，共采集 ${total} 条。\n${details}` +
      (total ? '\nCSV 已开始下载，可上传到服务器“数据更新”。' : '\n没有可下载的评论。')
    );
    return;
  }
  const target = queue[0];
  authPaused = false;
  touchActivity();
  setStatus(
    `正在打开 ${target.platform}:${target.productId}\n` +
    `剩余商品：${queue.length}，已采集：${collected.length}`
  );
  if (workerTabId) {
    try {
      const currentTab = await chrome.tabs.get(workerTabId);
      if (currentTab.url === target.url) await chrome.tabs.reload(workerTabId);
      else await chrome.tabs.update(workerTabId, {url: target.url, active: true});
      await persistState();
      return;
    } catch (_) {
      workerTabId = null;
    }
  }
  const tab = await chrome.tabs.create({url: target.url, active: true});
  workerTabId = tab.id;
  await persistState();
}

async function pauseForLogin() {
  await hydrateState();
  authPaused = true;
  lastActivityAt = 0;
  await persistState();
  const target = queue[0];
  setStatus(
    `需要登录后继续：${target?.platform || ''}:${target?.productId || ''}\n` +
    '请在当前商品/登录页扫码。登录成功后会自动重试，也可点击“登录后继续”。'
  );
}

async function failCurrentTarget(url, error) {
  await hydrateState();
  if (!queue.length || queue[0].url !== url) return;
  const target = queue[0];
  const actual = rowsForTarget(url).length;
  outcomes.push({
    url,
    platform: target.platform,
    productId: target.productId,
    requested: Number(target.count || 0),
    actual,
    failed: true,
    error
  });
  queue.shift();
  authPaused = false;
  lastActivityAt = Date.now();
  await persistState();
  setStatus(`${target.platform}:${target.productId} 失败：${error}\n此前采集的 ${actual} 条已保存，将继续下一个商品。`);
  await runNext();
}

async function startScrapeWithRetry(tabId, target) {
  for (let attempt = 1; attempt <= 5; attempt++) {
    await new Promise(resolve => setTimeout(resolve, attempt === 1 ? 1800 : 1000));
    try {
      const response = await chrome.tabs.sendMessage(tabId, {
        type: 'SCRAPE',
        target: {...target, checkpointRows: rowsForTarget(target.url)}
      });
      if (response?.authRequired) {
        await pauseForLogin();
        return;
      }
      if (response?.started) {
        authPaused = false;
        touchActivity();
        await persistState();
        return;
      }
    } catch (_) {
      // The content script may not have reached document_idle yet.
    }
    setStatus(`正在等待第 ${attempt}/5 次加载页面脚本\n${target.platform}:${target.productId}`);
  }
  await failCurrentTarget(target.url, '页面脚本连续 5 次未就绪');
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;
  (async () => {
    await hydrateState();
    if (tabId !== workerTabId || !queue.length) return;
    await startScrapeWithRetry(tabId, queue[0]);
  })();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'START_QUEUE') {
    (async () => {
      try {
        await hydrateState();
        queue = parseTargets(message.text);
        if (!queue.length) throw new Error('请至少输入一个商品');
        collected = [];
        outcomes = [];
        authPaused = false;
        lastActivityAt = Date.now();
        await persistState();
        setStatus(`任务已开始，共 ${queue.length} 个商品`);
        await runNext();
        sendResponse({message: '任务已开始，弹窗可以关闭。'});
      } catch (error) {
        setStatus(error.message);
        sendResponse({message: error.message});
      }
    })();
    return true;
  }
  if (message.type === 'START_CURRENT_PAGE') {
    (async () => {
      try {
        await hydrateState();
        const identity = targetIdentity(message.url);
        const count = Number(message.count);
        if (!identity) throw new Error('当前标签页不是受支持的淘宝、天猫或京东商品页。');
        if (!Number.isInteger(count) || count <= 0 || count > 2000) {
          throw new Error('数量无效，必须是 1–2000。');
        }
        queue = [{url: message.url, count, allowDocumentScroll: true, ...identity}];
        collected = [];
        outcomes = [];
        workerTabId = Number(message.tabId);
        authPaused = false;
        lastActivityAt = Date.now();
        await persistState();
        setStatus(`正在采集当前页 ${identity.platform}:${identity.productId}\n目标：${count} 条`);
        await startScrapeWithRetry(workerTabId, queue[0]);
        sendResponse({message: '已开始采集当前商品页，弹窗可以关闭。'});
      } catch (error) {
        setStatus(error.message);
        sendResponse({message: error.message});
      }
    })();
    return true;
  }
  if (message.type === 'RESUME_QUEUE') {
    (async () => {
      await hydrateState();
      if (!queue.length) {
        sendResponse({message: '当前没有待继续的任务。'});
        return;
      }
      authPaused = false;
      lastActivityAt = Date.now();
      await persistState();
      await runNext();
      sendResponse({message: '正在重新打开当前商品并继续。'});
    })();
    return true;
  }
  if (message.type === 'CANCEL_QUEUE') {
    (async () => {
      await hydrateState();
      const kept = collected.length;
      if (kept) await downloadResults();
      await clearRunState();
      setStatus(kept ? `任务已取消，已下载此前采集的 ${kept} 条评论。` : '任务已取消。');
      sendResponse({message: kept ? `已取消并下载 ${kept} 条评论。` : '任务已取消。'});
    })();
    return true;
  }
  if (message.type === 'PROGRESS') {
    (async () => {
      await hydrateState();
      if (!queue.length || queue[0].url !== message.url) return;
      touchActivity();
      setStatus(`${queue[0].platform}:${queue[0].productId}\n已采集 ${message.count}/${message.target} 条`);
    })();
    return;
  }
  if (message.type === 'CHECKPOINT') {
    (async () => {
      try {
        await hydrateState();
        if (!queue.length || queue[0].url !== message.url) {
          sendResponse({saved: false, error: '当前商品与采集队列不一致'});
          return;
        }
        const added = mergeCollected(message.rows);
        lastActivityAt = Date.now();
        await persistState();
        setStatus(`${queue[0].platform}:${queue[0].productId}\n已采集 ${message.count}/${message.target} 条；本轮新增 ${added} 条已保存`);
        sendResponse({saved: true, added});
      } catch (error) {
        setStatus(`${message.url}\n保存检查点失败：${error.message}`);
        sendResponse({saved: false, error: error.message});
      }
    })();
    return true;
  }
  if (message.type === 'DONE') {
    (async () => {
      await hydrateState();
      if (!queue.length || queue[0].url !== message.url) return;
      const target = queue[0];
      mergeCollected(message.rows);
      outcomes.push({
        url: message.url,
        platform: target.platform,
        productId: message.productId || target.productId,
        requested: Number(message.requested || target.count || 0),
        actual: message.rows.length
      });
      queue.shift();
      authPaused = false;
      lastActivityAt = Date.now();
      await persistState();
      const requested = Number(message.requested || 0);
      setStatus(
        message.rows.length < requested
          ? `${target.platform}:${target.productId} 评论已到底：要求 ${requested} 条，实际 ${message.rows.length} 条；继续下一个商品。`
          : `${target.platform}:${target.productId} 完成：${message.rows.length}/${requested} 条`
      );
      await runNext();
    })();
    return;
  }
  if (message.type === 'FAILED') {
    (async () => failCurrentTarget(message.url, message.error))();
  }
});

chrome.alarms.create(WATCHDOG_ALARM, {periodInMinutes: 1});
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name !== WATCHDOG_ALARM) return;
  (async () => {
    await hydrateState();
    if (!queue.length || !lastActivityAt || authPaused) return;
    if (Date.now() - lastActivityAt < STALE_AFTER_MS) return;
    await failCurrentTarget(queue[0].url, '超过 90 秒没有收到采集进度，已由看门狗结束');
  })();
});

async function recoverUnfinishedQueue() {
  await hydrateState();
  if (!queue.length || authPaused) return;
  if (!workerTabId) {
    await runNext();
    return;
  }
  try {
    const response = await chrome.tabs.sendMessage(workerTabId, {type: 'PING_SCRAPER'});
    if (response?.authRequired) {
      await pauseForLogin();
      return;
    }
    if (response?.active && response.url === queue[0].url) {
      touchActivity();
      setStatus(`${queue[0].platform}:${queue[0].productId}\n检测到采集仍在运行，已恢复后台监控。`);
      return;
    }
  } catch (_) {
    // Extension reloads invalidate the old content script; reload to inject the current one.
  }
  setStatus(`${queue[0].platform}:${queue[0].productId}\n检测到未完成任务，正在从本地检查点恢复。`);
  try {
    await chrome.tabs.reload(workerTabId);
  } catch (_) {
    workerTabId = null;
    await persistState();
    await runNext();
  }
}

recoverUnfinishedQueue();
