# Patch: Fix Validate Story (VS) workflow

> **How to use:** Copy everything below the `---` line into any LLM chat (Claude, GPT, etc.) that has access to your project files. The LLM will create 1 new file and apply 3 replacements to 1 existing file.

## Verification (for humans)

After the LLM applies the patch, test it:

1. Run `/bmad-bmm-create-story` — you should see a **mode selection menu** before any story discovery happens
2. Choose **C** — verify the Create flow works as before (auto-discovers next backlog story)
3. Run `/bmad-bmm-create-story` again, choose **V** — verify it finds `ready-for-dev` stories and lets you pick one to validate

---

# Task: Apply patch to fix Validate Story (VS) workflow

You are applying a patch to the BMad Method `create-story` workflow. Follow the steps below exactly.

## Context (read, do not execute)

The `/bmad-bmm-create-story` command currently always enters Create mode. It should ask the user to choose between Create and Validate mode first. Additionally, the file `_bmad/core/tasks/validate-workflow.xml` is referenced but does not exist.

## Step 1: Create new file `_bmad/core/tasks/validate-workflow.xml`

Create this file with the exact content below:

```xml
<task id="_bmad/core/tasks/validate-workflow.xml" name="Validate Workflow Output">
  <objective>Execute a validation checklist against a workflow output artifact</objective>

  <inputs>
    <input name="target_file" desc="The artifact file to validate (story, PRD, architecture, etc.)" required="true" />
    <input name="checklist" desc="Path to the checklist.md containing validation steps" required="true" />
    <input name="workflow_config" desc="Path to workflow.yaml for variable resolution context" required="false" />
  </inputs>

  <llm critical="true">
    <mandate>Load the checklist file and execute its steps IN EXACT ORDER</mandate>
    <mandate>The checklist is the authority — follow its instructions precisely</mandate>
    <mandate>Load the target file as the primary artifact under review</mandate>
    <mandate>If workflow_config is provided, resolve variables from it for context</mandate>
    <mandate>Present findings interactively as directed by the checklist</mandate>
  </llm>

  <flow>
    <step n="1" title="Load Validation Context">
      <action>Load the target artifact from {target_file}</action>
      <action>Load the checklist from {checklist}</action>
      <check if="{workflow_config} is provided">
        <action>Load workflow config and resolve any variable references the checklist may use</action>
      </check>
    </step>

    <step n="2" title="Execute Checklist">
      <critical>Follow the checklist instructions exactly as written — it contains its own step-by-step process</critical>
      <action>Execute each step defined in the checklist sequentially</action>
      <action>Use subagents or parallel processing where the checklist recommends it</action>
    </step>

    <step n="3" title="Return Results">
      <action>Present validation results as directed by the checklist</action>
      <action>If the checklist includes interactive improvement steps, follow them</action>
    </step>
  </flow>
</task>
```

## Step 2: Modify `_bmad/bmm/workflows/4-implementation/create-story/instructions.xml`

Apply 3 replacements to this file in order. Each replacement shows the exact old text to find and the exact new text to replace it with.

### Replacement 1: Update the ZERO USER INTERVENTION directive

FIND:
```xml
  <critical>🎯 ZERO USER INTERVENTION: Process should be fully automated except for initial epic/story selection or missing documents</critical>

  <step n="1" goal="Determine target story">
```

REPLACE WITH:
```xml
  <critical>🎯 ZERO USER INTERVENTION: After Step 0 mode selection, process should be fully automated except for initial epic/story selection or missing documents</critical>

  <step n="0" goal="MANDATORY mode selection — must execute before anything else" critical="true">
    <critical>🚨 STOP — Do NOT read sprint-status, do NOT discover stories, do NOT load any artifacts until this step completes.
      You MUST present the mode menu below and WAIT for user response. This is NOT optional.</critical>
    <output>
**📋 Story Workflow — Select Mode**

[C] **Create Mode** — Create the next story from backlog (default)
[V] **Validate Mode** — Validate an existing story file before development
    </output>
    <ask>Choose mode [C/V] (default: C):</ask>

    <check if="user chooses V or Validate">
      <action>Set {{workflow_mode}} = "validate"</action>
      <action>GOTO step 7</action>
    </check>

    <!-- Default: Create mode — fall through to step 1 -->
    <action>Set {{workflow_mode}} = "create"</action>
  </step>

  <step n="1" goal="Determine target story">
```

### Replacement 2: Fix the invoke-task path in Step 6

FIND:
```xml
    <invoke-task>Validate against checklist at {installed_path}/checklist.md using _bmad/core/tasks/validate-workflow.xml</invoke-task>
```

REPLACE WITH:
```xml
    <invoke-task>Validate against checklist at {installed_path}/checklist.md using {project-root}/_bmad/core/tasks/validate-workflow.xml</invoke-task>
```

### Replacement 3: Append Step 7 before closing tag

FIND:
```xml
  </step>

</workflow>
```

REPLACE WITH:
```xml
  </step>

  <step n="7" goal="Validate Mode — discover and validate story file">
    <critical>This step only runs when {{workflow_mode}} = "validate"</critical>

    <!-- Discover story to validate -->
    <check if="user provided a story path or number (e.g., 1.3 or 1-3) with their mode selection">
      <action>Resolve to file path in {implementation_artifacts} matching the story number pattern</action>
      <action>Set {{story_file}} to the resolved path</action>
    </check>

    <check if="no story specified by user">
      <check if="sprint status file exists at {{sprint_status}}">
        <action>Load {{sprint_status}} fully</action>
        <action>Find ALL stories with status "ready-for-dev"</action>
        <check if="exactly one ready-for-dev story found">
          <action>Auto-select that story and resolve to file path in {implementation_artifacts}</action>
          <action>Set {{story_file}} to the resolved path</action>
        </check>
        <check if="multiple ready-for-dev stories found">
          <action>List all ready-for-dev stories with their keys</action>
          <ask>Which story to validate? Provide number (e.g., 1.3) or key:</ask>
          <action>Resolve user selection to file path in {implementation_artifacts}</action>
          <action>Set {{story_file}} to the resolved path</action>
        </check>
        <check if="no ready-for-dev stories found">
          <action>List all non-backlog story files in {implementation_artifacts}</action>
          <ask>No ready-for-dev stories. Select a story file to validate, or [q] to quit:</ask>
        </check>
      </check>
      <check if="no sprint status file">
        <action>Scan {implementation_artifacts} for files matching *-*-*.md (story file pattern)</action>
        <action>List found story files</action>
        <ask>Select a story file to validate:</ask>
      </check>
    </check>

    <!-- Load source artifacts for cross-reference validation -->
    <invoke-protocol name="discover_inputs" />

    <!-- Delegate to validation task runner -->
    <invoke-task>Validate {{story_file}} against checklist at {installed_path}/checklist.md using {project-root}/_bmad/core/tasks/validate-workflow.xml</invoke-task>
  </step>

</workflow>
```

## Step 3: Self-check

Confirm all changes were applied:

1. `_bmad/core/tasks/validate-workflow.xml` exists and is valid XML
2. `instructions.xml` contains `<step n="0">` before `<step n="1">`
3. `instructions.xml` Step 6 `invoke-task` path starts with `{project-root}/`
4. `instructions.xml` contains `<step n="7">` before `</workflow>`
5. No other files were changed
