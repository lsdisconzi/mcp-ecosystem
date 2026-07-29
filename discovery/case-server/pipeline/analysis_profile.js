'use strict';

const ANALYSIS_PROFILE_DEFAULT = 'general';

const ANALYSIS_PROFILE_META = {
  general: {
    key: 'general',
    label: 'General Workspace',
    scope: 'multi-domain operational documents',
    finding_singular: 'finding',
    finding_plural: 'findings',
    proceeding_label: 'formal escalation',
    narrative_title: 'Workspace Narrative',
    summary_title: 'Workspace Summary',
    findings_title: 'Findings Analysis',
    kb: {
      enabled: false,
      augment_extraction: false,
      persist_graph: false,
      jurisdictions: [],
      min_confidence_for_persist: 0.6,
      top_k_articles_search: 5
    }
  },
  office: {
    key: 'office',
    label: 'Office Operations',
    scope: 'administrative and procedural office records',
    finding_singular: 'operational finding',
    finding_plural: 'operational findings',
    proceeding_label: 'formal escalation',
    narrative_title: 'Office Operations Narrative',
    summary_title: 'Office Summary',
    findings_title: 'Operational Findings Analysis',
    kb: {
      enabled: false,
      augment_extraction: false,
      persist_graph: false,
      jurisdictions: [],
      min_confidence_for_persist: 0.6,
      top_k_articles_search: 5
    }
  },
  'law-firm': {
    key: 'law-firm',
    label: 'Law Firm Operations',
    scope: 'legal office material beyond strict violation analysis',
    finding_singular: 'triage finding',
    finding_plural: 'triage findings',
    proceeding_label: 'formal legal escalation',
    narrative_title: 'Law Office Narrative',
    summary_title: 'Matter Summary',
    findings_title: 'Triage Findings Analysis',
    kb: {
      enabled: true,
      augment_extraction: true,
      persist_graph: true,
      jurisdictions: ['BR', 'CL', 'INT', 'EU'],
      min_confidence_for_persist: 0.5,
      top_k_articles_search: 5
    }
  },
  business: {
    key: 'business',
    label: 'Business Operations',
    scope: 'corporate process, compliance, and reporting records',
    finding_singular: 'business finding',
    finding_plural: 'business findings',
    proceeding_label: 'governance escalation',
    narrative_title: 'Business Operations Narrative',
    summary_title: 'Business Summary',
    findings_title: 'Business Findings Analysis',
    kb: {
      enabled: false,
      augment_extraction: false,
      persist_graph: false,
      jurisdictions: [],
      min_confidence_for_persist: 0.6,
      top_k_articles_search: 5
    }
  },
  legal: {
    key: 'legal',
    label: 'Legal / Violations',
    scope: 'legal and regulatory case material',
    finding_singular: 'violation',
    finding_plural: 'violations',
    proceeding_label: 'legal proceeding',
    narrative_title: 'Case Narrative',
    summary_title: 'Case Summary',
    findings_title: 'Violations Analysis',
    kb: {
      enabled: true,
      augment_extraction: true,
      persist_graph: true,
      jurisdictions: ['BR', 'CL', 'INT', 'EU'],
      min_confidence_for_persist: 0.4,
      top_k_articles_search: 10
    }
  }
};

function normalizeAnalysisProfile(value) {
  const raw = String(value || '').trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(ANALYSIS_PROFILE_META, raw)
    ? raw
    : ANALYSIS_PROFILE_DEFAULT;
}

function getAnalysisProfileMeta(profile) {
  return ANALYSIS_PROFILE_META[normalizeAnalysisProfile(profile)];
}

function isLegalProfile(profile) {
  return normalizeAnalysisProfile(profile) === 'legal';
}

function getKbConfig(profile) {
  const meta = getAnalysisProfileMeta(profile);
  const kb = meta?.kb || ANALYSIS_PROFILE_META.general.kb;
  const env = {
    enabled:           process.env.KB_ENABLED === 'true' ? true
                     : process.env.KB_ENABLED === 'false' ? false
                     : kb.enabled,
    augment_extraction: process.env.KB_AUGMENT_EXTRACTION === 'true' ? true
                     : process.env.KB_AUGMENT_EXTRACTION === 'false' ? false
                     : kb.augment_extraction,
    persist_graph:      process.env.KB_PERSIST_GRAPH === 'true' ? true
                     : process.env.KB_PERSIST_GRAPH === 'false' ? false
                     : kb.persist_graph
  };
  return { ...kb, ...env };
}

module.exports = {
  ANALYSIS_PROFILE_DEFAULT,
  ANALYSIS_PROFILE_META,
  normalizeAnalysisProfile,
  getAnalysisProfileMeta,
  isLegalProfile,
  getKbConfig
};
