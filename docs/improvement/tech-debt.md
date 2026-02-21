# Technical Debt Registry

Items discovered during code review but deferred from immediate fix.
Each entry tracks: origin story, severity, description, and suggested fix.

## Active Items

### TD-001: graph_repo.get_topic_by_name case-sensitive matching

- **Origin**: Story 2.3 review
- **Severity**: Low
- **Description**: Story 2.3 Dev Notes specify `func.lower(Topic.name) == name.strip().lower()` inside `graph_repo.get_topic_by_name`, but the current implementation uses exact match (`Topic.name == name`). The tool layer compensates with a `get_all_topics` fallback + Python-side `.lower()` comparison, which is functionally correct but inefficient (full table scan) and inconsistent (other callers of `get_topic_by_name` don't get case-insensitive matching).
- **Impact**: Minimal for single-user scenario (few dozen topics). Becomes relevant if topics grow to hundreds or if other callers rely on case-insensitive lookup.
- **Suggested fix**: Change `graph_repo.get_topic_by_name` to use `func.lower(Topic.name) == name.strip().lower()` and remove the fallback loop in `learning_plan_tool.py` (both in `generate_learning_plan` and `get_learning_plan`).
- **Files**: `app/repositories/graph_repo.py:39`, `app/tools/learning_plan_tool.py:207-212`, `app/tools/learning_plan_tool.py:341-346`

## Resolved Items

### TD-002: add_edge has local variable shadowing global _digraph

- **Origin**: Story 2.3 self-review (pre-existing, Story 2.2)
- **Severity**: Low
- **Resolution**: Already fixed — `add_edge` error handler now calls `reset_graph()` (line 193) after `load_graph()` fallback fails. Verified 2026-02-21.
- **Files**: `app/services/graph_service.py:193`
