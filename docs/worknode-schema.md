# WorkNode Schema

## TypeScript Interfaces

```typescript
/**
 * The fundamental unit of work in GOTN.
 * Represents research, building, or decision-making activities.
 */
interface WorkNode {
  id: string;
  depth: number;  // Current recursion depth (for bounds checking)

  // === INTENT LAYER ===
  mode: 'epistemic' | 'instrumental' | 'decision';
  goal: Goal;
  parent?: WorkNodeRef;

  // === WORK LAYER ===
  deliverable_type: 'knowledge' | 'artifact' | 'commitment';
  budget: Budget;

  // === EVIDENCE LAYER ===
  claims: Claim[];
  evidence: Evidence[];
  confidence: AggregatedConfidence;

  // === CONTROL LAYER ===
  autonomy_gate: AutonomyGate;
  exit_policy: ExitPolicy;
  status: NodeStatus;

  // === GRAPH LAYER ===
  edges: TypedEdge[];
  children: WorkNodeRef[];

  // === OUTPUTS ===
  outputs: Output[];
  created_at: Timestamp;
  updated_at: Timestamp;
}

type WorkNodeRef = string;  // Node ID reference

type NodeStatus =
  | 'pending'    // Not yet ready to start
  | 'ready'      // Dependencies met, can start
  | 'running'    // Actively being worked on
  | 'blocked'    // Waiting on child nodes
  | 'complete'   // Successfully finished
  | 'degraded'   // Finished with minimal viable output
  | 'escalated'  // Requires human intervention
  | 'failed'     // Unrecoverable error
  | 'cancelled'; // Terminated by parent

/**
 * What we're trying to achieve.
 */
interface Goal {
  statement: string;              // Action-oriented: "Determine...", "Build...", "Commit to..."
  original_question?: string;     // If spawned from a question, preserve for traceability
  acceptance_criteria: Criterion[];
  deadline?: Deadline;
}

interface Criterion {
  id: string;
  description: string;
  type: 'knowledge' | 'artifact' | 'validation' | 'metric';
  satisfied: boolean;
  confidence: number;             // 0.0 - 1.0
  evidence_ids: string[];         // References to supporting evidence
  must_pass: boolean;             // If true, failure blocks completion
}

interface Deadline {
  type: 'soft' | 'hard';
  timestamp: Timestamp;
  consequence: string;            // What happens if missed
}

/**
 * Resource constraints for this node.
 */
interface Budget {
  time_ms?: number;               // Wall clock time
  tokens?: number;                // LLM tokens
  steps?: number;                 // Discrete operations
  cost_dollars?: number;          // API/compute costs
  exhausted: boolean;
}

/**
 * A proposition we believe to be true, with confidence.
 */
interface Claim {
  id: string;
  proposition: string;            // The statement we're claiming
  confidence: number;             // 0.0 - 1.0
  evidence_ids: string[];         // Supporting evidence
  expiry?: Timestamp;             // When this claim needs re-validation
  scope: string;                  // Context in which this claim applies
}

/**
 * Supporting material for claims and decisions.
 */
interface Evidence {
  id: string;
  type: 'research' | 'experiment' | 'expert' | 'documentation' | 'validation';
  source: string;                 // URL, file path, or description
  summary: string;                // Key takeaway
  strength: number;               // 0.0 - 1.0 (how reliable)
  recency: Timestamp;             // When was this evidence gathered
  relevance: number;              // 0.0 - 1.0 (how applicable to our context)
}

/**
 * Aggregated confidence across all criteria.
 */
interface AggregatedConfidence {
  aggregate: number;              // Combined score
  by_criterion: Map<string, number>;  // Per-criterion scores
  aggregation_method: 'weighted_min' | 'weighted_mean' | 'custom';
  last_computed: Timestamp;
}

/**
 * Controls when the node can proceed autonomously.
 */
interface AutonomyGate {
  proceed_threshold: number;      // Confidence level to auto-proceed (default: 0.8)
  must_pass_criteria: string[];   // Criterion IDs that must exceed threshold
  risk_flags: RiskFlag[];         // Conditions that raise the bar
  human_required: boolean;        // Force human review regardless of confidence
  escalation_triggers: string[];  // Conditions that force escalation
}

type RiskFlag = 'safety' | 'cost' | 'appropriateness' | 'legal' | 'irreversible';

/**
 * What to do when the node can't complete normally.
 */
interface ExitPolicy {
  on_success: 'complete';
  on_budget_exhausted: 'escalate' | 'degrade' | 'fail';
  on_blocked: 'spawn_child' | 'escalate' | 'wait';
  on_low_confidence: 'spawn_research' | 'escalate' | 'proceed_anyway';
  degradation_output?: string;    // Minimal viable output description
  rollback_plan?: string;         // How to undo if needed
}

/**
 * Relationship between nodes.
 */
interface TypedEdge {
  target: WorkNodeRef;
  type: EdgeType;
  metadata?: Record<string, unknown>;
}

type EdgeType =
  | 'depends_on'   // Hard prerequisite (blocks until complete)
  | 'informs'      // Soft prerequisite (useful but not required)
  | 'blocks'       // Risk relationship
  | 'enables'      // Completion unlocks possibility
  | 'spawned_by'   // Parent-child relationship
  | 'supersedes';  // Replaces a previous node

/**
 * What the node produced.
 */
type Output =
  | KnowledgeOutput
  | ArtifactOutput
  | CommitmentOutput;

interface KnowledgeOutput {
  type: 'knowledge';
  claims: Claim[];
  findings: Finding[];
  summary: string;
}

interface Finding {
  id: string;
  source: string;
  summary: string;
  relevance: number;
  raw_content?: string;
}

interface ArtifactOutput {
  type: 'artifact';
  path: string;
  artifact_type: string;          // 'code', 'config', 'content', 'model', etc.
  hash: string;                   // Content hash for integrity
  metadata: Record<string, unknown>;
}

interface CommitmentOutput {
  type: 'commitment';
  choice_set: string[];           // Options that were considered
  selected: string;               // The chosen option
  rationale: string;              // Why this choice
  constraints: Record<string, unknown>;  // Binding constraints for downstream
  residual_risks: string[];       // Known risks of this choice
  rollback_plan: string;          // How to reverse if needed
  assumption_ledger: Assumption[];
}

interface Assumption {
  id: string;
  statement: string;
  basis: string;                  // Why we believe this
  expiry?: Timestamp;             // When to re-validate
  invalidation_trigger: string;   // What would make this false
}

type Timestamp = string;  // ISO 8601 format
```

## YAML Representation

For human-readable storage:

```yaml
# Example: Research node
id: tts-capabilities-research
depth: 1
mode: epistemic
deliverable_type: knowledge

goal:
  statement: "Determine TTS providers suitable for children's narration"
  original_question: "What TTS options exist with emotive capabilities?"
  acceptance_criteria:
    - id: options_identified
      description: "At least 3 viable providers identified"
      type: knowledge
      must_pass: true
    - id: quality_assessed
      description: "Audio quality evaluated for each"
      type: validation
      must_pass: true
    - id: cost_compared
      description: "Pricing compared across providers"
      type: metric
      must_pass: false

budget:
  time_ms: 3600000  # 1 hour
  tokens: 50000
  cost_dollars: 5.00

autonomy_gate:
  proceed_threshold: 0.8
  must_pass_criteria: [options_identified, quality_assessed]
  risk_flags: []
  human_required: false

exit_policy:
  on_success: complete
  on_budget_exhausted: degrade
  on_blocked: spawn_child
  degradation_output: "Use ElevenLabs v3 (known working default)"

edges:
  - target: tts-provider-decision
    type: informs
  - target: session-assembly
    type: informs

status: complete

claims:
  - id: claim-001
    proposition: "ElevenLabs v3 produces highest quality emotive narration"
    confidence: 0.85
    evidence_ids: [ev-001, ev-002]
    expiry: "2026-07-01"

evidence:
  - id: ev-001
    type: experiment
    source: "experiments/tts-comparison-2026-01"
    summary: "Blind test showed ElevenLabs preferred 4:1 over Google"
    strength: 0.9
    recency: "2026-01-10"
```

## JSON Schema (for validation)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://gotn.dev/schemas/worknode.json",
  "title": "WorkNode",
  "type": "object",
  "required": ["id", "mode", "goal", "deliverable_type", "status"],
  "properties": {
    "id": { "type": "string" },
    "depth": { "type": "integer", "minimum": 0, "maximum": 10 },
    "mode": { "enum": ["epistemic", "instrumental", "decision"] },
    "deliverable_type": { "enum": ["knowledge", "artifact", "commitment"] },
    "status": {
      "enum": ["pending", "ready", "running", "blocked", "complete",
               "degraded", "escalated", "failed", "cancelled"]
    },
    "goal": {
      "type": "object",
      "required": ["statement", "acceptance_criteria"],
      "properties": {
        "statement": { "type": "string", "minLength": 10 },
        "original_question": { "type": "string" },
        "acceptance_criteria": {
          "type": "array",
          "items": { "$ref": "#/$defs/criterion" },
          "minItems": 1
        }
      }
    },
    "budget": { "$ref": "#/$defs/budget" },
    "autonomy_gate": { "$ref": "#/$defs/autonomy_gate" },
    "exit_policy": { "$ref": "#/$defs/exit_policy" }
  },
  "$defs": {
    "criterion": {
      "type": "object",
      "required": ["id", "description", "type"],
      "properties": {
        "id": { "type": "string" },
        "description": { "type": "string" },
        "type": { "enum": ["knowledge", "artifact", "validation", "metric"] },
        "must_pass": { "type": "boolean", "default": false },
        "satisfied": { "type": "boolean", "default": false },
        "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
      }
    },
    "budget": {
      "type": "object",
      "properties": {
        "time_ms": { "type": "integer", "minimum": 0 },
        "tokens": { "type": "integer", "minimum": 0 },
        "steps": { "type": "integer", "minimum": 0 },
        "cost_dollars": { "type": "number", "minimum": 0 }
      }
    },
    "autonomy_gate": {
      "type": "object",
      "properties": {
        "proceed_threshold": { "type": "number", "minimum": 0, "maximum": 1, "default": 0.8 },
        "must_pass_criteria": { "type": "array", "items": { "type": "string" } },
        "risk_flags": { "type": "array", "items": { "enum": ["safety", "cost", "appropriateness", "legal", "irreversible"] } },
        "human_required": { "type": "boolean", "default": false }
      }
    },
    "exit_policy": {
      "type": "object",
      "properties": {
        "on_success": { "const": "complete" },
        "on_budget_exhausted": { "enum": ["escalate", "degrade", "fail"] },
        "on_blocked": { "enum": ["spawn_child", "escalate", "wait"] },
        "degradation_output": { "type": "string" }
      }
    }
  }
}
```
