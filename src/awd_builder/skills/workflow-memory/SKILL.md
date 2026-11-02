---
name: workflow-memory
description: Manage the user's private, project-local workflow memory. Use before relevant work to recall context, whenever the user asks to remember, recall, forget, compact, export, or import information, and when asking permission to save useful new information.
---

# Workflow Memory

Use this skill as the single source of truth for memory behavior in this workflow. The memory is local to the project and private to the user; it is not part of the workflow's version-controlled configuration.

## Storage

- Store memory only in `.awd-builder/memory/memories.json` at the project root. The scaffold adds this directory to `.gitignore` and initializes an empty store.
- The store is UTF-8 JSON with this shape:

  ```json
  {
    "version": 1,
    "memories": [
      {
        "id": "UUID",
        "created_at": "UTC ISO-8601 timestamp",
        "updated_at": "UTC ISO-8601 timestamp",
        "content": "One concise, self-contained fact or preference",
        "tags": ["optional", "lowercase-tags"]
      }
    ]
  }
  ```

- If the file does not exist, treat memory as empty. Create the directory and valid store only when the user approves a save or explicitly requests an operation that needs it.
- If the file is malformed or has an unsupported version, do not overwrite or try to repair it silently. Tell the user what is wrong and ask how they want to proceed.
- Preserve all unrelated entries and metadata when changing the store. Use a new UUID for each distinct memory and UTC timestamps. Do not store credentials, API keys, or other secrets.

## Consent and automatic recall

1. Before relevant work, inspect the store and recall only entries that help with the current request. Do not expose unrelated memories or dump the full store into the conversation.
2. When a meaningful, potentially reusable preference, decision, project convention, or fact is discovered or discussed, ask the user whether they want it saved. State the proposed memory clearly. Do not save unless the user explicitly agrees; a refusal means do not save it.
3. Do not interrupt for transient details that have no likely future value. Never infer consent from the user's disclosure alone.
4. If the user asks to save something, remember it without asking for a second confirmation. If the request or proposed content is ambiguous, clarify it first.

## Operations

Use the `/memory` command, the user's direct request, or this skill to perform these operations:

- **Remember:** Save only user-approved information. Write a concise, self-contained entry with appropriate tags. Avoid duplicates; if a matching entry exists, update it only when the user asked to revise it.
- **Recall:** With a topic or query, return the relevant entries and their IDs. With no query, list the stored entries. If there are no matches, say so without inventing an answer.
- **Forget:** Remove only the entry or entries the user identifies. If the target is ambiguous, show candidates and ask which to remove. Report what was removed.
- **Compact:** Review entries for redundancy and propose a compacted version that preserves meaning and useful distinctions. Show the proposed changes and get approval before replacing or deleting source entries. Never discard unique information merely to shorten the file.
- **Export:** Export the complete store to a user-specified destination as a portable JSON bundle:

  ```json
  {
    "format": "awd-builder-workflow-memory",
    "version": 1,
    "exported_at": "UTC ISO-8601 timestamp",
    "memories": []
  }
  ```

  Do not export without a destination. Tell the user that the exported file contains private information and may be tracked if saved inside a repository.
- **Import:** Read only a bundle with the expected format and supported version. Merge by ID without deleting existing local entries. Ignore exact duplicate IDs; if an imported ID conflicts with different content, preserve both by assigning the imported entry a fresh UUID. Report how many entries were added, skipped, or had IDs changed. Never replace the local store wholesale.

## Safe file updates

- Validate the complete JSON before writing it. Preserve the top-level version and all unrelated entries.
- For a save or import, write the full updated JSON back to the memory file; do not leave partial JSON behind. If the available file tools support a temporary file and rename, use that pattern.
- Never copy private memory into agent/skill/command files, plans, evals, logs, or other version-controlled files.
