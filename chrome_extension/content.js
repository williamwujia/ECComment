(() => {
  if (window.__jdReviewCollectorInstalled) return;
  window.__jdReviewCollectorInstalled = true;

  const clean = value => (value || '').replace(/\s+/g, ' ').trim();
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const textOf = (root, selectors) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const value = clean(node?.innerText || node?.textContent);
      if (value) return value;
    }
    return '';
  };

  function productId() {
    return (location.pathname.match(/\/(\d+)\.html$/) || [])[1] || '';
  }

  function productTitle() {
    const selectors = [
      '.itemInfo-wrap .sku-name',
      '.sku-name',
      '[class*="skuName"]',
      '[class*="productName"]'
    ];
    for (const selector of selectors) {
      const value = clean(document.querySelector(selector)?.textContent);
      if (value && value !== '最小单价计算器') return value;
    }
    const metaTitle = clean(
      document.querySelector('meta[property="og:title"], meta[name="title"]')?.content
    );
    if (metaTitle && metaTitle !== '最小单价计算器') return metaTitle;
    return clean(document.title)
      .replace(/【行情\s*报价\s*价格\s*评测】\s*[-—]?\s*京东.*$/i, '')
      .replace(/\s*[-—]\s*京东(?:JD\.COM)?\s*$/i, '')
      .trim();
  }

  function cards() {
    const overlay = document.querySelector('#rateList, .jdc-page-overlay[class*="_rateListBox_"]');
    if (overlay) {
      return [...overlay.querySelectorAll('[class*="_listItem_"], .jdc-pc-rate-card')]
        .filter(card => card.querySelector('.jdc-pc-rate-card-main-desc'));
    }
    return [...document.querySelectorAll([
      '.comment-item', '[class*="CommentItem"]', '[class*="review-item"]',
      '.comment-root .list > .item', '.comment-list > .item'
    ].join(','))].filter(card => card.querySelector('.info, .comment-con, [class*="content"]'));
  }

  function extract(card, url) {
    const classText = [...card.querySelectorAll('[class]')].map(node => node.className).join(' ');
    const explicitRating = (classText.match(/(?:star|score)[-_]?(?:level)?[-_]?([1-5])/i) || [])[1] ||
      ([...card.querySelectorAll('[aria-label], [title]')].map(node => node.getAttribute('aria-label') || node.title)
        .join(' ').match(/([1-5])\s*(?:星|分)/) || [])[1] || '';
    const rating = explicitRating || (/star-good/i.test(classText) ? '5' : /star-(?:middle|medium)/i.test(classText) ? '3' : /star-bad/i.test(classText) ? '1' : '');
    const text = textOf(card, ['.jdc-pc-rate-card-main-desc', '.comment-con', '[class*="comment-content"]', '[class*="commentContent"]', '[class*="review-content"]']);
    const user = textOf(card, ['.jdc-pc-rate-card-nick', '.nickname', '.user-info', '[class*="userInfo"]', '[class*="user-name"]']);
    const time = textOf(card, ['.date.list', '.comment-time', '[class*="commentTime"]', 'time']);
    const sku = textOf(card, ['.jdc-pc-rate-card-info.top .info', '.order-info', '[class*="product-info"]', '[class*="sku"]']);
    return {
      platform: 'jd', product_id: productId(), product_url: url,
      product_title: productTitle(),
      user_name_masked: user, rating, review_time: time, sku, review_text_raw: text
    };
  }

  async function clickText(labels) {
    const nodes = [...document.querySelectorAll('button, a, div, span, li')];
    for (const label of labels) {
      const node = nodes.find(item => clean(item.textContent) === label && item.getClientRects().length);
      if (node) { node.click(); await sleep(1200); return true; }
    }
    return false;
  }

  function scrollReviews() {
    const knownContainer = document.querySelector('#rateList [class*="_rateListContainer_"], .jdc-page-overlay [class*="_rateListContainer_"]');
    if (knownContainer) {
      const before = knownContainer.scrollTop;
      const atEnd = before + knownContainer.clientHeight >= knownContainer.scrollHeight - 8;
      knownContainer.scrollBy(0, Math.max(knownContainer.clientHeight * .8, 500));
      return {found: true, atEnd};
    }
    const card = cards()[0];
    let node = card?.parentElement;
    while (node && node !== document.body) {
      const style = getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 20) {
        node.scrollBy(0, Math.max(node.clientHeight * .8, 500));
        return {
          found: true,
          atEnd: node.scrollTop + node.clientHeight >= node.scrollHeight - 8
        };
      }
      node = node.parentElement;
    }
    return {found: false, atEnd: false};
  }

  async function scrape(target) {
    const allButton = document.querySelector('.comment-root .all-btn, .everyone-reviews .all-btn');
    if (allButton) { allButton.click(); await sleep(1400); }
    else if (!await clickText(['全部评价', '买家评价'])) throw new Error('没有找到“全部评价”');
    if (!await clickText(['最新', '最新评价', '时间排序'])) throw new Error('没有找到“最新”排序');

    const rows = [];
    const seen = new Set();
    let stale = 0;
    let bottomWithoutNew = 0;
    while (rows.length < target.count && stale < 10 && bottomWithoutNew < 3) {
      const before = rows.length;
      for (const card of cards()) {
        const row = extract(card, target.url);
        const key = [row.user_name_masked, row.review_time, row.sku, row.review_text_raw].join('|');
        if (row.review_text_raw && !seen.has(key)) { seen.add(key); rows.push(row); }
        if (rows.length >= target.count) break;
      }
      stale = rows.length === before ? stale + 1 : 0;
      chrome.runtime.sendMessage({type: 'PROGRESS', url: target.url, count: rows.length, target: target.count});
      const scroll = scrollReviews();
      if (!scroll.found) throw new Error('没有找到评价弹层的滚动区域，已停止以避免滚动主页面');
      await sleep(1300);
      bottomWithoutNew = scroll.atEnd && rows.length === before ? bottomWithoutNew + 1 : 0;
    }
    return rows.slice(0, target.count);
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === 'EXPORT_CSV') {
      const blob = new Blob([message.csv], {type: 'text/csv;charset=utf-8'});
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = message.filename;
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      sendResponse({downloaded: true});
      return;
    }
    if (message.type !== 'SCRAPE') return;
    sendResponse({started: true});
    scrape(message.target)
      .then(rows => chrome.runtime.sendMessage({
        type: 'DONE',
        url: message.target.url,
        productId: productId(),
        requested: message.target.count,
        rows
      }))
      .catch(error => chrome.runtime.sendMessage({type: 'FAILED', url: message.target.url, error: error.message}));
  });
})();
