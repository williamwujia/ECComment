(() => {
  if (window.__ecommerceReviewAssistantInstalled) return;
  window.__ecommerceReviewAssistantInstalled = true;

  const helpers = globalThis.ReviewAssistantAdapters;
  let activeScrapeUrl = null;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function isLoginPage() {
    if (/^login\.(?:taobao|tmall)\.com$/i.test(location.hostname)) return true;
    const loginNode = helpers.firstVisibleTextNode(
      document,
      ['亲，请登录', '密码登录', '短信登录', '扫码登录'],
      'button, a, div, span'
    );
    return Boolean(loginNode);
  }

  function metaContent(names) {
    for (const name of names) {
      const node = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
      const value = helpers.clean(node?.content);
      if (value) return value;
    }
    return '';
  }

  function productTitle(adapter) {
    const isCandidate = value => {
      const title = helpers.clean(value);
      return title.length >= 2
        && title !== '最小单价计算器'
        && !['商品评价', '累计评价', '宝贝评价', '买家评价', '问大家'].includes(title);
    };
    const value = helpers.textOf(document, adapter.titleSelectors);
    if (isCandidate(value)) return value;
    const meta = metaContent(['og:title', 'twitter:title', 'title']);
    if (isCandidate(meta)) return meta;
    const pageTitle = helpers.clean(document.title)
      .replace(/【行情\s*报价\s*价格\s*评测】\s*[-—]?\s*京东.*$/i, '')
      .replace(/\s*[-—|｜]\s*(?:淘宝网|天猫|京东(?:JD\.COM)?)\s*$/i, '')
      .trim();
    return isCandidate(pageTitle) ? pageTitle : '';
  }

  function normalizedReviewDate(text) {
    const match = helpers.clean(text).match(/(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?/);
    if (!match) return '';
    const month = match[2].padStart(2, '0');
    const day = match[3].padStart(2, '0');
    return `${match[1]}-${month}-${day}`;
  }

  function reviewRoot(adapter) {
    const scrollCandidates = (adapter.scrollSelectors || [])
      .flatMap(selector => [...document.querySelectorAll(selector)])
      .filter(item => item.getClientRects().length && item.scrollHeight > item.clientHeight + 20)
      .sort((left, right) => right.scrollHeight - left.scrollHeight);
    if (scrollCandidates.length) return scrollCandidates[0];

    for (const selector of adapter.reviewRootSelectors || []) {
      const candidates = [...document.querySelectorAll(selector)]
        .filter(item => item.getClientRects().length)
        .sort((left, right) => right.scrollHeight - left.scrollHeight);
      if (candidates.length) return candidates[0];
    }
    return document;
  }

  function cards(adapter) {
    const selector = adapter.cardSelectors.join(',');
    const found = [...reviewRoot(adapter).querySelectorAll(selector)];
    return found.filter((card, index) => {
      if (!card.getClientRects().length) return false;
      if (found.some((other, otherIndex) => otherIndex !== index && card.contains(other))) {
        return false;
      }
      return Boolean(helpers.textOf(card, adapter.reviewTextSelectors));
    });
  }

  function classText(card) {
    return [...card.querySelectorAll('[class]')]
      .map(node => typeof node.className === 'string' ? node.className : '')
      .join(' ');
  }

  function ratingOf(card) {
    const combined = `${classText(card)} ${helpers.clean(card.textContent)}`;
    const explicit = (combined.match(/(?:star|score)[-_]?(?:level)?[-_]?([1-5])/i) || [])[1]
      || (combined.match(/([1-5](?:\.\d)?)\s*(?:星|分)/) || [])[1];
    if (explicit) return explicit;
    if (/star-good/i.test(combined)) return '5';
    if (/star-(?:middle|medium)/i.test(combined)) return '3';
    if (/star-bad/i.test(combined)) return '1';
    return '';
  }

  function contentIdOf(card) {
    for (const name of ['data-id', 'data-rate-id', 'data-review-id', 'data-comment-id']) {
      const value = helpers.clean(card.getAttribute(name));
      if (value) return value;
    }
    return '';
  }

  function extract(card, target, adapter) {
    const platform = helpers.detectPlatform(target.url);
    const metaText = helpers.textOf(card, adapter.timeSelectors);
    let sku = helpers.textOf(card, adapter.skuSelectors);
    if (!sku && metaText.includes('已购：')) sku = helpers.clean(metaText.split('已购：', 2)[1]);
    return {
      platform,
      product_id: helpers.productId(target.url, platform),
      product_url: target.url,
      product_title: productTitle(adapter),
      shop_name: helpers.textOf(document, adapter.shopSelectors),
      platform_content_id: contentIdOf(card),
      user_name_masked: helpers.textOf(card, adapter.userSelectors),
      rating: ratingOf(card),
      review_time: metaText,
      review_date: normalizedReviewDate(metaText),
      sku,
      review_text_raw: helpers.textOf(card, adapter.reviewTextSelectors)
    };
  }

  async function clickLabels(labels) {
    const node = helpers.firstVisibleTextNode(document, labels);
    if (!node) return false;
    node.click();
    await sleep(1300);
    return true;
  }

  async function waitForScrollableReviewRoot(adapter) {
    for (let attempt = 0; attempt < 15; attempt++) {
      const found = (adapter.scrollSelectors || []).some(selector =>
        [...document.querySelectorAll(selector)].some(node =>
          node.getClientRects().length && node.scrollHeight > node.clientHeight + 20
        )
      );
      if (found) return true;
      await sleep(200);
    }
    return false;
  }

  function scrollContainer(adapter) {
    for (const selector of adapter.scrollSelectors || []) {
      const node = document.querySelector(selector);
      if (node && node.scrollHeight > node.clientHeight + 20) return node;
    }
    const card = cards(adapter)[0];
    let node = card?.parentElement;
    while (node && node !== document.body && node !== document.documentElement) {
      const style = getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 20) {
        return node;
      }
      node = node.parentElement;
    }
    return null;
  }

  async function advanceReviews(adapter, allowDocumentScroll = false) {
    const container = scrollContainer(adapter);
    if (container) {
      const before = container.scrollTop;
      const atEnd = before + container.clientHeight >= container.scrollHeight - 8;
      container.scrollBy(0, Math.max(container.clientHeight * 0.8, 500));
      return {found: true, atEnd, mode: 'scroll'};
    }
    for (const rootSelector of adapter.reviewRootSelectors || []) {
      const root = document.querySelector(rootSelector);
      if (!root) continue;
      const next = helpers.firstVisibleTextNode(root, ['下一页', '下页'], 'button, a, li, span');
      if (next && !next.disabled && next.getAttribute('aria-disabled') !== 'true') {
        next.click();
        await sleep(1300);
        return {found: true, atEnd: false, mode: 'page'};
      }
    }
    if (allowDocumentScroll) {
      const container = document.scrollingElement;
      if (container && container.scrollHeight > container.clientHeight + 20) {
        const before = container.scrollTop;
        const atEnd = before + container.clientHeight >= container.scrollHeight - 8;
        window.scrollBy(0, Math.max(container.clientHeight * 0.8, 500));
        return {found: true, atEnd, mode: 'document'};
      }
    }
    return {found: false, atEnd: false, mode: ''};
  }

  function rowKey(row) {
    return [
      row.platform,
      row.product_id,
      row.platform_content_id,
      row.user_name_masked,
      row.review_time,
      row.review_date,
      row.sku,
      row.review_text_raw
    ].join('|');
  }

  async function scrape(target) {
    const platform = helpers.detectPlatform(target.url);
    const adapter = helpers.adapterFor(platform);
    if (!adapter) throw new Error('当前页面不是受支持的商品页面');

    const openedReviews = await clickLabels(adapter.reviewLabels);
    if (!openedReviews) {
      if (!cards(adapter).length) {
        throw new Error('当前页面未加载评论模块；请正常打开带“查看全部评价”的商品页，再使用“采集当前商品页”');
      }
    }
    if (adapter.requiresScrollableReviewRoot && !await waitForScrollableReviewRoot(adapter)) {
      const inlineReviewsReady = target.allowDocumentScroll && cards(adapter).length;
      if (!inlineReviewsReady) {
        throw new Error('评价抽屉未打开，已停止以避免误采商品页预览评论');
      }
    }
    if (adapter.sortTriggerLabels?.length) {
      await clickLabels(adapter.sortTriggerLabels);
    }
    await clickLabels(adapter.newestLabels);

    const rows = Array.isArray(target.checkpointRows)
      ? target.checkpointRows.slice(0, target.count)
      : [];
    const seen = new Set(rows.map(rowKey));
    let stale = 0;
    let bottomWithoutNew = 0;
    while (rows.length < target.count && stale < 10 && bottomWithoutNew < 3) {
      const before = rows.length;
      const added = [];
      for (const card of cards(adapter)) {
        const row = extract(card, target, adapter);
        const key = rowKey(row);
        if (row.review_text_raw && !seen.has(key)) {
          seen.add(key);
          rows.push(row);
          added.push(row);
        }
        if (rows.length >= target.count) break;
      }
      if (added.length) {
        const checkpoint = await chrome.runtime.sendMessage({
          type: 'CHECKPOINT',
          url: target.url,
          rows: added,
          count: rows.length,
          target: target.count
        });
        if (!checkpoint?.saved) {
          throw new Error('新增评论未能写入本地检查点，采集已暂停以避免数据丢失');
        }
      }
      stale = rows.length === before ? stale + 1 : 0;
      chrome.runtime.sendMessage({
        type: 'PROGRESS',
        url: target.url,
        count: rows.length,
        target: target.count
      });
      if (rows.length >= target.count) break;
      const advance = await advanceReviews(adapter, Boolean(target.allowDocumentScroll));
      if (!advance.found) {
        throw new Error('没有找到评价区域的滚动层或下一页按钮，已停止以避免滚动商品主页面');
      }
      if (advance.mode === 'scroll' || advance.mode === 'document') await sleep(1300);
      bottomWithoutNew = advance.atEnd && rows.length === before
        ? bottomWithoutNew + 1
        : 0;
    }
    return rows.slice(0, target.count);
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === 'PING_SCRAPER') {
      sendResponse({
        active: Boolean(activeScrapeUrl),
        url: activeScrapeUrl,
        authRequired: isLoginPage()
      });
      return;
    }
    if (message.type !== 'SCRAPE') return;
    if (isLoginPage()) {
      sendResponse({started: false, authRequired: true});
      return;
    }
    if (activeScrapeUrl) {
      sendResponse({
        started: activeScrapeUrl === message.target.url,
        alreadyRunning: true
      });
      return;
    }
    activeScrapeUrl = message.target.url;
    sendResponse({started: true});
    scrape(message.target)
      .then(rows => chrome.runtime.sendMessage({
        type: 'DONE',
        url: message.target.url,
        productId: helpers.productId(message.target.url),
        requested: message.target.count,
        rows
      }))
      .catch(error => chrome.runtime.sendMessage({
        type: 'FAILED',
        url: message.target.url,
        error: error.message
      }))
      .finally(() => {
        activeScrapeUrl = null;
      });
  });
})();
