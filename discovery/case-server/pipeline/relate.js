/**
 *  Layer 4 — RELATE
 *
 *  Cross-file relationship mapping.
 *  Runs AFTER all files have been processed through L0-L3.
 *  Works on the aggregate data to find:
 *  - Files sharing the same entities (people, laws, orgs, locations)
 *  - Temporal clusters (files created/modified in same timeframe)
 *  - Topic clusters (files with overlapping key terms)
 *  - Document groups (same naming pattern or directory lineage)
 *
 *  Produces:
 *  - Global entity index (each entity → list of files)
 *  - Per-file related_files list
 *  - Timeline (chronological events derived from dates)
 */

/**
 * Build a global entity index from all files' Layer 3 data.
 * @param {object} allFiles - store.getAllFiles() — hash → { layers, file_ref }
 * @returns {{ people, organizations, laws, locations, dates }}
 */
function buildEntityIndex(allFiles) {
  const index = {
    people: {},       // name → [{ hash, file_ref, position }]
    organizations: {},
    laws: {},         // normalized law ref → [{ hash, file_ref }]
    locations: {},
    dates: {},
  };

  for (const [hash, record] of Object.entries(allFiles)) {
    const L3 = record.layers && record.layers.L3;
    if (!L3 || !L3.entities) continue;
    const fileRef = record.file_ref || hash;

    for (const person of (L3.entities.people || [])) {
      const key = person.raw.toLowerCase();
      if (!index.people[key]) index.people[key] = [];
      index.people[key].push({ hash, file_ref: fileRef });
    }
    for (const org of (L3.entities.organizations || [])) {
      const key = org.normalized;
      if (!index.organizations[key]) index.organizations[key] = [];
      index.organizations[key].push({ hash, file_ref: fileRef });
    }
    for (const law of (L3.entities.legal_refs || [])) {
      const key = law.normalized;
      if (!index.laws[key]) index.laws[key] = [];
      index.laws[key].push({ hash, file_ref: fileRef });
    }
    for (const loc of (L3.entities.locations || [])) {
      const key = loc.normalized;
      if (!index.locations[key]) index.locations[key] = [];
      index.locations[key].push({ hash, file_ref: fileRef });
    }
    for (const d of (L3.entities.dates || [])) {
      const key = d.raw;
      if (!index.dates[key]) index.dates[key] = [];
      index.dates[key].push({ hash, file_ref: fileRef });
    }
  }

  return index;
}

/**
 * Build relationships array: pairs of files connected by shared entities.
 * @param {object} entityIndex - from buildEntityIndex
 * @returns {Array<{ source, target, type, entity, strength }>}
 */
function buildRelationships(entityIndex) {
  const relMap = {}; // "hashA|hashB" → { types, strength }

  function addRel(hashA, hashB, type, entity) {
    if (hashA === hashB) return;
    const key = [hashA, hashB].sort().join("|");
    if (!relMap[key]) relMap[key] = { source: hashA, target: hashB, types: new Set(), entities: [], strength: 0 };
    relMap[key].types.add(type);
    relMap[key].entities.push(entity);
    relMap[key].strength++;
  }

  for (const [category, entityMap] of Object.entries(entityIndex)) {
    for (const [entity, files] of Object.entries(entityMap)) {
      if (files.length < 2 || files.length > 100) continue; // skip singletons and overly-common
      for (let i = 0; i < files.length; i++) {
        for (let j = i + 1; j < Math.min(files.length, i + 20); j++) { // cap pairings
          addRel(files[i].hash, files[j].hash, category, entity);
        }
      }
    }
  }

  return Object.values(relMap).map((r) => ({
    source: r.source,
    target: r.target,
    types: [...r.types],
    shared_entities: [...new Set(r.entities)].slice(0, 10),
    strength: r.strength,
  })).sort((a, b) => b.strength - a.strength);
}

/**
 * Build temporal clusters: group files by creation/modification month.
 * @param {object} allFiles - store.getAllFiles()
 * @returns {Array<{ period, file_count, files }>}
 */
function buildTemporalClusters(allFiles) {
  const buckets = {};

  for (const [hash, record] of Object.entries(allFiles)) {
    const L0 = record.layers && record.layers.L0;
    if (!L0) continue;
    const dateStr = L0.modified_at || L0.created_at;
    if (!dateStr) continue;
    const period = dateStr.slice(0, 7); // YYYY-MM
    if (!buckets[period]) buckets[period] = [];
    buckets[period].push({ hash, file_ref: record.file_ref, modified_at: dateStr });
  }

  return Object.entries(buckets)
    .map(([period, files]) => ({ period, file_count: files.length, files }))
    .sort((a, b) => a.period.localeCompare(b.period));
}

/**
 * Build per-file related files list from relationships.
 * @param {Array} relationships - from buildRelationships
 * @param {object} allFiles - store.getAllFiles() (for file_ref lookup)
 * @returns {object} hash → [{ related_hash, file_ref, strength, types }]
 */
function buildPerFileRelations(relationships, allFiles) {
  const perFile = {};

  for (const rel of relationships) {
    const sourceRef = allFiles[rel.source] ? allFiles[rel.source].file_ref : rel.source;
    const targetRef = allFiles[rel.target] ? allFiles[rel.target].file_ref : rel.target;

    if (!perFile[rel.source]) perFile[rel.source] = [];
    perFile[rel.source].push({
      related_hash: rel.target,
      file_ref: targetRef,
      strength: rel.strength,
      types: rel.types,
    });

    if (!perFile[rel.target]) perFile[rel.target] = [];
    perFile[rel.target].push({
      related_hash: rel.source,
      file_ref: sourceRef,
      strength: rel.strength,
      types: rel.types,
    });
  }

  // Sort each file's relations by strength and cap at 20
  for (const hash of Object.keys(perFile)) {
    perFile[hash] = perFile[hash]
      .sort((a, b) => b.strength - a.strength)
      .slice(0, 20);
  }

  return perFile;
}

/**
 * Build a timeline from dates found across all files.
 * @param {object} entityIndex - from buildEntityIndex
 * @param {object} allFiles - store.getAllFiles()
 * @returns {Array<{ date, files }>}
 */
function buildTimeline(entityIndex, allFiles) {
  const dateEntries = [];

  // From extracted dates in content
  for (const [dateStr, files] of Object.entries(entityIndex.dates || {})) {
    dateEntries.push({
      date: dateStr,
      source: "content",
      files: files.map((f) => ({
        hash: f.hash,
        file_ref: f.file_ref,
      })),
    });
  }

  // From file metadata dates
  for (const [hash, record] of Object.entries(allFiles)) {
    const L0 = record.layers && record.layers.L0;
    if (!L0 || !L0.created_at) continue;
    const dateStr = L0.created_at.slice(0, 10);
    dateEntries.push({
      date: dateStr,
      source: "file_created",
      files: [{ hash, file_ref: record.file_ref }],
    });
  }

  // Sort chronologically
  return dateEntries.sort((a, b) => a.date.localeCompare(b.date));
}

/**
 * Run Layer 4 on the complete store after L0-L3 processing.
 * @param {object} store - Pipeline store instance
 */
function processAll(store) {
  const allFiles = store.getAllFiles();
  const entityIndex = buildEntityIndex(allFiles);
  const relationships = buildRelationships(entityIndex);
  const temporalClusters = buildTemporalClusters(allFiles);
  const perFileRelations = buildPerFileRelations(relationships, allFiles);
  const timeline = buildTimeline(entityIndex, allFiles);

  // Store global entity index
  store.setEntities(entityIndex);

  // Store relationships
  store.setRelationships(relationships);

  // Store timeline
  store.setTimeline(timeline);

  // Attach per-file relations as L4 data
  for (const [hash, related] of Object.entries(perFileRelations)) {
    store.setLayer(hash, "L4", {
      related_files: related,
      relationship_count: related.length,
    });
  }

  return {
    entity_index_size: {
      people: Object.keys(entityIndex.people).length,
      organizations: Object.keys(entityIndex.organizations).length,
      laws: Object.keys(entityIndex.laws).length,
      locations: Object.keys(entityIndex.locations).length,
      dates: Object.keys(entityIndex.dates).length,
    },
    relationship_count: relationships.length,
    temporal_clusters: temporalClusters.length,
    timeline_entries: timeline.length,
  };
}

module.exports = { processAll, buildEntityIndex, buildRelationships, buildTemporalClusters };
