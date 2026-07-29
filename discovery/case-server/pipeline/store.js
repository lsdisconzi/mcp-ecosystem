/**
 *  Pipeline Store — Persistent enrichment data
 *
 *  Stores pipeline results per-file keyed by content hash.
 *  Survives rebuilds: if the same file (same hash) is re-ingested,
 *  previous enrichment data is preserved and only updated layers run.
 *
 *  Structure:
 *    {
 *      meta: { created_at, last_run, runs: [...] },
 *      files: {
 *        "<sha256>": { layers: { L0: {...}, L1: {...}, ... }, file_ref: "rel/path" }
 *      },
 *      entities: { people: {}, organizations: {}, laws: {}, dates: {}, locations: {} },
 *      relationships: [ { source, target, type, evidence } ],
 *      timeline: [ { date, event, files: [] } ]
 *    }
 */

const fs = require("fs");
const path = require("path");

const DEFAULT_STORE_FILE = "pipeline_store.json";

function createStore(storeFilePath) {
  const filePath = storeFilePath || path.resolve(__dirname, "..", DEFAULT_STORE_FILE);

  let data = {
    meta: { created_at: new Date().toISOString(), last_run: null, runs: [] },
    files: {},
    entities: { people: {}, organizations: {}, laws: {}, dates: {}, locations: {} },
    relationships: [],
    timeline: [],
    dedup: {},
    extraction: {},
  };

  // Load existing store if present
  try {
    if (fs.existsSync(filePath)) {
      data = JSON.parse(fs.readFileSync(filePath, "utf8"));
    }
  } catch (err) {
    console.warn(`Pipeline store: could not load ${filePath}, starting fresh.`, err.message);
  }

  function save() {
    try {
      fs.mkdirSync(path.dirname(filePath), { recursive: true });
      fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
    } catch (err) {
      console.error("Pipeline store: failed to save", err.message);
    }
  }

  function getFile(hash) {
    return data.files[hash] || null;
  }

  function hasFile(hash) {
    return !!data.files[hash];
  }

  function setFile(hash, record) {
    data.files[hash] = record;
  }

  function setLayer(hash, layerName, layerData) {
    if (!data.files[hash]) {
      data.files[hash] = { layers: {}, file_ref: null };
    }
    data.files[hash].layers[layerName] = layerData;
  }

  function getLayer(hash, layerName) {
    const file = data.files[hash];
    return file && file.layers ? file.layers[layerName] : null;
  }

  function recordRun(runInfo) {
    data.meta.last_run = new Date().toISOString();
    data.meta.runs.push({
      ...runInfo,
      timestamp: new Date().toISOString(),
    });
    // Keep last 100 runs
    if (data.meta.runs.length > 100) {
      data.meta.runs = data.meta.runs.slice(-100);
    }
  }

  function setEntities(entities) {
    data.entities = entities;
  }

  function getEntities() {
    return data.entities;
  }

  function setRelationships(rels) {
    data.relationships = rels;
  }

  function getRelationships() {
    return data.relationships;
  }

  function setTimeline(tl) {
    data.timeline = tl;
  }

  function getTimeline() {
    return data.timeline;
  }

  function setDedupResults(results) {
    data.dedup = results || {};
  }

  function getDedupResults() {
    return data.dedup || {};
  }

  function setExtractionResults(results) {
    data.extraction = results || {};
  }

  function getExtractionResults() {
    return data.extraction || {};
  }

  function getAllFiles() {
    return data.files;
  }

  function getMeta() {
    return data.meta;
  }

  function getRawData() {
    return data;
  }

  return {
    save,
    hasFile,
    getFile,
    setFile,
    setLayer,
    getLayer,
    recordRun,
    setEntities,
    getEntities,
    setRelationships,
    getRelationships,
    setTimeline,
    getTimeline,
    setDedupResults,
    getDedupResults,
    setExtractionResults,
    getExtractionResults,
    getAllFiles,
    getMeta,
    getRawData,
  };
}

module.exports = { createStore };
