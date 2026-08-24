(() => {
  const statusNode = document.querySelector('#status');
  const MANIFEST_COLUMNS = [
    'review_index', 'platform', 'product_id', 'product_url', 'product_title',
    'user_name_masked', 'rating', 'review_time', 'sku', 'review_text_raw',
    'image_index', 'source_url', 'resolved_url', 'relative_path',
    'download_status', 'error'
  ];

  const csvCell = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
  const safePart = value => String(value || 'unknown').replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 80) || 'unknown';

  function extensionFor(contentType, url) {
    const mime = String(contentType || '').split(';')[0].toLowerCase();
    const byMime = {
      'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif',
      'image/webp': 'webp', 'image/avif': 'avif', 'image/bmp': 'bmp'
    };
    if (byMime[mime]) return byMime[mime];
    const match = String(url || '').match(/\.([a-z0-9]{2,5})(?:[!?]|$)/i);
    return match && /^(?:jpe?g|png|gif|webp|avif|bmp)$/i.test(match[1])
      ? match[1].toLowerCase().replace('jpeg', 'jpg')
      : 'jpg';
  }

  function imageEntries(rows) {
    const entries = [];
    rows.forEach((row, rowIndex) => {
      const images = Array.isArray(row.review_images) ? row.review_images : [];
      images.forEach((image, imageIndex) => entries.push({
        order: entries.length,
        row,
        reviewIndex: rowIndex + 1,
        imageIndex: imageIndex + 1,
        sourceUrl: String(image?.source_url || image || ''),
        candidateUrls: Array.isArray(image?.candidate_urls)
          ? image.candidate_urls.filter(Boolean)
          : [String(image?.source_url || image || '')].filter(Boolean)
      }));
    });
    return entries;
  }

  async function fetchImage(entry) {
    let lastError = '没有可用图片 URL';
    for (const url of [...new Set(entry.candidateUrls)]) {
      if (url.startsWith('blob:')) {
        lastError = '页面临时 blob URL 已失效';
        continue;
      }
      try {
        const response = await fetch(url, {credentials: 'include', cache: 'force-cache'});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const contentType = response.headers.get('content-type') || '';
        if (contentType && !contentType.toLowerCase().startsWith('image/')) {
          throw new Error(`返回类型不是图片：${contentType}`);
        }
        const data = new Uint8Array(await response.arrayBuffer());
        if (!data.byteLength) throw new Error('图片内容为空');
        return {data, contentType, resolvedUrl: url};
      } catch (error) {
        lastError = error.message;
      }
    }
    throw new Error(lastError);
  }

  async function buildPackage(payload) {
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    const entries = imageEntries(rows);
    const results = new Array(entries.length);
    const zipEntries = [];
    let cursor = 0;
    let finished = 0;

    async function worker() {
      while (cursor < entries.length) {
        const index = cursor++;
        const entry = entries[index];
        const row = entry.row;
        const productId = safePart(row.product_id);
        let relativePath = '';
        let resolvedUrl = '';
        let downloadStatus = 'failed';
        let error = '';
        try {
          const fetched = await fetchImage(entry);
          const extension = extensionFor(fetched.contentType, fetched.resolvedUrl);
          relativePath = `images/${productId}/review_${String(entry.reviewIndex).padStart(6, '0')}/image_${String(entry.imageIndex).padStart(2, '0')}.${extension}`;
          resolvedUrl = fetched.resolvedUrl;
          downloadStatus = 'success';
          zipEntries.push({name: relativePath, data: fetched.data});
        } catch (fetchError) {
          error = fetchError.message;
        }
        results[index] = {
          review_index: entry.reviewIndex,
          platform: row.platform,
          product_id: row.product_id,
          product_url: row.product_url,
          product_title: row.product_title,
          user_name_masked: row.user_name_masked,
          rating: row.rating,
          review_time: row.review_time,
          sku: row.sku,
          review_text_raw: row.review_text_raw,
          image_index: entry.imageIndex,
          source_url: entry.sourceUrl,
          resolved_url: resolvedUrl,
          relative_path: relativePath,
          download_status: downloadStatus,
          error
        };
        finished++;
        statusNode.textContent = `正在下载评论图片：${finished}/${entries.length}`;
      }
    }

    await Promise.all(Array.from({length: Math.min(4, Math.max(entries.length, 1))}, worker));
    const manifest = [
      MANIFEST_COLUMNS.join(','),
      ...results.map(row => MANIFEST_COLUMNS.map(column => csvCell(row[column])).join(','))
    ].join('\r\n');
    const successCount = results.filter(row => row.download_status === 'success').length;
    const readme = [
      '京东评论图片包',
      '',
      `评论总数：${rows.length}`,
      `识别图片数：${entries.length}`,
      `成功保存图片数：${successCount}`,
      `失败图片数：${entries.length - successCount}`,
      '',
      'images.csv 保存评论正文、图片序号、原始 URL、包内相对路径及下载状态。',
      'images/ 目录保存实际图片。review_index 对应本次 ECComment CSV 的评论数据行顺序。'
    ].join('\r\n');
    zipEntries.push({name: 'images.csv', data: '\ufeff' + manifest});
    zipEntries.push({name: 'README.txt', data: readme});
    const blob = globalThis.JDZipBuilder.build(zipEntries);
    const objectUrl = URL.createObjectURL(blob);
    try {
      await chrome.downloads.download({
        url: objectUrl,
        filename: `jd_review_images_${payload.stamp}.zip`,
        saveAs: false
      });
    } finally {
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
    }
    return {reviewCount: rows.length, imageCount: entries.length, successCount};
  }

  async function start() {
    try {
      const payload = await chrome.runtime.sendMessage({type: 'IMAGE_EXPORT_READY'});
      if (!payload?.rows) throw new Error('没有找到待导出的评论检查点');
      const result = await buildPackage(payload);
      statusNode.textContent = `图片包已开始下载：成功 ${result.successCount}/${result.imageCount} 张。`;
      await chrome.runtime.sendMessage({type: 'IMAGE_EXPORT_DONE', ...result});
      setTimeout(() => window.close(), 1200);
    } catch (error) {
      statusNode.textContent = `图片包生成失败：${error.message}`;
      await chrome.runtime.sendMessage({type: 'IMAGE_EXPORT_FAILED', error: error.message});
    }
  }

  globalThis.JDImageExport = {extensionFor, imageEntries, buildPackage};
  start();
})();
