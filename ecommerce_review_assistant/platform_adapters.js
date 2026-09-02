(() => {
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();

  function detectPlatform(urlValue) {
    const url = new URL(urlValue);
    const host = url.hostname.toLowerCase();
    if (host === 'item.jd.com') return 'jd';
    if (host === 'item.taobao.com') return 'taobao';
    if (['detail.tmall.com', 'chaoshi.detail.tmall.com', 'detail.tmall.hk'].includes(host)) {
      return 'tmall';
    }
    return '';
  }

  function productId(urlValue, platform = detectPlatform(urlValue)) {
    const url = new URL(urlValue);
    if (platform === 'jd') {
      return (url.pathname.match(/\/(\d+)\.html$/) || [])[1] || '';
    }
    return url.searchParams.get('id') || url.searchParams.get('itemId') || '';
  }

  function isSupportedProductUrl(urlValue) {
    try {
      const platform = detectPlatform(urlValue);
      return Boolean(platform && productId(urlValue, platform));
    } catch (_) {
      return false;
    }
  }

  function visible(node) {
    return Boolean(node && node.getClientRects && node.getClientRects().length);
  }

  function textOf(root, selectors) {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const value = clean(node?.innerText || node?.textContent);
      if (value) return value;
    }
    return '';
  }

  function firstVisibleTextNode(document, labels, selector = 'button, a, div, span, li') {
    const nodes = [...document.querySelectorAll(selector)];
    for (const label of labels) {
      const node = nodes.find(item => clean(item.textContent) === label && visible(item));
      if (node) return node;
    }
    return null;
  }

  const shared = {
    cardSelectors: [
      "[class*='Comment--']",
      "[class*='review-item']",
      "[class*='ReviewItem']",
      "[class*='comment-item']",
      "[class*='CommentItem']",
      "[class*='rate-item']",
      "[class*='evaluation-item']"
    ],
    reviewTextSelectors: [
      "[class*='content--']",
      "[class*='review-content']",
      "[class*='comment-content']",
      "[class*='CommentContent']",
      "[class*='rate-content']"
    ],
    userSelectors: [
      "[class*='userInfo--'] span",
      "[class*='user-name']",
      "[class*='userName']",
      "[class*='nickname']",
      "[class*='buyer-name']"
    ],
    timeSelectors: [
      "[class*='meta--']",
      "[class*='comment-time']",
      "[class*='review-time']",
      "[class*='date']",
      'time'
    ],
    skuSelectors: [
      "[class*='sku']",
      "[class*='variant']",
      "[class*='spec']",
      "[class*='property']"
    ],
    titleSelectors: [
      "[class*='mainTitle--']",
      '#tbpcDetail_SkuPanelBody [class*="title"]',
      "[class*='product-title']",
      "[class*='ProductTitle']",
      "[class*='item-title']",
      "[class*='ItemTitle']",
      '.tb-main-title'
    ],
    shopSelectors: [
      "[class*='shopName--']",
      "[class*='shop-name']",
      "[class*='shopName']",
      "[class*='ShopName']",
      "[class*='seller-name']"
    ],
    reviewLabels: ['宝贝评价', '商品评价', '累计评价', '买家评价', '全部评价'],
    newestLabels: ['最新', '最新评价', '按时间', '时间排序'],
    reviewRootSelectors: [
      "[class*='review-list']",
      "[class*='comment-list']",
      "[class*='rate-list']",
      "[class*='evaluation-list']",
      "[class*='ReviewList']"
    ]
  };

  const modernTaobaoTmall = {
    ...shared,
    cardSelectors: ["[class*='Comment--']", ...shared.cardSelectors],
    reviewTextSelectors: ["[class*='content--']", ...shared.reviewTextSelectors],
    userSelectors: ["[class*='userName--']", ...shared.userSelectors],
    timeSelectors: ["[class*='meta--']", ...shared.timeSelectors],
    reviewLabels: ['查看全部评价', '用户评价'],
    sortTriggerLabels: ['默认排序'],
    newestLabels: ['时间排序'],
    reviewRootSelectors: ["[class*='Comments--']"],
    scrollSelectors: ["[class*='comments--']"],
    requiresScrollableReviewRoot: true
  };

  const adapters = {
    jd: {
      ...shared,
      cardSelectors: [
        '#rateList [class*="_listItem_"]',
        '#rateList .jdc-pc-rate-card',
        '.comment-item',
        ...shared.cardSelectors
      ],
      reviewTextSelectors: ['.jdc-pc-rate-card-main-desc', '.comment-con', ...shared.reviewTextSelectors],
      userSelectors: ['.jdc-pc-rate-card-nick', '.nickname', '.user-info', ...shared.userSelectors],
      timeSelectors: ['.date.list', '.comment-time', ...shared.timeSelectors],
      skuSelectors: ['.jdc-pc-rate-card-info.top .info', '.order-info', ...shared.skuSelectors],
      titleSelectors: ['.itemInfo-wrap .sku-name', '.sku-name', ...shared.titleSelectors],
      reviewLabels: ['全部评价', '买家评价'],
      newestLabels: ['最新', '最新评价', '时间排序'],
      reviewRootSelectors: ['#rateList', '.jdc-page-overlay[class*="_rateListBox_"]'],
      scrollSelectors: [
        '#rateList [class*="_rateListContainer_"]',
        '.jdc-page-overlay [class*="_rateListContainer_"]'
      ]
    },
    taobao: {...modernTaobaoTmall},
    tmall: {...modernTaobaoTmall}
  };

  function adapterFor(platform) {
    return adapters[platform] || null;
  }

  globalThis.ReviewAssistantAdapters = {
    clean,
    detectPlatform,
    productId,
    isSupportedProductUrl,
    textOf,
    firstVisibleTextNode,
    adapterFor
  };
})();
