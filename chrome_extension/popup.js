const input = document.querySelector('#targets');
const status = document.querySelector('#status');

chrome.storage.local.get(['jdTargetsText', 'jdScrapeStatus'], data => {
  input.value = data.jdTargetsText || '';
  status.textContent = data.jdScrapeStatus || '等待开始';
});

chrome.storage.onChanged.addListener(changes => {
  if (changes.jdScrapeStatus) status.textContent = changes.jdScrapeStatus.newValue;
});

document.querySelector('#start').addEventListener('click', async () => {
  const text = input.value.trim();
  await chrome.storage.local.set({jdTargetsText: text});
  chrome.runtime.sendMessage({type: 'START_QUEUE', text}, response => {
    if (chrome.runtime.lastError) status.textContent = chrome.runtime.lastError.message;
    else status.textContent = response?.message || '任务已提交';
  });
});
