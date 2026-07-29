/**
 *  Layer 0 — INGEST & LOG
 *
 *  First contact with files. Records:
 *  - SHA-256 content hash (identity & dedup)
 *  - Ingestion timestamp
 *  - Original absolute path
 *  - File system metadata (permissions, inode, links, uid/gid)
 *  - Directory depth from root
 */

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const MAX_HASH_SIZE = 100 * 1024 * 1024; // 100 MB — skip hashing huge files

function hashFile(filePath) {
  try {
    const stats = fs.statSync(filePath);
    if (stats.size > MAX_HASH_SIZE) {
      // For very large files, hash first 1 MB + size as fingerprint
      const fd = fs.openSync(filePath, "r");
      const buf = Buffer.alloc(1024 * 1024);
      const bytesRead = fs.readSync(fd, buf, 0, buf.length, 0);
      fs.closeSync(fd);
      const h = crypto.createHash("sha256");
      h.update(buf.subarray(0, bytesRead));
      h.update(`|size:${stats.size}`);
      return h.digest("hex");
    }
    const content = fs.readFileSync(filePath);
    return crypto.createHash("sha256").update(content).digest("hex");
  } catch {
    return null;
  }
}

function getExtendedStats(filePath) {
  try {
    const s = fs.statSync(filePath);
    return {
      size_bytes: s.size,
      created_at: s.birthtime.toISOString(),
      modified_at: s.mtime.toISOString(),
      accessed_at: s.atime.toISOString(),
      changed_at: s.ctime.toISOString(),  // inode change time
      permissions: "0" + (s.mode & 0o777).toString(8),
      inode: s.ino,
      hard_links: s.nlink,
      uid: s.uid,
      gid: s.gid,
      is_empty: s.size === 0,
    };
  } catch {
    return {
      size_bytes: 0, created_at: null, modified_at: null,
      accessed_at: null, changed_at: null, permissions: null,
      inode: null, hard_links: null, uid: null, gid: null, is_empty: true,
    };
  }
}

/**
 * Process a single file through Layer 0
 * @param {string} filePath - Absolute file path
 * @param {string} rootDir - Root directory for relative path calculation
 * @param {string} ingestionId - ID of this ingestion run
 * @returns {{ hash: string, data: object }}
 */
function processFile(filePath, rootDir, ingestionId) {
  const rel = path.relative(rootDir, filePath);
  const depth = rel.split(path.sep).filter(Boolean).length;
  const hash = hashFile(filePath);
  const extStats = getExtendedStats(filePath);

  return {
    hash,
    data: {
      ingested_at: new Date().toISOString(),
      ingestion_id: ingestionId,
      original_absolute_path: filePath,
      relative_path: rel,
      directory: path.dirname(rel),
      filename: path.basename(filePath),
      stem: path.basename(filePath, path.extname(filePath)),
      extension: path.extname(filePath).toLowerCase(),
      depth,
      hash_sha256: hash,
      ...extStats,
    },
  };
}

module.exports = { processFile, hashFile };
