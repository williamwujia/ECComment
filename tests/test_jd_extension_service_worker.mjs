import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const firstUrl = 'https://item.jd.com/100.html';
const secondUrl = 'https://item.jd.com/200.html';
const storage = {
  jdQueue: [{url: firstUrl, count: 20}, {url: secondUrl, count: 20}],
  jdCollected: [{
    product_id: '100',
    product_url: firstUrl,
    review_text_raw: '已经保存的评论'
  }],
  jdWorkerTabId: 7,
  jdOutcomes: [],
  jdLastActivityAt: Date.now()
};
const calls = [];
const listeners = {};
const tabState = {url: firstUrl};

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
    async download() {
      calls.push(['download']);
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
      return {id: 7, url: values.url};
    },
    async sendMessage(_tabId, message) {
      if (message.type === 'PING_SCRAPER') {
        return {active: true, url: firstUrl};
      }
      throw new Error('content script unavailable');
    },
    onUpdated: {
      addListener(listener) {
        listeners.updated = listener;
      }
    }
  },
  runtime: {
    getURL(path) {
      return `chrome-extension://test/${path}`;
    },
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
  encodeURIComponent,
  setTimeout(callback) {
    callback();
  }
});
const source = fs.readFileSync(
  new URL('../chrome_extension/service_worker.js', import.meta.url),
  'utf8'
);
vm.runInContext(source, context);
await new Promise(resolve => setImmediate(resolve));

const mergedImageCount = vm.runInContext(`
  mergeCollected([{
    product_id: '100', product_url: '${firstUrl}', review_text_raw: '已经保存的评论',
    image_count: 1, review_images: [{source_url: 'https://img30.360buyimg.com/a.jpg'}]
  }]);
  collected[0].image_count;
`, context);
assert.equal(mergedImageCount, 1);

await vm.runInContext('startScrapeWithRetry(7, queue[0])', context);

assert.equal(storage.jdQueue.length, 1);
assert.equal(storage.jdQueue[0].url, secondUrl);
assert.equal(storage.jdCollected.length, 1);
assert.equal(storage.jdOutcomes.length, 1);
assert.equal(storage.jdOutcomes[0].failed, true);
assert.equal(storage.jdOutcomes[0].actual, 1);
assert.deepEqual(calls.at(-1), ['update', secondUrl]);

await vm.runInContext('runNext()', context);
assert.deepEqual(calls.at(-1), ['reload', secondUrl]);

await vm.runInContext(`
  queue = [];
  collected = [{
    platform: 'jd', product_id: '200', product_url: '${secondUrl}',
    review_text_raw: '带图片的评论', image_count: 1,
    review_images: [{source_url: 'data:image/png;base64,AQID'}]
  }];
  runNext();
`, context);
assert.equal(storage.jdCollected.length, 1);
assert.ok(storage.jdPendingImageExport);
assert.equal(calls.filter(call => call[0] === 'download').length, 1);

console.log('JD extension recovery tests passed');
