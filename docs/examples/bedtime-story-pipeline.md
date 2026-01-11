# Example: Bedtime Story Content Pipeline

This example demonstrates GOTN applied to an automated content generation system for children's bedtime stories.

## Domain Context

**Goal**: Produce nightly bedtime story sessions consisting of:
- Narrated story chapters (TTS)
- Ambient soundbeds
- Musical intros
- Animated visual covers

**Constraints**:
- Fully automated (no manual intervention in normal operation)
- Content must be age-appropriate and sleep-conducive
- Workflows are not pre-defined—they emerge through research

## Root Objective

```yaml
id: root-session-production
mode: instrumental
goal:
  statement: "Produce complete bedtime story sessions for ages 3-10"
  acceptance_criteria:
    - id: audio-complete
      description: "Full audio session renders without errors"
      type: artifact
      must_pass: true
    - id: content-safe
      description: "All content passes safety review"
      type: validation
      must_pass: true
    - id: sleep-effective
      description: "Session supports sleep onset (based on research)"
      type: validation
      must_pass: true
deliverable_type: artifact
budget:
  time_ms: 86400000  # 24 hours per session type
  cost_dollars: 50
```

## Node Decomposition

The root objective spawns child nodes as complexity is discovered:

```
[ROOT] Produce bedtime sessions
    │
    ├── [EPISTEMIC] Research age-appropriate content patterns
    │       │
    │       ├── [EPISTEMIC] Attention span by age
    │       │       └── Claims: "3-5yo: 5-8 min chapters"
    │       │
    │       ├── [EPISTEMIC] Sleep onset factors
    │       │       └── Claims: "Gradual energy decrease helps"
    │       │
    │       └── [EPISTEMIC] Tone references
    │               └── Claims: "Avoid anxiety-inducing cliffhangers"
    │
    ├── [DECISION] Commit to content structure ◄── SHIPPING GATE
    │       │
    │       └── Commitment:
    │           selected: "Two-part structure: arc chapter + vignettes"
    │           constraints:
    │             chapter_length: "5-8 min for 3-5, 8-12 for 5-8"
    │             vignette_count: "5-8 per session"
    │             energy_curve: "decreasing"
    │
    ├── [INSTRUMENTAL] Build story generation pipeline
    │       │
    │       ├── [EPISTEMIC] Research LLM prompting for children's stories
    │       ├── [DECISION] Commit to prompt templates
    │       └── [INSTRUMENTAL] Implement story generator
    │
    ├── [INSTRUMENTAL] Build TTS narration pipeline
    │       │
    │       ├── [EPISTEMIC] Research TTS providers
    │       │       ├── [EPISTEMIC] Evaluate ElevenLabs v3
    │       │       └── [EPISTEMIC] Evaluate alternatives
    │       │
    │       ├── [DECISION] Commit to ElevenLabs v3 ◄── SHIPPING GATE
    │       └── [INSTRUMENTAL] Implement TTS module
    │
    ├── [INSTRUMENTAL] Build soundbed assembly
    │       │
    │       ├── [EPISTEMIC] Research ambient audio generation
    │       ├── [EPISTEMIC] Research spatial audio techniques
    │       ├── [DECISION] Commit to component layering approach
    │       └── [INSTRUMENTAL] Implement soundbed mixer
    │
    └── [VALIDATE] Integration testing
            │
            ├── [VALIDATE] Age-appropriateness check
            ├── [VALIDATE] Audio quality validation
            └── [VALIDATE] Sleep-effectiveness proxy metrics
```

## Detailed Node Examples

### Epistemic Node: Research TTS Providers

```yaml
id: research-tts-providers
mode: epistemic
depth: 2
parent: build-tts-pipeline

goal:
  statement: "Determine optimal TTS provider for children's narration"
  original_question: "What TTS service produces the best emotive narration?"
  acceptance_criteria:
    - id: options-identified
      description: "At least 3 viable providers evaluated"
      type: knowledge
      must_pass: true
    - id: quality-compared
      description: "Audio quality assessed via blind test"
      type: validation
      must_pass: true
    - id: cost-analyzed
      description: "Per-minute pricing documented"
      type: metric
      must_pass: false
  deadline:
    type: soft
    timestamp: "2026-01-15T00:00:00Z"
    consequence: "Use default provider (ElevenLabs)"

budget:
  time_ms: 14400000  # 4 hours
  tokens: 100000
  cost_dollars: 20

autonomy_gate:
  proceed_threshold: 0.8
  must_pass_criteria: [options-identified, quality-compared]
  risk_flags: []
  human_required: false

exit_policy:
  on_success: complete
  on_budget_exhausted: degrade
  on_blocked: spawn_child
  degradation_output: "Recommend ElevenLabs v3 (industry standard)"

production_anchor: build-tts-pipeline

edges:
  - target: commit-tts-provider
    type: informs
```

### Decision Node: Commit to TTS Provider

```yaml
id: commit-tts-provider
mode: decision
depth: 2
parent: build-tts-pipeline

goal:
  statement: "Commit to TTS provider for production pipeline"
  acceptance_criteria:
    - id: provider-selected
      description: "Single provider chosen with rationale"
      type: commitment
      must_pass: true
    - id: fallback-defined
      description: "Backup provider identified"
      type: knowledge
      must_pass: false

budget:
  time_ms: 3600000  # 1 hour
  tokens: 10000

autonomy_gate:
  proceed_threshold: 0.85
  must_pass_criteria: [provider-selected]
  risk_flags: [cost]
  human_required: false

exit_policy:
  on_success: complete
  on_budget_exhausted: escalate
  on_blocked: escalate

edges:
  - target: research-tts-providers
    type: depends_on
  - target: implement-tts-module
    type: enables

# Output (after completion)
outputs:
  - type: commitment
    choice_set:
      - ElevenLabs v3
      - Google Cloud TTS
      - Amazon Polly
      - Azure Speech
    selected: "ElevenLabs v3"
    rationale: |
      - Highest emotive quality in blind tests (4:1 preference)
      - Emotive tag support aligns with narration needs
      - Cost acceptable at $0.30/1000 chars
      - Good API stability and documentation
    constraints:
      provider: elevenlabs
      model: eleven_multilingual_v2
      voice_id: "to-be-selected-per-character"
      output_format: mp3_44100_128
    residual_risks:
      - "Rate limits may constrain batch generation"
      - "Voice cloning requires separate agreement"
    rollback_plan: "TTS module uses abstract interface; can swap to Google TTS"
    assumption_ledger:
      - id: pricing-stable
        statement: "ElevenLabs pricing remains at current levels"
        basis: "No announced changes, enterprise tier available"
        expiry: "2026-06-01"
        invalidation_trigger: "Price increase >20%"
```

### Instrumental Node: Build TTS Module

```yaml
id: implement-tts-module
mode: instrumental
depth: 2
parent: build-tts-pipeline

goal:
  statement: "Implement TTS generation module with ElevenLabs integration"
  acceptance_criteria:
    - id: api-integration
      description: "ElevenLabs API wrapper implemented"
      type: artifact
      must_pass: true
    - id: emotive-tags
      description: "Emotive tag parser functional"
      type: artifact
      must_pass: true
    - id: cli-interface
      description: "CLI generates audio from text file"
      type: artifact
      must_pass: true
    - id: tests-passing
      description: "Unit tests cover core functionality"
      type: validation
      must_pass: true

budget:
  time_ms: 28800000  # 8 hours
  tokens: 200000
  cost_dollars: 10

autonomy_gate:
  proceed_threshold: 0.9
  must_pass_criteria: [api-integration, cli-interface, tests-passing]
  risk_flags: []
  human_required: false

exit_policy:
  on_success: complete
  on_budget_exhausted: escalate
  on_blocked: spawn_child

edges:
  - target: commit-tts-provider
    type: depends_on
  - target: integration-testing
    type: enables

# Output (after completion)
outputs:
  - type: artifact
    path: "voice/src/nes_voice/providers/elevenlabs.py"
    artifact_type: code
    hash: "sha256:abc123..."
    metadata:
      language: python
      loc: 250
      test_coverage: 0.85
```

### Validation Node: Age-Appropriateness Check

```yaml
id: validate-age-appropriate
mode: instrumental  # Validation is still "doing work"
depth: 2
parent: integration-testing

goal:
  statement: "Validate all generated content is age-appropriate"
  acceptance_criteria:
    - id: vocabulary-level
      description: "Vocabulary matches target age reading level"
      type: validation
      must_pass: true
    - id: no-scary-content
      description: "No frightening imagery or themes"
      type: validation
      must_pass: true
    - id: positive-messages
      description: "Themes support healthy development"
      type: validation
      must_pass: false

budget:
  time_ms: 7200000  # 2 hours
  tokens: 50000
  cost_dollars: 5

autonomy_gate:
  proceed_threshold: 0.95  # High bar for safety
  must_pass_criteria: [vocabulary-level, no-scary-content]
  risk_flags: [safety, appropriateness]
  human_required: false
  escalation_triggers:
    - "Any scary content detected"
    - "Vocabulary above age level"

exit_policy:
  on_success: complete
  on_budget_exhausted: escalate  # Never skip safety
  on_blocked: escalate

edges:
  - target: implement-story-generator
    type: depends_on
  - target: implement-tts-module
    type: depends_on
```

## Confidence Flow Example

When `research-tts-providers` completes:

```python
# Child node completes with claims
research_node.claims = [
    Claim(
        proposition="ElevenLabs v3 produces best emotive narration",
        confidence=0.85,
        evidence_ids=["blind-test-001", "user-reviews"]
    ),
    Claim(
        proposition="Cost is $0.30/1000 characters",
        confidence=0.95,
        evidence_ids=["pricing-page-2026-01"]
    )
]

# Parent decision node aggregates
decision_node.confidence.by_criterion = {
    'provider-selected': 0.85,  # From research confidence
    'fallback-defined': 0.70    # Secondary research
}

# Aggregate: must_pass weighted heavily
aggregate = (0.85 * 0.8) + (0.70 * 0.2) = 0.82

# Exceeds threshold (0.85)? No, but close
# Autonomy decision: spawn_research to fill gap OR proceed_anyway if VOI low
```

## VOI Check Example

Should we research a 4th TTS provider?

```python
def evaluate_4th_provider_research():
    current_confidence = 0.82
    threshold = 0.85
    gap = threshold - current_confidence  # 0.03

    # Best case: 4th provider is better, confidence -> 0.90
    potential_gain = 0.08

    # Cost: 2 hours, $5, 20k tokens
    cost = normalize_cost(hours=2, dollars=5, tokens=20000)  # ~0.15

    # VOI = probability_of_gain * gain_magnitude
    # Probability that 4th provider beats ElevenLabs? Low (~20%)
    voi = 0.20 * potential_gain  # 0.016

    # VOI (0.016) < Cost (0.15) → Don't research
    return False, "VOI too low, proceed with current selection"
```

## Shipping Gate Enforcement

The system prevents research without delivery:

```
❌ INVALID: Research node without shipping gate
[EPISTEMIC] Research TTS options
    └── No downstream decision or build node
    → FLAG: "Research without production anchor"

✅ VALID: Research connects to decision
[EPISTEMIC] Research TTS options
    └── [DECISION] Commit to TTS provider
        └── [INSTRUMENTAL] Build TTS module
```

## Human Escalation Example

When validation fails with low confidence:

```yaml
# Validation node result
id: validate-age-appropriate
status: escalated

escalation_context:
  reason: "Confidence below threshold for safety-critical criterion"
  criterion: no-scary-content
  confidence: 0.65
  threshold: 0.95

  flagged_content:
    - story_id: "violet-ep-03"
      segment: "The storm clouds gathered darkly..."
      concern: "Potentially frightening imagery for 3-5 age group"

  options:
    - action: "Remove segment"
      impact: "Story coherence reduced"
    - action: "Soften language"
      suggested: "The fluffy clouds gathered softly..."
    - action: "Accept risk"
      note: "Mild weather description, may be acceptable"

  human_decision_required: true
  timeout: "48h"
  default_action: "Soften language"
```

## Full Pipeline Visualization

```
SESSION PRODUCTION PIPELINE
═══════════════════════════════════════════════════════════════

[ROOT] Produce Sessions ────────────────────────────────────────┐
    │                                                           │
    ├── CONTENT TRACK ──────────────────────────────────────┐   │
    │   │                                                   │   │
    │   ├── [E] Research age patterns ──┐                   │   │
    │   │       ├── [E] Attention span  │                   │   │
    │   │       ├── [E] Sleep factors   ├──► [D] Commit     │   │
    │   │       └── [E] Tone refs       │     structure     │   │
    │   │                               │         │         │   │
    │   │                               │         ▼         │   │
    │   ├── [E] Research LLM prompting ─┴──► [D] Commit     │   │
    │   │                                    prompts        │   │
    │   │                                       │           │   │
    │   │                                       ▼           │   │
    │   └── [I] Build story generator ◄─────────┘           │   │
    │           │                                           │   │
    │           ▼                                           │   │
    ├── AUDIO TRACK ────────────────────────────────────────┤   │
    │   │                                                   │   │
    │   ├── [E] Research TTS ───────────► [D] Commit TTS ───┤   │
    │   │       ├── [E] ElevenLabs          │               │   │
    │   │       └── [E] Alternatives        ▼               │   │
    │   │                              [I] Build TTS ───────┤   │
    │   │                                                   │   │
    │   ├── [E] Research soundbeds ─────► [D] Commit ───────┤   │
    │   │       ├── [E] Components          approach        │   │
    │   │       └── [E] Spatial audio       │               │   │
    │   │                                   ▼               │   │
    │   │                              [I] Build mixer ─────┤   │
    │   │                                                   │   │
    │   └── [E] Research musical intro ─► [D] Commit ───────┤   │
    │                                       │               │   │
    │                                       ▼               │   │
    │                                  [I] Build intro ─────┤   │
    │                                                       │   │
    ├── VISUAL TRACK ───────────────────────────────────────┤   │
    │   │                                                   │   │
    │   ├── [E] Research image gen ─────► [D] Commit ───────┤   │
    │   │                                   tool            │   │
    │   │                                   │               │   │
    │   └── [E] Research animation ─────► [D] Commit ───────┤   │
    │                                       Veo3            │   │
    │                                       │               │   │
    │                                       ▼               │   │
    │                                  [I] Build visual ────┤   │
    │                                                       │   │
    └── VALIDATION ◄────────────────────────────────────────┘   │
        │                                                       │
        ├── [V] Age-appropriate ────────────────────────────────┤
        ├── [V] Audio quality ──────────────────────────────────┤
        └── [V] Sleep effectiveness ────────────────────────────┘
                    │
                    ▼
            [COMPLETE] Sessions ready for production

Legend:
[E] = Epistemic (Research)
[D] = Decision (Shipping Gate)
[I] = Instrumental (Build)
[V] = Validation
───► = depends_on (blocking)
- - ► = informs (non-blocking)
```
