# /gotn - Goal-Oriented Task Network

Execute and manage GOTN workflow nodes. GOTN provides recursive workflow orchestration with confidence tracking, automatic child spawning, and human-in-the-loop escalation.

## Commands

### Initialize a Goal Tree

```bash
gotn init "Your goal statement here" --mode epistemic
```

Creates a new root node to start a goal tree. Modes:
- `epistemic` - Research and knowledge gathering
- `instrumental` - Building artifacts
- `decision` - Making choices
- `validation` - Verifying outputs

### Run Nodes

```bash
# Run next ready node
gotn run

# Run continuously until blocked or complete
gotn run --continuous

# Run specific node
gotn run --node <node-id>
```

### Check Status

```bash
# Table view
gotn status

# Tree view
gotn status --tree

# Node details
gotn status --node <node-id>
```

### Spawn Child Nodes

```bash
gotn spawn <parent-id> --goal "Research X" --mode epistemic
```

### Resume After Escalation

```bash
gotn resume <node-id> --decision proceed
gotn resume <node-id> --decision cancel
```

### Export Goal Tree

```bash
gotn export --format yaml
gotn export --format json
gotn export --format mermaid --output tree.md
```

### Cancel Nodes

```bash
gotn cancel <node-id>              # Cancel with cascade
gotn cancel <node-id> --no-cascade # Cancel single node
```

## Workflow

1. **Initialize**: `gotn init "Build TTS pipeline" --mode instrumental`
2. **Run**: `gotn run --continuous` (executes until blocked or complete)
3. **Monitor**: `gotn status --tree` (see progress)
4. **Intervene**: If escalated, review and `gotn resume <id> --decision proceed`
5. **Export**: `gotn export --format mermaid` (document the work)

## Node States

| State | Meaning |
|-------|---------|
| pending | Waiting for dependencies |
| ready | Can be executed |
| running | Currently executing |
| blocked | Waiting for child nodes |
| complete | Finished successfully |
| degraded | Finished with reduced quality |
| escalated | Needs human review |
| failed | Error occurred |
| cancelled | Manually cancelled |

## Confidence System

Each node tracks confidence against its acceptance criteria:
- Must-pass criteria weighted 2x
- Confidence updated as claims and evidence accumulate
- Node proceeds when confidence meets threshold (default 80%)
- Low confidence triggers research spawning or escalation

## Example Session

```bash
# Start a research project
gotn init "Determine best TTS provider for children's narration" --mode epistemic

# Run until complete or blocked
gotn run --continuous

# Check what happened
gotn status --tree

# If escalated, review and resume
gotn status --node node-abc123
gotn resume node-abc123 --decision proceed

# Export final result
gotn export --format yaml --output results.yaml
```
