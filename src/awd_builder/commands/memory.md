---
description: Remember, recall, forget, compact, export, or import private workflow memory.
---

Manage this workflow's private memory using the `workflow-memory` skill. Follow its consent, storage, validation, and portability rules; do not bypass them.

Arguments: `$ARGUMENTS`

Supported operations:

- `remember <fact>` — save the fact only when the user has explicitly approved it.
- `recall [topic]` — list memory or return relevant entries.
- `forget <memory-id or description>` — remove only the requested entry; clarify if ambiguous.
- `compact` — propose a lossless compaction and get approval before replacing entries.
- `export <destination>` — write a portable JSON bundle to the requested path.
- `import <source>` — validate and merge a portable JSON bundle.

If no operation is provided or it is unclear, explain these options and ask what the user wants. Do not silently save information merely because it appears in the arguments; explicit `/memory remember ...` is consent to save that content.
