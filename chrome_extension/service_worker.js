let queue = [];
let collected = [];
let workerTabId = null;
let hydrated = false;

async function hydrateState() {
  if (hydrated) return;
  const saved = await chrome.storage.local.get(['jdQueue', 'jdCollected', 'jdWorkerTabId']);
  queue = Array.isArray(saved.jdQueue) ? saved.jdQueue : [];
  collected = Array.isArray(saved.jdCollected) ? saved.jdCollected : [];
  workerTabId = Number.isInteger(saved.jdWorkerTabId) ? saved.jdWorkerTabId : null;
  hydrated = true;
}

async function persistState() {
  await chrome.storage.local.set({
    jdQueue: queue,
    jdCollected: collected,
    jdWorkerTabId: workerTabId
  });
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

async function downloadResults() {
  const columns = ['platform', 'product_id', 'product_url', 'product_title', 'user_name_masked', 'rating', 'review_time', 'sku', 'review_text_raw'];
  const lines = [columns.join(','), ...collected.map(row => columns.map(key => csvCell(row[key])).join(','))];
  const stamp = new Date().toISOString().replaceAll(/[-:TZ.]/g, '').slice(0, 14);
  if (!workerTabId) throw new Error('采集标签页已关闭，无法导出');
  await chrome.tabs.sendMessage(workerTabId, {
    type: 'EXPORT_CSV',
    csv: '\ufeff' + lines.join('\r\n'),
    filename: `jd_reviews_${stamp}.csv`
  });
}

async function runNext() {
  await hydrateState();
  if (!queue.length) {
    await downloadResults();
    setStatus(`完成，共采集 ${collected.length} 条；请选择 CSV 保存位置。`);
    await chrome.storage.local.remove(['jdQueue', 'jdCollected', 'jdWorkerTabId']);
    return;
  }
  const target = queue[0];
  setStatus(`正在打开 ${target.url}\n剩余商品：${queue.length}，已采集：${collected.length}`);
  if (workerTabId) {
    try {
      await chrome.tabs.update(workerTabId, {url: target.url, active: true});
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

async function startScrapeWithRetry(tabId, target) {
  for (let attempt = 1; attempt <= 5; attempt++) {
    await new Promise(resolve => setTimeout(resolve, attempt === 1 ? 1800 : 1000));
    try {
      const response = await chrome.tabs.sendMessage(tabId, {type: 'SCRAPE', target});
      if (response?.started) return;
    } catch (_) {
      // The content script may not have reached document_idle yet.
    }
    setStatus(`正在等待第 ${attempt}/5 次加载页面脚本\n${target.url}`);
  }
  setStatus(`第二阶段启动失败：页面脚本未就绪\n${target.url}\n请刷新此商品页，扩展会再次尝试。`);
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
  if (message.type === 'START_QUEUE') {
    (async () => {
      try {
        await hydrateState();
        queue = parseTargets(message.text);
        if (!queue.length) throw new Error('请至少输入一个商品');
        collected = [];
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
    setStatus(`${message.url}\n已采集 ${message.count}/${message.target} 条`);
    return;
  }
  if (message.type === 'DONE') {
    (async () => {
      await hydrateState();
      // Ignore a late duplicate completion message from the previous page.
      if (!queue.length || queue[0].url !== message.url) return;
      collected.push(...message.rows);
      queue.shift();
      await persistState();
      setStatus(`${message.url} 完成：${message.rows.length} 条`);
      await runNext();
    })();
    return;
  }
  if (message.type === 'FAILED') {
    (async () => {
      await hydrateState();
      if (!queue.length || queue[0].url !== message.url) return;
      setStatus(`${message.url} 失败：${message.error}\n将继续下一个商品。`);
      queue.shift();
      await persistState();
      await runNext();
    })();
  }
});

hydrateState();
