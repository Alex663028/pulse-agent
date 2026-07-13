---
name: research-paper-writing
title: Research Paper Writing Pipeline
description: "Write ML papers for NeurIPS/ICML/ICLR: design -> experiments -> submit. Use when the user wants help drafting or structuring an academic paper."
version: 1.1.0
author: Orchestra Research
license: MIT
dependencies: [semanticscholar, arxiv]
platforms: [linux, macos]
metadata:
  hermes:
    tags: [writing, research, academic]
    category: research
    related_skills: [latex-formatting, literature-review]
    requires_toolsets: [terminal, files]
---

# Research Paper Writing Pipeline

End-to-end assistance for drafting machine-learning papers.

## Steps
1. Clarify contribution and target venue.
2. Draft related-work via Semantic Scholar / arXiv search.
3. Outline method + experiments; verify reproducibility.
4. Write per venue template; export to LaTeX.

## Notes
- Respect double-blind review constraints.
- Keep claims supported by cited evidence.
