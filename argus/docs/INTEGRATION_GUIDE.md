# Argus Integration Guide
## Connecting with pinocchio-multi and Awareness-Agents

---

## Table of Contents
1. [Overview](#overview)
2. [pinocchio-multi Integration](#pinocchio-multi-integration)
3. [Awareness-Agents Integration](#awareness-agents-integration)
4. [Workflow Examples](#workflow-examples)
5. [Troubleshooting](#troubleshooting)
6. [Best Practices](#best-practices)

---

## Overview

Argus generates legal framework analyzers that integrate seamlessly with:
- **pinocchio-multi**: Main analysis platform where frameworks are deployed and used
- **Awareness-Agents**: Multi-agent system that can utilize generated analyzers for specialized legal analysis

### Integration Architecture
```
Argus (Generator) → Generated Analyzer → pinocchio-multi (Deployment) → Awareness-Agents (Usage)
```

---

## pinocchio-multi Integration

### 1. Deployment Process

#### Step 1: Generate Framework in Argus
1. Access Argus UI: `http://localhost:8029/view?path=frameworks/frameworks.html`
2. Upload legal document (PDF or text)
3. Generate AI configuration
4. Generate JavaScript analyzer
5. Download complete package as ZIP

#### Step 2: Deploy to pinocchio-multi
```bash
# 1. Extract downloaded package
unzip TokyoConventionAnalyzer_package.zip -d /tmp/

# 2. Copy to pinocchio-multi frameworks directory
cp -r /tmp/TokyoConventionAnalyzer/ \
  /path/to/pinocchio-multi/static/js/legal_frameworks/

# 3. Run watch script to register framework
cd /path/to/pinocchio-multi/scripts
python watch_frameworks.py
```

#### Step 3: Verify Deployment
1. Check `framework_list.json` is updated:
```json
{
  "tokyoconvention": {
    "name": "Convention on Offences and Certain Other Acts Committed on Board Aircraft",
    "path": "/static/js/legal_frameworks/TokyoConventionAnalyzer",
    "config": {...},
    "primary_jurisdiction": "International",
    "flag": "🇺🇳"
  }
}
```

2. Restart pinocchio-multi if needed
3. New framework appears in UI checkbox list

### 2. Directory Structure

```
pinocchio-multi/static/js/legal_frameworks/
└── TokyoConventionAnalyzer/
    ├── TokyoConventionAnalyzer.js      # Generated analyzer
    ├── config.json                     # Framework configuration
    ├── generated_prompt.txt            # AI prompt template
    └── Tokyo_Convention_1963.txt       # Original document
```

### 3. Framework Activation

#### Automatic Detection
The `watch_frameworks.py` script:
1. Scans `legal_frameworks/` directory for new analyzer folders
2. Reads `config.json` from each folder
3. Enriches with jurisdiction and flag using `JurisdictionEnricher`
4. Updates `framework_list.json`
5. Makes framework available in UI

#### Manual Activation (if needed)
```python
# Example manual activation script
import json
import os

framework_dir = "TokyoConventionAnalyzer"
config_path = f"static/js/legal_frameworks/{framework_dir}/config.json"

with open(config_path, 'r') as f:
    config = json.load(f)

framework_entry = {
    "tokyoconvention": {
        "name": config["framework_name"],
        "path": f"/static/js/legal_frameworks/{framework_dir}",
        "config": config,
        "primary_jurisdiction": config.get("jurisdiction", "Unknown"),
        "flag": "🇺🇳"  # Auto-detected by JurisdictionEnricher
    }
}

# Update framework_list.json
with open("framework_list.json", 'r+') as f:
    frameworks = json.load(f)
    frameworks.update(framework_entry)
    f.seek(0)
    json.dump(frameworks, f, indent=2)
```

### 4. Usage in pinocchio-multi

#### UI Integration
1. **Framework Selection**: Checkbox appears in analysis interface
2. **Analysis Execution**: When selected, analyzer runs on transcripts
3. **Results Display**: Violations shown with integrated severity assessment

#### API Integration
```javascript
// Example: Using generated analyzer in pinocchio-multi
const analyzer = require('./static/js/legal_frameworks/TokyoConventionAnalyzer/TokyoConventionAnalyzer.js');

function analyzeWithFramework(transcript, frameworkName) {
    const violations = analyzer.analyzeTranscript(transcript, frameworkName);
    return {
        violations: violations,
        framework: frameworkName,
        timestamp: new Date().toISOString()
    };
}
```

---

## Awareness-Agents Integration

### 1. Agent Architecture Integration

#### Legal Specialist Agent
```python
# Example: Legal specialist agent using Argus-generated analyzers
class LegalFrameworkAgent:
    def __init__(self, framework_path):
        self.framework_path = framework_path
        self.analyzer = self.load_analyzer(framework_path)
    
    def load_analyzer(self, path):
        """Load generated analyzer from Argus"""
        # Implementation depends on analyzer format
        # Could be JavaScript module or Python wrapper
        pass
    
    def analyze_conversation(self, transcript):
        """Analyze conversation for legal violations"""
        violations = self.analyzer.detect_violations(transcript)
        return self.format_violations(violations)
    
    def format_violations(self, violations):
        """Format violations for agent communication"""
        return {
            "agent": "LegalFrameworkAgent",
            "framework": self.analyzer.config.framework_name,
            "violations": violations,
            "severity_summary": self.calculate_severity(violations)
        }
```

### 2. Multi-Agent Coordination

#### Framework Distribution
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Agent: Brazilian│    │  Agent:         │    │  Agent:         │
│  Law Specialist  │    │  International  │    │  Corporate      │
│                  │    │  Law Specialist │    │  Policy Expert  │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • CDC Analyzer   │    │ • Montreal      │    │ • Code of       │
│ • ANAC Res.      │    │   Convention    │    │   Conduct       │
│ • Brazilian      │    │ • Tokyo Conv.   │    │ • Internal      │
│   Constitution   │    │ • ICAO Annexes  │    │   Regulations   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                         ┌─────────────────┐
                         │  Coordinator    │
                         │  Agent          │
                         └─────────────────┘
```

#### Coordinator Agent Example
```python
class LegalCoordinatorAgent:
    def __init__(self):
        self.specialists = {
            "brazilian": LegalFrameworkAgent("BrazilianLawAnalyzer"),
            "international": LegalFrameworkAgent("InternationalLawAnalyzer"),
            "corporate": LegalFrameworkAgent("CorporatePolicyAnalyzer")
        }
    
    def coordinate_analysis(self, transcript, context):
        """Coordinate multiple legal analyses"""
        results = {}
        
        # Determine which frameworks apply based on context
        applicable_frameworks = self.determine_applicable_frameworks(context)
        
        # Run analyses in parallel
        for framework in applicable_frameworks:
            if framework in self.specialists:
                results[framework] = self.specialists[framework].analyze_conversation(transcript)
        
        # Consolidate results
        return self.consolidate_results(results)
```

### 3. Real-time Analysis Integration

#### WebSocket Integration
```javascript
// Example: Real-time analysis in awareness-agents
const WebSocket = require('ws');
const TokyoAnalyzer = require('./TokyoConventionAnalyzer.js');

const wss = new WebSocket.Server({ port: 8080 });

wss.on('connection', (ws) => {
    console.log('Awareness-agent connected');
    
    ws.on('message', (message) => {
        const data = JSON.parse(message);
        
        if (data.type === 'analyze_transcript') {
            const violations = TokyoAnalyzer.analyzeTranscript(data.transcript);
            
            ws.send(JSON.stringify({
                type: 'analysis_result',
                violations: violations,
                framework: 'Tokyo Convention',
                timestamp: new Date().toISOString()
            }));
        }
    });
});
```

#### REST API Endpoint
```python
# Flask endpoint for awareness-agents
@app.route('/api/analyze_with_framework', methods=['POST'])
def analyze_with_framework():
    data = request.json
    transcript = data.get('transcript')
    framework_name = data.get('framework')
    
    # Load appropriate analyzer based on framework
    analyzer_path = f"../pinocchio-multi/static/js/legal_frameworks/{framework_name}Analyzer/{framework_name}Analyzer.js"
    
    # Execute analysis (implementation depends on JS-Python bridge)
    violations = execute_js_analyzer(analyzer_path, transcript)
    
    return jsonify({
        'success': True,
        'violations': violations,
        'framework': framework_name
    })
```

---

## Workflow Examples

### Example 1: Airline Complaint Analysis

#### Scenario
Passenger complaint about denied boarding and mistreatment.

#### Analysis Workflow
```
1. Argus generates analyzers for:
   - Montreal Convention 1999 (International)
   - ANAC Resolution 400 (Brazil)
   - Brazilian Consumer Defense Code

2. pinocchio-multi deploys all three analyzers

3. Awareness-agents coordinate:
   - International agent: Checks Montreal Convention violations
   - Brazilian agent: Checks ANAC and CDC violations
   - Coordinator: Consolidates results, identifies overlapping violations

4. Result: Comprehensive legal analysis covering all applicable frameworks
```

#### Code Implementation
```python
def analyze_airline_complaint(transcript):
    # Load all relevant analyzers
    analyzers = {
        'montreal': load_analyzer('MontrealConventionAnalyzer'),
        'anac': load_analyzer('ANACResolution400Analyzer'),
        'cdc': load_analyzer('CDCAnalyzer')
    }
    
    results = {}
    for name, analyzer in analyzers.items():
        results[name] = analyzer.analyze(transcript)
    
    # Cross-reference violations
    consolidated = consolidate_violations(results)
    
    return {
        'per_framework': results,
        'consolidated': consolidated,
        'recommendations': generate_recommendations(consolidated)
    }
```

### Example 2: Corporate Ethics Investigation

#### Scenario
Internal investigation of potential ethics violations.

#### Analysis Workflow
```
1. Argus generates analyzers for:
   - Company Code of Conduct
   - Anti-Corruption Policy
   - Data Privacy Regulations

2. pinocchio-multi deploys corporate policy analyzers

3. Awareness-agents:
   - Ethics agent: Monitors for code of conduct violations
   - Compliance agent: Checks regulatory compliance
   - Privacy agent: Ensures data protection compliance

4. Result: Multi-faceted ethics and compliance assessment
```

---

## Troubleshooting

### Common Integration Issues

#### Issue 1: Framework Not Appearing in pinocchio-multi
**Symptoms**: Framework not in checkbox list after deployment
**Solutions**:
1. Check `watch_frameworks.py` ran successfully
2. Verify `framework_list.json` was updated
3. Check directory permissions: `ls -la static/js/legal_frameworks/`
4. Restart pinocchio-multi server

#### Issue 2: Analyzer Loading Errors
**Symptoms**: JavaScript errors when analyzer runs
**Solutions**:
1. Check browser console for specific errors
2. Verify all dependencies in generated analyzer
3. Check for CORS issues in API calls
4. Validate analyzer was generated with latest Argus version

#### Issue 3: Awareness-Agent Communication Failures
**Symptoms**: Agents can't access or use analyzers
**Solutions**:
1. Verify file paths are correct
2. Check agent permissions to access analyzer files
3. Validate WebSocket/REST API connectivity
4. Check analyzer compatibility with agent runtime

### Debugging Steps

#### Step 1: Verify Argus Generation
```bash
# Check generated analyzer structure
ls -la /tmp/TokyoConventionAnalyzer/
cat /tmp/TokyoConventionAnalyzer/config.json
```

#### Step 2: Verify pinocchio-multi Deployment
```bash
# Check deployment directory
ls -la /path/to/pinocchio-multi/static/js/legal_frameworks/TokyoConventionAnalyzer/

# Check framework list
cat /path/to/pinocchio-multi/framework_list.json | grep -A5 -B5 tokyoconvention
```

#### Step 3: Test Analyzer Functionality
```javascript
// Simple test script
const analyzer = require('./TokyoConventionAnalyzer.js');
const testTranscript = "The commander ordered the passenger to disembark...";
const result = analyzer.analyzeTranscript(testTranscript);
console.log(JSON.stringify(result, null, 2));
```

---

## Best Practices

### 1. Framework Management

#### Version Control
```bash
# Use semantic versioning for framework updates
TokyoConventionAnalyzer_v1.0.0/
TokyoConventionAnalyzer_v1.1.0/  # Added new article patterns
TokyoConventionAnalyzer_v2.0.0/  # Major rewrite with SYSTEM_PROMPT fix
```

#### Documentation
- Keep `generated_prompt.txt` for reference
- Document any manual modifications to generated analyzers
- Maintain changelog for framework updates

### 2. Performance Optimization

#### Analyzer Optimization
- Minimize generated JavaScript size
- Use efficient regex patterns in `analysis_focus`
- Implement caching for frequent analyses

#### Deployment Optimization
- Deploy during low-traffic periods
- Use symbolic links for common framework components
- Implement lazy loading for large analyzers

### 3. Security Considerations

#### Access Control
- Restrict write access to framework directories
- Validate analyzer inputs to prevent injection attacks
- Implement rate limiting for analyzer usage

#### Code Validation
- Review generated analyzers before production deployment
- Implement checksum verification for analyzer integrity
- Regular security audits of analyzer code

### 4. Monitoring and Maintenance

#### Health Checks
```python
# Example health check script
def check_framework_health(framework_name):
    analyzer_path = f"legal_frameworks/{framework_name}Analyzer"
    
    checks = {
        "directory_exists": os.path.exists(analyzer_path),
        "config_valid": validate_config(f"{analyzer_path}/config.json"),
        "analyzer_loads": test_analyzer_load(f"{analyzer_path}/{framework_name}Analyzer.js"),
        "recent_usage": check_usage_stats(framework_name)
    }
    
    return all(checks.values()), checks
```

#### Usage Analytics
- Track which frameworks are most frequently used
- Monitor analysis performance and response times
- Log errors and exceptions for debugging

---

## Quick Reference

### Deployment Commands
```bash
# Generate and deploy new framework
cd /Users/leandrodisconzi/Documents/sa_server/Argus
./start.sh  # Start Argus
# Use UI to generate analyzer, download ZIP

# Deploy to pinocchio-multi
unzip ~/Downloads/TokyoConventionAnalyzer_package.zip -d /tmp/
cp -r /tmp/TokyoConventionAnalyzer/ \
  ~/Documents/sa_server/pinocchio-multi/static/js/legal_frameworks/
cd ~/Documents/sa_server/pinocchio-multi/scripts
python watch_frameworks.py
```

### Integration Test
```python
# Quick integration test script
import requests
import json

# Test Argus API
response = requests.post(
    'http://localhost:8029/api/extract_pdf_text',
    files={'file': open('legal_doc.pdf', 'rb')}
)
print("PDF extraction:", response.status_code)

# Test analyzer in pinocchio-multi
test_data = {
    'transcript': 'Sample conversation text...',
    'framework': 'TokyoConvention'
}
response = requests.post(
    'http://localhost:8000/api/analyze',
    json=test_data
)
print("Analysis result:", response.json())
```

---

## Support and Resources

### Documentation
- `ARGUS_ANALYSIS_REPORT.md` - Complete system analysis
- `README.md` - Quick start guide
- Source code comments - Detailed implementation notes

### Contact
- Development team for technical issues
- Legal experts for framework validation
- System administrators for deployment support

### Updates
- Check for Argus updates regularly
- Subscribe to framework update notifications
- Participate in integration testing

---
**Last Updated**: $(date)
**Integration Version**: 1.0.0
**Compatible With**: pinocchio-multi v2+, Awareness-Agents v1+