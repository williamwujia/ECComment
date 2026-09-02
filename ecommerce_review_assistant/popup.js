const input = document.querySelector('#targets');
const status = document.querySelector('#status');

chrome.storage.local.get(['ecomTargetsText', 'ecomScrapeStatus'], data => {
  input.value = data.ecomTargetsText || '';
  status.textContent = data.ecomScrapeStatus || '等待开始';
});

chrome.storage.onChanged.addListener(changes => {
  if (changes.ecomScrapeStatus) {
    status.textContent = changes.ecomScrapeStatus.newValue;
  }
});

async function send(type, extra = {}) {
  return new Promise(resolve => {
    chrome.runtime.sendMessage({type, ...extra}, response => {
      if (chrome.runtime.lastError) {
        status.textContent = chrome.runtime.lastError.message;
        resolve(null);
        return;
      }
      status.textContent = response?.message || '操作已提交';
      resolve(response);
    });
  });
}

document.querySelector('#start').addEventListener('click', async () => {
  const text = input.value.trim();
  await chrome.storage.local.set({ecomTargetsText: text});
  await send('START_QUEUE', {text});
});

document.querySelector('#current').addEventListener('click', async () => {
  const firstLine = input.value.split(/\r?\n/).map(value => value.trim()).find(Boolean) || '';
  const count = Number(firstLine.split(/[,\t]/)[1] || 20);
  if (!Number.isInteger(count) || count <= 0 || count > 2000) {
    status.textContent = '数量无效，必须是 1–2000。';
    return;
  }
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.id || !tab.url) {
    status.textContent = '没有找到当前浏览器标签页。';
    return;
  }
  await send('START_CURRENT_PAGE', {tabId: tab.id, url: tab.url, count});
});

document.querySelector('#resume').addEventListener('click', () => send('RESUME_QUEUE'));
document.querySelector('#cancel').addEventListener('click', () => send('CANCEL_QUEUE'));
