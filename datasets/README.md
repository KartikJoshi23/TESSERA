# Datasets (local only)

Everything in this folder except this README is git-ignored.

- `entity_level/{dev,test}/`: entity cards built from real register and alert records (Part 6).
- `message_level/{dev,test}/`: **synthetic** offer messages. Every item carries
  `synthetic: true`, a generator version and a scenario ID. No real user message is ever used.
- `restricted/`: any item that contains DFSA fact values.

The test splits are sealed: they are never used to tune prompts or thresholds. Release only after
the review in `docs/data-governance.md` (VARA's terms bar redistribution; DFSA data needs written
permission).
