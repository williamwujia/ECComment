let queue = [];
let collected = [];
let workerTabId = null;
let outcomes = [];
let lastActivityAt = 0;
let hydrated = false;
const WATCHDOG_ALARM = 'jd-scrape-watchdog';
const STALE_AFTER_MS = 90_000;

async function hydrateState() {
  if (hydrated) return;
  const saved = await chrome.storage.local.get([
    'jdQueue',
    'jdCollected',
    'jdWorkerTabId',
    'jdOutcomes',
    'jdLastActivityAt'
  ]);
  queue = Array.isArray(saved.jdQueue) ? saved.jdQueue : [];
  collected = Array.isArray(saved.jdCollected) ? saved.jdCollected : [];
  workerTabId = Number.isInteger(saved.jdWorkerTabId) ? saved.jdWorkerTabId : null;
  outcomes = Array.isArray(saved.jdOutcomes) ? saved.jdOutcomes : [];
  lastActivityAt = Number(saved.jdLastActivityAt || 0);
  hydrated = true;
}

async function persistState() {
  await chrome.storage.local.set({
    jdQueue: queue,
    jdCollected: collected,
    jdWorkerTabId: workerTabId,
    jdOutcomes: outcomes,
    jdLastActivityAt: lastActivityAt
  });
}

function touchActivity() {
  lastActivityAt = Date.now();
  chrome.storage.local.set({jdLastActivityAt: lastActivityAt});
}

function rowKey(row) {
  return [
    row?.product_id,
    row?.product_url,
    row?.user_name_masked,
    row?.review_time,
    row?.sku,
    row?.review_text_raw
  ].join('|');
}

function mergeCollected(rows) {
  const known = new Map(collected.map(row => [rowKey(row), row]));
  let added = 0;
  for (const row of Array.isArray(rows) ? rows : []) {
    const key = rowKey(row);
    if (!row?.review_text_raw) continue;
    if (known.has(key)) {
      const existing = known.get(key);
      if (Number(existing.image_count || 0) < Number(row.image_count || 0)) {
        existing.image_count = Number(row.image_count || 0);
        existing.review_images = Array.isArray(row.review_images) ? row.review_images : [];
      }
      continue;
    }
    known.set(key, row);
    collected.push(row);
    added++;
  }
  return added;
}

function rowsForTarget(url) {
  return collected.filter(row => row.product_url === url);
}

function setStatus(value) {
  chrome.storage.local.set({jdScrapeStatus: value});
  chrome.action.setBadgeText({text: queue.length ? String(queue.length) : ''});
  chrome.action.setBadgeBackgroundColor({color: '#e1251b'});
}

function parseTargets(text) {
  return text.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map((line, index) => {
    const parts = line.split(/[,\t]/).map(value => value.trim());
    const url = parts[0];
    const count = Number(parts[1]);
    const parsed = new URL(url);
    if (!/(^|\.)jd\.com$/i.test(parsed.hostname) || !/^\/\d+\.html$/.test(parsed.pathname)) {
      throw new Error(`第 ${index + 1} 行不是京东商品 URL`);
    }
    if (!Number.isInteger(count) || count <= 0) throw new Error(`第 ${index + 1} 行数量无效`);
    return {url, count};
  });
}

function csvCell(value) {
  return `"${String(value ?? '').replaceAll('"', '""')}"`;
}

async function startImagePackageExport(stamp, details) {
  const pending = {stamp, details, retryCount: 0};
  await chrome.storage.local.set({jdPendingImageExport: pending});
  const tab = await chrome.tabs.create({
    url: chrome.runtime.getURL('image_export.html'),
    active: false
  });
  await chrome.storage.local.set({jdImageExportTabId: tab.id});
}

async function downloadResults(details) {
  const columns = ['platform', 'product_id', 'product_url', 'product_title', 'user_name_masked', 'rating', 'review_time', 'sku', 'review_text_raw'];
  const lines = [columns.join(','), ...collected.map(row => columns.map(key => csvCell(row[key])).join(','))];
  const stamp = new Date().toISOString().replaceAll(/[-:TZ.]/g, '').slice(0, 14);
  const csv = '\ufeff' + lines.join('\r\n');
  await chrome.downloads.download({
    url: `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`,
    filename: `jd_reviews_${stamp}.csv`,
    saveAs: false
  });
  await startImagePackageExport(stamp, details);
}

async function runNext() {
  await hydrateState();
  if (!queue.length) {
    const details = outcomes.map(item =>
      `${item.productId || item.url}：要求 ${item.requested}，实际 ${item.actual}` +
      (item.failed ? '（中途失败，已保存现有结果）' : item.actual < item.requested ? '（评论已到底，未达标）' : '')
    ).join('\n');
    const imageCount = collected.reduce((sum, row) => sum + Number(row.image_count || 0), 0);
    setStatus(
      `评论采集完成，共 ${collected.length} 条，识别评论图片 ${imageCount} 张。\n` +
      `${details}\nECComment CSV 已开始下载，图片 ZIP 正在后台生成。`
    );
    await downloadResults(details);
    lastActivityAt = 0;
    await chrome.storage.local.remove([
      'jdQueue',
      'jdWorkerTabId',
      'jdOutcomes',
      'jdLastActivityAt'
    ]);
    return;
  }
  const target = queue[0];
  touchActivity();
  setStatus(`正在打开 ${target.url}\n剩余商品：${queue.length}，已采集：${collected.length}`);
  if (workerTabId) {
    try {
      const currentTab = await chrome.tabs.get(workerTabId);
      if (currentTab.url === target.url) {
        await chrome.tabs.reload(workerTabId);
      } else {
        await chrome.tabs.update(workerTabId, {url: target.url, active: true});
      }
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

async function failCurrentTarget(url, error) {
  await hydrateState();
  if (!queue.length || queue[0].url !== url) return;
  const target = queue[0];
  const actual = rowsForTarget(url).length;
  outcomes.push({
    url,
    productId: (url.match(/\/(\d+)\.html/) || [])[1] || '',
    requested: Number(target.count || 0),
    actual,
    failed: true
  });
  queue.shift();
  lastActivityAt = Date.now();
  await persistState();
  setStatus(
    `${url} 失败：${error}\n` +
    `此前采集的 ${actual} 条已保存，将自动继续下一个商品。`
  );
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
      if (response?.started) {
        touchActivity();
        return;
      }
    } catch (_) {
      // The content script may not have reached document_idle yet.
    }
    setStatus(`正在等待第 ${attempt}/5 次加载页面脚本\n${target.url}`);
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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'IMAGE_EXPORT_READY') {
    (async () => {
      const exportPageUrl = chrome.runtime.getURL('image_export.html');
      if (!String(sender.url || '').startsWith(exportPageUrl)) {
        sendResponse({error: '导出页面来源无效'});
        return;
      }
      const saved = await chrome.storage.local.get(['jdPendingImageExport', 'jdCollected']);
      if (!saved.jdPendingImageExport) {
        sendResponse({error: '没有待处理的图片导出任务'});
        return;
      }
      sendResponse({
        ...saved.jdPendingImageExport,
        rows: Array.isArray(saved.jdCollected) ? saved.jdCollected : []
      });
    })();
    return true;
  }
  if (message.type === 'IMAGE_EXPORT_DONE') {
    (async () => {
      const saved = await chrome.storage.local.get('jdPendingImageExport');
      const pending = saved.jdPendingImageExport || {};
      await chrome.storage.local.remove([
        'jdPendingImageExport', 'jdImageExportTabId', 'jdCollected'
      ]);
      setStatus(
        `全部导出完成：ECComment CSV + 评论图片 ZIP。\n` +
        `评论 ${message.reviewCount || 0} 条，图片成功 ${message.successCount || 0}/${message.imageCount || 0} 张。\n` +
        `${pending.details || ''}`
      );
    })();
    return;
  }
  if (message.type === 'IMAGE_EXPORT_FAILED') {
    (async () => {
      const saved = await chrome.storage.local.get('jdPendingImageExport');
      const pending = saved.jdPendingImageExport;
      await chrome.storage.local.remove('jdImageExportTabId');
      if (pending && Number(pending.retryCount || 0) < 1) {
        pending.retryCount = Number(pending.retryCount || 0) + 1;
        await chrome.storage.local.set({jdPendingImageExport: pending});
        setStatus(`图片包首次生成失败，正在自动重试：${message.error}`);
        const tab = await chrome.tabs.create({
          url: chrome.runtime.getURL('image_export.html'), active: false
        });
        await chrome.storage.local.set({jdImageExportTabId: tab.id});
        return;
      }
      setStatus(
        `ECComment CSV 已导出，但图片 ZIP 生成失败：${message.error}\n` +
        `评论与图片索引仍保存在扩展检查点中，刷新扩展可再次尝试。`
      );
    })();
    return;
  }
  if (message.type === 'START_QUEUE') {
    (async () => {
      try {
        await hydrateState();
        const pending = await chrome.storage.local.get('jdPendingImageExport');
        if (pending.jdPendingImageExport) {
          throw new Error('上一批图片包仍在生成，请等待图片 ZIP 下载完成后再开始新任务');
        }
        queue = parseTargets(message.text);
        if (!queue.length) throw new Error('请至少输入一个商品');
        collected = [];
        outcomes = [];
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
  if (message.type === 'PROGRESS') {
    (async () => {
      await hydrateState();
      if (!queue.length || queue[0].url !== message.url) return;
      touchActivity();
      setStatus(`${message.url}\n已采集 ${message.count}/${message.target} 条`);
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
        setStatus(
          `${message.url}\n已采集 ${message.count}/${message.target} 条；` +
          `本轮新增 ${added} 条已保存`
        );
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
      // Ignore a late duplicate completion message from the previous page.
      if (!queue.length || queue[0].url !== message.url) return;
      mergeCollected(message.rows);
      outcomes.push({
        url: message.url,
        productId: message.productId || '',
        requested: Number(message.requested || queue[0].count || 0),
        actual: message.rows.length
      });
      queue.shift();
      lastActivityAt = Date.now();
      await persistState();
      const requested = Number(message.requested || 0);
      setStatus(
        message.rows.length < requested
          ? `${message.url} 评论已到底：要求 ${requested} 条，实际 ${message.rows.length} 条；继续下一个商品。`
          : `${message.url} 完成：${message.rows.length}/${requested} 条`
      );
      await runNext();
    })();
    return;
  }
  if (message.type === 'FAILED') {
    (async () => {
      await failCurrentTarget(message.url, message.error);
    })();
  }
});

chrome.alarms.create(WATCHDOG_ALARM, {periodInMinutes: 1});

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name !== WATCHDOG_ALARM) return;
  (async () => {
    await hydrateState();
    if (!queue.length || !lastActivityAt) return;
    if (Date.now() - lastActivityAt < STALE_AFTER_MS) return;
    await failCurrentTarget(queue[0].url, '超过 90 秒没有收到采集进度，已由看门狗结束');
  })();
});

async function recoverUnfinishedQueue() {
  await hydrateState();
  if (!queue.length) return;
  if (!workerTabId) {
    await runNext();
    return;
  }
  try {
    const response = await chrome.tabs.sendMessage(workerTabId, {type: 'PING_SCRAPER'});
    if (response?.active && response.url === queue[0].url) {
      touchActivity();
      setStatus(`${queue[0].url}\n检测到采集仍在运行，已恢复后台监控。`);
      return;
    }
  } catch (_) {
    // Extension reloads invalidate the old content script; reload to inject the current one.
  }
  setStatus(`${queue[0].url}\n检测到未完成任务，正在从已保存检查点恢复。`);
  try {
    await chrome.tabs.reload(workerTabId);
  } catch (_) {
    workerTabId = null;
    await persistState();
    await runNext();
  }
}

recoverUnfinishedQueue();

async function recoverPendingImageExport() {
  const saved = await chrome.storage.local.get(['jdPendingImageExport', 'jdImageExportTabId']);
  if (!saved.jdPendingImageExport) return;
  if (Number.isInteger(saved.jdImageExportTabId)) {
    try {
      await chrome.tabs.get(saved.jdImageExportTabId);
      return;
    } catch (_) {
      // The previous export page is gone; create a fresh one below.
    }
  }
  setStatus('检测到未完成的评论图片包，正在继续生成。');
  const tab = await chrome.tabs.create({
    url: chrome.runtime.getURL('image_export.html'), active: false
  });
  await chrome.storage.local.set({jdImageExportTabId: tab.id});
}

recoverPendingImageExport();
