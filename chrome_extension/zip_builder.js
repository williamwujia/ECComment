(() => {
  const encoder = new TextEncoder();
  const crcTable = new Uint32Array(256);
  for (let value = 0; value < 256; value++) {
    let crc = value;
    for (let bit = 0; bit < 8; bit++) crc = (crc & 1) ? (0xedb88320 ^ (crc >>> 1)) : (crc >>> 1);
    crcTable[value] = crc >>> 0;
  }

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (const byte of bytes) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  }

  function bytesOf(value) {
    if (typeof value === 'string') return encoder.encode(value);
    if (value instanceof Uint8Array) return value;
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    throw new TypeError('ZIP entry data must be text, Uint8Array, or ArrayBuffer');
  }

  function dosTime(date = new Date()) {
    const year = Math.max(date.getFullYear(), 1980);
    return {
      time: (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2),
      date: ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate()
    };
  }

  function view(size) {
    const bytes = new Uint8Array(size);
    return {bytes, data: new DataView(bytes.buffer)};
  }

  function build(entries) {
    if (entries.length > 0xffff) throw new Error('图片包文件数超过 ZIP32 的 65535 个限制');
    const localParts = [];
    const centralParts = [];
    let offset = 0;
    const stamp = dosTime();
    for (const entry of entries) {
      const name = encoder.encode(String(entry.name).replaceAll('\\', '/'));
      const content = bytesOf(entry.data);
      if (content.byteLength > 0xffffffff || offset > 0xffffffff) {
        throw new Error('图片包超过 ZIP32 的 4GB 限制');
      }
      const checksum = crc32(content);
      const local = view(30);
      local.data.setUint32(0, 0x04034b50, true);
      local.data.setUint16(4, 20, true);
      local.data.setUint16(6, 0x0800, true);
      local.data.setUint16(8, 0, true);
      local.data.setUint16(10, stamp.time, true);
      local.data.setUint16(12, stamp.date, true);
      local.data.setUint32(14, checksum, true);
      local.data.setUint32(18, content.byteLength, true);
      local.data.setUint32(22, content.byteLength, true);
      local.data.setUint16(26, name.byteLength, true);
      local.data.setUint16(28, 0, true);
      localParts.push(local.bytes, name, content);

      const central = view(46);
      central.data.setUint32(0, 0x02014b50, true);
      central.data.setUint16(4, 20, true);
      central.data.setUint16(6, 20, true);
      central.data.setUint16(8, 0x0800, true);
      central.data.setUint16(10, 0, true);
      central.data.setUint16(12, stamp.time, true);
      central.data.setUint16(14, stamp.date, true);
      central.data.setUint32(16, checksum, true);
      central.data.setUint32(20, content.byteLength, true);
      central.data.setUint32(24, content.byteLength, true);
      central.data.setUint16(28, name.byteLength, true);
      central.data.setUint16(30, 0, true);
      central.data.setUint16(32, 0, true);
      central.data.setUint16(34, 0, true);
      central.data.setUint16(36, 0, true);
      central.data.setUint32(38, 0, true);
      central.data.setUint32(42, offset, true);
      centralParts.push(central.bytes, name);
      offset += local.bytes.byteLength + name.byteLength + content.byteLength;
    }

    const centralSize = centralParts.reduce((sum, part) => sum + part.byteLength, 0);
    const end = view(22);
    end.data.setUint32(0, 0x06054b50, true);
    end.data.setUint16(4, 0, true);
    end.data.setUint16(6, 0, true);
    end.data.setUint16(8, entries.length, true);
    end.data.setUint16(10, entries.length, true);
    end.data.setUint32(12, centralSize, true);
    end.data.setUint32(16, offset, true);
    end.data.setUint16(20, 0, true);
    return new Blob([...localParts, ...centralParts, end.bytes], {type: 'application/zip'});
  }

  globalThis.JDZipBuilder = {build, crc32};
})();
