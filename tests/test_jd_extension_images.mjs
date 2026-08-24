import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function loadScript(path, additions = {}) {
  const context = vm.createContext({
    URL, Blob, TextEncoder, Uint8Array, ArrayBuffer, DataView, Date,
    location: {href: 'https://item.jd.com/100.html'},
    ...additions
  });
  vm.runInContext(fs.readFileSync(path, 'utf8'), context);
  return context;
}

const imageContext = loadScript('chrome_extension/review_images.js');
const thumbnail = 'https://img30.360buyimg.com/shaidan/s128x96_jfs/t1/test.jpg.avif';
assert.equal(
  imageContext.JDReviewImages.originalCandidate(thumbnail),
  'https://img30.360buyimg.com/shaidan/jfs/t1/test.jpg'
);

const reviewParent = {
  id: '', className: 'jdc-pc-rate-card-main-imgs', parentElement: null,
  getAttribute() { return ''; }
};
const avatarParent = {
  id: '', className: 'user-avatar', parentElement: null,
  getAttribute() { return ''; }
};
function fakeImage(src, parentElement) {
  return {
    id: '', className: '', parentElement, naturalWidth: 128, naturalHeight: 96,
    width: 128, height: 96, currentSrc: src,
    getAttribute(name) { return name === 'src' ? src : ''; }
  };
}
const extracted = imageContext.JDReviewImages.extract({
  querySelectorAll() {
    return [fakeImage(thumbnail, reviewParent), fakeImage('https://img30.360buyimg.com/avatar/a.jpg', avatarParent)];
  }
});
assert.equal(extracted.length, 1);
assert.equal(extracted[0].candidate_urls.length, 2);

const zipContext = loadScript('chrome_extension/zip_builder.js');
assert.equal(zipContext.JDZipBuilder.crc32(new TextEncoder().encode('123456789')), 0xcbf43926);
const zipBlob = zipContext.JDZipBuilder.build([
  {name: 'images.csv', data: '图片,路径\r\n1,images/a.jpg'},
  {name: 'images/a.jpg', data: new Uint8Array([1, 2, 3, 4])}
]);
const zipBytes = new Uint8Array(await zipBlob.arrayBuffer());
assert.equal(new DataView(zipBytes.buffer).getUint32(0, true), 0x04034b50);
assert.equal(new DataView(zipBytes.buffer).getUint32(zipBytes.length - 22, true), 0x06054b50);
assert.match(new TextDecoder().decode(zipBytes), /images\.csv/);
assert.match(new TextDecoder().decode(zipBytes), /images\/a\.jpg/);

let downloadedPackage;
let exportDone;
const statusNode = {textContent: ''};
const exportContext = vm.createContext({
  URL, Blob, TextEncoder, TextDecoder, Uint8Array, ArrayBuffer, DataView, Date, fetch,
  document: {querySelector() { return statusNode; }},
  window: {close() {}},
  setTimeout(callback, delay) {
    if (delay < 5000) queueMicrotask(callback);
    return 1;
  },
  chrome: {
    runtime: {
      async sendMessage(message) {
        if (message.type === 'IMAGE_EXPORT_READY') {
          return {
            stamp: '20260818_120000',
            rows: [{
              platform: 'jd', product_id: '100', product_url: 'https://item.jd.com/100.html',
              product_title: '测试商品', user_name_masked: 'u***1', rating: '5',
              review_time: '2026-08-18', sku: '白色', review_text_raw: '带图评论',
              review_images: [{
                source_url: 'data:image/png;base64,AQIDBA==',
                candidate_urls: ['data:image/png;base64,AQIDBA==']
              }]
            }]
          };
        }
        if (message.type === 'IMAGE_EXPORT_DONE') exportDone = message;
        if (message.type === 'IMAGE_EXPORT_FAILED') throw new Error(message.error);
        return {};
      }
    },
    downloads: {
      async download(options) {
        downloadedPackage = new Uint8Array(await fetch(options.url).then(response => response.arrayBuffer()));
        assert.equal(options.filename, 'jd_review_images_20260818_120000.zip');
        return 1;
      }
    }
  }
});
vm.runInContext(fs.readFileSync('chrome_extension/zip_builder.js', 'utf8'), exportContext);
vm.runInContext(fs.readFileSync('chrome_extension/image_export.js', 'utf8'), exportContext);
for (let attempt = 0; attempt < 20 && !exportDone; attempt++) {
  await new Promise(resolve => setTimeout(resolve, 10));
}
assert.ok(downloadedPackage?.length > 100);
assert.equal(exportDone?.successCount, 1);
const packageText = new TextDecoder().decode(downloadedPackage);
assert.match(packageText, /images\.csv/);
assert.match(packageText, /images\/100\/review_000001\/image_01\.png/);

console.log('JD extension image extraction and ZIP tests passed');
