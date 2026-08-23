import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const adapterSource = fs.readFileSync(
  new URL('../ecommerce_review_assistant/platform_adapters.js', import.meta.url),
  'utf8'
);
const adapterContext = vm.createContext({URL});
vm.runInContext(adapterSource, adapterContext);

const adapterCases = JSON.parse(vm.runInContext(`JSON.stringify([
  ReviewAssistantAdapters.detectPlatform('https://item.jd.com/13745188.html'),
  ReviewAssistantAdapters.detectPlatform('https://item.taobao.com/item.htm?id=123456'),
  ReviewAssistantAdapters.detectPlatform('https://detail.tmall.com/item.htm?id=987654'),
  ReviewAssistantAdapters.detectPlatform('https://chaoshi.detail.tmall.com/item.htm?id=555555'),
  ReviewAssistantAdapters.productId('https://item.jd.com/13745188.html'),
  ReviewAssistantAdapters.productId('https://detail.tmall.hk/item.htm?id=7654321'),
  ReviewAssistantAdapters.isSupportedProductUrl('https://example.com/item?id=1')
])` , adapterContext));
assert.deepEqual(adapterCases, ['jd', 'taobao', 'tmall', 'tmall', '13745188', '7654321', false]);

const liveTmallContract = JSON.parse(vm.runInContext(`JSON.stringify((() => {
  const adapter = ReviewAssistantAdapters.adapterFor('tmall');
  return {
    reviewLabels: adapter.reviewLabels,
    sortTriggerLabels: adapter.sortTriggerLabels,
    newestLabels: adapter.newestLabels,
    cardSelectors: adapter.cardSelectors,
    scrollSelectors: adapter.scrollSelectors,
    userSelectors: adapter.userSelectors,
    timeSelectors: adapter.timeSelectors,
    requiresScrollableReviewRoot: adapter.requiresScrollableReviewRoot
  };
})())`, adapterContext));
assert.deepEqual(liveTmallContract.reviewLabels.slice(0, 2), ['查看全部评价', '用户评价']);
assert.deepEqual(liveTmallContract.sortTriggerLabels, ['默认排序']);
assert.deepEqual(liveTmallContract.newestLabels, ['时间排序']);
assert.ok(liveTmallContract.cardSelectors.includes("[class*='Comment--']"));
assert.ok(liveTmallContract.scrollSelectors.includes("[class*='comments--']"));
assert.ok(liveTmallContract.userSelectors.includes("[class*='userName--']"));
assert.ok(liveTmallContract.timeSelectors.includes("[class*='meta--']"));
assert.equal(liveTmallContract.requiresScrollableReviewRoot, true);
assert.ok(vm.runInContext("ReviewAssistantAdapters.adapterFor('tmall').titleSelectors.includes(\"[class*='mainTitle--']\")", adapterContext));
assert.ok(vm.runInContext("ReviewAssistantAdapters.adapterFor('tmall').shopSelectors.includes(\"[class*='shopName--']\")", adapterContext));

const workerSource = fs.readFileSync(
  new URL('../ecommerce_review_assistant/service_worker.js', import.meta.url),
  'utf8'
);

function createWorker(initialStorage = {}, sendMessageImpl = async () => ({started: true})) {
  const storage = structuredClone(initialStorage);
  const calls = [];
  const listeners = {};
  const tabState = {url: initialStorage.ecomQueue?.[0]?.url || ''};
  const chrome = {
    storage: {
      local: {
        async get(keys) {
          return Object.fromEntries(keys.map(key => [key, storage[key]]));
        },
        async set(values) {
          Object.assign(storage, values);
        },
        async remove(keys) {
          for (const key of keys) delete storage[key];
        }
      }
    },
    action: {
      setBadgeText() {},
      setBadgeBackgroundColor() {}
    },
    downloads: {
      async download(values) {
        calls.push(['download', values]);
      }
    },
    tabs: {
      async get() {
        return {id: 7, url: tabState.url};
      },
      async reload() {
        calls.push(['reload', tabState.url]);
      },
      async update(_tabId, values) {
        tabState.url = values.url;
        calls.push(['update', values.url]);
        return {id: 7, url: values.url};
      },
      async create(values) {
        tabState.url = values.url;
        calls.push(['create', values.url]);
        return {id: 7, url: values.url};
      },
      sendMessage: sendMessageImpl,
      onUpdated: {
        addListener(listener) {
          listeners.updated = listener;
        }
      }
    },
    runtime: {
      onMessage: {
        addListener(listener) {
          listeners.message = listener;
        }
      }
    },
    alarms: {
      create() {},
      onAlarm: {
        addListener(listener) {
          listeners.alarm = listener;
        }
      }
    }
  };
  const context = vm.createContext({
    chrome,
    console,
    URL,
    Date,
    TextEncoder,
    btoa,
    setTimeout(callback) {
      callback();
    }
  });
  vm.runInContext(workerSource, context);
  return {context, storage, calls, listeners};
}

const parserWorker = createWorker();
await new Promise(resolve => setImmediate(resolve));
const parsedTargets = JSON.parse(vm.runInContext(`JSON.stringify(parseTargets(
  'https://item.jd.com/100.html,20\\n' +
  'https://item.taobao.com/item.htm?id=200,30\\n' +
  'https://detail.tmall.com/item.htm?id=300,40'
))`, parserWorker.context));
assert.deepEqual(
  parsedTargets.map(item => [item.platform, item.productId, item.count]),
  [['jd', '100', 20], ['taobao', '200', 30], ['tmall', '300', 40]]
);
assert.throws(
  () => vm.runInContext("parseTargets('https://example.com/item?id=1,20')", parserWorker.context),
  /不是受支持/
);

vm.runInContext(`collected = [{
  platform: 'tmall',
  product_id: '300',
  product_url: 'https://detail.tmall.com/item.htm?id=300',
  product_title: '中文商品标题',
  review_text_raw: '中文评价内容'
}]`, parserWorker.context);
await vm.runInContext('downloadResults()', parserWorker.context);
const downloadUrl = parserWorker.calls.find(call => call[0] === 'download')[1].url;
assert.match(downloadUrl, /^data:text\/csv;charset=utf-8;base64,/);
const decodedCsv = Buffer.from(downloadUrl.split(',', 2)[1], 'base64').toString('utf8');
assert.match(decodedCsv, /中文商品标题/);
assert.match(decodedCsv, /中文评价内容/);

const currentPageWorker = createWorker();
await new Promise(resolve => setImmediate(resolve));
const currentPageResponse = await new Promise(resolve => {
  currentPageWorker.listeners.message({
    type: 'START_CURRENT_PAGE',
    tabId: 42,
    url: 'https://detail.tmall.com/item.htm?id=638663201210&from=search',
    count: 20
  }, {}, resolve);
});
assert.match(currentPageResponse.message, /当前商品页/);
assert.equal(currentPageWorker.storage.ecomWorkerTabId, 42);
assert.equal(currentPageWorker.storage.ecomQueue[0].productId, '638663201210');
assert.equal(currentPageWorker.storage.ecomQueue[0].count, 20);
assert.equal(currentPageWorker.storage.ecomQueue[0].allowDocumentScroll, true);

const loginUrl = 'https://detail.tmall.com/item.htm?id=300';
const loginWorker = createWorker({
  ecomQueue: [{url: loginUrl, count: 20, platform: 'tmall', productId: '300'}],
  ecomCollected: [],
  ecomWorkerTabId: 7,
  ecomOutcomes: [],
  ecomLastActivityAt: Date.now(),
  ecomAuthPaused: false
}, async () => ({authRequired: true}));
await new Promise(resolve => setImmediate(resolve));
await vm.runInContext('startScrapeWithRetry(7, queue[0])', loginWorker.context);
assert.equal(loginWorker.storage.ecomQueue.length, 1);
assert.equal(loginWorker.storage.ecomAuthPaused, true);
assert.equal(loginWorker.storage.ecomLastActivityAt, 0);

const firstUrl = 'https://item.jd.com/100.html';
const secondUrl = 'https://item.taobao.com/item.htm?id=200';
const recoveryWorker = createWorker({
  ecomQueue: [
    {url: firstUrl, count: 20, platform: 'jd', productId: '100'},
    {url: secondUrl, count: 20, platform: 'taobao', productId: '200'}
  ],
  ecomCollected: [{
    platform: 'jd',
    product_id: '100',
    product_url: firstUrl,
    review_text_raw: '已经保存的评论'
  }],
  ecomWorkerTabId: 7,
  ecomOutcomes: [],
  ecomLastActivityAt: Date.now(),
  ecomAuthPaused: false
}, async () => {
  throw new Error('content script unavailable');
});
await new Promise(resolve => setImmediate(resolve));
await vm.runInContext('startScrapeWithRetry(7, queue[0])', recoveryWorker.context);
assert.equal(recoveryWorker.storage.ecomQueue.length, 1);
assert.equal(recoveryWorker.storage.ecomQueue[0].url, secondUrl);
assert.equal(recoveryWorker.storage.ecomCollected.length, 1);
assert.equal(recoveryWorker.storage.ecomOutcomes.length, 1);
assert.equal(recoveryWorker.storage.ecomOutcomes[0].actual, 1);
assert.deepEqual(recoveryWorker.calls.at(-1), ['update', secondUrl]);

console.log('Ecommerce review assistant tests passed');
