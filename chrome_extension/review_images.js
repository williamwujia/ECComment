(() => {
  const NOISE_RE = /avatar|head|user|nick|icon|logo|sprite|emoji|badge|shop|seller|product|goods|sku|二维码|头像|主图|商品图/i;
  const REVIEW_ASSET_RE = /image|img|pic|photo|media|shaidan|comment|晒单|晒图|评价图|评论图/i;
  const SOURCE_ATTRIBUTES = [
    'data-origin', 'data-original', 'data-large', 'data-large-img',
    'data-big', 'data-big-img', 'data-src', 'data-lazy-img', 'src'
  ];

  function absoluteUrl(value, baseUrl = location.href) {
    const cleaned = String(value || '').trim();
    if (!cleaned || cleaned.startsWith('data:') || cleaned.startsWith('blob:')) return cleaned;
    try {
      return new URL(cleaned, baseUrl).href;
    } catch (_) {
      return '';
    }
  }

  function originalCandidate(value, baseUrl = location.href) {
    const absolute = absoluteUrl(value, baseUrl);
    if (!absolute || absolute.startsWith('data:') || absolute.startsWith('blob:')) return absolute;
    try {
      const url = new URL(absolute);
      if (!/(^|\.)360buyimg\.com$/i.test(url.hostname)) return absolute;
      url.pathname = url.pathname
        .replace(/\/s\d+x\d+_jfs\//i, '/jfs/')
        .replace(/\.(?:avif|webp)$/i, '')
        .replace(/![^/]*$/i, '');
      url.search = '';
      url.hash = '';
      return url.href;
    } catch (_) {
      return absolute;
    }
  }

  function signature(node) {
    const values = [];
    let current = node;
    for (let depth = 0; current && depth < 4; depth++, current = current.parentElement) {
      values.push(current.id || '', current.className || '', current.getAttribute?.('alt') || '');
    }
    return values.join(' ');
  }

  function bestSource(img) {
    for (const attribute of SOURCE_ATTRIBUTES) {
      const value = img.getAttribute(attribute);
      if (value && !/^data:image\/svg/i.test(value)) return value;
    }
    const srcset = String(img.getAttribute('srcset') || '').trim();
    if (srcset) {
      const candidates = srcset.split(',').map(item => item.trim().split(/\s+/)[0]).filter(Boolean);
      if (candidates.length) return candidates[candidates.length - 1];
    }
    return img.currentSrc || '';
  }

  function extract(card, baseUrl = location.href) {
    const results = [];
    const seen = new Set();
    for (const img of card.querySelectorAll('img')) {
      const nodeSignature = signature(img);
      if (NOISE_RE.test(nodeSignature)) continue;
      const rawSource = bestSource(img);
      const sourceUrl = absoluteUrl(rawSource, baseUrl);
      if (!sourceUrl || seen.has(sourceUrl)) continue;
      const width = Number(img.naturalWidth || img.width || img.getAttribute('width') || 0);
      const height = Number(img.naturalHeight || img.height || img.getAttribute('height') || 0);
      const hasReviewSignal = REVIEW_ASSET_RE.test(`${nodeSignature} ${sourceUrl}`);
      if (!hasReviewSignal && width < 72 && height < 72) continue;
      const originalUrl = originalCandidate(sourceUrl, baseUrl);
      const candidateUrls = [...new Set([originalUrl, sourceUrl].filter(Boolean))];
      seen.add(sourceUrl);
      results.push({source_url: sourceUrl, candidate_urls: candidateUrls});
    }
    return results;
  }

  globalThis.JDReviewImages = {absoluteUrl, originalCandidate, extract};
})();
